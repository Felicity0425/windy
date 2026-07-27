# AMDAR 数据处理统一实施方案
## 生成时间：2026-07-01
## 方案版本：Unified Plan (融合 Plan4 + Plan5)

---

## 执行摘要

本方案融合了 Plan4 的分层置信度体系和 Plan5 的质量审计流程，提供完整的 AMDAR 数据处理解决方案。

### 核心原则

1. **严格真值边界**：不降低 strict truth 标准，只有具备逐点观测时间的数据才能作为 holdout truth
2. **分层数据利用**：通过置信度体系充分利用所有 AMDAR 数据，而非丢弃或降低标准
3. **可审计性**：所有处理步骤可追溯，所有置信度可解释
4. **渐进式验证**：每个阶段都有明确的验证标准和回退机制

### 数据现实

根据数据提供方确认和全量审计结果：

```text
AMDAR 总数：431,008 条
批次时间特征：98.47% 属于重复时间批次
时间语义：飞机在不同飞行阶段累计下发一批数据
  - 爬升阶段：30 分钟一次，一次下发 n 个数据
  - 巡航阶段：批次下发
  - 下降阶段：批次下发
原始时间字段：批次下发/接收时间，不是逐点真实观测时间
```

### 方案目标

1. **Stage1 增强**：添加置信度字段，明确时间语义，保持向后兼容
2. **ADS-B 时间重建**：作为研究分支继续推进，不阻塞主线
3. **分层置信度体系**：T0-T4 五层分级，支持不同使用场景
4. **Stage2/Stage4 集成**：提供清晰的数据接口和权重计算方法
5. **完整验证框架**：包括 pseudo-AMDAR 闭环、分层评估、消融实验

---

## 第一部分：数据分级体系

### 1.1 分级定义（融合 Plan4 T0-T4 和 Plan5 S/A/B/C/R）

#### T0 层 / S 级：Strict Truth（严格真值）

**定义**：
- 具备逐点观测时间，独立于任何模型/背景
- 可用于 holdout 验证
- 时间不确定性 < 60 秒

**当前符合**：
- TURB：181 条
- AMDAR：0 条（除非 ADS-B 重建达到 A+ 级别）

**置信度**：
```python
obs_conf = 1.0
holdout_eligible = True
effective_strict_truth = True
time_is_point_observation = True
```

**用途**：
- Stage4 holdout evaluation 唯一真值源
- 不参与风场重构（reconstruction），仅用于验证

---

#### T1 层 / A 级：High-Confidence Support（高置信度支持）

**定义**：
- 时间不确定性 < 5 分钟
- 空间代表性好
- 气象质量通过
- ADS-B 重建成功且几何残差小

**AMDAR 候选条件**：
1. **单点批次**（batch_row_count = 1）
2. **小批次中心点**（2-4 点批次，空间跨度 < 0.1°，高度跨度 < 200m）
3. **A 级 ADS-B 重建成功**：
   - 身份强匹配（机尾号 + 航班号一致）
   - 时间误差 q90 < 3 分钟
   - 几何残差小（水平 < 5km，垂直 < 200m）
   - 候选无明显歧义（ambiguity_margin > 2.0）

**置信度范围**：
```python
obs_conf = 0.70 - 0.85
time_uncertainty_s = 60 - 300
holdout_eligible = False  # 即使高置信度，仍不进 holdout
```

**用途**：
- Stage4 OI 主要约束，权重高
- 不进 holdout 但可以作为主要支持数据

---

#### T2 层 / B 级：Medium-Confidence Support（中置信度支持）

**定义**：
- 时间不确定性 5-15 分钟
- 批次内空间跨度 < 2°，高度跨度 < 1000m
- B 级 ADS-B 重建或批次特征较好

**AMDAR 候选条件**：
1. **中小批次**（5-10 点）且批次跨度不大
2. **B 级 ADS-B 重建成功**：
   - 身份和航迹基本可信
   - 时间误差 q90 < 10 分钟
   - 几何残差中等
3. **飞行阶段稳定**（LVR 巡航阶段优先）

**置信度范围**：
```python
obs_conf = 0.45 - 0.65
time_uncertainty_s = 300 - 900
holdout_eligible = False
```

**用途**：
- Stage4 OI 次要约束，降权使用
- 可用于较宽时间窗（15-30 分钟）

---

#### T3 层 / C 级：Low-Confidence Support（低置信度支持）

**定义**：
- 时间不确定性 15-30 分钟
- 批次跨度较大但仍在合理范围
- 无法得到精确逐点时间，但批次、空间、顺序或风值仍可信

**AMDAR 候选条件**：
1. **大批次**（11-25 点）
2. **超大批次**（26-50 点）中质量较好的部分
3. **C 级时间估计**：基于批次顺序和飞行阶段速度先验

**置信度范围**：
```python
obs_conf = 0.25 - 0.40
time_uncertainty_s = 900 - 1800
holdout_eligible = False
```

**用途**：
- 背景填充、大尺度约束
- super-ob 聚合
- 粗时间窗（30-60 分钟）
- 高权重压制（避免单批次主导）

---

#### T4 层 / R 级：Display-Only / Rejected（仅展示或拒绝）

**定义**：
- 时间不确定性 > 30 分钟，或空间跨度极大（> 5°）
- 或气象值失败、身份冲突、严重轨迹异常

**AMDAR 候选**：
1. **Display-Only**（T4-D）：
   - 最大批次（50 点）
   - 异常批次但风值可信
   - 仅用于完整性展示、CMA-style background fill
2. **Rejected**（T4-R）：
   - 非有限风值
   - 明显错误坐标
   - 身份冲突
   - 不可能时间
   - 严重航迹跳跃
   - 灾难性匹配歧义

**置信度范围**：
```python
# Display-Only
obs_conf = 0.05 - 0.20
time_uncertainty_s = 1800+
holdout_eligible = False

# Rejected
obs_conf = 0.0
rejected = True
```

**用途**：
- T4-D：完整性展示，不参与正式评估
- T4-R：完全不使用

---

### 1.2 分级流程图

```text
AMDAR 原始数据
    |
    ├─> 硬拒绝检查（QC）
    |       ├─> 非有限风值 ─────────────> T4-R (Rejected)
    |       ├─> 明显错误坐标 ───────────> T4-R
    |       ├─> 身份冲突 ─────────────> T4-R
    |       └─> 通过 ─────────────────> 继续
    |
    ├─> 批次特征分析
    |       ├─> batch_row_count
    |       ├─> horizontal_span_deg
    |       ├─> vertical_span_m
    |       ├─> flight_phase
    |       └─> met_consistency
    |
    ├─> ADS-B 时间重建（可选）
    |       ├─> A 级重建成功 ───────────> T1 (A 级)
    |       ├─> B 级重建成功 ───────────> T2 (B 级)
    |       ├─> C 级重建成功 ───────────> T3 (C 级)
    |       └─> 未匹配 ─────────────────> 继续
    |
    └─> 基于批次特征分级
            ├─> 单点批次 + 质量好 ─────> T1
            ├─> 小批次 + 跨度小 ────────> T1/T2
            ├─> 中批次 + 跨度中等 ──────> T2/T3
            ├─> 大批次 ──────────────> T3
            └─> 超大批次或跨度极大 ────> T4-D
```

---

## 第二部分：置信度计算方法

### 2.1 置信度组成（融合 Plan4 和 Plan5）

每条 AMDAR 的最终置信度由以下组件计算：

```python
base_support_conf = weighted_geometric_mean(
    source_conf,          # 数据源基准置信度
    met_conf,             # 气象质量置信度
    time_source_conf,     # 时间来源置信度
    sequence_conf,        # 批次顺序置信度
    identity_conf,        # 航班身份置信度
    adsb_leg_conf,        # ADS-B 航段质量
    adsb_match_conf,      # ADS-B 匹配质量
    spatial_match_conf,   # 空间匹配质量
    representativeness_conf  # 空间代表性
)
```

### 2.2 详细计算公式

#### 2.2.1 数据源基准置信度

```python
def calculate_source_conf(source):
    """数据源基准置信度"""
    if source == 'turb':
        return 1.0  # TURB 数据结构干净
    elif source == 'amdar':
        return 0.90  # AMDAR 仪器精度较高，但时间语义问题
    else:
        return 0.70
```

#### 2.2.2 气象质量置信度

