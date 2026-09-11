# centralized_v1 最新工程结果、数据集说明与通俗解读

> 本次复核日期：2026-09-11
> 工程根目录：`/data/LFT-W02_data/pengxu/`
> 本文检索范围：`优化/`、`centralized_v1_output/`、`stage1_output/`、`workflow/centralized_v1_docs/new_window_project_handover_20260529/` 及其下的代码、配置、JSON 报告、Parquet/CSV 结果和交接文档。
> **最新有效结果口径：**截至 2026-09-11，目录中可确认的最新正式优化产物集中在 2026-07-20（Stage2/Stage3 结果总说明）、2026-07-17（周报）和 2026-07-16（Stage2 v8、Stage3 v13、Stage5 v7 正式结果）；原始 `centralized_v1_output/` 的最新可见诊断产物为 2026-06-25 的 representation-error equivalent report，最新官方主线对比为 2026-06-14。未发现之后新的正式全量实验报告，因此下文不会把旧计划目标、smoke 结果、展示层填充或诊断结果冒充为最新正式结果。
> **阅读提示：**前 10 章保留原有项目交接结构；第 11 至 16 章是本次新增的普通话解释、数据集对比、术语词典、图表、证据等级和执行计划。数字后面的“通过”只表示对应质量门通过，不等于最终三维风场已经完成。

---

## 1. 项目全称与核心定位（机器可读：任务域、优化目标、应用场景）

### 1.1 项目全称

**centralized_v1：基于稀疏飞机风观测、ADS-B 航迹和独立背景场的中心化三维水平风场重构与严格飞机留出验证工程。**

英文工作描述可概括为：

> Centralized 3-D horizontal wind-field reconstruction from sparse aircraft-wind observations, ADS-B trajectory evidence and weak background fields, with auditable aircraft-holdout evaluation.

### 1.2 机器可读项目定义

```yaml
project_name: centralized_v1
task_domain:
  - atmospheric_science
  - numerical_weather_analysis
  - aircraft_wind_observation_processing
  - sparse_observation_data_association
  - 3d_horizontal_wind_field_reconstruction
primary_objective:
  - improve sparse aircraft-wind utilization without falsifying truth labels
  - reconstruct physically plausible u/v wind fields
  - reduce time/identity/trajectory association errors
  - preserve strict aircraft holdout integrity
application_scenarios:
  - radar-frame or analysis-time wind-field reconstruction
  - aircraft observation quality control and support weighting
  - AMDAR-ADS-B sequence association
  - background-plus-observation diagnostic assimilation
  - research-grade auditable evaluation
strict_boundaries:
  amdar_effective_strict_truth: false
  amdar_holdout_eligible: false
  interpolated_adsb_state_is_observed_point: false
  pseudo_validation_is_real_truth: false
  graph_edge_is_automatically_unique_match: false
latest_formal_chain:
  - stage1_AMDAR_semantic_qc
  - stage2_v8_track_graph
  - stage3_v13_bridge_validation
  - stage4_confidence_v3
  - stage5_v7_calibrated_partial_matching
next_authorized_scope: stage5_v8_small_set_graph_audit
```

### 1.3 当前工程的核心定位变化

项目早期重点是直接提升三维风场重构误差；最新工程阶段已转为“**先保证数据语义、证据独立性和关联安全，再扩大可用支持观测**”。最重要的主线修正包括：

1. `CMA-RA/CRA40` 被识别为 reanalysis/analysis product，独立性不足，当前只适合 display-only 或弱背景参考，不直接作为 official OI 的独立背景。
2. `GFS forecast` 被选为更干净的独立背景候选，但当前仅完成 weak/diagnostic background 诊断，尚未授权直接进入 official OI blend。
3. AMDAR 原始时间不再被解释为逐点真实观测时间，而是以批次结束/下发语义处理。
4. AMDAR、ADS-B 重建状态、pseudo-AMDAR、graph bridge 和 background field 被拆成不同证据角色，禁止把 support-only 结果升级成 strict truth。

---

## 2. 项目背景与待解决问题（原始痛点、缺陷、优化动机）

### 2.1 原始数据与业务痛点

项目面对的是稀疏、异步、非均匀质量的飞机风观测。主要数据现实如下：

- AMDAR 以批次形式提供，原始时间更接近 batch end 或 dissemination time，而不是每一行的真实采样时刻。
- ADS-B 点数很多，但存在异常位置、异常高度、接收缺口和身份/日期跨片段问题；约 `19,162,638` 个点被组织成约 `2,977,478` 个旧版兼容航段/tracklet，平均航段极短。
- 同一机尾、同一天可能有多个竞争航段；仅靠 identity/date 或最近距离，容易把正确飞机接到错误 tracklet。
- AMDAR 批次内单个异常行会导致整批拒绝，造成“部分行其实可用、但整批不可用”的利用率损失。
- 真实 ADS-B 覆盖并不完整。算法不能因没有同日期、同机尾、同航班和同区域证据，就凭借放宽阈值生成“合理看起来”的观测。
- 12 km 以上高空的 baseline 误差显著高于低空：全高度 baseline vector RMSE 为 `14.7690`，工程 proxy floor 为 `11.1126`；`12 km+` 区域 baseline vector RMSE 约 `19.9177`。

### 2.2 原始框架缺陷

原始框架的主要问题不是单一模型不够大，而是数据角色和误差语义混在一起：

1. **时间语义缺陷：**把批次时间近似当作逐点时间，会造成时间重建和风场配准偏差。
2. **身份/航段缺陷：**旧版 tracklet 生成受异常点和接收空洞影响，导致同一真实飞行被切成多个碎片。
3. **匹配目标缺陷：**独立最近线段投影无法表达序列单调性、方向一致性、局部缺测和部分行异常。
4. **置信度缺陷：**早期用单一常数或粗粒度标签表示全部 AMDAR，无法区分来源质量、气象物理一致性、批次代表性和身份风险。
5. **验证缺陷：**pseudo validation、真实 AMDAR matching、strict aircraft holdout 和 graph bridge 曾存在语义混淆，容易出现“验证通过但实际产品越权”的问题。
6. **背景独立性缺陷：**CMA/CRA40 与目标 holdout 的独立性没有被证明，直接进入 OI 会产生泄漏风险。
7. **工程扩展缺陷：**全量候选展开容易复制 25 份数据，内存和磁盘开销高，需要 slice、audit-first 和 compact output 设计。

### 2.3 优化动机

本轮优化的真实目标不是单纯追求接受率，而是：

- 在 strict truth/holdout 不变的前提下释放可安全使用的支持观测；
- 将“完整匹配、部分匹配、bridge、mixture、reject”分层输出；
- 让每个 accepted 结果可追溯到原始点、身份、日期、候选 path、质量门和 posterior；
- 先用独立验证证明安全性，再决定是否进入 Stage5/Stage6/Stage4 下游；
- 避免用调阈值掩盖真实的 ADS-B coverage 不足和空间不重合问题。

---

## 3. 核心算法 / 工程原理（底层机制、数学逻辑、物理逻辑、原始框架缺陷）

### 3.1 总体思想：证据分层 + 物理约束 + 独立质量门

工程把每类数据放入不同角色：

| 证据 | 角色 | 是否 strict truth | 是否可进入下游 | 主要验证 |
|---|---|---:|---:|---|
| 官方 aircraft holdout | 正式评估真值 | 是 | 仅评估 | aircraft holdout split |
| AMDAR 原始/批次信息 | support-only | 否 | 经过分级后支持 OI/Stage6 | Stage1 QC、Stage4 confidence |
| ADS-B observed points | 轨迹证据 | 否 | 可构建候选轨迹 | Stage2 QC |
| ADS-B smoothed/interpolated state | 轨迹状态估计 | 否 | 只能作为 support/bridge evidence | Stage2/Stage3 |
| pseudo-AMDAR | 验证样本 | 否 | 不能直接成为产品真值 | Stage3 locked-test |
| graph edge/path | 物理连接假设 | 否 | 需 Stage3 bridge posterior + Stage5 gate | Stage3 v13 |
| GFS forecast | 独立弱背景候选 | 否 | report-only/受限 OI 试验 | background/OI diagnostics |
| CMA-RA/CRA40 | 再分析/分析参考 | 否 | display-only weak fill | independence audit |

### 3.2 Stage1：AMDAR 语义审计与质量分层

Stage1 不再只输出风值，而是补齐：

- source quality、meteorological physics、batch representativeness、identity completeness；
- batch end/dissemination time 语义；
- continuous time uncertainty；
- `effective_strict_truth`、`holdout_eligible`、`usage_role`；
- 高风速保留与 unsupported high-wind reject 标识。

时间不确定性采用保守分布而不是虚构 point time。Stage4 v3 的 AMDAR time uncertainty 统计为：最小 `180 s`、p10 `300 s`、中位数 `900 s`、p90 `1500 s`、p99/最大 `2100 s`。

### 3.3 Stage2 v8：local consistency、clean tracklet、协方差平滑与 graph prior

Stage2 v8 的底层链路为：

```text
raw ADS-B points
  -> local consistency checks
  -> point anomaly typing
  -> clean/uncertain/diagnostic role assignment
  -> covariance-aware constant-velocity IMM-style forward/backward smoothing
  -> clean tracklets
  -> candidate graph edges
  -> physical graph edges and graph paths
```

核心机制：

1. **局部一致性检查：**按相邻时间、水平速度、航向变化、垂直速度和高度突变识别 `isolated_position_spike`、`isolated_altitude_spike`、`unreachable_motion_edge`、`timestamp_bias_candidate` 等异常类型。
2. **不删除原始证据：**`diagnostic_exclude` 只表示该点不进入 clean tracklet；点仍保留在 local-consistency 产品中，保证 point conservation。
3. **不确定点降权：**对 `uncertain_keep_low_weight` 保留状态但降低权重，避免把边界点粗暴删除。
4. **运动模型：**当前是 diagonal constant-velocity、IMM-style forward/backward smoother；输出均值、协方差和 mode probability，但还不是完整 CTRV/IMM/RTS。
5. **Graph prior：**以 identity/date、时间差、空间位置、水平/垂直运动可达性和协方差状态生成 graph candidates；Stage2 只生成 prior，`formal_bridge_accepts=0` 是设计不变量。

可抽象为候选边代价：

\[
J(e)=w_t J_t(e)+w_h J_h(e)+w_v J_v(e)+w_m J_{motion}(e)+w_c J_{cov}(e),
\]

其中时间差、水平/垂直位置差、运动可达性和不确定性归一化项共同决定边是否进入 physical graph；该分数不是最终 unique posterior。

### 3.4 Stage3 v12：Drop-DTW 部分序列验证

Stage3 v12 解决“批次中某一行异常导致整批拒绝”的问题。对 AMDAR 序列与 ADS-B 候选序列执行单调动态规划，在“匹配当前行”和“支付 drop penalty 丢弃当前行”之间选择：

\[
DP(i,j)=\min\begin{cases}
DP(i-1,j-1)+d(x_i,y_j),\\
DP(i-1,j)+\lambda_{drop},\\
DP(i,j-1)+\lambda_{skip}.
\end{cases}
\]

其中 `d` 综合水平距离、垂直差和 robust/Huber 损失；同时要求 matched fraction、contiguous fraction、posterior、cross-track、vertical、sampling gap、batch-end 上界和 path stability 通过。被 drop 的行保持 excluded/diagnostic，不回填成 strict truth。

