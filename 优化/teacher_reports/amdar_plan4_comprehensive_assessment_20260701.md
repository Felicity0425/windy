# AMDAR Plan4 综合评估与下一步完整计划 (2026-07-01)

## 执行摘要

基于对项目全貌、Stage1问题、Plan4执行结果的深入分析，本报告提供：

1. **当前状态评估**：Plan4的Stage1修正是正确的，但ADS-B时间重建质量不足以进入主链
2. **核心问题诊断**：真值候选过少（6615/431008 = 1.53%）不是筛选条件过严，而是AMDAR数据本质特征
3. **数据利用策略**：应该通过**分层置信度体系**充分利用数据，而非降低质量门槛
4. **下一步完整计划**：包含P0-P15的15个阶段，涵盖数据利用、时间重建、风场应用的完整路径

---

## 1. 项目背景理解

### 1.1 项目整体架构

**centralized_v1** 是一个aircraft-holdout三维风场重构项目：

- **Stage1**: 数据清洗与角色分类（location, AMDAR, TURB）
- **Stage2**: 按帧组织观测数据
- **Stage3**: 雷达背景准备
- **Stage4**: 风场重构主算法（当前最稳：tp26_thr11_preserve）
- **Stage5**: 可选的残差修正（gate-only，增益有限）

**核心价值**：严格的aircraft holdout validation framework，确保评估的独立性和可审计性。

### 1.2 AMDAR数据的本质问题

根据数据提供方反馈和审计结果：

1. **时间语义**：`时间（北京时）` 是**批次下发/接收时间**，不是逐点观测时间
2. **批次特征**：飞机在不同飞行阶段累计下发一批数据（例如爬升30分钟一次，一次下发n个点）
3. **空间分散**：同一批次内的点在空间上可以跨越数公里甚至数十公里、数千米高度
4. **规模巨大**：431008条AMDAR中，424393条（98.47%）属于重复时间批次
5. **风速单位**：2026-07-01 用户补充确认 `AMDAR` 风速单位为 `m/s`；因此高风速记录（例如 `wind_speed > 150 m/s`）应作为气象质量/QC异常复核，而不是解释为 knots/m/s 单位歧义

这不是"脏数据"，而是AMDAR业务数据的**本质特征**。

### 1.3 Plan4的正确定位

Plan4做了两件事：

1. **Stage1语义修正**（✅ 已正确完成）：
   - 明确标注AMDAR时间为 `ground_receive_approx_downlink_batch_end_time`
   - 设置 `strict_time_truth=false`, `point_observation_time_available=false`
   - 保留 `wind_reconstruction_role` 兼容现有Stage2/Stage4
   - 新增保守字段 `effective_strict_truth` 供未来使用

2. **ADS-B时间重建研究**（⚠️ 尚未达标）：
   - 尝试用ADS-B轨迹为AMDAR批次重建逐点时间
   - 目前匹配成功率极低（全量：0/18855候选，smoke：0/587候选）
   - 主要拒绝原因：时间窗口失配（geometry_failed占最多）

---

## 2. 当前执行结果详细分析

### 2.1 Stage1 Plan4 输出统计

**基础统计**：
- AMDAR总行数：431,008
- TURB总行数：181
- location总行数：19,162,638

**AMDAR时间角色分类**：
- `strict_time_truth=false`：431,008（100%）
- `effective_strict_truth=false`：431,008（100%）
- `point_observation_time_available=false`：431,008（100%）

**AMDAR风场重构角色**（兼容字段）：
- `support_only_not_strict_truth`：424,393（98.47%）
- `strict_truth_candidate`：6,615（1.53%）

**TURB风场重构角色**：
- `strict_truth_candidate`：181（100%）

**关键洞察**：
- Plan4正确地将所有AMDAR标记为"无逐点时间"
- 但保留了 `wind_reconstruction_role` 兼容字段，使得Stage2/Stage4仍能按原方式运行
- 6615个"候选"实际上是**单点时间戳批次**，但它们仍然没有真实观测时间保证

### 2.2 AMDAR批次特征分析

**批次总数**：56,521批次（覆盖431,008点）

**批次大小分布**：
- 单点批次 (=1)：6,683批次，6,683点（11.83%批次，1.55%点）
- 小批次 (2-4)：19,627批次，57,266点（34.72%批次，13.29%点）
- 中批次 (5-10)：24,301批次，174,731点（43.00%批次，40.54%点）
- 大批次 (11-25)：1,796批次，30,896点（3.18%批次，7.17%点）
- 超大批次 (26-49)：3,722批次，141,832点（6.59%批次，32.90%点）
- 最大批次 (50)：392批次，19,600点（0.69%批次，4.55%点）

**批次空间特征**：
- 水平跨度中位数：1.16度（约130公里）
- 水平跨度90分位：>3度（约330公里）
- 高度跨度中位数：238米
- 高度跨度90分位：>2000米
- 最大水平跨度：10.5度（约1150公里）
- 最大高度跨度：7824米

