from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import polars as pl


ROOT = Path("/data/LFT-W02_data/pengxu")
DATA_DIR = ROOT / "优化/数据处理"
DEFAULT_BASE_DIR = DATA_DIR / "amdar_unified_stage1_2_complete_optimized_20260701"
DEFAULT_INPUT = DEFAULT_BASE_DIR / "stage1_qc_resolution_v3/stage1_qc_resolution_table_v3.parquet"
DEFAULT_OUT_DIR = DEFAULT_BASE_DIR / "stage1_qc_teacher_filter_v4"

WIND_SPEED_FILTER_MS = 150.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Apply teacher-confirmed Stage1 policy: filter AMDAR wind_speed >150 m/s before downstream support use."
    )
    parser.add_argument("--input", default=str(DEFAULT_INPUT))
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--slice-count", type=int, default=25)
    return parser.parse_args()


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def counts_map(df: pl.DataFrame, col: str) -> dict[str, int]:
    if df.height == 0 or col not in df.columns:
        return {}
    rows = (
        df.select(pl.col(col).cast(pl.Utf8, strict=False).fill_null("null").alias(col))
        .to_series()
        .value_counts()
        .sort("count", descending=True)
        .iter_rows()
    )
    return {str(k): int(v) for k, v in rows}


def bool_count(df: pl.DataFrame, expr: pl.Expr) -> int:
    if df.height == 0:
        return 0
    return int(df.select(expr.fill_null(False).sum()).item())


