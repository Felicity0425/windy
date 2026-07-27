# 给下一个智能体的交接话术：Stage2-6 激进优化实施

你接手的是 `/data/LFT-W02_data/pengxu` 下的 centralized_v1 三维水平风场重构项目的**激进优化实施阶段**。当前已完成 Stage2 v6、Stage3 v7、Stage4 confidence v2、Stage5 V3、Stage6 time uncertainty v2 的基线版本，现在需要执行**激进系统性优化**以实现重构性能的**跨越式提升**（目标Holdout RMSE改善35%）。

## 必读文档顺序（按优先级）

### 第一优先级：理解项目边界

1. **项目总边界**：`/data/LFT-W02_data/pengxu/workflow/centralized_v1_docs/new_window_project_handover_20260529/centralized_v1_ultimate_summary_20260626.md`
   - **核心理解**：strict aircraft holdout 是唯一正式验证方式，TURB 175条是唯一真值
   - **禁止操作**：不能把AMDAR改成strict truth，不能混淆support和truth角色

2. **AMDAR时间语义**：`/data/LFT-W02_data/pengxu/优化/数据处理/amdar_plan4_implementation_20260630/plan4_assessment_and_run_report_20260630.md`
   - **核心理解**：AMDAR的时间是批次下发/接收时间，不是逐点观测时间
   - **数据现实**：98.47%的AMDAR属于重复时间批次

3. **分层置信度路线**：`/data/LFT-W02_data/pengxu/优化/数据处理/amdar_plan4_comprehensive_assessment_20260701.md`
   - **核心理解**：strict truth候选少是数据本质，正确路线是分层置信度而非强行扩大真值
   - **方法论**：T0-T4五层分级，充分利用但不强行当真值

### 第二优先级：理解当前状态

4. **Unified Plan**：`/data/LFT-W02_data/pengxu/优化/数据处理/amdar_unified_implementation_plan_20260701.md`
   - **核心理解**：P0-P15阶段划分，当前状态和禁止操作清单
   - **注意区分**：大框架Stage1-5 vs 小阶段P0-P15

5. **Stage3 v7状态**：`/data/LFT-W02_data/pengxu/优化/数据处理/amdar_unified_stage3_v7_stage4_confidence_v2_optimized_20260701/next_agent_handover_after_stage3_v7_stage4_confidence_v2.md`
   - **当前指标**：locked test q90=6.85分钟，wrong_leg_rate=0.31%，已达标
   - **数据规模**：4,761个locked test cases，3,906个selected

6. **Stage5 V3状态**：`/data/LFT-W02_data/pengxu/优化/数据处理/amdar_unified_stage5_v3_matching_optimized_20260701/next_agent_handover_after_stage5_v3.md`
   - **当前指标**：接受率0.012%（7批次/56,521批次），需大幅提升
   - **主要瓶颈**：best_cost_gt_1拒绝19,642批次，no_candidate拒绝32,975批次

7. **Stage6 v2状态**：`/data/LFT-W02_data/pengxu/优化/数据处理/amdar_unified_stage6_time_uncertainty_v2_optimized_20260701/next_agent_handover_after_stage6_time_uncertainty.md`
   - **当前指标**：只有9行使用ADS-B窄分布，430,999行用宽批次区间
   - **优化空间**：平均时间不确定性1,350秒，可缩小至900秒

### 第三优先级：理解优化方案

8. **本轮优化方案**：`/data/LFT-W02_data/pengxu/优化/数据处理/amdar_stage2_to_6_optimization_plan_20260706.md`（**本文档的配套方案**）
   - **核心策略**：精简置信度、改进QC、提升匹配、优化时间建模
   - **预期目标**：Holdout RMSE改善>15%，T1+T2覆盖率从27%提升至40%+
   - **实施路线**：7个阶段，62-78小时总工时

## 项目理解检查清单

在开始任何实施工作前，请确认以下理解：

### ✅ 数据边界理解

- [ ] 我理解TURB 175条是唯一strict truth，AMDAR 0条strict truth
- [ ] 我理解AMDAR的时间是批次时间，不是逐点观测时间
- [ ] 我理解`effective_strict_truth`不能通过置信度推导
- [ ] 我理解`holdout_eligible=false`对所有AMDAR必须保持
- [ ] 我理解Stage5 accepted也只是support-only，不是point truth

