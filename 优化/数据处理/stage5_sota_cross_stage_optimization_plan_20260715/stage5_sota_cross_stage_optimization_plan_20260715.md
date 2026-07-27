# Stage5 SOTA 跨阶段优化方案

生成日期：2026-07-15

## 1. 阶段边界

本文的 Stage1-5 均指大框架：

- Stage1：AMDAR/观测清洗与批次语义整理；
- Stage2：ADS-B 轨迹分段、QC 和候选 source pool；
- Stage3：pseudo-AMDAR 闭环验证；
- Stage4：AMDAR support confidence 与下游角色；
- Stage5：真实 AMDAR-ADS-B 数据关联和时间投影。

本方案不改变以下不变量：AMDAR 始终 support-only；`effective_strict_truth=false`；`holdout_eligible=false`；Stage5 estimated time 不是逐点真值。

## 2. 当前基线与核心判断

最终安全基线：`198 accepted batches / 251 rows / 0.3503%`，距离 1% 所需的 `566` 批仍差 `368`。

当前主要拒绝项：

- `best_cost_gt_3=48615`；
- Stage4 T4=`3026`；
- monotonic=`1961`；
- no-candidate=`1368`；
- batch-end=`1048`。

核心判断：**候选数量已不是主瓶颈，真实几何和验证域不一致才是主瓶颈。** 最终候选表已覆盖 55153/56521 个批次，但 99% 以上仍无法通过真实空间轨迹门。

## 3. 已证伪的简单优化

以下方向已用本地数据做只读审计，不应再作为主路线：

| 方向 | 本地结果 | 判断 |
|---|---:|---|
| 时间窗扩大到 24h/4h | 新增 6905 个候选批次，新增安全 accepted=0 | 不做正式阈值放宽 |
| 批内顺序直接反转 | 1961 个 monotonic reject 中安全通过=0 | 不能只试 forward/reverse |
| 10+ 点 excluded long leg | 1548 个候选批次，pass=0 | 不直接恢复 |
| 两段 ADS-B 物理桥接 | 879 对，真实 pass-like=3 | 低优先级 |
| tail/date unique fallback | pass=0 | 无效 |
| tail/date multi-flight fallback | strict-B pass=0 | 无序列模型时无效 |
| 50% partial monotone subset | 45 批；70% 仅 5 批 | 仅次级研究分支 |

因此，继续添加启发式候选或放宽 cost/cross-track 不会产生有效提升。

## 4. SOTA 与本项目的对应关系

### 4.1 概率序列匹配，而非独立最近线段

HMM map matching 的核心是把每个观测点的空间似然作为 emission，把候选轨迹之间的可达性、顺序和运动连续性作为 transition，再用 Viterbi 求整段最优路径。它比逐点最近邻更适合稀疏、带噪和局部歧义观测。

本项目对应改造：

- state：ADS-B leg 上的离散点或线段位置；
- emission：水平距离、垂直距离、飞行阶段和观测误差协方差；
- transition：沿轨前进距离、允许速度、方向一致性、跨 gap 代价；
- latent variables：批内方向、下发延迟、点顺序可靠度；
- inference：Viterbi 最优路径 + forward-backward posterior。

### 4.2 Soft-DTW / Gromov-DTW

Soft-DTW 将 DTW 的硬最小路径替换为平滑 soft-min，可用于连续评分和参数学习；Gromov-DTW 能在两个序列特征并不完全同构时比较内部结构。

本项目建议：

- 首选可审计的 HMM/Viterbi 作为正式模型；
- Soft-DTW 作为候选 reranker 和消融实验；
- 不直接使用黑盒深度模型决定 accepted；
- 所有模型最终都输出可分解的距离、转移、覆盖率和 posterior。

### 4.3 多假设数据关联

JPDA/MHT 的核心是保留多个候选关联及其概率，而不是过早只保留 best candidate。对本项目而言，这允许把高置信唯一匹配与歧义混合分布分开：唯一匹配可生成窄 Stage6 seed，歧义匹配只生成 top-K mixture，不作为 point truth。

### 4.4 轨迹一致性与 ADS-B 数据质量

最新 ADS-B 质量研究强调：局部轨迹一致性可以发现单点字段看似合理、但航迹整体不连续的异常；不同接收站和时间戳机制也可能制造表观速度跳变。OpenSky 相关研究同时说明覆盖取决于接收站网络和信号环境，缺测不能通过匹配算法凭空恢复。

## 5. 跨阶段根因

### Stage1 → Stage5

当前 Stage5 使用 `amdar_observation_order` 排序，但 AMDAR 时间是批次语义。Stage1 应额外生成：

