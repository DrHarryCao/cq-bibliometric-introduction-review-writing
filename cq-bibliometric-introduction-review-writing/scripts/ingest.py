#!/usr/bin/env python3
"""Import heterogeneous bibliographic exports into the canonical corpus."""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any, Iterable

from common import as_list, canonical_record, deduplicate, load_jsonl, normalize_doi, write_json, write_jsonl


FIELD_ALIASES = {
    "title": ["title", "ti", "t1", "标题", "题名", "篇名", "文献题名"],
    "authors": ["authors", "author", "au", "af", "作者", "作者姓名"],
    "year": ["year", "py", "y1", "dp", "publication year", "年份", "年"],
    "publication_date": ["publication date", "date", "da", "y1", "dp", "online date", "发表日期"],
    "abstract": ["abstract", "ab", "摘要"],
    "keywords": ["keywords", "keyword", "kw", "de", "id", "关键词", "关键字"],
    "venue": ["venue", "journal", "jo", "jf", "t2", "source title", "期刊", "来源出版物"],
    "doi": ["doi", "di", "do"],
    "wos_id": ["ut", "an", "wos id"],
    "pmid": ["pmid", "pm"],
    "issn": ["issn", "sn"],
    "isbn": ["isbn", "bn"],
    "citations": ["citations", "times cited", "tc", "z9", "cited by", "引用数", "被引频次"],
    "references": ["references", "cr", "参考文献"],
    "language": ["language", "la", "语种"],
    "type": ["document type", "dt", "ty", "文献类型"],
}


def clean_key(value: Any) -> str:
    return re.sub(r"[\s_\-]+", " ", str(value or "").strip().lower())


def pick(row: dict[str, Any], field: str) -> Any:
    normalized = {clean_key(k): v for k, v in row.items()}
    for alias in FIELD_ALIASES[field]:
        if clean_key(alias) in normalized and normalized[clean_key(alias)] not in (None, ""):
            return normalized[clean_key(alias)]
    return ""


def row_to_record(row: dict[str, Any], source: str) -> dict[str, Any]:
    citations = pick(row, "citations")
    citation_counts = {}
    if str(citations or "").strip():
        match = re.search(r"\d+", str(citations))
        if match: citation_counts[source] = int(match.group())
    ids = dict(row.get("ids") or {})
    doi = normalize_doi(pick(row, "doi"))
    if doi: ids["doi"] = doi
    for field, key in (("wos_id", "wos"), ("pmid", "pmid"), ("issn", "issn"), ("isbn", "isbn")):
        value = str(pick(row, field) or "").strip()
        if value: ids[key] = value
    raw_date = str(pick(row, "publication_date") or "").strip()
    year_match = re.search(r"(?:19|20)\d{2}", str(pick(row, "year") or raw_date))
    date_match = re.search(r"((?:19|20)\d{2})(?:[-/]([01]?\d)(?:[-/]([0-3]?\d))?)?", raw_date)
    publication_date = ""
    if date_match:
        publication_date = date_match.group(1)
        if date_match.group(2): publication_date += f"-{int(date_match.group(2)):02d}"
        if date_match.group(3): publication_date += f"-{int(date_match.group(3)):02d}"
    references = as_list(pick(row, "references"))
    reference_metadata = []
    for ref in references:
        ref_year = re.search(r"(?:19|20)\d{2}", ref)
        ref_doi = re.search(r"10\.\d{4,9}/[-._;()/:A-Z0-9]+", ref, flags=re.I)
        reference_metadata.append({"raw": ref, "year": int(ref_year.group()) if ref_year else None, "doi": normalize_doi(ref_doi.group()) if ref_doi else ""})
    return canonical_record({
        "title": pick(row, "title"),
        "authors": as_list(pick(row, "authors")),
        "year": year_match.group() if year_match else None,
        "publication_date": publication_date,
        "publication_date_meta": {"source": source, "raw": raw_date, "confidence": "high" if publication_date else "missing"},
        "abstract": pick(row, "abstract"),
        "keywords": as_list(pick(row, "keywords")),
        "venue": pick(row, "venue"),
        "ids": ids,
        "citation_counts": citation_counts,
        "references": references,
        "reference_metadata": reference_metadata,
        "language": pick(row, "language"),
        "type": pick(row, "type") or "article",
        "raw": {source: row},
    }, source)


