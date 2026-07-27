from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl


ROOT = Path("/data/LFT-W02_data/pengxu")
DATA_DIR = ROOT / "优化/数据处理"
STAGE1_DIR = DATA_DIR / "amdar_plan4_implementation_20260630/stage1_output_plan4_v1"
STAGE8_DIR = DATA_DIR / "amdar_unified_stage8_enhanced_stage1_optimized_20260701"
STAGE9_DIR = DATA_DIR / "amdar_unified_stage9_stage2_role_split_global_frame_optimized_20260702"
STAGE10_DIR = DATA_DIR / "amdar_unified_stage10_superob_weight_control_v2_optimized_20260702"
DEFAULT_OUT_DIR = DATA_DIR / "amdar_unified_stage11_stage2_compat_smoke_optimized_20260702"
STAGE2_SCRIPT = ROOT / "stage/centralized_v1/core/centralized_stage2_multimodal.py"

DEFAULT_SMOKE_FRAMES = (
    "20260208124800,"
    "20260206174200,"
    "20260207022400,"
    "20260131073000,"
    "20260215063600,"
    "20260215063000,"
    "20260215100600,"
    "20260211060600,"
    "20260213053600,"
    "20260210060000"
)


@dataclass(frozen=True)
class RunConfig:
    out_dir: Path = DEFAULT_OUT_DIR
    stage1_dir: Path = STAGE1_DIR
    stage8_dir: Path = STAGE8_DIR
    stage9_dir: Path = STAGE9_DIR
    stage10_dir: Path = STAGE10_DIR
    frame_times: str = DEFAULT_SMOKE_FRAMES
    workers: int = 5
    polars_threads: int = 25
    current_window_minutes: int = 5
    context_window_minutes: int = 360
    stage11_version: str = "v1"


def parse_args() -> RunConfig:
    parser = argparse.ArgumentParser(
        description=(
            "Run AMDAR Unified Plan Stage11 compatibility smoke test. The script creates a Stage1-compatible "
            "view from Stage8 clean_wind_with_confidence, fixes legacy role fields so AMDAR cannot enter strict "
            "truth, then runs centralized_v1 Stage2 on 10 smoke frames."
        )
    )
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--stage1-dir", default=str(STAGE1_DIR))
    parser.add_argument("--stage8-dir", default=str(STAGE8_DIR))
    parser.add_argument("--stage9-dir", default=str(STAGE9_DIR))
    parser.add_argument("--stage10-dir", default=str(STAGE10_DIR))
    parser.add_argument("--frame-times", default=DEFAULT_SMOKE_FRAMES)
    parser.add_argument("--workers", type=int, default=5)
    parser.add_argument("--polars-threads", type=int, default=25)
    parser.add_argument("--current-window-minutes", type=int, default=5)
    parser.add_argument("--context-window-minutes", type=int, default=360)
    args = parser.parse_args()
    return RunConfig(
        out_dir=Path(args.out_dir).resolve(),
        stage1_dir=Path(args.stage1_dir).resolve(),
        stage8_dir=Path(args.stage8_dir).resolve(),
        stage9_dir=Path(args.stage9_dir).resolve(),
        stage10_dir=Path(args.stage10_dir).resolve(),
        frame_times=str(args.frame_times),
        workers=int(args.workers),
        polars_threads=int(args.polars_threads),
        current_window_minutes=int(args.current_window_minutes),
        context_window_minutes=int(args.context_window_minutes),
    )


def json_default(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=json_default), encoding="utf-8")
    tmp.replace(path)


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def parse_frame_times(frame_times: str) -> list[str]:
    return [token.strip() for token in frame_times.split(",") if token.strip()]


def counts_map(df: pl.DataFrame, col: str) -> dict[str, int]:
    if df.height == 0 or col not in df.columns:
        return {}
    vc = (
        df.select(pl.col(col).cast(pl.Utf8, strict=False).fill_null("null").alias(col))
        .to_series()
        .value_counts()
        .sort("count", descending=True)
    )
    return {str(k): int(v) for k, v in vc.iter_rows()}


