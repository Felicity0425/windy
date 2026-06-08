"""Decompose Stage4 pairwise errors into paper-aligned diagnostic groups."""

from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path
from typing import Any, Callable

import numpy as np


LITERATURE_GUIDE: dict[str, dict[str, str]] = {
    "observation_error": {
        "mechanism": "Aircraft wind itself has a finite measurement/QC error, but this should be much smaller than Stage4 reconstruction departures.",
        "fix": "Use de Haan/EMADDC as the R prior and keep it separate from reconstruction and representativeness error.",
        "literature": "de Haan 2016 Mode-S EHS triple collocation; EMADDC 2025 operational Mode-S EHS aircraft weather observations.",
    },
    "representation_error": {
        "mechanism": "A point aircraft observation is compared to a 500 m grid/time-window reconstruction; sampling, interpolation, and scale mismatch inflate departures.",
        "fix": "Report height/speed/support bins; add representativeness sigma or neighborhood verification instead of treating all departures as observation error.",
        "literature": "Janjic et al. 2018 representation error in data assimilation.",
    },
    "localization": {
        "mechanism": "Too narrow a kernel misses physically relevant nearby context; too wide a kernel admits unrelated or stale observations.",
        "fix": "Tune radius/sigma by support regime; add per-point/flow-dependent localization and a tail-risk guard for high-altitude sparse regions.",
        "literature": "Gaspari and Cohn 1999 covariance localization; DART localization guidance; LETKF/local data assimilation.",
    },
    "temporal_weighting": {
        "mechanism": "Context observations are not synchronous; an exponential time-confidence can either overuse stale context or underuse useful recent context.",
        "fix": "Diagnose O-A by context-time bins; fit time decay against holdout departures without leakage, then use frame-level cross-validation.",
        "literature": "ECMWF 4D-Var observation-window logic; Desroziers et al. 2005 observation-space diagnostics.",
    },
    "role_conflict": {
        "mechanism": "Current aircraft anchors and context winds may disagree; aggressive current-priority can help anchors but hurt context-dependent holdout points.",
        "fix": "Make role conflict threshold depend on height/support/time and preserve context when current support is too sparse.",
        "literature": "Observation/background departure diagnostics in variational data assimilation; PyDDA-style observation/background constraints.",
    },
    "vertical_structure": {
        "mechanism": "High-altitude and strong-shear layers are vulnerable to vertical oversmoothing or cross-layer contamination.",
        "fix": "Use anisotropic vertical localization, layer-preserving smoothing, and height-bin-specific sigma/context rules.",
        "literature": "DART vertical localization guidance; PyDDA/3DVAR smoothness and physical constraints; Perona-Malik edge-preserving diffusion.",
    },
    "sparse_support": {
        "mechanism": "When the nearest non-holdout current wind is far away or absent, the reconstruction becomes extrapolation rather than interpolation.",
        "fix": "Flag sparse-support points, use wider/context-aware kernels only there, and report no/low-support skill separately.",
        "literature": "Representation error literature and localization guidance both require support-aware interpretation.",
    },
    "tail_qc": {
        "mechanism": "A small number of extreme points dominate weighted RMSE and P99/max error.",
        "fix": "Add high-error review, robust loss/reporting, and a separate tail-risk head; do not tune the mean RMSE only.",
        "literature": "Operational aircraft QC in EMADDC 2025; Desroziers-style departure monitoring.",
    },
}


DIAGNOSTIC_TO_SOURCE = {
    "altitude_bin": "vertical_structure",
    "adaptive_selected_kernel": "localization",
    "nearest_distance_bin": "sparse_support",
    "nearest_train_source_role": "sparse_support",
    "nearest_current_count_bin": "sparse_support",
    "nearest_context_count_bin": "sparse_support",
    "nearest_role_gap_bin": "role_conflict",
    "role_conflict_at_point": "role_conflict",
    "role_conflict_component_gap_bin": "role_conflict",
    "context_time_conf_bin": "temporal_weighting",
    "adaptive_context_time_conf_mean": "temporal_weighting",
    "adaptive_current_support": "sparse_support",
    "adaptive_role_gap_mps": "role_conflict",
    "local_consistency_conf_mean": "representation_error",
    "role_conflict_fraction_of_overlap": "role_conflict",
    "vertical_context_mismatch_voxels": "vertical_structure",
    "recon_vertical_jump_bin": "vertical_structure",
    "vertical_speed_gap_bin": "vertical_structure",
    "truth_speed_bin": "representation_error",
    "recon_confidence_bin": "representation_error",
    "qc_review_bin": "tail_qc",
}


