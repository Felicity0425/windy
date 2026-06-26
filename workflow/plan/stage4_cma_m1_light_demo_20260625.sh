#!/usr/bin/env bash
set -euo pipefail

PY="/data/LFT-W02_data/pengxu/.conda/envs/windy310/bin/python"
ROOT="/data/LFT-W02_data/pengxu"
cd "$ROOT"

STAGE2="centralized_v1_output/stage2_full_v2/stage2_multimodal_summary.json"
STAGE3="centralized_v1_output/stage3_full_v2_25w_payload_only/stage3_center_summary.json"
FRAMES200="centralized_v1_output/stage4_guardrail_display_fill_200_20260605_25w/tp26_thr11_preserve_metrics/stage4_validation_frame_times.txt"
FRAMES5614="centralized_v1_output/stage4_full_tp26_thr11_preserve_25w_taildiag_20260602_173319/stage4_holdout_only_frame_times_5614.txt"
CMA_DIR="$ROOT/cma"
REP_FRAMES_FILE="$ROOT/workflow/plan/stage4_cma_m1_representative_frames_20260625.txt"
REP_FRAMES_CSV="$(paste -sd, "$REP_FRAMES_FILE")"

OUT_ROOT="$ROOT/优化/stage4_cma_m1_light_demo_20260625"
REPORT_DIR="$OUT_ROOT/reports"
LOG_DIR="$OUT_ROOT/logs"
BASE_DIR="$OUT_ROOT/tp26_metrics_only_200_25w"
REP_CMA_DIR="$OUT_ROOT/representative_cma_proxy"
REP_STAGE4_DIR="$OUT_ROOT/representative_stage4_display_fill"
REP_VIS_DIR="$OUT_ROOT/representative_visuals"

mkdir -p "$REPORT_DIR" "$LOG_DIR" "$BASE_DIR" "$REP_CMA_DIR" "$REP_STAGE4_DIR" "$REP_VIS_DIR"

echo "[1/7] verify CMA inventory and GRIB readability"
"$PY" stage/centralized_v1/core/verify_cma_grib.py \
  --cma-dir "$CMA_DIR" \
  --frame-times-file "$FRAMES200" \
  --frame-times-file "$FRAMES5614" \
  --out-json "$REPORT_DIR/cma_grib_verify_report.json" \
  >"$LOG_DIR/01_verify_cma_grib.log" 2>&1

cat > "$REPORT_DIR/cma_independence_report.md" <<'EOF'
# CMA independence report

- Manual URL: `https://data.cma.cn/article/showPDFFile.html?file=/pic/static/doc/cra/%E4%B8%AD%E5%9B%BD%E6%B0%94%E8%B1%A1%E5%B1%80%E5%85%A8%E7%90%83%E5%A4%A7%E6%B0%94%EF%BC%8F%E9%99%86%E9%9D%A2%E5%86%8D%E5%88%86%E6%9E%90%E4%BA%A7%E5%93%81%EF%BC%88CMA-RA%EF%BC%89%E7%94%A8%E6%88%B7%E6%89%8B%E5%86%8C.pdf`
- Manual revision date: `2022-04-25`.
- Manual wording: CMA-RA is a reanalysis product family built from observations, numerical modeling, and data assimilation.
- Local files: `CRA40_*_GLB_34KM_HOUR_V1_0_0.grib2?...&dataCode=NAFP_CRA40_FTM_6HOR...`, covering `2026-01-23 00Z` to `2026-02-24 00Z`.

## Conclusion

- `S4-CMA-M1` display-only fill is safe to run now because official `recon_u/v/conf/mask` and strict holdout metrics remain untouched.
- `S4-OI-*` and innovation / Desroziers statistics remain blocked until the data provider confirms whether this 2026 `FTM` extension is independent of the strict-holdout aircraft winds.
- Working assumption for this demo: `background_independent_of_holdout = false` for OI-grade claims, but acceptable for M1 product-only usage.
EOF

echo "[2/7] estimate Stage4 error-floor band"
"$PY" stage/centralized_v1/core/centralized_stage4_error_floor_estimate.py \
  --point-csv "centralized_v1_output/stage4_guardrail_display_fill_200_20260605_25w/tp26_thr11_preserve_metrics/stage4_point_departures.csv" \
  --out-json "$REPORT_DIR/stage4_error_floor_estimate.json" \
  --out-md "$REPORT_DIR/stage4_error_floor_estimate.md" \
  >"$LOG_DIR/02_error_floor.log" 2>&1

echo "[3/7] run 200-frame tp26 metrics-only baseline with 25 workers"
POLARS_MAX_THREADS=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 \
"$PY" stage/centralized_v1/core/centralized_stage4_sensitivity.py \
  --stage2-summary "$STAGE2" \
  --stage3-summary "$STAGE3" \
  --frame-times-file "$FRAMES200" \
  --out-dir "$BASE_DIR" \
  --param-grid 8,4,2,1 \
  --kernels gaussian \
  --confidence-mode diagnostic_weighted \
  --physics-constraint-mode pydda_3dvar_proxy \
  --localization-policy diagnostic_adaptive_v3 \
  --localization-candidate-grid 8:4,10:5 \
  --current-weight-boost 2.0 \
  --context-weight-scale 0.5 \
  --context-time-conf-power 2.6 \
  --role-conflict-mode current_priority_adaptive \
  --conflict-speed-threshold-mps 11.0 \
  --conflict-context-factor 0.25 \
  --vertical-risk-mode preserve_strong_layers \
  --vertical-localization-policy fixed \
  --vertical-gradient-preserve-weight 0.12 \
  --vertical-context-mismatch-damping 0.35 \
  --progress-interval-seconds 30 \
  --num-workers 25 \
  >"$LOG_DIR/03_tp26_metrics_only_200_25w.log" 2>&1

