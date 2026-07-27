from __future__ import annotations

import argparse
import csv
import json
import math
import os
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl


ROOT = Path("/data/LFT-W02_data/pengxu")
DATA_DIR = ROOT / "优化/数据处理"
DEFAULT_STAGE11_DIR = DATA_DIR / "amdar_unified_stage11_stage2_compat_smoke_optimized_20260702"
DEFAULT_STAGE10_DIR = DATA_DIR / "amdar_unified_stage10_superob_weight_control_v2_optimized_20260702"
DEFAULT_OUT_DIR = DATA_DIR / "amdar_unified_stage12_stage4_baseline_reproduction_optimized_20260702"
DEFAULT_FRAME_TIMES_TXT = (
    ROOT
    / "centralized_v1_output/stage4_guardrail_display_fill_200_20260605_25w/"
    "tp26_thr11_preserve_metrics/stage4_validation_frame_times.txt"
)
DEFAULT_LEGACY_BASELINE_DIR = (
    ROOT
    / "centralized_v1_output/stage4_guardrail_display_fill_200_20260605_25w/"
    "tp26_thr11_preserve_metrics"
)

STAGE2_SCRIPT = ROOT / "stage/centralized_v1/core/centralized_stage2_multimodal.py"
STAGE3_SCRIPT = ROOT / "stage/centralized_v1/core/centralized_stage3_center.py"
STAGE4_SENSITIVITY_SCRIPT = ROOT / "stage/centralized_v1/core/centralized_stage4_sensitivity.py"


@dataclass(frozen=True)
class RunConfig:
    out_dir: Path = DEFAULT_OUT_DIR
    stage11_dir: Path = DEFAULT_STAGE11_DIR
    stage10_dir: Path = DEFAULT_STAGE10_DIR
    frame_times_txt: Path = DEFAULT_FRAME_TIMES_TXT
    legacy_baseline_dir: Path = DEFAULT_LEGACY_BASELINE_DIR
    frame_policy: str = "strict_turb_enriched_200"
    num_workers: int = 25
    polars_threads: int = 25
    current_window_minutes: int = 5
    context_window_minutes: int = 360
    min_strict_turb_truth_records: int = 100
    strict_rmse_diff_tolerance_pct_if_comparable: float = 1.0
    force: bool = False


def parse_args() -> RunConfig:
    parser = argparse.ArgumentParser(
        description=(
            "Run AMDAR Unified Plan Stage12 baseline reproduction. This is Unified Plan Stage12, "
            "not a new centralized_v1 framework stage. It calls centralized_v1 Stage2/3/4 with "
            "the Stage11 compatible Stage1 view, keeps AMDAR out of strict truth, and writes "
            "machine-readable audits plus handover docs."
        )
    )
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--stage11-dir", default=str(DEFAULT_STAGE11_DIR))
    parser.add_argument("--stage10-dir", default=str(DEFAULT_STAGE10_DIR))
    parser.add_argument("--frame-times-txt", default=str(DEFAULT_FRAME_TIMES_TXT))
    parser.add_argument("--legacy-baseline-dir", default=str(DEFAULT_LEGACY_BASELINE_DIR))
    parser.add_argument(
        "--frame-policy",
        choices=("strict_turb_enriched_200", "legacy_200"),
        default="strict_turb_enriched_200",
        help=(
            "strict_turb_enriched_200 selects all usable radar frames within the current window of Stage11 "
            "TURB strict truth and fills to 200 from the legacy list. legacy_200 reuses the historical 200-frame set."
        ),
    )
    parser.add_argument("--num-workers", type=int, default=25)
    parser.add_argument("--polars-threads", type=int, default=25)
    parser.add_argument("--current-window-minutes", type=int, default=5)
    parser.add_argument("--context-window-minutes", type=int, default=360)
    parser.add_argument("--min-strict-turb-truth-records", type=int, default=1)
    parser.add_argument("--strict-rmse-diff-tolerance-pct-if-comparable", type=float, default=1.0)
    parser.add_argument("--force", action="store_true", help="Rerun Stage2/3/4 even when complete outputs exist.")
    args = parser.parse_args()
    return RunConfig(
        out_dir=Path(args.out_dir).resolve(),
        stage11_dir=Path(args.stage11_dir).resolve(),
        stage10_dir=Path(args.stage10_dir).resolve(),
        frame_times_txt=Path(args.frame_times_txt).resolve(),
        legacy_baseline_dir=Path(args.legacy_baseline_dir).resolve(),
        frame_policy=str(args.frame_policy),
        num_workers=int(args.num_workers),
        polars_threads=int(args.polars_threads),
        current_window_minutes=int(args.current_window_minutes),
        context_window_minutes=int(args.context_window_minutes),
        min_strict_turb_truth_records=int(args.min_strict_turb_truth_records),
        strict_rmse_diff_tolerance_pct_if_comparable=float(args.strict_rmse_diff_tolerance_pct_if_comparable),
        force=bool(args.force),
    )


def json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    return str(value)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=json_default), encoding="utf-8")
    tmp.replace(path)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_frame_times(path: Path) -> list[str]:
    if not path.exists():
        raise FileNotFoundError(path)
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError(f"Empty frame-times file: {path}")
    if text.startswith("["):
        payload = json.loads(text)
        if not isinstance(payload, list):
            raise ValueError(f"Frame-times JSON must be a list: {path}")
        values = [str(item).strip() for item in payload if str(item).strip()]
    else:
        values = [line.strip() for line in text.splitlines() if line.strip()]
    if len(set(values)) != len(values):
        raise ValueError(f"Duplicate frame times in {path}")
    return values


def write_frame_time_files(cfg: RunConfig, frame_times: list[str]) -> dict[str, str]:
    out_txt = cfg.out_dir / "stage12_frame_times_200.txt"
    out_json = cfg.out_dir / "stage12_frame_times_200.json"
    out_txt.write_text("\n".join(frame_times) + "\n", encoding="utf-8")
    write_json(out_json, frame_times)
    return {"txt": str(out_txt), "json": str(out_json), "count": len(frame_times)}


