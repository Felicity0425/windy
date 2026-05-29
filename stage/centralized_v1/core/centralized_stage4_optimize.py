"""Small-grid Stage4 method optimization without overwriting baseline outputs."""

from __future__ import annotations

import argparse
import csv
import json
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

from stage.centralized_v1.configs.centralized_v1_config import REGENERATED_STAGE2_OUTPUT_DIR
from stage.centralized_v1.core.centralized_stage4_ground_recon import DEFAULT_QC_CALIBRATION, _load_json, _load_qc_calibration
from stage.centralized_v1.core.centralized_stage4_sensitivity import (
    DEFAULT_EXPANDED_FRAMES,
    DEFAULT_EXPANDED_STAGE3_SUMMARY,
    _evaluate_metrics_only,
    _parse_param_grid,
    _select_rows,
)


DEFAULT_OUT_DIR = Path("/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_center_strict_expanded/optimization")


def _parse_csv_values(text: str, cast):
    return [cast(token.strip()) for token in str(text).split(",") if token.strip()]


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


def _score(row: dict[str, Any], fill_penalty: float, coverage_penalty: float) -> float:
    rmse = float(row.get("rmse_vector", row.get("mean_rmse_vector", 0.0)))
    fill = float(row.get("low_conf_fill_voxels", row.get("mean_low_conf_fill_voxels", 0.0)))
    effective = float(row.get("effective_reconstructed_voxels", row.get("mean_effective_reconstructed_voxels", 0.0)))
    return rmse + fill_penalty * fill / 100000.0 - coverage_penalty * effective / 100000.0


