"""Narrow 25-worker grid refinement around the current best Stage4 candidate."""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[3]
STAGE_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
if str(STAGE_DIR) not in sys.path:
    sys.path.insert(0, str(STAGE_DIR))

DEFAULT_PYTHON = Path("/data/LFT-W02_data/pengxu/.conda/envs/windy310/bin/python")
DEFAULT_BEST_JSON = Path(
    "/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_error_resolution_refine_20260602_25w/reports/best_refined_candidate.json"
)
DEFAULT_OUT_ROOT = Path("/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_error_resolution_narrow_grid_20260602_25w")

SENSITIVITY_SCRIPT = ROOT_DIR / "stage/centralized_v1/core/centralized_stage4_sensitivity.py"
PAIRWISE_SCRIPT = ROOT_DIR / "stage/centralized_v1/core/centralized_stage4_pairwise_frame_compare.py"
DECOMPOSITION_SCRIPT = ROOT_DIR / "stage/centralized_v1/core/centralized_stage4_error_source_decomposition.py"
PYTHON_EXE = DEFAULT_PYTHON


@dataclass(frozen=True)
class CandidateSpec:
    slug: str
    context_time_conf_power: float
    conflict_speed_threshold_mps: float


def _default_env() -> dict[str, str]:
    env = dict(os.environ)
    env.setdefault("POLARS_MAX_THREADS", "1")
    env.setdefault("OMP_NUM_THREADS", "1")
    env.setdefault("OPENBLAS_NUM_THREADS", "1")
    return env


def _read_csv_rows(path: Path) -> list[dict[str, Any]]:
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


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _to_float(row: dict[str, Any], key: str, default: float = 0.0) -> float:
    try:
        return float(row.get(key, default))
    except (TypeError, ValueError):
        return float(default)


