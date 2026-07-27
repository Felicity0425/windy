# Stage5 V4 综合分析与 V5 优化方案评估

生成时间：2026-07-08  
文档版本：v1.0  
作者：AI Assistant

---

## 执行摘要

### Stage5 V4 结果概述

当前 Stage5 v4 real AMDAR-ADS-B matching 已完成运行，结果如下：

**核心指标**：
- AMDAR 总批次：56,521
- 接受批次：86（0.152%）
- 接受行数：118
- 分层接受：A=7, B=41, C=38
- 诊断门：**通过 ✓**
- 目标门：**未通过 ✗**

**关键发现**：
- 候选池覆盖率：28,746/56,521（50.9%）
- 主要拒绝原因：
  - `no_candidate_leg`：27,775 批次（49.1%）
  - `best_cost_gt_3`：21,197 批次（73.7% 有候选但被拒绝）
  - `projected_time_after_batch_end_gt_180s`：3,871 批次
- 候选但被拒绝的 `best_cost` p10：24.82（远高于 C 级上限 3.0）

**核心结论**：Stage5 v4 结果真实且可追溯，但距离目标（500+ 批次，1-2% 接受率）有显著差距。差距根源不是匹配门控过严，而是**候选可用性和数据对齐问题**。

### V5 优化方案评估

已有的 Stage5 v5 优化计划（`stage5_v5_optimization_plan_summary.md`）提出了**正确的优化路径**：

✅ **核心原则正确**：不通过放宽几何门控来提升接受率，而是通过审计和修复候选可用性问题  
✅ **四阶段路线清晰**：对齐审计 → 候选策略扩展 → 伪验证门 → 真实 v5 匹配  
✅ **质量边界严格**：AMDAR 保持 support-only，分层身份等级，伪验证必须通过  
✅ **可追溯性强**：每个候选记录身份等级、证据字段、歧义诊断

**评估结论**：V5 优化方案**可用且科学**，但需要补充具体实施细节和风险缓解措施。

---

## 第一部分：Stage5 V4 结果深度分析

### 1.1 接受率分析：为什么只有 0.152%？

#### 漏斗分析

```
AMDAR 总批次：56,521
    ↓
有候选批次：28,746（50.9%）← 损失 27,775（49.1%）
    ↓
评估候选批次：28,746（100%）
    ↓
通过几何门控：86（0.30%）← 损失 28,660（99.70%）
    ↓
最终接受：86（0.152%）
```

**关键瓶颈识别**：

1. **瓶颈 1：候选池覆盖不足**（49.1% 无候选）
   - `no_candidate_leg=27,775`
   - 可能原因：
     - 航班号/尾号归一化失败（AMDAR vs ADS-B 不同命名规则）
     - 日期对齐问题（UTC 跨日、时区、日期格式）
     - ADS-B 覆盖缺口（某些航空公司、某些时间窗口）
     - 飞行阶段/边界框/高度过滤过严

2. **瓶颈 2：几何匹配质量差**（99.7% 有候选但被拒）
   - `best_cost_gt_3=21,197`（占有候选批次的 73.7%）
   - `best_cost` p10=24.82，远高于 C 级上限 3.0
   - 说明：即使有候选，AMDAR 批次与 ADS-B 轨迹在空间上距离很远
   - 可能原因：
     - 候选身份正确但时间窗口错位
     - 候选身份错误（wrong leg 混入）
     - AMDAR 批次时间区间估计不准
     - ADS-B 轨迹片段化（缺少关键时间段的点）

#### 与 Stage3 V8 伪验证对比

Stage3 v8 pseudo-AMDAR 验证（闭环测试）：
- Selected case count：14,607
- Matched case count：14,533（99.49%）
- Wrong leg rate：0.51%
- Time error q90：4.86 秒

Stage5 v4 real AMDAR matching：
- 有候选批次：28,746
- 接受批次：86（0.30%）
- 接受率是伪验证的 **1/330**

**差异根源**：
- 伪验证使用的是**已知正确的 ADS-B 轨迹**生成的伪 AMDAR 批次
- 真实匹配需要从**未知身份的 AMDAR 批次**反向找到正确的 ADS-B 轨迹
- 身份匹配（tail/flight/date）是主要障碍，而非几何匹配

### 1.2 候选策略分析

#### V4 使用的候选策略

```python
# Stage5 v4 候选身份策略
identity_levels = {
    'strong_tail_flight_date': {
        'match': 'exact tail_norm + flight_norm + service_date_utc',
        'eligible_grades': ['A', 'B', 'C'],
        'v4_candidate_rows': 43481,
        'v4_accepted_rows': 86,  # 全部来自此级别
    },
    'tail_date_unique_flight_no_exact_match': {
        'match': 'exact tail_norm + service_date_utc, unique flight',
        'eligible_grades': ['C'],
        'v4_candidate_rows': 1910,
        'v4_accepted_rows': 0,  # 未接受任何
        'cost_q1': 25.55,  # 几何质量差
    }
}
```

**V4 弱身份扩展的失败**：
- 新增 1,910 候选行，但 `cost` q1 就高达 25.55
- 说明：弱身份候选虽然在 tail+date 层面唯一，但空间位置与 AMDAR 批次不匹配
- 结论：简单的弱身份扩展**不是安全路径**

#### V4 候选 Stage4 置信度分布

```python
candidate_stage4_tier_counts = {
    'T2': 30161,  # 66.4%
    'T1': 9072,   # 20.0%
    'T4': 3142,   # 6.9%
    'T3': 3016,   # 6.6%
}
```

- T1+T2 占 86.4%，说明候选池质量很高
- 但接受率只有 0.26%（86/28746），说明问题不在 Stage4 置信度

### 1.3 拒绝原因分解

#### 详细拒绝原因统计

```python
reject_reason_counts = {
    'no_candidate_leg': 27775,          # 49.1% - 主要瓶颈 1
    'best_cost_gt_3': 21197,            # 37.5% - 主要瓶颈 2
    'projected_time_after_batch_end_gt_180s': 3871,  # 6.8%
    'monotonic_violation': 1909,        # 3.4%
    'stage4_t4_not_accepted_for_reconstruction': 1599,  # 2.8%
    'cross_track_q90_gt_1_5km': 32,     # 0.06%
    'stage1_qc_blocked_rows_present': 32,  # 0.06%
    'vertical_q90_gt_800m': 20,         # 0.04%
}
```

**关键观察**：
- 几何指标拒绝（`cross_track_q90_gt_1_5km`、`vertical_q90_gt_800m`）只占 0.1%
- 说明：对于通过 `best_cost<=3` 的候选，几何门控并不严格
- 真正的问题是 **99%+ 的候选 `best_cost` 就超过 3.0**

#### 时间投影问题

`projected_time_after_batch_end_gt_180s`：3,871 批次

- 说明：这些候选的重建时间超出 AMDAR `batch_end_time_utc` 后 180 秒
- 可能原因：
  - AMDAR 批次时间区间估计过短
  - ADS-B 轨迹时间对齐错误
  - 飞行速度先验不准确

### 1.4 接受批次特征分析

#### 接受批次的质量分布

