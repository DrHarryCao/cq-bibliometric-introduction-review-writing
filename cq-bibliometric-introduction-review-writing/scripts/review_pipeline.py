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
import shlex
import subprocess
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path: sys.path.insert(0, str(SCRIPT_DIR))

from analysis import analyze
from common import canonical_record, deduplicate, ensure_task, file_sha256, load_jsonl, normalize_doi, normalize_title, read_json, update_manifest, utc_stamp, write_json, write_jsonl
from credentials import configure_dialog, credential_guide, credential_status, credential_value, delete_credentials, prompt_value, store_credential, test_credentials
from evidence import build_evidence, sync_references, validate, write_introduction
from focus import focus_records
from extract import extract_documents
from ingest import export_corpus, ingest
from sources import CachedClient, OpenAlexClient, contains_cjk, download_oa_files, enrich_crossref, enrich_semantic_scholar, enrich_unpaywall, oa_download_inventory, query_language, run_search_plan, validate_search_plan
from science import dependency_versions, prisma_report
from semantic import compile_semantic, embedding_dry_run, prepare as prepare_semantic, reconcile_semantic, validate_semantic
from meta_analysis import compile_meta, prepare as prepare_meta, validate_meta
from writing_audit import audit_writing
from deliverables import export_deliverables
from publication import compile_publication, prepare_publication, validate_publication
from gap_design import compile_design, compile_gaps, prepare_design, prepare_gaps, validate_design, validate_gaps
from workflow_v5 import apply_corpus_policy, build_search_strategy, enrich_metadata, metadata_coverage, write_brief, writing_context_manifest
from platform_support import failure, path_issues, platform_report
from install_skill import inspect_one, install_one, targets as install_targets
from theory_library import (disable_theory, ensure_library, export_library, import_library,
                            ingest_theories, library_status, promote_theories,
                            safe_task_theory_phase, search_theories, set_task_support,
                            show_theory, theory_home, theory_support_needed,
                            update_theory, verify_theories)


def root_of(args: argparse.Namespace) -> Path:
    return ensure_task(Path(args.task))


def review_approval_state(root: Path) -> dict:
    approval = read_json(root / "06_review/review_approval.json", {})
    draft = root / "06_review/review_draft.md"
    current_hash = file_sha256(draft) if draft.exists() else ""
    approved = approval.get("status") == "approved" and approval.get("source_sha256") == current_hash
    state = "approved" if approved else "stale" if approval.get("status") == "approved" else approval.get("status", "missing")
    return {**approval, "state": state, "current_source_sha256": current_hash, "current": approved}


def introduction_brief_state(root: Path) -> dict:
    brief = read_json(root / "06_review/introduction_brief.json", {})
    approval = review_approval_state(root)
    current = bool(brief and approval.get("current") and brief.get("review_approval_sha256") == approval.get("source_sha256"))
    return {**brief, "current": current, "state": "current" if current else "stale" if brief else "missing"}


def safe_theory_status() -> dict:
    try: return library_status()
    except Exception as exc: return {"status": "unavailable", "cards": 0, "error": str(exc), "non_blocking": True}


def cmd_init(args: argparse.Namespace) -> int:
    candidate = Path(args.task).expanduser().absolute(); issues = path_issues(candidate)
    blocking = [x for x in issues if x["code"] != "windows-long-path-risk"]
    if blocking: raise RuntimeError("; ".join(x["message"] for x in blocking))
    if issues: print(json.dumps({"status": "path-warning", "issues": issues, "task_creation_continues": True}, ensure_ascii=False), file=sys.stderr)
    root = ensure_task(candidate)
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
    update_manifest(root, "init", {"title": args.title, "skill_schema_version": 11, "path_preflight": issues})
    manifest = read_json(root / "manifest.json", {}); manifest.update({"acquisition_mode": "unselected", "metadata_enrichment": "offline", "corpus_mode": "unselected", "v5_workflow_enforced": True, "writing_audit_required": True, "theory_support_mode": "unselected", "theory_support_non_blocking": True}); write_json(root / "manifest.json", manifest)
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
        if args.credential_command == "setup": report = configure_dialog(include_semantic_scholar=args.include_semantic_scholar, input_mode=args.input)
        else:
            hidden = args.name not in {"UNPAYWALL_EMAIL", "CROSSREF_EMAIL"}
            value = prompt_value(f"请输入新的 {args.name}：", "CQ 凭据替换", hidden=hidden, input_mode=args.input)
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
    report = analyze(root, records, args.topic_count, args.nmf_min_k, args.nmf_max_k, args.cluster_min_k, args.cluster_max_k, args.burst_min_docs, args.counting, args.skip_kmeans, args.strategic_map, args.citation_age, args.knowledge_flow, args.language, args.bootstrap_runs, args.nmf_structure)
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
    elif args.phase == "reconcile": report = reconcile_semantic(root)
    else: report = validate_semantic(root)
    update_manifest(root, f"build-semantic-{args.phase}", report); print(json.dumps(report, ensure_ascii=False, indent=2)); return 0 if report.get("valid", True) else 1


