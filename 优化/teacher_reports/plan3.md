下面这版已经把老师最新确认的四点全部纳入，可以直接替换原来的 `plan.md`。

# AMDAR Stage1 数据治理、ADS-B 时间重建与风场应用实施方案

## 1. 项目背景

原始 AMDAR 数据中，大量记录出现：

> 同一航班、同一时间戳，但对应多个空间上明显分散的观测点。

经原始数据统计与数据提供方确认，该现象并非普通重复记录或清洗错误，而是 AMDAR 数据的实际下传机制导致：

* 飞机在爬升、巡航、下降等飞行阶段持续采集观测；
* 多条观测先在机载系统中累计；
* 累计到一定条件后，以一个批次统一下传；
* 表格中的时间是地面系统接收到该批数据的时间；
* 地空链路可近似视为实时，因此该时间也可理解为飞机下发该批数据的时间；
* 该时间可以作为该批观测的结束时间；
* 批次内原始数据表的排列顺序即观测先后顺序；
* 不同飞行阶段的累计和下发周期可以动态调整，不是固定的 30 分钟或其他固定时长。

因此，原始 AMDAR 表中的时间不能作为每个空间点的真实逐点观测时间，但可以作为：

1. 批次结束时间；
2. 批次内所有观测时间的上界；
3. ADS-B 时间重建的重要约束。

---
注意：运行的时候直接25路并行来跑。会快一点。
# 2. 项目目标

本方案的目标包括：

1. 防止 AMDAR 批次结束时间被错误解释为逐点真实观测时间；
2. 保留 AMDAR 中有效的风、温度、位置和高度观测；
3. 建立基于 ADS-B 航迹的 AMDAR 逐点观测时间估计方法；
4. 为每条重建结果提供质量等级和时间不确定度；
5. 通过 pseudo-AMDAR 闭环实验验证时间重建能力；
6. 将验证合格的 AMDAR 数据用于风场重构；
7. 对无法精确重建时间的数据采用粗时间窗、降权或超级观测处理；
8. 始终保留原始时间，不用重建时间覆盖原始字段。

---

# 3. 已确认的数据事实

## 3.1 原始 AMDAR 统计

原始文件：

```text
/data/LFT-W02_data/pengxu/20260224/amdar.xlsx
```

数据规模：

* 总记录数：431,008；
* 同航班、同时间的多点组：49,750；
* 多点组内记录数：424,393；
* 多点记录占比：98.47%；
* 重复组占全部时间组比例：88.26%；
* 单组最大记录数：50；
* 重复组原始行连续率：99.69%。

重复组水平跨度：

* 中位数：137.10 km；
* P90：355.40 km；
* P99：666.95 km。

重复组垂直跨度：

* 中位数：530.35 m；
* P90：2,980.94 m；
* P99：5,227.32 m。

这些统计表明，同时间多点结构代表的是一段累计下传的飞行轨迹，而不是同一瞬间发生在多个地点的观测。

---

## 3.2 数据提供方确认的信息

已确认：

1. 表格中的时间是地面系统接收该批数据的时间；
2. 地空链路基本实时，可近似理解为飞机下发该批数据的时间；
3. 该时间可理解为该批观测的结束时间；
4. 同一批次内，表格中的记录顺序就是实际观测先后顺序；
5. 爬升、巡航、下降阶段的累计周期可动态调整；
6. 原始数据没有提供每个观测点独立的真实观测时间。

因此，对批次内第 (i) 个点，有：

[
t_1 < t_2 < \cdots < t_n \leq T_b
]

其中：

* (t_i)：待估计的逐点观测时间；
* (T_b)：该批次地面接收时间或批次结束时间；
* 原始表中的行顺序决定 (t_i) 的先后关系。

---

# 4. 核心术语和字段语义

## 4.1 原始时间

原始 AMDAR 时间统一定义为：

```text
amdar_batch_end_time
```

其语义为：

```text
地面系统接收该批数据的时间
≈ 飞机下发该批数据的时间
≈ 该批观测的结束时间
```

