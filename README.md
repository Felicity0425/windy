# windy

`windy` is a research codebase for sparse aircraft-observation wind-field
reconstruction. The current mainline is `centralized_v1`, which organizes
aircraft wind observations, aircraft trajectory/motion records, radar/cloud
context, and weak meteorological background fields into a strictly validated
3D wind reconstruction workflow.

This repository is not an operational aviation warning system. Current outputs
should be interpreted as research-grade sparse 3D wind reconstruction products
under strict aircraft hold-out validation.

## Current status

As of `2026-06-26`, the project has completed a new Stage4 audit-and-handoff
round focused on:

- `CMA/CRA40` data verification
- background-independence (`P0-LEAK`) audit
- Stage4 error-floor estimation
- `S4-CMA-M1` display-only weak-background product branch
- `GFS forecast` historical background acquisition for the next `OI` line

The practical state is:

- `CMA-RA` is treated as a **reanalysis / analysis product**, not a pure
  independent forecast background.
- `CMA` is currently safe for **display-only weak background fill**, but not
  yet cleared as the main background for `OI / innovation / Desroziers`
  claims.
- `GFS forecast` is the current preferred candidate background for the next
  `S4-OI-DIAG` stage.
- The `200`-frame `GFS` historical background set is now complete:
  `178/178` unique sources, `200/200` frame NPZs, `failed_count = 0`.

## Current mainline

The active workflow is:

```text
Stage1 clean source + radar index
  -> Stage2 all-in observation voxelization
  -> Stage3 Ground Center payload
  -> Stage4 strict aircraft hold-out reconstruction
  -> Stage4 product / background branches
  -> optional Stage5 residual refinement (not current default)
```

The current near-term Stage4 execution order is:

```text
P0-FRAME   input format check
P0-LEAK    background independence audit
P0-CMA     CMA/CRA40 readability and coverage audit
P0-FLOOR   practical error-floor estimate
P0-GFS     historical forecast background acquisition + verification
S4-CMA-M1  display-only low-confidence background fill
S4-OI-DIAG report-only innovation / obs_influence diagnostics
S4-OI-*    only after background diagnostics support it
```

Do not default back to older frozen Stage4/Stage5 chains unless the task is
explicitly historical comparison.

## Repository layout

```text
stage/centralized_v1/
  core/
    centralized_stage2_multimodal.py
    centralized_stage3_center.py
    centralized_stage4_ground_recon.py
    centralized_stage4_sensitivity.py
    centralized_stage4_stratified_eval.py
    centralized_stage4_error_trace.py
    centralized_stage4_error_floor_estimate.py
    verify_cma_grib.py
    centralized_cma_ra_virtual_radial_3dvar.py

stage/
  download_stage5_gfs_aws_historical_roi.py
  download_stage5_gfs_aws_cached_batch.py

workflow/
  centralized_v1_docs/
  plan/

优化/
  stage4_cma_m1_light_demo_20260625/
```

Large generated outputs, raw GRIB files, frame NPZs, Excel workbooks, and
local runtime artifacts are not intended to be fully versioned in Git. Most
large local outputs live under:

```text
/data/LFT-W02_data/pengxu/centralized_v1_output
/data/LFT-W02_data/pengxu/优化
```

## Stage summary

### Stage1

Stage1 prepares stable cleaned inputs:

- `clean_wind.parquet`: AMDAR/TURB aircraft wind observations
- `clean_loc.parquet`: aircraft location and motion records
- `radar_index.json`: radar/cloud image time index

Important rule:

```text
aircraft motion (u_motion, v_motion) is diagnostic only
it is not atmospheric wind truth
```

### Stage2

Stage2 is all-in observation organization, not final wind reconstruction. It
voxelizes sparse observations and context onto the Stage4 grid.

Key Stage2 records:

- `wind_records`: the only strict hold-out truth candidates for Stage4
- `context_wind_records`: historical support observations, not current truth
- `loc_records`: aircraft trajectory/location voxels
- `motion_records`: motion diagnostics, not wind truth
- `cloud_2d`: radar/cloud context for visualization and spatial support

### Stage3

Stage3 is the Ground Center payload layer. It packages Stage2 frame records
into Stage4-consumable payloads and confidence summaries. It does not produce
the final 3D wind field.

### Stage4

Stage4 is the first stage that generates 3D reconstructed wind fields.

Its strict validation rule is:

```text
holdout truth = selected current-window wind_records
fusion input  = non-holdout current wind_records + context_wind_records
```

Forbidden:

- hold-out wind entering fusion
- motion records used as wind
- context motion used as wind
- CMA used as aircraft truth

Required flags:

```text
strict_holdout_no_leakage = true
motion_used_as_wind = false
```

## Current audited baseline

The current `200`-frame Stage4 smoke baseline has been reproduced under a
lightweight `25`-worker metrics-only run:

```text
holdout points        = 530
vector RMSE           = 14.7690 m/s
vector MAE            = 6.8545 m/s
frame mean RMSE       = 8.2243 m/s
frame P95 RMSE        = 27.9861 m/s
frame P99 RMSE        = 58.7838 m/s
12km+ RMSE            = 19.9177 m/s
light-wind RMSE       = 5.1959 m/s
floor10 relative MAE  = 0.2828
```

