# centralized_v1 Stage4/Stage5 文献支持优化总方案（截至 2026-06-12）

适用范围：

1. 只讨论 `strict aircraft holdout` 正式验证口径。
2. 所有主指标只允许在 `strict_holdout_no_leakage = True`、`motion_used_as_wind = False` 前提下比较。
3. 本文中的“优化方法”尽量绑定 2024-2025 的直接相关文献；少量更早的方法学只作为背景。
4. 本文中的“数值门槛”是结合你当前项目风险和现有基线做出的工程门槛，不是文献原文直接给出的数字。

---

## 1. 先给结论

当前最稳正式主线仍然是：

```text
Stage4 default = tp26_thr11_preserve
```

当前真正的问题不是“整体完全无效”，而是：

1. 高空 `9-12km / 12km+` tail 仍主导误差。
2. `role conflict + sparse support + temporal mismatch + vertical mismatch` 叠加后，会产生少量但非常贵的极端点。
3. Stage4 的全局 soft-weight、全局 vertical dynamic、全局 point-wise localization 都已经证明过于激进。
4. Stage5 的 residual PINN 只在极窄门控下表现出 tiny safe signal；一旦允许 `12km+ residual` 非零，就会重新打穿正式 gate。

因此最优路线不是继续做“更大、更全场”的修正，而是：

1. 先把 Stage4 做成 `representation-aware + support-aware + physics-constrained localization`。
2. 再把 Stage5 改成 `uncertainty-gated residual correction`，并且把 `12km+` 默认视为 residual 禁区，直到有新证据。
3. 所有优化都必须先过 `200-frame smoke`，再过 `full-5614 strict holdout`，否则不能进正式主线。

---

## 2. 当前已经拿到的正式指标

### 2.1 Stage4 当前正式 200 帧主基准

固定 benchmark：

```text
frames = 200
holdout points = 530
```

| 方法 | frame RMSE | frame MAE | weighted RMSE | weighted MAE | P95 | P99 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `baseline_aircraft` | 11.6898 | 10.3011 | 18.9184 | 10.3509 | 42.6407 | 74.2244 |
| `adaptive_v3` | 8.4570 | 7.3067 | 14.9326 | 7.0682 | 28.1452 | 63.2337 |
| `tp26_thr11_preserve` | 8.2243 | 7.0819 | 14.7690 | 6.8545 | 27.9861 | 58.7838 |

当前默认 `tp26_thr11_preserve` 相对 `baseline_aircraft` 的主收益：

```text
weighted RMSE: 18.9184 -> 14.7690   (-21.9%)
frame RMSE:    11.6898 -> 8.2243    (-29.6%)
P95 RMSE:      42.6407 -> 27.9861   (-34.4%)
```

### 2.2 Stage4 当前 full-5614 正式基线

来自本地 `rep5614_analysis/tp26_vs_rep_soft_weight_v1_full5614.md` 的 baseline 指标：

```text
frames = 5614
holdout_points = 15054
baseline = tp26_thr11_preserve
```

| 指标 | 当前正式值 |
| --- | ---: |
| frame mean RMSE | 8.418875 |
| frame mean MAE | 7.408240 |
| weighted RMSE | 14.520015 |
| weighted MAE | 6.475666 |
| median frame RMSE | 4.539204 |
| frame P95 RMSE | 31.783087 |
| frame P99 RMSE | 73.325466 |
| 12km+ vector RMSE | 17.585340 |
| 5-15mps light wind RMSE | 5.510587 |
| 5-15mps light wind MAE | 4.188920 |
| floor10 relative error MAE | 0.255017 |

### 2.3 Stage4 非默认候选里，已经明确拿到的结果

#### `tp26_rep_soft_weight_v1`

200 帧 formal gate：

| gate | baseline `tp26_thr11_preserve` | candidate `tp26_rep_soft_weight_v1` | 结果 |
| --- | ---: | ---: | --- |
| weighted RMSE | 14.769036 | 14.755381 | PASS |
| frame P95 | 27.986111 | 27.947974 | PASS |
| frame P99 | 58.783770 | 58.756881 | PASS |
| 12km+ vector RMSE | 19.917698 | 19.884741 | PASS |
| light wind RMSE | 5.195877 | 5.165311 | PASS |
| light wind MAE | 4.185283 | 4.160541 | PASS |
| floor10 relative MAE | 0.282804 | 0.281212 | PASS |
| new light/mod tail failure | 0 | 0 | PASS |

full-5614 pairwise：

| gate | baseline | candidate | 结果 |
| --- | ---: | ---: | --- |
| weighted RMSE | 14.520015 | 15.303054 | FAIL |
| frame P95 | 31.783087 | 33.069294 | FAIL |
| frame P99 | 73.325466 | 73.840188 | FAIL |
| 12km+ vector RMSE | 17.585340 | 18.630932 | FAIL |
| light wind RMSE | 5.510587 | 5.852620 | FAIL |
| light wind MAE | 4.188920 | 4.505876 | FAIL |
| floor10 relative MAE | 0.255017 | 0.274576 | FAIL |
| new light/mod tail failure | 0 | 9 | FAIL |

结论：

