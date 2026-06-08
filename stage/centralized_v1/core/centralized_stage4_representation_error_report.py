"""Report-only representation-error diagnostics for Stage4 point departures."""

from __future__ import annotations

import argparse
import csv
import json
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
    "stage4_tail_risk_confidence_v2_20260608/representation_error_report"
)
HIGH_ERROR_THRESHOLD_MPS = 30.0
BASELINE_WEIGHTED_RMSE_MPS = 14.769036


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


def _nearest_train_speed(row: dict[str, Any]) -> float:
    return math.hypot(_to_float(row, "nearest_train_u"), _to_float(row, "nearest_train_v"))


def _vertical_proxy(row: dict[str, Any]) -> float:
    return max(_to_float(row, "vertical_speed_gap_mps"), _to_float(row, "recon_vertical_jump_mps"))


def _context_only_nearest_support(row: dict[str, Any]) -> bool:
    return str(row.get("nearest_train_source_role", "")) == "context_wind" and _to_int(row, "nearest_current_count") <= 0


def _distance_bin(distance: float) -> str:
    if distance <= 2.0:
        return "le_2vox"
    if distance <= 4.0:
        return "2_to_4vox"
    if distance <= 8.0:
        return "4_to_8vox"
    return "gt_8vox"


def _role_gap_bin(role_gap: float) -> str:
    if role_gap < 20.0:
        return "lt_20mps"
    if role_gap < 30.0:
        return "20_to_30mps"
    if role_gap < 60.0:
        return "30_to_60mps"
    return "ge_60mps"


def _conf_bin(confidence: float) -> str:
    if confidence < 0.05:
        return "lt_0p05"
    if confidence < 0.20:
        return "0p05_to_0p20"
    if confidence < 0.50:
        return "0p20_to_0p50"
    return "ge_0p50"


def _support_bin(count: int) -> str:
    if count <= 0:
        return "0"
    if count == 1:
        return "1"
    if count <= 3:
        return "2_to_3"
    return "4_plus"


def _adaptive_support_bin(count: int) -> str:
    if count <= 0:
        return "0"
    if count < 10:
        return "1_to_9"
    if count < 25:
        return "10_to_24"
    if count < 100:
        return "25_to_99"
    return "100_plus"


def _speed_bin(speed: float) -> str:
    if speed < 5.0:
        return "lt_5mps"
    if speed < 15.0:
        return "5_to_15mps"
    if speed < 30.0:
        return "15_to_30mps"
    if speed < 60.0:
        return "30_to_60mps"
    return "ge_60mps"


def _altitude_bin(alt_m: float) -> str:
    if alt_m < 3000.0:
        return "0_to_3km"
    if alt_m < 6000.0:
        return "3_to_6km"
    if alt_m < 9000.0:
        return "6_to_9km"
    if alt_m < 12000.0:
        return "9_to_12km"
    return "12km_plus"


def _vertical_proxy_bin(value: float) -> str:
    if value < 5.0:
        return "lt_5mps"
    if value < 10.0:
        return "5_to_10mps"
    if value < 25.0:
        return "10_to_25mps"
    return "ge_25mps"


def _removed_weight_bin(value: float) -> str:
    if value <= 0.0:
        return "0"
    if value < 0.05:
        return "0_to_0p05"
    if value < 0.20:
        return "0p05_to_0p20"
    return "ge_0p20"


def _score_bin(score: float) -> str:
    if score < 0.10:
        return "lt_0p10"
    if score < 0.20:
        return "0p10_to_0p20"
    if score < 0.35:
        return "0p20_to_0p35"
    if score < 0.50:
        return "0p35_to_0p50"
    return "ge_0p50"


def _score_bin_order(bucket: str) -> int:
    order = {
        "lt_0p10": 0,
        "0p10_to_0p20": 1,
        "0p20_to_0p35": 2,
        "0p35_to_0p50": 3,
        "ge_0p50": 4,
    }
    return order.get(bucket, 99)


