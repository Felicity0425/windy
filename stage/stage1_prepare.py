"""Stage 1：读取并清洗 location/amdar/turb，生成统一中间数据与雷达时间窗索引。

输出目录：stage1_output/
- clean_wind.parquet
- clean_loc.parquet
- radar_index.json
- frame_window_index.json
- stage1_summary.json
"""

import json
import os
import glob
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import polars as pl

import pipeline_config as cfg


FEET_TO_METERS = 0.3048
WIND_FEET_SHARE_THRESHOLD = 0.20
MAX_REASONABLE_ALT_METERS = 20000.0
AMDAR_BATCH_HSPAN_THRESHOLD_DEG = float(getattr(cfg, "AMDAR_BATCH_HSPAN_THRESHOLD_DEG", 0.50))
AMDAR_BATCH_SUPPORT_CONFIDENCE = float(getattr(cfg, "AMDAR_BATCH_SUPPORT_CONFIDENCE", 0.35))


def _sanitize_float_expr(expr: pl.Expr) -> pl.Expr:
    expr = expr.cast(pl.Float64, strict=False)
    return pl.when(expr.is_finite()).then(expr).otherwise(pl.lit(None, dtype=pl.Float64))


def _nullify_nonfinite_float_columns(df: pl.DataFrame) -> pl.DataFrame:
    exprs: list[pl.Expr] = []
    for col_name, dtype in df.schema.items():
        if dtype in (pl.Float32, pl.Float64):
            exprs.append(
                pl.when(pl.col(col_name).is_finite())
                .then(pl.col(col_name))
                .otherwise(pl.lit(None, dtype=dtype))
                .alias(col_name)
            )
    if not exprs:
        return df
    return df.with_columns(exprs)


def _read_parquet_manifest_dir(parquet_dir: str, num_workers: int = 1) -> pl.DataFrame:
    manifest_path = os.path.join(parquet_dir, "_manifest.json")
    if not os.path.exists(manifest_path):
        raise FileNotFoundError(f"Missing manifest: {manifest_path}")
    with open(manifest_path, "r", encoding="utf-8") as f:
        mf = json.load(f)
    shards = mf.get("shards", []) or []
    shard_paths = []
    for s in shards:
        p = s.get("out_parquet") or s.get("parquet")
        if not p:
            continue
        candidates = []
        if os.path.isabs(p):
            candidates.append(p)
        else:
            candidates.append(os.path.join(parquet_dir, p))
        # Manifests are often migrated with stale absolute paths. Prefer the
        # current parquet directory when a same-named shard exists there.
        candidates.append(os.path.join(parquet_dir, os.path.basename(p)))
        shard_paths.append(next((c for c in candidates if os.path.exists(c)), candidates[0]))
    if not shard_paths:
        raise RuntimeError(f"No parquet shards found in {parquet_dir}")
    readable_paths = [p for p in shard_paths if os.path.exists(p)]
    workers = max(1, min(int(num_workers), len(readable_paths)))
    if workers > 1:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            dfs = list(pool.map(pl.read_parquet, readable_paths))
    else:
        dfs = [pl.read_parquet(p) for p in readable_paths]
    if not dfs:
        raise RuntimeError(f"No readable parquet shards found in {parquet_dir}")
    return pl.concat(dfs, how="diagonal_relaxed")


def _load_new_inputs(num_workers: int):
    loc_dir = os.path.join(cfg.DATA_ROOT, "location_location_parquet")
    amdar_dir = os.path.join(cfg.DATA_ROOT, "amdar_parquet")
    turb_dir = os.path.join(cfg.DATA_ROOT, "turb_parquet")

    with ThreadPoolExecutor(max_workers=max(1, min(int(num_workers), 3))) as pool:
        fut_loc = pool.submit(_read_parquet_manifest_dir, loc_dir, num_workers)
        fut_amdar = pool.submit(_read_parquet_manifest_dir, amdar_dir, num_workers)
        fut_turb = pool.submit(_read_parquet_manifest_dir, turb_dir, num_workers)
        df_loc = fut_loc.result()
        df_amdar = fut_amdar.result()
        df_turb = fut_turb.result()

    return df_amdar, df_turb, df_loc


def _first_existing_altitude_col(df: pl.DataFrame):
    for col in ("alt_meters", "高度"):
        if col in df.columns:
            return col
    return None


def _infer_altitude_unit_mode(df: pl.DataFrame, source_hint: str) -> str:
    alt_col = _first_existing_altitude_col(df)
    if alt_col is None:
        return "missing_column"

    alt = df.select(pl.col(alt_col).cast(pl.Float64, strict=False).alias("alt")).get_column("alt").drop_nulls()
    if alt.len() == 0:
        return "missing_values"

    total = float(alt.len())
    median_alt = float(alt.quantile(0.5))
    share_gt_15000 = float((alt > 15000.0).sum()) / total
    share_20k_45k = float(((alt >= 20000.0) & (alt <= 45000.0)).sum()) / total

    if source_hint in {"amdar", "turb", "wind"}:
        if median_alt > 15000.0 or share_gt_15000 > 0.50 or share_20k_45k > WIND_FEET_SHARE_THRESHOLD:
            return "feet_source"
        return "meters_source"

    if share_20k_45k > 0.0:
        return "meters_source_with_feet_anomalies"
    return "meters_source"


