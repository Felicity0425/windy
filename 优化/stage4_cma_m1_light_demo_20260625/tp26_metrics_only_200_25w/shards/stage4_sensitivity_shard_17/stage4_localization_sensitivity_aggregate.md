# Stage4 Sensitivity Aggregate

Metrics-only aggregate. No per-parameter 3D NPZ fields are saved.

Official error metrics below use holdout frames only. No-holdout frames are unverified reconstruction coverage diagnostics and are not zero-error validation frames.

| rank | kernel | confidence | physics | role conflict | vertical risk | vertical loc | rxy/sxy/rz/sz | frames | eval frames | no holdout | holdout points | official frame RMSE | official frame MAE | zero-filled all-frame RMSE | mean fill | mean effective | strict no leakage | motion used |
| ---: | --- | --- | --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| 1 | `gaussian` | `diagnostic_weighted` | `pydda_3dvar_proxy` | `current_priority_adaptive` | `preserve_strong_layers` | `fixed` | 10/5.0/2/1.0 | 5 | 5 | 0 | 10 | 4.445642 | 4.235676 | 4.445642 | 92053.2 | 225397.0 | `True` | `False` |
| 2 | `gaussian` | `diagnostic_weighted` | `pydda_3dvar_proxy` | `current_priority_adaptive` | `preserve_strong_layers` | `fixed` | 8/4.0/2/1.0 | 3 | 3 | 0 | 8 | 22.834964 | 22.083933 | 22.834964 | 92693.0 | 204743.3 | `True` | `False` |

## Adaptive/Vertical Diagnostics

| rank | mean conflict voxels | mean adaptive threshold | mean context factor | mean vertical loc sigma factor | mean vertical mismatch | mean oversmooth | mean isolated strong | refine risk | refine oversmooth preserve | refine mismatch damp |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 1573.4 | 13.003 | 0.210 | 1.000 | 986.2 | 1839.2 | 9.4 | 2878.6 | 1842.8 | 1035.8 |
| 2 | 3397.3 | 12.648 | 0.209 | 1.000 | 2127.3 | 3283.3 | 4.7 | 5453.0 | 3288.3 | 2164.7 |

## Guarded Vertical Dynamic Diagnostics

| rank | guard active frac | guarded fallback frac | dynamic active frac | 12km+ fallback | role-gap fallback | remote fallback | light/mod protected |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 0.000000 | 0.000000 | 0.000000 | 0 | 0 | 0 | 0 |
| 2 | 0.000000 | 0.000000 | 0.000000 | 0 | 0 | 0 | 0 |
