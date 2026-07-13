#!/usr/bin/env python3
"""Deterministic bibliometric analysis adapted from the user's v6.2 workflow."""
from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import networkx as nx
import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.decomposition import NMF
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import silhouette_score

from common import as_list, normalize_doi, normalize_title, write_json
from advanced_analysis import (
    burst_tables, citation_impact, document_clusters, extract_context_keywords, modeling_text, network_metrics,
    nmf_topics, topic_cluster_cross,
)
from fourth_round import citation_age_analysis, citation_role_candidates, kmeans_incremental_diagnostic, knowledge_flow, strategic_map, write_flow_html


STOP = {"the", "and", "of", "in", "to", "a", "for", "on", "with", "by", "an", "from", "using", "based", "study", "research", "analysis", "与", "及", "的", "在", "基于", "研究", "分析"}


def citations(record: dict[str, Any]) -> int:
    values = []
    for value in (record.get("citation_counts") or {}).values():
        try: values.append(int(float(value)))
        except (TypeError, ValueError): pass
    return max(values or [0])


def author_names(record: dict[str, Any]) -> list[str]:
    return [a.get("name", "") if isinstance(a, dict) else str(a) for a in record.get("authors") or []]


def keyword_list(record: dict[str, Any], include_topics: bool = False) -> list[str]:
    terms = list(record.get("keywords") or [])
    # OpenAlex keywords are machine-derived. Remove them unless the same record
    # also supplies a non-OpenAlex keyword field through an imported database.
    oa_keywords = {
        str(x.get("display_name", "")).strip().lower()
        for x in (((record.get("raw") or {}).get("openalex") or {}).get("keywords") or [])
        if isinstance(x, dict) and x.get("display_name")
    }
    if oa_keywords:
        terms = [term for term in terms if str(term).strip().lower() not in oa_keywords]
    # OpenAlex topic labels are useful metadata, but are automatically assigned
    # and can inject unrelated hierarchy labels (for example, physics) into a
    # small field-specific corpus. Keep them out of text modeling by default.
    if include_topics:
        for topic in record.get("topics") or []:
            name = topic.get("name") or topic.get("display_name") if isinstance(topic, dict) else str(topic)
            if name: terms.append(name)
    return list(dict.fromkeys(re.sub(r"\s+", " ", str(t).strip().lower()) for t in terms if str(t).strip()))


def corpus_text(record: dict[str, Any]) -> str:
    return modeling_text(record)


def edge_frame(counter: Counter, a: str, b: str, weight: str) -> pd.DataFrame:
    return pd.DataFrame([{a: x, b: y, weight: n} for (x, y), n in counter.items()]).sort_values(weight, ascending=False) if counter else pd.DataFrame(columns=[a, b, weight])


def cooccurrence(records: list[dict[str, Any]], getter, a: str, b: str, weight: str, cap: int = 30, counting: str = "full") -> pd.DataFrame:
    edges = Counter()
    for r in records:
        terms = list(dict.fromkeys(x for x in getter(r) if x))[:cap]
        contribution = 1.0 if counting == "full" else 1.0 / max(len(terms) - 1, 1)
        for i, left in enumerate(terms):
            for right in terms[i + 1:]: edges[tuple(sorted((left, right)))] += contribution
    return edge_frame(edges, a, b, weight)


def year_stats(records: list[dict[str, Any]]) -> pd.DataFrame:
    counts = Counter(r.get("year") for r in records if r.get("year"))
    cites = Counter()
    for r in records:
        if r.get("year"): cites[r["year"]] += citations(r)
    return pd.DataFrame([{"year": y, "documents": counts[y], "citations": cites[y]} for y in sorted(counts)])


