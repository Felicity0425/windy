#!/usr/bin/env bash

# ============================================================
# Stage-3 / Stage-4 总控脚本
# ============================================================
#
# 设计目标：
# 1. 把“选帧 -> 跑 Stage 3 -> 跑 Stage 4 -> validate -> export -> 汇总日志”
#    这一整套流程收敛成一个脚本，避免手工敲很多命令。
# 2. 兼容三类常见调试场景：
#    - first3：最前面 3 帧链路测试
#    - offset：跳过前若干帧后连续取 3 帧
#    - topwind_auto / indices：直接抽高风帧做重构质量验证
#    - full：全量运行，用于生成后续训练所需的完整数据
# 3. 每次运行都生成完整日志，并把当前 run 的 Stage-4 输出单独收集到
#    独立目录，避免 export 混入历史帧。
#
# 服务器默认路径按你的实际环境设置：
#   BASE_DIR=/data/LFT-W02_data/pengxu
#   STAGE_DIR=/data/LFT-W02_data/pengxu/stage
#   LOG_DIR=/data/LFT-W02_data/pengxu/stage/logs
#
# 使用方式示例：
#
# 1) 最前面 3 帧链路测试
#    RUN_MODE=first3 bash /data/LFT-W02_data/pengxu/stage/run_stage34_workflow.sh
#
# 2) 跳过前 300 帧，再跑 3 帧
#    RUN_MODE=offset FRAME_OFFSET=300 MAX_FRAMES=3 \
#    bash /data/LFT-W02_data/pengxu/stage/run_stage34_workflow.sh
#
# 3) 自动挑 top-N 高风帧，推荐
#    RUN_MODE=topwind_auto TOPWIND_COUNT=3 \
#    bash /data/LFT-W02_data/pengxu/stage/run_stage34_workflow.sh
#
# 4) 手工精确指定 Stage-2 下标
#    RUN_MODE=indices FRAME_INDICES=3769,3338,3425 \
#    bash /data/LFT-W02_data/pengxu/stage/run_stage34_workflow.sh
#
# 可选环境变量：
#   PYTHON_BIN            Python 命令，默认 python
#   RUN_MODE              first3 / offset / topwind_auto / indices / full
#   MAX_FRAMES            连续小批量帧数，默认 3
#   FRAME_OFFSET          offset 模式的起始偏移，默认 300
#   FRAME_INDICES         indices 模式的精确下标列表，例如 3769,3338,3425
#   TOPWIND_COUNT         自动挑 topwind 时抽取几帧，默认 3
#   RUN_LABEL_OVERRIDE    自定义日志名后缀
#   EXPORT_AFTER_RUN      是否执行 export，默认 1
#   RUN_VALIDATE          是否执行 validator，默认 1
#   PROGRESS_EVERY        export 时进度间隔，默认 1
#
# ============================================================

set -euo pipefail

BASE_DIR="${BASE_DIR:-/data/LFT-W02_data/pengxu}"
STAGE_DIR="${STAGE_DIR:-$BASE_DIR/stage}"
LOG_ROOT_DIR="${LOG_ROOT_DIR:-$STAGE_DIR/logs}"
LOG_DIR="${LOG_DIR:-$LOG_ROOT_DIR}"
PYTHON_BIN="${PYTHON_BIN:-python}"
LATEST_LOG_DIR="${LATEST_LOG_DIR:-$LOG_ROOT_DIR}"

STAGE2_OUTPUT_DIR="${STAGE2_OUTPUT_DIR:-$BASE_DIR/stage2_output}"
STAGE3_OUTPUT_DIR="${STAGE3_OUTPUT_DIR:-$BASE_DIR/stage3_output}"
STAGE4_OUTPUT_DIR="${STAGE4_OUTPUT_DIR:-$BASE_DIR/stage4_output}"

