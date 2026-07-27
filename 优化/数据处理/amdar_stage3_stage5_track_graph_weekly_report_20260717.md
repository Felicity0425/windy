# AMDAR–ADS-B 数据关联与 Track Graph 优化研究生周报

报告日期：2026-07-17  
报告周期：2026-07-13 至 2026-07-17  
项目路径：`/data/LFT-W02_data/pengxu`  
报告范围：centralized_v1 大框架 Stage2、Stage3 和 Stage5 优化，不等同于旧 `amdar_stage2_to_6_optimization_plan_20260706.md` 内部的小阶段编号。

---

## 一、本周工作摘要

本周围绕“如何在不破坏 strict truth 和 aircraft holdout 边界的前提下，提高稀疏 AMDAR–ADS-B 数据利用率”开展工作，形成了两条连续推进的技术路线：

1. **真实 AMDAR–ADS-B 序列匹配路线**：完成 Stage5 v6 HMM/Viterbi、Stage3 v12 Drop-DTW 验证和 Stage5 v7 calibrated partial matching，将冻结基线由 `198 unique batches / 251 rows` 提升至 `229 unique batches / 345 rows`。
2. **ADS-B Track Graph 路线**：针对现有 ADS-B 航迹被异常点和接收缺口切碎的问题，完成大框架 Stage2 v8 local consistency、clean tracklet、协方差状态平滑和 tracklet graph，并建立 Stage3 v13 bridge-specific validation。

本周最主要的进展不是简单放宽匹配阈值，而是将“完整序列匹配、部分行剔除、轨迹重连接、候选不确定性和 hard-negative 验证”纳入统一的安全验证框架。

截至本周结束：

- Stage5 v7 safety gate 与 merge target 已通过；
- Stage2 v8 工程和语义质量门全部通过；
- Stage3 v13 locked-test 全部硬质量门通过；
- AMDAR strict truth、holdout 和 estimated-time point-truth 违规均为 `0`；
- 已具备进入 Stage5 v8 graph matching 小集合审计的条件。

---

## 二、研究背景与本周目标

当前 AMDAR 数据存在两个核心限制：

1. AMDAR 时间是批次结束或批次下发时间，不是逐点真实观测时间；
2. ADS-B 虽有约 1,916 万个位置点，但轨迹被划分成约 299 万个短 fragments，大量 leg 的中位点数仅约 7 个。

因此，数据利用率低不能简单归因于“候选数量不足”，还包括：

- AMDAR 序列中局部异常行导致整批拒绝；
- ADS-B 轨迹碎片化导致候选状态不连续；
- 相同身份下存在多个竞争 tracklet/path；
- 稀疏区域存在真实 no-coverage，算法不能凭空生成观测；
- Stage3 pseudo validation 与真实 AMDAR matching 分布存在差异。

本周设定的目标为：

1. 使用序列模型提高真实 AMDAR–ADS-B 匹配的安全接受数量；
2. 建立显式的 partial-row exclusion validation，避免单个异常 AMDAR 行拖累整批；
3. 从原始 ADS-B 点重新构建 clean tracklet 和 track graph，恢复被错误切碎的轨迹证据；
4. 对 graph bridge 建立独立 Stage3 calibration/validation/locked-test；
5. 全程保持 AMDAR support-only、strict aircraft holdout 和 25-slice 省空间口径。

---

## 三、本周完成的主要工作

### 1. Stage5 v6：HMM/Viterbi 序列匹配

本阶段属于大框架 Stage5，处理真实 AMDAR–ADS-B 数据关联。

主要实现内容：

- 冻结 Stage5 v5 的 `198 batches / 251 rows` 安全基线；
- 使用 forward、reverse 和 PCA-order HMM/Viterbi 替代独立最近线段投影；
- 对 `best_cost_gt_3` 拒绝批次增加 partial monotone alignment；
- 保留 unique、ambiguous mixture 和 diagnostic reject 三种不同语义；
- 使用 Stage3 v11 冻结 posterior，禁止在真实 AMDAR 或 locked-test 上调阈值；
- 审计相邻 ADS-B tracklet 的简单物理 bridge，但未经独立 bridge validation 不予放行。

结果如下：

| 指标 | Stage5 v5 | Stage5 v6 | 变化 |
|---|---:|---:|---:|
| Unique batches | 198 | 205 | +7 |
| Matched rows | 251 | 274 | +23 |
| Calibrated mixtures | 0 | 20 | +20 |
| Truth/holdout violations | 0 | 0 | 不变 |