See:

- [优化/stage4_cma_m1_light_demo_20260625/reports/demo_summary_20260625.json](优化/stage4_cma_m1_light_demo_20260625/reports/demo_summary_20260625.json)
- [优化/stage4_cma_m1_light_demo_20260625/stage4_cma_m1_light_demo_20260625_summary.md](优化/stage4_cma_m1_light_demo_20260625/stage4_cma_m1_light_demo_20260625_summary.md)

## CMA and GFS roles

The repository currently distinguishes background roles carefully:

### `CMA-RA / CRA40`

Use cases:

- display-only weak background fill
- reference large-scale field
- product completeness branch

Do not currently use as:

- strict independent `OI` background
- direct `innovation` / `Desroziers` background for formal claims

Reason:

```text
CMA-RA is a reanalysis / analysis product
it may be closer to reality than forecast background
but background independence from project holdout observations is not proven
```

### `GFS forecast`

Use cases:

- candidate independent background
- `S4-OI-DIAG` innovation diagnostics
- future `oi_diag_approx / local_oi` experiments

Current downloaded set:

```text
horizontal resolution ~ 0.25 degree
levels currently extracted = 1000 ... 200 hPa
u/v background only
200/200 target frames completed
```

Current note:

```text
the downloaded GFS set is sufficient for first-stage OI diagnostics
but the present default extraction tops out near 200 hPa (~11.8 km)
so a later 150/100 hPa refresh may be useful for deeper 12km+ analysis
```

## Why background matters in this project

The purpose of background fields here is not to replace aircraft observations.
It is to support reconstruction where observations are sparse, especially:

- `12km+`
- `count_0 / count_1`
- `dist_ge6km`
- `gap_ge30`
- moderate `time_conf` risk layers

The intended role is:

```text
observations constrain where they are strong
background stabilizes where observations are weak
```

This is why the repository now separates:

- `display-only background fill`
- `report-only innovation diagnostics`
- possible later `OI` official-branch experiments

## New scripts added in the current round

### CMA / floor audit

- `stage/centralized_v1/core/verify_cma_grib.py`
- `stage/centralized_v1/core/centralized_stage4_error_floor_estimate.py`

### GFS background pipeline

- `stage/download_stage5_gfs_aws_cached_batch.py`
- `workflow/plan/stage4_gfs_historical_background_200_20260625.sh`

### Stage4 product demo

- `workflow/plan/stage4_cma_m1_light_demo_20260625.sh`
- `workflow/plan/stage4_cma_m1_representative_frames_20260625.txt`

## Documentation entry points

Recommended reading order for the current state:

1. [workflow/plan/plan_0625_executable.md](workflow/plan/plan_0625_executable.md)
2. [优化/stage4_cma_m1_light_demo_20260625/stage4_cma_m1_light_demo_20260625_summary.md](优化/stage4_cma_m1_light_demo_20260625/stage4_cma_m1_light_demo_20260625_summary.md)
3. [优化/stage4_cma_m1_light_demo_20260625/reports/cma_independence_report.md](优化/stage4_cma_m1_light_demo_20260625/reports/cma_independence_report.md)
4. [优化/stage4_cma_m1_light_demo_20260625/reports/stage4_error_floor_estimate.md](优化/stage4_cma_m1_light_demo_20260625/reports/stage4_error_floor_estimate.md)
5. [优化/stage4_cma_m1_light_demo_20260625/weekly_report_20260625.md](优化/stage4_cma_m1_light_demo_20260625/weekly_report_20260625.md)
6. [workflow/centralized_v1_docs/new_window_project_handover_20260529/README.md](workflow/centralized_v1_docs/new_window_project_handover_20260529/README.md)

## Current next steps

The current recommended next execution path is:

1. verify the completed `GFS` background set with a dedicated
   `verify_gfs_background` report
2. run `S4-OI-DIAG` with `GFS forecast` as the background
3. finish `S4-CMA-M1` full-200 pairwise sealing if product-branch proof is
   needed
4. only then decide whether `local_oi` is worth implementing

## Reporting rules

Always report:

- strict hold-out-only RMSE/MAE
- no-holdout frame count separately
- high-error tail metrics
- `12km+` metrics
- light-wind metrics
- leakage and `motion_used_as_wind` flags
- whether a branch is `official`, `display-only`, or `report-only`

Never report:

- CMA agreement as aircraft truth skill
- all-frame RMSE with no-holdout zeros as the main skill metric
- background-filled display area as official reconstruction skill
- a reanalysis background as an independent OI background without proof

## Safety / interpretation caveat

Stage4 uses a `500 m` vertical grid and evaluates point `u/v` vector error.
That is not numerically equivalent to an operational aviation wind-shear alert
metric defined over much finer vertical layers.

This codebase should therefore be described as:

```text
research-grade sparse 3D wind-field reconstruction with strict aircraft hold-out validation
```

and not as a deployed operational hazard-warning system.
