"""Stage 3：基于 Stage 2 的体素结果构建飞行智能体与通信关系。

Stage 3 的任务目标
------------------
1. 读取 Stage 2 生成的每帧 voxel npz 与 stage2_summary.json。
2. 还原体素聚合后的风观测、轨迹观测、运动观测。
3. 基于轨迹/运动信息构建 flight agents。
4. 计算通信可达性、空空关系、风观测关系。
5. 输出每帧的 agents JSON 和 stage3_summary.json，供 Stage 4 继续使用。

输出目录
--------
- stage3_output/agents/*.json
- stage3_output/stage3_summary.json
"""

import json
import os
import sys
import time
from pathlib import Path
from datetime import datetime

ROOT_DIR = Path(__file__).resolve().parent.parent
STAGE_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
if str(STAGE_DIR) not in sys.path:
    sys.path.insert(0, str(STAGE_DIR))

import numpy as np
import polars as pl

import pipeline_config as cfg
from stage.agent_builder import build_flight_agents_sparse
from stage.communication_builder import select_ff_edges
from stage.pipeline_utils import (
    _compute_flight_intent,
    _eval_agent_geo,
    _ff_demand_score,
    _ff_edge_score,
    _haversine_km,
    _linear_conf,
    _space_likelihood,
    _time_likelihood,
    _zyx_to_linear_idx,
)
from schema_contract import (
    FLIGHT_COMM_ALLOWED,
    FLIGHT_FF_COMM_ALLOWED,
    FLIGHT_FF_MOTION_ALLOWED,
    FLIGHT_FF_WIND_ALLOWED,
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
    STAGE3_CANDIDATE_FLIGHT_COUNT,
    STAGE3_FLIGHT_COMM_ALLOWED_AGENTS,
    STAGE3_FLIGHT_FF_ALLOWED_EDGES,
    STAGE3_FLIGHT_FF_MOTION_EDGES,
    STAGE3_FLIGHT_FF_WIND_EDGES,
    STAGE3_TIER1_CANDIDATE_COUNT,
    STAGE3_TIER2_CANDIDATE_COUNT,
    STAGE3_VALID_FLIGHT_AGENTS,
    STAGE3_VALID_WIND_CAPABLE_FLIGHTS,
)


def _linear_idx_from_df(df, h_dim, w_dim):
    if df is None or len(df) == 0 or not {"z", "y", "x"}.issubset(set(df.columns)):
        return np.array([], dtype=np.int64)
    z = df["z"].cast(pl.Int64, strict=False).to_numpy()
    y = df["y"].cast(pl.Int64, strict=False).to_numpy()
    x = df["x"].cast(pl.Int64, strict=False).to_numpy()
    return (z * int(h_dim) * int(w_dim) + y * int(w_dim) + x).astype(np.int64, copy=False)


