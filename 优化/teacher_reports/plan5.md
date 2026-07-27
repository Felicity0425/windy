# AMDAR Plan5：保守真值、置信度支持与多时间尺度风场重构计划

## 1. 计划目标

本计划不再追求把所有 AMDAR 转换成 strict truth，而是同时实现三个目标：

1. 保持严格真值定义不被破坏；
2. 尽可能让 AMDAR 以可审计的置信度参与风场重构；
3. 建立从时间不确定性到 Stage2/Stage4 权重的完整接口。

最终数据分为：

```text
S：严格逐点时间真值
A：高质量时间重建支持
B：中质量时间重建支持
C：批次级或粗时间窗支持
R：拒绝
```

其中只有 S 级可以作为 official strict holdout truth。

---

# P0：冻结 Stage1 Plan4 基线

## 目标

保留现有运行结果，确保后续修改可比较、可回退。

## 操作

冻结：

```text
stage1_output_plan4_v1
stage1_prepare.py
stage1_schema_v2.json
stage1_policy_v2.json
stage1_summary.json
```

记录：

```text
Git commit
Python 环境
Polars 版本
配置文件哈希
输入文件哈希
运行命令
CPU 和内存信息
```

## 输出

```text
stage1_plan4_frozen_manifest.json
stage1_plan4_file_hashes.json
stage1_plan4_environment.txt
```

## 完成标准

所有输入、代码和输出均可通过哈希追溯。

---

# P1：并行确定性验证

## 目标

确认 25 路并行没有改变批次顺序、batch_id 或分类结果。

## 运行三组配置

```text
A：POLARS_MAX_THREADS=25，num_workers=1
B：POLARS_MAX_THREADS=1，num_workers=25
C：POLARS_MAX_THREADS=4，num_workers=6
```

## 比较内容

```text
总行数
字段顺序和类型
分类计数
null 计数
batch_id
raw_row_number
amdar_observation_order
按稳定主键排序后的文件哈希
```

稳定主键建议：

```text
source
source_row_index
raw_row_number
flight_id
amdar_batch_id
```

## 输出

```text
stage1_parallel_determinism_report.json
stage1_parallel_performance_report.json
```

## 完成标准

三组运行逻辑结果完全一致，只允许运行时间和资源占用不同。

---

# P2：修复 Stage1 质量审计缺口

## 目标

确保进入时间匹配前，风值和单位本身没有未识别错误。

## 新增审计

### 风速单位

增加：

```text
wind_speed_raw
wind_speed_unit_source
wind_speed_unit_normalized
wind_speed_ms
wind_speed_unit_conversion_applied
```

重点核实当前：

```text
median = 57
p90 = 101
max = 254
```

到底是 knots、m/s 还是其他单位。

### 气象质量

输出：

```text
met_value_quality_counts
wind_speed_outlier_count
wind_direction_invalid_count
uv_nonfinite_count
temperature_outlier_count
altitude_outlier_count
duplicate_met_record_count
```

### 时间字段

输出：

```text
observation_time_utc_null_count
observation_time_source_counts
observation_time_uncertainty_summary
```

### 字段一致性

检查：

```text
effective_strict_truth=true
必须同时满足：
strict_time_truth=true
time_is_point_observation=true
point_observation_time_available=true
met_value_quality=passed
```

## 输出

```text
stage1_met_qc_rows.parquet
stage1_met_qc_summary.json
stage1_semantics_invariant_check.json
```

## 完成标准

所有单位明确；所有严格真值行满足字段不变量。

---

# P3：重构置信度数据模型

## 目标

停止使用单一常数 `obs_conf=0.35` 表示全部 AMDAR。

## 新增字段

```text
source_conf
met_conf
time_source_conf
sequence_conf
identity_conf
adsb_leg_conf
adsb_match_conf
spatial_match_conf
representativeness_conf
density_conf
base_support_conf
```

保留：

```text
truth_eligible
effective_strict_truth
```

但禁止通过 `base_support_conf` 推导 strict truth。

## 置信度计算

先执行硬拒绝：

```text
非有限风值
明显错误坐标
身份冲突
不可能时间
严重航迹跳跃
灾难性匹配歧义
```

通过硬拒绝后：

```text
base_support_conf =
    weighted_geometric_mean(
        source_conf,
        met_conf,
        sequence_conf,
        identity_conf,
        adsb_leg_conf,
        adsb_match_conf,
        spatial_match_conf,
        representativeness_conf
    )
```

## 输出

```text
amdar_confidence_components.parquet
amdar_confidence_policy_v1.json
```

## 完成标准

任何总置信度都能追溯到具体组成项，不再只有固定 0.35。

---

# P4：重新审计 ADS-B QC 和航段分级

## 目标

查明 A 级 leg 只有 45 条的真实原因。

## 操作

为每个 leg 保存失败原因：

```text
failed_time_order
failed_speed
failed_position_jump
failed_sampling_gap
failed_altitude
failed_identity
failed_duration
failed_point_count
failed_phase_consistency
```

分别统计每项条件单独剔除多少航段。

## 重点排查

