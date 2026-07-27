# 给下一个智能体的完整交接话术：立即实施大框架 Stage2 v8 Track Graph

生成日期：2026-07-16

## 1. 你的任务

你接手 `/data/LFT-W02_data/pengxu` 下 centralized_v1 三维水平风场重构项目。你的直接任务是：

> 使用现有单份约 1,916 万点 ADS-B 数据，实施大框架 Stage2 v8 local consistency + IMM/Kalman smoother + tracklet graph；随后建立大框架 Stage3 v13 bridge-specific validation；只有 locked-test 安全后，才实施大框架 Stage5 v8 graph matching，以提高稀疏数据利用率。

注意：这里的 Stage2/3/5 是**大框架阶段**，不是 `amdar_stage2_to_6_optimization_plan_20260706.md` 内部小阶段编号。

## 2. 第一件事：按顺序完整阅读

1. `/data/LFT-W02_data/pengxu/优化/数据处理/stage2_v8_track_graph_plan_20260716/stage2_v8_track_graph_full_implementation_plan_20260716.md`
   - 这是你的直接实施规范，包含算法、schema、运行顺序、质量门和禁止操作。
2. `/data/LFT-W02_data/pengxu/优化/数据处理/next_agent_handover_after_stage3_v12_stage5_v7_20260716.md`
   - 理解当前 Stage3 v12 / Stage5 v7 已完成状态与 Stage6 边界。
3. `/data/LFT-W02_data/pengxu/优化/数据处理/stage3_stage5_optimization_results_and_next_steps_20260716.md`
   - 当前联合基线与 Stage6 规则。
4. `/data/LFT-W02_data/pengxu/优化/数据处理/stage3_pseudo_amdar_v12_drop_dtw_optimized_20260716/stage3_v12_results_analysis_and_next_steps.md`
   - 理解 partial row drop policy、hard negatives 和 locked-test 口径。
5. `/data/LFT-W02_data/pengxu/优化/数据处理/stage5_v7_calibrated_partial_optimized_20260716/stage5_v7_results_analysis_and_next_steps.md`
   - 理解当前 `229/345` 基线、24 个新增和 5 个 stitched rejected cases。
6. `/data/LFT-W02_data/pengxu/优化/数据处理/stage5_v6_hmm_viterbi_optimized_20260715/stage5_v6_research_based_breakthrough_plan_20260716.md`
   - Track Graph 的研究依据和原始路线。
7. `/data/LFT-W02_data/pengxu/优化/数据处理/stage5_sota_cross_stage_optimization_plan_20260715/stage5_sota_cross_stage_optimization_plan_20260715.md`
   - 历史 HMM/partial/bridge/track graph 审计设计。
8. `/data/LFT-W02_data/pengxu/优化/数据处理/stage5_sota_cross_stage_optimization_plan_20260715/local_stage5_optimization_audit_summary.json`
   - 已证伪的简单时间窗、reverse、long-leg 和 naive bridge 路线。
9. `/data/LFT-W02_data/pengxu/优化/数据处理/next_agent_handover_optimization_20260706.md`
   - 大框架阶段、truth/holdout 不变量。
10. `/data/LFT-W02_data/pengxu/优化/数据处理/amdar_stage2_to_6_optimization_plan_20260706.md`
    - 原优化目标和小阶段编号，注意不要混淆。
11. `/data/LFT-W02_data/pengxu/workflow/centralized_v1_docs/new_window_project_handover_20260529/centralized_v1_ultimate_summary_20260626.md`
    - strict aircraft holdout 与防泄漏总边界。
12. `/data/LFT-W02_data/pengxu/优化/teacher_reports/plan4.md`
    - AMDAR 时间是批次时间，不是逐点观测时间。

未读完上述文档前不要修改 Stage2、Stage3 或 Stage5 代码。

## 3. 当前必须冻结的基线

- Stage3 v12 quality gate：通过；
- Stage5 v7：`229 unique batches / 345 matched rows`；
- Stage5 v7 safety gate：通过；
- Stage5 v7 merge target：通过；
- Stage6 mode：`target_branch`；
- AMDAR strict truth rows：`0`；
- AMDAR holdout eligible rows：`0`；
- estimated time point-truth：false；
- 旧 `1% / 566 batches` 目标：未达到。

任何新版本都必须把 `229/345` 作为 frozen prior，不能重算后减少。

## 4. 输入数据

### Stage2 主输入

`/data/LFT-W02_data/pengxu/优化/数据处理/amdar_unified_stage0_1_2_optimized_20260701/stage2_adsb_qc_v4/adsb_qc_v4_rows.parquet`

规模和字段：

- 约 `19,162,638` points；
- identity/date/time/lat/lon/alt；
- heading、ground speed；
- 前后点时间、距离、速度和高度差；
- speed/gap/position/altitude/time-order hard break；
- 原 `adsb_leg_id` 和 QC fields。

### Stage2 对照输入

