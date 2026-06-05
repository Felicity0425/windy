"""Pairwise frame-level comparison for two Stage4 metrics-only runs."""

from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path
from typing import Any

import numpy as np


def _read_csv(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        return [dict(row) for row in csv.DictReader(f)]


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


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
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


def _unique_by_time(rows: list[dict[str, Any]], label: str) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        time_str = str(row.get("time_str", ""))
        if not time_str:
            continue
        if time_str in out:
            raise ValueError(f"{label} has more than one row for time_str={time_str}; compare one config at a time.")
        out[time_str] = row
    return out


def _point_key(row: dict[str, Any]) -> tuple[str, int, int, int]:
    return (
        str(row.get("time_str", "")),
        _to_int(row, "z"),
        _to_int(row, "y"),
        _to_int(row, "x"),
    )


def _dehaan_sigma_mps(alt_m: float) -> float:
    # Project discretization of de Haan (2016): about 1.4 m/s near surface
    # and about 1.1 m/s near 500 hPa / upper levels.
    if alt_m < 1000.0:
        return 1.4
    if alt_m < 3000.0:
        return 1.3
    if alt_m < 6000.0:
        return 1.2
    return 1.1


def _emaddc_sigma_mps(alt_m: float) -> float:
    # Project operational prior from EMADDC (2025): lower-level winds near
    # 2.2 m/s, increasing toward upper cruise levels.
    if alt_m < 3000.0:
        return 2.2
    if alt_m < 6000.0:
        return 2.5
    return 2.8


def _altitude_bin(alt_m: float) -> str:
    if alt_m < 3000.0:
        return "0-3km"
    if alt_m < 6000.0:
        return "3-6km"
    if alt_m < 9000.0:
        return "6-9km"
    if alt_m < 12000.0:
        return "9-12km"
    return "12km+"


def _truth_speed_bin(speed_mps: float) -> str:
    if speed_mps < 5.0:
        return "0-5mps_calm"
    if speed_mps < 15.0:
        return "5-15mps_light"
    if speed_mps < 30.0:
        return "15-30mps_moderate"
    if speed_mps < 60.0:
        return "30-60mps_strong"
    return "60mps_plus_extreme"


def _angle_error_deg(gt_u: float, gt_v: float, pred_u: float, pred_v: float, gt_speed: float, pred_speed: float) -> float:
    if gt_speed < 5.0 or pred_speed < 1.0:
        return float("nan")
    gt_angle = math.degrees(math.atan2(gt_v, gt_u))
    pred_angle = math.degrees(math.atan2(pred_v, pred_u))
    diff = abs((pred_angle - gt_angle + 180.0) % 360.0 - 180.0)
    return float(diff)


def _finite_values(values: list[float]) -> list[float]:
    return [float(value) for value in values if math.isfinite(float(value))]


def _mean(values: list[float]) -> float:
    finite = _finite_values(values)
    return float(np.mean(finite)) if finite else float("nan")


def _percentile(values: list[float], q: float) -> float:
    finite = _finite_values(values)
    return float(np.percentile(np.asarray(finite, dtype=np.float64), q)) if finite else float("nan")


def _paper_summary(rows: list[dict[str, Any]], label: str, group: str) -> dict[str, Any]:
    if not rows:
        return {}
    u_err = np.asarray([_to_float(row, f"{label}_u_error") for row in rows], dtype=np.float64)
    v_err = np.asarray([_to_float(row, f"{label}_v_error") for row in rows], dtype=np.float64)
    vec = np.sqrt(u_err**2 + v_err**2)
    abs_u = np.abs(u_err)
    abs_v = np.abs(v_err)
    neighborhood_min = np.asarray(
        [_to_float(row, f"{label}_neighbor_min_vector_error", _to_float(row, f"{label}_vector_error")) for row in rows],
        dtype=np.float64,
    )
    neighborhood_weighted = np.asarray(
        [_to_float(row, f"{label}_neighbor_weighted_vector_error", _to_float(row, f"{label}_vector_error")) for row in rows],
        dtype=np.float64,
    )
    represent_gap = np.asarray(
        [_to_float(row, f"{label}_representativeness_gap_point_minus_min_mps", 0.0) for row in rows],
        dtype=np.float64,
    )
    dehaan = np.asarray([_to_float(row, "sigma_dehaan_mps", 1.2) for row in rows], dtype=np.float64)
    emaddc = np.asarray([_to_float(row, "sigma_emaddc_mps", 2.5) for row in rows], dtype=np.float64)
    component_sq = 0.5 * (u_err**2 + v_err**2)
    component_rmse = float(np.sqrt(np.mean(component_sq)))
    return {
        "group": group,
        "method": label,
        "points": int(len(rows)),
        "u_bias_mps": float(np.mean(u_err)),
        "v_bias_mps": float(np.mean(v_err)),
        "u_mae_mps": float(np.mean(abs_u)),
        "v_mae_mps": float(np.mean(abs_v)),
        "u_rmse_mps": float(np.sqrt(np.mean(u_err**2))),
        "v_rmse_mps": float(np.sqrt(np.mean(v_err**2))),
        "component_rmse_mps": component_rmse,
        "vector_rmse_mps": float(np.sqrt(np.mean(vec**2))),
        "vector_mae_mps": float(np.mean(vec)),
        "mean_sigma_dehaan_mps": float(np.mean(dehaan)),
        "mean_sigma_emaddc_mps": float(np.mean(emaddc)),
        "component_rmse_over_dehaan": float(component_rmse / np.mean(dehaan)),
        "component_rmse_over_emaddc": float(component_rmse / np.mean(emaddc)),
        "normalized_chi2_dehaan": float(np.mean(component_sq / np.maximum(dehaan**2, 1e-12))),
        "normalized_chi2_emaddc": float(np.mean(component_sq / np.maximum(emaddc**2, 1e-12))),
        "mean_neighbor_min_vector_error_mps": float(np.mean(neighborhood_min)),
        "mean_neighbor_weighted_vector_error_mps": float(np.mean(neighborhood_weighted)),
        "mean_representativeness_gap_point_minus_min_mps": float(np.mean(represent_gap)),
        "p95_vector_error_mps": float(np.percentile(vec, 95.0)),
        "max_vector_error_mps": float(np.max(vec)),
    }


def _paper_aligned_rows(
    baseline_points: list[dict[str, Any]],
    candidate_points: list[dict[str, Any]],
    baseline_label: str,
    candidate_label: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    baseline = {_point_key(row): row for row in baseline_points if str(row.get("time_str", ""))}
    candidate = {_point_key(row): row for row in candidate_points if str(row.get("time_str", ""))}
    common = sorted(set(baseline) & set(candidate))
    merged: list[dict[str, Any]] = []
    for key in common:
        base = baseline[key]
        cand = candidate[key]
        alt_m = _to_float(cand, "alt_m", _to_float(base, "alt_m"))
        gt_u = _to_float(cand, "gt_u", _to_float(base, "gt_u"))
        gt_v = _to_float(cand, "gt_v", _to_float(base, "gt_v"))
        gt_speed = _to_float(cand, "gt_speed", _to_float(base, "gt_speed", math.sqrt(gt_u**2 + gt_v**2)))
        base_vec = _to_float(base, "vector_error")
        cand_vec = _to_float(cand, "vector_error")
        base_pred_u = _to_float(base, "pred_u")
        base_pred_v = _to_float(base, "pred_v")
        cand_pred_u = _to_float(cand, "pred_u")
        cand_pred_v = _to_float(cand, "pred_v")
        base_pred_speed = _to_float(base, "pred_speed", math.sqrt(base_pred_u**2 + base_pred_v**2))
        cand_pred_speed = _to_float(cand, "pred_speed", math.sqrt(cand_pred_u**2 + cand_pred_v**2))
        merged.append(
            {
                "time_str": key[0],
                "z": key[1],
                "y": key[2],
                "x": key[3],
                "alt_m": alt_m,
                "altitude_bin": _altitude_bin(alt_m),
                "lat": _to_float(cand, "lat", _to_float(base, "lat")),
                "lon": _to_float(cand, "lon", _to_float(base, "lon")),
                "sigma_dehaan_mps": _dehaan_sigma_mps(alt_m),
                "sigma_emaddc_mps": _emaddc_sigma_mps(alt_m),
                "gt_u": gt_u,
                "gt_v": gt_v,
                "gt_speed_mps": gt_speed,
                "truth_speed_bin": _truth_speed_bin(gt_speed),
                f"{baseline_label}_pred_u": base_pred_u,
                f"{baseline_label}_pred_v": base_pred_v,
                f"{baseline_label}_pred_speed_mps": base_pred_speed,
                f"{baseline_label}_u_error": _to_float(base, "u_error"),
                f"{baseline_label}_v_error": _to_float(base, "v_error"),
                f"{baseline_label}_vector_error": base_vec,
                f"{baseline_label}_relative_error_ratio": base_vec / max(gt_speed, 1e-6),
                f"{baseline_label}_floor10_relative_error": base_vec / max(gt_speed, 10.0),
                f"{baseline_label}_direction_error_deg": _angle_error_deg(
                    gt_u,
                    gt_v,
                    base_pred_u,
                    base_pred_v,
                    gt_speed,
                    base_pred_speed,
                ),
                f"{candidate_label}_pred_u": cand_pred_u,
                f"{candidate_label}_pred_v": cand_pred_v,
                f"{candidate_label}_pred_speed_mps": cand_pred_speed,
                f"{candidate_label}_u_error": _to_float(cand, "u_error"),
                f"{candidate_label}_v_error": _to_float(cand, "v_error"),
                f"{candidate_label}_vector_error": cand_vec,
                f"{candidate_label}_relative_error_ratio": cand_vec / max(gt_speed, 1e-6),
                f"{candidate_label}_floor10_relative_error": cand_vec / max(gt_speed, 10.0),
                f"{candidate_label}_direction_error_deg": _angle_error_deg(
                    gt_u,
                    gt_v,
                    cand_pred_u,
                    cand_pred_v,
                    gt_speed,
                    cand_pred_speed,
                ),
                "delta_vector_error_candidate_minus_baseline": cand_vec - base_vec,
                "delta_floor10_relative_error_candidate_minus_baseline": cand_vec / max(gt_speed, 10.0)
                - base_vec / max(gt_speed, 10.0),
                f"{baseline_label}_recon_confidence": _to_float(base, "recon_confidence"),
                f"{candidate_label}_recon_confidence": _to_float(cand, "recon_confidence"),
                f"{baseline_label}_neighbor_mean_vector_error": _to_float(base, "point_neighbor_mean_vector_error", base_vec),
                f"{baseline_label}_neighbor_min_vector_error": _to_float(base, "point_neighbor_min_vector_error", base_vec),
                f"{baseline_label}_neighbor_weighted_vector_error": _to_float(base, "point_neighbor_weighted_vector_error", base_vec),
                f"{baseline_label}_representativeness_gap_point_minus_min_mps": _to_float(base, "representativeness_gap_point_minus_min_mps", 0.0),
                f"{candidate_label}_neighbor_mean_vector_error": _to_float(cand, "point_neighbor_mean_vector_error", cand_vec),
                f"{candidate_label}_neighbor_min_vector_error": _to_float(cand, "point_neighbor_min_vector_error", cand_vec),
                f"{candidate_label}_neighbor_weighted_vector_error": _to_float(cand, "point_neighbor_weighted_vector_error", cand_vec),
                f"{candidate_label}_representativeness_gap_point_minus_min_mps": _to_float(cand, "representativeness_gap_point_minus_min_mps", 0.0),
                "strict_holdout_no_leakage": str(cand.get("strict_holdout_no_leakage", "")),
                "motion_used_as_wind": str(cand.get("motion_used_as_wind", "")),
            }
        )
    summary: list[dict[str, Any]] = []
    for label in [baseline_label, candidate_label]:
        row = _paper_summary(merged, label, "all_holdout_points")
        if row:
            summary.append(row)
    bands: list[dict[str, Any]] = []
    for group in ["0-3km", "3-6km", "6-9km", "9-12km", "12km+"]:
        selected = [row for row in merged if row["altitude_bin"] == group]
        for label in [baseline_label, candidate_label]:
            row = _paper_summary(selected, label, group)
            if row:
                bands.append(row)
    return merged, summary, bands


def _summary(rows: list[dict[str, Any]], baseline_label: str, candidate_label: str) -> dict[str, Any]:
    if not rows:
        return {}
    base_rmse = np.asarray([_to_float(row, f"{baseline_label}_rmse") for row in rows], dtype=np.float64)
    cand_rmse = np.asarray([_to_float(row, f"{candidate_label}_rmse") for row in rows], dtype=np.float64)
    base_mae = np.asarray([_to_float(row, f"{baseline_label}_mae") for row in rows], dtype=np.float64)
    cand_mae = np.asarray([_to_float(row, f"{candidate_label}_mae") for row in rows], dtype=np.float64)
    holdout = np.asarray([max(0, _to_int(row, "holdout_wind_records")) for row in rows], dtype=np.float64)
    weights = np.where(holdout > 0.0, holdout, 1.0)
    delta = cand_rmse - base_rmse

    def _trimmed_rmse(values: np.ndarray, percentile: float = 95.0) -> float:
        cutoff = float(np.percentile(values, percentile))
        kept = values[values <= cutoff]
        if kept.size == 0:
            kept = values
        return float(np.sqrt(np.mean(kept**2)))

    return {
        "frames": int(len(rows)),
        "holdout_points": int(np.sum(holdout)),
        f"{baseline_label}_frame_mean_rmse": float(np.mean(base_rmse)),
        f"{candidate_label}_frame_mean_rmse": float(np.mean(cand_rmse)),
        f"{baseline_label}_frame_mean_mae": float(np.mean(base_mae)),
        f"{candidate_label}_frame_mean_mae": float(np.mean(cand_mae)),
        f"{baseline_label}_median_rmse": float(np.median(base_rmse)),
        f"{candidate_label}_median_rmse": float(np.median(cand_rmse)),
        f"{baseline_label}_weighted_rmse": float(np.sqrt(np.sum((base_rmse**2) * weights) / np.sum(weights))),
        f"{candidate_label}_weighted_rmse": float(np.sqrt(np.sum((cand_rmse**2) * weights) / np.sum(weights))),
        f"{baseline_label}_weighted_mae": float(np.sum(base_mae * weights) / np.sum(weights)),
        f"{candidate_label}_weighted_mae": float(np.sum(cand_mae * weights) / np.sum(weights)),
        f"{baseline_label}_trimmed_rmse_p95": _trimmed_rmse(base_rmse, 95.0),
        f"{candidate_label}_trimmed_rmse_p95": _trimmed_rmse(cand_rmse, 95.0),
        "candidate_wins": int(np.sum(delta < -1e-12)),
        "candidate_losses": int(np.sum(delta > 1e-12)),
        "ties": int(np.sum(np.abs(delta) <= 1e-12)),
        "mean_delta_rmse": float(np.mean(delta)),
        "median_delta_rmse": float(np.median(delta)),
        "p90_candidate_rmse": float(np.percentile(cand_rmse, 90.0)),
        "p95_candidate_rmse": float(np.percentile(cand_rmse, 95.0)),
        "p99_candidate_rmse": float(np.percentile(cand_rmse, 99.0)),
        "max_candidate_rmse": float(np.max(cand_rmse)),
        "p90_baseline_rmse": float(np.percentile(base_rmse, 90.0)),
        "p95_baseline_rmse": float(np.percentile(base_rmse, 95.0)),
        "p99_baseline_rmse": float(np.percentile(base_rmse, 99.0)),
        "max_baseline_rmse": float(np.max(base_rmse)),
        "all_strict_holdout_no_leakage": bool(all(str(row.get("strict_holdout_no_leakage")) == "True" for row in rows)),
        "any_motion_used_as_wind": bool(any(str(row.get("motion_used_as_wind")) == "True" for row in rows)),
    }


def _band_rows(rows: list[dict[str, Any]], baseline_label: str, candidate_label: str) -> list[dict[str, Any]]:
    bands = [
        ("baseline_rmse_le6", lambda value: value <= 6.0),
        ("baseline_rmse_6_10", lambda value: 6.0 < value <= 10.0),
        ("baseline_rmse_10_20", lambda value: 10.0 < value <= 20.0),
        ("baseline_rmse_gt20", lambda value: value > 20.0),
    ]
    out = []
    for name, pred in bands:
        selected = [row for row in rows if pred(_to_float(row, f"{baseline_label}_rmse"))]
        summary = _summary(selected, baseline_label, candidate_label)
        if summary:
            summary["group"] = name
            out.append(summary)
    return out


def _wind_scale_method_metrics(rows: list[dict[str, Any]], label: str, group: str, group_type: str) -> dict[str, Any]:
    vec = [_to_float(row, f"{label}_vector_error") for row in rows]
    rel = [_to_float(row, f"{label}_relative_error_ratio") for row in rows]
    floor10 = [_to_float(row, f"{label}_floor10_relative_error") for row in rows]
    direction = [_to_float(row, f"{label}_direction_error_deg", float("nan")) for row in rows]
    gt_speed = [_to_float(row, "gt_speed_mps") for row in rows]
    return {
        "group_type": group_type,
        "group": group,
        "method": label,
        "points": int(len(rows)),
        "gt_speed_mean_mps": _mean(gt_speed),
        "vector_rmse_mps": float(np.sqrt(np.mean(np.asarray(vec, dtype=np.float64) ** 2))) if vec else float("nan"),
        "vector_mae_mps": _mean(vec),
        "p95_vector_error_mps": _percentile(vec, 95.0),
        "relative_error_mae": _mean(rel),
        "floor10_relative_error_mae": _mean(floor10),
        "floor10_relative_error_p95": _percentile(floor10, 95.0),
        "direction_error_mae_deg": _mean(direction),
    }


def _wind_scale_delta_metrics(rows: list[dict[str, Any]], baseline_label: str, candidate_label: str, group: str, group_type: str) -> dict[str, Any]:
    delta = [_to_float(row, "delta_vector_error_candidate_minus_baseline") for row in rows]
    floor_delta = [_to_float(row, "delta_floor10_relative_error_candidate_minus_baseline") for row in rows]
    return {
        "group_type": group_type,
        "group": group,
        "points": int(len(rows)),
        "mean_delta_vector_error_mps": _mean(delta),
        "median_delta_vector_error_mps": float(np.median(np.asarray(delta, dtype=np.float64))) if delta else float("nan"),
        "p90_delta_vector_error_mps": _percentile(delta, 90.0),
        "max_delta_vector_error_mps": max(delta) if delta else float("nan"),
        "mean_delta_floor10_relative_error": _mean(floor_delta),
        "candidate_worse_gt5mps_points": int(sum(1 for value in delta if value > 5.0)),
        "candidate_better_gt5mps_points": int(sum(1 for value in delta if value < -5.0)),
        "baseline_label": baseline_label,
        "candidate_label": candidate_label,
    }


def _wind_scale_groups(
    paper_merged: list[dict[str, Any]],
    baseline_label: str,
    candidate_label: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    group_specs: list[tuple[str, list[tuple[str, list[dict[str, Any]]]]]] = [
        ("all", [("all_holdout_points", paper_merged)]),
        (
            "speed",
            [
                (name, [row for row in paper_merged if row.get("truth_speed_bin") == name])
                for name in [
                    "0-5mps_calm",
                    "5-15mps_light",
                    "15-30mps_moderate",
                    "30-60mps_strong",
                    "60mps_plus_extreme",
                ]
            ],
        ),
        (
            "altitude",
            [
                (name, [row for row in paper_merged if row.get("altitude_bin") == name])
                for name in ["0-3km", "3-6km", "6-9km", "9-12km", "12km+"]
            ],
        ),
    ]
    method_rows: list[dict[str, Any]] = []
    delta_rows: list[dict[str, Any]] = []
    for group_type, groups in group_specs:
        for group, selected in groups:
            if not selected:
                continue
            method_rows.append(_wind_scale_method_metrics(selected, baseline_label, group, group_type))
            method_rows.append(_wind_scale_method_metrics(selected, candidate_label, group, group_type))
            delta_rows.append(_wind_scale_delta_metrics(selected, baseline_label, candidate_label, group, group_type))
    return method_rows, delta_rows


def _method_group_lookup(rows: list[dict[str, Any]], method: str, group_type: str, group: str, metric: str) -> float:
    for row in rows:
        if row.get("method") == method and row.get("group_type") == group_type and row.get("group") == group:
            return _to_float(row, metric, float("nan"))
    return float("nan")


def _promotion_checklist(
    summary: dict[str, Any],
    paper_merged: list[dict[str, Any]],
    wind_method_rows: list[dict[str, Any]],
    baseline_label: str,
    candidate_label: str,
) -> list[dict[str, Any]]:
    def row(name: str, baseline: float | str | bool, candidate: float | str | bool, passed: bool, detail: str = "") -> dict[str, Any]:
        return {
            "gate": name,
            "baseline_value": baseline,
            "candidate_value": candidate,
            "passed": bool(passed),
            "detail": detail,
        }

    rows: list[dict[str, Any]] = []
    rows.append(row("strict_holdout_no_leakage_all_true", "True", summary.get("all_strict_holdout_no_leakage"), bool(summary.get("all_strict_holdout_no_leakage"))))
    rows.append(row("motion_used_as_wind_all_false", "False", summary.get("any_motion_used_as_wind"), not bool(summary.get("any_motion_used_as_wind"))))

    def no_worse_gate(gate: str, base_key: str, cand_key: str) -> None:
        base = _to_float(summary, base_key, float("nan"))
        cand = _to_float(summary, cand_key, float("nan"))
        rows.append(row(gate, base, cand, math.isfinite(base) and math.isfinite(cand) and cand <= base))

    no_worse_gate("weighted_rmse_no_worse", f"{baseline_label}_weighted_rmse", f"{candidate_label}_weighted_rmse")
    no_worse_gate("frame_p95_no_worse", "p95_baseline_rmse", "p95_candidate_rmse")
    no_worse_gate("frame_p99_no_worse", "p99_baseline_rmse", "p99_candidate_rmse")

    base_12 = _method_group_lookup(wind_method_rows, baseline_label, "altitude", "12km+", "vector_rmse_mps")
    cand_12 = _method_group_lookup(wind_method_rows, candidate_label, "altitude", "12km+", "vector_rmse_mps")
    rows.append(row("alt_12km_plus_vector_rmse_no_worse", base_12, cand_12, math.isfinite(base_12) and math.isfinite(cand_12) and cand_12 <= base_12))

    for metric in ["vector_rmse_mps", "vector_mae_mps"]:
        base_light = _method_group_lookup(wind_method_rows, baseline_label, "speed", "5-15mps_light", metric)
        cand_light = _method_group_lookup(wind_method_rows, candidate_label, "speed", "5-15mps_light", metric)
        rows.append(
            row(
                f"light_wind_{metric}_no_worse",
                base_light,
                cand_light,
                math.isfinite(base_light) and math.isfinite(cand_light) and cand_light <= base_light,
            )
        )

    base_floor = _method_group_lookup(wind_method_rows, baseline_label, "all", "all_holdout_points", "floor10_relative_error_mae")
    cand_floor = _method_group_lookup(wind_method_rows, candidate_label, "all", "all_holdout_points", "floor10_relative_error_mae")
    rows.append(
        row(
            "floor10_relative_error_mae_no_worse",
            base_floor,
            cand_floor,
            math.isfinite(base_floor) and math.isfinite(cand_floor) and cand_floor <= base_floor,
        )
    )

    bad_light_moderate = [
        record
        for record in paper_merged
        if record.get("truth_speed_bin") in {"5-15mps_light", "15-30mps_moderate"}
        and _to_float(record, f"{candidate_label}_relative_error_ratio") > 2.0
        and _to_float(record, "delta_vector_error_candidate_minus_baseline") > 5.0
    ]
    rows.append(
        row(
            "light_moderate_relative_tail_no_new_failure",
            0,
            len(bad_light_moderate),
            len(bad_light_moderate) == 0,
            "candidate relative_error_ratio > 2 and delta_vector_error > 5 m/s",
        )
    )

    overall_pass = all(bool(item["passed"]) for item in rows)
    rows.insert(0, row("PROMOTION_OVERALL", "all gates pass", "PASS" if overall_pass else "FAIL", overall_pass))
    return rows


def _write_promotion_md(path: Path, checklist: list[dict[str, Any]]) -> None:
    lines = [
        "# Stage4 Promotion Checklist",
        "",
        "| gate | baseline | candidate | passed | detail |",
        "| --- | ---: | ---: | --- | --- |",
    ]
    for row in checklist:
        lines.append(
            f"| `{row['gate']}` | `{row.get('baseline_value', '')}` | `{row.get('candidate_value', '')}` | "
            f"`{row.get('passed')}` | {row.get('detail', '')} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_md(
    path: Path,
    summary: dict[str, Any],
    bands: list[dict[str, Any]],
    baseline_label: str,
    candidate_label: str,
    paper_summary: list[dict[str, Any]] | None = None,
    paper_bands: list[dict[str, Any]] | None = None,
    promotion_checklist: list[dict[str, Any]] | None = None,
) -> None:
    lines = [
        "# Stage4 Pairwise Frame Comparison",
        "",
        f"Baseline: `{baseline_label}`",
        f"Candidate: `{candidate_label}`",
        "",
        "## Aggregate",
        "",
        "| metric | value |",
        "| --- | ---: |",
    ]
    for key, value in summary.items():
        if isinstance(value, bool):
            lines.append(f"| `{key}` | `{value}` |")
        else:
            lines.append(f"| `{key}` | {float(value):.6f} |")
    if promotion_checklist:
        overall = next((row for row in promotion_checklist if row.get("gate") == "PROMOTION_OVERALL"), None)
        lines.extend(
            [
                "",
                "## Promotion Checklist",
                "",
                f"Overall: `{overall.get('candidate_value') if overall else 'UNKNOWN'}`",
                "",
                "| gate | baseline | candidate | passed |",
                "| --- | ---: | ---: | --- |",
            ]
        )
        for row in promotion_checklist:
            if row.get("gate") == "PROMOTION_OVERALL":
                continue
            lines.append(
                f"| `{row['gate']}` | `{row.get('baseline_value', '')}` | `{row.get('candidate_value', '')}` | `{row.get('passed')}` |"
            )
    lines.extend(
        [
            "",
            "## Baseline RMSE Bands",
            "",
            "| group | frames | baseline RMSE | candidate RMSE | delta | wins | losses |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in bands:
        base = float(row[f"{baseline_label}_frame_mean_rmse"])
        cand = float(row[f"{candidate_label}_frame_mean_rmse"])
        lines.append(
            f"| `{row['group']}` | {int(row['frames'])} | {base:.6f} | {cand:.6f} | {cand - base:.6f} | "
            f"{int(row['candidate_wins'])} | {int(row['candidate_losses'])} |"
        )
    if paper_summary:
        lines.extend(
            [
                "",
                "## Paper-Aligned Aircraft Departure Metrics",
                "",
                "These metrics use point-level analysis departures: `reconstruction - withheld aircraft wind`. "
                "The literature sigma columns are observation-error reference priors; they are not direct targets for Stage4 reconstruction RMSE.",
                "",
                "| method | points | u bias | v bias | u RMSE | v RMSE | component RMSE | vector RMSE | de Haan sigma | EMADDC sigma | comp/de Haan | comp/EMADDC | norm chi2 de Haan | norm chi2 EMADDC |",
                "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for row in paper_summary:
            lines.append(
                f"| `{row['method']}` | {int(row['points'])} | {float(row['u_bias_mps']):.6f} | "
                f"{float(row['v_bias_mps']):.6f} | {float(row['u_rmse_mps']):.6f} | "
                f"{float(row['v_rmse_mps']):.6f} | {float(row['component_rmse_mps']):.6f} | "
                f"{float(row['vector_rmse_mps']):.6f} | {float(row['mean_sigma_dehaan_mps']):.6f} | "
                f"{float(row['mean_sigma_emaddc_mps']):.6f} | {float(row['component_rmse_over_dehaan']):.6f} | "
                f"{float(row['component_rmse_over_emaddc']):.6f} | {float(row['normalized_chi2_dehaan']):.6f} | "
                f"{float(row['normalized_chi2_emaddc']):.6f} |"
            )
    if paper_bands:
        lines.extend(
            [
                "",
                "## Paper-Aligned Height Bins",
                "",
                "| altitude bin | method | points | component RMSE | vector RMSE | de Haan sigma | EMADDC sigma | comp/de Haan | comp/EMADDC | p95 vector | max vector |",
                "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for row in paper_bands:
            lines.append(
                f"| `{row['group']}` | `{row['method']}` | {int(row['points'])} | "
                f"{float(row['component_rmse_mps']):.6f} | {float(row['vector_rmse_mps']):.6f} | "
                f"{float(row['mean_sigma_dehaan_mps']):.6f} | {float(row['mean_sigma_emaddc_mps']):.6f} | "
                f"{float(row['component_rmse_over_dehaan']):.6f} | {float(row['component_rmse_over_emaddc']):.6f} | "
                f"{float(row['p95_vector_error_mps']):.6f} | {float(row['max_vector_error_mps']):.6f} |"
            )
        lines.extend(
            [
                "",
                "Reference mapping:",
                "",
                "- `de Haan sigma` is the project height-bin approximation of Mode-S EHS component observation error from de Haan (2016).",
                "- `EMADDC sigma` is the project operational aircraft-derived wind prior from EMADDC (2025).",
                "- Values above these priors indicate reconstruction, representativeness, localization, and sparse-support error in addition to aircraft observation error.",
            ]
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare two Stage4 per-frame sensitivity CSV files.")
    parser.add_argument("--baseline-csv", type=Path, required=True)
    parser.add_argument("--candidate-csv", type=Path, required=True)
    parser.add_argument("--baseline-point-csv", type=Path)
    parser.add_argument("--candidate-point-csv", type=Path)
    parser.add_argument("--baseline-label", default="baseline")
    parser.add_argument("--candidate-label", default="candidate")
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--out-prefix", default="stage4_pairwise")
    parser.add_argument("--top-n", type=int, default=20)
    args = parser.parse_args()

    baseline = _unique_by_time(_read_csv(args.baseline_csv), args.baseline_label)
    candidate = _unique_by_time(_read_csv(args.candidate_csv), args.candidate_label)
    common = sorted(set(baseline) & set(candidate))
    if not common:
        raise ValueError("No common frame times between the two CSV files.")
    rows: list[dict[str, Any]] = []
    for time_str in common:
        base = baseline[time_str]
        cand = candidate[time_str]
        base_rmse = _to_float(base, "rmse_vector")
        cand_rmse = _to_float(cand, "rmse_vector")
        rows.append(
            {
                "time_str": time_str,
                "holdout_wind_records": _to_int(base, "holdout_wind_records"),
                f"{args.baseline_label}_rmse": base_rmse,
                f"{args.candidate_label}_rmse": cand_rmse,
                "delta_rmse_candidate_minus_baseline": cand_rmse - base_rmse,
                f"{args.baseline_label}_mae": _to_float(base, "mae_vector"),
                f"{args.candidate_label}_mae": _to_float(cand, "mae_vector"),
                "delta_mae_candidate_minus_baseline": _to_float(cand, "mae_vector") - _to_float(base, "mae_vector"),
                "strict_holdout_no_leakage": str(cand.get("strict_holdout_no_leakage")),
                "motion_used_as_wind": str(cand.get("motion_used_as_wind")),
                "baseline_effective_reconstructed_voxels": _to_int(base, "effective_reconstructed_voxels"),
                "candidate_effective_reconstructed_voxels": _to_int(cand, "effective_reconstructed_voxels"),
            }
        )
    summary = _summary(rows, args.baseline_label, args.candidate_label)
    bands = _band_rows(rows, args.baseline_label, args.candidate_label)
    paper_merged: list[dict[str, Any]] = []
    paper_summary: list[dict[str, Any]] = []
    paper_bands: list[dict[str, Any]] = []
    wind_method_rows: list[dict[str, Any]] = []
    wind_delta_rows: list[dict[str, Any]] = []
    promotion_checklist: list[dict[str, Any]] = []
    if args.baseline_point_csv and args.candidate_point_csv:
        paper_merged, paper_summary, paper_bands = _paper_aligned_rows(
            _read_csv(args.baseline_point_csv),
            _read_csv(args.candidate_point_csv),
            args.baseline_label,
            args.candidate_label,
        )
        wind_method_rows, wind_delta_rows = _wind_scale_groups(paper_merged, args.baseline_label, args.candidate_label)
        promotion_checklist = _promotion_checklist(summary, paper_merged, wind_method_rows, args.baseline_label, args.candidate_label)
    top_n = max(1, int(args.top_n))
    top_wins = sorted(rows, key=lambda row: float(row["delta_rmse_candidate_minus_baseline"]))[:top_n]
    top_losses = sorted(rows, key=lambda row: float(row["delta_rmse_candidate_minus_baseline"]), reverse=True)[:top_n]

    args.out_dir.mkdir(parents=True, exist_ok=True)
    merged_csv = args.out_dir / f"{args.out_prefix}_merged.csv"
    summary_csv = args.out_dir / f"{args.out_prefix}_summary.csv"
    bands_csv = args.out_dir / f"{args.out_prefix}_baseline_rmse_bands.csv"
    paper_merged_csv = args.out_dir / f"{args.out_prefix}_paper_point_departures.csv"
    paper_summary_csv = args.out_dir / f"{args.out_prefix}_paper_summary.csv"
    paper_bands_csv = args.out_dir / f"{args.out_prefix}_paper_height_bins.csv"
    wind_method_csv = args.out_dir / f"{args.out_prefix}_wind_scale_method_groups.csv"
    wind_delta_csv = args.out_dir / f"{args.out_prefix}_wind_scale_delta_groups.csv"
    promotion_csv = args.out_dir / f"{args.out_prefix}_promotion_checklist.csv"
    promotion_md = args.out_dir / f"{args.out_prefix}_promotion_checklist.md"
    wins_csv = args.out_dir / f"{args.out_prefix}_top_candidate_wins.csv"
    losses_csv = args.out_dir / f"{args.out_prefix}_top_candidate_losses.csv"
    md_path = args.out_dir / f"{args.out_prefix}.md"
    _write_csv(merged_csv, rows)
    _write_csv(summary_csv, [summary])
    _write_csv(bands_csv, bands)
    if args.baseline_point_csv and args.candidate_point_csv:
        _write_csv(paper_merged_csv, paper_merged)
        _write_csv(paper_summary_csv, paper_summary)
        _write_csv(paper_bands_csv, paper_bands)
        _write_csv(wind_method_csv, wind_method_rows)
        _write_csv(wind_delta_csv, wind_delta_rows)
        _write_csv(promotion_csv, promotion_checklist)
        _write_promotion_md(promotion_md, promotion_checklist)
    _write_csv(wins_csv, top_wins)
    _write_csv(losses_csv, top_losses)
    _write_md(
        md_path,
        summary,
        bands,
        args.baseline_label,
        args.candidate_label,
        paper_summary,
        paper_bands,
        promotion_checklist,
    )
    print(md_path)


if __name__ == "__main__":
    main()
