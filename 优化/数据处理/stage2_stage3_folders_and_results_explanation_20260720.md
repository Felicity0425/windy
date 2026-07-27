# Stage2 v8 / Stage3 v13 文件夹、文件与结果总说明

生成日期：2026-07-20  
适用项目：`/data/LFT-W02_data/pengxu/` 下 centralized_v1 三维水平风场重构项目

---

## 一、先给最终结论

### 1. Stage2 v8 是否达标

**按本轮 Stage2 v8 计划规定的工程、安全和语义质量门，已经达标。**

正式全量结果：

- 输入点数：`19,162,638`。
- local consistency 输出点数：`19,162,638`，点守恒通过。
- clean tracklet 点数：`19,154,894`。
- diagnostic excluded：`7,744`，仍保留在 local-consistency 产品中，没有从原始证据层删除。
- 兼容 v4 的 legacy legs：`2,977,478`。
- v8 clean tracklets：`2,953,850`。
- fragment 数量减少：`23,628`，约 `0.7936%`。
- physical graph edges：`11,306`。
- exact identity/date groups：`357,754`。
- identity/date 跨 slice 违规：`0`。
- Stage2 formal bridge accepts：`0`，符合“Stage2 只能生成 prior，不能提前正式接受 bridge”的规定。

Stage2 的达标不是“所有数据都被成功匹配”，而是：

1. 输入点没有丢失；
2. 同一 identity/date group 没有被错误分到不同 slice；
3. 轨迹碎片没有恶化，反而减少；
4. graph candidates 成功生成；
5. 没有在 Stage2 越权接受未经 Stage3 验证的 bridge；
6. truth/holdout 违规为 `0`。

### 2. Stage3 v13 是否达标

**Stage3 v13 的全部 locked-test hard quality gates 已通过。**

正式验证结果：

- selected base tracklets：`15,000`。
- case bank：`151,951` cases。
- calibration cases：`80,971`。
- validation cases：`28,381`。
- locked-test cases：`27,599`。
- wrong-tracklet/path rate：`0.0827%`，要求 `<=1%`。
- catastrophic bridge rate：`0.0645%`，要求 `<3%`。
- edge posterior ECE：`0.000321`，要求 `<=0.05`。
- path posterior ECE：`0.000321`，要求 `<=0.05`。
- 最大单类 corruption false acceptance：`0.8621%`，要求 `<=2%`。
- same-identity wrong-tracklet：`0.8621%`，要求 `<=1%`。
- unreachable bridge：`0%`，要求 `<=0.5%`。
- clean no-bridge retention：`100%`。
- truth/holdout violations：`0`。

### 3. 是否可以进入 Stage5 航迹匹配

答案需要分成两层：

#### 可以进入：Stage5 v8 小范围 graph audit

Stage2 v8 和 Stage3 v13 已经满足进入以下小范围工作的前置条件：

- 历史 5 个 stitched cases 审计；
- graph-recoverable rejects 审计；
- same-identity hard negatives 审计；
- Stage5 v7 prior regression 审计；
- covariance-normalized emission 试验；
- unique / mixture / rejected 三层产品试验。

#### 还不能直接做：Stage5 v8 全量正式 merge

当前**不能**因为 Stage2/3 达标就直接把所有 `11,306` 个 graph edges 接入 Stage5 unique。原因是：

- Stage2 edge 只是物理 prior，不是正式接受结果；
- Stage3 v13 验证的是 bridge/path policy 的安全性，不是每个真实 AMDAR batch 的匹配成功证明；
- Stage5 v7 的 `229 unique batches / 345 matched rows` 必须冻结并回归保护；
- graph mixture 不能改名为 unique；
- interpolated gap state 不能当成 observed ADS-B point；
- 最终是否使用 graph unique/mixture，还要由 Stage5 v8 safety + utility gate 和 Stage6 strict aircraft holdout sensitivity 决定。

因此准确结论是：

