# 给下一个智能体的交接话术：Stage5 v6 完成后进入 Stage6 Conservative Diagnostic

你接手的是 `/data/LFT-W02_data/pengxu` 下 centralized_v1 三维水平风场重构项目。注意区分大框架 Stage1-6 与旧 Stage2-6 优化计划中的小阶段。本轮已完成大框架 Stage5 v6 HMM/Viterbi、partial alignment 和 bridge 审计。

## 必读顺序

1. `/data/LFT-W02_data/pengxu/优化/数据处理/stage5_v6_hmm_viterbi_optimized_20260715/stage5_v6_results_analysis_and_next_steps.md`
   - 最终 `205 unique batches / 274 rows`、20 mixtures、安全门和未通过的 `+10` 合并门。
2. `/data/LFT-W02_data/pengxu/优化/数据处理/stage5_v6_hmm_viterbi_optimized_20260715/stage5_v6_stage6_gate_check.json`
   - Stage6 只能 `conservative_diagnostic_only`。
3. `/data/LFT-W02_data/pengxu/优化/数据处理/stage5_v6_hmm_viterbi_optimized_20260715/stage5_v6/amdar_adsb_match_diagnostics_v6.json`
   - 完整机器可读结果、安全检查、merge target 和输出路径。
4. `/data/LFT-W02_data/pengxu/优化/数据处理/stage3_pseudo_amdar_v11_domain_matched_optimized_20260715_validated/stage3_v11_results_analysis_and_next_steps.md`
   - 冻结 Stage3 v11 posterior、locked-test 和 domain-gap 口径。
5. `/data/LFT-W02_data/pengxu/优化/数据处理/stage5_sota_cross_stage_optimization_plan_20260715/stage5_sota_cross_stage_optimization_plan_20260715.md`
   - Stage5 v6 验收要求和后续 Stage2 track graph/新增 ADS-B 路线。
6. `/data/LFT-W02_data/pengxu/优化/数据处理/stage5_v5_final_optimized_20260714/stage5_v5_results_analysis_and_next_steps.md`
   - 原冻结 `198/251` 基线。
7. `/data/LFT-W02_data/pengxu/优化/数据处理/stage5_v6_hmm_viterbi_optimized_20260715/stage5_v6_document_reading_manifest_20260715.md`
   - 项目、数据、脚本和衍生文档清单。

## 当前最终状态

- Stage5 v5 冻结基线：`198 batches / 251 rows`；
- Stage5 v6 安全新增：`7 batches / 23 selected rows`；
- Stage5 v6 最终：`205 batches / 274 rows`；
- ambiguous mixtures：`20 batches`，覆盖率均 `>=50%`，不得计 unique；
- 新增 unique：6 个 full HMM/v11 expansion，1 个 `5/6` 行 partial match；
- locked wrong/hard-negative proxy：`0.5821%`；
- safety gate：`true`；
- SOTA merge target `+10`：`false`；
- Stage6 allowed mode：`conservative_diagnostic_only`。

## 项目与数据理解

- TURB strict aircraft holdout 仍是正式重构验证边界；AMDAR 不是 strict truth。
- AMDAR `time_utc` 是批次语义，Stage5 estimated time 只是 support-only 时间分布种子。
- 当前主瓶颈仍是 ADS-B 覆盖和真实几何错位，不是候选数量。
- HMM 无法修复几十公里级 geometry mismatch；partial/bridge 只有在物理门和 v11 posterior 同时通过时才可用。
- 不能把 mixture、posterior、confidence、accepted 或 batch end 推导成逐点真值。
- 25-slice 只通过 `processing_slice_id` 分片调度，不能复制 25 份全量 ADS-B/AMDAR 数据。

## 下一步执行规则

1. 进入 Stage6 时只读取：
   - `stage5_v6/amdar_adsb_match_v6.parquet` 作为 unique narrow support-only seeds；
   - `stage5_v6/amdar_adsb_batch_diagnostics_v6.parquet` 中的 20 个 mixture 作为 mixture distribution 输入；
   - 其余 AMDAR 保持 batch interval 或物理约束宽分布。
2. Stage6 输出必须保留：`effective_strict_truth=false`、`holdout_eligible=false`、`estimated_time_is_strict_point_truth=false`。
3. 报告必须明确 Stage5 safety passed，但 merge target failed；不得宣称已达到 208 或 1%。
4. 如果目标仍要求 Stage5 `+10` 或 `>=1%`，先新增原始 ADS-B 覆盖或重建 Stage2 track graph，再为 stitched states 重跑 Stage3 validation/locked-test；不要继续调 Stage5 阈值。
5. 继续使用 `POLARS_MAX_THREADS=25 / slice_count=25 / workers<=25`，复用单份 ADS-B 点表。

## 推荐开场话术

```text
我已阅读 Stage5 v6 最终分析、Stage6 gate check、Stage3 v11 结果和 Stage5 SOTA 方案。我理解大框架 Stage5 已安全完成为 205 unique batches / 274 rows，并有 20 个仅用于 mixture distribution 的 batches；安全门通过，但 +10 merge target 未通过，因此 Stage6 只能 conservative diagnostic。我不会把 AMDAR、posterior、mixture 或 estimated time 当作 strict point truth，并将继续使用 25-slice / POLARS_MAX_THREADS=25 的单份中间数据口径。
```

## 关键输出

- `/data/LFT-W02_data/pengxu/优化/数据处理/stage5_v6_hmm_viterbi_optimized_20260715/stage5_v6/amdar_adsb_match_v6.parquet`：最终 unique match；
- `/data/LFT-W02_data/pengxu/优化/数据处理/stage5_v6_hmm_viterbi_optimized_20260715/stage5_v6/amdar_adsb_match_incremental_v6.parquet`：7 个新增 batch；
- `/data/LFT-W02_data/pengxu/优化/数据处理/stage5_v6_hmm_viterbi_optimized_20260715/stage5_v6/amdar_adsb_batch_diagnostics_v6.parquet`：unique/mixture/reject 诊断；
- `/data/LFT-W02_data/pengxu/优化/数据处理/stage5_v6_hmm_viterbi_optimized_20260715/stage5_v6/amdar_adsb_candidate_sequence_scores_v6.parquet`：候选序列评分；
- `/data/LFT-W02_data/pengxu/优化/数据处理/stage5_v6_hmm_viterbi_optimized_20260715/stage5_v6/amdar_adsb_partial_row_diagnostics_v6.parquet`：partial selected/excluded 行。