RUN_MODE="${RUN_MODE:-topwind_auto}"
MAX_FRAMES="${MAX_FRAMES:-3}"
FRAME_OFFSET="${FRAME_OFFSET:-300}"
FRAME_INDICES="${FRAME_INDICES:-}"
TOPWIND_COUNT="${TOPWIND_COUNT:-3}"
RUN_LABEL_OVERRIDE="${RUN_LABEL_OVERRIDE:-}"
EXPORT_AFTER_RUN="${EXPORT_AFTER_RUN:-1}"
RUN_VALIDATE="${RUN_VALIDATE:-1}"
PROGRESS_EVERY="${PROGRESS_EVERY:-1}"

# 每次 run 的 Stage-4 子集复制到独立目录，确保 export 不混入历史帧。
STAGE4_RUN_ROOT="${STAGE4_RUN_ROOT:-$BASE_DIR/stage4_output_runs}"
EXPORT_DST="${EXPORT_DST:-$BASE_DIR/dataset_output_stage4_clean}"

mkdir -p "$LOG_ROOT_DIR" "$STAGE4_RUN_ROOT"

log() {
  printf '[workflow] %s\n' "$*"
}

warn() {
  printf '[workflow][WARN] %s\n' "$*" >&2
}

die() {
  printf '[workflow][ERROR] %s\n' "$*" >&2
  exit 1
}

require_file() {
  local path="$1"
  [[ -f "$path" ]] || die "缺少文件: $path"
}

# [改动说明] 自动寻找 validator 脚本，适配服务器实际路径不一致的情况。
resolve_validate_py() {
  if [[ -n "${VALIDATE_PY:-}" && -f "${VALIDATE_PY:-}" ]]; then
    printf '%s\n' "$VALIDATE_PY"
    return
  fi
  local found
  found="$(find "$BASE_DIR" -name 'validate_pipeline_constracts.py' 2>/dev/null | head -n 1 || true)"
  if [[ -n "$found" ]]; then
    printf '%s\n' "$found"
    return
  fi
  printf '%s\n' "$STAGE_DIR/validate_pipeline_constracts.py"
}

# [改动说明] 自动寻找 export_stage4_dataset.py，适配服务器路径不一致。
resolve_export_py() {
  if [[ -n "${EXPORT_PY:-}" && -f "${EXPORT_PY:-}" ]]; then
    printf '%s\n' "$EXPORT_PY"
    return
  fi
  local found
  found="$(find "$BASE_DIR" -name 'export_stage4_dataset.py' 2>/dev/null | head -n 1 || true)"
  if [[ -n "$found" ]]; then
    printf '%s\n' "$found"
    return
  fi
  # 本地仓库没有这个脚本时，返回空字符串，由主流程决定是否跳过 export。
  printf '%s\n' ""
}

resolve_stage4_readiness_py() {
  if [[ -n "${STAGE4_READINESS_PY:-}" && -f "${STAGE4_READINESS_PY:-}" ]]; then
    printf '%s\n' "$STAGE4_READINESS_PY"
    return
  fi
  local found
  found="$(find "$BASE_DIR" -name 'report_stage4_training_readiness.py' 2>/dev/null | head -n 1 || true)"
  if [[ -n "$found" ]]; then
    printf '%s\n' "$found"
    return
  fi
  printf '%s\n' "$STAGE_DIR/report_stage4_training_readiness.py"
}

generate_stage2_topwind_log() {
  local out_log="$LOG_DIR/stage2_topwind.log"
  export STAGE2_SUMMARY_PATH="$STAGE2_OUTPUT_DIR/stage2_summary.json"
  require_file "$STAGE2_SUMMARY_PATH"
  "$PYTHON_BIN" - <<'PY' > "$out_log" 2>&1
import json
import os
from pathlib import Path

p = Path(os.environ["STAGE2_SUMMARY_PATH"])
data = json.loads(p.read_text(encoding="utf-8"))
pairs = sorted(enumerate(data), key=lambda x: x[1].get("wind_voxels", 0), reverse=True)
for idx, item in pairs[:30]:
    print(
        "idx=", idx,
        "time=", item.get("time_str"),
        "wind_voxels=", item.get("wind_voxels"),
        "motion_voxels=", item.get("motion_voxels"),
        "amdar_voxels=", item.get("amdar_voxels"),
        "turb_voxels=", item.get("turb_voxels"),
    )
PY
  log "已生成高风帧索引日志: $out_log"
}

