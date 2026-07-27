# Stage5 V4 结果与 V5 方案执行摘要

生成时间：2026-07-08  
文档类型：执行摘要  
阅读时间：5-8 分钟

---

## 一、Stage5 V4 结果总结

### 核心数据

| 指标 | 数值 | 状态 |
|------|------|------|
| AMDAR 总批次 | 56,521 | - |
| 候选覆盖 | 28,746 (50.9%) | ⚠️ 49.1% 无候选 |
| 接受批次 | 86 (0.152%) | ❌ 远低于 1% 目标 |
| 接受行数 | 118 | - |
| 诊断门 | 通过 | ✅ |
| 目标门 | 未通过 | ❌ |

### 关键发现

**发现 1：候选覆盖不足是主要瓶颈**
- 27,775 批次（49.1%）无候选leg
- 原因可能：航班号归一化失败、日期对齐问题、ADS-B 覆盖缺口

**发现 2：有候选的批次几何质量差**
- 28,746 有候选批次中，21,197（73.7%）因 best_cost>3 被拒绝
- best_cost p10=24.82，远高于 C 级上限 3.0
- 说明：即使有候选，空间位置也不匹配

**发现 3：V4 的弱身份扩展失败**
- 尝试 `tail_date_unique_flight_no_exact_match`：新增 1,910 候选，接受 0
- 候选 cost q1=25.55，几何质量太差
- 结论：简单的弱身份扩展不是安全路径

**发现 4：不能通过放宽门控解决**
- 达到 500 批次需要 cost>20、cross_track_q90>10km
- 这超出 Stage3 v8 验证范围
- 会破坏质量边界

### 结论

✅ **V4 结果真实且可追溯**  
❌ **V4 未达目标（0.152% vs 1%）**  
⚠️ **根源是候选可用性和数据对齐问题，不是门控过严**

---

## 二、V5 优化方案评估

### 方案结构

```
Phase 1: 对齐审计 (8-12h)
   ↓ 量化潜在收益 >= 5000 batches?
Phase 2: 候选策略实施 (6-8h)
   ↓ 新增候选 >= 5000 batches?
Phase 3: 伪验证门 (12-16h)
   ↓ Wrong-leg rate <= 2%?
Phase 4: 真实 V5 匹配 (10-14h)
   ↓ Target gate 通过?
进入 Stage6
```

### 核心设计：分层身份等级

| 等级 | 匹配逻辑 | 用途 | 可接受等级 | Wrong-leg 目标 |
|------|---------|------|-----------|---------------|
| **I0** | exact tail+flight+date | V4 使用 | A/B/C | <=0.5% |
| **I1** | exact tail+flight, date±1 | 修复 UTC 跨日 | B/C | <=1.5% |
| **I2** | 归一化 tail+flight+date | 修复航班号归一化 | B/C | <=2.0% |
| **I3** | exact tail+date, unique flight | 航班号缺失 | C only | <=5.0% |

**设计亮点**：
- 分层降级：I0 可进 A/B/C，I1/I2 只能 B/C，I3 只能 C
- 伪验证前置：每个等级必须通过 Stage3 pseudo 验证才能在真实匹配中启用
- 可追溯：每个候选记录 identity_level 和 evidence

### 方案评估

| 维度 | 评分 | 说明 |
|------|------|------|
| 科学性 | ⭐⭐⭐⭐⭐ | 正确识别根源 |
| 可追溯性 | ⭐⭐⭐⭐⭐ | 每个候选可追溯 |
| 安全性 | ⭐⭐⭐⭐⭐ | 伪验证门 + 边界保持 |
| 完整性 | ⭐⭐⭐⭐☆ | 需补充实施细节（已补充）|
| 可操作性 | ⭐⭐⭐⭐☆ | Phase 1 需详细规格（已补充）|

**总体评估**：✅ **方案科学且安全，可以实施**

---

## 三、V5 增强建议（已补充）

本次分析已补充以下 5 个增强点：

### 增强 1：Phase 1 对齐审计的具体规格

补充内容：
- no_candidate 分解审计逻辑（5 层检查）
- 航班号归一化审计方法
- 日期对齐审计策略
- 时间窗口审计方法
- 几何失败量化方法

### 增强 2：候选扩展的数值参数

