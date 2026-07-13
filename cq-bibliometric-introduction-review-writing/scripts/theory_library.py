#!/usr/bin/env python3
"""External, user-managed theory library with fail-open task integration."""
from __future__ import annotations

import hashlib
import csv
import json
import os
import platform
import re
import shutil
import zipfile
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable

from common import file_sha256, load_jsonl, normalize_title, read_json, utc_stamp, write_json, write_jsonl
from extract import extract_one


THEORY_STATES = {"candidate", "source-located", "content-verified", "disabled"}
SUPPORT_MODES = {"combined", "local-only", "llm-only", "skip"}
SUPPORTED = {".html", ".htm", ".pdf", ".docx", ".doc", ".txt", ".md", ".markdown"}
CARD_FIELDS = (
    "theory_id", "name_zh", "name_en", "aliases", "theory_type", "founders",
    "origin_year", "development", "explanatory_problem", "constructs", "mechanisms",
    "causal_chain", "falsifiable_predictions", "level_of_analysis", "contexts",
    "assumptions", "boundary_conditions", "variable_roles", "competing_theories",
    "complementary_theories", "common_misuses", "measurement", "research_design",
    "search_terms_zh", "search_terms_en", "foundational_sources", "review_sources",
    "verification_notes", "verification_status", "source_files", "source_hashes",
)


def theory_home() -> Path:
    override = os.environ.get("CQ_THEORY_HOME", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    system = platform.system()
    if system == "Darwin":
        return (Path.home() / "Library/Application Support/CQ-BIRW/theories").resolve()
    if system == "Windows":
        base = Path(os.environ.get("APPDATA") or (Path.home() / "AppData/Roaming"))
        return (base / "CQ-BIRW/theories").resolve()
    base = Path(os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local/share"))
    return (base / "cq-birw/theories").resolve()


def ensure_library(home: Path | None = None) -> Path:
    root = (home or theory_home()).expanduser().resolve()
    for name in ("sources", "candidates", "verified", "indexes", "audit"):
        (root / name).mkdir(parents=True, exist_ok=True)
    metadata = root / "library.json"
    if not metadata.exists():
        write_json(metadata, {"schema_version": 1, "created_at": utc_stamp(), "encoding": "UTF-8", "builtin_theories": 0})
    return root


def _library_rows(root: Path, include_disabled: bool = True) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for folder in ("verified", "candidates"):
        for path in sorted((root / folder).glob("*.json")):
            try:
                item = read_json(path, {})
                if item and (include_disabled or item.get("verification_status") != "disabled"):
                    rows.append(item)
            except (OSError, UnicodeError, json.JSONDecodeError):
                continue
    seen: set[str] = set(); unique = []
    for item in rows:
        theory_id = str(item.get("theory_id") or "")
        if theory_id and theory_id not in seen:
            seen.add(theory_id); unique.append(item)
    return unique


def library_status(home: Path | None = None) -> dict[str, Any]:
    root = ensure_library(home); rows = _library_rows(root)
    counts = Counter(str(x.get("verification_status") or "candidate") for x in rows)
    corrupt = []
    for folder in ("verified", "candidates"):
        for path in (root / folder).glob("*.json"):
            try: json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError): corrupt.append(str(path))
    size = sum(p.stat().st_size for p in root.rglob("*") if p.is_file())
    return {"status": "ready", "home": str(root), "cards": len(rows), "states": dict(counts), "corrupt_cards": corrupt, "bytes": size, "builtin_theories": 0}


class _HTMLText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(); self.parts: list[str] = []; self.title: list[str] = []; self._skip = 0; self._title = False
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in {"script", "style", "svg", "noscript"}: self._skip += 1
        if tag.lower() == "title": self._title = True
        if tag.lower() in {"p", "div", "h1", "h2", "h3", "li", "br", "article", "main"}: self.parts.append("\n")
    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "svg", "noscript"} and self._skip: self._skip -= 1
        if tag.lower() == "title": self._title = False
    def handle_data(self, data: str) -> None:
        if self._skip: return
        if self._title: self.title.append(data)
        self.parts.append(data)


def _html_text(path: Path) -> tuple[str, str]:
    parser = _HTMLText(); parser.feed(path.read_text(encoding="utf-8-sig", errors="replace"))
    text = re.sub(r"[ \t]+", " ", "".join(parser.parts)); text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text, re.sub(r"\s+", " ", "".join(parser.title)).strip()