```python
accepted_summary = {
    'by_batch_size': {
        '1': 77,      # 89.5% - 单点批次
        '2-4': 5,     # 5.8%
        '5-10': 4,    # 4.7%
    },
    'by_phase': {
        'LVR': 70,    # 81.4% - 巡航阶段
        'DES': 16,    # 18.6%
    },
    'by_source_tier': {
        'S2_short_batch_threshold_source': 47,  # 54.7%
        'S1_balanced_medium_source': 34,        # 39.5%
        'S0_core_clean_medium_long_source': 5,  # 5.8%
    },
}
```

**接受模式特征**：
- **单点批次主导**（89.5%）：更容易匹配，时间不确定性相对较小
- **巡航阶段主导**（81.4%）：轨迹更平稳，几何匹配更容易
- **S2 source 为主**（54.7%）：短批次更易接受

#### 接受批次的几何质量

```python
accepted_geometry = {
    'cost': {
        'q50': 0.99,
        'q90': 1.48,
        'max': 1.83,
    },
    'cross_track_q90_km': {
        'q50': 0.97,
        'q90': 1.24,
        'max': 1.48,
    },
    'vertical_q90_m': {
        'q50': 0.0,
        'q90': 432.2,
        'max': 762.0,
    },
}
```

- 接受批次的几何质量**非常好**，接近 Stage3 v8 验证标准
- 说明：V4 的接受门控**不是过严**，而是候选池质量问题

---

## 第二部分：V5 优化方案评估与增强

### 2.1 V5 优化方案核心评估

#### 方案结构

V5 方案提出四阶段流程：

```
Phase 1: 对齐审计 (Alignment Audit)
    ↓
Phase 2: 候选策略 V5 (Candidate Policy V5)
    ↓
Phase 3: 伪验证门 (Pseudo Validation Gate)
    ↓
Phase 4: 真实 V5 匹配 (Real Stage5 V5 Matching)
```

#### 评估维度

| 评估维度 | 评分 | 说明 |
|---------|------|------|
| **科学性** | ⭐⭐⭐⭐⭐ | 正确识别根源是候选可用性，而非门控过严 |
| **可追溯性** | ⭐⭐⭐⭐⭐ | 要求每个候选记录身份等级和证据字段 |
| **安全性** | ⭐⭐⭐⭐⭐ | 伪验证门 + AMDAR 保持 support-only |
| **完整性** | ⭐⭐⭐⭐☆ | 缺少具体实施细节和数值参数 |
| **可操作性** | ⭐⭐⭐☆☆ | Phase 1 审计脚本需要详细规格 |

**总体评估**：✅ **方案科学且安全，但需补充实施细节**

### 2.2 V5 方案优势

#### 优势 1：正确的诊断思路

❌ **错误思路**（V5 明确拒绝）：
- 放宽 `cost` 阈值到 5、10、20
- 放宽 `cross_track_q90` 到 3km、5km、10km
- 降低 Stage3 验证标准以"匹配"当前接受率

✅ **正确思路**（V5 采用）：
- 审计为什么 49.1% AMDAR 批次无候选
- 审计为什么有候选的批次 `best_cost` p10 高达 24.82
- 修复数据对齐问题，而非放宽几何门控

#### 优势 2：分层身份等级设计

```python
identity_levels_v5 = {
    'I0_exact_tail_flight_date': {
        'eligible_grades': ['A', 'B', 'C'],
        'description': 'Exact match on tail_norm, flight_norm, service_date_utc',
    },
    'I1_exact_tail_flight_date_shift': {
        'eligible_grades': ['B', 'C'],
        'description': 'Same tail/flight, date shifted by ±1 day',
        'use_case': '修复 UTC 跨日、时区错位问题',
    },
    'I2_normalized_flight_equivalent': {
        'eligible_grades': ['B', 'C'],
        'description': 'Same tail/date after flight normalization repair',
        'use_case': '修复航班号归一化问题（如 CA1234 vs CCA1234）',
    },
    'I3_tail_date_unique_flight': {
        'eligible_grades': ['C'],
        'description': 'Unique ADS-B flight under same tail/date',
        'use_case': '处理航班号缺失但 tail+date 唯一的情况',
    },
    'I4_tail_time_spatial_multi_flight': {
        'eligible_grades': [],  # 诊断用，不接受
        'description': 'Multiple flights under tail/time/spatial, ambiguous',
    },
}
```

**设计亮点**：
- **分层降级**：I0 可进 A/B/C，I1/I2 只能 B/C，I3 只能 C
- **明确用例**：每个级别都有清晰的数据修复用例
- **安全边界**：I4 明确不接受，避免歧义候选

#### 优势 3：伪验证门前置

V5 要求在运行真实 Stage5 v5 matching 之前：

1. 在 Stage3 pseudo-AMDAR 中复现 v5 候选策略
2. 在 validation split 上调优
3. 在 locked test 上报告（不调优）
4. 分身份等级（I0/I1/I2/I3）报告指标
5. 质量门：wrong-leg rate <=1%（目标）或 <=2%（最大）

**安全价值**：
- 避免在真实数据上盲目扩展候选
- 确保弱身份候选不会引入大量 wrong leg
- 保持 Stage3 → Stage5 的验证一致性

### 2.3 V5 方案需要增强的点

#### 增强点 1：Phase 1 对齐审计的具体规格

**当前状态**：V5 方案列出了审计目标和输出文件名，但缺少具体审计逻辑

**建议补充**：

```python
# 1.1 no_candidate 分解审计
no_candidate_audit = {
    'total_no_candidate': 27775,
    'decomposition': {
        'tail_not_in_adsb': '?',  # AMDAR tail 在 ADS-B 中不存在
        'tail_exists_but_no_date_match': '?',  # tail 存在但日期不匹配
        'tail_date_exists_but_no_flight_match': '?',  # tail+date 存在但航班号不匹配
        'tail_date_flight_exists_but_filtered': '?',  # 存在但被 phase/bbox/altitude 过滤
        'tail_date_flight_exists_but_no_time_overlap': '?',  # 存在但时间窗口不重叠
    }
}

# 1.2 航班号归一化审计
flight_normalization_audit = {
    'amdar_flight_patterns': ['CA1234', 'CCA1234', 'CA 1234', ...],
    'adsb_flight_patterns': ['CCA1234', 'AIR_CHINA_1234', ...],
    'normalization_coverage': '?',  # 当前归一化能覆盖多少 pattern
    'suggested_rules': [...],  # 建议的新归一化规则
}

# 1.3 日期对齐审计
date_alignment_audit = {
    'date_shift_-1_candidates': '?',  # 日期前移 1 天能增加多少候选
    'date_shift_+1_candidates': '?',  # 日期后移 1 天能增加多少候选
    'utc_midnight_crossing_cases': '?',  # 跨 UTC 零点的批次数量
}

# 1.4 时间窗口审计
time_window_audit = {
    'current_window_hours': 24,  # 当前时间窗口
    'expand_to_36h_candidates': '?',
    'expand_to_48h_candidates': '?',
}

# 1.5 几何失败量化审计
geometry_failure_audit = {
    'best_cost_distribution': {
        'p10': 24.82,
        'p25': '?',
        'q50': '?',
        'p75': '?',
        'p90': '?',
    },
    'cost_breakdown_by_component': {
        'cross_track_contribution': '?',
        'vertical_contribution': '?',
        'time_contribution': '?',
    },
}
```


