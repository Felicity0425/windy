# AMDAR Unified Plan 阶段4：置信度数据模型重构汇报稿

生成时间：2026-07-02  
对应方案：`/data/LFT-W02_data/pengxu/优化/数据处理/amdar_unified_implementation_plan_20260701.md`  
对应输出目录：`/data/LFT-W02_data/pengxu/优化/数据处理/amdar_unified_stage3_v7_stage4_confidence_v2_optimized_20260701`  
对应核心产物：`stage4_confidence_v2/amdar_confidence_components_v2.parquet`、`stage4_confidence_v2/amdar_confidence_policy_v2.json`、`stage4_confidence_v2/confidence_tier_summary_v2.json`

---

## 1. 先纠正口径：这里的“阶段4”是什么

这里讲的阶段4，不是 centralized_v1 大框架里风场重构主流程的某个 Stage4，也不是 `amdar_unified_stage14_stage2_stage4_qc_superob_redesign_20260702` 目录里的那套重构质量 redesign。

这里讲的是 AMDAR Unified Plan 里的：

```text
阶段 4：置信度数据模型重构
```

它对应的原始设计目标非常明确：

```text
停止使用单一常数 obs_conf = 0.35 表示全部 AMDAR，
改为把每条 AMDAR 的“可用性、可信度、时间不确定性、匹配先验、批次代表性”
拆成可解释、可追溯的多组件置信度体系。
```

所以阶段4本质上不是“去证明 AMDAR 已经变成真值”，而是做三件事：

1. 把 AMDAR 从“全体一个固定分数”的粗糙状态，升级成逐条可解释的分层支持数据。
2. 明确保住 strict truth 边界，不允许任何置信度字段反推出真值资格。
3. 为后续 Stage5 真正的 AMDAR-ADS-B matching、Stage6 时间不确定性、Stage7 等级标定、Stage8 增强输出打基础。

---

## 2. 为什么必须做这个阶段4

### 2.1 原来的问题：全部 AMDAR 都是一个固定 `0.35`

Unified Plan 在阶段4之前，AMDAR 的一个核心问题是：

```text
虽然 AMDAR 仪器风值本身有价值，
但它的时间字段是批次下发/接收时间，不是逐点真实观测时间。
```

这意味着：

1. 它不能被当成 strict truth。
2. 但也不能因为不是 strict truth，就粗暴地给所有 AMDAR 一个完全相同的固定分数。

如果全部 AMDAR 都是 `obs_conf=0.35`，会带来几个明显问题：

1. 无法区分单点小批次和超大批次。
2. 无法区分风值干净记录和高风速异常记录。
3. 无法区分身份信息完整记录和身份缺失记录。
4. 无法区分有 ADS-B 身份日期先验支持的记录和完全没有先验支持的记录。
5. 下游 Stage2 / Stage4 / super-ob / assimilation 无法按层使用数据。

### 2.2 阶段4的核心思想

阶段4不是去“降低真值标准”，而是承认数据现实：

```text
真实 AMDAR 绝大多数不是逐点真时间，
所以它们不能进 strict holdout；
但它们仍然可以作为不同置信度层级的 support data 参与后续流程。
```

这就是 Unified Plan 的关键思想：

```text
不放宽 strict truth，
通过可解释的置信度体系尽可能利用 AMDAR。
```

---

## 3. 这次阶段4依赖了哪些上游结果

本次阶段4不是独立凭空运行，而是依赖了三个关键上游结果。

### 3.1 Stage1 v3 质量审计与下游动作

输入文件：

```text
/data/LFT-W02_data/pengxu/优化/数据处理/amdar_unified_stage1_2_complete_optimized_20260701/stage1_qc_resolution_v3/stage1_qc_resolution_table_v3.parquet
```

阶段4直接消费了其中这些能力：

1. `stage1_confidence_cap_v3`
2. `strict_holdout_eligible_v3`
3. `enhanced_holdout_eligible_v3`
4. `support_assimilation_eligible_v3`
5. `amdar_high_wind_review_required_v3`
6. `amdar_high_wind_exclude_pending_review_v3`
7. `amdar_high_wind_downweight_pending_review_v3`
8. `turb_enhanced_holdout_review_required_v3`

换句话说，阶段4不是自己重新发明一套 QC，而是在 Stage1 v3 已经审计过的数据基础上继续做分层。

### 3.2 Stage2 v6 ADS-B identity-date prior

输入文件：

```text
/data/LFT-W02_data/pengxu/优化/数据处理/amdar_unified_stage2_v6_stage3_pseudo_optimized_20260701/stage2_adsb_qc_v6_readiness/adsb_leg_quality_components_v6.parquet
```

这里提供的不是“真实 AMDAR-ADS-B 已匹配成功”的结果，而只是：

```text
同一 tail_norm + flight_norm + service_date_utc 上，
ADS-B 有没有可靠 leg 可作为身份日期先验。
```

这点必须特别强调：

```text
Stage2 v6 提供的是 identity-date prior，
不是 point-time accepted match。
```

### 3.3 Stage3 v7 pseudo-AMDAR 闭环验证

输入文件：

```text
/data/LFT-W02_data/pengxu/优化/数据处理/amdar_unified_stage3_v7_stage4_confidence_v2_optimized_20260701/stage3_pseudo_amdar_v7_compound_gate/pseudo_amdar_v7_calibration_report.json
```

阶段3 v7 给阶段4提供的意义是：

1. 证明 pseudo 场景下，复合 gate 的时间重建和航段筛选规则是可靠的。
2. 给阶段4提供一个“方法学层面的可信背景”。
3. 但不意味着真实 AMDAR-ADS-B matching 已完成。

