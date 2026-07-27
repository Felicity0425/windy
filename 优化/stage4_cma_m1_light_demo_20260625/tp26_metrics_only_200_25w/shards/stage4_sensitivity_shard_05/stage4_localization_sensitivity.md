# Stage4 Localization Sensitivity

This table is metrics-only. Per-parameter 3D NPZ outputs are intentionally not saved.

| frame | kernel | confidence | physics | policy | rxy | sxy | rz | sz | holdout | RMSE | MAE | effective voxels | low-conf fill | leakage |
| --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `20260124121800` | `gaussian` | `diagnostic_weighted` | `pydda_3dvar_proxy` | `diagnostic_adaptive_v3` | 10 | 5.00 | 2 | 1.00 | 2 | 1.925367 | 1.882592 | 222143 | 97051 | `True` |
| `20260129084200` | `gaussian` | `diagnostic_weighted` | `pydda_3dvar_proxy` | `diagnostic_adaptive_v3` | 8 | 4.00 | 2 | 1.00 | 5 | 6.078200 | 5.903677 | 152596 | 63807 | `True` |
| `20260201120000` | `gaussian` | `diagnostic_weighted` | `pydda_3dvar_proxy` | `diagnostic_adaptive_v3` | 8 | 4.00 | 2 | 1.00 | 4 | 4.760807 | 4.675581 | 216696 | 84147 | `True` |
| `20260203233000` | `gaussian` | `diagnostic_weighted` | `pydda_3dvar_proxy` | `diagnostic_adaptive_v3` | 8 | 4.00 | 2 | 1.00 | 1 | 36.164613 | 36.164613 | 173382 | 81938 | `True` |
| `20260208051200` | `gaussian` | `diagnostic_weighted` | `pydda_3dvar_proxy` | `diagnostic_adaptive_v3` | 8 | 4.00 | 2 | 1.00 | 3 | 4.698028 | 4.081932 | 310756 | 121958 | `True` |
| `20260211154800` | `gaussian` | `diagnostic_weighted` | `pydda_3dvar_proxy` | `diagnostic_adaptive_v3` | 8 | 4.00 | 2 | 1.00 | 1 | 2.065831 | 2.065831 | 151394 | 72854 | `True` |
| `20260217051800` | `gaussian` | `diagnostic_weighted` | `pydda_3dvar_proxy` | `diagnostic_adaptive_v3` | 10 | 5.00 | 2 | 1.00 | 1 | 4.118139 | 4.118139 | 302088 | 120860 | `True` |
| `20260220114200` | `gaussian` | `diagnostic_weighted` | `pydda_3dvar_proxy` | `diagnostic_adaptive_v3` | 10 | 5.00 | 2 | 1.00 | 2 | 3.629933 | 3.418058 | 174416 | 74921 | `True` |

References:

- DART Gaspari-Cohn localization: https://docs.dart.ucar.edu/en/latest/assimilation_code/modules/assimilation/cov_cutoff_mod.html
- ECMWF ERA5/IFS finite assimilation windows: https://confluence.ecmwf.int/display/CKB/ERA5%3A%2Bdata%2Bdocumentation
- PyDDA/3DVAR wind retrieval constraints: https://openresearchsoftware.metajnl.com/articles/264
