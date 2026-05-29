#!/usr/bin/env bash

# ============================================================
# Stage-3 / Stage-4 V2 总控脚本
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
# 3. 支持按阶段拆开试跑，便于把“Stage-3 / Stage-4 / validate / reports / export”
#    分开验证，减少一次性全跑时的排查成本。
# 4. 每次运行都生成完整日志，并把当前 run 的 Stage-4 输出单独收集到
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
#    RUN_MODE=first3 bash /data/LFT-W02_data/pengxu/stage/run_stage34_workflow_v2.sh
#
# 2) 跳过前 300 帧，再跑 3 帧
#    RUN_MODE=offset FRAME_OFFSET=300 MAX_FRAMES=3 \
#    bash /data/LFT-W02_data/pengxu/stage/run_stage34_workflow_v2.sh
#
# 3) 自动挑 top-N 高风帧，推荐
#    RUN_MODE=topwind_auto TOPWIND_COUNT=3 \
#    bash /data/LFT-W02_data/pengxu/stage/run_stage34_workflow_v2.sh
#
# 4) 手工精确指定 Stage-2 下标
#    RUN_MODE=indices FRAME_INDICES=3769,3338,3425 \
#    bash /data/LFT-W02_data/pengxu/stage/run_stage34_workflow_v2.sh
#
# 5) 只跑 Stage-3，快速看建图是否正常
#    RUN_MODE=topwind_auto RUN_PHASE=stage3_only \
#    bash /data/LFT-W02_data/pengxu/stage/run_stage34_workflow_v2.sh
#
# 6) 只跑 Stage-4，复用已有 Stage-3 输出
#    RUN_MODE=topwind_auto RUN_PHASE=stage4_only \
#    bash /data/LFT-W02_data/pengxu/stage/run_stage34_workflow_v2.sh
#
# 7) 只跑报告，不重算 Stage-3/4
#    RUN_MODE=topwind_auto RUN_PHASE=reports_only \
#    bash /data/LFT-W02_data/pengxu/stage/run_stage34_workflow_v2.sh
#
# 8) 自定义阶段组合
#    RUN_MODE=indices FRAME_INDICES=3769,3338,3425 \
#    RUN_PHASES=stage3,stage3_summary,stage4,stage4_summary,validate \
#    bash /data/LFT-W02_data/pengxu/stage/run_stage34_workflow_v2.sh
#
# 可选环境变量：
#   PYTHON_BIN            Python 命令，默认 python
#   RUN_MODE              first3 / offset / topwind_auto / indices / full
#   RUN_PHASE             dryrun / stage3_only / stage4_only / stage34_core /
#                         validate_only / collect_only / export_only /
#                         reports_only / full
#   RUN_PHASES            更细粒度的阶段组合，逗号分隔；支持：
#                         stage3, stage3_summary, stage4, stage4_summary,
#                         validate, collect, export, readiness, sparse_metrics,
#                         outliers, npz_check, keylog
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

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEFAULT_BASE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
DEFAULT_LOG_ROOT_DIR="$SCRIPT_DIR/logs_v2"
if [[ -d "$SCRIPT_DIR/log" && ! -d "$DEFAULT_LOG_ROOT_DIR" ]]; then
  DEFAULT_LOG_ROOT_DIR="$SCRIPT_DIR/log_v2"
fi
DEFAULT_STAGE2_OUTPUT_DIR="$DEFAULT_BASE_DIR/stage2_output"
if [[ -d "$SCRIPT_DIR/stage2_output" && ! -d "$DEFAULT_STAGE2_OUTPUT_DIR" ]]; then
  DEFAULT_STAGE2_OUTPUT_DIR="$SCRIPT_DIR/stage2_output"
fi

BASE_DIR="${BASE_DIR:-$DEFAULT_BASE_DIR}"
STAGE_DIR="${STAGE_DIR:-$SCRIPT_DIR}"
LOG_ROOT_DIR="${LOG_ROOT_DIR:-$DEFAULT_LOG_ROOT_DIR}"
LOG_DIR="${LOG_DIR:-$LOG_ROOT_DIR}"
PYTHON_BIN="${PYTHON_BIN:-python}"
LATEST_LOG_DIR="${LATEST_LOG_DIR:-$LOG_ROOT_DIR}"

STAGE2_OUTPUT_DIR="${STAGE2_OUTPUT_DIR:-$DEFAULT_STAGE2_OUTPUT_DIR}"
STAGE3_OUTPUT_DIR_V2="${STAGE3_OUTPUT_DIR_V2:-$BASE_DIR/stage3_output_v2}"
STAGE3_INPUT_DIR_ORIG="${STAGE3_INPUT_DIR_ORIG:-$BASE_DIR/stage3_output}"
STAGE4_OUTPUT_DIR="${STAGE4_OUTPUT_DIR:-$BASE_DIR/stage4_output_v2}"
STAGE4_FAST_SOURCE_DIR="${STAGE4_FAST_SOURCE_DIR:-$STAGE4_OUTPUT_DIR}"
STAGE4_FULL_AUX_OUTPUT_ROOT="${STAGE4_FULL_AUX_OUTPUT_ROOT:-$BASE_DIR/stage4_output_full_aux_v2}"
export BASE_DIR STAGE_DIR LOG_ROOT_DIR LOG_DIR PYTHON_BIN LATEST_LOG_DIR
export STAGE2_OUTPUT_DIR STAGE3_OUTPUT_DIR_V2 STAGE3_INPUT_DIR_ORIG STAGE4_OUTPUT_DIR STAGE4_FAST_SOURCE_DIR STAGE4_FULL_AUX_OUTPUT_ROOT

RUN_MODE="${RUN_MODE:-topwind_auto}"
RUN_PHASE="${RUN_PHASE:-stage4_only}"
RUN_PHASES="${RUN_PHASES:-}"
MAX_FRAMES="${MAX_FRAMES:-3}"
FRAME_OFFSET="${FRAME_OFFSET:-300}"
FRAME_INDICES="${FRAME_INDICES:-}"
TOPWIND_COUNT="${TOPWIND_COUNT:-3}"
RUN_LABEL_OVERRIDE="${RUN_LABEL_OVERRIDE:-}"
EXPORT_AFTER_RUN="${EXPORT_AFTER_RUN:-1}"
RUN_VALIDATE="${RUN_VALIDATE:-1}"
PROGRESS_EVERY="${PROGRESS_EVERY:-1}"
FAST_FULL_MODE="${FAST_FULL_MODE:-1}"
STAGE3_PARALLEL_SHARDS="${STAGE3_PARALLEL_SHARDS:-8}"
STAGE3_CPU_THREADS_PER_WORKER="${STAGE3_CPU_THREADS_PER_WORKER:-2}"
STAGE4_CPU_THREADS="${STAGE4_CPU_THREADS:-8}"

