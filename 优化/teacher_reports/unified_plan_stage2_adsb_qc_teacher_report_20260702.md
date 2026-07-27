# AMDAR Unified Plan 阶段2：ADS-B QC 和航段分级审计汇报稿

生成时间：2026-07-02  
对应文档：`/data/LFT-W02_data/pengxu/优化/数据处理/amdar_unified_implementation_plan_20260701.md`  
对应小节：`阶段 2：ADS-B QC 和航段分级审计（高优先级）`

---

## 1. 先纠正口径：这里的“阶段2”不是大框架 Stage2

这里讲的阶段2，不是 centralized_v1 大框架里那个“把观测映射到三维网格”的 Stage2。

这里讲的是 AMDAR Unified Plan 里面的阶段2：

```text
阶段 2：ADS-B QC 和航段分级审计
```

它的核心任务是：

```text
把 ADS-B/location 原始轨迹点整理成一段段可解释、可分级、可审计的 ADS-B 航段 leg，
并查清为什么高质量 A 级 leg 一开始那么少。
```

更通俗一点说：

原始 ADS-B 数据是一堆飞机位置点。阶段2要做的是把这些点串成“飞机这一段时间内连续飞行的一条航迹”，然后判断这条航迹质量好不好，能不能用于后续 pseudo-AMDAR 验证、时间重建、AMDAR-ADS-B 匹配候选。

所以这个阶段2不是直接处理风场重构，也不是最终匹配 AMDAR，而是为后面所有 ADS-B 相关任务打地基。

---

## 2. 为什么要做这个阶段2

### 2.1 背景问题

我们想用 ADS-B 轨迹帮助解决 AMDAR 的一个关键问题：

```text
AMDAR 的原始时间是批次下发/接收时间，不是逐点观测时间。
```

也就是说，同一个 AMDAR 批次里可能有很多点，这些点真实发生的时间不同，但原始表里只有一个批次时间。

如果我们能找到同一架飞机对应的 ADS-B 轨迹，就有可能沿着轨迹给 AMDAR 批次里的点估计更合理的逐点时间。

但是，在做 AMDAR-ADS-B 匹配之前，必须先问一个更基础的问题：

```text
ADS-B 轨迹本身可靠吗？
```

如果 ADS-B 航迹里有时间倒序、长时间缺口、位置跳变、速度离谱、跨日期错误连接，那么后面用它给 AMDAR 重建时间就会很危险。

所以 Unified Plan 把阶段2设为高优先级，先做 ADS-B QC 和航段分级审计。

### 2.2 阶段2要回答的核心问题

阶段2主要回答四个问题：

1. 为什么原先 A 级 ADS-B leg 很少？
2. ADS-B leg 被降级到底是因为时间问题、速度问题、位置跳变、采样缺口，还是身份问题？
3. 哪些 leg 可以作为后续 pseudo-AMDAR 的干净 source？
4. 哪些 leg 只能做 identity/date prior，不能用于真实匹配？

这一步的意义非常大：

```text
如果阶段2没有把 ADS-B 航段质量讲清楚，后面 Stage3 pseudo、Stage5 real matching、时间不确定性建模都会没有可靠基础。
```

---

## 3. 阶段2的输入是什么

阶段2主要输入是 ADS-B/location 数据。

规模：

```text
ADS-B/location rows = 19,162,638
```

每一行大致表示某架飞机在某个时间的位置和状态，包括：

- `tail_norm`：归一化机尾号
- `flight_norm`：归一化航班号
- `service_date_utc`：服务日期
- `time_utc`：ADS-B 点时间
- `lat_clean / lon_clean`：经纬度
- `alt_meters`：高度
- `heading_deg`：航向
- `ground_speed_ms`：地速

注意：

```text
ADS-B/location 是飞机运动轨迹，不是风观测。
```

它的作用不是直接提供风速风向，而是帮助我们判断飞机走过哪里、何时走过、轨迹是否连续，从而为 AMDAR 时间重建和匹配提供几何/时间依据。