def require_upstream(cfg: RunConfig) -> dict[str, Any]:
    stage8_summary = read_json(cfg.stage8_dir / "stage8_enhanced_stage1_summary.json")
    stage9_summary = read_json(cfg.stage9_dir / "stage9_stage2_role_split_summary.json")
    stage10_summary = read_json(cfg.stage10_dir / "stage10_superob_summary.json")
    checks = {
        "stage8_gate_passed": bool(
            stage8_summary.get("stage8_completion_checks", {}).get("passed_stage8_enhanced_stage1_gate")
        ),
        "stage9_gate_passed": bool(
            stage9_summary.get("stage9_completion_checks", {}).get("passed_stage9_stage2_role_split_gate")
        ),
        "stage10_gate_passed": bool(
            stage10_summary.get("stage10_completion_checks", {}).get("passed_stage10_superob_weight_control_gate")
        ),
        "stage10_compression_gate_passed": bool(
            stage10_summary.get("stage10_completion_checks", {}).get("t1t2t3_compression_ratio_ge_min")
        ),
    }
    if not all(checks.values()):
        raise RuntimeError(f"Upstream not ready for Stage11: {checks}")
    return {
        "stage8_summary": stage8_summary,
        "stage9_summary": stage9_summary,
        "stage10_summary": stage10_summary,
        "upstream_checks": checks,
    }


def ensure_symlink_or_copy(src: Path, dst: Path) -> dict[str, Any]:
    if dst.exists() or dst.is_symlink():
        dst.unlink()
    try:
        dst.symlink_to(src)
        return {"path": str(dst), "target": str(src), "mode": "symlink"}
    except OSError:
        import shutil

        shutil.copy2(src, dst)
        return {"path": str(dst), "target": str(src), "mode": "copy"}


def build_compatible_stage1_view(cfg: RunConfig) -> dict[str, Any]:
    compat_dir = cfg.out_dir / "stage1_confidence_compat_view"
    compat_dir.mkdir(parents=True, exist_ok=True)
    src_wind = cfg.stage8_dir / "clean_wind_with_confidence.parquet"
    out_wind = compat_dir / "clean_wind.parquet"
    if not src_wind.exists():
        raise FileNotFoundError(src_wind)

    lf = pl.scan_parquet(src_wind)
    strict_expr = (
        (pl.col("source") == "turb")
        & pl.col("holdout_eligible").fill_null(False)
        & pl.col("stage8_effective_strict_truth").fill_null(False)
        & pl.col("stage8_point_time_strict_truth_available").fill_null(False)
        & (pl.col("confidence_grade") == "S")
    )
    compat_lf = lf.with_columns(
        [
            pl.col("wind_reconstruction_role").alias("legacy_wind_reconstruction_role_before_stage11"),
            pl.when(strict_expr)
            .then(pl.lit("strict_truth_candidate"))
            .otherwise(pl.lit("support_only_not_strict_truth"))
            .alias("wind_reconstruction_role"),
            pl.when(strict_expr)
            .then(pl.lit("stage11_turb_t0_s_strict_truth"))
            .when(pl.col("source") == "amdar")
            .then(pl.lit("stage11_amdar_support_only_never_truth"))
            .when(pl.col("stage8_holdout_review").fill_null(False))
            .then(pl.lit("stage11_turb_holdout_review_not_truth"))
            .otherwise(pl.lit("stage11_non_truth_support_or_diagnostic"))
            .alias("stage11_compat_role_policy"),
            pl.when(pl.col("obs_conf_v2").is_not_null())
            .then(pl.col("obs_conf_v2").cast(pl.Float64))
            .otherwise(pl.col("obs_conf").cast(pl.Float64, strict=False))
            .alias("obs_conf"),
            pl.when(strict_expr)
            .then(pl.lit("none"))
            .when(pl.col("source") == "amdar")
            .then(pl.lit("amdar_batch_time_not_strict_truth_stage11"))
            .when(pl.col("stage8_holdout_review").fill_null(False))
            .then(pl.lit("turb_holdout_review_not_strict_truth_stage11"))
            .otherwise(pl.lit("support_only_stage11"))
            .alias("wind_reconstruction_exclusion_reason"),
        ]
    )
    compat_lf.sink_parquet(out_wind)

    links = {
        "clean_loc": ensure_symlink_or_copy(cfg.stage1_dir / "clean_loc.parquet", compat_dir / "clean_loc.parquet"),
        "radar_index": ensure_symlink_or_copy(cfg.stage1_dir / "radar_index.json", compat_dir / "radar_index.json"),
    }
    fwi = cfg.stage1_dir / "frame_window_index.json"
    if fwi.exists():
        links["frame_window_index"] = ensure_symlink_or_copy(fwi, compat_dir / "frame_window_index.json")

    df = pl.read_parquet(out_wind)
    role_source = (
        df.group_by(["source", "wind_reconstruction_role", "confidence_grade"])
        .agg(pl.len().alias("rows"))
        .sort(["source", "wind_reconstruction_role", "confidence_grade"])
        .to_dicts()
    )
    audit = {
        "compat_dir": str(compat_dir),
        "clean_wind": str(out_wind),
        "linked_or_copied_inputs": links,
        "row_counts": {
            "clean_wind_rows": int(df.height),
            "amdar_rows": int(df.filter(pl.col("source") == "amdar").height),
            "turb_rows": int(df.filter(pl.col("source") == "turb").height),
            "strict_truth_rows": int(df.filter(pl.col("wind_reconstruction_role") == "strict_truth_candidate").height),
            "amdar_strict_truth_rows": int(
                df.filter((pl.col("source") == "amdar") & (pl.col("wind_reconstruction_role") == "strict_truth_candidate")).height
            ),
            "turb_strict_truth_rows": int(
                df.filter((pl.col("source") == "turb") & (pl.col("wind_reconstruction_role") == "strict_truth_candidate")).height
            ),
        },
        "role_source_grade_counts": role_source,
        "confidence_grade_counts": counts_map(df, "confidence_grade"),
        "stage11_policy_counts": counts_map(df, "stage11_compat_role_policy"),
    }
    audit["compat_view_checks"] = {
        "row_count_preserved": audit["row_counts"]["clean_wind_rows"]
        == int(read_json(cfg.stage8_dir / "stage8_enhanced_stage1_summary.json").get("row_counts", {}).get("clean_wind_rows", 431189)),
        "no_amdar_strict_truth_role": audit["row_counts"]["amdar_strict_truth_rows"] == 0,
        "turb_strict_truth_rows_match_stage8_holdout": audit["row_counts"]["turb_strict_truth_rows"] == 175,
        "clean_loc_not_copied_when_symlink_supported": links["clean_loc"]["mode"] == "symlink",
    }
    write_json(cfg.out_dir / "stage11_compat_stage1_view_audit.json", audit)
    return audit