**关键发现**：
1. **批次主体是5-10点的中等批次**（43%批次数，40.5%点数）
2. **空间跨度巨大**：中位数就超过1度，这远超单点观测的合理范围
3. **单点批次占比小**：仅11.83%，且同样无法保证是真实单点观测
4. **大批次占比高**：26-50点的批次虽然只占7.3%批次数，但占37.5%的点数

### 2.3 ADS-B时间重建结果

**全量运行结果**（56,521批次）：
- 候选行数：18,855（33.4%批次找到至少1个ADS-B候选）
- 匹配成功：0批次
- 拒绝原因统计：
  - `time_failed`：162,121次（时间窗口失配）
  - `geometry_failed`：38,705次（空间包络失配）
  - `identity_conflict`：3,289次（航班号冲突）
  - `phase_failed`：608次（飞行阶段不匹配）
  - `altitude_failed`：241次（高度范围失配）

**Smoke test结果**（500k location行，1,773批次）：
- 候选行数：587（33.1%批次找到候选）
- 匹配成功：0批次
- 主要拒绝原因：`geometry_failed`（1,113次），`time_failed`（355次）

**ADS-B数据质量**：
- 位置跳跃：255次（0.05%）
- 不合理速度：66,129次（13.2%）
- 重复位置：130次
- 采样间隔中位数：60秒
- Leg质量分布：C级9,691（94%），B级615（6%），A级3（<0.1%）

**诊断结论**：
1. **匹配质量不足**：0成功率说明当前约束条件下，AMDAR批次与ADS-B轨迹无法可靠对齐
2. **主要瓶颈**：几何包络失配（AMDAR批次空间跨度太大）和时间窗口失配
3. **ADS-B质量问题**：13%的不合理速度点说明ADS-B本身也有质量问题
4. **高质量Leg稀缺**：A/B级leg仅占6%，这限制了可用于重建的高质量轨迹

---

## 3. 核心问题诊断

### 3.1 真值候选过少的原因

**表面数据**：
- AMDAR总数：431,008
- strict_truth_candidate：6,615（1.53%）
- 实际可用作严格真值：0（因为都是批次时间）

**深层原因**：

这**不是筛选条件过严**，而是**AMDAR数据本质决定**的：

1. **时间语义限制**：98.47%的AMDAR属于重复时间批次，本质上就不具备逐点时间
2. **单点批次不可靠**：剩余1.53%的单点批次，也只是"碰巧该批次只下发了1个点"，不代表时间就是准确的观测时间
3. **数据来源特征**：AMDAR业务模式决定了它就是批量下发，不是逐点上报

**对比TURB**：
- TURB总数：181
- strict_truth_candidate：181（100%）
- 为什么TURB可以？因为TURB数据结构明显更干净，没有大规模"同航班同时间多点"现象

**结论**：真值候选少不是bug，是feature。强行降低筛选标准，只会把不可靠的数据当作真值，破坏整个holdout validation的可信度。

### 3.2 当前困境

**项目目标与数据现实的矛盾**：

1. **项目需求**：需要独立的holdout truth来验证风场重构质量
2. **AMDAR现状**：431,008条数据中，真正具备逐点时间保证的≈0
3. **TURB现状**：仅181条，且在时空分布上可能不足以代表整个风场
4. **GFS背景**：已经有200帧GFS forecast作为背景，但这是用于OI，不是真值

**你提到的困境**：
> "我其实已经没有其他数据了"

这是真实的。但问题不是"如何降低标准让AMDAR进入真值池"，而是"如何在现有条件下最大化AMDAR的价值"。

### 3.3 不应该做的事

❌ **降低strict truth筛选标准**：
- 把批次时间当作逐点时间
- 允许"可能不准但总比没有强"的数据进入holdout
- 这会破坏整个validation framework的可信度

❌ **强行推进ADS-B时间重建主链化**：
- 当前0%成功率说明技术路径尚未成熟
- 需要大幅放松约束才能提高覆盖率，但这会引入错误时间

❌ **放弃数据角色分层**：
- 把所有AMDAR都标记为high confidence
- 忽视批次时间的不确定性

---

## 4. 解决方案：分层置信度体系

### 4.1 核心思路

**不要混淆两个目标**：

1. **Strict Holdout Truth**：用于独立验证，必须严格
2. **Data Assimilation Support**：用于风场重构，可以宽容但要明确置信度

**关键创新**：引入**多层置信度体系**，让不同质量的数据在不同角色中发挥作用。

### 4.2 分层置信度定义

**T0层：Strict Truth（严格真值）**
- 定义：具备逐点观测时间，独立于任何模型/背景，可用于holdout验证
- 当前符合：TURB 181条
- AMDAR符合：0条（除非ADS-B重建成功）
- 置信度：`obs_conf = 1.0`, `holdout_eligible = true`
- 用途：Stage4 holdout evaluation唯一真值源

**T1层：High-Confidence Support（高置信度支持）**
- 定义：时间不确定性<5分钟，空间代表性好，气象质量通过
- AMDAR候选：单点批次（6,683批次）+ 小批次中心点
- 置信度：`obs_conf = 0.70-0.85`
- 用途：Stage4 OI主要约束，不进holdout但权重高

