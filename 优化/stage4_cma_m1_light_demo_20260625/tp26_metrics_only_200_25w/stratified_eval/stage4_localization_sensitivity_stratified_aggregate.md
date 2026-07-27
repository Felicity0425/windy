# Stage4 Stratified Evaluation

Official RMSE/MAE comes only from `eval_holdout_only` and its holdout subsets. `no_holdout_unverified_reconstruction` keeps coverage and risk diagnostics but does not contribute to official error metrics.

- expected frames: `0`
- validation failures: `0`

| stratum | official | frames | holdout points | frame RMSE | frame MAE | weighted RMSE | weighted MAE | mean effective voxels | mean low-conf fill | leakage | motion used |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| `all_frames_original` | `False` | 106 | 338 |  |  |  |  | 201378.641509 | 87832.688679 | `True` | `False` |
| `eval_holdout_only` | `True` | 106 | 338 | 9.046904 | 7.757578 | 13.740281 | 6.851163 | 201378.641509 | 87832.688679 | `True` | `False` |
| `no_holdout_unverified_reconstruction` | `False` | 0 | 0 |  |  |  |  |  |  | `True` | `False` |
| `single_holdout_pressure_test` | `True` | 35 | 35 | 10.718542 | 10.718542 | 20.848615 | 10.718542 | 181342.400000 | 82082.428571 | `True` | `False` |
| `multi_holdout_supported` | `True` | 71 | 303 | 8.222858 | 6.297948 | 12.664698 | 6.404436 | 211255.661972 | 90667.323944 | `True` | `False` |
| `multi_holdout_ge3` | `True` | 64 | 289 | 8.144559 | 6.130468 | 12.661695 | 6.335416 | 215198.796875 | 91732.921875 | `True` | `False` |
| `rmse_le6` | `True` | 72 | 219 | 3.574652 | 3.266483 | 4.027674 | 3.405092 | 202736.819444 | 87838.902778 | `True` | `False` |
| `rmse_gt6` | `True` | 34 | 119 | 20.635204 | 17.268132 | 22.503066 | 13.193090 | 198502.500000 | 87819.529412 | `True` | `False` |
| `strong_wind_subset` | `True` | 104 | 333 | 9.164567 | 7.857724 | 13.834364 | 6.905753 | 202688.009615 | 88291.192308 | `True` | `False` |
| `vertical_mismatch_subset` | `True` | 104 | 333 | 9.164567 | 7.857724 | 13.834364 | 6.905753 | 202688.009615 | 88291.192308 | `True` | `False` |
| `all_frames_original` | `False` | 94 | 192 |  |  |  |  | 234246.202128 | 95624.127660 | `True` | `False` |
| `eval_holdout_only` | `True` | 94 | 192 | 7.296702 | 6.319984 | 16.424245 | 6.860249 | 234246.202128 | 95624.127660 | `True` | `False` |
| `no_holdout_unverified_reconstruction` | `False` | 0 | 0 |  |  |  |  |  |  | `True` | `False` |
| `single_holdout_pressure_test` | `True` | 22 | 22 | 4.611664 | 4.611664 | 5.665405 | 4.611664 | 230388.545455 | 96408.090909 | `True` | `False` |
| `multi_holdout_supported` | `True` | 72 | 170 | 8.117131 | 6.841971 | 17.335273 | 7.151242 | 235424.930556 | 95384.583333 | `True` | `False` |
| `multi_holdout_ge3` | `True` | 26 | 78 | 10.782246 | 8.864129 | 23.298675 | 8.864129 | 238840.307692 | 95558.923077 | `True` | `False` |
| `rmse_le6` | `True` | 64 | 128 | 3.532404 | 3.287651 | 3.825721 | 3.325345 | 227597.656250 | 93221.406250 | `True` | `False` |
| `rmse_gt6` | `True` | 30 | 64 | 15.327207 | 12.788963 | 27.928393 | 13.930057 | 248429.766667 | 100749.933333 | `True` | `False` |
| `strong_wind_subset` | `True` | 94 | 192 | 7.296702 | 6.319984 | 16.424245 | 6.860249 | 234246.202128 | 95624.127660 | `True` | `False` |
| `vertical_mismatch_subset` | `True` | 94 | 192 | 7.296702 | 6.319984 | 16.424245 | 6.860249 | 234246.202128 | 95624.127660 | `True` | `False` |