```text
200 帧小幅 PASS
5614 帧明确 FAIL
不能升默认
只能保留为 representation / reliability 方向的诊断候选
```

#### 其他已明确 FAIL 的 Stage4 分支

| 候选 | 最核心结论 |
| --- | --- |
| `support_role_height_aware` | 高空 role conflict 下灾难性放大 |
| `sparse_temporal_gated CMA/NWP` | 能救部分 tail，但污染 light wind |
| `guarded_vertical_dynamic_v2` | 比 SRHA 保守，但仍轻微污染 `12km+ / light / floor10` |
| `tp26_point_regime_localization_v1` | 500m/6min 稀疏支持下，过细 point-wise localization 反而更差 |

### 2.4 Stage5 当前正式状态

#### point-level safest nonzero candidate

```text
checkpoint = cap1p0_seed20260609_w512_l6
gate       = vertical_gap_ge20_not_light
scale      = 1.0
```

locked test：

| metric | baseline | gated Stage5 | delta |
| --- | ---: | ---: | ---: |
| RMSE | 9.896785 | 9.892352 | -0.004433 |
| MAE | 5.217920 | 5.216535 | -0.001385 |
| P95 | 13.157155 | 13.037976 | -0.119179 |
| P99 | 43.020285 | 42.984991 | -0.035294 |
| light RMSE | 5.086997 | 5.086997 | 0.000000 |
| floor10 relative MAE | 0.197422 | 0.197393 | -0.000029 |

结论：

```text
有真实但极小的 point-level signal
还不足以说明 full-field 一定值得做
```

#### field-v1 smoke

| Metric | `tp26_thr11_preserve` | Stage5 field-v1 | Direction |
| --- | ---: | ---: | --- |
| Holdout-weighted RMSE | 14.7690356 | 14.7714931 | worse |
| Holdout-weighted MAE | 6.8544542 | 6.8541252 | slightly better |
| Frame mean RMSE | 8.2243094 | 8.2190661 | better |
| Frame mean MAE | 7.0819089 | 7.0812025 | better |
| Frame P95 RMSE | 27.9861110 | 27.9861110 | tie |
| Frame P99 RMSE | 58.7837702 | 58.7837702 | tie |
| 12km+ vector RMSE | 19.9176978 | 19.9417944 | worse |

结论：

```text
formal gate FAIL
field 应用结构安全，但收益不够且 12km+ 仍受伤
```

#### field-v2 replay

| case | variant | result | changed points | weighted RMSE | 12km+ RMSE | 说明 |
| --- | --- | --- | ---: | ---: | ---: | --- |
| safest PASS | `alt12_off_cap10p0_riskoff_cleanoff` | PASS | 2 | `14.7690356 -> 14.7578689` | `19.9176978 -> 19.9176978` | 极小安全收益，不碰 `12km+ residual` |
| best nonzero-`alt12` candidate | `alt12_0p25_cap10p0_riskoff_cleanoff` | FAIL | 7 | `14.7690356 -> 14.7611852` | `19.9176978 -> 19.9235639` | 总体略好，但高空 gate 被打穿 |

结论：

```text
只要 `12km+ residual > 0`，当前 Stage5 就还不安全
```

---

## 3. 当前遇到的问题，按证据逐条拆开

### 3.1 P1：高空 tail 仍主导大部分误差预算

证据：

1. 200 帧里 `alt_12km_plus` 只有 222 点，但 SSE share 已达 `0.761818`。
2. full-5614 下 baseline 的 `12km+ vector RMSE = 17.585340`，明显高于低层。
3. `vertical_speed_gap_bin = vgap_ge30` 只有 17 个点，baseline 已达 `96.233249`，候选恶化到 `107.555847`。

解释：

```text
高空不是“均匀偏差”，而是极少数高代价点主导 tail
```

### 3.2 P2：current/context role conflict 在高 gap 区间很贵

证据：

1. `role_conflict_at_point = role_conflict` 的 2997 点，baseline vector RMSE `18.472347`，候选 `21.178670`。
2. `nearest_role_gap_bin = gap_ge30` 的 1007 点，baseline `27.107158`，候选 `30.591070`。
3. `role_conflict_component_gap_bin = gap_ge30` 的 959 点，baseline `28.861663`，候选 `33.668149`。

解释：

```text
一旦 current anchor 和 context wind 本身冲突，简单 global reweighting 会放大方向错误
```

### 3.3 P3：stale context 不是完全没用，但不能按统一时间权重硬吃

证据：

1. `context_time_conf_bin = timeconf_0_4_0_6` 的 2394 点，baseline `16.453636`，候选 `17.936028`，恶化 `1.482391`。
2. `timeconf_ge0_6` 也不是零风险，只是恶化较小。

解释：

```text
时间衰减不是一个全局常数
它必须跟 height / support / role gap 联动
```

### 3.4 P4：稀疏支撑区本质上是外推，不是插值

证据：

1. `nearest_current_count_bin = count_0` 的 4933 点，baseline `20.231176`。
2. `nearest_current_count_bin = count_1` 的 5349 点，候选相对 baseline 恶化 `1.443092`。
3. `nearest_distance_bin = dist_ge6` 的 382 点，baseline 已有 `40.391248`。
4. top extreme tail 大量落在 `context_wind/count_0` 或 `count_1`。