echo "[4/7] build CMA proxy only for representative frames"
"$PY" stage/centralized_v1/core/centralized_cma_ra_virtual_radial_3dvar.py \
  --cma-dir "$CMA_DIR" \
  --stage2-summary "$STAGE2" \
  --frame-times-file "$REP_FRAMES_FILE" \
  --cma-time-method linear_qc \
  --aircraft-anchor-mode stage4_train_wind \
  --stage4-holdout-fraction 0.125 \
  --stage4-holdout-count 0 \
  --out-dir "$REP_CMA_DIR" \
  --sample-stride 48 \
  --num-workers 6 \
  >"$LOG_DIR/04_representative_cma_proxy.log" 2>&1

echo "[5/7] run display-only M1 on representative frames"
"$PY" stage/centralized_v1/core/centralized_stage4_ground_recon.py \
  --stage2-summary "$STAGE2" \
  --stage3-summary "$STAGE3" \
  --frame-times-file "$REP_FRAMES_FILE" \
  --localization-policy diagnostic_adaptive_v3 \
  --localization-candidate-grid 8:4,10:5 \
  --confidence-mode diagnostic_weighted \
  --physics-constraint-mode pydda_3dvar_proxy \
  --current-weight-boost 2.0 \
  --context-weight-scale 0.5 \
  --context-time-conf-power 2.6 \
  --role-conflict-mode current_priority_adaptive \
  --conflict-speed-threshold-mps 11.0 \
  --conflict-context-factor 0.25 \
  --vertical-risk-mode preserve_strong_layers \
  --vertical-localization-policy fixed \
  --vertical-gradient-preserve-weight 0.12 \
  --vertical-context-mismatch-damping 0.35 \
  --cma-fusion-mode off \
  --background-independent-of-holdout false \
  --display-fill-mode low_conf_background \
  --display-fill-cma-proxy-dir "$REP_CMA_DIR" \
  --display-fill-source cma_reanalysis \
  --display-fill-confidence-cap 0.20 \
  --display-fill-qc-gating strict_temporal \
  --out-dir "$REP_STAGE4_DIR" \
  --num-workers 6 \
  >"$LOG_DIR/05_representative_stage4_m1.log" 2>&1

echo "[6/7] render representative display-filled slices"
"$PY" stage/centralized_v1/core/centralized_report_stage4_slices.py \
  --stage4-dir "$REP_STAGE4_DIR" \
  --frame-times "$REP_FRAMES_CSV" \
  --out-dir "$REP_VIS_DIR" \
  --field-mode display_filled \
  --crop-mode bbox \
  --crop-pad 24 \
  --z-levels 5,17,29 \
  --num-workers 6 \
  >"$LOG_DIR/06_representative_visuals.log" 2>&1

echo "[7/7] write M1 checklist summary"
"$PY" - <<'PY' >"$LOG_DIR/07_m1_checklist.log" 2>&1
import glob
import json
from pathlib import Path
import numpy as np

root = Path("/data/LFT-W02_data/pengxu/优化/stage4_cma_m1_light_demo_20260625")
base_dir = root / "tp26_metrics_only_200_25w"
rep_dir = root / "representative_stage4_display_fill"
out_path = root / "reports" / "m1_promotion_checklist.json"

items = []
for path in sorted(rep_dir.glob("frame_*_center_strict.npz")):
    with np.load(path, allow_pickle=False) as z:
        diag = {}
        if "stage4_display_fill_diagnostics_json" in z.files:
            diag = json.loads(str(z["stage4_display_fill_diagnostics_json"]))
        items.append(
            {
                "frame_npz": str(path),
                "time_str": str(z["time_str"]) if "time_str" in z.files else path.stem,
                "display_background_voxels": int(diag.get("display_background_voxels", 0)),
                "display_active_voxels": int(diag.get("display_active_voxels", 0)),
                "display_background_confidence_max": float(diag.get("display_background_confidence_max", 0.0)),
                "display_source_code_2": str(diag.get("display_source_code_2", "")),
            }
        )

payload = {
    "baseline_metrics_dir": str(base_dir),
    "baseline_metrics_csv": str(base_dir / "stage4_localization_sensitivity_aggregate.csv"),
    "baseline_point_departures_csv": str(base_dir / "stage4_point_departures.csv"),
    "representative_frame_count": len(items),
    "representative_items": items,
    "official_metrics_rule": "M1 is display-only. Official strict-holdout metrics remain those from the metrics-only tp26 run because recon_u/v/conf/mask were not modified.",
    "display_value_rule": "Representative frames must show display_source=2 only in low-confidence background-filled voxels with display_conf <= 0.20.",
}
out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
print(out_path)
PY

echo "done: $OUT_ROOT"
