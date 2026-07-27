# Stage4 Sensitivity Aggregate

Metrics-only aggregate. No per-parameter 3D NPZ fields are saved.

Official error metrics below use holdout frames only. No-holdout frames are unverified reconstruction coverage diagnostics and are not zero-error validation frames.

| rank | kernel | confidence | physics | role conflict | vertical risk | vertical loc | rxy/sxy/rz/sz | frames | eval frames | no holdout | holdout points | official frame RMSE | official frame MAE | zero-filled all-frame RMSE | mean fill | mean effective | strict no leakage | motion used |
| ---: | --- | --- | --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| 1 | `gaussian` | `diagnostic_weighted` | `pydda_3dvar_proxy` | `current_priority_adaptive` | `preserve_strong_layers` | `fixed` | 10/5.0/2/1.0 | 6 | 6 | 0 | 12 | 12.465994 | 10.050440 | 12.465994 | 94660.8 | 222443.2 | `True` | `False` |
| 2 | `gaussian` | `diagnostic_weighted` | `pydda_3dvar_proxy` | `current_priority_adaptive` | `preserve_strong_layers` | `fixed` | 8/4.0/2/1.0 | 2 | 2 | 0 | 10 | 12.839012 | 10.340503 | 12.839012 | 102465.0 | 244045.0 | `True` | `False` |

## Adaptive/Vertical Diagnostics

| rank | mean conflict voxels | mean adaptive threshold | mean context factor | mean vertical loc sigma factor | mean vertical mismatch | mean oversmooth | mean isolated strong | refine risk | refine oversmooth preserve | refine mismatch damp |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 1928.3 | 12.975 | 0.248 | 1.000 | 2413.2 | 4422.7 | 11.5 | 6909.7 | 4424.3 | 2485.3 |
| 2 | 1677.0 | 12.519 | 0.252 | 1.000 | 1749.5 | 2555.5 | 1.5 | 4332.0 | 2555.5 | 1776.5 |

## Guarded Vertical Dynamic Diagnostics

| rank | guard active frac | guarded fallback frac | dynamic active frac | 12km+ fallback | role-gap fallback | remote fallback | light/mod protected |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 1 | 0.000000 | 0.000000 | 0.000000 | 0 | 0 | 0 | 0 |
| 2 | 0.000000 | 0.000000 | 0.000000 | 0 | 0 | 0 | 0 |
