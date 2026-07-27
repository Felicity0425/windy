# Stage5 v6 HMM/Viterbi 最终结果分析与下一步建议

生成日期：2026-07-15

## 1. 阶段边界

本文的 Stage5 指大框架 Stage5：真实 AMDAR-ADS-B 数据关联与时间投影，不是旧 Stage2-6 优化计划中的“小阶段5”。大框架 Stage3 v11 已完成 hard-negative/domain-matched pseudo 验证；本轮使用其冻结 posterior 和 validation-only 阈值，不在 locked-test 上调参。

AMDAR 始终是 support-only：`effective_strict_truth=false`、`holdout_eligible=false`，`estimated_time_utc` 不是逐点观测真值。

## 2. 正式运行口径

- `POLARS_MAX_THREADS=25`；
- `slice_count=25`；
- `workers=25`；
- 复用单份 Stage2 ADS-B 点表；
- 只保存 compact candidate score、batch diagnostic、incremental match 和 combined match；
- 未复制 25 份全量中间数据。

复现命令：

```bash
POLARS_MAX_THREADS=25 /data/LFT-W02_data/pengxu/.conda/envs/windy310/bin/python \
  /data/LFT-W02_data/pengxu/优化/数据处理/amdar_unified_stage5_v6_hmm_viterbi_20260715.py \
  --out-dir /data/LFT-W02_data/pengxu/优化/数据处理/stage5_v6_hmm_viterbi_optimized_20260715 \
  --slice-count 25 --workers 25 --candidate-topk 10
```

## 3. 实现内容

1. 冻结 Stage5 v5 的候选宇宙和 `198 batches / 251 rows` 安全基线。
2. 对 monotonic 和 batch-end rejects 运行 forward/reverse/PCA-order HMM/Viterbi；状态为 ADS-B segment，严格保持非递减沿轨路径和 batch-end `+180s` 上界。
3. 对 `best_cost_gt_3` 运行可跳过异常行的 partial Viterbi；unique 至少覆盖 `70%`，mixture 至少覆盖 `50%`，所有剔除行逐行记录原因。
4. 对旧 expansion validation rejects 使用 Stage3 v11 冻结 posterior 重新校准；`SX` 短 leg 只映射为 S2 association source，不提升为 strict truth。
5. 审计同 exact identity 相邻 tracklet 的严格物理 bridge；桥接速度、时间顺序和垂直率必须物理可达，随后仍需通过完整 HMM、物理门和 posterior 门。
6. 输出 unique accepted、ambiguous mixture、diagnostic reject 三种角色；mixture 不计 unique acceptance。

## 4. 最终结果

- 冻结基线：`198 unique batches / 251 rows`；
- 安全新增：`7 unique batches / 23 selected rows`；
- 最终：`205 unique batches / 274 rows`；
- calibrated ambiguous mixtures：`20 batches`，覆盖率 `50%-66.7%`；
- 新增 unique 构成：`6` 个 full HMM/v11 expansion，`1` 个 `83.33%` partial monotone alignment；
- partial unique 的 6 行中保留 5 行，1 行明确标记为 `excluded_spatial_outlier`；
- unique best cost：median `0.8699`，p90 `1.0148`，max `1.0678`；
- unique Stage3 v11 association posterior：min `0.9412`，median `0.9646`，max `0.9882`；
- Stage3 v11 locked-test proxy wrong/hard-negative rate：`0.5821%`，低于 `1%`。

## 5. 安全检查

全部安全门通过：

- 原 198 批完整保留；
- 增量与基线 batch 无重叠；
- 增量 `(amdar_batch_id, source_row_index)` 无重复；
- 所有增量均为 exact identity；
- 所有增量均通过原有 cost/cross-track/vertical/sampling-gap/batch-end 物理门；
- 所有增量均通过冻结 Stage3 v11 posterior 门；
- mixture 没有计入 unique；
- combined match 中 truth/holdout/point-truth 违规行数均为 0；
- 25-slice 省空间口径保持。

## 6. 为什么没有达到 `+10 unique`

SOTA 合并门要求保留原 198 批并新增至少 10 批。本轮最终新增 7 批，差 3 批，因此 `passed_stage5_v6_merge_target=false`。

已完整验证但不能安全补足的路线：

- monotonic reject 的 HMM 最低几何仍明显超界，新增 0；
- batch-end constrained HMM 没有产生 posterior 达标新增；
- `>=70%` partial 候选只有 5 批，其中仅 1 批同时通过完整物理和 posterior 门；
- 严格物理 bridge 虽产生局部低成本候选，但 Stage3 v11 posterior 不足，新增 0；
- 继续放宽 posterior、cross-track、cost、batch-end 或把低覆盖 mixture 计为 unique 都会违反既定安全边界。

因此，不能为了凑够 10 批而伪造“达标”。当前 `205/274 + 20 mixtures` 是同一数据源、现有验证证据下的安全最优结果。

## 7. Stage6 决策

只允许进入 **conservative diagnostic**：

1. `274` 条 unique matched rows 可作为窄分布 support-only seeds；
2. `20` 个 mixture batches 只能生成 top-K/mixture 时间分布，不得当 unique 或 point truth；
3. 其余 AMDAR 保持批次区间或物理约束宽分布；
4. Stage6 报告必须明确 `Stage5 safety=true, merge_target=false`；
5. 不得把 `estimated_time_utc`、batch end 或 posterior 推导为 strict truth。

## 8. 真正达到 `+10` 或 `>=1%` 的下一步

优先级从高到低：

1. 增加与 AMDAR 同日期、机尾、航班、区域匹配的原始 ADS-B 覆盖；
2. 重新运行 Stage2 原始 track segmentation/track graph，而不是只重评分旧 leg；
3. 为 stitched track states 新建 Stage3 validation/locked-test，不用当前 aggregate posterior 直接放行 bridge；
4. 在新证据下重新运行 Stage4 association prior 与 Stage5；
5. 在上游候选证据没有变化前冻结本结果，不继续做阈值放宽。

## 9. 核心输出

- `stage5_v6/amdar_adsb_match_diagnostics_v6.json`：完整结果、安全门、合并目标和 Stage6 模式；
- `stage5_v6/amdar_adsb_batch_diagnostics_v6.parquet`：51,687 个被审计 batch 的 v6 诊断；
- `stage5_v6/amdar_adsb_candidate_sequence_scores_v6.parquet`：compact candidate/HMM/partial/bridge score；
- `stage5_v6/amdar_adsb_match_incremental_v6.parquet`：7 个新增 unique batch、23 行；
- `stage5_v6/amdar_adsb_match_v6.parquet`：最终 205 batch、274 行；
- `stage5_v6/amdar_adsb_partial_row_diagnostics_v6.parquet`：partial selected/excluded 行级解释。