**T2层：Medium-Confidence Support（中置信度支持）**
- 定义：时间不确定性5-15分钟，批次内空间跨度<2度，高度跨度<1000m
- AMDAR候选：中小批次（2-10点，批次跨度不大）
- 置信度：`obs_conf = 0.45-0.65`
- 用途：Stage4 OI次要约束，降权使用

**T3层：Low-Confidence Support（低置信度支持）**
- 定义：时间不确定性15-30分钟，批次跨度较大但仍在合理范围
- AMDAR候选：大批次（11-25点），超大批次中质量较好的部分
- 置信度：`obs_conf = 0.25-0.40`
- 用途：背景填充、大尺度约束，高权重压制

**T4层：Display-Only（仅展示）**
- 定义：时间不确定性>30分钟，或空间跨度极大（>5度）
- AMDAR候选：最大批次（50点）、异常批次
- 置信度：`obs_conf = 0.05-0.20`
- 用途：完整性展示，CMA-style background fill，不参与正式评估

### 4.3 置信度计算公式

**基础置信度（针对AMDAR）**：

```python
def calculate_amdar_confidence(batch):
    """
    基于批次特征计算AMDAR观测置信度
    
    考虑因素：
    1. 批次大小（越小越好）
    2. 空间跨度（越小越好）
    3. 时间不确定性（基于批次特征估算）
    4. 飞行阶段（巡航>爬升>下降）
    5. 气象一致性（批次内风场变化是否合理）
    """
    
    # 批次大小惩罚
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
    
    # 空间跨度惩罚
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
    
    # 飞行阶段调整
    if batch.phase == 'LVR':
        phase_factor = 1.0  # 巡航最稳定
    elif batch.phase == 'ASC':
        phase_factor = 0.85  # 爬升变化快
    else:  # DES
        phase_factor = 0.75  # 下降变化更快
    
    # 气象一致性检查（需要批次内数据）
    if has_batch_points(batch):
        wind_std = batch.wind_speed_std
        dir_std = batch.wind_dir_circular_std
        
        if wind_std < 5 and dir_std < 15:
            met_factor = 1.0  # 高度一致
        elif wind_std < 10 and dir_std < 30:
            met_factor = 0.85  # 中等一致
        else:
            met_factor = 0.60  # 变化较大（可能真实变化或质量问题）
    else:
        met_factor = 0.80  # 默认
    
    # 最终置信度
    base_conf = 0.90  # AMDAR基准置信度（相对于仪器精度）
    batch_conf = base_conf * size_factor * spatial_factor * phase_factor * met_factor
    
    # 时间不确定性估算（秒）
    # 假设批次时间最多提前30分钟下发
    if batch.row_count == 1:
        time_uncertainty = 300  # 5分钟
    elif batch.row_count <= 4:
        time_uncertainty = 600  # 10分钟
    elif batch.row_count <= 10:
        time_uncertainty = 900  # 15分钟
    elif batch.row_count <= 25:
        time_uncertainty = 1500  # 25分钟
    else:
        time_uncertainty = 1800  # 30分钟
    
    return {
        'obs_conf': max(0.05, min(0.85, batch_conf)),  # 上限0.85，不能达到strict truth的1.0
        'time_uncertainty_s': time_uncertainty,
        'spatial_representativeness': spatial_factor,
        'holdout_eligible': False,  # AMDAR批次时间永不进holdout
        'tier': assign_tier(batch_conf)
    }

def assign_tier(conf):
    """根据置信度分配层级"""
    if conf >= 0.70:
        return 'T1_high_confidence'
    elif conf >= 0.45:
        return 'T2_medium_confidence'
    elif conf >= 0.25:
        return 'T3_low_confidence'
    else:
        return 'T4_display_only'
```

### 4.4 分层使用策略

**Stage2（数据组织）**：
- 保留所有AMDAR数据
- 添加 `obs_conf`, `time_uncertainty_s`, `confidence_tier` 字段
- 不改变数据量，只添加元数据

**Stage4（风场重构）**：

1. **Baseline run（兼容当前）**：
   - 继续使用 `wind_reconstruction_role` 字段
   - 保持当前的support_only/strict_truth二分法
   - 确保可复现性

2. **Confidence-aware run（新实验）**：
   - T0 (TURB 181条)：`holdout_only`，不参与重构，仅用于验证
   - T1 (AMDAR高置信)：`obs_conf=0.70-0.85`，主要约束
   - T2 (AMDAR中置信)：`obs_conf=0.45-0.65`，次要约束
   - T3 (AMDAR低置信)：`obs_conf=0.25-0.40`，背景约束
   - T4 (AMDAR展示)：`obs_conf=0.05-0.20`，填充only

3. **OI权重调整**：
   ```python
   # 当前：binary weight
   if role == 'strict_truth_candidate':
       weight = 1.0
   else:
       weight = 0.35  # support_only固定权重
   
   # 新方案：confidence-based weight
   weight = obs_conf * (1 / time_uncertainty_s) * spatial_representativeness
   ```

**Stage4评估**：
- **Holdout evaluation**: 仅用T0 (TURB 181条)
- **Support contribution analysis**: 分析T1/T2/T3各层对重构的贡献
- **Ablation study**: T0 only vs T0+T1 vs T0+T1+T2 vs T0+T1+T2+T3

