# Stage4 Stratified Evaluation

Official RMSE/MAE comes only from `eval_holdout_only` and its holdout subsets. `no_holdout_unverified_reconstruction` keeps coverage and risk diagnostics but does not contribute to official error metrics.

- expected frames: `0`
- validation failures: `0`

| stratum | official | frames | holdout points | frame RMSE | frame MAE | weighted RMSE | weighted MAE | mean effective voxels | mean low-conf fill | leakage | motion used |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| `all_frames_original` | `False` | 4 | 19 |  |  |  |  | 199844.500000 | 89056.750000 | `True` | `False` |
| `eval_holdout_only` | `True` | 4 | 19 | 16.945880 | 10.378086 | 21.552579 | 9.960156 | 199844.500000 | 89056.750000 | `True` | `False` |
| `no_holdout_unverified_reconstruction` | `False` | 0 | 0 |  |  |  |  |  |  | `True` | `False` |
| `single_holdout_pressure_test` | `True` | 1 | 1 | 6.289395 | 6.289395 | 6.289395 | 6.289395 | 221308.000000 | 101800.000000 | `True` | `False` |
| `multi_holdout_supported` | `True` | 3 | 18 | 20.498041 | 11.740983 | 22.093492 | 10.164087 | 192690.000000 | 84809.000000 | `True` | `False` |
| `multi_holdout_ge3` | `True` | 3 | 18 | 20.498041 | 11.740983 | 22.093492 | 10.164087 | 192690.000000 | 84809.000000 | `True` | `False` |
| `rmse_le6` | `True` | 1 | 6 | 4.192221 | 3.454338 | 4.192221 | 3.454338 | 216919.000000 | 95286.000000 | `True` | `False` |
| `rmse_gt6` | `True` | 3 | 13 | 21.197099 | 12.686002 | 25.899676 | 12.962842 | 194153.000000 | 86980.333333 | `True` | `False` |
| `strong_wind_subset` | `True` | 4 | 19 | 16.945880 | 10.378086 | 21.552579 | 9.960156 | 199844.500000 | 89056.750000 | `True` | `False` |
| `vertical_mismatch_subset` | `True` | 4 | 19 | 16.945880 | 10.378086 | 21.552579 | 9.960156 | 199844.500000 | 89056.750000 | `True` | `False` |
| `all_frames_original` | `False` | 4 | 10 |  |  |  |  | 232463.250000 | 97453.750000 | `True` | `False` |
| `eval_holdout_only` | `True` | 4 | 10 | 5.043259 | 4.717498 | 5.098557 | 4.352461 | 232463.250000 | 97453.750000 | `True` | `False` |
| `no_holdout_unverified_reconstruction` | `False` | 0 | 0 |  |  |  |  |  |  | `True` | `False` |
| `single_holdout_pressure_test` | `True` | 1 | 1 | 6.542680 | 6.542680 | 6.542680 | 6.542680 | 200669.000000 | 92743.000000 | `True` | `False` |
| `multi_holdout_supported` | `True` | 3 | 9 | 4.543451 | 4.109103 | 4.911960 | 4.109103 | 243061.333333 | 99024.000000 | `True` | `False` |
| `multi_holdout_ge3` | `True` | 3 | 9 | 4.543451 | 4.109103 | 4.911960 | 4.109103 | 243061.333333 | 99024.000000 | `True` | `False` |
| `rmse_le6` | `True` | 2 | 6 | 3.228820 | 2.919535 | 3.235292 | 2.919535 | 191698.000000 | 80784.500000 | `True` | `False` |
| `rmse_gt6` | `True` | 2 | 4 | 6.857697 | 6.515460 | 7.020508 | 6.501850 | 273228.500000 | 114123.000000 | `True` | `False` |
| `strong_wind_subset` | `True` | 4 | 10 | 5.043259 | 4.717498 | 5.098557 | 4.352461 | 232463.250000 | 97453.750000 | `True` | `False` |
| `vertical_mismatch_subset` | `True` | 4 | 10 | 5.043259 | 4.717498 | 5.098557 | 4.352461 | 232463.250000 | 97453.750000 | `True` | `False` |
