"""Analyze fixed-kernel Stage4 metrics and oracle-best upper bound."""

from __future__ import annotations

import argparse
import csv
import math
from pathlib import Path
from typing import Any

import numpy as np


def _read_csv(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        return [dict(row) for row in csv.DictReader(f)]


def _to_float(row: dict[str, Any], key: str, default: float = 0.0) -> float:
    try:
        value = float(row.get(key, default))
    except (TypeError, ValueError):
        return default
    return value if math.isfinite(value) else default


def _to_int(row: dict[str, Any], key: str, default: int = 0) -> int:
    try:
        return int(float(row.get(key, default)))
    except (TypeError, ValueError):
        return default


def _kernel_label(row: dict[str, Any]) -> str:
    return (
        f"{int(_to_float(row, 'localization_radius_xy'))}/"
        f"{_to_float(row, 'localization_sigma_xy'):g}/"
        f"{int(_to_float(row, 'localization_radius_z'))}/"
        f"{_to_float(row, 'localization_sigma_z'):g}"
    )


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


def _summary(rows: list[dict[str, Any]], label: str) -> dict[str, Any]:
    rmse = np.asarray([_to_float(row, "rmse_vector") for row in rows], dtype=np.float64)
    mae = np.asarray([_to_float(row, "mae_vector") for row in rows], dtype=np.float64)
    holdout = np.asarray([max(0, _to_int(row, "holdout_wind_records")) for row in rows], dtype=np.float64)
    weights = np.where(holdout > 0.0, holdout, 1.0)
    return {
        "method": label,
        "frames": int(len(rows)),
        "holdout_points": int(np.sum(holdout)),
        "frame_mean_rmse": float(np.mean(rmse)),
        "frame_mean_mae": float(np.mean(mae)),
        "weighted_rmse": float(np.sqrt(np.sum((rmse**2) * weights) / np.sum(weights))),
        "weighted_mae": float(np.sum(mae * weights) / np.sum(weights)),
        "median_rmse": float(np.median(rmse)),
        "p90_rmse": float(np.percentile(rmse, 90.0)),
        "p95_rmse": float(np.percentile(rmse, 95.0)),
        "p99_rmse": float(np.percentile(rmse, 99.0)),
        "max_rmse": float(np.max(rmse)),
        "all_strict_holdout_no_leakage": bool(all(str(row.get("strict_holdout_no_leakage")) == "True" for row in rows)),
        "any_motion_used_as_wind": bool(any(str(row.get("motion_used_as_wind")) == "True" for row in rows)),
    }


def _write_md(path: Path, summaries: list[dict[str, Any]], oracle_rows: list[dict[str, Any]], selection_counts: dict[str, int]) -> None:
    lines = [
        "# Stage4 Fixed-Kernel And Oracle Analysis",
        "",
        "Oracle best selects the lowest holdout RMSE per frame and is an upper-bound diagnostic only. It is not deployable because it uses holdout errors.",
        "",
        "## Summary",
        "",
        "| method | frames | frame RMSE | frame MAE | weighted RMSE | weighted MAE | median | p95 | p99 | max | strict | motion used |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    for row in summaries:
        lines.append(
            f"| `{row['method']}` | {row['frames']} | {row['frame_mean_rmse']:.6f} | {row['frame_mean_mae']:.6f} | "
            f"{row['weighted_rmse']:.6f} | {row['weighted_mae']:.6f} | {row['median_rmse']:.6f} | "
            f"{row['p95_rmse']:.6f} | {row['p99_rmse']:.6f} | {row['max_rmse']:.6f} | "
            f"`{row['all_strict_holdout_no_leakage']}` | `{row['any_motion_used_as_wind']}` |"
        )
    lines.extend(["", "## Oracle Kernel Selection Counts", "", "| kernel | frames |", "| --- | ---: |"])
    for key, count in sorted(selection_counts.items()):
        lines.append(f"| `{key}` | {count} |")
    lines.extend(
        [
            "",
            "## Note",
            "",
            "Use this report to estimate the possible gain from localization adaptation. A real diagnostic-adaptive policy must choose kernels without holdout RMSE.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build fixed-kernel summary and oracle-best rows.")
    parser.add_argument("--input-csv", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--out-prefix", default="fixed_kernel_oracle_analysis")
    args = parser.parse_args()

    rows = _read_csv(args.input_csv)
    by_kernel: dict[str, list[dict[str, Any]]] = {}
    by_time: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_kernel.setdefault(_kernel_label(row), []).append(row)
        by_time.setdefault(str(row.get("time_str")), []).append(row)
    summaries = [_summary(group, kernel) for kernel, group in sorted(by_kernel.items())]
    oracle_rows: list[dict[str, Any]] = []
    selection_counts: dict[str, int] = {}
    for time_str, frame_rows in sorted(by_time.items()):
        best = min(frame_rows, key=lambda row: _to_float(row, "rmse_vector"))
        out = dict(best)
        out["oracle_selected_kernel"] = _kernel_label(best)
        out["oracle_note"] = "uses_holdout_rmse_not_deployable"
        oracle_rows.append(out)
        selection_counts[out["oracle_selected_kernel"]] = selection_counts.get(out["oracle_selected_kernel"], 0) + 1
    summaries.append(_summary(oracle_rows, "oracle_best_holdout_rmse"))

    args.out_dir.mkdir(parents=True, exist_ok=True)
    summary_csv = args.out_dir / f"{args.out_prefix}_summary.csv"
    oracle_csv = args.out_dir / f"{args.out_prefix}_oracle_rows.csv"
    counts_csv = args.out_dir / f"{args.out_prefix}_selection_counts.csv"
    md_path = args.out_dir / f"{args.out_prefix}.md"
    _write_csv(summary_csv, summaries)
    _write_csv(oracle_csv, oracle_rows)
    _write_csv(counts_csv, [{"kernel": key, "frames": count} for key, count in sorted(selection_counts.items())])
    _write_md(md_path, summaries, oracle_rows, selection_counts)
    print(md_path)


if __name__ == "__main__":
    main()