### 3.5 Stage3 v13：bridge/path posterior 与 locked-test

Stage3 v13 将 graph bridge 单独建模，不再复用普通 association posterior：

- edge-level posterior：判断两段 tracklet 是否存在可信物理连接；
- path-level posterior：判断完整 bridge path 是否稳定；
- calibration/validation/locked-test 三分；
- hard negatives：same-identity wrong-tracklet、wrong flight same tail/date、unreachable bridge、competing fork path；
- formal maximum gap：`1800 s`；
- 分离 `clean no-bridge retention` 与真正的 bridge acceptance。

### 3.6 Stage5 v6/v7：HMM/Viterbi + calibrated partial matching

Stage5 v6 用 forward、reverse 和 PCA-order HMM/Viterbi 替代独立最近线段投影，增加序列状态、顺序一致性和 path stability。Stage5 v7 在 v6 基础上只审计有限候选集合，并引入 Stage3 v12 calibrated partial policy。

当前 v7 采用的关键门包括：

```text
candidate_topk = 10
candidate_posterior_min = 0.90
max_cross_track_q90 = 1.5 km
max_vertical_q90 = 800 m
max_sampling_gap = 900 s
max_after_batch_end = 180 s
maximum_drop_fraction = 0.50
matched_fraction_min = 0.50
contiguous_fraction_min = 0.40
```

输出语义明确分为 `unique`、`mixture`、`partial`、`diagnostic reject`。mixture 不计入 unique；estimated time 不能升级为逐点真值。

### 3.7 Stage4：置信度、背景与风场重构

Stage4 v3 将置信度拆成四个核心组件：

1. `source_quality_conf`；
2. `met_physics_conf`；
3. `batch_representativeness_conf`；
4. `identity_completeness_conf`。

对 AMDAR 生成 T1/T2/T3/T4 support tiers，T0 只保留原有 TURB strict truth。Stage4 的正式风场主线仍是严格 aircraft holdout 评估；GFS 当前定位为 weak/diagnostic background，CMA 为 display-only/参考背景。

---

## 4. 本次优化具体实现方案（逐模块改造点、工程落地方式、参数改动、结构改动）

### 4.1 Stage1 数据结构改造

- 增加 AMDAR 的批次时间语义字段，避免把 batch end 误当逐点 time truth。
- 增加连续时间不确定性字段，支持 Stage6 overlap/weight 计算。
- 增加 `usage_role`、`effective_strict_truth`、`holdout_eligible` 和质量分层字段。
- 高风速采用保守保留策略：有足够来源和物理支持时进入 support candidate，否则拒绝或降级。
- 保留与旧 Stage2/Stage4 的兼容字段，避免破坏官方 strict holdout 连续性。

### 4.2 Stage2 v8 文件和模块改造

实现脚本：`优化/数据处理/amdar_unified_stage2_v8_track_graph_20260716.py`。

主要模块：

- local consistency point audit；
- point anomaly type assignment；
- clean tracklet generation；
- forward/backward covariance smoother；
- candidate edge generation；
- physical edge filtering；
- graph path compact output；
- per-slice report 和全局 conservation report。

正式运行配置：`25` slices、`25` workers、`max_graph_gap_s=1800`、`top_k=5`，采用 Polars 多线程和分片输出，避免 25 份全量数据副本。

结构性改动：

- 原始点、clean point、uncertain point、diagnostic excluded 分层保存；
- `graph_edges=6,627,625` 与经过物理门后的 `physical_graph_edges=11,306` 分开；
- graph path 只作为候选证据，不直接产生 formal bridge accept；
- identity/date 跨 slice 分配采用强约束，避免同组被不同 slice 拆开。

### 4.3 Stage3 v12/v13 验证改造

- v12 从 aggregate-only 变成 raw sequence case bank + row-level truth；
- 新增 block/point outlier、reverse、swap、random order、continuous gap、receiver-time bias 等 corruption；
- 新增 domain-matched 和 same-identity hard negatives；
- v13 为 bridge 单独建立 edge/path posterior、Platt calibration、physical gates 和 locked-test；
- 修复 no-bridge retention 被误计入 bridge acceptance 的指标错误；
- 加入 `gap <=1800 s` 通用 formal gate；
- 修正 identity normalization，例如去除机尾号连字符，保证 `B-1353` 与 `B1353` 在跨阶段语义一致。

### 4.4 Stage5 v6/v7 改造

- v6 引入 HMM/Viterbi、partial alignment 和 mixture 语义；
- v7 采用 audit-first，只审计 `20` 个 v6 mixture、`4` 个 near-pass partial 和 `5` 个 stitched-track cases，共 `29` 个 batch；
- 先冻结 Stage5 v5 的 `198/251` 和 v6 的 `205/274`，新增结果必须无 overlap、可回退；
- 对 2 行批次允许只保留 1 行，但 drop 行仍记录在 partial diagnostics，不进入 match 产品；
- 用 v12 frozen gate、物理门、batch-end upper bound 和 posterior 门联合决定 accept。

### 4.5 Stage4/背景工程改造

- Stage4 v3 从单常数 confidence 改为四核心组件、T1/T2a/T2b/T3/T4 分层；
- GFS 下载、层级补齐到 `100 hPa`、200/200 frame 完成背景体检；
- GFS 只进入 report-only weak background 诊断，不直接改写 official OI 结果；
- CMA/CRA40 只作为 display-only 或大尺度参考；
- 12 km cutoff 作为业务敏感性分支，不替代全高度 official baseline。

### 4.6 工程可复现与空间控制

- 所有正式运行采用 `run_config.json`、质量门 JSON、per-slice reports、compact diagnostics 和 Parquet 输出；
- smoke、plan、optimized 三类目录明确区分；
- 采用 25-slice、25-worker 和 audit-only candidate scope；
- 全量 Stage2 结果不复制 25 份原始数据，仅写 compact outputs；
- 旧版本 accepted 集合作为 regression protection，新增集合必须无重叠且可回退。

---

## 5. 整体技术链路与执行流程（输入 → 处理 → 优化模块 → 输出）

```text
原始输入
  ├─ AMDAR batch wind observations
  ├─ ADS-B position/altitude/time/identity points
  ├─ radar frame / background field inputs
  ├─ aircraft strict holdout labels
  └─ independent GFS forecast candidate
        │
        ▼
Stage0 基线冻结与确定性检查
        │
        ▼
Stage1 AMDAR/风值/单位/时间语义 QC
  ├─ batch-time semantics
  ├─ strict/support role
  ├─ confidence components
  └─ time uncertainty
        │
        ├──────────────────────────────┐
        ▼                              ▼
Stage2 v8 ADS-B QC/track graph      Stage3 pseudo case bank
  ├─ local consistency               ├─ synthetic corruption
  ├─ clean tracklets                 ├─ hard negatives
  ├─ covariance smoother             ├─ Drop-DTW v12
  ├─ physical graph edges            └─ bridge validation v13
  └─ graph paths/prior                         │
        │                                      ▼
        └────────────── candidate prior + calibrated posterior
                              │
                              ▼
Stage4 confidence / role split / background diagnostics
  ├─ T1/T2/T3/T4 support tiers
  ├─ GFS weak background
  ├─ CMA display-only branch
  └─ Stage4 strict aircraft holdout evaluation
                              │
                              ▼
Stage5 real AMDAR–ADS-B matching
  ├─ v4 legacy exact baseline
  ├─ v5 candidate expansion
  ├─ v6 HMM/Viterbi
  ├─ v7 calibrated partial
  └─ future v8 graph audit
                              │
                              ▼
Stage6 time uncertainty / support weighting / sensitivity
                              │
                              ▼
最终输出
  ├─ strict aircraft-holdout metrics
  ├─ support-only observations
  ├─ unique matches
  ├─ mixture/partial diagnostics
  ├─ rejected/unmatched batches
  ├─ reconstructed 3-D u/v wind field
  └─ auditable reports and quality gates
```

### 5.1 当前已完成链路

当前已经实质完成的是：

`Stage1 semantic QC → Stage2 v8 track graph prior → Stage3 v12/v13 validation → Stage4 v3 confidence → Stage5 v7 calibrated partial matching`。

当前尚未完成的是：

`Stage5 v8 graph matching 全量正式 merge → Stage6 全链路 sensitivity → official constrained OI/最终风场增益封口`。

---

## 6. 参考资料与基线版本（论文、开源仓库、基线模型、原始工程版本）

### 6.1 工程内参考资料

以下文件是当前最重要的工程内方法学和交接依据：

1. `workflow/centralized_v1_docs/new_window_project_handover_20260529/centralized_v1_ultimate_summary_20260626.md`：原始 centralized_v1 主线、背景独立性、Stage4 baseline、GFS/CMA 定位。
2. `workflow/centralized_v1_docs/new_window_project_handover_20260529/stage1_to_stage4_pipeline.md`：Stage1–Stage4 输入、输出和正式评估链路。
3. `优化/teacher_reports/amdar_unified_implementation_plan_20260701.md`：统一 Stage1–Stage14 实施方案、分级体系和风险边界。
4. `优化/数据处理/amdar_stage2_to_6_optimization_plan_20260706.md`：Stage2–Stage6 优化目标、质量门、回退机制和实验计划。
5. `优化/数据处理/stage2_v8_track_graph_plan_20260716/stage2_v8_track_graph_full_implementation_plan_20260716.md`：Stage2 v8 完整实现规范。
6. `优化/数据处理/stage2_stage3_folders_and_results_explanation_20260720.md`：最新 Stage2/Stage3 目录、文件、结果和授权边界总说明。

### 6.2 算法类别参考

当前代码实现对应的公开方法类别包括：

- HMM/Viterbi：用于带顺序约束的序列状态选择；
- Drop-DTW/单调动态规划：用于部分序列匹配和异常行剔除；
- Kalman/IMM-style smoother：用于带协方差的运动状态平滑；
- graph-based trajectory stitching：用于 tracklet 之间的物理可达连接；
- Platt/calibration/ECE：用于 posterior 概率校准；
- optimal interpolation / background-plus-observation：用于最终三维风场重构诊断；
- strict aircraft holdout：用于防止训练、匹配或背景数据泄漏到官方评估。

本次汇总没有把未在当前工程目录中锁定版本号的外部论文或仓库写成唯一依赖；正式复现实验应以运行配置、代码文件、输入/输出路径和 JSON quality gate 为准。

### 6.3 基线版本演进

| 版本 | 主要作用 | 当前定位 |
|---|---|---|
| centralized_v1 Stage4 `tp26_thr11_preserve` | 官方三维风场 baseline | 正式精度比较基线 |
| Stage2 v4/v7 legacy | 旧 ADS-B QC/identity prior | 回退与兼容基线 |
| Stage5 v4 | strong exact identity matching | 最早安全匹配基线 |
| Stage5 v5 | candidate expansion + tiny-leg 修复 | `198/251` 冻结安全基线 |
| Stage5 v6 | HMM/Viterbi | `205/274` prior |
| Stage5 v7 | calibrated partial | 当前最新真实匹配结果 `229/345` |
| Stage2 v8 | clean tracklet + graph prior | 当前最新正式 ADS-B 轨迹结果 |
| Stage3 v12 | Drop-DTW partial validation | Stage5 partial 安全依据 |
| Stage3 v13 | bridge/path locked-test | Stage5 graph bridge 安全依据 |

