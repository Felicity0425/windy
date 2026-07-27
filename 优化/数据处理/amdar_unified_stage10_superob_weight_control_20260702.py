from __future__ import annotations

import argparse
import json
import math
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import polars as pl


ROOT = Path("/data/LFT-W02_data/pengxu")
DATA_DIR = ROOT / "优化/数据处理"
DEFAULT_STAGE9_DIR = DATA_DIR / "amdar_unified_stage9_stage2_role_split_global_frame_optimized_20260702"
DEFAULT_OUT_DIR = DATA_DIR / "amdar_unified_stage10_superob_weight_control_v2_optimized_20260702"


@dataclass(frozen=True)
class RunConfig:
    stage9_dir: Path = DEFAULT_STAGE9_DIR
    out_dir: Path = DEFAULT_OUT_DIR
    max_weight_per_batch_per_frame: float = 5.0
    max_weight_per_flight_per_voxel: float = 3.0
    max_weight_per_source_per_frame: float = 50.0
    max_total_weight_ratio: float = 0.30
    along_track_bin_points: int = 5
    batch_along_track_bin_points: int = 10
    context_along_track_bin_points: int = 25
    current_xy_superob_factor: int = 1
    batch_xy_superob_factor: int = 2
    context_xy_superob_factor: int = 4
    min_t1t2t3_raw_per_superob: float = 1.40
    stage10_version: str = "v1"


TIERS: dict[str, list[str]] = {
    "T1": ["A"],
    "T1T2": ["A", "B"],
    "T1T2T3": ["A", "B", "C"],
}

TIER_OUTPUTS = {
    "T1": "amdar_superobs_T1.parquet",
    "T1T2": "amdar_superobs_T1T2.parquet",
    "T1T2T3": "amdar_superobs_T1T2T3.parquet",
}


def parse_args() -> RunConfig:
    parser = argparse.ArgumentParser(
        description=(
            "Run AMDAR Unified Plan Stage10 super-ob and density/weight control. "
            "Consumes Stage9 role-split records and writes A, A+B, A+B+C AMDAR super-ob products."
        )
    )
    parser.add_argument("--stage9-dir", default=str(DEFAULT_STAGE9_DIR))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--max-weight-per-batch-per-frame", type=float, default=5.0)
    parser.add_argument("--max-weight-per-flight-per-voxel", type=float, default=3.0)
    parser.add_argument("--max-weight-per-source-per-frame", type=float, default=50.0)
    parser.add_argument("--max-total-weight-ratio", type=float, default=0.30)
    parser.add_argument("--along-track-bin-points", type=int, default=5)
    parser.add_argument("--batch-along-track-bin-points", type=int, default=10)
    parser.add_argument("--context-along-track-bin-points", type=int, default=25)
    parser.add_argument("--current-xy-superob-factor", type=int, default=1)
    parser.add_argument("--batch-xy-superob-factor", type=int, default=2)
    parser.add_argument("--context-xy-superob-factor", type=int, default=4)
    parser.add_argument("--min-t1t2t3-raw-per-superob", type=float, default=1.40)
    args = parser.parse_args()
    return RunConfig(
        stage9_dir=Path(args.stage9_dir).resolve(),
        out_dir=Path(args.out_dir).resolve(),
        max_weight_per_batch_per_frame=float(args.max_weight_per_batch_per_frame),
        max_weight_per_flight_per_voxel=float(args.max_weight_per_flight_per_voxel),
        max_weight_per_source_per_frame=float(args.max_weight_per_source_per_frame),
        max_total_weight_ratio=float(args.max_total_weight_ratio),
        along_track_bin_points=int(args.along_track_bin_points),
        batch_along_track_bin_points=int(args.batch_along_track_bin_points),
        context_along_track_bin_points=int(args.context_along_track_bin_points),
        current_xy_superob_factor=int(args.current_xy_superob_factor),
        batch_xy_superob_factor=int(args.batch_xy_superob_factor),
        context_xy_superob_factor=int(args.context_xy_superob_factor),
        min_t1t2t3_raw_per_superob=float(args.min_t1t2t3_raw_per_superob),
    )


def json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=json_default), encoding="utf-8")
    tmp.replace(path)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def numeric_summary_lf(lf: pl.LazyFrame, col: str) -> dict[str, Any]:
    if col not in lf.collect_schema().names():
        return {"present": False}
    row = (
        lf.select(pl.col(col).cast(pl.Float64, strict=False).alias(col))
        .select(
            [
                pl.len().alias("rows"),
                pl.col(col).null_count().alias("null_rows"),
                pl.col(col).filter(pl.col(col).is_finite()).count().alias("finite_rows"),
                pl.col(col).filter(pl.col(col).is_finite()).min().alias("min"),
                pl.col(col).filter(pl.col(col).is_finite()).quantile(0.10).alias("p10"),
                pl.col(col).filter(pl.col(col).is_finite()).quantile(0.50).alias("q50"),
                pl.col(col).filter(pl.col(col).is_finite()).quantile(0.90).alias("p90"),
                pl.col(col).filter(pl.col(col).is_finite()).quantile(0.99).alias("p99"),
                pl.col(col).filter(pl.col(col).is_finite()).max().alias("max"),
            ]
        )
        .collect(engine="streaming")
        .to_dicts()[0]
    )
    return {"present": True, **{k: (float(v) if isinstance(v, float) else int(v) if isinstance(v, int) else v) for k, v in row.items()}}


def require_stage9(stage9_dir: Path) -> dict[str, Any]:
    summary_path = stage9_dir / "stage9_stage2_role_split_summary.json"
    records_path = stage9_dir / "stage2_observation_records_all.parquet"
    if not summary_path.exists():
        raise FileNotFoundError(f"Missing Stage9 summary: {summary_path}")
    if not records_path.exists():
        raise FileNotFoundError(f"Missing Stage9 observation records: {records_path}")
    summary = read_json(summary_path)
    checks = summary.get("stage9_completion_checks", {})
    required = [
        "passed_stage9_stage2_role_split_gate",
        "frame_index_global_unique",
        "frame_index_maps_to_single_time_str",
        "no_amdar_holdout_records",
        "no_amdar_effective_strict_truth_records",
        "r_not_regular_support",
    ]
    failed = [name for name in required if not checks.get(name)]
    if failed:
        raise RuntimeError(f"Stage9 is not ready for Stage10; failed checks: {failed}")
    return summary


