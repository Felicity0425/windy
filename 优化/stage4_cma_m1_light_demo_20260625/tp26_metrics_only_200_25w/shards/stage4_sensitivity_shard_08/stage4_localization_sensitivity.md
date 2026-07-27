# Stage4 Localization Sensitivity

This table is metrics-only. Per-parameter 3D NPZ outputs are intentionally not saved.

| frame | kernel | confidence | physics | policy | rxy | sxy | rz | sz | holdout | RMSE | MAE | effective voxels | low-conf fill | leakage |
| --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `20260125014200` | `gaussian` | `diagnostic_weighted` | `pydda_3dvar_proxy` | `diagnostic_adaptive_v3` | 8 | 4.00 | 2 | 1.00 | 2 | 16.902702 | 12.235475 | 193237 | 98332 | `True` |
| `20260129140600` | `gaussian` | `diagnostic_weighted` | `pydda_3dvar_proxy` | `diagnostic_adaptive_v3` | 8 | 4.00 | 2 | 1.00 | 5 | 3.026905 | 2.506783 | 181970 | 79186 | `True` |
| `20260201192400` | `gaussian` | `diagnostic_weighted` | `pydda_3dvar_proxy` | `diagnostic_adaptive_v3` | 8 | 4.00 | 2 | 1.00 | 1 | 1.008672 | 1.008672 | 201202 | 89586 | `True` |
| `20260204070000` | `gaussian` | `diagnostic_weighted` | `pydda_3dvar_proxy` | `diagnostic_adaptive_v3` | 8 | 4.00 | 2 | 1.00 | 1 | 0.627686 | 0.627686 | 142967 | 67246 | `True` |
| `20260208084800` | `gaussian` | `diagnostic_weighted` | `pydda_3dvar_proxy` | `diagnostic_adaptive_v3` | 8 | 4.00 | 2 | 1.00 | 6 | 5.044941 | 3.919578 | 303414 | 116906 | `True` |
| `20260212040600` | `gaussian` | `diagnostic_weighted` | `pydda_3dvar_proxy` | `diagnostic_adaptive_v3` | 10 | 5.00 | 2 | 1.00 | 1 | 4.431649 | 4.431649 | 242797 | 103651 | `True` |
| `20260217111800` | `gaussian` | `diagnostic_weighted` | `pydda_3dvar_proxy` | `diagnostic_adaptive_v3` | 8 | 4.00 | 2 | 1.00 | 6 | 5.472712 | 4.949678 | 227661 | 95203 | `True` |
| `20260221025400` | `gaussian` | `diagnostic_weighted` | `pydda_3dvar_proxy` | `diagnostic_adaptive_v3` | 10 | 5.00 | 2 | 1.00 | 2 | 2.845480 | 2.227027 | 212258 | 98717 | `True` |

References:

- DART Gaspari-Cohn localization: https://docs.dart.ucar.edu/en/latest/assimilation_code/modules/assimilation/cov_cutoff_mod.html
- ECMWF ERA5/IFS finite assimilation windows: https://confluence.ecmwf.int/display/CKB/ERA5%3A%2Bdata%2Bdocumentation
- PyDDA/3DVAR wind retrieval constraints: https://openresearchsoftware.metajnl.com/articles/264
