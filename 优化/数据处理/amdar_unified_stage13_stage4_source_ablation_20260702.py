#!/usr/bin/env python3
"""Run Stage13 source-level Stage4 support ablations.

This helper keeps the centralized_v1 Stage1/2/3/4 boundary intact. It reuses
the completed Stage12 Stage2/3 products, filters Stage2 `context_wind_records`
in memory inside Stage4 metrics-only evaluation, and writes compact Stage4
diagnostic outputs. It does not create a copied 25-slice Stage2 dataset.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np


ROOT = Path("/data/LFT-W02_data/pengxu")
DATA_DIR = ROOT / "优化/数据处理"
STAGE12_DIR = DATA_DIR / "amdar_unified_stage12_stage4_baseline_reproduction_optimized_20260702"
STAGE13_CONTEXT_DIR = DATA_DIR / "amdar_unified_stage13_stage4_context_tail_optimization_20260702"
DEFAULT_OUT_DIR = DATA_DIR / "amdar_unified_stage13_stage4_source_ablation_20260702"
STAGE2_SUMMARY = STAGE12_DIR / "stage2_baseline_compat_200/stage2_multimodal_summary.json"
STAGE3_SUMMARY = STAGE12_DIR / "stage3_baseline_compat_200/stage3_center_summary.json"
FRAME_TIMES = STAGE12_DIR / "stage12_frame_times_200.txt"
BASELINE_STAGE4_DIR = STAGE12_DIR / "stage4_baseline_unified_v1_200frames"
CONTEXT_BEST_STAGE4_DIR = STAGE13_CONTEXT_DIR / "experiments/G2_rep_soft_8x4_tail_v1"
TAIL_V1_CALIBRATION = STAGE13_CONTEXT_DIR / "calibration/stage13_context_tail_conservative_v1.json"


if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(DATA_DIR) not in sys.path:
    sys.path.insert(0, str(DATA_DIR))

from stage.centralized_v1.configs.centralized_v1_contract import C2_CONTEXT_WIND_RECORDS  # noqa: E402
from stage.centralized_v1.core import centralized_stage4_sensitivity as sens  # noqa: E402
import amdar_unified_stage13_stage4_context_tail_optimization_20260702 as prev_stage13  # noqa: E402


@dataclass(frozen=True)
class Experiment:
    name: str
    description: str
    policy: str


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


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
        return out if math.isfinite(out) else default
    except Exception:
        return default


def record_speed(row: dict[str, Any]) -> float:
    diag = row.get("wind_speed_diagnostic")
    if diag not in ("", None):
        return safe_float(diag)
    return math.hypot(safe_float(row.get("u")), safe_float(row.get("v")))


def is_amdar_context(row: dict[str, Any]) -> bool:
    return safe_float(row.get("amdar_rows")) > 0.0


def is_turb_context(row: dict[str, Any]) -> bool:
    return safe_float(row.get("turb_rows")) > 0.0


def scale_speed(row: dict[str, Any], cap_mps: float) -> dict[str, Any]:
    speed = record_speed(row)
    if speed <= cap_mps or speed <= 0.0:
        return row
    out = dict(row)
    factor = float(cap_mps) / speed
    out["u"] = safe_float(out.get("u")) * factor
    out["v"] = safe_float(out.get("v")) * factor
    out["wind_speed_diagnostic"] = float(cap_mps)
    out["stage13_source_ablation_transform"] = f"speed_cap_{cap_mps:g}mps"
    return out


def keep_context_record(row: dict[str, Any], policy: str) -> bool:
    amdar = is_amdar_context(row)
    turb = is_turb_context(row)
    speed = record_speed(row)
    time_conf = safe_float(row.get("time_conf"))
    obs_conf = safe_float(row.get("obs_conf"))
    grade = str(row.get("confidence_grade_mode", "")).upper()

    if policy == "no_filter":
        return True
    if policy == "no_amdar_support":
        return not amdar
    if policy == "drop_amdar_grade_cr":
        return (not amdar) or grade not in {"C", "R", "T3", "T4"}
    if policy == "drop_amdar_speed_gt60":
        return (not amdar) or speed <= 60.0
    if policy == "drop_amdar_speed_gt45":
        return (not amdar) or speed <= 45.0
    if policy == "drop_amdar_unreliable_or_speed_gt60":
        return (not amdar) or (speed <= 60.0 and time_conf >= 0.55 and obs_conf >= 0.25 and grade not in {"R", "T4"})
    if policy == "fresh_amdar_speed_le60_only":
        return (not amdar) or (speed <= 60.0 and time_conf >= 0.70 and obs_conf >= 0.25)
    if policy == "drop_context_speed_gt90_all":
        return speed <= 90.0 or turb
    if policy == "drop_context_speed_gt85_all":
        return speed <= 85.0 or turb
    if policy == "drop_context_speed_gt80_all":
        return speed <= 80.0 or turb
    if policy in {"drop_context_speed_gt90_cap_amdar_75", "drop_context_speed_gt90_cap_amdar_60"}:
        return speed <= 90.0 or turb
    if policy in {"cap_amdar_speed_75", "cap_amdar_speed_60", "cap_amdar_speed_45", "cap_context_speed_80_all"}:
        return True
    raise ValueError(f"Unknown context filter policy: {policy}")


def transform_context_record(row: dict[str, Any], policy: str) -> dict[str, Any]:
    if policy == "cap_context_speed_80_all" and not is_turb_context(row):
        return scale_speed(row, 80.0)
    if policy in {"cap_amdar_speed_75", "drop_context_speed_gt90_cap_amdar_75"} and is_amdar_context(row):
        return scale_speed(row, 75.0)
    if policy == "cap_amdar_speed_60" and is_amdar_context(row):
        return scale_speed(row, 60.0)
    if policy == "drop_context_speed_gt90_cap_amdar_60" and is_amdar_context(row):
        return scale_speed(row, 60.0)
    if policy == "cap_amdar_speed_45" and is_amdar_context(row):
        return scale_speed(row, 45.0)
    return row


def apply_context_policy(records: list[dict[str, Any]], policy: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    kept: list[dict[str, Any]] = []
    removed = 0
    removed_amdar = 0
    capped = 0
    original_amdar = 0
    original_turb = 0
    for row in records:
        amdar = is_amdar_context(row)
        turb = is_turb_context(row)
        original_amdar += int(amdar)
        original_turb += int(turb)
        if not keep_context_record(row, policy):
            removed += 1
            removed_amdar += int(amdar)
            continue
        out = transform_context_record(row, policy)
        capped += int(out is not row)
        kept.append(out)
    kept_amdar = sum(1 for row in kept if is_amdar_context(row))
    kept_turb = sum(1 for row in kept if is_turb_context(row))
    return kept, {
        "context_filter_policy": policy,
        "context_records_original": len(records),
        "context_records_kept": len(kept),
        "context_records_removed": removed,
        "context_amdar_records_original": original_amdar,
        "context_turb_records_original": original_turb,
        "context_amdar_records_kept": kept_amdar,
        "context_turb_records_kept": kept_turb,
        "context_amdar_records_removed": removed_amdar,
        "context_records_speed_capped": capped,
    }


def selected_rows() -> list[dict[str, Any]]:
    rows = read_json(STAGE2_SUMMARY)
    wanted = [line.strip() for line in FRAME_TIMES.read_text(encoding="utf-8").splitlines() if line.strip()]
    wanted_set = set(wanted)
    selected = [row for row in rows if str(row.get("time_str")) in wanted_set]
    found = {str(row.get("time_str")) for row in selected}
    missing = sorted(wanted_set - found)
    if missing:
        raise ValueError(f"Missing Stage2 rows for frame times: {missing[:10]}")
    return sorted(selected, key=lambda row: wanted.index(str(row["time_str"])))


def eval_kwargs(qc_calibration: dict[str, Any]) -> dict[str, Any]:
    return {
        "localization_kernel": "gaussian",
        "confidence_mode": "representation_error_soft_weighted",
        "holdout_fraction": 0.125,
        "holdout_count": 0,
        "localization_radius_xy": 8,
        "localization_radius_z": 2,
        "localization_sigma_xy": 4.0,
        "localization_sigma_z": 1.0,
        "refine_iters": 4,
        "pinn_smoothness_weight": 0.018,
        "pinn_divergence_weight": 0.010,
        "diffusion_weight": 0.22,
        "low_conf_fill_weight": 0.72,
        "source_preserve": 0.95,
        "physics_constraint_mode": "pydda_3dvar_proxy",
        "observation_anchor_weight": 0.10,
        "speed_limit_mps": 120.0,
        "localization_policy": "diagnostic_adaptive_v3",
        "localization_candidate_grid": "8:4,10:5",
        "vertical_risk_mode": "preserve_strong_layers",
        "vertical_gradient_preserve_weight": 0.12,
        "vertical_context_mismatch_damping": 0.35,
        "qc_calibration": qc_calibration,
        "current_weight_boost": 2.0,
        "context_weight_scale": 0.5,
        "context_time_conf_power": 2.6,
        "role_conflict_mode": "current_priority_adaptive",
        "conflict_speed_threshold_mps": 11.0,
        "conflict_context_factor": 0.25,
        "vertical_localization_policy": "support_adaptive",
    }


def evaluate_one(args: tuple[dict[str, Any], str, dict[str, Any]]) -> dict[str, Any]:
    stage2_row, policy, kwargs = args
    original_loader = sens._load_stage2_npz
    filter_stats: dict[str, Any] = {}

    def filtered_loader(path: Path) -> dict[str, Any]:
        loaded = original_loader(path)
        context_records = sens._records(loaded.get(C2_CONTEXT_WIND_RECORDS))
        filtered, stats = apply_context_policy(context_records, policy)
        loaded[C2_CONTEXT_WIND_RECORDS] = np.array(filtered, dtype=object)
        filter_stats.update(stats)
        return loaded

    sens._load_stage2_npz = filtered_loader
    try:
        result = sens._evaluate_metrics_only(stage2_row, **kwargs)
    finally:
        sens._load_stage2_npz = original_loader
    result.update(filter_stats)
    for point_row in result.get("_point_departure_rows", []):
        point_row.update(
            {
                "context_filter_policy": policy,
                "context_records_original": filter_stats.get("context_records_original", 0),
                "context_records_kept": filter_stats.get("context_records_kept", 0),
                "context_amdar_records_kept": filter_stats.get("context_amdar_records_kept", 0),
                "context_turb_records_kept": filter_stats.get("context_turb_records_kept", 0),
            }
        )
    return result


def stage4_complete(stage4_dir: Path) -> bool:
    return (
        (stage4_dir / "stage4_point_departures.csv").exists()
        and (stage4_dir / "stage4_localization_sensitivity_run.json").exists()
    )


def run_experiment(exp: Experiment, out_dir: Path, *, force: bool, num_workers: int) -> Path:
    stage4_dir = out_dir / "experiments" / exp.name
    if stage4_complete(stage4_dir) and not force:
        return stage4_dir
    stage4_dir.mkdir(parents=True, exist_ok=True)
    qc_calibration = read_json(TAIL_V1_CALIBRATION)
    qc_calibration["calibration_path"] = str(TAIL_V1_CALIBRATION)
    kwargs = eval_kwargs(qc_calibration)
    rows = selected_rows()
    tasks = [(row, exp.policy, kwargs) for row in rows]
    started = time.time()
    frame_rows: list[dict[str, Any]] = []
    total = len(tasks)
    done = 0
    print(f"[{exp.name}] start {total} frames policy={exp.policy} workers={num_workers}", flush=True)
    with ProcessPoolExecutor(max_workers=max(1, int(num_workers))) as pool:
        futures = [pool.submit(evaluate_one, task) for task in tasks]
        next_report = time.time() + 30.0
        for future in as_completed(futures):
            frame_rows.append(future.result())
            done += 1
            now = time.time()
            if now >= next_report or done == total:
                elapsed = now - started
                rate = done / elapsed if elapsed > 0 else 0.0
                eta = (total - done) / rate if rate > 0 else 0.0
                print(f"[{exp.name}] {done}/{total} frames elapsed={elapsed:.1f}s eta={eta:.1f}s", flush=True)
                next_report = now + 30.0
    frame_rows = sorted(frame_rows, key=lambda row: str(row.get("time_str", "")))
    point_rows = sens._split_point_departures(frame_rows)
    sens._annotate_point_departures(point_rows, frame_rows)
    sens._write_csv(stage4_dir / "stage4_localization_sensitivity.csv", frame_rows)
    sens._write_csv(stage4_dir / "stage4_point_departures.csv", point_rows)
    sens._write_md(stage4_dir / "stage4_localization_sensitivity.md", frame_rows)
    aggregate_rows = sens._aggregate_rows(frame_rows)
    sens._write_csv(stage4_dir / "stage4_localization_sensitivity_aggregate.csv", aggregate_rows)
    sens._write_aggregate_md(stage4_dir / "stage4_localization_sensitivity_aggregate.md", aggregate_rows)
    tail_outputs = sens._write_tail_diagnostics(stage4_dir / "tail_diagnostics", point_rows)
    filter_totals = {
        "context_records_original_sum": int(sum(safe_float(row.get("context_records_original")) for row in frame_rows)),
        "context_records_kept_sum": int(sum(safe_float(row.get("context_records_kept")) for row in frame_rows)),
        "context_records_removed_sum": int(sum(safe_float(row.get("context_records_removed")) for row in frame_rows)),
        "context_amdar_records_original_sum": int(sum(safe_float(row.get("context_amdar_records_original")) for row in frame_rows)),
        "context_amdar_records_kept_sum": int(sum(safe_float(row.get("context_amdar_records_kept")) for row in frame_rows)),
        "context_turb_records_kept_sum": int(sum(safe_float(row.get("context_turb_records_kept")) for row in frame_rows)),
        "context_records_speed_capped_sum": int(sum(safe_float(row.get("context_records_speed_capped")) for row in frame_rows)),
    }
    run_meta = {
        "experiment": exp.name,
        "description": exp.description,
        "context_filter_policy": exp.policy,
        "started_at_utc": datetime.fromtimestamp(started, tz=timezone.utc).isoformat(),
        "ended_at_utc": datetime.now(timezone.utc).isoformat(),
        "elapsed_seconds": time.time() - started,
        "frame_times": [str(row["time_str"]) for row in rows],
        "num_workers": int(num_workers),
        "polars_threads": int(os.environ.get("POLARS_MAX_THREADS", num_workers)),
        "space_saving": "Stage2 NPZ files are read once per evaluated frame and context_wind_records are filtered in memory; no copied Stage2 view.",
        "eval_kwargs": {k: v for k, v in kwargs.items() if k != "qc_calibration"},
        "qc_calibration": str(TAIL_V1_CALIBRATION),
        "filter_totals": filter_totals,
        "tail_outputs": tail_outputs,
    }
    write_json(stage4_dir / "stage4_localization_sensitivity_run.json", run_meta)
    return stage4_dir


def experiments() -> list[Experiment]:
    return [
        Experiment(
            "S1_true_no_amdar_support",
            "True no-AMDAR support ablation: remove every context wind voxel containing AMDAR support.",
            "no_amdar_support",
        ),
        Experiment(
            "S2_drop_amdar_grade_cr",
            "Remove AMDAR context voxels whose modal confidence grade is C/R.",
            "drop_amdar_grade_cr",
        ),
        Experiment(
            "S3_drop_amdar_speed_gt60",
            "Remove AMDAR context voxels faster than 60 m/s.",
            "drop_amdar_speed_gt60",
        ),
        Experiment(
            "S4_drop_amdar_speed_gt45",
            "Remove AMDAR context voxels faster than 45 m/s.",
            "drop_amdar_speed_gt45",
        ),
        Experiment(
            "S5_drop_amdar_unreliable_or_speed_gt60",
            "Keep AMDAR only if speed <=60 m/s, time_conf >=0.55, obs_conf >=0.25, and not R/T4.",
            "drop_amdar_unreliable_or_speed_gt60",
        ),
        Experiment(
            "S6_fresh_amdar_speed_le60_only",
            "Keep AMDAR only if speed <=60 m/s, time_conf >=0.70, and obs_conf >=0.25.",
            "fresh_amdar_speed_le60_only",
        ),
        Experiment(
            "S7_cap_amdar_speed_60",
            "Keep AMDAR but cap AMDAR support vector speed at 60 m/s before Stage4 accumulation.",
            "cap_amdar_speed_60",
        ),
        Experiment(
            "S8_cap_amdar_speed_45",
            "Keep AMDAR but cap AMDAR support vector speed at 45 m/s before Stage4 accumulation.",
            "cap_amdar_speed_45",
        ),
        Experiment(
            "S9_drop_context_speed_gt90_all",
            "Remove any non-TURB context support voxel faster than 90 m/s.",
            "drop_context_speed_gt90_all",
        ),
        Experiment(
            "S10_drop_context_speed_gt85_all",
            "Remove any non-TURB context support voxel faster than 85 m/s.",
            "drop_context_speed_gt85_all",
        ),
        Experiment(
            "S11_drop_context_speed_gt80_all",
            "Remove any non-TURB context support voxel faster than 80 m/s.",
            "drop_context_speed_gt80_all",
        ),
        Experiment(
            "S12_cap_amdar_speed_75",
            "Keep AMDAR but cap AMDAR support vector speed at 75 m/s.",
            "cap_amdar_speed_75",
        ),
        Experiment(
            "S13_cap_context_speed_80_all",
            "Keep all non-TURB context support but cap non-TURB support vector speed at 80 m/s.",
            "cap_context_speed_80_all",
        ),
        Experiment(
            "S14_drop_context_gt90_cap_amdar_75",
            "Drop non-TURB context support above 90 m/s, then cap remaining AMDAR support at 75 m/s.",
            "drop_context_speed_gt90_cap_amdar_75",
        ),
        Experiment(
            "S15_drop_context_gt90_cap_amdar_60",
            "Drop non-TURB context support above 90 m/s, then cap remaining AMDAR support at 60 m/s.",
            "drop_context_speed_gt90_cap_amdar_60",
        ),
    ]


def summarized_rows(out_dir: Path, exps: list[Experiment]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    reference = [
        prev_stage13.Experiment(
            "B0_stage12_existing",
            "Existing Stage12 strict-TURB baseline with AMDAR support context.",
            [],
        ),
        prev_stage13.Experiment(
            "G2_rep_soft_8x4_tail_v1",
            "Best Stage13 context-tail run before source ablation.",
            [],
        ),
    ]
    rows.extend(prev_stage13.summarize_point_rows(reference[0], BASELINE_STAGE4_DIR))
    rows.extend(prev_stage13.summarize_point_rows(reference[1], CONTEXT_BEST_STAGE4_DIR))
    for exp in exps:
        stage4_dir = out_dir / "experiments" / exp.name
        if not stage4_complete(stage4_dir):
            continue
        row = prev_stage13.summarize_point_rows(prev_stage13.Experiment(exp.name, exp.description, []), stage4_dir)[0]
        if row.get("point_rmse_vector") is None:
            continue
        run_meta_path = stage4_dir / "stage4_localization_sensitivity_run.json"
        if run_meta_path.exists():
            run_meta = read_json(run_meta_path)
            row.update(run_meta.get("filter_totals", {}))
            row["context_filter_policy"] = run_meta.get("context_filter_policy", exp.policy)
        rows.append(row)
    ranked = sorted(
        rows,
        key=lambda row: (
            row.get("point_rmse_vector") is None,
            row.get("point_rmse_vector") or 1e9,
            row.get("point_p95_vector") or 1e9,
            row.get("high_error_ge30_count") or 1e9,
        ),
    )
    return ranked


def write_markdown(out_dir: Path, rows: list[dict[str, Any]]) -> None:
    baseline = next(row for row in rows if row["experiment"] == "B0_stage12_existing")
    prior_best = next(row for row in rows if row["experiment"] == "G2_rep_soft_8x4_tail_v1")
    best = rows[0]
    b_rmse = float(baseline["point_rmse_vector"])
    best_rmse = float(best["point_rmse_vector"])
    prior_rmse = float(prior_best["point_rmse_vector"])
    best_improve = 100.0 * (b_rmse - best_rmse) / b_rmse
    prior_improve = 100.0 * (b_rmse - prior_rmse) / b_rmse
    verdict = "not_satisfactory"
    if best_rmse <= 18.0 and float(best.get("point_p95_vector") or 1e9) <= 45.0 and int(best.get("high_error_ge30_count") or 999) <= 6:
        verdict = "candidate_but_needs_independent_validation"
    lines = [
        "# Stage13 Stage4 Source-Ablation Results",
        "",
        "This is an AMDAR Unified Plan Stage13 ablation. It is not centralized_v1 large-framework Stage3 or Stage4 renaming. The run calls centralized_v1 Stage4 metrics-only on completed Stage12 Stage2/3 products, while filtering `context_wind_records` in memory.",
        "",
        "## Verdict",
        "",
        f"- Verdict: `{verdict}`",
        f"- Stage12 baseline RMSE / p95 / max: `{baseline['point_rmse_vector']:.6f}` / `{baseline['point_p95_vector']:.6f}` / `{baseline['point_max_vector']:.6f}` m/s",
        f"- Prior best after context-tail weighting: `{prior_best['experiment']}` RMSE `{prior_rmse:.6f}` m/s, improvement `{prior_improve:.2f}%`",
        f"- Best source-ablation config: `{best['experiment']}`",
        f"- Best RMSE / p95 / max: `{best_rmse:.6f}` / `{best['point_p95_vector']:.6f}` / `{best['point_max_vector']:.6f}` m/s",
        f"- Best RMSE improvement vs Stage12 baseline: `{best_improve:.2f}%`",
        f"- Best high-error >=30 m/s count: `{best['high_error_ge30_count']}`",
        "",
        "## Interpretation",
        "",
        "The first Stage13 context-tail run showed that Stage4 localization and representation-error weights alone do not remove the speed-amplitude tail. This source-ablation run tests the next more fundamental hypothesis: whether AMDAR support context is the driver of weak-truth false-strong predictions.",
        "",
        "Aircraft observations remain valuable support observations, but WMO aircraft-observation guidance, EMADDC/Mode-S QC work, and variational retrieval practice all support explicit QC, observation-error handling, and representativeness control before using high-density aircraft winds as reconstruction anchors.",
        "",
        "## Ranked Configs",
        "",
        "| rank | experiment | policy | points | RMSE | MAE | p95 | max | high>=30 | calm false strong | weak false strong | strong under | kept AMDAR | removed context | capped context | leakage | motion |",
        "| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    for idx, row in enumerate(rows, start=1):
        lines.append(
            f"| {idx} | `{row['experiment']}` | `{row.get('context_filter_policy', '')}` | {row['holdout_points']} | "
            f"{row['point_rmse_vector']:.6f} | {row['point_mae_vector']:.6f} | {row['point_p95_vector']:.6f} | "
            f"{row['point_max_vector']:.6f} | {row['high_error_ge30_count']} | "
            f"{row['calm_truth_le5_pred_ge30_count']} | {row['weak_truth_le10_pred_ge50_count']} | "
            f"{row['strong_truth_ge80_pred_le40_count']} | {row.get('context_amdar_records_kept_sum', '')} | "
            f"{row.get('context_records_removed_sum', '')} | {row.get('context_records_speed_capped_sum', '')} | "
            f"`{row['all_strict_holdout_no_leakage']}` | `{row['any_motion_used_as_wind']}` |"
        )
    lines.extend(
        [
            "",
            "## Stage Responsibilities",
            "",
            "- centralized_v1 Stage1: clean raw AMDAR/TURB/location/radar inputs, preserve provenance, strict truth flags, timing confidence, and support-only roles.",
            "- centralized_v1 Stage2: organize each radar frame into strict current `wind_records` and support/context `context_wind_records`; it is not reconstruction.",
            "- centralized_v1 Stage3: prepare Ground Center/radar background payloads for Stage4.",
            "- centralized_v1 Stage4: reconstruct the wind field and evaluate only withheld strict `wind_records` labels.",
            "- AMDAR Unified Plan Stage9/10/11/12/13 are internal plan phases. They must not be confused with the centralized_v1 large-framework Stage1/2/3/4.",
            "",
            "## Outputs",
            "",
            f"- Machine summary: `{out_dir / 'stage13_stage4_source_ablation_summary.json'}`",
            f"- Ranked CSV: `{out_dir / 'stage13_stage4_source_ablation_ranked.csv'}`",
            f"- Experiment dirs: `{out_dir / 'experiments'}`",
            f"- Logs/stdout: the run is process-pool based; per-experiment run metadata is under each experiment dir.",
        ]
    )
    (out_dir / "stage13_stage4_source_ablation_results_analysis_and_next_steps.md").write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )


def write_handover(out_dir: Path, rows: list[dict[str, Any]]) -> None:
    best = rows[0]
    lines = [
        "# Next Agent Handover: After Stage13 Stage4 Source Ablation",
        "",
        "You are continuing `/data/LFT-W02_data/pengxu` centralized_v1 3D horizontal wind reconstruction work. Keep the boundary clear: centralized_v1 Stage1/2/3/4 are the large framework; AMDAR Unified Plan Stage9/10/11/12/13 are internal optimization/ablation phases.",
        "",
        "## Must Read",
        "",
        f"1. `{STAGE12_DIR / 'stage12_baseline_reproduction_results_analysis_and_next_steps.md'}`",
        f"2. `{STAGE12_DIR / 'stage4_holdout_diagnostics_and_stage13_supplement/stage4_holdout_diagnostics_and_stage13_supplement.md'}`",
        f"3. `{STAGE13_CONTEXT_DIR / 'stage13_stage4_context_tail_optimization_results_analysis_and_next_steps.md'}`",
        f"4. `{out_dir / 'stage13_stage4_source_ablation_results_analysis_and_next_steps.md'}`",
        f"5. `{out_dir / 'stage13_stage4_source_ablation_summary.json'}`",
        "6. `/data/LFT-W02_data/pengxu/workflow/centralized_v1_docs/stage4_strict_holdout_logic_and_results.md`",
        "",
        "## Current Understanding",
        "",
        "- AMDAR batch/downlink timestamps are not point-time strict truth. AMDAR must stay out of `wind_records` and official holdout.",
        "- TURB T0/S is the current strict truth source after Stage11 compatibility rewriting.",
        "- Stage12 baseline is `B0_stage12_strict_TURB_truth_with_AMDAR_support_context`, not true no-AMDAR E0.",
        "- Stage13 context-tail tuning only improved RMSE by about 1.2% and did not fix the worst speed-amplitude tail.",
        "- This source-ablation run tests whether AMDAR support context itself is driving weak-truth false-strong predictions.",
        "",
        "## Latest Best Result",
        "",
        f"- Best config: `{best['experiment']}`",
        f"- RMSE / MAE / p95 / max: `{best['point_rmse_vector']:.6f}` / `{best['point_mae_vector']:.6f}` / `{best['point_p95_vector']:.6f}` / `{best['point_max_vector']:.6f}` m/s",
        f"- high-error >=30 m/s count: `{best['high_error_ge30_count']}`",
        f"- calm false-strong / weak false-strong / strong-under: `{best['calm_truth_le5_pred_ge30_count']}` / `{best['weak_truth_le10_pred_ge50_count']}` / `{best['strong_truth_ge80_pred_le40_count']}`",
        f"- strict no leakage: `{best['all_strict_holdout_no_leakage']}`",
        f"- motion used as wind: `{best['any_motion_used_as_wind']}`",
        "",
        "## Next Recommended Actions",
        "",
        "1. If the source-ablation best is still not satisfactory, stop blind Stage4 radius tuning and inspect the small set of repeated tail frames by source records before Stage2 aggregation.",
        "2. Build a source-aware Stage2 support product: AMDAR support should be super-obbed/thinned and gated by confidence grade, speed, time confidence, and representativeness before entering `context_wind_records`.",
        "3. Add a true `E0_no_AMDAR_support` baseline to every future report, alongside `B0_with_AMDAR_support_context`, so improvement is not measured against a contaminated baseline only.",
        "4. Keep 25-slice / `POLARS_MAX_THREADS=25`; avoid copying 25 full Stage2 datasets.",
        "",
        "## Suggested Opening Prompt",
        "",
        "```text",
        "I have read Stage12, Stage13 context-tail optimization, and Stage13 source-ablation outputs. I understand centralized_v1 Stage1/2/3/4 is separate from AMDAR Unified Plan stages. AMDAR remains support-only and never strict truth. The current failure mode is speed-amplitude tail error under context-only support, and the next step is source-aware Stage2 AMDAR support QC/super-ob/thinning plus true no-AMDAR baseline tracking.",
        "```",
    ]
    (out_dir / "next_agent_handover_after_stage13_stage4_source_ablation.md").write_text(
        "\n".join(lines) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Stage13 source-level Stage4 support ablation.")
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--num-workers", type=int, default=25)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--only", default="")
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)
    selected_exps = experiments()
    if args.only.strip():
        wanted = {name.strip() for name in args.only.split(",") if name.strip()}
        selected_exps = [exp for exp in selected_exps if exp.name in wanted]
        missing = wanted - {exp.name for exp in selected_exps}
        if missing:
            raise ValueError(f"Unknown experiments in --only: {sorted(missing)}")
    os.environ["POLARS_MAX_THREADS"] = str(int(args.num_workers))
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
    for exp in selected_exps:
        run_experiment(exp, args.out_dir, force=bool(args.force), num_workers=int(args.num_workers))
    all_exps = experiments()
    rows = summarized_rows(args.out_dir, all_exps)
    write_csv(args.out_dir / "stage13_stage4_source_ablation_ranked.csv", rows)
    summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "stage_boundary_note": "AMDAR Unified Plan Stage13 source ablation calling centralized_v1 Stage4 metrics-only.",
        "run_policy": {
            "polars_threads": int(args.num_workers),
            "num_workers": int(args.num_workers),
            "space_saving": "No copied Stage2 view; context_wind_records are filtered/capped in worker memory.",
        },
        "inputs": {
            "stage12_dir": str(STAGE12_DIR),
            "stage2_summary": str(STAGE2_SUMMARY),
            "stage3_summary": str(STAGE3_SUMMARY),
            "frame_times": str(FRAME_TIMES),
            "baseline_stage4_dir": str(BASELINE_STAGE4_DIR),
            "context_tail_best_stage4_dir": str(CONTEXT_BEST_STAGE4_DIR),
        },
        "ranked_configs": rows,
    }
    write_json(args.out_dir / "stage13_stage4_source_ablation_summary.json", summary)
    write_markdown(args.out_dir, rows)
    write_handover(args.out_dir, rows)
    print(
        json.dumps(
            {
                "out_dir": str(args.out_dir),
                "best_config": rows[0] if rows else None,
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
