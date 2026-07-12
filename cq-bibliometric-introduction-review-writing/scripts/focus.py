#!/usr/bin/env python3
"""Deterministic relevance screening for a livestream-commerce core corpus."""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from typing import Any


DIRECT_QUERY_IDS = {"Q01-ZH", "Q01-EN", "Q02-EN", "Q03-ZH", "Q04-EN", "Q05-EN", "Q08-EN"}
THEORY_QUERY_IDS = {"Q06-EN", "Q07-EN"}

CONTEXT_TERMS = ["livestream", "live stream", "livestreaming", "live commerce", "live shopping", "live streaming commerce", "直播", "直播电商", "直播购物", "电商直播", "直播带货"]
OVERLOAD_TERMS = ["information overload", "information overabundance", "cognitive overload", "choice overload", "decision fatigue", "information complexity", "信息超载", "信息过载", "认知超载", "认知负荷", "选择超载", "决策疲劳"]
DECISION_TERMS = ["consumer", "customer", "shopper", "buyer", "purchase", "purchasing", "buying", "shopping", "purchase intention", "impulse buying", "decision quality", "decision making", "购买", "消费者", "消费", "购物", "购买意愿", "购买决策", "冲动购买", "决策质量"]
EXCLUSION_TERMS = ["covid", "coronavirus", "pandemic", "vaccination", "healthcare", "health care", "medical", "clinical", "patient", "nursing", "electronic health record", "ehr", "游戏", "电竞", "gaming", "esports", "education", "educational", "student", "learning", "teaching", "医疗", "患者", "健康", "教育", "学生", "教学"]


def _text(record: dict[str, Any]) -> str:
    return " ".join([str(record.get("title") or ""), str(record.get("abstract") or ""), " ".join(str(x) for x in record.get("keywords") or [])]).lower()


def _hits(text: str, terms: list[str]) -> list[str]:
    return [term for term in terms if term in text]


def classify_record(record: dict[str, Any]) -> tuple[str, list[str]]:
    text = _text(record)
    query_ids = set(record.get("query_ids") or [])
    excluded = _hits(text, EXCLUSION_TERMS)
    context, overload, decision = _hits(text, CONTEXT_TERMS), _hits(text, OVERLOAD_TERMS), _hits(text, DECISION_TERMS)
    reasons = []
    if excluded:
        return "excluded", [f"排除情境：{', '.join(excluded[:4])}"]
    direct_hit = query_ids & DIRECT_QUERY_IDS
    theory_hit = query_ids & THEORY_QUERY_IDS
    wos_only = bool((record.get("ids") or {}).get("wos")) and not query_ids
    if direct_hit and context and (overload or decision):
        reasons = [f"直接查询命中：{', '.join(sorted(direct_hit))}", f"直播情境：{', '.join(context[:3])}"]
        if overload: reasons.append(f"超载信号：{', '.join(overload[:3])}")
        return "core", reasons
    if wos_only and context and overload and decision:
        return "core", ["WoS-only 直接相关", f"直播情境：{', '.join(context[:3])}", f"超载信号：{', '.join(overload[:3])}", f"消费者决策：{', '.join(decision[:3])}"]
    if (theory_hit or wos_only) and overload and decision:
        origin = "理论查询命中：" + ", ".join(sorted(theory_hit)) if theory_hit else "WoS-only 理论补充"
        return "theory", [origin, f"超载信号：{', '.join(overload[:3])}", f"消费者决策：{', '.join(decision[:3])}"]
    if direct_hit and not context:
        return "excluded", [f"直接查询命中但正文未显示直播电商情境：{', '.join(sorted(direct_hit))}"]
    return "excluded", ["未同时满足直播电商直接相关或消费者信息超载理论补充条件"]


def focus_records(records: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    core, theory, excluded = [], [], []
    excluded_reasons = Counter()
    for raw in records:
        record = deepcopy(raw)
        classification, reasons = classify_record(record)
        record["focus_screening"] = {"profile": "livestream-commerce", "classification": classification, "reasons": reasons}
        if classification == "core":
            record["inclusion"] = {"status": "included_core", "reasons": reasons}; core.append(record)
        elif classification == "theory":
            record["inclusion"] = {"status": "supplementary_theory", "reasons": reasons}; theory.append(record)
        else:
            record["inclusion"] = {"status": "excluded_focus", "reasons": reasons}; excluded.append(record)
            excluded_reasons[reasons[0] if reasons else "未说明"] += 1
    report = {
        "profile": "livestream-commerce", "input_records": len(records), "core_records": len(core), "theory_pool_records": len(theory), "excluded_records": len(excluded),
        "direct_query_ids": sorted(DIRECT_QUERY_IDS), "theory_query_ids": sorted(THEORY_QUERY_IDS), "excluded_reason_counts": dict(excluded_reasons),
    }
    return core, theory, excluded, report