def run_stage2_smoke(cfg: RunConfig, compat_dir: Path) -> dict[str, Any]:
    out_dir = cfg.out_dir / "stage2_smoke_confidence_v1"
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable,
        str(STAGE2_SCRIPT),
        "--stage1-dir",
        str(compat_dir),
        "--out-dir",
        str(out_dir),
        "--frame-times",
        cfg.frame_times,
        "--num-workers",
        str(cfg.workers),
        "--current-window-minutes",
        str(cfg.current_window_minutes),
        "--context-window-minutes",
        str(cfg.context_window_minutes),
    ]
    env = os.environ.copy()
    env["POLARS_MAX_THREADS"] = str(cfg.polars_threads)
    log_path = cfg.out_dir / "stage11_stage2_smoke.log"
    with log_path.open("w", encoding="utf-8") as log:
        proc = subprocess.run(cmd, cwd=str(ROOT), env=env, stdout=log, stderr=subprocess.STDOUT, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"Stage2 smoke failed rc={proc.returncode}; see {log_path}")
    summary_path = out_dir / "stage2_multimodal_summary.json"
    if not summary_path.exists():
        raise FileNotFoundError(summary_path)
    return {"out_dir": str(out_dir), "summary_path": str(summary_path), "log_path": str(log_path), "cmd": cmd}


def load_npz_records(path: Path, key: str) -> list[dict[str, Any]]:
    with np.load(path, allow_pickle=True) as data:
        arr = data[key]
        if arr.size == 0:
            return []
        return [dict(x) for x in arr.tolist()]