---

## 4. 阶段2的整体流程

阶段2可以分成六步讲。

### 第一步：按飞机和航班排序

首先把 ADS-B 点按以下键排序：

```text
tail_norm
flight_norm
time_utc
lat_clean
lon_clean
alt_meters
```

为什么要排序？

因为后面所有相邻速度、相邻距离、采样间隔，都必须基于时间顺序计算。

如果没排序，两个不相邻的点被拿来算速度，就会出现大量假异常。

这一点在阶段2里很关键：

```text
必须先排序，再计算相邻点差分。
```

### 第二步：计算相邻点之间的差

对同一架飞机、同一航班的相邻 ADS-B 点，计算：

- 时间差 `dt_from_prev_seconds`
- 水平距离 `distance_from_prev_haversine_km`
- 表观地速 `apparent_ground_speed_haversine_mps`
- 高度跳变 `alt_jump_m`
- 是否跨日期
- 是否时间非递增

通俗解释：

我们要看飞机从上一个点到当前点是否合理。

例如：

- 60 秒飞了 8 km，大概 133 m/s，可能合理。
- 60 秒飞了 900 km，明显不合理。
- 两个点时间一样但位置不同，不合理。
- 中间隔了几小时再接上，不应该算作同一段连续航迹。

### 第三步：识别“坏边”

阶段2不是只看单个点，而是看相邻点之间的连接是否可信。这个连接可以叫 edge。

常见坏边包括：

```text
hard_speed_edge          速度离谱
hard_sampling_gap_edge   采样缺口过长
hard_position_jump_edge  位置突然跳变
hard_altitude_edge       高度突然大跳
date_boundary_edge       跨日期边界
non_increasing_time      时间不递增
```

这些坏边不一定说明前后所有点都坏，但说明“不能把坏边两侧当成一条连续航迹”。

### 第四步：重新切段，生成 ADS-B leg

这是 v4 的关键优化。

早期做法容易出现一个问题：一条长航迹中间有一个坏边，整条 leg 都被污染。

v4 的修复方法是：

```text
遇到坏边就切开，从坏边后面重新开始一个新的 leg。
```

这样做的意义是：

- 坏点/坏边不会拖累后面本来正常的航迹。
- 可用 ADS-B 片段数量显著增加。
- 每段 leg 的质量更容易解释。

通俗比喻：

如果一串珠子中间有一颗坏珠子，不应该把整串都丢掉，而是从坏珠子那里剪开，保留两边好的部分。

### 第五步：给每条 leg 计算质量组件

每条 leg 不再只给一个 A/B/C 总分，而是拆成多个质量组件。

主要组件：

```text
leg_time_quality       时间序列质量
leg_geometry_quality   几何轨迹质量
leg_identity_quality   身份一致性
leg_sampling_quality   采样密度质量
leg_phase_quality      飞行阶段一致性
leg_overall_quality    综合等级
```

为什么要组件化？

因为只给一个 C，后面不知道它为什么 C。

组件化后可以解释：

- 是时间缺口太大？
- 是速度异常？
- 是身份缺失？
- 是点数太少？
- 是高度变化和飞行阶段不一致？

这就是“可审计”的核心。

### 第六步：给下游用途分级

这是 v5/v6 的关键。

有些 leg 质量是 A/B，但仍然不能直接做真实匹配，因为它可能太短、太碎、只适合做 identity/date prior。

所以阶段2不仅要判断“质量好不好”，还要判断“能用来干什么”。

v6 最终形成了分层：

```text
S0_core_clean_long_source
S1_strong_component_b_long_source
S2_broad_short_batch_threshold_source
P_identity_date_prior_only_no_matching
D_diagnostic_or_reject
```

含义：

- S0：最干净的长航段，可作为核心 pseudo source。
- S1：B 级组件但无硬失败的强候选长航段。
- S2：短批次阈值验证 source，只能用于 short-batch pseudo validation。
- P：只有 identity/date prior 价值，不能用于 matching。
- D：诊断或拒绝。