```python
def calculate_met_conf(row):
    """气象质量置信度"""
    issues = []
    
    # 风速检查
    if not np.isfinite(row['wind_speed']):
        return 0.0
    if row['wind_speed'] < 0 or row['wind_speed'] > 150:  # m/s
        return 0.0
    
    # 风向检查
    if not np.isfinite(row['wind_dir']):
        return 0.0
    if row['wind_dir'] < 0 or row['wind_dir'] >= 360:
        return 0.0
    
    # u/v 一致性检查
    computed_speed = np.sqrt(row['u_wind']**2 + row['v_wind']**2)
    if abs(computed_speed - row['wind_speed']) > 0.1:
        issues.append('uv_inconsistent')
    
    # 温度检查（如果有）
    if 'temperature' in row and np.isfinite(row['temperature']):
        if row['temperature'] < -80 or row['temperature'] > 50:
            issues.append('temp_outlier')
    
    # 计算置信度
    if len(issues) == 0:
        return 1.0
    elif len(issues) == 1 and 'temp_outlier' in issues:
        return 0.85  # 温度异常不影响风场
    else:
        return 0.60
```

#### 2.2.3 批次特征置信度

```python
def calculate_batch_conf(batch):
    """
    基于批次特征计算置信度
    考虑：批次大小、空间跨度、飞行阶段、气象一致性
    """
    
    # 1. 批次大小因子
    if batch.row_count == 1:
        size_factor = 0.85  # 单点但仍有批次时间不确定性
    elif batch.row_count <= 4:
        size_factor = 0.70
    elif batch.row_count <= 10:
        size_factor = 0.55
    elif batch.row_count <= 25:
        size_factor = 0.35
    else:
        size_factor = 0.15
    
    # 2. 空间跨度因子
    hspan_deg = batch.hspan_deg
    vspan_m = batch.vspan_m
    
    if hspan_deg < 0.1 and vspan_m < 200:
        spatial_factor = 1.0  # 高度集中
    elif hspan_deg < 0.5 and vspan_m < 500:
        spatial_factor = 0.85  # 中等集中
    elif hspan_deg < 1.0 and vspan_m < 1000:
        spatial_factor = 0.65  # 较分散
    elif hspan_deg < 2.0 and vspan_m < 2000:
        spatial_factor = 0.40  # 分散
    else:
        spatial_factor = 0.15  # 极度分散
    
    # 3. 飞行阶段因子
    if batch.phase == 'LVR':
        phase_factor = 1.0  # 巡航最稳定
    elif batch.phase == 'ASC':
        phase_factor = 0.85  # 爬升变化快
    elif batch.phase == 'DES':
        phase_factor = 0.75  # 下降变化更快
    else:
        phase_factor = 0.70  # 未知阶段
    
    # 4. 气象一致性因子
    if batch.has_multiple_points:
        wind_std = batch.wind_speed_std
        dir_std = batch.wind_dir_circular_std
        
        if wind_std < 5 and dir_std < 15:
            met_factor = 1.0  # 高度一致
        elif wind_std < 10 and dir_std < 30:
            met_factor = 0.85  # 中等一致
        elif wind_std < 20 and dir_std < 60:
            met_factor = 0.70  # 变化较大
        else:
            met_factor = 0.50  # 变化很大（可能真实变化或质量问题）
    else:
        met_factor = 0.90  # 单点无法检查一致性，给予较高默认值
    
    # 5. 最终批次置信度
    batch_conf = size_factor * spatial_factor * phase_factor * met_factor
    
    # 6. 时间不确定性估算（秒）
    if batch.row_count == 1:
        time_uncertainty = 300  # 5 分钟
    elif batch.row_count <= 4:
        time_uncertainty = 600  # 10 分钟
    elif batch.row_count <= 10:
        time_uncertainty = 900  # 15 分钟
    elif batch.row_count <= 25:
        time_uncertainty = 1500  # 25 分钟
    else:
        time_uncertainty = 1800  # 30 分钟
    
    return {
        'batch_conf': max(0.05, min(0.85, batch_conf)),
        'time_uncertainty_s': time_uncertainty,
        'spatial_representativeness': spatial_factor,
        'size_factor': size_factor,
        'spatial_factor': spatial_factor,
        'phase_factor': phase_factor,
        'met_factor': met_factor
    }
```

#### 2.2.4 ADS-B 重建置信度

```python
def calculate_adsb_recon_conf(match_result):
    """ADS-B 时间重建置信度"""
    
    if match_result is None or match_result['rejected']:
        return {
            'adsb_leg_conf': 0.0,
            'adsb_match_conf': 0.0,
            'time_source_conf': 0.0,
            'reconstructed_time': None,
            'time_uncertainty_s': None
        }
    
    # 1. ADS-B 航段质量
    leg_quality = match_result['leg_overall_quality']
    if leg_quality == 'A':
        leg_conf = 1.0
        base_time_unc = 60  # 1 分钟
    elif leg_quality == 'B':
        leg_conf = 0.80
        base_time_unc = 180  # 3 分钟
    elif leg_quality == 'C':
        leg_conf = 0.50
        base_time_unc = 600  # 10 分钟
    else:
        leg_conf = 0.0
        return {'adsb_leg_conf': 0.0, 'adsb_match_conf': 0.0, 
                'time_source_conf': 0.0}
    
    # 2. 匹配质量
    identity_match = match_result['identity_match_level']  # strong/medium/weak
    ambiguity_margin = match_result['ambiguity_margin']
    cross_track_dist = match_result['cross_track_distance_m']
    vertical_diff = match_result['vertical_difference_m']
    
    # 身份匹配
    if identity_match == 'strong':
        identity_factor = 1.0
    elif identity_match == 'medium':
        identity_factor = 0.80
    else:
        identity_factor = 0.50
    
    # 歧义度
    if ambiguity_margin > 2.0:
        ambiguity_factor = 1.0
    elif ambiguity_margin > 1.2:
        ambiguity_factor = 0.80
    else:
        ambiguity_factor = 0.50
    
    # 几何残差
    if cross_track_dist < 5000 and vertical_diff < 200:
        geometry_factor = 1.0
        time_unc_mult = 1.0
    elif cross_track_dist < 15000 and vertical_diff < 500:
        geometry_factor = 0.85
        time_unc_mult = 1.5
    elif cross_track_dist < 30000 and vertical_diff < 1000:
        geometry_factor = 0.65
        time_unc_mult = 2.0
    else:
        geometry_factor = 0.30
        time_unc_mult = 3.0
    
    # 插值外推标志
    if match_result['is_extrapolation']:
        extrapolation_factor = 0.60
        time_unc_mult *= 1.5
    elif match_result['crosses_large_gap']:
        extrapolation_factor = 0.75
        time_unc_mult *= 1.3
    else:
        extrapolation_factor = 1.0
    
    match_conf = (identity_factor * ambiguity_factor * 
                  geometry_factor * extrapolation_factor)
    
    # 3. 最终时间来源置信度
    time_source_conf = leg_conf * match_conf
    final_time_unc = base_time_unc * time_unc_mult
    
    return {
        'adsb_leg_conf': leg_conf,
        'adsb_match_conf': match_conf,
        'time_source_conf': time_source_conf,
        'reconstructed_time': match_result['estimated_time_q50'],
        'time_interval_start': match_result['estimated_time_q10'],
        'time_interval_end': match_result['estimated_time_q90'],
        'time_uncertainty_s': final_time_unc,
        'time_pdf_type': 'gaussian' if geometry_factor > 0.8 else 'uniform'
    }
```

#### 2.2.5 分层分配

