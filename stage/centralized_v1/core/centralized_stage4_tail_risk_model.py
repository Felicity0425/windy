"""Tail-risk report-only analysis for Stage4 point departures."""

from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path
from typing import Any, Callable

import numpy as np


DEFAULT_POINT_DEPARTURES = Path(
    "/data/LFT-W02_data/pengxu/centralized_v1_output/"
    "stage4_guardrail_display_fill_200_20260605_25w/"
    "tp26_thr11_preserve_metrics/stage4_point_departures.csv"
)
DEFAULT_OUT_DIR = Path(
    "/data/LFT-W02_data/pengxu/centralized_v1_output/"
    "stage4_tail_risk_confidence_v2_20260608/tail_risk_report"
)
HIGH_ERROR_THRESHOLD_MPS = 30.0


def _read_csv(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        return [dict(row) for row in csv.DictReader(f)]


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _to_float(row: dict[str, Any], key: str, default: float = 0.0) -> float:
    try:
        value = float(row.get(key, default))
    except (TypeError, ValueError):
        return default
    return value if math.isfinite(value) else default


def _to_int(row: dict[str, Any], key: str, default: int = 0) -> int:
    try:
        return int(float(row.get(key, default)))
    except (TypeError, ValueError):
        return default


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"true", "1", "yes", "y"}


def _clip(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, value))


def _safe_div(num: float, den: float) -> float:
    return num / den if den else float("nan")


def _finite_array(values: list[float]) -> np.ndarray:
    arr = np.asarray(values, dtype=np.float64)
    return arr[np.isfinite(arr)]


def _mean(values: list[float]) -> float:
    arr = _finite_array(values)
    return float(np.mean(arr)) if arr.size else float("nan")


def _percentile(values: list[float], q: float) -> float:
    arr = _finite_array(values)
    return float(np.percentile(arr, q)) if arr.size else float("nan")


def _rmse_rows(rows: list[dict[str, Any]]) -> float:
    values = [_to_float(row, "vector_error", float("nan")) for row in rows]
    arr = _finite_array(values)
    return float(np.sqrt(np.mean(arr**2))) if arr.size else float("nan")


def _mae_rows(rows: list[dict[str, Any]]) -> float:
    values = [_to_float(row, "vector_error", float("nan")) for row in rows]
    arr = _finite_array(values)
    return float(np.mean(arr)) if arr.size else float("nan")


def _fmt(value: Any, digits: int = 6) -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if not math.isfinite(number):
        return ""
    return f"{number:.{digits}f}"


def _distance_bin(distance: float) -> str:
    if distance <= 2.0:
        return "le_2vox"
    if distance <= 4.0:
        return "2_to_4vox"
    return "gt_4vox"


def _role_gap_bin(role_gap: float) -> str:
    if role_gap < 20.0:
        return "lt_20mps"
    if role_gap < 30.0:
        return "20_to_30mps"
    return "ge_30mps"


def _recon_conf_bin(confidence: float) -> str:
    if confidence < 0.05:
        return "lt_0p05"
    if confidence < 0.2:
        return "0p05_to_0p2"
    return "ge_0p2"


def _adaptive_support_bin(value: int) -> str:
    if value <= 0:
        return "0"
    if value < 10:
        return "1_to_9"
    if value < 100:
        return "10_to_99"
    return "100_plus"


def _neighbor_error_bin(value: float) -> str:
    if value < 5.0:
        return "lt_5mps"
    if value < 15.0:
        return "5_to_15mps"
    return "ge_15mps"


def _represent_gap_bin(value: float) -> str:
    if value < 2.0:
        return "lt_2mps"
    if value < 10.0:
        return "2_to_10mps"
    return "ge_10mps"


def _score_bin(score: float) -> str:
    if score < 0.25:
        return "lt_0p25"
    if score < 0.45:
        return "0p25_to_0p45"
    if score < 0.65:
        return "0p45_to_0p65"
    return "ge_0p65"


