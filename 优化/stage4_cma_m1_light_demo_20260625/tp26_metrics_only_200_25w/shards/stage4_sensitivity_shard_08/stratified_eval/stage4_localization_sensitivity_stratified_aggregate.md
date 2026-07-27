# Stage4 Stratified Evaluation

Official RMSE/MAE comes only from `eval_holdout_only` and its holdout subsets. `no_holdout_unverified_reconstruction` keeps coverage and risk diagnostics but does not contribute to official error metrics.

- expected frames: `0`
- validation failures: `0`

| stratum | official | frames | holdout points | frame RMSE | frame MAE | weighted RMSE | weighted MAE | mean effective voxels | mean low-conf fill | leakage | motion used |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| `all_frames_original` | `False` | 6 | 21 |  |  |  |  | 208408.500000 | 91076.500000 | `True` | `False` |
| `eval_holdout_only` | `True` | 6 | 21 | 5.347270 | 4.207979 | 6.729597 | 4.374131 | 208408.500000 | 91076.500000 | `True` | `False` |
| `no_holdout_unverified_reconstruction` | `False` | 0 | 0 |  |  |  |  |  |  | `True` | `False` |
| `single_holdout_pressure_test` | `True` | 2 | 2 | 0.818179 | 0.818179 | 0.840062 | 0.818179 | 172084.500000 | 78416.000000 | `True` | `False` |
| `multi_holdout_supported` | `True` | 4 | 19 | 7.611815 | 5.902878 | 7.069674 | 4.748442 | 226570.500000 | 97406.750000 | `True` | `False` |
| `multi_holdout_ge3` | `True` | 3 | 17 | 4.514853 | 3.792013 | 4.716821 | 3.867615 | 237681.666667 | 97098.333333 | `True` | `False` |
| `rmse_le6` | `True` | 5 | 19 | 3.036183 | 2.602479 | 4.469983 | 3.546621 | 211442.800000 | 89625.400000 | `True` | `False` |
| `rmse_gt6` | `True` | 1 | 2 | 16.902702 | 12.235475 | 16.902702 | 12.235475 | 193237.000000 | 98332.000000 | `True` | `False` |
| `strong_wind_subset` | `True` | 6 | 21 | 5.347270 | 4.207979 | 6.729597 | 4.374131 | 208408.500000 | 91076.500000 | `True` | `False` |
| `vertical_mismatch_subset` | `True` | 6 | 21 | 5.347270 | 4.207979 | 6.729597 | 4.374131 | 208408.500000 | 91076.500000 | `True` | `False` |
| `all_frames_original` | `False` | 2 | 3 |  |  |  |  | 227527.500000 | 101184.000000 | `True` | `False` |
| `eval_holdout_only` | `True` | 2 | 3 | 3.638565 | 3.329338 | 3.456059 | 2.961901 | 227527.500000 | 101184.000000 | `True` | `False` |
| `no_holdout_unverified_reconstruction` | `False` | 0 | 0 |  |  |  |  |  |  | `True` | `False` |
| `single_holdout_pressure_test` | `True` | 1 | 1 | 4.431649 | 4.431649 | 4.431649 | 4.431649 | 242797.000000 | 103651.000000 | `True` | `False` |
| `multi_holdout_supported` | `True` | 1 | 2 | 2.845480 | 2.227027 | 2.845480 | 2.227027 | 212258.000000 | 98717.000000 | `True` | `False` |
| `multi_holdout_ge3` | `True` | 0 | 0 |  |  |  |  |  |  | `True` | `False` |
| `rmse_le6` | `True` | 2 | 3 | 3.638565 | 3.329338 | 3.456059 | 2.961901 | 227527.500000 | 101184.000000 | `True` | `False` |
| `rmse_gt6` | `True` | 0 | 0 |  |  |  |  |  |  | `True` | `False` |
| `strong_wind_subset` | `True` | 2 | 3 | 3.638565 | 3.329338 | 3.456059 | 2.961901 | 227527.500000 | 101184.000000 | `True` | `False` |
| `vertical_mismatch_subset` | `True` | 2 | 3 | 3.638565 | 3.329338 | 3.456059 | 2.961901 | 227527.500000 | 101184.000000 | `True` | `False` |
