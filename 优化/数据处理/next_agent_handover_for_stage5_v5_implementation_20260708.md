# 给下一个智能体的交接话术：Stage5 V5 实施

生成时间：2026-07-08  
版本：v1.0  
任务类型：Stage5 V5 real AMDAR-ADS-B matching 实施

---

## 项目概览

你接手的是 `/data/LFT-W02_data/pengxu` 下的 centralized_v1 三维水平风场重构项目。当前任务是**实施 Stage5 V5 optimization**，以提升 AMDAR-ADS-B 匹配接受率从当前的 0.152% 提升到至少 1%。

### 当前状态

- **大框架阶段**：Stage5 real AMDAR-ADS-B matching
- **当前版本**：V4 已完成，V5 待实施
- **优化计划阶段**：仍在优化计划 phase 4（Stage5 匹配），不是 phase 5（Stage6 时间建模）

### Stage5 V4 核心结果

```json
{
    "amdar_batches": 56521,
    "accepted_batches": 86,
    "accepted_rows": 118,
    "acceptance_rate": 0.00152,
    "acceptance_rate_pct": 0.152,
    "diagnostic_gate": "PASSED",
    "target_gate": "FAILED",
    "target_requirement": ">=1% or >=500 batches",
    "main_bottlenecks": {
        "no_candidate": "27775 batches (49.1%)",
        "best_cost_gt_3": "21197 batches (73.7% of candidates rejected)",
        "best_cost_p10": 24.82,
        "validation_c_grade_upper_bound": 3.0
    }
}
```

### V5 目标

- **保守目标**：接受率 >= 1%（>= 500 批次）
- **平衡目标**：接受率 >= 1.8%（>= 1000 批次）
- **激进目标**：接受率 >= 3.5%（>= 2000 批次）
- **最低要求**：Safety gate 通过，不恶化 V4 结果

---

## 必读文档清单

### 核心文档（必读，按顺序）

1. **`stage5_v4_comprehensive_analysis_and_v5_plan_20260708.md`**（本次生成）
   - 用途：Stage5 V4 结果深度分析 + V5 方案评估 + 详细实施路线图
   - 重点：第一、二、三部分（V4 分析、V5 评估、实施路线图）
   - 阅读时间：30-40 分钟

2. **`stage5_v5_optimization_plan_summary.md`**
   - 用途：V5 优化方案原始版本
   - 重点：四阶段流程、分层身份等级、质量门
   - 阅读时间：15-20 分钟

3. **`stage5_v4_results_analysis_and_next_steps.md`**
   - 用途：V4 运行结果和质量门
   - 重点：拒绝原因统计、接受模式特征
   - 阅读时间：10-15 分钟

4. **`next_agent_handover_after_stage5_v4.md`**
   - 用途：V4 交接话术
   - 重点：输出文件位置、运行口径
   - 阅读时间：10 分钟

### 背景文档（选读，需要时查阅）

5. **`amdar_stage2_to_6_optimization_plan_20260706.md`**
   - 用途：Stage2-6 总优化方案
   - 何时读：需要理解更广泛的优化背景时

6. **`/data/LFT-W02_data/pengxu/workflow/centralized_v1_docs/new_window_project_handover_20260529/centralized_v1_ultimate_summary_20260626.md`**
   - 用途：项目总边界和 strict truth 定义
   - 何时读：需要确认数据边界规则时

7. **`优化/teacher_reports/plan4.md`**
   - 用途：AMDAR 时间语义说明
   - 何时读：需要理解 AMDAR 批次时间含义时

8. **`stage4_confidence_v3_next_window_optimized_20260708/next_agent_handover_after_stage4_v3.md`**
   - 用途：Stage4 v3 置信度分层
   - 何时读：需要理解候选的置信度层级时

9. **`stage3_pseudo_amdar_v8_optimized_20260707/stage3_v8_results_analysis_and_next_steps.md`**
   - 用途：Stage3 v8 伪验证结果
   - 何时读：需要理解伪验证质量门标准时

---

## 核心理解要点

### 关键事实

1. **AMDAR 全部 support-only**
   - AMDAR strict truth count = 0（固定，永远为 0）
   - AMDAR holdout eligible = false（全部，永远）
   - Stage5 accepted 也是 support-only，不是 point truth
   - `estimated_time_utc` 是 Stage6 时间分布种子，不是精确时间

