#!/usr/bin/env python3
"""Advanced, deterministic topic, burst, network and citation analyses."""
from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from itertools import combinations
from typing import Any

import networkx as nx
import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.decomposition import NMF, TruncatedSVD
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import normalize


STOP = {
    "the", "and", "of", "in", "to", "a", "for", "on", "with", "by", "an", "from", "using", "based",
    "study", "research", "analysis", "results", "effect", "effects", "impact", "examining", "role",
    "与", "及", "的", "在", "基于", "研究", "分析", "影响", "作用", "结果",
}


def modeling_text(record: dict[str, Any]) -> str:
    """Use source-grounded prose only; OpenAlex derived keywords/topics are excluded."""
    return re.sub(r"\s+", " ", f"{record.get('title', '')} {record.get('title', '')} {record.get('abstract', '')}").strip()


def vectorize(records: list[dict[str, Any]]):
    texts = [modeling_text(r) for r in records]
    valid = [i for i, text in enumerate(texts) if text]
    if len(valid) < 3:
        return None, None, valid
    min_df = 2 if len(valid) >= 20 else 1
    vectorizer = TfidfVectorizer(
        max_features=4000, min_df=min_df, max_df=0.97, ngram_range=(1, 3),
        stop_words=list(STOP), token_pattern=r"(?u)\b\w[\w-]+\b", sublinear_tf=True,
    )
    try:
        matrix = vectorizer.fit_transform([texts[i] for i in valid])
    except ValueError:
        vectorizer.set_params(min_df=1, max_df=1.0)
        matrix = vectorizer.fit_transform([texts[i] for i in valid])
    return vectorizer, matrix, valid


def _topic_coherence(component: np.ndarray, binary: np.ndarray, top_n: int = 10) -> float:
    ids = component.argsort()[::-1][:top_n]
    scores = []
    for a, b in combinations(ids, 2):
        both = float(np.logical_and(binary[:, a], binary[:, b]).sum())
        either = float(np.logical_or(binary[:, a], binary[:, b]).sum())
        if either: scores.append(both / either)
    return float(np.mean(scores)) if scores else 0.0