def cmd_semantic_embeddings(args: argparse.Namespace) -> int:
    if not args.dry_run: raise RuntimeError("本版本只预留 embedding 扩展协议；必须使用 --dry-run，不会下载或运行模型。")
    report = embedding_dry_run(root_of(args)); print(json.dumps(report, ensure_ascii=False, indent=2)); return 0


def cmd_synthesize_effects(args: argparse.Namespace) -> int:
    root = root_of(args); report = prepare_meta(root) if args.phase == "prepare" else compile_meta(root) if args.phase == "compile" else validate_meta(root)
    update_manifest(root, f"synthesize-effects-{args.phase}", report); print(json.dumps(report, ensure_ascii=False, indent=2)); return 0 if report.get("valid", True) else 1


def cmd_audit_writing(args: argparse.Namespace) -> int:
    root = root_of(args); source = Path(args.source).expanduser() if args.source else None
    report = audit_writing(root, args.document, source, args.scope, args.variant)
    update_manifest(root, f"audit-writing-{args.document}-{args.variant}", report); print(json.dumps(report, ensure_ascii=False, indent=2)); return 0 if report.get("valid", True) else 1


def cmd_validate(args: argparse.Namespace) -> int:
    root = root_of(args); report = validate(root); update_manifest(root, "validate", report); print(json.dumps(report, ensure_ascii=False, indent=2)); return 0 if report["valid"] else 1


def cmd_write_introduction(args: argparse.Namespace) -> int:
    root = root_of(args)
    if not review_approval_state(root).get("current"):
        raise RuntimeError("综述尚未确认或确认已因正文变更而过期。请先运行 document-approval --document review --status approved。")
    if not introduction_brief_state(root).get("current"):
        raise RuntimeError("绪论简报未绑定当前已确认的综述版本。请先运行 writing-brief --document introduction，允许指定缺口、跳过或不写绪论。")
    source = Path(args.audit_source).expanduser().resolve() if args.audit_source else None
    report = write_introduction(root, source); update_manifest(root, "write-introduction", report)
    print(json.dumps(report, ensure_ascii=False, indent=2)); return 0


def cmd_sync_references(args: argparse.Namespace) -> int:
    root = root_of(args); draft = Path(args.draft).expanduser().resolve() if args.draft else None
    report = sync_references(root, args.document, draft, args.variant); update_manifest(root, f"sync-references-{args.document}-{args.variant}", report)
    print(json.dumps(report, ensure_ascii=False, indent=2)); return 0


def cmd_build_publication(args: argparse.Namespace) -> int:
    root = root_of(args)
    report = prepare_publication(root, args.document) if args.phase == "prepare" else compile_publication(root, args.document) if args.phase == "compile" else validate_publication(root, args.document)
    update_manifest(root, f"build-publication-{args.document}-{args.phase}", report)
    print(json.dumps(report, ensure_ascii=False, indent=2)); return 0 if report.get("valid", True) else 1


def cmd_writing_brief(args: argparse.Namespace) -> int:
    root = root_of(args); gaps = list(args.gap or [])
    if args.document == "introduction" and not review_approval_state(root).get("current"):
        raise RuntimeError("必须先完成并确认系统综述，然后才能单独设置绪论缺口偏好。")
    if args.decline:
        if args.document != "introduction": raise RuntimeError("--decline 仅用于用户明确不撰写绪论")
        approval = review_approval_state(root)
        report = {"document": "introduction", "status": "declined", "user_declined": True, "review_approval_sha256": approval.get("source_sha256"), "review_approved_at": approval.get("approved_at"), "updated_at": utc_stamp()}
        write_json(root / "06_review/introduction_brief.json", report)
        update_manifest(root, "writing-brief-introduction-declined", report); print(json.dumps(report, ensure_ascii=False, indent=2)); return 0
    if not gaps and not args.skip:
        raw = input("请输入希望突出的研究缺口方向（多个用分号分隔，直接回车表示跳过）：").strip()
        gaps = [x.strip() for x in re.split(r"[;；\n]+", raw) if x.strip()]
    report = write_brief(root, args.document, gaps, args.skip or not gaps, not args.no_model_package, list(args.method_preference or []), list(args.method_constraint or []))
    if args.document == "introduction":
        approval = review_approval_state(root)
        report.update({"review_approval_sha256": approval.get("source_sha256"), "review_approved_at": approval.get("approved_at")})
        write_json(root / "06_review/introduction_brief.json", report)
    update_manifest(root, f"writing-brief-{args.document}", report); print(json.dumps(report, ensure_ascii=False, indent=2)); return 0