> **Stage2 和 Stage3 已达标，可以进入 Stage5 v8 小集合 graph matching 审计；但尚未授权直接进行 Stage5 v8 全量正式合并。**

---

## 二、为什么会有这么多目录

这 5 个目录不是 5 次互相重复的正式实验，而是四种不同用途：

| 目录 | 类型 | 用途 | 是否最终依据 |
|---|---|---|---|
| `stage2_v8_track_graph_plan_20260716` | 方案与交接 | 记录算法、schema、质量门、禁止事项和执行顺序 | 是规范，不是结果 |
| `stage2_v8_track_graph_smoke_20260716` | Stage2 smoke | 约 1% identity/date group 的开发期小样本调试 | 否 |
| `stage2_v8_track_graph_optimized_20260716` | Stage2 正式结果 | 19,162,638 点的 25-slice 全量结果 | **是** |
| `stage3_v13_bridge_validation_smoke_20260716` | Stage3 smoke | 基于 Stage2 smoke 的小规模 bridge validation 调试 | 否 |
| `stage3_v13_bridge_validation_optimized_20260716` | Stage3 正式结果 | 15,000 tracklets、27,599 locked cases 的正式验证 | **是** |

目录命名中的 `optimized` 指正式全量或正式规模结果；`smoke` 指开发期小样本；`plan` 指设计文档。不要把 smoke 的通过理解为正式全量通过，也不要把 plan 目录当成运行输出。

---

## 三、Stage2 plan 文件夹说明

目录：

`优化/数据处理/stage2_v8_track_graph_plan_20260716/`

该目录只有两个 Markdown 文件，共同构成 Stage2 v8/Stage3 v13 的实施规范和交接入口。

### 1. `stage2_v8_track_graph_full_implementation_plan_20260716.md`

这是**完整实施方案**，不是运行结果。主要内容包括：

- 大框架 Stage2/3/5/6 与旧优化计划小阶段的编号区分；
- Stage2 v8 的 local consistency、clean tracklet、状态平滑和 graph 设计；
- exact `tail/flight/date` graph locality 规则；
- 25-slice 和 `POLARS_MAX_THREADS=25` 省空间规则；
- raw point、clean point、smoothed state、interpolated gap state、unique path、mixture、no-coverage 的语义；
- Stage3 v13 case bank、calibration/validation/locked-test 规则；
- Stage3 v13 hard quality gates；
- Stage5 v8 的 frozen prior、unique/mixture/rejected 分层和 utility gate；
- 失败回退矩阵与禁止操作。

该文件回答“应该怎么做、哪些操作不允许做”，不回答“这次实际跑出了什么结果”。

### 2. `next_agent_handover_for_stage2_v8_track_graph_20260716.md`

这是**执行交接文档**，用于让下一个智能体从正确的项目边界开始执行。主要包含：

- 必须先阅读的文档列表；
- Stage5 v7 frozen baseline：`229/345`；
- Stage2 输入、Stage3 输入和 Stage5 prior 的路径；
- 需要创建的 Stage2 v8、Stage3 v13、Stage5 v8 代码；
- 首轮 smoke、5 个 stitched cases 只读审计和正式运行顺序；
- Stage3 v13 全部硬门；
- Stage5 v8 utility gate；
- 可直接复制给下一智能体的启动话术。

它是“怎么接着做”的说明，不是数据产品。

---

## 四、Stage2 smoke 文件夹说明

目录：

`优化/数据处理/stage2_v8_track_graph_smoke_20260716/`

### 1. smoke 的目的

Stage2 smoke 不是旧计划中的“1% AMDAR 利用率目标”，而是约 1% identity/date group 的工程小样本，主要验证：

- hash slice 是否正常；
- local feature 是否能计算；
- isolated anomaly 是否被识别；
- clean tracklet 是否生成；
- smoother 是否能运行；
- graph DAG 是否能生成；
- 是否存在明显 Polars/schema/进程错误。