# 每次 run 的 Stage-4 子集复制到独立目录，确保 export 不混入历史帧。
STAGE4_RUN_ROOT="${STAGE4_RUN_ROOT:-$BASE_DIR/stage4_output_runs_v2}"
EXPORT_DST="${EXPORT_DST:-$BASE_DIR/dataset_output_stage4_v2_clean}"

mkdir -p "$LOG_ROOT_DIR" "$STAGE4_RUN_ROOT"

declare -A PHASES=(
  [stage3]=0
  [stage3_summary]=0
  [stage4]=0
  [stage4_summary]=0
  [validate]=0
  [collect]=0
  [export]=0
  [readiness]=0
  [sparse_metrics]=0
  [outliers]=0
  [npz_check]=0
  [keylog]=0
)

PHASE_PLAN_LABEL=""
PHASE_TAG="full"
PHASE_STATUS_FILE=""
STAGE4_RUN_DIR="${STAGE4_RUN_ROOT}/${RUN_LABEL_OVERRIDE:-pending}"
ACTIVE_STAGE3_DIR="$STAGE3_INPUT_DIR_ORIG"

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

sanitize_tag() {
  local raw="${1:-}"
  raw="${raw//,/+}"
  raw="${raw// /}"
  raw="${raw//\//-}"
  raw="${raw//:/-}"
  printf '%s' "$raw" | tr -cd '[:alnum:]_.+-'
}

reset_phase_plan() {
  local key
  for key in "${!PHASES[@]}"; do
    PHASES["$key"]=0
  done
}

enable_phase() {
  local key="$1"
  [[ -v PHASES[$key] ]] || die "未知 phase=$key"
  PHASES["$key"]=1
}

phase_enabled() {
  local key="$1"
  [[ "${PHASES[$key]:-0}" == "1" ]]
}

enable_report_bundle() {
  enable_phase readiness
  enable_phase sparse_metrics
  enable_phase outliers
  enable_phase npz_check
}

enable_full_bundle() {
  enable_phase stage3
  enable_phase stage3_summary
  enable_phase stage4
  enable_phase stage4_summary
  enable_phase validate
  enable_phase collect
  enable_phase export
  enable_report_bundle
  enable_phase keylog
}

enable_runtime_bundle() {
  enable_phase stage3
  enable_phase stage3_summary
  enable_phase stage4
  enable_phase stage4_summary
  enable_phase validate
  enable_phase collect
  enable_phase readiness
}

enable_aux_runtime_bundle() {
  enable_phase stage4
  enable_phase stage4_summary
  enable_phase validate
  enable_phase collect
  enable_phase readiness
}

enabled_phases_csv() {
  local ordered=(
    stage3
    stage3_summary
    stage4
    stage4_summary
    validate
    collect
    export
    readiness
    sparse_metrics
    outliers
    npz_check
    keylog
  )
  local out=()
  local key
  for key in "${ordered[@]}"; do
    if phase_enabled "$key"; then
      out+=("$key")
    fi
  done
  local IFS=,
  printf '%s' "${out[*]}"
}

configure_v2_stage_dirs() {
  if phase_enabled stage3; then
    ACTIVE_STAGE3_DIR="$STAGE3_OUTPUT_DIR_V2"
  else
    ACTIVE_STAGE3_DIR="${STAGE3_INPUT_DIR_FOR_STAGE4:-$STAGE3_INPUT_DIR_ORIG}"
  fi
  export ACTIVE_STAGE3_DIR
}

plan_run_phases() {
  reset_phase_plan

  if [[ -n "$RUN_PHASES" ]]; then
    PHASE_PLAN_LABEL="custom"
    local token
    local bad_tokens=()
    IFS=',' read -r -a __phase_tokens <<< "$RUN_PHASES"
    for token in "${__phase_tokens[@]}"; do
      token="${token//[[:space:]]/}"
      [[ -n "$token" ]] || continue
      case "$token" in
        stage3|stage3_summary|stage4|stage4_summary|validate|collect|export|readiness|sparse_metrics|outliers|npz_check|keylog)
          enable_phase "$token"
          ;;
        core)
          enable_phase stage3
          enable_phase stage3_summary
          enable_phase stage4
          enable_phase stage4_summary
          ;;
        reports)
          enable_phase stage3_summary
          enable_phase stage4_summary
          enable_phase validate
          enable_report_bundle
          enable_phase keylog
          ;;
        *)
          bad_tokens+=("$token")
          ;;
      esac
    done
    if [[ ${#bad_tokens[@]} -gt 0 ]]; then
      die "RUN_PHASES 含未知项: ${bad_tokens[*]}"
    fi
    PHASE_TAG="$(sanitize_tag "$RUN_PHASES")"
    [[ -n "$PHASE_TAG" ]] || PHASE_TAG="custom"
    return
  fi

  case "$RUN_PHASE" in
    dryrun)
      ;;
    stage3_only)
      enable_phase stage3
      enable_phase stage3_summary
      ;;
    stage4_only)
      enable_phase stage4
      enable_phase stage4_summary
      ;;
    stage34_core)
      enable_phase stage3
      enable_phase stage3_summary
      enable_phase stage4
      enable_phase stage4_summary
      ;;
    validate_only)
      enable_phase validate
      ;;
    collect_only)
      enable_phase collect
      enable_phase npz_check
      ;;
    export_only)
      enable_phase collect
      enable_phase export
      ;;
    reports_only)
      enable_phase stage3_summary
      enable_phase stage4_summary
      enable_phase validate
      enable_report_bundle
      enable_phase keylog
      ;;
    full_fast_multi_gpu)
      enable_runtime_bundle
      ;;
    full_aux_export)
      enable_aux_runtime_bundle
      ;;
    full)
      enable_runtime_bundle
      ;;
    *)
      die "未知 RUN_PHASE=$RUN_PHASE，可选: dryrun / stage3_only / stage4_only / stage34_core / validate_only / collect_only / export_only / reports_only / full_fast_multi_gpu / full_aux_export / full"
      ;;
  esac

  PHASE_PLAN_LABEL="$RUN_PHASE"
  PHASE_TAG="$(sanitize_tag "$RUN_PHASE")"
  [[ -n "$PHASE_TAG" ]] || PHASE_TAG="full"
}

