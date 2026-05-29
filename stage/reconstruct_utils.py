"""Reconstruction utilities for the staged pipeline.

This module contains the shared 3-D wind reconstruction baseline so Stage 4 and
runtime scaffolds can import it without depending on `hello.py`.

The implementation is conservative by design:
- fuse multiple voxelized observation sources;
- keep explicit confidence / mask outputs;
- optionally perform a bounded local IDW completion on sparse holes.
"""

from __future__ import annotations

import numpy as np
import polars as pl

import pipeline_config as cfg


def _reconstruct_wind_field(
    z_dim,
    h_dim,
    w_dim,
    wind_grouped,
    loc_motion_grouped,
    amdar_grouped,
    turb_grouped,
    enable_idw=None,
    idw_max_fill=None,
):
    """Construct a conservative 3-D wind reconstruction.

    Parameters
    ----------
    z_dim, h_dim, w_dim:
        Target voxel grid size.
    wind_grouped, loc_motion_grouped, amdar_grouped, turb_grouped:
        Per-voxel grouped observations from Stage 2.

    Returns
    -------
    recon_u, recon_v, recon_conf, recon_mask:
        3-D arrays with the reconstructed wind components, confidence, and
        binary mask of reconstructed voxels.
    """
    recon_u = np.full((z_dim, h_dim, w_dim), np.nan, dtype=np.float32)
    recon_v = np.full((z_dim, h_dim, w_dim), np.nan, dtype=np.float32)
    recon_conf = np.zeros((z_dim, h_dim, w_dim), dtype=np.float32)
    recon_mask = np.zeros((z_dim, h_dim, w_dim), dtype=np.float32)

    # [改动说明] 这里优先使用 Stage-4 预先计算的 qc_weight，
    # 保证前面的质量清洗真正进入重构权重。
    def _safe_cols(df, u_name, v_name, weight_name=None):
        if len(df) == 0 or u_name not in df.columns or v_name not in df.columns:
            return None
        z = df["z"].to_numpy().astype(np.int32, copy=False)
        y = df["y"].to_numpy().astype(np.int32, copy=False)
        x = df["x"].to_numpy().astype(np.int32, copy=False)
        u = df[u_name].to_numpy().astype(np.float32, copy=False)
        v = df[v_name].to_numpy().astype(np.float32, copy=False)
        # Stage-4 会先对不同来源观测做一次质量清洗，并生成 `qc_weight`。
        # 如果这里不优先消费 `qc_weight`，那么前面的清洗结果只会停留在表里，
        # 实际重构权重却仍然沿用旧字段，导致“看起来清洗了，实际上没生效”。
        if "qc_weight" in df.columns:
            w = df["qc_weight"].to_numpy().astype(np.float32, copy=False)
        elif weight_name is not None and weight_name in df.columns:
            w = df[weight_name].to_numpy().astype(np.float32, copy=False)
        elif "obs_conf" in df.columns:
            w = df["obs_conf"].to_numpy().astype(np.float32, copy=False)
        else:
            w = np.ones(len(df), dtype=np.float32)
        return z, y, x, u, v, np.clip(w, 0.0, 1.0)

    # 1) 汇总各来源观测。基础权重稍微偏向直接风观测和 AMDAR。
    source_specs = []
    if len(wind_grouped) > 0:
        source_specs.append((wind_grouped, "u", "v", "obs_conf", 1.20))
    if len(loc_motion_grouped) > 0:
        source_specs.append((loc_motion_grouped, "u_motion", "v_motion", "motion_count", 0.85))
    if len(amdar_grouped) > 0:
        source_specs.append((amdar_grouped, "u", "v", None, 1.00))
    if len(turb_grouped) > 0:
        source_specs.append((turb_grouped, "u", "v", None, 0.95))

    observed_coords, observed_vals_u, observed_vals_v, observed_weight = [], [], [], []
    for df, u_name, v_name, weight_name, base_w in source_specs:
        cols = _safe_cols(df, u_name, v_name, weight_name)
        if cols is None:
            continue
        z, y, x, u, v, w = cols
        speed = np.sqrt(u * u + v * v)
        keep = np.isfinite(u) & np.isfinite(v) & np.isfinite(speed) & (speed <= cfg.MAX_WIND_SPEED_MS)
        if not np.any(keep):
            continue
        for zi, yi, xi, uu, vv, ww in zip(z[keep], y[keep], x[keep], u[keep], v[keep], w[keep]):
            if zi < 0 or yi < 0 or xi < 0 or zi >= z_dim or yi >= h_dim or xi >= w_dim:
                continue
            observed_coords.append((int(zi), int(yi), int(xi)))
            observed_vals_u.append(float(uu))
            observed_vals_v.append(float(vv))
            observed_weight.append(float(base_w * max(1e-4, float(ww))))

    if not observed_coords:
        return recon_u, recon_v, recon_conf, recon_mask

    observed_coords = np.asarray(observed_coords, dtype=np.int32)
    observed_vals_u = np.asarray(observed_vals_u, dtype=np.float32)
    observed_vals_v = np.asarray(observed_vals_v, dtype=np.float32)
    observed_weight = np.asarray(observed_weight, dtype=np.float32)

    # 2) 同体素加权融合。
    linear = observed_coords[:, 0].astype(np.int64) * (h_dim * w_dim) + observed_coords[:, 1].astype(np.int64) * w_dim + observed_coords[:, 2].astype(np.int64)
    uniq_lin, inv = np.unique(linear, return_inverse=True)

    sum_w = np.zeros(len(uniq_lin), dtype=np.float32)
    sum_u = np.zeros(len(uniq_lin), dtype=np.float32)
    sum_v = np.zeros(len(uniq_lin), dtype=np.float32)
    np.add.at(sum_w, inv, observed_weight)
    np.add.at(sum_u, inv, observed_vals_u * observed_weight)
    np.add.at(sum_v, inv, observed_vals_v * observed_weight)

    z = (uniq_lin // (h_dim * w_dim)).astype(np.int32)
    rem = uniq_lin % (h_dim * w_dim)
    y = (rem // w_dim).astype(np.int32)
    x = (rem % w_dim).astype(np.int32)

    valid = sum_w > 1e-8
    if np.any(valid):
        u0 = sum_u[valid] / sum_w[valid]
        v0 = sum_v[valid] / sum_w[valid]
        c0 = np.clip(1.0 - np.exp(-sum_w[valid]), 0.0, 1.0)
        recon_u[z[valid], y[valid], x[valid]] = u0.astype(np.float32, copy=False)
        recon_v[z[valid], y[valid], x[valid]] = v0.astype(np.float32, copy=False)
        recon_conf[z[valid], y[valid], x[valid]] = c0.astype(np.float32, copy=False)
        recon_mask[z[valid], y[valid], x[valid]] = 1.0

    if enable_idw is None:
        enable_idw = cfg.RECON_ENABLE_IDW
    if idw_max_fill is None:
        idw_max_fill = int(cfg.RECON_IDW_MAX_FILL)

    if not enable_idw:
        return recon_u, recon_v, recon_conf, recon_mask

    # 3) 有界局部补全：仅补少量最近邻缺失体素，防止把整幅图“糊满”。
    missing = np.argwhere(recon_mask <= 0)
    if missing.size == 0:
        return recon_u, recon_v, recon_conf, recon_mask

    known_idx = np.argwhere(recon_mask > 0)
    if known_idx.size == 0:
        return recon_u, recon_v, recon_conf, recon_mask

    known_u = recon_u[recon_mask > 0]
    known_v = recon_v[recon_mask > 0]
    known_conf = recon_conf[recon_mask > 0]
    known_xyz = known_idx.astype(np.float32)

    max_fill = min(int(idw_max_fill), len(missing))
    for zi, yi, xi in missing[:max_fill]:
        d = known_xyz - np.array([zi, yi, xi], dtype=np.float32)
        dist2 = np.sum(d * d, axis=1)
        local = np.argsort(dist2)[:12]
        dist2 = dist2[local]
        w = 1.0 / (dist2 + 1.0)
        w *= np.clip(known_conf[local], 0.05, 1.0)
        ws = float(np.sum(w))
        if ws <= 1e-8:
            continue
        recon_u[zi, yi, xi] = float(np.sum(known_u[local] * w) / ws)
        recon_v[zi, yi, xi] = float(np.sum(known_v[local] * w) / ws)
        recon_conf[zi, yi, xi] = float(np.clip(ws / len(local), 0.0, 1.0) * 0.4)
        recon_mask[zi, yi, xi] = 1.0

    return recon_u, recon_v, recon_conf, recon_mask


__all__ = ["_reconstruct_wind_field"]
