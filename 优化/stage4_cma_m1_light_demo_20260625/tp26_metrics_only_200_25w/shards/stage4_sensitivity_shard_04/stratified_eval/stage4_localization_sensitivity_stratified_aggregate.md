# Stage4 Stratified Evaluation

Official RMSE/MAE comes only from `eval_holdout_only` and its holdout subsets. `no_holdout_unverified_reconstruction` keeps coverage and risk diagnostics but does not contribute to official error metrics.

- expected frames: `0`
- validation failures: `0`

| stratum | official | frames | holdout points | frame RMSE | frame MAE | weighted RMSE | weighted MAE | mean effective voxels | mean low-conf fill | leakage | motion used |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| `all_frames_original` | `False` | 4 | 7 |  |  |  |  | 214628.000000 | 89014.250000 | `True` | `False` |
| `eval_holdout_only` | `True` | 4 | 7 | 8.439932 | 7.616891 | 10.400759 | 8.118413 | 214628.000000 | 89014.250000 | `True` | `False` |
| `no_holdout_unverified_reconstruction` | `False` | 0 | 0 |  |  |  |  |  |  | `True` | `False` |
| `single_holdout_pressure_test` | `True` | 1 | 1 | 4.106237 | 4.106237 | 4.106237 | 4.106237 | 213313.000000 | 85495.000000 | `True` | `False` |
| `multi_holdout_supported` | `True` | 3 | 6 | 9.884497 | 8.787109 | 11.108325 | 8.787109 | 215066.333333 | 90187.333333 | `True` | `False` |
| `multi_holdout_ge3` | `True` | 0 | 0 |  |  |  |  |  |  | `True` | `False` |
| `rmse_le6` | `True` | 2 | 3 | 3.946536 | 3.945440 | 3.896213 | 3.891841 | 215540.500000 | 88716.500000 | `True` | `False` |
| `rmse_gt6` | `True` | 2 | 4 | 12.933329 | 11.288342 | 13.338751 | 11.288342 | 213715.500000 | 89312.000000 | `True` | `False` |
| `strong_wind_subset` | `True` | 4 | 7 | 8.439932 | 7.616891 | 10.400759 | 8.118413 | 214628.000000 | 89014.250000 | `True` | `False` |
| `vertical_mismatch_subset` | `True` | 4 | 7 | 8.439932 | 7.616891 | 10.400759 | 8.118413 | 214628.000000 | 89014.250000 | `True` | `False` |
| `all_frames_original` | `False` | 4 | 9 |  |  |  |  | 216180.750000 | 91211.250000 | `True` | `False` |
| `eval_holdout_only` | `True` | 4 | 9 | 3.373287 | 3.270176 | 3.254546 | 2.932973 | 216180.750000 | 91211.250000 | `True` | `False` |
| `no_holdout_unverified_reconstruction` | `False` | 0 | 0 |  |  |  |  |  |  | `True` | `False` |
| `single_holdout_pressure_test` | `True` | 2 | 2 | 3.712890 | 3.712890 | 3.869421 | 3.712890 | 229001.500000 | 97759.000000 | `True` | `False` |
| `multi_holdout_supported` | `True` | 2 | 7 | 3.033684 | 2.827463 | 3.056230 | 2.710139 | 203360.000000 | 84663.500000 | `True` | `False` |
| `multi_holdout_ge3` | `True` | 2 | 7 | 3.033684 | 2.827463 | 3.056230 | 2.710139 | 203360.000000 | 84663.500000 | `True` | `False` |
| `rmse_le6` | `True` | 4 | 9 | 3.373287 | 3.270176 | 3.254546 | 2.932973 | 216180.750000 | 91211.250000 | `True` | `False` |
| `rmse_gt6` | `True` | 0 | 0 |  |  |  |  |  |  | `True` | `False` |
| `strong_wind_subset` | `True` | 4 | 9 | 3.373287 | 3.270176 | 3.254546 | 2.932973 | 216180.750000 | 91211.250000 | `True` | `False` |
| `vertical_mismatch_subset` | `True` | 4 | 9 | 3.373287 | 3.270176 | 3.254546 | 2.932973 | 216180.750000 | 91211.250000 | `True` | `False` |