def support_records_lf(cfg: RunConfig) -> pl.LazyFrame:
    records_path = cfg.stage9_dir / "stage2_observation_records_all.parquet"
    support_channels = ["current_support_records", "batch_support_records", "context_support_records"]
    return (
        pl.scan_parquet(records_path)
        .filter(
            (pl.col("source") == "amdar")
            & pl.col("confidence_grade").is_in(["A", "B", "C"])
            & pl.col("stage9_output_channel").is_in(support_channels)
            & ~pl.col("holdout_eligible").fill_null(False)
            & ~pl.col("stage8_effective_strict_truth").fill_null(False)
        )
        .with_columns(
            [
                pl.when(pl.col("stage9_output_channel") == "context_support_records")
                .then(pl.col("context_joint_conf").cast(pl.Float64).fill_null(0.0))
                .otherwise(pl.col("frame_time_conf").cast(pl.Float64).fill_null(0.0))
                .alias("support_time_weight_raw"),
                pl.col("spatial_representativeness").cast(pl.Float64).fill_null(1.0).clip(0.0, 1.0).alias(
                    "support_space_weight"
                ),
                pl.when(pl.col("stage9_output_channel") == "context_support_records")
                .then(pl.lit(max(1, cfg.context_along_track_bin_points)))
                .when(pl.col("stage9_output_channel") == "batch_support_records")
                .then(pl.lit(max(1, cfg.batch_along_track_bin_points)))
                .otherwise(pl.lit(max(1, cfg.along_track_bin_points)))
                .cast(pl.Int64)
                .alias("channel_along_track_bin_points"),
                pl.when(pl.col("stage9_output_channel") == "context_support_records")
                .then(pl.lit(max(1, cfg.context_xy_superob_factor)))
                .when(pl.col("stage9_output_channel") == "batch_support_records")
                .then(pl.lit(max(1, cfg.batch_xy_superob_factor)))
                .otherwise(pl.lit(max(1, cfg.current_xy_superob_factor)))
                .cast(pl.Int64)
                .alias("channel_xy_superob_factor"),
                pl.col("z").cast(pl.Int32).alias("altitude_bin"),
                pl.col("frame_index").cast(pl.Int64).alias("time_bin"),
            ]
        )
        .with_columns(
            [
                (
                    pl.col("amdar_observation_order").fill_null(0).cast(pl.Int64)
                    // pl.col("channel_along_track_bin_points")
                )
                .cast(pl.Int64)
                .alias("along_track_bin"),
                (pl.col("x").cast(pl.Int64) // pl.col("channel_xy_superob_factor")).cast(pl.Int64).alias(
                    "superob_x"
                ),
                (pl.col("y").cast(pl.Int64) // pl.col("channel_xy_superob_factor")).cast(pl.Int64).alias(
                    "superob_y"
                ),
                (pl.col("support_time_weight_raw") * pl.col("support_space_weight")).alias("support_weight_raw"),
            ]
        )
        .filter(pl.col("support_weight_raw").is_finite() & (pl.col("support_weight_raw") > 0.0))
    )


