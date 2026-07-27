# Stage4 Tail Diagnostics

Tail strata are diagnostic only. They do not remove aircraft holdout truth from official RMSE/MAE.

| stratum | category | points | frames | RMSE | MAE | P95 | P99 | max | SSE share | mean alt | mean nearest dist | mean role gap |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `all_holdout_points` | `official_baseline` | 18 | 8 | 4.259100 | 3.482345 | 7.948139 | 8.681969 | 8.865426 | 1.000000 | 10472.222222 | 1.517796 | 6.845526 |
| `single_holdout_frame` | `support_tail` | 2 | 2 | 1.823696 | 1.669760 | 2.329754 | 2.388420 | 2.403087 | 0.020372 | 8250.000000 | 0.500000 | 2.544338 |
| `multi_holdout_ge2_frame` | `support_reference` | 16 | 6 | 4.471207 | 3.708919 | 8.056056 | 8.703552 | 8.865426 | 0.979628 | 10750.000000 | 1.645020 | 7.383174 |
| `multi_holdout_ge3_frame` | `support_reference` | 10 | 3 | 3.961082 | 3.419423 | 6.106703 | 6.351566 | 6.412781 | 0.480529 | 10400.000000 | 1.343398 | 9.326176 |
| `alt_9_12km` | `high_alt_tail` | 4 | 4 | 4.336843 | 4.079852 | 5.673503 | 5.720787 | 5.732608 | 0.230409 | 9875.000000 | 1.813958 | 2.495622 |
| `alt_12km_plus` | `high_alt_tail` | 9 | 6 | 4.777133 | 3.959439 | 8.433762 | 8.779093 | 8.865426 | 0.629026 | 13833.333333 | 1.784944 | 8.735906 |
| `alt_12km_plus_single_holdout` | `combined_tail` | 0 | 0 |  |  |  |  |  | 0.000000 |  |  |  |
| `context_only_nearest_support` | `context_tail` | 5 | 3 | 5.091727 | 4.970302 | 6.276747 | 6.385574 | 6.412781 | 0.397001 | 10200.000000 | 2.286796 | 0.000000 |
| `alt_12km_plus_context_only` | `combined_tail` | 2 | 2 | 3.683846 | 3.683772 | 3.704810 | 3.706680 | 3.707148 | 0.083124 | 14500.000000 | 3.207107 | 0.000000 |
| `single_holdout_context_only` | `combined_tail` | 0 | 0 |  |  |  |  |  | 0.000000 |  |  |  |
| `nearest_context_wind` | `support_tail` | 12 | 7 | 3.895788 | 3.459722 | 6.038686 | 6.337962 | 6.412781 | 0.557781 | 10250.000000 | 1.472504 | 9.018465 |
| `nearest_current_wind_train` | `support_reference` | 6 | 6 | 4.905659 | 3.527593 | 8.595636 | 8.811468 | 8.865426 | 0.442219 | 10916.666667 | 1.608380 | 2.499648 |
| `nearest_distance_gt4vox` | `remote_support_tail` | 1 | 1 | 3.707148 | 3.707148 | 3.707148 | 3.707148 | 3.707148 | 0.042089 | 14500.000000 | 5.000000 | 0.000000 |
| `role_gap_ge30mps` | `role_conflict_tail` | 1 | 1 | 0.890158 | 0.890158 | 0.890158 | 0.890158 | 0.890158 | 0.002427 | 14500.000000 | 1.000000 | 55.787992 |
| `role_conflict_at_point` | `role_conflict_tail` | 4 | 2 | 1.075370 | 1.064525 | 1.223934 | 1.226738 | 1.227439 | 0.014167 | 10500.000000 | 1.000000 | 20.728951 |
| `qc_review_flag` | `qc_tail` | 9 | 5 | 3.862269 | 3.234401 | 6.140712 | 6.358368 | 6.412781 | 0.411168 | 10333.333333 | 1.714886 | 9.212867 |
| `no_qc_review_flag` | `clean_reference` | 9 | 5 | 4.621986 | 3.730290 | 8.433762 | 8.779093 | 8.865426 | 0.588832 | 10611.111111 | 1.320706 | 4.478184 |
| `high_vector_error_ge30mps` | `error_tail` | 0 | 0 |  |  |  |  |  | 0.000000 |  |  |  |
| `extreme_truth_speed_ge120mps` | `qc_tail` | 0 | 0 |  |  |  |  |  | 0.000000 |  |  |  |
| `extreme_prediction_speed_ge120mps` | `qc_tail` | 0 | 0 |  |  |  |  |  | 0.000000 |  |  |  |
