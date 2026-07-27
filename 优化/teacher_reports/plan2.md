# AMDAR Stage1 数据处理与时间重建实施计划
注意：运行的时候直接25路并行来跑。会快一点。
## 1. 项目目标

本阶段目标不是强行恢复所有 AMDAR 记录的“真实观测时间”，而是：

1. 阻止批次时间被误当作逐点观测时间进入 Stage2、Stage4；
2. 保留 AMDAR 中有价值的空间位置、温度、风向和风速观测；
3. 建立基于 ADS-B 航迹的观测时间估计研究分支；
4. 通过闭环实验量化时间重建误差；
5. 仅将通过验证的高质量重建结果用于风场重构；
6. 对无法精确恢复时间的数据，采用粗时间窗、降权或 super-observation，而不是直接丢弃或冒充严格真值。

---

## 2. 已确认事实

原始 AMDAR 数据来自：

`/data/LFT-W02_data/pengxu/20260224/amdar.xlsx`

数据统计结果如下：

* 总记录数：431,008；
* 同航班、同时间的多点组：49,750；
* 多点组内记录数：424,393；
* 多点记录占比：98.47%；
* 重复组占全部时间组比例：88.26%；
* 单组最大记录数：50；
* 重复组原始行连续率：99.69%。

重复组空间跨度：

* 水平跨度中位数：137.10 km；
* 水平跨度 P90：355.40 km；
* 水平跨度 P99：666.95 km；
* 垂直跨度中位数：530.35 m；
* 垂直跨度 P90：2,980.94 m；
* 垂直跨度 P99：5,227.32 m。

结合老师确认的信息：

> 飞机在爬升、巡航和下降等不同阶段累计一批观测后统一下发，原始数据中没有每个点独立的真实观测时间。

因此，原表中的 `时间（北京时）` 应解释为某种批次级时间，不能解释为每个空间点的瞬时观测时间。

目前尚未确认：

* 是机载下发时间、报文生成时间还是地面接收时间；
* 是否对应批次末端；
* 原始行顺序是否严格等于观测先后顺序；
* 巡航和下降阶段的累计周期；
* 是否存在延迟传输或补传。

在这些信息缺失的情况下，主链必须采用保守策略。

---

## 3. 核心工程原则

### 3.1 不伪造时间精度

不得将批次时间直接解释为逐点时间。

不得把重建结果命名为：

* `true_time`
* `real_time`
* `real_observation_time`

统一使用：

* `estimated_observation_time_utc`
* `reconstructed_time_utc`

### 3.2 原始时间永不覆盖

必须同时保存：

```text
amdar_batch_time_raw
amdar_batch_time_utc
estimated_observation_time_utc
time_uncertainty_s
time_reconstruction_method
```

ADS-B 重建时间只能作为新增字段，不能覆盖原始 AMDAR 时间。

### 3.3 时间质量与气象质量分开

批次时间不可信，不代表风温观测本身无效。

建议拆分为：

```text
met_value_quality
time_quality
usage_role
strict_time_truth
```

例如：

```text
met_value_quality = passed
time_quality = batch_time_unknown_semantics
usage_role = coarse_window_support
strict_time_truth = false
```

### 3.4 宁可拒绝，不强制匹配

ADS-B 匹配质量评价的目标不是覆盖率最大化。

对于风场重构：

> 低覆盖率的高质量匹配优于高覆盖率的错误匹配。

### 3.5 不比较 AMDAR 风向与 ADS-B 航向

AMDAR `风向` 是气象学风向，表示风从哪里吹来。

ADS-B `heading` 或 `track` 是飞机运动方向。

两者物理意义不同，不能用于匹配代价或质量评价。

飞机运动方向只能由：

* ADS-B 航迹；
* AMDAR 相邻经纬度；
* 原始点序或沿轨距离；

进行计算。

---

# 4. 双轨处理架构

## 4.1 默认生产链路

生产链目标是确保严格真值集合不再受到批次时间污染。

### AMDAR 数据处理规则

所有 AMDAR 记录统一设置：

```text
strict_time_truth = false
```

包括：

* 同航班同时间多点组；
* 同航班同时间单点组。

单点组不能因为只有一条记录就自动升级为严格时间真值，因为其时间仍可能是批次下发或接收时间。

建议状态：

### 多点批次组

```text
time_quality = batch_time_confirmed
usage_role = support_only_not_strict_truth
```

### 单点组