### ✅ 架构理解

- [ ] 我理解大框架：Stage1清洗→Stage2组织→Stage3验证→Stage4重构→Stage5匹配
- [ ] 我理解小阶段：Unified Plan的P0-P15实施步骤
- [ ] 我理解Stage3是pseudo-AMDAR闭环验证，不是真实匹配
- [ ] 我理解Stage5是真实AMDAR-ADS-B匹配，但当前接受率极低
- [ ] 我理解Stage6是时间不确定性建模，为Stage2时间相关性服务

### ✅ 优化策略理解

- [ ] 我理解置信度从9组件精简至4-5组件的必要性
- [ ] 我理解Stage2 QC优化是后续改善的基础（候选池扩大）
- [ ] 我理解分层接受策略：A/B/C三级而非单一阈值
- [ ] 我理解物理约束可以缩窄时间不确定性
- [ ] 我理解优化目标是充分利用数据，不是强行当真值

## 当前状态摘要

### Stage2 v6：ADS-B QC与Source Pool

```json
{
  "A_grade_legs": 127,
  "B_grade_legs": 2806,
  "C_grade_legs": 372274,
  "S0_source_pool": 13432,
  "S1_source_pool": 561,
  "S2_source_pool": 356793,
  "main_failure_reasons": {
    "failed_speed": 364811,
    "failed_sampling_gap": 219696,
    "failed_position_jump": 88312
  },
  "optimization_target": {
    "A_grade_legs": ">500",
    "S0_source_pool": ">30000"
  }
}
```

### Stage3 v7：Pseudo-AMDAR验证

```json
{
  "locked_test_cases": 4761,
  "selected_cases": 3906,
  "selected_coverage": 0.8204,
  "time_error_q90_s": 6.85,
  "wrong_leg_rate": 0.0031,
  "catastrophic_error_rate": 0.0025,
  "quality_gate_passed": true,
  "optimization_target": {
    "locked_test_cases": ">15000",
    "time_error_q90": "<5.5min"
  }
}
```

### Stage4 confidence v2：置信度分层

```json
{
  "tier_distribution": {
    "T0": 175,
    "T1": 3555,
    "T2": 114363,
    "T3": 227080,
    "T4": 86016
  },
  "tier_coverage_pct": {
    "T0": 0.04,
    "T1": 0.82,
    "T2": 26.52,
    "T3": 52.66,
    "T4": 19.95
  },
  "component_count": 9,
  "redundant_components": ["adsb_match_conf=0", "spatial_match_conf=0", "time_source_conf=batch_conf/0.85"],
  "optimization_target": {
    "component_count": "4-5",
    "T1_coverage_pct": "5-8%",
    "T2_coverage_pct": "35-40%"
  }
}
```

### Stage5 V3：AMDAR-ADS-B匹配

```json
{
  "total_batches": 56521,
  "candidate_batches": 23546,
  "accepted_batches": 7,
  "accepted_rows": 9,
  "acceptance_rate": 0.00012,
  "main_reject_reasons": {
    "no_candidate_leg": 32975,
    "best_cost_gt_1": 19642,
    "projected_time_after_batch_end_gt_60s": 3607
  },
  "optimization_target": {
    "accepted_batches": "500-1000",
    "acceptance_rate": "1-2%"
  }
}
```

### Stage6 time uncertainty v2：时间分布

```json
{
  "total_rows": 431008,
  "adsb_reconstructed_narrow": 9,
  "batch_interval_wide": 430999,
  "avg_time_uncertainty_s": 1350,
  "distribution_types": ["uniform", "triangular"],
  "optimization_target": {
    "adsb_reconstructed_narrow": "2000-5000",
    "avg_time_uncertainty_s": "900"
  }
}
```

## 优化方案核心要点

### 第一部分：置信度必要性分析（详见优化方案1.3-1.5节）

**保留的核心组件（4个）**：

1. `source_quality_conf`：数据源质量（替代固定source_conf）
2. `met_physics_conf`：气象物理置信度（优化高风速处理）
3. `batch_representativeness_conf`：批次代表性（合并batch_conf + time_source_conf）
4. `identity_completeness_conf`：身份完整性（从三档改为连续值）