def nmf_topics(records: list[dict[str, Any]], min_k: int = 4, max_k: int = 8, requested_k: int = 0):
    vectorizer, matrix, valid = vectorize(records)
    empty_topics = pd.DataFrame(columns=["topic_id", "top_terms", "documents", "representative_ids"])
    empty_assign = pd.DataFrame(columns=["record_id", "topic_id", "topic_weight", "topic_probability", "topic_entropy", "mixed_topic"])
    empty_diag = pd.DataFrame(columns=["k", "reconstruction_error", "coherence", "stability", "bootstrap_stability", "iterations", "converged", "min_topic_size", "score"])
    if matrix is None or matrix.shape[1] < 2:
        return empty_topics, empty_assign, empty_diag, {"status": "insufficient-corpus", "method": "tfidf-nmf"}
    distinct = int(np.unique(np.round(matrix.toarray(), 12), axis=0).shape[0])
    if distinct < 2:
        return empty_topics, empty_assign, empty_diag, {"status": "insufficient-distinct-documents", "method": "tfidf-nmf"}
    upper = min(max_k, len(valid) - 1, matrix.shape[1] - 1, distinct)
    lower = min(max(2, min_k), upper)
    candidates = [requested_k] if requested_k and lower <= requested_k <= upper else list(range(lower, upper + 1))
    binary = matrix.toarray() > 0
    runs: dict[int, tuple[NMF, np.ndarray]] = {}
    diagnostics = []
    for k in candidates:
        model = NMF(n_components=k, init="nndsvda", random_state=42, max_iter=800)
        weights = model.fit_transform(matrix)
        labels = weights.argmax(axis=1)
        alternative_labels = [NMF(n_components=k, init="nndsvdar", random_state=seed, max_iter=800).fit_transform(matrix).argmax(axis=1) for seed in (73, 101, 151)]
        stability_values = [_adjusted_rand(labels, alt) for alt in alternative_labels]
        stability = float(np.mean(stability_values))
        coherence = float(np.mean([_topic_coherence(c, binary) for c in model.components_]))
        sizes = Counter(labels)
        min_size = min(sizes.values()) if sizes else 0
        recon = float(model.reconstruction_err_) / max(math.sqrt(matrix.shape[0]), 1)
        balance = min_size / max(len(valid) / k, 1)
        score = coherence * 0.45 + stability * 0.35 + min(balance, 1.0) * 0.20 - recon * 0.05
        diagnostics.append({"k": k, "reconstruction_error": round(recon, 6), "coherence": round(coherence, 6), "stability": round(stability, 6), "bootstrap_stability": round(min(stability_values), 6), "iterations": int(model.n_iter_), "converged": bool(model.n_iter_ < model.max_iter), "min_topic_size": min_size, "score": round(score, 6)})
        runs[k] = (model, weights)
    diag = pd.DataFrame(diagnostics)
    selected = int(diag.sort_values(["score", "coherence", "stability"], ascending=False).iloc[0]["k"])
    model, weights = runs[selected]
    features = np.array(vectorizer.get_feature_names_out()); labels = weights.argmax(axis=1)
    topic_rows = []
    for index, component in enumerate(model.components_):
        top = [x for x in features[component.argsort()[::-1]] if x not in STOP][:12]
        local_ids = [i for i, label in enumerate(labels) if label == index]
        representatives = sorted(local_ids, key=lambda i: float(weights[i, index]), reverse=True)[:10]
        topic_rows.append({"topic_id": index + 1, "top_terms": "; ".join(top), "documents": len(local_ids), "representative_ids": "; ".join(records[valid[i]]["record_id"] for i in representatives)})
    assignments = []
    for i in range(len(valid)):
        probabilities = weights[i] / max(float(weights[i].sum()), 1e-12)
        entropy = float(-(probabilities * np.log(probabilities + 1e-12)).sum() / max(math.log(selected), 1e-12))
        assignments.append({"record_id": records[valid[i]]["record_id"], "topic_id": int(labels[i]) + 1, "topic_weight": round(float(weights[i, labels[i]]), 6), "topic_probability": round(float(probabilities[labels[i]]), 6), "topic_entropy": round(entropy, 6), "mixed_topic": entropy >= 0.65})
    chosen_diagnostic = diag[diag["k"] == selected].iloc[0]
    meta = {"status": "ok", "method": "tfidf-nmf", "selected_k": selected, "documents": len(valid), "features": int(matrix.shape[1]), "selection": "coherence+multi-seed-stability+balance+reconstruction", "random_seeds": [42, 73, 101, 151], "soft_membership": True, "selected_converged": bool(chosen_diagnostic["converged"]), "selected_stability": float(chosen_diagnostic["stability"]), "strong_bibliometric_claims_allowed": bool(chosen_diagnostic["converged"] and chosen_diagnostic["stability"] >= 0.75)}
    return pd.DataFrame(topic_rows), pd.DataFrame(assignments), diag, meta


def _adjusted_rand(left: np.ndarray, right: np.ndarray) -> float:
    from sklearn.metrics import adjusted_rand_score
    return float(adjusted_rand_score(left, right))