---

## 7. 最新实验结果（量化指标、对比基线、收敛情况、推理速度、精度、误差）

### 7.1 最新结果判定

按时间和正式性排序：

1. **2026-07-20：**Stage2/Stage3 文件夹与结果总说明，确认正式结果和 Stage5 v8 授权边界。
2. **2026-07-17：**Stage3/Stage5/Track Graph 周报，汇总 v7、v8、v13 联动结论。
3. **2026-07-16：**Stage2 v8 全量、Stage3 v13 locked-test、Stage5 v7 audit-first 正式产物。
4. **2026-07-08：**Stage4 confidence v3 和背景诊断结果。

### 7.2 Stage2 v8 正式全量结果

| 指标 | 结果 |
|---|---:|
| 输入点数 | `19,162,638` |
| local consistency 输出点数 | `19,162,638` |
| clean tracklet 点数 | `19,154,894` |
| diagnostic excluded 点数 | `7,744` |
| legacy-compatible legs | `2,977,478` |
| v8 clean tracklets | `2,953,850` |
| singleton tracklets | `234,439` |
| 原始 candidate graph edges | `6,627,625` |
| physical graph edges | `11,306` |
| graph paths | `2,965,156` |
| formal Stage2 bridge accepts | `0` |
| fragmentation reduction | `23,628` 个 |
| fragmentation reduction fraction | `0.7936%` |
| point conservation | 通过 |
| Stage2 formal bridge invariant | 通过 |
| identity/date 跨 slice 违规 | `0` |

解释：Stage2 的成功标准不是“把所有 fragments 都拼起来”，而是点不丢、碎片不恶化、物理候选生成、跨 slice 语义不泄漏且不越权接受 bridge。`11,306` 条 physical edges 是 prior，不是 `11,306` 个可直接 merge 的 unique 结果。

### 7.3 Stage3 v13 bridge locked-test 结果

| 指标 | Locked-test 结果 | 质量门 | 状态 |
|---|---:|---:|---|
| selected base tracklets | `15,000` | - | 完成 |
| case bank | `151,951` | - | 完成 |
| calibration cases | `80,971` | - | 完成 |
| validation cases | `28,381` | - | 完成 |
| locked-test cases | `27,599` | - | 完成 |
| wrong-tracklet/path rate | `0.0827%` | `<=1%` | 通过 |
| catastrophic bridge rate | `0.0645%` | `<3%` | 通过 |
| edge posterior ECE | `0.000321` | `<=0.05` | 通过 |
| path posterior ECE | `0.000321` | `<=0.05` | 通过 |
| max corruption false acceptance | `0.8621%` | `<=2%` | 通过 |
| same-identity wrong-tracklet | `0.8621%` | `<=1%` | 通过 |
| unreachable bridge | `0%` | `<=0.5%` | 通过 |
| clean no-bridge retention | `100%` | 不明显退化 | 通过 |
| truth/holdout violations | `0` | `0` | 通过 |

Stage3 v13 的 `0.8621%` 最大误接纳来自 locked-test 中最难的 corruption/hard-negative 子类，并不等同于真实全量 Stage5 的错误率；它证明的是 bridge policy 在验证分布上的安全边界。

### 7.4 Stage3 v12 Drop-DTW 结果

- sequence cases：`25,004`；
- row-level truth：`163,461`；
- locked selected：`7,347`；
- catastrophic rate：`0.0602%`，低于 `<3%` 门；
- posterior ECE：`0.000361`，低于 `0.05` 门；
- domain-matched wrong leg locked evaluations：`4,760`，误接纳 `0`；
- quality gate 全部通过。

该结果支撑 Stage5 v7 的 partial row exclusion，但不代表所有真实 AMDAR 行都可以安全地窄化到 ADS-B 时间点。

### 7.5 Stage5 真实 AMDAR–ADS-B 匹配演进

| 版本 | Unique batches | Matched rows | 说明 |
|---|---:|---:|---|
| Stage5 v4 | `86` | `118` | strong exact identity |
| Stage5 v5 | `198` | `251` | 修复候选 scope、micro/tiny 分支 |
| Stage5 v6 | `205` | `274` | HMM/Viterbi 新增 `7` batches、`23` rows |
| Stage5 v7 | `229` | `345` | 新增 `24` batches、`71` rows |

Stage5 v7 相对 v5：

- unique batches 增加 `31`，提升 `15.66%`；
- matched rows 增加 `94`，提升 `37.45%`；
- 相对 v6 增加 `24` unique batches，提升 `11.71%`；
- `20/20` v6 mixtures 通过 v12 calibrated partial gate；
- `4/4` near-pass partial cases 通过；
- `0/5` stitched-track cases 通过，全部继续 rejected，说明没有越过未验证 bridge 边界；
- 若以原始 `56,521` AMDAR batches 为分母，最终 unique batch rate 约 `0.405%`，仍低于旧计划 `1%` 目标（约 `566` batches）。

Stage5 v7 新增批次的关键分布：matched fraction 最小/中位数/最大约为 `0.50/0.50/0.75`，q90 为 `0.70`；所有新增结果满足 exact identity、posterior、cross-track、vertical、sampling gap、batch-end upper bound、leave-one-out stability 等联合门。

### 7.6 Stage4 confidence v3 结果

| 指标 | 结果 |
|---|---:|
| 总 scored rows | `431,189` |
| AMDAR rows | `431,008` |
| TURB rows | `181` |
| T0 | `175`（TURB strict truth） |
| T1 | `45,818` |
| T2 | `210,537` |
| T3 | `123,358` |
| T4 | `51,301` |
| AMDAR T1+T2 coverage | `59.478%` |
| T2a direct support candidate | `117,916` |
| high-wind retained | `3,018 / 4,505` |
| AMDAR strict truth rows | `0` |
| AMDAR holdout rows | `0` |
| quality gate | 全部通过 |

### 7.7 背景与风场 baseline 结果

- 全高度 baseline vector RMSE：`14.7690`；
- 工程 proxy floor：`11.1126`；
- baseline 与 proxy floor 的差距：`3.6564 m/s`；
- `<12 km` baseline vector RMSE：`9.4552`；
- `12 km+` baseline vector RMSE：约 `19.9177`；
- `12 km+` 点数占比约 `41.89%`，但贡献 SSE 约 `76.18%`；
- GFS：`178/178` unique source、`200/200` frame、`failed_count=0`，21 层至 `100 hPa`，顶层约 `15.80 km`；
- GFS OI 诊断：可做 weak/diagnostic background，但尚未证明可以直接改善 official OI；
- CMA：6 个代表帧 display-only low-confidence fill 已跑通，填充比例约 `97.72%–98.49%`，均值约 `98.16%`，display confidence 上限 `0.20`；full-200 official pairwise 封口未完成。

### 7.8 收敛、速度和精度说明

- **收敛：**Stage3 v12/v13 的 calibration/validation/locked-test 均完成，posterior ECE 极低且 quality gate 全过；Stage2/Stage5 不存在需要继续训练的大模型收敛问题，主要是候选安全门和真实 coverage 限制。
- **并行速度口径：**正式 Stage2/Stage5 配置使用 `25` workers、`POLARS_MAX_THREADS=25`、25 slices；工程采用 compact audit-first 输出以控制磁盘/内存。当前文件未形成跨版本统一 wall-clock benchmark，因此不能捏造一个全链路秒数。
- **精度：**Stage3 的错误率/ECE 是验证集指标；Stage5 真实数据没有 point-truth，因此 `229/345` 是安全 support matching 数量，不是“真实匹配精度”；最终风场精度仍必须以 strict aircraft holdout RMSE/MAE 评估。
- **误差主因：**Stage5 剩余拒绝主要来自真实空间几何不一致，而不是单纯 no-candidate。Stage5 v5 统计中 `best_cost_gt_3` 为主要拒绝原因，其次为 Stage4 T4、monotonic violation、no candidate、batch-end projection 等。

---

## 8. 结果深度分析（优势、未解决缺陷、边界问题、失效场景）

### 8.1 已验证优势

1. **安全性显著提升：**Stage2、Stage3 v12/v13、Stage4 v3、Stage5 v7 的 truth/holdout 违规均为 `0`。
2. **数据语义清晰：**strict truth、support-only、mixture、partial、bridge、rejected 已分开，避免下游误用。
3. **轨迹证据更完整：**Stage2 v8 保持点守恒，并将物理可达 graph edge 从碎片化 ADS-B 中显式提取出来。
4. **部分匹配有效释放利用率：**Stage5 v7 在不放宽安全边界的前提下，从 `198/251` 增至 `229/345`。
5. **posterior 可解释和可审计：**Stage3 v12/v13 保存 case bank、row-level diagnostics、edge/path posterior、corruption report 和 quality gate。
6. **工程可扩展：**25-slice + audit-first + compact outputs 避免全量候选复制，适合继续做 Stage5 v8 小集合实验。

### 8.2 尚未解决的核心缺陷

1. **真实覆盖不足：**unique batch rate 约 `0.405%`，距离旧 `1%` 目标仍有差距；继续放宽阈值不能解决没有同日期/同航班 ADS-B 的问题。
2. **graph bridge 还未接入真实 unique：**Stage2 的 `11,306` physical edges 只是 prior；Stage3 v13 通过 locked-test 也不证明每个真实 batch bridge 都可靠。
3. **Stage2 运动模型仍简化：**当前不是完整 CTRV/IMM/RTS，对机场附近急转弯、快速爬升/下降、非匀速和稀疏采样仍可能失配。
4. **AMDAR 时间仍是分布而非点真值：**即便 partial matching 通过，也只能产生 support-only 时间证据。
5. **高空 representation error：**12 km+ 对整体 SSE 贡献大，是风场误差地板的重要来源；低空改善不能直接推断全高度改善。
6. **背景独立性和 OI 增益未封口：**GFS 已可用于诊断，但 constrained OI 的 official holdout 增益尚未完成；CMA 不能作为已证明独立背景。
7. **Stage6 尚未完成：**Stage5 v7 仅说明可以进入 target branch，尚未证明新 support seeds 对最终风场和 strict holdout 有净收益。

### 8.3 边界问题与失效场景

- 大时间 gap 超过 `1800 s` 的 bridge：必须拒绝，不能用平滑轨迹强行连接。
- 同机尾同日期多个航班/tracklet：identity exact 不足以保证 path 唯一，需要 same-identity hard negative 检查。
- competing fork path：可能产生高 posterior 但错误路径，必须使用 path margin 和 bridge-specific calibration。
- 接收空洞导致真实轨迹不可见：没有 evidence 时应输出 rejected/no coverage，而不是插值成 observed point。
- 单行或两行 AMDAR 批次：partial accept 的信息量低，必须单独做 Stage6 sensitivity，不能和完整序列等价。
- 高空快速变化和垂直风突变：当前 constant-velocity/diagonal covariance 模型可能低估模型误差。
- Stage3 pseudo 分布与真实 AMDAR 分布不匹配：locked-test 通过只能证明指定 corruption/domain，不是无限外推保证。
- 将 mixture 改名为 unique、把 interpolated graph state 改名为 observed ADS-B、把 estimated time 改成 strict point truth，均属于明确禁止的语义越权。