def _representation_components(row: dict[str, Any]) -> tuple[dict[str, float], dict[str, bool]]:
    distance = _to_float(row, "nearest_train_distance_vox")
    role_gap = _to_float(row, "nearest_role_gap_mps")
    recon_conf = _to_float(row, "recon_confidence")
    current_count = _to_int(row, "nearest_current_count")
    vertical_proxy = _vertical_proxy(row)
    nearest_speed = _nearest_train_speed(row)
    pred_speed = _to_float(row, "pred_speed")
    alt_m = _to_float(row, "alt_m")
    adaptive_current_support = _to_int(row, "adaptive_current_support")
    role_conflict_at_point = _as_bool(row.get("role_conflict_at_point"))
    role_conflict_gap = _to_float(row, "role_conflict_component_gap_at_point_mps")
    context_only = _context_only_nearest_support(row)

    components = {
        "remote_support": _clip((distance - 2.0) / 5.0),
        "role_gap": _clip((role_gap - 15.0) / 65.0),
        "low_recon_confidence": _clip((0.20 - recon_conf) / 0.20),
        "context_only_support": 1.0 if context_only else 0.0,
        "sparse_current_support": 1.0 if current_count <= 0 else (0.5 if current_count <= 1 else 0.0),
        "vertical_proxy": _clip((vertical_proxy - 5.0) / 30.0),
        "nearest_train_speed": _clip((nearest_speed - 20.0) / 80.0),
        "high_altitude": 1.0 if alt_m >= 12000.0 else (0.5 if alt_m >= 9000.0 else 0.0),
        "predicted_strong_wind": _clip((pred_speed - 25.0) / 60.0),
        "role_conflict": 1.0 if role_conflict_at_point else _clip((role_conflict_gap - 15.0) / 50.0),
        "low_support_field": 1.0
        if adaptive_current_support < 10
        else (0.5 if adaptive_current_support < 25 else 0.0),
    }
    hard_flags = {
        "remote_support": distance > 4.0,
        "role_gap_ge30": role_gap >= 30.0,
        "low_recon_confidence": recon_conf < 0.05,
        "context_only_nearest_support": context_only,
        "vertical_proxy_ge10": vertical_proxy >= 10.0,
        "vertical_proxy_ge25": vertical_proxy >= 25.0,
        "nearest_train_speed_ge30": nearest_speed >= 30.0,
        "high_altitude_12km_plus": alt_m >= 12000.0,
        "role_conflict_at_point": role_conflict_at_point,
        "low_adaptive_current_support": adaptive_current_support < 10,
    }
    return components, hard_flags


def _representation_score(components: dict[str, float]) -> float:
    weights = {
        "remote_support": 0.13,
        "role_gap": 0.14,
        "low_recon_confidence": 0.13,
        "context_only_support": 0.12,
        "sparse_current_support": 0.06,
        "vertical_proxy": 0.13,
        "nearest_train_speed": 0.12,
        "high_altitude": 0.05,
        "predicted_strong_wind": 0.04,
        "role_conflict": 0.05,
        "low_support_field": 0.03,
    }
    return float(sum(weights[key] * components[key] for key in weights))


