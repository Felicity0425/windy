"""Stage-4 full-run readiness report.

This script is intentionally engineering-oriented. It answers:
1. Is `stage4_summary.json` structurally sane?
2. Are the main reconstruction metrics in a usable range?
3. Is the dataset good enough for a first-pass baseline run?
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


def _to_float_array(items: list[dict[str, Any]], key: str) -> np.ndarray:
    values: list[float] = []
    for item in items:
        try:
            values.append(float(item.get(key, 0.0)))
        except Exception:
            values.append(0.0)
    return np.asarray(values, dtype=np.float64)


def _to_int_array(items: list[dict[str, Any]], key: str) -> np.ndarray:
    values: list[int] = []
    for item in items:
        try:
            values.append(int(item.get(key, 0)))
        except Exception:
            values.append(0)
    return np.asarray(values, dtype=np.int64)


def _describe(values: np.ndarray) -> dict[str, float]:
    if values.size == 0:
        return {
            "count": 0,
            "min": 0.0,
            "p10": 0.0,
            "p25": 0.0,
            "p50": 0.0,
            "p75": 0.0,
            "p90": 0.0,
            "max": 0.0,
            "mean": 0.0,
        }
    return {
        "count": int(values.size),
        "min": float(np.min(values)),
        "p10": float(np.quantile(values, 0.10)),
        "p25": float(np.quantile(values, 0.25)),
        "p50": float(np.quantile(values, 0.50)),
        "p75": float(np.quantile(values, 0.75)),
        "p90": float(np.quantile(values, 0.90)),
        "max": float(np.max(values)),
        "mean": float(np.mean(values)),
    }


def _topk_examples(items: list[dict[str, Any]], key: str, k: int = 5, reverse: bool = True) -> list[dict[str, Any]]:
    sorted_items = sorted(items, key=lambda x: float(x.get(key, 0.0)), reverse=reverse)
    out: list[dict[str, Any]] = []
    for item in sorted_items[:k]:
        out.append(
            {
                "source_index": item.get("source_index"),
                "time_str": item.get("time_str"),
                key: item.get(key),
                "wind_voxels": item.get("wind_voxels"),
                "wind_edges": item.get("flight_ff_wind_edges"),
                "recon_conf_mean": item.get("recon_conf_mean"),
                "recon_conf_p50": item.get("recon_conf_p50"),
                "recon_coverage_ratio": item.get("recon_coverage_ratio"),
            }
        )
    return out


def _evaluate_readiness(
    items: list[dict[str, Any]],
    export_report: dict[str, Any] | None,
) -> dict[str, Any]:
    total = len(items)
    triggered = _to_int_array(items, "recon_triggered")
    conf = _to_float_array(items, "recon_conf_mean")
    conf_p50 = _to_float_array(items, "recon_conf_p50")
    conf_p90 = _to_float_array(items, "recon_conf_p90")
    coverage = _to_float_array(items, "recon_coverage_ratio")
    forecast_cov = _to_float_array(items, "forecast_coverage_ratio")
    wind_edges = _to_int_array(items, "flight_ff_wind_edges")
    wind_voxels = _to_int_array(items, "wind_voxels")
    wind_keep_ratio = _to_float_array(items, "wind_keep_ratio")
    pruned_voxels = _to_int_array(items, "recon_pruned_voxels")
    support_domain = _to_int_array(items, "recon_support_domain_voxels")

    high_wind_threshold = float(np.quantile(wind_voxels, 0.90)) if wind_voxels.size > 0 else 0.0
    high_wind_items = [x for x in items if high_wind_threshold > 0 and float(x.get("wind_voxels", 0)) >= high_wind_threshold]
    high_conf = _to_float_array(high_wind_items, "recon_conf_mean")
    high_cov = _to_float_array(high_wind_items, "recon_coverage_ratio")

    notes: list[str] = []
    recommendation = "ready_for_first_training_pass"

    if total < 100:
        recommendation = "caution_small_sample"
        notes.append("当前 summary 帧数较少，结论更适合局部验证，不适合作为最终全量质量结论。")

    if conf.size > 0 and (
        float(np.max(conf)) > 1.0
        or float(np.min(conf)) < 0.0
        or float(np.max(coverage)) > 1.0
        or float(np.min(coverage)) < 0.0
        or (forecast_cov.size > 0 and (float(np.max(forecast_cov)) > 1.0 or float(np.min(forecast_cov)) < 0.0))
    ):
        recommendation = "not_ready"
        notes.append("summary 出现越界指标，说明 Stage-4 指标口径仍需修正。")

    if triggered.size > 0 and float(np.mean(triggered > 0)) < 0.05:
        recommendation = "not_ready"
        notes.append("触发帧占比过低，说明 Stage-4 事件触发可能过严。")

    if conf.size > 0 and float(np.quantile(conf, 0.50)) < 0.20:
        recommendation = "not_ready"
        notes.append("recon_conf_mean 中位数过低，说明整体重构证据偏弱。")

    if coverage.size > 0 and float(np.quantile(coverage, 0.50)) < 0.03:
        recommendation = "not_ready"
        notes.append("recon_coverage_ratio 中位数过低，说明有效重构区域偏少。")

    if wind_edges.size > 0 and float(np.quantile(wind_edges, 0.50)) < 20:
        recommendation = "not_ready"
        notes.append("flight_ff_wind_edges 中位数过低，说明 Stage-3 风图仍偏弱。")

    if high_conf.size > 0 and float(np.quantile(high_conf, 0.50)) < 0.30:
        if recommendation == "ready_for_first_training_pass":
            recommendation = "caution_highwind_quality"
        notes.append("高风帧上的重构置信度仍偏低，适合继续优化后再做高质量训练。")

    if high_cov.size > 0 and float(np.quantile(high_cov, 0.50)) < 0.05:
        if recommendation == "ready_for_first_training_pass":
            recommendation = "caution_highwind_quality"
        notes.append("高风帧上的覆盖率仍偏低，说明 Stage-4 support fill 仍可增强。")

    if conf_p50.size > 0 and float(np.quantile(conf_p50, 0.50)) < 0.15:
        if recommendation == "ready_for_first_training_pass":
            recommendation = "caution_low_confidence_resolution"
        notes.append("recon_conf_p50 中位数仍偏低，说明扩展区域的置信水平仍偏弱。")

    if conf_p90.size > 0 and float(np.quantile(conf_p90, 0.50)) < 0.50:
        if recommendation == "ready_for_first_training_pass":
            recommendation = "caution_high_conf_core_small"
        notes.append("高置信核心区仍不够强，说明当前直接证据区偏小。")

    if export_report is not None:
        bad = int(export_report.get("bad", 0))
        if bad > 0:
            recommendation = "not_ready"
            notes.append(f"export 报告中 bad={bad}，说明仍有样本结构问题。")

    if wind_keep_ratio.size > 0 and float(np.quantile(wind_keep_ratio, 0.50)) < 0.60:
        if recommendation == "ready_for_first_training_pass":
            recommendation = "caution_stage4_filtering"
        notes.append("Stage-4 对 wind voxels 的保留比例偏低，建议检查清洗阈值是否过严。")

    if pruned_voxels.size > 0 and support_domain.size > 0:
        pruned_ratio = pruned_voxels / np.maximum(1, support_domain)
        if float(np.quantile(pruned_ratio, 0.50)) > 0.80:
            if recommendation == "ready_for_first_training_pass":
                recommendation = "caution_heavy_pruning"
            notes.append("低质量尾部裁剪比例较高，说明 Stage-4 原始扩展仍偏宽。")

    if not notes:
        notes.append("当前数据已满足第一版训练集生成条件，建议先进行 baseline 训练，再按训练结果迭代重构逻辑。")

    return {
        "recommendation": recommendation,
        "notes": notes,
        "high_wind_threshold": high_wind_threshold,
        "high_wind_frame_count": len(high_wind_items),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize Stage-4 full-run readiness for training.")
    parser.add_argument("--summary", required=True, help="Path to stage4_summary.json")
    parser.add_argument("--export-report", default="", help="Optional path to export report JSON")
    parser.add_argument("--out-json", default="", help="Optional output JSON report path")
    args = parser.parse_args()

    summary_path = Path(args.summary)
    data = _load_json(summary_path)
    if not isinstance(data, list):
        raise SystemExit("stage4_summary.json format invalid: expected list")

    export_report = None
    if args.export_report:
        export_path = Path(args.export_report)
        if export_path.exists():
            export_report = _load_json(export_path)

    triggered_items = [x for x in data if int(x.get("recon_triggered", 0)) > 0]

    report = {
        "summary_path": str(summary_path),
        "frame_count": len(data),
        "triggered_count": len(triggered_items),
        "triggered_ratio": float(len(triggered_items) / max(1, len(data))),
        "metrics": {
            "recon_conf_mean": _describe(_to_float_array(data, "recon_conf_mean")),
            "recon_conf_p50": _describe(_to_float_array(data, "recon_conf_p50")),
            "recon_conf_p90": _describe(_to_float_array(data, "recon_conf_p90")),
            "recon_coverage_ratio": _describe(_to_float_array(data, "recon_coverage_ratio")),
            "forecast_coverage_ratio": _describe(_to_float_array(data, "forecast_coverage_ratio")),
            "flight_ff_wind_edges": _describe(_to_int_array(data, "flight_ff_wind_edges")),
            "recon_seed_strength": _describe(_to_float_array(data, "recon_seed_strength")),
            "recon_filled_voxels": _describe(_to_int_array(data, "recon_filled_voxels")),
            "recon_pruned_voxels": _describe(_to_int_array(data, "recon_pruned_voxels")),
            "recon_support_domain_voxels": _describe(_to_int_array(data, "recon_support_domain_voxels")),
            "support_fill_voxels": _describe(_to_int_array(data, "support_fill_voxels")),
            "temporal_fill_voxels": _describe(_to_int_array(data, "temporal_fill_voxels")),
            "comm_joint_voxels": _describe(_to_int_array(data, "comm_joint_voxels")),
            "comm_wind_voxels": _describe(_to_int_array(data, "comm_wind_voxels")),
            "comm_motion_voxels": _describe(_to_int_array(data, "comm_motion_voxels")),
            "pinn_div_mean": _describe(_to_float_array(data, "pinn_div_mean")),
            "pinn_smooth_mean": _describe(_to_float_array(data, "pinn_smooth_mean")),
            "physics_weight_mean": _describe(_to_float_array(data, "physics_weight_mean")),
            "wind_keep_ratio": _describe(_to_float_array(data, "wind_keep_ratio")),
            "motion_keep_ratio": _describe(_to_float_array(data, "motion_keep_ratio")),
            "amdar_keep_ratio": _describe(_to_float_array(data, "amdar_keep_ratio")),
            "wind_overlap_ratio": _describe(_to_float_array(data, "wind_overlap_ratio")),
        },
        "top_examples": {
            "best_conf": _topk_examples(data, "recon_conf_mean", k=5, reverse=True),
            "best_coverage": _topk_examples(data, "recon_coverage_ratio", k=5, reverse=True),
            "worst_conf": _topk_examples(data, "recon_conf_mean", k=5, reverse=False),
            "worst_coverage": _topk_examples(data, "recon_coverage_ratio", k=5, reverse=False),
        },
        "export_report": export_report,
        "readiness": _evaluate_readiness(data, export_report),
    }

    print("=== Stage4 Training Readiness ===")
    print("summary_path =", report["summary_path"])
    print("frame_count =", report["frame_count"])
    print("triggered_count =", report["triggered_count"])
    print("triggered_ratio =", f"{report['triggered_ratio']:.6f}")
    print()

    for key, stats in report["metrics"].items():
        print(f"[{key}]")
        for sub_key in ("count", "min", "p10", "p25", "p50", "p75", "p90", "max", "mean"):
            print(f"  {sub_key} = {stats[sub_key]}")
        print()

    readiness = report["readiness"]
    print("[readiness]")
    print("  recommendation =", readiness["recommendation"])
    print("  high_wind_threshold =", readiness["high_wind_threshold"])
    print("  high_wind_frame_count =", readiness["high_wind_frame_count"])
    for note in readiness["notes"]:
        print("  note =", note)
    print()

    if args.out_json:
        out_path = Path(args.out_json)
        out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
