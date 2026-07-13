#!/usr/bin/env python3
"""Evidence-grounded research-gap audit and dynamic research-design matching."""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

import pandas as pd

from common import load_jsonl, read_csv_optional, read_json, utc_stamp, write_json, write_jsonl


GAP_REQUIRED = [
    "gap_id", "title", "level", "failure_type", "target_question", "known_findings",
    "current_explanation", "failure_point", "failure_evidence", "counterevidence",
    "comparability", "knowledge_consequence", "practical_importance", "repair_strategy",
    "research_questions", "discriminating_predictions", "design_requirements",
    "inferential_goals", "confidence", "evidence_level", "status",
]
LEVEL_A = {"assumption-failure", "competing-explanations", "contradiction", "mechanism-missing", "boundary-failure", "construct-mismatch", "phenomenon-vocabulary"}
LEVEL_B = {"measurement", "causal-identification", "bias", "imprecision", "inconsistency", "sample-dependence", "external-validity", "intention-behavior"}
LEVEL_C = {"understudied-context", "understudied-population", "underused-method", "understudied-combination", "distribution-only"}
WEAK_SIGNAL = re.compile(r"研究较少|关注不足|尚未研究|国内.{0,8}(?:缺乏|不足)|文献不足|未使用.{0,12}方法|understudied|few studies|not been studied", re.I)
FRAGMENT_SIGNAL = re.compile(r"研究碎片化|文献碎片化|未形成统一框架|没有统一框架|fragmented|no unified framework", re.I)


def _catalog(root: Path) -> list[dict[str, Any]]:
    return json.loads((Path(__file__).resolve().parents[1] / "assets/method_catalog.json").read_text(encoding="utf-8"))


def _method_counts(root: Path) -> Counter:
    path = root / "05_evidence/semantic/method_context_outcome_matrix.csv"
    counts: Counter = Counter()
    if not path.exists(): return counts
    frame = read_csv_optional(path, ["methods"])
    for value in frame.get("methods", []):
        for item in re.split(r"[;,；|]+", str(value)):
            item = item.strip().lower()
            if item: counts[item] += 1
    return counts


def gap_template(gap_id: str, title: str = "") -> dict[str, Any]:
    return {
        "gap_id": gap_id, "title": title, "level": "C", "failure_type": "distribution-only",
        "target_question": "", "known_findings": [], "current_explanation": [], "failure_point": "",
        "failure_evidence": [], "counterevidence": [],
        "comparability": {"constructs": "unchecked", "outcomes": "unchecked", "samples": "unchecked", "contexts": "unchecked", "time": "unchecked", "designs": "unchecked"},
        "mechanism_audit": {"base_relation_supported": False, "synonyms_checked": False, "statistical_mediation_only": "unchecked"}, "boundary_assumption": "",
        "knowledge_consequence": "", "practical_importance": "", "repair_strategy": "",
        "research_questions": [], "discriminating_predictions": [], "design_requirements": [],
        "inferential_goals": [], "confidence": "low", "evidence_level": "bibliometric-signal",
        "status": "opportunity", "source_signals": [], "notes": "",
    }