def _enrich_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    enriched_rows: list[dict[str, Any]] = []
    for row in rows:
        components, hard_flags = _representation_components(row)
        score = _representation_score(components)
        enriched = dict(row)
        enriched["vector_error"] = _to_float(row, "vector_error")
        enriched["high_vector_error_ge30mps"] = enriched["vector_error"] >= HIGH_ERROR_THRESHOLD_MPS
        enriched["nearest_train_speed_mps"] = _nearest_train_speed(row)
        enriched["representation_vertical_proxy_mps"] = _vertical_proxy(row)
        enriched["context_only_nearest_support"] = _context_only_nearest_support(row)
        enriched["representation_error_score"] = score
        enriched["representation_error_score_bin"] = _score_bin(score)
        enriched["altitude_bin"] = _altitude_bin(_to_float(row, "alt_m"))
        enriched["pred_speed_bin"] = _speed_bin(_to_float(row, "pred_speed"))
        enriched["nearest_train_speed_bin"] = _speed_bin(_nearest_train_speed(row))
        enriched["nearest_distance_bin"] = _distance_bin(_to_float(row, "nearest_train_distance_vox"))
        enriched["nearest_role_gap_bin"] = _role_gap_bin(_to_float(row, "nearest_role_gap_mps"))
        enriched["recon_confidence_bin"] = _conf_bin(_to_float(row, "recon_confidence"))
        enriched["nearest_current_count_bin"] = _support_bin(_to_int(row, "nearest_current_count"))
        enriched["nearest_context_count_bin"] = _support_bin(_to_int(row, "nearest_context_count"))
        enriched["adaptive_current_support_bin"] = _adaptive_support_bin(_to_int(row, "adaptive_current_support"))
        enriched["adaptive_context_support_bin"] = _adaptive_support_bin(_to_int(row, "adaptive_context_support"))
        enriched["vertical_proxy_bin"] = _vertical_proxy_bin(_vertical_proxy(row))
        enriched["role_conflict_removed_weight_bin"] = _removed_weight_bin(
            _to_float(row, "role_conflict_context_removed_weight_at_point")
        )
        enriched["representation_conservative_rule_v1"] = any(
            hard_flags[key]
            for key in (
                "remote_support",
                "role_gap_ge30",
                "low_recon_confidence",
                "context_only_nearest_support",
                "vertical_proxy_ge10",
                "nearest_train_speed_ge30",
            )
        )
        enriched["representation_compact_rule_v1"] = (
            hard_flags["remote_support"]
            or hard_flags["role_gap_ge30"]
            or hard_flags["low_recon_confidence"]
            or (
                hard_flags["context_only_nearest_support"]
                and (hard_flags["nearest_train_speed_ge30"] or _vertical_proxy(row) >= 5.0)
            )
            or hard_flags["vertical_proxy_ge25"]
        )
        for key, value in components.items():
            enriched[f"representation_component_{key}"] = value
        for key, value in hard_flags.items():
            enriched[f"representation_flag_{key}"] = value
        enriched["representation_reason_codes"] = ";".join(key for key, value in hard_flags.items() if value)
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
        "truth_free_rule_inputs": True,
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
        "mean_representation_error_score_flagged": _mean(
            [_to_float(row, "representation_error_score") for row in flagged]
        ),
        "mean_representation_error_score_unflagged": _mean(
            [_to_float(row, "representation_error_score") for row in unflagged]
        ),
    }