建议保存：

```text
amdar_batch_end_time_raw
amdar_batch_end_time_beijing
amdar_batch_end_time_utc
```

不得继续把该字段直接称为逐点：

```text
observation_time
```

---

## 4.2 重建时间

ADS-B 重建结果统一使用：

```text
estimated_observation_time_utc
```

或：

```text
reconstructed_observation_time_utc
```

不得使用：

```text
true_time
real_time
real_observation_time
```

因为原始真实逐点时间不存在，重建结果仍然是估计值。

---

## 4.3 时间约束

对每个批次：

```text
estimated_observation_time[i] <= amdar_batch_end_time
```

同时：

```text
estimated_observation_time[i + 1]
>
estimated_observation_time[i]
```

如果同一连续航段存在前一个批次，可暂时使用：

```text
previous_batch_end_time
<
estimated_observation_time[i]
<=
current_batch_end_time
```

但前一批结束时间初期只作为软下界，待确认不存在补传、重复下传或跨阶段混合后，再决定是否升级为硬约束。

---

# 5. 总体架构：生产主链与研究分支双轨运行

## 5.1 默认生产链路

生产链路的目标是保护 Stage2、Stage4 以及其他下游模块，不让批次结束时间污染严格时空真值。

所有 AMDAR 数据统一设置：

```text
strict_time_truth = false
```

包括：

* 同航班、同时间多点组；
* 同航班、同时间单点组。

单点组也不能自动视为严格时间真值，因为它仍可能是某个批次下发的唯一一条记录。

推荐字段：

```text
time_quality
usage_role
strict_time_truth
time_is_point_observation
```

多点批次组：

```text
time_quality = batch_end_time
usage_role = support_only_not_strict_truth
strict_time_truth = false
time_is_point_observation = false
```

单点批次组：

```text
time_quality = singleton_batch_end_time
usage_role = support_only_not_strict_truth
strict_time_truth = false
time_is_point_observation = false
```

---

## 5.2 ADS-B 时间重建研究分支

时间重建作为独立研究分支运行，建议输出：

```text
amdar_reconstructed_v1.parquet
```

在完成闭环验证前：

* 不覆盖 Stage1 默认时间字段；
* 不替换原始 AMDAR 批次时间；
* 不自动升级为 strict truth；
* 不作为时间重建算法自身的验证真值；
* 不直接全部送入高分辨率风场重构。

---

# 6. Stage1 数据治理方案

## 6.1 建立 AMDAR 批次标识

建议批次键为：

```text
tail_number
+ flight_number
+ amdar_batch_end_time
+ flight_phase
+ contiguous_block_index
```

生成：

```text
amdar_batch_id
```

批次级字段：

```text
amdar_batch_id
flight_number
tail_number
flight_phase
amdar_batch_end_time_utc

batch_raw_row_start
batch_raw_row_end
batch_row_count
batch_is_contiguous

batch_horizontal_span_km
batch_vertical_span_m
```

不能只使用：

```text
flight_number + time
```

因为同一航班号可能跨日期重复运行，也可能更换飞机。

---

## 6.2 建立批次内部观测顺序

根据老师确认的信息，原始表顺序即观测顺序。

每个批次生成：

```text
amdar_observation_order
```

取值：

```text
1, 2, ..., n
```

并永久保留：

```text
raw_row_number
```

匹配时原始顺序作为硬约束，不再尝试倒序匹配。

---

## 6.3 明确逐点时间字段

建议新增：

```text
estimated_observation_time_utc
observation_time_lower_bound_utc
observation_time_upper_bound_utc
time_reconstruction_method
time_uncertainty_s
```

在未重建前：

```text
estimated_observation_time_utc = null
observation_time_upper_bound_utc = amdar_batch_end_time_utc
observation_time_lower_bound_utc = null
time_reconstruction_method = unavailable
time_uncertainty_s = null
```

---

## 6.4 防止下游误用

如果现有代码必须保留通用字段：