```python
def assign_tier(row):
    """
    根据最终置信度和时间不确定性分配层级
    优先使用 ADS-B 重建结果，其次使用批次特征
    """
    
    # 1. 检查是否为 TURB strict truth
    if row['source'] == 'turb' and row['effective_strict_truth']:
        return {
            'tier': 'T0',
            'grade': 'S',
            'obs_conf': 1.0,
            'holdout_eligible': True
        }
    
    # 2. 使用 ADS-B 重建结果（如果有）
    if row['adsb_reconstructed'] and row['time_source_conf'] > 0:
        time_unc = row['time_uncertainty_s']
        time_conf = row['time_source_conf']
        
        if time_conf >= 0.80 and time_unc < 180:
            return {'tier': 'T1', 'grade': 'A', 'obs_conf': 0.80, 
                    'holdout_eligible': False}
        elif time_conf >= 0.65 and time_unc < 600:
            return {'tier': 'T2', 'grade': 'B', 'obs_conf': 0.65, 
                    'holdout_eligible': False}
        elif time_conf >= 0.45 and time_unc < 1200:
            return {'tier': 'T3', 'grade': 'C', 'obs_conf': 0.50, 
                    'holdout_eligible': False}
        else:
            return {'tier': 'T4', 'grade': 'D', 'obs_conf': 0.15, 
                    'holdout_eligible': False}
    
    # 3. 使用批次特征（AMDAR 未重建或重建失败）
    if row['source'] == 'amdar':
        batch_conf = row['batch_conf']
        time_unc = row['time_uncertainty_s']
        
        # 应用 AMDAR 上限（因为批次时间语义）
        batch_conf = min(batch_conf, 0.85)
        
        if batch_conf >= 0.70 and time_unc < 300:
            return {'tier': 'T1', 'grade': 'A', 'obs_conf': batch_conf, 
                    'holdout_eligible': False}
        elif batch_conf >= 0.45 and time_unc < 900:
            return {'tier': 'T2', 'grade': 'B', 'obs_conf': batch_conf, 
                    'holdout_eligible': False}
        elif batch_conf >= 0.25 and time_unc < 1800:
            return {'tier': 'T3', 'grade': 'C', 'obs_conf': batch_conf, 
                    'holdout_eligible': False}
        else:
            return {'tier': 'T4', 'grade': 'D', 'obs_conf': 0.10, 
                    'holdout_eligible': False}
    
    # 4. 其他数据源
    return {'tier': 'T3', 'grade': 'C', 'obs_conf': 0.40, 
            'holdout_eligible': False}
```

---

## 第三部分：执行阶段（融合 Plan4 P0-P15 和 Plan5 P0-P14）

### 阶段 0：冻结基线并验证确定性（必须优先）

**来源**：Plan5 P0 + P1

**目标**：
1. 冻结 Stage1 Plan4 当前运行结果作为可比较基线
2. 验证并行处理的确定性

**操作**：

1. **冻结基线**：
```bash
# 冻结目录和文件
stage1_output_plan4_v1/
stage1_prepare.py
stage1_schema_v2.json
stage1_policy_v2.json
stage1_summary.json

# 记录完整环境
- Git commit hash
- Python 版本和环境
- Polars 版本
- 输入文件 SHA256
- 配置文件 SHA256
- 运行命令
```

2. **并行确定性测试**：
```bash
# 运行三组配置
Config A: POLARS_MAX_THREADS=25, num_workers=1
Config B: POLARS_MAX_THREADS=1, num_workers=25
Config C: POLARS_MAX_THREADS=4, num_workers=6

# 比较内容
- 总行数
- 字段类型和顺序
- 分类计数
- null 计数
- batch_id 分配
- 按稳定主键排序后的文件哈希
```

**稳定主键**：
```python
sort_keys = ['source', 'source_row_index', 'raw_row_number', 
             'flight_id', 'amdar_batch_id']
```

**输出**：
```text
stage1_plan4_frozen_manifest.json
stage1_plan4_file_hashes.json
stage1_plan4_environment.txt
stage1_parallel_determinism_report.json
stage1_parallel_performance_report.json
```

**完成标准**：
- 所有输入、代码和输出可通过哈希追溯
- 三组并行配置逻辑结果完全一致
- 只允许运行时间和资源占用不同

**预计工时**：4-6 小时

---

### 阶段 1：Stage1 质量审计缺口修复（必须优先）

**来源**：Plan5 P2

**目标**：确保进入时间匹配前，风值和单位本身没有未识别错误

**操作**：

1. **风速单位核实**：
```python
# 新增字段
wind_speed_raw              # 原始值
wind_speed_unit_source      # 来源单位
wind_speed_unit_normalized  # 标准化单位
wind_speed_ms               # m/s 值
wind_speed_unit_conversion_applied  # 是否转换
```

当前 AMDAR 统计需重新确认：
```text
median = 57
p90 = 101
max = 254
```

2026-07-01 补充确认：
```text
AMDAR 风速单位 = m/s
wind_speed_ms = wind_speed_raw
wind_speed_unit_conversion_applied = false
```

因此 `wind_speed > 150 m/s` 的记录不再解释为 knots/m/s 单位歧义，而应进入气象质量异常复核。

2. **气象质量检查**：
```python
# 输出统计
met_value_quality_counts
wind_speed_outlier_count
wind_direction_invalid_count
uv_nonfinite_count
temperature_outlier_count
altitude_outlier_count
duplicate_met_record_count
```

3. **时间字段审计**：
```python
observation_time_utc_null_count
observation_time_source_counts
observation_time_uncertainty_summary
```

4. **字段不变量检查**：
```python
# effective_strict_truth=true 必须同时满足
assert strict_time_truth == True
assert time_is_point_observation == True
assert point_observation_time_available == True
assert met_value_quality == 'passed'
```

**输出**：
```text
stage1_met_qc_rows.parquet
stage1_met_qc_summary.json
stage1_semantics_invariant_check.json
```

**完成标准**：
- 所有单位明确
- 所有严格真值行满足字段不变量
- 无遗漏的质量问题

**预计工时**：6-8 小时

---

### 阶段 2：ADS-B QC 和航段分级审计（高优先级）

**来源**：Plan5 P4

**目标**：查明 A 级 leg 只有 45 条的真实原因

**操作**：

1. **失败原因详细统计**：
```python
# 为每个 leg 保存失败原因
failed_time_order
failed_speed
failed_position_jump
failed_sampling_gap
failed_altitude
failed_identity
failed_duration
failed_point_count
failed_phase_consistency

# 分别统计每项条件单独剔除多少航段
```

2. **重点排查**：
```python
checklist = [
    "是否按 time_utc 排序后计算相邻速度",
    "是否跨长时间缺口计算速度",
    "是否跨航班或跨日期连接",
    "是否使用 haversine/测地距离",
    "速度单位是否统一为 m/s",
    "同一航班号重复执行是否被合并",
    "午夜航班是否被错误切断"
]
```

3. **航段质量组件化**：
```python
# 不再只用 A/B/C 一个总标签
leg_time_quality          # 时间序列质量
leg_geometry_quality      # 几何轨迹质量
leg_identity_quality      # 身份一致性
leg_sampling_quality      # 采样密度质量
leg_overall_quality       # 综合等级
```

**输出**：
```text
adsb_qc_v3_rows.parquet
adsb_leg_failure_reason_summary.json
adsb_leg_quality_components.parquet
```

**完成标准**：
- 可以明确解释每一条 C 级 leg 为什么被降级
- A/B 级 leg 数量合理（预期应比 45 条多）

**预计工时**：8-10 小时

---

### 阶段 3：Pseudo-AMDAR 闭环独立重写（高优先级）

**来源**：Plan5 P5

**目标**：在不依赖真实 AMDAR 匹配的情况下验证时间重建算法

**数据构造**：

1. **从 ADS-B 连续片段抽取**：
```python
# 飞行阶段
phases = ['ASC', 'DES', 'LVR']

# 批次大小
batch_sizes = [1, 2-4, 5-10, 11-25, 26-50]

# 模拟因素
simulation_factors = [
    "30-180 秒采样间隔",
    "5-60 分钟批次跨度",
    "不同下传延迟",
    "位置噪声",
    "高度偏差",
    "ADS-B 缺测",
    "身份字段缺失",
    "候选航段歧义",
    "部分异常点"
]
```

2. **数据划分**（关键）：
```python
# 必须按 tail_number + date 进行分组划分
# 同一飞机同一天不能跨集合

calibration_set    # 用于调整阈值
validation_set     # 用于中间验证
locked_test_set    # 最终锁定测试集，不可调参
```

3. **评估指标**：
```python
metrics = {
    'correct_leg_rate': '正确航段率',
    'wrong_leg_rate': '错误航段率',
    'reject_rate': '拒绝率',
    'time_error_q50': '时间误差中位数',
    'time_error_q90': '时间误差 90 分位',
    'time_error_q99': '时间误差 99 分位',
    'catastrophic_error_rate': '灾难性错误率（>30min）',
    'coverage_error_curve': '覆盖率-误差曲线'
}
```

**输出**：
```text
pseudo_amdar_train.parquet
pseudo_amdar_validation.parquet
pseudo_amdar_locked_test.parquet
pseudo_amdar_calibration_report.json
```

**完成标准**：
- locked test 上能够得到稳定的时间误差和错误航段率
- 时间误差 q90 < 5 分钟的覆盖率 > 30%
- 灾难性错误率 < 5%

**预计工时**：10-12 小时

---

### 阶段 4：置信度数据模型重构（中优先级）

**来源**：Plan5 P3 + Plan4 置信度计算

**目标**：停止使用单一常数 obs_conf=0.35 表示全部 AMDAR

