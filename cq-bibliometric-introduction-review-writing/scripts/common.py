#!/usr/bin/env python3
"""Shared UTF-8 data model and filesystem helpers."""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import sys
import re
import time
from copy import deepcopy
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Iterable


TASK_DIRS = [
    "00_plan", "01_sources/raw", "01_sources/cache", "02_corpus",
    "03_fulltext/original", "03_fulltext/extracted", "04_analysis/tables",
    "04_analysis/markdown", "04_analysis/figures", "05_evidence/cards",
    "05_evidence/dossiers", "06_review/sections", "07_logs",
]


def utc_stamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def ensure_task(root: Path) -> Path:
    root = root.expanduser().resolve()
    for name in TASK_DIRS:
        (root / name).mkdir(parents=True, exist_ok=True)
    return root


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    # Iterate on actual LF-delimited records. str.splitlines() also splits on
    # Unicode U+2028/U+2029/NEL characters that may legally occur inside JSON
    # strings from publisher metadata, corrupting otherwise valid JSONL rows.
    with path.open("r", encoding="utf-8-sig") as fh:
        for line in fh:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def normalize_doi(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", text)
    return text.rstrip(". ,;)")


def normalize_title(value: Any) -> str:
    text = re.sub(r"<[^>]+>", " ", str(value or "").lower())
    return re.sub(r"[^0-9a-z\u4e00-\u9fff]+", "", text)


def as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    if isinstance(value, (tuple, set)):
        return [str(x).strip() for x in value if str(x).strip()]
    return [x.strip() for x in re.split(r"\s*;\s*|\s*\|\s*", str(value)) if x.strip()]


def stable_record_id(record: dict[str, Any]) -> str:
    ids = record.get("ids") or {}
    doi = normalize_doi(ids.get("doi") or record.get("doi"))
    if doi:
        seed = f"doi:{doi}"
    elif ids.get("openalex"):
        seed = f"openalex:{str(ids['openalex']).rsplit('/', 1)[-1]}"
    elif ids.get("pmid"):
        seed = f"pmid:{ids['pmid']}"
    else:
        authors = record.get("authors") or []
        first = authors[0].get("name", "") if authors and isinstance(authors[0], dict) else (authors[0] if authors else "")
        seed = f"title:{normalize_title(record.get('title'))}:{record.get('year') or ''}:{normalize_title(first)}"
    return "R" + hashlib.sha1(seed.encode("utf-8")).hexdigest()[:14]


def canonical_record(data: dict[str, Any], source: str = "unknown") -> dict[str, Any]:
    authors = data.get("authors") or []
    normalized_authors = []
    for author in authors if isinstance(authors, list) else as_list(authors):
        normalized_authors.append(author if isinstance(author, dict) else {"name": str(author)})
    ids = dict(data.get("ids") or {})
    if data.get("doi"):
        ids["doi"] = normalize_doi(data["doi"])
    record = {
        "record_id": data.get("record_id", ""),
        "ids": ids,
        "title": str(data.get("title") or "").strip(),
        "authors": normalized_authors,
        "year": int(data["year"]) if str(data.get("year") or "").isdigit() else None,
        "publication_date": data.get("publication_date") or "",
        "publication_date_meta": dict(data.get("publication_date_meta") or {}),
        "venue": data.get("venue") or "",
        "type": data.get("type") or "article",
        "language": data.get("language") or "",
        "abstract": re.sub(r"\s+", " ", str(data.get("abstract") or "")).strip(),
        "keywords": list(dict.fromkeys(as_list(data.get("keywords")))),
        "topics": data.get("topics") or [],
        "citation_counts": dict(data.get("citation_counts") or {}),
        "citation_counts_by_year": dict(data.get("citation_counts_by_year") or {}),
        "references": data.get("references") or [],
        "reference_metadata": data.get("reference_metadata") or [],
        "oa": dict(data.get("oa") or {}),
        "fulltext": dict(data.get("fulltext") or {}),
        "query_ids": list(dict.fromkeys(as_list(data.get("query_ids")))),
        "inclusion": data.get("inclusion") or {"status": "candidate", "reasons": []},
        "provenance": list(data.get("provenance") or []),
        "raw": data.get("raw") or {},
    }
    if not record["provenance"]:
        record["provenance"] = [{"source": source, "retrieved_at": utc_stamp()}]
    record["record_id"] = record["record_id"] or stable_record_id(record)
    return record


def records_match(a: dict[str, Any], b: dict[str, Any]) -> tuple[bool, str, float]:
    ai, bi = a.get("ids") or {}, b.get("ids") or {}
    ad, bd = normalize_doi(ai.get("doi")), normalize_doi(bi.get("doi"))
    if ad and bd:
        return ad == bd, "doi", 1.0 if ad == bd else 0.0
    for key in ("openalex", "pmid", "pmcid"):
        if ai.get(key) and bi.get(key) and str(ai[key]).rsplit("/", 1)[-1] == str(bi[key]).rsplit("/", 1)[-1]:
            return True, key, 1.0
    at, bt = normalize_title(a.get("title")), normalize_title(b.get("title"))
    if not at or not bt:
        return False, "missing-title", 0.0
    score = SequenceMatcher(None, at, bt).ratio()
    year_ok = not a.get("year") or not b.get("year") or abs(int(a["year"]) - int(b["year"])) <= 1
    aa = (a.get("authors") or [{}])[0]
    ba = (b.get("authors") or [{}])[0]
    aa = aa.get("name", "") if isinstance(aa, dict) else str(aa)
    ba = ba.get("name", "") if isinstance(ba, dict) else str(ba)
    author_ok = not aa or not ba or normalize_title(aa).split(" ")[0] == normalize_title(ba).split(" ")[0]
    return bool(score >= 0.94 and year_ok and author_ok), "title-year-author", score


def merge_records(base: dict[str, Any], incoming: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    out = deepcopy(base)
    conflicts: list[dict[str, Any]] = []
    for key in ("title", "year", "publication_date", "venue", "type", "language", "abstract"):
        left, right = out.get(key), incoming.get(key)
        if not left and right:
            out[key] = right
        elif left and right and left != right:
            if key == "abstract" and len(str(right)) > len(str(left)):
                out[key] = right
            conflicts.append({"record_id": out["record_id"], "field": key, "kept": out.get(key), "alternate": right})
    for key in ("ids", "citation_counts", "citation_counts_by_year", "oa", "fulltext", "raw", "publication_date_meta"):
        out.setdefault(key, {}).update({k: v for k, v in (incoming.get(key) or {}).items() if v not in (None, "", [], {})})
    for key in ("authors", "keywords", "topics", "references", "reference_metadata", "query_ids", "provenance"):
        combined = out.get(key, []) + incoming.get(key, [])
        seen, unique = set(), []
        for item in combined:
            marker = json.dumps(item, ensure_ascii=False, sort_keys=True) if isinstance(item, (dict, list)) else str(item)
            if marker not in seen:
                seen.add(marker); unique.append(item)
        out[key] = unique
    return out, conflicts


def deduplicate(records: Iterable[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    unique: list[dict[str, Any]] = []
    audit: list[dict[str, Any]] = []
    doi_index: dict[str, int] = {}
    for raw in records:
        rec = canonical_record(raw)
        doi = normalize_doi((rec.get("ids") or {}).get("doi"))
        candidates = [doi_index[doi]] if doi and doi in doi_index else range(len(unique))
        matched = None
        for idx in candidates:
            ok, method, score = records_match(unique[idx], rec)
            if ok:
                matched = (idx, method, score); break
        if matched is None:
            unique.append(rec)
            if doi: doi_index[doi] = len(unique) - 1
            continue
        idx, method, score = matched
        merged, conflicts = merge_records(unique[idx], rec)
        unique[idx] = merged
        audit.append({"kept_id": merged["record_id"], "merged_id": rec["record_id"], "method": method, "score": round(score, 4), "conflicts": conflicts})
    return unique, audit


def update_manifest(root: Path, event: str, details: dict[str, Any] | None = None) -> None:
    path = root / "manifest.json"
    manifest = read_json(path, {"created_at": utc_stamp(), "events": []})
    previous_schema = int(manifest.get("skill_schema_version", 1))
    manifest["skill_name"] = "cq-bibliometric-introduction-review-writing"
    manifest["skill_schema_version"] = 6
    manifest["data_schema_version"] = int(manifest.get("data_schema_version", 1))
    if "runtime" not in manifest:
        versions = {"python": sys.version.split()[0]}
        for package in ("numpy", "pandas", "scikit-learn", "networkx", "requests"):
            try: versions[package] = importlib.metadata.version(package)
            except importlib.metadata.PackageNotFoundError: versions[package] = "missing"
        manifest["runtime"] = versions
    manifest.setdefault("reproducibility", {"random_seeds": [42, 73, 101, 151], "encoding": "UTF-8"})
    if previous_schema < 4 and not any(e.get("event") == "schema-migrated-v4" for e in manifest.get("events", [])):
        manifest.setdefault("events", []).append({"at": utc_stamp(), "event": "schema-migrated-v4", "details": {"from": previous_schema, "to": 4, "data_files_modified": False}})
    if previous_schema < 6 and not any(e.get("event") == "schema-migrated-v6" for e in manifest.get("events", [])):
        manifest.setdefault("events", []).append({"at": utc_stamp(), "event": "schema-migrated-v6", "details": {"from": previous_schema, "to": 6, "data_files_modified": False, "new_optional_artifacts": ["gap_ledger", "research_design_brief", "method_fit_matrix"]}})
    manifest["updated_at"] = utc_stamp()
    manifest["events"].append({"at": utc_stamp(), "event": event, "details": details or {}})
    manifest["files"] = sorted(str(p.relative_to(root)) for p in root.rglob("*") if p.is_file())
    write_json(path, manifest)
