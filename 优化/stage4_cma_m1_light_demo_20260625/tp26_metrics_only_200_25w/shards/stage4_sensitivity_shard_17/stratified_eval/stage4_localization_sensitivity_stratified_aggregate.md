# Stage4 Stratified Evaluation

Official RMSE/MAE comes only from `eval_holdout_only` and its holdout subsets. `no_holdout_unverified_reconstruction` keeps coverage and risk diagnostics but does not contribute to official error metrics.

- expected frames: `0`
- validation failures: `0`

| stratum | official | frames | holdout points | frame RMSE | frame MAE | weighted RMSE | weighted MAE | mean effective voxels | mean low-conf fill | leakage | motion used |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| `all_frames_original` | `False` | 5 | 10 |  |  |  |  | 225397.000000 | 92053.200000 | `True` | `False` |
| `eval_holdout_only` | `True` | 5 | 10 | 4.445642 | 4.235676 | 4.980669 | 4.087993 | 225397.000000 | 92053.200000 | `True` | `False` |
| `no_holdout_unverified_reconstruction` | `False` | 0 | 0 |  |  |  |  |  |  | `True` | `False` |
| `single_holdout_pressure_test` | `True` | 1 | 1 | 4.468917 | 4.468917 | 4.468917 | 4.468917 | 251440.000000 | 89416.000000 | `True` | `False` |
| `multi_holdout_supported` | `True` | 4 | 9 | 4.439823 | 4.177365 | 5.034320 | 4.045668 | 218886.250000 | 92712.500000 | `True` | `False` |
| `multi_holdout_ge3` | `True` | 1 | 3 | 3.559057 | 2.992091 | 3.559057 | 2.992091 | 196859.000000 | 78454.000000 | `True` | `False` |
| `rmse_le6` | `True` | 4 | 8 | 3.304257 | 3.128421 | 3.272380 | 2.943818 | 236431.250000 | 93317.250000 | `True` | `False` |
| `rmse_gt6` | `True` | 1 | 2 | 9.011184 | 8.664696 | 9.011184 | 8.664696 | 181260.000000 | 86997.000000 | `True` | `False` |
| `strong_wind_subset` | `True` | 5 | 10 | 4.445642 | 4.235676 | 4.980669 | 4.087993 | 225397.000000 | 92053.200000 | `True` | `False` |
| `vertical_mismatch_subset` | `True` | 5 | 10 | 4.445642 | 4.235676 | 4.980669 | 4.087993 | 225397.000000 | 92053.200000 | `True` | `False` |
| `all_frames_original` | `False` | 3 | 8 |  |  |  |  | 204743.333333 | 92693.000000 | `True` | `False` |
| `eval_holdout_only` | `True` | 3 | 8 | 22.834964 | 22.083933 | 21.429987 | 10.950400 | 204743.333333 | 92693.000000 | `True` | `False` |
| `no_holdout_unverified_reconstruction` | `False` | 0 | 0 |  |  |  |  |  |  | `True` | `False` |
| `single_holdout_pressure_test` | `True` | 1 | 1 | 58.508859 | 58.508859 | 58.508859 | 58.508859 | 209526.000000 | 95479.000000 | `True` | `False` |
| `multi_holdout_supported` | `True` | 2 | 7 | 4.998017 | 3.871470 | 5.984126 | 4.156334 | 202352.000000 | 91300.000000 | `True` | `False` |
| `multi_holdout_ge3` | `True` | 2 | 7 | 4.998017 | 3.871470 | 5.984126 | 4.156334 | 202352.000000 | 91300.000000 | `True` | `False` |
| `rmse_le6` | `True` | 1 | 3 | 2.344618 | 1.877424 | 2.344618 | 1.877424 | 192338.000000 | 88950.000000 | `True` | `False` |
| `rmse_gt6` | `True` | 2 | 5 | 33.080137 | 32.187188 | 27.046120 | 16.394185 | 210946.000000 | 94564.500000 | `True` | `False` |
| `strong_wind_subset` | `True` | 3 | 8 | 22.834964 | 22.083933 | 21.429987 | 10.950400 | 204743.333333 | 92693.000000 | `True` | `False` |
| `vertical_mismatch_subset` | `True` | 3 | 8 | 22.834964 | 22.083933 | 21.429987 | 10.950400 | 204743.333333 | 92693.000000 | `True` | `False` |