#### 增强点 2：候选扩展的数值参数

**当前状态**：V5 方案定义了身份等级但未给出具体参数

**建议补充**：

```python
# Phase 2 候选策略 V5 参数规格

# I1: 日期偏移策略
date_shift_policy = {
    'enabled': True,
    'shift_range': [-1, 0, +1],  # UTC 日期前后各 1 天
    'conditions': {
        'batch_near_utc_midnight': True,  # 优先处理跨零点批次
        'tail_exists_in_adsb': True,
        'flight_pattern_similar': True,  # 航班号模式相似
    },
    'cost_penalty': 0.2,  # 日期偏移候选的 cost 加权 penalty
    'eligible_grades': ['B', 'C'],
    'pseudo_validation_required': True,
}

# I2: 航班号归一化修复
flight_normalization_policy = {
    'enabled': True,
    'normalization_rules': [
        # 航空公司代码变体
        {'amdar_pattern': r'^CA(\d+)$', 'adsb_pattern': r'^CCA\1$'},
        {'amdar_pattern': r'^MU(\d+)$', 'adsb_pattern': r'^CES\1$'},
        {'amdar_pattern': r'^3U(\d+)$', 'adsb_pattern': r'^CHH\1$'},
        # 空格处理
        {'amdar_pattern': r'^(\w+)\s+(\d+)$', 'adsb_pattern': r'^(\w+)(\d+)$'},
        # 前导零
        {'amdar_pattern': r'^(\w+)0+(\d+)$', 'adsb_pattern': r'^(\w+)(\d+)$'},
    ],
    'apply_after_exact_match_fails': True,
    'cost_penalty': 0.1,
    'eligible_grades': ['B', 'C'],
    'pseudo_validation_required': True,
}

# I3: Tail+Date 唯一航班策略
tail_date_unique_policy = {
    'enabled': True,
    'conditions': {
        'flight_count_under_tail_date': 1,  # 必须唯一
        'no_flight_number_in_amdar': True,  # AMDAR 航班号缺失
        'adsb_flight_has_valid_number': True,
    },
    'cost_penalty': 0.3,
    'eligible_grades': ['C'],
    'max_acceptance_fraction': 0.20,  # 最多占 C 级接受的 20%
    'pseudo_validation_required': True,
    'wrong_leg_rate_threshold': 0.05,  # 在伪验证中 wrong-leg 率必须 <5%
}

# 多候选歧义处理
ambiguity_policy_v5 = {
    'A_grade': {
        'min_margin': 2.5,  # second_cost / best_cost >= 2.5
        'single_I0_candidate_allowed': True,
    },
    'B_grade': {
        'min_margin': 1.5,
        'single_I0_I1_candidate_allowed': True,
    },
    'C_grade': {
        'min_margin': 1.2,
        'single_candidate_allowed': True,
    },
}
```

#### 增强点 3：伪验证的分级质量门

**当前状态**：V5 方案给出了总体质量门，但未分身份等级

**建议补充**：

```python
# Phase 3 伪验证分级质量门

pseudo_validation_quality_gates_v5 = {
    'overall': {
        'selected_coverage_ge': 0.75,  # 至少 75% selected
        'wrong_leg_rate_le': 0.01,  # 目标 <=1%
        'wrong_leg_rate_max': 0.02,  # 最大 <=2%
        'catastrophic_error_rate_lt': 0.03,
    },
    
    'by_identity_level': {
        'I0_exact': {
            'wrong_leg_rate_le': 0.005,  # I0 应该最准确
            'time_error_q90_s': 300,  # 5 分钟
        },
        'I1_date_shift': {
            'wrong_leg_rate_le': 0.015,  # 允许稍高
            'time_error_q90_s': 450,  # 7.5 分钟
            'min_case_count': 500,  # 至少 500 个 case 才有统计意义
        },
        'I2_flight_norm': {
            'wrong_leg_rate_le': 0.020,
            'time_error_q90_s': 450,
            'min_case_count': 500,
        },
        'I3_tail_date_unique': {
            'wrong_leg_rate_le': 0.050,  # C 级允许更高
            'time_error_q90_s': 600,  # 10 分钟
            'min_case_count': 200,
            'acceptance_in_real_stage5_le': 0.20,  # 最多占总接受的 20%
        },
    },
    
    'tier_compatibility': {
        'T1_validation_q90_le': 180,  # 与 Stage4 v3 T1 定义一致
        'T2_validation_q90_le': 600,  # 与 Stage4 v3 T2 定义一致
    },
    
    'safety_checks': {
        'no_tail_date_split_leakage': True,
        'locked_test_not_used_for_tuning': True,
        'weak_identity_reported_separately': True,
    },
}

# 如果任一身份等级未通过质量门，该级别不能进入真实 Stage5 v5
```

#### 增强点 4：Phase 4 实施的风险控制

**当前状态**：V5 方案给出了接受规则，但缺少风险缓解

**建议补充**：

```python
# Phase 4 风险控制与回退机制

risk_mitigation_v5 = {
    'risk_1_weak_identity_wrong_leg': {
        'description': 'I1/I2/I3 候选引入大量 wrong leg',
        'detection': {
            'monitor_accepted_by_identity_level': True,
            'flag_if_I3_fraction_gt': 0.30,  # I3 超过 30% 触发警告
        },
        'mitigation': {
            'tighten_I3_cost_threshold': 'cost<=2.0 instead of 3.0',
            'raise_I3_ambiguity_margin': 'margin>=1.5 instead of 1.2',
        },
        'rollback': 'Disable I3, rerun with I0/I1/I2 only',
    },
    
    'risk_2_date_shift_time_alignment': {
        'description': '日期偏移导致时间对齐错误',
        'detection': {
            'check_projected_time_distribution': True,
            'flag_if_time_after_batch_end_q50_gt': 120,  # 中位数超 2 分钟
        },
        'mitigation': {
            'add_date_shift_time_penalty': True,
            'tighten_time_projection_threshold': '±120s instead of ±180s',
        },
        'rollback': 'Disable I1, rerun with I0/I2/I3 only',
    },
    
    'risk_3_flight_norm_false_positive': {
        'description': '航班号归一化误匹配不同航班',
        'detection': {
            'cross_check_route_consistency': True,
            'flag_if_route_mismatch_rate_gt': 0.10,
        },
        'mitigation': {
            'add_route_validation': True,
            'require_origin_dest_compatible': True,
        },
        'rollback': 'Disable problematic normalization rules',
    },
    
    'risk_4_target_still_missed': {
        'description': 'V5 扩展后仍未达到 500 批次目标',
        'detection': {
            'accepted_batches_lt': 500,
        },
        'response': {
            'run_conservative_stage6_diagnostic': True,
            'report_target_miss_explicitly': True,
            'document_remaining_gaps': True,
            'do_not_loosen_geometry_gates': True,
        },
        'next_step': 'Return to Stage2 QC optimization (expand candidate pool)',
    },
}

# 每个风险都有检测、缓解、回退三层防护
```


#### 增强点 5：Stage6 前向兼容性设计

**当前状态**：V5 方案聚焦 Stage5，但应考虑 Stage6 使用场景

**建议补充**：

