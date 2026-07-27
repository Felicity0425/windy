# Stage4 Tail Diagnostics

Tail strata are diagnostic only. They do not remove aircraft holdout truth from official RMSE/MAE.

| stratum | category | points | frames | RMSE | MAE | P95 | P99 | max | SSE share | mean alt | mean nearest dist | mean role gap |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `all_holdout_points` | `official_baseline` | 28 | 8 | 10.557681 | 4.977398 | 9.695946 | 40.443336 | 51.527214 | 1.000000 | 10107.142857 | 0.831838 | 6.773095 |
| `single_holdout_frame` | `support_tail` | 0 | 0 |  |  |  |  |  | 0.000000 |  |  |  |
| `multi_holdout_ge2_frame` | `support_reference` | 28 | 8 | 10.557681 | 4.977398 | 9.695946 | 40.443336 | 51.527214 | 1.000000 | 10107.142857 | 0.831838 | 6.773095 |
| `multi_holdout_ge3_frame` | `support_reference` | 22 | 5 | 11.801355 | 5.639818 | 10.364406 | 42.906420 | 51.527214 | 0.981728 | 10272.727273 | 0.409091 | 5.709753 |
| `alt_9_12km` | `high_alt_tail` | 7 | 6 | 19.533800 | 8.524451 | 37.045515 | 48.630874 | 51.527214 | 0.855808 | 10357.142857 | 0.571429 | 13.854074 |
| `alt_12km_plus` | `high_alt_tail` | 12 | 7 | 4.238971 | 3.424935 | 7.625880 | 8.123268 | 8.247615 | 0.069089 | 13708.333333 | 1.004615 | 3.590663 |
| `alt_12km_plus_single_holdout` | `combined_tail` | 0 | 0 |  |  |  |  |  | 0.000000 |  |  |  |
| `context_only_nearest_support` | `context_tail` | 11 | 6 | 5.101972 | 4.261889 | 8.796502 | 10.139954 | 10.475816 | 0.091743 | 10954.545455 | 0.454545 | 0.000000 |
| `alt_12km_plus_context_only` | `combined_tail` | 7 | 6 | 3.921166 | 3.316288 | 6.213626 | 6.936475 | 7.117188 | 0.034485 | 13928.571429 | 0.142857 | 0.000000 |
| `single_holdout_context_only` | `combined_tail` | 0 | 0 |  |  |  |  |  | 0.000000 |  |  |  |
| `nearest_context_wind` | `support_tail` | 20 | 7 | 12.361426 | 6.027013 | 12.528386 | 43.727448 | 51.527214 | 0.979201 | 10200.000000 | 0.300000 | 5.568920 |
| `nearest_current_wind_train` | `support_reference` | 8 | 6 | 2.848524 | 2.353360 | 4.984315 | 5.596975 | 5.750139 | 0.020799 | 9875.000000 | 2.161432 | 9.783532 |
| `nearest_distance_gt4vox` | `remote_support_tail` | 1 | 1 | 5.750139 | 5.750139 | 5.750139 | 5.750139 | 5.750139 | 0.010594 | 14500.000000 | 9.055385 | 13.436997 |
| `role_gap_ge30mps` | `role_conflict_tail` | 1 | 1 | 2.414051 | 2.414051 | 2.414051 | 2.414051 | 2.414051 | 0.001867 | 7500.000000 | 0.000000 | 35.593846 |
| `role_conflict_at_point` | `role_conflict_tail` | 4 | 3 | 26.045075 | 15.628345 | 44.862135 | 50.194198 | 51.527214 | 0.869393 | 8500.000000 | 0.500000 | 21.255308 |
| `qc_review_flag` | `qc_tail` | 15 | 7 | 14.100741 | 7.203396 | 22.791236 | 45.780018 | 51.527214 | 0.955609 | 10800.000000 | 1.003692 | 6.563882 |
| `no_qc_review_flag` | `clean_reference` | 13 | 6 | 3.264567 | 2.408939 | 6.668162 | 7.931724 | 8.247615 | 0.044391 | 9307.692308 | 0.633544 | 7.014494 |
| `high_vector_error_ge30mps` | `error_tail` | 1 | 1 | 51.527214 | 51.527214 | 51.527214 | 51.527214 | 51.527214 | 0.850703 | 10000.000000 | 0.000000 | 28.646333 |
| `extreme_truth_speed_ge120mps` | `qc_tail` | 0 | 0 |  |  |  |  |  | 0.000000 |  |  |  |
| `extreme_prediction_speed_ge120mps` | `qc_tail` | 0 | 0 |  |  |  |  |  | 0.000000 |  |  |  |