---

## 5. ADS-B时间重建的正确定位

### 5.1 当前状态

**技术可行性**：原理上可行，工程上有挑战
**当前质量**：0%匹配成功率，远未达标
**主要障碍**：
1. AMDAR批次空间跨度太大（中位数>1度）
2. ADS-B质量问题（13%不合理速度）
3. 航班身份匹配困难（3,289次冲突）
4. 高质量ADS-B leg稀缺（A/B级仅6%）

### 5.2 推荐路径

**不应该**：强行推进全量重建并回写Stage1主链

**应该做**：

1. **作为独立研究分支继续推进**（Plan4 P10-P14）：
   - 优先解决ADS-B质量问题
   - 改进匹配算法（放宽几何约束，增加拒绝分级）
   - 建立pseudo-AMDAR闭环验证
   - 量化重建误差分布

2. **设立质量门槛**：
   - 只有当匹配成功率>80%且pseudo验证时间误差<5分钟时，才考虑主链化
   - 即使主链化，也只针对A/B级ADS-B leg重建的结果
   - 重建结果单独标记为 `time_source=adsb_reconstructed`

3. **分层重建策略**：
   - **A级重建**：ADS-B质量极高，匹配无歧义，时间重建误差<2分钟 → `obs_conf=0.90`, 可升至T0-like
   - **B级重建**：ADS-B质量好，匹配可信，时间重建误差<5分钟 → `obs_conf=0.75`, T1层
   - **C级重建**：ADS-B一般，匹配有风险 → `obs_conf=0.50`, T2层
   - **拒绝重建**：保持批次时间，按批次特征分配T2-T4

### 5.3 不要过度投入

**现实评估**：
- ADS-B时间重建即使成功，也只能覆盖部分AMDAR（受限于ADS-B可用性）
- 即使全部成功，也只能把部分AMDAR从T2/T3提升到T1，不能变成T0（因为仍依赖ADS-B推算）
- 相比之下，**分层置信度体系可以立即生效，覆盖全部431,008条AMDAR**

**投入优先级建议**：
1. **P0**：实施分层置信度体系（立即见效）
2. **P1**：完成Stage4 confidence-aware实验（验证效果）
3. **P2**：ADS-B重建继续作为研究分支（长期改进）

---

## 6. 完整执行计划（P0-P15）

### P0：Stage1增强置信度字段（优先级：⭐⭐⭐⭐⭐）

**目标**：在现有Stage1输出基础上，为每条AMDAR添加置信度和时间不确定性字段

**输入**：
- `stage1_output_plan4_v1/clean_wind.parquet`
- `stage1_output_plan4_v1/amdar_batch_statistics.parquet`

**操作**：
1. 读取批次统计，计算每个批次的置信度、时间不确定性、层级
2. 将批次级属性join回逐点数据
3. 对单点进行气象一致性检查（与邻近location对比）
4. 生成新字段：
   - `obs_conf_v2`：基于批次特征的置信度（0.05-0.85）
   - `time_uncertainty_s`：时间不确定性（秒）
   - `confidence_tier`：T1/T2/T3/T4
   - `spatial_representativeness`：空间代表性因子
   - `batch_met_consistency`：批次内气象一致性
5. 保留原有所有字段，确保向后兼容

**输出**：
- `stage1_output_plan4_v2/clean_wind_with_confidence.parquet`
- `stage1_output_plan4_v2/confidence_tier_summary.json`
- `stage1_output_plan4_v2/confidence_distribution_by_phase.json`

**验证**：
- 所有AMDAR行都有 `obs_conf_v2`, `confidence_tier`
- 置信度分布合理（不全是极端值）
- 层级分布：T1<T2<T3>T4
- TURB仍保持 `obs_conf=1.0`, `holdout_eligible=true`

**估算工时**：2-3小时（脚本开发+运行+验证）

---

### P1：Stage2兼容性测试（优先级：⭐⭐⭐⭐⭐）

**目标**：确认Stage2能够正确读取和传递新置信度字段

**操作**：
1. 用 `clean_wind_with_confidence.parquet` 替换Stage2输入
2. 跑Stage2（可以只跑一小部分帧，如10帧smoke test）
3. 检查Stage2输出中是否保留了 `obs_conf_v2`, `confidence_tier` 等字段
4. 确认数据没有意外丢失或损坏

**输出**：
- `stage2_smoke_confidence_v2/` (10帧测试输出)
- `stage2_confidence_compatibility_report.json`

**验证**：
- Stage2输出包含所有新字段
- 字段值与Stage1输出一致
- 无数据丢失

**估算工时**：1小时

---

### P2：Stage4 Baseline复现（优先级：⭐⭐⭐⭐⭐）

**目标**：确认当前最稳方案（tp26_thr11_preserve）在新Stage1下仍可复现

**操作**：
1. 使用 `stage1_output_plan4_v2` 运行Stage2全量（或200帧代表集）
2. 运行Stage3（GFS背景）
3. 运行Stage4 tp26_thr11_preserve
4. 对比新旧baseline的holdout RMSE

