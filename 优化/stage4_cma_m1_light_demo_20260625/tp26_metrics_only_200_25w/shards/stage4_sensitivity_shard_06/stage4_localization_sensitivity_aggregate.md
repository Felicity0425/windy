# Stage4 Sensitivity Aggregate

Metrics-only aggregate. No per-parameter 3D NPZ fields are saved.

Official error metrics below use holdout frames only. No-holdout frames are unverified reconstruction coverage diagnostics and are not zero-error validation frames.

| rank | kernel | confidence | physics | role conflict | vertical risk | vertical loc | rxy/sxy/rz/sz | frames | eval frames | no holdout | holdout points | official frame RMSE | official frame MAE | zero-filled all-frame RMSE | mean fill | mean effective | strict no leakage | motion used |
| ---: | --- | --- | --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| 1 | `gaussian` | `diagnostic_weighted` | `pydda_3dvar_proxy` | `current_priority_adaptive` | `preserve_strong_layers` | `fixed` | 10/5.0/2/1.0 | 3 | 3 | 0 | 5 | 8.375104 | 7.884492 | 8.375104 | 86027.7 | 211865.7 | `True` | `False` |
| 2 | `gaussian` | `diagnostic_weighted` | `pydda_3dvar_proxy` | `current_priority_adaptive` | `preserve_strong_layers` | `fixed` | 8/4.0/2/1.0 | 5 | 5 | 0 | 13 | 8.397036 | 7.747605 | 8.397036 | 89095.0 | 208331.4 | `True` | `False` |

## Adaptive/Vertical Diagnostics

| rank | mean conflict voxels | mean adaptive threshold | mean context factor | mean vertical loc sigma factor | mean vertical mismatch | mean oversmooth | mean isolated strong | refine risk | refine oversmooth preserve | refine mismatch damp |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 1594.7 | 13.233 | 0.205 | 1.000 | 1699.0 | 3399.0 | 56.0 | 5124.0 | 3399.0 | 1725.0 |
| 2 | 1405.4 | 12.367 | 0.184 | 1.000 | 898.0 | 2206.2 | 7.8 | 3129.2 | 2209.8 | 919.4 |

## Guarded Vertical Dynamic Diagnostics

| rank | guard active frac | guarded fallback frac | dynamic active frac | 12km+ fallback | role-gap fallback | remote fallback | light/mod protected |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 0.000000 | 0.000000 | 0.000000 | 0 | 0 | 0 | 0 |
| 2 | 0.000000 | 0.000000 | 0.000000 | 0 | 0 | 0 | 0 |
