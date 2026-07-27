# Stage4 Stratified Evaluation

Official RMSE/MAE comes only from `eval_holdout_only` and its holdout subsets. `no_holdout_unverified_reconstruction` keeps coverage and risk diagnostics but does not contribute to official error metrics.

- expected frames: `0`
- validation failures: `0`

| stratum | official | frames | holdout points | frame RMSE | frame MAE | weighted RMSE | weighted MAE | mean effective voxels | mean low-conf fill | leakage | motion used |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| `all_frames_original` | `False` | 3 | 7 |  |  |  |  | 262010.333333 | 102356.666667 | `True` | `False` |
| `eval_holdout_only` | `True` | 3 | 7 | 8.984262 | 7.716834 | 12.105257 | 8.577300 | 262010.333333 | 102356.666667 | `True` | `False` |
| `no_holdout_unverified_reconstruction` | `False` | 0 | 0 |  |  |  |  |  |  | `True` | `False` |
| `single_holdout_pressure_test` | `True` | 0 | 0 |  |  |  |  |  |  | `True` | `False` |
| `multi_holdout_supported` | `True` | 3 | 7 | 8.984262 | 7.716834 | 12.105257 | 8.577300 | 262010.333333 | 102356.666667 | `True` | `False` |
| `multi_holdout_ge3` | `True` | 1 | 3 | 17.159523 | 13.740096 | 17.159523 | 13.740096 | 298938.000000 | 114061.000000 | `True` | `False` |
| `rmse_le6` | `True` | 1 | 2 | 1.486902 | 1.307441 | 1.486902 | 1.307441 | 215614.000000 | 86243.000000 | `True` | `False` |
| `rmse_gt6` | `True` | 2 | 5 | 12.732943 | 10.921531 | 14.292229 | 11.485244 | 285208.500000 | 110413.500000 | `True` | `False` |
| `strong_wind_subset` | `True` | 3 | 7 | 8.984262 | 7.716834 | 12.105257 | 8.577300 | 262010.333333 | 102356.666667 | `True` | `False` |
| `vertical_mismatch_subset` | `True` | 3 | 7 | 8.984262 | 7.716834 | 12.105257 | 8.577300 | 262010.333333 | 102356.666667 | `True` | `False` |
| `all_frames_original` | `False` | 5 | 17 |  |  |  |  | 177175.800000 | 79067.800000 | `True` | `False` |
| `eval_holdout_only` | `True` | 5 | 17 | 7.373411 | 6.354302 | 11.018334 | 8.146631 | 177175.800000 | 79067.800000 | `True` | `False` |
| `no_holdout_unverified_reconstruction` | `False` | 0 | 0 |  |  |  |  |  |  | `True` | `False` |
| `single_holdout_pressure_test` | `True` | 3 | 3 | 4.033803 | 4.033803 | 5.539340 | 4.033803 | 158065.333333 | 74380.000000 | `True` | `False` |
| `multi_holdout_supported` | `True` | 2 | 14 | 12.382821 | 9.835051 | 11.867752 | 9.027951 | 205841.500000 | 86099.500000 | `True` | `False` |
| `multi_holdout_ge3` | `True` | 2 | 14 | 12.382821 | 9.835051 | 11.867752 | 9.027951 | 205841.500000 | 86099.500000 | `True` | `False` |
| `rmse_le6` | `True` | 2 | 2 | 1.354944 | 1.354944 | 1.387836 | 1.354944 | 158732.500000 | 77465.500000 | `True` | `False` |
| `rmse_gt6` | `True` | 3 | 15 | 11.385722 | 9.687208 | 11.718960 | 9.052189 | 189471.333333 | 80136.000000 | `True` | `False` |
| `strong_wind_subset` | `True` | 5 | 17 | 7.373411 | 6.354302 | 11.018334 | 8.146631 | 177175.800000 | 79067.800000 | `True` | `False` |
| `vertical_mismatch_subset` | `True` | 5 | 17 | 7.373411 | 6.354302 | 11.018334 | 8.146631 | 177175.800000 | 79067.800000 | `True` | `False` |
