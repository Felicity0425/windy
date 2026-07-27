# Stage4 Stratified Evaluation

Official RMSE/MAE comes only from `eval_holdout_only` and its holdout subsets. `no_holdout_unverified_reconstruction` keeps coverage and risk diagnostics but does not contribute to official error metrics.

- expected frames: `0`
- validation failures: `0`

| stratum | official | frames | holdout points | frame RMSE | frame MAE | weighted RMSE | weighted MAE | mean effective voxels | mean low-conf fill | leakage | motion used |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| `all_frames_original` | `False` | 5 | 11 |  |  |  |  | 199680.800000 | 86964.000000 | `True` | `False` |
| `eval_holdout_only` | `True` | 5 | 11 | 8.274543 | 7.958655 | 8.245755 | 5.302145 | 199680.800000 | 86964.000000 | `True` | `False` |
| `no_holdout_unverified_reconstruction` | `False` | 0 | 0 |  |  |  |  |  |  | `True` | `False` |
| `single_holdout_pressure_test` | `True` | 2 | 2 | 15.588483 | 15.588483 | 17.656527 | 15.588483 | 205780.000000 | 92245.000000 | `True` | `False` |
| `multi_holdout_supported` | `True` | 3 | 9 | 3.398583 | 2.872103 | 3.717995 | 3.016292 | 195614.666667 | 83443.333333 | `True` | `False` |
| `multi_holdout_ge3` | `True` | 2 | 7 | 3.679292 | 3.088445 | 3.933599 | 3.181113 | 203075.500000 | 86832.000000 | `True` | `False` |
| `rmse_le6` | `True` | 3 | 9 | 3.398583 | 2.872103 | 3.717995 | 3.016292 | 195614.666667 | 83443.333333 | `True` | `False` |
| `rmse_gt6` | `True` | 2 | 2 | 15.588483 | 15.588483 | 17.656527 | 15.588483 | 205780.000000 | 92245.000000 | `True` | `False` |
| `strong_wind_subset` | `True` | 5 | 11 | 8.274543 | 7.958655 | 8.245755 | 5.302145 | 199680.800000 | 86964.000000 | `True` | `False` |
| `vertical_mismatch_subset` | `True` | 5 | 11 | 8.274543 | 7.958655 | 8.245755 | 5.302145 | 199680.800000 | 86964.000000 | `True` | `False` |
| `all_frames_original` | `False` | 3 | 7 |  |  |  |  | 266981.000000 | 103935.000000 | `True` | `False` |
| `eval_holdout_only` | `True` | 3 | 7 | 4.847731 | 4.088341 | 4.865037 | 3.827750 | 266981.000000 | 103935.000000 | `True` | `False` |
| `no_holdout_unverified_reconstruction` | `False` | 0 | 0 |  |  |  |  |  |  | `True` | `False` |
| `single_holdout_pressure_test` | `True` | 0 | 0 |  |  |  |  |  |  | `True` | `False` |
| `multi_holdout_supported` | `True` | 3 | 7 | 4.847731 | 4.088341 | 4.865037 | 3.827750 | 266981.000000 | 103935.000000 | `True` | `False` |
| `multi_holdout_ge3` | `True` | 1 | 3 | 2.363261 | 2.264200 | 2.363261 | 2.264200 | 262160.000000 | 99217.000000 | `True` | `False` |
| `rmse_le6` | `True` | 2 | 5 | 4.037150 | 3.480799 | 4.049369 | 3.237479 | 270908.500000 | 106015.500000 | `True` | `False` |
| `rmse_gt6` | `True` | 1 | 2 | 6.468892 | 5.303426 | 6.468892 | 5.303426 | 259126.000000 | 99774.000000 | `True` | `False` |
| `strong_wind_subset` | `True` | 3 | 7 | 4.847731 | 4.088341 | 4.865037 | 3.827750 | 266981.000000 | 103935.000000 | `True` | `False` |
| `vertical_mismatch_subset` | `True` | 3 | 7 | 4.847731 | 4.088341 | 4.865037 | 3.827750 | 266981.000000 | 103935.000000 | `True` | `False` |
