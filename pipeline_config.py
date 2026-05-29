"""Project-level pipeline configuration.

This module is the single source of truth for the staged pipeline and does not
import `hello.py`.
"""

from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATASET_DATE = os.environ.get("WIND_DATASET_DATE", "20260224")
DATASET_ROOT = os.path.join(BASE_DIR, DATASET_DATE)


def _resolve_data_root() -> str:
    if os.path.isdir(DATASET_ROOT):
        return DATASET_ROOT
    return BASE_DIR


DATA_ROOT = _resolve_data_root()

# Spatial domain
LAT_MIN, LAT_MAX = 12.2, 54.2
LON_MIN, LON_MAX = 73.0, 135.0
ALT_MIN, ALT_MAX = 0, 15000
DELTA_ALT = 500
Z_DIM = int((ALT_MAX - ALT_MIN) / DELTA_ALT) + 1

# Temporal / radar settings
TIME_WINDOW_MINUTES = int(os.environ.get("WIND_TIME_WINDOW_MINUTES", "5"))
MAX_FRAMES = int(os.environ.get("WIND_MAX_FRAMES", "0")) or None
OVERLAP_ONLY = os.environ.get("WIND_OVERLAP_ONLY", "1") not in ("0", "false", "False")
RADAR_PATTERNS = [
    os.path.join("radar", "Z_RADA_*.png"),
    os.path.join("气象雷达拼图（UTC）", "Z_RADA_*.png"),
    "Z_RADA_*.png",
    os.path.join("**", "Z_RADA_*.png"),
]

# Stage-1 input parquet dirs
LOC_PARQUET_DIR = os.path.join(DATA_ROOT, "location_location_parquet")
AMDAR_PARQUET_DIR = os.path.join(DATA_ROOT, "amdar_parquet")
TURB_PARQUET_DIR = os.path.join(DATA_ROOT, "turb_parquet")

# Output root
OUTPUT_DIR = "dataset_output"
OUTPUT_DIR_ABS = os.path.join(BASE_DIR, OUTPUT_DIR)

# Motion / conversion
GROUND_SPEED_TO_MPS = 1000.0 / 3600.0
ALT_MULTIPLIER = 1.0
MAX_WIND_SPEED_MS = float(os.environ.get("WIND_MAX_WIND_SPEED_MS", "100.0"))
MAX_GROUND_SPEED_MS = float(os.environ.get("WIND_MAX_GROUND_SPEED_MS", "400.0"))
MIN_VALID_YEAR = int(os.environ.get("WIND_MIN_VALID_YEAR", "2000"))
MAX_VALID_YEAR = int(os.environ.get("WIND_MAX_VALID_YEAR", "2035"))

# Agent / communication settings
FLIGHT_AGENT_TOPK = int(os.environ.get("WIND_FLIGHT_AGENT_TOPK", "0"))
FLIGHT_TIER2_MAX = int(os.environ.get("WIND_FLIGHT_TIER2_MAX", "0"))
COMM_TIME_LIMIT_SECONDS = float(os.environ.get("WIND_COMM_TIME_LIMIT_SECONDS", "300"))
COMM_SPACE_LIMIT_KM = float(os.environ.get("WIND_COMM_SPACE_LIMIT_KM", "300"))
COMM_VERTICAL_LIMIT_M = float(os.environ.get("WIND_COMM_VERTICAL_LIMIT_M", "5000"))
FF_COMM_TIME_LIMIT_SECONDS = float(os.environ.get("WIND_FF_COMM_TIME_LIMIT_SECONDS", "120"))
FF_COMM_SPACE_LIMIT_KM = float(os.environ.get("WIND_FF_COMM_SPACE_LIMIT_KM", "200"))
FF_COMM_VERTICAL_LIMIT_M = float(os.environ.get("WIND_FF_COMM_VERTICAL_LIMIT_M", "2000"))
FLIGHT_PREFER_COMM_ELIGIBLE = os.environ.get("WIND_FLIGHT_PREFER_COMM_ELIGIBLE", "1") not in ("0", "false", "False")
COMM_ROUND = int(os.environ.get("WIND_COMM_ROUND", "1"))
FF_MAX_NEIGHBORS_PER_AGENT = int(os.environ.get("WIND_FF_MAX_NEIGHBORS", "12"))
PHYSICS_REALISM_MODE = os.environ.get("WIND_PHYSICS_REALISM_MODE", "1") not in ("0", "false", "False")