```text
time_utc
```

则 AMDAR 数据必须增加：

```text
time_is_point_observation = false
```

Stage2、Stage4 中需要设置硬过滤：

```text
source == amdar
and time_is_point_observation == false
```

不得进入 strict temporal truth 或 strict holdout truth。

---

# 7. AMDAR 原始序列质量检查

老师确认原始行序是观测顺序，但仍需进行数据级质量诊断，以发现解析异常或局部脏数据。

## 7.1 高度趋势检查

### 爬升阶段 ASC

计算：

```text
altitude_increase_ratio
altitude_reverse_count
maximum_altitude_reverse_m
```

预期高度总体增加。

### 下降阶段 DES

计算：

```text
altitude_decrease_ratio
altitude_reverse_count
maximum_altitude_reverse_m
```

预期高度总体下降。

### 巡航阶段 CRZ

计算：

```text
altitude_std_m
altitude_range_m
altitude_stability_ratio
```

巡航中允许高度层调整，但不应出现无规律的大幅反复跳动。

---

## 7.2 空间连续性检查

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

[
path_efficiency
===============

\frac{endpoint_distance}{path_length}
]

同时标记：

```text
sequence_spatial_jump_count
sequence_monotonic_pass
sequence_geometry_quality
```

---

## 7.3 批次大小 50 的专项分析

由于单组最大记录数为 50，且大量典型批次接近或等于 50，需要分析是否存在报文容量或缓冲区上限。

统计：

```text
count_group_size_50
ratio_group_size_50
group_size_50_by_phase
group_size_50_by_tail_number
group_size_50_by_airline
```

重点检查：

* 同一航班是否连续出现多个 50 条批次；
* 是否存在 50 + 50 + 50 的分包模式；
* 组大小是否与阶段、航司或机型有关。

该统计用于理解批次机制，但不能据此推断固定累计时长。

---

# 8. ADS-B 航迹预处理

ADS-B 数据来源：

```text
clean_loc.parquet
```

## 8.1 统一数据格式

必须统一：

```text
时间：UTC
经纬度：十进制度
高度：统一为米或英尺
速度：统一单位
机尾号：统一大小写和符号格式
航班号：去除空格和前导格式差异
```

需要重点检查：

* 北京时间与 UTC 是否相差 8 小时；
* ADS-B 是否已经是 UTC；
* AMDAR 高度是米、英尺、飞行高度层还是气压高度；
* 经纬度是否正确解析；
* 航班号是否存在前导零、空格、共享航班号或呼号差异。

---

## 8.2 构建连续 ADS-B 航段

优先按：

```text
tail_number
flight_number
date
```

分组。

再根据以下条件切分航段：

* 时间间隔超过阈值；
* 空间位置发生不合理跳跃；
* 高度或飞行阶段明显重置；
* 航班号变化；
* 起降循环重新开始。

生成：

```text
adsb_leg_id
```

航段级字段：

```text
adsb_leg_id
tail_number
flight_number

leg_start_time_utc
leg_end_time_utc
leg_duration_s

leg_start_lat
leg_start_lon
leg_end_lat
leg_end_lon

leg_min_altitude
leg_max_altitude
leg_phase_sequence

median_sampling_gap_s
p90_sampling_gap_s
max_sampling_gap_s
```

---

# 9. ADS-B 候选航段筛选

## 9.1 身份筛选优先级

候选筛选顺序：

```text
机尾号完全一致
→ 航班号一致
→ 日期和批次结束时间合理
→ ADS-B 时间不晚于批次结束时间
→ 空间包络重合
→ 高度范围一致
→ 飞行阶段一致
```

机尾号优先级高于航班号。

若机尾号缺失，再使用：

```text
flight_number + date + route geometry
```

进行候选筛选，但必须增加歧义惩罚。

---

## 9.2 单侧时间窗口

由于批次时间已确认是结束时间，候选 ADS-B 观测原则上必须满足：

```text
adsb_time <= amdar_batch_end_time
```