**条件组件（仅Stage5 accepted）**：

5. `adsb_match_quality_conf`：ADS-B匹配质量（合并adsb_match_conf + spatial_match_conf）

**移除的冗余组件**：

- `time_source_conf`：完全重复batch_conf
- `adsb_leg_conf`：当前是未验证的prior，Stage5接受率仅0.012%
- `density_conf`：移到Stage10权重控制

### 第二部分：Stage2-6逐阶段优化（详见优化方案2.1-2.5节）

#### 激进优化目标对比

| 阶段 | 关键指标 | 当前 | 保守目标 | **激进目标** | 激进改善 |
|------|---------|------|---------|-------------|---------|
| **Stage2** | A级leg数量 | 127 | 500+ | **1,500-2,000** | **+1,081-1,473%** |
| **Stage2** | S0 source pool | 13,432 | 30,000+ | **50,000-60,000** | **+272-347%** |
| **Stage3** | time_error q90 | 6.85分钟 | 5.5分钟 | **4.5分钟** | **-34%** |
| **Stage4** | T1覆盖率 | 0.8% | 5-8% | **12-18%** | **+1,400-2,150%** |
| **Stage4** | T1+T2覆盖率 | 27.3% | 40-48% | **57-73%** | **+109-167%** |
| **Stage5** | 接受率 | 0.012% | 1-2% | **6-10%** | **+49,900-83,233%** |
| **Stage5** | 接受批次数 | 7 | 500-1,000 | **3,391-5,652** | **+48,343-80,614%** |
| **Stage6** | 窄分布(<5min) | 0.002% | 0.5-1.2% | **4.2-8.1%** | **+2,100-4,050倍** |
| **Stage6** | 平均时间不确定性 | 1,350秒 | 900秒 | **550秒** | **-59%** |
| **端到端** | Holdout RMSE | baseline | -15% | **-35%** | **2.3倍改善** |

#### Stage2优化：激进ADS-B QC改进

**当前问题**：
- A级仅127条（目标>500未达成）
- 速度检查过严：相邻点>300 m/s直接拒绝
- 采样间隔固定：300秒统一阈值
- 组件评分一票否决

**激进策略**：
1. 速度检查改为分层（考虑时间跨度和飞行阶段）
2. 采样间隔分层阈值（LVR=600s, ASC=240s, DES=300s）
3. 组件化评分改为加权（85分→A，65分→B）
4. 缺口桥接（允许15分钟内小段低质量桥接）

**预期**：A级leg 127→**1,500-2,000**，S0 pool 13,432→**50,000-60,000**

#### Stage3优化：扩展验证与置信度预测

**激进策略**：
1. 扩大case到50,000（当前15,000）
2. 多时间尺度验证（5min/15min/30min三档）
3. 训练置信度预测器（R²>0.75）

**预期**：locked test time_error_q90从6.85分钟→**4.5分钟**

#### Stage4优化：精简置信度+动态阈值+高风速保留

**激进策略**：
1. 实施精简置信度体系（9组件→4-5组件）
2. 基于pseudo locked test动态标定T1/T2阈值
3. 高风速智能保留（GFS对比+邻近支持，保留70-80%）

**预期**：T1覆盖0.8%→**12-18%**，T2覆盖26.5%→**45-55%**，高风速保留~3,200条

#### Stage5优化：分层接受+时间宽容+多候选

**激进策略**：
1. 分层接受：A(cost<0.5)、B(cost<1.5)、C(cost<3.0)
2. 时间投影从±60秒→**±180秒**
3. 保留top-3候选加权混合（ambiguity_margin>1.2）

**预期**：接受率0.012%→**6-10%**，接受批次7→**3,391-5,652**

#### Stage6优化：物理约束+混合分布+多候选融合

**激进策略**：
1. 单点批次利用飞行动力学：300秒→**120-150秒**
2. 小批次（2-4点）利用沿轨距离：600秒→**300-450秒**
3. 多候选加权混合分布（gaussian_mixture）

**预期**：窄分布9行→**18,000-35,000行**，平均不确定性1,350秒→**550秒**

### 第三部分：实施路线图（详见优化方案3.1-3.3节）

**7个实施阶段**（总工时62-78小时）：

