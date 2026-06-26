# S4 OI diagnostic report

- Generated: `2026-06-26T09:04:18.314972Z`
- Background dir: `/data/LFT-W02_data/pengxu/优化/stage4_cma_m1_light_demo_20260625/gfs_historical_aws_200/npz`
- Stage2 summary: `centralized_v1_output/stage2_full_v2/stage2_multimodal_summary.json`
- Frame count: `200`

## Train Innovation

- Rows inside background ROI: `154332`
- Rows outside background ROI: `0`
- Overall vector RMSE: `39.340049` m/s
- Overall vector MAE: `33.891837` m/s
- Mean obs_influence_proxy: `0.172186`

## Holdout Background

- Strict holdout rows inside background ROI: `530`
- Strict holdout rows outside background ROI: `0`
- Overall vector RMSE: `35.233698` m/s
- Overall vector MAE: `29.786583` m/s
- Departures join hit rate: `1.000000`

## Recommendation

- Summary: `GFS is usable as a diagnostic/weak background, but high-risk strata remain and official OI should stay constrained.`
- Next step: `Proceed only with constrained S4-OI-1a/1b style experiments, protect light wind and treat high-risk strata conservatively.`
- High-risk strata: `['12km+', '6-9km', '9-12km', 'count_0', 'count_1', 'count_ge2', 'gap_10_30', 'gap_ge30', 'gap_lt10']`
- Conditionally usable strata: `['0-3km', '3-6km']`