init_phase_status() {
  PHASE_STATUS_FILE="$LOG_DIR/phase_status_${RUN_LABEL}.log"
  {
    echo "run_mode=$RUN_MODE"
    echo "run_phase=$RUN_PHASE"
    echo "run_phases=${RUN_PHASES:-}"
    echo "phase_plan=$PHASE_PLAN_LABEL"
    echo "enabled_phases=$(enabled_phases_csv)"
  } > "$PHASE_STATUS_FILE"
}

mark_phase() {
  local phase="$1"
  local status="$2"
  local detail="${3:-}"
  local ts
  ts="$(date '+%Y-%m-%d %H:%M:%S' 2>/dev/null || echo 'unknown-time')"
  printf '%s\t%s\t%s\t%s\n' "$ts" "$phase" "$status" "$detail" >> "$PHASE_STATUS_FILE"
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
  if [[ "$PHASE_TAG" != "full" ]]; then
    mode_dir="${mode_dir}__${PHASE_TAG}"
  fi
  LOG_DIR="$LOG_ROOT_DIR/$mode_dir"
  export LOG_DIR
  mkdir -p "$LOG_DIR"

  local base_run_label=""
  case "$RUN_MODE" in
    first3)
      export WIND_FRAME_OFFSET=0
      export WIND_MAX_FRAMES="$MAX_FRAMES"
      base_run_label="${RUN_LABEL_OVERRIDE:-3frames_new}"
      ;;
    offset)
      export WIND_FRAME_OFFSET="$FRAME_OFFSET"
      export WIND_MAX_FRAMES="$MAX_FRAMES"
      base_run_label="${RUN_LABEL_OVERRIDE:-offset${FRAME_OFFSET}}"
      ;;
    indices)
      [[ -n "$FRAME_INDICES" ]] || die "RUN_MODE=indices 时必须提供 FRAME_INDICES"
      export WIND_FRAME_INDICES="$FRAME_INDICES"
      base_run_label="${RUN_LABEL_OVERRIDE:-indices}"
      ;;
    topwind_auto)
      generate_stage2_topwind_log
      FRAME_INDICES="$(pick_topwind_indices)"
      [[ -n "$FRAME_INDICES" ]] || die "自动挑选高风帧失败，FRAME_INDICES 为空"
      export WIND_FRAME_INDICES="$FRAME_INDICES"
      base_run_label="${RUN_LABEL_OVERRIDE:-topwind}"
      ;;
    full)
      base_run_label="${RUN_LABEL_OVERRIDE:-full}"
      ;;
    *)
      die "未知 RUN_MODE=$RUN_MODE，可选: first3 / offset / indices / topwind_auto / full"
      ;;
  esac

  RUN_LABEL="$base_run_label"
  if [[ "$PHASE_TAG" != "full" ]]; then
    RUN_LABEL="${RUN_LABEL}_${PHASE_TAG}"
  fi
  export RUN_LABEL
  STAGE4_RUN_DIR="$STAGE4_RUN_ROOT/$RUN_LABEL"
  export STAGE4_RUN_DIR
  if [[ "$RUN_PHASE" == "full" && "$FAST_FULL_MODE" == "1" ]]; then
    export WIND_STAGE4_FAST_MODE=1
    export WIND_STAGE4_OUTPUT_PROFILE=fast
    export WIND_STAGE4_ENABLE_QUALITY_EXPAND=0
    export WIND_STAGE4_SAVE_COMPRESSED=0
    export EXPORT_AFTER_RUN=0
    log "启用 Stage-4 快速全量研究模式: WIND_STAGE4_FAST_MODE=1, WIND_STAGE4_OUTPUT_PROFILE=fast, WIND_STAGE4_ENABLE_QUALITY_EXPAND=0, WIND_STAGE4_SAVE_COMPRESSED=0, EXPORT_AFTER_RUN=0"
  fi
  if [[ "$RUN_PHASE" == "full_fast_multi_gpu" ]]; then
    export WIND_STAGE4_FAST_MODE=1
    export WIND_STAGE4_OUTPUT_PROFILE=fast
    export WIND_STAGE4_ENABLE_QUALITY_EXPAND=0
    export WIND_STAGE4_SAVE_COMPRESSED=0
    export EXPORT_AFTER_RUN=0
    log "启用 Stage-4 多卡快速模式: output_profile=fast, quality_expand=0"
  fi
  if [[ "$RUN_PHASE" == "full_aux_export" ]]; then
    export WIND_STAGE4_FAST_MODE=1
    export WIND_STAGE4_OUTPUT_PROFILE=full_aux_export
    export WIND_STAGE4_ENABLE_QUALITY_EXPAND=1
    export WIND_STAGE4_FAST_SKIP_POST=0
    export WIND_STAGE4_FAST_SKIP_DENSE_AUX=0
    export WIND_STAGE4_SAVE_COMPRESSED=1
    export WIND_STAGE4_AUX_SOURCE_DIR="${STAGE4_FAST_SOURCE_DIR}"
    STAGE4_OUTPUT_DIR="${STAGE4_FULL_AUX_OUTPUT_ROOT}/${RUN_LABEL}"
    export STAGE4_OUTPUT_DIR
    log "启用 Stage-4 full_aux_export 模式: 基于已有 fast 结果补写完整辅助场"
  fi
  log "运行模式: $RUN_MODE"
  log "阶段方案: $PHASE_PLAN_LABEL"
  log "启用阶段: $(enabled_phases_csv)"
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
    echo "run_phase=$RUN_PHASE"
    echo "run_phases=${RUN_PHASES:-}"
    echo "phase_plan=$PHASE_PLAN_LABEL"
    echo "enabled_phases=$(enabled_phases_csv)"
    echo "run_label=$RUN_LABEL"
    echo "log_dir=$LOG_DIR"
    echo "stage2_output_dir=$STAGE2_OUTPUT_DIR"
    echo "active_stage3_dir=$ACTIVE_STAGE3_DIR"
    echo "stage3_output_dir_v2=$STAGE3_OUTPUT_DIR_V2"
    echo "stage4_output_dir=$STAGE4_OUTPUT_DIR"
    echo "stage4_fast_source_dir=$STAGE4_FAST_SOURCE_DIR"
    echo "stage4_full_aux_output_root=$STAGE4_FULL_AUX_OUTPUT_ROOT"
    echo "stage3_parallel_shards=$STAGE3_PARALLEL_SHARDS"
    echo "stage3_cpu_threads_per_worker=$STAGE3_CPU_THREADS_PER_WORKER"
    echo "stage4_cpu_threads=$STAGE4_CPU_THREADS"
    echo "stage4_run_dir=${STAGE4_RUN_ROOT}/${RUN_LABEL}"
    echo "frame_indices=${WIND_FRAME_INDICES:-}"
    echo "frame_offset=${WIND_FRAME_OFFSET:-}"
    echo "max_frames=${WIND_MAX_FRAMES:-}"
  } > "$run_info"
  cp "$run_info" "$latest_info"
}

