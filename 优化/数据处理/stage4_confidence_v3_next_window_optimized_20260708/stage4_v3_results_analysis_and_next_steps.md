# Stage4 Confidence v3 Next-Window Optimization Results Analysis And Next Steps

Generated at UTC: 2026-07-08T03:20:53.278382+00:00

## Scope And Stage Naming

This is optimization plan phase 3 next-window optimization. It corresponds to large-framework Stage4 confidence/tier modeling, not large-framework Stage5 real AMDAR-ADS-B matching and not a full Stage4 windfield holdout reconstruction run.

## Run Policy

- `POLARS_MAX_THREADS=25`
- `slice_count=25`
- One compact confidence table with `processing_slice_id`.
- Stage2 v7 compact leg table is read once for diagnostic identity-date priors.
- Stage3 v8 reports are consumed; the 19M ADS-B point table is not copied.

## What Changed From v2

- Reduced confidence core from redundant v2 components to 4 core components.
- Removed `time_source_conf`, zero-valued `adsb_match_conf`, zero-valued `spatial_match_conf`, and `density_conf` from `base_support_conf`.
- Kept Stage2 v7 identity-date ADS-B information as a diagnostic field only, not as a real match component.
- Added explicit high-wind support override for Stage4 v3 with audited action reasons.
- Added `confidence_subtier` to split T2 into T2a/T2b for downstream weighting.
- Added conservative `time_uncertainty_s_stage4_v3_continuous` for Stage6 consumption while preserving discrete Stage4 tiering.
- Added validation-only threshold grid, locked-test report-only file, and A0/A1/A2 high-wind branch sensitivity.

## Key Result

- Tier counts: `{'T2': 210537, 'T3': 123358, 'T4': 51301, 'T1': 45818, 'T0': 175}`
- AMDAR tier counts: `{'T2': 210537, 'T3': 123358, 'T4': 51295, 'T1': 45818}`
- AMDAR tier coverage pct: `{'T2': 48.847585195634416, 'T3': 28.6208144628406, 'T4': 11.901171207959017, 'T1': 10.630429133565967}`
- AMDAR T1+T2 coverage pct: `59.478`
- High-wind retained rows: `3018` of `4505`
- T2 subtier detail: `{'T2_total': 210537, 'T2a_direct_support_candidate': 117916, 'T2b_broad_or_lower_weight_support': 92621, 'T2a_pct_of_T2': 56.00725763167519, 'T2b_pct_of_T2': 43.992742368324805}`
- Stage4 next-window checks: `{'confidence_subtier_present': True, 't2_subtier_covers_all_t2_rows': True, 'time_uncertainty_continuous_present': True, 'continuous_time_uncertainty_not_above_step_uncertainty': True, 'identity_risk_diagnostic_present': True, 'identity_risk_diagnostic_not_used_as_adsb_match': True, 'stage2_v7_identity_prior_not_used_in_base_support_conf': True, 'validation_only_threshold_grid_written': True, 'selected_t1_validation_q90_lt_3min': True, 'selected_t2_validation_q90_lt_10min': True, 'selected_t1_validation_wrong_leg_le_1pct': True, 'selected_t2_validation_wrong_leg_le_2pct': True, 'locked_test_not_used_for_threshold_selection': True, 'branch_a1_current_high_wind_retained_ge_2800': True, 'branch_a2_moderate_available_for_downstream_ablation': True, 'all_branches_keep_amdar_t0_zero': True, 'all_branches_keep_amdar_holdout_zero': True, 'passed_stage4_next_window_quality_gate': True}`
- Completion checks: `{'component_count_is_4_core_plus_stage5_conditional': True, 'removed_redundant_v2_components': True, 'stage3_v8_quality_gate_passed': True, 'strict_truth_not_derived_from_confidence': True, 'amdar_effective_strict_truth_rows': 0, 'amdar_effective_strict_truth_v3_rows': 0, 'amdar_t0_rows': 0, 'amdar_holdout_eligible_rows': 0, 'turb_enhanced_holdout_eligible_is_175': True, 'turb_review_rows_is_6': True, 'stage5_match_not_fabricated': True, 'stage2_v7_identity_prior_diagnostic_present': True, 't1_coverage_pct_ge_10': True, 't2_coverage_pct_ge_42': True, 't1_t2_coverage_pct_ge_55': True, 'high_wind_retained_rows_ge_2800': True, 'unsupported_high_wind_rejected': True, 'space_saving_single_compact_table': True, 'passed_stage4_confidence_v3_quality_gate': True, 'confidence_subtier_present': True, 't2_subtier_covers_all_t2_rows': True, 'time_uncertainty_continuous_present': True, 'continuous_time_uncertainty_not_above_step_uncertainty': True, 'identity_risk_diagnostic_present': True, 'identity_risk_diagnostic_not_used_as_adsb_match': True, 'stage2_v7_identity_prior_not_used_in_base_support_conf': True, 'validation_only_threshold_grid_written': True, 'selected_t1_validation_q90_lt_3min': True, 'selected_t2_validation_q90_lt_10min': True, 'selected_t1_validation_wrong_leg_le_1pct': True, 'selected_t2_validation_wrong_leg_le_2pct': True, 'locked_test_not_used_for_threshold_selection': True, 'branch_a1_current_high_wind_retained_ge_2800': True, 'branch_a2_moderate_available_for_downstream_ablation': True, 'all_branches_keep_amdar_t0_zero': True, 'all_branches_keep_amdar_holdout_zero': True, 'passed_stage4_next_window_quality_gate': True}`

