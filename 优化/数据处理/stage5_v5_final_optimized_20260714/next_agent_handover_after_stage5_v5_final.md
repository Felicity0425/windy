# 给下一个智能体的交接话术：Stage5 最终安全优化完成

你接手的是 `/data/LFT-W02_data/pengxu` 下 centralized_v1 三维水平风场重构项目。必须区分：大框架 Stage5 是真实 AMDAR-ADS-B matching；本次工作对应 Stage2-6 优化计划的小阶段/阶段4；下一小阶段才是大框架 Stage6 时间不确定性建模。

## 当前冻结结论

最终 Stage5 输出位于：

`/data/LFT-W02_data/pengxu/优化/数据处理/stage5_v5_final_optimized_20260714`

关键结果：

- accepted batches：`198`；
- accepted rows：`251`；
- accepted fraction：`0.3503%`；
- grades：`A=7, B=41, C=150`；
- v4 strong exact：`86`；
- Stage3 v9 validated 5-9 point micro：`100`；
- Stage3 v10 validated 2-4 point tiny：`12`；
- safety gate：`true`；
- target gate：`false`；
- AMDAR strict truth：`0`；
- AMDAR holdout：`0`。

原 v5 的问题已修复：它只给 `no_candidate_leg` 批次补 micro leg，遗漏了 `26737` 个已有差候选的 rejected 批次。最终版本把已验证扩展作用于全部 `56435` 个 v4 rejected batches，并新增独立 pseudo 验证通过的 tiny-leg 分支。旧 v4、原 v5 和全-scope micro 版本的 accepted batches 全部保留。

## 必读文档及用途

1. `/data/LFT-W02_data/pengxu/优化/数据处理/next_agent_handover_optimization_20260706.md`
   - 项目边界、Stage2-6 优化路线、大框架与小阶段映射。
2. `/data/LFT-W02_data/pengxu/优化/数据处理/amdar_stage2_to_6_optimization_plan_20260706.md`
   - 总优化目标；注意激进数量目标必须服从验证和真值边界。
3. `/data/LFT-W02_data/pengxu/优化/数据处理/stage4_confidence_v3_next_window_optimized_20260708/next_agent_handover_after_stage4_v3.md`
   - Stage4 v3 gate、T2a/T2b、时间不确定性先验和 support-only 边界。
4. `/data/LFT-W02_data/pengxu/优化/数据处理/stage5_v5_matching_optimized_20260713/stage5_v5_optimization_plan_summary.md`
   - 原方案及 2026-07-14 最终作用域修订。
5. `/data/LFT-W02_data/pengxu/优化/数据处理/stage3_pseudo_amdar_v9_micro_leg_optimized_20260713/stage3_pseudo_amdar_v9_micro/pseudo_amdar_v9_micro_validation_report.json`
   - 5-9 点 micro validation-selected gate 和 locked-test 报告。
6. `/data/LFT-W02_data/pengxu/优化/数据处理/stage3_pseudo_amdar_v10_tiny_leg_optimized_20260714_validated/stage3_pseudo_amdar_v9_micro/pseudo_amdar_v9_micro_validation_report.json`
   - 2-4 点 tiny 独立 validation/locked-test gate。
7. `/data/LFT-W02_data/pengxu/优化/数据处理/stage5_v5_final_optimized_20260714/stage5_v5_optimization_plan_summary_revised_20260714.md`
   - 最终候选策略、修订原因、运行与验收口径。
8. `/data/LFT-W02_data/pengxu/优化/数据处理/stage5_v5_final_optimized_20260714/stage5_v5_results_analysis_and_next_steps.md`
   - 最终结果、质量分析、数量目标未达原因和下一步。
9. `/data/LFT-W02_data/pengxu/优化/数据处理/stage5_v5_final_optimized_20260714/stage5_v5/amdar_adsb_match_diagnostics_v5.json`
   - machine-readable candidate/result/safety/target checks。
10. `/data/LFT-W02_data/pengxu/优化/数据处理/stage5_v5_final_optimized_20260714/stage5_v5_stage6_gate_check.json`
    - Stage6 允许模式和强制约束。

## 必须理解的数据边界

AMDAR 时间是批次下发/接收语义，不是逐点观测时间。Stage5 accepted 只提供可追溯的 ADS-B 投影时间种子，仍然是 support-only。不得把 confidence、match grade 或 estimated time 推导为 strict truth；不得把 rejected rows 晋升为 accepted；不得修改 `effective_strict_truth=false` 和 `holdout_eligible=false`。

Stage3 pseudo validation 是 ADS-B 闭环验证，不是真实 AMDAR truth。locked-test 只报告，不参与阈值选择。

## Stage6 入口约束

只允许运行优化计划下一小阶段的大框架 Stage6 conservative diagnostic：

- 读取 `stage5_v5/amdar_adsb_match_v5.parquet`；
- 仅对 251 accepted rows 生成窄 support-only 时间分布；
- 其他 AMDAR 使用批次/物理不确定性；
- 明确写出 Stage5 target gate=false；
- 禁止声称 Stage5 已达到 1% 或运行 target-complete Stage6。

## 推荐继续话术

```text
我已阅读 Stage2-6 总交接与优化计划、Stage4 v3、Stage3 v9 micro validation、Stage3 v10 tiny validation，以及 Stage5 最终修订方案和结果。
我理解大框架 Stage5 对应优化计划阶段4，最终冻结结果为198 accepted batches / 251 rows，safety gate=true、target gate=false；AMDAR仍全部support-only，strict truth和holdout均为0。
我不会通过放宽cost/cross-track、取消monotonic/batch-end、接纳T4或未验证date-shift来伪造达标。下一步只运行大框架Stage6 conservative diagnostic，仅把251条accepted rows作为窄时间分布种子，并明确报告Stage5数量目标未达。
```
