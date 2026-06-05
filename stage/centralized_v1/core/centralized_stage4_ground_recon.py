"""Centralized v1 Stage4: strict hold-out ground wind reconstruction.

Stage4 is the first stage that reconstructs a 3D wind field. It consumes the
Stage2 all-in observation package and the Stage3 Ground Center payload, removes
the selected hold-out wind labels before fusion, and evaluates only on those
withheld labels.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import numpy as np

ROOT_DIR = Path(__file__).resolve().parents[3]
STAGE_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
if str(STAGE_DIR) not in sys.path:
    sys.path.insert(0, str(STAGE_DIR))

from stage.centralized_v1.configs.centralized_v1_config import (  # noqa: E402
    ALT_MIN,
    BLINDZONE_IDW_RADIUS_XY,
    BLINDZONE_IDW_RADIUS_Z,
    DELTA_ALT,
    LAT_MAX,
    LAT_MIN,
    LON_MAX,
    LON_MIN,
    REGENERATED_STAGE2_OUTPUT_DIR,
    STAGE3_OUTPUT_DIR,
)
from stage.centralized_v1.configs.centralized_v1_contract import (  # noqa: E402
    C2_CLOUD_2D,
    C2_CONTEXT_MOTION_RECORDS,
    C2_CONTEXT_WIND_RECORDS,
    C2_GRID_SHAPE,
    C2_LOC_RECORDS,
    C2_MOTION_RECORDS,
    C2_MULTIMODAL_META_JSON,
    C2_TIME_STR,
    C2_TIMESTAMP_UTC,
    C2_WIND_RECORDS,
    C4_BLINDZONE_MASK,
    C4_C_JOINT_3D,
    C4_C_SPACE_3D,
    C4_C_TIME_3D,
    C4_CLOUD_2D,
    C4_DISPLAY_CONF,
    C4_DISPLAY_FILL_DIAGNOSTICS_JSON,
    C4_DISPLAY_MASK,
    C4_DISPLAY_SOURCE,
    C4_DISPLAY_U,
    C4_DISPLAY_V,
    C4_POINT_EVAL_JSON,
    C4_RECON_CONF,
    C4_RECON_MASK,
    C4_RECON_U,
    C4_RECON_V,
)

STRICT_STAGE4_OUTPUT_DIR = Path("/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_center_strict")
EFFECTIVE_CONF_THRESHOLD = 1e-6
LOCALIZATION_KERNELS = {"gaussian", "gaspari_cohn"}
LOCALIZATION_POLICIES = {
    "fixed",
    "diagnostic_adaptive",
    "diagnostic_adaptive_v3",
    "diagnostic_adaptive_regime_v4",
    "support_role_height_aware",
}
VERTICAL_LOCALIZATION_POLICIES = {"fixed", "support_adaptive"}
CONFIDENCE_MODES = {"diagnostic_only", "diagnostic_weighted", "obs_error_weighted"}
PHYSICS_CONSTRAINT_MODES = {"proxy", "pydda_3dvar_proxy"}
ROLE_CONFLICT_MODES = {"off", "current_priority", "current_priority_adaptive"}
VERTICAL_RISK_MODES = {"off", "preserve_strong_layers"}
CMA_FUSION_MODES = {"off", "cma_proxy_background", "cma_reanalysis_background", "cma_pseudo_observation"}
CMA_CONFIDENCE_SOURCES = {"dense", "coverage_conf", "temporal_conf", "coverage_temporal_conf"}
CMA_PSEUDO_SOURCES = {"reanalysis", "proxy"}
CMA_QC_GATING_MODES = {"off", "temporal_change", "strict_temporal"}
CMA_BACKGROUND_WEIGHT_MODES = {"fixed", "diagnostic_gated", "sparse_temporal_gated"}
DISPLAY_FILL_MODES = {"off", "low_conf_background"}
DISPLAY_FILL_SOURCES = {"cma_reanalysis", "cma_proxy"}
CMA_RAPID_CHANGE_QC_FACTOR = np.float32(0.35)
POINT_HIGH_ERROR_THRESHOLD_MPS = 30.0
POINT_STRONG_WIND_THRESHOLD_MPS = 90.0
POINT_EXTREME_WIND_THRESHOLD_MPS = 120.0
POINT_REMOTE_SUPPORT_THRESHOLD_VOX = 8.0
STRONG_WIND_DIAGNOSTIC_THRESHOLD_MPS = 60.0
RAPID_VERTICAL_JUMP_DIAGNOSTIC_THRESHOLD_MPS = 25.0
VERTICAL_OVERSMOOTH_JUMP_THRESHOLD_MPS = 2.0

DEFAULT_QC_CALIBRATION = {
    "calibration_role": "documented_default_until_larger_strict_validation",
    "density_count_scale": 3.0,
    "density_min": 0.10,
    "density_power": 1.0,
    "quality_min": 0.10,
    "speed_soft_limit_mps": 90.0,
    "speed_hard_limit_mps": 120.0,
    "speed_flag_factor": 0.35,
    "speed_hard_factor": 0.50,
    "speed_soft_factor": 0.80,
    "time_spread_halflife_minutes": 180.0,
    "local_consistency_min": 0.25,
    "role_conflict_adaptive_height_threshold_gain": 0.35,
    "role_conflict_adaptive_sparse_current_threshold_gain": 0.25,
    "role_conflict_adaptive_stale_context_threshold_reduction": 0.30,
    "role_conflict_adaptive_dense_overlap_threshold_reduction": 0.15,
    "role_conflict_adaptive_min_threshold_factor": 0.50,
    "role_conflict_adaptive_max_threshold_factor": 2.00,
    "role_conflict_adaptive_min_threshold_mps": 3.0,
    "role_conflict_adaptive_sparse_current_factor_gain": 0.20,
    "role_conflict_adaptive_height_factor_gain": 0.12,
    "role_conflict_adaptive_stale_context_factor_reduction": 0.50,
    "role_conflict_adaptive_current_density_factor_reduction": 0.15,
    "role_conflict_adaptive_min_context_factor": 0.05,
    "role_conflict_adaptive_max_context_factor": 0.80,
    "vertical_risk_gradient_preserve_weight": 0.12,
    "vertical_risk_context_mismatch_damping": 0.35,
    "vertical_localization_min_sigma_factor": 0.55,
    "vertical_localization_max_sigma_factor": 1.25,
    "vertical_localization_strong_speed_mps": 60.0,
    "vertical_localization_high_altitude_m": 9000.0,
    "vertical_localization_dense_count": 6.0,
    "vertical_localization_sparse_count": 1.0,
    "vertical_localization_stale_context_time_conf": 0.28,
    "vertical_localization_strong_speed_factor": 0.75,
    "vertical_localization_high_altitude_factor": 0.85,
    "vertical_localization_dense_current_factor": 0.85,
    "vertical_localization_stale_context_factor": 0.70,
    "vertical_localization_sparse_weak_factor": 1.10,
    "obs_error_sigma_floor_mps": 1.0,
    "obs_error_sigma_default_mps": 8.0,
    "obs_error_reference_sigma_mps": 8.0,
    "obs_error_weight_min": 0.05,
    "obs_error_weight_max": 4.0,
    "obs_error_use_diagnostic_factor": 1.0,
    "obs_error_altitude_bin_edges_m": [0.0, 3000.0, 6000.0, 9000.0, 12000.0, 15000.0, 20000.0],
    "obs_error_speed_bin_edges_mps": [0.0, 15.0, 30.0, 45.0, 60.0, 90.0, 120.0, 200.0],
    "obs_error_density_bin_edges": [0.0, 1.0, 3.0, 6.0, 12.0, 999999.0],
    "obs_error_consistency_bin_edges": [0.0, 0.40, 0.65, 0.85, 1.10],
    "obs_error_bin_sigma_mps": {},
    "obs_error_altitude_bin_sigma_mps": {},
    "obs_error_speed_bin_sigma_mps": {},
    "obs_error_density_bin_sigma_mps": {},
    "obs_error_consistency_bin_sigma_mps": {},
    "adaptive_localization_low_current_support": 2.0,
    "adaptive_localization_high_current_support": 8.0,
    "adaptive_localization_high_context_support": 300.0,
    "adaptive_localization_low_context_time_conf": 0.28,
    "adaptive_localization_high_context_time_conf": 0.45,
    "adaptive_localization_low_obs_error_weight": 0.90,
    "adaptive_localization_high_role_conflict_ratio": 0.08,
    "adaptive_localization_high_vertical_mismatch_ratio": 0.006,
    "adaptive_localization_v3_guard_max_current_support": 8.0,
    "adaptive_localization_v3_guard_max_context_time_conf": 0.57,
    "adaptive_localization_v3_guard_min_local_consistency": 0.98,
    "adaptive_localization_v3_sparse_guard_max_current_support": 2.0,
    "adaptive_localization_v3_sparse_guard_max_context_time_conf": 0.52,
    "adaptive_localization_v3_sparse_guard_min_local_consistency": 0.985,
    "adaptive_localization_srha_very_sparse_current_support": 1.0,
    "adaptive_localization_srha_sparse_current_support": 2.0,
    "adaptive_localization_srha_dense_current_support": 10.0,
    "adaptive_localization_srha_high_altitude_m": 12000.0,
    "adaptive_localization_srha_high_altitude_fraction": 0.22,
    "adaptive_localization_srha_high_speed_mps": 60.0,
    "adaptive_localization_srha_high_speed_fraction": 0.12,
    "adaptive_localization_srha_fresh_context_time_conf": 0.50,
    "adaptive_localization_srha_stale_context_time_conf": 0.36,
    "adaptive_localization_srha_stable_local_consistency": 0.975,
    "adaptive_localization_srha_unstable_local_consistency": 0.93,
    "adaptive_localization_srha_moderate_role_gap_mps": 18.0,
    "adaptive_localization_srha_high_role_gap_mps": 30.0,
    "adaptive_localization_srha_tight_radius_z": 1.0,
    "adaptive_localization_srha_tight_sigma_z": 0.75,
    "adaptive_localization_srha_horizontal_min_sigma_factor": 0.65,
    "adaptive_localization_srha_horizontal_max_sigma_factor": 1.15,
    "adaptive_localization_srha_horizontal_high_altitude_factor": 0.78,
    "adaptive_localization_srha_horizontal_high_speed_factor": 0.85,
    "adaptive_localization_srha_horizontal_role_gap_factor": 0.80,
    "adaptive_localization_srha_horizontal_stale_context_factor": 0.75,
    "adaptive_localization_srha_horizontal_dense_current_factor": 0.90,
    "adaptive_localization_srha_horizontal_sparse_fresh_factor": 1.10,
    "adaptive_localization_srha_vertical_role_gap_factor": 0.85,
    "adaptive_localization_srha_vertical_stale_context_factor": 0.85,
    "cma_gated_sparse_current_norm_threshold": 0.18,
    "cma_gated_min_effective_conf": 0.02,
    "cma_strict_min_temporal_conf": 0.55,
    "cma_strict_max_temporal_change_mps": 8.0,
    "references": [
        "https://amt.copernicus.org/articles/18/3341/2025/",
        "https://amt.copernicus.org/articles/9/4141/2016/",
        "https://wmo.int/aircraft-based-observations-programme",
        "https://openradarscience.org/PyDDA/",
        "https://doi.org/10.1109/34.56205",
    ],
}


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_stage2_npz(path: Path) -> dict[str, Any]:
    with np.load(path, allow_pickle=True) as z:
        return {k: z[k] for k in z.files}


def _records(arr: np.ndarray | None) -> list[dict[str, Any]]:
    if arr is None or len(arr) == 0:
        return []
    return [dict(x) for x in arr.tolist()]


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _safe_int(value: Any, default: int = -1) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _record_sort_key(row: dict[str, Any]) -> tuple[int, int, int, float, float]:
    return (
        _safe_int(row.get("z")),
        _safe_int(row.get("y")),
        _safe_int(row.get("x")),
        _safe_float(row.get("u")),
        _safe_float(row.get("v")),
    )


def _record_identity(row: dict[str, Any]) -> tuple[int, int, int, float, float]:
    return (
        _safe_int(row.get("z")),
        _safe_int(row.get("y")),
        _safe_int(row.get("x")),
        round(_safe_float(row.get("u")), 9),
        round(_safe_float(row.get("v")), 9),
    )


def _split_holdout(
    records: list[dict[str, Any]],
    holdout_fraction: float,
    holdout_count: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (train_records, holdout_records) with deterministic selection."""

    if not records:
        return [], []
    sorted_records = sorted(records, key=_record_sort_key)
    n_records = len(sorted_records)
    if holdout_count > 0:
        n_holdout = min(n_records, int(holdout_count))
    else:
        n_holdout = max(1, int(math.ceil(n_records * max(0.0, float(holdout_fraction)))))
        n_holdout = min(n_records, n_holdout)
    if n_holdout >= n_records:
        selected = set(range(n_records))
    else:
        selected = {int(round(v)) for v in np.linspace(0, n_records - 1, n_holdout)}
        cursor = 0
        while len(selected) < n_holdout and cursor < n_records:
            selected.add(cursor)
            cursor += 1
    holdout = [row for i, row in enumerate(sorted_records) if i in selected]
    train = [row for i, row in enumerate(sorted_records) if i not in selected]
    return train, holdout


def _active_base_weight(row: dict[str, Any], default_time_conf: float = 1.0) -> float:
    obs_conf = _safe_float(row.get("obs_conf"), 1.0)
    time_conf = _safe_float(row.get("time_conf"), default_time_conf)
    if time_conf <= 0.0 and row.get("joint_likelihood") is not None:
        return max(0.0, _safe_float(row.get("joint_likelihood"), 0.0))
    return max(0.0, obs_conf * time_conf)


def _factor_stats(values: list[float]) -> dict[str, float | int | None]:
    finite = [float(v) for v in values if math.isfinite(float(v))]
    if not finite:
        return {"count": 0, "min": None, "mean": None, "max": None}
    arr = np.asarray(finite, dtype=np.float64)
    return {"count": int(arr.size), "min": float(np.min(arr)), "mean": float(np.mean(arr)), "max": float(np.max(arr))}


def _qc_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        flag = str(row.get("qc_flags", "ok") or "ok")
        counts[flag] = counts.get(flag, 0) + 1
    return counts


def _load_qc_calibration(path: Path | None) -> dict[str, Any]:
    calibration = dict(DEFAULT_QC_CALIBRATION)
    if path:
        loaded = _load_json(path)
        if not isinstance(loaded, dict):
            raise ValueError(f"QC calibration must be a JSON object: {path}")
        calibration.update(loaded)
        calibration["calibration_path"] = str(path)
    else:
        calibration["calibration_path"] = ""
    return calibration


def _cal_float(calibration: dict[str, Any], key: str, default: float) -> float:
    return _safe_float(calibration.get(key), default)


def _speed_qc_factor(row: dict[str, Any], calibration: dict[str, Any]) -> float:
    flag = str(row.get("qc_flags", "ok") or "ok")
    speed = math.sqrt(_safe_float(row.get("u")) ** 2 + _safe_float(row.get("v")) ** 2)
    if flag != "ok":
        return float(np.clip(_cal_float(calibration, "speed_flag_factor", 0.35), 0.0, 1.0))
    if speed > _cal_float(calibration, "speed_hard_limit_mps", 120.0):
        return float(np.clip(_cal_float(calibration, "speed_hard_factor", 0.50), 0.0, 1.0))
    if speed > _cal_float(calibration, "speed_soft_limit_mps", 90.0):
        return float(np.clip(_cal_float(calibration, "speed_soft_factor", 0.80), 0.0, 1.0))
    return 1.0


def _local_consistency_factor(row: dict[str, Any], calibration: dict[str, Any]) -> float:
    mean_abs_dt = _safe_float(row.get("mean_abs_delta_time_minutes"), 0.0)
    nearest_dt = _safe_float(row.get("nearest_delta_time_minutes"), mean_abs_dt)
    spread = max(0.0, mean_abs_dt - nearest_dt)
    halflife = max(1e-6, _cal_float(calibration, "time_spread_halflife_minutes", 180.0))
    lower = float(np.clip(_cal_float(calibration, "local_consistency_min", 0.25), 0.0, 1.0))
    return float(np.clip(0.5 ** (spread / halflife), lower, 1.0))


def _diagnostic_factor_bundle(row: dict[str, Any], calibration: dict[str, Any]) -> dict[str, float]:
    density = _safe_float(row.get("density_conf_diagnostic"), 0.0)
    if density <= 0.0:
        count = _safe_float(row.get("obs_count"), _safe_float(row.get("motion_count"), 1.0))
        scale = max(1e-6, _cal_float(calibration, "density_count_scale", 3.0))
        density = 1.0 - math.exp(-max(0.0, count) / scale)
    density_power = max(0.01, _cal_float(calibration, "density_power", 1.0))
    density = float(np.clip(density**density_power, _cal_float(calibration, "density_min", 0.10), 1.0))
    quality = _safe_float(row.get("quality_conf_diagnostic"), 1.0)
    quality = float(np.clip(quality if quality > 0 else 1.0, _cal_float(calibration, "quality_min", 0.10), 1.0))
    speed_qc = _speed_qc_factor(row, calibration)
    local_consistency = _local_consistency_factor(row, calibration)
    combined = float(np.clip(density * quality * speed_qc * local_consistency, 0.0, 1.0))
    return {
        "density_conf_factor": density,
        "quality_conf_factor": quality,
        "speed_qc_conf_factor": speed_qc,
        "local_consistency_conf_factor": local_consistency,
        "combined_diagnostic_factor": combined,
    }


def _bin_label(value: float, edges: list[Any]) -> str:
    clean_edges = [_safe_float(v, 0.0) for v in edges]
    if len(clean_edges) < 2:
        return "bin0"
    number = _safe_float(value, clean_edges[0])
    for idx in range(len(clean_edges) - 1):
        if clean_edges[idx] <= number < clean_edges[idx + 1]:
            return f"bin{idx}"
    return f"bin{max(0, len(clean_edges) - 2)}"


def _obs_error_feature_labels(row: dict[str, Any], calibration: dict[str, Any]) -> dict[str, str]:
    speed = math.sqrt(_safe_float(row.get("u")) ** 2 + _safe_float(row.get("v")) ** 2)
    altitude = _safe_float(row.get("alt_meters"), ALT_MIN + max(0, _safe_int(row.get("z"), 0)) * DELTA_ALT)
    density_value = _safe_float(row.get("obs_count"), _safe_float(row.get("motion_count"), 1.0))
    if density_value <= 0.0:
        density_conf = _safe_float(row.get("density_conf_diagnostic"), 0.0)
        density_value = -math.log(max(1e-6, 1.0 - min(0.999999, density_conf))) * _cal_float(calibration, "density_count_scale", 3.0)
    consistency = _local_consistency_factor(row, calibration)
    return {
        "altitude": _bin_label(altitude, list(calibration.get("obs_error_altitude_bin_edges_m", []))),
        "speed": _bin_label(speed, list(calibration.get("obs_error_speed_bin_edges_mps", []))),
        "density": _bin_label(density_value, list(calibration.get("obs_error_density_bin_edges", []))),
        "consistency": _bin_label(consistency, list(calibration.get("obs_error_consistency_bin_edges", []))),
    }


def _obs_error_composite_key(labels: dict[str, str]) -> str:
    return (
        f"altitude={labels['altitude']}|"
        f"speed={labels['speed']}|"
        f"density={labels['density']}|"
        f"consistency={labels['consistency']}"
    )


def _sigma_from_map(mapping: Any, key: str) -> float | None:
    if not isinstance(mapping, dict):
        return None
    if key not in mapping:
        return None
    sigma = _safe_float(mapping.get(key), float("nan"))
    return sigma if math.isfinite(sigma) and sigma > 0.0 else None


def _obs_error_sigma_for_row(row: dict[str, Any], calibration: dict[str, Any]) -> tuple[float, str]:
    labels = _obs_error_feature_labels(row, calibration)
    composite_key = _obs_error_composite_key(labels)
    sigma = _sigma_from_map(calibration.get("obs_error_bin_sigma_mps"), composite_key)
    source = "composite"
    if sigma is None:
        marginal_sigmas = [
            _sigma_from_map(calibration.get("obs_error_altitude_bin_sigma_mps"), labels["altitude"]),
            _sigma_from_map(calibration.get("obs_error_speed_bin_sigma_mps"), labels["speed"]),
            _sigma_from_map(calibration.get("obs_error_density_bin_sigma_mps"), labels["density"]),
            _sigma_from_map(calibration.get("obs_error_consistency_bin_sigma_mps"), labels["consistency"]),
        ]
        valid = [value for value in marginal_sigmas if value is not None]
        if valid:
            sigma = float(np.median(np.asarray(valid, dtype=np.float64)))
            source = "marginal_median"
    if sigma is None:
        sigma = _cal_float(calibration, "obs_error_sigma_default_mps", 8.0)
        source = "default"
    floor = max(1e-6, _cal_float(calibration, "obs_error_sigma_floor_mps", 1.0))
    return max(floor, float(sigma)), source


def _obs_error_weight_bundle(row: dict[str, Any], calibration: dict[str, Any]) -> dict[str, float | str]:
    sigma, sigma_source = _obs_error_sigma_for_row(row, calibration)
    reference = max(1e-6, _cal_float(calibration, "obs_error_reference_sigma_mps", _cal_float(calibration, "obs_error_sigma_default_mps", 8.0)))
    obs_conf = float(np.clip(_safe_float(row.get("obs_conf"), 1.0), 0.0, 2.0))
    raw_weight = obs_conf * (reference / sigma) ** 2
    weight = float(
        np.clip(
            raw_weight,
            _cal_float(calibration, "obs_error_weight_min", 0.05),
            _cal_float(calibration, "obs_error_weight_max", 4.0),
        )
    )
    labels = _obs_error_feature_labels(row, calibration)
    return {
        "obs_error_sigma_vector_mps": float(sigma),
        "obs_error_weight_factor": weight,
        "obs_error_sigma_source": sigma_source,
        "obs_error_bin_key": _obs_error_composite_key(labels),
    }


