"""Compare Stage4 metrics-only sensitivity aggregates.

The input files are the `stage4_localization_sensitivity_aggregate.csv` files
written by `centralized_stage4_sensitivity.py`.
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Any


def _read_labeled_csv(spec: str) -> list[dict[str, Any]]:
    if "=" not in spec:
        raise ValueError("--input must use label=/path/to/aggregate.csv")
    label, path_text = spec.split("=", 1)
    label = label.strip()
    path = Path(path_text.strip())
    if not label:
        raise ValueError(f"Missing label in --input {spec!r}")
    if not path.exists():
        raise FileNotFoundError(path)

    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            out = dict(row)
            out["run_label"] = label
            out["source_csv"] = str(path)
            rows.append(out)
    return rows


def _to_float(row: dict[str, Any], key: str, default: float = float("nan")) -> float:
    try:
        return float(row.get(key, default))
    except (TypeError, ValueError):
        return default


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames: list[str] = []
    preferred = [
        "rank",
        "run_label",
        "delta_rmse_vs_baseline_best",
        "delta_mae_vs_baseline_best",
        "kernel",
        "confidence_mode",
        "physics_constraint_mode",
        "role_conflict_mode",
        "localization_radius_xy",
        "localization_sigma_xy",
        "localization_radius_z",
        "localization_sigma_z",
        "frames",
        "mean_rmse_vector",
        "mean_mae_vector",
        "mean_bias_u",
        "mean_bias_v",
        "mean_low_conf_fill_voxels",
        "mean_effective_reconstructed_voxels",
        "all_strict_holdout_no_leakage",
        "any_motion_used_as_wind",
        "source_csv",
    ]
    for key in preferred:
        if any(key in row for row in rows):
            fieldnames.append(key)
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
        "# Stage4 Validation Comparison",
        "",
        "Combined ranking from metrics-only aggregate CSV files. No 3D NPZ or visualization files are read here.",
        "",
        "| rank | run | kernel | confidence | physics | role conflict | rxy/sxy/rz/sz | frames | mean RMSE | delta RMSE | mean MAE | delta MAE | mean fill | leakage | motion used |",
        "| ---: | --- | --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    for row in rows:
        params = (
            f"{row.get('localization_radius_xy')}/"
            f"{row.get('localization_sigma_xy')}/"
            f"{row.get('localization_radius_z')}/"
            f"{row.get('localization_sigma_z')}"
        )
        lines.append(
            f"| {row.get('rank')} | `{row.get('run_label')}` | `{row.get('kernel')}` | "
            f"`{row.get('confidence_mode')}` | `{row.get('physics_constraint_mode')}` | "
            f"`{row.get('role_conflict_mode')}` | {params} | {row.get('frames')} | "
            f"{_to_float(row, 'mean_rmse_vector'):.6f} | "
            f"{_to_float(row, 'delta_rmse_vs_baseline_best'):.6f} | "
            f"{_to_float(row, 'mean_mae_vector'):.6f} | "
            f"{_to_float(row, 'delta_mae_vs_baseline_best'):.6f} | "
            f"{_to_float(row, 'mean_low_conf_fill_voxels'):.1f} | "
            f"`{row.get('all_strict_holdout_no_leakage')}` | "
            f"`{row.get('any_motion_used_as_wind')}` |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare Stage4 sensitivity aggregate tables.")
    parser.add_argument("--input", action="append", required=True, help="label=/path/to/stage4_localization_sensitivity_aggregate.csv")
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--out-prefix", default="stage4_validation_comparison")
    args = parser.parse_args()

    rows: list[dict[str, Any]] = []
    for spec in args.input:
        rows.extend(_read_labeled_csv(spec))
    if not rows:
        raise ValueError("No rows were read from input aggregate CSV files.")

    baseline_label = args.input[0].split("=", 1)[0].strip()
    baseline_rows = [row for row in rows if row.get("run_label") == baseline_label]
    if not baseline_rows:
        raise ValueError(f"No baseline rows found for first input label: {baseline_label}")
    baseline_best = min(baseline_rows, key=lambda row: _to_float(row, "mean_rmse_vector"))
    baseline_rmse = _to_float(baseline_best, "mean_rmse_vector")
    baseline_mae = _to_float(baseline_best, "mean_mae_vector")

    ranked = sorted(rows, key=lambda row: _to_float(row, "mean_rmse_vector"))
    for idx, row in enumerate(ranked, start=1):
        row["rank"] = idx
        row["delta_rmse_vs_baseline_best"] = _to_float(row, "mean_rmse_vector") - baseline_rmse
        row["delta_mae_vs_baseline_best"] = _to_float(row, "mean_mae_vector") - baseline_mae

    args.out_dir.mkdir(parents=True, exist_ok=True)
    csv_path = args.out_dir / f"{args.out_prefix}.csv"
    md_path = args.out_dir / f"{args.out_prefix}.md"
    _write_csv(csv_path, ranked)
    _write_md(md_path, ranked)
    print(csv_path)


if __name__ == "__main__":
    main()
