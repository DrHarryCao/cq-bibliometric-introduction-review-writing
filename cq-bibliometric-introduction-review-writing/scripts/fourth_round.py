#!/usr/bin/env python3
"""Fourth-round diagnostics: strategy, citation age, knowledge flow, and KMeans gating."""
from __future__ import annotations

import html
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import adjusted_rand_score, normalized_mutual_info_score


def _empty_status(name: str, status: str, reason: str, **extra) -> dict[str, Any]:
    return {"module": name, "status": status, "reason": reason, **extra}


def kmeans_incremental_diagnostic(assignments: pd.DataFrame, clusters: pd.DataFrame, diagnostics: pd.DataFrame, meta: dict[str, Any]) -> tuple[pd.DataFrame, dict[str, Any]]:
    if assignments.empty or clusters.empty:
        return pd.DataFrame(), _empty_status("kmeans", "disabled", "KMeans skipped or insufficient corpus", writing_allowed=False)
    merged = assignments[["record_id", "topic_id"]].merge(clusters[["record_id", "cluster_id"]], on="record_id")
    if merged.empty: return pd.DataFrame(), _empty_status("kmeans", "disabled", "no shared assignments", writing_allowed=False)
    nmi = float(normalized_mutual_info_score(merged["topic_id"], merged["cluster_id"]))
    ari = float(adjusted_rand_score(merged["topic_id"], merged["cluster_id"]))
    selected = diagnostics[diagnostics["k"] == meta.get("selected_k")]
    row = selected.iloc[0] if not selected.empty else pd.Series(dtype=float)
    silhouette, stability, min_size = float(row.get("silhouette", -1)), float(row.get("stability", 0)), int(row.get("min_cluster_size", 0))
    stable = silhouette >= 0.15 and stability >= 0.75 and min_size >= 3
    incremental = stable and nmi < 0.85
    status = "ready" if incremental else "no-incremental-structure" if stable else "exploratory"
    reason = "stable clusters add heterogeneity information beyond NMF" if incremental else "high overlap with NMF" if stable else "silhouette/stability/minimum-size gate failed"
    cross = merged.groupby(["topic_id", "cluster_id"], as_index=False).size().rename(columns={"size": "documents"})
    return cross, {"module": "kmeans", "status": status, "reason": reason, "writing_allowed": incremental, "role": "heterogeneity-diagnostic-only", "nmi": round(nmi, 6), "ari": round(ari, 6), "silhouette": silhouette, "stability": stability, "min_cluster_size": min_size}


def strategic_map(records: list[dict[str, Any]], topics: pd.DataFrame, assignments: pd.DataFrame, keyword_edges: pd.DataFrame, mode: str = "auto") -> tuple[pd.DataFrame, dict[str, Any]]:
    if mode == "off": return pd.DataFrame(), _empty_status("strategic_map", "disabled", "disabled by user")
    valid_text = sum(bool(f"{r.get('title','')} {r.get('abstract','')}".strip()) for r in records)
    coverage = valid_text / max(len(records), 1)
    sizes = dict(zip(topics.get("topic_id", []), topics.get("documents", [])))
    gates = len(records) >= 50 and len(topics) >= 4 and coverage >= .60 and all(int(v) >= 5 for v in sizes.values())
    if not gates and mode == "auto":
        return pd.DataFrame(), _empty_status("strategic_map", "skipped-insufficient-data", "requires >=50 documents, >=4 topics, >=5 documents/topic and >=60% text coverage", text_coverage=round(coverage, 4))
    term_topic = {}
    for _, row in topics.iterrows():
        for term in str(row.get("top_terms", "")).split("; "): term_topic.setdefault(term.strip().lower(), int(row["topic_id"]))
    internal, external, possible = Counter(), Counter(), Counter()
    for _, edge in keyword_edges.iterrows():
        a, b = str(edge.iloc[0]).lower(), str(edge.iloc[1]).lower(); weight = float(edge.iloc[2])
        ta, tb = term_topic.get(a), term_topic.get(b)
        if not ta or not tb: continue
        if ta == tb: internal[ta] += weight
        else: external[ta] += weight; external[tb] += weight
    terms_per_topic = Counter(term_topic.values())
    rows = []
    for topic_id in sorted(sizes):
        possible_pairs = max(terms_per_topic[topic_id] * (terms_per_topic[topic_id] - 1) / 2, 1)
        rows.append({"topic_id": int(topic_id), "documents": int(sizes[topic_id]), "density": internal[topic_id] / possible_pairs, "centrality": external[topic_id], "text_coverage": coverage})
    frame = pd.DataFrame(rows)
    if frame.empty: return frame, _empty_status("strategic_map", "skipped-insufficient-data", "no topic-term network")
    cmed, dmed = frame["centrality"].median(), frame["density"].median()
    def quadrant(r):
        if r.centrality >= cmed and r.density >= dmed: return "motor"
        if r.centrality >= cmed: return "basic"
        if r.density >= dmed: return "niche"
        return "weakly-developed"
    frame["quadrant"] = frame.apply(quadrant, axis=1)
    # Conservative bootstrap proxy: perturb coordinates within observed sampling error.
    rng = np.random.default_rng(42); agreements = []
    for _, row in frame.iterrows():
        same = 0
        for _ in range(200):
            c = max(0, rng.normal(row.centrality, max(math.sqrt(row.centrality), .01)))
            d = max(0, rng.normal(row.density, max(row.density * .15, .001)))
            q = "motor" if c >= cmed and d >= dmed else "basic" if c >= cmed else "niche" if d >= dmed else "weakly-developed"
            same += q == row.quadrant
        agreements.append(same / 200)
    frame["quadrant_stability"] = agreements
    stable = bool((frame["quadrant_stability"] >= .70).all())
    status = "ready" if gates and stable else "exploratory"
    reason = "all gates passed" if status == "ready" else "quadrant stability below 70%" if gates else "forced despite data-coverage gates"
    return frame, {"module": "strategic_map", "status": status, "reason": reason, "writing_allowed": status == "ready", "text_coverage": round(coverage, 4), "bootstrap_runs": 200, "warning": "weakly-developed never means emerging or declining without temporal evidence"}


