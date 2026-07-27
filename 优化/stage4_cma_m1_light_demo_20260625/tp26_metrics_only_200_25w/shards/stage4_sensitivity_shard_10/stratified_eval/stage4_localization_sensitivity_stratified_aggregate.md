# Stage4 Stratified Evaluation

Official RMSE/MAE comes only from `eval_holdout_only` and its holdout subsets. `no_holdout_unverified_reconstruction` keeps coverage and risk diagnostics but does not contribute to official error metrics.

- expected frames: `0`
- validation failures: `0`

| stratum | official | frames | holdout points | frame RMSE | frame MAE | weighted RMSE | weighted MAE | mean effective voxels | mean low-conf fill | leakage | motion used |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| `all_frames_original` | `False` | 6 | 12 |  |  |  |  | 222443.166667 | 94660.833333 | `True` | `False` |
| `eval_holdout_only` | `True` | 6 | 12 | 12.465994 | 10.050440 | 19.509511 | 10.007824 | 222443.166667 | 94660.833333 | `True` | `False` |
| `no_holdout_unverified_reconstruction` | `False` | 0 | 0 |  |  |  |  |  |  | `True` | `False` |
| `single_holdout_pressure_test` | `True` | 1 | 1 | 4.989545 | 4.989545 | 4.989545 | 4.989545 | 143707.000000 | 59675.000000 | `True` | `False` |
| `multi_holdout_supported` | `True` | 5 | 11 | 13.961284 | 11.062619 | 20.321410 | 10.464032 | 238190.400000 | 101658.000000 | `True` | `False` |
| `multi_holdout_ge3` | `True` | 1 | 3 | 4.653620 | 4.478162 | 4.653620 | 4.478162 | 197792.000000 | 86899.000000 | `True` | `False` |
| `rmse_le6` | `True` | 4 | 8 | 4.895806 | 4.501712 | 4.856594 | 4.437789 | 202625.250000 | 84847.250000 | `True` | `False` |
| `rmse_gt6` | `True` | 2 | 4 | 27.606370 | 21.147896 | 33.086101 | 21.147896 | 262079.000000 | 114288.000000 | `True` | `False` |
| `strong_wind_subset` | `True` | 6 | 12 | 12.465994 | 10.050440 | 19.509511 | 10.007824 | 222443.166667 | 94660.833333 | `True` | `False` |
| `vertical_mismatch_subset` | `True` | 6 | 12 | 12.465994 | 10.050440 | 19.509511 | 10.007824 | 222443.166667 | 94660.833333 | `True` | `False` |
| `all_frames_original` | `False` | 2 | 10 |  |  |  |  | 244045.000000 | 102465.000000 | `True` | `False` |
| `eval_holdout_only` | `True` | 2 | 10 | 12.839012 | 10.340503 | 14.443173 | 8.844416 | 244045.000000 | 102465.000000 | `True` | `False` |
| `no_holdout_unverified_reconstruction` | `False` | 0 | 0 |  |  |  |  |  |  | `True` | `False` |
| `single_holdout_pressure_test` | `True` | 0 | 0 |  |  |  |  |  |  | `True` | `False` |
| `multi_holdout_supported` | `True` | 2 | 10 | 12.839012 | 10.340503 | 14.443173 | 8.844416 | 244045.000000 | 102465.000000 | `True` | `False` |
| `multi_holdout_ge3` | `True` | 2 | 10 | 12.839012 | 10.340503 | 14.443173 | 8.844416 | 244045.000000 | 102465.000000 | `True` | `False` |
| `rmse_le6` | `True` | 1 | 6 | 3.174829 | 2.860072 | 3.174829 | 2.860072 | 288937.000000 | 113961.000000 | `True` | `False` |
| `rmse_gt6` | `True` | 1 | 4 | 22.503195 | 17.820933 | 22.503195 | 17.820933 | 199153.000000 | 90969.000000 | `True` | `False` |
| `strong_wind_subset` | `True` | 2 | 10 | 12.839012 | 10.340503 | 14.443173 | 8.844416 | 244045.000000 | 102465.000000 | `True` | `False` |
| `vertical_mismatch_subset` | `True` | 2 | 10 | 12.839012 | 10.340503 | 14.443173 | 8.844416 | 244045.000000 | 102465.000000 | `True` | `False` |