```text
是否按 time_utc 排序后计算相邻速度
是否跨长时间缺口计算速度
是否跨航班或跨日期连接
是否使用 haversine/测地距离
速度单位是否统一为 m/s
同一航班号重复执行是否被合并
午夜航班是否被错误切断
```

## 航段等级

不直接用 A/B/C 一个总标签覆盖全部信息，改为：

```text
leg_time_quality
leg_geometry_quality
leg_identity_quality
leg_sampling_quality
leg_overall_quality
```

## 输出

```text
adsb_qc_v3_rows.parquet
adsb_leg_failure_reason_summary.json
adsb_leg_quality_components.parquet
```

## 完成标准

可以明确解释每一条 C 级 leg 为什么被降级。

---

# P5：独立重写 pseudo-AMDAR 闭环

## 目标

在不依赖真实 AMDAR 匹配的情况下验证时间重建算法。

## 数据构造

从通过基础 QC 的 ADS-B 连续片段中抽取：

```text
ASC
DES
LVR
```

模拟批次大小：

```text
1
2–4
5–10
11–25
26–50
```

模拟：

```text
30–180 秒采样
5–60 分钟批次跨度
不同下传延迟
位置噪声
高度偏差
ADS-B 缺测
身份字段缺失
候选航段歧义
部分异常点
```

## 数据划分

必须按：

```text
tail_number + date
```

进行分组划分：

```text
calibration set
validation set
locked test set
```

同一飞机同一天不能跨集合。

## 指标

```text
correct_leg_rate
wrong_leg_rate
reject_rate
time_error_q50
time_error_q90
time_error_q99
catastrophic_error_rate
coverage_error_curve
```

## 输出

```text
pseudo_amdar_train.parquet
pseudo_amdar_validation.parquet
pseudo_amdar_locked_test.parquet
pseudo_amdar_calibration_report.json
```

## 完成标准

locked test 上能够得到稳定的时间误差和错误航段率。

---

# P6：AMDAR—ADS-B 匹配 V3

## 目标

在修复 ADS-B QC 后重新进行真实匹配。

## 候选筛选

身份优先级：

```text
机尾号 + 航班号
机尾号 + 归一化航班号
机尾号一致、航班号缺失
航班号一致、机尾号缺失
身份冲突拒绝
```

时间条件：

```text
adsb_time <= batch_end_time + clock_tolerance
```

空间条件：

```text
航迹包络重叠
高度范围重叠
飞行阶段兼容
```

## 单调匹配

要求：

```text
一个 AMDAR 批次最多对应一条 ADS-B leg
AMDAR 原始顺序不变
沿轨位置单调非递减
估计时间单调非递减
不跨长 ADS-B 缺口插值
```

## 保存

```text
最佳候选代价
第二候选代价
ambiguity_margin
cross_track_distance
vertical_difference
sampling_gap
interpolation/extrapolation flag
```

## 输出

```text
amdar_adsb_match_v3.parquet
amdar_adsb_reject_v3.parquet
amdar_adsb_match_diagnostics_v3.json
```

## 完成标准

任何接受结果都可以完整追溯到对应 ADS-B 前后点。

---

# P7：建立时间不确定性，而非只保存单一估计时间

## 目标

让 Stage2 能够根据目标雷达帧动态计算时间相关性。

## 每条 AMDAR 保存

```text
estimated_time_q10
estimated_time_q50
estimated_time_q90
time_interval_start
time_interval_end
time_pdf_type
time_uncertainty_s
time_reconstruction_grade
```

## 对未匹配批次

使用：

```text
previous_batch_end
current_batch_end
原始批次顺序
沿轨距离
飞行阶段速度先验
```

构造宽时间区间。

## 输出

```text
amdar_time_uncertainty_v1.parquet
time_uncertainty_policy_v1.json
```

## 完成标准

所有非拒绝 AMDAR 至少拥有时间区间；只有高质量结果拥有窄时间分布。

---

# P8：确定 S/A/B/C/R 等级

## S 级

```text
源数据直接提供可信逐点时间
met_value_quality=passed
```

可用于 strict truth。

## A 级

```text
ADS-B 身份强匹配
时间误差 q90 满足精细风场要求
几何残差小
候选无明显歧义
非长距离外推
```

作为高权重支持，不自动成为 strict truth。

## B 级

```text
身份和航迹基本可信
时间误差较大
可用于较宽时间窗或降权支持
```

## C 级

```text
无法得到精确逐点时间
但批次、空间、顺序或风值仍可信
```

仅用于：

```text
粗时间窗
批次级支持
super-ob
低权重大尺度约束
```

## R 级

```text
气象值失败
身份冲突
严重轨迹异常
灾难性匹配歧义
```

不参与重构。

## 输出

```text
amdar_quality_thresholds_v2.json
amdar_quality_grade_summary.json
```

## 完成标准

等级阈值由 pseudo-AMDAR locked test 标定，而不是根据覆盖率人工放宽。

---

# P9：Stage2 V2 数据接口改造

## 目标

同时保留严格真值和带不确定性的支持观测。

## Stage2 输出通道

```text
strict_truth_records
current_support_records
context_support_records
batch_support_records
diagnostic_only_records
rejected_records
```