def document_clusters(records: list[dict[str, Any]], min_k: int = 2, max_k: int = 10):
    _, matrix, valid = vectorize(records)
    empty = pd.DataFrame(columns=["record_id", "cluster_id", "distance"])
    if matrix is None or len(valid) < 4:
        return empty, pd.DataFrame(), pd.DataFrame(), {"status": "insufficient-corpus", "method": "svd-kmeans"}
    distinct = int(np.unique(np.round(matrix.toarray(), 12), axis=0).shape[0])
    if distinct < 2:
        return empty, pd.DataFrame(), pd.DataFrame(), {"status": "insufficient-distinct-documents", "method": "svd-kmeans"}
    dimensions = min(100, matrix.shape[0] - 1, matrix.shape[1] - 1)
    dense = TruncatedSVD(n_components=max(2, dimensions), random_state=42).fit_transform(matrix) if dimensions >= 2 else matrix.toarray()
    dense = normalize(dense)
    upper = min(max_k, len(valid) - 1, distinct)
    candidates = range(max(2, min_k), upper + 1)
    diagnostics, runs = [], {}
    for k in candidates:
        model = KMeans(n_clusters=k, random_state=42, n_init=20).fit(dense)
        labels = model.labels_
        silhouette = silhouette_score(dense, labels, metric="cosine") if len(set(labels)) > 1 else -1.0
        alt = KMeans(n_clusters=k, random_state=73, n_init=20).fit_predict(dense)
        stability = _adjusted_rand(labels, alt)
        sizes = Counter(labels); min_size = min(sizes.values())
        balance = min_size / max(len(valid) / k, 1)
        score = silhouette * 0.55 + stability * 0.30 + min(balance, 1.0) * 0.15
        diagnostics.append({"k": k, "silhouette": round(float(silhouette), 6), "stability": round(stability, 6), "min_cluster_size": min_size, "score": round(score, 6)})
        runs[k] = model
    diag = pd.DataFrame(diagnostics)
    selected = int(diag.sort_values(["score", "silhouette", "stability"], ascending=False).iloc[0]["k"])
    model = runs[selected]; distances = model.transform(dense)
    rows = [{"record_id": records[valid[i]]["record_id"], "cluster_id": int(model.labels_[i]) + 1, "distance": round(float(distances[i, model.labels_[i]]), 6)} for i in range(len(valid))]
    sizes = pd.DataFrame([{"cluster_id": key + 1, "documents": value} for key, value in sorted(Counter(model.labels_).items())])
    return pd.DataFrame(rows), sizes, diag, {"status": "ok", "method": "svd-tfidf-kmeans", "selected_k": selected, "selection": "silhouette+stability+balance"}


def topic_cluster_cross(assignments: pd.DataFrame, clusters: pd.DataFrame) -> pd.DataFrame:
    if assignments.empty or clusters.empty: return pd.DataFrame(columns=["topic_id", "cluster_id", "documents"])
    merged = assignments[["record_id", "topic_id"]].merge(clusters[["record_id", "cluster_id"]], on="record_id")
    return merged.groupby(["topic_id", "cluster_id"], as_index=False).size().rename(columns={"size": "documents"})


def extract_phrases(records: list[dict[str, Any]]) -> tuple[dict[str, set[str]], dict[str, str]]:
    texts = [modeling_text(r) for r in records]
    if not any(texts): return {}, {}
    vectorizer = TfidfVectorizer(ngram_range=(2, 4), min_df=2 if len(records) >= 20 else 1, max_features=5000, stop_words=list(STOP), token_pattern=r"(?u)\b\w[\w-]+\b")
    matrix = vectorizer.fit_transform(texts); terms = vectorizer.get_feature_names_out()
    by_record, examples = {}, {}
    for i, record in enumerate(records):
        indices = matrix[i].indices[np.argsort(matrix[i].data)[::-1][:25]] if matrix[i].nnz else []
        phrases = {str(terms[j]) for j in indices if len(str(terms[j])) >= 5}
        by_record[record["record_id"]] = phrases
        for phrase in phrases:
            if phrase not in examples:
                source_text = f"{record.get('title', '')}. {record.get('abstract', '')}"
                sentence = next((s.strip() for s in re.split(r"(?<=[.!?。！？])\s*", source_text) if phrase.lower() in s.lower()), record.get("title", ""))
                examples[phrase] = sentence[:350]
    return by_record, examples


def extract_context_keywords(records: list[dict[str, Any]]) -> dict[str, set[str]]:
    texts = [modeling_text(r) for r in records]
    if not any(texts): return {}
    vectorizer = TfidfVectorizer(ngram_range=(1, 2), min_df=2 if len(records) >= 20 else 1, max_features=3000, stop_words=list(STOP), token_pattern=r"(?u)\b\w[\w-]+\b")
    matrix = vectorizer.fit_transform(texts); terms = vectorizer.get_feature_names_out(); result = {}
    for i, record in enumerate(records):
        indices = matrix[i].indices[np.argsort(matrix[i].data)[::-1][:20]] if matrix[i].nnz else []
        result[record["record_id"]] = {str(terms[j]) for j in indices if str(terms[j]) not in STOP and len(str(terms[j])) >= 3}
    return result