### 8.4 为什么当前不能直接宣布“全链路优化完成”

当前已经完成的是**关联安全与工程准备阶段**，还没有完成最终风场收益封口。原因是：

1. Stage5 v7 的 matched rows 不是独立 point truth；
2. Stage2/Stage3 的 bridge 结果还未经过真实 Stage5 v8 unique/mixture/reject 三层产品审计；
3. Stage6 尚未证明 support-only seeds 改善 strict holdout；
4. GFS/CMA background 尚未完成 official constrained OI pairwise 评估；
5. 全高度 baseline 的主要误差由高空与 representation error 主导，单纯增加匹配数量未必降低 RMSE。

---

## 9. 当前工程完整进度状态

### 9.1 总体状态矩阵

| 模块 | 状态 | 当前结论 |
|---|---|---|
| Stage0 基线/确定性 | 基本完成 | 已有 baseline、环境和质量门体系 |
| Stage1 AMDAR QC/时间语义 | 已完成一轮正式修正 | batch-time 语义已保守纳入，支持/真值边界清晰 |
| Stage2 v7 legacy QC | 已有兼容结果 | 作为 prior/回退，不是最新主创新 |
| Stage2 v8 track graph | **正式达标** | 19.16M 点全量，11,306 physical edges，0 formal accepts |
| Stage3 v8/v11 association validation | 已完成并被继承 | 为 matching posterior 提供冻结 policy |
| Stage3 v12 Drop-DTW | **正式达标** | partial row exclusion locked gate 通过 |
| Stage3 v13 bridge validation | **正式达标** | 全部 locked-test hard gates 通过 |
| Stage4 confidence v3 | **正式达标** | T1/T2 分层、连续不确定性、AMDAR T0/holdout 为 0 |
| Stage4 GFS background | 诊断完成 | 可 weak/diagnostic，official OI 未封口 |
| Stage4 CMA branch | display-only 完成 | 不放行 official independent OI |
| Stage5 v4/v5 | 已冻结 | `198 batches / 251 rows` 安全基线 |
| Stage5 v6 HMM/Viterbi | 已完成 | `205 batches / 274 rows` prior |
| Stage5 v7 calibrated partial | **正式达标** | `229 unique batches / 345 rows`，safety gate 通过 |
| Stage5 v8 graph matching | **尚未全量开始** | 只授权小集合 audit |
| Stage6 time uncertainty | 规划/待执行 | 需 S0–S4 sensitivity |
| constrained official OI | 未封口 | 需 GFS weak background + strict holdout pairwise |
| 最终全高度风场提升 | 未证明 | 不能由 Stage5 匹配数量直接推断 |

### 9.2 当前可交付成果

- 可复现的 Stage2 v8 全量 track graph 产品；
- 可复现的 Stage3 v12/v13 validation/calibration/locked-test 产品；
- Stage4 v3 confidence compact table；
- Stage5 v7 `amdar_adsb_match_v7.parquet`、candidate scores、batch diagnostics、partial-row diagnostics；
- GFS background verification 和 OI report-only diagnostics；
- 完整的质量门、回退、交接和目录解释文档。

### 9.3 当前尚不可宣称的结论

- 不能说 `11,306` 条 physical graph edges 已经全部成为可信 unique match；
- 不能说 `229/345` 已达到 `1%` 利用率目标；
- 不能说 AMDAR 已经是 strict truth 或 holdout；
- 不能说 GFS 已经改善 official OI；
- 不能说高空 `12 km+` 误差已被解决；
- 不能说最终风场 RMSE 已因 Stage5 v7 单独改善。

---

## 10. 下一步迭代方向、优化方案、实验计划、预期指标

### 10.1 P0：Stage5 v8 graph matching 小集合审计

**目标：**先验证 graph prior 在真实 AMDAR 上是否带来安全、可解释、可回退的增量，而不是直接全量 merge。

**第一批实验集合：**

1. 历史 `5` 个 stitched cases；
2. graph-recoverable rejects；
3. same-identity hard negatives；
4. Stage5 v7 `229/345` prior regression set；
5. covariance-normalized emission ablation；
6. unique / mixture / rejected 三层产品输出。

**实施要求：**

- 读取 Stage2 covariance、mean/scale、mode probability；
- 读取 Stage3 v13 edge/path posterior 和 calibration 参数；
- 同时施加 Stage3 v12 partial gate、batch-end upper bound、exact identity、path margin 和 gap `<=1800 s`；
- 任何 graph interpolation 只能是 support/bridge state，不是 observed ADS-B point；
- 输出必须保留 rejection reason、candidate ranking、posterior、path stability 和 source role。

**建议验收指标：**

- frozen Stage5 v7 `229/345` 100% regression 保留；
- 新增 safe unique 至少 `+3` 才考虑形成正式增量；
- mixture 单独统计，不计入 unique；
- graph bridge false acceptance 不得超过 Stage3 v13 locked gate 对应边界；
- truth/holdout/time-point-truth violations 必须保持 `0`；
- 5 个 stitched historical cases 若仍大部分 rejected，应明确归因于 no coverage/physical mismatch，而不是继续放宽门。

### 10.2 P0：Stage6 strict aircraft holdout sensitivity

设计四组至少实验：

| 分支 | 内容 | 目的 |
|---|---|---|
| S0 | Stage5 v7 baseline | 固定比较基线 |
| S1 | 仅加入 full-sequence unique | 测试完整匹配净收益 |
| S2 | 加入 partial accepted rows | 测试 drop 行策略影响 |
| S3 | 加入 graph unique/mixture 分层 | 测试 graph 证据影响 |
| S4 | 高空/低空、风速 regime、tail/region 分层 | 定位收益边界 |

**必须报告：**strict holdout vector RMSE/MAE、u/v 分量误差、12 km cutoff、风速分位数、飞机类型/区域/时间段、支持点密度、影响半径、观测权重和退化样本数。

**预期指标：**不是预先承诺固定 RMSE 降幅，而是要求新分支相对 S0 在主要 holdout 总体和关键高空子集不退化，并能解释任何局部退化。只有通过这一关，graph matching 才能升级为正式下游输入。

### 10.3 P1：协方差和运动模型增强

当前 smoother 是 diagonal constant-velocity IMM-style，建议按风险可控顺序迭代：

1. 先做 covariance-normalized emission：比较欧氏距离与 Mahalanobis-like 代价；
2. 再加入垂直运动状态和 mode-specific process noise；
3. 对机场附近高转弯/爬升/下降样本建立 regime-specific validation；
4. 只有 validation recall 明显改善、locked safety 不退化时，再尝试完整 CTRV/IMM/RTS；
5. 每次模型升级保留 Stage2 v8 输出作为 fallback。

**预期指标：**physical edge recall 提升、same-identity wrong-tracklet 不上升、unreachable bridge 仍接近 `0%`、point conservation 和跨 slice identity/date 违规仍为 `0`。

### 10.4 P1：真实 ADS-B 覆盖扩展，而非继续调阈值

若项目目标仍是 `>=1%` unique batch rate，需要改变候选宇宙：

- 增加相同日期、同机尾、同航班和空间区域的原始 ADS-B 数据源；
- 评估 ADS-C、其他接收源或更完整历史轨迹；
- 基于新原始证据重新生成 service date/flight identity；
- 重新跑 Stage2 leg construction、Stage3 v12/v13 locked validation 和 Stage4 confidence；
- 禁止用扩大 cross-track、放宽 best cost、取消 monotonic 或忽略 batch-end 上界来凑 `1%`。

**预期指标：**候选覆盖率和 no-candidate 比例真实改善；若 acceptance 仍被 `best_cost_gt_3` 主导，则说明问题是空间几何不一致，应继续扩展数据而不是调分数。

### 10.5 P1：GFS constrained OI 小步实验

建议建立三个严格分支：

1. `B0`：当前 official baseline；
2. `B1`：GFS weak background + 不加入新 AMDAR；
3. `B2`：GFS weak background + 仅 Stage5 v7 high-confidence support；
4. `B3`：GFS weak background + Stage5 v8 graph unique/mixture 分层。

每个分支都必须使用完全独立的 strict aircraft holdout，报告 background-only、OI-only、support-only 和 combined 的误差；CMA 只做 display-only 对照，不得把更接近真实的再分析误认为独立背景。

**预期指标：**B1/B2/B3 至少在主要 holdout 指标不劣于 B0；如无改善，应保留 report-only 结论，不强行写入 official pipeline。

### 10.6 P2：高空专项与 representation error

针对 `12 km+`：

- 单独建立高空 process noise 和 observation error prior；
- 对温度、垂直速度、风速 regime 做分层；
- 比较 full-height 与 `<12 km` 两套 baseline/gate；
- 将高空误差拆成 background error、observation representation error、time uncertainty 和 spatial support error；
- 不把 `<12 km` 的改善宣传成全高度改善。

**预期指标：**至少识别主要误差来源和可控项；在没有高空严格证据时，保持高空结果为风险诊断，不放宽 acceptance。

### 10.7 推荐实验记录模板

每次正式运行新增以下文件：

```text
run_config.json
input_manifest.json
code_commit_or_hash.txt
quality_gate.json
global_metrics.json
slice_reports/*.json
candidate_diagnostics.parquet
accepted_unique.parquet
accepted_mixture.parquet
rejected_diagnostics.parquet
holdout_metrics.csv
result_analysis.md
```

并强制记录：

- 输入文件和代码 hash；
- slice/workers/thread 配置；
- 参数变更表；
- 新增/回退 batch 数；
- truth/holdout invariants；
- runtime、峰值内存和磁盘占用；
- 失败原因 top-k；
- 与冻结 baseline 的逐项差分。

### 10.8 近期可执行顺序

```text
1. 冻结 Stage5 v7 229/345 regression set
2. 实现并运行 Stage5 v8 graph 小集合 audit
3. 通过 safety + utility gate 后扩展 candidate scope
4. 运行 Stage6 S0-S4 strict aircraft holdout sensitivity
5. 完成 GFS constrained OI B0-B3 对照
6. 对 12 km+ 做 representation-error 分层
7. 只有最终 holdout 不退化且收益可解释，才合并正式 pipeline
```

---

## 总结结论

截至 2026-09-11，`centralized_v1` 已从“稀疏飞机风场重构 + 低利用率匹配”推进到一条**数据语义明确、质量门完整、轨迹 graph 可审计、partial matching 可验证**的工程主线。最新正式结果是：Stage2 v8 全量处理 `19,162,638` 个 ADS-B 点并生成 `11,306` 条 physical graph edges；Stage3 v13 在 `27,599` 个 locked cases 上通过全部 bridge safety gates；Stage5 v7 在保持 `0` 条 truth/holdout 违规的前提下达到 `229 unique batches / 345 matched rows`；Stage4 v3 完成 confidence 分层并保持 AMDAR strict truth/holdout 为 `0`。

但项目尚未完成最终科学闭环：真实 unique batch rate 仍约 `0.405%`，graph edge 仍是 prior，Stage6 和 constrained official OI 尚未封口，高空 `12 km+` representation error 仍是主要瓶颈。因此最正确的当前判断是：

> **Stage2/3/4/5 v7 的安全工程优化已经达标；Stage5 v8 graph 小集合审计具备进入条件；最终三维风场精度和全量利用率提升仍需通过 Stage6 strict aircraft holdout 与 GFS constrained OI 实验验证，不能提前宣称完成。**

