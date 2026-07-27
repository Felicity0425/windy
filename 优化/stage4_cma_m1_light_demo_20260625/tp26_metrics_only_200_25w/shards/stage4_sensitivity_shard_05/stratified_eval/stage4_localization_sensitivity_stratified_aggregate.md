# Stage4 Stratified Evaluation

Official RMSE/MAE comes only from `eval_holdout_only` and its holdout subsets. `no_holdout_unverified_reconstruction` keeps coverage and risk diagnostics but does not contribute to official error metrics.

- expected frames: `0`
- validation failures: `0`

| stratum | official | frames | holdout points | frame RMSE | frame MAE | weighted RMSE | weighted MAE | mean effective voxels | mean low-conf fill | leakage | motion used |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| `all_frames_original` | `False` | 3 | 5 |  |  |  |  | 232882.333333 | 97610.666667 | `True` | `False` |
| `eval_holdout_only` | `True` | 3 | 5 | 3.224480 | 3.139596 | 3.185152 | 2.943888 | 232882.333333 | 97610.666667 | `True` | `False` |
| `no_holdout_unverified_reconstruction` | `False` | 0 | 0 |  |  |  |  |  |  | `True` | `False` |
| `single_holdout_pressure_test` | `True` | 1 | 1 | 4.118139 | 4.118139 | 4.118139 | 4.118139 | 302088.000000 | 120860.000000 | `True` | `False` |
| `multi_holdout_supported` | `True` | 2 | 4 | 2.777650 | 2.650325 | 2.905465 | 2.650325 | 198279.500000 | 85986.000000 | `True` | `False` |
| `multi_holdout_ge3` | `True` | 0 | 0 |  |  |  |  |  |  | `True` | `False` |
| `rmse_le6` | `True` | 3 | 5 | 3.224480 | 3.139596 | 3.185152 | 2.943888 | 232882.333333 | 97610.666667 | `True` | `False` |
| `rmse_gt6` | `True` | 0 | 0 |  |  |  |  |  |  | `True` | `False` |
| `strong_wind_subset` | `True` | 3 | 5 | 3.224480 | 3.139596 | 3.185152 | 2.943888 | 232882.333333 | 97610.666667 | `True` | `False` |
| `vertical_mismatch_subset` | `True` | 3 | 5 | 3.224480 | 3.139596 | 3.185152 | 2.943888 | 232882.333333 | 97610.666667 | `True` | `False` |
| `all_frames_original` | `False` | 5 | 14 |  |  |  |  | 200964.800000 | 84940.800000 | `True` | `False` |
| `eval_holdout_only` | `True` | 5 | 14 | 10.753496 | 10.578327 | 10.868516 | 7.049782 | 200964.800000 | 84940.800000 | `True` | `False` |
| `no_holdout_unverified_reconstruction` | `False` | 0 | 0 |  |  |  |  |  |  | `True` | `False` |
| `single_holdout_pressure_test` | `True` | 2 | 2 | 19.115222 | 19.115222 | 25.613931 | 19.115222 | 162388.000000 | 77396.000000 | `True` | `False` |
| `multi_holdout_supported` | `True` | 3 | 12 | 5.179012 | 4.887063 | 5.335401 | 5.038875 | 226682.666667 | 89970.666667 | `True` | `False` |
| `multi_holdout_ge3` | `True` | 3 | 12 | 5.179012 | 4.887063 | 5.335401 | 5.038875 | 226682.666667 | 89970.666667 | `True` | `False` |
| `rmse_le6` | `True` | 3 | 8 | 3.841555 | 3.607781 | 4.488084 | 4.126744 | 226282.000000 | 92986.333333 | `True` | `False` |
| `rmse_gt6` | `True` | 2 | 6 | 21.121407 | 21.034145 | 15.772348 | 10.947166 | 162989.000000 | 72872.500000 | `True` | `False` |
| `strong_wind_subset` | `True` | 5 | 14 | 10.753496 | 10.578327 | 10.868516 | 7.049782 | 200964.800000 | 84940.800000 | `True` | `False` |
| `vertical_mismatch_subset` | `True` | 5 | 14 | 10.753496 | 10.578327 | 10.868516 | 7.049782 | 200964.800000 | 84940.800000 | `True` | `False` |
