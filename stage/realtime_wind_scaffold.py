"""Realtime sliding-window scaffold for wind reconstruction.

This module does not replace the existing offline pipeline. It provides a
clean runtime-facing interface that can later host a lightweight model,
PINN-based physical correction, and diffusion refinement hooks.

The current implementation is intentionally conservative:
- it consumes the existing stage outputs;
- it builds model-ready tensors;
- it produces a fast baseline reconstruction from the latest window;
- it exposes placeholders for PINN and diffusion refinement.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import polars as pl

import pipeline_config as cfg
from stage.reconstruct_utils import _reconstruct_wind_field
from stage.stage4_pack import (
    _build_where2comm_targets,
    _compute_pinn_proxy_fields,
    _build_diffusion_condition_tensors,
    _forecast_next_wind_field,
    _compute_hazard_proxies,
)
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


@dataclass
class RealtimeWindowSample:
    """Model-ready bundle for one sliding-window sample."""

    filename: str
    time_str: str
    timestamp_utc: str
    radar_img: np.ndarray
    wind_grouped: pl.DataFrame
    loc_grouped: pl.DataFrame
    loc_motion_grouped: pl.DataFrame
    amdar_grouped: pl.DataFrame
    turb_grouped: pl.DataFrame
    grid_shape: Tuple[int, int, int]
    tensors: Dict[str, np.ndarray]
    metadata: Dict[str, Any]


class RealtimeWindReconstructor:
    """A lightweight runtime scaffold for sliding-window reconstruction."""

    def __init__(self, window_size: int = 3):
        self.window_size = max(1, int(window_size))
        # 仅保留最近一帧的重构状态，用于实时一阶预测。
        self._prev_recon_state: Optional[Dict[str, np.ndarray]] = None
        self._sequence_counter = 0

    @staticmethod
    def _records_to_df(records: Any) -> pl.DataFrame:
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
        return pl.DataFrame(records.tolist() if hasattr(records, "tolist") else records)

    @staticmethod
    def _safe_load_npz(path: str) -> Dict[str, Any]:
        data = np.load(path, allow_pickle=True)
        return {k: data[k] for k in data.files}

    def load_stage2_frame(self, vox_path: str) -> RealtimeWindowSample:
        payload = self._safe_load_npz(vox_path)
        radar_img = payload.get(STAGE2_RADAR_IMG)
        if radar_img is None and "radar_2d" in payload:
            radar_img = payload["radar_2d"]
        if radar_img is None:
            radar_shape = payload.get(STAGE2_RADAR_SHAPE)
            if radar_shape is not None:
                h_dim, w_dim = tuple(int(x) for x in np.asarray(radar_shape).tolist())
                radar_img = np.zeros((h_dim, w_dim), dtype=np.uint8)
            else:
                radar_img = np.zeros((0, 0), dtype=np.uint8)

        grid_shape = payload.get(STAGE2_GRID_SHAPE)
        if grid_shape is None:
            grid_shape = np.array([cfg.Z_DIM, radar_img.shape[0], radar_img.shape[1]], dtype=np.int32)
        grid_tuple = tuple(int(x) for x in np.asarray(grid_shape).tolist())

        wind_grouped = self._records_to_df(payload.get(STAGE2_WIND_RECORDS))
        loc_grouped = self._records_to_df(payload.get(STAGE2_LOC_RECORDS))
        loc_motion_grouped = self._records_to_df(payload.get(STAGE2_MOTION_RECORDS))
        amdar_grouped = self._records_to_df(payload.get(STAGE2_AMDAR_RECORDS))
        turb_grouped = self._records_to_df(payload.get(STAGE2_TURB_RECORDS))

        filename = str(np.asarray(payload.get(STAGE2_FILENAME, "")).item())
        time_str = str(np.asarray(payload.get(STAGE2_TIME_STR, "")).item())
        timestamp_utc = str(np.asarray(payload.get(STAGE2_TIMESTAMP_UTC, "")).item())

        tensors = self.build_input_tensors(
            radar_img=radar_img,
            wind_grouped=wind_grouped,
            loc_grouped=loc_grouped,
            loc_motion_grouped=loc_motion_grouped,
            amdar_grouped=amdar_grouped,
            turb_grouped=turb_grouped,
        )
        metadata = {
            "source_path": vox_path,
            "z_dim": grid_tuple[0],
            "h_dim": grid_tuple[1],
            "w_dim": grid_tuple[2],
            "source_index": self._sequence_counter,
        }
        self._sequence_counter += 1

        return RealtimeWindowSample(
            filename=filename,
            time_str=time_str,
            timestamp_utc=timestamp_utc,
            radar_img=radar_img,
            wind_grouped=wind_grouped,
            loc_grouped=loc_grouped,
            loc_motion_grouped=loc_motion_grouped,
            amdar_grouped=amdar_grouped,
            turb_grouped=turb_grouped,
            grid_shape=grid_tuple,
            tensors=tensors,
            metadata=metadata,
        )

    def build_input_tensors(
        self,
        radar_img: np.ndarray,
        wind_grouped: pl.DataFrame,
        loc_grouped: pl.DataFrame,
        loc_motion_grouped: pl.DataFrame,
        amdar_grouped: pl.DataFrame,
        turb_grouped: pl.DataFrame,
    ) -> Dict[str, np.ndarray]:
        """Create model-ready tensors from the current frame.

        The tensor contract is intentionally simple and stable so a future
        learning model can consume the same shapes during offline training and
        online inference.
        """
        h_dim, w_dim = radar_img.shape[:2]
        z_dim = cfg.Z_DIM
        shape_3d = (z_dim, h_dim, w_dim)

        def _empty(fill_value: float = 0.0) -> np.ndarray:
            return np.full(shape_3d, fill_value, dtype=np.float32)

        wind_u = _empty(np.nan)
        wind_v = _empty(np.nan)
        wind_count = _empty(0.0)
        wind_conf = _empty(0.0)
        motion_u = _empty(np.nan)
        motion_v = _empty(np.nan)
        motion_count = _empty(0.0)
        amdar_u = _empty(np.nan)
        amdar_v = _empty(np.nan)
        turb_u = _empty(np.nan)
        turb_v = _empty(np.nan)
        obs_mask = np.zeros(shape_3d, dtype=np.float32)

        def _scatter(df: pl.DataFrame, u_col: str, v_col: str, base_u: np.ndarray, base_v: np.ndarray, count_arr: np.ndarray, conf_arr: Optional[np.ndarray] = None) -> None:
            if len(df) == 0:
                return
            needed = {"z", "y", "x", u_col, v_col}
            if not needed.issubset(set(df.columns)):
                return
            z = df["z"].to_numpy().astype(np.int32, copy=False)
            y = df["y"].to_numpy().astype(np.int32, copy=False)
            x = df["x"].to_numpy().astype(np.int32, copy=False)
            u = df[u_col].to_numpy().astype(np.float32, copy=False)
            v = df[v_col].to_numpy().astype(np.float32, copy=False)
            valid = np.isfinite(u) & np.isfinite(v)
            if not np.any(valid):
                return
            z, y, x, u, v = z[valid], y[valid], x[valid], u[valid], v[valid]
            count_name = "obs_count" if "obs_count" in df.columns else "motion_count" if "motion_count" in df.columns else None
            if count_name is not None:
                c = df[count_name].to_numpy().astype(np.float32, copy=False)[valid]
            else:
                c = np.ones(len(z), dtype=np.float32)
            if conf_arr is not None and "obs_conf" in df.columns:
                conf = df["obs_conf"].to_numpy().astype(np.float32, copy=False)[valid]
            else:
                conf = None

            for zi, yi, xi, uu, vv, cc in zip(z, y, x, u, v, c):
                if 0 <= zi < z_dim and 0 <= yi < h_dim and 0 <= xi < w_dim:
                    base_u[zi, yi, xi] = uu
                    base_v[zi, yi, xi] = vv
                    count_arr[zi, yi, xi] = cc
                    obs_mask[zi, yi, xi] = 1.0
            if conf_arr is not None and conf is not None:
                for zi, yi, xi, cf in zip(z, y, x, conf):
                    if 0 <= zi < z_dim and 0 <= yi < h_dim and 0 <= xi < w_dim:
                        conf_arr[zi, yi, xi] = cf

        _scatter(wind_grouped, "u", "v", wind_u, wind_v, wind_count, wind_conf)
        _scatter(loc_motion_grouped, "u_motion", "v_motion", motion_u, motion_v, motion_count, None)
        _scatter(amdar_grouped, "u", "v", amdar_u, amdar_v, _empty(0.0), None)
        _scatter(turb_grouped, "u", "v", turb_u, turb_v, _empty(0.0), None)

        radar_norm = radar_img.astype(np.float32)
        if radar_norm.size > 0:
            radar_norm = radar_norm / max(1.0, float(np.nanmax(radar_norm)))
        radar_3d = np.repeat(radar_norm[None, :, :], z_dim, axis=0)

        return {
            "radar": radar_3d.astype(np.float32),
            "wind_u": wind_u,
            "wind_v": wind_v,
            "wind_count": wind_count,
            "wind_conf": wind_conf,
            "motion_u": motion_u,
            "motion_v": motion_v,
            "motion_count": motion_count,
            "amdar_u": amdar_u,
            "amdar_v": amdar_v,
            "turb_u": turb_u,
            "turb_v": turb_v,
            "obs_mask": obs_mask,
        }

    def build_cooperative_tensors(
        self,
        wind_grouped: pl.DataFrame,
        loc_motion_grouped: pl.DataFrame,
        support_strength: np.ndarray,
        recon_conf: np.ndarray,
        h_dim: int,
        w_dim: int,
    ) -> Dict[str, np.ndarray]:
        """构建面向机载端协同感知的体素级通信候选。

        这里直接复用离线 Stage-4 里的 Where2Comm 风格候选生成逻辑，
        让实时端和离线端使用同一套“哪些体素最值得通信”的定义。
        """
        targets = _build_where2comm_targets(
            wind_grouped=wind_grouped,
            motion_grouped=loc_motion_grouped,
            support_strength=support_strength,
            recon_conf=recon_conf,
            h_dim=h_dim,
            w_dim=w_dim,
        )
        return {
            "comm_joint_idx": np.asarray(targets["joint_idx"], dtype=np.uint32),
            "comm_joint_score": np.asarray(targets["joint_score"], dtype=np.float32),
            "comm_wind_idx": np.asarray(targets["wind_idx"], dtype=np.uint32),
            "comm_motion_idx": np.asarray(targets["motion_idx"], dtype=np.uint32),
            "comm_uncertainty_idx": np.asarray(targets["uncertainty_idx"], dtype=np.uint32),
        }

    def reconstruct_baseline(
        self,
        wind_grouped: pl.DataFrame,
        loc_motion_grouped: pl.DataFrame,
        amdar_grouped: pl.DataFrame,
        turb_grouped: pl.DataFrame,
        h_dim: int,
        w_dim: int,
    ) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        return _reconstruct_wind_field(
            cfg.Z_DIM,
            h_dim,
            w_dim,
            wind_grouped,
            loc_motion_grouped,
            amdar_grouped,
            turb_grouped,
        )

    def pinn_refine(
        self,
        recon_u: np.ndarray,
        recon_v: np.ndarray,
        conf: np.ndarray,
    ) -> Dict[str, np.ndarray]:
        """Placeholder for future PINN-based correction."""
        return {
            "u": recon_u,
            "v": recon_v,
            "conf": conf,
        }

    def diffusion_refine(
        self,
        recon_u: np.ndarray,
        recon_v: np.ndarray,
        conf: np.ndarray,
    ) -> Dict[str, np.ndarray]:
        """Placeholder for future diffusion-based refinement."""
        return {
            "u": recon_u,
            "v": recon_v,
            "conf": conf,
        }

    def realtime_forecast(
        self,
        recon_u: np.ndarray,
        recon_v: np.ndarray,
        recon_conf: np.ndarray,
        recon_mask: np.ndarray,
        support_strength: np.ndarray,
        physics_weight: np.ndarray,
        where2comm_targets: Dict[str, np.ndarray],
        source_index: int,
    ) -> Dict[str, np.ndarray]:
        """生成一步前瞻预测。

        用途：
        - 机载端实时显示下一步风场变化趋势；
        - 在没有真值的在线环境中，先输出“预测版本”的风场与风险图。
        """
        forecast_u, forecast_v, forecast_conf, forecast_mask = _forecast_next_wind_field(
            recon_u=recon_u,
            recon_v=recon_v,
            recon_conf=recon_conf,
            recon_mask=recon_mask,
            support_strength=support_strength,
            physics_weight_3d=physics_weight,
            where2comm_targets={
                "joint_idx": where2comm_targets["comm_joint_idx"],
            },
            prev_recon_state=self._prev_recon_state,
            curr_source_index=source_index,
        )
        self._prev_recon_state = {
            "source_index": source_index,
            "recon_u": np.asarray(recon_u, dtype=np.float32).copy(),
            "recon_v": np.asarray(recon_v, dtype=np.float32).copy(),
            "recon_conf": np.asarray(recon_conf, dtype=np.float32).copy(),
            "recon_mask": np.asarray(recon_mask, dtype=np.float32).copy(),
        }
        return {
            "u": forecast_u,
            "v": forecast_v,
            "conf": forecast_conf,
            "mask": forecast_mask,
        }

    def hazard_refine(
        self,
        forecast_u: np.ndarray,
        forecast_v: np.ndarray,
        support_strength: np.ndarray,
        pinn_divergence: np.ndarray,
        pinn_smoothness: np.ndarray,
    ) -> Dict[str, np.ndarray]:
        """计算飞机端更关心的风险代理量。

        输出可以直接供：
        - 驾驶舱风切变/颠簸风险提示
        - 机群协同共享危险区
        """
        shear, turbulence, alert = _compute_hazard_proxies(
            forecast_u,
            forecast_v,
            support_strength,
            pinn_divergence,
            pinn_smoothness,
        )
        return {
            "shear": shear,
            "turbulence": turbulence,
            "alert": alert,
        }

    def run_frame(self, vox_path: str) -> Dict[str, Any]:
        sample = self.load_stage2_frame(vox_path)
        current_seq = int(sample.metadata.get("source_index", self._sequence_counter))
        h_dim, w_dim = sample.radar_img.shape[:2]
        baseline_u, baseline_v, baseline_conf, baseline_mask = self.reconstruct_baseline(
            sample.wind_grouped,
            sample.loc_motion_grouped,
            sample.amdar_grouped,
            sample.turb_grouped,
            h_dim,
            w_dim,
        )
        support_strength = np.clip(
            0.55 * sample.tensors["obs_mask"] +
            0.45 * (sample.tensors["motion_count"] / max(1.0, float(np.max(sample.tensors["motion_count"])) if np.max(sample.tensors["motion_count"]) > 0 else 1.0)),
            0.0,
            1.0,
        ).astype(np.float32)
        pinn_div, pinn_smooth, physics_weight = _compute_pinn_proxy_fields(
            np.nan_to_num(baseline_u, nan=0.0),
            np.nan_to_num(baseline_v, nan=0.0),
            support_strength,
        )
        coop = self.build_cooperative_tensors(
            sample.wind_grouped,
            sample.loc_motion_grouped,
            support_strength,
            np.nan_to_num(baseline_conf, nan=0.0),
            h_dim,
            w_dim,
        )
        pinn_out = self.pinn_refine(baseline_u, baseline_v, baseline_conf)
        diffusion_out = self.diffusion_refine(pinn_out["u"], pinn_out["v"], pinn_out["conf"])
        forecast_out = self.realtime_forecast(
            recon_u=np.nan_to_num(diffusion_out["u"], nan=0.0),
            recon_v=np.nan_to_num(diffusion_out["v"], nan=0.0),
            recon_conf=np.nan_to_num(diffusion_out["conf"], nan=0.0),
            recon_mask=baseline_mask,
            support_strength=support_strength,
            physics_weight=physics_weight,
            where2comm_targets=coop,
            source_index=current_seq,
        )
        hazard_out = self.hazard_refine(
            forecast_u=forecast_out["u"],
            forecast_v=forecast_out["v"],
            support_strength=support_strength,
            pinn_divergence=pinn_div,
            pinn_smoothness=pinn_smooth,
        )
        diffusion_condition = _build_diffusion_condition_tensors(
            radar_img=sample.radar_img,
            trajectory_3d=sample.tensors["obs_mask"],
            recon_u=np.nan_to_num(diffusion_out["u"], nan=0.0),
            recon_v=np.nan_to_num(diffusion_out["v"], nan=0.0),
            recon_conf=np.nan_to_num(diffusion_out["conf"], nan=0.0),
            support_strength=support_strength,
            physics_weight=physics_weight,
        )

        return {
            "filename": sample.filename,
            "time_str": sample.time_str,
            "timestamp_utc": sample.timestamp_utc,
            "baseline_u": baseline_u,
            "baseline_v": baseline_v,
            "baseline_conf": baseline_conf,
            "baseline_mask": baseline_mask,
            "pinn_u": pinn_out["u"],
            "pinn_v": pinn_out["v"],
            "pinn_conf": pinn_out["conf"],
            "diffusion_u": diffusion_out["u"],
            "diffusion_v": diffusion_out["v"],
            "diffusion_conf": diffusion_out["conf"],
            "forecast_u": forecast_out["u"],
            "forecast_v": forecast_out["v"],
            "forecast_conf": forecast_out["conf"],
            "forecast_mask": forecast_out["mask"],
            "hazard_shear": hazard_out["shear"],
            "hazard_turbulence": hazard_out["turbulence"],
            "hazard_alert": hazard_out["alert"],
            "comm_joint_idx": coop["comm_joint_idx"],
            "comm_joint_score": coop["comm_joint_score"],
            "comm_wind_idx": coop["comm_wind_idx"],
            "comm_motion_idx": coop["comm_motion_idx"],
            "comm_uncertainty_idx": coop["comm_uncertainty_idx"],
            "pinn_divergence": pinn_div,
            "pinn_smoothness": pinn_smooth,
            "physics_weight": physics_weight,
            "diffusion_condition": diffusion_condition,
            "inputs": sample.tensors,
            "metadata": sample.metadata,
        }