def _expand(inputs: Iterable[Path]) -> list[Path]:
    files: list[Path] = []
    for value in inputs:
        path = value.expanduser()
        if path.is_dir(): files.extend(p for p in path.rglob("*") if p.is_file() and p.suffix.lower() in SUPPORTED)
        elif path.is_file() and path.suffix.lower() in SUPPORTED: files.append(path)
    return sorted(set(p.resolve() for p in files))


def _candidate_name(path: Path, text: str, html_title: str = "") -> str:
    # Saved web pages are commonly named index.html; their parent folder holds
    # the article/theory title and is more discriminating than the HTML shell title.
    candidates = [path.parent.name if path.stem.lower() == "index" else "", html_title, path.stem]
    candidates += [x.strip("# *\t") for x in text.splitlines()[:12] if x.strip()]
    fallbacks = []
    for value in candidates:
        clean = re.sub(r"\s+", " ", value).strip()
        clean = re.sub(r"^\d{4}[-/.年]\d{1,2}[-/.月]\d{1,2}日?\s*", "", clean)
        clean = re.sub(r"^(?:研究)?(?:理论|模型)(?:介绍|集锦)?\s*[|｜丨:：·—-]*\s*", "", clean)
        clean = clean.strip(" |｜丨:：·—-")
        if clean and clean.lower() != "index": fallbacks.append(clean)
        match = re.search(r"([A-Za-z][A-Za-z0-9\- '\u2019]{2,80}(?:theory|model|framework)|[\u4e00-\u9fffA-Za-z0-9·—\-]{2,50}(?:理论|模型|框架|视角))", clean, re.I)
        if match: return match.group(1).strip()
    return (fallbacks[0][:120] if fallbacks else re.sub(r"[_-]+", " ", path.stem).strip()[:120]) or "Unnamed theory candidate"


def _theory_id(name: str) -> str:
    return "T" + hashlib.sha1(normalize_title(name).encode("utf-8")).hexdigest()[:14]


def empty_card(name: str, source: Path | None = None, digest: str = "") -> dict[str, Any]:
    zh = name if re.search(r"[\u4e00-\u9fff]", name) else ""
    en = name if not zh else ""
    card: dict[str, Any] = {field: [] for field in CARD_FIELDS}
    card.update({
        "theory_id": _theory_id(name), "name_zh": zh, "name_en": en, "aliases": [],
        "theory_type": "unclassified", "origin_year": None, "development": "",
        "explanatory_problem": "", "causal_chain": "", "level_of_analysis": "",
        "verification_notes": "", "verification_status": "candidate",
        "source_files": [str(source)] if source else [], "source_hashes": [digest] if digest else [],
        "host_review_status": "pending", "created_at": utc_stamp(), "updated_at": utc_stamp(),
    })
    return card


def _merge_card(old: dict[str, Any], new: dict[str, Any]) -> dict[str, Any]:
    out = dict(old)
    for key in CARD_FIELDS:
        left, right = out.get(key), new.get(key)
        if isinstance(left, list) or isinstance(right, list):
            values = (left if isinstance(left, list) else ([left] if left else [])) + (right if isinstance(right, list) else ([right] if right else []))
            out[key] = list(dict.fromkeys(str(x) if not isinstance(x, dict) else json.dumps(x, ensure_ascii=False, sort_keys=True) for x in values))
            out[key] = [json.loads(x) if isinstance(x, str) and x.startswith("{") else x for x in out[key]]
        elif not left and right: out[key] = right
    out["updated_at"] = utc_stamp(); return out


