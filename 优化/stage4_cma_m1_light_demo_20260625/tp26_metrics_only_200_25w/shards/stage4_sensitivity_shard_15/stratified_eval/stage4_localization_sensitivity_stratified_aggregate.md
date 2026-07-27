# Stage4 Stratified Evaluation

Official RMSE/MAE comes only from `eval_holdout_only` and its holdout subsets. `no_holdout_unverified_reconstruction` keeps coverage and risk diagnostics but does not contribute to official error metrics.

- expected frames: `0`
- validation failures: `0`

| stratum | official | frames | holdout points | frame RMSE | frame MAE | weighted RMSE | weighted MAE | mean effective voxels | mean low-conf fill | leakage | motion used |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| `all_frames_original` | `False` | 4 | 9 |  |  |  |  | 223938.000000 | 91707.000000 | `True` | `False` |
| `eval_holdout_only` | `True` | 4 | 9 | 2.904684 | 2.631768 | 3.118458 | 2.659516 | 223938.000000 | 91707.000000 | `True` | `False` |
| `no_holdout_unverified_reconstruction` | `False` | 0 | 0 |  |  |  |  |  |  | `True` | `False` |
| `single_holdout_pressure_test` | `True` | 0 | 0 |  |  |  |  |  |  | `True` | `False` |
| `multi_holdout_supported` | `True` | 4 | 9 | 2.904684 | 2.631768 | 3.118458 | 2.659516 | 223938.000000 | 91707.000000 | `True` | `False` |
| `multi_holdout_ge3` | `True` | 1 | 3 | 3.188348 | 2.881497 | 3.188348 | 2.881497 | 279926.000000 | 104527.000000 | `True` | `False` |
| `rmse_le6` | `True` | 4 | 9 | 2.904684 | 2.631768 | 3.118458 | 2.659516 | 223938.000000 | 91707.000000 | `True` | `False` |
| `rmse_gt6` | `True` | 0 | 0 |  |  |  |  |  |  | `True` | `False` |
| `strong_wind_subset` | `True` | 4 | 9 | 2.904684 | 2.631768 | 3.118458 | 2.659516 | 223938.000000 | 91707.000000 | `True` | `False` |
| `vertical_mismatch_subset` | `True` | 4 | 9 | 2.904684 | 2.631768 | 3.118458 | 2.659516 | 223938.000000 | 91707.000000 | `True` | `False` |
| `all_frames_original` | `False` | 4 | 19 |  |  |  |  | 217342.500000 | 91734.250000 | `True` | `False` |
| `eval_holdout_only` | `True` | 4 | 19 | 9.830909 | 6.522121 | 12.635553 | 6.075342 | 217342.500000 | 91734.250000 | `True` | `False` |
| `no_holdout_unverified_reconstruction` | `False` | 0 | 0 |  |  |  |  |  |  | `True` | `False` |
| `single_holdout_pressure_test` | `True` | 0 | 0 |  |  |  |  |  |  | `True` | `False` |
| `multi_holdout_supported` | `True` | 4 | 19 | 9.830909 | 6.522121 | 12.635553 | 6.075342 | 217342.500000 | 91734.250000 | `True` | `False` |
| `multi_holdout_ge3` | `True` | 4 | 19 | 9.830909 | 6.522121 | 12.635553 | 6.075342 | 217342.500000 | 91734.250000 | `True` | `False` |
| `rmse_le6` | `True` | 3 | 15 | 4.410210 | 3.366535 | 4.546847 | 3.431733 | 236965.333333 | 99601.000000 | `True` | `False` |
| `rmse_gt6` | `True` | 1 | 4 | 26.093004 | 15.988878 | 26.093004 | 15.988878 | 158474.000000 | 68134.000000 | `True` | `False` |
| `strong_wind_subset` | `True` | 4 | 19 | 9.830909 | 6.522121 | 12.635553 | 6.075342 | 217342.500000 | 91734.250000 | `True` | `False` |
| `vertical_mismatch_subset` | `True` | 4 | 19 | 9.830909 | 6.522121 | 12.635553 | 6.075342 | 217342.500000 | 91734.250000 | `True` | `False` |