解释：

```text
这类点不能再假装和 dense support 一样可验证
```

### 3.5 P5：当前 departure 远大于 aircraft observation error prior，本质是 representation + reconstruction error

证据：

1. baseline component RMSE `10.267201`。
2. EMADDC sigma RMS 只有 `2.743868`。
3. `comp / EMADDC = 3.748032`。
4. `excess variance fraction = 0.928580`。

解释：

```text
绝大部分误差不是飞机风观测仪器误差本身
而是网格表示误差、时空错配、局地支撑不足、operator mismatch
```

### 3.6 P6：当前系统非常 tail-sensitive，不能只优化 mean RMSE

证据：

1. 200 帧里 `high_vector_error_ge30mps` 只有 21 点，但 SSE share `0.811075`。
2. `qc_review_flag` 302 点，SSE share `0.937646`。
3. 多个候选虽然均值项略好，但会打穿 `P95 / P99 / 12km+ / light wind / floor10`。

解释：

```text
mean-only tuning 会把系统推向“看起来平均更好，但业务上更危险”
```

### 3.7 P7：Stage5 的 full-field residual 目前只在极小范围安全

证据：

1. point-level safest candidate 的 RMSE 改善只有 `0.004433 m/s`。
2. field-v1 formal gate FAIL。
3. field-v2 中所有 `alt12_scale > 0` 变体全部 FAIL。

解释：

```text
Stage5 当前学到的是“局部修补信号”
不是“可以全场推广的替代场”
```

### 3.8 P8：Stage5 还没有可信的不确定性控制和 abstention 机制

证据：

1. 当前 gate 主要靠手工规则，而不是 calibrated uncertainty。
2. 只要 residual 进入高空/低支撑/冲突区，就会出现 real degradation。

解释：

```text
没有 uncertainty-aware abstention，Stage5 很容易在最不该改的地方硬改
```

---

## 4. 优化必须达到什么指标才算过关

## 4.1 统一硬门槛

所有 Stage4 / Stage5 候选都必须同时满足：

```text
strict_holdout_no_leakage = True
motion_used_as_wind = False
比较必须在相同 frame set、相同 holdout 口径下进行
```

## 4.2 200-frame smoke gate

这是所有新方法的第一层 cheap screen。若以下任一条失败，直接不进 full-5614：

| 指标 | 当前 baseline (`tp26_thr11_preserve`) | smoke 过线要求 |
| --- | ---: | --- |
| weighted RMSE | 14.769036 | 不高于 baseline |
| frame P95 RMSE | 27.986111 | 不高于 baseline |
| frame P99 RMSE | 58.783770 | 不高于 baseline |
| 12km+ vector RMSE | 19.917698 | 不高于 baseline |
| light wind RMSE | 5.195877 | 不高于 baseline |
| light wind MAE | 4.185283 | 不高于 baseline |
| floor10 relative MAE | 0.282804 | 不高于 baseline |
| new light/mod tail failure | 0 | 必须仍为 0 |

## 4.3 full-5614 default promotion gate

这是正式 gate。若任一条失败，不能升默认：

| 指标 | 当前 full-5614 baseline | formal 过线要求 |
| --- | ---: | --- |
| weighted RMSE | 14.520015 | 不高于 baseline |
| weighted MAE | 6.475666 | 不高于 baseline |
| frame mean RMSE | 8.418875 | 不高于 baseline |
| frame P95 RMSE | 31.783087 | 不高于 baseline |
| frame P99 RMSE | 73.325466 | 不高于 baseline |
| 12km+ vector RMSE | 17.585340 | 不高于 baseline |
| 5-15mps light RMSE | 5.510587 | 不高于 baseline |
| 5-15mps light MAE | 4.188920 | 不高于 baseline |
| floor10 relative MAE | 0.255017 | 不高于 baseline |

## 4.4 工程上“值得升默认”的额外门槛

即使 formal gate 通过，也不代表值得升默认。为了避免“为了 1-2 个点的 0.01 m/s 改进而引入长期复杂度”，再加一个工程门槛：

```text
至少满足以下两条中的一条：

A. full-5614 weighted RMSE 改善 >= 0.05 m/s
B. 在目标问题层（12km+ / gap_ge30 / count_0-1 / timeconf_0.4-0.6）中，至少两个 strata 的 RMSE 改善 >= 5%，且所有硬门槛仍通过
```

这个门槛是工程推断，不是文献原值。

## 4.5 Stage5 单独门槛

### point-level research continuation gate

如果做完 Stage5 新训练后仍然达不到：

```text
point-level RMSE improvement >= 0.02 m/s
P95 improvement >= 0.10 m/s
light RMSE 不恶化
floor10 relative MAE 不恶化
90% uncertainty interval coverage 落在 87%-93%
```

则 Stage5 不应该继续推进到 field。

### field-level smoke gate

如果 Stage5 point-level 过线，field smoke 还必须满足：

```text
200-frame 所有硬门槛通过
12km+ residual 默认关闭
changed holdout points 不应只是 1-2 个点就宣称“方法有效”
若 weighted RMSE 改善 < 0.02 m/s 且 changed points <= 2，则只保留为 research note，不升默认
```