补充内容：
- I1 日期偏移策略参数（shift_range, cost_penalty）
- I2 航班号归一化规则示例
- I3 tail-date-unique 条件和限制
- 多候选歧义处理策略

### 增强 3：伪验证的分级质量门

补充内容：
- Overall 质量门（wrong-leg <=1%目标/<=2%最大）
- I0/I1/I2/I3 分级质量门
- Tier 兼容性检查（与 Stage4 v3 一致）
- 安全检查（无 tail-date split 泄漏）

### 增强 4：Phase 4 实施的风险控制

补充内容：
- 4 类风险场景（weak identity wrong-leg, date shift, flight norm, target miss）
- 每类风险的检测、缓解、回退三层防护
- 具体参数阈值和行动方案

### 增强 5：Stage6 前向兼容性设计

补充内容：
- V5 输出表 schema 要求
- 分身份等级的时间分布指导
- Rejected batch 处理指导

---

## 四、预期改善目标

### 保守目标（Tier 2）

- 接受批次：86 → **500**（+482%）
- 接受率：0.152% → **1.0%**
- Stage6 窄时间分布：0.002% → **1-2%**
- 前提：I0 + I1/I2 至少一个通过伪验证

### 平衡目标（Tier 3）

- 接受批次：86 → **1,000**（+1063%）
- 接受率：0.152% → **1.8%**
- Stage6 窄时间分布：0.002% → **2-4%**
- 前提：I0 + I1 + I2 都通过伪验证

### 激进目标（Tier 4）

- 接受批次：86 → **2,000**（+2226%）
- 接受率：0.152% → **3.5%**
- Stage6 窄时间分布：0.002% → **4-8%**
- 前提：I0 + I1 + I2 + I3 都通过伪验证

### 现实性评估

**取决于 Phase 1 审计发现**：
- 如果 no_candidate 中可恢复 >= 10,000 batches → 保守/平衡目标可达
- 如果可恢复 5,000-10,000 batches → 保守目标可达
- 如果可恢复 < 5,000 batches → 应转向 Stage2 QC 优化

---

## 五、实施建议

### 立即行动

**推荐**：先执行 Phase 1 对齐审计（8-12h）

**理由**：
1. 工时可控，风险低
2. 直接量化 V5 的潜在收益
3. 为后续决策提供数据支撑
4. 如果结果不佳，可及时转向其他优化路径

**行动**：
```bash
# Step 1: 创建审计脚本
vim /data/LFT-W02_data/pengxu/优化/数据处理/amdar_unified_stage5_v5_alignment_audit_20260708.py

# Step 2: 运行审计
POLARS_MAX_THREADS=25 python amdar_unified_stage5_v5_alignment_audit_20260708.py \
  --out-dir stage5_v5_alignment_audit_optimized_20260708

# Step 3: 审查结果
less stage5_v5_alignment_audit_optimized_20260708/alignment_audit_results_and_next_steps_v5.md

# Step 4: 决策
if potential_candidates >= 10000:
    继续 Phase 2
elif potential_candidates >= 5000:
    谨慎继续，降低预期
else:
    转向 Stage2 QC 优化
```

### 关键决策点时间表

```
Day 0:     启动 Phase 1 对齐审计
Day 1-2:   完成 Phase 1，审查结果
           └─ 决策点 1: 是否继续 Phase 2？
Day 2-3:   完成 Phase 2 候选策略
           └─ 决策点 2: 新增候选是否足够？
Day 3-5:   完成 Phase 3 伪验证
           └─ 决策点 3: 质量门是否通过？
Day 5-7:   完成 Phase 4 真实匹配
           └─ 决策点 4: Target gate 是否通过？
Day 7:     生成最终分析和交接文档
```

### 并行 Plan B/C

如果 Phase 1 发现潜在候选不足，可转向：

**Plan B：Stage2 QC 优化**
- A 级 leg：127 → 500+
- S0 source pool：13,432 → 40,000+
- 预期工时：8-12h

**Plan C：Stage4 置信度优化**
- T1 覆盖率：0.8% → 5-8%
- T2 覆盖率：26.5% → 35-40%
- 预期工时：12-16h

---

## 六、质量保障

### 不变量（必须保持）

```python
INVARIANTS = {
    'amdar_strict_truth_count': 0,        # 固定，永远为 0
    'amdar_holdout_eligible_count': 0,    # 固定，永远为 0
    'stage5_accepted_usage_role': 'support_only_not_strict_truth',
    'stage5_estimated_time_is_point_truth': False,
}
```

