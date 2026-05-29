"""Trace Stage4 hold-out point errors back to nearby training observations."""

from __future__ import annotations

import argparse
import csv
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

from stage.centralized_v1.configs.centralized_v1_config import REGENERATED_STAGE2_OUTPUT_DIR
from stage.centralized_v1.configs.centralized_v1_contract import (
    C2_CONTEXT_WIND_RECORDS,
    C2_GRID_SHAPE,
    C2_WIND_RECORDS,
    C4_RECON_U,
    C4_RECON_V,
)
from stage.centralized_v1.core.centralized_stage4_ground_recon import (
    DEFAULT_QC_CALIBRATION,
    POINT_EXTREME_WIND_THRESHOLD_MPS,
    POINT_HIGH_ERROR_THRESHOLD_MPS,
    POINT_REMOTE_SUPPORT_THRESHOLD_VOX,
    POINT_STRONG_WIND_THRESHOLD_MPS,
    RAPID_VERTICAL_JUMP_DIAGNOSTIC_THRESHOLD_MPS,
    _build_wind_observations,
    _idx_to_geo_point,
    _load_json,
    _load_stage2_npz,
    _nearest_observation_diagnostics,
    _nearest_role_gap,
    _records,
    _safe_float,
    _split_holdout,
    _vertical_jump_field,
)


DEFAULT_EXPANDED_STAGE4 = Path("/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_center_strict_expanded")


def _parse_frame_times(text: str) -> list[str]:
    return [token.strip() for token in str(text).split(",") if token.strip()]


def _load_summary_rows(stage4_dir: Path) -> list[dict[str, Any]]:
    path = stage4_dir / "stage4_center_summary.json"
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, list) else []


def _auto_high_error_frame_times(stage4_dir: Path, *, min_rmse: float, top_n: int) -> list[str]:
    rows = _load_summary_rows(stage4_dir)
    scored = []
    for row in rows:
        time_str = str(row.get("time_str", ""))
        if not time_str:
            continue
        rmse = _safe_float(row.get("rmse_vector"), 0.0)
        holdout = int(_safe_float(row.get("holdout_wind_records"), 0.0))
        if holdout <= 0:
            continue
        if rmse >= float(min_rmse):
            scored.append((rmse, time_str))
    scored.sort(reverse=True)
    if top_n > 0:
        scored = scored[:top_n]
    return [time_str for _rmse, time_str in scored]


def _read_point_eval(path: Path) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))


def _stage2_rows_by_time(path: Path) -> dict[str, dict[str, Any]]:
    return {str(row["time_str"]): row for row in _load_json(path)}


def _nearest_trace_stats(nearest_rows: list[dict[str, Any]]) -> dict[str, Any]:
    nearest_role_gap_mps, nearest_current_count, nearest_context_count = _nearest_role_gap(nearest_rows)
    speeds = [float(np.hypot(_safe_float(row.get("u")), _safe_float(row.get("v")))) for row in nearest_rows]
    context_time = [
        _safe_float(row.get("time_conf"))
        for row in nearest_rows
        if str(row.get("source_role")) == "context_wind"
    ]
    qc_flagged = [row for row in nearest_rows if str(row.get("qc_flags", "ok") or "ok") != "ok"]
    return {
        "nearest_role_gap_mps": nearest_role_gap_mps,
        "nearest_current_count": nearest_current_count,
        "nearest_context_count": nearest_context_count,
        "nearest_speed_max_mps": float(max(speeds)) if speeds else 0.0,
        "nearest_context_time_conf_min": float(min(context_time)) if context_time else "",
        "nearest_context_time_conf_mean": float(np.mean(context_time)) if context_time else "",
        "nearest_qc_flagged_count": int(len(qc_flagged)),
    }