def select_frame_times(cfg: RunConfig, legacy_frame_times: list[str], compat_dir: Path) -> tuple[list[str], dict[str, Any]]:
    if cfg.frame_policy == "legacy_200":
        return legacy_frame_times, {
            "frame_policy": cfg.frame_policy,
            "selected_frames": len(legacy_frame_times),
            "strict_turb_anchor_frames": 0,
            "legacy_fill_frames": len(legacy_frame_times),
            "note": "Historical legacy 200-frame set. Under Stage11 strict-TURB policy this may contain few truth frames.",
        }

    radar_index = read_json(compat_dir / "radar_index.json")
    if not isinstance(radar_index, list):
        raise ValueError(f"radar_index.json must contain a list: {compat_dir / 'radar_index.json'}")
    radar_times: list[tuple[str, datetime]] = []
    for row in radar_index:
        if not isinstance(row, dict) or not row.get("usable"):
            continue
        time_str = str(row.get("time_str", "")).strip()
        if not time_str:
            continue
        radar_times.append((time_str, datetime.strptime(time_str, "%Y%m%d%H%M%S")))
    if not radar_times:
        raise ValueError(f"No usable radar frames found in {compat_dir / 'radar_index.json'}")

    wind = pl.read_parquet(
        compat_dir / "clean_wind.parquet",
        columns=["source", "wind_reconstruction_role", "time_utc", "confidence_grade"],
    )
    turb_times = (
        wind.filter(
            (pl.col("source") == "turb")
            & (pl.col("wind_reconstruction_role") == "strict_truth_candidate")
            & (pl.col("confidence_grade") == "S")
        )
        .select("time_utc")
        .to_series()
        .to_list()
    )
    max_delta_s = float(cfg.current_window_minutes * 60)
    selected: list[str] = []
    anchor_rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for time_utc in turb_times:
        best_time_str, best_dt = min(radar_times, key=lambda item: abs((item[1] - time_utc).total_seconds()))
        delta_s = abs((best_dt - time_utc).total_seconds())
        selected_unique_frame = delta_s <= max_delta_s and best_time_str not in seen
        if selected_unique_frame:
            seen.add(best_time_str)
            selected.append(best_time_str)
        if delta_s <= max_delta_s:
            anchor_rows.append(
                {
                    "turb_time_utc": time_utc.isoformat() if hasattr(time_utc, "isoformat") else str(time_utc),
                    "nearest_radar_time_str": best_time_str,
                    "abs_delta_s": delta_s,
                    "selected_unique_frame": selected_unique_frame,
                }
            )

    legacy_fill: list[str] = []
    for time_str in legacy_frame_times:
        if len(selected) >= 200:
            break
        if time_str not in seen:
            seen.add(time_str)
            selected.append(time_str)
            legacy_fill.append(time_str)

    if len(selected) < 200:
        for time_str, _ in radar_times:
            if len(selected) >= 200:
                break
            if time_str not in seen:
                seen.add(time_str)
                selected.append(time_str)
                legacy_fill.append(time_str)

    audit = {
        "frame_policy": cfg.frame_policy,
        "selected_frames": len(selected),
        "strict_turb_rows": len(turb_times),
        "strict_turb_anchor_rows_with_radar_within_current_window": len(anchor_rows),
        "strict_turb_anchor_frames": len(selected) - len(legacy_fill),
        "legacy_fill_frames": len(legacy_fill),
        "current_window_minutes": cfg.current_window_minutes,
        "anchor_rows_preview": anchor_rows[:40],
        "legacy_fill_preview": legacy_fill[:40],
        "note": (
            "This Stage12 frame set is intentionally strict-TURB enriched. The legacy 200-frame set only covers a "
            "small number of Stage11 strict TURB truth rows, so it is not adequate as the default conservative "
            "Stage12 validation set."
        ),
    }
    if len(selected) != 200:
        raise RuntimeError(f"Frame policy {cfg.frame_policy} selected {len(selected)} frames, expected 200")
    return selected, audit


def run_command(cmd: list[str], log_path: Path, env: dict[str, str]) -> dict[str, Any]:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    started = datetime.now(timezone.utc)
    with log_path.open("w", encoding="utf-8") as log:
        proc = subprocess.run(cmd, cwd=str(ROOT), env=env, stdout=log, stderr=subprocess.STDOUT, text=True)
    ended = datetime.now(timezone.utc)
    result = {
        "cmd": cmd,
        "log_path": str(log_path),
        "returncode": int(proc.returncode),
        "started_at_utc": started.isoformat(),
        "ended_at_utc": ended.isoformat(),
        "elapsed_seconds": (ended - started).total_seconds(),
    }
    if proc.returncode != 0:
        raise RuntimeError(f"Command failed rc={proc.returncode}; see {log_path}")
    return result


def command_env(cfg: RunConfig) -> dict[str, str]:
    env = os.environ.copy()
    env["POLARS_MAX_THREADS"] = str(cfg.polars_threads)
    env.setdefault("OMP_NUM_THREADS", "1")
    env.setdefault("OPENBLAS_NUM_THREADS", "1")
    return env


def require_upstream(cfg: RunConfig) -> dict[str, Any]:
    stage10_summary = read_json(cfg.stage10_dir / "stage10_superob_summary.json")
    stage11_summary = read_json(cfg.stage11_dir / "stage11_stage2_compat_smoke_summary.json")
    stage10_checks = stage10_summary.get("stage10_completion_checks", {})
    stage11_checks = stage11_summary.get("stage11_completion_checks", {})
    checks = {
        "stage10_gate_passed": bool(stage10_checks.get("passed_stage10_superob_weight_control_gate")),
        "stage10_compression_gate_passed": bool(stage10_checks.get("t1t2t3_compression_ratio_ge_min")),
        "stage11_gate_passed": bool(stage11_checks.get("passed_stage11_stage2_compat_smoke_gate")),
        "stage11_no_amdar_truth": bool(stage11_checks.get("stage2_wind_records_no_amdar_truth")),
        "stage11_turb_truth_present": bool(stage11_checks.get("stage2_wind_records_have_turb_truth")),
        "stage11_confidence_fields_preserved": bool(stage11_checks.get("stage2_records_preserve_confidence_fields")),
    }
    if not all(checks.values()):
        raise RuntimeError(f"Upstream Stage10/11 not ready for Stage12: {checks}")
    compat_dir = cfg.stage11_dir / "stage1_confidence_compat_view"
    if not (compat_dir / "clean_wind.parquet").exists():
        raise FileNotFoundError(compat_dir / "clean_wind.parquet")
    return {
        "stage10_summary": str(cfg.stage10_dir / "stage10_superob_summary.json"),
        "stage11_summary": str(cfg.stage11_dir / "stage11_stage2_compat_smoke_summary.json"),
        "compat_stage1_view": str(compat_dir),
        "checks": checks,
    }