def parse_tagged(path: Path, style: str) -> list[dict[str, Any]]:
    records, current = [], {}
    last_tag = ""
    lines = path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
    patterns = {
        "ris": re.compile(r"^([A-Z0-9]{2})\s+-\s*(.*)$"),
        "enw": re.compile(r"^%(.?)\s+(.*)$"),
        "nbib": re.compile(r"^([A-Z0-9]{2,4})\s*-\s*(.*)$"),
        "wos": re.compile(r"^([A-Z][A-Z0-9])\s(.*)$"),
        "net": re.compile(r"^\{([^}]+)\}:\s*(.*)$"),
    }
    author_tags = {"AU", "A1", "FAU"}
    for line in lines:
        match = patterns[style].match(line)
        if not match:
            if last_tag and current and (line.startswith(" ") or line.startswith("\t")):
                current[last_tag] = f"{current.get(last_tag, '')} {line.strip()}".strip()
            continue
        tag, value = match.group(1), match.group(2).strip()
        if (style == "ris" and tag == "TY") or (style == "enw" and tag == "0") or (style == "wos" and tag == "PT") or (style == "net" and tag == "Reference Type"):
            if current: records.append(current)
            current = {}
        if (style == "ris" and tag == "ER") or (style == "wos" and tag == "ER"):
            if current: records.append(current); current = {}
            continue
        if style == "enw":
            tag = {"A": "AU", "T": "TI", "D": "PY", "X": "AB", "K": "KW", "J": "JO", "R": "DO", "C": "CR"}.get(tag, tag)
        if style == "net":
            tag = {"Title": "TI", "Author": "AU", "Year": "PY", "Abstract": "AB", "Keywords": "KW", "DOI": "DO", "References": "CR", "Journal": "JO"}.get(tag, tag)
        if tag in author_tags:
            current.setdefault("AU", []).append(value)
            last_tag = "AU"
        elif tag in current:
            current[tag] = f"{current[tag]}; {value}"
            last_tag = tag
        else:
            current[tag] = value
            last_tag = tag
    if current: records.append(current)
    normalized = []
    for r in records:
        if not (r.get("TI") or r.get("T1")):
            continue
        is_wos_ris = str(r.get("AN", "")).upper().startswith("WOS:") or "WEB OF SCIENCE" in str(r.get("N1", "")).upper()
        source = "wos" if is_wos_ris else style
        citations = r.get("TC") or r.get("Z9") or ""
        if is_wos_ris and not citations:
            match = re.search(r"(?:Times Cited in Web of Science Core Collection|Total Times Cited)\s*:\s*(\d+)", str(r.get("N1", "")), flags=re.I)
            citations = match.group(1) if match else ""
        normalized.append(row_to_record({
            "title": r.get("TI") or r.get("T1"), "authors": r.get("AU", []), "year": r.get("PY") or r.get("Y1") or r.get("DP"),
            "publication date": r.get("DA") or r.get("Y1") or r.get("DP"),
            "abstract": r.get("AB"), "keywords": r.get("KW") or r.get("DE") or r.get("OT"),
            "venue": r.get("SO") or r.get("JO") or r.get("JF") or r.get("JT"), "doi": r.get("DI") or r.get("DO") or r.get("LID"),
            "citations": citations, "references": r.get("CR"), "language": r.get("LA"), "type": r.get("DT") or r.get("PT"),
            "wos id": r.get("UT") or (r.get("AN", "") if is_wos_ris else ""), "pmid": r.get("PMID") or r.get("PM"), "issn": r.get("SN"), "isbn": r.get("BN"),
            "ids": {"wos": r.get("UT") or r.get("AN", "")} if (r.get("UT") or (is_wos_ris and r.get("AN"))) else {},
        }, source))
    return normalized


