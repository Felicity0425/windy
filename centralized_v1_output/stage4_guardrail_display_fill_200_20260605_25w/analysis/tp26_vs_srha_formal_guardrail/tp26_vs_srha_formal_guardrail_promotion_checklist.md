# Stage4 Promotion Checklist

| gate | baseline | candidate | passed | detail |
| --- | ---: | ---: | --- | --- |
| `PROMOTION_OVERALL` | `all gates pass` | `FAIL` | `False` |  |
| `strict_holdout_no_leakage_all_true` | `True` | `True` | `True` |  |
| `motion_used_as_wind_all_false` | `False` | `False` | `True` |  |
| `weighted_rmse_no_worse` | `14.769035584178605` | `20.148614706594163` | `False` |  |
| `frame_p95_no_worse` | `27.986110980146194` | `34.72710322612249` | `False` |  |
| `frame_p99_no_worse` | `58.78377017267204` | `86.32245410423373` | `False` |  |
| `alt_12km_plus_vector_rmse_no_worse` | `19.917697780481415` | `28.454525761392187` | `False` |  |
| `light_wind_vector_rmse_mps_no_worse` | `5.195876810373414` | `5.183379083355663` | `True` |  |
| `light_wind_vector_mae_mps_no_worse` | `4.185283061205855` | `4.087178616509373` | `True` |  |
| `floor10_relative_error_mae_no_worse` | `0.2828040963230872` | `0.31772350822238454` | `False` |  |
| `light_moderate_relative_tail_no_new_failure` | `0` | `1` | `False` | candidate relative_error_ratio > 2 and delta_vector_error > 5 m/s |