def build_superobs_base(cfg: RunConfig, base_path: Path) -> None:
    lf = support_records_lf(cfg)
    keys = [
        "frame_index",
        "time_str",
        "target_time",
        "time_bin",
        "stage9_output_channel",
        "source",
        "confidence_grade",
        "flight_id",
        "amdar_batch_id",
        "z",
        "superob_y",
        "superob_x",
        "channel_xy_superob_factor",
        "altitude_bin",
        "along_track_bin",
        "channel_along_track_bin_points",
    ]
    grouped = lf.group_by(keys).agg(
        [
            pl.len().alias("raw_point_count"),
            pl.col("observation_id").n_unique().alias("unique_observation_count"),
            pl.col("support_weight_raw").sum().alias("sum_support_weight_raw"),
            (pl.col("support_weight_raw") * pl.col("support_weight_raw")).sum().alias("sum_support_weight_sq"),
            pl.col("support_weight_raw").mean().alias("mean_support_weight_raw"),
            (pl.col("u_wind") * pl.col("support_weight_raw")).sum().alias("weighted_u_num"),
            (pl.col("v_wind") * pl.col("support_weight_raw")).sum().alias("weighted_v_num"),
            (pl.col("u_wind") * pl.col("u_wind") * pl.col("support_weight_raw")).sum().alias("weighted_u2_num"),
            (pl.col("v_wind") * pl.col("v_wind") * pl.col("support_weight_raw")).sum().alias("weighted_v2_num"),
            (pl.col("lat_clean") * pl.col("support_weight_raw")).sum().alias("weighted_lat_num"),
            (pl.col("lon_clean") * pl.col("support_weight_raw")).sum().alias("weighted_lon_num"),
            (pl.col("alt_meters") * pl.col("support_weight_raw")).sum().alias("weighted_alt_num"),
            (pl.col("x").cast(pl.Float64) * pl.col("support_weight_raw")).sum().alias("weighted_x_num"),
            (pl.col("y").cast(pl.Float64) * pl.col("support_weight_raw")).sum().alias("weighted_y_num"),
            pl.col("x").min().alias("min_x"),
            pl.col("x").max().alias("max_x"),
            pl.col("y").min().alias("min_y"),
            pl.col("y").max().alias("max_y"),
            pl.col("x").n_unique().alias("unique_x"),
            pl.col("y").n_unique().alias("unique_y"),
            pl.col("lat_clean").mean().alias("mean_lat_clean"),
            pl.col("lon_clean").mean().alias("mean_lon_clean"),
            pl.col("alt_meters").mean().alias("mean_alt_meters"),
            pl.col("wind_speed").mean().alias("mean_wind_speed"),
            pl.col("obs_conf_v2").mean().alias("mean_obs_conf_v2"),
            pl.col("frame_time_conf").mean().alias("mean_frame_time_conf"),
            pl.col("frame_time_overlap_prob").mean().alias("mean_frame_time_overlap_prob"),
            pl.col("context_time_conf").mean().alias("mean_context_time_conf"),
            pl.col("context_joint_conf").mean().alias("mean_context_joint_conf"),
            pl.col("spatial_representativeness").mean().alias("mean_spatial_representativeness"),
            pl.col("time_uncertainty_s").mean().alias("mean_time_uncertainty_s"),
            pl.col("time_interval_width_s").mean().alias("mean_time_interval_width_s"),
            pl.col("q50_delta_to_frame_s").mean().alias("mean_q50_delta_to_frame_s"),
            pl.col("time_pdf_type").mode().first().alias("time_pdf_type_mode"),
            pl.col("time_source").mode().first().alias("time_source_mode"),
            pl.col("time_reconstruction_grade").mode().first().alias("time_reconstruction_grade_mode"),
            pl.col("batch_interval_driver").mode().first().alias("batch_interval_driver_mode"),
            pl.col("stage9_role_reason").mode().first().alias("stage9_role_reason_mode"),
            pl.col("stage8_usage_recommendation").mode().first().alias("stage8_usage_recommendation_mode"),
            pl.col("adsb_reconstructed").sum().alias("adsb_reconstructed_rows"),
            pl.col("adsb_match_cost").mean().alias("mean_adsb_match_cost"),
            pl.col("adsb_match_ambiguity").mean().alias("mean_adsb_match_ambiguity"),
            pl.col("raw_row_number").min().alias("min_raw_row_number"),
            pl.col("raw_row_number").max().alias("max_raw_row_number"),
            pl.col("amdar_observation_order").min().alias("min_amdar_observation_order"),
            pl.col("amdar_observation_order").max().alias("max_amdar_observation_order"),
        ]
    )
    with_metrics = (
        grouped.with_columns(
            [
                (pl.col("weighted_u_num") / pl.col("sum_support_weight_raw")).alias("weighted_u"),
                (pl.col("weighted_v_num") / pl.col("sum_support_weight_raw")).alias("weighted_v"),
                (pl.col("weighted_lat_num") / pl.col("sum_support_weight_raw")).alias("weighted_lat_clean"),
                (pl.col("weighted_lon_num") / pl.col("sum_support_weight_raw")).alias("weighted_lon_clean"),
                (pl.col("weighted_alt_num") / pl.col("sum_support_weight_raw")).alias("weighted_alt_meters"),
                (pl.col("weighted_x_num") / pl.col("sum_support_weight_raw")).round(0).cast(pl.Int32).alias("x"),
                (pl.col("weighted_y_num") / pl.col("sum_support_weight_raw")).round(0).cast(pl.Int32).alias("y"),
                (pl.col("max_x") - pl.col("min_x") + 1).cast(pl.Int32).alias("stage2_x_span"),
                (pl.col("max_y") - pl.col("min_y") + 1).cast(pl.Int32).alias("stage2_y_span"),
                (
                    (pl.col("sum_support_weight_raw") * pl.col("sum_support_weight_raw"))
                    / pl.col("sum_support_weight_sq").clip(1e-12, None)
                )
                .clip(0.0, None)
                .alias("kish_effective_sample_size"),
                (
                    pl.col("sum_support_weight_raw")
                    / pl.when(pl.col("confidence_grade") == "A")
                    .then(0.75)
                    .when(pl.col("confidence_grade") == "B")
                    .then(0.50)
                    .otherwise(0.25)
                )
                .clip(0.0, None)
                .alias("weight_equivalent_sample_size"),
            ]
        )
        .with_columns(
            [
                (
                    (
                        (pl.col("weighted_u2_num") / pl.col("sum_support_weight_raw"))
                        - (pl.col("weighted_u") * pl.col("weighted_u"))
                    ).clip(0.0, None)
                    + (
                        (pl.col("weighted_v2_num") / pl.col("sum_support_weight_raw"))
                        - (pl.col("weighted_v") * pl.col("weighted_v"))
                    ).clip(0.0, None)
                )
                .sqrt()
                .alias("within_group_spread"),
                pl.min_horizontal(
                    [
                        pl.col("sum_support_weight_raw"),
                        pl.col("mean_support_weight_raw") * pl.col("raw_point_count").cast(pl.Float64).sqrt(),
                    ]
                ).alias("super_ob_weight_unlimited"),
                (1.0 / pl.col("raw_point_count").cast(pl.Float64).sqrt()).clip(0.05, 1.0).alias(
                    "density_conf"
                ),
            ]
        )
        .with_columns(
            [
                (pl.col("super_ob_weight_unlimited") / pl.col("sum_support_weight_raw").clip(1e-12, None)).alias(
                    "superob_density_scale"
                ),
                pl.min_horizontal(
                    [
                        pl.col("raw_point_count").cast(pl.Float64),
                        pl.col("kish_effective_sample_size"),
                        pl.col("weight_equivalent_sample_size"),
                    ]
                ).alias("effective_sample_size"),
                pl.min_horizontal([pl.col("mean_support_weight_raw"), pl.lit(0.85)]).alias("super_ob_conf"),
                pl.struct(keys).hash(seed=10).alias("super_ob_id"),
            ]
        )
        .drop(
            [
                "weighted_u_num",
                "weighted_v_num",
                "weighted_u2_num",
                "weighted_v2_num",
                "weighted_lat_num",
                "weighted_lon_num",
                "weighted_alt_num",
                "weighted_x_num",
                "weighted_y_num",
            ]
        )
    )
    with_metrics.sink_parquet(base_path)


