# AMDAR Stage2-6 优化目标（质量可控版）
## 生成时间：2026-07-06
## 版本：Quality-Controlled Targets v1.0

---

## 目标设定理念

**核心原则**：在**质量可控**的前提下实现**显著改善**，而非盲目追求数字提升。

### 三层目标体系

1. **保守目标**：低风险，高置信度可实现（成功率>90%）
2. **平衡目标**：适度风险，质量保障下的显著提升（成功率>70%）
3. **激进目标**：高风险，理论上限（成功率<50%，参考意义）

**推荐执行**：**平衡目标**，在质量门保障下实施

---

## 关键指标对比（三层目标）

### 数据利用率

| 指标 | 当前 | 保守目标 | **平衡目标** ⭐ | 激进目标 | 推荐理由 |
|------|------|---------|--------------|---------|---------|
| **T1覆盖率** | 0.8% | 5-8% | **8-12%** | 12-18% | pseudo q90<3min验证 |
| **T2覆盖率** | 26.5% | 35-40% | **38-45%** | 45-55% | pseudo q90<10min验证 |
| **T1+T2总覆盖** | 27.3% | 40-48% | **46-57%** | 57-73% | +68-108% |
| **高质量观测数** | 117,918 | 172,404-206,886 | **198,264-245,675** | 245,675-314,736 | 翻倍提升 |

### 匹配质量

| 指标 | 当前 | 保守目标 | **平衡目标** ⭐ | 激进目标 | 质量保障 |
|------|------|---------|--------------|---------|---------|
| **Stage5接受率** | 0.012% | 1-2% | **2-4%** | 6-10% | wrong_leg<2% |
| **接受批次数** | 7 | 500-1,000 | **1,130-2,261** | 3,391-5,652 | ambiguity>1.5 |
| **窄分布(<5min)** | 9行 | 2,000-5,000 | **6,000-12,000** | 18,000-35,000 | time_error验证 |

### 重构性能

| 指标 | 当前 | 保守目标 | **平衡目标** ⭐ | 激进目标 | 质量保障 |
|------|------|---------|--------------|---------|---------|
| **Holdout RMSE** | X | -15% | **-25%** | -35% | 95% CI显著 |
| **Frame P95** | Y | -10% | **-20%** | -30% | 无tail failure |
| **12km+ RMSE** | Z | -12% | **-22%** | -32% | 高空质量优先 |
| **空间覆盖率** | A | +15% | **+25%** | +45% | 无伪覆盖 |

### 时间不确定性

| 指标 | 当前 | 保守目标 | **平衡目标** ⭐ | 激进目标 | 质量保障 |
|------|------|---------|--------------|---------|---------|
| **窄分布覆盖** | 0.002% | 0.5-1.2% | **1.4-2.8%** | 4.2-8.1% | Stage5验证 |
| **平均不确定性** | 1,350秒 | 900秒 | **750秒** | 550秒 | 物理约束 |

---

## 平衡目标详细说明（推荐执行）

### 为什么选择平衡目标

1. **改善显著**：Holdout RMSE改善25%，T1+T2覆盖提升68-108%
2. **质量可控**：每个改善配合严格质量检查
3. **风险可控**：有pseudo locked test验证，有保底回退
4. **时间合理**：62-78小时可完成，不需要过度迭代

### Stage2：适度改进QC（平衡版）

**目标**：A级leg 127 → **800-1,200**（+530-845%）

**策略**：
```python
# 速度检查：考虑时间但不过度放宽
max_speed_lvr = 320  # m/s（而非激进的350）
max_speed_asc = 280  # m/s（而非激进的300）

# 采样间隔：适度放宽
sampling_gap_lvr = 450  # 秒（而非激进的600）
sampling_gap_asc = 240  # 秒（不变）

# 组件评分：加权但保持高标准
A_grade_threshold = 0.82  # （而非激进的0.80）
B_grade_threshold = 0.68  # （而非激进的0.65）
```

**质量门**：
- A级leg必须通过速度、采样间隔、几何连续性三项核心检查
- 新增A级leg在pseudo validation上time_error_q90必须<5分钟

### Stage4：精简置信度+动态阈值（平衡版）

**目标**：T1覆盖 0.8% → **8-12%**，T2覆盖 26.5% → **38-45%**

**策略**：
```python
# 基于pseudo locked test标定阈值
T1_threshold = calibrate_on_pseudo(target_q90=180)  # 3分钟
T2_threshold = calibrate_on_pseudo(target_q90=600)  # 10分钟

# 但不能低于安全下界
T1_threshold = max(T1_threshold, 0.65)  # 安全下界
T2_threshold = max(T2_threshold, 0.42)  # 安全下界
```