2. **V4 结果真实但未达标**
   - 接受率 0.152% 不是门控过严，而是候选可用性问题
   - 49.1% AMDAR 批次无候选（no_candidate_leg=27775）
   - 有候选的批次中，73.7% 因 best_cost>3 被拒绝
   - best_cost p10=24.82，远高于 C 级上限 3.0

3. **不能通过放宽门控解决**
   - 达到 500 批次需要 cost>20、cross_track>10km
   - 这超出 Stage3 v8 验证范围，会破坏质量边界
   - V4 尝试的弱身份扩展（tail_date_unique）失败：1910 候选，0 接受

4. **正确路径是修复候选可用性**
   - 审计航班号归一化失败
   - 审计日期对齐问题（UTC 跨日）
   - 审计时间窗口问题
   - 通过系统性修复扩大候选池

### V5 四阶段流程

```
Phase 1: 对齐审计（8-12h）
  目标：量化 no_candidate 的分解原因，评估各修复策略的潜在收益
  输出：alignment_audit_results_and_next_steps_v5.md
  决策点：如果潜在候选 < 5000，转向 Stage2 QC 优化

Phase 2: 候选策略实施（6-8h）
  目标：实施 I0/I1/I2/I3 分层身份等级匹配
  输出：candidate_policy_v5_summary.json
  决策点：如果新增候选 < 5000，调整策略

Phase 3: 伪验证门（12-16h）
  目标：在 Stage3 pseudo-AMDAR 中验证 V5 候选策略
  输出：pseudo_validation_v5_analysis_and_gate_check.md
  决策点：如果 wrong-leg rate > 2%，禁用问题身份等级

Phase 4: 真实 V5 匹配（10-14h）
  目标：运行真实 AMDAR-ADS-B matching V5
  输出：stage5_v5_results_analysis_and_next_steps.md
  决策点：如果 target gate 未通过，进入保守 Stage6 诊断分支
```

### 分层身份等级设计

| 等级 | 匹配逻辑 | 可接受等级 | 用途 | Wrong-leg 目标 |
|------|---------|-----------|------|---------------|
| **I0** | exact tail+flight+date | A/B/C | 当前 V4 使用 | <=0.5% |
| **I1** | exact tail+flight, date±1 | B/C | 修复 UTC 跨日 | <=1.5% |
| **I2** | 归一化后 tail+flight+date | B/C | 修复航班号归一化 | <=2.0% |
| **I3** | exact tail+date, unique flight | C only | 处理航班号缺失 | <=5.0% |
| **I4** | tail+time+spatial, 多航班 | 不接受 | 诊断用 | N/A |

**关键规则**：
- 每个候选必须记录 `identity_level` 和 `identity_evidence`
- I1/I2/I3 必须通过伪验证质量门才能在真实匹配中启用
- I3 最多占 C 级接受的 20%
- 禁止接受 `identity_conflict` 候选

---

## 实施路线图

### Phase 1: 对齐审计（8-12 小时）

#### 目标

量化以下问题的规模：
1. 27,775 个 no_candidate 批次的分解原因
2. 航班号归一化覆盖率
3. 日期±1 天能增加的候选数
4. 时间窗口扩展的潜在收益
5. 几何失败的组件分解

#### 输入数据

```python
inputs_phase1 = {
    'stage5_v4_outputs': {
        'batch_diagnostics': '/data/LFT-W02_data/pengxu/优化/数据处理/stage5_v4_matching_optimized_20260708/stage5_v4/amdar_adsb_batch_diagnostics_v4.parquet',
        'reject_table': '/data/LFT-W02_data/pengxu/优化/数据处理/stage5_v4_matching_optimized_20260708/stage5_v4/amdar_adsb_reject_v4.parquet',
    },
    'amdar_batch_table': '/data/LFT-W02_data/pengxu/优化/数据处理/stage5_v4_matching_optimized_20260708/stage5_v4/amdar_batch_base_v4.parquet',
    'adsb_leg_table': '/data/LFT-W02_data/pengxu/优化/数据处理/stage2_adsb_qc_v7_optimized_20260706/adsb_leg_quality_components_v7.parquet',
    'stage4_confidence': '/data/LFT-W02_data/pengxu/优化/数据处理/stage4_confidence_v3_next_window_optimized_20260708/stage4_v3/amdar_confidence_components_v3.parquet',
}
```