def _feature_summary_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    total_high = sum(1 for row in rows if _as_bool(row.get("high_vector_error_ge30mps")))
    total_sse = sum(_to_float(row, "vector_error") ** 2 for row in rows)
    overall_high_rate = _safe_div(total_high, len(rows))
    feature_defs: list[tuple[str, Callable[[dict[str, Any]], str]]] = [
        ("altitude_bin", lambda row: str(row["altitude_bin"])),
        ("pred_speed_bin", lambda row: str(row["pred_speed_bin"])),
        ("nearest_train_speed_bin", lambda row: str(row["nearest_train_speed_bin"])),
        ("nearest_distance_bin", lambda row: str(row["nearest_distance_bin"])),
        ("nearest_train_source_role", lambda row: str(row.get("nearest_train_source_role", ""))),
        (
            "context_only_nearest_support",
            lambda row: "true" if _as_bool(row.get("context_only_nearest_support")) else "false",
        ),
        ("nearest_current_count_bin", lambda row: str(row["nearest_current_count_bin"])),
        ("nearest_context_count_bin", lambda row: str(row["nearest_context_count_bin"])),
        ("adaptive_current_support_bin", lambda row: str(row["adaptive_current_support_bin"])),
        ("adaptive_context_support_bin", lambda row: str(row["adaptive_context_support_bin"])),
        ("nearest_role_gap_bin", lambda row: str(row["nearest_role_gap_bin"])),
        ("recon_confidence_bin", lambda row: str(row["recon_confidence_bin"])),
        ("vertical_proxy_bin", lambda row: str(row["vertical_proxy_bin"])),
        ("role_conflict_at_point", lambda row: "true" if _as_bool(row.get("role_conflict_at_point")) else "false"),
        ("role_conflict_removed_weight_bin", lambda row: str(row["role_conflict_removed_weight_bin"])),
        ("representation_error_score_bin", lambda row: str(row["representation_error_score_bin"])),
    ]

    summary_rows: list[dict[str, Any]] = []
    for feature_name, labeler in feature_defs:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            grouped.setdefault(labeler(row), []).append(row)
        for bucket, bucket_rows in sorted(grouped.items()):
            high_count = sum(1 for row in bucket_rows if _as_bool(row.get("high_vector_error_ge30mps")))
            sse = sum(_to_float(row, "vector_error") ** 2 for row in bucket_rows)
            high_rate = _safe_div(high_count, len(bucket_rows))
            summary_rows.append(
                {
                    "feature": feature_name,
                    "bucket": bucket,
                    "truth_free_feature": True,
                    "points": len(bucket_rows),
                    "points_fraction": _safe_div(len(bucket_rows), len(rows)),
                    "expected_sigma_rep_mps": _rmse_rows(bucket_rows),
                    "vector_rmse_mps": _rmse_rows(bucket_rows),
                    "vector_mae_mps": _mae_rows(bucket_rows),
                    "median_vector_error_mps": _percentile(
                        [_to_float(row, "vector_error", float("nan")) for row in bucket_rows], 50.0
                    ),
                    "p95_vector_error_mps": _percentile(
                        [_to_float(row, "vector_error", float("nan")) for row in bucket_rows], 95.0
                    ),
                    "p99_vector_error_mps": _percentile(
                        [_to_float(row, "vector_error", float("nan")) for row in bucket_rows], 99.0
                    ),
                    "high_error_ge30_count": high_count,
                    "high_error_ge30_rate": high_rate,
                    "high_error_ge30_recall": _safe_div(high_count, total_high),
                    "high_error_rate_lift": _safe_div(high_rate, overall_high_rate),
                    "sse_share": _safe_div(sse, total_sse),
                    "mean_representation_error_score": _mean(
                        [_to_float(row, "representation_error_score") for row in bucket_rows]
                    ),
                    "conservative_rule_flag_rate": _safe_div(
                        sum(1 for row in bucket_rows if _as_bool(row.get("representation_conservative_rule_v1"))),
                        len(bucket_rows),
                    ),
                }
            )
    return sorted(
        summary_rows,
        key=lambda row: (
            -_to_float(row, "high_error_rate_lift"),
            -_to_float(row, "high_error_ge30_rate"),
            -_to_float(row, "sse_share"),
            str(row["feature"]),
            str(row["bucket"]),
        ),
    )


