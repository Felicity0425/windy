"""Sparse supervised evaluation for Stage-4 reconstruction.

This script evaluates reconstruction quality only at Stage-2 wind-observation
anchor voxels. It is useful for checking anchor fidelity and outliers, but it
must not be interpreted as full-field truth evaluation.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np


def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _corr(a: np.ndarray, b: np.ndarray) -> float:
    if a.size < 2 or b.size < 2:
        return 0.0
    if float(np.std(a)) < 1e-12 or float(np.std(b)) < 1e-12:
        return 0.0
    return float(np.corrcoef(a, b)[0, 1])


def _describe(values: np.ndarray) -> dict[str, float]:
    if values.size == 0:
        return {"count": 0, "min": 0.0, "p25": 0.0, "p50": 0.0, "p75": 0.0, "p90": 0.0, "max": 0.0, "mean": 0.0}
    return {
        "count": int(values.size),
        "min": float(np.min(values)),
        "p25": float(np.quantile(values, 0.25)),
        "p50": float(np.quantile(values, 0.50)),
        "p75": float(np.quantile(values, 0.75)),
        "p90": float(np.quantile(values, 0.90)),
        "max": float(np.max(values)),
        "mean": float(np.mean(values)),
    }


def _reliability_bins(conf: np.ndarray, err: np.ndarray, n_bins: int = 10) -> list[dict[str, float]]:
    bins = np.linspace(0.0, 1.0, n_bins + 1)
    stats: list[dict[str, float]] = []
    if conf.size == 0:
        return stats
    err_norm = err / max(1e-6, float(np.max(err))) if err.size > 0 else err
    pseudo_acc = 1.0 - np.clip(err_norm, 0.0, 1.0)
    for i in range(n_bins):
        lo = bins[i]
        hi = bins[i + 1]
        sel = (conf >= lo) & (conf < hi if i < n_bins - 1 else conf <= hi)
        if not np.any(sel):
            continue
        stats.append(
            {
                "bin_lo": float(lo),
                "bin_hi": float(hi),
                "count": int(np.sum(sel)),
                "mean_conf": float(np.mean(conf[sel])),
                "pseudo_accuracy": float(np.mean(pseudo_acc[sel])),
                "mean_vector_err": float(np.mean(err[sel])),
            }
        )
    return stats


def _robust_rmse(values: np.ndarray, keep_q: float = 0.995) -> float:
    if values.size == 0:
        return 0.0
    thr = float(np.quantile(values, keep_q))
    keep = values <= thr
    if not np.any(keep):
        return 0.0
    return float(np.sqrt(np.mean(values[keep] ** 2)))


def _collect_fullfield_conf(stage4_summary, stage4_dir: Path) -> np.ndarray:
    all_conf: list[np.ndarray] = []
    for item in stage4_summary:
        fp = stage4_dir / item["filename"]
        if not fp.exists():
            continue
        with np.load(fp, allow_pickle=True) as npz:
            if "recon_conf_val" in npz.files and "recon_mask_val" in npz.files:
                vals = np.asarray(npz["recon_conf_val"], dtype=np.float32)
                mask_val = np.asarray(npz["recon_mask_val"], dtype=np.float32) > 0
                vals = vals[mask_val]
                if vals.size > 0:
                    all_conf.append(vals.astype(np.float64, copy=False))
                continue
            if "recon_confidence_3d" not in npz.files or "recon_mask_3d" not in npz.files:
                continue
            conf = np.asarray(npz["recon_confidence_3d"], dtype=np.float32)
            mask = np.asarray(npz["recon_mask_3d"], dtype=np.float32) > 0
            vals = conf[mask]
            if vals.size > 0:
                all_conf.append(vals.astype(np.float64, copy=False))
    if not all_conf:
        return np.asarray([], dtype=np.float64)
    return np.concatenate(all_conf)


def _build_sparse_lookup(npz, idx_key: str, val_key: str) -> dict[int, float] | None:
    if idx_key not in npz.files or val_key not in npz.files:
        return None
    idx = np.asarray(npz[idx_key], dtype=np.int64)
    val = np.asarray(npz[val_key], dtype=np.float32)
    if idx.size == 0 or val.size != idx.size:
        return {}
    return {int(i): float(v) for i, v in zip(idx.tolist(), val.tolist())}


def _eval_sparse_lookup(lookup: dict[int, float] | None, linear_idx: int, default: float = 0.0) -> float:
    if lookup is None:
        return default
    return float(lookup.get(int(linear_idx), default))


def _iter_eval_rows(stage2_summary, stage4_summary, stage4_dir: Path):
    stage4_map = {x["time_str"]: x for x in stage4_summary}
    for s2 in stage2_summary:
        ts = s2["time_str"]
        s4 = stage4_map.get(ts)
        if s4 is None:
            continue

        vox = np.load(s2["vox_path"], allow_pickle=True)
        stage4_npz = np.load(stage4_dir / s4["filename"], allow_pickle=True)
        wind_records = vox["wind_records"].tolist() if "wind_records" in vox.files else []
        if not wind_records:
            continue

        grid_shape = tuple(np.asarray(stage4_npz["grid_shape"], dtype=np.int32).tolist()) if "grid_shape" in stage4_npz.files else None
        sparse_recon_u = _build_sparse_lookup(stage4_npz, "recon_idx", "recon_u_val")
        sparse_recon_v = _build_sparse_lookup(stage4_npz, "recon_idx", "recon_v_val")
        sparse_recon_conf = _build_sparse_lookup(stage4_npz, "recon_idx", "recon_conf_val")
        sparse_recon_mask = _build_sparse_lookup(stage4_npz, "recon_idx", "recon_mask_val")
        use_sparse = (
            grid_shape is not None
            and len(grid_shape) == 3
            and sparse_recon_u is not None
            and sparse_recon_v is not None
            and sparse_recon_conf is not None
            and sparse_recon_mask is not None
        )
        if use_sparse:
            z_dim, h_dim, w_dim = (int(grid_shape[0]), int(grid_shape[1]), int(grid_shape[2]))
        else:
            recon_u = np.asarray(stage4_npz["recon_u_3d"], dtype=np.float32)
            recon_v = np.asarray(stage4_npz["recon_v_3d"], dtype=np.float32)
            recon_mask = np.asarray(stage4_npz["recon_mask_3d"], dtype=np.float32)
            recon_conf = np.asarray(stage4_npz["recon_confidence_3d"], dtype=np.float32)
            z_dim, h_dim, w_dim = recon_u.shape

        for rec in wind_records:
            try:
                z = int(rec["z"])
                y = int(rec["y"])
                x = int(rec["x"])
                u_true = float(rec["u"])
                v_true = float(rec["v"])
            except Exception:
                continue
            if not (0 <= z < z_dim and 0 <= y < h_dim and 0 <= x < w_dim):
                continue

            if use_sparse:
                linear_idx = int(z) * (h_dim * w_dim) + int(y) * w_dim + int(x)
                u_pred = _eval_sparse_lookup(sparse_recon_u, linear_idx, 0.0)
                v_pred = _eval_sparse_lookup(sparse_recon_v, linear_idx, 0.0)
                mask_val = _eval_sparse_lookup(sparse_recon_mask, linear_idx, 0.0)
                conf_val = _eval_sparse_lookup(sparse_recon_conf, linear_idx, 0.0)
            else:
                u_pred = float(recon_u[z, y, x])
                v_pred = float(recon_v[z, y, x])
                mask_val = float(recon_mask[z, y, x])
                conf_val = float(recon_conf[z, y, x])

            speed_true = float(np.sqrt(u_true * u_true + v_true * v_true))
            speed_pred = float(np.sqrt(u_pred * u_pred + v_pred * v_pred))
            vector_err = float(np.sqrt((u_pred - u_true) ** 2 + (v_pred - v_true) ** 2))
            speed_err = float(abs(speed_pred - speed_true))
            yield {
                "time_str": ts,
                "u_true": u_true,
                "v_true": v_true,
                "u_pred": u_pred,
                "v_pred": v_pred,
                "speed_true": speed_true,
                "speed_pred": speed_pred,
                "vector_err": vector_err,
                "speed_err": speed_err,
                "mask": mask_val,
                "conf": conf_val,
            }


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate Stage-4 reconstruction on sparse supervised wind voxels.")
    parser.add_argument("--stage2-summary", required=True, help="Path to stage2_summary.json")
    parser.add_argument("--stage4-summary", required=True, help="Path to stage4_summary.json")
    parser.add_argument("--stage4-dir", required=True, help="Directory containing frame_*.npz")
    parser.add_argument("--out-json", default="", help="Optional JSON output path")
    args = parser.parse_args()

    stage2_summary = _load_json(Path(args.stage2_summary))
    stage4_summary = _load_json(Path(args.stage4_summary))
    stage4_dir = Path(args.stage4_dir)
    rows = list(_iter_eval_rows(stage2_summary, stage4_summary, Path(args.stage4_dir)))
    if not rows:
        raise SystemExit("No supervised wind voxels found for sparse metrics.")

    u_true = np.asarray([x["u_true"] for x in rows], dtype=np.float64)
    v_true = np.asarray([x["v_true"] for x in rows], dtype=np.float64)
    u_pred = np.asarray([x["u_pred"] for x in rows], dtype=np.float64)
    v_pred = np.asarray([x["v_pred"] for x in rows], dtype=np.float64)
    speed_true = np.asarray([x["speed_true"] for x in rows], dtype=np.float64)
    speed_pred = np.asarray([x["speed_pred"] for x in rows], dtype=np.float64)
    vector_err = np.asarray([x["vector_err"] for x in rows], dtype=np.float64)
    speed_err = np.asarray([x["speed_err"] for x in rows], dtype=np.float64)
    mask = np.asarray([x["mask"] for x in rows], dtype=np.float64)
    conf = np.asarray([x["conf"] for x in rows], dtype=np.float64)

    rmse_u = float(np.sqrt(np.mean((u_pred - u_true) ** 2)))
    rmse_v = float(np.sqrt(np.mean((v_pred - v_true) ** 2)))
    rmse_speed = float(np.sqrt(np.mean((speed_pred - speed_true) ** 2)))
    vector_rmse = float(np.sqrt(np.mean(vector_err ** 2)))
    mae_u = float(np.mean(np.abs(u_pred - u_true)))
    mae_v = float(np.mean(np.abs(v_pred - v_true)))
    mae_speed = float(np.mean(speed_err))
    corr_u = _corr(u_true, u_pred)
    corr_v = _corr(v_true, v_pred)
    corr_speed = _corr(speed_true, speed_pred)
    coverage = float(np.mean(mask > 0))
    recovery_rate = coverage

    baseline_vector_rmse = float(np.sqrt(np.mean(u_true ** 2 + v_true ** 2)))
    skill_score_vs_zero = 1.0 - vector_rmse / max(1e-6, baseline_vector_rmse)
    confidence_error_corr = _corr(conf, -vector_err)
    outlier_threshold = max(10.0, float(np.quantile(vector_err, 0.995)))
    outlier_mask = vector_err >= outlier_threshold
    confidence_spread = float(np.quantile(conf, 0.90) - np.quantile(conf, 0.10)) if conf.size > 0 else 0.0
    fullfield_conf = _collect_fullfield_conf(stage4_summary, stage4_dir)
    fullfield_conf_spread = float(np.quantile(fullfield_conf, 0.90) - np.quantile(fullfield_conf, 0.10)) if fullfield_conf.size > 0 else 0.0

    report = {
        "evaluation_scope": "anchor_fidelity",
        "sample_count": len(rows),
        "metrics": {
            "rmse_u": rmse_u,
            "rmse_v": rmse_v,
            "rmse_speed": rmse_speed,
            "vector_rmse": vector_rmse,
            "mae_u": mae_u,
            "mae_v": mae_v,
            "mae_speed": mae_speed,
            "corr_u": corr_u,
            "corr_v": corr_v,
            "corr_speed": corr_speed,
            "coverage": coverage,
            "recovery_rate": recovery_rate,
            "skill_score_vs_zero": skill_score_vs_zero,
            "confidence_error_corr": confidence_error_corr,
            "robust_vector_rmse_p995": _robust_rmse(vector_err, keep_q=0.995),
            "robust_speed_rmse_p995": _robust_rmse(speed_err, keep_q=0.995),
            "confidence_spread_p10_p90": confidence_spread,
            "anchor_confidence_spread_p10_p90": confidence_spread,
            "fullfield_confidence_spread_p10_p90": fullfield_conf_spread,
            "outlier_threshold": outlier_threshold,
            "outlier_count": int(np.sum(outlier_mask)),
            "outlier_rate": float(np.mean(outlier_mask)),
        },
        "error_distribution": {
            "vector_err": _describe(vector_err),
            "speed_err": _describe(speed_err),
            "confidence": _describe(conf),
            "fullfield_confidence": _describe(fullfield_conf),
        },
        "reliability_bins": _reliability_bins(conf, vector_err),
        "notes": [
            "当前评估范围是 Stage-2 稀疏风观测锚点，反映的是 anchor fidelity，不代表 full-field 真值误差。",
            "`confidence_spread_p10_p90` 是锚点处置信度 spread；`fullfield_confidence_spread_p10_p90` 才更接近整体重构场的置信度层次。",
            "robust_* 指标排除了最极端 0.5% 样本，更适合观察主体质量；原始 RMSE 仍保留用来暴露极端 outlier。",
            "如果 robust RMSE 非常小，通常表示观测锚点被成功保留，而不是说明扩展区同样完美。",
            "SSIM/PSNR 需要完整密集真值场或统一二维投影真值，目前不建议作为主指标。",
            "Calibration/ Reliability 当前使用的是基于 recon_conf 与误差关系的代理分析，不是严格概率校准。",
            "Skill score 当前采用相对零风场基线的工程型定义，用于粗略判断是否优于朴素基线。",
        ],
    }

    print("=== Stage4 Sparse Supervised Metrics ===")
    print("evaluation_scope =", report["evaluation_scope"])
    print("sample_count =", report["sample_count"])
    for k, v in report["metrics"].items():
        print(f"{k} = {v}")
    print()
    print("[reliability_bins]")
    for item in report["reliability_bins"]:
        print(item)

    if args.out_json:
        Path(args.out_json).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