- `/data/LFT-W02_data/pengxu/优化/数据处理/amdar_unified_stage0_1_2_optimized_20260701/stage2_adsb_qc_v4/adsb_leg_points_v4.parquet`
- `/data/LFT-W02_data/pengxu/优化/数据处理/amdar_unified_stage0_1_2_optimized_20260701/stage2_adsb_qc_v4/adsb_leg_quality_components_v4.parquet`

### Stage3 当前输入与模型

- `/data/LFT-W02_data/pengxu/优化/数据处理/stage3_pseudo_amdar_v12_drop_dtw_optimized_20260716/stage3_pseudo_amdar_v12/raw_sequence_case_bank_v12.parquet`
- `/data/LFT-W02_data/pengxu/优化/数据处理/stage3_pseudo_amdar_v12_drop_dtw_optimized_20260716/stage3_pseudo_amdar_v12/raw_sequence_rows_with_truth_v12.parquet`
- `/data/LFT-W02_data/pengxu/优化/数据处理/stage3_pseudo_amdar_v12_drop_dtw_optimized_20260716/stage3_pseudo_amdar_v12/stage3_v12_calibration_report.json`

### Stage5 frozen prior

- `/data/LFT-W02_data/pengxu/优化/数据处理/stage5_v7_calibrated_partial_optimized_20260716/stage5_v7/amdar_adsb_match_v7.parquet`
- `/data/LFT-W02_data/pengxu/优化/数据处理/stage5_v7_calibrated_partial_optimized_20260716/stage5_v7/amdar_adsb_batch_diagnostics_v7.parquet`
- `/data/LFT-W02_data/pengxu/优化/数据处理/stage5_v7_calibrated_partial_optimized_20260716/stage5_v7/amdar_adsb_partial_row_diagnostics_v7.parquet`
- `/data/LFT-W02_data/pengxu/优化/数据处理/stage5_v7_calibrated_partial_optimized_20260716/stage5_v7_stage6_gate_check.json`

## 5. 你需要创建的代码

### 5.1 Stage2 v8

`/data/LFT-W02_data/pengxu/优化/数据处理/amdar_unified_stage2_v8_track_graph_20260716.py`

职责：

- local consistency；
- isolated anomaly detection；
- clean tracklet reconstruction；
- IMM/Kalman + RTS smoother；
- covariance output；
- exact identity/date tracklet graph；
- graph edges；
- top-k paths；
- stitched/mixture state points。

### 5.2 Stage3 v13

`/data/LFT-W02_data/pengxu/优化/数据处理/amdar_unified_stage3_v13_bridge_validation_20260716.py`

职责：

- bridge-specific raw case bank；
- correct/wrong/unreachable/competing bridges；
- calibration/validation/locked-test；
- edge/path posterior；
- corruption reports；
- frozen bridge policy。

### 5.3 Stage5 v8

`/data/LFT-W02_data/pengxu/优化/数据处理/amdar_unified_stage5_v8_graph_matching_20260716.py`

职责：

- 读取 frozen Stage3 v13 policy；
- 先审计 5 known stitched cases；
- 扩展到 graph-recoverable rejects；
- 输出 unique graph matches；
- 输出 graph mixtures；
- 保留 frozen Stage5 v7 prior；
- 生成 Stage6 gate。

## 6. 第一轮立即执行的工作

不要一开始就运行全量 1,916 万点。按以下顺序：

### Action 1：建立 baseline manifest

机器检查：

```text
Stage5 v7 unique batches = 229
Stage5 v7 rows = 345
truth violations = 0
holdout violations = 0
```

### Action 2：检查 25-slice group locality

使用稳定 hash：

```text
tail_norm + flight_norm + service_date_utc
```

同一 group 必须只属于一个 slice。

### Action 3：实现约 1% 输入样本 smoke

先选择每个 slice 少量 exact identity/date groups，总规模约为输入点或 groups 的 1%。这里指运行抽样比例，不是 `566 batches / 1%` 的旧利用率目标。输出：

- local consistency fields；
- clean tracklets；
- smoothed states；
- graph edges；
- graph DAG/top-k paths。

必须检查输入点守恒，不能静默丢点。

### Action 4：只读审计 5 known stitched cases

从 Stage5 v6/v7 diagnostics 定位 5 个 cases，检查：

- 原 tracklets；
- graph nodes；
- gap；
- forward/backward residual；
- competing paths；
- covariance；
- 是否真的能形成唯一 bridge。

这一步只报告，不接受。

### Action 5：构建 Stage3 v13 case bank

必须先完成 validation，才能运行 Stage5 v8 acceptance。

## 7. 正式运行资源规则

统一使用：

```bash
export POLARS_MAX_THREADS=25
```

并使用：

```text
slice_count = 25
workers = 25
```

规则：

- 25 个互斥 shards；
- 每个点只写一次；
- 不复制 25 份全量输入；
- scan/filter/streaming；
- 输出 zstd parquet；
- graph group 不跨 slice；
- compact summary 单独输出。

## 8. 必须实现的数据语义

### Raw point

原始 ADS-B 证据，不修改。

