"""Stage4 localization sensitivity table for centralized_v1 strict hold-out.

This script intentionally writes table outputs only. It reuses the Stage4
strict reconstruction functions but does not save per-parameter 3D NPZ fields.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

ROOT_DIR = Path(__file__).resolve().parents[3]
STAGE_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
if str(STAGE_DIR) not in sys.path:
    sys.path.insert(0, str(STAGE_DIR))

from stage.centralized_v1.configs.centralized_v1_config import REGENERATED_STAGE2_OUTPUT_DIR
from stage.centralized_v1.core.centralized_stage4_ground_recon import (
    CMA_BACKGROUND_WEIGHT_MODES,
    CMA_CONFIDENCE_SOURCES,
    CMA_FUSION_MODES,
    CMA_PSEUDO_SOURCES,
    CMA_QC_GATING_MODES,
    CONFIDENCE_MODES,
    DEFAULT_QC_CALIBRATION,
    LOCALIZATION_POLICIES,
    LOCALIZATION_KERNELS,
    PHYSICS_CONSTRAINT_MODES,
    ROLE_CONFLICT_MODES,
    STRICT_STAGE4_OUTPUT_DIR,
    VERTICAL_LOCALIZATION_POLICIES,
    VERTICAL_RISK_MODES,
    _accumulate_localized,
    _apply_cma_background_to_accumulator,
    _build_wind_observations,
    _cap_cma_only_confidence,
    _field_proxy_diagnostics,
    _finalize_effective_reconstruction,
    _find_cma_proxy_npz,
    _leakage_report,
    _load_cma_background,
    _load_json,
    _load_qc_calibration,
    _load_stage2_npz,
    _make_reconstruction,
    _metric_summary,
    _parse_frame_times,
    _pinn_diffusion_refine,
    _point_eval_rows,
    _records,
    _reconstruction_extent_stats,
    _role_conflict_diagnostics,
    _select_adaptive_localization,
    _split_holdout,
)
from stage.centralized_v1.configs.centralized_v1_contract import (
    C2_CLOUD_2D,
    C2_CONTEXT_MOTION_RECORDS,
    C2_CONTEXT_WIND_RECORDS,
    C2_GRID_SHAPE,
    C2_LOC_RECORDS,
    C2_MOTION_RECORDS,
    C2_WIND_RECORDS,
)
from stage.centralized_v1.core.centralized_stage4_stratified_eval import write_stratified_eval


DEFAULT_EXPANDED_FRAMES = (
    "20260131073000,"
    "20260206174200,"
    "20260207022400,"
    "20260208124800,"
    "20260210060000,"
    "20260211060600,"
    "20260213053600,"
    "20260215063000,"
    "20260215063600,"
    "20260215100600"
)

DEFAULT_PARAM_GRID = "8,4,2,1;12,6,2,1;16,8,3,1.5"
DEFAULT_EXPANDED_STAGE3_SUMMARY = Path("/data/LFT-W02_data/pengxu/centralized_v1_output/stage3_center_expanded/stage3_center_summary.json")
DEFAULT_SENSITIVITY_DIR = Path("/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_center_strict_expanded/sensitivity")


def _parse_param_grid(text: str) -> list[dict[str, float | int]]:
    params: list[dict[str, float | int]] = []
    for item in str(text).split(";"):
        token = item.strip()
        if not token:
            continue
        parts = [p.strip() for p in token.split(",")]
        if len(parts) != 4:
            raise ValueError(f"Parameter grid entry must be rxy,sxy,rz,sz: {token}")
        params.append(
            {
                "localization_radius_xy": int(parts[0]),
                "localization_sigma_xy": float(parts[1]),
                "localization_radius_z": int(parts[2]),
                "localization_sigma_z": float(parts[3]),
            }
        )
    if not params:
        raise ValueError("No sensitivity parameter combinations were provided.")
    return params


def _select_rows(rows: list[dict[str, Any]], frame_times: str) -> list[dict[str, Any]]:
    wanted = _parse_frame_times(frame_times)
    if not wanted:
        return rows
    selected = [row for row in rows if str(row.get("time_str")) in wanted]
    found = {str(row.get("time_str")) for row in selected}
    missing = sorted(wanted - found)
    if missing:
        raise ValueError(f"Requested frame-times not found in Stage2 summary: {missing}")
    return sorted(selected, key=lambda row: str(row["time_str"]))


def _frame_times_from_args(frame_times: str, frame_times_file: Path | None) -> str:
    if frame_times_file is None:
        return frame_times
    lines = [
        line.strip()
        for line in frame_times_file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return ",".join(lines)


def _sample_rows(rows: list[dict[str, Any]], sample_count: int, sample_seed: int) -> list[dict[str, Any]]:
    sample_count = int(sample_count)
    if sample_count <= 0 or sample_count >= len(rows):
        return sorted(rows, key=lambda row: str(row["time_str"]))
    rng = np.random.default_rng(int(sample_seed))
    indices = sorted(int(i) for i in rng.choice(len(rows), size=sample_count, replace=False))
    return sorted([rows[i] for i in indices], key=lambda row: str(row["time_str"]))


def _write_frame_times(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(str(row["time_str"]) for row in rows) + "\n",
        encoding="utf-8",
    )


def _print_progress(done: int, total: int, *, started: float, force: bool = False) -> None:
    if total <= 0:
        return
    percent = 100.0 * float(done) / float(total)
    elapsed = max(0.0, time.time() - started)
    rate = float(done) / elapsed if elapsed > 0.0 and done > 0 else 0.0
    remaining = (total - done) / rate if rate > 0.0 else 0.0
    if force or done == 0 or done == total:
        print(
            f"[Stage4 sensitivity progress] {done}/{total} tasks ({percent:.2f}%), "
            f"elapsed={elapsed:.1f}s, eta={remaining:.1f}s",
            flush=True,
        )


def _write_progress(path: Path | None, *, completed: int, total: int, shard_id: int, status: str) -> None:
    if path is None:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "completed": int(completed),
        "total": int(total),
        "shard_id": int(shard_id),
        "status": str(status),
        "updated_at": time.time(),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_progress(path: Path, fallback_total: int) -> tuple[int, int]:
    if not path.exists():
        return 0, int(fallback_total)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return int(payload.get("completed", 0)), int(payload.get("total", fallback_total))
    except Exception:
        return 0, int(fallback_total)


def _print_parent_progress(progress_files: list[tuple[Path, int]], *, started: float, workers: int, force: bool = False) -> None:
    total = 0
    completed = 0
    for path, fallback_total in progress_files:
        done, part_total = _read_progress(path, fallback_total)
        completed += max(0, min(done, part_total))
        total += max(0, part_total)
    if total <= 0:
        return
    percent = 100.0 * float(completed) / float(total)
    elapsed = max(0.0, time.time() - started)
    rate = float(completed) / elapsed if elapsed > 0.0 and completed > 0 else 0.0
    remaining = (total - completed) / rate if rate > 0.0 else 0.0
    if force or completed == 0 or completed == total:
        print(
            f"[Stage4 sensitivity {int(workers)}w progress] {completed}/{total} tasks ({percent:.2f}%), "
            f"elapsed={elapsed:.1f}s, eta={remaining:.1f}s",
            flush=True,
        )


def _evaluate_metrics_only(
    stage2_row: dict[str, Any],
    *,
    localization_kernel: str,
    confidence_mode: str,
    holdout_fraction: float,
    holdout_count: int,
    localization_radius_xy: int,
    localization_radius_z: int,
    localization_sigma_xy: float,
    localization_sigma_z: float,
    refine_iters: int,
    pinn_smoothness_weight: float,
    pinn_divergence_weight: float,
    diffusion_weight: float,
    low_conf_fill_weight: float,
    source_preserve: float,
    physics_constraint_mode: str,
    observation_anchor_weight: float,
    speed_limit_mps: float,
    localization_policy: str = "fixed",
    localization_candidate_grid: str = "6:3,8:4,10:5,12:6",
    vertical_risk_mode: str = "off",
    vertical_gradient_preserve_weight: float = 0.12,
    vertical_context_mismatch_damping: float = 0.35,
    qc_calibration: dict[str, Any] | None = None,
    current_weight_boost: float = 1.0,
    context_weight_scale: float = 1.0,
    context_time_conf_power: float = 1.0,
    role_conflict_mode: str = "off",
    conflict_speed_threshold_mps: float = 12.0,
    conflict_context_factor: float = 0.25,
    vertical_localization_policy: str = "fixed",
    cma_fusion_mode: str = "off",
    cma_proxy_dir: Path | None = None,
    cma_proxy_npz: Path | None = None,
    cma_background_weight: float = 0.10,
    cma_background_weight_mode: str = "fixed",
    cma_confidence_source: str = "dense",
    cma_confidence_cap: float = 0.35,
    cma_time_confidence: float = 0.70,
    cma_space_confidence: float = 0.70,
    cma_pseudo_source: str = "reanalysis",
    cma_qc_gating: str = "off",
) -> dict[str, Any]:
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
    _ = np.asarray(npz[C2_CLOUD_2D], dtype=np.float32)

    train_wind, holdout_wind = _split_holdout(wind_records, holdout_fraction, holdout_count)
    observations, confidence_diagnostics = _build_wind_observations(
        train_wind,
        context_wind_records,
        confidence_mode,
        qc_calibration=qc_calibration or DEFAULT_QC_CALIBRATION,
        current_weight_boost=current_weight_boost,
        context_weight_scale=context_weight_scale,
        context_time_conf_power=context_time_conf_power,
    )
    localization_policy = str(localization_policy)
    if localization_policy not in LOCALIZATION_POLICIES:
        raise ValueError(f"Unsupported localization_policy={localization_policy}; choose {sorted(LOCALIZATION_POLICIES)}")
    adaptive_diagnostics: dict[str, Any] = {
        "localization_policy": localization_policy,
        "localization_candidate_grid": str(localization_candidate_grid),
        "adaptive_selected_radius_xy": int(localization_radius_xy),
        "adaptive_selected_sigma_xy": float(localization_sigma_xy),
        "adaptive_selected_radius_z": int(localization_radius_z),
        "adaptive_selected_sigma_z": float(localization_sigma_z),
        "adaptive_score": 0.0,
        "adaptive_reasons": "fixed",
        "adaptive_no_holdout_inputs_used": True,
    }
    if localization_policy in {
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
            qc_calibration=qc_calibration or DEFAULT_QC_CALIBRATION,
            policy=localization_policy,
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
        qc_calibration=qc_calibration or DEFAULT_QC_CALIBRATION,
    )
    vertical_localization_diag = dict(acc.get("vertical_localization_scalar_diagnostics", {}))
    srha_horizontal_diag = dict(acc.get("srha_horizontal_scalar_diagnostics", {}))
    time_str = str(stage2_row["time_str"])
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
        qc_calibration=qc_calibration or DEFAULT_QC_CALIBRATION,
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
                qc_calibration=qc_calibration or DEFAULT_QC_CALIBRATION,
                time_confidence=float(cma_time_confidence),
                space_confidence=float(cma_space_confidence),
            )
        )
    leakage = _leakage_report(
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
        iterations=refine_iters,
        pinn_smoothness_weight=pinn_smoothness_weight,
        pinn_divergence_weight=pinn_divergence_weight,
        diffusion_weight=diffusion_weight,
        low_conf_fill_weight=low_conf_fill_weight,
        source_preserve=source_preserve,
        physics_constraint_mode=physics_constraint_mode,
        observation_anchor_weight=observation_anchor_weight,
        speed_limit_mps=speed_limit_mps,
        vertical_risk_mode=vertical_risk_mode,
        vertical_gradient_preserve_weight=vertical_gradient_preserve_weight,
        vertical_context_mismatch_damping=vertical_context_mismatch_damping,
    )
    recon = _finalize_effective_reconstruction(recon)
    point_rows = _point_eval_rows(holdout_wind, recon["recon_u"], recon["recon_v"], recon["recon_conf"], observations, acc)
    metrics = _metric_summary(point_rows)
    extent = _reconstruction_extent_stats(recon, pre_refine_voxels)
    field_diag = _field_proxy_diagnostics(recon)
    role_conflict_diag = _role_conflict_diagnostics(acc)
    result = {
        "time_str": str(stage2_row["time_str"]),
        "kernel": localization_kernel,
        "confidence_mode": confidence_mode,
        "physics_constraint_mode": physics_constraint_mode,
        "localization_policy": localization_policy,
        "localization_candidate_grid": str(localization_candidate_grid),
        "adaptive_selected_radius_xy": int(adaptive_diagnostics.get("adaptive_selected_radius_xy", localization_radius_xy)),
        "adaptive_selected_sigma_xy": float(adaptive_diagnostics.get("adaptive_selected_sigma_xy", localization_sigma_xy)),
        "adaptive_selected_radius_z": int(adaptive_diagnostics.get("adaptive_selected_radius_z", localization_radius_z)),
        "adaptive_selected_sigma_z": float(adaptive_diagnostics.get("adaptive_selected_sigma_z", localization_sigma_z)),
        "adaptive_score": float(adaptive_diagnostics.get("adaptive_score", 0.0)),
        "adaptive_reasons": str(adaptive_diagnostics.get("adaptive_reasons", "")),
        "adaptive_current_support": int(adaptive_diagnostics.get("adaptive_current_support", len(train_wind))),
        "adaptive_context_support": int(adaptive_diagnostics.get("adaptive_context_support", len(context_wind_records))),
        "adaptive_context_time_conf_mean": float(adaptive_diagnostics.get("adaptive_context_time_conf_mean", 0.0)),
        "adaptive_obs_error_weight_mean": float(adaptive_diagnostics.get("adaptive_obs_error_weight_mean", 0.0)),
        "adaptive_role_gap_mps": float(adaptive_diagnostics.get("adaptive_role_gap_mps", 0.0)),
        "adaptive_no_holdout_inputs_used": bool(adaptive_diagnostics.get("adaptive_no_holdout_inputs_used", True)),
        "localization_radius_xy": int(localization_radius_xy),
        "localization_sigma_xy": float(localization_sigma_xy),
        "localization_radius_z": int(localization_radius_z),
        "localization_sigma_z": float(localization_sigma_z),
        "wind_records_total": int(len(wind_records)),
        "holdout_wind_records": int(len(holdout_wind)),
        "fusion_current_wind_records": int(len(train_wind)),
        "context_wind_records": int(len(context_wind_records)),
        "trajectory_records": int(len(loc_records)),
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
        "field_smoothness_proxy": float(field_diag["field_smoothness_proxy"]),
        "field_horizontal_divergence_proxy": float(field_diag["field_horizontal_divergence_proxy"]),
        "field_vertical_shear_proxy": float(field_diag["field_vertical_shear_proxy"]),
        "field_vertical_jump_mean_mps": float(field_diag["field_vertical_jump_mean_mps"]),
        "field_vertical_jump_p95_mps": float(field_diag["field_vertical_jump_p95_mps"]),
        "field_vertical_jump_p99_mps": float(field_diag["field_vertical_jump_p99_mps"]),
        "strong_wind_voxels": int(field_diag["strong_wind_voxels"]),
        "rapid_vertical_change_voxels": int(field_diag["rapid_vertical_change_voxels"]),
        "strong_rapid_vertical_voxels": int(field_diag["strong_rapid_vertical_voxels"]),
        "strong_layer_vertical_jump_mean_mps": float(field_diag["strong_layer_vertical_jump_mean_mps"]),
        "vertical_oversmoothing_candidate_voxels": int(field_diag["vertical_oversmoothing_candidate_voxels"]),
        "vertical_oversmoothing_candidate_fraction": float(field_diag["vertical_oversmoothing_candidate_fraction"]),
        "vertical_context_mismatch_candidate_voxels": int(field_diag["vertical_context_mismatch_candidate_voxels"]),
        "vertical_context_mismatch_candidate_fraction": float(field_diag["vertical_context_mismatch_candidate_fraction"]),
        "strong_vertical_isolated_voxels": int(field_diag["strong_vertical_isolated_voxels"]),
        "strong_vertical_isolated_fraction": float(field_diag["strong_vertical_isolated_fraction"]),
        "speed_plausibility_violation_voxels": int(field_diag["speed_plausibility_violation_voxels"]),
        "density_conf_factor_mean": confidence_diagnostics["density_conf_factor_stats"]["mean"],
        "speed_qc_conf_mean": confidence_diagnostics["speed_qc_conf_stats"]["mean"],
        "local_consistency_conf_mean": confidence_diagnostics["local_consistency_conf_stats"]["mean"],
        "obs_error_sigma_vector_mps_mean": confidence_diagnostics["obs_error_sigma_vector_mps_stats"]["mean"],
        "obs_error_weight_factor_mean": confidence_diagnostics["obs_error_weight_factor_stats"]["mean"],
        "diffusion_fill_new_voxels": int(refine_metrics["diffusion_fill_new_voxels"]),
        "observation_anchor_weight": float(observation_anchor_weight),
        "speed_limit_mps": float(speed_limit_mps),
        "vertical_risk_mode": str(vertical_risk_mode),
        "vertical_localization_policy": str(vertical_localization_policy),
        "vertical_gradient_preserve_weight": float(vertical_gradient_preserve_weight),
        "vertical_context_mismatch_damping": float(vertical_context_mismatch_damping),
        "vertical_localization_sigma_factor_mean": (
            vertical_localization_diag.get("vertical_localization_sigma_factor_stats", {}) or {}
        ).get("mean"),
        "vertical_localization_sigma_factor_min": (
            vertical_localization_diag.get("vertical_localization_sigma_factor_stats", {}) or {}
        ).get("min"),
        "vertical_localization_sigma_factor_max": (
            vertical_localization_diag.get("vertical_localization_sigma_factor_stats", {}) or {}
        ).get("max"),
        "vertical_localization_reason_counts": str(vertical_localization_diag.get("vertical_localization_reason_counts", "")),
        "srha_horizontal_sigma_factor_mean": (
            srha_horizontal_diag.get("srha_horizontal_sigma_factor_stats", {}) or {}
        ).get("mean"),
        "srha_horizontal_sigma_factor_min": (
            srha_horizontal_diag.get("srha_horizontal_sigma_factor_stats", {}) or {}
        ).get("min"),
        "srha_horizontal_sigma_factor_max": (
            srha_horizontal_diag.get("srha_horizontal_sigma_factor_stats", {}) or {}
        ).get("max"),
        "srha_horizontal_reason_counts": str(srha_horizontal_diag.get("srha_horizontal_reason_counts", "")),
        "srha_high_altitude_gate_count": int(srha_horizontal_diag.get("high_altitude_gate_count", 0)),
        "srha_high_speed_gate_count": int(srha_horizontal_diag.get("high_speed_gate_count", 0)),
        "srha_role_gap_gate_count": int(srha_horizontal_diag.get("role_gap_gate_count", 0)),
        "srha_stale_context_gate_count": int(srha_horizontal_diag.get("stale_context_gate_count", 0)),
        "srha_sparse_fresh_widen_gate_count": int(srha_horizontal_diag.get("sparse_fresh_widen_gate_count", 0)),
        "srha_dense_current_gate_count": int(srha_horizontal_diag.get("dense_current_gate_count", 0)),
        "vertical_risk_refine_enabled": float(refine_metrics.get("vertical_risk_refine_enabled", 0.0)),
        "vertical_risk_candidate_voxels_last": int(refine_metrics.get("vertical_risk_candidate_voxels_last", 0.0)),
        "vertical_oversmooth_preserve_voxels_last": int(refine_metrics.get("vertical_oversmooth_preserve_voxels_last", 0.0)),
        "vertical_context_mismatch_damped_voxels_last": int(refine_metrics.get("vertical_context_mismatch_damped_voxels_last", 0.0)),
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
        "cma_temporal_conf_mean": float(cma_fusion_diagnostics.get("cma_temporal_conf_mean", 0.0)),
        "cma_temporal_change_speed_mean_mps": float(cma_fusion_diagnostics.get("cma_temporal_change_speed_mean_mps", 0.0)),
        "cma_rapid_change_fraction": float(cma_fusion_diagnostics.get("cma_rapid_change_fraction", 0.0)),
        "cma_effective_conf_mean": float(cma_fusion_diagnostics.get("cma_effective_conf_mean", 0.0)),
        "cma_background_active_voxels": int(cma_fusion_diagnostics.get("cma_background_active_voxels", 0)),
        "cma_background_gate_mean": float(cma_fusion_diagnostics.get("cma_background_gate_mean", 0.0)),
        "cma_background_gate_active_fraction": float(cma_fusion_diagnostics.get("cma_background_gate_active_fraction", 0.0)),
        "cma_background_no_current_gate_voxels": int(cma_fusion_diagnostics.get("cma_background_no_current_gate_voxels", 0)),
        "cma_background_localized_support_gate_voxels": int(
            cma_fusion_diagnostics.get("cma_background_localized_support_gate_voxels", 0)
        ),
        "cma_background_localized_support_gate_fraction": float(
            cma_fusion_diagnostics.get("cma_background_localized_support_gate_fraction", 0.0)
        ),
        "cma_background_sparse_current_gate_fraction": float(cma_fusion_diagnostics.get("cma_background_sparse_current_gate_fraction", 0.0)),
        "cma_strict_temporal_gate_active_fraction": float(cma_fusion_diagnostics.get("cma_strict_temporal_gate_active_fraction", 0.0)),
        "cma_used_as_background_not_truth": bool(leakage.get("cma_used_as_background_not_truth", False)),
        "role_conflict_voxels": int(role_conflict_diag["role_conflict_voxels"]),
        "role_overlap_voxels": int(role_conflict_diag["role_overlap_voxels"]),
        "role_conflict_fraction_of_overlap": float(role_conflict_diag["role_conflict_fraction_of_overlap"]),
        "role_conflict_context_weight_sum": float(role_conflict_diag["role_conflict_context_weight_sum"]),
        "role_conflict_context_weight_removed_sum": float(role_conflict_diag["role_conflict_context_weight_removed_sum"]),
        "role_conflict_component_gap_mean_mps": float(role_conflict_diag["role_conflict_component_gap_mean_mps"]),
        "role_conflict_component_gap_max_mps": float(role_conflict_diag["role_conflict_component_gap_max_mps"]),
        "role_conflict_threshold_mean_mps": float(role_conflict_diag["role_conflict_threshold_mean_mps"]),
        "role_conflict_threshold_min_mps": float(role_conflict_diag.get("role_conflict_threshold_min_mps", 0.0)),
        "role_conflict_threshold_max_mps": float(role_conflict_diag.get("role_conflict_threshold_max_mps", 0.0)),
        "role_conflict_context_factor_mean": float(role_conflict_diag["role_conflict_context_factor_mean"]),
        "role_conflict_context_factor_min": float(role_conflict_diag.get("role_conflict_context_factor_min", 0.0)),
        "role_conflict_context_factor_max": float(role_conflict_diag.get("role_conflict_context_factor_max", 0.0)),
        "role_conflict_current_density_mean": float(role_conflict_diag["role_conflict_current_density_mean"]),
        "role_conflict_context_time_conf_mean": float(role_conflict_diag["role_conflict_context_time_conf_mean"]),
        "role_conflict_altitude_mean_m": float(role_conflict_diag["role_conflict_altitude_mean_m"]),
        "qc_calibration_path": str((qc_calibration or {}).get("calibration_path", "")),
        "strict_holdout_no_leakage": bool(leakage["strict_holdout_no_leakage"]),
        "motion_used_as_wind": bool(leakage["motion_records_used_as_wind"]),
    }
    result["_point_departure_rows"] = [
        {
            "time_str": str(stage2_row["time_str"]),
            "kernel": localization_kernel,
            "confidence_mode": confidence_mode,
            "physics_constraint_mode": physics_constraint_mode,
            "localization_policy": localization_policy,
            "localization_radius_xy": int(localization_radius_xy),
            "localization_sigma_xy": float(localization_sigma_xy),
            "localization_radius_z": int(localization_radius_z),
            "localization_sigma_z": float(localization_sigma_z),
            "strict_holdout_no_leakage": bool(leakage["strict_holdout_no_leakage"]),
            "motion_used_as_wind": bool(leakage["motion_records_used_as_wind"]),
            **point_row,
        }
        for point_row in point_rows
    ]
    return result


def _split_point_departures(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    point_rows: list[dict[str, Any]] = []
    for row in rows:
        raw = row.pop("_point_departure_rows", [])
        if isinstance(raw, list):
            point_rows.extend(dict(item) for item in raw if isinstance(item, dict))
    return point_rows


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


def _write_md(path: Path, rows: list[dict[str, Any]]) -> None:
    lines = [
        "# Stage4 Localization Sensitivity",
        "",
        "This table is metrics-only. Per-parameter 3D NPZ outputs are intentionally not saved.",
        "",
        "| frame | kernel | confidence | physics | policy | rxy | sxy | rz | sz | holdout | RMSE | MAE | effective voxels | low-conf fill | leakage |",
        "| --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in rows:
        holdout_count = _to_int(row.get("holdout_wind_records"))
        rmse_cell = _fmt_metric(row.get("rmse_vector")) if holdout_count > 0 else ""
        mae_cell = _fmt_metric(row.get("mae_vector")) if holdout_count > 0 else ""
        lines.append(
            f"| `{row['time_str']}` | `{row['kernel']}` | `{row.get('confidence_mode', '')}` | "
            f"`{row.get('physics_constraint_mode', 'proxy')}` | `{row.get('localization_policy', 'fixed')}` | "
            f"{row['localization_radius_xy']} | "
            f"{float(row['localization_sigma_xy']):.2f} | {row['localization_radius_z']} | "
            f"{float(row['localization_sigma_z']):.2f} | {holdout_count} | "
            f"{rmse_cell} | {mae_cell} | "
            f"{row['effective_reconstructed_voxels']} | {row['low_conf_fill_voxels']} | "
            f"`{row['strict_holdout_no_leakage']}` |"
        )
    lines.extend(
        [
            "",
            "References:",
            "",
            "- DART Gaspari-Cohn localization: https://docs.dart.ucar.edu/en/latest/assimilation_code/modules/assimilation/cov_cutoff_mod.html",
            "- ECMWF ERA5/IFS finite assimilation windows: https://confluence.ecmwf.int/display/CKB/ERA5%3A%2Bdata%2Bdocumentation",
            "- PyDDA/3DVAR wind retrieval constraints: https://openresearchsoftware.metajnl.com/articles/264",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _to_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if np.isfinite(number) else None


def _to_int(value: Any) -> int:
    number = _to_float(value)
    return int(number) if number is not None else 0


def _has_holdout(row: dict[str, Any]) -> bool:
    return _to_int(row.get("holdout_wind_records")) > 0


def _mean_numeric(rows: list[dict[str, Any]], key: str) -> float | None:
    vals = [_to_float(row.get(key)) for row in rows]
    clean = [val for val in vals if val is not None]
    return float(np.mean(clean)) if clean else None


def _sum_numeric(rows: list[dict[str, Any]], key: str) -> float:
    return float(sum(val for val in (_to_float(row.get(key)) for row in rows) if val is not None))


def _fmt_metric(value: Any) -> str:
    number = _to_float(value)
    return "" if number is None else f"{number:.6f}"


def _aggregate_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    for row in rows:
        key = (
            row.get("kernel"),
            row.get("confidence_mode"),
            row.get("physics_constraint_mode"),
            row.get("localization_policy", "fixed"),
            row.get("localization_candidate_grid", ""),
            row.get("localization_radius_xy"),
            row.get("localization_sigma_xy"),
            row.get("localization_radius_z"),
            row.get("localization_sigma_z"),
            row.get("current_weight_boost"),
            row.get("context_weight_scale"),
            row.get("context_time_conf_power"),
            row.get("role_conflict_mode"),
            row.get("conflict_speed_threshold_mps"),
            row.get("conflict_context_factor"),
            row.get("vertical_risk_mode"),
            row.get("vertical_localization_policy", "fixed"),
            row.get("vertical_gradient_preserve_weight"),
            row.get("vertical_context_mismatch_damping"),
        )
        groups.setdefault(key, []).append(row)
    out: list[dict[str, Any]] = []
    for key, group_rows in groups.items():
        official_rows = [row for row in group_rows if _has_holdout(row)]
        out.append(
            {
                "kernel": key[0],
                "confidence_mode": key[1],
                "physics_constraint_mode": key[2],
                "localization_policy": key[3],
                "localization_candidate_grid": key[4],
                "localization_radius_xy": key[5],
                "localization_sigma_xy": key[6],
                "localization_radius_z": key[7],
                "localization_sigma_z": key[8],
                "current_weight_boost": key[9],
                "context_weight_scale": key[10],
                "context_time_conf_power": key[11],
                "role_conflict_mode": key[12],
                "conflict_speed_threshold_mps": key[13],
                "conflict_context_factor": key[14],
                "vertical_risk_mode": key[15],
                "vertical_localization_policy": key[16],
                "vertical_gradient_preserve_weight": key[17],
                "vertical_context_mismatch_damping": key[18],
                "frames": len(group_rows),
                "official_holdout_frames": len(official_rows),
                "no_holdout_frames": len(group_rows) - len(official_rows),
                "holdout_points": int(_sum_numeric(group_rows, "holdout_wind_records")),
                "mean_rmse_vector": _mean_numeric(official_rows, "rmse_vector"),
                "mean_mae_vector": _mean_numeric(official_rows, "mae_vector"),
                "mean_bias_u": _mean_numeric(official_rows, "bias_u"),
                "mean_bias_v": _mean_numeric(official_rows, "bias_v"),
                "zero_filled_all_frame_mean_rmse_vector": _mean_numeric(group_rows, "rmse_vector"),
                "zero_filled_all_frame_mean_mae_vector": _mean_numeric(group_rows, "mae_vector"),
                "mean_effective_reconstructed_voxels": _mean_numeric(group_rows, "effective_reconstructed_voxels"),
                "mean_low_conf_fill_voxels": _mean_numeric(group_rows, "low_conf_fill_voxels"),
                "mean_obs_error_sigma_vector_mps": _mean_numeric(group_rows, "obs_error_sigma_vector_mps_mean"),
                "mean_obs_error_weight_factor": _mean_numeric(group_rows, "obs_error_weight_factor_mean"),
                "mean_adaptive_selected_radius_xy": _mean_numeric(group_rows, "adaptive_selected_radius_xy"),
                "mean_adaptive_score": _mean_numeric(group_rows, "adaptive_score"),
                "mean_role_conflict_voxels": _mean_numeric(group_rows, "role_conflict_voxels"),
                "mean_role_conflict_threshold_mps": _mean_numeric(group_rows, "role_conflict_threshold_mean_mps"),
                "mean_role_conflict_context_factor": _mean_numeric(group_rows, "role_conflict_context_factor_mean"),
                "mean_vertical_context_mismatch_candidate_voxels": _mean_numeric(group_rows, "vertical_context_mismatch_candidate_voxels"),
                "mean_vertical_oversmoothing_candidate_voxels": _mean_numeric(group_rows, "vertical_oversmoothing_candidate_voxels"),
                "mean_strong_vertical_isolated_voxels": _mean_numeric(group_rows, "strong_vertical_isolated_voxels"),
                "mean_vertical_localization_sigma_factor": _mean_numeric(group_rows, "vertical_localization_sigma_factor_mean"),
                "mean_vertical_risk_candidate_voxels_last": _mean_numeric(group_rows, "vertical_risk_candidate_voxels_last"),
                "mean_vertical_oversmooth_preserve_voxels_last": _mean_numeric(group_rows, "vertical_oversmooth_preserve_voxels_last"),
                "mean_vertical_context_mismatch_damped_voxels_last": _mean_numeric(group_rows, "vertical_context_mismatch_damped_voxels_last"),
                "all_strict_holdout_no_leakage": bool(all(_as_bool(r["strict_holdout_no_leakage"]) for r in group_rows)),
                "any_motion_used_as_wind": bool(any(_as_bool(r["motion_used_as_wind"]) for r in group_rows)),
            }
        )
    return sorted(out, key=lambda row: _to_float(row.get("mean_rmse_vector")) if _to_float(row.get("mean_rmse_vector")) is not None else float("inf"))


def _write_aggregate_md(path: Path, rows: list[dict[str, Any]]) -> None:
    lines = [
        "# Stage4 Sensitivity Aggregate",
        "",
        "Metrics-only aggregate. No per-parameter 3D NPZ fields are saved.",
        "",
        "Official error metrics below use holdout frames only. No-holdout frames are unverified reconstruction coverage diagnostics and are not zero-error validation frames.",
        "",
        "| rank | kernel | confidence | physics | role conflict | vertical risk | vertical loc | rxy/sxy/rz/sz | frames | eval frames | no holdout | holdout points | official frame RMSE | official frame MAE | zero-filled all-frame RMSE | mean fill | mean effective | strict no leakage | motion used |",
        "| ---: | --- | --- | --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    for idx, row in enumerate(rows, start=1):
        lines.append(
            f"| {idx} | `{row['kernel']}` | `{row['confidence_mode']}` | `{row['physics_constraint_mode']}` | "
            f"`{row['role_conflict_mode']}` | `{row.get('vertical_risk_mode', 'off')}` | "
            f"`{row.get('vertical_localization_policy', 'fixed')}` | "
            f"{row['localization_radius_xy']}/{row['localization_sigma_xy']}/"
            f"{row['localization_radius_z']}/{row['localization_sigma_z']} | "
            f"{row['frames']} | {row.get('official_holdout_frames', 0)} | {row.get('no_holdout_frames', 0)} | "
            f"{row.get('holdout_points', 0)} | {_fmt_metric(row.get('mean_rmse_vector'))} | "
            f"{_fmt_metric(row.get('mean_mae_vector'))} | {_fmt_metric(row.get('zero_filled_all_frame_mean_rmse_vector'))} | "
            f"{(_to_float(row.get('mean_low_conf_fill_voxels')) or 0.0):.1f} | "
            f"{(_to_float(row.get('mean_effective_reconstructed_voxels')) or 0.0):.1f} | "
            f"`{row['all_strict_holdout_no_leakage']}` | `{row['any_motion_used_as_wind']}` |"
        )
    lines.extend(
        [
            "",
            "## Adaptive/Vertical Diagnostics",
            "",
            "| rank | mean conflict voxels | mean adaptive threshold | mean context factor | mean vertical loc sigma factor | mean vertical mismatch | mean oversmooth | mean isolated strong | refine risk | refine oversmooth preserve | refine mismatch damp |",
            "| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for idx, row in enumerate(rows, start=1):
        lines.append(
            f"| {idx} | {row.get('mean_role_conflict_voxels', 0.0):.1f} | "
            f"{row.get('mean_role_conflict_threshold_mps', 0.0):.3f} | "
            f"{row.get('mean_role_conflict_context_factor', 0.0):.3f} | "
            f"{row.get('mean_vertical_localization_sigma_factor', 0.0):.3f} | "
            f"{row.get('mean_vertical_context_mismatch_candidate_voxels', 0.0):.1f} | "
            f"{row.get('mean_vertical_oversmoothing_candidate_voxels', 0.0):.1f} | "
            f"{row.get('mean_strong_vertical_isolated_voxels', 0.0):.1f} | "
            f"{row.get('mean_vertical_risk_candidate_voxels_last', 0.0):.1f} | "
            f"{row.get('mean_vertical_oversmooth_preserve_voxels_last', 0.0):.1f} | "
            f"{row.get('mean_vertical_context_mismatch_damped_voxels_last', 0.0):.1f} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


POINT_CONFIG_COLUMNS = [
    "time_str",
    "kernel",
    "confidence_mode",
    "physics_constraint_mode",
    "localization_policy",
    "localization_radius_xy",
    "localization_sigma_xy",
    "localization_radius_z",
    "localization_sigma_z",
]


def _point_frame_key(row: dict[str, Any]) -> tuple[str, ...]:
    return tuple(str(row.get(key, "")) for key in POINT_CONFIG_COLUMNS)


def _annotate_point_departures(point_rows: list[dict[str, Any]], frame_rows: list[dict[str, Any]]) -> None:
    frame_lookup = {
        _point_frame_key(row): {
            "holdout_wind_records": _to_int(row.get("holdout_wind_records")),
            "frame_rmse_vector": row.get("rmse_vector"),
            "frame_mae_vector": row.get("mae_vector"),
            "adaptive_reasons": row.get("adaptive_reasons", ""),
            "adaptive_current_support": row.get("adaptive_current_support", ""),
            "adaptive_context_support": row.get("adaptive_context_support", ""),
        }
        for row in frame_rows
    }
    for row in point_rows:
        context = frame_lookup.get(_point_frame_key(row), {})
        row.setdefault("frame_holdout_wind_records", context.get("holdout_wind_records", ""))
        row.setdefault("frame_rmse_vector", context.get("frame_rmse_vector", ""))
        row.setdefault("frame_mae_vector", context.get("frame_mae_vector", ""))
        row.setdefault("adaptive_reasons", context.get("adaptive_reasons", ""))
        row.setdefault("adaptive_current_support", context.get("adaptive_current_support", ""))
        row.setdefault("adaptive_context_support", context.get("adaptive_context_support", ""))


def _point_reason(row: dict[str, Any], reason: str) -> bool:
    reasons = str(row.get("qc_review_reasons", ""))
    return reason in {token.strip() for token in reasons.split(";") if token.strip()}


def _point_bool(row: dict[str, Any], key: str) -> bool:
    return _as_bool(row.get(key))


def _point_strata() -> list[tuple[str, str, Any]]:
    return [
        ("all_holdout_points", "official_baseline", lambda row: True),
        ("single_holdout_frame", "support_tail", lambda row: _to_int(row.get("frame_holdout_wind_records")) == 1),
        ("multi_holdout_ge2_frame", "support_reference", lambda row: _to_int(row.get("frame_holdout_wind_records")) >= 2),
        ("multi_holdout_ge3_frame", "support_reference", lambda row: _to_int(row.get("frame_holdout_wind_records")) >= 3),
        ("alt_9_12km", "high_alt_tail", lambda row: 9000.0 <= (_to_float(row.get("alt_m")) or -1.0) < 12000.0),
        ("alt_12km_plus", "high_alt_tail", lambda row: (_to_float(row.get("alt_m")) or -1.0) >= 12000.0),
        (
            "alt_12km_plus_single_holdout",
            "combined_tail",
            lambda row: (_to_float(row.get("alt_m")) or -1.0) >= 12000.0 and _to_int(row.get("frame_holdout_wind_records")) == 1,
        ),
        ("context_only_nearest_support", "context_tail", lambda row: _point_reason(row, "context_only_nearest_support")),
        (
            "alt_12km_plus_context_only",
            "combined_tail",
            lambda row: (_to_float(row.get("alt_m")) or -1.0) >= 12000.0 and _point_reason(row, "context_only_nearest_support"),
        ),
        (
            "single_holdout_context_only",
            "combined_tail",
            lambda row: _to_int(row.get("frame_holdout_wind_records")) == 1 and _point_reason(row, "context_only_nearest_support"),
        ),
        ("nearest_context_wind", "support_tail", lambda row: str(row.get("nearest_train_source_role", "")) == "context_wind"),
        ("nearest_current_wind_train", "support_reference", lambda row: str(row.get("nearest_train_source_role", "")) == "current_wind_train"),
        ("nearest_distance_gt4vox", "remote_support_tail", lambda row: (_to_float(row.get("nearest_train_distance_vox")) or 0.0) > 4.0),
        ("role_gap_ge30mps", "role_conflict_tail", lambda row: (_to_float(row.get("nearest_role_gap_mps")) or 0.0) >= 30.0),
        ("role_conflict_at_point", "role_conflict_tail", lambda row: _point_bool(row, "role_conflict_at_point")),
        ("qc_review_flag", "qc_tail", lambda row: _point_bool(row, "qc_review_flag")),
        ("no_qc_review_flag", "clean_reference", lambda row: not _point_bool(row, "qc_review_flag")),
        ("high_vector_error_ge30mps", "error_tail", lambda row: (_to_float(row.get("vector_error")) or 0.0) >= 30.0),
        ("extreme_truth_speed_ge120mps", "qc_tail", lambda row: _point_reason(row, "extreme_truth_speed_ge_120mps")),
        ("extreme_prediction_speed_ge120mps", "qc_tail", lambda row: _point_reason(row, "extreme_prediction_speed_ge_120mps")),
    ]


def _percentile(values: list[float], q: float) -> float | None:
    clean = [val for val in values if np.isfinite(val)]
    return float(np.percentile(clean, q)) if clean else None


def _tail_metric_rows(point_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    all_errors = [_to_float(row.get("vector_error")) for row in point_rows]
    all_sse = sum(float(err) ** 2 for err in all_errors if err is not None)
    out: list[dict[str, Any]] = []
    for stratum, category, predicate in _point_strata():
        selected = [row for row in point_rows if predicate(row)]
        errors = [err for err in (_to_float(row.get("vector_error")) for row in selected) if err is not None]
        sse = sum(err**2 for err in errors)
        frames = {_point_frame_key(row) for row in selected}
        out.append(
            {
                "stratum": stratum,
                "category": category,
                "points": len(selected),
                "frames": len(frames),
                "point_weighted_rmse_vector": float(np.sqrt(np.mean(np.asarray(errors, dtype=np.float64) ** 2))) if errors else None,
                "point_weighted_mae_vector": float(np.mean(errors)) if errors else None,
                "p50_vector_error": _percentile(errors, 50),
                "p90_vector_error": _percentile(errors, 90),
                "p95_vector_error": _percentile(errors, 95),
                "p99_vector_error": _percentile(errors, 99),
                "max_vector_error": max(errors) if errors else None,
                "sse_share_of_all_points": (sse / all_sse) if all_sse > 0.0 else None,
                "mean_alt_m": _mean_numeric(selected, "alt_m"),
                "mean_truth_speed_mps": _mean_numeric(selected, "gt_speed"),
                "mean_prediction_speed_mps": _mean_numeric(selected, "pred_speed"),
                "mean_nearest_train_distance_vox": _mean_numeric(selected, "nearest_train_distance_vox"),
                "mean_nearest_role_gap_mps": _mean_numeric(selected, "nearest_role_gap_mps"),
            }
        )
    return out


def _write_tail_diagnostics(out_dir: Path, point_rows: list[dict[str, Any]]) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    aggregate = _tail_metric_rows(point_rows)
    aggregate_csv = out_dir / "stage4_tail_diagnostics.csv"
    aggregate_md = out_dir / "stage4_tail_diagnostics.md"
    run_json = out_dir / "stage4_tail_diagnostics_run.json"
    _write_csv(aggregate_csv, aggregate)
    lines = [
        "# Stage4 Tail Diagnostics",
        "",
        "Tail strata are diagnostic only. They do not remove aircraft holdout truth from official RMSE/MAE.",
        "",
        "| stratum | category | points | frames | RMSE | MAE | P95 | P99 | max | SSE share | mean alt | mean nearest dist | mean role gap |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in aggregate:
        lines.append(
            f"| `{row['stratum']}` | `{row['category']}` | {row['points']} | {row['frames']} | "
            f"{_fmt_metric(row.get('point_weighted_rmse_vector'))} | {_fmt_metric(row.get('point_weighted_mae_vector'))} | "
            f"{_fmt_metric(row.get('p95_vector_error'))} | {_fmt_metric(row.get('p99_vector_error'))} | "
            f"{_fmt_metric(row.get('max_vector_error'))} | {_fmt_metric(row.get('sse_share_of_all_points'))} | "
            f"{_fmt_metric(row.get('mean_alt_m'))} | {_fmt_metric(row.get('mean_nearest_train_distance_vox'))} | "
            f"{_fmt_metric(row.get('mean_nearest_role_gap_mps'))} |"
        )
    aggregate_md.write_text("\n".join(lines) + "\n", encoding="utf-8")
    run_meta = {
        "input_point_rows": len(point_rows),
        "aggregate_csv": str(aggregate_csv),
        "aggregate_md": str(aggregate_md),
        "strata": [name for name, _category, _predicate in _point_strata()],
    }
    run_json.write_text(json.dumps(run_meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "tail_diagnostics_csv": str(aggregate_csv),
        "tail_diagnostics_md": str(aggregate_md),
        "tail_diagnostics_run_json": str(run_json),
    }


def _read_csv_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open("r", encoding="utf-8", newline="") as f:
        return [dict(row) for row in csv.DictReader(f)]


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "y"}:
        return True
    if text in {"false", "0", "no", "n", ""}:
        return False
    return bool(value)


def _run_parent_shards(
    args: argparse.Namespace,
    selected: list[dict[str, Any]],
    kernels: list[str],
    grid: list[dict[str, float | int]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    workers = max(1, int(args.num_workers))
    shard_dir = args.out_dir / "shards"
    shard_dir.mkdir(parents=True, exist_ok=True)
    shards = [[] for _ in range(workers)]
    for idx, row in enumerate(selected):
        shards[idx % workers].append(row)

    env_base = os.environ.copy()
    env_base.setdefault("PYTHONUNBUFFERED", "1")
    procs: list[tuple[subprocess.Popen[str], Path, Path, Path, int]] = []
    progress_files: list[tuple[Path, int]] = []
    script_path = Path(__file__).resolve()
    total_per_frame = len(kernels) * len(grid)

    for shard_idx, rows in enumerate(shards):
        if not rows:
            continue
        shard_out = shard_dir / f"stage4_sensitivity_shard_{shard_idx:02d}"
        frame_file = shard_dir / f"stage4_sensitivity_shard_{shard_idx:02d}_frames.txt"
        log_file = shard_dir / f"stage4_sensitivity_shard_{shard_idx:02d}.log"
        progress_file = shard_dir / f"stage4_sensitivity_shard_{shard_idx:02d}_progress.json"
        _write_frame_times(frame_file, rows)
        shard_total = len(rows) * total_per_frame
        _write_progress(progress_file, completed=0, total=shard_total, shard_id=shard_idx, status="queued")

        cmd = [
            sys.executable,
            str(script_path),
            "--stage2-summary",
            str(args.stage2_summary),
            "--stage3-summary",
            str(args.stage3_summary),
            "--frame-times-file",
            str(frame_file),
            "--out-dir",
            str(shard_out),
            "--sample-count",
            "0",
            "--sample-seed",
            str(args.sample_seed),
            "--param-grid",
            str(args.param_grid),
            "--kernels",
            str(args.kernels),
            "--confidence-mode",
            str(args.confidence_mode),
            "--holdout-fraction",
            str(args.holdout_fraction),
            "--holdout-count",
            str(args.holdout_count),
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
            "--localization-policy",
            str(args.localization_policy),
            "--localization-candidate-grid",
            str(args.localization_candidate_grid),
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
            "--progress-interval-seconds",
            str(args.progress_interval_seconds),
            "--num-workers",
            "1",
            "--shard-id",
            str(shard_idx),
            "--progress-file",
            str(progress_file),
            "--progress-total",
            str(shard_total),
        ]
        if args.qc_calibration:
            cmd.extend(["--qc-calibration", str(args.qc_calibration)])
        if args.cma_proxy_npz:
            cmd.extend(["--cma-proxy-npz", str(args.cma_proxy_npz)])

        with log_file.open("w", encoding="utf-8") as log:
            proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT, text=True, env=env_base)
        procs.append((proc, shard_out / "stage4_localization_sensitivity.csv", log_file, progress_file, shard_total))
        progress_files.append((progress_file, shard_total))

    started = time.time()
    last_progress = 0.0
    _print_parent_progress(progress_files, started=started, workers=workers, force=True)
    while any(proc.poll() is None for proc, *_ in procs):
        now = time.time()
        if now - last_progress >= max(1.0, float(args.progress_interval_seconds)):
            _print_parent_progress(progress_files, started=started, workers=workers, force=True)
            last_progress = now
        time.sleep(1.0)
    _print_parent_progress(progress_files, started=started, workers=workers, force=True)

    rows: list[dict[str, Any]] = []
    point_rows: list[dict[str, Any]] = []
    for proc, csv_path, log_file, _progress_file, _shard_total in procs:
        rc = proc.wait()
        if rc != 0:
            raise RuntimeError(f"Stage4 sensitivity shard failed rc={rc}; see {log_file}")
        rows.extend(_read_csv_rows(csv_path))
        point_rows.extend(_read_csv_rows(csv_path.parent / "stage4_point_departures.csv"))
    return rows, point_rows


def main() -> None:
    parser = argparse.ArgumentParser(description="Stage4 localization sensitivity table.")
    parser.add_argument("--stage2-summary", type=Path, default=REGENERATED_STAGE2_OUTPUT_DIR / "stage2_multimodal_summary.json")
    parser.add_argument("--stage3-summary", type=Path, default=DEFAULT_EXPANDED_STAGE3_SUMMARY)
    parser.add_argument("--frame-times", default=DEFAULT_EXPANDED_FRAMES)
    parser.add_argument("--frame-times-file", type=Path)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_SENSITIVITY_DIR)
    parser.add_argument("--sample-count", type=int, default=0)
    parser.add_argument("--sample-seed", type=int, default=20260527)
    parser.add_argument("--param-grid", default=DEFAULT_PARAM_GRID)
    parser.add_argument("--kernels", default="gaussian,gaspari_cohn")
    parser.add_argument("--confidence-mode", choices=sorted(CONFIDENCE_MODES), default="diagnostic_only")
    parser.add_argument("--qc-calibration", type=Path)
    parser.add_argument("--holdout-fraction", type=float, default=0.125)
    parser.add_argument("--holdout-count", type=int, default=0)
    parser.add_argument("--refine-iters", type=int, default=4)
    parser.add_argument("--pinn-smoothness-weight", type=float, default=0.018)
    parser.add_argument("--pinn-divergence-weight", type=float, default=0.010)
    parser.add_argument("--diffusion-weight", type=float, default=0.22)
    parser.add_argument("--low-conf-fill-weight", type=float, default=0.72)
    parser.add_argument("--source-preserve", type=float, default=0.95)
    parser.add_argument("--physics-constraint-mode", choices=sorted(PHYSICS_CONSTRAINT_MODES), default="proxy")
    parser.add_argument("--observation-anchor-weight", type=float, default=0.10)
    parser.add_argument("--speed-limit-mps", type=float, default=120.0)
    parser.add_argument("--localization-policy", choices=sorted(LOCALIZATION_POLICIES), default="fixed")
    parser.add_argument("--localization-candidate-grid", default="6:3,8:4,10:5,12:6")
    parser.add_argument("--vertical-risk-mode", choices=sorted(VERTICAL_RISK_MODES), default="off")
    parser.add_argument("--vertical-localization-policy", choices=sorted(VERTICAL_LOCALIZATION_POLICIES), default="fixed")
    parser.add_argument("--vertical-gradient-preserve-weight", type=float, default=0.12)
    parser.add_argument("--vertical-context-mismatch-damping", type=float, default=0.35)
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
    parser.add_argument("--progress-interval-seconds", type=float, default=10.0)
    parser.add_argument("--num-workers", type=int, default=1)
    parser.add_argument("--shard-id", type=int, default=-1)
    parser.add_argument("--progress-file", type=Path)
    parser.add_argument("--progress-total", type=int, default=0)
    args = parser.parse_args()

    # Keep a Stage3 summary argument in the CLI so runs document which Ground
    # Center payload set they correspond to, even though metrics-only evaluation
    # reads the Stage2 npz records directly.
    if args.stage3_summary and not args.stage3_summary.exists():
        raise FileNotFoundError(f"Stage3 summary not found: {args.stage3_summary}")
    frame_times = _frame_times_from_args(str(args.frame_times), args.frame_times_file)
    stage2_rows = _sample_rows(_select_rows(_load_json(args.stage2_summary), frame_times), int(args.sample_count), int(args.sample_seed))
    kernels = [token.strip() for token in str(args.kernels).split(",") if token.strip()]
    unsupported = sorted(set(kernels) - LOCALIZATION_KERNELS)
    if unsupported:
        raise ValueError(f"Unsupported kernels: {unsupported}; choose {sorted(LOCALIZATION_KERNELS)}")
    grid = _parse_param_grid(args.param_grid)
    qc_calibration = _load_qc_calibration(args.qc_calibration)

    rows: list[dict[str, Any]] = []
    point_departure_rows: list[dict[str, Any]] = []
    total_tasks = len(stage2_rows) * len(kernels) * len(grid)
    if int(args.shard_id) < 0 and int(args.num_workers) > 1 and len(stage2_rows) > 1:
        rows, point_departure_rows = _run_parent_shards(args, stage2_rows, kernels, grid)
        total_tasks = len(rows)
    else:
        progress_total = int(args.progress_total) if int(args.progress_total) > 0 else total_tasks
        _write_progress(args.progress_file, completed=0, total=progress_total, shard_id=int(args.shard_id), status="running")
        started = time.time()
        last_progress = 0.0
        done = 0
        _print_progress(done, total_tasks, started=started, force=True)
        for stage2_row in stage2_rows:
            for kernel in kernels:
                for params in grid:
                    rows.append(
                        _evaluate_metrics_only(
                            stage2_row,
                            localization_kernel=kernel,
                            confidence_mode=str(args.confidence_mode),
                            holdout_fraction=float(args.holdout_fraction),
                            holdout_count=int(args.holdout_count),
                            localization_radius_xy=int(params["localization_radius_xy"]),
                            localization_radius_z=int(params["localization_radius_z"]),
                            localization_sigma_xy=float(params["localization_sigma_xy"]),
                            localization_sigma_z=float(params["localization_sigma_z"]),
                            refine_iters=int(args.refine_iters),
                            pinn_smoothness_weight=float(args.pinn_smoothness_weight),
                            pinn_divergence_weight=float(args.pinn_divergence_weight),
                            diffusion_weight=float(args.diffusion_weight),
                            low_conf_fill_weight=float(args.low_conf_fill_weight),
                            source_preserve=float(args.source_preserve),
                            physics_constraint_mode=str(args.physics_constraint_mode),
                            observation_anchor_weight=float(args.observation_anchor_weight),
                            speed_limit_mps=float(args.speed_limit_mps),
                            localization_policy=str(args.localization_policy),
                            localization_candidate_grid=str(args.localization_candidate_grid),
                            vertical_risk_mode=str(args.vertical_risk_mode),
                            vertical_localization_policy=str(args.vertical_localization_policy),
                            vertical_gradient_preserve_weight=float(args.vertical_gradient_preserve_weight),
                            vertical_context_mismatch_damping=float(args.vertical_context_mismatch_damping),
                            qc_calibration=qc_calibration,
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
                        )
                    )
                    done += 1
                    _write_progress(args.progress_file, completed=done, total=progress_total, shard_id=int(args.shard_id), status="running")
                    now = time.time()
                    if now - last_progress >= max(1.0, float(args.progress_interval_seconds)) or done == total_tasks:
                        _print_progress(done, total_tasks, started=started, force=True)
                        last_progress = now
        _write_progress(args.progress_file, completed=done, total=progress_total, shard_id=int(args.shard_id), status="done")
        point_departure_rows = _split_point_departures(rows)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    _annotate_point_departures(point_departure_rows, rows)
    csv_path = args.out_dir / "stage4_localization_sensitivity.csv"
    md_path = args.out_dir / "stage4_localization_sensitivity.md"
    aggregate_csv_path = args.out_dir / "stage4_localization_sensitivity_aggregate.csv"
    aggregate_md_path = args.out_dir / "stage4_localization_sensitivity_aggregate.md"
    point_departure_csv_path = args.out_dir / "stage4_point_departures.csv"
    frame_times_path = args.out_dir / "stage4_validation_frame_times.txt"
    _write_csv(csv_path, rows)
    _write_csv(point_departure_csv_path, point_departure_rows)
    _write_md(md_path, rows)
    aggregate_rows = _aggregate_rows(rows)
    _write_csv(aggregate_csv_path, aggregate_rows)
    _write_aggregate_md(aggregate_md_path, aggregate_rows)
    _write_frame_times(frame_times_path, stage2_rows)
    tail_diagnostics = _write_tail_diagnostics(args.out_dir / "tail_diagnostics", point_departure_rows)
    stratified_eval = write_stratified_eval(
        rows,
        args.out_dir / "stratified_eval",
        expected_frames=0,
        source_csv=str(csv_path),
    )
    run_meta = {
        "stage2_summary": str(args.stage2_summary),
        "stage3_summary": str(args.stage3_summary),
        "frame_times": [str(row["time_str"]) for row in stage2_rows],
        "sample_count": int(args.sample_count),
        "sample_seed": int(args.sample_seed),
        "kernels": kernels,
        "param_grid": grid,
        "confidence_mode": str(args.confidence_mode),
        "physics_constraint_mode": str(args.physics_constraint_mode),
        "observation_anchor_weight": float(args.observation_anchor_weight),
        "speed_limit_mps": float(args.speed_limit_mps),
        "localization_policy": str(args.localization_policy),
        "localization_candidate_grid": str(args.localization_candidate_grid),
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
        "cma_proxy_dir": str(args.cma_proxy_dir),
        "cma_proxy_npz": str(args.cma_proxy_npz or ""),
        "cma_background_weight": float(args.cma_background_weight),
        "cma_confidence_source": str(args.cma_confidence_source),
        "cma_confidence_cap": float(args.cma_confidence_cap),
        "cma_time_confidence": float(args.cma_time_confidence),
        "cma_space_confidence": float(args.cma_space_confidence),
        "cma_pseudo_source": str(args.cma_pseudo_source),
        "cma_qc_gating": str(args.cma_qc_gating),
        "qc_calibration": qc_calibration,
        "output_csv": str(csv_path),
        "output_md": str(md_path),
        "aggregate_csv": str(aggregate_csv_path),
        "aggregate_md": str(aggregate_md_path),
        "point_departure_csv": str(point_departure_csv_path),
        "tail_diagnostics": tail_diagnostics,
        "stratified_eval": stratified_eval,
        "frame_times_file": str(frame_times_path),
        "baseline_stage4_output_dir": str(STRICT_STAGE4_OUTPUT_DIR),
    }
    (args.out_dir / "stage4_localization_sensitivity_run.json").write_text(json.dumps(run_meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(csv_path)


if __name__ == "__main__":
    main()
