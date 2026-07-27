# Stage4 Localization Sensitivity

This table is metrics-only. Per-parameter 3D NPZ outputs are intentionally not saved.

| frame | kernel | confidence | physics | policy | rxy | sxy | rz | sz | holdout | RMSE | MAE | effective voxels | low-conf fill | leakage |
| --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `20260127121200` | `gaussian` | `diagnostic_weighted` | `pydda_3dvar_proxy` | `diagnostic_adaptive_v3` | 8 | 4.00 | 2 | 1.00 | 5 | 5.965762 | 5.063469 | 256291 | 99069 | `True` |
| `20260201033000` | `gaussian` | `diagnostic_weighted` | `pydda_3dvar_proxy` | `diagnostic_adaptive_v3` | 10 | 5.00 | 2 | 1.00 | 1 | 4.402232 | 4.402232 | 346496 | 127861 | `True` |
| `20260203075400` | `gaussian` | `diagnostic_weighted` | `pydda_3dvar_proxy` | `diagnostic_adaptive_v3` | 10 | 5.00 | 2 | 1.00 | 2 | 10.802384 | 9.461775 | 170719 | 67372 | `True` |
| `20260207010600` | `gaussian` | `diagnostic_weighted` | `pydda_3dvar_proxy` | `diagnostic_adaptive_v3` | 8 | 4.00 | 2 | 1.00 | 4 | 10.237787 | 8.557396 | 229096 | 102505 | `True` |
| `20260211000000` | `gaussian` | `diagnostic_weighted` | `pydda_3dvar_proxy` | `diagnostic_adaptive_v3` | 10 | 5.00 | 2 | 1.00 | 2 | 3.552872 | 2.833785 | 275852 | 108022 | `True` |
| `20260215041800` | `gaussian` | `diagnostic_weighted` | `pydda_3dvar_proxy` | `diagnostic_adaptive_v3` | 8 | 4.00 | 2 | 1.00 | 4 | 6.751520 | 5.566381 | 159477 | 68515 | `True` |
| `20260220002400` | `gaussian` | `diagnostic_weighted` | `pydda_3dvar_proxy` | `diagnostic_adaptive_v3` | 10 | 5.00 | 2 | 1.00 | 1 | 4.523941 | 4.523941 | 171088 | 77187 | `True` |
| `20260223133000` | `gaussian` | `diagnostic_weighted` | `pydda_3dvar_proxy` | `diagnostic_adaptive_v3` | 10 | 5.00 | 2 | 1.00 | 3 | 109.692698 | 80.430431 | 190357 | 73784 | `True` |

References:

- DART Gaspari-Cohn localization: https://docs.dart.ucar.edu/en/latest/assimilation_code/modules/assimilation/cov_cutoff_mod.html
- ECMWF ERA5/IFS finite assimilation windows: https://confluence.ecmwf.int/display/CKB/ERA5%3A%2Bdata%2Bdocumentation
- PyDDA/3DVAR wind retrieval constraints: https://openresearchsoftware.metajnl.com/articles/264