# Re-sampling / filtering
WIND_RESAMPLE_ENABLE = os.environ.get("WIND_RESAMPLE_ENABLE", "0") not in ("0", "false", "False")
WIND_RESAMPLE_ALPHA = float(os.environ.get("WIND_RESAMPLE_ALPHA", "0.5"))
WIND_RESAMPLE_MIN_REPEAT = int(os.environ.get("WIND_RESAMPLE_MIN_REPEAT", "1"))
WIND_RESAMPLE_MAX_REPEAT = int(os.environ.get("WIND_RESAMPLE_MAX_REPEAT", "8"))
FILTER_LOW_QUALITY_FOR_SPLIT = os.environ.get("WIND_FILTER_LOW_QUALITY_FOR_SPLIT", "1") not in ("0", "false", "False")
ADAPTIVE_MIN_OBS_ENABLE = os.environ.get("WIND_ADAPTIVE_MIN_OBS_ENABLE", "1") not in ("0", "false", "False")
ADAPTIVE_MIN_OBS_QUANTILE = float(os.environ.get("WIND_ADAPTIVE_MIN_OBS_QUANTILE", "0.25"))
ADAPTIVE_MIN_OBS_CAP = int(os.environ.get("WIND_ADAPTIVE_MIN_OBS_CAP", "8"))

# Source confidence
SOURCE_CONFIDENCE = {"amdar": 1.0, "turb": 0.9, "loc_motion": 0.7}

# Likelihood parameters
TIME_LIKELIHOOD_SIGMA_SECONDS = 360.0
SPACE_LIKELIHOOD_SIGMA_KM = 180.0
SPACE_LIKELIHOOD_SIGMA_Z_M = 2500.0
ADAPTIVE_SPACE_LIKELIHOOD = os.environ.get("WIND_ADAPTIVE_SPACE_LIKELIHOOD", "1") not in ("0", "false", "False")
COMM_WEIGHT_TIME_CONF = 0.35
COMM_WEIGHT_SPACE_CONF = 0.15
COMM_WEIGHT_TIME_LIKE = 0.25
COMM_WEIGHT_SPACE_LIKE = 0.25
COMM_WEIGHT_WIND_BONUS = 0.10
FF_SCORE_DEMAND_W = 0.45
FF_SCORE_CONF_W = 0.35
FF_SCORE_LIKE_W = 0.20

# Reconstruction parameters
RECON_ENABLE_IDW = os.environ.get("WIND_RECON_ENABLE_IDW", "1") not in ("0", "false", "False")
RECON_IDW_MAX_FILL = int(os.environ.get("WIND_RECON_IDW_MAX_FILL", "4000"))


def _haversine_km(lat1, lon1, lat2, lon2):
    import math
    r = 6371.0
    p1 = math.radians(float(lat1))
    p2 = math.radians(float(lat2))
    dphi = math.radians(float(lat2) - float(lat1))
    dlambda = math.radians(float(lon2) - float(lon1))
    a = math.sin(dphi / 2.0) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2.0) ** 2
    return 2.0 * r * math.asin(min(1.0, math.sqrt(a)))


def _eval_agent_geo(flight_frame, flight_id, target_time):
    """Estimate one flight agent's representative geospatial state.

    返回值必须是 5 元组：
    (lat, lon, alt, t_mid, dt_sec)

    这个函数的目标不是找到“航班真实轨迹的精确点”，而是找到
    “对当前雷达帧最有代表性的飞行状态”。因此这里的估计策略分三层：

    1. 首先在该 flight_id 的记录中，挑选时间最接近 target_time 的点；
    2. 如果时间字段不可解析，则退化到该 flight 的稳健空间中位数；
    3. 整个过程禁止依赖 pyarrow，以免在轻量环境里因为 to_pandas() 失败。

    说明：
    - flight_frame: Stage 2 提供的 flight_raw_records / flight_motion_grouped
    - flight_id: 需要评估的航班号/机尾号
    - target_time: 当前雷达帧对应的时间点
    """
    import datetime as _dt

    if flight_frame is None or len(flight_frame) == 0:
        return None

    try:
        import polars as pl  # type: ignore
    except Exception:
        return None

    fid = str(flight_id)
    if "flight_id" not in flight_frame.columns:
        return None

    one = flight_frame.filter(pl.col("flight_id").cast(pl.Utf8, strict=False) == fid)
    if len(one) == 0:
        return None

    def _as_float_series(frame, col):
        if col not in frame.columns:
            return []
        try:
            vals = frame.get_column(col).cast(pl.Float64, strict=False).to_list()
            return [float(v) for v in vals if v is not None]
        except Exception:
            return []

    def _parse_dt(v):
        if v is None:
            return None
        if isinstance(v, _dt.datetime):
            return v
        s = str(v).strip()
        if not s:
            return None
        # 常见格式做宽容解析，尽量避免因为脏值导致全列失效。
        for fmt in (
            "%Y-%m-%d %H:%M:%S",
            "%Y/%m/%d %H:%M:%S",
            "%Y%m%d%H%M%S",
            "%Y-%m-%dT%H:%M:%S",
            "%Y-%m-%dT%H:%M:%S.%f",
        ):
            try:
                return _dt.datetime.strptime(s[: len(fmt.replace('%Y', 'YYYY'))], fmt)
            except Exception:
                pass
        try:
            from dateutil import parser as _parser  # type: ignore
            return _parser.parse(s)
        except Exception:
            return None

    # 1) 先尝试用时间字段找最近点
    time_col = None
    for c in ["time_utc", "time_beijing"]:
        if c in one.columns:
            time_col = c
            break

    if time_col is not None:
        try:
            times = one.get_column(time_col).to_list()
            lats = _as_float_series(one, "lat_clean")
            lons = _as_float_series(one, "lon_clean")
            alts = _as_float_series(one, "alt_meters")
            n = min(len(times), len(lats), len(lons), len(alts))
            best = None
            for i in range(n):
                t = _parse_dt(times[i])
                if t is None:
                    continue
                dt_sec = abs((t - target_time).total_seconds())
                cand = (dt_sec, lats[i], lons[i], alts[i], t)
                if best is None or cand[0] < best[0]:
                    best = cand
            if best is not None:
                dt_sec, lat, lon, alt, t_mid = best
                return float(lat), float(lon), float(alt), t_mid, float(dt_sec)
        except Exception:
            pass

    # 2) 时间解析失败时，退化到几何中位数
    lats = _as_float_series(one, "lat_clean")
    lons = _as_float_series(one, "lon_clean")
    alts = _as_float_series(one, "alt_meters")
    if not lats or not lons or not alts:
        return None

    import numpy as np
    return float(np.median(lats)), float(np.median(lons)), float(np.median(alts)), target_time, 0.0