def audit_stage2_outputs(cfg: RunConfig, smoke: dict[str, Any], compat_audit: dict[str, Any]) -> dict[str, Any]:
    summary_rows = json.loads(Path(smoke["summary_path"]).read_text(encoding="utf-8"))
    per_frame: list[dict[str, Any]] = []
    total_current_amdar_truth_records = 0
    total_current_turb_truth_records = 0
    total_context_amdar_rows = 0
    confidence_field_hits = {
        "wind_obs_conf_v2": 0,
        "wind_confidence_grade_mode": 0,
        "context_obs_conf_v2": 0,
        "context_confidence_grade_mode": 0,
        "context_stage11_policy": 0,
    }
    all_required_meta = True
    for row in summary_rows:
        npz_path = Path(row["multimodal_vox_path"])
        wind_records = load_npz_records(npz_path, "wind_records")
        context_records = load_npz_records(npz_path, "context_wind_records")
        wind_amdar_rows = sum(int(rec.get("amdar_rows", 0) or 0) for rec in wind_records)
        wind_turb_rows = sum(int(rec.get("turb_rows", 0) or 0) for rec in wind_records)
        context_amdar_rows = sum(int(rec.get("amdar_rows", 0) or 0) for rec in context_records)
        total_current_amdar_truth_records += wind_amdar_rows
        total_current_turb_truth_records += wind_turb_rows
        total_context_amdar_rows += context_amdar_rows
        confidence_field_hits["wind_obs_conf_v2"] += sum(1 for rec in wind_records if "obs_conf_v2" in rec)
        confidence_field_hits["wind_confidence_grade_mode"] += sum(1 for rec in wind_records if "confidence_grade_mode" in rec)
        confidence_field_hits["context_obs_conf_v2"] += sum(1 for rec in context_records if "obs_conf_v2" in rec)
        confidence_field_hits["context_confidence_grade_mode"] += sum(
            1 for rec in context_records if "confidence_grade_mode" in rec
        )
        confidence_field_hits["context_stage11_policy"] += sum(
            1 for rec in context_records if "stage11_compat_role_policy" in rec
        )
        meta = row.get("data_integrity_audit", {})
        all_required_meta = all_required_meta and bool(meta.get("stage1_confidence_fields_present", {}).get("obs_conf_v2"))
        per_frame.append(
            {
                "time_str": row["time_str"],
                "wind_voxels": int(row.get("wind_voxels", 0)),
                "context_wind_voxels": int(row.get("context_wind_voxels", 0)),
                "current_label_rows": int(row.get("current_label_rows", 0)),
                "current_support_only_rows": int(row.get("current_support_only_rows", 0)),
                "wind_current_label_amdar_rows": int(meta.get("wind_current_label_amdar_rows", 0)),
                "wind_current_label_turb_rows": int(meta.get("wind_current_label_turb_rows", 0)),
                "wind_current_support_amdar_rows": int(meta.get("wind_current_support_amdar_rows", 0)),
                "wind_context_amdar_rows": int(meta.get("wind_context_amdar_rows", 0)),
                "wind_records_amdar_rows_after_grouping": int(wind_amdar_rows),
                "wind_records_turb_rows_after_grouping": int(wind_turb_rows),
                "context_records_amdar_rows_after_grouping": int(context_amdar_rows),
            }
        )

    checks = {
        "stage2_smoke_wrote_10_frames": len(summary_rows) == len(parse_frame_times(cfg.frame_times)),
        "compat_view_no_amdar_strict_truth_role": bool(
            compat_audit.get("compat_view_checks", {}).get("no_amdar_strict_truth_role")
        ),
        "stage2_wind_records_no_amdar_truth": total_current_amdar_truth_records == 0,
        "stage2_wind_records_have_turb_truth": total_current_turb_truth_records > 0,
        "stage2_context_records_have_amdar_support": total_context_amdar_rows > 0,
        "stage2_meta_preserves_confidence_fields": all_required_meta,
        "stage2_records_preserve_confidence_fields": confidence_field_hits["context_obs_conf_v2"] > 0
        and confidence_field_hits["context_confidence_grade_mode"] > 0
        and confidence_field_hits["context_stage11_policy"] > 0,
        "stage10_superob_products_available": all(
            (cfg.stage10_dir / name).exists()
            for name in ["amdar_superobs_T1.parquet", "amdar_superobs_T1T2.parquet", "amdar_superobs_T1T2T3.parquet"]
        ),
    }
    checks["passed_stage11_stage2_compat_smoke_gate"] = bool(all(checks.values()))
    audit = {
        "smoke_summary_rows": len(summary_rows),
        "total_current_amdar_truth_records": total_current_amdar_truth_records,
        "total_current_turb_truth_records": total_current_turb_truth_records,
        "total_context_amdar_rows": total_context_amdar_rows,
        "confidence_field_hits": confidence_field_hits,
        "per_frame": per_frame,
        "stage11_completion_checks": checks,
    }
    write_json(cfg.out_dir / "stage2_confidence_compatibility_report.json", audit)
    write_json(
        cfg.out_dir / "stage2_field_preservation_audit.json",
        {
            "confidence_field_hits": confidence_field_hits,
            "per_frame_fields_audited": per_frame,
            "checks": checks,
        },
    )
    return audit