本次阶段4里，Stage3 v7 结果被保存为诊断字段：

```text
stage3_v7_compound_gate_confidence = locked_test_selected_coverage * (1 - wrong_leg_rate_selected)
                                   = 0.8204158790170132 * (1 - 0.0030721966205837174)
                                   = 0.817895400
```

但要注意：

```text
这个字段被保存了下来，
但没有被纳入本次 base_support_conf 的加权几何平均。
```

它是背景诊断信号，不是直接加进最终支持置信度的一个组件。

---

## 4. 阶段4这次到底做了什么改动

这次阶段4的工作可以概括为八个方面。

### 4.1 从“单一常数”改成“多组件置信度”

旧口径的问题是：

```text
所有 AMDAR 都差不多一个分数，无法解释，也无法分层。
```

新口径把每条记录拆成多个组成项：

```text
source_conf
met_conf
time_source_conf
sequence_conf
identity_conf
adsb_leg_conf
adsb_match_conf
spatial_match_conf
spatial_representativeness_conf
density_conf
base_support_conf
```

这样每一条 AMDAR 的“为什么高、为什么低、为什么被拒绝”，都能追溯。

### 4.2 对 AMDAR 批次结构做了系统化建模

因为 AMDAR 的真实问题在于“批次语义”，所以阶段4没有把时间问题藏起来，而是明确建模：

1. 批次大小
2. 批次水平跨度
3. 批次垂直跨度
4. 飞行阶段
5. 批次内风速一致性
6. 由批次大小映射出的时间不确定性

这一步非常关键，因为它把 AMDAR 的最大现实约束显式写进了置信度。

### 4.3 把 Stage1 v3 的高风速审计落实到支持置信度里

本次实现里：

1. `> 200 m/s` 的 AMDAR 直接支撑置信度归零，进入人工复核/拒绝口径。
2. `150-200 m/s` 的 AMDAR 不直接当正常数据使用，而是大幅降权，保留为低置信度复核支持。

这样做的好处是：

```text
既没有简单粗暴地全删掉高风速记录，
也没有把明显异常值混进正常支持层。
```

### 4.4 明确保留 strict truth 边界

阶段4明确规定：

```text
No confidence field can create strict truth.
AMDAR remains support-only.
```

也就是说：

1. 再高的 `base_support_conf` 也不能把 AMDAR 升格成 T0 strict truth。
2. strict truth 仍然只能由原始数据语义和 Stage1 审计边界决定。

### 4.5 让 Stage2 identity-date prior 进入 Stage4，但不伪装成真实匹配

这次引入了：

```text
adsb_leg_conf
```

它表示的是：

```text
同一身份和日期上，有没有质量较好的 ADS-B leg 先验支持。
```

但同时明确保持：

```text
adsb_match_conf = 0
spatial_match_conf = 0
adsb_reconstructed = false
adsb_match_status = stage5_pending_no_real_amdar_adsb_match_yet
```

这说明阶段4很克制：

```text
允许使用 ADS-B 先验，
但不允许把“先验”说成“真实匹配已成功”。
```

### 4.6 引入 T0-T4 五层分级

阶段4最终不是只给一个连续分数，而是同时给：

1. 连续型 `base_support_conf`
2. 离散型 `confidence_tier`
3. 离散型 `confidence_grade`
4. 推荐用途 `recommended_stage4_role`

这样下游既可以用连续权重，也可以用分层规则。

### 4.7 让 TURB 的 holdout 边界更清楚

本轮总共有 181 条 TURB。

其中：

1. 175 条保留为 `T0 / S / strict_holdout`
2. 6 条被转成 `T4 / R / strict_holdout_review`

这说明阶段4不只是管 AMDAR，也顺便把真正 strict truth 的下游资格更严谨地表达出来了。

### 4.8 使用 25-slice 省空间口径

本轮运行策略是：

```text
slice_count = 25
POLARS_MAX_THREADS = 25
```

空间策略是：

```text
Single compact full confidence table with processing_slice_id;
no duplicated 25-way full intermediates.
```

意思是：

1. 用 25 slice 处理全量数据。
2. 只保留一份完整 confidence table。
3. 不复制 25 份全量中间产物。

这符合你要求的“省空间口径”。

---

## 5. 置信度是怎么计算的

这一部分是汇报最核心的内容。下面给的是“本次实际运行代码口径”，不是抽象设想。

## 5.1 组件清单

本次真正参与阶段4结构化输出的主要组件有：

```text
source_conf
met_conf
batch_conf
time_source_conf
sequence_conf
identity_conf
adsb_leg_conf
adsb_match_conf
spatial_match_conf
spatial_representativeness_conf
density_conf
base_support_conf_pre_stage1_cap
base_support_conf
time_uncertainty_s_stage4_v2
```

其中：

1. `batch_conf` 是批次层综合置信度。
2. `base_support_conf_pre_stage1_cap` 是加权几何平均后的原始支持置信度。
3. `base_support_conf` 是再经过 Stage1 cap 和硬拒绝后得到的最终支持置信度。

## 5.2 `source_conf`：数据源基准置信度

实际规则：

```text
TURB  = 1.00
AMDAR = 0.90
其他  = 0.70
```

它表达的是一个很朴素的事实：

```text
AMDAR 仪器风值本身不是低质量垃圾，
它的问题主要不是“源本身差”，而是时间语义和批次代表性。
```

所以 `source_conf` 并不低。

## 5.3 `met_conf`：气象质量置信度

本次 `met_conf` 先看硬异常，再看需要降权的异常。

### 硬拒绝条件

满足以下任一条件，`met_conf = 0`，并触发 `hard_reject_flag`：