**新增字段**：
```python
confidence_components = {
    'source_conf': '数据源基准置信度',
    'met_conf': '气象质量置信度',
    'time_source_conf': '时间来源置信度',
    'sequence_conf': '批次顺序置信度',
    'identity_conf': '航班身份置信度',
    'adsb_leg_conf': 'ADS-B 航段质量',
    'adsb_match_conf': 'ADS-B 匹配质量',
    'spatial_match_conf': '空间匹配质量',
    'representativeness_conf': '空间代表性',
    'density_conf': '密度权重因子',
    'base_support_conf': '最终支持置信度'
}

preserved_fields = {
    'truth_eligible': '真值候选资格',
    'effective_strict_truth': '有效严格真值标志'
}
```

**硬拒绝检查**（在置信度计算前）：
```python
hard_rejects = [
    '非有限风值',
    '明显错误坐标',
    '身份冲突',
    '不可能时间',
    '严重航迹跳跃',
    '灾难性匹配歧义'
]
```

**置信度计算**（通过硬拒绝后）：
```python
base_support_conf = weighted_geometric_mean(
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

**重要约束**：
- 禁止通过 base_support_conf 推导 strict truth
- strict truth 只能由原始数据语义决定

**输出**：
```text
amdar_confidence_components.parquet
amdar_confidence_policy_v1.json
```

**完成标准**：
- 任何总置信度都能追溯到具体组成项
- 不再只有固定 0.35

**预计工时**：6-8 小时

---


### 阶段 5：AMDAR-ADS-B 匹配 V3（中优先级）

**来源**：Plan5 P6

**目标**：在修复 ADS-B QC 后重新进行真实匹配

**候选筛选**：

1. **身份匹配优先级**：
```python
identity_priority = [
    '机尾号 + 航班号精确匹配',          # strong
    '机尾号 + 归一化航班号匹配',        # strong
    '机尾号一致、航班号缺失',          # medium
    '航班号一致、机尾号缺失',          # weak
    '身份冲突' -> '拒绝'
]
```

2. **时间条件**：
```python
time_condition = (
    adsb_time <= batch_end_time + clock_tolerance
)
```

3. **空间条件**：
```python
spatial_conditions = [
    '航迹包络重叠',
    '高度范围重叠',
    '飞行阶段兼容'
]
```

**单调匹配约束**：
```python
monotonic_constraints = [
    '一个 AMDAR 批次最多对应一条 ADS-B leg',
    'AMDAR 原始顺序不变',
    '沿轨位置单调非递减',
    '估计时间单调非递减',
    '不跨长 ADS-B 缺口插值'
]
```

**保存完整匹配信息**：
```python
match_info = {
    'best_candidate_cost': '最佳候选代价',
    'second_candidate_cost': '第二候选代价',
    'ambiguity_margin': '歧义度',
    'cross_track_distance': '横向距离',
    'vertical_difference': '垂直差',
    'sampling_gap': '采样间隔',
    'interpolation_flag': '插值/外推标志'
}
```

**输出**：
```text
amdar_adsb_match_v3.parquet
amdar_adsb_reject_v3.parquet
amdar_adsb_match_diagnostics_v3.json
```

**完成标准**：
- 任何接受结果都可以完整追溯到对应 ADS-B 前后点
- 匹配成功率 > 30%（基于 pseudo-AMDAR 验证）

**预计工时**：8-10 小时

---

### 阶段 6：时间不确定性建模（中优先级）

**来源**：Plan5 P7

**目标**：让 Stage2 能够根据目标雷达帧动态计算时间相关性

**每条 AMDAR 保存时间分布**：
```python
time_distribution = {
    'estimated_time_q10': '时间分布 10 分位',
    'estimated_time_q50': '时间分布中位数（最可能时间）',
    'estimated_time_q90': '时间分布 90 分位',
    'time_interval_start': '时间区间起点',
    'time_interval_end': '时间区间终点',
    'time_pdf_type': '时间概率分布类型（gaussian/uniform/triangular）',
    'time_uncertainty_s': '时间不确定性（秒）',
    'time_reconstruction_grade': '时间重建等级（A/B/C/batch）'
}
```

**对未匹配批次的时间估计**：
```python
def estimate_batch_time_distribution(batch):
    """对未 ADS-B 重建的批次估计时间分布"""
    
    # 使用信息
    previous_batch_end = batch.previous_batch_end_time
    current_batch_end = batch.current_batch_end_time
    original_order = batch.amdar_observation_order
    along_track_distance = batch.along_track_cumulative_distance
    phase = batch.flight_phase
    
    # 飞行阶段速度先验
    if phase == 'ASC':
        typical_speed = 150  # m/s
    elif phase == 'LVR':
        typical_speed = 230  # m/s
    elif phase == 'DES':
        typical_speed = 180  # m/s
    else:
        typical_speed = 200  # m/s
    
    # 基于距离和速度估计时间跨度
    estimated_duration = along_track_distance[-1] / typical_speed
    
    # 构造宽时间区间
    time_interval_start = current_batch_end - estimated_duration - 300
    time_interval_end = current_batch_end
    
    # 为批次内每个点分配时间（假设沿轨距离与时间成正比）
    for i, point in enumerate(batch.points):
        progress = along_track_distance[i] / along_track_distance[-1]
        
        # 三角分布（更可能在后半段）
        estimated_time = (time_interval_start + 
                          estimated_duration * (0.3 + 0.7 * progress))
        
        point.estimated_time_q50 = estimated_time
        point.estimated_time_q10 = estimated_time - estimated_duration * 0.3
        point.estimated_time_q90 = estimated_time + estimated_duration * 0.2
        point.time_interval_start = time_interval_start
        point.time_interval_end = time_interval_end
        point.time_pdf_type = 'triangular'
        point.time_uncertainty_s = estimated_duration
        point.time_reconstruction_grade = 'C'
    
    return batch
```

**输出**：
```text
amdar_time_uncertainty_v1.parquet
time_uncertainty_policy_v1.json
```

**完成标准**：
- 所有非拒绝 AMDAR 至少拥有时间区间
- 只有高质量 ADS-B 重建结果拥有窄时间分布（< 5 分钟）

**预计工时**：6-8 小时

---

### 阶段 7：S/A/B/C/R 等级标定（中优先级）

**来源**：Plan5 P8 + Plan4 分层体系

**目标**：基于 pseudo-AMDAR locked test 确定分级阈值

**阈值标定流程**：

1. **在 pseudo-AMDAR validation set 上调整阈值**：
```python
# A/B 边界：时间误差 q90
threshold_A_B = optimize_on_validation_set(
    target_metric='time_error_q90',
    A_level_target=180,  # 3 分钟
    coverage_constraint=0.15  # 至少覆盖 15%
)

# B/C 边界：时间误差 q90
threshold_B_C = optimize_on_validation_set(
    target_metric='time_error_q90',
    B_level_target=600,  # 10 分钟
    coverage_constraint=0.30  # 至少覆盖 30%
)

# C/R 边界：灾难性错误率
threshold_C_R = optimize_on_validation_set(
    target_metric='catastrophic_error_rate',
    max_allowed=0.05  # < 5%
)
```

2. **在 pseudo-AMDAR locked test 上验证**：
```python
locked_test_results = evaluate_on_locked_test(
    thresholds={'A_B': threshold_A_B, 'B_C': threshold_B_C, 'C_R': threshold_C_R}
)

for grade in ['A', 'B', 'C']:
    print(f"{grade} 级覆盖率: {locked_test_results[grade]['coverage']}")
    print(f"{grade} 级时间误差 q90: {locked_test_results[grade]['time_error_q90']}")