---

## 5. Stage4 怎么优化：问题、文献、方法、门槛，一一对应

### 5.1 S4-A：把 observation / representation error 显式建模，不再用单一全局可信度

对应问题：

```text
P4 sparse support
P5 representation error
P6 tail-sensitive verification
```

文献依据：

1. Goux et al. (2025) 说明观测误差相关性被忽略时，简单对角假设会丢掉小尺度有效信息；当相关长度较短时，方差膨胀是可接受近似，但显式相关建模更好。[R1]
2. Gupta et al. (2024) 把稀疏观测区分为 good / reasonable / bad 三个 zone，意味着稀疏区不应与 dense support 区混为一谈。[R4]

这里的工程推断：

```text
你当前问题不是 aircraft instrument sigma 不够准
而是 point-to-grid / time-window / sparse-support 的 representation sigma 没有单独进权重模型
```

建议改法：

1. 保留 `de Haan / EMADDC` 作为观测误差下界。
2. 额外拟合 `sigma_repr(height, support, nearest_distance, role_gap, vertical_gap, time_conf)`。
3. 最终权重改成：

```text
sigma_total^2 = sigma_obs^2 + sigma_repr^2
weight ~ 1 / sigma_total^2
```

4. 对同一 aircraft / 同一时间窗 / 相邻高度层的观测，允许小范围相关误差模型；先从扩散型 banded correlation 或局部方差膨胀做起，不要一上来做全矩阵。

执行 if/else：

```text
if holdout points in a bin < 300:
    回退到父层级 bin，避免过拟合 sigma_repr
else:
    单独拟合该 bin 的 sigma_repr

if estimated obs-error correlation length is short:
    先做 diagonal variance inflation
else:
    再做 local correlated-R / diffusion-R

if point is count_0 or dist_ge6:
    必须显式提高 sigma_repr
else:
    不允许无脑全局降权或升权
```

成功标准：

```text
full-5614 通过全部硬门槛
12km+ vector RMSE 改善 >= 3%
count_0/count_1 两层至少一层 RMSE 改善 >= 5%
0-3km 不得恶化超过 0.05 m/s
```

### 5.2 S4-B：不要再做完全自由的 point-wise localization，改做“受约束的 physics-constrained localization”

对应问题：

```text
P1 high-alt tail
P2 role conflict
P4 sparse support
```

文献依据：

1. Gilpin et al. (2025) 在高维 localization 对比里发现：传统 distance-based localization 往往仍是最稳的，非距离型方法最多带来边际收益，而且调参成本更高。[R2]
2. Er and Meldi (2025) 则说明 localization 的空间形状可以跟随瞬时流场特征变化，而不是永远固定不变。[R3]

这里的工程推断：

```text
你已经证明“完全自由的 point-regime localization”会失败
因此下一步不是更自由，而是更受约束
```

建议改法：

1. 保留 distance-based kernel 作为主骨架，不要推翻。
2. 只允许在 3 套 kernel family 之间切换：

```text
K1: dense-current / low-risk
K2: sparse-current but fresh-context
K3: high-alt / high-vertical-gap / role-conflict
```

3. 真正自适应的只允许改：

```text
horizontal radius
vertical anisotropy
context/current ratio
```

4. 不允许再引入更细的 point-wise kernel catalog。

执行 if/else：

```text
if altitude >= 9km and nearest_current_count <= 1:
    用更强 vertical shrink + 更保守 horizontal widening
else:
    维持 baseline kernel family

if role_gap >= 30:
    不允许直接清空 context
    只有当 current_count >= 2 and nearest_distance <= 1.5 vox 时才显著提高 current 权重
else:
    使用 baseline role mix

if vertical_gap >= 10:
    降低跨层耦合
else:
    维持 baseline vertical preserve
```

成功标准：

```text
200-frame smoke 先过
target strata: gap_ge30 / vgap_ge10 / altitude>=9km 至少两层 RMSE 改善 >= 5%
full-5614 全部硬门槛通过
```

### 5.3 S4-C：重做 temporal weighting，按 regime 校准 observation window，而不是一个全局 time confidence

对应问题：

```text
P3 stale context
P2 role conflict
```

文献依据：

1. Goux et al. (2025) 说明相关观测误差长度不同，决定了“显式相关建模”与“方差膨胀近似”的取舍。[R1]
2. Peduto et al. (2025) 在 observation-driven wind correction 中显式使用 recent observation-forecast pair、time embedding 和 irregular set handling，说明“时间不是单一衰减常数”，而是模型输入的一部分。[R13]

建议改法：

1. 对 `timeconf_0.2-0.4 / 0.4-0.6 / >=0.6` 分开做 holdout CV。
2. 每个时间层再按 `height x support zone` 拟合最优半衰期或幂指数。
3. 旧 context 不是直接删掉，而是通过 `sigma_repr/time` 增大其不确定性。

执行 if/else：