**输出**：
- `stage4_baseline_plan4_v2_200frames/`
- `baseline_comparison_report.json`

**验证**：
- Holdout RMSE差异<1%（应该几乎相同，因为只是添加了字段，没改角色）
- 确认TURB 181条仍然是唯一holdout truth
- 确认AMDAR仍按 `wind_reconstruction_role` 使用

**估算工时**：4-6小时（取决于是否全量）

---

### P3：Stage4 Confidence-Aware实验设计（优先级：⭐⭐⭐⭐）

**目标**：设计和实现基于置信度的风场重构方案

**操作**：
1. 修改Stage4代码，支持读取 `obs_conf_v2` 和 `confidence_tier`
2. 实现分层权重策略：
   ```python
   if source == 'turb':
       weight = 1.0  # holdout only
       use_in_reconstruction = False
   else:  # AMDAR
       base_weight = obs_conf_v2
       time_weight = 1.0 / (1.0 + time_uncertainty_s / 600.0)
       spatial_weight = spatial_representativeness
       weight = base_weight * time_weight * spatial_weight
       use_in_reconstruction = True
   ```
3. 实现层级过滤：
   - Experiment A: T0 holdout only (baseline)
   - Experiment B: T0 holdout + T1 reconstruction
   - Experiment C: T0 holdout + T1+T2 reconstruction
   - Experiment D: T0 holdout + T1+T2+T3 reconstruction
   - Experiment E: T0 holdout + T1+T2+T3+T4 reconstruction (full)
4. 保持其他参数与baseline一致（tp26, thr11, preserve）

**输出**：
- `stage4_confidence_aware/` (代码修改)
- `experiment_design_doc.md`

**验证**：
- 代码可以正确读取和使用置信度字段
- 权重计算符合设计
- 可以灵活切换不同实验配置

**估算工时**：3-4小时

---

### P4：Confidence-Aware实验执行（优先级：⭐⭐⭐⭐）

**目标**：运行实验A-E，评估不同置信度层级的贡献

**操作**：
1. 对每个实验运行Stage4（建议先用200帧代表集）
2. 收集指标：
   - Holdout RMSE (u, v, vector, speed, direction)
   - Support count by tier
   - Spatial coverage (有风场估计的网格点占比)
   - Confidence distribution in output
3. 生成对比报告

**输出**：
- `stage4_exp_A_T0only/` 
- `stage4_exp_B_T0T1/`
- `stage4_exp_C_T0T1T2/`
- `stage4_exp_D_T0T1T2T3/`
- `stage4_exp_E_full/`
- `confidence_experiments_comparison.json`
- `confidence_experiments_report.md`

**预期结果**：
- Exp A (T0 only): RMSE最高，覆盖率极低（只有181个点）
- Exp B (T0+T1): RMSE显著下降，覆盖率提升
- Exp C (T0+T1+T2): RMSE进一步下降，覆盖率继续提升
- Exp D (T0+T1+T2+T3): RMSE接近baseline，覆盖率接近full
- Exp E (full): 覆盖率最高，RMSE可能略升（因为包含低质量点）

**关键问题**：
- T2/T3能否在不显著恶化RMSE的前提下，大幅提升覆盖率？
- 最优的tier cutoff在哪里？

**估算工时**：8-12小时（取决于运行时间）

---

### P5：Confidence-Tier优化（优先级：⭐⭐⭐）

**目标**：基于P4结果，优化置信度阈值和层级定义

**操作**：
1. 分析P4实验结果，找出RMSE与覆盖率的trade-off曲线
2. 如果某个tier显著恶化RMSE，调整该tier的置信度阈值或权重
3. 可能的调整：
   - 细化T1（分为T1-high和T1-medium）
   - 调整时间不确定性惩罚系数
   - 引入空间自适应权重（密集区域降权，稀疏区域提权）
4. 重新运行关键实验验证

**输出**：
- `confidence_tier_optimization_report.md`
- `stage1_output_plan4_v3/` (如果需要调整置信度计算)

**估算工时**：4-6小时

---

### P6：Production Configuration确定（优先级：⭐⭐⭐⭐）

**目标**：确定最终推荐的生产配置

**操作**：
1. 综合P4-P5结果，选择最佳tier组合
2. 文档化最终配置：
   - 使用哪些tier
   - 各tier权重公式
   - 置信度计算参数
3. 生成production-ready Stage1配置
4. 更新项目文档

**输出**：
- `production_config_recommendation.md`
- `stage1_production_settings.json`
- 更新的 `centralized_v1_ultimate_summary`

**推荐决策框架**：
- 如果T1+T2就能达到>95%的baseline RMSE且覆盖率显著提升 → 推荐T0+T1+T2
- 如果需要T3才能达到满意覆盖率且RMSE退化<3% → 推荐T0+T1+T2+T3
- T4一般只用于display-only产品分支

**估算工时**：2-3小时

---

### P7：12km+高空专项优化（优先级：⭐⭐⭐）

**目标**：针对高空（>12km）进行专项分析和优化

**背景**：
- 从项目总结得知，12km+占点数41.89%，但贡献SSE 76.18%
- 这是当前最大的误差来源