def _build_wind_observations(
    train_current_wind: list[dict[str, Any]],
    context_wind: list[dict[str, Any]],
    confidence_mode: str,
    qc_calibration: dict[str, Any] | None = None,
    current_weight_boost: float = 1.0,
    context_weight_scale: float = 1.0,
    context_time_conf_power: float = 1.0,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    observations: list[dict[str, Any]] = []
    confidence_mode = str(confidence_mode)
    if confidence_mode not in CONFIDENCE_MODES:
        raise ValueError(f"Unsupported confidence_mode={confidence_mode}; choose {sorted(CONFIDENCE_MODES)}")
    calibration = qc_calibration or DEFAULT_QC_CALIBRATION
    current_weight_boost = float(max(0.0, current_weight_boost))
    context_weight_scale = float(max(0.0, context_weight_scale))
    context_time_conf_power = float(max(0.01, context_time_conf_power))
    for row in train_current_wind:
        factors = _diagnostic_factor_bundle(row, calibration)
        obs_error = _obs_error_weight_bundle(row, calibration)
        if confidence_mode == "obs_error_weighted":
            use_diag = _safe_float(calibration.get("obs_error_use_diagnostic_factor"), 1.0) > 0.0
            diagnostic_multiplier = factors["combined_diagnostic_factor"] if use_diag else 1.0
            time_conf = _safe_float(row.get("time_conf"), 1.0)
            base_weight = max(0.0, time_conf) * float(obs_error["obs_error_weight_factor"]) * diagnostic_multiplier * current_weight_boost
        else:
            diagnostic_multiplier = factors["combined_diagnostic_factor"] if confidence_mode == "diagnostic_weighted" else 1.0
            base_weight = _active_base_weight(row, default_time_conf=1.0) * diagnostic_multiplier * current_weight_boost
        observations.append(
            {
                "source_role": "current_wind_train",
                "z": _safe_int(row.get("z")),
                "y": _safe_int(row.get("y")),
                "x": _safe_int(row.get("x")),
                "u": _safe_float(row.get("u")),
                "v": _safe_float(row.get("v")),
                "base_weight": max(0.05, base_weight),
                "time_conf": 1.0,
                "obs_conf": _safe_float(row.get("obs_conf"), 1.0),
                "obs_count": _safe_float(row.get("obs_count"), 1.0),
                "alt_meters": _safe_float(row.get("alt_meters"), ALT_MIN + _safe_int(row.get("z"), 0) * DELTA_ALT),
                "qc_flags": str(row.get("qc_flags", "ok") or "ok"),
                "role_weight_multiplier": current_weight_boost,
                **factors,
                **obs_error,
            }
        )
    for row in context_wind:
        factors = _diagnostic_factor_bundle(row, calibration)
        obs_error = _obs_error_weight_bundle(row, calibration)
        if confidence_mode == "obs_error_weighted":
            use_diag = _safe_float(calibration.get("obs_error_use_diagnostic_factor"), 1.0) > 0.0
            diagnostic_multiplier = factors["combined_diagnostic_factor"] if use_diag else 1.0
        else:
            diagnostic_multiplier = factors["combined_diagnostic_factor"] if confidence_mode == "diagnostic_weighted" else 1.0
        time_conf = _safe_float(row.get("time_conf"), 0.0)
        time_power_factor = time_conf ** max(0.0, context_time_conf_power - 1.0) if time_conf > 0.0 else 0.0
        if confidence_mode == "obs_error_weighted":
            base_weight = time_conf * float(obs_error["obs_error_weight_factor"]) * diagnostic_multiplier * context_weight_scale * time_power_factor
        else:
            base_weight = _active_base_weight(row, default_time_conf=0.0) * diagnostic_multiplier * context_weight_scale * time_power_factor
        observations.append(
            {
                "source_role": "context_wind",
                "z": _safe_int(row.get("z")),
                "y": _safe_int(row.get("y")),
                "x": _safe_int(row.get("x")),
                "u": _safe_float(row.get("u")),
                "v": _safe_float(row.get("v")),
                "base_weight": max(0.0, base_weight),
                "time_conf": time_conf,
                "obs_conf": _safe_float(row.get("obs_conf"), 1.0),
                "obs_count": _safe_float(row.get("obs_count"), 1.0),
                "alt_meters": _safe_float(row.get("alt_meters"), ALT_MIN + _safe_int(row.get("z"), 0) * DELTA_ALT),
                "qc_flags": str(row.get("qc_flags", "ok") or "ok"),
                "role_weight_multiplier": context_weight_scale,
                "context_time_conf_power": context_time_conf_power,
                **factors,
                **obs_error,
            }
        )
    filtered = [
        row
        for row in observations
        if row["base_weight"] > 0.0
        and row["z"] >= 0
        and row["y"] >= 0
        and row["x"] >= 0
        and math.isfinite(row["u"])
        and math.isfinite(row["v"])
    ]
    diagnostics = {
        "confidence_mode": confidence_mode,
        "density_conf_factor_stats": _factor_stats([row["density_conf_factor"] for row in filtered]),
        "speed_qc_conf_stats": _factor_stats([row["speed_qc_conf_factor"] for row in filtered]),
        "local_consistency_conf_stats": _factor_stats([row["local_consistency_conf_factor"] for row in filtered]),
        "combined_diagnostic_factor_stats": _factor_stats([row["combined_diagnostic_factor"] for row in filtered]),
        "obs_error_sigma_vector_mps_stats": _factor_stats([row["obs_error_sigma_vector_mps"] for row in filtered]),
        "obs_error_weight_factor_stats": _factor_stats([row["obs_error_weight_factor"] for row in filtered]),
        "qc_flags_counts": _qc_counts(filtered),
        "qc_calibration": calibration,
        "current_weight_boost": float(current_weight_boost),
        "context_weight_scale": float(context_weight_scale),
        "context_time_conf_power": float(context_time_conf_power),
    }
    return filtered, diagnostics


def _gaspari_cohn_1d(r: np.ndarray) -> np.ndarray:
    q = np.abs(r).astype(np.float32)
    out = np.zeros_like(q, dtype=np.float32)
    first = q <= 1.0
    q1 = q[first]
    out[first] = (((-0.25 * q1 + 0.5) * q1 + 0.625) * q1 - (5.0 / 3.0)) * q1 * q1 + 1.0
    second = (q > 1.0) & (q <= 2.0)
    q2 = q[second]
    out[second] = ((((q2 / 12.0 - 0.5) * q2 + 0.625) * q2 + (5.0 / 3.0)) * q2 - 5.0) * q2 + 4.0 - (2.0 / (3.0 * q2))
    return np.clip(out, 0.0, 1.0).astype(np.float32)


def _localization_weights(
    dx: np.ndarray,
    dy: np.ndarray,
    dz: np.ndarray,
    sigma_xy: float,
    sigma_z: float,
    kernel: str,
) -> np.ndarray:
    if kernel == "gaussian":
        return np.exp(-0.5 * ((dy / sigma_xy) ** 2 + (dx / sigma_xy) ** 2 + (dz / sigma_z) ** 2)).astype(np.float32)
    if kernel == "gaspari_cohn":
        horizontal = np.sqrt((dx / sigma_xy) ** 2 + (dy / sigma_xy) ** 2, dtype=np.float32)
        vertical = np.abs(dz / sigma_z).astype(np.float32)
        return (_gaspari_cohn_1d(horizontal) * _gaspari_cohn_1d(vertical)).astype(np.float32)
    raise ValueError(f"Unsupported localization kernel: {kernel}")


def _dynamic_vertical_localization(
    row: dict[str, Any],
    *,
    base_radius_z: int,
    base_sigma_z: float,
    policy: str,
    qc_calibration: dict[str, Any],
    localization_context: dict[str, Any] | None = None,
) -> dict[str, float | int | str]:
    policy = str(policy)
    if policy not in VERTICAL_LOCALIZATION_POLICIES:
        raise ValueError(f"Unsupported vertical_localization_policy={policy}; choose {sorted(VERTICAL_LOCALIZATION_POLICIES)}")
    base_radius_z = max(0, int(base_radius_z))
    base_sigma_z = max(1e-6, float(base_sigma_z))
    if policy == "fixed" or base_radius_z == 0:
        return {
            "radius_z": base_radius_z,
            "sigma_z": base_sigma_z,
            "sigma_factor": 1.0,
            "reason": "fixed",
        }

    speed = math.sqrt(_safe_float(row.get("u")) ** 2 + _safe_float(row.get("v")) ** 2)
    altitude = _safe_float(row.get("alt_meters"), ALT_MIN + max(0, _safe_int(row.get("z"), 0)) * DELTA_ALT)
    obs_count = _safe_float(row.get("obs_count"), 1.0)
    time_conf = _safe_float(row.get("time_conf"), 1.0)
    source_role = str(row.get("source_role"))
    factor = 1.0
    reasons: list[str] = []

    if speed >= _cal_float(qc_calibration, "vertical_localization_strong_speed_mps", 60.0):
        factor *= _cal_float(qc_calibration, "vertical_localization_strong_speed_factor", 0.75)
        reasons.append("strong_speed")
    if altitude >= _cal_float(qc_calibration, "vertical_localization_high_altitude_m", 9000.0):
        factor *= _cal_float(qc_calibration, "vertical_localization_high_altitude_factor", 0.85)
        reasons.append("high_altitude")
    if source_role == "current_wind_train" and obs_count >= _cal_float(qc_calibration, "vertical_localization_dense_count", 6.0):
        factor *= _cal_float(qc_calibration, "vertical_localization_dense_current_factor", 0.85)
        reasons.append("dense_current")
    if source_role == "context_wind" and time_conf <= _cal_float(qc_calibration, "vertical_localization_stale_context_time_conf", 0.28):
        factor *= _cal_float(qc_calibration, "vertical_localization_stale_context_factor", 0.70)
        reasons.append("stale_context")
    if not reasons and obs_count <= _cal_float(qc_calibration, "vertical_localization_sparse_count", 1.0):
        factor *= _cal_float(qc_calibration, "vertical_localization_sparse_weak_factor", 1.10)
        reasons.append("sparse_weak_support")
    context = localization_context or {}
    if str(context.get("localization_policy", "")) == "support_role_height_aware":
        role_gap = _safe_float(context.get("adaptive_role_gap_mps"), 0.0)
        context_time_mean = _safe_float(context.get("adaptive_context_time_conf_mean"), 1.0)
        if role_gap >= _cal_float(qc_calibration, "adaptive_localization_srha_moderate_role_gap_mps", 18.0):
            factor *= _cal_float(qc_calibration, "adaptive_localization_srha_vertical_role_gap_factor", 0.85)
            reasons.append("srha_role_gap")
        if source_role == "context_wind" and context_time_mean <= _cal_float(qc_calibration, "adaptive_localization_srha_stale_context_time_conf", 0.36):
            factor *= _cal_float(qc_calibration, "adaptive_localization_srha_vertical_stale_context_factor", 0.85)
            reasons.append("srha_stale_context")

    min_factor = _cal_float(qc_calibration, "vertical_localization_min_sigma_factor", 0.55)
    max_factor = _cal_float(qc_calibration, "vertical_localization_max_sigma_factor", 1.25)
    factor = float(np.clip(factor, min_factor, max_factor))
    radius_z = max(1, int(round(base_radius_z * factor))) if base_radius_z > 0 else 0
    return {
        "radius_z": radius_z,
        "sigma_z": base_sigma_z * factor,
        "sigma_factor": factor,
        "reason": "+".join(reasons) if reasons else "neutral",
    }


def _dynamic_horizontal_localization(
    row: dict[str, Any],
    *,
    base_radius_xy: int,
    base_sigma_xy: float,
    policy: str,
    qc_calibration: dict[str, Any],
    localization_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    policy = str(policy)
    base_radius_xy = max(0, int(base_radius_xy))
    base_sigma_xy = max(1e-6, float(base_sigma_xy))
    if policy != "support_role_height_aware" or base_radius_xy == 0:
        return {
            "radius_xy": base_radius_xy,
            "sigma_xy": base_sigma_xy,
            "sigma_factor": 1.0,
            "reason": "fixed",
            "high_altitude_gate": False,
            "high_speed_gate": False,
            "role_gap_gate": False,
            "stale_context_gate": False,
            "sparse_fresh_widen_gate": False,
            "dense_current_gate": False,
        }

    context = localization_context or {}
    speed = math.sqrt(_safe_float(row.get("u")) ** 2 + _safe_float(row.get("v")) ** 2)
    altitude = _safe_float(row.get("alt_meters"), ALT_MIN + max(0, _safe_int(row.get("z"), 0)) * DELTA_ALT)
    source_role = str(row.get("source_role"))
    time_conf = _safe_float(row.get("time_conf"), 1.0)
    current_support = _safe_float(context.get("adaptive_current_support"), 0.0)
    context_time_mean = _safe_float(context.get("adaptive_context_time_conf_mean"), 0.0)
    local_consistency_mean = _safe_float(context.get("adaptive_local_consistency_mean"), 1.0)
    role_gap = _safe_float(context.get("adaptive_role_gap_mps"), 0.0)

    high_altitude_gate = altitude >= _cal_float(qc_calibration, "adaptive_localization_srha_high_altitude_m", 12000.0)
    high_speed_gate = speed >= _cal_float(qc_calibration, "adaptive_localization_srha_high_speed_mps", 60.0)
    role_gap_gate = role_gap >= _cal_float(qc_calibration, "adaptive_localization_srha_moderate_role_gap_mps", 18.0)
    stale_context_gate = (
        source_role == "context_wind"
        and (
            time_conf <= _cal_float(qc_calibration, "adaptive_localization_srha_stale_context_time_conf", 0.36)
            or context_time_mean <= _cal_float(qc_calibration, "adaptive_localization_srha_stale_context_time_conf", 0.36)
        )
    )
    dense_current_gate = (
        source_role == "current_wind_train"
        and current_support >= _cal_float(qc_calibration, "adaptive_localization_srha_dense_current_support", 10.0)
    )
    sparse_fresh_widen_gate = (
        current_support <= _cal_float(qc_calibration, "adaptive_localization_srha_sparse_current_support", 2.0)
        and context_time_mean >= _cal_float(qc_calibration, "adaptive_localization_srha_fresh_context_time_conf", 0.50)
        and local_consistency_mean >= _cal_float(qc_calibration, "adaptive_localization_srha_stable_local_consistency", 0.975)
        and role_gap < _cal_float(qc_calibration, "adaptive_localization_srha_moderate_role_gap_mps", 18.0)
        and not high_altitude_gate
        and not high_speed_gate
        and not stale_context_gate
    )

    factor = 1.0
    reasons: list[str] = []
    if high_altitude_gate:
        factor *= _cal_float(qc_calibration, "adaptive_localization_srha_horizontal_high_altitude_factor", 0.78)
        reasons.append("high_altitude")
    if high_speed_gate:
        factor *= _cal_float(qc_calibration, "adaptive_localization_srha_horizontal_high_speed_factor", 0.85)
        reasons.append("high_speed")
    if role_gap_gate:
        factor *= _cal_float(qc_calibration, "adaptive_localization_srha_horizontal_role_gap_factor", 0.80)
        reasons.append("role_gap")
    if stale_context_gate:
        factor *= _cal_float(qc_calibration, "adaptive_localization_srha_horizontal_stale_context_factor", 0.75)
        reasons.append("stale_context")
    if dense_current_gate:
        factor *= _cal_float(qc_calibration, "adaptive_localization_srha_horizontal_dense_current_factor", 0.90)
        reasons.append("dense_current")
    if sparse_fresh_widen_gate:
        factor *= _cal_float(qc_calibration, "adaptive_localization_srha_horizontal_sparse_fresh_factor", 1.10)
        reasons.append("sparse_fresh_widen")

    min_factor = _cal_float(qc_calibration, "adaptive_localization_srha_horizontal_min_sigma_factor", 0.65)
    max_factor = _cal_float(qc_calibration, "adaptive_localization_srha_horizontal_max_sigma_factor", 1.15)
    factor = float(np.clip(factor, min_factor, max_factor))
    radius_xy = max(1, int(round(base_radius_xy * factor))) if base_radius_xy > 0 else 0
    return {
        "radius_xy": radius_xy,
        "sigma_xy": base_sigma_xy * factor,
        "sigma_factor": factor,
        "reason": "+".join(reasons) if reasons else "neutral",
        "high_altitude_gate": high_altitude_gate,
        "high_speed_gate": high_speed_gate,
        "role_gap_gate": role_gap_gate,
        "stale_context_gate": stale_context_gate,
        "sparse_fresh_widen_gate": sparse_fresh_widen_gate,
        "dense_current_gate": dense_current_gate,
    }


def _parse_localization_candidate_grid(text: str) -> list[dict[str, float | int]]:
    candidates: list[dict[str, float | int]] = []
    for item in str(text).split(","):
        token = item.strip()
        if not token:
            continue
        parts = [part.strip() for part in token.replace("/", ":").split(":")]
        if len(parts) == 2:
            rxy, sxy = parts
            rz, sz = 2, 1.0
        elif len(parts) == 4:
            rxy, sxy, rz, sz = parts
        else:
            raise ValueError(f"Localization candidate must be rxy:sxy or rxy:sxy:rz:sz: {token}")
        candidates.append(
            {
                "localization_radius_xy": int(rxy),
                "localization_sigma_xy": float(sxy),
                "localization_radius_z": int(rz),
                "localization_sigma_z": float(sz),
            }
        )
    if not candidates:
        raise ValueError("No localization candidates were provided.")
    return candidates


def _candidate_by_radius(candidates: list[dict[str, float | int]], radius_xy: int) -> dict[str, float | int]:
    target = int(radius_xy)
    return min(candidates, key=lambda row: abs(int(row["localization_radius_xy"]) - target))


def _mean_record_value(rows: list[dict[str, Any]], key: str, default: float = 0.0) -> float:
    values = [_safe_float(row.get(key), float("nan")) for row in rows]
    finite = [value for value in values if math.isfinite(value)]
    return float(np.mean(finite)) if finite else float(default)


def _record_fraction(rows: list[dict[str, Any]], predicate: Any) -> float:
    if not rows:
        return 0.0
    return float(sum(1 for row in rows if predicate(row))) / float(len(rows))


def _select_adaptive_localization(
    *,
    train_current_wind: list[dict[str, Any]],
    context_wind: list[dict[str, Any]],
    observations: list[dict[str, Any]],
    candidate_grid: str,
    default_radius_xy: int,
    default_sigma_xy: float,
    default_radius_z: int,
    default_sigma_z: float,
    qc_calibration: dict[str, Any] | None = None,
    policy: str = "diagnostic_adaptive",
) -> tuple[dict[str, float | int], dict[str, Any]]:
    """Choose a frame-level localization kernel without inspecting holdout errors."""

    calibration = qc_calibration or DEFAULT_QC_CALIBRATION
    candidates = _parse_localization_candidate_grid(candidate_grid)
    current_count = len(train_current_wind)
    context_count = len(context_wind)
    obs_error_weight_mean = _mean_record_value(observations, "obs_error_weight_factor", 1.0)
    local_consistency_mean = _mean_record_value(observations, "local_consistency_conf_factor", 1.0)
    context_time_mean = _mean_record_value([row for row in observations if str(row.get("source_role")) == "context_wind"], "time_conf", 0.0)
    current_time_mean = _mean_record_value([row for row in observations if str(row.get("source_role")) == "current_wind_train"], "time_conf", 1.0)
    high_altitude_m = _cal_float(calibration, "adaptive_localization_srha_high_altitude_m", 12000.0)
    high_speed_mps = _cal_float(calibration, "adaptive_localization_srha_high_speed_mps", 60.0)
    high_altitude_fraction = _record_fraction(
        observations,
        lambda row: _safe_float(row.get("alt_meters"), ALT_MIN + _safe_int(row.get("z"), 0) * DELTA_ALT) >= high_altitude_m,
    )
    high_speed_fraction = _record_fraction(
        observations,
        lambda row: math.sqrt(_safe_float(row.get("u")) ** 2 + _safe_float(row.get("v")) ** 2) >= high_speed_mps,
    )
    current_density_proxy = min(1.0, current_count / max(1e-6, _cal_float(calibration, "adaptive_localization_high_current_support", 8.0)))
    context_density_proxy = min(1.0, context_count / max(1e-6, _cal_float(calibration, "adaptive_localization_high_context_support", 300.0)))
    context_fresh_proxy = min(1.0, context_time_mean / max(1e-6, _cal_float(calibration, "adaptive_localization_high_context_time_conf", 0.45)))
    low_obs_error_weight = obs_error_weight_mean < _cal_float(calibration, "adaptive_localization_low_obs_error_weight", 0.90)

    current_u = _mean_record_value(train_current_wind, "u", 0.0)
    current_v = _mean_record_value(train_current_wind, "v", 0.0)
    context_u = _mean_record_value(context_wind, "u", current_u)
    context_v = _mean_record_value(context_wind, "v", current_v)
    role_gap_mps = math.sqrt((current_u - context_u) ** 2 + (current_v - context_v) ** 2) if current_count > 0 and context_count > 0 else 0.0
    role_conflict_proxy = role_gap_mps / max(1.0, _cal_float(calibration, "speed_soft_limit_mps", 90.0))

    score = 8.0
    reasons: list[str] = ["default_timepower15_8_4_conservative_v2"]
    low_current = current_count <= _cal_float(calibration, "adaptive_localization_low_current_support", 2.0)
    high_current = current_count >= _cal_float(calibration, "adaptive_localization_high_current_support", 8.0)
    context_useful = (
        context_count >= _cal_float(calibration, "adaptive_localization_high_context_support", 300.0)
        and context_time_mean >= _cal_float(calibration, "adaptive_localization_low_context_time_conf", 0.28)
    )
    high_vertical_mismatch = (
        _mean_record_value(observations, "local_consistency_conf_factor", 1.0) < 0.94
        or role_conflict_proxy >= _cal_float(calibration, "adaptive_localization_high_role_conflict_ratio", 0.08)
    )

    # Conservative v2: only widen for moderate-risk frames. The first adaptive
    # pass showed that frequent 6/3 or 12/6 switches hurt low-error frames.
    if context_useful and not low_current and current_count <= 18 and context_time_mean >= 0.50:
        score = 10.0
        reasons.append("moderate_current_support_fresh_context_prefers_10_5")
    if low_current and context_useful and context_time_mean >= 0.55 and not high_vertical_mismatch:
        score = 10.0
        reasons.append("low_current_but_stable_context_prefers_10_5")
    if high_current and role_conflict_proxy >= 0.18 and context_time_mean < 0.50:
        score = 6.0
        reasons.append("dense_current_stale_conflict_prefers_6_3")
    if low_obs_error_weight and score < 10.0 and context_useful and current_count <= 12:
        score = 10.0
        reasons.append("low_obs_error_weight_sparse_support_prefers_10_5")

    if str(policy) in {"diagnostic_adaptive_v3", "diagnostic_adaptive_regime_v4"} and score > 8.0:
        stable_low_error_guard = (
            current_count <= _cal_float(calibration, "adaptive_localization_v3_guard_max_current_support", 8.0)
            and context_time_mean <= _cal_float(calibration, "adaptive_localization_v3_guard_max_context_time_conf", 0.57)
            and local_consistency_mean >= _cal_float(calibration, "adaptive_localization_v3_guard_min_local_consistency", 0.98)
        )
        sparse_context_guard = (
            current_count <= _cal_float(calibration, "adaptive_localization_v3_sparse_guard_max_current_support", 2.0)
            and context_time_mean <= _cal_float(calibration, "adaptive_localization_v3_sparse_guard_max_context_time_conf", 0.52)
            and local_consistency_mean >= _cal_float(calibration, "adaptive_localization_v3_sparse_guard_min_local_consistency", 0.985)
        )
        if stable_low_error_guard or sparse_context_guard:
            score = 8.0
            reasons.append("v3_low_error_guard_prefers_8_4")

    if str(policy) == "diagnostic_adaptive_regime_v4":
        very_sparse_current = current_count <= _cal_float(calibration, "adaptive_localization_v4_very_sparse_current_support", 1.0)
        sparse_current = current_count <= _cal_float(calibration, "adaptive_localization_v4_sparse_current_support", 2.0)
        dense_current = current_count >= _cal_float(calibration, "adaptive_localization_v4_dense_current_support", 10.0)
        fresh_context = context_time_mean >= _cal_float(calibration, "adaptive_localization_v4_fresh_context_time_conf", 0.52)
        stale_context = context_time_mean <= _cal_float(calibration, "adaptive_localization_v4_stale_context_time_conf", 0.42)
        stable_local = local_consistency_mean >= _cal_float(calibration, "adaptive_localization_v4_stable_local_consistency", 0.975)
        unstable_local = local_consistency_mean <= _cal_float(calibration, "adaptive_localization_v4_unstable_local_consistency", 0.93)
        elevated_role_conflict = role_conflict_proxy >= _cal_float(calibration, "adaptive_localization_v4_high_role_conflict_ratio", 0.18)

        if high_vertical_mismatch or unstable_local or elevated_role_conflict:
            score = 8.0
            reasons.append("v4_vertical_or_role_risk_prefers_8_4")
        elif very_sparse_current and context_useful and fresh_context and stable_local:
            score = 12.0
            reasons.append("v4_very_sparse_current_fresh_context_prefers_12_6")
        elif sparse_current and context_useful and fresh_context:
            score = max(score, 10.0)
            reasons.append("v4_sparse_current_fresh_context_prefers_10_5")
        elif dense_current and stable_local and role_conflict_proxy < _cal_float(calibration, "adaptive_localization_v4_dense_current_max_role_conflict_ratio", 0.10):
            score = 8.0
            reasons.append("v4_dense_current_stable_anchor_prefers_8_4")

        if stale_context and score > 8.0:
            score = 8.0
            reasons.append("v4_stale_context_guard_prefers_8_4")
        if low_obs_error_weight and score > 10.0 and current_count >= 3:
            score = 10.0
            reasons.append("v4_low_obs_error_weight_caps_widening_10_5")

    if str(policy) == "support_role_height_aware":
        very_sparse_current = current_count <= _cal_float(calibration, "adaptive_localization_srha_very_sparse_current_support", 1.0)
        sparse_current = current_count <= _cal_float(calibration, "adaptive_localization_srha_sparse_current_support", 2.0)
        dense_current = current_count >= _cal_float(calibration, "adaptive_localization_srha_dense_current_support", 10.0)
        fresh_context = context_time_mean >= _cal_float(calibration, "adaptive_localization_srha_fresh_context_time_conf", 0.50)
        stale_context = context_time_mean <= _cal_float(calibration, "adaptive_localization_srha_stale_context_time_conf", 0.36)
        stable_local = local_consistency_mean >= _cal_float(calibration, "adaptive_localization_srha_stable_local_consistency", 0.975)
        unstable_local = local_consistency_mean <= _cal_float(calibration, "adaptive_localization_srha_unstable_local_consistency", 0.93)
        moderate_role_gap = role_gap_mps >= _cal_float(calibration, "adaptive_localization_srha_moderate_role_gap_mps", 18.0)
        high_role_gap = role_gap_mps >= _cal_float(calibration, "adaptive_localization_srha_high_role_gap_mps", 30.0)
        high_altitude_regime = high_altitude_fraction >= _cal_float(calibration, "adaptive_localization_srha_high_altitude_fraction", 0.22)
        high_speed_regime = high_speed_fraction >= _cal_float(calibration, "adaptive_localization_srha_high_speed_fraction", 0.12)

        score = 8.0
        reasons.append("srha_default_8_4")
        if high_role_gap or unstable_local:
            score = 8.0
            reasons.append("srha_role_or_consistency_risk_keeps_8_4")
        elif (very_sparse_current or sparse_current) and context_useful and fresh_context and stable_local:
            score = 10.0
            reasons.append("srha_sparse_current_fresh_context_prefers_10_5")
        elif dense_current and not moderate_role_gap:
            score = 8.0
            reasons.append("srha_dense_current_anchor_prefers_8_4")
        elif context_useful and fresh_context and not high_vertical_mismatch:
            score = 10.0
            reasons.append("srha_moderate_support_fresh_context_prefers_10_5")

        if high_altitude_regime or high_speed_regime:
            score = min(score, 10.0)
            reasons.append("srha_high_alt_or_speed_caps_xy_widening")
        if stale_context or (moderate_role_gap and not sparse_current):
            score = 8.0
            reasons.append("srha_stale_or_role_gap_guard_prefers_8_4")
        if low_obs_error_weight and score > 8.0 and not (sparse_current and fresh_context):
            score = 8.0
            reasons.append("srha_low_obs_error_guard_prefers_8_4")

    candidate_radii = [int(row["localization_radius_xy"]) for row in candidates]
    min_radius = min(candidate_radii)
    max_radius = max(candidate_radii)
    selected_radius = int(np.clip(round(score / 2.0) * 2, min_radius, max_radius))
    selected = dict(_candidate_by_radius(candidates, selected_radius))
    if not selected:
        selected = {
            "localization_radius_xy": int(default_radius_xy),
            "localization_sigma_xy": float(default_sigma_xy),
            "localization_radius_z": int(default_radius_z),
            "localization_sigma_z": float(default_sigma_z),
        }
    if str(policy) == "support_role_height_aware" and (
        high_altitude_fraction >= _cal_float(calibration, "adaptive_localization_srha_high_altitude_fraction", 0.22)
        or high_speed_fraction >= _cal_float(calibration, "adaptive_localization_srha_high_speed_fraction", 0.12)
        or role_gap_mps >= _cal_float(calibration, "adaptive_localization_srha_moderate_role_gap_mps", 18.0)
    ):
        selected["localization_radius_z"] = int(_cal_float(calibration, "adaptive_localization_srha_tight_radius_z", 1.0))
        selected["localization_sigma_z"] = float(_cal_float(calibration, "adaptive_localization_srha_tight_sigma_z", 0.75))
        reasons.append("srha_tight_vertical_for_tail_regime")
    else:
        # Keep the current vertical spread fixed until vertical-risk phase has a stronger rule.
        selected["localization_radius_z"] = int(default_radius_z)
        selected["localization_sigma_z"] = float(default_sigma_z)
    diagnostics = {
        "localization_policy": str(policy),
        "localization_candidate_grid": str(candidate_grid),
        "adaptive_selected_radius_xy": int(selected["localization_radius_xy"]),
        "adaptive_selected_sigma_xy": float(selected["localization_sigma_xy"]),
        "adaptive_selected_radius_z": int(selected["localization_radius_z"]),
        "adaptive_selected_sigma_z": float(selected["localization_sigma_z"]),
        "adaptive_score": float(score),
        "adaptive_reasons": ";".join(reasons),
        "adaptive_current_support": int(current_count),
        "adaptive_context_support": int(context_count),
        "adaptive_current_time_conf_mean": float(current_time_mean),
        "adaptive_context_time_conf_mean": float(context_time_mean),
        "adaptive_obs_error_weight_mean": float(obs_error_weight_mean),
        "adaptive_local_consistency_mean": float(local_consistency_mean),
        "adaptive_role_gap_mps": float(role_gap_mps),
        "adaptive_role_conflict_proxy": float(role_conflict_proxy),
        "adaptive_high_altitude_fraction": float(high_altitude_fraction),
        "adaptive_high_speed_fraction": float(high_speed_fraction),
        "adaptive_current_density_proxy": float(current_density_proxy),
        "adaptive_context_density_proxy": float(context_density_proxy),
        "adaptive_context_fresh_proxy": float(context_fresh_proxy),
        "adaptive_no_holdout_inputs_used": True,
    }
    return selected, diagnostics


def _positive_percentile_scale(values: np.ndarray, percentile: float = 90.0, default: float = 1.0) -> float:
    finite = np.asarray(values, dtype=np.float32)
    positive = finite[np.isfinite(finite) & (finite > 0.0)]
    if positive.size == 0:
        return float(default)
    return max(float(np.percentile(positive, percentile)), 1e-6)


def _adaptive_role_conflict_fields(
    shape: tuple[int, int, int],
    *,
    base_threshold_mps: float,
    base_context_factor: float,
    acc_current_w: np.ndarray,
    acc_context_w: np.ndarray,
    acc_context_time: np.ndarray,
    qc_calibration: dict[str, Any] | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Return threshold/retention fields for current-vs-context role conflicts."""

    calibration = qc_calibration or DEFAULT_QC_CALIBRATION
    z_dim, _, _ = shape
    z_alt = (ALT_MIN + np.arange(z_dim, dtype=np.float32) * np.float32(DELTA_ALT))[:, None, None]
    height_norm = np.clip((z_alt - np.float32(8000.0)) / np.float32(7000.0), 0.0, 1.0).astype(np.float32)
    current_density = np.clip(
        acc_current_w / np.float32(_positive_percentile_scale(acc_current_w)),
        0.0,
        1.0,
    ).astype(np.float32)
    context_density = np.clip(
        acc_context_w / np.float32(_positive_percentile_scale(acc_context_w)),
        0.0,
        1.0,
    ).astype(np.float32)
    density_norm = np.clip(0.5 * (current_density + context_density), 0.0, 1.0).astype(np.float32)
    context_time_mean = np.divide(
        acc_context_time,
        np.maximum(acc_context_w, 1e-6),
        out=np.ones_like(acc_context_w, dtype=np.float32),
        where=acc_context_w > 0.0,
    )
    context_time_mean = np.clip(context_time_mean, 0.0, 1.0).astype(np.float32)
    context_staleness = (1.0 - context_time_mean).astype(np.float32)

    base_threshold = float(max(0.0, base_threshold_mps))
    if base_threshold <= 0.0:
        threshold = np.zeros(shape, dtype=np.float32)
    else:
        height_threshold_gain = _cal_float(calibration, "role_conflict_adaptive_height_threshold_gain", 0.35)
        sparse_current_threshold_gain = _cal_float(calibration, "role_conflict_adaptive_sparse_current_threshold_gain", 0.25)
        stale_context_threshold_reduction = _cal_float(calibration, "role_conflict_adaptive_stale_context_threshold_reduction", 0.30)
        dense_overlap_threshold_reduction = _cal_float(calibration, "role_conflict_adaptive_dense_overlap_threshold_reduction", 0.15)
        min_threshold_factor = _cal_float(calibration, "role_conflict_adaptive_min_threshold_factor", 0.50)
        max_threshold_factor = _cal_float(calibration, "role_conflict_adaptive_max_threshold_factor", 2.00)
        min_threshold_mps = _cal_float(calibration, "role_conflict_adaptive_min_threshold_mps", 3.0)
        threshold = base_threshold * (
            1.0
            + height_threshold_gain * height_norm
            + sparse_current_threshold_gain * (1.0 - current_density)
            - stale_context_threshold_reduction * context_staleness
            - dense_overlap_threshold_reduction * density_norm
        )
        threshold = np.clip(
            threshold,
            max(float(min_threshold_mps), base_threshold * max(0.0, min_threshold_factor)),
            max(float(min_threshold_mps), base_threshold * max(min_threshold_factor, max_threshold_factor)),
        ).astype(np.float32)

    base_factor = float(np.clip(base_context_factor, 0.0, 1.0))
    sparse_current_factor_gain = _cal_float(calibration, "role_conflict_adaptive_sparse_current_factor_gain", 0.20)
    height_factor_gain = _cal_float(calibration, "role_conflict_adaptive_height_factor_gain", 0.12)
    stale_context_factor_reduction = _cal_float(calibration, "role_conflict_adaptive_stale_context_factor_reduction", 0.50)
    current_density_factor_reduction = _cal_float(calibration, "role_conflict_adaptive_current_density_factor_reduction", 0.15)
    min_context_factor = _cal_float(calibration, "role_conflict_adaptive_min_context_factor", 0.05)
    max_context_factor = _cal_float(calibration, "role_conflict_adaptive_max_context_factor", 0.80)
    context_factor = (
        base_factor
        + sparse_current_factor_gain * (1.0 - current_density)
        + height_factor_gain * height_norm
        - stale_context_factor_reduction * context_staleness
        - current_density_factor_reduction * current_density
    )
    context_factor = np.clip(context_factor, min_context_factor, max_context_factor).astype(np.float32)
    return threshold, context_factor, current_density, context_time_mean, height_norm


def _accumulate_localized(
    shape: tuple[int, int, int],
    observations: list[dict[str, Any]],
    radius_xy: int,
    radius_z: int,
    sigma_xy: float,
    sigma_z: float,
    localization_kernel: str,
    *,
    role_conflict_mode: str = "off",
    conflict_speed_threshold_mps: float = 12.0,
    conflict_context_factor: float = 0.25,
    vertical_localization_policy: str = "fixed",
    localization_policy: str = "fixed",
    localization_context: dict[str, Any] | None = None,
    qc_calibration: dict[str, Any] | None = None,
) -> dict[str, np.ndarray]:
    z_dim, h_dim, w_dim = shape
    acc_u = np.zeros(shape, dtype=np.float32)
    acc_v = np.zeros(shape, dtype=np.float32)
    acc_w = np.zeros(shape, dtype=np.float32)
    acc_time = np.zeros(shape, dtype=np.float32)
    acc_space = np.zeros(shape, dtype=np.float32)
    source_mask = np.zeros(shape, dtype=bool)
    acc_current_u = np.zeros(shape, dtype=np.float32)
    acc_current_v = np.zeros(shape, dtype=np.float32)
    acc_current_w = np.zeros(shape, dtype=np.float32)
    acc_context_u = np.zeros(shape, dtype=np.float32)
    acc_context_v = np.zeros(shape, dtype=np.float32)
    acc_context_w = np.zeros(shape, dtype=np.float32)
    acc_context_time = np.zeros(shape, dtype=np.float32)
    acc_context_space = np.zeros(shape, dtype=np.float32)
    conflict_context_w = np.zeros(shape, dtype=np.float32)
    conflict_context_removed_w = np.zeros(shape, dtype=np.float32)
    role_conflict_mask = np.zeros(shape, dtype=bool)
    calibration = qc_calibration or DEFAULT_QC_CALIBRATION
    vertical_localization_policy = str(vertical_localization_policy)
    if vertical_localization_policy not in VERTICAL_LOCALIZATION_POLICIES:
        raise ValueError(
            f"Unsupported vertical_localization_policy={vertical_localization_policy}; "
            f"choose {sorted(VERTICAL_LOCALIZATION_POLICIES)}"
        )
    vertical_sigma_factors: list[float] = []
    vertical_reason_counts: dict[str, int] = {}
    horizontal_sigma_factors: list[float] = []
    horizontal_reason_counts: dict[str, int] = {}
    srha_gate_counts = {
        "high_altitude_gate_count": 0,
        "high_speed_gate_count": 0,
        "role_gap_gate_count": 0,
        "stale_context_gate_count": 0,
        "sparse_fresh_widen_gate_count": 0,
        "dense_current_gate_count": 0,
    }
    localization_context = localization_context or {}
    component_gap = np.zeros(shape, dtype=np.float32)
    threshold_field = np.zeros(shape, dtype=np.float32)
    context_factor_field = np.zeros(shape, dtype=np.float32)
    current_density = np.zeros(shape, dtype=np.float32)
    context_time_mean = np.zeros(shape, dtype=np.float32)
    role_conflict_scalar_diagnostics: dict[str, float | int | str] = {
        "role_conflict_mode_active": str(role_conflict_mode),
        "role_conflict_component_gap_mean_mps": 0.0,
        "role_conflict_component_gap_max_mps": 0.0,
        "role_conflict_threshold_mean_mps": 0.0,
        "role_conflict_threshold_min_mps": 0.0,
        "role_conflict_threshold_max_mps": 0.0,
        "role_conflict_context_factor_mean": 0.0,
        "role_conflict_context_factor_min": 0.0,
        "role_conflict_context_factor_max": 0.0,
        "role_conflict_current_density_mean": 0.0,
        "role_conflict_context_time_conf_mean": 0.0,
        "role_conflict_altitude_mean_m": 0.0,
        "role_conflict_context_weight_removed_sum": 0.0,
        "role_conflict_adaptive_calibration": json.dumps(
            {
                key: calibration.get(key)
                for key in sorted(calibration)
                if str(key).startswith("role_conflict_adaptive_")
            },
            ensure_ascii=False,
        ),
    }

    radius_xy = max(0, int(radius_xy))
    radius_z = max(0, int(radius_z))
    sigma_xy = max(1e-6, float(sigma_xy))
    sigma_z = max(1e-6, float(sigma_z))
    localization_policy = str(localization_policy)
    if localization_policy not in LOCALIZATION_POLICIES:
        raise ValueError(f"Unsupported localization_policy={localization_policy}; choose {sorted(LOCALIZATION_POLICIES)}")
    if localization_kernel not in LOCALIZATION_KERNELS:
        raise ValueError(f"Unsupported localization_kernel={localization_kernel}; choose {sorted(LOCALIZATION_KERNELS)}")
    role_conflict_mode = str(role_conflict_mode)
    if role_conflict_mode not in ROLE_CONFLICT_MODES:
        raise ValueError(f"Unsupported role_conflict_mode={role_conflict_mode}; choose {sorted(ROLE_CONFLICT_MODES)}")
    conflict_speed_threshold_mps = float(max(0.0, conflict_speed_threshold_mps))
    conflict_context_factor = float(np.clip(conflict_context_factor, 0.0, 1.0))

    for row in observations:
        z = int(row["z"])
        y = int(row["y"])
        x = int(row["x"])
        if not (0 <= z < z_dim and 0 <= y < h_dim and 0 <= x < w_dim):
            continue
        horizontal_loc = _dynamic_horizontal_localization(
            row,
            base_radius_xy=radius_xy,
            base_sigma_xy=sigma_xy,
            policy=localization_policy,
            qc_calibration=calibration,
            localization_context=localization_context,
        )
        vertical_loc = _dynamic_vertical_localization(
            row,
            base_radius_z=radius_z,
            base_sigma_z=sigma_z,
            policy=vertical_localization_policy,
            qc_calibration=calibration,
            localization_context=localization_context,
        )
        row_radius_xy = int(horizontal_loc["radius_xy"])
        row_sigma_xy = float(horizontal_loc["sigma_xy"])
        horizontal_factor = float(horizontal_loc["sigma_factor"])
        horizontal_reason = str(horizontal_loc["reason"])
        horizontal_sigma_factors.append(horizontal_factor)
        horizontal_reason_counts[horizontal_reason] = horizontal_reason_counts.get(horizontal_reason, 0) + 1
        for gate_key in srha_gate_counts:
            if bool(horizontal_loc.get(gate_key.replace("_count", ""), False)):
                srha_gate_counts[gate_key] += 1
        row_radius_z = int(vertical_loc["radius_z"])
        row_sigma_z = float(vertical_loc["sigma_z"])
        factor = float(vertical_loc["sigma_factor"])
        reason = str(vertical_loc["reason"])
        vertical_sigma_factors.append(factor)
        vertical_reason_counts[reason] = vertical_reason_counts.get(reason, 0) + 1
        z0 = max(0, z - row_radius_z)
        z1 = min(z_dim, z + row_radius_z + 1)
        y0 = max(0, y - row_radius_xy)
        y1 = min(h_dim, y + row_radius_xy + 1)
        x0 = max(0, x - row_radius_xy)
        x1 = min(w_dim, x + row_radius_xy + 1)

        dz = (np.arange(z0, z1, dtype=np.float32) - float(z))[:, None, None]
        dy = (np.arange(y0, y1, dtype=np.float32) - float(y))[None, :, None]
        dx = (np.arange(x0, x1, dtype=np.float32) - float(x))[None, None, :]
        localization = _localization_weights(dx, dy, dz, row_sigma_xy, row_sigma_z, localization_kernel)
        local_w = localization * np.float32(row["base_weight"])

        acc_u[z0:z1, y0:y1, x0:x1] += np.float32(row["u"]) * local_w
        acc_v[z0:z1, y0:y1, x0:x1] += np.float32(row["v"]) * local_w
        acc_w[z0:z1, y0:y1, x0:x1] += local_w
        acc_time[z0:z1, y0:y1, x0:x1] += np.float32(row["time_conf"]) * local_w
        acc_space[z0:z1, y0:y1, x0:x1] += localization * local_w
        source_mask[z, y, x] = True
        if str(row.get("source_role")) == "current_wind_train":
            acc_current_u[z0:z1, y0:y1, x0:x1] += np.float32(row["u"]) * local_w
            acc_current_v[z0:z1, y0:y1, x0:x1] += np.float32(row["v"]) * local_w
            acc_current_w[z0:z1, y0:y1, x0:x1] += local_w
        elif str(row.get("source_role")) == "context_wind":
            acc_context_u[z0:z1, y0:y1, x0:x1] += np.float32(row["u"]) * local_w
            acc_context_v[z0:z1, y0:y1, x0:x1] += np.float32(row["v"]) * local_w
            acc_context_w[z0:z1, y0:y1, x0:x1] += local_w
            acc_context_time[z0:z1, y0:y1, x0:x1] += np.float32(row["time_conf"]) * local_w
            acc_context_space[z0:z1, y0:y1, x0:x1] += localization * local_w

    if role_conflict_mode in {"current_priority", "current_priority_adaptive"} and conflict_context_factor < 1.0:
        both_roles = (acc_current_w > 0.0) & (acc_context_w > 0.0)
        current_u = np.divide(acc_current_u, np.maximum(acc_current_w, 1e-6), out=np.zeros_like(acc_current_w), where=acc_current_w > 0.0)
        current_v = np.divide(acc_current_v, np.maximum(acc_current_w, 1e-6), out=np.zeros_like(acc_current_w), where=acc_current_w > 0.0)
        context_u = np.divide(acc_context_u, np.maximum(acc_context_w, 1e-6), out=np.zeros_like(acc_context_w), where=acc_context_w > 0.0)
        context_v = np.divide(acc_context_v, np.maximum(acc_context_w, 1e-6), out=np.zeros_like(acc_context_w), where=acc_context_w > 0.0)
        component_gap = np.sqrt((current_u - context_u) ** 2 + (current_v - context_v) ** 2).astype(np.float32)
        component_gap = np.where(both_roles, component_gap, 0.0).astype(np.float32)
        if role_conflict_mode == "current_priority_adaptive":
            threshold_field, context_factor_field, current_density, context_time_mean, height_norm = _adaptive_role_conflict_fields(
                shape,
                base_threshold_mps=conflict_speed_threshold_mps,
                base_context_factor=conflict_context_factor,
                acc_current_w=acc_current_w,
                acc_context_w=acc_context_w,
                acc_context_time=acc_context_time,
                qc_calibration=calibration,
            )
            threshold_for_mask = threshold_field
            context_factor_for_mask = context_factor_field
        else:
            threshold_field = np.full(shape, np.float32(conflict_speed_threshold_mps), dtype=np.float32)
            context_factor_field = np.full(shape, np.float32(conflict_context_factor), dtype=np.float32)
            current_density = np.clip(
                acc_current_w / np.float32(_positive_percentile_scale(acc_current_w)),
                0.0,
                1.0,
            ).astype(np.float32)
            context_time_mean = np.divide(
                acc_context_time,
                np.maximum(acc_context_w, 1e-6),
                out=np.ones_like(acc_context_w, dtype=np.float32),
                where=acc_context_w > 0.0,
            )
            height_norm = np.zeros(shape, dtype=np.float32)
            threshold_for_mask = np.float32(conflict_speed_threshold_mps)
            context_factor_for_mask = np.float32(conflict_context_factor)
        role_conflict_mask = both_roles & (component_gap >= threshold_for_mask)
        context_removed_fraction = np.where(role_conflict_mask, 1.0 - context_factor_for_mask, 0.0).astype(np.float32)
        context_delta_w = acc_context_w * context_removed_fraction
        context_delta_u = acc_context_u * context_removed_fraction
        context_delta_v = acc_context_v * context_removed_fraction
        context_delta_time = acc_context_time * context_removed_fraction
        context_delta_space = acc_context_space * context_removed_fraction
        acc_u = np.where(role_conflict_mask, acc_u - context_delta_u, acc_u).astype(np.float32)
        acc_v = np.where(role_conflict_mask, acc_v - context_delta_v, acc_v).astype(np.float32)
        acc_w = np.where(role_conflict_mask, acc_w - context_delta_w, acc_w).astype(np.float32)
        acc_time = np.where(role_conflict_mask, acc_time - context_delta_time, acc_time).astype(np.float32)
        acc_space = np.where(role_conflict_mask, acc_space - context_delta_space, acc_space).astype(np.float32)
        acc_w = np.maximum(acc_w, 0.0).astype(np.float32)
        acc_time = np.maximum(acc_time, 0.0).astype(np.float32)
        acc_space = np.maximum(acc_space, 0.0).astype(np.float32)
        conflict_context_w = np.where(role_conflict_mask, acc_context_w, 0.0).astype(np.float32)
        conflict_context_removed_w = np.where(role_conflict_mask, context_delta_w, 0.0).astype(np.float32)
        if np.any(role_conflict_mask):
            conflict_alt = ALT_MIN + np.where(role_conflict_mask)[0].astype(np.float32) * np.float32(DELTA_ALT)
            role_conflict_scalar_diagnostics.update(
                {
                    "role_conflict_component_gap_mean_mps": float(np.mean(component_gap[role_conflict_mask])),
                    "role_conflict_component_gap_max_mps": float(np.max(component_gap[role_conflict_mask])),
                    "role_conflict_threshold_mean_mps": float(np.mean(threshold_field[role_conflict_mask])),
                    "role_conflict_threshold_min_mps": float(np.min(threshold_field[role_conflict_mask])),
                    "role_conflict_threshold_max_mps": float(np.max(threshold_field[role_conflict_mask])),
                    "role_conflict_context_factor_mean": float(np.mean(context_factor_field[role_conflict_mask])),
                    "role_conflict_context_factor_min": float(np.min(context_factor_field[role_conflict_mask])),
                    "role_conflict_context_factor_max": float(np.max(context_factor_field[role_conflict_mask])),
                    "role_conflict_current_density_mean": float(np.mean(current_density[role_conflict_mask])),
                    "role_conflict_context_time_conf_mean": float(np.mean(context_time_mean[role_conflict_mask])),
                    "role_conflict_altitude_mean_m": float(np.mean(conflict_alt)),
                    "role_conflict_context_weight_removed_sum": float(np.sum(conflict_context_removed_w)),
                }
            )
        elif np.any(both_roles):
            role_conflict_scalar_diagnostics.update(
                {
                    "role_conflict_component_gap_mean_mps": float(np.mean(component_gap[both_roles])),
                    "role_conflict_component_gap_max_mps": float(np.max(component_gap[both_roles])),
                    "role_conflict_threshold_mean_mps": float(np.mean(threshold_field[both_roles])),
                    "role_conflict_threshold_min_mps": float(np.min(threshold_field[both_roles])),
                    "role_conflict_threshold_max_mps": float(np.max(threshold_field[both_roles])),
                    "role_conflict_context_factor_mean": float(np.mean(context_factor_field[both_roles])),
                    "role_conflict_context_factor_min": float(np.min(context_factor_field[both_roles])),
                    "role_conflict_context_factor_max": float(np.max(context_factor_field[both_roles])),
                    "role_conflict_current_density_mean": float(np.mean(current_density[both_roles])),
                    "role_conflict_context_time_conf_mean": float(np.mean(context_time_mean[both_roles])),
                }
            )

    return {
        "acc_u": acc_u,
        "acc_v": acc_v,
        "acc_w": acc_w,
        "acc_time": acc_time,
        "acc_space": acc_space,
        "source_mask": source_mask,
        "acc_current_w": acc_current_w,
        "acc_context_w": acc_context_w,
        "acc_context_time": acc_context_time,
        "role_conflict_mask": role_conflict_mask,
        "conflict_context_w": conflict_context_w,
        "conflict_context_removed_w": conflict_context_removed_w,
        "role_conflict_component_gap": component_gap,
        "role_conflict_threshold_field": threshold_field,
        "role_conflict_context_factor_field": context_factor_field,
        "role_conflict_current_density_field": current_density,
        "role_conflict_context_time_mean_field": context_time_mean,
        "role_conflict_scalar_diagnostics": role_conflict_scalar_diagnostics,
        "vertical_localization_scalar_diagnostics": {
            "vertical_localization_policy": vertical_localization_policy,
            "vertical_localization_sigma_factor_stats": _factor_stats(vertical_sigma_factors),
            "vertical_localization_reason_counts": json.dumps(vertical_reason_counts, ensure_ascii=False, sort_keys=True),
            "vertical_localization_base_radius_z": int(radius_z),
            "vertical_localization_base_sigma_z": float(sigma_z),
        },
        "srha_horizontal_scalar_diagnostics": {
            "srha_localization_policy": localization_policy,
            "srha_horizontal_sigma_factor_stats": _factor_stats(horizontal_sigma_factors),
            "srha_horizontal_reason_counts": json.dumps(horizontal_reason_counts, ensure_ascii=False, sort_keys=True),
            "srha_horizontal_base_radius_xy": int(radius_xy),
            "srha_horizontal_base_sigma_xy": float(sigma_xy),
            **srha_gate_counts,
        },
    }


def _normalize_confidence(weight: np.ndarray) -> np.ndarray:
    positive = weight[weight > 0]
    if positive.size == 0:
        return np.zeros_like(weight, dtype=np.float32)
    scale = float(np.percentile(positive, 90))
    scale = max(scale, 1e-6)
    return np.clip(weight / scale, 0.0, 1.0).astype(np.float32)


def _scalar_npz_text(value: Any) -> str:
    arr = np.asarray(value)
    if arr.shape == ():
        return str(arr.item())
    return str(value)


def _find_cma_proxy_npz(cma_proxy_dir: Path | None, frame_time: str) -> Path | None:
    if cma_proxy_dir is None:
        return None
    candidates = [
        cma_proxy_dir / f"cma_ra_virtual_radial_3dvar_{frame_time}.npz",
        cma_proxy_dir / f"{frame_time}.npz",
    ]
    for path in candidates:
        if path.exists():
            return path
    matches = sorted(cma_proxy_dir.rglob(f"*{frame_time}*.npz"))
    return matches[0] if matches else None


def _load_cma_background(
    path: Path | None,
    shape: tuple[int, int, int],
    *,
    fusion_mode: str,
    confidence_source: str,
    pseudo_source: str = "reanalysis",
    qc_gating: str = "off",
    qc_calibration: dict[str, Any] | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict[str, Any]]:
    fusion_mode = str(fusion_mode)
    if fusion_mode not in CMA_FUSION_MODES:
        raise ValueError(f"Unsupported cma_fusion_mode={fusion_mode}; choose {sorted(CMA_FUSION_MODES)}")
    if fusion_mode == "off":
        return (
            np.zeros(shape, dtype=np.float32),
            np.zeros(shape, dtype=np.float32),
            np.zeros(shape, dtype=np.float32),
            {"cma_fusion_mode": "off", "cma_proxy_npz": ""},
        )
    if path is None or not path.exists():
        raise FileNotFoundError(f"CMA proxy NPZ not found for cma_fusion_mode={fusion_mode}: {path}")
    pseudo_source = str(pseudo_source)
    if pseudo_source not in CMA_PSEUDO_SOURCES:
        raise ValueError(f"Unsupported cma_pseudo_source={pseudo_source}; choose {sorted(CMA_PSEUDO_SOURCES)}")
    qc_gating = str(qc_gating)
    if qc_gating not in CMA_QC_GATING_MODES:
        raise ValueError(f"Unsupported cma_qc_gating={qc_gating}; choose {sorted(CMA_QC_GATING_MODES)}")
    calibration = qc_calibration or DEFAULT_QC_CALIBRATION
    with np.load(path, allow_pickle=True) as z:
        if fusion_mode == "cma_proxy_background":
            u_key, v_key = "u_proxy_3d", "v_proxy_3d"
        elif fusion_mode == "cma_pseudo_observation" and pseudo_source == "proxy":
            u_key, v_key = "u_proxy_3d", "v_proxy_3d"
        else:
            u_key, v_key = "u_cma_3d", "v_cma_3d"
        if u_key not in z.files or v_key not in z.files:
            raise KeyError(f"CMA NPZ {path} is missing {u_key}/{v_key}")
        u = np.asarray(z[u_key], dtype=np.float32)
        v = np.asarray(z[v_key], dtype=np.float32)
        if confidence_source == "coverage_conf" and "coverage_conf_3d" in z.files:
            conf = np.clip(np.asarray(z["coverage_conf_3d"], dtype=np.float32), 0.0, 1.0)
        elif confidence_source == "temporal_conf" and "cma_temporal_conf_3d" in z.files:
            conf = np.clip(np.asarray(z["cma_temporal_conf_3d"], dtype=np.float32), 0.0, 1.0)
        elif confidence_source == "coverage_temporal_conf" and "coverage_conf_3d" in z.files and "cma_temporal_conf_3d" in z.files:
            conf = np.clip(
                np.asarray(z["coverage_conf_3d"], dtype=np.float32)
                * np.asarray(z["cma_temporal_conf_3d"], dtype=np.float32),
                0.0,
                1.0,
            )
        elif confidence_source == "dense":
            conf = np.ones(shape, dtype=np.float32)
        else:
            raise ValueError(f"Unsupported cma_confidence_source={confidence_source}; choose {sorted(CMA_CONFIDENCE_SOURCES)}")
        rapid_change = np.zeros(shape, dtype=np.float32)
        temporal_change = np.zeros(shape, dtype=np.float32)
        temporal_conf = None
        if "cma_rapid_change_flag_3d" in z.files:
            rapid_change = np.asarray(z["cma_rapid_change_flag_3d"], dtype=np.float32)
        if "cma_temporal_change_speed_3d" in z.files:
            temporal_change = np.asarray(z["cma_temporal_change_speed_3d"], dtype=np.float32)
        if "cma_temporal_conf_3d" in z.files:
            temporal_conf = np.clip(np.asarray(z["cma_temporal_conf_3d"], dtype=np.float32), 0.0, 1.0)
        strict_temporal_gate: np.ndarray | None = None
        if qc_gating in {"temporal_change", "strict_temporal"}:
            temporal_conf_already_used = confidence_source in {"temporal_conf", "coverage_temporal_conf"}
            if temporal_conf is not None and not temporal_conf_already_used:
                conf = (conf * temporal_conf).astype(np.float32)
            if rapid_change.shape == shape:
                conf = np.where(rapid_change > 0.0, conf * CMA_RAPID_CHANGE_QC_FACTOR, conf).astype(np.float32)
        if qc_gating == "strict_temporal":
            min_temporal_conf = np.float32(
                np.clip(_cal_float(calibration, "cma_strict_min_temporal_conf", 0.55), 0.0, 1.0)
            )
            max_temporal_change = np.float32(
                max(0.0, _cal_float(calibration, "cma_strict_max_temporal_change_mps", 8.0))
            )
            if temporal_conf is None or temporal_conf.shape != shape:
                temporal_ok = np.zeros(shape, dtype=bool)
            else:
                temporal_ok = np.asarray(temporal_conf, dtype=np.float32) >= min_temporal_conf
            rapid_ok = np.ones(shape, dtype=bool)
            if rapid_change.shape == shape:
                rapid_ok &= np.asarray(rapid_change, dtype=np.float32) <= 0.0
            if temporal_change.shape == shape:
                rapid_ok &= np.asarray(temporal_change, dtype=np.float32) <= max_temporal_change
            strict_temporal_gate = temporal_ok & rapid_ok
            conf = np.where(strict_temporal_gate, conf, 0.0).astype(np.float32)
        meta: dict[str, Any] = {
            "cma_fusion_mode": fusion_mode,
            "cma_proxy_npz": str(path),
            "cma_field_u_key": u_key,
            "cma_field_v_key": v_key,
            "cma_confidence_source": confidence_source,
            "cma_pseudo_source": pseudo_source,
            "cma_qc_gating": qc_gating,
            "cma_qc_temporal_conf_already_in_source": bool(qc_gating == "temporal_change" and confidence_source in {"temporal_conf", "coverage_temporal_conf"}),
            "cma_rapid_change_qc_factor": float(CMA_RAPID_CHANGE_QC_FACTOR),
            "cma_time_str": _scalar_npz_text(z["cma_time_str"]) if "cma_time_str" in z.files else "",
            "cma_time_method": _scalar_npz_text(z["cma_time_method"]) if "cma_time_method" in z.files else "",
        }
        if strict_temporal_gate is not None:
            meta["cma_strict_min_temporal_conf"] = float(_cal_float(calibration, "cma_strict_min_temporal_conf", 0.55))
            meta["cma_strict_max_temporal_change_mps"] = float(_cal_float(calibration, "cma_strict_max_temporal_change_mps", 8.0))
            meta["cma_strict_temporal_gate_active_voxels"] = int(np.count_nonzero(strict_temporal_gate))
            meta["cma_strict_temporal_gate_active_fraction"] = float(np.count_nonzero(strict_temporal_gate) / max(1, strict_temporal_gate.size))
        if "cma_temporal_conf_3d" in z.files:
            temporal_conf = np.asarray(z["cma_temporal_conf_3d"], dtype=np.float32)
            meta["cma_temporal_conf_mean"] = float(np.mean(temporal_conf))
            meta["cma_temporal_conf_p01"] = float(np.percentile(temporal_conf, 1))
        if "cma_temporal_change_speed_3d" in z.files:
            meta["cma_temporal_change_speed_mean_mps"] = float(np.mean(temporal_change))
            meta["cma_temporal_change_speed_p99_mps"] = float(np.percentile(temporal_change, 99))
        if rapid_change.shape == shape:
            meta["cma_rapid_change_voxels"] = int(np.count_nonzero(rapid_change > 0.0))
            meta["cma_rapid_change_fraction"] = float(np.count_nonzero(rapid_change > 0.0) / max(1, rapid_change.size))
        meta["cma_effective_conf_mean"] = float(np.mean(conf))
        meta["cma_effective_conf_p01"] = float(np.percentile(conf, 1))
    if u.shape != shape or v.shape != shape or conf.shape != shape:
        raise ValueError(f"CMA field shape mismatch: {path} has {u.shape}/{v.shape}/{conf.shape}, expected {shape}")
    return u, v, conf, meta


def _apply_cma_background_to_accumulator(
    acc: dict[str, np.ndarray],
    *,
    cma_u: np.ndarray,
    cma_v: np.ndarray,
    cma_conf: np.ndarray,
    background_weight: float,
    time_confidence: float,
    space_confidence: float,
    background_weight_mode: str = "fixed",
    qc_calibration: dict[str, Any] | None = None,
) -> dict[str, Any]:
    background_weight_mode = str(background_weight_mode)
    if background_weight_mode not in CMA_BACKGROUND_WEIGHT_MODES:
        raise ValueError(
            f"Unsupported cma_background_weight_mode={background_weight_mode}; "
            f"choose {sorted(CMA_BACKGROUND_WEIGHT_MODES)}"
        )
    calibration = qc_calibration or DEFAULT_QC_CALIBRATION
    effective_conf = np.clip(cma_conf, 0.0, 1.0).astype(np.float32)
    gate = np.ones_like(effective_conf, dtype=np.float32)
    current_w = np.asarray(acc.get("acc_current_w"), dtype=np.float32)
    support_scale = np.float32(1.0)
    current_density = np.zeros_like(effective_conf, dtype=np.float32)
    sparse_threshold = np.float32(0.0)
    min_effective_conf = np.float32(0.0)
    context_w = np.asarray(acc.get("acc_context_w"), dtype=np.float32)
    localized_support_gate = (current_w > 0.0) | (context_w > 0.0)
    no_current_gate = (current_w <= 0.0) & localized_support_gate
    sparse_current_gate = np.zeros_like(effective_conf, dtype=bool)
    if background_weight_mode in {"diagnostic_gated", "sparse_temporal_gated"}:
        support_scale = np.float32(_positive_percentile_scale(current_w, percentile=90.0, default=1.0))
        current_density = np.clip(current_w / max(float(support_scale), 1e-6), 0.0, 1.0).astype(np.float32)
        sparse_threshold = np.float32(
            np.clip(_cal_float(calibration, "cma_gated_sparse_current_norm_threshold", 0.18), 0.0, 1.0)
        )
        min_effective_conf = np.float32(
            np.clip(_cal_float(calibration, "cma_gated_min_effective_conf", 0.02), 0.0, 1.0)
        )
        sparse_factor = np.clip((sparse_threshold - current_density) / max(float(sparse_threshold), 1e-6), 0.0, 1.0)
        gate = np.where(effective_conf >= min_effective_conf, sparse_factor, 0.0).astype(np.float32)
        if background_weight_mode == "sparse_temporal_gated":
            gate = np.where(localized_support_gate, gate, 0.0).astype(np.float32)
        sparse_current_gate = gate > 0.0
    weight = (effective_conf * gate * np.float32(max(0.0, background_weight))).astype(np.float32)
    mask = weight > 0.0
    if not np.any(mask):
        return {
            "cma_background_weight": float(background_weight),
            "cma_background_weight_mode": background_weight_mode,
            "cma_background_active_voxels": 0,
            "cma_background_weight_sum": 0.0,
            "cma_background_speed_mean_mps": 0.0,
            "cma_background_speed_max_mps": 0.0,
            "cma_background_gate_mean": float(np.mean(gate)),
            "cma_background_gate_active_fraction": 0.0,
            "cma_background_current_density_scale": float(support_scale),
            "cma_background_sparse_current_norm_threshold": float(sparse_threshold),
            "cma_background_min_effective_conf": float(min_effective_conf),
            "cma_background_no_current_gate_voxels": int(np.count_nonzero(no_current_gate)),
            "cma_background_localized_support_gate_voxels": int(np.count_nonzero(localized_support_gate)),
            "cma_background_localized_support_gate_fraction": float(np.count_nonzero(localized_support_gate) / max(1, localized_support_gate.size)),
            "cma_background_sparse_current_gate_voxels": int(np.count_nonzero(sparse_current_gate)),
            "cma_background_sparse_current_gate_fraction": float(np.count_nonzero(sparse_current_gate) / max(1, sparse_current_gate.size)),
        }
    acc["acc_u"] += cma_u.astype(np.float32) * weight
    acc["acc_v"] += cma_v.astype(np.float32) * weight
    acc["acc_w"] += weight
    acc["acc_time"] += np.float32(np.clip(time_confidence, 0.0, 1.0)) * weight
    acc["acc_space"] += np.float32(np.clip(space_confidence, 0.0, 1.0)) * weight
    acc["source_mask"] = np.asarray(acc["source_mask"], dtype=bool) | mask
    speed = np.sqrt(cma_u.astype(np.float32) ** 2 + cma_v.astype(np.float32) ** 2)
    return {
        "cma_background_weight": float(background_weight),
        "cma_background_weight_mode": background_weight_mode,
        "cma_background_active_voxels": int(np.count_nonzero(mask)),
        "cma_background_weight_sum": float(np.sum(weight)),
        "cma_background_speed_mean_mps": float(np.mean(speed[mask])),
        "cma_background_speed_max_mps": float(np.max(speed[mask])),
        "cma_background_gate_mean": float(np.mean(gate)),
        "cma_background_gate_active_fraction": float(np.count_nonzero(gate > 0.0) / max(1, gate.size)),
        "cma_background_current_density_scale": float(support_scale),
        "cma_background_sparse_current_norm_threshold": float(sparse_threshold),
        "cma_background_min_effective_conf": float(min_effective_conf),
        "cma_background_no_current_gate_voxels": int(np.count_nonzero(no_current_gate)),
        "cma_background_localized_support_gate_voxels": int(np.count_nonzero(localized_support_gate)),
        "cma_background_localized_support_gate_fraction": float(np.count_nonzero(localized_support_gate) / max(1, localized_support_gate.size)),
        "cma_background_sparse_current_gate_voxels": int(np.count_nonzero(sparse_current_gate)),
        "cma_background_sparse_current_gate_fraction": float(np.count_nonzero(sparse_current_gate) / max(1, sparse_current_gate.size)),
    }


def _cap_cma_only_confidence(
    recon: dict[str, np.ndarray],
    acc: dict[str, np.ndarray],
    *,
    cma_confidence_cap: float,
) -> dict[str, np.ndarray]:
    cma_confidence_cap = float(np.clip(cma_confidence_cap, 0.0, 1.0))
    if cma_confidence_cap >= 1.0:
        return recon
    obs_supported = (np.asarray(acc.get("acc_current_w"), dtype=np.float32) > 0.0) | (
        np.asarray(acc.get("acc_context_w"), dtype=np.float32) > 0.0
    )
    active = np.asarray(recon["recon_mask"], dtype=np.float32) > 0.0
    cma_only = active & ~obs_supported
    if not np.any(cma_only):
        return recon
    capped = dict(recon)
    conf = np.asarray(capped["recon_conf"], dtype=np.float32).copy()
    conf[cma_only] = np.minimum(conf[cma_only], np.float32(cma_confidence_cap))
    capped["recon_conf"] = conf
    capped["c_joint"] = conf
    return capped


def _make_reconstruction(acc: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    weight = acc["acc_w"]
    mask = weight > 0
    recon_u = np.divide(acc["acc_u"], np.maximum(weight, 1e-6), out=np.zeros_like(weight), where=mask).astype(np.float32)
    recon_v = np.divide(acc["acc_v"], np.maximum(weight, 1e-6), out=np.zeros_like(weight), where=mask).astype(np.float32)
    c_time = np.divide(acc["acc_time"], np.maximum(weight, 1e-6), out=np.zeros_like(weight), where=mask).astype(np.float32)
    c_space = np.divide(acc["acc_space"], np.maximum(weight, 1e-6), out=np.zeros_like(weight), where=mask).astype(np.float32)
    recon_conf = _normalize_confidence(weight)
    recon_mask = mask.astype(np.float32)
    blindzone_initialized = (mask & ~acc["source_mask"]).astype(np.float32)
    return {
        "recon_u": recon_u,
        "recon_v": recon_v,
        "recon_conf": recon_conf,
        "recon_mask": recon_mask,
        "c_time": c_time,
        "c_space": c_space,
        "c_joint": recon_conf,
        "blindzone_initialized": blindzone_initialized,
        "weight": weight,
    }


def _neighbor_mean_3d(field: np.ndarray) -> np.ndarray:
    pad = np.pad(field, ((1, 1), (1, 1), (1, 1)), mode="edge")
    return (
        pad[1:-1, 1:-1, :-2]
        + pad[1:-1, 1:-1, 2:]
        + pad[1:-1, :-2, 1:-1]
        + pad[1:-1, 2:, 1:-1]
        + pad[:-2, 1:-1, 1:-1]
        + pad[2:, 1:-1, 1:-1]
    ) / 6.0


def _horizontal_neighbor_mean_3d(field: np.ndarray) -> np.ndarray:
    pad = np.pad(field, ((0, 0), (1, 1), (1, 1)), mode="edge")
    return (
        pad[:, 1:-1, :-2]
        + pad[:, 1:-1, 2:]
        + pad[:, :-2, 1:-1]
        + pad[:, 2:, 1:-1]
    ) / 4.0


def _neighbor_mean_masked(field: np.ndarray, mask: np.ndarray) -> np.ndarray:
    values = field * mask.astype(np.float32)
    pad_values = np.pad(values, ((1, 1), (1, 1), (1, 1)), mode="constant", constant_values=0.0)
    pad_mask = np.pad(mask.astype(np.float32), ((1, 1), (1, 1), (1, 1)), mode="constant", constant_values=0.0)
    value_sum = (
        pad_values[1:-1, 1:-1, :-2]
        + pad_values[1:-1, 1:-1, 2:]
        + pad_values[1:-1, :-2, 1:-1]
        + pad_values[1:-1, 2:, 1:-1]
        + pad_values[:-2, 1:-1, 1:-1]
        + pad_values[2:, 1:-1, 1:-1]
    )
    count = (
        pad_mask[1:-1, 1:-1, :-2]
        + pad_mask[1:-1, 1:-1, 2:]
        + pad_mask[1:-1, :-2, 1:-1]
        + pad_mask[1:-1, 2:, 1:-1]
        + pad_mask[:-2, 1:-1, 1:-1]
        + pad_mask[2:, 1:-1, 1:-1]
    )
    return np.divide(value_sum, np.maximum(count, 1e-6), out=field.copy(), where=count > 0).astype(np.float32)


def _pinn_diffusion_refine(
    recon: dict[str, np.ndarray],
    *,
    iterations: int,
    pinn_smoothness_weight: float,
    pinn_divergence_weight: float,
    diffusion_weight: float,
    low_conf_fill_weight: float,
    source_preserve: float,
    physics_constraint_mode: str = "proxy",
    observation_anchor_weight: float = 0.10,
    speed_limit_mps: float = 120.0,
    vertical_risk_mode: str = "off",
    vertical_gradient_preserve_weight: float = 0.12,
    vertical_context_mismatch_damping: float = 0.35,
) -> tuple[dict[str, np.ndarray], dict[str, float]]:
    """Proxy refinement: smooth/propagate low-confidence gaps without hold-out labels.

    This is not a trained PINN or denoising diffusion model. It is a documented
    Stage4 proxy: divergence/smoothness penalties mimic PINN regularization and
    repeated neighbor blending mimics diffusion-style local propagation.
    """

    physics_constraint_mode = str(physics_constraint_mode)
    if physics_constraint_mode not in PHYSICS_CONSTRAINT_MODES:
        raise ValueError(
            f"Unsupported physics_constraint_mode={physics_constraint_mode}; "
            f"choose {sorted(PHYSICS_CONSTRAINT_MODES)}"
        )
    vertical_risk_mode = str(vertical_risk_mode)
    if vertical_risk_mode not in VERTICAL_RISK_MODES:
        raise ValueError(
            f"Unsupported vertical_risk_mode={vertical_risk_mode}; "
            f"choose {sorted(VERTICAL_RISK_MODES)}"
        )
    iterations = max(0, int(iterations))
    vertical_preserve_w = float(np.clip(vertical_gradient_preserve_weight, 0.0, 1.0))
    vertical_context_damping = float(np.clip(vertical_context_mismatch_damping, 0.0, 1.0))
    if iterations == 0:
        return recon, {
            "pinn_diffusion_refine_enabled": 0.0,
            "physics_constraint_mode": physics_constraint_mode,
            "pinn_proxy_iterations": 0.0,
            "pinn_loss_divergence_proxy": 0.0,
            "pinn_loss_smoothness_proxy": 0.0,
            "diffusion_fill_new_voxels": 0.0,
            "speed_limit_mps": float(speed_limit_mps),
            "observation_anchor_weight": float(observation_anchor_weight),
            "vertical_risk_mode": vertical_risk_mode,
            "vertical_gradient_preserve_weight": float(vertical_preserve_w),
            "vertical_context_mismatch_damping": float(vertical_context_damping),
            "vertical_risk_refine_enabled": 0.0,
            "vertical_risk_candidate_voxels_last": 0.0,
            "vertical_oversmooth_preserve_voxels_last": 0.0,
            "vertical_context_mismatch_damped_voxels_last": 0.0,
        }

    u = recon["recon_u"].astype(np.float32).copy()
    v = recon["recon_v"].astype(np.float32).copy()
    anchor_u = recon["recon_u"].astype(np.float32).copy()
    anchor_v = recon["recon_v"].astype(np.float32).copy()
    conf = recon["recon_conf"].astype(np.float32).copy()
    source_mask = recon["weight"] > 0
    pre_mask = recon["recon_mask"] > 0
    source_preserve = float(np.clip(source_preserve, 0.0, 1.0))
    anchor_w = float(np.clip(observation_anchor_weight, 0.0, 1.0))
    speed_limit_mps = float(max(1e-6, speed_limit_mps))
    smooth_w = float(max(0.0, pinn_smoothness_weight))
    div_w = float(max(0.0, pinn_divergence_weight))
    diff_w = float(max(0.0, diffusion_weight))
    fill_w = float(np.clip(low_conf_fill_weight, 0.0, 1.0))

    last_div = 0.0
    last_smooth = 0.0
    last_vertical_risk = 0
    last_vertical_oversmooth = 0
    last_vertical_context = 0
    for _ in range(iterations):
        u_mean = _neighbor_mean_3d(u)
        v_mean = _neighbor_mean_3d(v)
        conf_mean = _neighbor_mean_3d(conf)
        du_dx = np.gradient(u, axis=2)
        dv_dy = np.gradient(v, axis=1)
        div = du_dx + dv_dy
        div_grad_x = np.gradient(div, axis=2)
        div_grad_y = np.gradient(div, axis=1)
        low_conf = np.clip(1.0 - conf, 0.0, 1.0)
        update_gain = np.clip(diff_w * low_conf + smooth_w, 0.0, 0.65).astype(np.float32)
        preserve = np.where(source_mask, source_preserve, 0.0).astype(np.float32)
        vertical_oversmooth_mask = np.zeros_like(conf, dtype=bool)
        vertical_context_mask = np.zeros_like(conf, dtype=bool)
        vertical_risk_mask = np.zeros_like(conf, dtype=bool)
        if vertical_risk_mode == "preserve_strong_layers":
            speed = np.sqrt(u**2 + v**2).astype(np.float32)
            vertical_jump = _vertical_jump_field(u, v)
            vertical_neighbor_mean, _ = _vertical_neighbor_speed_stats(u, v)
            active_mask = conf > EFFECTIVE_CONF_THRESHOLD
            strong_mask = active_mask & (speed >= STRONG_WIND_DIAGNOSTIC_THRESHOLD_MPS)
            vertical_oversmooth_mask = strong_mask & (vertical_jump <= VERTICAL_OVERSMOOTH_JUMP_THRESHOLD_MPS)
            vertical_context_mask = strong_mask & (
                np.abs(speed - vertical_neighbor_mean) >= RAPID_VERTICAL_JUMP_DIAGNOSTIC_THRESHOLD_MPS
            )
            vertical_risk_mask = vertical_oversmooth_mask | vertical_context_mask
            if np.any(vertical_risk_mask) and vertical_context_damping > 0.0:
                update_gain = np.where(
                    vertical_risk_mask,
                    update_gain * np.float32(1.0 - vertical_context_damping),
                    update_gain,
                ).astype(np.float32)
            if np.any(vertical_risk_mask):
                u_mean_horizontal = _horizontal_neighbor_mean_3d(u)
                v_mean_horizontal = _horizontal_neighbor_mean_3d(v)
                u_mean = np.where(vertical_risk_mask, u_mean_horizontal, u_mean).astype(np.float32)
                v_mean = np.where(vertical_risk_mask, v_mean_horizontal, v_mean).astype(np.float32)

        candidate_u = u + update_gain * (u_mean - u) - div_w * div_grad_x
        candidate_v = v + update_gain * (v_mean - v) - div_w * div_grad_y
        if physics_constraint_mode == "pydda_3dvar_proxy":
            active_mask = conf > EFFECTIVE_CONF_THRESHOLD
            support_mean_u = _neighbor_mean_masked(candidate_u, active_mask)
            support_mean_v = _neighbor_mean_masked(candidate_v, active_mask)
            candidate_u = candidate_u + smooth_w * low_conf * (support_mean_u - candidate_u)
            candidate_v = candidate_v + smooth_w * low_conf * (support_mean_v - candidate_v)
            candidate_u = candidate_u + anchor_w * conf * (anchor_u - candidate_u)
            candidate_v = candidate_v + anchor_w * conf * (anchor_v - candidate_v)
            candidate_speed = np.sqrt(candidate_u**2 + candidate_v**2)
            speed_scale = np.minimum(1.0, speed_limit_mps / np.maximum(candidate_speed, 1e-6)).astype(np.float32)
            candidate_u = candidate_u * speed_scale
            candidate_v = candidate_v * speed_scale
        if vertical_risk_mode == "preserve_strong_layers" and np.any(vertical_risk_mask):
            preserve_weight = (vertical_preserve_w * np.clip(conf, 0.0, 1.0)).astype(np.float32)
            context_weight = (vertical_context_damping * np.clip(conf, 0.0, 1.0)).astype(np.float32)
            candidate_u = np.where(
                vertical_oversmooth_mask,
                (1.0 - preserve_weight) * candidate_u + preserve_weight * anchor_u,
                candidate_u,
            ).astype(np.float32)
            candidate_v = np.where(
                vertical_oversmooth_mask,
                (1.0 - preserve_weight) * candidate_v + preserve_weight * anchor_v,
                candidate_v,
            ).astype(np.float32)
            candidate_u = np.where(
                vertical_context_mask,
                (1.0 - context_weight) * candidate_u + context_weight * anchor_u,
                candidate_u,
            ).astype(np.float32)
            candidate_v = np.where(
                vertical_context_mask,
                (1.0 - context_weight) * candidate_v + context_weight * anchor_v,
                candidate_v,
            ).astype(np.float32)
        u = preserve * u + (1.0 - preserve) * candidate_u
        v = preserve * v + (1.0 - preserve) * candidate_v
        conf = np.maximum(conf, np.clip(conf_mean * fill_w, 0.0, 0.45).astype(np.float32))

        last_div = float(np.mean(np.abs(div)))
        last_smooth = float(np.mean(np.sqrt((u_mean - u) ** 2 + (v_mean - v) ** 2)))
        last_vertical_risk = int(np.count_nonzero(vertical_risk_mask))
        last_vertical_oversmooth = int(np.count_nonzero(vertical_oversmooth_mask))
        last_vertical_context = int(np.count_nonzero(vertical_context_mask))

    mask = conf > EFFECTIVE_CONF_THRESHOLD
    conf = np.where(mask, conf, 0.0).astype(np.float32)
    u = np.where(mask, u, 0.0).astype(np.float32)
    v = np.where(mask, v, 0.0).astype(np.float32)
    refined = dict(recon)
    refined["recon_u"] = u
    refined["recon_v"] = v
    refined["recon_conf"] = conf
    refined["recon_mask"] = mask.astype(np.float32)
    refined["c_joint"] = conf
    refined["blindzone_initialized"] = (mask & ~source_mask).astype(np.float32)
    new_voxels = int(np.count_nonzero(mask & ~pre_mask))
    return refined, {
        "pinn_diffusion_refine_enabled": 1.0,
        "physics_constraint_mode": physics_constraint_mode,
        "pinn_proxy_iterations": float(iterations),
        "pinn_loss_divergence_proxy": last_div,
        "pinn_loss_smoothness_proxy": last_smooth,
        "diffusion_fill_new_voxels": float(new_voxels),
        "low_conf_fill_weight": float(fill_w),
        "source_preserve": float(source_preserve),
        "observation_anchor_weight": float(anchor_w),
        "speed_limit_mps": float(speed_limit_mps),
        "vertical_risk_mode": vertical_risk_mode,
        "vertical_gradient_preserve_weight": float(vertical_preserve_w),
        "vertical_context_mismatch_damping": float(vertical_context_damping),
        "vertical_risk_refine_enabled": 1.0 if vertical_risk_mode != "off" else 0.0,
        "vertical_risk_candidate_voxels_last": float(last_vertical_risk),
        "vertical_oversmooth_preserve_voxels_last": float(last_vertical_oversmooth),
        "vertical_context_mismatch_damped_voxels_last": float(last_vertical_context),
    }


def _finalize_effective_reconstruction(recon: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    """Keep mask, confidence, wind and diagnostics on one effective support."""

    mask = np.asarray(recon["recon_conf"], dtype=np.float32) > EFFECTIVE_CONF_THRESHOLD
    finalized = dict(recon)
    finalized["recon_u"] = np.where(mask, recon["recon_u"], 0.0).astype(np.float32)
    finalized["recon_v"] = np.where(mask, recon["recon_v"], 0.0).astype(np.float32)
    finalized["recon_conf"] = np.where(mask, recon["recon_conf"], 0.0).astype(np.float32)
    finalized["recon_mask"] = mask.astype(np.float32)
    finalized["c_time"] = np.where(mask, recon["c_time"], 0.0).astype(np.float32)
    finalized["c_space"] = np.where(mask, recon["c_space"], 0.0).astype(np.float32)
    finalized["c_joint"] = finalized["recon_conf"]
    finalized["blindzone_initialized"] = (mask & (np.asarray(recon["blindzone_initialized"]) > 0)).astype(np.float32)
    finalized["weight"] = np.asarray(recon["weight"], dtype=np.float32)
    return finalized


def _display_fill_fusion_mode(display_fill_source: str) -> str:
    if display_fill_source == "cma_proxy":
        return "cma_proxy_background"
    return "cma_reanalysis_background"


def _make_display_filled_field(
    recon: dict[str, np.ndarray],
    *,
    shape: tuple[int, int, int],
    time_str: str,
    display_fill_mode: str,
    display_fill_cma_proxy_dir: Path | None,
    display_fill_source: str,
    display_fill_confidence_cap: float,
    display_fill_qc_gating: str,
    qc_calibration: dict[str, Any],
) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    display_fill_mode = str(display_fill_mode)
    if display_fill_mode not in DISPLAY_FILL_MODES:
        raise ValueError(f"Unsupported display_fill_mode={display_fill_mode}; choose {sorted(DISPLAY_FILL_MODES)}")
    display_fill_source = str(display_fill_source)
    if display_fill_source not in DISPLAY_FILL_SOURCES:
        raise ValueError(f"Unsupported display_fill_source={display_fill_source}; choose {sorted(DISPLAY_FILL_SOURCES)}")
    display_fill_qc_gating = str(display_fill_qc_gating)
    if display_fill_qc_gating not in CMA_QC_GATING_MODES:
        raise ValueError(f"Unsupported display_fill_qc_gating={display_fill_qc_gating}; choose {sorted(CMA_QC_GATING_MODES)}")

    official_mask = np.asarray(recon["recon_mask"], dtype=np.float32) > 0.0
    display_u = np.asarray(recon["recon_u"], dtype=np.float32).copy()
    display_v = np.asarray(recon["recon_v"], dtype=np.float32).copy()
    display_conf = np.asarray(recon["recon_conf"], dtype=np.float32).copy()
    display_mask = official_mask.astype(np.float32)
    display_source = np.where(official_mask, 1, 0).astype(np.uint8)
    diagnostics: dict[str, Any] = {
        "display_fill_mode": display_fill_mode,
        "display_fill_source": display_fill_source,
        "display_fill_qc_gating": display_fill_qc_gating,
        "display_fill_is_official_accuracy": False,
        "display_fill_note": "Display-only weak background fill. Official recon_u/v/conf/mask and strict holdout metrics are unchanged.",
        "display_official_voxels": int(np.count_nonzero(official_mask)),
        "display_background_voxels": 0,
        "display_total_voxels": int(np.prod(shape)),
        "display_background_confidence_cap": float(np.clip(display_fill_confidence_cap, 0.0, 1.0)),
    }
    if display_fill_mode == "off":
        diagnostics["display_active_voxels"] = int(np.count_nonzero(display_mask > 0.0))
        return (
            {
                "display_u": display_u,
                "display_v": display_v,
                "display_conf": display_conf,
                "display_mask": display_mask,
                "display_source": display_source,
            },
            diagnostics,
        )

    cma_path = _find_cma_proxy_npz(display_fill_cma_proxy_dir, time_str)
    if cma_path is None:
        diagnostics["display_fill_warning"] = "CMA proxy NPZ not found; display field falls back to official recon only."
        diagnostics["display_active_voxels"] = int(np.count_nonzero(display_mask > 0.0))
        return (
            {
                "display_u": display_u,
                "display_v": display_v,
                "display_conf": display_conf,
                "display_mask": display_mask,
                "display_source": display_source,
            },
            diagnostics,
        )

    cma_u, cma_v, cma_conf, cma_meta = _load_cma_background(
        cma_path,
        shape,
        fusion_mode=_display_fill_fusion_mode(display_fill_source),
        confidence_source="temporal_conf",
        pseudo_source="proxy" if display_fill_source == "cma_proxy" else "reanalysis",
        qc_gating=display_fill_qc_gating,
        qc_calibration=qc_calibration,
    )
    background_mask = ~official_mask
    cap = float(np.clip(display_fill_confidence_cap, 0.0, 1.0))
    floor_conf = np.float32(max(0.0, min(cap, cap * 0.05)))
    background_conf = np.clip(np.asarray(cma_conf, dtype=np.float32), 0.0, cap).astype(np.float32)
    if cap > 0.0:
        background_conf = np.where(background_conf > 0.0, background_conf, floor_conf).astype(np.float32)
    display_u = np.where(official_mask, display_u, cma_u.astype(np.float32)).astype(np.float32)
    display_v = np.where(official_mask, display_v, cma_v.astype(np.float32)).astype(np.float32)
    display_conf = np.where(official_mask, display_conf, background_conf).astype(np.float32)
    display_mask = np.ones(shape, dtype=np.float32)
    display_source = np.where(official_mask, 1, 2).astype(np.uint8)
    diagnostics.update(cma_meta)
    diagnostics.update(
        {
            "display_cma_proxy_npz": str(cma_path),
            "display_active_voxels": int(display_mask.size),
            "display_background_voxels": int(np.count_nonzero(background_mask)),
            "display_background_confidence_mean": float(np.mean(display_conf[background_mask])) if np.any(background_mask) else 0.0,
            "display_background_confidence_min": float(np.min(display_conf[background_mask])) if np.any(background_mask) else 0.0,
            "display_background_confidence_max": float(np.max(display_conf[background_mask])) if np.any(background_mask) else 0.0,
            "display_source_code_1": "official_tp26_reconstruction",
            "display_source_code_2": "low_confidence_weak_background_display_only",
        }
    )
    return (
        {
            "display_u": display_u,
            "display_v": display_v,
            "display_conf": display_conf,
            "display_mask": display_mask,
            "display_source": display_source,
        },
        diagnostics,
    )


def _idx_to_geo_bbox(
    shape: tuple[int, int, int],
    z_min: int,
    z_max: int,
    y_min: int,
    y_max: int,
    x_min: int,
    x_max: int,
) -> dict[str, float]:
    _, h_dim, w_dim = shape
    lat_north = LAT_MAX - (float(y_min) / float(h_dim)) * (LAT_MAX - LAT_MIN)
    lat_south = LAT_MAX - (float(y_max + 1) / float(h_dim)) * (LAT_MAX - LAT_MIN)
    lon_west = LON_MIN + (float(x_min) / float(w_dim)) * (LON_MAX - LON_MIN)
    lon_east = LON_MIN + (float(x_max + 1) / float(w_dim)) * (LON_MAX - LON_MIN)
    return {
        "bbox_lat_min": float(lat_south),
        "bbox_lat_max": float(lat_north),
        "bbox_lon_min": float(lon_west),
        "bbox_lon_max": float(lon_east),
        "bbox_alt_min_m": float(ALT_MIN + z_min * DELTA_ALT),
        "bbox_alt_max_m": float(ALT_MIN + z_max * DELTA_ALT),
    }


def _reconstruction_extent_stats(recon: dict[str, np.ndarray], pre_refine_voxels: int) -> dict[str, Any]:
    mask = np.asarray(recon["recon_mask"]) > 0
    blind = np.asarray(recon["blindzone_initialized"]) > 0
    conf = np.asarray(recon["recon_conf"], dtype=np.float32)
    speed = np.sqrt(np.asarray(recon["recon_u"], dtype=np.float32) ** 2 + np.asarray(recon["recon_v"], dtype=np.float32) ** 2)
    total = int(mask.size)
    active = int(np.count_nonzero(mask))
    fill = int(np.count_nonzero(mask & blind))
    support = int(pre_refine_voxels)
    stats: dict[str, Any] = {
        "grid_total_voxels": total,
        "effective_reconstructed_voxels": active,
        "effective_reconstructed_fraction": float(active / total) if total else 0.0,
        "support_pre_refine_voxels": support,
        "support_pre_refine_fraction": float(support / total) if total else 0.0,
        "low_conf_fill_voxels": fill,
        "low_conf_fill_fraction": float(fill / total) if total else 0.0,
        "confidence_threshold_effective": float(EFFECTIVE_CONF_THRESHOLD),
        "confidence_positive_voxels": int(np.count_nonzero(conf > 0.0)),
        "mask_conf_positive_mismatch_voxels": int(np.count_nonzero((conf > 0.0) != mask)),
    }
    if active == 0:
        stats.update(
            {
                "bbox_z_min": -1,
                "bbox_z_max": -1,
                "bbox_y_min": -1,
                "bbox_y_max": -1,
                "bbox_x_min": -1,
                "bbox_x_max": -1,
                "bbox_lat_min": 0.0,
                "bbox_lat_max": 0.0,
                "bbox_lon_min": 0.0,
                "bbox_lon_max": 0.0,
                "bbox_alt_min_m": 0.0,
                "bbox_alt_max_m": 0.0,
                "speed_active_min_mps": 0.0,
                "speed_active_mean_mps": 0.0,
                "speed_active_max_mps": 0.0,
                "confidence_active_mean": 0.0,
                "confidence_active_max": 0.0,
            }
        )
        return stats

    zz, yy, xx = np.where(mask)
    z_min, z_max = int(zz.min()), int(zz.max())
    y_min, y_max = int(yy.min()), int(yy.max())
    x_min, x_max = int(xx.min()), int(xx.max())
    stats.update(
        {
            "bbox_z_min": z_min,
            "bbox_z_max": z_max,
            "bbox_y_min": y_min,
            "bbox_y_max": y_max,
            "bbox_x_min": x_min,
            "bbox_x_max": x_max,
            **_idx_to_geo_bbox(mask.shape, z_min, z_max, y_min, y_max, x_min, x_max),
            "speed_active_min_mps": float(np.min(speed[mask])),
            "speed_active_mean_mps": float(np.mean(speed[mask])),
            "speed_active_max_mps": float(np.max(speed[mask])),
            "confidence_active_mean": float(np.mean(conf[mask])),
            "confidence_active_max": float(np.max(conf[mask])),
        }
    )
    return stats


def _vertical_jump_field(u: np.ndarray, v: np.ndarray) -> np.ndarray:
    u_arr = np.asarray(u, dtype=np.float32)
    v_arr = np.asarray(v, dtype=np.float32)
    jump = np.zeros_like(u_arr, dtype=np.float32)
    if u_arr.shape[0] <= 1:
        return jump
    pair_jump = np.sqrt(np.diff(u_arr, axis=0) ** 2 + np.diff(v_arr, axis=0) ** 2).astype(np.float32)
    jump[:-1] = np.maximum(jump[:-1], pair_jump)
    jump[1:] = np.maximum(jump[1:], pair_jump)
    return jump


def _vertical_neighbor_speed_stats(u: np.ndarray, v: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    u_arr = np.asarray(u, dtype=np.float32)
    v_arr = np.asarray(v, dtype=np.float32)
    speed = np.sqrt(u_arr**2 + v_arr**2).astype(np.float32)
    lower = np.empty_like(speed, dtype=np.float32)
    upper = np.empty_like(speed, dtype=np.float32)
    lower[0] = speed[0]
    lower[1:] = speed[:-1]
    upper[-1] = speed[-1]
    upper[:-1] = speed[1:]
    vertical_neighbor_mean = ((lower + upper) * 0.5).astype(np.float32)
    vertical_neighbor_max = np.maximum(lower, upper).astype(np.float32)
    return vertical_neighbor_mean, vertical_neighbor_max


def _field_proxy_diagnostics(recon: dict[str, np.ndarray]) -> dict[str, float | int]:
    mask = np.asarray(recon["recon_mask"]) > 0
    if not np.any(mask):
        return {
            "field_smoothness_proxy": 0.0,
            "field_horizontal_divergence_proxy": 0.0,
            "field_vertical_shear_proxy": 0.0,
            "field_vertical_jump_mean_mps": 0.0,
            "field_vertical_jump_p95_mps": 0.0,
            "field_vertical_jump_p99_mps": 0.0,
            "strong_wind_voxels": 0,
            "rapid_vertical_change_voxels": 0,
            "strong_rapid_vertical_voxels": 0,
            "strong_layer_vertical_jump_mean_mps": 0.0,
            "vertical_oversmoothing_candidate_voxels": 0,
            "vertical_oversmoothing_candidate_fraction": 0.0,
            "vertical_context_mismatch_candidate_voxels": 0,
            "vertical_context_mismatch_candidate_fraction": 0.0,
            "strong_vertical_isolated_voxels": 0,
            "strong_vertical_isolated_fraction": 0.0,
            "speed_plausibility_violation_voxels": 0,
            "speed_plausibility_violation_fraction": 0.0,
        }
    u = np.asarray(recon["recon_u"], dtype=np.float32)
    v = np.asarray(recon["recon_v"], dtype=np.float32)
    speed = np.sqrt(u**2 + v**2)
    u_mean = _neighbor_mean_3d(u)
    v_mean = _neighbor_mean_3d(v)
    du_dx = np.gradient(u, axis=2)
    dv_dy = np.gradient(v, axis=1)
    du_dz = np.gradient(u, axis=0)
    dv_dz = np.gradient(v, axis=0)
    divergence = du_dx + dv_dy
    shear = np.sqrt(du_dz**2 + dv_dz**2)
    vertical_jump = _vertical_jump_field(u, v)
    vertical_active = vertical_jump[mask]
    strong_wind = mask & (speed >= STRONG_WIND_DIAGNOSTIC_THRESHOLD_MPS)
    rapid_vertical = mask & (vertical_jump >= RAPID_VERTICAL_JUMP_DIAGNOSTIC_THRESHOLD_MPS)
    strong_rapid = strong_wind & rapid_vertical
    oversmooth_candidate = strong_wind & (vertical_jump <= VERTICAL_OVERSMOOTH_JUMP_THRESHOLD_MPS)
    vertical_neighbor_mean, vertical_neighbor_max = _vertical_neighbor_speed_stats(u, v)
    vertical_speed_gap = np.abs(speed - vertical_neighbor_mean)
    isolated_strong = strong_wind & (vertical_neighbor_max < STRONG_WIND_DIAGNOSTIC_THRESHOLD_MPS * 0.70)
    context_mismatch_candidate = strong_wind & (vertical_speed_gap >= RAPID_VERTICAL_JUMP_DIAGNOSTIC_THRESHOLD_MPS)
    violations = speed > 120.0
    strong_count = int(np.count_nonzero(strong_wind))
    active_count = max(1, int(np.count_nonzero(mask)))
    return {
        "field_smoothness_proxy": float(np.mean(np.sqrt((u_mean[mask] - u[mask]) ** 2 + (v_mean[mask] - v[mask]) ** 2))),
        "field_horizontal_divergence_proxy": float(np.mean(np.abs(divergence[mask]))),
        "field_vertical_shear_proxy": float(np.mean(shear[mask])),
        "field_vertical_jump_mean_mps": float(np.mean(vertical_active)),
        "field_vertical_jump_p95_mps": float(np.percentile(vertical_active, 95)),
        "field_vertical_jump_p99_mps": float(np.percentile(vertical_active, 99)),
        "strong_wind_voxels": strong_count,
        "rapid_vertical_change_voxels": int(np.count_nonzero(rapid_vertical)),
        "strong_rapid_vertical_voxels": int(np.count_nonzero(strong_rapid)),
        "strong_layer_vertical_jump_mean_mps": float(np.mean(vertical_jump[strong_wind])) if strong_count > 0 else 0.0,
        "vertical_oversmoothing_candidate_voxels": int(np.count_nonzero(oversmooth_candidate)),
        "vertical_oversmoothing_candidate_fraction": float(np.count_nonzero(oversmooth_candidate) / max(1, strong_count)),
        "vertical_context_mismatch_candidate_voxels": int(np.count_nonzero(context_mismatch_candidate)),
        "vertical_context_mismatch_candidate_fraction": float(np.count_nonzero(context_mismatch_candidate) / max(1, strong_count)),
        "strong_vertical_isolated_voxels": int(np.count_nonzero(isolated_strong)),
        "strong_vertical_isolated_fraction": float(np.count_nonzero(isolated_strong) / max(1, strong_count)),
        "speed_plausibility_violation_voxels": int(np.count_nonzero(violations & mask)),
        "speed_plausibility_violation_fraction": float(np.count_nonzero(violations & mask) / active_count),
    }


def _role_conflict_diagnostics(acc: dict[str, np.ndarray]) -> dict[str, float | int]:
    conflict_mask = np.asarray(acc.get("role_conflict_mask"), dtype=bool)
    current_w = np.asarray(acc.get("acc_current_w"), dtype=np.float32)
    context_w = np.asarray(acc.get("acc_context_w"), dtype=np.float32)
    conflict_context_w = np.asarray(acc.get("conflict_context_w"), dtype=np.float32)
    conflict_context_removed_w = np.asarray(acc.get("conflict_context_removed_w"), dtype=np.float32)
    scalar_diag = acc.get("role_conflict_scalar_diagnostics", {})
    scalar_diag = scalar_diag if isinstance(scalar_diag, dict) else {}
    both_roles = (current_w > 0.0) & (context_w > 0.0)
    out: dict[str, float | int] = {
        "role_conflict_voxels": int(np.count_nonzero(conflict_mask)),
        "role_overlap_voxels": int(np.count_nonzero(both_roles)),
        "role_conflict_fraction_of_overlap": float(np.count_nonzero(conflict_mask) / max(1, int(np.count_nonzero(both_roles)))),
        "role_conflict_context_weight_sum": float(np.sum(conflict_context_w)),
        "role_conflict_context_weight_removed_sum": float(np.sum(conflict_context_removed_w)),
    }
    for key, value in scalar_diag.items():
        if isinstance(value, str):
            continue
        if isinstance(value, (int, float, np.integer, np.floating)):
            out[key] = float(value)
    return out


def _leakage_report(
    *,
    wind_records: list[dict[str, Any]],
    train_wind: list[dict[str, Any]],
    holdout_wind: list[dict[str, Any]],
    observations: list[dict[str, Any]],
    motion_records: list[dict[str, Any]],
    context_motion_records: list[dict[str, Any]],
    cma_fusion_mode: str = "off",
    cma_proxy_npz: str = "",
) -> dict[str, Any]:
    wind_ids = {_record_identity(row) for row in wind_records}
    train_ids = {_record_identity(row) for row in train_wind}
    holdout_ids = {_record_identity(row) for row in holdout_wind}
    overlap = sorted(train_ids & holdout_ids)
    holdout_not_from_wind = sorted(holdout_ids - wind_ids)
    bad_sources = sorted({str(row.get("source_role")) for row in observations if str(row.get("source_role")) not in {"current_wind_train", "context_wind"}})
    report = {
        "holdout_from_wind_records": len(holdout_not_from_wind) == 0,
        "holdout_removed_from_current_train": len(overlap) == 0,
        "fusion_sources_allowed": len(bad_sources) == 0,
        "motion_records_used_as_wind": False,
        "motion_records_diagnostic_only_count": int(len(motion_records)),
        "context_motion_records_diagnostic_only_count": int(len(context_motion_records)),
        "train_holdout_overlap_count": int(len(overlap)),
        "holdout_not_from_wind_count": int(len(holdout_not_from_wind)),
        "bad_fusion_sources": bad_sources,
        "cma_fusion_mode": str(cma_fusion_mode),
        "cma_proxy_npz": str(cma_proxy_npz),
        "cma_used_as_background_not_truth": bool(str(cma_fusion_mode) != "off"),
    }
    report["strict_holdout_no_leakage"] = bool(
        report["holdout_from_wind_records"]
        and report["holdout_removed_from_current_train"]
        and report["fusion_sources_allowed"]
        and not report["motion_records_used_as_wind"]
    )
    if not report["strict_holdout_no_leakage"]:
        raise RuntimeError(f"Stage4 leakage guard failed: {report}")
    return report


def _idx_to_geo_point(shape: tuple[int, int, int], z: int, y: int, x: int) -> dict[str, float]:
    _, h_dim, w_dim = shape
    return {
        "lat": float(LAT_MAX - (float(y) + 0.5) / float(h_dim) * (LAT_MAX - LAT_MIN)),
        "lon": float(LON_MIN + (float(x) + 0.5) / float(w_dim) * (LON_MAX - LON_MIN)),
        "alt_m": float(ALT_MIN + float(z) * DELTA_ALT),
    }


def _nearest_observation_diagnostics(
    z: int,
    y: int,
    x: int,
    observations: list[dict[str, Any]],
    *,
    top_k: int = 3,
) -> dict[str, Any]:
    if not observations:
        return {
            "nearest_train_distance_vox": None,
            "nearest_train_source_role": "",
            "nearest_train_u": None,
            "nearest_train_v": None,
            "nearest_train_base_weight": None,
            "nearest_observations": [],
        }
    scored = []
    for obs in observations:
        dz = float(z - int(obs["z"]))
        dy = float(y - int(obs["y"]))
        dx = float(x - int(obs["x"]))
        dist = math.sqrt(dx * dx + dy * dy + dz * dz)
        scored.append((dist, obs))
    scored.sort(key=lambda item: item[0])
    nearest = scored[0]
    nearest_rows = [
        {
            "distance_vox": float(dist),
            "source_role": str(obs.get("source_role", "")),
            "z": int(obs["z"]),
            "y": int(obs["y"]),
            "x": int(obs["x"]),
            "u": float(obs["u"]),
            "v": float(obs["v"]),
            "base_weight": float(obs["base_weight"]),
            "time_conf": float(obs.get("time_conf", 0.0)),
            "qc_flags": str(obs.get("qc_flags", "ok")),
        }
        for dist, obs in scored[: max(1, int(top_k))]
    ]
    return {
        "nearest_train_distance_vox": float(nearest[0]),
        "nearest_train_source_role": str(nearest[1].get("source_role", "")),
        "nearest_train_u": float(nearest[1]["u"]),
        "nearest_train_v": float(nearest[1]["v"]),
        "nearest_train_base_weight": float(nearest[1]["base_weight"]),
        "nearest_observations": nearest_rows,
    }


def _nearest_role_gap(nearest_rows: list[dict[str, Any]]) -> tuple[float, int, int]:
    current = [row for row in nearest_rows if str(row.get("source_role")) == "current_wind_train"]
    context = [row for row in nearest_rows if str(row.get("source_role")) == "context_wind"]
    if not current or not context:
        return 0.0, len(current), len(context)
    best_gap = 0.0
    for a in current:
        for b in context:
            gap = math.sqrt((_safe_float(a.get("u")) - _safe_float(b.get("u"))) ** 2 + (_safe_float(a.get("v")) - _safe_float(b.get("v"))) ** 2)
            best_gap = max(best_gap, gap)
    return float(best_gap), len(current), len(context)


def _point_role_conflict_context(
    z: int,
    y: int,
    x: int,
    acc: dict[str, np.ndarray] | None,
) -> dict[str, Any]:
    if not acc:
        return {
            "role_overlap_at_point": False,
            "role_conflict_at_point": False,
            "role_conflict_component_gap_at_point_mps": 0.0,
            "role_conflict_threshold_at_point_mps": 0.0,
            "role_conflict_context_factor_at_point": 0.0,
            "role_conflict_current_density_at_point": 0.0,
            "role_conflict_context_time_conf_at_point": 0.0,
            "role_conflict_context_weight_at_point": 0.0,
            "role_conflict_context_removed_weight_at_point": 0.0,
        }
    current_w = np.asarray(acc.get("acc_current_w"), dtype=np.float32)
    context_w = np.asarray(acc.get("acc_context_w"), dtype=np.float32)
    if current_w.ndim != 3 or not (0 <= z < current_w.shape[0] and 0 <= y < current_w.shape[1] and 0 <= x < current_w.shape[2]):
        return {
            "role_overlap_at_point": False,
            "role_conflict_at_point": False,
            "role_conflict_component_gap_at_point_mps": 0.0,
            "role_conflict_threshold_at_point_mps": 0.0,
            "role_conflict_context_factor_at_point": 0.0,
            "role_conflict_current_density_at_point": 0.0,
            "role_conflict_context_time_conf_at_point": 0.0,
            "role_conflict_context_weight_at_point": 0.0,
            "role_conflict_context_removed_weight_at_point": 0.0,
        }
    conflict_mask = np.asarray(acc.get("role_conflict_mask"), dtype=bool)
    component_gap = np.asarray(acc.get("role_conflict_component_gap"), dtype=np.float32)
    threshold_field = np.asarray(acc.get("role_conflict_threshold_field"), dtype=np.float32)
    context_factor_field = np.asarray(acc.get("role_conflict_context_factor_field"), dtype=np.float32)
    current_density_field = np.asarray(acc.get("role_conflict_current_density_field"), dtype=np.float32)
    context_time_mean_field = np.asarray(acc.get("role_conflict_context_time_mean_field"), dtype=np.float32)
    context_removed_w = np.asarray(acc.get("conflict_context_removed_w"), dtype=np.float32)
    return {
        "role_overlap_at_point": bool(current_w[z, y, x] > 0.0 and context_w[z, y, x] > 0.0),
        "role_conflict_at_point": bool(conflict_mask[z, y, x]) if conflict_mask.shape == current_w.shape else False,
        "role_conflict_component_gap_at_point_mps": float(component_gap[z, y, x]) if component_gap.shape == current_w.shape else 0.0,
        "role_conflict_threshold_at_point_mps": float(threshold_field[z, y, x]) if threshold_field.shape == current_w.shape else 0.0,
        "role_conflict_context_factor_at_point": float(context_factor_field[z, y, x]) if context_factor_field.shape == current_w.shape else 0.0,
        "role_conflict_current_density_at_point": float(current_density_field[z, y, x]) if current_density_field.shape == current_w.shape else 0.0,
        "role_conflict_context_time_conf_at_point": float(context_time_mean_field[z, y, x]) if context_time_mean_field.shape == current_w.shape else 0.0,
        "role_conflict_context_weight_at_point": float(context_w[z, y, x]),
        "role_conflict_context_removed_weight_at_point": float(context_removed_w[z, y, x]) if context_removed_w.shape == current_w.shape else 0.0,
    }


def _point_qc_review(
    *,
    vector_error: float,
    gt_speed: float,
    pred_speed: float,
    recon_confidence: float,
    nearest_train_distance_vox: Any,
    nearest_role_gap_mps: float,
    nearest_current_count: int,
    nearest_context_count: int,
    recon_vertical_jump_mps: float,
    vertical_speed_gap_mps: float,
    vertical_neighbor_max_speed_mps: float,
    role_conflict_at_point: bool,
    role_conflict_component_gap_at_point_mps: float,
) -> tuple[bool, str]:
    reasons = []
    if gt_speed >= POINT_EXTREME_WIND_THRESHOLD_MPS:
        reasons.append("extreme_truth_speed_ge_120mps")
    elif gt_speed >= POINT_STRONG_WIND_THRESHOLD_MPS:
        reasons.append("strong_truth_speed_ge_90mps")
    if pred_speed >= POINT_EXTREME_WIND_THRESHOLD_MPS:
        reasons.append("extreme_prediction_speed_ge_120mps")
    if vector_error >= POINT_HIGH_ERROR_THRESHOLD_MPS:
        reasons.append("high_vector_error_ge_30mps")
    if recon_confidence <= EFFECTIVE_CONF_THRESHOLD:
        reasons.append("near_zero_reconstruction_confidence")
    nearest_distance = _safe_float(nearest_train_distance_vox, -1.0)
    if nearest_distance >= POINT_REMOTE_SUPPORT_THRESHOLD_VOX:
        reasons.append("remote_nearest_training_support")
    if nearest_context_count > 0 and nearest_current_count == 0:
        reasons.append("context_only_nearest_support")
    if nearest_context_count > 0 and nearest_role_gap_mps >= POINT_HIGH_ERROR_THRESHOLD_MPS:
        reasons.append("nearest_current_context_role_gap_ge_30mps")
    if role_conflict_at_point:
        reasons.append("role_conflict_triggered_at_holdout_voxel")
    elif nearest_current_count > 0 and nearest_context_count > 0 and role_conflict_component_gap_at_point_mps >= POINT_HIGH_ERROR_THRESHOLD_MPS:
        reasons.append("untriggered_role_gap_at_holdout_voxel_ge_30mps")
    if recon_vertical_jump_mps >= RAPID_VERTICAL_JUMP_DIAGNOSTIC_THRESHOLD_MPS:
        reasons.append("rapid_reconstructed_vertical_jump_ge_25mps")
    if gt_speed >= STRONG_WIND_DIAGNOSTIC_THRESHOLD_MPS and recon_vertical_jump_mps <= VERTICAL_OVERSMOOTH_JUMP_THRESHOLD_MPS:
        reasons.append("strong_wind_vertical_oversmoothing_candidate")
    if gt_speed >= STRONG_WIND_DIAGNOSTIC_THRESHOLD_MPS and vertical_speed_gap_mps >= RAPID_VERTICAL_JUMP_DIAGNOSTIC_THRESHOLD_MPS:
        reasons.append("strong_wind_vertical_context_mismatch_candidate")
    if gt_speed >= STRONG_WIND_DIAGNOSTIC_THRESHOLD_MPS and vertical_neighbor_max_speed_mps < STRONG_WIND_DIAGNOSTIC_THRESHOLD_MPS * 0.70:
        reasons.append("strong_wind_vertically_isolated_candidate")
    return bool(reasons), ";".join(reasons)


def _neighborhood_vector_error_stats(
    *,
    z: int,
    y: int,
    x: int,
    gt_u: float,
    gt_v: float,
    recon_u: np.ndarray,
    recon_v: np.ndarray,
    recon_conf: np.ndarray,
    radius_xy: int = 1,
    radius_z: int = 1,
) -> dict[str, float | int]:
    z0 = max(0, z - int(radius_z))
    z1 = min(recon_u.shape[0], z + int(radius_z) + 1)
    y0 = max(0, y - int(radius_xy))
    y1 = min(recon_u.shape[1], y + int(radius_xy) + 1)
    x0 = max(0, x - int(radius_xy))
    x1 = min(recon_u.shape[2], x + int(radius_xy) + 1)

    sub_u = np.asarray(recon_u[z0:z1, y0:y1, x0:x1], dtype=np.float32)
    sub_v = np.asarray(recon_v[z0:z1, y0:y1, x0:x1], dtype=np.float32)
    sub_conf = np.asarray(recon_conf[z0:z1, y0:y1, x0:x1], dtype=np.float32)
    mask = np.isfinite(sub_u) & np.isfinite(sub_v) & np.isfinite(sub_conf) & (sub_conf > EFFECTIVE_CONF_THRESHOLD)
    if not np.any(mask):
        return {
            "point_neighbor_count": 0,
            "point_neighbor_mean_vector_error": float("nan"),
            "point_neighbor_min_vector_error": float("nan"),
            "point_neighbor_weighted_vector_error": float("nan"),
            "point_neighbor_std_vector_error": float("nan"),
            "representativeness_gap_point_minus_min_mps": float("nan"),
        }

    vec = np.sqrt(((sub_u - np.float32(gt_u)) ** 2 + (sub_v - np.float32(gt_v)) ** 2).astype(np.float32)).astype(np.float32)
    valid_errors = vec[mask].astype(np.float64)
    valid_conf = np.clip(sub_conf[mask].astype(np.float64), 0.0, None)
    if float(np.sum(valid_conf)) <= 0.0:
        valid_conf = np.ones_like(valid_errors, dtype=np.float64)
    center_error = math.sqrt((float(recon_u[z, y, x]) - gt_u) ** 2 + (float(recon_v[z, y, x]) - gt_v) ** 2)
    neighbor_min = float(np.min(valid_errors))
    return {
        "point_neighbor_count": int(valid_errors.size),
        "point_neighbor_mean_vector_error": float(np.mean(valid_errors)),
        "point_neighbor_min_vector_error": neighbor_min,
        "point_neighbor_weighted_vector_error": float(np.sum(valid_errors * valid_conf) / np.sum(valid_conf)),
        "point_neighbor_std_vector_error": float(np.std(valid_errors)),
        "representativeness_gap_point_minus_min_mps": float(center_error - neighbor_min),
    }


def _point_eval_rows(
    holdout: list[dict[str, Any]],
    recon_u: np.ndarray,
    recon_v: np.ndarray,
    recon_conf: np.ndarray,
    observations: list[dict[str, Any]] | None = None,
    acc: dict[str, np.ndarray] | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    shape = tuple(int(v) for v in recon_u.shape)
    observations = observations or []
    vertical_jump = _vertical_jump_field(recon_u, recon_v)
    vertical_neighbor_mean, vertical_neighbor_max = _vertical_neighbor_speed_stats(recon_u, recon_v)
    for row in holdout:
        z = _safe_int(row.get("z"))
        y = _safe_int(row.get("y"))
        x = _safe_int(row.get("x"))
        if not (0 <= z < recon_u.shape[0] and 0 <= y < recon_u.shape[1] and 0 <= x < recon_u.shape[2]):
            continue
        gt_u = _safe_float(row.get("u"))
        gt_v = _safe_float(row.get("v"))
        pred_u = float(recon_u[z, y, x])
        pred_v = float(recon_v[z, y, x])
        u_error = pred_u - gt_u
        v_error = pred_v - gt_v
        vector_error = math.sqrt(u_error * u_error + v_error * v_error)
        geo = _idx_to_geo_point(shape, z, y, x)
        nearest = _nearest_observation_diagnostics(z, y, x, observations)
        nearest_rows = nearest["nearest_observations"]
        nearest_role_gap_mps, nearest_current_count, nearest_context_count = _nearest_role_gap(nearest_rows)
        gt_speed = math.sqrt(gt_u * gt_u + gt_v * gt_v)
        pred_speed = math.sqrt(pred_u * pred_u + pred_v * pred_v)
        recon_vertical_jump = float(vertical_jump[z, y, x])
        vertical_speed_gap = float(abs(pred_speed - vertical_neighbor_mean[z, y, x]))
        vertical_neighbor_max_speed = float(vertical_neighbor_max[z, y, x])
        role_context = _point_role_conflict_context(z, y, x, acc)
        neighborhood_stats = _neighborhood_vector_error_stats(
            z=z,
            y=y,
            x=x,
            gt_u=gt_u,
            gt_v=gt_v,
            recon_u=recon_u,
            recon_v=recon_v,
            recon_conf=recon_conf,
            radius_xy=1,
            radius_z=1,
        )
        qc_review_flag, qc_review_reasons = _point_qc_review(
            vector_error=vector_error,
            gt_speed=gt_speed,
            pred_speed=pred_speed,
            recon_confidence=float(recon_conf[z, y, x]),
            nearest_train_distance_vox=nearest.get("nearest_train_distance_vox"),
            nearest_role_gap_mps=nearest_role_gap_mps,
            nearest_current_count=nearest_current_count,
            nearest_context_count=nearest_context_count,
            recon_vertical_jump_mps=recon_vertical_jump,
            vertical_speed_gap_mps=vertical_speed_gap,
            vertical_neighbor_max_speed_mps=vertical_neighbor_max_speed,
            role_conflict_at_point=bool(role_context["role_conflict_at_point"]),
            role_conflict_component_gap_at_point_mps=float(role_context["role_conflict_component_gap_at_point_mps"]),
        )
        rows.append(
            {
                "z": z,
                "y": y,
                "x": x,
                "lat": geo["lat"],
                "lon": geo["lon"],
                "alt_m": geo["alt_m"],
                "gt_u": gt_u,
                "gt_v": gt_v,
                "gt_speed": gt_speed,
                "pred_u": pred_u,
                "pred_v": pred_v,
                "pred_speed": pred_speed,
                "u_error": u_error,
                "v_error": v_error,
                "abs_u_error": abs(u_error),
                "abs_v_error": abs(v_error),
                "vector_error": vector_error,
                "error_to_truth_speed_ratio": float(vector_error / max(1e-6, gt_speed)),
                "recon_confidence": float(recon_conf[z, y, x]),
                "obs_count": _safe_int(row.get("obs_count"), 0),
                "obs_conf": _safe_float(row.get("obs_conf"), 1.0),
                "nearest_role_gap_mps": nearest_role_gap_mps,
                "nearest_current_count": nearest_current_count,
                "nearest_context_count": nearest_context_count,
                "recon_vertical_jump_mps": recon_vertical_jump,
                "vertical_speed_gap_mps": vertical_speed_gap,
                "vertical_neighbor_max_speed_mps": vertical_neighbor_max_speed,
                **neighborhood_stats,
                **role_context,
                "qc_review_flag": qc_review_flag,
                "qc_review_reasons": qc_review_reasons,
                **{k: v for k, v in nearest.items() if k != "nearest_observations"},
                "nearest_observations_json": json.dumps(nearest_rows, ensure_ascii=False),
            }
        )
    return rows


def _metric_summary(rows: list[dict[str, Any]]) -> dict[str, float]:
    if not rows:
        return {
            "mae_u": 0.0,
            "mae_v": 0.0,
            "mae_vector": 0.0,
            "rmse_vector": 0.0,
            "bias_u": 0.0,
            "bias_v": 0.0,
        }
    abs_u = np.asarray([row["abs_u_error"] for row in rows], dtype=np.float64)
    abs_v = np.asarray([row["abs_v_error"] for row in rows], dtype=np.float64)
    vec = np.asarray([row["vector_error"] for row in rows], dtype=np.float64)
    u_err = np.asarray([row["u_error"] for row in rows], dtype=np.float64)
    v_err = np.asarray([row["v_error"] for row in rows], dtype=np.float64)
    return {
        "mae_u": float(np.mean(abs_u)),
        "mae_v": float(np.mean(abs_v)),
        "mae_vector": float(np.mean(vec)),
        "rmse_vector": float(np.sqrt(np.mean(vec**2))),
        "bias_u": float(np.mean(u_err)),
        "bias_v": float(np.mean(v_err)),
    }


def _write_point_eval_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "z",
        "y",
        "x",
        "lat",
        "lon",
        "alt_m",
        "gt_u",
        "gt_v",
        "gt_speed",
        "pred_u",
        "pred_v",
        "pred_speed",
        "u_error",
        "v_error",
        "abs_u_error",
        "abs_v_error",
        "vector_error",
        "error_to_truth_speed_ratio",
        "recon_confidence",
        "obs_count",
        "obs_conf",
        "nearest_role_gap_mps",
        "nearest_current_count",
        "nearest_context_count",
        "recon_vertical_jump_mps",
        "vertical_speed_gap_mps",
        "vertical_neighbor_max_speed_mps",
        "point_neighbor_count",
        "point_neighbor_mean_vector_error",
        "point_neighbor_min_vector_error",
        "point_neighbor_weighted_vector_error",
        "point_neighbor_std_vector_error",
        "representativeness_gap_point_minus_min_mps",
        "role_overlap_at_point",
        "role_conflict_at_point",
        "role_conflict_component_gap_at_point_mps",
        "role_conflict_threshold_at_point_mps",
        "role_conflict_context_factor_at_point",
        "role_conflict_current_density_at_point",
        "role_conflict_context_time_conf_at_point",
        "role_conflict_context_weight_at_point",
        "role_conflict_context_removed_weight_at_point",
        "qc_review_flag",
        "qc_review_reasons",
        "nearest_train_distance_vox",
        "nearest_train_source_role",
        "nearest_train_u",
        "nearest_train_v",
        "nearest_train_base_weight",
        "nearest_observations_json",
    ]
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def _write_point_eval_text(path: Path, rows: list[dict[str, Any]]) -> None:
    lines = []
    for row in rows:
        lines.append(
            "[Point Eval] hold-out voxel "
            f"(z={row['z']}, y={row['y']}, x={row['x']}): "
            f"gt=[u {row['gt_u']:.3f}, v {row['gt_v']:.3f}] m/s, "
            f"pred=[u {row['pred_u']:.3f}, v {row['pred_v']:.3f}] m/s, "
            f"u_error={row['u_error']:.3f}, v_error={row['v_error']:.3f}, "
            f"vector_error={row['vector_error']:.3f} m/s, conf={row['recon_confidence']:.3f}, "
            f"nearest_train_distance_vox={row.get('nearest_train_distance_vox')}, "
            f"qc_review={row.get('qc_review_flag')} ({row.get('qc_review_reasons', '')})"
        )
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_method_md(
    path: Path,
    *,
    time_str: str,
    stage2_row: dict[str, Any],
    meta: dict[str, Any],
    counts: dict[str, Any],
    metrics: dict[str, float],
    params: dict[str, Any],
    extent_stats: dict[str, Any],
    confidence_diagnostics: dict[str, Any],
    field_diagnostics: dict[str, Any],
    role_conflict_diagnostics: dict[str, Any],
    cma_diagnostics: dict[str, Any],
    display_fill_diagnostics: dict[str, Any],
    leakage_report: dict[str, Any],
    pressure_test_note: str,
) -> None:
    lines = [
        f"# Stage4 Strict Hold-Out Method - {time_str}",
        "",
        "## Role",
        "",
        "Stage4 is the first centralized_v1 wind-field reconstruction stage. It receives all Stage2/Stage3 Ground Center observations, removes selected current wind labels as strict hold-out truth, reconstructs the current 3D wind field, and evaluates only on withheld points.",
        "",
        "## Leakage Guard",
        "",
        "- `wind_records` are current-window true wind label candidates.",
        "- selected hold-out records are removed before fusion.",
        "- only non-holdout current wind and historical `context_wind_records` are used as wind observations.",
        "- `motion_records` and `context_motion_records` are coverage diagnostics here; they are not treated as atmospheric wind truth.",
        "- optional CMA fusion, when enabled, is written as an explicit CMA-background candidate branch and is not the default strict baseline.",
        f"- leakage status: `{leakage_report.get('strict_holdout_no_leakage')}`.",
        "",
        "## Counts",
        "",
        "| item | count |",
        "| --- | ---: |",
    ]
    for key, value in counts.items():
        lines.append(f"| `{key}` | {value} |")
    lines.extend(
        [
            "",
            "## Effective Reconstruction Range",
            "",
            "The effective wind field is defined by `recon_mask_3d > 0`. It is not the full China-domain grid.",
            "",
            "| item | value |",
            "| --- | --- |",
            f"| `grid_total_voxels` | `{extent_stats.get('grid_total_voxels')}` |",
            f"| `effective_reconstructed_voxels` | `{extent_stats.get('effective_reconstructed_voxels')}` |",
            f"| `effective_reconstructed_fraction` | `{float(extent_stats.get('effective_reconstructed_fraction', 0.0)):.6%}` |",
            f"| `support_pre_refine_voxels` | `{extent_stats.get('support_pre_refine_voxels')}` |",
            f"| `low_conf_fill_voxels` | `{extent_stats.get('low_conf_fill_voxels')}` |",
            f"| `bbox_idx_zyx` | `z {extent_stats.get('bbox_z_min')}..{extent_stats.get('bbox_z_max')}, y {extent_stats.get('bbox_y_min')}..{extent_stats.get('bbox_y_max')}, x {extent_stats.get('bbox_x_min')}..{extent_stats.get('bbox_x_max')}` |",
            f"| `bbox_geo` | `lat {float(extent_stats.get('bbox_lat_min', 0.0)):.3f}..{float(extent_stats.get('bbox_lat_max', 0.0)):.3f}, lon {float(extent_stats.get('bbox_lon_min', 0.0)):.3f}..{float(extent_stats.get('bbox_lon_max', 0.0)):.3f}, alt {float(extent_stats.get('bbox_alt_min_m', 0.0)):.0f}..{float(extent_stats.get('bbox_alt_max_m', 0.0)):.0f} m` |",
            f"| `speed_active_mean_mps` | `{float(extent_stats.get('speed_active_mean_mps', 0.0)):.6f}` |",
            f"| `speed_active_max_mps` | `{float(extent_stats.get('speed_active_max_mps', 0.0)):.6f}` |",
            f"| `confidence_active_mean` | `{float(extent_stats.get('confidence_active_mean', 0.0)):.6f}` |",
            f"| `mask_conf_positive_mismatch_voxels` | `{extent_stats.get('mask_conf_positive_mismatch_voxels')}` |",
            "",
            "Interpretation: a block-like footprint is expected from finite-radius Gaussian target-voxel localization plus low-confidence neighbor fill. It is not evidence that the atmosphere physically moves as one block.",
        ]
    )
    lines.extend(
        [
            "",
            "## Parameters",
            "",
            "| parameter | value |",
            "| --- | --- |",
        ]
    )
    for key, value in params.items():
        lines.append(f"| `{key}` | `{value}` |")
    lines.extend(
        [
            "",
            "## Display-Filled Visualization Diagnostics",
            "",
            "Display fill is a product/visualization layer only. It writes `stage4_display_*` fields so low-confidence or no-claim voxels can be colored with weak background context; official `recon_u/v/conf/mask` and strict aircraft holdout RMSE/MAE are unchanged.",
            "",
            "| item | value |",
            "| --- | --- |",
        ]
    )
    display_param_keys = [
        "display_fill_mode",
        "display_fill_source",
        "display_fill_confidence_cap",
        "display_fill_qc_gating",
        "display_fill_is_official_accuracy",
    ]
    for key in display_param_keys:
        lines.append(f"| `{key}` | `{json.dumps(params.get(key), ensure_ascii=False)}` |")
    for key, value in display_fill_diagnostics.items():
        lines.append(f"| `{key}` | `{json.dumps(value, ensure_ascii=False)}` |")
    lines.extend(
        [
            "",
            "## CMA Background Fusion Diagnostics",
            "",
            "These fields are active only for an explicit CMA-fused candidate branch. CMA dense/proxy fields are weak background information, not aircraft hold-out truth.",
            "",
            "| item | value |",
            "| --- | --- |",
        ]
    )
    for key, value in cma_diagnostics.items():
        lines.append(f"| `{key}` | `{json.dumps(value, ensure_ascii=False)}` |")
    lines.extend(
        [
            "",
            "## Confidence Diagnostics",
            "",
            "Default Stage4 keeps these as diagnostics only. They affect weights when `confidence_mode=diagnostic_weighted`; observation-error sigma/weight fields affect weights only when `confidence_mode=obs_error_weighted`. Those sigma values are priors or local consistency/representativeness diagnostics and are never subtracted from Stage4 RMSE/MAE.",
            "",
            "| item | value |",
            "| --- | --- |",
        ]
    )
    for key, value in confidence_diagnostics.items():
        lines.append(f"| `{key}` | `{json.dumps(value, ensure_ascii=False)}` |")
    lines.extend(
        [
            "",
            "## 3D Proxy Diagnostics",
            "",
            "| metric | value |",
            "| --- | ---: |",
        ]
    )
    for key, value in field_diagnostics.items():
        if isinstance(value, (int, float)):
            lines.append(f"| `{key}` | {float(value):.6f} |")
        else:
            lines.append(f"| `{key}` | `{value}` |")
    lines.extend(
        [
            "",
            "## Role Conflict Diagnostics",
            "",
            "These fields are active only when `role_conflict_mode` uses a current-priority conflict rule. Adaptive mode changes the conflict threshold and context-retention factor by altitude, context time confidence, and local support density.",
            "",
            "| metric | value |",
            "| --- | ---: |",
        ]
    )
    for key, value in role_conflict_diagnostics.items():
        if isinstance(value, (int, float)):
            lines.append(f"| `{key}` | {float(value):.6f} |")
        else:
            lines.append(f"| `{key}` | `{value}` |")
    lines.extend(
        [
            "",
            "Adaptive conflict interpretation: `current_priority_adaptive` starts from the CLI base threshold/context factor, then adjusts the actual voxel-wise threshold and context retention by altitude, context time confidence and local current/context support density. These diagnostics report the realized threshold/factor rather than only the CLI seed values.",
            "",
            "Vertical consistency interpretation: rapid vertical jumps, isolated strong layers and strong-wind oversmoothing candidates are review diagnostics. They should guide QC strata and training weights; they do not remove aircraft hold-out labels from strict evaluation.",
        ]
    )
    lines.extend(
        [
            "",
            "## Point Evaluation",
            "",
            "| metric | value |",
            "| --- | ---: |",
        ]
    )
    point_metric_keys = {"mae_u", "mae_v", "mae_vector", "rmse_vector", "bias_u", "bias_v"}
    for key, value in metrics.items():
        if key in point_metric_keys:
            lines.append(f"| `{key}` | {value:.6f} |")
    if pressure_test_note:
        lines.extend(["", "## Frame Note", "", pressure_test_note])
    refine = {k: v for k, v in metrics.items() if k.startswith("pinn_") or k.startswith("diffusion_") or k in {"low_conf_fill_weight", "source_preserve"}}
    if refine:
        lines.extend(["", "## PINN/Diffusion-Style Gap Fill Diagnostics", "", "| metric | value |", "| --- | ---: |"])
        for key, value in refine.items():
            lines.append(f"| `{key}` | {float(value):.6f} |")
    lines.extend(
        [
            "",
            "## Method Basis",
            "",
            "- Time-window context: `time_conf = 0.5 ** (abs(delta_time_minutes) / 180)`. ECMWF ERA5/IFS 4D-Var uses finite assimilation windows, supporting finite current/context windows instead of unlimited history mixing. References: https://confluence.ecmwf.int/display/CKB/ERA5%3A%2Bdata%2Bdocumentation and https://confluence.ecmwf.int/pages/viewpage.action?pageId=315559375",
            "- Aircraft observation separation: `wind_records` are wind labels; `motion_records` are aircraft kinematics. WMO aircraft-based observations report weather variables with position/time, supporting separate wind, trajectory and motion roles. Reference: https://wmo.int/aircraft-based-observations-programme",
            "- Strict hold-out: selected `wind_records` are answer keys and are removed before fusion. Aircraft-surveillance weather reconstruction literature supports aircraft-derived wind as a useful but noisy sparse observation source. References: https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0205029 and https://amt.copernicus.org/articles/9/4141/2016/",
            "- Target-voxel localization: Gaussian uses `exp(-0.5*((dx/sigma_xy)^2+(dy/sigma_xy)^2+(dz/sigma_z)^2))`; Gaspari-Cohn uses compact-support fifth-order localization. DART/Gaspari-Cohn localization motivates applying spatial influence relative to the target state/voxel, not the logical Ground Center. Reference: https://docs.dart.ucar.edu/en/latest/assimilation_code/modules/assimilation/cov_cutoff_mod.html",
            "- Optional diagnostic weighting: density/QC/time-consistency factors are recorded by default and only change active weights when `confidence_mode=diagnostic_weighted`. Aircraft-derived wind systems require QC and error awareness. References: https://amt.copernicus.org/articles/18/3341/2025/ and https://amt.copernicus.org/articles/9/4141/2016/",
            "- Observation-error wording: de Haan / EMADDC sigma values are aircraft wind observation-error priors or QC diagnostics. Local calibration sigma values, including the current `13.64 m/s` figure when present, are local consistency / representativeness sigma estimates. They may weight observations in `confidence_mode=obs_error_weighted`, but they are never deducted from Stage4 strict-holdout RMSE/MAE.",
            "- PINN/diffusion-style gap fill: smoothness, weak divergence and neighbor propagation are proxy diagnostics only, not trained PINN or diffusion models. Local basis: workflow/wiki/wind-field-reconstruction.md and workflow/wiki/beijing-aviation-3d-wind-reconstruction-analysis.md",
            "- `physics_constraint_mode=pydda_3dvar_proxy` adds observation anchoring, masked neighbor smoothness, weak horizontal divergence reduction and speed plausibility clipping. It borrows the 3DVAR idea that observation and physical constraints jointly shape retrieval, but it is still an aircraft-observation proxy rather than PyDDA radar retrieval.",
            "- 3D wind-field constraints: smoothness, mass-continuity/divergence and observation consistency are common in variational wind retrieval. PyDDA/3DVAR and dual-Doppler variational retrieval are reference routes; this Stage4 remains an aircraft-observation proxy, not a Doppler retrieval. References: https://openresearchsoftware.metajnl.com/articles/264 and workflow/wiki/source-dual-doppler-variational-wind-field.md",
            "- Radar layer boundary: single radar PNG mosaics are used as 2D cloud/radar intensity context only. True radar wind retrieval needs Doppler velocity geometry such as PyDDA/3DVAR or dual-Doppler variational methods.",
            "- Gridded organization: WeatherBench2-style gridded datasets support explicit grid-shape and resolution documentation. Reference: https://weatherbench2.readthedocs.io/en/latest/data-guide.html",
            "",
            "## Stage2 Metadata Excerpt",
            "",
            f"- `stage2_role`: `{meta.get('stage2_role')}`",
            f"- `stage2_space_conf_mode`: `{meta.get('stage2_space_conf_mode')}`",
            f"- `reference_center_used_for_weighting`: `{meta.get('reference_center_used_for_weighting')}`",
            f"- `stage2_npz`: `{stage2_row.get('multimodal_vox_path')}`",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def process_frame(
    stage2_row: dict[str, Any],
    stage3_row: dict[str, Any],
    *,
    out_dir: Path,
    holdout_fraction: float,
    holdout_count: int,
    localization_radius_xy: int,
    localization_radius_z: int,
    localization_sigma_xy: float,
    localization_sigma_z: float,
    localization_kernel: str,
    localization_policy: str,
    localization_candidate_grid: str,
    confidence_mode: str,
    qc_calibration: dict[str, Any],
    refine_iters: int,
    pinn_smoothness_weight: float,
    pinn_divergence_weight: float,
    diffusion_weight: float,
    low_conf_fill_weight: float,
    source_preserve: float,
    physics_constraint_mode: str,
    observation_anchor_weight: float,
    speed_limit_mps: float,
    vertical_risk_mode: str,
    vertical_localization_policy: str,
    vertical_gradient_preserve_weight: float,
    vertical_context_mismatch_damping: float,
    current_weight_boost: float,
    context_weight_scale: float,
    context_time_conf_power: float,
    role_conflict_mode: str,
    conflict_speed_threshold_mps: float,
    conflict_context_factor: float,
    cma_fusion_mode: str,
    cma_proxy_dir: Path | None,
    cma_proxy_npz: Path | None,
    cma_background_weight: float,
    cma_background_weight_mode: str,
    cma_confidence_source: str,
    cma_confidence_cap: float,
    cma_time_confidence: float,
    cma_space_confidence: float,
    cma_pseudo_source: str,
    cma_qc_gating: str,
    display_fill_mode: str,
    display_fill_cma_proxy_dir: Path | None,
    display_fill_source: str,
    display_fill_confidence_cap: float,
    display_fill_qc_gating: str,
) -> dict[str, Any]:
    npz_path = Path(stage2_row["multimodal_vox_path"])
    npz = _load_stage2_npz(npz_path)
    shape = tuple(int(v) for v in np.asarray(npz[C2_GRID_SHAPE], dtype=np.int32).tolist())
    time_str = str(stage2_row["time_str"])
    timestamp_utc = str(stage2_row["timestamp_utc"])
    meta = json.loads(str(npz[C2_MULTIMODAL_META_JSON])) if C2_MULTIMODAL_META_JSON in npz else {}

    wind_records = _records(npz.get(C2_WIND_RECORDS))
    context_wind_records = _records(npz.get(C2_CONTEXT_WIND_RECORDS))
    motion_records = _records(npz.get(C2_MOTION_RECORDS))
    context_motion_records = _records(npz.get(C2_CONTEXT_MOTION_RECORDS))
    loc_records = _records(npz.get(C2_LOC_RECORDS))
    cloud_2d = np.asarray(npz[C2_CLOUD_2D], dtype=np.float32)

    train_wind, holdout_wind = _split_holdout(wind_records, holdout_fraction, holdout_count)
    observations, confidence_diagnostics = _build_wind_observations(
        train_wind,
        context_wind_records,
        confidence_mode,
        qc_calibration=qc_calibration,
        current_weight_boost=current_weight_boost,
        context_weight_scale=context_weight_scale,
        context_time_conf_power=context_time_conf_power,
    )
    adaptive_diagnostics: dict[str, Any] = {
        "localization_policy": str(localization_policy),
        "localization_candidate_grid": str(localization_candidate_grid),
        "adaptive_selected_radius_xy": int(localization_radius_xy),
        "adaptive_selected_sigma_xy": float(localization_sigma_xy),
        "adaptive_selected_radius_z": int(localization_radius_z),
        "adaptive_selected_sigma_z": float(localization_sigma_z),
        "adaptive_score": 0.0,
        "adaptive_reasons": "fixed",
        "adaptive_no_holdout_inputs_used": True,
    }
    if str(localization_policy) in {
        "diagnostic_adaptive",
        "diagnostic_adaptive_v3",
        "diagnostic_adaptive_regime_v4",
        "support_role_height_aware",
    }:
        selected_loc, adaptive_diagnostics = _select_adaptive_localization(
            train_current_wind=train_wind,
            context_wind=context_wind_records,
            observations=observations,
            candidate_grid=str(localization_candidate_grid),
            default_radius_xy=int(localization_radius_xy),
            default_sigma_xy=float(localization_sigma_xy),
            default_radius_z=int(localization_radius_z),
            default_sigma_z=float(localization_sigma_z),
            qc_calibration=qc_calibration,
            policy=str(localization_policy),
        )
        localization_radius_xy = int(selected_loc["localization_radius_xy"])
        localization_sigma_xy = float(selected_loc["localization_sigma_xy"])
        localization_radius_z = int(selected_loc["localization_radius_z"])
        localization_sigma_z = float(selected_loc["localization_sigma_z"])
    acc = _accumulate_localized(
        shape,
        observations,
        radius_xy=localization_radius_xy,
        radius_z=localization_radius_z,
        sigma_xy=localization_sigma_xy,
        sigma_z=localization_sigma_z,
        localization_kernel=localization_kernel,
        role_conflict_mode=role_conflict_mode,
        conflict_speed_threshold_mps=conflict_speed_threshold_mps,
        conflict_context_factor=conflict_context_factor,
        vertical_localization_policy=vertical_localization_policy,
        localization_policy=localization_policy,
        localization_context=adaptive_diagnostics,
        qc_calibration=qc_calibration,
    )
    vertical_localization_diagnostics = dict(acc.get("vertical_localization_scalar_diagnostics", {}))
    srha_horizontal_diagnostics = dict(acc.get("srha_horizontal_scalar_diagnostics", {}))
    cma_path = cma_proxy_npz
    if cma_path is None:
        cma_path = _find_cma_proxy_npz(cma_proxy_dir, time_str)
    cma_u, cma_v, cma_conf, cma_fusion_diagnostics = _load_cma_background(
        cma_path,
        shape,
        fusion_mode=cma_fusion_mode,
        confidence_source=cma_confidence_source,
        pseudo_source=cma_pseudo_source,
        qc_gating=cma_qc_gating,
        qc_calibration=qc_calibration,
    )
    if str(cma_fusion_mode) != "off":
        cma_fusion_diagnostics.update(
            _apply_cma_background_to_accumulator(
                acc,
                cma_u=cma_u,
                cma_v=cma_v,
                cma_conf=cma_conf,
                background_weight=float(cma_background_weight),
                background_weight_mode=str(cma_background_weight_mode),
                qc_calibration=qc_calibration,
                time_confidence=float(cma_time_confidence),
                space_confidence=float(cma_space_confidence),
            )
        )
    leakage_report = _leakage_report(
        wind_records=wind_records,
        train_wind=train_wind,
        holdout_wind=holdout_wind,
        observations=observations,
        motion_records=motion_records,
        context_motion_records=context_motion_records,
        cma_fusion_mode=cma_fusion_mode,
        cma_proxy_npz=str(cma_path or ""),
    )
    recon = _make_reconstruction(acc)
    recon = _cap_cma_only_confidence(recon, acc, cma_confidence_cap=float(cma_confidence_cap))
    pre_refine_voxels = int(np.count_nonzero(recon["recon_mask"]))
    recon, refine_metrics = _pinn_diffusion_refine(
        recon,
        iterations=int(refine_iters),
        pinn_smoothness_weight=float(pinn_smoothness_weight),
        pinn_divergence_weight=float(pinn_divergence_weight),
        diffusion_weight=float(diffusion_weight),
        low_conf_fill_weight=float(low_conf_fill_weight),
        source_preserve=float(source_preserve),
        physics_constraint_mode=physics_constraint_mode,
        observation_anchor_weight=observation_anchor_weight,
        speed_limit_mps=speed_limit_mps,
        vertical_risk_mode=vertical_risk_mode,
        vertical_gradient_preserve_weight=vertical_gradient_preserve_weight,
        vertical_context_mismatch_damping=vertical_context_mismatch_damping,
    )
    recon = _finalize_effective_reconstruction(recon)
    point_rows = _point_eval_rows(holdout_wind, recon["recon_u"], recon["recon_v"], recon["recon_conf"], observations, acc)
    display_field, display_fill_diagnostics = _make_display_filled_field(
        recon,
        shape=shape,
        time_str=time_str,
        display_fill_mode=display_fill_mode,
        display_fill_cma_proxy_dir=display_fill_cma_proxy_dir,
        display_fill_source=display_fill_source,
        display_fill_confidence_cap=display_fill_confidence_cap,
        display_fill_qc_gating=display_fill_qc_gating,
        qc_calibration=qc_calibration,
    )
    metrics = _metric_summary(point_rows)
    extent_stats = _reconstruction_extent_stats(recon, pre_refine_voxels)
    field_diagnostics = _field_proxy_diagnostics(recon)
    role_conflict_diagnostics = _role_conflict_diagnostics(acc)
    method_metrics = {**metrics, **refine_metrics}

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"frame_{time_str}_center_strict.npz"
    counts = {
        "wind_records_total": len(wind_records),
        "holdout_wind_records": len(holdout_wind),
        "fusion_current_wind_records": len(train_wind),
        "context_wind_records": len(context_wind_records),
        "fusion_wind_observations_total": len(observations),
        "trajectory_records": len(loc_records),
        "motion_records_diagnostic_only": len(motion_records),
        "context_motion_records_diagnostic_only": len(context_motion_records),
        "localized_pre_refine_voxels": pre_refine_voxels,
        "localized_reconstructed_voxels": int(extent_stats["effective_reconstructed_voxels"]),
        "blindzone_initialized_voxels": int(extent_stats["low_conf_fill_voxels"]),
    }
    params = {
        "holdout_fraction": float(holdout_fraction),
        "holdout_count_arg": int(holdout_count),
        "localization_kernel": str(localization_kernel),
        "localization_radius_xy": int(localization_radius_xy),
        "localization_radius_z": int(localization_radius_z),
        "localization_sigma_xy": float(localization_sigma_xy),
        "localization_sigma_z": float(localization_sigma_z),
        "localization_policy": str(localization_policy),
        "localization_candidate_grid": str(localization_candidate_grid),
        "adaptive_selected_radius_xy": int(adaptive_diagnostics["adaptive_selected_radius_xy"]),
        "adaptive_selected_sigma_xy": float(adaptive_diagnostics["adaptive_selected_sigma_xy"]),
        "adaptive_selected_radius_z": int(adaptive_diagnostics["adaptive_selected_radius_z"]),
        "adaptive_selected_sigma_z": float(adaptive_diagnostics["adaptive_selected_sigma_z"]),
        "adaptive_score": float(adaptive_diagnostics["adaptive_score"]),
        "adaptive_reasons": str(adaptive_diagnostics["adaptive_reasons"]),
        "adaptive_no_holdout_inputs_used": bool(adaptive_diagnostics["adaptive_no_holdout_inputs_used"]),
        "confidence_mode": str(confidence_mode),
        "active_weight": {
            "diagnostic_only": "obs_conf * time_conf * target_voxel_localization",
            "diagnostic_weighted": "obs_conf * time_conf * target_voxel_localization * diagnostic_confidence_factors",
            "obs_error_weighted": "time_conf * aircraft_wind_obs_error_or_representativeness_prior_weight * target_voxel_localization * optional_diagnostic_confidence_factors",
        }.get(str(confidence_mode), str(confidence_mode)),
        "motion_as_wind": False,
        "pinn_diffusion_refine": bool(refine_metrics.get("pinn_diffusion_refine_enabled", 0.0)),
        "pinn_proxy_iterations": int(refine_metrics.get("pinn_proxy_iterations", 0.0)),
        "pinn_smoothness_weight": float(pinn_smoothness_weight),
        "pinn_divergence_weight": float(pinn_divergence_weight),
        "diffusion_weight": float(diffusion_weight),
        "low_conf_fill_weight": float(low_conf_fill_weight),
        "source_preserve": float(source_preserve),
        "physics_constraint_mode": str(physics_constraint_mode),
        "observation_anchor_weight": float(observation_anchor_weight),
        "speed_limit_mps": float(speed_limit_mps),
        "vertical_risk_mode": str(vertical_risk_mode),
        "vertical_localization_policy": str(vertical_localization_policy),
        "vertical_gradient_preserve_weight": float(vertical_gradient_preserve_weight),
        "vertical_context_mismatch_damping": float(vertical_context_mismatch_damping),
        "srha_horizontal_sigma_factor_mean": (
            srha_horizontal_diagnostics.get("srha_horizontal_sigma_factor_stats", {}) or {}
        ).get("mean"),
        "srha_horizontal_sigma_factor_min": (
            srha_horizontal_diagnostics.get("srha_horizontal_sigma_factor_stats", {}) or {}
        ).get("min"),
        "srha_horizontal_sigma_factor_max": (
            srha_horizontal_diagnostics.get("srha_horizontal_sigma_factor_stats", {}) or {}
        ).get("max"),
        "srha_horizontal_reason_counts": str(srha_horizontal_diagnostics.get("srha_horizontal_reason_counts", "")),
        "srha_high_altitude_gate_count": int(srha_horizontal_diagnostics.get("high_altitude_gate_count", 0)),
        "srha_high_speed_gate_count": int(srha_horizontal_diagnostics.get("high_speed_gate_count", 0)),
        "srha_role_gap_gate_count": int(srha_horizontal_diagnostics.get("role_gap_gate_count", 0)),
        "srha_stale_context_gate_count": int(srha_horizontal_diagnostics.get("stale_context_gate_count", 0)),
        "srha_sparse_fresh_widen_gate_count": int(srha_horizontal_diagnostics.get("sparse_fresh_widen_gate_count", 0)),
        "srha_dense_current_gate_count": int(srha_horizontal_diagnostics.get("dense_current_gate_count", 0)),
        "current_weight_boost": float(current_weight_boost),
        "context_weight_scale": float(context_weight_scale),
        "context_time_conf_power": float(context_time_conf_power),
        "role_conflict_mode": str(role_conflict_mode),
        "conflict_speed_threshold_mps": float(conflict_speed_threshold_mps),
        "conflict_context_factor": float(conflict_context_factor),
        "cma_fusion_mode": str(cma_fusion_mode),
        "cma_proxy_npz": str(cma_path or ""),
        "cma_background_weight": float(cma_background_weight),
        "cma_background_weight_mode": str(cma_background_weight_mode),
        "cma_confidence_source": str(cma_confidence_source),
        "cma_confidence_cap": float(cma_confidence_cap),
        "cma_time_confidence": float(cma_time_confidence),
        "cma_space_confidence": float(cma_space_confidence),
        "cma_pseudo_source": str(cma_pseudo_source),
        "cma_qc_gating": str(cma_qc_gating),
        "display_fill_mode": str(display_fill_mode),
        "display_fill_cma_proxy_dir": str(display_fill_cma_proxy_dir or ""),
        "display_fill_source": str(display_fill_source),
        "display_fill_confidence_cap": float(display_fill_confidence_cap),
        "display_fill_qc_gating": str(display_fill_qc_gating),
        "display_fill_is_official_accuracy": False,
        "qc_calibration_path": str(qc_calibration.get("calibration_path", "")),
        "stage3_agent_path": stage3_row.get("agent_path", ""),
    }
    pressure_test_note = ""
    if len(wind_records) <= 1:
        pressure_test_note = "This frame has one or fewer current wind voxels. It is valid as a sparse-label pressure test, but it should not represent average Stage4 performance alone."

    method_json = {
        "stage4_role": "strict_holdout_current_wind_reconstruction",
        "leakage_guard": "selected hold-out wind_records are removed before fusion",
        "leakage_report": leakage_report,
        "counts": counts,
        "metrics": metrics,
        "extent_stats": extent_stats,
        "parameters": params,
        "confidence_diagnostics": confidence_diagnostics,
        "field_diagnostics": field_diagnostics,
        "role_conflict_diagnostics": role_conflict_diagnostics,
        "vertical_localization_diagnostics": vertical_localization_diagnostics,
        "cma_fusion_diagnostics": cma_fusion_diagnostics,
        "display_fill_diagnostics": display_fill_diagnostics,
        "refine_metrics": refine_metrics,
        "pressure_test_note": pressure_test_note,
    }

    np.savez_compressed(
        out_path,
        **{
            C2_TIME_STR: np.array(time_str),
            C2_TIMESTAMP_UTC: np.array(timestamp_utc),
            C4_RECON_U: recon["recon_u"],
            C4_RECON_V: recon["recon_v"],
            C4_RECON_CONF: recon["recon_conf"],
            C4_RECON_MASK: recon["recon_mask"],
            C4_DISPLAY_U: display_field["display_u"],
            C4_DISPLAY_V: display_field["display_v"],
            C4_DISPLAY_CONF: display_field["display_conf"],
            C4_DISPLAY_MASK: display_field["display_mask"],
            C4_DISPLAY_SOURCE: display_field["display_source"],
            C4_C_TIME_3D: recon["c_time"],
            C4_C_SPACE_3D: recon["c_space"],
            C4_C_JOINT_3D: recon["c_joint"],
            C4_BLINDZONE_MASK: recon["blindzone_initialized"],
            C4_CLOUD_2D: cloud_2d,
            C4_POINT_EVAL_JSON: np.array(json.dumps(point_rows, ensure_ascii=False)),
            "stage4_role_conflict_mask_3d": acc["role_conflict_mask"].astype(np.float32),
            "stage4_role_conflict_component_gap_3d": np.asarray(acc["role_conflict_component_gap"], dtype=np.float32),
            "stage4_role_conflict_threshold_3d": np.asarray(acc["role_conflict_threshold_field"], dtype=np.float32),
            "stage4_role_conflict_context_factor_3d": np.asarray(acc["role_conflict_context_factor_field"], dtype=np.float32),
            "stage4_method_json": np.array(json.dumps(method_json, ensure_ascii=False)),
            "stage4_refine_metrics_json": np.array(json.dumps(refine_metrics, ensure_ascii=False)),
            "stage4_confidence_diagnostics_json": np.array(json.dumps(confidence_diagnostics, ensure_ascii=False)),
            "stage4_field_diagnostics_json": np.array(json.dumps(field_diagnostics, ensure_ascii=False)),
            "stage4_role_conflict_diagnostics_json": np.array(json.dumps(role_conflict_diagnostics, ensure_ascii=False)),
            "stage4_vertical_localization_diagnostics_json": np.array(json.dumps(vertical_localization_diagnostics, ensure_ascii=False)),
            "stage4_cma_fusion_diagnostics_json": np.array(json.dumps(cma_fusion_diagnostics, ensure_ascii=False)),
            C4_DISPLAY_FILL_DIAGNOSTICS_JSON: np.array(json.dumps(display_fill_diagnostics, ensure_ascii=False)),
            "stage4_leakage_report_json": np.array(json.dumps(leakage_report, ensure_ascii=False)),
            "holdout_records_json": np.array(json.dumps(holdout_wind, ensure_ascii=False)),
        },
    )

    point_json_path = out_dir / f"point_eval_{time_str}.json"
    point_csv_path = out_dir / f"point_eval_{time_str}.csv"
    point_txt_path = out_dir / f"point_eval_{time_str}.txt"
    method_md_path = out_dir / f"stage4_method_{time_str}.md"
    point_json_path.write_text(json.dumps(point_rows, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_point_eval_csv(point_csv_path, point_rows)
    _write_point_eval_text(point_txt_path, point_rows)
    _write_method_md(
        method_md_path,
        time_str=time_str,
        stage2_row=stage2_row,
        meta=meta,
        counts=counts,
        metrics=method_metrics,
        params=params,
        extent_stats=extent_stats,
        confidence_diagnostics=confidence_diagnostics,
        field_diagnostics=field_diagnostics,
        role_conflict_diagnostics=role_conflict_diagnostics,
        cma_diagnostics=cma_fusion_diagnostics,
        display_fill_diagnostics=display_fill_diagnostics,
        leakage_report=leakage_report,
        pressure_test_note=pressure_test_note,
    )

    return {
        "time_str": time_str,
        "timestamp_utc": timestamp_utc,
        "output_npz": str(out_path),
        "point_eval_json": str(point_json_path),
        "point_eval_csv": str(point_csv_path),
        "point_eval_text_log": str(point_txt_path),
        "method_md": str(method_md_path),
        **counts,
        **extent_stats,
        **metrics,
        **refine_metrics,
        **field_diagnostics,
        **role_conflict_diagnostics,
        **vertical_localization_diagnostics,
        **srha_horizontal_diagnostics,
        **cma_fusion_diagnostics,
        "display_fill_mode": str(display_fill_mode),
        "display_fill_source": str(display_fill_source),
        "display_fill_confidence_cap": float(display_fill_confidence_cap),
        "display_fill_qc_gating": str(display_fill_qc_gating),
        "display_fill_is_official_accuracy": False,
        "display_fill_active_voxels": int(display_fill_diagnostics.get("display_active_voxels", 0)),
        "display_fill_background_voxels": int(display_fill_diagnostics.get("display_background_voxels", 0)),
        "display_fill_diagnostics": display_fill_diagnostics,
        "confidence_mode": str(confidence_mode),
        "localization_kernel": str(localization_kernel),
        "localization_policy": str(localization_policy),
        "localization_candidate_grid": str(localization_candidate_grid),
        "adaptive_selected_radius_xy": int(adaptive_diagnostics["adaptive_selected_radius_xy"]),
        "adaptive_selected_sigma_xy": float(adaptive_diagnostics["adaptive_selected_sigma_xy"]),
        "adaptive_selected_radius_z": int(adaptive_diagnostics["adaptive_selected_radius_z"]),
        "adaptive_selected_sigma_z": float(adaptive_diagnostics["adaptive_selected_sigma_z"]),
        "adaptive_score": float(adaptive_diagnostics["adaptive_score"]),
        "adaptive_reasons": str(adaptive_diagnostics["adaptive_reasons"]),
        "adaptive_no_holdout_inputs_used": bool(adaptive_diagnostics["adaptive_no_holdout_inputs_used"]),
        "physics_constraint_mode": str(physics_constraint_mode),
        "vertical_risk_mode": str(vertical_risk_mode),
        "vertical_localization_policy": str(vertical_localization_policy),
        "vertical_gradient_preserve_weight": float(vertical_gradient_preserve_weight),
        "vertical_context_mismatch_damping": float(vertical_context_mismatch_damping),
        "current_weight_boost": float(current_weight_boost),
        "context_weight_scale": float(context_weight_scale),
        "context_time_conf_power": float(context_time_conf_power),
        "role_conflict_mode": str(role_conflict_mode),
        "conflict_speed_threshold_mps": float(conflict_speed_threshold_mps),
        "conflict_context_factor": float(conflict_context_factor),
        "cma_fusion_mode": str(cma_fusion_mode),
        "cma_background_weight": float(cma_background_weight),
        "cma_background_weight_mode": str(cma_background_weight_mode),
        "cma_confidence_source": str(cma_confidence_source),
        "cma_confidence_cap": float(cma_confidence_cap),
        "cma_pseudo_source": str(cma_pseudo_source),
        "cma_qc_gating": str(cma_qc_gating),
        "confidence_diagnostics": confidence_diagnostics,
        "cma_fusion_diagnostics": cma_fusion_diagnostics,
        "leakage_report": leakage_report,
        "strict_holdout_no_leakage": True,
        "motion_used_as_wind": False,
        "blindzone_background_source": f"{localization_kernel}_target_voxel_localization",
        "stage3_agent_path": stage3_row.get("agent_path", ""),
    }


def _parse_frame_times(frame_times: str) -> set[str]:
    return {token.strip() for token in str(frame_times).split(",") if token.strip()}


def _write_shard_frame_times(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text(json.dumps([str(row["time_str"]) for row in rows], ensure_ascii=False, indent=2), encoding="utf-8")


def _read_frame_times_file(path: Path) -> str:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"Stage4 frame-times-file must contain a JSON list: {path}")
    return ",".join(str(item) for item in payload)


def _run_parent_shards(args: argparse.Namespace, selected: list[dict[str, Any]]) -> list[dict[str, Any]]:
    workers = max(1, int(args.num_workers))
    shard_dir = args.out_dir / "shards"
    shard_dir.mkdir(parents=True, exist_ok=True)
    shards = [[] for _ in range(workers)]
    for idx, row in enumerate(selected):
        shards[idx % workers].append(row)

    procs: list[tuple[subprocess.Popen[str], Path, Path]] = []
    env_base = os.environ.copy()
    env_base.setdefault("POLARS_MAX_THREADS", "1")
    env_base.setdefault("OMP_NUM_THREADS", "1")
    env_base.setdefault("OPENBLAS_NUM_THREADS", "1")
    for shard_idx, rows in enumerate(shards):
        if not rows:
            continue
        frame_file = shard_dir / f"stage4_shard_{shard_idx:02d}_frames.json"
        summary_file = shard_dir / f"stage4_shard_{shard_idx:02d}_summary.json"
        log_file = shard_dir / f"stage4_shard_{shard_idx:02d}.log"
        _write_shard_frame_times(frame_file, rows)
        cmd = [
            sys.executable,
            str(Path(__file__).resolve()),
            "--stage2-summary",
            str(args.stage2_summary),
            "--stage3-summary",
            str(args.stage3_summary),
            "--out-dir",
            str(args.out_dir),
            "--frame-times-file",
            str(frame_file),
            "--holdout-fraction",
            str(args.holdout_fraction),
            "--holdout-count",
            str(args.holdout_count),
            "--localization-radius-xy",
            str(args.localization_radius_xy),
            "--localization-radius-z",
            str(args.localization_radius_z),
            "--localization-sigma-xy",
            str(args.localization_sigma_xy),
            "--localization-sigma-z",
            str(args.localization_sigma_z),
            "--localization-kernel",
            str(args.localization_kernel),
            "--localization-policy",
            str(args.localization_policy),
            "--localization-candidate-grid",
            str(args.localization_candidate_grid),
            "--confidence-mode",
            str(args.confidence_mode),
            "--refine-iters",
            str(args.refine_iters),
            "--pinn-smoothness-weight",
            str(args.pinn_smoothness_weight),
            "--pinn-divergence-weight",
            str(args.pinn_divergence_weight),
            "--diffusion-weight",
            str(args.diffusion_weight),
            "--low-conf-fill-weight",
            str(args.low_conf_fill_weight),
            "--source-preserve",
            str(args.source_preserve),
            "--physics-constraint-mode",
            str(args.physics_constraint_mode),
            "--observation-anchor-weight",
            str(args.observation_anchor_weight),
            "--speed-limit-mps",
            str(args.speed_limit_mps),
            "--vertical-risk-mode",
            str(args.vertical_risk_mode),
            "--vertical-localization-policy",
            str(args.vertical_localization_policy),
            "--vertical-gradient-preserve-weight",
            str(args.vertical_gradient_preserve_weight),
            "--vertical-context-mismatch-damping",
            str(args.vertical_context_mismatch_damping),
            "--current-weight-boost",
            str(args.current_weight_boost),
            "--context-weight-scale",
            str(args.context_weight_scale),
            "--context-time-conf-power",
            str(args.context_time_conf_power),
            "--role-conflict-mode",
            str(args.role_conflict_mode),
            "--conflict-speed-threshold-mps",
            str(args.conflict_speed_threshold_mps),
            "--conflict-context-factor",
            str(args.conflict_context_factor),
            "--cma-fusion-mode",
            str(args.cma_fusion_mode),
            "--cma-proxy-dir",
            str(args.cma_proxy_dir),
            "--cma-background-weight",
            str(args.cma_background_weight),
            "--cma-background-weight-mode",
            str(args.cma_background_weight_mode),
            "--cma-confidence-source",
            str(args.cma_confidence_source),
            "--cma-confidence-cap",
            str(args.cma_confidence_cap),
            "--cma-time-confidence",
            str(args.cma_time_confidence),
            "--cma-space-confidence",
            str(args.cma_space_confidence),
            "--cma-pseudo-source",
            str(args.cma_pseudo_source),
            "--cma-qc-gating",
            str(args.cma_qc_gating),
            "--display-fill-mode",
            str(args.display_fill_mode),
            "--display-fill-cma-proxy-dir",
            str(args.display_fill_cma_proxy_dir),
            "--display-fill-source",
            str(args.display_fill_source),
            "--display-fill-confidence-cap",
            str(args.display_fill_confidence_cap),
            "--display-fill-qc-gating",
            str(args.display_fill_qc_gating),
            "--num-workers",
            str(workers),
            "--shard-id",
            str(shard_idx),
            "--shard-summary",
            str(summary_file),
        ]
        if args.qc_calibration:
            cmd.extend(["--qc-calibration", str(args.qc_calibration)])
        if args.cma_proxy_npz:
            cmd.extend(["--cma-proxy-npz", str(args.cma_proxy_npz)])
        with log_file.open("w", encoding="utf-8") as log:
            proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, text=True, env=env_base)
        procs.append((proc, summary_file, log_file))

    summaries: list[dict[str, Any]] = []
    for proc, summary_file, log_file in procs:
        rc = proc.wait()
        if rc != 0:
            raise RuntimeError(f"Stage4 shard failed rc={rc}; see {log_file}")
        summaries.extend(json.loads(summary_file.read_text(encoding="utf-8")))
    return sorted(summaries, key=lambda row: str(row["time_str"]))


def main() -> None:
    parser = argparse.ArgumentParser(description="Centralized v1 Stage4 strict hold-out ground reconstruction.")
    parser.add_argument(
        "--stage2-summary",
        type=Path,
        default=REGENERATED_STAGE2_OUTPUT_DIR / "stage2_multimodal_summary.json",
    )
    parser.add_argument(
        "--stage3-summary",
        type=Path,
        default=STAGE3_OUTPUT_DIR / "stage3_center_summary.json",
    )
    parser.add_argument("--frame-times", default="")
    parser.add_argument("--frame-times-file", type=Path)
    parser.add_argument("--out-dir", type=Path, default=STRICT_STAGE4_OUTPUT_DIR)
    parser.add_argument("--holdout-fraction", type=float, default=0.125)
    parser.add_argument("--holdout-count", type=int, default=0)
    parser.add_argument("--localization-radius-xy", type=int, default=BLINDZONE_IDW_RADIUS_XY)
    parser.add_argument("--localization-radius-z", type=int, default=BLINDZONE_IDW_RADIUS_Z)
    parser.add_argument("--localization-sigma-xy", type=float, default=max(1.0, BLINDZONE_IDW_RADIUS_XY / 2.0))
    parser.add_argument("--localization-sigma-z", type=float, default=max(0.5, BLINDZONE_IDW_RADIUS_Z / 2.0))
    parser.add_argument("--localization-kernel", choices=sorted(LOCALIZATION_KERNELS), default="gaussian")
    parser.add_argument("--localization-policy", choices=sorted(LOCALIZATION_POLICIES), default="fixed")
    parser.add_argument("--localization-candidate-grid", default="6:3,8:4,10:5,12:6")
    parser.add_argument("--confidence-mode", choices=sorted(CONFIDENCE_MODES), default="diagnostic_only")
    parser.add_argument("--qc-calibration", type=Path)
    parser.add_argument("--refine-iters", type=int, default=4)
    parser.add_argument("--pinn-smoothness-weight", type=float, default=0.018)
    parser.add_argument("--pinn-divergence-weight", type=float, default=0.010)
    parser.add_argument("--diffusion-weight", type=float, default=0.22)
    parser.add_argument("--low-conf-fill-weight", type=float, default=0.72)
    parser.add_argument("--source-preserve", type=float, default=0.95)
    parser.add_argument("--physics-constraint-mode", choices=sorted(PHYSICS_CONSTRAINT_MODES), default="proxy")
    parser.add_argument("--observation-anchor-weight", type=float, default=0.10)
    parser.add_argument("--speed-limit-mps", type=float, default=120.0)
    parser.add_argument("--vertical-risk-mode", choices=sorted(VERTICAL_RISK_MODES), default="off")
    parser.add_argument("--vertical-localization-policy", choices=sorted(VERTICAL_LOCALIZATION_POLICIES), default="fixed")
    parser.add_argument("--vertical-gradient-preserve-weight", type=float, default=float(DEFAULT_QC_CALIBRATION["vertical_risk_gradient_preserve_weight"]))
    parser.add_argument("--vertical-context-mismatch-damping", type=float, default=float(DEFAULT_QC_CALIBRATION["vertical_risk_context_mismatch_damping"]))
    parser.add_argument("--current-weight-boost", type=float, default=1.0)
    parser.add_argument("--context-weight-scale", type=float, default=1.0)
    parser.add_argument("--context-time-conf-power", type=float, default=1.0)
    parser.add_argument("--role-conflict-mode", choices=sorted(ROLE_CONFLICT_MODES), default="off")
    parser.add_argument("--conflict-speed-threshold-mps", type=float, default=12.0)
    parser.add_argument("--conflict-context-factor", type=float, default=0.25)
    parser.add_argument("--cma-fusion-mode", choices=sorted(CMA_FUSION_MODES), default="off")
    parser.add_argument("--cma-proxy-dir", type=Path, default=Path("/data/LFT-W02_data/pengxu/centralized_v1_output/cma_ra_virtual_radial_3dvar"))
    parser.add_argument("--cma-proxy-npz", type=Path)
    parser.add_argument("--cma-background-weight", type=float, default=0.10)
    parser.add_argument("--cma-background-weight-mode", choices=sorted(CMA_BACKGROUND_WEIGHT_MODES), default="fixed")
    parser.add_argument("--cma-confidence-source", choices=sorted(CMA_CONFIDENCE_SOURCES), default="dense")
    parser.add_argument("--cma-confidence-cap", type=float, default=0.35)
    parser.add_argument("--cma-time-confidence", type=float, default=0.70)
    parser.add_argument("--cma-space-confidence", type=float, default=0.70)
    parser.add_argument("--cma-pseudo-source", choices=sorted(CMA_PSEUDO_SOURCES), default="reanalysis")
    parser.add_argument("--cma-qc-gating", choices=sorted(CMA_QC_GATING_MODES), default="off")
    parser.add_argument("--display-fill-mode", choices=sorted(DISPLAY_FILL_MODES), default="off")
    parser.add_argument(
        "--display-fill-cma-proxy-dir",
        type=Path,
        default=Path("/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_three_method_compare_20260531/cma_proxy"),
    )
    parser.add_argument("--display-fill-source", choices=sorted(DISPLAY_FILL_SOURCES), default="cma_reanalysis")
    parser.add_argument("--display-fill-confidence-cap", type=float, default=0.20)
    parser.add_argument("--display-fill-qc-gating", choices=sorted(CMA_QC_GATING_MODES), default="strict_temporal")
    parser.add_argument("--num-workers", type=int, default=1)
    parser.add_argument("--shard-id", type=int, default=-1)
    parser.add_argument("--shard-summary", type=Path)
    args = parser.parse_args()

    stage2_rows_all = _load_json(args.stage2_summary)
    stage3_rows_all = _load_json(args.stage3_summary)
    frame_times = _read_frame_times_file(args.frame_times_file) if args.frame_times_file else str(args.frame_times)
    wanted = _parse_frame_times(frame_times)
    if wanted:
        stage2_rows_all = [row for row in stage2_rows_all if str(row.get("time_str")) in wanted]
        found = {str(row.get("time_str")) for row in stage2_rows_all}
        missing = sorted(wanted - found)
        if missing:
            raise ValueError(f"Requested frame-times not found in Stage2 summary: {missing}")

    args.out_dir.mkdir(parents=True, exist_ok=True)
    if args.shard_id < 0 and int(args.num_workers) > 1 and len(stage2_rows_all) > 1:
        summaries = _run_parent_shards(args, sorted(stage2_rows_all, key=lambda row: str(row["time_str"])))
        summary_path = args.out_dir / "stage4_center_summary.json"
        summary_path.write_text(json.dumps(summaries, ensure_ascii=False, indent=2), encoding="utf-8")
        print(summary_path)
        return

    stage3_rows = {str(row["time_str"]): row for row in stage3_rows_all}
    qc_calibration = _load_qc_calibration(args.qc_calibration)
    summaries = []
    for stage2_row in sorted(stage2_rows_all, key=lambda row: str(row["time_str"])):
        time_str = str(stage2_row["time_str"])
        if time_str not in stage3_rows:
            raise ValueError(f"Stage3 summary is missing frame {time_str}")
        summaries.append(
            process_frame(
                stage2_row,
                stage3_rows[time_str],
                out_dir=args.out_dir,
                holdout_fraction=float(args.holdout_fraction),
                holdout_count=int(args.holdout_count),
                localization_radius_xy=int(args.localization_radius_xy),
                localization_radius_z=int(args.localization_radius_z),
                localization_sigma_xy=float(args.localization_sigma_xy),
                localization_sigma_z=float(args.localization_sigma_z),
                localization_kernel=str(args.localization_kernel),
                localization_policy=str(args.localization_policy),
                localization_candidate_grid=str(args.localization_candidate_grid),
                confidence_mode=str(args.confidence_mode),
                qc_calibration=qc_calibration,
                refine_iters=int(args.refine_iters),
                pinn_smoothness_weight=float(args.pinn_smoothness_weight),
                pinn_divergence_weight=float(args.pinn_divergence_weight),
                diffusion_weight=float(args.diffusion_weight),
                low_conf_fill_weight=float(args.low_conf_fill_weight),
                source_preserve=float(args.source_preserve),
                physics_constraint_mode=str(args.physics_constraint_mode),
                observation_anchor_weight=float(args.observation_anchor_weight),
                speed_limit_mps=float(args.speed_limit_mps),
                vertical_risk_mode=str(args.vertical_risk_mode),
                vertical_localization_policy=str(args.vertical_localization_policy),
                vertical_gradient_preserve_weight=float(args.vertical_gradient_preserve_weight),
                vertical_context_mismatch_damping=float(args.vertical_context_mismatch_damping),
                current_weight_boost=float(args.current_weight_boost),
                context_weight_scale=float(args.context_weight_scale),
                context_time_conf_power=float(args.context_time_conf_power),
                role_conflict_mode=str(args.role_conflict_mode),
                conflict_speed_threshold_mps=float(args.conflict_speed_threshold_mps),
                conflict_context_factor=float(args.conflict_context_factor),
                cma_fusion_mode=str(args.cma_fusion_mode),
                cma_proxy_dir=args.cma_proxy_dir,
                cma_proxy_npz=args.cma_proxy_npz,
                cma_background_weight=float(args.cma_background_weight),
                cma_background_weight_mode=str(args.cma_background_weight_mode),
                cma_confidence_source=str(args.cma_confidence_source),
                cma_confidence_cap=float(args.cma_confidence_cap),
                cma_time_confidence=float(args.cma_time_confidence),
                cma_space_confidence=float(args.cma_space_confidence),
                cma_pseudo_source=str(args.cma_pseudo_source),
                cma_qc_gating=str(args.cma_qc_gating),
                display_fill_mode=str(args.display_fill_mode),
                display_fill_cma_proxy_dir=args.display_fill_cma_proxy_dir,
                display_fill_source=str(args.display_fill_source),
                display_fill_confidence_cap=float(args.display_fill_confidence_cap),
                display_fill_qc_gating=str(args.display_fill_qc_gating),
            )
        )
        summaries[-1]["num_workers"] = int(args.num_workers)
        summaries[-1]["parallel_mode"] = "shard_subprocess" if int(args.num_workers) > 1 else "single_process"
        summaries[-1]["shard_id"] = int(args.shard_id)

    summary_path = args.shard_summary if args.shard_summary else args.out_dir / "stage4_center_summary.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summaries, ensure_ascii=False, indent=2), encoding="utf-8")
    print(summary_path)


if __name__ == "__main__":
    main()
