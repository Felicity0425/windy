# 给下一个智能体的交接话术：Stage4 confidence v3 next-window 后续进入优化计划阶段4

你接手的是 `/data/LFT-W02_data/pengxu` 下的 centralized_v1 三维水平风场重构项目。本轮已经完成优化计划阶段3 next-window：大框架 Stage4 confidence v3 风险控制优化。注意：这里的“阶段3/阶段4”是优化计划小阶段；大框架仍是 Stage1 清洗、Stage2 组织/QC、Stage3 pseudo 验证、Stage4 confidence/重构、Stage5 real matching。

## 必读文档与用途

1. `/data/LFT-W02_data/pengxu/workflow/centralized_v1_docs/new_window_project_handover_20260529/centralized_v1_ultimate_summary_20260626.md`
   - 项目总边界：strict aircraft holdout 是唯一正式验证，AMDAR 不能进入 strict truth。
2. `/data/LFT-W02_data/pengxu/优化/teacher_reports/plan4.md`
   - AMDAR 时间是批次下发/接收时间，不是逐点观测时间。
3. `/data/LFT-W02_data/pengxu/优化/teacher_reports/amdar_plan4_comprehensive_assessment_20260701.md`
   - strict truth 候选少是数据现实；路线是分层置信度和 support-only 使用。
4. `/data/LFT-W02_data/pengxu/优化/teacher_reports/amdar_unified_implementation_plan_20260701.md`
   - Unified Plan 小阶段边界、禁止操作、T0-T4 分层定义。
5. `/data/LFT-W02_data/pengxu/优化/数据处理/amdar_stage2_to_6_optimization_plan_20260706.md`
   - 本轮 Stage2-6 优化总方案；下一步是优化计划阶段4（大框架 Stage5 real matching v4）。
6. `/data/LFT-W02_data/pengxu/优化/数据处理/amdar_optimization_targets_quality_controlled_20260706.md`
   - 平衡目标和质量门，尤其是 T1/T2 覆盖和质量可控原则。
7. `/data/LFT-W02_data/pengxu/优化/数据处理/stage2_adsb_qc_v7_optimized_20260706/stage2_v7_results_analysis_and_next_steps.md`
   - Stage2 v7 已完成；A/S0 达到目标，Stage5 应继续使用 v7 source tiers。
8. `/data/LFT-W02_data/pengxu/优化/数据处理/stage3_pseudo_amdar_v8_optimized_20260707/stage3_v8_results_analysis_and_next_steps.md`
   - Stage3 v8 已通过 validation-only gate 和 locked_test 报告。
9. `/data/LFT-W02_data/pengxu/优化/数据处理/stage3_pseudo_amdar_v8_optimized_20260707/stage3_pseudo_amdar_v8/pseudo_amdar_v8_calibration_report.json`
   - Stage4 v3 使用的 gate、validation/locked metrics、多尺度验证入口。
10. `/data/LFT-W02_data/pengxu/优化/数据处理/stage4_confidence_v3_next_window_optimized_20260708/stage4_v3_results_analysis_and_next_steps.md`
   - 本轮 Stage4 v3 next-window 结果分析、质量门、下一步建议。
11. `/data/LFT-W02_data/pengxu/优化/数据处理/stage4_confidence_v3_next_window_optimized_20260708/stage4_confidence_v3/confidence_tier_summary_v3.json`
   - machine-readable Stage4 v3 summary，含分层覆盖、高风速保留、不变量检查、next-window safeguards。
12. `/data/LFT-W02_data/pengxu/优化/数据处理/stage4_confidence_v3_next_window_optimized_20260708/stage4_confidence_v3/amdar_confidence_policy_v3.json`
   - v3 置信度组件、权重、分层阈值和高风速 override 规则。
13. `/data/LFT-W02_data/pengxu/优化/数据处理/stage4_confidence_v3_next_window_optimized_20260708/stage4_confidence_v3/stage4_next_window_quality_checks.json`
   - T2a/T2b、连续时间不确定性、validation-only 阈值网格、高风速分支敏感性统一审计。
14. `/data/LFT-W02_data/pengxu/优化/数据处理/stage4_confidence_v3_next_window_optimized_20260708/stage4_confidence_v3/high_wind_branch_sensitivity_summary.json`
   - A0 teacher-filter、A1 current rescue、A2 moderate rescue 的 confidence-only 分支对比。
15. `/data/LFT-W02_data/pengxu/优化/数据处理/stage4_confidence_v3_next_window_optimized_20260708/stage4_confidence_v3/stage4_v3_threshold_grid_summary.json`
   - 只用 Stage3 v8 validation split 的阈值质量审计；locked-test 只报告不调参。

## 本轮脚本与输出

- 脚本：`/data/LFT-W02_data/pengxu/优化/数据处理/amdar_unified_stage4_confidence_v3_next_window_20260708.py`
- 输出目录：`/data/LFT-W02_data/pengxu/优化/数据处理/stage4_confidence_v3_next_window_optimized_20260708`
- Stage4 v3 confidence table：`stage4_confidence_v3/amdar_confidence_components_v3.parquet`
- Stage4 v3 summary：`stage4_confidence_v3/confidence_tier_summary_v3.json`
- Stage4 v3 policy：`stage4_confidence_v3/amdar_confidence_policy_v3.json`
- Component correlation：`stage4_confidence_v3/component_correlation_matrix.json`
- Stage4 v3 report：`stage4_confidence_v3/stage4_confidence_v3_report.md`
- Next-window quality checks：`stage4_confidence_v3/stage4_next_window_quality_checks.json`
- Threshold grid：`stage4_confidence_v3/stage4_v3_threshold_grid_validation_only.parquet`
- High-wind branch sensitivity：`stage4_confidence_v3/high_wind_branch_sensitivity_summary.json`