YEAR_RE = re.compile(r"(?<!\d)(18\d{2}|19\d{2}|20\d{2})(?!\d)")


def _reference_year(ref: Any) -> int | None:
    if isinstance(ref, dict):
        for key in ("year", "PY", "publication_year", "issued"):
            value = ref.get(key)
            match = YEAR_RE.search(str(value or ""))
            if match: return int(match.group(1))
    match = YEAR_RE.search(str(ref))
    return int(match.group(1)) if match else None


def citation_age_analysis(records: list[dict[str, Any]], assignments: pd.DataFrame, mode: str = "auto") -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    topic = dict(zip(assignments.get("record_id", []), assignments.get("topic_id", [])))
    instances, docs_with_refs, total_refs = [], set(), 0
    for record in records:
        citing_year = int(record.get("year") or 0)
        refs = record.get("references") or []; total_refs += len(refs)
        parsed = False
        for ref in refs:
            year = _reference_year(ref)
            if year and citing_year and year <= citing_year:
                parsed = True; instances.append({"record_id": record["record_id"], "topic_id": topic.get(record["record_id"]), "citing_year": citing_year, "reference_year": year, "citation_age": citing_year - year})
        if parsed: docs_with_refs.add(record["record_id"])
    coverage = len(instances) / max(total_refs, 1)
    gates = len(docs_with_refs) >= 20 and len(instances) >= 100 and coverage >= .60
    if mode == "off": return pd.DataFrame(), pd.DataFrame(), _empty_status("citation_age", "disabled", "disabled by user")
    if not gates and mode == "auto":
        return pd.DataFrame(instances), pd.DataFrame(), _empty_status("citation_age", "skipped-insufficient-data", "requires >=20 citing documents, >=100 reference instances and >=60% year coverage", citing_documents=len(docs_with_refs), parsed_instances=len(instances), year_coverage=round(coverage, 4))
    frame = pd.DataFrame(instances)
    summaries = []
    for label, group in [("all", frame)] + [(f"topic-{int(t)}", g) for t, g in frame.dropna(subset=["topic_id"]).groupby("topic_id")]:
        ages = sorted(group["citation_age"].astype(int).tolist())
        summaries.append({"scope": label, "references": len(ages), "median_age": float(np.median(ages)), "mean_age": float(np.mean(ages)), "synchronous_half_life": float(np.quantile(ages, .5)), "recent_reference_share_5y": round(sum(a <= 5 for a in ages) / len(ages), 6)})
    summary = pd.DataFrame(summaries)
    status = "ready" if gates else "exploratory"
    return frame, summary, {"module": "citation_age", "status": status, "reason": "all gates passed" if gates else "forced despite coverage gates", "writing_allowed": gates, "citing_documents": len(docs_with_refs), "parsed_instances": len(instances), "year_coverage": round(coverage, 4), "role_labels": "annual citation histories required for sustained-classic, short-wave, and rediscovery labels"}