run_stage3_script() {
  local stage3_log="$LOG_DIR/stage3_${RUN_LABEL}.log"
  require_file "$STAGE_DIR/stage3_agents_v2.py"
  require_file "$STAGE2_OUTPUT_DIR/stage2_summary.json"
  export WIND_STAGE2_SUMMARY_PATH_OVERRIDE="$STAGE2_OUTPUT_DIR/stage2_summary.json"
  export WIND_STAGE3_OUTPUT_DIR="$STAGE3_OUTPUT_DIR_V2"

  mark_phase stage3 RUN "python $STAGE_DIR/stage3_agents_v2.py"
  log "开始运行 Stage-3 ..."
  "$PYTHON_BIN" "$STAGE_DIR/stage3_agents_v2.py" > "$stage3_log" 2>&1
  mark_phase stage3 DONE "$stage3_log"
  log "Stage-3 日志: $stage3_log"
}

run_stage4_script() {
  local stage4_log="$LOG_DIR/stage4_${RUN_LABEL}.log"

  require_file "$STAGE_DIR/stage4_pack_v2.py"
  require_file "$ACTIVE_STAGE3_DIR/stage3_summary.json"
  export WIND_STAGE2_SUMMARY_PATH_OVERRIDE="$STAGE2_OUTPUT_DIR/stage2_summary.json"
  export WIND_STAGE3_INPUT_DIR="$ACTIVE_STAGE3_DIR"
  export WIND_STAGE4_OUTPUT_DIR="$STAGE4_OUTPUT_DIR"
  export OMP_NUM_THREADS="$STAGE4_CPU_THREADS"
  export MKL_NUM_THREADS="$STAGE4_CPU_THREADS"
  export NUMEXPR_NUM_THREADS="$STAGE4_CPU_THREADS"
  export POLARS_MAX_THREADS="$STAGE4_CPU_THREADS"
  mkdir -p "$STAGE4_OUTPUT_DIR"

  mark_phase stage4 RUN "python $STAGE_DIR/stage4_pack_v2.py"
  log "开始运行 Stage-4 ..."
  "$PYTHON_BIN" "$STAGE_DIR/stage4_pack_v2.py" > "$stage4_log" 2>&1
  mark_phase stage4 DONE "$stage4_log"
  log "Stage-4 日志: $stage4_log"
}

