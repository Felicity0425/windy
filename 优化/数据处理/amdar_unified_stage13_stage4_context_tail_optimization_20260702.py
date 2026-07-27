#!/usr/bin/env python3
"""Run Stage13-style Stage4 context-tail optimization experiments.

This is an AMDAR Unified Plan Stage13 helper. It reuses the completed
centralized_v1 Stage12 Stage2/3 products and only writes metrics-only Stage4
experiment outputs plus summaries. It does not alter official Stage2/3/4 code.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np


ROOT = Path("/data/LFT-W02_data/pengxu")
DATA_DIR = ROOT / "优化/数据处理"
STAGE12_DIR = DATA_DIR / "amdar_unified_stage12_stage4_baseline_reproduction_optimized_20260702"
DEFAULT_OUT_DIR = DATA_DIR / "amdar_unified_stage13_stage4_context_tail_optimization_20260702"
STAGE4_SCRIPT = ROOT / "stage/centralized_v1/core/centralized_stage4_sensitivity.py"
STAGE2_SUMMARY = STAGE12_DIR / "stage2_baseline_compat_200/stage2_multimodal_summary.json"
STAGE3_SUMMARY = STAGE12_DIR / "stage3_baseline_compat_200/stage3_center_summary.json"
FRAME_TIMES = STAGE12_DIR / "stage12_frame_times_200.txt"
BASELINE_STAGE4_DIR = STAGE12_DIR / "stage4_baseline_unified_v1_200frames"
LEGACY_OBS_ERROR_CAL = (
    ROOT
    / "centralized_v1_output/stage4_obs_error_weighted_200_20260601/"
    "calibration_downweight_only/stage4_aircraft_obs_error_calibration.json"
)


@dataclass(frozen=True)
class Experiment:
    name: str
    description: str
    args: list[str]
    qc_calibration: Path | None = None
    source_stage4_dir: Path | None = None


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def f(row: dict[str, Any], key: str, default: float = float("nan")) -> float:
    try:
        value = row.get(key)
        if value in ("", None):
            return default
        out = float(value)
        return out if math.isfinite(out) else default
    except Exception:
        return default


def s(row: dict[str, Any], key: str, default: str = "") -> str:
    value = row.get(key)
    return default if value is None else str(value)


def quantile(values: list[float], q: float) -> float | None:
    clean = [v for v in values if math.isfinite(v)]
    if not clean:
        return None
    return float(np.quantile(np.asarray(clean, dtype=np.float64), q))


def mean(values: list[float]) -> float | None:
    clean = [v for v in values if math.isfinite(v)]
    return float(sum(clean) / len(clean)) if clean else None


def rmse(values: list[float]) -> float | None:
    clean = [v for v in values if math.isfinite(v)]
    if not clean:
        return None
    return float(math.sqrt(sum(v * v for v in clean) / len(clean)))


def summarize_point_rows(experiment: Experiment, stage4_dir: Path) -> list[dict[str, Any]]:
    point_rows = read_csv(stage4_dir / "stage4_point_departures.csv")
    rows = point_rows
    errors = [f(row, "vector_error") for row in rows]
    abs_speed_bias = [abs(f(row, "pred_speed") - f(row, "gt_speed")) for row in rows]
    speed_bias = [f(row, "pred_speed") - f(row, "gt_speed") for row in rows]
    high_error = [row for row in rows if f(row, "vector_error") >= 30.0]
    calm_false_strong = [row for row in rows if f(row, "gt_speed") <= 5.0 and f(row, "pred_speed") >= 30.0]
    weak_false_strong = [row for row in rows if f(row, "gt_speed") <= 10.0 and f(row, "pred_speed") >= 50.0]
    strong_under = [row for row in rows if f(row, "gt_speed") >= 80.0 and f(row, "pred_speed") <= 40.0]
    context_only = [row for row in rows if "context_only_nearest_support" in s(row, "qc_review_reasons")]
    role_conflict = [row for row in rows if s(row, "role_conflict_at_point").lower() == "true"]
    no_claim = [row for row in rows if s(row, "no_claim_at_point").lower() == "true"]
    low_reliability = [row for row in rows if f(row, "reliability_confidence_at_point", 1.0) < 0.25]
    all_no_leak = all(s(row, "strict_holdout_no_leakage").lower() == "true" for row in rows)
    any_motion = any(s(row, "motion_used_as_wind").lower() == "true" for row in rows)

    run_meta = read_json(stage4_dir / "stage4_localization_sensitivity_run.json") if (stage4_dir / "stage4_localization_sensitivity_run.json").exists() else {}
    frame_count = len(run_meta.get("frame_times", [])) if isinstance(run_meta, dict) else 0
    config_count = max(1, len(run_meta.get("param_grid", [])) if isinstance(run_meta, dict) else 1)
    expected_points = None
    if frame_count and config_count and len(rows) % config_count == 0:
        expected_points = len(rows) // config_count

    row0 = rows[0] if rows else {}
    summary_row = {
        "experiment": experiment.name,
        "description": experiment.description,
        "stage4_dir": str(stage4_dir),
        "kernel": s(row0, "kernel"),
        "confidence_mode": s(row0, "confidence_mode"),
        "physics_constraint_mode": s(row0, "physics_constraint_mode"),
        "localization_policy": s(row0, "localization_policy"),
        "localization_radius_xy": str(run_meta.get("param_grid", [{}])[0].get("localization_radius_xy", s(row0, "localization_radius_xy"))) if isinstance(run_meta, dict) else s(row0, "localization_radius_xy"),
        "localization_sigma_xy": str(run_meta.get("param_grid", [{}])[0].get("localization_sigma_xy", s(row0, "localization_sigma_xy"))) if isinstance(run_meta, dict) else s(row0, "localization_sigma_xy"),
        "localization_radius_z": str(run_meta.get("param_grid", [{}])[0].get("localization_radius_z", s(row0, "localization_radius_z"))) if isinstance(run_meta, dict) else s(row0, "localization_radius_z"),
        "localization_sigma_z": str(run_meta.get("param_grid", [{}])[0].get("localization_sigma_z", s(row0, "localization_sigma_z"))) if isinstance(run_meta, dict) else s(row0, "localization_sigma_z"),
        "stage4_param_config_count": config_count,
        "frame_count": frame_count,
        "holdout_points": len(rows),
        "expected_points_per_config": expected_points,
        "point_rmse_vector": rmse(errors),
        "point_mae_vector": mean(errors),
        "point_p50_vector": quantile(errors, 0.50),
        "point_p90_vector": quantile(errors, 0.90),
        "point_p95_vector": quantile(errors, 0.95),
        "point_p99_vector": quantile(errors, 0.99),
        "point_max_vector": max(errors) if errors else None,
        "mean_abs_speed_bias": mean(abs_speed_bias),
        "mean_speed_bias_pred_minus_truth": mean(speed_bias),
        "high_error_ge30_count": len(high_error),
        "calm_truth_le5_pred_ge30_count": len(calm_false_strong),
        "weak_truth_le10_pred_ge50_count": len(weak_false_strong),
        "strong_truth_ge80_pred_le40_count": len(strong_under),
        "context_only_nearest_count": len(context_only),
        "role_conflict_at_point_count": len(role_conflict),
        "no_claim_count": len(no_claim),
        "low_reliability_lt025_count": len(low_reliability),
        "mean_reliability_confidence": mean([f(row, "reliability_confidence_at_point") for row in rows]),
        "median_recon_confidence": quantile([f(row, "recon_confidence") for row in rows], 0.50),
        "all_strict_holdout_no_leakage": all_no_leak,
        "any_motion_used_as_wind": any_motion,
        "adaptive_reasons_example": s(row0, "adaptive_reasons"),
        "adaptive_current_support_example": s(row0, "adaptive_current_support"),
        "adaptive_context_support_example": s(row0, "adaptive_context_support"),
    }
    return [summary_row]


def stage4_complete(stage4_dir: Path) -> bool:
    return (
        (stage4_dir / "stage4_point_departures.csv").exists()
        and (stage4_dir / "stage4_localization_sensitivity_run.json").exists()
    )


def run_stage4(exp: Experiment, out_dir: Path, *, force: bool, num_workers: int) -> Path:
    if exp.source_stage4_dir is not None:
        return exp.source_stage4_dir
    stage4_dir = out_dir / "experiments" / exp.name
    if stage4_complete(stage4_dir) and not force:
        return stage4_dir
    cmd = [
        sys.executable,
        str(STAGE4_SCRIPT),
        "--stage2-summary",
        str(STAGE2_SUMMARY),
        "--stage3-summary",
        str(STAGE3_SUMMARY),
        "--frame-times-file",
        str(FRAME_TIMES),
        "--sample-count",
        "0",
        "--progress-interval-seconds",
        "30",
        "--num-workers",
        str(num_workers),
        "--out-dir",
        str(stage4_dir),
        *exp.args,
    ]
    if exp.qc_calibration is not None:
        cmd.extend(["--qc-calibration", str(exp.qc_calibration)])
    env = os.environ.copy()
    env["POLARS_MAX_THREADS"] = str(num_workers)
    env.setdefault("OMP_NUM_THREADS", "1")
    env.setdefault("OPENBLAS_NUM_THREADS", "1")
    log_path = out_dir / "logs" / f"{exp.name}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    started = datetime.now(timezone.utc)
    with log_path.open("w", encoding="utf-8") as log:
        proc = subprocess.run(cmd, cwd=str(ROOT), env=env, stdout=log, stderr=subprocess.STDOUT, text=True)
    ended = datetime.now(timezone.utc)
    run_record = {
        "experiment": exp.name,
        "description": exp.description,
        "cmd": cmd,
        "log_path": str(log_path),
        "returncode": proc.returncode,
        "started_at_utc": started.isoformat(),
        "ended_at_utc": ended.isoformat(),
        "elapsed_seconds": (ended - started).total_seconds(),
    }
    write_json(out_dir / "logs" / f"{exp.name}.run.json", run_record)
    if proc.returncode != 0:
        raise RuntimeError(f"Stage4 experiment failed: {exp.name}; see {log_path}")
    return stage4_dir


def write_calibrations(out_dir: Path) -> dict[str, Path]:
    cal_dir = out_dir / "calibration"
    tail_v1 = {
        "calibration_role": "stage13_context_tail_conservative_v1",
        "speed_soft_limit_mps": 70.0,
        "speed_hard_limit_mps": 105.0,
        "speed_flag_factor": 0.20,
        "speed_hard_factor": 0.20,
        "speed_soft_factor": 0.45,
        "density_min": 0.05,
        "time_spread_halflife_minutes": 90.0,
        "representation_error_soft_weight_strength": 0.85,
        "representation_error_soft_weight_min_current": 0.85,
        "representation_error_soft_weight_min_context": 0.18,
        "representation_error_soft_weight_high_altitude_m": 9000.0,
        "representation_error_soft_weight_mid_altitude_m": 6000.0,
        "representation_error_soft_weight_speed_start_mps": 20.0,
        "representation_error_soft_weight_speed_full_mps": 90.0,
        "representation_error_soft_weight_context_stale_time_conf": 0.70,
        "representation_error_soft_weight_density_count_scale": 3.0,
        "role_conflict_adaptive_min_context_factor": 0.02,
        "role_conflict_adaptive_max_context_factor": 0.50,
        "role_conflict_adaptive_stale_context_factor_reduction": 0.70,
        "role_conflict_adaptive_current_density_factor_reduction": 0.25,
        "vertical_localization_strong_speed_mps": 45.0,
        "vertical_localization_high_altitude_m": 7000.0,
        "vertical_localization_strong_speed_factor": 0.65,
        "vertical_localization_high_altitude_factor": 0.75,
        "vertical_localization_stale_context_time_conf": 0.45,
        "vertical_localization_stale_context_factor": 0.60,
        "point_regime_localization_min_xy_factor": 0.80,
        "point_regime_localization_min_z_factor": 0.70,
        "point_regime_localization_remote_xy_factor": 0.88,
        "point_regime_localization_context_only_xy_factor": 0.88,
        "point_regime_localization_high_altitude_xy_factor": 0.88,
        "point_regime_localization_vertical_gap_xy_factor": 0.88,
        "point_regime_localization_high_altitude_z_factor": 0.82,
        "point_regime_localization_vertical_gap_z_factor": 0.78,
        "references": [
            "https://community.wmo.int/en/activity-areas/aircraft-based-observations",
            "https://amdar.noaa.gov/",
            "https://amt.copernicus.org/articles/18/3341/2025/",
            "https://amt.copernicus.org/articles/9/4141/2016/",
            "https://openradarscience.org/PyDDA/",
        ],
    }
    tail_v2 = dict(tail_v1)
    tail_v2.update(
        {
            "calibration_role": "stage13_context_tail_strong_downweight_v2",
            "speed_soft_limit_mps": 55.0,
            "speed_hard_limit_mps": 90.0,
            "speed_soft_factor": 0.30,
            "speed_hard_factor": 0.12,
            "representation_error_soft_weight_strength": 0.95,
            "representation_error_soft_weight_min_context": 0.08,
            "representation_error_soft_weight_speed_start_mps": 15.0,
            "representation_error_soft_weight_speed_full_mps": 75.0,
        }
    )
    paths = {
        "tail_v1": cal_dir / "stage13_context_tail_conservative_v1.json",
        "tail_v2": cal_dir / "stage13_context_tail_strong_downweight_v2.json",
    }
    write_json(paths["tail_v1"], tail_v1)
    write_json(paths["tail_v2"], tail_v2)
    return paths


def experiments(out_dir: Path, calibration_paths: dict[str, Path]) -> list[Experiment]:
    base_args = [
        "--kernels",
        "gaussian",
        "--confidence-mode",
        "diagnostic_weighted",
        "--physics-constraint-mode",
        "pydda_3dvar_proxy",
        "--current-weight-boost",
        "2.0",
        "--context-weight-scale",
        "0.5",
        "--context-time-conf-power",
        "2.6",
        "--role-conflict-mode",
        "current_priority_adaptive",
        "--conflict-speed-threshold-mps",
        "11.0",
        "--conflict-context-factor",
        "0.25",
        "--localization-policy",
        "diagnostic_adaptive_v3",
        "--localization-candidate-grid",
        "8:4,10:5",
        "--vertical-risk-mode",
        "preserve_strong_layers",
        "--vertical-gradient-preserve-weight",
        "0.12",
        "--vertical-context-mismatch-damping",
        "0.35",
    ]
    return [
        Experiment(
            name="B0_stage12_existing",
            description="Existing Stage12 strict-TURB baseline with AMDAR support context.",
            args=[],
            source_stage4_dir=BASELINE_STAGE4_DIR,
        ),
        Experiment(
            name="G1_obs_error_8x4",
            description="Legacy observation-error calibration, fixed single 8/4/2/1 base config.",
            args=[*base_args, "--param-grid", "8,4,2,1", "--confidence-mode", "obs_error_weighted"],
            qc_calibration=LEGACY_OBS_ERROR_CAL,
        ),
        Experiment(
            name="G2_rep_soft_8x4_tail_v1",
            description="Representation-error soft weighting, conservative tail calibration, 8/4/2/1.",
            args=[
                *base_args,
                "--param-grid",
                "8,4,2,1",
                "--confidence-mode",
                "representation_error_soft_weighted",
                "--vertical-localization-policy",
                "support_adaptive",
            ],
            qc_calibration=calibration_paths["tail_v1"],
        ),
        Experiment(
            name="G3_rep_soft_6x3_tail_v1",
            description="Representation-error soft weighting with tighter 6/3/1/0.75 localization.",
            args=[
                *base_args,
                "--param-grid",
                "6,3,1,0.75",
                "--confidence-mode",
                "representation_error_soft_weighted",
                "--localization-policy",
                "fixed",
                "--vertical-localization-policy",
                "support_adaptive",
            ],
            qc_calibration=calibration_paths["tail_v1"],
        ),
        Experiment(
            name="G4_gaspari_4x2_tail_v1",
            description="Compact Gaspari-Cohn localization 4/2/1/0.75 to reduce context-only bleed.",
            args=[
                *base_args,
                "--kernels",
                "gaspari_cohn",
                "--param-grid",
                "4,2,1,0.75",
                "--confidence-mode",
                "representation_error_soft_weighted",
                "--localization-policy",
                "fixed",
            ],
            qc_calibration=calibration_paths["tail_v1"],
        ),
        Experiment(
            name="G5_gaspari_6x3_tail_v1",
            description="Compact Gaspari-Cohn localization 6/3/1/0.75 to reduce context-only bleed.",
            args=[
                *base_args,
                "--kernels",
                "gaspari_cohn",
                "--param-grid",
                "6,3,1,0.75",
                "--confidence-mode",
                "representation_error_soft_weighted",
                "--localization-policy",
                "fixed",
            ],
            qc_calibration=calibration_paths["tail_v1"],
        ),
        Experiment(
            name="G6_point_regime_6x3_tail_v1",
            description="Point-regime localization with conservative context-tail weighting, 6/3/1/0.75.",
            args=[
                *base_args,
                "--param-grid",
                "6,3,1,0.75",
                "--confidence-mode",
                "representation_error_soft_weighted",
                "--localization-policy",
                "point_regime_localization_v1",
            ],
            qc_calibration=calibration_paths["tail_v1"],
        ),
        Experiment(
            name="G7_strong_downweight_6x3_v2",
            description="Aggressive high-speed context downweight, fixed 6/3/1/0.75.",
            args=[
                *base_args,
                "--param-grid",
                "6,3,1,0.75",
                "--confidence-mode",
                "representation_error_soft_weighted",
                "--localization-policy",
                "fixed",
            ],
            qc_calibration=calibration_paths["tail_v2"],
        ),
    ]


def best_rows(rows: list[dict[str, Any]], limit: int = 12) -> list[dict[str, Any]]:
    return sorted(
        rows,
        key=lambda row: (
            row.get("point_rmse_vector") is None,
            row.get("point_rmse_vector") or 1e9,
            row.get("point_p95_vector") or 1e9,
            row.get("high_error_ge30_count") or 1e9,
        ),
    )[:limit]


def write_markdown(out_dir: Path, rows: list[dict[str, Any]]) -> None:
    best = best_rows(rows, 15)
    baseline = next((row for row in rows if row["experiment"] == "B0_stage12_existing"), None)
    top = best[0] if best else None
    lines = [
        "# Stage13 Stage4 Context-Tail Optimization Results",
        "",
        "This run is AMDAR Unified Plan Stage13-style optimization. It reuses the completed Stage12 centralized_v1 Stage2/3 products and writes only metrics-only Stage4 experiment outputs.",
        "",
        "## Boundary",
        "",
        "- centralized_v1 large framework remains Stage1/2/3/4.",
        "- This document's Stage13 means the AMDAR Unified Plan ablation/optimization stage.",
        "- AMDAR is not used as strict truth or holdout in any experiment here; it is support/context only.",
        "- All experiments preserve strict holdout no-leakage and do not use motion records as wind.",
        "",
        "## Result Summary",
        "",
    ]
    if baseline and top:
        b_rmse = baseline.get("point_rmse_vector")
        t_rmse = top.get("point_rmse_vector")
        improvement = None
        if b_rmse and t_rmse:
            improvement = 100.0 * (float(b_rmse) - float(t_rmse)) / float(b_rmse)
        lines.extend(
            [
                f"- Baseline point-weighted RMSE: `{b_rmse:.6f}` m/s",
                f"- Best experiment/config: `{top['experiment']}` ({top['kernel']}, {top['confidence_mode']}, {top['localization_policy']}, rxy/sxy/rz/sz={top['localization_radius_xy']}/{top['localization_sigma_xy']}/{top['localization_radius_z']}/{top['localization_sigma_z']})",
                f"- Best point-weighted RMSE: `{t_rmse:.6f}` m/s",
                f"- RMSE improvement vs baseline: `{improvement:.2f}%`" if improvement is not None else "- RMSE improvement vs baseline: `n/a`",
                f"- Baseline high-error >=30 m/s count: `{baseline.get('high_error_ge30_count')}`",
                f"- Best high-error >=30 m/s count: `{top.get('high_error_ge30_count')}`",
                f"- Baseline p95 / max: `{baseline.get('point_p95_vector'):.6f}` / `{baseline.get('point_max_vector'):.6f}` m/s",
                f"- Best p95 / max: `{top.get('point_p95_vector'):.6f}` / `{top.get('point_max_vector'):.6f}` m/s",
                "",
            ]
        )
    lines.extend(
        [
            "## Ranked Configs",
            "",
            "| rank | experiment | kernel | confidence | policy | rxy/sxy/rz/sz | points | RMSE | MAE | p95 | max | high>=30 | calm false strong | weak false strong | strong under | leakage | motion-as-wind |",
            "| ---: | --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |",
        ]
    )
    for idx, row in enumerate(best, start=1):
        lines.append(
            f"| {idx} | `{row['experiment']}` | `{row['kernel']}` | `{row['confidence_mode']}` | `{row['localization_policy']}` | "
            f"{row['localization_radius_xy']}/{row['localization_sigma_xy']}/{row['localization_radius_z']}/{row['localization_sigma_z']} | "
            f"{row['holdout_points']} | {row['point_rmse_vector']:.6f} | {row['point_mae_vector']:.6f} | "
            f"{row['point_p95_vector']:.6f} | {row['point_max_vector']:.6f} | {row['high_error_ge30_count']} | "
            f"{row['calm_truth_le5_pred_ge30_count']} | {row['weak_truth_le10_pred_ge50_count']} | "
            f"{row['strong_truth_ge80_pred_le40_count']} | `{row['all_strict_holdout_no_leakage']}` | `{row['any_motion_used_as_wind']}` |"
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "The Stage12 baseline passed role/leakage gates but was not satisfactory for reconstruction quality. The main weakness was a small number of context-only, speed-amplitude tail failures, not a broad direction bias. These experiments test whether the tail can be reduced by making Stage4 more conservative where support is high-speed, high-altitude, context-only, sparse, or low-reliability.",
            "",
            "A configuration should not be promoted only because mean RMSE improves. It must also keep strict no-leakage true, motion-as-wind false, and avoid increasing calm false-strong or strong-wind underprediction regimes.",
            "",
            "## Outputs",
            "",
            f"- Machine summary: `{out_dir / 'stage13_stage4_context_tail_optimization_summary.json'}`",
            f"- Ranked CSV: `{out_dir / 'stage13_stage4_context_tail_optimization_ranked.csv'}`",
            f"- Experiment dirs: `{out_dir / 'experiments'}`",
            f"- Logs: `{out_dir / 'logs'}`",
        ]
    )
    (out_dir / "stage13_stage4_context_tail_optimization_results_analysis_and_next_steps.md").write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )


def write_handover(out_dir: Path, rows: list[dict[str, Any]]) -> None:
    best = best_rows(rows, 1)[0] if rows else None
    lines = [
        "# Next Agent Handover: After Stage13 Stage4 Context-Tail Optimization",
        "",
        "You are continuing `/data/LFT-W02_data/pengxu` centralized_v1 3D horizontal wind reconstruction work. Keep the naming boundary clear:",
        "",
        "- centralized_v1 large framework stages are Stage1/2/3/4.",
        "- Stage9/10/11/12/13 are AMDAR Unified Plan stages under `/data/LFT-W02_data/pengxu/优化/数据处理/amdar_unified_implementation_plan_20260701.md`.",
        "",
        "## Must Read",
        "",
        "1. `/data/LFT-W02_data/pengxu/workflow/centralized_v1_docs/new_window_project_handover_20260529/centralized_v1_ultimate_summary_20260626.md`",
        "2. `/data/LFT-W02_data/pengxu/优化/数据处理/amdar_plan4_comprehensive_assessment_20260701.md`",
        "3. `/data/LFT-W02_data/pengxu/优化/数据处理/amdar_unified_stage11_stage2_compat_smoke_optimized_20260702/stage9_10_11_integrated_assessment_and_stage12_readiness.md`",
        "4. `/data/LFT-W02_data/pengxu/优化/数据处理/amdar_unified_stage12_stage4_baseline_reproduction_optimized_20260702/stage12_baseline_reproduction_results_analysis_and_next_steps.md`",
        "5. `/data/LFT-W02_data/pengxu/优化/数据处理/amdar_unified_stage12_stage4_baseline_reproduction_optimized_20260702/stage4_holdout_diagnostics_and_stage13_supplement/stage4_holdout_diagnostics_and_stage13_supplement.md`",
        f"6. `{out_dir / 'stage13_stage4_context_tail_optimization_results_analysis_and_next_steps.md'}`",
        f"7. `{out_dir / 'stage13_stage4_context_tail_optimization_summary.json'}`",
        "",
        "## Current Understanding",
        "",
        "- AMDAR batch timestamps are not per-point strict truth. AMDAR must stay out of `wind_records` and official holdout.",
        "- TURB T0/S is the current strict truth source after Stage11 compatibility rewriting.",
        "- Stage12 baseline is better named `B0_stage12_strict_TURB_truth_with_AMDAR_support_context`, not true no-AMDAR E0.",
        "- The poor Stage12 reconstruction is mainly a speed-amplitude tail problem in context-only support regimes.",
        "- Do not compare this strict-TURB 148-point population directly to the old legacy 530-point AMDAR+TURB population.",
        "",
        "## Latest Optimization Result",
        "",
    ]
    if best:
        lines.extend(
            [
                f"- Best config: `{best['experiment']}`",
                f"- RMSE / MAE / p95 / max: `{best['point_rmse_vector']:.6f}` / `{best['point_mae_vector']:.6f}` / `{best['point_p95_vector']:.6f}` / `{best['point_max_vector']:.6f}` m/s",
                f"- high-error >=30 m/s count: `{best['high_error_ge30_count']}`",
                f"- calm false-strong count: `{best['calm_truth_le5_pred_ge30_count']}`",
                f"- weak false-strong count: `{best['weak_truth_le10_pred_ge50_count']}`",
                f"- strong underprediction count: `{best['strong_truth_ge80_pred_le40_count']}`",
                f"- strict no leakage: `{best['all_strict_holdout_no_leakage']}`",
                f"- motion used as wind: `{best['any_motion_used_as_wind']}`",
                f"- Stage4 dir: `{best['stage4_dir']}`",
            ]
        )
    lines.extend(
        [
            "",
            "## Next Recommended Actions",
            "",
            "1. If the best config improves both RMSE and tail gates, rerun it once as a named candidate and generate full diagnostic plots from its `stage4_point_departures.csv`.",
            "2. Add `E0_true_no_AMDAR_support` as a separate Stage2 NPZ view by filtering AMDAR out of `context_wind_records`; use it only as an ablation baseline.",
            "3. If tail remains high, do not loosen truth. Investigate TURB weak-wind/high-conflict cases and add an explicit holdout reliability review gate.",
            "4. Keep all runs in 25-slice / `POLARS_MAX_THREADS=25` mode and avoid copying 25 full intermediate datasets.",
            "",
            "## Suggested Opening Prompt",
            "",
            "```text",
            "I have read Stage12 and Stage13 context-tail optimization outputs. I understand centralized_v1 Stage1/2/3/4 is separate from AMDAR Unified Plan Stage9/10/11/12/13. AMDAR remains support-only, TURB is strict truth, and the Stage12 failure mode is context-only speed-amplitude tail error. I will continue with strict no-leakage Stage4 candidate validation and add true no-AMDAR support ablation without changing holdout truth.",
            "```",
        ]
    )
    (out_dir / "next_agent_handover_after_stage13_stage4_context_tail_optimization.md").write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--num-workers", type=int, default=25)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--only", nargs="*", default=None, help="Optional experiment names to run/summarize.")
    args = parser.parse_args()

    out_dir = args.out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    calibration_paths = write_calibrations(out_dir)
    exps = experiments(out_dir, calibration_paths)
    if args.only:
        wanted = set(args.only)
        exps = [exp for exp in exps if exp.name in wanted]
        missing = sorted(wanted - {exp.name for exp in exps})
        if missing:
            raise ValueError(f"Unknown experiments: {missing}")

    all_rows: list[dict[str, Any]] = []
    run_index: list[dict[str, Any]] = []
    for exp in exps:
        stage4_dir = run_stage4(exp, out_dir, force=bool(args.force), num_workers=int(args.num_workers))
        rows = summarize_point_rows(exp, stage4_dir)
        all_rows.extend(rows)
        run_index.append(
            {
                "experiment": exp.name,
                "description": exp.description,
                "stage4_dir": str(stage4_dir),
                "configs": len(rows),
                "best_point_rmse_vector": rows[0].get("point_rmse_vector") if rows else None,
            }
        )

    ranked = best_rows(all_rows, len(all_rows))
    write_csv(out_dir / "stage13_stage4_context_tail_optimization_ranked.csv", ranked)
    summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "stage_boundary_note": "This is AMDAR Unified Plan Stage13-style optimization. It calls centralized_v1 Stage4 metrics-only on completed Stage12 Stage2/3 products.",
        "run_policy": {
            "polars_threads": int(args.num_workers),
            "num_workers": int(args.num_workers),
            "space_saving": "Reuse one Stage12 Stage2 output and one Stage3 output; write metrics-only Stage4 experiment dirs. No 25 full intermediate copies.",
        },
        "inputs": {
            "stage12_dir": str(STAGE12_DIR),
            "stage2_summary": str(STAGE2_SUMMARY),
            "stage3_summary": str(STAGE3_SUMMARY),
            "frame_times": str(FRAME_TIMES),
            "baseline_stage4_dir": str(BASELINE_STAGE4_DIR),
        },
        "run_index": run_index,
        "ranked_configs": ranked,
        "best_config": ranked[0] if ranked else None,
        "outputs": {
            "ranked_csv": str(out_dir / "stage13_stage4_context_tail_optimization_ranked.csv"),
            "analysis_md": str(out_dir / "stage13_stage4_context_tail_optimization_results_analysis_and_next_steps.md"),
            "handover_md": str(out_dir / "next_agent_handover_after_stage13_stage4_context_tail_optimization.md"),
        },
    }
    write_json(out_dir / "stage13_stage4_context_tail_optimization_summary.json", summary)
    write_markdown(out_dir, ranked)
    write_handover(out_dir, ranked)
    print(json.dumps({"out_dir": str(out_dir), "best_config": ranked[0] if ranked else None}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