1. 风速非有限值
2. 风向非有限值
3. `u_wind` 或 `v_wind` 非有限
4. 风速 < 0
5. 风速 > 200 m/s
6. 风向 < 0 或 >= 360
7. `uv_nonfinite_flag = true`
8. `stage1_confidence_cap_v3 <= 0`

### 降权条件

如果不是硬拒绝，则继续判断：

1. `150 < wind_speed <= 200 m/s`：`met_conf = 0.35`
2. 存在复核型异常：
   - `wind_speed_outlier_flag`
   - `temperature_outlier_flag`
   - `altitude_outlier_flag`
   - 或者 `uv` 计算风速与 `wind_speed` 的差值 `> 0.5`
   此时 `met_conf = 0.60`
3. 其他正常情况：`met_conf = 1.00`

这套规则的意义是：

```text
把“明显不可用”和“仍可保留但应降权”的情况分开。
```

## 5.4 `batch_conf`：批次特征综合置信度

`batch_conf` 是本次阶段4最重要的核心之一。它由四个因子相乘得到：

```text
batch_conf
  = batch_size_conf
  * spatial_representativeness_conf
  * sequence_conf
  * batch_met_consistency_conf
```

最后再截断到：

```text
[0.05, 0.85]
```

### 5.4.1 `batch_size_conf`：批次大小因子

规则如下：

```text
batch_row_count <= 1   -> 0.85
2-4                    -> 0.70
5-10                   -> 0.55
11-25                  -> 0.35
>= 26                  -> 0.15
```

含义很直接：

```text
批次越大，批次内每个点的真实时间不确定性越强，
逐点代表性越差。
```

### 5.4.2 `spatial_representativeness_conf`：空间代表性因子

基于批次水平跨度 `amdar_batch_hspan_deg` 和垂直跨度 `amdar_batch_vertical_span_m`：

```text
hspan < 0.1  且 vspan < 200    -> 1.00
hspan < 0.5  且 vspan < 500    -> 0.85
hspan < 1.0  且 vspan < 1000   -> 0.65
hspan < 2.0  且 vspan < 2000   -> 0.40
否则                            -> 0.15
```

它表达的是：

```text
一个批次在空间上越集中，
批次终止时间去代表其中各点的误差就越可控。
```

### 5.4.3 `sequence_conf`：飞行阶段/顺序因子

代码里用的是飞行阶段：

```text
LVR -> 1.00
ASC -> 0.85
DES -> 0.75
其他 -> 0.70
```

含义是：

1. 巡航阶段相对最稳定。
2. 爬升阶段变化较快。
3. 下降阶段变化通常更快、更复杂。

所以顺序信息在不同阶段的可用性不同。

### 5.4.4 `batch_met_consistency_conf`：批次内风场一致性因子

本次主要使用批次内风速标准差：

```text
单点批次                       -> 0.90
std < 5 m/s                    -> 1.00
5 <= std < 10                  -> 0.85
10 <= std < 20                 -> 0.70
std >= 20                      -> 0.50
```

这意味着：

```text
批次内风速波动越大，
越说明这批点可能跨越了更大的真实时空范围，
或者气象/记录质量更复杂。
```

## 5.5 `time_source_conf`：时间来源置信度

实际规则：

```text
TURB  -> 1.00
AMDAR -> clamp(batch_conf / 0.85, 0.05, 1.0)
其他   -> 0.50
```

这一步很重要，因为它直接把“AMDAR 的时间并非逐点真时间”编码进去了。

对 AMDAR 来说：

```text
时间来源置信度并不是来自真实 point-time，
而是来自批次结构本身。
```

## 5.6 `identity_conf`：身份完整性置信度

规则如下：

```text
机尾号和航班号都存在 -> 1.00
只有一个存在         -> 0.75
都缺失               -> 0.35
```

它表达的是：

```text
身份字段越完整，
越有利于下游匹配、分组和约束。
```

## 5.7 `adsb_leg_conf`：Stage2 v6 身份日期先验

本次 `adsb_leg_conf` 来自 Stage2 v6 identity-date prior。

其上限映射为：

```text
S0_core_clean_long_source               -> 0.90
S1_strong_component_b_long_source       -> 0.78
S2_broad_short_batch_threshold_source   -> 0.62
projection candidate only               -> 0.30
identity-date prior only / none         -> 0.00
```

这一步表达的是：

```text
如果同一身份和日期上确实存在更可信的 ADS-B leg，
那这条 AMDAR 至少有一个“身份日期上的航迹先验背景”。
```

但必须强调：

```text
它不等于这条 AMDAR 已经完成 point-time matching。
```

## 5.8 `adsb_match_conf` 与 `spatial_match_conf`

本轮阶段4里，这两个字段故意保持：

```text
adsb_match_conf   = 0
spatial_match_conf = 0
```

原因不是“忘了算”，而是策略上故意不造假：

```text
因为 Stage5 真正的 real AMDAR-ADS-B matching 还没有运行，
所以当前没有资格声称已经存在被接受的真实匹配质量和空间匹配质量。
```

这是阶段4最重要的边界自律之一。

## 5.9 `density_conf`：密度权重因子

规则为：

```text
density_conf = clamp(1 / sqrt(batch_row_count), 0.10, 1.00)
```

直觉上可以理解为：

```text
同一个大批次里的记录越多，
单条记录在统计意义上的独立增量越小，
所以每条点的额外权重应该被抑制。
```

## 5.10 `base_support_conf`：最终支持置信度

本次真正的核心公式是加权几何平均。

先计算：

```text
base_support_conf_pre_stage1_cap
```

再应用 Stage1 cap 与硬拒绝，得到：

```text
base_support_conf
```

### 公式

设组件为：

