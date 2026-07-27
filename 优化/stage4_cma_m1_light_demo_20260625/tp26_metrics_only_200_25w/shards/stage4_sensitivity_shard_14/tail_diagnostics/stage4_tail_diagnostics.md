# Stage4 Tail Diagnostics

Tail strata are diagnostic only. They do not remove aircraft holdout truth from official RMSE/MAE.

| stratum | category | points | frames | RMSE | MAE | P95 | P99 | max | SSE share | mean alt | mean nearest dist | mean role gap |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `all_holdout_points` | `official_baseline` | 23 | 8 | 4.087318 | 3.573236 | 7.670781 | 8.183130 | 8.274112 | 1.000000 | 10000.000000 | 1.197801 | 15.210485 |
| `single_holdout_frame` | `support_tail` | 0 | 0 |  |  |  |  |  | 0.000000 |  |  |  |
| `multi_holdout_ge2_frame` | `support_reference` | 23 | 8 | 4.087318 | 3.573236 | 7.670781 | 8.183130 | 8.274112 | 1.000000 | 10000.000000 | 1.197801 | 15.210485 |
| `multi_holdout_ge3_frame` | `support_reference` | 13 | 3 | 4.163829 | 3.665028 | 6.887319 | 7.996754 | 8.274112 | 0.586576 | 10076.923077 | 1.405501 | 3.177931 |
| `alt_9_12km` | `high_alt_tail` | 3 | 3 | 4.039309 | 4.024605 | 4.399815 | 4.432093 | 4.440162 | 0.127389 | 10833.333333 | 2.128388 | 8.982736 |
| `alt_12km_plus` | `high_alt_tail` | 10 | 7 | 3.653023 | 3.132225 | 5.902660 | 5.950764 | 5.962790 | 0.347296 | 13800.000000 | 1.009977 | 2.689946 |
| `alt_12km_plus_single_holdout` | `combined_tail` | 0 | 0 |  |  |  |  |  | 0.000000 |  |  |  |
| `context_only_nearest_support` | `context_tail` | 7 | 6 | 3.584496 | 3.213297 | 5.506001 | 5.871432 | 5.962790 | 0.234072 | 12714.285714 | 1.724389 | 0.000000 |
| `alt_12km_plus_context_only` | `combined_tail` | 5 | 5 | 3.309869 | 2.824477 | 5.454322 | 5.861096 | 5.962790 | 0.142556 | 13800.000000 | 1.337112 | 0.000000 |
| `single_holdout_context_only` | `combined_tail` | 0 | 0 |  |  |  |  |  | 0.000000 |  |  |  |
| `nearest_context_wind` | `support_tail` | 10 | 7 | 3.760583 | 3.357537 | 5.889199 | 5.948071 | 5.962790 | 0.368049 | 12500.000000 | 1.207072 | 4.006678 |
| `nearest_current_wind_train` | `support_reference` | 13 | 7 | 4.321877 | 3.739159 | 8.025979 | 8.224486 | 8.274112 | 0.631951 | 8076.923077 | 1.190670 | 23.828799 |
| `nearest_distance_gt4vox` | `remote_support_tail` | 1 | 1 | 4.440162 | 4.440162 | 4.440162 | 4.440162 | 4.440162 | 0.051309 | 11500.000000 | 5.385165 | 0.000000 |
| `role_gap_ge30mps` | `role_conflict_tail` | 2 | 2 | 5.710696 | 4.857065 | 7.560208 | 7.800488 | 7.860557 | 0.169747 | 8250.000000 | 1.414214 | 136.761240 |
| `role_conflict_at_point` | `role_conflict_tail` | 6 | 5 | 4.966194 | 4.083571 | 8.170724 | 8.253435 | 8.274112 | 0.385118 | 9750.000000 | 1.413118 | 47.156147 |
| `qc_review_flag` | `qc_tail` | 13 | 7 | 4.278018 | 3.614962 | 8.025979 | 8.224486 | 8.274112 | 0.619190 | 11346.153846 | 1.580725 | 21.764376 |
| `no_qc_review_flag` | `clean_reference` | 10 | 6 | 3.825221 | 3.518993 | 5.815707 | 5.826476 | 5.829168 | 0.380810 | 8250.000000 | 0.700000 | 6.690428 |
| `high_vector_error_ge30mps` | `error_tail` | 0 | 0 |  |  |  |  |  | 0.000000 |  |  |  |
| `extreme_truth_speed_ge120mps` | `qc_tail` | 0 | 0 |  |  |  |  |  | 0.000000 |  |  |  |
| `extreme_prediction_speed_ge120mps` | `qc_tail` | 0 | 0 |  |  |  |  |  | 0.000000 |  |  |  |
