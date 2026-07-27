# Stage4 Tail Diagnostics

Tail strata are diagnostic only. They do not remove aircraft holdout truth from official RMSE/MAE.

| stratum | category | points | frames | RMSE | MAE | P95 | P99 | max | SSE share | mean alt | mean nearest dist | mean role gap |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `all_holdout_points` | `official_baseline` | 18 | 8 | 7.124283 | 4.728769 | 11.238409 | 21.351822 | 23.880175 | 1.000000 | 10555.555556 | 1.291299 | 1.536285 |
| `single_holdout_frame` | `support_tail` | 2 | 2 | 17.656527 | 15.588483 | 23.051006 | 23.714341 | 23.880175 | 0.682473 | 8000.000000 | 2.618034 | 0.000000 |
| `multi_holdout_ge2_frame` | `support_reference` | 16 | 6 | 4.258018 | 3.371305 | 8.211032 | 8.848214 | 9.007510 | 0.317527 | 10875.000000 | 1.125457 | 1.728320 |
| `multi_holdout_ge3_frame` | `support_reference` | 10 | 3 | 3.536487 | 2.906040 | 6.457525 | 7.333920 | 7.553019 | 0.136896 | 11650.000000 | 1.294281 | 2.765313 |
| `alt_9_12km` | `high_alt_tail` | 6 | 5 | 4.486767 | 3.524890 | 7.488962 | 7.540207 | 7.553019 | 0.132210 | 10500.000000 | 1.314392 | 1.128207 |
| `alt_12km_plus` | `high_alt_tail` | 6 | 5 | 2.292784 | 1.966650 | 3.782637 | 3.975528 | 4.023750 | 0.034524 | 14250.000000 | 1.162449 | 2.341748 |
| `alt_12km_plus_single_holdout` | `combined_tail` | 0 | 0 |  |  |  |  |  | 0.000000 |  |  |  |
| `context_only_nearest_support` | `context_tail` | 6 | 4 | 10.867703 | 7.617804 | 19.896516 | 23.083443 | 23.880175 | 0.775661 | 10250.000000 | 1.108380 | 0.000000 |
| `alt_12km_plus_context_only` | `combined_tail` | 2 | 2 | 1.241341 | 1.219985 | 1.426328 | 1.444670 | 1.449255 | 0.003373 | 14500.000000 | 0.707107 | 0.000000 |
| `single_holdout_context_only` | `combined_tail` | 1 | 1 | 23.880175 | 23.880175 | 23.880175 | 23.880175 | 23.880175 | 0.624195 | 7000.000000 | 3.000000 | 0.000000 |
| `nearest_context_wind` | `support_tail` | 7 | 5 | 10.070615 | 6.691125 | 19.099784 | 22.924097 | 23.880175 | 0.777061 | 10285.714286 | 0.950040 | 0.342675 |
| `nearest_current_wind_train` | `support_reference` | 11 | 5 | 4.303026 | 3.479997 | 8.152150 | 8.836438 | 9.007510 | 0.222939 | 10727.272727 | 1.508463 | 2.295855 |
| `nearest_distance_gt4vox` | `remote_support_tail` | 0 | 0 |  |  |  |  |  | 0.000000 |  |  |  |
| `role_gap_ge30mps` | `role_conflict_tail` | 0 | 0 |  |  |  |  |  | 0.000000 |  |  |  |
| `role_conflict_at_point` | `role_conflict_tail` | 3 | 2 | 5.450255 | 4.311842 | 8.339626 | 8.873933 | 9.007510 | 0.097544 | 7166.666667 | 1.688165 | 2.277800 |
| `qc_review_flag` | `qc_tail` | 10 | 6 | 8.944939 | 6.017913 | 17.187475 | 22.541635 | 23.880175 | 0.875790 | 9750.000000 | 1.312899 | 0.683340 |
| `no_qc_review_flag` | `clean_reference` | 8 | 4 | 3.766266 | 3.117339 | 6.534419 | 7.144316 | 7.296790 | 0.124210 | 11562.500000 | 1.264298 | 2.602466 |
| `high_vector_error_ge30mps` | `error_tail` | 0 | 0 |  |  |  |  |  | 0.000000 |  |  |  |
| `extreme_truth_speed_ge120mps` | `qc_tail` | 0 | 0 |  |  |  |  |  | 0.000000 |  |  |  |
| `extreme_prediction_speed_ge120mps` | `qc_tail` | 0 | 0 |  |  |  |  |  | 0.000000 |  |  |  |