### Clean point/tracklet

经过 local consistency 判定可用于状态估计，但仍保留原始来源。

### Smoothed observed state

由观测和平滑得到，仍能追溯到真实 ADS-B 点。

### Interpolated gap state

模型预测，必须带 covariance，不能标记为 observed。

### Unique graph path

经过 Stage3 v13 校准并具有唯一 posterior/margin，才可用于 Stage5 unique。

### Graph mixture

多个路径合理；不能计 unique，但应作为 Stage6 mixture distribution 使用。

### No coverage

没有可用 ADS-B 证据；必须保留宽 AMDAR batch distribution，不得插值伪造。

## 9. Stage3 v13 硬质量门

全部满足才允许 Stage5 unique：

- wrong-tracklet/path `<=1%`；
- catastrophic `<3%`；
- edge ECE `<=0.05`；
- path ECE `<=0.05`；
- 每类 corruption false acceptance `<=2%`；
- same-identity wrong-tracklet `<=1%`；
- unreachable bridge false acceptance `<=0.5%`；
- clean no-bridge 不明显退化；
- truth/holdout 违规 `0`。

locked-test 只报告，不能调参。

## 10. Stage5 v8 硬规则

- `combined_v8 = frozen_v7 + incremental_graph`；
- prior 229 批全部保留；
- unique、mixture、rejected 分开；
- graph mixture 不计 unique；
- dropped AMDAR rows 不回填；
- interpolated graph states 不当观测 truth；
- batch-end upper bound 保留；
- AMDAR strict truth/holdout 始终 false。

Utility gate 至少满足一个：

- safe unique `+3`；
- calibrated mixtures `+20` 且 Stage6 strict holdout sensitivity 有益；
- graph 显著降低 fragmentation 并提高可解释 candidate coverage。

5 个 known stitched cases 不要求全部接受。若全部拒绝但 hard-negative safety 更好，结果仍可能正确。

## 11. 输出目录

建议：

```text
优化/数据处理/stage2_v8_track_graph_optimized_20260716/
优化/数据处理/stage3_v13_bridge_validation_optimized_20260716/
优化/数据处理/stage5_v8_graph_matching_optimized_20260716/
```

每个目录必须包含：

- `run_config.json`；
- machine-readable report；
- result analysis and next steps；
- source/input manifest；
- 最终 handover。

## 12. 禁止事项

- 不得混淆大框架和小阶段编号；
- 不得覆盖原 Stage2 v4 和 Stage5 v7；
- 不得复制 25 份全量数据；
- 不得跨身份建边；
- 不得把 gap prediction 当观测；
- 不得在 locked-test 上选阈值；
- 不得未经 Stage3 v13 直接接受 stitched；
- 不得把 mixture 改名 unique；
- 不得用 AMDAR 作为正式 holdout truth；
- 不得为达到 1% 放宽 wrong-path gate。

## 13. 完成后必须交付

1. Stage2 v8 正式脚本、输出和分析；
2. Stage3 v13 case bank、模型、locked report 和分析；
3. Stage5 v8 unique/mixture/reject 产品和分析；
4. 与 frozen `229/345` 的对比；
5. Stage6 sensitivity 建议；
6. 是否达到 safety/utility/1% 三类目标的明确结论；
7. 给下一智能体的新交接文档。

## 14. 可直接复制给执行智能体的启动指令

```text
请严格区分大框架 Stage2/3/5 与旧优化 plan 的小阶段编号。完整阅读：
/data/LFT-W02_data/pengxu/优化/数据处理/stage2_v8_track_graph_plan_20260716/stage2_v8_track_graph_full_implementation_plan_20260716.md
以及：
/data/LFT-W02_data/pengxu/优化/数据处理/stage2_v8_track_graph_plan_20260716/next_agent_handover_for_stage2_v8_track_graph_20260716.md

当前 frozen Stage5 v7 基线为 229 unique batches / 345 rows，任何新版本不得回退。请从单份 adsb_qc_v4_rows.parquet 实施大框架 Stage2 v8 local consistency、clean tracklet、IMM/Kalman smoother、exact identity/date tracklet graph 和 top-k path；使用 25-slice / POLARS_MAX_THREADS=25，25 个 slice 必须互斥，禁止复制 25 份全量数据。

先完成约 1% 输入样本 smoke（不是旧利用率目标）和 5 个 known stitched cases 的只读审计，再建立大框架 Stage3 v13 bridge-specific calibration/validation/locked-test。未经 Stage3 v13 全部质量门通过，不得把 stitched path 接入 Stage5 unique。Stage5 v8 必须输出 unique、graph mixture、rejected 三层，并以 frozen v7 + safe incremental 的方式合并。AMDAR、estimated time、interpolated states 永远不是 strict point truth；正式评价只使用 strict aircraft holdout。

请持续实施、运行、分析和修正，直到 safety gate 完全通过；若 utility 不足，必须如实区分错误切段可恢复量与真实 no-coverage，不得通过放宽阈值伪造利用率。
```
