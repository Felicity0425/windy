# Stage4 Representation-Error Report

This report is generated from strict holdout point departures. It is report-only: it does not change `recon_u/v`, `recon_conf`, `recon_mask`, NPZ fields, or official RMSE/MAE.

Score/rule inputs are restricted to truth-free support and reconstruction diagnostics. Holdout truth fields are used only as report targets.

## Validation Boundary

| check | value | result |
| --- | --- | --- |
| strict_holdout_no_leakage | `True` | PASS |
| motion_used_as_wind | `False` | PASS |
| report_only_no_recon_change | `True` | PASS |
| truth_used_for_score_features | `False` | PASS |
| official_holdout_points_removed | `0` | PASS |

Excluded from score/rule inputs: `vector_error`, `gt_u/v`, `gt_speed`, `qc_review_flag`, `qc_review_reasons`, `point_neighbor_*_vector_error`, and `representativeness_gap_point_minus_min_mps`.

## Overall Target Distribution

| points | RMSE | MAE | P95 | P99 | high-error >=30 m/s |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 530 | 14.769036 | 6.854454 | 23.889507 | 63.542791 | 21 |

## Representation-Equivalent Auxiliary Metrics

These are auxiliary evaluation metrics only. They keep the official center-voxel strict holdout score unchanged and add a narrower neighborhood-equivalent view for representation-mismatch diagnosis.

| metric | official | RMSE | MAE | P95 | P99 | RMSE gain vs official | MAE gain vs official |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `official_center_voxel` | `True` | 14.769036 | 6.854454 | 23.889507 | 63.542791 | 0.000000 | 0.000000 |
| `representation_equivalent_neighbor_min_r1` | `False` | 11.598926 | 5.029302 | 16.596271 | 57.767942 | 3.170110 | 1.825152 |
| `representation_equivalent_neighbor_weighted_r1` | `False` | 14.126735 | 7.144267 | 22.783186 | 61.130780 | 0.642301 | -0.289813 |

## Rule Candidates

| rule | flagged | high-error recall | high-error precision | unflagged RMSE | SSE share captured | P95 recall | P99 recall |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `truth_free_conservative_rule_v1` | 328 | 1.000000 | 0.064024 | 5.520299 | 0.946753 | 0.925926 | 1.000000 |
| `truth_free_compact_rule_v1` | 139 | 0.809524 | 0.122302 | 7.228706 | 0.823267 | 0.666667 | 1.000000 |
| `score_ge_0p20` | 195 | 0.857143 | 0.092308 | 7.072306 | 0.855061 | 0.703704 | 1.000000 |
| `score_ge_0p25` | 107 | 0.857143 | 0.168224 | 6.911493 | 0.825215 | 0.703704 | 1.000000 |
| `score_ge_0p35` | 34 | 0.619048 | 0.382353 | 8.357593 | 0.700316 | 0.481481 | 1.000000 |
| `score_ge_0p50` | 10 | 0.380952 | 0.800000 | 10.260653 | 0.526442 | 0.296296 | 0.666667 |
| `remote_or_low_confidence` | 29 | 0.333333 | 0.241379 | 13.149229 | 0.250696 | 0.259259 | 0.500000 |
| `context_only_or_nearest_speed_ge30` | 295 | 0.952381 | 0.067797 | 6.710974 | 0.908450 | 0.851852 | 1.000000 |

## Score Bucket Calibration

| score bucket | points | sigma_rep/RMSE | tail prob >=30 | high-error recall | SSE share | cumulative high-error recall | cumulative SSE share |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `lt_0p10` | 184 | 4.968807 | 0.000000 | 0.000000 | 0.039295 | 1.000000 | 1.000000 |
| `0p10_to_0p20` | 151 | 8.993405 | 0.019868 | 0.142857 | 0.105644 | 1.000000 | 0.960705 |
| `0p20_to_0p35` | 161 | 10.541081 | 0.031056 | 0.238095 | 0.154745 | 0.857143 | 0.855061 |
| `0p35_to_0p50` | 24 | 28.940198 | 0.208333 | 0.238095 | 0.173874 | 0.619048 | 0.700316 |
| `ge_0p50` | 10 | 78.012700 | 0.800000 | 0.380952 | 0.526442 | 0.380952 | 0.526442 |

## Highest-Risk Truth-Free Buckets

