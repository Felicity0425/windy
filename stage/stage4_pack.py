"""Stage 4：融合 Stage 2 / Stage 3 的结果，重构风场并打包最终训练样本。

Stage 4 的职责要尽量清晰：
1. 读取 Stage 2 的体素结果。
2. 读取 Stage 3 的智能体结果。
3. 对齐时间帧并做一致性检查。
4. 融合风/轨迹/运动/AMDAR/Turb 观测，输出重构风场初值。
5. 将“训练样本所需字段”打包成 frame_*.npz。
6. 输出 stage4_summary.json 作为后续训练入口索引。

输出目录：stage4_output/
- frame_*.npz
- stage4_summary.json
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import polars as pl

ROOT_DIR = Path(__file__).resolve().parent.parent
STAGE_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
if str(STAGE_DIR) not in sys.path:
    sys.path.insert(0, str(STAGE_DIR))

import pipeline_config as cfg
from stage.reconstruct_utils import _reconstruct_wind_field
from stage.pipeline_utils import _save_sparse_lossless_npz, _zyx_to_linear_idx
from schema_contract import (
    STAGE2_AMDAR_RECORDS,
    STAGE2_FLIGHT_MOTION_RECORDS,
    STAGE2_FLIGHT_RAW_RECORDS,
    STAGE2_LOC_RECORDS,
    STAGE2_MOTION_RECORDS,
    STAGE2_RADAR_IMG,
    STAGE2_TIME_STR,
    STAGE2_TIMESTAMP_UTC,
    STAGE2_TURB_RECORDS,
    STAGE2_WIND_RECORDS,
)

# 各类观测源的基础权重。
# 后续若引入 PINN，可以优先在这里或训练 loss 中增加物理约束权重。
SOURCE_WEIGHTS = {
    "wind": 0.65,
    "motion": 0.45,
    "amdar": 0.95,
    "turb": 0.75,
}
SUPPORT_RADIUS_XY = int(os.environ.get("WIND_RECON_SUPPORT_RADIUS_XY", "4"))
SUPPORT_RADIUS_Z = int(os.environ.get("WIND_RECON_SUPPORT_RADIUS_Z", "2"))
SUPPORT_MAX_FILL = int(os.environ.get("WIND_RECON_SUPPORT_MAX_FILL", "20000"))
SUPPORT_FILL_MIN_SUPPORT = float(os.environ.get("WIND_RECON_SUPPORT_FILL_MIN_SUPPORT", "0.12"))
SUPPORT_FILL_MIN_NEIGHBORS = int(os.environ.get("WIND_RECON_SUPPORT_FILL_MIN_NEIGHBORS", "3"))
SUPPORT_FILL_MAX_LOCAL_SPREAD = float(os.environ.get("WIND_RECON_SUPPORT_FILL_MAX_LOCAL_SPREAD", "18.0"))
TEMPORAL_BG_BLEND = float(os.environ.get("WIND_RECON_TEMPORAL_BG_BLEND", "0.30"))
TEMPORAL_BG_MAX_GAP = int(os.environ.get("WIND_RECON_TEMPORAL_BG_MAX_GAP", "1"))
RECON_RELAX_STEPS = int(os.environ.get("WIND_RECON_RELAX_STEPS", "2"))
RECON_RELAX_BLEND = float(os.environ.get("WIND_RECON_RELAX_BLEND", "0.15"))
COMM_TOPK_RATIO = float(getattr(cfg, "COMM_TOPK_RATIO", 0.30))
COMM_MIN_TOPK = int(getattr(cfg, "COMM_MIN_TOPK", 32))
COMM_WIND_WEIGHT = float(getattr(cfg, "COMM_WIND_WEIGHT", 0.70))
COMM_MOTION_WEIGHT = float(getattr(cfg, "COMM_MOTION_WEIGHT", 0.30))
FORECAST_BLEND = float(os.environ.get("WIND_FORECAST_BLEND", "0.35"))
FORECAST_CONF_DECAY = float(os.environ.get("WIND_FORECAST_CONF_DECAY", "0.85"))
FORECAST_COMM_CONF_BOOST = float(os.environ.get("WIND_FORECAST_COMM_CONF_BOOST", "0.10"))
HAZARD_SHEAR_ALERT = float(os.environ.get("WIND_HAZARD_SHEAR_ALERT", "0.40"))
HAZARD_TURB_ALERT = float(os.environ.get("WIND_HAZARD_TURB_ALERT", "0.45"))
RECON_OUTLIER_SPEED_PENALTY = float(os.environ.get("WIND_RECON_OUTLIER_SPEED_PENALTY", "0.35"))
RECON_OUTLIER_GRAD_PENALTY = float(os.environ.get("WIND_RECON_OUTLIER_GRAD_PENALTY", "0.30"))
RECON_OUTLIER_GRAD_Q = float(os.environ.get("WIND_RECON_OUTLIER_GRAD_Q", "0.995"))
RECON_CONF_KEEP_FLOOR = float(os.environ.get("WIND_RECON_CONF_KEEP_FLOOR", "0.08"))
RECON_SUPPORT_KEEP_Q = float(os.environ.get("WIND_RECON_SUPPORT_KEEP_Q", "0.10"))
WIND_PRIMARY_CONFLICT_KEEP_MS = float(os.environ.get("WIND_PRIMARY_CONFLICT_KEEP_MS", "8.0"))
DIRECT_AGREEMENT_SCALE_MS = float(os.environ.get("WIND_DIRECT_AGREEMENT_SCALE_MS", "12.0"))
BASE_RECON_ENABLE_IDW = os.environ.get("WIND_STAGE4_BASE_RECON_ENABLE_IDW", "0") not in ("0", "false", "False")
BASE_RECON_IDW_MAX_FILL = int(os.environ.get("WIND_STAGE4_BASE_RECON_IDW_MAX_FILL", "512"))


def _records_to_df(records):
    """把 Stage 2 npz 中的序列化记录恢复成 Polars DataFrame。"""
    if records is None:
        return pl.DataFrame()
    if isinstance(records, pl.DataFrame):
        return records
    if isinstance(records, np.ndarray):
        if records.size == 0:
            return pl.DataFrame()
        return pl.DataFrame(records.tolist())
    if isinstance(records, list):
        if len(records) == 0:
            return pl.DataFrame()
        return pl.DataFrame(records)
    if hasattr(records, "tolist"):
        payload = records.tolist()
        return pl.DataFrame(payload) if payload else pl.DataFrame()
    return pl.DataFrame(records)


# [改动说明] Stage-4 观测清洗在这里做：
# 改成按配置中的风速/运动速度模长过滤，并生成 qc_weight。
def _sanitize_observations(df, required_cols, source_name):
    """清洗单一来源的体素观测。

    规则：
    - 必要列必须存在；
    - 去掉 null；
    - 过滤明显异常速度值；
    - 计算 qc_weight，供后续多源融合和重构使用。
    """
    if len(df) == 0:
        return pl.DataFrame()
    if any(c not in df.columns for c in required_cols):
        return pl.DataFrame()
    df = df.drop_nulls(subset=required_cols)
    if len(df) == 0:
        return pl.DataFrame()

    # 这里不能再把所有向量统一裁到 [-80, 80]。
    # 原因：
    # 1. 根配置里已经分别定义了风速上限和地速上限；
    # 2. 直接按分量裁剪会把“单分量偏大但总矢量仍合理”的样本误删；
    # 3. Stage-4 若过滤过严，会导致 Stage-2 明明有 wind voxels，
    #    到 Stage-4 却被无声吃掉，形成“看起来像 Stage-2 有问题”的假象。
    if {"u", "v"}.issubset(set(df.columns)):
        max_speed = float(cfg.MAX_WIND_SPEED_MS)
        df = df.filter(
            ((pl.col("u").cast(pl.Float32, strict=False) ** 2 + pl.col("v").cast(pl.Float32, strict=False) ** 2).sqrt() <= max_speed)
        )
    if {"u_motion", "v_motion"}.issubset(set(df.columns)):
        max_motion = float(getattr(cfg, "MAX_GROUND_SPEED_MS", 400.0))
        df = df.filter(
            ((pl.col("u_motion").cast(pl.Float32, strict=False) ** 2 + pl.col("v_motion").cast(pl.Float32, strict=False) ** 2).sqrt() <= max_motion)
        )
    if len(df) == 0:
        return pl.DataFrame()

    score = pl.lit(SOURCE_WEIGHTS.get(source_name, 0.5), dtype=pl.Float32)
    if "obs_conf" in df.columns:
        score = score * pl.col("obs_conf").fill_null(0.0).clip(0.0, 1.0)
    if "obs_count" in df.columns:
        score = score * (0.35 + 0.65 * (pl.col("obs_count").clip(1, 50) / 50.0))
    if "motion_count" in df.columns:
        score = score * (0.35 + 0.65 * (pl.col("motion_count").clip(1, 50) / 50.0))
    if "density" in df.columns:
        score = score * (0.35 + 0.65 * (pl.col("density").clip(1, 50) / 50.0))

    return df.with_columns(score.fill_null(0.0).clip(0.0, 1.0).alias("qc_weight")).filter(pl.col("qc_weight") > 0.05)


def _load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _load_stage3_pack_map(stage3_dir):
    """加载 Stage 3 summary，并建立 time_str -> agent_path 的映射。"""
    summary = _load_json(os.path.join(stage3_dir, "stage3_summary.json"))
    pack_map = {}
    for item in summary:
        time_str = item["time_str"]
        path = item.get("agent_path") or item.get("vox_path")
        if not path:
            path = os.path.join(stage3_dir, "agents", f"frame_{time_str}_agents.json")
        elif not os.path.isabs(path):
            path = os.path.join(cfg.BASE_DIR, path)
        pack_map[time_str] = {**item, "agent_path": path}
    return summary, pack_map


def _json_to_flight_pack(payload):
    """把 Stage 3 的 JSON 智能体包恢复为 Python dict。"""
    if not payload:
        return {}
    if isinstance(payload, dict):
        return payload
    return dict(payload)


def _concat_frames(frames):
    frames = [x for x in frames if x is not None and len(x) > 0]
    if not frames:
        return pl.DataFrame()
    if len(frames) == 1:
        return frames[0]
    return pl.concat(frames, how="diagonal_relaxed")


def _merge_motion_views(*frames):
    """把多个 motion 视图按体素重新聚合，避免重复体素被简单拼接后翻倍。

    当前 Stage-4 会同时使用：
    - Stage-2 的 `motion_grouped`
    - 更细粒度的 `flight_motion_records`

    如果直接 `concat`，相同 `(z,y,x)` 会被重复计数，导致：
    - `motion_voxels` 虚高
    - `recon_seed_strength` 虚高
    - support_strength 偏向 motion，压制 wind / amdar 的作用

    因此这里在融合后重新按 `(z,y,x)` 聚合：
    - `u_motion / v_motion` 用 `motion_count` 加权平均
    - `motion_count` 取求和
    - `qc_weight` / `obs_conf` 用平均
    """
    valid_frames = [x for x in frames if x is not None and len(x) > 0]
    if not valid_frames:
        return pl.DataFrame()
    merged = pl.concat(valid_frames, how="diagonal_relaxed")
    needed = {"z", "y", "x", "u_motion", "v_motion"}
    if not needed.issubset(set(merged.columns)):
        return merged
    if "motion_count" not in merged.columns:
        merged = merged.with_columns(pl.lit(1.0, dtype=pl.Float32).alias("motion_count"))

    exprs = [
        (pl.col("u_motion").cast(pl.Float32, strict=False) * pl.col("motion_count").cast(pl.Float32, strict=False)).alias("_wm_u"),
        (pl.col("v_motion").cast(pl.Float32, strict=False) * pl.col("motion_count").cast(pl.Float32, strict=False)).alias("_wm_v"),
    ]
    if "qc_weight" in merged.columns:
        exprs.append(pl.col("qc_weight").cast(pl.Float32, strict=False).alias("_qc_weight"))
    if "obs_conf" in merged.columns:
        exprs.append(pl.col("obs_conf").cast(pl.Float32, strict=False).alias("_obs_conf"))

    merged = merged.with_columns(exprs)
    agg_exprs = [
        pl.col("_wm_u").sum().alias("_sum_wm_u"),
        pl.col("_wm_v").sum().alias("_sum_wm_v"),
        pl.col("motion_count").cast(pl.Float32, strict=False).sum().alias("motion_count"),
    ]
    if "_qc_weight" in merged.columns:
        agg_exprs.append(pl.col("_qc_weight").mean().alias("qc_weight"))
    if "_obs_conf" in merged.columns:
        agg_exprs.append(pl.col("_obs_conf").mean().alias("obs_conf"))

    grouped = merged.group_by(["z", "y", "x"]).agg(agg_exprs)
    grouped = grouped.with_columns(
        (pl.col("_sum_wm_u") / pl.col("motion_count").clip(1e-6, None)).alias("u_motion"),
        (pl.col("_sum_wm_v") / pl.col("motion_count").clip(1e-6, None)).alias("v_motion"),
    ).drop(["_sum_wm_u", "_sum_wm_v"])
    return grouped


def _topk_sparse_targets(idx: np.ndarray, score: np.ndarray, total_candidates: int) -> tuple[np.ndarray, np.ndarray]:
    """Where2Comm 风格的 top-k 通信目标筛选。

    思路来源：
    - Where2Comm 的核心不是“所有位置都通信”，而是只让信息量高的位置通信；
    - 因此这里对每类候选体素先打分，再保留 top-k。

    这里的 k 不是固定值，而是：
    - 至少 `COMM_MIN_TOPK`
    - 至多 `COMM_TOPK_RATIO * total_candidates`
    """
    idx = np.asarray(idx, dtype=np.uint32)
    score = np.asarray(score, dtype=np.float32)
    if idx.size == 0 or score.size == 0:
        return np.array([], dtype=np.uint32), np.array([], dtype=np.float32)

    uniq = {}
    for i, s in zip(idx.tolist(), score.tolist()):
        i = int(i)
        s = float(s)
        if i not in uniq or s > uniq[i]:
            uniq[i] = s
    uniq_idx = np.asarray(list(uniq.keys()), dtype=np.uint32)
    uniq_score = np.asarray(list(uniq.values()), dtype=np.float32)

    k = min(len(uniq_idx), max(COMM_MIN_TOPK, int(round(max(1, total_candidates) * COMM_TOPK_RATIO))))
    order = np.argsort(-uniq_score)[:k]
    return uniq_idx[order], uniq_score[order]


def _build_where2comm_targets(
    wind_grouped,
    motion_grouped,
    support_strength,
    recon_conf,
    h_dim,
    w_dim,
):
    """构建 Where2Comm 风格的体素级通信候选。

    当前项目中的落地方式：
    - wind branch：高置信风观测体素优先通信；
    - motion branch：高运动密度/高 support 区域优先通信；
    - uncertainty branch：support 高但当前重构置信度低的区域优先通信；
    - joint branch：三者综合后选出最终通信体素。

    这样做的意义：
    - 让后续 GNN / PINN / diffusion 只关注“最值得通信”的体素；
    - 把协同感知从 flight-edge 层扩展到 voxel target 层。
    """
    wind_idx = np.array([], dtype=np.uint32)
    wind_score = np.array([], dtype=np.float32)
    motion_idx = np.array([], dtype=np.uint32)
    motion_score = np.array([], dtype=np.float32)

    total_candidates = int(np.count_nonzero(support_strength > 0))

    if len(wind_grouped) > 0 and {"z", "y", "x", "u", "v"}.issubset(set(wind_grouped.columns)):
        wind_idx = _zyx_to_linear_idx(
            wind_grouped["z"].to_numpy(),
            wind_grouped["y"].to_numpy(),
            wind_grouped["x"].to_numpy(),
            h_dim,
            w_dim,
        )
        if "qc_weight" in wind_grouped.columns:
            base = wind_grouped["qc_weight"].cast(pl.Float32, strict=False).fill_null(0.0).to_numpy()
        elif "obs_conf" in wind_grouped.columns:
            base = wind_grouped["obs_conf"].cast(pl.Float32, strict=False).fill_null(0.0).to_numpy()
        else:
            base = np.ones(len(wind_grouped), dtype=np.float32)
        obs_count = (
            wind_grouped["obs_count"].cast(pl.Float32, strict=False).fill_null(1.0).to_numpy()
            if "obs_count" in wind_grouped.columns
            else np.ones(len(wind_grouped), dtype=np.float32)
        )
        wind_score = (0.65 * base + 0.35 * np.log1p(obs_count)).astype(np.float32, copy=False)

    if len(motion_grouped) > 0 and {"z", "y", "x", "u_motion", "v_motion"}.issubset(set(motion_grouped.columns)):
        motion_idx = _zyx_to_linear_idx(
            motion_grouped["z"].to_numpy(),
            motion_grouped["y"].to_numpy(),
            motion_grouped["x"].to_numpy(),
            h_dim,
            w_dim,
        )
        motion_count = (
            motion_grouped["motion_count"].cast(pl.Float32, strict=False).fill_null(1.0).to_numpy()
            if "motion_count" in motion_grouped.columns
            else np.ones(len(motion_grouped), dtype=np.float32)
        )
        z = motion_grouped["z"].cast(pl.Int32, strict=False).to_numpy()
        y = motion_grouped["y"].cast(pl.Int32, strict=False).to_numpy()
        x = motion_grouped["x"].cast(pl.Int32, strict=False).to_numpy()
        local_support = support_strength[z, y, x]
        motion_score = (0.55 * np.log1p(motion_count) + 0.45 * local_support).astype(np.float32, copy=False)

    uncertainty_mask = support_strength > 0
    if recon_conf.shape == support_strength.shape:
        uncertainty_score_3d = support_strength * np.clip(1.0 - recon_conf, 0.0, 1.0)
    else:
        uncertainty_score_3d = support_strength.copy()
    uncertainty_idx = np.flatnonzero(uncertainty_mask.reshape(-1)).astype(np.uint32)
    uncertainty_score = uncertainty_score_3d.reshape(-1)[uncertainty_idx].astype(np.float32, copy=False)

    wind_top_idx, wind_top_score = _topk_sparse_targets(wind_idx, wind_score, total_candidates)
    motion_top_idx, motion_top_score = _topk_sparse_targets(motion_idx, motion_score, total_candidates)
    uncertainty_top_idx, uncertainty_top_score = _topk_sparse_targets(uncertainty_idx, uncertainty_score, total_candidates)

    joint_idx = np.concatenate([wind_top_idx, motion_top_idx, uncertainty_top_idx]) if (
        wind_top_idx.size + motion_top_idx.size + uncertainty_top_idx.size
    ) > 0 else np.array([], dtype=np.uint32)
    joint_score = np.concatenate([
        COMM_WIND_WEIGHT * wind_top_score,
        COMM_MOTION_WEIGHT * motion_top_score,
        0.20 * uncertainty_top_score,
    ]).astype(np.float32, copy=False) if joint_idx.size > 0 else np.array([], dtype=np.float32)
    joint_top_idx, joint_top_score = _topk_sparse_targets(joint_idx, joint_score, total_candidates)

    return {
        "wind_idx": wind_top_idx,
        "wind_score": wind_top_score,
        "motion_idx": motion_top_idx,
        "motion_score": motion_top_score,
        "uncertainty_idx": uncertainty_top_idx,
        "uncertainty_score": uncertainty_top_score,
        "joint_idx": joint_top_idx,
        "joint_score": joint_top_score,
    }


def _compute_pinn_proxy_fields(recon_u, recon_v, support_strength):
    """生成 PINN 风格的物理代理量。

    说明：
    - 这不是完整的 PINN 训练；
    - 但它把后续 PINN 需要关心的物理量显式计算并保存下来：
      - divergence
      - smoothness / Laplacian proxy
      - physics weight

    后续你做 PINN refinement 时，可以直接把这些场作为：
    - loss mask
    - 采样重点区域
    - 误差分析指标
    """
    du_dx = np.zeros_like(recon_u, dtype=np.float32)
    dv_dy = np.zeros_like(recon_v, dtype=np.float32)
    du_dx[:, :, 1:-1] = 0.5 * (recon_u[:, :, 2:] - recon_u[:, :, :-2])
    dv_dy[:, 1:-1, :] = 0.5 * (recon_v[:, 2:, :] - recon_v[:, :-2, :])
    divergence = du_dx + dv_dy

    def _lap(a):
        out = np.zeros_like(a, dtype=np.float32)
        out[1:-1, 1:-1, 1:-1] = (
            a[1:-1, 1:-1, :-2] + a[1:-1, 1:-1, 2:] +
            a[1:-1, :-2, 1:-1] + a[1:-1, 2:, 1:-1] +
            a[:-2, 1:-1, 1:-1] + a[2:, 1:-1, 1:-1] -
            6.0 * a[1:-1, 1:-1, 1:-1]
        )
        return out

    smoothness = np.sqrt(_lap(recon_u) ** 2 + _lap(recon_v) ** 2).astype(np.float32, copy=False)
    divergence_abs = np.abs(divergence).astype(np.float32, copy=False)
    if np.max(divergence_abs) > 0:
        divergence_norm = divergence_abs / float(np.max(divergence_abs))
    else:
        divergence_norm = divergence_abs
    if np.max(smoothness) > 0:
        smoothness_norm = smoothness / float(np.max(smoothness))
    else:
        smoothness_norm = smoothness
    physics_weight = np.clip(
        support_strength * (0.55 + 0.45 * np.clip(divergence_norm + smoothness_norm, 0.0, 1.0)),
        0.0,
        1.0,
    ).astype(np.float32, copy=False)
    return divergence_abs, smoothness, physics_weight


def _build_diffusion_condition_tensors(
    radar_img,
    trajectory_3d,
    recon_u,
    recon_v,
    recon_conf,
    support_strength,
    physics_weight,
):
    """构建 diffusion refinement 的条件先验。

    这里不直接训练 diffusion，但把后续 diffusion 模型最需要的条件显式写入：
    - 当前 deterministic baseline (u,v,conf)
    - 轨迹密度
    - support 强度
    - physics weight
    - radar 背景

    这样你后续接 `training/diffusion_baseline.py` 时，不需要再返工 Stage-4 输出层。
    """
    z_dim = recon_u.shape[0]
    radar_norm = radar_img.astype(np.float32)
    if radar_norm.size > 0:
        radar_norm = radar_norm / max(1.0, float(np.max(radar_norm)))
    radar_3d = np.repeat(radar_norm[None, :, :], z_dim, axis=0).astype(np.float32, copy=False)
    cond = np.stack(
        [
            np.nan_to_num(recon_u, nan=0.0).astype(np.float32, copy=False),
            np.nan_to_num(recon_v, nan=0.0).astype(np.float32, copy=False),
            np.nan_to_num(recon_conf, nan=0.0).astype(np.float32, copy=False),
            np.asarray(trajectory_3d, dtype=np.float32),
            np.asarray(support_strength, dtype=np.float32),
            np.asarray(physics_weight, dtype=np.float32),
            radar_3d,
        ],
        axis=0,
    )
    return cond


def _build_confidence_source_fields(
    z_dim,
    h_dim,
    w_dim,
    wind_grouped,
    motion_grouped,
    amdar_grouped,
    turb_grouped,
    flight_seed_df,
):
    """把各来源的观测强度投影成 3D 置信度先验场。

    目标是给 `recon_confidence_3d` 提供更细粒度的来源信息，避免只由单一
    `sum_w -> 1-exp(-sum_w)` 决定，最终让大部分体素置信度塌成同一个常数。
    """
    shape = (z_dim, h_dim, w_dim)
    fields = {
        "wind": np.zeros(shape, dtype=np.float32),
        "motion": np.zeros(shape, dtype=np.float32),
        "amdar": np.zeros(shape, dtype=np.float32),
        "turb": np.zeros(shape, dtype=np.float32),
        "seed": np.zeros(shape, dtype=np.float32),
    }

    def _scatter(df, out, count_key=None, conf_key=None):
        if df is None or len(df) == 0 or not {"z", "y", "x"}.issubset(set(df.columns)):
            return
        z = df["z"].cast(pl.Int32, strict=False).to_numpy()
        y = df["y"].cast(pl.Int32, strict=False).to_numpy()
        x = df["x"].cast(pl.Int32, strict=False).to_numpy()
        keep = (
            (z >= 0) & (z < z_dim) &
            (y >= 0) & (y < h_dim) &
            (x >= 0) & (x < w_dim)
        )
        if not np.any(keep):
            return
        z, y, x = z[keep], y[keep], x[keep]
        base = np.ones(len(z), dtype=np.float32)
        if conf_key and conf_key in df.columns:
            base *= df[conf_key].cast(pl.Float32, strict=False).fill_null(0.0).to_numpy()[keep]
        if count_key and count_key in df.columns:
            c = df[count_key].cast(pl.Float32, strict=False).fill_null(1.0).to_numpy()[keep]
            base *= np.clip(np.log1p(c) / np.log(51.0), 0.0, 1.0)
        out[z, y, x] = np.maximum(out[z, y, x], base.astype(np.float32, copy=False))

    _scatter(wind_grouped, fields["wind"], count_key="obs_count", conf_key="qc_weight" if "qc_weight" in getattr(wind_grouped, "columns", []) else "obs_conf")
    _scatter(motion_grouped, fields["motion"], count_key="motion_count", conf_key="qc_weight")
    _scatter(amdar_grouped, fields["amdar"], count_key="obs_count", conf_key="qc_weight")
    _scatter(turb_grouped, fields["turb"], count_key="obs_count", conf_key="qc_weight")
    _scatter(flight_seed_df, fields["seed"], count_key="obs_count", conf_key="obs_conf")
    return fields


def _refine_recon_confidence(
    recon_u,
    recon_v,
    recon_conf,
    recon_mask,
    support_strength,
    source_fields,
    temporal_fill_mask,
    support_fill_mask,
    relaxed_mask,
    direct_agreement_field=None,
    direct_source_count_field=None,
):
    """提升 recon_confidence_3d 的分辨率。

    当前问题：
    - 大量监督点的置信度接近同一个常数，区分不出“高可信”和“低可信”区域。

    这里的改进思路：
    1. 引入分来源观测强度（wind / motion / amdar / turb / seed）；
    2. 引入局部一致性：与邻域差异越大，置信度越低；
    3. 区分 direct / support_fill / temporal_fill / relax 区域；
    4. 对填充类区域统一降置信，对直接观测区域保留高置信。
    """
    conf0 = np.asarray(recon_conf, dtype=np.float32).copy()
    conf = conf0.copy()
    mask = np.asarray(recon_mask, dtype=np.float32) > 0
    if not np.any(mask):
        return conf

    wind_strength = source_fields["wind"]
    motion_strength = source_fields["motion"]
    amdar_strength = source_fields["amdar"]
    turb_strength = source_fields["turb"]
    seed_strength = source_fields["seed"]

    u = np.asarray(recon_u, dtype=np.float32)
    v = np.asarray(recon_v, dtype=np.float32)
    u_pad = np.pad(u, ((1, 1), (1, 1), (1, 1)), mode="edge")
    v_pad = np.pad(v, ((1, 1), (1, 1), (1, 1)), mode="edge")
    u_avg = (
        u_pad[1:-1, 1:-1, :-2] + u_pad[1:-1, 1:-1, 2:] +
        u_pad[1:-1, :-2, 1:-1] + u_pad[1:-1, 2:, 1:-1] +
        u_pad[:-2, 1:-1, 1:-1] + u_pad[2:, 1:-1, 1:-1]
    ) / 6.0
    v_avg = (
        v_pad[1:-1, 1:-1, :-2] + v_pad[1:-1, 1:-1, 2:] +
        v_pad[1:-1, :-2, 1:-1] + v_pad[1:-1, 2:, 1:-1] +
        v_pad[:-2, 1:-1, 1:-1] + v_pad[2:, 1:-1, 1:-1]
    ) / 6.0
    local_residual = np.sqrt((u - u_avg) ** 2 + (v - v_avg) ** 2).astype(np.float32, copy=False)
    if np.max(local_residual) > 0:
        local_residual = local_residual / float(np.max(local_residual))

    source_conf = np.clip(
        0.40 * wind_strength +
        0.20 * motion_strength +
        0.25 * amdar_strength +
        0.05 * turb_strength +
        0.10 * seed_strength,
        0.0,
        1.0,
    )
    support_conf = np.asarray(support_strength, dtype=np.float32)
    conf = np.clip(
        0.55 * conf +
        0.30 * source_conf +
        0.15 * support_conf,
        0.0,
        1.0,
    )
    conf = np.clip(conf * (1.0 - 0.35 * local_residual), 0.0, 1.0)

    # 直接观测区域应最高，但不能全部塌成同一常数。
    direct_mask = (wind_strength > 0) | (amdar_strength > 0) | (turb_strength > 0)
    if direct_agreement_field is None:
        direct_agreement = np.full_like(conf, 0.55, dtype=np.float32)
    else:
        direct_agreement = np.asarray(direct_agreement_field, dtype=np.float32)
    if direct_source_count_field is None:
        direct_source_count = np.zeros_like(conf, dtype=np.float32)
    else:
        direct_source_count = np.asarray(direct_source_count_field, dtype=np.float32)
    direct_penalty = np.clip(0.78 + 0.22 * direct_agreement, 0.70, 1.0)
    conf[direct_mask] *= direct_penalty[direct_mask]
    direct_floor = np.clip(
        0.24
        + 0.16 * source_conf
        + 0.16 * np.sqrt(np.clip(conf0, 0.0, 1.0))
        + 0.10 * support_conf
        + 0.22 * direct_agreement
        + 0.08 * direct_source_count
        + 0.05 * (1.0 - local_residual),
        0.35,
        0.98,
    )
    conf[direct_mask] = np.maximum(conf[direct_mask], direct_floor[direct_mask])

    support_target = np.clip(
        0.10 + 0.42 * support_conf + 0.18 * source_conf + 0.10 * np.sqrt(np.clip(conf0, 0.0, 1.0)),
        0.08,
        0.75,
    )
    temporal_target = np.clip(
        0.06 + 0.30 * support_conf + 0.12 * source_conf,
        0.05,
        0.55,
    )
    indirect_mask = mask & (~direct_mask) & (~support_fill_mask) & (~temporal_fill_mask)
    indirect_target = np.clip(
        0.03 + 0.24 * support_conf + 0.08 * source_conf,
        0.03,
        0.40,
    )

    conf[support_fill_mask] = np.minimum(conf[support_fill_mask], support_target[support_fill_mask])
    conf[temporal_fill_mask] = np.minimum(conf[temporal_fill_mask], temporal_target[temporal_fill_mask])
    conf[indirect_mask] = np.minimum(conf[indirect_mask], indirect_target[indirect_mask])
    conf[relaxed_mask] *= 0.92
    conf[mask] = np.clip(conf[mask], 0.02, 0.98)
    return conf


def _suppress_recon_outliers(
    recon_u,
    recon_v,
    recon_conf,
    recon_mask,
    direct_observation_mask,
):
    """抑制极端 outlier 对 RMSE 的破坏。

    处理原则：
    - 不动直接观测锚点；
    - 只对低置信区域施加二次惩罚；
    - 综合考虑速度上界和局地梯度异常。
    """
    u = np.asarray(recon_u, dtype=np.float32)
    v = np.asarray(recon_v, dtype=np.float32)
    conf = np.asarray(recon_conf, dtype=np.float32)
    mask = np.asarray(recon_mask, dtype=np.float32)

    speed = np.sqrt(u * u + v * v)
    speed_excess = np.clip(speed / max(1e-6, float(cfg.MAX_WIND_SPEED_MS)) - 1.0, 0.0, None)

    du_dx = np.zeros_like(u)
    du_dy = np.zeros_like(u)
    dv_dx = np.zeros_like(v)
    dv_dy = np.zeros_like(v)
    du_dx[:, :, 1:-1] = 0.5 * (u[:, :, 2:] - u[:, :, :-2])
    du_dy[:, 1:-1, :] = 0.5 * (u[:, 2:, :] - u[:, :-2, :])
    dv_dx[:, :, 1:-1] = 0.5 * (v[:, :, 2:] - v[:, :, :-2])
    dv_dy[:, 1:-1, :] = 0.5 * (v[:, 2:, :] - v[:, :-2, :])
    shear = np.sqrt(du_dx ** 2 + du_dy ** 2 + dv_dx ** 2 + dv_dy ** 2)
    shear_thr = float(np.quantile(shear[np.isfinite(shear)], RECON_OUTLIER_GRAD_Q)) if np.any(np.isfinite(shear)) else 0.0
    shear_excess = np.clip(shear / max(1e-6, shear_thr) - 1.0, 0.0, None) if shear_thr > 0 else np.zeros_like(shear)

    penalize = (
        (mask > 0) &
        (~direct_observation_mask) &
        (conf < 0.45) &
        ((speed_excess > 0) | (shear_excess > 0))
    )
    if not np.any(penalize):
        return recon_u, recon_v, recon_conf, recon_mask, 0

    # 对异常值降权，而不是粗暴删掉。
    penalty = np.clip(
        RECON_OUTLIER_SPEED_PENALTY * speed_excess +
        RECON_OUTLIER_GRAD_PENALTY * shear_excess,
        0.0,
        0.85,
    )
    conf[penalize] *= (1.0 - penalty[penalize])
    hard_bad = penalize & (conf < 0.03)
    mask[hard_bad] = 0.0
    u[hard_bad] = 0.0
    v[hard_bad] = 0.0
    return u, v, conf, mask, int(np.sum(hard_bad))


def _prune_low_quality_reconstruction(
    recon_u,
    recon_v,
    recon_conf,
    recon_mask,
    support_strength,
    source_fields,
    direct_observation_mask,
    support_fill_mask,
    temporal_fill_mask,
    base_domain_mask,
):
    """裁掉大面积低支撑、低置信的尾部重构体素。

    当前 Stage-4 的主要问题不是监督点不准，而是：
    - `_reconstruct_wind_field()` 的 IDW 会给出一批很宽的弱支撑尾部；
    - 这些尾部会把 `coverage` 和 `conf_mean` 一起拉歪。

    因此这里做一层保守裁剪：
    - 直接观测、support_fill、temporal_fill、seed 锚点始终保留；
    - 其余体素必须同时满足“支撑够强 + 置信度不过低”才保留；
    - 最终有效域使用“基础支撑域 + 实际保留域”的并集，保证 coverage 不会大于 1。
    """
    u = np.asarray(recon_u, dtype=np.float32).copy()
    v = np.asarray(recon_v, dtype=np.float32).copy()
    conf = np.asarray(recon_conf, dtype=np.float32).copy()
    mask = np.asarray(recon_mask, dtype=np.float32) > 0
    base_domain = np.asarray(base_domain_mask, dtype=bool).copy()
    if not np.any(mask):
        return u, v, conf, mask.astype(np.float32), 0, base_domain, base_domain

    seed_mask = np.asarray(source_fields["seed"] > 0, dtype=bool)
    support_positive = np.asarray(support_strength, dtype=np.float32)
    positive_vals = support_positive[support_positive > 0]
    support_floor = 0.05
    if positive_vals.size > 0:
        support_floor = max(support_floor, float(np.quantile(positive_vals, RECON_SUPPORT_KEEP_Q)))

    support_fill_keep_mask = support_fill_mask & (
        (support_positive >= max(support_floor, SUPPORT_FILL_MIN_SUPPORT))
        & (conf >= max(RECON_CONF_KEEP_FLOOR, 0.12))
    )
    temporal_fill_keep_mask = temporal_fill_mask & (conf >= max(RECON_CONF_KEEP_FLOOR, 0.10))
    trusted_mask = direct_observation_mask | support_fill_keep_mask | temporal_fill_keep_mask | seed_mask
    supported_mask = support_positive >= support_floor
    confident_mask = conf >= RECON_CONF_KEEP_FLOOR
    strong_conf_mask = conf >= max(RECON_CONF_KEEP_FLOOR + 0.08, 0.18)

    keep_mask = mask & (
        trusted_mask |
        (supported_mask & confident_mask) |
        strong_conf_mask
    )
    pruned_mask = mask & (~keep_mask)
    if np.any(pruned_mask):
        u[pruned_mask] = 0.0
        v[pruned_mask] = 0.0
        conf[pruned_mask] = 0.0

    recon_mask_out = keep_mask.astype(np.float32)
    support_domain_mask = base_domain | trusted_mask
    effective_domain_mask = support_domain_mask | keep_mask
    return (
        u,
        v,
        conf,
        recon_mask_out,
        int(np.sum(pruned_mask)),
        support_domain_mask,
        effective_domain_mask,
    )


def _forecast_next_wind_field(
    recon_u,
    recon_v,
    recon_conf,
    recon_mask,
    support_strength,
    physics_weight_3d,
    where2comm_targets,
    prev_recon_state,
    curr_source_index,
):
    """生成一步前瞻风场预测。

    目标不是替代未来真正的神经网络时序预测器，而是先提供一个工程上
    可运行、可解释、可在飞机端部署的 baseline forecast：

    1. 若存在前一连续帧，则利用当前-前一帧的变化量做一阶外推；
    2. 对 support_strength 高、physics_weight 高的区域保留更多惯性；
    3. 对 Where2Comm 选中的高信息体素，适度提高预测置信度；
    4. 若当前帧与上一帧不连续，则退化为“当前重构即当前预测”。

    这相当于把：
    - Vision Mamba 的序列上下文思路
    - 实时协同感知中的高信息区域优先传播
    做成一个不依赖训练的轻量预测基线。
    """
    forecast_u = np.asarray(recon_u, dtype=np.float32).copy()
    forecast_v = np.asarray(recon_v, dtype=np.float32).copy()
    forecast_conf = np.asarray(recon_conf, dtype=np.float32).copy() * FORECAST_CONF_DECAY
    forecast_mask = np.asarray(recon_mask, dtype=np.float32).copy()

    if prev_recon_state is not None:
        prev_idx = int(prev_recon_state.get("source_index", -1))
        if curr_source_index >= 0 and prev_idx >= 0 and abs(curr_source_index - prev_idx) <= max(1, TEMPORAL_BG_MAX_GAP):
            prev_u = np.asarray(prev_recon_state.get("recon_u", []), dtype=np.float32)
            prev_v = np.asarray(prev_recon_state.get("recon_v", []), dtype=np.float32)
            prev_conf = np.asarray(prev_recon_state.get("recon_conf", []), dtype=np.float32)
            prev_mask = np.asarray(prev_recon_state.get("recon_mask", []), dtype=np.float32)
            if prev_u.shape == forecast_u.shape:
                delta_u = forecast_u - prev_u
                delta_v = forecast_v - prev_v
                inertial_gain = np.clip(
                    FORECAST_BLEND * (0.50 + 0.50 * np.asarray(support_strength, dtype=np.float32))
                    * (0.50 + 0.50 * np.asarray(physics_weight_3d, dtype=np.float32)),
                    0.0,
                    0.45,
                )
                valid_prev = prev_mask > 0
                forecast_u[valid_prev] = forecast_u[valid_prev] + inertial_gain[valid_prev] * delta_u[valid_prev]
                forecast_v[valid_prev] = forecast_v[valid_prev] + inertial_gain[valid_prev] * delta_v[valid_prev]
                forecast_conf[valid_prev] = np.maximum(
                    forecast_conf[valid_prev],
                    np.clip(prev_conf[valid_prev] * FORECAST_CONF_DECAY, 0.05, 0.75),
                )
                forecast_mask[valid_prev] = 1.0

    joint_idx = np.asarray(where2comm_targets.get("joint_idx", []), dtype=np.uint32)
    if joint_idx.size > 0:
        z, y, x = _linear_to_zyx(joint_idx.astype(np.int64), recon_u.shape[1], recon_u.shape[2])
        keep = (
            (z >= 0) & (z < forecast_u.shape[0]) &
            (y >= 0) & (y < forecast_u.shape[1]) &
            (x >= 0) & (x < forecast_u.shape[2])
        )
        if np.any(keep):
            forecast_conf[z[keep], y[keep], x[keep]] = np.clip(
                forecast_conf[z[keep], y[keep], x[keep]] + FORECAST_COMM_CONF_BOOST,
                0.0,
                1.0,
            )
            forecast_mask[z[keep], y[keep], x[keep]] = 1.0

    return (
        forecast_u.astype(np.float32, copy=False),
        forecast_v.astype(np.float32, copy=False),
        forecast_conf.astype(np.float32, copy=False),
        forecast_mask.astype(np.float32, copy=False),
    )


def _compute_hazard_proxies(forecast_u, forecast_v, support_strength, pinn_divergence_3d, pinn_smoothness_3d):
    """计算飞机端实时监控更关心的危险区代理量。

    目标不是精确替代湍流或颠簸物理诊断，而是构建适合机载端部署的
    风场变化风险提示：

    - shear proxy：风切变强度
    - turbulence proxy：局地扰动/不稳定性代理
    - alert mask：危险区域二值提示
    """
    u = np.asarray(forecast_u, dtype=np.float32)
    v = np.asarray(forecast_v, dtype=np.float32)

    du_dx = np.zeros_like(u)
    du_dy = np.zeros_like(u)
    dv_dx = np.zeros_like(v)
    dv_dy = np.zeros_like(v)
    du_dx[:, :, 1:-1] = 0.5 * (u[:, :, 2:] - u[:, :, :-2])
    du_dy[:, 1:-1, :] = 0.5 * (u[:, 2:, :] - u[:, :-2, :])
    dv_dx[:, :, 1:-1] = 0.5 * (v[:, :, 2:] - v[:, :, :-2])
    dv_dy[:, 1:-1, :] = 0.5 * (v[:, 2:, :] - v[:, :-2, :])

    shear_3d = np.sqrt(du_dx ** 2 + du_dy ** 2 + dv_dx ** 2 + dv_dy ** 2).astype(np.float32, copy=False)
    if np.max(shear_3d) > 0:
        shear_norm = shear_3d / float(np.max(shear_3d))
    else:
        shear_norm = shear_3d

    div_abs = np.abs(np.asarray(pinn_divergence_3d, dtype=np.float32))
    smooth_abs = np.asarray(pinn_smoothness_3d, dtype=np.float32)
    if np.max(div_abs) > 0:
        div_norm = div_abs / float(np.max(div_abs))
    else:
        div_norm = div_abs
    if np.max(smooth_abs) > 0:
        smooth_norm = smooth_abs / float(np.max(smooth_abs))
    else:
        smooth_norm = smooth_abs

    turbulence_3d = np.clip(
        0.45 * shear_norm +
        0.25 * div_norm +
        0.20 * smooth_norm +
        0.10 * np.asarray(support_strength, dtype=np.float32),
        0.0,
        1.0,
    ).astype(np.float32, copy=False)

    alert_mask_3d = (
        (shear_norm >= HAZARD_SHEAR_ALERT) |
        (turbulence_3d >= HAZARD_TURB_ALERT)
    ).astype(np.float32, copy=False)

    return shear_norm.astype(np.float32, copy=False), turbulence_3d, alert_mask_3d


def _build_coord_set(df):
    """把体素 DataFrame 转成坐标集合。

    这里专门用于判断不同来源是否在同一批 voxel 上高度重叠。
    目标不是追求极致性能，而是服务于 Stage-4 的诊断与保守去重逻辑。
    """
    if df is None or len(df) == 0 or not {"z", "y", "x"}.issubset(set(df.columns)):
        return set()
    z = df["z"].cast(pl.Int32, strict=False).to_numpy()
    y = df["y"].cast(pl.Int32, strict=False).to_numpy()
    x = df["x"].cast(pl.Int32, strict=False).to_numpy()
    return {(int(zz), int(yy), int(xx)) for zz, yy, xx in zip(z, y, x)}


def _build_direct_source_maps(*frames):
    source_map = {}
    for df in frames:
        if df is None or len(df) == 0 or not {"z", "y", "x", "u", "v"}.issubset(set(df.columns)):
            continue
        z = df["z"].cast(pl.Int32, strict=False).to_numpy()
        y = df["y"].cast(pl.Int32, strict=False).to_numpy()
        x = df["x"].cast(pl.Int32, strict=False).to_numpy()
        u = df["u"].cast(pl.Float32, strict=False).to_numpy()
        v = df["v"].cast(pl.Float32, strict=False).to_numpy()
        if "qc_weight" in df.columns:
            q = df["qc_weight"].cast(pl.Float32, strict=False).fill_null(0.0).to_numpy()
        elif "obs_conf" in df.columns:
            q = df["obs_conf"].cast(pl.Float32, strict=False).fill_null(0.0).to_numpy()
        else:
            q = np.ones(len(df), dtype=np.float32)
        for zz, yy, xx, uu, vv, qq in zip(z, y, x, u, v, q):
            key = (int(zz), int(yy), int(xx))
            source_map.setdefault(key, []).append((float(uu), float(vv), float(np.clip(qq, 0.0, 1.0))))
    return source_map


def _build_direct_agreement_fields(z_dim, h_dim, w_dim, wind_grouped, amdar_grouped, turb_grouped):
    agreement = np.zeros((z_dim, h_dim, w_dim), dtype=np.float32)
    source_count = np.zeros((z_dim, h_dim, w_dim), dtype=np.float32)
    source_map = _build_direct_source_maps(wind_grouped, amdar_grouped, turb_grouped)
    if not source_map:
        return agreement, source_count

    for (zz, yy, xx), values in source_map.items():
        if not (0 <= zz < z_dim and 0 <= yy < h_dim and 0 <= xx < w_dim):
            continue
        arr = np.asarray(values, dtype=np.float32)
        uv = arr[:, :2]
        w = np.clip(arr[:, 2], 0.05, 1.0)
        ws = float(np.sum(w))
        if ws <= 1e-8:
            continue
        mean_uv = np.sum(uv * w[:, None], axis=0) / ws
        dev = np.sqrt(np.sum(((uv - mean_uv[None, :]) ** 2) * w[:, None]) / ws)
        if arr.shape[0] == 1:
            agree = float(np.clip(0.55 + 0.25 * float(np.mean(w)), 0.0, 1.0))
        else:
            agree = float(np.clip(1.0 - dev / max(1e-6, DIRECT_AGREEMENT_SCALE_MS), 0.0, 1.0))
        agreement[zz, yy, xx] = agree
        source_count[zz, yy, xx] = float(min(arr.shape[0], 3) / 3.0)
    return agreement, source_count


# [改动说明] 这里加入 wind_grouped 与 amdar/turb 的高重叠去重，
# 避免同一批风体素在 Stage-4 中被重复计权。
def _dedupe_primary_wind_source(wind_grouped, amdar_grouped, turb_grouped):
    """避免在 Stage-4 中把同一批 wind voxels 与 AMDAR 重复计权。

    现象背景：
    - Stage-2 的 `wind_grouped` 是所有风源的总聚合；
    - `amdar_grouped` / `turb_grouped` 又是分源聚合；
    - 如果当前帧的风源几乎全部来自 AMDAR，那么 Stage-4 同时使用
      `wind_grouped + amdar_grouped` 时，会把同一批风体素重复加权。

    处理策略：
    - 如果 `wind_grouped` 和 `{amdar,turb}` 的重叠比例很高，就保守地剔除重复坐标；
    - 如果重叠比例不高，则不做处理，避免误删混合源信号。
    """
    if len(wind_grouped) == 0:
        return wind_grouped, 0.0, 0, 0

    wind_coords = _build_coord_set(wind_grouped)
    other_coords = _build_coord_set(amdar_grouped) | _build_coord_set(turb_grouped)
    if not wind_coords or not other_coords:
        return wind_grouped, 0.0, 0, 0

    overlap = wind_coords & other_coords
    overlap_ratio = float(len(overlap) / max(1, len(wind_coords)))

    # 只有在高重叠时才做去重，防止把少量混合源风体素也一并删掉。
    if overlap_ratio < 0.85:
        return wind_grouped, overlap_ratio, 0, 0

    other_map = _build_direct_source_maps(amdar_grouped, turb_grouped)
    keep_mask = []
    qc_scale = []
    conflict_keep_count = 0
    z = wind_grouped["z"].cast(pl.Int32, strict=False).to_numpy()
    y = wind_grouped["y"].cast(pl.Int32, strict=False).to_numpy()
    x = wind_grouped["x"].cast(pl.Int32, strict=False).to_numpy()
    u = wind_grouped["u"].cast(pl.Float32, strict=False).to_numpy() if "u" in wind_grouped.columns else np.zeros(len(wind_grouped), dtype=np.float32)
    v = wind_grouped["v"].cast(pl.Float32, strict=False).to_numpy() if "v" in wind_grouped.columns else np.zeros(len(wind_grouped), dtype=np.float32)
    for zz, yy, xx, uu, vv in zip(z, y, x, u, v):
        key = (int(zz), int(yy), int(xx))
        if key not in overlap:
            keep_mask.append(True)
            qc_scale.append(1.0)
            continue
        keep_this = False
        scale = 0.0
        if key in other_map:
            ref = np.asarray(other_map[key], dtype=np.float32)
            ref_w = np.clip(ref[:, 2], 0.05, 1.0)
            ref_uv = np.sum(ref[:, :2] * ref_w[:, None], axis=0) / max(1e-6, float(np.sum(ref_w)))
            diff = float(np.sqrt((float(uu) - float(ref_uv[0])) ** 2 + (float(vv) - float(ref_uv[1])) ** 2))
            if diff >= WIND_PRIMARY_CONFLICT_KEEP_MS:
                keep_this = True
                scale = 0.35
                conflict_keep_count += 1
        keep_mask.append(keep_this)
        qc_scale.append(scale)
    filtered = wind_grouped.with_columns(
        pl.Series("_keep_wind_primary", keep_mask),
        pl.Series("_qc_scale", qc_scale, dtype=pl.Float32),
    ).filter(pl.col("_keep_wind_primary"))
    if len(filtered) > 0 and "qc_weight" in filtered.columns:
        filtered = filtered.with_columns((pl.col("qc_weight") * pl.col("_qc_scale")).clip(0.0, 1.0).alias("qc_weight"))
    if len(filtered) > 0 and "obs_conf" in filtered.columns:
        filtered = filtered.with_columns((pl.col("obs_conf") * pl.col("_qc_scale")).clip(0.0, 1.0).alias("obs_conf"))
    filtered = filtered.drop(["_keep_wind_primary", "_qc_scale"])
    removed = int(len(wind_grouped) - len(filtered))
    return filtered, overlap_ratio, removed, int(conflict_keep_count)


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


def _build_trajectory_volume(loc_grouped, z_dim, h_dim, w_dim):
    vol = np.zeros((z_dim, h_dim, w_dim), dtype=np.float32)
    if len(loc_grouped) == 0 or not {"z", "y", "x"}.issubset(set(loc_grouped.columns)):
        return vol
    density = (
        loc_grouped["density"].cast(pl.Float32, strict=False).fill_null(1.0).to_numpy()
        if "density" in loc_grouped.columns
        else np.ones(len(loc_grouped), dtype=np.float32)
    )
    z = loc_grouped["z"].cast(pl.Int32, strict=False).to_numpy()
    y = loc_grouped["y"].cast(pl.Int32, strict=False).to_numpy()
    x = loc_grouped["x"].cast(pl.Int32, strict=False).to_numpy()
    keep = (
        (z >= 0) & (z < z_dim) &
        (y >= 0) & (y < h_dim) &
        (x >= 0) & (x < w_dim)
    )
    if not np.any(keep):
        return vol
    density = density[keep]
    if density.size > 0:
        density = np.log1p(np.clip(density, 0.0, None))
        density = density / max(1e-6, float(np.max(density)))
    vol[z[keep], y[keep], x[keep]] = density.astype(np.float32, copy=False)
    return vol


def _flight_pack_to_seed_df(flight_pack, h_dim, w_dim):
    if not flight_pack:
        return pl.DataFrame()
    ids = np.asarray(flight_pack.get("flight_agent_ids", []))
    offsets = np.asarray(flight_pack.get("flight_offsets", []), dtype=np.int64)
    idx_flat = np.asarray(flight_pack.get("flight_idx_flat", []), dtype=np.int64)
    u_flat = np.asarray(flight_pack.get("flight_u_flat", []), dtype=np.float32)
    v_flat = np.asarray(flight_pack.get("flight_v_flat", []), dtype=np.float32)
    c_flat = np.asarray(flight_pack.get("flight_count_flat", []), dtype=np.float32)
    has_wind = np.asarray(flight_pack.get("flight_has_wind_obs", []), dtype=np.float32)
    comm_weight = np.asarray(flight_pack.get("flight_comm_weight", []), dtype=np.float32)
    st_like = np.asarray(flight_pack.get("flight_st_likelihood", []), dtype=np.float32)
    mask = np.asarray(flight_pack.get("flight_mask", []), dtype=np.uint8)

    if ids.size == 0 or offsets.size != ids.size + 1 or idx_flat.size == 0:
        return pl.DataFrame()

    records = []
    for i in range(ids.size):
        if i >= mask.size or mask[i] <= 0:
            continue
        wind_gate = float(has_wind[i]) if i < has_wind.size else 0.0
        if wind_gate <= 0.0:
            continue
        sl = slice(int(offsets[i]), int(offsets[i + 1]))
        own_idx = idx_flat[sl]
        if own_idx.size == 0:
            continue
        own_u = u_flat[sl] if sl.stop <= u_flat.size else np.zeros(own_idx.size, dtype=np.float32)
        own_v = v_flat[sl] if sl.stop <= v_flat.size else np.zeros(own_idx.size, dtype=np.float32)
        own_c = c_flat[sl] if sl.stop <= c_flat.size else np.ones(own_idx.size, dtype=np.float32)
        z, y, x = _linear_to_zyx(own_idx, h_dim, w_dim)
        obs_conf = float(np.clip(
            0.25 + 0.35 * wind_gate
            + 0.20 * (float(comm_weight[i]) if i < comm_weight.size else 0.0)
            + 0.20 * (float(st_like[i]) if i < st_like.size else 0.0),
            0.15,
            0.95,
        ))
        for zi, yi, xi, uu, vv, cc in zip(z, y, x, own_u, own_v, own_c):
            records.append(
                {
                    "z": int(zi),
                    "y": int(yi),
                    "x": int(xi),
                    "u": float(uu),
                    "v": float(vv),
                    "obs_count": float(max(1.0, cc)),
                    "obs_conf": obs_conf,
                }
            )
    return pl.DataFrame(records) if records else pl.DataFrame()


def _build_support_strength(trajectory_3d, motion_grouped, flight_seed_df, z_dim, h_dim, w_dim):
    support = np.asarray(trajectory_3d, dtype=np.float32).copy()
    if len(motion_grouped) > 0 and {"z", "y", "x"}.issubset(set(motion_grouped.columns)):
        z = motion_grouped["z"].cast(pl.Int32, strict=False).to_numpy()
        y = motion_grouped["y"].cast(pl.Int32, strict=False).to_numpy()
        x = motion_grouped["x"].cast(pl.Int32, strict=False).to_numpy()
        cnt = (
            motion_grouped["motion_count"].cast(pl.Float32, strict=False).fill_null(1.0).to_numpy()
            if "motion_count" in motion_grouped.columns
            else np.ones(len(motion_grouped), dtype=np.float32)
        )
        keep = (
            (z >= 0) & (z < z_dim) &
            (y >= 0) & (y < h_dim) &
            (x >= 0) & (x < w_dim)
        )
        if np.any(keep):
            cnt = np.log1p(np.clip(cnt[keep], 0.0, None))
            cnt = cnt / max(1e-6, float(np.max(cnt)))
            support[z[keep], y[keep], x[keep]] = np.maximum(support[z[keep], y[keep], x[keep]], 0.55 + 0.45 * cnt)
    if len(flight_seed_df) > 0:
        z = flight_seed_df["z"].cast(pl.Int32, strict=False).to_numpy()
        y = flight_seed_df["y"].cast(pl.Int32, strict=False).to_numpy()
        x = flight_seed_df["x"].cast(pl.Int32, strict=False).to_numpy()
        obs_conf = flight_seed_df["obs_conf"].cast(pl.Float32, strict=False).fill_null(0.35).to_numpy()
        keep = (
            (z >= 0) & (z < z_dim) &
            (y >= 0) & (y < h_dim) &
            (x >= 0) & (x < w_dim)
        )
        if np.any(keep):
            support[z[keep], y[keep], x[keep]] = np.maximum(support[z[keep], y[keep], x[keep]], obs_conf[keep])
    return np.clip(support, 0.0, 1.0)


def _build_domain_mask(z_dim, h_dim, w_dim, support_strength=None, grouped_frames=None):
    domain = np.zeros((z_dim, h_dim, w_dim), dtype=bool)
    if support_strength is not None:
        domain |= np.asarray(support_strength) > 0
    grouped_frames = grouped_frames or []
    for df in grouped_frames:
        if df is None or len(df) == 0 or not {"z", "y", "x"}.issubset(set(df.columns)):
            continue
        z = df["z"].cast(pl.Int32, strict=False).to_numpy()
        y = df["y"].cast(pl.Int32, strict=False).to_numpy()
        x = df["x"].cast(pl.Int32, strict=False).to_numpy()
        keep = (
            (z >= 0) & (z < z_dim) &
            (y >= 0) & (y < h_dim) &
            (x >= 0) & (x < w_dim)
        )
        if np.any(keep):
            domain[z[keep], y[keep], x[keep]] = True
    return domain


def _support_guided_fill(recon_u, recon_v, recon_conf, recon_mask, support_strength):
    known_idx = np.argwhere(recon_mask > 0)
    if known_idx.size == 0:
        return 0
    candidate_idx = np.argwhere((support_strength > 0) & (recon_mask <= 0))
    if candidate_idx.size == 0:
        return 0
    candidate_scores = support_strength[candidate_idx[:, 0], candidate_idx[:, 1], candidate_idx[:, 2]]
    candidate_idx = candidate_idx[np.argsort(-candidate_scores)]

    known_u = recon_u[recon_mask > 0]
    known_v = recon_v[recon_mask > 0]
    known_conf = recon_conf[recon_mask > 0]
    filled = 0
    max_fill = min(int(SUPPORT_MAX_FILL), int(candidate_idx.shape[0]))

    for zi, yi, xi in candidate_idx[:max_fill]:
        support_val = float(support_strength[zi, yi, xi])
        if support_val < SUPPORT_FILL_MIN_SUPPORT:
            continue
        delta = known_idx - np.array([zi, yi, xi], dtype=np.int32)
        gate = (
            (np.abs(delta[:, 0]) <= SUPPORT_RADIUS_Z) &
            (np.abs(delta[:, 1]) <= SUPPORT_RADIUS_XY) &
            (np.abs(delta[:, 2]) <= SUPPORT_RADIUS_XY)
        )
        local = np.where(gate)[0]
        if local.size < max(1, SUPPORT_FILL_MIN_NEIGHBORS):
            continue
        dist2 = np.sum(delta[local].astype(np.float32) ** 2, axis=1)
        order = np.argsort(dist2)[:10]
        local = local[order]
        dist2 = dist2[order]
        w = 1.0 / (dist2 + 1.0)
        w *= np.clip(known_conf[local], 0.05, 1.0)
        ws = float(np.sum(w))
        if ws <= 1e-8:
            continue
        fill_u = float(np.sum(known_u[local] * w) / ws)
        fill_v = float(np.sum(known_v[local] * w) / ws)
        local_spread = float(
            np.sqrt(
                np.sum(((known_u[local] - fill_u) ** 2 + (known_v[local] - fill_v) ** 2) * w) / ws
            )
        )
        if local_spread > SUPPORT_FILL_MAX_LOCAL_SPREAD:
            continue
        recon_u[zi, yi, xi] = fill_u
        recon_v[zi, yi, xi] = fill_v
        coherence = float(np.clip(1.0 - local_spread / max(1e-6, SUPPORT_FILL_MAX_LOCAL_SPREAD), 0.0, 1.0))
        mean_local_conf = float(np.mean(np.clip(known_conf[local], 0.0, 1.0)))
        recon_conf[zi, yi, xi] = float(
            np.clip(
                0.12 + 0.48 * support_val + 0.18 * coherence + 0.16 * mean_local_conf,
                0.10,
                0.78,
            )
        )
        recon_mask[zi, yi, xi] = 1.0
        filled += 1
    return filled


def _apply_temporal_background(
    recon_u,
    recon_v,
    recon_conf,
    recon_mask,
    support_strength,
    prev_recon_state,
    curr_source_index,
):
    """用前一帧的重构结果作为当前帧的时序背景场。

    文献启发：
    - Vision Mamba 的核心思想之一，是利用序列上下文恢复缺失区域；
    - 4DVar / Kalman filtering 类方法的核心思想，是用前一时刻状态作为背景场。

    在当前工程里，我们先做一个最保守、最不破坏现有链路的落地版本：
    - 只有当前帧与前一帧在原始序列中相邻时才启用；
    - 只在“当前 support 区域内但当前重构缺失”的位置使用上一帧补充；
    - 赋予较低置信度，不与当前直接观测竞争。
    """
    if prev_recon_state is None:
        return 0
    prev_idx = int(prev_recon_state.get("source_index", -1))
    if curr_source_index < 0 or prev_idx < 0:
        return 0
    if abs(curr_source_index - prev_idx) > max(1, TEMPORAL_BG_MAX_GAP):
        return 0

    prev_mask = np.asarray(prev_recon_state.get("recon_mask", []), dtype=np.float32)
    prev_u = np.asarray(prev_recon_state.get("recon_u", []), dtype=np.float32)
    prev_v = np.asarray(prev_recon_state.get("recon_v", []), dtype=np.float32)
    prev_conf = np.asarray(prev_recon_state.get("recon_conf", []), dtype=np.float32)
    if prev_mask.size == 0 or prev_u.shape != recon_u.shape:
        return 0

    fill_mask = (
        (support_strength > 0.0)
        & (recon_mask <= 0)
        & (prev_mask > 0)
    )
    fill_count = int(np.sum(fill_mask))
    if fill_count <= 0:
        return 0

    recon_u[fill_mask] = prev_u[fill_mask]
    recon_v[fill_mask] = prev_v[fill_mask]
    recon_conf[fill_mask] = np.clip(prev_conf[fill_mask] * TEMPORAL_BG_BLEND, 0.05, 0.35)
    recon_mask[fill_mask] = 1.0
    return fill_count


def _physics_guided_relaxation(recon_u, recon_v, recon_conf, recon_mask, support_strength):
    """对低置信度重构区做轻量物理引导平滑。

    文献启发：
    - PINN / 变分反演类方法强调“物理约束 + 观测约束”；
    - PyDDA 强调风场的平滑性和一致性；
    - 当前工程还没有进入真正的神经网络训练，因此这里先使用一个
      可运行的轻量近似：对低置信度区域做局部邻域一致性松弛。

    这不是严格的 NS/PINN 约束求解，但它在工程上等价于：
    - 保持高置信度种子不动；
    - 对低置信度补全区域做有限步平滑；
    - 用 support_strength 控制哪些区域允许被“物理背景”拉动。
    """
    steps = max(0, int(RECON_RELAX_STEPS))
    if steps <= 0:
        return 0

    movable = (recon_mask > 0) & (recon_conf < 0.75) & (support_strength > 0)
    if not np.any(movable):
        return 0

    for _ in range(steps):
        u_pad = np.pad(recon_u, ((1, 1), (1, 1), (1, 1)), mode="edge")
        v_pad = np.pad(recon_v, ((1, 1), (1, 1), (1, 1)), mode="edge")
        u_avg = (
            u_pad[1:-1, 1:-1, :-2] + u_pad[1:-1, 1:-1, 2:] +
            u_pad[1:-1, :-2, 1:-1] + u_pad[1:-1, 2:, 1:-1] +
            u_pad[:-2, 1:-1, 1:-1] + u_pad[2:, 1:-1, 1:-1]
        ) / 6.0
        v_avg = (
            v_pad[1:-1, 1:-1, :-2] + v_pad[1:-1, 1:-1, 2:] +
            v_pad[1:-1, :-2, 1:-1] + v_pad[1:-1, 2:, 1:-1] +
            v_pad[:-2, 1:-1, 1:-1] + v_pad[2:, 1:-1, 1:-1]
        ) / 6.0
        blend = np.clip(
            RECON_RELAX_BLEND * (1.0 - recon_conf) * (0.35 + 0.65 * support_strength),
            0.0,
            0.35,
        )
        recon_u[movable] = (1.0 - blend[movable]) * recon_u[movable] + blend[movable] * u_avg[movable]
        recon_v[movable] = (1.0 - blend[movable]) * recon_v[movable] + blend[movable] * v_avg[movable]
    return steps


def _masked_mean(values, mask):
    masked = np.asarray(values, dtype=np.float32)[np.asarray(mask) > 0]
    return float(np.mean(masked)) if masked.size > 0 else 0.0


def _masked_quantile(values, mask, q):
    masked = np.asarray(values, dtype=np.float32)[np.asarray(mask) > 0]
    return float(np.quantile(masked, q)) if masked.size > 0 else 0.0


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
    """打印适合终端和日志文件查看的文本进度条。"""
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


# [改动说明] Stage-4 复用与 Stage-3 一致的选帧规则，
# 保证两阶段处理的是同一组 frame。
def _select_stage2_frames(stage2_summary):
    """根据环境变量选择要进入 Stage-4 的帧。

    选择规则和 Stage-3 保持一致，避免两阶段处理的帧集合不一致：

    1. `WIND_FRAME_INDICES`
       - 精确指定原始 Stage-2 下标；
       - 适合抽取 `stage2_topwind.log` 中的高风帧。

    2. `WIND_FRAME_OFFSET`
       - 跳过前若干帧，再连续取；
       - 适合快速避开数据最前面的低风稀疏区段。

    3. `WIND_MAX_FRAMES`
       - 最终保留的帧数上限。

    和 Stage-3 一样，这里会补充 `source_index` 字段，方便 summary 回溯。
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
            print(f"[Stage-4][WARN] 忽略非法 WIND_FRAME_INDICES 项: {bad_tokens}")
        # 精确抽帧时仍按原始 source_index 排序，保证后续时序触发逻辑有意义。
        selected = sorted(selected, key=lambda x: int(x.get("source_index", -1)))
        print(f"[Stage-4] 按精确下标选帧: {[x['source_index'] for x in selected]}")
        return selected

    frame_offset = max(0, int(os.environ.get("WIND_FRAME_OFFSET", "0") or "0"))
    if frame_offset > 0:
        indexed = indexed[frame_offset:]
        print(f"[Stage-4] 跳过前 {frame_offset} 帧")

    max_frames_env = os.environ.get("WIND_MAX_FRAMES")
    max_frames = None
    if max_frames_env not in (None, "", "0"):
        try:
            max_frames = max(1, int(max_frames_env))
        except ValueError:
            print(f"[Stage-4][WARN] 无法解析 WIND_MAX_FRAMES={max_frames_env!r}，将忽略该限制")
            max_frames = None
    if max_frames is not None:
        indexed = indexed[:max_frames]
        print(f"[Stage-4] 小批量试跑模式：仅处理前 {len(indexed)} 帧")
    return indexed


