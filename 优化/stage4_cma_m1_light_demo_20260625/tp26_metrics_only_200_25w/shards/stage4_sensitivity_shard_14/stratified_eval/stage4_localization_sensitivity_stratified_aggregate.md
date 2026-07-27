# Stage4 Stratified Evaluation

Official RMSE/MAE comes only from `eval_holdout_only` and its holdout subsets. `no_holdout_unverified_reconstruction` keeps coverage and risk diagnostics but does not contribute to official error metrics.

- expected frames: `0`
- validation failures: `0`

| stratum | official | frames | holdout points | frame RMSE | frame MAE | weighted RMSE | weighted MAE | mean effective voxels | mean low-conf fill | leakage | motion used |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| `all_frames_original` | `False` | 3 | 12 |  |  |  |  | 232760.333333 | 101297.666667 | `True` | `False` |
| `eval_holdout_only` | `True` | 3 | 12 | 2.917557 | 2.716146 | 3.185354 | 2.883226 | 232760.333333 | 101297.666667 | `True` | `False` |
| `no_holdout_unverified_reconstruction` | `False` | 0 | 0 |  |  |  |  |  |  | `True` | `False` |
| `single_holdout_pressure_test` | `True` | 0 | 0 |  |  |  |  |  |  | `True` | `False` |
| `multi_holdout_supported` | `True` | 3 | 12 | 2.917557 | 2.716146 | 3.185354 | 2.883226 | 232760.333333 | 101297.666667 | `True` | `False` |
| `multi_holdout_ge3` | `True` | 2 | 10 | 3.249257 | 2.962427 | 3.340589 | 3.015155 | 248089.000000 | 102208.000000 | `True` | `False` |
| `rmse_le6` | `True` | 3 | 12 | 2.917557 | 2.716146 | 3.185354 | 2.883226 | 232760.333333 | 101297.666667 | `True` | `False` |
| `rmse_gt6` | `True` | 0 | 0 |  |  |  |  |  |  | `True` | `False` |
| `strong_wind_subset` | `True` | 3 | 12 | 2.917557 | 2.716146 | 3.185354 | 2.883226 | 232760.333333 | 101297.666667 | `True` | `False` |
| `vertical_mismatch_subset` | `True` | 3 | 12 | 2.917557 | 2.716146 | 3.185354 | 2.883226 | 232760.333333 | 101297.666667 | `True` | `False` |
| `all_frames_original` | `False` | 5 | 11 |  |  |  |  | 215588.400000 | 87564.400000 | `True` | `False` |
| `eval_holdout_only` | `True` | 5 | 11 | 4.539939 | 4.175445 | 4.884894 | 4.325975 | 215588.400000 | 87564.400000 | `True` | `False` |
| `no_holdout_unverified_reconstruction` | `False` | 0 | 0 |  |  |  |  |  |  | `True` | `False` |
| `single_holdout_pressure_test` | `True` | 0 | 0 |  |  |  |  |  |  | `True` | `False` |
| `multi_holdout_supported` | `True` | 5 | 11 | 4.539939 | 4.175445 | 4.884894 | 4.325975 | 215588.400000 | 87564.400000 | `True` | `False` |
| `multi_holdout_ge3` | `True` | 1 | 3 | 6.158782 | 5.831273 | 6.158782 | 5.831273 | 202551.000000 | 83691.000000 | `True` | `False` |
| `rmse_le6` | `True` | 4 | 8 | 4.135228 | 3.761488 | 4.311212 | 3.761488 | 218847.750000 | 88532.750000 | `True` | `False` |
| `rmse_gt6` | `True` | 1 | 3 | 6.158782 | 5.831273 | 6.158782 | 5.831273 | 202551.000000 | 83691.000000 | `True` | `False` |
| `strong_wind_subset` | `True` | 5 | 11 | 4.539939 | 4.175445 | 4.884894 | 4.325975 | 215588.400000 | 87564.400000 | `True` | `False` |
| `vertical_mismatch_subset` | `True` | 5 | 11 | 4.539939 | 4.175445 | 4.884894 | 4.325975 | 215588.400000 | 87564.400000 | `True` | `False` |