- `batch_order_reliability`；
- `batch_orientation_hypothesis`；
- `batch_shape_linearity`；
- `batch_spatial_outlier_fraction`；
- `identity_reliability_tail/flight/date`；
- PCA 主轴方向和累计沿轨距离；
- forward/reverse/unordered 三类候选顺序，而不是直接改变原始行。

审计显示简单 reverse 无新增，因此这些字段只能作为序列模型的先验，不能单独接受匹配。

### Stage2 → Stage5

Stage2 v7 只重评分继承自 v4 的 leg，没有重新分段。建议新增 Stage2 v8 track graph：

- raw ADS-B point-level timestamp/position consistency；
- constant-velocity 或 IMM/Kalman filtering；
- 同 tail/flight/date 的 tracklet graph；
- 物理可达边、gap、速度、转弯率和垂直率；
- 保留原 leg、stitched track 和不确定性，不覆盖原始数据。

但简单两段桥接只产生 3 个 pass-like，因此该阶段的目标应是改进 sequence state space 和异常检测，而不是承诺大幅增加 accepted。

### Stage3 → Stage5

这是当前最需要优先修复的阶段。现有 v8/v9/v10 pseudo case 从真实 ADS-B leg 截取后，再在几乎同一候选宇宙中寻找源 leg，因此 validation q90 只有约 2-5 秒，而真实 Stage5 有 48615 个 geometry failure。pseudo 和 real 的难度明显不匹配。

Stage3 v11 必须加入 hard negatives 和 domain randomization：

- 同 tail/date 的错误 flight；
- 同 flight/date 的错误 tracklet；
- exact identity 但空间不一致；
- 跨午夜 service-date 扰动；
- callsign/flight normalization corruption；
- ADS-B 缺段、长 gap、接收站时间偏差；
- AMDAR 点顺序交换、反转、局部乱序和空间 outlier；
- 真实 batch-size、phase、confidence-tier 分布重加权；
- candidate policy 必须与真实 Stage5 完全一致。

需要新增 pseudo-real domain-gap 报告，而不能只看 pseudo locked-test 自身指标。

### Stage4 → Stage5

Stage4 不是当前主要数量瓶颈：T4 批次本身的 cost/cross-track 中位数也很差。不要通过提高 T1/T2 覆盖来宣称 Stage5 会自然改善。

建议把 Stage4 输出拆成两条正交轴：

1. `observation_support_conf`：风、温度、批次代表性等重构权重；
2. `association_prior_conf`：身份完整度、时间语义、批内形状和候选可用性。

Stage5 只把第二条作为候选 prior；匹配完成后再与 observation support confidence 合成下游权重。禁止用 confidence 推导 truth。

### Stage5 本体

Stage5 v6 应拆成四层：

1. candidate retrieval：exact identity、规范化身份、route fingerprint 和保守空间索引；
2. candidate sequence scoring：HMM/Viterbi 为主，Soft-DTW 为对照；
3. posterior calibration：validation 调参、locked-test 报告；
4. output roles：unique accepted、ambiguous mixture、diagnostic reject。

## 6. 推荐实施顺序

### P0：冻结基线与审计集

- 冻结 198/251 基线和所有 truth invariants；
- 固定 25-slice / POLARS_MAX_THREADS=25；
- 建立 hard-negative case bank；
- 记录每个实验相对 198 批的新增、丢失和重叠。

### P1：Stage3 v11 Domain-Matched Validation

这是第一优先级。没有真实难度的 Stage3，任何 SOTA scorer 都无法安全调参。

输出：

- `pseudo_amdar_v11_hard_negative_cases.parquet`；
- `candidate_policy_domain_gap_report.json`；
- 按 corruption type 的 validation/locked-test 指标；
- posterior calibration、Brier score、ECE；
- real Stage5 feature-distribution overlap。

### P2：Stage5 v6 HMM/Viterbi Scorer

先只使用现有候选表，不改变候选宇宙：

- emission：Huber horizontal distance + vertical normalized distance；
- transition：non-decreasing along-track progress、速度和阶段约束；
- forward/reverse/order-uncertain 三种路径假设；
- latent downlink delay 只影响 time posterior，不修改空间位置；
- top-K candidate posterior；
- best posterior、entropy、margin、effective candidate count。

这一步的目标是证明序列模型比当前 mean-cost 更可靠，而不是直接追求 1%。

### P3：Stage1 Geometry Features + Robust Partial Alignment

- 仅对 P2 仍拒绝、且存在局部好点的批次运行 trimmed/partial alignment；
- 最低覆盖建议从 validation 选择，不能低于 70% 直接用于 unique match；
- 50% 覆盖只能 diagnostic mixture；
- 被剔除的 AMDAR rows 必须逐行标记 reject reason。