Stage5 v6 safety gate 通过，但新增 `7` 批，未达到当时 `+10` 的 merge target。因此本阶段没有通过降低 posterior、cross-track、cost 或 batch-end 门强行凑数，而是进入 Stage3 v12 partial validation 路线。

### 2. Stage3 v12：Drop-DTW 部分行剔除验证

本阶段属于大框架 Stage3，目标是验证 Stage5 是否可以安全地显式剔除 AMDAR 序列中的局部离群行。

主要实现内容：

- 使用 Drop-DTW 风格单调动态规划，在“匹配当前行”和“支付 penalty 丢弃当前行”之间选择；
- emission 使用水平距离、垂直差和 Huber robust loss；
- 建立 raw sequence case bank 和 row-level truth；
- 加入 point/block outlier、10%–50% drop、reverse、local swap、random order、continuous gap、receiver-time bias 等 corruption；
- 加入 same-identity wrong-tracklet、same-tail/date wrong-flight 和 domain-matched wrong-leg 等 hard negatives；
- calibration 训练 posterior，validation 冻结 policy，locked-test 仅报告。

正式规模与结果：

| 指标 | 结果 | 质量门 |
|---|---:|---:|
| Sequence cases | 25,004 | - |
| Row-level truth | 163,461 | - |
| Locked selected | 7,347 | - |
| Wrong-leg/hard-negative rate | 0.0136% | ≤1%，通过 |
| Catastrophic rate | 0.0602% | <3%，通过 |
| Posterior ECE | 0.000361 | ≤0.05，通过 |
| Max corruption false acceptance | 0.1686% | ≤2%，通过 |
| Same-identity wrong-tracklet | 0.0423% | ≤1%，通过 |

Stage3 v12 全部质量门通过，为 Stage5 v7 的 calibrated partial matching 提供了独立验证依据。

### 3. Stage5 v7：Calibrated Partial Matching

Stage5 v7 使用 Stage3 v12 冻结 policy，针对 Stage5 v6 中的 20 个 mixture、4 个 near-pass partial 和 5 个 physical stitched cases进行小集合审计。

结果如下：

- `20/20` mixture cases 通过 calibrated partial gate；
- `4/4` near-pass partial cases 通过；
- `0/5` stitched cases 通过，继续保持 rejected；
- 新增 `24 unique batches / 71 rows`；
- 最终达到 `229 unique batches / 345 matched rows`。

相对 Stage5 v5：

| 指标 | Stage5 v5 | Stage5 v7 | 改善 |
|---|---:|---:|---:|
| Unique batches | 198 | 229 | +31，提升15.66% |
| Matched rows | 251 | 345 | +94，提升37.45% |
| Unique batch rate | 0.350% | 0.405% | +0.055个百分点 |

Stage5 v7 safety gate 和 merge target 均通过。所有新增均保持 exact identity、物理门、posterior、path stability 和 batch-end upper bound；被剔除 AMDAR 行只保留为 diagnostic，不回填到 match 产品。

### 4. Stage2 v8：ADS-B Local Consistency 与 Track Graph

针对 5 个 stitched cases 未经验证不能放行的问题，本周进一步从大框架 Stage2 开始重建 ADS-B 轨迹组织逻辑。

正式输入：

- ADS-B points：`19,162,638`；
- exact identity/date groups：`357,754`；
- 使用 `tail_norm + flight_norm + service_date_utc` 稳定 hash 分成 25 个互斥 slices。

主要实现内容：

- 计算前后时间差、haversine distance、表观速度、垂直率、加速度、转弯率和 forward/backward residual；
- 识别 isolated position spike、altitude spike、timestamp bias、unreachable motion edge 和 real sampling gap；
- 原始点全部保留，并区分 `clean_include`、`uncertain_keep_low_weight` 和 `diagnostic_exclude`；
- 不继承旧 v4 leg 边界作为永久硬边界，重新构建 clean tracklets；
- 实现 diagonal constant-velocity IMM-style forward/backward covariance smoother；
- 建立 exact identity/date tracklet DAG，输出 physical candidate edges 和 stitched hypotheses；
- Stage2 中所有 `formal_bridge_accepted_v8` 固定为 false。

正式结果：