def _risk_components(row: dict[str, Any]) -> tuple[dict[str, float], dict[str, bool]]:
    gt_speed = _to_float(row, "gt_speed")
    pred_speed = _to_float(row, "pred_speed")
    distance = _to_float(row, "nearest_train_distance_vox")
    role_gap = _to_float(row, "nearest_role_gap_mps")
    recon_conf = _to_float(row, "recon_confidence")
    current_count = _to_int(row, "nearest_current_count")
    context_count = _to_int(row, "nearest_context_count")
    vertical_gap = _to_float(row, "vertical_speed_gap_mps")
    vertical_jump = _to_float(row, "recon_vertical_jump_mps")
    neighbor_error = _to_float(row, "point_neighbor_mean_vector_error")
    represent_gap = _to_float(row, "representativeness_gap_point_minus_min_mps")
    role_conflict_component_gap = _to_float(row, "role_conflict_component_gap_at_point_mps")
    nearest_source_role = str(row.get("nearest_train_source_role", ""))
    qc_review_flag = _as_bool(row.get("qc_review_flag", False))
    role_conflict_at_point = _as_bool(row.get("role_conflict_at_point", False))

    context_only_nearest_support = nearest_source_role == "context_wind" and current_count <= 0
    strong_wind_vertically_isolated_candidate = (
        max(gt_speed, pred_speed) >= 30.0 and max(vertical_gap, vertical_jump) >= 10.0
    )

    components = {
        "qc_review": 1.0 if qc_review_flag else 0.0,
        "distance": _clip((distance - 2.0) / 4.0),
        "role_gap": _clip((role_gap - 15.0) / 25.0),
        "low_confidence": _clip((0.2 - recon_conf) / 0.2),
        "context_only_support": 1.0 if context_only_nearest_support else 0.0,
        "vertical_isolation": _clip((max(vertical_gap, vertical_jump) - 5.0) / 20.0)
        * _clip((max(gt_speed, pred_speed) - 25.0) / 35.0),
        "role_conflict": 1.0 if role_conflict_at_point else _clip((role_conflict_component_gap - 15.0) / 25.0),
        "neighbor_error": _clip((neighbor_error - 8.0) / 20.0),
        "support_count": 1.0 if current_count <= 0 and context_count <= 1 else (0.6 if current_count <= 0 else 0.0),
        "representativeness": _clip((represent_gap - 2.0) / 10.0),
    }
    hard_flags = {
        "qc_review_flag": qc_review_flag,
        "remote_support": distance > 4.0,
        "role_gap_ge30": role_gap >= 30.0,
        "low_recon_confidence": recon_conf < 0.05,
        "context_only_nearest_support": context_only_nearest_support,
        "strong_wind_vertically_isolated_candidate": strong_wind_vertically_isolated_candidate,
        "role_conflict_at_point": role_conflict_at_point,
    }
    return components, hard_flags


def _tail_risk_score(components: dict[str, float]) -> float:
    weights = {
        "qc_review": 0.22,
        "distance": 0.14,
        "role_gap": 0.14,
        "low_confidence": 0.12,
        "context_only_support": 0.10,
        "vertical_isolation": 0.10,
        "role_conflict": 0.08,
        "neighbor_error": 0.05,
        "support_count": 0.03,
        "representativeness": 0.02,
    }
    return float(sum(weights[key] * components[key] for key in weights))


