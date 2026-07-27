# Stage6/7/8 Readiness And Stage9 Assessment

Generated at UTC: 2026-07-01T16:45:00+00:00

## 阶段边界

这里的 Stage6/7/8/9 指 `/data/LFT-W02_data/pengxu/优化/数据处理/amdar_unified_implementation_plan_20260701.md` 的 Unified Plan 阶段，不是 centralized_v1 大框架 Stage1/2/3/4。Stage8 的 "Enhanced Stage1" 是把 Stage6 时间分布和 Stage7 分级 join 回大框架 Stage1 的 `clean_wind` 表。

## Stage6/7/8 达标判断

- Stage6 gate: passed. 所有 431,008 条 AMDAR 都有时间分布，且 AMDAR 仍然 0 strict truth / 0 holdout。
- Stage7 gate: passed. S/A/B/C/R 阈值由 pseudo-AMDAR validation 选择，并由 locked-test 检查；真实 AMDAR 分级只是 support-quality metadata。
- Stage8 gate: passed. `clean_wind_with_confidence.parquet` 保留 431,189 行，AMDAR 431,008 行全部非 holdout，TURB 181 行保留 point-time semantics，其中 175 行为 T0/S official enhanced holdout，6 行为 review。

当前结果适合进入 Stage9。优化空间仍存在，但不应通过放宽 Stage6/7 gate 解决：

- Stage5/ADS-B broad matching 仍是研究优化空间，当前只接受 9 行窄时间支持种子是保守但可审计的。
- C 级和 context support 的高覆盖会带来密度/批次支配风险，应在 Stage10 通过 super-ob 和权重上限处理。
- 是否真的改善风场，需要 Stage12 baseline 复现和 Stage13 多时间尺度消融验证，不能在 Stage9 直接迁移 official Stage4 权重。

## 文献和资料依据

- WMO Aircraft-Based Observations/AMDAR 支持把飞机观测作为高容量上空气象支持资料，但不等价于供应商批次时间是逐点观测时间。
- NOAA AMDAR/ABO 支持质量评估后的 aircraft report 用于 NWP。
- 14 CFR 91.227 说明 ADS-B Out 状态矢量、精度/完整性和延迟要求；本项目中 ADS-B 秒级时间误差不是主导项，AMDAR 批次下发语义才是主导不确定性。
- Sources: WMO ABO (`https://community.wmo.int/en/activity-areas/aircraft-based-observations`), WMO-No. 1200 (`https://library.wmo.int/idurl/4/68221`), NOAA AMDAR/ABO (`https://amdar.noaa.gov/`), 14 CFR 91.227 (`https://www.ecfr.gov/current/title-14/chapter-I/subchapter-F/part-91/subpart-C/section-91.227`).

## Stage9 结果

Stage9 已运行通过：

- 输出目录：`/data/LFT-W02_data/pengxu/优化/数据处理/amdar_unified_stage9_stage2_role_split_optimized_20260701`
- 运行口径：25-slice，`POLARS_MAX_THREADS=25`
- Frames: 7,395
- Observation record rows: 35,918,255
- Unique observations used: 419,671
- Voxel summary rows: 26,591,517
- Channel counts: `{'context_support_records': 33615611, 'batch_support_records': 1234804, 'diagnostic_only_records': 859339, 'current_support_records': 192395, 'rejected_records': 15785, 'strict_truth_records': 321}`
- Completion: `passed_stage9_stage2_role_split_gate=true`

关键审计结果：

- AMDAR holdout rows: 0
- AMDAR effective strict truth rows: 0
- R regular support rows: 0
- Context support nonzero `frame_time_conf`: 0
- `frame_time_conf` bounded in [0, 1]
- Stage9 未复制 `clean_loc.parquet`

## 时间置信度修正

Stage9 使用 Stage6 时间分布与目标帧 T±5 分钟窗口的重叠概率计算 `frame_time_conf`。实现时已修正一个重要风险：三角分布 overlap 必须按概率密度归一化，不能把 10 分钟窗口与 15-60 分钟批次区间的交叠直接 clip 成 1。

全量结果中的典型分布：

- A/B current support `frame_time_conf` median: about 0.251, p90: about 0.493, max: 0.75
- C batch support `frame_time_conf` median: about 0.070, p90: about 0.167, max: 0.25
- Context support uses `context_joint_conf`; its `frame_time_conf=0` by design

这符合预期：宽时间分布进窄时间窗会显著降权，不能等价于逐点观测。

## 空间和文件口径

Stage9 输出目录约 3.4G。它没有复制 25 份全量输入，也没有复制 `clean_loc.parquet`。目录中同时保留了 shard parquet 和合并 parquet，便于复核。脚本已补充 `--drop-shard-parquets-after-merge` 参数，后续若更重视空间可在合并成功后只保留：

- `stage2_observation_records_all.parquet`
- `stage2_voxel_support_summary_all.parquet`
- JSON/MD 审计文档

## 下一步

进入 Unified Plan Stage10：super-ob 和密度权重控制。重点检查并限制：

- 单个 AMDAR batch 在单帧/单体素的总权重；
- 单个 flight 在单帧/单体素的总权重；
- 单个 source 在单帧的最大权重占比；
- C 级 batch support 与 context support 的 super-ob 聚合策略。

在 Stage10/11/12/13 通过前，不要迁移 official Stage2/Stage4 默认权重。
