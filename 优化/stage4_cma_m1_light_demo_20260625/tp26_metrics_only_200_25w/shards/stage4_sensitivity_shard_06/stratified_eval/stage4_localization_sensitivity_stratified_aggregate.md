# Stage4 Stratified Evaluation

Official RMSE/MAE comes only from `eval_holdout_only` and its holdout subsets. `no_holdout_unverified_reconstruction` keeps coverage and risk diagnostics but does not contribute to official error metrics.

- expected frames: `0`
- validation failures: `0`

| stratum | official | frames | holdout points | frame RMSE | frame MAE | weighted RMSE | weighted MAE | mean effective voxels | mean low-conf fill | leakage | motion used |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| `all_frames_original` | `False` | 3 | 5 |  |  |  |  | 211865.666667 | 86027.666667 | `True` | `False` |
| `eval_holdout_only` | `True` | 3 | 5 | 8.375104 | 7.884492 | 8.429522 | 6.519175 | 211865.666667 | 86027.666667 | `True` | `False` |
| `no_holdout_unverified_reconstruction` | `False` | 0 | 0 |  |  |  |  |  |  | `True` | `False` |
| `single_holdout_pressure_test` | `True` | 1 | 1 | 14.711078 | 14.711078 | 14.711078 | 14.711078 | 222079.000000 | 98350.000000 | `True` | `False` |
| `multi_holdout_supported` | `True` | 2 | 4 | 5.207117 | 4.471199 | 5.892121 | 4.471199 | 206759.000000 | 79866.500000 | `True` | `False` |
| `multi_holdout_ge3` | `True` | 0 | 0 |  |  |  |  |  |  | `True` | `False` |
| `rmse_le6` | `True` | 1 | 2 | 2.449758 | 2.231437 | 2.449758 | 2.231437 | 171186.000000 | 73772.000000 | `True` | `False` |
| `rmse_gt6` | `True` | 2 | 3 | 11.337776 | 10.711020 | 10.697064 | 9.377667 | 232205.500000 | 92155.500000 | `True` | `False` |
| `strong_wind_subset` | `True` | 3 | 5 | 8.375104 | 7.884492 | 8.429522 | 6.519175 | 211865.666667 | 86027.666667 | `True` | `False` |
| `vertical_mismatch_subset` | `True` | 3 | 5 | 8.375104 | 7.884492 | 8.429522 | 6.519175 | 211865.666667 | 86027.666667 | `True` | `False` |
| `all_frames_original` | `False` | 5 | 13 |  |  |  |  | 208331.400000 | 89095.000000 | `True` | `False` |
| `eval_holdout_only` | `True` | 5 | 13 | 8.397036 | 7.747605 | 11.491410 | 6.690118 | 208331.400000 | 89095.000000 | `True` | `False` |
| `no_holdout_unverified_reconstruction` | `False` | 0 | 0 |  |  |  |  |  |  | `True` | `False` |
| `single_holdout_pressure_test` | `True` | 1 | 1 | 3.070605 | 3.070605 | 3.070605 | 3.070605 | 168901.000000 | 82817.000000 | `True` | `False` |
| `multi_holdout_supported` | `True` | 4 | 12 | 9.728643 | 8.916855 | 11.927748 | 6.991744 | 218189.000000 | 90664.500000 | `True` | `False` |
| `multi_holdout_ge3` | `True` | 3 | 10 | 3.660703 | 3.318890 | 3.831566 | 3.247943 | 240830.333333 | 97493.333333 | `True` | `False` |
| `rmse_le6` | `True` | 4 | 11 | 3.513179 | 3.256819 | 3.768742 | 3.231821 | 222848.000000 | 93824.250000 | `True` | `False` |
| `rmse_gt6` | `True` | 1 | 2 | 27.932464 | 25.710751 | 27.932464 | 25.710751 | 150265.000000 | 70178.000000 | `True` | `False` |
| `strong_wind_subset` | `True` | 5 | 13 | 8.397036 | 7.747605 | 11.491410 | 6.690118 | 208331.400000 | 89095.000000 | `True` | `False` |
| `vertical_mismatch_subset` | `True` | 5 | 13 | 8.397036 | 7.747605 | 11.491410 | 6.690118 | 208331.400000 | 89095.000000 | `True` | `False` |