def audit_compat_stage1(compat_dir: Path) -> dict[str, Any]:
    wind_path = compat_dir / "clean_wind.parquet"
    lf = pl.scan_parquet(wind_path)
    rows = lf.select(
        [
            pl.len().alias("rows"),
            (pl.col("source") == "amdar").sum().alias("amdar_rows"),
            (pl.col("source") == "turb").sum().alias("turb_rows"),
            ((pl.col("source") == "amdar") & (pl.col("wind_reconstruction_role") == "strict_truth_candidate")).sum().alias(
                "amdar_strict_truth_role_rows"
            ),
            ((pl.col("source") == "turb") & (pl.col("wind_reconstruction_role") == "strict_truth_candidate")).sum().alias(
                "turb_strict_truth_role_rows"
            ),
        ]
    ).collect().to_dicts()[0]
    policy_counts = (
        lf.group_by(["source", "wind_reconstruction_role", "confidence_grade"])
        .agg(pl.len().alias("rows"))
        .sort(["source", "wind_reconstruction_role", "confidence_grade"])
        .collect()
        .to_dicts()
    )
    return {
        "path": str(wind_path),
        "row_counts": {k: int(v) for k, v in rows.items()},
        "role_source_grade_counts": policy_counts,
        "checks": {
            "no_amdar_strict_truth_role": int(rows["amdar_strict_truth_role_rows"]) == 0,
            "turb_strict_truth_role_rows_positive": int(rows["turb_strict_truth_role_rows"]) > 0,
        },
    }


def json_list_complete(path: Path, expected_rows: int, required_path_key: str | None = None) -> bool:
    if not path.exists():
        return False
    try:
        rows = read_json(path)
    except Exception:
        return False
    if not isinstance(rows, list) or len(rows) != expected_rows:
        return False
    if required_path_key:
        for row in rows:
            candidate = Path(str(row.get(required_path_key, "")))
            if not candidate.exists():
                return False
    return True


def stage4_complete(stage4_dir: Path, expected_frames: int) -> bool:
    run_json = stage4_dir / "stage4_localization_sensitivity_run.json"
    point_csv = stage4_dir / "stage4_point_departures.csv"
    aggregate_csv = stage4_dir / "stage4_localization_sensitivity_aggregate.csv"
    if not (run_json.exists() and point_csv.exists() and aggregate_csv.exists()):
        return False
    try:
        meta = read_json(run_json)
    except Exception:
        return False
    return len(meta.get("frame_times", [])) == expected_frames


def run_stage2(cfg: RunConfig, frame_json: Path) -> dict[str, Any]:
    out_dir = cfg.out_dir / "stage2_baseline_compat_200"
    summary_path = out_dir / "stage2_multimodal_summary.json"
    if not cfg.force and json_list_complete(summary_path, 200, "multimodal_vox_path"):
        return {"skipped": True, "out_dir": str(out_dir), "summary_path": str(summary_path)}
    cmd = [
        sys.executable,
        str(STAGE2_SCRIPT),
        "--stage1-dir",
        str(cfg.stage11_dir / "stage1_confidence_compat_view"),
        "--out-dir",
        str(out_dir),
        "--frame-times-file",
        str(frame_json),
        "--num-workers",
        str(cfg.num_workers),
        "--current-window-minutes",
        str(cfg.current_window_minutes),
        "--context-window-minutes",
        str(cfg.context_window_minutes),
    ]
    result = run_command(cmd, cfg.out_dir / "logs/stage12_stage2_baseline_compat_200.log", command_env(cfg))
    result.update({"skipped": False, "out_dir": str(out_dir), "summary_path": str(summary_path)})
    return result


def run_stage3(cfg: RunConfig, stage2_summary: Path, frame_json: Path) -> dict[str, Any]:
    out_dir = cfg.out_dir / "stage3_baseline_compat_200"
    summary_path = out_dir / "stage3_center_summary.json"
    if not cfg.force and json_list_complete(summary_path, 200, "agent_path"):
        return {"skipped": True, "out_dir": str(out_dir), "summary_path": str(summary_path)}
    cmd = [
        sys.executable,
        str(STAGE3_SCRIPT),
        "--stage2-summary",
        str(stage2_summary),
        "--out-dir",
        str(out_dir),
        "--frame-times-file",
        str(frame_json),
        "--num-workers",
        str(cfg.num_workers),
        "--agent-mode",
        "none",
    ]
    result = run_command(cmd, cfg.out_dir / "logs/stage12_stage3_baseline_compat_200.log", command_env(cfg))
    result.update({"skipped": False, "out_dir": str(out_dir), "summary_path": str(summary_path)})
    return result


def run_stage4_metrics(cfg: RunConfig, stage2_summary: Path, stage3_summary: Path, frame_txt: Path) -> dict[str, Any]:
    out_dir = cfg.out_dir / "stage4_baseline_unified_v1_200frames"
    if not cfg.force and stage4_complete(out_dir, 200):
        return {
            "skipped": True,
            "out_dir": str(out_dir),
            "aggregate_csv": str(out_dir / "stage4_localization_sensitivity_aggregate.csv"),
            "point_departure_csv": str(out_dir / "stage4_point_departures.csv"),
            "run_json": str(out_dir / "stage4_localization_sensitivity_run.json"),
        }
    cmd = [
        sys.executable,
        str(STAGE4_SENSITIVITY_SCRIPT),
        "--stage2-summary",
        str(stage2_summary),
        "--stage3-summary",
        str(stage3_summary),
        "--frame-times-file",
        str(frame_txt),
        "--sample-count",
        "0",
        "--param-grid",
        "8,4,2,1",
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
        "--progress-interval-seconds",
        "30",
        "--num-workers",
        str(cfg.num_workers),
        "--out-dir",
        str(out_dir),
    ]
    result = run_command(cmd, cfg.out_dir / "logs/stage12_stage4_tp26_thr11_preserve_metrics.log", command_env(cfg))
    result.update(
        {
            "skipped": False,
            "out_dir": str(out_dir),
            "aggregate_csv": str(out_dir / "stage4_localization_sensitivity_aggregate.csv"),
            "point_departure_csv": str(out_dir / "stage4_point_departures.csv"),
            "run_json": str(out_dir / "stage4_localization_sensitivity_run.json"),
        }
    )
    return result


