# 给下一个智能体的交接话术：Stage3 v12 与 Stage5 v7 已完成

你接手的是 `/data/LFT-W02_data/pengxu` 下 centralized_v1 三维水平风场重构项目。当前日期为 2026-07-16。请先明确：本次完成的是**大框架 Stage3 和 Stage5**，不是 `amdar_stage2_to_6_optimization_plan_20260706.md` 内部的小阶段3/5。

## 一、当前状态

- 大框架 Stage3 v12 raw-sequence Drop-DTW validation 已完成并通过全部 locked-test 质量门。
- 大框架 Stage5 v7 calibrated partial matcher 已完成并通过 safety gate 与 merge target。
- Stage5 最终结果：`229 unique batches / 345 matched rows`。
- 相对冻结 Stage5 v5：`198/251 -> 229/345`，unique batches `+31`，matched rows `+94`。
- Stage6 gate：`target_branch`。
- 旧 `1% / 566 batches` 目标仍未达到；当前约 `0.405%`，不得宣称覆盖问题已完全解决。

## 二、必须按顺序阅读

1. `/data/LFT-W02_data/pengxu/优化/数据处理/next_agent_handover_optimization_20260706.md`
   - 理解大框架 Stage1-5 与优化 plan 小阶段编号的区别，以及 truth/holdout 不变量。
2. `/data/LFT-W02_data/pengxu/优化/数据处理/amdar_stage2_to_6_optimization_plan_20260706.md`
   - 理解原始目标、质量门和回退原则；注意部分旧数量目标已被后续证据修正。
3. `/data/LFT-W02_data/pengxu/优化/数据处理/stage5_v6_hmm_viterbi_optimized_20260715/stage5_v6_results_analysis_and_next_steps.md`
   - 理解 v6 为什么安全但只新增 7、为什么不能继续放宽旧门。
4. `/data/LFT-W02_data/pengxu/优化/数据处理/stage5_v6_hmm_viterbi_optimized_20260715/stage5_v6_research_based_breakthrough_plan_20260716.md`
   - 本轮 Stage3 v12 / Stage5 v7 的直接设计依据。
5. `/data/LFT-W02_data/pengxu/优化/数据处理/stage3_pseudo_amdar_v12_drop_dtw_optimized_20260716/stage3_v12_results_analysis_and_next_steps.md`
   - 查看 v12 case bank、hard negatives、冻结策略和 locked-test 结果。
6. `/data/LFT-W02_data/pengxu/优化/数据处理/stage5_v7_calibrated_partial_optimized_20260716/stage5_v7_results_analysis_and_next_steps.md`
   - 查看 29 批审计、24 批新增、5 个 bridge 继续 rejected 的原因。
7. `/data/LFT-W02_data/pengxu/优化/数据处理/stage3_stage5_optimization_results_and_next_steps_20260716.md`
   - 查看联合结论和 Stage6 强制规则。
8. `/data/LFT-W02_data/pengxu/workflow/centralized_v1_docs/new_window_project_handover_20260529/centralized_v1_ultimate_summary_20260626.md`
   - 项目正式验证、strict aircraft holdout 和防泄漏总边界。
9. `/data/LFT-W02_data/pengxu/优化/teacher_reports/plan4.md`
   - AMDAR 时间是批次下发/接收时间，不是逐点观测时间。
10. `/data/LFT-W02_data/pengxu/优化/teacher_reports/amdar_plan4_comprehensive_assessment_20260701.md`
    - T0-T4 support-only 分层利用原则。

## 三、关键代码

- Stage3 v12：`/data/LFT-W02_data/pengxu/优化/数据处理/amdar_unified_stage3_v12_drop_dtw_20260716.py`
- Stage5 v7：`/data/LFT-W02_data/pengxu/优化/数据处理/amdar_unified_stage5_v7_calibrated_partial_20260716.py`

两个脚本均已使用 `POLARS_MAX_THREADS=25`、`slice_count=25`、单份共享压缩输出验证。不要生成 25 份全量中间数据。