---

## 5. v3 做了什么，结果说明了什么

### 5.1 v3 的主要工作

v3 是第一轮组件化 ADS-B QC。

它做了：

- 对 ADS-B rows 进行行级 QC。
- 构建 ADS-B leg。
- 给每条 leg 输出失败原因。
- 输出每个 leg 的质量组件。

输出包括：

```text
adsb_qc_v3_rows.parquet
adsb_leg_failure_reason_summary.json
adsb_leg_quality_components.parquet
```

### 5.2 v3 结果

```text
ADS-B rows audited: 19,162,638
usable legs >=5 points: 375,207
A: 127
B: 2,806
C: 372,274
```

主要失败原因：

```text
failed_speed: 364,811
failed_sampling_gap: 219,696
failed_position_jump: 88,312
failed_altitude: 87,742
failed_phase_consistency: 17,510
```

### 5.3 v3 结果分析

v3 结果显示 A/B 级 leg 很少，说明原始 ADS-B 轨迹里确实存在大量质量问题。

但进一步看后发现，问题不只是 ADS-B 数据差，而是切段策略也有问题：

```text
一些坏边污染了整条 leg。
```

比如一条航迹中有一个速度异常边，v3 可能把整条航迹都判成 C。

因此 v3 的结论是：

```text
必须重新切段，让坏边成为断点，而不是让坏边污染整条航迹。
```

---

## 6. v4 做了什么，为什么结果大幅改善

### 6.1 v4 的核心改动

v4 的核心是 resegmentation，也就是重新切段。

切段规则：

```text
遇到以下情况就开新 leg：
- hard speed edge
- hard sampling gap
- hard position jump
- large altitude jump
- date boundary
- non-increasing time
```

并且在新 leg 开始时，坏边不再计入新 leg 内部失败。

这句话很重要：

```text
坏边只是断点，不再污染断点后的新航段。
```

### 6.2 v4 结果

```text
ADS-B rows: 19,162,638
segmented_leg_count_all: 2,991,827
segmented_leg_count_min_points: 2,048,446
```

质量统计：

```text
A: 13,434
B: 1,918,580
C: 116,432
raw A/B usable legs: 1,932,014
```

相对于 v3：

```text
A: +13,307
B: +1,915,774
C: -255,842
```

### 6.3 v4 结果分析

v4 说明：原来很多 leg 被判坏，不是因为全段都坏，而是因为坏边没有被正确切开。

v4 之后 raw A/B 暴增，说明重切段是有效的。

但这里有一个新的风险：

```text
raw A/B 很多，不等于都可以做 Stage3 source，更不等于可以做真实 AMDAR-ADS-B matching。
```

为什么？

因为大量 B 类 leg 是短碎片。

短碎片可能局部质量不错，但：

- 太短，不足以支持长批次 AMDAR 时间重建。
- 只能提供 identity/date prior。
- 容易在真实匹配中产生歧义。

所以 v4 解决了“坏边污染”的问题，但还没有解决“下游怎么用”的问题。

---

## 7. v5 做了什么：不再只看 A/B 总数

### 7.1 v5 的核心思想

v5 增加了 downstream readiness gate。

也就是说，除了 A/B/C，还要告诉后续阶段：

```text
这条 leg 可以用于什么？
```

v5 强制使用两个字段：

```text
match_readiness_tier_v4
stage2_downstream_use_class_v5
```

### 7.2 v5 的分类

v5 把 leg 分成：

```text
S_stage3_clean_source
M1_strong_candidate_not_stage3_source
M2_broad_prior_needs_stage3_threshold
P_identity_date_prior_only_no_matching
D_diagnostic_or_reject
```

解释：

