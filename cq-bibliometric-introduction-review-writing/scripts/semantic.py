#!/usr/bin/env python3
"""Host-agent semantic evidence workflow. No embeddings or model downloads."""
from __future__ import annotations

import json
import hashlib
import math
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import pandas as pd

from common import load_jsonl, read_csv_optional, read_json, write_json, write_jsonl

REQUIRED = ["record_id", "evidence_level", "research_questions", "theories", "variables", "relations", "design", "sample", "contexts", "methods", "findings", "limitations", "dataset_overlap_signals", "relevance", "anchors"]
CAUSAL = re.compile(r"\b(causes?|leads? to|results? in|drives?|determines?)\b|导致|引起|决定|驱动", re.I)
NONCAUSAL_DESIGNS = {"survey", "cross-sectional", "qualitative", "review", "unclear"}
PROTOCOL_VERSION = "8.0"


def _source_hash(record: dict[str, Any], full: str | None) -> str:
    path = Path(full) if full else None
    if path and path.exists(): payload = path.read_bytes()
    else: payload = f"{record.get('title','')}\n{record.get('abstract','')}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _template(record: dict[str, Any], evidence_level: str, source_hash: str) -> dict[str, Any]:
    return {"record_id": record["record_id"], "evidence_level": evidence_level, "source_hash": source_hash, "extraction_protocol_version": PROTOCOL_VERSION, "research_questions": [], "theories": [], "variables": {"antecedents": [], "mediators": [], "moderators": [], "outcomes": []}, "relations": [], "design": "unclear", "sample": {}, "contexts": [], "methods": [], "findings": [], "limitations": [], "dataset_overlap_signals": [], "relevance": "", "anchors": [], "host_review_status": "pending"}