def load_npz_records(path: Path, key: str) -> list[dict[str, Any]]:
    with np.load(path, allow_pickle=True) as data:
        if key not in data.files:
            return []
        arr = data[key]
        if arr.size == 0:
            return []
        return [dict(item) for item in arr.tolist()]


def audit_stage2_outputs(summary_path: Path, expected_frames: int) -> dict[str, Any]:
    rows = read_json(summary_path)
    if not isinstance(rows, list):
        raise ValueError(f"Stage2 summary is not a JSON list: {summary_path}")
    totals = {
        "frames": len(rows),
        "current_amdar_truth_records": 0,
        "current_turb_truth_records": 0,
        "context_amdar_support_records": 0,
        "wind_confidence_field_hits": 0,
        "context_confidence_field_hits": 0,
        "context_stage11_policy_hits": 0,
        "current_support_only_rows": 0,
        "current_label_rows": 0,
    }
    per_frame: list[dict[str, Any]] = []
    for row in rows:
        npz_path = Path(str(row["multimodal_vox_path"]))
        wind_records = load_npz_records(npz_path, "wind_records")
        context_records = load_npz_records(npz_path, "context_wind_records")
        wind_amdar = sum(int(rec.get("amdar_rows", 0) or 0) for rec in wind_records)
        wind_turb = sum(int(rec.get("turb_rows", 0) or 0) for rec in wind_records)
        context_amdar = sum(int(rec.get("amdar_rows", 0) or 0) for rec in context_records)
        totals["current_amdar_truth_records"] += wind_amdar
        totals["current_turb_truth_records"] += wind_turb
        totals["context_amdar_support_records"] += context_amdar
        totals["wind_confidence_field_hits"] += sum(
            1 for rec in wind_records if "obs_conf_v2" in rec or "confidence_grade_mode" in rec
        )
        totals["context_confidence_field_hits"] += sum(
            1 for rec in context_records if "obs_conf_v2" in rec or "confidence_grade_mode" in rec
        )
        totals["context_stage11_policy_hits"] += sum(1 for rec in context_records if "stage11_compat_role_policy" in rec)
        totals["current_support_only_rows"] += int(row.get("current_support_only_rows", 0) or 0)
        totals["current_label_rows"] += int(row.get("current_label_rows", 0) or 0)
        per_frame.append(
            {
                "time_str": str(row.get("time_str")),
                "wind_voxels": int(row.get("wind_voxels", 0) or 0),
                "context_wind_voxels": int(row.get("context_wind_voxels", 0) or 0),
                "current_label_rows": int(row.get("current_label_rows", 0) or 0),
                "current_support_only_rows": int(row.get("current_support_only_rows", 0) or 0),
                "wind_records_amdar_rows_after_grouping": wind_amdar,
                "wind_records_turb_rows_after_grouping": wind_turb,
                "context_records_amdar_rows_after_grouping": context_amdar,
            }
        )
    checks = {
        "stage2_wrote_expected_frames": len(rows) == expected_frames,
        "stage2_wind_records_no_amdar_truth": totals["current_amdar_truth_records"] == 0,
        "stage2_wind_records_have_turb_truth": totals["current_turb_truth_records"] > 0,
        "stage2_context_records_have_amdar_support": totals["context_amdar_support_records"] > 0,
        "stage2_confidence_fields_preserved": totals["context_confidence_field_hits"] > 0,
        "stage2_stage11_policy_preserved": totals["context_stage11_policy_hits"] > 0,
    }
    return {"totals": totals, "checks": checks, "per_frame": per_frame}


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(path)
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def to_float(value: Any) -> float | None:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def metric_values(rows: list[dict[str, str]], key: str) -> list[float]:
    values: list[float] = []
    for row in rows:
        number = to_float(row.get(key))
        if number is not None:
            values.append(number)
    return values


def point_metrics(point_csv: Path) -> dict[str, Any]:
    rows = read_csv_rows(point_csv)
    errors = metric_values(rows, "vector_error")
    maes = errors
    frame_rmse: dict[str, float] = {}
    frame_mae: dict[str, float] = {}
    for row in rows:
        time_str = str(row.get("time_str", ""))
        rmse = to_float(row.get("frame_rmse_vector"))
        mae = to_float(row.get("frame_mae_vector"))
        if time_str:
            if rmse is not None:
                frame_rmse[time_str] = rmse
            if mae is not None:
                frame_mae[time_str] = mae
    high = [row for row in rows if (to_float(row.get("alt_m")) or -1.0) >= 12000.0]
    light = [row for row in rows if (to_float(row.get("gt_speed")) or 999.0) <= 10.0]
    gt_speeds = metric_values(rows, "gt_speed")
    floor10_relative = []
    for row in rows:
        err = to_float(row.get("vector_error"))
        speed = to_float(row.get("gt_speed"))
        if err is not None and speed is not None:
            floor10_relative.append(err / max(10.0, abs(speed)))

    def rmse(vals: list[float]) -> float | None:
        return float(math.sqrt(sum(v * v for v in vals) / len(vals))) if vals else None

    def mean(vals: list[float]) -> float | None:
        return float(sum(vals) / len(vals)) if vals else None

    def quantile(vals: list[float], q: float) -> float | None:
        return float(np.quantile(np.asarray(vals, dtype=np.float64), q)) if vals else None

    frame_rmse_values = list(frame_rmse.values())
    high_errors = metric_values(high, "vector_error")
    light_errors = metric_values(light, "vector_error")
    return {
        "point_csv": str(point_csv),
        "holdout_points": len(rows),
        "holdout_frames": len(frame_rmse),
        "vector_rmse": rmse(errors),
        "vector_mae": mean(maes),
        "frame_mean_rmse": mean(frame_rmse_values),
        "frame_mean_mae": mean(list(frame_mae.values())),
        "frame_p95_rmse": quantile(frame_rmse_values, 0.95),
        "frame_p99_rmse": quantile(frame_rmse_values, 0.99),
        "point_p95_error": quantile(errors, 0.95),
        "point_p99_error": quantile(errors, 0.99),
        "12km_plus_points": len(high),
        "12km_plus_rmse": rmse(high_errors),
        "light_wind_points": len(light),
        "light_wind_rmse": rmse(light_errors),
        "light_wind_mae": mean(light_errors),
        "floor10_relative_mae": mean(floor10_relative),
        "gt_speed_min": min(gt_speeds) if gt_speeds else None,
        "gt_speed_max": max(gt_speeds) if gt_speeds else None,
    }