```text
source_conf
met_conf
time_source_conf
sequence_conf
identity_conf
adsb_leg_conf
spatial_representativeness_conf
density_conf
```

对应权重为：

```text
source_conf                     -> 1.0
met_conf                        -> 2.0
time_source_conf                -> 2.0
sequence_conf                   -> 1.0
identity_conf                   -> 1.0
adsb_leg_conf                   -> 0.5
adsb_match_conf                 -> 0.0
spatial_match_conf              -> 0.0
spatial_representativeness_conf -> 1.0
density_conf                    -> 1.0
```

总权重：

```text
1 + 2 + 2 + 1 + 1 + 0.5 + 1 + 1 = 9.5
```

于是：

```text
base_support_conf_pre_stage1_cap
= exp(
    (
      1.0 * ln(source_conf)
    + 2.0 * ln(met_conf)
    + 2.0 * ln(time_source_conf)
    + 1.0 * ln(sequence_conf)
    + 1.0 * ln(identity_conf)
    + 0.5 * ln(adsb_leg_conf)
    + 1.0 * ln(spatial_representativeness_conf)
    + 1.0 * ln(density_conf)
    ) / 9.5
  )
```

之后：

1. TURB 直接给 `base_support_conf_pre_stage1_cap = 1.0`
2. AMDAR 再截断到 `[0.0, 0.85]`
3. 若 `hard_reject_flag = true`，则 `base_support_conf = 0`
4. 否则：

```text
base_support_conf = min(base_support_conf_pre_stage1_cap, stage1_confidence_cap_v3)
```

### `stage1_confidence_cap_v3` 是怎么决定上限的

这里的 `stage1_confidence_cap_v3` 不是 Stage4 临时发明出来的，而是上一轮 Stage1 v3 QC resolution 已经给每条记录设好的“最高可用分上限”。

它的作用可以直接理解为：

```text
Stage4 先按自己的多组件公式算一个综合分，
但这个综合分不能突破 Stage1 先验质控给出的安全上限。
```

Stage1 的判定逻辑不是连续公式，而是保守分档：

```text
若 AMDAR >200 m/s，或者 AMDAR 存在硬气象质量问题
    -> stage1_confidence_cap_v3 = 0.0

若 AMDAR 在 150-200 m/s
    -> stage1_confidence_cap_v3 = 0.15

若 TURB 仍处于 enhanced holdout review
    -> stage1_confidence_cap_v3 = 0.0

其他正常情况
    -> stage1_confidence_cap_v3 = 1.0
```

更通俗地说：

1. `1.0`：Stage1 不额外卡你，后面可以按正常支持数据继续评分。
2. `0.15`：你没有被彻底否决，但 Stage1 认为你风险偏高，只能低置信度保留。
3. `0.0`：Stage1 已经判定你不能作为 support 使用，后续总分必须被压到 0。

所以 `base_support_conf = min(base_support_conf_pre_stage1_cap, stage1_confidence_cap_v3)` 的意思就是：

```text
Stage4 可以细化评分，
但不能推翻 Stage1 已经做出的更保守的安全封顶决定。
```

### 为什么用加权几何平均，而不是简单加法平均

因为阶段4想表达的是：

```text
某些短板是“乘法式惩罚”，
不是“均值稀释”。
```

例如：

1. 时间来源很差，不能靠别的高分轻松补回来。
2. 气象质量有问题，也不能靠身份完整性抵消。

几何平均比算术平均更适合这种“短板限制型”问题。

## 5.11 `time_uncertainty_s_stage4_v2`：阶段4时间不确定性

这次阶段4对 AMDAR 的时间不确定性不是连续拟合，而是先用批次大小给一个保守分段：

```text
1 点     -> 300 s
2-4 点   -> 600 s
5-10 点  -> 900 s
11-25 点 -> 1500 s
>=26 点  -> 1800 s
```

这些值不是说“我们已经知道每个点的真实误差正好就是这些秒数”，而是一个保守的分段时间不确定性口径。它背后的想法是：

1. 批次越小，批次时间去代表单点时间时，误差通常越可控。
2. 批次越大，说明这批点更可能覆盖了一段更长的飞行过程，单点真实时间离批次时间的偏差通常更大。
3. 因为当前 Stage4 还没有 Stage5 的真实 accepted point-time match，所以这里不能假装自己已经知道逐点时间，只能先给一个保守、可解释、单调递增的时间不确定性阶梯。

可以把这组分段理解成：

```text
单点批次：大约 5 分钟级不确定性
小批次：10 分钟级
中等批次：15 分钟级
较大批次：25 分钟级
超大批次：30 分钟级封顶
```

这样设计的好处是：

1. 它和 AMDAR 的批次语义一致，明确承认“批次时间不是逐点真时间”。
2. 它保证批次越大，时间不确定性不会反而更小，逻辑上单调一致。
3. 它给 T1/T2/T3 分层提供了直接可解释的时间门槛基础。

对 TURB：

1. 若通过 `strict_holdout_eligible_v3` 且非硬拒绝，则时间不确定性置 0。
2. 否则按 review 逻辑转入非 holdout。

这说明阶段4对 AMDAR 的时间不确定性建模仍然是保守口径，不是假装已经知道逐点真实时间。

---

## 6. T0-T4 的分布标准是什么

这一部分是汇报里必须讲清楚的，因为阶段4最后不是只给一个分数，而是给分层策略。

## 6.1 T0 / S：Strict Holdout

规则：

```text
仅 TURB
并且 strict_holdout_eligible_v3 = true
并且不是 hard reject
```

意义：

```text
这是真正的严格真值层，
是 holdout 验证可使用的最保守来源。
```

它对应的判断逻辑不是“支持数据里最优秀的一层”，而是：