1. **Stage2 ADS-B QC优化**（8-12h）：最高优先级，是后续基础
2. **Stage3 Pseudo扩展**（10-14h）：高优先级，验证和标定
3. **Stage4 置信度精简**（12-16h）：高优先级，核心改造
4. **Stage5 匹配优化**（10-12h）：中优先级，扩大覆盖
5. **Stage6 时间建模**（8-10h）：中优先级，精细化
6. **端到端验证**（6-8h）：最高优先级，质量门
7. **迭代优化**（4-6h）：中优先级，微调参数

**依赖关系**：阶段1→阶段2→阶段3→阶段4→阶段5→阶段6→阶段7

**质量门**：每个阶段都有明确的质量检查，未通过则回退

## 强制规则重申

### ❌ 绝对禁止的操作

```python
# 真值边界
FORBIDDEN = [
    '把任何AMDAR的effective_strict_truth改为true',
    '把任何AMDAR的holdout_eligible改为true',
    '通过base_support_conf推导strict truth资格',
    '为了提高覆盖率降低strict truth标准',
]

# 时间语义
FORBIDDEN += [
    '把batch_end_time_utc当作逐点观测时间',
    '把estimated_time_q50当作strict point truth',
    '忽略time_uncertainty_s直接使用单点时间',
    '把Stage5 accepted当作point observation',
]

# 匹配质量
FORBIDDEN += [
    '把Stage5 rejected rows伪造成accepted',
    '接受identity_conflict的匹配',
    '放宽到无法追溯的匹配标准',
]

# 评估混淆
FORBIDDEN += [
    '用support数据做holdout评估',
    '混淆pseudo验证和真实验证',
    '不报告置信区间和样本数',
]
```

### ✅ 必须保持的不变量

```python
INVARIANTS = {
    'turb_strict_truth_count': 175,       # 固定
    'turb_review_count': 6,               # 固定
    'amdar_strict_truth_count': 0,        # 固定，永远为0
    'amdar_holdout_eligible_count': 0,    # 固定，永远为0
}

# 每个阶段结束后必须验证
def validate_invariants(output_data):
    assert count_turb_strict_truth(output_data) == 175
    assert count_amdar_strict_truth(output_data) == 0
    assert count_amdar_holdout_eligible(output_data) == 0
```

## 推荐开场话术

当你准备好开始实施时，请用以下话术确认理解：

```text
我已完整阅读以下文档：

1. centralized_v1总交接（项目边界）
2. Plan4实跑报告（AMDAR时间语义）
3. Plan4综合评估（分层置信度路线）
4. Unified Plan（P0-P15阶段划分）
5. Stage3 v7状态（pseudo验证已达标）
6. Stage5 V3状态（匹配接受率0.012%）
7. Stage6 v2状态（时间建模保守）
8. Stage2-6优化方案（本次任务核心）

我理解以下核心边界：

- TURB 175条是唯一strict truth，AMDAR 0条strict truth且永远为0
- AMDAR时间是批次时间不是逐点时间，estimated_time_q50不是point truth
- Stage5 accepted也是support-only，不能进入holdout
- 优化目标是充分利用数据但不强行当真值

我理解优化方案的核心策略：

- 置信度从9组件精简至4-5组件，消除冗余
- Stage2 QC改进是基础，影响后续所有阶段的候选池
- 分层接受策略（A/B/C三级）替代单一阈值
- 物理约束缩窄时间不确定性
- 7个实施阶段，每阶段有质量门和回退机制

我理解预期改善目标：

- Holdout RMSE相对改善 > 15%
- T1+T2覆盖率从27%提升至40%+
- Stage5接受率从0.012%提升至1-2%
- 平均时间不确定性从1,350秒降至900秒

我准备从阶段1（Stage2 ADS-B QC优化）开始实施，预计工时8-12小时。请确认是否开始。
```

## 输出文件结构

实施过程中将生成以下文件结构：

