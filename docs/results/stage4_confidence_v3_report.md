# Stage4 Confidence v3 Results

Generated at UTC: 2026-07-08T03:20:51.742220+00:00

## Scope

This is optimization-plan phase 3: large-framework Stage4 confidence v3. It refreshes confidence tiers only; it does not run real Stage5 matching or full windfield reconstruction.

## Key Results

- Total rows scored: `431189`
- AMDAR rows scored: `431008`
- TURB rows scored: `181`
- Core components: `['source_quality_conf', 'met_physics_conf', 'batch_representativeness_conf', 'identity_completeness_conf']`
- Tier counts: `{'T2': 210537, 'T3': 123358, 'T4': 51301, 'T1': 45818, 'T0': 175}`
- AMDAR tier coverage pct: `{'T2': 48.847585195634416, 'T3': 28.6208144628406, 'T4': 11.901171207959017, 'T1': 10.630429133565967}`
- AMDAR T1+T2 coverage pct: `59.47801432920039`
- High-wind retained rows: `3018` / `4505`
- TURB enhanced holdout eligible rows: `175`
- TURB enhanced holdout review rows: `6`
- T2 subtier detail: `{'T2_total': 210537, 'T2a_direct_support_candidate': 117916, 'T2b_broad_or_lower_weight_support': 92621, 'T2a_pct_of_T2': 56.00725763167519, 'T2b_pct_of_T2': 43.992742368324805}`
- Continuous time uncertainty summary: `{'present': True, 'rows': 431008, 'null_rows': 0, 'finite_rows': 431008, 'min': 180.0, 'p10': 300.0, 'q50': 900.0, 'p90': 1500.0, 'p99': 2100.0, 'max': 2100.0}`

## Completion Checks

- Checks: `{'component_count_is_4_core_plus_stage5_conditional': True, 'removed_redundant_v2_components': True, 'stage3_v8_quality_gate_passed': True, 'strict_truth_not_derived_from_confidence': True, 'amdar_effective_strict_truth_rows': 0, 'amdar_effective_strict_truth_v3_rows': 0, 'amdar_t0_rows': 0, 'amdar_holdout_eligible_rows': 0, 'turb_enhanced_holdout_eligible_is_175': True, 'turb_review_rows_is_6': True, 'stage5_match_not_fabricated': True, 'stage2_v7_identity_prior_diagnostic_present': True, 't1_coverage_pct_ge_10': True, 't2_coverage_pct_ge_42': True, 't1_t2_coverage_pct_ge_55': True, 'high_wind_retained_rows_ge_2800': True, 'unsupported_high_wind_rejected': True, 'space_saving_single_compact_table': True, 'passed_stage4_confidence_v3_quality_gate': True, 'confidence_subtier_present': True, 't2_subtier_covers_all_t2_rows': True, 'time_uncertainty_continuous_present': True, 'continuous_time_uncertainty_not_above_step_uncertainty': True, 'identity_risk_diagnostic_present': True, 'identity_risk_diagnostic_not_used_as_adsb_match': True, 'stage2_v7_identity_prior_not_used_in_base_support_conf': True, 'validation_only_threshold_grid_written': True, 'selected_t1_validation_q90_lt_3min': True, 'selected_t2_validation_q90_lt_10min': True, 'selected_t1_validation_wrong_leg_le_1pct': True, 'selected_t2_validation_wrong_leg_le_2pct': True, 'locked_test_not_used_for_threshold_selection': True, 'branch_a1_current_high_wind_retained_ge_2800': True, 'branch_a2_moderate_available_for_downstream_ablation': True, 'all_branches_keep_amdar_t0_zero': True, 'all_branches_keep_amdar_holdout_zero': True, 'passed_stage4_next_window_quality_gate': True}`

## Next-Window Safeguards

- `confidence_subtier` splits broad T2 rows into T2a/T2b so downstream stages can avoid treating all T2 rows equally.
- `time_uncertainty_s_stage4_v3_continuous` is a conservative Stage6 diagnostic; tiering still uses the discrete Stage4 uncertainty.
- `identity_risk_conf_diagnostic` is diagnostic only and does not enter `base_support_conf`.
- Validation-only threshold grid and high-wind branch sensitivity are written as separate audit files.

Interpretation: Stage4 confidence v3 passes the pre-Stage5 confidence quality gate. AMDAR remains support-only; Stage2 v7 identity-date priors are diagnostic only; Stage5 accepted rows are not fabricated.