def cmd_document_approval(args: argparse.Namespace) -> int:
    root = root_of(args); draft = root / "06_review/review_draft.md"
    if not draft.exists(): raise RuntimeError("综述草稿不存在，无法记录审阅结果。")
    audit = read_json(root / "07_logs/writing_audit_review.json", {})
    current_hash = file_sha256(draft)
    if args.status == "approved" and (not audit.get("valid") or audit.get("source_sha256") != current_hash):
        raise RuntimeError("综述逐句审计未通过或已过期，不能确认。请先运行 audit-writing --document review。")
    preview = root / "06_review/previews/review_draft.html"
    if args.status == "approved" and (not preview.exists() or preview.stat().st_mtime < draft.stat().st_mtime):
        raise RuntimeError("综述HTML草稿预览缺失或已过期。请先运行 export-deliverables --document review --draft。")
    report = {"document": "review", "status": args.status, "source": str(draft), "source_sha256": current_hash, "approved_at" if args.status == "approved" else "updated_at": utc_stamp()}
    write_json(root / "06_review/review_approval.json", report)
    update_manifest(root, f"document-approval-review-{args.status}", report)
    print(json.dumps(report, ensure_ascii=False, indent=2)); return 0


def cmd_build_gaps(args: argparse.Namespace) -> int:
    root = root_of(args)
    report = prepare_gaps(root) if args.phase == "prepare" else compile_gaps(root) if args.phase == "compile" else validate_gaps(root)
    update_manifest(root, f"build-gaps-{args.phase}", report); print(json.dumps(report, ensure_ascii=False, indent=2)); return 0 if report.get("valid", True) else 1


def cmd_recommend_design(args: argparse.Namespace) -> int:
    root = root_of(args)
    report = prepare_design(root) if args.phase == "prepare" else compile_design(root) if args.phase == "compile" else validate_design(root)
    update_manifest(root, f"recommend-design-{args.phase}", report); print(json.dumps(report, ensure_ascii=False, indent=2)); return 0 if report.get("valid", True) else 1


def cmd_theory_library(args: argparse.Namespace) -> int:
    """Manage the external library without ever changing task writing state."""
    home = Path(args.home).expanduser().resolve() if getattr(args, "home", None) else None
    action = args.theory_command
    try:
        if action == "init": report = library_status(home)
        elif action == "status": report = library_status(home)
        elif action == "ingest":
            inputs = [Path(x) for x in (args.inputs or [])]
            if args.from_corpus:
                if not args.task: raise RuntimeError("--from-corpus 需要 --task TASK")
                task = Path(args.task).expanduser().resolve()
                inputs += list((task / "03_fulltext/extracted").glob("*.md"))
            if not inputs: raise RuntimeError("请提供理论资料文件/目录，或使用 --from-corpus --task TASK")
            report = ingest_theories(inputs, home, args.copy_sources)
        elif action == "verify": report = verify_theories(args.phase, home)
        elif action == "promote": report = promote_theories(args.ids, args.confirm, home)
        elif action == "search": report = {"status": "ready", "query": args.query, "results": search_theories(args.query, args.limit, home, args.verified_only)}
        elif action == "show": report = show_theory(args.id, home)
        elif action == "update": report = update_theory(args.id, Path(args.input), home)
        elif action == "disable": report = disable_theory(args.id, home)
        elif action == "export": report = export_library(Path(args.output), home)
        elif action == "import": report = import_library(Path(args.bundle), home)
        else: raise RuntimeError(f"未知理论库命令：{action}")
    except Exception as exc:
        report = {"status": "unavailable", "operation": action, "error": str(exc), "non_blocking": True, "writing_continues": True}
    print(json.dumps(report, ensure_ascii=False, indent=2)); return 0


def cmd_theory_support(args: argparse.Namespace) -> int:
    root = root_of(args)
    try: report = set_task_support(root, args.mode)
    except Exception as exc: report = {"status": "unavailable", "mode": args.mode, "error": str(exc), "non_blocking": True, "writing_continues": True}
    update_manifest(root, "theory-support", report); print(json.dumps(report, ensure_ascii=False, indent=2)); return 0


def cmd_theory_recommend(args: argparse.Namespace) -> int:
    root = root_of(args); report = safe_task_theory_phase(root, args.phase, args.limit)
    update_manifest(root, f"theory-recommend-{args.phase}", report); print(json.dumps(report, ensure_ascii=False, indent=2)); return 0


