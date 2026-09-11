# Stage5 Residual PINN Truth-Free Gate Selection

The gate is selected on validation only, then locked before the test split is evaluated.
Rules use Stage4/report features only; truth-speed and error buckets are not rule inputs.

## Selected Gate

- rule: `risk_ge_0p2_or_pred45_not_light`
- scale: `0.500`
- description: Enable where risk >= 0.20 or pred_speed >= 45 m/s, excluding pred-light.
- selected by: `val` guardrail pass and RMSE gain > `0.000000`
- selection policy: `promotion_safe`
- promotion-safe retain fraction: `0.500`

## Locked Metrics

| split | points | enabled | baseline RMSE | gated RMSE | delta RMSE | baseline P95 | gated P95 | baseline P99 | gated P99 | light RMSE base/gated | floor10 base/gated | guardrail |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | --- |
| `train` | 381 | 92 | 13.725409 | 13.714874 | -0.010534 | 27.009251 | 27.009251 | 66.457706 | 66.537216 | 5.543500/5.543589 | 0.304833/0.304659 | `FAIL` |
| `val` | 86 | 18 | 8.617390 | 8.614037 | -0.003353 | 16.937550 | 16.937550 | 35.747789 | 35.747418 | 4.799782/4.798943 | 0.273249/0.273137 | `PASS` |
| `test` | 63 | 18 | 24.379357 | 24.367270 | -0.012087 | 11.790345 | 11.790345 | 105.904655 | 105.844654 | 3.420118/3.420118 | 0.162625/0.162602 | `PASS` |
| `all` | 530 | 128 | 14.769036 | 14.759309 | -0.009726 | 23.889507 | 23.923941 | 63.542790 | 63.591535 | 5.266499/5.266406 | 0.282804/0.282658 | `FAIL` |

## `val` Guardrail

| gate | result |
| --- | --- |
| `weighted_rmse_not_worse` | `PASS` |
| `p95_not_worse` | `PASS` |
| `p99_not_worse` | `PASS` |
| `light_rmse_not_worse` | `PASS` |
| `light_mae_not_worse` | `PASS` |
| `floor10_not_worse` | `PASS` |
| `no_new_light_moderate_tail_failure` | `PASS` |
| `high_error_count_not_worse` | `PASS` |
| `POINT_REPORT_OVERALL` | `PASS` |

## Locked `test` Guardrail

| gate | result |
| --- | --- |
| `weighted_rmse_not_worse` | `PASS` |
| `p95_not_worse` | `PASS` |
| `p99_not_worse` | `PASS` |
| `light_rmse_not_worse` | `PASS` |
| `light_mae_not_worse` | `PASS` |
| `floor10_not_worse` | `PASS` |
| `no_new_light_moderate_tail_failure` | `PASS` |
| `high_error_count_not_worse` | `PASS` |
| `POINT_REPORT_OVERALL` | `PASS` |

## Top Validation Candidates

| rule | scale | val enabled | val delta RMSE | val delta P95 | val light delta | val floor10 delta | val pass | locked test delta RMSE | locked test pass |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: | --- |
| `risk_ge_0p2_or_pred45_not_light` | 1.000 | 18 | -0.004475 | +0.000000 | -0.001663 | -0.000111 | `PASS` | -0.023383 | `FAIL` |
| `risk_ge_0p2_or_pred45_not_light` | 0.750 | 18 | -0.004193 | +0.000000 | -0.001253 | -0.000125 | `PASS` | -0.017834 | `FAIL` |
| `risk_ge_0p15_or_pred45_not_light` | 0.750 | 25 | -0.003509 | +0.000000 | -0.029029 | -0.000005 | `PASS` | -0.019000 | `PASS` |
| `risk_ge_0p2_or_pred45_not_light` | 0.500 | 18 | -0.003353 | +0.000000 | -0.000840 | -0.000112 | `PASS` | -0.012087 | `PASS` |
| `risk_ge_0p15_or_pred45_not_light` | 0.500 | 25 | -0.003157 | +0.000000 | -0.019543 | -0.000038 | `PASS` | -0.013031 | `PASS` |
| `risk_ge_0p15_or_pred45_not_light` | 0.250 | 25 | -0.001988 | +0.000000 | -0.009866 | -0.000037 | `PASS` | -0.006698 | `PASS` |
| `risk_ge_0p2_or_pred45_not_light` | 0.250 | 18 | -0.001955 | +0.000000 | -0.000422 | -0.000071 | `PASS` | -0.006142 | `PASS` |
| `risk_ge_0p2_not_light` | 1.000 | 14 | -0.001805 | +0.000000 | -0.001663 | -0.000160 | `PASS` | -0.023178 | `FAIL` |
| `risk_ge_0p2_not_light` | 0.750 | 14 | -0.001748 | +0.000000 | -0.001253 | -0.000144 | `PASS` | -0.017576 | `FAIL` |
| `risk_0p20_to_0p50_not_light` | 0.750 | 13 | -0.001563 | +0.000000 | -0.001253 | -0.000143 | `PASS` | -0.009919 | `FAIL` |
| `risk_0p20_to_0p50_not_light` | 1.000 | 13 | -0.001557 | +0.000000 | -0.001663 | -0.000158 | `PASS` | -0.012967 | `FAIL` |
| `risk_ge_0p2_not_light` | 0.500 | 14 | -0.001429 | +0.000000 | -0.000840 | -0.000113 | `PASS` | -0.011846 | `FAIL` |
| `risk_0p20_to_0p50_not_light` | 0.500 | 13 | -0.001305 | +0.000000 | -0.000840 | -0.000112 | `PASS` | -0.006742 | `FAIL` |
| `risk_ge_0p15_not_light` | 0.500 | 21 | -0.001233 | +0.000000 | -0.019543 | -0.000039 | `PASS` | -0.012790 | `PASS` |
| `risk_ge_0p15_not_light` | 0.750 | 21 | -0.001065 | +0.000000 | -0.029029 | -0.000024 | `PASS` | -0.018743 | `PASS` |
| `risk_ge_0p15_not_light` | 0.250 | 21 | -0.000878 | +0.000000 | -0.009866 | -0.000031 | `PASS` | -0.006543 | `PASS` |
| `risk_ge_0p2_not_light` | 0.250 | 14 | -0.000846 | +0.000000 | -0.000422 | -0.000065 | `PASS` | -0.005987 | `FAIL` |
| `risk_0p20_to_0p50_not_light` | 0.250 | 13 | -0.000784 | +0.000000 | -0.000422 | -0.000064 | `PASS` | -0.003435 | `FAIL` |
| `risk_ge_0p35_not_light` | 1.000 | 3 | -0.000491 | +0.000000 | -0.001663 | -0.000039 | `PASS` | -0.014770 | `FAIL` |
| `risk_ge_0p4_not_light` | 1.000 | 3 | -0.000491 | +0.000000 | -0.001663 | -0.000039 | `PASS` | -0.015712 | `PASS` |

## Field Decision Boundary

- This is still a point-level report gate, not a field_v1 promotion.
- A field_v1 candidate should only be generated after the locked test point report passes, then it still needs full-field smoke and strict holdout pairwise checks.