```text
这类数据在时间语义上本来就属于 strict truth，
并且额外 QC 也没有把它排除出去。
```

所以 T0 的本质不是“高支持分”，而是“真值资格成立”。

这也是为什么：

1. T0 只允许 TURB 进入。
2. AMDAR 即使某些行支持置信度很高，也不能进入 T0。
3. T0 的含义是验证用真值，不是重构用 support。

本次 AMDAR：

```text
0 条进入 T0
```

汇报时可以直接强调：

```text
阶段4没有用置信度把 AMDAR 升格成真值，
这条 strict truth 边界是被明确守住的。
```

## 6.2 T1 / A：高置信度支持层

规则：

```text
base_support_conf >= 0.70
且 time_uncertainty_s <= 300
```

这类数据含义是：

```text
在支持数据内部已经算非常强，
但仍然只是 support-only，不是 strict truth。
```

它的直觉含义是：

```text
这条数据在综合质量上已经很好，
而且时间不确定性被压到了 5 分钟级以内，
因此可以作为最强的一档支持数据。
```

T1 通常对应的数据画像是：

1. 批次很小，甚至接近单点。
2. 空间跨度小。
3. 飞行阶段较稳定。
4. 批次内风值一致性较好。
5. 没有明显气象质量问题。
6. 没有被 Stage1 cap 额外压低。

但即使如此，它仍然不是 strict truth，原因在于：

```text
它的时间来源依然可能是批次语义推断出来的高可信 support，
而不是天然 point observation truth。
```

下游使用上，T1 更适合：

1. 作为 support 数据里权重最高的一层。
2. 用于较窄时间窗的支持约束。
3. 与 T2 区分开来，避免把所有 support 一视同仁。

## 6.3 T2 / B：中高置信度支持层

规则：

```text
base_support_conf >= 0.45
且 time_uncertainty_s <= 900
```

这是阶段4里最典型的“support assimilation candidate”层。

它的直觉含义是：

```text
这类数据已经足够像“可用支持观测”，
但还没有强到可以进入 T1。
```

T2 一般对应：

1. 小到中等批次。
2. 时间不确定性大约在 15 分钟级以内。
3. 批次结构、风值质量、身份信息总体较稳。
4. 可能存在一定批次语义不确定性，但仍然可控。

为什么 T2 很重要：

```text
如果 T1 是“少量高质量 support”，
那 T2 就是“规模上最有工程价值的一档可用 support”。
```

也就是说，在实际下游里，T2 往往是最像“主力支持层”的一层。

它适合：

1. support assimilation candidate
2. 中等时间窗下的支持约束
3. 作为比 T3 更强、比 T1 更充足的数据池

## 6.4 T3 / C：低置信度支持 / super-ob 层

规则：

```text
base_support_conf >= 0.25
且 time_uncertainty_s <= 1800
```

这类数据不适合被当成强约束，但仍适合：

1. 低权重 support
2. super-ob 聚合
3. 大尺度背景辅助

它的直觉含义是：

```text
这类数据还不能说“坏”，
但它们对单点、窄时间窗、强约束来说已经太不稳了。
```

典型原因往往是：

1. 批次更大。
2. 时间不确定性更宽。
3. 空间跨度更大。
4. 批次内部一致性一般。
5. 综合支持分还可以，但不足以进入 T2。

所以 T3 的正确使用方式不是“当成弱一点的 T2”，而是：

```text
把它看成有价值的低置信度背景支持信息。
```

它更适合：

1. 低权重融合
2. super-ob 后再用
3. 大尺度约束
4. 完整性补充，而不是强控制信号

这也是为什么本次结果里 T3 占比最高时，不应理解成“结果不好”，而应理解成：

```text
大部分 AMDAR 被成功保留为低置信度 support，
而不是被粗暴丢弃。
```

## 6.5 T4 / D 或 R：展示/拒绝层

规则：

```text
低于 T3
或 hard review / reject
```

其中 T4 实际上包含两种不同性质：

1. `D`：display_only_or_reject
   这类通常不是完全坏，只是不适合进入正式高权重支持层。
2. `R`：rejected_or_manual_review
   这类是明确被拒绝或要求人工复核。

这里最容易误解的一点是：T4 不全等于“脏数据”。

更准确地说，T4 包含两类完全不同的情况：

### 第一类：还能看、但不该正式强用

这就是 `D` 类。

比如：

1. 时间不确定性太宽。
2. 批次过大。
3. 空间跨度过大。
4. 综合支持分已经低于 T3 门槛。

这类数据未必是错的，但它们已经不适合进入正式高权重 support 流程。

### 第二类：明确风险太高，需要隔离

这就是 `R` 类。

比如：

1. 高风速严重异常。
2. 硬气象质量问题。
3. 需要人工复核后才能恢复资格。
4. 被 Stage1 cap 直接压到 0。

所以 T4 的工程意义不是简单“扔掉”，而是：

```text
把不适合正式支持使用的记录，从 T1/T2/T3 主支持流里清楚地隔离出来。
```

汇报时很适合强调：

```text
T4 是阶段4风险控制能力的体现。
它不是为了把数据做少，而是为了防止不合格数据混入正式支持层。
```

---

## 7. 本次阶段4的最终统计结果

这一部分使用的是本次实际运行输出的 `confidence_tier_summary_v2.json`。

## 7.1 总体规模

总评分行数：

```text
Total rows = 431,189
AMDAR rows = 431,008
TURB rows  = 181
```

## 7.2 T0-T4 总体分布

总体分布如下：

```text
T3 = 227,080  (52.6637%)
T2 = 114,363  (26.5227%)
T4 = 86,016   (19.9486%)
T1 = 3,555    (0.8245%)
T0 = 175      (0.0406%)
```