run_full_fast_multi_gpu() {
  local shard_count="${STAGE3_PARALLEL_SHARDS:-4}"
  local stage4_shard_enabled="${MULTI_GPU_STAGE4_SHARD:-0}"
  log "multi_gpu policy: stage3=sharded(${shard_count}) cpu_threads_per_worker=${STAGE3_CPU_THREADS_PER_WORKER}, stage4=$([[ \"$stage4_shard_enabled\" == \"1\" ]] && printf 'sharded-experimental' || printf 'single-gpu-serial') cpu_threads=${STAGE4_CPU_THREADS}"
  local indices_csv
  indices_csv="$(build_frame_indices_for_current_run)"
  [[ -n "$indices_csv" ]] || die "full_fast_multi_gpu 未生成任何 frame indices"

  local shard_indices
  mapfile -t shard_indices < <(split_indices_into_shards "$indices_csv" "$shard_count")
  local shard_root="$BASE_DIR/stage_shard_runs/${RUN_LABEL}"
  local shard_stage3_root="$shard_root/stage3"
  local shard_stage4_root="$shard_root/stage4"
  mkdir -p "$shard_stage3_root" "$shard_stage4_root"

  local pids=()
  local shard_id=0
  local shard_csv=""
  for shard_csv in "${shard_indices[@]}"; do
    if [[ -z "$shard_csv" ]]; then
      shard_id=$((shard_id + 1))
      continue
    fi
    local shard_name="shard_${shard_id}"
    local shard_stage3_dir="$shard_stage3_root/$shard_name"
    local shard_log_dir="$LOG_DIR/$shard_name"
    mkdir -p "$shard_stage3_dir" "$shard_log_dir"
    (
      export WIND_FRAME_INDICES="$shard_csv"
      export WIND_STAGE2_SUMMARY_PATH_OVERRIDE="$STAGE2_OUTPUT_DIR/stage2_summary.json"
      export WIND_STAGE3_OUTPUT_DIR="$shard_stage3_dir"
      export WIND_STAGE4_USE_GPU=1
      export WIND_STAGE4_GPU_DEVICE="cuda:${shard_id}"
      export WIND_STAGE4_OUTPUT_PROFILE=fast
      export WIND_STAGE4_ENABLE_QUALITY_EXPAND=0
      export WIND_STAGE4_FAST_MODE=1
      export WIND_STAGE4_SAVE_COMPRESSED=0
      export OMP_NUM_THREADS="$STAGE3_CPU_THREADS_PER_WORKER"
      export MKL_NUM_THREADS="$STAGE3_CPU_THREADS_PER_WORKER"
      export NUMEXPR_NUM_THREADS="$STAGE3_CPU_THREADS_PER_WORKER"
      export POLARS_MAX_THREADS="$STAGE3_CPU_THREADS_PER_WORKER"
      "$PYTHON_BIN" "$STAGE_DIR/stage3_agents_v2.py" > "$shard_log_dir/stage3_${shard_name}.log" 2>&1
    ) &
    pids+=("$!")
    shard_id=$((shard_id + 1))
  done

  local pid
  for pid in "${pids[@]}"; do
    wait "$pid"
  done

  merge_stage3_shards "$shard_stage3_root" "$STAGE3_OUTPUT_DIR_V2"

  if [[ "$stage4_shard_enabled" == "1" ]]; then
    local stage4_pids=()
    shard_id=0
    for shard_csv in "${shard_indices[@]}"; do
      if [[ -z "$shard_csv" ]]; then
        shard_id=$((shard_id + 1))
        continue
      fi
      local shard_name="shard_${shard_id}"
      local shard_stage4_dir="$shard_stage4_root/$shard_name"
      local shard_log_dir="$LOG_DIR/$shard_name"
      mkdir -p "$shard_stage4_dir" "$shard_log_dir"
      (
        export WIND_FRAME_INDICES="$shard_csv"
        export WIND_STAGE2_SUMMARY_PATH_OVERRIDE="$STAGE2_OUTPUT_DIR/stage2_summary.json"
        export WIND_STAGE3_INPUT_DIR="$STAGE3_OUTPUT_DIR_V2"
        export WIND_STAGE4_OUTPUT_DIR="$shard_stage4_dir"
        export WIND_STAGE4_USE_GPU=1
        export WIND_STAGE4_GPU_DEVICE="cuda:${shard_id}"
        export WIND_STAGE4_OUTPUT_PROFILE=fast
        export WIND_STAGE4_ENABLE_QUALITY_EXPAND=0
        export WIND_STAGE4_FAST_MODE=1
        export WIND_STAGE4_SAVE_COMPRESSED=0
        export OMP_NUM_THREADS="$STAGE4_CPU_THREADS"
        export MKL_NUM_THREADS="$STAGE4_CPU_THREADS"
        export NUMEXPR_NUM_THREADS="$STAGE4_CPU_THREADS"
        export POLARS_MAX_THREADS="$STAGE4_CPU_THREADS"
        "$PYTHON_BIN" "$STAGE_DIR/stage4_pack_v2.py" > "$shard_log_dir/stage4_${shard_name}.log" 2>&1
      ) &
      stage4_pids+=("$!")
      shard_id=$((shard_id + 1))
    done
    for pid in "${stage4_pids[@]}"; do
      wait "$pid"
    done
    merge_stage4_shards "$shard_stage4_root" "$STAGE4_OUTPUT_DIR"
  else
    export WIND_STAGE3_INPUT_DIR="$STAGE3_OUTPUT_DIR_V2"
    export WIND_STAGE4_OUTPUT_DIR="$STAGE4_OUTPUT_DIR"
    export WIND_STAGE4_USE_GPU=1
    export WIND_STAGE4_GPU_DEVICE="cuda:0"
    export WIND_STAGE4_OUTPUT_PROFILE=fast
    export WIND_STAGE4_ENABLE_QUALITY_EXPAND=0
    export WIND_STAGE4_FAST_MODE=1
    export WIND_STAGE4_SAVE_COMPRESSED=0
    export OMP_NUM_THREADS="$STAGE4_CPU_THREADS"
    export MKL_NUM_THREADS="$STAGE4_CPU_THREADS"
    export NUMEXPR_NUM_THREADS="$STAGE4_CPU_THREADS"
    export POLARS_MAX_THREADS="$STAGE4_CPU_THREADS"
    "$PYTHON_BIN" "$STAGE_DIR/stage4_pack_v2.py" > "$LOG_DIR/stage4_${RUN_LABEL}.log" 2>&1
  fi
}

build_frame_indices_for_current_run() {
  "$PYTHON_BIN" - <<'PY'
import json
import os
from pathlib import Path

stage2_path = Path(os.environ["STAGE2_OUTPUT_DIR"]) / "stage2_summary.json"
data = json.loads(stage2_path.read_text(encoding="utf-8"))
indexed = []
for idx, item in enumerate(data):
    one = dict(item)
    one["source_index"] = idx
    indexed.append(one)

indices_env = os.environ.get("WIND_FRAME_INDICES", "").strip()
if indices_env:
    picked = []
    for token in indices_env.split(","):
        token = token.strip()
        if not token:
            continue
        try:
            src_idx = int(token)
        except ValueError:
            continue
        if 0 <= src_idx < len(indexed):
            picked.append(src_idx)
    picked = sorted(set(picked))
    print(",".join(str(x) for x in picked))
    raise SystemExit(0)

frame_offset = max(0, int(os.environ.get("WIND_FRAME_OFFSET", "0") or "0"))
if frame_offset > 0:
    indexed = indexed[frame_offset:]
max_frames_env = os.environ.get("WIND_MAX_FRAMES")
if max_frames_env not in (None, "", "0"):
    try:
        max_frames = max(1, int(max_frames_env))
    except ValueError:
        max_frames = None
    if max_frames is not None:
        indexed = indexed[:max_frames]
print(",".join(str(int(x["source_index"])) for x in indexed))
PY
}

split_indices_into_shards() {
  local indices_csv="$1"
  local shard_count="${2:-4}"
  "$PYTHON_BIN" - <<'PY' "$indices_csv" "$shard_count"
import sys
indices_csv = sys.argv[1].strip()
shard_count = max(1, int(sys.argv[2]))
indices = [int(x) for x in indices_csv.split(",") if x.strip()]
shards = []
if not indices:
    shards = [[] for _ in range(shard_count)]
else:
    n = len(indices)
    base = n // shard_count
    rem = n % shard_count
    start = 0
    for i in range(shard_count):
        size = base + (1 if i < rem else 0)
        shards.append(indices[start:start + size])
        start += size
for shard in shards:
    print(",".join(str(x) for x in shard))
PY
}