def _linear_conf(x, limit=None):
    """线性置信度函数。

    兼容两种调用方式：
    1. _linear_conf(score)
       - 直接把值裁剪到 [0, 1]
    2. _linear_conf(x, limit)
       - 将 x 归一化为 1 - x/limit 的形式，再裁剪到 [0, 1]

    这样可以同时兼容 agent_builder 里单参数/双参数的调用风格。
    """
    try:
        v = float(x)
    except Exception:
        return 0.0

    if limit is not None:
        try:
            lim = float(limit)
        except Exception:
            lim = 1.0
        if lim <= 0:
            return 0.0
        v = 1.0 - (v / lim)

    return max(0.0, min(1.0, v))


def _time_likelihood(dt_seconds):
    import math
    sigma = max(1.0, TIME_LIKELIHOOD_SIGMA_SECONDS)
    x = float(dt_seconds) / sigma
    return float(math.exp(-0.5 * x * x))


def _space_likelihood(h_km, v_m):
    import math
    sx = max(1e-6, SPACE_LIKELIHOOD_SIGMA_KM)
    sz = max(1e-6, SPACE_LIKELIHOOD_SIGMA_Z_M)
    x = float(h_km) / sx
    z = float(v_m) / sz
    return float(math.exp(-0.5 * (x * x + z * z)))


def _blend_comm_weight(time_conf, space_conf, time_like, space_like, wind_bonus=0.0):
    score = (
        COMM_WEIGHT_TIME_CONF * float(time_conf)
        + COMM_WEIGHT_SPACE_CONF * float(space_conf)
        + COMM_WEIGHT_TIME_LIKE * float(time_like)
        + COMM_WEIGHT_SPACE_LIKE * float(space_like)
        + COMM_WEIGHT_WIND_BONUS * float(wind_bonus)
    )
    return max(0.0, min(1.0, score))


def _compute_flight_intent(flight_frame, flight_id):
    """Compute a light-weight flight intent vector.

    这是一个简化版意图向量，用于 Stage 3/4 的结构占位与下游训练输入：
    - [0] 低空/近地趋势
    - [1] 中等高度巡航趋势
    - [2] 高空巡航趋势

    这里根据航班的中位高度做一个粗分类，返回长度为 3 的列表。
    如果没有可用高度，则返回全 0。
    """
    try:
        import polars as pl  # type: ignore
    except Exception:
        return [0.0, 0.0, 0.0]

    if flight_frame is None or len(flight_frame) == 0 or "flight_id" not in flight_frame.columns:
        return [0.0, 0.0, 0.0]

    fid = str(flight_id)
    one = flight_frame.filter(pl.col("flight_id").cast(pl.Utf8, strict=False) == fid)
    if len(one) == 0 or "alt_meters" not in one.columns:
        return [0.0, 0.0, 0.0]

    alt = one.select(pl.col("alt_meters").cast(pl.Float64, strict=False)).drop_nulls()
    if len(alt) == 0:
        return [0.0, 0.0, 0.0]

    med_alt = float(alt["alt_meters"].median())
    if med_alt < 4000:
        return [1.0, 0.0, 0.0]
    if med_alt < 9000:
        return [0.0, 1.0, 0.0]
    return [0.0, 0.0, 1.0]


def _ff_demand_score(*args, **kwargs):
    return 0.0


def _ff_edge_score(*args, **kwargs):
    return 0.0


def _zyx_to_linear_idx(z, y, x, h_dim, w_dim):
    import numpy as np
    z = np.asarray(z, dtype=np.int64)
    y = np.asarray(y, dtype=np.int64)
    x = np.asarray(x, dtype=np.int64)
    return (z * int(h_dim) * int(w_dim) + y * int(w_dim) + x).astype(np.uint32, copy=False)
