#!/usr/bin/env python3
"""Host-agent semantic evidence workflow. No embeddings or model downloads."""
from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import pandas as pd

from common import load_jsonl, read_json, write_json, write_jsonl

REQUIRED = ["record_id", "evidence_level", "research_questions", "theories", "variables", "relations", "design", "sample", "contexts", "methods", "findings", "limitations", "dataset_overlap_signals", "relevance", "anchors"]
CAUSAL = re.compile(r"\b(causes?|leads? to|results? in|drives?|determines?)\b|导致|引起|决定|驱动", re.I)
NONCAUSAL_DESIGNS = {"survey", "cross-sectional", "qualitative", "review", "unclear"}


def _template(record: dict[str, Any], evidence_level: str) -> dict[str, Any]:
    return {"record_id": record["record_id"], "evidence_level": evidence_level, "research_questions": [], "theories": [], "variables": {"antecedents": [], "mediators": [], "moderators": [], "outcomes": []}, "relations": [], "design": "unclear", "sample": {}, "contexts": [], "methods": [], "findings": [], "limitations": [], "dataset_overlap_signals": [], "relevance": "", "anchors": [], "host_review_status": "pending"}


def prepare(root: Path, batch_size: int = 12, budget: str = "balanced") -> dict[str, Any]:
    records = load_jsonl(root / "02_corpus/corpus.jsonl")
    target_ids = {x.get("record_id") for x in load_jsonl(root / "05_evidence/citation_coverage_targets.jsonl")}
    if budget == "balanced" and target_ids: records = [r for r in records if r.get("record_id") in target_ids]
    assignments_path = root / "04_analysis/tables/topic_assignments.csv"
    assignments = pd.read_csv(assignments_path) if assignments_path.exists() else pd.DataFrame(columns=["record_id", "topic_id"])
    topic = dict(zip(assignments.get("record_id", []), assignments.get("topic_id", [])))
    base = root / "05_evidence/semantic"; batches = base / "batches"; outputs = base / "extractions"
    batches.mkdir(parents=True, exist_ok=True); outputs.mkdir(parents=True, exist_ok=True)
    for stale in batches.glob("batch-*.json"): stale.unlink()
    tasks = []
    for record in sorted(records, key=lambda r: (topic.get(r["record_id"], 0), r.get("year") or 0)):
        full = (record.get("fulltext") or {}).get("local_path")
        level = "fulltext" if full else "abstract" if record.get("abstract") else "metadata"
        output_path = outputs / f"{record['record_id']}.json"
        if output_path.exists() and read_json(output_path, {}).get("host_review_status") == "completed": continue
        tasks.append({"record_id": record["record_id"], "topic_id": int(topic.get(record["record_id"], 0) or 0), "title": record.get("title", ""), "year": record.get("year"), "evidence_level": level, "source_path": full or f"05_evidence/cards/{record['record_id']}.md", "abstract": record.get("abstract", "") if not full else "", "output_path": f"05_evidence/semantic/extractions/{record['record_id']}.json", "template": _template(record, level)})
    for index in range(0, len(tasks), batch_size): write_json(batches / f"batch-{index // batch_size + 1:03d}.json", {"instructions": "Host Codex/Claude must read each source, fill its template, preserve exact anchors, and never infer unavailable details.", "tasks": tasks[index:index + batch_size]})
    write_json(base / "schema.json", {"required_fields": REQUIRED, "relation_fields": ["subject", "predicate", "object", "direction", "status", "anchor"], "allowed_relation_status": ["support", "contradict", "mixed", "not-significant"], "note": "No embedding model is used."})
    return {"phase": "prepare", "budget": budget, "selected_records": len(records), "pending_records": len(tasks), "batches": math.ceil(len(tasks) / batch_size), "batch_size": batch_size, "embedding_used": False, "next": "Host agent fills extraction JSON files, then run compile."}


def _completed(root: Path) -> list[dict[str, Any]]:
    rows = []
    for path in sorted((root / "05_evidence/semantic/extractions").glob("*.json")):
        item = read_json(path, {})
        if item.get("host_review_status") == "completed": rows.append(item)
    return rows


