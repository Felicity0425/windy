#!/usr/bin/env bash
set -euo pipefail

PY="/data/LFT-W02_data/pengxu/.conda/envs/windy310/bin/python"
ROOT="/data/LFT-W02_data/pengxu"
cd "$ROOT"

FRAMES200="centralized_v1_output/stage4_guardrail_display_fill_200_20260605_25w/tp26_thr11_preserve_metrics/stage4_validation_frame_times.txt"
OUT_ROOT="$ROOT/优化/stage4_cma_m1_light_demo_20260625/gfs_historical_aws_200"
RAW_DIR="$OUT_ROOT/raw_grib"
CACHE_NPZ_DIR="$OUT_ROOT/cache_npz"
NPZ_DIR="$OUT_ROOT/npz"
LOG_DIR="$ROOT/优化/stage4_cma_m1_light_demo_20260625/logs"
TMP_CSV="$OUT_ROOT/frame_times_200.csv"
RUN_LOG="$LOG_DIR/gfs_historical_aws_200_resume.log"
FAIL_LOG="$OUT_ROOT/failed_frames.txt"

mkdir -p "$RAW_DIR" "$CACHE_NPZ_DIR" "$NPZ_DIR" "$LOG_DIR"
cp "$FRAMES200" "$OUT_ROOT/frame_times_200.txt"
paste -sd, "$FRAMES200" > "$TMP_CSV"
echo "[gfs-run] frames_file=$FRAMES200"
echo "[gfs-run] out_root=$OUT_ROOT"
echo "[gfs-run] run_log=$RUN_LOG"
"$PY" stage/download_stage5_gfs_aws_cached_batch.py \
  --frame-times-file "$FRAMES200" \
  --variables UGRD,VGRD \
  --raw-dir "$RAW_DIR" \
  --cache-npz-dir "$CACHE_NPZ_DIR" \
  --frame-npz-dir "$NPZ_DIR" \
  --manifest-path "$RAW_DIR/gfs_historical_aws_manifest.json" \
  --failed-frames-path "$FAIL_LOG" \
  --max-attempts 0 \
  2>&1 | tee -a "$RUN_LOG"