def _burst_intervals(counts: list[int], totals: list[int], years: list[int], s: float = 2.0, gamma: float = 1.0):
    observations = sum(counts); opportunities = sum(totals)
    if observations < 2 or opportunities <= 0: return []
    p0 = min(max(observations / opportunities, 1e-6), 0.999999); p1 = min(p0 * s, 0.999999)
    transition = gamma * math.log(max(len(years), 2))
    cost = [[0.0, 0.0] for _ in years]; back = [[0, 0] for _ in years]
    def emission(k, n, p):
        return -(k * math.log(p) + (n - k) * math.log(max(1 - p, 1e-9)))
    for state, p in enumerate((p0, p1)): cost[0][state] = emission(counts[0], totals[0], p) + (transition if state else 0)
    for t in range(1, len(years)):
        for state, p in enumerate((p0, p1)):
            options = [cost[t-1][prev] + (transition if prev == 0 and state == 1 else 0) for prev in (0, 1)]
            prev = int(np.argmin(options)); back[t][state] = prev; cost[t][state] = options[prev] + emission(counts[t], totals[t], p)
    state = int(np.argmin(cost[-1])); states = [state]
    for t in range(len(years)-1, 0, -1): state = back[t][state]; states.append(state)
    states.reverse(); intervals, start = [], None
    for i, active in enumerate(states + [0]):
        if active and start is None: start = i
        if not active and start is not None:
            end = i - 1
            gain = sum(max(0.0, emission(counts[j], totals[j], p0) - emission(counts[j], totals[j], p1)) for j in range(start, end + 1))
            intervals.append((years[start], years[end], round(gain, 6), years[start + int(np.argmax(counts[start:end+1]))]))
            start = None
    return intervals


def burst_tables(records: list[dict[str, Any]], keyword_getter, assignments: pd.DataFrame, min_docs: int = 3):
    years = sorted({int(r["year"]) for r in records if r.get("year")})
    if len(years) < 4:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), {"status": "growth-signal-only", "reason": "fewer-than-four-years"}
    totals = Counter(int(r["year"]) for r in records if r.get("year")); rec_topic = dict(zip(assignments.get("record_id", []), assignments.get("topic_id", [])))
    phrase_map, examples = extract_phrases(records)
    extracted_keywords = extract_context_keywords(records)
    def build(kind: str, getter):
        term_year, docs = Counter(), defaultdict(set)
        for r in records:
            if not r.get("year"): continue
            for term in set(getter(r)):
                term = str(term).strip().lower()
                if term: term_year[(term, int(r["year"]))] += 1; docs[term].add(r["record_id"])
        rows = []
        for term, record_ids in docs.items():
            if len(record_ids) < min_docs: continue
            counts = [term_year[(term, y)] for y in years]
            for start, end, strength, peak in _burst_intervals(counts, [totals[y] for y in years], years):
                supporting = sorted(rid for rid in record_ids if start <= int(next(r["year"] for r in records if r["record_id"] == rid)) <= end)
                topics = sorted({int(rec_topic[rid]) for rid in supporting if rid in rec_topic})
                rows.append({"type": kind, "term": term, "start_year": start, "end_year": end, "duration": end-start+1, "strength": strength, "peak_year": peak, "documents": len(record_ids), "supporting_documents": "; ".join(supporting[:20]), "topic_ids": "; ".join(map(str, topics)), "representative_context": examples.get(term, "")})
        return pd.DataFrame(rows).sort_values(["strength", "duration"], ascending=False) if rows else pd.DataFrame(columns=["type", "term", "start_year", "end_year", "duration", "strength", "peak_year", "documents", "supporting_documents", "topic_ids", "representative_context"])
    keyword_bursts = build("keyword", lambda r: set(keyword_getter(r)) | extracted_keywords.get(r["record_id"], set()))
    phrase_bursts = build("phrase", lambda r: phrase_map.get(r["record_id"], set()))
    citation_rows = []
    for r in records:
        history = r.get("citation_counts_by_year") or {}
        if not history: continue
        cyears = sorted(int(y) for y in history if str(y).isdigit())
        if len(cyears) < 4: continue
        values = [int(history.get(str(y), history.get(y, 0)) or 0) for y in cyears]
        baseline = [max(1, sum(values))] * len(values)
        for start, end, strength, peak in _burst_intervals(values, baseline, cyears):
            citation_rows.append({"record_id": r["record_id"], "title": r.get("title", ""), "start_year": start, "end_year": end, "duration": end-start+1, "strength": strength, "peak_year": peak})
    citation_bursts = pd.DataFrame(citation_rows).sort_values("strength", ascending=False) if citation_rows else pd.DataFrame(columns=["record_id", "title", "start_year", "end_year", "duration", "strength", "peak_year"])
    return keyword_bursts, phrase_bursts, citation_bursts, {"status": "ok", "method": "kleinberg-two-state", "years": years, "citation_history_records": sum(bool(r.get("citation_counts_by_year")) for r in records)}


