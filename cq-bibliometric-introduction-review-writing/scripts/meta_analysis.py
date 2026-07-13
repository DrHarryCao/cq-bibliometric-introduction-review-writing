#!/usr/bin/env python3
"""Conditionally run auditable random-effects synthesis; never invent effect sizes."""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scipy.optimize import minimize_scalar
from scipy.stats import linregress, norm

from common import load_jsonl, read_json, write_json, write_jsonl


SUPPORTED = {"r", "hedges-g", "or", "rr"}


def prepare(root: Path) -> dict[str, Any]:
    base = root / "05_evidence/meta"; base.mkdir(parents=True, exist_ok=True)
    corpus = load_jsonl(root / "02_corpus/corpus.jsonl"); targets = {x.get("record_id") for x in load_jsonl(root / "05_evidence/citation_coverage_targets.jsonl")}
    records = [r for r in corpus if not targets or r.get("record_id") in targets]
    path = base / "effect_sizes.jsonl"
    if not path.exists():
        write_jsonl(path, [{"effect_id": f"E{i:04d}", "record_id": r["record_id"], "sample_id": "", "outcome": "", "metric": "", "estimate": None, "standard_error": None, "ci_low": None, "ci_high": None, "n": None, "subgroup": "", "numeric_moderator": None, "anchor": "", "extraction_status": "pending", "notes": "Host fills only explicitly reported or transparently convertible effects."} for i, r in enumerate(records, 1)])
    report = {"phase": "prepare", "status": "prepared", "candidate_records": len(records), "effect_file": str(path), "rule": "no conversion when metric, variance, outcome or sample independence is ambiguous"}
    write_json(base / "meta_prepare_report.json", report); return report


def _working(row: dict[str, Any]) -> tuple[float, float, str]:
    metric = str(row.get("metric") or "").lower(); estimate = float(row["estimate"]); se = row.get("standard_error")
    if se in (None, "") and row.get("ci_low") not in (None, "") and row.get("ci_high") not in (None, ""):
        se = (float(row["ci_high"]) - float(row["ci_low"])) / (2 * 1.95996398454)
    if metric == "r":
        if not -1 < estimate < 1: raise ValueError("correlation must be between -1 and 1")
        value = np.arctanh(estimate); se = float(se) if se not in (None, "") else 1 / math.sqrt(float(row["n"]) - 3)
    elif metric in {"or", "rr"}:
        if estimate <= 0: raise ValueError(f"{metric} must be positive")
        value = math.log(estimate); se = float(se) if se not in (None, "") else None
    else: value = estimate; se = float(se) if se not in (None, "") else None
    if not se or se <= 0: raise ValueError("positive standard_error or convertible CI/n is required")
    return float(value), float(se), metric


def _back(value: float, metric: str) -> float:
    return float(np.tanh(value)) if metric == "r" else math.exp(value) if metric in {"or", "rr"} else value


def _reml(y: np.ndarray, variance: np.ndarray) -> float:
    def objective(tau2: float) -> float:
        weights = 1 / (variance + tau2); mean = np.sum(weights * y) / np.sum(weights)
        return .5 * (np.sum(np.log(variance + tau2)) + math.log(np.sum(weights)) + np.sum(weights * (y - mean) ** 2))
    upper = max(float(np.var(y) * 10), .01); result = minimize_scalar(objective, bounds=(0, upper), method="bounded")
    return max(0.0, float(result.x))


def _pool(frame: pd.DataFrame) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    y = frame["working"].to_numpy(float); variance = np.square(frame["se"].to_numpy(float)); metric = str(frame.iloc[0]["metric"]); k = len(frame)
    tau2 = _reml(y, variance); weights = 1 / (variance + tau2); pooled = float(np.sum(weights * y) / np.sum(weights)); pooled_se = math.sqrt(1 / np.sum(weights)); z = 1.95996398454
    fixed_w = 1 / variance; fixed = np.sum(fixed_w * y) / np.sum(fixed_w); q = float(np.sum(fixed_w * (y - fixed) ** 2)); i2 = max(0.0, (q - (k - 1)) / q * 100) if q else 0.0
    prediction_se = math.sqrt(tau2 + pooled_se ** 2)
    summary = {"outcome": frame.iloc[0]["outcome"], "metric": metric, "independent_studies": k, "model": "random-effects-REML", "pooled": _back(pooled, metric), "ci_low": _back(pooled - z * pooled_se, metric), "ci_high": _back(pooled + z * pooled_se, metric), "prediction_low": _back(pooled - z * prediction_se, metric), "prediction_high": _back(pooled + z * prediction_se, metric), "tau2_working_scale": tau2, "Q": q, "I2_percent": i2, "publication_bias_status": "skipped-fewer-than-10-studies"}
    if k >= 10:
        precision = 1 / frame["se"].to_numpy(float)
        standard_normal = y / frame["se"].to_numpy(float)
        if np.ptp(precision) > 1e-12:
            egger = linregress(precision, standard_normal)
            summary.update({"publication_bias_status": "exploratory-egger", "egger_intercept": float(egger.intercept), "egger_p": float(egger.intercept_stderr and 2 * norm.sf(abs(egger.intercept / egger.intercept_stderr))) if egger.intercept_stderr else None, "publication_bias_warning": "Egger检验只是小样本效应的探索性信号，不能单独证明发表偏倚。"})
        else:
            summary["publication_bias_status"] = "skipped-no-standard-error-variation"
    influence = []
    for index in range(k):
        keep = np.arange(k) != index; local_w = 1 / (variance[keep] + tau2); local = float(np.sum(local_w * y[keep]) / np.sum(local_w))
        influence.append({"omitted_effect_id": frame.iloc[index]["effect_id"], "pooled_without": _back(local, metric), "absolute_change_working_scale": abs(local - pooled)})
    return summary, influence


