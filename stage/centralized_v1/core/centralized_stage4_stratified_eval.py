"""Stratified evaluation for centralized_v1 Stage4 metrics-only outputs."""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any, Callable

import numpy as np


DEFAULT_STAGE4_DIR = Path("/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_full_v2_best_adaptive_all_12w_20260529")
DEFAULT_SENSITIVITY_CSV = DEFAULT_STAGE4_DIR / "stage4_localization_sensitivity.csv"
DEFAULT_OUT_DIR = DEFAULT_STAGE4_DIR / "stratified_eval"

CONFIG_COLUMNS = [
    "kernel",
    "confidence_mode",
    "physics_constraint_mode",
    "localization_policy",
    "localization_candidate_grid",
    "localization_radius_xy",
    "localization_sigma_xy",
    "localization_radius_z",
    "localization_sigma_z",
    "current_weight_boost",
    "context_weight_scale",
    "context_time_conf_power",
    "role_conflict_mode",
    "conflict_speed_threshold_mps",
    "conflict_context_factor",
]

DIAGNOSTIC_COLUMNS = [
    "effective_reconstructed_voxels",
    "effective_reconstructed_fraction",
    "low_conf_fill_voxels",
    "low_conf_fill_fraction",
    "confidence_active_mean",
    "strong_wind_voxels",
    "vertical_context_mismatch_candidate_voxels",
    "vertical_oversmoothing_candidate_voxels",
    "strong_vertical_isolated_voxels",
    "role_conflict_voxels",
]


def _read_csv(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        return [dict(row) for row in csv.DictReader(f)]


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


def _to_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _to_int(value: Any) -> int:
    number = _to_float(value)
    return int(number) if number is not None else 0


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "y"}:
        return True
    if text in {"false", "0", "no", "n", ""}:
        return False
    return bool(value)


def _mean(values: list[float]) -> float | None:
    vals = [v for v in values if math.isfinite(v)]
    return float(np.mean(vals)) if vals else None


def _median(values: list[float]) -> float | None:
    vals = [v for v in values if math.isfinite(v)]
    return float(np.median(vals)) if vals else None


def _percentile(values: list[float], q: float) -> float | None:
    vals = [v for v in values if math.isfinite(v)]
    return float(np.percentile(vals, q)) if vals else None


def _sum(values: list[float]) -> float:
    return float(sum(v for v in values if math.isfinite(v)))


def _config_key(row: dict[str, Any]) -> tuple[str, ...]:
    return tuple(str(row.get(key, "")) for key in CONFIG_COLUMNS)


def _config_values(rows: list[dict[str, Any]]) -> dict[str, Any]:
    first = rows[0] if rows else {}
    return {key: first.get(key, "") for key in CONFIG_COLUMNS}


def _holdout_count(row: dict[str, Any]) -> int:
    return _to_int(row.get("holdout_wind_records"))


def _has_holdout(row: dict[str, Any]) -> bool:
    return _holdout_count(row) > 0


def _rmse(row: dict[str, Any]) -> float | None:
    return _to_float(row.get("rmse_vector"))


def _rmse_le6(row: dict[str, Any]) -> bool:
    value = _rmse(row)
    return _has_holdout(row) and value is not None and value <= 6.0


def _rmse_gt6(row: dict[str, Any]) -> bool:
    value = _rmse(row)
    return _has_holdout(row) and value is not None and value > 6.0


def _row_class(row: dict[str, Any]) -> dict[str, Any]:
    holdout = _holdout_count(row)
    if holdout <= 0:
        return {
            "eval_class": "no_holdout_unverified_reconstruction",
            "pressure_class": "no_holdout",
            "official_metric_allowed": False,
        }
    if holdout == 1:
        pressure = "single_holdout_pressure_test"
    else:
        pressure = "multi_holdout_supported"
    return {
        "eval_class": "eval_holdout_only",
        "pressure_class": pressure,
        "official_metric_allowed": True,
    }


def _classified_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for row in rows:
        classified = dict(row)
        classified.update(_row_class(row))
        classified["holdout_weight"] = _holdout_count(row)
        classified["no_holdout_unverified"] = not _has_holdout(row)
        out.append(classified)
    return out


def _strata() -> list[tuple[str, bool, bool, Callable[[dict[str, Any]], bool]]]:
    return [
        ("all_frames_original", False, False, lambda row: True),
        ("eval_holdout_only", True, True, lambda row: _has_holdout(row)),
        ("no_holdout_unverified_reconstruction", False, False, lambda row: not _has_holdout(row)),
        ("single_holdout_pressure_test", True, True, lambda row: _holdout_count(row) == 1),
        ("multi_holdout_supported", True, True, lambda row: _holdout_count(row) >= 2),
        ("multi_holdout_ge3", True, True, lambda row: _holdout_count(row) >= 3),
        ("rmse_le6", True, True, _rmse_le6),
        ("rmse_gt6", True, True, _rmse_gt6),
        ("strong_wind_subset", True, True, lambda row: _has_holdout(row) and _to_int(row.get("strong_wind_voxels")) > 0),
        (
            "vertical_mismatch_subset",
            True,
            True,
            lambda row: _has_holdout(row) and _to_int(row.get("vertical_context_mismatch_candidate_voxels")) > 0,
        ),
    ]