def _load_best_candidate(path: Path) -> tuple[str, Path, dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return str(payload["best_label"]), Path(payload["metrics_dir"]), dict(payload["args"])


def _build_cli(script: Path, args_map: dict[str, Any], out_dir: Path) -> list[str]:
    cmd = [str(PYTHON_EXE), str(script)]
    ordered = dict(args_map)
    ordered["out-dir"] = out_dir
    for key, value in ordered.items():
        if value is None:
            continue
        cmd.extend([f"--{key}", str(value)])
    return cmd


def _run_logged(cmd: list[str], log_path: Path) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as log:
        subprocess.run(cmd, cwd=str(ROOT_DIR), env=_default_env(), stdout=log, stderr=subprocess.STDOUT, check=True, text=True)


def _run_metrics(label: str, args_map: dict[str, Any], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = _build_cli(SENSITIVITY_SCRIPT, args_map, out_dir)
    _run_logged(cmd, out_dir / f"{label}_run.log")
    _write_json(out_dir / f"{label}_command.json", {"cmd": cmd, "args": {k: str(v) for k, v in dict(args_map, **{"out-dir": out_dir}).items()}})


def _run_pairwise(
    *,
    baseline_label: str,
    baseline_dir: Path,
    candidate_label: str,
    candidate_dir: Path,
    out_dir: Path,
    prefix: str,
) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    pairwise_cmd = [
        str(PYTHON_EXE),
        str(PAIRWISE_SCRIPT),
        "--baseline-csv",
        str(baseline_dir / "stage4_localization_sensitivity.csv"),
        "--candidate-csv",
        str(candidate_dir / "stage4_localization_sensitivity.csv"),
        "--baseline-point-csv",
        str(baseline_dir / "stage4_point_departures.csv"),
        "--candidate-point-csv",
        str(candidate_dir / "stage4_point_departures.csv"),
        "--baseline-label",
        baseline_label,
        "--candidate-label",
        candidate_label,
        "--out-dir",
        str(out_dir),
        "--out-prefix",
        prefix,
        "--top-n",
        "30",
    ]
    _run_logged(pairwise_cmd, out_dir / f"{prefix}_pairwise.log")

    decomp_dir = out_dir / "error_source_decomposition"
    decomp_dir.mkdir(parents=True, exist_ok=True)
    decomp_cmd = [
        str(PYTHON_EXE),
        str(DECOMPOSITION_SCRIPT),
        "--baseline-csv",
        str(baseline_dir / "stage4_localization_sensitivity.csv"),
        "--candidate-csv",
        str(candidate_dir / "stage4_localization_sensitivity.csv"),
        "--baseline-point-csv",
        str(baseline_dir / "stage4_point_departures.csv"),
        "--candidate-point-csv",
        str(candidate_dir / "stage4_point_departures.csv"),
        "--baseline-label",
        baseline_label,
        "--candidate-label",
        candidate_label,
        "--out-dir",
        str(decomp_dir),
        "--out-prefix",
        f"{prefix}_error_sources",
        "--top-tail-n",
        "50",
    ]
    _run_logged(decomp_cmd, decomp_dir / f"{prefix}_error_sources.log")
    return {
        "summary_csv": out_dir / f"{prefix}_summary.csv",
        "band_csv": out_dir / f"{prefix}_baseline_rmse_bands.csv",
        "paper_height_csv": out_dir / f"{prefix}_paper_height_bins.csv",
        "source_priority_csv": decomp_dir / f"{prefix}_error_sources_source_priority.csv",
        "markdown": out_dir / f"{prefix}.md",
    }


def _band_row(path: Path, group: str) -> dict[str, Any]:
    for row in _read_csv_rows(path):
        if str(row.get("group", "")) == group:
            return row
    return {}


def _height_row(path: Path, group: str, method: str) -> dict[str, Any]:
    for row in _read_csv_rows(path):
        if str(row.get("group", "")) == group and str(row.get("method", "")) == method:
            return row
    return {}


def _priority_score(path: Path, source: str) -> float:
    for row in _read_csv_rows(path):
        if str(row.get("source", "")) == source:
            return _to_float(row, "priority_score", float("nan"))
    return float("nan")


def _score_candidate(
    *,
    baseline_label: str,
    candidate_label: str,
    compare_paths: dict[str, Path],
    context_time_conf_power: float,
    conflict_speed_threshold_mps: float,
) -> dict[str, Any]:
    summary = _read_csv_rows(compare_paths["summary_csv"])[0]
    low_band = _band_row(compare_paths["band_csv"], "baseline_rmse_le6")
    mid_band = _band_row(compare_paths["band_csv"], "baseline_rmse_10_20")
    high_band = _band_row(compare_paths["band_csv"], "baseline_rmse_gt20")
    base_12km = _height_row(compare_paths["paper_height_csv"], "12km+", baseline_label)
    cand_12km = _height_row(compare_paths["paper_height_csv"], "12km+", candidate_label)
    tail_score = _priority_score(compare_paths["source_priority_csv"], "tail_qc")

    baseline_weighted = _to_float(summary, f"{baseline_label}_weighted_rmse", float("inf"))
    candidate_weighted = _to_float(summary, f"{candidate_label}_weighted_rmse", float("inf"))
    baseline_frame = _to_float(summary, f"{baseline_label}_frame_mean_rmse", float("inf"))
    candidate_frame = _to_float(summary, f"{candidate_label}_frame_mean_rmse", float("inf"))
    baseline_weighted_mae = _to_float(summary, f"{baseline_label}_weighted_mae", float("inf"))
    candidate_weighted_mae = _to_float(summary, f"{candidate_label}_weighted_mae", float("inf"))
    baseline_p95 = _to_float(summary, "p95_baseline_rmse", float("inf"))
    candidate_p95 = _to_float(summary, "p95_candidate_rmse", float("inf"))
    baseline_p99 = _to_float(summary, "p99_baseline_rmse", float("inf"))
    candidate_p99 = _to_float(summary, "p99_candidate_rmse", float("inf"))
    baseline_max = _to_float(summary, "max_baseline_rmse", float("inf"))
    candidate_max = _to_float(summary, "max_candidate_rmse", float("inf"))
    low_band_delta = _to_float(low_band, f"{candidate_label}_frame_mean_rmse", float("inf")) - _to_float(low_band, f"{baseline_label}_frame_mean_rmse", float("inf"))
    mid_band_delta = _to_float(mid_band, f"{candidate_label}_frame_mean_rmse", float("inf")) - _to_float(mid_band, f"{baseline_label}_frame_mean_rmse", float("inf"))
    high_band_delta = _to_float(high_band, f"{candidate_label}_frame_mean_rmse", float("inf")) - _to_float(high_band, f"{baseline_label}_frame_mean_rmse", float("inf"))
    delta_12km = _to_float(cand_12km, "vector_rmse_mps", float("inf")) - _to_float(base_12km, "vector_rmse_mps", float("inf"))
    leakage_ok = str(summary.get("all_strict_holdout_no_leakage", "False")) == "True"
    motion_ok = str(summary.get("any_motion_used_as_wind", "True")) == "False"

    passes = (
        leakage_ok
        and motion_ok
        and candidate_weighted <= baseline_weighted
        and candidate_weighted_mae <= baseline_weighted_mae + 0.02
        and low_band_delta <= 0.05
        and candidate_p99 <= baseline_p99 + 0.10
        and delta_12km <= 0.20
    )
    score = (
        (baseline_weighted - candidate_weighted) * 1000.0
        + (baseline_p99 - candidate_p99) * 0.6
        + (baseline_frame - candidate_frame) * 100.0
        - max(0.0, low_band_delta) * 10.0
    )
    return {
        "candidate_label": candidate_label,
        "context_time_conf_power": context_time_conf_power,
        "conflict_speed_threshold_mps": conflict_speed_threshold_mps,
        "baseline_weighted_rmse": baseline_weighted,
        "candidate_weighted_rmse": candidate_weighted,
        "delta_weighted_rmse": candidate_weighted - baseline_weighted,
        "baseline_frame_rmse": baseline_frame,
        "candidate_frame_rmse": candidate_frame,
        "delta_frame_rmse": candidate_frame - baseline_frame,
        "baseline_weighted_mae": baseline_weighted_mae,
        "candidate_weighted_mae": candidate_weighted_mae,
        "delta_weighted_mae": candidate_weighted_mae - baseline_weighted_mae,
        "baseline_p95": baseline_p95,
        "candidate_p95": candidate_p95,
        "delta_p95": candidate_p95 - baseline_p95,
        "baseline_p99": baseline_p99,
        "candidate_p99": candidate_p99,
        "delta_p99": candidate_p99 - baseline_p99,
        "baseline_max": baseline_max,
        "candidate_max": candidate_max,
        "delta_max": candidate_max - baseline_max,
        "low_band_delta": low_band_delta,
        "mid_band_delta": mid_band_delta,
        "high_band_delta": high_band_delta,
        "delta_12km_vector_rmse": delta_12km,
        "tail_priority_score": tail_score,
        "passes_guardrail": bool(passes),
        "selection_score": float(score),
        "compare_markdown": str(compare_paths["markdown"]),
    }


def _candidate_grid() -> list[CandidateSpec]:
    out: list[CandidateSpec] = []
    for power in (2.2, 2.3, 2.4):
        for threshold in (11.0, 12.0, 13.0):
            slug = f"tp{str(power).replace('.', '')}_thr{int(threshold)}_preserve"
            out.append(
                CandidateSpec(
                    slug=slug,
                    context_time_conf_power=power,
                    conflict_speed_threshold_mps=threshold,
                )
            )
    return out


def _write_markdown(path: Path, baseline_label: str, rows: list[dict[str, Any]], best_row: dict[str, Any] | None) -> None:
    lines = [
        "# Stage4 Narrow Grid Refinement",
        "",
        f"Baseline candidate: `{baseline_label}`",
        "",
        "| candidate | pass | time power | threshold | weighted RMSE delta | frame RMSE delta | weighted MAE delta | low-band delta | 10-20 band delta | 12km+ delta | P99 delta |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in rows:
        lines.append(
            f"| `{row['candidate_label']}` | `{row['passes_guardrail']}` | {row['context_time_conf_power']:.1f} | "
            f"{row['conflict_speed_threshold_mps']:.0f} | {row['delta_weighted_rmse']:.6f} | {row['delta_frame_rmse']:.6f} | "
            f"{row['delta_weighted_mae']:.6f} | {row['low_band_delta']:.6f} | {row['mid_band_delta']:.6f} | "
            f"{row['delta_12km_vector_rmse']:.6f} | {row['delta_p99']:.6f} |"
        )
    if best_row:
        lines.extend(
            [
                "",
                f"Selected best candidate: `{best_row['candidate_label']}`",
                f"- weighted RMSE: `{best_row['baseline_weighted_rmse']:.6f} -> {best_row['candidate_weighted_rmse']:.6f}`",
                f"- frame RMSE: `{best_row['baseline_frame_rmse']:.6f} -> {best_row['candidate_frame_rmse']:.6f}`",
                f"- weighted MAE: `{best_row['baseline_weighted_mae']:.6f} -> {best_row['candidate_weighted_mae']:.6f}`",
                f"- P99: `{best_row['baseline_p99']:.6f} -> {best_row['candidate_p99']:.6f}`",
            ]
        )
    else:
        lines.extend(["", "No narrow-grid candidate beat the baseline under the guardrail."])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_full_run_script(path: Path, args_map: dict[str, Any], best_label: str) -> None:
    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        "",
        "ROOT=/data/LFT-W02_data/pengxu",
        "PY=$ROOT/.conda/envs/windy310/bin/python",
        f"OUT=$ROOT/centralized_v1_output/stage4_full_{best_label}_25w_$(date +%Y%m%d_%H%M%S)",
        "",
        "POLARS_MAX_THREADS=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 \\",
        "  $PY $ROOT/stage/centralized_v1/core/centralized_stage4_sensitivity.py \\",
    ]
    ordered_keys = [
        "stage2-summary",
        "stage3-summary",
        "frame-times",
        "sample-count",
        "param-grid",
        "kernels",
        "confidence-mode",
        "qc-calibration",
        "physics-constraint-mode",
        "current-weight-boost",
        "context-weight-scale",
        "context-time-conf-power",
        "role-conflict-mode",
        "conflict-speed-threshold-mps",
        "conflict-context-factor",
        "localization-policy",
        "localization-candidate-grid",
        "vertical-risk-mode",
        "vertical-gradient-preserve-weight",
        "vertical-context-mismatch-damping",
        "progress-interval-seconds",
        "num-workers",
    ]
    args = dict(args_map)
    args["frame-times"] = ""
    args.pop("frame-times-file", None)
    for key in ordered_keys:
        value = args.get(key)
        if value is None:
            continue
        if key == "stage2-summary":
            value = "$ROOT/centralized_v1_output/stage2_full_v2/stage2_multimodal_summary.json"
        elif key == "stage3-summary":
            value = "$ROOT/centralized_v1_output/stage3_full_v2_25w_payload_only/stage3_center_summary.json"
        elif key == "frame-times" and str(value) == "":
            value = '""'
        lines.append(f"  --{key} {value} \\")
    lines.append("  --out-dir $OUT")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a narrow 25-worker grid refinement around the current best Stage4 candidate.")
    parser.add_argument("--python", type=Path, default=DEFAULT_PYTHON)
    parser.add_argument("--best-json", type=Path, default=DEFAULT_BEST_JSON)
    parser.add_argument("--out-root", type=Path, default=DEFAULT_OUT_ROOT)
    parser.add_argument("--num-workers", type=int, default=25)
    args = parser.parse_args()

    global PYTHON_EXE
    PYTHON_EXE = args.python

    baseline_label, baseline_dir, baseline_args = _load_best_candidate(args.best_json)
    baseline_args["num-workers"] = args.num_workers
    args.out_root.mkdir(parents=True, exist_ok=True)
    runs_root = args.out_root / "runs"
    analysis_root = args.out_root / "analysis"
    reports_root = args.out_root / "reports"
    runs_root.mkdir(parents=True, exist_ok=True)
    analysis_root.mkdir(parents=True, exist_ok=True)
    reports_root.mkdir(parents=True, exist_ok=True)

    scoreboard: list[dict[str, Any]] = []
    for idx, spec in enumerate(_candidate_grid(), start=1):
        if (
            abs(spec.context_time_conf_power - float(baseline_args["context-time-conf-power"])) < 1e-9
            and abs(spec.conflict_speed_threshold_mps - float(baseline_args["conflict-speed-threshold-mps"])) < 1e-9
        ):
            continue
        candidate_args = dict(baseline_args)
        candidate_args["context-time-conf-power"] = spec.context_time_conf_power
        candidate_args["conflict-speed-threshold-mps"] = spec.conflict_speed_threshold_mps
        run_dir = runs_root / f"{idx:02d}_{spec.slug}"
        _run_metrics(spec.slug, candidate_args, run_dir)
        compare_dir = analysis_root / f"{idx:02d}_{spec.slug}"
        compare_paths = _run_pairwise(
            baseline_label=baseline_label,
            baseline_dir=baseline_dir,
            candidate_label=spec.slug,
            candidate_dir=run_dir,
            out_dir=compare_dir,
            prefix=f"{baseline_label}_vs_{spec.slug}",
        )
        row = _score_candidate(
            baseline_label=baseline_label,
            candidate_label=spec.slug,
            compare_paths=compare_paths,
            context_time_conf_power=spec.context_time_conf_power,
            conflict_speed_threshold_mps=spec.conflict_speed_threshold_mps,
        )
        row["candidate_metrics_dir"] = str(run_dir)
        row["candidate_args"] = {key: str(value) for key, value in candidate_args.items()}
        scoreboard.append(row)

    scoreboard.sort(key=lambda row: (not row["passes_guardrail"], row["candidate_weighted_rmse"], row["candidate_p99"], row["candidate_frame_rmse"]))
    passing = [row for row in scoreboard if row["passes_guardrail"]]
    best_row = passing[0] if passing else None

    _write_csv(reports_root / "narrow_grid_scoreboard.csv", scoreboard)
    _write_json(reports_root / "narrow_grid_scoreboard.json", scoreboard)
    _write_markdown(reports_root / "narrow_grid_scoreboard.md", baseline_label, scoreboard, best_row)
    if best_row is not None:
        _write_json(
            reports_root / "best_narrow_grid_candidate.json",
            {
                "baseline_label": baseline_label,
                "best_label": best_row["candidate_label"],
                "metrics_dir": best_row["candidate_metrics_dir"],
                "args": best_row["candidate_args"],
                "compare_markdown": best_row["compare_markdown"],
            },
        )
        _write_full_run_script(reports_root / "run_best_full_25w.sh", best_row["candidate_args"], best_row["candidate_label"])
        print(best_row["candidate_metrics_dir"])
    else:
        _write_json(
            reports_root / "best_narrow_grid_candidate.json",
            {
                "baseline_label": baseline_label,
                "best_label": baseline_label,
                "metrics_dir": str(baseline_dir),
                "args": {key: str(value) for key, value in baseline_args.items()},
                "note": "No narrow-grid candidate beat the baseline under the guardrail.",
            },
        )
        _write_full_run_script(reports_root / "run_best_full_25w.sh", baseline_args, baseline_label)
        print(baseline_dir)


if __name__ == "__main__":
    main()