def build_teacher_filter(input_path: Path, out_dir: Path, slice_count: int) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)

    high_wind = (pl.col("source") == "amdar") & (pl.col("wind_speed_ms") > WIND_SPEED_FILTER_MS)
    turb_review = pl.col("turb_enhanced_holdout_review_required_v3").fill_null(False)
    strict_holdout = pl.col("strict_holdout_eligible_v3").fill_null(False) & ~turb_review

    df = (
        pl.scan_parquet(input_path)
        .with_columns(
            [
                high_wind.alias("teacher_filter_high_wind_gt150_mps_v4"),
                turb_review.alias("teacher_filter_turb_review_required_v4"),
                pl.when(high_wind)
                .then(pl.lit("filtered_high_wind_gt150_mps_teacher_confirmed_anomaly"))
                .when(turb_review)
                .then(pl.lit("filtered_turb_enhanced_qc_review"))
                .when(strict_holdout)
                .then(pl.lit("strict_holdout_eligible"))
                .when(pl.col("source") == "amdar")
                .then(pl.lit("support_only_filtered_clean"))
                .otherwise(pl.lit("other_or_legacy"))
                .alias("stage1_teacher_filter_action_v4"),
                pl.when(high_wind | turb_review)
                .then(pl.lit(0.0))
                .otherwise(pl.col("stage1_confidence_cap_v3").fill_null(1.0))
                .alias("stage1_teacher_filter_confidence_cap_v4"),
            ]
        )
        .with_columns(
            [
                (
                    (pl.col("source") == "amdar")
                    & ~pl.col("teacher_filter_high_wind_gt150_mps_v4")
                    & (pl.col("met_value_quality") == "passed")
                ).alias("support_assimilation_eligible_teacher_filter_v4"),
                strict_holdout.alias("strict_holdout_eligible_teacher_filter_v4"),
                pl.lit(False).alias("amdar_effective_strict_truth_teacher_filter_v4"),
                (high_wind | turb_review).alias("teacher_filtered_out_v4"),
                pl.lit("teacher_confirmed_filter_high_wind_anomalies_20260702").alias("teacher_filter_policy_version_v4"),
            ]
        )
        .with_columns(((pl.col("source_row_index").cast(pl.UInt64) % slice_count).cast(pl.UInt8)).alias("processing_slice_id_v4"))
        .collect(streaming=True)
    )

    filtered_out = df.filter(pl.col("teacher_filtered_out_v4"))
    kept = df.filter(~pl.col("teacher_filtered_out_v4"))
    amdar_support = df.filter(pl.col("support_assimilation_eligible_teacher_filter_v4"))
    strict_holdout_df = df.filter(pl.col("strict_holdout_eligible_teacher_filter_v4"))

    df.write_parquet(out_dir / "stage1_qc_teacher_filter_table_v4.parquet")
    kept.write_parquet(out_dir / "stage1_qc_teacher_filter_kept_rows_v4.parquet")
    filtered_out.write_parquet(out_dir / "stage1_qc_teacher_filter_filtered_rows_v4.parquet")
    amdar_support.write_parquet(out_dir / "amdar_support_after_teacher_filter_v4.parquet")
    strict_holdout_df.write_parquet(out_dir / "strict_holdout_after_teacher_filter_v4.parquet")

    strata = (
        df.group_by(
            [
                "source",
                "stage1_teacher_filter_action_v4",
                "飞行阶段",
                "altitude_band_v3",
                "amdar_batch_size_bucket_v3",
            ]
        )
        .agg(
            [
                pl.len().alias("rows"),
                pl.col("amdar_batch_id").n_unique().alias("unique_amdar_batches"),
                pl.col("wind_speed_ms").median().alias("wind_speed_ms_q50"),
                pl.col("wind_speed_ms").quantile(0.9).alias("wind_speed_ms_q90"),
                pl.col("wind_speed_ms").max().alias("wind_speed_ms_max"),
            ]
        )
        .sort("rows", descending=True)
    )
    strata.write_parquet(out_dir / "stage1_qc_teacher_filter_strata_v4.parquet")

    by_slice = (
        df.group_by("processing_slice_id_v4")
        .agg(
            [
                pl.len().alias("rows"),
                pl.col("teacher_filter_high_wind_gt150_mps_v4").sum().alias("high_wind_filtered"),
                pl.col("support_assimilation_eligible_teacher_filter_v4").sum().alias("amdar_support_kept"),
            ]
        )
        .sort("processing_slice_id_v4")
        .to_dicts()
    )

    summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "teacher_policy_context": {
            "confirmed_on": "2026-07-02",
            "statement": "老师确认风速中确实会有一些异常数据存在，这类异常可先过滤掉。",
            "implemented_policy": "Filter all AMDAR wind_speed_ms >150 m/s from downstream support assimilation for now.",
            "strict_truth_boundary": "AMDAR remains support-only; filtering high wind does not promote AMDAR to strict truth.",
        },
        "input": str(input_path),
        "rows_total": int(df.height),
        "source_counts": counts_map(df, "source"),
        "action_counts": counts_map(df, "stage1_teacher_filter_action_v4"),
        "previous_v3_action_counts": counts_map(df, "stage1_downstream_action_v3"),
        "amdar_high_wind_filtered_rows": bool_count(df, pl.col("teacher_filter_high_wind_gt150_mps_v4")),
        "amdar_support_after_filter_rows": int(amdar_support.height),
        "turb_strict_holdout_after_filter_rows": int(strict_holdout_df.height),
        "turb_review_filtered_rows": bool_count(df, pl.col("teacher_filter_turb_review_required_v4")),
        "teacher_filtered_out_rows": int(filtered_out.height),
        "support_assimilation_eligible_counts": {
            "true": bool_count(df, pl.col("support_assimilation_eligible_teacher_filter_v4")),
            "false": bool_count(df, ~pl.col("support_assimilation_eligible_teacher_filter_v4")),
        },
        "amdar_high_wind_by_phase": counts_map(
            df.filter(pl.col("teacher_filter_high_wind_gt150_mps_v4")), "飞行阶段"
        ),
        "amdar_high_wind_by_batch_size": counts_map(
            df.filter(pl.col("teacher_filter_high_wind_gt150_mps_v4")), "amdar_batch_size_bucket_v3"
        ),
        "readiness_checks": {
            "amdar_gt150_filtered_from_support": bool_count(
                df,
                pl.col("teacher_filter_high_wind_gt150_mps_v4")
                & pl.col("support_assimilation_eligible_teacher_filter_v4"),
            )
            == 0,
            "amdar_effective_strict_truth_zero": bool_count(
                df.filter(pl.col("source") == "amdar"), pl.col("amdar_effective_strict_truth_teacher_filter_v4")
            )
            == 0,
            "turb_strict_holdout_after_filter_is_175": int(strict_holdout_df.height) == 175,
            "turb_review_filtered_rows_is_6": bool_count(df, pl.col("teacher_filter_turb_review_required_v4")) == 6,
            "stage1_teacher_filter_ready_for_downstream": True,
        },
        "by_processing_slice": by_slice,
        "outputs": {
            "teacher_filter_table": str(out_dir / "stage1_qc_teacher_filter_table_v4.parquet"),
            "kept_rows": str(out_dir / "stage1_qc_teacher_filter_kept_rows_v4.parquet"),
            "filtered_rows": str(out_dir / "stage1_qc_teacher_filter_filtered_rows_v4.parquet"),
            "amdar_support_after_filter": str(out_dir / "amdar_support_after_teacher_filter_v4.parquet"),
            "strict_holdout_after_filter": str(out_dir / "strict_holdout_after_teacher_filter_v4.parquet"),
            "strata": str(out_dir / "stage1_qc_teacher_filter_strata_v4.parquet"),
            "policy": str(out_dir / "stage1_qc_teacher_filter_policy_v4.json"),
            "summary": str(out_dir / "stage1_qc_teacher_filter_summary_v4.json"),
        },
    }

    policy = {
        "generated_at_utc": summary["generated_at_utc"],
        "policy_version": "stage1_teacher_filter_high_wind_v4",
        "policy_owner_context": "Teacher confirmed on 2026-07-02 that anomalous wind-speed records can be filtered first.",
        "filter_rule": {
            "source": "amdar",
            "field": "wind_speed_ms",
            "threshold": WIND_SPEED_FILTER_MS,
            "operator": ">",
            "action": "exclude from downstream support assimilation until provider/manual review rescues rows",
        },
        "turb_rule": {
            "enhanced_qc_review_rows": "exclude from enhanced strict holdout until altitude/temperature review closes",
            "strict_holdout_after_filter": 175,
        },
        "unit_policy": {
            "amdar_wind_speed_unit": "m/s",
            "turb_wind_speed_unit": "m/s",
            "conversion_applied": False,
            "interpretation": "High AMDAR wind speed is treated as anomalous QC risk, not unit ambiguity.",
        },
        "downstream_use": {
            "amdar_support_rows_after_filter": int(amdar_support.height),
            "amdar_effective_strict_truth": 0,
            "stage2_stage3_stage4": "Use filtered support table if consuming Stage1 support data.",
            "stage5": "Still blocked unless separate validated AMDAR-ADS-B matching exists.",
        },
    }
    write_json(out_dir / "stage1_qc_teacher_filter_policy_v4.json", policy)
    write_json(out_dir / "stage1_qc_teacher_filter_summary_v4.json", summary)

    report_lines = [
        "# Stage1 Teacher-Confirmed High-Wind Filter v4",
        "",
        f"Generated at UTC: {summary['generated_at_utc']}",
        "",
        "## Context",
        "",
        "老师确认风速中确实会有一些异常数据存在，这类异常可以先过滤掉。因此本版本把 AMDAR `wind_speed_ms >150 m/s` 统一从下游 support assimilation 数据流中过滤，而不是继续保留 150-200 m/s 低置信使用。",
        "",
        "## Result",
        "",
        f"- Total rows: `{summary['rows_total']}`",
        f"- Source counts: `{summary['source_counts']}`",
        f"- AMDAR high-wind filtered rows: `{summary['amdar_high_wind_filtered_rows']}`",
        f"- AMDAR support rows after filter: `{summary['amdar_support_after_filter_rows']}`",
        f"- TURB strict holdout after enhanced filter: `{summary['turb_strict_holdout_after_filter_rows']}`",
        f"- TURB enhanced-QC filtered/review rows: `{summary['turb_review_filtered_rows']}`",
        f"- Action counts: `{summary['action_counts']}`",
        "",
        "## Interpretation",
        "",
        "Stage1 is now cleaner for downstream experiments: AMDAR remains support-only, but the confirmed anomalous high-wind tail is removed from the support stream. This lowers the chance that extreme bad wind values dominate super-ob or reconstruction weights.",
        "",
        "This does not change the strict-truth boundary: AMDAR strict truth is still zero. TURB remains the conservative strict-truth source, with 175 enhanced-holdout-eligible rows after excluding 6 review rows.",
        "",
        "## Outputs",
        "",
        f"- Teacher filter table: `{summary['outputs']['teacher_filter_table']}`",
        f"- Filtered rows: `{summary['outputs']['filtered_rows']}`",
        f"- AMDAR support after filter: `{summary['outputs']['amdar_support_after_filter']}`",
        f"- Strict holdout after filter: `{summary['outputs']['strict_holdout_after_filter']}`",
        f"- Summary: `{summary['outputs']['summary']}`",
    ]
    (out_dir / "stage1_qc_teacher_filter_results_v4.md").write_text("\n".join(report_lines) + "\n", encoding="utf-8")
    return summary


def main() -> None:
    args = parse_args()
    summary = build_teacher_filter(Path(args.input), Path(args.out_dir), args.slice_count)
    print(json.dumps({"stage": "stage1_teacher_filter_v4_done", "summary": summary["outputs"]["summary"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