## Validation And Branch Audits

- Validation-only selected policy: `{'t1_base_support_conf_min': 0.72, 't2_base_support_conf_min': 0.53, 't3_base_support_conf_min': 0.3, 'real_amdar_t1_rows': 45818, 'real_amdar_t2_rows': 210537, 'real_amdar_t1_coverage_pct': 10.630429133565967, 'real_amdar_t2_coverage_pct': 48.847585195634416, 'real_amdar_t1_t2_coverage_pct': 59.47801432920039, 'validation_policy_pool_rows': 14630, 'validation_t1_cases': 11425, 'validation_t2_cases': 3135, 'validation_t1_case_time_error_q90_seconds_q90': 5.894042, 'validation_t2_case_time_error_q90_seconds_q90': 5.087406, 'validation_t1_wrong_leg_rate': 0.006652078774617068, 'validation_t2_wrong_leg_rate': 0.0, 'passes_t1_q90_lt_180s': True, 'passes_t2_q90_lt_600s': True, 'passes_t1_wrong_leg_le_1pct': True, 'passes_t2_wrong_leg_le_2pct': True}`
- Locked-test handling: `validation split only for threshold quality checks; locked_test is report-only.`
- High-wind branch sensitivity: `[{'branch_name': 'A0_teacher_filter_all_gt150_rejected', 'tier_counts': {'T2': 209377, 'T3': 121500, 'T4': 54319, 'T1': 45818, 'T0': 175}, 'amdar_tier_counts': {'T2': 209377, 'T3': 121500, 'T4': 54313, 'T1': 45818}, 'amdar_t1_t2_coverage_pct': 59.208877793451634, 'high_wind_action_counts': {'reject_gt150_teacher_filter': 4505}, 'high_wind_retained_rows_T1_T3': 0, 'high_wind_retained_pct_of_gt150': 0.0, 'gt200_retained_rows_T1_T3': 0, 'strict_truth_invariant_check': {'amdar_t0_rows': 0, 'amdar_strict_holdout_rows': 0, 'turb_t0_rows': 175}, 'stage4_reconstruction_smoke': {'status': 'not_run_in_confidence_only_next_window_audit', 'reason': 'This audit does not run full large-framework Stage4 windfield reconstruction; branch must still be validated on strict TURB holdout before claiming reconstruction benefit.'}}, {'branch_name': 'A1_current_v3_rescue', 'tier_counts': {'T2': 210537, 'T3': 123358, 'T4': 51301, 'T1': 45818, 'T0': 175}, 'amdar_tier_counts': {'T2': 210537, 'T3': 123358, 'T4': 51295, 'T1': 45818}, 'amdar_t1_t2_coverage_pct': 59.47801432920039, 'high_wind_action_counts': {'retain_150_200_review_low_confidence': 1712, 'retain_gt200_high_altitude_batch_supported': 1626, 'reject_gt150_unsupported': 1167}, 'high_wind_retained_rows_T1_T3': 3018, 'high_wind_retained_pct_of_gt150': 66.99223085460599, 'gt200_retained_rows_T1_T3': 1511, 'strict_truth_invariant_check': {'amdar_t0_rows': 0, 'amdar_strict_holdout_rows': 0, 'turb_t0_rows': 175}, 'stage4_reconstruction_smoke': {'status': 'not_run_in_confidence_only_next_window_audit', 'reason': 'This audit does not run full large-framework Stage4 windfield reconstruction; branch must still be validated on strict TURB holdout before claiming reconstruction benefit.'}}, {'branch_name': 'A2_moderate_rescue_gt200_stricter', 'tier_counts': {'T2': 210537, 'T3': 122089, 'T4': 52570, 'T1': 45818, 'T0': 175}, 'amdar_tier_counts': {'T2': 210537, 'T3': 122089, 'T4': 52564, 'T1': 45818}, 'amdar_t1_t2_coverage_pct': 59.47801432920039, 'high_wind_action_counts': {'reject_gt150_moderate_policy': 2551, 'retain_150_200_review_low_confidence': 1712, 'retain_gt200_strict_high_altitude_small_batch': 242}, 'high_wind_retained_rows_T1_T3': 1749, 'high_wind_retained_pct_of_gt150': 38.82352941176471, 'gt200_retained_rows_T1_T3': 242, 'strict_truth_invariant_check': {'amdar_t0_rows': 0, 'amdar_strict_holdout_rows': 0, 'turb_t0_rows': 175}, 'stage4_reconstruction_smoke': {'status': 'not_run_in_confidence_only_next_window_audit', 'reason': 'This audit does not run full large-framework Stage4 windfield reconstruction; branch must still be validated on strict TURB holdout before claiming reconstruction benefit.'}}]`