def ingest_theories(inputs: Iterable[Path], home: Path | None = None, copy_sources: bool = False) -> dict[str, Any]:
    root = ensure_library(home); files = _expand(inputs); existing = {x["theory_id"]: x for x in _library_rows(root)}
    imported = merged = 0; errors: list[dict[str, str]] = []; registry = load_jsonl(root / "sources/registry.jsonl")
    for path in files:
        try:
            digest = file_sha256(path)
            if path.suffix.lower() in {".html", ".htm"}: text, title = _html_text(path)
            else: text, _ = extract_one(path); title = ""
            name = _candidate_name(path, text, title); card = empty_card(name, path, digest)
            card["source_excerpt"] = re.sub(r"\s+", " ", text)[:4000]
            if card["theory_id"] in existing:
                card = _merge_card(existing[card["theory_id"]], card); merged += 1
            else: imported += 1
            target = root / "candidates" / f"{card['theory_id']}.json"; write_json(target, card); existing[card["theory_id"]] = card
            managed = ""
            if copy_sources:
                managed_path = root / "sources" / f"{digest[:12]}-{path.name}"
                if not managed_path.exists(): shutil.copy2(path, managed_path)
                managed = str(managed_path)
            registry.append({"source": str(path), "managed_copy": managed, "sha256": digest, "theory_id": card["theory_id"], "ingested_at": utc_stamp()})
        except Exception as exc: errors.append({"file": str(path), "error": str(exc)})
    unique_registry: dict[tuple[str, str], dict[str, Any]] = {}
    for item in registry: unique_registry[(str(item.get("sha256") or ""), str(item.get("theory_id") or ""))] = item
    write_jsonl(root / "sources/registry.jsonl", unique_registry.values()); rebuild_index(root)
    report = {"status": "ready" if not errors else "degraded", "files": len(files), "imported": imported, "merged": merged, "errors": errors, "home": str(root), "copy_sources": copy_sources}
    write_json(root / "audit/last_ingest.json", report); return report


def rebuild_index(root: Path) -> dict[str, Any]:
    rows = _library_rows(root, include_disabled=False); index: dict[str, list[str]] = {}
    for card in rows:
        terms = [card.get("name_zh"), card.get("name_en")] + list(card.get("aliases") or []) + list(card.get("search_terms_zh") or []) + list(card.get("search_terms_en") or [])
        for value in terms:
            key = normalize_title(value)
            if key: index.setdefault(key, []).append(card["theory_id"])
    write_json(root / "indexes/term_index.json", {k: sorted(set(v)) for k, v in index.items()}); return {"terms": len(index), "cards": len(rows)}


def verify_theories(phase: str, home: Path | None = None) -> dict[str, Any]:
    root = ensure_library(home); rows = _library_rows(root); warnings: list[str] = []
    if phase == "prepare":
        queue = [{"theory_id": x["theory_id"], "name": x.get("name_zh") or x.get("name_en"), "required": ["core constructs", "mechanisms", "boundaries", "foundational source", "verification notes"], "source_files": x.get("source_files") or []} for x in rows if x.get("verification_status") not in {"content-verified", "disabled"}]
        write_jsonl(root / "audit/verification_queue.jsonl", queue)
        return {"phase": phase, "status": "prepared", "candidates": len(queue), "host_action": "核对奠基文献或权威综述后补全候选理论卡；不得仅凭网页概述晋升。"}
    if phase == "compile":
        updated = 0
        for card in rows:
            if card.get("verification_status") in {"disabled", "content-verified"}: continue
            sources = card.get("foundational_sources") or card.get("review_sources") or []
            complete = bool(card.get("host_review_status") == "completed" and card.get("constructs") and card.get("mechanisms") and card.get("boundary_conditions") and sources and card.get("verification_notes"))
            if complete:
                card["verification_status"] = "source-located"; updated += 1
            write_json(root / "candidates" / f"{card['theory_id']}.json", card)
        rebuild_index(root)
        return {"phase": phase, "status": "ready", "source_located": updated, "note": "晋升content-verified仍需显式promote --confirm。"}
    for card in rows:
        state = card.get("verification_status")
        if state not in THEORY_STATES: warnings.append(f"{card.get('theory_id')}: unknown state {state}")
        if state == "content-verified" and not (card.get("foundational_sources") or card.get("review_sources")): warnings.append(f"{card.get('theory_id')}: verified card lacks authoritative source")
    report = {"phase": phase, "status": "validated" if not warnings else "degraded", "valid": not warnings, "warnings": warnings, "non_blocking": True}
    write_json(root / "audit/verification_report.json", report); return report


def promote_theories(ids: Iterable[str], confirmed: bool, home: Path | None = None) -> dict[str, Any]:
    if not confirmed: return {"status": "needs-confirmation", "promoted": 0, "non_blocking": True}
    root = ensure_library(home); promoted = 0; skipped = []
    for theory_id in ids:
        source = root / "candidates" / f"{theory_id}.json"; card = read_json(source, {})
        if not card or card.get("verification_status") != "source-located": skipped.append({"theory_id": theory_id, "reason": "not-source-located"}); continue
        card.update({"verification_status": "content-verified", "verified_at": utc_stamp(), "updated_at": utc_stamp()})
        write_json(root / "verified" / f"{theory_id}.json", card); source.unlink(missing_ok=True); promoted += 1
    rebuild_index(root); return {"status": "validated" if promoted else "degraded", "promoted": promoted, "skipped": skipped, "non_blocking": True}


