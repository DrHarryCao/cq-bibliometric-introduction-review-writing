#!/usr/bin/env python3
"""Polite, cached scholarly API clients and OpenAlex normalization."""
from __future__ import annotations

import hashlib
import html
import json
import random
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

import requests

from common import canonical_record, normalize_doi, read_json, utc_stamp, write_json
from credentials import credential_value


CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
LATIN_RE = re.compile(r"[A-Za-z]")


def contains_cjk(value: Any) -> bool:
    return bool(CJK_RE.search(str(value or "")))


def contains_latin(value: Any) -> bool:
    return bool(LATIN_RE.search(str(value or "")))


def query_language(value: Any) -> str:
    text = str(value or "")
    has_zh, has_en = contains_cjk(text), contains_latin(text)
    if has_zh and has_en: return "mixed"
    if has_zh: return "zh"
    if has_en: return "en"
    return "unknown"


def validate_search_plan(plan: dict[str, Any]) -> dict[str, Any]:
    """Block Chinese-origin plans until the host model supplies auditable bilingual queries."""
    errors: list[str] = []; warnings: list[str] = []
    title = str(plan.get("title_or_idea") or "").strip()
    source_language = str(plan.get("source_language") or query_language(title))
    chinese_origin = contains_cjk(title) or source_language in {"zh", "mixed", "zh-CN"}
    queries = []
    for index, raw in enumerate(plan.get("queries") or [], 1):
        query = {"id": f"Q{index:02d}", "family": "core", "query": raw} if isinstance(raw, str) else dict(raw)
        query["detected_language"] = query_language(query.get("query"))
        queries.append(query)
    if not queries: errors.append("检索计划没有 queries。")
    for query in queries:
        declared = str(query.get("language") or "").lower()
        detected = query["detected_language"]
        if declared == "en" and detected not in {"en", "mixed"}: errors.append(f"{query.get('id')} 标记为英文，但查询文本不含英文字母。")
        if declared in {"zh", "zh-cn"} and detected not in {"zh", "mixed"}: errors.append(f"{query.get('id')} 标记为中文，但查询文本不含中文。")
    if chinese_origin:
        if not contains_cjk(plan.get("title_zh")): errors.append("中文输入必须保留 title_zh。")
        if not contains_latin(plan.get("title_en")) or contains_cjk(plan.get("title_en")): errors.append("中文输入必须由宿主模型生成纯英文 title_en。")
        if plan.get("translation_status") != "completed": errors.append("translation_status 必须为 completed。")
        concepts = plan.get("concepts") or []
        bilingual = [c for c in concepts if isinstance(c, dict) and any(contains_cjk(x) for x in c.get("zh") or []) and any(contains_latin(x) for x in c.get("en") or [])]
        if not bilingual: errors.append("至少一个概念组必须同时包含非空 zh 与 en 术语。")
        incomplete = [str(c.get("name") or i + 1) for i, c in enumerate(concepts) if isinstance(c, dict) and (not c.get("zh") or not c.get("en"))]
        if incomplete: warnings.append(f"以下概念组不完全双语对齐，需宿主核查语义：{incomplete}")
        core = [q for q in queries if str(q.get("family") or "core").lower() == "core"]
        has_zh_core = any(q["detected_language"] in {"zh", "mixed"} and str(q.get("language") or "").lower() in {"zh", "zh-cn"} for q in core)
        has_en_core = any(q["detected_language"] == "en" and str(q.get("language") or "").lower() == "en" for q in core)
        if not has_zh_core: errors.append("中文输入必须包含 language=zh 的中文核心查询。")
        if not has_en_core: errors.append("中文输入必须包含 language=en 的纯英文核心查询。")
    return {"valid": not errors, "errors": errors, "warnings": warnings, "source_language": source_language, "chinese_origin": chinese_origin, "queries": queries}


def reconstruct_abstract(index: dict[str, list[int]] | None) -> str:
    if not index:
        return ""
    positions = [(pos, word) for word, locs in index.items() for pos in locs]
    return " ".join(word for _, word in sorted(positions))


class CachedClient:
    def __init__(self, cache_dir: Path, timeout: int = 45, retries: int = 5):
        self.cache_dir = cache_dir; self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.timeout, self.retries = timeout, retries
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "cq-bibliometric-introduction-review-writing/3.0 (scholarly research workflow)"})

    def get_json(self, url: str, params: dict[str, Any] | None = None, refresh: bool = False) -> dict[str, Any]:
        key = hashlib.sha256((url + "?" + urlencode(sorted((params or {}).items()))).encode()).hexdigest()
        cache = self.cache_dir / f"{key}.json"
        if cache.exists() and not refresh:
            return json.loads(cache.read_text(encoding="utf-8"))
        for attempt in range(self.retries):
            response = self.session.get(url, params=params, timeout=self.timeout)
            if response.status_code == 200:
                payload = response.json(); write_json(cache, payload); return payload
            if response.status_code not in {429, 500, 502, 503, 504}:
                raise RuntimeError(f"GET {response.url} failed: HTTP {response.status_code} {response.text[:300]}")
            wait = min(60, (2 ** attempt) + random.random())
            retry_after = response.headers.get("Retry-After")
            if retry_after and retry_after.isdigit(): wait = max(wait, int(retry_after))
            time.sleep(wait)
        raise RuntimeError(f"GET {url} failed after {self.retries} attempts")