pick_topwind_indices() {
  export STAGE2_SUMMARY_PATH="$STAGE2_OUTPUT_DIR/stage2_summary.json"
  export TOPWIND_COUNT
  "$PYTHON_BIN" - <<'PY'
import json
import os
from pathlib import Path

p = Path(os.environ["STAGE2_SUMMARY_PATH"])
count = max(1, int(os.environ["TOPWIND_COUNT"]))
data = json.loads(p.read_text(encoding="utf-8"))
pairs = sorted(enumerate(data), key=lambda x: x[1].get("wind_voxels", 0), reverse=True)
indices = [str(idx) for idx, _ in pairs[:count]]
print(",".join(indices))
PY
}

# [改动说明] 统一 first3 / offset / topwind_auto / indices / full 五种运行模式。
select_run_mode() {
  unset WIND_FRAME_INDICES || true
  unset WIND_FRAME_OFFSET || true
  unset WIND_MAX_FRAMES || true

  local mode_dir="${RUN_MODE}"
  if [[ -n "$RUN_LABEL_OVERRIDE" ]]; then
    mode_dir="${RUN_MODE}_${RUN_LABEL_OVERRIDE}"
  fi
  LOG_DIR="$LOG_ROOT_DIR/$mode_dir"
  export LOG_DIR
  mkdir -p "$LOG_DIR"

  case "$RUN_MODE" in
    first3)
      export WIND_FRAME_OFFSET=0
      export WIND_MAX_FRAMES="$MAX_FRAMES"
      RUN_LABEL="${RUN_LABEL_OVERRIDE:-3frames_new}"
      ;;
    offset)
      export WIND_FRAME_OFFSET="$FRAME_OFFSET"
      export WIND_MAX_FRAMES="$MAX_FRAMES"
      RUN_LABEL="${RUN_LABEL_OVERRIDE:-offset${FRAME_OFFSET}}"
      ;;
    indices)
      [[ -n "$FRAME_INDICES" ]] || die "RUN_MODE=indices 时必须提供 FRAME_INDICES"
      export WIND_FRAME_INDICES="$FRAME_INDICES"
      RUN_LABEL="${RUN_LABEL_OVERRIDE:-indices}"
      ;;
    topwind_auto)
      generate_stage2_topwind_log
      FRAME_INDICES="$(pick_topwind_indices)"
      [[ -n "$FRAME_INDICES" ]] || die "自动挑选高风帧失败，FRAME_INDICES 为空"
      export WIND_FRAME_INDICES="$FRAME_INDICES"
      RUN_LABEL="${RUN_LABEL_OVERRIDE:-topwind}"
      ;;
    full)
      RUN_LABEL="${RUN_LABEL_OVERRIDE:-full}"
      ;;
    *)
      die "未知 RUN_MODE=$RUN_MODE，可选: first3 / offset / indices / topwind_auto / full"
      ;;
  esac

  export RUN_LABEL
  log "运行模式: $RUN_MODE"
  log "运行标签: $RUN_LABEL"
  log "日志目录: $LOG_DIR"
  if [[ -n "${WIND_FRAME_INDICES:-}" ]]; then
    log "精确抽帧下标: ${WIND_FRAME_INDICES}"
  else
        log "连续抽帧: offset=${WIND_FRAME_OFFSET:-0}, max_frames=${WIND_MAX_FRAMES:-all}"
  fi
}

write_run_info() {
  local run_info="$LOG_DIR/run_info.txt"
  local latest_info="$LATEST_LOG_DIR/run_info_latest.txt"
  {
    echo "run_mode=$RUN_MODE"
    echo "run_label=$RUN_LABEL"
    echo "log_dir=$LOG_DIR"
    echo "stage4_run_dir=${STAGE4_RUN_ROOT}/${RUN_LABEL}"
    echo "frame_indices=${WIND_FRAME_INDICES:-}"
    echo "frame_offset=${WIND_FRAME_OFFSET:-}"
    echo "max_frames=${WIND_MAX_FRAMES:-}"
  } > "$run_info"
  cp "$run_info" "$latest_info"
}