### 2. smoke 根目录文件

#### `run_config.json`

记录 smoke 的运行参数，例如：

- 输入路径；
- 输出路径；
- `slice_count=25`；
- `workers=25`；
- `smoke_group_modulus=100`；
- `POLARS_MAX_THREADS=25`；
- graph 最大 gap 和 top-k 设置。

它用于复现 smoke，不代表正式全量配置。

#### `source_input_manifest.json`

记录 smoke 输入源的：

- 输入路径；
- 实际抽取行数；
- 源表 schema；
- ADS-B truth semantics。

它用于确认 smoke 是从同一份 `stage1_output/clean_loc.parquet` 派生，而不是从另一份数据开始。

#### `stage2_v8_input_profile.json`

记录 25 个 smoke input shards 的行数分配。它主要用于检查：

- smoke 是否成功分布到多个 slice；
- 输入点是否有丢失；
- 是否存在某个 slice 异常占满全部样本。

### 3. smoke 的 `stage2_track_graph_v8/` 子目录

smoke 子目录结构与正式 Stage2 基本一致，但数据规模小得多，包含以下 8 类子目录：

#### `raw_input_shards_v8/`

- `slice_00.parquet` 至 `slice_24.parquet`，共 25 个。
- 每个点只写入一个 slice。
- 只保留后续 Stage2 所需的 12 个紧凑字段：稳定 row id、规范化 identity、时间、位置、高度、航向、地速、hash 和 slice id。
- 这是分片工作输入，不是原始 ADS-B 全量原表。

#### `local_consistency_points_v8/`

- 每个 slice 一个 parquet，共 25 个。
- 保存所有 smoke 输入点及局部运动特征。
- 主要字段包括 `dt_prev/dt_next`、前后距离、前后速度、skip speed、vertical rate、acceleration、turn rate、duplicate rank、异常类型和 `local_consistency_score_v8`。
- 该层仍保留原始点，即使某点后来被标记为 diagnostic exclude。

#### `clean_tracklet_points_v8/`

- 每个 slice 一个 parquet，共 25 个。
- 只保留 `clean_include` 和 `uncertain_keep_low_weight` 点。
- 增加 clean 序列上的前点运动特征、hard break、uncertain break、tracklet index 和 `clean_tracklet_id_v8`。
- 这是 clean tracklet 的点级产品。

#### `smoothed_track_states_v8/`

- 每个 slice 一个 parquet，共 25 个。
- 保存平滑后的纬度、经度、高度、水平/垂直速度、mode probabilities、位置/高度 covariance 和 uncertainty radius。
- `state_source_role_v8` 标记为 `smoothed_observed`。
- 该版本没有把缺口预测密集写成 observed ADS-B；后续 Stage5 若使用 gap prediction，必须保持 prediction 语义并传播 covariance。

#### `clean_tracklet_summary_v8/`

- 每个 slice 一个 parquet，共 25 个。
- 每行对应一个 clean tracklet，而不是一个 ADS-B point。
- 包含 tracklet 起止时间、点数、起止状态、速度、covariance、consistency 分位数、tier 和 graph node allowed 标志。

#### `tracklet_graph_edges_v8/`

- 每个 slice 一个 parquet，共 25 个。
- 保存同一 exact identity/date 内的候选连接边。
- 包含 gap、forward/backward Mahalanobis、位置/高度 residual、速度差、vertical-rate 差、bridge prior、physical gate 和 `formal_bridge_accepted_v8`。
- Stage2 中 `formal_bridge_accepted_v8` 必须全部为 false。

#### `track_graph_paths_v8/`

- 每个 slice 一个 parquet，共 25 个。
- 保存 clean single path 和 stitched hypothesis path。
- `path_prior_weight_v8` 只是 Stage2 prior，不是 Stage3 calibrated posterior。

#### `slice_reports/`

