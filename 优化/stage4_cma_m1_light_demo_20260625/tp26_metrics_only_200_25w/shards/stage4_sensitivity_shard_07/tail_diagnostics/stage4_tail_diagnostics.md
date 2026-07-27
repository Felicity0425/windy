# Stage4 Tail Diagnostics

Tail strata are diagnostic only. They do not remove aircraft holdout truth from official RMSE/MAE.

| stratum | category | points | frames | RMSE | MAE | P95 | P99 | max | SSE share | mean alt | mean nearest dist | mean role gap |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `all_holdout_points` | `official_baseline` | 17 | 8 | 5.730283 | 4.923425 | 9.375410 | 9.662189 | 9.733884 | 1.000000 | 10676.470588 | 1.374029 | 4.562987 |
| `single_holdout_frame` | `support_tail` | 3 | 3 | 8.583865 | 8.450480 | 9.688779 | 9.724863 | 9.733884 | 0.395992 | 11500.000000 | 1.824045 | 0.000000 |
| `multi_holdout_ge2_frame` | `support_reference` | 14 | 5 | 4.907474 | 4.167627 | 8.463053 | 9.121244 | 9.285792 | 0.604008 | 10500.000000 | 1.277596 | 5.540770 |
| `multi_holdout_ge3_frame` | `support_reference` | 12 | 4 | 4.849514 | 4.094138 | 8.589629 | 9.146559 | 9.285792 | 0.505564 | 10583.333333 | 1.220857 | 5.915935 |
| `alt_9_12km` | `high_alt_tail` | 3 | 3 | 5.539774 | 4.212259 | 8.558437 | 9.140321 | 9.285792 | 0.164932 | 10000.000000 | 0.666667 | 2.519952 |
| `alt_12km_plus` | `high_alt_tail` | 9 | 7 | 5.700498 | 5.065148 | 9.048346 | 9.596776 | 9.733884 | 0.523923 | 13666.666667 | 1.928721 | 7.047930 |
| `alt_12km_plus_single_holdout` | `combined_tail` | 2 | 2 | 8.212101 | 8.034303 | 9.563926 | 9.699892 | 9.733884 | 0.241623 | 13250.000000 | 2.236068 | 0.000000 |
| `context_only_nearest_support` | `context_tail` | 9 | 6 | 6.370391 | 5.533688 | 9.554647 | 9.698036 | 9.733884 | 0.654295 | 10388.888889 | 1.052460 | 0.000000 |
| `alt_12km_plus_context_only` | `combined_tail` | 4 | 4 | 6.639995 | 6.273637 | 9.224009 | 9.631909 | 9.733884 | 0.315933 | 13250.000000 | 1.618034 | 0.000000 |
| `single_holdout_context_only` | `combined_tail` | 3 | 3 | 8.583865 | 8.450480 | 9.688779 | 9.724863 | 9.733884 | 0.395992 | 11500.000000 | 1.824045 | 0.000000 |
| `nearest_context_wind` | `support_tail` | 13 | 7 | 5.928680 | 4.989273 | 9.465029 | 9.680113 | 9.733884 | 0.818575 | 11153.846154 | 1.086340 | 1.842159 |
| `nearest_current_wind_train` | `support_reference` | 4 | 2 | 5.031756 | 4.709417 | 6.783932 | 7.041653 | 7.106083 | 0.181425 | 9125.000000 | 2.309017 | 13.405679 |
| `nearest_distance_gt4vox` | `remote_support_tail` | 0 | 0 |  |  |  |  |  | 0.000000 |  |  |  |
| `role_gap_ge30mps` | `role_conflict_tail` | 1 | 1 | 4.662141 | 4.662141 | 4.662141 | 4.662141 | 4.662141 | 0.038938 | 14500.000000 | 4.000000 | 47.043158 |
| `role_conflict_at_point` | `role_conflict_tail` | 2 | 2 | 3.744948 | 3.231454 | 4.934890 | 5.086307 | 5.124161 | 0.050248 | 11250.000000 | 0.500000 | 3.779928 |
| `qc_review_flag` | `qc_tail` | 13 | 8 | 5.503096 | 4.507836 | 9.465029 | 9.680113 | 9.733884 | 0.705272 | 11346.153846 | 1.285246 | 4.384829 |
| `no_qc_review_flag` | `clean_reference` | 4 | 4 | 6.413299 | 6.274088 | 7.882947 | 7.992621 | 8.020040 | 0.294728 | 8500.000000 | 1.662570 | 5.142003 |
| `high_vector_error_ge30mps` | `error_tail` | 0 | 0 |  |  |  |  |  | 0.000000 |  |  |  |
| `extreme_truth_speed_ge120mps` | `qc_tail` | 0 | 0 |  |  |  |  |  | 0.000000 |  |  |  |
| `extreme_prediction_speed_ge120mps` | `qc_tail` | 0 | 0 |  |  |  |  |  | 0.000000 |  |  |  |
