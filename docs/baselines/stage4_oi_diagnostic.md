# Stage4 OI Diagnostic Report

## Scope

- Mode: `S4-OI-DIAG`, report-only.
- No 3D reconstruction NPZ files are written.
- Official `recon_u/v/conf/mask` and point-eval logic are unchanged.
- Train current aircraft observations are used for OMB reliability diagnostics; holdout rows are report-only side evidence.

## Run

- Frames: 200/200 ok
- Train current points: 2928
- Holdout report-only points: 530
- CMA proxy dir: `/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_three_method_compare_20260531/cma_proxy`
- Baseline Stage4 frame RMSE mean: 8.224309 m/s

## OMB Summary

| role | valid | RMSE | MAE | P95 | P99 | mean OI influence at obs |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| train_current | 2358 | 38.628995 | 33.414103 | 66.807629 | 91.012857 | 0.315225 |
| holdout_report_only | 431 | 34.615552 | 28.592272 | 66.242764 | 85.565591 | 0.327629 |

## Recommendation

- Decision: `report_only_do_not_promote_to_m2`.
- Reason: background_independent_of_holdout is not confirmed.
- Reason: S4-OI-DIAG is diagnostics-only and does not modify official recon.
- Reason: train OMB RMSE is 4.70x the Stage4 baseline frame RMSE.
- Reason: train OMB P95 is high (66.808 m/s).

## Outputs

- `oi_diag_frame_summary.csv`
- `oi_diag_point_departures.csv`
- `oi_diag_stratified_summary.csv`
- `oi_diag_summary.json`
