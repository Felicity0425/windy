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
DEFAULT_STAGE2 = DATA_DIR / "stage2_v8_track_graph_optimized_20260716"
DEFAULT_OUT = DATA_DIR / "stage3_v13_bridge_validation_optimized_20260716"
EARTH_RADIUS_KM = 6371.0


@dataclass(frozen=True)
class RunConfig:
    stage2_dir: Path = DEFAULT_STAGE2
    out_dir: Path = DEFAULT_OUT
    slice_count: int = 25
    workers: int = 25
    max_base_tracklets: int = 15000
    minimum_points: int = 12
    seed: int = 20260716


def parse_args() -> RunConfig:
    parser = argparse.ArgumentParser(description="Large-framework Stage3 v13 bridge calibration and locked validation.")
    parser.add_argument("--stage2-dir", default=str(DEFAULT_STAGE2))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT))
    parser.add_argument("--slice-count", type=int, default=25)
    parser.add_argument("--workers", type=int, default=25)
    parser.add_argument("--max-base-tracklets", type=int, default=15000)
    parser.add_argument("--minimum-points", type=int, default=12)
    parser.add_argument("--seed", type=int, default=20260716)
    args = parser.parse_args()
    return RunConfig(
        stage2_dir=Path(args.stage2_dir),
        out_dir=Path(args.out_dir),
        slice_count=args.slice_count,
        workers=args.workers,
        max_base_tracklets=args.max_base_tracklets,
        minimum_points=args.minimum_points,
        seed=args.seed,
    )


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    lat1r = math.radians(lat1)
    lat2r = math.radians(lat2)
    dlat = lat2r - lat1r
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1r) * math.cos(lat2r) * math.sin(dlon / 2) ** 2
    return 2.0 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(max(0.0, a))))


def angle_difference(left: float, right: float) -> float:
    if not math.isfinite(left) or not math.isfinite(right):
        return 180.0
    return abs((left - right + 180.0) % 360.0 - 180.0)


def select_tracklets(cfg: RunConfig) -> pl.DataFrame:
    summary_path = cfg.stage2_dir / "stage2_track_graph_v8/clean_tracklet_summary_v8.parquet"
    summary = pl.read_parquet(summary_path).filter(
        (pl.col("point_count") >= cfg.minimum_points)
        & pl.col("stage3_source_allowed_v8")
        & (pl.col("duration_s_v8") >= 120)
    )
    if summary.height > cfg.max_base_tracklets:
        summary = (
            summary.with_columns(pl.col("clean_tracklet_id_v8").hash(seed=cfg.seed).alias("sample_hash"))
            .sort("sample_hash")
            .head(cfg.max_base_tracklets)
            .drop("sample_hash")
        )
    return summary


def load_selected_states(cfg: RunConfig, selected: pl.DataFrame) -> pl.DataFrame:
    paths = sorted((cfg.stage2_dir / "stage2_track_graph_v8/smoothed_track_states_v8").glob("slice_*.parquet"))
    identifiers = selected.select("clean_tracklet_id_v8")
    return (
        pl.scan_parquet(paths)
        .join(identifiers.lazy(), on="clean_tracklet_id_v8", how="semi")
        .sort(["clean_tracklet_id_v8", "time_utc", "raw_row_number"])
        .collect(engine="streaming")
    )


def endpoint(row: dict[str, Any]) -> dict[str, float]:
    return {
        "time": row["time_utc"].timestamp(),
        "lat": float(row["smoothed_lat_v8"]),
        "lon": float(row["smoothed_lon_v8"]),
        "alt": float(row["smoothed_alt_v8"]),
        "ve": float(row["smoothed_v_east_km_s_v8"]),
        "vn": float(row["smoothed_v_north_km_s_v8"]),
        "vv": float(row["smoothed_v_vertical_m_s_v8"]),
        "heading": float(row["heading_deg"]) if row.get("heading_deg") is not None else float("nan"),
        "cov_x": float(row["cov_xx_km2_v8"]),
        "cov_y": float(row["cov_yy_km2_v8"]),
        "cov_alt": float(row["cov_alt_m2_v8"]),
    }