```text
/data/LFT-W02_data/pengxu/优化/数据处理/
├── stage2_adsb_qc_v7_optimized_20260706/
│   ├── adsb_leg_quality_components_v7.parquet
│   ├── adsb_leg_readiness_summary_v7.json
│   └── stage2_v6_to_v7_comparison.json
├── stage3_pseudo_amdar_v8_optimized_20260706/
│   ├── pseudo_amdar_v8_calibration_report.json
│   ├── confidence_predictor_model.pkl
│   └── multiscale_validation_report.json
├── stage4_confidence_v3_optimized_20260706/
│   ├── amdar_confidence_components_v3.parquet
│   ├── confidence_tier_summary_v3.json
│   └── component_correlation_matrix.json
├── stage5_v4_matching_optimized_20260706/
│   ├── amdar_adsb_match_v4.parquet
│   ├── amdar_adsb_match_diagnostics_v4.json
│   └── multi_candidate_summary.json
├── stage6_time_uncertainty_v3_optimized_20260706/
│   ├── amdar_time_uncertainty_v3.parquet
│   ├── time_uncertainty_summary_v3.json
│   └── distribution_type_statistics.json
└── stage4_baseline_optimized_v3_20260706/
    ├── holdout_evaluation_report.json
    ├── tier_contribution_analysis.json
    ├── gfs_comparison_statistics.json
    └── optimization_summary_20260706.md
```

## 成功标准

优化实施成功需满足以下所有标准：

### 技术指标（激进目标）

- [ ] **Holdout RMSE相对改善 ≥ 30%**（目标35%，保底30%）
- [ ] Holdout RMSE不恶化 > 2%（安全边界）
- [ ] **T1+T2覆盖率 ≥ 55%**（目标57-73%，保底55%）
- [ ] **Stage5接受率 ≥ 5%**（目标6-10%，保底5%）
- [ ] **窄时间分布(<5min) ≥ 3.5%**（目标4.2-8.1%，保底3.5%）
- [ ] **平均时间不确定性 ≤ 650秒**（目标550秒，保底650秒）
- [ ] GFS风速差异标准差 < 6 m/s（目标5.5 m/s）
- [ ] 伪梯度发生率 < 2%（目标1.5%）
- [ ] 无灾难性失败（max_frame_rmse < 50 m/s）

### 分阶段里程碑

**阶段1（Stage2）里程碑**：
- [ ] A级leg ≥ 1,200（目标1,500-2,000）
- [ ] S0 source pool ≥ 40,000（目标50,000-60,000）
- [ ] 速度失败率 < 25%（当前97.8%）

**阶段3（Stage4）里程碑**：
- [ ] T1覆盖率 ≥ 10%（目标12-18%）
- [ ] T2覆盖率 ≥ 42%（目标45-55%）
- [ ] 高风速保留 ≥ 2,800条（目标3,200条）

**阶段4（Stage5）里程碑**：
- [ ] 接受批次数 ≥ 2,500（目标3,391-5,652）
- [ ] 候选池 ≥ 50,000批次
- [ ] 分层接受覆盖：A级≥300, B级≥1,200, C级≥1,000

**阶段5（Stage6）里程碑**：
- [ ] 窄分布行数 ≥ 12,000（目标18,000-35,000）
- [ ] 中等分布覆盖 ≥ 45%
- [ ] 单点批次平均不确定性 ≤ 180秒

### 不变量检查

- [ ] TURB strict truth = 175（不变）
- [ ] AMDAR strict truth = 0（不变）
- [ ] AMDAR holdout_eligible全部为false（不变）
- [ ] 所有置信度可追溯到组成组件

### 文档完整性

- [ ] 每个阶段都有输出文件和摘要JSON
- [ ] 质量门通过情况有记录
- [ ] 优化前后对比清晰（包含详细指标表）
- [ ] 下一步建议明确

### 保底回退标准

如果无法达到激进目标，但满足以下保守标准，也算成功：

- [ ] Holdout RMSE改善 ≥ 15%（保守目标）
- [ ] T1+T2覆盖率 ≥ 40%
- [ ] Stage5接受率 ≥ 1%
- [ ] 平均时间不确定性 ≤ 900秒

---

**交接文档版本**：v2.0 (激进优化版)  
**生成日期**：2026-07-06  
**配套方案**：amdar_stage2_to_6_optimization_plan_20260706.md  
**预计总工时**：62-78小时（7个阶段）  
**核心目标**：Holdout RMSE改善**35%**，T1+T2覆盖率**57-73%**，充分利用但不强行当真值  
**改善倍数**：相比保守目标，关键指标改善幅度提升**2-3倍**
