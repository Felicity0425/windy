# Stage4 Stratified Evaluation

Official RMSE/MAE comes only from `eval_holdout_only` and its holdout subsets. `no_holdout_unverified_reconstruction` keeps coverage and risk diagnostics but does not contribute to official error metrics.

- expected frames: `0`
- validation failures: `0`

| stratum | official | frames | holdout points | frame RMSE | frame MAE | weighted RMSE | weighted MAE | mean effective voxels | mean low-conf fill | leakage | motion used |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| `all_frames_original` | `False` | 3 | 6 |  |  |  |  | 260249.000000 | 100036.333333 | `True` | `False` |
| `eval_holdout_only` | `True` | 3 | 6 | 4.918743 | 4.801963 | 5.357148 | 4.766293 | 260249.000000 | 100036.333333 | `True` | `False` |
| `no_holdout_unverified_reconstruction` | `False` | 0 | 0 |  |  |  |  |  |  | `True` | `False` |
| `single_holdout_pressure_test` | `True` | 1 | 1 | 3.377397 | 3.377397 | 3.377397 | 3.377397 | 214235.000000 | 89836.000000 | `True` | `False` |
| `multi_holdout_supported` | `True` | 2 | 5 | 5.689416 | 5.514246 | 5.670757 | 5.044072 | 283256.000000 | 105136.500000 | `True` | `False` |
| `multi_holdout_ge3` | `True` | 1 | 3 | 3.510954 | 3.163375 | 3.510954 | 3.163375 | 256392.000000 | 98729.000000 | `True` | `False` |
| `rmse_le6` | `True` | 2 | 4 | 3.444175 | 3.270386 | 3.478045 | 3.216880 | 235313.500000 | 94282.500000 | `True` | `False` |
| `rmse_gt6` | `True` | 1 | 2 | 7.867878 | 7.865118 | 7.867878 | 7.865118 | 310120.000000 | 111544.000000 | `True` | `False` |
| `strong_wind_subset` | `True` | 3 | 6 | 4.918743 | 4.801963 | 5.357148 | 4.766293 | 260249.000000 | 100036.333333 | `True` | `False` |
| `vertical_mismatch_subset` | `True` | 3 | 6 | 4.918743 | 4.801963 | 5.357148 | 4.766293 | 260249.000000 | 100036.333333 | `True` | `False` |
| `all_frames_original` | `False` | 5 | 16 |  |  |  |  | 205679.200000 | 90587.600000 | `True` | `False` |
| `eval_holdout_only` | `True` | 5 | 16 | 15.719715 | 9.309389 | 27.163199 | 11.437655 | 205679.200000 | 90587.600000 | `True` | `False` |
| `no_holdout_unverified_reconstruction` | `False` | 0 | 0 |  |  |  |  |  |  | `True` | `False` |
| `single_holdout_pressure_test` | `True` | 2 | 2 | 3.584044 | 3.584044 | 3.609590 | 3.584044 | 164186.500000 | 73139.500000 | `True` | `False` |
| `multi_holdout_supported` | `True` | 3 | 14 | 23.810162 | 13.126286 | 29.006614 | 12.559599 | 233341.000000 | 102219.666667 | `True` | `False` |
| `multi_holdout_ge3` | `True` | 3 | 14 | 23.810162 | 13.126286 | 29.006614 | 12.559599 | 233341.000000 | 102219.666667 | `True` | `False` |
| `rmse_le6` | `True` | 3 | 6 | 3.707267 | 3.510059 | 3.842431 | 3.436073 | 200085.000000 | 87786.333333 | `True` | `False` |
| `rmse_gt6` | `True` | 2 | 10 | 33.738387 | 18.008384 | 34.229876 | 16.238604 | 214070.500000 | 94789.500000 | `True` | `False` |
| `strong_wind_subset` | `True` | 5 | 16 | 15.719715 | 9.309389 | 27.163199 | 11.437655 | 205679.200000 | 90587.600000 | `True` | `False` |
| `vertical_mismatch_subset` | `True` | 5 | 16 | 15.719715 | 9.309389 | 27.163199 | 11.437655 | 205679.200000 | 90587.600000 | `True` | `False` |