```text
time_quality = unverified_singleton_batch_time
usage_role = support_only_not_strict_truth
```

### 其他数据源

* `location`：保留为轨迹或运动约束来源；
* `location.u_motion/v_motion`：不得作为气象风真值；
* `turb`：继续沿用现有清洗链；
* 具有明确逐点时间语义的数据源：可继续作为 strict truth candidate。

---

## 4.2 ADS-B 时间重建研究分支

研究分支独立生成：

```text
amdar_reconstructed_v1.parquet
```

在闭环验证完成前：

* 不覆盖 Stage1 默认输出；
* 不修改默认 `time_utc`；
* 不自动升格为 strict truth；
* 不直接作为 Stage2/Stage4 的严格验证数据。

---

# 5. Stage1 立即修改项

## P0.1 明确时间字段语义

原 AMDAR 时间建议改名或增加别名：

```text
amdar_batch_time_raw
amdar_batch_time_beijing
amdar_batch_time_utc
amdar_time_semantics = batch_time_unknown_exact_type
```

逐点观测时间字段：

```text
observation_time_utc
observation_time_source
observation_time_uncertainty_s
```

未重建时：

```text
observation_time_utc = null
observation_time_source = unavailable
observation_time_uncertainty_s = null
```

如果下游系统暂时要求 `time_utc` 非空，可以保留批次时间，但必须增加：

```text
time_is_point_observation = false
```

并在 Stage2、Stage4 中加入硬过滤，禁止将该字段作为严格逐点时间使用。

---

## P0.2 建立批次 ID

建议按以下字段建立批次键：

```text
tail_number
flight_number
batch_time
flight_phase
contiguous_block_index
```

生成：

```text
amdar_batch_id
```

批次级统计字段：

```text
batch_row_count
batch_raw_row_start
batch_raw_row_end
batch_is_contiguous
batch_horizontal_span_km
batch_vertical_span_m
batch_phase
```

不能只使用 `flight_number + time`，因为同一航班号可能跨日期重复运行，也可能发生机尾更换。

---

## P0.3 修正 strict truth 规则

`stage1_prepare.py` 中建议采用：

```text
source == amdar
    => strict_time_truth = false
```

不要只对重复组降级。

保留以下诊断标志：

```text
amdar_batched_same_timestamp
amdar_singleton_unverified_time
```

---

# 6. 原始 AMDAR 序列诊断

原始重复组连续率达到 99.69%，说明表格行序可能保存了报文内部顺序，但仍需验证。

## P1.1 高度单调性检查

按飞行阶段统计：

### ASC

计算：

```text
altitude_increase_ratio
altitude_large_reverse_count
```

### DES

计算：

```text
altitude_decrease_ratio
altitude_large_reverse_count
```

### CRZ

计算：

```text
altitude_stability_ratio
altitude_std_m
```

---

## P1.2 空间连续性检查

每个批次计算：

```text
median_adjacent_distance_km
p90_adjacent_distance_km
max_adjacent_distance_km
path_length_km
endpoint_distance_km
path_efficiency
```

其中：

```text
path_efficiency = endpoint_distance / path_length
```

若原始顺序合理，通常应表现为：

* 相邻点距离连续；
* 少量或没有空间回跳；
* ASC/DES 高度趋势与行序一致；
* 点序构成一条连续航迹，而不是随机排列。

---

## P1.3 正序与倒序比较

分别计算：

* 原始顺序与候选 ADS-B 沿轨距离的相关性；
* 倒序后与候选 ADS-B 沿轨距离的相关性。

输出：

```text
sequence_direction = forward / reverse / unresolved
sequence_monotonic_score
```

在没有证明前，不能默认所有批次都是从上到下的时间顺序。

---

## P1.4 组大小 50 的专项统计

由于最大组大小为 50，且大量案例正好达到 50，需要统计：

```text
count_group_size_50
ratio_group_size_50
group_size_50_by_phase
group_size_50_by_tail_number
group_size_50_by_airline
```

目的：

* 判断是否存在机载缓冲区 50 条上限；
* 判断是否存在数据库或解析程序截断；
* 检查一段较长轨迹是否被拆成多个连续的 50 条批次。

若发现同航班相邻批次频繁出现 `50 + 50 + ...`，应检查是否是同一飞行阶段被分包下发。

---

# 7. ADS-B 候选航段构建

ADS-B 数据来源：

```text
clean_loc.parquet
```

## P2.1 航段拆分

优先按：