def _normalize_altitude(df: pl.DataFrame, source_hint: str) -> pl.DataFrame:
    alt_col = _first_existing_altitude_col(df)
    unit_mode = _infer_altitude_unit_mode(df, source_hint)

    if alt_col is None:
        return df.with_columns(
            [
                pl.lit(None, dtype=pl.Float64).alias("alt_meters"),
                pl.lit("missing_altitude").alias("altitude_unit_state"),
                pl.lit(unit_mode).alias("altitude_unit_mode"),
            ]
        )

    alt_expr = pl.col(alt_col).cast(pl.Float64, strict=False)

    if source_hint in {"amdar", "turb", "wind"} and unit_mode == "feet_source":
        converted_expr = alt_expr * FEET_TO_METERS
        outlier_mask = converted_expr > MAX_REASONABLE_ALT_METERS
        alt_meters_expr = pl.when(outlier_mask).then(pl.lit(None, dtype=pl.Float64)).otherwise(converted_expr)
        state_expr = (
            pl.when(alt_expr.is_null())
            .then(pl.lit("missing_altitude"))
            .when(outlier_mask)
            .then(pl.lit("altitude_outlier_nullified"))
            .otherwise(pl.lit("feet_to_meters_source"))
        )
    elif source_hint == "loc":
        feet_row_mask = alt_expr.is_not_null() & (alt_expr > 15000.0) & (alt_expr <= 45000.0)
        alt_meters_expr = pl.when(feet_row_mask).then(alt_expr * FEET_TO_METERS).otherwise(alt_expr)
        state_expr = (
            pl.when(alt_expr.is_null())
            .then(pl.lit("missing_altitude"))
            .when(feet_row_mask)
            .then(pl.lit("feet_to_meters_row"))
            .otherwise(pl.lit("meters_preserved"))
        )
    else:
        alt_meters_expr = alt_expr
        state_expr = (
            pl.when(alt_expr.is_null())
            .then(pl.lit("missing_altitude"))
            .otherwise(pl.lit("meters_preserved"))
        )

    return df.with_columns(
        [
            alt_meters_expr.alias("alt_meters"),
            state_expr.alias("altitude_unit_state"),
            pl.lit(unit_mode).alias("altitude_unit_mode"),
        ]
    )


def _altitude_audit(df: pl.DataFrame, group_col: str | None = None):
    def _value_count_map(frame: pl.DataFrame, col_name: str):
        vc = frame.select(pl.col(col_name).fill_null("null").alias(col_name)).to_series().value_counts().sort("count", descending=True)
        return {str(row[0]): int(row[1]) for row in vc.iter_rows()}

    def _audit_one(frame: pl.DataFrame):
        out = {
            "rows": int(len(frame)),
            "nonnull_rows": 0,
            "min_m": None,
            "median_m": None,
            "p90_m": None,
            "max_m": None,
            "rows_gt_12000m": 0,
            "rows_gt_15000m": 0,
            "unit_mode_counts": {},
            "unit_state_counts": {},
        }
        if "altitude_unit_mode" in frame.columns:
            out["unit_mode_counts"] = _value_count_map(frame, "altitude_unit_mode")
        if "altitude_unit_state" in frame.columns:
            out["unit_state_counts"] = _value_count_map(frame, "altitude_unit_state")

        if "alt_meters" not in frame.columns:
            return out

        alt = frame.select(pl.col("alt_meters").cast(pl.Float64, strict=False).alias("alt")).get_column("alt").drop_nulls()
        if alt.len() == 0:
            return out

        out["nonnull_rows"] = int(alt.len())
        out["min_m"] = float(alt.min())
        out["median_m"] = float(alt.quantile(0.5))
        out["p90_m"] = float(alt.quantile(0.9))
        out["max_m"] = float(alt.max())
        out["rows_gt_12000m"] = int((alt > 12000.0).sum())
        out["rows_gt_15000m"] = int((alt > 15000.0).sum())
        return out

    if group_col and group_col in df.columns:
        groups = {}
        for value in df[group_col].drop_nulls().unique().to_list():
            groups[str(value)] = _audit_one(df.filter(pl.col(group_col) == value))
        return groups
    return _audit_one(df)


def _numeric_field_audit(df: pl.DataFrame, col: str):
    out = {
        "present": col in df.columns,
        "rows": int(len(df)),
        "null_rows": 0,
        "nan_rows": 0,
        "finite_rows": 0,
        "min": None,
        "median": None,
        "p90": None,
        "max": None,
    }
    if col not in df.columns:
        return out

    s = df.select(pl.col(col).cast(pl.Float64, strict=False).alias(col)).get_column(col)
    out["null_rows"] = int(s.is_null().sum())
    out["nan_rows"] = int(s.is_nan().sum())
    finite = s.filter(s.is_finite())
    out["finite_rows"] = int(finite.len())
    if finite.len() == 0:
        return out

    out["min"] = float(finite.min())
    out["median"] = float(finite.quantile(0.5))
    out["p90"] = float(finite.quantile(0.9))
    out["max"] = float(finite.max())
    return out