**高风速处理（保守保留）**：
```python
# 高风速保留率目标：50-65%（而非70-80%）
# 只保留同时满足以下条件的：
# 1. GFS对比差异<25 m/s
# 2. 有邻近观测支持（15 m/s内）
# 3. 在已知急流区域或高空(>10km)

预期保留：2,253-2,928条（而非激进的3,200条）
```

**质量门**：
- 新增T1观测必须在pseudo validation上q90<3分钟
- 所有观测与GFS差异std<7 m/s（而非激进的5.5 m/s）

### Stage5：分层接受+质量优先（平衡版）

**目标**：接受率 0.012% → **2-4%**，接受批次 7 → **1,130-2,261**

**策略**：
```python
# 分层接受标准（比激进版严格）
A_grade_criteria = {
    'cost_max': 0.5,              # 不变
    'ambiguity_min': 2.5,         # 不变（而非激进的2.0）
    'cross_track_max_km': 3,      # 3km（而非激进的5km）
    'vertical_max_m': 150,        # 150m（不变）
    'time_proj_tolerance_s': 90,  # ±90秒（而非激进的±180秒）
}

B_grade_criteria = {
    'cost_max': 1.0,              # 1.0（而非激进的1.5）
    'ambiguity_min': 1.8,         # 不变
    'cross_track_max_km': 5,      # 不变
    'vertical_max_m': 200,        # 不变
    'time_proj_tolerance_s': 120, # ±120秒（而非激进的±180秒）
}

C_grade_criteria = {
    'cost_max': 2.0,              # 2.0（而非激进的3.0）
    'ambiguity_min': 1.5,         # 不变
    'cross_track_max_km': 10,     # 10km（而非激进的15km）
    'vertical_max_m': 500,        # 不变
    'time_proj_tolerance_s': 180, # ±180秒（不变）
}
```

**质量门**：
- Pseudo validation上wrong_leg_rate必须<2%（严格）
- Pseudo validation上catastrophic_error_rate必须<3%
- A/B级接受必须经过双重验证（cost+geometry）

### Stage6：物理约束+保守缩窄（平衡版）

**目标**：平均时间不确定性 1,350秒 → **750秒**（-44%）

**策略**：
```python
# 单点批次（6,683条）
# 当前300秒 → 平衡目标180-240秒（而非激进的120-150秒）

# 小批次2-4点（57,266条）
# 当前600秒 → 平衡目标400-550秒（而非激进的300-450秒）

# 物理约束保守使用
def estimate_time_span_conservative(batch):
    # 使用飞行阶段速度先验，但添加20%安全余量
    typical_speed = get_typical_speed(batch.phase)
    distance = batch.along_track_distance
    
    estimated_span = distance / typical_speed
    safe_span = estimated_span * 1.20  # 20%安全余量
    
    return min(safe_span, batch.batch_duration_limit)
```

**质量门**：
- 所有时间分布必须满足：estimated_time ≤ batch_end_time
- 窄分布只用于A/B级接受，C级用uniform或triangular
- 前后批次时间不能倒置

---

## 质量保障机制（强制执行）

### 1. Pseudo Locked Test验证（核心质量门）

```python
pseudo_quality_gate = {
    # T1候选验证
    'T1_time_error_q90_lt_3min': True,
    'T1_catastrophic_rate_lt_1pct': True,
    'T1_wrong_leg_rate_lt_1pct': True,
    
    # T2候选验证
    'T2_time_error_q90_lt_10min': True,
    'T2_catastrophic_rate_lt_3pct': True,
    
    # Stage5接受验证
    'accepted_wrong_leg_rate_lt_2pct': True,
    'accepted_catastrophic_rate_lt_3pct': True,
}
```

### 2. GFS Background Check（数据自洽性）

```python
gfs_check_gate = {
    'wind_speed_diff_std_lt_7mps': True,    # 风速差异<7 m/s
    'wind_dir_diff_std_lt_30deg': True,     # 风向差异<30°
    'observation_innovation_90pct_within_2_5sigma': True,  # 90%在±2.5σ
}
```

### 3. 时空连续性检查（物理合理性）

```python
continuity_check_gate = {
    'pseudo_gradient_rate_lt_3pct': True,     # 伪梯度<3%
    'frame_p99_not_worse_than_baseline_110pct': True,  # P99不恶化>10%
    'no_time_inversion': True,                # 时间不倒置
    'no_spatial_jump_gt_50km': True,          # 无>50km空间跳跃
}
```