| 指标 | 结果 |
|---|---:|
| Input/local rows | 19,162,638 / 19,162,638 |
| Clean rows | 19,154,894 |
| Diagnostic excluded rows | 7,744，约0.0404% |
| Legacy-compatible legs | 2,977,478 |
| Clean tracklets | 2,953,850 |
| Fragmentation reduction | 23,628，约0.7936% |
| Physical graph edges | 11,306 |
| Short/medium/long edges | 2,990 / 4,151 / 4,165 |
| Cross-slice group violations | 0 |
| Stage2 formal bridge accepts | 0 |

Stage2 v8 全部工程和语义质量门通过。结果表明，Track Graph 能恢复一部分被错误切碎的证据，但真实碎片化和 no-coverage 仍然占主导，不能依靠无约束 bridge 获得数量级提升。

### 5. Stage3 v13：Bridge-Specific Validation

Stage3 v12 只能授权 partial row drop，不能授权 stitched track。因此本周新建 Stage3 v13，对 bridge edge/path 单独进行验证。

主要实现内容：

- 从 `15,000` 个 clean source tracklets 构建 bridge case bank；
- case 类型包括 reachable short/medium/long bridge、missing middle、position/altitude spike、timestamp bias、heading discontinuity、unreachable bridge、same-identity wrong-tracklet、competing fork 和 wrong-flight same-tail/date；
- `clean_no_bridge` 仅用于 retention 审计，不混入 edge acceptance；
- calibration/validation/locked-test 按 identity/date group 隔离；
- 比较 basic physical、forward residual、forward/backward、covariance-normalized 和 calibrated posterior 模型；
- maximum formal gap 固定为 `1,800s`，locked-test 不参与调参。

正式结果：

| 指标 | 正式结果 | 硬门 | 结论 |
|---|---:|---:|---|
| Case bank | 151,951 | - | - |
| Locked-test cases | 27,599 | - | - |
| Positive recall | 100% | 报告项 | - |
| Wrong-tracklet/path | 0.0827% | ≤1% | 通过 |
| Catastrophic bridge | 0.0645% | <3% | 通过 |
| Edge ECE | 0.000321 | ≤0.05 | 通过 |
| Path ECE | 0.000321 | ≤0.05 | 通过 |
| Max corruption false acceptance | 0.8621% | ≤2% | 通过 |
| Same-identity wrong-tracklet | 0.8621% | ≤1% | 通过 |
| Unreachable bridge | 0% | ≤0.5% | 通过 |
| Truth/holdout violations | 0 | 0 | 通过 |

Stage3 v13 全部 hard quality gates 通过，具备进入 Stage5 v8 小集合 graph audit 的条件。

---

## 四、本周关键结果汇总

| 研究环节 | 本周主要结果 | 状态 |
|---|---|---|
| Stage5 v6 HMM/Viterbi | 198/251 → 205/274，另保留20 mixtures | Safety通过，merge target未过 |
| Stage3 v12 Drop-DTW | Wrong rate 0.0136%，ECE 0.000361 | 全部门通过 |
| Stage5 v7 partial matching | 205/274 → 229/345 | Safety和merge target通过 |
| Stage2 v8 Track Graph | fragments减少23,628，生成11,306 physical edges | 全部门通过 |
| Stage3 v13 bridge validation | wrong-path 0.0827%，ECE 0.000321 | 全部门通过 |

本周在不改变 truth 定义的前提下，使 Stage5 unique batches 相对 v5 增加 `15.66%`，matched rows 增加 `37.45%`；同时建立了后续安全利用 stitched graph 的 Stage2/Stage3 基础。

---

## 五、本周主要技术改进与创新点

### 1. 从点级最近邻转向序列级数据关联

传统独立投影无法保证 AMDAR 行沿 ADS-B 轨迹单调前进。本周使用 HMM/Viterbi 和 Drop-DTW，将关联问题建模为带顺序约束的序列优化问题，并显式建模：

- 状态转移；
- 局部异常行跳过；
- matched fraction；
- contiguous fraction；
- path stability；
- candidate posterior。

### 2. 将“异常点清理”和“轨迹缺失”分开

Stage2 v8 不再把所有高速边和 gap 都视为永久错误，而是区分：

- isolated anomaly；
- uncertain low-weight evidence；
- physically unreachable edge；
- real no-coverage gap。

该设计可以恢复错误切段，但不会用插值伪造无覆盖区域。

### 3. 使用协方差表达轨迹状态不确定性

