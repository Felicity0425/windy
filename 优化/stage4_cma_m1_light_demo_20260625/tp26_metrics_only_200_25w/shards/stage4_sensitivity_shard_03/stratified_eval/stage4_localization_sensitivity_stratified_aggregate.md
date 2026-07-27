# Stage4 Stratified Evaluation

Official RMSE/MAE comes only from `eval_holdout_only` and its holdout subsets. `no_holdout_unverified_reconstruction` keeps coverage and risk diagnostics but does not contribute to official error metrics.

- expected frames: `0`
- validation failures: `0`

| stratum | official | frames | holdout points | frame RMSE | frame MAE | weighted RMSE | weighted MAE | mean effective voxels | mean low-conf fill | leakage | motion used |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| `all_frames_original` | `False` | 5 | 16 |  |  |  |  | 218750.000000 | 95670.200000 | `True` | `False` |
| `eval_holdout_only` | `True` | 5 | 16 | 4.194425 | 3.753513 | 4.589560 | 3.879361 | 218750.000000 | 95670.200000 | `True` | `False` |
| `no_holdout_unverified_reconstruction` | `False` | 0 | 0 |  |  |  |  |  |  | `True` | `False` |
| `single_holdout_pressure_test` | `True` | 1 | 1 | 1.894851 | 1.894851 | 1.894851 | 1.894851 | 262013.000000 | 105948.000000 | `True` | `False` |
| `multi_holdout_supported` | `True` | 4 | 15 | 4.769318 | 4.218179 | 4.714760 | 4.011661 | 207934.250000 | 93100.750000 | `True` | `False` |
| `multi_holdout_ge3` | `True` | 4 | 15 | 4.769318 | 4.218179 | 4.714760 | 4.011661 | 207934.250000 | 93100.750000 | `True` | `False` |
| `rmse_le6` | `True` | 4 | 13 | 3.522224 | 3.300429 | 3.871875 | 3.490171 | 223817.000000 | 94292.500000 | `True` | `False` |
| `rmse_gt6` | `True` | 1 | 3 | 6.883228 | 5.565851 | 6.883228 | 5.565851 | 198482.000000 | 101181.000000 | `True` | `False` |
| `strong_wind_subset` | `True` | 5 | 16 | 4.194425 | 3.753513 | 4.589560 | 3.879361 | 218750.000000 | 95670.200000 | `True` | `False` |
| `vertical_mismatch_subset` | `True` | 5 | 16 | 4.194425 | 3.753513 | 4.589560 | 3.879361 | 218750.000000 | 95670.200000 | `True` | `False` |
| `all_frames_original` | `False` | 3 | 7 |  |  |  |  | 205125.666667 | 90412.333333 | `True` | `False` |
| `eval_holdout_only` | `True` | 3 | 7 | 11.716744 | 10.780196 | 19.201613 | 13.308197 | 205125.666667 | 90412.333333 | `True` | `False` |
| `no_holdout_unverified_reconstruction` | `False` | 0 | 0 |  |  |  |  |  |  | `True` | `False` |
| `single_holdout_pressure_test` | `True` | 1 | 1 | 1.932191 | 1.932191 | 1.932191 | 1.932191 | 193130.000000 | 82142.000000 | `True` | `False` |
| `multi_holdout_supported` | `True` | 2 | 6 | 16.609020 | 15.204198 | 20.725107 | 15.204198 | 211123.500000 | 94547.500000 | `True` | `False` |
| `multi_holdout_ge3` | `True` | 2 | 6 | 16.609020 | 15.204198 | 20.725107 | 15.204198 | 211123.500000 | 94547.500000 | `True` | `False` |
| `rmse_le6` | `True` | 2 | 4 | 3.072410 | 2.709420 | 3.773993 | 3.098034 | 192379.500000 | 82536.500000 | `True` | `False` |
| `rmse_gt6` | `True` | 1 | 3 | 29.005411 | 26.921748 | 29.005411 | 26.921748 | 230618.000000 | 106164.000000 | `True` | `False` |
| `strong_wind_subset` | `True` | 3 | 7 | 11.716744 | 10.780196 | 19.201613 | 13.308197 | 205125.666667 | 90412.333333 | `True` | `False` |
| `vertical_mismatch_subset` | `True` | 3 | 7 | 11.716744 | 10.780196 | 19.201613 | 13.308197 | 205125.666667 | 90412.333333 | `True` | `False` |