def term_stats(records: list[dict[str, Any]]) -> pd.DataFrame:
    counts, cites, recent = Counter(), Counter(), Counter()
    max_year = max([r.get("year") or 0 for r in records] or [0]); cutoff = max_year - 2
    for r in records:
        for term in keyword_list(r):
            counts[term] += 1; cites[term] += citations(r)
            if (r.get("year") or 0) >= cutoff: recent[term] += 1
    rows = []
    total_recent = sum(1 for r in records if (r.get("year") or 0) >= cutoff)
    for term, count in counts.items():
        prior = count - recent[term]
        burst = recent[term] / max(total_recent, 1) - prior / max(len(records) - total_recent, 1)
        rows.append({"term": term, "documents": count, "citations": cites[term], "recent_documents": recent[term], "burst_score": round(burst, 6)})
    return pd.DataFrame(rows).sort_values(["documents", "citations"], ascending=False) if rows else pd.DataFrame(columns=["term", "documents", "citations", "recent_documents", "burst_score"])


def topic_model(records: list[dict[str, Any]], requested_k: int = 0, min_k: int = 4, max_k: int = 8) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    topics, assignments, diagnostics, meta = nmf_topics(records, min_k, max_k, requested_k)
    meta["diagnostics"] = diagnostics.to_dict("records")
    return topics, assignments, meta