考虑系统时钟偏差和秒级舍入，可暂时设置小容差：

```text
adsb_time <= amdar_batch_end_time + tolerance
```

初始可测试：

```text
tolerance = 30–60 s
```

最终容差由真实匹配分布确定。

不再使用以批次时间为中心的前后对称宽窗口。

---

## 9.3 动态回溯窗口

由于飞行阶段累计周期动态调整，不能固定使用：

```text
batch_end_time - 30 min
```

作为通用下界。

优先使用：

### 同一航段存在前一批时

```text
previous_batch_end_time
```

作为软下界。

### 航段第一批时

使用：

* ADS-B 航段开始时间；
* 当前飞行阶段开始时间；
* 起飞时间；
* 较宽但有上限的回溯窗口。

回溯窗口只用于减少候选，不代表真实累计周期。

---

# 10. 批次级单调匹配算法

## 10.1 匹配单位

匹配单位必须是：

```text
一个完整 AMDAR 批次
对
一个完整 ADS-B 候选航段
```

不得继续采用每个 AMDAR 点独立寻找最近 ADS-B 点的贪心方式。

---

## 10.2 顺序约束

对于 AMDAR 原始顺序：

```text
i = 1, 2, ..., n
```

要求：

[
t_{i+1} > t_i
]

同时：

[
s_{i+1} \geq s_i
]

其中 (s_i) 是匹配到 ADS-B 航迹上的沿轨距离。

算法只允许沿 ADS-B 时间轴和航迹方向向前移动。

---

## 10.3 可选算法

可以采用：

* 动态规划；
* Viterbi 路径匹配；
* 单调 DTW；
* 带跳点和拒绝状态的序列对齐。

需要支持：

* 跳过少量异常 AMDAR 点；
* 跳过部分 ADS-B 点；
* 一个 ADS-B 线段对应多个临近 AMDAR 点；
* 拒绝整个批次；
* 标记局部失败点；
* 输出最佳和第二佳候选航段。

---

## 10.4 匹配代价

推荐代价函数包括：

[
C =
w_h C_h
+
w_z C_z
+
w_s C_s
+
w_p C_p
+
w_e C_e
+
w_j C_j
+
w_a C_a
]

其中：

* (C_h)：轨迹横向距离；
* (C_z)：高度差；
* (C_s)：原始序列和沿轨顺序一致性；
* (C_p)：飞行阶段一致性；
* (C_e)：批次结束时间约束；
* (C_j)：不合理跳跃惩罚；
* (C_a)：候选航段歧义惩罚。

禁止使用：

```text
AMDAR 风向 - ADS-B 航向
```

因为 AMDAR 风向是气象风向，ADS-B 航向是飞机运动方向，两者物理意义不同。

若需要比较运动方向，应使用：

```text
由相邻 AMDAR 经纬度计算的轨迹方位角
与
ADS-B 轨迹方向
```

---

# 11. 轨迹投影和时间插值

## 11.1 线段投影

对每个 AMDAR 点，不直接赋予最近 ADS-B 离散点的时间，而是投影到相邻 ADS-B 轨迹线段：

```text
A(t0) → B(t1)
```

若投影比例为 (\lambda)，其中：

[
0 \leq \lambda \leq 1
]

则：

[
t_i = t_0 + \lambda (t_1 - t_0)
]

保存：

```text
adsb_time_before
adsb_time_after
adsb_interpolation_fraction
adsb_sampling_gap_s

matched_adsb_lat
matched_adsb_lon
matched_adsb_altitude

cross_track_distance_km
vertical_difference_m
```

---

## 11.2 外推规则

原则上只允许线段内部插值。

需要外推时必须严格限制：

```text
extrapolation_seconds
extrapolation_distance_km
```

超过阈值直接拒绝，不得用长距离外推提高覆盖率。

---

# 12. 飞行阶段约束

## 12.1 爬升 ASC

要求：

* 原始顺序时间递增；
* 高度总体增加；
* 匹配时间不晚于批次结束时间；
* 不应匹配到巡航后段或下降阶段；
* 允许小幅高度波动，但不允许持续反向。