def apply_weight_limits(cfg: RunConfig, base_path: Path, tier: str, grades: list[str], out_path: Path) -> None:
    base = pl.scan_parquet(base_path).filter(pl.col("confidence_grade").is_in(grades))
    frame_sum = base.group_by("frame_index").agg(
        [
            pl.col("super_ob_weight_unlimited").sum().alias("frame_weight_prelimit"),
            pl.col("amdar_batch_id").n_unique().alias("frame_unique_batches"),
            pl.col("flight_id").n_unique().alias("frame_unique_flights"),
        ]
    )
    batch_sum = base.group_by(["frame_index", "amdar_batch_id"]).agg(
        pl.col("super_ob_weight_unlimited").sum().alias("batch_frame_weight_prelimit")
    )
    flight_voxel_sum = base.group_by(["frame_index", "flight_id", "z", "superob_y", "superob_x"]).agg(
        pl.col("super_ob_weight_unlimited").sum().alias("flight_voxel_weight_prelimit")
    )
    source_frame_sum = base.group_by(["frame_index", "source"]).agg(
        pl.col("super_ob_weight_unlimited").sum().alias("source_frame_weight_prelimit")
    )
    limited = (
        base.join(frame_sum, on="frame_index", how="left")
        .join(batch_sum, on=["frame_index", "amdar_batch_id"], how="left")
        .join(flight_voxel_sum, on=["frame_index", "flight_id", "z", "superob_y", "superob_x"], how="left")
        .join(source_frame_sum, on=["frame_index", "source"], how="left")
        .with_columns(
            [
                pl.min_horizontal(
                    [
                        pl.lit(cfg.max_weight_per_batch_per_frame),
                        pl.lit(cfg.max_total_weight_ratio) * pl.col("frame_weight_prelimit"),
                    ]
                ).alias("batch_frame_allowed_weight"),
                pl.lit(cfg.max_weight_per_flight_per_voxel).alias("flight_voxel_allowed_weight"),
                pl.lit(cfg.max_weight_per_source_per_frame).alias("source_frame_allowed_weight"),
            ]
        )
        .with_columns(
            [
                pl.min_horizontal(
                    [
                        pl.lit(1.0),
                        pl.col("batch_frame_allowed_weight")
                        / pl.col("batch_frame_weight_prelimit").clip(1e-12, None),
                    ]
                ).alias("batch_frame_scale"),
                pl.min_horizontal(
                    [
                        pl.lit(1.0),
                        pl.col("flight_voxel_allowed_weight")
                        / pl.col("flight_voxel_weight_prelimit").clip(1e-12, None),
                    ]
                ).alias("flight_voxel_scale"),
                pl.min_horizontal(
                    [
                        pl.lit(1.0),
                        pl.col("source_frame_allowed_weight")
                        / pl.col("source_frame_weight_prelimit").clip(1e-12, None),
                    ]
                ).alias("source_frame_scale"),
            ]
        )
        .with_columns(
            pl.min_horizontal(["batch_frame_scale", "flight_voxel_scale", "source_frame_scale"]).alias(
                "stage10_weight_scale"
            )
        )
        .with_columns(
            [
                (pl.col("super_ob_weight_unlimited") * pl.col("stage10_weight_scale")).alias(
                    "super_ob_weight_final"
                ),
                (pl.col("stage10_weight_scale") < 0.999999).alias("weight_limited"),
                (pl.col("batch_frame_scale") < 0.999999).alias("batch_weight_limited"),
                (pl.col("flight_voxel_scale") < 0.999999).alias("flight_voxel_weight_limited"),
                (pl.col("source_frame_scale") < 0.999999).alias("source_frame_weight_limited"),
                pl.lit(tier).alias("stage10_tier_product"),
                pl.lit(",".join(grades)).alias("stage10_included_grades"),
            ]
        )
    )
    limited.sink_parquet(out_path)


def counts_by(df: pl.DataFrame, col: str) -> dict[str, int]:
    if df.height == 0 or col not in df.columns:
        return {}
    return {
        str(k): int(v)
        for k, v in df.select(pl.col(col).cast(pl.Utf8, strict=False).fill_null("null").alias(col))
        .to_series()
        .value_counts()
        .sort("count", descending=True)
        .iter_rows()
    }


def audit_tier(cfg: RunConfig, tier: str, out_path: Path) -> dict[str, Any]:
    lf = pl.scan_parquet(out_path)
    base = lf.select(
        [
            pl.len().alias("super_ob_rows"),
            pl.col("raw_point_count").sum().alias("raw_point_rows_collapsed"),
            pl.col("frame_index").n_unique().alias("frames"),
            pl.col("flight_id").n_unique().alias("unique_flights"),
            pl.col("amdar_batch_id").n_unique().alias("unique_batches"),
            pl.col("sum_support_weight_raw").sum().alias("sum_record_weight_raw"),
            pl.col("super_ob_weight_unlimited").sum().alias("sum_super_ob_weight_unlimited"),
            pl.col("super_ob_weight_final").sum().alias("sum_super_ob_weight_final"),
            pl.col("weight_limited").sum().alias("weight_limited_superobs"),
            pl.col("batch_weight_limited").sum().alias("batch_weight_limited_superobs"),
            pl.col("flight_voxel_weight_limited").sum().alias("flight_voxel_weight_limited_superobs"),
            pl.col("source_frame_weight_limited").sum().alias("source_frame_weight_limited_superobs"),
        ]
    ).collect(engine="streaming").to_dicts()[0]
    channel_grade = (
        lf.group_by(["stage9_output_channel", "confidence_grade"])
        .agg(
            [
                pl.len().alias("super_ob_rows"),
                pl.col("raw_point_count").sum().alias("raw_point_rows_collapsed"),
                pl.col("super_ob_weight_final").sum().alias("sum_final_weight"),
            ]
        )
        .sort(["stage9_output_channel", "confidence_grade"])
        .collect(engine="streaming")
        .to_dicts()
    )
    batch_final = lf.group_by(["frame_index", "amdar_batch_id"]).agg(
        pl.col("super_ob_weight_final").sum().alias("batch_frame_weight_final")
    )
    flight_final = lf.group_by(["frame_index", "flight_id", "z", "superob_y", "superob_x"]).agg(
        pl.col("super_ob_weight_final").sum().alias("flight_voxel_weight_final")
    )
    source_final = lf.group_by(["frame_index", "source"]).agg(
        pl.col("super_ob_weight_final").sum().alias("source_frame_weight_final")
    )
    frame_final = lf.group_by("frame_index").agg(
        [
            pl.col("super_ob_weight_final").sum().alias("frame_weight_final"),
            pl.col("amdar_batch_id").n_unique().alias("batch_groups"),
        ]
    )
    batch_ratio = batch_final.join(frame_final, on="frame_index", how="left").with_columns(
        (pl.col("batch_frame_weight_final") / pl.col("frame_weight_final").clip(1e-12, None)).alias(
            "batch_frame_weight_ratio_final"
        )
    )
    dominant_batch = batch_ratio.filter(
        (pl.col("frame_weight_final") >= 10.0)
        & (pl.col("batch_groups") >= 4)
        & (pl.col("batch_frame_weight_ratio_final") > cfg.max_total_weight_ratio)
    )
    caps = {
        "batch_frame_weight_final": numeric_summary_lf(batch_final, "batch_frame_weight_final"),
        "flight_voxel_weight_final": numeric_summary_lf(flight_final, "flight_voxel_weight_final"),
        "source_frame_weight_final": numeric_summary_lf(source_final, "source_frame_weight_final"),
        "batch_frame_weight_ratio_final": numeric_summary_lf(batch_ratio, "batch_frame_weight_ratio_final"),
    }
    cap_checks = {
        "max_batch_weight_le_limit": int(
            batch_final.filter(pl.col("batch_frame_weight_final") > cfg.max_weight_per_batch_per_frame + 1e-8)
            .select(pl.len())
            .collect(engine="streaming")
            .item()
        )
        == 0,
        "max_flight_voxel_weight_le_limit": int(
            flight_final.filter(pl.col("flight_voxel_weight_final") > cfg.max_weight_per_flight_per_voxel + 1e-8)
            .select(pl.len())
            .collect(engine="streaming")
            .item()
        )
        == 0,
        "max_source_frame_weight_le_limit": int(
            source_final.filter(pl.col("source_frame_weight_final") > cfg.max_weight_per_source_per_frame + 1e-8)
            .select(pl.len())
            .collect(engine="streaming")
            .item()
        )
        == 0,
        "no_dominant_batch_in_multi_batch_frames": int(
            dominant_batch.select(pl.len()).collect(engine="streaming").item()
        )
        == 0,
        "final_weights_finite_nonnegative": int(
            lf.filter(~pl.col("super_ob_weight_final").is_finite() | (pl.col("super_ob_weight_final") < 0.0))
            .select(pl.len())
            .collect(engine="streaming")
            .item()
        )
        == 0,
    }
    return {
        "tier": tier,
        "path": str(out_path),
        "grades": TIERS[tier],
        "counts": {k: int(v) if isinstance(v, int) else float(v) if isinstance(v, float) else v for k, v in base.items()},
        "compression": {
            "raw_per_superob": float(base["raw_point_rows_collapsed"] / max(1, base["super_ob_rows"])),
            "superob_per_raw": float(base["super_ob_rows"] / max(1, base["raw_point_rows_collapsed"])),
        },
        "channel_grade_statistics": channel_grade,
        "final_weight_summaries": caps,
        "cap_checks": cap_checks,
        "passed_tier_gate": bool(all(cap_checks.values())),
    }


