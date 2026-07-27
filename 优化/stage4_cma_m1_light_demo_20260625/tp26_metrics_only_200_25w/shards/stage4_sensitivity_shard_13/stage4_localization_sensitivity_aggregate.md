# Stage4 Sensitivity Aggregate

Metrics-only aggregate. No per-parameter 3D NPZ fields are saved.

Official error metrics below use holdout frames only. No-holdout frames are unverified reconstruction coverage diagnostics and are not zero-error validation frames.

| rank | kernel | confidence | physics | role conflict | vertical risk | vertical loc | rxy/sxy/rz/sz | frames | eval frames | no holdout | holdout points | official frame RMSE | official frame MAE | zero-filled all-frame RMSE | mean fill | mean effective | strict no leakage | motion used |
| ---: | --- | --- | --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| 1 | `gaussian` | `diagnostic_weighted` | `pydda_3dvar_proxy` | `current_priority_adaptive` | `preserve_strong_layers` | `fixed` | 10/5.0/2/1.0 | 2 | 2 | 0 | 4 | 2.413219 | 2.277340 | 2.413219 | 103868.5 | 260143.0 | `True` | `False` |
| 2 | `gaussian` | `diagnostic_weighted` | `pydda_3dvar_proxy` | `current_priority_adaptive` | `preserve_strong_layers` | `fixed` | 8/4.0/2/1.0 | 6 | 6 | 0 | 15 | 8.528311 | 7.902275 | 8.528311 | 86012.3 | 188507.3 | `True` | `False` |

## Adaptive/Vertical Diagnostics

| rank | mean conflict voxels | mean adaptive threshold | mean context factor | mean vertical loc sigma factor | mean vertical mismatch | mean oversmooth | mean isolated strong | refine risk | refine oversmooth preserve | refine mismatch damp |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 2782.5 | 13.284 | 0.242 | 1.000 | 905.0 | 2634.5 | 0.5 | 3577.0 | 2641.5 | 935.5 |
| 2 | 868.7 | 8.438 | 0.126 | 1.000 | 1363.8 | 2599.8 | 20.7 | 4006.3 | 2601.7 | 1404.7 |

## Guarded Vertical Dynamic Diagnostics

| rank | guard active frac | guarded fallback frac | dynamic active frac | 12km+ fallback | role-gap fallback | remote fallback | light/mod protected |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 0.000000 | 0.000000 | 0.000000 | 0 | 0 | 0 | 0 |
| 2 | 0.000000 | 0.000000 | 0.000000 | 0 | 0 | 0 | 0 |