如果只看 AMDAR：

```text
T3 = 227,080  (52.6858%)
T2 = 114,363  (26.5338%)
T4 = 86,010   (19.9555%)
T1 = 3,555    (0.8248%)
T0 = 0
```

如果只看 TURB：

```text
T0 = 175  (96.6851%)
T4 = 6    (3.3149%)
```

这个分布非常有代表性，说明：

1. 大多数 AMDAR 被保留在 T2/T3，而不是直接丢弃。
2. 真正能到 T1 的比例很少，说明阶段4是保守而不是冒进的。
3. AMDAR 没有任何一条越界进入 T0，strict truth 边界守住了。

## 7.3 等级分布

```text
C = 227,080  (52.6637%)
B = 114,363  (26.5227%)
D = 83,217   (19.2994%)
A = 3,555    (0.8245%)
R = 2,799    (0.6491%)
S = 175      (0.0406%)
```

这里也能看出：

1. `C` 和 `B` 是主体。
2. `A` 很少，说明高置信度支持层没有被滥发。
3. `R` 占比不到 1%，说明明确硬拒绝是少数，但确实被严格隔离出来了。

## 7.4 推荐使用角色分布

```text
low_confidence_support_or_superob_only = 227,080  (52.6637%)
support_assimilation_candidate         = 117,918  (27.3472%)
display_only_or_reject                 = 83,217   (19.2994%)
rejected_or_manual_review              = 2,793    (0.6477%)
strict_holdout                         = 175      (0.0406%)
strict_holdout_review                  = 6        (0.0014%)
```

只看 AMDAR：

```text
support_assimilation_candidate         = 117,918  (27.3587%)
low_confidence_support_or_superob_only = 227,080  (52.6858%)
display_only_or_reject                 = 83,217   (19.3075%)
rejected_or_manual_review              = 2,793    (0.6480%)
```

这非常适合汇报时解释：

```text
阶段4不是简单地“要么全用、要么全扔”，
而是把 AMDAR 切成了不同使用角色。
```

## 7.5 质量动作分布

```text
none                                   = 426,678  (98.9538%)
reject_from_support_pending_provider_review = 2,793  (0.6477%)
wind_speed_gt_150_mps_downweighted     = 1,712    (0.3970%)
exclude_from_enhanced_holdout_pending_review = 6 (0.0014%)
```

这表明：

1. 大多数记录没有触发额外动作。
2. 高风速异常虽然比例不高，但确实被单独识别并处理了。

## 7.6 `base_support_conf` 分布

AMDAR 的最终支持置信度分布：

```text
min   = 0.000000
p10   = 0.178535
q50   = 0.353607
p90   = 0.621283
p99   = 0.847954
max   = 0.850000
```

这里非常值得汇报：

1. 中位数 `0.353607` 与旧的固定 `0.35` 很接近。
2. 但现在不再是“所有数据都等于 0.35”，而是形成了完整分布。
3. 这说明阶段4没有盲目整体抬高分数，而是在保持总体保守中心的同时，引入了必要的分层分辨率。

也就是说：

```text
阶段4不是把所有 AMDAR 都美化成高质量，
而是在总体依然保守的前提下，把真正更好和更差的数据分开。
```

## 7.7 时间不确定性分布

AMDAR 的 `time_uncertainty_s_stage4_v2`：

```text
min   = 300 s
p10   = 600 s
q50   = 900 s
p90   = 1800 s
p99   = 1800 s
max   = 1800 s
```

这组结果很重要，因为它客观反映了 AMDAR 的现实：

```text
绝大多数 AMDAR 仍然带着分钟级到半小时级的不确定性，
所以不能被伪装成 point observation。
```

## 7.8 批次大小分布

AMDAR 批次大小分布如下：

```text
5-10   = 174,731  (40.5401%)
26-49  = 141,832  (32.9070%)
2-4    = 57,266   (13.2865%)
11-25  = 30,896   (7.1683%)
50+    = 19,600   (4.5475%)
1      = 6,683    (1.5506%)
```

这里说明一个关键现实：

```text
真正单点批次很少，
大多数 AMDAR 不是“天然高置信度逐点记录”，
而是中到大型批次。
```

这也是为什么阶段4最终 T3 占比最高，而 T1 占比很低。

## 7.9 高风速异常统计

AMDAR 中：

```text
wind_speed > 150 m/s = 4,505 条  (1.0452%)
wind_speed > 200 m/s = 2,793 条  (0.6480%)
```

并且在本次统计结果中：

```text
>150 m/s 的 AMDAR 高风速组全部落在 T4
>200 m/s 的 AMDAR 最终 base_support_conf = 0
```

这说明高风速风险控制真正落地了，不是写在文档里但没执行。

## 7.10 Stage2 v6 identity-date prior 覆盖情况

AMDAR 中有：

```text
same identity-date ADS-B leg prior = 425,090 条
占全部 AMDAR 的 98.6269%
```

按最佳先验来源分布：

```text
S2_broad_short_batch_threshold_source = 276,527  (64.1582%)
identity_date_prior_only_no_matching  = 135,550  (31.4495%)
S0_core_clean_long_source             = 11,760   (2.7285%)
null                                  = 5,918    (1.3731%)
diagnostic_or_none                    = 720      (0.1671%)
S1_strong_component_b_long_source     = 533      (0.1237%)
```

这意味着：

1. 大部分 AMDAR 至少有某种 identity-date ADS-B 背景先验。
2. 但高质量 S0/S1 先验占比其实不高。
3. 绝不能把这 98.6% 误说成“98.6% AMDAR 已经匹配成功”。

这里非常容易出现一个口径误区，汇报时需要专门说明：