- 每个 slice 一个 JSON，共 25 个。
- 记录输入点数、clean 点数、被隔离点数、legacy-compatible leg 数、tracklet 数、singleton 数、edge 数、physical edge 数、异常分布和 point role 分布。
- 用于发现某一个 slice 是否出现局部异常。

### 4. smoke 的最终文件

在 `stage2_track_graph_v8/` 根下还存在三个 consolidated parquet 和一个总报告：

#### `clean_tracklet_summary_v8.parquet`

把 25 个 summary shards 通过 streaming concat 合并后的 smoke 总表。

#### `tracklet_graph_edges_v8.parquet`

把 25 个 edge shards 合并后的 smoke 总边表。

#### `track_graph_paths_v8.parquet`

把 25 个 path shards 合并后的 smoke 总路径表。

#### `stage2_v8_track_graph_report.json`

smoke 的机器可读总报告，包含：

- totals；
- point conservation；
- fragmentation delta；
- graph candidate 数；
- Stage2 formal bridge invariant；
- truth/holdout invariant；
- quality gate。

### 5. smoke 结果的地位

smoke 曾经通过：

- point conservation；
- fragmentation not worse；
- Stage2 formal bridge accepts 为 0；
- Stage3 graph candidates 非零。

但它不是最终结果。更重要的是：正式 Stage2 后续修正了 identity normalization，将 `B-1353` 统一为 `B1353`，正式 Stage2/Stage3 已重新全量运行；smoke 目录保留为历史调试记录，不应作为当前最终指标来源。

---

## 五、Stage2 正式结果文件夹说明

目录：

`优化/数据处理/stage2_v8_track_graph_optimized_20260716/`

这是**唯一应作为 Stage2 最终结果依据的目录**。总大小约 `12G`，共 208 个文件、10 个目录层级。

### 1. 为什么正式 Stage2 约 12G

这不是 25 份全量输入复制，而是不同语义层的正式产品：

- raw selected input shards：约 454M；
- local consistency points：约 2.4G；
- clean tracklet points：约 3.1G；
- smoothed states：约 4.6G；
- summaries、edges、paths 和 reports：其余空间。

每一种产品都服务于不同的追溯和后续计算：

- local 层用于审计原始点和异常；
- clean 层用于 tracklet 重建；
- smoothed 层用于 covariance-aware matching；
- summary 层用于 graph 节点；
- edge/path 层用于 Stage3/Stage5。

因此“没有复制 25 份全量输入”与“正式目录有多个全量派生产品”并不矛盾。

### 2. 正式根目录文件

#### `run_config.json`

正式 Stage2 的运行配置。关键字段：

- `input_path=/data/LFT-W02_data/pengxu/stage1_output/clean_loc.parquet`；
- `slice_count=25`；
- `workers=25`；
- `smoke_group_modulus=1`，表示全量；
- `max_graph_gap_s=1800`；
- `top_k=5`；
- `POLARS_MAX_THREADS=25`；
- 文档指定的 v4 派生表不存在，因此从同源 19,162,638 行 Stage1 ADS-B 表重建 compatible audit fields。

#### `source_input_manifest.json`

正式输入审计清单：

- 实际输入点数；
- 期望点数；
- 是否一致；
- 原始 schema；
- truth semantics。

该文件明确说明 Stage2 使用的是 ADS-B 源点，没有创建 AMDAR point-truth。

#### `stage2_v8_input_profile.json`

正式 25 个 input shards 的行数分配，总和为 `19,162,638`。它用于核对分片守恒，不是算法结果本身。

### 3. 正式 `stage2_track_graph_v8/` 子目录

正式子目录与 smoke 同名，但数据规模为全量。各目录的产品语义如下：

