#!/usr/bin/env python3
"""Build progressive evidence artifacts and validate review traceability."""
from __future__ import annotations

import json
import math
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

import pandas as pd

from common import load_jsonl, normalize_title, read_json, write_json, write_jsonl
from science import quality_appraisal
from semantic import validate_semantic


CARD_FIELDS = ["研究问题", "理论与概念", "研究设计", "样本与情境", "方法", "主要发现", "机制", "边界条件", "局限", "与当前课题的关系", "反向或矛盾证据"]


def citation_minimum(total: int) -> int:
    if total <= 100:
        return math.ceil(total * 0.60)
    legacy_floor = math.ceil(max(40, math.sqrt(total) * 5))
    return min(total, max(legacy_floor, min(120, math.ceil(total * 0.60))))


def writing_eligible_records(root: Path, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return the auditable denominator for prose citation coverage.

    In an ``all`` corpus, every record remains in bibliometric analysis, but
    completed semantic screening may establish that homonyms and peripheral
    records cannot support the focal review.  Such records must not inflate a
    prose-citation quota that could only be met by citation stuffing.
    """
    manifest = read_json(root / "manifest.json", {})
    if manifest.get("corpus_mode") != "all":
        return records
    semantic_dir = root / "05_evidence/semantic/extractions"
    screened: dict[str, str] = {}
    for path in semantic_dir.glob("*.json") if semantic_dir.exists() else []:
        item = read_json(path, {})
        if item.get("host_review_status") == "completed":
            screened[str(item.get("record_id"))] = str(item.get("relevance") or "").lower()
    if not screened:
        return records
    blocked = ("peripheral", "irrelevant", "homonym", "prohibit")
    eligible_ids = {rid for rid, label in screened.items() if label and not any(token in label for token in blocked)}
    # Use a semantic denominator only after every planned citation candidate
    # has been screened; otherwise retain the conservative full-corpus rule.
    targets = {x.get("record_id") for x in load_jsonl(root / "05_evidence/citation_coverage_targets.jsonl")}
    if targets and not targets.issubset(set(screened)):
        return records
    return [record for record in records if record.get("record_id") in eligible_ids]


def topic_citation_quotas(topic_sizes: dict[int, int], total: int) -> dict[int, int]:
    minimum = citation_minimum(total)
    return {
        topic: min(size, max(3, math.ceil(size * .40)) if total <= 100 else max(3, math.ceil(minimum * size / max(total, 1))))
        for topic, size in topic_sizes.items()
    }


def cited_records(text: str, ledger: list[dict[str, Any]]) -> set[str]:
    claim_ids = claim_ids_in_text(text)
    direct = set(re.findall(r"\bR[0-9a-f]{14}\b", text))
    return direct | {rid for claim in ledger if claim.get("claim_id") in claim_ids for rid in claim.get("record_ids") or []}


def claim_ids_in_text(text: str) -> set[str]:
    ids = set(re.findall(r"\bC\d{4}\b", text))
    for left, right in re.findall(r"C(\d{4})\s*[–—-]\s*C(\d{4})", text):
        start, end = int(left), int(right)
        if 0 <= end - start <= 100: ids.update(f"C{x:04d}" for x in range(start, end + 1))
    return ids


def split_embedded_references(text: str) -> tuple[str, str]:
    match = re.search(r"(?m)^##\s+参考文献.*$", text)
    return (text[:match.start()].rstrip(), text[match.start():].strip()) if match else (text.rstrip(), "")


def embedded_reference_ids(reference_text: str) -> list[str]:
    return re.findall(r"<!--\s*record:(R[0-9a-f]{14})\s*-->", reference_text)


def embedded_social_source_ids(reference_text: str) -> list[str]:
    return re.findall(r"<!--\s*source:(SCTX-\d{3,})\s*-->", reference_text)


def approved_review_headings(root: Path) -> list[str]:
    outline = root / "06_review/outline.md"
    if not outline.exists(): return []
    return [re.sub(r"^\d+[.、]\s*", "", x).strip() for x in re.findall(r"(?m)^##\s+(.+?)\s*$", outline.read_text(encoding="utf-8"))]


def _social_sources(root: Path) -> list[dict[str, Any]]:
    rows = load_jsonl(root / "06_review/social_context_sources.jsonl")
    for index, row in enumerate(rows, 1):
        row.setdefault("source_id", f"SCTX-{index:03d}")
    return rows


def _social_apa(row: dict[str, Any]) -> str:
    author = str(row.get("citation_author") or row.get("source_name") or "机构作者").strip()
    year = str(row.get("publication_date") or "n.d.")[:4]
    title = str(row.get("title") or "网络资料").strip().rstrip(".。")
    url = str(row.get("url") or "").strip()
    retrieved = str(row.get("retrieved_at") or "").strip()
    access = f" 检索日期：{retrieved}。" if retrieved else ""
    return re.sub(r"\s+", " ", f"{author}. ({year}). {title}. {url}.{access}").replace("..", ".").strip()


def sync_references(root: Path, document: str = "review", draft_path: Path | None = None) -> dict[str, Any]:
    if document not in {"review", "introduction"}:
        raise ValueError("document 必须是 review 或 introduction")
    default = root / ("06_review/review_draft.md" if document == "review" else "06_review/ssci_introduction_audit.md")
    path = draft_path or default
    if not path.exists(): raise RuntimeError(f"{document} 正文不存在：{path}")
    text = path.read_text(encoding="utf-8"); body, _ = split_embedded_references(text)
    ledger = load_jsonl(root / "05_evidence/claim_ledger.jsonl")
    used = cited_records(body, ledger)
    registry = {row.get("record_id"): row for row in load_jsonl(root / "05_evidence/reference_registry.jsonl")}
    missing = sorted(used - set(registry))
    if missing: raise RuntimeError(f"参考文献注册表缺少正文引用记录：{missing}")
    rows = sorted((registry[rid] for rid in used), key=lambda row: str(row.get("apa") or "").casefold())
    social_rows = _social_sources(root) if document == "introduction" else []
    explicit_social = set(re.findall(r"\bSCTX-\d{3,}\b", body))
    # Backward compatibility: registered introduction context sources were
    # created specifically for the first paragraph before source IDs existed.
    used_social = explicit_social or {row["source_id"] for row in social_rows}
    selected_social = [row for row in social_rows if row["source_id"] in used_social]
    lines = [body, "", "## 参考文献", "", "> 以下条目由正文实际使用的审计标记自动同步；APA 细节仍须在最终投稿前核查。", ""]
    combined = [(str(row.get("apa") or "").casefold(), "record", row) for row in rows]
    combined += [(_social_apa(row).casefold(), "source", row) for row in selected_social]
    for _, kind, row in sorted(combined, key=lambda item: item[0]):
        if kind == "source":
            lines += [f"<!-- source:{row['source_id']} -->", _social_apa(row), ""]
            continue
        lines += [f"<!-- record:{row['record_id']} -->", str(row.get("apa") or ""), ""]
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    report = {"document": document, "draft": str(path), "cited_records": len(used), "social_sources": len(selected_social), "embedded_references": len(rows) + len(selected_social), "missing_registry_records": missing}
    write_json(root / f"07_logs/reference_sync_{document}_report.json", report)
    return report


def sync_review_references(root: Path, draft_path: Path | None = None) -> dict[str, Any]:
    """Backward-compatible wrapper for callers created before v6."""
    return sync_references(root, "review", draft_path)


def coverage_targets(records: list[dict[str, Any]], assignments: pd.DataFrame) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    topic_map = dict(zip(assignments.get("record_id", []), assignments.get("topic_id", [])))
    by_topic: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for record in records: by_topic[int(topic_map.get(record["record_id"], 0) or 0)].append(record)
    minimum = citation_minimum(len(records))
    topic_quotas = topic_citation_quotas({topic_id: len(group) for topic_id, group in by_topic.items()}, len(records))
    selected: list[dict[str, Any]] = []
    for topic_id, group in sorted(by_topic.items()):
        quota = topic_quotas[topic_id]
        ranked = sorted(group, key=lambda r: (bool((r.get("fulltext") or {}).get("local_path")), bool(r.get("abstract")), max((r.get("citation_counts") or {"": 0}).values()), r.get("year") or 0), reverse=True)
        selected.extend({"record_id": r["record_id"], "topic_id": topic_id, "selection_reason": "topic-quota"} for r in ranked[:quota])
    seen = {x["record_id"] for x in selected}
    ranked_all = sorted(records, key=lambda r: (bool(r.get("abstract")), max((r.get("citation_counts") or {"": 0}).values()), r.get("year") or 0), reverse=True)
    for record in ranked_all:
        if len(seen) >= minimum: break
        if record["record_id"] not in seen:
            selected.append({"record_id": record["record_id"], "topic_id": int(topic_map.get(record["record_id"], 0) or 0), "selection_reason": "overall-coverage"}); seen.add(record["record_id"])
    summary = {"records": len(records), "minimum_required": minimum, "planned_records": len(seen), "minimum_ratio": .60 if len(records) <= 100 else None, "topic_targets": {str(t): topic_quotas[t] for t in by_topic}}
    return selected, summary


def _table_dossier(root: Path, filename: str, title: str, tables: list[str]) -> None:
    lines = [f"# {title}", "", "> 计量结果用于组织综述思路，不等同于内容性或因果证据。每项写作判断仍须回到 supporting_documents 与证据卡。", ""]
    for table in tables:
        path = root / "04_analysis/markdown" / f"{table}.md"
        lines += [f"## {table}", "", path.read_text(encoding="utf-8") if path.exists() else "_无可用结果_", ""]
    (root / "05_evidence/dossiers" / filename).write_text("\n".join(lines), encoding="utf-8")


def _computed_analysis_claims(root: Path, start: int) -> list[dict[str, Any]]:
    claims, index = [], start
    specs = [
        ("keyword_bursts", "关键词突现", "term", "supporting_documents"),
        ("phrase_bursts", "上下文短语突现", "term", "supporting_documents"),
        ("structural_hole_opportunities", "结构洞连接机会", "node_a", "supporting_documents"),
        ("citation_bursts", "引用突现", "title", "record_id"),
    ]
    for table, label, value_col, records_col in specs:
        path = root / "04_analysis/tables" / f"{table}.csv"
        if not path.exists(): continue
        try: frame = pd.read_csv(path).head(20)
        except pd.errors.EmptyDataError: continue
        for _, row in frame.iterrows():
            raw = str(row.get(records_col, "")); record_ids = re.findall(r"R[0-9a-f]{14}", raw)
            if not record_ids: continue
            index += 1
            value = str(row.get(value_col, ""))
            if table == "structural_hole_opportunities": value += f" ↔ {row.get('node_b', '')}"
            claims.append({"claim_id": f"C{index:04d}", "claim": f"{label}信号：{value}。该信号需结合内容证据解释。", "claim_type": "bibliometric", "direction": "descriptive", "strength": "computed", "record_ids": list(dict.fromkeys(record_ids)), "anchors": [f"04_analysis/tables/{table}.csv"], "counterevidence": [], "status": "ready"})
    return claims


def apa_reference(record: dict[str, Any]) -> str:
    raw_names = [a.get("name", "") if isinstance(a, dict) else str(a) for a in record.get("authors") or []]
    names, seen_exact, seen_abbrev = [], set(), set()
    for value in raw_names:
        name = re.sub(r"\s+", " ", str(value)).strip(" ,;")
        if not name: continue
        exact = re.sub(r"\W+", "", name).casefold()
        if exact in seen_exact: continue
        parts = re.findall(r"[A-Za-z]+", name)
        if "," in name:
            surname = name.split(",", 1)[0].strip().casefold(); given = "".join(parts[1:])
        else:
            surname = (parts[-1] if parts else name).casefold(); given = "".join(parts[:-1])
        abbrev = surname + (given[:1].casefold() if given else "")
        is_abbreviated = bool(re.fullmatch(r"[A-Za-z.' -]+,?\s*[A-Za-z. -]{1,5}", name))
        if abbrev in seen_abbrev and is_abbreviated: continue
        names.append(name); seen_exact.add(exact); seen_abbrev.add(abbrev)
    if not names: author = "Unknown author"
    elif len(names) <= 20: author = ", ".join(names[:-1]) + (", & " + names[-1] if len(names) > 1 else names[0])
    else: author = ", ".join(names[:19]) + ", …, " + names[-1]
    year = record.get("year") or "n.d."; title = str(record.get("title") or "Untitled").strip().rstrip(".。"); venue = str(record.get("venue") or "").strip().rstrip(".。")
    doi = (record.get("ids") or {}).get("doi", "")
    parts = [f"{author}.", f"({year}).", f"{title}."]
    if venue: parts.append(f"{venue}.")
    if doi: parts.append(f"https://doi.org/{doi}")
    return re.sub(r"\s+", " ", " ".join(parts)).replace("..", ".").strip()


def best_fulltext(record: dict[str, Any], extracted: list[Path]) -> Path | None:
    local = (record.get("fulltext") or {}).get("local_path")
    if local and Path(local).exists(): return Path(local)
    title = normalize_title(record.get("title"))
    if not title: return None
    candidates = [(len(normalize_title(p.stem)), p) for p in extracted if normalize_title(p.stem) and (normalize_title(p.stem) in title or title[:30] in normalize_title(p.stem))]
    return max(candidates)[1] if candidates else None


def card_markdown(record: dict[str, Any], fulltext: Path | None) -> str:
    level = "fulltext" if fulltext else ("abstract" if record.get("abstract") else "metadata")
    authors = "; ".join(a.get("name", "") if isinstance(a, dict) else str(a) for a in record.get("authors") or [])
    lines = [f"# [{record['record_id']}] {record.get('title') or '无题名'}", "", "## 来源", "",
             f"- evidence_level: `{level}`", f"- authors: {authors}", f"- year: {record.get('year') or ''}",
             f"- doi: {(record.get('ids') or {}).get('doi','')}", f"- fulltext_path: `{fulltext or ''}`", ""]
    if record.get("abstract"): lines += ["## 摘要", "", record["abstract"], ""]
    lines += ["## 宿主模型证据提取区", "", "> 仅依据上列摘要或 fulltext_path 指向的文件填写。全文证据必须给出 `[page:n]` 或 `[paragraph:n]` 锚点；不得把待填模板当作证据。", ""]
    for field in CARD_FIELDS: lines += [f"### {field}", "", "<!-- TODO: host-agent -->", ""]
    lines += ["### 可复核证据摘录", "", "- <!-- TODO: [page:n]/[paragraph:n] 简短证据与释义 -->", ""]
    return "\n".join(lines)


def build_evidence(root: Path) -> dict[str, Any]:
    records = load_jsonl(root / "02_corpus/corpus.jsonl")
    if not records: raise RuntimeError("缺少 02_corpus/corpus.jsonl，请先 search 或 ingest。")
    extracted = list((root / "03_fulltext/extracted").glob("*.md"))
    assignments_path = root / "04_analysis/tables/topic_assignments.csv"
    assignments = pd.read_csv(assignments_path) if assignments_path.exists() else pd.DataFrame(columns=["record_id", "topic_id"])
    topic_map = dict(zip(assignments.get("record_id", []), assignments.get("topic_id", [])))
    cards_dir = root / "05_evidence/cards"; cards_dir.mkdir(parents=True, exist_ok=True)
    levels, topics = defaultdict(int), defaultdict(list)
    for record in records:
        fulltext = best_fulltext(record, extracted); level = "fulltext" if fulltext else ("abstract" if record.get("abstract") else "metadata")
        levels[level] += 1; topic_id = int(topic_map.get(record["record_id"], 0) or 0); topics[topic_id].append((record, fulltext))
        path = cards_dir / f"{record['record_id']}.md"
        if not path.exists(): path.write_text(card_markdown(record, fulltext), encoding="utf-8")
    dossiers = root / "05_evidence/dossiers"; dossiers.mkdir(parents=True, exist_ok=True)
    for topic_id, items in sorted(topics.items()):
        lines = [f"# Topic {topic_id} evidence dossier", "", f"- documents: {len(items)}", "- status: host-agent synthesis required", "", "## 代表性与覆盖", ""]
        ranked = sorted(items, key=lambda x: (bool(x[1]), max((x[0].get("citation_counts") or {"": 0}).values())), reverse=True)
        for record, fulltext in ranked:
            lines.append(f"- [{record['record_id']}] {record['title']} ({record.get('year') or 'n.d.'}) — {'fulltext' if fulltext else 'abstract/metadata'} — [card](../cards/{record['record_id']}.md)")
        lines += ["", "## 宿主模型综合区", "", "### 共识", "", "<!-- TODO -->", "", "### 分歧与反例", "", "<!-- TODO -->", "", "### 方法和情境边界", "", "<!-- TODO -->"]
        (dossiers / f"topic-{topic_id:02d}.md").write_text("\n".join(lines), encoding="utf-8")
    quality_rows = quality_appraisal(records)
    write_jsonl(root / "05_evidence/study_quality_appraisal.jsonl", quality_rows)
    pd.DataFrame(quality_rows).to_csv(root / "05_evidence/study_quality_appraisal.csv", index=False, encoding="utf-8-sig")
    previous = load_jsonl(root / "05_evidence/claim_ledger.jsonl")
    ledger = []
    topic_table = root / "04_analysis/tables/topics.csv"
    if topic_table.exists():
        for idx, row in pd.read_csv(topic_table).iterrows():
            representatives = row.get("representative_ids", "")
            record_ids = str(representatives).split("; ") if pd.notna(representatives) and str(representatives).strip() else []
            ledger.append({"claim_id": f"C{idx+1:04d}", "claim": f"语料中主题 {int(row['topic_id'])} 包含 {int(row['documents'])} 篇文献，主要词为 {row['top_terms']}。", "claim_type": "bibliometric", "direction": "descriptive", "strength": "computed", "record_ids": record_ids, "anchors": ["04_analysis/tables/topics.csv"], "counterevidence": [], "status": "ready"})
    preserved = [c for c in previous if c.get("claim_type") in {"abstract", "fulltext", "metadata"}]
    existing_ids = {c.get("claim_id") for c in ledger}
    for claim in preserved:
        if claim.get("claim_id") not in existing_ids: ledger.append(claim); existing_ids.add(claim.get("claim_id"))
    next_index = max([int(re.sub(r"\D", "", str(c.get("claim_id") or "0")) or 0) for c in ledger] or [0])
    ledger.extend(_computed_analysis_claims(root, max(2000, next_index)))
    for claim in ledger:
        claim.setdefault("study_quality", "not-applicable" if claim.get("claim_type") == "bibliometric" else "not-yet-appraised")
        claim.setdefault("risk_of_bias", "not-applicable" if claim.get("claim_type") == "bibliometric" else "unknown")
        claim.setdefault("independent_sample_status", "unverified")
        claim.setdefault("evidence_scope", "direct" if claim.get("claim_type") in {"fulltext", "abstract"} else "computed-or-host-synthesis")
        claim.setdefault("support_check", "pending")
    write_jsonl(root / "05_evidence/claim_ledger.jsonl", ledger)
    ledger_lines = ["# Claim ledger", "", "> 内容性论断由宿主模型在逐篇证据卡完成后追加；每条必须列 record_ids 与 anchors。", ""]
    for c in ledger: ledger_lines += [f"## [{c['claim_id']}] {c['claim']}", "", f"- 类型：{c['claim_type']}", f"- 文献：{'; '.join(c['record_ids'])}", f"- 锚点：{'; '.join(c['anchors'])}", ""]
    (root / "05_evidence/claim_ledger.md").write_text("\n".join(ledger_lines), encoding="utf-8")
    index = ["# 分节证据索引", "", "宿主模型应逐节读取相关 dossier、claim ledger 和代表性证据卡；不要一次加载全部全文。", "", "## 建议综述结构", "", "1. 研究范围与语料边界", "2. 发展阶段与主题结构", "3. 理论、概念与作用机制", "4. 方法与研究情境", "5. 争议、反例与边界条件", "6. 经证据校准的研究空白", "7. 未来研究议程", "", "## Dossiers", ""]
    index.extend(f"- [Topic {tid}](dossiers/topic-{tid:02d}.md) — {len(items)} documents" for tid, items in sorted(topics.items()))
    (root / "05_evidence/evidence_index.md").write_text("\n".join(index), encoding="utf-8")
    _table_dossier(root, "trend-evidence.md", "趋势与突现证据 dossier", ["keyword_bursts", "phrase_bursts", "topic_trends", "topic_lifecycle", "topic_evolution"])
    _table_dossier(root, "network-evidence.md", "网络、结构洞与桥接证据 dossier", ["network_summary", "network_nodes", "structural_hole_opportunities"])
    _table_dossier(root, "citation-evidence.md", "引用、共引与耦合证据 dossier", ["citation_impact", "citation_bursts", "citation_metrics", "co_citation_edges", "bibliographic_coupling_edges"])
    module_status = read_json(root / "04_analysis/advanced_module_status.json", {})
    _table_dossier(root, "strategic-map-evidence.md", "主题战略图证据 dossier", ["strategic_map"])
    _table_dossier(root, "citation-age-evidence.md", "引文年龄与半衰期证据 dossier", ["citation_age_summary", "citation_age_instances", "citation_role_candidates"])
    _table_dossier(root, "knowledge-flow-evidence.md", "跨主题知识流动证据 dossier", ["knowledge_flow_summary", "knowledge_flow_detail"])
    _table_dossier(root, "kmeans-diagnostic.md", "KMeans 异质性诊断（非主题结构）", ["cluster_diagnostics", "kmeans_incremental_cross"])
    for filename, key in (("strategic-map-evidence.md", "strategic_map"), ("citation-age-evidence.md", "citation_age"), ("knowledge-flow-evidence.md", "knowledge_flow"), ("kmeans-diagnostic.md", "kmeans")):
        path = dossiers / filename
        status = module_status.get(key, {})
        path.write_text(path.read_text(encoding="utf-8") + f"\n## 模块门控\n\n```json\n{json.dumps(status, ensure_ascii=False, indent=2)}\n```\n", encoding="utf-8")
    semantic_source = root / "05_evidence/semantic/semantic-synthesis.md"
    semantic_target = dossiers / "semantic-synthesis.md"
    semantic_target.write_text(semantic_source.read_text(encoding="utf-8") if semantic_source.exists() else "# Semantic synthesis\n\n> 尚未运行 build-semantic prepare/compile；不得伪造语义结论。\n", encoding="utf-8")
    targets, coverage = coverage_targets(records, assignments)
    write_jsonl(root / "05_evidence/citation_coverage_targets.jsonl", targets)
    coverage_lines = ["# 引用覆盖计划", "", f"- 核心语料：{coverage['records']}", f"- 正文最低独立引用：{coverage['minimum_required']}", f"- 已分配候选：{coverage['planned_records']}", "", "## 主题配额", ""] + [f"- Topic {topic}: {quota}" for topic, quota in sorted(coverage["topic_targets"].items())]
    (root / "05_evidence/citation_coverage.md").write_text("\n".join(coverage_lines), encoding="utf-8")
    section_quota = {"研究范围与演进": .15, "理论与机制": .25, "多源线索与边界": .25, "方法与情境": .15, "争议、空白与议程": .20}
    write_json(root / "05_evidence/section_citation_quotas.json", {name: max(3, math.ceil(coverage["minimum_required"] * share)) for name, share in section_quota.items()})
    ref_lines = ["# APA 7 参考文献注册表", "", "> 自动格式仅作注册与完整性核对；最终交付前由宿主模型核查作者缩写、期刊卷期页码和文献类型。", ""]
    registry = []
    for record in sorted(records, key=lambda r: (str((r.get("authors") or [""])[0]), r.get("year") or 0, r.get("title") or "")):
        apa = apa_reference(record); registry.append({"record_id": record["record_id"], "apa": apa, "doi": (record.get("ids") or {}).get("doi", "")})
        ref_lines += [f"<!-- record:{record['record_id']} -->", f"- {apa}", ""]
    (root / "06_review/references.md").write_text("\n".join(ref_lines), encoding="utf-8")
    write_jsonl(root / "05_evidence/reference_registry.jsonl", registry)
    outline = root / "06_review/outline.md"
    if not outline.exists(): outline.write_text("# 文献综述提纲（需用户确认）\n\n> status: draft-not-approved\n\n" + "\n".join(f"## {x}\n\n- 本节核心问题：\n- 使用 dossier：\n- 使用 claim IDs：\n- 反例/边界：\n" for x in ["研究范围与语料边界", "发展阶段与主题结构", "理论、概念与作用机制", "方法与研究情境", "争议与边界条件", "研究空白", "未来研究议程"]), encoding="utf-8")
    report = {"records": len(records), "evidence_levels": dict(levels), "dossiers": len(topics) + 8, "computed_claims": len(ledger), "quality_appraisals": len(quality_rows), "citation_coverage": coverage, "advanced_modules": module_status, "embedding_used": False}
    write_json(root / "05_evidence/evidence_build_report.json", report); return report


EVIDENCE_TRIGGER = re.compile(r"(?:一些|多项|既有|现有|相关|过去)?(?:研究|文献|语料|证据)(?:表明|显示|发现|指出|提示|呈现|报告|认为)|(?:一些|多项|既有|现有)研究", re.I)


def punctuation_errors(text: str, label: str) -> list[str]:
    checks = [
        (r"[\(（]\s*[;；,，]\s*[\)）]", "空括号内只有标点"),
        (r"[；;]{2,}", "连续分号"),
        (r"[，,]\s*[；;]|[；;]\s*[，,]", "逗号与分号连用"),
        (r"[）)]\s*[，,]\s*[；;]|[）)]\s*[；;]{2,}", "括号后异常标点"),
        (r"\[\s*[,;，；–—-]+\s*\]", "审计标记清理残留"),
    ]
    return [f"{label}存在{description}" for pattern, description in checks if re.search(pattern, text)]


def citation_trigger_errors(text: str, ledger: list[dict[str, Any]], label: str) -> list[str]:
    failures = []
    body, _ = split_embedded_references(text)
    for paragraph in [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip() and not p.lstrip().startswith("#")]:
        sentences = [sentence for sentence in re.split(r"(?<=[。！？!?])", paragraph) if sentence.strip()]
        for index, sentence in enumerate(sentences):
            if not EVIDENCE_TRIGGER.search(sentence): continue
            visible_citation = bool(re.search(r"[\(（][^\n\)）]*\b(?:19|20)\d{2}[a-z]?[^\n\)）]*[\)）]", sentence))
            window = " ".join(sentences[max(0, index - 1):min(len(sentences), index + 2)])
            traceable = bool(cited_records(window, ledger))
            if not (visible_citation or traceable):
                failures.append(f"{label}证据触发句缺少引用：{sentence[:80]}")
    return failures


def validate(root: Path) -> dict[str, Any]:
    errors, warnings = [], []
    records = load_jsonl(root / "02_corpus/corpus.jsonl"); ids = {r.get("record_id") for r in records}
    if not records: errors.append("缺少或空的 canonical corpus")
    if len(ids) != len(records): errors.append("record_id 不唯一")
    ledger = load_jsonl(root / "05_evidence/claim_ledger.jsonl"); claim_ids = {c.get("claim_id") for c in ledger}
    module_status = read_json(root / "04_analysis/advanced_module_status.json", {})
    doi_counts = defaultdict(list)
    for record in records:
        doi = (record.get("ids") or {}).get("doi")
        if doi: doi_counts[str(doi).lower()].append(record["record_id"])
    duplicates = {doi: recs for doi, recs in doi_counts.items() if len(recs) > 1}
    if duplicates: errors.append(f"语料存在重复 DOI: {duplicates}")
    for claim in ledger:
        missing = set(claim.get("record_ids") or []) - ids
        if missing: errors.append(f"{claim.get('claim_id')} 引用不存在的记录: {sorted(missing)}")
        if claim.get("claim_type") == "fulltext" and not any(re.search(r"(?:page|paragraph):\d+", str(a)) for a in claim.get("anchors") or []): errors.append(f"{claim.get('claim_id')} 全文论断缺页码/段落锚点")
        if claim.get("support_check") == "unsupported": errors.append(f"{claim.get('claim_id')} 论断—原文支持度检查为 unsupported")
        if claim.get("strength") == "high" and len(set(claim.get("record_ids") or [])) < 3: errors.append(f"{claim.get('claim_id')} 强概括性论断少于 3 篇独立候选研究")
        anchor_text = " ".join(map(str, claim.get("anchors") or []))
        for marker, module in (("strategic_map", "strategic_map"), ("knowledge_flow", "knowledge_flow"), ("kmeans_", "kmeans")):
            if marker in anchor_text and not (module_status.get(module) or {}).get("writing_allowed"):
                errors.append(f"{claim.get('claim_id')} 使用未通过写作门控的 {module} 结果")
    retracted = [r.get("record_id") for r in records if (r.get("publication_status") or {}).get("is_retracted")]
    if retracted: warnings.append(f"语料含 {len(retracted)} 篇撤稿标记记录，不得作为正向结论证据: {retracted[:10]}")
    assignments_path = root / "04_analysis/tables/topic_assignments.csv"
    assignments = pd.read_csv(assignments_path) if assignments_path.exists() else pd.DataFrame(columns=["record_id", "topic_id"])
    topic_map = dict(zip(assignments.get("record_id", []), assignments.get("topic_id", [])))
    coverage_rows: list[dict[str, Any]] = []
    def validate_manuscript(path: Path, label: str, audit: bool = True, embedded_references: bool = False):
        if not path.exists(): return
        text = path.read_text(encoding="utf-8"); body, reference_text = split_embedded_references(text) if embedded_references else (text, "")
        used_claims = claim_ids_in_text(body); missing = used_claims - claim_ids
        if missing: errors.append(f"{label}使用未知 claim IDs: {sorted(missing)}")
        used_records = cited_records(body, ledger)
        eligible = writing_eligible_records(root, records); eligible_ids = {r["record_id"] for r in eligible}
        eligible_used = used_records & eligible_ids; minimum = citation_minimum(len(eligible))
        coverage_rows.append({"manuscript": label, "scope": "overall", "topic_id": "", "available": len(eligible), "cited": len(eligible_used), "minimum_required": minimum, "coverage": round(len(eligible_used)/max(len(eligible), 1), 6), "status": "pass" if len(eligible_used) >= minimum else "fail"})
        if len(eligible_used) < minimum: errors.append(f"{label}写作合格证据引用覆盖不足：{len(eligible_used)}/{len(eligible)}，最低要求 {minimum}（全量计量语料 {len(records)}）")
        topic_sizes = {int(topic): sum(rid in eligible_ids and value == topic for rid, value in topic_map.items()) for topic in set(topic_map.values())}
        quotas = topic_citation_quotas(topic_sizes, len(eligible))
        for topic_id in sorted(set(topic_map.values())):
            members = {rid for rid, topic in topic_map.items() if topic == topic_id and rid in eligible_ids}; quota = quotas[int(topic_id)]
            covered = len(members & used_records)
            coverage_rows.append({"manuscript": label, "scope": "topic", "topic_id": int(topic_id), "available": len(members), "cited": covered, "minimum_required": quota, "coverage": round(covered/max(len(members), 1), 6), "status": "pass" if covered >= quota else "fail"})
            if covered < quota: errors.append(f"{label} Topic {int(topic_id)} 引用覆盖不足：{covered}/{len(members)}，最低要求 {quota}")
        registered_ids = {row.get("record_id") for row in load_jsonl(root / "05_evidence/reference_registry.jsonl")}
        if not registered_ids and (root / "06_review/references.md").exists():
            registered_ids = set(re.findall(r"<!--\s*record:(R[0-9a-f]{14})\s*-->", (root / "06_review/references.md").read_text(encoding="utf-8")))
        absent = [rid for rid in used_records if rid not in registered_ids]
        if absent: errors.append(f"{label}参考文献注册表缺失记录: {sorted(absent)}")
        if embedded_references:
            embedded = embedded_reference_ids(reference_text); embedded_set = set(embedded)
            if not reference_text: errors.append(f"{label}缺少正文内嵌参考文献段")
            if len(embedded) != len(embedded_set): errors.append(f"{label}文末存在重复参考文献 record 标记")
            if used_records - embedded_set: errors.append(f"{label}文内引用未列入文末参考文献: {sorted(used_records-embedded_set)}")
            if embedded_set - used_records: errors.append(f"{label}文末包含正文未引用文献: {sorted(embedded_set-used_records)}")
            if label == "SSCI 绪论":
                registered_social = {row["source_id"] for row in _social_sources(root)}
                used_social = set(re.findall(r"\bSCTX-\d{3,}\b", body)) or registered_social
                embedded_social = embedded_social_source_ids(reference_text); embedded_social_set = set(embedded_social)
                if len(embedded_social) != len(embedded_social_set): errors.append("绪论文末存在重复社会背景来源")
                if used_social != embedded_social_set: errors.append(f"绪论社会背景来源与文末集合不一致：正文={sorted(used_social)} 文末={sorted(embedded_social_set)}")
            forbidden = re.findall(r"(?im)^#{2,6}\s+.*(?:扩展主题证据|扩展证据|补充引用|引用扩展).*$", body)
            if forbidden: errors.append(f"{label}包含后置引用填充章节: {forbidden}")
            approved = set(approved_review_headings(root)); actual = [re.sub(r"^\d+[.、]\s*", "", x).strip() for x in re.findall(r"(?m)^##\s+(.+?)\s*$", body)]
            unexpected = [heading for heading in actual if approved and heading not in approved]
            if unexpected: errors.append(f"{label}包含未获提纲批准的章节: {unexpected}")
            for heading, content in re.findall(r"(?ms)^##\s+(.+?)\s*\n(.*?)(?=^##\s+|\Z)", body):
                section_records = cited_records(content, ledger)
                coverage_rows.append({"manuscript": label, "scope": "section", "topic_id": heading.strip(), "available": len(records), "cited": len(section_records), "minimum_required": 2, "coverage": round(len(section_records)/max(len(records), 1), 6), "status": "pass" if len(section_records) >= 2 else "fail"})
                if len(section_records) < 2: errors.append(f"{label}章节“{heading.strip()}”引用过少：{len(section_records)}，最低要求 2")
                if re.search(r"主题|知识结构|热点", heading):
                    for index, paragraph in enumerate(re.split(r"\n\s*\n", content), 1):
                        plain = paragraph.strip()
                        if len(re.findall(r"[\u4e00-\u9fff]", plain)) >= 40 and not cited_records(plain, ledger):
                            errors.append(f"{label}主题章节“{heading.strip()}”第{index}段缺少相关文献")
            # NMF 主题常以“第一主题……”等段落呈现，而非另设三级标题；逐段强制绑定相关证据。
            for paragraph in re.split(r"\n\s*\n", body):
                plain = paragraph.strip()
                if re.match(r"^第[一二三四五六七八九十]+主题", plain) and not cited_records(plain, ledger):
                    errors.append(f"{label}知识主题段落缺少相关文献：{plain[:50]}")
        errors.extend(citation_trigger_errors(body, ledger, label))
        errors.extend(punctuation_errors(body, label))
        if "TODO" in body: warnings.append(f"{label}仍含 TODO")
        if re.search(r"从未(?:有|被)?研究|完全空白|没有任何研究|never been studied|no studies have", body, flags=re.I): warnings.append(f"{label}含绝对化 gap 表述")
        return used_records
    draft = root / "06_review/review_draft.md"
    if draft.exists():
        text = draft.read_text(encoding="utf-8"); body, _ = split_embedded_references(text); used = claim_ids_in_text(body)
        validate_manuscript(draft, "综述", embedded_references=True)
        if not used: warnings.append("正文未使用任何 claim ID，无法证明事实论断可追溯")
        contrad = {c.get("claim_id") for c in ledger if c.get("direction") in {"contradict", "mixed"} or c.get("counterevidence")}
        if contrad and not (used & contrad): warnings.append("正文未使用 claim ledger 中的反向/混合证据")
    else: warnings.append("尚未生成 review_draft.md（在语料与提纲确认前这是正常状态）")
    intro_audit = root / "06_review/ssci_introduction_audit.md"; intro_clean = root / "06_review/ssci_introduction.md"
    if intro_audit.exists(): validate_manuscript(intro_audit, "SSCI 绪论", embedded_references=True)
    if intro_clean.exists():
        clean = intro_clean.read_text(encoding="utf-8").strip()
        clean_body, clean_references = split_embedded_references(clean)
        if re.search(r"(?m)^\s*#{1,6}\s|^\s*[-*+]\s|^\s*\d+[.)]\s", clean_body): errors.append("SSCI 绪论清洁版正文不得含小标题、列表或编号")
        paragraphs = [p for p in re.split(r"\n\s*\n", clean_body) if p.strip()]
        if not 8 <= len(paragraphs) <= 12: errors.append(f"SSCI 绪论应为 8–12 个连续自然段，当前 {len(paragraphs)} 段")
        cjk = len(re.findall(r"[\u4e00-\u9fff]", clean_body))
        if not 3000 <= cjk <= 5000: errors.append(f"SSCI 绪论中文长度应为 3000–5000 字，当前约 {cjk} 字")
        if not clean_references: errors.append("SSCI 绪论清洁版缺少文末参考文献")
        if re.search(r"\bC\d{4}\b|\bR[0-9a-f]{14}\b|\bSCTX-\d{3,}\b", clean): errors.append("SSCI 绪论清洁版仍含内部审计 ID")
        errors.extend(punctuation_errors(clean, "SSCI 绪论清洁版"))
    semantic_files = list((root / "05_evidence/semantic/extractions").glob("*.json"))
    completed_semantic = {p.stem for p in semantic_files if read_json(p, {}).get("host_review_status") == "completed"}
    planned_semantic = set()
    for batch in (root / "05_evidence/semantic/batches").glob("batch-*.json"):
        planned_semantic.update(task.get("record_id") for task in (read_json(batch, {}).get("tasks") or []) if task.get("record_id"))
    pending_semantic = planned_semantic - completed_semantic
    if pending_semantic: warnings.append(f"计划候选中仍有 {len(pending_semantic)} 篇待宿主语义提取")
    manifest = read_json(root / "manifest.json", {}); v5_enforced = bool(manifest.get("v5_workflow_enforced"))
    if v5_enforced and draft.exists() and not (root / "06_review/review_brief.json").exists(): errors.append("综述写作前缺少 review_brief.json")
    if v5_enforced and intro_audit.exists():
        if not (root / "06_review/introduction_brief.json").exists(): errors.append("绪论写作前缺少 introduction_brief.json")
        social = load_jsonl(root / "06_review/social_context_sources.jsonl")
        if not social or not all(x.get("url") and x.get("retrieved_at") for x in social): errors.append("绪论第一段缺少可核验现实社会背景来源登记")
    briefs = [read_json(root / "06_review/review_brief.json", {}), read_json(root / "06_review/introduction_brief.json", {})]
    if v5_enforced and any(x.get("model_package_requested") for x in briefs if x):
        package = root / "06_review/theory_model_package.md"
        if not package.exists(): errors.append("写作简报要求完整理论模型包，但 theory_model_package.md 不存在")
        elif not all(term in package.read_text(encoding="utf-8") for term in ("变量", "理论", "假设", "mermaid", "证据等级")): errors.append("理论模型包缺少变量/理论/假设/Mermaid/证据等级要素")
    coverage_frame = pd.DataFrame(coverage_rows)
    if not coverage_frame.empty:
        coverage_frame.to_csv(root / "05_evidence/citation_coverage.csv", index=False, encoding="utf-8-sig")
        (root / "05_evidence/citation_coverage_actual.md").write_text("# 实际引用覆盖\n\n" + coverage_frame.to_markdown(index=False) + "\n", encoding="utf-8")
    semantic_dir = root / "05_evidence/semantic/extractions"
    semantic_report = None
    if semantic_dir.exists() and any(semantic_dir.glob("*.json")):
        semantic_report = validate_semantic(root); errors.extend(semantic_report["errors"]); warnings.extend(semantic_report["warnings"])
    eligible_count = len(writing_eligible_records(root, records))
    report = {"valid": not errors, "errors": errors, "warnings": warnings, "records": len(records), "writing_eligible_records": eligible_count, "claims": len(ledger), "minimum_citations": citation_minimum(eligible_count), "citation_coverage_rows": len(coverage_rows), "advanced_modules": module_status, "semantic_validation": semantic_report}
    write_json(root / "07_logs/validation_report.json", report); return report


def write_introduction(root: Path, audit_source: Path | None = None) -> dict[str, Any]:
    outline = root / "06_review/outline.md"
    if not outline.exists() or "status: approved" not in outline.read_text(encoding="utf-8"):
        raise RuntimeError("综述提纲尚未获用户确认，不能生成 SSCI 绪论。")
    audit_path = root / "06_review/ssci_introduction_audit.md"
    clean_path = root / "06_review/ssci_introduction.md"
    if audit_source:
        text = audit_source.read_text(encoding="utf-8")
        audit_path.write_text(text, encoding="utf-8")
        sync_report = sync_references(root, "introduction", audit_path)
        synced = audit_path.read_text(encoding="utf-8")
        clean = re.sub(r"\s*\[(?:cite:)?\s*(?:C\d{4}|R[0-9a-f]{14}|SCTX-\d{3,})(?:\s*[,;，；]\s*(?:C\d{4}|R[0-9a-f]{14}|SCTX-\d{3,}))*\s*\]", "", synced, flags=re.I)
        clean = re.sub(r"<!--.*?-->", "", clean, flags=re.S)
        body, references = split_embedded_references(clean)
        body = re.sub(r"(?m)^\s*#{1,6}.*$", "", body).strip()
        clean = body + ("\n\n" + references.strip() if references else "")
        clean_path.write_text(re.sub(r"\n{3,}", "\n\n", clean), encoding="utf-8")
        return {"status": "written", "audit": str(audit_path), "clean": str(clean_path), "reference_sync": sync_report}
    targets = load_jsonl(root / "05_evidence/citation_coverage_targets.jsonl")
    records = load_jsonl(root / "02_corpus/corpus.jsonl")
    eligible = writing_eligible_records(root, records)
    minimum = citation_minimum(len(eligible))
    brief = ["# SSCI 漏斗型绪论写作任务", "", "> 由宿主模型据此撰写 8–12 个无小标题连续段落；可见 APA 引文后使用 `[cite:R...,R...]` 绑定证据，完成后用 write-introduction --audit-source 自动同步参考文献并清洁。", "", f"语料总数：{len(records)}", f"语义筛选后可写证据：{len(eligible)}", f"最低独立引用：{minimum}", "", "## 必须读取", "", "- 研究现状地图与已确认提纲", "- topic dossiers", "- trend-evidence.md", "- network-evidence.md", "- citation-evidence.md", "- citation_coverage_targets.jsonl", "", "## 候选记录", ""]
    brief.extend(f"- {x['record_id']} — Topic {x['topic_id']} — {x['selection_reason']}" for x in targets)
    path = root / "06_review/ssci_introduction_brief.md"; path.write_text("\n".join(brief), encoding="utf-8")
    return {"status": "brief-created", "brief": str(path), "corpus_records": len(records), "writing_eligible_records": len(eligible), "minimum_citations": minimum}