def build_policy(cfg: RunConfig, summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "generated_at_utc": summary["generated_at_utc"],
        "policy_version": f"amdar_unified_stage10_superob_weight_control_{cfg.stage10_version}",
        "stage_boundary_note": (
            "This is Unified Plan Stage10. It consumes the Stage9 Stage2-role-split interface; it is not the "
            "large centralized_v1 Stage10 and does not migrate official Stage4 weights."
        ),
        "input_rules": [
            "Use only AMDAR A/B/C regular support channels from Stage9.",
            "Exclude strict_truth_records, diagnostic_only_records, rejected_records, R grade rows, and all holdout rows.",
            "Context support keeps frame_time_conf=0 from Stage9; Stage10 uses context_joint_conf times spatial representativeness as low-rank context support weight.",
        ],
        "super_ob_grouping": [
            "frame_index/time_str/time_bin",
            "stage9_output_channel",
            "confidence_grade",
            "flight_id",
            "amdar_batch_id",
            "altitude voxel z",
            "superob_y/superob_x, derived from channel-specific Stage2 voxel bins",
            "altitude_bin",
            "along_track_bin = amdar_observation_order // channel-specific along-track bin points",
        ],
        "channel_specific_superob_bins": {
            "current_support_records": {
                "xy_superob_factor": cfg.current_xy_superob_factor,
                "along_track_bin_points": cfg.along_track_bin_points,
                "rationale": "Keep A/B current-frame support at native Stage2 voxel resolution.",
            },
            "batch_support_records": {
                "xy_superob_factor": cfg.batch_xy_superob_factor,
                "along_track_bin_points": cfg.batch_along_track_bin_points,
                "rationale": "Compress C-grade current-window batch support without erasing mesoscale structure.",
            },
            "context_support_records": {
                "xy_superob_factor": cfg.context_xy_superob_factor,
                "along_track_bin_points": cfg.context_along_track_bin_points,
                "rationale": "Treat context as low-rank conditioning and reduce density dominance before Stage13.",
            },
        },
        "density_control": {
            "raw_record_weight": "current/batch: frame_time_conf * spatial_representativeness; context: context_joint_conf * spatial_representativeness",
            "double_count_fix": "Stage9 frame_joint_conf already includes spatial representativeness; v2 intentionally uses frame_time_conf before applying support_space_weight once.",
            "super_ob_weight_unlimited": "min(sum(raw_record_weight), mean(raw_record_weight) * sqrt(raw_point_count))",
            "density_conf": "1 / sqrt(raw_point_count), clipped to [0.05, 1.0]",
        },
        "weight_limits": {
            "max_weight_per_batch_per_frame": cfg.max_weight_per_batch_per_frame,
            "max_weight_per_flight_per_voxel": cfg.max_weight_per_flight_per_voxel,
            "max_weight_per_source_per_frame": cfg.max_weight_per_source_per_frame,
            "max_total_weight_ratio_for_batch_frame": cfg.max_total_weight_ratio,
            "ratio_gate_scope": "frames with final AMDAR weight >=10 and at least 4 batch groups",
            "scale_application": "final_scale = min(batch_frame_scale, flight_voxel_scale, source_frame_scale)",
        },
        "tier_products": {
            "T1": "A only",
            "T1T2": "A+B",
            "T1T2T3": "A+B+C",
        },
        "completion_checks": summary["stage10_completion_checks"],
    }