def search_theories(query: str, limit: int = 8, home: Path | None = None, verified_only: bool = False) -> list[dict[str, Any]]:
    root = ensure_library(home); q = set(re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]{2,}", query.lower()))
    scored = []
    for card in _library_rows(root, include_disabled=False):
        if verified_only and card.get("verification_status") != "content-verified": continue
        searchable = " ".join(str(card.get(k) or "") for k in ("name_zh", "name_en", "aliases", "constructs", "mechanisms", "contexts", "search_terms_zh", "search_terms_en")).lower()
        score = sum(3 if token in normalize_title((card.get("name_zh") or "") + (card.get("name_en") or "")) else 1 for token in q if token in searchable)
        if score: scored.append((score, card))
    return [{**card, "match_score": score} for score, card in sorted(scored, key=lambda x: (-x[0], x[1]["theory_id"]))[:limit]]


def show_theory(theory_id: str, home: Path | None = None) -> dict[str, Any]:
    root = ensure_library(home)
    for folder in ("verified", "candidates"):
        card = read_json(root / folder / f"{theory_id}.json", {})
        if card: return card
    return {"status": "not-found", "theory_id": theory_id}


def update_theory(theory_id: str, input_path: Path, home: Path | None = None) -> dict[str, Any]:
    root = ensure_library(home); incoming = read_json(input_path.expanduser().resolve(), {})
    if not incoming: return {"status": "degraded", "reason": "empty-or-invalid-update", "non_blocking": True}
    current = show_theory(theory_id, root)
    if current.get("status") == "not-found": return {"status": "degraded", "reason": "theory-not-found", "non_blocking": True}
    incoming["theory_id"] = theory_id; merged = _merge_card(current, incoming)
    state = merged.get("verification_status") if merged.get("verification_status") in THEORY_STATES else "candidate"; folder = "verified" if state == "content-verified" else "candidates"
    write_json(root / folder / f"{theory_id}.json", merged); rebuild_index(root); return {"status": "ready", "theory_id": theory_id}


def disable_theory(theory_id: str, home: Path | None = None) -> dict[str, Any]:
    root = ensure_library(home); card = show_theory(theory_id, root)
    if card.get("status") == "not-found": return {"status": "degraded", "reason": "theory-not-found", "non_blocking": True}
    for folder in ("verified", "candidates"): (root / folder / f"{theory_id}.json").unlink(missing_ok=True)
    card.update({"verification_status": "disabled", "updated_at": utc_stamp()}); write_json(root / "candidates" / f"{theory_id}.json", card); rebuild_index(root)
    return {"status": "disabled", "theory_id": theory_id}


def export_library(output: Path, home: Path | None = None) -> dict[str, Any]:
    root = ensure_library(home); output = output.expanduser().resolve(); output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in root.rglob("*"):
            if path.is_file(): archive.write(path, path.relative_to(root).as_posix())
    return {"status": "ready", "output": str(output), "sha256": file_sha256(output)}


def import_library(bundle: Path, home: Path | None = None) -> dict[str, Any]:
    root = ensure_library(home); imported = 0; rejected = []
    with zipfile.ZipFile(bundle.expanduser().resolve()) as archive:
        for member in archive.infolist():
            target = (root / member.filename).resolve()
            try: target.relative_to(root)
            except ValueError: rejected.append(member.filename); continue
            if member.is_dir(): continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as src, target.open("wb") as dst: shutil.copyfileobj(src, dst)
            imported += 1
    rebuild_index(root); return {"status": "ready" if not rejected else "degraded", "imported_files": imported, "rejected": rejected}


def set_task_support(root: Path, mode: str) -> dict[str, Any]:
    if mode not in SUPPORT_MODES: raise ValueError(f"unknown theory support mode: {mode}")
    manifest = read_json(root / "manifest.json", {}); manifest.update({"theory_support_mode": mode, "theory_support_selected_at": utc_stamp(), "theory_support_non_blocking": True})
    write_json(root / "manifest.json", manifest)
    report = {"status": "skipped" if mode == "skip" else "ready", "mode": mode, "non_blocking": True, "next": "continue-writing" if mode == "skip" else "theory-recommend --phase prepare"}
    return report