**操作**：
1. 分析12km+的AMDAR分布和置信度分布
2. 检查12km+是否AMDAR批次特征更差（更大跨度？）
3. 针对12km+设计专门的置信度调整：
   - 可能需要更严格的筛选
   - 或者引入高度相关的权重衰减
4. 运行12km+ targeted实验

**输出**：
- `high_altitude_analysis_report.md`
- `confidence_altitude_adjustment.json`

**估算工时**：4-5小时

---

### P8：GFS背景与AMDAR一致性分析（优先级：⭐⭐⭐）

**目标**：评估不同置信度AMDAR与GFS背景的一致性，作为质量交叉验证

**操作**：
1. 对每个AMDAR点，提取最近的GFS背景值
2. 计算AMDAR与GFS的差异（innovation）
3. 按置信度层级统计innovation分布
4. 预期：高置信度AMDAR的innovation应该更小且更符合正态分布

**输出**：
- `amdar_gfs_innovation_by_tier.json`
- `innovation_distribution_plots/` (如果有可视化)

**用途**：
- 验证置信度分级是否合理
- 识别可能的异常点
- 为future的Desroziers迭代提供基础

**估算工时**：3-4小时

---

### P9：完整文档更新（优先级：⭐⭐⭐⭐）

**目标**：更新所有项目文档，反映新的置信度体系

**操作**：
1. 更新 `centralized_v1_ultimate_summary`，添加置信度体系章节
2. 更新Stage1文档，说明新字段
3. 创建 `confidence_aware_workflow_guide.md`
4. 更新Stage4文档，说明如何使用置信度
5. 创建decision log，记录为什么采用当前方案

**输出**：
- 更新的项目文档集
- `confidence_system_design_rationale.md`

**估算工时**：3-4小时

---

## P10-P14：ADS-B时间重建研究分支（优先级：⭐⭐，长期任务）

这部分与主链解耦，可以并行或后续进行。

### P10：ADS-B质量增强（优先级：⭐⭐）

**目标**：提升ADS-B数据质量，降低不合理速度占比

**操作**：
1. 对13.2%的不合理速度点进行根因分析
2. 改进速度异常检测算法（考虑加速度约束）
3. 引入multi-pass过滤（先粗筛，再精筛）
4. 可能需要向上游确认ADS-B数据源和处理方式

**输出**：
- `adsb_quality_enhancement_report.md`
- 改进的ADS-B QC脚本

**估算工时**：6-8小时

---

### P11：AMDAR-ADSB匹配算法改进（优先级：⭐⭐）

**目标**：提高匹配成功率，从当前0%提升到至少30-50%

**操作**：
1. 分析当前拒绝原因，逐类设计改进方案：
   - `geometry_failed` (38705次)：放宽空间包络，使用adaptive padding
   - `time_failed` (162121次)：扩大时间窗口，引入phase-aware padding
   - `identity_conflict` (3289次)：改进航班号匹配逻辑，容忍格式差异
2. 实现分级匹配：
   - Strict match: 所有条件都满足，高置信度
   - Relaxed match: 部分条件放宽，中置信度
   - Weak match: 大幅放宽，低置信度，仅用于研究
3. 重新运行匹配

**输出**：
- `adsb_matching_v2/` (改进算法)
- `matching_success_rate_comparison.json`

**估算工时**：8-10小时

---

### P12：Pseudo-AMDAR闭环完善（优先级：⭐⭐）

**目标**：建立可靠的闭环验证，量化重建误差

**操作**：
1. 扩大pseudo-AMDAR case数量（当前0，目标>1000）
2. 对每个case，记录：
   - 真实时间 vs 重建时间
   - 重建误差分布
   - 匹配质量等级
3. 分析哪些类型的批次重建误差小，哪些大
4. 建立误差模型

**输出**：
- `pseudo_amdar_validation_extended.parquet`
- `time_reconstruction_error_model.json`

**估算工时**：6-8小时

---

### P13：A/B级重建优先实现（优先级：⭐⭐）

**目标**：只针对高质量ADS-B leg进行时间重建，确保质量

**操作**：
1. 筛选A/B级leg（当前仅6% ADS-B leg）
2. 只对匹配到A/B级leg的AMDAR批次进行重建
3. 对重建结果进行严格验证
4. 如果pseudo误差<5分钟，标记为可升级

**输出**：
- `amdar_reconstructed_AB_grade.parquet`
- `reconstruction_quality_report_AB.json`

**预期结果**：
- 覆盖率：可能只有5-10%的AMDAR批次
- 质量：时间误差<5分钟
- 置信度提升：从T2/T3提升到T1

**估算工时**：5-6小时

---

### P14：重建结果选择性集成（优先级：⭐⭐）

**目标**：将高质量重建结果选择性集成到主链

**操作**：
1. 只接受A/B级重建且pseudo误差<5分钟的结果
2. 为这些点添加：
   - `observation_time_utc` (重建时间)
   - `observation_time_source` = 'adsb_reconstructed'
   - `observation_time_uncertainty_s` (基于pseudo误差)
   - `obs_conf_v2` 提升至0.75-0.85（但仍<1.0，不进holdout）
   - `confidence_tier` 提升至T1