```text
阶段4确实已经把 AMDAR 和 ADS-B 做了“身份 + 日期”层面的先验关联，
所以每条 AMDAR 可以挂到一个 best_stage3_source_tier_v6_identity_date 标签上。
```

但这一步做成的只是：

```text
identity-date prior association
```

不是：

```text
real AMDAR-ADS-B point-time matching
```

更具体地说，现在阶段4回答的问题是：

```text
这条 AMDAR 在同一 tail_norm + flight_norm + service_date_utc 上，
背后有没有一个质量较好的 ADS-B 航段背景可以作为先验。
```

它还没有回答下面这些 Stage5 才该回答的问题：

1. 这条 AMDAR 具体对应哪一条 ADS-B leg。
2. 它在那条 leg 上对应哪个时间段。
3. 候选是否唯一，还是存在歧义。
4. 横向距离、垂直差、采样缺口是否满足真实接受条件。
5. 是否可以被接受为真实 point-time match。

也正因为如此，本轮 Stage4 的策略是明确保守的：

```text
adsb_leg_conf      可以非零
adsb_match_conf    必须为 0
spatial_match_conf 必须为 0
```

所以你看到这些 `S0/S1/S2/prior-only` 数量时，正确口径应该是：

```text
Stage4 已经完成了 AMDAR 到 ADS-B 的身份日期先验分层，
但还没有完成真实 AMDAR-ADS-B 时空匹配。
```

这也是为什么：

1. `S2_broad_short_batch_threshold_source` 占比很高，表示大量 AMDAR 背后确实存在某种 ADS-B 背景。
2. `identity_date_prior_only_no_matching` 也很多，表示不少 AMDAR 只能证明“同身份同日期存在 ADS-B”，但还不具备真实匹配条件。
3. `S0/S1` 很少，说明真正强背景先验其实不多，更不能据此把阶段4说成“匹配已经完成”。

## 7.11 Slice 运行一致性

本轮按 25 个 processing slice 运行后，每个 slice 的：

1. 行数都在约 17,247 到 17,249 之间
2. `base_support_conf_mean` 在约 `0.3858` 到 `0.3890` 之间

这说明：

```text
25-slice 口径没有造成明显的切片偏置，
全量结果在 slice 之间是稳定的。
```

---

## 8. 阶段3 v7 对阶段4的支撑结果

虽然这份汇报聚焦阶段4，但汇报时最好顺带说明阶段4为什么有资格刷新。

Stage3 v7 locked test 指标为：

```text
case_count              = 4,761
selected_case_count     = 3,906
selected_case_fraction  = 0.8204158790
matched_case_count      = 3,894
wrong_leg_count         = 12
wrong_leg_rate_selected = 0.0030721966
time_error_q50          = 2.283804 s
time_error_q90          = 6.85245 s
time_error_q99          = 326.04626 s
catastrophic_error_rate = 0.0024668155
```

质量门通过情况：

```text
validation_compound_gate_passes_targets = true
locked_test_available                   = true
locked_test_selected_coverage_gt_30pct  = true
locked_test_selected_q90_lt_5min        = true
locked_test_selected_catastrophic_lt_5pct = true
locked_test_selected_wrong_leg_le_1pct  = true
no_tail_date_split_leakage              = true
locked_test_not_used_for_threshold      = true
passed_stage3_v7_targets                = true
```

这给阶段4的意义是：

```text
阶段4引入 ADS-B 身份日期先验和 pseudo-AMDAR 方法学证据是有依据的，
不是无约束地抬高 AMDAR 权重。
```

但仍然必须加一句：

```text
Stage3 v7 证明的是 pseudo 场景下的方法可靠，
不等于真实 AMDAR-ADS-B matching 已完成。
```

---

## 9. 这次阶段4做法的好处和意义

这部分是汇报里非常适合展开讲的。

## 9.1 把“能不能用 AMDAR”从二元问题变成层级问题

阶段4之前，容易出现两种极端：

1. 因为 AMDAR 不是 strict truth，就觉得它几乎不能用。
2. 因为 AMDAR 数据量大，就想把它当成普通逐点观测来用。

阶段4的意义就在于打破这个二元对立：

```text
AMDAR 不是 strict truth，
但它仍然可以按不同置信度层级参与支持。
```

## 9.2 让每个置信度都可追溯、可解释

阶段4不是黑盒打分，而是明确告诉下游：

1. 源本身怎么样
2. 风值质量怎么样
3. 批次时间问题有多严重
4. 身份信息是否完整
5. 有没有 Stage2 的身份日期先验
6. 批次代表性是否足够
7. 这条记录最后为什么落在 T1/T2/T3/T4

这对后续研究和汇报都很重要。

## 9.3 保护 strict truth 体系不被稀释

阶段4最大的制度意义之一是：

```text
它没有为了“多利用数据”而偷偷放松真值标准。
```

这点很关键，因为如果一旦允许高置信度 AMDAR 反推出 strict truth，那么整个 holdout 体系就会被污染。

阶段4明确避免了这个问题。

## 9.4 为 Stage5 真匹配提供了清晰的前置边界

本轮把：

```text
adsb_leg_conf
```

和：

```text
adsb_match_conf = 0
spatial_match_conf = 0
```

同时存在下来，实际上是给 Stage5 划了一条非常清楚的界线：

1. 当前可以承认存在 identity-date prior。
2. 但当前还不能声称真实 point-time match 已经成立。

这让后续 Stage5 的目标更加清晰，也避免口径混乱。

## 9.5 为后续 Stage6/7/8 提供直接输入

阶段4产出的连续置信度和分层字段，后续可以直接服务于：

