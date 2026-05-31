# windy

`windy` is a research codebase for sparse aircraft-observation wind-field
reconstruction. The current mainline is `centralized_v1`, which organizes
aircraft wind observations, aircraft trajectory/motion records, radar/cloud
context, and weak meteorological background fields into a strictly validated
3D wind reconstruction workflow.

The project is not an operational aviation wind-shear warning system. Current
results should be interpreted as research-grade 3D sparse wind reconstruction
products with strict aircraft hold-out validation.

## Current mainline

The active pipeline is:

```text
Stage1 clean source + radar index
  -> Stage2 all-in observation voxelization
  -> Stage3 Ground Center payload
  -> Stage4 strict aircraft hold-out reconstruction
  -> TimePower15 / CMA / PINN / Diffusion residual refinement
```

Do not default back to the legacy frozen Stage4/Stage5 chain unless a task
explicitly asks for historical comparison.

## Repository layout

```text
stage/centralized_v1/
  configs/
    centralized_v1_config.py
    centralized_v1_contract.py
  core/
    centralized_stage2_multimodal.py
    centralized_stage3_center.py
    centralized_stage3_acceptance.py
    centralized_stage4_ground_recon.py
    centralized_stage4_sensitivity.py
    centralized_stage4_stratified_eval.py
    centralized_stage4_error_trace.py
    centralized_report_stage4_slices.py
    centralized_training_manifest.py
    centralized_cma_ra_virtual_radial_3dvar.py

workflow/
  centralized_v1_docs/
  project_stage1_4_summaries_20260529/

stage1_output/
  clean_wind.parquet
  clean_loc.parquet
  radar_index.json
```

Large generated outputs, raw meteorological files, Excel workbooks, NPZ files,
and local runtime artifacts are ignored by Git. They live in the local working
tree, most importantly under:

```text
/data/LFT-W02_data/pengxu/centralized_v1_output
```

## Stage summary

### Stage1

Stage1 prepares stable cleaned inputs:

- `clean_wind.parquet`: AMDAR/TURB aircraft wind observations.
- `clean_loc.parquet`: aircraft location and motion records.
- `radar_index.json`: radar/cloud image time index.

Important rule: aircraft motion (`u_motion`, `v_motion`) is diagnostic only. It
is not atmospheric wind truth.

### Stage2

Stage2 is all-in observation organization, not final wind reconstruction. It
voxelizes sparse observations and context onto the Stage4 grid:

```text
z x y x = 31 x 525 x 775
lat = 12.2 .. 54.2
lon = 73.0 .. 135.0
alt = 0 .. 15000 m
vertical step = 500 m
```

For each target radar time `T`:

```text
current window = [T - 5 min, T + 5 min]
context window = [T - 360 min, T + 360 min]
```

Key Stage2 records:

- `wind_records`: current aircraft wind observations and the only Stage4
  strict hold-out truth candidates.
- `context_wind_records`: historical background wind observations used for
  fusion, not current-frame truth.
- `loc_records`: current aircraft trajectory/location voxels.
- `motion_records` and `context_motion_records`: aircraft motion diagnostics,
  not wind truth.
- `cloud_2d`: radar/cloud context for visualization and spatial support.

### Stage3

Stage3 is the Ground Center payload layer. It packages Stage2 frame records into
Stage4-consumable payloads and confidence summaries. It does not reconstruct
the final wind field and it does not use an Air-to-Air graph in the current
mainline.

### Stage4

Stage4 is the first stage that generates 3D reconstructed wind fields. Its
strict validation rule is:

```text
holdout truth = selected current-window wind_records
fusion input = non-holdout current wind_records + context_wind_records
```

Forbidden:

- hold-out wind entering fusion,
- motion records used as wind,
- context motion records used as wind,
- CMA used as aircraft truth.

Required flags:

```text
strict_holdout_no_leakage = true
motion_used_as_wind = false
```

## Current best traditional result

The current best traditional Stage4 chain is TimePower15 / candidate-v2 /
adaptive:

```text
Gaussian 8/4/2/1
diagnostic_weighted
pydda_3dvar_proxy
current_weight_boost = 2.0
context_weight_scale = 0.5
context_time_conf_power = 1.5
role_conflict_mode = current_priority_adaptive
conflict_speed_threshold_mps = 12
conflict_context_factor = 0.25
```

Full-run output:

```text
/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_full_v2_best_adaptive_all_12w_20260529
```

Headline results must be reported with stratification:

```text
all_frames_original:
  frames = 7395
  RMSE = 6.60 m/s
  MAE  = 5.81 m/s

eval_holdout_only:
  frames = 5614
  holdout points = 15054
  frame-mean RMSE = 8.696082 m/s
  frame-mean MAE  = 7.652211 m/s

no_holdout_unverified_reconstruction:
  frames = 1781
  official RMSE/MAE = blank by design
```

