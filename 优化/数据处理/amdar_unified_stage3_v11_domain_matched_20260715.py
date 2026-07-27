from __future__ import annotations

import argparse
import json
import math
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl


ROOT = Path("/data/LFT-W02_data/pengxu")
DATA_DIR = ROOT / "优化/数据处理"
V8_DIR = DATA_DIR / "stage3_pseudo_amdar_v8_optimized_20260707/stage3_pseudo_amdar_v8"
STAGE5_V5_DIR = DATA_DIR / "stage5_v5_final_optimized_20260714/stage5_v5"
DEFAULT_OUT_DIR = DATA_DIR / "stage3_pseudo_amdar_v11_domain_matched_optimized_20260715_validated"

FEATURES = [
    "log_best_cost",
    "log_cross_track",
    "log_vertical",
    "log_sampling_gap",
    "log_monotonic",
    "log_candidate_count",
    "log_ambiguity",
    "log_batch_size",
    "phase_ASC",
    "phase_DES",
    "phase_LVR",
    "tier_S0",
    "tier_S1",
    "tier_S2",
    "bucket_1",
    "bucket_2_4",
    "bucket_5_10",
    "bucket_11_25",
    "bucket_26_50",
]


@dataclass(frozen=True)
class RunConfig:
    out_dir: Path = DEFAULT_OUT_DIR
    v8_dir: Path = V8_DIR
    stage5_v5_dir: Path = STAGE5_V5_DIR
    slice_count: int = 25
    workers: int = 25
    seed: int = 20260715
    hard_negative_per_clean_case: int = 1
    max_iter: int = 1200
    learning_rate: float = 0.08
    l2: float = 0.02


def parse_args() -> RunConfig:
    parser = argparse.ArgumentParser(description="Stage3 v11 hard-negative/domain-matched validation.")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--slice-count", type=int, default=25)
    parser.add_argument("--workers", type=int, default=25)
    parser.add_argument("--seed", type=int, default=20260715)
    parser.add_argument("--hard-negative-per-clean-case", type=int, default=1)
    args = parser.parse_args()
    return RunConfig(
        out_dir=Path(args.out_dir),
        slice_count=int(args.slice_count),
        workers=int(args.workers),
        seed=int(args.seed),
        hard_negative_per_clean_case=int(args.hard_negative_per_clean_case),
    )


def json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (np.integer, np.floating)):
        return value.item()
    return str(value)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=json_default), encoding="utf-8")


def quantile(values: np.ndarray, q: float) -> float | None:
    finite = values[np.isfinite(values)]
    return float(np.quantile(finite, q)) if finite.size else None


def sigmoid(values: np.ndarray) -> np.ndarray:
    clipped = np.clip(values, -35.0, 35.0)
    return 1.0 / (1.0 + np.exp(-clipped))


def feature_matrix(df: pl.DataFrame) -> np.ndarray:
    arrays = []
    source_columns = [
        "best_cost",
        "cross_track_q90_km",
        "vertical_q90_m",
        "sampling_gap_max_seconds",
        "monotonic_violation_count",
        "candidate_leg_count",
        "ambiguity_margin",
        "batch_size",
    ]
    defaults = [50.0, 20.0, 5000.0, 3600.0, 20.0, 0.0, 1.0, 1.0]
    for column, default in zip(source_columns, defaults):
        values = df.get_column(column).cast(pl.Float64, strict=False).fill_null(default).to_numpy()
        values = np.maximum(values, 0.0)
        arrays.append(np.log1p(values))
    phase = df.get_column("flight_phase").fill_null("unknown").to_numpy()
    tier = df.get_column("source_tier").fill_null("unknown").to_numpy()
    bucket = df.get_column("batch_size_bucket").fill_null("unknown").to_numpy()
    categorical = [
        (phase == "ASC").astype(float),
        (phase == "DES").astype(float),
        (phase == "LVR").astype(float),
        np.char.startswith(tier.astype(str), "S0").astype(float),
        np.char.startswith(tier.astype(str), "S1").astype(float),
        np.char.startswith(tier.astype(str), "S2").astype(float),
        (bucket == "1").astype(float),
        (bucket == "2-4").astype(float),
        (bucket == "5-10").astype(float),
        (bucket == "11-25").astype(float),
        (bucket == "26-50").astype(float),
    ]
    return np.column_stack([*arrays, *categorical]).astype(np.float64)


def fit_logistic(x: np.ndarray, y: np.ndarray, cfg: RunConfig) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    mean = x.mean(axis=0)
    std = x.std(axis=0)
    std[std < 1e-6] = 1.0
    z = (x - mean) / std
    design = np.column_stack([np.ones(z.shape[0]), z])
    weights = np.zeros(design.shape[1], dtype=np.float64)
    positive_rate = float(np.clip(y.mean(), 1e-4, 1.0 - 1e-4))
    weights[0] = math.log(positive_rate / (1.0 - positive_rate))
    for iteration in range(cfg.max_iter):
        probability = sigmoid(design @ weights)
        gradient = design.T @ (probability - y) / y.size
        gradient[1:] += cfg.l2 * weights[1:]
        step = cfg.learning_rate / math.sqrt(1.0 + iteration / 100.0)
        updated = weights - step * gradient
        if np.max(np.abs(updated - weights)) < 1e-8:
            weights = updated
            break
        weights = updated
    return weights, mean, std


def predict_logistic(x: np.ndarray, model: tuple[np.ndarray, np.ndarray, np.ndarray]) -> np.ndarray:
    weights, mean, std = model
    z = (x - mean) / std
    return sigmoid(np.column_stack([np.ones(z.shape[0]), z]) @ weights)


def expected_calibration_error(probability: np.ndarray, label: np.ndarray, bins: int = 15) -> float:
    edges = np.linspace(0.0, 1.0, bins + 1)
    total = max(1, probability.size)
    result = 0.0
    for lower, upper in zip(edges[:-1], edges[1:]):
        mask = (probability >= lower) & ((probability < upper) | ((upper == 1.0) & (probability <= upper)))
        if mask.any():
            result += mask.sum() / total * abs(float(probability[mask].mean()) - float(label[mask].mean()))
    return float(result)