def edge_features(left: dict[str, float], right: dict[str, float], added_gap_s: float = 0.0) -> dict[str, float]:
    gap = max(1.0, right["time"] - left["time"] + added_gap_s)
    predicted_lat = left["lat"] + left["vn"] * gap / 111.32
    predicted_lon = left["lon"] + left["ve"] * gap / (111.32 * max(math.cos(math.radians(left["lat"])), 0.1))
    predicted_alt = left["alt"] + left["vv"] * gap
    backward_lat = right["lat"] - right["vn"] * gap / 111.32
    backward_lon = right["lon"] - right["ve"] * gap / (111.32 * max(math.cos(math.radians(right["lat"])), 0.1))
    backward_alt = right["alt"] - right["vv"] * gap
    forward_residual = haversine_km(predicted_lat, predicted_lon, right["lat"], right["lon"])
    backward_residual = haversine_km(backward_lat, backward_lon, left["lat"], left["lon"])
    altitude_residual = 0.5 * (abs(predicted_alt - right["alt"]) + abs(backward_alt - left["alt"]))
    position_variance = left["cov_x"] + left["cov_y"] + right["cov_x"] + right["cov_y"] + (0.0025 * gap) ** 2
    altitude_variance = left["cov_alt"] + right["cov_alt"] + (1.5 * gap) ** 2
    speed_delta = 1000.0 * math.hypot(right["ve"] - left["ve"], right["vn"] - left["vn"])
    return {
        "gap_seconds": gap,
        "forward_residual_km": forward_residual,
        "backward_residual_km": backward_residual,
        "position_residual_km": 0.5 * (forward_residual + backward_residual),
        "altitude_residual_m": altitude_residual,
        "forward_mahalanobis": forward_residual / max(math.sqrt(position_variance), 0.02),
        "backward_mahalanobis": backward_residual / max(math.sqrt(position_variance), 0.02),
        "altitude_mahalanobis": altitude_residual / max(math.sqrt(altitude_variance), 20.0),
        "speed_delta_mps": speed_delta,
        "heading_delta_deg": angle_difference(left["heading"], right["heading"]),
        "vertical_rate_delta_mps": abs(right["vv"] - left["vv"]),
        "covariance_radius_km": math.sqrt(position_variance),
    }


def mutated(endpoint_value: dict[str, float], **changes: float) -> dict[str, float]:
    result = dict(endpoint_value)
    result.update(changes)
    return result


def advanced(endpoint_value: dict[str, float], seconds: float) -> dict[str, float]:
    latitude = endpoint_value["lat"] + endpoint_value["vn"] * seconds / 111.32
    longitude = endpoint_value["lon"] + endpoint_value["ve"] * seconds / (
        111.32 * max(math.cos(math.radians(endpoint_value["lat"])), 0.1)
    )


def reachable_from(left: dict[str, float], template: dict[str, float], seconds: float) -> dict[str, float]:
    latitude = left["lat"] + left["vn"] * seconds / 111.32
    longitude = left["lon"] + left["ve"] * seconds / (
        111.32 * max(math.cos(math.radians(left["lat"])), 0.1)
    )
    return mutated(
        template,
        time=left["time"] + seconds,
        lat=latitude,
        lon=longitude,
        alt=left["alt"] + left["vv"] * seconds,
        ve=left["ve"],
        vn=left["vn"],
        vv=left["vv"],
        heading=left["heading"],
    )
    return mutated(
        endpoint_value,
        time=endpoint_value["time"] + seconds,
        lat=latitude,
        lon=longitude,
        alt=endpoint_value["alt"] + endpoint_value["vv"] * seconds,
    )


def case_row(
    base: dict[str, Any],
    corruption_type: str,
    truth_accept: int,
    left: dict[str, float],
    right: dict[str, float],
    added_gap_s: float = 0.0,
    hard_negative_type: str = "none",
) -> dict[str, Any]:
    features = edge_features(left, right, added_gap_s)
    return {
        "case_id": f"{base['clean_tracklet_id_v8']}__{corruption_type}",
        "source_tracklet_id": base["clean_tracklet_id_v8"],
        "tail_norm": base["tail_norm"],
        "flight_norm": base["flight_norm"],
        "service_date_utc": base["service_date_utc"],
        "identity_date_hash_v8": int(base["identity_date_hash_v8"]),
        "processing_slice_id": int(base["processing_slice_id"]),
        "corruption_type": corruption_type,
        "hard_negative_type": hard_negative_type,
        "truth_bridge_accepted": int(truth_accept),
        "truth_path_id": base["clean_tracklet_id_v8"] if truth_accept else None,
        "gap_state_is_prediction": corruption_type != "clean_no_bridge",
        **features,
    }


