#!/usr/bin/env bash
set -euo pipefail

PY="/data/LFT-W02_data/pengxu/.conda/envs/windy310/bin/python"
ROOT="/data/LFT-W02_data/pengxu"
cd "$ROOT"

STAGE2="centralized_v1_output/stage2_full_v2/stage2_multimodal_summary.json"
FRAMES200="centralized_v1_output/stage4_guardrail_display_fill_200_20260605_25w/tp26_thr11_preserve_metrics/stage4_validation_frame_times.txt"
DEPARTURES="centralized_v1_output/stage4_guardrail_display_fill_200_20260605_25w/tp26_thr11_preserve_metrics/stage4_point_departures.csv"
GFS_ROOT="$ROOT/优化/stage4_cma_m1_light_demo_20260625/gfs_historical_aws_200"
GFS_FRAME_DIR="$GFS_ROOT/npz"
GFS_CACHE_DIR="$GFS_ROOT/cache_npz"
GFS_MANIFEST="$GFS_ROOT/raw_grib/gfs_historical_aws_manifest.json"
GFS_FAILED="$GFS_ROOT/failed_frames.txt"

OUT_ROOT="$ROOT/优化/stage4_gfs_oi_diag_20260626"
REPORT_DIR="$OUT_ROOT/reports"
LOG_DIR="$OUT_ROOT/logs"
mkdir -p "$REPORT_DIR" "$LOG_DIR"

echo "[1/2] verify GFS background inventory"
"$PY" stage/centralized_v1/core/verify_gfs_background.py \
  --background-dir "$GFS_FRAME_DIR" \
  --cache-dir "$GFS_CACHE_DIR" \
  --manifest-path "$GFS_MANIFEST" \
  --failed-frames-path "$GFS_FAILED" \
  --frame-times-file "$FRAMES200" \
  --out-json "$REPORT_DIR/gfs_background_verify_report_200.json" \
  --out-md "$REPORT_DIR/gfs_background_verify_report_200.md" \
  >"$LOG_DIR/01_verify_gfs_background.log" 2>&1

echo "[2/2] run report-only S4 OI diagnostics against GFS"
"$PY" stage/centralized_v1/core/centralized_stage4_oi_diag_report.py \
  --stage2-summary "$STAGE2" \
  --frame-times-file "$FRAMES200" \
  --background-dir "$GFS_FRAME_DIR" \
  --departures-csv "$DEPARTURES" \
  --out-json "$REPORT_DIR/s4_oi_diag_gfs_200.json" \
  --out-md "$REPORT_DIR/s4_oi_diag_gfs_200.md" \
  --out-train-strata-csv "$REPORT_DIR/s4_oi_diag_gfs_200_train_strata.csv" \
  --out-holdout-strata-csv "$REPORT_DIR/s4_oi_diag_gfs_200_holdout_strata.csv" \
  --holdout-fraction 0.125 \
  --holdout-count 0 \
  --confidence-mode diagnostic_weighted \
  --current-weight-boost 2.0 \
  --context-weight-scale 0.5 \
  --context-time-conf-power 2.6 \
  --background-reference-weight 0.20 \
  >"$LOG_DIR/02_s4_oi_diag_gfs_200.log" 2>&1

echo "done: $OUT_ROOT"
