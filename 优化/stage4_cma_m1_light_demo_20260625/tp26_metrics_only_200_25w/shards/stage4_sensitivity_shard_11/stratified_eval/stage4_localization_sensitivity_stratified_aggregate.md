# Stage4 Stratified Evaluation

Official RMSE/MAE comes only from `eval_holdout_only` and its holdout subsets. `no_holdout_unverified_reconstruction` keeps coverage and risk diagnostics but does not contribute to official error metrics.

- expected frames: `0`
- validation failures: `0`

| stratum | official | frames | holdout points | frame RMSE | frame MAE | weighted RMSE | weighted MAE | mean effective voxels | mean low-conf fill | leakage | motion used |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| `all_frames_original` | `False` | 3 | 7 |  |  |  |  | 207242.000000 | 88710.333333 | `True` | `False` |
| `eval_holdout_only` | `True` | 3 | 7 | 7.205283 | 6.662302 | 9.221379 | 7.451715 | 207242.000000 | 88710.333333 | `True` | `False` |
| `no_holdout_unverified_reconstruction` | `False` | 0 | 0 |  |  |  |  |  |  | `True` | `False` |
| `single_holdout_pressure_test` | `True` | 1 | 1 | 3.899356 | 3.899356 | 3.899356 | 3.899356 | 208406.000000 | 91659.000000 | `True` | `False` |
| `multi_holdout_supported` | `True` | 2 | 6 | 8.858246 | 8.043775 | 9.832191 | 8.043775 | 206660.000000 | 87236.000000 | `True` | `False` |
| `multi_holdout_ge3` | `True` | 2 | 6 | 8.858246 | 8.043775 | 9.832191 | 8.043775 | 206660.000000 | 87236.000000 | `True` | `False` |
| `rmse_le6` | `True` | 2 | 4 | 4.245526 | 4.078015 | 4.428770 | 4.167345 | 170814.000000 | 72731.500000 | `True` | `False` |
| `rmse_gt6` | `True` | 1 | 3 | 13.124796 | 11.830876 | 13.124796 | 11.830876 | 280098.000000 | 120668.000000 | `True` | `False` |
| `strong_wind_subset` | `True` | 3 | 7 | 7.205283 | 6.662302 | 9.221379 | 7.451715 | 207242.000000 | 88710.333333 | `True` | `False` |
| `vertical_mismatch_subset` | `True` | 3 | 7 | 7.205283 | 6.662302 | 9.221379 | 7.451715 | 207242.000000 | 88710.333333 | `True` | `False` |
| `all_frames_original` | `False` | 5 | 19 |  |  |  |  | 203382.200000 | 90310.400000 | `True` | `False` |
| `eval_holdout_only` | `True` | 5 | 19 | 4.576678 | 4.129822 | 6.019021 | 4.531172 | 203382.200000 | 90310.400000 | `True` | `False` |
| `no_holdout_unverified_reconstruction` | `False` | 0 | 0 |  |  |  |  |  |  | `True` | `False` |
| `single_holdout_pressure_test` | `True` | 2 | 2 | 4.381107 | 4.381107 | 4.388859 | 4.381107 | 164249.000000 | 79461.500000 | `True` | `False` |
| `multi_holdout_supported` | `True` | 3 | 17 | 4.707058 | 3.962299 | 6.182611 | 4.548826 | 229471.000000 | 97543.000000 | `True` | `False` |
| `multi_holdout_ge3` | `True` | 3 | 17 | 4.707058 | 3.962299 | 6.182611 | 4.548826 | 229471.000000 | 97543.000000 | `True` | `False` |
| `rmse_le6` | `True` | 4 | 10 | 3.713511 | 3.594519 | 3.288009 | 2.965296 | 206163.750000 | 92799.750000 | `True` | `False` |
| `rmse_gt6` | `True` | 1 | 9 | 8.029346 | 6.271034 | 8.029346 | 6.271034 | 192256.000000 | 80353.000000 | `True` | `False` |
| `strong_wind_subset` | `True` | 5 | 19 | 4.576678 | 4.129822 | 6.019021 | 4.531172 | 203382.200000 | 90310.400000 | `True` | `False` |
| `vertical_mismatch_subset` | `True` | 5 | 19 | 4.576678 | 4.129822 | 6.019021 | 4.531172 | 203382.200000 | 90310.400000 | `True` | `False` |