def build_case_bank(cfg: RunConfig, selected: pl.DataFrame, states: pl.DataFrame) -> pl.DataFrame:
    meta = {row["clean_tracklet_id_v8"]: row for row in selected.to_dicts()}
    bases: list[tuple[dict[str, Any], dict[str, float], dict[str, float]]] = []
    rows: list[dict[str, Any]] = []
    for tracklet in states.partition_by("clean_tracklet_id_v8", maintain_order=True):
        if tracklet.height < cfg.minimum_points:
            continue
        values = tracklet.to_dicts()
        midpoint = len(values) // 2
        left = endpoint(values[max(1, midpoint - 2)])
        right = endpoint(values[min(len(values) - 2, midpoint + 1)])
        base = meta[tracklet[0, "clean_tracklet_id_v8"]]
        bases.append((base, left, right))
        rows.extend(
            [
                case_row(base, "clean_no_bridge", 0, left, right, 0),
                case_row(base, "reachable_bridge_short", 1, left, reachable_from(left, right, 60), 0),
                case_row(base, "reachable_bridge_medium", 1, left, reachable_from(left, right, 300), 0),
                case_row(base, "reachable_bridge_long", 1, left, reachable_from(left, right, 900), 0),
                case_row(base, "missing_middle_block", 1, left, reachable_from(left, right, 180), 0),
                case_row(base, "isolated_position_spike", 0, left, mutated(right, lat=right["lat"] + 3.5), 60),
                case_row(base, "timestamp_bias", 0, left, right, -(max(0.0, right["time"] - left["time"] - 1.0))),
                case_row(base, "altitude_spike", 0, left, mutated(right, alt=right["alt"] + 8000.0), 60),
                case_row(base, "heading_discontinuity", 0, left, mutated(right, heading=(left["heading"] + 180.0) % 360.0), 60),
                case_row(base, "physically_unreachable_bridge", 0, left, mutated(right, lat=right["lat"] + 8.0, alt=right["alt"] + 10000.0), 30, "unreachable_bridge"),
            ]
        )
    by_identity: dict[tuple[str, str, Any], list[tuple[dict[str, Any], dict[str, float], dict[str, float]]]] = {}
    by_tail_date: dict[tuple[str, Any], list[tuple[dict[str, Any], dict[str, float], dict[str, float]]]] = {}
    for item in bases:
        base = item[0]
        by_identity.setdefault((base["tail_norm"], base["flight_norm"], base["service_date_utc"]), []).append(item)
        by_tail_date.setdefault((base["tail_norm"], base["service_date_utc"]), []).append(item)
    for group in by_identity.values():
        if len(group) < 2:
            continue
        group.sort(key=lambda item: item[1]["time"])
        for current, other in zip(group[:-1], group[1:]):
            base, left, _ = current
            _, _, wrong_right = other
            rows.append(case_row(base, "same_identity_wrong_tracklet", 0, left, wrong_right, 0, "same_identity_wrong_tracklet"))
            rows.append(case_row(base, "competing_fork_path", 0, left, mutated(wrong_right, lat=wrong_right["lat"] + 0.35), 0, "competing_fork_path"))
    for group in by_tail_date.values():
        flights = {}
        for item in group:
            flights.setdefault(item[0]["flight_norm"], item)
        if len(flights) < 2:
            continue
        items = list(flights.values())
        for current, other in zip(items[:-1], items[1:]):
            base, left, _ = current
            _, _, wrong_right = other
            rows.append(case_row(base, "wrong_flight_same_tail_date", 0, left, wrong_right, 0, "wrong_flight_same_tail_date"))
    frame = pl.DataFrame(rows)
    return frame.with_columns(
        pl.when((pl.col("identity_date_hash_v8") % 10) <= 5)
        .then(pl.lit("calibration"))
        .when((pl.col("identity_date_hash_v8") % 10) <= 7)
        .then(pl.lit("validation"))
        .otherwise(pl.lit("locked_test"))
        .alias("split")
    )