```text
tail_number
flight_id
date
```

聚类。

再按以下条件拆分连续航段：

* 时间间隔超过阈值；
* 地理位置发生不合理跳跃；
* 起降阶段发生明显重置；
* 航班号或机尾号变化。

生成：

```text
adsb_leg_id
```

每个航段保存：

```text
leg_start_time
leg_end_time
leg_start_location
leg_end_location
altitude_min
altitude_max
phase_sequence
sampling_gap_statistics
```

---

## P2.2 候选航段筛选优先级

优先顺序：

```text
tail_number
→ flight_number
→ 日期范围
→ 批次空间包络
→ 高度范围
→ 飞行阶段
```

AMDAR 中已有机尾号时，机尾号应作为主要条件。

AMDAR 批次时间目前只能作为宽松条件，不能作为硬约束。

在老师没有进一步说明前，候选时间窗口采用保守策略：

```text
batch_time 前后若干小时
```

但最终候选必须由空间、高度、阶段和整段几何一致性决定。

---

# 8. ADS-B 匹配算法修订

## P3.1 匹配单位

匹配单位必须是：

```text
一个 AMDAR 批次
对
一个完整 ADS-B 候选航段
```

不能让每个 AMDAR 点独立贪心匹配最近 ADS-B 点。

---

## P3.2 匹配方式

采用动态规划、单调序列匹配或约束 DTW。

必须满足：

```text
matched_time[i+1] >= matched_time[i]
```

并尽量满足：

```text
along_track_position[i+1] >= along_track_position[i]
```

允许：

* 跳过少量异常 AMDAR 点；
* 跳过少量 ADS-B 点；
* 拒绝整个批次；
* 标记候选航段歧义。

不允许：

* 为追求覆盖率强制匹配；
* 在时间轴上反复前进后退；
* 将空间距离很远的点仍判为成功。

---

## P3.3 匹配代价

建议包括：

```text
cross_track_distance
vertical_difference
sequence_consistency
phase_consistency
altitude_trend_consistency
jump_penalty
candidate_leg_ambiguity
```

不得包括：

```text
AMDAR wind_direction - ADSB heading
```

若需比较运动方向，只能使用：

```text
AMDAR 相邻经纬度计算出的 track bearing
ADS-B track bearing
```

---

## P3.4 轨迹投影与时间插值

AMDAR 点应投影到相邻 ADS-B 轨迹线段，而不是简单赋予最近离散 ADS-B 点的时间。

假设投影在线段：

```text
A(t0) → B(t1)
```

投影比例为 `lambda`，则：

```text
estimated_time = t0 + lambda * (t1 - t0)
```

保存：

```text
adsb_time_before
adsb_time_after
adsb_interpolation_fraction
adsb_sampling_gap_s
cross_track_distance_km
vertical_difference_m
```

禁止长距离或长时间外推。

---

# 9. 时间语义反推实验

由于老师暂时无法确认批次时间的准确语义，使用高质量 ADS-B 匹配结果反向诊断。

## P4.1 高置信样本筛选

先选一批高置信批次：

* 机尾号一致；
* 航班号一致；
* 候选 ADS-B 航段唯一；
* 整体轨迹高度重合；
* 飞行阶段一致；
* 原始点序高度和空间趋势合理；
* 匹配横向残差较小。

---

## P4.2 计算时间差

对每个批次计算：

```text
batch_time_minus_first_adsb_time
batch_time_minus_last_adsb_time
matched_segment_duration
```

按以下维度统计：

```text
ASC
CRZ
DES
tail_number
airline
batch_size
```

重点观察：

* 批次时间是否通常晚于最后一个匹配观测点；
* 批次时间与航段末端的差值是否集中；
* 是否存在数小时的延迟补传；
* 是否有批次时间落在轨迹中间或轨迹之前。

---

## P4.3 语义分类

根据统计结果，对批次时间语义标记：

```text
inferred_batch_end_time
inferred_downlink_or_receive_time
possible_delayed_transmission
unstable_time_semantics
unresolved
```

除非证据非常稳定，否则不能将其升级为硬时间约束。

---

# 10. pseudo-AMDAR 闭环实验

这是决定 ADS-B 重建能否进入风场重构链的核心实验。

## P5.1 样本构造

从真实 ADS-B 航段中分别抽取：

* ASC；
* CRZ；
* DES。

模拟 AMDAR 批次：

