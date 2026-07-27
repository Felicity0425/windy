# Stage4 Stratified Evaluation

Official RMSE/MAE comes only from `eval_holdout_only` and its holdout subsets. `no_holdout_unverified_reconstruction` keeps coverage and risk diagnostics but does not contribute to official error metrics.

- expected frames: `0`
- validation failures: `0`

| stratum | official | frames | holdout points | frame RMSE | frame MAE | weighted RMSE | weighted MAE | mean effective voxels | mean low-conf fill | leakage | motion used |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| `all_frames_original` | `False` | 6 | 12 |  |  |  |  | 258698.166667 | 102509.333333 | `True` | `False` |
| `eval_holdout_only` | `True` | 6 | 12 | 4.925241 | 4.425040 | 7.996448 | 5.498124 | 258698.166667 | 102509.333333 | `True` | `False` |
| `no_holdout_unverified_reconstruction` | `False` | 0 | 0 |  |  |  |  |  |  | `True` | `False` |
| `single_holdout_pressure_test` | `True` | 2 | 2 | 1.873351 | 1.873351 | 1.890952 | 1.873351 | 212464.000000 | 93207.500000 | `True` | `False` |
| `multi_holdout_supported` | `True` | 4 | 10 | 6.451186 | 5.700884 | 8.718755 | 6.223078 | 281815.250000 | 107160.250000 | `True` | `False` |
| `multi_holdout_ge3` | `True` | 2 | 6 | 9.199049 | 8.311854 | 10.789118 | 8.311854 | 319482.000000 | 118390.000000 | `True` | `False` |
| `rmse_le6` | `True` | 5 | 9 | 2.942959 | 2.696213 | 3.447054 | 2.974441 | 242245.400000 | 98370.000000 | `True` | `False` |
| `rmse_gt6` | `True` | 1 | 3 | 14.836651 | 13.069173 | 14.836651 | 13.069173 | 340962.000000 | 123206.000000 | `True` | `False` |
| `strong_wind_subset` | `True` | 6 | 12 | 4.925241 | 4.425040 | 7.996448 | 5.498124 | 258698.166667 | 102509.333333 | `True` | `False` |
| `vertical_mismatch_subset` | `True` | 6 | 12 | 4.925241 | 4.425040 | 7.996448 | 5.498124 | 258698.166667 | 102509.333333 | `True` | `False` |
| `all_frames_original` | `False` | 2 | 2 |  |  |  |  | 141801.000000 | 63297.000000 | `True` | `False` |
| `eval_holdout_only` | `True` | 2 | 2 | 1.959425 | 1.959425 | 2.044028 | 1.959425 | 141801.000000 | 63297.000000 | `True` | `False` |
| `no_holdout_unverified_reconstruction` | `False` | 0 | 0 |  |  |  |  |  |  | `True` | `False` |
| `single_holdout_pressure_test` | `True` | 2 | 2 | 1.959425 | 1.959425 | 2.044028 | 1.959425 | 141801.000000 | 63297.000000 | `True` | `False` |
| `multi_holdout_supported` | `True` | 0 | 0 |  |  |  |  |  |  | `True` | `False` |
| `multi_holdout_ge3` | `True` | 0 | 0 |  |  |  |  |  |  | `True` | `False` |
| `rmse_le6` | `True` | 2 | 2 | 1.959425 | 1.959425 | 2.044028 | 1.959425 | 141801.000000 | 63297.000000 | `True` | `False` |
| `rmse_gt6` | `True` | 0 | 0 |  |  |  |  |  |  | `True` | `False` |
| `strong_wind_subset` | `True` | 2 | 2 | 1.959425 | 1.959425 | 2.044028 | 1.959425 | 141801.000000 | 63297.000000 | `True` | `False` |
| `vertical_mismatch_subset` | `True` | 2 | 2 | 1.959425 | 1.959425 | 2.044028 | 1.959425 | 141801.000000 | 63297.000000 | `True` | `False` |