## 禁止

```text
原始 AMDAR batch_end_time 直接作为 point time
所有 AMDAR 直接进入 T±5min current window
在 holdout 前先把同体素观测平均
```

## 时间置信度

对每个目标帧 `T`：

```text
frame_time_conf_i(T) =
    AMDAR 时间概率分布
    与目标时间窗口的重叠概率
```

## 记录保留

Stage2 必须保存逐条观测：

```text
observation_id
flight_id
batch_id
source
time grade
quality grade
u/v
confidence components
```

同时可生成体素统计，但不能只保存聚合结果。

## 输出

```text
stage2_observation_records/
stage2_voxel_support_summary/
stage2_role_audit.json
```

## 完成标准

holdout 观测可以在任何聚合前被完整移除。

---

# P10：super-ob 和密度权重控制

## 目标

防止一架飞机、一个批次或一个航段因点数过多支配风场。

## 分组维度

```text
flight_id
amdar_batch_id
time bin
altitude bin
along-track distance bin
spatial voxel
```

## 每个 super-ob 保存

```text
weighted_u
weighted_v
within_group_spread
raw_point_count
effective_sample_size
unique_flight_count
time_uncertainty
quality_grade
```

## 权重上限

设置：

```text
max_weight_per_batch_per_frame
max_weight_per_flight_per_voxel
max_weight_per_source_per_frame
```

## 输出

```text
amdar_superobs_A.parquet
amdar_superobs_AB.parquet
amdar_superobs_ABC.parquet
```

## 完成标准

50 点批次不能自动获得单点批次 50 倍的总权重。

---

# P11：多时间尺度重构实验

## 目标

判断 AMDAR 适合的真实时间分辨率，而不是强迫所有数据进入最细时间窗。

## 时间尺度

至少比较：

```text
精细窗口：当前 radar frame window
15 分钟
30 分钟
60 分钟
```

## 实验

```text
E0：无 AMDAR
E1：仅 S
E2：S + A
E3：S + A + B
E4：S + A + B + C super-ob
E5：旧 legacy 方案
E6：所有 AMDAR 固定 0.35 的旧式方案
```

## 指标

```text
严格真值 RMSE/MAE
有效真值数量
frame coverage
空间覆盖
时间连续性
高空误差
稀疏区误差
伪梯度数量
单批次最大权重占比
```

## 完成标准

A/B/C 的加入必须在至少一个合理时间尺度上稳定改善结果，并且不能产生明显伪梯度。

---

# P12：真值稀缺条件下的评估体系

## 目标

避免用 181 条真值给出过度确定的全局结论。

## 四层结果分别报告

### Level 1：Conservative strict

只使用：

```text
effective_strict_truth=true
```

报告样本数和置信区间。

### Level 2：Legacy compatibility

继续报告旧 6796 条口径，但必须明确标记：

```text
legacy compatibility metric
not conservative strict truth
```

### Level 3：Pseudo-AMDAR time validation

只验证时间重建和航段匹配能力。

### Level 4：Consistency diagnostics

包括：

```text
时间连续性
空间平滑性
批次权重占比
观测创新
背景差异
```

不能把这些称为真实风场精度。

## 统计方式

采用：

```text
按 flight/date 分组 bootstrap
```

而不是逐行 bootstrap。

## 输出

```text
stage4_validation_tiered_report.json
stage4_validation_confidence_intervals.json
```

## 完成标准

任何 RMSE 都同时报告样本数、来源、时间语义和置信区间。

---

# P13：主链迁移门槛

只有满足以下条件才允许替换旧主链：

```text
Stage1 并行结果确定性通过
风速单位完成确认
ADS-B QC 失败原因明确
pseudo-AMDAR locked test 通过
A/B/C 阈值完成标定
Stage2 角色分流完成
strict holdout 无泄漏
多时间尺度消融稳定
```

主链迁移后仍保留：

```text
legacy branch
conservative branch
```

至少一个版本周期，以便回归比较。

---

# P14：最终产物

```text
stage1_output_plan5_v1/
amdar_confidence_components.parquet
adsb_leg_quality_components.parquet
pseudo_amdar_locked_test.parquet
amdar_time_uncertainty_v1.parquet
amdar_quality_thresholds_v2.json
stage2_role_aware_v2/
stage4_multiscale_ablation/
plan5_final_assessment.md
```

---

# 当前立即执行顺序

```text
1. P1 并行确定性验证
2. P2 风速单位和气象质量审计
3. P4 ADS-B leg 失败原因拆解
4. P5 独立重写 pseudo-AMDAR
5. P3 置信度字段拆分
6. P6/P7 匹配和时间不确定性
7. P8 等级标定
8. P9 Stage2 接口改造
9. P10 super-ob
10. P11/P12 重构与分层验证
```

当前禁止：

```text
把全部 AMDAR 改成 strict truth
把固定 0.35 直接提高到 0.8 或 1.0
按 batch_end_time 把整批点放进同一精细帧
为了提高覆盖率放宽到不可解释的匹配
用 legacy 6796 条指标冒充 conservative strict 结果
```
