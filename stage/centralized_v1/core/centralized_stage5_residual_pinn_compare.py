"""Compare point-level Stage5 residual PINN predictions with Stage4 baseline."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd


def _metrics(group: pd.DataFrame) -> dict[str, Any]:
    base = pd.to_numeric(group["baseline_vector_error"], errors="coerce").fillna(0.0).to_numpy(dtype=np.float64)
    cand = pd.to_numeric(group["candidate_vector_error"], errors="coerce").fillna(0.0).to_numpy(dtype=np.float64)
    gt_speed = pd.to_numeric(group["gt_speed"], errors="coerce").fillna(0.0).to_numpy(dtype=np.float64)
    light = (gt_speed >= 5.0) & (gt_speed < 15.0)
    light_mod = (gt_speed >= 5.0) & (gt_speed < 30.0)
    rel = cand / np.maximum(gt_speed, 1e-6)
    delta = cand - base

    def rmse(values: np.ndarray) -> float:
        return float(np.sqrt(np.mean(values**2))) if values.size else 0.0

    def mean(values: np.ndarray) -> float:
        return float(np.mean(values)) if values.size else 0.0

    def q(values: np.ndarray, quantile: float) -> float:
        return float(np.quantile(values, quantile)) if values.size else 0.0

    return {
        "points": int(len(group)),
        "baseline_rmse": rmse(base),
        "candidate_rmse": rmse(cand),
        "delta_rmse": rmse(cand) - rmse(base),
        "baseline_mae": mean(base),
        "candidate_mae": mean(cand),
        "baseline_p95": q(base, 0.95),
        "candidate_p95": q(cand, 0.95),
        "baseline_p99": q(base, 0.99),
        "candidate_p99": q(cand, 0.99),
        "baseline_light_rmse": rmse(base[light]),
        "candidate_light_rmse": rmse(cand[light]),
        "baseline_light_mae": mean(base[light]),
        "candidate_light_mae": mean(cand[light]),
        "baseline_floor10_relative_mae": mean(base / np.maximum(gt_speed, 10.0)),
        "candidate_floor10_relative_mae": mean(cand / np.maximum(gt_speed, 10.0)),
        "baseline_high_error_ge30_count": int(np.count_nonzero(base >= 30.0)),
        "candidate_high_error_ge30_count": int(np.count_nonzero(cand >= 30.0)),
        "new_light_moderate_relative_tail_failures": int(np.count_nonzero(light_mod & (rel > 2.0) & (delta > 5.0))),
    }


def _passes(row: dict[str, Any]) -> dict[str, bool]:
    return {
        "weighted_rmse_not_worse": row["candidate_rmse"] <= row["baseline_rmse"] + 1e-9,
        "p95_not_worse": row["candidate_p95"] <= row["baseline_p95"] + 1e-9,
        "p99_not_worse": row["candidate_p99"] <= row["baseline_p99"] + 1e-9,
        "light_rmse_not_worse": row["candidate_light_rmse"] <= row["baseline_light_rmse"] + 1e-9,
        "light_mae_not_worse": row["candidate_light_mae"] <= row["baseline_light_mae"] + 1e-9,
        "floor10_not_worse": row["candidate_floor10_relative_mae"] <= row["baseline_floor10_relative_mae"] + 1e-9,
        "no_new_light_moderate_tail_failure": int(row["new_light_moderate_relative_tail_failures"]) == 0,
        "high_error_count_not_worse": row["candidate_high_error_ge30_count"] <= row["baseline_high_error_ge30_count"],
    }


def _write_md(path: Path, rows: list[dict[str, Any]], focus_split: str) -> None:
    lines = [
        "# Stage5 Residual PINN Point-Level Comparison",
        "",
        "This comparison is report-only. It does not promote a full-field Stage5 reconstruction.",
        "",
        "| split | points | baseline RMSE | candidate RMSE | delta RMSE | baseline P95 | candidate P95 | baseline P99 | candidate P99 | light RMSE base/cand | floor10 base/cand | new light/mod fails |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | ---: |",
    ]
    for row in rows:
        lines.append(
            f"| `{row['split']}` | {row['points']} | {row['baseline_rmse']:.6f} | "
            f"{row['candidate_rmse']:.6f} | {row['delta_rmse']:+.6f} | "
            f"{row['baseline_p95']:.6f} | {row['candidate_p95']:.6f} | "
            f"{row['baseline_p99']:.6f} | {row['candidate_p99']:.6f} | "
            f"{row['baseline_light_rmse']:.6f}/{row['candidate_light_rmse']:.6f} | "
            f"{row['baseline_floor10_relative_mae']:.6f}/{row['candidate_floor10_relative_mae']:.6f} | "
            f"{row['new_light_moderate_relative_tail_failures']} |"
        )
    focus = next((row for row in rows if row["split"] == focus_split), None)
    if focus:
        gates = _passes(focus)
        overall = all(gates.values())
        lines.extend(["", f"## `{focus_split}` Guardrail", "", "| gate | result |", "| --- | --- |"])
        for key, value in gates.items():
            lines.append(f"| `{key}` | `{'PASS' if value else 'FAIL'}` |")
        lines.append(f"| `POINT_REPORT_OVERALL` | `{'PASS' if overall else 'FAIL'}` |")
    lines.extend(
        [
            "",
            "## Boundary",
            "",
            "- This is a split-aware point report, not the official Stage4/Stage5 field formal gate.",
            "- Train split metrics are not promotion evidence.",
            "- A full-field candidate still requires smoke and the 200-frame strict holdout pairwise checklist.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare Stage5 residual PINN point predictions.")
    parser.add_argument("--baseline-point-departures", type=Path, required=True)
    parser.add_argument("--candidate-point-predictions", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--focus-split", choices=["train", "val", "test", "all"], default="test")
    parser.add_argument("--formal-guardrail", action="store_true")
    args = parser.parse_args()

    baseline = pd.read_csv(args.baseline_point_departures)
    candidate = pd.read_csv(args.candidate_point_predictions)
    if "row_id" not in baseline.columns:
        baseline = baseline.copy()
        baseline["row_id"] = np.arange(len(baseline), dtype=np.int64)
    merged = candidate.merge(
        baseline[["row_id", "time_str", "z", "y", "x", "alt_m"]].copy(),
        on="row_id",
        how="left",
    )
    rows: list[dict[str, Any]] = []
    for split in ("train", "val", "test"):
        group = merged[merged["split"] == split]
        row = _metrics(group)
        row["split"] = split
        rows.append(row)
    all_row = _metrics(merged)
    all_row["split"] = "all"
    rows.append(all_row)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    with (args.out_dir / "residual_pinn_point_compare.csv").open("w", encoding="utf-8", newline="") as f:
        fieldnames = list(rows[0].keys())
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    focus = next((row for row in rows if row["split"] == args.focus_split), all_row)
    checklist = _passes(focus)
    result = {
        "rows": rows,
        "focus_split": args.focus_split,
        "checklist": checklist,
        "point_report_overall": bool(all(checklist.values())),
        "formal_guardrail_requested": bool(args.formal_guardrail),
        "formal_guardrail_note": "This point report is not a full-field promotion gate.",
    }
    (args.out_dir / "residual_pinn_point_compare.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_md(args.out_dir / "residual_pinn_point_compare.md", rows, args.focus_split)
    print(args.out_dir / "residual_pinn_point_compare.md")


if __name__ == "__main__":
    main()