run_stage_scripts() {
  local stage3_log="$LOG_DIR/stage3_${RUN_LABEL}.log"
  local stage4_log="$LOG_DIR/stage4_${RUN_LABEL}.log"

  require_file "$STAGE_DIR/stage3_agents.py"
  require_file "$STAGE_DIR/stage4_pack.py"

  log "开始运行 Stage-3 ..."
  "$PYTHON_BIN" "$STAGE_DIR/stage3_agents.py" > "$stage3_log" 2>&1
  log "Stage-3 日志: $stage3_log"

  log "开始运行 Stage-4 ..."
  "$PYTHON_BIN" "$STAGE_DIR/stage4_pack.py" > "$stage4_log" 2>&1
  log "Stage-4 日志: $stage4_log"
}

run_validate() {
  local validate_log_run="$LOG_DIR/validate_pipeline_constracts_${RUN_LABEL}.log"
  local validate_log_latest="$LOG_DIR/validate_pipeline_constracts.log"
  local validate_py
  validate_py="$(resolve_validate_py)"

  if [[ "$RUN_VALIDATE" != "1" ]]; then
    warn "按配置跳过 validate"
    return
  fi

  if [[ ! -f "$validate_py" ]]; then
    warn "未找到 validate_pipeline_constracts.py，跳过 validate"
    printf '[contract-check] SKIP\n - missing validator script\n' > "$validate_log_run"
  else
    "$PYTHON_BIN" "$validate_py" > "$validate_log_run" 2>&1 || true
  fi
  cp "$validate_log_run" "$validate_log_latest"
  log "Validate 日志: $validate_log_run"
}

write_stage3_summary_logs() {
  local run_log="$LOG_DIR/stage3wind_${RUN_LABEL}.log"
  local latest_log="$LOG_DIR/stage3wind.log"
  export STAGE3_SUMMARY_PATH="$STAGE3_OUTPUT_DIR/stage3_summary.json"
  require_file "$STAGE3_SUMMARY_PATH"
  "$PYTHON_BIN" - <<'PY' > "$run_log" 2>&1
import json
import os
from pathlib import Path

p = Path(os.environ["STAGE3_SUMMARY_PATH"])
data = json.loads(p.read_text(encoding="utf-8"))
print("frames =", len(data))
for item in data:
    print(
        "idx=", item.get("source_index"),
        "time=", item["time_str"],
        "valid_wind_capable=", item.get("valid_wind_capable_flights"),
        "wind_edges=", item.get("flight_ff_wind_edges"),
        "comm_agents=", item.get("flight_comm_allowed_agents"),
        "ff_edges=", item.get("flight_ff_allowed_edges"),
        "direct=", item.get("wind_support_direct_hits"),
        "near=", item.get("wind_support_near_hits"),
        "geo=", item.get("wind_support_geo_hits"),
        "soft=", item.get("wind_support_soft_hits"),
        "score_p50=", item.get("wind_support_score_p50"),
        "score_p90=", item.get("wind_support_score_p90"),
    )
PY
  cp "$run_log" "$latest_log"
  log "Stage-3 summary 日志: $run_log"
}