```

**重要原则**：
- 阈值由 pseudo-AMDAR locked test 标定，不是根据覆盖率人工放宽
- 宁可拒绝更多数据，也不降低质量标准

**输出**：
```text
amdar_quality_thresholds_v2.json
amdar_quality_grade_summary.json
amdar_graded_distribution.json
```

**完成标准**：
- A 级时间误差 q90 < 5 分钟
- B 级时间误差 q90 < 10 分钟
- C 级灾难性错误率 < 5%

**预计工时**：6-8 小时

---

### 阶段 8：Stage1 增强输出（核心执行）

**来源**：Plan4 P0

**目标**：在现有 Stage1 输出基础上，为每条 AMDAR 添加置信度和时间不确定性字段

**输入**：
```text
stage1_output_plan4_v1/clean_wind.parquet
stage1_output_plan4_v1/amdar_batch_statistics.parquet
adsb_qc_v3_rows.parquet (来自阶段 2)
amdar_adsb_match_v3.parquet (来自阶段 5)
amdar_time_uncertainty_v1.parquet (来自阶段 6)
amdar_quality_thresholds_v2.json (来自阶段 7)
```

**操作步骤**：

1. 读取批次统计，计算每个批次的置信度、时间不确定性、层级
2. 将批次级属性 join 回逐点数据
3. 应用 ADS-B 重建结果（如果有）
4. 对单点进行气象一致性检查（与邻近 location 对比）
5. 应用标定好的等级阈值
6. 生成新字段并保留原有所有字段

**新增字段清单**：
```python
new_fields = {
    # 置信度相关
    'obs_conf_v2': '基于批次特征和 ADS-B 重建的置信度（0.05-1.0）',
    'source_conf': '数据源基准置信度',
    'met_conf': '气象质量置信度',
    'batch_conf': '批次特征置信度',
    'time_source_conf': '时间来源置信度',
    'spatial_representativeness': '空间代表性因子',
    'batch_met_consistency': '批次内气象一致性',
    
    # 分级相关
    'confidence_tier': 'T0/T1/T2/T3/T4',
    'confidence_grade': 'S/A/B/C/R',
    
    # 时间不确定性相关
    'time_uncertainty_s': '时间不确定性（秒）',
    'time_source': 'original/adsb_reconstructed/batch_estimated',
    'estimated_time_q10': '估计时间 10 分位',
    'estimated_time_q50': '估计时间中位数',
    'estimated_time_q90': '估计时间 90 分位',
    'time_interval_start': '时间区间起点',
    'time_interval_end': '时间区间终点',
    'time_pdf_type': '时间概率分布类型',
    'time_reconstruction_grade': '时间重建等级',
    
    # ADS-B 匹配相关（如果适用）
    'adsb_reconstructed': '是否 ADS-B 重建',
    'adsb_leg_quality': 'ADS-B 航段质量（A/B/C）',
    'adsb_match_quality': 'ADS-B 匹配质量',
    'adsb_match_ambiguity': '匹配歧义度',
    'adsb_cross_track_dist': '横向距离',
    'adsb_vertical_diff': '垂直差'
}
```

**输出**：
```text
stage1_output_unified_v1/clean_wind_with_confidence.parquet
stage1_output_unified_v1/confidence_tier_summary.json
stage1_output_unified_v1/confidence_distribution_by_phase.json
stage1_output_unified_v1/time_uncertainty_summary.json
stage1_output_unified_v1/adsb_reconstruction_summary.json
stage1_output_unified_v1/grade_transition_matrix.json
```

**验证检查**：
```python
validation_checks = [
    '所有 AMDAR 行都有 obs_conf_v2, confidence_tier, confidence_grade',
    '置信度分布合理（不全是极端值）',
    '层级分布：T1 < T2 < T3，T4 最少',
    'TURB 仍保持 obs_conf=1.0, holdout_eligible=true',
    '字段向后兼容：原有字段保持不变',
    '所有非拒绝 AMDAR 都有时间不确定性信息',
    'ADS-B 重建成功的有更小的 time_uncertainty_s'
]
```

**完成标准**：
- Stage1 输出包含完整置信度信息
- 可以追溯每个置信度值的计算依据
- 向后兼容现有 Stage2/Stage4

**预计工时**：6-8 小时

---

### 阶段 9：Stage2 角色分流改造（核心执行）

**来源**：Plan5 P9

**目标**：同时保留严格真值和带不确定性的支持观测

**Stage2 输出通道**：
```python
output_channels = {
    'strict_truth_records': 'T0/S 级，仅用于 holdout',
    'current_support_records': 'T1/T2 级，当前时间窗支持（基于时间分布重叠）',
    'context_support_records': 'T1/T2/T3 级，历史上下文支持',
    'batch_support_records': 'T3/C 级，批次级或粗时间窗支持',
    'diagnostic_only_records': 'T4-D 级，仅诊断和展示',
    'rejected_records': 'T4-R 级，完全拒绝'
}
```

**关键修改**：

1. **禁止操作清单**：
```python
forbidden = [
    '原始 AMDAR batch_end_time 直接作为 point time',
    '所有 AMDAR 直接进入 T±5min current window',
    '在 holdout 前先把同体素观测平均',
    '混淆 support 和 truth 角色',
    '为了提高覆盖率放宽 strict truth 标准'
]
```

2. **时间置信度动态计算**：
```python
def calculate_frame_time_conf(observation, target_frame_time):
    """计算观测对目标帧的时间置信度"""
    
    frame_window_start = target_frame_time - 300  # -5 min
    frame_window_end = target_frame_time + 300    # +5 min
    
    obs_time_start = observation.time_interval_start
    obs_time_end = observation.time_interval_end
    obs_time_best = observation.estimated_time_q50
    obs_pdf_type = observation.time_pdf_type
    
    # 计算时间分布与目标窗口的重叠概率
    if obs_pdf_type == 'gaussian':
        sigma = observation.time_uncertainty_s / 2.0
        overlap_prob = gaussian_overlap(
            obs_time_best, sigma,
            frame_window_start, frame_window_end
        )
    elif obs_pdf_type == 'uniform':
        overlap_prob = uniform_overlap(
            obs_time_start, obs_time_end,
            frame_window_start, frame_window_end
        )
    elif obs_pdf_type == 'triangular':
        overlap_prob = triangular_overlap(
            obs_time_start, obs_time_best, obs_time_end,
            frame_window_start, frame_window_end
        )
    else:
        # 点时间
        if frame_window_start <= obs_time_best <= frame_window_end:
            overlap_prob = 1.0
        else:
            time_distance = min(
                abs(obs_time_best - frame_window_start),
                abs(obs_time_best - frame_window_end)
            )
            overlap_prob = 0.5 ** (time_distance / 180)  # 3分钟半衰期
    
    # 最终时间置信度 = 观测置信度 × 时间重叠概率
    frame_time_conf = observation.obs_conf_v2 * overlap_prob
    
    return frame_time_conf
```

3. **观测记录保留**：
```python
observation_record = {
    'observation_id': '唯一观测 ID',
    'flight_id': '航班 ID',
    'batch_id': 'AMDAR 批次 ID（如果适用）',
    'source': '数据源',
    'time_grade': 'S/A/B/C',
    'confidence_tier': 'T0-T4',
    'u_wind': 'u 分量',
    'v_wind': 'v 分量',
    'obs_conf_v2': '观测置信度',
    'time_uncertainty_s': '时间不确定性',
    'frame_time_conf': '对目标帧的时间置信度',
    'spatial_representativeness': '空间代表性',
    'voxel_indices': '体素索引 (i, j, k)',
    'role': '角色标签'
}
```

**输出**：
```text
stage2_observation_records/frame_{:06d}.parquet
stage2_voxel_support_summary/frame_{:06d}.parquet
stage2_role_audit.json
stage2_time_conf_distribution.json
stage2_channel_statistics.json
```

**完成标准**：
- holdout 观测可以在任何聚合前被完整移除
- 角色分离清晰，无混淆
- 时间置信度合理反映时间不确定性
- 向后兼容：可生成与旧版本相同格式的输出

**预计工时**：10-12 小时

---

### 阶段 10：Super-ob 和密度权重控制（中优先级）

**来源**：Plan5 P10

**目标**：防止一架飞机、一个批次或一个航段因点数过多支配风场

**分组维度**：
```python
grouping_dimensions = [
    'flight_id',
    'amdar_batch_id',
    'time_bin',  # 例如 5 分钟
    'altitude_bin',  # 例如 500m
    'along_track_distance_bin',  # 例如 10km
    'spatial_voxel'
]
```

**Super-ob 生成**：
```python
def create_super_ob(group):
    """为一组观测创建 super-ob"""
    
    # 加权平均（使用置信度作为权重）
    total_weight = np.sum(group['obs_conf_v2'])
    weighted_u = np.sum(group['u_wind'] * group['obs_conf_v2']) / total_weight
    weighted_v = np.sum(group['v_wind'] * group['obs_conf_v2']) / total_weight
    
    # 组内离散度
    u_spread = np.std(group['u_wind'])
    v_spread = np.std(group['v_wind'])
    within_group_spread = np.sqrt(u_spread**2 + v_spread**2)
    
    # 有效样本量（考虑相关性）
    raw_count = len(group)
    effective_sample_size = min(raw_count, total_weight / 0.35)  # 防止过度加权
    
    # Super-ob 记录
    super_ob = {
        'weighted_u': weighted_u,
        'weighted_v': weighted_v,
        'within_group_spread': within_group_spread,
        'raw_point_count': raw_count,
        'effective_sample_size': effective_sample_size,
        'unique_flight_count': group['flight_id'].nunique(),
        'time_uncertainty_mean': group['time_uncertainty_s'].mean(),
        'confidence_tier_mode': group['confidence_tier'].mode()[0],
        'quality_grade_mode': group['confidence_grade'].mode()[0],
        'super_ob_conf': min(total_weight / raw_count, 0.85)  # 归一化
    }
    
    return super_ob
