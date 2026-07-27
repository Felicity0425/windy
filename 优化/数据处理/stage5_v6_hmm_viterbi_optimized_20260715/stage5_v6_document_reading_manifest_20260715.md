# Stage5 v6 文档阅读与依赖清单

生成日期：2026-07-15

## 项目边界与阶段定义

- `/data/LFT-W02_data/pengxu/优化/数据处理/next_agent_handover_optimization_20260706.md`：大框架 Stage1-5 与旧优化计划小阶段的区分、truth/holdout 不变量。
- `/data/LFT-W02_data/pengxu/优化/数据处理/amdar_stage2_to_6_optimization_plan_20260706.md`：旧小阶段1-7优化路线、质量门和回退原则。
- `/data/LFT-W02_data/pengxu/workflow/centralized_v1_docs/new_window_project_handover_20260529/centralized_v1_ultimate_summary_20260626.md`：项目总边界、strict aircraft holdout 和防泄漏要求。
- `/data/LFT-W02_data/pengxu/优化/teacher_reports/plan4.md`：AMDAR 时间是批次下发/接收时间，不是逐点观测时间。
- `/data/LFT-W02_data/pengxu/优化/teacher_reports/amdar_plan4_comprehensive_assessment_20260701.md`：T0-T4 support-only 数据利用原则。
- `/data/LFT-W02_data/pengxu/优化/teacher_reports/amdar_unified_implementation_plan_20260701.md`：P0-P15、禁止操作和阶段依赖。

## 直接上游与本轮方案

- `/data/LFT-W02_data/pengxu/优化/数据处理/stage3_pseudo_amdar_v11_domain_matched_optimized_20260715_validated/stage3_v11_document_reading_manifest_20260715.md`：Stage3 v11 已读文档和固定理解。
- `/data/LFT-W02_data/pengxu/优化/数据处理/stage3_pseudo_amdar_v11_domain_matched_optimized_20260715_validated/stage3_v11_results_analysis_and_next_steps.md`：Stage3 v11 质量门和下一步。
- `/data/LFT-W02_data/pengxu/优化/数据处理/stage3_pseudo_amdar_v11_domain_matched_optimized_20260715_validated/next_agent_handover_after_stage3_v11_20260715.md`：本轮直接交接。
- `/data/LFT-W02_data/pengxu/优化/数据处理/stage5_sota_cross_stage_optimization_plan_20260715/stage5_sota_cross_stage_optimization_plan_20260715.md`：HMM/Viterbi、partial alignment、track graph 和正式验收门。
- `/data/LFT-W02_data/pengxu/优化/数据处理/stage5_sota_cross_stage_optimization_plan_20260715/local_stage5_optimization_audit_summary.json`：已证伪的时间窗、reverse、long-leg、bridge 和 fallback 路线。
- `/data/LFT-W02_data/pengxu/优化/数据处理/stage5_v5_final_optimized_20260714/stage5_v5_results_analysis_and_next_steps.md`：冻结 `198/251` 基线。
- `/data/LFT-W02_data/pengxu/优化/数据处理/amdar_unified_stage5_v4_matching_20260708.py`：candidate policy、nearest-segment、mean-cost 和 layered gate。
- `/data/LFT-W02_data/pengxu/优化/数据处理/amdar_unified_stage5_v5_matching_20260713.py`：micro/tiny expansion validation 逻辑。
- `/data/LFT-W02_data/pengxu/优化/数据处理/amdar_unified_stage3_v11_domain_matched_20260715.py`：冻结 posterior 模型、physical gate 和 locked-test 口径。

## 本轮交付物

- `/data/LFT-W02_data/pengxu/优化/数据处理/amdar_unified_stage5_v6_hmm_viterbi_20260715.py`：正式可复现脚本。
- `/data/LFT-W02_data/pengxu/优化/数据处理/stage5_v6_hmm_viterbi_optimized_20260715/stage5_v6_results_analysis_and_next_steps.md`：结果分析和下一步。
- `/data/LFT-W02_data/pengxu/优化/数据处理/stage5_v6_hmm_viterbi_optimized_20260715/stage5_v6_stage6_gate_check.json`：Stage6 机器可读门控。
- `/data/LFT-W02_data/pengxu/优化/数据处理/stage5_v6_hmm_viterbi_optimized_20260715/next_agent_handover_after_stage5_v6_20260715.md`：后续交接话术。
- `stage5_v6/amdar_adsb_match_diagnostics_v6.json`：完整机器可读结果。
- `stage5_v6/amdar_adsb_match_v6.parquet`：最终 unique match 产品。
- `stage5_v6/amdar_adsb_partial_row_diagnostics_v6.parquet`：partial 行级解释。

## 固化理解

大框架 Stage3 已完成，旧优化计划“小阶段3”对应大框架 Stage4 confidence。本轮是大框架 Stage5。安全门通过不等于 SOTA 合并目标通过：最终 `205/274` 和 20 mixtures 是安全结果，但新增 unique 只有 7，不能宣称满足 `+10`。Stage6 只能 conservative diagnostic；AMDAR、posterior、accepted 和 estimated time 始终不是 strict point truth。