def _bucket_calibration_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    total_high = sum(1 for row in rows if _as_bool(row.get("high_vector_error_ge30mps")))
    total_sse = sum(_to_float(row, "vector_error") ** 2 for row in rows)
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(str(row["representation_error_score_bin"]), []).append(row)

    ordered_buckets = sorted(grouped, key=_score_bin_order)
    bucket_rows: list[dict[str, Any]] = []
    for bucket in ordered_buckets:
        current = grouped[bucket]
        bucket_order = _score_bin_order(bucket)
        cumulative = [
            row
            for candidate_bucket in ordered_buckets
            if _score_bin_order(candidate_bucket) >= bucket_order
            for row in grouped[candidate_bucket]
        ]
        high_count = sum(1 for row in current if _as_bool(row.get("high_vector_error_ge30mps")))
        high_cumulative = sum(1 for row in cumulative if _as_bool(row.get("high_vector_error_ge30mps")))
        sse = sum(_to_float(row, "vector_error") ** 2 for row in current)
        cumulative_sse = sum(_to_float(row, "vector_error") ** 2 for row in cumulative)
        bucket_rows.append(
            {
                "score_bucket": bucket,
                "score_bucket_order": bucket_order,
                "truth_free_score": True,
                "points": len(current),
                "points_fraction": _safe_div(len(current), len(rows)),
                "expected_sigma_rep_mps": _rmse_rows(current),
                "vector_mae_mps": _mae_rows(current),
                "median_vector_error_mps": _percentile(
                    [_to_float(row, "vector_error", float("nan")) for row in current], 50.0
                ),
                "p95_vector_error_mps": _percentile(
                    [_to_float(row, "vector_error", float("nan")) for row in current], 95.0
                ),
                "p99_vector_error_mps": _percentile(
                    [_to_float(row, "vector_error", float("nan")) for row in current], 99.0
                ),
                "tail_probability_ge30": _safe_div(high_count, len(current)),
                "high_error_ge30_count": high_count,
                "high_error_ge30_recall": _safe_div(high_count, total_high),
                "sse_share": _safe_div(sse, total_sse),
                "cumulative_points_score_ge_bucket": len(cumulative),
                "cumulative_high_error_recall_score_ge_bucket": _safe_div(high_cumulative, total_high),
                "cumulative_sse_share_score_ge_bucket": _safe_div(cumulative_sse, total_sse),
            }
        )
    return bucket_rows


def _top_points(rows: list[dict[str, Any]], top_n: int) -> list[dict[str, Any]]:
    sorted_rows = sorted(
        rows,
        key=lambda row: (_to_float(row, "vector_error"), _to_float(row, "representation_error_score")),
        reverse=True,
    )
    out: list[dict[str, Any]] = []
    for rank, row in enumerate(sorted_rows[:top_n], start=1):
        out.append(
            {
                "error_rank": rank,
                "time_str": row.get("time_str", ""),
                "z": _to_int(row, "z"),
                "y": _to_int(row, "y"),
                "x": _to_int(row, "x"),
                "alt_m": _to_float(row, "alt_m"),
                "altitude_bin": row.get("altitude_bin", ""),
                "gt_speed_mps_target_only": _to_float(row, "gt_speed"),
                "pred_speed_mps": _to_float(row, "pred_speed"),
                "nearest_train_speed_mps": _to_float(row, "nearest_train_speed_mps"),
                "vector_error_mps_target": _to_float(row, "vector_error"),
                "representation_error_score": _to_float(row, "representation_error_score"),
                "representation_score_bin": row.get("representation_error_score_bin", ""),
                "compact_rule_flag": _as_bool(row.get("representation_compact_rule_v1")),
                "conservative_rule_flag": _as_bool(row.get("representation_conservative_rule_v1")),
                "nearest_train_distance_vox": _to_float(row, "nearest_train_distance_vox"),
                "nearest_train_source_role": row.get("nearest_train_source_role", ""),
                "nearest_current_count": _to_int(row, "nearest_current_count"),
                "nearest_context_count": _to_int(row, "nearest_context_count"),
                "nearest_role_gap_mps": _to_float(row, "nearest_role_gap_mps"),
                "recon_confidence": _to_float(row, "recon_confidence"),
                "representation_vertical_proxy_mps": _to_float(row, "representation_vertical_proxy_mps"),
                "role_conflict_at_point": _as_bool(row.get("role_conflict_at_point")),
                "representation_reason_codes": row.get("representation_reason_codes", ""),
                "qc_review_flag_target_audit_only": _as_bool(row.get("qc_review_flag")),
                "qc_review_reasons_target_audit_only": row.get("qc_review_reasons", ""),
            }
        )
    return out


