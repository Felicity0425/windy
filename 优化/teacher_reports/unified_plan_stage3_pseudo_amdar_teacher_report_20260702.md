# AMDAR Unified Plan 阶段3：Pseudo-AMDAR 闭环独立重写汇报稿

生成时间：2026-07-02  
对应文档：`/data/LFT-W02_data/pengxu/优化/数据处理/amdar_unified_implementation_plan_20260701.md`  
对应小节：`阶段 3：Pseudo-AMDAR 闭环独立重写（高优先级）`

---

## 1. 先纠正口径：这里的“阶段3”不是大框架 Stage3

这里讲的阶段3，不是 centralized_v1 大框架里那个 Stage3 背景场或 ground-center 相关流程。

这里讲的是 AMDAR Unified Plan 里面的阶段3：

```text
阶段 3：Pseudo-AMDAR 闭环独立重写
```

它的核心任务是：

```text
在不使用真实 AMDAR 作为真值、不做真实 AMDAR-ADS-B matching 的前提下，
先用 ADS-B 自己构造“伪 AMDAR”，闭环验证时间重建和航段匹配方法是否可靠。
```

更通俗地说：

我们现在有一个现实问题：真实 AMDAR 的时间字段不是逐点观测时间，而是批次下发/接收时间。真实 AMDAR 每个点的真实时间不知道，所以不能直接拿真实 AMDAR 来判断“我重建出来的时间对不对”。

阶段3的做法是：

```text
既然真实 AMDAR 没有逐点真时间，
那就从 ADS-B 连续航迹里抽一段出来，假装它是一批 AMDAR。
因为这批点本来来自 ADS-B，所以每个点的真实时间我们是知道的。
然后故意只给算法一个类似 AMDAR 的“批次时间”和带噪声的位置，
让算法去找回对应 ADS-B 航段并重建每个点的时间。
最后拿算法估计时间和已知真时间比较。
```

这就叫 pseudo-AMDAR 闭环验证。

---

## 2. 为什么必须做这个阶段3

### 2.1 真实 AMDAR 不能直接拿来验证时间重建

AMDAR 数据量很大，有 431,008 条，看起来很有价值。但它最大的问题是：

```text
AMDAR 的 time_utc 是批次下发/接收时间，不是批次内每个点的真实观测时间。
```

比如一架飞机在爬升阶段累计了多个点，最后一次性下发。表里这些点可能有同一个时间，但真实观测时刻其实分布在前面一段飞行过程中。

这导致一个问题：

```text
我们不能直接用 AMDAR 原始 time_utc 当逐点真值。
```

如果直接用它评价时间重建算法，就相当于拿一个本身不是真时间的字段当答案，会把错误当正确，或者把正确当错误。

### 2.2 阶段3是为了先验证“方法能不能找回时间”

阶段3不是为了证明真实 AMDAR 已经能匹配 ADS-B。

阶段3要回答的是一个更基础的问题：

```text
如果我们知道一批点确实来自某条 ADS-B 航迹，
但只给算法类似 AMDAR 的批次信息，
算法能不能找回正确航段？
能不能把批次内每个点的时间估得足够准？
什么条件下可以接受，什么条件下必须拒绝？
```

只有这个闭环验证过了，后面才有资格讨论真实 AMDAR-ADS-B matching。

所以阶段3的意义是：

1. 不污染 truth 边界。
2. 不把 AMDAR 伪装成 strict truth。
3. 用已知答案的模拟任务验证时间重建方法。
4. 给后续 Stage5-V3 real matching 提供阈值依据。

---

## 3. 阶段3的输入是什么

阶段3主要使用阶段2输出的 ADS-B leg。

阶段2已经把原始 ADS-B/location 点整理成一条条航段，并完成质量分级。阶段3不直接从全部 ADS-B 点乱抽，而是使用阶段2 v6 的分层 source pool。

阶段2 v6 的关键输入结果是：

```text
V6 tiered pseudo source pool = 370,786 条 ADS-B leg
```

它们分成三类：