```text
if timeconf >= 0.6:
    沿用接近 baseline 的 decay

if 0.4 <= timeconf < 0.6:
    if support is sparse and role_gap < 15:
        允许保留 context，但 inflate sigma
    else:
        更强衰减

if timeconf < 0.4:
    if current_count == 0 and vertical_gap < 2 and truth-speed regime not extreme:
        仅作为 weak support 使用
    else:
        不进入主重构
```

成功标准：

```text
timeconf_0.4-0.6 stratum RMSE 改善 >= 5%
global hard gates 全过
light wind 不得恶化
```

### 5.4 S4-D：弱背景只允许进入“低支撑 + 低快速变化”区，不得再做半全局 rescue

对应问题：

```text
P4 sparse support
P6 tail-sensitive system
```

文献依据：

1. Physics-Informed Field Inversion for Sparse Data Assimilation (2025) 表明：在 sparse、truncated、noisy observation 下，把低保真模型作为被物理约束的 correction base，比纯数据驱动更稳。[R8]
2. Peduto et al. (2025) 说明 observation-informed correction 的价值在于“纠偏低保真背景”，不是无条件替换原场。[R13]

这里的工程推断：

```text
CMA/GFS/NWP 只能做 gated weak prior
不能再做 broad rescue
```

建议改法：

1. 只在下面的交集中允许 weak background：

```text
nearest_current_count = 0 or 1
nearest_distance >= 3 vox
vertical_gap < 2
role_gap < 15
light/moderate wind
```

2. 背景只允许做 convex weak prior，不允许主导当前重构。
3. 先从 `count_0 + low-risk` 这一层做单独 ablation。

执行 if/else：

```text
if current support is dense:
    禁止 background 进入

if altitude >= 12km:
    background 只允许 report-only diagnostics，不进入主 correction

if low-support and low-vertical-gap and low-role-gap:
    允许弱背景 prior
else:
    禁止
```

成功标准：

```text
count_0 层改善 >= 5%
light wind hard gate 不破
12km+ hard gate 不破
```

### 5.5 S4-E：把 tail-risk 和 no-claim 从“解释层”升级成正式优化约束

对应问题：

```text
P6 tail-sensitive verification
```

文献依据：

1. Allen et al. (2024/2025 version) 指出极端尾部需要单独做 tail calibration，普通 calibration 并不足以说明极端区可靠。[R12]
2. Yu et al. (2025) 与 Gopakumar et al. (2025) 则给出 conformal-style calibration 的可操作路径，适合把“不确定时不改”做成正式机制。[R10][R11]

建议改法：

1. 正式报告里把 `P95 / P99 / max / tail coverage / risk-strata hit-rate` 固定为二级主表。
2. 把 `count_0 / count_1 / dist_ge6 / gap_ge30 / vgap_ge10 / altitude>=9km` 固定为 no-claim or low-confidence strata。
3. default tuning 时不允许只看 weighted RMSE。

执行 if/else：

```text
if candidate improves weighted RMSE but worsens P95/P99 or 12km+:
    直接 reject

if candidate only improves tail but worsens light/floor10:
    只能保留为 report-only branch

if candidate passes global gate but gain < engineering threshold:
    不升默认，只保留 diagnostic value
```

成功标准：

```text
tail metrics 被正式纳入 gate
任何新候选都不允许绕开 P95/P99/12km+/light/floor10
```

---

## 6. Stage5 怎么优化：同样逐条绑定问题和文献

### 6.1 S5-A：把 Stage5 定义成 uncertainty-gated residual，不再把它当 full-field replacement

对应问题：

```text
P7 Stage5 full-field unsafe
P8 no calibrated abstention
```

文献依据：

1. Yan et al. (2024) 的 wind-flow PINN 框架说明 PINN 更适合做受物理约束的 field reconstruction / correction，而不是无约束硬回归。[R7]
2. Ugur and Zhou (2025) 说明 sparse-data correction 应由 physical loss 提供 dense gradients 和 adaptive regularization。[R8]
3. Peduto et al. (2025) 说明“observation-informed correction of a low-fidelity field”是一个稳健范式。[R13]

建议改法：

1. 明确 Stage5 目标：

```text
不是重建全场
而是在 Stage4 官方场上叠加 very small residual
```

2. 默认 gate：

```text
altitude < 12km
not light wind
support in good/reasonable zone
uncertainty low
role conflict not extreme
```

3. 换句话说，Stage5 应该学的是“我什么时候别改”，而不是“我在哪里都改一点”。

执行 if/else：

```text
if altitude >= 12km:
    residual = 0

if light wind:
    residual = 0

if nearest_current_count == 0 and nearest_distance >= 3 and uncertainty high:
    residual = 0

if role_gap >= 30 or vertical_gap >= 30:
    默认 residual = 0，除非后续有单独证据证明安全
```

成功标准：

```text
200-frame smoke 全过
point-level test 过 continuation gate
full-5614 不打穿任何硬门槛
```

### 6.2 S5-B：先解决 PINN 训练病态，再谈 residual 是否有效

对应问题：

```text
P7 signal tiny
P8 training instability / no robust optimization
```

文献依据：