| 子目录 | 文件数 | 正式作用 |
|---|---:|---|
| `raw_input_shards_v8` | 25 | 分片后的紧凑工作输入，每点一次 |
| `local_consistency_points_v8` | 25 | 全量局部运动特征与异常解释 |
| `clean_tracklet_points_v8` | 25 | clean/uncertain 点和 clean tracklet id |
| `smoothed_track_states_v8` | 25 | 平滑状态、mode probability、covariance |
| `clean_tracklet_summary_v8` | 25 | 每个 tracklet 一个 summary |
| `tracklet_graph_edges_v8` | 25 | 候选 graph edges 与 Stage2 physical gate |
| `track_graph_paths_v8` | 25 | clean path 和 stitched hypothesis |
| `slice_reports` | 25 | 每个 slice 的机器审计报告 |

### 4. 正式 consolidated 文件

#### `clean_tracklet_summary_v8.parquet`

25 个 summary shards 的总表。后续 Stage3 选择 base tracklets 和 Stage5 构建候选节点时优先使用它。

#### `tracklet_graph_edges_v8.parquet`

25 个 edge shards 的总表，共约 `6,627,625` 条全部候选边，其中 `11,306` 条通过 Stage2 physical candidate gate。

后续 Stage5 不应直接使用全部边；必须使用 Stage3 v13 model 和 Stage5 covariance/path gates 再筛选。

#### `track_graph_paths_v8.parquet`

25 个 path shards 的总表，共约 `2,965,156` 条路径记录：

- clean single paths：约 `2,953,850`；
- stitched hypotheses：`11,306`。

这些 path 仍是 hypothesis/prior，不是 unique accepted product。

#### `stage2_v8_track_graph_report.json`

Stage2 最终机器报告。重点字段：

- `totals`：全量数量统计；
- `quality_gate`：点守恒、无提前接受、fragmentation、graph candidate 和 truth gate；
- `limitations`：v4 派生文件缺失、smoother 是简化 diagonal CV IMM-style、edge 尚未 calibrated。

### 5. 正式 Stage2 的结果判断

正式报告中的 `quality_gate` 全部通过：

```text
point_conservation = true
no_formal_bridge_acceptance_in_stage2 = true
fragmentation_not_worse = true
graph_candidates_nonzero = true
truth_holdout_violations = 0
```

所以 Stage2 已经完成“组织和候选生成阶段”，但没有完成 Stage5 的“正式匹配接受阶段”。

---

## 六、Stage3 smoke 文件夹说明

目录：

`优化/数据处理/stage3_v13_bridge_validation_smoke_20260716/`

### 1. smoke 输入与规模

它读取的是 `stage2_v8_track_graph_smoke_20260716`，不是正式 Stage2。主要配置：

- `max_base_tracklets=3000`；
- 实际 selected base tracklets：`1,571`；
- case bank：`16,635`；
- locked-test：`2,449`。

### 2. smoke 根目录文件

#### `run_config.json`

记录 smoke 的 Stage2 输入目录、Stage3 输出目录、slice/worker、最大 tracklet 数、最少点数和 seed。

#### `stage3_bridge_validation_v13/`

包含与正式 Stage3 相同的 6 类输出，但规模较小：

- `bridge_case_bank_v13.parquet`：smoke case bank；
- `bridge_case_scores_v13.parquet`：加入 edge/path posterior 的全部 smoke case；
- `bridge_locked_test_v13.parquet`：smoke locked-test 子集；
- `edge_path_posterior_model_v13.json`：smoke 校准模型；
- `stage3_v13_bridge_validation_report.json`：smoke 机器报告；
- `stage3_v13_quality_gate.json`：smoke gate 布尔值。

### 3. smoke 结果的地位

smoke 结果全部 gate 通过，但它只能证明代码和基本 policy 在小样本上工作。它不能替代正式 Stage3，原因有两个：

1. smoke case 数量远小于正式 case bank；
2. smoke 使用的是 Stage2 smoke 数据，而且生成时间早于最后一次 identity normalization 修正。

所以当前最终 Stage3 指标只能查看正式目录，不能查看 smoke 目录。

---

## 七、Stage3 正式结果文件夹说明

目录：

`优化/数据处理/stage3_v13_bridge_validation_optimized_20260716/`

