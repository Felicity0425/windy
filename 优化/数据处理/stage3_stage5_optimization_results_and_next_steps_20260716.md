# 大框架 Stage3 + Stage5 优化结果与进入 Stage6 建议

生成日期：2026-07-16

## 总结

本轮严格区分了大框架阶段和旧优化 plan 的小阶段编号：执行的是 **大框架 Stage3 v12 pseudo validation** 与 **大框架 Stage5 v7 real AMDAR-ADS-B matching**。两者均使用 `25-slice / POLARS_MAX_THREADS=25` 的省空间口径。

最终结论：

- Stage3 v12 全部 locked-test 质量门通过；
- Stage5 v7 safety gate 与 merge target 均通过；
- Stage5 从冻结 v5 的 `198/251` 提升到 `229/345`；
- 可以进入 Stage6 `target_branch`，但所有 AMDAR 仍是 support-only；
- `1% / 566 batches` 的旧数量目标仍未达到，不能声称覆盖瓶颈已经解决。

## 关键指标

| 指标 | 结果 | 要求 | 结论 |
|---|---:|---:|---|
| Stage3 locked wrong/hard-negative | 0.0136% | <=1% | 通过 |
| Stage3 catastrophic | 0.0602% | <3% | 通过 |
| Stage3 posterior ECE | 0.000361 | <=0.05 | 通过 |
| 最大 corruption false acceptance | 0.1686% | <=2% | 通过 |
| 最大 hard-negative false acceptance | 0.0423% | <=2% | 通过 |
| Stage5 v7 新增 unique | 24 | >=3 | 通过 |
| 相对 v5 总新增 unique | 31 | >=10 | 通过 |
| Stage5 最终 unique | 229 | >=208 | 通过 |
| truth/holdout 违规 | 0 | 0 | 通过 |

## 进入 Stage6 的输入

- unique match：`/data/LFT-W02_data/pengxu/优化/数据处理/stage5_v7_calibrated_partial_optimized_20260716/stage5_v7/amdar_adsb_match_v7.parquet`
- incremental match：`/data/LFT-W02_data/pengxu/优化/数据处理/stage5_v7_calibrated_partial_optimized_20260716/stage5_v7/amdar_adsb_match_incremental_v7.parquet`
- dropped-row diagnostics：`/data/LFT-W02_data/pengxu/优化/数据处理/stage5_v7_calibrated_partial_optimized_20260716/stage5_v7/amdar_adsb_partial_row_diagnostics_v7.parquet`
- Stage6 gate：`/data/LFT-W02_data/pengxu/优化/数据处理/stage5_v7_calibrated_partial_optimized_20260716/stage5_v7_stage6_gate_check.json`
- Stage3 policy/report：`/data/LFT-W02_data/pengxu/优化/数据处理/stage3_pseudo_amdar_v12_drop_dtw_optimized_20260716/stage3_pseudo_amdar_v12/stage3_v12_calibration_report.json`

## Stage6 强制规则

1. 只对 matched rows 使用窄 support distribution；不得把整批次或 dropped rows 一并缩窄。
2. unmatched AMDAR 保留 batch interval 或物理约束宽分布。
3. `estimated_time_utc` 是推断时间，不是 point-observation truth。
4. AMDAR `effective_strict_truth=false`、`holdout_eligible=false` 必须保持。
5. 正式性能只用 strict aircraft holdout；AMDAR 不能进入正式 holdout truth。
6. 单独做 13 个 singleton matched-row batches 的 on/off sensitivity，防止少量 seeds 对下游产生异常杠杆。