def cmd_export_deliverables(args: argparse.Namespace) -> int:
    root = root_of(args)
    if args.draft:
        report = export_deliverables(root, args.document, draft=True, variant=args.variant)
    else:
        if args.variant in {"evidence-aware", "both"}:
            source = root / "06_review" / ("review_draft.md" if args.document == "review" else "ssci_introduction_audit.md")
            sync_references(root, args.document, source, "evidence-aware")
            validation = validate(root)
            update_manifest(root, "validate-before-export", validation)
            if not validation.get("valid"):
                raise RuntimeError("最终交付已阻止：总体验证未通过。" + "；".join(validation.get("errors", [])[:5]))
        if args.variant in {"publication", "both"}:
            publication_validation = validate_publication(root, args.document)
            update_manifest(root, f"publication-validate-before-export-{args.document}", publication_validation)
            if not publication_validation.get("valid"):
                raise RuntimeError("投稿版交付已阻止：" + "；".join(publication_validation.get("errors", [])[:5]))
        report = export_deliverables(root, args.document, variant=args.variant)
    update_manifest(root, f"export-deliverables-{args.document}-{args.variant}", report); print(json.dumps(report, ensure_ascii=False, indent=2)); return 0


def cmd_status(args: argparse.Namespace) -> int:
    root = root_of(args); corpus = load_jsonl(root / "02_corpus/corpus.jsonl")
    semantic_files = list((root / "05_evidence/semantic/extractions").glob("*.json"))
    batch_tasks = []
    for path in (root / "05_evidence/semantic/batches").glob("*.json"):
        batch_tasks.extend(read_json(path, {}).get("tasks") or [])
    planned_semantic = len({x.get("record_id") for x in batch_tasks if x.get("record_id")}) or len(load_jsonl(root / "05_evidence/citation_coverage_targets.jsonl"))
    reconcile_report = read_json(root / "05_evidence/semantic/semantic_reconcile_report.json", {})
    semantic_state = {"prepared": (root / "05_evidence/semantic/schema.json").exists(), "planned_extractions": planned_semantic, "completed_extractions": sum(read_json(p, {}).get("host_review_status") == "completed" for p in semantic_files), "compiled": (root / "05_evidence/semantic/semantic-synthesis.md").exists(), "reconcile": reconcile_report.get("status", "needs-review"), "validated": bool(read_json(root / "07_logs/semantic_validation.json", {}).get("valid"))}
    manifest = read_json(root / "manifest.json", {})
    status = {"task": str(root), "plan": (root / "00_plan/search_plan.json").exists(), "plan_approved": bool(read_json(root / "00_plan/search_plan.json", {}).get("approved")), "acquisition_mode": manifest.get("acquisition_mode", "unselected"), "metadata_enrichment": manifest.get("metadata_enrichment", "offline"), "corpus_mode": manifest.get("corpus_mode", "unselected"), "records": len(corpus), "extracted_documents": len(list((root / "03_fulltext/extracted").glob("*.md"))), "analysis": (root / "04_analysis/tables/bibliometric_analysis.xlsx").exists(), "evidence_cards": len(list((root / "05_evidence/cards").glob("*.md"))), "outline_status": "missing"}
    outline = root / "06_review/outline.md"
    if outline.exists(): status["outline_status"] = "approved" if "status: approved" in outline.read_text(encoding="utf-8") else "draft-not-approved"
    status["review_draft"] = (root / "06_review/review_draft.md").exists()
    status["review_html"] = (root / "06_review/deliverables/review.html").exists()
    review_preview = root / "06_review/previews/review_draft.html"
    review_source = root / "06_review/review_draft.md"
    status["review_preview_current"] = bool(review_preview.exists() and review_source.exists() and review_preview.stat().st_mtime >= review_source.stat().st_mtime)
    status["introduction_html"] = (root / "06_review/deliverables/introduction.html").exists()
    status["validation_valid"] = bool(read_json(root / "07_logs/validation_report.json", {}).get("valid"))
    status["gap_status"] = read_json(root / "07_logs/gap_validation.json", read_json(root / "05_evidence/gaps/gap_compile_report.json", {"status": "needs-review"})).get("status", "needs-review")
    status["design_status"] = read_json(root / "07_logs/design_validation.json", read_json(root / "05_evidence/design/design_compile_report.json", {"status": "needs-review"})).get("status", "needs-review")
    try: theory_needed = theory_support_needed(root)
    except Exception: theory_needed = False
    theory_mode = manifest.get("theory_support_mode", "unselected")
    theory_report = read_json(root / "07_logs/theory_validation.json", read_json(root / "05_evidence/theories/theory_compile_report.json", {}))
    theory_library_report = safe_theory_status()
    library_state = "unavailable" if theory_library_report.get("status") == "unavailable" else "configured" if theory_library_report.get("cards") else "empty"
    status.update({"theory_support_needed": theory_needed, "theory_support_mode": theory_mode, "theory_library_status": library_state, "theory_recommendation_status": theory_report.get("status", "not-started"), "theory_degradation_reason": theory_report.get("error") or theory_report.get("warnings") or [], "theory_auto_continue": True, "writing_fallback_mode": theory_report.get("writing_fallback_mode", "mechanism-boundary-neutral-narrative")})
    meta_report = read_json(root / "07_logs/meta_validation.json", read_json(root / "05_evidence/meta/meta_compile_report.json", {}))
    status["effect_synthesis"] = meta_report.get("status", "needs-review")
    status["writing_audit"] = {document: read_json(root / f"07_logs/writing_audit_{document}.json", {}).get("status", "needs-review") for document in ("review", "introduction")}
    status["publication"] = {document: {"prepared": (root / f"06_review/{document}_publication_audit.md").exists(), "validation": read_json(root / f"07_logs/publication_validation_{document}.json", {}).get("status", "not-prepared"), "html": (root / f"06_review/deliverables/{document}_publication.html").exists()} for document in ("review", "introduction")}
    approval = review_approval_state(root)
    status["review_approval"] = approval.get("state", "missing")
    intro_brief = introduction_brief_state(root)
    status["introduction_brief_state"] = intro_brief.get("state")
    status["introduction_brief_required"] = bool(approval.get("current") and not intro_brief.get("current"))
    current_platform = platform_report()
    status["platform"] = {"system": current_platform["system"], "python": current_platform["python"], "python_supported": current_platform["python_supported"]}
    requires_input, checkpoint, prompt, replies, auto_continue = False, "none", "", [], True
    if not status["plan"]: next_step = "init --task TASK --title IDEA"; checkpoint = "title-required"; requires_input = True; prompt = "请输入论文题目或研究思路。"; replies = ["论文题目或研究思路"]
    elif not status["plan_approved"]: next_step = "validate-plan；展示计划后等待批准"; checkpoint = "search-plan-approval"; requires_input = True; prompt = "请回复“批准检索计划”，或直接列出需要修改的关键词。"; replies = ["批准检索计划", "修改：……"]
    elif status["acquisition_mode"] == "unselected": next_step = "search-strategy --mode strategy-only|api-search"; checkpoint = "acquisition-mode"; requires_input = True; prompt = "请回复“API自动检索”或“仅生成检索策略”。"; replies = ["API自动检索", "仅生成检索策略"]
    elif not status["records"] and status["acquisition_mode"] == "strategy-only": next_step = "ingest --task TASK RIS_OR_FOLDER"; checkpoint = "local-input-path"; requires_input = True; prompt = "请提供RIS/题录文件或文件夹路径，也可回复“跳过题录导入”。"; replies = ["文件或文件夹路径", "跳过题录导入"]
    elif not status["records"]: next_step = "search --task TASK --confirm"
    elif status["corpus_mode"] == "unselected": next_step = "corpus-policy --mode all|focused"; checkpoint = "corpus-policy"; requires_input = True; prompt = "请回复“全部语料”或“聚焦语料”。"; replies = ["全部语料", "聚焦语料"]
    elif not status["analysis"]: next_step = "analyze --task TASK"
    elif not status["evidence_cards"]: next_step = "build-evidence --task TASK"
    elif semantic_state["prepared"] and semantic_state["completed_extractions"] < semantic_state["planned_extractions"]: next_step = "宿主自动按批完成计划候选语义提取，再 compile/reconcile/validate"
    elif status["outline_status"] != "approved": next_step = "展示研究现状地图与提纲"; checkpoint = "outline-approval"; requires_input = True; prompt = "请回复“确认提纲”，或列出需要调整的章节。"; replies = ["确认提纲", "调整：……"]
    elif not (root / "06_review/review_brief.json").exists(): next_step = "writing-brief --document review"; checkpoint = "review-gap-brief"; requires_input = True; prompt = "请输入希望突出的研究缺口方向，或回复“跳过”。"; replies = ["缺口方向", "跳过"]
    elif status["gap_status"] == "needs-review": next_step = "自动运行 build-gaps prepare/compile/validate，形成经审计缺口或降级研究机会"
    elif theory_needed and theory_mode == "unselected": next_step = "theory-support --mode combined|local-only|llm-only|skip"; checkpoint = "theory-support-choice"; requires_input = True; prompt = "当前进入理论解释阶段。请选择“结合本地理论库与LLM推荐”“仅使用本地理论库”“仅由LLM推荐理论”或“跳过理论支持”。"; replies = ["结合本地理论库与LLM推荐", "仅使用本地理论库", "仅由LLM推荐理论", "跳过理论支持"]
    elif theory_needed and theory_mode != "skip" and status["theory_recommendation_status"] not in {"validated", "degraded", "unavailable", "skipped"}: next_step = "自动运行 theory-recommend prepare/compile/validate；无合适理论时自动降级并继续写作"
    elif status["design_status"] == "needs-review": next_step = "自动运行 recommend-design prepare/compile/validate，先选设计再匹配方法"
    elif not status["review_draft"]: next_step = "自动分节写作、补足引用、同步参考文献并验证"
    elif status["writing_audit"]["review"] != "validated": next_step = "自动运行audit-writing --document review，完成逐句支持复核后重跑"
    elif not status["review_preview_current"]: next_step = "自动运行 export-deliverables --document review --draft 生成不覆盖最终成果的HTML审阅稿"
    elif not approval.get("current"): next_step = "document-approval --document review --status approved|revision-requested"; checkpoint = "review-approval"; requires_input = True; prompt = "请审阅系统综述：满意请回复“确认综述”，或直接列出修改意见。"; replies = ["确认综述", "修改：……"]
    elif not status["publication"]["review"]["prepared"]: next_step = "自动运行 build-publication --document review --phase prepare，完成投稿语义改写、原子引文归属、compile与validate"
    elif status["publication"]["review"]["validation"] != "validated": next_step = "自动完成综述投稿版改写队列、原子引文审计和验证"
    elif not intro_brief.get("current"): next_step = "writing-brief --document introduction"; checkpoint = "introduction-decision"; requires_input = True; prompt = "综述已确认。请单独输入绪论希望突出的一个或多个研究缺口/研究问题；也可回复“跳过”或“不写绪论”。"; replies = ["绪论缺口：……", "跳过", "不写绪论"]
    elif intro_brief.get("user_declined"): next_step = "验证并导出系统综述HTML/RIS（用户已选择不写绪论）"
    elif not (root / "06_review/ssci_introduction_audit.md").exists(): next_step = "自动撰写绪论、同步文末参考文献并验证"
    elif status["writing_audit"]["introduction"] != "validated": next_step = "自动运行audit-writing --document introduction，完成漏斗角色与逐句支持复核"
    elif not status["publication"]["introduction"]["prepared"]: next_step = "自动运行 build-publication --document introduction --phase prepare，完成投稿语义改写、原子引文归属、compile与validate"
    elif status["publication"]["introduction"]["validation"] != "validated": next_step = "自动完成绪论投稿版改写队列、原子引文审计和验证"
    elif status["review_html"] and status["introduction_html"] and status["publication"]["review"]["html"] and status["publication"]["introduction"]["html"] and status["validation_valid"]: next_step = "任务已完成；如正文或语料变更，重新运行 validate 与 export-deliverables --variant both"
    else: next_step = "validate 后 export-deliverables --document review|introduction"
    auto_continue = not requires_input
    status["advanced_modules"] = read_json(root / "04_analysis/advanced_module_status.json", {})
    status["semantic"] = semantic_state
    status["writing_context"] = read_json(root / "05_evidence/writing-context-manifest.json", {})
    status.update({"recommended_next_step": next_step, "requires_user_input": requires_input, "checkpoint": checkpoint, "user_prompt": prompt, "accepted_replies": replies, "next_command": next_step, "auto_continue": auto_continue})
    print(json.dumps(status, ensure_ascii=False, indent=2)); return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    skill = SCRIPT_DIR.parent; entry_targets = install_targets("both", "project")
    if args.repair:
        for host, target in entry_targets.items(): install_one(host, target, "auto")
    entries = {host: inspect_one(host, target) for host, target in entry_targets.items()}
    checks = {"platform": platform_report(), "dependencies": dependency_versions(), "entries": entries,
              "skill_writable": os.access(skill, os.W_OK), "credentials": credential_status(), "theory_library": safe_theory_status()}
    required = {"numpy", "pandas", "scipy", "scikit-learn", "networkx", "requests", "openpyxl", "matplotlib", "PyMuPDF", "python-docx", "tabulate"}
    required_missing = [k for k, v in checks["dependencies"].items() if v == "missing" and k in required]
    checks["optional_python"] = {name: {"status": "ready" if checks["dependencies"].get(name) != "missing" else "skipped-unavailable", "recovery": f'{sys.executable} -m pip install {name}'} for name in ("jieba", "xlrd")}
    checks["ok"] = bool(checks["platform"]["python_supported"] and not required_missing and all(x["status"] == "ready" for x in entries.values()))
    py = f'"{sys.executable}"'; checks["recommended_actions"] = ([f"{py} -m pip install -r \"{skill / 'scripts/requirements-core.txt'}\""] if required_missing else []) + ([f"{py} \"{__file__}\" credentials setup --input auto"] if not checks["credentials"]["configured"] else [])
    print(json.dumps(checks, ensure_ascii=False, indent=2)); return 0 if checks["ok"] else 1


