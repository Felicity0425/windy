# Stage4 Stratified Evaluation

Official RMSE/MAE comes only from `eval_holdout_only` and its holdout subsets. `no_holdout_unverified_reconstruction` keeps coverage and risk diagnostics but does not contribute to official error metrics.

- expected frames: `0`
- validation failures: `0`

| stratum | official | frames | holdout points | frame RMSE | frame MAE | weighted RMSE | weighted MAE | mean effective voxels | mean low-conf fill | leakage | motion used |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| `all_frames_original` | `False` | 3 | 7 |  |  |  |  | 278841.666667 | 103487.333333 | `True` | `False` |
| `eval_holdout_only` | `True` | 3 | 7 | 4.704290 | 4.204724 | 4.693810 | 3.942640 | 278841.666667 | 103487.333333 | `True` | `False` |
| `no_holdout_unverified_reconstruction` | `False` | 0 | 0 |  |  |  |  |  |  | `True` | `False` |
| `single_holdout_pressure_test` | `True` | 0 | 0 |  |  |  |  |  |  | `True` | `False` |
| `multi_holdout_supported` | `True` | 3 | 7 | 4.704290 | 4.204724 | 4.693810 | 3.942640 | 278841.666667 | 103487.333333 | `True` | `False` |
| `multi_holdout_ge3` | `True` | 1 | 3 | 2.660535 | 2.370135 | 2.660535 | 2.370135 | 300074.000000 | 107180.000000 | `True` | `False` |
| `rmse_le6` | `True` | 2 | 5 | 3.855009 | 3.615201 | 3.800786 | 3.366188 | 282076.500000 | 103721.500000 | `True` | `False` |
| `rmse_gt6` | `True` | 1 | 2 | 6.402853 | 5.383770 | 6.402853 | 5.383770 | 272372.000000 | 103019.000000 | `True` | `False` |
| `strong_wind_subset` | `True` | 3 | 7 | 4.704290 | 4.204724 | 4.693810 | 3.942640 | 278841.666667 | 103487.333333 | `True` | `False` |
| `vertical_mismatch_subset` | `True` | 3 | 7 | 4.704290 | 4.204724 | 4.693810 | 3.942640 | 278841.666667 | 103487.333333 | `True` | `False` |
| `all_frames_original` | `False` | 5 | 15 |  |  |  |  | 175409.000000 | 76926.200000 | `True` | `False` |
| `eval_holdout_only` | `True` | 5 | 15 | 11.310358 | 8.834959 | 24.950012 | 13.459656 | 175409.000000 | 76926.200000 | `True` | `False` |
| `no_holdout_unverified_reconstruction` | `False` | 0 | 0 |  |  |  |  |  |  | `True` | `False` |
| `single_holdout_pressure_test` | `True` | 1 | 1 | 4.337906 | 4.337906 | 4.337906 | 4.337906 | 162724.000000 | 72351.000000 | `True` | `False` |
| `multi_holdout_supported` | `True` | 4 | 14 | 13.053471 | 9.959222 | 25.799680 | 14.111210 | 178580.250000 | 78070.000000 | `True` | `False` |
| `multi_holdout_ge3` | `True` | 2 | 10 | 21.780730 | 15.752361 | 30.399357 | 18.089261 | 209101.500000 | 90421.500000 | `True` | `False` |
| `rmse_le6` | `True` | 4 | 9 | 4.369450 | 4.184483 | 4.433295 | 4.141520 | 169931.250000 | 75573.000000 | `True` | `False` |
| `rmse_gt6` | `True` | 1 | 6 | 39.073989 | 27.436861 | 39.073989 | 27.436861 | 197320.000000 | 82339.000000 | `True` | `False` |
| `strong_wind_subset` | `True` | 5 | 15 | 11.310358 | 8.834959 | 24.950012 | 13.459656 | 175409.000000 | 76926.200000 | `True` | `False` |
| `vertical_mismatch_subset` | `True` | 5 | 15 | 11.310358 | 8.834959 | 24.950012 | 13.459656 | 175409.000000 | 76926.200000 | `True` | `False` |