def openalex_to_record(work: dict[str, Any], query_id: str = "") -> dict[str, Any]:
    authors = []
    for item in work.get("authorships") or []:
        author = item.get("author") or {}
        authors.append({
            "name": author.get("display_name") or item.get("raw_author_name") or "",
            "openalex": author.get("id") or "", "orcid": author.get("orcid") or "",
            "institutions": [x.get("display_name") for x in item.get("institutions") or [] if x.get("display_name")],
        })
    location = work.get("best_oa_location") or work.get("primary_location") or {}
    source = location.get("source") or {}
    topics = [{"id": t.get("id", ""), "name": t.get("display_name", ""), "score": t.get("score")} for t in work.get("topics") or []]
    keywords = [k.get("display_name", "") for k in work.get("keywords") or [] if k.get("display_name")]
    oa = work.get("open_access") or {}
    return canonical_record({
        "ids": {"openalex": work.get("id", ""), "doi": normalize_doi(work.get("doi")), "pmid": (work.get("ids") or {}).get("pmid", ""), "pmcid": (work.get("ids") or {}).get("pmcid", "")},
        "title": work.get("title") or work.get("display_name") or "", "authors": authors,
        "year": work.get("publication_year"), "publication_date": work.get("publication_date") or "",
        "venue": source.get("display_name") or "", "type": work.get("type") or "article", "language": work.get("language") or "",
        "abstract": reconstruct_abstract(work.get("abstract_inverted_index")), "keywords": keywords, "topics": topics,
        "citation_counts": {"openalex": int(work.get("cited_by_count") or 0)},
        "publication_status": {"is_retracted": bool(work.get("is_retracted")), "is_paratext": bool(work.get("is_paratext")), "type_crossref": work.get("type_crossref", "")},
        "citation_counts_by_year": {str(x.get("year")): int(x.get("cited_by_count") or 0) for x in work.get("counts_by_year") or [] if x.get("year")},
        "references": work.get("referenced_works") or [],
        "oa": {"is_oa": oa.get("is_oa", False), "status": oa.get("oa_status"), "license": location.get("license"), "landing_page_url": location.get("landing_page_url"), "pdf_url": location.get("pdf_url")},
        "fulltext": {"content_url": work.get("content_url") or "", "has_pdf": bool((work.get("has_content") or {}).get("pdf") or location.get("pdf_url"))},
        "query_ids": [query_id] if query_id else [], "raw": {"openalex": work},
    }, "openalex")


class OpenAlexClient:
    base = "https://api.openalex.org"
    def __init__(self, client: CachedClient, api_key: str | None = None):
        self.client = client; self.api_key = api_key or credential_value("OPENALEX_API_KEY")
        if not self.api_key:
            raise RuntimeError("缺少 OpenAlex API Key。请运行 review_pipeline.py credentials guide，然后用 credentials setup 在安全对话框中输入。")

    def search(self, query: str, query_id: str, filters: str = "", limit: int = 200, refresh: bool = False) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        rows, cursor, calls, estimate = [], "*", 0, None
        while cursor and len(rows) < limit:
            params = {"api_key": self.api_key, "search": query, "per_page": min(100, limit - len(rows)), "cursor": cursor}
            if filters: params["filter"] = filters
            payload = self.client.get_json(f"{self.base}/works", params, refresh=refresh)
            calls += 1; estimate = (payload.get("meta") or {}).get("count", estimate)
            page = payload.get("results") or []
            rows.extend(openalex_to_record(w, query_id) for w in page)
            cursor = (payload.get("meta") or {}).get("next_cursor") if page else None
        return rows[:limit], {"query_id": query_id, "query": query, "filter": filters, "estimated_results": estimate, "retrieved": min(len(rows), limit), "calls": calls, "retrieved_at": utc_stamp()}

    def get_work(self, identifier: str) -> dict[str, Any] | None:
        try:
            payload = self.client.get_json(f"{self.base}/works/{identifier}", {"api_key": self.api_key})
            return openalex_to_record(payload)
        except RuntimeError as exc:
            if "404" in str(exc): return None
            raise