- S：可以作为 Stage3 pseudo 的干净 source。
- M1：强候选，但因为组件等级等原因不能直接进入 S。
- M2：可作为 broad prior 或阈值验证候选。
- P：只能做 identity/date prior，不能 matching。
- D：诊断或拒绝。

### 7.3 v5 结果

```text
raw A/B usable legs: 1,932,014
Stage3 clean source pool: 13,432
raw A/B not allowed as Stage3 source: 1,918,582
M1 strong but not Stage3 source: 565
M2 broad prior needing Stage3 threshold: 356,796
P identity/date prior only: 1,561,221
D diagnostic/reject: 116,432
```

### 7.4 v5 结果分析

v5 的最大意义是防止误判。

如果只看 raw A/B，我们会以为有 193 万可用 leg，可以直接进入真实匹配。

但 v5 告诉我们：

```text
真正严格干净、可作为 Stage3 source 的只有 13,432。
```

这说明：

- 阶段2已经比 v3/v4 更审慎。
- raw A/B 只能作为诊断数字，不能作为下游准入。
- broad real AMDAR-ADS-B matching 仍然不允许。

---

## 8. v6 做了什么：解决 v5 source pool 太窄的问题

### 8.1 为什么需要 v6

v5 太保守，Stage3 clean source pool 只有 13,432。

这个数量不是完全不能用，但对 pseudo validation 来说覆盖不够理想。

我们希望 Stage3 pseudo 覆盖：

- calibration / validation / locked_test
- ASC / DES / LVR 三种飞行阶段
- 不同 batch size
- 不同 tail/date group

如果 source pool 太窄，pseudo 验证可能不够稳定。

### 8.2 v6 的核心思路

v6 没有简单放开 raw A/B，而是做了分层 source pool。

分为：

```text
S0_core_clean_long_source
S1_strong_component_b_long_source
S2_broad_short_batch_threshold_source
```

解释：

#### S0：核心干净长航段

这是继承 v5 的最严格 source。

特点：

- A 级
- 点数足够
- 持续时间足够
- path length 足够
- gap 小
- 无硬失败

#### S1：强 B 类长航段

这些 leg 不是 A，但没有硬失败。

它们可能因为某些组件是 B 而不能进 S0，但仍然可作为长航段补充 source。

#### S2：短批次阈值验证 source

这些主要来自 M2。

它们适合 short-batch pseudo validation，但不能直接用于真实匹配。

这是 v6 最重要的边界：

```text
S2 只能用于短批次 pseudo validation 和阈值校准，不能直接 real matching。
```

### 8.3 v6 结果

```text
raw A/B usable legs: 1,932,014
v5 core clean source pool: 13,432
v6 tiered pseudo source pool: 370,786
candidate projection pool: 370,788
```

source tier：

```text
S0_core_clean_long_source: 13,432
S1_strong_component_b_long_source: 561
S2_broad_short_batch_threshold_source: 356,793
P_identity_date_prior_only_no_matching: 1,561,221
D_diagnostic_or_reject: 116,432
M1_hold_for_threshold_or_reject_diagnostics: 4
M2_prior_only_failed_v6_source_requirements: 3
```

Stage2 v6 readiness checks 全部通过：

```text
v6_source_tier_present: True
v6_pseudo_source_pool_nonzero: True
v6_pseudo_source_pool_failure_free: True
v6_all_split_phase_have_sources: True
v6_core_all_split_phase_have_minimum_sources: True
v6_short_batch_expansion_available: True
v6_long_batch_core_available: True
broad_real_match_still_blocked: True
stage2_ready_for_stage3_pseudo_v6: True
```

### 8.4 v6 结果分析

v6 解决了两个问题：

第一，解决 v5 source pool 太窄的问题。

```text
13,432 -> 370,786
```

第二，仍然没有违反保守边界。

虽然 source pool 扩大了，但不是 raw A/B 全放开，而是用途分层：

- S0/S1 可支持长航段 pseudo source。
- S2 只支持短批次 pseudo validation。
- P 仍然不能 matching。
- D 仍然诊断/拒绝。
- broad real matching 仍然 blocked。