这是**唯一应作为 Stage3 v13 最终结果依据的目录**，总大小约 `20M`，包含 8 个文件、2 个目录层级。

### 1. 根目录 `run_config.json`

记录正式 Stage3 配置：

- Stage2 正式输入目录；
- Stage3 输出目录；
- `slice_count=25`；
- `workers=25`；
- `max_base_tracklets=15000`；
- `minimum_points=12`；
- `seed=20260716`；
- `POLARS_MAX_THREADS=25`。

### 2. `stage3_bridge_validation_v13/` 子目录

正式 Stage3 结果目录包含 6 个文件。

#### `bridge_case_bank_v13.parquet`

Stage3 的原始 case bank。每行是一个 bridge validation case，包含：

- case id；
- source tracklet；
- tail/flight/date；
- corruption type；
- hard negative type；
- pseudo truth 是否接受 bridge；
- gap 是否为 prediction；
- gap seconds；
- forward/backward residual；
- position/altitude Mahalanobis；
- speed/heading/vertical-rate difference；
- covariance radius；
- calibration/validation/locked split。

它用于复核 case 构造和真值标签，不包含 AMDAR truth。

正式规模：`151,951` cases。

#### `bridge_case_scores_v13.parquet`

在 case bank 基础上加入模型分数：

- `edge_posterior_v13`；
- `path_posterior_v13`。

它用于分析不同 corruption/hard-negative 类型的 posterior 分布，不能直接当 Stage5 match 产品。

#### `bridge_locked_test_v13.parquet`

正式 locked-test 子集，包含固定后的 case、truth、features 和 posterior。它的唯一用途是最终报告 safety metrics，不能再用来反调阈值。

正式规模：`27,599` cases。

#### `edge_path_posterior_model_v13.json`

Stage3 v13 冻结模型参数，包含：

- features 列表；
- logistic weights；
- bias；
- feature mean/scale；
- Platt calibration slope/intercept；
- edge/path posterior threshold；
- unique path margin；
- maximum formal gap；
- locked-test 是否用于调参的标志。

Stage5 v8 若使用 graph unique/mixture，必须读取这个 JSON 的完整参数，不能只抄一个 threshold。

#### `stage3_v13_bridge_validation_report.json`

正式 Stage3 总报告，包含：

- counts；
- selected policy；
- validation metrics；
- locked-test metrics；
- corruption report；
- hard-negative report；
- model comparison；
- quality gate；
- truth semantics。

它是解释 Stage3 是否达标的主机器报告。

#### `stage3_v13_quality_gate.json`

只保存质量门布尔结果，便于脚本快速读取：

- wrong path；
- catastrophic；
- edge/path ECE；
- corruption false acceptance；
- same-identity wrong-tracklet；
- unreachable bridge；
- clean no-bridge retention；
- truth/holdout；
- `all_passed`。

### 3. 正式 Stage3 的结果判断

正式 `stage3_v13_quality_gate.json` 中：

```text
wrong_tracklet_path_le_1pct = true
catastrophic_lt_3pct = true
edge_ece_le_0_05 = true
path_ece_le_0_05 = true
each_corruption_false_accept_le_2pct = true
same_identity_wrong_tracklet_le_1pct = true
unreachable_bridge_le_0_5pct = true
clean_no_bridge_not_degraded = true
truth_holdout_violations_zero = true
all_passed = true
```

因此 Stage3 v13 已达标。但它授权的是“经过 policy 的 bridge/path 可以进入 Stage5 候选审计”，不是“所有 graph path 自动成为 unique match”。

---

## 八、Stage2 和 Stage3 分别做了什么

### Stage2 v8 做什么

Stage2 v8 解决的是：

> ADS-B 原始轨迹如何从点表组织成可追溯、可平滑、可构图的轨迹证据。

它做了：

