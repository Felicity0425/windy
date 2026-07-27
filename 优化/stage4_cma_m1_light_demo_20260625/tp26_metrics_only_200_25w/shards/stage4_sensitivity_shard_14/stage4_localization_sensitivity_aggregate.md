# Stage4 Sensitivity Aggregate

Metrics-only aggregate. No per-parameter 3D NPZ fields are saved.

Official error metrics below use holdout frames only. No-holdout frames are unverified reconstruction coverage diagnostics and are not zero-error validation frames.

| rank | kernel | confidence | physics | role conflict | vertical risk | vertical loc | rxy/sxy/rz/sz | frames | eval frames | no holdout | holdout points | official frame RMSE | official frame MAE | zero-filled all-frame RMSE | mean fill | mean effective | strict no leakage | motion used |
| ---: | --- | --- | --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| 1 | `gaussian` | `diagnostic_weighted` | `pydda_3dvar_proxy` | `current_priority_adaptive` | `preserve_strong_layers` | `fixed` | 8/4.0/2/1.0 | 3 | 3 | 0 | 12 | 2.917557 | 2.716146 | 2.917557 | 101297.7 | 232760.3 | `True` | `False` |
| 2 | `gaussian` | `diagnostic_weighted` | `pydda_3dvar_proxy` | `current_priority_adaptive` | `preserve_strong_layers` | `fixed` | 10/5.0/2/1.0 | 5 | 5 | 0 | 11 | 4.539939 | 4.175445 | 4.539939 | 87564.4 | 215588.4 | `True` | `False` |

## Adaptive/Vertical Diagnostics

| rank | mean conflict voxels | mean adaptive threshold | mean context factor | mean vertical loc sigma factor | mean vertical mismatch | mean oversmooth | mean isolated strong | refine risk | refine oversmooth preserve | refine mismatch damp |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 1915.7 | 11.788 | 0.199 | 1.000 | 1262.0 | 2100.0 | 4.7 | 3406.7 | 2103.0 | 1303.7 |
| 2 | 1041.4 | 13.153 | 0.252 | 1.000 | 1054.0 | 2544.4 | 11.2 | 3604.6 | 2544.4 | 1060.2 |

## Guarded Vertical Dynamic Diagnostics

| rank | guard active frac | guarded fallback frac | dynamic active frac | 12km+ fallback | role-gap fallback | remote fallback | light/mod protected |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 0.000000 | 0.000000 | 0.000000 | 0 | 0 | 0 | 0 |
| 2 | 0.000000 | 0.000000 | 0.000000 | 0 | 0 | 0 | 0 |