```text
S0_core_clean_long_source              13,432 条
S1_strong_component_b_long_source         561 条
S2_broad_short_batch_threshold_source 356,793 条
```

含义是：

- S0：核心干净长航段，最可靠。
- S1：质量略低但仍然较强的 B 类长航段。
- S2：短批次阈值验证 source，只能用于 pseudo validation，不能直接用于真实 broad matching。

这里很关键：

```text
阶段3使用 S0/S1/S2 做 pseudo-AMDAR 闭环验证，
但这不等于允许真实 AMDAR-ADS-B broad matching。
```

阶段3验证的是算法能力，不是给真实匹配放行。

---

## 4. 阶段3的整体流程

阶段3可以按 8 个步骤理解。

### 第一步：选择可靠的 ADS-B source leg

先从阶段2 v6 的 source pool 里抽取 ADS-B leg。

抽取时要保证不同飞行阶段都有覆盖：

```text
ASC：爬升
DES：下降
LVR：巡航 / 平飞
```

也要覆盖不同批次大小：

```text
1
2-4
5-10
11-25
26-50
```

为什么要这样做？

因为真实 AMDAR 不是只有一种情况。单点批次、小批次、大批次、爬升、下降、巡航的时间重建难度都不一样。如果只测一种情况，结果会过于乐观。

本轮实际抽样结果：

```text
Stage3 source legs sampled = 4,923 条
Pseudo cases = 15,000 个
```

### 第二步：从 ADS-B leg 中截取一小段，构造 pseudo batch

对每条 source leg，从连续 ADS-B 点里截取一段。

例如原来 ADS-B 是：

```text
t1 点、t2 点、t3 点、t4 点、t5 点、...
```

我们取其中一段：

```text
t10 到 t18
```

把这一段假装成一个 AMDAR 批次。

这一步非常重要，因为这些点的真实时间来自 ADS-B，是已知的。所以后面可以评价算法误差。

### 第三步：模拟 AMDAR 的“批次下发时间”

真实 AMDAR 不是每个点都有真实时间，而是一个批次下发时间。

所以 pseudo-AMDAR 也要模拟这个特点：

```text
batch_end_time = 这一段最后一个 ADS-B 点的真实时间 + 一个下传延迟
```

本轮模拟中加入了下传延迟，典型是几十秒到几分钟。

这样构造后，算法看到的不是每个点的真实时间，而是更像 AMDAR 的批次结束/下发时间。

### 第四步：给 pseudo 点加小扰动

为了不让任务过于简单，构造 pseudo 点时加入确定性小噪声，例如：

- 位置噪声
- 高度偏差
- 不同批次大小
- 不同飞行阶段
- 候选航段歧义

通俗说：

```text
不能让算法直接拿原始 ADS-B 点原封不动去匹配，否则太容易。
要让它更像真实 AMDAR：位置和高度接近 ADS-B，但不是完全一样。
```

### 第五步：按 tail + date 分组切分数据集

这是阶段3最重要的防泄漏设计。

数据不是随机逐行切分，而是按：

```text
tail_norm + service_date_utc
```

也就是同一架飞机同一天的数据，不能同时出现在 validation 和 locked_test 里。

分成三类：

```text
calibration_set    用于前期观察和开发
validation_set     用于选择阈值
locked_test_set    最终锁定测试，不允许调参
```

为什么不能随机逐行切？

因为如果同一架飞机同一天的一些片段在训练/调参里，另一些片段在测试里，算法可能“见过”很相似的航迹，测试结果会虚高。

本轮检查结果：

```text
no_tail_date_split_leakage = True
```

说明没有同一飞机同一天跨集合泄漏。

### 第六步：给每个 pseudo batch 生成候选 ADS-B leg

对每个 pseudo case，算法根据这些信息找候选：

- 机尾号 tail
- 航班号 flight
- 日期 date
- 批次结束时间附近的时间窗
- 空间包络范围
- 高度范围
- 飞行阶段

候选不是直接接受，只是说：

```text
这些 ADS-B leg 有可能是这个 pseudo batch 的来源。
```

