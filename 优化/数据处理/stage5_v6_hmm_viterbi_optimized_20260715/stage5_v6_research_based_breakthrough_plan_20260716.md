# Stage5 v6 后续突破方案：基于相关研究的可实施路线

生成日期：2026-07-16

## 1. 结论

存在继续改善的方法，但不能继续依赖放宽 cost、cross-track、posterior、batch-end 或把低覆盖 mixture 直接改名为 unique。

当前最值得实施的路线是：

1. **Stage3 v12 raw-sequence Drop-DTW/partial alignment validation**：为 partial match 单独建立包含丢点、离群行、乱序、错误 leg 和 track gap 的序列级 calibration/validation/locked-test；
2. **Stage5 v7 calibrated partial matcher**：用验证选择的 drop penalty、连续覆盖、路径稳定性和 posterior，重新审计当前 20 个 mixtures 与 4 个未通过 posterior 的 `>=70%` partial cases；
3. 若仍不能安全新增 3 批，再做 **Stage2 v8 local-consistency + IMM/Kalman track graph**，从原始 ADS-B 点重新构建 tracklet 和 stitched states；
4. 若目标是 `>=1%` 而不只是补足 `+3`，最终仍需要新增 ADS-B/ADS-C/其他轨迹覆盖证据。

## 2. 当前本地证据

Stage5 v6 当前状态：

- 冻结基线：`198 unique batches / 251 rows`；
- v6 安全新增：`7 unique batches / 23 rows`；
- 最终：`205 unique batches / 274 rows`；
- 距离 SOTA merge target `208` 仍差 `3` 批；
- 当前有 `20` 个 calibrated mixtures，association posterior 均不低于 `0.941176`；
- 20 个 mixtures 的 candidate posterior 均不低于 `0.90`，主要不能成为 unique 的原因不是候选歧义，而是覆盖率只有 `50%-66.7%`；
- 另有 5 个 `>=70%` partial cases，其中 1 个已接受，其余 4 个主要被 aggregate posterior 拒绝；
- stitched track 中有 5 个通过物理门，但当前 aggregate Stage3 v11 posterior 全部不足，说明 stitched states 需要单独验证，不能直接放行。

因此，剩余问题本质是：**当前 Stage3 v11 posterior 没有直接建模“允许丢弃多少行、丢弃行是否真的是空间离群点、保留路径是否稳定”**。

## 3. 研究启示与项目映射

### 3.1 Drop-DTW：允许显式丢弃不匹配元素

Drop-DTW 把“匹配成本”和“丢弃成本”放入同一个动态规划，而不是先固定 70% 覆盖再做硬判断。它适合两个序列只部分对应、存在背景/离群元素的场景。

项目映射：

- AMDAR 行可选择 match 或 drop；
- ADS-B segment 可选择使用或跳过；
- drop penalty 不能人工指定，必须由 Stage3 v12 validation 选择；
- unique acceptance 由 drop pattern、连续覆盖、路径成本和 posterior 共同决定；
- 被 drop 的 AMDAR 行继续逐行保存 reject reason。

这比当前“先找最长单调子序列，再固定 coverage>=70%”更有希望安全处理 50%-66.7% mixtures。

### 3.2 Robust/Partial Optimal Transport：处理离群点和不等质量

部分最优传输和 robust optimal transport 允许只传输可信质量，并限制离群质量对整体对齐的影响。它可以作为 Drop-DTW 的 reranker 或独立消融，不应直接黑盒决定 accepted。

项目映射：

- AMDAR 每行质量由 Stage1/Stage4 observation support confidence 提供；
- ADS-B segment 质量由 Stage2 local consistency、sampling gap 和 source tier 提供；
- 运输质量代表“被解释的观测比例”，但 unique 阈值必须通过 validation/locked-test 确定；
- 输出 transport mass、unmatched mass、最大连续匹配段和候选间 margin。

### 3.3 Local Track Consistency：先修复错误分段和异常点

ADS-B 局部轨迹一致性研究表明，时间戳或接收异常可以在局部制造不合理速度/位置变化；先做 track consistency 检查，能够避免把异常点误当真实断点。

项目映射：

- 在 Stage2 v8 对原始点计算局部速度、加速度、转弯率、垂直率和时间戳一致性；
- 将“接收异常”与“真实机动/真实 gap”分开；
- 不覆盖原始 leg，而是输出 raw leg、clean tracklet、stitched hypothesis 三层状态；
- stitched states 必须进入 Stage3 v12 corruption/locked-test 后才能用于 Stage5 unique。

### 3.4 IMM/Kalman + forward/backward smoothing：重建 track graph

航空轨迹重建研究通常将数据关联、IMM/Kalman 状态估计、平滑和 tracklet 重连接组合使用。该路线适合当前“简单 bridge 有物理 pass-like，但 posterior 不足”的情况。

项目映射：

- 水平方向：constant velocity/turn rate IMM；
- 垂直方向：按 ASC/DES/LVR 使用自适应 Kalman；
- forward filter + backward smoother 给出 gap 区间状态及协方差；
- tracklet edge 需要时间、位置、速度、航向、垂直率和 identity 一致；
- Stage5 emission 使用状态协方差归一化，而不是只用固定 km/m 权重。

### 3.5 多假设和轨迹推断：mixture 本身也是数据利用

多假设轨迹推断研究强调，在观测不足时保留 top-K 轨迹及概率，而不是强制唯一选择。当前 20 个 mixtures 应首先进入 Stage6 mixture distribution；只有新验证证明可唯一化时才提升为 unique。

## 4. 推荐实施：Stage3 v12 Sequence-Drop Validation

### 4.1 输入与 case bank

从 Stage3 v8 clean pseudo cases 和真实 Stage5 v6 诊断分布生成 raw sequence cases，至少包含：