```python
# Stage6 时间建模的 V5 输出需求

stage6_compatibility_v5 = {
    'accepted_match_table_schema': {
        'required_columns': [
            'amdar_batch_id',
            'matched_leg_id',
            'segment_start_idx',
            'segment_end_idx',
            'stage5_v5_grade',  # A/B/C
            'identity_level',  # I0/I1/I2/I3
            'identity_evidence',  # JSON: 匹配的具体证据
            'best_cost',
            'cross_track_q90_km',
            'vertical_q90_m',
            'ambiguity_margin',
            'projected_time_q50_utc',
            'projected_time_q10_utc',
            'projected_time_q90_utc',
            'time_after_batch_end_q50_s',
            'confidence_subtier',  # Stage4 v3
            'source_tier',  # Stage2 v7
        ],
    },
    
    'time_distribution_guidance': {
        'A_grade_I0': {
            'pdf_type': 'gaussian',
            'time_std_s': 60,  # ±1 分钟
            'confidence_for_stage6': 0.85,
        },
        'B_grade_I0': {
            'pdf_type': 'gaussian',
            'time_std_s': 120,  # ±2 分钟
            'confidence_for_stage6': 0.70,
        },
        'B_grade_I1_I2': {
            'pdf_type': 'gaussian',
            'time_std_s': 180,  # ±3 分钟
            'confidence_for_stage6': 0.60,
        },
        'C_grade': {
            'pdf_type': 'gaussian',
            'time_std_s': 300,  # ±5 分钟
            'confidence_for_stage6': 0.45,
        },
    },
    
    'rejected_batch_guidance': {
        'usage': 'Continue using batch interval distribution',
        'do_not_fabricate_accepted': True,
        'do_not_use_batch_end_as_point_time': True,
    },
}
```

### 2.4 V5 方案实施优先级调整

基于以上增强点，建议调整实施优先级：

```
高优先级（必须完成）：
  ├─ Phase 1.1: no_candidate 分解审计（识别主要缺失原因）
  ├─ Phase 1.2: 航班号归一化审计（量化归一化覆盖率）
  ├─ Phase 1.3: 日期对齐审计（量化跨日问题）
  ├─ Phase 2: 实施 I0/I1/I2 候选策略（先不启用 I3）
  ├─ Phase 3: 伪验证门（分级质量门）
  └─ Phase 4: 真实 V5 匹配（I0/I1/I2 only）

中优先级（条件启用）：
  ├─ Phase 2: 实施 I3 tail-date-unique 策略
  ├─ Phase 3: I3 伪验证（wrong-leg rate <=5%）
  └─ Phase 4: 真实 V5 匹配（包含 I3）

低优先级（诊断用）：
  ├─ Phase 1.4: 时间窗口扩展审计（36h/48h）
  ├─ Phase 1.5: 几何失败组件分解
  └─ I4 多候选歧义诊断（不接受，仅报告）
```

**优先级理由**：
- I1（日期偏移）和 I2（航班归一化）是**系统性修复**，预期 wrong-leg rate 低
- I3（tail-date-unique）是**启发式扩展**，wrong-leg 风险更高，作为条件启用
- Phase 1 审计必须先完成，才能量化各策略的潜在收益

---

## 第三部分：V5 实施路线图与工时估算

### 3.1 Phase 1: 对齐审计（8-12 小时）

#### 任务清单

```markdown
□ Task 1.1: 编写审计脚本框架（2h）
  - 输入：Stage5 v4 batch diagnostics, Stage2 v7 leg table, AMDAR batch table
  - 输出框架：no_candidate_decomposition, flight_norm_audit, date_audit, time_audit, geometry_audit

□ Task 1.2: no_candidate 分解审计（3-4h）
  - 逐层检查：tail 存在性 → date 匹配 → flight 匹配 → 过滤条件 → 时间重叠
  - 输出：no_candidate_decomposition_v5.json

□ Task 1.3: 航班号归一化审计（2-3h）
  - 提取 AMDAR/ADS-B 航班号 pattern
  - 评估当前归一化覆盖率
  - 建议新归一化规则
  - 输出：flight_normalization_audit_v5.parquet

□ Task 1.4: 日期对齐审计（1-2h）
  - 统计日期 ±1 天能增加的候选数
  - 识别跨 UTC 零点批次
  - 输出：date_shift_candidate_audit_v5.parquet

□ Task 1.5: 几何失败量化（1-2h）
  - 分解 best_cost 的组件贡献
  - 分析 cost 分布的尾部
  - 输出：geometry_failure_quantiles_v5.json

□ Task 1.6: 生成审计报告（1h）
  - 综合 1.2-1.5 的发现
  - 量化各策略的潜在收益
  - 输出：alignment_audit_results_and_next_steps_v5.md
```

#### 关键输出

```python
alignment_audit_summary_v5 = {
    'no_candidate_breakdown': {
        'tail_not_in_adsb': '? batches',
        'tail_exists_date_mismatch': '? batches (potential for I1)',
        'tail_date_exists_flight_mismatch': '? batches (potential for I2/I3)',
        'exists_but_filtered': '? batches',
        'exists_no_time_overlap': '? batches',
    },
    'potential_gains': {
        'I1_date_shift': '+? candidate batches',
        'I2_flight_norm': '+? candidate batches',
        'I3_tail_date_unique': '+? candidate batches',
        'total_potential': '+? candidate batches',
    },
    'risk_assessment': {
        'I1_expected_wrong_leg_rate': '<?%',
        'I2_expected_wrong_leg_rate': '<?%',
        'I3_expected_wrong_leg_rate': '<?%',
    },
    'recommendation': 'Proceed to Phase 2 if total_potential >= 10000 batches',
}
```

### 3.2 Phase 2: 候选策略 V5 实施（6-8 小时）

#### 任务清单

```markdown
□ Task 2.1: 实施身份匹配层次结构（2h）
  - 定义 I0/I1/I2/I3 匹配逻辑
  - 实施 cost penalty 机制
  - 每个候选记录 identity_level 和 evidence

□ Task 2.2: 实施 I1 日期偏移策略（1-2h）
  - 日期 ±1 天扩展
  - UTC 跨零点检测
  - Date-shift evidence 记录

□ Task 2.3: 实施 I2 航班号归一化（2-3h）
  - 应用 Phase 1 建议的归一化规则
  - 归一化后重新匹配
  - Normalization evidence 记录

□ Task 2.4: 实施 I3 tail-date-unique（1-2h）
  - 检查 tail+date 唯一性
  - Uniqueness evidence 记录
  - 标记为条件启用（默认关闭）

□ Task 2.5: 候选表质量检查（1h）
  - 验证每个候选都有 identity_level
  - 验证 no identity_conflict
  - 输出：candidate_policy_v5_summary.json
```

#### 关键输出

```python
candidate_policy_v5_summary = {
    'total_candidates': '?',
    'by_identity_level': {
        'I0': '?',
        'I1': '?',
        'I2': '?',
        'I3': '?',
    },
    'new_candidates_vs_v4': '+?',
    'identity_conflict_count': 0,  # 必须为 0
    'evidence_completeness': 1.0,  # 必须为 100%
}
```

### 3.3 Phase 3: 伪验证门（12-16 小时）

#### 任务清单

