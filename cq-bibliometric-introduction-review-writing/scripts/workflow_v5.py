#!/usr/bin/env python3
"""Fifth-round acquisition, corpus-policy, writing-brief and coverage helpers."""
from __future__ import annotations

import math
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

import pandas as pd

from common import load_jsonl, read_json, utc_stamp, write_json, write_jsonl
from ingest import export_corpus
from sources import CachedClient, enrich_crossref, validate_search_plan


def _quoted(term: str) -> str:
    term = re.sub(r"\s+", " ", str(term or "").strip())
    if not term: return ""
    if re.search(r"\b(?:AND|OR|NOT)\b|[()\"]", term, re.I): return term
    return f'"{term}"' if " " in term else term


def _concept_groups(plan: dict[str, Any], language: str) -> list[str]:
    groups = []
    for concept in plan.get("concepts") or []:
        terms = [_quoted(x) for x in concept.get(language) or [] if str(x).strip()]
        if terms: groups.append("(" + " OR ".join(dict.fromkeys(terms)) + ")")
    return groups


def build_search_strategy(root: Path, mode: str) -> dict[str, Any]:
    plan_path = root / "00_plan/search_plan.json"; plan = read_json(plan_path, {})
    validation = validate_search_plan(plan)
    if not validation["valid"]: raise RuntimeError("检索计划未通过校验：" + "; ".join(validation["errors"]))
    en_groups, zh_groups = _concept_groups(plan, "en"), _concept_groups(plan, "zh")
    exclusions = [_quoted(x) for c in plan.get("concepts") or [] for x in c.get("exclude") or [] if str(x).strip()]
    if not en_groups: raise RuntimeError("缺少英文概念组，无法生成 WoS 检索式。")
    core_groups = en_groups[: min(3, len(en_groups))]
    extended_groups = en_groups[: min(2, len(en_groups))]
    variants = {
        "core": "TS=(" + " AND ".join(core_groups) + ")",
        "extended": "TS=(" + " AND ".join(extended_groups) + ")",
        "frontier": "TS=(" + " AND ".join(en_groups) + ")",
    }
    if exclusions:
        variants = {k: f"{v} NOT TS=({' OR '.join(exclusions)})" for k, v in variants.items()}
    txt = "\n\n".join(f"[{k.upper()}]\n{v}" for k, v in variants.items()) + "\n"
    (root / "00_plan/wos_search_query.txt").write_text(txt, encoding="utf-8")
    md = ["# WoS 可复制检索式", "", "> 字段：Topic (TS)；核心、扩展、前沿三个版本需分开执行并记录检索日期。", ""]
    for name, query in variants.items(): md += [f"## {name}", "", "```text", query, "```", ""]
    md += ["## 中文数据库概念组", ""] + [f"- {x}" for x in zh_groups]
    md += ["", "## 审计提示", "", "- 使用种子文献检查召回。", "- 导出时尽量选择“完整记录与引用的参考文献”。", "- 保留数据库、日期、命中数和检索式。"]
    (root / "00_plan/wos_search_query.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    manifest = read_json(root / "manifest.json", {})
    manifest.update({"acquisition_mode": mode, "metadata_enrichment": manifest.get("metadata_enrichment", "offline"), "corpus_mode": manifest.get("corpus_mode", "unselected")})
    write_json(root / "manifest.json", manifest)
    return {"mode": mode, "validation": validation, "outputs": ["00_plan/wos_search_query.txt", "00_plan/wos_search_query.md"], "openalex_required": mode == "api-search"}


def metadata_coverage(root: Path, records: list[dict[str, Any]]) -> dict[str, Any]:
    fields = {
        "title": lambda r: bool(r.get("title")), "authors": lambda r: bool(r.get("authors")), "year": lambda r: bool(r.get("year")),
        "publication_date": lambda r: bool(r.get("publication_date")), "abstract": lambda r: bool(r.get("abstract")), "keywords": lambda r: bool(r.get("keywords")),
        "doi": lambda r: bool((r.get("ids") or {}).get("doi")), "citation_total": lambda r: bool(r.get("citation_counts")),
        "annual_citation_history": lambda r: bool(r.get("citation_counts_by_year")), "references": lambda r: bool(r.get("references")),
        "reference_years": lambda r: any((x or {}).get("year") for x in r.get("reference_metadata") or [] if isinstance(x, dict)),
    }
    rows = []
    total = len(records)
    for field, check in fields.items():
        count = sum(bool(check(r)) for r in records)
        rows.append({"scope": "overall", "source": "all", "field": field, "available": count, "total": total, "coverage": round(count / max(total, 1), 6)})
    by_source: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        sources = {str(x.get("source") or "unknown") for x in record.get("provenance") or []} or {"unknown"}
        for source in sources: by_source[source].append(record)
    for source, group in sorted(by_source.items()):
        for field, check in fields.items():
            count = sum(bool(check(r)) for r in group)
            rows.append({"scope": "source", "source": source, "field": field, "available": count, "total": len(group), "coverage": round(count / max(len(group), 1), 6)})
    frame = pd.DataFrame(rows); frame.to_csv(root / "02_corpus/metadata-coverage.csv", index=False, encoding="utf-8-sig")
    notes = {
        "annual_citation_history": "缺失时不运行引用突现，不从总被引数推造。",
        "reference_years": "覆盖不足时引文年龄/半衰期模块降级。",
        "citation_total": "各来源口径分开保存，不相加。",
    }
    lines = ["# 元数据覆盖报告", "", f"- records: {total}", "", frame[frame.scope == "overall"].to_markdown(index=False), "", "## 降级与补全规则", ""]
    lines += [f"- **{key}**：{value}" for key, value in notes.items()]
    (root / "02_corpus/metadata-coverage.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"records": total, "fields": {x["field"]: x["coverage"] for x in rows if x["scope"] == "overall"}}


def enrich_metadata(root: Path, source: str, confirmed: bool, limit: int = 0) -> dict[str, Any]:
    if source != "crossref": raise RuntimeError("当前只支持 Crossref 无密钥补全。")
    if not confirmed: raise RuntimeError("未确认联网补全，未发送任何请求。")
    records = load_jsonl(root / "02_corpus/corpus.jsonl"); client = CachedClient(root / "01_sources/cache")
    attempted = updated = failed = 0
    for record in records[: limit or None]:
        if not record.get("title") and not (record.get("ids") or {}).get("doi"): continue
        attempted += 1; before = str(record)
        try: enrich_crossref(record, client, "")
        except RuntimeError: failed += 1; continue
        updated += before != str(record)
    export_corpus(root, records, {"source": source, "attempted": attempted, "updated": updated, "failed": failed}, "metadata_enrichment_report.json")
    coverage = metadata_coverage(root, records)
    manifest = read_json(root / "manifest.json", {}); manifest["metadata_enrichment"] = "crossref-confirmed"; write_json(root / "manifest.json", manifest)
    return {"source": source, "attempted": attempted, "updated": updated, "failed": failed, "coverage": coverage}


def apply_corpus_policy(root: Path, mode: str) -> dict[str, Any]:
    records = load_jsonl(root / "02_corpus/corpus.jsonl")
    if not records: raise RuntimeError("语料为空，请先导入或检索。")
    if mode != "all": raise RuntimeError("聚焦模式需通过 focus 建立派生任务。")
    for record in records:
        level = "metadata-only" if not record.get("abstract") else ("direct-or-adjacent-evidence")
        record["inclusion"] = {"status": "included_all", "reasons": ["user-selected-zero-exclusion-policy"], "evidence_scope": level}
    policy = {"mode": "all", "records": len(records), "excluded": 0, "evidence_scopes_are_not_exclusions": True, "set_at": utc_stamp()}
    export_corpus(root, records, policy, "corpus_policy_report.json")
    write_json(root / "02_corpus/corpus_policy.json", policy)
    manifest = read_json(root / "manifest.json", {}); manifest["corpus_mode"] = "all"; write_json(root / "manifest.json", manifest)
    return policy


def write_brief(root: Path, document: str, gaps: list[str], skipped: bool, model_requested: bool) -> dict[str, Any]:
    if document == "introduction" and not (root / "06_review/review_draft.md").exists():
        raise RuntimeError("系统综述尚未完成，不能建立绪论写作简报。")
    dimensions = ["理论", "机制", "测量", "方法", "情境", "时间", "样本", "实践干预"]
    data = {"document": document, "status": "completed", "user_gap_directions": gaps, "user_skipped": skipped, "default_gap_dimensions": dimensions if skipped else [], "model_package_requested": model_requested, "updated_at": utc_stamp()}
    stem = "review_brief" if document == "review" else "introduction_brief"
    write_json(root / f"06_review/{stem}.json", data)
    lines = [f"# {document} writing brief", "", f"- user_skipped: {str(skipped).lower()}", f"- model_package_requested: {str(model_requested).lower()}", "", "## 希望突出的缺口方向", ""]
    lines += [f"- {x}" for x in (gaps or dimensions)]
    lines += ["", "## 每个缺口必须回答", "", "- 已有研究覆盖什么", "- 缺少哪类直接证据", "- 为什么重要", "- 可检验的研究问题", "- 适合的设计、数据与方法", "- 反例、边界与禁止夸大事项"]
    (root / f"06_review/{stem}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return data


def writing_context_manifest(root: Path, budget: str, batch_size: int = 12) -> dict[str, Any]:
    records = load_jsonl(root / "02_corpus/corpus.jsonl")
    targets = load_jsonl(root / "05_evidence/citation_coverage_targets.jsonl")
    selected = records if budget == "exhaustive" else [r for r in records if r["record_id"] in {x.get("record_id") for x in targets}]
    tokens = sum(max(1, len((r.get("title") or "") + " " + (r.get("abstract") or "")) // 4) for r in selected)
    report = {"budget": budget, "corpus_records": len(records), "semantic_records": len(selected), "estimated_input_tokens": tokens, "estimated_batches": math.ceil(len(selected) / max(batch_size, 1)), "selection": "all" if budget == "exhaustive" else "citation-quota+fulltext+counterevidence", "generated_at": utc_stamp()}
    write_json(root / "05_evidence/writing-context-manifest.json", report)
    return report
