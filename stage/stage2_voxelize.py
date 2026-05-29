"""Stage 2：将 Stage 1 的清洗结果投影到雷达帧对应的三维体素网格。

Stage 2 的任务目标
------------------
1. 读取 Stage 1 输出的 clean_wind / clean_loc / radar_index / frame_window_index。
2. 针对每一帧雷达图，按照时间窗筛选对应的风观测与轨迹观测。
3. 将观测点投影到与雷达图像一致的 x/y 网格，并按照高度离散为 z。
4. 对同一体素内的观测做聚合，形成体素级风场、轨迹、运动约束数据。
5. 为 Stage 3 提供按帧组织好的 voxel npz 文件，以及汇总 json。

输出目录
--------
- stage2_output/voxels/*.npz
- stage2_output/stage2_summary.json
"""

import json
import os
import sys
from pathlib import Path
from datetime import datetime, timedelta

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import numpy as np
import polars as pl

import pipeline_config as cfg
from pipeline_utils import _read_gray_image_robust
from reconstruct_utils import _reconstruct_wind_field
from schema_contract import (
    STAGE2_AMDAR_RECORDS,
    STAGE2_FILENAME,
    STAGE2_FLIGHT_MOTION_RECORDS,
    STAGE2_FLIGHT_RAW_RECORDS,
    STAGE2_GRID_SHAPE,
    STAGE2_LOC_RECORDS,
    STAGE2_MOTION_RECORDS,
    STAGE2_RADAR_IMG,
    STAGE2_RADAR_SHAPE,
    STAGE2_TIMESTAMP_UTC,
    STAGE2_TIME_STR,
    STAGE2_TURB_RECORDS,
    STAGE2_WIND_RECORDS,
)


def load_stage1_outputs():
    """读取 Stage 1 输出文件。

    这里不再依赖 hello.py，而是直接读取 stage1_output 里的新 parquet 和索引文件。
    返回值包括：
    - df_wind: 风观测清洗表
    - df_loc: 轨迹观测清洗表
    - radar_index: 雷达帧元数据列表
    - frame_window_index: 每帧对应的时间窗索引（用于检查）
    """
    out_dir = os.path.join(cfg.BASE_DIR, "stage1_output")
    wind_path = os.path.join(out_dir, "clean_wind.parquet")
    loc_path = os.path.join(out_dir, "clean_loc.parquet")
    radar_index_path = os.path.join(out_dir, "radar_index.json")
    frame_window_index_path = os.path.join(out_dir, "frame_window_index.json")

    df_wind = pl.read_parquet(wind_path)
    df_loc = pl.read_parquet(loc_path)
    with open(radar_index_path, "r", encoding="utf-8") as f:
        radar_index = json.load(f)
    with open(frame_window_index_path, "r", encoding="utf-8") as f:
        frame_window_index = json.load(f)
    return df_wind, df_loc, radar_index, frame_window_index


def _df_to_records(df):
    """把 Polars DataFrame 转成可写入 npz 的普通 Python records。

    说明：
    - np.savez_compressed 不适合直接存 DataFrame
    - 下游 Stage 3 需要把这些 records 再恢复成 DataFrame
    - 空表返回空列表，避免后续读取时报错
    """
    if len(df) == 0:
        return []
    return df.to_dicts()


