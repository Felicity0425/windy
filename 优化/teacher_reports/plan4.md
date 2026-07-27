# AMDAR Plan4 v2：批次时间重建验证与风场应用执行计划

## 1. 当前阶段定位

当前已完成：

* AMDAR 批次时间语义确认；
* 原始重复时间结构统计；
* 按原始连续块建立批次；
* 建立批次内观测顺序；
* Stage1 保守字段落地；
* Stage1/Stage2 结构对齐检查；
* 全量批次序列诊断第一版；
* ADS-B 批次级匹配 smoke test。

当前尚未完成：

* ADS-B 数据完整质量审计；
* 分层 smoke test；
* 线段投影版本的完整验证；
* pseudo-AMDAR 闭环实验；
* A/B/C 质量阈值；
* 全量 AMDAR 时间重建；
* 风场消融实验。

当前任务重点是验证和提高匹配质量，而不是扩大覆盖率。

---

# 2. P0：冻结现有结果并修正字段定义

## 目的

保留当前结果作为可复现基线，同时消除字段语义冲突。

## 操作

1. 保存当前代码版本、配置和 summary。
2. 保存当前 smoke test 样本行号和 batch_id。
3. 将：

```text
batch_time_unknown_exact_type
```

修改为：

```text
ground_receive_approx_downlink_batch_end_time
```

4. 增加：

```text
batch_end_is_time_upper_bound = true
point_observation_time_available = false
```

5. 将旧字段明确标记为：

```text
legacy_wind_reconstruction_role
```

6. 新增：

```text
effective_strict_truth =
    strict_time_truth
    AND time_is_point_observation
    AND met_value_quality_pass
```

## 输出

```text
stage1_schema_v2.json
stage1_policy_v2.json
legacy_vs_conservative_counts.json
```

## 完成标准

* 431008 条 AMDAR 全部 `strict_time_truth=false`；
* 181 条 TURB 的原有时间角色不被意外修改；
* 旧评估和新保守评估可以分别运行。

---

# 3. P1：解决批次统计不一致

## 目的

保证每一条 AMDAR 都有唯一、可解释的分类。

## 操作

生成交叉表：

```text
flight_time_group_id
amdar_batch_id
batch_row_count
continuous_block_index
time_group_alignment_flag
time_semantics
batch_structure
usage_role
strict_time_truth
legacy_wind_reconstruction_role
```

重点检查：

```text
424393 - 424325 = 68
```

这些行具体属于什么情况。

增加批次结构类型：

```text
multi_point_contiguous
singleton_contiguous
same_timestamp_multiblock
discontiguous_singleton_block
```

检查：

```text
56521 batches
56365 original flight+time groups
155 multiblock groups
```

并输出每个原始组被切成几个块。

## 输出

```text
amdar_classification_cross_table.parquet
amdar_multiblock_group_summary.parquet
amdar_invariant_check.json
```

## 完成标准

* 所有分类合计严格等于 431008；
* 每行只有一个 batch_id；
* 每行只有一种 time_semantics；
* 68 行差异得到明确解释；
* 155 个多块组的 block_count 全部可追溯。

---

# 4. P2：补充批次序列诊断

## 目的

将现有均值结果升级为可用于质量分级的分布结果。

## 操作

按 ASC、DES、LVR 分别输出：

```text
altitude_increase_ratio q10/q25/q50/q75/q90
altitude_decrease_ratio q10/q25/q50/q75/q90
path_efficiency q10/q25/q50/q75/q90
adjacent_distance q50/q90/q99
max_adjacent_jump
```

按批次大小分层：

```text
1 point
2–4 points
5–10 points
11–25 points
26–49 points
50 points
```

建立诊断标志：

```text
sequence_good
sequence_suspicious
sequence_bad
```

检查 392 个 50 点 ASC 批次是否在相同航班中连续出现，并计算相邻批次之间的空间和高度连续性。

## 输出

```text
amdar_sequence_diagnostics_v2.parquet
amdar_sequence_phase_summary.json
amdar_size50_chain_analysis.parquet
```

## 完成标准

* 不再只报告均值；
* 可以明确知道各阶段多少批次顺序可靠；
* 50 点批次的分包特征得到初步解释。

---

# 5. P3：ADS-B 数据完整质量审计

## 目的

避免使用本身有时区、单位、位置或身份错误的 ADS-B 航迹进行重建。

## 操作

### 时间

检查：

```text
timestamp_timezone
UTC conversion
cross-day conversion
duplicate timestamp
non-increasing timestamp
```

### 身份

统一：

```text
tail_number_normalized
flight_number_normalized
callsign_normalized
```

统计：

```text
tail missing rate
flight missing rate
tail-flight conflict rate
```

### 位置

根据连续位置和时间重新计算：

```text
apparent_ground_speed
```

标记：

```text
position_jump
zero_time_nonzero_distance
unreasonable_speed
duplicate_position
```

### 高度

保存：

```text
altitude_raw
altitude_value
altitude_unit
altitude_reference
```

尽量区分：

```text
barometric
geometric
pressure
unknown
```

