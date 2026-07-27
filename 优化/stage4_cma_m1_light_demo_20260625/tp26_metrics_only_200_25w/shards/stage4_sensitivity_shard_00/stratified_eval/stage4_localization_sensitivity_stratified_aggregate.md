# Stage4 Stratified Evaluation

Official RMSE/MAE comes only from `eval_holdout_only` and its holdout subsets. `no_holdout_unverified_reconstruction` keeps coverage and risk diagnostics but does not contribute to official error metrics.

- expected frames: `0`
- validation failures: `0`

| stratum | official | frames | holdout points | frame RMSE | frame MAE | weighted RMSE | weighted MAE | mean effective voxels | mean low-conf fill | leakage | motion used |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| `all_frames_original` | `False` | 5 | 24 |  |  |  |  | 219573.200000 | 95754.000000 | `True` | `False` |
| `eval_holdout_only` | `True` | 5 | 24 | 4.334173 | 3.741710 | 5.137488 | 4.175502 | 219573.200000 | 95754.000000 | `True` | `False` |
| `no_holdout_unverified_reconstruction` | `False` | 0 | 0 |  |  |  |  |  |  | `True` | `False` |
| `single_holdout_pressure_test` | `True` | 1 | 1 | 2.826490 | 2.826490 | 2.826490 | 2.826490 | 206423.000000 | 101772.000000 | `True` | `False` |
| `multi_holdout_supported` | `True` | 4 | 23 | 4.711094 | 3.970515 | 5.214786 | 4.234155 | 222860.750000 | 94249.500000 | `True` | `False` |
| `multi_holdout_ge3` | `True` | 4 | 23 | 4.711094 | 3.970515 | 5.214786 | 4.234155 | 222860.750000 | 94249.500000 | `True` | `False` |
| `rmse_le6` | `True` | 4 | 17 | 3.775278 | 3.351181 | 4.414676 | 3.710898 | 216220.500000 | 94205.500000 | `True` | `False` |
| `rmse_gt6` | `True` | 1 | 7 | 6.569754 | 5.303827 | 6.569754 | 5.303827 | 232984.000000 | 101948.000000 | `True` | `False` |
| `strong_wind_subset` | `True` | 5 | 24 | 4.334173 | 3.741710 | 5.137488 | 4.175502 | 219573.200000 | 95754.000000 | `True` | `False` |
| `vertical_mismatch_subset` | `True` | 5 | 24 | 4.334173 | 3.741710 | 5.137488 | 4.175502 | 219573.200000 | 95754.000000 | `True` | `False` |
| `all_frames_original` | `False` | 3 | 7 |  |  |  |  | 218040.333333 | 88153.666667 | `True` | `False` |
| `eval_holdout_only` | `True` | 3 | 7 | 11.688233 | 9.798724 | 14.085832 | 8.903127 | 218040.333333 | 88153.666667 | `True` | `False` |
| `no_holdout_unverified_reconstruction` | `False` | 0 | 0 |  |  |  |  |  |  | `True` | `False` |
| `single_holdout_pressure_test` | `True` | 0 | 0 |  |  |  |  |  |  | `True` | `False` |
| `multi_holdout_supported` | `True` | 3 | 7 | 11.688233 | 9.798724 | 14.085832 | 8.903127 | 218040.333333 | 88153.666667 | `True` | `False` |
| `multi_holdout_ge3` | `True` | 1 | 3 | 3.615041 | 3.529544 | 3.615041 | 3.529544 | 185729.000000 | 80454.000000 | `True` | `False` |
| `rmse_le6` | `True` | 1 | 3 | 3.615041 | 3.529544 | 3.615041 | 3.529544 | 185729.000000 | 80454.000000 | `True` | `False` |
| `rmse_gt6` | `True` | 2 | 4 | 15.724829 | 12.933315 | 18.368921 | 12.933315 | 234196.000000 | 92003.500000 | `True` | `False` |
| `strong_wind_subset` | `True` | 3 | 7 | 11.688233 | 9.798724 | 14.085832 | 8.903127 | 218040.333333 | 88153.666667 | `True` | `False` |
| `vertical_mismatch_subset` | `True` | 3 | 7 | 11.688233 | 9.798724 | 14.085832 | 8.903127 | 218040.333333 | 88153.666667 | `True` | `False` |