def _normalize_loc(df: pl.DataFrame) -> pl.DataFrame:
    parsed_time = None
    if "接收时间（UTC）" in df.columns:
        parsed_time = pl.col("接收时间（UTC）").cast(pl.Utf8, strict=False).str.strptime(pl.Datetime, strict=False)
    time_exprs: list[pl.Expr] = []
    if "time_utc" in df.columns:
        time_exprs.append(pl.col("time_utc").cast(pl.Datetime, strict=False))
    if parsed_time is not None:
        time_exprs.append(parsed_time)
    if time_exprs:
        df = df.with_columns(pl.coalesce(time_exprs).alias("time_utc"))

    lat_exprs: list[pl.Expr] = []
    if "lat_clean" in df.columns:
        lat_exprs.append(_sanitize_float_expr(pl.col("lat_clean")))
    if "纬度_clean" in df.columns:
        lat_exprs.append(_sanitize_float_expr(pl.col("纬度_clean")))
    if lat_exprs:
        df = df.with_columns(pl.coalesce(lat_exprs).alias("lat_clean"))

    lon_exprs: list[pl.Expr] = []
    if "lon_clean" in df.columns:
        lon_exprs.append(_sanitize_float_expr(pl.col("lon_clean")))
    if "经度_clean" in df.columns:
        lon_exprs.append(_sanitize_float_expr(pl.col("经度_clean")))
    if lon_exprs:
        df = df.with_columns(pl.coalesce(lon_exprs).alias("lon_clean"))

    df = _normalize_altitude(df, source_hint="loc")
    heading_exprs: list[pl.Expr] = []
    if "heading_deg" in df.columns:
        heading_exprs.append(_sanitize_float_expr(pl.col("heading_deg")))
    if "航向角" in df.columns:
        heading_exprs.append(_sanitize_float_expr(pl.col("航向角")))
    if heading_exprs:
        df = df.with_columns(pl.coalesce(heading_exprs).alias("heading_deg"))

    speed_exprs: list[pl.Expr] = []
    if "ground_speed_ms" in df.columns:
        speed_exprs.append(_sanitize_float_expr(pl.col("ground_speed_ms")))
    if "地速" in df.columns:
        speed_exprs.append(_sanitize_float_expr(pl.col("地速")) * cfg.GROUND_SPEED_TO_MPS)
    if speed_exprs:
        df = df.with_columns(pl.coalesce(speed_exprs).alias("ground_speed_ms"))

    flight_col = None
    for c in ["flight_id", "航班号", "机尾号"]:
        if c in df.columns:
            flight_col = c
            break
    virtual_id = pl.lit("flight_") + pl.int_range(0, pl.len()).cast(pl.Utf8)
    if flight_col:
        raw_flight = pl.col(flight_col).cast(pl.Utf8, strict=False).str.strip_chars()
        missing_flight = raw_flight.is_null() | (raw_flight == "")
        df = df.with_columns(
            [
                pl.when(missing_flight).then(virtual_id).otherwise(raw_flight).alias("flight_id"),
                missing_flight.alias("flight_id_is_virtual"),
                pl.when(missing_flight).then(pl.lit("generated_missing_value")).otherwise(pl.lit(flight_col)).alias("flight_id_source"),
            ]
        )
    else:
        df = df.with_columns(
            [
                virtual_id.alias("flight_id"),
                pl.lit(True).alias("flight_id_is_virtual"),
                pl.lit("generated_missing_column").alias("flight_id_source"),
            ]
        )

    if "ground_speed_ms" in df.columns and "heading_deg" in df.columns:
        df = df.with_columns([
            (pl.col("ground_speed_ms") * (pl.col("heading_deg") * 3.141592653589793 / 180).sin()).alias("u_motion"),
            (pl.col("ground_speed_ms") * (pl.col("heading_deg") * 3.141592653589793 / 180).cos()).alias("v_motion"),
        ])

    return _nullify_nonfinite_float_columns(df)


