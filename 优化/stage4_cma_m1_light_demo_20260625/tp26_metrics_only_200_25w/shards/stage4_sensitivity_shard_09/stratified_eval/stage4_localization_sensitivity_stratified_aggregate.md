# Stage4 Stratified Evaluation

Official RMSE/MAE comes only from `eval_holdout_only` and its holdout subsets. `no_holdout_unverified_reconstruction` keeps coverage and risk diagnostics but does not contribute to official error metrics.

- expected frames: `0`
- validation failures: `0`

| stratum | official | frames | holdout points | frame RMSE | frame MAE | weighted RMSE | weighted MAE | mean effective voxels | mean low-conf fill | leakage | motion used |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| `all_frames_original` | `False` | 5 | 10 |  |  |  |  | 233416.600000 | 99802.800000 | `True` | `False` |
| `eval_holdout_only` | `True` | 5 | 10 | 3.993255 | 3.755853 | 5.012258 | 4.189069 | 233416.600000 | 99802.800000 | `True` | `False` |
| `no_holdout_unverified_reconstruction` | `False` | 0 | 0 |  |  |  |  |  |  | `True` | `False` |
| `single_holdout_pressure_test` | `True` | 1 | 1 | 0.936433 | 0.936433 | 0.936433 | 0.936433 | 245307.000000 | 111975.000000 | `True` | `False` |
| `multi_holdout_supported` | `True` | 4 | 9 | 4.757460 | 4.460708 | 5.274155 | 4.550473 | 230444.000000 | 96759.750000 | `True` | `False` |
| `multi_holdout_ge3` | `True` | 1 | 3 | 5.397069 | 5.268595 | 5.397069 | 5.268595 | 260770.000000 | 104335.000000 | `True` | `False` |
| `rmse_le6` | `True` | 4 | 8 | 3.292867 | 3.123244 | 4.456577 | 3.664764 | 238597.500000 | 100455.750000 | `True` | `False` |
| `rmse_gt6` | `True` | 1 | 2 | 6.794804 | 6.286287 | 6.794804 | 6.286287 | 212693.000000 | 97191.000000 | `True` | `False` |
| `strong_wind_subset` | `True` | 5 | 10 | 3.993255 | 3.755853 | 5.012258 | 4.189069 | 233416.600000 | 99802.800000 | `True` | `False` |
| `vertical_mismatch_subset` | `True` | 5 | 10 | 3.993255 | 3.755853 | 5.012258 | 4.189069 | 233416.600000 | 99802.800000 | `True` | `False` |
| `all_frames_original` | `False` | 3 | 8 |  |  |  |  | 201348.000000 | 84923.666667 | `True` | `False` |
| `eval_holdout_only` | `True` | 3 | 8 | 2.525270 | 2.425668 | 3.067807 | 2.598941 | 201348.000000 | 84923.666667 | `True` | `False` |
| `no_holdout_unverified_reconstruction` | `False` | 0 | 0 |  |  |  |  |  |  | `True` | `False` |
| `single_holdout_pressure_test` | `True` | 1 | 1 | 2.403087 | 2.403087 | 2.403087 | 2.403087 | 115648.000000 | 55668.000000 | `True` | `False` |
| `multi_holdout_supported` | `True` | 2 | 7 | 2.586361 | 2.436958 | 3.151342 | 2.626920 | 244198.000000 | 99551.500000 | `True` | `False` |
| `multi_holdout_ge3` | `True` | 2 | 7 | 2.586361 | 2.436958 | 3.151342 | 2.626920 | 244198.000000 | 99551.500000 | `True` | `False` |
| `rmse_le6` | `True` | 3 | 8 | 2.525270 | 2.425668 | 3.067807 | 2.598941 | 201348.000000 | 84923.666667 | `True` | `False` |
| `rmse_gt6` | `True` | 0 | 0 |  |  |  |  |  |  | `True` | `False` |
| `strong_wind_subset` | `True` | 3 | 8 | 2.525270 | 2.425668 | 3.067807 | 2.598941 | 201348.000000 | 84923.666667 | `True` | `False` |
| `vertical_mismatch_subset` | `True` | 3 | 8 | 2.525270 | 2.425668 | 3.067807 | 2.598941 | 201348.000000 | 84923.666667 | `True` | `False` |