1. Stage6 时间不确定性建模
2. Stage7 A/B/C/R 阈值标定
3. Stage8 增强版 Stage1 输出
4. 下游 super-ob / assimilation / support selection

所以阶段4不是孤立产物，而是后续整个 workflow 的中间枢纽。

---

## 10. 如何评价这次结果：达标吗，满意吗

## 10.1 从完成检查看：达标

本轮阶段4 completion checks 全部通过：

```text
no_fixed_035_only                    = true
confidence_components_present        = true
strict_truth_not_derived_from_confidence = true
amdar_effective_strict_truth_rows    = 0
amdar_t0_rows                        = 0
turb_enhanced_holdout_eligible_is_175 = true
turb_review_rows_is_6                = true
stage5_match_not_fabricated          = true
stage2_v6_identity_prior_present     = true
stage3_v7_gate_passed                = true
gt200_amdar_base_support_zero        = true
passed                               = true
```

从规则完成度上讲，这一轮是达标的。

## 10.2 从分布形态看：结果是保守且合理的

这次分布有几个很合理的特征：

1. T1 很少：
   说明系统没有把 AMDAR 过度乐观地抬成“高质量逐点观测”。
2. T2/T3 占主体：
   说明大部分 AMDAR 被保留为可用支持数据，而不是全扔掉。
3. T4 约 20%：
   说明系统确实对代表性差、大批次或异常值做了隔离，不是所有数据都硬塞进 support。
4. 中位数 `0.3536` 接近旧 `0.35`：
   说明新模型在总体上仍保守，没有整体失真上抬。

这组结果从工程上是让人满意的。

## 10.3 但阶段4还不是终点

虽然这次结果达标并且适合作为阶段性成果，但也要清楚它的边界：

1. `adsb_match_conf` 仍为 0。
2. `spatial_match_conf` 仍为 0。
3. AMDAR 的时间不确定性仍是批次保守分段，不是真实 point-time 重建。
4. 大量记录仍集中在 T3，说明它们适合低权重 support，不适合高权重强约束。

所以：

```text
阶段4是“把 AMDAR 支持数据体系整理清楚了”，
不是“把真实 AMDAR 时空匹配问题彻底解决了”。
```

---

## 11. 汇报时必须强调的边界

为了避免口径失真，汇报里建议明确讲下面几句。

### 11.1 不能说“AMDAR 已经成为真值”

正确说法：

```text
AMDAR 仍然是 support-only，
严格真值仍由 TURB 等真正 point-observation 数据承担。
```

### 11.2 不能说“Stage4 已完成真实 AMDAR-ADS-B matching”

正确说法：

```text
Stage4 只引入了 Stage2 v6 identity-date prior，
没有运行 Stage5 真实 accepted point-time matching。
```

### 11.3 不能说“98.6% AMDAR 已匹配成功”

正确说法：

```text
98.6% AMDAR 具有 same identity-date ADS-B prior，
这只是先验覆盖，不是匹配成功率。
```

### 11.4 不能说“T1 就等于真值”

正确说法：

```text
T1 是 support-only 的高置信度层，
不是 strict holdout truth。
```

---

## 12. 一段适合直接汇报的总结口径

可以把本次阶段4概括成下面这段话：

```text
Unified Plan 的阶段4，本质上是把 AMDAR 从“全体一个固定 0.35 分”的粗粒度支持数据，
重构成一套逐条可解释、可追溯、可分层使用的置信度体系。
它没有放松 strict truth 标准，也没有把 identity-date ADS-B prior 伪装成真实匹配，
而是在 Stage1 v3 质量审计、Stage2 v6 ADS-B 先验、Stage3 v7 pseudo-AMDAR 验证的基础上，
为 431,008 条 AMDAR 建立了从 T1 到 T4 的支持层级，并把 175 条 TURB 保持在 T0 strict holdout。

从结果看，阶段4成功消除了固定 0.35 的单值问题，最终形成了以 T2/T3 为主体、T1 极少、T4 受控隔离的保守分布。
AMDAR 的 base_support_conf 中位数为 0.3536，和旧口径总体保守程度接近，但已经具备了足够的分辨率来区分更适合 assimilation 的支持数据、
仅适合低权重 support/super-ob 的数据，以及应当展示或拒绝的数据。

因此，阶段4的意义不在于把 AMDAR 变成真值，而在于在不污染真值边界的前提下，把 AMDAR 真正变成“可分层使用的支持数据体系”，
并为后续 Stage5 真实匹配、Stage6 时间不确定性和 Stage7 等级标定提供了可靠起点。
```

---

## 13. 相关文件建议同时查看

建议汇报前同时熟悉以下文档：

1. `优化/teacher_reports/unified_plan_stage3_pseudo_amdar_teacher_report_20260702.md`
2. `/data/LFT-W02_data/pengxu/优化/数据处理/amdar_unified_implementation_plan_20260701.md`
3. `/data/LFT-W02_data/pengxu/优化/数据处理/amdar_unified_stage3_v7_stage4_confidence_v2_optimized_20260701/stage4_confidence_v2/stage4_confidence_v2_report.md`
4. `/data/LFT-W02_data/pengxu/优化/数据处理/amdar_unified_stage3_v7_stage4_confidence_v2_optimized_20260701/stage3_v7_stage4_confidence_v2_results_analysis_and_next_steps.md`
5. `/data/LFT-W02_data/pengxu/优化/数据处理/amdar_unified_stage3_v7_stage4_confidence_v2_optimized_20260701/stage4_confidence_v2/amdar_confidence_policy_v2.json`
6. `/data/LFT-W02_data/pengxu/优化/数据处理/amdar_unified_stage3_v7_stage4_confidence_v2_optimized_20260701/stage4_confidence_v2/confidence_tier_summary_v2.json`