def citation_role_candidates(records: list[dict[str, Any]]) -> pd.DataFrame:
    years = [int(r.get("year") or 0) for r in records if r.get("year")]; latest = max(years or [0]); rows = []
    for record in records:
        year = int(record.get("year") or 0); counts = record.get("citation_counts") or {}
        citations = max([int(float(v)) for v in counts.values() if str(v).replace(".", "", 1).isdigit()] or [0])
        history = {int(y): int(v) for y, v in (record.get("citation_counts_by_year") or {}).items() if str(y).isdigit()}
        role, strength, reason = "unclassified", "insufficient", "insufficient citation evidence"
        if history:
            active = sorted(y for y, value in history.items() if value > 0); recent = sum(v for y, v in history.items() if y >= latest - 2)
            earlier = sum(v for y, v in history.items() if y < latest - 2)
            if year and latest - year >= 8 and len(active) >= 4: role, strength, reason = "sustained-classic", "moderate", "older work with citations across >=4 years"
            if year and latest - year >= 8 and recent > max(earlier, 1): role, strength, reason = "rediscovery-candidate", "moderate", "older work with renewed recent citation activity"
            elif year >= latest - 3 and recent >= max(3, earlier * 2): role, strength, reason = "short-wave-or-frontier", "provisional", "recent work with concentrated recent citations; persistence unknown"
        elif year and year <= latest - 8 and citations > 0: role, strength, reason = "early-high-impact-candidate", "weak", "annual history unavailable"
        elif year and year >= latest - 3: role, strength, reason = "recent-growth-candidate", "weak", "annual history unavailable"
        rows.append({"record_id": record["record_id"], "year": year or None, "citations": citations, "role": role, "classification_strength": strength, "annual_history_available": bool(history), "reason": reason})
    return pd.DataFrame(rows)


def knowledge_flow(citation_edges: pd.DataFrame, assignments: pd.DataFrame, records: list[dict[str, Any]], mode: str = "auto") -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    if mode == "off": return pd.DataFrame(), pd.DataFrame(), _empty_status("knowledge_flow", "disabled", "disabled by user")
    edge_count = len(citation_edges)
    if edge_count < 50 and mode == "auto": return pd.DataFrame(), pd.DataFrame(), _empty_status("knowledge_flow", "skipped-insufficient-data", "requires at least 50 local directed citation edges", local_edges=edge_count, writing_allowed=False)
    topic = dict(zip(assignments.get("record_id", []), assignments.get("topic_id", []))); years = {r["record_id"]: r.get("year") for r in records}
    rows = []
    for _, edge in citation_edges.iterrows():
        source, target = edge["source_id"], edge["target_id"]; a, b = topic.get(target), topic.get(source)
        if not a or not b: continue
        rows.append({"source_topic": int(a), "target_topic": int(b), "citing_record_id": source, "cited_record_id": target, "citing_year": years.get(source), "weight": float(edge.get("weight", 1))})
    detail = pd.DataFrame(rows)
    if detail.empty: return detail, pd.DataFrame(), _empty_status("knowledge_flow", "skipped-insufficient-data", "citation edges do not join topic assignments", local_edges=edge_count, writing_allowed=False)
    sizes = Counter(assignments["topic_id"]); grouped = []
    for (a, b), group in detail.groupby(["source_topic", "target_topic"]):
        citing = group["citing_record_id"].nunique(); raw = group["weight"].sum(); normalized = raw / math.sqrt(max(sizes[a] * sizes[b], 1))
        grouped.append({"source_topic": a, "target_topic": b, "citation_weight": raw, "fractional_flow": normalized, "independent_citing_documents": citing, "writing_eligible": citing >= 3})
    flows = pd.DataFrame(grouped).sort_values("fractional_flow", ascending=False)
    ready = edge_count >= 50 and bool(flows["writing_eligible"].any())
    return detail, flows, {"module": "knowledge_flow", "status": "ready" if ready else "exploratory", "reason": "eligible flows have >=3 independent citing documents" if ready else "forced or no flow reaches independent-document gate", "local_edges": edge_count, "writing_allowed": ready}


def write_flow_html(path: Path, flows: pd.DataFrame) -> None:
    rows = "".join(f"<tr><td>{int(r.source_topic)}</td><td>{int(r.target_topic)}</td><td>{r.fractional_flow:.4f}</td><td>{int(r.independent_citing_documents)}</td></tr>" for _, r in flows.iterrows())
    path.write_text("<!doctype html><meta charset='utf-8'><title>Knowledge flow</title><h1>Cross-topic knowledge flow</h1><p>Exploratory structural evidence; not causal proof.</p><table border='1'><tr><th>Source topic</th><th>Target topic</th><th>Fractional flow</th><th>Independent citing documents</th></tr>" + rows + "</table>", encoding="utf-8")
