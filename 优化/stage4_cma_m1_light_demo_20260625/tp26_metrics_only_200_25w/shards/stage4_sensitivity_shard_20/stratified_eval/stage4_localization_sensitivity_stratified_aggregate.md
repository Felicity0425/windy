# Stage4 Stratified Evaluation

Official RMSE/MAE comes only from `eval_holdout_only` and its holdout subsets. `no_holdout_unverified_reconstruction` keeps coverage and risk diagnostics but does not contribute to official error metrics.

- expected frames: `0`
- validation failures: `0`

| stratum | official | frames | holdout points | frame RMSE | frame MAE | weighted RMSE | weighted MAE | mean effective voxels | mean low-conf fill | leakage | motion used |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| `all_frames_original` | `False` | 5 | 11 |  |  |  |  | 178273.200000 | 81415.200000 | `True` | `False` |
| `eval_holdout_only` | `True` | 5 | 11 | 11.454879 | 11.172416 | 13.104174 | 7.394070 | 178273.200000 | 81415.200000 | `True` | `False` |
| `no_holdout_unverified_reconstruction` | `False` | 0 | 0 |  |  |  |  |  |  | `True` | `False` |
| `single_holdout_pressure_test` | `True` | 3 | 3 | 15.790393 | 15.790393 | 23.737945 | 15.790393 | 159123.000000 | 73492.666667 | `True` | `False` |
| `multi_holdout_supported` | `True` | 2 | 8 | 4.951607 | 4.245449 | 4.980502 | 4.245449 | 206998.500000 | 93299.000000 | `True` | `False` |
| `multi_holdout_ge3` | `True` | 2 | 8 | 4.951607 | 4.245449 | 4.980502 | 4.245449 | 206998.500000 | 93299.000000 | `True` | `False` |
| `rmse_le6` | `True` | 4 | 10 | 4.127597 | 3.774518 | 4.766647 | 4.057077 | 178369.750000 | 81664.000000 | `True` | `False` |
| `rmse_gt6` | `True` | 1 | 1 | 40.764004 | 40.764004 | 40.764004 | 40.764004 | 177887.000000 | 80420.000000 | `True` | `False` |
| `strong_wind_subset` | `True` | 3 | 6 | 17.139177 | 16.920689 | 17.362971 | 10.876274 | 208261.000000 | 93031.666667 | `True` | `False` |
| `vertical_mismatch_subset` | `True` | 3 | 6 | 17.139177 | 16.920689 | 17.362971 | 10.876274 | 208261.000000 | 93031.666667 | `True` | `False` |
| `all_frames_original` | `False` | 3 | 8 |  |  |  |  | 260225.333333 | 100299.000000 | `True` | `False` |
| `eval_holdout_only` | `True` | 3 | 8 | 8.134625 | 6.198111 | 9.232537 | 6.436172 | 260225.333333 | 100299.000000 | `True` | `False` |
| `no_holdout_unverified_reconstruction` | `False` | 0 | 0 |  |  |  |  |  |  | `True` | `False` |
| `single_holdout_pressure_test` | `True` | 0 | 0 |  |  |  |  |  |  | `True` | `False` |
| `multi_holdout_supported` | `True` | 3 | 8 | 8.134625 | 6.198111 | 9.232537 | 6.436172 | 260225.333333 | 100299.000000 | `True` | `False` |
| `multi_holdout_ge3` | `True` | 2 | 6 | 9.900759 | 7.150355 | 10.324360 | 7.150355 | 256457.000000 | 95601.000000 | `True` | `False` |
| `rmse_le6` | `True` | 1 | 2 | 4.602358 | 4.293623 | 4.602358 | 4.293623 | 267762.000000 | 109695.000000 | `True` | `False` |
| `rmse_gt6` | `True` | 2 | 6 | 9.900759 | 7.150355 | 10.324360 | 7.150355 | 256457.000000 | 95601.000000 | `True` | `False` |
| `strong_wind_subset` | `True` | 3 | 8 | 8.134625 | 6.198111 | 9.232537 | 6.436172 | 260225.333333 | 100299.000000 | `True` | `False` |
| `vertical_mismatch_subset` | `True` | 3 | 8 | 8.134625 | 6.198111 | 9.232537 | 6.436172 | 260225.333333 | 100299.000000 | `True` | `False` |