### 采样

统计：

```text
sampling_gap q50/q90/q99
long_gap count
```

## 输出

```text
adsb_qc_rows.parquet
adsb_qc_summary.json
adsb_identity_summary.json
adsb_altitude_reference_summary.json
```

## 完成标准

* 极端速度和位置跳跃有明确标记；
* 高度单位不再仅依靠数值猜测；
* 每条可用 ADS-B 记录都有时间、位置和身份质量标志。

---

# 6. P4：重新构建高质量 ADS-B 航段

## 目的

确保一个 `adsb_leg_id` 尽可能对应一次真实连续飞行。

## 操作

优先按：

```text
tail_number
flight_number
date
```

聚类。

根据以下条件切段：

```text
large_time_gap
large_position_jump
flight_number_change
landing_then_takeoff
phase_reset
identity_conflict
```

每个航段计算：

```text
point_count
start_time
end_time
duration
start/end position
altitude range
sampling_gap distribution
position_jump count
leg_quality
```

## 输出

```text
adsb_flight_legs_v2.parquet
adsb_leg_points_v2.parquet
adsb_leg_summary_v2.json
```

## 完成标准

* 每个候选航段内部时间严格递增；
* 不存在明显瞬移；
* 高质量航段和低质量航段分开；
* 低质量航段不能参与 A 级重建。

---

# 7. P5：候选航段筛选分级

## 目的

先排除不可能的航段，再进入昂贵的序列匹配。

## 操作

定义身份等级：

```text
ID-A：机尾号和航班号完全一致
ID-B：机尾号一致，归一化后航班号一致
ID-C：机尾号一致，航班号缺失
ID-D：航班号一致，机尾号缺失
ID-R：身份冲突
```

应用时间条件：

```text
adsb_time <= batch_end_time + clock_tolerance
```

有前一批时：

```text
previous_batch_end_time
```

作为软下界。

继续筛选：

```text
spatial envelope overlap
altitude range overlap
phase compatibility
```

## 输出

```text
amdar_adsb_candidate_legs.parquet
candidate_rejection_summary.json
```

## 完成标准

* 每个 AMDAR 批次的候选数可统计；
* 候选为零、一个和多个的原因可区分；
* ID-R 不能进入匹配；
* ID-D 不能直接成为 A 级结果。

---

# 8. P6：批次级单调匹配 V2

## 目的

将一个 AMDAR 批次完整映射到同一条 ADS-B 航段。

## 操作

约束：

```text
AMDAR 原始顺序不变
估计时间严格递增
沿轨位置非递减
时间不晚于批次结束时间
飞行阶段基本一致
```

代价包括：

```text
cross-track distance
vertical difference
sequence consistency
phase consistency
batch-end constraint
jump penalty
identity grade
candidate ambiguity
ADS-B sampling gap
```

允许：

```text
跳过少量异常 AMDAR 点
跳过 ADS-B 缺测区
局部点拒绝
整批拒绝
```

禁止：

```text
AMDAR风向与ADS-B航向比较
跨多个ADS-B航段拼接一个批次
为提高覆盖率强制匹配
```

## 输出

```text
amdar_adsb_match_v2.parquet
amdar_adsb_rejected_v2.parquet
match_cost_diagnostics.json
```

## 完成标准

* 匹配时间不存在倒序；
* 每个批次最多对应一条 ADS-B 航段；
* 最佳候选和第二佳候选都被保存；
* 完整匹配、部分匹配和弱匹配分开统计。

---

# 9. P7：轨迹线段投影和时间插值

## 目的

避免直接把 AMDAR 点赋给最近 ADS-B 离散点。

## 操作

将 AMDAR 点投影到相邻 ADS-B 线段：

```text
A(t0) → B(t1)
```

得到：

```text
interpolation_fraction
estimated_observation_time
cross_track_distance
vertical_difference
sampling_gap
```

原则上只允许线段内部插值。

外推必须保存：

```text
extrapolation_seconds
extrapolation_distance
```

超过阈值直接拒绝。

## 输出

```text
amdar_reconstructed_pilot_v2.parquet
```

## 完成标准

* 每个估计时间可以追溯到前后两个 ADS-B 点；
* 外推结果和插值结果分开；
* 不再只输出最近邻时间。

---

# 10. P8：分层 smoke test

## 目的

确认结果不是由某几个日期或航班偶然造成。

## 操作

按以下条件分层抽样：

```text
ASC / DES / LVR
日期
航空公司
机尾号
批次大小
水平跨度
垂直跨度
ADS-B覆盖等级
身份等级
```

至少报告：

```text
complete_group_match_rate
partial_group_match_rate
weak_group_match_rate
row_match_rate
reject_rate
unmatched_rate

horizontal residual by phase
vertical residual by phase
identity grade distribution
candidate count distribution
ambiguity ratio distribution
batch_end_lag distribution
sampling_gap distribution
```

拒绝原因分开：

```text
no_adsb_coverage
no_identity_candidate
geometry_failed
altitude_failed
phase_failed
ambiguous_candidate
sequence_failed
```

## 输出