def voxelize_frame(df_wind, df_loc, radar_item):
    """针对单帧雷达图执行体素化。

    处理步骤：
    1. 读取雷达图，得到图像尺寸（H/W），作为 x/y 网格边界。
    2. 根据雷达时间构造一个时间窗，筛选 Stage 1 中对应时间段的风与轨迹观测。
    3. 将经纬度/高度离散为体素坐标 (x, y, z)。
    4. 对相同体素内的观测做聚合，得到风场、轨迹密度、轨迹运动量等。
    5. 把每帧结果写成 npz，并返回该帧的摘要信息。
    """
    radar_path = radar_item["radar_path"]
    fn = radar_item["filename"]
    ts = radar_item["time_str"]
    target_time = datetime.strptime(ts, "%Y%m%d%H%M%S")
    time_start = target_time - timedelta(minutes=cfg.TIME_WINDOW_MINUTES)
    time_end = target_time + timedelta(minutes=cfg.TIME_WINDOW_MINUTES)

    radar_img = _read_gray_image_robust(radar_path)
    if radar_img is None:
        return None

    H_DIM, W_DIM = radar_img.shape
    delta_lat = (cfg.LAT_MAX - cfg.LAT_MIN) / H_DIM
    delta_lon = (cfg.LON_MAX - cfg.LON_MIN) / W_DIM

    # ----------------------------
    # 风观测：时间窗筛选 + 地理投影 + 高度离散
    # ----------------------------
    wind_frame = df_wind.filter((pl.col("time_utc") >= time_start) & (pl.col("time_utc") <= time_end))
    wind_frame = wind_frame.with_columns([
        ((pl.col("lon_clean") - cfg.LON_MIN) / delta_lon).cast(pl.Int32).alias("x"),
        ((cfg.LAT_MAX - pl.col("lat_clean")) / delta_lat).cast(pl.Int32).alias("y"),
        ((pl.col("alt_meters") - cfg.ALT_MIN) / cfg.DELTA_ALT).cast(pl.Int32).alias("z"),
    ]).filter(
        (pl.col("x") >= 0) & (pl.col("x") < W_DIM) &
        (pl.col("y") >= 0) & (pl.col("y") < H_DIM) &
        (pl.col("z") >= 0) & (pl.col("z") < cfg.Z_DIM)
    )

    # ----------------------------
    # 轨迹观测：同样按时间窗和空间体素筛选
    # ----------------------------
    loc_frame = df_loc.filter((pl.col("time_utc") >= time_start) & (pl.col("time_utc") <= time_end))
    loc_frame = loc_frame.with_columns([
        ((pl.col("lon_clean") - cfg.LON_MIN) / delta_lon).cast(pl.Int32).alias("x"),
        ((cfg.LAT_MAX - pl.col("lat_clean")) / delta_lat).cast(pl.Int32).alias("y"),
        ((pl.col("alt_meters") - cfg.ALT_MIN) / cfg.DELTA_ALT).cast(pl.Int32).alias("z"),
    ]).filter(
        (pl.col("x") >= 0) & (pl.col("x") < W_DIM) &
        (pl.col("y") >= 0) & (pl.col("y") < H_DIM) &
        (pl.col("z") >= 0) & (pl.col("z") < cfg.Z_DIM)
    )

    # ----------------------------
    # 体素聚合：风场
    # ----------------------------
    wind_grouped = wind_frame.group_by(["z", "y", "x"]).agg([
        pl.col("u_wind").mean().alias("u"),
        pl.col("v_wind").mean().alias("v"),
        pl.len().alias("obs_count"),
        pl.col("obs_conf").mean().alias("obs_conf"),
    ])

    # ----------------------------
    # 体素聚合：轨迹密度 / 运动分量
    # ----------------------------
    loc_grouped = loc_frame.group_by(["z", "y", "x"]).agg(pl.len().alias("density"))
    loc_motion_grouped = loc_frame.drop_nulls(subset=["u_motion", "v_motion"]).group_by(["z", "y", "x"]).agg([
        pl.col("u_motion").mean().alias("u_motion"),
        pl.col("v_motion").mean().alias("v_motion"),
        pl.len().alias("motion_count"),
    ])
    flight_motion_grouped = loc_frame.drop_nulls(subset=["u_motion", "v_motion", "flight_id"]).group_by(["flight_id", "z", "y", "x"]).agg([
        pl.col("u_motion").mean().alias("u_motion"),
        pl.col("v_motion").mean().alias("v_motion"),
        pl.len().alias("motion_count"),
    ])

    # 原始航班记录，用于 Stage 3 构建智能体
    flight_raw_records = loc_frame.drop_nulls(subset=["u_motion", "v_motion", "flight_id", "time_utc", "lat_clean", "lon_clean", "alt_meters"])

    # AMDAR / TURB 分开保留，便于 Stage 3/4 更清楚地区分来源
    amdar_grouped = wind_frame.filter(pl.col("source") == "amdar").group_by(["z", "y", "x"]).agg([
        pl.col("u_wind").mean().alias("u"),
        pl.col("v_wind").mean().alias("v"),
    ])
    turb_grouped = wind_frame.filter(pl.col("source") == "turb").group_by(["z", "y", "x"]).agg([
        pl.col("u_wind").mean().alias("u"),
        pl.col("v_wind").mean().alias("v"),
    ])

    # ----------------------------
    # 输出 npz
    # ----------------------------
    vox_dir = os.path.join(cfg.BASE_DIR, "stage2_output", "voxels")
    os.makedirs(vox_dir, exist_ok=True)
    out_path = os.path.join(vox_dir, f"frame_{ts}_voxels.npz")
    np.savez_compressed(
        out_path,
        **{
            STAGE2_FILENAME: np.array(fn),
            STAGE2_TIME_STR: np.array(ts),
            STAGE2_TIMESTAMP_UTC: np.array(target_time.strftime("%Y-%m-%dT%H:%M:%SZ")),
            STAGE2_RADAR_SHAPE: np.array([H_DIM, W_DIM], dtype=np.int32),
            STAGE2_GRID_SHAPE: np.array([cfg.Z_DIM, H_DIM, W_DIM], dtype=np.int32),
            STAGE2_RADAR_IMG: radar_img,
            STAGE2_WIND_RECORDS: np.array(_df_to_records(wind_grouped), dtype=object),
            STAGE2_LOC_RECORDS: np.array(_df_to_records(loc_grouped), dtype=object),
            STAGE2_MOTION_RECORDS: np.array(_df_to_records(loc_motion_grouped), dtype=object),
            STAGE2_FLIGHT_MOTION_RECORDS: np.array(_df_to_records(flight_motion_grouped), dtype=object),
            STAGE2_FLIGHT_RAW_RECORDS: np.array(_df_to_records(flight_raw_records), dtype=object),
            STAGE2_AMDAR_RECORDS: np.array(_df_to_records(amdar_grouped), dtype=object),
            STAGE2_TURB_RECORDS: np.array(_df_to_records(turb_grouped), dtype=object),
        },
    )

    return {
        "filename": fn,
        "time_str": ts,
        "timestamp_utc": target_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "radar_shape": [H_DIM, W_DIM],
        "wind_grouped": wind_grouped,
        "loc_grouped": loc_grouped,
        "loc_motion_grouped": loc_motion_grouped,
        "flight_motion_grouped": flight_motion_grouped,
        "amdar_grouped": amdar_grouped,
        "turb_grouped": turb_grouped,
        "vox_path": out_path,
    }