### 第七步：把 pseudo 点投影到候选 ADS-B leg 上

对每个候选 leg，算法把 pseudo batch 里的每个点投影到 ADS-B 轨迹上，估计它最可能对应轨迹上的哪个时间点。

然后计算几个代价：

- `best_cost`：最佳候选的综合代价。
- `second_best_cost`：第二候选代价。
- `ambiguity_margin`：第一名和第二名的差距。
- `cross_track_q90`：横向偏离 90 分位。
- `vertical_q90`：垂直偏差 90 分位。
- `sampling_gap`：候选 ADS-B 轨迹采样缺口。
- `monotonic_violation_count`：批次内点沿轨时间/位置是否违反单调顺序。

这些指标的意义是：

```text
不仅要看能不能找到一条 leg，
还要看这条 leg 是否几何上合理、时间顺序合理、是否有歧义。
```

### 第八步：用 validation 选择接受门槛，再只在 locked_test 报告

阶段3不能用 locked_test 调阈值。

正确流程是：

```text
只在 validation set 上选择门槛；
门槛确定后，原封不动应用到 locked_test；
locked_test 只报告结果，不再修改阈值。
```

本轮先做了 v6，再做了 v7 优化。

---

## 5. v6 做了什么，结果说明什么

### 5.1 v6 的做法

v6 先解决了阶段3 source pool 过窄的问题。

之前 v5 只有：

```text
S_stage3_clean_source = 13,432 条
```

这对平衡不同飞行阶段和批次大小来说太少。

v6 将 source pool 扩展成：

```text
S0 + S1 + S2 = 370,786 条
```

然后从中抽样：

```text
source legs sampled = 4,923
pseudo cases = 15,000
```

### 5.2 v6 的完整覆盖结果不好

如果不加接受阈值，所有 case 都强行接受，locked_test 结果是：

```text
case_count = 4,761
matched_case_count = 4,508
wrong_leg_count = 253
wrong_leg_rate = 5.31%
time_error_q90 = 1,928 s
catastrophic_error_rate = 10.58%
```

这个结果说明：

```text
不能把所有候选都接受。
```

也就是说，算法确实能找到很多正确 leg，但如果不做拒绝/门控，会把一部分歧义大、时间误差大的 case 也接受进来。

### 5.3 v6 用 validation 选择单一 best_cost 阈值后通过

v6 接着在 validation set 上选择 `best_cost` 阈值，然后应用到 locked_test。

locked_test selected 结果：

```text
case_count = 4,761
selected_case_count = 3,325
selected_case_fraction = 69.84%
matched_case_count = 3,302
wrong_leg_count = 23
wrong_leg_rate_selected = 0.69%
time_error_q50 = 2.35 s
time_error_q90 = 7.06 s
time_error_q99 = 379.82 s
catastrophic_error_rate = 0.37%
```

这个结果达到计划要求：

```text
selected coverage > 30%
time_error_q90 < 5 min
catastrophic_error_rate < 5%
wrong_leg_rate <= 1%
```

所以 v6 证明：

```text
只要有合适的拒绝门槛，pseudo-AMDAR 时间重建是可行的。
```

但 v6 还有一个不足：

```text
它主要依赖单一 best_cost 阈值，可解释性还不够强。
```

老师问“为什么接受这些、拒绝那些”时，只说 best_cost 小于某个值还不够直观。

---

## 6. v7 又优化了什么

### 6.1 为什么要做 v7

v6 已经达标，但它的接受规则主要是：

```text
best_cost <= threshold
```

这在工程上能用，但解释性不够好。

因为真实 AMDAR-ADS-B matching 以后不能只靠一个黑盒代价。我们希望接受条件更像人工质检逻辑：

- 横向偏差要小。
- 垂直偏差要小。
- ADS-B 轨迹采样缺口不能太大。
- 批次内点沿轨顺序不能乱。
- 多个候选接近时要有足够歧义间隔。

所以 v7 把单一阈值升级成复合门控。

### 6.2 v7 的复合接受门槛

v7 使用 validation-only 复合 gate：