---

## 11. 面向普通人的逐章解读

这一章不增加新的实验结论，目的是把前 10 章翻译成不需要气象、机器学习或数据工程背景也能理解的语言。可以把整个项目想成：**天空中有很多飞机，但真正报告风的飞机很少；工程要根据飞机的位置、速度、时间和周围资料，尽量恢复某个时刻、某个高度的风场，同时不能把猜测写成真实观测。**

### 11.1 第 1 章：项目到底要做什么

项目不是单纯“预测天气”，也不是单纯“找两张表中相同的飞机”。它有三件事同时发生：

1. 把飞机报告的风速和风向转换成数学上可以计算的东西；
2. 判断这条风报告到底对应哪架飞机、哪段 ADS-B 航迹；
3. 把稀疏的点整理成可供三维重构使用的风场，并用严格留出的飞机检查结果。

普通类比是“拼地图”：AMDAR 像少量人工测温点，ADS-B 像飞机走过的脚印，雷达像时间框架，GFS/CMA 像一张较粗的背景地图，strict holdout 像考试时暂时遮住的答案。算法可以使用脚印和背景地图，但不能偷看被遮住的答案。

机器可读定义中的 `support-only` 意味着“可以帮助判断或重构，但不能被当作官方真值”；`strict truth` 意味着“可以作为最终评价答案”。这两个角色必须一直分开。

### 11.2 第 2 章：为什么不能直接把所有数据扔进模型

数据量大不代表信息一定可靠。项目面对的困难可以分成四类：

| 普通说法 | 工程含义 | 直接后果 |
|---|---|---|
| 时间标签不完全是真实采样时刻 | AMDAR 常带 batch end/dissemination 语义 | 同一批点可能被错误地当成同一时刻的逐点真值 |
| 飞机脚印中间会断 | ADS-B 接收有空洞，或异常点触发断航段 | 一架飞机被切成多个短 tracklet |
| 同一个身份可能对应多个竞争航段 | identity/date 不能保证唯一空间路径 | 最近邻可能接到错误航段 |
| 背景场比较平滑 | GFS/CMA 不一定代表局地真实风 | 低置信背景可能掩盖局地结构 |
| 高空样本和局地样本都有限 | 12 km 以上支持更稀疏、误差更大 | 全高度平均数可能掩盖高空失效 |

所以优化动机不是“把阈值放宽，让接受数看起来更多”，而是先回答：**这条数据的时间、空间、身份和可信度是什么？**只有回答清楚，接受数量增加才有意义。

### 11.3 第 3 章：算法为什么这样设计

算法的核心是三道门：

1. **物理门：**飞机不可能在很短时间内瞬移很远，也不可能无缘无故出现极大的高度跳变；
2. **序列门：**一批 AMDAR 行应沿一条飞机航迹按时间向前走，而不是每一行独立找最近点；
3. **证据门：**即使一条连接在物理上看起来可能，也要经过独立的 validation/calibration/locked-test 才能成为可接受结果。

用数学语言说，单条候选路径的代价通常包含位置差、速度差、垂直差、时间差和轨迹不连续惩罚。路径模型会在满足时间单调性的候选中寻找低代价路径；`posterior` 再把路径分数校准成“这条路径可信的概率”。这里的概率不是凭感觉加的，而是用独立构造的正例、负例和 corruption case 校准。

风的物理分量也必须与飞机运动分开。气象风向通常表示“风从哪里来”，因此使用：

```text
u_wind = - speed * sin(direction)
v_wind = - speed * cos(direction)
```

而飞机地速和航向属于运动信息：

```text
u_motion = ground_speed * sin(heading)
v_motion = ground_speed * cos(heading)
ground_vector = air_vector + wind_vector
```

不能因为 ADS-B 记录了飞机向东飞，就说风向东；飞机的真实空速、航向和风矢量之间还需要独立气象观测或可靠运动模型约束。

### 11.4 第 4 章：代码和目录具体改了什么

本轮改造可以按模块理解：

| 模块 | 原来容易出错的地方 | 当前落地方式 |
|---|---|---|
| Stage1 | 时间、单位、异常高度混在一起 | 统一 UTC、单位、风的 u/v 分量，并保存原始语义字段 |
| Stage2 v8 | 旧 leg 边界过硬，异常点会切碎航迹 | local consistency + clean tracklet + covariance smoother + graph prior |
| Stage3 v12 | 一行异常导致整批拒绝 | Drop-DTW 允许在证据足够时丢弃局部坏行，但不修改 truth |
| Stage3 v13 | bridge 只靠物理距离，没有专门验证 | bridge/path 独立 case bank、calibration、validation、locked-test |
| Stage4 | 不同来源和不同置信度混用 | current/context 分层、严格 aircraft holdout、confidence tier |
| Stage5 v7 | 独立最近线段投影容易错序 | HMM/Viterbi、partial matching、unique/mixture/reject 分层 |
| OI/CMA/GFS | 展示填充可能被误认为官方精度 | display-only、report-only、background independence 单独记录 |
| PINN/field branch | 很小的平均改善可能伴随尾部变差 | validation 选 gate，locked test 检查尾部和轻风 guardrail |

关键参数不是越大越好。例如 Stage2 graph `max_graph_gap_s=1800` 只是允许寻找候选连接的最大时间范围；它不代表 1800 秒的连接都能正式接受。正式 bridge acceptance 在 Stage2 固定为 0，避免“候选范围”被误读为“已经确认”。

### 11.5 第 5 章：一条数据怎样走完整流程

用一条 AMDAR 记录作为例子：

```text
原始文件
  -> Stage1: 时间/单位/高度/风分量规范化
  -> Stage2: ADS-B 点做局部一致性检查，生成 clean tracklet 和 graph prior
  -> Stage3: 用伪造 corruption 和 hard negative 检查匹配方法是否容易犯错
  -> Stage4: 建立当前/上下文/置信度分层，并冻结 strict aircraft holdout
  -> Stage5: 对真实 AMDAR 批次做序列匹配、局部丢行和 partial gate
  -> Stage6: 只在严格留出飞机上评估是否真的改善风场
  -> 输出: unique、mixture、support-only、reject、诊断和质量报告
```

原始 `centralized_v1_output/` 还有一条较早的正式链路：Stage2 先为 `7,395` 个雷达时间窗生成多模态 voxel，Stage3 为相同的 `7,395` 个时间窗生成 ground-center payload，Stage4 在固定 `200` 个严格留出帧、`530` 个 holdout 点上评估。后来的优化链路则以更细粒度的 AMDAR/ADS-B 关联为重点。两条链路是前后继承关系，不应把 `7,395` 帧和 `19,162,638` 个 ADS-B 点当成同一种样本。

### 11.6 第 6 章：结果和哪些基线比较

报告中有四类“基线”：

1. **数据工程基线：**Stage1、原始 Stage2/Stage3 的 schema 和 `7,395` 时间窗一致性；
2. **风场重构基线：**纯 aircraft baseline，使用非 holdout 飞机观测；
3. **局地重构候选：**TimePower15、adaptive v3、tp26、S4A downweight；
4. **关联算法基线：**Stage5 v5 的 `198 batches / 251 rows`，以及 v6/v7 的递进结果。

GFS、CMA/CRA40、PINN 不是自动更高级的“真值”。GFS 是独立背景候选，CMA/CRA40 更接近再分析/分析参考，PINN 是 report/field branch。它们必须按照证据等级使用。

### 11.7 第 7 章：到底有没有变好

回答要分成三种“变好”：

- **安全性变好：**Stage3 v13 locked-test 所有硬门通过，truth/holdout 违规为 0；
- **可用数量变好：**Stage5 v5 到 v7 从 `198/251` 增至 `229/345`，但整体 batch rate 仍只有约 `0.405%`；
- **风场误差变好：**Stage4 的 tp26/TimePower15 在固定 200 帧基线实验中比纯 aircraft baseline 更好，但 OI、CMA、PINN 新分支尚未形成可以替换 official baseline 的闭环。

这三种改善不能相互替代。匹配数增加不自动等于风场 RMSE 下降；RMSE 下降也不自动说明新数据没有泄漏；一个诊断分支的显示覆盖率增加，更不代表官方预测精度增加。

### 11.8 第 8 章：为什么结果仍不完美

当前最大的限制来自真实信息缺失，而不只是模型能力：

- 许多 AMDAR batch 没有足够的同身份、同日期、同空间 ADS-B 支持；
- ADS-B 的中位 tracklet 很短，轨迹 graph 只能恢复一部分“被异常点切断”的连接；
- 高空 `12 km+` 的误差和代表性误差更大；
- 时间标签是 batch 级而非逐点级，导致理论上存在不可消除的时间错配；
- CMA/GFS 的空间覆盖很好，但大尺度平滑背景可能伤害局地结构；
- 严格 acceptance 保守，因此“接受率低”部分是安全策略的结果，不应简单视为程序失败。

### 11.9 第 9 章：工程现在处在哪一站

当前可以说“已完成”的是：Stage1 语义处理、Stage2 v8 全量 graph prior、Stage3 v13 bridge validation、Stage4 confidence v3、Stage5 v7 calibrated partial matching。当前不能说“已完成”的是：Stage5 v8 全量 graph merge、Stage6 strict aircraft holdout sensitivity、独立背景驱动的 official OI、稳定上线的三维场精度提升。

换句话说，项目已经从“能不能跑”进入“哪些证据能安全进入正式产品”的阶段，但还没有完成最终科学闭环。

### 11.10 第 10 章：下一步怎样做才不会走偏

下一步应先冻结 `229/345` regression set，再对 graph unique、graph mixture 和 rejected 三类 separately audit。每个实验都要有固定输入清单、代码 hash、参数、输出 manifest、holdout metrics 和失败原因统计。只有在严格留出误差不恶化、尾部风险不新增、支持观测语义不越权时，才允许从 audit 进入更大规模。

---

## 12. 数据集全景、数据字典与优缺点对比

### 12.1 数据集总表