def _read_csv(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        return [dict(row) for row in csv.DictReader(f)]


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


def _sort_key(row: dict[str, Any], *keys: str) -> tuple[Any, ...]:
    out: list[Any] = []
    for key in keys:
        value = row.get(key)
        if isinstance(value, (int, float)):
            out.append(value)
        else:
            try:
                out.append(float(value))
            except (TypeError, ValueError):
                out.append(str(value))
    return tuple(out)


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


def _bin(value: float, edges: list[tuple[float | None, float | None, str]]) -> str:
    for lo, hi, label in edges:
        if lo is not None and value < lo:
            continue
        if hi is not None and value >= hi:
            continue
        return label
    return "unknown"


def _point_key(row: dict[str, Any]) -> tuple[str, int, int, int]:
    return str(row.get("time_str", "")), _to_int(row, "z"), _to_int(row, "y"), _to_int(row, "x")


def _merge_frames(
    baseline_rows: list[dict[str, Any]],
    candidate_rows: list[dict[str, Any]],
    baseline_label: str,
    candidate_label: str,
) -> list[dict[str, Any]]:
    baseline = {str(row.get("time_str", "")): row for row in baseline_rows}
    candidate = {str(row.get("time_str", "")): row for row in candidate_rows}
    out: list[dict[str, Any]] = []
    for time_str in sorted(set(baseline) & set(candidate)):
        base = baseline[time_str]
        cand = candidate[time_str]
        base_rmse = _to_float(base, "rmse_vector")
        cand_rmse = _to_float(cand, "rmse_vector")
        holdout = max(0, _to_int(base, "holdout_wind_records"))
        out.append(
            {
                "time_str": time_str,
                "holdout_points": holdout,
                f"{baseline_label}_vector_rmse": base_rmse,
                f"{candidate_label}_vector_rmse": cand_rmse,
                "delta_vector_rmse_candidate_minus_baseline": cand_rmse - base_rmse,
                "adaptive_selected_kernel": f"{_to_int(cand, 'localization_radius_xy')}:{_to_float(cand, 'localization_sigma_xy'):.0f}",
                "adaptive_current_support": _to_int(cand, "adaptive_current_support"),
                "adaptive_context_support": _to_int(cand, "adaptive_context_support"),
                "adaptive_context_time_conf_mean": _to_float(cand, "adaptive_context_time_conf_mean"),
                "adaptive_role_gap_mps": _to_float(cand, "adaptive_role_gap_mps"),
                "local_consistency_conf_mean": _to_float(cand, "local_consistency_conf_mean"),
                "role_conflict_voxels": _to_int(cand, "role_conflict_voxels"),
                "role_conflict_fraction_of_overlap": _to_float(cand, "role_conflict_fraction_of_overlap"),
                "vertical_context_mismatch_candidate_voxels": _to_int(cand, "vertical_context_mismatch_candidate_voxels"),
                "vertical_oversmoothing_candidate_voxels": _to_int(cand, "vertical_oversmoothing_candidate_voxels"),
                "strong_vertical_isolated_voxels": _to_int(cand, "strong_vertical_isolated_voxels"),
                "strict_holdout_no_leakage": str(cand.get("strict_holdout_no_leakage", "")),
                "motion_used_as_wind": str(cand.get("motion_used_as_wind", "")),
            }
        )
    return out


def _merge_points(
    baseline_rows: list[dict[str, Any]],
    candidate_rows: list[dict[str, Any]],
    baseline_label: str,
    candidate_label: str,
) -> list[dict[str, Any]]:
    baseline = {_point_key(row): row for row in baseline_rows if str(row.get("time_str", ""))}
    candidate = {_point_key(row): row for row in candidate_rows if str(row.get("time_str", ""))}
    out: list[dict[str, Any]] = []
    for key in sorted(set(baseline) & set(candidate)):
        base = baseline[key]
        cand = candidate[key]
        base_u = _to_float(base, "u_error")
        base_v = _to_float(base, "v_error")
        cand_u = _to_float(cand, "u_error")
        cand_v = _to_float(cand, "v_error")
        alt_m = _to_float(cand, "alt_m", _to_float(base, "alt_m"))
        sigma_dehaan = _to_float(cand, "sigma_dehaan_mps", 0.0)
        sigma_emaddc = _to_float(cand, "sigma_emaddc_mps", 0.0)
        if sigma_dehaan <= 0.0:
            sigma_dehaan = _dehaan_sigma_mps(alt_m)
        if sigma_emaddc <= 0.0:
            sigma_emaddc = _emaddc_sigma_mps(alt_m)
        out.append(
            {
                "time_str": key[0],
                "z": key[1],
                "y": key[2],
                "x": key[3],
                "alt_m": alt_m,
                "altitude_bin": _altitude_bin(alt_m),
                "gt_speed": _to_float(cand, "gt_speed", _to_float(base, "gt_speed")),
                "truth_speed_bin": _truth_speed_bin(_to_float(cand, "gt_speed", _to_float(base, "gt_speed"))),
                "sigma_dehaan_mps": sigma_dehaan,
                "sigma_emaddc_mps": sigma_emaddc,
                f"{baseline_label}_u_error": base_u,
                f"{baseline_label}_v_error": base_v,
                f"{baseline_label}_vector_error": math.sqrt(base_u * base_u + base_v * base_v),
                f"{candidate_label}_u_error": cand_u,
                f"{candidate_label}_v_error": cand_v,
                f"{candidate_label}_vector_error": math.sqrt(cand_u * cand_u + cand_v * cand_v),
                "delta_vector_error_candidate_minus_baseline": math.sqrt(cand_u * cand_u + cand_v * cand_v)
                - math.sqrt(base_u * base_u + base_v * base_v),
                "adaptive_selected_kernel": f"{_to_int(cand, 'localization_radius_xy')}:{_to_float(cand, 'localization_sigma_xy'):.0f}",
                "nearest_train_distance_vox": _to_float(cand, "nearest_train_distance_vox", -1.0),
                "nearest_distance_bin": _nearest_distance_bin(_to_float(cand, "nearest_train_distance_vox", -1.0)),
                "nearest_train_source_role": str(cand.get("nearest_train_source_role", "")),
                "nearest_current_count": _to_int(cand, "nearest_current_count"),
                "nearest_current_count_bin": _count_bin(_to_int(cand, "nearest_current_count")),
                "nearest_context_count": _to_int(cand, "nearest_context_count"),
                "nearest_context_count_bin": _count_bin(_to_int(cand, "nearest_context_count")),
                "nearest_role_gap_mps": _to_float(cand, "nearest_role_gap_mps"),
                "nearest_role_gap_bin": _role_gap_bin(_to_float(cand, "nearest_role_gap_mps")),
                "role_conflict_at_point": str(cand.get("role_conflict_at_point", "")),
                "role_conflict_at_point_bin": "role_conflict" if _as_bool(cand.get("role_conflict_at_point")) else "no_role_conflict",
                "role_conflict_context_time_conf_at_point": _to_float(cand, "role_conflict_context_time_conf_at_point"),
                "context_time_conf_bin": _context_time_bin(_to_float(cand, "role_conflict_context_time_conf_at_point")),
                "role_conflict_component_gap_at_point_mps": _to_float(cand, "role_conflict_component_gap_at_point_mps"),
                "role_conflict_component_gap_bin": _role_gap_bin(_to_float(cand, "role_conflict_component_gap_at_point_mps")),
                "recon_confidence": _to_float(cand, "recon_confidence"),
                "recon_confidence_bin": _confidence_bin(_to_float(cand, "recon_confidence")),
                "recon_vertical_jump_mps": _to_float(cand, "recon_vertical_jump_mps"),
                "recon_vertical_jump_bin": _vertical_jump_bin(_to_float(cand, "recon_vertical_jump_mps")),
                "vertical_speed_gap_mps": _to_float(cand, "vertical_speed_gap_mps"),
                "vertical_speed_gap_bin": _vertical_speed_gap_bin(_to_float(cand, "vertical_speed_gap_mps")),
                "qc_review_flag": str(cand.get("qc_review_flag", "")),
                "qc_review_bin": "qc_review" if _as_bool(cand.get("qc_review_flag")) else "no_qc_review",
            }
        )
    return out


def _dehaan_sigma_mps(alt_m: float) -> float:
    if alt_m < 1000.0:
        return 1.4
    if alt_m < 3000.0:
        return 1.3
    if alt_m < 6000.0:
        return 1.2
    return 1.1


def _emaddc_sigma_mps(alt_m: float) -> float:
    if alt_m < 3000.0:
        return 2.2
    if alt_m < 6000.0:
        return 2.5
    return 2.8


def _altitude_bin(alt_m: float) -> str:
    return _bin(
        alt_m,
        [
            (None, 3000.0, "0-3km"),
            (3000.0, 6000.0, "3-6km"),
            (6000.0, 9000.0, "6-9km"),
            (9000.0, 12000.0, "9-12km"),
            (12000.0, None, "12km+"),
        ],
    )


def _truth_speed_bin(speed: float) -> str:
    return _bin(
        speed,
        [
            (None, 15.0, "speed_lt15"),
            (15.0, 30.0, "speed_15_30"),
            (30.0, 60.0, "speed_30_60"),
            (60.0, None, "speed_ge60"),
        ],
    )


def _nearest_distance_bin(distance: float) -> str:
    if distance < 0.0:
        return "missing"
    return _bin(
        distance,
        [
            (None, 0.5, "dist_0"),
            (0.5, 1.5, "dist_0_5_1_5"),
            (1.5, 3.0, "dist_1_5_3"),
            (3.0, 6.0, "dist_3_6"),
            (6.0, None, "dist_ge6"),
        ],
    )


def _count_bin(count: int) -> str:
    if count <= 0:
        return "count_0"
    if count == 1:
        return "count_1"
    if count <= 3:
        return "count_2_3"
    return "count_ge4"


def _role_gap_bin(gap: float) -> str:
    return _bin(
        gap,
        [
            (None, 5.0, "gap_lt5"),
            (5.0, 15.0, "gap_5_15"),
            (15.0, 30.0, "gap_15_30"),
            (30.0, None, "gap_ge30"),
        ],
    )


def _context_time_bin(value: float) -> str:
    return _bin(
        value,
        [
            (None, 0.2, "timeconf_lt0_2"),
            (0.2, 0.4, "timeconf_0_2_0_4"),
            (0.4, 0.6, "timeconf_0_4_0_6"),
            (0.6, None, "timeconf_ge0_6"),
        ],
    )


def _confidence_bin(value: float) -> str:
    return _bin(
        value,
        [
            (None, 0.2, "conf_lt0_2"),
            (0.2, 0.6, "conf_0_2_0_6"),
            (0.6, 0.95, "conf_0_6_0_95"),
            (0.95, None, "conf_ge0_95"),
        ],
    )


def _vertical_jump_bin(value: float) -> str:
    return _bin(
        value,
        [
            (None, 2.0, "jump_lt2"),
            (2.0, 5.0, "jump_2_5"),
            (5.0, 15.0, "jump_5_15"),
            (15.0, None, "jump_ge15"),
        ],
    )


def _vertical_speed_gap_bin(value: float) -> str:
    return _bin(
        value,
        [
            (None, 2.0, "vgap_lt2"),
            (2.0, 10.0, "vgap_2_10"),
            (10.0, 30.0, "vgap_10_30"),
            (30.0, None, "vgap_ge30"),
        ],
    )


def _frame_metric_rows(
    rows: list[dict[str, Any]],
    group_name: str,
    group_fn: Callable[[dict[str, Any]], str],
    baseline_label: str,
    candidate_label: str,
) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(group_fn(row), []).append(row)
    out: list[dict[str, Any]] = []
    for group, selected in sorted(groups.items()):
        if not selected:
            continue
        weights = np.asarray([max(1, _to_int(row, "holdout_points")) for row in selected], dtype=np.float64)
        base = np.asarray([_to_float(row, f"{baseline_label}_vector_rmse") for row in selected], dtype=np.float64)
        cand = np.asarray([_to_float(row, f"{candidate_label}_vector_rmse") for row in selected], dtype=np.float64)
        delta = cand - base
        out.append(
            {
                "diagnostic": group_name,
                "group": group,
                "frames": int(len(selected)),
                "holdout_points": int(np.sum(weights)),
                f"{baseline_label}_weighted_vector_rmse": float(np.sqrt(np.sum((base**2) * weights) / np.sum(weights))),
                f"{candidate_label}_weighted_vector_rmse": float(np.sqrt(np.sum((cand**2) * weights) / np.sum(weights))),
                "delta_candidate_minus_baseline": float(np.sqrt(np.sum((cand**2) * weights) / np.sum(weights)) - np.sqrt(np.sum((base**2) * weights) / np.sum(weights))),
                "mean_frame_delta": float(np.mean(delta)),
                "candidate_wins": int(np.sum(delta < -1e-12)),
                "candidate_losses": int(np.sum(delta > 1e-12)),
                "ties": int(np.sum(np.abs(delta) <= 1e-12)),
                "mean_holdout_points_per_frame": float(np.mean(weights)),
            }
        )
    return out


def _point_metric_rows(
    rows: list[dict[str, Any]],
    group_name: str,
    group_fn: Callable[[dict[str, Any]], str],
    baseline_label: str,
    candidate_label: str,
) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(group_fn(row), []).append(row)
    out: list[dict[str, Any]] = []
    for group, selected in sorted(groups.items()):
        if not selected:
            continue
        base_u = np.asarray([_to_float(row, f"{baseline_label}_u_error") for row in selected], dtype=np.float64)
        base_v = np.asarray([_to_float(row, f"{baseline_label}_v_error") for row in selected], dtype=np.float64)
        cand_u = np.asarray([_to_float(row, f"{candidate_label}_u_error") for row in selected], dtype=np.float64)
        cand_v = np.asarray([_to_float(row, f"{candidate_label}_v_error") for row in selected], dtype=np.float64)
        sigma = np.asarray([_to_float(row, "sigma_emaddc_mps", 2.8) for row in selected], dtype=np.float64)
        base_vec = np.sqrt(base_u**2 + base_v**2)
        cand_vec = np.sqrt(cand_u**2 + cand_v**2)
        base_component = np.sqrt(0.5 * np.mean(base_u**2 + base_v**2))
        cand_component = np.sqrt(0.5 * np.mean(cand_u**2 + cand_v**2))
        mean_sigma = float(np.mean(sigma))
        out.append(
            {
                "diagnostic": group_name,
                "group": group,
                "points": int(len(selected)),
                f"{baseline_label}_component_rmse": float(base_component),
                f"{candidate_label}_component_rmse": float(cand_component),
                f"{baseline_label}_vector_rmse": float(np.sqrt(np.mean(base_vec**2))),
                f"{candidate_label}_vector_rmse": float(np.sqrt(np.mean(cand_vec**2))),
                "delta_vector_rmse_candidate_minus_baseline": float(np.sqrt(np.mean(cand_vec**2)) - np.sqrt(np.mean(base_vec**2))),
                "candidate_mean_vector_error": float(np.mean(cand_vec)),
                "candidate_p95_vector_error": float(np.percentile(cand_vec, 95.0)),
                "candidate_max_vector_error": float(np.max(cand_vec)),
                "mean_emaddc_sigma": mean_sigma,
                "candidate_component_over_emaddc": float(cand_component / mean_sigma) if mean_sigma else None,
                "candidate_excess_component_after_emaddc": float(math.sqrt(max(cand_component * cand_component - mean_sigma * mean_sigma, 0.0))),
                "candidate_wins": int(np.sum(cand_vec < base_vec - 1e-12)),
                "candidate_losses": int(np.sum(cand_vec > base_vec + 1e-12)),
                "ties": int(np.sum(np.abs(cand_vec - base_vec) <= 1e-12)),
            }
        )
    return out


def _overall_stack(rows: list[dict[str, Any]], baseline_label: str, candidate_label: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for label in [baseline_label, candidate_label]:
        u = np.asarray([_to_float(row, f"{label}_u_error") for row in rows], dtype=np.float64)
        v = np.asarray([_to_float(row, f"{label}_v_error") for row in rows], dtype=np.float64)
        sigma = np.asarray([_to_float(row, "sigma_emaddc_mps", 2.8) for row in rows], dtype=np.float64)
        component = float(np.sqrt(0.5 * np.mean(u**2 + v**2)))
        obs_sigma_rms = float(np.sqrt(np.mean(sigma**2)))
        out.append(
            {
                "method": label,
                "points": len(rows),
                "component_rmse": component,
                "emaddc_observation_sigma_rms": obs_sigma_rms,
                "non_observation_excess_component": float(math.sqrt(max(component * component - obs_sigma_rms * obs_sigma_rms, 0.0))),
                "non_observation_fraction_of_component_variance": float(max(component * component - obs_sigma_rms * obs_sigma_rms, 0.0) / max(component * component, 1e-12)),
                "vector_rmse": float(np.sqrt(np.mean(u**2 + v**2))),
                "u_bias": float(np.mean(u)),
                "v_bias": float(np.mean(v)),
            }
        )
    return out


def _source_priority_rows(
    frame_rows: list[dict[str, Any]],
    point_rows: list[dict[str, Any]],
    candidate_label: str,
) -> list[dict[str, Any]]:
    priority: dict[str, dict[str, Any]] = {}

    def ensure(source: str) -> dict[str, Any]:
        guide = LITERATURE_GUIDE[source]
        return priority.setdefault(
            source,
            {
                "source": source,
                "max_candidate_vector_rmse": 0.0,
                "max_candidate_component_over_emaddc": 0.0,
                "max_candidate_p95_vector_error": 0.0,
                "max_negative_delta": 0.0,
                "max_positive_delta": 0.0,
                "affected_points_or_holdouts": 0,
                "worst_diagnostic": "",
                "worst_group": "",
                "mechanism": guide["mechanism"],
                "recommended_fix": guide["fix"],
                "literature": guide["literature"],
            },
        )

    for row in point_rows:
        source = DIAGNOSTIC_TO_SOURCE.get(str(row.get("diagnostic", "")), "representation_error")
        item = ensure(source)
        cand_rmse = _to_float(row, f"{candidate_label}_vector_rmse")
        comp_over = _to_float(row, "candidate_component_over_emaddc")
        p95 = _to_float(row, "candidate_p95_vector_error")
        delta = _to_float(row, "delta_vector_rmse_candidate_minus_baseline")
        points = _to_int(row, "points")
        if cand_rmse > _to_float(item, "max_candidate_vector_rmse"):
            item["max_candidate_vector_rmse"] = cand_rmse
            item["worst_diagnostic"] = row.get("diagnostic", "")
            item["worst_group"] = row.get("group", "")
        item["max_candidate_component_over_emaddc"] = max(_to_float(item, "max_candidate_component_over_emaddc"), comp_over)
        item["max_candidate_p95_vector_error"] = max(_to_float(item, "max_candidate_p95_vector_error"), p95)
        item["max_negative_delta"] = min(_to_float(item, "max_negative_delta"), delta)
        item["max_positive_delta"] = max(_to_float(item, "max_positive_delta"), delta)
        item["affected_points_or_holdouts"] = max(_to_int(item, "affected_points_or_holdouts"), points)

    for row in frame_rows:
        source = DIAGNOSTIC_TO_SOURCE.get(str(row.get("diagnostic", "")), "representation_error")
        item = ensure(source)
        cand_rmse = _to_float(row, f"{candidate_label}_weighted_vector_rmse")
        delta = _to_float(row, "delta_candidate_minus_baseline")
        holdout_points = _to_int(row, "holdout_points")
        if cand_rmse > _to_float(item, "max_candidate_vector_rmse"):
            item["max_candidate_vector_rmse"] = cand_rmse
            item["worst_diagnostic"] = row.get("diagnostic", "")
            item["worst_group"] = row.get("group", "")
        item["max_negative_delta"] = min(_to_float(item, "max_negative_delta"), delta)
        item["max_positive_delta"] = max(_to_float(item, "max_positive_delta"), delta)
        item["affected_points_or_holdouts"] = max(_to_int(item, "affected_points_or_holdouts"), holdout_points)

    rows = list(priority.values())
    for row in rows:
        # Prioritize large residuals first, then categories where adaptive v3 made
        # things worse, then broader support.
        row["priority_score"] = (
            _to_float(row, "max_candidate_vector_rmse")
            + 2.0 * max(0.0, _to_float(row, "max_positive_delta"))
            + 0.05 * _to_int(row, "affected_points_or_holdouts")
        )
    return sorted(rows, key=lambda row: _to_float(row, "priority_score"), reverse=True)


def _action_plan_rows(priority_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    actions = {
        "vertical_structure": [
            "Add height-bin-specific localization candidates, e.g. high-level 8:4 vs 10:5 vs vertical sigma 0.75/1.0.",
            "Keep cross-layer smoothing weak when vertical_speed_gap or recon_vertical_jump is high.",
            "Report 9-12 km and 12 km+ as separate official strata.",
        ],
        "localization": [
            "Replace frame-only kernel choice with point/regime-aware kernel choice.",
            "Use support-aware gating: narrow near dense current anchors, wider when current support is sparse but context is fresh.",
            "Add a tail-risk guard that avoids kernel choices increasing P95/P99.",
        ],
        "sparse_support": [
            "Add nearest-current-distance and nearest-current-count into adaptive gating.",
            "Create low-support stratum and do not mix it with dense interpolation cases.",
            "Allow CMA/GFS weak background only in low-support, low-rapid-change bins.",
        ],
        "temporal_weighting": [
            "Calibrate context-time decay with holdout departures by time-conf bins.",
            "Compare powers 1.0/1.5/2.0 and half-life alternatives under the same strict holdout frames.",
            "Add stale-context guard when role gap is high.",
        ],
        "role_conflict": [
            "Fit role-conflict threshold by altitude/support instead of one global threshold.",
            "Do not remove context aggressively when current support is one point or far from holdout.",
            "Track role-conflict at holdout voxels as a formal diagnostic.",
        ],
        "representation_error": [
            "Add representativeness sigma to the paper-aligned table.",
            "Compare point verification with neighborhood verification within 1-2 voxels.",
            "Separate strong-wind and high-gradient cases from ordinary wind cases.",
        ],
        "tail_qc": [
            "Build a top-tail audit table for P95/P99/max points.",
            "Use robust auxiliary metrics such as median, P90, and trimmed RMSE.",
            "Do not optimize default policy on max error alone; use it for guardrails.",
        ],
        "observation_error": [
            "Keep de Haan and EMADDC as priors only.",
            "Never reinterpret local consistency sigma as aircraft measurement error.",
            "Use literature sigma for normalized departure reporting.",
        ],
    }
    rows: list[dict[str, Any]] = []
    for item in priority_rows:
        source = str(item["source"])
        for rank, action in enumerate(actions.get(source, []), start=1):
            rows.append(
                {
                    "source": source,
                    "rank": rank,
                    "action": action,
                    "worst_diagnostic": item.get("worst_diagnostic", ""),
                    "worst_group": item.get("worst_group", ""),
                    "literature": item.get("literature", ""),
                }
            )
    return rows


def _top_tail_rows(
    points: list[dict[str, Any]],
    baseline_label: str,
    candidate_label: str,
    top_n: int,
) -> list[dict[str, Any]]:
    rows = sorted(points, key=lambda row: _to_float(row, f"{candidate_label}_vector_error"), reverse=True)[: max(1, top_n)]
    out: list[dict[str, Any]] = []
    for row in rows:
        source_guess = "tail_qc"
        if str(row.get("altitude_bin")) in {"9-12km", "12km+"}:
            source_guess = "vertical_structure"
        if str(row.get("nearest_current_count_bin")) in {"count_0", "count_1"} or str(row.get("nearest_distance_bin")) in {"dist_3_6", "dist_ge6"}:
            source_guess = "sparse_support"
        if str(row.get("role_conflict_at_point_bin")) == "role_conflict" or str(row.get("nearest_role_gap_bin")) in {"gap_15_30", "gap_ge30"}:
            source_guess = "role_conflict"
        out.append(
            {
                "time_str": row["time_str"],
                "z": row["z"],
                "y": row["y"],
                "x": row["x"],
                "altitude_bin": row["altitude_bin"],
                "truth_speed_bin": row["truth_speed_bin"],
                f"{baseline_label}_vector_error": row[f"{baseline_label}_vector_error"],
                f"{candidate_label}_vector_error": row[f"{candidate_label}_vector_error"],
                "delta_candidate_minus_baseline": row["delta_vector_error_candidate_minus_baseline"],
                "nearest_distance_bin": row["nearest_distance_bin"],
                "nearest_train_source_role": row["nearest_train_source_role"],
                "nearest_current_count_bin": row["nearest_current_count_bin"],
                "nearest_role_gap_bin": row["nearest_role_gap_bin"],
                "context_time_conf_bin": row["context_time_conf_bin"],
                "vertical_speed_gap_bin": row["vertical_speed_gap_bin"],
                "qc_review_bin": row["qc_review_bin"],
                "primary_suspected_source": source_guess,
            }
        )
    return out


def _write_md(
    path: Path,
    *,
    stack_rows: list[dict[str, Any]],
    frame_rows: list[dict[str, Any]],
    point_rows: list[dict[str, Any]],
    priority_rows: list[dict[str, Any]],
    action_rows: list[dict[str, Any]],
    tail_rows: list[dict[str, Any]],
    baseline_label: str,
    candidate_label: str,
) -> None:
    lines = [
        "# Stage4 Error Source Decomposition",
        "",
        "Scope: strict aircraft holdout only. Departures are `reconstruction - withheld aircraft wind`.",
        "",
        "## Candidate vs Baseline",
        "",
    ]
    if len(stack_rows) >= 2:
        base = stack_rows[0]
        cand = stack_rows[1]
        delta = float(cand["vector_rmse"]) - float(base["vector_rmse"])
        pct = 100.0 * delta / max(float(base["vector_rmse"]), 1e-12)
        if delta < 0.0:
            verdict = f"improves vector RMSE by {-delta:.6f} m/s ({-pct:.2f}%)"
        elif delta > 0.0:
            verdict = f"worsens vector RMSE by {delta:.6f} m/s ({pct:.2f}%)"
        else:
            verdict = "leaves vector RMSE unchanged"
        lines.append(
            f"`{candidate_label}` {verdict}: {float(base['vector_rmse']):.6f} -> "
            f"{float(cand['vector_rmse']):.6f} m/s. "
            "The extreme tail remains the main unresolved issue."
        )
    lines.extend(
        [
            "",
            "## Error Stack",
            "",
            "| method | points | component RMSE | EMADDC obs sigma RMS | non-observation excess | excess variance fraction | vector RMSE | u bias | v bias |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in stack_rows:
        lines.append(
            f"| `{row['method']}` | {row['points']} | {row['component_rmse']:.6f} | "
            f"{row['emaddc_observation_sigma_rms']:.6f} | {row['non_observation_excess_component']:.6f} | "
            f"{row['non_observation_fraction_of_component_variance']:.6f} | {row['vector_rmse']:.6f} | "
            f"{row['u_bias']:.6f} | {row['v_bias']:.6f} |"
        )
    lines.extend(
        [
            "",
            "Interpretation: EMADDC/de Haan explain the aircraft-observation part. The much larger residual is reconstruction, representativeness, temporal, localization, and sparse-support error.",
            "",
            "## Source Priority",
            "",
            "| rank | source | priority score | worst diagnostic | worst group | max candidate RMSE | max worsening | affected points/holdouts | recommended fix |",
            "| ---: | --- | ---: | --- | --- | ---: | ---: | ---: | --- |",
        ]
    )
    for rank, row in enumerate(priority_rows, start=1):
        lines.append(
            f"| {rank} | `{row['source']}` | {float(row['priority_score']):.6f} | "
            f"`{row['worst_diagnostic']}` | `{row['worst_group']}` | "
            f"{float(row['max_candidate_vector_rmse']):.6f} | {float(row['max_positive_delta']):.6f} | "
            f"{int(row['affected_points_or_holdouts'])} | {row['recommended_fix']} |"
        )
    lines.extend(
        [
            "",
            "## Stepwise Error Sources And Fixes",
            "",
            "| source | mechanism | first fixes | literature |",
            "| --- | --- | --- | --- |",
        ]
    )
    seen_sources: set[str] = set()
    for row in priority_rows:
        source = str(row["source"])
        if source in seen_sources:
            continue
        seen_sources.add(source)
        guide = LITERATURE_GUIDE[source]
        lines.append(f"| `{source}` | {guide['mechanism']} | {guide['fix']} | {guide['literature']} |")
    lines.extend(
        [
            "",
            "## Action Plan",
            "",
            "| source | rank | action | tied diagnostic | tied group |",
            "| --- | ---: | --- | --- | --- |",
        ]
    )
    for row in action_rows:
        lines.append(
            f"| `{row['source']}` | {row['rank']} | {row['action']} | "
            f"`{row['worst_diagnostic']}` | `{row['worst_group']}` |"
        )
    lines.extend(
        [
            "",
            "## Extreme Tail Audit",
            "",
            "| time | z/y/x | altitude | truth speed | baseline error | candidate error | delta | nearest/source/current | role gap | vertical gap | suspected source |",
            "| --- | --- | --- | --- | ---: | ---: | ---: | --- | --- | --- | --- |",
        ]
    )
    for row in tail_rows:
        lines.append(
            f"| `{row['time_str']}` | `{row['z']}/{row['y']}/{row['x']}` | `{row['altitude_bin']}` | "
            f"`{row['truth_speed_bin']}` | {float(row[f'{baseline_label}_vector_error']):.6f} | "
            f"{float(row[f'{candidate_label}_vector_error']):.6f} | {float(row['delta_candidate_minus_baseline']):.6f} | "
            f"`{row['nearest_distance_bin']}/{row['nearest_train_source_role']}/{row['nearest_current_count_bin']}` | "
            f"`{row['nearest_role_gap_bin']}` | `{row['vertical_speed_gap_bin']}` | `{row['primary_suspected_source']}` |"
        )
    lines.extend(
        [
            "",
            "## Top Frame-Level Diagnostics",
            "",
            "| diagnostic | group | frames | holdout points | baseline wRMSE | candidate wRMSE | delta | wins/losses/ties |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for row in frame_rows:
        lines.append(
            f"| `{row['diagnostic']}` | `{row['group']}` | {row['frames']} | {row['holdout_points']} | "
            f"{row[f'{baseline_label}_weighted_vector_rmse']:.6f} | {row[f'{candidate_label}_weighted_vector_rmse']:.6f} | "
            f"{row['delta_candidate_minus_baseline']:.6f} | {row['candidate_wins']}/{row['candidate_losses']}/{row['ties']} |"
        )
    lines.extend(
        [
            "",
            "## Top Point-Level Diagnostics",
            "",
            "| diagnostic | group | points | baseline vector RMSE | candidate vector RMSE | delta | cand comp/EMADDC | excess comp | cand p95 | cand max | wins/losses/ties |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for row in point_rows:
        lines.append(
            f"| `{row['diagnostic']}` | `{row['group']}` | {row['points']} | "
            f"{row[f'{baseline_label}_vector_rmse']:.6f} | {row[f'{candidate_label}_vector_rmse']:.6f} | "
            f"{row['delta_vector_rmse_candidate_minus_baseline']:.6f} | {row['candidate_component_over_emaddc']:.6f} | "
            f"{row['candidate_excess_component_after_emaddc']:.6f} | {row['candidate_p95_vector_error']:.6f} | "
            f"{row['candidate_max_vector_error']:.6f} | {row['candidate_wins']}/{row['candidate_losses']}/{row['ties']} |"
        )
    lines.extend(
        [
            "",
            "## Literature Mapping",
            "",
            "- Aircraft observation error: de Haan (2016) triple collocation and EMADDC (2025).",
            "- Representation error: Janjic et al. (2018) terminology for observation/operator/sampling/representativeness components.",
            "- Localization: Gaspari and Cohn (1999), DART localization, and LETKF/local DA literature.",
            "- Time handling: ECMWF 4D-Var treats observations inside an assimilation time window with an observation operator and background constraints.",
            "- Variational wind retrieval: PyDDA frames wind retrieval as an optimization over observation, background, smoothness, and physical constraints.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Decompose Stage4 pairwise error sources.")
    parser.add_argument("--baseline-csv", type=Path, required=True)
    parser.add_argument("--candidate-csv", type=Path, required=True)
    parser.add_argument("--baseline-point-csv", type=Path, required=True)
    parser.add_argument("--candidate-point-csv", type=Path, required=True)
    parser.add_argument("--baseline-label", default="baseline")
    parser.add_argument("--candidate-label", default="candidate")
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--out-prefix", default="stage4_error_source_decomposition")
    parser.add_argument("--top-tail-n", type=int, default=20)
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    frames = _merge_frames(_read_csv(args.baseline_csv), _read_csv(args.candidate_csv), args.baseline_label, args.candidate_label)
    points = _merge_points(_read_csv(args.baseline_point_csv), _read_csv(args.candidate_point_csv), args.baseline_label, args.candidate_label)

    frame_specs: list[tuple[str, Callable[[dict[str, Any]], str]]] = [
        ("adaptive_selected_kernel", lambda row: str(row["adaptive_selected_kernel"])),
        ("adaptive_current_support", lambda row: _bin(_to_float(row, "adaptive_current_support"), [(None, 3, "support_lt3"), (3, 9, "support_3_8"), (9, 30, "support_9_29"), (30, None, "support_ge30")])),
        ("adaptive_context_time_conf_mean", lambda row: _context_time_bin(_to_float(row, "adaptive_context_time_conf_mean"))),
        ("adaptive_role_gap_mps", lambda row: _role_gap_bin(_to_float(row, "adaptive_role_gap_mps"))),
        ("local_consistency_conf_mean", lambda row: _bin(_to_float(row, "local_consistency_conf_mean"), [(None, 0.95, "consistency_lt0_95"), (0.95, 0.98, "consistency_0_95_0_98"), (0.98, 0.995, "consistency_0_98_0_995"), (0.995, None, "consistency_ge0_995")])),
        ("role_conflict_fraction_of_overlap", lambda row: _bin(_to_float(row, "role_conflict_fraction_of_overlap"), [(None, 0.1, "rolefrac_lt0_1"), (0.1, 0.3, "rolefrac_0_1_0_3"), (0.3, 0.6, "rolefrac_0_3_0_6"), (0.6, None, "rolefrac_ge0_6")])),
        ("vertical_context_mismatch_voxels", lambda row: _bin(_to_float(row, "vertical_context_mismatch_candidate_voxels"), [(None, 1000, "vmismatch_lt1k"), (1000, 3000, "vmismatch_1k_3k"), (3000, 6000, "vmismatch_3k_6k"), (6000, None, "vmismatch_ge6k")])),
    ]
    point_specs: list[tuple[str, Callable[[dict[str, Any]], str]]] = [
        ("altitude_bin", lambda row: str(row["altitude_bin"])),
        ("truth_speed_bin", lambda row: str(row["truth_speed_bin"])),
        ("adaptive_selected_kernel", lambda row: str(row["adaptive_selected_kernel"])),
        ("nearest_distance_bin", lambda row: str(row["nearest_distance_bin"])),
        ("nearest_train_source_role", lambda row: str(row["nearest_train_source_role"])),
        ("nearest_current_count_bin", lambda row: str(row["nearest_current_count_bin"])),
        ("nearest_context_count_bin", lambda row: str(row["nearest_context_count_bin"])),
        ("nearest_role_gap_bin", lambda row: str(row["nearest_role_gap_bin"])),
        ("role_conflict_at_point", lambda row: str(row["role_conflict_at_point_bin"])),
        ("context_time_conf_bin", lambda row: str(row["context_time_conf_bin"])),
        ("role_conflict_component_gap_bin", lambda row: str(row["role_conflict_component_gap_bin"])),
        ("recon_confidence_bin", lambda row: str(row["recon_confidence_bin"])),
        ("recon_vertical_jump_bin", lambda row: str(row["recon_vertical_jump_bin"])),
        ("vertical_speed_gap_bin", lambda row: str(row["vertical_speed_gap_bin"])),
        ("qc_review_bin", lambda row: str(row["qc_review_bin"])),
    ]

    frame_decomp = [
        item
        for name, fn in frame_specs
        for item in _frame_metric_rows(frames, name, fn, args.baseline_label, args.candidate_label)
    ]
    point_decomp = [
        item
        for name, fn in point_specs
        for item in _point_metric_rows(points, name, fn, args.baseline_label, args.candidate_label)
    ]
    stack = _overall_stack(points, args.baseline_label, args.candidate_label)
    priority = _source_priority_rows(frame_decomp, point_decomp, args.candidate_label)
    action_plan = _action_plan_rows(priority)
    tail = _top_tail_rows(points, args.baseline_label, args.candidate_label, top_n=int(args.top_tail_n))

    _write_csv(args.out_dir / f"{args.out_prefix}_frame_groups.csv", frame_decomp)
    _write_csv(args.out_dir / f"{args.out_prefix}_point_groups.csv", point_decomp)
    _write_csv(args.out_dir / f"{args.out_prefix}_error_stack.csv", stack)
    _write_csv(args.out_dir / f"{args.out_prefix}_source_priority.csv", priority)
    _write_csv(args.out_dir / f"{args.out_prefix}_action_plan.csv", action_plan)
    _write_csv(args.out_dir / f"{args.out_prefix}_tail_audit.csv", tail)
    _write_md(
        args.out_dir / f"{args.out_prefix}.md",
        stack_rows=stack,
        frame_rows=frame_decomp,
        point_rows=point_decomp,
        priority_rows=priority,
        action_rows=action_plan,
        tail_rows=tail,
        baseline_label=args.baseline_label,
        candidate_label=args.candidate_label,
    )
    print(args.out_dir / f"{args.out_prefix}.md")


if __name__ == "__main__":
    main()