# [改动说明] 触发器只看少量轻量统计，不直接吃完整 frame dict，
# 这样更稳、更可解释。
def _build_frame_meta(frame):
    """抽取触发器真正需要的轻量元信息。

    这里故意只保留“随帧变化、且能代表事件强度”的少量统计量：
    - 风体素数量
    - 运动体素数量
    - 风边数量
    - 可通信 agent 数量
    - 重构种子强度

    触发器只看这些轻量指标，避免把完整 frame dict 直接塞进去后，
    因字段过多、含义混杂而导致误判。
    """
    return {
        "source_index": int(frame.get("source_index", -1)),
        "wind_voxels": int(len(frame["wind_grouped"])),
        "motion_voxels": int(len(frame["motion_grouped"])),
        "flight_ff_wind_edges": int(np.sum(np.asarray(frame["flight_pack"].get("ff_wind_allowed", []), dtype=np.float32) > 0.0)),
        "flight_comm_allowed_agents": int(np.sum(np.asarray(frame["flight_pack"].get("flight_comm_allowed", []), dtype=np.float32) > 0.5)),
        "recon_seed_strength": float(frame.get("recon_seed_strength", 0.0)),
    }


def _infer_hw_from_vox(vox, fallback_shape=(0, 0)):
    """优先从 Stage 2 的 radar 图恢复 H/W。"""
    if STAGE2_RADAR_IMG in vox.files:
        radar_img = vox[STAGE2_RADAR_IMG]
        return radar_img.shape[0], radar_img.shape[1], radar_img
    if "radar_2d" in vox.files:
        radar_img = vox["radar_2d"]
        return radar_img.shape[0], radar_img.shape[1], radar_img
    if "radar_shape" in vox.files:
        shape = tuple(int(x) for x in vox["radar_shape"].tolist())
        return shape[0], shape[1], np.zeros(shape, dtype=np.uint8)
    return fallback_shape[0], fallback_shape[1], np.zeros(fallback_shape, dtype=np.uint8)