| 数据集/产品 | 规模或覆盖 | 主要内容 | 在工程中的角色 | 优点 | 缺点与限制 |
|---|---:|---|---|---|---|
| `clean_wind.parquet` | `431,189` 行 | AMDAR `431,008` + TURB `181` | Stage1 风观测输入 | 有真实风速/风向，能提供气象量 | AMDAR 多为 batch time；同批重复时间不能直接当逐点 truth |
| AMDAR | `431,008` 行 | 飞机报告风 | support-only | 数量最大，直接含风信息 | 最新有效策略下 `effective_strict_truth=0`，不能直接做 strict holdout |
| TURB | `181` 行，其中 `175` 条可用、`6` 条高度审查 | 湍流/相关飞机观测记录 | Stage1 质量审计/辅助输入 | 可以帮助识别高空和质量分层 | 样本小，缺失与高度异常比例相对显眼，不能代表全部 AMDAR |
| `clean_loc.parquet` | `19,162,638` 行 | ADS-B 位置、时间、高度、地速、航向 | 轨迹证据 | 点数极大，能重建飞机运动路径 | 不是风真值；接收断点、异常跳点和短碎片很多 |
| 雷达索引 | `7,396` 个文件，`7,395` 个可用时间窗 | 雷达文件和时间窗 | 给 Stage2 多模态网格提供时间框架 | 时间覆盖清楚，可组织逐 6 分钟帧 | PNG/强度不是 Doppler 风速；不能直接当风真值 |
| Stage2 原始 voxel | `7,395` 帧，网格约 `31 x 525 x 775` | 当前窗、上下文窗、飞机/风/雷达角色 | 组织数据，不负责最终重构 | 时间窗和空间网格统一 | 空间覆盖稀疏，voxel 非法填充不能当观测 |
| strict aircraft holdout | `200` 帧、`530` 点 | 被遮住的飞机风标签 | 官方 Stage4 评价 | 评价最接近真实产品目标 | 数量远小于原始 ADS-B，且分层后高空/尾部不均衡 |
| Stage3 pseudo case bank | v12 `25,004` cases / `163,461` row labels；v13 `151,951` cases | 人工 corruption、hard negative、bridge case | 验证错误率与校准 | 可系统制造已知答案和危险场景 | 仍不是真实 AMDAR truth，分布依赖构造策略 |
| GFS | `178/178` 源文件，覆盖 `200/200` 帧，约 21 层至 100 hPa | 独立弱背景候选 | report-only / constrained OI 候选 | 覆盖连续，适合填补低支持区域 | 分辨率和大尺度平滑可能抹掉局地风；未完成 official blend 验证 |
| CMA/CRA40 | `773` 文件、约 `129` 时次 | 再分析/分析背景 | display-only / weak reference | 空间连续，便于可视化与背景诊断 | 与目标资料独立性未证明，不能直接当真值或官方独立背景 |
| Stage5 v7 accepted | `229` unique batches / `345` rows | 真实 AMDAR-ADS-B 关联结果 | support-only，可作为后续审计输入 | 有 exact identity、物理门和 posterior 约束 | 仅占原始 `56,521` batches 约 `0.405%`，覆盖仍低 |

### 12.2 规模图：不同数据不是同一种“样本”

下面只用于直观看量级，条形长度经过取整，不能替代表中精确数字：

```text
ADS-B clean_loc points       19,162,638 |##############################|
风观测 clean_wind rows          431,189 |#                             |
雷达可用时间窗                    7,395 |                              |
Stage4 holdout points              530 |                              |
Stage5 accepted unique batches    229 |                              |
```

解释：ADS-B 点最多，是“飞机走过哪里”的证据；风观测较少，是“飞机报告了什么风”的证据；holdout 更少，是“最终用来判分的答案”。不能因为 ADS-B 点数很多，就认为它们提供了同样多的风真值。

### 12.3 Stage1 数据质量图

```text
clean_loc 全部位置点       19,162,638 |##############################|
地速有限值                  17,143,292 |###########################   |
地速缺失                    2,019,346 |###                           |
clean_wind 全部风行             431,189 |#                             |
AMDAR                          431,008 |#                             |
TURB                               181 |                              |
```

地速缺失不等于位置点全部无效；它表示该点不适合直接做运动速度计算，需要保留位置证据并在后续模型中传播不确定性。Stage2 的 `diagnostic excluded=7,744` 也不是从原始证据永久删除，而是从 clean tracklet 主路径中排除，仍保留在 local-consistency 产品中供审计。

### 12.4 数据集之间的关键差异

| 比较维度 | AMDAR/TURB | ADS-B | 雷达 | GFS/CMA | aircraft holdout |
|---|---|---|---|---|---|
| 记录的是什么 | 风速、风向等气象量 | 飞机位置和运动 | 回波/图像或空间框架 | 网格化背景风 | 官方评价用的飞机风 |
| 是否直接有风 | 是 | 否 | 通常否，不能把强度当 Doppler 风 | 是，但属于背景/模式产品 | 是 |
| 时间精度 | AMDAR 多为 batch 级 | 位置时间较细但会断 | 帧级 | 模式时次/预报时次 | 作为评价标签使用 |
| 空间覆盖 | 很稀疏 | 航迹附近较密 | 区域覆盖但物理量有限 | 连续网格 | 只覆盖少量 holdout 点 |
| 主要风险 | 时间和批次语义 | identity、断轨、插值误读 | 强度误读为风 | 独立性/平滑偏差 | 样本量和分层代表性 |
| 当前最终用途 | support-only | candidate/track graph | frame organization | display/report-only | official metrics |

### 12.5 数据集优缺点的通俗结论

- **AMDAR/TURB 的优点是“直接告诉你风”，缺点是“时间和批次语义不够细”。**因此不能按表面行数直接当作 431,189 个独立精确真值。
- **ADS-B 的优点是“脚印多且能表达运动连续性”，缺点是“脚印不是风”。**它能帮助回答“这两个观测是否来自同一条航迹”，但不能单独回答“风是多少”。
- **雷达的优点是“给出时间和空间组织”，缺点是“强度不等于风速”。**它主要为 voxel 和 frame 提供框架。
- **GFS/CMA 的优点是“填补空间空洞”，缺点是“背景可能太平滑且独立性不同”。**它们只能按角色受限使用。
- **strict holdout 的优点是“最能检验是否真的变好”，缺点是“数量少、结果有方差”。**所以必须同时报告平均误差、尾部误差、分高度和分 regime 结果。

### 12.6 数据集路径和可复核文件

```text
stage1_output/clean_wind.parquet
stage1_output/clean_loc.parquet
stage1_output/radar_index.json
stage1_output/frame_window_index.json
stage1_output/stage1_summary.json
centralized_v1_output/stage2_full_v2/stage2_multimodal_summary.json
centralized_v1_output/stage3_full_v2_25w_payload_only/acceptance/stage3_payload_only_acceptance.md
```

---

## 13. 核心名词词典：每个名词到底是什么意思

| 名词 | 白话解释 | 本项目中的实际边界 |
|---|---|---|
| centralized_v1 | 中心化处理整条数据链的工程版本 | 不是某一个单独神经网络 |
| Stage1 | 原始数据清洗、单位统一和语义标注 | 不负责恢复完整风场 |
| Stage2 | 组织多模态数据或 ADS-B 轨迹的阶段 | v8 graph 只产生 prior，不正式接受 bridge |
| Stage3 | 对匹配/bridge 规则进行独立验证的阶段 | pseudo case 不是现实真值 |
| Stage4 | 把有效观测定位到三维网格并评估风场的阶段 | official score 只看 strict aircraft holdout |
| Stage5 | 真实 AMDAR 与 ADS-B 的序列匹配，或较早 field/PINN 分支 | 两者必须用完整名称区分 |
| Stage6 | 将安全支持观测放入更大范围重构并做严格验证 | 当前尚未完成正式闭环 |
| AMDAR | 飞机上传的气象观测，通常包含风信息 | 最新策略中是 support-only |
| TURB | 与飞机湍流/质量记录相关的小规模来源 | 181 行，不代表完整 AMDAR |
| ADS-B | 飞机广播的位置、时间、高度、速度、航向 | 是轨迹证据，不是风真值 |
| tracklet | 一小段连续、同身份、同日期的航迹片段 | 不是完整航班，也不是正式 bridge |
| leg | 旧版本兼容的飞行段定义 | v8 不把旧 leg 边界当永久真理 |
| identity/date | 飞机身份和日期组合 | 用于候选分组，不等于唯一空间路径 |
| graph edge | 两个 tracklet 之间的一条候选连接 | Stage2 的 edge 仍是 prior |
| graph path | 多条 edge 串起来的候选轨迹 | 需要 Stage3 path validation |
| bridge | 跨越两个轨迹碎片的连接假设 | 不能只凭距离就接受 |
| voxel | 三维网格中的一个小立方体 | 里面可以放观测、背景或空值，不同角色要标记 |
| u/v | 东西向和南北向的水平风分量 | 由气象风向约定转换得到 |
| ground vector | 飞机相对地面的运动向量 | 不能直接当风 |
| current window | 当前时间附近的观测窗口 | 原始 Stage2 使用当前时间前后约 5 分钟 |
| context window | 用于补充空间/时间信息的更宽窗口 | 原始 Stage2 约为当前时间前后 360 分钟 |
| strict truth | 可用于官方判分的真实标签 | 不是所有带 wind 字段的行都满足 |
| aircraft holdout | 从输入中暂时遮住的一架或一组飞机 | 防止模型直接看答案 |
| support-only | 可以辅助重构或匹配，但不作为真值 | AMDAR 最新有效策略属于此类 |
| pseudo validation | 人工制造有答案的验证样本 | 用来测规则风险，不能替代真实 holdout |
| corruption | 对干净样本人为加入异常 | 例如跳点、逆序、局部交换、时间偏移 |
| hard negative | 故意构造很像但其实错误的候选 | 用来测算法会不会“自信地选错” |
| HMM | 隐马尔可夫模型，用状态和转移表达序列 | 这里用于让匹配按轨迹顺序推进 |
| Viterbi | 在 HMM 中寻找代价最低的状态路径 | 不是简单逐行最近邻 |
| Drop-DTW | 允许动态时间规整在必要时跳过坏行 | 跳过的是诊断行，不是修改 truth |
| partial matching | 只接受批次中可靠的一部分行 | 必须满足 matched fraction、contiguous 等门 |
| posterior | 候选结果可信度的概率化分数 | 要经过独立 calibration |
| calibration | 把原始分数校准成有概率意义的分数 | 不能在 locked-test 上调阈值 |
| ECE | Expected Calibration Error，概率和实际正确率的偏差 | 越接近 0 越好 |
| covariance | 描述位置/速度估计不确定性的矩阵 | 可用于 Mahalanobis 距离，而不是固定半径 |
| Mahalanobis distance | 按不确定性缩放后的距离 | 误差大且不确定的点不应与高精度点等权 |
| unique | 只有一个足够可信的候选 | 可以作为唯一关联结果输出 |
| mixture | 多个候选都不能安全区分 | 不能改名成 unique |
| reject | 没有满足安全门的候选 | 保留失败原因，不能强行填充 |
| OI | Optimal Interpolation，背景和观测按误差协方差加权 | 当前 constrained/diagnostic 为主 |
| background | 连续的先验风场 | 不等于 truth，需独立性和误差验证 |
| OMB | Observation Minus Background，观测减背景 | 诊断背景是否明显偏离观测 |
| QC | Quality Control，质量控制 | 识别异常、缺失和角色边界 |
| RMSE | 平方误差平均后开根号 | 对大错误敏感，越低越好 |
| MAE | 绝对误差平均 | 比 RMSE 更直观，越低越好 |
| P95/P99 | 误差的 95/99 分位点 | 反映尾部风险，越低越好 |
| bias | 平均有方向的误差 | 反映整体偏高/偏低 |
| representation error | 观测点与网格/背景代表的物理尺度不一致 | 高空和稀疏区域尤其重要 |
| PINN residual branch | 用网络学习相对已有场的修正量 | 当前是诊断/受限 gate 分支，不是正式替代模型 |
| gate | 决定某个修正是否真正启用的规则 | 由 validation 选择，再在 locked test 固定检查 |
| display-only | 只为显示补背景，不改变 official recon | M1 CMA 填充属于此类 |
| report-only | 只生成诊断报告，不改正式输出 | OI diagnostic 属于此类 |

### 13.1 三个最容易混淆的词