def _enrich_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    enriched_rows: list[dict[str, Any]] = []
    for row in rows:
        components, hard_flags = _risk_components(row)
        score = _tail_risk_score(components)
        enriched = dict(row)
        enriched["vector_error"] = _to_float(row, "vector_error")
        enriched["gt_speed_mps"] = _to_float(row, "gt_speed")
        enriched["pred_speed_mps"] = _to_float(row, "pred_speed")
        enriched["high_vector_error_ge30mps"] = enriched["vector_error"] >= HIGH_ERROR_THRESHOLD_MPS
        enriched["nearest_distance_bin"] = _distance_bin(_to_float(row, "nearest_train_distance_vox"))
        enriched["nearest_role_gap_bin"] = _role_gap_bin(_to_float(row, "nearest_role_gap_mps"))
        enriched["recon_confidence_bin"] = _recon_conf_bin(_to_float(row, "recon_confidence"))
        enriched["adaptive_current_support_bin"] = _adaptive_support_bin(_to_int(row, "adaptive_current_support"))
        enriched["adaptive_context_support_bin"] = _adaptive_support_bin(_to_int(row, "adaptive_context_support"))
        enriched["point_neighbor_mean_vector_error_bin"] = _neighbor_error_bin(
            _to_float(row, "point_neighbor_mean_vector_error")
        )
        enriched["representativeness_gap_bin"] = _represent_gap_bin(
            _to_float(row, "representativeness_gap_point_minus_min_mps")
        )
        enriched["tail_risk_score"] = score
        enriched["tail_risk_score_bin"] = _score_bin(score)
        enriched["tail_risk_baseline_flag"] = any(
            hard_flags[key]
            for key in (
                "qc_review_flag",
                "remote_support",
                "role_gap_ge30",
                "low_recon_confidence",
                "context_only_nearest_support",
                "strong_wind_vertically_isolated_candidate",
            )
        )
        for key, value in components.items():
            enriched[f"tail_risk_component_{key}"] = value
        for key, value in hard_flags.items():
            enriched[f"tail_risk_flag_{key}"] = value
        reasons = [key for key, value in hard_flags.items() if value]
        enriched["tail_risk_reason_codes"] = ";".join(reasons)
        enriched_rows.append(enriched)
    return enriched_rows


def _rule_metrics(
    rows: list[dict[str, Any]],
    rule_name: str,
    description: str,
    predicate: Callable[[dict[str, Any]], bool],
    p95_threshold: float,
    p99_threshold: float,
) -> dict[str, Any]:
    flagged = [row for row in rows if predicate(row)]
    unflagged = [row for row in rows if not predicate(row)]
    total_high = sum(1 for row in rows if _as_bool(row.get("high_vector_error_ge30mps")))
    total_p95 = sum(1 for row in rows if _to_float(row, "vector_error") >= p95_threshold)
    total_p99 = sum(1 for row in rows if _to_float(row, "vector_error") >= p99_threshold)
    flagged_high = sum(1 for row in flagged if _as_bool(row.get("high_vector_error_ge30mps")))
    flagged_p95 = sum(1 for row in flagged if _to_float(row, "vector_error") >= p95_threshold)
    flagged_p99 = sum(1 for row in flagged if _to_float(row, "vector_error") >= p99_threshold)
    total_sse = sum(_to_float(row, "vector_error") ** 2 for row in rows)
    flagged_sse = sum(_to_float(row, "vector_error") ** 2 for row in flagged)
    return {
        "rule_name": rule_name,
        "rule_description": description,
        "flagged_points": len(flagged),
        "flagged_fraction": _safe_div(len(flagged), len(rows)),
        "flagged_error_rmse": _rmse_rows(flagged),
        "flagged_error_mae": _mae_rows(flagged),
        "unflagged_points": len(unflagged),
        "unflagged_fraction": _safe_div(len(unflagged), len(rows)),
        "unflagged_error_rmse": _rmse_rows(unflagged),
        "unflagged_error_mae": _mae_rows(unflagged),
        "high_error_ge30_count": flagged_high,
        "high_error_ge30_recall": _safe_div(flagged_high, total_high),
        "high_error_ge30_precision": _safe_div(flagged_high, len(flagged)),
        "p95_tail_recall": _safe_div(flagged_p95, total_p95),
        "p99_tail_recall": _safe_div(flagged_p99, total_p99),
        "sse_share_captured": _safe_div(flagged_sse, total_sse),
        "mean_tail_risk_score_flagged": _mean([_to_float(row, "tail_risk_score") for row in flagged]),
        "mean_tail_risk_score_unflagged": _mean([_to_float(row, "tail_risk_score") for row in unflagged]),
    }