1. Wang et al. (2023) 总结了 PINN 最有效的一批 best practices，并给出可复现实验基线。[R5]
2. Rathore et al. (2024) 从 loss landscape 角度说明 PINN 残差项会导致病态，Adam+L-BFGS 与更强二阶优化通常优于单一一阶法。[R6]
3. Malineni and Rajendran (2025) 在 sparse flow reconstruction 中明确比较了 Standard PINN 与 BC-PINN，并强调 dynamic weighting 和 physics relaxation 的作用。[R9]

建议改法：

1. 训练流程固定为：

```text
normalization/scaling
Adam warmup
L-BFGS refinement
必要时二阶近似优化
```

2. 加入：

```text
dynamic loss weighting
curriculum on physics loss
BC-PINN or compatible warm start
```

3. Stage4 改版后，Stage5 应该重抽 residual dataset，不能沿用旧 residual。

执行 if/else：

```text
if train-val gap large:
    提高 regularization，降低 residual target scope

if PDE loss dominates and data loss不下降:
    放缓 physics loss 权重上升速度

if Adam plateau:
    切换 L-BFGS

if L-BFGS 仍不稳定:
    再试更强二阶近似或 BC-PINN warm start
```

成功标准：

```text
point-level RMSE improvement >= 0.02 m/s
P95 improvement >= 0.10 m/s
不同 seed 下结果符号一致，不再出现“一个 seed 过、另一个 seed 反向”
```

### 6.3 S5-C：给 residual 加 calibrated uncertainty，再决定 apply / abstain

对应问题：

```text
P8 no calibrated abstention
```

文献依据：

1. Gopakumar et al. (2025) 提出 physics-informed conformal prediction，可用 physics residual 做 nonconformity score，不必完全依赖带标签数据。[R10]
2. Yu et al. (2025) 进一步给出 local conformal quantile，用于 spatially heteroskedastic uncertainty band。[R11]
3. Allen et al. (2024/2025 version) 提醒极端尾部必须单独检查 tail calibration。[R12]

建议改法：

1. Stage5 输出不再只有 `delta_u, delta_v`，还要输出：

```text
uncertainty score
conformal interval width
tail-risk flag
```

2. field apply 不再只看 gate rule，还看 uncertainty coverage 是否校准。
3. 最简单落地方式：

```text
先做 deep ensemble 或 multi-seed ensemble
再用 conformal calibration 把 interval 校准到 holdout coverage
```

执行 if/else：

```text
if 90% interval coverage not in [87%, 93%]:
    不允许 field apply

if local uncertainty above threshold:
    residual = 0

if tail-risk flag = True:
    residual = 0 and report risk only
```

成功标准：

```text
coverage 合格
light / 12km+ / floor10 不恶化
Stage5 改动点不再集中在明显高风险未校准区域
```

### 6.4 S5-D：如果 PINN 继续 plateau，下一步不要硬拧同一架构，改走 observation-informed residual architecture

对应问题：

```text
P7/P8：当前 PINN 可能已经接近“现有目标定义下的收益上限”
```

文献依据：

1. Peduto et al. (2025) 用 set-based attention + cross-attention 处理 irregular、time-varying observations，直接学 observation-informed correction，并在 marine wind correction 上显著降 RMSE。[R13]
2. FNP (2024) 支持 arbitrary-resolution data assimilation，说明对异分辨率、异稀疏度观测，神经过程类结构比固定栅格输入更自然。[R14]
3. Energy Transformer (2025) 在 sparse flow reconstruction 上展示了高缺测率下仍可恢复复杂流场。[R15]
4. Latent DA (2025) 表明在 latent space 做 physically consistent assimilation 可能比在原空间手工配 B/R 更稳。[R16]

这里的工程推断：

```text
如果 Stage5 PINN v3 仍然只有 0.00x m/s 级别收益
那问题可能不在“再调一点 loss”，而在“架构没有正确表示 irregular observation set”
```

建议改法：

1. Stage5 主线先不直接切架构。
2. 但应立一个明确的 fallback：

```text
Stage5-B1: observation-informed set-transformer residual
Stage5-B2: FNP-style arbitrary-resolution correction
Stage5-B3: ET-style sparse field reconstruction
```

执行 if/else：

```text
if PINN v3 point-level improvement < 0.02 m/s after stability + UQ fixes:
    停止继续拧 PINN 主干
    转 Stage5-B1

if B1 仍无法通过 200-frame smoke:
    再评估 B2 / B3

if alternative architecture 计算成本过高且收益 < 0.05 m/s:
    停止 Stage5 default promotion，保留为 research branch
```

成功标准：

```text
必须先过 point-level continuation gate
再过 200-frame smoke
再过 full-5614 formal gate
否则不能写成默认候选
```

---

## 7. 一条完整、没有缝的 if/else 决策线

### 7.1 Stage4 决策线

```text
if 候选在 200-frame smoke 失败:
    直接 reject
else:
    进入 full-5614 strict holdout

if full-5614 任一硬门槛失败:
    不升默认
    回到失败 stratum 定位问题来源
else:
    检查 engineering threshold

if 5614 全过但 weighted RMSE 改善 < 0.05 m/s
and 目标 strata 改善 < 2 个:
    不升默认
    仅保留为 diagnostic / report-only candidate
else:
    可以进入默认升级讨论
```

### 7.2 Stage4 分支选择线