## 四、机器可读结果

- Stage3 report：`/data/LFT-W02_data/pengxu/优化/数据处理/stage3_pseudo_amdar_v12_drop_dtw_optimized_20260716/stage3_pseudo_amdar_v12/stage3_v12_calibration_report.json`
- Stage3 posterior model：`/data/LFT-W02_data/pengxu/优化/数据处理/stage3_pseudo_amdar_v12_drop_dtw_optimized_20260716/stage3_pseudo_amdar_v12/association_posterior_model_v12.json`
- Stage3 raw case bank：`/data/LFT-W02_data/pengxu/优化/数据处理/stage3_pseudo_amdar_v12_drop_dtw_optimized_20260716/stage3_pseudo_amdar_v12/raw_sequence_case_bank_v12.parquet`
- Stage3 row truth：`/data/LFT-W02_data/pengxu/优化/数据处理/stage3_pseudo_amdar_v12_drop_dtw_optimized_20260716/stage3_pseudo_amdar_v12/raw_sequence_rows_with_truth_v12.parquet`
- Stage5 diagnostics：`/data/LFT-W02_data/pengxu/优化/数据处理/stage5_v7_calibrated_partial_optimized_20260716/stage5_v7/amdar_adsb_match_diagnostics_v7.json`
- Stage5 final match：`/data/LFT-W02_data/pengxu/优化/数据处理/stage5_v7_calibrated_partial_optimized_20260716/stage5_v7/amdar_adsb_match_v7.parquet`
- Stage5 dropped rows：`/data/LFT-W02_data/pengxu/优化/数据处理/stage5_v7_calibrated_partial_optimized_20260716/stage5_v7/amdar_adsb_partial_row_diagnostics_v7.parquet`
- Stage6 gate：`/data/LFT-W02_data/pengxu/优化/数据处理/stage5_v7_calibrated_partial_optimized_20260716/stage5_v7_stage6_gate_check.json`

## 五、对数据与结果的固定理解

- AMDAR 没有 strict point truth；accepted 也只是 support-only。
- Stage3 v12 的 pseudo truth 来自 ADS-B source legs，只用于验证 association/drop policy。
- `20` 个 v6 mixtures 和 `4` 个 near-pass 在 v12 规则下转为 unique support；5 个 stitched cases仍 rejected。
- 24 个新增中有 13 个批次仅保留 2 行中的 1 行；另一行是 excluded diagnostic，不能进入 Stage6 narrow seed。
- Stage3 locked wrong/hard-negative `0.0136%`、ECE `0.000361`；同身份错误 tracklet false acceptance `0.0423%`。
- Stage5 truth/holdout/time-point-truth 违规为 0，prior overlap 和重复行均为 0。

## 六、下一任务：Stage6

1. 读取 `amdar_adsb_match_v7.parquet` 作为 narrow support-only seeds。
2. 同时读取 dropped-row diagnostics；明确阻止 excluded rows 被缩窄。
3. 对 13 个 singleton matched-row batches 做 on/off sensitivity。
4. unmatched AMDAR 保持宽分布，estimated time 不作为 truth。
5. 正式评价只使用 strict aircraft holdout。
6. 若 Stage6/最终 holdout 未改善，先回退 singleton seeds，再检查时间不确定性传播；不要回到 Stage5 放宽阈值。
7. 若仍要求达到 `>=1%` batch coverage，转 Stage2 v8 track graph 或新增 ADS-B/ADS-C 覆盖，不要伪造 unique。

## 七、禁止操作

- 不得把 AMDAR、posterior、accepted、estimated time 改成 strict truth。
- 不得把 dropped rows 回填进 match 产品。
- 不得接受 5 个 stitched cases，除非新建 bridge-specific Stage3 validation 并通过 locked-test。
- 不得在 locked-test 上重新选择 drop penalty、coverage 或 posterior threshold。
- 不得复制 25 份全量中间数据。