merge_stage3_shards() {
  local shard_root="$1"
  local merged_dir="$2"
  mkdir -p "$merged_dir/agents"
  export STAGE3_SHARD_ROOT="$shard_root"
  export STAGE3_MERGED_DIR="$merged_dir"
  "$PYTHON_BIN" - <<'PY'
import json
import os
import shutil
from pathlib import Path

root = Path(os.environ["STAGE3_SHARD_ROOT"])
merged = Path(os.environ["STAGE3_MERGED_DIR"])
items = []
for shard_dir in sorted(root.glob("shard_*")):
    summary = shard_dir / "stage3_summary.json"
    if not summary.exists():
        continue
    data = json.loads(summary.read_text(encoding="utf-8"))
    for item in data:
        src = Path(item["agent_path"])
        dst = merged / "agents" / src.name
        if src.exists() and not dst.exists():
            shutil.copy2(src, dst)
        one = dict(item)
        one["agent_path"] = str(dst)
        items.append(one)
items = sorted(items, key=lambda x: int(x.get("source_index", -1)))
(merged / "stage3_summary.json").write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"merged_stage3_frames={len(items)}")
PY
}

merge_stage4_shards() {
  local shard_root="$1"
  local merged_dir="$2"
  mkdir -p "$merged_dir"
  export STAGE4_SHARD_ROOT="$shard_root"
  export STAGE4_MERGED_DIR="$merged_dir"
  "$PYTHON_BIN" - <<'PY'
import json
import os
import shutil
from pathlib import Path

root = Path(os.environ["STAGE4_SHARD_ROOT"])
merged = Path(os.environ["STAGE4_MERGED_DIR"])
for old in merged.glob("frame_*.npz"):
    old.unlink()
items = []
for shard_dir in sorted(root.glob("shard_*")):
    summary = shard_dir / "stage4_summary.json"
    if not summary.exists():
        continue
    data = json.loads(summary.read_text(encoding="utf-8"))
    for item in data:
        src = shard_dir / item["filename"]
        dst = merged / item["filename"]
        if src.exists() and not dst.exists():
            shutil.copy2(src, dst)
        items.append(dict(item))
items = sorted(items, key=lambda x: int(x.get("source_index", -1)))
(merged / "stage4_summary.json").write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"merged_stage4_frames={len(items)}")
PY
}

run_validate() {
  local validate_log_run="$LOG_DIR/validate_pipeline_constracts_${RUN_LABEL}.log"
  local validate_log_latest="$LOG_DIR/validate_pipeline_constracts.log"
  local validate_py
  validate_py="$(resolve_validate_py)"

  if [[ "$RUN_VALIDATE" != "1" ]]; then
    mark_phase validate SKIP "RUN_VALIDATE=$RUN_VALIDATE"
    warn "按配置跳过 validate"
    return
  fi

  if [[ ! -f "$validate_py" ]]; then
    warn "未找到 validate_pipeline_constracts.py，跳过 validate"
    printf '[contract-check] SKIP\n - missing validator script\n' > "$validate_log_run"
    mark_phase validate SKIP "missing validator: $validate_py"
  else
    mark_phase validate RUN "$validate_py"
    "$PYTHON_BIN" "$validate_py" > "$validate_log_run" 2>&1 || true
    mark_phase validate DONE "$validate_log_run"
  fi
  cp "$validate_log_run" "$validate_log_latest"
  log "Validate 日志: $validate_log_run"
}

write_stage3_summary_logs() {
  local run_log="$LOG_DIR/stage3wind_${RUN_LABEL}.log"
  local latest_log="$LOG_DIR/stage3wind.log"
  export STAGE3_SUMMARY_PATH="$ACTIVE_STAGE3_DIR/stage3_summary.json"
  require_file "$STAGE3_SUMMARY_PATH"
  mark_phase stage3_summary RUN "$STAGE3_SUMMARY_PATH"
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
  mark_phase stage3_summary DONE "$run_log"
  log "Stage-3 summary 日志: $run_log"
}

write_stage4_summary_logs() {
  local run_log="$LOG_DIR/stage4summary_${RUN_LABEL}.log"
  local latest_log="$LOG_DIR/stage4summary.log"
  export STAGE4_SUMMARY_PATH="$STAGE4_OUTPUT_DIR/stage4_summary.json"
  require_file "$STAGE4_SUMMARY_PATH"
  mark_phase stage4_summary RUN "$STAGE4_SUMMARY_PATH"
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
        "anchor_restore=", item.get("anchor_restore_voxels"),
        "anchor_force=", item.get("anchor_force_voxels"),
        "wind_conflict_keep=", item.get("wind_conflict_keep_voxels"),
        "direct_agree=", item.get("direct_agreement_mean"),
        "pruned=", item.get("recon_pruned_voxels"),
        "support_domain=", item.get("recon_support_domain_voxels"),
        "domain=", item.get("recon_domain_voxels"),
        "recon_mean=", item.get("recon_conf_mean"),
        "conf_p10=", item.get("recon_conf_p10"),
        "conf_p50=", item.get("recon_conf_p50"),
        "conf_p90=", item.get("recon_conf_p90"),
        "conf_spread=", item.get("recon_conf_spread_p10_p90"),
        "coverage=", item.get("recon_coverage_ratio"),
        "forecast_cov=", item.get("forecast_coverage_ratio"),
        "outlier_drop=", item.get("outlier_drop_voxels"),
        "wind_edges=", item.get("flight_ff_wind_edges"),
    )
PY
  cp "$run_log" "$latest_log"
  mark_phase stage4_summary DONE "$run_log"
  log "Stage-4 summary 日志: $run_log"
}