def prepare_gaps(root: Path) -> dict[str, Any]:
    base = root / "05_evidence/gaps"; base.mkdir(parents=True, exist_ok=True)
    candidates: list[dict[str, Any]] = []
    table = root / "04_analysis/tables/gap_candidates.csv"
    if table.exists():
        for row in read_csv_optional(table, ["gap_id", "candidate_gap", "topic_id", "documents"]).to_dict("records"):
            item = gap_template(str(row.get("gap_id") or f"G{len(candidates)+1:03d}"), str(row.get("candidate_gap") or ""))
            item.update({"source": "bibliometric", "topic_id": row.get("topic_id"), "documents": int(row.get("documents") or 0), "source_signals": ["04_analysis/tables/gap_candidates.csv"]})
            candidates.append(item)
    counter = root / "05_evidence/semantic/counter_and_null_evidence.csv"
    if counter.exists():
        frame = read_csv_optional(counter, ["record_id", "direction", "finding", "anchor"])
        if not frame.empty:
            item = gap_template(f"GS{len(candidates)+1:03d}", "反向、不显著或混合证据需要可比性诊断")
            item.update({"level": "B", "failure_type": "inconsistency", "status": "candidate", "confidence": "medium", "evidence_level": "semantic-extraction", "failure_evidence": sorted(set(frame.get("record_id", []))), "source": "semantic", "source_signals": ["05_evidence/semantic/counter_and_null_evidence.csv"]})
            candidates.append(item)
    write_jsonl(base / "gap_candidates.jsonl", candidates)
    ledger = base / "gap_ledger.jsonl"
    if not ledger.exists(): write_jsonl(ledger, candidates)
    packet = ["# Research-gap candidate packet", "", "> 计量信号只能定位问题，不能证明研究缺口。宿主模型必须用摘要/全文证据完成 gap ledger。", "", f"- candidates: {len(candidates)}", f"- semantic counter/null records: {sum(len(x.get('failure_evidence') or []) for x in candidates)}", "", "## Promotion rule", "", "C级分布信号只有在说明理论边界、可信推断或重要决策后果后才能升级。方法未使用本身不得升级。"]
    (base / "gap_candidate_packet.md").write_text("\n".join(packet) + "\n", encoding="utf-8")
    note = "" if candidates else "未发现可结构化关系，不代表没有研究缺口；请继续进行语义证据诊断。"
    report = {"phase": "prepare", "status": "prepared", "candidates": len(candidates), "ledger": str(ledger), "host_action": "complete gap_ledger.jsonl from content evidence", "note": note}
    write_json(base / "gap_prepare_report.json", report); return report


def _record_ids(item: dict[str, Any]) -> set[str]:
    values: list[Any] = []
    for field in ("failure_evidence", "counterevidence"):
        values.extend(item.get(field) or [])
    for finding in item.get("known_findings") or []:
        if isinstance(finding, dict): values.extend(finding.get("record_ids") or [])
    return {str(x) for x in values if re.fullmatch(r"R[0-9a-f]{14}", str(x))}