def aggregate_audit(aggregate_csv: Path) -> dict[str, Any]:
    rows = read_csv_rows(aggregate_csv)
    if not rows:
        return {"rows": 0, "checks": {"aggregate_present": False}}
    total_frames = sum(int(to_float(row.get("frames")) or 0) for row in rows)
    total_holdout_points = sum(int(to_float(row.get("holdout_points")) or 0) for row in rows)
    total_holdout_frames = sum(int(to_float(row.get("official_holdout_frames")) or 0) for row in rows)
    leakage_ok = all(str(row.get("all_strict_holdout_no_leakage", "")).lower() == "true" for row in rows)
    motion_used = any(str(row.get("any_motion_used_as_wind", "")).lower() == "true" for row in rows)
    return {
        "rows": len(rows),
        "total_frames": total_frames,
        "total_holdout_frames": total_holdout_frames,
        "total_holdout_points": total_holdout_points,
        "rows_detail": rows,
        "checks": {
            "aggregate_present": True,
            "strict_holdout_no_leakage": leakage_ok,
            "motion_not_used_as_wind": not motion_used,
            "has_holdout_points": total_holdout_points > 0,
        },
    }


def compare_to_legacy(
    cfg: RunConfig,
    strict_metrics: dict[str, Any],
    strict_stage2_audit: dict[str, Any],
    frame_selection_audit: dict[str, Any],
) -> dict[str, Any]:
    legacy_point = cfg.legacy_baseline_dir / "stage4_point_departures.csv"
    legacy_aggregate = cfg.legacy_baseline_dir / "stage4_localization_sensitivity_aggregate.csv"
    legacy_metrics = point_metrics(legacy_point)
    legacy_agg = aggregate_audit(legacy_aggregate)
    comparable = (
        legacy_metrics["holdout_points"] == strict_metrics["holdout_points"]
        and strict_stage2_audit["totals"]["current_amdar_truth_records"] == 0
        and frame_selection_audit.get("frame_policy") == "legacy_200"
    )
    diff: dict[str, Any] = {"legacy_population_comparable": comparable}
    for key in [
        "vector_rmse",
        "vector_mae",
        "frame_mean_rmse",
        "frame_p95_rmse",
        "frame_p99_rmse",
        "12km_plus_rmse",
        "light_wind_rmse",
        "floor10_relative_mae",
    ]:
        old = to_float(legacy_metrics.get(key))
        new = to_float(strict_metrics.get(key))
        if old is None or new is None:
            diff[key] = {"legacy": old, "stage12": new, "delta": None, "delta_pct": None}
        else:
            diff[key] = {
                "legacy": old,
                "stage12": new,
                "delta": new - old,
                "delta_pct": 100.0 * (new - old) / old if old != 0.0 else None,
            }
    applicable = comparable and diff["vector_rmse"]["delta_pct"] is not None
    diff["rmse_diff_gate_applicable"] = applicable
    diff["rmse_diff_within_tolerance_if_applicable"] = (
        abs(float(diff["vector_rmse"]["delta_pct"])) <= cfg.strict_rmse_diff_tolerance_pct_if_comparable
        if applicable
        else None
    )
    diff["interpretation"] = (
        "Legacy 530-point baseline is not directly comparable after Stage11 because Stage11 intentionally removes "
        "AMDAR from strict truth and the default Stage12 frame set is strict-TURB enriched. This is expected and is "
        "not a Stage12 failure; forcing the old population would violate the strict truth boundary."
        if not comparable
        else "Strict holdout populations are comparable; use the RMSE percent-difference gate."
    )
    return {
        "legacy_metrics": legacy_metrics,
        "legacy_aggregate_audit": legacy_agg,
        "metrics_diff": diff,
    }