```text
stratified_smoke_test_results.parquet
stratified_smoke_test_summary.json
```

## 完成标准

* 结果覆盖多个日期、航司和阶段；
* 不再只报告总体中位数；
* 可以定位水平误差主要来自哪类数据。

---

# 11. P9：pseudo-AMDAR 闭环验证

## 目的

得到真实可计算的时间重建误差。

## 操作

从完整 ADS-B 航段中：

1. 抽取连续轨迹；
2. 保存真实逐点时间；
3. 隐藏逐点时间；
4. 保留位置、高度、身份和顺序；
5. 赋予统一批次结束时间；
6. 运行与真实 AMDAR 完全相同的重建代码；
7. 将估计时间与隐藏真值比较。

模拟：

```text
不同阶段
不同批次大小
不同航迹跨度
不同采样间隔
不同数据缺口
不同下传延迟
不同身份缺失
不同候选歧义
```

## 输出

```text
pseudo_amdar_cases.parquet
pseudo_amdar_reconstruction.parquet
pseudo_amdar_validation_summary.json
```

核心指标：

```text
correct_leg_rate
wrong_leg_rate
reject_rate
time_error_q50
time_error_q90
time_error_q99
catastrophic_error_rate
```

## 完成标准

* 能够真实量化时间误差；
* 能够知道哪些条件下容易匹配错航段；
* 在完成本阶段前，不运行全量真实 AMDAR 重建。

---

# 12. P10：确定 A/B/C/Reject 标准

## 目的

将匹配结果转换成风场可以使用的质量等级。

## 操作

根据：

```text
pseudo-AMDAR真实时间误差
目标风场时间分辨率
目标风场空间分辨率
身份等级
几何残差
航段歧义
外推情况
```

制定等级。

A：

```text
可进入精细风场
```

B：

```text
降权使用或较粗分辨率使用
```

C：

```text
仅用于粗时间窗或super-ob
```

Reject：

```text
不进入风场
```

## 输出

```text
amdar_quality_thresholds_v1.json
amdar_quality_calibration_report.md
```

## 完成标准

* 阈值由闭环误差得到，不是主观拍定；
* 当前 18.66 km 中位水平残差不能自动视为 A 级；
* A/B/C 与真实误差具有稳定关系。

---

# 13. P11：小规模真实数据试运行

## 目的

在全量运行前，确认真实 AMDAR 上的运行稳定性。

## 操作

选择：

```text
多个日期
多个航司
ASC/DES/LVR
不同批次大小
不同ADS-B覆盖质量
```

运行重建并人工抽查典型轨迹图。

每个案例绘制：

```text
AMDAR原始点
ADS-B轨迹
匹配投影点
批次结束时间
估计逐点时间
拒绝点
```

## 输出

```text
real_amdar_pilot_results.parquet
real_amdar_case_plots/
real_amdar_pilot_summary.json
```

## 完成标准

* A 级结果在图上具有明显轨迹一致性；
* 不存在系统性跨航段匹配；
* 时间顺序和飞行阶段一致；
* 运行资源可控。

---

# 14. P12：全量时间重建

## 前置条件

只有 P9、P10、P11 全部通过后才执行。

## 操作

按以下方式分区：

```text
日期
机尾号
航班号
```

要求：

```text
支持断点续跑
分区完成立即写出
失败分区单独记录
不覆盖原始批次时间
```

并行数量根据性能测试确定，不强制固定 25 路。

## 输出

```text
amdar_reconstructed_A.parquet
amdar_reconstructed_B.parquet
amdar_reconstructed_C.parquet
amdar_reconstruction_rejected.parquet
```

---

# 15. P13：气象质控和 super-ob

## 目的

防止同一飞机密集观测在风场中权重过高。

## 操作

将风向风速转换为：

```text
u
v
```

分别保存：

```text
met_value_quality
time_quality
```

根据目标网格按时间、沿轨距离和高度层生成超级观测。

## 输出

```text
amdar_superobs_A.parquet
amdar_superobs_AB.parquet
amdar_superobs_ABC.parquet
```

---

# 16. P14：风场消融实验

运行：

```text
实验0：无AMDAR
实验1：仅A级
实验2：A+B，B降权
实验3：A+B+C，C仅使用super-ob
实验4：旧legacy主链
```

使用独立观测评估：

```text
u_rmse
v_rmse
wind_speed_rmse
wind_direction_error
temporal_consistency
spatial_smoothness
false_gradient_artifacts
```

只有高质量重建 AMDAR 能够稳定改善独立验证结果时，才允许进入正式生产链。

---

# 17. 当前立即执行顺序

现在执行：

```text
P0 字段语义修正
P1 统计一致性修复
P2 补充分位数和异常批次分析
P3 ADS-B质量审计
P4 高质量ADS-B航段重建
P5 候选筛选
P6/P7 匹配与投影优化
P8 分层smoke test
P9 pseudo-AMDAR闭环
```

现在不要执行：

```text
全量AMDAR时间重建
直接回写Stage1 time_utc
把重建结果改成strict truth
直接送入正式风场
```