```

**权重上限控制**：
```python
weight_limits = {
    'max_weight_per_batch_per_frame': 5.0,  # 单个批次最多等效 5 个独立观测
    'max_weight_per_flight_per_voxel': 3.0,  # 单架飞机单体素最多等效 3 个观测
    'max_weight_per_source_per_frame': 50.0,  # 单个数据源单帧最多等效 50 个观测
    'max_total_weight_ratio': 0.30  # 任何单组不能超过总权重的 30%
}

def apply_weight_limits(observations):
    """应用权重上限"""
    
    # 按批次限制
    for batch_id in observations['amdar_batch_id'].unique():
        batch_mask = observations['amdar_batch_id'] == batch_id
        batch_total_weight = observations.loc[batch_mask, 'obs_conf_v2'].sum()
        
        if batch_total_weight > weight_limits['max_weight_per_batch_per_frame']:
            scale_factor = weight_limits['max_weight_per_batch_per_frame'] / batch_total_weight
            observations.loc[batch_mask, 'obs_conf_v2'] *= scale_factor
            observations.loc[batch_mask, 'weight_limited'] = True
    
    return observations
```

**输出**：
```text
amdar_superobs_T1.parquet  # T1 级 super-ob
amdar_superobs_T1T2.parquet  # T1+T2 级 super-ob
amdar_superobs_T1T2T3.parquet  # T1+T2+T3 级 super-ob
superob_policy_v1.json
weight_limit_audit.json
```

**完成标准**：
- 50 点批次不能自动获得单点批次 50 倍的总权重
- 权重上限合理且可审计
- Super-ob 覆盖率和质量在可接受范围

**预计工时**：8-10 小时

---

### 阶段 11：Stage2 兼容性测试（必须执行）

**来源**：Plan4 P1

**目标**：确认 Stage2 能够正确读取和传递新置信度字段

**操作**：

1. 用 `clean_wind_with_confidence.parquet` 替换 Stage2 输入
2. 跑 Stage2（smoke test：10 帧）
3. 检查 Stage2 输出中是否保留了所有新字段
4. 确认数据没有意外丢失或损坏

**测试检查项**：
```python
compatibility_checks = [
    'Stage2 输出包含所有新字段',
    '字段值与 Stage1 输出一致',
    '无数据丢失',
    '体素分配正确',
    '角色分流正确',
    '时间置信度计算正确',
    '向后兼容：可生成旧格式输出'
]
```

**输出**：
```text
stage2_smoke_confidence_v1/  # 10 帧测试输出
stage2_confidence_compatibility_report.json
stage2_field_preservation_audit.json
```

**完成标准**：
- Stage2 输出包含所有新字段
- 字段值与 Stage1 输出一致
- 无数据丢失

**预计工时**：2-3 小时

---

### 阶段 12：Stage4 Baseline 复现（必须执行）

**来源**：Plan4 P2

**目标**：确认当前最稳方案（tp26_thr11_preserve）在新 Stage1 和2 下仍可复现

**操作**：

1. 使用 `stage1_output_unified_v1` 运行 Stage2 全量（或 200 帧代表集）
2. 运行 Stage3（GFS 背景）
3. 运行 Stage4 tp26_thr11_preserve
4. 对比新旧 baseline 的 holdout RMSE

**对比指标**：
```python
comparison_metrics = {
    'weighted_rmse': 'Holdout 加权 RMSE',
    'weighted_mae': 'Holdout 加权 MAE',
    'frame_rmse': 'Frame 级别 RMSE',
    'frame_p95': 'Frame P95',
    'frame_p99': 'Frame P99',
    '12km_plus_rmse': '12km+ RMSE',
    'light_wind_rmse': '轻风 RMSE',
    'floor10_relative_mae': 'Floor10 相对 MAE'
}
```

**输出**：
```text
stage4_baseline_unified_v1_200frames/
baseline_comparison_report.json
baseline_metrics_diff.json
```

**完成标准**：
- Holdout RMSE 差异 < 1%（应该几乎相同，因为只是添加了字段）
- 确认 TURB 181 条仍然是唯一 holdout truth
- 确认 AMDAR 按新角色分流使用

**预计工时**：4-6 小时（取决于是否全量）

---

### 阶段 13：多时间尺度重构实验（核心验证）

**来源**：Plan5 P11

**目标**：判断 AMDAR 适合的真实时间分辨率，而不是强迫所有数据进入最细时间窗

**时间尺度对比**：
```python
time_scales = {
    'fine': '精细窗口：当前 radar frame window (T±5min)',
    '15min': '15 分钟窗口 (T±7.5min)',
    '30min': '30 分钟窗口 (T±15min)',
    '60min': '60 分钟窗口 (T±30min)'
}
```

**实验设计（消融研究）**：
```python
experiments = {
    'E0': '无 AMDAR（仅 TURB 181 条）',
    'E1': '仅 S 级（TURB）',
    'E2': 'S + A 级（高质量 ADS-B 重建）',
    'E3': 'S + A + B 级',
    'E4': 'S + A + B + C 级（含 super-ob）',
    'E5': 'Legacy 方案（Plan4 原始）',
    'E6': '所有 AMDAR 固定 0.35（旧式）'
}
```

**每个实验 × 每个时间尺度的指标**：
```python
metrics = {
    'holdout_rmse': '严格真值 RMSE',
    'holdout_mae': '严格真值 MAE',
    'holdout_count': '有效真值数量',
    'frame_coverage': 'Frame 覆盖率',
    'spatial_coverage': '空间覆盖率',
    'temporal_continuity': '时间连续性',
    '12km_plus_rmse': '高空误差',
    'sparse_region_rmse': '稀疏区误差',
    'pseudo_gradient_count': '伪梯度数量',
    'max_batch_weight_ratio': '单批次最大权重占比',
    'weight_entropy': '权重分布熵'
}
```

**特别关注**：
```python
quality_checks = [
    '伪梯度检测：相邻体素风场差异 > 20 m/s 且无观测支持',
    '单批次主导：任何批次权重 > 30% 该帧总权重',
    '时空连续性：风场时空梯度合理性',
    '边界效应：批次边界是否产生风场不连续'
]
```

**输出**：
```text
stage4_multiscale_ablation/
  - E0_no_amdar/
  - E1_S_only/
  - E2_S_A/
  - E3_S_A_B/
  - E4_S_A_B_C/
  - E5_legacy/
  - E6_old_fixed/
multiscale_ablation_summary.json
experiment_comparison_matrix.json
optimal_timescale_recommendation.json
pseudo_gradient_audit.json
```

**成功标准**：
- A/B/C 的加入在至少一个合理时间尺度上稳定改善结果
- 不能产生明显伪梯度
- 单批次权重占比 < 30%
- E4 相比 E0 的改善显著且稳定

**预计工时**：16-20 小时

---

### 阶段 14：分层评估体系（核心验证）

**来源**：Plan5 P12

**目标**：避免用 181 条真值给出过度确定的全局结论

**四层评估结果**：

#### Level 1：Conservative Strict（保守严格）

**定义**：
- 只使用 `effective_strict_truth=true` 的观测
- 当前仅 TURB 181 条

**报告内容**：
```python
level1_report = {
    'sample_count': 181,
    'holdout_rmse': '加权 RMSE',
    'holdout_mae': '加权 MAE',
    'confidence_interval_95': 'Bootstrap 95% 置信区间',
    'by_altitude': '按高度分层结果',
    'by_phase': '按飞行阶段分层结果',
    'note': 'Conservative strict truth - only for official validation'
}
```

#### Level 2：Legacy Compatibility（遗留兼容）

**定义**：
- 继续报告旧 6796 条口径（单点批次）
- 必须明确标记为 legacy compatibility

**报告内容**：
```python
level2_report = {
    'sample_count': 6796,
    'note': 'Legacy compatibility metric - NOT conservative strict truth',
    'warning': '包含批次时间不确定性，不能作为严格真值',
    'metrics': '...'
}
```

#### Level 3：Pseudo-AMDAR Time Validation（伪 AMDAR 时间验证）

**定义**：
- 只验证时间重建和航段匹配能力
- 不混淆为风场精度验证

**报告内容**：
```python
level3_report = {
    'validation_type': '时间重建质量验证',
    'locked_test_metrics': {
        'correct_leg_rate': '正确航段率',
        'time_error_q50': '时间误差中位数',
        'time_error_q90': '时间误差 90 分位',
        'catastrophic_rate': '灾难性错误率'
    },
    'note': '此层级验证时间重建质量，不是风场精度'
}
```

#### Level 4：Consistency Diagnostics（一致性诊断）

**定义**：
- 时空连续性、批次权重占比、观测创新、背景差异
- 不能称为真实风场精度

**报告内容**：
```python
level4_report = {
    'diagnostic_type': '内部一致性和合理性检查',
    'temporal_continuity': '时间连续性指标',
    'spatial_smoothness': '空间平滑性指标',
    'batch_weight_distribution': '批次权重分布',
    'observation_innovation': '观测创新统计（与 GFS 背景）',
    'background_departure': '背景偏差统计',
    'note': '这些不是真实风场精度，只是内部一致性诊断'
}
```

**统计方法**：
```python
# 采用按 flight/date 分组的 bootstrap
# 而不是逐行 bootstrap