Stage2 v8 输出 smoothed state 和 horizontal/vertical covariance。后续 Stage5 v8 可使用 Mahalanobis/covariance-normalized emission，而不是继续使用固定的“水平公里数 + 垂直米数”经验权重。

### 4. Bridge 单独建立验证体系

本周明确了不同 policy 不能互相越权：

- Stage3 v11：domain-matched association posterior；
- Stage3 v12：partial row exclusion；
- Stage3 v13：tracklet bridge/path posterior。

这种拆分避免使用一个 aggregate posterior 同时授权完全不同的算法行为。

### 5. 将安全性和数据利用率分开评价

本周没有把 mixture 改名为 unique，也没有为了达到旧 `1%` 目标降低 wrong-path gate。数据利用率提升必须在 safety gate 通过后单独评价。

---

## 六、实验过程中发现并解决的问题

### 1. No-bridge retention 与 bridge acceptance 语义混淆

Stage3 v13 初始 smoke 将“保留原 clean tracklet”计入 bridge acceptance，导致指标解释错误。修正后，clean no-bridge 只用于 retention，edge posterior 只评价是否新增连接。

### 2. Pseudo gap 构造不符合运动学

初始 pseudo case 只增加时间 gap，但未同步推进右端位置，等于人为制造不可达 positive。修正为根据左端状态传播右端状态后，pseudo truth 与物理语义一致。

### 3. Same-identity wrong-tracklet 子门超限

首轮正式 Stage3 v13 中，该子类误接纳率为 `2/113 = 1.77%`。审计发现其中一个 gap 为 `2,869s`，超过方案规定的 `1,800s` formal gap。加入通用 maximum-gap gate 后重新运行，最终降至 `1/116 = 0.8621%`。

### 4. Identity normalization 与旧链不一致

初始实现未移除机尾号连字符，例如 `B-1353` 未转换为 `B1353`，会阻断与 Stage5 exact identity 的连接。修正 normalization 后重新运行 Stage2 和 Stage3，exact identity/date groups 恢复为文档记录的 `357,754`。

以上问题均通过通用语义或物理规则修正，没有针对 locked-test case ID 硬编码。

---

## 七、现阶段存在的问题

### 1. Unique batch rate 仍低于旧计划目标

Stage5 v7 最终 unique batch rate 约为：

```text
229 / 56,521 ≈ 0.405%
```

仍低于旧 `1% / 566 batches` 目标。现有结果说明，主要瓶颈不仅是算法阈值，还包括真实 ADS-B 空间覆盖不足和轨迹区域不重合。

### 2. Track Graph 的直接恢复量有限

Stage2 v8 fragmentation reduction 为 `0.7936%`，说明部分碎片可以恢复，但不是数量级改善。历史 5 个 stitched rejects 对应 4 个 identity/date groups，其中仅 `B1355/MF8773/2026-01-28` 产生一个物理 graph hypothesis，其余仍无可达 edge。

### 3. 当前 smoother 仍是简化模型

Stage2 v8 使用 diagonal constant-velocity IMM-style forward/backward smoother，已输出 mode probability 和 covariance，但还不是完整 CTRV/IMM/RTS。对于机场附近大转弯、快速爬升和下降，后续可以在 validation 上比较更强运动模型。

### 4. Stage3 v13 通过不等于 Stage5 unique 自动通过

Stage5 v8 仍需要同时满足：

- exact identity；
- Stage3 v13 edge/path posterior；
- path margin；
- covariance emission；
- Stage3 v12 partial-row gate；
- batch-end upper bound；
- frozen prior regression；
- truth/holdout invariants。

---

## 八、下周工作计划

### 1. 实现 Stage5 v8 Graph Matching 小集合审计

优先处理：

- 历史 5 个 stitched cases；
- `no_candidate_leg` 中存在 graph path 的 rejects；
- graph state 能显著降低 covariance-normalized emission 的 rejects；
- same-identity hard negatives；
- Stage5 v7 prior `229/345` regression protection。

输出必须分为：

- unique graph match；
- calibrated graph mixture；
- rejected/no-coverage。

### 2. 冻结并保护 Stage5 v7 基线

正式组合方式固定为：

```text
combined_v8 = frozen_stage5_v7 + safe_graph_incremental
```

不允许重新解释、删除或覆盖已有 `229` 个 unique batches 和 `345` 个 matched rows。

