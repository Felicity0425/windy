# centralized_v1 Stage2/Stage3/Stage4 Documentation Index

This folder is the long-term explanation and handover entry for the current
centralized_v1 Stage2/Stage3 prototype and the Stage4 strict hold-out entry.

## Recommended reading order

1. `stage2_stage3_full_process_explanation.md`
   - Full explanation of Stage1-3 calculations, Stage2, Stage3, voxelization,
     current/context windows, Ground Center, confidence fields, QC diagnostics,
     Stage4 strict hold-out design, and references.
2. `stage2_figure_20260208124800_explanation.md`
   - Detailed explanation of the Stage2 slice PNG, including colors,
     transparency, arrows, x markers, z-level counts, and figure layout.
3. `stage4_strict_holdout_logic_and_results.md`
   - Stage4 strict hold-out logic, leakage guard, Gaussian/Gaspari-Cohn
     localization, expanded 10-frame results, sensitivity table and full-run
     gate.
4. `new_window_handover_stage2_stage3.md`
   - Short handover script for a new window before continuing Stage4/Stage5.

## Current verified demo outputs

- Stage2 regenerated summary:
  `/data/LFT-W02_data/pengxu/centralized_v1_output/stage2_regenerated/stage2_multimodal_summary.json`
- Stage2 slices:
  `/data/LFT-W02_data/pengxu/centralized_v1_output/stage2_regenerated/slices`
- Stage3 Ground Center summary:
  `/data/LFT-W02_data/pengxu/centralized_v1_output/stage3_center/stage3_center_summary.json`
- Stage3 Ground Center reports:
  `/data/LFT-W02_data/pengxu/centralized_v1_output/stage3_center/reports`
- Stage3 expanded 10-frame summary:
  `/data/LFT-W02_data/pengxu/centralized_v1_output/stage3_center_expanded/stage3_center_summary.json`
- Stage4 strict hold-out output:
  `/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_center_strict`
- Stage4 strict expanded output:
  `/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_center_strict_expanded`
- Stage4 localization sensitivity table:
  `/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_center_strict_expanded/sensitivity/stage4_localization_sensitivity.csv`
- Stage4 strict slices:
  `/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_center_strict/slices`
- Stage2 visual encoding charts:
  `/data/LFT-W02_data/pengxu/centralized_v1_output/stage2_regenerated/slices/stage2_visual_encoding_<time>.png`
- Stage4 diagnostic charts:
  `/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_center_strict/slices/<time>_centralized_stage4_diagnostics.png`

## Data sources

Stage2/Stage3 currently use:

```text
stage1_output/clean_wind.parquet
stage1_output/clean_loc.parquet
stage1_output/radar_index.json
radar PNG mosaics from radar_index.json.radar_path
```

The radar PNG paths point to the project weather-radar mosaic files, for
example:

```text
/data/LFT-W02_data/pengxu/20260224/radar/Z_RADA_*.png
```

## Current stage boundary

Stage2 is all-in observation organization. Stage3 is Ground Center intake and
confidence packaging. Neither stage reconstructs the final wind field.

Current Stage4 entry:

```text
Stage4 strict hold-out + observation-to-target-voxel localization + point eval
```

Verified two-frame strict result:

```text
20260208124800:
  hold-out = 15 / 114 current wind voxels
  pre-refine voxels = 276198
  final voxels = 417438
  final domain fraction = 3.309553%
  bbox = lat 17.240-36.760, lon 106.360-118.280, alt 0-15000 m
  diffusion fill = 141240
  RMSE vector = 6.468737 m/s
  MAE vector = 5.422913 m/s

20260211060600:
  hold-out = 1 / 1 current wind voxels
  pre-refine voxels = 217861
  final voxels = 339248
  final domain fraction = 2.689643%
  bbox = lat 19.000-37.480, lon 106.920-118.200, alt 500-15000 m
  diffusion fill = 121387
  RMSE vector = 3.390634 m/s
  MAE vector = 3.390634 m/s
  note = sparse-label pressure test, context-wind-only fusion
```

Verified expanded strict run:

```text
10 frames in /data/LFT-W02_data/pengxu/centralized_v1_output/stage4_center_strict_expanded
60-row sensitivity table in stage4_center_strict_expanded/sensitivity
strict_holdout_no_leakage = true for all expanded/sensitivity rows
motion_used_as_wind = false
mask_conf_positive_mismatch_voxels = 0 for all expanded Stage4 rows
```

The strict Stage4 footprint is not a dense nationwide wind analysis. It is the
effective support defined by `recon_mask_3d > 0`, with observation-supported
voxels and low-confidence fill shown separately in the refreshed slice figures.

Do not run full Stage2/Stage3/Stage4 yet. The current recommendation is to
review the expanded 10-frame metrics and Gaussian/Gaspari-Cohn sensitivity
before any full rerun.

## Stage1-3 gate

Current conclusion:

```text
Stage1 = pass as cleaned source and radar index preparation.
Stage2 = pass as all-in observation organization.
Stage3 = pass as Ground Center intake and confidence package.
```

They can be temporarily frozen for the small-batch demo. Freeze means keeping
the current data contracts stable while Stage4 is built and tested; it does not
forbid later QC tuning or full reruns.
