# windy / centralized_v1

Research code for **sparse aircraft-observation 3D horizontal wind-field reconstruction**. The project combines AMDAR/TURB wind reports, ADS-B trajectory evidence, radar time-space organization, and weak meteorological background fields under strict aircraft holdout validation.

> This is a research repository, not an operational aviation warning system. `support-only`, pseudo-validation, graph candidates, display fills, and report-only diagnostics must not be interpreted as official truth or operational forecasts.

## Current status

The latest verified optimization results are from July 2026; the latest visible report-only representation-error diagnostic is from June 2026. No newer formal full-scale experiment is present in the local project tree as of `2026-09-11`.

| Area | Latest verified result | Status |
|---|---:|---|
| Stage2 v8 ADS-B track graph | `19,162,638` input points, `19,154,894` clean points, `11,306` physical candidate edges | quality gates passed; edges remain priors |
| Stage3 v13 bridge validation | `27,599` locked cases, wrong path `0.0827%`, ECE `0.000321` | all hard gates passed |
| Stage5 v7 calibrated partial matching | `229` unique batches / `345` matched rows | safety and merge gates passed |
| Stage4 strict holdout baseline | `200` frames / `530` holdout points, vector RMSE `14.7690 m/s` | official comparison baseline |
| High-altitude stratum | `12 km+` vector RMSE about `20.012 m/s` | primary unresolved risk |
| Official OI / graph full merge | not completed | do not promote yet |

## Main idea

```text
raw aircraft / radar inputs
  -> Stage1 semantic QC and unit normalization
  -> Stage2 observation organization and ADS-B track graph
  -> Stage3 independent pseudo/corruption/bridge validation
  -> Stage4 confidence tiers and strict aircraft holdout reconstruction
  -> Stage5 sequence matching and calibrated partial matching
  -> Stage6 sensitivity and official promotion checks
```

Important semantic rules:

- AMDAR batch timestamps are not automatically point-observation truth.
- ADS-B location and motion are trajectory evidence, not atmospheric wind truth.
- `graph edge` means a candidate connection, not an accepted match.
- CMA/CRA40 is currently display/reference background; it is not proven independent of the holdout.
- GFS is the preferred candidate for constrained background diagnostics, not yet an official blend.
- Official accuracy is evaluated on strict aircraft holdout points only.

## Repository layout

```text
stage/
  centralized_v1/core/       Original centralized_v1 Stage1-5 implementation
  optimization/              Latest Stage2 v8 / Stage3 v12-v13 / Stage4 v3 / Stage5 v6-v7 scripts
  *.py                       Data preparation, reconstruction, background and reporting utilities

docs/
  centralized_v1_latest_results_summary_20260911.md
  results/                   Latest formal optimization reports and compact JSON artifacts
  baselines/                 Original Stage4, OI, representation-error and PINN comparisons

workflow/
  wiki/                      Curated methodology and literature notes
  centralized_v1_docs/      Compact pipeline explanations

stage1_output/
  *.json                     Lightweight manifests and dataset summaries
  *.parquet                  Local-only data; intentionally not distributed in the repository
```

Large raw inputs, GRIB files, Excel workbooks, Parquet data, NPZ fields, generated images, shard-level logs, and temporary runtime outputs are intentionally excluded from the GitHub working tree. They remain available in the local project workspace when needed.

## Key documentation

- [Latest full project summary](docs/centralized_v1_latest_results_summary_20260911.md)
- [Stage2 v8 / Stage3 v13 detailed explanation](docs/results/stage2_stage3_v8_v13_explanation.md)
- [Stage3 / Stage5 track-graph weekly report](docs/results/stage3_stage5_track_graph_weekly_report.md)
- [Stage2 v8 formal result](docs/results/stage2_v8_results.md)
- [Stage3 v13 formal result](docs/results/stage3_v13_results.md)
- [Stage5 v7 formal result](docs/results/stage5_v7_results.md)
- [Original Stage4 strict-holdout comparison](docs/baselines/stage4_three_method_compare.md)
- [Stage4 OI diagnostic boundary](docs/baselines/stage4_oi_diagnostic.md)
- [Stage4 representation-error diagnostic](docs/baselines/stage4_representation_error_report.md)
- [Stage5 residual/PINN baseline](docs/baselines/stage5_pinn_dataset.md)

## Latest optimization code

The latest optimization scripts are collected under `stage/optimization/`:

- `amdar_unified_stage0_stage1_stage2_optimization_20260701.py`
- `amdar_unified_stage2_v8_track_graph_20260716.py`
- `amdar_unified_stage3_v12_drop_dtw_20260716.py`
- `amdar_unified_stage3_v13_bridge_validation_20260716.py`
- `amdar_unified_stage4_confidence_v3_next_window_20260708.py`
- `amdar_unified_stage5_v6_hmm_viterbi_20260715.py`
- `amdar_unified_stage5_v7_calibrated_partial_20260716.py`
- `amdar_unified_stage6_time_uncertainty_20260701.py`

The original Stage1-4 pipeline remains under `stage/centralized_v1/core/` for historical reproduction and baseline comparison.

## Reproduction boundary

The repository contains source code and compact manifests, not the private/raw observation corpus. A local reproduction requires the project data workspace and the appropriate Python environment. Typical inputs are:

```text
stage1_output/clean_wind.parquet
stage1_output/clean_loc.parquet
stage1_output/radar_index.json
stage1_output/frame_window_index.json
```

Do not use aircraft motion as wind, do not use holdout rows in fusion, and do not promote graph candidates or display-only background fields without a new strict holdout experiment.

## Next authorized experiments

1. Freeze Stage5 v7 `229/345` as a regression set.
2. Run a small Stage5 v8 graph audit with `unique`, `mixture`, and `reject` outputs separated.
3. Compare Stage6 S0-S4 on the same strict aircraft holdout.
4. Run GFS constrained OI B0-B3 with an explicit background-independence audit.
5. Analyze the `12 km+` representation-error and localization failure modes.
6. Promote only when weighted RMSE, tail risk, light-wind behavior, high-altitude metrics, and leakage gates all pass.

## License and data note

This repository is an internal research snapshot. Raw aviation observations and downloaded meteorological fields are not redistributed here. Check the source data terms and local project policy before sharing derived artifacts.