**第一，`edge` 不等于 `match`。**edge 是“可能连接”，match 是“经过验证并被规则接受”。Stage2 v8 生成了 `11,306` 条 physical graph edges，但 Stage2 formal bridge accepts 仍为 `0`，这是安全设计，不是矛盾。

**第二，`display fill` 不等于 `accuracy improvement`。**CMA M1 把大量空间补成了弱背景，能让图看起来更完整；但官方 `recon_u/v/conf/mask` 和精度指标没有改变，不能把覆盖率提升写成 RMSE 提升。

**第三，`strict truth` 不等于“有 wind 字段”。**Stage1 的兼容字段曾记录 `strict_truth_candidate`，但最新有效政策根据批次时间和逐点时间语义把 AMDAR 的 `effective_strict_truth` 设为 false。报告必须以后者为准。

---

## 14. 图表化结果展示

### 14.1 Stage2 v8 处理漏斗

```text
原始 ADS-B 点              19,162,638
        |
        v
local consistency 点       19,162,638   点守恒: PASS
        |
        +-- diagnostic exclude   7,744   保留在诊断层
        v
clean tracklet 点          19,154,894
        |
        v
clean tracklets              2,953,850   这是“轨迹段”数量，不是点数
        |
        v
physical graph edges            11,306   只是候选连接
        |
        v
formal bridge accepts                0   Stage2 明确不越权接受
```

`19,154,894` 和 `2,953,850` 不能直接相减理解为“删除了这么多点”，因为一个是点数，一个是 tracklet 数。这个漏斗同时展示了数据清理、轨迹压缩和候选连接三个不同单位。

### 14.2 Stage5 v5 到 v7 的利用率变化

| 版本 | unique batches | matched rows | 相对 v5 的 unique 变化 | 相对 v5 的 rows 变化 | 状态 |
|---|---:|---:|---:|---:|---|
| v5 | 198 | 251 | 基线 | 基线 | frozen safe baseline |
| v6 | 205 | 274 | +3.54% | +9.16% | safety 通过，merge target 未完全通过 |
| v7 | 229 | 345 | +15.66% | +37.45% | safety/merge gate 通过 |

```text
unique batches
v5 198 |###################
v6 205 |####################
v7 229 |######################

matched rows
v5 251 |#########################
v6 274 |############################
v7 345 |###################################
```

原始分母约 `56,521` 个 AMDAR batch，因此 `229 / 56,521 = 0.405%` 左右。这个结果说明“新增的 accepted 质量更好”，但还不能说“绝大多数 AMDAR 已经被利用”。主要拒绝原因仍是候选轨迹在几何上不够可信、没有候选或 batch-end 约束不满足。

### 14.3 Stage3 v13 安全门结果

| 质量指标 | 结果 | 要求 | 直观解释 |
|---|---:|---:|---|
| wrong-tracklet/path | `0.0827%` | `<=1%` | 1000 个测试 case 中约不到 1 个错误航段 |
| catastrophic bridge | `0.0645%` | `<3%` | 极严重的错误连接很少 |
| edge/path ECE | `0.000321` | `<=0.05` | posterior 概率与真实正确率很接近 |
| max corruption false acceptance | `0.8621%` | `<=2%` | 最危险异常类的误接收仍在门内 |
| unreachable bridge | `0%` | `<=0.5%` | 物理上到不了的桥没有被接受 |
| clean no-bridge retention | `100%` | 需保持 | 原本不该桥接的干净 case 没被破坏 |
| truth/holdout violation | `0` | `0` | 没有使用禁用真值 |

### 14.4 Stage4 旧主线误差比较

#### 固定 200 帧严格留出主对比

| 方法 | frame RMSE | frame MAE | P95 RMSE | holdout-weighted RMSE | 解释 |
|---|---:|---:|---:|---:|---|
| aircraft baseline | `11.690` | `10.301` | `42.641` | `18.918` | 纯 aircraft 观测基线 |
| TimePower15 | `8.636` | `7.423` | `28.147` | `15.039` | 时间权重和更紧局地核 |
| CMA proxy | `9.377` | `8.017` | `24.329` | `14.964` | 背景参考，不代表独立 truth |

```text
frame RMSE, 越短越好
aircraft baseline 11.690 |########################
TimePower15          8.636 |##################
CMA proxy            9.377 |###################
```

这一表是 2026-05-31 的主对比。另一个 2026-06-02 teacher showcase 中，`adaptive_v3` 为 `8.457`，`tp26` 为 `8.224`，相对 baseline `11.690` 分别下降约 `27.7%` 和 `29.6%`。2026-06-14 的 pairwise 汇总使用另一套聚合输出，tp26 frame mean 为 `8.404`、weighted RMSE 为 `14.869`；它不能和前表逐位混合，应该按各自 run 的输入和指标定义比较。

#### 为什么不能只看平均 RMSE

`frame RMSE` 是先对每个时间帧算误差，再平均，能防止样本多的帧完全支配结果；`weighted RMSE` 是把所有 holdout 点按整体统计，容易被高误差帧和高空尾部拉高。两者都需要报告。

代表帧已经说明了方法互有胜负：

| 时间 | baseline | TimePower15/tp26 | CMA | 说明 |
|---|---:|---:|---:|---|
| `20260206074200` | `74.105` | `3.265` / `3.079` | `5.221` | 局地优化显著抑制大错 |
| `20260125124200` | `4.132` | `32.594` / `32.597` | `8.602` | 收窄邻域反而损失有用上下文 |
| `20260205190000` | `86.000` | `86.000` / `86.000` | `32.619` | 大尺度背景对崩坏帧有兜底作用 |
| `20260216015400` | `32.713` | `29.007` / `29.005` | `66.290` | 背景过度平滑伤害局地结构 |
| `20260126090000` | `5.999` | `2.230` / `2.450` | `5.401` | 低误差边界对方法很敏感 |
| `20260223133000` | `117.236` | `108.858` / `109.693` | `109.389` | 高误差多 holdout 压力帧 |

完整可视化在：

```text
centralized_v1_output/stage4_teacher_showcase_20260602_baseline_adaptive_v3_tp26/visuals/
centralized_v1_output/stage4_three_method_compare_20260531/representative_visuals/
```

### 14.5 高空误差图

2026-06-14 tp26 结果的分高度统计显示：

| 高度层 | 点数 | vector RMSE | 结论 |
|---|---:|---:|---|
| `0-3 km` | 39 | `5.694` | 低空支持相对较好 |
| `3-6 km` | 47 | `8.384` | 误差增加 |
| `6-9 km` | 85 | `7.622` | 有波动，不是单调关系 |
| `9-12 km` | 137 | `11.700` | 高空开始明显变难 |
| `12 km+` | 222 | `20.012` | 主要尾部风险 |

`12 km+` 只有 `222/530` 个点，却贡献了约 `76.18%` 的平方误差。通俗地说，整体平均分主要被高空少数但很难的样本拖住；下一轮不能只优化低空平均数。

### 14.6 OI 和 PINN 为什么还没有升格

| 分支 | 观测/背景 | 结果 | 当前判断 |
|---|---|---|---|
| CMA M1 display fill | CMA 弱背景填充展示层 | 官方 recon 和指标逐帧零差异；覆盖增加 | display-only，不是精度提升 |
| S4-OI diagnostic | train OMB RMSE `38.629`，holdout report-only RMSE `34.616` | 背景独立性未确认，train OMB P95 `66.808` | report-only，不升格 M2 |
| Residual PINN raw | test RMSE `24.379 -> 24.350`，但 MAE/P95 变差 | 平均 RMSE 小幅改善，尾部风险不安全 | 不替换 Stage4 |
| gated residual | 只在小部分高风险点启用，test RMSE 约改善 `0.012` | 改善太小，整体 guardrail 未完整通过 | 继续实验，不正式合并 |
| representation-error equivalent v2 | 530 点官方 RMSE `14.769`；邻域最小误差诊断 RMSE `11.599` | `328` 点保守规则召回全部 21 个高误差点，但邻域指标不是官方指标 | report-only，不改 recon |

PINN 的普通话解释是：网络不是从零预测风，而是试图对已有 tp26 结果加一个小修正。若修正平均值只减少 `0.029 m/s`，但 P95、MAE 或轻风区域变差，工程上仍然不能说它更好。

---

## 15. 结果证据等级、可以怎么说、不能怎么说

### 15.1 证据等级

| 等级 | 代表结果 | 可以说什么 | 不能说什么 |
|---|---|---|---|
| A：正式严格评价 | Stage4 200 帧/530 点；无泄漏 holdout 指标 | 某方法在该固定 holdout 上的误差是多少 | 不能外推成所有区域、所有季节都一样 |
| B：正式安全验证 | Stage2 v8、Stage3 v12/v13、Stage5 v7 | 质量门、错误率和利用率在定义范围内达标 | 不能说已证明最终风场精度提升 |
| C：诊断/展示 | CMA fill、OI diag、GFS proxy、PINN gate | 某个误差来源或候选机制值得继续研究 | 不能写成 official accuracy |
| D：计划/目标 | Stage5 v8、Stage6、预期 1%-2% 利用率等 | 下一步要验证的目标 | 不能写成已经达到的结果 |

### 15.2 当前最稳妥的工程结论

可以明确写：

- Stage2 v8 在 `19,162,638` ADS-B 点上点守恒通过，clean fragments 减少 `23,628`，生成 `11,306` 个 physical graph edges；
- Stage3 v13 在 `27,599` locked cases 上通过全部 hard gates，wrong path `0.0827%`，truth/holdout violation `0`；
- Stage5 v7 相对 v5 增加到 `229 unique batches / 345 rows`，并保持安全门；
- Stage4 teacher showcase 中 tp26 在固定 200 帧严格 holdout 上优于纯 aircraft baseline；
- OI/CMA/PINN 分支目前是诊断、展示或受限研究结果，尚未替换 official baseline。

不能明确写：

- “Stage5 已经达到 1% 利用率”：当前约 `0.405%`；
- “11,306 条 graph edges 都已经匹配成功”：它们是 prior/candidate；
- “CMA 填充让官方精度提升”：M1 官方指标没有变化；
- “PINN 已经降低整体误差”：原始候选存在 MAE/P95/轻风风险，整体 guardrail 未完成；
- “AMDAR 431,008 行都是 strict truth”：最新有效政策是 support-only；
- “GFS/CMA 与 holdout 完全独立”：CMA independence 未确认，GFS 也需要逐实验记录独立性证据。

### 15.3 旧目标、当前结果和缺口

| 项目 | 旧计划/期望 | 当前真实结果 | 缺口 |
|---|---|---|---|
| AMDAR batch 利用率 | 通过安全扩展提升到更高比例 | `229/56,521 ~= 0.405%` | 需要增加空间覆盖或更可靠时间信息，不能只调阈值 |
| graph bridge | 恢复被切碎轨迹 | 生成 `11,306` candidate edges | 尚未完成 Stage5 v8 unique/mixture merge |
| Stage4 精度 | 降低全高度和高空误差 | tp26 旧主线改善，12 km+ 仍约 `20 m/s` | 需要 representation error 和高空专项 |
| OI 背景 | 用独立背景填补稀疏区域 | OI diagnostic 不安全，CMA 只展示 | 完成 GFS constrained OI 严格对照 |
| PINN residual | 小修正减少误差 | 平均改善极小且尾部不稳定 | 重新设计 gate 和风险目标 |

