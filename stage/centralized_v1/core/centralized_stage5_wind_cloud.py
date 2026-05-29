"""Centralized v1 Stage5: PINN/Diffusion-style wind-cloud forecast demo."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np

ROOT_DIR = Path(__file__).resolve().parents[3]
STAGE_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
if str(STAGE_DIR) not in sys.path:
    sys.path.insert(0, str(STAGE_DIR))

from stage.centralized_v1.configs.centralized_v1_config import (
    CLOUD_ADVECT_BLEND,
    DIFFUSION_BLEND,
    PINN_DIVERGENCE_WEIGHT,
    PINN_SMOOTHNESS_WEIGHT,
    PINN_TEMPORAL_WEIGHT,
    STAGE5_OUTPUT_DIR,
)
from stage.centralized_v1.configs.centralized_v1_contract import (
    C2_TIME_STR,
    C4_CLOUD_2D,
    C4_C_JOINT_3D,
    C4_RECON_CONF,
    C4_RECON_U,
    C4_RECON_V,
    C5_DOWNLINK_ROI_JSON,
    C5_FUTURE_CLOUD_2D,
    C5_FUTURE_CLOUD_METRICS_JSON,
    C5_FUTURE_WIND_CONF,
    C5_FUTURE_WIND_U,
    C5_FUTURE_WIND_V,
    C5_REFINED_CONF,
    C5_REFINED_U,
    C5_REFINED_V,
)


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text())


def _load_stage4(path: Path) -> dict[str, Any]:
    with np.load(path, allow_pickle=False) as z:
        return {k: z[k] for k in z.files}


def _neighbor_mean(field: np.ndarray) -> np.ndarray:
    pad = np.pad(field, ((1, 1), (1, 1), (1, 1)), mode="edge")
    return (
        pad[1:-1, 1:-1, :-2]
        + pad[1:-1, 1:-1, 2:]
        + pad[1:-1, :-2, 1:-1]
        + pad[1:-1, 2:, 1:-1]
        + pad[:-2, 1:-1, 1:-1]
        + pad[2:, 1:-1, 1:-1]
    ) / 6.0


def _pinn_refine(u: np.ndarray, v: np.ndarray, conf: np.ndarray) -> tuple[np.ndarray, np.ndarray, dict[str, float]]:
    u_mean = _neighbor_mean(u)
    v_mean = _neighbor_mean(v)
    du_dx = np.gradient(u, axis=2)
    dv_dy = np.gradient(v, axis=1)
    div = du_dx + dv_dy
    u2 = u + PINN_SMOOTHNESS_WEIGHT * (u_mean - u) - PINN_DIVERGENCE_WEIGHT * np.gradient(div, axis=2)
    v2 = v + PINN_SMOOTHNESS_WEIGHT * (v_mean - v) - PINN_DIVERGENCE_WEIGHT * np.gradient(div, axis=1)
    return u2.astype(np.float32), v2.astype(np.float32), {
        "pinn_loss_divergence_proxy": float(np.mean(np.abs(div))),
        "pinn_loss_smoothness_proxy": float(np.mean(np.sqrt((u_mean - u) ** 2 + (v_mean - v) ** 2))),
        "pinn_loss_temporal_proxy": float(PINN_TEMPORAL_WEIGHT),
    }


def _diffusion_refine(u: np.ndarray, v: np.ndarray, conf: np.ndarray, c_joint: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    u_mean = _neighbor_mean(u)
    v_mean = _neighbor_mean(v)
    blend = np.clip(DIFFUSION_BLEND * np.clip(conf + c_joint, 0.0, 1.0), 0.0, 0.45)
    u2 = (1.0 - blend) * u + blend * u_mean
    v2 = (1.0 - blend) * v + blend * v_mean
    return u2.astype(np.float32), v2.astype(np.float32)


def _predict_future_cloud(cloud_2d: np.ndarray, u: np.ndarray, v: np.ndarray) -> tuple[np.ndarray, dict[str, float]]:
    near_surface_u = np.mean(u[: min(3, u.shape[0])], axis=0)
    near_surface_v = np.mean(v[: min(3, v.shape[0])], axis=0)
    shift_x = int(np.clip(np.mean(near_surface_u) * CLOUD_ADVECT_BLEND, -8, 8))
    shift_y = int(np.clip(-np.mean(near_surface_v) * CLOUD_ADVECT_BLEND, -8, 8))
    future = np.roll(cloud_2d, shift=(shift_y, shift_x), axis=(0, 1))
    return future.astype(np.float32), {
        "shift_x_pixels": int(shift_x),
        "shift_y_pixels": int(shift_y),
        "future_cloud_mean": float(np.mean(future)),
        "future_cloud_max": float(np.max(future)),
    }


def _predict_future_wind(u: np.ndarray, v: np.ndarray, conf: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    u_mean = _neighbor_mean(u)
    v_mean = _neighbor_mean(v)
    future_u = (1.0 - 0.15) * u + 0.15 * u_mean
    future_v = (1.0 - 0.15) * v + 0.15 * v_mean
    future_conf = np.clip(conf * 0.95, 0.0, 1.0)
    return future_u.astype(np.float32), future_v.astype(np.float32), future_conf.astype(np.float32)


def _build_downlink_roi(future_cloud: np.ndarray, u: np.ndarray, v: np.ndarray) -> list[dict[str, Any]]:
    h, w = future_cloud.shape
    windows = []
    for i, (cy, cx) in enumerate([(h // 3, w // 3), (2 * h // 3, 2 * w // 3)]):
        y0 = max(0, cy - 64)
        y1 = min(h, cy + 64)
        x0 = max(0, cx - 64)
        x1 = min(w, cx + 64)
        windows.append(
            {
                "flight_stub_id": f"downlink_stub_{i}",
                "roi_yx": [int(y0), int(y1), int(x0), int(x1)],
                "future_cloud_mean": float(np.mean(future_cloud[y0:y1, x0:x1])),
                "future_wind_speed_mean": float(np.mean(np.sqrt(u[:, y0:y1, x0:x1] ** 2 + v[:, y0:y1, x0:x1] ** 2))),
            }
        )
    return windows


def process_frame(summary_row: dict[str, Any]) -> dict[str, Any]:
    payload = _load_stage4(Path(summary_row["output_npz"]))
    u = np.asarray(payload[C4_RECON_U], dtype=np.float32)
    v = np.asarray(payload[C4_RECON_V], dtype=np.float32)
    conf = np.asarray(payload[C4_RECON_CONF], dtype=np.float32)
    c_joint = np.asarray(payload[C4_C_JOINT_3D], dtype=np.float32)
    cloud_2d = np.asarray(payload[C4_CLOUD_2D], dtype=np.float32)

    u1, v1, pinn_metrics = _pinn_refine(u, v, conf)
    u2, v2 = _diffusion_refine(u1, v1, conf, c_joint)
    future_u, future_v, future_conf = _predict_future_wind(u2, v2, conf)
    future_cloud, cloud_metrics = _predict_future_cloud(cloud_2d, u2, v2)
    downlink = _build_downlink_roi(future_cloud, future_u, future_v)

    out_path = STAGE5_OUTPUT_DIR / f"frame_{summary_row['time_str']}_wind_cloud_demo.npz"
    STAGE5_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        out_path,
        **{
            C2_TIME_STR: np.array(summary_row["time_str"]),
            C5_REFINED_U: u2,
            C5_REFINED_V: v2,
            C5_REFINED_CONF: conf,
            C5_FUTURE_WIND_U: future_u,
            C5_FUTURE_WIND_V: future_v,
            C5_FUTURE_WIND_CONF: future_conf,
            C5_FUTURE_CLOUD_2D: future_cloud,
            C5_FUTURE_CLOUD_METRICS_JSON: np.array(json.dumps(cloud_metrics, ensure_ascii=False)),
            C5_DOWNLINK_ROI_JSON: np.array(json.dumps(downlink, ensure_ascii=False)),
        },
    )
    return {
        "time_str": summary_row["time_str"],
        "output_npz": str(out_path),
        "future_wind_generated": 1,
        "future_cloud_generated": 1,
        "cloud_forwarding_enabled": 1,
        "downlink_roi_count": len(downlink),
        **pinn_metrics,
        **cloud_metrics,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Centralized v1 Stage5 wind-cloud forecast demo.")
    parser.add_argument(
        "--stage4-summary",
        type=Path,
        default=Path("/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_center/stage4_center_summary.json"),
    )
    args = parser.parse_args()
    rows = _load_json(args.stage4_summary)
    out_rows = [process_frame(row) for row in rows]
    summary_path = STAGE5_OUTPUT_DIR / "stage5_center_summary.json"
    summary_path.write_text(json.dumps(out_rows, ensure_ascii=False, indent=2), encoding="utf-8")
    print(summary_path)


if __name__ == "__main__":
    main()