---

## 12.2 巡航 CRZ

巡航阶段高度约束相对较弱，主要依赖：

* 轨迹几何形状；
* 沿轨顺序；
* 机尾号和航班号；
* 水平空间重合；
* 航段时间范围；
* 高度层大致一致。

需要允许正常的高度层调整。

---

## 12.3 下降 DES

要求：

* 原始顺序时间递增；
* 高度总体下降；
* 航迹逐渐接近目的地区域；
* 不匹配到同一航班前部的爬升或巡航段；
* 防止将返航、盘旋等特殊轨迹误判为普通下降。

---

# 13. 重建结果输出字段

最终研究分支至少输出：

```text
amdar_batch_id
amdar_observation_order
raw_row_number

flight_number
tail_number
flight_phase

amdar_batch_end_time_utc
previous_batch_end_time_utc

estimated_observation_time_utc
observation_time_lower_bound_utc
observation_time_upper_bound_utc
time_uncertainty_s
time_reconstruction_method

matched_adsb_leg_id
matched_adsb_time_before
matched_adsb_time_after
adsb_interpolation_fraction
adsb_sampling_gap_s

matched_adsb_lat
matched_adsb_lon
matched_adsb_altitude

cross_track_distance_km
vertical_difference_m
track_direction_difference_deg

candidate_leg_count
best_match_cost
second_best_match_cost
match_ambiguity_ratio

sequence_monotonic_pass
phase_consistency_pass
batch_end_constraint_pass

time_quality_level
usage_role
strict_time_truth
reject_reason
```

---

# 14. 时间不确定度设计

每条记录必须输出：

```text
time_uncertainty_s
```

时间不确定度至少包含：

[
\sigma_t^2 =
\sigma_{\text{sampling}}^2
+
\sigma_{\text{geometry}}^2
+
\sigma_{\text{ambiguity}}^2
+
\sigma_{\text{sequence}}^2
+
\sigma_{\text{downlink}}^2
]

## 14.1 ADS-B 采样误差

若相邻 ADS-B 点间隔为 (\Delta t)，可初步使用：

[
\sigma_{\text{sampling}}
\approx
\frac{\Delta t}{2}
]

---

## 14.2 几何匹配误差

利用：

* 横向轨迹残差；
* 高度差；
* 沿轨位置不确定性；
* 飞机地速；

估算几何对应的时间误差。

横向偏离过大时不能简单换算为时间误差，应判为候选航段或轨迹匹配错误。

---

## 14.3 候选航段歧义

若最佳候选与第二佳候选代价接近：

```text
match_ambiguity_ratio
```

较低，则应：

* 增大时间不确定度；
* 降低质量等级；
* 或直接拒绝匹配。

---

## 14.4 下传延迟

老师确认链路基本实时，但仍需考虑：

* 机载打包；
* 下传；
* 地面接收；
* 系统时间舍入。

该误差主要影响批次末端约束，不应假设为严格零。

---

# 15. 批次时间与累计机制统计

老师已确认时间语义，因此后续统计目标不再是判断“时间是什么”，而是估计批次机制。

每个高质量匹配批次计算：

```text
batch_duration_s
batch_end_lag_s
inter_batch_interval_s
```

其中：

```text
batch_duration =
last_estimated_observation_time
-
first_estimated_observation_time
```

```text
batch_end_lag =
amdar_batch_end_time
-
last_estimated_observation_time
```

```text
inter_batch_interval =
current_batch_end_time
-
previous_batch_end_time
```

按以下维度统计：

```text
ASC / CRZ / DES
airline
tail_number
aircraft type
batch size
route
flight level
```

由于下发周期动态变化，应分析分布，不应寻找单一固定周期。

---

# 16. pseudo-AMDAR 闭环验证

这是决定时间重建结果能否进入风场重构的核心实验。

## 16.1 样本构造

从完整 ADS-B 航段中分别选择：

