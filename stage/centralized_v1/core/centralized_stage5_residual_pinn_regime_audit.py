"""Audit where a Stage5 residual PINN point report helps or hurts.

The audit joins point predictions with the dataset metadata and truth-free
feature matrix. It is diagnostic only: it can inspect truth-speed/error buckets
after evaluation, but those labels are not model inputs.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
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


def _load_features(dataset_dir: Path) -> pd.DataFrame:
    schema = json.loads((dataset_dir / "feature_schema.json").read_text(encoding="utf-8"))
    feature_names = list(schema["feature_names"])
    rows: list[pd.DataFrame] = []
    for split in ("train", "val", "test"):
        with np.load(dataset_dir / f"features_{split}.npz", allow_pickle=False) as data:
            frame = pd.DataFrame(data["x"], columns=feature_names)
            frame["row_id"] = data["row_id"].astype(np.int64)
            frame["feature_split"] = split
            rows.append(frame)
    return pd.concat(rows, ignore_index=True)


def _bin_numeric(values: pd.Series, edges: list[float], labels: list[str], missing: str = "missing") -> pd.Series:
    series = pd.to_numeric(values, errors="coerce")
    out = pd.Series(missing, index=series.index, dtype="object")
    for i, label in enumerate(labels):
        lo = edges[i]
        hi = edges[i + 1]
        if i == 0:
            mask = series < hi
        elif i == len(labels) - 1:
            mask = series >= lo
        else:
            mask = (series >= lo) & (series < hi)
        out.loc[mask.fillna(False)] = label
    return out


def _build_buckets(df: pd.DataFrame) -> dict[str, pd.Series]:
    vertical = np.maximum(
        pd.to_numeric(df.get("vertical_speed_gap_mps", 0.0), errors="coerce").fillna(0.0),
        pd.to_numeric(df.get("recon_vertical_jump_mps", 0.0), errors="coerce").fillna(0.0),
    )
    source = np.where(
        pd.to_numeric(df.get("nearest_source_current_train", 0.0), errors="coerce").fillna(0.0) > 0.5,
        "current_train",
        np.where(
            pd.to_numeric(df.get("nearest_source_context", 0.0), errors="coerce").fillna(0.0) > 0.5,
            "context",
            "unknown",
        ),
    )
    return {
        "altitude_bin": df["altitude_bin"].astype(str),
        "truth_speed_bin": df["truth_speed_bin"].astype(str),
        "pred_speed_bin": _bin_numeric(
            df["pred_speed"],
            [0.0, 5.0, 15.0, 30.0, 60.0, np.inf],
            ["0-5mps", "5-15mps", "15-30mps", "30-60mps", "60mps_plus"],
        ),
        "nearest_distance_bin": _bin_numeric(
            df["nearest_train_distance_vox"],
            [0.0, 2.0, 4.0, 6.0, np.inf],
            ["lt2vox", "2-4vox", "4-6vox", "ge6vox"],
        ),
        "current_count_bin": _bin_numeric(
            df["nearest_current_count"],
            [0.0, 1.0, 2.0, 4.0, np.inf],
            ["count0", "count1", "count2-3", "count_ge4"],
        ),
        "context_count_bin": _bin_numeric(
            df["nearest_context_count"],
            [0.0, 1.0, 3.0, 10.0, np.inf],
            ["ctx0", "ctx1-2", "ctx3-9", "ctx_ge10"],
        ),
        "support_total_bin": _bin_numeric(
            df["support_total"],
            [0.0, 2.0, 5.0, 20.0, np.inf],
            ["support_lt2", "support2-4", "support5-19", "support_ge20"],
        ),
        "role_gap_bin": _bin_numeric(
            df["nearest_role_gap_mps"],
            [0.0, 10.0, 20.0, 30.0, np.inf],
            ["gap_lt10", "gap10-20", "gap20-30", "gap_ge30"],
        ),
        "recon_conf_bin": _bin_numeric(
            df["recon_confidence"],
            [0.0, 0.05, 0.2, 0.8, np.inf],
            ["conf_lt0p05", "conf0p05-0p2", "conf0p2-0p8", "conf_ge0p8"],
        ),
        "representation_risk_bin": _bin_numeric(
            df["representation_risk_score"],
            [0.0, 0.10, 0.20, 0.35, 0.50, np.inf],
            ["risk_lt0p10", "risk0p10-0p20", "risk0p20-0p35", "risk0p35-0p50", "risk_ge0p50"],
        ),
        "sigma_rep_bin": _bin_numeric(
            df["sigma_rep_proxy_mps"],
            [0.0, 5.0, 10.0, 20.0, np.inf],
            ["sigma_lt5", "sigma5-10", "sigma10-20", "sigma_ge20"],
        ),
        "gate_bin": _bin_numeric(
            df["residual_gate"],
            [0.0, 0.05, 0.2, 0.5, np.inf],
            ["gate_lt0p05", "gate0p05-0p2", "gate0p2-0p5", "gate_ge0p5"],
        ),
        "vertical_gap_bin": _bin_numeric(
            pd.Series(vertical, index=df.index),
            [0.0, 5.0, 15.0, 30.0, np.inf],
            ["vgap_lt5", "vgap5-15", "vgap15-30", "vgap_ge30"],
        ),
        "nearest_source_role": pd.Series(source, index=df.index),
        "role_conflict_flag": np.where(
            pd.to_numeric(df.get("role_conflict_at_point", 0.0), errors="coerce").fillna(0.0) > 0.5,
            "role_conflict",
            "no_role_conflict",
        ),
        "context_only_flag": np.where(
            pd.to_numeric(df.get("context_only_risk_flag", 0.0), errors="coerce").fillna(0.0) > 0.5,
            "context_only",
            "not_context_only",
        ),
        "high_altitude_flag": np.where(
            pd.to_numeric(df.get("high_altitude_flag", 0.0), errors="coerce").fillna(0.0) > 0.5,
            "high_altitude",
            "not_high_altitude",
        ),
        "pred_light_wind_flag": np.where(
            pd.to_numeric(df.get("pred_light_wind_flag", 0.0), errors="coerce").fillna(0.0) > 0.5,
            "pred_light_wind",
            "not_pred_light_wind",
        ),
    }


def _metrics(group: pd.DataFrame) -> dict[str, Any]:
    base = pd.to_numeric(group["baseline_vector_error"], errors="coerce").fillna(0.0).to_numpy(dtype=np.float64)
    cand = pd.to_numeric(group["candidate_vector_error"], errors="coerce").fillna(0.0).to_numpy(dtype=np.float64)
    delta = cand - base
    gt_speed = pd.to_numeric(group["gt_speed"], errors="coerce").fillna(0.0).to_numpy(dtype=np.float64)
    light = (gt_speed >= 5.0) & (gt_speed < 15.0)
    floor = np.maximum(gt_speed, 10.0)

    def rmse(values: np.ndarray) -> float:
        return float(np.sqrt(np.mean(values**2))) if values.size else 0.0

    def mean(values: np.ndarray) -> float:
        return float(np.mean(values)) if values.size else 0.0

    def q(values: np.ndarray, p: float) -> float:
        return float(np.quantile(values, p)) if values.size else 0.0

    return {
        "points": int(len(group)),
        "baseline_rmse": rmse(base),
        "candidate_rmse": rmse(cand),
        "delta_rmse": rmse(cand) - rmse(base),
        "baseline_mae": mean(base),
        "candidate_mae": mean(cand),
        "mean_delta_error": mean(delta),
        "median_delta_error": q(delta, 0.50),
        "baseline_p95": q(base, 0.95),
        "candidate_p95": q(cand, 0.95),
        "baseline_p99": q(base, 0.99),
        "candidate_p99": q(cand, 0.99),
        "improved_points": int(np.count_nonzero(delta < -1e-6)),
        "worsened_points": int(np.count_nonzero(delta > 1e-6)),
        "unchanged_points": int(np.count_nonzero(np.abs(delta) <= 1e-6)),
        "max_improvement": float(np.min(delta)) if delta.size else 0.0,
        "max_worsening": float(np.max(delta)) if delta.size else 0.0,
        "baseline_light_rmse": rmse(base[light]),
        "candidate_light_rmse": rmse(cand[light]),
        "baseline_floor10_relative_mae": mean(base / floor),
        "candidate_floor10_relative_mae": mean(cand / floor),
        "candidate_delta_abs_mean": mean(
            np.sqrt(
                pd.to_numeric(group["delta_u"], errors="coerce").fillna(0.0).to_numpy(dtype=np.float64) ** 2
                + pd.to_numeric(group["delta_v"], errors="coerce").fillna(0.0).to_numpy(dtype=np.float64) ** 2
            )
            * pd.to_numeric(group["residual_gate"], errors="coerce").fillna(0.0).to_numpy(dtype=np.float64)
        ),
    }


def _audit(df: pd.DataFrame, min_points: int) -> pd.DataFrame:
    buckets = _build_buckets(df)
    rows: list[dict[str, Any]] = []
    for bucket_name, bucket_series in buckets.items():
        work = df.copy()
        work["bucket_value"] = bucket_series.astype(str)
        for split, split_df in work.groupby("split"):
            for bucket_value, group in split_df.groupby("bucket_value"):
                if len(group) < int(min_points):
                    continue
                row = _metrics(group)
                row.update({"split": str(split), "bucket_name": bucket_name, "bucket_value": str(bucket_value)})
                rows.append(row)
        for bucket_value, group in work.groupby("bucket_value"):
            if len(group) < int(min_points):
                continue
            row = _metrics(group)
            row.update({"split": "all", "bucket_name": bucket_name, "bucket_value": str(bucket_value)})
            rows.append(row)
    return pd.DataFrame(rows)


def _write_top_md(path: Path, audit: pd.DataFrame, predictions: pd.DataFrame, focus_split: str, top_n: int) -> None:
    focus = audit[audit["split"] == focus_split].copy()
    focus = focus[focus["points"] > 0].copy()
    improved = focus.sort_values(["delta_rmse", "points"], ascending=[True, False]).head(top_n)
    worsened = focus.sort_values(["delta_rmse", "points"], ascending=[False, False]).head(top_n)
    split_points = predictions[predictions["split"] == focus_split].copy()
    split_points["abs_delta_error"] = split_points["delta_vector_error"].abs()
    top_point_worse = split_points.sort_values("delta_vector_error", ascending=False).head(top_n)
    top_point_better = split_points.sort_values("delta_vector_error", ascending=True).head(top_n)

    def fmt_zyx(row: pd.Series) -> str:
        coords: list[str] = []
        for name in ("z", "y", "x"):
            value = row.get(name)
            coords.append("NA" if pd.isna(value) else str(int(value)))
        return "/".join(coords)

    lines = [
        "# Stage5 Residual PINN Regime Audit",
        "",
        f"Focus split: `{focus_split}`",
        "",
        "Negative `delta_rmse` / `delta_vector_error` means the PINN residual improved over tp26.",
        "",
        "## Top Improved Buckets",
        "",
        "| bucket | value | points | baseline RMSE | candidate RMSE | delta RMSE | improved/worsened | max improve | max worsen |",
        "| --- | --- | ---: | ---: | ---: | ---: | --- | ---: | ---: |",
    ]
    for _, row in improved.iterrows():
        lines.append(
            f"| `{row['bucket_name']}` | `{row['bucket_value']}` | {int(row['points'])} | "
            f"{row['baseline_rmse']:.6f} | {row['candidate_rmse']:.6f} | {row['delta_rmse']:+.6f} | "
            f"{int(row['improved_points'])}/{int(row['worsened_points'])} | "
            f"{row['max_improvement']:.6f} | {row['max_worsening']:.6f} |"
        )
    lines.extend(
        [
            "",
            "## Top Worsened Buckets",
            "",
            "| bucket | value | points | baseline RMSE | candidate RMSE | delta RMSE | improved/worsened | max improve | max worsen |",
            "| --- | --- | ---: | ---: | ---: | ---: | --- | ---: | ---: |",
        ]
    )
    for _, row in worsened.iterrows():
        lines.append(
            f"| `{row['bucket_name']}` | `{row['bucket_value']}` | {int(row['points'])} | "
            f"{row['baseline_rmse']:.6f} | {row['candidate_rmse']:.6f} | {row['delta_rmse']:+.6f} | "
            f"{int(row['improved_points'])}/{int(row['worsened_points'])} | "
            f"{row['max_improvement']:.6f} | {row['max_worsening']:.6f} |"
        )
    lines.extend(
        [
            "",
            "## Top Improved Points",
            "",
            "| row | time | z/y/x | gt speed | baseline error | candidate error | delta error | altitude | truth speed bin |",
            "| ---: | --- | --- | ---: | ---: | ---: | ---: | --- | --- |",
        ]
    )
    for _, row in top_point_better.iterrows():
        lines.append(
            f"| {int(row['row_id'])} | `{row.get('time_str', '')}` | "
            f"`{fmt_zyx(row)}` | "
            f"{float(row['gt_speed']):.6f} | {float(row['baseline_vector_error']):.6f} | "
            f"{float(row['candidate_vector_error']):.6f} | {float(row['delta_vector_error']):+.6f} | "
            f"`{row.get('altitude_bin', '')}` | `{row.get('truth_speed_bin', '')}` |"
        )
    lines.extend(
        [
            "",
            "## Top Worsened Points",
            "",
            "| row | time | z/y/x | gt speed | baseline error | candidate error | delta error | altitude | truth speed bin |",
            "| ---: | --- | --- | ---: | ---: | ---: | ---: | --- | --- |",
        ]
    )
    for _, row in top_point_worse.iterrows():
        lines.append(
            f"| {int(row['row_id'])} | `{row.get('time_str', '')}` | "
            f"`{fmt_zyx(row)}` | "
            f"{float(row['gt_speed']):.6f} | {float(row['baseline_vector_error']):.6f} | "
            f"{float(row['candidate_vector_error']):.6f} | {float(row['delta_vector_error']):+.6f} | "
            f"`{row.get('altitude_bin', '')}` | `{row.get('truth_speed_bin', '')}` |"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit Stage5 residual PINN regime improvements and degradations.")
    parser.add_argument("--dataset-dir", type=Path, required=True)
    parser.add_argument("--candidate-point-predictions", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--focus-split", choices=["train", "val", "test", "all"], default="test")
    parser.add_argument("--min-points", type=int, default=3)
    parser.add_argument("--top-n", type=int, default=20)
    args = parser.parse_args()

    predictions = pd.read_csv(args.candidate_point_predictions)
    metadata = pd.read_csv(args.dataset_dir / "metadata.csv")
    features = _load_features(args.dataset_dir)
    df = predictions.merge(metadata, on=["row_id", "split"], how="left", suffixes=("", "_meta"))
    df = df.merge(features, on="row_id", how="left", suffixes=("", "_feat"))
    audit = _audit(df, int(args.min_points))
    args.out_dir.mkdir(parents=True, exist_ok=True)
    audit.to_csv(args.out_dir / "regime_audit.csv", index=False)
    df.to_csv(args.out_dir / "regime_point_table.csv", index=False)
    for split in ("train", "val", "test", "all"):
        _write_top_md(args.out_dir / f"regime_audit_{split}.md", audit, df, split, int(args.top_n))
    metadata_out = {
        "dataset_dir": str(args.dataset_dir),
        "candidate_point_predictions": str(args.candidate_point_predictions),
        "min_points": int(args.min_points),
        "focus_split": str(args.focus_split),
        "diagnostic_only": True,
        "truth_buckets_used_for_audit_only_not_features": True,
    }
    (args.out_dir / "regime_audit_metadata.json").write_text(json.dumps(metadata_out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(args.out_dir / f"regime_audit_{args.focus_split}.md")


if __name__ == "__main__":
    main()
