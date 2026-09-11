# 大框架 Stage5 v7 结果分析与下一步建议

生成日期：2026-07-16

## 1. 阶段定义

本文的 **Stage5 v7** 是大框架 Stage5 的真实 AMDAR-ADS-B support-only 匹配，不是优化 plan 内部的小阶段5/6。Stage3 v12 提供的是 pseudo validation posterior；真实 AMDAR 没有 point-truth label。

## 2. 审计范围

严格按照 `stage5_v6_research_based_breakthrough_plan_20260716.md` 先运行小集合，而不是全量盲跑：

- Stage5 v6 的 `20` 个 50%-66.7% mixtures；
- `4` 个 coverage `>=70%` 但 v11 aggregate posterior 未通过的 near-pass partial cases；
- `5` 个 physical stitched-track cases；
- 合计 `29` 个唯一 audit batches；
- 原 Stage5 v6 `205` 个 unique batches 全部冻结为回退保护集。

## 3. 正式运行口径

```bash
POLARS_MAX_THREADS=25 \
/data/LFT-W02_data/pengxu/.conda/envs/windy310/bin/python \
/data/LFT-W02_data/pengxu/优化/数据处理/amdar_unified_stage5_v7_calibrated_partial_20260716.py \
  --out-dir /data/LFT-W02_data/pengxu/优化/数据处理/stage5_v7_calibrated_partial_optimized_20260716 \
  --slice-count 25 \
  --workers 25 \
  --candidate-topk 10
```

只读取 audit 所需 AMDAR 行和 candidate ADS-B legs，输出约 `164 KB`，没有复制 25 份全量数据。

## 4. 结果

- Stage5 v6 prior unique：`205 batches / 274 rows`。
- Stage5 v7 新增：`24 batches / 71 rows`。
- 最终：`229 unique batches / 345 matched rows`。
- 相对冻结 Stage5 v5 `198 batches / 251 rows`：
  - unique batches 增加 `31`，提升 `15.66%`；
  - matched rows 增加 `94`，提升 `37.45%`。
- 相对 Stage5 v6：unique batches 从 `205` 增至 `229`，提升 `11.71%`。
- `20/20` mixtures 通过 v12 calibrated partial gate。
- `4/4` near-pass partial cases 通过。
- `0/5` stitched-track cases 通过；继续保持 rejected，说明没有越过未验证 bridge 边界。

## 5. 新增批次质量

- matched fraction：最小 `0.50`，中位数 `0.50`，q90 `0.70`，最大 `0.75`。
- `13` 个新增批次是 2 行批次，只保留其中 1 行；被排除行不会进入 match 产品。
- 所有新增均满足：
  - `strong_tail_flight_date` identity；
  - Stage3 v12 frozen validation gate；
  - candidate posterior `>=0.90`；
  - cross-track q90 `<=1.5 km`；
  - vertical q90 `<=800 m`；
  - sampling gap `<=900 s`；
  - projected time 不晚于 batch-end 上界 `180 s`；
  - leave-one-out path stability `>=0.60`。

## 6. 安全与一致性审计

- prior `205` unique batches 全部保留。
- 新增与 prior overlap：`0`。
- incremental `(amdar_batch_id, source_row_index)` 重复：`0`。
- combined null batch ID：`0`。
- truth/holdout/time-point-truth 违规：`0`。
- 新增物理门违规：`0`。
- Stage5 v7 safety gate：通过。
- Stage5 v7 merge target：通过：新增 `24 >= 3`；相对 v5 总新增 `31 >= 10`；最终 `229 >= 208`。

## 7. 数据利用率的正确解释

若以原 `56,521` 个 AMDAR batches 为分母，最终 unique batch rate 约为 `0.405%`，仍未达到旧计划的 `1% / 566 batches`。本轮完成的是突破方案定义的安全 merge gate，而不是宣称解决 ADS-B 覆盖不足。

因此可以进入 Stage6 的 `target_branch`，但必须继续：

- unique matched rows 仅作为 narrow support-only seeds；
- dropped rows 保持 excluded diagnostic；
- unmatched AMDAR 保持 batch interval 或物理约束宽分布；
- 不把 posterior、accepted 或 estimated time 改成 strict point truth。

## 8. 下一步建议

1. Stage6 使用 `amdar_adsb_match_v7.parquet`，同时读取 `amdar_adsb_partial_row_diagnostics_v7.parquet`，禁止把 dropped rows 回填为窄时间点。
2. 对 13 个 singleton matched-row batches 单独报告 sensitivity：启用/禁用这些 seeds，比较 Stage6 及最终 strict aircraft holdout；不得用 AMDAR 自身作为 holdout truth。
3. 5 个 stitched cases 继续冻结 rejected。若要利用，转 Stage2 v8 local-consistency + IMM/Kalman track graph，并新建 bridge-specific Stage3 validation。
4. 若目标恢复为 `>=1%`，需要新增同日期/同机尾/同航班区域的 ADS-B、ADS-C 或其他轨迹覆盖，不应继续放宽 Stage5 阈值。