```text
if 主要失败来自 count_0/count_1/dist_ge6:
    先做 S4-A + S4-D

if 主要失败来自 gap_ge30 / role_conflict:
    先做 S4-B

if 主要失败来自 timeconf_0.4-0.6:
    先做 S4-C

if 主要失败来自 tail but not mean:
    先做 S4-E

if 一个候选同时想改 localization + background + temporal:
    拒绝一次性全上
    必须拆成可审计 ablation
```

### 7.3 Stage5 决策线

```text
if point-level continuation gate 没过:
    Stage5 不进入 field
    回到 S5-B / S5-C
else:
    允许做 200-frame field smoke

if field smoke 失败:
    不进 full-5614
    看失败是否来自 12km+ / light / floor10

if 任何 nonzero 12km+ residual 再次打穿 gate:
    将 alt12_off 固化为默认策略

if field smoke 通过但 gain < 0.02 m/s 且 changed points <= 2:
    只保留为 research note
    不升默认

if field smoke 通过且 gain 达到 engineering threshold:
    进入 full-5614

if full-5614 任一硬门槛失败:
    Stage5 仍不是默认候选

if PINN v3 完成稳定化和 UQ 后仍收益极小:
    停止继续调 PINN
    转 observation-informed residual architecture
```

---

## 8. 可直接执行的实验矩阵

| 实验 ID | 阶段 | 只改什么 | 不允许改什么 | 先看哪层 | smoke 通过条件 | formal 通过条件 | 失败后转向 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `S4A-1` | Stage4 | `sigma_repr(height,support,distance,time)` | localization / background / Stage5 | `count_0,count_1,dist_ge6` | 200-frame 全硬门槛通过 | full-5614 全硬门槛通过，且 `count_0/1` 至少一层改善 >= 5% | `S4B-1` 或 `S4C-1` |
| `S4A-2` | Stage4 | `local variance inflation` vs `local correlated-R` | 其他主干参数 | `timeconf_0.4-0.6` | 不打穿 `light / 12km+ / floor10` | weighted RMSE 不劣，`timeconf_0.4-0.6` 改善 >= 5% | 保留 diagonal inflation，放弃 correlated-R |
| `S4B-1` | Stage4 | 3 套 constrained kernel family | background / Stage5 | `gap_ge30,vgap_ge10,alt>=9km` | 200-frame 全硬门槛通过 | 至少两个 target strata 改善 >= 5%，formal 全过 | `S4C-1` |
| `S4C-1` | Stage4 | regime-aware temporal decay | localization / background / Stage5 | `timeconf_0.4-0.6` | light wind 不恶化 | target stratum 改善 >= 5%，formal 全过 | 回退 baseline time decay |
| `S4D-1` | Stage4 | low-support weak background prior | localization / Stage5 | `count_0 + low-risk` | `12km+` 与 light gate 不破 | `count_0` 改善 >= 5%，formal 全过 | 禁止 background 进主线 |
| `S4E-1` | Stage4 | tail/no-claim gate productization | 重构本身 | `P95,P99,12km+,floor10` | gate 定义无歧义 | 后续所有实验都按新 gate 审批 | 不适用 |
| `S5A-1` | Stage5 | strict abstention gate (`alt12_off` 固化) | PINN 架构 | point residual apply set | point continuation gate 通过 | 200-frame 全硬门槛通过 | `S5B-1` |
| `S5B-1` | Stage5 | Adam->L-BFGS + dynamic weighting + warm start | apply gate | point-level residual dataset | RMSE 改善 >= 0.02，P95 改善 >= 0.10 | 才允许进 field smoke | `S5C-1` 或 `S5D-1` |
| `S5C-1` | Stage5 | ensemble + conformal UQ | 主架构大改 | coverage / tail-risk | 90% 覆盖落在 `87%-93%` | field smoke 全过 | `S5D-1` |
| `S5D-1` | Stage5 | observation-informed residual architecture | Stage4 主干 | point-level first | point continuation gate 通过 | 200-frame 与 full-5614 全过 | 停止 Stage5 default promotion |

执行规则：

```text
一次只跑一个实验 ID
每个实验都必须保存独立输出目录和独立 promotion checklist
任何实验只要在 smoke 打穿硬门槛，就不允许进入 formal
```

---

## 9. 推荐执行顺序

### 第一优先：先修 Stage4，再碰 Stage5

原因：

```text
Stage5 学的是 Stage4 residual
如果 Stage4 的权重模型、support model、temporal model 还没修好
Stage5 学到的 residual 就会混入大量“本该在 Stage4 解决的系统性错误”
```

建议顺序：

1. `S4-A representation-aware sigma`
2. `S4-B constrained localization`
3. `S4-C temporal calibration`
4. `S4-D gated weak background`
5. 重新抽 residual training set
6. `S5-A/B/C` 组合推进
7. PINN 仍 plateau 时再转 `S5-D`

### 第二优先：每次只改一类机制

```text
不要再做“同时改 current/context weight + localization + background + residual gate”的混合 run
```

必须拆成：

1. 单机制 ablation。
2. 200-frame smoke。
3. full-5614 formal。

### 第三优先：把“no-claim strata”正式产品化

