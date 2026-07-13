#!/usr/bin/env python3
"""Prepare and validate reader-facing publication variants without weakening evidence."""
from __future__ import annotations

import hashlib
import re
import shutil
from pathlib import Path
from typing import Any

from common import load_jsonl, write_json, write_jsonl
from evidence import manuscript_path, punctuation_errors, split_embedded_references, sync_references
from writing_audit import audit_writing


PUBLICATION_BANNED = {
    "聚焦语料": r"聚焦语料",
    "核心语料": r"核心语料",
    "全部语料": r"全部语料",
    "当前语料": r"当前语料",
    "当前证据": r"当前证据",
    "本任务": r"本任务",
    "摘要证据": r"摘要(?:级)?证据|证据(?:主要)?(?:来自|以)摘要(?:为主)?|摘要(?:层面|级|报告|所报告|无法|不能)",
    "全文级证据": r"全文级证据|全文(?:不足|有限|核验|可用性)",
    "直接证据": r"直接证据",
    "邻近证据": r"邻近证据",
    "证据等级": r"证据等级",
    "证据卡": r"证据卡",
    "证据不足提示": r"证据(?:仍|尚|还)?(?:不足|有限)|不足以(?:证明|判断)",
}
PROPOSITION = re.compile(r"本研究(?:提出|认为|拟|将)|有待(?:检验|验证)|需要(?:检验|验证)|待检验命题|可能|尚待", re.I)


def _source(root: Path, document: str) -> Path:
    return manuscript_path(root, document, "evidence-aware")


def _publication(root: Path, document: str) -> Path:
    return manuscript_path(root, document, "publication")


def _body_sentences(text: str) -> list[dict[str, Any]]:
    body, _ = split_embedded_references(text)
    rows = []
    for paragraph, block in enumerate(re.split(r"\n\s*\n", body), 1):
        if not block.strip() or block.lstrip().startswith("#"): continue
        clean = re.sub(r"[ \t]*\[role:[a-z-]+\]", "", block, flags=re.I).strip()
        for sentence in re.split(r"(?<=[。！？!?])\s*", clean):
            if sentence.strip(): rows.append({"paragraph": paragraph, "sentence": sentence.strip()})
    return rows


def _banned_hits(text: str) -> list[str]:
    return [label for label, pattern in PUBLICATION_BANNED.items() if re.search(pattern, text, flags=re.I)]


def _semantic_sentence(text: str) -> str:
    text = re.sub(r"[ \t]*\[role:[a-z-]+\]", "", str(text), flags=re.I)
    text = re.sub(r"[ \t]*\[(?:cite:)?[^\]]+\]", "", text, flags=re.I)
    return re.sub(r"\s+", " ", text).strip()


def prepare_publication(root: Path, document: str) -> dict[str, Any]:
    source, target = _source(root, document), _publication(root, document)
    if not source.exists(): raise RuntimeError(f"缺少证据提示版正文：{source}")
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists(): shutil.copyfile(source, target)
    ledger_rows = load_jsonl(root / "05_evidence/prose_claim_ledger.jsonl")
    evidence_rows = [x for x in ledger_rows if x.get("document") == document and x.get("variant", "evidence-aware") == "evidence-aware" and str(x.get("scope") or "final") == "final"]
    publication_rows = [x for x in ledger_rows if x.get("document") == document and x.get("variant") == "publication" and str(x.get("scope") or "final") == "final"]
    support_by_sentence = {_semantic_sentence(x.get("sentence") or ""): x for x in evidence_rows}
    # On resumed tasks the publication ledger is more specific than the
    # evidence-aware source and includes explicit host-reviewed rewrites.
    support_by_sentence.update({_semantic_sentence(x.get("sentence") or ""): x for x in publication_rows})
    queue = []
    for index, item in enumerate(_body_sentences(target.read_text(encoding="utf-8")), 1):
        sentence = item["sentence"]
        support = support_by_sentence.get(_semantic_sentence(sentence), {})
        hits = _banned_hits(sentence)
        status = support.get("support_status", "pending")
        reasons = []
        if hits: reasons.append("reader-facing-workflow-language")
        if status == "partial" and not PROPOSITION.search(sentence): reasons.append("partial-support-must-be-proposition")
        if status == "unsupported": reasons.append("unsupported-claim-must-be-removed")
        if reasons:
            queue.append({
                "queue_id": "P" + hashlib.sha256(f"{document}|{index}|{sentence}".encode("utf-8")).hexdigest()[:14],
                "document": document, "paragraph": item["paragraph"], "sentence": sentence,
                "support_status": status, "record_ids": support.get("record_ids") or re.findall(r"R[0-9a-f]{14}", sentence),
                "reason_codes": sorted(set(reasons)), "banned_terms": hits,
                "required_action": "rewrite-as-testable-proposition" if status == "partial" else "remove" if status == "unsupported" else "rewrite-reader-facing",
                "rule": "Remove workflow/evidence-level wording without upgrading certainty; split heterogeneous claims and bind citations at the smallest verifiable claim.",
                "status": "host-review-required",
            })
    queue_path = root / "05_evidence/publication_rewrite_queue.jsonl"
    retained = [x for x in load_jsonl(queue_path) if x.get("document") != document]
    write_jsonl(queue_path, retained + queue)
    report = {"phase": "prepare", "document": document, "status": "prepared", "source": str(source), "publication_audit": str(target), "rewrite_queue": str(queue_path), "queue_items": len(queue), "source_preserved": True}
    write_json(root / f"07_logs/publication_prepare_{document}.json", report); return report


