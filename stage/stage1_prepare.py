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
        if not os.path.isabs(p):
            p = os.path.join(parquet_dir, os.path.basename(p))
        shard_paths.append(p)
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


def _normalize_loc(df: pl.DataFrame) -> pl.DataFrame:
    parsed_time = None
    if "接收时间（UTC）" in df.columns:
        parsed_time = pl.col("接收时间（UTC）").cast(pl.Utf8, strict=False).str.strptime(pl.Datetime, strict=False)
    if "time_utc" in df.columns:
        df = df.with_columns(
            pl.coalesce([
                pl.col("time_utc").cast(pl.Datetime, strict=False),
                parsed_time if parsed_time is not None else pl.lit(None, dtype=pl.Datetime),
            ]).alias("time_utc")
        )
    elif parsed_time is not None:
        df = df.with_columns(parsed_time.alias("time_utc"))

    if "lat_clean" not in df.columns and "纬度_clean" in df.columns:
        df = df.with_columns(pl.col("纬度_clean").cast(pl.Float64, strict=False).alias("lat_clean"))
    if "lon_clean" not in df.columns and "经度_clean" in df.columns:
        df = df.with_columns(pl.col("经度_clean").cast(pl.Float64, strict=False).alias("lon_clean"))
    if "alt_meters" not in df.columns and "高度" in df.columns:
        df = df.with_columns(pl.col("高度").cast(pl.Float64, strict=False).alias("alt_meters"))
    if "heading_deg" not in df.columns and "航向角" in df.columns:
        df = df.with_columns(pl.col("航向角").cast(pl.Float64, strict=False).alias("heading_deg"))
    if "ground_speed_ms" not in df.columns and "地速" in df.columns:
        df = df.with_columns((pl.col("地速").cast(pl.Float64, strict=False) * cfg.GROUND_SPEED_TO_MPS).alias("ground_speed_ms"))
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
    if "u_motion" not in df.columns and "ground_speed_ms" in df.columns and "heading_deg" in df.columns:
        df = df.with_columns([
            (pl.col("ground_speed_ms") * (pl.col("heading_deg") * 3.141592653589793 / 180).sin()).alias("u_motion"),
            (pl.col("ground_speed_ms") * (pl.col("heading_deg") * 3.141592653589793 / 180).cos()).alias("v_motion"),
        ])
    return df


def _normalize_wind(df: pl.DataFrame) -> pl.DataFrame:
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
    if "lat_clean" not in df.columns and "纬度_clean" in df.columns:
        df = df.with_columns(pl.col("纬度_clean").cast(pl.Float64, strict=False).alias("lat_clean"))
    if "lon_clean" not in df.columns and "经度_clean" in df.columns:
        df = df.with_columns(pl.col("经度_clean").cast(pl.Float64, strict=False).alias("lon_clean"))
    if "alt_meters" not in df.columns and "高度" in df.columns:
        df = df.with_columns(pl.col("高度").cast(pl.Float64, strict=False).alias("alt_meters"))
    if "wind_dir" not in df.columns and "风向" in df.columns:
        df = df.with_columns(pl.col("风向").cast(pl.Float64, strict=False).alias("wind_dir"))
    if "wind_speed" not in df.columns and "风速" in df.columns:
        df = df.with_columns(pl.col("风速").cast(pl.Float64, strict=False).alias("wind_speed"))
    if "u_wind" not in df.columns and "wind_dir" in df.columns and "wind_speed" in df.columns:
        df = df.with_columns([
            (-pl.col("wind_speed") * (pl.col("wind_dir") * 3.141592653589793 / 180).sin()).alias("u_wind"),
            (-pl.col("wind_speed") * (pl.col("wind_dir") * 3.141592653589793 / 180).cos()).alias("v_wind"),
        ])
    return df


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
        _normalize_wind(df_amdar).with_columns([
            pl.lit("amdar").alias("source"),
            pl.lit(float(cfg.SOURCE_CONFIDENCE.get("amdar", 1.0))).alias("obs_conf"),
        ]),
        _normalize_wind(df_turb).with_columns([
            pl.lit("turb").alias("source"),
            pl.lit(float(cfg.SOURCE_CONFIDENCE.get("turb", 0.9))).alias("obs_conf"),
        ]),
    ], how="diagonal_relaxed")
    df_loc = _normalize_loc(df_loc)

    print("[Stage-1] 保存清洗后的 parquet...")
    wind_path = os.path.join(out_dir, "clean_wind.parquet")
    loc_path = os.path.join(out_dir, "clean_loc.parquet")
    df_wind.write_parquet(wind_path)
    df_loc.write_parquet(loc_path)

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
    }
    with open(os.path.join(out_dir, "stage1_summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print("[Stage-1] 完成")
    print(summary)
    print(f"输出目录: {out_dir}")


if __name__ == "__main__":
    main()
