#!/usr/bin/env python3
"""CLI entry point for the staged literature-review workflow."""
from __future__ import annotations

import argparse
import importlib.util
import os
import shutil
import json
import sys
import re
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path: sys.path.insert(0, str(SCRIPT_DIR))

from analysis import analyze
from common import canonical_record, deduplicate, ensure_task, load_jsonl, normalize_doi, normalize_title, read_json, update_manifest, utc_stamp, write_json, write_jsonl
from credentials import configure_dialog, credential_guide, credential_status, credential_value, delete_credentials, prompt_value, store_credential, test_credentials
from evidence import build_evidence, sync_references, validate, write_introduction
from focus import focus_records
from extract import extract_documents
from ingest import export_corpus, ingest
from sources import CachedClient, OpenAlexClient, contains_cjk, download_oa_files, enrich_crossref, enrich_semantic_scholar, enrich_unpaywall, oa_download_inventory, query_language, run_search_plan, validate_search_plan
from science import dependency_versions, prisma_report
from semantic import compile_semantic, embedding_dry_run, prepare as prepare_semantic, validate_semantic
from deliverables import export_deliverables
from workflow_v5 import apply_corpus_policy, build_search_strategy, enrich_metadata, metadata_coverage, write_brief, writing_context_manifest


def root_of(args: argparse.Namespace) -> Path:
    return ensure_task(Path(args.task))


def cmd_init(args: argparse.Namespace) -> int:
    root = root_of(args)
    chinese = contains_cjk(args.title); source_language = "zh" if chinese else query_language(args.title)
    plan = {
        "title_or_idea": args.title, "title_zh": args.title if chinese else "", "title_en": "" if chinese else args.title,
        "research_question": "", "source_language": source_language, "output_language": "zh-CN", "translation_status": "required" if chinese else "not_required", "approved": False,
        "target_min": 300, "target_max": 800, "per_query": 200, "seed_papers": [],
        "concepts": [{"name": "核心概念", "zh": [], "en": [], "exclude": []}],
        "queries": [{"id": "Q01-ZH" if chinese else "Q01-EN", "family": "core", "language": "zh" if chinese else "en", "query": args.title, "filter": "type:article"}],
        "notes": "若 source_language=zh，宿主模型必须自行生成 title_en、双语概念和中英文核心查询，并把 translation_status 改为 completed；脚本不调用外部翻译 API。",
    }
    write_json(root / "00_plan/search_plan.json", plan)
    translation_note = "检测到中文输入：宿主模型必须先生成英文标题、双语概念、中文核心查询和英文核心查询；完成后将 `translation_status` 设为 `completed`。" if chinese else "检测到非中文输入，无强制翻译门。"
    (root / "00_plan/search_plan.md").write_text(f"# 检索计划（待用户确认）\n\n- 题目/思路：{args.title}\n- 输入语言：{source_language}\n- 目标语料：300–800\n- 状态：`not-approved`\n\n{translation_note}\n\n请由宿主模型补齐并解释 `search_plan.json` 中的概念组、同义词、排除词、查询族、年份、语种和文献类型，再让用户确认。\n", encoding="utf-8")
    update_manifest(root, "init", {"title": args.title, "skill_schema_version": 5})
    manifest = read_json(root / "manifest.json", {}); manifest.update({"acquisition_mode": "unselected", "metadata_enrichment": "offline", "corpus_mode": "unselected", "v5_workflow_enforced": True}); write_json(root / "manifest.json", manifest)
    print(root); return 0


def cmd_search_strategy(args: argparse.Namespace) -> int:
    root = root_of(args); report = build_search_strategy(root, args.mode)
    update_manifest(root, "search-strategy", report); print(json.dumps(report, ensure_ascii=False, indent=2)); return 0


def maybe_enrich(records, root: Path, limit: int) -> None:
    if limit <= 0: return
    client = CachedClient(root / "01_sources/cache"); email = credential_value("UNPAYWALL_EMAIL") or credential_value("CROSSREF_EMAIL")
    s2_key = credential_value("S2_API_KEY")
    for i, record in enumerate(records[:limit], 1):
        doi = (record.get("ids") or {}).get("doi")
        if not doi and record.get("title"): enrich_crossref(record, client, email)
        elif doi and not record.get("abstract"): enrich_crossref(record, client, email)
        if (record.get("ids") or {}).get("doi") and email: enrich_unpaywall(record, client, email)
        if s2_key and (record.get("ids") or {}).get("doi"): enrich_semantic_scholar(record, client, s2_key)
        if i % 50 == 0: print(f"enriched {i}/{min(limit, len(records))}", file=sys.stderr)


