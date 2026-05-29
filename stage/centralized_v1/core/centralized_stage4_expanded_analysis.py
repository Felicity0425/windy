"""Analyze centralized_v1 Stage4 expanded outputs.

This report is read-only: it summarizes existing Stage4 NPZ/CSV/PNG outputs,
compares point errors with literature-informed reference bands, and writes a
compact Markdown/CSV analysis table.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
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


DEFAULT_STAGE4_DIR = Path("/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_center_strict_expanded")
DEFAULT_OUT_DIR = DEFAULT_STAGE4_DIR / "analysis"


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


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


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        x = float(value)
    except (TypeError, ValueError):
        return default
    return x if math.isfinite(x) else default


def _band(rmse: float) -> str:
    """Literature-informed pragmatic bands for sparse aircraft hold-out RMSE."""

    if rmse <= 3.0:
        return "excellent_against_sparse_point_holdout"
    if rmse <= 6.0:
        return "good_for_sparse_aircraft_reconstruction"
    if rmse <= 10.0:
        return "usable_demo_but_needs_review"
    if rmse <= 15.0:
        return "weak_high_error_review_required"
    return "poor_failure_case"


def _slice_stats(stage4_dir: Path, time_str: str) -> dict[str, Any]:
    path = stage4_dir / "slices" / f"{time_str}_centralized_stage4_slice_stats.csv"
    if not path.exists():
        return {"slice_stats_exists": False}
    rows = _read_csv(path)
    domain = next((r for r in rows if r.get("slice") == "domain_extent"), {})
    horizontal = [r for r in rows if str(r.get("slice", "")).startswith("horizontal_z_")]
    return {
        "slice_stats_exists": True,
        "slice_rows": len(rows),
        "slice_horizontal_rows": len(horizontal),
        "slice_active_voxels_max": max((_to_float(r.get("active_voxels")) for r in horizontal), default=0.0),
        "slice_low_conf_fill_voxels_max": max((_to_float(r.get("low_conf_fill_voxels")) for r in horizontal), default=0.0),
        "slice_speed_mean_max_mps": max((_to_float(r.get("speed_mean_mps")) for r in horizontal), default=0.0),
        "domain_effective_reconstructed_voxels": int(_to_float(domain.get("effective_reconstructed_voxels"), 0.0)),
        "domain_low_conf_fill_fraction": _to_float(domain.get("low_conf_fill_fraction"), 0.0),
        "domain_confidence_active_mean": _to_float(domain.get("confidence_active_mean"), 0.0),
    }


def _point_stats(stage4_dir: Path, time_str: str) -> dict[str, Any]:
    path = stage4_dir / f"point_eval_{time_str}.csv"
    if not path.exists():
        return {"point_eval_exists": False}
    rows = _read_csv(path)
    vec = [_to_float(r.get("vector_error")) for r in rows]
    conf = [_to_float(r.get("recon_confidence")) for r in rows]
    nearest = [_to_float(r.get("nearest_train_distance_vox"), float("nan")) for r in rows]
    zero_conf = sum(1 for x in conf if x <= 1e-6)
    return {
        "point_eval_exists": True,
        "holdout_points": len(rows),
        "point_error_max_mps": max(vec, default=0.0),
        "point_error_p90_mps": float(np.percentile(vec, 90)) if vec else 0.0,
        "point_conf_min": min(conf, default=0.0),
        "point_zero_conf_count": zero_conf,
        "nearest_distance_max_vox": max((x for x in nearest if math.isfinite(x)), default=0.0),
    }


def _aggregate_sensitivity(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = _read_csv(path)
    groups: dict[tuple[str, str, str, str, str, str], list[dict[str, str]]] = {}
    for row in rows:
        key = (
            row.get("kernel", ""),
            row.get("confidence_mode", ""),
            row.get("physics_constraint_mode", row.get("mode", "")),
            row.get("localization_radius_xy", ""),
            row.get("localization_sigma_xy", ""),
            row.get("localization_radius_z", "") + "/" + row.get("localization_sigma_z", ""),
        )
        groups.setdefault(key, []).append(row)
    out = []
    for key, rs in sorted(groups.items()):
        out.append(
            {
                "kernel": key[0],
                "confidence_mode": key[1],
                "physics_constraint_mode": key[2],
                "rxy": key[3],
                "sxy": key[4],
                "rz_sz": key[5],
                "rows": len(rs),
                "mean_rmse_vector": float(np.mean([_to_float(r.get("rmse_vector")) for r in rs])),
                "mean_mae_vector": float(np.mean([_to_float(r.get("mae_vector")) for r in rs])),
                "mean_low_conf_fill_voxels": float(np.mean([_to_float(r.get("low_conf_fill_voxels")) for r in rs])),
                "mean_effective_reconstructed_voxels": float(np.mean([_to_float(r.get("effective_reconstructed_voxels")) for r in rs])),
                "leakage_all_true": all(str(r.get("strict_holdout_no_leakage")) == "True" for r in rs),
                "motion_all_false": all(str(r.get("motion_used_as_wind")) == "False" for r in rs),
            }
        )
    return sorted(out, key=lambda r: float(r["mean_rmse_vector"]))


def _png_inventory(stage4_dir: Path, time_str: str) -> dict[str, Any]:
    slices = stage4_dir / "slices" / f"{time_str}_centralized_stage4_slices.png"
    diag = stage4_dir / "slices" / f"{time_str}_centralized_stage4_diagnostics.png"
    return {
        "slice_png_exists": slices.exists(),
        "slice_png_bytes": slices.stat().st_size if slices.exists() else 0,
        "diagnostics_png_exists": diag.exists(),
        "diagnostics_png_bytes": diag.stat().st_size if diag.exists() else 0,
    }


def _write_md(
    path: Path,
    frame_rows: list[dict[str, Any]],
    sens_default: list[dict[str, Any]],
    sens_weighted: list[dict[str, Any]],
) -> None:
    lines = [
        "# Stage4 Expanded Output Analysis",
        "",
        "This report summarizes the existing 10-frame Stage4 strict expanded outputs. It does not rerun full Stage2/Stage3/Stage4.",
        "",
        "## Literature-Informed Metric Bands",
        "",
        "Aircraft-derived wind observations are sparse and noisy. Published aircraft/Mode-S wind studies commonly discuss errors of a few m/s after QC, while this project evaluates a reconstructed field at withheld sparse points rather than raw observation-vs-reference pairs. Therefore these bands are pragmatic review gates, not universal laws:",
        "",
        "| RMSE vector | interpretation |",
        "| ---: | --- |",
        "| <= 3 m/s | excellent against sparse point hold-out |",
        "| 3-6 m/s | good for sparse aircraft reconstruction |",
        "| 6-10 m/s | usable demo, still needs frame review |",
        "| 10-15 m/s | weak, high-error review required |",
        "| > 15 m/s | poor/failure case |",
        "",
        "References: WMO aircraft observations, ECMWF ERA5/4D-Var observation windows, PyDDA/3DVAR wind retrieval constraints, DART Gaspari-Cohn localization, scikit-learn leakage guidance, and AMT aircraft/Mode-S wind QC papers.",
        "",
        "## Per-Frame Result",
        "",
        "| frame | holdout | RMSE | MAE | band | max point error | zero-conf points | effective voxels | fill frac | visual note |",
        "| --- | ---: | ---: | ---: | --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in frame_rows:
        note = "review"
        if row["rmse_vector"] <= 6.0:
            note = "good/sparse pressure ok"
        elif row["rmse_vector"] > 15.0:
            note = "failure-case trace required"
        elif row["rmse_vector"] > 10.0:
            note = "weak/high-error"
        lines.append(
            f"| `{row['time_str']}` | {row['holdout_wind_records']} | {row['rmse_vector']:.3f} | "
            f"{row['mae_vector']:.3f} | `{row['metric_band']}` | {row['point_error_max_mps']:.3f} | "
            f"{row['point_zero_conf_count']} | {row['effective_reconstructed_voxels']} | "
            f"{row['low_conf_fill_fraction']:.4f} | {note} |"
        )
    lines.extend(
        [
            "",
            "## Sensitivity Summary",
            "",
            "Default diagnostic_only top rows:",
            "",
            "| rank | kernel | mode | rxy/sxy/rz/sz | mean RMSE | mean MAE | mean fill | mean effective |",
            "| ---: | --- | --- | --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for idx, row in enumerate(sens_default[:8], start=1):
        lines.append(
            f"| {idx} | `{row['kernel']}` | `{row['physics_constraint_mode']}` | "
            f"{row['rxy']}/{row['sxy']}/{row['rz_sz']} | {row['mean_rmse_vector']:.3f} | "
            f"{row['mean_mae_vector']:.3f} | {row['mean_low_conf_fill_voxels']:.1f} | "
            f"{row['mean_effective_reconstructed_voxels']:.1f} |"
        )
    lines.extend(
        [
            "",
            "Diagnostic_weighted + PyDDA-proxy top rows:",
            "",
            "| rank | kernel | mode | rxy/sxy/rz/sz | mean RMSE | mean MAE | mean fill | mean effective |",
            "| ---: | --- | --- | --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for idx, row in enumerate(sens_weighted[:8], start=1):
        lines.append(
            f"| {idx} | `{row['kernel']}` | `{row['physics_constraint_mode']}` | "
            f"{row['rxy']}/{row['sxy']}/{row['rz_sz']} | {row['mean_rmse_vector']:.3f} | "
            f"{row['mean_mae_vector']:.3f} | {row['mean_low_conf_fill_voxels']:.1f} | "
            f"{row['mean_effective_reconstructed_voxels']:.1f} |"
        )
    lines.extend(
        [
            "",
            "## Optimization Direction",
            "",
            "1. Keep Gaussian baseline unchanged for comparability.",
            "2. Treat Gaspari-Cohn `(8,4,2,1)` as the strongest all-10-frame candidate.",
            "3. Diagnose high-error frames separately because the two worst frames behave differently from the 10-frame average.",
            "4. Test role-aware weighting: current-window train wind should be allowed to dominate stale context wind when they conflict.",
            "5. Keep QC calibration experimental until larger train/validation/test splits exist.",
            "",
            "## References",
            "",
            "- WMO aircraft-based observations: https://wmo.int/aircraft-based-observations-programme",
            "- ECMWF ERA5 data documentation: https://confluence.ecmwf.int/display/CKB/ERA5%3A%2Bdata%2Bdocumentation",
            "- PyDDA 3DVAR wind retrieval: https://openresearchsoftware.metajnl.com/articles/264",
            "- PyDDA user guide: https://openradarscience.org/PyDDA/user_guide/retrieving_winds.html",
            "- DART Gaspari-Cohn localization: https://docs.dart.ucar.edu/en/v11.16.0/assimilation_code/modules/assimilation/cov_cutoff_mod.html",
            "- Data leakage guidance: https://scikit-learn.org/stable/common_pitfalls.html#data-leakage",
            "- Mode-S EHS aircraft-derived wind QC: https://amt.copernicus.org/articles/9/4141/2016/",
            "- EMADDC aircraft surveillance meteorological data QC: https://amt.copernicus.org/articles/18/3341/2025/",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze Stage4 expanded strict outputs.")
    parser.add_argument("--stage4-dir", type=Path, default=DEFAULT_STAGE4_DIR)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    args = parser.parse_args()

    summary = _read_json(args.stage4_dir / "stage4_center_summary.json")
    frame_rows = []
    for row in summary:
        time_str = str(row["time_str"])
        merged = {
            "time_str": time_str,
            "holdout_wind_records": int(row.get("holdout_wind_records", 0)),
            "rmse_vector": _to_float(row.get("rmse_vector")),
            "mae_vector": _to_float(row.get("mae_vector")),
            "bias_u": _to_float(row.get("bias_u")),
            "bias_v": _to_float(row.get("bias_v")),
            "effective_reconstructed_voxels": int(_to_float(row.get("effective_reconstructed_voxels"))),
            "low_conf_fill_voxels": int(_to_float(row.get("low_conf_fill_voxels"))),
            "low_conf_fill_fraction": _to_float(row.get("low_conf_fill_fraction")),
            "strict_holdout_no_leakage": bool(row.get("strict_holdout_no_leakage")),
            "motion_used_as_wind": bool(row.get("motion_used_as_wind")),
            "mask_conf_positive_mismatch_voxels": int(_to_float(row.get("mask_conf_positive_mismatch_voxels"))),
            "metric_band": _band(_to_float(row.get("rmse_vector"))),
            **_point_stats(args.stage4_dir, time_str),
            **_slice_stats(args.stage4_dir, time_str),
            **_png_inventory(args.stage4_dir, time_str),
        }
        frame_rows.append(merged)
    frame_rows.sort(key=lambda r: r["time_str"])

    sens_default = _aggregate_sensitivity(args.stage4_dir / "sensitivity" / "stage4_localization_sensitivity.csv")
    sens_weighted = _aggregate_sensitivity(
        args.stage4_dir / "sensitivity_diagnostic_weighted_pydda_proxy" / "stage4_localization_sensitivity.csv"
    )

    args.out_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(args.out_dir / "stage4_expanded_frame_analysis.csv", frame_rows)
    _write_csv(args.out_dir / "stage4_expanded_sensitivity_aggregate.csv", sens_default + sens_weighted)
    _write_md(args.out_dir / "stage4_expanded_analysis.md", frame_rows, sens_default, sens_weighted)
    print(args.out_dir / "stage4_expanded_analysis.md")


if __name__ == "__main__":
    main()

