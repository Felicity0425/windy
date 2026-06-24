"""Apply the locked Stage5 residual PINN candidate to Stage4 full fields.

This script is a candidate-only Stage5 field smoke / pairwise tool. It rebuilds
the Stage4 tp26 baseline from Stage2 records, constructs truth-free field
features, applies the locked narrow residual gate, and writes Stage4-compatible
metrics tables for strict pairwise comparison.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import torch

ROOT_DIR = Path(__file__).resolve().parents[3]
STAGE_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
if str(STAGE_DIR) not in sys.path:
    sys.path.insert(0, str(STAGE_DIR))

from stage.centralized_v1.configs.centralized_v1_config import (  # noqa: E402
    ALT_MIN,
    DELTA_ALT,
    LAT_MAX,
    LAT_MIN,
    LON_MAX,
    LON_MIN,
    REGENERATED_STAGE2_OUTPUT_DIR,
)
from stage.centralized_v1.configs.centralized_v1_contract import (  # noqa: E402
    C2_CLOUD_2D,
    C2_CONTEXT_MOTION_RECORDS,
    C2_CONTEXT_WIND_RECORDS,
    C2_GRID_SHAPE,
    C2_LOC_RECORDS,
    C2_MOTION_RECORDS,
    C2_TIME_STR,
    C2_TIMESTAMP_UTC,
    C2_WIND_RECORDS,
    C4_CLOUD_2D,
    C4_RECON_CONF,
    C4_RECON_MASK,
    C4_RECON_U,
    C4_RECON_V,
)
from stage.centralized_v1.core.centralized_stage4_ground_recon import (  # noqa: E402
    CMA_BACKGROUND_WEIGHT_MODES,
    CMA_CONFIDENCE_SOURCES,
    CMA_FUSION_MODES,
    CMA_PSEUDO_SOURCES,
    CMA_QC_GATING_MODES,
    CONFIDENCE_MODES,
    DEFAULT_QC_CALIBRATION,
    LOCALIZATION_KERNELS,
    LOCALIZATION_POLICIES,
    PHYSICS_CONSTRAINT_MODES,
    ROLE_CONFLICT_MODES,
    VERTICAL_LOCALIZATION_POLICIES,
    VERTICAL_RISK_MODES,
    _accumulate_localized,
    _apply_cma_background_to_accumulator,
    _build_wind_observations,
    _cap_cma_only_confidence,
    _field_proxy_diagnostics,
    _finalize_effective_reconstruction,
    _find_cma_proxy_npz,
    _is_guarded_vertical_policy,
    _leakage_report,
    _load_cma_background,
    _load_json,
    _load_qc_calibration,
    _load_stage2_npz,
    _make_guarded_vertical_localization_context,
    _make_reconstruction,
    _metric_summary,
    _pinn_diffusion_refine,
    _point_eval_rows,
    _records,
    _reconstruction_extent_stats,
    _role_conflict_diagnostics,
    _select_adaptive_localization,
    _split_holdout,
    _vertical_jump_field,
    _vertical_neighbor_speed_stats,
)
from stage.centralized_v1.core.centralized_stage5_residual_pinn_dataset import _build_features  # noqa: E402
from stage.centralized_v1.core.centralized_stage5_residual_pinn_train import ResidualMLP  # noqa: E402


DEFAULT_CHECKPOINT = Path(
    "/data/LFT-W02_data/pengxu/centralized_v1_output/"
    "stage5_residual_pinn_full_tp26_gpu_sweep_narrow_train_20260609/"
    "train_cap1p0_seed20260609_w512_l6/checkpoint.pt"
)
DEFAULT_OUT_ROOT = Path(
    "/data/LFT-W02_data/pengxu/centralized_v1_output/"
    "stage5_residual_pinn_field_v1_smoke_20260610"
)
SMOKE_FRAMES = (
    "20260215010000,"
    "20260216081800,"
    "20260215151200,"
    "20260216163000,"
    "20260217000000"
)


def _read_frame_times(text: str, path: Path | None) -> list[str]:
    if path is not None:
        return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [token.strip() for token in str(text).split(",") if token.strip()]


def _select_stage2_rows(summary_path: Path, frame_times: list[str]) -> list[dict[str, Any]]:
    rows = _load_json(summary_path)
    wanted = set(frame_times)
    if not wanted:
        return sorted(rows, key=lambda row: str(row["time_str"]))
    selected = [row for row in rows if str(row.get("time_str")) in wanted]
    found = {str(row.get("time_str")) for row in selected}
    missing = sorted(wanted - found)
    if missing:
        raise ValueError(f"Requested frame-times not found in Stage2 summary: {missing}")
    return sorted(selected, key=lambda row: frame_times.index(str(row["time_str"])))


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


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _frame_row(
    *,
    stage2_row: dict[str, Any],
    label: str,
    point_rows: list[dict[str, Any]],
    recon: dict[str, np.ndarray],
    pre_refine_voxels: int,
    leakage: dict[str, Any],
    params: dict[str, Any],
    counts: dict[str, Any],
    adaptive: dict[str, Any],
    confidence_diagnostics: dict[str, Any],
    refine_metrics: dict[str, Any],
    role_conflict_diagnostics: dict[str, Any],
    field_stats: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metrics = _metric_summary(point_rows)
    extent = _reconstruction_extent_stats(recon, pre_refine_voxels)
    field_diag = field_stats or _field_proxy_diagnostics(recon)
    row: dict[str, Any] = {
        "time_str": str(stage2_row["time_str"]),
        "stage5_field_label": label,
        "kernel": params["localization_kernel"],
        "confidence_mode": params["confidence_mode"],
        "physics_constraint_mode": params["physics_constraint_mode"],
        "localization_policy": params["localization_policy"],
        "localization_candidate_grid": params["localization_candidate_grid"],
        "adaptive_selected_radius_xy": int(params["localization_radius_xy"]),
        "adaptive_selected_sigma_xy": float(params["localization_sigma_xy"]),
        "adaptive_selected_radius_z": int(params["localization_radius_z"]),
        "adaptive_selected_sigma_z": float(params["localization_sigma_z"]),
        "adaptive_score": float(adaptive.get("adaptive_score", 0.0)),
        "adaptive_reasons": str(adaptive.get("adaptive_reasons", "")),
        "adaptive_current_support": int(adaptive.get("adaptive_current_support", counts["fusion_current_wind_records"])),
        "adaptive_context_support": int(adaptive.get("adaptive_context_support", counts["context_wind_records"])),
        "adaptive_context_time_conf_mean": float(adaptive.get("adaptive_context_time_conf_mean", 0.0)),
        "adaptive_obs_error_weight_mean": float(adaptive.get("adaptive_obs_error_weight_mean", 0.0)),
        "adaptive_role_gap_mps": float(adaptive.get("adaptive_role_gap_mps", 0.0)),
        "adaptive_no_holdout_inputs_used": bool(adaptive.get("adaptive_no_holdout_inputs_used", True)),
        "localization_radius_xy": int(params["localization_radius_xy"]),
        "localization_sigma_xy": float(params["localization_sigma_xy"]),
        "localization_radius_z": int(params["localization_radius_z"]),
        "localization_sigma_z": float(params["localization_sigma_z"]),
        **counts,
        "rmse_vector": float(metrics["rmse_vector"]),
        "mae_vector": float(metrics["mae_vector"]),
        "bias_u": float(metrics["bias_u"]),
        "bias_v": float(metrics["bias_v"]),
        "effective_reconstructed_voxels": int(extent["effective_reconstructed_voxels"]),
        "effective_reconstructed_fraction": float(extent["effective_reconstructed_fraction"]),
        "support_pre_refine_voxels": int(extent["support_pre_refine_voxels"]),
        "low_conf_fill_voxels": int(extent["low_conf_fill_voxels"]),
        "low_conf_fill_fraction": float(extent["low_conf_fill_fraction"]),
        "mask_conf_positive_mismatch_voxels": int(extent["mask_conf_positive_mismatch_voxels"]),
        "speed_active_mean_mps": float(extent["speed_active_mean_mps"]),
        "speed_active_max_mps": float(extent["speed_active_max_mps"]),
        "confidence_active_mean": float(extent["confidence_active_mean"]),
        "density_conf_factor_mean": (confidence_diagnostics.get("density_conf_factor_stats", {}) or {}).get("mean"),
        "speed_qc_conf_mean": (confidence_diagnostics.get("speed_qc_conf_stats", {}) or {}).get("mean"),
        "local_consistency_conf_mean": (confidence_diagnostics.get("local_consistency_conf_stats", {}) or {}).get("mean"),
        "obs_error_sigma_vector_mps_mean": (confidence_diagnostics.get("obs_error_sigma_vector_mps_stats", {}) or {}).get("mean"),
        "obs_error_weight_factor_mean": (confidence_diagnostics.get("obs_error_weight_factor_stats", {}) or {}).get("mean"),
        "diffusion_fill_new_voxels": int(refine_metrics.get("diffusion_fill_new_voxels", 0)),
        "observation_anchor_weight": float(params["observation_anchor_weight"]),
        "speed_limit_mps": float(params["speed_limit_mps"]),
        "vertical_risk_mode": str(params["vertical_risk_mode"]),
        "vertical_localization_policy": str(params["vertical_localization_policy"]),
        "vertical_gradient_preserve_weight": float(params["vertical_gradient_preserve_weight"]),
        "vertical_context_mismatch_damping": float(params["vertical_context_mismatch_damping"]),
        "vertical_risk_refine_enabled": float(refine_metrics.get("vertical_risk_refine_enabled", 0.0)),
        "vertical_risk_candidate_voxels_last": int(refine_metrics.get("vertical_risk_candidate_voxels_last", 0.0)),
        "vertical_oversmooth_preserve_voxels_last": int(refine_metrics.get("vertical_oversmooth_preserve_voxels_last", 0.0)),
        "vertical_context_mismatch_damped_voxels_last": int(refine_metrics.get("vertical_context_mismatch_damped_voxels_last", 0.0)),
        "current_weight_boost": float(params["current_weight_boost"]),
        "context_weight_scale": float(params["context_weight_scale"]),
        "context_time_conf_power": float(params["context_time_conf_power"]),
        "role_conflict_mode": str(params["role_conflict_mode"]),
        "conflict_speed_threshold_mps": float(params["conflict_speed_threshold_mps"]),
        "conflict_context_factor": float(params["conflict_context_factor"]),
        "cma_fusion_mode": str(params["cma_fusion_mode"]),
        "cma_background_weight": float(params["cma_background_weight"]),
        "cma_background_weight_mode": str(params["cma_background_weight_mode"]),
        "cma_confidence_source": str(params["cma_confidence_source"]),
        "cma_confidence_cap": float(params["cma_confidence_cap"]),
        "cma_time_confidence": float(params["cma_time_confidence"]),
        "cma_space_confidence": float(params["cma_space_confidence"]),
        "cma_pseudo_source": str(params["cma_pseudo_source"]),
        "cma_qc_gating": str(params["cma_qc_gating"]),
        **{key: value for key, value in role_conflict_diagnostics.items() if isinstance(value, (int, float, np.integer, np.floating))},
        **{key: value for key, value in field_diag.items() if isinstance(value, (int, float, np.integer, np.floating))},
        "strict_holdout_no_leakage": bool(leakage["strict_holdout_no_leakage"]),
        "motion_used_as_wind": bool(leakage["motion_records_used_as_wind"]),
    }
    return row


def _annotate_points(
    rows: list[dict[str, Any]],
    *,
    stage2_row: dict[str, Any],
    params: dict[str, Any],
    frame_row: dict[str, Any],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for point in rows:
        out.append(
            {
                "time_str": str(stage2_row["time_str"]),
                "kernel": params["localization_kernel"],
                "confidence_mode": params["confidence_mode"],
                "physics_constraint_mode": params["physics_constraint_mode"],
                "localization_policy": params["localization_policy"],
                "localization_radius_xy": int(params["localization_radius_xy"]),
                "localization_sigma_xy": float(params["localization_sigma_xy"]),
                "localization_radius_z": int(params["localization_radius_z"]),
                "localization_sigma_z": float(params["localization_sigma_z"]),
                "strict_holdout_no_leakage": bool(frame_row["strict_holdout_no_leakage"]),
                "motion_used_as_wind": bool(frame_row["motion_used_as_wind"]),
                **point,
                "frame_holdout_wind_records": int(frame_row["holdout_wind_records"]),
                "frame_rmse_vector": float(frame_row["rmse_vector"]),
                "frame_mae_vector": float(frame_row["mae_vector"]),
                "adaptive_reasons": frame_row.get("adaptive_reasons", ""),
                "adaptive_current_support": frame_row.get("adaptive_current_support", ""),
                "adaptive_context_support": frame_row.get("adaptive_context_support", ""),
            }
        )
    return out


def _build_stage4_baseline(stage2_row: dict[str, Any], args: argparse.Namespace, qc_calibration: dict[str, Any]) -> dict[str, Any]:
    npz_path = Path(stage2_row["multimodal_vox_path"])
    if not npz_path.is_absolute():
        npz_path = ROOT_DIR / npz_path
    npz = _load_stage2_npz(npz_path)
    shape = tuple(int(v) for v in np.asarray(npz[C2_GRID_SHAPE], dtype=np.int32).tolist())
    wind_records = _records(npz.get(C2_WIND_RECORDS))
    context_wind_records = _records(npz.get(C2_CONTEXT_WIND_RECORDS))
    motion_records = _records(npz.get(C2_MOTION_RECORDS))
    context_motion_records = _records(npz.get(C2_CONTEXT_MOTION_RECORDS))
    loc_records = _records(npz.get(C2_LOC_RECORDS))
    cloud_2d = np.asarray(npz[C2_CLOUD_2D], dtype=np.float32)

    train_wind, holdout_wind = _split_holdout(wind_records, float(args.holdout_fraction), int(args.holdout_count))
    observations, confidence_diagnostics = _build_wind_observations(
        train_wind,
        context_wind_records,
        str(args.confidence_mode),
        qc_calibration=qc_calibration,
        current_weight_boost=float(args.current_weight_boost),
        context_weight_scale=float(args.context_weight_scale),
        context_time_conf_power=float(args.context_time_conf_power),
    )

    localization_radius_xy = int(args.localization_radius_xy)
    localization_sigma_xy = float(args.localization_sigma_xy)
    localization_radius_z = int(args.localization_radius_z)
    localization_sigma_z = float(args.localization_sigma_z)
    adaptive_diagnostics: dict[str, Any] = {
        "localization_policy": str(args.localization_policy),
        "localization_candidate_grid": str(args.localization_candidate_grid),
        "adaptive_selected_radius_xy": localization_radius_xy,
        "adaptive_selected_sigma_xy": localization_sigma_xy,
        "adaptive_selected_radius_z": localization_radius_z,
        "adaptive_selected_sigma_z": localization_sigma_z,
        "adaptive_score": 0.0,
        "adaptive_reasons": "fixed",
        "adaptive_no_holdout_inputs_used": True,
    }
    if str(args.localization_policy) in {
        "diagnostic_adaptive",
        "diagnostic_adaptive_v3",
        "diagnostic_adaptive_regime_v4",
        "support_role_height_aware",
    }:
        selected_loc, adaptive_diagnostics = _select_adaptive_localization(
            train_current_wind=train_wind,
            context_wind=context_wind_records,
            observations=observations,
            candidate_grid=str(args.localization_candidate_grid),
            default_radius_xy=localization_radius_xy,
            default_sigma_xy=localization_sigma_xy,
            default_radius_z=localization_radius_z,
            default_sigma_z=localization_sigma_z,
            qc_calibration=qc_calibration,
            policy=str(args.localization_policy),
        )
        localization_radius_xy = int(selected_loc["localization_radius_xy"])
        localization_sigma_xy = float(selected_loc["localization_sigma_xy"])
        localization_radius_z = int(selected_loc["localization_radius_z"])
        localization_sigma_z = float(selected_loc["localization_sigma_z"])

    localization_context = adaptive_diagnostics
    if _is_guarded_vertical_policy(str(args.vertical_localization_policy)):
        localization_context = _make_guarded_vertical_localization_context(
            shape,
            observations,
            radius_xy=localization_radius_xy,
            radius_z=localization_radius_z,
            sigma_xy=localization_sigma_xy,
            sigma_z=localization_sigma_z,
            localization_kernel=str(args.localization_kernel),
            role_conflict_mode=str(args.role_conflict_mode),
            conflict_speed_threshold_mps=float(args.conflict_speed_threshold_mps),
            conflict_context_factor=float(args.conflict_context_factor),
            localization_policy=str(args.localization_policy),
            localization_context=adaptive_diagnostics,
            qc_calibration=qc_calibration,
        )

    acc = _accumulate_localized(
        shape,
        observations,
        radius_xy=localization_radius_xy,
        radius_z=localization_radius_z,
        sigma_xy=localization_sigma_xy,
        sigma_z=localization_sigma_z,
        localization_kernel=str(args.localization_kernel),
        role_conflict_mode=str(args.role_conflict_mode),
        conflict_speed_threshold_mps=float(args.conflict_speed_threshold_mps),
        conflict_context_factor=float(args.conflict_context_factor),
        vertical_localization_policy=str(args.vertical_localization_policy),
        localization_policy=str(args.localization_policy),
        localization_context=localization_context,
        qc_calibration=qc_calibration,
    )

    cma_path = args.cma_proxy_npz or _find_cma_proxy_npz(args.cma_proxy_dir, str(stage2_row["time_str"]))
    cma_u, cma_v, cma_conf, cma_diag = _load_cma_background(
        cma_path,
        shape,
        fusion_mode=str(args.cma_fusion_mode),
        confidence_source=str(args.cma_confidence_source),
        pseudo_source=str(args.cma_pseudo_source),
        qc_gating=str(args.cma_qc_gating),
        qc_calibration=qc_calibration,
    )
    if str(args.cma_fusion_mode) != "off":
        cma_diag.update(
            _apply_cma_background_to_accumulator(
                acc,
                cma_u=cma_u,
                cma_v=cma_v,
                cma_conf=cma_conf,
                background_weight=float(args.cma_background_weight),
                background_weight_mode=str(args.cma_background_weight_mode),
                qc_calibration=qc_calibration,
                time_confidence=float(args.cma_time_confidence),
                space_confidence=float(args.cma_space_confidence),
            )
        )

    leakage = _leakage_report(
        wind_records=wind_records,
        train_wind=train_wind,
        holdout_wind=holdout_wind,
        observations=observations,
        motion_records=motion_records,
        context_motion_records=context_motion_records,
        cma_fusion_mode=str(args.cma_fusion_mode),
        cma_proxy_npz=str(cma_path or ""),
    )

    recon = _make_reconstruction(acc)
    recon = _cap_cma_only_confidence(recon, acc, cma_confidence_cap=float(args.cma_confidence_cap))
    pre_refine_voxels = int(np.count_nonzero(recon["recon_mask"]))
    recon, refine_metrics = _pinn_diffusion_refine(
        recon,
        iterations=int(args.refine_iters),
        pinn_smoothness_weight=float(args.pinn_smoothness_weight),
        pinn_divergence_weight=float(args.pinn_divergence_weight),
        diffusion_weight=float(args.diffusion_weight),
        low_conf_fill_weight=float(args.low_conf_fill_weight),
        source_preserve=float(args.source_preserve),
        physics_constraint_mode=str(args.physics_constraint_mode),
        observation_anchor_weight=float(args.observation_anchor_weight),
        speed_limit_mps=float(args.speed_limit_mps),
        vertical_risk_mode=str(args.vertical_risk_mode),
        vertical_gradient_preserve_weight=float(args.vertical_gradient_preserve_weight),
        vertical_context_mismatch_damping=float(args.vertical_context_mismatch_damping),
    )
    recon = _finalize_effective_reconstruction(recon)

    params = {
        "localization_kernel": str(args.localization_kernel),
        "confidence_mode": str(args.confidence_mode),
        "physics_constraint_mode": str(args.physics_constraint_mode),
        "localization_policy": str(args.localization_policy),
        "localization_candidate_grid": str(args.localization_candidate_grid),
        "localization_radius_xy": localization_radius_xy,
        "localization_sigma_xy": localization_sigma_xy,
        "localization_radius_z": localization_radius_z,
        "localization_sigma_z": localization_sigma_z,
        "observation_anchor_weight": float(args.observation_anchor_weight),
        "speed_limit_mps": float(args.speed_limit_mps),
        "vertical_risk_mode": str(args.vertical_risk_mode),
        "vertical_localization_policy": str(args.vertical_localization_policy),
        "vertical_gradient_preserve_weight": float(args.vertical_gradient_preserve_weight),
        "vertical_context_mismatch_damping": float(args.vertical_context_mismatch_damping),
        "current_weight_boost": float(args.current_weight_boost),
        "context_weight_scale": float(args.context_weight_scale),
        "context_time_conf_power": float(args.context_time_conf_power),
        "role_conflict_mode": str(args.role_conflict_mode),
        "conflict_speed_threshold_mps": float(args.conflict_speed_threshold_mps),
        "conflict_context_factor": float(args.conflict_context_factor),
        "cma_fusion_mode": str(args.cma_fusion_mode),
        "cma_background_weight": float(args.cma_background_weight),
        "cma_background_weight_mode": str(args.cma_background_weight_mode),
        "cma_confidence_source": str(args.cma_confidence_source),
        "cma_confidence_cap": float(args.cma_confidence_cap),
        "cma_time_confidence": float(args.cma_time_confidence),
        "cma_space_confidence": float(args.cma_space_confidence),
        "cma_pseudo_source": str(args.cma_pseudo_source),
        "cma_qc_gating": str(args.cma_qc_gating),
    }
    counts = {
        "wind_records_total": int(len(wind_records)),
        "holdout_wind_records": int(len(holdout_wind)),
        "fusion_current_wind_records": int(len(train_wind)),
        "context_wind_records": int(len(context_wind_records)),
        "trajectory_records": int(len(loc_records)),
        "motion_records_diagnostic_only": int(len(motion_records)),
        "context_motion_records_diagnostic_only": int(len(context_motion_records)),
    }
    point_rows = _point_eval_rows(holdout_wind, recon["recon_u"], recon["recon_v"], recon["recon_conf"], observations, acc)
    role_diag = _role_conflict_diagnostics(acc)
    return {
        "npz": npz,
        "shape": shape,
        "cloud_2d": cloud_2d,
        "observations": observations,
        "holdout_wind": holdout_wind,
        "acc": acc,
        "recon": recon,
        "pre_refine_voxels": pre_refine_voxels,
        "point_rows": point_rows,
        "leakage": leakage,
        "params": params,
        "counts": counts,
        "adaptive": adaptive_diagnostics,
        "confidence_diagnostics": confidence_diagnostics,
        "refine_metrics": refine_metrics,
        "role_conflict_diagnostics": role_diag,
        "cma_diagnostics": cma_diag,
    }


def _support_feature_fields(
    shape: tuple[int, int, int],
    observations: list[dict[str, Any]],
    *,
    radius_xy: int,
    radius_z: int,
) -> dict[str, np.ndarray]:
    current_count = np.zeros(shape, dtype=np.float32)
    context_count = np.zeros(shape, dtype=np.float32)
    nearest_dist = np.full(shape, np.float32(1.0e6), dtype=np.float32)
    nearest_u = np.zeros(shape, dtype=np.float32)
    nearest_v = np.zeros(shape, dtype=np.float32)
    nearest_w = np.zeros(shape, dtype=np.float32)
    nearest_role = np.zeros(shape, dtype=np.int8)
    z_dim, h_dim, w_dim = shape
    for obs in observations:
        z = int(obs["z"])
        y = int(obs["y"])
        x = int(obs["x"])
        if not (0 <= z < z_dim and 0 <= y < h_dim and 0 <= x < w_dim):
            continue
        z0 = max(0, z - int(radius_z))
        z1 = min(z_dim, z + int(radius_z) + 1)
        y0 = max(0, y - int(radius_xy))
        y1 = min(h_dim, y + int(radius_xy) + 1)
        x0 = max(0, x - int(radius_xy))
        x1 = min(w_dim, x + int(radius_xy) + 1)
        dz = (np.arange(z0, z1, dtype=np.float32) - float(z))[:, None, None]
        dy = (np.arange(y0, y1, dtype=np.float32) - float(y))[None, :, None]
        dx = (np.arange(x0, x1, dtype=np.float32) - float(x))[None, None, :]
        dist = np.sqrt((dx * dx + dy * dy + dz * dz).astype(np.float32)).astype(np.float32)
        if str(obs.get("source_role")) == "current_wind_train":
            current_count[z0:z1, y0:y1, x0:x1] += 1.0
            role_value = np.int8(1)
        else:
            context_count[z0:z1, y0:y1, x0:x1] += 1.0
            role_value = np.int8(2)
        patch = nearest_dist[z0:z1, y0:y1, x0:x1]
        update = dist < patch
        if np.any(update):
            patch[update] = dist[update]
            nearest_dist[z0:z1, y0:y1, x0:x1] = patch
            nearest_u_patch = nearest_u[z0:z1, y0:y1, x0:x1]
            nearest_v_patch = nearest_v[z0:z1, y0:y1, x0:x1]
            nearest_w_patch = nearest_w[z0:z1, y0:y1, x0:x1]
            nearest_role_patch = nearest_role[z0:z1, y0:y1, x0:x1]
            nearest_u_patch[update] = np.float32(obs["u"])
            nearest_v_patch[update] = np.float32(obs["v"])
            nearest_w_patch[update] = np.float32(obs.get("base_weight", 0.0))
            nearest_role_patch[update] = role_value
            nearest_u[z0:z1, y0:y1, x0:x1] = nearest_u_patch
            nearest_v[z0:z1, y0:y1, x0:x1] = nearest_v_patch
            nearest_w[z0:z1, y0:y1, x0:x1] = nearest_w_patch
            nearest_role[z0:z1, y0:y1, x0:x1] = nearest_role_patch
    nearest_dist = np.where(nearest_dist < 1.0e5, nearest_dist, np.float32(radius_xy + radius_z + 1)).astype(np.float32)
    return {
        "current_count": current_count,
        "context_count": context_count,
        "nearest_dist": nearest_dist,
        "nearest_u": nearest_u,
        "nearest_v": nearest_v,
        "nearest_w": nearest_w,
        "nearest_role": nearest_role,
    }


def _field_dataframe(stage4: dict[str, Any], time_str: str) -> tuple[pd.DataFrame, np.ndarray]:
    recon = stage4["recon"]
    acc = stage4["acc"]
    params = stage4["params"]
    shape = tuple(int(v) for v in stage4["shape"])
    u = np.asarray(recon["recon_u"], dtype=np.float32)
    v = np.asarray(recon["recon_v"], dtype=np.float32)
    conf = np.asarray(recon["recon_conf"], dtype=np.float32)
    mask = np.asarray(recon["recon_mask"], dtype=np.float32) > 0.0
    active_idx = np.argwhere(mask)
    if active_idx.size == 0:
        return pd.DataFrame(), active_idx
    z = active_idx[:, 0].astype(np.float32)
    y = active_idx[:, 1].astype(np.float32)
    x = active_idx[:, 2].astype(np.float32)
    _, h_dim, w_dim = shape
    lat = LAT_MAX - (y + 0.5) / float(h_dim) * (LAT_MAX - LAT_MIN)
    lon = LON_MIN + (x + 0.5) / float(w_dim) * (LON_MAX - LON_MIN)
    alt_m = ALT_MIN + z * float(DELTA_ALT)
    pred_u = u[mask]
    pred_v = v[mask]
    pred_speed = np.sqrt((pred_u * pred_u + pred_v * pred_v).astype(np.float32)).astype(np.float32)
    vertical_jump = _vertical_jump_field(u, v)
    vertical_mean, vertical_max = _vertical_neighbor_speed_stats(u, v)
    vertical_speed_gap = np.abs(np.sqrt((u * u + v * v).astype(np.float32)) - vertical_mean).astype(np.float32)
    support = _support_feature_fields(
        shape,
        stage4["observations"],
        radius_xy=max(1, int(params["localization_radius_xy"])),
        radius_z=max(0, int(params["localization_radius_z"])),
    )
    role = support["nearest_role"][mask]
    nearest_source = np.where(role == 1, "current_wind_train", np.where(role == 2, "context_wind", ""))
    role_gap = np.asarray(acc.get("role_conflict_component_gap"), dtype=np.float32)
    threshold = np.asarray(acc.get("role_conflict_threshold_field"), dtype=np.float32)
    context_factor = np.asarray(acc.get("role_conflict_context_factor_field"), dtype=np.float32)
    current_density = np.asarray(acc.get("role_conflict_current_density_field"), dtype=np.float32)
    context_time = np.asarray(acc.get("role_conflict_context_time_mean_field"), dtype=np.float32)
    context_w = np.asarray(acc.get("acc_context_w"), dtype=np.float32)
    context_removed = np.asarray(acc.get("conflict_context_removed_w"), dtype=np.float32)
    conflict_mask = np.asarray(acc.get("role_conflict_mask"), dtype=bool)
    current_w = np.asarray(acc.get("acc_current_w"), dtype=np.float32)

    df = pd.DataFrame(
        {
            "time_str": str(time_str),
            "z": z,
            "y": y,
            "x": x,
            "lat": lat.astype(np.float32),
            "lon": lon.astype(np.float32),
            "alt_m": alt_m.astype(np.float32),
            "pred_u": pred_u,
            "pred_v": pred_v,
            "pred_speed": pred_speed,
            "recon_confidence": conf[mask],
            "obs_count": (support["current_count"][mask] + support["context_count"][mask]).astype(np.float32),
            "obs_conf": np.ones(int(active_idx.shape[0]), dtype=np.float32),
            "nearest_role_gap_mps": role_gap[mask] if role_gap.shape == shape else np.zeros(int(active_idx.shape[0]), dtype=np.float32),
            "nearest_current_count": support["current_count"][mask],
            "nearest_context_count": support["context_count"][mask],
            "recon_vertical_jump_mps": vertical_jump[mask],
            "vertical_speed_gap_mps": vertical_speed_gap[mask],
            "vertical_neighbor_max_speed_mps": vertical_max[mask],
            "role_conflict_component_gap_at_point_mps": role_gap[mask] if role_gap.shape == shape else 0.0,
            "role_conflict_threshold_at_point_mps": threshold[mask] if threshold.shape == shape else 0.0,
            "role_conflict_context_factor_at_point": context_factor[mask] if context_factor.shape == shape else 0.0,
            "role_conflict_current_density_at_point": current_density[mask] if current_density.shape == shape else 0.0,
            "role_conflict_context_time_conf_at_point": context_time[mask] if context_time.shape == shape else 0.0,
            "role_conflict_context_weight_at_point": context_w[mask] if context_w.shape == shape else 0.0,
            "role_conflict_context_removed_weight_at_point": context_removed[mask] if context_removed.shape == shape else 0.0,
            "nearest_train_distance_vox": support["nearest_dist"][mask],
            "nearest_train_u": support["nearest_u"][mask],
            "nearest_train_v": support["nearest_v"][mask],
            "nearest_train_base_weight": support["nearest_w"][mask],
            "adaptive_current_support": float(stage4["adaptive"].get("adaptive_current_support", stage4["counts"]["fusion_current_wind_records"])),
            "adaptive_context_support": float(stage4["adaptive"].get("adaptive_context_support", stage4["counts"]["context_wind_records"])),
            "localization_radius_xy": float(params["localization_radius_xy"]),
            "localization_sigma_xy": float(params["localization_sigma_xy"]),
            "localization_radius_z": float(params["localization_radius_z"]),
            "localization_sigma_z": float(params["localization_sigma_z"]),
            "role_overlap_at_point": ((current_w[mask] > 0.0) & (context_w[mask] > 0.0)) if current_w.shape == shape else False,
            "role_conflict_at_point": conflict_mask[mask] if conflict_mask.shape == shape else False,
            "nearest_train_source_role": nearest_source,
        }
    )
    return df, active_idx


def _predict_delta(
    model: ResidualMLP,
    ckpt: dict[str, Any],
    features: pd.DataFrame,
    feature_names: list[str],
    *,
    device: torch.device,
    batch_size: int,
) -> np.ndarray:
    if features.empty:
        return np.zeros((0, 2), dtype=np.float32)
    x = features[feature_names].to_numpy(dtype=np.float32)
    mean = np.asarray(ckpt["normalizer"]["feature_mean"], dtype=np.float32)
    std = np.asarray(ckpt["normalizer"]["feature_std"], dtype=np.float32)
    std = np.where(std < 1e-6, 1.0, std)
    x = ((x - mean) / std).astype(np.float32)
    out = np.zeros((x.shape[0], 2), dtype=np.float32)
    model.eval()
    with torch.no_grad():
        for start in range(0, x.shape[0], max(1, int(batch_size))):
            end = min(x.shape[0], start + max(1, int(batch_size)))
            batch = torch.as_tensor(x[start:end], dtype=torch.float32, device=device)
            delta, _sigma = model(batch)
            out[start:end] = delta.detach().cpu().numpy().astype(np.float32)
    return out


def _apply_stage5(stage4: dict[str, Any], model: ResidualMLP, ckpt: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    time_str = str(stage4["npz"].get(C2_TIME_STR, ""))
    if not time_str:
        time_str = str(args.current_time_for_log)
    field_df, active_idx = _field_dataframe(stage4, time_str)
    recon = stage4["recon"]
    candidate = {key: np.asarray(value).copy() for key, value in recon.items()}
    if field_df.empty:
        return {
            "recon": candidate,
            "active_idx": active_idx,
            "gate": np.zeros((0,), dtype=bool),
            "raw_delta": np.zeros((0, 2), dtype=np.float32),
            "feature_rows": 0,
            "smoke": {"stage5_gate_voxels": 0, "stage5_changed_voxels": 0},
        }

    features, built_names = _build_features(field_df)
    schema = ckpt.get("feature_schema", {}) if isinstance(ckpt.get("feature_schema"), dict) else {}
    feature_names = list(schema.get("feature_names", built_names))
    missing = [name for name in feature_names if name not in features.columns]
    if missing:
        raise ValueError(f"Field feature construction is missing checkpoint features: {missing}")
    device = torch.device(args.device)
    raw_delta = _predict_delta(
        model,
        ckpt,
        features,
        feature_names,
        device=device,
        batch_size=int(args.torch_batch_size),
    )
    vertical_proxy = np.maximum(
        features["vertical_speed_gap_mps"].to_numpy(dtype=np.float32),
        features["recon_vertical_jump_mps"].to_numpy(dtype=np.float32),
    )
    pred_light = features["pred_light_wind_flag"].to_numpy(dtype=np.float32) > 0.5
    if str(args.stage5_gate) != "vertical_gap_ge20_not_light":
        raise ValueError("Only locked gate vertical_gap_ge20_not_light is supported for field_v1 smoke.")
    gate = (vertical_proxy >= 20.0) & (~pred_light)
    scale = float(args.stage5_scale)
    z = active_idx[:, 0]
    y = active_idx[:, 1]
    x = active_idx[:, 2]
    base_u = np.asarray(recon["recon_u"], dtype=np.float32)
    base_v = np.asarray(recon["recon_v"], dtype=np.float32)
    cand_u = candidate["recon_u"]
    cand_v = candidate["recon_v"]
    cand_u[z[gate], y[gate], x[gate]] = base_u[z[gate], y[gate], x[gate]] + np.float32(scale) * raw_delta[gate, 0]
    cand_v[z[gate], y[gate], x[gate]] = base_v[z[gate], y[gate], x[gate]] + np.float32(scale) * raw_delta[gate, 1]
    diff = np.sqrt(((cand_u - base_u) ** 2 + (cand_v - base_v) ** 2).astype(np.float32)).astype(np.float32)
    full_gate = np.zeros(base_u.shape, dtype=bool)
    full_gate[z[gate], y[gate], x[gate]] = True
    non_gate_changed = np.count_nonzero((diff > 1e-6) & ~full_gate)
    smoke = {
        "stage5_gate": str(args.stage5_gate),
        "stage5_scale": scale,
        "stage5_feature_rows": int(field_df.shape[0]),
        "stage5_gate_voxels": int(np.count_nonzero(gate)),
        "stage5_gate_fraction_active": float(np.count_nonzero(gate) / max(1, int(field_df.shape[0]))),
        "stage5_changed_voxels": int(np.count_nonzero(diff > 1e-6)),
        "stage5_non_gate_changed_voxels": int(non_gate_changed),
        "stage5_max_abs_raw_delta_mps": float(np.max(np.abs(raw_delta))) if raw_delta.size else 0.0,
        "stage5_max_vector_residual_mps": float(np.max(diff)) if diff.size else 0.0,
        "stage5_nan_or_inf_count": int(
            np.count_nonzero(~np.isfinite(cand_u)) + np.count_nonzero(~np.isfinite(cand_v))
        ),
        "stage5_non_gate_unchanged": bool(non_gate_changed == 0),
        "stage5_residual_cap_ok": bool((float(np.max(np.abs(raw_delta))) if raw_delta.size else 0.0) <= float(args.delta_cap_tolerance)),
    }
    return {"recon": candidate, "active_idx": active_idx, "gate": gate, "raw_delta": raw_delta, "feature_rows": int(field_df.shape[0]), "smoke": smoke}


def _write_field_npz(path: Path, *, stage2_row: dict[str, Any], stage4: dict[str, Any], stage5: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    recon = stage4["recon"]
    cand = stage5["recon"]
    active_idx = stage5["active_idx"]
    gate = stage5["gate"]
    raw_delta = stage5["raw_delta"]
    full_gate = np.zeros(np.asarray(recon["recon_u"]).shape, dtype=np.float32)
    full_delta_u = np.zeros_like(np.asarray(recon["recon_u"], dtype=np.float32))
    full_delta_v = np.zeros_like(full_delta_u)
    if active_idx.size and gate.size:
        z = active_idx[:, 0]
        y = active_idx[:, 1]
        x = active_idx[:, 2]
        full_gate[z[gate], y[gate], x[gate]] = 1.0
        full_delta_u[z, y, x] = raw_delta[:, 0]
        full_delta_v[z, y, x] = raw_delta[:, 1]
    np.savez_compressed(
        path,
        **{
            C2_TIME_STR: np.array(str(stage2_row["time_str"])),
            C2_TIMESTAMP_UTC: np.array(str(stage2_row.get("timestamp_utc", ""))),
            "stage5_candidate_label": np.array("tp26_residual_pinn_field_v1_smoke"),
            "stage5_gate_mask_3d": full_gate,
            "stage5_raw_delta_u_3d": full_delta_u,
            "stage5_raw_delta_v_3d": full_delta_v,
            "stage5_smoke_json": np.array(json.dumps(stage5["smoke"], ensure_ascii=False)),
            "baseline_recon_u_3d": recon["recon_u"],
            "baseline_recon_v_3d": recon["recon_v"],
            "baseline_recon_confidence_3d": recon["recon_conf"],
            "baseline_recon_mask_3d": recon["recon_mask"],
            "stage5_recon_u_3d": cand["recon_u"],
            "stage5_recon_v_3d": cand["recon_v"],
            "stage5_recon_confidence_3d": cand["recon_conf"],
            "stage5_recon_mask_3d": cand["recon_mask"],
            C4_RECON_U: cand["recon_u"],
            C4_RECON_V: cand["recon_v"],
            C4_RECON_CONF: cand["recon_conf"],
            C4_RECON_MASK: cand["recon_mask"],
            C4_CLOUD_2D: stage4["cloud_2d"],
        },
    )


def _write_report(path: Path, smoke_rows: list[dict[str, Any]], run_meta: dict[str, Any]) -> None:
    lines = [
        "# Stage5 Residual PINN Field Apply Report",
        "",
        "Stage5 is a candidate residual layer on top of Stage4 `tp26_thr11_preserve`; Stage4 remains the default.",
        "",
        "## Run",
        "",
        f"- frames: `{len(smoke_rows)}`",
        f"- checkpoint: `{run_meta['checkpoint']}`",
        f"- gate: `{run_meta['stage5_gate']}`",
        f"- scale: `{run_meta['stage5_scale']}`",
        f"- save field npz: `{run_meta['save_field_npz']}`",
        "",
        "## Smoke Summary",
        "",
        "| frame | active features | gate voxels | changed voxels | non-gate changed | max residual | raw cap ok | nan/inf | baseline RMSE | stage5 RMSE |",
        "| --- | ---: | ---: | ---: | ---: | ---: | --- | ---: | ---: | ---: |",
    ]
    for row in smoke_rows:
        lines.append(
            f"| `{row['time_str']}` | {int(row.get('stage5_feature_rows', 0))} | "
            f"{int(row.get('stage5_gate_voxels', 0))} | {int(row.get('stage5_changed_voxels', 0))} | "
            f"{int(row.get('stage5_non_gate_changed_voxels', 0))} | "
            f"{float(row.get('stage5_max_vector_residual_mps', 0.0)):.6f} | "
            f"`{row.get('stage5_residual_cap_ok')}` | {int(row.get('stage5_nan_or_inf_count', 0))} | "
            f"{float(row.get('baseline_rmse_vector', 0.0)):.6f} | {float(row.get('candidate_rmse_vector', 0.0)):.6f} |"
        )
    overall = all(
        bool(row.get("stage5_non_gate_unchanged"))
        and bool(row.get("stage5_residual_cap_ok"))
        and int(row.get("stage5_nan_or_inf_count", 0)) == 0
        for row in smoke_rows
    )
    lines.extend(["", f"Smoke overall: `{'PASS' if overall else 'FAIL'}`", ""])
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply locked Stage5 residual PINN to Stage4 full fields.")
    parser.add_argument("--stage2-summary", type=Path, default=REGENERATED_STAGE2_OUTPUT_DIR / "stage2_multimodal_summary.json")
    parser.add_argument("--frame-times", default=SMOKE_FRAMES)
    parser.add_argument("--frame-times-file", type=Path)
    parser.add_argument("--out-root", type=Path, default=DEFAULT_OUT_ROOT)
    parser.add_argument("--checkpoint", type=Path, default=DEFAULT_CHECKPOINT)
    parser.add_argument("--save-field-npz", action="store_true")
    parser.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    parser.add_argument("--torch-batch-size", type=int, default=65536)
    parser.add_argument("--stage5-gate", default="vertical_gap_ge20_not_light")
    parser.add_argument("--stage5-scale", type=float, default=1.0)
    parser.add_argument("--delta-cap-tolerance", type=float, default=1.00001)
    parser.add_argument("--qc-calibration", type=Path)

    parser.add_argument("--holdout-fraction", type=float, default=0.125)
    parser.add_argument("--holdout-count", type=int, default=0)
    parser.add_argument("--localization-kernel", choices=sorted(LOCALIZATION_KERNELS), default="gaussian")
    parser.add_argument("--localization-radius-xy", type=int, default=8)
    parser.add_argument("--localization-sigma-xy", type=float, default=4.0)
    parser.add_argument("--localization-radius-z", type=int, default=2)
    parser.add_argument("--localization-sigma-z", type=float, default=1.0)
    parser.add_argument("--localization-policy", choices=sorted(LOCALIZATION_POLICIES), default="diagnostic_adaptive_v3")
    parser.add_argument("--localization-candidate-grid", default="8:4,10:5")
    parser.add_argument("--confidence-mode", choices=sorted(CONFIDENCE_MODES), default="diagnostic_weighted")
    parser.add_argument("--refine-iters", type=int, default=4)
    parser.add_argument("--pinn-smoothness-weight", type=float, default=0.018)
    parser.add_argument("--pinn-divergence-weight", type=float, default=0.010)
    parser.add_argument("--diffusion-weight", type=float, default=0.22)
    parser.add_argument("--low-conf-fill-weight", type=float, default=0.72)
    parser.add_argument("--source-preserve", type=float, default=0.95)
    parser.add_argument("--physics-constraint-mode", choices=sorted(PHYSICS_CONSTRAINT_MODES), default="pydda_3dvar_proxy")
    parser.add_argument("--observation-anchor-weight", type=float, default=0.10)
    parser.add_argument("--speed-limit-mps", type=float, default=120.0)
    parser.add_argument("--vertical-risk-mode", choices=sorted(VERTICAL_RISK_MODES), default="preserve_strong_layers")
    parser.add_argument("--vertical-localization-policy", choices=sorted(VERTICAL_LOCALIZATION_POLICIES), default="fixed")
    parser.add_argument("--vertical-gradient-preserve-weight", type=float, default=0.12)
    parser.add_argument("--vertical-context-mismatch-damping", type=float, default=0.35)
    parser.add_argument("--current-weight-boost", type=float, default=2.0)
    parser.add_argument("--context-weight-scale", type=float, default=0.5)
    parser.add_argument("--context-time-conf-power", type=float, default=2.6)
    parser.add_argument("--role-conflict-mode", choices=sorted(ROLE_CONFLICT_MODES), default="current_priority_adaptive")
    parser.add_argument("--conflict-speed-threshold-mps", type=float, default=11.0)
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
    args = parser.parse_args()
    setattr(args, "current_time_for_log", "")

    if str(args.device).startswith("cuda") and not torch.cuda.is_available():
        args.device = "cpu"
    ckpt = torch.load(args.checkpoint, map_location=str(args.device))
    model = ResidualMLP(
        int(ckpt["input_dim"]),
        int(ckpt["width"]),
        int(ckpt["layers"]),
        float(ckpt["delta_cap_mps"]),
    ).to(torch.device(args.device))
    model.load_state_dict(ckpt["model_state_dict"])
    model.eval()
    qc_calibration = _load_qc_calibration(args.qc_calibration)
    frame_times = _read_frame_times(str(args.frame_times), args.frame_times_file)
    rows = _select_stage2_rows(args.stage2_summary, frame_times)

    baseline_frame_rows: list[dict[str, Any]] = []
    candidate_frame_rows: list[dict[str, Any]] = []
    baseline_points: list[dict[str, Any]] = []
    candidate_points: list[dict[str, Any]] = []
    smoke_rows: list[dict[str, Any]] = []
    field_dir = args.out_root / "field_npz"
    for idx, stage2_row in enumerate(rows, start=1):
        time_str = str(stage2_row["time_str"])
        setattr(args, "current_time_for_log", time_str)
        print(f"[Stage5 field apply] {idx}/{len(rows)} {time_str}", flush=True)
        stage4 = _build_stage4_baseline(stage2_row, args, qc_calibration)
        baseline_row = _frame_row(
            stage2_row=stage2_row,
            label="tp26_thr11_preserve",
            point_rows=stage4["point_rows"],
            recon=stage4["recon"],
            pre_refine_voxels=stage4["pre_refine_voxels"],
            leakage=stage4["leakage"],
            params=stage4["params"],
            counts=stage4["counts"],
            adaptive=stage4["adaptive"],
            confidence_diagnostics=stage4["confidence_diagnostics"],
            refine_metrics=stage4["refine_metrics"],
            role_conflict_diagnostics=stage4["role_conflict_diagnostics"],
        )
        stage5 = _apply_stage5(stage4, model, ckpt, args)
        candidate_point_rows = _point_eval_rows(
            stage4["holdout_wind"],
            stage5["recon"]["recon_u"],
            stage5["recon"]["recon_v"],
            stage5["recon"]["recon_conf"],
            stage4["observations"],
            stage4["acc"],
        )
        candidate_row = _frame_row(
            stage2_row=stage2_row,
            label="tp26_residual_pinn_field_v1_smoke",
            point_rows=candidate_point_rows,
            recon=stage5["recon"],
            pre_refine_voxels=stage4["pre_refine_voxels"],
            leakage=stage4["leakage"],
            params=stage4["params"],
            counts=stage4["counts"],
            adaptive=stage4["adaptive"],
            confidence_diagnostics=stage4["confidence_diagnostics"],
            refine_metrics=stage4["refine_metrics"],
            role_conflict_diagnostics=stage4["role_conflict_diagnostics"],
        )
        if args.save_field_npz:
            _write_field_npz(
                field_dir / f"frame_{time_str}_stage5_residual_pinn_field_v1.npz",
                stage2_row=stage2_row,
                stage4=stage4,
                stage5=stage5,
            )
        baseline_frame_rows.append(baseline_row)
        candidate_frame_rows.append(candidate_row)
        baseline_points.extend(
            _annotate_points(stage4["point_rows"], stage2_row=stage2_row, params=stage4["params"], frame_row=baseline_row)
        )
        candidate_points.extend(
            _annotate_points(candidate_point_rows, stage2_row=stage2_row, params=stage4["params"], frame_row=candidate_row)
        )
        smoke_rows.append(
            {
                "time_str": time_str,
                **stage5["smoke"],
                "stage5_feature_rows": int(stage5["feature_rows"]),
                "baseline_rmse_vector": float(baseline_row["rmse_vector"]),
                "candidate_rmse_vector": float(candidate_row["rmse_vector"]),
                "baseline_mae_vector": float(baseline_row["mae_vector"]),
                "candidate_mae_vector": float(candidate_row["mae_vector"]),
            }
        )

    baseline_dir = args.out_root / "tp26_thr11_preserve_metrics"
    candidate_dir = args.out_root / "tp26_residual_pinn_field_v1_metrics"
    _write_csv(baseline_dir / "stage4_localization_sensitivity.csv", baseline_frame_rows)
    _write_csv(baseline_dir / "stage4_point_departures.csv", baseline_points)
    _write_csv(candidate_dir / "stage4_localization_sensitivity.csv", candidate_frame_rows)
    _write_csv(candidate_dir / "stage4_point_departures.csv", candidate_points)
    (args.out_root / "stage5_field_frame_times.txt").write_text("\n".join(frame_times) + "\n", encoding="utf-8")
    _write_csv(args.out_root / "stage5_field_smoke_summary.csv", smoke_rows)
    run_meta = {
        "stage2_summary": str(args.stage2_summary),
        "checkpoint": str(args.checkpoint),
        "stage5_gate": str(args.stage5_gate),
        "stage5_scale": float(args.stage5_scale),
        "save_field_npz": bool(args.save_field_npz),
        "device": str(args.device),
        "frames": frame_times,
        "baseline_csv": str(baseline_dir / "stage4_localization_sensitivity.csv"),
        "candidate_csv": str(candidate_dir / "stage4_localization_sensitivity.csv"),
        "baseline_point_csv": str(baseline_dir / "stage4_point_departures.csv"),
        "candidate_point_csv": str(candidate_dir / "stage4_point_departures.csv"),
        "stage4_default_unchanged": True,
        "candidate_only": True,
    }
    args.out_root.mkdir(parents=True, exist_ok=True)
    (args.out_root / "stage5_field_apply_run.json").write_text(json.dumps(run_meta, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_report(args.out_root / "stage5_field_apply_report.md", smoke_rows, run_meta)
    print(args.out_root / "stage5_field_apply_report.md")


if __name__ == "__main__":
    main()
