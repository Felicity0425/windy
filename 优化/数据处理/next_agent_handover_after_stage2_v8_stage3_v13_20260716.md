# 给下一个智能体的完整交接话术：Stage2 v8 与 Stage3 v13 已完成

你接手 `/data/LFT-W02_data/pengxu` 下 centralized_v1 三维水平风场重构项目。当前日期为 2026-07-16。注意：本文中的 Stage2/3/5/6 都是**大框架阶段**，不是 `amdar_stage2_to_6_optimization_plan_20260706.md` 内部的小阶段编号。

## 一、当前完成状态

- 大框架 Stage2 v8 local consistency + clean tracklet + covariance smoother + track graph 已全量完成。
- 大框架 Stage3 v13 bridge-specific calibration/validation/locked-test 已完成，全部硬质量门通过。
- Stage5 v7 frozen prior 仍为 `229 unique batches / 345 rows`，未覆盖、未重算、未回退。
- 当前允许进入 Stage5 v8 **小集合审计**，不允许未经审计直接形成 combined merge。

## 二、必须按顺序阅读

1. `/data/LFT-W02_data/pengxu/优化/数据处理/stage2_stage3_v8_v13_joint_results_and_next_steps_20260716.md`
   - 联合结论、是否达标、下一步边界。
2. `/data/LFT-W02_data/pengxu/优化/数据处理/stage2_stage3_v8_v13_joint_audit_20260716.json`
   - 机器可读正式指标。
3. `/data/LFT-W02_data/pengxu/优化/数据处理/stage2_v8_track_graph_optimized_20260716/stage2_v8_results_analysis_and_next_steps.md`
   - Stage2 点守恒、fragmentation、tracklet tier、graph 和历史 5 cases 审计。
4. `/data/LFT-W02_data/pengxu/优化/数据处理/stage3_v13_bridge_validation_optimized_20260716/stage3_v13_results_analysis_and_next_steps.md`
   - Stage3 case bank、冻结 policy、locked metrics 和修正记录。
5. `/data/LFT-W02_data/pengxu/优化/数据处理/stage2_v8_track_graph_plan_20260716/stage2_v8_track_graph_full_implementation_plan_20260716.md`
   - 原始实施规范、Stage5/6 接入要求和禁止操作。
6. `/data/LFT-W02_data/pengxu/优化/数据处理/stage5_v7_calibrated_partial_optimized_20260716/stage5_v7_results_analysis_and_next_steps.md`
   - frozen `229/345`、24 个 v7 增量和 5 个 stitched rejects。
7. `/data/LFT-W02_data/pengxu/优化/数据处理/stage3_pseudo_amdar_v12_drop_dtw_optimized_20260716/stage3_v12_results_analysis_and_next_steps.md`
   - partial row exclusion policy，Stage5 v8 仍需同时满足。
8. `/data/LFT-W02_data/pengxu/优化/数据处理/next_agent_handover_optimization_20260706.md`
   - 大框架与小阶段编号、truth/holdout 不变量。
9. `/data/LFT-W02_data/pengxu/workflow/centralized_v1_docs/new_window_project_handover_20260529/centralized_v1_ultimate_summary_20260626.md`
   - strict aircraft holdout 与防泄漏总边界。
10. `/data/LFT-W02_data/pengxu/优化/teacher_reports/plan4.md`
    - AMDAR 时间是批次时间，不是逐点观测时间。

## 三、关键代码

- Stage2 v8：`/data/LFT-W02_data/pengxu/优化/数据处理/amdar_unified_stage2_v8_track_graph_20260716.py`
- Stage3 v13：`/data/LFT-W02_data/pengxu/优化/数据处理/amdar_unified_stage3_v13_bridge_validation_20260716.py`

正式运行均使用：

```bash
export POLARS_MAX_THREADS=25
```

并采用 `slice_count=25 / workers=25`。25 个 slice 按 exact identity/date 稳定 hash 互斥分区，每个点只属于一个 shard，不存在 25 份全量输入复制。

## 四、Stage2 正式输出

根目录：

`/data/LFT-W02_data/pengxu/优化/数据处理/stage2_v8_track_graph_optimized_20260716/`

重点文件：

- `run_config.json`
- `source_input_manifest.json`
- `stage2_v8_input_profile.json`
- `stage2_track_graph_v8/local_consistency_points_v8/`
- `stage2_track_graph_v8/clean_tracklet_points_v8/`
- `stage2_track_graph_v8/smoothed_track_states_v8/`
- `stage2_track_graph_v8/clean_tracklet_summary_v8.parquet`
- `stage2_track_graph_v8/tracklet_graph_edges_v8.parquet`
- `stage2_track_graph_v8/track_graph_paths_v8.parquet`
- `stage2_track_graph_v8/stage2_v8_track_graph_report.json`

固定指标：

- input/local：`19,162,638 / 19,162,638`。
- clean rows：`19,154,894`。
- fragmentation：`2,977,478 -> 2,953,850`，减少 `23,628`。
- physical graph edges：`11,306`。
- exact groups：`357,754`，跨 slice 违规 `0`。
- formal Stage2 accepts：`0`。

## 五、Stage3 正式输出

根目录：

`/data/LFT-W02_data/pengxu/优化/数据处理/stage3_v13_bridge_validation_optimized_20260716/`