def _linear_to_zyx(idx, h_dim, w_dim):
    idx = np.asarray(idx, dtype=np.int64)
    if idx.size == 0:
        return (
            np.array([], dtype=np.int32),
            np.array([], dtype=np.int32),
            np.array([], dtype=np.int32),
        )
    z = (idx // (h_dim * w_dim)).astype(np.int32, copy=False)
    rem = idx % (h_dim * w_dim)
    y = (rem // w_dim).astype(np.int32, copy=False)
    x = (rem % w_dim).astype(np.int32, copy=False)
    return z, y, x


def _expand_linear_support(linear_idx, grid_shape, radius_xy=1, radius_z=1):
    if linear_idx is None or len(linear_idx) == 0:
        return set()
    z_dim, h_dim, w_dim = [int(v) for v in grid_shape]
    expanded = set()
    for idx in np.asarray(linear_idx, dtype=np.int64):
        z = int(idx // (h_dim * w_dim))
        rem = int(idx % (h_dim * w_dim))
        y = int(rem // w_dim)
        x = int(rem % w_dim)
        for dz in range(-radius_z, radius_z + 1):
            zz = z + dz
            if zz < 0 or zz >= z_dim:
                continue
            for dy in range(-radius_xy, radius_xy + 1):
                yy = y + dy
                if yy < 0 or yy >= h_dim:
                    continue
                for dx in range(-radius_xy, radius_xy + 1):
                    xx = x + dx
                    if xx < 0 or xx >= w_dim:
                        continue
                    expanded.add(int(zz * h_dim * w_dim + yy * w_dim + xx))
    return expanded


# [改动说明] 这里是 Stage-3 最核心的风能力激活增强：
# 由“硬重叠”改成“direct + near + geo + soft”四层证据链，
# 用来避免 valid_wind_capable_flights / wind_edges 全 0。
def _refine_flight_pack_with_wind_support(vox, flight_pack, h_dim, w_dim):
    """用风体素邻域和软支撑重算 flight 的风能力。

    物理上更理想的情况当然是“飞行体轨迹体素直接与风体素重叠”，
    但在当前数据里风观测非常稀疏，这种 direct hit 往往长期为 0。

    因此这里采用四层逐步放宽的证据链：

    1. direct：直接命中风体素；
    2. near：命中风体素邻域；
    3. geo：与风体素簇在几何中心上足够接近；
    4. soft：虽然没命中，但时空似然和通信权重足够支持其作为风能力节点。

    这样做的目的不是“无条件放松”，而是避免 Stage-3 出现
    `valid_wind_capable=0 / wind_edges=0` 的全灭情况。
    """
    if not flight_pack or int(flight_pack.get("valid_flight_agents", 0)) <= 0:
        return flight_pack

    support_idx = np.concatenate(
        [
            _linear_idx_from_df(vox.get("wind_grouped"), h_dim, w_dim),
            _linear_idx_from_df(vox.get("amdar_grouped"), h_dim, w_dim),
            _linear_idx_from_df(vox.get("turb_grouped"), h_dim, w_dim),
        ]
    )
    if support_idx.size == 0:
        return flight_pack

    support_direct = set(int(x) for x in support_idx.tolist())
    support_near = _expand_linear_support(support_idx, vox["grid_shape"], radius_xy=4, radius_z=2)
    support_z, support_y, support_x = _linear_to_zyx(support_idx, h_dim, w_dim)

    ids = np.asarray(flight_pack.get("flight_agent_ids", []))
    offsets = np.asarray(flight_pack.get("flight_offsets", []), dtype=np.int64)
    idx_flat = np.asarray(flight_pack.get("flight_idx_flat", []), dtype=np.int64)
    mask = np.asarray(flight_pack.get("flight_mask", []), dtype=np.uint8)
    st_like = np.asarray(flight_pack.get("flight_st_likelihood", []), dtype=np.float32)
    comm_weight = np.asarray(flight_pack.get("flight_comm_weight", []), dtype=np.float32)

    if ids.size == 0 or offsets.size != ids.size + 1:
        return flight_pack

    refined_has_wind = np.asarray(flight_pack.get("flight_has_wind_obs", np.zeros(ids.size, dtype=np.float32)), dtype=np.float32).copy()
    support_scores = np.zeros(ids.size, dtype=np.float32)
    direct_hits = 0
    near_hits = 0
    soft_hits = 0
    geo_hits = 0

    for i in range(ids.size):
        if i >= mask.size or mask[i] <= 0:
            continue
        sl = slice(int(offsets[i]), int(offsets[i + 1]))
        own_idx = idx_flat[sl]
        if own_idx.size == 0:
            continue
        direct = sum(1 for x in own_idx if int(x) in support_direct)
        near = sum(1 for x in own_idx if int(x) in support_near)
        own_n = float(max(1, own_idx.size))
        direct_ratio = float(direct / own_n)
        near_ratio = float(near / own_n)
        own_z, own_y, own_x = _linear_to_zyx(own_idx, h_dim, w_dim)
        geo_score = 0.0
        if own_idx.size > 0 and support_idx.size > 0:
            cz = float(np.median(own_z))
            cy = float(np.median(own_y))
            cx = float(np.median(own_x))
            dz = np.abs(support_z.astype(np.float32) - cz)
            dxy = np.sqrt((support_y.astype(np.float32) - cy) ** 2 + (support_x.astype(np.float32) - cx) ** 2)
            min_z = float(np.min(dz))
            min_xy = float(np.min(dxy))
            geo_score = float(
                max(0.0, 1.0 - min_xy / 8.0) *
                max(0.0, 1.0 - min_z / 3.0)
            )
        soft_score = 0.35 * near_ratio
        if i < st_like.size:
            soft_score += 0.40 * float(st_like[i])
        if i < comm_weight.size:
            soft_score += 0.25 * float(comm_weight[i])
        support_score = max(direct_ratio, 0.75 * near_ratio, 0.85 * geo_score, soft_score)
        support_scores[i] = support_score
        if direct_ratio > 0.0:
            direct_hits += 1
        elif near_ratio > 0.0:
            near_hits += 1
        elif geo_score >= 0.12:
            geo_hits += 1
        elif support_score >= 0.18:
            soft_hits += 1

        refined_has_wind[i] = 1.0 if (
            direct_ratio > 0.0
            or near_ratio >= 0.08
            or geo_score >= 0.12
            or support_score >= 0.18
        ) else 0.0

    ff_comm_allowed = np.asarray(flight_pack.get("ff_comm_allowed", []), dtype=np.float32)
    ff_comm_weight = np.asarray(flight_pack.get("ff_comm_weight", []), dtype=np.float32)
    ff_wind_allowed = np.zeros_like(ff_comm_allowed, dtype=np.float32)
    ff_wind_weight = np.zeros_like(ff_comm_weight, dtype=np.float32)
    if ff_comm_allowed.ndim == 2 and ff_comm_weight.ndim == 2:
        n_slots = ff_comm_allowed.shape[0]
        for i in range(n_slots):
            if i >= refined_has_wind.size or refined_has_wind[i] <= 0:
                continue
            for j in range(n_slots):
                if i == j or j >= refined_has_wind.size or ff_comm_allowed[i, j] <= 0:
                    continue
                both = 1.0 if (refined_has_wind[i] > 0 and refined_has_wind[j] > 0) else 0.0
                one = 1.0 if ((refined_has_wind[i] > 0) ^ (refined_has_wind[j] > 0)) else 0.0
                gate = both + 0.5 * one
                ff_wind_allowed[i, j] = gate
                ff_wind_weight[i, j] = ff_comm_weight[i, j] * gate

    flight_pack["flight_has_wind_obs"] = refined_has_wind
    flight_pack["flight_wind_support_score"] = support_scores
    if ff_comm_allowed.ndim == 2:
        flight_pack["ff_wind_allowed"] = ff_wind_allowed
        flight_pack["ff_wind_weight"] = ff_wind_weight
        flight_pack["ff_wind_edges"] = int(np.sum(ff_wind_allowed > 0.0))
    flight_pack["valid_wind_capable_flights"] = int(np.sum(refined_has_wind > 0.0))
    flight_pack["wind_support_direct_hits"] = int(direct_hits)
    flight_pack["wind_support_near_hits"] = int(near_hits)
    flight_pack["wind_support_geo_hits"] = int(geo_hits)
    flight_pack["wind_support_soft_hits"] = int(soft_hits)
    if support_scores.size > 0:
        flight_pack["wind_support_score_p50"] = float(np.percentile(support_scores, 50))
        flight_pack["wind_support_score_p90"] = float(np.percentile(support_scores, 90))
    print(
        f"[Stage-3][wind] frame={vox['time_str']} direct={direct_hits} near={near_hits} "
        f"geo={geo_hits} soft={soft_hits} valid_wind_capable={flight_pack['valid_wind_capable_flights']}"
    )
    return flight_pack


# [改动说明] 这里补入 source_index，便于后续 Stage-3 / Stage-4 / 日志统一回溯原始帧下标。
def load_stage2_voxel(frame_item):
    """读取单帧 Stage 2 输出并恢复为可处理的数据结构。

    这里做两件事：
    1. 读取 npz 中的固定 key。
    2. 将其中的 records 恢复为 Polars DataFrame，便于后续 agent 构建。

    注意：
    - 这里的字段名必须和 schema_contract.py 中定义的一致。
    - 如果某类 records 为空，则返回空 DataFrame，避免下游报错。
    """
    vox_path = frame_item["vox_path"]
    data = np.load(vox_path, allow_pickle=True)
    return {
        "filename": str(data[STAGE2_FILENAME]),
        "source_index": int(frame_item.get("source_index", -1)),
        "time_str": str(data[STAGE2_TIME_STR]),
        "timestamp_utc": str(data[STAGE2_TIMESTAMP_UTC]),
        "radar_shape": data[STAGE2_RADAR_SHAPE].tolist(),
        "grid_shape": data[STAGE2_GRID_SHAPE].tolist(),
        "wind_grouped": pl.DataFrame(data[STAGE2_WIND_RECORDS].tolist()) if len(data[STAGE2_WIND_RECORDS]) else pl.DataFrame(),
        "loc_grouped": pl.DataFrame(data[STAGE2_LOC_RECORDS].tolist()) if len(data[STAGE2_LOC_RECORDS]) else pl.DataFrame(),
        "loc_motion_grouped": pl.DataFrame(data[STAGE2_MOTION_RECORDS].tolist()) if len(data[STAGE2_MOTION_RECORDS]) else pl.DataFrame(),
        "flight_motion_grouped": pl.DataFrame(data[STAGE2_FLIGHT_MOTION_RECORDS].tolist()) if len(data[STAGE2_FLIGHT_MOTION_RECORDS]) else pl.DataFrame(),
        "flight_raw_records": pl.DataFrame(data[STAGE2_FLIGHT_RAW_RECORDS].tolist()) if len(data[STAGE2_FLIGHT_RAW_RECORDS]) else pl.DataFrame(),
        "amdar_grouped": pl.DataFrame(data[STAGE2_AMDAR_RECORDS].tolist()) if len(data[STAGE2_AMDAR_RECORDS]) else pl.DataFrame(),
        "turb_grouped": pl.DataFrame(data[STAGE2_TURB_RECORDS].tolist()) if len(data[STAGE2_TURB_RECORDS]) else pl.DataFrame(),
    }


def _safe_float_series(df, col):
    """把 Polars 列稳健地转成 float64 numpy 数组。

    说明：
    - 不依赖 pyarrow，不走 `to_pandas()`，避免轻量环境中额外依赖失败。
    - 会自动忽略空值和无法转成数字的值。
    """
    if df is None or len(df) == 0 or col not in df.columns:
        return np.array([], dtype=np.float64)
    try:
        return np.asarray(df.get_column(col).cast(pl.Float64, strict=False).drop_nulls().to_list(), dtype=np.float64)
    except Exception:
        return np.array([], dtype=np.float64)


def _robust_center(values):
    """计算鲁棒中心：中位数 + 截尾均值的组合。

    目的：
    - 中位数抗离群点；
    - 截尾均值在样本量足够时更平滑；
    - 这里用于动态 ground 估计，避免少数极端航班把参考点拉偏。
    """
    arr = np.asarray(values, dtype=np.float64)
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        return float("nan")
    if arr.size < 5:
        return float(np.median(arr))
    lo = np.percentile(arr, 10)
    hi = np.percentile(arr, 90)
    trimmed = arr[(arr >= lo) & (arr <= hi)]
    if trimmed.size == 0:
        trimmed = arr
    return float(0.5 * np.median(arr) + 0.5 * np.mean(trimmed))


def _weighted_center(values, weights):
    """计算按权重加权的中心。"""
    values = np.asarray(values, dtype=np.float64)
    weights = np.asarray(weights, dtype=np.float64)
    keep = np.isfinite(values) & np.isfinite(weights) & (weights > 0)
    if not np.any(keep):
        return float("nan")
    values = values[keep]
    weights = weights[keep]
    order = np.argsort(values)
    values = values[order]
    weights = weights[order]
    cdf = np.cumsum(weights) / np.sum(weights)
    return float(values[np.searchsorted(cdf, 0.5, side="left")])


def _weighted_center_by_flight(flight_frame, value_col):
    if (
        flight_frame is None
        or len(flight_frame) == 0
        or "flight_id" not in flight_frame.columns
        or value_col not in flight_frame.columns
    ):
        return float("nan")
    try:
        grouped = (
            flight_frame
            .drop_nulls(subset=["flight_id", value_col])
            .group_by("flight_id")
            .agg(
                pl.col(value_col).cast(pl.Float64, strict=False).median().alias("center_value"),
                pl.len().alias("obs_n"),
            )
        )
        if len(grouped) == 0:
            return float("nan")
        values = np.asarray(grouped["center_value"].to_list(), dtype=np.float64)
        weights = np.asarray(grouped["obs_n"].to_list(), dtype=np.float64)
        return _weighted_center(values, weights)
    except Exception:
        return float("nan")


def _count_positive_entries(values, threshold=0.0):
    arr = np.asarray(values, dtype=np.float32)
    if arr.size == 0:
        return 0
    return int(np.sum(arr > float(threshold)))


def _format_duration(seconds):
    """把秒数格式化成更适合日志阅读的字符串。"""
    seconds = max(0.0, float(seconds))
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, sec = divmod(int(round(seconds)), 60)
    if minutes < 60:
        return f"{minutes}m{sec:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h{minutes:02d}m{sec:02d}s"


# [改动说明] 新增文本进度条，适配服务器日志重定向场景。
def _print_stage_progress(stage_name, done, total, t_start, frame_item=None):
    """打印适合终端和日志文件查看的文本进度条。

    这里不使用依赖库版 progress bar，原因有两个：
    1. 服务器环境不一定预装 tqdm；
    2. 当前脚本经常重定向到日志文件，简单的单行覆盖进度条在日志里不易读。

    因此采用“周期性输出一整行”的方式，既能在终端里看，也能在 log 中追踪。
    """
    total = max(1, int(total))
    done = int(done)
    elapsed = max(1e-6, time.perf_counter() - t_start)
    speed = done / elapsed
    remain = max(0, total - done)
    eta = remain / max(1e-6, speed)
    ratio = min(1.0, max(0.0, done / total))
    bar_len = 24
    filled = int(round(ratio * bar_len))
    bar = "#" * filled + "-" * (bar_len - filled)
    suffix = ""
    if frame_item:
        suffix = (
            f" idx={frame_item.get('source_index', -1)}"
            f" time={frame_item.get('time_str', '?')}"
        )
    print(
        f"[{stage_name}][progress] [{bar}] "
        f"{done}/{total} ({ratio * 100:6.2f}%) "
        f"elapsed={_format_duration(elapsed)} "
        f"eta={_format_duration(eta)} "
        f"fps={speed:.2f}{suffix}"
    )


# [改动说明] 新增统一选帧逻辑：
# 支持 first3 / offset / 精确下标抽帧，方便调试与高风帧验证。
def _select_stage2_frames(stage2_summary):
    """根据环境变量选择要处理的 Stage-2 帧。

    这个辅助函数主要服务于两类调试场景：

    1. 连续小批量调试：
       - `WIND_FRAME_OFFSET=300`
       - `WIND_MAX_FRAMES=3`
       适合快速跳过最前面的低风帧。

    2. 精确抽取高风帧：
       - `WIND_FRAME_INDICES=3769,3338,3425`
       适合直接从 `stage2_topwind.log` 里挑出代表性帧做验证。

    返回结果仍是原来的 frame-item 字典列表，但会额外补一个 `source_index`
    字段，方便 Stage-3 / Stage-4 的 summary 和日志回溯原始帧位置。
    """
    indexed = []
    for idx, item in enumerate(stage2_summary):
        one = dict(item)
        one["source_index"] = idx
        indexed.append(one)

    indices_env = os.environ.get("WIND_FRAME_INDICES", "").strip()
    if indices_env:
        selected = []
        bad_tokens = []
        for token in indices_env.split(","):
            token = token.strip()
            if not token:
                continue
            try:
                src_idx = int(token)
            except ValueError:
                bad_tokens.append(token)
                continue
            if 0 <= src_idx < len(indexed):
                selected.append(dict(indexed[src_idx]))
            else:
                bad_tokens.append(token)
        if bad_tokens:
            print(f"[Stage-3][WARN] 忽略非法 WIND_FRAME_INDICES 项: {bad_tokens}")
        # 精确抽帧时仍按原始 source_index 排序，保证时序分析和日志阅读是一致的。
        selected = sorted(selected, key=lambda x: int(x.get("source_index", -1)))
        print(f"[Stage-3] 按精确下标选帧: {[x['source_index'] for x in selected]}")
        return selected

    frame_offset = max(0, int(os.environ.get("WIND_FRAME_OFFSET", "0") or "0"))
    if frame_offset > 0:
        indexed = indexed[frame_offset:]
        print(f"[Stage-3] 跳过前 {frame_offset} 帧")

    if cfg.MAX_FRAMES is not None:
        indexed = indexed[: cfg.MAX_FRAMES]
    return indexed


def _estimate_ground_from_frame(vox, flight_frame):
    """基于当前帧航班分布动态估计 ground 参考点。

    这里不是在推断“真实雷达中心”，而是在估计一个更符合当前帧
    观测分布的虚拟参考点。这样做的好处是：
    1. 避免固定域中心把所有航班拉到几百/上千公里外；
    2. 让空间似然和通信筛选对当前帧更敏感；
    3. 仍然保留物理约束，不会把参考点设到离群位置。

    估计策略：
    - 先用 flight_raw_records 的经纬高样本做鲁棒中心；
    - 再用各 flight 的观测数做一次加权中心；
    - 对离群点先做粗过滤，再融合 voxel 级分布；
    - 高度优先用分位数稳态值，避免被极低/极高值带偏。
    """
    lat_arr = _safe_float_series(flight_frame, "lat_clean")
    lon_arr = _safe_float_series(flight_frame, "lon_clean")
    alt_arr = _safe_float_series(flight_frame, "alt_meters")

    voxel_lat = np.array([], dtype=np.float64)
    voxel_lon = np.array([], dtype=np.float64)
    voxel_alt = np.array([], dtype=np.float64)
    if vox.get("flight_motion_grouped") is not None and len(vox["flight_motion_grouped"]) > 0:
        voxel_lat = _safe_float_series(vox["flight_motion_grouped"], "lat_clean")
        voxel_lon = _safe_float_series(vox["flight_motion_grouped"], "lon_clean")
        voxel_alt = _safe_float_series(vox["flight_motion_grouped"], "alt_meters")

    lat = _robust_center(lat_arr)
    lon = _robust_center(lon_arr)
    alt = _robust_center(alt_arr)

    # 用 flight_id 的观测数作为权重，给“更稳定、更密集”的航班更高影响。
    if flight_frame is not None and len(flight_frame) > 0 and "flight_id" in flight_frame.columns:
        try:
            lat_w = _weighted_center_by_flight(flight_frame, "lat_clean")
            lon_w = _weighted_center_by_flight(flight_frame, "lon_clean")
            alt_w = _weighted_center_by_flight(flight_frame, "alt_meters")
            # 用 flight 级中心再做一次按观测数加权，避免高频单机样本或离群点主导参考点。
            if np.isfinite(lat_w):
                lat = 0.5 * lat + 0.5 * lat_w
            if np.isfinite(lon_w):
                lon = 0.5 * lon + 0.5 * lon_w
            if np.isfinite(alt_w):
                alt = 0.5 * alt + 0.5 * alt_w
        except Exception:
            pass

    # 如果 voxel 级样本更“平滑”，就向 voxel 中心轻微回拉。
    if voxel_lat.size > 0 and voxel_lon.size > 0:
        lat = 0.65 * lat + 0.35 * _robust_center(voxel_lat)
        lon = 0.65 * lon + 0.35 * _robust_center(voxel_lon)
    if voxel_alt.size > 0:
        alt = 0.7 * alt + 0.3 * _robust_center(voxel_alt)

    # 最后做一次物理边界裁剪，避免参考点跑到有效域外。
    lat = float(np.clip(lat, cfg.LAT_MIN, cfg.LAT_MAX))
    lon = float(np.clip(lon, cfg.LON_MIN, cfg.LON_MAX))
    alt = float(np.clip(alt, cfg.ALT_MIN, cfg.ALT_MAX))
    return lat, lon, alt


def _diag_frame_distribution(vox, ground_lat, ground_lon, ground_alt, flight_pack=None):
    """输出每帧 ground 点、flight 分布中心和空间似然分布。

    新版诊断还会输出“几何可达”与“高置信候选”的拆分结果，便于判断：
    - 是否是几何距离过大导致全灭；
    - 还是 likelihood 过严导致几何可达但不够高置信；
    - 当前帧是否适合继续构建通信图。
    """
    flight_frame = vox["flight_raw_records"]
    if flight_frame is None or len(flight_frame) == 0:
        flight_frame = vox["flight_motion_grouped"]
    lat_arr = _safe_float_series(flight_frame, "lat_clean")
    lon_arr = _safe_float_series(flight_frame, "lon_clean")
    alt_arr = _safe_float_series(flight_frame, "alt_meters")
    if lat_arr.size == 0 or lon_arr.size == 0 or alt_arr.size == 0:
        print(f"[Stage-3][diag] frame={vox['time_str']} no flight distribution available")
        return

    n = min(len(lat_arr), len(lon_arr), len(alt_arr))
    lat_arr = lat_arr[:n]
    lon_arr = lon_arr[:n]
    alt_arr = alt_arr[:n]
    dh = np.array([cfg._haversine_km(lat_arr[i], lon_arr[i], ground_lat, ground_lon) for i in range(n)], dtype=np.float64)
    dz = np.abs(alt_arr - float(ground_alt))
    if cfg.ADAPTIVE_SPACE_LIKELIHOOD:
        dh_scale = max(50.0, float(np.percentile(dh, 75)))
        dz_scale = max(800.0, float(np.percentile(dz, 75)))
    else:
        dh_scale = float(cfg.SPACE_LIKELIHOOD_SIGMA_KM)
        dz_scale = float(cfg.SPACE_LIKELIHOOD_SIGMA_Z_M)
    sl = np.array([
        np.exp(-0.5 * ((dh[i] / dh_scale) ** 2 + (dz[i] / dz_scale) ** 2))
        for i in range(n)
    ], dtype=np.float64)
    geo_ok = int(np.sum((dh <= dh_scale) & (dz <= dz_scale)))
    hi_conf = int(np.sum(sl >= 0.25))
    print(
        f"[Stage-3][diag] frame={vox['time_str']} valid={flight_pack.get(STAGE3_VALID_FLIGHT_AGENTS, 0) if flight_pack is not None else 0} "
        f"geo_ok={geo_ok}/{n} hi_conf={hi_conf}/{n} sl_p50={np.percentile(sl, 50):.6f} "
        f"sl_p90={np.percentile(sl, 90):.6f} sl_min={sl.min():.6f} "
        f"scales=({dh_scale:.1f}km,{dz_scale:.1f}m)"
    )


# [改动说明] 这里把增强后的风能力 flight_pack 写回 summary，
# 并把 agent_path / source_index 一并暴露给 Stage-4 和日志系统。
def build_agents_for_frame(vox):
    """针对单帧 Stage 2 结果构建飞行智能体。"""
    ts = vox["time_str"]
    target_time = datetime.strptime(ts, "%Y%m%d%H%M%S")
    H_DIM, W_DIM = vox["radar_shape"]

    flight_frame = vox["flight_raw_records"]
    if flight_frame is None or len(flight_frame) == 0:
        flight_frame = vox["flight_motion_grouped"]

    ground_lat, ground_lon, ground_alt = _estimate_ground_from_frame(vox, flight_frame)
    flight_pack = build_flight_agents_sparse(
        vox["flight_motion_grouped"],
        flight_frame,
        H_DIM,
        W_DIM,
        0,
        target_time,
        ground_lat,
        ground_lon,
        ground_alt,
        amdar_flight_ids=set(),
        tier2_max_override=cfg.FLIGHT_TIER2_MAX,
        config={
            "COMM_TIME_LIMIT_SECONDS": cfg.COMM_TIME_LIMIT_SECONDS,
            "COMM_SPACE_LIMIT_KM": cfg.COMM_SPACE_LIMIT_KM,
            "COMM_VERTICAL_LIMIT_M": cfg.COMM_VERTICAL_LIMIT_M,
            "FF_COMM_TIME_LIMIT_SECONDS": cfg.FF_COMM_TIME_LIMIT_SECONDS,
            "FF_COMM_SPACE_LIMIT_KM": cfg.FF_COMM_SPACE_LIMIT_KM,
            "FF_COMM_VERTICAL_LIMIT_M": cfg.FF_COMM_VERTICAL_LIMIT_M,
            "FLIGHT_PREFER_COMM_ELIGIBLE": cfg.FLIGHT_PREFER_COMM_ELIGIBLE,
            "FLIGHT_TIER2_MAX": cfg.FLIGHT_TIER2_MAX,
            "COMM_ROUND": cfg.COMM_ROUND,
            "FF_MAX_NEIGHBORS_PER_AGENT": cfg.FF_MAX_NEIGHBORS_PER_AGENT,
            "PHYSICS_REALISM_MODE": cfg.PHYSICS_REALISM_MODE,
        },
        helpers={
            "haversine_km": _haversine_km,
            "eval_agent_geo": _eval_agent_geo,
            "linear_conf": _linear_conf,
            "time_likelihood": _time_likelihood,
            "space_likelihood": _space_likelihood,
            "blend_comm_weight": cfg._blend_comm_weight,
            "compute_flight_intent": _compute_flight_intent,
            "ff_demand_score": _ff_demand_score,
            "ff_edge_score": _ff_edge_score,
            "zyx_to_linear_idx": _zyx_to_linear_idx,
            "select_ff_edges": select_ff_edges,
        },
    )
    flight_pack = _refine_flight_pack_with_wind_support(vox, flight_pack, H_DIM, W_DIM)

    _diag_frame_distribution(vox, ground_lat, ground_lon, ground_alt, flight_pack)
    print(f"[Stage-3][ground] frame={ts} ground=dynamic_flight_distribution")

    vox_dir = os.path.join(cfg.BASE_DIR, "stage3_output", "agents")
    os.makedirs(vox_dir, exist_ok=True)
    out_path = os.path.join(vox_dir, f"frame_{ts}_agents.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(flight_pack, f, ensure_ascii=False, default=lambda x: x.tolist() if hasattr(x, "tolist") else x, indent=2)

    return {
        "filename": vox["filename"],
        "source_index": int(vox.get("source_index", -1)),
        "time_str": ts,
        "timestamp_utc": vox["timestamp_utc"],
        "agent_path": out_path,
        "vox_path": out_path,
        "ground_lat": float(ground_lat),
        "ground_lon": float(ground_lon),
        "ground_alt": float(ground_alt),
        "space_likelihood_mode": "adaptive" if cfg.ADAPTIVE_SPACE_LIKELIHOOD else "fixed",
        "wind_voxels": int(len(vox["wind_grouped"])),
        "motion_voxels": int(len(vox["loc_motion_grouped"])),
        STAGE3_VALID_FLIGHT_AGENTS: int(flight_pack[STAGE3_VALID_FLIGHT_AGENTS]),
        STAGE3_CANDIDATE_FLIGHT_COUNT: int(flight_pack.get(STAGE3_CANDIDATE_FLIGHT_COUNT, 0)),
        STAGE3_TIER1_CANDIDATE_COUNT: int(flight_pack.get(STAGE3_TIER1_CANDIDATE_COUNT, 0)),
        STAGE3_TIER2_CANDIDATE_COUNT: int(flight_pack.get(STAGE3_TIER2_CANDIDATE_COUNT, 0)),
        STAGE3_VALID_WIND_CAPABLE_FLIGHTS: int(flight_pack.get(STAGE3_VALID_WIND_CAPABLE_FLIGHTS, 0)),
        "wind_support_direct_hits": int(flight_pack.get("wind_support_direct_hits", 0)),
        "wind_support_near_hits": int(flight_pack.get("wind_support_near_hits", 0)),
        "wind_support_geo_hits": int(flight_pack.get("wind_support_geo_hits", 0)),
        "wind_support_soft_hits": int(flight_pack.get("wind_support_soft_hits", 0)),
        "wind_support_score_p50": float(flight_pack.get("wind_support_score_p50", 0.0)),
        "wind_support_score_p90": float(flight_pack.get("wind_support_score_p90", 0.0)),
        STAGE3_FLIGHT_COMM_ALLOWED_AGENTS: _count_positive_entries(flight_pack.get(FLIGHT_COMM_ALLOWED, []), threshold=0.5),
        STAGE3_FLIGHT_FF_ALLOWED_EDGES: _count_positive_entries(flight_pack.get(FLIGHT_FF_COMM_ALLOWED, []), threshold=0.5),
        STAGE3_FLIGHT_FF_MOTION_EDGES: _count_positive_entries(flight_pack.get(FLIGHT_FF_MOTION_ALLOWED, []), threshold=0.5),
        STAGE3_FLIGHT_FF_WIND_EDGES: _count_positive_entries(flight_pack.get(FLIGHT_FF_WIND_ALLOWED, []), threshold=0.0),
    }


# [改动说明] main 中加入统一选帧和文本进度条输出。
def main():
    """Stage 3 主入口。

    执行流程：
    1. 读取 Stage 2 的 stage2_summary.json。
    2. 逐帧读取 npz，恢复体素聚合结果。
    3. 调用 build_flight_agents_sparse 构建智能体。
    4. 写出每帧 agents json 和 stage3_summary.json。

    小批量试跑时可通过 WIND_MAX_FRAMES 控制处理帧数；这一步在 Stage 3 内部
    再做一次截断，确保不会因为上游 summary 较长而误跑全量。
    """
    stage3_dir = os.path.join(cfg.BASE_DIR, "stage3_output")
    os.makedirs(stage3_dir, exist_ok=True)
    progress_every = max(1, int(os.environ.get("WIND_PROGRESS_EVERY", "25") or "25"))

    print("[Stage-3] 读取 Stage-2 中间结果...")
    summary_path = os.path.join(cfg.BASE_DIR, "stage2_output", "stage2_summary.json")
    with open(summary_path, "r", encoding="utf-8") as f:
        stage2_summary = json.load(f)

    stage2_summary = _select_stage2_frames(stage2_summary)

    summary = []
    total_frames = len(stage2_summary)
    t_start = time.perf_counter()
    if total_frames > 0:
        print(f"[Stage-3] 计划处理 {total_frames} 帧，进度日志间隔={progress_every}")
    for i, item in enumerate(stage2_summary, 1):
        vox = load_stage2_voxel(item)
        out = build_agents_for_frame(vox)
        summary.append(out)
        if i % progress_every == 0 or i == total_frames:
            _print_stage_progress("Stage-3", i, total_frames, t_start, frame_item=out)

    with open(os.path.join(stage3_dir, "stage3_summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print("[Stage-3] 完成")
    print(f"样本数: {len(summary)}")


if __name__ == "__main__":
    main()