def strip_jats(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", value or ""))).strip()


def enrich_crossref(record: dict[str, Any], client: CachedClient, email: str = "") -> dict[str, Any]:
    doi = normalize_doi((record.get("ids") or {}).get("doi"))
    params = {"mailto": email} if email else {}
    if doi:
        payload = client.get_json(f"https://api.crossref.org/v1/works/{doi}", params)
        item = payload.get("message") or {}
    else:
        payload = client.get_json("https://api.crossref.org/v1/works", {**params, "query.bibliographic": record.get("title", ""), "rows": 1})
        items = (payload.get("message") or {}).get("items") or []
        item = items[0] if items else {}
    if not item: return record
    record.setdefault("ids", {})["doi"] = normalize_doi(item.get("DOI") or doi)
    if not record.get("abstract") and item.get("abstract"): record["abstract"] = strip_jats(item["abstract"])
    if not record.get("references") and item.get("reference"): record["references"] = item["reference"]
    date_source, date_parts = "", []
    for key in ("published-online", "published-print", "issued", "created"):
        parts = ((item.get(key) or {}).get("date-parts") or [[]])[0]
        if parts:
            date_source, date_parts = key, parts; break
    if date_parts:
        normalized_date = "-".join([str(date_parts[0])] + [f"{int(x):02d}" for x in date_parts[1:3]])
        if not record.get("year"): record["year"] = int(date_parts[0])
        if not record.get("publication_date"): record["publication_date"] = normalized_date
        record["publication_date_meta"] = {"source": f"crossref:{date_source}", "raw": date_parts, "confidence": "high"}
    if item.get("is-referenced-by-count") is not None:
        record.setdefault("citation_counts", {})["crossref"] = int(item.get("is-referenced-by-count") or 0)
    if item.get("container-title") and not record.get("venue"): record["venue"] = item["container-title"][0]
    if item.get("ISSN"): record.setdefault("ids", {})["issn"] = item["ISSN"][0]
    if item.get("ISBN"): record.setdefault("ids", {})["isbn"] = item["ISBN"][0]
    if item.get("reference"):
        metadata = []
        for ref in item["reference"]:
            year = ref.get("year")
            metadata.append({"raw": ref, "year": int(year) if str(year or "").isdigit() else None, "doi": normalize_doi(ref.get("DOI"))})
        record["reference_metadata"] = metadata
    record.setdefault("raw", {})["crossref"] = item
    record.setdefault("provenance", []).append({"source": "crossref", "retrieved_at": utc_stamp()})
    return record


def enrich_unpaywall(record: dict[str, Any], client: CachedClient, email: str) -> dict[str, Any]:
    doi = normalize_doi((record.get("ids") or {}).get("doi"))
    if not doi or not email: return record
    try: item = client.get_json(f"https://api.unpaywall.org/v2/{doi}", {"email": email})
    except RuntimeError as exc:
        if "404" in str(exc): return record
        raise
    best = item.get("best_oa_location") or {}
    record.setdefault("oa", {}).update({"is_oa": item.get("is_oa", False), "status": item.get("oa_status"), "license": best.get("license"), "landing_page_url": best.get("url_for_landing_page"), "pdf_url": best.get("url_for_pdf")})
    record.setdefault("raw", {})["unpaywall"] = item
    record.setdefault("provenance", []).append({"source": "unpaywall", "retrieved_at": utc_stamp()})
    return record


def enrich_semantic_scholar(record: dict[str, Any], client: CachedClient, api_key: str) -> dict[str, Any]:
    doi = normalize_doi((record.get("ids") or {}).get("doi"))
    if not doi or not api_key: return record
    previous = client.session.headers.get("x-api-key")
    client.session.headers["x-api-key"] = api_key
    try:
        item = client.get_json(f"https://api.semanticscholar.org/graph/v1/paper/DOI:{doi}", {"fields": "paperId,title,abstract,year,authors,citationCount,fieldsOfStudy,openAccessPdf,references.paperId,references.title"})
    except RuntimeError as exc:
        if "404" in str(exc): return record
        raise
    finally:
        if previous is None: client.session.headers.pop("x-api-key", None)
        else: client.session.headers["x-api-key"] = previous
    if not record.get("abstract") and item.get("abstract"): record["abstract"] = item["abstract"]
    record.setdefault("ids", {})["s2"] = item.get("paperId", "")
    record.setdefault("citation_counts", {})["semantic_scholar"] = int(item.get("citationCount") or 0)
    record.setdefault("raw", {})["semantic_scholar"] = item
    record.setdefault("provenance", []).append({"source": "semantic_scholar", "retrieved_at": utc_stamp()})
    return record


def download_oa_files(root: Path, records: list[dict[str, Any]], limit: int = 100, allow_openalex_content: bool = False) -> dict[str, Any]:
    """Download only explicit OA PDF URLs; paid OpenAlex content needs its own flag."""
    out = root / "03_fulltext/original"; out.mkdir(parents=True, exist_ok=True)
    session = requests.Session(); session.headers.update({"User-Agent": "cq-bibliometric-introduction-review-writing/3.0"})
    attempted = downloaded = 0; failures = []
    for record in records:
        if attempted >= limit: break
        url = (record.get("oa") or {}).get("pdf_url") or ""
        paid = False
        if "content.openalex.org" in url:
            paid = True
            if not allow_openalex_content: continue
        if not url and allow_openalex_content and (record.get("fulltext") or {}).get("content_url"):
            url = record["fulltext"]["content_url"]; paid = "content.openalex.org" in url
            if paid and "api_key=" not in url:
                sep = "&" if "?" in url else "?"; url += f"{sep}api_key={credential_value('OPENALEX_API_KEY')}"
        if not url: continue
        attempted += 1; target = out / f"{record['record_id']}.pdf"
        if target.exists(): record.setdefault("fulltext", {})["local_path"] = str(target); downloaded += 1; continue
        try:
            with session.get(url, timeout=90, stream=True, allow_redirects=True) as response:
                response.raise_for_status()
                content_type = response.headers.get("Content-Type", "").lower()
                first = b""; size = 0
                with target.open("wb") as fh:
                    for chunk in response.iter_content(1024 * 256):
                        if not chunk: continue
                        if not first: first = chunk[:5]
                        size += len(chunk)
                        if size > 150 * 1024 * 1024: raise RuntimeError("file exceeds 150 MB safety limit")
                        fh.write(chunk)
                if first != b"%PDF-" and "pdf" not in content_type: raise RuntimeError(f"not a PDF ({content_type})")
            record.setdefault("fulltext", {}).update({"local_path": str(target), "download_url": re.sub(r"([?&]api_key=)[^&]+", r"\1***", url), "downloaded_at": utc_stamp(), "access": "openalex-paid-content" if paid else "oa-direct"})
            downloaded += 1
        except Exception as exc:
            target.unlink(missing_ok=True); failures.append({"record_id": record["record_id"], "url": re.sub(r"([?&]api_key=)[^&]+", r"\1***", url), "error": str(exc)})
    return {"attempted": attempted, "downloaded": downloaded, "failures": failures, "paid_openalex_enabled": allow_openalex_content, "estimated_openalex_cost_usd": round(sum((r.get("fulltext") or {}).get("access") == "openalex-paid-content" for r in records) * 0.01, 2)}


def oa_download_inventory(records: list[dict[str, Any]], limit: int = 100) -> dict[str, Any]:
    direct = paid = 0
    for record in records:
        url = (record.get("oa") or {}).get("pdf_url") or ""
        content = (record.get("fulltext") or {}).get("content_url") or ""
        if url and "content.openalex.org" not in url: direct += 1
        elif (url and "content.openalex.org" in url) or content: paid += 1
    return {"limit": limit, "direct_oa_available": direct, "openalex_paid_content_available": paid, "maximum_paid_downloads_this_run": min(paid, limit), "maximum_estimated_cost_usd": round(min(paid, limit) * 0.01, 2)}


def run_search_plan(root: Path, plan_path: Path, confirmed: bool = False, refresh: bool = False) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    plan = read_json(plan_path, {})
    validation = validate_search_plan(plan)
    if not validation["valid"]:
        raise RuntimeError("检索计划双语校验失败：\n- " + "\n- ".join(validation["errors"]))
    if not (confirmed or plan.get("approved") is True):
        raise RuntimeError("检索计划尚未确认。请审阅 search_plan.md/json 后设置 approved=true 或使用 --confirm。")
    cache = CachedClient(root / "01_sources/cache")
    oa = OpenAlexClient(cache)
    target_max = int(plan.get("target_max", 800)); queries = plan.get("queries") or []
    per_query = max(1, min(int(plan.get("per_query", 200)), target_max))
    records, audits = [], []
    for i, query in enumerate(queries, 1):
        if isinstance(query, str): query = {"id": f"Q{i:02d}", "query": query}
        rows, audit = oa.search(query["query"], query.get("id", f"Q{i:02d}"), query.get("filter", plan.get("filter", "")), per_query, refresh)
        records.extend(rows); audits.append(audit)
        write_json(root / f"01_sources/raw/{query.get('id', f'Q{i:02d}')}.json", {"audit": audit, "records": [r.get("raw", {}).get("openalex", {}) for r in rows]})
        if len(records) >= target_max * 2: break
    return records, {"plan": str(plan_path), "plan_language": {"source_language": validation["source_language"], "chinese_origin": validation["chinese_origin"]}, "queries": audits, "raw_records": len(records), "target_min": plan.get("target_min", 300), "target_max": target_max}
