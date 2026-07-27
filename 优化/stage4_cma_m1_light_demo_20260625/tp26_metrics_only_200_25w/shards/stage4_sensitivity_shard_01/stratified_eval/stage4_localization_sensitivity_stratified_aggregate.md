# Stage4 Stratified Evaluation

Official RMSE/MAE comes only from `eval_holdout_only` and its holdout subsets. `no_holdout_unverified_reconstruction` keeps coverage and risk diagnostics but does not contribute to official error metrics.

- expected frames: `0`
- validation failures: `0`

| stratum | official | frames | holdout points | frame RMSE | frame MAE | weighted RMSE | weighted MAE | mean effective voxels | mean low-conf fill | leakage | motion used |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| `all_frames_original` | `False` | 4 | 7 |  |  |  |  | 255532.750000 | 103797.250000 | `True` | `False` |
| `eval_holdout_only` | `True` | 4 | 7 | 5.806426 | 5.089629 | 6.734667 | 5.169753 | 255532.750000 | 103797.250000 | `True` | `False` |
| `no_holdout_unverified_reconstruction` | `False` | 0 | 0 |  |  |  |  |  |  | `True` | `False` |
| `single_holdout_pressure_test` | `True` | 2 | 2 | 4.377046 | 4.377046 | 5.316173 | 4.377046 | 241569.000000 | 95613.500000 | `True` | `False` |
| `multi_holdout_supported` | `True` | 2 | 5 | 7.235806 | 5.802212 | 7.224497 | 5.486836 | 269496.500000 | 111981.000000 | `True` | `False` |
| `multi_holdout_ge3` | `True` | 1 | 3 | 4.399135 | 4.225331 | 4.399135 | 4.225331 | 251099.000000 | 112105.000000 | `True` | `False` |
| `rmse_le6` | `True` | 2 | 4 | 2.879518 | 2.792616 | 3.869965 | 3.508973 | 216823.500000 | 94688.000000 | `True` | `False` |
| `rmse_gt6` | `True` | 2 | 3 | 8.733334 | 7.386642 | 9.266133 | 7.384126 | 294242.000000 | 112906.500000 | `True` | `False` |
| `strong_wind_subset` | `True` | 4 | 7 | 5.806426 | 5.089629 | 6.734667 | 5.169753 | 255532.750000 | 103797.250000 | `True` | `False` |
| `vertical_mismatch_subset` | `True` | 4 | 7 | 5.806426 | 5.089629 | 6.734667 | 5.169753 | 255532.750000 | 103797.250000 | `True` | `False` |
| `all_frames_original` | `False` | 4 | 13 |  |  |  |  | 196003.750000 | 84685.750000 | `True` | `False` |
| `eval_holdout_only` | `True` | 4 | 13 | 8.499203 | 7.427495 | 13.203509 | 8.501074 | 196003.750000 | 84685.750000 | `True` | `False` |
| `no_holdout_unverified_reconstruction` | `False` | 0 | 0 |  |  |  |  |  |  | `True` | `False` |
| `single_holdout_pressure_test` | `True` | 1 | 1 | 2.775321 | 2.775321 | 2.775321 | 2.775321 | 160916.000000 | 74659.000000 | `True` | `False` |
| `multi_holdout_supported` | `True` | 3 | 12 | 10.407164 | 8.978220 | 13.719275 | 8.978220 | 207699.666667 | 88028.000000 | `True` | `False` |
| `multi_holdout_ge3` | `True` | 3 | 12 | 10.407164 | 8.978220 | 13.719275 | 8.978220 | 207699.666667 | 88028.000000 | `True` | `False` |
| `rmse_le6` | `True` | 3 | 9 | 3.649808 | 3.238856 | 3.966469 | 3.393368 | 165831.666667 | 73881.333333 | `True` | `False` |
| `rmse_gt6` | `True` | 1 | 4 | 23.047390 | 19.993411 | 23.047390 | 19.993411 | 286520.000000 | 117099.000000 | `True` | `False` |
| `strong_wind_subset` | `True` | 4 | 13 | 8.499203 | 7.427495 | 13.203509 | 8.501074 | 196003.750000 | 84685.750000 | `True` | `False` |
| `vertical_mismatch_subset` | `True` | 4 | 13 | 8.499203 | 7.427495 | 13.203509 | 8.501074 | 196003.750000 | 84685.750000 | `True` | `False` |