1. 抽取一段 ADS-B 点；
2. 保存真实时间作为隐藏真值；
3. 删除逐点时间；
4. 给所有点赋相同批次时间；
5. 仅保留经纬度、高度、阶段、航班号、机尾号和点序；
6. 使用正式重建算法恢复逐点时间；
7. 与隐藏真值比较。

抽样分布应尽量复现真实 AMDAR：

```text
组大小中位数 = 6
组大小 P90 = 17
组大小 P99 = 49
最大组大小 = 50
```

同时复现真实水平跨度、垂直跨度和 ADS-B 采样缺口。

---

## P5.2 必须输出的指标

### 航段识别

```text
correct_leg_rate
wrong_leg_rate
ambiguous_leg_rate
reject_rate
```

### 时间误差

```text
time_absolute_error_median
time_absolute_error_p90
time_absolute_error_p99
catastrophic_time_error_rate
```

### 序列质量

```text
time_order_reversal_rate
along_track_reversal_rate
```

### 几何质量

```text
cross_track_distance_median
cross_track_distance_p90
vertical_difference_median
vertical_difference_p90
```

### 分层结果

分别按以下条件报告：

```text
ASC / CRZ / DES
batch size
horizontal span
vertical span
ADS-B sampling gap
candidate leg count
with / without tail number
raw order / reordered
```

---

# 11. 时间质量等级

最终阈值必须根据 pseudo-AMDAR 闭环结果和目标风场分辨率确定，不应仅凭经验固定。

初期可使用 A/B/C 作为诊断等级。

## A 级

* 候选航段唯一；
* 整段匹配单调；
* 无明显阶段冲突；
* 几何残差满足精细风场要求；
* 闭环验证表明 P90 时间误差满足目标时间分辨率；
* 无明显补传风险。

用途：

```text
可作为重建输入
可进入风场重构
不可作为时间算法的独立验证真值
```

## B 级

* 航段基本可信；
* 存在一定几何或采样误差；
* 时间误差仍可量化；
* 不确定度较大。

用途：

```text
降权进入较粗时间分辨率重构
或生成 super-observation
```

## C 级

* 只能确定大致航段或时间窗；
* 逐点时间误差较大；
* 几何残差较高。

用途：

```text
30分钟或1小时时间窗支持
背景约束
super-observation
```

## Reject

* 候选航段不唯一；
* 匹配时间倒退；
* 阶段明显冲突；
* 需要长时间外推；
* 几何残差过大；
* 可能延迟补传；
* 无法确定可靠时间范围。

用途：

```text
不进入风场重构
保留原始记录和拒绝原因
```

---

# 12. 时间不确定度估计

每条重建结果必须带：

```text
time_uncertainty_s
```

不确定度至少考虑：

```text
ADS-B sampling gap
geometry residual
candidate ambiguity
sequence uncertainty
possible transmission delay
```

概念上可表示为：

```text
sigma_time² =
sigma_sampling²
+ sigma_geometry²
+ sigma_ambiguity²
+ sigma_sequence²
```

若批次时间语义不稳定，不得用批次时间把不确定度强行压小。

---

# 13. 风场重构前的数据处理

## P6.1 风向风速转为 u/v

AMDAR 风向按气象学来向处理：

```text
u = -speed * sin(direction)
v = -speed * cos(direction)
```

不得直接平均风向角。

---

## P6.2 气象值质控

检查：

```text
wind_speed_range
temperature_range
vertical_consistency
spatial_gradient
flight_phase_consistency
duplicate_observation
```

时间错误与气象值异常必须分开标记。

---

## P6.3 去相关与 super-observation

同一架飞机连续观测高度相关，不能把每条记录当作完全独立观测。

根据目标网格选择：

```text
固定时间窗口
固定沿轨距离
固定高度层
```

生成 super-observation。

输出：

```text
mean_u
mean_v
mean_temperature
sample_count
within_group_variance
representative_time
representative_location
```

---

## P6.4 时间误差进入观测权重

风场重构中，观测误差应包含：

```text
instrument_error
representativeness_error
time_reconstruction_error
```

A级正常使用，B级降权，C级只进入粗时间窗，Reject 不使用。

---

# 14. 风场重构消融实验

至少运行四组实验：

## Experiment 0

```text
不使用 AMDAR
```

作为基准。

## Experiment 1

```text
仅使用 A 级重建 AMDAR
```

## Experiment 2

```text
使用 A + B 级 AMDAR
B 级降低权重
```

## Experiment 3