```markdown
□ Task 3.1: 修改 Stage3 pseudo-AMDAR 脚本（3-4h）
  - 集成 I0/I1/I2/I3 候选策略
  - 实施分级质量门
  - 记录每个 pseudo case 的 identity_level

□ Task 3.2: 在 validation split 上调优（4-6h）
  - 调整 cost penalty 参数
  - 调整 ambiguity margin 阈值
  - 平衡接受率与 wrong-leg rate

□ Task 3.3: 在 locked test 上报告（2-3h）
  - 分 I0/I1/I2/I3 报告指标
  - 验证质量门通过情况
  - 输出：pseudo_validation_v5_report.json

□ Task 3.4: 质量门评审（1-2h）
  - 如果任一级别未通过，禁用该级别
  - 记录禁用原因和改进建议
  - 决定是否继续 Phase 4

□ Task 3.5: 伪验证结果分析文档（1-2h）
  - 输出：pseudo_validation_v5_analysis_and_gate_check.md
```

#### 质量门检查

```python
phase3_quality_gate_v5 = {
    'overall_gate': {
        'selected_coverage_ge_75pct': '?',  # 必须通过
        'wrong_leg_rate_le_1pct': '?',  # 目标
        'wrong_leg_rate_le_2pct': '?',  # 最大
        'catastrophic_error_rate_lt_3pct': '?',  # 必须通过
    },
    'I0_gate': {
        'wrong_leg_rate_le_0_5pct': '?',
        'time_error_q90_le_300s': '?',
    },
    'I1_gate': {
        'wrong_leg_rate_le_1_5pct': '?',
        'time_error_q90_le_450s': '?',
        'min_case_count_ge_500': '?',
    },
    'I2_gate': {
        'wrong_leg_rate_le_2_0pct': '?',
        'time_error_q90_le_450s': '?',
        'min_case_count_ge_500': '?',
    },
    'I3_gate': {
        'wrong_leg_rate_le_5_0pct': '?',
        'time_error_q90_le_600s': '?',
        'min_case_count_ge_200': '?',
    },
    'decision': {
        'I0_enabled': True,  # 始终启用
        'I1_enabled': '?',  # 根据质量门决定
        'I2_enabled': '?',
        'I3_enabled': '?',
    },
}
```


### 3.4 Phase 4: 真实 V5 匹配（10-14 小时）

#### 任务清单

```markdown
□ Task 4.1: 创建 Stage5 v5 匹配脚本（3-4h）
  - 基于 v4 脚本修改
  - 集成 Phase 3 启用的身份等级
  - 实施分级接受规则

□ Task 4.2: 运行 Stage5 v5 匹配（3-4h）
  - 使用 25 slice / 25 workers
  - 复用 Stage4 v3 / Stage2 v7 / Stage2 v4 表
  - 生成 accepted/rejected/diagnostics 表

□ Task 4.3: 质量检查与诊断（2-3h）
  - 验证 safety gate 通过
  - 检查 target gate 状态
  - 分析接受/拒绝分布

□ Task 4.4: 结果分析文档（2-3h）
  - 对比 v4 vs v5 改善
  - 分析身份等级贡献
  - 生成下一步建议
  - 输出：stage5_v5_results_analysis_and_next_steps.md
```

#### 预期改善目标

```python
stage5_v5_targets = {
    'conservative': {
        'accepted_batches': 500,  # 从 v4 的 86 提升到 500
        'acceptance_rate': 0.010,  # 1%
        'improvement_vs_v4': '+482% batches',
    },
    'balanced': {
        'accepted_batches': 1000,
        'acceptance_rate': 0.018,  # 1.8%
        'improvement_vs_v4': '+1063% batches',
    },
    'aggressive': {
        'accepted_batches': 2000,
        'acceptance_rate': 0.035,  # 3.5%
        'improvement_vs_v4': '+2226% batches',
    },
    'realism_check': {
        'depends_on': 'Phase 1 audit findings',
        'key_factor': 'How many no_candidate batches can be recovered',
        'note': 'If Phase 1 finds <5000 recoverable batches, conservative target may not be reached',
    },
}
```

#### V5 质量门

```python
stage5_v5_quality_gates = {
    'safety_gate': {
        'stage3_v8_pseudo_validation_v5_passed': True,
        'stage4_v3_gate_passed': True,
        'batch_diagnostics_cover_all_56521': True,
        'accepted_rows_have_required_fields': True,
        'no_identity_conflict_accepted': True,
        'amdar_strict_truth_count_eq_0': True,
        'amdar_holdout_eligible_count_eq_0': True,
        'all_accepted_support_only': True,
    },
    'target_gate': {
        'accepted_batches_ge_500': '?',
        'accepted_fraction_ge_1pct': '?',
        'A_B_C_grades_all_present': '?',
        'reject_reason_counts_complete': True,
        'weak_identity_reported_separately': True,
    },
    'overall_pass': {
        'safety_gate': True,  # 必须通过
        'target_gate': '?',  # 可能未通过
    },
}
```

### 3.5 总工时与里程碑

#### 总工时估算

| Phase | 任务 | 工时（保守） | 工时（激进） |
|-------|------|-------------|-------------|
| Phase 1 | 对齐审计 | 8h | 12h |
| Phase 2 | 候选策略实施 | 6h | 8h |
| Phase 3 | 伪验证门 | 12h | 16h |
| Phase 4 | 真实 V5 匹配 | 10h | 14h |
| **总计** | **Stage5 V5 全流程** | **36h** | **50h** |

#### 里程碑与决策点

```
Milestone 1 (完成 Phase 1)：
  ├─ 决策：Phase 1 审计发现的潜在候选是否 >= 10000 batches？
  ├─ 如果 Yes → 继续 Phase 2
  └─ 如果 No → 考虑转向 Stage2 QC 优化（扩大 ADS-B leg 候选池）

Milestone 2 (完成 Phase 2)：
  ├─ 决策：候选策略 V5 是否新增候选 >= 5000 batches？
  ├─ 如果 Yes → 继续 Phase 3
  └─ 如果 No → 审查 Phase 1 审计结论，调整策略

Milestone 3 (完成 Phase 3)：
  ├─ 决策：伪验证质量门是否通过？
  ├─ 如果 Yes → 继续 Phase 4
  └─ 如果 No → 禁用未通过的身份等级，重新评估目标

Milestone 4 (完成 Phase 4)：
  ├─ 决策：Stage5 v5 target gate 是否通过？
  ├─ 如果 Yes → 进入 Stage6 目标分支
  └─ 如果 No → 进入 Stage6 保守诊断分支，报告 target miss
```

---

## 第四部分：V5 成功标准与回退策略

### 4.1 分级成功标准

#### Tier 1: 最小可行成功（Safety Gate）

```python
tier1_success_criteria = {
    'safety_gate_passed': True,
    'accepted_batches': '>= 86',  # 至少不退步
    'accepted_rows_traceable': True,
    'amdar_remain_support_only': True,
    'no_quality_regression': True,
}
```

**达成条件**：Phase 4 完成，safety gate 通过  
**后果**：可以进入保守 Stage6 诊断分支  
**不足**：未达到 target gate，不能进入目标 Stage6 分支

#### Tier 2: 保守目标成功

```python
tier2_success_criteria = {
    'safety_gate_passed': True,
    'target_gate_passed': True,
    'accepted_batches': '>= 500',
    'acceptance_rate': '>= 0.01',
    'A_B_C_grades_balanced': True,
    'weak_identity_fraction': '<= 0.30',
}
```

