# Stage5 Residual PINN Point Dataset

This dataset is point-level report-only input for residual PINN experiments.
It does not alter Stage4 recon fields and it uses frame/time splits.

## Leakage Boundary

- `gt_u/gt_v/vector_error` are labels or evaluation columns, not model features.
- `qc_review_flag`, `point_neighbor_*_vector_error`, and `representativeness_gap_point_minus_min_mps` are excluded from features.
- `motion_records` / `context_motion_records` are not used as wind labels.
- CMA/NWP fields, if added later, are weak background features only.

## Splits

| split | frames | points | baseline RMSE | baseline MAE | >=30mps tail |
| --- | ---: | ---: | ---: | ---: | ---: |
| `train` | 140 | 381 | 13.725408 | 7.078873 | 16 |
| `val` | 30 | 86 | 8.617390 | 5.458972 | 3 |
| `test` | 30 | 63 | 24.379358 | 7.402198 | 2 |

## Feature Schema

- feature count: `64`
- feature list: `z, y, x, lat, lon, alt_m, pred_u, pred_v, pred_speed, recon_confidence, obs_count, obs_conf, nearest_role_gap_mps, nearest_current_count, nearest_context_count, recon_vertical_jump_mps, vertical_speed_gap_mps, vertical_neighbor_max_speed_mps, role_conflict_component_gap_at_point_mps, role_conflict_threshold_at_point_mps, role_conflict_context_factor_at_point, role_conflict_current_density_at_point, role_conflict_context_time_conf_at_point, role_conflict_context_weight_at_point, role_conflict_context_removed_weight_at_point, nearest_train_distance_vox, nearest_train_u, nearest_train_v, nearest_train_base_weight, adaptive_current_support, adaptive_context_support, localization_radius_xy, localization_sigma_xy, localization_radius_z, localization_sigma_z, role_overlap_at_point, role_conflict_at_point, z_norm, y_norm, x_norm, alt_norm, pred_speed_norm, support_total, support_log1p, hour_sin, hour_cos, day_sin, day_cos, nearest_source_current_train, nearest_source_context, nearest_source_unknown, representation_risk_score, sigma_rep_proxy_mps, tail_probability_proxy, residual_gate_initial, sample_weight_raw, distance_risk_score, role_gap_risk_score, low_conf_risk_score, support_risk_score, vertical_risk_score, context_only_risk_flag, high_altitude_flag, pred_light_wind_flag`
