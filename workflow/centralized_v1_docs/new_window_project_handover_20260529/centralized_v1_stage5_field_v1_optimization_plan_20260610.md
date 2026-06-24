# centralized_v1 Stage5 field-v1 optimization plan

Draft date: 2026-06-10

Purpose: summarize the post-smoke optimization direction after the formal 200-frame Stage5 residual PINN field-v1 smoke test.

## Executive decision

Do not promote Stage5 field-v1 as the default reconstruction method.

The current default remains `tp26_thr11_preserve`. Stage5 field-v1 is structurally safe, but it fails the formal promotion gate because holdout-weighted RMSE and 12 km+ RMSE are slightly worse than the Stage4 default.

The next optimization direction should be conservative:

1. Keep the Stage4 default unchanged.
2. Treat Stage5 as a gated residual candidate only.
3. Optimize the truth-free gate and altitude-aware residual scale before retraining larger neural models.
4. In parallel, prioritize representation-error and reliability weighting because this direction is more stable and more manuscript-defensible.

## Current evidence

### Formal 200-frame field smoke status

Source directory:

```text
centralized_v1_output/stage5_residual_pinn_field_v1_200_20260610/
```

Main files:

```text
stage5_field_smoke_summary.csv
pairwise_original_tp26/tp26_vs_stage5_field_v1_200_summary.csv
pairwise_original_tp26/tp26_vs_stage5_field_v1_200_promotion_checklist.csv
pairwise_original_tp26/tp26_vs_stage5_field_v1_200_paper_point_departures.csv
```

Structure checks passed:

| Check | Result |
| --- | ---: |
| Frames | 200 |
| Holdout points | 530 |
| Gate rule | `vertical_gap_ge20_not_light` |
| Non-gate changed voxels | 0 |
| NaN/Inf count | 0 |
| Changed voxels | 2,532,697 |
| Gate voxels | 2,532,697 |
| `changed_voxels == gate_voxels` | true |
| Residual cap OK | true |
| Max vector residual | 1.4126 m/s |

Interpretation: the field application code is mechanically safe. It does not perturb non-gated voxels, does not generate invalid values, and respects the residual cap.

### Formal promotion status

Promotion result: **FAIL**.

| Metric | `tp26_thr11_preserve` | Stage5 field-v1 | Direction |
| --- | ---: | ---: | --- |
| Holdout-weighted RMSE | 14.7690356 | 14.7714931 | worse |
| Holdout-weighted MAE | 6.8544542 | 6.8541252 | slightly better |
| Frame mean RMSE | 8.2243094 | 8.2190661 | better |
| Frame mean MAE | 7.0819089 | 7.0812025 | better |
| Frame P95 RMSE | 27.9861110 | 27.9861110 | tie |
| Frame P99 RMSE | 58.7837702 | 58.7837702 | tie |
| 12 km+ vector RMSE | 19.9176978 | 19.9417944 | worse |

Frame-level result:

| Category | Count |
| --- | ---: |
| Candidate wins | 3 |
| Candidate losses | 3 |
| Ties | 194 |

Point-level result:

| Category | Count |
| --- | ---: |
| Changed frames | 6 |
| Changed holdout points | 7 |
| Improved changed points | 3 |
| Worsened changed points | 4 |
| Net changed-point delta sum | -0.1744 m/s |

The Stage5 signal is real but too small and too unstable. The failure is not a broad field corruption problem; it is a gate/correction-targeting problem concentrated in a few holdout points.

## Changed holdout points

Meaningful point-level deltas greater than `1e-6` m/s:

| Time | z | Altitude | Ground truth speed | Baseline error | Stage5 error | Delta |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 20260125014200 | 5 | 2,500 m | 4.0 | 23.8971 | 22.7140 | -1.1832 |
| 20260125041200 | 21 | 10,500 m | 98.0 | 64.8221 | 63.8929 | -0.9292 |
| 20260210100600 | 29 | 14,500 m | 35.0 | 43.9805 | 43.4265 | -0.5540 |
| 20260201043000 | 29 | 14,500 m | 37.0 | 19.6015 | 19.6702 | +0.0688 |
| 20260223133000 | 29 | 14,500 m | 198.0 | 180.1318 | 180.5138 | +0.3820 |
| 20260223133000 | 27 | 13,500 m | 182.0 | 60.4106 | 61.3581 | +0.9475 |
| 20260125013000 | 29 | 14,500 m | 29.0 | 2.1110 | 3.2048 | +1.0938 |

Immediate lesson: Stage5 must avoid modifying points where the Stage4 baseline is already locally good. The worst avoidable loss is `20260125013000`, where baseline error was only 2.1110 m/s and Stage5 increased it to 3.2048 m/s.

## Optimization priorities

### Priority 1: Stage5 gate v2

The current gate, `vertical_gap_ge20_not_light`, is too broad for field promotion. It catches some useful vertical-gap cases, but also fires on points where residual correction is unnecessary or directionally wrong.

Next gate should remain truth-free and should add at least one suppressor:

1. Suppress residual correction when Stage4 confidence is high and local support geometry is clean.
2. Suppress residual correction when the target point is high-altitude but weakly supported by neighboring high-altitude anchors.
3. Suppress residual correction in low representation-risk regimes.
4. Lower scale or cap for 12 km+ points unless the role-gap or vertical-mismatch signal is strong.
5. Keep light-wind and floor10-sensitive regimes protected.