def _normalize_wind(df: pl.DataFrame, source_hint: str) -> pl.DataFrame:
    if "source_row_index" not in df.columns:
        df = df.with_row_index("source_row_index")

    time_candidates = []
    if "time_utc" in df.columns:
        time_candidates.append(pl.col("time_utc").cast(pl.Datetime, strict=False))
    if "time_beijing" in df.columns:
        time_candidates.append(pl.col("time_beijing").cast(pl.Datetime, strict=False))
    if "时间（北京时间）" in df.columns:
        time_candidates.append(pl.col("时间（北京时间）").cast(pl.Datetime, strict=False))

    if time_candidates:
        # Prefer already-normalized UTC, then Beijing time shifted to UTC.
        utc_expr = None
        if "time_utc" in df.columns:
            utc_expr = pl.col("time_utc").cast(pl.Datetime, strict=False)
        bj_exprs = []
        if "time_beijing" in df.columns:
            bj_exprs.append(pl.col("time_beijing").cast(pl.Datetime, strict=False).dt.offset_by("-8h"))
        if "时间（北京时间）" in df.columns:
            bj_exprs.append(pl.col("时间（北京时间）").cast(pl.Datetime, strict=False).dt.offset_by("-8h"))
        exprs = []
        if utc_expr is not None:
            exprs.append(utc_expr)
        exprs.extend(bj_exprs)
        df = df.with_columns(pl.coalesce(exprs).alias("time_utc"))

    lat_exprs: list[pl.Expr] = []
    if "lat_clean" in df.columns:
        lat_exprs.append(_sanitize_float_expr(pl.col("lat_clean")))
    if "纬度_clean" in df.columns:
        lat_exprs.append(_sanitize_float_expr(pl.col("纬度_clean")))
    if lat_exprs:
        df = df.with_columns(pl.coalesce(lat_exprs).alias("lat_clean"))

    lon_exprs: list[pl.Expr] = []
    if "lon_clean" in df.columns:
        lon_exprs.append(_sanitize_float_expr(pl.col("lon_clean")))
    if "经度_clean" in df.columns:
        lon_exprs.append(_sanitize_float_expr(pl.col("经度_clean")))
    if lon_exprs:
        df = df.with_columns(pl.coalesce(lon_exprs).alias("lon_clean"))

    df = _normalize_altitude(df, source_hint=source_hint)

    wind_dir_exprs: list[pl.Expr] = []
    if "wind_dir" in df.columns:
        wind_dir_exprs.append(_sanitize_float_expr(pl.col("wind_dir")))
    if "风向" in df.columns:
        wind_dir_exprs.append(_sanitize_float_expr(pl.col("风向")))
    if wind_dir_exprs:
        df = df.with_columns(pl.coalesce(wind_dir_exprs).alias("wind_dir"))

    wind_speed_exprs: list[pl.Expr] = []
    if "wind_speed" in df.columns:
        wind_speed_exprs.append(_sanitize_float_expr(pl.col("wind_speed")))
    if "风速" in df.columns:
        wind_speed_exprs.append(_sanitize_float_expr(pl.col("风速")))
    if wind_speed_exprs:
        df = df.with_columns(pl.coalesce(wind_speed_exprs).alias("wind_speed"))

    if "wind_dir" in df.columns and "wind_speed" in df.columns:
        df = df.with_columns([
            (-pl.col("wind_speed") * (pl.col("wind_dir") * 3.141592653589793 / 180).sin()).alias("u_wind"),
            (-pl.col("wind_speed") * (pl.col("wind_dir") * 3.141592653589793 / 180).cos()).alias("v_wind"),
        ])

    if "flight_id" not in df.columns:
        wind_flight_col = None
        for c in ["航班号", "机尾号"]:
            if c in df.columns:
                wind_flight_col = c
                break
        if wind_flight_col is not None:
            df = df.with_columns(pl.col(wind_flight_col).cast(pl.Utf8, strict=False).str.strip_chars().alias("flight_id"))
        else:
            df = df.with_columns(pl.lit(None, dtype=pl.Utf8).alias("flight_id"))

    if source_hint == "amdar":
        batch_time_exprs: list[pl.Expr] = []
        if "时间（北京时间）" in df.columns:
            batch_time_exprs.append(pl.col("时间（北京时间）").cast(pl.Datetime, strict=False))
        if "时间（北京时）" in df.columns:
            batch_time_exprs.append(pl.col("时间（北京时）").cast(pl.Datetime, strict=False))
        if "time_beijing" in df.columns:
            batch_time_exprs.append(pl.col("time_beijing").cast(pl.Datetime, strict=False))
        if batch_time_exprs:
            batch_time_beijing = pl.coalesce(batch_time_exprs)
        else:
            batch_time_beijing = pl.lit(None, dtype=pl.Datetime)
        df = df.with_columns(
            [
                batch_time_beijing.alias("amdar_batch_time_beijing"),
                pl.col("time_utc").cast(pl.Datetime, strict=False).alias("amdar_batch_time_utc"),
                pl.col("time_utc").cast(pl.Datetime, strict=False).alias("time_utc"),
                pl.lit("batch_time_unknown_exact_type").alias("amdar_time_semantics"),
                pl.lit(False).alias("strict_time_truth"),
                pl.lit(False).alias("time_is_point_observation"),
                pl.lit(None, dtype=pl.Datetime).alias("observation_time_utc"),
                pl.lit("unavailable").alias("observation_time_source"),
                pl.lit(None, dtype=pl.Float64).alias("observation_time_uncertainty_s"),
                pl.lit("passed").alias("met_value_quality"),
            ]
        )
    else:
        df = df.with_columns(
            [
                pl.lit(None, dtype=pl.Datetime).alias("amdar_batch_time_beijing"),
                pl.lit(None, dtype=pl.Datetime).alias("amdar_batch_time_utc"),
                pl.lit(None, dtype=pl.Utf8).alias("amdar_time_semantics"),
                pl.lit(source_hint != "amdar").alias("strict_time_truth"),
                pl.lit(True).alias("time_is_point_observation"),
                pl.col("time_utc").cast(pl.Datetime, strict=False).alias("observation_time_utc"),
                pl.lit("source_time_utc").alias("observation_time_source"),
                pl.lit(0.0).alias("observation_time_uncertainty_s"),
                pl.lit("passed").alias("met_value_quality"),
            ]
        )

    return _nullify_nonfinite_float_columns(df)