def compile_meta(root: Path) -> dict[str, Any]:
    base = root / "05_evidence/meta"; source = base / "effect_sizes.jsonl"
    if not source.exists(): prepare(root)
    raw = [x for x in load_jsonl(source) if x.get("extraction_status") == "completed"]
    valid, rejected = [], []
    for row in raw:
        try:
            metric = str(row.get("metric") or "").lower()
            if metric not in SUPPORTED: raise ValueError(f"unsupported metric: {metric}")
            if not row.get("outcome") or not row.get("sample_id") or not row.get("anchor"): raise ValueError("outcome, sample_id and anchor are required")
            value, se, metric = _working(row); valid.append({**row, "metric": metric, "working": value, "se": se})
        except Exception as exc: rejected.append({"effect_id": row.get("effect_id"), "reason": str(exc)})
    frame = pd.DataFrame(valid); summaries, influence, duplicate_samples, subgroups, meta_regressions = [], [], [], [], []
    if not frame.empty:
        for (outcome, metric), group in frame.groupby(["outcome", "metric"]):
            duplicate = group[group.duplicated("sample_id", keep=False)]
            if not duplicate.empty: duplicate_samples.extend(duplicate[["effect_id", "sample_id", "outcome", "metric"]].to_dict("records"))
            independent = group.sort_values("effect_id").drop_duplicates("sample_id", keep="first")
            if len(independent) < 3:
                summaries.append({"outcome": outcome, "metric": metric, "independent_studies": len(independent), "status": "skipped-insufficient-data", "reason": "requires at least 3 independent studies"}); continue
            summary, local = _pool(independent); summary["status"] = "ready"; summaries.append(summary)
            influence.extend({"outcome": outcome, "metric": metric, **x} for x in local)
            if "subgroup" in independent and independent["subgroup"].fillna("").astype(str).str.strip().ne("").any():
                eligible = [(name, part) for name, part in independent.groupby("subgroup") if str(name).strip() and len(part) >= 3]
                if len(eligible) >= 2:
                    for name, part in eligible:
                        local_summary, _ = _pool(part)
                        subgroups.append({"outcome": outcome, "metric": metric, "subgroup": name, **local_summary})
            if len(independent) >= 10 and "numeric_moderator" in independent:
                local = independent.dropna(subset=["numeric_moderator"])
                if len(local) >= 10 and local["numeric_moderator"].nunique() >= 3:
                    x = local["numeric_moderator"].astype(float).to_numpy(); y = local["working"].to_numpy(float); w = 1 / np.square(local["se"].to_numpy(float))
                    design = np.column_stack([np.ones(len(x)), x]); covariance = np.linalg.inv(design.T @ (w[:, None] * design)); beta = covariance @ design.T @ (w * y); se_beta = math.sqrt(float(covariance[1, 1]))
                    meta_regressions.append({"outcome": outcome, "metric": metric, "studies": len(local), "slope_working_scale": float(beta[1]), "standard_error": se_beta, "p": float(2 * norm.sf(abs(beta[1] / se_beta))) if se_beta else None, "status": "exploratory"})
    pd.DataFrame(summaries).to_csv(base / "meta_summary.csv", index=False, encoding="utf-8-sig"); pd.DataFrame(influence).to_csv(base / "meta_influence.csv", index=False, encoding="utf-8-sig"); pd.DataFrame(rejected).to_csv(base / "meta_rejected.csv", index=False, encoding="utf-8-sig")
    status = "ready" if any(x.get("status") == "ready" for x in summaries) else "skipped-insufficient-data"
    pd.DataFrame(subgroups).to_csv(base / "meta_subgroups.csv", index=False, encoding="utf-8-sig"); pd.DataFrame(meta_regressions).to_csv(base / "meta_regression.csv", index=False, encoding="utf-8-sig")
    report = {"phase": "compile", "status": status, "completed_effects": len(raw), "valid_effects": len(valid), "rejected": rejected, "duplicate_sample_effects": duplicate_samples, "syntheses": summaries, "subgroups": subgroups, "meta_regressions": meta_regressions, "fallback": "structured-narrative-synthesis" if status != "ready" else "not-needed"}
    write_json(base / "meta_compile_report.json", report); return report


def validate_meta(root: Path) -> dict[str, Any]:
    report = read_json(root / "05_evidence/meta/meta_compile_report.json", {}) or compile_meta(root); corpus = {x.get("record_id") for x in load_jsonl(root / "02_corpus/corpus.jsonl")}
    errors, warnings = [], []
    for row in load_jsonl(root / "05_evidence/meta/effect_sizes.jsonl"):
        if row.get("extraction_status") != "completed": continue
        if row.get("record_id") not in corpus: errors.append(f"{row.get('effect_id')} unknown record_id")
        if not row.get("anchor"): errors.append(f"{row.get('effect_id')} missing anchor")
    if report.get("duplicate_sample_effects"): warnings.append("同一sample_id的多个效应未被重复计数；默认仅保留首个可审计效应")
    if report.get("status") != "ready": warnings.append("数据不足以进行稳健定量合并，已回退结构化叙事综合")
    result = {"phase": "validate", "status": report.get("status", "skipped-insufficient-data"), "valid": not errors, "errors": errors, "warnings": warnings}
    write_json(root / "07_logs/meta_validation.json", result); return result