| feature | bucket | points | high-error count | high-error rate | rate lift | RMSE | SSE share | mean score |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `representation_error_score_bin` | `ge_0p50` | 10 | 8 | 0.800000 | 20.190476 | 78.012700 | 0.526442 | 0.539515 |
| `vertical_proxy_bin` | `ge_25mps` | 7 | 5 | 0.714286 | 18.027211 | 78.917311 | 0.377105 | 0.449543 |
| `nearest_distance_bin` | `gt_8vox` | 7 | 5 | 0.714286 | 18.027211 | 56.838337 | 0.195614 | 0.489119 |
| `recon_confidence_bin` | `lt_0p05` | 17 | 6 | 0.352941 | 8.907563 | 40.047824 | 0.235845 | 0.416732 |
| `nearest_train_speed_bin` | `ge_60mps` | 26 | 6 | 0.230769 | 5.824176 | 46.946485 | 0.495678 | 0.335733 |
| `representation_error_score_bin` | `0p35_to_0p50` | 24 | 5 | 0.208333 | 5.257937 | 28.940198 | 0.173874 | 0.405180 |
| `nearest_role_gap_bin` | `ge_60mps` | 15 | 3 | 0.200000 | 5.047619 | 51.101516 | 0.338828 | 0.377626 |
| `recon_confidence_bin` | `0p05_to_0p20` | 18 | 3 | 0.166667 | 4.206349 | 44.376443 | 0.306618 | 0.317273 |
| `adaptive_current_support_bin` | `0` | 8 | 1 | 0.125000 | 3.154762 | 30.989602 | 0.066457 | 0.360521 |
| `pred_speed_bin` | `ge_60mps` | 16 | 2 | 0.125000 | 3.154762 | 19.136340 | 0.050682 | 0.274678 |
| `vertical_proxy_bin` | `10_to_25mps` | 34 | 4 | 0.117647 | 2.969188 | 21.902772 | 0.141090 | 0.248570 |
| `role_conflict_removed_weight_bin` | `0_to_0p05` | 17 | 2 | 0.117647 | 2.969188 | 18.048947 | 0.047904 | 0.185732 |
| `pred_speed_bin` | `lt_5mps` | 55 | 6 | 0.109091 | 2.753247 | 22.132960 | 0.233057 | 0.147967 |
| `nearest_distance_bin` | `4_to_8vox` | 20 | 2 | 0.100000 | 2.523810 | 17.180994 | 0.051068 | 0.343893 |
| `recon_confidence_bin` | `0p20_to_0p50` | 43 | 4 | 0.093023 | 2.347730 | 17.566000 | 0.114772 | 0.240145 |
| `context_only_nearest_support` | `true` | 184 | 13 | 0.070652 | 1.783126 | 17.305344 | 0.476648 | 0.267640 |
| `nearest_current_count_bin` | `0` | 184 | 13 | 0.070652 | 1.783126 | 17.305344 | 0.476648 | 0.267640 |
| `altitude_bin` | `12km_plus` | 222 | 15 | 0.067568 | 1.705277 | 19.917698 | 0.761818 | 0.213755 |

## Top Target Tail Points

| rank | frame | z/y/x | alt | gt speed target | pred speed | nearest train speed | error target | score | reasons |
| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 1 | `20260223133000` | `29/345/498` | 14500.0 | 198.000000 | 53.476727 | 164.000000 | 180.131789 | 0.569884 | `role_gap_ge30;vertical_proxy_ge10;vertical_proxy_ge25;nearest_train_speed_ge30;high_altitude_12km_plus` |
| 2 | `20260207001200` | `25/256/520` | 12500.0 | 101.000000 | 22.979613 | 101.000000 | 98.605778 | 0.367673 | `context_only_nearest_support;nearest_train_speed_ge30;high_altitude_12km_plus` |
| 3 | `20260131182400` | `28/383/548` | 14000.0 | 87.000000 | 0.942383 | 74.000000 | 86.061243 | 0.597030 | `remote_support;low_recon_confidence;context_only_nearest_support;vertical_proxy_ge10;nearest_train_speed_ge30;high_altitude_12km_plus` |
| 4 | `20260205190000` | `24/360/518` | 12000.0 | 86.000000 | 0.000000 | 46.000000 | 86.000000 | 0.559000 | `remote_support;low_recon_confidence;context_only_nearest_support;nearest_train_speed_ge30;high_altitude_12km_plus;low_adaptive_current_support` |
| 5 | `20260130174200` | `28/384/547` | 14000.0 | 73.000000 | 0.000000 | 39.000000 | 73.000000 | 0.518500 | `remote_support;low_recon_confidence;context_only_nearest_support;nearest_train_speed_ge30;high_altitude_12km_plus` |
| 6 | `20260125041200` | `21/322/504` | 10500.0 | 98.000000 | 35.383619 | 28.000000 | 64.822133 | 0.433922 | `context_only_nearest_support;vertical_proxy_ge10;vertical_proxy_ge25;role_conflict_at_point;low_adaptive_current_support` |
| 7 | `20260223133000` | `27/345/498` | 13500.0 | 182.000000 | 153.156928 | 164.000000 | 60.410609 | 0.560086 | `role_gap_ge30;vertical_proxy_ge10;vertical_proxy_ge25;nearest_train_speed_ge30;high_altitude_12km_plus;role_conflict_at_point` |
| 8 | `20260210000600` | `23/250/493` | 11500.0 | 77.000000 | 20.929431 | 38.000000 | 58.508859 | 0.292219 | `context_only_nearest_support;nearest_train_speed_ge30;low_adaptive_current_support` |
| 9 | `20260125124200` | `29/307/507` | 14500.0 | 57.000000 | 0.676521 | 55.000000 | 56.324013 | 0.298757 | `remote_support;low_recon_confidence;nearest_train_speed_ge30;high_altitude_12km_plus` |
| 10 | `20260202123000` | `20/288/515` | 10000.0 | 30.000000 | 25.695639 | 11.000000 | 51.527214 | 0.197063 | `vertical_proxy_ge10;role_conflict_at_point` |
| 11 | `20260210100600` | `29/377/546` | 14500.0 | 35.000000 | 62.249438 | 148.000000 | 43.980542 | 0.514833 | `role_gap_ge30;vertical_proxy_ge10;vertical_proxy_ge25;nearest_train_speed_ge30;high_altitude_12km_plus;role_conflict_at_point` |
| 12 | `20260202181200` | `24/242/509` | 12000.0 | 52.000000 | 11.743751 | 24.000000 | 40.764004 | 0.266000 | `context_only_nearest_support;high_altitude_12km_plus;low_adaptive_current_support` |

## Minimum Checklist

| item | value | result |
| --- | ---: | --- |
| top-risk score>=0.20 SSE share | 0.855061 | PASS |
| top-risk score>=0.20 high-error recall | 0.857143 | PASS |
| low-risk score<0.20 RMSE | 7.072306 | PASS |
| conservative rule high-error recall | 1.000000 | PASS |
| all official holdout points retained | 530 | PASS |

Conclusion: this report supports representation-error / no-claim calibration as a report-only diagnostic. It is not a promotion of a reconstruction branch.