#### 任务清单

```markdown
□ Task 1.1: 创建审计脚本框架
  - 文件：amdar_unified_stage5_v5_alignment_audit_20260708.py
  - 时间：2h

□ Task 1.2: no_candidate 分解审计
  - 逐层检查：tail 存在性 → date 匹配 → flight 匹配 → 过滤 → 时间重叠
  - 时间：3-4h

□ Task 1.3: 航班号归一化审计
  - 提取 AMDAR/ADS-B pattern
  - 评估当前覆盖率
  - 建议新规则
  - 时间：2-3h

□ Task 1.4: 日期对齐审计
  - 统计±1 天增益
  - 识别跨 UTC 零点批次
  - 时间：1-2h

□ Task 1.5: 几何失败量化
  - 分解 cost 组件贡献
  - 时间：1-2h

□ Task 1.6: 生成审计报告
  - 综合发现，量化潜在收益
  - 决策建议
  - 时间：1h
```

#### 输出文件

```
/data/LFT-W02_data/pengxu/优化/数据处理/stage5_v5_alignment_audit_optimized_20260708/
├── no_candidate_decomposition_v5.json
├── flight_normalization_audit_v5.parquet
├── date_shift_candidate_audit_v5.parquet
├── time_window_candidate_audit_v5.parquet
├── geometry_failure_quantiles_v5.json
└── alignment_audit_results_and_next_steps_v5.md
```

#### 决策点 1

```python
# 审计完成后，评估潜在收益
if total_potential_candidates >= 10000:
    decision = "继续 Phase 2，预期可达保守/平衡目标"
elif total_potential_candidates >= 5000:
    decision = "谨慎继续 Phase 2，预期可达最低/保守目标"
else:
    decision = "暂停 V5，转向 Stage2 QC 优化（扩大 ADS-B leg 候选池）"
```

### Phase 2: 候选策略实施（6-8 小时）

#### 前提条件

- Phase 1 完成
- 潜在候选 >= 5000 batches
- 审计报告建议继续

#### 任务清单

```markdown
□ Task 2.1: 实施身份匹配层次结构
  - I0/I1/I2/I3 匹配逻辑
  - Cost penalty 机制
  - 时间：2h

□ Task 2.2: 实施 I1 日期偏移策略
  - 日期±1 天扩展
  - UTC 跨零点检测
  - 时间：1-2h

□ Task 2.3: 实施 I2 航班号归一化
  - 应用 Phase 1 规则
  - 时间：2-3h

□ Task 2.4: 实施 I3 tail-date-unique
  - 检查唯一性
  - 默认关闭
  - 时间：1-2h

□ Task 2.5: 候选表质量检查
  - 验证 identity_level 完整
  - 验证无 identity_conflict
  - 时间：1h
```

#### 关键参数

```python
# I1: 日期偏移
date_shift_config = {
    'shift_range': [-1, 0, +1],
    'cost_penalty': 0.2,
    'eligible_grades': ['B', 'C'],
}

# I2: 航班号归一化
flight_norm_config = {
    'rules': [
        {'amdar': r'^CA(\d+)$', 'adsb': r'^CCA\1$'},  # 示例
        # 根据 Phase 1 审计补充
    ],
    'cost_penalty': 0.1,
    'eligible_grades': ['B', 'C'],
}

# I3: Tail-date unique
tail_date_unique_config = {
    'enabled': False,  # 默认关闭，Phase 3 后决定
    'cost_penalty': 0.3,
    'eligible_grades': ['C'],
    'max_fraction': 0.20,
}
```

#### 输出文件

```
/data/LFT-W02_data/pengxu/优化/数据处理/stage5_v5_candidate_policy_optimized_20260708/
├── candidate_leg_table_v5.parquet
├── candidate_policy_v5_summary.json
└── identity_level_distribution_v5.json
```

#### 决策点 2

```python
# 候选策略完成后
if new_candidates_vs_v4 >= 5000:
    decision = "继续 Phase 3"
else:
    decision = "审查 Phase 1 结论，调整策略或转向 Plan B"
```

### Phase 3: 伪验证门（12-16 小时）

