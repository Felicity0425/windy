# Stage4 Tail Diagnostics

Tail strata are diagnostic only. They do not remove aircraft holdout truth from official RMSE/MAE.

| stratum | category | points | frames | RMSE | MAE | P95 | P99 | max | SSE share | mean alt | mean nearest dist | mean role gap |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `all_holdout_points` | `official_baseline` | 14 | 8 | 7.443474 | 4.992595 | 14.302874 | 21.136179 | 22.844505 | 1.000000 | 10464.285714 | 0.991882 | 4.431797 |
| `single_holdout_frame` | `support_tail` | 4 | 4 | 1.968978 | 1.916388 | 2.479810 | 2.529088 | 2.541408 | 0.019992 | 9375.000000 | 1.059017 | 7.232222 |
| `multi_holdout_ge2_frame` | `support_reference` | 10 | 4 | 8.718755 | 6.223078 | 16.931068 | 21.661817 | 22.844505 | 0.980008 | 10900.000000 | 0.965028 | 3.311627 |
| `multi_holdout_ge3_frame` | `support_reference` | 6 | 2 | 10.789118 | 8.311854 | 19.559262 | 22.187456 | 22.844505 | 0.900417 | 11416.666667 | 0.735702 | 3.589434 |
| `alt_9_12km` | `high_alt_tail` | 5 | 4 | 11.162535 | 8.076468 | 19.667505 | 22.209105 | 22.844505 | 0.803186 | 10100.000000 | 1.047214 | 5.785777 |
| `alt_12km_plus` | `high_alt_tail` | 5 | 4 | 5.183929 | 4.355124 | 8.520562 | 9.466940 | 9.703534 | 0.173224 | 14000.000000 | 1.282843 | 3.093758 |
| `alt_12km_plus_single_holdout` | `combined_tail` | 0 | 0 |  |  |  |  |  | 0.000000 |  |  |  |
| `context_only_nearest_support` | `context_tail` | 7 | 5 | 10.190108 | 7.602250 | 18.902214 | 22.056047 | 22.844505 | 0.937079 | 10714.285714 | 1.210305 | 0.000000 |
| `alt_12km_plus_context_only` | `combined_tail` | 2 | 2 | 7.247824 | 6.502778 | 9.383458 | 9.639519 | 9.703534 | 0.135446 | 14500.000000 | 1.500000 | 0.000000 |
| `single_holdout_context_only` | `combined_tail` | 2 | 2 | 1.890952 | 1.873351 | 2.105012 | 2.125604 | 2.130752 | 0.009220 | 8250.000000 | 1.118034 | 0.000000 |
| `nearest_context_wind` | `support_tail` | 10 | 6 | 8.601586 | 5.857061 | 16.931068 | 21.661817 | 22.844505 | 0.953845 | 9900.000000 | 0.947214 | 2.012611 |
| `nearest_current_wind_train` | `support_reference` | 4 | 3 | 2.991718 | 2.831430 | 3.763104 | 3.783561 | 3.788676 | 0.046155 | 11875.000000 | 1.103553 | 10.479760 |
| `nearest_distance_gt4vox` | `remote_support_tail` | 0 | 0 |  |  |  |  |  | 0.000000 |  |  |  |
| `role_gap_ge30mps` | `role_conflict_tail` | 0 | 0 |  |  |  |  |  | 0.000000 |  |  |  |
| `role_conflict_at_point` | `role_conflict_tail` | 3 | 3 | 13.393068 | 9.336874 | 20.938922 | 22.463388 | 22.844505 | 0.693748 | 11333.333333 | 1.138071 | 6.175428 |
| `qc_review_flag` | `qc_tail` | 9 | 7 | 9.086740 | 6.486874 | 17.588116 | 21.793227 | 22.844505 | 0.958030 | 10833.333333 | 1.209594 | 2.058476 |
| `no_qc_review_flag` | `clean_reference` | 5 | 4 | 2.551660 | 2.302894 | 3.545902 | 3.603736 | 3.618195 | 0.041970 | 9800.000000 | 0.600000 | 8.703774 |
| `high_vector_error_ge30mps` | `error_tail` | 0 | 0 |  |  |  |  |  | 0.000000 |  |  |  |
| `extreme_truth_speed_ge120mps` | `qc_tail` | 0 | 0 |  |  |  |  |  | 0.000000 |  |  |  |
| `extreme_prediction_speed_ge120mps` | `qc_tail` | 0 | 0 |  |  |  |  |  | 0.000000 |  |  |  |