# [改动说明] 这里改成“相对变化 + 绝对变化”双门槛触发器，
# 并对不连续抽帧直接标记为 discontiguous_frame_gap。
def _should_trigger_reconstruction(curr_item, prev_item=None):
    """判断当前帧是否值得做一次完整风场重构。

    设计思路：
    - 风场重构是重计算操作，不必每帧都做；
    - 当风观测、运动信息或通信结构出现明显变化时，再触发重构；
    - 如果没有上一帧，则默认触发，保证首帧有初始风场；
    - 触发器是轻量的事件检测器，不是最终物理判别器。
    """
    if prev_item is None:
        return True, "first_frame"

    curr_src = int(curr_item.get("source_index", -1))
    prev_src = int(prev_item.get("source_index", -1))
    if curr_src >= 0 and prev_src >= 0 and abs(curr_src - prev_src) > 1:
        # 对精确抽帧或大跨度跳帧的测试，不把相隔很远的帧当成连续时序，
        # 否则触发原因会被“无意义的大跳变”主导。
        return True, f"discontiguous_frame_gap={abs(curr_src - prev_src)}"

    curr_wind = float(curr_item.get("wind_voxels", 0))
    prev_wind = float(prev_item.get("wind_voxels", 0))
    curr_motion = float(curr_item.get("motion_voxels", 0))
    prev_motion = float(prev_item.get("motion_voxels", 0))
    curr_ff = float(curr_item.get("flight_ff_wind_edges", 0))
    prev_ff = float(prev_item.get("flight_ff_wind_edges", 0))
    curr_comm = float(curr_item.get("flight_comm_allowed_agents", 0))
    prev_comm = float(prev_item.get("flight_comm_allowed_agents", 0))
    curr_seed = float(curr_item.get("recon_seed_strength", 0.0))
    prev_seed = float(prev_item.get("recon_seed_strength", 0.0))

    def _rel_change(a, b):
        denom = max(1.0, abs(b))
        return abs(a - b) / denom

    wind_delta = abs(curr_wind - prev_wind)
    motion_delta = abs(curr_motion - prev_motion)
    ff_delta = abs(curr_ff - prev_ff)
    comm_delta = abs(curr_comm - prev_comm)
    seed_delta = abs(curr_seed - prev_seed)

    wind_jump = _rel_change(curr_wind, prev_wind)
    motion_jump = _rel_change(curr_motion, prev_motion)
    ff_jump = _rel_change(curr_ff, prev_ff)
    comm_jump = _rel_change(curr_comm, prev_comm)
    seed_jump = _rel_change(curr_seed, prev_seed)

    # 触发规则采用“相对变化 + 绝对变化”双重门槛。
    # 这样可以避免：
    # - 从 1 个风体素变成 2 个风体素时，相对变化=100%，但实际物理意义并不强；
    # - 从 200 条风边变成 150 条风边时，相对变化不夸张，但绝对变化已经很明显。
    wind_event = curr_wind >= 8 and wind_delta >= 4 and wind_jump >= 0.35
    motion_event = max(curr_motion, prev_motion) >= 40 and motion_delta >= 10 and motion_jump >= 0.20
    ff_event = max(curr_ff, prev_ff) >= 40 and ff_delta >= 15 and ff_jump >= 0.20
    comm_event = max(curr_comm, prev_comm) >= 15 and comm_delta >= 4 and comm_jump >= 0.15
    seed_event = curr_seed >= 120.0 and seed_delta >= 20.0 and seed_jump >= 0.15
    triggered = wind_event or motion_event or ff_event or comm_event or seed_event
    reason = (
        f"wind(delta={wind_delta:.1f},jump={wind_jump:.3f},event={int(wind_event)}), "
        f"motion(delta={motion_delta:.1f},jump={motion_jump:.3f},event={int(motion_event)}), "
        f"ff(delta={ff_delta:.1f},jump={ff_jump:.3f},event={int(ff_event)}), "
        f"comm(delta={comm_delta:.1f},jump={comm_jump:.3f},event={int(comm_event)}), "
        f"seed(delta={seed_delta:.1f},jump={seed_jump:.3f},event={int(seed_event)})"
    )
    return triggered, reason