**达成条件**：Phase 4 完成，target gate 通过  
**后果**：可以进入目标 Stage6 分支  
**价值**：Stage6 窄时间分布覆盖从 0.002% 提升到 1-2%

#### Tier 3: 平衡目标成功

```python
tier3_success_criteria = {
    'all_tier2_criteria': True,
    'accepted_batches': '>= 1000',
    'acceptance_rate': '>= 0.018',
    'I0_I1_I2_all_enabled': True,
    'pseudo_validation_wrong_leg_le_1pct': True,
}
```

**达成条件**：Phase 3 质量门全部通过，Phase 4 超预期  
**价值**：Stage6 窄时间分布覆盖提升到 2-4%

#### Tier 4: 激进目标成功

```python
tier4_success_criteria = {
    'all_tier3_criteria': True,
    'accepted_batches': '>= 2000',
    'acceptance_rate': '>= 0.035',
    'I3_enabled_and_safe': True,
    'overall_wrong_leg_rate_le_1pct': True,
}
```

**达成条件**：所有身份等级启用且质量可控  
**价值**：Stage6 窄时间分布覆盖可能达到 4-8%

### 4.2 失败场景与回退策略

#### 失败场景 1：Phase 1 审计发现潜在候选 < 5000

**症状**：
- no_candidate 分解后，可通过 I1/I2/I3 恢复的批次 < 5000
- 主要缺失原因是 ADS-B 覆盖缺口或真实无候选

**诊断**：
- 检查 `tail_not_in_adsb` 占比
- 检查 `exists_but_no_time_overlap` 占比

**回退策略**：
```python
fallback_1 = {
    'action': 'Pause Stage5 V5, pivot to Stage2 QC optimization',
    'reason': 'Candidate pool insufficient, need to expand ADS-B legs first',
    'next_step': '执行 Stage2-6 优化方案的 Stage2 部分（见 amdar_stage2_to_6_optimization_plan_20260706.md）',
    'target': 'A 级 leg 从 127 提升到 500+，S0 source pool 从 13,432 提升到 40,000+',
}
```

#### 失败场景 2：Phase 3 伪验证 wrong-leg rate > 2%

**症状**：
- I1/I2/I3 某个等级在 pseudo validation 中 wrong-leg rate 超过 2%
- Catastrophic error rate > 3%

**诊断**：
- 检查是哪个身份等级导致
- 分析 wrong leg 的 pattern

**回退策略**：
```python
fallback_2 = {
    'action': 'Disable the problematic identity level',
    'I1_wrong_leg_gt_2pct': 'Disable I1, rerun Phase 3 with I0/I2/I3 only',
    'I2_wrong_leg_gt_2pct': 'Disable I2, review normalization rules',
    'I3_wrong_leg_gt_5pct': 'Disable I3, run Phase 4 with I0/I1/I2 only',
    'all_levels_problematic': 'Abort V5, investigate data quality issues',
}
```

#### 失败场景 3：Phase 4 target gate 未通过但 safety gate 通过

**症状**：
- accepted_batches < 500
- 但 safety gate 全部通过

**诊断**：
- V5 扩展的候选虽然身份正确，但几何质量仍然不佳
- 说明数据对齐修复有限

**回退策略**：
```python
fallback_3 = {
    'action': 'Accept partial success, enter conservative Stage6',
    'stage6_mode': 'diagnostic',
    'stage6_usage': 'Use only V5 accepted rows as narrow seeds',
    'stage6_report': 'Explicitly state Stage5 target miss',
    'future_path': [
        'Option 1: 执行 Stage2 QC 优化（扩大候选池）',
        'Option 2: 执行 Stage4 置信度优化（提升 T1/T2 覆盖）',
        'Option 3: 重新审视 AMDAR 数据源质量',
    ],
}
```

#### 失败场景 4：Phase 4 safety gate 未通过

**症状**：
- identity_conflict 候选被接受
- AMDAR strict truth count != 0
- 或其他安全边界破坏

**诊断**：
- 严重的实施错误或逻辑漏洞

**回退策略**：
```python
fallback_4 = {
    'action': 'ABORT V5 immediately',
    'rollback_to': 'Stage5 V4',
    'required_action': 'Fix safety violations before any retry',
    'review': 'Manual code review and test case addition',
}
```

### 4.3 质量保障清单

在运行 Phase 4 之前，必须通过以下检查：

```markdown
□ Phase 1 审计完成，潜在候选 >= 5000 batches
□ Phase 2 候选策略实施完成，每个候选有 identity_level 和 evidence
□ Phase 3 伪验证质量门通过（至少 I0 通过，I1/I2 条件通过）
□ Phase 3 locked test 报告生成，未用于调优
□ Phase 4 脚本经过 dry-run 测试
□ Phase 4 输出路径准备好（不覆盖 v4 输出）
□ Phase 4 运行前备份关键输入表
□ Phase 4 safety gate 检查逻辑已实施
□ Phase 4 结果分析文档模板准备好
```

---

## 第五部分：下一步执行建议

### 5.1 立即行动建议

**推荐路径**：先执行 Phase 1 对齐审计

**理由**：
1. 工时可控（8-12h），风险低
2. 产出直接量化 V5 的潜在收益
3. 为 Phase 2-4 提供数据支撑
4. 如果审计结果不佳，可及时转向 Stage2 优化

**具体行动**：

```bash
# Step 1: 创建 Phase 1 审计脚本
# 文件：/data/LFT-W02_data/pengxu/优化/数据处理/amdar_unified_stage5_v5_alignment_audit_20260708.py

# Step 2: 运行审计
POLARS_MAX_THREADS=25 /data/LFT-W02_data/pengxu/.conda/envs/windy310/bin/python \
  /data/LFT-W02_data/pengxu/优化/数据处理/amdar_unified_stage5_v5_alignment_audit_20260708.py \
  --out-dir /data/LFT-W02_data/pengxu/优化/数据处理/stage5_v5_alignment_audit_optimized_20260708

# Step 3: 审查审计结果
# 查看：stage5_v5_alignment_audit_optimized_20260708/alignment_audit_results_and_next_steps_v5.md

# Step 4: 基于审计结果决策
# 如果潜在候选 >= 10000 → 继续 Phase 2
# 如果潜在候选 5000-10000 → 谨慎继续，降低预期
# 如果潜在候选 < 5000 → 转向 Stage2 QC 优化
```

### 5.2 并行路径建议

如果有多个智能体或开发者并行工作，可以同时推进：

```
路径 A（Stage5 V5 优化）：
  ├─ Agent A1: Phase 1 对齐审计（8-12h）
  ├─ Agent A2: Phase 2 候选策略实施（6-8h，等待 A1 完成）
  ├─ Agent A3: Phase 3 伪验证（12-16h，等待 A2 完成）
  └─ Agent A4: Phase 4 真实匹配（10-14h，等待 A3 完成）
  
路径 B（Stage2 QC 优化，作为 Plan B）：
  ├─ Agent B1: Stage2 速度检查改进（4-6h）
  ├─ Agent B2: Stage2 采样间隔优化（3-4h）
  ├─ Agent B3: Stage2 组件化评分（4-6h）
  └─ Agent B4: Stage2 缺口桥接（3-4h）

路径 C（Stage4 置信度优化，作为 Plan C）：
  ├─ Agent C1: 精简置信度组件（6-8h）
  ├─ Agent C2: 动态分层阈值（4-6h）
  └─ Agent C3: 高风速优化（4-6h）
```

