# AMDAR Stage2-6 优化计划阶段1-4研究生周报

报告日期：2026-07-10  
报告周期：2026-07-06 至 2026-07-10  
项目路径：`/data/LFT-W02_data/pengxu`  
报告范围：优化计划小阶段1-4，不等同于 centralized_v1 大框架 Stage1-4。

---

## 一、本周工作目标

本周围绕 AMDAR Stage2-6 优化计划开展前四个小阶段工作，目标是在不破坏 strict truth 边界的前提下，提高 ADS-B 候选源质量、扩展 pseudo-AMDAR 验证规模、重构 Stage4 置信度分层，并尝试推进真实 AMDAR-ADS-B 匹配。

需要特别区分两套阶段编号：

- 优化计划阶段1：大框架 Stage2 ADS-B QC/source pool 优化。
- 优化计划阶段2：大框架 Stage3 pseudo-AMDAR 闭环验证。
- 优化计划阶段3：大框架 Stage4 confidence/tier modeling 优化。
- 优化计划阶段4：大框架 Stage5 real AMDAR-ADS-B matching v4。

核心边界保持不变：

- TURB 是当前 strict holdout 的唯一来源。
- AMDAR 全部保持 support-only，不进入 strict truth。
- AMDAR 批次时间不是逐点观测时间。
- Stage5 accepted rows 也只是 support-only，不能进入 holdout。

---

## 二、本周完成的主要工作

### 1. 优化计划阶段1：ADS-B QC/source pool v7

本阶段优化的是大框架 Stage2 的 ADS-B 航段质量与 source pool，不运行风场重构。

主要改进：

- 将 ADS-B leg quality 与 source tier 分离，避免仅凭原始 A/B 数量误判可用源质量。
- 使用加权组件评分和核心速度、采样、几何门控，扩大 S0/S1/S2 source pool。
- 继续复用单份 Stage2 v4 ADS-B 点表，不复制 25 份全量中间数据。

关键结果：

| 指标 | v6/旧基线 | v7结果 | 结论 |
| --- | ---: | ---: | --- |
| A级 leg | 127 | 1,662 | 达到激进目标区间 |
| S0 source pool | 13,432 | 53,850 | 达到 50,000-60,000 目标 |
| S1 source pool | 561 | 81,106 | 明显扩大 |
| S2 source pool | 356,793 | 254,295 | 从宽松短批次转向更有用的源分级 |
| hard speed failure rate | 1.76% | 0.91% | 下降 |
| hard sampling failure rate | 2.75% | 0.28% | 下降 |

质量门结果：`passed_stage2_v7_quality_gate = true`。

阶段结论：Stage2 v7 达到进入 pseudo-AMDAR v8 的要求，并为后续 Stage3/Stage5 提供更大的、可追溯的 ADS-B source pool。

---

### 2. 优化计划阶段2：Pseudo-AMDAR v8 验证

本阶段优化的是大框架 Stage3 pseudo-AMDAR 验证，不是真实 AMDAR-ADS-B 匹配。

主要改进：

- 使用 Stage2 v7 source tiers 生成 pseudo-AMDAR cases。
- 将 pseudo case 数扩展至 50,000。
- 使用 `tail_norm + service_date_utc` 做 split 分组，避免同一 aircraft-day 泄漏。
- 只用 validation split 选择策略，locked-test 仅用于报告。
- 训练 confidence predictor，用于判断闭环误差是否可学习。

关键结果：

| 指标 | 结果 |
| --- | ---: |
| sampled source legs | 19,525 |
| generated cases before balance | 191,795 |
| final pseudo cases | 50,000 |
| row reconstructions | 274,031 |
| validation selected cases | 14,630 / 16,165 |
| validation selected q90 time error | 4.793507 s |
| validation selected wrong-leg rate | 0.519% |
| locked-test selected cases | 14,607 / 16,145 |
| locked-test selected q90 time error | 4.860723 s |
| locked-test selected wrong-leg rate | 0.507% |
| confidence predictor validation log-error R2 | 0.7644 |
| confidence predictor locked-test log-error R2 | 0.7512 |

质量门结果：`passed_stage3_v8_quality_gate = true`。

阶段结论：Stage3 v8 验证规模和质量均满足后续 Stage4 confidence v3 标定要求。需要注意，pseudo-AMDAR 是闭环验证，不是真实 AMDAR 匹配结果。

---

### 3. 优化计划阶段3：Stage4 confidence v3 next-window

本阶段优化的是大框架 Stage4 的 confidence/tier modeling，不是完整风场重构。

主要改进：

- 将 v2 的 9 个冗余置信度组件精简为 4 个核心组件：
  - `source_quality_conf`
  - `met_physics_conf`
  - `batch_representativeness_conf`
  - `identity_completeness_conf`