write_stage4_summary_logs() {
  local run_log="$LOG_DIR/stage4summary_${RUN_LABEL}.log"
  local latest_log="$LOG_DIR/stage4summary.log"
  export STAGE4_SUMMARY_PATH="$STAGE4_OUTPUT_DIR/stage4_summary.json"
  require_file "$STAGE4_SUMMARY_PATH"
  "$PYTHON_BIN" - <<'PY' > "$run_log" 2>&1
import json
import os
from pathlib import Path

p = Path(os.environ["STAGE4_SUMMARY_PATH"])
data = json.loads(p.read_text(encoding="utf-8"))
print("frames =", len(data))
for item in data:
    print(
        "idx=", item.get("source_index"),
        "time=", item["time_str"],
        "triggered=", item.get("recon_triggered"),
        "reason=", item.get("recon_trigger_reason"),
        "seed=", item.get("recon_seed_strength"),
        "seed_vox=", item.get("wind_seed_voxels"),
        "support_vox=", item.get("support_voxels"),
        "support_fill=", item.get("support_fill_voxels"),
        "support_fill_kept=", item.get("support_fill_kept_voxels"),
        "wind_conflict_keep=", item.get("wind_conflict_keep_voxels"),
        "direct_agree=", item.get("direct_agreement_mean"),
        "pruned=", item.get("recon_pruned_voxels"),
        "support_domain=", item.get("recon_support_domain_voxels"),
        "domain=", item.get("recon_domain_voxels"),
        "recon_mean=", item.get("recon_conf_mean"),
        "conf_p50=", item.get("recon_conf_p50"),
        "conf_p90=", item.get("recon_conf_p90"),
        "coverage=", item.get("recon_coverage_ratio"),
        "forecast_cov=", item.get("forecast_coverage_ratio"),
        "outlier_drop=", item.get("outlier_drop_voxels"),
        "wind_edges=", item.get("flight_ff_wind_edges"),
    )
PY
  cp "$run_log" "$latest_log"
  log "Stage-4 summary 日志: $run_log"
}

collect_current_stage4_run() {
  # 这里把“当前这次 run 的 Stage-4 输出子集”拷贝到独立目录，
  # 避免 export 时混入历史 run 留在 stage4_output 目录里的旧帧。
  export STAGE4_OUTPUT_DIR
  export STAGE4_RUN_DIR="$STAGE4_RUN_ROOT/$RUN_LABEL"
  mkdir -p "$STAGE4_RUN_DIR"
  "$PYTHON_BIN" - <<'PY'
import json
import os
import shutil
from pathlib import Path

src = Path(os.environ["STAGE4_OUTPUT_DIR"])
dst = Path(os.environ["STAGE4_RUN_DIR"])
summary_path = src / "stage4_summary.json"
data = json.loads(summary_path.read_text(encoding="utf-8"))

dst.mkdir(parents=True, exist_ok=True)
for old in dst.glob("frame_*.npz"):
    old.unlink()
out_summary = dst / "stage4_summary.json"
if out_summary.exists():
    out_summary.unlink()

for item in data:
    name = item["filename"]
    shutil.copy2(src / name, dst / name)

out_summary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"copied_frames={len(data)}")
print(f"run_stage4_dir={dst}")
PY
  log "本次 Stage-4 子集目录: $STAGE4_RUN_DIR"
}

run_export() {
  local export_py
  local run_log="$LOG_DIR/export_stage4_${RUN_LABEL}.log"
  local latest_log="$LOG_DIR/export_stage4"
  local help_text=""

  if [[ "$EXPORT_AFTER_RUN" != "1" ]]; then
    warn "按配置跳过 export"
    return
  fi

  export_py="$(resolve_export_py)"
  if [[ -z "$export_py" || ! -f "$export_py" ]]; then
    warn "未找到 export_stage4_dataset.py，跳过 export"
    printf '[export] SKIP\nmissing export_stage4_dataset.py\n' > "$run_log"
    cp "$run_log" "$latest_log"
    return
  fi

  help_text="$("$PYTHON_BIN" "$export_py" -h 2>&1 || true)"
  if printf '%s' "$help_text" | grep -q -- '--progress_every'; then
    "$PYTHON_BIN" "$export_py" \
      --src "$STAGE4_RUN_DIR" \
      --dst "$EXPORT_DST" \
      --progress_every "$PROGRESS_EVERY" \
      > "$run_log" 2>&1
  else
    "$PYTHON_BIN" "$export_py" \
      --src "$STAGE4_RUN_DIR" \
      --dst "$EXPORT_DST" \
      > "$run_log" 2>&1
  fi
  cp "$run_log" "$latest_log"
  log "Export 日志: $run_log"
}