def compile_publication(root: Path, document: str) -> dict[str, Any]:
    target = _publication(root, document)
    if not target.exists(): raise RuntimeError("缺少投稿审计稿；请先运行 build-publication --phase prepare 并由宿主完成改写。")
    sync = sync_references(root, document, target, variant="publication")
    audit = audit_writing(root, document, target, "final", variant="publication")
    report = {"phase": "compile", "document": document, "status": "compiled" if audit.get("valid") else "needs-review", "valid": audit.get("valid", False), "reference_sync": sync, "writing_audit": audit}
    write_json(root / f"07_logs/publication_compile_{document}.json", report); return report


def validate_publication(root: Path, document: str) -> dict[str, Any]:
    target = _publication(root, document); clean = manuscript_path(root, document, "publication", clean=True)
    if not target.exists(): raise RuntimeError("投稿审计稿不存在")
    audit = audit_writing(root, document, target, "final", variant="publication")
    text = target.read_text(encoding="utf-8"); body, references = split_embedded_references(text)
    errors, warnings = list(audit.get("errors") or []), list(audit.get("warnings") or [])
    hits = _banned_hits(body)
    if hits: errors.append(f"投稿正文仍含内部证据状态语言：{sorted(hits)}")
    publication_rows = [x for x in load_jsonl(root / "05_evidence/prose_claim_ledger.jsonl") if x.get("document") == document and x.get("variant") == "publication" and str(x.get("scope") or "final") == "final"]
    for row in publication_rows:
        status, sentence = row.get("support_status"), str(row.get("sentence") or "")
        if status == "unsupported": errors.append(f"{row.get('sentence_id')} unsupported claim remains in publication text")
        if status == "partial" and not PROPOSITION.search(sentence): errors.append(f"{row.get('sentence_id')} partial claim is not written as a testable proposition")
    if not references: errors.append("投稿版缺少同步参考文献")
    if not clean.exists(): errors.append("投稿清洁版不存在")
    else:
        clean_text = clean.read_text(encoding="utf-8")
        if re.search(r"\b(?:R[0-9a-f]{14}|C\d{4}|SCTX-\d{3,})\b", clean_text): errors.append("投稿清洁版仍含内部ID")
        errors.extend(punctuation_errors(clean_text, f"{document}投稿清洁版"))
        if document == "introduction":
            clean_body, _ = split_embedded_references(clean_text)
            paragraphs = [p for p in re.split(r"\n\s*\n", clean_body) if p.strip() and not p.lstrip().startswith("#")]
            if not 8 <= len(paragraphs) <= 12: errors.append(f"投稿绪论应为8–12个自然段，当前{len(paragraphs)}段")
    report = {"phase": "validate", "document": document, "status": "validated" if not errors else "needs-review", "valid": not errors, "errors": list(dict.fromkeys(errors)), "warnings": list(dict.fromkeys(warnings)), "banned_terms": hits, "source": str(target), "clean": str(clean), "source_sha256": hashlib.sha256(target.read_bytes()).hexdigest()}
    write_json(root / f"07_logs/publication_validation_{document}.json", report); return report