---

## 16. 后续详细迭代方向、实验计划与预期指标

### 16.1 P0：冻结现有结果，建立回归保护

**目标：**保证后续任何 graph/partial/OI 改动都不能悄悄破坏当前安全结果。

| 步骤 | 输入 | 必须输出 | 通过条件 |
|---|---|---|---|
| 1 | Stage5 v7 accepted/rejected/mixture 产品 | frozen manifest、参数和 hash | `229/345` 可重复 |
| 2 | Stage3 v13 locked case | locked metrics | wrong path 不超过 `1%`，ECE 不超过 `0.05` |
| 3 | Stage4 200 帧 holdout | baseline/candidate pairwise | no leakage、motion not wind |
| 4 | Stage2 v8 25 slices | point conservation report | 输入输出点数一致，跨 slice violation 为 0 |

### 16.2 P1：Stage5 v8 graph 小集合审计

不要直接把 `11,306` 条 edge 全量并入。建议按四类小集合推进：

1. 已知的 5 个 stitched cases：验证 graph 能否恢复真实被切碎轨迹；
2. Stage5 v5/v6 已拒绝但有 graph edge 的 cases：判断拒绝是因为旧轨迹碎片还是确实无覆盖；
3. same-identity hard negatives：验证 graph 是否把错误航段串起来；
4. no-candidate cases：确认“没有候选”是真空洞还是 graph 组织不足。

每一类同时输出：

```text
unique candidates
mixture candidates
rejected candidates
edge/path posterior
gap time and batch-end residual
observed state vs interpolated gap state
failure reason top-k
```

**预期指标：**不要求第一轮马上达到 1% 利用率，而要求：

- unique 新增结果 truth/holdout violation 为 0；
- wrong-path 不超过 Stage3 v13 locked gate；
- `229/345` 完全回归通过；
- 新增 accepted 中 observed 与 interpolated state 角色不混淆；
- 失败原因能区分 coverage 不足、时间不确定、几何不一致和身份冲突。

### 16.3 P2：Stage5 v8 从小集合扩展到分层全量

只有 P1 通过后，才按 `short / medium / long gap`、`unique / mixture`、`low / high altitude` 分层扩展。每一层都要有独立的 acceptance rate 和 error-risk 曲线。

建议固定参数初始值：

```text
candidate_topk = 10
cross_track_km = 1.5
vertical_diff_m = 800
max_gap_s = 900
after_batch_end_s = 180
posterior_min = 0.90
max_drop_fraction = 0.50
```

这些参数来自当前 v7 的安全配置，只能作为起点。不能因为接受率低就同时放大 `cross_track`、`max_gap`、`best_cost` 和 `after_batch_end`，否则无法知道新增结果是哪一个门造成的。

### 16.4 P3：Stage6 strict aircraft holdout sensitivity

建立至少五个分支：

| 分支 | 使用内容 | 目的 |
|---|---|---|
| S0 | 当前 tp26/official baseline | 冻结比较基线 |
| S1 | 仅 Stage5 v7 unique support | 评估已验证真实匹配 |
| S2 | Stage5 v7 unique + partial | 评估局部行剔除的净收益 |
| S3 | graph unique | 评估 graph 连接对风场的影响 |
| S4 | graph unique + mixture 分层 | 评估不确定候选是否应该只做低权重 support |

每个分支在同一批 200 帧 strict aircraft holdout 上报告：

- frame RMSE/MAE；
- all-point weighted RMSE/MAE；
- P95/P99/max；
- `12 km+`、`<12 km`；
- light wind、moderate wind、high wind；
- single/multi holdout frame；
- coverage、confidence 和 effective reconstructed voxels；
- 与 S0 的逐帧胜负数。

**预期指标：**S1-S4 至少不使 weighted RMSE、P95、12 km+ vector RMSE 和 light-wind guardrail 恶化；如果 graph 只增加覆盖但不改善严格 holdout，应保留为 support/diagnostic，不合并为 official。

### 16.5 P4：GFS constrained OI 正式对照

建立严格的 B0-B3：

| 分支 | 说明 |
|---|---|
| B0 | 当前 official baseline |
| B1 | GFS weak background，不加入新 AMDAR |
| B2 | GFS + Stage5 v7 high-confidence unique support |
| B3 | GFS + Stage5 v8 graph unique/mixture 分层 |

关键控制：

- GFS 的资料时间和目标 holdout 时间不能偷看未来或同一标签；
- background independent audit 必须明确写出；
- background-only、OI-only、support-only、combined 要分别算；
- CMA 继续作为 display-only 对照，不替代 GFS independence 证明；
- OI 先在小样本诊断，不能因为图面覆盖率高就直接升格。

**预期指标：**B1/B2/B3 在主要 holdout 指标不劣于 B0，且 OMB、P95、12 km+ 误差能够解释；若只填补空洞但误差变差，保留 report-only。

### 16.6 P5：12 km+ 高空专项

高空专项要把总误差拆成：

```text
aircraft observation error
time uncertainty
spatial support error
representation error
background error
localization error
```

建议实验：

1. 以高度层、风速 regime、温度/垂直速度 regime 分层；
2. 对高空单独设 process noise 和 observation-error prior；
3. 对比固定半径和 covariance-normalized Mahalanobis localization；
4. 对比使用/不使用 graph support；
5. 只在高空 holdout 指标改善且整体指标不恶化时推广。

**预期指标：**第一阶段不是承诺把 `12 km+` 从 `20.012 m/s` 降到某个未经验证的数字，而是先证明误差来源可分解、可重复、可控。之后再设置相对改善目标，例如高空 RMSE 下降、P95 不升、全高度 weighted RMSE 不升三者同时满足。

### 16.7 P6：PINN/residual branch 的安全重做

当前 residual 网络不应直接替代 tp26。下一轮建议：

- 只预测小幅 residual，并限制最大修正幅度；
- gate 选择只在 validation 完成，test 完全锁定；
- 把 P95/P99、light-wind 和 12 km+ 放入主目标，而不是只优化平均 RMSE；
- 对高风险点允许启用，对低风险点默认不改；
- 记录每个启用点的原因、修正量、原始/新误差。

**上线前最低门：**test weighted RMSE 不升、MAE 不升、P95/P99 不升、light-wind 不新增失败、12 km+ 不恶化，并且在多个时间/身份分组上重复成立。

### 16.8 每次实验的强制记录模板

```text
run_config.json
input_manifest.json
code_commit_or_hash.txt
quality_gate.json
global_metrics.json
slice_reports/*.json
candidate_diagnostics.parquet
accepted_unique.parquet
accepted_mixture.parquet
rejected_diagnostics.parquet
holdout_metrics.csv
result_analysis.md
```

必须记录：输入文件和代码 hash、slice/workers/thread 配置、参数变更、新增/回退 batch 数、truth/holdout invariants、runtime、峰值内存、磁盘占用、失败原因 top-k，以及相对冻结 baseline 的逐项差分。

### 16.9 最终可执行顺序

```text
1. 冻结 Stage5 v7 的 229/345 regression set
2. 完成 Stage5 v8 graph 小集合 audit
3. 通过 safety + utility gate 后扩展 candidate scope
4. 在同一 strict aircraft holdout 上运行 Stage6 S0-S4
5. 完成 GFS constrained OI 的 B0-B3 对照
6. 对 12 km+ 做 representation-error 分层
7. 重新审计 residual/PINN 的尾部风险
8. 只有正式 holdout 不退化且收益可解释，才合并 official pipeline
```

---

## 17. 本次扩展使用的关键证据文件

| 证据类别 | 文件 |
|---|---|
| Stage1 数据规模和语义 | `stage1_output/stage1_summary.json` |
| 原始 Stage1-4 设计 | `workflow/centralized_v1_docs/new_window_project_handover_20260529/stage1_to_stage4_pipeline.md` |
| 原始 Stage2 全量结果 | `centralized_v1_output/stage2_full_v2/stage2_multimodal_summary.json` |
| 原始 Stage3 payload 通过报告 | `centralized_v1_output/stage3_full_v2_25w_payload_only/acceptance/stage3_payload_only_acceptance.md` |
| Stage4 200 帧三方法对比 | `centralized_v1_output/stage4_three_method_compare_20260531/analysis/three_method_compare_analysis.md` |
| Stage4 teacher showcase | `centralized_v1_output/stage4_teacher_showcase_20260602_baseline_adaptive_v3_tp26/` |
| Stage4 OI/CMA 诊断 | `centralized_v1_output/stage45_oi_diag_light_200_20260614/oi_diag_200/oi_diag_report.md` |
| Stage4 OI/CMA 展示边界 | `centralized_v1_output/stage45_oi_cma_m1_200_25w_20260614/analysis/experiment_report_20260614.md` |
| Stage4 S4A promotion gate | `centralized_v1_output/stage45_s4a_metrics_200_25w_20260614/analysis/downweight_pairwise/tp26_vs_s4a_downweight.md` |
| Stage4 representation-error 最新诊断 | `centralized_v1_output/stage4_tail_risk_confidence_v2_20260608/representation_error_report_equivalent_v2/representation_error_report.md` |
| Stage5 residual/PINN 数据 | `centralized_v1_output/stage5_residual_pinn_report_v1_20260608/` |
| Stage2/3 v8/v13 最新正式解释 | `优化/数据处理/stage2_stage3_folders_and_results_explanation_20260720.md` |
| Stage3/Stage5 最新周报 | `优化/数据处理/amdar_stage3_stage5_track_graph_weekly_report_20260717.md` |
| Stage2 v8 正式报告 | `优化/数据处理/stage2_v8_track_graph_optimized_20260716/stage2_track_graph_v8/stage2_v8_track_graph_report.json` |
| Stage3 v13 正式报告 | `优化/数据处理/stage3_v13_bridge_validation_optimized_20260716/stage3_bridge_validation_v13/stage3_v13_bridge_validation_report.json` |
| Stage5 v7 正式报告 | `优化/数据处理/stage5_v7_calibrated_partial_optimized_20260716/stage5_v7/` |

## 18. 最终通俗结论

这个工程已经完成了最重要的“把数据讲清楚、把错误挡住、把结果留痕”工作：知道哪些是风、哪些是飞机脚印，知道哪些是官方答案、哪些只是辅助证据，也知道一条看起来合理的轨迹连接可能会在哪里犯错。

截至本次复核，最可靠的进展是：

1. ADS-B 全量组织和 track graph 质量门通过；
2. bridge/path 的独立 locked-test 通过；
3. 真实 AMDAR 的安全 partial matching 已从 `198/251` 提升到 `229/345`；
4. 旧 Stage4 严格留出实验中，TimePower15/adaptive/tp26 相比纯 aircraft baseline 有明确改善；
5. CMA display、OI diagnostic 和 PINN residual 都被正确限制在各自证据等级内。

最关键的未完成事项是：**新增的 support 观测是否能在不伤害 strict aircraft holdout 的情况下真正改善最终三维风场。**这个问题必须通过 Stage5 v8 小集合审计、Stage6 S0-S4 严格对照和 GFS constrained OI 才能回答。当前最科学、最稳妥的状态判断是：

> **数据和安全验证主线已经达标，风场最终增益主线仍在验证中；不能把 graph candidate、背景展示覆盖率或 PINN 的微小平均改善提前写成正式完成。**