def theory_support_needed(root: Path) -> bool:
    brief = read_json(root / "06_review/review_brief.json", {})
    gaps = load_jsonl(root / "05_evidence/gaps/gap_ledger.jsonl")
    outline = (root / "06_review/outline.md").read_text(encoding="utf-8", errors="replace") if (root / "06_review/outline.md").exists() else ""
    return bool(brief.get("model_package_requested") or any(x.get("level") in {"A", "B"} for x in gaps) or re.search(r"理论|机制|模型|hypothes|theor|mechanism", outline, re.I))


def _task_query(root: Path) -> str:
    plan = read_json(root / "00_plan/search_plan.json", {}); gaps = load_jsonl(root / "05_evidence/gaps/gap_ledger.jsonl")
    values = [plan.get("title_or_idea", ""), plan.get("research_question", "")]
    for gap in gaps: values += [gap.get("title", ""), gap.get("failure_point", ""), " ".join(gap.get("current_explanation") or [])]
    return " ".join(str(x) for x in values if x)


def prepare_recommendations(root: Path, limit: int = 8, home: Path | None = None) -> dict[str, Any]:
    base = root / "05_evidence/theories"; base.mkdir(parents=True, exist_ok=True)
    manifest = read_json(root / "manifest.json", {}); mode = manifest.get("theory_support_mode", "unselected"); query = _task_query(root)
    requirements = {"research_context": query, "required_checks": ["explanatory fit", "assumptions", "boundaries", "competing explanations", "task evidence"], "mode": mode, "generated_at": utc_stamp()}
    write_json(base / "theory_requirements.json", requirements)
    (base / "theory_requirements.md").write_text("# Theory requirements\n\n- mode: " + mode + "\n- research context: " + query + "\n\n理论仅作为解释导航，不是当前任务的经验性证据。\n", encoding="utf-8")
    local = [] if mode in {"llm-only", "skip"} else search_theories(query, limit, home)
    candidates = [{"theory_id": x["theory_id"], "name": x.get("name_zh") or x.get("name_en"), "origin": "local-library", "verification_status": x.get("verification_status"), "match_score": x.get("match_score"), "fit_status": "pending", "fit_rationale": "", "explanatory_target": "", "assumption_fit": "unchecked", "boundary_fit": "unchecked", "competing_theories": x.get("competing_theories") or [], "task_record_ids": [], "decision": "pending"} for x in local]
    if mode in {"combined", "llm-only"}:
        candidates.append({"theory_id": "LLM-CANDIDATES-REQUIRED", "name": "宿主模型补充候选", "origin": "host-llm", "verification_status": "candidate", "fit_status": "pending", "decision": "pending", "instruction": "根据需求提出可能遗漏的理论；逐条登记来源，不得把模型记忆当作已核验来源。"})
    write_jsonl(base / "theory_candidates.jsonl", candidates)
    if not (base / "theory_fit_ledger.jsonl").exists(): write_jsonl(base / "theory_fit_ledger.jsonl", candidates)
    status = "skipped" if mode == "skip" else "exploratory" if candidates else "degraded"
    report = {"phase": "prepare", "status": status, "mode": mode, "candidates": len(candidates), "local_candidates": len(local), "non_blocking": True}
    write_json(base / "theory_prepare_report.json", report); return report


