# Stage4 Pairwise Frame Comparison

Baseline: `tp26`
Candidate: `s4a_downweight`

## Aggregate

| metric | value |
| --- | ---: |
| `frames` | 200.000000 |
| `holdout_points` | 530.000000 |
| `tp26_frame_mean_rmse` | 8.403722 |
| `s4a_downweight_frame_mean_rmse` | 8.400417 |
| `tp26_frame_mean_mae` | 7.200442 |
| `s4a_downweight_frame_mean_mae` | 7.223910 |
| `tp26_median_rmse` | 4.498770 |
| `s4a_downweight_median_rmse` | 4.480290 |
| `tp26_weighted_rmse` | 14.868531 |
| `s4a_downweight_weighted_rmse` | 15.049371 |
| `tp26_weighted_mae` | 6.952149 |
| `s4a_downweight_weighted_mae` | 6.995963 |
| `tp26_trimmed_rmse_p95` | 8.079312 |
| `s4a_downweight_trimmed_rmse_p95` | 7.969255 |
| `candidate_wins` | 85.000000 |
| `candidate_losses` | 88.000000 |
| `ties` | 27.000000 |
| `mean_delta_rmse` | -0.003305 |
| `median_delta_rmse` | 0.000000 |
| `p90_candidate_rmse` | 19.300959 |
| `p95_candidate_rmse` | 27.975163 |
| `p99_candidate_rmse` | 58.746097 |
| `max_candidate_rmse` | 109.062222 |
| `p90_baseline_rmse` | 18.205387 |
| `p95_baseline_rmse` | 27.989640 |
| `p99_baseline_rmse` | 58.783770 |
| `max_baseline_rmse` | 108.826876 |
| `all_strict_holdout_no_leakage` | `True` |
| `any_motion_used_as_wind` | `False` |

## Promotion Checklist

Overall: `FAIL`

| gate | baseline | candidate | passed |
| --- | ---: | ---: | --- |
| `strict_holdout_no_leakage_all_true` | `True` | `True` | `True` |
| `motion_used_as_wind_all_false` | `False` | `False` | `True` |
| `weighted_rmse_no_worse` | `14.868531084096004` | `15.049370865795895` | `False` |
| `frame_p95_no_worse` | `27.98963951592178` | `27.97516329898089` | `True` |
| `frame_p99_no_worse` | `58.78377017267204` | `58.746096854646275` | `True` |
| `alt_12km_plus_vector_rmse_no_worse` | `20.01215889399047` | `19.980172732880444` | `True` |
| `light_wind_vector_rmse_mps_no_worse` | `5.1912373974359465` | `5.051847492151737` | `True` |
| `light_wind_vector_mae_mps_no_worse` | `4.172283795723608` | `4.058591552162469` | `True` |
| `floor10_relative_error_mae_no_worse` | `0.28641134420940795` | `0.2828871207677611` | `True` |
| `light_moderate_relative_tail_no_new_failure` | `0` | `0` | `True` |

## Baseline RMSE Bands

| group | frames | baseline RMSE | candidate RMSE | delta | wins | losses |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `baseline_rmse_le6` | 132 | 3.530784 | 3.523482 | -0.007303 | 51 | 58 |
| `baseline_rmse_6_10` | 33 | 7.469416 | 7.445651 | -0.023765 | 14 | 16 |
| `baseline_rmse_10_20` | 16 | 13.958053 | 13.166583 | -0.791470 | 10 | 6 |
| `baseline_rmse_gt20` | 19 | 39.203224 | 39.926942 | 0.723718 | 10 | 8 |

## Paper-Aligned Aircraft Departure Metrics

These metrics use point-level analysis departures: `reconstruction - withheld aircraft wind`. The literature sigma columns are observation-error reference priors; they are not direct targets for Stage4 reconstruction RMSE.

| method | points | u bias | v bias | u RMSE | v RMSE | component RMSE | vector RMSE | de Haan sigma | EMADDC sigma | comp/de Haan | comp/EMADDC | norm chi2 de Haan | norm chi2 EMADDC |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `tp26` | 530 | -1.387090 | 0.727606 | 10.953328 | 10.054741 | 10.513639 | 14.868531 | 1.123585 | 2.729245 | 9.357227 | 3.852215 | 90.661080 | 14.294522 |
| `s4a_downweight` | 530 | -1.680196 | 0.776684 | 11.143648 | 10.114479 | 10.641512 | 15.049371 | 1.123585 | 2.729245 | 9.471035 | 3.899068 | 92.895466 | 14.639871 |

## Paper-Aligned Height Bins

| altitude bin | method | points | component RMSE | vector RMSE | de Haan sigma | EMADDC sigma | comp/de Haan | comp/EMADDC | p95 vector | max vector |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `0-3km` | `tp26` | 39 | 4.026536 | 5.694382 | 1.300000 | 2.200000 | 3.097335 | 1.830244 | 8.680026 | 23.897143 |
| `0-3km` | `s4a_downweight` | 39 | 4.025233 | 5.692539 | 1.300000 | 2.200000 | 3.096333 | 1.829651 | 8.628955 | 23.903745 |
| `3-6km` | `tp26` | 47 | 5.928664 | 8.384397 | 1.200000 | 2.500000 | 4.940553 | 2.371466 | 14.841372 | 29.355886 |
| `3-6km` | `s4a_downweight` | 47 | 5.939285 | 8.399418 | 1.200000 | 2.500000 | 4.949404 | 2.375714 | 14.842204 | 29.355886 |
| `6-9km` | `tp26` | 85 | 5.389506 | 7.621912 | 1.100000 | 2.800000 | 4.899551 | 1.924823 | 13.850339 | 36.164613 |
| `6-9km` | `s4a_downweight` | 85 | 5.815069 | 8.223750 | 1.100000 | 2.800000 | 5.286426 | 2.076810 | 14.661777 | 36.346216 |
| `9-12km` | `tp26` | 137 | 8.273214 | 11.700092 | 1.100000 | 2.800000 | 7.521104 | 2.954719 | 22.910233 | 63.700871 |
| `9-12km` | `s4a_downweight` | 137 | 8.772064 | 12.405572 | 1.100000 | 2.800000 | 7.974604 | 3.132880 | 26.885017 | 75.917213 |
| `12km+` | `tp26` | 222 | 14.150733 | 20.012159 | 1.100000 | 2.800000 | 12.864303 | 5.053833 | 35.523317 | 178.995501 |
| `12km+` | `s4a_downweight` | 222 | 14.128116 | 19.980173 | 1.100000 | 2.800000 | 12.843741 | 5.045756 | 35.448696 | 179.187572 |

Reference mapping:

- `de Haan sigma` is the project height-bin approximation of Mode-S EHS component observation error from de Haan (2016).
- `EMADDC sigma` is the project operational aircraft-derived wind prior from EMADDC (2025).
- Values above these priors indicate reconstruction, representativeness, localization, and sparse-support error in addition to aircraft observation error.