### 3. 开展 Stage6 时间不确定性敏感性实验

计划比较：

- S0：Stage5 v7 baseline；
- S1：v7 + graph unique；
- S2：v7 + graph unique + graph mixture；
- S3：关闭高 covariance/long-gap paths；
- S4：关闭 singleton-supported paths。

最终选择依据仍是 strict aircraft holdout，而不是 AMDAR 自身拟合度。

### 4. 评估完整 CTRV/IMM 的必要性

针对 turn/high-maneuver 子集比较：

- 当前 diagonal CV smoother；
- 多过程噪声线性 IMM；
- CTRV/RTS smoother。

只有 validation 明显改善且 locked safety 不退化时，才替换当前 Stage2 v8 smoother。

### 5. 整理可视化和论文材料

计划补充：

- raw leg 与 clean tracklet 对比图；
- isolated spike 修复案例；
- graph edge short/medium/long 分布；
- positive bridge 与 same-identity hard negative 对比；
- Stage5 v5/v6/v7 accepted batch 演进图；
- unique、mixture、no-coverage 三种数据语义示意图。

---

## 九、资源与可复现性

本周所有正式运行统一采用：

```bash
export POLARS_MAX_THREADS=25
```

并使用：

```text
slice_count = 25
workers = 25
```

空间策略：

- exact identity/date group 不跨 slice；
- 25 个 shards 互斥；
- 每个 ADS-B 点只属于一个 shard；
- 不复制 25 份全量输入；
- parquet 使用 zstd 压缩；
- Stage3 仅保存 compact case bank、posterior 和 diagnostics。

主要正式输出：

- Stage5 v6：`优化/数据处理/stage5_v6_hmm_viterbi_optimized_20260715/`
- Stage3 v12：`优化/数据处理/stage3_pseudo_amdar_v12_drop_dtw_optimized_20260716/`
- Stage5 v7：`优化/数据处理/stage5_v7_calibrated_partial_optimized_20260716/`
- Stage2 v8：`优化/数据处理/stage2_v8_track_graph_optimized_20260716/`
- Stage3 v13：`优化/数据处理/stage3_v13_bridge_validation_optimized_20260716/`
- 联合机器审计：`优化/数据处理/stage2_stage3_v8_v13_joint_audit_20260716.json`

---

## 十、导师汇报简版

本周完成了 AMDAR–ADS-B 数据关联的两轮升级。首先使用 HMM/Viterbi 和 Drop-DTW，将 Stage5 安全匹配结果从 `198 batches / 251 rows` 提升到 `229 batches / 345 rows`，unique batches 提升 `15.66%`、matched rows 提升 `37.45%`，同时保持 truth/holdout 违规为 0。随后针对 ADS-B 轨迹碎片化问题，从 1,916 万个原始点构建 local consistency、clean tracklet、协方差状态和平滑 track graph，减少 23,628 个 fragments，得到 11,306 个物理 graph hypotheses。新建的 Stage3 v13 bridge locked-test 中，wrong-path 为 `0.0827%`、catastrophic 为 `0.0645%`、posterior ECE 为 `0.000321`，全部安全门通过。

目前 Stage2/3 已具备进入 Stage5 v8 graph matching 小集合审计的条件，但尚不能宣称数据覆盖问题完全解决。历史 5 个 stitched rejects 中只有一个 identity group 存在物理可达 graph edge，其余仍属于 no-coverage 或物理不匹配。下周将冻结 Stage5 v7 的 `229/345` 基线，实施 graph unique/mixture/rejected 三层匹配，并通过 Stage6 strict aircraft holdout sensitivity 判断是否形成正式增量。

---

## 十一、本周结论

本周工作的主要结论为：

1. 序列级匹配和显式 partial-row exclusion 能在保持严格安全门的前提下，提高真实 AMDAR–ADS-B 利用率；
2. Track Graph 能恢复一部分被错误切碎的 ADS-B 轨迹证据，但不能解决真实 no-coverage；
3. association、partial drop 和 bridge 必须使用不同的 Stage3 validation policy，不能用同一个 posterior 越权放行；
4. 当前 Stage5 v7 已达到安全 merge target，Stage2 v8/Stage3 v13 已满足 Stage5 v8 的前置条件；
5. 后续应继续以 strict aircraft holdout 和 covariance-aware uncertainty propagation 为核心，而不是通过放宽阈值追求表面接受率。