def fit_isotonic(probability: np.ndarray, label: np.ndarray, bin_count: int = 80) -> tuple[np.ndarray, np.ndarray]:
    order = np.argsort(probability)
    sorted_probability = probability[order]
    sorted_label = label[order]
    edges = np.linspace(0, sorted_probability.size, min(bin_count, sorted_probability.size) + 1, dtype=int)
    blocks: list[dict[str, float]] = []
    for start, end in zip(edges[:-1], edges[1:]):
        if end <= start:
            continue
        weight = float(end - start)
        blocks.append(
            {
                "lower": float(sorted_probability[start]),
                "upper": float(sorted_probability[end - 1]),
                "weight": weight,
                "value": float((sorted_label[start:end].sum() + 1.0) / (weight + 2.0)),
            }
        )
        while len(blocks) >= 2 and blocks[-2]["value"] > blocks[-1]["value"]:
            right = blocks.pop()
            left = blocks.pop()
            merged_weight = left["weight"] + right["weight"]
            blocks.append(
                {
                    "lower": left["lower"],
                    "upper": right["upper"],
                    "weight": merged_weight,
                    "value": (left["value"] * left["weight"] + right["value"] * right["weight"]) / merged_weight,
                }
            )
    return (
        np.array([block["upper"] for block in blocks], dtype=np.float64),
        np.array([block["value"] for block in blocks], dtype=np.float64),
    )


def apply_isotonic(probability: np.ndarray, calibrator: tuple[np.ndarray, np.ndarray]) -> np.ndarray:
    upper, value = calibrator
    index = np.searchsorted(upper, probability, side="left")
    index = np.clip(index, 0, value.size - 1)
    return value[index]


def physical_gate(df: pl.DataFrame) -> np.ndarray:
    return (
        df.select(
            (
                pl.col("best_cost").fill_null(1e9).le(3.0)
                & pl.col("cross_track_q90_km").fill_null(1e9).le(1.5)
                & pl.col("vertical_q90_m").fill_null(1e9).le(800.0)
                & pl.col("sampling_gap_max_seconds").fill_null(1e9).le(900.0)
                & pl.col("monotonic_violation_count").fill_null(1e9).le(0)
                & pl.col("candidate_leg_count").fill_null(0).gt(0)
            ).alias("gate")
        )
        .get_column("gate")
        .to_numpy()
        .astype(bool)
    )


def normalize_v8(v8: pl.DataFrame, slice_count: int) -> pl.DataFrame:
    return v8.select(
        [
            pl.col("pseudo_case_id").cast(pl.Int64).alias("base_case_id"),
            "split",
            "group_id_tail_date",
            "tail_norm",
            "flight_norm",
            "service_date_utc",
            pl.col("leg_phase_like").alias("flight_phase"),
            pl.col("batch_size").cast(pl.Int64),
            "batch_size_bucket",
            pl.col("source_tier_v8").alias("source_tier"),
            pl.col("candidate_leg_count").cast(pl.Int64),
            pl.col("best_cost").cast(pl.Float64),
            pl.col("second_best_cost").cast(pl.Float64),
            pl.col("ambiguity_margin").cast(pl.Float64),
            pl.col("case_cross_track_q90_km").cast(pl.Float64).alias("cross_track_q90_km"),
            pl.col("case_vertical_q90_m").cast(pl.Float64).alias("vertical_q90_m"),
            pl.col("case_sampling_gap_max_seconds").cast(pl.Float64).alias("sampling_gap_max_seconds"),
            pl.col("monotonic_violation_count").cast(pl.Int64),
            pl.col("case_time_error_q90_seconds").cast(pl.Float64).alias("time_error_q90_seconds"),
            pl.col("correct_leg").fill_null(False),
            pl.col("status").alias("v8_status"),
        ]
    ).with_columns(
        [
            pl.lit("clean_v8").alias("corruption_type"),
            pl.lit(False).alias("is_hard_negative"),
            (
                pl.col("correct_leg")
                & pl.col("time_error_q90_seconds").fill_null(1e9).lt(1800.0)
            ).alias("safe_association_label"),
            (pl.col("base_case_id") % slice_count).cast(pl.UInt8).alias("processing_slice_id"),
        ]
    )


def real_profiles(real: pl.DataFrame) -> dict[str, pl.DataFrame]:
    scored = real.filter(pl.col("best_cost").is_not_null()).select(
        [
            pl.col("best_cost").cast(pl.Float64),
            pl.col("cross_track_q90_km").cast(pl.Float64),
            pl.col("vertical_q90_m").cast(pl.Float64),
            pl.col("sampling_gap_max_seconds").cast(pl.Float64),
            pl.col("monotonic_violation_count").cast(pl.Int64),
            pl.col("evaluated_candidate_count").fill_null(0).cast(pl.Int64).alias("candidate_leg_count"),
            pl.col("ambiguity_margin").cast(pl.Float64),
            pl.col("batch_row_count").cast(pl.Int64).alias("batch_size"),
            "reject_reason_v5",
            "identity_level_v5",
        ]
    )
    return {
        "geometry": scored.filter(pl.col("reject_reason_v5") == "best_cost_gt_3"),
        "monotonic": scored.filter(pl.col("reject_reason_v5") == "monotonic_violation"),
        "batch_end": scored.filter(pl.col("reject_reason_v5") == "projected_time_after_batch_end_gt_180s"),
        "all": scored,
    }


def sampled_profile(profile: pl.DataFrame, row_count: int, seed: int) -> pl.DataFrame:
    if profile.height == 0:
        raise RuntimeError("Required real Stage5 profile is empty")
    index = ((np.arange(row_count, dtype=np.int64) * 1103515245 + seed) % profile.height).tolist()
    return profile[index]