- 移除或改为诊断字段：
  - `time_source_conf`
  - zero-valued `adsb_match_conf`
  - zero-valued `spatial_match_conf`
  - `density_conf`
- 增加 high-wind support override，并显式记录 action。
- 增加 `confidence_subtier`，将 T2 拆分为 T2a/T2b。
- 增加 `time_uncertainty_s_stage4_v3_continuous`，供 Stage6 使用，但不作为逐点时间 truth。
- 增加 validation-only threshold grid、locked-test report-only 文件和 high-wind A0/A1/A2 分支敏感性分析。

关键结果：

| 指标 | 结果 | 质量门 |
| --- | ---: | --- |
| AMDAR T1 | 45,818 / 10.63% | 通过 |
| AMDAR T2 | 210,537 / 48.85% | 通过 |
| AMDAR T1+T2 | 256,355 / 59.48% | 通过 |
| high-wind retained | 3,018 / 4,505 | 通过 |
| T2a direct support candidate | 117,916 | 新增拆分 |
| T2b broad/lower-weight support | 92,621 | 新增拆分 |
| AMDAR strict truth | 0 | 不变量保持 |
| AMDAR holdout eligible | 0 | 不变量保持 |
| TURB enhanced holdout | 175 | 不变量保持 |

Validation-only 阈值审计：

| 指标 | 结果 |
| --- | ---: |
| selected T1 validation q90 | 5.894042 s |
| selected T2 validation q90 | 5.087406 s |
| selected T1 wrong-leg rate | 0.665% |
| selected T2 wrong-leg rate | 0.000% |

质量门结果：

- `passed_stage4_confidence_v3_quality_gate = true`
- `passed_stage4_next_window_quality_gate = true`

阶段结论：Stage4 confidence v3 next-window 已满足进入真实匹配阶段的要求。高风速 rescue 分支仍需在后续完整风场重构中用 strict TURB holdout 做 A0/A1/A2 对比，不能仅凭 confidence 覆盖率判断其对 RMSE 有收益。

---

### 4. 优化计划阶段4：Stage5 real AMDAR-ADS-B matching v4

本阶段推进大框架 Stage5 的真实 AMDAR-ADS-B matching。该阶段不是 Stage6 时间建模。

主要改进：

- 使用 Stage4 confidence v3 next-window 输出，而不是旧的 Stage4 v2。
- 使用 Stage2 v7 source tiers，而不是 Stage2 v6 source tiers。
- 使用 A/B/C 分层接受策略，并受 Stage3 v8 validation-selected diagnostic gate 约束。
- 将 `confidence_subtier`、连续时间不确定性、高风速 action 和 v7 source tier 带入 accepted rows。
- 保持 accepted rows 为 support-only；rejected rows 不提升、不伪造。

关键结果：

| 指标 | 结果 |
| --- | ---: |
| AMDAR batches | 56,521 |
| candidate leg pool | 389,251 |
| candidate rows | 45,391 |
| batches with candidates | 28,746 |
| accepted batches | 86 |
| accepted rows | 118 |
| accepted fraction of all batches | 0.152% |
| accepted fraction of candidate batches | 0.299% |
| accepted grade A/B/C | A=7, B=41, C=38 |

主要拒绝原因：

| reject reason | count |
| --- | ---: |
| no_candidate_leg | 27,775 |
| best_cost_gt_3 | 21,197 |
| projected_time_after_batch_end_gt_180s | 3,871 |
| monotonic_violation | 1,909 |
| stage4_t4_not_accepted_for_reconstruction | 1,599 |

质量门结果：

- `passed_stage5_v4_diagnostic_gate = true`
- `passed_stage5_v4_target_gate = false`

阶段结论：Stage5 v4 的 accepted rows 是真实、可追溯的 AMDAR-to-ADS-B projections，但数量远低于原目标。当前结果只能作为安全诊断分支，不能称为 Stage5 target-complete。

---

## 三、关键问题与原因分析

### 1. Stage5 v4 未达到目标接受率

Stage5 v4 虽然通过诊断安全门，但未达到目标门。核心原因不是格式或代码输出问题，而是候选几何质量不足。

当前 all-scored `best_cost` p10 为 `24.82`，而 Stage3 v8 validation-selected C-grade 上界为：

```text
cost <= 3
cross_track_q90 <= 1.5 km
```

压力测试显示，如果想达到 500 批次以上接受量，需要放宽到大约：

```text
cost > 20
cross_track > 10 km
```

这会超过 Stage3 v8 验证门，不能称为安全真实匹配。

### 2. 不能通过放宽门限强行达标

在 unsafe relaxation 下，接受批次数可以从 86 增加到 454、756 甚至 2220，但这些接受需要明显越过 validation-selected gate。这样会引入错误几何匹配和潜在 wrong-leg 风险，破坏 support confidence 体系。