## Interpretation

Stage4 confidence v3 next-window optimization `passes` the confidence quality gate for entering optimization plan phase 4. The result meets the requested T1/T2 coverage and high-wind-retention checks while preserving the strict-truth boundary: AMDAR has zero strict-truth rows and zero holdout-eligible rows.

The high-wind rule is intentionally explicit because it departs from the older Stage1 teacher-filter v4 branch. It should be treated as the optimization-plan confidence branch and validated in later strict TURB holdout reconstruction experiments, not as proof that high-wind AMDAR is strict truth.

The new T2a/T2b split and continuous time uncertainty reduce downstream risk without changing the truth boundary. Stage2 v7 identity-date information remains diagnostic only and is not part of `base_support_conf` or `adsb_match_quality_conf`.

## Next Steps

1. Enter optimization plan phase 4: large-framework Stage5 real AMDAR-ADS-B matching v4.
2. Consume `stage4_confidence_v3/amdar_confidence_components_v3.parquet`; use `base_support_conf`, `confidence_tier`, `confidence_subtier`, `time_uncertainty_s_stage4_v3`, `time_uncertainty_s_stage4_v3_continuous`, and high-wind action fields.
3. Keep Stage5 accepted rows support-only and write match grade/ambiguity diagnostics before Stage6 time modeling.
4. In later full Stage4 reconstruction validation, compare A0 teacher-filter, A1 current rescue, and A2 moderate rescue on strict TURB holdout before claiming reconstruction benefit.
