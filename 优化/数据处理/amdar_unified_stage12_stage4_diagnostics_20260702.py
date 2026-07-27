#!/usr/bin/env python3
"""Stage12/Stage4 diagnostics after strict-TURB baseline reproduction.

This script is intentionally read-only for upstream Stage2/3/4 products. It
derives point-level wind speed/direction diagnostics, representative plots, and
a Stage13 plan supplement from the metrics-only Stage4 output.
"""

from __future__ import annotations

import csv
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


BASE = Path(
    "/data/LFT-W02_data/pengxu/优化/数据处理/"
    "amdar_unified_stage12_stage4_baseline_reproduction_optimized_20260702"
)
STAGE4_DIR = BASE / "stage4_baseline_unified_v1_200frames"
STAGE2_SUMMARY = BASE / "stage2_baseline_compat_200" / "stage2_multimodal_summary.json"
PLAN = Path("/data/LFT-W02_data/pengxu/优化/数据处理/amdar_unified_implementation_plan_20260701.md")
OUT_DIR = BASE / "stage4_holdout_diagnostics_and_stage13_supplement"


def f(row: dict[str, Any], key: str, default: float = float("nan")) -> float:
    try:
        value = row.get(key)
        if value in ("", None):
            return default
        return float(value)
    except Exception:
        return default


def wind_dir_to_deg(u: float, v: float) -> float:
    return (math.degrees(math.atan2(u, v)) + 360.0) % 360.0


def wind_dir_from_deg(u: float, v: float) -> float:
    return (wind_dir_to_deg(u, v) + 180.0) % 360.0


def angle_diff_deg(a: float, b: float) -> float:
    return abs((a - b + 180.0) % 360.0 - 180.0)


def q(vals: list[float], pct: float) -> float:
    clean = [v for v in vals if math.isfinite(v)]
    if not clean:
        return float("nan")
    return float(np.quantile(np.asarray(clean, dtype=np.float64), pct))


def mean(vals: list[float]) -> float:
    clean = [v for v in vals if math.isfinite(v)]
    return float(sum(clean) / len(clean)) if clean else float("nan")