def prepare(root: Path, batch_size: int = 12, budget: str = "balanced") -> dict[str, Any]:
    records = load_jsonl(root / "02_corpus/corpus.jsonl")
    target_ids = {x.get("record_id") for x in load_jsonl(root / "05_evidence/citation_coverage_targets.jsonl")}
    if budget == "balanced" and target_ids: records = [r for r in records if r.get("record_id") in target_ids]
    assignments_path = root / "04_analysis/tables/topic_assignments.csv"
    assignments = read_csv_optional(assignments_path, ["record_id", "topic_id"])
    topic = dict(zip(assignments.get("record_id", []), assignments.get("topic_id", [])))
    base = root / "05_evidence/semantic"; batches = base / "batches"; outputs = base / "extractions"
    batches.mkdir(parents=True, exist_ok=True); outputs.mkdir(parents=True, exist_ok=True)
    for stale in batches.glob("batch-*.json"): stale.unlink()
    tasks = []
    for record in sorted(records, key=lambda r: (topic.get(r["record_id"], 0), r.get("year") or 0)):
        full = (record.get("fulltext") or {}).get("local_path")
        level = "fulltext" if full else "abstract" if record.get("abstract") else "metadata"
        source_hash = _source_hash(record, full)
        output_path = outputs / f"{record['record_id']}.json"
        cached = read_json(output_path, {}) if output_path.exists() else {}
        if cached.get("host_review_status") == "completed" and (not cached.get("source_hash") or cached.get("source_hash") == source_hash): continue
        tasks.append({"record_id": record["record_id"], "topic_id": int(topic.get(record["record_id"], 0) or 0), "title": record.get("title", ""), "year": record.get("year"), "evidence_level": level, "source_hash": source_hash, "source_path": full or f"05_evidence/cards/{record['record_id']}.md", "abstract": record.get("abstract", "") if not full else "", "output_path": f"05_evidence/semantic/extractions/{record['record_id']}.json", "template": _template(record, level, source_hash)})
    for index in range(0, len(tasks), batch_size): write_json(batches / f"batch-{index // batch_size + 1:03d}.json", {"instructions": "Host Codex/Claude must read each source, fill its template, preserve exact anchors, and never infer unavailable details.", "tasks": tasks[index:index + batch_size]})
    write_json(base / "schema.json", {"protocol_version": PROTOCOL_VERSION, "required_fields": REQUIRED, "relation_fields": ["subject", "predicate", "object", "direction", "status", "anchor", "confidence"], "allowed_relation_status": ["support", "contradict", "mixed", "not-significant"], "note": "No embedding model is used."})
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
    schemas = {
        "theory_variable_matrix": ["record_id", "theory", "evidence_level"],
        "mechanism_relation_matrix": ["record_id", "subject", "predicate", "object", "direction", "status", "anchor", "confidence", "evidence_level", "design"],
        "method_context_outcome_matrix": ["record_id", "design", "sample", "contexts", "methods", "outcomes"],
        "counter_and_null_evidence": ["record_id", "subject", "predicate", "object", "direction", "status", "anchor", "confidence", "evidence_level", "design"],
    }
    outputs = {"theory_variable_matrix": theory_rows, "mechanism_relation_matrix": relation_rows, "method_context_outcome_matrix": method_rows, "counter_and_null_evidence": counter_rows}
    for name, data in outputs.items():
        pd.DataFrame(data, columns=schemas[name]).to_csv(base / f"{name}.csv", index=False, encoding="utf-8-sig")
    grouped = defaultdict(list)
    for row in relation_rows: grouped[(row.get("subject", ""), row.get("predicate", ""), row.get("object", ""), row.get("direction", ""))].append(row)
    for index, (key, evidence) in enumerate(grouped.items(), 1):
        claim_rows.append({"semantic_claim_id": f"SC{index:04d}", "claim": " ".join(x for x in key if x), "record_ids": sorted({x["record_id"] for x in evidence}), "statuses": sorted({str(x.get("status")) for x in evidence}), "anchors": [x.get("anchor") for x in evidence if x.get("anchor")], "independent_studies": len({x["record_id"] for x in evidence}), "claim_status": "candidate", "support_check": "pending"})
    write_jsonl(base / "semantic_claim_candidates.jsonl", claim_rows)
    lines = ["# Semantic synthesis", "", "> Generated from host-reviewed structured extractions; no embedding model was used.", "", f"- completed records: {len(rows)}", f"- relation observations: {len(relation_rows)}", f"- counter/null observations: {len(counter_rows)}", f"- claim candidates: {len(claim_rows)}", "", "## Writing priority", "", "Full text/abstract evidence → host semantic synthesis → NMF structure → citation age/knowledge flow → strategic/KMeans/network diagnostics."]
    (base / "semantic-synthesis.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"phase": "compile", "completed_records": len(rows), "relations": len(relation_rows), "counter_or_null": len(counter_rows), "claim_candidates": len(claim_rows), "embedding_used": False}


def reconcile_semantic(root: Path) -> dict[str, Any]:
    base = root / "05_evidence/semantic"; candidates = load_jsonl(base / "semantic_claim_candidates.jsonl"); tasks = []
    for claim in candidates:
        statuses = set(claim.get("statuses") or [])
        reasons = []
        if len(statuses) > 1 or statuses & {"contradict", "mixed", "not-significant"}: reasons.append("direction-or-significance-conflict")
        studies = int(claim.get("independent_studies") or 0)
        # A second pass is deliberately selective: ordinary single-study facts
        # remain in their extraction, while synthesis claims and conflicts are reconciled.
        if claim.get("support_check") in {None, "", "pending"} and studies >= 3: reasons.append("support-pending-high-impact")
        if studies >= 3: reasons.append("high-impact-synthesis")
        if reasons: tasks.append({"semantic_claim_id": claim.get("semantic_claim_id"), "claim": claim.get("claim"), "record_ids": claim.get("record_ids") or [], "anchors": claim.get("anchors") or [], "reasons": reasons, "terminology_decision": "", "adjudicated_support": "pending", "reconciliation_status": "pending"})
    path = base / "reconciliation_tasks.jsonl"
    previous = {x.get("semantic_claim_id"): x for x in load_jsonl(path)} if path.exists() else {}
    tasks = [{**task, **previous[task["semantic_claim_id"]]} if previous.get(task["semantic_claim_id"], {}).get("reconciliation_status") == "completed" else task for task in tasks]
    write_jsonl(path, tasks); pending = sum(x.get("reconciliation_status") != "completed" for x in tasks)
    report = {"phase": "reconcile", "status": "needs-review" if pending else "validated", "tasks": len(tasks), "pending": pending, "rule": "Host reviews only conflicts, terminology mismatch, low-confidence and high-impact syntheses."}
    write_json(base / "semantic_reconcile_report.json", report); return report


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
    reconciliation = load_jsonl(root / "05_evidence/semantic/reconciliation_tasks.jsonl")
    pending_reconciliation = [x.get("semantic_claim_id") for x in reconciliation if x.get("reconciliation_status") != "completed"]
    if pending_reconciliation: warnings.append(f"{len(pending_reconciliation)} semantic reconciliation tasks remain pending; pending claims cannot support final prose")
    report = {"phase": "validate", "valid": not errors, "completed_records": len(rows), "errors": errors, "warnings": warnings, "embedding_used": False}
    write_json(root / "07_logs/semantic_validation.json", report); return report


def embedding_dry_run(root: Path) -> dict[str, Any]:
    records = load_jsonl(root / "02_corpus/corpus.jsonl"); fulltexts = list((root / "03_fulltext/extracted").glob("*.md"))
    characters = sum(len(r.get("title", "")) + len(r.get("abstract", "")) for r in records) + sum(p.stat().st_size for p in fulltexts)
    chunks = max(len(records), math.ceil(characters / 2400))
    return {"status": "interface-only", "dry_run": True, "documents": len(records), "fulltext_files": len(fulltexts), "estimated_chunks": chunks, "estimated_model_download": "hundreds of MB to several GB depending on future model", "hardware_note": "CPU-only full-text encoding may be slow; GPU is optional but not detected by the base workflow.", "dependencies_installed": False, "download_started": False, "embedding_used": False, "message": "This release intentionally provides no inference implementation and never downloads a model."}