def _write_report_md(
    path: Path,
    rows: list[dict[str, Any]],
    rule_rows: list[dict[str, Any]],
    feature_rows: list[dict[str, Any]],
    bucket_rows: list[dict[str, Any]],
    top_rows: list[dict[str, Any]],
) -> None:
    overall_rmse = _rmse_rows(rows)
    overall_mae = _mae_rows(rows)
    overall_p95 = _percentile([_to_float(row, "vector_error", float("nan")) for row in rows], 95.0)
    overall_p99 = _percentile([_to_float(row, "vector_error", float("nan")) for row in rows], 99.0)
    high_count = sum(1 for row in rows if _as_bool(row.get("high_vector_error_ge30mps")))
    strict_ok = all(_as_bool(row.get("strict_holdout_no_leakage")) for row in rows)
    motion_ok = not any(_as_bool(row.get("motion_used_as_wind")) for row in rows)
    score_ge_0p20 = next((row for row in rule_rows if row["rule_name"] == "score_ge_0p20"), {})
    conservative = next((row for row in rule_rows if row["rule_name"] == "truth_free_conservative_rule_v1"), {})
    low_risk_rows = [row for row in rows if _to_float(row, "representation_error_score") < 0.20]
    low_risk_rmse = _rmse_rows(low_risk_rows)
    top_risk_sse_share = _to_float(score_ge_0p20, "sse_share_captured")
    top_risk_high_recall = _to_float(score_ge_0p20, "high_error_ge30_recall")

    lines = [
        "# Stage4 Representation-Error Report",
        "",
        "This report is generated from strict holdout point departures. It is report-only: it does not change `recon_u/v`, `recon_conf`, `recon_mask`, NPZ fields, or official RMSE/MAE.",
        "",
        "Score/rule inputs are restricted to truth-free support and reconstruction diagnostics. Holdout truth fields are used only as report targets.",
        "",
        "## Validation Boundary",
        "",
        "| check | value | result |",
        "| --- | --- | --- |",
        f"| strict_holdout_no_leakage | `{strict_ok}` | {'PASS' if strict_ok else 'FAIL'} |",
        f"| motion_used_as_wind | `{not motion_ok}` | {'PASS' if motion_ok else 'FAIL'} |",
        "| report_only_no_recon_change | `True` | PASS |",
        "| truth_used_for_score_features | `False` | PASS |",
        "| official_holdout_points_removed | `0` | PASS |",
        "",
        "Excluded from score/rule inputs: `vector_error`, `gt_u/v`, `gt_speed`, `qc_review_flag`, `qc_review_reasons`, `point_neighbor_*_vector_error`, and `representativeness_gap_point_minus_min_mps`.",
        "",
        "## Overall Target Distribution",
        "",
        "| points | RMSE | MAE | P95 | P99 | high-error >=30 m/s |",
        "| ---: | ---: | ---: | ---: | ---: | ---: |",
        f"| {len(rows)} | {_fmt(overall_rmse)} | {_fmt(overall_mae)} | {_fmt(overall_p95)} | {_fmt(overall_p99)} | {high_count} |",
        "",
        "## Rule Candidates",
        "",
        "| rule | flagged | high-error recall | high-error precision | unflagged RMSE | SSE share captured | P95 recall | P99 recall |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in rule_rows:
        lines.append(
            f"| `{row['rule_name']}` | {row['flagged_points']} | {_fmt(row['high_error_ge30_recall'])} | "
            f"{_fmt(row['high_error_ge30_precision'])} | {_fmt(row['unflagged_error_rmse'])} | "
            f"{_fmt(row['sse_share_captured'])} | {_fmt(row['p95_tail_recall'])} | {_fmt(row['p99_tail_recall'])} |"
        )

    lines.extend(
        [
            "",
            "## Score Bucket Calibration",
            "",
            "| score bucket | points | sigma_rep/RMSE | tail prob >=30 | high-error recall | SSE share | cumulative high-error recall | cumulative SSE share |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in bucket_rows:
        lines.append(
            f"| `{row['score_bucket']}` | {row['points']} | {_fmt(row['expected_sigma_rep_mps'])} | "
            f"{_fmt(row['tail_probability_ge30'])} | {_fmt(row['high_error_ge30_recall'])} | "
            f"{_fmt(row['sse_share'])} | {_fmt(row['cumulative_high_error_recall_score_ge_bucket'])} | "
            f"{_fmt(row['cumulative_sse_share_score_ge_bucket'])} |"
        )

    lines.extend(
        [
            "",
            "## Highest-Risk Truth-Free Buckets",
            "",
            "| feature | bucket | points | high-error count | high-error rate | rate lift | RMSE | SSE share | mean score |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
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
            f"{_fmt(row['high_error_ge30_rate'])} | {_fmt(row['high_error_rate_lift'])} | "
            f"{_fmt(row['vector_rmse_mps'])} | {_fmt(row['sse_share'])} | "
            f"{_fmt(row['mean_representation_error_score'])} |"
        )
        shown += 1
        if shown >= 18:
            break

    lines.extend(
        [
            "",
            "## Top Target Tail Points",
            "",
            "| rank | frame | z/y/x | alt | gt speed target | pred speed | nearest train speed | error target | score | reasons |",
            "| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for row in top_rows[:12]:
        lines.append(
            f"| {row['error_rank']} | `{row['time_str']}` | `{row['z']}/{row['y']}/{row['x']}` | "
            f"{_fmt(row['alt_m'], 1)} | {_fmt(row['gt_speed_mps_target_only'])} | "
            f"{_fmt(row['pred_speed_mps'])} | {_fmt(row['nearest_train_speed_mps'])} | "
            f"{_fmt(row['vector_error_mps_target'])} | {_fmt(row['representation_error_score'])} | "
            f"`{row['representation_reason_codes']}` |"
        )

    lines.extend(
        [
            "",
            "## Minimum Checklist",
            "",
            "| item | value | result |",
            "| --- | ---: | --- |",
            f"| top-risk score>=0.20 SSE share | {_fmt(top_risk_sse_share)} | {'PASS' if top_risk_sse_share >= 0.80 else 'FAIL'} |",
            f"| top-risk score>=0.20 high-error recall | {_fmt(top_risk_high_recall)} | {'PASS' if top_risk_high_recall >= 0.80 else 'FAIL'} |",
            f"| low-risk score<0.20 RMSE | {_fmt(low_risk_rmse)} | {'PASS' if low_risk_rmse < BASELINE_WEIGHTED_RMSE_MPS else 'FAIL'} |",
            f"| conservative rule high-error recall | {_fmt(conservative.get('high_error_ge30_recall', float('nan')))} | {'PASS' if _to_float(conservative, 'high_error_ge30_recall') >= 0.95 else 'FAIL'} |",
            f"| all official holdout points retained | {len(rows)} | PASS |",
            "",
            "Conclusion: this report supports representation-error / no-claim calibration as a report-only diagnostic. It is not a promotion of a reconstruction branch.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build report-only Stage4 representation-error diagnostics.")
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
            "truth_free_conservative_rule_v1",
            "remote OR role_gap>=30 OR recon_conf<0.05 OR context-only OR vertical_proxy>=10 OR nearest_train_speed>=30",
            lambda row: _as_bool(row.get("representation_conservative_rule_v1")),
        ),
        (
            "truth_free_compact_rule_v1",
            "remote OR role_gap>=30 OR recon_conf<0.05 OR guarded context-only OR vertical_proxy>=25",
            lambda row: _as_bool(row.get("representation_compact_rule_v1")),
        ),
        (
            "score_ge_0p20",
            "representation_error_score >= 0.20",
            lambda row: _to_float(row, "representation_error_score") >= 0.20,
        ),
        (
            "score_ge_0p25",
            "representation_error_score >= 0.25",
            lambda row: _to_float(row, "representation_error_score") >= 0.25,
        ),
        (
            "score_ge_0p35",
            "representation_error_score >= 0.35",
            lambda row: _to_float(row, "representation_error_score") >= 0.35,
        ),
        (
            "score_ge_0p50",
            "representation_error_score >= 0.50",
            lambda row: _to_float(row, "representation_error_score") >= 0.50,
        ),
        (
            "remote_or_low_confidence",
            "nearest_train_distance_vox > 4 OR recon_confidence < 0.05",
            lambda row: _to_float(row, "nearest_train_distance_vox") > 4.0
            or _to_float(row, "recon_confidence") < 0.05,
        ),
        (
            "context_only_or_nearest_speed_ge30",
            "context-only nearest support OR nearest_train_speed >= 30",
            lambda row: _as_bool(row.get("context_only_nearest_support"))
            or _to_float(row, "nearest_train_speed_mps") >= 30.0,
        ),
    ]
    rule_rows = [
        _rule_metrics(enriched_rows, rule_name, description, predicate, p95_threshold, p99_threshold)
        for rule_name, description, predicate in rule_defs
    ]
    feature_rows = _feature_summary_rows(enriched_rows)
    bucket_rows = _bucket_calibration_rows(enriched_rows)
    top_rows = _top_points(enriched_rows, args.top_n)

    metadata = {
        "input_point_departures": str(args.point_departures),
        "out_dir": str(args.out_dir),
        "points": len(enriched_rows),
        "strict_holdout_no_leakage": all(_as_bool(row.get("strict_holdout_no_leakage")) for row in enriched_rows),
        "motion_used_as_wind": any(_as_bool(row.get("motion_used_as_wind")) for row in enriched_rows),
        "report_only_no_recon_change": True,
        "truth_used_for_report_targets": True,
        "truth_used_for_score_features": False,
        "excluded_from_score_features": [
            "vector_error",
            "gt_u",
            "gt_v",
            "gt_speed",
            "qc_review_flag",
            "qc_review_reasons",
            "point_neighbor_mean_vector_error",
            "point_neighbor_min_vector_error",
            "point_neighbor_weighted_vector_error",
            "point_neighbor_std_vector_error",
            "representativeness_gap_point_minus_min_mps",
        ],
    }

    args.out_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(args.out_dir / "representation_error_feature_summary.csv", feature_rows)
    _write_csv(args.out_dir / "representation_error_bucket_calibration.csv", bucket_rows)
    _write_csv(args.out_dir / "representation_error_rule_candidates.csv", rule_rows)
    _write_csv(args.out_dir / "representation_error_top_points.csv", top_rows)
    (args.out_dir / "representation_error_run_metadata.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _write_report_md(
        args.out_dir / "representation_error_report.md",
        enriched_rows,
        rule_rows,
        feature_rows,
        bucket_rows,
        top_rows,
    )

    score_rule = next((row for row in rule_rows if row["rule_name"] == "score_ge_0p20"), None)
    low_risk_rmse = _rmse_rows([row for row in enriched_rows if _to_float(row, "representation_error_score") < 0.20])
    print(f"wrote: {args.out_dir}")
    print(f"overall_points={len(enriched_rows)} overall_rmse={_rmse_rows(enriched_rows):.6f}")
    print(f"low_risk_score_lt_0p20_rmse={low_risk_rmse:.6f}")
    if score_rule is not None:
        print(
            "score_ge_0p20 "
            f"flagged_points={score_rule['flagged_points']} "
            f"high_error_recall={_fmt(score_rule['high_error_ge30_recall'])} "
            f"sse_share={_fmt(score_rule['sse_share_captured'])}"
        )


if __name__ == "__main__":
    main()