**协调机制**：
- 路径 A 优先，B 和 C 作为备选
- 如果 Phase 1 审计发现潜在候选不足，立即启动路径 B
- 如果 Phase 3 伪验证失败，考虑路径 C（提升现有数据质量）

### 5.3 关键决策点时间表

```
Day 0: 启动 Phase 1 对齐审计
Day 1-2: 完成 Phase 1，审查结果
  ├─ 决策点 1: 是否继续 Phase 2？
  └─ 如果 No → 转向 Stage2 QC 优化

Day 2-3: 完成 Phase 2 候选策略实施
  ├─ 决策点 2: 新增候选是否足够？
  └─ 如果 No → 调整策略或转向 Plan B

Day 3-5: 完成 Phase 3 伪验证
  ├─ 决策点 3: 质量门是否通过？
  └─ 如果 No → 禁用问题级别或 abort

Day 5-7: 完成 Phase 4 真实匹配
  ├─ 决策点 4: Target gate 是否通过？
  ├─ 如果 Yes → 进入 Stage6 目标分支
  └─ 如果 No → 进入 Stage6 诊断分支，报告 target miss

Day 7: 生成最终分析和交接文档
```


---

## 第六部分：给下一个智能体的交接话术

### 6.1 项目状态摘要

你接手的是 `/data/LFT-W02_data/pengxu` 下的 centralized_v1 三维水平风场重构项目。当前已完成**大框架 Stage5 V4 real AMDAR-ADS-B matching**，并完成了结果分析和 V5 优化方案评估。

**Stage5 V4 核心结果**：
- 接受率：0.152%（86/56,521 批次）
- 诊断门：通过 ✓
- 目标门：未通过 ✗（目标 >=1%）
- 主要瓶颈：候选覆盖不足（49.1%）和几何质量差（best_cost p10=24.82）

**V5 优化方案状态**：
- 已有方案文档：`stage5_v5_optimization_plan_summary.md`
- 方案评估：科学且安全 ✓，需补充实施细节
- 本文档已补充：5 个增强点，详细实施路线图，36-50h 工时估算

### 6.2 必读文档清单（按优先级）

#### 第一优先级：理解当前结果

1. **本文档**：`stage5_v4_comprehensive_analysis_and_v5_plan_20260708.md`（当前文档）
   - Stage5 V4 结果深度分析
   - V5 方案评估与增强建议
   - 完整实施路线图

2. **Stage5 V4 结果分析**：`stage5_v4_matching_optimized_20260708/stage5_v4_results_analysis_and_next_steps.md`
   - V4 运行结果和质量门
   - 拒绝原因详细统计
   - 下一步建议

3. **Stage5 V4 交接文档**：`stage5_v4_matching_optimized_20260708/next_agent_handover_after_stage5_v4.md`
   - V4 输出文件位置
   - 运行口径和空间策略
   - 关键结果摘要

#### 第二优先级：理解 V5 优化方案

4. **Stage5 V5 优化计划**：`stage5_v4_matching_optimized_20260708/stage5_v5_optimization_plan_summary.md`
   - 四阶段优化流程
   - 分层身份等级设计
   - 质量门要求

5. **Stage2-6 总优化方案**：`amdar_stage2_to_6_optimization_plan_20260706.md`
   - 置信度精简策略
   - Stage2-6 各阶段优化
   - 预期改善目标

#### 第三优先级：理解项目边界

6. **项目总边界**：`/data/LFT-W02_data/pengxu/workflow/centralized_v1_docs/new_window_project_handover_20260529/centralized_v1_ultimate_summary_20260626.md`
   - Strict aircraft holdout 边界
   - TURB 175 条是唯一真值

7. **AMDAR 时间语义**：`优化/teacher_reports/plan4.md`
   - AMDAR 时间是批次时间，不是逐点时间

8. **分层置信度路线**：`优化/teacher_reports/amdar_plan4_comprehensive_assessment_20260701.md`
   - Strict truth 候选少是数据现实
   - 正确路线是分层置信度

9. **Stage4 V3 交接**：`stage4_confidence_v3_next_window_optimized_20260708/next_agent_handover_after_stage4_v3.md`
   - Stage4 v3 next-window 结果
   - 置信度分层和质量门

10. **Stage3 V8 验证**：`stage3_pseudo_amdar_v8_optimized_20260707/stage3_v8_results_analysis_and_next_steps.md`
    - Pseudo-AMDAR 验证结果
    - 质量门标准

### 6.3 核心理解检查清单

在开始 V5 实施前，请确认以下理解：

#### ✅ 数据边界理解

- [ ] 我理解 TURB 175 条是唯一 strict truth，AMDAR 0 条 strict truth
- [ ] 我理解 AMDAR 时间是批次时间，不是逐点观测时间
- [ ] 我理解 Stage5 accepted 也只是 support-only，不是 point truth
- [ ] 我理解 `effective_strict_truth` 不能通过置信度推导
- [ ] 我理解 `holdout_eligible=false` 对所有 AMDAR 必须保持

#### ✅ V4 结果理解

- [ ] 我理解 V4 接受率 0.152% 是真实结果，不是门控过严
- [ ] 我理解主要瓶颈是候选可用性（49.1% 无候选）和几何质量（best_cost p10=24.82）
- [ ] 我理解 V4 尝试的弱身份扩展失败（1910 候选，0 接受）
- [ ] 我理解不能通过放宽几何门控来提升接受率
- [ ] 我理解达到 500 批次目标需要 cost>20、cross_track>10km，这超出验证范围

#### ✅ V5 方案理解

- [ ] 我理解 V5 采用四阶段流程：审计 → 策略 → 伪验证 → 真实匹配
- [ ] 我理解 I0/I1/I2/I3 分层身份等级设计和降级规则
- [ ] 我理解每个身份等级必须通过伪验证质量门才能启用
- [ ] 我理解伪验证必须在 locked test 上报告但不调优
- [ ] 我理解 Phase 1 审计是必要前提，量化潜在收益

#### ✅ 实施路线理解

- [ ] 我理解 Phase 1（8-12h）是最高优先级
- [ ] 我理解如果 Phase 1 审计发现潜在候选 < 5000，应转向 Stage2 优化
- [ ] 我理解 I1/I2 是系统性修复（优先），I3 是启发式扩展（条件启用）
- [ ] 我理解每个 Phase 都有质量门和回退策略
- [ ] 我理解总工时 36-50h，分 4 个 milestone

#### ✅ 边界规则理解

- [ ] 我理解禁止放宽几何门控超出 Stage3 v8 验证范围
- [ ] 我理解禁止接受 identity_conflict 候选
- [ ] 我理解禁止把 rejected rows 伪造成 accepted
- [ ] 我理解禁止把 Stage5 accepted 当作 point observation
- [ ] 我理解如果 V5 target gate 未通过，只能进入保守 Stage6 诊断分支

### 6.4 推荐开场话术

当你准备开始 V5 实施时，请用以下话术确认理解：