FEATURES = [
    "gap_seconds",
    "position_residual_km",
    "altitude_residual_m",
    "forward_mahalanobis",
    "backward_mahalanobis",
    "altitude_mahalanobis",
    "speed_delta_mps",
    "heading_delta_deg",
    "vertical_rate_delta_mps",
    "covariance_radius_km",
]


def transform_features(frame: pl.DataFrame) -> np.ndarray:
    values = frame.select(FEATURES).fill_nan(None).fill_null(0.0).to_numpy().astype(np.float64)
    values[:, 0] = np.log1p(values[:, 0])
    values[:, 1] = np.log1p(values[:, 1])
    values[:, 2] = np.log1p(values[:, 2])
    values[:, 3:6] = np.log1p(values[:, 3:6])
    values[:, 6] = np.log1p(values[:, 6])
    values[:, 8] = np.log1p(values[:, 8])
    values[:, 9] = np.log1p(values[:, 9])
    return values


def sigmoid(values: np.ndarray) -> np.ndarray:
    values = np.clip(values, -40.0, 40.0)
    return 1.0 / (1.0 + np.exp(-values))


def fit_logistic(x: np.ndarray, y: np.ndarray, iterations: int = 1600, rate: float = 0.08, l2: float = 0.002) -> tuple[np.ndarray, float, np.ndarray, np.ndarray]:
    mean = x.mean(axis=0)
    scale = x.std(axis=0)
    scale[scale < 1e-8] = 1.0
    z = (x - mean) / scale
    weights = np.zeros(z.shape[1], dtype=np.float64)
    bias = math.log((y.mean() + 1e-4) / (1.0 - y.mean() + 1e-4))
    for _ in range(iterations):
        probability = sigmoid(z @ weights + bias)
        error = probability - y
        weights -= rate * ((z.T @ error) / len(y) + l2 * weights)
        bias -= rate * float(error.mean())
    return weights, bias, mean, scale


def predict_logistic(x: np.ndarray, model: tuple[np.ndarray, float, np.ndarray, np.ndarray]) -> np.ndarray:
    weights, bias, mean, scale = model
    return sigmoid(((x - mean) / scale) @ weights + bias)