重点文件：

- `run_config.json`
- `stage3_bridge_validation_v13/bridge_case_bank_v13.parquet`
- `stage3_bridge_validation_v13/bridge_case_scores_v13.parquet`
- `stage3_bridge_validation_v13/bridge_locked_test_v13.parquet`
- `stage3_bridge_validation_v13/edge_path_posterior_model_v13.json`
- `stage3_bridge_validation_v13/stage3_v13_bridge_validation_report.json`
- `stage3_bridge_validation_v13/stage3_v13_quality_gate.json`

固定 locked-test 指标：

- cases：`27,599`。
- wrong-tracklet/path：`0.0827%`。
- catastrophic：`0.0645%`。
- edge/path ECE：`0.000321`。
- max corruption false acceptance：`0.8621%`。
- same-identity wrong-tracklet：`0.8621%`。
- unreachable bridge：`0%`。
- quality gate：全部通过。

正式 policy 必须完整读取 model JSON。posterior threshold `0.0005426103460326424` 不能脱离 model 输出尺度单独手改；maximum formal gap 固定为 `1800s`。

## 六、项目和数据的固定理解

- ADS-B 是轨迹证据；AMDAR 是 support-only 风观测，不是 point truth。
- AMDAR 原始时间是批次结束/下发时间语义，不是逐点观测时间。
- Stage2 smoothed observed state 可追溯到真实 ADS-B 点。
- gap state 是 prediction，必须传播 covariance，永远不能标记 observed。
- Stage3 pseudo truth 来自 ADS-B clean tracklet，不来自 AMDAR。
- graph mixture 不能计 unique。
- strict aircraft holdout 是最终正式评价；AMDAR strict truth/holdout 始终为 0。

## 七、历史 5 stitched cases 的固定结论

5 个批次对应 4 个 unique identity/date groups：

- `B1353/MF8286/2026-02-09`：无 physical graph edge。
- `B1661/3U3551/2026-02-17`：两个历史批次，同组；无 physical graph edge。
- `B1355/MF8773/2026-01-28`：有 1 个 294 秒 physical hypothesis，可进入 Stage5 v8 小审计。
- `B1820/3U6920/2026-02-13`：无 physical graph edge。

不要求 5/5 接受。无 edge 的 case 应保持 rejected/no-coverage。

## 八、下一任务：Stage5 v8 小集合 graph audit

必须实现：

1. 新建 `amdar_unified_stage5_v8_graph_matching_20260716.py`。
2. `combined_v8 = frozen_stage5_v7 + safe_graph_incremental`。
3. prior `229/345` 全部保留，overlap/duplicate 为 0。
4. 第一轮只处理：历史 5 stitched、graph-recoverable rejects、same-identity hard negatives、prior 229 regression。
5. emission 使用 covariance-normalized residual，不再只用固定 km/m cost。
6. 同时应用 Stage3 v13 bridge/path posterior、path margin、Stage3 v12 partial policy、batch-end upper bound。
7. 输出 unique、graph mixture、rejected 三层；mixture 不计 unique。
8. 所有新增 AMDAR `effective_strict_truth=false`、`holdout_eligible=false`、`estimated_time_is_strict_point_truth=false`。

Stage5 v8 utility gate 至少满足一个：safe unique `+3`；或 calibrated mixtures `+20` 且 Stage6 strict holdout sensitivity 有益；或 graph 显著改善 fragmentation/candidate coverage。不得为 utility 放宽 safety。

## 九、可直接复制给下一智能体的启动指令

```text
请严格区分大框架 Stage2/3/5/6 与旧优化 plan 的小阶段编号。先完整阅读：
/data/LFT-W02_data/pengxu/优化/数据处理/next_agent_handover_after_stage2_v8_stage3_v13_20260716.md
/data/LFT-W02_data/pengxu/优化/数据处理/stage2_stage3_v8_v13_joint_results_and_next_steps_20260716.md
/data/LFT-W02_data/pengxu/优化/数据处理/stage2_stage3_v8_v13_joint_audit_20260716.json

Stage2 v8 已全量处理 19,162,638 点，点守恒通过，fragmentation 减少 23,628，生成 11,306 个 physical graph hypotheses，357,754 个 exact identity/date groups 跨 slice 违规为 0，Stage2 formal accepts 为 0。Stage3 v13 已完成 27,599-case locked-test，wrong-path 0.0827%、catastrophic 0.0645%、edge/path ECE 0.000321、same-identity wrong-tracklet 0.8621%、unreachable 0%，全部 hard gates 通过。

现在实现大框架 Stage5 v8 小集合 graph audit。冻结 Stage5 v7 的 229 unique batches / 345 rows；combined_v8 只能增量追加。必须读取 Stage2 covariance 和 Stage3 v13 完整 model JSON，同时保留 Stage3 v12 partial policy、batch-end upper bound 和 truth invariants。先审计历史 5 stitched cases、graph-recoverable rejects、hard negatives 与 prior 229 regression；输出 unique、mixture、rejected，mixture 不计 unique。历史 5 cases 中仅 B1355/MF8773/2026-01-28 有 physical graph hypothesis，其余应保持 rejected/no-coverage。继续使用 POLARS_MAX_THREADS=25、25-slice、互斥 shards，禁止复制 25 份全量数据。
```