def _normalize_gap(item: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    item = {**gap_template(str(item.get("gap_id") or "GAP-UNKNOWN")), **item}; notes = []
    failure = str(item.get("failure_type") or "distribution-only")
    title_text = " ".join(str(item.get(k) or "") for k in ("title", "failure_point", "knowledge_consequence"))
    if failure in LEVEL_A: item["level"] = "A"
    elif failure in LEVEL_B: item["level"] = "B"
    else: item["level"] = "C"
    if failure == "underused-method" or re.search(r"方法缺口|未使用.{0,12}方法", title_text):
        item.update({"level": "C", "failure_type": "underused-method", "status": "opportunity", "confidence": "low"}); notes.append("方法未使用只能作为低等级研究机会")
    substantive = all(bool(item.get(field)) for field in ("known_findings", "current_explanation", "failure_point", "failure_evidence", "knowledge_consequence", "repair_strategy", "research_questions", "design_requirements"))
    if item["level"] in {"A", "B"} and substantive:
        comp = item.get("comparability") or {}
        if failure in {"contradiction", "inconsistency"} and any(str(comp.get(k, "unchecked")) in {"unchecked", "not-comparable", "false"} for k in ("constructs", "outcomes", "designs")):
            item.update({"level": "C", "status": "opportunity", "confidence": "low"}); notes.append("矛盾证据未通过构念/结果/设计可比性检查")
        else: item["status"] = "validated"
    elif item["level"] in {"A", "B"}:
        item.update({"level": "C", "status": "opportunity", "confidence": "low"}); notes.append("缺少解释失效或证据失效的完整诊断，已降级")
    if WEAK_SIGNAL.search(title_text) and not item.get("knowledge_consequence"):
        item.update({"level": "C", "status": "opportunity", "confidence": "low"}); notes.append("仅有研究分布信号，没有知识后果")
    if FRAGMENT_SIGNAL.search(title_text) and not any(x in str(item.get("failure_point")) for x in ("假设", "构念", "机制", "边界", "设计")):
        item.update({"level": "C", "status": "opportunity", "confidence": "low"}); notes.append("碎片化来源未被诊断")
    if failure == "mechanism-missing":
        audit = item.get("mechanism_audit") or {}
        if not audit.get("base_relation_supported") or not audit.get("synonyms_checked") or str(audit.get("statistical_mediation_only")) not in {"false", "False", "no", "not-only"}:
            item.update({"level": "C", "status": "opportunity", "confidence": "low"}); notes.append("机制缺口未完成基础关系、同义机制或统计中介审计")
    if failure in {"boundary-failure", "external-validity"} and not item.get("boundary_assumption"):
        item.update({"level": "C", "status": "opportunity", "confidence": "low"}); notes.append("情境/外部效度缺口未指出被改变的理论边界假设")
    item["audit_notes"] = list(dict.fromkeys((item.get("audit_notes") or []) + notes)); return item, notes


def compile_gaps(root: Path) -> dict[str, Any]:
    base = root / "05_evidence/gaps"; ledger_path = base / "gap_ledger.jsonl"
    if not ledger_path.exists(): prepare_gaps(root)
    normalized, notes = [], []
    for item in load_jsonl(ledger_path):
        row, row_notes = _normalize_gap(item); normalized.append(row); notes.extend(f"{row['gap_id']}: {note}" for note in row_notes)
    write_jsonl(ledger_path, normalized)
    counts = Counter(x.get("status") for x in normalized); levels = Counter(x.get("level") for x in normalized)
    state = "validated" if counts.get("validated") else "opportunity-only"
    lines = ["# Research gap audit", "", f"- status: {state}", f"- A/B validated gaps: {sum(x.get('status') == 'validated' and x.get('level') in {'A','B'} for x in normalized)}", f"- C-level opportunities: {sum(x.get('level') == 'C' for x in normalized)}", "", "## Validated gaps", ""]
    for row in normalized:
        if row.get("status") == "validated": lines += [f"### {row['gap_id']} · {row.get('title')}", "", f"- level/failure: {row.get('level')} / {row.get('failure_type')}", f"- failure point: {row.get('failure_point')}", f"- consequence: {row.get('knowledge_consequence')}", f"- repair: {row.get('repair_strategy')}", ""]
    lines += ["## Downgraded opportunities", ""]
    for row in normalized:
        if row.get("status") == "opportunity": lines += [f"- {row['gap_id']}: {row.get('title')} — {'; '.join(row.get('audit_notes') or ['低等级分布性机会'])}"]
    if state == "opportunity-only": lines += ["", "> 未识别出高置信解释性或证据性缺口；以下内容只能作为研究机会，不应宣称强理论贡献。"]
    (base / "gap_audit.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    report = {"phase": "compile", "status": state, "records": len(normalized), "levels": dict(levels), "statuses": dict(counts), "warnings": notes}
    write_json(base / "gap_compile_report.json", report); return report


def validate_gaps(root: Path) -> dict[str, Any]:
    base = root / "05_evidence/gaps"; ledger = load_jsonl(base / "gap_ledger.jsonl")
    if not ledger: return {"phase": "validate", "status": "needs-review", "valid": True, "errors": [], "warnings": ["尚无 gap ledger；缺口只能作为未审计候选"]}
    corpus_ids = {x.get("record_id") for x in load_jsonl(root / "02_corpus/corpus.jsonl")}
    errors, warnings = [], []
    normalized = []
    for raw in ledger:
        item, notes = _normalize_gap(raw); normalized.append(item)
        missing_fields = [x for x in GAP_REQUIRED if x not in raw]
        if missing_fields: warnings.append(f"{item['gap_id']}缺少字段并已使用默认值: {missing_fields}")
        unknown = _record_ids(item) - corpus_ids
        if unknown: errors.append(f"{item['gap_id']}引用不存在的文献: {sorted(unknown)}")
        warnings.extend(f"{item['gap_id']}: {note}" for note in notes)
    validated = [x for x in normalized if x.get("status") == "validated" and x.get("level") in {"A", "B"}]
    status = "validated" if validated else "opportunity-only"
    if not validated: warnings.append("未识别出高置信解释性或证据性缺口；最终稿必须将其表述为低等级研究机会")
    for manuscript in (root / "06_review/review_draft.md", root / "06_review/ssci_introduction_audit.md"):
        if not manuscript.exists(): continue
        text = manuscript.read_text(encoding="utf-8")
        if re.search(r"方法缺口|未使用.{0,12}(?:方法|模型)", text): warnings.append(f"{manuscript.name}仍将方法未使用表述为缺口，应改写为识别或设计问题")
        for paragraph in re.split(r"\n\s*\n", text):
            if WEAK_SIGNAL.search(paragraph) and not re.search(r"理论|解释|推断|识别|外部效度|决策|后果|边界|机制", paragraph):
                warnings.append(f"{manuscript.name}含未说明知识后果的研究分布表述：{paragraph[:60]}")
            if FRAGMENT_SIGNAL.search(paragraph) and not re.search(r"假设|构念|机制|边界|设计", paragraph):
                warnings.append(f"{manuscript.name}声称碎片化但未诊断来源：{paragraph[:60]}")
        if status == "opportunity-only" and "未识别出高置信解释性或证据性缺口" not in text:
            warnings.append(f"{manuscript.name}在仅有C级机会时缺少明确降级声明")
    report = {"phase": "validate", "status": status, "valid": not errors, "errors": errors, "warnings": list(dict.fromkeys(warnings)), "validated_gaps": len(validated), "opportunities": sum(x.get("level") == "C" for x in normalized)}
    write_json(root / "07_logs/gap_validation.json", report); return report


def _goals_for_gap(gap: dict[str, Any]) -> list[str]:
    goals = [str(x) for x in gap.get("inferential_goals") or []]
    if goals: return goals
    mapping = {
        "measurement": ["measurement"], "causal-identification": ["causal"], "mechanism-missing": ["explanation", "mechanism"],
        "competing-explanations": ["explanation", "mechanism"], "contradiction": ["explanation", "heterogeneity"],
        "inconsistency": ["synthesis", "heterogeneity"], "boundary-failure": ["heterogeneity"], "external-validity": ["heterogeneity"],
        "intention-behavior": ["longitudinal", "causal"], "construct-mismatch": ["measurement", "qualitative"],
    }
    return mapping.get(str(gap.get("failure_type")), ["description"])


def prepare_design(root: Path) -> dict[str, Any]:
    base = root / "05_evidence/design"; base.mkdir(parents=True, exist_ok=True)
    gaps = load_jsonl(root / "05_evidence/gaps/gap_ledger.jsonl")
    selected_gaps = [g for g in gaps if g.get("status") == "validated"] or [g for g in gaps if g.get("status") == "opportunity"]
    brief = read_json(root / "06_review/review_brief.json", {})
    data = {"status": "prepared", "selection_mode": "corpus-evidence-plus-general-method-library", "method_preferences": brief.get("method_preferences") or [], "method_constraints": brief.get("method_constraints") or [], "questions": [{"gap_id": g.get("gap_id"), "gap_level": g.get("level"), "research_questions": g.get("research_questions") or [], "inferential_goals": _goals_for_gap(g), "design_requirements": g.get("design_requirements") or []} for g in selected_gaps], "method_usage_in_corpus": dict(_method_counts(root).most_common(30)), "rule": "select design before estimator; user preferences require fit audit; use C-level opportunities only when no A/B gap is validated"}
    write_json(base / "research_design_brief.json", data)
    lines = ["# Research design brief", "", f"- selection mode: {data['selection_mode']}", f"- user method preferences: {', '.join(data['method_preferences']) or 'none'}", f"- constraints: {', '.join(data['method_constraints']) or 'none'}", "", "宿主模型应先明确推断目标和最有识别力的设计，再选择主要、辅助和稳健性方法。数据条件未知时输出条件分支。"]
    (base / "research_design_brief.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {"phase": "prepare", "status": "prepared", "questions": len(data["questions"]), "catalog_methods": len(_catalog(root))}


def compile_design(root: Path) -> dict[str, Any]:
    base = root / "05_evidence/design"
    if not (base / "research_design_brief.json").exists(): prepare_design(root)
    brief = read_json(base / "research_design_brief.json", {}); catalog = _catalog(root); usage = brief.get("method_usage_in_corpus") or {}
    recommendations = []
    for question in brief.get("questions") or []:
        goals = set(question.get("inferential_goals") or [])
        scored = []
        for method in catalog:
            overlap = goals & set(method.get("inferential_goals") or [])
            if overlap: scored.append((len(overlap), method))
        for rank, (_, method) in enumerate(sorted(scored, key=lambda x: (-x[0], x[1]["method_id"]))[:4], 1):
            corpus_mentions = sum(count for name, count in usage.items() if method["method_id"].replace("-", " ") in name or any(alias.lower() in name for alias in method.get("aliases") or []))
            recommendations.append({"gap_id": question.get("gap_id"), "research_question": (question.get("research_questions") or [""])[0], "inferential_goals": sorted(goals), "method_id": method["method_id"], "method": method["name"], "role": "primary-candidate" if rank == 1 else "alternative-or-robustness", "design_first": method["design"], "data_requirements": method["data_requirements"], "assumptions": method["assumptions"], "cannot_answer": method["cannot_answer"], "robustness": method["robustness"], "common_misuse": method["common_misuse"], "corpus_mentions": corpus_mentions, "conditional": True, "fit_rationale": f"matches goals: {', '.join(sorted(goals & set(method.get('inferential_goals') or [])))}"})
    write_jsonl(base / "method_recommendations.jsonl", recommendations)
    frame = pd.DataFrame(recommendations); frame.to_csv(base / "method_fit_matrix.csv", index=False, encoding="utf-8-sig")
    md = "# Method fit matrix\n\n> 方法复杂度、流行度和新颖性均不构成研究贡献。所有推荐均以数据与识别条件成立为前提。\n\n" + (frame.to_markdown(index=False) if not frame.empty else "无可匹配的研究问题。") + "\n"
    (base / "method_fit_matrix.md").write_text(md, encoding="utf-8")
    status = "validated" if recommendations else "needs-review"
    report = {"phase": "compile", "status": status, "recommendations": len(recommendations), "questions": len({x.get('gap_id') for x in recommendations})}
    write_json(base / "design_compile_report.json", report); return report


def validate_design(root: Path) -> dict[str, Any]:
    base = root / "05_evidence/design"; rows = load_jsonl(base / "method_recommendations.jsonl")
    catalog = {x["method_id"]: x for x in _catalog(root)}; errors, warnings = [], []
    brief = read_json(base / "research_design_brief.json", {}); preferences = {str(x).lower() for x in brief.get("method_preferences") or []}
    for row in rows:
        method_id = row.get("method_id")
        if method_id not in catalog: errors.append(f"未知方法ID: {method_id}"); continue
        goals = set(row.get("inferential_goals") or [])
        compatible = goals & set(catalog[method_id].get("inferential_goals") or [])
        if not compatible: errors.append(f"{method_id}与推断目标不匹配: {sorted(goals)}")
        if not row.get("design_first") or not row.get("assumptions") or not row.get("cannot_answer"): errors.append(f"{method_id}缺少设计、假设或不可回答范围")
    selected_names = {str(x.get("method_id", "")).lower() for x in rows} | {str(x.get("method", "")).lower() for x in rows}
    for preference in preferences:
        if not any(preference in name for name in selected_names): warnings.append(f"用户偏好方法“{preference}”未通过当前问题适配，不应强行采用")
    report = {"phase": "validate", "status": "validated" if rows and not errors else "needs-review", "valid": not errors, "errors": errors, "warnings": warnings, "recommendations": len(rows), "preferences_audited": len(preferences)}
    write_json(root / "07_logs/design_validation.json", report); return report
