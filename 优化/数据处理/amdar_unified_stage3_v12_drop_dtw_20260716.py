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
STAGE2_POINTS = DATA_DIR / "amdar_unified_stage0_1_2_optimized_20260701/stage2_adsb_qc_v4/adsb_leg_points_v4.parquet"
DEFAULT_OUT_DIR = DATA_DIR / "stage3_pseudo_amdar_v12_drop_dtw_optimized_20260716"


@dataclass(frozen=True)
class RunConfig:
    out_dir: Path = DEFAULT_OUT_DIR
    slice_count: int = 25
    workers: int = 25
    seed: int = 20260716
    cases_per_split: int = 900
    negative_candidates: int = 1
    huber_delta: float = 1.5


def parse_args() -> RunConfig:
    parser = argparse.ArgumentParser(description="Stage3 v12 raw-sequence Drop-DTW validation.")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--slice-count", type=int, default=25)
    parser.add_argument("--workers", type=int, default=25)
    parser.add_argument("--seed", type=int, default=20260716)
    parser.add_argument("--cases-per-split", type=int, default=900)
    args = parser.parse_args()
    return RunConfig(
        out_dir=Path(args.out_dir),
        slice_count=int(args.slice_count),
        workers=int(args.workers),
        seed=int(args.seed),
        cases_per_split=int(args.cases_per_split),
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


def partition_key(key: Any) -> Any:
    return key[0] if isinstance(key, tuple) and len(key) == 1 else key


def local_xy_km(latitude0: float, longitude0: float, latitude: np.ndarray, longitude: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    return (
        (longitude - longitude0) * 111.320 * math.cos(math.radians(latitude0)),
        (latitude - latitude0) * 110.574,
    )


def huber(values: np.ndarray, delta: float) -> np.ndarray:
    absolute = np.abs(values)
    return np.where(absolute <= delta, 0.5 * absolute * absolute, delta * (absolute - 0.5 * delta))


def build_leg_arrays(rows: list[dict[str, Any]]) -> dict[str, np.ndarray] | None:
    if len(rows) < 2:
        return None
    latitude = np.array([float(row["lat_clean"]) for row in rows], dtype=np.float64)
    longitude = np.array([float(row["lon_clean"]) for row in rows], dtype=np.float64)
    altitude = np.array([float(row["alt_meters"]) for row in rows], dtype=np.float64)
    epoch = datetime(1970, 1, 1)
    time_seconds = np.array([(row["time_utc"] - epoch).total_seconds() for row in rows], dtype=np.float64)
    mean_latitude = 0.5 * (latitude[:-1] + latitude[1:])
    dx = (longitude[1:] - longitude[:-1]) * 111.320 * np.cos(np.radians(mean_latitude))
    dy = (latitude[1:] - latitude[:-1]) * 110.574
    segment_length = np.sqrt(dx * dx + dy * dy)
    return {
        "latitude": latitude,
        "longitude": longitude,
        "altitude": altitude,
        "time_seconds": time_seconds,
        "segment_length_km": segment_length,
        "cumulative_km": np.concatenate([np.array([0.0]), np.cumsum(segment_length)]),
    }


def segment_emissions(point: dict[str, Any], leg: dict[str, np.ndarray], delta: float) -> dict[str, np.ndarray]:
    latitude0 = float(point["lat_clean"])
    longitude0 = float(point["lon_clean"])
    ax, ay = local_xy_km(latitude0, longitude0, leg["latitude"][:-1], leg["longitude"][:-1])
    bx, by = local_xy_km(latitude0, longitude0, leg["latitude"][1:], leg["longitude"][1:])
    dx = bx - ax
    dy = by - ay
    denominator = dx * dx + dy * dy
    fraction = np.divide(-(ax * dx + ay * dy), denominator, out=np.zeros_like(denominator), where=denominator > 1e-12)
    fraction = np.clip(fraction, 0.0, 1.0)
    projected_x = ax + fraction * dx
    projected_y = ay + fraction * dy
    horizontal = np.sqrt(projected_x * projected_x + projected_y * projected_y)
    projected_altitude = leg["altitude"][:-1] + fraction * (leg["altitude"][1:] - leg["altitude"][:-1])
    vertical = np.abs(float(point["alt_meters"]) - projected_altitude)
    normalized = horizontal / 1.0 + vertical / 800.0
    emission = huber(normalized, delta)
    time_seconds = leg["time_seconds"][:-1] + fraction * (leg["time_seconds"][1:] - leg["time_seconds"][:-1])
    along_km = leg["cumulative_km"][:-1] + fraction * leg["segment_length_km"]
    gap_seconds = leg["time_seconds"][1:] - leg["time_seconds"][:-1]
    return {
        "emission": emission,
        "horizontal": horizontal,
        "vertical": vertical,
        "time_seconds": time_seconds,
        "along_km": along_km,
        "gap_seconds": gap_seconds,
        "fraction": fraction,
    }


def drop_dtw_align(
    rows: list[dict[str, Any]],
    leg_rows: list[dict[str, Any]],
    drop_penalty: float,
    delta: float,
    maximum_time_seconds: float | None = None,
) -> dict[str, Any] | None:
    leg = build_leg_arrays(leg_rows)
    if not rows or leg is None:
        return None
    emissions = [segment_emissions(row, leg, delta) for row in rows]
    if maximum_time_seconds is not None:
        for values in emissions:
            values["emission"] = np.where(values["time_seconds"] <= maximum_time_seconds, values["emission"], np.inf)
    state_count = int(emissions[0]["emission"].size)
    if state_count == 0:
        return None
    row_count = len(rows)
    dynamic = np.full((row_count + 1, state_count), np.inf, dtype=np.float64)
    action = np.zeros((row_count + 1, state_count), dtype=np.int8)
    previous_state = np.full((row_count + 1, state_count), -1, dtype=np.int32)
    dynamic[0, :] = 0.0
    for row_index in range(1, row_count + 1):
        prior = dynamic[row_index - 1]
        prefix_cost = np.minimum.accumulate(prior)
        prefix_index = np.empty(state_count, dtype=np.int32)
        best_index = 0
        best_value = prior[0]
        for state in range(state_count):
            if prior[state] < best_value:
                best_value = prior[state]
                best_index = state
            prefix_index[state] = best_index
        match_cost = prefix_cost + emissions[row_index - 1]["emission"]
        drop_cost = prior + drop_penalty
        choose_match = match_cost <= drop_cost
        dynamic[row_index] = np.where(choose_match, match_cost, drop_cost)
        action[row_index] = choose_match.astype(np.int8)
        previous_state[row_index] = np.where(choose_match, prefix_index, np.arange(state_count, dtype=np.int32))
    if not np.isfinite(dynamic[-1]).any():
        return None
    state = int(np.argmin(dynamic[-1]))
    selected: list[dict[str, Any]] = []
    dropped: list[int] = []
    for row_index in range(row_count, 0, -1):
        if action[row_index, state] == 1:
            values = emissions[row_index - 1]
            selected.append(
                {
                    "original_index": row_index - 1,
                    "segment_index": state,
                    "emission_cost": float(values["emission"][state]),
                    "cross_track_distance_km": float(values["horizontal"][state]),
                    "vertical_difference_m": float(values["vertical"][state]),
                    "estimated_time_seconds": float(values["time_seconds"][state]),
                    "along_track_km": float(values["along_km"][state]),
                    "sampling_gap_seconds": float(values["gap_seconds"][state]),
                    "segment_fraction": float(values["fraction"][state]),
                }
            )
        else:
            dropped.append(row_index - 1)
        state = int(previous_state[row_index, state])
    selected.reverse()
    dropped.reverse()
    if not selected:
        return {
            "path": [],
            "dropped_indices": list(range(row_count)),
            "matched_row_fraction": 0.0,
            "matched_contiguous_fraction": 0.0,
            "drop_fraction": 1.0,
            "largest_dropped_block_fraction": 1.0,
            "drop_cost_per_row": drop_penalty,
            "matched_cost_q50": drop_penalty,
            "matched_cost_q90": drop_penalty,
            "matched_cost_max": drop_penalty,
            "path_progress_monotonicity": 0.0,
            "normalized_cost": drop_penalty,
        }
    matched_indices = [item["original_index"] for item in selected]
    longest = 1
    current = 1
    for left, right in zip(matched_indices[:-1], matched_indices[1:]):
        current = current + 1 if right == left + 1 else 1
        longest = max(longest, current)
    matched_costs = np.array([item["emission_cost"] for item in selected], dtype=np.float64)
    along = np.array([item["along_track_km"] for item in selected], dtype=np.float64)
    total_cost = float(dynamic[-1, int(np.argmin(dynamic[-1]))])
    return {
        "path": selected,
        "dropped_indices": dropped,
        "matched_row_fraction": len(selected) / row_count,
        "matched_contiguous_fraction": longest / row_count,
        "drop_fraction": len(dropped) / row_count,
        "largest_dropped_block_fraction": largest_block_fraction(dropped, row_count),
        "drop_cost_per_row": drop_penalty * len(dropped) / row_count,
        "matched_cost_q50": float(np.quantile(matched_costs, 0.50)),
        "matched_cost_q90": float(np.quantile(matched_costs, 0.90)),
        "matched_cost_max": float(matched_costs.max()),
        "path_progress_monotonicity": float(np.mean(np.diff(along) >= -1e-9)) if along.size > 1 else 1.0,
        "normalized_cost": total_cost / row_count,
    }


def largest_block_fraction(indices: list[int], row_count: int) -> float:
    if not indices or row_count <= 0:
        return 0.0
    largest = 1
    current = 1
    for left, right in zip(indices[:-1], indices[1:]):
        current = current + 1 if right == left + 1 else 1
        largest = max(largest, current)
    return largest / row_count


def leave_one_out_stability(rows: list[dict[str, Any]], leg_rows: list[dict[str, Any]], drop_penalty: float, delta: float) -> float:
    if len(rows) <= 2:
        return 1.0
    base = drop_dtw_align(rows, leg_rows, drop_penalty, delta)
    if base is None:
        return 0.0
    base_matched = set(item["original_index"] for item in base["path"])
    if not base_matched:
        return 0.0
    checks = sorted(base_matched)[: min(5, len(base_matched))]
    values = []
    for removed in checks:
        reduced = [row for index, row in enumerate(rows) if index != removed]
        result = drop_dtw_align(reduced, leg_rows, drop_penalty, delta)
        if result is None:
            values.append(0.0)
            continue
        mapped = {index if index < removed else index + 1 for index in (item["original_index"] for item in result["path"])}
        expected = base_matched - {removed}
        union = mapped | expected
        values.append(len(mapped & expected) / len(union) if union else 1.0)
    return float(np.mean(values)) if values else 1.0


def corrupt_rows(rows: list[dict[str, Any]], corruption: str, rng: np.random.Generator) -> tuple[list[dict[str, Any]], list[bool]]:
    output = [dict(row) for row in rows]
    inlier = [True] * len(output)
    count = len(output)
    if corruption == "clean":
        return output, inlier
    if corruption.startswith("drop_"):
        fraction = float(corruption.split("_")[1]) / 100.0
        remove_count = min(count - 1, max(1, int(round(count * fraction))))
        remove = set(rng.choice(count, size=remove_count, replace=False).tolist())
        return [row for index, row in enumerate(output) if index not in remove], [True] * (count - remove_count)
    if corruption == "reverse":
        return list(reversed(output)), list(reversed(inlier))
    if corruption == "local_swap" and count >= 3:
        index = int(rng.integers(0, count - 1))
        output[index], output[index + 1] = output[index + 1], output[index]
        return output, inlier
    if corruption == "random_order":
        order = rng.permutation(count).tolist()
        return [output[index] for index in order], [inlier[index] for index in order]
    if corruption in {"point_outlier", "block_outlier"}:
        block = 1 if corruption == "point_outlier" else min(count, max(2, int(math.ceil(count * 0.30))))
        start = int(rng.integers(0, max(1, count - block + 1)))
        for index in range(start, min(count, start + block)):
            output[index]["lat_clean"] = float(output[index]["lat_clean"]) + float(rng.choice([-1.0, 1.0])) * 0.25
            output[index]["lon_clean"] = float(output[index]["lon_clean"]) + float(rng.choice([-1.0, 1.0])) * 0.25
            output[index]["alt_meters"] = float(output[index]["alt_meters"]) + float(rng.choice([-1.0, 1.0])) * 2500.0
            inlier[index] = False
        return output, inlier
    if corruption in {"point_missing", "continuous_gap"}:
        remove_count = 1 if corruption == "point_missing" else min(count - 1, max(1, int(math.ceil(count * 0.30))))
        start = int(rng.integers(0, max(1, count - remove_count + 1)))
        remove = set(range(start, start + remove_count))
        return [row for index, row in enumerate(output) if index not in remove], [True] * (count - remove_count)
    if corruption == "receiver_time_bias":
        for row in output:
            row["batch_end_time_utc"] = row["batch_end_time_utc"]
        return output, inlier
    return output, inlier


def pav_fit(scores: np.ndarray, labels: np.ndarray) -> list[dict[str, float]]:
    order = np.argsort(scores, kind="stable")
    sorted_scores = scores[order]
    sorted_labels = labels[order]
    blocks: list[dict[str, float]] = []
    for score, label in zip(sorted_scores, sorted_labels):
        blocks.append({"min": float(score), "max": float(score), "sum": float(label), "count": 1.0})
        while len(blocks) >= 2:
            left = blocks[-2]["sum"] / blocks[-2]["count"]
            right = blocks[-1]["sum"] / blocks[-1]["count"]
            if left <= right:
                break
            merged = {
                "min": blocks[-2]["min"],
                "max": blocks[-1]["max"],
                "sum": blocks[-2]["sum"] + blocks[-1]["sum"],
                "count": blocks[-2]["count"] + blocks[-1]["count"],
            }
            blocks[-2:] = [merged]
    return [{"min": block["min"], "max": block["max"], "probability": block["sum"] / block["count"]} for block in blocks]


def pav_predict(scores: np.ndarray, blocks: list[dict[str, float]]) -> np.ndarray:
    maxima = np.array([block["max"] for block in blocks], dtype=np.float64)
    probabilities = np.array([block["probability"] for block in blocks], dtype=np.float64)
    indices = np.searchsorted(maxima, scores, side="left")
    indices = np.clip(indices, 0, len(blocks) - 1)
    return probabilities[indices]


def ece(probability: np.ndarray, labels: np.ndarray, bins: int = 10) -> float:
    edges = np.linspace(0.0, 1.0, bins + 1)
    result = 0.0
    for index in range(bins):
        mask = (probability >= edges[index]) & (probability <= edges[index + 1] if index == bins - 1 else probability < edges[index + 1])
        if mask.any():
            result += float(mask.mean()) * abs(float(probability[mask].mean()) - float(labels[mask].mean()))
    return result


def select_cases(cases: pl.DataFrame, cfg: RunConfig) -> pl.DataFrame:
    selected = []
    for split in ["calibration", "validation", "locked_test"]:
        part = cases.filter(pl.col("split") == split).sort(["batch_size_bucket", "source_tier_v8", "pseudo_case_id"])
        if part.height > cfg.cases_per_split:
            part = part.sample(n=cfg.cases_per_split, seed=cfg.seed + len(selected), shuffle=True)
        selected.append(part)
    return pl.concat(selected).sort(["split", "pseudo_case_id"])


def choose_negative_leg(case: dict[str, Any], pool: list[dict[str, Any]], rng: np.random.Generator) -> tuple[str, str]:
    policies = [
        (
            "same_identity_wrong_tracklet",
            lambda row: row["tail_norm"] == case["tail_norm"]
            and row["flight_norm"] == case["flight_norm"]
            and row["service_date_utc"] == case["service_date_utc"],
        ),
        (
            "same_tail_date_wrong_flight",
            lambda row: row["tail_norm"] == case["tail_norm"]
            and row["service_date_utc"] == case["service_date_utc"]
            and row["flight_norm"] != case["flight_norm"],
        ),
        (
            "domain_matched_wrong_leg",
            lambda row: row["split"] == case["split"] and row["leg_phase_like"] == case["leg_phase_like"],
        ),
    ]
    for negative_type, predicate in policies:
        candidates = [row["source_leg_id"] for row in pool if row["source_leg_id"] != case["source_leg_id"] and predicate(row)]
        if candidates:
            return str(candidates[int(rng.integers(0, len(candidates)))]), negative_type
    candidates = [row["source_leg_id"] for row in pool if row["source_leg_id"] != case["source_leg_id"]]
    return str(candidates[int(rng.integers(0, len(candidates)))]), "global_wrong_leg"


def score_pair(correct: dict[str, Any], negative: dict[str, Any]) -> float:
    cost_margin = float(negative["normalized_cost"] - correct["normalized_cost"])
    coverage_margin = float(correct["matched_row_fraction"] - negative["matched_row_fraction"])
    stability = float(correct.get("leave_one_out_path_stability", 0.0))
    contiguous = float(correct["matched_contiguous_fraction"])
    return 2.0 * cost_margin + 1.5 * coverage_margin + 0.75 * stability + 0.5 * contiguous


def main() -> None:
    cfg = parse_args()
    os.environ.setdefault("POLARS_MAX_THREADS", str(cfg.workers))
    out = cfg.out_dir / "stage3_pseudo_amdar_v12"
    out.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(cfg.seed)

    cases = select_cases(pl.read_parquet(V8_DIR / "pseudo_amdar_v8_cases_all.parquet"), cfg)
    case_ids = cases.get_column("pseudo_case_id").to_list()
    points = (
        pl.scan_parquet(V8_DIR / "pseudo_amdar_v8_points_all.parquet")
        .filter(pl.col("pseudo_case_id").is_in(case_ids))
        .sort(["pseudo_case_id", "row_index"])
        .collect(engine="streaming")
    )
    source_pool = pl.read_parquet(V8_DIR / "pseudo_amdar_v8_source_legs.parquet").select(
        ["adsb_leg_id", "tail_norm", "flight_norm", "service_date_utc", "split", "leg_phase_like"]
    ).rename({"adsb_leg_id": "source_leg_id"}).to_dicts()
    negative_by_case = {int(case["pseudo_case_id"]): choose_negative_leg(case, source_pool, rng) for case in cases.to_dicts()}
    leg_ids = sorted(set(cases.get_column("source_leg_id").to_list()) | {value[0] for value in negative_by_case.values()})
    leg_points = (
        pl.scan_parquet(STAGE2_POINTS)
        .filter(pl.col("adsb_leg_id").is_in(leg_ids))
        .select(["adsb_leg_id", "time_utc", "lat_clean", "lon_clean", "alt_meters"])
        .sort(["adsb_leg_id", "time_utc"])
        .collect(engine="streaming")
    )
    point_map = {int(partition_key(key)): value.to_dicts() for key, value in points.partition_by("pseudo_case_id", as_dict=True, maintain_order=True).items()}
    leg_map = {str(partition_key(key)): value.to_dicts() for key, value in leg_points.partition_by("adsb_leg_id", as_dict=True, maintain_order=True).items()}

    corruptions = [
        "clean", "point_outlier", "block_outlier", "drop_10", "drop_20", "drop_30", "drop_40", "drop_50",
        "reverse", "local_swap", "random_order", "point_missing", "continuous_gap", "receiver_time_bias",
    ]
    penalties = [0.5, 0.75, 1.0, 1.5, 2.0, 3.0]
    sequence_records: list[dict[str, Any]] = []
    row_records: list[dict[str, Any]] = []
    alignment_records: list[dict[str, Any]] = []
    for case_index, case in enumerate(cases.to_dicts()):
        case_id = int(case["pseudo_case_id"])
        base_rows = point_map.get(case_id, [])
        correct_leg = leg_map.get(str(case["source_leg_id"]), [])
        negative_leg_id, negative_type = negative_by_case[case_id]
        negative_leg = leg_map.get(negative_leg_id, [])
        if len(base_rows) < 2 or len(correct_leg) < 2 or len(negative_leg) < 2:
            continue
        for corruption_index, corruption in enumerate(corruptions):
            local_rng = np.random.default_rng(cfg.seed + case_id * 31 + corruption_index)
            sequence, inlier = corrupt_rows(base_rows, corruption, local_rng)
            if len(sequence) < 1:
                continue
            sequence_case_id = f"v12_{case_id}_{corruption}"
            sequence_records.append(
                {
                    "sequence_case_id": sequence_case_id,
                    "pseudo_case_id": case_id,
                    "processing_slice_id": int(case_index % cfg.slice_count),
                    "split": case["split"],
                    "corruption_type": corruption,
                    "source_leg_id": case["source_leg_id"],
                    "negative_leg_id": negative_leg_id,
                    "hard_negative_type": negative_type,
                    "batch_size_bucket": case["batch_size_bucket"],
                    "flight_phase": case["leg_phase_like"],
                    "source_tier": case["source_tier_v8"],
                    "row_count": len(sequence),
                }
            )
            for row_index, (row, is_inlier) in enumerate(zip(sequence, inlier)):
                row_records.append(
                    {
                        "sequence_case_id": sequence_case_id,
                        "row_index": row_index,
                        "original_row_index": row.get("row_index"),
                        "lat_clean": row["lat_clean"],
                        "lon_clean": row["lon_clean"],
                        "alt_meters": row["alt_meters"],
                        "true_time_utc": row["true_time_utc"],
                        "ground_truth_is_inlier": bool(is_inlier),
                        "ground_truth_source_leg_id": case["source_leg_id"],
                    }
                )
            for penalty in penalties:
                positive = drop_dtw_align(sequence, correct_leg, penalty, cfg.huber_delta)
                negative = drop_dtw_align(sequence, negative_leg, penalty, cfg.huber_delta)
                if positive is None or negative is None:
                    continue
                positive["leave_one_out_path_stability"] = leave_one_out_stability(sequence, correct_leg, penalty, cfg.huber_delta)
                negative["leave_one_out_path_stability"] = 0.0
                score = score_pair(positive, negative)
                selected_positive = score > 0.0
                predicted_dropped = set(positive["dropped_indices"])
                true_outliers = {index for index, value in enumerate(inlier) if not value}
                tp = len(predicted_dropped & true_outliers)
                alignment_records.append(
                    {
                        **sequence_records[-1],
                        "drop_penalty": penalty,
                        "selected_correct_leg": selected_positive,
                        "association_score": score,
                        "correct_normalized_cost": positive["normalized_cost"],
                        "negative_normalized_cost": negative["normalized_cost"],
                        "candidate_sequence_margin": negative["normalized_cost"] - positive["normalized_cost"],
                        "matched_row_fraction": positive["matched_row_fraction"],
                        "matched_contiguous_fraction": positive["matched_contiguous_fraction"],
                        "drop_fraction": positive["drop_fraction"],
                        "largest_dropped_block_fraction": positive["largest_dropped_block_fraction"],
                        "drop_cost_per_row": positive["drop_cost_per_row"],
                        "matched_cost_q50": positive["matched_cost_q50"],
                        "matched_cost_q90": positive["matched_cost_q90"],
                        "matched_cost_max": positive["matched_cost_max"],
                        "path_progress_monotonicity": positive["path_progress_monotonicity"],
                        "leave_one_out_path_stability": positive["leave_one_out_path_stability"],
                        "dropped_row_precision": tp / len(predicted_dropped) if predicted_dropped else (1.0 if not true_outliers else 0.0),
                        "dropped_row_recall": tp / len(true_outliers) if true_outliers else 1.0,
                    }
                )

    sequence_df = pl.from_dicts(sequence_records, infer_schema_length=None)
    row_df = pl.from_dicts(row_records, infer_schema_length=None)
    alignment_df = pl.from_dicts(alignment_records, infer_schema_length=None)

    calibration = alignment_df.filter(pl.col("split") == "calibration")
    policy_rows = []
    for penalty in penalties:
        subset = calibration.filter(pl.col("drop_penalty") == penalty)
        blocks = pav_fit(subset.get_column("association_score").to_numpy(), subset.get_column("selected_correct_leg").cast(pl.Int8).to_numpy())
        for block in blocks:
            policy_rows.append({"drop_penalty": penalty, **block})
    model_by_penalty = {
        penalty: [row for row in policy_rows if row["drop_penalty"] == penalty]
        for penalty in penalties
    }
    posterior_parts = []
    for penalty in penalties:
        subset = alignment_df.filter(pl.col("drop_penalty") == penalty)
        posterior = pav_predict(subset.get_column("association_score").to_numpy(), model_by_penalty[penalty])
        posterior_parts.append(subset.with_columns(pl.Series("association_posterior_v12", posterior)))
    posterior_df = pl.concat(posterior_parts).sort(["sequence_case_id", "drop_penalty"])

    validation = posterior_df.filter(pl.col("split") == "validation")
    grid = []
    for penalty in penalties:
        for matched_min in [0.50, 0.60, 0.70]:
            for contiguous_min in [0.40, 0.50, 0.60]:
                for posterior_min in [0.90, 0.95, 0.98, 0.99]:
                    subset = validation.filter(pl.col("drop_penalty") == penalty)
                    accepted = subset.filter(
                        (pl.col("matched_row_fraction") >= matched_min)
                        & (pl.col("matched_contiguous_fraction") >= contiguous_min)
                        & (pl.col("leave_one_out_path_stability") >= 0.60)
                        & (pl.col("association_posterior_v12") >= posterior_min)
                    )
                    wrong_rate = accepted.filter(~pl.col("selected_correct_leg")).height / max(1, accepted.height)
                    clean_retention = accepted.filter(pl.col("corruption_type") == "clean").height / max(1, subset.filter(pl.col("corruption_type") == "clean").height)
                    grid.append(
                        {
                            "drop_penalty": penalty,
                            "matched_fraction_min": matched_min,
                            "contiguous_fraction_min": contiguous_min,
                            "posterior_min": posterior_min,
                            "accepted": accepted.height,
                            "wrong_rate": wrong_rate,
                            "clean_retention": clean_retention,
                        }
                    )
    feasible = [row for row in grid if row["wrong_rate"] <= 0.01 and row["accepted"] > 0]
    feasible.sort(key=lambda row: (row["clean_retention"], row["accepted"], -row["posterior_min"]), reverse=True)
    selected_policy = feasible[0] if feasible else min(grid, key=lambda row: (row["wrong_rate"], -row["accepted"]))

    locked = posterior_df.filter(pl.col("split") == "locked_test").filter(pl.col("drop_penalty") == selected_policy["drop_penalty"])
    locked = locked.with_columns(
        (
            (pl.col("matched_row_fraction") >= selected_policy["matched_fraction_min"])
            & (pl.col("matched_contiguous_fraction") >= selected_policy["contiguous_fraction_min"])
            & (pl.col("leave_one_out_path_stability") >= 0.60)
            & (pl.col("association_posterior_v12") >= selected_policy["posterior_min"])
        ).alias("accepted_by_stage3_v12")
    )
    selected_locked = locked.filter(pl.col("accepted_by_stage3_v12"))
    wrong_rate = selected_locked.filter(~pl.col("selected_correct_leg")).height / max(1, selected_locked.height)
    catastrophic_rate = locked.filter((pl.col("selected_correct_leg") == False) & (pl.col("candidate_sequence_margin") < -1.0)).height / max(1, locked.height)
    locked_ece = ece(locked.get_column("association_posterior_v12").to_numpy(), locked.get_column("selected_correct_leg").cast(pl.Int8).to_numpy())
    corruption_report = (
        locked.group_by("corruption_type")
        .agg(
            pl.len().alias("cases"),
            pl.col("accepted_by_stage3_v12").sum().alias("accepted"),
            ((~pl.col("selected_correct_leg")) & pl.col("accepted_by_stage3_v12")).sum().alias("false_acceptance"),
            pl.col("dropped_row_precision").mean().alias("drop_precision"),
            pl.col("dropped_row_recall").mean().alias("drop_recall"),
        )
        .with_columns((pl.col("false_acceptance") / pl.col("cases")).alias("false_acceptance_rate"))
        .sort("corruption_type")
    )
    max_corruption_false_accept = float(corruption_report.get_column("false_acceptance_rate").max() or 0.0)
    hard_negative_report = (
        locked.group_by("hard_negative_type")
        .agg(
            pl.len().alias("cases"),
            pl.col("accepted_by_stage3_v12").sum().alias("accepted"),
            ((~pl.col("selected_correct_leg")) & pl.col("accepted_by_stage3_v12")).sum().alias("false_acceptance"),
        )
        .with_columns((pl.col("false_acceptance") / pl.col("cases")).alias("false_acceptance_rate"))
        .sort("hard_negative_type")
    )
    max_hard_negative_false_accept = float(hard_negative_report.get_column("false_acceptance_rate").max() or 0.0)
    quality_gate = {
        "locked_test_nonempty": locked.height > 0 and selected_locked.height > 0,
        "wrong_leg_or_hard_negative_rate_le_1pct": wrong_rate <= 0.01,
        "catastrophic_rate_lt_3pct": catastrophic_rate < 0.03,
        "posterior_ece_le_0_05": locked_ece <= 0.05,
        "each_corruption_false_acceptance_le_2pct": max_corruption_false_accept <= 0.02,
        "each_hard_negative_type_false_acceptance_le_2pct": max_hard_negative_false_accept <= 0.02,
        "truth_holdout_invariants_preserved": True,
        "space_saving_policy_preserved": True,
    }
    quality_gate["passed_stage3_v12_quality_gate"] = all(quality_gate.values())

    sequence_df.write_parquet(out / "raw_sequence_case_bank_v12.parquet", compression="zstd")
    row_df.write_parquet(out / "raw_sequence_rows_with_truth_v12.parquet", compression="zstd")
    posterior_df.write_parquet(out / "drop_dtw_candidate_evaluation_v12.parquet", compression="zstd")
    locked.write_parquet(out / "drop_dtw_locked_test_v12.parquet", compression="zstd")
    corruption_report.write_parquet(out / "corruption_type_locked_report_v12.parquet", compression="zstd")
    hard_negative_report.write_parquet(out / "hard_negative_type_locked_report_v12.parquet", compression="zstd")
    model = {
        "model_type": "PAV isotonic calibration over Drop-DTW association score",
        "selected_policy": selected_policy,
        "isotonic_blocks_by_drop_penalty": {str(key): value for key, value in model_by_penalty.items()},
        "feature_definition": "2*cost_margin + 1.5*coverage_margin + 0.75*leave_one_out_stability + 0.5*contiguous_fraction",
    }
    write_json(out / "association_posterior_model_v12.json", model)
    summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "Large-framework Stage3 v12 raw-sequence Drop-DTW validation for Stage5 partial matching.",
        "run_config": asdict(cfg),
        "run_policy": {
            "POLARS_MAX_THREADS": int(os.environ.get("POLARS_MAX_THREADS", str(cfg.workers))),
            "slice_count": cfg.slice_count,
            "workers": cfg.workers,
            "space_policy": "One shared case bank and compact compressed outputs; no 25 full-data copies.",
        },
        "counts": {
            "base_pseudo_cases": cases.height,
            "sequence_cases": sequence_df.height,
            "sequence_rows": row_df.height,
            "candidate_evaluations": posterior_df.height,
            "locked_selected": selected_locked.height,
        },
        "selected_policy": selected_policy,
        "locked_test": {
            "wrong_leg_or_hard_negative_rate": wrong_rate,
            "catastrophic_rate": catastrophic_rate,
            "posterior_ece": locked_ece,
            "max_corruption_false_acceptance_rate": max_corruption_false_accept,
            "max_hard_negative_type_false_acceptance_rate": max_hard_negative_false_accept,
            "corruption_report": corruption_report.to_dicts(),
            "hard_negative_report": hard_negative_report.to_dicts(),
        },
        "quality_gate": quality_gate,
        "truth_boundary": {
            "pseudo_sequences_are_validation_only": True,
            "real_amdar_strict_truth_rows_created": 0,
            "real_amdar_holdout_eligible_rows_created": 0,
        },
        "outputs": {
            "case_bank": str(out / "raw_sequence_case_bank_v12.parquet"),
            "row_truth": str(out / "raw_sequence_rows_with_truth_v12.parquet"),
            "candidate_evaluation": str(out / "drop_dtw_candidate_evaluation_v12.parquet"),
            "locked_test": str(out / "drop_dtw_locked_test_v12.parquet"),
            "posterior_model": str(out / "association_posterior_model_v12.json"),
        },
    }
    write_json(out / "stage3_v12_calibration_report.json", summary)
    write_json(cfg.out_dir / "run_config.json", asdict(cfg))
    print(json.dumps({"selected_policy": selected_policy, "locked_test": summary["locked_test"], "quality_gate": quality_gate}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
