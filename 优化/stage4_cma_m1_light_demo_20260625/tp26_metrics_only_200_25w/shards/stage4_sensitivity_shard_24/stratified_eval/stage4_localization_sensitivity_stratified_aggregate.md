# Stage4 Stratified Evaluation

Official RMSE/MAE comes only from `eval_holdout_only` and its holdout subsets. `no_holdout_unverified_reconstruction` keeps coverage and risk diagnostics but does not contribute to official error metrics.

- expected frames: `0`
- validation failures: `0`

| stratum | official | frames | holdout points | frame RMSE | frame MAE | weighted RMSE | weighted MAE | mean effective voxels | mean low-conf fill | leakage | motion used |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| `all_frames_original` | `False` | 3 | 13 |  |  |  |  | 214954.666667 | 90029.666667 | `True` | `False` |
| `eval_holdout_only` | `True` | 3 | 13 | 7.651690 | 6.395749 | 7.743647 | 6.293266 | 214954.666667 | 90029.666667 | `True` | `False` |
| `no_holdout_unverified_reconstruction` | `False` | 0 | 0 |  |  |  |  |  |  | `True` | `False` |
| `single_holdout_pressure_test` | `True` | 0 | 0 |  |  |  |  |  |  | `True` | `False` |
| `multi_holdout_supported` | `True` | 3 | 13 | 7.651690 | 6.395749 | 7.743647 | 6.293266 | 214954.666667 | 90029.666667 | `True` | `False` |
| `multi_holdout_ge3` | `True` | 3 | 13 | 7.651690 | 6.395749 | 7.743647 | 6.293266 | 214954.666667 | 90029.666667 | `True` | `False` |
| `rmse_le6` | `True` | 1 | 5 | 5.965762 | 5.063469 | 5.965762 | 5.063469 | 256291.000000 | 99069.000000 | `True` | `False` |
| `rmse_gt6` | `True` | 2 | 8 | 8.494654 | 7.061889 | 8.671658 | 7.061889 | 194286.500000 | 85510.000000 | `True` | `False` |
| `strong_wind_subset` | `True` | 3 | 13 | 7.651690 | 6.395749 | 7.743647 | 6.293266 | 214954.666667 | 90029.666667 | `True` | `False` |
| `vertical_mismatch_subset` | `True` | 3 | 13 | 7.651690 | 6.395749 | 7.743647 | 6.293266 | 214954.666667 | 90029.666667 | `True` | `False` |
| `all_frames_original` | `False` | 5 | 9 |  |  |  |  | 230902.400000 | 90845.200000 | `True` | `False` |
| `eval_holdout_only` | `True` | 5 | 9 | 26.594825 | 20.330433 | 63.592399 | 30.534287 | 230902.400000 | 90845.200000 | `True` | `False` |
| `no_holdout_unverified_reconstruction` | `False` | 0 | 0 |  |  |  |  |  |  | `True` | `False` |
| `single_holdout_pressure_test` | `True` | 2 | 2 | 4.463086 | 4.463086 | 4.463501 | 4.463086 | 258792.000000 | 102524.000000 | `True` | `False` |
| `multi_holdout_supported` | `True` | 3 | 7 | 41.349318 | 30.908663 | 72.067521 | 37.983202 | 212309.333333 | 83059.333333 | `True` | `False` |
| `multi_holdout_ge3` | `True` | 1 | 3 | 109.692698 | 80.430431 | 109.692698 | 80.430431 | 190357.000000 | 73784.000000 | `True` | `False` |
| `rmse_le6` | `True` | 3 | 4 | 4.159682 | 3.919986 | 4.033965 | 3.648435 | 264478.666667 | 104356.666667 | `True` | `False` |
| `rmse_gt6` | `True` | 2 | 5 | 60.247541 | 44.946103 | 85.241829 | 52.042969 | 180538.000000 | 70578.000000 | `True` | `False` |
| `strong_wind_subset` | `True` | 5 | 9 | 26.594825 | 20.330433 | 63.592399 | 30.534287 | 230902.400000 | 90845.200000 | `True` | `False` |
| `vertical_mismatch_subset` | `True` | 5 | 9 | 26.594825 | 20.330433 | 63.592399 | 30.534287 | 230902.400000 | 90845.200000 | `True` | `False` |