def _trace_qc_review(
    *,
    vector_error: float,
    gt_speed: float,
    pred_speed: float,
    recon_confidence: float,
    nearest_train_distance_vox: Any,
    nearest_role_gap_mps: float,
    nearest_current_count: int,
    nearest_context_count: int,
    nearest_qc_flagged_count: int,
    recon_vertical_jump_mps: float,
    vertical_speed_gap_mps: float,
    vertical_neighbor_max_speed_mps: float,
    role_conflict_at_point: bool,
    role_conflict_component_gap_at_point_mps: float,
    role_conflict_threshold_at_point_mps: float,
    high_error_threshold_mps: float,
    strong_speed_threshold_mps: float,
    extreme_speed_threshold_mps: float,
    remote_distance_threshold_vox: float,
    vertical_jump_threshold_mps: float,
) -> tuple[bool, str, str]:
    reasons = []
    recommendation = []
    if gt_speed >= extreme_speed_threshold_mps:
        reasons.append("extreme_truth_speed")
        recommendation.append("separate_qc_stratum_or_review_truth_label")
    elif gt_speed >= strong_speed_threshold_mps:
        reasons.append("strong_truth_speed")
        recommendation.append("report_strong_wind_subset")
    if pred_speed >= extreme_speed_threshold_mps:
        reasons.append("extreme_prediction_speed")
        recommendation.append("cap_or_review_prediction_plausibility")
    if vector_error >= high_error_threshold_mps:
        reasons.append("high_vector_error")
        recommendation.append("include_in_high_error_trace")
    if recon_confidence <= 1e-6:
        reasons.append("near_zero_reconstruction_confidence")
        recommendation.append("downweight_in_training_loss")
    nearest_distance = _safe_float(nearest_train_distance_vox, -1.0)
    if nearest_distance >= remote_distance_threshold_vox:
        reasons.append("remote_training_support")
        recommendation.append("density_aware_loss_weight")
    if nearest_context_count > 0 and nearest_current_count == 0:
        reasons.append("context_only_nearest_support")
        recommendation.append("separate_context_only_points")
    if nearest_context_count > 0 and nearest_role_gap_mps >= high_error_threshold_mps:
        reasons.append("nearest_current_context_role_gap")
        recommendation.append("adaptive_role_conflict_or_context_downweight")
    if role_conflict_at_point:
        reasons.append("role_conflict_triggered_at_holdout_voxel")
        recommendation.append("inspect_adaptive_context_retention")
    elif nearest_current_count > 0 and nearest_context_count > 0 and role_conflict_component_gap_at_point_mps >= high_error_threshold_mps:
        reasons.append("untriggered_role_gap_at_holdout_voxel")
        recommendation.append("lower_adaptive_threshold_or_increase_current_density_weight")
    if nearest_current_count > 0 and nearest_context_count > 0 and role_conflict_threshold_at_point_mps > 0 and role_conflict_component_gap_at_point_mps >= role_conflict_threshold_at_point_mps:
        recommendation.append("candidate_role_conflict_boundary_case")
    if nearest_qc_flagged_count > 0:
        reasons.append("nearest_training_qc_flagged")
        recommendation.append("propagate_source_qc_to_trace")
    if recon_vertical_jump_mps >= vertical_jump_threshold_mps:
        reasons.append("rapid_reconstructed_vertical_jump")
        recommendation.append("vertical_consistency_review")
    if gt_speed >= strong_speed_threshold_mps and recon_vertical_jump_mps <= 2.0:
        reasons.append("strong_wind_vertical_oversmoothing_candidate")
        recommendation.append("avoid_over_smoothing_strong_layer")
    if gt_speed >= strong_speed_threshold_mps and vertical_speed_gap_mps >= vertical_jump_threshold_mps:
        reasons.append("strong_wind_vertical_context_mismatch_candidate")
        recommendation.append("review_vertical_neighbor_context")
    if gt_speed >= strong_speed_threshold_mps and vertical_neighbor_max_speed_mps < strong_speed_threshold_mps * 0.70:
        reasons.append("strong_wind_vertically_isolated_candidate")
        recommendation.append("separate_jet_or_outlier_stratum")
    return bool(reasons), ";".join(reasons), ";".join(dict.fromkeys(recommendation))


def _qc_stratum(
    row: dict[str, Any],
    *,
    high_error_threshold_mps: float,
    strong_speed_threshold_mps: float,
    extreme_speed_threshold_mps: float,
) -> str:
    gt_speed = _safe_float(row.get("gt_speed"), 0.0)
    vector_error = _safe_float(row.get("vector_error"), 0.0)
    if gt_speed >= extreme_speed_threshold_mps:
        return "extreme_truth_speed_review"
    if vector_error >= high_error_threshold_mps and gt_speed >= strong_speed_threshold_mps:
        return "strong_wind_high_error"
    if vector_error >= high_error_threshold_mps:
        return "high_error"
    if str(row.get("nearest_train_source_role")) == "context_wind" and _safe_float(row.get("nearest_train_distance_vox"), 999.0) <= 2.0:
        return "context_nearby_sensitive"
    return "nominal"