The goal is not to increase the number of activated points. The goal is to remove the four worsened changed points while preserving the three useful changes.

### Priority 2: altitude-aware residual scale

The formal failure is driven partly by the 12 km+ guardrail. A single global scale is too crude.

Recommended sweep:

| Altitude regime | Candidate action |
| --- | --- |
| 0-6 km | keep current scale only if floor10/light-wind gates pass |
| 6-12 km | allow current scale under vertical-gap gate |
| 12 km+ | use lower scale or require an additional risk signal |

The 12 km+ group must be a hard promotion gate. Any candidate that improves mean RMSE but worsens 12 km+ RMSE should remain non-promoted.

### Priority 3: representation-error and reliability weighting

Representation-error work is currently more promising than raw residual correction.

Known result:

```text
tp26_rep_soft_weight_v1:
weighted RMSE 14.769036 -> 14.755381 m/s
formal 200-frame guardrail passed
```

This improvement is small, but it is methodologically cleaner. It explains when a holdout departure is likely affected by support geometry and representation mismatch, without deleting difficult truth points.

Recommended next step:

1. Run `tp26_rep_soft_weight_v1` on the full 5,614 holdout-evaluable frame set.
2. Report low-risk and high-risk strata separately.
3. Preserve all official holdout points in the main metric.
4. Use reliability as an audit layer, not as a mechanism to remove failures.

### Priority 4: keep Stage4 mainline stable

Do not modify `tp26_thr11_preserve` unless a new branch passes the full formal gate.

Several intuitive Stage4 branches have already failed because they improved one regime while contaminating another:

| Branch type | Failure mode |
| --- | --- |
| Support-role-height localization | worsened weighted RMSE and 12 km+ RMSE |
| Sparse temporal CMA/NWP | improved some tail metrics but worsened weighted RMSE and light-wind/floor10 metrics |
| Guarded vertical dynamic | reduced some amplification risk but still failed formal gate |

The default Stage4 method is now a stable manuscript baseline. Further optimization should be branch-based and reversible.

## Proposed next experiment

Experiment name:

```text
stage5_residual_pinn_field_v2_gate_sweep_20260610
```

Scope:

```text
fixed residual model: cap1p0_seed20260609_w512_l6
fixed baseline: tp26_thr11_preserve
evaluation set: formal 200-frame, 530-point strict holdout
change surface: truth-free gate rules, altitude scale, residual cap
```

Do not retrain the residual model in this experiment. The purpose is to determine whether the existing residual signal can be safely targeted.

Candidate sweep dimensions:

| Dimension | Values to test |
| --- | --- |
| Gate base | `vertical_gap_ge20_not_light` |
| Confidence suppressor | high-confidence off / no suppressor |
| Altitude scale | global 1.0; 12 km+ 0.5; 12 km+ 0.25; 12 km+ off |
| Support-risk requirement | off; require sparse-support or role-gap flag |
| Residual cap | 1.0; 0.75; 0.5 |

Hard pass criteria:

| Gate | Required result |
| --- | --- |
| Non-gate unchanged | true |
| NaN/Inf count | 0 |
| Residual cap OK | true |
| Strict holdout no leakage | true |
| Motion used as wind | false |
| Weighted RMSE | no worse than 14.7690356 |
| Frame P95 | no worse than 27.9861110 |
| Frame P99 | no worse than 58.7837702 |
| 12 km+ vector RMSE | no worse than 19.9176978 |
| Light-wind RMSE/MAE | no worse |
| Floor10 relative MAE | no worse |
| New light/moderate catastrophic failure | none |

Additional diagnostic target:

```text
changed holdout points <= 7
worsened changed points <= 1
no worsening when baseline vector error < 5 m/s
```

If no Stage5 gate-v2 candidate passes, pause Stage5 field promotion and move effort to full-scale representation-error validation.

## Manuscript implications

The manuscript draft should be updated after the field-v1 smoke result.

Current wording says Stage5 is ready for controlled field-v1 smoke. That is now outdated. The correct wording is:

```text
The Stage5 field-v1 smoke test preserved non-gated grid cells, produced no NaN/Inf values and respected residual caps, but it did not pass formal promotion because holdout-weighted RMSE and 12 km+ RMSE were slightly worse than the Stage4 default. Stage5 is therefore retained as a gated residual candidate rather than a promoted reconstruction method.
```

Recommended claim status:

| Claim | Status |
| --- | --- |
| Stage5 point-level locked-test signal exists | supported |
| Stage5 field-v1 structure is safe | supported |
| Stage5 field-v1 improves formal 200-frame benchmark | not supported |
| Stage5 should replace `tp26_thr11_preserve` | not supported |
| Representation-aware reliability is a stronger next direction | supported |

## Bottom line

The next optimization should not chase a larger neural correction. The system is already close to the guardrail boundary, and the remaining errors are regime-specific.

The highest-value path is:

1. Run a conservative Stage5 gate-v2 sweep with no retraining.
2. Protect 12 km+, light-wind and floor10 regimes as hard constraints.
3. Promote only if weighted RMSE and 12 km+ RMSE are no worse than `tp26_thr11_preserve`.
4. Otherwise, pause Stage5 and scale the representation-error reliability branch to the full 5,614-frame holdout set.