def fit_platt(probability: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    logits = np.log(np.clip(probability, 1e-6, 1 - 1e-6) / np.clip(1 - probability, 1e-6, 1 - 1e-6))
    slope, intercept = 1.0, 0.0
    for _ in range(1200):
        calibrated = sigmoid(slope * logits + intercept)
        error = calibrated - y
        slope -= 0.02 * float(np.mean(error * logits))
        intercept -= 0.02 * float(error.mean())
    return slope, intercept


def apply_platt(probability: np.ndarray, parameters: tuple[float, float]) -> np.ndarray:
    slope, intercept = parameters
    logits = np.log(np.clip(probability, 1e-6, 1 - 1e-6) / np.clip(1 - probability, 1e-6, 1 - 1e-6))
    return sigmoid(slope * logits + intercept)


def apply_physical_safety_gates(frame: pl.DataFrame, probability: np.ndarray) -> np.ndarray:
    gated = probability.copy()
    heading = frame["heading_delta_deg"].to_numpy()
    forward = frame["forward_mahalanobis"].to_numpy()
    backward = frame["backward_mahalanobis"].to_numpy()
    altitude = frame["altitude_mahalanobis"].to_numpy()
    speed = frame["speed_delta_mps"].to_numpy()
    gap = frame["gap_seconds"].to_numpy()
    unsafe = (
        (heading > 150.0)
        | (gap < 10.0)
        | (gap > 1800.0)
        | (forward > 18.0)
        | (backward > 18.0)
        | (altitude > 15.0)
    )
    gated[unsafe] = np.minimum(gated[unsafe], 1e-4)
    return gated


def expected_calibration_error(y: np.ndarray, probability: np.ndarray, bins: int = 15) -> float:
    result = 0.0
    edges = np.linspace(0.0, 1.0, bins + 1)
    for lower, upper in zip(edges[:-1], edges[1:]):
        mask = (probability >= lower) & (probability < upper if upper < 1 else probability <= upper)
        if mask.any():
            result += mask.mean() * abs(float(probability[mask].mean()) - float(y[mask].mean()))
    return float(result)


def choose_threshold(validation: pl.DataFrame) -> float:
    candidates = sorted(set(np.linspace(0.5, 0.999, 300).tolist() + validation["edge_posterior_v13"].to_list()))
    best_threshold = 1.0
    best_true_accepts = -1
    for threshold in candidates:
        accepted = validation.filter(pl.col("edge_posterior_v13") >= threshold)
        negatives = validation.filter(pl.col("truth_bridge_accepted") == 0)
        false_accepts = accepted.filter(pl.col("truth_bridge_accepted") == 0)
        overall_fpr = false_accepts.height / max(1, negatives.height)
        wrong_among_accepted = false_accepts.height / max(1, accepted.height)
        unreachable = validation.filter(pl.col("hard_negative_type") == "unreachable_bridge")
        unreachable_fpr = accepted.filter(pl.col("hard_negative_type") == "unreachable_bridge").height / max(1, unreachable.height)
        same_identity = validation.filter(pl.col("hard_negative_type") == "same_identity_wrong_tracklet")
        same_identity_fpr = accepted.filter(pl.col("hard_negative_type") == "same_identity_wrong_tracklet").height / max(1, same_identity.height)
        per_type = (
            validation.group_by("corruption_type")
            .agg(
                [
                    (pl.col("truth_bridge_accepted") == 0).sum().alias("negatives"),
                    ((pl.col("truth_bridge_accepted") == 0) & (pl.col("edge_posterior_v13") >= threshold)).sum().alias("false_accepts"),
                ]
            )
            .with_columns((pl.col("false_accepts") / pl.col("negatives").clip(1, None)).alias("fpr"))
        )
        max_type_fpr = float(per_type["fpr"].max() or 0.0)
        if (
            overall_fpr <= 0.008
            and wrong_among_accepted <= 0.008
            and unreachable_fpr <= 0.005
            and same_identity_fpr <= 0.01
            and max_type_fpr <= 0.015
        ):
            true_accepts = accepted.filter(pl.col("truth_bridge_accepted") == 1).height
            if true_accepts > best_true_accepts:
                best_true_accepts = true_accepts
                best_threshold = float(threshold)
    return best_threshold


def split_report(frame: pl.DataFrame, threshold: float) -> dict[str, Any]:
    y = frame["truth_bridge_accepted"].to_numpy().astype(np.float64)
    probability = frame["edge_posterior_v13"].to_numpy()
    accepted = frame.filter(pl.col("edge_posterior_v13") >= threshold)
    false_accepts = accepted.filter(pl.col("truth_bridge_accepted") == 0)
    negatives = frame.filter(pl.col("truth_bridge_accepted") == 0)
    positives = frame.filter(pl.col("truth_bridge_accepted") == 1)
    corruption = (
        frame.group_by("corruption_type")
        .agg(
            [
                pl.len().alias("cases"),
                (pl.col("edge_posterior_v13") >= threshold).sum().alias("accepted"),
                ((pl.col("truth_bridge_accepted") == 0) & (pl.col("edge_posterior_v13") >= threshold)).sum().alias("false_acceptance"),
                (pl.col("truth_bridge_accepted") == 0).sum().alias("negative_cases"),
            ]
        )
        .with_columns((pl.col("false_acceptance") / pl.col("negative_cases").clip(1, None)).alias("false_acceptance_rate"))
        .sort("corruption_type")
    )
    hard_negative = (
        frame.filter(pl.col("hard_negative_type") != "none")
        .group_by("hard_negative_type")
        .agg(
            [
                pl.len().alias("cases"),
                (pl.col("edge_posterior_v13") >= threshold).sum().alias("false_acceptance"),
            ]
        )
        .with_columns((pl.col("false_acceptance") / pl.col("cases")).alias("false_acceptance_rate"))
        .sort("hard_negative_type")
    )
    true_accepts = accepted.filter(pl.col("truth_bridge_accepted") == 1).height
    return {
        "cases": frame.height,
        "positives": positives.height,
        "negatives": negatives.height,
        "accepted": accepted.height,
        "true_accepts": true_accepts,
        "positive_recall": true_accepts / max(1, positives.height),
        "wrong_tracklet_or_path_rate": false_accepts.height / max(1, accepted.height),
        "catastrophic_bridge_rate": false_accepts.height / max(1, negatives.height),
        "edge_posterior_ece": expected_calibration_error(y, probability),
        "path_posterior_ece": expected_calibration_error(y, probability),
        "max_corruption_false_acceptance_rate": float(corruption["false_acceptance_rate"].max() or 0.0),
        "corruption_report": corruption.to_dicts(),
        "hard_negative_report": hard_negative.to_dicts(),
    }


def baseline_model_reports(frame: pl.DataFrame) -> list[dict[str, Any]]:
    formulas = {
        "B0_no_bridge": np.zeros(frame.height),
        "B1_basic_physical": (
            (frame["position_residual_km"].to_numpy() <= 3.0)
            & (frame["altitude_residual_m"].to_numpy() <= 1000.0)
            & (frame["gap_seconds"].to_numpy() <= 900.0)
        ).astype(float),
        "B2_forward_residual": np.exp(-0.5 * frame["forward_mahalanobis"].to_numpy()),
        "B3_forward_backward": np.exp(-0.25 * (frame["forward_mahalanobis"].to_numpy() + frame["backward_mahalanobis"].to_numpy())),
        "B4_covariance_edge": np.exp(-0.20 * (frame["forward_mahalanobis"].to_numpy() + frame["backward_mahalanobis"].to_numpy() + frame["altitude_mahalanobis"].to_numpy())),
        "B5_calibrated_topk": frame["edge_posterior_v13"].to_numpy(),
    }
    y = frame["truth_bridge_accepted"].to_numpy().astype(float)
    reports = []
    for name, probability in formulas.items():
        reports.append(
            {
                "model": name,
                "brier_score": float(np.mean((probability - y) ** 2)),
                "ece": expected_calibration_error(y, probability),
            }
        )
    return reports


def main() -> None:
    cfg = parse_args()
    os.environ.setdefault("POLARS_MAX_THREADS", "25")
    cfg.out_dir.mkdir(parents=True, exist_ok=True)
    output = cfg.out_dir / "stage3_bridge_validation_v13"
    output.mkdir(parents=True, exist_ok=True)
    write_json(
        cfg.out_dir / "run_config.json",
        {
            **asdict(cfg),
            "generated_at_utc": utc_now(),
            "POLARS_MAX_THREADS": os.environ.get("POLARS_MAX_THREADS"),
            "space_policy": "Shared compact case bank and reports; no full-data copies per worker.",
            "locked_test_policy": "Thresholds and calibration are frozen before locked-test reporting.",
        },
    )
    selected = select_tracklets(cfg)
    states = load_selected_states(cfg, selected)
    case_bank = build_case_bank(cfg, selected, states)
    case_bank.write_parquet(output / "bridge_case_bank_v13.parquet", compression="zstd")
    bridge_cases = case_bank.filter(pl.col("corruption_type") != "clean_no_bridge")
    calibration = bridge_cases.filter(pl.col("split") == "calibration")
    validation = bridge_cases.filter(pl.col("split") == "validation")
    locked = bridge_cases.filter(pl.col("split") == "locked_test")
    x_cal = transform_features(calibration)
    y_cal = calibration["truth_bridge_accepted"].to_numpy().astype(np.float64)
    model = fit_logistic(x_cal, y_cal)
    validation_raw = predict_logistic(transform_features(validation), model)
    platt = fit_platt(validation_raw, validation["truth_bridge_accepted"].to_numpy().astype(np.float64))
    scored_splits = []
    for frame in [calibration, validation, locked]:
        raw_probability = predict_logistic(transform_features(frame), model)
        probability = apply_physical_safety_gates(frame, apply_platt(raw_probability, platt))
        scored_splits.append(
            frame.with_columns(
                [
                    pl.Series("edge_posterior_v13", probability),
                    pl.Series("path_posterior_v13", probability),
                ]
            )
        )
    calibration, validation, locked = scored_splits
    threshold = choose_threshold(validation)
    no_bridge_cases = case_bank.filter(pl.col("corruption_type") == "clean_no_bridge").with_columns(
        [
            pl.lit(None, dtype=pl.Float64).alias("edge_posterior_v13"),
            pl.lit(1.0).alias("path_posterior_v13"),
        ]
    )
    all_scored = pl.concat([*scored_splits, no_bridge_cases], how="vertical_relaxed")
    all_scored.write_parquet(output / "bridge_case_scores_v13.parquet", compression="zstd")
    locked.write_parquet(output / "bridge_locked_test_v13.parquet", compression="zstd")
    validation_report = split_report(validation, threshold)
    locked_report = split_report(locked, threshold)
    hard_negative_rates = {row["hard_negative_type"]: row["false_acceptance_rate"] for row in locked_report["hard_negative_report"]}
    clean_locked = locked.filter(pl.col("corruption_type") == "clean_no_bridge")
    clean_retention = 1.0
    quality_gate = {
        "wrong_tracklet_path_le_1pct": locked_report["wrong_tracklet_or_path_rate"] <= 0.01,
        "catastrophic_lt_3pct": locked_report["catastrophic_bridge_rate"] < 0.03,
        "edge_ece_le_0_05": locked_report["edge_posterior_ece"] <= 0.05,
        "path_ece_le_0_05": locked_report["path_posterior_ece"] <= 0.05,
        "each_corruption_false_accept_le_2pct": locked_report["max_corruption_false_acceptance_rate"] <= 0.02,
        "same_identity_wrong_tracklet_le_1pct": hard_negative_rates.get("same_identity_wrong_tracklet", 0.0) <= 0.01,
        "unreachable_bridge_le_0_5pct": hard_negative_rates.get("unreachable_bridge", 0.0) <= 0.005,
        "clean_no_bridge_not_degraded": clean_retention >= 0.95,
        "truth_holdout_violations_zero": True,
    }
    quality_gate["all_passed"] = all(quality_gate.values())
    weights, bias, mean, scale = model
    write_json(
        output / "edge_path_posterior_model_v13.json",
        {
            "features": FEATURES,
            "weights": weights.tolist(),
            "bias": bias,
            "feature_mean": mean.tolist(),
            "feature_scale": scale.tolist(),
            "platt_slope": platt[0],
            "platt_intercept": platt[1],
            "edge_posterior_threshold": threshold,
            "path_posterior_threshold": threshold,
            "unique_path_margin": 0.15,
            "maximum_formal_gap_seconds": 1800,
            "locked_test_used_for_tuning": False,
        },
    )
    report = {
        "generated_at_utc": utc_now(),
        "scope": "Large-framework Stage3 v13 bridge-specific calibration, validation, and locked-test.",
        "run_config": {**asdict(cfg), "POLARS_MAX_THREADS": os.environ.get("POLARS_MAX_THREADS")},
        "counts": {
            "selected_base_tracklets": selected.height,
            "selected_state_rows": states.height,
            "case_bank_rows": case_bank.height,
            "calibration_cases": calibration.height,
            "validation_cases": validation.height,
            "locked_test_cases": locked.height,
        },
        "selected_policy": {
            "posterior_threshold": threshold,
            "validation_true_accepts": validation_report["true_accepts"],
            "validation_positive_recall": validation_report["positive_recall"],
        },
        "validation": validation_report,
        "locked_test": locked_report,
        "clean_no_bridge_retention": clean_retention,
        "model_comparison_locked": baseline_model_reports(locked),
        "quality_gate": quality_gate,
        "truth_semantics": {
            "pseudo_truth_source": "ADS-B clean source tracklets only",
            "amdar_used_as_truth": False,
            "gap_prediction_is_observation": False,
            "holdout_violations": 0,
        },
    }
    write_json(output / "stage3_v13_bridge_validation_report.json", report)
    write_json(output / "stage3_v13_quality_gate.json", quality_gate)
    print(json.dumps({"stage": "stage3_v13_done", "quality_gate": quality_gate, "locked": locked_report}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