运行口径：

```bash
POLARS_MAX_THREADS=25 /data/LFT-W02_data/pengxu/.conda/envs/windy310/bin/python \
  /data/LFT-W02_data/pengxu/优化/数据处理/amdar_unified_stage4_confidence_v3_next_window_20260708.py \
  --out-dir /data/LFT-W02_data/pengxu/优化/数据处理/stage4_confidence_v3_next_window_optimized_20260708 --slice-count 25
```

空间口径：读取 Stage2 v7 单份 compact leg table；读取 Stage3 v8 报告；不复制 19M ADS-B 点表，不创建 25 份全量中间数据。

## 本轮关键结果

- Tier counts: `{'T2': 210537, 'T3': 123358, 'T4': 51301, 'T1': 45818, 'T0': 175}`
- AMDAR tier coverage pct: `{'T2': 48.847585195634416, 'T3': 28.6208144628406, 'T4': 11.901171207959017, 'T1': 10.630429133565967}`
- AMDAR T1+T2 coverage pct: `59.47801432920039`
- High-wind retained rows: `3018` / `4505`
- T2 subtier detail: `{'T2_total': 210537, 'T2a_direct_support_candidate': 117916, 'T2b_broad_or_lower_weight_support': 92621, 'T2a_pct_of_T2': 56.00725763167519, 'T2b_pct_of_T2': 43.992742368324805}`
- Next-window quality gate: `True`
- Quality gate: `{'component_count_is_4_core_plus_stage5_conditional': True, 'removed_redundant_v2_components': True, 'stage3_v8_quality_gate_passed': True, 'strict_truth_not_derived_from_confidence': True, 'amdar_effective_strict_truth_rows': 0, 'amdar_effective_strict_truth_v3_rows': 0, 'amdar_t0_rows': 0, 'amdar_holdout_eligible_rows': 0, 'turb_enhanced_holdout_eligible_is_175': True, 'turb_review_rows_is_6': True, 'stage5_match_not_fabricated': True, 'stage2_v7_identity_prior_diagnostic_present': True, 't1_coverage_pct_ge_10': True, 't2_coverage_pct_ge_42': True, 't1_t2_coverage_pct_ge_55': True, 'high_wind_retained_rows_ge_2800': True, 'unsupported_high_wind_rejected': True, 'space_saving_single_compact_table': True, 'passed_stage4_confidence_v3_quality_gate': True, 'confidence_subtier_present': True, 't2_subtier_covers_all_t2_rows': True, 'time_uncertainty_continuous_present': True, 'continuous_time_uncertainty_not_above_step_uncertainty': True, 'identity_risk_diagnostic_present': True, 'identity_risk_diagnostic_not_used_as_adsb_match': True, 'stage2_v7_identity_prior_not_used_in_base_support_conf': True, 'validation_only_threshold_grid_written': True, 'selected_t1_validation_q90_lt_3min': True, 'selected_t2_validation_q90_lt_10min': True, 'selected_t1_validation_wrong_leg_le_1pct': True, 'selected_t2_validation_wrong_leg_le_2pct': True, 'locked_test_not_used_for_threshold_selection': True, 'branch_a1_current_high_wind_retained_ge_2800': True, 'branch_a2_moderate_available_for_downstream_ablation': True, 'all_branches_keep_amdar_t0_zero': True, 'all_branches_keep_amdar_holdout_zero': True, 'passed_stage4_next_window_quality_gate': True}`

## 项目与数据理解

TURB/aircraft holdout 是唯一正式 strict truth；AMDAR 431,008 行全部 support-only。AMDAR 原始时间是批次下发/接收时间，不是逐点观测时间。Stage4 v3 的 `confidence_tier` 和 `base_support_conf` 只能控制 support 权重，不能改变 truth/holdout 身份。

Stage2 v7 的 identity-date ADS-B 信息在 Stage4 v3 中只作为诊断风险字段，不进入 `base_support_conf`，也不是 `adsb_match_quality_conf`。真实 AMDAR-ADS-B 匹配仍需在 Stage5 v4 中完成，并且 accepted rows 也仍是 support-only。

新增的 `confidence_subtier` 用于把 T2 拆成 T2a/T2b，防止宽批次 T2 在后续阶段被等权使用。新增的连续时间不确定性只作为 Stage6 输入先验；不能把它解释成逐点时间 truth。

## 下一步执行话术

```text
我已阅读 centralized_v1 总交接、Plan4 时间语义、Plan4 综合评估、Unified Plan、Stage2-6 优化方案、质量控制目标、Stage2 v7、Stage3 v8，以及最新 Stage4 confidence v3 next-window 结果。
当前结论：优化计划阶段3 next-window（大框架 Stage4 confidence v3）已通过质量门；AMDAR 仍为 support-only，Stage5 真匹配未被伪造；新增 T2a/T2b、连续时间不确定性、validation-only 阈值审计和高风速 A0/A1/A2 分支敏感性。
我将进入优化计划阶段4（大框架 Stage5 real AMDAR-ADS-B matching v4），读取 Stage4 v3 confidence table、confidence_subtier、time_uncertainty_s_stage4_v3_continuous 和 Stage2 v7 source tiers，输出候选/拒绝/歧义诊断；不会把 AMDAR 或 Stage5 accepted 当作 strict truth。
```