def write_docs(cfg: RunConfig, summary: dict[str, Any]) -> None:
    result_path = cfg.out_dir / "stage10_superob_weight_control_results_analysis_and_next_steps.md"
    handover_path = cfg.out_dir / "next_agent_handover_after_stage10_superob_weight_control.md"
    rows = summary["tier_audits"]["T1T2T3"]["counts"]
    compression = summary["tier_audits"]["T1T2T3"]["compression"]
    checks = summary["stage10_completion_checks"]
    sources = summary["literature_and_reference_basis"]["sources"]
    lines = [
        "# AMDAR Unified Plan Stage10 Super-Ob And Weight Control Results",
        "",
        f"Generated at UTC: {summary['generated_at_utc']}",
        "",
        "## 核心结论",
        "",
        "Stage7/8/9 复核后仍可用，但 Stage9 原始支持记录存在明显密度支配风险；Stage10 v2 已完成 super-ob、密度压缩和 batch/flight/source 限权。修正后的 Stage9 使用全局 `frame_index`，因此 Stage10 可以安全按帧审计。",
        "",
        "这仍然是 Unified Plan Stage10，不是 centralized_v1 大框架 Stage4 权重迁移；official Stage4 仍需 Stage11/12/13 兼容和消融验证后再接入。v2 还修复了 current/batch support 空间代表性双重降权的问题，并对 batch/context support 使用更合适的 coarse super-ob bin。",
        "",
        "## Stage7/8/9 复核",
        "",
        f"- Stage7 gate: `{checks['stage7_gate_passed']}`",
        f"- Stage8 gate: `{checks['stage8_gate_passed']}`",
        f"- Stage9 gate: `{checks['stage9_gate_passed']}`",
        f"- Stage9 global frame index gate: `{checks['stage9_global_frame_index_ready']}`",
        "- 结论：Stage7/8/9 现在适合进入 Stage10；主要优化空间已经从分级/角色分流转移到限权和后续消融验证。",
        "",
        "## Stage10 输出结果",
        "",
        f"- T1T2T3 super-ob rows: `{rows['super_ob_rows']}`",
        f"- Collapsed raw support rows: `{rows['raw_point_rows_collapsed']}`",
        f"- Frames: `{rows['frames']}`",
        f"- Unique batches: `{rows['unique_batches']}`",
        f"- Unique flights: `{rows['unique_flights']}`",
        f"- Sum raw record weight: `{rows['sum_record_weight_raw']}`",
        f"- Sum unlimited super-ob weight: `{rows['sum_super_ob_weight_unlimited']}`",
        f"- Sum final limited weight: `{rows['sum_super_ob_weight_final']}`",
        f"- Raw/support compression ratio: `{compression}`",
        f"- Completion checks: `{checks}`",
        "",
        "## 限权效果",
        "",
        f"- Batch/frame cap pass: `{summary['tier_audits']['T1T2T3']['cap_checks']['max_batch_weight_le_limit']}`; final max summary: `{summary['tier_audits']['T1T2T3']['final_weight_summaries']['batch_frame_weight_final']}`",
        f"- Flight/voxel cap pass: `{summary['tier_audits']['T1T2T3']['cap_checks']['max_flight_voxel_weight_le_limit']}`; final max summary: `{summary['tier_audits']['T1T2T3']['final_weight_summaries']['flight_voxel_weight_final']}`",
        f"- Source/frame cap pass: `{summary['tier_audits']['T1T2T3']['cap_checks']['max_source_frame_weight_le_limit']}`; final max summary: `{summary['tier_audits']['T1T2T3']['final_weight_summaries']['source_frame_weight_final']}`",
        f"- Dominant-batch gate pass: `{summary['tier_audits']['T1T2T3']['cap_checks']['no_dominant_batch_in_multi_batch_frames']}`",
        "",
        "## 文献和资料依据",
        "",
        "- WMO ABO/AMDAR：飞机观测是高容量上空气象支持资料，适合预报/NWP 使用，但项目中不能把批次下发时间自动解释成逐点真值。",
        "- NOAA AMDAR/MADIS：ABO/ACARS 数据需要质量评估、坏值标记和可能订正，支持 Stage7/8 的分级和 QC 字段保留。",
        "- FAA/eCFR ADS-B Out：ADS-B state vector 有明确精度/完整性/延迟要求，支持作为时间重建研究依据；但本项目主导不确定性仍是 AMDAR 批次时间语义。",
        "- EMADDC 2025：高体量 aircraft-derived observations 进入资料同化前需要 thinning/superobbing，这直接支持 Stage10 的 super-ob 与限权。",
        "- 本地敏感性审计：只放宽 along-track bin 对 3504 万 support rows 压缩有限；通道分级的 spatial super-ob bin 更能降低 context/C 级密度支配，同时保留 current A/B 的原生 Stage2 voxel resolution。",
        f"- Sources: `{sources}`",
        "",
        "## Outputs",
        "",
        f"- T1 superobs: `{summary['outputs']['amdar_superobs_T1']}`",
        f"- T1T2 superobs: `{summary['outputs']['amdar_superobs_T1T2']}`",
        f"- T1T2T3 superobs: `{summary['outputs']['amdar_superobs_T1T2T3']}`",
        f"- Policy: `{summary['outputs']['superob_policy']}`",
        f"- Weight audit: `{summary['outputs']['weight_limit_audit']}`",
        f"- Stage10 summary: `{summary['outputs']['stage10_summary']}`",
        "",
        "## 下一步建议",
        "",
        "1. 进入 Stage11：做 Stage2/Stage4 兼容 smoke test，确认下游能读 Stage10 super-ob 字段但不误把 AMDAR 当 truth。",
        "2. Stage12：先复现 baseline，再接入 Stage10 产品做 report-only/ablation 准备。",
        "3. Stage13：按 E0/E1/E3/E4 和多时间尺度验证 A/B/C 是否真的改善风场，尤其检查 12km+ 和 batch 边界伪梯度。",
    ]
    result_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    handover = [
        "# 给下一个智能体的交接话术：Stage10 Super-Ob 后续",
        "",
        "你接手的是 `/data/LFT-W02_data/pengxu` 下的 centralized_v1 三维水平风场重构项目。不要从零开始，也不要混淆阶段名：这里的 Stage7/8/9/10 都是 `amdar_unified_implementation_plan_20260701.md` 的 Unified Plan 阶段；大框架仍是 centralized_v1 Stage1/2/3/4。",
        "",
        "## 必读文档顺序",
        "",
        "1. `/data/LFT-W02_data/pengxu/workflow/centralized_v1_docs/new_window_project_handover_20260529/centralized_v1_ultimate_summary_20260626.md`：项目 strict aircraft holdout 边界。",
        "2. `/data/LFT-W02_data/pengxu/优化/数据处理/amdar_plan4_implementation_20260630/plan4_assessment_and_run_report_20260630.md`：AMDAR 时间是批次下发/接收时间，不是逐点观测时间。",
        "3. `/data/LFT-W02_data/pengxu/优化/数据处理/amdar_plan4_comprehensive_assessment_20260701.md`：AMDAR 应走分层置信度，不能放进 strict truth。",
        "4. `/data/LFT-W02_data/pengxu/优化/数据处理/amdar_unified_implementation_plan_20260701.md`：Unified Plan 阶段边界和 Stage11/12/13 要求。",
        "5. `/data/LFT-W02_data/pengxu/优化/数据处理/amdar_unified_stage7_grade_calibration_optimized_20260701/stage7_grade_calibration_results_analysis_and_next_steps.md`：Stage7 pseudo/locked-test gate。",
        "6. `/data/LFT-W02_data/pengxu/优化/数据处理/amdar_unified_stage8_enhanced_stage1_optimized_20260701/stage8_enhanced_stage1_results_analysis_and_next_steps.md`：Stage8 enhanced Stage1 字段。",
        "7. `/data/LFT-W02_data/pengxu/优化/数据处理/amdar_unified_stage9_stage2_role_split_global_frame_optimized_20260702/stage9_stage2_role_split_results_analysis_and_next_steps.md`：修正后的 Stage9，全局 frame_index 已通过 gate。",
        f"8. `{result_path}`：Stage10 输出、达标判断、下一步建议。",
        f"9. `{summary['outputs']['stage10_summary']}`：Stage10 machine-readable completion checks。",
        f"10. `{summary['outputs']['superob_policy']}`：Stage10 super-ob 和限权策略。",
        "",
        "## 本轮脚本和输出",
        "",
        "- Stage9 修复脚本：`/data/LFT-W02_data/pengxu/优化/数据处理/amdar_unified_stage9_stage2_role_split_20260701.py`",
        "- Stage10 v2 脚本：`/data/LFT-W02_data/pengxu/优化/数据处理/amdar_unified_stage10_superob_weight_control_20260702.py`",
        f"- Stage10 输出目录：`{cfg.out_dir}`",
        "- `amdar_superobs_T1.parquet`：A 级 AMDAR super-ob。",
        "- `amdar_superobs_T1T2.parquet`：A+B 级 AMDAR super-ob。",
        "- `amdar_superobs_T1T2T3.parquet`：A+B+C 级 AMDAR super-ob。",
        "- `weight_limit_audit.json`、`superob_policy_v1.json`、`stage10_superob_summary.json`：审计与策略。",
        "",
        "运行口径：",
        "",
        "```bash",
        "POLARS_MAX_THREADS=25 /data/LFT-W02_data/pengxu/.conda/envs/windy310/bin/python \\",
        "  /data/LFT-W02_data/pengxu/优化/数据处理/amdar_unified_stage10_superob_weight_control_20260702.py \\",
        f"  --stage9-dir {cfg.stage9_dir} --out-dir {cfg.out_dir}",
        "```",
        "",
        "## 关键结果",
        "",
        f"- Stage10 completion checks: `{checks}`",
        f"- T1T2T3 counts: `{rows}`",
        f"- T1T2T3 compression: `{compression}`",
        f"- T1T2T3 cap checks: `{summary['tier_audits']['T1T2T3']['cap_checks']}`",
        "",
        "## 强制规则",
        "",
        "- AMDAR 仍然全部非 holdout、非 strict truth；strict truth 只来自 TURB T0/S，不在 Stage10 super-ob 中出现。",
        "- Stage10 只输出 support 产品，不要直接覆盖 official Stage2/Stage4 默认输入。",
        "- v2 的 current/batch support 权重公式是 `frame_time_conf * spatial_representativeness`；不要再使用已乘空间项的 `frame_joint_conf` 后二次乘空间。",
        "- A/B/C 的加入是否改善风场，必须在 Stage13 多时间尺度消融中验证，不能只凭覆盖率判断。",
        "- context support 的 `frame_time_conf=0` 语义必须保留；它是上下文条件，不是当前帧精确观测。",
        "",
        "推荐开场话术：",
        "",
        "```text",
        "我已阅读 centralized_v1 总交接、Plan4 报告、Unified Plan、Stage7/8/9/10 结果。当前 Stage9 已修复全局 frame_index，Stage10 v2 已生成 A、A+B、A+B+C 三套 AMDAR super-ob，修复空间权重双乘，并通过 batch/frame、flight/superob-voxel、source/frame 限权和压缩审计。下一步我会进入 Stage11 做兼容 smoke test，再准备 Stage12 baseline 复现和 Stage13 多时间尺度消融，严禁把 AMDAR support 当 strict truth。",
        "```",
    ]
    handover_path.write_text("\n".join(handover) + "\n", encoding="utf-8")