def citation_network(records: list[dict[str, Any]]) -> tuple[pd.DataFrame, pd.DataFrame]:
    doi_map = {normalize_doi((r.get("ids") or {}).get("doi")): r["record_id"] for r in records if normalize_doi((r.get("ids") or {}).get("doi"))}
    oa_map = {str((r.get("ids") or {}).get("openalex", "")).rsplit("/", 1)[-1]: r["record_id"] for r in records if (r.get("ids") or {}).get("openalex")}
    edges = Counter()
    for r in records:
        for ref in r.get("references") or []:
            target = ""
            if isinstance(ref, dict):
                target = doi_map.get(normalize_doi(ref.get("DOI") or ref.get("doi")), "")
                raw = jsonish(ref)
            else: raw = str(ref)
            if not target:
                doi = re.search(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", raw, flags=re.I)
                if doi: target = doi_map.get(normalize_doi(doi.group()), "")
            if not target:
                oa = re.search(r"W\d+", raw); target = oa_map.get(oa.group(), "") if oa else ""
            if target and target != r["record_id"]: edges[(r["record_id"], target)] += 1
    frame = edge_frame(edges, "source_id", "target_id", "weight")
    graph = nx.DiGraph()
    for _, row in frame.iterrows(): graph.add_edge(row["source_id"], row["target_id"], weight=row["weight"])
    metrics = []
    if graph:
        between = nx.betweenness_centrality(graph)
        for node in graph.nodes:
            metrics.append({"record_id": node, "local_citations": int(graph.in_degree(node, weight="weight")), "references_in_corpus": int(graph.out_degree(node, weight="weight")), "betweenness": round(between.get(node, 0), 6)})
    return frame, pd.DataFrame(metrics)


def reference_key(ref: Any) -> str:
    raw = jsonish(ref)
    doi = re.search(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", raw, flags=re.I)
    if doi: return "doi:" + normalize_doi(doi.group())
    oa = re.search(r"W\d+", raw)
    if oa: return "openalex:" + oa.group()
    return "raw:" + normalize_title(raw)[:180] if normalize_title(raw) else ""


def citation_relation_tables(records: list[dict[str, Any]]) -> tuple[pd.DataFrame, pd.DataFrame]:
    refsets = {r["record_id"]: {reference_key(x) for x in r.get("references") or [] if reference_key(x)} for r in records}
    cocited = Counter()
    for refs in refsets.values():
        ordered = sorted(refs)[:80]
        for i, left in enumerate(ordered):
            for right in ordered[i + 1:]: cocited[(left, right)] += 1
    coupling = Counter(); ids = list(refsets)
    for i, left in enumerate(ids):
        if not refsets[left]: continue
        for right in ids[i + 1:]:
            shared = len(refsets[left] & refsets[right])
            if shared: coupling[(left, right)] = shared
    return edge_frame(cocited, "reference_a", "reference_b", "co_citations"), edge_frame(coupling, "record_a", "record_b", "shared_references")


def topic_time_tables(records: list[dict[str, Any]], assignments: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    rec_year = {r["record_id"]: r.get("year") for r in records}
    rows = []
    for _, row in assignments.iterrows():
        year = rec_year.get(row["record_id"])
        if year: rows.append({"year": int(year), "topic_id": int(row["topic_id"]), "documents": 1})
    trends = pd.DataFrame(rows)
    if trends.empty: return pd.DataFrame(columns=["year", "topic_id", "documents"]), pd.DataFrame(), pd.DataFrame()
    trends = trends.groupby(["year", "topic_id"], as_index=False)["documents"].sum()
    max_year = int(trends["year"].max()); life = []
    for topic_id, group in trends.groupby("topic_id"):
        recent = int(group[group["year"] >= max_year - 2]["documents"].sum()); prior = int(group[group["year"] < max_year - 2]["documents"].sum())
        stage = "emerging" if recent >= max(2, prior) else ("declining" if recent == 0 else "established")
        life.append({"topic_id": int(topic_id), "first_year": int(group["year"].min()), "last_year": int(group["year"].max()), "recent_documents": recent, "prior_documents": prior, "stage": stage})
    periods = sorted({(int(y) // 5) * 5 for y in trends["year"]}); evolution = []
    for left, right in zip(periods, periods[1:]):
        for topic_id in sorted(trends["topic_id"].unique()):
            a = int(trends[(trends["topic_id"] == topic_id) & (trends["year"].between(left, left + 4))]["documents"].sum())
            b = int(trends[(trends["topic_id"] == topic_id) & (trends["year"].between(right, right + 4))]["documents"].sum())
            if a and b: evolution.append({"source_period": f"{left}-{left+4}", "target_period": f"{right}-{right+4}", "topic_id": int(topic_id), "flow_weight": min(a, b), "source_documents": a, "target_documents": b})
    return trends, pd.DataFrame(life), pd.DataFrame(evolution)


def frontier_table(records: list[dict[str, Any]], assignments: pd.DataFrame) -> pd.DataFrame:
    weight = dict(zip(assignments.get("record_id", []), assignments.get("topic_weight", [])))
    max_year = max([r.get("year") or 0 for r in records] or [0]); rows = []
    for r in records:
        recency = max(0, 1 - (max_year - (r.get("year") or max_year)) / 5)
        impact = math.log1p(citations(r))
        novelty = float(weight.get(r["record_id"], 0))
        rows.append({"record_id": r["record_id"], "title": r["title"], "year": r.get("year"), "citations": citations(r), "recency_score": round(recency, 4), "topic_signal": round(novelty, 4), "frontier_score": round(recency * 2 + novelty + impact / 5, 4)})
    return pd.DataFrame(rows).sort_values("frontier_score", ascending=False)


def jsonish(value: Any) -> str:
    import json
    return json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value)


def gap_candidates(topics: pd.DataFrame, assignments: pd.DataFrame, records: list[dict[str, Any]], terms: pd.DataFrame) -> pd.DataFrame:
    rec_map = {r["record_id"]: r for r in records}; rows = []
    for _, topic in topics.iterrows():
        ids = assignments[assignments["topic_id"] == topic["topic_id"]]["record_id"].tolist()
        docs = [rec_map[x] for x in ids if x in rec_map]; years = [r["year"] for r in docs if r.get("year")]
        fulltext = sum(bool((r.get("fulltext") or {}).get("local_path")) for r in docs)
        evidence = "low" if len(docs) < 5 or fulltext == 0 else "medium"
        rows.append({"gap_id": f"G{int(topic['topic_id']):03d}", "topic_id": int(topic["topic_id"]), "candidate_gap": f"主题“{topic['top_terms']}”的对象、方法、情境或机制边界仍需进一步核查。", "documents": len(docs), "year_min": min(years) if years else None, "year_max": max(years) if years else None, "fulltext_documents": fulltext, "evidence_strength": evidence, "warning": "计量信号不是内容性研究空白；写作前必须用全文/摘要证据卡验证。"})
    return pd.DataFrame(rows)


def df_to_md(title: str, frame: pd.DataFrame, limit: int | None = None) -> str:
    shown = frame.head(limit) if limit else frame
    return f"# {title}\n\n- rows_total: {len(frame)}\n\n" + (shown.to_markdown(index=False) if not shown.empty else "_无数据_") + "\n"


def save_figures(root: Path, outputs: dict[str, pd.DataFrame]) -> None:
    try:
        import matplotlib; matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception: return
    figdir = root / "04_analysis/figures"; figdir.mkdir(parents=True, exist_ok=True)
    configs = [("year_stats", "year", "documents", "Publications by year"), ("term_stats", "term", "documents", "Top terms")]
    for key, x, y, title in configs:
        frame = outputs.get(key, pd.DataFrame()).head(25)
        if frame.empty: continue
        fig, ax = plt.subplots(figsize=(10, 6))
        if key == "year_stats": ax.plot(frame[x], frame[y], marker="o")
        else: ax.barh(frame[x][::-1], frame[y][::-1])
        ax.set_title(title); fig.tight_layout()
        for ext in ("png", "svg"): fig.savefig(figdir / f"{key}.{ext}", dpi=180)
        plt.close(fig)


def analyze(root: Path, records: list[dict[str, Any]], topic_count: int = 0, nmf_min_k: int = 4, nmf_max_k: int = 8, cluster_min_k: int = 2, cluster_max_k: int = 10, burst_min_docs: int = 3, counting: str = "fractional", skip_kmeans: bool = False, strategic_mode: str = "auto", citation_age_mode: str = "auto", knowledge_flow_mode: str = "auto") -> dict[str, Any]:
    years = year_stats(records); terms = term_stats(records)
    topics, assignments, nmf_diagnostics, model = nmf_topics(records, nmf_min_k, nmf_max_k, topic_count)
    if skip_kmeans:
        clusters, cluster_sizes, cluster_diagnostics, cluster_model = pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), {"status": "disabled", "role": "heterogeneity-diagnostic-only"}
    else:
        clusters, cluster_sizes, cluster_diagnostics, cluster_model = document_clusters(records, cluster_min_k, cluster_max_k)
    topic_cluster = topic_cluster_cross(assignments, clusters)
    kmeans_cross, kmeans_gate = kmeans_incremental_diagnostic(assignments, clusters, cluster_diagnostics, cluster_model)
    context_keywords = extract_context_keywords(records)
    analysis_keywords = lambda record: list(set(keyword_list(record)) | context_keywords.get(record["record_id"], set()))
    keyword_edges = cooccurrence(records, analysis_keywords, "term_a", "term_b", "cooccurrence", counting=counting)
    author_edges = cooccurrence(records, author_names, "author_a", "author_b", "collaborations", cap=100, counting=counting)
    citation_edges, citation_metrics = citation_network(records)
    cocitation_edges, coupling_edges = citation_relation_tables(records)
    topic_trends, topic_lifecycle, topic_evolution = topic_time_tables(records, assignments)
    frontier = frontier_table(records, assignments)
    gaps = gap_candidates(topics, assignments, records, terms)
    top_cited = pd.DataFrame([{"record_id": r["record_id"], "title": r["title"], "year": r["year"], "citations": citations(r)} for r in records]).sort_values("citations", ascending=False)
    citation_impact_table = citation_impact(records)
    strategic_table, strategic_status = strategic_map(records, topics, assignments, keyword_edges, strategic_mode)
    citation_age_instances, citation_age_summary, citation_age_status = citation_age_analysis(records, assignments, citation_age_mode)
    citation_roles = citation_role_candidates(records)
    flow_detail, flow_summary, flow_status = knowledge_flow(citation_edges, assignments, records, knowledge_flow_mode)
    overview = pd.DataFrame([
        {"metric": "records", "value": len(records)}, {"metric": "with_abstract", "value": sum(bool(r.get("abstract")) for r in records)},
        {"metric": "with_doi", "value": sum(bool((r.get("ids") or {}).get("doi")) for r in records)}, {"metric": "oa_records", "value": sum(bool((r.get("oa") or {}).get("is_oa")) for r in records)},
        {"metric": "year_min", "value": min([r["year"] for r in records if r.get("year")] or [""])}, {"metric": "year_max", "value": max([r["year"] for r in records if r.get("year")] or [""])},
    ])
    keyword_bursts, phrase_bursts, citation_bursts, burst_meta = burst_tables(records, keyword_list, assignments, burst_min_docs)
    hotspots = keyword_bursts.copy()
    keyword_support, author_support = defaultdict(set), defaultdict(set)
    for record in records:
        for term in analysis_keywords(record): keyword_support[term].add(record["record_id"])
        for author in author_names(record): author_support[author].add(record["record_id"])
    record_support = {r["record_id"]: {r["record_id"]} for r in records}
    network_parts = [
        network_metrics("keyword_cooccurrence", keyword_edges, "term_a", "term_b", "cooccurrence", keyword_support),
        network_metrics("author_collaboration", author_edges, "author_a", "author_b", "collaborations", author_support),
        network_metrics("local_citation", citation_edges, "source_id", "target_id", "weight", record_support),
        network_metrics("co_citation", cocitation_edges, "reference_a", "reference_b", "co_citations"),
        network_metrics("bibliographic_coupling", coupling_edges, "record_a", "record_b", "shared_references", record_support),
    ]
    summary_parts = [x[0] for x in network_parts if not x[0].empty]
    node_parts = [x[1] for x in network_parts if not x[1].empty]
    hole_parts = [x[2] for x in network_parts if not x[2].empty]
    network_summary = pd.concat(summary_parts, ignore_index=True) if summary_parts else pd.DataFrame()
    network_nodes = pd.concat(node_parts, ignore_index=True) if node_parts else pd.DataFrame()
    structural_holes = pd.concat(hole_parts, ignore_index=True) if hole_parts else pd.DataFrame()
    network_claim_rows = []
    for network, group in network_nodes.groupby("network") if not network_nodes.empty else []:
        for _, row in group.sort_values(["betweenness", "effective_size"], ascending=False).head(10).iterrows():
            network_claim_rows.append({"network": network, "node": row["node"], "community": row["community"], "brokerage_role": row["brokerage_role"], "betweenness": row["betweenness"], "constraint": row["constraint"], "effective_size": row["effective_size"], "supporting_documents": row["supporting_documents"], "writing_interpretation": "该节点连接多个局部知识群，可用于讨论领域整合或知识扩散；需由支持文献核查具体含义。", "research_question": "该桥接位置是否对应尚未充分整合的理论、方法或研究情境？", "caution": "网络位置是结构信号，不代表理论质量、因果重要性或研究结论。"})
    network_claims = pd.DataFrame(network_claim_rows)
    sensitivity_rows = []
    for network, frame, weight in (("keyword_cooccurrence", keyword_edges, "cooccurrence"), ("author_collaboration", author_edges, "collaborations"), ("co_citation", cocitation_edges, "co_citations"), ("bibliographic_coupling", coupling_edges, "shared_references")):
        for threshold in (1, 2, 3):
            sensitivity_rows.append({"network": network, "minimum_weight": threshold, "edges_retained": int((frame[weight] >= threshold).sum()) if not frame.empty else 0, "counting": counting})
    network_sensitivity = pd.DataFrame(sensitivity_rows)
    outputs = {"overview": overview, "year_stats": years, "term_stats": terms, "hotspots": hotspots, "keyword_bursts": keyword_bursts, "phrase_bursts": phrase_bursts, "citation_bursts": citation_bursts, "topics": topics, "topic_assignments": assignments, "nmf_diagnostics": nmf_diagnostics, "document_clusters": clusters, "cluster_sizes": cluster_sizes, "cluster_diagnostics": cluster_diagnostics, "topic_cluster_cross": topic_cluster, "topic_trends": topic_trends, "topic_lifecycle": topic_lifecycle, "topic_evolution": topic_evolution, "keyword_edges": keyword_edges, "author_edges": author_edges, "citation_edges": citation_edges, "citation_metrics": citation_metrics, "co_citation_edges": cocitation_edges, "bibliographic_coupling_edges": coupling_edges, "network_summary": network_summary, "network_nodes": network_nodes, "network_writing_claims": network_claims, "structural_hole_opportunities": structural_holes, "citation_impact": citation_impact_table, "frontier_signals": frontier, "top_cited": top_cited, "gap_candidates": gaps}
    outputs["network_sensitivity"] = network_sensitivity
    outputs.update({"kmeans_incremental_cross": kmeans_cross, "strategic_map": strategic_table, "citation_age_instances": citation_age_instances, "citation_age_summary": citation_age_summary, "citation_role_candidates": citation_roles, "knowledge_flow_detail": flow_detail, "knowledge_flow_summary": flow_summary})
    table_dir, md_dir = root / "04_analysis/tables", root / "04_analysis/markdown"
    table_dir.mkdir(parents=True, exist_ok=True); md_dir.mkdir(parents=True, exist_ok=True)
    excel_max_data_rows = 1_048_575  # Excel's row limit minus the header row.
    excel_embed_limit = 100_000  # Keep the workbook portable; CSV retains all rows.
    with pd.ExcelWriter(table_dir / "bibliometric_analysis.xlsx") as writer:
        for name, frame in outputs.items():
            frame.to_csv(table_dir / f"{name}.csv", index=False, encoding="utf-8-sig")
            if len(frame) > excel_embed_limit:
                pd.DataFrame([{
                    "rows_total": len(frame),
                    "authoritative_file": f"{name}.csv",
                    "excel_status": "not embedded: large table; no data excluded from CSV",
                }]).to_excel(writer, sheet_name=name[:31], index=False)
            else:
                chunks = max(1, math.ceil(len(frame) / excel_max_data_rows))
                for part in range(chunks):
                    start, stop = part * excel_max_data_rows, (part + 1) * excel_max_data_rows
                    suffix = f"_{part + 1}" if chunks > 1 else ""
                    sheet_name = f"{name[:31 - len(suffix)]}{suffix}"
                    frame.iloc[start:stop].to_excel(writer, sheet_name=sheet_name, index=False)
            # CSV remains the complete authoritative table. Markdown is a readable
            # preview for very large edge lists so a million-row network does not
            # create an unusable evidence file.
            md_limit = 5_000 if len(frame) > 5_000 else None
            (md_dir / f"{name}.md").write_text(df_to_md(name, frame, md_limit), encoding="utf-8")
    write_json(root / "04_analysis/analysis_parameters.json", {"source": "adapted from 文献计量和综述v6.2.py", "topic_model": model, "cluster_model": cluster_model, "burst_model": burst_meta, "record_count": len(records), "topic_count_requested": topic_count, "nmf_k_range": [nmf_min_k, nmf_max_k], "cluster_k_range": [cluster_min_k, cluster_max_k], "derived_openalex_keywords_in_topic_model": False})
    parameters = __import__("json").loads((root / "04_analysis/analysis_parameters.json").read_text(encoding="utf-8"))
    parameters.update({"network_counting": counting, "network_threshold_sensitivity": [1, 2, 3], "causal_interpretation_allowed": False})
    parameters.update({"topic_structure_source": "NMF-only", "kmeans_role": "heterogeneity-diagnostic-only", "advanced_modules": {"kmeans": kmeans_gate, "strategic_map": strategic_status, "citation_age": citation_age_status, "knowledge_flow": flow_status}, "embedding_used": False})
    write_json(root / "04_analysis/analysis_parameters.json", parameters)
    write_json(root / "04_analysis/advanced_module_status.json", parameters["advanced_modules"])
    if not flow_summary.empty: write_flow_html(root / "04_analysis/figures/knowledge_flow.html", flow_summary)
    save_figures(root, outputs)
    return {"record_count": len(records), "tables": {k: len(v) for k, v in outputs.items()}, "topic_model": model, "cluster_model": cluster_model, "burst_model": burst_meta, "advanced_modules": parameters["advanced_modules"], "embedding_used": False}