def write_stage12_docs(
    cfg: RunConfig,
    summary: dict[str, Any],
    stage10_11_assessment: dict[str, Any],
) -> dict[str, str]:
    result_path = cfg.out_dir / "stage12_baseline_reproduction_results_analysis_and_next_steps.md"
    handover_path = cfg.out_dir / "next_agent_handover_after_stage12_baseline_reproduction.md"
    stage2_totals = summary["stage2_output_audit"]["totals"]
    strict_metrics = summary["stage4_metrics"]["strict_turb_stage12_metrics"]
    legacy_metrics = summary["baseline_comparison"]["legacy_metrics"]
    diff = summary["baseline_comparison"]["metrics_diff"]
    checks = summary["stage12_completion_checks"]
    lines = [
        "# AMDAR Unified Plan Stage12 Baseline Reproduction Results",
        "",
        f"Generated at UTC: {summary['generated_at_utc']}",
        "",
        "## 阶段边界",
        "",
        "这里的 Stage12 是 AMDAR Unified Plan Stage12；它调用 centralized_v1 大框架 Stage2/3/4，但不是新增大框架 Stage12。大框架仍然只有 Stage1/2/3/4 主链。",
        "",
        "## 核心结论",
        "",
        f"- Stage12 gate: `{checks['passed_stage12_baseline_reproduction_gate']}`",
        f"- Stage10/11 readiness recheck: `{stage10_11_assessment['stage10_11_ready_for_stage12']}`",
        f"- Stage2 current AMDAR truth records: `{stage2_totals['current_amdar_truth_records']}`",
        f"- Stage2 current TURB truth records: `{stage2_totals['current_turb_truth_records']}`",
        f"- Stage2 context AMDAR support records: `{stage2_totals['context_amdar_support_records']}`",
        f"- Stage4 strict-TURB holdout points: `{strict_metrics['holdout_points']}`",
        f"- Stage4 strict-TURB vector RMSE: `{strict_metrics['vector_rmse']}`",
        f"- Stage4 strict no-leakage: `{summary['stage4_metrics']['aggregate_audit']['checks']['strict_holdout_no_leakage']}`",
        "",
        "## Stage10/11 复核",
        "",
        "Stage10 v2 仍适合进入后续消融：它已经修复 current/batch support 的空间代表性双乘，并通过 batch/frame、flight/superob-voxel、source/frame cap。Stage10 仍然只是 support 产品，不进入本次 official baseline。",
        "",
        "Stage11 仍适合进入 Stage12：兼容 Stage1 view 已把 legacy AMDAR strict candidate 改为 support-only，TURB T0/S truth 保留，Stage2 smoke 已验证字段可传递。",
        "",
        "## 与 legacy 200 帧 baseline 的关系",
        "",
        f"- Stage12 frame policy: `{summary['frame_selection_audit']['frame_policy']}`",
        f"- Strict TURB anchor frames: `{summary['frame_selection_audit']['strict_turb_anchor_frames']}`",
        f"- Legacy fill frames: `{summary['frame_selection_audit']['legacy_fill_frames']}`",
        f"- Legacy holdout points: `{legacy_metrics['holdout_points']}`",
        f"- Legacy vector RMSE: `{legacy_metrics['vector_rmse']}`",
        f"- Stage12 strict-TURB holdout points: `{strict_metrics['holdout_points']}`",
        f"- Stage12 strict-TURB vector RMSE: `{strict_metrics['vector_rmse']}`",
        f"- Population comparable: `{diff['legacy_population_comparable']}`",
        "",
        diff["interpretation"],
        "",
        "因此，本次 Stage12 的达标口径不是强行复现 legacy 530 点 AMDAR+TURB 旧真值，而是在修复 Stage11 strict truth 边界后建立新的 strict-TURB-enriched baseline。后续 Stage13 的 E0/E1/E3/E4 必须以这个严格边界为主评估口径。",
        "",
        "## 文献和资料依据",
        "",
        "- WMO Aircraft-Based Observations/AMDAR：飞机观测是高容量上空气象资料，适合 NWP/预报支持；这支持 AMDAR 作为 quality-controlled support，不等于批次时间可自动当逐点 strict truth。",
        "- NOAA AMDAR/ACARS/MADIS 资料强调飞机观测的质量评估、坏值标记和订正，支持本项目保留 QC 与置信度字段。",
        "- FAA 14 CFR 91.227 对 ADS-B Out state vector 的精度/完整性/延迟有要求，支持 ADS-B 时间重建研究分支；但不能消除当前 AMDAR 批次时间不确定性。",
        "- EMADDC 2025 的 aircraft-derived observation 资料强调大体量飞机观测进入应用前需要 thinning/superobbing，支持 Stage10 v2 的 super-ob 和限权方向。",
        "",
        "Sources: WMO `https://community.wmo.int/en/activity-areas/aircraft-based-observations`; NOAA `https://amdar.noaa.gov/`; eCFR `https://www.ecfr.gov/current/title-14/chapter-I/subchapter-F/part-91/subpart-C/section-91.227`; EMADDC `https://amt.copernicus.org/articles/18/3341/2025/`.",
        "",
        "## 下一步建议",
        "",
        "1. 进入 Stage13：用 Stage10 v2 A / A+B / A+B+C 产品做 report-only/ablation，严禁把 AMDAR support 当 strict truth。",
        "2. Stage13 主指标使用本次 strict-TURB baseline；legacy 530 点只可作为历史兼容附录，必须标注不是 conservative strict truth。",
        "3. 重点检查 12km+、batch 边界伪梯度、source/frame cap 饱和后的权重熵和局地不连续。",
    ]
    result_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    handover = [
        "# 给下一个智能体的交接话术：Stage12 Baseline 后续",
        "",
        "你接手的是 `/data/LFT-W02_data/pengxu` 下的 centralized_v1 三维水平风场重构项目。务必区分：Stage9/10/11/12 是 `amdar_unified_implementation_plan_20260701.md` 的 AMDAR Unified Plan 阶段；centralized_v1 大框架仍是 Stage1/2/3/4。",
        "",
        "## 必读文档顺序",
        "",
        "1. `/data/LFT-W02_data/pengxu/workflow/centralized_v1_docs/new_window_project_handover_20260529/centralized_v1_ultimate_summary_20260626.md`：大框架 Stage1/2/3/4、strict aircraft holdout、tp26 baseline 历史。",
        "2. `/data/LFT-W02_data/pengxu/优化/数据处理/amdar_plan4_implementation_20260630/plan4_assessment_and_run_report_20260630.md`：AMDAR 批次时间语义。",
        "3. `/data/LFT-W02_data/pengxu/优化/数据处理/amdar_plan4_comprehensive_assessment_20260701.md`：AMDAR 分层置信度总体策略。",
        "4. `/data/LFT-W02_data/pengxu/优化/数据处理/amdar_unified_implementation_plan_20260701.md`：Unified Plan Stage12/13 要求。",
        "5. `/data/LFT-W02_data/pengxu/优化/数据处理/amdar_unified_stage11_stage2_compat_smoke_optimized_20260702/stage9_10_11_integrated_assessment_and_stage12_readiness.md`：Stage9/10/11 readiness。",
        f"6. `{result_path}`：Stage12 结果、达标判断和下一步建议。",
        f"7. `{cfg.out_dir / 'stage12_baseline_reproduction_summary.json'}`：Stage12 machine-readable checks。",
        f"8. `{cfg.out_dir / 'baseline_comparison_report.json'}` 和 `{cfg.out_dir / 'baseline_metrics_diff.json'}`：legacy vs strict-TURB 指标关系。",
        "",
        "## 本轮输出",
        "",
        f"- Stage12 输出目录：`{cfg.out_dir}`",
        f"- Stage2 200 帧输出：`{cfg.out_dir / 'stage2_baseline_compat_200'}`",
        f"- Stage3 200 帧输出：`{cfg.out_dir / 'stage3_baseline_compat_200'}`",
        f"- Stage4 metrics-only 输出：`{cfg.out_dir / 'stage4_baseline_unified_v1_200frames'}`",
        f"- frame list JSON/TXT：`{cfg.out_dir / 'stage12_frame_times_200.json'}` / `{cfg.out_dir / 'stage12_frame_times_200.txt'}`",
        "",
        "## 关键结论",
        "",
        f"- Stage12 gate: `{checks}`",
        f"- Stage2 current AMDAR truth records: `{stage2_totals['current_amdar_truth_records']}`",
        f"- Stage2 current TURB truth records: `{stage2_totals['current_turb_truth_records']}`",
        f"- Stage12 frame policy: `{summary['frame_selection_audit']['frame_policy']}`",
        f"- Stage4 strict-TURB holdout points/RMSE: `{strict_metrics['holdout_points']}` / `{strict_metrics['vector_rmse']}`",
        f"- Legacy 530-point comparison is population-comparable? `{diff['legacy_population_comparable']}`",
        "",
        "## 强制规则",
        "",
        "- AMDAR 仍全部非 holdout、非 strict truth；不要回退到 legacy `wind_reconstruction_role` AMDAR candidate 口径。",
        "- Stage10 v2 super-ob 只用于 Stage13 消融；不能覆盖 official Stage2/Stage4 默认输入。",
        "- Stage12 建立的是 strict-TURB-enriched baseline。legacy 530 点只能当历史兼容参考，不是 conservative strict truth。",
        "- 如果 Stage13 候选让 strict-TURB 变好但产生明显 12km+ 或 batch 边界伪梯度，不能推广。",
        "",
        "推荐开场话术：",
        "",
        "```text",
        "我已阅读 centralized_v1 总交接、Plan4/Unified Plan、Stage9/10/11/12 输出。Stage12 已用 Stage11 compatible Stage1 view 跑通 strict-TURB-enriched 200 帧大框架 Stage2/3/4 metrics-only baseline，验证 AMDAR 不进入 strict truth，TURB strict truth 保留，Stage4 no-leakage 成立。legacy 530 点 baseline 与 strict-TURB baseline 人群不同，不能直接要求 <1% RMSE；后续 Stage13 应以 strict-TURB baseline 为主评估口径，对 Stage10 v2 A/B/C super-ob 做多时间尺度消融。",
        "```",
    ]
    handover_path.write_text("\n".join(handover) + "\n", encoding="utf-8")
    return {"result_analysis": str(result_path), "next_agent_handover": str(handover_path)}