* 爬升；
* 巡航；
* 下降。

模拟步骤：

1. 从 ADS-B 航段连续抽取一段轨迹；
2. 保留真实逐点时间作为隐藏真值；
3. 删除逐点时间；
4. 保留经纬度、高度、机尾号、航班号和原始顺序；
5. 将模拟批次时间设为最后一个观测时间加模拟下传延迟；
6. 使用正式算法恢复逐点时间；
7. 与隐藏的真实时间比较。

---

## 16.2 模拟真实批次分布

组大小应尽量复现真实 AMDAR：

```text
中位数：6
P90：17
P99：49
最大值：50
```

同时复现：

* 水平跨度分布；
* 垂直跨度分布；
* 不同飞行阶段；
* ADS-B 采样间隔；
* 轨迹缺口；
* 候选航段歧义；
* 动态批次持续时间。

模拟下传延迟可设置多组场景：

```text
0–30 s
30–60 s
1–3 min
异常延迟场景
```

---

## 16.3 闭环评价指标

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

### 分层统计

分别按以下维度报告：

```text
ASC / CRZ / DES
batch size
batch duration
horizontal span
vertical span
ADS-B sampling gap
candidate leg count
with / without tail number
```

---

# 17. 质量等级设计

最终 A/B/C 阈值必须由：

1. pseudo-AMDAR 闭环误差；
2. 目标风场时间分辨率；
3. 目标风场空间分辨率；

共同确定。

基本原则：

[
time_uncertainty
\leq
\frac{field_time_resolution}{2}
]

[
cross_track_distance
\leq
\frac{field_spatial_resolution}{2}
]

---

## 17.1 A 级

满足：

* 航段唯一；
* 原始顺序与 ADS-B 时间严格单调；
* 无阶段冲突；
* 几何残差满足精细风场要求；
* 时间误差 P90 满足目标时间分辨率；
* 无明显补传或长距离外推；
* 匹配歧义低。

用途：

```text
可进入精细风场重构
不可作为时间重建算法自身的严格验证真值
```

---

## 17.2 B 级

满足：

* 航段基本可信；
* 存在一定采样或几何误差；
* 时间误差可量化；
* 时间和空间误差大于 A 级，但仍在可接受范围内。

用途：

```text
降低权重进入较粗分辨率风场
或生成 super-observation
```

---

## 17.3 C 级

特征：

* 只能确定大致航段和时间窗；
* 逐点时间误差较大；
* 几何残差较高；
* 仍具有一定气象支持价值。

用途：

```text
30分钟或1小时时间窗
背景约束
super-observation
```

---

## 17.4 Reject

出现以下任一情况：

* 候选航段不唯一；
* 原始顺序无法单调匹配；
* 飞行阶段明显冲突；
* 水平或垂直残差过大；
* 需要长时间外推；
* 批次结束约束失败；
* ADS-B 数据覆盖不足；
* 时区、身份或航段无法确认。

用途：

```text
不进入风场重构
保留原始数据与拒绝原因
```

---

# 18. AMDAR 气象变量处理

## 18.1 时间质量与气象质量分离

建议保留：

```text
met_value_quality
time_quality
usage_role
```

时间无法重建不代表风、温度等观测值本身无效。

---

## 18.2 风向风速转换

AMDAR 风向通常是气象学来向。

转换为 (u,v)：

[
u=-V\sin\theta
]

[
v=-V\cos\theta
]

不能直接对风向角做普通算术平均。

---

## 18.3 气象质控

检查：

```text
wind_speed_range
temperature_range
spatial_gradient
vertical_gradient
flight_phase_consistency
duplicate_observation
```

气象异常和时间异常必须分开标记。

---

# 19. 数据去相关与 super-observation

同一架飞机连续观测具有较强相关性，不能将所有观测视为完全独立。

可根据目标风场分辨率，按以下方式生成超级观测：

* 固定时间窗口；
* 固定沿轨距离；
* 固定高度层；
* 固定时空网格。

输出：