def compile_semantic(root: Path) -> dict[str, Any]:
    rows = _completed(root); base = root / "05_evidence/semantic"; base.mkdir(parents=True, exist_ok=True)
    theory_rows, relation_rows, method_rows, counter_rows, claim_rows = [], [], [], [], []
    for item in rows:
        rid = item["record_id"]
        for theory in item.get("theories") or []: theory_rows.append({"record_id": rid, "theory": theory, "evidence_level": item.get("evidence_level")})
        for relation in item.get("relations") or []:
            row = {"record_id": rid, **relation, "evidence_level": item.get("evidence_level"), "design": item.get("design")}; relation_rows.append(row)
            if relation.get("status") in {"contradict", "mixed", "not-significant"}: counter_rows.append(row)
        method_rows.append({"record_id": rid, "design": item.get("design"), "sample": json.dumps(item.get("sample") or {}, ensure_ascii=False), "contexts": "; ".join(map(str, item.get("contexts") or [])), "methods": "; ".join(map(str, item.get("methods") or [])), "outcomes": "; ".join(map(str, (item.get("variables") or {}).get("outcomes") or []))})
    outputs = {"theory_variable_matrix": theory_rows, "mechanism_relation_matrix": relation_rows, "method_context_outcome_matrix": method_rows, "counter_and_null_evidence": counter_rows}
    for name, data in outputs.items(): pd.DataFrame(data).to_csv(base / f"{name}.csv", index=False, encoding="utf-8-sig")
    grouped = defaultdict(list)
    for row in relation_rows: grouped[(row.get("subject", ""), row.get("predicate", ""), row.get("object", ""), row.get("direction", ""))].append(row)
    for index, (key, evidence) in enumerate(grouped.items(), 1):
        claim_rows.append({"semantic_claim_id": f"SC{index:04d}", "claim": " ".join(x for x in key if x), "record_ids": sorted({x["record_id"] for x in evidence}), "statuses": sorted({str(x.get("status")) for x in evidence}), "anchors": [x.get("anchor") for x in evidence if x.get("anchor")], "independent_studies": len({x["record_id"] for x in evidence}), "claim_status": "candidate", "support_check": "pending"})
    write_jsonl(base / "semantic_claim_candidates.jsonl", claim_rows)
    lines = ["# Semantic synthesis", "", "> Generated from host-reviewed structured extractions; no embedding model was used.", "", f"- completed records: {len(rows)}", f"- relation observations: {len(relation_rows)}", f"- counter/null observations: {len(counter_rows)}", f"- claim candidates: {len(claim_rows)}", "", "## Writing priority", "", "Full text/abstract evidence → host semantic synthesis → NMF structure → citation age/knowledge flow → strategic/KMeans/network diagnostics."]
    (base / "semantic-synthesis.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"phase": "compile", "completed_records": len(rows), "relations": len(relation_rows), "counter_or_null": len(counter_rows), "claim_candidates": len(claim_rows), "embedding_used": False}


def validate_semantic(root: Path) -> dict[str, Any]:
    records = {r["record_id"]: r for r in load_jsonl(root / "02_corpus/corpus.jsonl")}; errors, warnings = [], []
    rows = _completed(root)
    for item in rows:
        rid = item.get("record_id")
        if rid not in records: errors.append(f"unknown record_id: {rid}"); continue
        missing = [field for field in REQUIRED if field not in item]
        if missing: errors.append(f"{rid} missing fields: {missing}")
        level = item.get("evidence_level"); anchors = item.get("anchors") or []
        if level == "fulltext" and not any(re.search(r"(?:page|paragraph):\d+", str(a)) for a in anchors): errors.append(f"{rid} fulltext extraction lacks page/paragraph anchor")
        if level == "abstract" and any(re.search(r"(?:page|paragraph):\d+", str(a)) for a in anchors): warnings.append(f"{rid} abstract extraction contains fulltext-style anchor")
        design = str(item.get("design") or "unclear").lower()
        for relation in item.get("relations") or []:
            if not relation.get("anchor"): errors.append(f"{rid} relation lacks anchor")
            wording = " ".join(str(relation.get(k, "")) for k in ("subject", "predicate", "object"))
            if design in NONCAUSAL_DESIGNS and CAUSAL.search(wording): errors.append(f"{rid} causal wording exceeds {design} design")
    candidates = load_jsonl(root / "05_evidence/semantic/semantic_claim_candidates.jsonl")
    for claim in candidates:
        if claim.get("support_check") == "unsupported": errors.append(f"{claim.get('semantic_claim_id')} is unsupported")
        if claim.get("claim_status") == "strong" and int(claim.get("independent_studies") or 0) < 3: errors.append(f"{claim.get('semantic_claim_id')} strong claim has fewer than 3 independent studies")
        if claim.get("support_check") == "partial" and claim.get("claim_status") == "strong": errors.append(f"{claim.get('semantic_claim_id')} partial support must use narrower wording")
    report = {"phase": "validate", "valid": not errors, "completed_records": len(rows), "errors": errors, "warnings": warnings, "embedding_used": False}
    write_json(root / "07_logs/semantic_validation.json", report); return report


def embedding_dry_run(root: Path) -> dict[str, Any]:
    records = load_jsonl(root / "02_corpus/corpus.jsonl"); fulltexts = list((root / "03_fulltext/extracted").glob("*.md"))
    characters = sum(len(r.get("title", "")) + len(r.get("abstract", "")) for r in records) + sum(p.stat().st_size for p in fulltexts)
    chunks = max(len(records), math.ceil(characters / 2400))
    return {"status": "interface-only", "dry_run": True, "documents": len(records), "fulltext_files": len(fulltexts), "estimated_chunks": chunks, "estimated_model_download": "hundreds of MB to several GB depending on future model", "hardware_note": "CPU-only full-text encoding may be slow; GPU is optional but not detected by the base workflow.", "dependencies_installed": False, "download_started": False, "embedding_used": False, "message": "This release intentionally provides no inference implementation and never downloads a model."}