本地审计显示 70% 分支只有约 5 个现有 pass-like，故为低收益补充。

### P4：Stage2 v8 Track Graph

- 对 AMDAR identity universe 重新构建 track graph；
- 使用 Kalman/IMM 状态和物理 bridge probability；
- 在 Stage3 v11 中验证 stitched states；
- 只有 validation 获得真实提升后才进入 Stage5。

简单桥接只有 3 个 pass-like，因此 P4 优先级低于 P1/P2。

### P5：新增 ADS-B 覆盖

如果目标仍是 `>=1%`，这是最可能的必要条件：

- 获取 AMDAR 时段/区域/机尾更完整的 ADS-B 数据；
- 对接收站覆盖和时间戳来源做审计；
- 重新运行 Stage2 → Stage3 → Stage4 → Stage5；
- 禁止只替换 Stage5 candidate table。

## 7. 实验矩阵

| 实验 | 改动 | 候选宇宙 | 主要问题 | 优先级 |
|---|---|---|---|---|
| E0 | 当前 mean-cost | 当前 | baseline | 冻结 |
| E1 | HMM/Viterbi | 当前 | 序列一致性 | 最高 |
| E2 | Soft-DTW reranker | 当前 | 平滑对齐 | 高 |
| E3 | hard-negative posterior calibration | 当前 | pseudo-real gap | 最高 |
| E4 | partial alignment | 当前 | 局部异常点 | 中低 |
| E5 | Stage1 order/shape prior | 当前 | 批内顺序不确定 | 中 |
| E6 | Stage2 track graph | 新 stitched states | ADS-B 碎片 | 中低 |
| E7 | 新 ADS-B 数据源 | 扩大 | 覆盖不足 | 达到 1% 的关键 |

## 8. 验收门槛

### Stage3 v11

- validation 调参，locked-test 只报告；
- wrong-leg `<=1%`，最大回退线 `<=2%`；
- catastrophic `<3%`；
- hard-negative false acceptance 必须分类型报告；
- posterior ECE `<=0.05` 或显著优于 baseline；
- pseudo 与 real Stage5 的 cost/cross-track/candidate-count 分布差距必须缩小。

### Stage5 v6

- 保留现有 198 个 accepted batches，除非有逐批次可解释证据；
- unique accepted 新增至少 `+10` 批才值得合并；
- 新增分支 locked wrong-leg 不得超过 1%；
- 不允许以 ambiguous mixture 冒充 unique accepted；
- mixture rows 只能进入 Stage6 mixture distribution；
- AMDAR strict truth 和 holdout 始终为 0。

### 现实目标

- 同一数据源、仅算法改进：建议把第一阶段目标设为 `208-248` unique accepted batches，而不是直接承诺 566；
- ambiguous calibrated mixtures 可单独提高时间信息利用率，但不得计入 unique acceptance；
- `>=566` 需要上游覆盖发生实质变化后重新评估。

## 9. 存储和计算口径

- `POLARS_MAX_THREADS=25`；
- `slice_count=25`；
- workers `<=25`；
- raw ADS-B point table 只保留一份；
- 每个实验只输出 compact case/candidate/posterior/diagnostic tables；
- 不复制 25 份全量中间数据；
- 大型序列 scorer 临时状态放 `/tmp`，正式目录只保存可复现实验摘要。

## 10. 推荐下一步

不要先改 Stage4 阈值，也不要继续扩大 Stage5 时间窗。下一次正式实现应从 **Stage3 v11 hard-negative/domain-matched validation** 开始，然后实现 **Stage5 v6 HMM/Viterbi sequence scorer**。只有这两步能判断当前 198 批中有多少是真正可安全突破的算法空间。

## 11. SOTA 参考资料

1. Newson, P. and Krumm, J. Hidden Markov Map Matching Through Noise and Sparseness. ACM GIS 2009.
2. Cuturi, M. and Blondel, M. Soft-DTW: a Differentiable Loss Function for Time-Series. ICML/PMLR 2017.
3. Cohen, S. et al. Aligning Time Series on Incomparable Spaces. AISTATS/PMLR 2021. Gromov Dynamic Time Warping.
4. Reid, D. B. An Algorithm for Tracking Multiple Targets. IEEE Transactions on Automatic Control, 1979. Multiple Hypothesis Tracking.
5. Will, H. et al. Air Traffic and OpenSky Network in 2024. OpenSky Report 2025.
6. The OpenSky Network: A Swiss Army Knife for Air Traffic Security Research. IEEE DASC 2017.
7. Detecting Radio-Frequency Interference in Crowdsourced ADS-B Data Using Local Track Consistency. arXiv:2606.14002, 2026.
8. Evaluation of Map Matching Algorithms. Sensors 2024, 24, 6511.