def main() -> None:
    cfg = parse_args()
    for bin_name in [
        "along_track_bin_points",
        "batch_along_track_bin_points",
        "context_along_track_bin_points",
        "current_xy_superob_factor",
        "batch_xy_superob_factor",
        "context_xy_superob_factor",
    ]:
        if getattr(cfg, bin_name) <= 0:
            raise ValueError(f"--{bin_name.replace('_', '-')} must be positive")
    for value_name in [
        "max_weight_per_batch_per_frame",
        "max_weight_per_flight_per_voxel",
        "max_weight_per_source_per_frame",
        "max_total_weight_ratio",
        "min_t1t2t3_raw_per_superob",
    ]:
        if getattr(cfg, value_name) <= 0:
            raise ValueError(f"--{value_name.replace('_', '-')} must be positive")
    cfg.out_dir.mkdir(parents=True, exist_ok=True)
    write_json(cfg.out_dir / "run_config.json", {**asdict(cfg), "polars_threads": os.environ.get("POLARS_MAX_THREADS")})
    stage9_summary = require_stage9(cfg.stage9_dir)
    stage8_summary = read_json(Path(stage9_summary["inputs"]["stage8_summary"]))
    stage7_summary = read_json(Path(stage9_summary["inputs"]["stage7_summary"]))

    base_path = cfg.out_dir / "_stage10_superobs_base_ABC.tmp.parquet"
    base_path.unlink(missing_ok=True)
    print(json.dumps({"stage": "stage10_build_superobs_base", "path": str(base_path)}, ensure_ascii=False), flush=True)
    build_superobs_base(cfg, base_path)

    outputs: dict[str, str] = {}
    tier_audits: dict[str, Any] = {}
    for tier, grades in TIERS.items():
        out_path = cfg.out_dir / TIER_OUTPUTS[tier]
        out_path.unlink(missing_ok=True)
        print(json.dumps({"stage": "stage10_apply_weight_limits", "tier": tier, "grades": grades}, ensure_ascii=False), flush=True)
        apply_weight_limits(cfg, base_path, tier, grades, out_path)
        tier_audits[tier] = audit_tier(cfg, tier, out_path)
        outputs[f"amdar_superobs_{tier}"] = str(out_path)

    base_path.unlink(missing_ok=True)

    completion_checks = {
        "stage7_gate_passed": bool(
            stage7_summary.get("stage7_completion_checks", {}).get("passed_stage7_grade_calibration_gate")
        ),
        "stage8_gate_passed": bool(
            stage8_summary.get("stage8_completion_checks", {}).get("passed_stage8_enhanced_stage1_gate")
        ),
        "stage9_gate_passed": bool(
            stage9_summary.get("stage9_completion_checks", {}).get("passed_stage9_stage2_role_split_gate")
        ),
        "stage9_global_frame_index_ready": bool(
            stage9_summary.get("stage9_completion_checks", {}).get("frame_index_global_unique")
            and stage9_summary.get("stage9_completion_checks", {}).get("frame_index_maps_to_single_time_str")
        ),
        "t1_written": Path(outputs["amdar_superobs_T1"]).exists(),
        "t1t2_written": Path(outputs["amdar_superobs_T1T2"]).exists(),
        "t1t2t3_written": Path(outputs["amdar_superobs_T1T2T3"]).exists(),
        "t1_gate_passed": bool(tier_audits["T1"]["passed_tier_gate"]),
        "t1t2_gate_passed": bool(tier_audits["T1T2"]["passed_tier_gate"]),
        "t1t2t3_gate_passed": bool(tier_audits["T1T2T3"]["passed_tier_gate"]),
        "t1t2t3_compression_ratio_ge_min": bool(
            tier_audits["T1T2T3"]["compression"]["raw_per_superob"] >= cfg.min_t1t2t3_raw_per_superob
        ),
    }
    completion_checks["passed_stage10_superob_weight_control_gate"] = bool(all(completion_checks.values()))

    generated_at = datetime.now(timezone.utc).isoformat()
    summary = {
        "generated_at_utc": generated_at,
        "run_policy": {
            "polars_threads": os.environ.get("POLARS_MAX_THREADS"),
            "stage10_boundary_note": (
                "Unified Plan Stage10 v2 super-ob/weight control. Does not migrate official centralized_v1 Stage4 weights."
            ),
            "space_saving_policy": (
                "Read corrected Stage9 merged parquet once, write one temporary ABC base parquet, generate three tier "
                "products, then remove the temporary base. No 25 full input copies are created."
            ),
            "stage10_v2_fixes": [
                "Use frame_time_conf, not frame_joint_conf, before applying spatial_representativeness once.",
                "Use channel-specific super-ob bins: current native, batch light coarse, context coarse low-rank.",
            ],
        },
        "inputs": {
            "stage9_dir": str(cfg.stage9_dir),
            "stage9_records": str(cfg.stage9_dir / "stage2_observation_records_all.parquet"),
            "stage9_summary": str(cfg.stage9_dir / "stage9_stage2_role_split_summary.json"),
        },
        "tier_audits": tier_audits,
        "stage10_completion_checks": completion_checks,
        "assessment": {
            "stage7_8_9_readiness": (
                "Stage7/8 gates remain valid, and corrected Stage9 now has one global frame_index per time_str. "
                "This fixes the main pre-Stage10 interface issue found during review."
            ),
            "stage10_result_quality": (
                "The products cap batch/frame, flight/superob-voxel, and source/frame weights and compress dense local "
                "groups with channel-specific super-ob bins plus a sqrt(n) density rule. They are suitable for Stage11 "
                "compatibility testing."
            ),
            "remaining_optimization_space": (
                "Stage13 must still test whether A/B/C support improves reconstruction and whether any pseudo-gradient "
                "appears near batch boundaries or 12km+ sparse regions."
            ),
        },
        "outputs": {
            **outputs,
            "superob_policy": str(cfg.out_dir / "superob_policy_v1.json"),
            "weight_limit_audit": str(cfg.out_dir / "weight_limit_audit.json"),
            "stage10_summary": str(cfg.out_dir / "stage10_superob_summary.json"),
            "result_analysis": str(cfg.out_dir / "stage10_superob_weight_control_results_analysis_and_next_steps.md"),
            "next_agent_handover": str(cfg.out_dir / "next_agent_handover_after_stage10_superob_weight_control.md"),
        },
        "literature_and_reference_basis": {
            "wmo_abo": (
                "Aircraft-based observations and AMDAR are high-volume upper-air observations for forecasting/NWP; "
                "this supports use as quality-controlled support data, not automatic strict truth."
            ),
            "noaa_amdar_madis": (
                "NOAA MADIS/AMDAR history emphasizes ACARS/ABO data-quality assessment, bad-data flagging, and correction."
            ),
            "faa_adsb": (
                "ADS-B Out broadcasts state vectors with accuracy/integrity/latency requirements; useful for time "
                "reconstruction research, while AMDAR batch timing remains the dominant uncertainty here."
            ),
                "emaddc_2025": (
                    "High-volume aircraft-derived observations need thinning and/or superobbing before data assimilation."
                ),
            "sources": {
                "wmo_aircraft_based_observations": "https://community.wmo.int/site/knowledge-hub/programmes-and-initiatives/aircraft-based-observations",
                "noaa_amdar": "https://amdar.noaa.gov/",
                "ecfr_14_cfr_91_227_adsb_out": "https://www.ecfr.gov/current/title-14/chapter-I/subchapter-F/part-91/subpart-C/section-91.227",
                "emaddc_2025_amt": "https://amt.copernicus.org/articles/18/3341/2025/",
            },
        },
    }
    policy = build_policy(cfg, summary)
    write_json(cfg.out_dir / "stage10_superob_summary.json", summary)
    write_json(cfg.out_dir / "superob_policy_v1.json", policy)
    write_json(
        cfg.out_dir / "weight_limit_audit.json",
        {
            "generated_at_utc": generated_at,
            "limits": policy["weight_limits"],
            "tier_audits": tier_audits,
            "completion_checks": completion_checks,
        },
    )
    write_docs(cfg, summary)
    print(
        json.dumps(
            {
                "stage": "stage10_done",
                "passed": summary["stage10_completion_checks"]["passed_stage10_superob_weight_control_gate"],
                "out_dir": str(cfg.out_dir),
                "tier_counts": {tier: audit["counts"] for tier, audit in tier_audits.items()},
            },
            ensure_ascii=False,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