def _feature_summary_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    total_high = sum(1 for row in rows if _as_bool(row.get("high_vector_error_ge30mps")))
    total_sse = sum(_to_float(row, "vector_error") ** 2 for row in rows)
    overall_high_error_rate = _safe_div(total_high, len(rows))
    feature_defs: list[tuple[str, Callable[[dict[str, Any]], str]]] = [
        ("qc_review_flag", lambda row: "true" if _as_bool(row.get("qc_review_flag")) else "false"),
        ("nearest_distance_bin", lambda row: str(row["nearest_distance_bin"])),
        ("nearest_train_source_role", lambda row: str(row.get("nearest_train_source_role", ""))),
        ("nearest_role_gap_bin", lambda row: str(row["nearest_role_gap_bin"])),
        ("recon_confidence_bin", lambda row: str(row["recon_confidence_bin"])),
        (
            "context_only_nearest_support",
            lambda row: "true" if _as_bool(row.get("tail_risk_flag_context_only_nearest_support")) else "false",
        ),
        (
            "strong_wind_vertically_isolated_candidate",
            lambda row: "true"
            if _as_bool(row.get("tail_risk_flag_strong_wind_vertically_isolated_candidate"))
            else "false",
        ),
        ("role_conflict_at_point", lambda row: "true" if _as_bool(row.get("role_conflict_at_point")) else "false"),
        ("adaptive_current_support_bin", lambda row: str(row["adaptive_current_support_bin"])),
        ("adaptive_context_support_bin", lambda row: str(row["adaptive_context_support_bin"])),
        ("point_neighbor_mean_vector_error_bin", lambda row: str(row["point_neighbor_mean_vector_error_bin"])),
        ("representativeness_gap_bin", lambda row: str(row["representativeness_gap_bin"])),
        ("tail_risk_score_bin", lambda row: str(row["tail_risk_score_bin"])),
    ]

    summary_rows: list[dict[str, Any]] = []
    for feature_name, labeler in feature_defs:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            grouped.setdefault(labeler(row), []).append(row)
        for bucket, bucket_rows in sorted(grouped.items()):
            high_count = sum(1 for row in bucket_rows if _as_bool(row.get("high_vector_error_ge30mps")))
            sse = sum(_to_float(row, "vector_error") ** 2 for row in bucket_rows)
            high_error_rate = _safe_div(high_count, len(bucket_rows))
            summary_rows.append(
                {
                    "feature": feature_name,
                    "bucket": bucket,
                    "points": len(bucket_rows),
                    "points_fraction": _safe_div(len(bucket_rows), len(rows)),
                    "vector_rmse_mps": _rmse_rows(bucket_rows),
                    "vector_mae_mps": _mae_rows(bucket_rows),
                    "p95_vector_error_mps": _percentile(
                        [_to_float(row, "vector_error", float("nan")) for row in bucket_rows], 95.0
                    ),
                    "p99_vector_error_mps": _percentile(
                        [_to_float(row, "vector_error", float("nan")) for row in bucket_rows], 99.0
                    ),
                    "high_error_ge30_count": high_count,
                    "high_error_ge30_rate": high_error_rate,
                    "high_error_ge30_recall": _safe_div(high_count, total_high),
                    "high_error_rate_lift": _safe_div(high_error_rate, overall_high_error_rate),
                    "sse_share": _safe_div(sse, total_sse),
                    "mean_tail_risk_score": _mean([_to_float(row, "tail_risk_score") for row in bucket_rows]),
                    "baseline_rule_flag_rate": _safe_div(
                        sum(1 for row in bucket_rows if _as_bool(row.get("tail_risk_baseline_flag"))),
                        len(bucket_rows),
                    ),
                }
            )
    return sorted(
        summary_rows,
        key=lambda row: (
            -_to_float(row, "high_error_rate_lift"),
            -_to_float(row, "high_error_ge30_rate"),
            -_to_int(row, "high_error_ge30_count"),
            -_to_float(row, "sse_share"),
            str(row["feature"]),
            str(row["bucket"]),
        ),
    )