这就是 v6 的价值：

```text
既解决覆盖不足，又不放松真实匹配准入。
```

---

## 9. 阶段2之后为什么要接 Stage3 pseudo 验证

阶段2自己只是说“这些 ADS-B leg 质量上看可以这样分层”。

但这个分层是否真的有用，必须用 Stage3 pseudo-AMDAR 测试。

Stage3 pseudo 的逻辑是：

1. 从 ADS-B leg 中抽取一段真实轨迹。
2. 把它伪装成 AMDAR 批次。
3. 只给 batch end time，不给逐点真实时间。
4. 让算法从候选 ADS-B leg 中找回它。
5. 因为答案已知，所以可以算时间误差和错误航段率。

这相当于在真实匹配前做闭环考试。

### Stage3 v6 验证结果

```text
source legs sampled: 4,923
pseudo cases: 15,000
locked_test cases: 4,761
```

全量接受所有 case 的结果：

```text
locked_test q90 time error: 1,928 s
catastrophic error rate: 10.58%
wrong-leg rate: 5.31%
```

这个结果说明：

```text
不能全量接受。
```

使用 validation-selected threshold 后的 locked_test：

```text
selected coverage: 69.84%
selected q50 time error: 2.35 s
selected q90 time error: 7.06 s
selected q99 time error: 379.82 s
catastrophic error rate: 0.369%
wrong-leg rate: 0.692%
no tail/date split leakage: True
```

这说明：

```text
阶段2 v6 的分层是有效的，但必须配合阈值选择和拒绝机制。
```

不能说“所有都能用”，只能说：

```text
高置信筛选后的那部分可用。
```

---

## 10. AMDAR 异常数据过滤在这个阶段2中的作用

严格说，AMDAR 异常风速过滤属于 Stage1/Stage14 support QC 前置处理，不是 Unified Plan 阶段2 ADS-B QC 的核心内容。

但它对后续阶段非常重要。

老师确认 AMDAR 中确实有异常数据，可以过滤。

当前口径：

```text
AMDAR wind_speed_ms > 150 m/s 先过滤，不进入 downstream support assimilation。
```

结果：

```text
AMDAR 总行数: 431,008
过滤 AMDAR 高风速异常行: 4,505
过滤后 AMDAR support rows: 426,503
TURB enhanced strict holdout rows: 175
TURB enhanced-QC review/filter rows: 6
```

这件事和 Unified Plan 阶段2的关系是：

1. 阶段2主要审计 ADS-B leg，不直接把 AMDAR 异常风当作 ADS-B leg 问题。
2. 但是后续 AMDAR-ADS-B matching 和 Stage4 support assimilation 会用到 AMDAR support。
3. 如果 AMDAR 异常强风不先过滤，会污染后续 confidence、matching 和 wind reconstruction。

所以对老师可以这样讲：

```text
阶段2重点解决 ADS-B 航迹质量问题；
AMDAR 异常风速过滤是进入后续支撑/匹配之前的前置质量控制。
两者共同保证后续不是用坏 AMDAR 去匹配坏 ADS-B。
```

---

## 11. 当前阶段2结果是否达标

### 11.1 达标的部分

我认为 Unified Plan 阶段2目前已经达到了原始目标。

原始目标是：

```text
查明 A 级 leg 只有 45 条的真实原因。
```

现在已经查明：

- 早期 A 级少，主要不是因为 ADS-B 完全不可用。
- 很多问题来自坏边污染整段 leg。
- v4 通过重切段把可用片段恢复出来。
- v5/v6 又进一步把 raw A/B 转成下游用途分级。

阶段2已经能解释：

- 每条 C 级 leg 为什么被降级。
- A/B leg 为什么不能全当 source。
- 哪些 leg 能做 pseudo source。
- 哪些只能做 prior。
- 哪些必须诊断或拒绝。