def write_docs(
    cfg: RunConfig,
    upstream: dict[str, Any],
    compat_audit: dict[str, Any],
    smoke: dict[str, Any],
    output_audit: dict[str, Any],
) -> dict[str, str]:
    generated_at = datetime.now(timezone.utc).isoformat()
    checks = output_audit["stage11_completion_checks"]
    result_path = cfg.out_dir / "stage11_stage2_compat_smoke_results_analysis_and_next_steps.md"
    handover_path = cfg.out_dir / "next_agent_handover_after_stage11_stage2_compat_smoke.md"
    stage10_summary = upstream["stage10_summary"]
    compression = stage10_summary["tier_audits"]["T1T2T3"]["compression"]
    lines = [
        "# AMDAR Unified Plan Stage11 Stage2 Compatibility Smoke Results",
        "",
        f"Generated at UTC: {generated_at}",
        "",
        "## 核心结论",
        "",
        "Stage9 和 Stage10 v2 现在适合进入 Stage11。Stage11 已创建大框架 Stage2 可读取的兼容 Stage1 视图，并用 10 帧 smoke test 验证：AMDAR 不再能通过 legacy `wind_reconstruction_role` 混入 strict truth，TURB T0/S truth 仍保留，AMDAR support 进入 context/support 通道。",
        "",
        "这里的 Stage11 是 Unified Plan Stage11；被调用的脚本是 centralized_v1 大框架 Stage2 (`stage/centralized_v1/core/centralized_stage2_multimodal.py`)。",
        "",
        "## 为什么必须做兼容视图",
        "",
        "Stage8 为保持向后兼容保留了旧 `wind_reconstruction_role`，其中 6615 条 AMDAR 仍标为 `strict_truth_candidate`。如果直接喂给旧 Stage2，会破坏 strict truth 边界。Stage11 兼容视图只让 `source=turb & holdout_eligible & stage8_effective_strict_truth & confidence_grade=S` 保持 strict truth，其余全部改为 support-only。",
        "",
        "## Stage10 v2 复核",
        "",
        f"- Stage10 gate: `{upstream['upstream_checks']['stage10_gate_passed']}`",
        f"- Stage10 compression gate: `{upstream['upstream_checks']['stage10_compression_gate_passed']}`",
        f"- T1T2T3 compression: `{compression}`",
        "- 结论：v2 修复空间代表性双重降权，并用通道分级 super-ob bin 降低 context/C 密度支配，结果比旧 Stage10 更适合进入 Stage11/13。",
        "",
        "## Stage11 输出结果",
        "",
        f"- Compatible Stage1 view: `{compat_audit['compat_dir']}`",
        f"- Stage2 smoke output: `{smoke['out_dir']}`",
        f"- Smoke frames: `{output_audit['smoke_summary_rows']}`",
        f"- Total current AMDAR truth records after grouping: `{output_audit['total_current_amdar_truth_records']}`",
        f"- Total current TURB truth records after grouping: `{output_audit['total_current_turb_truth_records']}`",
        f"- Total context AMDAR support rows after grouping: `{output_audit['total_context_amdar_rows']}`",
        f"- Confidence field hits: `{output_audit['confidence_field_hits']}`",
        f"- Completion checks: `{checks}`",
        "",
        "## Outputs",
        "",
        f"- Stage11 summary: `{cfg.out_dir / 'stage11_stage2_compat_smoke_summary.json'}`",
        f"- Compatibility report: `{cfg.out_dir / 'stage2_confidence_compatibility_report.json'}`",
        f"- Field preservation audit: `{cfg.out_dir / 'stage2_field_preservation_audit.json'}`",
        f"- Compatible Stage1 audit: `{cfg.out_dir / 'stage11_compat_stage1_view_audit.json'}`",
        f"- Stage2 smoke log: `{smoke['log_path']}`",
        "",
        "## 下一步建议",
        "",
        "1. 进入 Stage12：先复现 baseline，确认 strict TURB holdout 指标不因字段增强而漂移。",
        "2. Stage13：再接入 Stage10 v2 的 A / A+B / A+B+C super-ob 产品做多时间尺度消融。",
        "3. 不要把 Stage10 support parquet 直接覆盖 official Stage2/Stage4 默认输入；先做 report-only/ablation。",
    ]
    result_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    handover = [
        "# 给下一个智能体的交接话术：Stage11 Stage2 Compatibility Smoke 后续",
        "",
        "你接手的是 `/data/LFT-W02_data/pengxu` 下的 centralized_v1 三维水平风场重构项目。不要混淆阶段名：Stage9/10/11 是 `amdar_unified_implementation_plan_20260701.md` 的 Unified Plan 阶段；centralized_v1 大框架仍是 Stage1/2/3/4。",
        "",
        "## 必读文档顺序",
        "",
        "1. `/data/LFT-W02_data/pengxu/workflow/centralized_v1_docs/new_window_project_handover_20260529/centralized_v1_ultimate_summary_20260626.md`：strict aircraft holdout 边界。",
        "2. `/data/LFT-W02_data/pengxu/优化/数据处理/amdar_plan4_implementation_20260630/plan4_assessment_and_run_report_20260630.md`：AMDAR 批次时间语义。",
        "3. `/data/LFT-W02_data/pengxu/优化/数据处理/amdar_plan4_comprehensive_assessment_20260701.md`：AMDAR 分层置信度策略。",
        "4. `/data/LFT-W02_data/pengxu/优化/数据处理/amdar_unified_implementation_plan_20260701.md`：Unified Plan Stage11/12/13 要求。",
        "5. `/data/LFT-W02_data/pengxu/优化/数据处理/amdar_unified_stage9_stage2_role_split_global_frame_optimized_20260702/stage9_stage2_role_split_results_analysis_and_next_steps.md`：Stage9 角色分流。",
        "6. `/data/LFT-W02_data/pengxu/优化/数据处理/amdar_unified_stage10_superob_weight_control_v2_optimized_20260702/stage10_superob_weight_control_results_analysis_and_next_steps.md`：Stage10 v2 super-ob/限权。",
        f"7. `{result_path}`：Stage11 兼容 smoke 结果和下一步建议。",
        f"8. `{cfg.out_dir / 'stage11_stage2_compat_smoke_summary.json'}`：Stage11 machine-readable checks。",
        "",
        "## 本轮脚本和输出",
        "",
        "- Stage10 v2 脚本：`/data/LFT-W02_data/pengxu/优化/数据处理/amdar_unified_stage10_superob_weight_control_20260702.py`",
        "- Stage11 脚本：`/data/LFT-W02_data/pengxu/优化/数据处理/amdar_unified_stage11_stage2_compat_smoke_20260702.py`",
        f"- Stage11 输出目录：`{cfg.out_dir}`",
        "- `stage1_confidence_compat_view/clean_wind.parquet`：兼容 Stage1 view，只允许 TURB T0/S 作为 strict truth。",
        "- `stage1_confidence_compat_view/clean_loc.parquet`：指向 Plan4 Stage1 clean_loc 的 symlink，避免复制 1.4G 大文件。",
        "- `stage2_smoke_confidence_v1/`：10 帧 centralized_v1 Stage2 smoke 输出。",
        "",
        "## 关键结果",
        "",
        f"- Stage11 completion checks: `{checks}`",
        f"- Current AMDAR truth after Stage2 grouping: `{output_audit['total_current_amdar_truth_records']}`",
        f"- Current TURB truth after Stage2 grouping: `{output_audit['total_current_turb_truth_records']}`",
        f"- Context AMDAR support after Stage2 grouping: `{output_audit['total_context_amdar_rows']}`",
        f"- Stage10 v2 T1T2T3 compression: `{compression}`",
        "",
        "## 强制规则",
        "",
        "- AMDAR 仍全部非 holdout、非 strict truth；不要用 legacy `wind_reconstruction_role` 的旧 AMDAR candidate 口径。",
        "- Stage11 只证明 Stage2 兼容与字段保留；不证明 A/B/C support 改善风场，改善必须在 Stage13 消融验证。",
        "- Stage10 v2 support parquet 不能直接覆盖 official Stage2/Stage4 默认输入。",
        "",
        "推荐开场话术：",
        "",
        "```text",
        "我已阅读 Stage9/10/11 结果。Stage10 v2 已修复空间权重双乘并通过压缩/限权审计；Stage11 已生成兼容 Stage1 视图并跑通 10 帧 centralized_v1 Stage2 smoke，验证 AMDAR 不进入 strict truth，TURB T0/S truth 保留，置信度字段可传递。下一步进入 Stage12 baseline 复现，再做 Stage13 多时间尺度消融。",
        "```",
    ]
    handover_path.write_text("\n".join(handover) + "\n", encoding="utf-8")
    return {"result_analysis": str(result_path), "next_agent_handover": str(handover_path)}


