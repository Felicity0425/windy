"""Detailed Stage-4 sparse-anchor outlier report.

This report complements `report_stage4_sparse_metrics.py` by locating the worst
anchor-point outliers and attaching interpretable diagnostics:
- source overlap / disagreement
- direct source agreement
- direct source count
- local gradient anomaly
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np

ROOT_DIR = Path(__file__).resolve().parent.parent
STAGE_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
if str(STAGE_DIR) not in sys.path:
    sys.path.insert(0, str(STAGE_DIR))

from schema_contract import STAGE2_AMDAR_RECORDS, STAGE2_TURB_RECORDS, STAGE2_WIND_RECORDS


def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _records_to_list(records: Any) -> list[dict[str, Any]]:
    if records is None:
        return []
    if isinstance(records, list):
        return records
    if isinstance(records, np.ndarray):
        if records.size == 0:
            return []
        return records.tolist()
    if hasattr(records, "tolist"):
        payload = records.tolist()
        return payload if payload else []
    return list(records)


def _coord_source_map(records: list[dict[str, Any]]) -> dict[tuple[int, int, int], list[tuple[float, float]]]:
    out: dict[tuple[int, int, int], list[tuple[float, float]]] = {}
    for rec in records:
        try:
            key = (int(rec["z"]), int(rec["y"]), int(rec["x"]))
            uv = (float(rec["u"]), float(rec["v"]))
        except Exception:
            continue
        out.setdefault(key, []).append(uv)
    return out


def _mean_uv(values: list[tuple[float, float]]) -> tuple[float, float]:
    arr = np.asarray(values, dtype=np.float32)
    return float(np.mean(arr[:, 0])), float(np.mean(arr[:, 1]))


def _pairwise_disagreement(source_uvs: list[tuple[float, float]]) -> float:
    if len(source_uvs) < 2:
        return 0.0
    arr = np.asarray(source_uvs, dtype=np.float32)
    max_diff = 0.0
    for i in range(arr.shape[0]):
        for j in range(i + 1, arr.shape[0]):
            diff = float(np.sqrt(np.sum((arr[i] - arr[j]) ** 2)))
            max_diff = max(max_diff, diff)
    return max_diff


def _compute_shear_3d(recon_u: np.ndarray, recon_v: np.ndarray) -> np.ndarray:
    u = np.asarray(recon_u, dtype=np.float32)
    v = np.asarray(recon_v, dtype=np.float32)
    du_dx = np.zeros_like(u)
    du_dy = np.zeros_like(u)
    dv_dx = np.zeros_like(v)
    dv_dy = np.zeros_like(v)
    du_dx[:, :, 1:-1] = 0.5 * (u[:, :, 2:] - u[:, :, :-2])
    du_dy[:, 1:-1, :] = 0.5 * (u[:, 2:, :] - u[:, :-2, :])
    dv_dx[:, :, 1:-1] = 0.5 * (v[:, :, 2:] - v[:, :, :-2])
    dv_dy[:, 1:-1, :] = 0.5 * (v[:, 2:, :] - v[:, :-2, :])
    return np.sqrt(du_dx ** 2 + du_dy ** 2 + dv_dx ** 2 + dv_dy ** 2).astype(np.float32, copy=False)


def _dense_or_sparse_scalar(npz, dense_key: str, idx_key: str, val_key: str, shape: tuple[int, int, int]) -> np.ndarray:
    if dense_key in npz.files:
        return np.asarray(npz[dense_key], dtype=np.float32)
    out = np.zeros(shape, dtype=np.float32)
    if idx_key in npz.files and val_key in npz.files:
        idx = np.asarray(npz[idx_key], dtype=np.int64)
        val = np.asarray(npz[val_key], dtype=np.float32)
        if idx.size > 0 and val.size == idx.size:
            out.reshape(-1)[idx] = val
    return out


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


def _sparse_eval_at_coord(npz, idx_key: str, val_key: str, z: int, y: int, x: int, h_dim: int, w_dim: int, default: float = 0.0) -> float:
    if idx_key not in npz.files or val_key not in npz.files:
        return default
    idx = np.asarray(npz[idx_key], dtype=np.int64)
    val = np.asarray(npz[val_key], dtype=np.float32)
    if idx.size == 0 or val.size != idx.size:
        return default
    target = int(z) * (h_dim * w_dim) + int(y) * w_dim + int(x)
    pos = np.where(idx == target)[0]
    if pos.size == 0:
        return default
    return float(val[int(pos[0])])


def _classify_root_cause(mask: float, conf: float, overlap_count: int, disagreement: float, direct_agreement: float, local_shear: float, shear_thr: float) -> str:
    if mask <= 0:
        return "missing_anchor"
    if overlap_count >= 2 and disagreement >= 8.0:
        return "multi_source_conflict"
    if local_shear >= shear_thr:
        return "local_gradient_spike"
    if direct_agreement > 0 and direct_agreement < 0.75:
        return "low_direct_agreement"
    if conf >= 0.75:
        return "overconfident_outlier"
    return "other"


def main() -> None:
    parser = argparse.ArgumentParser(description="Locate sparse-anchor outliers in Stage-4 reconstruction.")
    parser.add_argument("--stage2-summary", required=True)
    parser.add_argument("--stage4-summary", required=True)
    parser.add_argument("--stage4-dir", required=True)
    parser.add_argument("--top-k", type=int, default=20)
    parser.add_argument("--out-json", default="")
    args = parser.parse_args()

    stage2_summary = _load_json(Path(args.stage2_summary))
    stage4_summary = _load_json(Path(args.stage4_summary))
    stage4_map = {x["time_str"]: x for x in stage4_summary}

    rows: list[dict[str, Any]] = []
    for s2 in stage2_summary:
        ts = s2["time_str"]
        s4 = stage4_map.get(ts)
        if s4 is None:
            continue
        vox = np.load(s2["vox_path"], allow_pickle=True)
        stage4_npz = np.load(Path(args.stage4_dir) / s4["filename"], allow_pickle=True)

        wind_records = _records_to_list(vox[STAGE2_WIND_RECORDS]) if STAGE2_WIND_RECORDS in vox.files else []
        if not wind_records:
            continue
        wind_map = _coord_source_map(_records_to_list(vox[STAGE2_WIND_RECORDS]) if STAGE2_WIND_RECORDS in vox.files else [])
        amdar_map = _coord_source_map(_records_to_list(vox[STAGE2_AMDAR_RECORDS]) if STAGE2_AMDAR_RECORDS in vox.files else [])
        turb_map = _coord_source_map(_records_to_list(vox[STAGE2_TURB_RECORDS]) if STAGE2_TURB_RECORDS in vox.files else [])

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
            shape = (z_dim, h_dim, w_dim)
            recon_u = np.asarray(stage4_npz["recon_u_3d"], dtype=np.float32) if "recon_u_3d" in stage4_npz.files else np.zeros(shape, dtype=np.float32)
            recon_v = np.asarray(stage4_npz["recon_v_3d"], dtype=np.float32) if "recon_v_3d" in stage4_npz.files else np.zeros(shape, dtype=np.float32)
            recon_mask = np.asarray(stage4_npz["recon_mask_3d"], dtype=np.float32) if "recon_mask_3d" in stage4_npz.files else np.zeros(shape, dtype=np.float32)
            recon_conf = np.asarray(stage4_npz["recon_confidence_3d"], dtype=np.float32) if "recon_confidence_3d" in stage4_npz.files else np.zeros(shape, dtype=np.float32)
        else:
            recon_u = np.asarray(stage4_npz["recon_u_3d"], dtype=np.float32)
            recon_v = np.asarray(stage4_npz["recon_v_3d"], dtype=np.float32)
            recon_mask = np.asarray(stage4_npz["recon_mask_3d"], dtype=np.float32)
            recon_conf = np.asarray(stage4_npz["recon_confidence_3d"], dtype=np.float32)
            shape = recon_conf.shape
            z_dim, h_dim, w_dim = shape
        direct_agreement = _dense_or_sparse_scalar(stage4_npz, "direct_agreement_3d", "direct_agreement_idx", "direct_agreement_val", shape)
        direct_source_count = _dense_or_sparse_scalar(stage4_npz, "direct_source_count_3d", "direct_source_count_idx", "direct_source_count_val", shape)
        shear_3d = _compute_shear_3d(recon_u, recon_v)
        finite_shear = shear_3d[np.isfinite(shear_3d)]
        shear_thr = float(np.quantile(finite_shear, 0.995)) if finite_shear.size > 0 else 0.0

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
            key = (z, y, x)
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
            vector_err = float(np.sqrt((u_pred - u_true) ** 2 + (v_pred - v_true) ** 2))
            source_names: list[str] = []
            source_uvs: list[tuple[float, float]] = []
            if key in wind_map:
                source_names.append("wind")
                source_uvs.append(_mean_uv(wind_map[key]))
            if key in amdar_map:
                source_names.append("amdar")
                source_uvs.append(_mean_uv(amdar_map[key]))
            if key in turb_map:
                source_names.append("turb")
                source_uvs.append(_mean_uv(turb_map[key]))
            disagreement = _pairwise_disagreement(source_uvs)
            overlap_count = len(source_names)
            d_agree = float(direct_agreement[z, y, x]) if direct_agreement.size > 0 else 0.0
            d_count = float(direct_source_count[z, y, x]) if direct_source_count.size > 0 else 0.0
            local_shear = float(shear_3d[z, y, x]) if shear_3d.size > 0 else 0.0
            rows.append(
                {
                    "time_str": ts,
                    "z": z,
                    "y": y,
                    "x": x,
                    "u_true": u_true,
                    "v_true": v_true,
                    "u_pred": u_pred,
                    "v_pred": v_pred,
                    "mask": mask_val,
                    "conf": conf_val,
                    "vector_err": vector_err,
                    "source_names": source_names,
                    "source_overlap_count": overlap_count,
                    "source_disagreement_ms": disagreement,
                    "direct_agreement": d_agree,
                    "direct_source_count": d_count,
                    "local_shear": local_shear,
                    "root_cause": _classify_root_cause(mask_val, conf_val, overlap_count, disagreement, d_agree, local_shear, shear_thr),
                }
            )

    if not rows:
        raise SystemExit("No sparse-anchor rows found for outlier report.")

    vector_err = np.asarray([float(x["vector_err"]) for x in rows], dtype=np.float64)
    effective_threshold = max(1.0, float(np.quantile(vector_err, 0.99)))
    rows_sorted = sorted(rows, key=lambda x: float(x["vector_err"]), reverse=True)
    meaningful_rows = [x for x in rows_sorted if float(x["vector_err"]) >= effective_threshold]
    top_rows = meaningful_rows[: max(1, int(args.top_k))]
    cause_counts = Counter(x["root_cause"] for x in top_rows)
    report = {
        "effective_outlier_threshold": effective_threshold,
        "top_k": len(top_rows),
        "top_outliers": top_rows,
        "root_cause_counts": dict(cause_counts),
        "notes": [
            "该报告只定位 Stage-2 风观测锚点上的极端点，不代表 full-field 区域分析。",
            "只有 vector_err 超过 `max(1.0 m/s, p99)` 的样本才会进入 outlier 列表，避免把数值噪声当成异常点。",
            "source_disagreement_ms 越大，越可能是重叠风源冲突。",
            "direct_agreement 越低，越可能是 direct 区 source consistency 不足。",
            "local_shear 越大，越可能是局地梯度异常点。",
        ],
    }

    print("=== Stage4 Outlier Report ===")
    print("effective_outlier_threshold =", report["effective_outlier_threshold"])
    print("top_k =", report["top_k"])
    print("[root_cause_counts]")
    for k, v in report["root_cause_counts"].items():
        print(k, "=", v)
    print()
    print("[top_outliers]")
    for item in top_rows:
        print(item)

    if args.out_json:
        Path(args.out_json).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