# [改动说明] 自动生成 Stage-4 训练可用性统计报告。
run_stage4_readiness_report() {
  local report_py
  local run_log="$LOG_DIR/stage4stats_${RUN_LABEL}.log"
  local latest_log="$LOG_DIR/stage4stats.log"
  local out_json="$LOG_DIR/stage4stats_${RUN_LABEL}.json"
  local export_json="$EXPORT_DST/stage4_clean_report.json"
  report_py="$(resolve_stage4_readiness_py)"

  if [[ ! -f "$report_py" ]]; then
    warn "未找到 report_stage4_training_readiness.py，跳过全量统计报告"
    printf '[readiness] SKIP\nmissing report_stage4_training_readiness.py\n' > "$run_log"
    cp "$run_log" "$latest_log"
    return
  fi

  if [[ -f "$export_json" ]]; then
    "$PYTHON_BIN" "$report_py" \
      --summary "$STAGE4_OUTPUT_DIR/stage4_summary.json" \
      --export-report "$export_json" \
      --out-json "$out_json" \
      > "$run_log" 2>&1
  else
    "$PYTHON_BIN" "$report_py" \
      --summary "$STAGE4_OUTPUT_DIR/stage4_summary.json" \
      --out-json "$out_json" \
      > "$run_log" 2>&1
  fi
  cp "$run_log" "$latest_log"
  log "Stage-4 全量统计报告: $run_log"
}

run_stage4_sparse_metrics_report() {
  local report_py="$STAGE_DIR/report_stage4_sparse_metrics.py"
  local run_log="$LOG_DIR/stage4_sparse_metrics_${RUN_LABEL}.log"
  local latest_log="$LOG_DIR/stage4_sparse_metrics.log"
  local out_json="$LOG_DIR/stage4_sparse_metrics_${RUN_LABEL}.json"

  if [[ ! -f "$report_py" ]]; then
    warn "未找到 report_stage4_sparse_metrics.py，跳过稀疏监督指标统计"
    return
  fi

  "$PYTHON_BIN" "$report_py" \
    --stage2-summary "$STAGE2_OUTPUT_DIR/stage2_summary.json" \
    --stage4-summary "$STAGE4_OUTPUT_DIR/stage4_summary.json" \
    --stage4-dir "$STAGE4_OUTPUT_DIR" \
    --out-json "$out_json" \
    > "$run_log" 2>&1
  cp "$run_log" "$latest_log"
  log "Stage-4 稀疏监督指标报告: $run_log"
}

run_stage4_outlier_report() {
  local report_py="$STAGE_DIR/report_stage4_outlier_report.py"
  local run_log="$LOG_DIR/stage4_outliers_${RUN_LABEL}.log"
  local latest_log="$LOG_DIR/stage4_outliers.log"
  local out_json="$LOG_DIR/stage4_outliers_${RUN_LABEL}.json"

  if [[ ! -f "$report_py" ]]; then
    warn "未找到 report_stage4_outlier_report.py，跳过 outlier 定位报告"
    printf '[outlier-report] SKIP\nmissing report_stage4_outlier_report.py\n' > "$run_log"
    cp "$run_log" "$latest_log"
    return
  fi

  "$PYTHON_BIN" "$report_py" \
    --stage2-summary "$STAGE2_OUTPUT_DIR/stage2_summary.json" \
    --stage4-summary "$STAGE4_OUTPUT_DIR/stage4_summary.json" \
    --stage4-dir "$STAGE4_OUTPUT_DIR" \
    --top-k 20 \
    --out-json "$out_json" \
    > "$run_log" 2>&1
  cp "$run_log" "$latest_log"
  log "Stage-4 outlier 定位报告: $run_log"
}

check_stage4_npz_fields_current_run() {
  local run_log="$LOG_DIR/stage4_npz_fields_${RUN_LABEL}.log"
  local latest_log="$LOG_DIR/stage4_npz_fields.log"
  export STAGE4_RUN_DIR
  "$PYTHON_BIN" - <<'PY' > "$run_log" 2>&1
import numpy as np
import os
from pathlib import Path

p = Path(os.environ["STAGE4_RUN_DIR"])
files = sorted(p.glob("frame_*.npz"))
for fp in files[:3]:
    with np.load(fp, allow_pickle=True) as npz:
        print(fp.name)
        for key in [
            "comm_joint_idx",
            "comm_wind_idx",
            "comm_motion_idx",
            "comm_uncertainty_idx",
            "pinn_divergence_3d",
            "pinn_smoothness_3d",
            "physics_weight_3d",
            "direct_agreement_3d",
            "direct_source_count_3d",
            "diffusion_condition_4d",
            "pinn_prior_u_3d",
            "diffusion_prior_u_3d",
            "forecast_u_3d",
            "forecast_confidence_3d",
            "hazard_shear_3d",
            "hazard_turbulence_3d",
            "hazard_alert_mask_3d",
        ]:
            print(key, key in npz.files, npz[key].shape if key in npz.files else None)
        print()
PY
  cp "$run_log" "$latest_log"
  log "Stage-4 当前 run 的 npz 字段检查: $run_log"
}