3. 重新运行Stage4 confidence-aware实验
4. 评估重建对RMSE和覆盖率的边际贡献

**输出**：
- `stage1_output_plan4_v4_with_reconstruction/`
- `reconstruction_impact_analysis.json`

**预期效果**：
- 如果只有5-10%覆盖率，边际效果可能有限
- 但可以作为未来扩大重建范围的验证

**估算工时**：4-5小时

---

## P15：Stage5保守推进（优先级：⭐，可选）

**目标**：在置信度体系下，评估Stage5是否仍有价值

**操作**：
1. 使用confidence-aware Stage4输出作为Stage5输入
2. 保持当前最保守的gate-only方案
3. 只允许12km+抑制
4. 严格的pairwise验证

**判断标准**：
- 如果confidence-aware Stage4已经接近proxy floor，Stage5增益可能很小
- 如果12km+仍然是主要误差源，gate-only可能有帮助

**估算工时**：视Stage4结果而定，可能10-15小时

---

## 7. 执行优先级与时间规划

### 7.1 立即执行（P0-P6，预计3-5天）

**第一阶段（关键路径）**：
1. **Day 1上午**：P0 - Stage1增强置信度字段
2. **Day 1下午**：P1 - Stage2兼容性测试
3. **Day 2上午**：P2 - Stage4 Baseline复现（smoke 10帧）
4. **Day 2下午**：P3 - Confidence-Aware实验设计
5. **Day 3全天**：P4 - 运行实验A-E（200帧）
6. **Day 4上午**：P5 - 分析结果，优化tier
7. **Day 4下午**：P6 - 确定production配置
8. **Day 5**：P7-P9 - 高空专项、GFS一致性、文档

**交付物**：
- 可工作的置信度体系
- 实验验证报告
- Production推荐配置

### 7.2 并行研究（P10-P14，预计1-2周，可与P0-P9并行）

**如果有额外资源**：
- 可以同时推进ADS-B重建研究
- 但不阻塞主线（置信度体系）

**如果资源有限**：
- 先完成P0-P9
- 再根据效果决定是否继续P10-P14

### 7.3 可选扩展（P15，视情况而定）

---

## 8. 风险与缓解

### 8.1 技术风险

**风险1**：置信度公式设计不当，导致不合理的权重分布
- **缓解**：P4实验会暴露问题，P5可以调整
- **回退**：可以回到binary scheme (support vs strict)

**风险2**：Confidence-aware实验RMSE反而恶化
- **缓解**：逐层添加（A→B→C→D），可以定位问题层级
- **回退**：保留baseline配置

**风险3**：Stage2/Stage4代码需要大改，引入新bug
- **缓解**：先smoke test，再full run
- **回退**：保留原始代码分支

### 8.2 数据风险

**风险4**：TURB 181条太少，holdout评估不稳定
- **现实**：这是客观限制，但181条分布在200帧中，每帧平均<1条
- **缓解**：
  - 可以考虑bootstrap重采样评估置信区间
  - 可以用GFS innovation作为辅助质量指标（P8）
  - 强调这是proof-of-concept，不是operational system

**风险5**：分层置信度可能被误解为"降低标准"
- **缓解**：
  - 在文档中明确：holdout truth标准不变（仍只有TURB）
  - 置信度是用于data assimilation，不是validation
  - 分层使用是为了"充分利用数据"，不是"放松质量要求"

### 8.3 项目定位风险

**风险6**：过度投入AMDAR优化，偏离项目核心价值
- **提醒**：项目核心是"auditable aircraft-holdout validation framework"
- **缓解**：
  - 置信度体系是为了更好地利用support data，符合核心价值
  - 不改变holdout validation的严格性
  - 文档中继续强调框架价值>指标提升

---

## 9. 预期成果与评估标准

### 9.1 P0-P6成果（置信度体系）

**成功标准**：
1. ✅ 所有AMDAR都有合理的置信度（不是全0或全1）
2. ✅ Confidence-aware Stage4可以运行且不crash
3. ✅ 至少一个tier组合（如T0+T1+T2）能够：
   - Holdout RMSE ≤ baseline * 1.05（恶化不超过5%）
   - 覆盖率显著提升（相比只用support_only）
   - 产生合理的风场（无明显artifacts）

**优秀标准**：
1. 🌟 某个tier组合 Holdout RMSE < baseline * 0.98（改善>2%）
2. 🌟 12km+误差显著下降
3. 🌟 GFS innovation分析验证了置信度分级的合理性

**如果失败**：
- 如果所有tier组合RMSE都>baseline*1.10，说明置信度设计有问题，需要回到P5重新设计
- 如果覆盖率没有提升，说明tier cutoff太严格，需要调整

### 9.2 P10-P14成果（ADS-B重建）

**成功标准**：
1. ✅ ADS-B质量提升，不合理速度占比从13%降至<5%
2. ✅ 匹配成功率从0%提升到>30%
3. ✅ Pseudo-AMDAR验证有>500个成功case，时间误差<10分钟

**优秀标准**：
1. 🌟 A/B级重建成功率>80%，时间误差<5分钟
2. 🌟 重建覆盖>10% AMDAR点
3. 🌟 重建点集成后，holdout RMSE有可测量的改善

