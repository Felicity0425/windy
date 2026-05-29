"""Compare Stage4 CMA-fused candidate branches.

The script reads Stage4 branch summaries and writes a per-frame plus aggregate
CSV/Markdown comparison. It does not rerun reconstruction and it treats CMA
branches as weak-background / pseudo-observation candidates, not truth.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path
from typing import Any


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _parse_branch(text: str) -> tuple[str, Path]:
    if "=" not in text:
        raise ValueError(f"Branch must be name=/path/to/stage4_dir: {text}")
    name, path = text.split("=", 1)
    name = name.strip()
    if not name:
        raise ValueError(f"Branch name is empty: {text}")
    return name, Path(path.strip())


def _load_branch(name: str, stage4_dir: Path) -> list[dict[str, Any]]:
    summary_path = stage4_dir / "stage4_center_summary.json"
    if not summary_path.exists():
        return [
            {
                "branch": name,
                "stage4_dir": str(stage4_dir),
                "status": "missing_summary",
            }
        ]
    rows = _read_json(summary_path)
    out: list[dict[str, Any]] = []
    for row in rows:
        diagnostics = row.get("cma_fusion_diagnostics") if isinstance(row.get("cma_fusion_diagnostics"), dict) else {}
        leakage = row.get("leakage_report") if isinstance(row.get("leakage_report"), dict) else {}
        out.append(
            {
                "branch": name,
                "stage4_dir": str(stage4_dir),
                "status": "ok",
                "time_str": str(row.get("time_str", "")),
                "holdout": _to_int(row.get("holdout_wind_records")),
                "rmse_vector": _to_float(row.get("rmse_vector")),
                "mae_vector": _to_float(row.get("mae_vector")),
                "bias_u": _to_float(row.get("bias_u")),
                "bias_v": _to_float(row.get("bias_v")),
                "effective_reconstructed_voxels": _to_int(row.get("effective_reconstructed_voxels")),
                "effective_reconstructed_fraction": _to_float(row.get("effective_reconstructed_fraction")),
                "low_conf_fill_voxels": _to_int(row.get("low_conf_fill_voxels")),
                "cma_fusion_mode": str(row.get("cma_fusion_mode", diagnostics.get("cma_fusion_mode", "off"))),
                "cma_field_u_key": str(diagnostics.get("cma_field_u_key", "")),
                "cma_field_v_key": str(diagnostics.get("cma_field_v_key", "")),
                "cma_confidence_source": str(row.get("cma_confidence_source", diagnostics.get("cma_confidence_source", ""))),
                "cma_pseudo_source": str(row.get("cma_pseudo_source", diagnostics.get("cma_pseudo_source", ""))),
                "cma_qc_gating": str(row.get("cma_qc_gating", diagnostics.get("cma_qc_gating", ""))),
                "cma_temporal_conf_mean": _to_float(diagnostics.get("cma_temporal_conf_mean")),
                "cma_temporal_change_speed_mean_mps": _to_float(diagnostics.get("cma_temporal_change_speed_mean_mps")),
                "cma_rapid_change_fraction": _to_float(diagnostics.get("cma_rapid_change_fraction")),
                "cma_effective_conf_mean": _to_float(diagnostics.get("cma_effective_conf_mean")),
                "strict_holdout_no_leakage": bool(row.get("strict_holdout_no_leakage", leakage.get("strict_holdout_no_leakage", False))),
                "motion_used_as_wind": bool(row.get("motion_used_as_wind", leakage.get("motion_records_used_as_wind", False))),
                "cma_used_as_background_not_truth": bool(leakage.get("cma_used_as_background_not_truth", str(row.get("cma_fusion_mode", "off")) != "off")),
            }
        )
    return out


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: list[str] = []
    for row in rows:
        for key in row:
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _aggregate(rows: list[dict[str, Any]], baseline_name: str) -> list[dict[str, Any]]:
    by_branch: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        if row.get("status") != "ok":
            continue
        by_branch.setdefault(str(row["branch"]), []).append(row)
    baseline_by_time = {
        str(row["time_str"]): row
        for row in by_branch.get(baseline_name, [])
        if _to_int(row.get("holdout")) > 0
    }
    out: list[dict[str, Any]] = []
    for branch, branch_rows in sorted(by_branch.items()):
        eval_rows = [row for row in branch_rows if _to_int(row.get("holdout")) > 0]
        if not eval_rows:
            out.append({"branch": branch, "eval_frames": 0})
            continue
        deltas_rmse = []
        deltas_mae = []
        for row in eval_rows:
            base = baseline_by_time.get(str(row["time_str"]))
            if base is None:
                continue
            deltas_rmse.append(_to_float(row.get("rmse_vector")) - _to_float(base.get("rmse_vector")))
            deltas_mae.append(_to_float(row.get("mae_vector")) - _to_float(base.get("mae_vector")))
        out.append(
            {
                "branch": branch,
                "eval_frames": len(eval_rows),
                "mean_rmse": sum(_to_float(row.get("rmse_vector")) for row in eval_rows) / len(eval_rows),
                "mean_mae": sum(_to_float(row.get("mae_vector")) for row in eval_rows) / len(eval_rows),
                "mean_bias_u": sum(_to_float(row.get("bias_u")) for row in eval_rows) / len(eval_rows),
                "mean_bias_v": sum(_to_float(row.get("bias_v")) for row in eval_rows) / len(eval_rows),
                "mean_delta_rmse_vs_baseline": sum(deltas_rmse) / len(deltas_rmse) if deltas_rmse else 0.0,
                "mean_delta_mae_vs_baseline": sum(deltas_mae) / len(deltas_mae) if deltas_mae else 0.0,
                "leakage_all_true": all(bool(row.get("strict_holdout_no_leakage")) for row in eval_rows),
                "motion_used_as_wind_any": any(bool(row.get("motion_used_as_wind")) for row in eval_rows),
                "cma_background_not_truth_all_true": all(bool(row.get("cma_used_as_background_not_truth")) for row in eval_rows if str(row.get("cma_fusion_mode")) != "off"),
            }
        )
    return out


def _write_md(path: Path, rows: list[dict[str, Any]], aggregate: list[dict[str, Any]], baseline_name: str) -> None:
    lines = [
        "# Stage4 CMA Candidate Comparison",
        "",
        "CMA branches are evaluated as weak-background or pseudo-observation candidates. They do not replace the aircraft strict hold-out truth definition.",
        "",
        f"- baseline branch: `{baseline_name}`",
        f"- compared rows: `{len(rows)}`",
        "",
        "## Aggregate",
        "",
        "| branch | eval frames | mean RMSE | dRMSE vs baseline | mean MAE | dMAE vs baseline | leakage | motion as wind |",
        "| --- | ---: | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    for row in aggregate:
        lines.append(
            f"| `{row.get('branch', '')}` | {int(row.get('eval_frames', 0))} | "
            f"{_to_float(row.get('mean_rmse')):.6f} | {_to_float(row.get('mean_delta_rmse_vs_baseline')):.6f} | "
            f"{_to_float(row.get('mean_mae')):.6f} | {_to_float(row.get('mean_delta_mae_vs_baseline')):.6f} | "
            f"`{row.get('leakage_all_true', '')}` | `{row.get('motion_used_as_wind_any', '')}` |"
        )
    lines.extend(
        [
            "",
            "## Per Frame",
            "",
            "| branch | time | holdout | RMSE | MAE | bias_u | bias_v | CMA mode | temporal conf | rapid frac | leakage | motion |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | ---: | ---: | --- | --- |",
        ]
    )
    for row in sorted((r for r in rows if r.get("status") == "ok"), key=lambda r: (str(r["time_str"]), str(r["branch"]))):
        lines.append(
            f"| `{row['branch']}` | `{row['time_str']}` | {int(row['holdout'])} | "
            f"{_to_float(row['rmse_vector']):.6f} | {_to_float(row['mae_vector']):.6f} | "
            f"{_to_float(row['bias_u']):.6f} | {_to_float(row['bias_v']):.6f} | "
            f"`{row['cma_fusion_mode']}` | {_to_float(row['cma_temporal_conf_mean']):.3f} | "
            f"{_to_float(row['cma_rapid_change_fraction']):.6f} | `{row['strict_holdout_no_leakage']}` | `{row['motion_used_as_wind']}` |"
        )
    lines.extend(
        [
            "",
            "## Interpretation Rule",
            "",
            "If a CMA branch improves one metric but worsens another, or repairs some frames while degrading `20260207022400`, the conclusion should describe that mixed behavior. Do not promote CMA to the baseline unless a larger strict validation split confirms the tradeoff.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare Stage4 CMA candidate branches.")
    parser.add_argument("--branch", action="append", default=[], help="Branch mapping: name=/path/to/stage4_dir")
    parser.add_argument("--baseline-name", default="baseline")
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()
    if not args.branch:
        raise ValueError("Provide at least one --branch name=/path")
    rows: list[dict[str, Any]] = []
    for branch_text in args.branch:
        name, stage4_dir = _parse_branch(branch_text)
        rows.extend(_load_branch(name, stage4_dir))
    aggregate = _aggregate(rows, str(args.baseline_name))
    args.out_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(args.out_dir / "stage4_cma_candidate_comparison.csv", rows)
    _write_csv(args.out_dir / "stage4_cma_candidate_aggregate.csv", aggregate)
    _write_md(args.out_dir / "stage4_cma_candidate_comparison.md", rows, aggregate, str(args.baseline_name))
    print(args.out_dir / "stage4_cma_candidate_comparison.md")


if __name__ == "__main__":
    main()