def _annotate_wind_time_groups(df: pl.DataFrame) -> pl.DataFrame:
    needed = {"source", "flight_id", "time_utc", "lat_clean", "lon_clean", "alt_meters"}
    if len(df) == 0 or not needed.issubset(set(df.columns)):
        return df

    group_stats = (
        df.select(
            [
                "source",
                "flight_id",
                "time_utc",
                "lat_clean",
                "lon_clean",
                "alt_meters",
                "source_row_index",
            ]
        )
        .drop_nulls(["source", "flight_id", "time_utc"])
        .group_by(["source", "flight_id", "time_utc"])
        .agg(
            [
                pl.len().alias("same_time_group_rows"),
                pl.col("lat_clean").min().alias("lat_min"),
                pl.col("lat_clean").max().alias("lat_max"),
                pl.col("lon_clean").min().alias("lon_min"),
                pl.col("lon_clean").max().alias("lon_max"),
                pl.col("alt_meters").min().alias("alt_min"),
                pl.col("alt_meters").max().alias("alt_max"),
                pl.col("source_row_index").min().alias("same_time_group_row_index_min"),
                pl.col("source_row_index").max().alias("same_time_group_row_index_max"),
            ]
        )
        .with_columns(
            [
                (pl.col("lat_max") - pl.col("lat_min")).alias("same_time_group_lat_span_deg"),
                (pl.col("lon_max") - pl.col("lon_min")).alias("same_time_group_lon_span_deg"),
                (pl.col("alt_max") - pl.col("alt_min")).alias("same_time_group_alt_span_m"),
                (
                    pl.col("same_time_group_row_index_max") - pl.col("same_time_group_row_index_min") + 1
                ).alias("same_time_group_source_row_span"),
                (
                    ((pl.col("lat_max") - pl.col("lat_min")) ** 2)
                    + ((pl.col("lon_max") - pl.col("lon_min")) ** 2)
                )
                .sqrt()
                .alias("same_time_group_hspan_deg"),
            ]
        )
        .with_columns(
            pl.when(
                (pl.col("source") == "amdar")
                & (pl.col("same_time_group_rows") > 1)
                & (pl.col("same_time_group_hspan_deg") >= AMDAR_BATCH_HSPAN_THRESHOLD_DEG)
            )
            .then(pl.lit("amdar_batched_same_timestamp"))
            .when(
                (pl.col("source") == "amdar")
                & (pl.col("same_time_group_rows") > 1)
            )
            .then(pl.lit("amdar_duplicate_same_timestamp_requires_batch_handling"))
            .when(pl.col("same_time_group_rows") > 1)
            .then(pl.lit("duplicate_same_timestamp"))
            .otherwise(pl.lit("single_point_timestamp"))
            .alias("time_group_alignment_flag")
        )
        .select(
            [
                "source",
                "flight_id",
                "time_utc",
                "same_time_group_rows",
                "same_time_group_lat_span_deg",
                "same_time_group_lon_span_deg",
                "same_time_group_alt_span_m",
                "same_time_group_source_row_span",
                "same_time_group_row_index_min",
                "same_time_group_row_index_max",
                "same_time_group_hspan_deg",
                "time_group_alignment_flag",
            ]
        )
    )

    return (
        df.join(group_stats, on=["source", "flight_id", "time_utc"], how="left")
        .with_columns(
            [
                pl.col("same_time_group_rows").fill_null(1),
                pl.col("same_time_group_lat_span_deg").fill_null(0.0),
                pl.col("same_time_group_lon_span_deg").fill_null(0.0),
                pl.col("same_time_group_alt_span_m").fill_null(0.0),
                pl.col("same_time_group_source_row_span").fill_null(1),
                pl.col("same_time_group_row_index_min").fill_null(pl.col("source_row_index")),
                pl.col("same_time_group_row_index_max").fill_null(pl.col("source_row_index")),
                pl.col("same_time_group_hspan_deg").fill_null(0.0),
                pl.col("time_group_alignment_flag").fill_null("missing_group_key"),
            ]
        )
        .with_columns(pl.col("obs_conf").cast(pl.Float64, strict=False).alias("obs_conf_source_base"))
        .with_columns(
            [
                pl.when(
                    (pl.col("source") == "amdar")
                    & (pl.col("same_time_group_rows") > 1)
                )
                .then(pl.lit("support_only_not_strict_truth"))
                .otherwise(pl.lit("strict_truth_candidate"))
                .alias("wind_reconstruction_role"),
                pl.when(
                    (pl.col("source") == "amdar")
                    & (pl.col("same_time_group_rows") > 1)
                )
                .then(pl.lit("amdar_same_timestamp_duplicate_batch"))
                .otherwise(pl.lit("none"))
                .alias("wind_reconstruction_exclusion_reason"),
                pl.when(
                    (pl.col("source") == "amdar")
                    & (pl.col("same_time_group_rows") > 1)
                )
                .then(pl.lit(float(AMDAR_BATCH_SUPPORT_CONFIDENCE)))
                .otherwise(pl.col("obs_conf_source_base"))
                .alias("obs_conf"),
                pl.col("obs_conf_source_base").alias("obs_conf_raw_for_reconstruction"),
            ]
        )
    )