```
我已完整阅读以下文档：

1. stage5_v4_comprehensive_analysis_and_v5_plan_20260708.md（本文档，V4 分析和 V5 评估）
2. stage5_v4_results_analysis_and_next_steps.md（V4 结果分析）
3. next_agent_handover_after_stage5_v4.md（V4 交接）
4. stage5_v5_optimization_plan_summary.md（V5 原始方案）
5. amdar_stage2_to_6_optimization_plan_20260706.md（总优化方案）
6. centralized_v1_ultimate_summary_20260626.md（项目边界）
7. Stage4 v3、Stage3 v8 交接文档

我理解以下核心事实：

- Stage5 V4 接受率 0.152%（86 批次），未达到 1% 目标
- 主要瓶颈是候选可用性（49.1% 无候选）和几何质量（best_cost p10=24.82）
- 不能通过放宽几何门控解决，需要修复数据对齐问题
- V5 采用四阶段流程：审计 → 策略 → 伪验证 → 真实匹配
- AMDAR 永远 support-only，0 条 strict truth

我理解 V5 实施路线：

- Phase 1: 对齐审计（8-12h）- 量化 I1/I2/I3 的潜在收益
- Phase 2: 候选策略实施（6-8h）- 实施分层身份等级
- Phase 3: 伪验证门（12-16h）- 分级质量门，启用通过的等级
- Phase 4: 真实 V5 匹配（10-14h）- 运行并分析结果

我理解关键决策点：

- Milestone 1: 如果审计发现潜在候选 < 5000，转向 Stage2 优化
- Milestone 3: 如果伪验证 wrong-leg rate > 2%，禁用问题等级
- Milestone 4: 如果 target gate 未通过，进入保守 Stage6 诊断分支

我准备从 Phase 1（对齐审计）开始实施。请确认是否开始。
```

### 6.5 输出文件结构

V5 实施完成后将生成以下文件结构：

```
/data/LFT-W02_data/pengxu/优化/数据处理/
├── stage5_v4_comprehensive_analysis_and_v5_plan_20260708.md  # 本文档
├── stage5_v5_alignment_audit_optimized_20260708/  # Phase 1
│   ├── no_candidate_decomposition_v5.json
│   ├── flight_normalization_audit_v5.parquet
│   ├── date_shift_candidate_audit_v5.parquet
│   ├── time_window_candidate_audit_v5.parquet
│   ├── geometry_failure_quantiles_v5.json
│   └── alignment_audit_results_and_next_steps_v5.md
├── stage5_v5_candidate_policy_optimized_20260708/  # Phase 2
│   ├── candidate_leg_table_v5.parquet
│   ├── candidate_policy_v5_summary.json
│   └── identity_level_distribution_v5.json
├── stage5_v5_pseudo_validation_optimized_20260708/  # Phase 3
│   ├── pseudo_validation_v5_report.json
│   ├── pseudo_validation_by_identity_level_v5.json
│   ├── quality_gate_check_v5.json
│   └── pseudo_validation_v5_analysis_and_gate_check.md
└── stage5_v5_matching_optimized_20260708/  # Phase 4
    ├── stage5_v5/
    │   ├── amdar_adsb_match_v5.parquet
    │   ├── amdar_adsb_reject_v5.parquet
    │   ├── amdar_adsb_batch_diagnostics_v5.parquet
    │   └── amdar_adsb_match_diagnostics_v5.json
    ├── stage5_v5_results_analysis_and_next_steps.md
    └── next_agent_handover_after_stage5_v5.md
```

### 6.6 关键约束与不变量

在整个 V5 实施过程中，以下不变量**必须保持**：

```python
INVARIANTS = {
    'turb_strict_truth_count': 175,  # 固定
    'amdar_strict_truth_count': 0,   # 固定，永远为 0
    'amdar_holdout_eligible_count': 0,  # 固定，永远为 0
    'stage5_accepted_usage_role': 'support_only_not_strict_truth',
    'stage5_estimated_time_is_point_truth': False,
}

# 每个 Phase 完成后必须验证
def validate_invariants_v5(output_data):
    assert count_amdar_strict_truth(output_data) == 0
    assert count_amdar_holdout_eligible(output_data) == 0
    assert all_accepted_are_support_only(output_data)
    assert no_identity_conflict_accepted(output_data)
```

### 6.7 成功标准

V5 实施的分级成功标准：

| 级别 | 接受批次 | 接受率 | Safety Gate | Target Gate | 价值 |
|------|---------|--------|-------------|-------------|------|
| **Tier 1** | >= 86 | >= 0.15% | ✓ | ✗ | 保守 Stage6 诊断 |
| **Tier 2** | >= 500 | >= 1.0% | ✓ | ✓ | 目标 Stage6，窄分布 1-2% |
| **Tier 3** | >= 1000 | >= 1.8% | ✓ | ✓ | 目标 Stage6，窄分布 2-4% |
| **Tier 4** | >= 2000 | >= 3.5% | ✓ | ✓ | 目标 Stage6，窄分布 4-8% |

**最低要求**：Tier 1（safety gate 通过）  
**保守目标**：Tier 2（target gate 通过）  
**平衡目标**：Tier 3  
**激进目标**：Tier 4

---

## 结语

### 核心结论

1. **Stage5 V4 结果真实**：接受率 0.152% 不是门控过严，而是候选可用性和几何质量问题
2. **V5 方案科学**：四阶段流程正确识别根源，分层身份等级设计合理
3. **需要增强实施细节**：本文档补充了 5 个增强点、详细参数、质量门、风险控制
4. **推荐立即行动**：Phase 1 对齐审计（8-12h），量化潜在收益后再决定后续路径
5. **保持质量边界**：AMDAR 永远 support-only，伪验证必须通过才能进入真实匹配

### 预期改善

如果 V5 全流程成功（Tier 2-3）：
- 接受批次：86 → 500-1000（+482-1063%）
- 接受率：0.15% → 1.0-1.8%
- Stage6 窄时间分布覆盖：0.002% → 1-4%
- 平均时间不确定性：可能从 1350 秒降至 900-600 秒

### 风险提示

- 如果 Phase 1 审计发现潜在候选 < 5000，V5 可能无法达到保守目标
- 如果 Phase 3 伪验证 wrong-leg rate > 2%，需要禁用问题身份等级
- 如果 Phase 4 target gate 未通过，只能进入保守 Stage6 诊断分支
- 并行 Plan B（Stage2 QC 优化）和 Plan C（Stage4 置信度优化）作为备选

### 下一步行动

```bash
# 立即行动：创建并运行 Phase 1 对齐审计
# 预计工时：8-12 小时
# 输出：量化 I1/I2/I3 的潜在收益，决定是否继续 Phase 2-4

# 如果审计结果良好（潜在候选 >= 10000）：
#   → 继续 Phase 2-4
# 如果审计结果中等（潜在候选 5000-10000）：
#   → 谨慎继续，降低预期到 Tier 1-2
# 如果审计结果不佳（潜在候选 < 5000）：
#   → 转向 Stage2 QC 优化（扩大 ADS-B leg 候选池）
```

---

**文档版本**：v1.0  
**生成日期**：2026-07-08  
**作者**：AI Assistant  
**文档类型**：综合分析与优化方案评估  
**后续文档**：`next_agent_handover_for_stage5_v5_implementation_20260708.md`（待生成）