def _write_md(path: Path, rows: list[dict[str, Any]], fill_penalty: float, coverage_penalty: float) -> None:
    lines = [
        "# Stage4 Small-Grid Optimization",
        "",
        "This is a controlled small-batch optimization table. It does not replace the baseline default.",
        "",
        f"Score = RMSE + {fill_penalty} * low_conf_fill/100000 - {coverage_penalty} * effective_voxels/100000.",
        "",
        "| rank | kernel | confidence | physics | role conflict | rxy/sxy/rz/sz | smooth/div/fill/anchor | mean RMSE | mean MAE | mean fill | mean effective | score |",
        "| ---: | --- | --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for idx, row in enumerate(rows[:20], start=1):
        lines.append(
            f"| {idx} | `{row['kernel']}` | `{row['confidence_mode']}` | `{row['physics_constraint_mode']}` | "
            f"`{row.get('role_conflict_mode', 'off')}` | "
            f"{row['localization_radius_xy']}/{row['localization_sigma_xy']}/"
            f"{row['localization_radius_z']}/{row['localization_sigma_z']} | "
            f"{row['pinn_smoothness_weight']}/{row['pinn_divergence_weight']}/"
            f"{row['low_conf_fill_weight']}/{row['observation_anchor_weight']} | "
            f"{row['mean_rmse_vector']:.6f} | {row['mean_mae_vector']:.6f} | "
            f"{row['mean_low_conf_fill_voxels']:.1f} | {row['mean_effective_reconstructed_voxels']:.1f} | "
            f"{row['score']:.6f} |"
        )
    lines.extend(
        [
            "",
            "References:",
            "",
            "- DART Gaspari-Cohn localization: https://docs.dart.ucar.edu/en/latest/assimilation_code/modules/assimilation/cov_cutoff_mod.html",
            "- PyDDA/3DVAR wind retrieval constraints: https://openresearchsoftware.metajnl.com/articles/264",
            "- Data leakage guidance: https://scikit-learn.org/stable/common_pitfalls.html#data-leakage",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run small-grid Stage4 method optimization.")
    parser.add_argument("--stage2-summary", type=Path, default=REGENERATED_STAGE2_OUTPUT_DIR / "stage2_multimodal_summary.json")
    parser.add_argument("--stage3-summary", type=Path, default=DEFAULT_EXPANDED_STAGE3_SUMMARY)
    parser.add_argument("--frame-times", default=DEFAULT_EXPANDED_FRAMES)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--param-grid", default="8,4,2,1;12,6,2,1")
    parser.add_argument("--kernels", default="gaussian,gaspari_cohn")
    parser.add_argument("--confidence-modes", default="diagnostic_weighted")
    parser.add_argument("--physics-modes", default="pydda_3dvar_proxy")
    parser.add_argument("--smoothness-weights", default="0.018")
    parser.add_argument("--divergence-weights", default="0.006,0.010")
    parser.add_argument("--low-conf-fill-weights", default="0.60")
    parser.add_argument("--observation-anchor-weights", default="0.10")
    parser.add_argument("--current-weight-boosts", default="1.0")
    parser.add_argument("--context-weight-scales", default="1.0")
    parser.add_argument("--context-time-conf-powers", default="1.0")
    parser.add_argument("--role-conflict-modes", default="off")
    parser.add_argument("--conflict-speed-thresholds-mps", default="12.0")
    parser.add_argument("--conflict-context-factors", default="0.25")
    parser.add_argument("--holdout-fraction", type=float, default=0.125)
    parser.add_argument("--holdout-count", type=int, default=0)
    parser.add_argument("--refine-iters", type=int, default=4)
    parser.add_argument("--diffusion-weight", type=float, default=0.22)
    parser.add_argument("--source-preserve", type=float, default=0.95)
    parser.add_argument("--speed-limit-mps", type=float, default=120.0)
    parser.add_argument("--qc-calibration", type=Path)
    parser.add_argument("--fill-penalty", type=float, default=0.20)
    parser.add_argument("--coverage-penalty", type=float, default=0.03)
    args = parser.parse_args()

    if args.stage3_summary and not args.stage3_summary.exists():
        raise FileNotFoundError(f"Stage3 summary not found: {args.stage3_summary}")
    stage2_rows = _select_rows(_load_json(args.stage2_summary), args.frame_times)
    grid = _parse_param_grid(args.param_grid)
    kernels = _parse_csv_values(args.kernels, str)
    confidence_modes = _parse_csv_values(args.confidence_modes, str)
    physics_modes = _parse_csv_values(args.physics_modes, str)
    smoothness_weights = _parse_csv_values(args.smoothness_weights, float)
    divergence_weights = _parse_csv_values(args.divergence_weights, float)
    fill_weights = _parse_csv_values(args.low_conf_fill_weights, float)
    anchor_weights = _parse_csv_values(args.observation_anchor_weights, float)
    current_boosts = _parse_csv_values(args.current_weight_boosts, float)
    context_scales = _parse_csv_values(args.context_weight_scales, float)
    context_powers = _parse_csv_values(args.context_time_conf_powers, float)
    role_conflict_modes = _parse_csv_values(args.role_conflict_modes, str)
    conflict_thresholds = _parse_csv_values(args.conflict_speed_thresholds_mps, float)
    conflict_factors = _parse_csv_values(args.conflict_context_factors, float)
    qc_calibration = _load_qc_calibration(args.qc_calibration) if args.qc_calibration else dict(DEFAULT_QC_CALIBRATION)

    combo_rows = []
    detail_rows = []
    for kernel in kernels:
        for confidence_mode in confidence_modes:
            for physics_mode in physics_modes:
                for params in grid:
                    for smooth_w in smoothness_weights:
                        for div_w in divergence_weights:
                            for fill_w in fill_weights:
                                for anchor_w in anchor_weights:
                                    for current_boost in current_boosts:
                                        for context_scale in context_scales:
                                            for context_power in context_powers:
                                                for role_conflict_mode in role_conflict_modes:
                                                    for conflict_threshold in conflict_thresholds:
                                                        for conflict_factor in conflict_factors:
                                                            frame_rows = []
                                                            for stage2_row in stage2_rows:
                                                                row = _evaluate_metrics_only(
                                                                    stage2_row,
                                                                    localization_kernel=kernel,
                                                                    confidence_mode=confidence_mode,
                                                                    holdout_fraction=float(args.holdout_fraction),
                                                                    holdout_count=int(args.holdout_count),
                                                                    localization_radius_xy=int(params["localization_radius_xy"]),
                                                                    localization_radius_z=int(params["localization_radius_z"]),
                                                                    localization_sigma_xy=float(params["localization_sigma_xy"]),
                                                                    localization_sigma_z=float(params["localization_sigma_z"]),
                                                                    refine_iters=int(args.refine_iters),
                                                                    pinn_smoothness_weight=float(smooth_w),
                                                                    pinn_divergence_weight=float(div_w),
                                                                    diffusion_weight=float(args.diffusion_weight),
                                                                    low_conf_fill_weight=float(fill_w),
                                                                    source_preserve=float(args.source_preserve),
                                                                    physics_constraint_mode=physics_mode,
                                                                    observation_anchor_weight=float(anchor_w),
                                                                    speed_limit_mps=float(args.speed_limit_mps),
                                                                    qc_calibration=qc_calibration,
                                                                    current_weight_boost=float(current_boost),
                                                                    context_weight_scale=float(context_scale),
                                                                    context_time_conf_power=float(context_power),
                                                                    role_conflict_mode=str(role_conflict_mode),
                                                                    conflict_speed_threshold_mps=float(conflict_threshold),
                                                                    conflict_context_factor=float(conflict_factor),
                                                                )
                                                                frame_rows.append(row)
                                                                detail_rows.append(
                                                                    {
                                                                        **row,
                                                                        "pinn_smoothness_weight": float(smooth_w),
                                                                        "pinn_divergence_weight": float(div_w),
                                                                        "low_conf_fill_weight": float(fill_w),
                                                                    }
                                                                )
                                                            aggregate = {
                                                                "kernel": kernel,
                                                                "confidence_mode": confidence_mode,
                                                                "physics_constraint_mode": physics_mode,
                                                                "localization_radius_xy": int(params["localization_radius_xy"]),
                                                                "localization_sigma_xy": float(params["localization_sigma_xy"]),
                                                                "localization_radius_z": int(params["localization_radius_z"]),
                                                                "localization_sigma_z": float(params["localization_sigma_z"]),
                                                                "pinn_smoothness_weight": float(smooth_w),
                                                                "pinn_divergence_weight": float(div_w),
                                                                "low_conf_fill_weight": float(fill_w),
                                                                "observation_anchor_weight": float(anchor_w),
                                                                "current_weight_boost": float(current_boost),
                                                                "context_weight_scale": float(context_scale),
                                                                "context_time_conf_power": float(context_power),
                                                                "role_conflict_mode": str(role_conflict_mode),
                                                                "conflict_speed_threshold_mps": float(conflict_threshold),
                                                                "conflict_context_factor": float(conflict_factor),
                                                                "mean_rmse_vector": float(np.mean([r["rmse_vector"] for r in frame_rows])),
                                                                "mean_mae_vector": float(np.mean([r["mae_vector"] for r in frame_rows])),
                                                                "mean_low_conf_fill_voxels": float(np.mean([r["low_conf_fill_voxels"] for r in frame_rows])),
                                                                "mean_effective_reconstructed_voxels": float(np.mean([r["effective_reconstructed_voxels"] for r in frame_rows])),
                                                                "mean_role_conflict_voxels": float(np.mean([r["role_conflict_voxels"] for r in frame_rows])),
                                                                "all_strict_holdout_no_leakage": bool(all(r["strict_holdout_no_leakage"] for r in frame_rows)),
                                                                "any_motion_used_as_wind": bool(any(r["motion_used_as_wind"] for r in frame_rows)),
                                                            }
                                                            aggregate["score"] = _score(aggregate, float(args.fill_penalty), float(args.coverage_penalty))
                                                            combo_rows.append(aggregate)

    combo_rows.sort(key=lambda row: float(row["score"]))
    args.out_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(args.out_dir / "stage4_method_optimization.csv", combo_rows)
    _write_csv(args.out_dir / "stage4_method_optimization_detail.csv", detail_rows)
    _write_md(args.out_dir / "stage4_method_optimization.md", combo_rows, float(args.fill_penalty), float(args.coverage_penalty))
    (args.out_dir / "stage4_method_optimization_run.json").write_text(
        json.dumps(
            {
                "stage2_summary": str(args.stage2_summary),
                "stage3_summary": str(args.stage3_summary),
                "frame_times": [str(row["time_str"]) for row in stage2_rows],
                "qc_calibration": qc_calibration,
                "role_conflict_modes": role_conflict_modes,
                "conflict_speed_thresholds_mps": conflict_thresholds,
                "conflict_context_factors": conflict_factors,
                "fill_penalty": float(args.fill_penalty),
                "coverage_penalty": float(args.coverage_penalty),
                "note": "Small-grid optimization for candidate selection only; baseline default is unchanged.",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(args.out_dir / "stage4_method_optimization.csv")


if __name__ == "__main__":
    main()