def parse_bibtex(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    rows = []
    for block in re.split(r"(?=@\w+\s*\{)", text):
        if not block.strip().startswith("@"):
            continue
        fields = {}
        for key, value in re.findall(r"(?ms)\b(\w+)\s*=\s*(\{(?:[^{}]|\{[^{}]*\})*\}|\"(?:[^\"\\]|\\.)*\"|[^,\n]+)\s*,?", block):
            value = value.strip().strip("{},\"")
            fields[key.lower()] = re.sub(r"\s+", " ", value)
        fields["authors"] = [x.strip() for x in re.split(r"\s+and\s+", fields.get("author", "")) if x.strip()]
        rows.append(row_to_record(fields, "bibtex"))
    return rows


def parse_table(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() in {".xlsx", ".xls"}:
        import pandas as pd
        rows = pd.read_excel(path).fillna("").to_dict(orient="records")
    else:
        sample = path.read_text(encoding="utf-8-sig", errors="replace")[:8192]
        try: dialect = csv.Sniffer().sniff(sample, delimiters=",\t;")
        except csv.Error: dialect = csv.excel
        with path.open("r", encoding="utf-8-sig", errors="replace", newline="") as fh:
            rows = list(csv.DictReader(fh, dialect=dialect))
    return [row_to_record(row, path.suffix.lower().lstrip(".")) for row in rows]


def parse_json(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".jsonl": rows = load_jsonl(path)
    else:
        value = json.loads(path.read_text(encoding="utf-8-sig")); rows = value if isinstance(value, list) else value.get("records", [])
    return [canonical_record(row, "json") for row in rows]


def detect_style(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".ris": return "ris"
    if suffix == ".enw": return "enw"
    if suffix in {".nbib", ".medline"}: return "nbib"
    if suffix == ".net": return "net"
    head = path.read_text(encoding="utf-8-sig", errors="replace")[:3000] if suffix in {".txt", ".ciw"} else ""
    if "FN Clarivate" in head or re.search(r"(?m)^PT\s", head): return "wos"
    return ""


def expand_inputs(inputs: Iterable[Path]) -> list[Path]:
    supported = {".ris", ".enw", ".nbib", ".medline", ".net", ".txt", ".ciw", ".bib", ".csv", ".tsv", ".xlsx", ".xls", ".json", ".jsonl"}
    files = []
    for path in inputs:
        path = path.expanduser()
        files.extend(p for p in path.rglob("*") if p.is_file() and p.suffix.lower() in supported) if path.is_dir() else files.append(path)
    return sorted(set(p.resolve() for p in files if p.exists()))


def ingest(inputs: Iterable[Path], existing: list[dict[str, Any]] | None = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    all_records = list(existing or []); file_report = []
    for path in expand_inputs(inputs):
        suffix, style = path.suffix.lower(), detect_style(path)
        if style: rows = parse_tagged(path, style)
        elif suffix == ".bib": rows = parse_bibtex(path)
        elif suffix in {".csv", ".tsv", ".xlsx", ".xls"}: rows = parse_table(path)
        elif suffix in {".json", ".jsonl"}: rows = parse_json(path)
        else: rows = []
        all_records.extend(rows); file_report.append({"file": str(path), "format": style or suffix.lstrip("."), "records": len(rows)})
    unique, merges = deduplicate(all_records)
    return unique, {"files": file_report, "input_records": len(all_records), "unique_records": len(unique), "merge_count": len(merges), "merges": merges}


def export_corpus(root: Path, records: list[dict[str, Any]], report: dict[str, Any], report_name: str = "ingest_report.json") -> None:
    import pandas as pd
    corpus = root / "02_corpus"
    write_jsonl(corpus / "corpus.jsonl", records)
    flat = []
    for r in records:
        flat.append({
            "record_id": r["record_id"], "title": r["title"], "authors": "; ".join(a.get("name", "") for a in r["authors"]),
            "year": r["year"], "venue": r["venue"], "doi": (r["ids"] or {}).get("doi", ""), "abstract": r["abstract"],
            "keywords": "; ".join(r["keywords"]), "citations": max((r["citation_counts"] or {"": 0}).values()), "inclusion": r["inclusion"].get("status", "candidate"),
        })
    frame = pd.DataFrame(flat)
    frame.to_csv(corpus / "records.csv", index=False, encoding="utf-8-sig")
    frame.to_excel(corpus / "records.xlsx", index=False)
    lines = ["# 统一文献语料", "", f"> 唯一记录：{len(records)}", ""]
    for r in records:
        lines += [f"## [{r['record_id']}] {r['title'] or '无题名'}", "", f"- 作者：{'; '.join(a.get('name','') for a in r['authors'])}", f"- 年份：{r['year'] or ''}", f"- DOI：{(r['ids'] or {}).get('doi','')}", f"- 关键词：{'; '.join(r['keywords'])}", "", r["abstract"], ""]
    (corpus / "records.md").write_text("\n".join(lines), encoding="utf-8")
    write_json(root / "07_logs" / report_name, report)
    review_queue = [{**m, "review_reason": "fuzzy title/year/author merge requires human confirmation"} for m in report.get("merges") or [] if m.get("method") == "title-year-author" and float(m.get("score") or 0) < 0.98]
    write_jsonl(root / "07_logs/dedup_review_queue.jsonl", review_queue)
