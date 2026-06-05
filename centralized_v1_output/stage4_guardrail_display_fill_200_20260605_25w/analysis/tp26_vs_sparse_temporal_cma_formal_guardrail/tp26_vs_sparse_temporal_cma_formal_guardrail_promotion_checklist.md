# Stage4 Promotion Checklist

| gate | baseline | candidate | passed | detail |
| --- | ---: | ---: | --- | --- |
| `PROMOTION_OVERALL` | `all gates pass` | `FAIL` | `False` |  |
| `strict_holdout_no_leakage_all_true` | `True` | `True` | `True` |  |
| `motion_used_as_wind_all_false` | `False` | `False` | `True` |  |
| `weighted_rmse_no_worse` | `14.769035584178605` | `14.852237035605219` | `False` |  |
| `frame_p95_no_worse` | `27.986110980146194` | `26.226385584247325` | `True` |  |
| `frame_p99_no_worse` | `58.78377017267204` | `53.53234739592989` | `True` |  |
| `alt_12km_plus_vector_rmse_no_worse` | `19.917697780481415` | `19.951608908326953` | `False` |  |
| `light_wind_vector_rmse_mps_no_worse` | `5.195876810373414` | `6.057278442944428` | `False` |  |
| `light_wind_vector_mae_mps_no_worse` | `4.185283061205855` | `4.490679519582376` | `False` |  |
| `floor10_relative_error_mae_no_worse` | `0.2828040963230872` | `0.29384558698595586` | `False` |  |
| `light_moderate_relative_tail_no_new_failure` | `0` | `1` | `False` | candidate relative_error_ratio > 2 and delta_vector_error > 5 m/s |