def _top_points(rows: list[dict[str, Any]], top_n: int) -> list[dict[str, Any]]:
    by_error = sorted(rows, key=lambda row: (_to_float(row, "vector_error"), _to_float(row, "tail_risk_score")), reverse=True)
    by_score = sorted(rows, key=lambda row: (_to_float(row, "tail_risk_score"), _to_float(row, "vector_error")), reverse=True)
    error_rank = {
        (str(row.get("time_str", "")), _to_int(row, "z"), _to_int(row, "y"), _to_int(row, "x")): idx
        for idx, row in enumerate(by_error, start=1)
    }
    score_rank = {
        (str(row.get("time_str", "")), _to_int(row, "z"), _to_int(row, "y"), _to_int(row, "x")): idx
        for idx, row in enumerate(by_score, start=1)
    }

    out: list[dict[str, Any]] = []
    for row in by_error[:top_n]:
        key = (str(row.get("time_str", "")), _to_int(row, "z"), _to_int(row, "y"), _to_int(row, "x"))
        out.append(
            {
                "error_rank": error_rank[key],
                "score_rank": score_rank[key],
                "time_str": row.get("time_str", ""),
                "z": _to_int(row, "z"),
                "y": _to_int(row, "y"),
                "x": _to_int(row, "x"),
                "alt_m": _to_float(row, "alt_m"),
                "gt_speed_mps": _to_float(row, "gt_speed_mps"),
                "pred_speed_mps": _to_float(row, "pred_speed_mps"),
                "vector_error_mps": _to_float(row, "vector_error"),
                "tail_risk_score": _to_float(row, "tail_risk_score"),
                "tail_risk_baseline_flag": _as_bool(row.get("tail_risk_baseline_flag")),
                "high_vector_error_ge30mps": _as_bool(row.get("high_vector_error_ge30mps")),
                "qc_review_flag": _as_bool(row.get("qc_review_flag")),
                "qc_review_reasons": row.get("qc_review_reasons", ""),
                "tail_risk_reason_codes": row.get("tail_risk_reason_codes", ""),
                "nearest_train_distance_vox": _to_float(row, "nearest_train_distance_vox"),
                "nearest_train_source_role": row.get("nearest_train_source_role", ""),
                "nearest_current_count": _to_int(row, "nearest_current_count"),
                "nearest_context_count": _to_int(row, "nearest_context_count"),
                "nearest_role_gap_mps": _to_float(row, "nearest_role_gap_mps"),
                "recon_confidence": _to_float(row, "recon_confidence"),
                "recon_vertical_jump_mps": _to_float(row, "recon_vertical_jump_mps"),
                "vertical_speed_gap_mps": _to_float(row, "vertical_speed_gap_mps"),
                "point_neighbor_mean_vector_error": _to_float(row, "point_neighbor_mean_vector_error"),
                "representativeness_gap_point_minus_min_mps": _to_float(
                    row, "representativeness_gap_point_minus_min_mps"
                ),
                "tail_risk_component_qc_review": _to_float(row, "tail_risk_component_qc_review"),
                "tail_risk_component_distance": _to_float(row, "tail_risk_component_distance"),
                "tail_risk_component_role_gap": _to_float(row, "tail_risk_component_role_gap"),
                "tail_risk_component_low_confidence": _to_float(row, "tail_risk_component_low_confidence"),
                "tail_risk_component_context_only_support": _to_float(
                    row, "tail_risk_component_context_only_support"
                ),
                "tail_risk_component_vertical_isolation": _to_float(row, "tail_risk_component_vertical_isolation"),
                "tail_risk_component_role_conflict": _to_float(row, "tail_risk_component_role_conflict"),
            }
        )
    return out


