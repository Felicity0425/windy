# Stage4 Localization Sensitivity

This table is metrics-only. Per-parameter 3D NPZ outputs are intentionally not saved.

| frame | kernel | confidence | physics | policy | rxy | sxy | rz | sz | holdout | RMSE | MAE | effective voxels | low-conf fill | leakage |
| --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `20260125023000` | `gaussian` | `diagnostic_weighted` | `pydda_3dvar_proxy` | `diagnostic_adaptive_v3` | 10 | 5.00 | 2 | 1.00 | 1 | 0.936433 | 0.936433 | 245307 | 111975 | `True` |
| `20260129163000` | `gaussian` | `diagnostic_weighted` | `pydda_3dvar_proxy` | `diagnostic_adaptive_v3` | 10 | 5.00 | 2 | 1.00 | 2 | 0.976195 | 0.972246 | 230026 | 95222 | `True` |
| `20260201201800` | `gaussian` | `diagnostic_weighted` | `pydda_3dvar_proxy` | `diagnostic_adaptive_v3` | 8 | 4.00 | 2 | 1.00 | 3 | 1.117852 | 1.107223 | 199937 | 87783 | `True` |
| `20260204093000` | `gaussian` | `diagnostic_weighted` | `pydda_3dvar_proxy` | `diagnostic_adaptive_v3` | 8 | 4.00 | 2 | 1.00 | 1 | 2.403087 | 2.403087 | 115648 | 55668 | `True` |
| `20260208100600` | `gaussian` | `diagnostic_weighted` | `pydda_3dvar_proxy` | `diagnostic_adaptive_v3` | 8 | 4.00 | 2 | 1.00 | 4 | 4.054871 | 3.766694 | 288459 | 111320 | `True` |
| `20260212083000` | `gaussian` | `diagnostic_weighted` | `pydda_3dvar_proxy` | `diagnostic_adaptive_v3` | 10 | 5.00 | 2 | 1.00 | 2 | 5.861772 | 5.315702 | 218287 | 90291 | `True` |
| `20260217134800` | `gaussian` | `diagnostic_weighted` | `pydda_3dvar_proxy` | `diagnostic_adaptive_v3` | 10 | 5.00 | 2 | 1.00 | 3 | 5.397069 | 5.268595 | 260770 | 104335 | `True` |
| `20260221043600` | `gaussian` | `diagnostic_weighted` | `pydda_3dvar_proxy` | `diagnostic_adaptive_v3` | 10 | 5.00 | 2 | 1.00 | 2 | 6.794804 | 6.286287 | 212693 | 97191 | `True` |

References:

- DART Gaspari-Cohn localization: https://docs.dart.ucar.edu/en/latest/assimilation_code/modules/assimilation/cov_cutoff_mod.html
- ECMWF ERA5/IFS finite assimilation windows: https://confluence.ecmwf.int/display/CKB/ERA5%3A%2Bdata%2Bdocumentation
- PyDDA/3DVAR wind retrieval constraints: https://openresearchsoftware.metajnl.com/articles/264