### 质量门（V5）

**Safety Gate**（必须通过）：
- ✅ Stage3 v5 伪验证通过
- ✅ Stage4 v3 gate 通过
- ✅ AMDAR strict truth = 0
- ✅ AMDAR holdout eligible = 0
- ✅ 所有 accepted 都是 support-only
- ✅ 无 identity_conflict 被接受

**Target Gate**（期望通过）：
- ✅ 接受批次 >= 500
- ✅ 接受率 >= 1%
- ✅ A/B/C 等级都存在

### 回退策略

| 场景 | 触发条件 | 回退动作 |
|------|---------|---------|
| **Phase 1 不佳** | 潜在候选 < 5000 | 转 Stage2 QC 优化 |
| **Phase 3 失败** | Wrong-leg > 2% | 禁用问题等级 |
| **Phase 4 Target 未过** | 批次 < 500 | 保守 Stage6 诊断 |
| **Phase 4 Safety 未过** | 边界破坏 | 回退到 V4，修复后重试 |

---

## 七、文档结构

本次分析生成了 3 个文档：

### 1. 综合分析文档（1507 行）
**文件**：`stage5_v4_comprehensive_analysis_and_v5_plan_20260708.md`

**内容**：
- 第一部分：Stage5 V4 结果深度分析（接受率、拒绝原因、候选策略、接受模式）
- 第二部分：V5 方案评估与增强（5 个增强点）
- 第三部分：V5 实施路线图（4 个 Phase，任务清单，输出文件）
- 第四部分：成功标准与回退策略
- 第五部分：下一步执行建议
- 第六部分：交接话术

**用途**：完整的分析和实施指南

### 2. 交接文档（580 行）
**文件**：`next_agent_handover_for_stage5_v5_implementation_20260708.md`

**内容**：
- 项目概览和 V4 结果摘要
- 必读文档清单（按优先级）
- 核心理解检查清单
- 四个 Phase 的详细实施指南
- 风险控制与回退策略
- 推荐开场话术

**用途**：下一个智能体的交接话术

### 3. 执行摘要（本文档）
**文件**：`stage5_v4_v5_executive_summary_20260708.md`

**内容**：
- V4 结果总结
- V5 方案评估
- 预期改善目标
- 实施建议
- 质量保障

**用途**：快速理解和决策

---

## 八、核心要点总结

### 理解 V4 结果

1. ✅ V4 结果真实，诊断门通过
2. ❌ V4 未达目标（0.152% vs 1%）
3. ⚠️ 主要瓶颈：候选覆盖不足（49.1%）+ 几何质量差（best_cost p10=24.82）
4. 🚫 不能通过放宽门控解决

### 理解 V5 方案

1. ✅ 四阶段流程科学（审计 → 策略 → 伪验证 → 真实匹配）
2. ✅ 分层身份等级设计合理（I0/I1/I2/I3）
3. ✅ 伪验证前置保障质量
4. ✅ 本次已补充 5 个增强点

### 理解实施路线

1. 🎯 Phase 1（8-12h）最高优先级
2. 🔍 Phase 1 决定是否继续 V5
3. 🎯 保守目标：500 批次，1% 接受率
4. ⏱️ 总工时：36-50 小时

### 理解质量边界

1. 🔒 AMDAR 永远 support-only（0 条 strict truth）
2. 🔒 Stage5 accepted 不是 point truth
3. 🔒 必须通过伪验证质量门
4. 🔒 Safety gate 不可破坏

---

## 结论

**Stage5 V4**：结果真实但未达标，根源是候选可用性问题  
**V5 方案**：科学且安全，可以实施  
**立即行动**：Phase 1 对齐审计（8-12h）  
**预期改善**：接受率 0.15% → 1-3.5%（取决于审计发现）  
**质量保障**：AMDAR 永远 support-only，分层质量门，可追溯

---

**文档版本**：v1.0  
**生成日期**：2026-07-08  
**阅读时间**：5-8 分钟  
**详细文档**：见 `stage5_v4_comprehensive_analysis_and_v5_plan_20260708.md`（1507 行）  
**交接话术**：见 `next_agent_handover_for_stage5_v5_implementation_20260708.md`（580 行）
