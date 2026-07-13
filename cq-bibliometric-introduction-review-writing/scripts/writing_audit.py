#!/usr/bin/env python3
"""Sentence-level evidence binding and funnel-role audit for final manuscripts."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from common import load_jsonl, read_json, write_json, write_jsonl


FACTUAL = re.compile(r"研究|文献|证据|语料|发现|表明|显示|影响|导致|机制|中介|调节|相关|增长|下降|stud(?:y|ies)|evidence|findings?|affects?|causes?|associated|mediates?|moderates?", re.I)
CAUSAL = re.compile(r"导致|引起|决定|驱动|causes?|leads? to|determines?|drives?", re.I)
ROLE = re.compile(r"\[role:([a-z-]+)\]", re.I)
INTRO_ROLES = {"social-importance", "context-narrowing", "research-progress", "theoretical-tension", "competing-mechanisms", "boundary", "gap", "objective", "contribution"}
DUPLICATE_CITATION_ONLY = re.compile(
    r"(\[cite:(?P<ids>(?:R[0-9a-f]{14}|SCTX-\d{3,})(?:[,;]\s*(?:R[0-9a-f]{14}|SCTX-\d{3,}))*)\][。！？.!?]?)[ \t]*"
    r"(?:\[(?:SC|C)\d{4}\][ \t]*)?(?:[\(（][^()\n（）]*(?:19|20)\d{2}[^()\n（）]*[\)）][ \t]*)\[cite:(?P=ids)\]",
    re.I,
)
MISPLACED_CITATION_ONLY = re.compile(
    r"(?P<stop>[。！？!?])[ \t]*(?P<citation>(?:\[(?:SC|C)\d{4}\][ \t]*)?[\(（][^()\n（）]*(?:19|20)\d{2}[^()\n（）]*[\)）][ \t]*\[cite:(?:R[0-9a-f]{14}|SCTX-\d{3,})(?:[,;][ \t]*(?:R[0-9a-f]{14}|SCTX-\d{3,}))*\])(?=$|[ \t]*[。！？!?])",
    re.I | re.M,
)


def _source(root: Path, document: str, variant: str = "evidence-aware") -> Path:
    if variant == "publication":
        return root / "06_review" / f"{document}_publication_audit.md"
    return root / "06_review" / ("review_draft.md" if document == "review" else "ssci_introduction_audit.md")


def _body(text: str) -> str:
    return re.split(r"(?im)^##\s+参考文献\s*$", text, maxsplit=1)[0]


def _sentences(text: str) -> list[tuple[int, str, str]]:
    rows = []
    for paragraph_index, paragraph in enumerate(re.split(r"\n\s*\n", _body(text)), 1):
        if not paragraph.strip() or paragraph.lstrip().startswith("#"): continue
        role = next(iter(ROLE.findall(paragraph)), "")
        clean = ROLE.sub("", paragraph).strip()
        for sentence in re.split(r"(?<=[。！？!?])\s*", clean):
            if sentence.strip(): rows.append((paragraph_index, role, sentence.strip()))
    return rows


def _candidate_evidence(root: Path, record_ids: list[str]) -> list[dict[str, Any]]:
    corpus = {x.get("record_id"): x for x in load_jsonl(root / "02_corpus/corpus.jsonl")}
    semantic = {p.stem: read_json(p, {}) for p in (root / "05_evidence/semantic/extractions").glob("R*.json")}
    candidates = []
    for record_id in record_ids:
        record, extraction = corpus.get(record_id, {}), semantic.get(record_id, {})
        relations = extraction.get("relations") or []
        candidates.append({
            "record_id": record_id,
            "title": record.get("title", ""),
            "year": record.get("year"),
            "evidence_level": extraction.get("evidence_level") or ("abstract" if record.get("abstract") else "metadata"),
            "design": extraction.get("design", "unclear"),
            "contexts": extraction.get("contexts") or [],
            "outcomes": (extraction.get("variables") or {}).get("outcomes") or [],
            "relevance": extraction.get("relevance", ""),
            "relation_directions": sorted({str(x.get("direction") or x.get("status") or "") for x in relations if x.get("direction") or x.get("status")}),
            "host_review_status": extraction.get("host_review_status", "missing"),
        })
    return candidates


def _report_path(root: Path, document: str, scope: str, variant: str = "evidence-aware") -> Path:
    suffix = "" if scope == "final" else "_" + re.sub(r"[^0-9A-Za-z_-]+", "-", scope).strip("-")[:80]
    variant_suffix = "_publication" if variant == "publication" else ""
    return root / f"07_logs/writing_audit_{document}{variant_suffix}{suffix}.json"


CITE_GROUP = re.compile(r"\[cite:(?:R[0-9a-f]{14}|SCTX-\d{3,})(?:[,;]\s*(?:R[0-9a-f]{14}|SCTX-\d{3,}))*\]", re.I)


def _atomic_units(sentence: str) -> list[str]:
    """Split at top-level semicolons, never inside APA citations or audit tags.

    APA author groups commonly contain semicolons. Treating those separators as
    prose boundaries creates false atomic claims and a misleading repair queue.
    """
    units: list[str] = []
    start = 0
    round_depth = square_depth = 0
    for index, char in enumerate(sentence):
        if char in "(（":
            round_depth += 1
        elif char in ")）":
            round_depth = max(0, round_depth - 1)
        elif char == "[":
            square_depth += 1
        elif char == "]":
            square_depth = max(0, square_depth - 1)
        elif char in ";；" and round_depth == 0 and square_depth == 0:
            part = sentence[start:index + 1].strip()
            if part:
                units.append(part)
            start = index + 1
    tail = sentence[start:].strip()
    if tail:
        units.append(tail)
    return units or [sentence.strip()]


def _atomic_audit_rows(document: str, variant: str, scope: str, sentence_id: str, paragraph: int, sentence: str, prior: dict[str, dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    units = _atomic_units(sentence)
    parent_ids = sorted(set(re.findall(r"R[0-9a-f]{14}", sentence)))
    citation_groups = CITE_GROUP.findall(sentence)
    enumeration = len(re.findall(r"、|(?:以及|并且|同时|分别|和|与)", re.sub(CITE_GROUP, "", sentence)))
    heterogeneous_cluster = len(units) > 1 and len(parent_ids) >= 8 and enumeration >= 2 and len(citation_groups) <= 1
    rows, queue = [], []
    for index, unit in enumerate(units, 1):
        plain = re.sub(r"\[(?:cite:)?[^\]]+\]", "", unit).strip()
        atomic_id = "A" + hashlib.sha256(f"{document}|{variant}|{scope}|{sentence_id}|{plain}".encode("utf-8")).hexdigest()[:14]
        record_ids = sorted(set(re.findall(r"R[0-9a-f]{14}", unit)))
        factual = bool(FACTUAL.search(plain))
        previous = prior.get(atomic_id, {})
        status = previous.get("support_status", "pending" if factual else "not-applicable")
        row = {
            "atomic_claim_id": atomic_id, "parent_sentence_id": sentence_id, "document": document,
            "variant": variant, "scope": scope, "paragraph": paragraph, "unit_index": index,
            "claim_text": plain, "record_ids": record_ids, "object": previous.get("object", ""),
            "mechanism": previous.get("mechanism", ""), "outcome": previous.get("outcome", ""),
            "context": previous.get("context", ""), "evidence_direction": previous.get("evidence_direction", ""),
            "evidence_level": previous.get("evidence_level", ""), "support_status": status,
            "audit_notes": previous.get("audit_notes", ""),
        }
        reasons = []
        if factual and len(units) > 1 and not record_ids and parent_ids:
            reasons.append("atomic-claim-lacks-exact-citation")
        if factual and heterogeneous_cluster:
            reasons.append("heterogeneous-claims-share-one-large-citation-cluster")
        if reasons:
            queue.append({
                "atomic_claim_id": atomic_id, "parent_sentence_id": sentence_id, "document": document,
                "variant": variant, "scope": scope, "paragraph": paragraph, "claim_text": plain,
                "reason_codes": reasons, "parent_candidate_record_ids": parent_ids,
                "repair_rule": "Host must split the sentence into the smallest verifiable claims and place only semantically matching citations immediately after each claim.",
                "repair_status": "host-review-required",
            })
        rows.append(row)
    return rows, queue


def audit_writing(root: Path, document: str, source_path: Path | None = None, scope: str = "final", variant: str = "evidence-aware") -> dict[str, Any]:
    if document not in {"review", "introduction"}: raise ValueError("document must be review or introduction")
    if variant not in {"evidence-aware", "publication"}: raise ValueError("variant must be evidence-aware or publication")
    scope = str(scope or "final").strip() or "final"
    source = Path(source_path) if source_path else _source(root, document, variant)
    if not source.is_absolute(): source = root / source
    if not source.exists(): raise RuntimeError(f"manuscript not found: {source}")
    ledger_path = root / "05_evidence/prose_claim_ledger.jsonl"
    existing_rows = load_jsonl(ledger_path)
    existing = {x.get("sentence_id"): x for x in existing_rows if x.get("variant", "evidence-aware") == variant}
    evidence_fallback = {}
    publication_reviews: dict[str, dict[str, Any]] = {}
    if variant == "publication":
        for item in existing_rows:
            if item.get("document") != document or item.get("variant", "evidence-aware") != "evidence-aware": continue
            key = re.sub(r"[ \t]*[\(（][^()\n（）]*(?:19|20)\d{2}[^()\n（）]*[\)）](?=[。！？.!?]?$)", "", str(item.get("sentence") or "")).strip()
            evidence_fallback[key] = item
        publication_reviews = {
            str(item.get("sentence_id") or ""): item
            for item in load_jsonl(root / "05_evidence/publication_support_reviews.jsonl")
            if item.get("document") == document and item.get("sentence_id")
        }
    atomic_path = root / "05_evidence/prose_atomic_claim_ledger.jsonl"
    atomic_existing_rows = load_jsonl(atomic_path)
    atomic_existing = {x.get("atomic_claim_id"): x for x in atomic_existing_rows if x.get("variant", "evidence-aware") == variant}
    corpus_ids = {x.get("record_id") for x in load_jsonl(root / "02_corpus/corpus.jsonl")}
    social_ids = {x.get("source_id") or f"SCTX-{i:03d}" for i, x in enumerate(load_jsonl(root / "06_review/social_context_sources.jsonl"), 1)} if document == "introduction" else set()
    rows, errors, warnings, repair_queue, atomic_rows, atomic_queue = [], [], [], [], [], []
    source_text = source.read_text(encoding="utf-8")
    # Removing an immediately repeated citation-only fragment is a formatting
    # repair, not evidence rebinding: the same audit IDs already occur in the
    # preceding supported sentence. Different bindings remain in the queue.
    source_text, duplicate_repairs = DUPLICATE_CITATION_ONLY.subn(r"\1", source_text)
    source_text, position_repairs = MISPLACED_CITATION_ONLY.subn(r" \g<citation>\g<stop>", source_text)
    if duplicate_repairs or position_repairs:
        source.write_text(source_text, encoding="utf-8")
    sentence_rows = _sentences(source_text)
    paragraph_ids: dict[int, list[str]] = {}
    for paragraph, _, sentence in sentence_rows:
        paragraph_ids.setdefault(paragraph, []).extend(re.findall(r"R[0-9a-f]{14}", sentence))
    paragraph_ids = {key: list(dict.fromkeys(value)) for key, value in paragraph_ids.items()}
    paragraph_bindings: dict[int, list[tuple[str, ...]]] = {}
    for paragraph, role, sentence in sentence_rows:
        plain = re.sub(r"\[(?:cite:)?[^\]]+\]", "", sentence).strip()
        semantic_plain = re.sub(r"[ \t]*[\(（][^()\n（）]*(?:19|20)\d{2}[^()\n（）]*[\)）](?=[。！？.!?]?$)", "", plain).strip()
        sid_seed = f"{document}|{scope}|{semantic_plain}" if variant == "evidence-aware" else f"{document}|{variant}|{scope}|{semantic_plain}"
        sid = "S" + hashlib.sha256(sid_seed.encode("utf-8")).hexdigest()[:14]
        record_ids = sorted(set(re.findall(r"R[0-9a-f]{14}", sentence))); source_ids = sorted(set(re.findall(r"SCTX-\d{3,}", sentence)))
        if document == "introduction" and paragraph == 1 and not source_ids and social_ids: source_ids = sorted(social_ids)  # legacy source registries predated visible audit IDs
        factual = bool(FACTUAL.search(plain))
        legacy_sid = "S" + hashlib.sha256(f"{document}|{plain}".encode("utf-8")).hexdigest()[:14]
        semantic_legacy_sid = "S" + hashlib.sha256(f"{document}|{semantic_plain}".encode("utf-8")).hexdigest()[:14]
        prior = existing.get(sid, existing.get(legacy_sid, existing.get(semantic_legacy_sid, evidence_fallback.get(semantic_plain, {}))))
        if sid in publication_reviews:
            # Publication rewrites require an explicit host decision.  The
            # review file is a compact, auditable overlay rather than a bulk
            # mutation of generated ledger rows.
            prior = {**prior, **publication_reviews[sid]}
        row = {"sentence_id": sid, "document": document, "variant": variant, "scope": scope, "source": str(source), "paragraph": paragraph, "funnel_role": role, "sentence": plain, "record_ids": record_ids, "source_ids": source_ids, "claim_ids": sorted(set(re.findall(r"(?:SC|C)\d{4}", sentence))), "factual": factual, "claim_scope": prior.get("claim_scope", ""), "evidence_direction": prior.get("evidence_direction", ""), "design_fit": prior.get("design_fit", "pending" if factual else "not-applicable"), "evidence_level": prior.get("evidence_level", ""), "independent_samples": prior.get("independent_samples"), "counterevidence": prior.get("counterevidence", []), "support_status": prior.get("support_status", "pending" if factual else "not-applicable"), "audit_notes": prior.get("audit_notes", "")}
        reason_codes = []
        unknown = set(record_ids) - corpus_ids
        if unknown: errors.append(f"{sid} unknown record IDs: {sorted(unknown)}")
        unknown_sources = set(source_ids) - social_ids
        if unknown_sources: errors.append(f"{sid} unknown social source IDs: {sorted(unknown_sources)}")
        if factual and not (record_ids or source_ids): errors.append(f"{sid} factual sentence lacks an exact-sentence citation"); reason_codes.append("missing-exact-sentence-citation")
        if factual and row["support_status"] == "unsupported": errors.append(f"{sid} is unsupported"); reason_codes.append("citation-does-not-support-sentence")
        if factual and row["support_status"] == "pending": errors.append(f"{sid} support remains pending"); reason_codes.append("semantic-support-not-reviewed")
        if factual and row["support_status"] == "partial" and not row["audit_notes"]: errors.append(f"{sid} partial support requires narrowed wording/audit note")
        if factual and row["support_status"] in {"supported", "partial"}:
            missing_support = [field for field in ("evidence_level", "claim_scope", "audit_notes") if not row.get(field)]
            if not (record_ids or source_ids): missing_support.append("evidence_id")
            if missing_support:
                errors.append(f"{sid} support approval lacks required audit fields: {sorted(set(missing_support))}")
                reason_codes.append("incomplete-support-audit")
        if CAUSAL.search(plain) and row["design_fit"] not in {"causal-design", "causal-language-narrowed"}: errors.append(f"{sid} causal wording lacks design-fit approval")
        if factual and (row["independent_samples"] or 0) < 3 and re.search(r"普遍|一致|稳定|大量研究|generally|consistently", plain, re.I): warnings.append(f"{sid} broad synthesis has fewer than 3 verified independent samples")
        if re.fullmatch(r"[\s(（][^()（）]*(?:19|20)\d{2}[^()（）]*[)）]\s*[.。]?”?", plain):
            errors.append(f"{sid} citation-only fragment must be attached to a supported sentence"); reason_codes.append("citation-only-fragment")
        binding = tuple(record_ids + source_ids)
        if binding: paragraph_bindings.setdefault(paragraph, []).append(binding)
        if reason_codes:
            repair_queue.append({"sentence_id": sid, "document": document, "scope": scope, "source": str(source), "paragraph": paragraph, "sentence": plain, "reason_codes": sorted(set(reason_codes)), "paragraph_candidate_record_ids": paragraph_ids.get(paragraph, []), "candidate_evidence": _candidate_evidence(root, paragraph_ids.get(paragraph, [])), "repair_rule": "Host must re-read candidate evidence and bind only semantically supporting sources; never copy all paragraph citations mechanically.", "repair_status": "host-review-required"})
        rows.append(row)
        sentence_atomic_rows, sentence_atomic_queue = _atomic_audit_rows(document, variant, scope, sid, paragraph, sentence, atomic_existing)
        atomic_rows.extend(sentence_atomic_rows); atomic_queue.extend(sentence_atomic_queue)
    for paragraph, bindings in paragraph_bindings.items():
        if len(bindings) >= 3 and len(set(bindings)) == 1:
            warnings.append(f"paragraph {paragraph} repeats the same audit binding mechanically; verify sentence-level support")
    if atomic_queue:
        message = f"{len(atomic_queue)} atomic claims require citation attribution repair"
        (errors if variant == "publication" else warnings).append(message)
    retained = [x for x in existing_rows if not (x.get("document") == document and x.get("variant", "evidence-aware") == variant and str(x.get("scope") or "final") == scope)]; write_jsonl(ledger_path, retained + rows)
    retained_atomic = [x for x in atomic_existing_rows if not (x.get("document") == document and x.get("variant", "evidence-aware") == variant and str(x.get("scope") or "final") == scope)]
    write_jsonl(atomic_path, retained_atomic + atomic_rows)
    queue_path = root / "05_evidence/citation_repair_queue.jsonl"
    retained_queue = [x for x in load_jsonl(queue_path) if not (x.get("document") == document and str(x.get("scope") or "final") == scope)]
    write_jsonl(queue_path, retained_queue + repair_queue)
    attribution_path = root / "05_evidence/citation_attribution_queue.jsonl"
    retained_attribution = [x for x in load_jsonl(attribution_path) if not (x.get("document") == document and x.get("variant", "evidence-aware") == variant and str(x.get("scope") or "final") == scope)]
    write_jsonl(attribution_path, retained_attribution + atomic_queue)
    if document == "introduction" and scope == "final":
        observed = {x[1] for x in sentence_rows if x[1]}; missing_roles = sorted(INTRO_ROLES - observed)
        if missing_roles: errors.append(f"introduction funnel roles missing: {missing_roles}")
    report = {"document": document, "variant": variant, "scope": scope, "status": "validated" if not errors else "needs-review", "valid": not errors, "source": str(source), "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(), "sentences": len(rows), "factual_sentences": sum(x["factual"] for x in rows), "atomic_claims": len(atomic_rows), "atomic_repair_queue_items": len(atomic_queue), "automatic_duplicate_citation_repairs": duplicate_repairs, "automatic_citation_position_repairs": position_repairs, "repair_queue_items": len(repair_queue), "errors": errors, "warnings": list(dict.fromkeys(warnings)), "ledger": str(ledger_path), "atomic_ledger": str(atomic_path), "repair_queue": str(queue_path), "citation_attribution_queue": str(attribution_path)}
    write_json(_report_path(root, document, scope, variant), report); return report