def compile_recommendations(root: Path) -> dict[str, Any]:
    base = root / "05_evidence/theories"; rows = load_jsonl(base / "theory_fit_ledger.jsonl")
    adopted = []; warnings = []; rewrite_queue = []
    for row in rows:
        if row.get("decision") != "adopt": continue
        verified = row.get("verification_status") == "content-verified" or row.get("source_verified") is True
        fit = all(str(row.get(x, "")).lower() not in {"", "unchecked", "mismatch"} for x in ("fit_rationale", "assumption_fit", "boundary_fit"))
        if verified and fit: adopted.append(row)
        else:
            warning = f"{row.get('theory_id')}: 未通过来源或适配核验，已从确定性理论叙事排除"
            warnings.append(warning); rewrite_queue.append({"theory_id": row.get("theory_id"), "name": row.get("name"), "reason": warning, "required_action": "删除确定性理论陈述，或改写为待检验命题/理论中性机制叙事", "writing_continues": True})
    status = "validated" if adopted else "degraded"
    fallback = "validated-theory" if adopted else "mechanism-boundary-neutral-narrative"
    lines = ["# Theory usage audit", "", f"- status: {status}", f"- adopted: {len(adopted)}", f"- writing fallback: {fallback}", "", "## Adopted", ""]
    lines += [f"- {x.get('theory_id')} · {x.get('name')}: {x.get('fit_rationale')}" for x in adopted] or ["- none"]
    lines += ["", "## Warnings", ""] + ([f"- {x}" for x in warnings] or ["- none"])
    (base / "theory_usage_audit.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    write_jsonl(base / "theory_rewrite_queue.jsonl", rewrite_queue)
    ledger_lines = ["# Theory fit ledger", "", "| Theory ID | Name | Origin | Verification | Decision | Fit rationale |", "|---|---|---|---|---|---|"]
    ledger_lines += [f"| {x.get('theory_id','')} | {x.get('name','')} | {x.get('origin','')} | {x.get('verification_status','')} | {x.get('decision','')} | {x.get('fit_rationale','')} |" for x in rows]
    (base / "theory_fit_ledger.md").write_text("\n".join(ledger_lines) + "\n", encoding="utf-8")
    matrix_rows = []
    for row in rows:
        for competitor in row.get("competing_theories") or []:
            matrix_rows.append({"theory_id": row.get("theory_id", ""), "theory": row.get("name", ""), "competing_theory": competitor, "explanatory_target": row.get("explanatory_target", ""), "discriminating_prediction": row.get("discriminating_prediction", ""), "task_record_ids": ";".join(row.get("task_record_ids") or [])})
    columns = ["theory_id", "theory", "competing_theory", "explanatory_target", "discriminating_prediction", "task_record_ids"]
    with (base / "theory_competition_matrix.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns); writer.writeheader(); writer.writerows(matrix_rows)
    matrix_lines = ["# Theory competition matrix", "", "| Theory ID | Theory | Competing theory | Target | Discriminating prediction |", "|---|---|---|---|---|"]
    matrix_lines += [f"| {x['theory_id']} | {x['theory']} | {x['competing_theory']} | {x['explanatory_target']} | {x['discriminating_prediction']} |" for x in matrix_rows]
    if not matrix_rows: matrix_lines.append("|  |  |  |  | No completed competition comparisons |")
    (base / "theory_competition_matrix.md").write_text("\n".join(matrix_lines) + "\n", encoding="utf-8")
    write_jsonl(base / "theory_promotion_queue.jsonl", [x for x in rows if x.get("origin") != "local-library" and x.get("source_verified") is True])
    log = {"status": status, "reason": warnings or (["no-eligible-theory"] if not adopted else []), "fallback": fallback, "writing_continues": True, "generated_at": utc_stamp()}
    write_json(base / "theory_degradation_log.json", log)
    (base / "theory_degradation_log.md").write_text("# Theory degradation log\n\n- status: " + status + "\n- fallback: " + fallback + "\n- writing continues: true\n", encoding="utf-8")
    report = {"phase": "compile", "status": status, "adopted": len(adopted), "warnings": warnings, "writing_fallback_mode": fallback, "non_blocking": True}
    write_json(base / "theory_compile_report.json", report); return report


def validate_recommendations(root: Path) -> dict[str, Any]:
    base = root / "05_evidence/theories"; report = read_json(base / "theory_compile_report.json", {})
    status = report.get("status", "unavailable"); warnings = list(report.get("warnings") or [])
    result = {"phase": "validate", "status": status if status in {"validated", "exploratory", "skipped", "degraded", "unavailable"} else "degraded", "valid": True, "warnings": warnings, "non_blocking": True, "writing_continues": True, "writing_fallback_mode": report.get("writing_fallback_mode", "mechanism-boundary-neutral-narrative")}
    write_json(root / "07_logs/theory_validation.json", result); return result


def safe_task_theory_phase(root: Path, phase: str, limit: int = 8) -> dict[str, Any]:
    try:
        if phase == "prepare": return prepare_recommendations(root, limit)
        if phase == "compile": return compile_recommendations(root)
        return validate_recommendations(root)
    except Exception as exc:
        base = root / "05_evidence/theories"; base.mkdir(parents=True, exist_ok=True)
        report = {"phase": phase, "status": "unavailable", "valid": True, "error": str(exc), "non_blocking": True, "writing_continues": True, "writing_fallback_mode": "mechanism-boundary-neutral-narrative"}
        write_json(base / "theory_degradation_log.json", report); write_json(root / "07_logs/theory_validation.json", report)
        return report
