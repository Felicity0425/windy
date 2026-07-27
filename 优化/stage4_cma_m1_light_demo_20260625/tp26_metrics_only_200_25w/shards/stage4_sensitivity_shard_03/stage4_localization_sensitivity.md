# Stage4 Localization Sensitivity

This table is metrics-only. Per-parameter 3D NPZ outputs are intentionally not saved.

| frame | kernel | confidence | physics | policy | rxy | sxy | rz | sz | holdout | RMSE | MAE | effective voxels | low-conf fill | leakage |
| --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `20260124070600` | `gaussian` | `diagnostic_weighted` | `pydda_3dvar_proxy` | `diagnostic_adaptive_v3` | 8 | 4.00 | 2 | 1.00 | 3 | 6.883228 | 5.565851 | 198482 | 101181 | `True` |
| `20260128091200` | `gaussian` | `diagnostic_weighted` | `pydda_3dvar_proxy` | `diagnostic_adaptive_v3` | 8 | 4.00 | 2 | 1.00 | 6 | 3.421226 | 3.185593 | 189177 | 83968 | `True` |
| `20260201075400` | `gaussian` | `diagnostic_weighted` | `pydda_3dvar_proxy` | `diagnostic_adaptive_v3` | 8 | 4.00 | 2 | 1.00 | 1 | 1.894851 | 1.894851 | 262013 | 105948 | `True` |
| `20260203170000` | `gaussian` | `diagnostic_weighted` | `pydda_3dvar_proxy` | `diagnostic_adaptive_v3` | 10 | 5.00 | 2 | 1.00 | 3 | 4.212629 | 3.486648 | 191629 | 82931 | `True` |
| `20260207131800` | `gaussian` | `diagnostic_weighted` | `pydda_3dvar_proxy` | `diagnostic_adaptive_v3` | 8 | 4.00 | 2 | 1.00 | 3 | 5.354719 | 4.966558 | 250055 | 104161 | `True` |
| `20260211102400` | `gaussian` | `diagnostic_weighted` | `pydda_3dvar_proxy` | `diagnostic_adaptive_v3` | 8 | 4.00 | 2 | 1.00 | 3 | 3.418099 | 3.154712 | 194023 | 83093 | `True` |
| `20260216015400` | `gaussian` | `diagnostic_weighted` | `pydda_3dvar_proxy` | `diagnostic_adaptive_v3` | 10 | 5.00 | 2 | 1.00 | 3 | 29.005411 | 26.921748 | 230618 | 106164 | `True` |
| `20260220060600` | `gaussian` | `diagnostic_weighted` | `pydda_3dvar_proxy` | `diagnostic_adaptive_v3` | 10 | 5.00 | 2 | 1.00 | 1 | 1.932191 | 1.932191 | 193130 | 82142 | `True` |

References:

- DART Gaspari-Cohn localization: https://docs.dart.ucar.edu/en/latest/assimilation_code/modules/assimilation/cov_cutoff_mod.html
- ECMWF ERA5/IFS finite assimilation windows: https://confluence.ecmwf.int/display/CKB/ERA5%3A%2Bdata%2Bdocumentation
- PyDDA/3DVAR wind retrieval constraints: https://openresearchsoftware.metajnl.com/articles/264