def cmd_search(args: argparse.Namespace) -> int:
    root = root_of(args); plan = Path(args.plan) if args.plan else root / "00_plan/search_plan.json"
    manifest = read_json(root / "manifest.json", {})
    if manifest.get("acquisition_mode") == "strategy-only": raise RuntimeError("当前任务为 strategy-only，不会请求API。请使用 ingest/extract，或先将模式改为 api-search。")
    manifest["acquisition_mode"] = "api-search"; write_json(root / "manifest.json", manifest)
    validation = validate_search_plan(read_json(plan, {}))
    if validation["valid"] and not credential_value("OPENALEX_API_KEY") and not args.no_credential_dialog:
        configured = configure_dialog(include_semantic_scholar=False)
        if not configured.get("configured"): raise RuntimeError("用户取消了凭据配置，尚未开始搜索。")
    plan_data = read_json(plan, {})
    estimated_pages = sum(max(1, (int(q.get("limit") or plan_data.get("per_query", 200)) + 199) // 200) for q in plan_data.get("queries") or [])
    print(json.dumps({"preflight": "OpenAlex", "estimated_list_requests": estimated_pages, "paid_content_requested": bool(args.allow_paid_openalex_content), "note": "估算不包括重试和元数据补全。"}, ensure_ascii=False), file=sys.stderr)
    rows, report = run_search_plan(root, plan, args.confirm, args.refresh)
    unique, merges = deduplicate(rows); maybe_enrich(unique, root, args.enrich_limit)
    target_max = int(read_json(plan, {}).get("target_max", 800)); unique = balanced_select(unique, target_max)
    if args.download_oa:
        report["oa_download"] = download_oa_files(root, unique, args.oa_limit, args.allow_paid_openalex_content)
    report.update({"unique_records": len(unique), "deduplicated": len(merges), "enriched_limit": args.enrich_limit})
    export_corpus(root, unique, report); report["metadata_coverage"] = metadata_coverage(root, unique); write_json(root / "07_logs/search_report.json", report)
    report["prisma"] = prisma_report(root, "search-identification", unique, {"deduplicated": len(merges), "queries": len(plan_data.get("queries") or [])})
    update_manifest(root, "search", report); print(json.dumps(report, ensure_ascii=False, indent=2)); return 0


def cmd_validate_plan(args: argparse.Namespace) -> int:
    root = root_of(args); plan = Path(args.plan) if args.plan else root / "00_plan/search_plan.json"
    report = validate_search_plan(read_json(plan, {})); print(json.dumps(report, ensure_ascii=False, indent=2)); return 0 if report["valid"] else 1


def cmd_configure(args: argparse.Namespace) -> int:
    report = configure_dialog(include_semantic_scholar=args.include_semantic_scholar)
    print(json.dumps(report, ensure_ascii=False, indent=2)); return 0 if report.get("configured") else 1


def cmd_credential_status(args: argparse.Namespace) -> int:
    report = credential_status(); print(json.dumps(report, ensure_ascii=False, indent=2)); return 0 if report.get("configured") else 1


def cmd_credentials(args: argparse.Namespace) -> int:
    if args.credential_command == "guide": report = credential_guide(args.open_browser)
    elif args.credential_command in {"setup", "update"}:
        if args.credential_command == "setup": report = configure_dialog(include_semantic_scholar=args.include_semantic_scholar)
        else:
            hidden = args.name not in {"UNPAYWALL_EMAIL", "CROSSREF_EMAIL"}
            value = prompt_value(f"请输入新的 {args.name}：", "CQ 凭据替换", hidden=hidden)
            if not value: return 1
            store_credential(args.name, value); report = {"updated": args.name, "status": credential_status()["credentials"][args.name], "secrets_exposed": False}
    elif args.credential_command == "status": report = credential_status()
    elif args.credential_command == "test": report = test_credentials(args.timeout)
    elif args.credential_command == "delete":
        names = list(credentials_names()) if args.all else [args.name]
        if not args.yes:
            answer = prompt_value(f"输入 DELETE 确认删除 {', '.join(names)}：", "CQ 凭据删除", hidden=False)
            if answer != "DELETE": return 1
        report = delete_credentials(names)
    else: raise RuntimeError("未知凭据命令")
    print(json.dumps(report, ensure_ascii=False, indent=2)); return 0 if report.get("ok", report.get("configured", True)) else 1


def credentials_names():
    return ("OPENALEX_API_KEY", "UNPAYWALL_EMAIL", "CROSSREF_EMAIL", "S2_API_KEY")


def cmd_ingest(args: argparse.Namespace) -> int:
    root = root_of(args); existing = load_jsonl(root / "02_corpus/corpus.jsonl")
    records, report = ingest([Path(x) for x in args.inputs], existing); export_corpus(root, records, report)
    prisma_report(root, "database-import-and-deduplication", records, {"inputs": len(args.inputs), "merges": len(report.get("merges") or [])})
    report["metadata_coverage"] = metadata_coverage(root, records)
    update_manifest(root, "ingest", {k: v for k, v in report.items() if k != "merges"}); print(json.dumps({k: v for k, v in report.items() if k != "merges"}, ensure_ascii=False, indent=2)); return 0


def cmd_enrich_metadata(args: argparse.Namespace) -> int:
    root = root_of(args); report = enrich_metadata(root, args.source, args.confirm, args.limit)
    update_manifest(root, "enrich-metadata", report); print(json.dumps(report, ensure_ascii=False, indent=2)); return 0


def cmd_corpus_policy(args: argparse.Namespace) -> int:
    if args.mode == "focused":
        if not args.output_task: raise RuntimeError("focused 模式必须提供 --output-task。")
        return cmd_focus(argparse.Namespace(task=args.task, output_task=args.output_task))
    root = root_of(args); report = apply_corpus_policy(root, "all")
    update_manifest(root, "corpus-policy", report); print(json.dumps(report, ensure_ascii=False, indent=2)); return 0


def cmd_focus(args: argparse.Namespace) -> int:
    source_root = root_of(args); output_root = Path(args.output_task).expanduser().resolve()
    if (output_root / "02_corpus/corpus.jsonl").exists():
        raise RuntimeError(f"聚焦任务已存在：{output_root}。为保护已有结果，未覆盖。")
    records = load_jsonl(source_root / "02_corpus/corpus.jsonl")
    if not records: raise RuntimeError("原任务语料为空，无法建立聚焦语料。")
    core, theory, excluded, report = focus_records(records)
    if len(core) < 4: raise RuntimeError(f"聚焦核心仅得到 {len(core)} 篇，已停止创建派生任务；请调整筛选规则。")
    output_root = ensure_task(output_root)
    source_plan = source_root / "00_plan"
    shutil.copytree(source_plan, output_root / "00_plan", dirs_exist_ok=True)
    report.update({"source_task": str(source_root), "output_task": str(output_root), "analysis_scope": "core_records_only", "theory_pool_scope": "辅助理论解释，不进入主题模型"})
    export_corpus(output_root, core, report, report_name="focus_report.json")
    write_jsonl(output_root / "02_corpus/theory_supplement_pool.jsonl", theory)
    write_jsonl(output_root / "02_corpus/excluded_focus_records.jsonl", excluded)
    screening = ["# 聚焦核心语料筛选", "", f"- 原始语料：{len(records)}", f"- 直播电商直接核心：{len(core)}", f"- 理论补充池：{len(theory)}（不进入主题模型）", f"- 排除：{len(excluded)}", "", "## 核心规则", "", "- 直接查询或 WoS-only 文献须在题名、摘要或关键词中同时显示直播电商情境与消费者决策/超载信号。", "- Q06/Q07 及 WoS-only 非直播文献只有同时显示信息超载和消费者决策信号才进入理论补充池。", "- 健康、COVID-19、医疗、游戏、教育和非消费者购买情境排除。", "", "## 排除原因统计", ""]
    screening.extend(f"- {reason}: {count}" for reason, count in sorted(report["excluded_reason_counts"].items(), key=lambda x: x[1], reverse=True))
    (output_root / "02_corpus/focus_screening.md").write_text("\n".join(screening), encoding="utf-8")
    update_manifest(output_root, "focus-derived", report)
    focused_manifest = read_json(output_root / "manifest.json", {}); focused_manifest["corpus_mode"] = "focused"; focused_manifest["source_task"] = str(source_root); write_json(output_root / "manifest.json", focused_manifest)
    print(json.dumps(report, ensure_ascii=False, indent=2)); return 0


def cmd_extract(args: argparse.Namespace) -> int:
    root = root_of(args); report = extract_documents(root, [Path(x) for x in args.inputs], ocr=args.ocr)
    records = load_jsonl(root / "02_corpus/corpus.jsonl"); linked = 0
    for item in report:
        if item.get("status") != "ok": continue
        text = Path(item["output"]).read_text(encoding="utf-8", errors="replace")[:20000]; text_key = normalize_title(text)
        source_stem = normalize_title(Path(item["file"]).stem)
        matches = []
        for record in records:
            doi = normalize_doi((record.get("ids") or {}).get("doi")); title = normalize_title(record.get("title"))
            if doi and doi in text.lower(): matches.append(record)
            elif title and len(title) >= 20 and title[:60] in text_key: matches.append(record)
            # Very short/generic filenames (for example ``acat.pdf``) can be
            # accidental substrings of many normalized titles.  Use filename
            # matching only when the stem carries enough identifying text;
            # DOI and extracted-title matches above remain authoritative.
            elif len(source_stem) >= 12 and title and (source_stem in title or title in source_stem): matches.append(record)
        if len({r["record_id"] for r in matches}) == 1:
            record = matches[0]; record.setdefault("fulltext", {}).update({"local_path": item["output"], "source_file": item["file"], "evidence_level": "fulltext"}); linked += 1
    if records: write_jsonl(root / "02_corpus/corpus.jsonl", records)
    write_json(root / "03_fulltext/fulltext_link_report.json", {"linked": linked, "unlinked": sum(x.get("status") == "ok" for x in report) - linked})
    update_manifest(root, "extract", {"files": len(report), "ok": sum(x["status"] == "ok" for x in report), "linked_to_corpus": linked}); print(json.dumps(report, ensure_ascii=False, indent=2)); return 0


def cmd_download_oa(args: argparse.Namespace) -> int:
    root = root_of(args); records = load_jsonl(root / "02_corpus/corpus.jsonl")
    if not records: raise RuntimeError("语料为空，请先 search 或 ingest。")
    if args.dry_run:
        report = oa_download_inventory(records, args.limit); print(json.dumps(report, ensure_ascii=False, indent=2)); return 0
    report = download_oa_files(root, records, args.limit, args.allow_paid_openalex_content)
    write_jsonl(root / "02_corpus/corpus.jsonl", records); write_json(root / "07_logs/oa_download_report.json", report)
    update_manifest(root, "download-oa", report); print(json.dumps(report, ensure_ascii=False, indent=2)); return 0


def balanced_select(records, limit: int):
    if len(records) <= limit: return records
    groups = {}
    for record in records:
        topics = record.get("topics") or []
        topic = (topics[0].get("id") or topics[0].get("name")) if topics and isinstance(topics[0], dict) else "unclassified"
        decade = ((record.get("year") or 0) // 5) * 5
        groups.setdefault((topic or "unclassified", decade), []).append(record)
    for rows in groups.values(): rows.sort(key=lambda r: (len(r.get("query_ids") or []), bool(r.get("abstract")), max((r.get("citation_counts") or {"": 0}).values()), r.get("year") or 0), reverse=True)
    selected = []
    while groups and len(selected) < limit:
        for key in sorted(list(groups), key=str):
            selected.append(groups[key].pop(0))
            if not groups[key]: del groups[key]
            if len(selected) >= limit: break
    return selected


def cmd_expand_references(args: argparse.Namespace) -> int:
    root = root_of(args)
    if args.depth != 1: raise RuntimeError("当前安全边界只允许一跳参考文献扩展（--depth 1）。")
    raw_refs = []
    for path in (root / "03_fulltext/extracted").glob("*.references.json"):
        for ref in read_json(path, []): raw_refs.append({**ref, "source_file": str(path)})
    counts = {}
    for ref in raw_refs:
        key = ref.get("doi") or ref.get("raw", "")[:240]
        if not key: continue
        counts.setdefault(key, {**ref, "occurrences": 0}); counts[key]["occurrences"] += 1
    corpus = load_jsonl(root / "02_corpus/corpus.jsonl")
    corpus_dois = {normalize_doi((r.get("ids") or {}).get("doi")) for r in corpus if normalize_doi((r.get("ids") or {}).get("doi"))}
    corpus_titles = {normalize_title(r.get("title")) for r in corpus if normalize_title(r.get("title"))}
    candidates = sorted(counts.values(), key=lambda x: (x["occurrences"], x.get("year") or 0), reverse=True)
    for candidate in candidates:
        candidate["local_match"] = "doi" if normalize_doi(candidate.get("doi")) in corpus_dois else ""
    candidates = [x for x in candidates if not x["local_match"]][:args.max_candidates]
    if args.resolve_limit > 0:
        cache = CachedClient(root / "01_sources/cache"); email = credential_value("UNPAYWALL_EMAIL") or credential_value("CROSSREF_EMAIL")
        oa = OpenAlexClient(cache) if credential_value("OPENALEX_API_KEY") else None
        for candidate in candidates[:args.resolve_limit]:
            record = None; doi = normalize_doi(candidate.get("doi"))
            if doi and oa: record = oa.get_work(f"doi:{doi}")
            if record is None:
                seed = canonical_record({"title": candidate.get("raw", ""), "year": candidate.get("year"), "doi": doi}, "reference-list")
                try: record = enrich_crossref(seed, cache, email)
                except RuntimeError as exc: candidate["resolution_error"] = str(exc); continue
                resolved_doi = normalize_doi((record.get("ids") or {}).get("doi"))
                if resolved_doi and oa:
                    try: record = oa.get_work(f"doi:{resolved_doi}") or record
                    except RuntimeError: pass
            if record and normalize_title(record.get("title")) not in corpus_titles: candidate["resolved_record"] = record
    write_jsonl(root / "02_corpus/reference_expansion_candidates.jsonl", candidates)
    note = "# 一跳参考文献扩展候选（未纳入主语料）\n\n> 必须由用户确认后再将选中记录交给 ingest。\n\n" + "\n".join(f"- {x.get('raw','')} — occurrences={x['occurrences']}" for x in candidates)
    (root / "02_corpus/reference_expansion_candidates.md").write_text(note, encoding="utf-8")
    report = {"raw_references": len(raw_refs), "unique_candidates": len(candidates), "resolved_candidates": sum(bool(x.get("resolved_record")) for x in candidates), "depth": 1, "status": "awaiting-user-confirmation"}
    update_manifest(root, "expand-references", report); print(json.dumps(report, ensure_ascii=False, indent=2)); return 0


def cmd_analyze(args: argparse.Namespace) -> int:
    root = root_of(args); records = load_jsonl(root / "02_corpus/corpus.jsonl")
    if not records: raise RuntimeError("语料为空，请先 search 或 ingest。")
    previous = read_json(root / "04_analysis/analysis_parameters.json", {})
    report = analyze(root, records, args.topic_count, args.nmf_min_k, args.nmf_max_k, args.cluster_min_k, args.cluster_max_k, args.burst_min_docs, args.counting, args.skip_kmeans, args.strategic_map, args.citation_age, args.knowledge_flow)
    current = read_json(root / "04_analysis/analysis_parameters.json", {})
    diff = {"previous_exists": bool(previous), "record_count": {"before": previous.get("record_count"), "after": current.get("record_count")}, "nmf_selected_k": {"before": (previous.get("topic_model") or {}).get("selected_k"), "after": (current.get("topic_model") or {}).get("selected_k")}, "cluster_selected_k": {"before": (previous.get("cluster_model") or {}).get("selected_k"), "after": (current.get("cluster_model") or {}).get("selected_k")}, "parameter_changes": {k: {"before": previous.get(k), "after": current.get(k)} for k in ("nmf_k_range", "cluster_k_range", "network_counting") if previous.get(k) != current.get(k)}}
    write_json(root / "07_logs/analysis_rerun_diff.json", diff); report["rerun_diff"] = diff
    update_manifest(root, "analyze", report); print(json.dumps(report, ensure_ascii=False, indent=2)); return 0


def cmd_build_evidence(args: argparse.Namespace) -> int:
    root = root_of(args); report = build_evidence(root); update_manifest(root, "build-evidence", report); print(json.dumps(report, ensure_ascii=False, indent=2)); return 0


def cmd_build_semantic(args: argparse.Namespace) -> int:
    root = root_of(args)
    if args.phase == "prepare":
        context = writing_context_manifest(root, args.budget, args.batch_size)
        report = prepare_semantic(root, args.batch_size, args.budget); report["writing_context"] = context
    elif args.phase == "compile": report = compile_semantic(root)
    else: report = validate_semantic(root)
    update_manifest(root, f"build-semantic-{args.phase}", report); print(json.dumps(report, ensure_ascii=False, indent=2)); return 0 if report.get("valid", True) else 1


def cmd_semantic_embeddings(args: argparse.Namespace) -> int:
    if not args.dry_run: raise RuntimeError("本版本只预留 embedding 扩展协议；必须使用 --dry-run，不会下载或运行模型。")
    report = embedding_dry_run(root_of(args)); print(json.dumps(report, ensure_ascii=False, indent=2)); return 0


def cmd_validate(args: argparse.Namespace) -> int:
    root = root_of(args); report = validate(root); update_manifest(root, "validate", report); print(json.dumps(report, ensure_ascii=False, indent=2)); return 0 if report["valid"] else 1


def cmd_write_introduction(args: argparse.Namespace) -> int:
    root = root_of(args); source = Path(args.audit_source).expanduser().resolve() if args.audit_source else None
    report = write_introduction(root, source); update_manifest(root, "write-introduction", report)
    print(json.dumps(report, ensure_ascii=False, indent=2)); return 0


def cmd_sync_references(args: argparse.Namespace) -> int:
    root = root_of(args); draft = Path(args.draft).expanduser().resolve() if args.draft else None
    report = sync_references(root, args.document, draft); update_manifest(root, f"sync-references-{args.document}", report)
    print(json.dumps(report, ensure_ascii=False, indent=2)); return 0


def cmd_writing_brief(args: argparse.Namespace) -> int:
    root = root_of(args); gaps = list(args.gap or [])
    if not gaps and not args.skip:
        raw = input("请输入希望突出的研究缺口方向（多个用分号分隔，直接回车表示跳过）：").strip()
        gaps = [x.strip() for x in re.split(r"[;；\n]+", raw) if x.strip()]
    report = write_brief(root, args.document, gaps, args.skip or not gaps, not args.no_model_package)
    update_manifest(root, f"writing-brief-{args.document}", report); print(json.dumps(report, ensure_ascii=False, indent=2)); return 0


def cmd_export_deliverables(args: argparse.Namespace) -> int:
    root = root_of(args); report = export_deliverables(root, args.document)
    update_manifest(root, f"export-deliverables-{args.document}", report); print(json.dumps(report, ensure_ascii=False, indent=2)); return 0


def cmd_status(args: argparse.Namespace) -> int:
    root = root_of(args); corpus = load_jsonl(root / "02_corpus/corpus.jsonl")
    semantic_files = list((root / "05_evidence/semantic/extractions").glob("*.json"))
    batch_tasks = []
    for path in (root / "05_evidence/semantic/batches").glob("*.json"):
        batch_tasks.extend(read_json(path, {}).get("tasks") or [])
    planned_semantic = len({x.get("record_id") for x in batch_tasks if x.get("record_id")}) or len(load_jsonl(root / "05_evidence/citation_coverage_targets.jsonl"))
    semantic_state = {"prepared": (root / "05_evidence/semantic/schema.json").exists(), "planned_extractions": planned_semantic, "completed_extractions": sum(read_json(p, {}).get("host_review_status") == "completed" for p in semantic_files), "compiled": (root / "05_evidence/semantic/semantic-synthesis.md").exists()}
    manifest = read_json(root / "manifest.json", {})
    status = {"task": str(root), "plan": (root / "00_plan/search_plan.json").exists(), "plan_approved": bool(read_json(root / "00_plan/search_plan.json", {}).get("approved")), "acquisition_mode": manifest.get("acquisition_mode", "unselected"), "metadata_enrichment": manifest.get("metadata_enrichment", "offline"), "corpus_mode": manifest.get("corpus_mode", "unselected"), "records": len(corpus), "extracted_documents": len(list((root / "03_fulltext/extracted").glob("*.md"))), "analysis": (root / "04_analysis/tables/bibliometric_analysis.xlsx").exists(), "evidence_cards": len(list((root / "05_evidence/cards").glob("*.md"))), "outline_status": "missing"}
    outline = root / "06_review/outline.md"
    if outline.exists(): status["outline_status"] = "approved" if "status: approved" in outline.read_text(encoding="utf-8") else "draft-not-approved"
    status["review_draft"] = (root / "06_review/review_draft.md").exists()
    requires_input, checkpoint, prompt, replies, auto_continue = False, "none", "", [], True
    if not status["plan"]: next_step = "init --task TASK --title IDEA"; checkpoint = "title-required"; requires_input = True; prompt = "请输入论文题目或研究思路。"; replies = ["论文题目或研究思路"]
    elif not status["plan_approved"]: next_step = "validate-plan；展示计划后等待批准"; checkpoint = "search-plan-approval"; requires_input = True; prompt = "请回复“批准检索计划”，或直接列出需要修改的关键词。"; replies = ["批准检索计划", "修改：……"]
    elif status["acquisition_mode"] == "unselected": next_step = "search-strategy --mode strategy-only|api-search"; checkpoint = "acquisition-mode"; requires_input = True; prompt = "请回复“API自动检索”或“仅生成检索策略”。"; replies = ["API自动检索", "仅生成检索策略"]
    elif not status["records"] and status["acquisition_mode"] == "strategy-only": next_step = "ingest --task TASK RIS_OR_FOLDER"; checkpoint = "local-input-path"; requires_input = True; prompt = "请提供RIS/题录文件或文件夹路径，也可回复“跳过题录导入”。"; replies = ["文件或文件夹路径", "跳过题录导入"]
    elif not status["records"]: next_step = "search --task TASK --confirm"
    elif status["corpus_mode"] == "unselected": next_step = "corpus-policy --mode all|focused"; checkpoint = "corpus-policy"; requires_input = True; prompt = "请回复“全部语料”或“聚焦语料”。"; replies = ["全部语料", "聚焦语料"]
    elif not status["analysis"]: next_step = "analyze --task TASK"
    elif not status["evidence_cards"]: next_step = "build-evidence --task TASK"
    elif semantic_state["prepared"] and semantic_state["completed_extractions"] < semantic_state["planned_extractions"]: next_step = "宿主自动按批完成计划候选语义提取，再 compile/validate"
    elif status["outline_status"] != "approved": next_step = "展示研究现状地图与提纲"; checkpoint = "outline-approval"; requires_input = True; prompt = "请回复“确认提纲”，或列出需要调整的章节。"; replies = ["确认提纲", "调整：……"]
    elif not (root / "06_review/review_brief.json").exists(): next_step = "writing-brief --document review"; checkpoint = "review-gap-brief"; requires_input = True; prompt = "请输入希望突出的研究缺口方向，或回复“跳过”。"; replies = ["缺口方向", "跳过"]
    elif not status["review_draft"]: next_step = "自动分节写作、补足引用、同步参考文献并验证"
    elif not (root / "06_review/introduction_brief.json").exists(): next_step = "writing-brief --document introduction"; checkpoint = "introduction-decision"; requires_input = True; prompt = "系统综述已完成。请回复“继续写绪论”并可附突出缺口，或回复“不写绪论”。"; replies = ["继续写绪论：……", "不写绪论"]
    elif not (root / "06_review/ssci_introduction_audit.md").exists(): next_step = "自动撰写绪论、同步文末参考文献并验证"
    else: next_step = "validate 后 export-deliverables --document review|introduction"
    auto_continue = not requires_input
    status["advanced_modules"] = read_json(root / "04_analysis/advanced_module_status.json", {})
    status["semantic"] = semantic_state
    status["writing_context"] = read_json(root / "05_evidence/writing-context-manifest.json", {})
    status.update({"recommended_next_step": next_step, "requires_user_input": requires_input, "checkpoint": checkpoint, "user_prompt": prompt, "accepted_replies": replies, "next_command": next_step, "auto_continue": auto_continue})
    print(json.dumps(status, ensure_ascii=False, indent=2)); return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    skill = SCRIPT_DIR.parent; checks = {
        "python": sys.version.split()[0], "dependencies": dependency_versions(),
        "codex_symlink": (skill.parent / ".agents/skills" / skill.name).resolve() == skill,
        "claude_symlink": (skill.parent / ".claude/skills" / skill.name).resolve() == skill,
        "skill_writable": os.access(skill, os.W_OK), "credentials": credential_status(),
        "tesseract": bool(shutil.which("tesseract")), "libreoffice": bool(shutil.which("libreoffice")),
    }
    required_missing = [k for k, v in checks["dependencies"].items() if v == "missing" and k in {"numpy", "pandas", "scikit-learn", "networkx", "requests"}]
    checks["ok"] = not required_missing and checks["codex_symlink"] and checks["claude_symlink"]
    checks["recommended_actions"] = ([f"pip install -r {skill / 'scripts/requirements.txt'}"] if required_missing else []) + (["python scripts/review_pipeline.py credentials setup"] if not checks["credentials"]["configured"] else [])
    print(json.dumps(checks, ensure_ascii=False, indent=2)); return 0 if checks["ok"] else 1


def cmd_wizard(args: argparse.Namespace) -> int:
    title = args.title or input("请输入论文题目或研究思路：").strip()
    task = args.task or input("请输入任务目录：").strip()
    code = cmd_init(argparse.Namespace(task=task, title=title))
    mode = args.mode
    if not mode:
        choice = input("选择获取方式：1=API自动检索，2=只生成检索策略并导入本地文件 [2]：").strip()
        mode = "api-search" if choice == "1" else "strategy-only"
    manifest = read_json(Path(task).expanduser().resolve() / "manifest.json", {}); manifest["acquisition_mode"] = mode; write_json(Path(task).expanduser().resolve() / "manifest.json", manifest)
    report = {"created": str(Path(task).expanduser().resolve()), "acquisition_mode": mode, "next": "宿主模型补全双语 search_plan.json，运行 validate-plan 和 search-strategy，展示后等待确认。", "credentials_needed_now": mode == "api-search"}
    print(json.dumps(report, ensure_ascii=False, indent=2)); return code


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="CQ Bibliometric · Introduction · Review · Writing · JWC💗XQ@Rednote drharry")
    sub = p.add_subparsers(dest="command", required=True)
    creds = sub.add_parser("credentials", help="凭据申请、安全保存、验证、替换与删除")
    credsub = creds.add_subparsers(dest="credential_command", required=True)
    guide = credsub.add_parser("guide"); guide.add_argument("--open-browser", action="store_true"); guide.set_defaults(func=cmd_credentials)
    setup = credsub.add_parser("setup"); setup.add_argument("--include-semantic-scholar", action="store_true"); setup.set_defaults(func=cmd_credentials)
    cstatus = credsub.add_parser("status"); cstatus.set_defaults(func=cmd_credentials)
    ctest = credsub.add_parser("test"); ctest.add_argument("--timeout", type=int, default=15); ctest.set_defaults(func=cmd_credentials)
    update = credsub.add_parser("update"); update.add_argument("--name", required=True, choices=list(credentials_names())); update.set_defaults(func=cmd_credentials)
    delete = credsub.add_parser("delete"); delete.add_argument("--name", choices=list(credentials_names()), default="OPENALEX_API_KEY"); delete.add_argument("--all", action="store_true"); delete.add_argument("--yes", action="store_true"); delete.set_defaults(func=cmd_credentials)
    init = sub.add_parser("init"); init.add_argument("--task", required=True); init.add_argument("--title", required=True); init.set_defaults(func=cmd_init)
    strategy = sub.add_parser("search-strategy"); strategy.add_argument("--task", required=True); strategy.add_argument("--mode", choices=["strategy-only", "api-search"], default="strategy-only"); strategy.set_defaults(func=cmd_search_strategy)
    check = sub.add_parser("validate-plan"); check.add_argument("--task", required=True); check.add_argument("--plan"); check.set_defaults(func=cmd_validate_plan)
    search = sub.add_parser("search"); search.add_argument("--task", required=True); search.add_argument("--plan"); search.add_argument("--confirm", action="store_true"); search.add_argument("--refresh", action="store_true"); search.add_argument("--enrich-limit", type=int, default=200); search.add_argument("--download-oa", action="store_true"); search.add_argument("--oa-limit", type=int, default=100); search.add_argument("--allow-paid-openalex-content", action="store_true"); search.add_argument("--no-credential-dialog", action="store_true"); search.set_defaults(func=cmd_search)
    ing = sub.add_parser("ingest"); ing.add_argument("--task", required=True); ing.add_argument("inputs", nargs="+"); ing.set_defaults(func=cmd_ingest)
    enrich = sub.add_parser("enrich-metadata"); enrich.add_argument("--task", required=True); enrich.add_argument("--source", choices=["crossref"], default="crossref"); enrich.add_argument("--confirm", action="store_true"); enrich.add_argument("--limit", type=int, default=0); enrich.set_defaults(func=cmd_enrich_metadata)
    policy = sub.add_parser("corpus-policy"); policy.add_argument("--task", required=True); policy.add_argument("--mode", choices=["all", "focused"], required=True); policy.add_argument("--output-task"); policy.set_defaults(func=cmd_corpus_policy)
    focus = sub.add_parser("focus"); focus.add_argument("--task", required=True, help="包含完整语料的原任务目录"); focus.add_argument("--output-task", required=True, help="新建的聚焦任务目录"); focus.set_defaults(func=cmd_focus)
    dl = sub.add_parser("download-oa"); dl.add_argument("--task", required=True); dl.add_argument("--limit", type=int, default=100); dl.add_argument("--dry-run", action="store_true"); dl.add_argument("--allow-paid-openalex-content", action="store_true"); dl.set_defaults(func=cmd_download_oa)
    ext = sub.add_parser("extract"); ext.add_argument("--task", required=True); ext.add_argument("--ocr", action="store_true"); ext.add_argument("inputs", nargs="+"); ext.set_defaults(func=cmd_extract)
    ref = sub.add_parser("expand-references"); ref.add_argument("--task", required=True); ref.add_argument("--depth", type=int, default=1); ref.add_argument("--max-candidates", type=int, default=200); ref.add_argument("--resolve-limit", type=int, default=50); ref.set_defaults(func=cmd_expand_references)
    ana = sub.add_parser("analyze"); ana.add_argument("--task", required=True); ana.add_argument("--topic-count", type=int, default=0, help="固定 NMF k；0 为自动")
    ana.add_argument("--nmf-min-k", type=int, default=4); ana.add_argument("--nmf-max-k", type=int, default=8)
    ana.add_argument("--cluster-min-k", type=int, default=2); ana.add_argument("--cluster-max-k", type=int, default=10)
    ana.add_argument("--burst-min-docs", type=int, default=3); ana.add_argument("--counting", choices=["fractional", "full"], default="fractional")
    ana.add_argument("--skip-kmeans", action="store_true"); ana.add_argument("--strategic-map", choices=["auto", "on", "off"], default="auto"); ana.add_argument("--citation-age", choices=["auto", "on", "off"], default="auto"); ana.add_argument("--knowledge-flow", choices=["auto", "on", "off"], default="auto"); ana.set_defaults(func=cmd_analyze)
    ev = sub.add_parser("build-evidence"); ev.add_argument("--task", required=True); ev.set_defaults(func=cmd_build_evidence)
    sem = sub.add_parser("build-semantic"); sem.add_argument("--task", required=True); sem.add_argument("--phase", required=True, choices=["prepare", "compile", "validate"]); sem.add_argument("--batch-size", type=int, default=12); sem.add_argument("--budget", choices=["balanced", "exhaustive"], default="balanced"); sem.set_defaults(func=cmd_build_semantic)
    emb = sub.add_parser("semantic-embeddings"); emb.add_argument("--task", required=True); emb.add_argument("--dry-run", action="store_true"); emb.set_defaults(func=cmd_semantic_embeddings)
    val = sub.add_parser("validate"); val.add_argument("--task", required=True); val.set_defaults(func=cmd_validate)
    intro = sub.add_parser("write-introduction"); intro.add_argument("--task", required=True); intro.add_argument("--audit-source"); intro.set_defaults(func=cmd_write_introduction)
    sync = sub.add_parser("sync-references"); sync.add_argument("--task", required=True); sync.add_argument("--document", choices=["review", "introduction"], default="review"); sync.add_argument("--draft"); sync.set_defaults(func=cmd_sync_references)
    brief = sub.add_parser("writing-brief"); brief.add_argument("--task", required=True); brief.add_argument("--document", choices=["review", "introduction"], required=True); brief.add_argument("--gap", action="append"); brief.add_argument("--skip", action="store_true"); brief.add_argument("--no-model-package", action="store_true"); brief.set_defaults(func=cmd_writing_brief)
    delivery = sub.add_parser("export-deliverables"); delivery.add_argument("--task", required=True); delivery.add_argument("--document", choices=["review", "introduction"], required=True); delivery.set_defaults(func=cmd_export_deliverables)
    status = sub.add_parser("status"); status.add_argument("--task", required=True); status.set_defaults(func=cmd_status)
    doctor = sub.add_parser("doctor"); doctor.set_defaults(func=cmd_doctor)
    wizard = sub.add_parser("wizard"); wizard.add_argument("--task"); wizard.add_argument("--title"); wizard.add_argument("--mode", choices=["strategy-only", "api-search"]); wizard.set_defaults(func=cmd_wizard)
    return p


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    try: return args.func(args)
    except Exception as exc:
        command = getattr(args, "command", "") or "status"
        task = getattr(args, "task", "")
        document = getattr(args, "document", "")
        recovery = f"python scripts/review_pipeline.py {command}"
        if task: recovery += f' --task "{task}"'
        if document: recovery += f" --document {document}"
        print(f"错误: {exc}", file=sys.stderr)
        print("已完成内容保持不变，可从最近检查点恢复。", file=sys.stderr)
        print(f"恢复命令: {recovery}", file=sys.stderr)
        return 1


if __name__ == "__main__": raise SystemExit(main())