### 11.2 仍然不能做的事

阶段2虽然达标，但不等于可以真实 broad matching。

原因：

- full coverage pseudo 仍然失败。
- AMDAR 真实批次比 pseudo 更复杂。
- 存在 identity ambiguity。
- 真实 AMDAR 时间只有 batch end，不是逐点时间。
- S2 只是 short-batch threshold source，不是真实匹配许可。

所以当前结论是：

```text
阶段2适合支撑 Stage3 pseudo 阈值校准和 Stage5-prep 研究；
不适合直接进入 broad real AMDAR-ADS-B matching。
```

---

## 12. 对老师汇报时的建议说法

老师，这里的阶段2是 AMDAR Unified Plan 里的“ADS-B QC 和航段分级审计”，不是大框架里做三维体素化的 Stage2。这个阶段的目标是先把 ADS-B/location 点整理成可靠的航段 leg，并查清为什么早期 A 级 leg 很少。如果 ADS-B 航迹本身存在时间倒序、速度异常、位置跳变、采样缺口，后面用它给 AMDAR 重建时间或做匹配就会出错，所以必须先审计 ADS-B。

具体流程是：先按机尾号、航班号和时间排序；再计算相邻点之间的时间差、水平距离、表观速度和高度跳变；然后识别速度离谱、长时间缺口、位置跳变、高度大跳、跨日期、时间不递增等坏边；遇到坏边就切开，重新生成连续 ADS-B leg；最后给每条 leg 分别打时间质量、几何质量、身份质量、采样质量、飞行阶段一致性质量和综合等级。

最早的 v3 只做了组件化 QC，结果 A 级只有 127 条、B 级 2,806 条，C 级 372,274 条，说明质量问题很多。但进一步分析发现，很多 leg 是被中间的坏边污染了整段。v4 改成遇到坏边就重新切段，坏边不再污染后面的正常航迹，因此 raw A/B usable legs 提升到 1,932,014。不过我们没有直接把这 193 万都当作可用 source，因为里面很多是短碎片。

所以 v5 开始不只看 A/B，而是按下游用途分级。v5 发现真正严格干净、可作为 Stage3 source 的只有 13,432 条，raw A/B 里有 1,918,582 条不能直接当 Stage3 source。这说明只看 A/B 总数会误判。v6 进一步把 source pool 拆成 S0、S1、S2：S0 是核心干净长航段 13,432 条，S1 是强 B 类长航段 561 条，S2 是短批次阈值验证 source 356,793 条，总共得到 370,786 条分层 pseudo source。这样既解决了 v5 source pool 太窄的问题，又没有放开真实 broad matching。

为了验证阶段2分层是否可靠，我们跑了 Stage3 pseudo-AMDAR 闭环。全量接受所有 case 仍然失败，locked_test q90 时间误差 1,928 秒、灾难错误率 10.58%、wrong-leg 5.31%，说明不能无门槛使用。但用 validation 选出的阈值筛选高置信 case 后，locked_test selected coverage 达到 69.84%，q90 时间误差 7.06 秒，灾难错误率 0.369%，wrong-leg 0.692%，并且没有 tail/date split leakage。这说明阶段2 v6 的分层是有效的，但必须配合阈值和拒绝机制。

另外，老师确认 AMDAR 异常风速可以过滤后，我们把 `wind_speed_ms >150 m/s` 的 4,505 条 AMDAR 异常强风先过滤掉，过滤后 AMDAR support rows 为 426,503。这个过滤是进入后续 support assimilation 和匹配前的前置质量控制，不改变 truth 边界：AMDAR 仍然不是 strict truth，TURB 仍然是 conservative strict truth 来源。

最终结论是：Unified Plan 阶段2已经达到了“查清 ADS-B leg 质量问题并建立分级准入”的目标，可以支撑后续 Stage3 pseudo 阈值校准和 Stage5-prep 研究；但它仍然不支持直接 broad real AMDAR-ADS-B matching。

