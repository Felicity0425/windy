# Stage4 Stratified Evaluation

Official RMSE/MAE comes only from `eval_holdout_only` and its holdout subsets. `no_holdout_unverified_reconstruction` keeps coverage and risk diagnostics but does not contribute to official error metrics.

- expected frames: `0`
- validation failures: `0`

| stratum | official | frames | holdout points | frame RMSE | frame MAE | weighted RMSE | weighted MAE | mean effective voxels | mean low-conf fill | leakage | motion used |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| `all_frames_original` | `False` | 2 | 3 |  |  |  |  | 212173.000000 | 100000.500000 | `True` | `False` |
| `eval_holdout_only` | `True` | 2 | 3 | 7.487841 | 7.171221 | 7.064026 | 6.317001 | 212173.000000 | 100000.500000 | `True` | `False` |
| `no_holdout_unverified_reconstruction` | `False` | 0 | 0 |  |  |  |  |  |  | `True` | `False` |
| `single_holdout_pressure_test` | `True` | 1 | 1 | 9.733884 | 9.733884 | 9.733884 | 9.733884 | 191364.000000 | 91637.000000 | `True` | `False` |
| `multi_holdout_supported` | `True` | 1 | 2 | 5.241798 | 4.608559 | 5.241798 | 4.608559 | 232982.000000 | 108364.000000 | `True` | `False` |
| `multi_holdout_ge3` | `True` | 0 | 0 |  |  |  |  |  |  | `True` | `False` |
| `rmse_le6` | `True` | 1 | 2 | 5.241798 | 4.608559 | 5.241798 | 4.608559 | 232982.000000 | 108364.000000 | `True` | `False` |
| `rmse_gt6` | `True` | 1 | 1 | 9.733884 | 9.733884 | 9.733884 | 9.733884 | 191364.000000 | 91637.000000 | `True` | `False` |
| `strong_wind_subset` | `True` | 2 | 3 | 7.487841 | 7.171221 | 7.064026 | 6.317001 | 212173.000000 | 100000.500000 | `True` | `False` |
| `vertical_mismatch_subset` | `True` | 2 | 3 | 7.487841 | 7.171221 | 7.064026 | 6.317001 | 212173.000000 | 100000.500000 | `True` | `False` |
| `all_frames_original` | `False` | 6 | 14 |  |  |  |  | 207753.666667 | 89183.333333 | `True` | `False` |
| `eval_holdout_only` | `True` | 6 | 14 | 5.770983 | 5.332352 | 5.401806 | 4.624801 | 207753.666667 | 89183.333333 | `True` | `False` |
| `no_holdout_unverified_reconstruction` | `False` | 0 | 0 |  |  |  |  |  |  | `True` | `False` |
| `single_holdout_pressure_test` | `True` | 2 | 2 | 7.808778 | 7.808778 | 7.946688 | 7.808778 | 255558.000000 | 103534.000000 | `True` | `False` |
| `multi_holdout_supported` | `True` | 4 | 12 | 4.752085 | 4.094138 | 4.849514 | 4.094138 | 183851.500000 | 82008.000000 | `True` | `False` |
| `multi_holdout_ge3` | `True` | 4 | 12 | 4.752085 | 4.094138 | 4.849514 | 4.094138 | 183851.500000 | 82008.000000 | `True` | `False` |
| `rmse_le6` | `True` | 3 | 9 | 4.290752 | 3.781439 | 4.336650 | 3.781439 | 197323.666667 | 86831.333333 | `True` | `False` |
| `rmse_gt6` | `True` | 3 | 5 | 7.251213 | 6.883264 | 6.917431 | 6.142852 | 218183.666667 | 91535.333333 | `True` | `False` |
| `strong_wind_subset` | `True` | 6 | 14 | 5.770983 | 5.332352 | 5.401806 | 4.624801 | 207753.666667 | 89183.333333 | `True` | `False` |
| `vertical_mismatch_subset` | `True` | 6 | 14 | 5.770983 | 5.332352 | 5.401806 | 4.624801 | 207753.666667 | 89183.333333 | `True` | `False` |