原因：

```text
文献和你当前结果都说明 sparse-support / high-tail 区存在不可避免的不确定性
与其强行把这些点改成“看起来也很准”
不如把低可信度边界明确说清楚
```

---

## 10. 最后给一个最务实的项目判断

截至 2026-06-12，我对这条线的判断是：

1. Stage4 还有真实可挖空间，但必须沿着 `representation-aware + support-aware + constrained localization + temporal calibration` 走，不能再做更自由、更全局的激进修正。
2. Stage5 不是没信号，而是当前 signal 太小、太脆弱，必须先引入 `training stabilization + calibrated uncertainty + abstention`，否则只要碰 `12km+ / light / sparse-support` 就会重新失败。
3. 未来最有希望的 Stage5，不是“更大的 PINN”，而是“更会拒绝修改的 residual model”，必要时换成 observation-informed set architecture。
4. 如果你要优先拿一个更稳、可写论文、可正式升默认的结果，Stage4 先做；Stage5 现在仍应视为 research branch。

---

## 11. 参考文献（本文实际采用）

`[R1]` Olivier Goux, Anthony Weaver, Selime Gurol, Oliver Guillet, Andrea Piacentini. 2025. On the impact of observation error correlations in data assimilation, with application to along-track altimeter data.  
https://arxiv.org/abs/2503.09140

`[R2]` Shay Gilpin, Matthias Morzfeld, Kevin K. Lin. 2025. Numerical study of high-dimensional covariance estimation and localization for data assimilation.  
https://arxiv.org/abs/2508.18299

`[R3]` Sarp Er, Marcello Meldi. 2025. Physics-based localization methodology for Data Assimilation by Ensemble Kalman Filter.  
https://arxiv.org/abs/2511.08845

`[R4]` Vikrant Gupta, Yuanqing Chen, Minping Wan. 2024. Predictability of weakly turbulent systems from spatially sparse observations using data assimilation and machine learning.  
https://arxiv.org/abs/2407.10088

`[R5]` Sifan Wang, Shyam Sankaran, Hanwen Wang, Paris Perdikaris. 2023. An Expert's Guide to Training Physics-informed Neural Networks.  
https://arxiv.org/abs/2308.08468

`[R6]` Pratik Rathore, Weimu Lei, Zachary Frangella, Lu Lu, Madeleine Udell. 2024. Challenges in Training PINNs: A Loss Landscape Perspective.  
https://arxiv.org/abs/2402.01868

`[R7]` Chang Yan, Shengfeng Xu, Zhenxu Sun, Thorsten Lutz, Dilong Guo, Guowei Yang. 2024. A Framework of Data Assimilation for Wind Flow Fields by Physics-informed Neural Networks.  
https://arxiv.org/abs/2401.17001

`[R8]` Levent Ugur, Beckett Y. Zhou. 2025. Physics-Informed Field Inversion for Sparse Data Assimilation.  
https://arxiv.org/abs/2509.19160

`[R9]` Vamsi Sai Krishna Malineni, Suresh Rajendran. 2025. Physics-Informed Neural Network Approaches for Sparse Data Flow Reconstruction of Unsteady Flow Around Complex Geometries.  
https://arxiv.org/abs/2508.01314

`[R10]` Vignesh Gopakumar, Ander Gray, Lorenzo Zanisi, Timothy Nunn, Stanislas Pamela, Daniel Giles, Matt J. Kusner, Marc Peter Deisenroth. 2025. Calibrated Physics-Informed Uncertainty Quantification.  
https://arxiv.org/abs/2502.04406

`[R11]` Yifan Yu, Cheuk Hin Ho, Yangshuai Wang. 2025. A Conformal Prediction Framework for Uncertainty Quantification in Physics-Informed Neural Networks.  
https://arxiv.org/abs/2509.13717

`[R12]` Sam Allen, Jonathan Koh, Johan Segers, Johanna Ziegel. 2024/2025 version. Tail calibration of probabilistic forecasts.  
https://arxiv.org/abs/2407.03167

`[R13]` Matteo Peduto, Qidong Yang, Jonathan Giezendanner, Devis Tuia, Sherrie Wang. 2025. Observation-driven correction of numerical weather prediction for marine winds.  
https://arxiv.org/abs/2512.03606

`[R14]` Kun Chen, Tao Chen, Peng Ye, Hao Chen, Kang Chen, Tao Han, Wanli Ouyang, Lei Bai. 2024. FNP: Fourier Neural Processes for Arbitrary-Resolution Data Assimilation.  
https://arxiv.org/abs/2406.01645

`[R15]` Qian Zhang, Dmitry Krotov, George Em Karniadakis. 2025. Operator Learning for Reconstructing Flow Fields from Sparse Measurements: an Energy Transformer Approach.  
https://arxiv.org/abs/2501.08339

`[R16]` Hang Fan, Lei Bai, Ben Fei, Yi Xiao, Kun Chen, Yubao Liu, Yongquan Qu, Fenghua Ling, Pierre Gentine. 2025. Physically Consistent Global Atmospheric Data Assimilation with Machine Learning in Latent Space.  
https://arxiv.org/abs/2502.02884
