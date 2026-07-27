# 给下一个智能体的交接话术：Stage5 SOTA 跨阶段优化实施

你接手的是 centralized_v1 三维水平风场重构项目。注意区分大框架 Stage1-5 与 Stage2-6 优化计划中的小阶段。本轮目标不是放宽 Stage5 阈值，而是修复 Stage3 pseudo-real 分布错位，并用概率序列匹配替换独立最近线段 mean-cost。

## 必读文件

1. `/data/LFT-W02_data/pengxu/优化/数据处理/stage5_sota_cross_stage_optimization_plan_20260715/stage5_sota_cross_stage_optimization_plan_20260715.md`
   - 完整 SOTA 方案、跨阶段关系、实验矩阵和门槛。
2. `/data/LFT-W02_data/pengxu/优化/数据处理/stage5_sota_cross_stage_optimization_plan_20260715/local_stage5_optimization_audit_summary.json`
   - 所有本地只读审计结果；说明哪些简单路线已经证伪。
3. `/data/LFT-W02_data/pengxu/优化/数据处理/stage5_v5_final_optimized_20260714/stage5_v5_results_analysis_and_next_steps.md`
   - 当前冻结基线 198/251。
4. `/data/LFT-W02_data/pengxu/优化/数据处理/stage3_pseudo_amdar_v8_optimized_20260707/stage3_pseudo_amdar_v8/pseudo_amdar_v8_calibration_report.json`
   - 当前 Stage3 v8 validation/locked-test。
5. `/data/LFT-W02_data/pengxu/优化/数据处理/stage3_pseudo_amdar_v9_micro_leg_optimized_20260713/stage3_pseudo_amdar_v9_micro/pseudo_amdar_v9_micro_validation_report.json`
   - 当前 micro pseudo gate；注意它与真实 Stage5 难度差异巨大。
6. `/data/LFT-W02_data/pengxu/优化/数据处理/amdar_unified_stage5_v4_matching_20260708.py`
   - 当前 candidate retrieval、nearest-segment、mean-cost、monotonic 和 acceptance 实现。

## 当前结论

- 基线：198 batches / 251 rows，safety=true，target=false；
- 24h 窗口、reverse order、excluded long legs、简单 bridge、tail/date fallback 均没有实质新增；
- partial 70% coverage 现有上限仅约 5 批；
- 候选数量不是主问题；48615 个 geometry failure 是主问题；
- Stage3 synthetic cases 过于容易，不能继续直接为真实 Stage5 调阈值。

## 实施顺序

1. 新建 Stage3 v11 hard-negative/domain-matched case generator；
2. 加入 identity/date corruption、错误航班、缺段、乱序、时间戳偏差；
3. validation 选择规则，locked-test 只报告；
4. 实现 Stage5 v6 HMM/Viterbi sequence scorer；
5. 输出 candidate posterior、entropy、margin、unique/mixture role；
6. 与当前 mean-cost 做逐批次对照；
7. 只有新增 >=10 且 wrong-leg<=1% 才允许合并。

## 强制规则

- AMDAR 永远 support-only；
- 不得把 posterior、confidence 或 accepted 推导成 strict truth；
- 不得把 mixture 计入 unique accepted；
- 不得在 locked-test 上调参；
- 不得继续通过 cost/cross-track/time-window 放宽制造表面提升；
- 继续使用 25-slice / POLARS_MAX_THREADS=25，复用单份 ADS-B 点表。

## 推荐开场话术

```text
我已阅读 Stage5 SOTA 跨阶段优化方案、本地审计摘要、Stage5 198/251 基线以及 Stage3 v8/v9 报告。我理解当前瓶颈不是候选数量，而是 pseudo-real domain gap 和独立最近线段模型。下一步先实现 Stage3 v11 hard-negative/domain-matched validation，再实现 Stage5 v6 HMM/Viterbi sequence scorer；不会放宽真值、几何或 locked-test 边界。
```
