# Stage4 Stratified Evaluation

Official RMSE/MAE comes only from `eval_holdout_only` and its holdout subsets. `no_holdout_unverified_reconstruction` keeps coverage and risk diagnostics but does not contribute to official error metrics.

- expected frames: `0`
- validation failures: `0`

| stratum | official | frames | holdout points | frame RMSE | frame MAE | weighted RMSE | weighted MAE | mean effective voxels | mean low-conf fill | leakage | motion used |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| `all_frames_original` | `False` | 6 | 11 |  |  |  |  | 233346.666667 | 93653.166667 | `True` | `False` |
| `eval_holdout_only` | `True` | 6 | 11 | 5.299688 | 4.829691 | 5.582561 | 4.371165 | 233346.666667 | 93653.166667 | `True` | `False` |
| `no_holdout_unverified_reconstruction` | `False` | 0 | 0 |  |  |  |  |  |  | `True` | `False` |
| `single_holdout_pressure_test` | `True` | 2 | 2 | 6.545832 | 6.545832 | 7.422326 | 6.545832 | 232990.500000 | 97913.000000 | `True` | `False` |
| `multi_holdout_supported` | `True` | 4 | 9 | 4.676615 | 3.971620 | 5.084104 | 3.887906 | 233524.750000 | 91523.250000 | `True` | `False` |
| `multi_holdout_ge3` | `True` | 1 | 3 | 4.342839 | 3.218190 | 4.342839 | 3.218190 | 239108.000000 | 103255.000000 | `True` | `False` |
| `rmse_le6` | `True` | 4 | 8 | 3.384055 | 3.050211 | 3.655059 | 3.071631 | 223022.750000 | 86518.500000 | `True` | `False` |
| `rmse_gt6` | `True` | 2 | 3 | 9.130953 | 8.388651 | 8.868281 | 7.836590 | 253994.500000 | 107922.500000 | `True` | `False` |
| `strong_wind_subset` | `True` | 6 | 11 | 5.299688 | 4.829691 | 5.582561 | 4.371165 | 233346.666667 | 93653.166667 | `True` | `False` |
| `vertical_mismatch_subset` | `True` | 6 | 11 | 5.299688 | 4.829691 | 5.582561 | 4.371165 | 233346.666667 | 93653.166667 | `True` | `False` |
| `all_frames_original` | `False` | 2 | 6 |  |  |  |  | 165519.500000 | 74138.000000 | `True` | `False` |
| `eval_holdout_only` | `True` | 2 | 6 | 45.090901 | 44.931919 | 35.316279 | 17.553199 | 165519.500000 | 74138.000000 | `True` | `False` |
| `no_holdout_unverified_reconstruction` | `False` | 0 | 0 |  |  |  |  |  |  | `True` | `False` |
| `single_holdout_pressure_test` | `True` | 1 | 1 | 86.000000 | 86.000000 | 86.000000 | 86.000000 | 169456.000000 | 78685.000000 | `True` | `False` |
| `multi_holdout_supported` | `True` | 1 | 5 | 4.181801 | 3.863838 | 4.181801 | 3.863838 | 161583.000000 | 69591.000000 | `True` | `False` |
| `multi_holdout_ge3` | `True` | 1 | 5 | 4.181801 | 3.863838 | 4.181801 | 3.863838 | 161583.000000 | 69591.000000 | `True` | `False` |
| `rmse_le6` | `True` | 1 | 5 | 4.181801 | 3.863838 | 4.181801 | 3.863838 | 161583.000000 | 69591.000000 | `True` | `False` |
| `rmse_gt6` | `True` | 1 | 1 | 86.000000 | 86.000000 | 86.000000 | 86.000000 | 169456.000000 | 78685.000000 | `True` | `False` |
| `strong_wind_subset` | `True` | 2 | 6 | 45.090901 | 44.931919 | 35.316279 | 17.553199 | 165519.500000 | 74138.000000 | `True` | `False` |
| `vertical_mismatch_subset` | `True` | 2 | 6 | 45.090901 | 44.931919 | 35.316279 | 17.553199 | 165519.500000 | 74138.000000 | `True` | `False` |