No-holdout frames are not failed reconstructions and are not zero-error wins.
They are retained as unverified reconstruction products and excluded from
strict RMSE/MAE.

## Aviation risk caveat

Stage4 uses a 500 m vertical grid and evaluates point `u/v` wind-vector error.
That is not numerically equivalent to the aviation reference of about 6 m/s
wind-speed difference over a 30 m vertical layer. Current point errors are in
the same order as the aviation risk threshold, so they reduce safety margin, but
the current model should not be presented as an operational 30 m wind-shear
alert system.

Future work should add:

- vertical jump metrics,
- vertical mismatch diagnostics,
- strong-layer consistency checks,
- a dedicated `wind_shear_risk_head`.

## CMA, PINN, and Diffusion

CMA/CRA40 data may be used as:

- weak background,
- pseudo-observation,
- pretraining teacher prior,
- condition input,
- physical or boundary constraint.

CMA must not be used as:

- aircraft truth,
- true 6-minute convective evolution,
- final skill metric,
- 30 m wind-shear label.

The recommended learning pattern is residual correction:

```text
F_final = F_timepower15 + delta
```

Recommended model outputs:

```text
delta_u
delta_v
uncertainty
wind_shear_risk score
```

Validation remains aircraft strict hold-out only.

## Common commands

Run full Stage2 voxelization:

```bash
cd /data/LFT-W02_data/pengxu

POLARS_MAX_THREADS=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 \
/data/LFT-W02_data/pengxu/.conda/envs/windy310/bin/python \
stage/centralized_v1/core/centralized_stage2_multimodal.py \
  --stage1-dir stage1_output \
  --out-dir centralized_v1_output/stage2_full_v2 \
  --frame-times-file centralized_v1_output/stage2_full_frame_times.json \
  --num-workers 12
```

Run full TimePower15 metrics-only Stage4 sensitivity:

```bash
ROOT=/data/LFT-W02_data/pengxu
PY=$ROOT/.conda/envs/windy310/bin/python
OUT=$ROOT/centralized_v1_output/stage4_full_v2_best_adaptive_all_12w_20260529

$PY $ROOT/stage/centralized_v1/core/centralized_stage4_sensitivity.py \
  --stage2-summary $ROOT/centralized_v1_output/stage2_full_v2/stage2_multimodal_summary.json \
  --stage3-summary $ROOT/centralized_v1_output/stage3_full_v2_8w_minimal/stage3_center_summary.json \
  --frame-times "" \
  --out-dir $OUT \
  --sample-count 0 \
  --param-grid 8,4,2,1 \
  --kernels gaussian \
  --confidence-mode diagnostic_weighted \
  --physics-constraint-mode pydda_3dvar_proxy \
  --current-weight-boost 2.0 \
  --context-weight-scale 0.5 \
  --context-time-conf-power 1.5 \
  --role-conflict-mode current_priority_adaptive \
  --conflict-speed-threshold-mps 12 \
  --conflict-context-factor 0.25 \
  --progress-interval-seconds 30 \
  --num-workers 12
```

Render ROI Stage4 slice visualizations:

```bash
ROOT=/data/LFT-W02_data/pengxu
MPLCONFIGDIR=/tmp/matplotlib /opt/miniconda3/bin/python \
  $ROOT/stage/centralized_v1/core/centralized_report_stage4_slices.py \
  --stage4-dir $ROOT/centralized_v1_output/stage4_best_adaptive_representative_visuals_20260529/recon \
  --out-dir $ROOT/centralized_v1_output/stage4_best_adaptive_representative_visuals_20260529/visuals_roi \
  --z-levels auto \
  --crop-mode bbox \
  --crop-pad 24 \
  --num-workers 6
```

## Documentation entry points

Recommended reading order:

1. `workflow/project_stage1_4_summaries_20260529/project_centralized_v1_timepower15_stage1_4_summary.md`
2. `workflow/centralized_v1_docs/new_window_project_handover_20260529/centralized_v1_full_project_handover_20260529.md`
3. `workflow/centralized_v1_docs/new_window_project_handover_20260529/centralized_v1_timepower15_full_handover.md`
4. `stage/youhua.md`
5. `workflow/centralized_v1_docs/stage2_stage3_full_process_explanation.md`
6. `workflow/centralized_v1_docs/stage4_strict_holdout_logic_and_results.md`

## Reporting rules

Always report:

- all-frame reconstruction count,
- strict holdout-only RMSE/MAE,
- no-holdout count and unverified diagnostics,
- single-holdout pressure-test subset,
- multi-holdout supported subset,
- high-error tail metrics,
- strong-wind, vertical-mismatch, and role-conflict subsets,
- leakage and `motion_used_as_wind` flags.

Never report:

- all-frame RMSE with no-holdout zeros as the main skill metric,
- CMA agreement as aircraft truth skill,
- ROI rectangle area as actual wind-field footprint,
- Stage4 PINN/Diffusion scaffolds as trained production models.