def _trace_frame(
    time_str: str,
    stage2_row: dict[str, Any],
    stage4_dir: Path,
    *,
    holdout_fraction: float,
    holdout_count: int,
    confidence_mode: str,
    top_k: int,
    current_weight_boost: float,
    context_weight_scale: float,
    context_time_conf_power: float,
    high_error_threshold_mps: float,
    strong_speed_threshold_mps: float,
    extreme_speed_threshold_mps: float,
    remote_distance_threshold_vox: float,
    vertical_jump_threshold_mps: float,
) -> list[dict[str, Any]]:
    npz = _load_stage2_npz(Path(stage2_row["multimodal_vox_path"]))
    shape = tuple(int(v) for v in np.asarray(npz[C2_GRID_SHAPE], dtype=np.int32).tolist())
    wind_records = _records(npz.get(C2_WIND_RECORDS))
    context_wind_records = _records(npz.get(C2_CONTEXT_WIND_RECORDS))
    train_wind, _ = _split_holdout(wind_records, holdout_fraction, holdout_count)
    observations, _ = _build_wind_observations(
        train_wind,
        context_wind_records,
        confidence_mode,
        qc_calibration=DEFAULT_QC_CALIBRATION,
        current_weight_boost=current_weight_boost,
        context_weight_scale=context_weight_scale,
        context_time_conf_power=context_time_conf_power,
    )
    point_rows = _read_point_eval(stage4_dir / f"point_eval_{time_str}.json")
    vertical_jump = None
    frame_npz = stage4_dir / f"frame_{time_str}_center_strict.npz"
    if frame_npz.exists():
        with np.load(frame_npz, allow_pickle=True) as z:
            if C4_RECON_U in z.files and C4_RECON_V in z.files:
                vertical_jump = _vertical_jump_field(np.asarray(z[C4_RECON_U], dtype=np.float32), np.asarray(z[C4_RECON_V], dtype=np.float32))

    rows = []
    for row in sorted(point_rows, key=lambda item: float(item.get("vector_error", 0.0)), reverse=True):
        z = int(row["z"])
        y = int(row["y"])
        x = int(row["x"])
        nearest = _nearest_observation_diagnostics(z, y, x, observations, top_k=top_k)
        nearest_rows = nearest["nearest_observations"]
        nearest_stats = _nearest_trace_stats(nearest_rows)
        geo = _idx_to_geo_point(shape, z, y, x)
        gt_u = float(row.get("gt_u", 0.0))
        gt_v = float(row.get("gt_v", 0.0))
        pred_u = float(row.get("pred_u", 0.0))
        pred_v = float(row.get("pred_v", 0.0))
        vector_error = float(row.get("vector_error", 0.0))
        gt_speed = float(row.get("gt_speed", np.hypot(gt_u, gt_v)))
        pred_speed = float(row.get("pred_speed", np.hypot(pred_u, pred_v)))
        if vertical_jump is not None:
            recon_vertical_jump_mps = float(vertical_jump[z, y, x])
        else:
            recon_vertical_jump_mps = _safe_float(row.get("recon_vertical_jump_mps"), 0.0)
        qc_review_flag, qc_review_reasons, qc_action_hint = _trace_qc_review(
            vector_error=vector_error,
            gt_speed=gt_speed,
            pred_speed=pred_speed,
            recon_confidence=float(row.get("recon_confidence", 0.0)),
            nearest_train_distance_vox=nearest["nearest_train_distance_vox"],
            nearest_role_gap_mps=float(nearest_stats["nearest_role_gap_mps"]),
            nearest_current_count=int(nearest_stats["nearest_current_count"]),
            nearest_context_count=int(nearest_stats["nearest_context_count"]),
            nearest_qc_flagged_count=int(nearest_stats["nearest_qc_flagged_count"]),
            recon_vertical_jump_mps=recon_vertical_jump_mps,
            vertical_speed_gap_mps=_safe_float(row.get("vertical_speed_gap_mps"), 0.0),
            vertical_neighbor_max_speed_mps=_safe_float(row.get("vertical_neighbor_max_speed_mps"), 0.0),
            role_conflict_at_point=str(row.get("role_conflict_at_point", "False")).lower() == "true" or bool(row.get("role_conflict_at_point") is True),
            role_conflict_component_gap_at_point_mps=_safe_float(row.get("role_conflict_component_gap_at_point_mps"), 0.0),
            role_conflict_threshold_at_point_mps=_safe_float(row.get("role_conflict_threshold_at_point_mps"), 0.0),
            high_error_threshold_mps=high_error_threshold_mps,
            strong_speed_threshold_mps=strong_speed_threshold_mps,
            extreme_speed_threshold_mps=extreme_speed_threshold_mps,
            remote_distance_threshold_vox=remote_distance_threshold_vox,
            vertical_jump_threshold_mps=vertical_jump_threshold_mps,
        )
        rows.append(
            {
                "time_str": time_str,
                "z": z,
                "y": y,
                "x": x,
                "lat": geo["lat"],
                "lon": geo["lon"],
                "alt_m": geo["alt_m"],
                "gt_u": gt_u,
                "gt_v": gt_v,
                "gt_speed": gt_speed,
                "pred_u": pred_u,
                "pred_v": pred_v,
                "pred_speed": pred_speed,
                "u_error": float(row.get("u_error", 0.0)),
                "v_error": float(row.get("v_error", 0.0)),
                "vector_error": vector_error,
                "error_to_truth_speed_ratio": float(vector_error / max(1e-6, gt_speed)),
                "recon_confidence": float(row.get("recon_confidence", 0.0)),
                "recon_vertical_jump_mps": recon_vertical_jump_mps,
                "vertical_speed_gap_mps": _safe_float(row.get("vertical_speed_gap_mps"), 0.0),
                "vertical_neighbor_max_speed_mps": _safe_float(row.get("vertical_neighbor_max_speed_mps"), 0.0),
                "role_overlap_at_point": row.get("role_overlap_at_point", ""),
                "role_conflict_at_point": row.get("role_conflict_at_point", ""),
                "role_conflict_component_gap_at_point_mps": _safe_float(row.get("role_conflict_component_gap_at_point_mps"), 0.0),
                "role_conflict_threshold_at_point_mps": _safe_float(row.get("role_conflict_threshold_at_point_mps"), 0.0),
                "role_conflict_context_factor_at_point": _safe_float(row.get("role_conflict_context_factor_at_point"), 0.0),
                "role_conflict_current_density_at_point": _safe_float(row.get("role_conflict_current_density_at_point"), 0.0),
                "role_conflict_context_time_conf_at_point": _safe_float(row.get("role_conflict_context_time_conf_at_point"), 0.0),
                "qc_review_flag": qc_review_flag,
                "qc_review_reasons": qc_review_reasons,
                "qc_action_hint": qc_action_hint,
                "qc_stratum": _qc_stratum(
                    row,
                    high_error_threshold_mps=high_error_threshold_mps,
                    strong_speed_threshold_mps=strong_speed_threshold_mps,
                    extreme_speed_threshold_mps=extreme_speed_threshold_mps,
                ),
                "nearest_train_distance_vox": nearest["nearest_train_distance_vox"],
                "nearest_train_source_role": nearest["nearest_train_source_role"],
                "nearest_train_u": nearest["nearest_train_u"],
                "nearest_train_v": nearest["nearest_train_v"],
                "nearest_train_base_weight": nearest["nearest_train_base_weight"],
                **nearest_stats,
                "nearest_observations_json": json.dumps(nearest_rows, ensure_ascii=False),
            }
        )
    return rows


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _write_md(path: Path, rows: list[dict[str, Any]], top_n: int) -> None:
    lines = [
        "# Stage4 Point Error Trace",
        "",
        "Rows are sorted by vector error. Nearest observations are training/current or context wind observations; hold-out labels are not included.",
        "",
        "| frame | z/y/x | gt speed | pred speed | vector error | conf | stratum | QC review | reasons | action hint | nearest dist/role gap |",
        "| --- | --- | ---: | ---: | ---: | ---: | --- | --- | --- | --- | ---: |",
    ]
    for row in rows[:top_n]:
        lines.append(
            f"| `{row['time_str']}` | `{row['z']}/{row['y']}/{row['x']}` | "
            f"{row['gt_speed']:.3f} | {row['pred_speed']:.3f} | "
            f"{row['vector_error']:.3f} | {row['recon_confidence']:.3f} | "
            f"`{row.get('qc_stratum', '')}` | `{row['qc_review_flag']}` | "
            f"`{row['qc_review_reasons']}` | `{row.get('qc_action_hint', '')}` | "
            f"{row['nearest_train_distance_vox']}/{row['nearest_role_gap_mps']:.3f} |"
        )
    strata: dict[str, int] = {}
    for row in rows:
        key = str(row.get("qc_stratum", ""))
        strata[key] = strata.get(key, 0) + 1
    lines.extend(["", "## QC Strata", "", "| stratum | count |", "| --- | ---: |"])
    for key, count in sorted(strata.items()):
        lines.append(f"| `{key}` | {count} |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Trace high-error Stage4 hold-out points.")
    parser.add_argument("--stage2-summary", type=Path, default=REGENERATED_STAGE2_OUTPUT_DIR / "stage2_multimodal_summary.json")
    parser.add_argument("--stage4-dir", type=Path, default=DEFAULT_EXPANDED_STAGE4)
    parser.add_argument("--frame-times", default="20260206174200,20260207022400")
    parser.add_argument("--auto-high-error", action="store_true")
    parser.add_argument("--auto-min-rmse", type=float, default=20.0)
    parser.add_argument("--auto-top-n-frames", type=int, default=20)
    parser.add_argument("--holdout-fraction", type=float, default=0.125)
    parser.add_argument("--holdout-count", type=int, default=0)
    parser.add_argument("--confidence-mode", default="diagnostic_only")
    parser.add_argument("--current-weight-boost", type=float, default=1.0)
    parser.add_argument("--context-weight-scale", type=float, default=1.0)
    parser.add_argument("--context-time-conf-power", type=float, default=1.0)
    parser.add_argument("--top-k-nearest", type=int, default=5)
    parser.add_argument("--top-n-md", type=int, default=20)
    parser.add_argument("--high-error-threshold-mps", type=float, default=POINT_HIGH_ERROR_THRESHOLD_MPS)
    parser.add_argument("--strong-speed-threshold-mps", type=float, default=POINT_STRONG_WIND_THRESHOLD_MPS)
    parser.add_argument("--extreme-speed-threshold-mps", type=float, default=POINT_EXTREME_WIND_THRESHOLD_MPS)
    parser.add_argument("--remote-distance-threshold-vox", type=float, default=POINT_REMOTE_SUPPORT_THRESHOLD_VOX)
    parser.add_argument("--vertical-jump-threshold-mps", type=float, default=RAPID_VERTICAL_JUMP_DIAGNOSTIC_THRESHOLD_MPS)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_EXPANDED_STAGE4 / "diagnostics")
    args = parser.parse_args()

    stage2_rows = _stage2_rows_by_time(args.stage2_summary)
    frame_times = _parse_frame_times(args.frame_times)
    if args.auto_high_error:
        auto_times = _auto_high_error_frame_times(args.stage4_dir, min_rmse=float(args.auto_min_rmse), top_n=int(args.auto_top_n_frames))
        frame_times = list(dict.fromkeys(frame_times + auto_times))
    all_rows = []
    for time_str in frame_times:
        if time_str not in stage2_rows:
            raise ValueError(f"Frame missing from Stage2 summary: {time_str}")
        rows = _trace_frame(
            time_str,
            stage2_rows[time_str],
            args.stage4_dir,
            holdout_fraction=float(args.holdout_fraction),
            holdout_count=int(args.holdout_count),
            confidence_mode=str(args.confidence_mode),
            top_k=int(args.top_k_nearest),
            current_weight_boost=float(args.current_weight_boost),
            context_weight_scale=float(args.context_weight_scale),
            context_time_conf_power=float(args.context_time_conf_power),
            high_error_threshold_mps=float(args.high_error_threshold_mps),
            strong_speed_threshold_mps=float(args.strong_speed_threshold_mps),
            extreme_speed_threshold_mps=float(args.extreme_speed_threshold_mps),
            remote_distance_threshold_vox=float(args.remote_distance_threshold_vox),
            vertical_jump_threshold_mps=float(args.vertical_jump_threshold_mps),
        )
        _write_csv(args.out_dir / f"stage4_error_trace_{time_str}.csv", rows)
        all_rows.extend(rows)

    all_rows.sort(key=lambda item: float(item.get("vector_error", 0.0)), reverse=True)
    _write_csv(args.out_dir / "stage4_error_trace_high_error_frames.csv", all_rows)
    _write_md(args.out_dir / "stage4_error_trace_high_error_frames.md", all_rows, int(args.top_n_md))
    print(args.out_dir / "stage4_error_trace_high_error_frames.csv")


if __name__ == "__main__":
    main()
