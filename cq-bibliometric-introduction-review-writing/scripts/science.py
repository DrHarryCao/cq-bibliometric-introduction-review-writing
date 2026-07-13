#!/usr/bin/env python3
"""Transparent screening, study-quality and reproducibility helpers."""
from __future__ import annotations

import importlib.metadata
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from common import load_jsonl, read_json, utc_stamp, write_json, write_jsonl


def seed_recall(plan: dict[str, Any], records: list[dict[str, Any]]) -> dict[str, Any]:
    seeds = plan.get("seed_papers") or []
    corpus = "\n".join(f"{r.get('title','')} {(r.get('ids') or {}).get('doi','')}".lower() for r in records)
    rows = []
    for seed in seeds:
        label = str(seed.get("doi") or seed.get("title") or seed).strip()
        normalized = re.sub(r"https?://(?:dx\.)?doi\.org/", "", label.lower())
        matched = bool(normalized and normalized in corpus)
        rows.append({"seed": label, "recalled": matched})
    return {"seeds": len(rows), "recalled": sum(x["recalled"] for x in rows), "recall": round(sum(x["recalled"] for x in rows) / len(rows), 4) if rows else None, "details": rows}


def prisma_report(root: Path, stage: str, records: list[dict[str, Any]], details: dict[str, Any] | None = None) -> dict[str, Any]:
    log_path = root / "07_logs/screening_log.jsonl"
    log = load_jsonl(log_path)
    entry = {"at": utc_stamp(), "stage": stage, "records": len(records), **(details or {})}
    log.append(entry); write_jsonl(log_path, log)
    excluded = Counter()
    for r in records:
        inclusion = r.get("inclusion") or {}
        if inclusion.get("status", "").startswith("excluded"):
            excluded[inclusion.get("reason") or "unspecified"] += 1
    report = {
        "framework": "PRISMA-style transparent flow; not a claim of PRISMA compliance",
        "generated_at": utc_stamp(), "stages": log, "current_records": len(records),
        "excluded_reasons": dict(excluded), "seed_recall": seed_recall(read_json(root / "00_plan/search_plan.json", {}), records),
    }
    write_json(root / "07_logs/prisma_flow.json", report)
    lines = ["# PRISMA 风格检索与筛选流程", "", "> 这是透明报告工具，不代表本项目自动满足 PRISMA 2020 全部要求。", "", "| 阶段 | 时间 | 记录数 |", "|---|---|---:|"]
    lines += [f"| {x['stage']} | {x['at']} | {x['records']} |" for x in log]
    if excluded:
        lines += ["", "## 排除原因", ""] + [f"- {k}: {v}" for k, v in excluded.most_common()]
    recall = report["seed_recall"]
    lines += ["", "## 种子文献召回", "", f"- 已召回：{recall['recalled']}/{recall['seeds']}" if recall["seeds"] else "- 未提供种子文献。"]
    (root / "07_logs/prisma_flow.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report


def infer_study_design(record: dict[str, Any]) -> str:
    text = f"{record.get('title','')} {record.get('abstract','')}".lower()
    if re.search(r"\bexperiment|randomi[sz]ed|laboratory|field experiment|\u5b9e\u9a8c", text): return "experiment"
    if re.search(r"\binterview|focus group|ethnograph|qualitative|\u8bbf\u8c08|\u8d28\u6027", text): return "qualitative"
    if re.search(r"\breview|meta-analysis|systematic|\u7efc\u8ff0|\u5143\u5206\u6790", text): return "review"
    if re.search(r"\bsurvey|questionnaire|respondent|\u95ee\u5377|\u8c03\u67e5", text): return "survey"
    return "unclear"


def quality_appraisal(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for r in records:
        design = infer_study_design(r); abstract = r.get("abstract") or ""; fulltext = bool((r.get("fulltext") or {}).get("local_path"))
        rows.append({
            "record_id": r["record_id"], "study_design": design,
            "evidence_level": "fulltext" if fulltext else "abstract" if abstract else "metadata",
            "reports_sample_or_material": bool(re.search(r"\b(?:n\s*=|sample|participants?|respondents?|dataset)|\u6837\u672c|\u53c2\u4e0e\u8005", abstract, re.I)),
            "reports_method": bool(re.search(r"\bmethod|regression|sem\b|experiment|interview|survey|\u65b9\u6cd5|\u5b9e\u9a8c|\u56de\u5f52", abstract, re.I)),
            "reports_limitations": bool(re.search(r"\blimitations?|\u5c40\u9650", abstract, re.I)),
            "risk_of_bias": "not-assessable-from-abstract" if not fulltext else "requires-host-appraisal",
            "independent_sample_status": "unverified",
            "warning": "该表是设计适配的检查清单，不将不同研究设计机械合成单一质量分数。",
        })
    return rows


def dependency_versions() -> dict[str, str]:
    result = {"python": sys.version.split()[0]}
    for name in ("numpy", "pandas", "scikit-learn", "networkx", "requests", "openpyxl"):
        try: result[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError: result[name] = "missing"
    return result
