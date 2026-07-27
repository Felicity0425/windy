# Stage4 Stratified Evaluation

Official RMSE/MAE comes only from `eval_holdout_only` and its holdout subsets. `no_holdout_unverified_reconstruction` keeps coverage and risk diagnostics but does not contribute to official error metrics.

- expected frames: `0`
- validation failures: `0`

| stratum | official | frames | holdout points | frame RMSE | frame MAE | weighted RMSE | weighted MAE | mean effective voxels | mean low-conf fill | leakage | motion used |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| `all_frames_original` | `False` | 6 | 15 |  |  |  |  | 188507.333333 | 86012.333333 | `True` | `False` |
| `eval_holdout_only` | `True` | 6 | 15 | 8.528311 | 7.902275 | 12.970742 | 8.717542 | 188507.333333 | 86012.333333 | `True` | `False` |
| `no_holdout_unverified_reconstruction` | `False` | 0 | 0 |  |  |  |  |  |  | `True` | `False` |
| `single_holdout_pressure_test` | `True` | 3 | 3 | 7.893026 | 7.893026 | 9.187989 | 7.893026 | 173110.000000 | 82067.666667 | `True` | `False` |
| `multi_holdout_supported` | `True` | 3 | 12 | 9.163596 | 7.911524 | 13.754832 | 8.923672 | 203904.666667 | 89957.000000 | `True` | `False` |
| `multi_holdout_ge3` | `True` | 2 | 10 | 11.749303 | 9.935819 | 14.961516 | 9.935819 | 203850.500000 | 89744.000000 | `True` | `False` |
| `rmse_le6` | `True` | 4 | 9 | 3.904192 | 3.828951 | 3.409230 | 3.159734 | 183714.000000 | 83307.250000 | `True` | `False` |
| `rmse_gt6` | `True` | 2 | 6 | 17.776550 | 16.048922 | 20.078996 | 17.054254 | 198094.000000 | 91422.500000 | `True` | `False` |
| `strong_wind_subset` | `True` | 6 | 15 | 8.528311 | 7.902275 | 12.970742 | 8.717542 | 188507.333333 | 86012.333333 | `True` | `False` |
| `vertical_mismatch_subset` | `True` | 6 | 15 | 8.528311 | 7.902275 | 12.970742 | 8.717542 | 188507.333333 | 86012.333333 | `True` | `False` |
| `all_frames_original` | `False` | 2 | 4 |  |  |  |  | 260143.000000 | 103868.500000 | `True` | `False` |
| `eval_holdout_only` | `True` | 2 | 4 | 2.413219 | 2.277340 | 2.220525 | 1.981266 | 260143.000000 | 103868.500000 | `True` | `False` |
| `no_holdout_unverified_reconstruction` | `False` | 0 | 0 |  |  |  |  |  |  | `True` | `False` |
| `single_holdout_pressure_test` | `True` | 1 | 1 | 2.869489 | 2.869489 | 2.869489 | 2.869489 | 345859.000000 | 136035.000000 | `True` | `False` |
| `multi_holdout_supported` | `True` | 1 | 3 | 1.956950 | 1.685191 | 1.956950 | 1.685191 | 174427.000000 | 71702.000000 | `True` | `False` |
| `multi_holdout_ge3` | `True` | 1 | 3 | 1.956950 | 1.685191 | 1.956950 | 1.685191 | 174427.000000 | 71702.000000 | `True` | `False` |
| `rmse_le6` | `True` | 2 | 4 | 2.413219 | 2.277340 | 2.220525 | 1.981266 | 260143.000000 | 103868.500000 | `True` | `False` |
| `rmse_gt6` | `True` | 0 | 0 |  |  |  |  |  |  | `True` | `False` |
| `strong_wind_subset` | `True` | 2 | 4 | 2.413219 | 2.277340 | 2.220525 | 1.981266 | 260143.000000 | 103868.500000 | `True` | `False` |
| `vertical_mismatch_subset` | `True` | 2 | 4 | 2.413219 | 2.277340 | 2.220525 | 1.981266 | 260143.000000 | 103868.500000 | `True` | `False` |