# [改动说明] 这里是 Stage-4 的主要改动汇总点：
# 1. 原始/清洗后体素计数
# 2. wind primary 去重
# 3. flight seeds
# 4. support-guided fill
# 5. 诊断字段输出
def _prepare_frame(stage2_item, stage3_item, prev_recon_state=None):
    """准备单帧 Stage 4 打包所需的全部中间结果。"""
    vox = np.load(stage2_item["vox_path"], allow_pickle=True)
    H_DIM, W_DIM, radar_img = _infer_hw_from_vox(vox)

    flight_pack = {}
    agent_path = stage3_item["agent_path"]
    if os.path.exists(agent_path):
        with open(agent_path, "r", encoding="utf-8") as f:
            flight_pack = _json_to_flight_pack(json.load(f))

    wind_grouped_raw = _records_to_df(vox[STAGE2_WIND_RECORDS])
    loc_grouped_raw = _records_to_df(vox[STAGE2_LOC_RECORDS])
    motion_grouped_raw = _records_to_df(vox[STAGE2_MOTION_RECORDS])
    amdar_grouped_raw = _records_to_df(vox[STAGE2_AMDAR_RECORDS])
    turb_grouped_raw = _records_to_df(vox[STAGE2_TURB_RECORDS])

    wind_grouped = _sanitize_observations(wind_grouped_raw, ["z", "y", "x", "u", "v"], "wind")
    loc_grouped = _sanitize_observations(loc_grouped_raw, ["z", "y", "x", "density"], "motion")
    motion_grouped = _sanitize_observations(motion_grouped_raw, ["z", "y", "x", "u_motion", "v_motion"], "motion")
    amdar_grouped = _sanitize_observations(amdar_grouped_raw, ["z", "y", "x", "u", "v"], "amdar")
    turb_grouped = _sanitize_observations(turb_grouped_raw, ["z", "y", "x", "u", "v"], "turb")
    flight_raw_records = _records_to_df(vox[STAGE2_FLIGHT_RAW_RECORDS]) if STAGE2_FLIGHT_RAW_RECORDS in vox.files else pl.DataFrame()
    wind_grouped_primary, wind_overlap_ratio, wind_overlap_removed, wind_conflict_keep_count = _dedupe_primary_wind_source(
        wind_grouped, amdar_grouped, turb_grouped
    )

    # 额外构建一个“更宽松”的 motion 辅助视图，用于 Stage 4 重构。
    # 说明：Stage 3 只需要运动边上的压缩视图，而 Stage 4 需要更丰富的
    # 局部体素信息来做风场补全，所以这里优先从 flight_motion_records 中
    # 抽取更细粒度的轨迹/运动记录；如果没有，再退回 loc_grouped。
    raw_motion_records = _records_to_df(vox[STAGE2_FLIGHT_MOTION_RECORDS]) if STAGE2_FLIGHT_MOTION_RECORDS in vox.files else pl.DataFrame()
    if len(raw_motion_records) > 0 and {"z", "y", "x", "u_motion", "v_motion"}.issubset(set(raw_motion_records.columns)):
        motion_fine = _sanitize_observations(
            raw_motion_records.drop("flight_id") if "flight_id" in raw_motion_records.columns else raw_motion_records,
            ["z", "y", "x", "u_motion", "v_motion"],
            "motion",
        )
        # [改动说明] 这里不再直接 concat，而是重新按 voxel 聚合。
        # 否则相同 (z,y,x) 会被重复计数，导致 motion_voxels 虚高、seed 虚高。
        if len(motion_fine) > 0:
            motion_grouped = _merge_motion_views(motion_grouped, motion_fine)

    # 同时把轨迹密度场作为补充约束，避免风场只依赖少数稀疏风源。
    if len(loc_grouped) > 0 and "density" in loc_grouped.columns:
        loc_grouped = loc_grouped.with_columns(
            pl.col("density").cast(pl.Float32, strict=False).fill_null(1.0).clip(1.0, 50.0).alias("obs_conf")
        )

    trajectory_3d = _build_trajectory_volume(loc_grouped, cfg.Z_DIM, H_DIM, W_DIM)
    flight_seed_df = _flight_pack_to_seed_df(flight_pack, H_DIM, W_DIM)
    wind_for_recon = _concat_frames([wind_grouped_primary, flight_seed_df])
    motion_for_recon = _concat_frames([motion_grouped])

    # Stage 4 的重构不是只靠图传播，而是“多源融合 + 退化兜底”。
    # 当 flight-wind 边很少时，仍然可以依靠 wind / motion / amdar / turb
    # 的体素观测生成稳定的重构初值。
    recon_u, recon_v, recon_conf, recon_mask = _reconstruct_wind_field(
        cfg.Z_DIM,
        H_DIM,
        W_DIM,
        wind_for_recon,
        motion_for_recon,
        amdar_grouped,
        turb_grouped,
        enable_idw=BASE_RECON_ENABLE_IDW,
        idw_max_fill=BASE_RECON_IDW_MAX_FILL,
    )

    support_strength = _build_support_strength(trajectory_3d, motion_grouped, flight_seed_df, cfg.Z_DIM, H_DIM, W_DIM)
    support_voxel_count = int(np.count_nonzero(support_strength > 0))
    source_fields = _build_confidence_source_fields(
        cfg.Z_DIM,
        H_DIM,
        W_DIM,
        wind_grouped=wind_grouped,
        motion_grouped=motion_grouped,
        amdar_grouped=amdar_grouped,
        turb_grouped=turb_grouped,
        flight_seed_df=flight_seed_df,
    )
    direct_agreement_field, direct_source_count_field = _build_direct_agreement_fields(
        cfg.Z_DIM,
        H_DIM,
        W_DIM,
        wind_grouped=wind_grouped,
        amdar_grouped=amdar_grouped,
        turb_grouped=turb_grouped,
    )
    mask_before_support = np.asarray(recon_mask > 0, dtype=bool).copy()
    support_fill_count = _support_guided_fill(recon_u, recon_v, recon_conf, recon_mask, support_strength)
    support_fill_mask = (recon_mask > 0) & (~mask_before_support)
    temporal_fill_count = _apply_temporal_background(
        recon_u,
        recon_v,
        recon_conf,
        recon_mask,
        support_strength,
        prev_recon_state,
        int(stage2_item.get("source_index", -1)),
    )
    temporal_fill_mask = (recon_mask > 0) & (~mask_before_support) & (~support_fill_mask)
    relax_steps_used = _physics_guided_relaxation(
        recon_u,
        recon_v,
        recon_conf,
        recon_mask,
        support_strength,
    )
    relaxed_mask = (recon_mask > 0) & (~mask_before_support) & (~support_fill_mask) & (~temporal_fill_mask)
    base_recon_domain_mask = _build_domain_mask(
        cfg.Z_DIM,
        H_DIM,
        W_DIM,
        support_strength=support_strength,
        grouped_frames=[wind_grouped, motion_grouped, amdar_grouped, turb_grouped, flight_seed_df],
    )

    # 计算一个“重构种子强度”，供后续触发器使用。
    # 它不代表完整风场，只表示当前帧是否具备较强的重构条件。
    recon_seed_strength = float(
        len(wind_grouped)
        + 0.65 * len(motion_grouped)
        + 1.2 * len(amdar_grouped)
        + 0.9 * len(turb_grouped)
        + 0.4 * len(flight_seed_df)
        + 0.02 * float(stage3_item.get("flight_ff_wind_edges", 0))
    )

    # 做一层稳健收缩，避免极少数高值体素把整帧置信度抬高。
    if recon_conf.size > 0:
        direct_observation_mask = (
            (source_fields["wind"] > 0) |
            (source_fields["amdar"] > 0) |
            (source_fields["turb"] > 0)
        )
        recon_conf = _refine_recon_confidence(
            recon_u=np.nan_to_num(recon_u, nan=0.0),
            recon_v=np.nan_to_num(recon_v, nan=0.0),
            recon_conf=np.nan_to_num(recon_conf, nan=0.0),
            recon_mask=np.asarray(recon_mask, dtype=np.float32),
            support_strength=support_strength,
            source_fields=source_fields,
            temporal_fill_mask=temporal_fill_mask,
            support_fill_mask=support_fill_mask,
            relaxed_mask=relaxed_mask,
            direct_agreement_field=direct_agreement_field,
            direct_source_count_field=direct_source_count_field,
        )
        recon_u, recon_v, recon_conf, recon_mask, outlier_drop_count = _suppress_recon_outliers(
            recon_u=np.nan_to_num(recon_u, nan=0.0),
            recon_v=np.nan_to_num(recon_v, nan=0.0),
            recon_conf=np.nan_to_num(recon_conf, nan=0.0),
            recon_mask=np.asarray(recon_mask, dtype=np.float32),
            direct_observation_mask=direct_observation_mask,
        )
        (
            recon_u,
            recon_v,
            recon_conf,
            recon_mask,
            low_quality_pruned_count,
            recon_support_domain_mask,
            recon_domain_mask,
        ) = _prune_low_quality_reconstruction(
            recon_u=np.nan_to_num(recon_u, nan=0.0),
            recon_v=np.nan_to_num(recon_v, nan=0.0),
            recon_conf=np.nan_to_num(recon_conf, nan=0.0),
            recon_mask=np.asarray(recon_mask, dtype=np.float32),
            support_strength=support_strength,
            source_fields=source_fields,
            direct_observation_mask=direct_observation_mask,
            support_fill_mask=support_fill_mask,
            temporal_fill_mask=temporal_fill_mask,
            base_domain_mask=base_recon_domain_mask,
        )
    else:
        outlier_drop_count = 0
        low_quality_pruned_count = 0
        recon_support_domain_mask = np.asarray(base_recon_domain_mask, dtype=bool)
        recon_domain_mask = np.asarray(base_recon_domain_mask, dtype=bool)

    recon_support_domain_count = int(np.count_nonzero(recon_support_domain_mask))
    recon_domain_count = int(np.count_nonzero(recon_domain_mask))
    support_fill_kept_count = int(np.sum((recon_mask > 0) & support_fill_mask))
    temporal_fill_kept_count = int(np.sum((recon_mask > 0) & temporal_fill_mask))
    pinn_divergence_3d, pinn_smoothness_3d, physics_weight_3d = _compute_pinn_proxy_fields(
        np.nan_to_num(recon_u, nan=0.0),
        np.nan_to_num(recon_v, nan=0.0),
        support_strength,
    )
    where2comm_targets = _build_where2comm_targets(
        wind_grouped=wind_grouped,
        motion_grouped=motion_grouped,
        support_strength=support_strength,
        recon_conf=np.nan_to_num(recon_conf, nan=0.0),
        h_dim=H_DIM,
        w_dim=W_DIM,
    )
    diffusion_condition_4d = _build_diffusion_condition_tensors(
        radar_img=radar_img,
        trajectory_3d=trajectory_3d,
        recon_u=np.nan_to_num(recon_u, nan=0.0),
        recon_v=np.nan_to_num(recon_v, nan=0.0),
        recon_conf=np.nan_to_num(recon_conf, nan=0.0),
        support_strength=support_strength,
        physics_weight=physics_weight_3d,
    )
    forecast_u_3d, forecast_v_3d, forecast_conf_3d, forecast_mask_3d = _forecast_next_wind_field(
        recon_u=np.nan_to_num(recon_u, nan=0.0),
        recon_v=np.nan_to_num(recon_v, nan=0.0),
        recon_conf=np.nan_to_num(recon_conf, nan=0.0),
        recon_mask=np.asarray(recon_mask, dtype=np.float32),
        support_strength=support_strength,
        physics_weight_3d=physics_weight_3d,
        where2comm_targets=where2comm_targets,
        prev_recon_state=prev_recon_state,
        curr_source_index=int(stage2_item.get("source_index", -1)),
    )
    hazard_shear_3d, hazard_turbulence_3d, hazard_alert_mask_3d = _compute_hazard_proxies(
        forecast_u_3d,
        forecast_v_3d,
        support_strength,
        pinn_divergence_3d,
        pinn_smoothness_3d,
    )

    print(
        f"[Stage-4][diag] frame={stage3_item['time_str']} "
        f"wind_raw={len(wind_grouped_raw)} wind={len(wind_grouped)} "
        f"wind_primary={len(wind_grouped_primary)} overlap={wind_overlap_ratio:.3f} removed={wind_overlap_removed} conflict_keep={wind_conflict_keep_count} "
        f"motion_raw={len(motion_grouped_raw)} motion={len(motion_grouped)} "
        f"seed_vox={len(flight_seed_df)} support_vox={support_voxel_count} "
        f"support_fill={support_fill_count} temporal_fill={temporal_fill_count} relax_steps={relax_steps_used} "
        f"comm_joint={len(where2comm_targets['joint_idx'])} outlier_drop={outlier_drop_count} pruned={low_quality_pruned_count} "
        f"hazard_alert={int(np.sum(hazard_alert_mask_3d > 0))} "
        f"recon_vox={int(np.sum(recon_mask > 0))}"
    )

    return {
        "filename": stage2_item["filename"],
        "source_index": int(stage2_item.get("source_index", -1)),
        "time_str": stage2_item.get(STAGE2_TIME_STR, stage3_item["time_str"]),
        "timestamp_utc": stage2_item.get(STAGE2_TIMESTAMP_UTC, stage3_item.get("timestamp_utc")),
        "wind_grouped_raw_count": int(len(wind_grouped_raw)),
        "loc_grouped_raw_count": int(len(loc_grouped_raw)),
        "motion_grouped_raw_count": int(len(motion_grouped_raw)),
        "amdar_grouped_raw_count": int(len(amdar_grouped_raw)),
        "turb_grouped_raw_count": int(len(turb_grouped_raw)),
        "wind_grouped_primary_count": int(len(wind_grouped_primary)),
        "wind_overlap_ratio": float(wind_overlap_ratio),
        "wind_overlap_removed": int(wind_overlap_removed),
        "wind_conflict_keep_count": int(wind_conflict_keep_count),
        "wind_grouped": wind_grouped,
        "loc_grouped": loc_grouped,
        "motion_grouped": motion_grouped,
        "flight_raw_records": flight_raw_records,
        "amdar_grouped": amdar_grouped,
        "turb_grouped": turb_grouped,
        "flight_pack": flight_pack,
        "trajectory_3d": trajectory_3d,
        "support_strength": support_strength,
        "support_voxel_count": support_voxel_count,
        "direct_agreement_mean": float(np.mean(direct_agreement_field[direct_agreement_field > 0])) if np.any(direct_agreement_field > 0) else 0.0,
        "direct_agreement_3d": direct_agreement_field,
        "direct_source_count_3d": direct_source_count_field,
        "recon_support_domain_mask": recon_support_domain_mask,
        "recon_support_domain_count": recon_support_domain_count,
        "recon_domain_mask": recon_domain_mask,
        "recon_domain_count": recon_domain_count,
        "support_fill_count": support_fill_count,
        "support_fill_kept_count": support_fill_kept_count,
        "temporal_fill_count": temporal_fill_count,
        "temporal_fill_kept_count": temporal_fill_kept_count,
        "relax_steps_used": relax_steps_used,
        "outlier_drop_count": int(outlier_drop_count),
        "low_quality_pruned_count": int(low_quality_pruned_count),
        "pinn_divergence_3d": pinn_divergence_3d,
        "pinn_smoothness_3d": pinn_smoothness_3d,
        "physics_weight_3d": physics_weight_3d,
        "where2comm_targets": where2comm_targets,
        "diffusion_condition_4d": diffusion_condition_4d,
        "forecast_u_3d": forecast_u_3d,
        "forecast_v_3d": forecast_v_3d,
        "forecast_conf_3d": forecast_conf_3d,
        "forecast_mask_3d": forecast_mask_3d,
        "hazard_shear_3d": hazard_shear_3d,
        "hazard_turbulence_3d": hazard_turbulence_3d,
        "hazard_alert_mask_3d": hazard_alert_mask_3d,
        "flight_seed_df": flight_seed_df,
        "recon_u": recon_u,
        "recon_v": recon_v,
        "recon_conf": recon_conf,
        "recon_mask": recon_mask,
        "radar_img": radar_img,
        "recon_seed_strength": recon_seed_strength,
        "stage3": stage3_item,
        "stage2": stage2_item,
    }