```text
best_cost <= 1.0
cross_track_q90 <= 0.5 km
vertical_q90 <= 200 m
sampling_gap <= 300 s
monotonic_violation_count = 0
如果有多个候选，ambiguity_margin >= 2.0
```

通俗解释：

一个 pseudo case 要被接受，需要同时满足：

1. 综合代价低。
2. 点投影到航迹上不能横向偏太远。
3. 高度不能差太多。
4. ADS-B 轨迹中间不能有太长缺测。
5. 批次内点的顺序必须沿飞行轨迹单调前进。
6. 如果有多个候选航段，第一名必须明显优于第二名。

这比 v6 的单一 best_cost 更容易向老师解释，也更接近未来真实匹配需要的 reject/ambiguity diagnostics。

### 6.3 v7 locked_test 结果

v7 使用 validation set 确定复合规则，然后 locked_test 只报告结果。

locked_test selected 结果：

```text
case_count = 4,761
selected_case_count = 3,906
selected_case_fraction = 82.04%
matched_case_count = 3,894
wrong_leg_count = 12
wrong_leg_rate_selected = 0.31%
time_error_q50 = 2.28 s
time_error_q90 = 6.85 s
time_error_q99 = 326.05 s
catastrophic_error_rate = 0.25%
```

和 v6 对比：

```text
v6 selected coverage = 69.84%
v7 selected coverage = 82.04%

v6 wrong_leg_rate = 0.69%
v7 wrong_leg_rate = 0.31%

v6 q90 time error = 7.06 s
v7 q90 time error = 6.85 s

v6 catastrophic error rate = 0.37%
v7 catastrophic error rate = 0.25%
```

也就是说，v7 不只是更好解释，指标也更好：

- 接受覆盖率更高。
- 错航段率更低。
- 时间误差更小。
- 灾难性错误更少。

---

## 7. 这些结果怎么解读

### 7.1 阶段3说明算法在 pseudo 场景下是可靠的

v7 locked_test 已经满足 Unified Plan 的阶段3完成标准：

```text
时间误差 q90 < 5 分钟
selected coverage > 30%
灾难性错误率 < 5%
wrong-leg rate <= 1%
```

实际结果远好于最低要求：

```text
selected coverage = 82.04%
q90 time error = 6.85 秒
catastrophic error rate = 0.25%
wrong-leg rate = 0.31%
```

这说明：

```text
在 ADS-B source leg 质量足够、候选生成合理、复合门控生效的条件下，
我们可以比较可靠地找回 pseudo-AMDAR 的来源航段，并重建批次内点时间。
```

### 7.2 但阶段3不等于真实 AMDAR 匹配已经完成

这一点必须向老师讲清楚。

阶段3用的是 pseudo-AMDAR，来源本来就是 ADS-B。它验证的是：

```text
算法在可控闭环里的能力。
```

它不能直接推出：

```text
真实 AMDAR 已经和 ADS-B 成功匹配。
```

因为真实 AMDAR 还有额外困难：

- AMDAR 身份字段可能不完整。
- AMDAR 批次点和 ADS-B 轨迹不一定完美对应。
- AMDAR 位置/高度可能有误差。
- 真实数据可能存在更复杂的批次下发逻辑。
- 候选航迹可能更多、更歧义。

所以阶段3的正确结论是：

```text
可以进入下一步 Stage5-V3 prep / real matching 设计，
但不能直接把 broad real AMDAR-ADS-B matching 放开。
```

### 7.3 阶段3也不改变 truth 边界

无论 v6/v7 结果多好，都不改变：

```text
AMDAR effective_strict_truth = false
AMDAR 不进入 strict holdout
TURB 才是 conservative strict truth 来源
```

阶段3只是给 AMDAR 未来作为 support data 的时间重建提供依据。

---

## 8. 阶段3的产物

主要脚本：

```text
/data/LFT-W02_data/pengxu/优化/数据处理/amdar_unified_stage2_v6_stage3_pseudo_20260701.py
/data/LFT-W02_data/pengxu/优化/数据处理/amdar_unified_stage3_v7_stage4_confidence_v2_20260701.py
```