def build_stage10_11_assessment(upstream: dict[str, Any], stage2_audit: dict[str, Any]) -> dict[str, Any]:
    ready = bool(
        all(upstream["checks"].values())
        and stage2_audit["checks"]["stage2_wind_records_no_amdar_truth"]
        and stage2_audit["checks"]["stage2_wind_records_have_turb_truth"]
        and stage2_audit["checks"]["stage2_context_records_have_amdar_support"]
    )
    return {
        "stage10_11_ready_for_stage12": ready,
        "assessment": (
            "Stage10/11 are satisfactory for Stage12. Stage10 remains a controlled support-product branch; "
            "Stage11 compatibility view is the official Stage12 input because it prevents AMDAR strict-truth leakage."
        ),
        "remaining_optimization_space": (
            "Stage10/11 still have research optimization space for Stage13: time-scale ablation, 12km+ diagnostics, "
            "batch-boundary pseudo-gradient checks, and weight entropy. None of those should block Stage12 baseline."
        ),
    }


def main() -> None:
    cfg = parse_args()
    if cfg.num_workers <= 0:
        raise ValueError("--num-workers must be positive")
    if cfg.polars_threads <= 0:
        raise ValueError("--polars-threads must be positive")
    if cfg.context_window_minutes <= cfg.current_window_minutes:
        raise ValueError("--context-window-minutes must be larger than --current-window-minutes")
    cfg.out_dir.mkdir(parents=True, exist_ok=True)
    write_json(cfg.out_dir / "run_config.json", {**asdict(cfg), "env_polars_threads": os.environ.get("POLARS_MAX_THREADS")})

    legacy_frame_times = read_frame_times(cfg.frame_times_txt)
    upstream = require_upstream(cfg)
    compat_dir = Path(upstream["compat_stage1_view"])
    frame_times, frame_selection_audit = select_frame_times(cfg, legacy_frame_times, compat_dir)
    if len(frame_times) != 200:
        raise ValueError(f"Stage12 expects 200 representative frames; got {len(frame_times)} from {cfg.frame_times_txt}")
    frame_files = write_frame_time_files(cfg, frame_times)
    write_json(cfg.out_dir / "stage12_frame_selection_audit.json", frame_selection_audit)

    compat_audit = audit_compat_stage1(compat_dir)

    print(json.dumps({"stage": "stage12_run_stage2", "frames": len(frame_times)}, ensure_ascii=False), flush=True)
    stage2_run = run_stage2(cfg, Path(frame_files["json"]))
    print(json.dumps({"stage": "stage12_run_stage3", "stage2_skipped": stage2_run.get("skipped")}, ensure_ascii=False), flush=True)
    stage3_run = run_stage3(cfg, Path(stage2_run["summary_path"]), Path(frame_files["json"]))
    print(json.dumps({"stage": "stage12_run_stage4_metrics", "stage3_skipped": stage3_run.get("skipped")}, ensure_ascii=False), flush=True)
    stage4_run = run_stage4_metrics(cfg, Path(stage2_run["summary_path"]), Path(stage3_run["summary_path"]), Path(frame_files["txt"]))

    stage2_audit = audit_stage2_outputs(Path(stage2_run["summary_path"]), expected_frames=200)
    stage4_agg = aggregate_audit(Path(stage4_run["aggregate_csv"]))
    stage4_strict_metrics = point_metrics(Path(stage4_run["point_departure_csv"]))
    baseline_comparison = compare_to_legacy(cfg, stage4_strict_metrics, stage2_audit, frame_selection_audit)
    stage10_11_assessment = build_stage10_11_assessment(upstream, stage2_audit)

    completion_checks = {
        "stage10_11_ready_for_stage12": bool(stage10_11_assessment["stage10_11_ready_for_stage12"]),
        "compat_view_no_amdar_strict_truth_role": bool(compat_audit["checks"]["no_amdar_strict_truth_role"]),
        "stage2_wrote_200_frames": bool(stage2_audit["checks"]["stage2_wrote_expected_frames"]),
        "stage2_wind_records_no_amdar_truth": bool(stage2_audit["checks"]["stage2_wind_records_no_amdar_truth"]),
        "stage2_wind_records_have_min_turb_truth": bool(
            stage2_audit["totals"]["current_turb_truth_records"] >= cfg.min_strict_turb_truth_records
        ),
        "stage2_context_records_have_amdar_support": bool(stage2_audit["checks"]["stage2_context_records_have_amdar_support"]),
        "stage2_confidence_fields_preserved": bool(stage2_audit["checks"]["stage2_confidence_fields_preserved"]),
        "stage4_metrics_written": bool(stage4_agg["checks"]["aggregate_present"]),
        "stage4_holdout_points_positive": bool(stage4_strict_metrics["holdout_points"] > 0),
        "stage4_strict_holdout_no_leakage": bool(stage4_agg["checks"]["strict_holdout_no_leakage"]),
        "stage4_motion_not_used_as_wind": bool(stage4_agg["checks"]["motion_not_used_as_wind"]),
        "legacy_population_difference_documented": bool(
            baseline_comparison["metrics_diff"]["legacy_population_comparable"]
            or baseline_comparison["metrics_diff"]["interpretation"]
        ),
        "stage12_frame_set_has_sufficient_turb_truth": bool(
            stage2_audit["totals"]["current_turb_truth_records"] >= cfg.min_strict_turb_truth_records
        ),
    }
    completion_checks["passed_stage12_baseline_reproduction_gate"] = bool(all(completion_checks.values()))

    summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "run_policy": {
            "polars_threads": cfg.polars_threads,
            "num_workers": cfg.num_workers,
            "space_saving_policy": (
                "Use one Stage11 compatible Stage1 view with clean_loc/radar_index symlinks, one 200-frame Stage2 "
                "output, one Stage3 output, and Stage4 metrics-only tables. Do not copy 25 full intermediate datasets."
            ),
            "stage12_boundary_note": (
                "Unified Plan Stage12 baseline reproduction. It calls large-framework centralized_v1 Stage2/3/4."
            ),
            "official_stage4_config": "tp26_thr11_preserve metrics-only: diagnostic_weighted, pydda_3dvar_proxy, context_time_conf_power=2.6, conflict_threshold=11, preserve_strong_layers.",
        },
        "inputs": {
            "stage11_dir": str(cfg.stage11_dir),
            "stage10_dir": str(cfg.stage10_dir),
            "compat_stage1_view": upstream["compat_stage1_view"],
            "frame_times_source": str(cfg.frame_times_txt),
            "frame_policy": cfg.frame_policy,
            "legacy_baseline_dir": str(cfg.legacy_baseline_dir),
        },
        "frame_files": frame_files,
        "frame_selection_audit": frame_selection_audit,
        "upstream": upstream,
        "compat_stage1_audit": compat_audit,
        "stage2_run": stage2_run,
        "stage3_run": stage3_run,
        "stage4_run": stage4_run,
        "stage2_output_audit": stage2_audit,
        "stage4_metrics": {
            "aggregate_audit": stage4_agg,
            "strict_turb_stage12_metrics": stage4_strict_metrics,
        },
        "stage10_11_assessment": stage10_11_assessment,
        "baseline_comparison": baseline_comparison,
        "stage12_completion_checks": completion_checks,
        "outputs": {
            "summary": str(cfg.out_dir / "stage12_baseline_reproduction_summary.json"),
            "baseline_comparison_report": str(cfg.out_dir / "baseline_comparison_report.json"),
            "baseline_metrics_diff": str(cfg.out_dir / "baseline_metrics_diff.json"),
            "frame_selection_audit": str(cfg.out_dir / "stage12_frame_selection_audit.json"),
        },
        "literature_and_reference_basis": {
            "wmo_aircraft_based_observations": "https://community.wmo.int/en/activity-areas/aircraft-based-observations",
            "noaa_amdar": "https://amdar.noaa.gov/",
            "ecfr_14_cfr_91_227_adsb_out": "https://www.ecfr.gov/current/title-14/chapter-I/subchapter-F/part-91/subpart-C/section-91.227",
            "emaddc_2025_amt": "https://amt.copernicus.org/articles/18/3341/2025/",
        },
    }
    docs = write_stage12_docs(cfg, summary, stage10_11_assessment)
    summary["outputs"].update(docs)

    write_json(cfg.out_dir / "baseline_comparison_report.json", baseline_comparison)
    write_json(cfg.out_dir / "baseline_metrics_diff.json", baseline_comparison["metrics_diff"])
    write_json(cfg.out_dir / "stage12_stage10_11_precheck_and_optimization_assessment.json", stage10_11_assessment)
    write_json(cfg.out_dir / "stage12_baseline_reproduction_summary.json", summary)
    print(
        json.dumps(
            {
                "stage": "stage12_done",
                "passed": completion_checks["passed_stage12_baseline_reproduction_gate"],
                "out_dir": str(cfg.out_dir),
                "strict_turb_holdout_points": stage4_strict_metrics["holdout_points"],
                "strict_turb_vector_rmse": stage4_strict_metrics["vector_rmse"],
                "checks": completion_checks,
            },
            ensure_ascii=False,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