# [改动说明] 汇总关键日志，便于一次性查看 Stage-3 / Stage-4 / validate / export 结果。
build_key_log() {
  local run_log="$LOG_DIR/key_${RUN_LABEL}.log"
  local latest_log="$LOG_DIR/key.log"
  local stage3_log="$LOG_DIR/stage3_${RUN_LABEL}.log"
  local stage4_log="$LOG_DIR/stage4_${RUN_LABEL}.log"
  local stage3_summary_log="$LOG_DIR/stage3wind_${RUN_LABEL}.log"
  local stage4_summary_log="$LOG_DIR/stage4summary_${RUN_LABEL}.log"
  local stage4_stats_log="$LOG_DIR/stage4stats_${RUN_LABEL}.log"
  local stage4_sparse_metrics_log="$LOG_DIR/stage4_sparse_metrics_${RUN_LABEL}.log"
  local stage4_outliers_log="$LOG_DIR/stage4_outliers_${RUN_LABEL}.log"
  local validate_log="$LOG_DIR/validate_pipeline_constracts_${RUN_LABEL}.log"
  local export_log="$LOG_DIR/export_stage4_${RUN_LABEL}.log"

  {
    echo "=== Stage3 wind ==="
    grep "\[Stage-3\]\[wind\]" "$stage3_log" || true
    echo
    echo "=== Stage4 diag/frame ==="
    grep -E "\[Stage-4\]\[(diag|frame)\]" "$stage4_log" || true
    echo
    echo "=== Stage3 summary ==="
    tail -n 120 "$stage3_summary_log" || true
    echo
    echo "=== Stage4 summary ==="
    tail -n 120 "$stage4_summary_log" || true
    echo
    echo "=== Validate ==="
    tail -n 120 "$validate_log" || true
    echo
    echo "=== Stage4 readiness ==="
    tail -n 120 "$stage4_stats_log" || true
    echo
    echo "=== Stage4 sparse metrics ==="
    tail -n 120 "$stage4_sparse_metrics_log" || true
    echo
    echo "=== Stage4 outliers ==="
    tail -n 120 "$stage4_outliers_log" || true
    echo
    echo "=== Export ==="
    tail -n 120 "$export_log" || true
  } > "$run_log" 2>&1

  cp "$run_log" "$latest_log"
  log "汇总 key 日志: $run_log"
}

main() {
  require_file "$STAGE2_OUTPUT_DIR/stage2_summary.json"
  select_run_mode
  write_run_info
  run_stage_scripts
  write_stage3_summary_logs
  write_stage4_summary_logs
  run_validate
  collect_current_stage4_run
  run_export
  run_stage4_readiness_report
  run_stage4_sparse_metrics_report
  run_stage4_outlier_report
  check_stage4_npz_fields_current_run
  build_key_log

  log "流程完成"
  log "请重点查看:"
  log "  $LOG_DIR/stage3_${RUN_LABEL}.log"
  log "  $LOG_DIR/stage4_${RUN_LABEL}.log"
  log "  $LOG_DIR/stage3wind_${RUN_LABEL}.log"
  log "  $LOG_DIR/stage4summary_${RUN_LABEL}.log"
  log "  $LOG_DIR/stage4stats_${RUN_LABEL}.log"
  log "  $LOG_DIR/stage4_sparse_metrics_${RUN_LABEL}.log"
  log "  $LOG_DIR/stage4_outliers_${RUN_LABEL}.log"
  log "  $LOG_DIR/key_${RUN_LABEL}.log"
}

main "$@"