collect_current_stage4_run() {
  # 这里把“当前这次 run 的 Stage-4 输出子集”拷贝到独立目录，
  # 避免 export 时混入历史 run 留在 stage4_output 目录里的旧帧。
  export STAGE4_OUTPUT_DIR
  export STAGE4_RUN_DIR="$STAGE4_RUN_ROOT/$RUN_LABEL"
  if [[ "$(python - <<'PY'
import os
from pathlib import Path
src = Path(os.environ["STAGE4_OUTPUT_DIR"]).resolve()
dst = Path(os.environ["STAGE4_RUN_DIR"]).resolve()
print(int(src == dst))
PY
)" == "1" ]]; then
    mark_phase collect SKIP "stage4 output already isolated"
    log "跳过 collect: Stage-4 已直接输出到 run 目录"
    return
  fi
  mkdir -p "$STAGE4_RUN_DIR"
  require_file "$STAGE4_OUTPUT_DIR/stage4_summary.json"
  mark_phase collect RUN "$STAGE4_OUTPUT_DIR -> $STAGE4_RUN_DIR"
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
  mark_phase collect DONE "$STAGE4_RUN_DIR"
  log "本次 Stage-4 子集目录: $STAGE4_RUN_DIR"
}

run_export() {
  local export_py
  local run_log="$LOG_DIR/export_stage4_${RUN_LABEL}.log"
  local latest_log="$LOG_DIR/export_stage4"
  local help_text=""
  local export_src="${STAGE4_RUN_DIR:-$STAGE4_OUTPUT_DIR}"

  if [[ "$EXPORT_AFTER_RUN" != "1" ]]; then
    mark_phase export SKIP "EXPORT_AFTER_RUN=$EXPORT_AFTER_RUN"
    warn "按配置跳过 export"
    return
  fi

  export_py="$(resolve_export_py)"
  if [[ -z "$export_py" || ! -f "$export_py" ]]; then
    warn "未找到 export_stage4_dataset.py，跳过 export"
    printf '[export] SKIP\nmissing export_stage4_dataset.py\n' > "$run_log"
    cp "$run_log" "$latest_log"
    mark_phase export SKIP "missing export script"
    return
  fi

  if [[ ! -d "$export_src" ]]; then
    mark_phase export SKIP "missing export src: $export_src"
    warn "未找到 export 源目录，跳过 export: $export_src"
    return
  fi

  export STAGE4_RUN_DIR="$export_src"
  mark_phase export RUN "$export_py --src $STAGE4_RUN_DIR --dst $EXPORT_DST"
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
  mark_phase export DONE "$run_log"
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
    mark_phase readiness SKIP "missing report_stage4_training_readiness.py"
    return
  fi

  mark_phase readiness RUN "$report_py"
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
  mark_phase readiness DONE "$run_log"
  log "Stage-4 全量统计报告: $run_log"
}

run_stage4_sparse_metrics_report() {
  local report_py="$STAGE_DIR/report_stage4_sparse_metrics.py"
  local run_log="$LOG_DIR/stage4_sparse_metrics_${RUN_LABEL}.log"
  local latest_log="$LOG_DIR/stage4_sparse_metrics.log"
  local out_json="$LOG_DIR/stage4_sparse_metrics_${RUN_LABEL}.json"

  if [[ ! -f "$report_py" ]]; then
    warn "未找到 report_stage4_sparse_metrics.py，跳过稀疏监督指标统计"
    mark_phase sparse_metrics SKIP "missing report_stage4_sparse_metrics.py"
    return
  fi

  mark_phase sparse_metrics RUN "$report_py"
  "$PYTHON_BIN" "$report_py" \
    --stage2-summary "$STAGE2_OUTPUT_DIR/stage2_summary.json" \
    --stage4-summary "$STAGE4_OUTPUT_DIR/stage4_summary.json" \
    --stage4-dir "$STAGE4_OUTPUT_DIR" \
    --out-json "$out_json" \
    > "$run_log" 2>&1
  cp "$run_log" "$latest_log"
  mark_phase sparse_metrics DONE "$run_log"
  log "Stage-4 稀疏监督指标报告: $run_log"
}

run_stage4_outlier_report() {
  local report_py="$STAGE_DIR/report_stage4_outlier_report.py"
  local run_log="$LOG_DIR/stage4_outliers_${RUN_LABEL}.log"
  local latest_log="$LOG_DIR/stage4_outliers.log"
  local out_json="$LOG_DIR/stage4_outliers_${RUN_LABEL}.json"
  local top_k="${STAGE4_OUTLIER_TOPK:-10}"

  if [[ ! -f "$report_py" ]]; then
    warn "未找到 report_stage4_outlier_report.py，跳过 outlier 定位报告"
    printf '[outlier-report] SKIP\nmissing report_stage4_outlier_report.py\n' > "$run_log"
    cp "$run_log" "$latest_log"
    mark_phase outliers SKIP "missing report_stage4_outlier_report.py"
    return
  fi

  mark_phase outliers RUN "$report_py"
  "$PYTHON_BIN" "$report_py" \
    --stage2-summary "$STAGE2_OUTPUT_DIR/stage2_summary.json" \
    --stage4-summary "$STAGE4_OUTPUT_DIR/stage4_summary.json" \
    --stage4-dir "$STAGE4_OUTPUT_DIR" \
    --top-k "$top_k" \
    --out-json "$out_json" \
    > "$run_log" 2>&1
  cp "$run_log" "$latest_log"
  mark_phase outliers DONE "$run_log"
  log "Stage-4 outlier 定位报告: $run_log"
}

check_stage4_npz_fields_current_run() {
  local run_log="$LOG_DIR/stage4_npz_fields_${RUN_LABEL}.log"
  local latest_log="$LOG_DIR/stage4_npz_fields.log"
  local npz_dir="${STAGE4_RUN_DIR:-$STAGE4_OUTPUT_DIR}"
  local sample_n="${STAGE4_NPZ_CHECK_SAMPLES:-1}"
  if [[ ! -d "$npz_dir" ]]; then
    warn "未找到 Stage-4 npz 检查目录，跳过字段检查: $npz_dir"
    mark_phase npz_check SKIP "missing dir: $npz_dir"
    return
  fi
  export STAGE4_RUN_DIR="$npz_dir"
  export STAGE4_NPZ_CHECK_SAMPLES="$sample_n"
  mark_phase npz_check RUN "$STAGE4_RUN_DIR"
  "$PYTHON_BIN" - <<'PY' > "$run_log" 2>&1
import numpy as np
import os
from pathlib import Path

p = Path(os.environ["STAGE4_RUN_DIR"])
sample_n = max(1, int(os.environ.get("STAGE4_NPZ_CHECK_SAMPLES", "1") or "1"))
files = sorted(p.glob("frame_*.npz"))
for fp in files[:sample_n]:
    with np.load(fp, allow_pickle=True) as npz:
        print(fp.name)
        for key in [
            "comm_joint_idx",
            "comm_wind_idx",
            "comm_motion_idx",
            "comm_uncertainty_idx",
            "physics_weight_3d",
            "pinn_prior_u_3d",
            "direct_agreement_3d",
            "direct_agreement_idx",
            "direct_source_count_3d",
            "direct_source_count_idx",
            "source_diversity_3d",
            "source_diversity_idx",
            "pinn_divergence_3d",
            "diffusion_condition_4d",
            "forecast_u_3d",
            "hazard_alert_mask_3d",
        ]:
            print(key, key in npz.files, npz[key].shape if key in npz.files else None)
        print()
PY
  cp "$run_log" "$latest_log"
  mark_phase npz_check DONE "$run_log"
  log "Stage-4 当前 run 的 npz 字段检查: $run_log"
}

append_log_block() {
  local title="$1"
  local file_path="$2"
  local lines="${3:-120}"
  echo "=== $title ==="
  if [[ -f "$file_path" ]]; then
    tail -n "$lines" "$file_path" || true
  else
    echo "[SKIP] missing log: $file_path"
  fi
  echo
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
    echo "=== Phase Status ==="
    if [[ -f "$PHASE_STATUS_FILE" ]]; then
      cat "$PHASE_STATUS_FILE"
    else
      echo "[SKIP] missing phase status file"
    fi
    echo
    echo "=== Stage3 wind ==="
    if [[ -f "$stage3_log" ]]; then
      grep "\[Stage-3\]\[wind\]" "$stage3_log" || true
    else
      echo "[SKIP] missing log: $stage3_log"
    fi
    echo
    echo "=== Stage4 diag/frame ==="
    if [[ -f "$stage4_log" ]]; then
      grep -E "\[Stage-4\]\[(diag|frame)\]" "$stage4_log" || true
    else
      echo "[SKIP] missing log: $stage4_log"
    fi
    echo
    append_log_block "Stage3 summary" "$stage3_summary_log" 120
    append_log_block "Stage4 summary" "$stage4_summary_log" 120
    append_log_block "Validate" "$validate_log" 120
    append_log_block "Stage4 readiness" "$stage4_stats_log" 120
    append_log_block "Stage4 sparse metrics" "$stage4_sparse_metrics_log" 120
    append_log_block "Stage4 outliers" "$stage4_outliers_log" 120
    append_log_block "Export" "$export_log" 120
  } > "$run_log" 2>&1

  cp "$run_log" "$latest_log"
  mark_phase keylog DONE "$run_log"
  log "汇总 key 日志: $run_log"
}