```text
representative_time
representative_lat
representative_lon
representative_altitude

mean_u
mean_v
mean_temperature

sample_count
within_group_variance
time_uncertainty_s
spatial_uncertainty_km
```

A级可使用较细窗口，B/C 级应使用更粗窗口。

---

# 20. 时间误差进入风场观测权重

风场重构中的有效观测误差应包括：

[
R_{\text{effective}}
====================

R_{\text{instrument}}
+
R_{\text{representativeness}}
+
R_{\text{time}}
+
R_{\text{reconstruction}}
]

其中：

* A 级正常或轻微降权；
* B 级明显降权；
* C 级只用于粗时间窗或超级观测；
* Reject 不使用。

---

# 21. 风场重构消融实验

至少运行以下实验。

## Experiment 0：无 AMDAR

```text
不使用任何 AMDAR
```

作为基准。

## Experiment 1：仅 A 级 AMDAR

```text
仅使用高质量重建结果
```

## Experiment 2：A + B 级

```text
A级正常使用
B级降低权重
```

## Experiment 3：A + B + C

```text
C级仅以粗时间窗或super-ob形式加入
```

比较指标：

```text
u_rmse
v_rmse
wind_speed_rmse
wind_direction_error

spatial_smoothness
temporal_consistency
extreme_gradient_artifacts
```

验证数据必须独立于参与重构的 AMDAR，不能把同一批 AMDAR 同时作为输入和验证真值。

---

# 22. 当前原型的重新评估要求

此前 5000 行样本结果：

```text
重复时间组：521
匹配成功组：515
匹配成功行：4935
行级覆盖率：0.987

水平距离中位数：24.98 km
水平距离P90：46.58 km
```

该结果说明算法能够强制找到候选，但几何质量不足。

在老师最新信息下，原型必须加入：

```text
机尾号严格匹配
航班号匹配
批次结束时间单侧上界
原始行顺序硬单调约束
前一批结束时间软下界
阶段一致性
允许拒绝低质量匹配
```

重新运行后，不再把覆盖率作为主要指标。

主要指标改为：

```text
A/B/C级保留率
拒绝率
错误航段率
水平残差分布
垂直残差分布
时间误差分布
航段歧义率
```

如果加入新约束后水平距离仍普遍达到 20–50 km，应优先排查：

1. 北京时间和 UTC 转换；
2. 经纬度解析；
3. 高度单位和高度口径；
4. ADS-B 日期覆盖范围；
5. 机尾号格式；
6. 航班号格式；
7. ADS-B 航段切分；
8. 同一航班是否跨日；
9. AMDAR 与 ADS-B 数据是否来自完全相同日期和航段。

在这些问题排除前，不应通过放宽距离阈值提高覆盖率。

---

# 23. 代码文件规划

## 23.1 主链

```text
stage/stage1_prepare.py
```

职责：

* 标记 AMDAR 批次结束时间；
* 建立批次 ID；
* 建立批次内部观测顺序；
* 所有 AMDAR 取消 strict time truth；
* 防止下游将批次时间当逐点时间。

---

## 23.2 时间重建研究分支

```text
stage/reconstruct_amdar_time_from_adsb.py
```

职责：

* 构建 ADS-B 连续航段；
* 筛选候选航段；
* 批次级单调匹配；
* 轨迹线段投影；
* 时间插值；
* 不确定度计算；
* A/B/C 分级；
* 拒绝低质量匹配。

---

## 23.3 建议新增脚本

```text
stage/analyze_amdar_batch_sequence.py
stage/analyze_amdar_batch_mechanism.py
stage/build_adsb_flight_legs.py
stage/run_pseudo_amdar_validation.py
stage/evaluate_amdar_reconstruction.py
stage/build_amdar_superobs.py
stage/run_amdar_ablation.py
```

---

# 24. 输出文件规划