def _finalize_amdar_batch_fields(df: pl.DataFrame) -> pl.DataFrame:
    needed = {"source", "flight_id", "time_utc", "same_time_group_rows", "source_row_index"}
    if len(df) == 0 or not needed.issubset(set(df.columns)):
        return df

    amdar = (
        df.filter(pl.col("source") == "amdar")
        .sort("source_row_index")
        .with_columns(
            [
                (pl.col("source_row_index").cast(pl.Int64, strict=False) + 2).alias("raw_row_number"),
                pl.col("机尾号").cast(pl.Utf8, strict=False).fill_null("missing_tail").alias("tail_key"),
                pl.col("航班号").cast(pl.Utf8, strict=False).fill_null("missing_flight").alias("flight_key"),
                pl.col("飞行阶段").cast(pl.Utf8, strict=False).fill_null("missing_phase").alias("phase_key"),
                pl.col("time_utc").cast(pl.Datetime, strict=False).alias("batch_time_utc"),
                pl.col("time_utc").cast(pl.Int64, strict=False).fill_null(-1).alias("batch_time_key_int"),
            ]
        )
        .with_columns(
            [
                pl.col("source_row_index").shift(1).alias("prev_source_row_index"),
                pl.col("tail_key").shift(1).alias("prev_tail_key"),
                pl.col("flight_key").shift(1).alias("prev_flight_key"),
                pl.col("phase_key").shift(1).alias("prev_phase_key"),
                pl.col("batch_time_key_int").shift(1).alias("prev_batch_time_key_int"),
            ]
        )
        .with_columns(
            pl.when(
                pl.col("prev_source_row_index").is_null()
                | ((pl.col("source_row_index") - pl.col("prev_source_row_index")) != 1)
                | (pl.col("tail_key") != pl.col("prev_tail_key"))
                | (pl.col("flight_key") != pl.col("prev_flight_key"))
                | (pl.col("phase_key") != pl.col("prev_phase_key"))
                | (pl.col("batch_time_key_int") != pl.col("prev_batch_time_key_int"))
            )
            .then(1)
            .otherwise(0)
            .alias("amdar_batch_block_start_flag")
        )
        .with_columns(
            [
                pl.col("amdar_batch_block_start_flag").cum_sum().alias("amdar_batch_block_seq_global"),
                pl.col("amdar_batch_block_start_flag")
                .cum_sum()
                .over(["tail_key", "flight_key", "phase_key", "batch_time_key_int"])
                .alias("amdar_batch_contiguous_block_index"),
            ]
        )
        .with_columns(
            pl.col("source_row_index")
            .rank("ordinal")
            .over("amdar_batch_block_seq_global")
            .cast(pl.Int64, strict=False)
            .alias("amdar_observation_order")
        )
    )

    batch_stats = (
        amdar.group_by("amdar_batch_block_seq_global")
        .agg(
            [
                pl.col("flight_id").first().alias("flight_id"),
                pl.col("time_utc").first().alias("time_utc"),
                pl.col("机尾号").first().alias("机尾号"),
                pl.col("航班号").first().alias("航班号"),
                pl.col("飞行阶段").first().alias("飞行阶段"),
                pl.col("tail_key").first().alias("tail_key"),
                pl.col("flight_key").first().alias("flight_key"),
                pl.col("phase_key").first().alias("phase_key"),
                pl.col("batch_time_utc").first().alias("batch_time_utc"),
                pl.col("amdar_batch_contiguous_block_index").first().alias("amdar_batch_contiguous_block_index"),
                pl.len().alias("amdar_batch_row_count"),
                pl.col("raw_row_number").min().alias("amdar_batch_raw_row_start"),
                pl.col("raw_row_number").max().alias("amdar_batch_raw_row_end"),
                pl.col("same_time_group_hspan_deg").max().alias("amdar_batch_hspan_deg"),
                pl.col("same_time_group_alt_span_m").max().alias("amdar_batch_vertical_span_m"),
            ]
        )
        .with_columns(
            [
                (
                    pl.col("amdar_batch_raw_row_end") - pl.col("amdar_batch_raw_row_start") + 1
                ).alias("amdar_batch_expected_row_span"),
                (
                    pl.col("amdar_batch_row_count")
                    == (pl.col("amdar_batch_raw_row_end") - pl.col("amdar_batch_raw_row_start") + 1)
                )
                .fill_null(False)
                .alias("amdar_batch_is_contiguous"),
                pl.col("batch_time_utc")
                .cast(pl.Datetime, strict=False)
                .dt.strftime("%Y%m%dT%H%M%S")
                .fill_null("missing_time")
                .alias("time_key"),
            ]
        )
        .with_columns(
            (
                pl.lit("amdar_batch_")
                + pl.col("tail_key")
                + pl.lit("__")
                + pl.col("flight_key")
                + pl.lit("__")
                + pl.col("phase_key")
                + pl.lit("__")
                + pl.col("time_key")
                + pl.lit("__b")
                + pl.col("amdar_batch_contiguous_block_index").cast(pl.Utf8)
                + pl.lit("__r")
                + pl.col("amdar_batch_raw_row_start").cast(pl.Utf8)
            ).alias("amdar_batch_id")
        )
        .with_columns(
            [
                pl.when(pl.col("amdar_batch_row_count") > 1)
                .then(pl.lit("batch_time_confirmed"))
                .otherwise(pl.lit("unverified_singleton_batch_time"))
                .alias("time_quality"),
                pl.lit("support_only_not_strict_truth").alias("usage_role"),
            ]
        )
    )

    amdar_batch_rows = (
        amdar.join(batch_stats, on="amdar_batch_block_seq_global", how="left")
        .select(
            [
                "source",
                "source_row_index",
                "raw_row_number",
                "amdar_observation_order",
                "amdar_batch_block_seq_global",
                "amdar_batch_contiguous_block_index",
                "amdar_batch_id",
                "amdar_batch_row_count",
                "amdar_batch_raw_row_start",
                "amdar_batch_raw_row_end",
                "amdar_batch_is_contiguous",
                "amdar_batch_hspan_deg",
                "amdar_batch_vertical_span_m",
                "time_quality",
                "usage_role",
            ]
        )
    )

    out = df.join(amdar_batch_rows, on=["source", "source_row_index"], how="left")
    out = out.with_columns(
        [
            pl.when(pl.col("source") == "amdar")
            .then(pl.col("usage_role").fill_null("support_only_not_strict_truth"))
            .otherwise(pl.col("wind_reconstruction_role"))
            .alias("usage_role"),
            pl.when(pl.col("source") == "amdar")
            .then(pl.col("time_quality").fill_null("batch_time_unknown_semantics"))
            .otherwise(pl.lit("trusted_source_time"))
            .alias("time_quality"),
            pl.when(pl.col("source") == "amdar")
            .then(pl.lit(False))
            .otherwise(pl.col("strict_time_truth"))
            .alias("strict_time_truth"),
        ]
    )
    return out.with_columns(
        [
            pl.when(pl.col("source") == "amdar")
            .then(pl.lit("batch_time_available_observation_time_unavailable"))
            .otherwise(pl.col("observation_time_source"))
            .alias("observation_time_source"),
            pl.when(pl.col("source") == "amdar")
            .then(pl.lit(False))
            .otherwise(pl.col("time_is_point_observation"))
            .alias("time_is_point_observation"),
        ]
    )