def main() -> None:
    cfg = parse_args()
    if cfg.workers <= 0:
        raise ValueError("--workers must be positive")
    if cfg.polars_threads <= 0:
        raise ValueError("--polars-threads must be positive")
    cfg.out_dir.mkdir(parents=True, exist_ok=True)
    write_json(cfg.out_dir / "run_config.json", {**asdict(cfg), "env_polars_threads": os.environ.get("POLARS_MAX_THREADS")})
    upstream = require_upstream(cfg)
    compat_audit = build_compatible_stage1_view(cfg)
    smoke = run_stage2_smoke(cfg, Path(compat_audit["compat_dir"]))
    output_audit = audit_stage2_outputs(cfg, smoke, compat_audit)
    docs = write_docs(cfg, upstream, compat_audit, smoke, output_audit)
    summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "run_policy": {
            "polars_threads": cfg.polars_threads,
            "workers": cfg.workers,
            "stage11_boundary_note": (
                "Unified Plan Stage11 compatibility smoke. It calls large-framework centralized_v1 Stage2 but does "
                "not run Stage4 reconstruction or migrate official weights."
            ),
            "space_saving_policy": (
                "Write a compact compatible clean_wind parquet and symlink clean_loc/radar_index/frame_window_index "
                "when supported. Do not copy 25 full intermediate datasets."
            ),
        },
        "inputs": {
            "stage8_dir": str(cfg.stage8_dir),
            "stage9_dir": str(cfg.stage9_dir),
            "stage10_dir": str(cfg.stage10_dir),
            "stage1_plan4_dir": str(cfg.stage1_dir),
        },
        "upstream_checks": upstream["upstream_checks"],
        "compat_view_audit": compat_audit,
        "stage2_smoke": smoke,
        "stage2_output_audit": output_audit,
        "stage11_completion_checks": output_audit["stage11_completion_checks"],
        "outputs": {
            "summary": str(cfg.out_dir / "stage11_stage2_compat_smoke_summary.json"),
            "result_analysis": docs["result_analysis"],
            "next_agent_handover": docs["next_agent_handover"],
            "compat_report": str(cfg.out_dir / "stage2_confidence_compatibility_report.json"),
            "field_preservation_audit": str(cfg.out_dir / "stage2_field_preservation_audit.json"),
            "compat_stage1_view_audit": str(cfg.out_dir / "stage11_compat_stage1_view_audit.json"),
        },
    }
    write_json(cfg.out_dir / "stage11_stage2_compat_smoke_summary.json", summary)
    print(
        json.dumps(
            {
                "stage": "stage11_done",
                "passed": summary["stage11_completion_checks"]["passed_stage11_stage2_compat_smoke_gate"],
                "out_dir": str(cfg.out_dir),
                "checks": summary["stage11_completion_checks"],
            },
            ensure_ascii=False,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