def network_metrics(name: str, edges: pd.DataFrame, source: str, target: str, weight: str, support: dict[str, set[str]] | None = None):
    summary_cols = ["network", "nodes", "edges", "density", "components", "average_clustering", "modularity"]
    metric_cols = ["network", "node", "community", "degree", "weighted_degree", "pagerank", "betweenness", "closeness", "k_core", "constraint", "effective_size", "efficiency", "participation_coefficient", "within_module_z", "core_periphery", "brokerage_role", "supporting_documents"]
    if edges.empty: return pd.DataFrame(columns=summary_cols), pd.DataFrame(columns=metric_cols), pd.DataFrame()
    graph = nx.Graph()
    # Structural-hole measures are cubic on dense graphs. Preserve the
    # strongest evidence-bearing backbone so normal research corpora remain
    # resumable on a laptop, and record the cap in the summary.
    for _, row in edges.sort_values(weight, ascending=False).head(3000).iterrows():
        if row[source] != row[target]: graph.add_edge(str(row[source]), str(row[target]), weight=float(row[weight]))
    if not graph: return pd.DataFrame(columns=summary_cols), pd.DataFrame(columns=metric_cols), pd.DataFrame()
    original_nodes, original_edges = graph.number_of_nodes(), graph.number_of_edges()
    if graph.number_of_nodes() > 250:
        ranked = sorted(graph.degree(weight="weight"), key=lambda x: x[1], reverse=True)[:250]
        graph = graph.subgraph([node for node, _ in ranked]).copy()
    communities = list(nx.community.louvain_communities(graph, weight="weight", seed=42)) if graph.number_of_edges() else [{n} for n in graph]
    community = {node: i + 1 for i, group in enumerate(communities) for node in group}
    modularity = nx.community.modularity(graph, communities, weight="weight") if graph.number_of_edges() else 0.0
    pagerank = nx.pagerank(graph, weight="weight"); between = nx.betweenness_centrality(graph, weight="weight")
    closeness = nx.closeness_centrality(graph); core = nx.core_number(graph)
    constraint = nx.constraint(graph, weight="weight"); effective = nx.effective_size(graph, weight="weight")
    weighted = dict(graph.degree(weight="weight")); degrees = dict(graph.degree())
    rows = []
    for node in graph:
        neighbors = list(graph.neighbors(node)); comm_weights = Counter()
        for other in neighbors: comm_weights[community[other]] += graph[node][other].get("weight", 1.0)
        total = sum(comm_weights.values()); participation = 1 - sum((v/total)**2 for v in comm_weights.values()) if total else 0.0
        peers = [n for n in community if community[n] == community[node]]; peer_values = [weighted[n] for n in peers]
        std = float(np.std(peer_values)); within_z = (weighted[node] - float(np.mean(peer_values))) / std if std else 0.0
        core_label = "core" if core[node] >= max(core.values()) or pagerank[node] >= float(np.quantile(list(pagerank.values()), .75)) else "periphery"
        role = "connector" if participation >= .55 and between[node] > 0 else ("broker" if constraint.get(node, 1) <= .45 and effective.get(node, 0) >= 2 else ("hub" if core_label == "core" else "peripheral"))
        docs = sorted((support or {}).get(node, set()))
        rows.append({"network": name, "node": node, "community": community[node], "degree": degrees[node], "weighted_degree": round(weighted[node], 6), "pagerank": round(pagerank[node], 8), "betweenness": round(between[node], 8), "closeness": round(closeness[node], 8), "k_core": core[node], "constraint": round(constraint.get(node, 1), 8), "effective_size": round(effective.get(node, 0), 8), "efficiency": round(effective.get(node, 0)/max(degrees[node], 1), 8), "participation_coefficient": round(participation, 8), "within_module_z": round(within_z, 8), "core_periphery": core_label, "brokerage_role": role, "supporting_documents": "; ".join(docs[:30])})
    metrics = pd.DataFrame(rows).sort_values(["betweenness", "effective_size"], ascending=False)
    opportunities = []
    brokers = metrics[metrics["brokerage_role"].isin(["connector", "broker"])].head(30)
    for _, left in brokers.iterrows():
        for _, right in brokers.iterrows():
            if left["node"] >= right["node"] or left["community"] == right["community"] or graph.has_edge(left["node"], right["node"]): continue
            left_norm = re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", str(left["node"]).lower())
            right_norm = re.sub(r"[^a-z0-9\u4e00-\u9fff]", "", str(right["node"]).lower())
            if left_norm and right_norm and (left_norm in right_norm or right_norm in left_norm): continue
            score = (left["effective_size"] + right["effective_size"]) * (left["participation_coefficient"] + right["participation_coefficient"] + .1)
            docs = sorted(set(str(left["supporting_documents"]).split("; ")) | set(str(right["supporting_documents"]).split("; ")) - {""})
            opportunities.append({"network": name, "node_a": left["node"], "node_b": right["node"], "community_a": left["community"], "community_b": right["community"], "opportunity_score": round(float(score), 6), "supporting_documents": "; ".join(docs[:30]), "interpretation": "跨社群弱连接候选；需结合内容证据判断是否构成可研究的理论、方法或情境整合。", "research_question": f"{left['node']} 与 {right['node']} 的跨社群连接能否揭示新的机制、边界或方法组合？", "caution": "结构洞机会是探索性结构信号，不等于已经存在内容性研究空白。"})
    summary = pd.DataFrame([{"network": name, "nodes": graph.number_of_nodes(), "edges": graph.number_of_edges(), "original_nodes": original_nodes, "original_edges": original_edges, "backbone_capped": original_nodes > 250 or original_edges > 3000, "density": round(nx.density(graph), 8), "components": nx.number_connected_components(graph), "average_clustering": round(nx.average_clustering(graph, weight="weight"), 8), "modularity": round(modularity, 8)}])
    return summary, metrics, pd.DataFrame(opportunities).sort_values("opportunity_score", ascending=False) if opportunities else pd.DataFrame(columns=["network", "node_a", "node_b", "community_a", "community_b", "opportunity_score", "supporting_documents", "interpretation"])


def citation_impact(records: list[dict[str, Any]]) -> pd.DataFrame:
    current = max([int(r.get("year") or 0) for r in records] or [0]); rows = []
    for r in records:
        cites = max([int(float(v)) for v in (r.get("citation_counts") or {}).values() if str(v).replace(".", "", 1).isdigit()] or [0])
        age = max(1, current - int(r.get("year") or current) + 1)
        rows.append({"record_id": r["record_id"], "title": r.get("title", ""), "year": r.get("year"), "citations": cites, "citations_per_year": round(cites/age, 6), "citation_history_available": bool(r.get("citation_counts_by_year"))})
    frame = pd.DataFrame(rows)
    if not frame.empty: frame["year_normalized_percentile"] = frame.groupby("year")["citations"].rank(pct=True).round(6)
    return frame.sort_values(["year_normalized_percentile", "citations_per_year"], ascending=False)