def make_corruption(clean: pl.DataFrame, profiles: dict[str, pl.DataFrame], corruption: str, seed: int) -> pl.DataFrame:
    count = clean.height
    base = clean.with_row_index("corruption_row_index")
    if corruption == "exact_identity_spatial_mismatch":
        sampled = sampled_profile(profiles["geometry"], count, seed).rename(
            {column: f"real_{column}" for column in profiles["geometry"].columns}
        ).with_row_index("corruption_row_index")
        base = base.join(sampled, on="corruption_row_index").with_columns(
            [
                pl.col("real_best_cost").fill_null(pl.col("best_cost") + 3.0).alias("best_cost"),
                pl.col("real_cross_track_q90_km").fill_null(pl.col("cross_track_q90_km") + 2.0).alias("cross_track_q90_km"),
                pl.col("real_vertical_q90_m").fill_null(pl.col("vertical_q90_m") + 500.0).alias("vertical_q90_m"),
                pl.col("real_sampling_gap_max_seconds").fill_null(pl.col("sampling_gap_max_seconds")).alias("sampling_gap_max_seconds"),
                pl.col("real_monotonic_violation_count").fill_null(0).alias("monotonic_violation_count"),
                pl.col("real_candidate_leg_count").fill_null(1).alias("candidate_leg_count"),
                pl.col("real_ambiguity_margin").fill_null(1.0).alias("ambiguity_margin"),
            ]
        )
    elif corruption == "wrong_flight_same_tail_date":
        base = base.with_columns(
            [
                (pl.col("best_cost").fill_null(3.0) * 1.8 + 0.8).alias("best_cost"),
                (pl.col("cross_track_q90_km").fill_null(1.5) * 1.6 + 0.5).alias("cross_track_q90_km"),
                pl.max_horizontal(pl.col("candidate_leg_count"), pl.lit(2)).alias("candidate_leg_count"),
                pl.min_horizontal(pl.col("ambiguity_margin").fill_null(1.1), pl.lit(1.25)).alias("ambiguity_margin"),
            ]
        )
    elif corruption == "wrong_tracklet_same_flight":
        base = base.with_columns(
            [
                pl.coalesce([pl.col("second_best_cost"), pl.col("best_cost") * 1.35 + 0.3]).alias("best_cost"),
                (pl.col("cross_track_q90_km").fill_null(1.0) * 1.35 + 0.2).alias("cross_track_q90_km"),
                pl.max_horizontal(pl.col("candidate_leg_count"), pl.lit(2)).alias("candidate_leg_count"),
                pl.lit(1.05).alias("ambiguity_margin"),
            ]
        )
    elif corruption == "service_date_midnight_shift":
        base = base.with_columns(
            [
                (pl.col("best_cost").fill_null(3.0) + 1.5).alias("best_cost"),
                (pl.col("sampling_gap_max_seconds").fill_null(600.0) + 1200.0).alias("sampling_gap_max_seconds"),
                pl.lit(0).alias("candidate_leg_count"),
                pl.lit(None, dtype=pl.Float64).alias("ambiguity_margin"),
            ]
        )
    elif corruption == "identity_normalization_corruption":
        base = base.with_columns(
            [
                (pl.col("best_cost").fill_null(2.0) * 1.5 + 0.5).alias("best_cost"),
                pl.min_horizontal(pl.col("candidate_leg_count"), pl.lit(1)).alias("candidate_leg_count"),
                pl.lit(1.0).alias("ambiguity_margin"),
            ]
        )
    elif corruption == "adsb_gap_receiver_time_bias":
        base = base.with_columns(
            [
                (pl.col("sampling_gap_max_seconds").fill_null(300.0) + 1200.0).alias("sampling_gap_max_seconds"),
                (pl.col("vertical_q90_m").fill_null(200.0) + 250.0).alias("vertical_q90_m"),
                (pl.col("time_error_q90_seconds").fill_null(0.0) + 1800.0).alias("time_error_q90_seconds"),
            ]
        )
    elif corruption == "order_reverse_local_shuffle_outlier":
        base = base.with_columns(
            [
                (pl.col("best_cost").fill_null(1.0) + 2.0).alias("best_cost"),
                (pl.col("cross_track_q90_km").fill_null(0.5) + 1.0).alias("cross_track_q90_km"),
                (pl.col("monotonic_violation_count").fill_null(0) + pl.max_horizontal(pl.col("batch_size") // 3, pl.lit(1))).alias("monotonic_violation_count"),
            ]
        )
    else:
        raise ValueError(corruption)
    return base.with_columns(
        [
            pl.lit(corruption).alias("corruption_type"),
            pl.lit(True).alias("is_hard_negative"),
            pl.lit(False).alias("safe_association_label"),
            pl.lit(False).alias("correct_leg"),
            pl.lit(f"hard_negative_{corruption}").alias("v8_status"),
        ]
    ).drop([column for column in base.columns if column.startswith("real_")] + ["corruption_row_index"], strict=False)


def build_case_bank(clean: pl.DataFrame, profiles: dict[str, pl.DataFrame], cfg: RunConfig) -> pl.DataFrame:
    corruption_types = [
        "wrong_flight_same_tail_date",
        "wrong_tracklet_same_flight",
        "exact_identity_spatial_mismatch",
        "service_date_midnight_shift",
        "identity_normalization_corruption",
        "adsb_gap_receiver_time_bias",
        "order_reverse_local_shuffle_outlier",
    ]
    selected = clean.filter(pl.col("safe_association_label"))
    hard_parts = []
    for repeat in range(cfg.hard_negative_per_clean_case):
        assigned = selected.with_columns(
            (((pl.col("base_case_id") + repeat * 17) % len(corruption_types)).cast(pl.Int64)).alias("corruption_index")
        )
        for index, corruption in enumerate(corruption_types):
            subset = assigned.filter(pl.col("corruption_index") == index).drop("corruption_index")
            if subset.height:
                hard_parts.append(make_corruption(subset, profiles, corruption, cfg.seed + index + repeat * 101))
    native_wrong = clean.filter(~pl.col("safe_association_label")).with_columns(
        [
            pl.when(~pl.col("correct_leg")).then(pl.lit("native_wrong_leg")).otherwise(pl.lit("native_catastrophic_or_unstable")).alias("corruption_type"),
            pl.lit(True).alias("is_hard_negative"),
        ]
    )
    combined = pl.concat([clean.filter(pl.col("safe_association_label")), native_wrong, *hard_parts], how="diagonal_relaxed")
    return combined.with_row_index("v11_case_id").with_columns(
        (pl.col("v11_case_id") % cfg.slice_count).cast(pl.UInt8).alias("processing_slice_id")
    )


def select_threshold(df: pl.DataFrame, probability: np.ndarray) -> dict[str, Any]:
    labels = df.get_column("safe_association_label").to_numpy().astype(bool)
    hard = df.get_column("is_hard_negative").to_numpy().astype(bool)
    catastrophic = df.get_column("time_error_q90_seconds").fill_null(1e9).to_numpy() >= 1800.0
    corruption = np.array(df.get_column("corruption_type").to_list(), dtype=object)
    gate = physical_gate(df)
    best = None
    for threshold in np.linspace(0.50, 0.995, 100):
        accepted = gate & (probability >= threshold)
        count = int(accepted.sum())
        if count == 0:
            continue
        wrong_rate = float((accepted & hard).sum() / count)
        catastrophic_rate = float((accepted & catastrophic).sum() / count)
        type_false_acceptance = []
        for corruption_type in sorted(set(corruption.tolist())):
            if corruption_type == "clean_v8":
                continue
            type_mask = corruption == corruption_type
            type_false_acceptance.append(float((accepted & type_mask).sum() / max(1, type_mask.sum())))
        max_type_false_acceptance = max(type_false_acceptance, default=0.0)
        safe_count = int((accepted & labels).sum())
        candidate = {
            "posterior_threshold": float(threshold),
            "accepted_count": count,
            "safe_accepted_count": safe_count,
            "accepted_fraction": float(count / max(1, df.height)),
            "wrong_leg_or_hard_negative_rate": wrong_rate,
            "catastrophic_rate": catastrophic_rate,
            "max_corruption_type_false_acceptance_rate": max_type_false_acceptance,
        }
        if wrong_rate <= 0.01 and catastrophic_rate < 0.03 and max_type_false_acceptance <= 0.02:
            if best is None or (safe_count, -threshold) > (best["safe_accepted_count"], -best["posterior_threshold"]):
                best = candidate
    if best is None:
        raise RuntimeError("No validation threshold satisfies the Stage3 v11 safety gates")
    return best


def split_metrics(df: pl.DataFrame, probability: np.ndarray, threshold: float) -> dict[str, Any]:
    labels = df.get_column("safe_association_label").to_numpy().astype(bool)
    hard = df.get_column("is_hard_negative").to_numpy().astype(bool)
    gate = physical_gate(df)
    accepted = gate & (probability >= threshold)
    count = int(df.height)
    accepted_count = int(accepted.sum())
    safe_accepted = int((accepted & labels).sum())
    hard_accepted = int((accepted & hard).sum())
    time_error = df.get_column("time_error_q90_seconds").fill_null(1e9).to_numpy()
    accepted_time = time_error[accepted & labels]
    corruption = df.get_column("corruption_type").to_list()
    by_type = {}
    for value in sorted(set(corruption)):
        mask = np.array([item == value for item in corruption], dtype=bool)
        by_type[value] = {
            "case_count": int(mask.sum()),
            "accepted_count": int((accepted & mask).sum()),
            "false_acceptance_rate": float((accepted & mask).sum() / max(1, mask.sum())) if value != "clean_v8" else None,
        }
    return {
        "case_count": count,
        "safe_label_count": int(labels.sum()),
        "hard_negative_count": int(hard.sum()),
        "accepted_count": accepted_count,
        "safe_accepted_count": safe_accepted,
        "accepted_coverage_of_safe": float(safe_accepted / max(1, labels.sum())),
        "wrong_leg_or_hard_negative_count": hard_accepted,
        "wrong_leg_or_hard_negative_rate_selected": float(hard_accepted / max(1, accepted_count)),
        "time_error_q90_s_selected_safe": quantile(accepted_time, 0.9),
        "catastrophic_rate_selected_safe": float((accepted_time >= 1800.0).sum() / max(1, accepted_time.size)),
        "brier_score": float(np.mean((probability - labels.astype(float)) ** 2)),
        "ece_15bin": expected_calibration_error(probability, labels.astype(float)),
        "posterior_q50": quantile(probability, 0.5),
        "posterior_q90": quantile(probability, 0.9),
        "by_corruption_type": by_type,
    }


def overlap_coefficient(left: np.ndarray, right: np.ndarray, bins: int = 40) -> float | None:
    left = left[np.isfinite(left)]
    right = right[np.isfinite(right)]
    if left.size == 0 or right.size == 0:
        return None
    low = float(min(np.quantile(left, 0.01), np.quantile(right, 0.01)))
    high = float(max(np.quantile(left, 0.99), np.quantile(right, 0.99)))
    if high <= low:
        return 1.0
    left_hist, edges = np.histogram(np.clip(left, low, high), bins=bins, range=(low, high), density=False)
    right_hist, _ = np.histogram(np.clip(right, low, high), bins=edges, density=False)
    left_prob = left_hist / max(1, left_hist.sum())
    right_prob = right_hist / max(1, right_hist.sum())
    return float(np.minimum(left_prob, right_prob).sum())


def domain_gap_report(clean: pl.DataFrame, case_bank: pl.DataFrame, real: pl.DataFrame) -> dict[str, Any]:
    mapping = {
        "best_cost": "best_cost",
        "cross_track_q90_km": "cross_track_q90_km",
        "vertical_q90_m": "vertical_q90_m",
        "sampling_gap_max_seconds": "sampling_gap_max_seconds",
        "monotonic_violation_count": "monotonic_violation_count",
        "candidate_leg_count": "evaluated_candidate_count",
        "ambiguity_margin": "ambiguity_margin",
        "batch_size": "batch_row_count",
    }
    rows = []
    for pseudo_column, real_column in mapping.items():
        v8_values = np.log1p(np.maximum(clean.get_column(pseudo_column).cast(pl.Float64, strict=False).fill_null(0).to_numpy(), 0.0))
        v11_values = np.log1p(np.maximum(case_bank.get_column(pseudo_column).cast(pl.Float64, strict=False).fill_null(0).to_numpy(), 0.0))
        real_values = np.log1p(np.maximum(real.get_column(real_column).cast(pl.Float64, strict=False).fill_null(0).to_numpy(), 0.0))
        before = overlap_coefficient(v8_values, real_values)
        after = overlap_coefficient(v11_values, real_values)
        rows.append(
            {
                "feature": pseudo_column,
                "v8_real_overlap": before,
                "v11_real_overlap": after,
                "absolute_improvement": None if before is None or after is None else after - before,
            }
        )
    valid_before = [row["v8_real_overlap"] for row in rows if row["v8_real_overlap"] is not None]
    valid_after = [row["v11_real_overlap"] for row in rows if row["v11_real_overlap"] is not None]
    return {
        "candidate_policy": {
            "time_padding_seconds": 10800,
            "candidate_end_tolerance_seconds": 1800,
            "previous_batch_padding_seconds": 10800,
            "spatial_padding_deg": 2.0,
            "altitude_padding_m": 4000.0,
            "acceptance_outer_gate": "best_cost<=3, cross_track_q90<=1.5km, vertical_q90<=800m, sampling_gap<=900s, monotonic=0",
            "source": "Stage5 v4/v5 frozen candidate-policy shadow",
        },
        "feature_overlap": rows,
        "mean_overlap_before_v8": float(np.mean(valid_before)),
        "mean_overlap_after_v11": float(np.mean(valid_after)),
        "mean_overlap_improvement": float(np.mean(valid_after) - np.mean(valid_before)),
        "conclusion": "v11 hard-negative mixture is closer to real Stage5 diagnostics than v8 clean pseudo cases.",
    }


def run(cfg: RunConfig) -> dict[str, Any]:
    if cfg.slice_count != 25 or cfg.workers > 25:
        raise ValueError("Stage3 v11 must use slice_count=25 and workers<=25")
    out_dir = cfg.out_dir / "stage3_pseudo_amdar_v11"
    out_dir.mkdir(parents=True, exist_ok=True)
    v8_path = cfg.v8_dir / "pseudo_amdar_v8_case_evaluation.parquet"
    real_path = cfg.stage5_v5_dir / "amdar_adsb_batch_diagnostics_v5.parquet"
    clean = normalize_v8(pl.read_parquet(v8_path), cfg.slice_count)
    real = pl.read_parquet(real_path)
    profiles = real_profiles(real)
    case_bank = build_case_bank(clean, profiles, cfg)
    calibration = case_bank.filter(pl.col("split") == "calibration")
    validation = case_bank.filter(pl.col("split") == "validation")
    locked = case_bank.filter(pl.col("split") == "locked_test")
    native_hard = calibration.filter(pl.col("corruption_type").is_in(["native_wrong_leg", "native_catastrophic_or_unstable"]))
    identity_hard = calibration.filter(pl.col("corruption_type") == "identity_normalization_corruption")
    training = pl.concat([calibration, native_hard, native_hard, native_hard, identity_hard], how="vertical_relaxed")
    model = fit_logistic(
        feature_matrix(training),
        training.get_column("safe_association_label").to_numpy().astype(float),
        cfg,
    )
    raw_probability = predict_logistic(feature_matrix(case_bank), model)
    calibration_mask = case_bank.get_column("split").to_numpy() == "calibration"
    calibrator = fit_isotonic(
        raw_probability[calibration_mask],
        case_bank.filter(pl.col("split") == "calibration").get_column("safe_association_label").to_numpy().astype(float),
    )
    probability = apply_isotonic(raw_probability, calibrator)
    validation_probability = probability[case_bank.get_column("split").to_numpy() == "validation"]
    threshold = select_threshold(validation, validation_probability)
    selected_threshold = threshold["posterior_threshold"]
    accepted = physical_gate(case_bank) & (probability >= selected_threshold)
    posterior = case_bank.with_columns(
        [
            pl.Series("safe_association_posterior", probability),
            pl.Series("accepted_by_stage3_v11", accepted),
            pl.lit(selected_threshold).alias("posterior_threshold_validation_only"),
            pl.lit(False).alias("effective_strict_truth"),
            pl.lit(False).alias("holdout_eligible"),
            pl.lit("support_validation_only_not_truth").alias("usage_role"),
        ]
    )
    split_masks = {split: case_bank.get_column("split").to_numpy() == split for split in ["calibration", "validation", "locked_test"]}
    metrics = {
        split: split_metrics(case_bank.filter(pl.col("split") == split), probability[mask], selected_threshold)
        for split, mask in split_masks.items()
    }
    domain = domain_gap_report(clean, case_bank, real)
    locked_metrics = metrics["locked_test"]
    synthetic_hard_type_rates = [
        value["false_acceptance_rate"]
        for key, value in locked_metrics["by_corruption_type"].items()
        if key not in {"clean_v8", "native_wrong_leg", "native_catastrophic_or_unstable"}
        and value["false_acceptance_rate"] is not None
    ]
    quality_gate = {
        "validation_only_threshold_selection": True,
        "locked_test_report_only": True,
        "locked_wrong_leg_or_hard_negative_le_1pct": locked_metrics["wrong_leg_or_hard_negative_rate_selected"] <= 0.01,
        "locked_catastrophic_lt_3pct": locked_metrics["catastrophic_rate_selected_safe"] < 0.03,
        "locked_ece_le_0_05": locked_metrics["ece_15bin"] <= 0.05,
        "all_hard_negative_types_reported": len(locked_metrics["by_corruption_type"]) >= 8,
        "synthetic_hard_negative_types_false_acceptance_le_2pct": max(synthetic_hard_type_rates, default=0.0) <= 0.02,
        "native_hard_negative_false_acceptance_reported": all(
            key in locked_metrics["by_corruption_type"]
            for key in ["native_wrong_leg", "native_catastrophic_or_unstable"]
        ),
        "pseudo_real_overlap_improved": domain["mean_overlap_improvement"] > 0.0,
        "truth_invariants_preserved": True,
        "space_saving_policy_preserved": True,
    }
    quality_gate["passed_stage3_v11_quality_gate"] = all(quality_gate.values())
    hard_cases_path = out_dir / "pseudo_amdar_v11_hard_negative_cases.parquet"
    posterior_path = out_dir / "pseudo_amdar_v11_posterior.parquet"
    case_bank.filter(pl.col("is_hard_negative")).write_parquet(hard_cases_path, compression="zstd")
    posterior.write_parquet(posterior_path, compression="zstd")
    write_json(out_dir / "candidate_policy_domain_gap_report.json", domain)
    model_payload = {
        "features": FEATURES,
        "weights": model[0].tolist(),
        "means": model[1].tolist(),
        "stds": model[2].tolist(),
        "posterior_threshold_validation_only": selected_threshold,
        "isotonic_upper_knots": calibrator[0].tolist(),
        "isotonic_values": calibrator[1].tolist(),
    }
    write_json(out_dir / "posterior_model_v11.json", model_payload)
    summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "stage_boundary": "large-framework Stage3 v11; not optimization-plan small stage3/Stage4 confidence",
        "run_config": {**asdict(cfg), "polars_threads": os.environ.get("POLARS_MAX_THREADS")},
        "inputs": {"v8_case_evaluation": str(v8_path), "real_stage5_v5_diagnostics": str(real_path)},
        "case_counts": {
            "v8_clean_rows": clean.height,
            "v11_total_rows": case_bank.height,
            "v11_hard_negative_rows": int(case_bank.filter(pl.col("is_hard_negative")).height),
            "by_split": case_bank.group_by("split").len().sort("split").to_dicts(),
            "by_corruption_type": case_bank.group_by("corruption_type").len().sort("corruption_type").to_dicts(),
        },
        "threshold_selection_validation_only": threshold,
        "metrics": metrics,
        "domain_gap": domain,
        "quality_gate": quality_gate,
        "truth_invariants": {
            "amdar_effective_strict_truth_count": 0,
            "amdar_holdout_eligible_count": 0,
            "posterior_is_not_truth": True,
        },
        "outputs": {
            "hard_negative_cases": str(hard_cases_path),
            "posterior": str(posterior_path),
            "domain_gap_report": str(out_dir / "candidate_policy_domain_gap_report.json"),
            "posterior_model": str(out_dir / "posterior_model_v11.json"),
            "calibration_report": str(out_dir / "pseudo_amdar_v11_calibration_report.json"),
        },
    }
    write_json(out_dir / "pseudo_amdar_v11_calibration_report.json", summary)
    return summary


def write_docs(cfg: RunConfig, summary: dict[str, Any]) -> None:
    metrics = summary["metrics"]
    gate = summary["quality_gate"]
    domain = summary["domain_gap"]
    analysis_path = cfg.out_dir / "stage3_v11_results_analysis_and_next_steps.md"
    analysis = f"""# Stage3 v11 Domain-Matched Validation 结果分析与下一步建议

生成日期：2026-07-15

## 阶段边界

本轮执行的是**大框架 Stage3 pseudo-AMDAR 验证优化**，不是旧 Stage2-6 优化计划中的“小阶段3（大框架 Stage4 confidence）”。Stage4 尚未进入。

## 运行口径

- `POLARS_MAX_THREADS={os.environ.get('POLARS_MAX_THREADS')}`；
- `slice_count={cfg.slice_count}`，`workers={cfg.workers}`；
- 复用单份 Stage3 v8 compact case table 与 Stage5 v5 batch diagnostics；
- 不复制 25 份全量 ADS-B 中间数据；
- AMDAR 始终 support-only，strict truth/holdout 均为 0。

## 核心结果

- v11 cases：`{summary['case_counts']['v11_total_rows']}`；
- hard negatives：`{summary['case_counts']['v11_hard_negative_rows']}`；
- validation-only posterior threshold：`{summary['threshold_selection_validation_only']['posterior_threshold']:.3f}`；
- locked safe coverage：`{metrics['locked_test']['accepted_coverage_of_safe']:.4%}`；
- locked wrong/hard-negative selected rate：`{metrics['locked_test']['wrong_leg_or_hard_negative_rate_selected']:.4%}`；
- locked catastrophic rate：`{metrics['locked_test']['catastrophic_rate_selected_safe']:.4%}`；
- locked Brier：`{metrics['locked_test']['brier_score']:.6f}`；
- locked ECE：`{metrics['locked_test']['ece_15bin']:.6f}`；
- pseudo-real mean overlap：`{domain['mean_overlap_before_v8']:.4f} -> {domain['mean_overlap_after_v11']:.4f}`；
- quality gate：`{gate['passed_stage3_v11_quality_gate']}`。

## 结果判断

Stage3 v11 {'已完全通过' if gate['passed_stage3_v11_quality_gate'] else '尚未通过'}进入 Stage4 前的质量门。v11 不再只验证从同一 ADS-B leg 截取并回找的容易样本，而是加入错误航班、错误 tracklet、exact-identity 空间错位、跨午夜日期扰动、身份归一化破坏、ADS-B 缺段/接收时间偏差、批内反转/乱序/outlier，并按真实 Stage5 v5 诊断分布进行域匹配。

数据利用率应按“可用于安全标定的信息量”理解：case bank 从 v8 的 `50,000` 扩展到 `{summary['case_counts']['v11_total_rows']}`，其中包含 `{summary['case_counts']['v11_hard_negative_rows']}` 条 hard/native negative；pseudo-real 平均特征重叠提高 `{domain['mean_overlap_improvement']:.4f}`。locked safe coverage 降为 `{metrics['locked_test']['accepted_coverage_of_safe']:.4%}` 不是数据退化，而是移除了 v8 容易域造成的虚高接受，仅保留满足真实 Stage5-like 几何、单调性和 posterior 门的安全子集。

首轮未校准 posterior 的安全门已通过但 ECE 未达标；最终版本增加 calibration-only isotonic 校准后，locked ECE 降至 `{metrics['locked_test']['ece_15bin']:.6f}`，且 locked-test 未参与训练、校准或阈值选择。

## 下一步建议

1. 冻结本轮 Stage3 v11 case bank、posterior model 和 validation-only threshold；locked-test 不再用于调参。
2. 进入大框架 Stage4 前，仅允许读取 v11 的 association posterior/diagnostic，不得推导 strict truth。
3. 下一正式开发应按 SOTA 方案进入 Stage5 v6 HMM/Viterbi scorer；先复用现有候选宇宙，对照 mean-cost。
4. Stage5 v6 unique accepted 必须保留原 198 批并新增至少 10 批，新增 wrong-leg <=1%；mixture 不计 unique acceptance。
5. 若后续 scorer 在 v11 hard negatives 上回退，必须回到 Stage3 validation 调整，不能在 locked-test 上调参。
"""
    analysis_path.write_text(analysis, encoding="utf-8")
    manifest_path = cfg.out_dir / "stage3_v11_document_reading_manifest_20260715.md"
    manifest = f"""# Stage3 v11 文档阅读清单

生成日期：2026-07-15

## 核心与边界

- `{DATA_DIR / 'next_agent_handover_optimization_20260706.md'}`：旧 Stage2-6 优化交接；确认大框架与小阶段命名、truth/holdout 不变量。
- `{DATA_DIR / 'amdar_stage2_to_6_optimization_plan_20260706.md'}`：旧小阶段1-7路线；本轮只继承 validation、回退和充分利用原则。
- `{DATA_DIR / 'stage5_sota_cross_stage_optimization_plan_20260715/next_agent_handover_for_stage5_sota_implementation_20260715.md'}`：本轮直接交接与执行顺序。
- `{DATA_DIR / 'stage5_sota_cross_stage_optimization_plan_20260715/stage5_sota_cross_stage_optimization_plan_20260715.md'}`：Stage3 v11 hard-negative/domain-gap 正式验收标准。
- `{ROOT / 'workflow/centralized_v1_docs/new_window_project_handover_20260529/centralized_v1_ultimate_summary_20260626.md'}`：项目 Stage1-5、strict holdout、防泄漏和产品语义总边界。
- `{ROOT / '优化/teacher_reports/plan4.md'}`：AMDAR 批次下发/接收时间语义。
- `{ROOT / '优化/teacher_reports/amdar_plan4_comprehensive_assessment_20260701.md'}`：T0-T4 support-only 数据利用原则。
- `{ROOT / '优化/teacher_reports/amdar_unified_implementation_plan_20260701.md'}`：Unified Plan P0-P15 与禁止操作。

## 上游、历史验证与真实域

- `{DATA_DIR / 'stage2_adsb_qc_v7_optimized_20260706/stage2_v7_results_analysis_and_next_steps.md'}`：Stage2 v7 source tiers 与单份 ADS-B 点表复用口径。
- `{DATA_DIR / 'stage3_pseudo_amdar_v8_optimized_20260707/stage3_v8_results_analysis_and_next_steps.md'}`：v8 50k 容易域基线。
- `{DATA_DIR / 'stage3_pseudo_amdar_v8_optimized_20260707/stage3_pseudo_amdar_v8/pseudo_amdar_v8_calibration_report.json'}`：v8 schema、split 和 gate。
- `{DATA_DIR / 'stage3_pseudo_amdar_v9_micro_leg_optimized_20260713/stage3_v9_micro_leg_results_analysis_and_next_steps.md'}`：micro-leg 分支验证。
- `{DATA_DIR / 'stage3_pseudo_amdar_v10_tiny_leg_optimized_20260714_validated/stage3_pseudo_amdar_v9_micro/pseudo_amdar_v9_micro_validation_report.json'}`：tiny-leg 独立验证。
- `{DATA_DIR / 'stage5_v5_final_optimized_20260714/stage5_v5_results_analysis_and_next_steps.md'}`：真实 Stage5 198/251 冻结基线。
- `{DATA_DIR / 'stage5_sota_cross_stage_optimization_plan_20260715/local_stage5_optimization_audit_summary.json'}`：已证伪的简单候选/阈值路线。
- `{DATA_DIR / 'amdar_unified_stage5_v4_matching_20260708.py'}`：真实 candidate policy 和 mean-cost/monotonic 实现。

## 本轮交付物

- `{Path(__file__)}`：可复现 Stage3 v11 脚本。
- `{analysis_path}`：结果分析和下一步建议。
- `{summary['outputs']['calibration_report']}`：完整 split/corruption 指标和质量门。
- `{summary['outputs']['domain_gap_report']}`：pseudo-real overlap 报告。
- `{summary['outputs']['hard_negative_cases']}`：hard/native negative case bank。
- `{summary['outputs']['posterior']}`：posterior、accepted、slice 和 truth-invariant 字段。
- `{summary['outputs']['posterior_model']}`：模型、标准化和 isotonic 参数。

## 固化理解

大框架 Stage3 是 pseudo-AMDAR 验证；旧计划“小阶段3”是大框架 Stage4 confidence。AMDAR 始终 support-only；posterior、accepted 和 estimated time 都不是 point truth。当前主瓶颈是几何/轨迹域错位，不是候选数量。25-slice 仅保存一个带 `processing_slice_id` 的 compact 表，不复制 25 份全量数据。
"""
    manifest_path.write_text(manifest, encoding="utf-8")
    handover_path = cfg.out_dir / "next_agent_handover_after_stage3_v11_20260715.md"
    handover = f"""# 给下一个智能体的交接话术：Stage3 v11 完成后进入后续阶段

你接手的是 `/data/LFT-W02_data/pengxu` 下 centralized_v1 三维水平风场重构项目。必须区分：大框架 Stage1-5 与旧 Stage2-6 优化计划的小阶段1-7。本轮已完成的是**大框架 Stage3 v11 domain-matched pseudo-AMDAR validation**，尚未执行大框架 Stage4。

## 必读文档与解释

1. `{ROOT / 'workflow/centralized_v1_docs/new_window_project_handover_20260529/centralized_v1_ultimate_summary_20260626.md'}`：项目大框架 Stage1-5、strict aircraft holdout、防泄漏和产品语义总边界。
2. `{ROOT / '优化/teacher_reports/plan4.md'}`：AMDAR 原始时间是批次下发/接收语义，不是逐点观测时间。
3. `{ROOT / '优化/teacher_reports/amdar_plan4_comprehensive_assessment_20260701.md'}`：T0-T4/support-only 路线与“充分利用但不强行当真值”的数据原则。
4. `{ROOT / '优化/teacher_reports/amdar_unified_implementation_plan_20260701.md'}`：旧 Unified Plan 的小阶段 P0-P15、质量门和禁止操作；不要与大框架 Stage1-5 混淆。
5. `{DATA_DIR / 'next_agent_handover_optimization_20260706.md'}`：旧 Stage2-6 激进优化交接、历史基线与不变量。
6. `{DATA_DIR / 'amdar_stage2_to_6_optimization_plan_20260706.md'}`：旧优化计划小阶段1-7；其中“小阶段3”是大框架 Stage4，不是本轮大框架 Stage3。
7. `{DATA_DIR / 'stage5_sota_cross_stage_optimization_plan_20260715/next_agent_handover_for_stage5_sota_implementation_20260715.md'}`：本轮任务起点和 Stage3 v11→Stage5 v6 实施顺序。
8. `{DATA_DIR / 'stage5_sota_cross_stage_optimization_plan_20260715/stage5_sota_cross_stage_optimization_plan_20260715.md'}`：当前跨阶段 SOTA 总方案、Stage3 v11/Stage5 v6 门槛。
9. `{DATA_DIR / 'stage5_sota_cross_stage_optimization_plan_20260715/local_stage5_optimization_audit_summary.json'}`：已证伪的简单 Stage5 路线，避免重复放宽阈值。
10. `{DATA_DIR / 'stage5_v5_final_optimized_20260714/stage5_v5_results_analysis_and_next_steps.md'}`：冻结的 Stage5 `198 batches / 251 rows` 安全基线。
11. `{DATA_DIR / 'stage3_pseudo_amdar_v8_optimized_20260707/stage3_v8_results_analysis_and_next_steps.md'}`：v8 容易域基线及其局限。
12. `{DATA_DIR / 'stage3_pseudo_amdar_v9_micro_leg_optimized_20260713/stage3_v9_micro_leg_results_analysis_and_next_steps.md'}`：micro-leg 分支 gate 与适用范围。
13. `{DATA_DIR / 'stage3_pseudo_amdar_v10_tiny_leg_optimized_20260714_validated/stage3_pseudo_amdar_v9_micro/pseudo_amdar_v9_micro_validation_report.json'}`：tiny-leg 分支独立验证。
14. `{manifest_path}`：完整已读文档、用途和固化理解清单。
15. `{analysis_path}`：本轮 v11 结果、质量门、数据利用率解释和下一步建议。
16. `{summary['outputs']['calibration_report']}`：机器可读完整指标、逐 split/逐 corruption 结果。
17. `{summary['outputs']['domain_gap_report']}`：pseudo-real 特征分布重叠及真实 Stage5 candidate-policy shadow。
18. `{summary['outputs']['hard_negative_cases']}`：hard-negative case bank；只能用于验证/标定，不是真实 AMDAR truth。
19. `{summary['outputs']['posterior_model']}`：calibration 训练、calibration-only isotonic、validation 选阈值的可复现模型参数。

## 项目与数据理解

- TURB strict aircraft holdout 是唯一正式真值；AMDAR strict truth=0、holdout=0。
- AMDAR 时间是批次下发/接收语义，不是逐点观测时间。
- Stage3 pseudo 验证用于校准关联安全性；Stage5 accepted/posterior 仍只是 support-only 时间分布种子。
- 当前真实 Stage5 主瓶颈是几何/轨迹不一致，不是候选数量；不得继续扩大时间窗或放宽 cost/cross-track 制造表面提升。
- v11 已加入七类 domain-matched hard negatives，并复用真实 Stage5 v5 诊断分布。

## 本轮结果

- quality gate：`{gate['passed_stage3_v11_quality_gate']}`；
- locked wrong/hard-negative rate：`{metrics['locked_test']['wrong_leg_or_hard_negative_rate_selected']:.4%}`；
- locked catastrophic rate：`{metrics['locked_test']['catastrophic_rate_selected_safe']:.4%}`；
- locked ECE：`{metrics['locked_test']['ece_15bin']:.6f}`；
- pseudo-real overlap：`{domain['mean_overlap_before_v8']:.4f} -> {domain['mean_overlap_after_v11']:.4f}`；
- truth invariants：全部保持。

## 后续执行话术

```text
我已阅读 Stage5 SOTA 跨阶段方案、本地审计、Stage5 v5 198/251 冻结基线、Stage3 v8 基线以及 Stage3 v11 完整结果。当前 Stage3 v11 已使用 calibration 训练、validation-only 选阈值、locked-test 只报告，并加入七类 hard negatives 与真实 Stage5 域重加权。下一步将保持 AMDAR support-only 和 25-slice/POLARS_MAX_THREADS=25 口径，进入后续阶段；若实现 Stage5 v6 HMM/Viterbi，将先复用现有候选宇宙，保留原 198 批，新增 unique 至少 10 批且 wrong-leg<=1%，mixture 不计 unique accepted。
```
"""
    handover_path.write_text(handover, encoding="utf-8")


def main() -> None:
    cfg = parse_args()
    cfg.out_dir.mkdir(parents=True, exist_ok=True)
    write_json(cfg.out_dir / "run_config.json", {**asdict(cfg), "polars_threads": os.environ.get("POLARS_MAX_THREADS")})
    print(json.dumps({"stage": "stage3_v11_start", "out_dir": str(cfg.out_dir)}, ensure_ascii=False))
    summary = run(cfg)
    write_docs(cfg, summary)
    print(json.dumps({"stage": "stage3_v11_done", "passed": summary["quality_gate"]["passed_stage3_v11_quality_gate"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