def cmd_wizard(args: argparse.Namespace) -> int:
    if getattr(args, "workflow", "research") == "theory-library":
        report = safe_theory_status(); report["next"] = "theory-library ingest INPUT..."; print(json.dumps(report, ensure_ascii=False, indent=2)); return 0
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
    setup = credsub.add_parser("setup"); setup.add_argument("--include-semantic-scholar", action="store_true"); setup.add_argument("--input", choices=["auto", "gui", "terminal"], default="auto"); setup.set_defaults(func=cmd_credentials)
    cstatus = credsub.add_parser("status"); cstatus.set_defaults(func=cmd_credentials)
    ctest = credsub.add_parser("test"); ctest.add_argument("--timeout", type=int, default=15); ctest.set_defaults(func=cmd_credentials)
    update = credsub.add_parser("update"); update.add_argument("--name", required=True, choices=list(credentials_names())); update.add_argument("--input", choices=["auto", "gui", "terminal"], default="auto"); update.set_defaults(func=cmd_credentials)
    delete = credsub.add_parser("delete"); delete.add_argument("--name", choices=list(credentials_names()), default="OPENALEX_API_KEY"); delete.add_argument("--all", action="store_true"); delete.add_argument("--yes", action="store_true"); delete.set_defaults(func=cmd_credentials)
    theory = sub.add_parser("theory-library", help="独立建立、导入、核验和维护外部个人理论库")
    theorysub = theory.add_subparsers(dest="theory_command", required=True)
    for name in ("init", "status"):
        item = theorysub.add_parser(name); item.add_argument("--home"); item.set_defaults(func=cmd_theory_library)
    ting = theorysub.add_parser("ingest"); ting.add_argument("inputs", nargs="*"); ting.add_argument("--task"); ting.add_argument("--from-corpus", action="store_true"); ting.add_argument("--copy-sources", action="store_true"); ting.add_argument("--home"); ting.set_defaults(func=cmd_theory_library)
    tverify = theorysub.add_parser("verify"); tverify.add_argument("--phase", required=True, choices=["prepare", "compile", "validate"]); tverify.add_argument("--home"); tverify.set_defaults(func=cmd_theory_library)
    tpromote = theorysub.add_parser("promote"); tpromote.add_argument("--ids", nargs="+", required=True); tpromote.add_argument("--confirm", action="store_true"); tpromote.add_argument("--home"); tpromote.set_defaults(func=cmd_theory_library)
    tsearch = theorysub.add_parser("search"); tsearch.add_argument("--query", required=True); tsearch.add_argument("--limit", type=int, default=8); tsearch.add_argument("--verified-only", action="store_true"); tsearch.add_argument("--home"); tsearch.set_defaults(func=cmd_theory_library)
    tshow = theorysub.add_parser("show"); tshow.add_argument("--id", required=True); tshow.add_argument("--home"); tshow.set_defaults(func=cmd_theory_library)
    tupdate = theorysub.add_parser("update"); tupdate.add_argument("--id", required=True); tupdate.add_argument("--input", required=True); tupdate.add_argument("--home"); tupdate.set_defaults(func=cmd_theory_library)
    tdisable = theorysub.add_parser("disable"); tdisable.add_argument("--id", required=True); tdisable.add_argument("--home"); tdisable.set_defaults(func=cmd_theory_library)
    texport = theorysub.add_parser("export"); texport.add_argument("--output", required=True); texport.add_argument("--home"); texport.set_defaults(func=cmd_theory_library)
    timport = theorysub.add_parser("import"); timport.add_argument("--bundle", required=True); timport.add_argument("--home"); timport.set_defaults(func=cmd_theory_library)
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
    ana.add_argument("--language", choices=["auto", "zh", "en", "mixed"], default="auto"); ana.add_argument("--bootstrap-runs", type=int, default=5)
    ana.add_argument("--nmf-structure", choices=["auto", "strict", "off"], default="auto")
    ana.add_argument("--skip-kmeans", action="store_true"); ana.add_argument("--strategic-map", choices=["auto", "on", "off"], default="auto"); ana.add_argument("--citation-age", choices=["auto", "on", "off"], default="auto"); ana.add_argument("--knowledge-flow", choices=["auto", "on", "off"], default="auto"); ana.set_defaults(func=cmd_analyze)
    ev = sub.add_parser("build-evidence"); ev.add_argument("--task", required=True); ev.set_defaults(func=cmd_build_evidence)
    sem = sub.add_parser("build-semantic"); sem.add_argument("--task", required=True); sem.add_argument("--phase", required=True, choices=["prepare", "compile", "reconcile", "validate"]); sem.add_argument("--batch-size", type=int, default=12); sem.add_argument("--budget", choices=["balanced", "exhaustive"], default="balanced"); sem.set_defaults(func=cmd_build_semantic)
    meta = sub.add_parser("synthesize-effects"); meta.add_argument("--task", required=True); meta.add_argument("--phase", required=True, choices=["prepare", "compile", "validate"]); meta.set_defaults(func=cmd_synthesize_effects)
    writing_audit = sub.add_parser("audit-writing"); writing_audit.add_argument("--task", required=True); writing_audit.add_argument("--document", choices=["review", "introduction"], required=True); writing_audit.add_argument("--variant", choices=["evidence-aware", "publication"], default="evidence-aware"); writing_audit.add_argument("--source"); writing_audit.add_argument("--scope", default="final"); writing_audit.set_defaults(func=cmd_audit_writing)
    emb = sub.add_parser("semantic-embeddings"); emb.add_argument("--task", required=True); emb.add_argument("--dry-run", action="store_true"); emb.set_defaults(func=cmd_semantic_embeddings)
    val = sub.add_parser("validate"); val.add_argument("--task", required=True); val.set_defaults(func=cmd_validate)
    intro = sub.add_parser("write-introduction"); intro.add_argument("--task", required=True); intro.add_argument("--audit-source"); intro.set_defaults(func=cmd_write_introduction)
    sync = sub.add_parser("sync-references"); sync.add_argument("--task", required=True); sync.add_argument("--document", choices=["review", "introduction"], default="review"); sync.add_argument("--variant", choices=["evidence-aware", "publication"], default="evidence-aware"); sync.add_argument("--draft"); sync.set_defaults(func=cmd_sync_references)
    brief = sub.add_parser("writing-brief"); brief.add_argument("--task", required=True); brief.add_argument("--document", choices=["review", "introduction"], required=True); brief.add_argument("--gap", action="append"); brief.add_argument("--method-preference", action="append"); brief.add_argument("--method-constraint", action="append"); brief.add_argument("--skip", action="store_true"); brief.add_argument("--decline", action="store_true"); brief.add_argument("--no-model-package", action="store_true"); brief.set_defaults(func=cmd_writing_brief)
    approval = sub.add_parser("document-approval"); approval.add_argument("--task", required=True); approval.add_argument("--document", choices=["review"], required=True); approval.add_argument("--status", choices=["approved", "revision-requested"], required=True); approval.set_defaults(func=cmd_document_approval)
    gaps = sub.add_parser("build-gaps"); gaps.add_argument("--task", required=True); gaps.add_argument("--phase", required=True, choices=["prepare", "compile", "validate"]); gaps.set_defaults(func=cmd_build_gaps)
    design = sub.add_parser("recommend-design"); design.add_argument("--task", required=True); design.add_argument("--phase", required=True, choices=["prepare", "compile", "validate"]); design.set_defaults(func=cmd_recommend_design)
    tsupport = sub.add_parser("theory-support"); tsupport.add_argument("--task", required=True); tsupport.add_argument("--mode", required=True, choices=["combined", "local-only", "llm-only", "skip"]); tsupport.set_defaults(func=cmd_theory_support)
    trecommend = sub.add_parser("theory-recommend"); trecommend.add_argument("--task", required=True); trecommend.add_argument("--phase", required=True, choices=["prepare", "compile", "validate"]); trecommend.add_argument("--limit", type=int, default=8); trecommend.set_defaults(func=cmd_theory_recommend)
    publication = sub.add_parser("build-publication"); publication.add_argument("--task", required=True); publication.add_argument("--document", choices=["review", "introduction"], required=True); publication.add_argument("--phase", required=True, choices=["prepare", "compile", "validate"]); publication.set_defaults(func=cmd_build_publication)
    delivery = sub.add_parser("export-deliverables"); delivery.add_argument("--task", required=True); delivery.add_argument("--document", choices=["review", "introduction"], required=True); delivery.add_argument("--variant", choices=["evidence-aware", "publication", "both"], default="evidence-aware"); delivery.add_argument("--draft", action="store_true", help="仅生成明确标记的未验证预览，不覆盖最终交付"); delivery.set_defaults(func=cmd_export_deliverables)
    status = sub.add_parser("status"); status.add_argument("--task", required=True); status.set_defaults(func=cmd_status)
    doctor = sub.add_parser("doctor"); doctor.add_argument("--json", action="store_true"); doctor.add_argument("--repair", action="store_true"); doctor.set_defaults(func=cmd_doctor)
    wizard = sub.add_parser("wizard"); wizard.add_argument("--workflow", choices=["research", "theory-library"], default="research"); wizard.add_argument("--task"); wizard.add_argument("--title"); wizard.add_argument("--mode", choices=["strategy-only", "api-search"]); wizard.set_defaults(func=cmd_wizard)
    return p


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    try: return args.func(args)
    except Exception as exc:
        command = getattr(args, "command", "") or "status"
        task = getattr(args, "task", "")
        document = getattr(args, "document", "")
        parts = [sys.executable, str(Path(__file__).resolve()), command]
        if task: parts += ["--task", str(task)]
        if document: parts += ["--document", str(document)]
        recovery = subprocess.list2cmdline(parts) if os.name == "nt" else shlex.join(parts)
        print(json.dumps(failure(command, exc, ["已有任务文件保持不变"], recovery), ensure_ascii=False, indent=2), file=sys.stderr)
        return 1


if __name__ == "__main__": raise SystemExit(main())
