# Stage4 Stratified Evaluation

Official RMSE/MAE comes only from `eval_holdout_only` and its holdout subsets. `no_holdout_unverified_reconstruction` keeps coverage and risk diagnostics but does not contribute to official error metrics.

- expected frames: `0`
- validation failures: `0`

| stratum | official | frames | holdout points | frame RMSE | frame MAE | weighted RMSE | weighted MAE | mean effective voxels | mean low-conf fill | leakage | motion used |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| `all_frames_original` | `False` | 4 | 13 |  |  |  |  | 200096.250000 | 86398.000000 | `True` | `False` |
| `eval_holdout_only` | `True` | 4 | 13 | 6.746172 | 6.006112 | 6.835833 | 5.166273 | 200096.250000 | 86398.000000 | `True` | `False` |
| `no_holdout_unverified_reconstruction` | `False` | 0 | 0 |  |  |  |  |  |  | `True` | `False` |
| `single_holdout_pressure_test` | `True` | 1 | 1 | 9.954531 | 9.954531 | 9.954531 | 9.954531 | 209077.000000 | 83389.000000 | `True` | `False` |
| `multi_holdout_supported` | `True` | 3 | 12 | 5.676719 | 4.689973 | 6.508835 | 4.767252 | 197102.666667 | 87401.000000 | `True` | `False` |
| `multi_holdout_ge3` | `True` | 3 | 12 | 5.676719 | 4.689973 | 6.508835 | 4.767252 | 197102.666667 | 87401.000000 | `True` | `False` |
| `rmse_le6` | `True` | 2 | 7 | 4.144076 | 3.813218 | 4.247118 | 3.569944 | 192545.000000 | 84064.500000 | `True` | `False` |
| `rmse_gt6` | `True` | 2 | 6 | 9.348267 | 8.199007 | 8.955499 | 7.028657 | 207647.500000 | 88731.500000 | `True` | `False` |
| `strong_wind_subset` | `True` | 4 | 13 | 6.746172 | 6.006112 | 6.835833 | 5.166273 | 200096.250000 | 86398.000000 | `True` | `False` |
| `vertical_mismatch_subset` | `True` | 4 | 13 | 6.746172 | 6.006112 | 6.835833 | 5.166273 | 200096.250000 | 86398.000000 | `True` | `False` |
| `all_frames_original` | `False` | 4 | 8 |  |  |  |  | 222342.000000 | 92829.500000 | `True` | `False` |
| `eval_holdout_only` | `True` | 4 | 8 | 3.655311 | 3.538919 | 4.465765 | 4.016494 | 222342.000000 | 92829.500000 | `True` | `False` |
| `no_holdout_unverified_reconstruction` | `False` | 0 | 0 |  |  |  |  |  |  | `True` | `False` |
| `single_holdout_pressure_test` | `True` | 1 | 1 | 0.820973 | 0.820973 | 0.820973 | 0.820973 | 202523.000000 | 88988.000000 | `True` | `False` |
| `multi_holdout_supported` | `True` | 3 | 7 | 4.600090 | 4.444901 | 4.764009 | 4.472997 | 228948.333333 | 94110.000000 | `True` | `False` |
| `multi_holdout_ge3` | `True` | 1 | 3 | 4.916079 | 4.641572 | 4.916079 | 4.641572 | 197037.000000 | 77518.000000 | `True` | `False` |
| `rmse_le6` | `True` | 4 | 8 | 3.655311 | 3.538919 | 4.465765 | 4.016494 | 222342.000000 | 92829.500000 | `True` | `False` |
| `rmse_gt6` | `True` | 0 | 0 |  |  |  |  |  |  | `True` | `False` |
| `strong_wind_subset` | `True` | 4 | 8 | 3.655311 | 3.538919 | 4.465765 | 4.016494 | 222342.000000 | 92829.500000 | `True` | `False` |
| `vertical_mismatch_subset` | `True` | 4 | 8 | 3.655311 | 3.538919 | 4.465765 | 4.016494 | 222342.000000 | 92829.500000 | `True` | `False` |