def median(vals: list[float]) -> float:
    clean = sorted(v for v in vals if math.isfinite(v))
    if not clean:
        return float("nan")
    n = len(clean)
    if n % 2:
        return float(clean[n // 2])
    return float((clean[n // 2 - 1] + clean[n // 2]) / 2.0)


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def records_from_npz(npz_path: Path, key: str) -> list[dict[str, Any]]:
    with np.load(npz_path, allow_pickle=True) as z:
        if key not in z.files:
            return []
        arr = z[key]
        out: list[dict[str, Any]] = []
        for item in arr.tolist():
            if isinstance(item, dict):
                out.append(item)
            else:
                try:
                    out.append(dict(item))
                except Exception:
                    pass
        return out


def load_stage2_index() -> dict[str, dict[str, Any]]:
    rows = json.loads(STAGE2_SUMMARY.read_text(encoding="utf-8"))
    return {str(row["time_str"]): row for row in rows}


def enrich_point_departures() -> tuple[list[dict[str, Any]], dict[str, Any]]:
    point_rows = read_csv(STAGE4_DIR / "stage4_point_departures.csv")
    enriched: list[dict[str, Any]] = []
    reason_counter: Counter[str] = Counter()
    for row in point_rows:
        gt_u, gt_v = f(row, "gt_u"), f(row, "gt_v")
        pred_u, pred_v = f(row, "pred_u"), f(row, "pred_v")
        gt_speed = math.hypot(gt_u, gt_v)
        pred_speed = math.hypot(pred_u, pred_v)
        gt_to = wind_dir_to_deg(gt_u, gt_v)
        pred_to = wind_dir_to_deg(pred_u, pred_v)
        gt_from = wind_dir_from_deg(gt_u, gt_v)
        pred_from = wind_dir_from_deg(pred_u, pred_v)
        dir_err = angle_diff_deg(gt_to, pred_to)
        speed_err = pred_speed - gt_speed
        vector_error = math.hypot(pred_u - gt_u, pred_v - gt_v)
        for reason in str(row.get("qc_review_reasons", "")).split(";"):
            if reason:
                reason_counter[reason] += 1
        enriched.append(
            {
                **row,
                "gt_speed_calc_mps": gt_speed,
                "pred_speed_calc_mps": pred_speed,
                "speed_error_pred_minus_gt_mps": speed_err,
                "gt_dir_to_deg": gt_to,
                "pred_dir_to_deg": pred_to,
                "gt_dir_from_deg": gt_from,
                "pred_dir_from_deg": pred_from,
                "direction_error_deg": dir_err,
                "vector_error_calc_mps": vector_error,
            }
        )

    vector_errors = [float(row["vector_error_calc_mps"]) for row in enriched]
    speed_errors = [float(row["speed_error_pred_minus_gt_mps"]) for row in enriched]
    dir_errors = [float(row["direction_error_deg"]) for row in enriched]
    dir_errors_speed_ge_5 = [float(row["direction_error_deg"]) for row in enriched if float(row["gt_speed_calc_mps"]) >= 5.0]
    gt_speeds = [float(row["gt_speed_calc_mps"]) for row in enriched]
    pred_speeds = [float(row["pred_speed_calc_mps"]) for row in enriched]
    confs = [f(row, "recon_confidence") for row in enriched]
    summary = {
        "holdout_points": len(enriched),
        "vector_error_mps": {
            "mean": mean(vector_errors),
            "median": median(vector_errors),
            "p90": q(vector_errors, 0.90),
            "p95": q(vector_errors, 0.95),
            "max": max(vector_errors) if vector_errors else None,
        },
        "speed_error_pred_minus_gt_mps": {
            "mean": mean(speed_errors),
            "median": median(speed_errors),
            "p90": q(speed_errors, 0.90),
            "p95": q(speed_errors, 0.95),
            "min": min(speed_errors) if speed_errors else None,
            "max": max(speed_errors) if speed_errors else None,
        },
        "direction_error_deg": {
            "mean_all": mean(dir_errors),
            "median_all": median(dir_errors),
            "p90_all": q(dir_errors, 0.90),
            "p95_all": q(dir_errors, 0.95),
            "mean_gt_speed_ge_5": mean(dir_errors_speed_ge_5),
            "median_gt_speed_ge_5": median(dir_errors_speed_ge_5),
            "point_count_gt_speed_ge_5": len(dir_errors_speed_ge_5),
        },
        "gt_speed_mps": {"mean": mean(gt_speeds), "median": median(gt_speeds), "max": max(gt_speeds)},
        "pred_speed_mps": {"mean": mean(pred_speeds), "median": median(pred_speeds), "max": max(pred_speeds)},
        "recon_confidence": {"mean": mean(confs), "median": median(confs), "min": min(confs), "max": max(confs)},
        "qc_review_reasons_top": reason_counter.most_common(20),
        "context_only_nearest_support_points": reason_counter.get("context_only_nearest_support", 0),
        "high_vector_error_ge_30mps_points": reason_counter.get("high_vector_error_ge_30mps", 0),
    }
    return enriched, summary


def representative_rows(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    ordered = sorted(rows, key=lambda row: float(row["vector_error_calc_mps"]))
    by_time: dict[str, dict[str, Any]] = {}
    for row in rows:
        by_time.setdefault(str(row["time_str"]), row)
    return {
        "best": ordered[0],
        "median": ordered[len(ordered) // 2],
        "p90": ordered[int(0.90 * (len(ordered) - 1))],
        "worst": ordered[-1],
        "good_two_label_example": by_time.get("20260206021200", ordered[0]),
    }


def plot_overview(rows: list[dict[str, Any]], out_png: Path) -> None:
    errs = np.asarray([float(row["vector_error_calc_mps"]) for row in rows])
    gt = np.asarray([float(row["gt_speed_calc_mps"]) for row in rows])
    pred = np.asarray([float(row["pred_speed_calc_mps"]) for row in rows])
    speed_err = pred - gt
    dir_err = np.asarray([float(row["direction_error_deg"]) for row in rows])
    conf = np.asarray([f(row, "recon_confidence") for row in rows])

    fig, axes = plt.subplots(2, 2, figsize=(13, 9), constrained_layout=True)
    ax = axes[0, 0]
    ax.hist(errs, bins=24, color="#3a6ea5", alpha=0.85)
    ax.axvline(float(np.median(errs)), color="#111111", linestyle="--", linewidth=1.2, label="median")
    ax.axvline(float(np.quantile(errs, 0.95)), color="#c43c39", linestyle="--", linewidth=1.2, label="p95")
    ax.set_title("Holdout Vector Error")
    ax.set_xlabel("m/s")
    ax.set_ylabel("points")
    ax.legend()

    ax = axes[0, 1]
    sc = ax.scatter(gt, pred, c=errs, s=30 + 55 * np.clip(conf, 0, 1), cmap="magma", alpha=0.82)
    lim = max(float(gt.max()), float(pred.max()), 1.0) + 5.0
    ax.plot([0, lim], [0, lim], color="#555555", linewidth=1.0)
    ax.set_xlim(0, lim)
    ax.set_ylim(0, lim)
    ax.set_title("Truth vs Reconstructed Speed")
    ax.set_xlabel("truth speed (m/s)")
    ax.set_ylabel("pred speed (m/s)")
    fig.colorbar(sc, ax=ax, label="vector error (m/s)")

    ax = axes[1, 0]
    ax.hist(speed_err, bins=24, color="#4f8f58", alpha=0.85)
    ax.axvline(0, color="#111111", linewidth=1.0)
    ax.axvline(float(np.mean(speed_err)), color="#c43c39", linestyle="--", linewidth=1.2, label="mean")
    ax.set_title("Speed Bias: Predicted - Truth")
    ax.set_xlabel("m/s")
    ax.set_ylabel("points")
    ax.legend()

    ax = axes[1, 1]
    ax.hist(dir_err, bins=24, color="#8064a2", alpha=0.85)
    ax.set_title("Direction Error")
    ax.set_xlabel("degrees")
    ax.set_ylabel("points")
    ax.text(
        0.03,
        0.95,
        "Direction is unstable when truth speed is near zero.",
        transform=ax.transAxes,
        va="top",
        fontsize=9,
        color="#333333",
    )
    fig.suptitle("Stage12 Stage4 Strict-TURB Holdout Diagnostics", fontsize=15)
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png, dpi=180)
    plt.close(fig)


def plot_map(rows: list[dict[str, Any]], out_png: Path) -> None:
    lon = np.asarray([f(row, "lon") for row in rows])
    lat = np.asarray([f(row, "lat") for row in rows])
    err = np.asarray([float(row["vector_error_calc_mps"]) for row in rows])
    conf = np.asarray([f(row, "recon_confidence") for row in rows])
    fig, ax = plt.subplots(figsize=(11, 8), constrained_layout=True)
    sc = ax.scatter(lon, lat, c=err, s=30 + 70 * np.clip(conf, 0, 1), cmap="magma", alpha=0.86, edgecolors="black", linewidths=0.25)
    ax.set_title("Holdout Point Map Colored by Vector Error")
    ax.set_xlabel("lon")
    ax.set_ylabel("lat")
    ax.grid(True, alpha=0.25)
    fig.colorbar(sc, ax=ax, label="vector error (m/s)")
    for row in sorted(rows, key=lambda item: float(item["vector_error_calc_mps"]), reverse=True)[:5]:
        ax.annotate(str(row["time_str"])[4:12], (f(row, "lon"), f(row, "lat")), fontsize=7, xytext=(3, 3), textcoords="offset points")
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png, dpi=180)
    plt.close(fig)


def point_summary_text(row: dict[str, Any]) -> str:
    return (
        f"{row['time_str']} | z/y/x={row['z']}/{row['y']}/{row['x']} | "
        f"GT {float(row['gt_speed_calc_mps']):.2f} m/s to {float(row['gt_dir_to_deg']):.1f} deg "
        f"(from {float(row['gt_dir_from_deg']):.1f} deg), "
        f"Pred {float(row['pred_speed_calc_mps']):.2f} m/s to {float(row['pred_dir_to_deg']):.1f} deg "
        f"(from {float(row['pred_dir_from_deg']):.1f} deg), "
        f"vector error {float(row['vector_error_calc_mps']):.2f} m/s, "
        f"speed bias {float(row['speed_error_pred_minus_gt_mps']):+.2f} m/s, "
        f"direction error {float(row['direction_error_deg']):.1f} deg"
    )


def plot_representative_grid(reps: dict[str, dict[str, Any]], out_png: Path) -> None:
    labels = ["best", "median", "p90", "worst", "good_two_label_example"]
    names = [label for label in labels if label in reps]
    gt_speed = [float(reps[label]["gt_speed_calc_mps"]) for label in names]
    pred_speed = [float(reps[label]["pred_speed_calc_mps"]) for label in names]
    vector_error = [float(reps[label]["vector_error_calc_mps"]) for label in names]
    dir_error = [float(reps[label]["direction_error_deg"]) for label in names]
    x = np.arange(len(names))
    width = 0.35
    fig, axes = plt.subplots(2, 1, figsize=(12, 8), constrained_layout=True)
    axes[0].bar(x - width / 2, gt_speed, width, label="truth speed", color="#3a6ea5")
    axes[0].bar(x + width / 2, pred_speed, width, label="pred speed", color="#c43c39")
    axes[0].set_ylabel("m/s")
    axes[0].set_title("Representative Holdout Speed Comparison")
    axes[0].set_xticks(x)
    axes[0].set_xticklabels([f"{label}\n{reps[label]['time_str']}" for label in names], fontsize=8)
    axes[0].legend()
    axes[1].bar(x - width / 2, vector_error, width, label="vector error", color="#8064a2")
    axes[1].bar(x + width / 2, dir_error, width, label="direction error deg", color="#4f8f58")
    axes[1].set_ylabel("m/s or deg")
    axes[1].set_title("Representative Error")
    axes[1].set_xticks(x)
    axes[1].set_xticklabels([f"{label}\n{reps[label]['time_str']}" for label in names], fontsize=8)
    axes[1].legend()
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png, dpi=180)
    plt.close(fig)


def plot_deep_dive(row: dict[str, Any], stage2_index: dict[str, dict[str, Any]], out_png: Path) -> dict[str, Any]:
    time_str = str(row["time_str"])
    stage2_row = stage2_index[time_str]
    npz_path = Path(stage2_row["multimodal_vox_path"])
    context = records_from_npz(npz_path, "context_wind_records")
    wind = records_from_npz(npz_path, "wind_records")
    x0, y0, z0 = int(float(row["x"])), int(float(row["y"])), int(float(row["z"]))
    radius = 32
    same_layer = [
        rec
        for rec in context
        if abs(int(rec.get("z", -999)) - z0) <= 1
        and abs(int(rec.get("x", -999)) - x0) <= radius
        and abs(int(rec.get("y", -999)) - y0) <= radius
    ]
    near_column = [
        rec
        for rec in context
        if abs(int(rec.get("x", -999)) - x0) <= 8 and abs(int(rec.get("y", -999)) - y0) <= 8
    ]
    nearest = []
    try:
        nearest = json.loads(str(row.get("nearest_observations_json", "[]")))
    except Exception:
        nearest = []

    fig, axes = plt.subplots(1, 3, figsize=(17, 6), constrained_layout=True)
    ax = axes[0]
    if same_layer:
        xs = np.asarray([float(rec["x"]) for rec in same_layer])
        ys = np.asarray([float(rec["y"]) for rec in same_layer])
        us = np.asarray([float(rec["u"]) for rec in same_layer])
        vs = np.asarray([float(rec["v"]) for rec in same_layer])
        weights = np.asarray([float(rec.get("obs_conf_v2", rec.get("obs_conf", 0.2)) or 0.2) for rec in same_layer])
        step = max(1, len(xs) // 180)
        ax.quiver(xs[::step], ys[::step], us[::step], vs[::step], weights[::step], cmap="viridis", scale=1100, width=0.003)
    gt_u, gt_v, pred_u, pred_v = f(row, "gt_u"), f(row, "gt_v"), f(row, "pred_u"), f(row, "pred_v")
    ax.scatter([x0], [y0], marker="*", s=180, color="black", label="holdout point", zorder=5)
    ax.quiver([x0], [y0], [gt_u], [gt_v], color="#2ca02c", scale=650, width=0.008, label="truth")
    ax.quiver([x0], [y0], [pred_u], [pred_v], color="#d62728", scale=650, width=0.008, label="prediction")
    if nearest:
        ax.scatter([float(rec["x"]) for rec in nearest], [float(rec["y"]) for rec in nearest], marker="x", s=80, color="#1f77b4", label="nearest support")
    ax.set_xlim(x0 - radius, x0 + radius)
    ax.set_ylim(y0 - radius, y0 + radius)
    ax.set_title(f"{time_str} local support near z={z0}")
    ax.set_xlabel("Stage2 x voxel")
    ax.set_ylabel("Stage2 y voxel")
    ax.grid(True, alpha=0.25)
    ax.legend(fontsize=8)

    ax = axes[1]
    labels = ["u", "v", "speed"]
    gt_vals = [gt_u, gt_v, float(row["gt_speed_calc_mps"])]
    pred_vals = [pred_u, pred_v, float(row["pred_speed_calc_mps"])]
    xx = np.arange(len(labels))
    ax.bar(xx - 0.18, gt_vals, 0.36, label="truth", color="#2ca02c")
    ax.bar(xx + 0.18, pred_vals, 0.36, label="prediction", color="#d62728")
    ax.axhline(0, color="#333333", linewidth=0.8)
    ax.set_xticks(xx)
    ax.set_xticklabels(labels)
    ax.set_ylabel("m/s")
    ax.set_title(
        f"Error {float(row['vector_error_calc_mps']):.1f} m/s; "
        f"dir err {float(row['direction_error_deg']):.1f} deg"
    )
    ax.legend()

    ax = axes[2]
    if near_column:
        zs = np.asarray([float(rec["z"]) * 500.0 for rec in near_column])
        speeds = np.asarray([math.hypot(float(rec["u"]), float(rec["v"])) for rec in near_column])
        colors = np.asarray([float(rec.get("obs_conf_v2", rec.get("obs_conf", 0.2)) or 0.2) for rec in near_column])
        sc = ax.scatter(speeds, zs, c=colors, cmap="viridis", alpha=0.65, s=18)
        fig.colorbar(sc, ax=ax, label="support confidence")
    ax.scatter([float(row["gt_speed_calc_mps"])], [float(row["alt_m"])], marker="*", s=160, color="#2ca02c", label="truth")
    ax.scatter([float(row["pred_speed_calc_mps"])], [float(row["alt_m"])], marker="X", s=120, color="#d62728", label="prediction")
    ax.set_xlabel("speed (m/s)")
    ax.set_ylabel("altitude proxy / m")
    ax.set_title("Nearby context vertical speed profile")
    ax.grid(True, alpha=0.25)
    ax.legend(fontsize=8)
    fig.suptitle("Representative Stage4 Metrics-Only Deep Dive: context-only holdout reconstruction", fontsize=14)
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png, dpi=180)
    plt.close(fig)

    return {
        "time_str": time_str,
        "stage2_npz": str(npz_path),
        "context_records_total": len(context),
        "wind_records_total": len(wind),
        "same_layer_context_records_in_local_window": len(same_layer),
        "near_column_context_records": len(near_column),
        "nearest_observations": nearest,
        "point_summary": point_summary_text(row),
    }


def write_markdown(
    rows: list[dict[str, Any]],
    summary: dict[str, Any],
    reps: dict[str, dict[str, Any]],
    deep: dict[str, Any],
    paths: dict[str, Path],
) -> None:
    md = f"""# Stage4 Holdout Diagnostics and Stage13 Supplement

Generated from the metrics-only Stage12 Stage4 output. This file does not claim to visualize a saved full 3D `recon_u/v` field; it visualizes the available Stage4 point departures, frame diagnostics, and Stage2 support observations.

## Stage13 Plan Comparison

The original Stage13 in `{PLAN}` is a multi-time-scale ablation: fine / 15 min / 30 min / 60 min crossed with E0-E6 (`no AMDAR`, `S only`, `S+A`, `S+A+B`, `S+A+B+C super-ob`, `legacy`, `old fixed 0.35`). My earlier recommendation is not a different Stage13; it is a stricter interpretation after the Stage12 result.

The necessary supplement is:

1. The current Stage12 baseline is **not** a true E0 no-AMDAR baseline, because `context_wind_records` already contains AMDAR support. It is better named `B0_stage12_strict_TURB_truth_with_AMDAR_support_context`.
2. Add an explicit `E0_true_no_AMDAR_support`: remove AMDAR from `context_wind_records` and keep only TURB/allowed non-AMDAR support, so the E4-vs-E0 improvement is meaningful.
3. Keep AMDAR out of `wind_records` for all Stage13 experiments. A/B/C AMDAR must enter only as support/super-ob fusion observations, not strict truth.
4. For E2/E3/E4, compare raw Stage11 support versus Stage10 v2 super-ob support. This is now important because Stage12 shows `137 / 148` evaluated holdout points are context-only nearest-support cases.
5. Add error-regime gates beyond mean RMSE: calm-truth false strong-wind cases, strong-truth underprediction, context-only high-error count, role-conflict count, no-claim/reliability calibration, and batch dominance.
6. Treat legacy E5 as a compatibility appendix, not the primary conservative truth benchmark.

## Holdout Evaluation Summary

- Holdout points: `{summary['holdout_points']}`
- Vector error mean / median / p90 / p95 / max: `{summary['vector_error_mps']['mean']:.3f}` / `{summary['vector_error_mps']['median']:.3f}` / `{summary['vector_error_mps']['p90']:.3f}` / `{summary['vector_error_mps']['p95']:.3f}` / `{summary['vector_error_mps']['max']:.3f}` m/s
- Speed bias predicted-minus-truth mean / median / p95: `{summary['speed_error_pred_minus_gt_mps']['mean']:.3f}` / `{summary['speed_error_pred_minus_gt_mps']['median']:.3f}` / `{summary['speed_error_pred_minus_gt_mps']['p95']:.3f}` m/s
- Direction error mean / median, all points: `{summary['direction_error_deg']['mean_all']:.3f}` / `{summary['direction_error_deg']['median_all']:.3f}` degrees
- Direction error mean / median, truth speed >=5 m/s: `{summary['direction_error_deg']['mean_gt_speed_ge_5']:.3f}` / `{summary['direction_error_deg']['median_gt_speed_ge_5']:.3f}` degrees
- Truth speed mean / median / max: `{summary['gt_speed_mps']['mean']:.3f}` / `{summary['gt_speed_mps']['median']:.3f}` / `{summary['gt_speed_mps']['max']:.3f}` m/s
- Predicted speed mean / median / max: `{summary['pred_speed_mps']['mean']:.3f}` / `{summary['pred_speed_mps']['median']:.3f}` / `{summary['pred_speed_mps']['max']:.3f}` m/s
- Context-only nearest support points: `{summary['context_only_nearest_support_points']}`
- High vector error >=30 m/s points: `{summary['high_vector_error_ge_30mps_points']}`

Wind direction convention in the derived CSV:

- `*_dir_to_deg`: vector direction toward which wind blows, computed from `u` eastward and `v` northward.
- `*_dir_from_deg`: meteorological source direction, equal to `dir_to + 180 deg`.
- Direction is not physically stable when truth speed is near zero; use speed/component errors for calm cases.

## Representative Points

"""
    for name, row in reps.items():
        md += f"- `{name}`: {point_summary_text(row)}; reasons=`{row.get('qc_review_reasons', '')}`\n"

    md += f"""
## Detailed Frame: `{deep['time_str']}`

Chosen as a high-error context-only case to explain the current Stage12 weakness.

- Stage2 NPZ: `{deep['stage2_npz']}`
- `wind_records_total`: `{deep['wind_records_total']}`. These are strict current truth candidates; Stage4 holds out at least one for evaluation.
- `context_records_total`: `{deep['context_records_total']}`. These are the actual dominant support observations for reconstruction.
- Same-layer local context records in plotted window: `{deep['same_layer_context_records_in_local_window']}`
- Near-column context records for vertical profile: `{deep['near_column_context_records']}`
- Point: {deep['point_summary']}

Interpretation: this frame is not failing because Stage4 has no support. It is failing because the nearest available support is context-only and much stronger than the strict TURB truth at the holdout point. The predicted direction is close, but speed is badly overestimated, which produces almost all of the vector error.

## Output Files

- Derived point CSV: `{paths['derived_csv']}`
- JSON summary: `{paths['summary_json']}`
- Overview plot: `{paths['overview_png']}`
- Holdout map plot: `{paths['map_png']}`
- Representative point plot: `{paths['representative_png']}`
- Deep-dive frame plot: `{paths['deep_dive_png']}`
"""
    paths["markdown"].write_text(md, encoding="utf-8")


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rows, summary = enrich_point_departures()
    reps = representative_rows(rows)
    stage2_index = load_stage2_index()

    derived_csv = OUT_DIR / "stage4_holdout_point_wind_speed_direction_departures.csv"
    fieldnames = list(rows[0].keys())
    write_csv(derived_csv, rows, fieldnames)

    overview_png = OUT_DIR / "stage4_holdout_error_overview.png"
    map_png = OUT_DIR / "stage4_holdout_error_map.png"
    representative_png = OUT_DIR / "stage4_representative_points_speed_error.png"
    deep_dive_png = OUT_DIR / "stage4_deep_dive_20260209145400.png"
    plot_overview(rows, overview_png)
    plot_map(rows, map_png)
    plot_representative_grid(reps, representative_png)
    deep = plot_deep_dive(reps["worst"], stage2_index, deep_dive_png)

    summary_json = OUT_DIR / "stage4_holdout_diagnostics_summary.json"
    output_summary = {
        "summary": summary,
        "representative_rows": {name: point_summary_text(row) for name, row in reps.items()},
        "deep_dive": deep,
        "outputs": {
            "derived_csv": str(derived_csv),
            "overview_png": str(overview_png),
            "map_png": str(map_png),
            "representative_png": str(representative_png),
            "deep_dive_png": str(deep_dive_png),
        },
    }
    summary_json.write_text(json.dumps(output_summary, ensure_ascii=False, indent=2), encoding="utf-8")
    paths = {
        "derived_csv": derived_csv,
        "summary_json": summary_json,
        "overview_png": overview_png,
        "map_png": map_png,
        "representative_png": representative_png,
        "deep_dive_png": deep_dive_png,
        "markdown": OUT_DIR / "stage4_holdout_diagnostics_and_stage13_supplement.md",
    }
    write_markdown(rows, summary, reps, deep, paths)
    print(json.dumps({"out_dir": str(OUT_DIR), "summary": summary, "outputs": {k: str(v) for k, v in paths.items()}}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
