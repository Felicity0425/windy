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
    CONFIDENCE_MODES,
    DEFAULT_QC_CALIBRATION,
    LOCALIZATION_KERNELS,
    PHYSICS_CONSTRAINT_MODES,
    ROLE_CONFLICT_MODES,
    STRICT_STAGE4_OUTPUT_DIR,
    _accumulate_localized,
    _build_wind_observations,
    _field_proxy_diagnostics,
    _finalize_effective_reconstruction,
    _leakage_report,
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
    qc_calibration: dict[str, Any] | None,
    current_weight_boost: float = 1.0,
    context_weight_scale: float = 1.0,
    context_time_conf_power: float = 1.0,
    role_conflict_mode: str = "off",
    conflict_speed_threshold_mps: float = 12.0,
    conflict_context_factor: float = 0.25,
) -> dict[str, Any]:
    npz = _load_stage2_npz(Path(stage2_row["multimodal_vox_path"]))
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
    leakage = _leakage_report(
        wind_records=wind_records,
        train_wind=train_wind,
        holdout_wind=holdout_wind,
        observations=observations,
        motion_records=motion_records,
        context_motion_records=context_motion_records,
    )
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
        qc_calibration=qc_calibration or DEFAULT_QC_CALIBRATION,
    )
    recon = _make_reconstruction(acc)
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
    )
    recon = _finalize_effective_reconstruction(recon)
    point_rows = _point_eval_rows(holdout_wind, recon["recon_u"], recon["recon_v"], recon["recon_conf"], observations, acc)
    metrics = _metric_summary(point_rows)
    extent = _reconstruction_extent_stats(recon, pre_refine_voxels)
    field_diag = _field_proxy_diagnostics(recon)
    role_conflict_diag = _role_conflict_diagnostics(acc)
    return {
        "time_str": str(stage2_row["time_str"]),
        "kernel": localization_kernel,
        "confidence_mode": confidence_mode,
        "physics_constraint_mode": physics_constraint_mode,
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
        "diffusion_fill_new_voxels": int(refine_metrics["diffusion_fill_new_voxels"]),
        "observation_anchor_weight": float(observation_anchor_weight),
        "speed_limit_mps": float(speed_limit_mps),
        "current_weight_boost": float(current_weight_boost),
        "context_weight_scale": float(context_weight_scale),
        "context_time_conf_power": float(context_time_conf_power),
        "role_conflict_mode": str(role_conflict_mode),
        "conflict_speed_threshold_mps": float(conflict_speed_threshold_mps),
        "conflict_context_factor": float(conflict_context_factor),
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
        "| frame | kernel | mode | rxy | sxy | rz | sz | holdout | RMSE | MAE | effective voxels | low-conf fill | leakage |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in rows:
        lines.append(
            f"| `{row['time_str']}` | `{row['kernel']}` | `{row.get('physics_constraint_mode', 'proxy')}` | "
            f"{row['localization_radius_xy']} | "
            f"{float(row['localization_sigma_xy']):.2f} | {row['localization_radius_z']} | "
            f"{float(row['localization_sigma_z']):.2f} | {row['holdout_wind_records']} | "
            f"{float(row['rmse_vector']):.6f} | {float(row['mae_vector']):.6f} | "
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


def _aggregate_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    for row in rows:
        key = (
            row.get("kernel"),
            row.get("confidence_mode"),
            row.get("physics_constraint_mode"),
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
        )
        groups.setdefault(key, []).append(row)
    out: list[dict[str, Any]] = []
    for key, group_rows in groups.items():
        out.append(
            {
                "kernel": key[0],
                "confidence_mode": key[1],
                "physics_constraint_mode": key[2],
                "localization_radius_xy": key[3],
                "localization_sigma_xy": key[4],
                "localization_radius_z": key[5],
                "localization_sigma_z": key[6],
                "current_weight_boost": key[7],
                "context_weight_scale": key[8],
                "context_time_conf_power": key[9],
                "role_conflict_mode": key[10],
                "conflict_speed_threshold_mps": key[11],
                "conflict_context_factor": key[12],
                "frames": len(group_rows),
                "mean_rmse_vector": float(np.mean([float(r["rmse_vector"]) for r in group_rows])),
                "mean_mae_vector": float(np.mean([float(r["mae_vector"]) for r in group_rows])),
                "mean_bias_u": float(np.mean([float(r["bias_u"]) for r in group_rows])),
                "mean_bias_v": float(np.mean([float(r["bias_v"]) for r in group_rows])),
                "mean_effective_reconstructed_voxels": float(np.mean([float(r["effective_reconstructed_voxels"]) for r in group_rows])),
                "mean_low_conf_fill_voxels": float(np.mean([float(r["low_conf_fill_voxels"]) for r in group_rows])),
                "mean_role_conflict_voxels": float(np.mean([float(r.get("role_conflict_voxels", 0.0)) for r in group_rows])),
                "mean_role_conflict_threshold_mps": float(np.mean([float(r.get("role_conflict_threshold_mean_mps", 0.0)) for r in group_rows])),
                "mean_role_conflict_context_factor": float(np.mean([float(r.get("role_conflict_context_factor_mean", 0.0)) for r in group_rows])),
                "mean_vertical_context_mismatch_candidate_voxels": float(
                    np.mean([float(r.get("vertical_context_mismatch_candidate_voxels", 0.0)) for r in group_rows])
                ),
                "mean_vertical_oversmoothing_candidate_voxels": float(
                    np.mean([float(r.get("vertical_oversmoothing_candidate_voxels", 0.0)) for r in group_rows])
                ),
                "mean_strong_vertical_isolated_voxels": float(np.mean([float(r.get("strong_vertical_isolated_voxels", 0.0)) for r in group_rows])),
                "all_strict_holdout_no_leakage": bool(all(_as_bool(r["strict_holdout_no_leakage"]) for r in group_rows)),
                "any_motion_used_as_wind": bool(any(_as_bool(r["motion_used_as_wind"]) for r in group_rows)),
            }
        )
    return sorted(out, key=lambda row: float(row["mean_rmse_vector"]))


def _write_aggregate_md(path: Path, rows: list[dict[str, Any]]) -> None:
    lines = [
        "# Stage4 Sensitivity Aggregate",
        "",
        "Metrics-only aggregate. No per-parameter 3D NPZ fields are saved.",
        "",
        "| rank | kernel | confidence | physics | role conflict | rxy/sxy/rz/sz | frames | mean RMSE | mean MAE | mean fill | mean effective | leakage | motion used |",
        "| ---: | --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    for idx, row in enumerate(rows, start=1):
        lines.append(
            f"| {idx} | `{row['kernel']}` | `{row['confidence_mode']}` | `{row['physics_constraint_mode']}` | "
            f"`{row['role_conflict_mode']}` | "
            f"{row['localization_radius_xy']}/{row['localization_sigma_xy']}/"
            f"{row['localization_radius_z']}/{row['localization_sigma_z']} | "
            f"{row['frames']} | {row['mean_rmse_vector']:.6f} | {row['mean_mae_vector']:.6f} | "
            f"{row['mean_low_conf_fill_voxels']:.1f} | {row['mean_effective_reconstructed_voxels']:.1f} | "
            f"`{row['all_strict_holdout_no_leakage']}` | `{row['any_motion_used_as_wind']}` |"
        )
    lines.extend(
        [
            "",
            "## Adaptive/Vertical Diagnostics",
            "",
            "| rank | mean conflict voxels | mean adaptive threshold | mean context factor | mean vertical mismatch | mean oversmooth | mean isolated strong |",
            "| ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for idx, row in enumerate(rows, start=1):
        lines.append(
            f"| {idx} | {row.get('mean_role_conflict_voxels', 0.0):.1f} | "
            f"{row.get('mean_role_conflict_threshold_mps', 0.0):.3f} | "
            f"{row.get('mean_role_conflict_context_factor', 0.0):.3f} | "
            f"{row.get('mean_vertical_context_mismatch_candidate_voxels', 0.0):.1f} | "
            f"{row.get('mean_vertical_oversmoothing_candidate_voxels', 0.0):.1f} | "
            f"{row.get('mean_strong_vertical_isolated_voxels', 0.0):.1f} |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


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


def _run_parent_shards(args: argparse.Namespace, selected: list[dict[str, Any]], kernels: list[str], grid: list[dict[str, float | int]]) -> list[dict[str, Any]]:
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
    for proc, csv_path, log_file, _progress_file, _shard_total in procs:
        rc = proc.wait()
        if rc != 0:
            raise RuntimeError(f"Stage4 sensitivity shard failed rc={rc}; see {log_file}")
        rows.extend(_read_csv_rows(csv_path))
    return rows


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
    parser.add_argument("--current-weight-boost", type=float, default=1.0)
    parser.add_argument("--context-weight-scale", type=float, default=1.0)
    parser.add_argument("--context-time-conf-power", type=float, default=1.0)
    parser.add_argument("--role-conflict-mode", choices=sorted(ROLE_CONFLICT_MODES), default="off")
    parser.add_argument("--conflict-speed-threshold-mps", type=float, default=12.0)
    parser.add_argument("--conflict-context-factor", type=float, default=0.25)
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
    total_tasks = len(stage2_rows) * len(kernels) * len(grid)
    if int(args.shard_id) < 0 and int(args.num_workers) > 1 and len(stage2_rows) > 1:
        rows = _run_parent_shards(args, stage2_rows, kernels, grid)
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
                            qc_calibration=qc_calibration,
                            current_weight_boost=float(args.current_weight_boost),
                            context_weight_scale=float(args.context_weight_scale),
                            context_time_conf_power=float(args.context_time_conf_power),
                            role_conflict_mode=str(args.role_conflict_mode),
                            conflict_speed_threshold_mps=float(args.conflict_speed_threshold_mps),
                            conflict_context_factor=float(args.conflict_context_factor),
                        )
                    )
                    done += 1
                    _write_progress(args.progress_file, completed=done, total=progress_total, shard_id=int(args.shard_id), status="running")
                    now = time.time()
                    if now - last_progress >= max(1.0, float(args.progress_interval_seconds)) or done == total_tasks:
                        _print_progress(done, total_tasks, started=started, force=True)
                        last_progress = now
        _write_progress(args.progress_file, completed=done, total=progress_total, shard_id=int(args.shard_id), status="done")

    args.out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = args.out_dir / "stage4_localization_sensitivity.csv"
    md_path = args.out_dir / "stage4_localization_sensitivity.md"
    aggregate_csv_path = args.out_dir / "stage4_localization_sensitivity_aggregate.csv"
    aggregate_md_path = args.out_dir / "stage4_localization_sensitivity_aggregate.md"
    frame_times_path = args.out_dir / "stage4_validation_frame_times.txt"
    _write_csv(csv_path, rows)
    _write_md(md_path, rows)
    aggregate_rows = _aggregate_rows(rows)
    _write_csv(aggregate_csv_path, aggregate_rows)
    _write_aggregate_md(aggregate_md_path, aggregate_rows)
    _write_frame_times(frame_times_path, stage2_rows)
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
        "current_weight_boost": float(args.current_weight_boost),
        "context_weight_scale": float(args.context_weight_scale),
        "context_time_conf_power": float(args.context_time_conf_power),
        "role_conflict_mode": str(args.role_conflict_mode),
        "conflict_speed_threshold_mps": float(args.conflict_speed_threshold_mps),
        "conflict_context_factor": float(args.conflict_context_factor),
        "qc_calibration": qc_calibration,
        "output_csv": str(csv_path),
        "output_md": str(md_path),
        "aggregate_csv": str(aggregate_csv_path),
        "aggregate_md": str(aggregate_md_path),
        "frame_times_file": str(frame_times_path),
        "baseline_stage4_output_dir": str(STRICT_STAGE4_OUTPUT_DIR),
    }
    (args.out_dir / "stage4_localization_sensitivity_run.json").write_text(json.dumps(run_meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(csv_path)


if __name__ == "__main__":
    main()