main() {
  plan_run_phases
  configure_v2_stage_dirs
  select_run_mode
  write_run_info
  init_phase_status

  if [[ "$RUN_PHASE" == "full_fast_multi_gpu" ]]; then
    mark_phase stage3 RUN "multi_gpu shard runner"
    mark_phase stage4 RUN "multi_gpu shard runner"
    run_full_fast_multi_gpu
    mark_phase stage3 DONE "multi_gpu shard runner"
    mark_phase stage4 DONE "multi_gpu shard runner"
    if phase_enabled stage3_summary; then
      write_stage3_summary_logs
    else
      mark_phase stage3_summary SKIP "phase disabled"
    fi
    if phase_enabled stage4_summary; then
      write_stage4_summary_logs
    else
      mark_phase stage4_summary SKIP "phase disabled"
    fi
    if phase_enabled validate; then
      run_validate
    else
      mark_phase validate SKIP "phase disabled"
    fi
    if phase_enabled collect; then
      collect_current_stage4_run
    else
      mark_phase collect SKIP "phase disabled"
    fi
    if phase_enabled export; then
      run_export
    else
      mark_phase export SKIP "phase disabled"
    fi
    if phase_enabled readiness; then
      run_stage4_readiness_report
    else
      mark_phase readiness SKIP "phase disabled"
    fi
    if phase_enabled sparse_metrics; then
      run_stage4_sparse_metrics_report
    else
      mark_phase sparse_metrics SKIP "phase disabled"
    fi
    if phase_enabled outliers; then
      run_stage4_outlier_report
    else
      mark_phase outliers SKIP "phase disabled"
    fi
    if phase_enabled npz_check; then
      check_stage4_npz_fields_current_run
    else
      mark_phase npz_check SKIP "phase disabled"
    fi
    if phase_enabled keylog; then
      mark_phase keylog RUN "build_key_log"
      build_key_log
    else
      mark_phase keylog SKIP "phase disabled"
    fi

    log "流程完成"
    log "阶段方案: $PHASE_PLAN_LABEL"
    log "启用阶段: $(enabled_phases_csv)"
    return
  fi

  if phase_enabled stage3; then
    run_stage3_script
  else
    mark_phase stage3 SKIP "phase disabled"
  fi

  if phase_enabled stage3_summary; then
    write_stage3_summary_logs
  else
    mark_phase stage3_summary SKIP "phase disabled"
  fi

  if phase_enabled stage4; then
    run_stage4_script
  else
    mark_phase stage4 SKIP "phase disabled"
  fi

  if phase_enabled stage4_summary; then
    write_stage4_summary_logs
  else
    mark_phase stage4_summary SKIP "phase disabled"
  fi

  if phase_enabled validate; then
    run_validate
  else
    mark_phase validate SKIP "phase disabled"
  fi

  if phase_enabled collect; then
    collect_current_stage4_run
  else
    mark_phase collect SKIP "phase disabled"
  fi

  if phase_enabled export; then
    run_export
  else
    mark_phase export SKIP "phase disabled"
  fi

  if phase_enabled readiness; then
    run_stage4_readiness_report
  else
    mark_phase readiness SKIP "phase disabled"
  fi

  if phase_enabled sparse_metrics; then
    run_stage4_sparse_metrics_report
  else
    mark_phase sparse_metrics SKIP "phase disabled"
  fi

  if phase_enabled outliers; then
    run_stage4_outlier_report
  else
    mark_phase outliers SKIP "phase disabled"
  fi

  if phase_enabled npz_check; then
    check_stage4_npz_fields_current_run
  else
    mark_phase npz_check SKIP "phase disabled"
  fi

  if phase_enabled keylog; then
    mark_phase keylog RUN "build_key_log"
    build_key_log
  else
    mark_phase keylog SKIP "phase disabled"
  fi

  log "流程完成"
  log "阶段方案: $PHASE_PLAN_LABEL"
  log "启用阶段: $(enabled_phases_csv)"
  log "请重点查看:"
  log "  $PHASE_STATUS_FILE"
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