因此，本周结论是：Stage5 v4 target miss 是真实数据/对齐问题，不应通过降低标准掩盖。

### 3. AMDAR 时间语义仍是根本约束

AMDAR 原始时间是批次下发/接收时间，不是逐点观测时间。即使 Stage5 accepted rows 具有 ADS-B 投影时间，也只能作为 Stage6 narrow time-distribution seed，不能直接变成 point-time truth。

---

## 四、本周产出文件

### 阶段1产出

- `/data/LFT-W02_data/pengxu/优化/数据处理/stage2_adsb_qc_v7_optimized_20260706/stage2_v7_results_analysis_and_next_steps.md`
- `/data/LFT-W02_data/pengxu/优化/数据处理/stage2_adsb_qc_v7_optimized_20260706/adsb_leg_readiness_summary_v7.json`

### 阶段2产出

- `/data/LFT-W02_data/pengxu/优化/数据处理/stage3_pseudo_amdar_v8_optimized_20260707/stage3_v8_results_analysis_and_next_steps.md`
- `/data/LFT-W02_data/pengxu/优化/数据处理/stage3_pseudo_amdar_v8_optimized_20260707/stage3_pseudo_amdar_v8/pseudo_amdar_v8_calibration_report.json`
- `/data/LFT-W02_data/pengxu/优化/数据处理/stage3_pseudo_amdar_v8_optimized_20260707/stage3_pseudo_amdar_v8/confidence_predictor_report.json`

### 阶段3产出

- `/data/LFT-W02_data/pengxu/优化/数据处理/stage4_confidence_v3_next_window_optimized_20260708/stage4_v3_results_analysis_and_next_steps.md`
- `/data/LFT-W02_data/pengxu/优化/数据处理/stage4_confidence_v3_next_window_optimized_20260708/stage4_confidence_v3/amdar_confidence_components_v3.parquet`
- `/data/LFT-W02_data/pengxu/优化/数据处理/stage4_confidence_v3_next_window_optimized_20260708/stage4_confidence_v3/stage4_next_window_quality_checks.json`

### 阶段4产出

- `/data/LFT-W02_data/pengxu/优化/数据处理/stage5_v4_matching_optimized_20260708/stage5_v4_results_analysis_and_next_steps.md`
- `/data/LFT-W02_data/pengxu/优化/数据处理/stage5_v4_matching_optimized_20260708/stage5_v4/amdar_adsb_match_v4.parquet`
- `/data/LFT-W02_data/pengxu/优化/数据处理/stage5_v4_matching_optimized_20260708/stage5_v4/amdar_adsb_reject_v4.parquet`
- `/data/LFT-W02_data/pengxu/优化/数据处理/stage5_v4_matching_optimized_20260708/stage5_v4/amdar_adsb_match_diagnostics_v4.json`

---

## 五、下周工作计划

### 1. Stage6 时间不确定性建模

可以启动一个保守 Stage6 diagnostic branch：

- 仅将 Stage5 v4 的 118 accepted rows 作为 narrow support-only seeds。
- 对未匹配和 rejected AMDAR 继续保留 batch-interval uncertainty。
- 明确报告 Stage5 v4 target miss，不能把 118 rows 当作目标完成。

### 2. Stage5 候选可用性与数据对齐诊断

若继续追求 Stage5 接受率目标，应优先排查：

- ADS-B/AMDAR flight normalization 是否仍有可修复缺口。
- tail/date/flight 映射是否存在系统性不一致。
- AMDAR batch 与 ADS-B leg 的时间/date 对齐是否存在上游偏移。
- 弱 identity expansion 为什么新增 1,910 candidate rows 但 accepted 为 0。

### 3. 高风速分支后续验证

Stage4 confidence v3 的 high-wind rescue 已通过 confidence gate，但仍需在 full Stage4 reconstruction 中进行：

- A0 teacher-filter all >150 m/s rejected
- A1 current v3 rescue
- A2 moderate rescue

最终判断标准应是 strict TURB holdout 和 tail-risk diagnostics，而不是仅看 T1/T2 覆盖率。

---

## 六、本周总结

本周完成了 AMDAR Stage2-6 优化计划前四个小阶段的主要实施与验证。阶段1、阶段2、阶段3均达到既定质量门，显著扩大了 ADS-B source pool、pseudo-AMDAR 验证规模和 Stage4 confidence 的高质量 support 覆盖。阶段4实现了真实 AMDAR-ADS-B matching v4，并产出 118 条可追溯 accepted rows，但未达到接受率目标。

总体看，本周工作最大进展是建立了从 ADS-B QC、pseudo 验证、Stage4 confidence 到真实匹配的可审计链路；最大问题是真实匹配的几何质量不足，说明后续应优先做数据对齐和候选可用性诊断，而不是通过放宽门限强行提高接受率。