#### 前提条件

- Phase 2 完成
- 新增候选 >= 5000 batches

#### 任务清单

```markdown
□ Task 3.1: 修改 Stage3 pseudo-AMDAR 脚本
  - 集成 I0/I1/I2/I3 策略
  - 分级质量门
  - 时间：3-4h

□ Task 3.2: 在 validation split 上调优
  - 调整 cost penalty
  - 调整 ambiguity margin
  - 时间：4-6h

□ Task 3.3: 在 locked test 上报告
  - 分 I0/I1/I2/I3 报告
  - 不调优
  - 时间：2-3h

□ Task 3.4: 质量门评审
  - 检查各级别是否通过
  - 决定启用哪些级别
  - 时间：1-2h

□ Task 3.5: 生成分析文档
  - 时间：1-2h
```

#### 质量门标准

```python
quality_gates_phase3 = {
    'overall': {
        'selected_coverage': '>=75%',
        'wrong_leg_rate': '<=1% (target) or <=2% (max)',
        'catastrophic_error_rate': '<3%',
    },
    'I0': {'wrong_leg': '<=0.5%', 'time_error_q90': '<=300s'},
    'I1': {'wrong_leg': '<=1.5%', 'time_error_q90': '<=450s', 'min_cases': 500},
    'I2': {'wrong_leg': '<=2.0%', 'time_error_q90': '<=450s', 'min_cases': 500},
    'I3': {'wrong_leg': '<=5.0%', 'time_error_q90': '<=600s', 'min_cases': 200},
}
```

#### 输出文件

```
/data/LFT-W02_data/pengxu/优化/数据处理/stage5_v5_pseudo_validation_optimized_20260708/
├── pseudo_validation_v5_report.json
├── pseudo_validation_by_identity_level_v5.json
├── quality_gate_check_v5.json
└── pseudo_validation_v5_analysis_and_gate_check.md
```

#### 决策点 3

```python
# 伪验证完成后
enabled_levels = []
if I0_passed: enabled_levels.append('I0')
if I1_passed: enabled_levels.append('I1')
if I2_passed: enabled_levels.append('I2')
if I3_passed: enabled_levels.append('I3')

if len(enabled_levels) == 0:
    decision = "ABORT V5，审查数据质量"
elif len(enabled_levels) >= 2:
    decision = "继续 Phase 4，启用通过的级别"
else:
    decision = "仅启用 I0，降低预期到 Tier 1"
```

### Phase 4: 真实 V5 匹配（10-14 小时）

#### 前提条件

- Phase 3 完成
- 至少 I0 通过质量门

#### 任务清单

```markdown
□ Task 4.1: 创建 Stage5 v5 匹配脚本
  - 基于 v4 修改
  - 集成启用的身份等级
  - 时间：3-4h

□ Task 4.2: 运行匹配
  - 25 slice / 25 workers
  - 时间：3-4h

□ Task 4.3: 质量检查
  - Safety gate
  - Target gate
  - 时间：2-3h

□ Task 4.4: 结果分析文档
  - V4 vs V5 对比
  - 身份等级贡献
  - 下一步建议
  - 时间：2-3h
```

#### 运行口径

```bash
POLARS_MAX_THREADS=25 /data/LFT-W02_data/pengxu/.conda/envs/windy310/bin/python \
  /data/LFT-W02_data/pengxu/优化/数据处理/amdar_unified_stage5_v5_matching_20260708.py \
  --out-dir /data/LFT-W02_data/pengxu/优化/数据处理/stage5_v5_matching_optimized_20260708 \
  --slice-count 25 --workers 25
```

#### 质量门检查

```python
safety_gate_v5 = {
    'stage3_pseudo_validation_passed': True,
    'stage4_v3_gate_passed': True,
    'batch_diagnostics_complete': True,
    'accepted_rows_traceable': True,
    'no_identity_conflict': True,
    'amdar_strict_truth_eq_0': True,
    'amdar_holdout_eligible_eq_0': True,
    'all_accepted_support_only': True,
}

target_gate_v5 = {
    'accepted_batches_ge_500': '?',
    'accepted_fraction_ge_1pct': '?',
    'A_B_C_all_present': '?',
}
```

#### 输出文件