- clean exact leg；
- wrong leg / wrong flight / wrong tracklet；
- AMDAR 单点和连续块空间 outlier；
- 10%、20%、30%、40%、50% 行 drop；
- reverse、局部交换、随机乱序；
- ADS-B 单点缺测和连续 gap；
- tracklet split 与可达/不可达 bridge；
- receiver timestamp bias；
- batch size、phase、source tier 按真实 Stage5 重加权。

必须保存原始序列和 row-level ground-truth correspondence，不能只保存 aggregate features。

### 4.2 模型对照

至少比较：

- E0：当前 partial Viterbi；
- E1：Drop-DTW；
- E2：Drop-DTW + Huber emission；
- E3：partial/robust optimal transport reranker；
- E4：Drop-DTW + association posterior calibration；
- E5：tracklet stitched state，仅作为 validation 实验。

### 4.3 新增特征

- `matched_row_fraction`；
- `matched_contiguous_fraction`；
- `drop_fraction`；
- `largest_dropped_block_fraction`；
- `drop_cost_per_row`；
- `matched_cost_q50/q90/max`；
- `path_progress_monotonicity`；
- `path_speed_consistency`；
- `leave_one_out_path_stability`；
- `forward_reverse_score_margin`；
- `candidate_sequence_margin`；
- `tracklet_bridge_probability`；
- `state_uncertainty_normalized_cost`。

### 4.4 阈值选择

只在 validation 选择：

- AMDAR row drop penalty；
- ADS-B segment drop penalty；
- minimum matched fraction；
- minimum contiguous fraction；
- unique posterior；
- candidate margin；
- bridge probability。

locked-test 只报告，不得调参。

### 4.5 质量门

- wrong-leg/hard-negative rate `<=1%`；
- catastrophic rate `<3%`；
- posterior ECE `<=0.05`；
- 每种 corruption false acceptance `<=2%`；
- dropped-row identification precision/recall 分类型报告；
- 原 205 unique batches 全部保留；
- 新增 unique 至少 `+3` 才允许形成 Stage5 v7 merge；
- 20 mixtures 不得预先算作 unique；
- truth/holdout 违规为 0。

## 5. Stage5 v7 的目标审计集

第一优先级只审计小集合，避免再次全量盲跑：

1. 当前 20 个 `50%-66.7%` mixtures；
2. 当前 4 个 `>=70%` 但 posterior 未通过的 partial cases；
3. 5 个 physical stitched-track cases；
4. 与上述 batch 同 tail/flight/date 的 hard negatives；
5. 原 205 unique batches 作为回退保护集。

只有该小集合验证显示至少 3 个新增且 locked safety 达标，才运行全量 25-slice Stage5 v7。

## 6. 如果 Drop-DTW 仍不足

### Stage2 v8 Track Graph

1. 从单份原始 ADS-B 点表重新做 local consistency；
2. 使用 IMM/Kalman + smoother 输出状态和协方差；
3. 构建 same identity/date tracklet graph；
4. edge 只保留物理可达连接；
5. Stage3 v12 对 raw/clean/stitched state 分别验证；
6. Stage5 使用通过验证的 graph state，不在旧 leg 上继续启发式拼接。

### 新数据覆盖

如果目标恢复为 `>=566 batches / 1%`，仅靠当前算法证据不现实。需要增加相同日期、机尾、航班和空间区域的 ADS-B，或引入能补充远洋/偏远区域覆盖的 ADS-C/其他轨迹数据，再完整重跑 Stage2→Stage3→Stage4→Stage5。

## 7. 不推荐路线

- 把 posterior `0.805` 直接降到 `0.80`；
- 把 50% partial mixture 直接计 unique；
- 取消 batch-end 上界；
- cross-track/cost 继续放宽；
- 未经 Stage3 v12 验证直接接受 stitched bridge；
- 用深度模型直接输出 accepted 而不提供路径、drop、posterior 和 corruption 解释；
- 在 locked-test 上选 drop penalty 或 coverage threshold。

## 8. 推荐执行顺序

1. 新建 `amdar_unified_stage3_v12_drop_dtw_20260716.py`；
2. 生成 raw-sequence case bank 和 row-level truth；
3. 实现 Drop-DTW 与当前 partial Viterbi 对照；
4. validation 选择 drop/coverage/posterior 门；
5. locked-test 只报告；
6. 只读审计 20 mixtures、4 个 near-pass partial 和 5 个 physical bridge；
7. 若安全新增 `>=3`，再生成 Stage5 v7；
8. 否则停止 Stage5-only 优化，转 Stage2 v8 track graph 或新增覆盖。

## 9. 相关研究

1. Newson, P.; Krumm, J. *Hidden Markov Map Matching Through Noise and Sparseness*. ACM GIS, 2009.
2. Cuturi, M.; Blondel, M. *Soft-DTW: a Differentiable Loss Function for Time-Series*. ICML/PMLR, 2017.
3. Dvornik, N. et al. *Drop-DTW: Aligning Common Signal Between Sequences While Dropping Outliers*. NeurIPS, 2021.
4. Nietert, S. et al. *Outlier-Robust Optimal Transport: Duality, Structure, and Statistical Analysis*. AISTATS/PMLR, 2022.
5. Li, T. et al. *Detecting Radio-Frequency Interference in Crowdsourced ADS-B Data Using Local Track Consistency*. 2026.
6. García-Fernández, Á. F. et al. *SASS-C: Novel track reconstruction techniques for Space-Based ADS-B data*. 2022.
7. Liu, Y. et al. *InferTra: Inferring Missing Trajectories from Incomplete Data*. WWW, 2022.
8. OpenSky Network. *Air Traffic and OpenSky Network in 2024*. OpenSky Report, 2025.
