"""Build point-level datasets for Stage5 residual PINN report experiments.

This script intentionally starts with a point-level report dataset. It does not
write a 3D residual field and it does not change Stage4 official recon outputs.
The split is frame/time based so validation and test points cannot share a
frame with training points.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT_DIR = Path(__file__).resolve().parents[3]
STAGE_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
if str(STAGE_DIR) not in sys.path:
    sys.path.insert(0, str(STAGE_DIR))


GRID_Z = 31.0
GRID_Y = 525.0
GRID_X = 775.0
ALT_MAX_M = 15000.0


TRUTH_COLUMNS = {
    "gt_u",
    "gt_v",
    "gt_speed",
    "u_error",
    "v_error",
    "abs_u_error",
    "abs_v_error",
    "vector_error",
    "error_to_truth_speed_ratio",
    "frame_rmse_vector",
    "frame_mae_vector",
}

# These point-neighbor fields are useful offline diagnostics but they are
# derived from holdout point errors, so they are excluded from model features.
HOLDOUT_DIAGNOSTIC_COLUMNS = {
    "point_neighbor_mean_vector_error",
    "point_neighbor_min_vector_error",
    "point_neighbor_weighted_vector_error",
    "point_neighbor_std_vector_error",
    "representativeness_gap_point_minus_min_mps",
    "qc_review_flag",
    "qc_review_reasons",
}


BASE_NUMERIC_FEATURES = [
    "z",
    "y",
    "x",
    "lat",
    "lon",
    "alt_m",
    "pred_u",
    "pred_v",
    "pred_speed",
    "recon_confidence",
    "obs_count",
    "obs_conf",
    "nearest_role_gap_mps",
    "nearest_current_count",
    "nearest_context_count",
    "recon_vertical_jump_mps",
    "vertical_speed_gap_mps",
    "vertical_neighbor_max_speed_mps",
    "role_conflict_component_gap_at_point_mps",
    "role_conflict_threshold_at_point_mps",
    "role_conflict_context_factor_at_point",
    "role_conflict_current_density_at_point",
    "role_conflict_context_time_conf_at_point",
    "role_conflict_context_weight_at_point",
    "role_conflict_context_removed_weight_at_point",
    "nearest_train_distance_vox",
    "nearest_train_u",
    "nearest_train_v",
    "nearest_train_base_weight",
    "adaptive_current_support",
    "adaptive_context_support",
    "localization_radius_xy",
    "localization_sigma_xy",
    "localization_radius_z",
    "localization_sigma_z",
]


BOOL_FEATURES = [
    "role_overlap_at_point",
    "role_conflict_at_point",
]


def _read_manifest_splits(path: Path | None) -> dict[str, str]:
    if path is None or not path.exists():
        return {}
    manifest = json.loads(path.read_text(encoding="utf-8"))
    out: dict[str, str] = {}
    for row in manifest.get("frames", []):
        time_str = str(row.get("time_str", ""))
        split = str(row.get("split", ""))
        if time_str and split:
            out[time_str] = split
    return out


def _fallback_splits(times: list[str], train_fraction: float, val_fraction: float) -> dict[str, str]:
    ordered = sorted(dict.fromkeys(str(t) for t in times))
    n = len(ordered)
    n_train = int(round(n * float(train_fraction)))
    n_val = int(round(n * float(val_fraction)))
    n_train = max(0, min(n, n_train))
    n_val = max(0, min(n - n_train, n_val))
    out: dict[str, str] = {}
    for idx, time_str in enumerate(ordered):
        if idx < n_train:
            out[time_str] = "train"
        elif idx < n_train + n_val:
            out[time_str] = "val"
        else:
            out[time_str] = "test"
    return out


def _as_float_series(df: pd.DataFrame, col: str, default: float = 0.0) -> pd.Series:
    if col not in df.columns:
        return pd.Series(default, index=df.index, dtype="float64")
    return pd.to_numeric(df[col], errors="coerce").fillna(default).astype("float64")


def _as_bool_float(df: pd.DataFrame, col: str) -> pd.Series:
    if col not in df.columns:
        return pd.Series(0.0, index=df.index, dtype="float64")
    values = df[col]
    if values.dtype == bool:
        return values.astype("float64")
    return values.astype(str).str.lower().isin({"1", "true", "yes"}).astype("float64")


def _parse_time_features(time_str: str) -> tuple[float, float, float, float]:
    try:
        dt = datetime.strptime(str(time_str), "%Y%m%d%H%M%S")
    except ValueError:
        return (0.0, 1.0, 0.0, 1.0)
    hour_angle = 2.0 * math.pi * (dt.hour + dt.minute / 60.0) / 24.0
    day_angle = 2.0 * math.pi * max(0, dt.timetuple().tm_yday - 1) / 366.0
    return (
        math.sin(hour_angle),
        math.cos(hour_angle),
        math.sin(day_angle),
        math.cos(day_angle),
    )


def _truth_speed_bin(speed: float) -> str:
    if speed < 5.0:
        return "0-5mps_calm"
    if speed < 15.0:
        return "5-15mps_light"
    if speed < 30.0:
        return "15-30mps_moderate"
    if speed < 60.0:
        return "30-60mps_strong"
    return "60mps_plus_extreme"


def _alt_bin(alt_m: float) -> str:
    if alt_m < 3000.0:
        return "0-3km"
    if alt_m < 6000.0:
        return "3-6km"
    if alt_m < 9000.0:
        return "6-9km"
    if alt_m < 12000.0:
        return "9-12km"
    return "12km_plus"


def _source_role_features(df: pd.DataFrame) -> pd.DataFrame:
    source = df.get("nearest_train_source_role", pd.Series("", index=df.index)).fillna("").astype(str)
    return pd.DataFrame(
        {
            "nearest_source_current_train": source.str.contains("current", case=False, regex=False).astype("float64"),
            "nearest_source_context": source.str.contains("context", case=False, regex=False).astype("float64"),
            "nearest_source_unknown": (source == "").astype("float64"),
        },
        index=df.index,
    )


def _build_truth_free_scores(df: pd.DataFrame) -> pd.DataFrame:
    dist = _as_float_series(df, "nearest_train_distance_vox", 99.0)
    role_gap = _as_float_series(df, "nearest_role_gap_mps", 0.0)
    conf = _as_float_series(df, "recon_confidence", 0.0)
    cur_count = _as_float_series(df, "nearest_current_count", 0.0)
    ctx_count = _as_float_series(df, "nearest_context_count", 0.0)
    vertical_gap = np.maximum(
        _as_float_series(df, "vertical_speed_gap_mps", 0.0).to_numpy(),
        _as_float_series(df, "recon_vertical_jump_mps", 0.0).to_numpy(),
    )
    alt = _as_float_series(df, "alt_m", 0.0)
    pred_speed = _as_float_series(df, "pred_speed", 0.0)
    source_context = _source_role_features(df)["nearest_source_context"].to_numpy()

    dist_score = np.clip((dist.to_numpy() - 2.0) / 4.0, 0.0, 1.0)
    role_score = np.clip((role_gap.to_numpy() - 20.0) / 20.0, 0.0, 1.0)
    low_conf_score = 1.0 - np.clip(conf.to_numpy() / 0.20, 0.0, 1.0)
    support_score = 1.0 - np.clip((cur_count.to_numpy() + 0.5 * ctx_count.to_numpy()) / 3.0, 0.0, 1.0)
    vertical_score = np.clip(vertical_gap / 30.0, 0.0, 1.0)
    high_alt_score = (alt.to_numpy() >= 12000.0).astype("float64")
    context_only_score = ((cur_count.to_numpy() <= 0.0) & (source_context > 0.0)).astype("float64")
    high_speed_score = np.clip((pred_speed.to_numpy() - 45.0) / 45.0, 0.0, 1.0)

    rep_risk = np.clip(
        0.23 * dist_score
        + 0.18 * role_score
        + 0.18 * low_conf_score
        + 0.16 * support_score
        + 0.12 * vertical_score
        + 0.06 * high_alt_score
        + 0.05 * context_only_score
        + 0.02 * high_speed_score,
        0.0,
        1.0,
    )
    sigma_rep = np.clip(2.0 + 22.0 * rep_risk + 4.0 * high_alt_score, 2.0, 32.0)
    tail_prob = np.clip(rep_risk**2.2, 0.0, 1.0)
    conf_factor = np.clip((conf.to_numpy() - 0.02) / 0.18, 0.05, 1.0)
    role_factor = np.clip(1.0 - 0.65 * role_score, 0.10, 1.0)
    support_factor = np.clip(1.0 - 0.55 * support_score, 0.15, 1.0)
    gate = np.clip((1.0 - 0.80 * rep_risk) * conf_factor * role_factor * support_factor, 0.0, 0.85)
    sample_weight = 1.0 / np.maximum(2.2**2 + sigma_rep**2, 1.0)

    return pd.DataFrame(
        {
            "representation_risk_score": rep_risk,
            "sigma_rep_proxy_mps": sigma_rep,
            "tail_probability_proxy": tail_prob,
            "residual_gate_initial": gate,
            "sample_weight_raw": sample_weight,
            "distance_risk_score": dist_score,
            "role_gap_risk_score": role_score,
            "low_conf_risk_score": low_conf_score,
            "support_risk_score": support_score,
            "vertical_risk_score": vertical_score,
            "context_only_risk_flag": context_only_score,
            "high_altitude_flag": high_alt_score,
            "pred_light_wind_flag": ((pred_speed.to_numpy() >= 5.0) & (pred_speed.to_numpy() < 15.0)).astype("float64"),
        },
        index=df.index,
    )


def _build_features(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    parts: list[pd.DataFrame] = []
    numeric = pd.DataFrame(index=df.index)
    for col in BASE_NUMERIC_FEATURES:
        numeric[col] = _as_float_series(df, col, 0.0)
    for col in BOOL_FEATURES:
        numeric[col] = _as_bool_float(df, col)
    numeric["z_norm"] = np.clip((numeric["z"] / max(1.0, GRID_Z - 1.0)) * 2.0 - 1.0, -1.0, 1.0)
    numeric["y_norm"] = np.clip((numeric["y"] / max(1.0, GRID_Y - 1.0)) * 2.0 - 1.0, -1.0, 1.0)
    numeric["x_norm"] = np.clip((numeric["x"] / max(1.0, GRID_X - 1.0)) * 2.0 - 1.0, -1.0, 1.0)
    numeric["alt_norm"] = np.clip(numeric["alt_m"] / ALT_MAX_M, 0.0, 1.2)
    numeric["pred_speed_norm"] = np.clip(numeric["pred_speed"] / 120.0, 0.0, 2.0)
    numeric["support_total"] = numeric["nearest_current_count"] + numeric["nearest_context_count"]
    numeric["support_log1p"] = np.log1p(np.maximum(numeric["support_total"], 0.0))
    time_features = np.array([_parse_time_features(t) for t in df["time_str"].astype(str)], dtype=np.float64)
    numeric["hour_sin"] = time_features[:, 0]
    numeric["hour_cos"] = time_features[:, 1]
    numeric["day_sin"] = time_features[:, 2]
    numeric["day_cos"] = time_features[:, 3]
    parts.append(numeric)
    parts.append(_source_role_features(df))
    parts.append(_build_truth_free_scores(df))
    features = pd.concat(parts, axis=1)
    excluded = TRUTH_COLUMNS | HOLDOUT_DIAGNOSTIC_COLUMNS
    feature_names = [col for col in features.columns if col not in excluded]
    features = features[feature_names].replace([np.inf, -np.inf], np.nan).fillna(0.0)
    return features.astype("float32"), feature_names


def _write_split_npz(out_path: Path, frame_df: pd.DataFrame, features: pd.DataFrame, feature_names: list[str]) -> None:
    idx = frame_df.index.to_numpy(dtype=np.int64)
    target_delta_u = (_as_float_series(frame_df, "gt_u") - _as_float_series(frame_df, "pred_u")).to_numpy(dtype=np.float32)
    target_delta_v = (_as_float_series(frame_df, "gt_v") - _as_float_series(frame_df, "pred_v")).to_numpy(dtype=np.float32)
    np.savez_compressed(
        out_path,
        row_id=idx,
        x=features.loc[idx, feature_names].to_numpy(dtype=np.float32),
        target_delta_u=target_delta_u,
        target_delta_v=target_delta_v,
        gt_u=_as_float_series(frame_df, "gt_u").to_numpy(dtype=np.float32),
        gt_v=_as_float_series(frame_df, "gt_v").to_numpy(dtype=np.float32),
        gt_speed=_as_float_series(frame_df, "gt_speed").to_numpy(dtype=np.float32),
        pred_u=_as_float_series(frame_df, "pred_u").to_numpy(dtype=np.float32),
        pred_v=_as_float_series(frame_df, "pred_v").to_numpy(dtype=np.float32),
        pred_speed=_as_float_series(frame_df, "pred_speed").to_numpy(dtype=np.float32),
        residual_gate_initial=features.loc[idx, "residual_gate_initial"].to_numpy(dtype=np.float32),
        sample_weight_raw=features.loc[idx, "sample_weight_raw"].to_numpy(dtype=np.float32),
        sigma_rep_proxy_mps=features.loc[idx, "sigma_rep_proxy_mps"].to_numpy(dtype=np.float32),
        feature_names=np.asarray(feature_names),
    )


def _write_meta_csv(path: Path, df: pd.DataFrame) -> None:
    meta_cols = [
        "row_id",
        "split",
        "time_str",
        "z",
        "y",
        "x",
        "lat",
        "lon",
        "alt_m",
        "gt_u",
        "gt_v",
        "gt_speed",
        "pred_u",
        "pred_v",
        "pred_speed",
        "vector_error",
        "truth_speed_bin",
        "altitude_bin",
    ]
    present = [col for col in meta_cols if col in df.columns]
    df[present].to_csv(path, index=False)


def _metric_summary(df: pd.DataFrame) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for split, group in df.groupby("split"):
        err = pd.to_numeric(group["vector_error"], errors="coerce").dropna().to_numpy(dtype=np.float64)
        out[str(split)] = {
            "points": int(len(group)),
            "frames": int(group["time_str"].nunique()),
            "baseline_vector_rmse": float(np.sqrt(np.mean(err**2))) if err.size else 0.0,
            "baseline_vector_mae": float(np.mean(err)) if err.size else 0.0,
            "high_error_ge30_count": int(np.count_nonzero(err >= 30.0)),
        }
    return out


def _write_summary_md(path: Path, summary: dict[str, Any], feature_names: list[str]) -> None:
    lines = [
        "# Stage5 Residual PINN Point Dataset",
        "",
        "This dataset is point-level report-only input for residual PINN experiments.",
        "It does not alter Stage4 recon fields and it uses frame/time splits.",
        "",
        "## Leakage Boundary",
        "",
        "- `gt_u/gt_v/vector_error` are labels or evaluation columns, not model features.",
        "- `qc_review_flag`, `point_neighbor_*_vector_error`, and `representativeness_gap_point_minus_min_mps` are excluded from features.",
        "- `motion_records` / `context_motion_records` are not used as wind labels.",
        "- CMA/NWP fields, if added later, are weak background features only.",
        "",
        "## Splits",
        "",
        "| split | frames | points | baseline RMSE | baseline MAE | >=30mps tail |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for split in ("train", "val", "test"):
        row = summary["split_metrics"].get(split, {})
        lines.append(
            f"| `{split}` | {int(row.get('frames', 0))} | {int(row.get('points', 0))} | "
            f"{float(row.get('baseline_vector_rmse', 0.0)):.6f} | "
            f"{float(row.get('baseline_vector_mae', 0.0)):.6f} | "
            f"{int(row.get('high_error_ge30_count', 0))} |"
        )
    lines.extend(
        [
            "",
            "## Feature Schema",
            "",
            f"- feature count: `{len(feature_names)}`",
            f"- feature list: `{', '.join(feature_names)}`",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build point-level Stage5 residual PINN report dataset.")
    parser.add_argument("--point-departures", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, default=None)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--mode", choices=["point_report"], default="point_report")
    parser.add_argument("--train-fraction", type=float, default=0.70)
    parser.add_argument("--val-fraction", type=float, default=0.15)
    args = parser.parse_args()

    df = pd.read_csv(args.point_departures)
    if "time_str" not in df.columns:
        raise ValueError("point departures CSV must contain time_str")
    df = df.copy()
    df["time_str"] = df["time_str"].astype(str)
    split_map = _read_manifest_splits(args.manifest)
    if not split_map:
        split_map = _fallback_splits(df["time_str"].tolist(), float(args.train_fraction), float(args.val_fraction))
    df["split"] = df["time_str"].map(split_map).fillna("test")
    df["row_id"] = np.arange(len(df), dtype=np.int64)
    df.index = df["row_id"].to_numpy(dtype=np.int64)
    gt_speed = _as_float_series(df, "gt_speed", 0.0)
    alt = _as_float_series(df, "alt_m", 0.0)
    df["truth_speed_bin"] = [_truth_speed_bin(float(v)) for v in gt_speed]
    df["altitude_bin"] = [_alt_bin(float(v)) for v in alt]

    features, feature_names = _build_features(df)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    schema = {
        "mode": args.mode,
        "point_departures": str(args.point_departures),
        "manifest": str(args.manifest) if args.manifest else "",
        "feature_names": feature_names,
        "excluded_truth_columns": sorted(TRUTH_COLUMNS),
        "excluded_holdout_diagnostic_columns": sorted(HOLDOUT_DIAGNOSTIC_COLUMNS),
        "truth_free_feature_policy": True,
        "report_only_no_recon_change": True,
        "official_holdout_points_retained": int(len(df)),
    }
    (args.out_dir / "feature_schema.json").write_text(json.dumps(schema, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_meta_csv(args.out_dir / "metadata.csv", df)

    for split in ("train", "val", "test"):
        split_df = df[df["split"] == split]
        _write_split_npz(args.out_dir / f"features_{split}.npz", split_df, features, feature_names)

    summary = {
        "points": int(len(df)),
        "frames": int(df["time_str"].nunique()),
        "split_counts": {str(k): int(v) for k, v in df["split"].value_counts().to_dict().items()},
        "split_metrics": _metric_summary(df),
        "feature_count": int(len(feature_names)),
        "truth_free_feature_policy": True,
        "report_only_no_recon_change": True,
    }
    (args.out_dir / "dataset_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_summary_md(args.out_dir / "dataset_summary.md", summary, feature_names)
    print(args.out_dir / "dataset_summary.md")


if __name__ == "__main__":
    main()