```
/data/LFT-W02_data/pengxu/优化/数据处理/stage5_v5_matching_optimized_20260708/
├── stage5_v5/
│   ├── amdar_adsb_match_v5.parquet
│   ├── amdar_adsb_reject_v5.parquet
│   ├── amdar_adsb_batch_diagnostics_v5.parquet
│   └── amdar_adsb_match_diagnostics_v5.json
├── stage5_v5_results_analysis_and_next_steps.md
└── next_agent_handover_after_stage5_v5.md
```

#### 决策点 4（最终）

```python
if safety_gate_passed and target_gate_passed:
    decision = "V5 成功，进入 Stage6 目标分支"
    stage6_mode = "target"
elif safety_gate_passed and not target_gate_passed:
    decision = "V5 部分成功，进入 Stage6 保守诊断分支"
    stage6_mode = "conservative_diagnostic"
    note = "Explicitly report Stage5 target miss"
else:
    decision = "V5 失败，回退到 V4"
    action = "Fix safety violations, review implementation"
```

---

## 风险控制与回退策略

### 风险矩阵

| 风险 | 检测 | 缓解 | 回退 |
|------|------|------|------|
| **Phase 1 潜在候选不足** | total < 5000 | 转向 Stage2 QC | 暂停 V5 |
| **Phase 3 wrong-leg 率高** | I1/I2/I3 > 2% | 禁用问题等级 | 仅用通过的等级 |
| **Phase 4 target gate 未过** | batches < 500 | 保守 Stage6 | 报告 target miss |
| **Phase 4 safety gate 未过** | 边界破坏 | 立即停止 | 回退到 V4 |

### 不变量检查

每个 Phase 完成后必须验证：

```python
def validate_invariants():
    assert amdar_strict_truth_count == 0
    assert amdar_holdout_eligible_count == 0
    assert all(accepted.usage_role == 'support_only')
    assert all(accepted.identity_conflict == False)
```

---

## 成功标准

| 级别 | 接受批次 | 接受率 | Safety | Target | 后续行动 |
|------|---------|--------|--------|--------|---------|
| **Tier 1** | >= 86 | >= 0.15% | ✓ | ✗ | 保守 Stage6 诊断 |
| **Tier 2** | >= 500 | >= 1.0% | ✓ | ✓ | 目标 Stage6 |
| **Tier 3** | >= 1000 | >= 1.8% | ✓ | ✓ | 目标 Stage6（超预期）|
| **Tier 4** | >= 2000 | >= 3.5% | ✓ | ✓ | 目标 Stage6（激进成功）|

**最低要求**：Tier 1  
**推荐目标**：Tier 2

---

## 推荐开场话术

当你准备开始实施时，请确认：

```
我已阅读以下核心文档：
1. stage5_v4_comprehensive_analysis_and_v5_plan_20260708.md
2. stage5_v5_optimization_plan_summary.md
3. stage5_v4_results_analysis_and_next_steps.md
4. next_agent_handover_after_stage5_v4.md

我理解以下核心事实：
- Stage5 V4 接受率 0.152%，未达 1% 目标
- 主要瓶颈是候选可用性（49.1% 无候选）和几何质量（best_cost p10=24.82）
- 不能通过放宽几何门控解决
- V5 采用四阶段流程：审计 → 策略 → 伪验证 → 真实匹配
- AMDAR 永远 support-only，0 条 strict truth

我理解 V5 四阶段实施路线：
- Phase 1: 对齐审计（8-12h）- 量化潜在收益
- Phase 2: 候选策略（6-8h）- 实施 I0/I1/I2/I3
- Phase 3: 伪验证门（12-16h）- 分级质量门
- Phase 4: 真实匹配（10-14h）- 运行并分析

我理解关键决策点：
- Milestone 1: 潜在候选 < 5000 → 转 Stage2 优化
- Milestone 3: wrong-leg > 2% → 禁用问题等级
- Milestone 4: target gate 未过 → 保守 Stage6

我准备从 Phase 1（对齐审计）开始。请确认。
```

---

**文档版本**：v1.0  
**生成日期**：2026-07-08  
**预期工时**：36-50 小时  
**推荐启动**：Phase 1 对齐审计  
**后续文档**：`stage5_v5_results_analysis_and_next_steps.md`（Phase 4 完成后生成）