# [改动说明] main 中加入统一选帧、进度条、增强 summary 字段与训练诊断所需统计。
def main():
    stage4_dir = os.path.join(cfg.BASE_DIR, "stage4_output")
    os.makedirs(stage4_dir, exist_ok=True)
    progress_every = max(1, int(os.environ.get("WIND_PROGRESS_EVERY", "25") or "25"))

    print("[Stage-4] 读取 Stage-2/Stage-3 中间结果...")
    stage2_summary = _load_json(os.path.join(cfg.BASE_DIR, "stage2_output", "stage2_summary.json"))
    stage3_summary, stage3_map = _load_stage3_pack_map(os.path.join(cfg.BASE_DIR, "stage3_output"))
    stage2_summary = _select_stage2_frames(stage2_summary)

    # 对齐检查：确保 Stage 2 / Stage 3 一一对应。
    stage2_times = [x["time_str"] for x in stage2_summary]
    stage3_times = [x["time_str"] for x in stage3_summary]
    missing_in_stage3 = sorted(set(stage2_times) - set(stage3_times))
    missing_in_stage2 = sorted(set(stage3_times) - set(stage2_times))
    if missing_in_stage3 or missing_in_stage2:
        print("[Stage-4][WARN] Stage-2/Stage-3 帧集合不完全对齐")
        if missing_in_stage3:
            print(f"[Stage-4][WARN] Stage-3 缺失帧数: {len(missing_in_stage3)}")
            if len(missing_in_stage3) > 8:
                print(f"[Stage-4][WARN] Stage-3 首批缺失帧: {missing_in_stage3[:8]}")
        if missing_in_stage2:
            print(f"[Stage-4][WARN] Stage-2 缺失帧数: {len(missing_in_stage2)}")
            if len(missing_in_stage2) > 8:
                print(f"[Stage-4][WARN] Stage-2 首批缺失帧: {missing_in_stage2[:8]}")

    summary = []
    prev_frame_meta = None
    prev_recon_state = None
    total_frames = len(stage2_summary)
    t_start = time.perf_counter()
    if total_frames > 0:
        print(f"[Stage-4] 计划处理 {total_frames} 帧，进度日志间隔={progress_every}")
    for i, stage2_item in enumerate(stage2_summary, 1):
        stage3_item = stage3_map.get(stage2_item["time_str"])
        if stage3_item is None:
            raise KeyError(f"Missing Stage-3 summary for time_str={stage2_item['time_str']}")

        frame = _prepare_frame(stage2_item, stage3_item, prev_recon_state=prev_recon_state)
        save_name = f"frame_{frame['time_str']}.npz"
        save_path = os.path.join(stage4_dir, save_name)
        curr_frame_meta = _build_frame_meta(frame)

        # 在保存之前先判断本帧是否为“触发帧”。
        # 触发帧才允许输出完整风场重构结果；普通帧只保留轻量状态。
        trigger, trigger_reason = _should_trigger_reconstruction(curr_frame_meta, prev_frame_meta)
        if trigger:
            recon_conf_mean = _masked_mean(frame["recon_conf"], frame["recon_mask"])
            recon_coverage_ratio = float(
                np.sum(frame["recon_mask"] > 0) /
                max(1, int(frame.get("recon_domain_count", 0)))
            )
        else:
            # 非触发帧只保留轻量状态，避免每帧都做重计算。
            recon_conf_mean = 0.0
            recon_coverage_ratio = 0.0

        # 保存最终训练样本。
        # 注意：这里沿用项目已有的 sparse/lossless 保存器，确保：
        # 1) 原始观测可复用；
        # 2) 智能体图结构可复用；
        # 3) 重构结果可作为训练初值 / 物理先验；
        # 4) 后续训练脚本可直接读取 frame_*.npz。
        _save_sparse_lossless_npz(
            save_path,
            frame["radar_img"],
            frame["radar_img"].shape[0],
            frame["radar_img"].shape[1],
            cfg.Z_DIM,
            frame["wind_grouped"],
            frame["loc_grouped"],
            frame["motion_grouped"],
            frame["amdar_grouped"],
            frame["turb_grouped"],
            frame["flight_pack"],
            float(stage3_item.get("ground_lat", (cfg.LAT_MIN + cfg.LAT_MAX) * 0.5)),
            float(stage3_item.get("ground_lon", (cfg.LON_MIN + cfg.LON_MAX) * 0.5)),
            float(stage3_item.get("ground_alt", 0.0)),
        )

        # 将 Stage 4 的重构结果和训练所需兼容字段追加进同一个 npz，
        # 这样后续导出脚本无需再去依赖 hello.py 的内部结构。
        with np.load(save_path, allow_pickle=True) as base_npz:
            payload = {k: base_npz[k] for k in base_npz.files}
        payload.update({
            "storage_mode": payload.get("storage_mode", np.array("sparse_lossless")),
            "grid_shape": np.asarray((cfg.Z_DIM, frame["radar_img"].shape[0], frame["radar_img"].shape[1]), dtype=np.int32),
            "radar_2d": np.asarray(frame["radar_img"], dtype=np.float32),
            "trajectory_3d": np.asarray(frame["trajectory_3d"], dtype=np.float32),
            "recon_u_3d": np.nan_to_num(frame["recon_u"], nan=0.0).astype(np.float32) if trigger else np.zeros_like(frame["recon_u"], dtype=np.float32),
            "recon_v_3d": np.nan_to_num(frame["recon_v"], nan=0.0).astype(np.float32) if trigger else np.zeros_like(frame["recon_v"], dtype=np.float32),
            "recon_mask_3d": np.asarray(frame["recon_mask"], dtype=np.float32) if trigger else np.zeros_like(frame["recon_mask"], dtype=np.float32),
            "recon_confidence_3d": np.nan_to_num(frame["recon_conf"], nan=0.0).astype(np.float32) if trigger else np.zeros_like(frame["recon_conf"], dtype=np.float32),
            "recon_triggered": np.array(int(bool(trigger)), dtype=np.int32),
            "recon_trigger_reason": np.array(trigger_reason, dtype="<U256"),
            # Where2Comm 风格体素通信候选。
            "comm_joint_idx": np.asarray(frame["where2comm_targets"]["joint_idx"], dtype=np.uint32),
            "comm_joint_score": np.asarray(frame["where2comm_targets"]["joint_score"], dtype=np.float32),
            "comm_wind_idx": np.asarray(frame["where2comm_targets"]["wind_idx"], dtype=np.uint32),
            "comm_wind_score": np.asarray(frame["where2comm_targets"]["wind_score"], dtype=np.float32),
            "comm_motion_idx": np.asarray(frame["where2comm_targets"]["motion_idx"], dtype=np.uint32),
            "comm_motion_score": np.asarray(frame["where2comm_targets"]["motion_score"], dtype=np.float32),
            "comm_uncertainty_idx": np.asarray(frame["where2comm_targets"]["uncertainty_idx"], dtype=np.uint32),
            "comm_uncertainty_score": np.asarray(frame["where2comm_targets"]["uncertainty_score"], dtype=np.float32),
            # PINN / physics-guided 代理量。
            "pinn_divergence_3d": np.asarray(frame["pinn_divergence_3d"], dtype=np.float32),
            "pinn_smoothness_3d": np.asarray(frame["pinn_smoothness_3d"], dtype=np.float32),
            "physics_weight_3d": np.asarray(frame["physics_weight_3d"], dtype=np.float32),
            "direct_agreement_3d": np.asarray(frame["direct_agreement_3d"], dtype=np.float32),
            "direct_source_count_3d": np.asarray(frame["direct_source_count_3d"], dtype=np.float32),
            # diffusion refinement 条件先验张量。
            "diffusion_condition_4d": np.asarray(frame["diffusion_condition_4d"], dtype=np.float32),
            # 当前 heuristic baseline 也以 PINN / diffusion prior 名义单独写出，
            # 方便后续训练脚本直接读取，不必重新拼装。
            "pinn_prior_u_3d": np.nan_to_num(frame["recon_u"], nan=0.0).astype(np.float32) if trigger else np.zeros_like(frame["recon_u"], dtype=np.float32),
            "pinn_prior_v_3d": np.nan_to_num(frame["recon_v"], nan=0.0).astype(np.float32) if trigger else np.zeros_like(frame["recon_v"], dtype=np.float32),
            "pinn_prior_confidence_3d": np.nan_to_num(frame["recon_conf"], nan=0.0).astype(np.float32) if trigger else np.zeros_like(frame["recon_conf"], dtype=np.float32),
            "diffusion_prior_u_3d": np.nan_to_num(frame["recon_u"], nan=0.0).astype(np.float32) if trigger else np.zeros_like(frame["recon_u"], dtype=np.float32),
            "diffusion_prior_v_3d": np.nan_to_num(frame["recon_v"], nan=0.0).astype(np.float32) if trigger else np.zeros_like(frame["recon_v"], dtype=np.float32),
            "diffusion_prior_confidence_3d": np.nan_to_num(frame["recon_conf"], nan=0.0).astype(np.float32) if trigger else np.zeros_like(frame["recon_conf"], dtype=np.float32),
            # 面向飞机端实时监控/预测的直接输出。
            "forecast_u_3d": np.asarray(frame["forecast_u_3d"], dtype=np.float32) if trigger else np.zeros_like(frame["forecast_u_3d"], dtype=np.float32),
            "forecast_v_3d": np.asarray(frame["forecast_v_3d"], dtype=np.float32) if trigger else np.zeros_like(frame["forecast_v_3d"], dtype=np.float32),
            "forecast_confidence_3d": np.asarray(frame["forecast_conf_3d"], dtype=np.float32) if trigger else np.zeros_like(frame["forecast_conf_3d"], dtype=np.float32),
            "forecast_mask_3d": np.asarray(frame["forecast_mask_3d"], dtype=np.float32) if trigger else np.zeros_like(frame["forecast_mask_3d"], dtype=np.float32),
            "hazard_shear_3d": np.asarray(frame["hazard_shear_3d"], dtype=np.float32) if trigger else np.zeros_like(frame["hazard_shear_3d"], dtype=np.float32),
            "hazard_turbulence_3d": np.asarray(frame["hazard_turbulence_3d"], dtype=np.float32) if trigger else np.zeros_like(frame["hazard_turbulence_3d"], dtype=np.float32),
            "hazard_alert_mask_3d": np.asarray(frame["hazard_alert_mask_3d"], dtype=np.float32) if trigger else np.zeros_like(frame["hazard_alert_mask_3d"], dtype=np.float32),
        })
        np.savez_compressed(save_path, **payload)

        summary.append(
            {
                "filename": save_name,
                "source_index": int(frame.get("source_index", -1)),
                "time_str": frame["time_str"],
                "timestamp_utc": frame["timestamp_utc"],
                "wind_voxels": int(len(frame["wind_grouped"])),
                "wind_voxels_raw": int(frame.get("wind_grouped_raw_count", 0)),
                "wind_voxels_primary": int(frame.get("wind_grouped_primary_count", 0)),
                "wind_overlap_ratio": float(frame.get("wind_overlap_ratio", 0.0)),
                "wind_overlap_removed": int(frame.get("wind_overlap_removed", 0)),
                "wind_conflict_keep_voxels": int(frame.get("wind_conflict_keep_count", 0)),
                "traj_voxels": int(len(frame["loc_grouped"])),
                "traj_voxels_raw": int(frame.get("loc_grouped_raw_count", 0)),
                "motion_voxels": int(len(frame["motion_grouped"])),
                "motion_voxels_raw": int(frame.get("motion_grouped_raw_count", 0)),
                "amdar_voxels": int(len(frame["amdar_grouped"])),
                "amdar_voxels_raw": int(frame.get("amdar_grouped_raw_count", 0)),
                "turb_voxels": int(len(frame["turb_grouped"])),
                "turb_voxels_raw": int(frame.get("turb_grouped_raw_count", 0)),
                "wind_keep_ratio": float(len(frame["wind_grouped"]) / max(1, int(frame.get("wind_grouped_raw_count", 0)))),
                "motion_keep_ratio": float(len(frame["motion_grouped"]) / max(1, int(frame.get("motion_grouped_raw_count", 0)))),
                "amdar_keep_ratio": float(len(frame["amdar_grouped"]) / max(1, int(frame.get("amdar_grouped_raw_count", 0)))),
                "candidate_flight_count": int(frame["flight_pack"].get("candidate_flight_count", 0)),
                "tier1_candidate_count": int(frame["flight_pack"].get("tier1_candidate_count", 0)),
                "tier2_candidate_count": int(frame["flight_pack"].get("tier2_candidate_count", 0)),
                "valid_flight_agents": int(frame["flight_pack"].get("valid_flight_agents", 0)),
                "flight_comm_allowed_agents": int(np.sum(np.asarray(frame["flight_pack"].get("flight_comm_allowed", []), dtype=np.float32) > 0.5)),
                "flight_ff_allowed_edges": int(np.sum(np.asarray(frame["flight_pack"].get("ff_comm_allowed", []), dtype=np.float32) > 0.5)),
                "flight_ff_motion_edges": int(np.sum(np.asarray(frame["flight_pack"].get("ff_motion_allowed", []), dtype=np.float32) > 0.5)),
                "flight_ff_wind_edges": int(np.sum(np.asarray(frame["flight_pack"].get("ff_wind_allowed", []), dtype=np.float32) > 0.0)),
                "recon_triggered": int(bool(trigger)),
                "recon_trigger_reason": trigger_reason,
                "recon_seed_strength": float(frame.get("recon_seed_strength", 0.0)),
                "wind_seed_voxels": int(len(frame.get("flight_seed_df", []))) if frame.get("flight_seed_df") is not None else 0,
                "support_voxels": int(frame.get("support_voxel_count", 0)),
                "support_fill_voxels": int(frame.get("support_fill_count", 0)),
                "support_fill_kept_voxels": int(frame.get("support_fill_kept_count", 0)),
                "temporal_fill_voxels": int(frame.get("temporal_fill_count", 0)),
                "temporal_fill_kept_voxels": int(frame.get("temporal_fill_kept_count", 0)),
                "relax_steps_used": int(frame.get("relax_steps_used", 0)),
                "outlier_drop_voxels": int(frame.get("outlier_drop_count", 0)),
                "recon_pruned_voxels": int(frame.get("low_quality_pruned_count", 0)),
                "direct_agreement_mean": float(frame.get("direct_agreement_mean", 0.0)),
                "comm_joint_voxels": int(len(frame["where2comm_targets"]["joint_idx"])),
                "comm_wind_voxels": int(len(frame["where2comm_targets"]["wind_idx"])),
                "comm_motion_voxels": int(len(frame["where2comm_targets"]["motion_idx"])),
                "comm_uncertainty_voxels": int(len(frame["where2comm_targets"]["uncertainty_idx"])),
                "pinn_div_mean": float(np.mean(frame["pinn_divergence_3d"])) if np.size(frame["pinn_divergence_3d"]) else 0.0,
                "pinn_div_p90": float(np.quantile(frame["pinn_divergence_3d"], 0.90)) if np.size(frame["pinn_divergence_3d"]) else 0.0,
                "pinn_smooth_mean": float(np.mean(frame["pinn_smoothness_3d"])) if np.size(frame["pinn_smoothness_3d"]) else 0.0,
                "physics_weight_mean": float(np.mean(frame["physics_weight_3d"])) if np.size(frame["physics_weight_3d"]) else 0.0,
                "forecast_conf_mean": float(np.mean(frame["forecast_conf_3d"])) if np.size(frame["forecast_conf_3d"]) else 0.0,
                "forecast_coverage_ratio": float(
                    np.sum(np.asarray(frame["forecast_mask_3d"]) > 0) /
                    max(
                        1,
                        int(frame.get("recon_domain_count", 0)),
                        int(np.sum(np.asarray(frame["forecast_mask_3d"]) > 0)),
                    )
                ) if np.size(frame["forecast_mask_3d"]) else 0.0,
                "hazard_alert_voxels": int(np.sum(np.asarray(frame["hazard_alert_mask_3d"]) > 0)),
                "hazard_shear_mean": float(np.mean(frame["hazard_shear_3d"])) if np.size(frame["hazard_shear_3d"]) else 0.0,
                "hazard_turbulence_mean": float(np.mean(frame["hazard_turbulence_3d"])) if np.size(frame["hazard_turbulence_3d"]) else 0.0,
                "recon_support_domain_voxels": int(frame.get("recon_support_domain_count", 0)),
                "recon_domain_voxels": int(frame.get("recon_domain_count", 0)),
                "recon_filled_voxels": int(frame["recon_mask"].sum()) if trigger else 0,
                "recon_coverage_ratio": recon_coverage_ratio,
                "recon_conf_mean": recon_conf_mean,
                "recon_conf_p25": _masked_quantile(frame["recon_conf"], frame["recon_mask"], 0.25) if trigger else 0.0,
                "recon_conf_p50": _masked_quantile(frame["recon_conf"], frame["recon_mask"], 0.50) if trigger else 0.0,
                "recon_conf_p75": _masked_quantile(frame["recon_conf"], frame["recon_mask"], 0.75) if trigger else 0.0,
                "recon_conf_p90": _masked_quantile(frame["recon_conf"], frame["recon_mask"], 0.90) if trigger else 0.0,
                "ground_lat": float(stage3_item.get("ground_lat", 0.0)),
                "ground_lon": float(stage3_item.get("ground_lon", 0.0)),
                "ground_alt": float(stage3_item.get("ground_alt", 0.0)),
            }
        )

        prev_frame_meta = curr_frame_meta
        prev_recon_state = {
            "source_index": int(frame.get("source_index", -1)),
            "recon_u": np.asarray(frame["recon_u"], dtype=np.float32).copy(),
            "recon_v": np.asarray(frame["recon_v"], dtype=np.float32).copy(),
            "recon_conf": np.asarray(frame["recon_conf"], dtype=np.float32).copy(),
            "recon_mask": np.asarray(frame["recon_mask"], dtype=np.float32).copy(),
        }
        print(
            f"[Stage-4][frame] {frame['time_str']} triggered={int(bool(trigger))} "
            f"seed={frame.get('recon_seed_strength', 0.0):.2f} "
            f"filled={int(np.sum(frame['recon_mask'] > 0)) if trigger else 0} "
            f"support_fill={int(frame.get('support_fill_count', 0)) if trigger else 0} "
            f"temporal_fill={int(frame.get('temporal_fill_count', 0)) if trigger else 0} "
            f"relax_steps={int(frame.get('relax_steps_used', 0)) if trigger else 0} "
            f"comm_joint={len(frame['where2comm_targets']['joint_idx']) if trigger else 0} "
            f"hazard_alert={int(np.sum(frame['hazard_alert_mask_3d'] > 0)) if trigger else 0} "
            f"coverage={recon_coverage_ratio:.6f} conf_mean={recon_conf_mean:.6f}"
        )
        if i % progress_every == 0 or i == total_frames:
            _print_stage_progress("Stage-4", i, total_frames, t_start, frame_item=frame)

    with open(os.path.join(stage4_dir, "stage4_summary.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    if summary:
        recon_means = [float(x.get("recon_conf_mean", 0.0)) for x in summary]
        recon_cov = [float(x.get("recon_coverage_ratio", 0.0)) for x in summary]
        print(f"[Stage-4] 重构质量: recon_conf_mean_avg={float(np.mean(recon_means)):.6f}, recon_coverage_avg={float(np.mean(recon_cov)):.6f}")

    print("[Stage-4] 完成")
    print(f"输出目录: {stage4_dir}")
    print(f"样本数: {len(summary)}")


if __name__ == "__main__":
    main()