def _value_count_map(df: pl.DataFrame, col: str) -> dict[str, int]:
    if col not in df.columns:
        return {}
    vc = (
        df.select(pl.col(col).cast(pl.Utf8, strict=False).fill_null("null").alias(col))
        .to_series()
        .value_counts()
        .sort("count", descending=True)
    )
    return {str(row[0]): int(row[1]) for row in vc.iter_rows()}


def build_radar_files():
    radar_files = []
    for pattern in cfg.RADAR_PATTERNS:
        if os.path.isabs(pattern):
            search_patterns = [pattern]
        else:
            search_patterns = [os.path.join(cfg.DATA_ROOT, pattern)]
        for sp in search_patterns:
            radar_files.extend(glob.glob(sp, recursive=True))
    radar_files = sorted(set(radar_files))
    if cfg.MAX_FRAMES is not None:
        radar_files = radar_files[: cfg.MAX_FRAMES]
    return radar_files


def _radar_window_record(args):
    rp, loc_min_time, loc_max_time, df_wind_sorted, df_loc_sorted = args
    fn = os.path.basename(rp)
    try:
        ts = fn.split("_")[7]
        t = datetime.strptime(ts, "%Y%m%d%H%M%S")
    except Exception:
        return None

    usable = True
    if cfg.OVERLAP_ONLY and loc_min_time is not None and loc_max_time is not None:
        loc_min_time_dt = loc_min_time.to_pydatetime() if hasattr(loc_min_time, "to_pydatetime") else loc_min_time
        loc_max_time_dt = loc_max_time.to_pydatetime() if hasattr(loc_max_time, "to_pydatetime") else loc_max_time
        usable = loc_min_time_dt <= t <= loc_max_time_dt

    radar_item = {
        "filename": fn,
        "time_str": ts,
        "timestamp_utc": t.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "radar_path": rp,
        "usable": bool(usable),
    }
    if not usable:
        return radar_item, None

    t_start = t - timedelta(minutes=cfg.TIME_WINDOW_MINUTES)
    t_end = t + timedelta(minutes=cfg.TIME_WINDOW_MINUTES)
    wind_rows = len(df_wind_sorted.filter((pl.col("time_utc") >= t_start) & (pl.col("time_utc") <= t_end)))
    loc_rows = len(df_loc_sorted.filter((pl.col("time_utc") >= t_start) & (pl.col("time_utc") <= t_end)))
    window_item = {
        "filename": fn,
        "time_start": t_start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "time_end": t_end.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "wind_rows": int(wind_rows),
        "loc_rows": int(loc_rows),
    }
    return radar_item, window_item