**如果失败**：
- 如果匹配成功率仍<10%，说明AMDAR批次与ADS-B根本难以对齐，应该放弃这条路线
- 如果pseudo误差>15分钟，说明重建不可靠，不应该集成到主链

---

## 10. 最终建议

### 10.1 关于"真值候选太少"

**结论**：这不是筛选条件的问题，而是AMDAR数据特征决定的。

**应对**：不要降低strict truth标准，而是通过置信度体系充分利用所有数据。

### 10.2 关于"没有其他数据"

**现实评估**：
- AMDAR: 431,008条，但无逐点时间
- TURB: 181条，有逐点时间但太少
- Location: 19,162,638条，ADS-B轨迹，可能用于重建
- GFS: 200帧背景，用于OI，不是真值

**策略**：
- 接受"holdout truth稀缺"的现实
- 通过置信度体系，让AMDAR在reconstruction中发挥最大作用
- 不要混淆reconstruction support和holdout truth两个角色

### 10.3 关于置信度方案

**可行性**：⭐⭐⭐⭐⭐（高度可行）

**理由**：
1. 技术上简单：只是添加字段和权重，不改变核心算法
2. 向后兼容：保留原有binary scheme
3. 立即生效：不依赖ADS-B重建
4. 可解释：每个置信度都有明确的物理/业务含义
5. 可扩展：未来ADS-B重建成功后，可以提升部分点的置信度

**风险**：⭐⭐（低风险）
- 主要风险是参数调优，但P4实验会验证
- 有明确的回退路径

### 10.4 下一步立即行动

**如果你同意这个方案**，建议：

1. **立即开始P0**（今天）：
   - 我可以帮你写置信度计算脚本
   - 预计2-3小时完成
   
2. **明天P1-P2**：
   - Stage2兼容性测试
   - Baseline复现

3. **后天开始P3-P4**：
   - 实验设计和执行

4. **本周内完成P0-P6主线**

5. **下周决定是否继续P10-P14**（基于P0-P6效果）

**如果你不同意这个方案**，请告诉我：
- 哪些部分有疑虑？
- 是否有其他优先考虑？
- 项目的实际约束是什么（时间、资源、业务需求）？

---

## 11. 总结

**核心诊断**：
- 真值候选少是AMDAR批次时间特征决定的，不是筛选过严
- 当前最大的未利用价值在于：98%的AMDAR被binary分为support_only，实际上它们质量差异很大

**核心方案**：
- 引入分层置信度体系（T1-T4）
- 保持strict holdout不变（仅TURB）
- 让不同质量的AMDAR在reconstruction中发挥差异化作用
- ADS-B重建作为长期研究，不阻塞主线

**预期效果**：
- 覆盖率提升（相比binary scheme）
- RMSE持平或略有改善
- 风场产品更完整
- 框架仍然保持auditable和严格

**执行路径**：
- P0-P6为主线（3-5天）
- P10-P14为研究分支（1-2周，可并行）
- P15视情况而定

**最大价值**：
- 不是某个指标提升了多少
- 而是建立了一套可持续的数据利用框架
- 未来任何新数据源（新卫星、新地面站）都可以按置信度分级接入

---

## 附录A：置信度计算参数表

| 参数 | 值 | 说明 |
|------|------|------|
| AMDAR基准置信度 | 0.90 | 相对于仪器精度 |
| 单点批次size_factor | 0.85 | 仍有批次时间不确定性 |
| 2-4点批次size_factor | 0.70 | |
| 5-10点批次size_factor | 0.55 | |
| 11-25点批次size_factor | 0.35 | |
| 26+点批次size_factor | 0.15 | |
| T1置信度下限 | 0.70 | |
| T2置信度下限 | 0.45 | |
| T3置信度下限 | 0.25 | |
| T4置信度下限 | 0.05 | |
| AMDAR置信度上限 | 0.85 | 永远<1.0，因为批次时间 |
| TURB置信度 | 1.00 | 唯一的strict truth |

---

## 附录B：关键决策记录

**决策1**：为什么不降低strict truth标准？
- 理由：保持validation framework的可信度是项目核心价值
- 后果：Holdout仅181条，评估可能有噪声
- 缓解：用bootstrap和GFS innovation辅助评估

**决策2**：为什么置信度上限0.85而非更高？
- 理由：所有AMDAR都有批次时间不确定性，不应与TURB等同
- 后果：即使最好的AMDAR也不能进holdout
- 备选：未来如果ADS-B重建达到A级且误差<2分钟，可以考虑0.90-0.95，但仍不到1.0

**决策3**：为什么分4层而非更多/更少？
- 理由：4层可以覆盖"高中低展示"四种典型用途
- 备选：可以在P5根据实验结果调整为3层或5层

**决策4**：为什么ADS-B重建不是主线？
- 理由：当前0%成功率，技术不成熟
- 后果：短期内无法利用ADS-B提升AMDAR时间精度
- 未来：作为研究分支持续改进

---

**报告完成时间**：2026-07-01
**作者**：AI Assistant
**版本**：v1.0
**状态**：待审阅与决策