def grouped_bootstrap(data, n_bootstrap=1000):
    """按航班和日期分组的 bootstrap"""
    
    groups = data.groupby(['flight_id', 'date']).groups
    group_keys = list(groups.keys())
    
    results = []
    for _ in range(n_bootstrap):
        # 重采样组
        sampled_groups = np.random.choice(
            group_keys, 
            size=len(group_keys), 
            replace=True
        )
        
        # 收集该样本的所有观测
        sampled_indices = []
        for group_key in sampled_groups:
            sampled_indices.extend(groups[group_key])
        
        # 计算指标
        sample_data = data.iloc[sampled_indices]
        metric = calculate_rmse(sample_data)
        results.append(metric)
    
    # 返回置信区间
    return {
        'mean': np.mean(results),
        'std': np.std(results),
        'ci_lower': np.percentile(results, 2.5),
        'ci_upper': np.percentile(results, 97.5)
    }
```

**输出**：
```text
stage4_validation_tiered_report.json
stage4_validation_confidence_intervals.json
stage4_level1_conservative_strict.json
stage4_level2_legacy_compatibility.json
stage4_level3_pseudo_amdar_validation.json
stage4_level4_consistency_diagnostics.json
```

**完成标准**：
- 任何 RMSE 都同时报告样本数、来源、时间语义和置信区间
- 不混淆不同层级的验证结果
- 清楚标注哪些是 official validation，哪些是 diagnostic

**预计工时**：8-10 小时

---

### 阶段 15：完整文档更新（必须执行）

**来源**：Plan4 P9

**目标**：更新所有项目文档，反映新的置信度体系

**文档更新清单**：

1. **更新 centralized_v1_ultimate_summary**：
   - 添加置信度体系章节
   - 更新 AMDAR 时间语义说明
   - 添加分层评估说明

2. **更新 Stage1 文档**：
   - 说明新增字段及其含义
   - 说明 AMDAR 批次时间语义
   - 说明 ADS-B 重建流程

3. **创建 confidence_aware_workflow_guide.md**：
   - 如何使用置信度字段
   - 如何选择合适的层级
   - 如何解释分层评估结果

4. **更新 Stage4 文档**：
   - 说明如何使用置信度和时间不确定性
   - 说明权重计算方法
   - 说明分层评估体系

5. **创建 decision_log.md**：
   - 记录为什么采用当前方案
   - 记录关键决策点和理由
   - 记录拒绝的方案及原因

**输出**：
```text
centralized_v1_ultimate_summary_20260701.md  # 更新版
stage1_unified_plan_documentation.md
confidence_aware_workflow_guide.md
stage4_confidence_integration_guide.md
confidence_system_design_rationale.md
decision_log_unified_plan.md
```

**完成标准**：
- 所有文档反映当前方案
- 新用户可以通过文档理解整个体系
- 可以追溯所有关键决策

**预计工时**：6-8 小时

---

## 第四部分：执行顺序和依赖关系

### 立即执行路径（关键路径）

```text
阶段 0：冻结基线并验证确定性 ─────────> 必须最先
    ↓
阶段 1：Stage1 质量审计缺口修复 ─────────> 必须优先
    ↓
阶段 2：ADS-B QC 和航段分级审计 ────────> 高优先级，并行可开始
    ↓
阶段 3：Pseudo-AMDAR 闭环独立重写 ──────> 高优先级，并行可开始
    ↓
    ├──> 阶段 4：置信度数据模型重构 ────> 中优先级
    │    阶段 5：AMDAR-ADS-B 匹配 V3 ──> 中优先级（依赖阶段 2）
    │    阶段 6：时间不确定性建模 ──────> 中优先级（依赖阶段 5）
    │    阶段 7：S/A/B/C/R 等级标定 ───> 中优先级（依赖阶段 3）
    ↓
阶段 8：Stage1 增强输出 ──────────────> 核心执行（依赖阶段 1-7）
    ↓
阶段 11：Stage2 兼容性测试 ────────────> 必须执行（依赖阶段 8）
    ↓
阶段 9：Stage2 角色分流改造 ───────────> 核心执行（依赖阶段 11）
    ↓
阶段 10：Super-ob 和密度权重控制 ─────> 中优先级（依赖阶段 9）
    ↓
阶段 12：Stage4 Baseline 复现 ─────────> 必须执行（依赖阶段 9）
    ↓
阶段 13：多时间尺度重构实验 ───────────> 核心验证（依赖阶段 10, 12）
    ↓
阶段 14：分层评估体系 ────────────────> 核心验证（依赖阶段 13）
    ↓