def main():
    parser = argparse.ArgumentParser(description="Stage1 clean source and radar index preparation.")
    parser.add_argument("--out-dir", default=os.path.join(cfg.BASE_DIR, "stage1_output"))
    parser.add_argument("--num-workers", type=int, default=1)
    args = parser.parse_args()
    num_workers = max(1, int(args.num_workers))
    out_dir = args.out_dir
    os.makedirs(out_dir, exist_ok=True)

    print(f"[Stage-1] 直接加载新 parquet 输入... workers={num_workers}")
    df_amdar, df_turb, df_loc = _load_new_inputs(num_workers)
    df_wind = pl.concat([
        _normalize_wind(df_amdar, source_hint="amdar").with_columns([
            pl.lit("amdar").alias("source"),
            pl.lit(float(cfg.SOURCE_CONFIDENCE.get("amdar", 1.0))).alias("obs_conf"),
        ]),
        _normalize_wind(df_turb, source_hint="turb").with_columns([
            pl.lit("turb").alias("source"),
            pl.lit(float(cfg.SOURCE_CONFIDENCE.get("turb", 0.9))).alias("obs_conf"),
        ]),
    ], how="diagonal_relaxed")
    df_loc = _normalize_loc(df_loc)
    df_wind = _annotate_wind_time_groups(_nullify_nonfinite_float_columns(df_wind))
    df_wind = _finalize_amdar_batch_fields(df_wind)
    df_loc = _nullify_nonfinite_float_columns(df_loc)

    print("[Stage-1] 保存清洗后的 parquet...")
    wind_path = os.path.join(out_dir, "clean_wind.parquet")
    loc_path = os.path.join(out_dir, "clean_loc.parquet")
    amdar_conservative_path = os.path.join(out_dir, "amdar_stage1_conservative.parquet")
    amdar_batch_statistics_path = os.path.join(out_dir, "amdar_batch_statistics.parquet")
    df_wind.write_parquet(wind_path)
    df_loc.write_parquet(loc_path)
    df_wind.filter(pl.col("source") == "amdar").write_parquet(amdar_conservative_path)
    (
        df_wind.filter(pl.col("source") == "amdar")
        .select(
            [
                "amdar_batch_id",
                "机尾号",
                "航班号",
                "飞行阶段",
                "amdar_batch_time_beijing",
                "amdar_batch_time_utc",
                "amdar_batch_row_count",
                "amdar_batch_raw_row_start",
                "amdar_batch_raw_row_end",
                "amdar_batch_is_contiguous",
                "amdar_batch_hspan_deg",
                "amdar_batch_vertical_span_m",
                "time_quality",
                "usage_role",
                "strict_time_truth",
                "time_is_point_observation",
            ]
        )
        .unique(subset=["amdar_batch_id"], maintain_order=True)
        .write_parquet(amdar_batch_statistics_path)
    )

    print("[Stage-1] 构建雷达索引...")
    radar_files = build_radar_files()

    loc_min_time = df_loc["time_utc"].min() if len(df_loc) > 0 else None
    loc_max_time = df_loc["time_utc"].max() if len(df_loc) > 0 else None

    radar_index = []
    frame_window_index = []

    df_wind_sorted = df_wind.sort("time_utc") if len(df_wind) > 0 else df_wind
    df_loc_sorted = df_loc.sort("time_utc") if len(df_loc) > 0 else df_loc

    jobs = [(rp, loc_min_time, loc_max_time, df_wind_sorted, df_loc_sorted) for rp in radar_files]
    workers = max(1, min(num_workers, len(jobs) or 1))
    if workers > 1:
        with ThreadPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(_radar_window_record, jobs))
    else:
        results = [_radar_window_record(job) for job in jobs]
    for result in results:
        if result is None:
            continue
        radar_item, window_item = result
        radar_index.append(radar_item)
        if window_item is not None:
            frame_window_index.append(window_item)

    with open(os.path.join(out_dir, "radar_index.json"), "w", encoding="utf-8") as f:
        json.dump(radar_index, f, ensure_ascii=False, indent=2)

    with open(os.path.join(out_dir, "frame_window_index.json"), "w", encoding="utf-8") as f:
        json.dump(frame_window_index, f, ensure_ascii=False, indent=2)

    summary = {
        "clean_wind_rows": int(len(df_wind)),
        "clean_loc_rows": int(len(df_loc)),
        "radar_total": int(len(radar_index)),
        "radar_usable": int(sum(1 for x in radar_index if x["usable"])),
        "window_records": int(len(frame_window_index)),
        "num_workers": int(num_workers),
        "parallel_mode": "thread_pool" if num_workers > 1 else "single_process",
        "wind_altitude_audit": {
            "overall": _altitude_audit(df_wind),
            "by_source": _altitude_audit(df_wind, group_col="source"),
        },
        "loc_altitude_audit": _altitude_audit(df_loc),
        "numeric_field_audit": {
            "wind_speed": _numeric_field_audit(df_wind, "wind_speed"),
            "ground_speed_ms": _numeric_field_audit(df_loc, "ground_speed_ms"),
            "u_motion": _numeric_field_audit(df_loc, "u_motion"),
            "v_motion": _numeric_field_audit(df_loc, "v_motion"),
        },
        "wind_time_group_alignment_flag_counts": _value_count_map(df_wind, "time_group_alignment_flag"),
        "wind_reconstruction_role_counts": _value_count_map(df_wind, "wind_reconstruction_role"),
        "wind_reconstruction_exclusion_reason_counts": _value_count_map(df_wind, "wind_reconstruction_exclusion_reason"),
        "wind_usage_role_counts": _value_count_map(df_wind, "usage_role"),
        "wind_time_quality_counts": _value_count_map(df_wind, "time_quality"),
        "wind_strict_time_truth_counts": _value_count_map(df_wind, "strict_time_truth"),
        "wind_obs_conf_audit": {
            "obs_conf": _numeric_field_audit(df_wind, "obs_conf"),
            "obs_conf_raw_for_reconstruction": _numeric_field_audit(df_wind, "obs_conf_raw_for_reconstruction"),
        },
        "amdar_reconstruction_policy": {
            "batched_same_timestamp_threshold_hspan_deg": float(AMDAR_BATCH_HSPAN_THRESHOLD_DEG),
            "batched_same_timestamp_support_confidence": float(AMDAR_BATCH_SUPPORT_CONFIDENCE),
            "strict_truth_role": "strict_truth_candidate",
            "support_only_role": "support_only_not_strict_truth",
            "support_only_exclusion_reason": "amdar_same_timestamp_duplicate_batch",
            "policy_note": "all duplicate same-timestamp AMDAR rows are treated as batch-like support fusion inputs only and are excluded from strict holdout truth candidates until per-point observation time can be recovered",
        },
        "amdar_time_semantics_policy": {
            "amdar_batch_time_semantics": "batch_time_unknown_exact_type",
            "default_strict_time_truth": False,
            "point_observation_time_available_by_default": False,
            "conservative_export": amdar_conservative_path,
            "batch_statistics_export": amdar_batch_statistics_path,
            "note": "The existing wind_reconstruction_role split is preserved for current Stage2/Stage4 official evaluation compatibility; strict_time_truth is a separate, more conservative time-semantics field for future migration.",
        },
    }
    with open(os.path.join(out_dir, "stage1_summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print("[Stage-1] 完成")
    print(summary)
    print(f"输出目录: {out_dir}")


if __name__ == "__main__":
    main()