def _write_feature_md(
    path: Path,
    rows: list[dict[str, Any]],
    rule_rows: list[dict[str, Any]],
    feature_rows: list[dict[str, Any]],
    top_rows: list[dict[str, Any]],
) -> None:
    overall_rmse = _rmse_rows(rows)
    overall_mae = _mae_rows(rows)
    overall_p95 = _percentile([_to_float(row, "vector_error", float("nan")) for row in rows], 95.0)
    overall_p99 = _percentile([_to_float(row, "vector_error", float("nan")) for row in rows], 99.0)
    high_error_count = sum(1 for row in rows if _as_bool(row.get("high_vector_error_ge30mps")))
    lines = [
        "# Stage4 Tail-Risk Report",
        "",
        "This is report-only analysis on strict holdout point departures. It does not change `recon_u/v` or official RMSE/MAE.",
        "",
        "## Overall",
        "",
        "| points | RMSE | MAE | P95 | P99 | high-error >=30 m/s |",
        "| ---: | ---: | ---: | ---: | ---: | ---: |",
        f"| {len(rows)} | {_fmt(overall_rmse)} | {_fmt(overall_mae)} | {_fmt(overall_p95)} | {_fmt(overall_p99)} | {high_error_count} |",
        "",
        "## Baseline Tail-Risk Rule",
        "",
        "Baseline rule:",
        "",
        "```text",
        "qc_review_flag",
        "OR nearest_train_distance_vox > 4",
        "OR nearest_role_gap_mps >= 30",
        "OR recon_confidence < 0.05",
        "OR context_only_nearest_support",
        "OR strong_wind_vertically_isolated_candidate",
        "```",
        "",
        "| rule | flagged | high-error recall | high-error precision | unflagged RMSE | SSE share captured | P95 recall | P99 recall |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in rule_rows[:7]:
        lines.append(
            f"| `{row['rule_name']}` | {row['flagged_points']} | {_fmt(row['high_error_ge30_recall'])} | "
            f"{_fmt(row['high_error_ge30_precision'])} | {_fmt(row['unflagged_error_rmse'])} | "
            f"{_fmt(row['sse_share_captured'])} | {_fmt(row['p95_tail_recall'])} | {_fmt(row['p99_tail_recall'])} |"
        )

    lines.extend(
        [
            "",
        "## Highest-Risk Feature Buckets",
        "",
        "| feature | bucket | points | high-error count | high-error rate | rate lift | high-error recall | RMSE | SSE share | mean score |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    shown = 0
    for row in feature_rows:
        if _to_int(row, "points") >= len(rows):
            continue
        if _to_int(row, "high_error_ge30_count") <= 0 and _to_float(row, "sse_share") < 0.05:
            continue
        lines.append(
            f"| `{row['feature']}` | `{row['bucket']}` | {row['points']} | {row['high_error_ge30_count']} | "
            f"{_fmt(row['high_error_ge30_rate'])} | {_fmt(row['high_error_rate_lift'])} | {_fmt(row['high_error_ge30_recall'])} | "
            f"{_fmt(row['vector_rmse_mps'])} | {_fmt(row['sse_share'])} | {_fmt(row['mean_tail_risk_score'])} |"
        )
        shown += 1
        if shown >= 18:
            break

    lines.extend(
        [
            "",
            "## Top Tail Points",
            "",
            "| rank | frame | z/y/x | alt_m | gt_speed | error | score | nearest role | dist | role gap | conf | reasons |",
            "| ---: | --- | --- | ---: | ---: | ---: | ---: | --- | ---: | ---: | ---: | --- |",
        ]
    )
    for row in top_rows[:12]:
        lines.append(
            f"| {row['error_rank']} | `{row['time_str']}` | `{row['z']}/{row['y']}/{row['x']}` | "
            f"{_fmt(row['alt_m'], 1)} | {_fmt(row['gt_speed_mps'])} | {_fmt(row['vector_error_mps'])} | "
            f"{_fmt(row['tail_risk_score'])} | `{row['nearest_train_source_role']}` | "
            f"{_fmt(row['nearest_train_distance_vox'])} | {_fmt(row['nearest_role_gap_mps'])} | "
            f"{_fmt(row['recon_confidence'])} | `{row['tail_risk_reason_codes']}` |"
        )

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build report-only Stage4 tail-risk diagnostics.")
    parser.add_argument("--point-departures", type=Path, default=DEFAULT_POINT_DEPARTURES)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--top-n", type=int, default=50)
    args = parser.parse_args()

    rows = _read_csv(args.point_departures)
    enriched_rows = _enrich_rows(rows)
    vector_errors = [_to_float(row, "vector_error", float("nan")) for row in enriched_rows]
    p95_threshold = _percentile(vector_errors, 95.0)
    p99_threshold = _percentile(vector_errors, 99.0)

    rule_defs: list[tuple[str, str, Callable[[dict[str, Any]], bool]]] = [
        (
            "qc_review_only",
            "qc_review_flag",
            lambda row: _as_bool(row.get("qc_review_flag")),
        ),
        (
            "baseline_rule_v1",
            "qc OR remote_support OR role_gap_ge30 OR recon_conf_lt_0p05 OR context_only OR strong_wind_vertical_isolation",
            lambda row: _as_bool(row.get("tail_risk_baseline_flag")),
        ),
        (
            "support_gap_only",
            "remote_support OR role_gap_ge30 OR recon_conf_lt_0p05 OR context_only",
            lambda row: _as_bool(row.get("tail_risk_flag_remote_support"))
            or _as_bool(row.get("tail_risk_flag_role_gap_ge30"))
            or _as_bool(row.get("tail_risk_flag_low_recon_confidence"))
            or _as_bool(row.get("tail_risk_flag_context_only_nearest_support")),
        ),
        (
            "baseline_plus_neighbor_tail",
            "baseline_rule_v1 OR point_neighbor_mean_vector_error >= 15 m/s",
            lambda row: _as_bool(row.get("tail_risk_baseline_flag"))
            or _to_float(row, "point_neighbor_mean_vector_error") >= 15.0,
        ),
        (
            "score_ge_0p35",
            "tail_risk_score >= 0.35",
            lambda row: _to_float(row, "tail_risk_score") >= 0.35,
        ),
        (
            "score_ge_0p45",
            "tail_risk_score >= 0.45",
            lambda row: _to_float(row, "tail_risk_score") >= 0.45,
        ),
        (
            "score_ge_0p55",
            "tail_risk_score >= 0.55",
            lambda row: _to_float(row, "tail_risk_score") >= 0.55,
        ),
        (
            "score_ge_0p35_or_neighbor_tail",
            "tail_risk_score >= 0.35 OR point_neighbor_mean_vector_error >= 15 m/s",
            lambda row: _to_float(row, "tail_risk_score") >= 0.35
            or _to_float(row, "point_neighbor_mean_vector_error") >= 15.0,
        ),
    ]

    rule_rows = [
        _rule_metrics(enriched_rows, rule_name, description, predicate, p95_threshold, p99_threshold)
        for rule_name, description, predicate in rule_defs
    ]
    feature_rows = _feature_summary_rows(enriched_rows)
    top_rows = _top_points(enriched_rows, args.top_n)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(args.out_dir / "tail_risk_feature_summary.csv", feature_rows)
    _write_csv(args.out_dir / "tail_risk_rule_candidates.csv", rule_rows)
    _write_csv(args.out_dir / "tail_risk_top_points.csv", top_rows)
    _write_feature_md(
        args.out_dir / "tail_risk_feature_summary.md",
        enriched_rows,
        rule_rows,
        feature_rows,
        top_rows,
    )

    overall_rmse = _rmse_rows(enriched_rows)
    baseline = next((row for row in rule_rows if row["rule_name"] == "baseline_rule_v1"), None)
    print(f"wrote: {args.out_dir}")
    print(f"overall_points={len(enriched_rows)} overall_rmse={overall_rmse:.6f}")
    if baseline is not None:
        print(
            "baseline_rule_v1 "
            f"flagged_points={baseline['flagged_points']} "
            f"high_error_recall={_fmt(baseline['high_error_ge30_recall'])} "
            f"unflagged_rmse={_fmt(baseline['unflagged_error_rmse'])}"
        )


if __name__ == "__main__":
    main()