v6 输出目录：

```text
/data/LFT-W02_data/pengxu/优化/数据处理/amdar_unified_stage2_v6_stage3_pseudo_optimized_20260701/stage3_pseudo_amdar_v6
```

关键文件：

```text
pseudo_amdar_v6_cases_all.parquet
pseudo_amdar_v6_points_all.parquet
pseudo_amdar_v6_case_evaluation.parquet
pseudo_amdar_v6_row_reconstruction.parquet
pseudo_amdar_v6_calibration_report.json
stage3_pseudo_amdar_v6_report.md
```

v7 输出目录：

```text
/data/LFT-W02_data/pengxu/优化/数据处理/amdar_unified_stage3_v7_stage4_confidence_v2_optimized_20260701/stage3_pseudo_amdar_v7_compound_gate
```

关键文件：

```text
pseudo_amdar_v7_case_evaluation.parquet
pseudo_amdar_v7_acceptance_curve.parquet
pseudo_amdar_v7_accepted_profile.parquet
pseudo_amdar_v7_calibration_report.json
stage3_pseudo_amdar_v7_report.md
```

---

## 9. 向老师汇报时可以这样总结

可以用下面这段话作为口头汇报：

```text
Unified Plan 里的阶段3不是主框架 Stage3，而是 pseudo-AMDAR 闭环验证。
因为真实 AMDAR 的时间是批次下发/接收时间，不是逐点观测时间，所以我们不能直接用真实 AMDAR 判断时间重建算法准不准。
我的做法是从高质量 ADS-B 航段里抽取连续片段，模拟成 AMDAR 批次。这样每个伪 AMDAR 点的真实时间是已知的，但算法只能看到类似 AMDAR 的批次时间和带噪声的位置。
然后算法根据身份、日期、时间窗、空间包络和高度包络找候选 ADS-B 航段，再把伪 AMDAR 点投影到候选航迹上，估计逐点时间。
数据按 tail+date 分成 calibration、validation、locked_test，保证同一飞机同一天不跨集合，避免泄漏。阈值只在 validation 上确定，locked_test 只做最终报告。

v6 已经证明单一 best_cost 阈值可以通过 locked_test：选中覆盖率约 69.8%，q90 时间误差 7.06 秒，错航段率 0.69%，灾难性错误率 0.37%。
但为了更可解释，我又做了 v7 复合门控，同时要求 best_cost、横向偏差、垂直偏差、采样缺口、单调性和候选歧义都达标。
v7 locked_test 结果更好：选中覆盖率 82.04%，q90 时间误差 6.85 秒，错航段率 0.31%，灾难性错误率 0.25%。

因此阶段3已经达标，说明在 pseudo 场景下，时间重建和航段匹配方法是可靠的。
但这个结论不等于真实 AMDAR-ADS-B matching 已完成，也不改变 AMDAR support-only 的角色。
后续真实匹配仍然必须做 Stage5-V3 的候选、拒绝和歧义诊断。
```

---

## 10. 最终判断

阶段3已经达到 Unified Plan 的完成标准。

我对阶段3结果的判断是：

```text
满意，可以进入下一步。
```

原因：

1. 数据构造是闭环的，pseudo 点的真实时间已知。
2. 数据切分按 tail+date，无泄漏。
3. 阈值选择只用 validation，locked_test 没有参与调参。
4. v7 复合门控比 v6 单一阈值更可解释。
5. locked_test 的 coverage、q90 时间误差、wrong-leg rate、catastrophic rate 全部达标。
6. 结果没有破坏 strict truth 边界，AMDAR 仍然不是 strict truth。

剩余工作不是继续放宽阶段3，而是进入后续 Stage5-V3 prep：

```text
真实 AMDAR-ADS-B candidate generation
reject diagnostics
ambiguity diagnostics
sequence-level matching
time uncertainty distribution
```

只有这些完成后，真实 AMDAR 才能从 support-only 的粗时间批次数据，升级为更高置信度的 support data；但即便如此，也不能自动成为 strict truth。