def main():
    """Stage 2 主入口。

    执行流程：
    1. 读取 Stage 1 输出。
    2. 遍历所有可用雷达帧。
    3. 对每一帧执行 voxelize_frame。
    4. 汇总每帧的体素统计，写入 stage2_summary.json。
    """
    stage2_dir = os.path.join(cfg.BASE_DIR, "stage2_output")
    os.makedirs(stage2_dir, exist_ok=True)

    print("[Stage-2] 读取 Stage-1 中间结果...")
    df_wind, df_loc, radar_index, frame_window_index = load_stage1_outputs()

    # radar_index 中的 usable=True 才是需要进入体素化的帧。
    usable_frames = [x for x in radar_index if x.get("usable")]
    if cfg.MAX_FRAMES is not None:
        usable_frames = usable_frames[: cfg.MAX_FRAMES]
    print(f"[Stage-2] 可用雷达帧: {len(usable_frames)}")

    summary = []
    for i, item in enumerate(usable_frames, 1):
        out = voxelize_frame(df_wind, df_loc, item)
        if out is None:
            continue
        summary.append({
            "filename": out["filename"],
            "time_str": out["time_str"],
            "timestamp_utc": out["timestamp_utc"],
            "vox_path": out["vox_path"],
            "wind_voxels": int(len(out["wind_grouped"])),
            "traj_voxels": int(len(out["loc_grouped"])),
            "motion_voxels": int(len(out["loc_motion_grouped"])),
            "amdar_voxels": int(len(out["amdar_grouped"])),
            "turb_voxels": int(len(out["turb_grouped"])),
        })
        if i % 50 == 0 or i == len(usable_frames):
            print(f"[Stage-2] {i}/{len(usable_frames)} 完成")

    with open(os.path.join(stage2_dir, "stage2_summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print("[Stage-2] 完成")
    print(f"输出目录: {stage2_dir}")
    print(f"样本数: {len(summary)}")


if __name__ == "__main__":
    main()