def _metric_values(rows: list[dict[str, Any]], key: str) -> list[float]:
    vals = []
    for row in rows:
        number = _to_float(row.get(key))
        if number is not None:
            vals.append(number)
    return vals


def _weighted_metrics(rows: list[dict[str, Any]], *, allow_metrics: bool) -> dict[str, Any]:
    if not allow_metrics:
        return {
            "holdout_point_weighted_rmse_vector": None,
            "holdout_point_weighted_mae_vector": None,
        }
    weights = [_holdout_count(row) for row in rows]
    total_weight = sum(weights)
    if total_weight <= 0:
        return {
            "holdout_point_weighted_rmse_vector": None,
            "holdout_point_weighted_mae_vector": None,
        }
    rmse_sum = 0.0
    mae_sum = 0.0
    rmse_weight = 0
    mae_weight = 0
    for row, weight in zip(rows, weights):
        rmse = _to_float(row.get("rmse_vector"))
        mae = _to_float(row.get("mae_vector"))
        if rmse is not None:
            rmse_sum += (rmse**2) * weight
            rmse_weight += weight
        if mae is not None:
            mae_sum += mae * weight
            mae_weight += weight
    return {
        "holdout_point_weighted_rmse_vector": math.sqrt(rmse_sum / rmse_weight) if rmse_weight else None,
        "holdout_point_weighted_mae_vector": mae_sum / mae_weight if mae_weight else None,
    }


def _aggregate_stratum(
    config_rows: list[dict[str, Any]],
    stratum: str,
    official_metric: bool,
    allow_error_metrics: bool,
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    out: dict[str, Any] = {
        **_config_values(config_rows),
        "stratum": stratum,
        "official_metric": bool(official_metric),
        "frames": len(rows),
        "holdout_points": sum(_holdout_count(row) for row in rows),
        "all_strict_holdout_no_leakage": bool(all(_as_bool(row.get("strict_holdout_no_leakage")) for row in rows)) if rows else True,
        "any_motion_used_as_wind": bool(any(_as_bool(row.get("motion_used_as_wind")) for row in rows)),
    }
    if allow_error_metrics:
        rmse = _metric_values(rows, "rmse_vector")
        mae = _metric_values(rows, "mae_vector")
        out.update(
            {
                "frame_mean_rmse_vector": _mean(rmse),
                "frame_mean_mae_vector": _mean(mae),
                "median_rmse_vector": _median(rmse),
                "p90_rmse_vector": _percentile(rmse, 90),
                "p95_rmse_vector": _percentile(rmse, 95),
                "p99_rmse_vector": _percentile(rmse, 99),
                "max_rmse_vector": max(rmse) if rmse else None,
                "frame_mean_bias_u": _mean(_metric_values(rows, "bias_u")),
                "frame_mean_bias_v": _mean(_metric_values(rows, "bias_v")),
                **_weighted_metrics(rows, allow_metrics=True),
            }
        )
    else:
        out.update(
            {
                "frame_mean_rmse_vector": None,
                "frame_mean_mae_vector": None,
                "median_rmse_vector": None,
                "p90_rmse_vector": None,
                "p95_rmse_vector": None,
                "p99_rmse_vector": None,
                "max_rmse_vector": None,
                "frame_mean_bias_u": None,
                "frame_mean_bias_v": None,
                **_weighted_metrics(rows, allow_metrics=False),
            }
        )
    for key in DIAGNOSTIC_COLUMNS:
        vals = _metric_values(rows, key)
        out[f"mean_{key}"] = _mean(vals)
        out[f"median_{key}"] = _median(vals)
        out[f"sum_{key}"] = _sum(vals)
    return out


def _aggregate_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, ...], list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault(_config_key(row), []).append(row)
    out: list[dict[str, Any]] = []
    for config_rows in groups.values():
        for stratum, official, allow_metrics, predicate in _strata():
            selected = [row for row in config_rows if predicate(row)]
            out.append(_aggregate_stratum(config_rows, stratum, official, allow_metrics, selected))
    return out