1. 规范化 tail/flight/date identity；
2. 计算局部时间、距离、速度、垂直率、加速度和转弯特征；
3. 识别 isolated spike、timestamp bias、unreachable edge、sampling gap；
4. 不删除原始证据，只区分 clean、uncertain、diagnostic；
5. 重建 clean tracklets；
6. 生成平滑状态和 covariance；
7. 在同一 identity/date 内生成 graph edges；
8. 输出 single path 和 stitched hypothesis。

它没有做：

- 没有使用 AMDAR 作为 truth；
- 没有正式接受 bridge；
- 没有把 gap prediction 当 observed ADS-B；
- 没有完成真实 AMDAR–ADS-B Stage5 matching。

### Stage3 v13 做什么

Stage3 v13 解决的是：

> Stage2 生成的 graph bridge/path 是否足够安全，能否被校准成 posterior，并在 hard negatives 上保持低误接纳率。

它做了：

1. 建立 bridge-specific case bank；
2. 将 calibration、validation、locked-test 按 group 隔离；
3. 训练 edge/path posterior；
4. 选择 maximum formal gap、posterior threshold 和 safety gates；
5. 对 corruption 和 hard negatives 做专项报告；
6. locked-test 只报告，不调参；
7. 输出 Stage5 可以读取的 frozen model。

它没有做：

- 没有匹配全部真实 AMDAR batches；
- 没有产生 Stage5 unique match 产品；
- 没有覆盖 Stage5 v7 的 229/345 prior；
- 没有完成 Stage6 strict aircraft holdout sensitivity。

---

## 九、各阶段做到什么地步

| 阶段 | 当前完成程度 | 是否达标 | 还缺什么 |
|---|---|---|---|
| Stage2 v8 | 全量点表已组织、清洗、平滑、构图 | **已达标** | 需要 Stage5 v8 使用 graph 做真实 AMDAR matching |
| Stage3 v13 | bridge case bank、posterior、locked-test 全部完成 | **已达标** | 需要在真实 Stage5 小集合验证 utility |
| Stage5 v7 | frozen support-only matching 已完成 `229/345` | safety/merge target 已通过 | 旧 1% batch 利用率目标仍未达到 |
| Stage5 v8 | 尚未运行 | 尚未评价 | 需要实现 graph unique/mixture/rejected audit |
| Stage6 | 当前沿用已有 v7 gate/target branch | 未因本次 Stage2/3 自动完成 | 需要比较 graph unique/mixture 对 strict holdout 的影响 |

---

## 十、历史 5 个 stitched cases 的结果

Stage5 v7 历史审计中有 5 个 stitched batches，但其中两个属于同一个 identity/date group，因此对应 4 个 unique groups：

| identity/date | clean tracklets | physical graph edges | 结论 |
|---|---:|---:|---|
| `B1353/MF8286/2026-02-09` | 10 | 0 | 无可达 graph edge，保持 rejected/no-coverage |
| `B1661/3U3551/2026-02-17` | 4 | 0 | 两个历史 batch 同组，无可达 edge |
| `B1355/MF8773/2026-01-28` | 19 | 1 | 有一个 294 秒 physical hypothesis，可进入 Stage5 v8 小审计 |
| `B1820/3U6920/2026-02-13` | 4 | 0 | 无可达 graph edge，保持 rejected/no-coverage |

这说明 Track Graph 是“恢复已有证据”，不是“强行创造覆盖”。5 个 stitched cases 不要求全部接受。

---

## 十一、推荐保留与可后续清理的目录

### 建议永久保留

- `stage2_v8_track_graph_plan_20260716`：方案和交接依据；
- `stage2_v8_track_graph_optimized_20260716`：Stage2 正式全量产品；
- `stage3_v13_bridge_validation_optimized_20260716`：Stage3 正式验证产品；
- 对应正式脚本和最终分析/交接文档。

### 可作为历史调试记录保留，后续可压缩或清理

- `stage2_v8_track_graph_smoke_20260716`；
- `stage3_v13_bridge_validation_smoke_20260716`。