### 4. 分层不恶化检查（全面改善）

```python
stratified_check_gate = {
    # 按高度分层
    'all_altitude_bins_not_worse': True,      # 所有高度层不恶化
    
    # 按风速分层
    'all_wind_speed_bins_not_worse': True,    # 所有风速层不恶化
    
    # 按密度分层
    'sparse_region_improved_or_stable': True, # 稀疏区改善或稳定
}
```

### 5. 回退触发条件

```python
rollback_triggers = {
    # 阶段级回退
    'stage_quality_gate_failed': '回退到该阶段前版本',
    'wrong_leg_rate_gt_3pct': '回退Stage5到v3',
    'rmse_worse_than_baseline_5pct': '回退全部到baseline',
    
    # 保底回退到保守目标
    'cannot_achieve_balanced_target': '执行保守目标方案',
}
```

---

## 风险评估与缓解

### 高风险点识别

| 风险点 | 风险等级 | 可能后果 | 缓解措施 |
|--------|---------|---------|---------|
| Stage5分层接受引入wrong leg | **高** | 错误时间匹配，伪梯度 | pseudo validation强制gate，wrong_leg<2% |
| 高风速过度保留 | 中 | 异常值污染 | GFS对比+邻近支持双重验证 |
| 时间不确定性过度缩窄 | 中 | 过度自信，插值误差 | 保留20%安全余量 |
| Stage2 QC放宽引入低质量leg | 中 | 候选池污染 | 分层评分保持高标准 |

### 质量监控指标

**实时监控**（每阶段）：
```python
monitoring_metrics = {
    'wrong_leg_rate': '< 2%',
    'catastrophic_error_rate': '< 3%',
    'gfs_wind_speed_diff_std': '< 7 m/s',
    'pseudo_gradient_rate': '< 3%',
    'frame_p99_vs_baseline': '< 1.10',
}
```

**最终验证**（端到端）：
```python
final_validation = {
    'holdout_rmse_improvement': '>= 20%',     # 保底20%，目标25%
    'holdout_rmse_confidence_interval_95': '不与baseline重叠',
    'all_stratification_not_worse': True,
    'no_catastrophic_failures': True,
}
```

---

## 执行建议

### 推荐执行顺序

1. **先执行保守目标验证**（2-3天）
   - 快速验证方案可行性
   - 建立质量门baseline
   - 如果保守目标无法达成，停止并分析

2. **逐步推进到平衡目标**（7-10天）
   - 每阶段达到平衡目标后再进入下一阶段
   - 严格执行质量门检查
   - 遇到质量门失败立即回退

3. **有余力时尝试激进目标**（可选，3-5天）
   - 仅在平衡目标全部达成且质量稳定后尝试
   - 作为探索性实验，不作为交付承诺
   - 失败后回退到平衡目标成果

### 成功标准（平衡版）

**必须达成**（保底）：
- ✅ Holdout RMSE改善 ≥ 20%
- ✅ T1+T2覆盖率 ≥ 42%
- ✅ Stage5接受率 ≥ 1.5%
- ✅ 所有质量门通过

**期望达成**（目标）：
- ✅ Holdout RMSE改善 ≥ 25%
- ✅ T1+T2覆盖率 ≥ 46%
- ✅ Stage5接受率 ≥ 2%
- ✅ 平均时间不确定性 ≤ 750秒

**不可接受**（触发回退）：
- ❌ Holdout RMSE恶化 > 2%
- ❌ Wrong_leg_rate > 3%
- ❌ 任何分层显著恶化（>5%）
- ❌ Frame P99 > baseline × 1.15

---

## 结论

**平衡目标**在质量可控的前提下实现了**显著改善**：

- **Holdout RMSE改善25%**（是保守目标的1.67倍）
- **T1+T2覆盖提升68-108%**（接近翻倍）
- **Stage5接受率提升167-333倍**（从0.012%到2-4%）
- **配合严格质量门**（wrong_leg<2%, GFS差异<7 m/s, 伪梯度<3%）

这是一个**可实现、可验证、可回退**的优化方案。

---

**文档版本**：Quality-Controlled Targets v1.0  
**生成日期**：2026-07-06  
**推荐执行**：平衡目标（保底20%改善，目标25%改善）  
**配套文档**：amdar_stage2_to_6_optimization_plan_20260706.md