```text
使用 A + B + C
C 级只作为粗时间窗或 super-ob
```

比较：

```text
wind_u_rmse
wind_v_rmse
wind_speed_rmse
wind_direction_error
spatial_smoothness
temporal_consistency
extreme_gradient_artifacts
```

验证数据必须独立于参与重构的 AMDAR，不能用同一批 AMDAR 同时作输入和真值。

---

# 15. 代码与产物安排

## 主链代码

```text
stage/stage1_prepare.py
```

职责：

* 标记 AMDAR 批次时间；
* 禁止 AMDAR 作为 strict time truth；
* 建立批次 ID；
* 输出主链保守版本。

## 研究分支代码

```text
stage/reconstruct_amdar_time_from_adsb.py
```

职责：

* 构建 ADS-B 航段；
* 筛选候选航段；
* 批次级单调匹配；
* 轨迹投影与时间插值；
* 输出质量指标和不确定度；
* 允许拒绝匹配。

## 建议新增脚本

```text
stage/analyze_amdar_batch_sequence.py
stage/infer_amdar_batch_time_semantics.py
stage/run_pseudo_amdar_validation.py
stage/evaluate_amdar_reconstruction.py
stage/build_amdar_superobs.py
```

## 建议输出文件

```text
amdar_stage1_conservative.parquet
amdar_batch_statistics.parquet
amdar_sequence_diagnostics.parquet
amdar_reconstructed_v1.parquet
pseudo_amdar_validation_results.parquet
amdar_reconstruction_summary.json
amdar_superobs_v1.parquet
```

---

# 16. 执行顺序

## 第一阶段：立即完成

1. 所有 AMDAR 取消 strict time truth；
2. 原时间明确标记为批次时间；
3. 建立 `amdar_batch_id`；
4. 保留原始行号和连续块编号；
5. 修正下游对 `time_utc` 的误用；
6. 统计组大小为 50 的分布；
7. 输出 ASC、CRZ、DES 的高度单调性和空间连续性指标。

## 第二阶段：匹配算法修订

1. ADS-B 按机尾号和连续航段拆分；
2. 机尾号优先筛选候选航段；
3. 逐点贪心改为整段单调匹配；
4. 加入拒绝机制；
5. 使用轨迹线段投影插值时间；
6. 输出最佳和第二佳候选代价；
7. 输出航段歧义和拒绝原因。

## 第三阶段：验证

1. 运行时间语义反推实验；
2. 运行 pseudo-AMDAR 闭环实验；
3. 按阶段和批次规模统计时间误差；
4. 根据目标风场分辨率确定 A/B/C 阈值；
5. 确认哪些等级可进入风场重构。

## 第四阶段：风场实验

1. 构建 A/B/C 级数据集；
2. 生成必要的 super-observation；
3. 运行无 AMDAR、A级、A+B、A+B+C 消融实验；
4. 使用独立数据验证；
5. 仅在结果稳定改善时回并生产链。

---

# 17. 进入主链的准入条件

ADS-B 时间重建只有同时满足以下条件，才允许回并主链：

1. pseudo-AMDAR 的正确航段率达到可接受水平；
2. 错误航段率足够低；
3. 时间误差 P90 满足目标风场时间分辨率；
4. 几何残差满足目标空间分辨率；
5. 质量等级与真实误差有稳定关系；
6. A/B/C 分级在不同阶段、机型和航司间不过度失效；
7. 加入重建 AMDAR 后，独立风场验证结果稳定改善；
8. 原始批次时间和重建时间始终分字段保存；
9. 下游能够识别并使用时间不确定度；
10. 不将重建 AMDAR 作为其自身算法的严格验证真值。

---

# 18. 当前最终工程口径

在老师没有进一步确认时间字段含义前，采用以下默认结论：

```text
AMDAR 原始时间：
    未知具体语义的批次级时间

AMDAR 原始逐点时间：
    不存在或未提供

所有 AMDAR：
    strict_time_truth = false

ADS-B 重建时间：
    estimated / reconstructed
    仅研究分支使用

无法可靠重建的数据：
    粗时间窗支持、super-ob 或拒绝

原始时间：
    永久保留，不覆盖
```

一句话概括：

> Stage1 主链负责防止批次时间污染严格真值；ADS-B 分支负责研究逐点时间估计；只有经过 pseudo-AMDAR 闭环验证、质量分级和独立风场消融实验后，高质量重建结果才允许进入风场重构。