阶段 15：完整文档更新 ────────────────> 必须执行
```

### 并行执行机会

```text
阶段 2 和阶段 3 可以并行开始
阶段 4, 5, 6, 7 可以部分并行（注意依赖关系）
阶段 11 smoke test 后可以开始阶段 9 的设计
```

### 预计总工时

```text
关键路径工时：96-122 小时
并行优化后：70-90 小时（假设 2-3 人并行）
```

---

## 第五部分：主链迁移门槛和回退机制

### 主链迁移门槛（来自 Plan5 P13）

只有满足以下条件才允许替换旧主链：

```python
migration_checklist = {
    'stage1_parallel_determinism': '阶段 0 通过',
    'wind_speed_unit_confirmed': '阶段 1 风速单位明确',
    'adsb_qc_failure_analyzed': '阶段 2 失败原因明确',
    'pseudo_amdar_locked_test_passed': '阶段 3 locked test 通过',
    'grade_thresholds_calibrated': '阶段 7 阈值标定完成',
    'stage2_role_separation_complete': '阶段 9 角色分流完成',
    'strict_holdout_no_leakage': 'Holdout 验证无泄漏',
    'multiscale_ablation_stable': '阶段 13 消融实验稳定',
    'tiered_evaluation_documented': '阶段 14 分层评估完成'
}
```

### 质量门

```python
quality_gates = {
    'pseudo_amdar_time_error_q90': '< 5 分钟（A 级）',
    'pseudo_amdar_catastrophic_rate': '< 5%',
    'adsb_A_grade_leg_count': '> 500 条',
    'stage4_baseline_rmse_diff': '< 1%（向后兼容）',
    'multiscale_E4_vs_E0_improvement': '显著且稳定',
    'pseudo_gradient_count': '可接受范围',
    'max_batch_weight_ratio': '< 30%'
}
```

### 回退机制

主链迁移后仍保留：

```text
1. Legacy branch（Plan4 原始方案）
2. Conservative branch（仅使用高质量重建）
3. Minimal branch（仅 TURB，无 AMDAR）
```

保留周期：至少一个版本周期（3-6 个月），以便回归比较

---

## 第六部分：当前禁止操作清单

为确保方案正确实施，以下操作在任何阶段都严格禁止：

```python
forbidden_operations = [
    # 真值边界
    '把全部 AMDAR 改成 strict truth',
    '把固定 0.35 直接提高到 0.8 或 1.0',
    '通过 base_support_conf 推导 strict truth',
    '为了提高覆盖率放宽 strict truth 标准',
    
    # 时间语义
    '按 batch_end_time 把整批点放进同一精细帧',
    '忽略时间不确定性，直接当点时间处理',
    '不建模时间分布就直接进入 T±5min window',
    
    # 匹配质量
    '放宽到不可解释的匹配条件',
    '忽略匹配歧义度',
    '跨长 ADS-B 缺口外推',
    '接受身份冲突的匹配',
    
    # 权重控制
    '允许单批次无限制权重累加',
    '在 holdout 前先聚合同体素观测',
    '不控制密度权重',
    
    # 评估混淆
    '用 legacy 6796 条指标冒充 conservative strict 结果',
    '把内部一致性诊断当作真实精度',
    '混淆不同层级的验证结果',
    '不报告置信区间和样本数',
    
    # 角色混淆
    '混淆 support 和 truth 角色',
    'AMDAR 同时进入 train 和 holdout',
    '用 display-only 数据计算 official RMSE'
]
```

---

## 第七部分：成功标准总结

### 技术成功标准

1. **数据质量**：
   - Pseudo-AMDAR locked test 时间误差 q90 < 5 分钟（A 级）
   - 灾难性错误率 < 5%
   - ADS-B A/B 级 leg 数量合理（> 500 条）

2. **系统稳定性**：
   - Stage4 baseline 复现误差 < 1%
   - 多时间尺度实验结果稳定
   - 无明显伪梯度

3. **可审计性**：
   - 所有置信度可追溯到组成项
   - 所有分级决策有明确依据
   - 并行处理结果确定性

4. **向后兼容性**：
   - 可生成与旧版本相同格式的输出
   - 保留 legacy branch 可运行

### 科学成功标准

1. **改善验证**：
   - E4 (S+A+B+C) 相比 E0 (无 AMDAR) 有显著改善
   - 改善在统计上显著（Bootstrap 置信区间不重叠）
   - 改善在多个时间尺度上稳定

2. **不破坏现有优势**：
   - Light wind RMSE 不恶化
   - Floor10 relative MAE 不恶化
   - 无新的 tail failure

3. **分层合理性**：
   - T1/T2/T3 层级分布合理
   - 各层级对风场重构的贡献可量化
   - 层级间性能差异明显

### 工程成功标准

1. **完整性**：
   - 所有 15 个阶段完成
   - 所有输出文件生成
   - 所有文档更新

2. **可复现性**：
   - 冻结基线可完整追溯
   - 所有随机过程有固定种子
   - 环境完整记录

3. **可维护性**：
   - 代码结构清晰
   - 文档完整
   - Decision log 记录完整

---

## 第八部分：风险与缓解

### 主要风险

1. **ADS-B 重建覆盖率不足**：
   - **风险**：A/B 级重建覆盖率 < 20%
   - **缓解**：阶段 2 审计可以提前发现，阶段 3 pseudo-AMDAR 可以量化
   - **回退**：使用批次特征分级，不依赖 ADS-B 重建

2. **置信度公式设计不当**：
   - **风险**：置信度分布极端（全高或全低）
   - **缓解**：阶段 7 标定可以调整，阶段 13 消融实验可以验证
   - **回退**：调整权重公式或层级阈值

3. **Stage4 baseline 无法复现**：
   - **风险**：新 Stage1 导致 baseline 性能下降
   - **缓解**：阶段 12 提前发现，可以排查原因
   - **回退**：回到 Plan4 基线

4. **多时间尺度实验无显著改善**：
   - **风险**：E4 相比 E0 无统计显著差异
   - **缓解**：阶段 10 super-ob 可以优化，阶段 14 分层评估可以细化
   - **调整**：降低预期，作为"完整性"而非"精度"贡献

5. **工时超预算**：
   - **风险**：总工时超过 120 小时
   - **缓解**：并行执行，分阶段交付
   - **调整**：优先完成关键路径，次要阶段延后

---

## 第九部分：交付物清单

### 代码交付物

```text
stage/stage1_prepare_unified_v1.py
stage/adsb_qc_v3.py
stage/pseudo_amdar_generator.py
stage/amdar_adsb_match_v3.py
stage/confidence_calculator.py
stage/time_uncertainty_modeler.py
stage/centralized_stage2_multimodal_unified_v1.py
stage/superob_generator.py
stage/centralized_stage4_confidence_aware.py
```

### 数据交付物

```text
stage1_output_unified_v1/
adsb_qc_v3_rows.parquet
pseudo_amdar_locked_test.parquet
amdar_confidence_components.parquet
amdar_time_uncertainty_v1.parquet
amdar_quality_thresholds_v2.json
stage2_observation_records/
stage4_multiscale_ablation/
```

### 报告交付物

```text
stage1_parallel_determinism_report.json
stage1_met_qc_summary.json
adsb_leg_failure_reason_summary.json
pseudo_amdar_calibration_report.json
confidence_tier_summary.json
multiscale_ablation_summary.json
stage4_validation_tiered_report.json
```

### 文档交付物

```text
centralized_v1_ultimate_summary_20260701.md
confidence_aware_workflow_guide.md
stage4_confidence_integration_guide.md
confidence_system_design_rationale.md
decision_log_unified_plan.md
```

---

## 第十部分：给下一个智能体的执行指南

### 如何使用本方案

1. **先读懂整体架构**：
   - 第一部分：数据分级体系（T0-T4，S/A/B/C/R）
   - 第二部分：置信度计算方法
   - 理解为什么不降低 strict truth 标准

2. **按顺序执行阶段**：
   - 必须从阶段 0 开始，不能跳过
   - 注意依赖关系，前置阶段未完成不能开始后续
   - 每个阶段完成后检查"完成标准"

3. **使用提供的代码框架**：
   - 第二部分提供了完整的置信度计算公式
   - 可以直接使用或根据实际调整
   - 关键是保持可追溯性

4. **验证每个阶段输出**：
   - 每个阶段都有明确的输出文件
   - 每个阶段都有验证检查项
   - 不通过不进入下一阶段

5. **记录所有决策**：
   - 为什么选择某个阈值
   - 为什么调整某个公式
   - 为什么拒绝某个方案
   - 写入 decision_log.md

### 关键注意事项

1. **时间语义是核心**：
   - AMDAR 批次时间 ≠ 逐点观测时间
   - 必须建模时间不确定性
   - 不能把批次时间直接当点时间

2. **真值边界不能破坏**：
   - 只有 TURB 181 条是 conservative strict truth
   - AMDAR 即使高质量重建也不能自动成为 strict truth
   - Holdout 验证只用 T0/S 级

3. **置信度必须可解释**：
   - 每个置信度值都能追溯到组成项
   - 不能出现"黑盒置信度"
   - 文档必须说明计算依据

4. **向后兼容性优先**：
   - 保留所有原有字段
   - 可以生成旧格式输出
   - 保留 legacy branch

5. **质量门不能放松**：
   - Pseudo-AMDAR locked test 标准不能降低
   - Stage4 baseline 复现误差不能 > 1%
   - 不能为了覆盖率牺牲质量

### 遇到问题怎么办

1. **阶段 2 发现 A 级 leg 仍然很少**：
   - 仔细审计失败原因
   - 检查是否有代码 bug
   - 如果确实是数据质量问题，接受现实，依赖批次特征分级

2. **阶段 3 pseudo-AMDAR 误差过大**：
   - 调整匹配算法
   - 放宽时间窗口但保持几何约束
   - 如果无法改善，降低 A/B 级阈值或增加 C 级覆盖

3. **阶段 12 baseline 复现失败**：
   - 首先排查是否引入了 bug
   - 检查字段映射是否正确
   - 如果确实是新字段影响，分析原因并决定是否回退

4. **阶段 13 实验无改善**：
   - 检查是否正确应用了置信度权重
   - 检查是否有伪梯度
   - 分析各层级的实际贡献
   - 如果确实无改善，诚实报告，作为"完整性"贡献

### 成功的标志

当你完成所有阶段后，应该能够：

1. 明确回答："AMDAR 的 431,008 条数据中，有多少是 strict truth？"（答案：0 条）
2. 明确回答："那为什么还要用 AMDAR？"（答案：作为不同置信度的支持数据，通过分层权重参与重构）
3. 提供完整的置信度追溯链
4. 提供分层评估报告
5. 证明新方案不破坏旧方案的性能

---

## 结语

本方案融合了 Plan4 的分层置信度体系和 Plan5 的质量审计流程，提供了一个完整、可执行、可审计的 AMDAR 数据处理解决方案。

**核心思想**：不降低 strict truth 标准，通过置信度体系充分利用数据。

**执行原则**：质量优先、可审计性优先、向后兼容性优先。

**成功标准**：技术标准 + 科学标准 + 工程标准全部满足。

祝执行顺利！

---

**文档版本**：Unified Plan v1.0  
**生成日期**：2026-07-01  
**作者**：AI Assistant  
**审阅状态**：待人工审阅