```text
amdar_stage1_conservative.parquet
amdar_batch_statistics.parquet
amdar_sequence_diagnostics.parquet

adsb_flight_legs.parquet
amdar_reconstructed_v1.parquet
amdar_reconstruction_rejected.parquet

pseudo_amdar_validation_results.parquet
amdar_reconstruction_summary.json

amdar_superobs_A.parquet
amdar_superobs_AB.parquet
amdar_superobs_ABC.parquet
```

---

# 25. 实施顺序

## 第一阶段：Stage1 防污染

1. 将原 AMDAR 时间改为批次结束时间语义；
2. 所有 AMDAR 设置 `strict_time_truth=false`；
3. 建立 `amdar_batch_id`；
4. 建立 `amdar_observation_order`；
5. 保留原始行号；
6. 修改 Stage2、Stage4，禁止把批次时间当逐点时间；
7. 输出批次统计和序列质量诊断。

---

## 第二阶段：ADS-B 航段构建

1. 统一时间、经纬度、高度和身份字段格式；
2. 按机尾号、航班号和日期聚类；
3. 按时间间隔和空间跳跃切分航段；
4. 建立 `adsb_leg_id`；
5. 输出 ADS-B 航段覆盖率和采样间隔统计。

---

## 第三阶段：重建算法修订

1. 候选航段机尾号优先；
2. 批次结束时间作为单侧上界；
3. 前一批结束时间作为软下界；
4. 使用原始行序进行整批单调匹配；
5. 使用轨迹线段投影插值时间；
6. 加入批次拒绝机制；
7. 输出最佳和第二佳候选；
8. 计算时间不确定度和质量等级。

---

## 第四阶段：闭环验证

1. 构造动态批次 pseudo-AMDAR；
2. 隐藏 ADS-B 真实时间；
3. 运行正式重建算法；
4. 统计航段识别率和时间误差；
5. 分 ASC、CRZ、DES 报告；
6. 确定 A/B/C 阈值；
7. 检查阈值在不同航司和机尾上的稳定性。

---

## 第五阶段：风场应用

1. 仅 A 级进入初始风场实验；
2. B 级降权后加入；
3. C 级生成粗时间窗 super-ob；
4. 运行无 AMDAR、A、A+B、A+B+C 消融；
5. 使用独立观测验证；
6. 判断重建 AMDAR 是否稳定改善风场；
7. 满足准入条件后再讨论回并主链。

---

# 26. 回并主链的准入条件

ADS-B 重建结果只有同时满足以下条件，才允许进入正式风场生产链：

1. pseudo-AMDAR 正确航段率达到目标；
2. 错误航段率足够低；
3. 时间误差 P90 满足目标时间分辨率；
4. 几何残差满足目标空间分辨率；
5. A/B/C 分级与真实误差存在稳定关系；
6. 算法在 ASC、CRZ、DES 中均经过验证；
7. 算法在不同航司和机尾上不过度失效；
8. 原始批次时间和重建时间始终分开保存；
9. 下游能够使用时间不确定度和质量等级；
10. 独立风场验证显示结果稳定改善；
11. 重建 AMDAR 不被用作自身算法的严格验证真值。

---

# 27. 最终工程口径

当前统一采用以下定义：

```text
AMDAR原始时间：
    地面接收时间
    近似为飞机下发时间
    作为批次结束时间

AMDAR逐点原始时间：
    未提供

AMDAR原始行序：
    代表批次内观测先后顺序

阶段累计周期：
    动态变化，不使用固定30分钟假设

所有原始AMDAR：
    strict_time_truth = false

ADS-B重建时间：
    estimated / reconstructed
    不覆盖原始批次结束时间

高质量重建结果：
    经过闭环验证后可进入风场重构

低质量结果：
    降权、粗时间窗、super-ob或拒绝
```

本方案的核心原则为：

> 以 AMDAR 批次结束时间作为逐点观测时间上界，以原始表格顺序作为严格先后约束，将整批 AMDAR 点单调投影到同机尾、同航班的 ADS-B 航迹上，估算逐点观测时间；所有结果必须携带匹配质量和时间不确定度，并在闭环验证通过后才进入风场重构。