smoke 目录不是错误，也不是重复正式结果；它们记录了开发过程中的小样本调试和质量门迭代。但因为正式运行已经完成，若空间紧张，可以先压缩后再删除。当前不建议在没有备份的情况下直接删除。

---

## 十二、进入 Stage5 v8 前的准确启动条件

下一步应执行的是 **Stage5 v8 小集合 graph matching audit**，不是全量无条件接受：

1. 冻结 Stage5 v7 的 `229 unique batches / 345 rows`；
2. 读取 Stage2 v8 summary、smoothed states、edges、paths；
3. 读取 Stage3 v13 完整 `edge_path_posterior_model_v13.json`；
4. 先审计历史 5 cases、graph-recoverable rejects、hard negatives 和 prior regression；
5. 使用 covariance-normalized emission；
6. 输出 `unique`、`graph mixture`、`rejected/no-coverage` 三层；
7. mixture 不计 unique；
8. gap prediction 不计 observed ADS-B；
9. 所有 AMDAR 继续保持 `effective_strict_truth=false`、`holdout_eligible=false`、`estimated_time_is_strict_point_truth=false`；
10. 小集合满足 Stage5 safety + utility gate 后，才扩展到更大 candidate scope。

Stage5 v8 utility gate 至少满足以下一项：

- safe unique 增加 `>=3`；或
- calibrated mixtures 增加 `>=20`，且 Stage6 strict holdout sensitivity 有益；或
- graph 显著减少 fragmentation，并提高可解释 candidate coverage。

---

## 十三、权威结果文件索引

### Stage2

- 正式运行配置：`优化/数据处理/stage2_v8_track_graph_optimized_20260716/run_config.json`
- 输入清单：`优化/数据处理/stage2_v8_track_graph_optimized_20260716/source_input_manifest.json`
- 正式输入分片统计：`优化/数据处理/stage2_v8_track_graph_optimized_20260716/stage2_v8_input_profile.json`
- 正式总报告：`优化/数据处理/stage2_v8_track_graph_optimized_20260716/stage2_track_graph_v8/stage2_v8_track_graph_report.json`
- 正式结果分析：`优化/数据处理/stage2_v8_track_graph_optimized_20260716/stage2_v8_results_analysis_and_next_steps.md`

### Stage3

- 正式运行配置：`优化/数据处理/stage3_v13_bridge_validation_optimized_20260716/run_config.json`
- 正式 case bank：`优化/数据处理/stage3_v13_bridge_validation_optimized_20260716/stage3_bridge_validation_v13/bridge_case_bank_v13.parquet`
- 正式 case scores：`优化/数据处理/stage3_v13_bridge_validation_optimized_20260716/stage3_bridge_validation_v13/bridge_case_scores_v13.parquet`
- 正式 locked-test：`优化/数据处理/stage3_v13_bridge_validation_optimized_20260716/stage3_bridge_validation_v13/bridge_locked_test_v13.parquet`
- 冻结模型：`优化/数据处理/stage3_v13_bridge_validation_optimized_20260716/stage3_bridge_validation_v13/edge_path_posterior_model_v13.json`
- 正式总报告：`优化/数据处理/stage3_v13_bridge_validation_optimized_20260716/stage3_bridge_validation_v13/stage3_v13_bridge_validation_report.json`
- 质量门：`优化/数据处理/stage3_v13_bridge_validation_optimized_20260716/stage3_bridge_validation_v13/stage3_v13_quality_gate.json`
- 正式结果分析：`优化/数据处理/stage3_v13_bridge_validation_optimized_20260716/stage3_v13_results_analysis_and_next_steps.md`

### 联合审计

- `优化/数据处理/stage2_stage3_v8_v13_joint_audit_20260716.json`
- `优化/数据处理/stage2_stage3_v8_v13_joint_results_and_next_steps_20260716.md`
- `优化/数据处理/next_agent_handover_after_stage2_v8_stage3_v13_20260716.md`