def _validation(aggregate_rows: list[dict[str, Any]], expected_frames: int) -> dict[str, Any]:
    validation = {
        "expected_frames": int(expected_frames),
        "config_count": len({tuple(row.get(key, "") for key in CONFIG_COLUMNS) for row in aggregate_rows}),
        "failures": [],
    }
    if expected_frames <= 0:
        return validation
    all_frame_rows = [row for row in aggregate_rows if row.get("stratum") == "all_frames_original"]
    adaptive_split = any("adaptive" in str(row.get("localization_policy", "")) for row in all_frame_rows)
    if adaptive_split:
        frames = sum(_to_int(row.get("frames")) for row in all_frame_rows)
        if frames != expected_frames:
            validation["failures"].append(
                {
                    "stratum": "all_frames_original_adaptive_total",
                    "frames": frames,
                    "expected_frames": expected_frames,
                }
            )
        return validation
    for row in aggregate_rows:
        if row.get("stratum") != "all_frames_original":
            continue
        frames = _to_int(row.get("frames"))
        if frames != expected_frames:
            validation["failures"].append(
                {
                    "stratum": row.get("stratum"),
                    "kernel": row.get("kernel"),
                    "frames": frames,
                    "expected_frames": expected_frames,
                }
            )
    return validation


def _write_md(path: Path, rows: list[dict[str, Any]], validation: dict[str, Any]) -> None:
    lines = [
        "# Stage4 Stratified Evaluation",
        "",
        "Official RMSE/MAE comes only from `eval_holdout_only` and its holdout subsets. `no_holdout_unverified_reconstruction` keeps coverage and risk diagnostics but does not contribute to official error metrics.",
        "",
        f"- expected frames: `{validation.get('expected_frames')}`",
        f"- validation failures: `{len(validation.get('failures', []))}`",
        "",
        "| stratum | official | frames | holdout points | frame RMSE | frame MAE | weighted RMSE | weighted MAE | mean effective voxels | mean low-conf fill | leakage | motion used |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    for row in rows:
        lines.append(
            f"| `{row.get('stratum')}` | `{row.get('official_metric')}` | {row.get('frames')} | {row.get('holdout_points')} | "
            f"{_fmt(row.get('frame_mean_rmse_vector'))} | {_fmt(row.get('frame_mean_mae_vector'))} | "
            f"{_fmt(row.get('holdout_point_weighted_rmse_vector'))} | {_fmt(row.get('holdout_point_weighted_mae_vector'))} | "
            f"{_fmt(row.get('mean_effective_reconstructed_voxels'))} | {_fmt(row.get('mean_low_conf_fill_voxels'))} | "
            f"`{row.get('all_strict_holdout_no_leakage')}` | `{row.get('any_motion_used_as_wind')}` |"
        )
    if validation.get("failures"):
        lines.extend(["", "## Validation Failures", ""])
        for failure in validation["failures"]:
            lines.append(f"- `{failure}`")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _fmt(value: Any) -> str:
    number = _to_float(value)
    if number is None:
        return ""
    return f"{number:.6f}"


def write_stratified_eval(
    rows: list[dict[str, Any]],
    out_dir: Path,
    *,
    expected_frames: int = 0,
    source_csv: str = "",
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    classified = _classified_rows(rows)
    aggregate = _aggregate_rows(rows)
    validation = _validation(aggregate, int(expected_frames))

    rows_csv = out_dir / "stage4_localization_sensitivity_stratified_rows.csv"
    aggregate_csv = out_dir / "stage4_localization_sensitivity_stratified_aggregate.csv"
    aggregate_md = out_dir / "stage4_localization_sensitivity_stratified_aggregate.md"
    run_json = out_dir / "stage4_localization_sensitivity_stratified_run.json"

    _write_csv(rows_csv, classified)
    _write_csv(aggregate_csv, aggregate)
    _write_md(aggregate_md, aggregate, validation)
    run_meta = {
        "source_csv": str(source_csv),
        "expected_frames": int(expected_frames),
        "input_rows": len(rows),
        "classified_rows_csv": str(rows_csv),
        "aggregate_csv": str(aggregate_csv),
        "aggregate_md": str(aggregate_md),
        "validation": validation,
    }
    run_json.write_text(json.dumps(run_meta, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "stratified_rows_csv": str(rows_csv),
        "stratified_aggregate_csv": str(aggregate_csv),
        "stratified_aggregate_md": str(aggregate_md),
        "stratified_run_json": str(run_json),
        "validation": validation,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build strict holdout-only stratified Stage4 metrics.")
    parser.add_argument("--sensitivity-csv", type=Path, default=DEFAULT_SENSITIVITY_CSV)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--expected-frames", type=int, default=7395)
    args = parser.parse_args()

    if not args.sensitivity_csv.exists():
        raise FileNotFoundError(args.sensitivity_csv)
    rows = _read_csv(args.sensitivity_csv)
    result = write_stratified_eval(rows, args.out_dir, expected_frames=int(args.expected_frames), source_csv=str(args.sensitivity_csv))
    print(result["stratified_run_json"])
    if result["validation"].get("failures"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
