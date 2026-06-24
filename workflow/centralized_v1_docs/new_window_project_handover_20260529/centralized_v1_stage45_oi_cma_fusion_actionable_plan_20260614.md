# centralized_v1 Stage4/Stage5 优化 + CMA 弱背景融合 可落地执行方案（2026-06-14）

> 本文目标：给“执行智能体”一份**可直接动手**的方案。
> 你（执行智能体）不需要重新读全部历史文档，只要按本文的“文件路径 + 函数 + 命令 + 验收门槛”执行即可。
> 凡是涉及判断的地方，本文都给了 if/else 决策线和回退策略。
>
> 撰写依据：已逐份通读 `new_window_project_handover_20260529/` 全目录文档、`stage/centralized_v1/core/` 全部核心代码（Stage2/3/4/5 + CMA 融合 + virtual_radial_3dvar）、以及 2023-2025 的 SOTA 文献（见第 12 节参考文献）。
>
> 前置阅读（只读这两份就够建立全局）：
> 1. `centralized_v1_ultimate_summary_20260612.md`
> 2. `centralized_v1_stage45_literature_backed_optimization_plan_20260612.md`（本文是它的“可执行化 + CMA 融合”续作，不与它冲突，是把它落地）

> **2026-06-14 审阅修订说明（Codex）**：
> 我核对了 `centralized_v1_ultimate_summary_20260612.md`、`centralized_v1_stage45_literature_backed_optimization_plan_20260612.md`、Stage4/5 直接上游文档以及当前 `stage/centralized_v1/core/` 代码。本文主方向“CMA 只作弱背景、完整产品场必须低置信标注、official skill 仍只看 strict aircraft holdout”是正确的；但原稿有几处需要收紧：
>
> 1. `local_oi` 原稿公式是 **OI-inspired scalar nudging**，不是严格 OI。若要称为 OI，必须显式使用 `sigma_b^2`、`sigma_i^2`、背景-观测相关 `rho_i`，并输出可解释的 `obs_influence` / `analysis_error_var`。
> 2. `S4-CMA-M1` 不必先新增一套 `recon_u_full_3d` 机制；当前代码已有 `display_fill_mode=low_conf_background`，可以先作为最低风险 M1 产品路径。关键是 **不改 `recon_u/v/recon_mask` 和 `_point_eval_rows`**。
> 3. 原稿命令里 `--emit-background-npz`、`--time-match-mode`、`--cma-background-dir`、`--cma-fill-mode` 等 CLI 当前不存在。执行前要么改命令用现有参数，要么先实现这些接口。
> 4. 06-12 文献方案已经记录 `tp26_rep_soft_weight_v1` full-5614 明确 FAIL；这比 `ultimate_summary` 中“5614 未完成”的旧口径更新。本文后续执行顺序以 **full-5614 FAIL** 为准。
> 5. 当前 200/5614 frame list 文件是逐行文本；`centralized_stage4_ground_recon.py` 和 `centralized_cma_ra_virtual_radial_3dvar.py` 的 `--frame-times-file` 读取 JSON list。执行前必须转换或改读取函数。

---

## 0. 一句话总纲（最重要，先读这段）

当前 Stage4 用的是**确定性 IDW / 高斯核加权插值**（当前代码核查：`_accumulate_localized` 在 `centralized_stage4_ground_recon.py:1694` 起，核心为 `acc_u += u * local_w; acc_w += local_w`；成场 `_make_reconstruction` 在 `:2625` 起）。
它可以被解释为一种 **kernel smoother / inverse-distance weighted estimator**，与 OI/3D-Var 共享“距离相关影响 + 加权估计”的思想；但它还不是严格 OI，因为当前没有显式 `x_b`、`B`、`R`、`H`、创新量和分析误差协方差。

**你现在的三个核心诉求，本质上是同一件事的三个产物，OI/3D-Var 一次性全给：**

| 你的诉求 | OI/3D-Var 怎么一次性解决 |
| --- | --- |
| ① Stage4 还没达标，要有效优化 | 把退化核插值升级成带**真实 B/R 协方差**的 OI，等价于一次性把 representation error（R 膨胀）、sparse support（B 相关长度）、role conflict（创新量加权）、temporal weighting（R 时间膨胀）统一进一个**有统计意义的估计器**，而不是再手调一堆乘法因子 |
| ② 稀疏 → 要完整风场，又要标注低置信度 | OI 的解 `x_a = x_b + K(y - H x_b)` 里，没有观测的地方自动回退到背景 `x_b`（CMA 弱背景），于是天然得到**全场**；同时分析误差方差 `diag(A) = diag((I-KH)B)` 和**观测影响 / DFS** `diag(HK)` 天然给出**逐格点置信度图**，哪里是观测决定的、哪里是 CMA 背景决定的，一目了然 |
| ③ 把 CMA 融合进来当弱背景 | CMA(CRA40) 在 **OI 候选** 里可作为 `x_b`。它只在**没有飞机观测约束的地方**主导；有观测的地方观测主导。这正是“弱背景”的严格定义。代码里 `CMA_FUSION_MODES`、`_load_cma_background`、`_apply_cma_background_to_accumulator` 已经搭好骨架，但现在用的是**裸加法混合**（`acc_u += cma_u * weight`），缺的就是“按 R/B 协方差平衡”。把它改成 OI 增量形式即可 |

**修订后的主干 = 先用现有 display-fill / M1 交付“完整产品场 + 低置信度标注”，同时保持 official `recon_u/v` 完全不变；再把 Stage4 候选分支从启发式核插值逐步升级为 `OI-inspired -> local OI`。** 只有当代码显式实现 `B/R/H` 或其等价局地标量近似、并通过 200 + 5614 guardrail 后，才把它写成“局地 OI”主线。Stage5 在此之上仍是“极窄门控 + 不确定性弃改”的残差候选；它不能替代 Stage4 default。

> ⚠️ 关键边界（贯穿全文，不可违反）：
> - CMA/CRA40 **永远只能是背景 `x_b`，绝不能进入 holdout 评估真值**。代码里已有 `cma_used_as_background_not_truth` 守卫（`ground_recon.py:3265`），必须保持。
> - holdout 飞机风仍是唯一正式真值，`strict_holdout_no_leakage=True`、`motion_used_as_wind=False` 不可破（`ground_recon.py:3266-3273` 的 fail-fast 守卫必须保留）。
> - **必须先验证 CRA40 不同化了被 holdout 的同一批 AMDAR**（见 5.1 的 P0 泄漏检查），否则背景与真值不独立，整个 OI 的误差统计失效。

---

## 1. 当前正式基线（执行时以此为对照，不要重算口径）

### 1.1 200 帧 smoke 基准（cheap screen，第一道门）

```text
frames = 200, holdout points = 530
默认方法 = tp26_thr11_preserve
```

| 指标 | baseline 值 | smoke 过线 |
| --- | ---: | --- |
| weighted RMSE | 14.769036 | 不高于 baseline |
| frame P95 RMSE | 27.986111 | 不高于 baseline |
| frame P99 RMSE | 58.783770 | 不高于 baseline |
| 12km+ vector RMSE | 19.917698 | 不高于 baseline |
| light wind(5-15) RMSE | 5.195877 | 不高于 baseline |
| light wind(5-15) MAE | 4.185283 | 不高于 baseline |
| floor10 relative MAE | 0.282804 | 不高于 baseline |
| new light/mod tail failure | 0 | 必须仍为 0 |

### 1.2 full-5614 正式 promotion 门（第二道门，决定能否升默认）

```text
frames = 5614, holdout_points = 15054
```

| 指标 | full-5614 baseline | formal 过线 |
| --- | ---: | --- |
| frame mean RMSE | 8.418875 | 不高于 baseline |
| frame mean MAE | 7.408240 | 不高于 baseline |
| weighted RMSE | 14.520015 | 不高于 baseline |
| weighted MAE | 6.475666 | 不高于 baseline |
| frame P95 RMSE | 31.783087 | 不高于 baseline |
| frame P99 RMSE | 73.325466 | 不高于 baseline |
| 12km+ vector RMSE | 17.585340 | 不高于 baseline |
| light(5-15) RMSE | 5.510587 | 不高于 baseline |
| light(5-15) MAE | 4.188920 | 不高于 baseline |
| floor10 relative MAE | 0.255017 | 不高于 baseline |

### 1.3 误差结构（决定优先改什么）

200 帧 530 点的 tail 结构：`alt_12km_plus`（222 点）占 SSE 76.2%；`high_vector_error_ge30mps`（21 点）占 SSE 81%；`qc_review_flag`（302 点）占 SSE 93.8%。
误差来源优先级（来自误差分解文档，已稳定）：
`vertical_structure > representation_error > sparse_support > role_conflict > temporal_weighting > tail_qc > localization`。

观测误差锚点（de Haan 2016 / EMADDC 2025，单位 m/s，**只能当 R 的下界，不能从 RMSE 里硬扣**）：
- 仪器误差：近地 1.4、500hPa ~1.1。
- EMADDC 有效误差（含 QC+背景比对）：0-3km 2.2、3-6km 2.5、6-15km 2.8。
- 项目里 13.64 m/s 是 local-consistency / representativeness sigma，**不是仪器误差**。
- 当前 component RMSE 10.27，EMADDC sigma RMS 2.74，excess variance fraction 0.93 → **绝大部分误差是表示误差 + 重构误差，不是观测仪器误差**。这是 Stage4/5 的物理下界，必须在方案里显式承认（见第 8 节“误差地板”）。

---

## 2. 关键代码地图（执行时直接定位，省去你重新找）

### 2.1 Stage4 重构主链（`stage/centralized_v1/core/centralized_stage4_ground_recon.py`，4812 行）

| 功能 | 位置 | 说明 |
| --- | --- | --- |
| 观测权重基 `obs_conf*time_conf` | `:341-346 _active_base_weight` | 当前权重起点 |
| 观测构建 + 各置信因子相乘 | `:588-741 _build_wind_observations` | density/quality/speed_qc/local_consistency/obs_error/representation_soft 都在此乘入 |
| 核加权累加（**重构核心循环**） | `:1694-约2050 _accumulate_localized` | `acc_u += u*local_w`、`acc_w += local_w`；后续 role-conflict 分支会改写 context 权重 |
| 核权重函数 | `:744-791 _localization_weights` | gaussian / gaspari_cohn |
| 自适应核选择 | `:1357-1387, 1474-1487` | diagnostic_adaptive_v3，候选格 8:4,10:5 |
| 角色冲突处理 | `:1616-1691, 1957-2028` | current_priority_adaptive，阈值自适应，context 削减 |
| **成场（除权）** | `:2625-2645 _make_reconstruction` | `recon_u = acc_u/acc_w`；`recon_conf = _normalize_confidence(weight)`（:2632，按 90 分位归一） |
| 物理细化 | `:2693-2886 _pinn_diffusion_refine` | pydda_3dvar_proxy + 垂直保结构 |
| **可靠性/tail-risk/no-claim 场** | `:2158-2242 _compute_reliability_fields` | 已有 reliability_confidence_3d / tail_risk_score_3d / no_claim_mask_3d |
| **展示填充层** | `:2905-3025 _make_display_filled_field` | 已有 display-only CMA 背景填充；输出 `display_u/v/conf/mask/source`，并标注 `display_fill_is_official_accuracy=False` |
| holdout 切分 | `:312-338 _split_holdout` | 确定性 linspace 选点 |
| 泄漏守卫（**不可破**） | `:3266-3273 _leakage_report` | strict_holdout_no_leakage，fail-fast |
| 点评估 | `:3502-3627 _point_eval_rows / _metric_summary` | vector_error、rmse_vector |
| 方法 dispatch | `:4040-4078 process_frame` | 按 localization_policy / confidence_mode 分支 |
| argparse | `:4654-4719` | 所有 CLI 旋钮 |

### 2.2 CMA 弱背景骨架（**已存在，是融合的落点**）

`ground_recon.py`:
- `:92 CMA_FUSION_MODES = {"off","cma_proxy_background","cma_reanalysis_background","cma_pseudo_observation"}`
- `:2385-2506 _load_cma_background`：从 NPZ 读 u/v/conf，支持 confidence_source、qc_gating（strict_temporal 按 temporal_conf≥阈 + temporal_change≤阈 门控）。
- `:2509-2598 _apply_cma_background_to_accumulator`：**当前是裸加法** `acc_u += cma_u*weight; acc_w += weight`，background_weight_mode ∈ {fixed, diagnostic_gated, sparse_temporal_gated}。**这是要改成 OI 增量形式的地方。**
- `:2905-3025 _make_display_filled_field`：已经能把 CMA/CRA40 NPZ 作为 **display-only low-confidence fill**，不改 official `recon_u/v/conf/mask`。
- argparse：已有 `--cma-fusion-mode`、`--cma-proxy-dir`、`--cma-proxy-npz`、`--cma-background-weight`、`--cma-background-weight-mode`、`--display-fill-mode low_conf_background`、`--display-fill-cma-proxy-dir`、`--display-fill-source`、`--display-fill-confidence-cap`、`--display-fill-qc-gating`。
- **尚不存在**：`--recon-mode`、`--cma-background-dir`、`--cma-fill-mode`、`--cma-fill-eps`、`--oi-*`。本文后面凡写这些参数，都属于“需先实现”的接口，不是当前可直接运行命令。

`centralized_cma_ra_virtual_radial_3dvar.py`（1212 行，CRA40 读取 + 伪径向 3DVar）：
- `:217-299` GRIB2 读取：优先 `xr.open_dataset(engine="cfgrib")`，回退 `eccodes`。
- `:68-76` 变量码 `WIU→u_wind_mps, WIV→v_wind_mps`。
- `:315-348` 水平最近邻 + 垂直按气压→高度插值（`44330*(1-(p/1013.25)^0.1903)`）。
- `:128-214, 408-468` 时间匹配：nearest / linear / linear_qc（含 `temporal_conf=exp(-change_speed/24)`、`rapid_change_flag`）。
- `:654-776 _three_dvar_proxy`：已有 8 项软约束迭代（smoothness/divergence/vertical_shear/background/stage4_prior/observation/radial/boundary）。**这是 OI 的雏形，但缺真实 B/R。**
- `:968-990 np.savez_compressed`：当前已经输出 `u_cma_3d/v_cma_3d/cma_temporal_conf_3d/u_proxy_3d/v_proxy_3d/coverage_conf_3d`，因此不一定需要新增 `--emit-background-npz`；更小改动是用现有输出目录作为 `--display-fill-cma-proxy-dir` / `--cma-proxy-dir`。
- argparse 当前是 `--cma-time-method {nearest,linear,linear_qc}`，不是 `--time-match-mode`。

### 2.3 Stage5 残差 PINN

- `centralized_stage5_residual_pinn_train.py:49-67 ResidualMLP`：输入 60+ 无泄漏特征，输出 `(delta_u, delta_v, sigma_u, sigma_v)`，`delta = cap*tanh(...)`，`sigma = 0.25 + softplus(...)`。损失含 Huber + 高斯 NLL + delta 正则（`:183-198`，已有异方差不确定性）。
- `centralized_stage5_residual_pinn_field_apply.py:721-758`：锁定门 `vertical_gap_ge20_not_light`，`gate=(vertical_proxy>=20)&(~pred_light)`。
- `centralized_stage5_residual_pinn_field_v2_replay.py:75-136`：变体扫描，`alt12_scale∈{1,0.5,0.25,0}`、support_risk/clean_suppress 门控。结论：只要 `alt12_scale>0` 就 FAIL。
- `centralized_stage5_residual_pinn_dataset.py:37-61, 122-137`：按帧时间切 train/val/test（无点级随机切，防泄漏），truth 列严格排除。

---

## 3. Stage4 主优化：把核插值升级为“以 CRA40 为弱背景的局地 OI”

这是本方案的核心，也是最可能真正把 Stage4 推过门的一步。它不是“再加一个乘法因子”，而是换一个**有统计意义的估计器**，让 representation/sparse/role/temporal 四类误差在同一个 R/B 框架里被自然处理。

### 3.1 OI 的数学形式（执行智能体必须按此实现）

逐格点（或逐局地块）求解：

```text
x_a = x_b + K (y - H x_b)
K   = B Hᵀ (H B Hᵀ + R)⁻¹
A   = (I - K H) B          # 分析误差协方差，其对角线就是置信度图
```

- `x_b`：CRA40 背景（u/v），插值到当前网格与时刻（见 5.2 时间匹配）。
- `y`：当前帧训练用飞机风观测（**已剔除 holdout**，沿用 `_build_wind_observations` 的 train_wind）。
- `H`：观测算子，把格点场插值到观测点（用现有体素索引 + 三线性即可）。
- `B`：背景误差协方差。**用扩散算子 / 高斯相关核实现**（不显式建 B 矩阵），相关长度水平 `L_h`、垂直 `L_z` 各向异性。**注意：你现在的高斯核 `_localization_weights` 正是 B 的相关结构**——所以这步是“把核重新解释为 B 的相关算子”，工程上改动可控。
- `R`：观测误差协方差 = 仪器误差 + 表示误差。对角即可起步：`σ_total² = σ_obs² + σ_repr²`。

**局地化实现（关键，避免全局求逆）**：不要全域建 `B`。对每个目标格点或局地块，只收集半径内训练观测，建立小型局地系统。

严格局地 OI 对目标格点 `g` 的形式是：

```text
d_i = y_i - x_b(i)
k_i = Cov[x_g, y_i] = sigma_b(g) * sigma_b(i) * rho(g,i)
S_ij = Cov[y_i, y_j] + R_ij
     = sigma_b(i) * sigma_b(j) * rho(i,j) + delta_ij * sigma_i^2
alpha = solve(S, d)
x_a(g) = x_b(g) + k^T alpha
analysis_var(g) = sigma_b(g)^2 - k^T solve(S, k)
obs_influence(g) = clip(1 - analysis_var(g)/sigma_b(g)^2, 0, 1)
```

其中 `rho` 可以先复用现有 gaussian / Gaspari-Cohn localization 核，`sigma_i^2 = sigma_obs_i^2 + sigma_repr_i^2`。这才是可以被称为“local OI”的实现。

如果算力或内存不允许每个格点解局地矩阵，可以先做 **diagonal-S 近似**，但命名必须写成 `oi_diag_approx` 或 `OI-inspired`，不要写成完整 OI：

```text
对每个目标格点 g：
  d_i = y_i - x_b(i)
  k_i = sigma_b(g) * sigma_b(i) * rho(g,i)
  s_i = sigma_b(i)^2 + sigma_i^2
  raw_increment = Σ k_i * d_i / s_i
  raw_var = sigma_b(g)^2 - Σ k_i^2 / s_i
  analysis_var = clip(raw_var, sigma_floor^2, sigma_b(g)^2)
  obs_influence = clip(1 - analysis_var / sigma_b(g)^2, 0, 1)
  x_a(g) = x_b(g) + gain_cap(obs_influence) * raw_increment
```

> 原稿里 `Σw_i innovation_i / (Σw_i + ε_bg)` 的写法量纲和背景方差语义不够严谨，只能作为“背景锚定的 nudging heuristic”。修订后必须显式记录 `sigma_b`、`sigma_i`、`rho` 和 `analysis_var`，否则不能宣称 OI。
>
> 正确实现后的语义是：
> - **有观测**：`obs_influence→1`，`x_a→` 观测加权，`analysis_error_var→0`（高置信）。
> - **无观测**：`obs_influence→0`，`x_a→x_b`（CRA40 背景），`analysis_error_var→σ_b²`（低置信，明确标注）。
>
> 这正好同时满足你的“完整风场 + 低置信度标注 + CMA 弱背景”三诉求。

### 3.2 落地步骤（实验 ID：`S4-OI-1`）

**Step A：CRA40 预处理成每帧背景 NPZ（复用现有 GRIB2 读取链）**

- 复用 `centralized_cma_ra_virtual_radial_3dvar.py` 的现有读取/插值/输出。当前脚本已经在 `np.savez_compressed` 中产出：
  ```text
  u_cma_3d, v_cma_3d
  cma_temporal_conf_3d
  cma_temporal_change_speed_3d
  cma_rapid_change_flag_3d
  u_proxy_3d, v_proxy_3d
  coverage_conf_3d
  ```
- 输出文件名当前是 `cma_ra_virtual_radial_3dvar_<time>.npz`，`_find_cma_proxy_npz` 可直接按 frame time 找。**不需要先实现 `--emit-background-npz` 才能做 M1 display-fill。**
- 如果后续只想生成背景、不想跑 `_three_dvar_proxy`，可以新增 `--background-only` 以节省时间，但这属于优化，不是 M1 blocker。
- **P0 泄漏检查（必须先做，见 5.1）**：确认 CRA40 与 holdout AMDAR 独立。

**Step B：在 `ground_recon.py` 新增 OI 累加分支**

- 不动现有 `_accumulate_localized`，新增 `_accumulate_local_oi(...)` 或 `_accumulate_oi_diag_approx(...)`（紧邻 `_accumulate_localized`），并通过新增 `--recon-mode {kernel_idw, oi_diag_approx, local_oi}` dispatch。
- `kernel_idw` 必须保持默认，保证现有 tp26 可复现。
- `oi_diag_approx` 可先实现 3.1 的 diagonal-S 近似；`local_oi` 必须实现局地 `S` 矩阵求解。
- `_load_cma_background` 已能读现有 CMA NPZ；不用增加新的 fusion mode，先复用 `cma_reanalysis_background`。
- 新增 CLI（需先实现）：`--recon-mode`、`--oi-sigma-obs-mode`、`--oi-sigma-repr-config`、`--oi-sigma-bg-mps`、`--oi-length-h-vox`、`--oi-length-z-vox`、`--oi-min-obs-influence`、`--oi-max-increment-mps`。
- 成场时输出新场：`recon_obs_influence_3d`、`recon_analysis_error_var_3d`、`recon_background_u_3d`、`recon_background_v_3d`。只有 OI 分支通过 200 + 5614 gate 后，才考虑令 official `recon_confidence_3d` 改用 `obs_influence`；否则先作为附加诊断场。

**Step C：R 的表示误差膨胀（这步直接吃掉 representation_error 这个 P2 误差源）**

`σ_repr` 不是常数，按格点诊断设：

```text
σ_repr² = σ_repr_base²
        * f_height(alt)         # 高空更大：12km+ ×1.5~2.0
        * f_support(count,dist) # count_0 / dist_ge6 更大：×1.5~2.5
        * f_rolegap(role_gap)   # gap_ge30 更大：×1.5~2.0
        * f_time(time_conf)     # timeconf_0.4-0.6 更大：×1.3~1.6
```

- 起步值：`σ_obs` 按 EMADDC 分层（0-3km 2.2 / 3-6km 2.5 / 6-15km 2.8），`σ_repr_base` 用项目 13.64 的分层拆解（按高度/支撑）。
- **用 Desroziers 诊断在线校准 R/B**（见 5.3），不要纯手猜。

**Step D：先做 report-only diagnostics，再允许改 official field**

```text
1. 先跑 OI diagnostic-only:
   - 读取 CMA 背景
   - 计算 train observation innovation: y - Hx_b
   - 输出 obs_influence/analysis_var/innovation bins
   - 不改 recon_u/v
2. 若 innovation 分层显示背景在 light/12km+/timeconf 风险层不可靠:
   - 保持 M1 display-fill，不进入 M2 official branch
3. 只有 diagnostic-only 通过后:
   - 再跑 oi_diag_approx official candidate
   - 再跑 local_oi official candidate
```

### 3.3 为什么这条路比历史失败分支更可能过门

历史失败分支（SRHA / sparse_temporal_cma / guarded_vertical / point_regime）都败在**用确定性规则在某个 regime 强行改写场**，结果在 light wind / 12km+ / floor10 上反噬。OI 不同：

- 它在**有观测的地方几乎不动**（obs_influence→1，背景几乎无贡献），所以 light wind / 低层 dense 区**结构上不会被污染**——这正是 sparse_temporal_cma 当年污染 light wind 的根因被消除。
- 它只在**无观测的地方**用背景填充，而那些地方本来就进不了 holdout 评估（holdout 点必然在有飞机的地方），所以**对 holdout RMSE 风险低、对产品完整性收益大**。
- 12km+ 的改善来自 R 的高空膨胀（让稀疏高空观测不被过度信任）+ 背景兜底，而不是强行外推。

> ⚠️ 诚实预期（必须写给执行者和老师）：**OI 对 holdout RMSE 的提升可能有限**，因为 holdout 点恰好在观测密集处、本来就被观测主导。OI 的最大价值是：(a) **产品完整性**（全场 + 置信度），(b) **tail / 12km+ / sparse 区的稳健性**（不再灾难性外推），(c) **方法学正确性**（可写论文：从启发式核插值升级为有 B/R 的局地 OI + 影响诊断）。把这点说清楚，避免“跑完发现 weighted RMSE 只动 0.0x”时被误判为失败。

### 3.4 `S4-OI-1` 验收门

```text
smoke(200): 全部硬门槛不劣于 baseline（重点盯 light/12km+/floor10 不破）
formal(5614): 全部硬门槛不劣
工程增益(满足其一即可升默认):
  A. weighted RMSE 改善 >= 0.05 m/s, 或
  B. 12km+ / count_0 / count_1 / timeconf_0.4-0.6 中 >=2 层 RMSE 改善 >= 5% 且硬门槛全过
若 holdout 指标只持平但产品完整性 + 置信度图成立:
  → 不升默认，但作为“product-completeness + reliability branch”正式保留并写入论文
```

### 3.5 如果 `S4-OI-1` 整体过不了：拆成可审计子实验（不要一次全上）

| 子实验 | 只改 | 先看 | 过线 |
| --- | --- | --- | --- |
| `S4-OI-1a` | R 表示误差分层膨胀（仍 kernel_idw，不引背景） | count_0/count_1/dist_ge6 | 这些层 RMSE 改善且硬门槛不破 |
| `S4-OI-1b` | B 各向异性相关长度（扩散核替高斯核） | gap_ge30/vgap_ge10/alt>=9km | ≥2 层改善 5% |
| `S4-OI-1c` | 引入 CRA40 背景兜底（仅 obs_influence<0.1 的格点） | 产品完整性 + 12km+ | 12km+/light 不破 |
| `S4-OI-1d` | Desroziers 在线校准 R/B | 全局 | 持平或更好，且 R/B 自洽 |

执行规则：一次只跑一个 ID，独立输出目录 + 独立 promotion checklist，任一 smoke 打穿硬门槛立即停。

---

## 4. CMA(CRA40) 弱背景融合：完整专项方案（你的核心新增需求）

你的原话需求：**数据很稀疏，但需要一个完全的风场重构结果；想把 CMA 融合进去当弱背景，只需要指出这些地方置信度低就可以。**

这正是 OI 的标准用法。本节给出完整的、不依赖第 3 节也能独立读懂的落地方案。

### 4.1 CMA 数据现状（已确认）

```text
目录: /data/LFT-W02_data/pengxu/cma/   (注意：在项目根，不在 workflow/ 下)
产品: CRA40 再分析, GRIB2, 6 小时一帧
变量: GPH(128) RHU(129) TEM(129) VVP(129) WIU(129) WIV(129)
      —— WIU/WIV 就是 u/v 风, 直接可用作背景
时间覆盖: 2026-01-23 00Z ~ 2026-02-24 (6 小时步长)
分辨率: 全球 ~34km (相对 500m 网格非常粗 → 只能做"大尺度弱先验")
```

> ⚠️ 已发现问题（见第 8 节 P-CMA-1）：文件名带 `?AWSAccessKeyId=...&Signature=...` 的下载后缀，且是 6 小时步长、34km 分辨率。需先确认：(a) 文件能被 cfgrib/eccodes 正常打开（后缀不影响，但要确认 `.grib2` 解析）；(b) 时间覆盖与 5614 帧雷达时刻**完全对齐**（雷达帧若超出 1/23~2/24 则该帧无背景，必须有 fallback）。

### 4.2 融合的三种模式，按"侵入性从弱到强"，**只推荐前两种**

| 模式 | 做法 | 对 holdout 的风险 | 推荐度 |
| --- | --- | --- | --- |
| **M1: display-only 纯兜底填充（fill-only）** | 使用现有 `display_fill_mode=low_conf_background`，只填 `display_u/v/conf/source`，不改 official `recon_u/v/conf/mask` | 0（因为 point eval 仍读 official recon，不读 display） | ★★★ 首选，先做这个 |
| **M2: OI 弱背景（第 3 节）** | 全场 OI，背景方差 `σ_b²` 设得较大，让观测在有它的地方主导 | 低（R/B 平衡保证观测优先） | ★★★ 次选，M1 通过后做 |
| M3: CRA40 伪观测 / virtual radial 3DVar | 把 CRA40 转成伪观测进 `_three_dvar_proxy` | 中（伪观测会进入约束，可能污染） | ★ 仅研究，默认不做 |

> 历史教训：`sparse_temporal_gated CMA` 之所以 FAIL，是因为它虽然只激活约 0.78% 体素，仍在 light wind / 3-6km sparse 点污染 official reconstruction。M1 用 display-only 隔离规避；M2 必须用 **obs_influence 门控 + R/B 平衡 + 200/5614 guardrail** 证明没有重犯这个错误。

### 4.3 M1 纯兜底填充：最小可行落地（实验 ID `S4-CMA-M1`）

这是**风险最低、最快出"完整风场 + 置信度图"的路径**，建议第一个做。

**推荐最小实现（优先用现有代码，不新增 official 字段）**：

`ground_recon.py` 已有 `_make_display_filled_field(...)`，并已在 NPZ 中输出：

```text
C4_DISPLAY_U
C4_DISPLAY_V
C4_DISPLAY_CONF
C4_DISPLAY_MASK
C4_DISPLAY_SOURCE
C4_DISPLAY_FILL_DIAGNOSTICS_JSON
```

它的诊断里已经写死：

```text
display_fill_is_official_accuracy = False
display_fill_note = "Display-only weak background fill. Official recon_u/v/conf/mask and strict holdout metrics are unchanged."
```

因此 `S4-CMA-M1` 的第一版不应新增 `_fill_background_where_unconstrained`，而应：

```text
1. 用 centralized_cma_ra_virtual_radial_3dvar.py 生成每帧 CMA NPZ
2. Stage4 运行时设置:
   --display-fill-mode low_conf_background
   --display-fill-cma-proxy-dir <CMA_NPZ_DIR>
   --display-fill-source cma_reanalysis
   --display-fill-confidence-cap 0.20
   --display-fill-qc-gating strict_temporal
3. 保持:
   --cma-fusion-mode off
   official recon_u/v/conf/mask 不变
```

**可选增强（第二步再做）**：如果现有 display fill 只按 `~official_mask` 填，而你希望按 `obs_influence < eps` 细分背景区，可以新增 `_fill_background_where_unconstrained(...)`，但输出仍必须是 display/product 字段，不得覆盖 official recon：

```text
输入: recon_u/v (核插值结果), weight(acc_w), u_cma/v_cma(CRA40背景), cma_valid_mask
步骤:
  obs_influence_3d = clip(weight / (weight + bg_pseudo_weight), 0, 1)
      # bg_pseudo_weight 是一个小常数, 代表背景的等效权重
  fill_mask = (obs_influence_3d < eps_fill) & cma_valid_mask & (~recon_mask)
      # 只填: 观测约束极弱 且 CRA40 有值 且 当前重构没覆盖
  recon_u_full = where(fill_mask, u_cma, recon_u)
  recon_v_full = where(fill_mask, v_cma, recon_v)
输出新场(不覆盖官方场):
  display_u_full_3d, display_v_full_3d     # 完整产品场(含背景填充)
  display_source_3d                        # 1=official重构, 2=CRA40背景填充
  obs_influence_3d                         # 逐格点观测影响 [0,1]
  background_confidence_3d                 # 背景填充处的置信度 = cma_temporal_conf * 低基线(如0.2)
```

**关键产品语义（必须严格执行，防止误导）**：

- 官方 RMSE/MAE 仍只用 `recon_u/v`（观测重构场），**背景填充格点永不进入官方精度**。代码层面：不要改 `_point_eval_rows`，不要让它读取 `display_u/v` 或 `display_source`。
- `display_u/v` 是 **product footprint（产品完整图）**；`display_source_3d` 明确标注每个格点是"官方观测重构"还是"CRA40 背景填充"。
- 可视化层：背景填充区用**降饱和度 / 加阴影 / 标注 "background-filled, low confidence"**，绝不与观测重构区同等呈现。

**不要新增 CLI（第一版）**：先使用现有 `--display-fill-*` 参数。只有当 display source 需要从 `~official_mask` 扩展为 `obs_influence < eps` 时，再新增 `--display-fill-eps` / `--display-bg-pseudo-weight`。

**`S4-CMA-M1` 验收门**（注意：这是"产品门"，不是 RMSE 门）：

```text
硬约束(必须全过, 否则不发布):
  1. 官方 holdout RMSE/MAE/P95/P99/12km+/light/floor10 与 baseline 完全一致
     (因为 M1 不动观测重构场, 应当严格 == baseline; 若有任何变化 → 有 bug, 说明误填了观测点)
  2. display_source_3d 标注正确: official_mask 内必须 source=1, 背景填充区 source=2
  3. 背景填充区 display_conf <= 0.2~0.3, 与观测区 confidence 明显可分
产品价值验收:
  4. 全场覆盖率从 (重构覆盖率) 提升到接近 100% (CRA40 覆盖范围内)
  5. 若实现 obs_influence_3d: 空间分布合理，飞机航路附近高，远离航路低
```

> M1 的妙处：它对 holdout 指标**零风险**，原因不是“holdout 点必在有观测处”（holdout 被移除后，有些单点压力测试可能没有训练观测支撑），而是 **M1 不改 official recon，point eval 不读 display 字段**。先拿下 M1，产品需求就满足了；再用 M2/第 3 节去争取 holdout 指标改善。

### 4.4 M2 OI 弱背景：见第 3 节（`S4-OI-1`），M1 通过后做

M2 与 M1 的区别：M1 只在"完全无观测"处硬填背景；M2 在**全场**做 obs/bg 的连续加权过渡（OI），背景在中等支撑区也有平滑贡献，过渡更自然，且 `analysis_error_var` 是连续的置信度。M2 风险略高于 M1（背景会轻微进入中等支撑区），所以放在 M1 之后。

### 4.5 置信度图的两种等价表达（都要输出，论文好写）

1. **观测影响 / DFS**：`obs_influence(g) = Σw_i / (Σw_i + ε_bg) ∈ [0,1]`。1=纯观测决定，0=纯背景决定。对应文献 Cardinali et al. (2004) 的 influence matrix `S=HK` 自敏感度、DFS=trace(HK)。[R-Card]
2. **分析误差方差**：`analysis_error_var(g) ≈ σ_b²(g)·(1 - obs_influence(g))`，对应 OI 的 `A=(I-KH)B` 对角线。[R-OI]

两者一一对应（`obs_influence = 1 - diag(A)/diag(B)`）。建议产品里用 obs_influence（直观 0-1），论文里同时给 analysis_error_var（统计严谨）。

---

## 5. CMA 融合的工程前置检查（执行前必须逐条过，否则方法学失效）

### 5.1 P0 泄漏检查（最高优先，决定整个 OI 是否成立）

**风险**：CRA40 再分析在生产时**同化了全球飞机观测**（其论文明确说集成了 aircraft obs）。如果你 holdout 的那批 AMDAR 也被 CRA40 同化过，那么 `x_b`（背景）就"偷看"了真值，OI 的误差统计、obs-minus-background 创新量、Desroziers 诊断全部失效，且 holdout 不再独立。

**检查与处置**：

```text
1. 确认 CRA40 同化截止时间 vs 本项目 AMDAR 时段:
   - CRA40 主产品覆盖 1979-2018, 但本地文件是 2026-01~02 → 大概率是 CRA40 操作型/FTM 近实时延伸
   - 必须查清这批 2026 数据是 reanalysis 还是 forecast(FTM=Forecast?)
2. if CRA40 是纯预报(forecast, 未同化当前 AMDAR):
     → 背景与 holdout 独立, 安全, 可用
   elif CRA40 同化了本项目同源 AMDAR:
     → 背景污染真值. 处置二选一:
        (a) 只把 CRA40 用作 M1 兜底填充(背景填充区本就不进 holdout) → 仍安全
        (b) 若要做 M2 OI 并报告 obs-minus-bg 统计 → 必须改用一个不含本项目 AMDAR 的背景
            (如纯 GFS 预报场), 否则创新量统计无意义
3. 在 leakage_report 里新增字段:
   background_independent_of_holdout: bool
   并在论文/汇报里显式声明背景来源与独立性
```

> 这是**最容易被忽略、后果最严重**的点。务必第一步解决。M1 兜底填充对此**天然免疫**（填充区不参与 holdout），所以即使独立性存疑，M1 也能先上。

### 5.2 时间匹配与覆盖（CRA40 6 小时 vs 雷达帧）

```text
- CRA40 6 小时一帧, 雷达帧密度远高于此 → 必须时间插值.
  复用 centralized_cma_ra_virtual_radial_3dvar.py:427-468 的 linear_qc:
    x_b(t) = (1-α) x_b(T0) + α x_b(T1)
    temporal_conf = exp(-change_speed/24); rapid_change_flag = change_speed>=18
  背景置信度乘上 temporal_conf: 快速变天时背景更不可信 → 自动降权.
- 覆盖检查: 遍历 5614 帧时刻, 确认每帧都有 bracketing 的 CRA40 T0/T1.
    if 帧时刻 < 第一帧CRA40 or > 最后一帧:
        该帧 cma_valid_mask=False, 该帧退化为"无背景"(M1不填, M2 σ_b→∞即纯观测)
        统计并报告这类帧数量
```

### 5.3 Desroziers 在线校准 R/B（避免手猜协方差）

用创新量统计自洽地估计 R、B（**只用 train 观测，不用 holdout**）：

```text
d_ob = y - H x_b        (obs minus background, 用 train 观测)
d_oa = y - H x_a        (obs minus analysis)
则:  R ≈ ⟨d_oa · d_obᵀ⟩      (对角即可)
     HBHᵀ ≈ ⟨d_ab · d_obᵀ⟩,  d_ab = H x_a - H x_b
迭代: 用当前 R/B 跑 OI → 算 d_oa/d_ab → 更新 R/B → 收敛
```

实现为 `centralized_stage4_oi_desroziers_calibrate.py`，输出每个高度层 / 支撑 bin 的 `σ_obs, σ_repr, L_h, L_z` 标定值，写入 OI 配置。[R-Desr]

### 5.4 CRA40 垂直层与 12km+ 对齐

```text
- CRA40 是气压层(GPH 给位势高度), 项目是 500m 等高网格.
  复用 :330-348 的气压→高度插值, 但要确认:
    (a) CRA40 顶层气压能否覆盖到 15km(~120hPa). 若顶层不够高, 12km+ 背景缺失.
    (b) 12km+ 是当前最大 tail 来源. 背景在此处即使有, σ_repr 也要设最大,
        让 OI 在 12km+ 几乎不信背景(避免重蹈 sparse_temporal_cma 在12km+恶化的覆辙).
- 决策: 12km+ 默认只做 M1 兜底填充(标注极低置信度), 不做 M2 主动加权,
        除非 Desroziers 标定显示 12km+ 背景确实有正贡献.
```

---

## 6. Stage4 其余有效优化（与 OI 并行或内嵌，逐条绑文献）

这些是即使不上 OI 也能单独做的增量，且与 OI 兼容（OI 里它们就是 R/B 的具体形式）。

### 6.1 S4-A：表示误差显式建模（吃掉 P2 representation_error、P4 sparse_support）

- 现状：`_build_wind_observations`（:518-585）已有 `representation_error_soft_weight`，但它是启发式风险打分，不是 sigma。
- 改法：拟合 `σ_repr(height, support, nearest_distance, role_gap, vertical_gap, time_conf)`，权重改为 `w ~ 1/(σ_obs² + σ_repr²)`（OI 模式下直接就是 R）。
- 相关观测误差：当相关长度短时先做对角方差膨胀，不要一上来做全相关矩阵 R。[R-Goux]
- if/else：

```text
if bin holdout 点 < 300: 回退父层级 bin 拟合 (防过拟合)
if 估计的 obs-error 相关长度短: 先对角膨胀; else 再考虑 correlated-R
if point is count_0 or dist_ge6: 必须显式抬高 σ_repr
```

- 验收：full-5614 全硬门槛过；12km+ RMSE 改善≥3%；count_0/count_1 至少一层改善≥5%；0-3km 不恶化>0.05。

### 6.2 S4-B：受约束的物理化局地化（吃掉 P1 高空 tail、P2 role conflict）

- 文献：高维下**距离型局地化仍最稳**，非距离型最多边际收益且调参贵；局地化形状可随瞬时流场各向异性变化，但不要做更自由的 point-wise catalog。[R-Gilpin][R-Er]
- 改法：保留距离核为主骨架，只允许在 3 套 kernel family 间切换（K1 dense/low-risk；K2 sparse-current/fresh-context；K3 high-alt/high-vgap/role-conflict），自适应只改 horizontal radius / vertical anisotropy / context-current ratio。**禁止**再引入更细的 point-wise 核（point_regime 已证明失败）。
- if/else：

```text
if alt>=9km and nearest_current_count<=1: 更强垂直 shrink + 更保守水平 widen
if role_gap>=30: 不清空 context; 仅当 current_count>=2 且 dist<=1.5vox 才显著抬 current
if vertical_gap>=10: 降低跨层耦合; else 维持 baseline 垂直保结构
```

- 验收：200 smoke 先过；gap_ge30/vgap_ge10/alt>=9km 至少两层改善≥5%；full-5614 全过。

### 6.3 S4-C：regime-aware 时间权重校准（吃掉 P3 stale context、P5 temporal）

- 现状：`context_time_conf_power`（tp26 用 2.6）是全局常数。
- 改法：对 `timeconf_0.2-0.4 / 0.4-0.6 / >=0.6` 分层做 holdout CV，每层再按 `height × support zone` 拟合半衰期；旧 context 不删，而是通过抬高其 σ（OI 模式下即 R 的时间膨胀）降权。[R-Goux][R-ORCA]
- 验收：timeconf_0.4-0.6 层 RMSE 改善≥5%；light wind 不恶化；全局硬门槛过。

### 6.4 S4-E：把 tail-risk / no-claim 升级为正式 gate（吃掉 P6）

- 现状：`_compute_reliability_fields`（:2158-2242）已产出 reliability_confidence_3d / tail_risk_score_3d / no_claim_mask_3d，但只是解释层。
- 改法：把 `P95/P99/max/tail coverage/risk-strata hit-rate` 固定为二级主表；任何候选只要改善均值却恶化 P95/P99/12km+ 即 reject；只改善 tail 却恶化 light/floor10 的只能留 report-only。
- 这步是**审批纪律**，不改重构本身，但能阻止"看起来均值更好实则更危险"的候选升默认。

---

## 7. Stage5 可行性方案：先修目标定义，再谈模型

### 7.1 必须先承认的根因：Stage5 一直过不了门，不是模型不够大，而是目标定义错了

证据链：
- 点级最安全候选改善仅 **-0.004433 m/s**（33/1893 点）；field-v1 FAIL；field-v2 只要 `alt12_scale>0` 全 FAIL。
- Stage4 holdout component RMSE 10.27，其中 excess variance fraction 0.93 是**表示误差 + 重构误差**，不是可被残差网络在"点 vs 500m体素"尺度上学回来的可恢复信号。

**结论**：在当前目标（"降低 holdout 点 RMSE"）下，Stage5 的可改空间已逼近**表示误差地板**（见第 8 节）。继续在这个目标上加大 PINN 只会过拟合噪声。**Stage5 必须换目标。**

### 7.2 Stage5 的两个新目标（择一或并行，都比"降点RMSE"可行）

**目标 A：不确定性驱动的"弃改"残差（uncertainty-gated abstention residual）** —— 推荐主线

把 Stage5 重定义为"学习**在哪里不要改**"，而不是"在哪里改一点"。这与文献趋势一致（selective prediction / conformal abstention）。[R-Confm][R-LSCP]

- 模型已有异方差输出 `(delta, sigma)`（train.py:49-67），扩展为 **deep ensemble（多 seed）**得到 epistemic 方差。
- 用 **split / 局地空间 conformal** 把 90% 区间校准到 holdout 覆盖率 87-93%。nonconformity score 可用物理残差（physics-informed conformal，无需大量标签）。[R-PIConf]
- 应用规则：`residual 仅在 (区间宽度 < 阈) 且 (alt<12km) 且 (not light) 且 (support good) 时施加；否则 abstain→保持 Stage4 场`。
- if/else：

```text
if 90% interval coverage ∉ [87%,93%]: 不允许 field apply (先修校准)
if local uncertainty > 阈 or tail_risk_flag: residual=0, 只报风险
if alt>=12km: residual=0 (固化 alt12_off, 已被 field-v2 证明)
```

- 价值：即使 RMSE 不降，也能产出**校准良好的不确定性场**（论文可写、产品可用），这是比 0.00x RMSE 更扎实的贡献。

**目标 B：observation-informed 残差架构（PINN plateau 后的 fallback）**

若 PINN 在稳定化 + UQ 后点级改善仍 <0.02 m/s，停止拧 PINN 主干，转：
- B1：set-transformer / cross-attention 残差（ORCA 式，处理不规则观测集，海洋风 correction 已证明 1h 降误差 45%）。[R-ORCA]
- B2：FNP（Fourier Neural Process）任意分辨率同化。[R-FNP]
- B3：Energy Transformer 稀疏场重构（90% 缺测仍可恢复）。[R-ET]

### 7.3 Stage5 训练稳定化（无论哪个目标都要做）

PINN 训练病态是已知问题，按 SOTA best practice：[R-WangPINN][R-Rathore]

```text
1. Fourier feature embedding + modified MLP (抗谱偏差)
2. 动态损失权重 (NTK / grad-norm 平衡 PDE/data/BC 项)
3. 优化器: Adam warmup → L-BFGS refine; 仍不稳再 energy-NGD / NNCG (二阶)
4. 时间维若存在: causal weighting w_i=exp(-ε Σ_{k<i} L_r(t_k))
if train-val gap 大: 提正则 + 缩小 residual 目标范围
if PDE loss 主导且 data loss 不降: 放缓 physics 权重上升
不同 seed 结果符号必须一致 (否则是噪声, 不是信号)
```

### 7.4 Stage5 决策线与验收

```text
point continuation gate: RMSE 改善>=0.02, P95 改善>=0.10, light/floor10 不恶化,
                         90% coverage∈[87%,93%], 多 seed 符号一致
  不过 → 不进 field, 回 7.3/目标A 的 UQ
  过   → 200-frame field smoke (alt12 默认关)
field smoke 过但 gain<0.02 且 changed points<=2 → 只留 research note, 不升默认
field smoke 过且达工程门槛 → 进 full-5614
full-5614 任一硬门槛破 → 仍非默认
PINN 稳定化+UQ 后仍极小 → 转 observation-informed 架构(目标B)
```

> Stage5 现实定位（写给老师）：**当前阶段 Stage5 的正确产出不是"更准的风"，而是"更可信的不确定性 + 更克制的修改"**。这与"Stage4 OI 提供完整场 + 置信度"形成一致的方法学叙事。

---

## 8. 我额外发现的潜在问题 + 解决方法（你项目目前已做的部分）

这些是我通读代码与文档后发现的、文档里没明确点出的风险点。按严重度排序。

### P-LEAK-1（严重）：CRA40 背景可能与 holdout AMDAR 不独立

见 5.1。**解决**：先查 CRA40 是 reanalysis 还是 forecast；M1 兜底填充对此免疫，可先上；M2/创新量统计前必须确认独立性或换独立背景。在 leakage_report 增 `background_independent_of_holdout` 字段并在论文声明。

### P-OI-1（严重）：原方案的“局地标量 OI”公式不严谨

- 现状：原稿写 `x_a = x_b + Σw_i innovation_i / (Σw_i + ε_bg)`，但 `w_i`、`ε_bg` 没有显式单位，也没有 `sigma_b^2` 和 `sigma_i^2`。这更像 nudging，不是严格 OI。
- 风险：如果按这个公式实现，会把背景强弱调成任意伪权重；论文里称 OI/3D-Var 容易被质疑。
- **解决**：按第 3.1 修订公式实现。第一版命名为 `oi_diag_approx`；只有实现局地 `S = HBH^T + R` 求解时才命名 `local_oi`。所有输出必须包含 `sigma_b_mps`、`sigma_obs_mps`、`sigma_repr_mps`、`obs_influence`、`analysis_error_var`。

### P-M1-1（严重）：M1 不能改 official recon，也不能假设 holdout 点一定有观测支撑

- 现状：原稿说 holdout 点“必在有飞机观测处”，所以 M1 风险近 0。严格来说，holdout 被移除后，某些 single-holdout 压力测试点可能没有训练 current 支撑；如果背景填进 official `recon_u/v`，point eval 就可能变化。
- **解决**：M1 第一版必须只走 `display_fill_mode=low_conf_background`，保持 `--cma-fusion-mode off`，不改 `recon_u/v/conf/mask`，不改 `_point_eval_rows`。M1 的官方指标应与 baseline 完全一致；不一致就是 bug。

### P-REPRO-0（严重）：文中部分命令参数当前不存在

- 当前不存在：`--emit-background-npz`、`--time-match-mode`、`--cma-background-dir`、`--cma-fill-mode`、`--cma-fill-eps`、`--recon-mode`、`--oi-*`。
- 当前存在且应优先使用：
  ```text
  centralized_cma_ra_virtual_radial_3dvar.py:
    --cma-time-method linear_qc
    --out-dir <CMA_NPZ_DIR>

  centralized_stage4_ground_recon.py:
    --display-fill-mode low_conf_background
    --display-fill-cma-proxy-dir <CMA_NPZ_DIR>
    --display-fill-source cma_reanalysis
    --display-fill-confidence-cap 0.20
    --display-fill-qc-gating strict_temporal
  ```
- **解决**：第 9 节命令已按现有 CLI 改写；所有新增 OI 参数都标为“需先实现”。

### P-FRAME-1（严重）：frame-times 文件格式不一致

- 现状：`FRAMES200`、`FRAMES5614` 是逐行文本；`centralized_stage4_sensitivity.py` 能读逐行文本，但 `centralized_stage4_ground_recon.py` 和 `centralized_cma_ra_virtual_radial_3dvar.py` 的 `--frame-times-file` 要求 JSON list。
- **解决**：运行 `ground_recon.py` 或 `centralized_cma_ra_virtual_radial_3dvar.py` 前，先生成 JSON list：
  ```bash
  $PY - <<'PY'
  import json
  from pathlib import Path
  src = Path("centralized_v1_output/stage4_guardrail_display_fill_200_20260605_25w/tp26_thr11_preserve_metrics/stage4_validation_frame_times.txt")
  dst = Path("centralized_v1_output/stage4_guardrail_display_fill_200_20260605_25w/tp26_thr11_preserve_metrics/stage4_validation_frame_times.json")
  frames = [x.strip() for x in src.read_text().splitlines() if x.strip()]
  dst.write_text(json.dumps(frames, indent=2), encoding="utf-8")
  print(dst, len(frames))
  PY
  ```

### P-REP-1（严重）：`tp26_rep_soft_weight_v1` full-5614 口径已更新为 FAIL

- 文档冲突：`ultimate_summary_20260612` 仍写“5614 未完成”；但 `centralized_v1_stage45_literature_backed_optimization_plan_20260612.md` 已记录来自本地 `rep5614_analysis` 的 full-5614 pairwise，candidate 明确 FAIL：
  ```text
  weighted RMSE: 14.520015 -> 15.303054
  12km+ RMSE:    17.585340 -> 18.630932
  light RMSE:    5.510587  -> 5.852620
  new light/mod tail failure: 0 -> 9
  ```
- **解决**：不再把“跑完 rep-soft 5614”列为优先动作；它已是 failed scale-up。后续 representation 方向只能做 report-only、sigma calibration 或重新设计，不得沿用 `tp26_rep_soft_weight_v1` 作为待 promotion 候选。

### P-FLOOR-1（严重，影响目标设定）：缺少显式"误差地板"，导致 Stage4/5 在追不可达的指标

- 现状：excess variance fraction 0.93 说明大部分 RMSE 是表示误差，但项目没有把"理论可达下界"算出来当参照。
- 后果：Stage5 一直在 0.00x m/s 上挣扎，团队却不知道**距离地板还有多远**。
- **解决**：新建 `centralized_stage4_error_floor_estimate.py`，用三重配置/representativeness 估计 `σ_repr` 的不可约部分，给出"点 vs 500m/6min 体素"的**RMSE 理论地板**（预计在 5-8 m/s 量级）。所有 Stage4/5 改善都相对地板报告"skill = 1 - (RMSE-floor)/(baseline-floor)"。这能让老师看清"还剩多少真实空间"，避免无意义内卷。[R-deHaan][R-KNMI]

### P-WRMSE-1（中）：weighted RMSE(14.5) 远高于 frame RMSE(8.4)，weighting 口径可能放大少数高权重 tail

- 现状：weighted RMSE 比 frame mean RMSE 高近一倍，说明权重集中在少数高权重点上。
- 风险：promotion gate 主看 weighted RMSE，可能被极少数点绑架，导致"对整体有益但动了那几个点"的候选被误杀。
- **解决**：审计 weighted RMSE 的权重来源（是哪些点、权重多大），在二级表里同时报告 unweighted 与 trimmed（去掉 top-1% 权重点）RMSE，让决策不被单一口径绑架。**不改主 gate，但增加诊断维度。**

### P-CONF-1（中）：当前 recon_confidence 是权重的 90 分位归一，缺统计意义

- 现状：`_normalize_confidence`（:2098-2104）把 acc_w 按 90 分位 clip 到 [0,1]，这只是"相对权重"，不是误差概率。
- 风险：产品里说"置信度 0.8"无法对应任何误差量级，老师/用户会误读。
- **解决**：OI 模式下用 `obs_influence` 或 `1 - diag(A)/diag(B)` 替代，它有明确语义（观测决定 vs 背景决定）。kernel 模式下至少做一次"confidence vs 实际 holdout 误差"的可靠性曲线校准（reliability diagram），把 confidence 映射到经验误差分位。

### P-CMA-1（中）：CRA40 文件名带下载签名后缀 + 6h/34km 粗分辨率

见 4.1。**解决**：(a) 写个 `verify_cma_grib.py` 批量确认每个文件能被 cfgrib 打开、含 WIU/WIV、层数与顶层气压达标；(b) 34km→500m 是大尺度先验，明确只用于"弱背景"，不宣称背景有中小尺度能力；(c) 时间覆盖与 5614 帧做交集统计，报告多少帧无背景。

### P-VERT-1（中）：12km+ 既是最大 tail（SSE 76%）又是 CRA40 顶层可能缺失区

见 5.4。**解决**：12km+ 默认只做 M1 兜底 + 极低置信标注，不做主动加权；除非 Desroziers 显示正贡献。

### P-TAIL-CAL-1（轻）：tail 未做独立校准验证

- 现状：项目盯 P95/P99 数值，但没验证"极端预测是否可靠"（tail calibration）。
- **解决**：用 Allen et al. (2024) 的 tail calibration diagram，对极端风速段单独验证可靠性，与 bulk calibration 分开报告。若做 Stage5 概率输出，可用 tail-weighted scoring rule 训练（注意 tail-vs-bulk 权衡）。[R-Allen]

### P-REPRO-1（轻）：实验目录繁多，promotion 口径需固化

- **解决**：每个实验 ID 独立输出目录 + 独立 promotion_checklist.json（记录用了哪个 200/5614 frame list、baseline csv、tolerance）。固定 `--promotion-tolerance 1e-9`，固定 frame list 路径（见 9.3）。

---

## 9. 执行顺序、命令模板、实验矩阵

### 9.1 推荐执行顺序（严格按此，先低风险高价值）

```text
第0步(必做前置): P-LEAK-1 独立性检查 + P-CMA-1 GRIB 校验 + P-FLOOR-1 误差地板估计
第1步: 转换 frame-times JSON + 生成 CMA NPZ
第2步: S4-CMA-M1 display-only 纯兜底填充 → 立刻交付"完整风场+置信度图", 对 official holdout 零风险
第3步: S4-OI-DIAG report-only innovation / obs-influence / background reliability 诊断，不改 recon
第4步: 若 S4-OI-DIAG 证明背景可靠，再实现 S4-OI-1a/1b（R 膨胀 + B 各向异性，先 oi_diag_approx）
第5步: S4-OI-1c/1d 引 CRA40 背景 OI + Desroziers 校准 (= M2)
第6步: S4-B 受约束局地化 + S4-C 时间校准 (按失败 stratum 选)
第7步: 只有 Stage4 official branch 变更且通过 gate 后，才重抽 Stage5 residual dataset
第8步: Stage5 目标A (UQ-gated abstention) + 7.3 稳定化；plateau 后再转目标B
全程: S4-E tail gate 纪律 + P-WRMSE/P-CONF 诊断维度
```

### 9.2 分支选择线（按失败来源决定先做哪个）

```text
失败主来自 count_0/count_1/dist_ge6 → S4-A + S4-CMA-M1/M2
失败主来自 gap_ge30/role_conflict   → S4-B
失败主来自 timeconf_0.4-0.6         → S4-C
失败主来自 tail 非 mean             → S4-E
想同时改 localization+background+temporal → 拒绝, 必须拆成单机制 ablation
```

### 9.3 固定资产路径（执行时直接引用）

```text
PY=/data/LFT-W02_data/pengxu/.conda/envs/windy310/bin/python
STAGE2=centralized_v1_output/stage2_full_v2/stage2_multimodal_summary.json
STAGE3=centralized_v1_output/stage3_full_v2_25w_payload_only/stage3_center_summary.json
FRAMES200=centralized_v1_output/stage4_guardrail_display_fill_200_20260605_25w/tp26_thr11_preserve_metrics/stage4_validation_frame_times.txt
FRAMES200_JSON=centralized_v1_output/stage4_guardrail_display_fill_200_20260605_25w/tp26_thr11_preserve_metrics/stage4_validation_frame_times.json
FRAMES5614=centralized_v1_output/stage4_full_tp26_thr11_preserve_25w_taildiag_20260602_173319/stage4_holdout_only_frame_times_5614.txt
FRAMES5614_JSON=centralized_v1_output/stage4_full_tp26_thr11_preserve_25w_taildiag_20260602_173319/stage4_holdout_only_frame_times_5614.json
CMA_DIR=/data/LFT-W02_data/pengxu/cma
```

### 9.4 命令模板

**(a0) 前置：把逐行 frame list 转成 JSON list**

`centralized_stage4_sensitivity.py` 能读逐行 txt；但 `centralized_stage4_ground_recon.py` 和 `centralized_cma_ra_virtual_radial_3dvar.py` 的 `--frame-times-file` 要 JSON list。先做一次转换：

```bash
$PY - <<'PY'
import json
from pathlib import Path
pairs = [
    (
        Path("centralized_v1_output/stage4_guardrail_display_fill_200_20260605_25w/tp26_thr11_preserve_metrics/stage4_validation_frame_times.txt"),
        Path("centralized_v1_output/stage4_guardrail_display_fill_200_20260605_25w/tp26_thr11_preserve_metrics/stage4_validation_frame_times.json"),
    ),
    (
        Path("centralized_v1_output/stage4_full_tp26_thr11_preserve_25w_taildiag_20260602_173319/stage4_holdout_only_frame_times_5614.txt"),
        Path("centralized_v1_output/stage4_full_tp26_thr11_preserve_25w_taildiag_20260602_173319/stage4_holdout_only_frame_times_5614.json"),
    ),
]
for src, dst in pairs:
    frames = [x.strip() for x in src.read_text(encoding="utf-8").splitlines() if x.strip()]
    dst.write_text(json.dumps(frames, ensure_ascii=False, indent=2), encoding="utf-8")
    print(dst, len(frames))
PY
```

**(a) 前置：CRA40 背景预处理（每帧 NPZ，使用现有 CLI）**

```bash
$PY stage/centralized_v1/core/centralized_cma_ra_virtual_radial_3dvar.py \
  --cma-dir $CMA_DIR \
  --stage2-summary $STAGE2 \
  --frame-times-file $FRAMES200_JSON \
  --cma-time-method linear_qc \
  --aircraft-anchor-mode stage4_train_wind \
  --stage4-holdout-fraction 0.125 \
  --stage4-holdout-count 0 \
  --out-dir centralized_v1_output/stage4_cma_background_v1 \
  --num-workers 12
# 输出: cma_ra_virtual_radial_3dvar_<frame>.npz，已含 u_cma_3d/v_cma_3d/cma_temporal_conf_3d
```

**(b) Stage4 baseline（tp26，确认口径一致）**

```bash
POLARS_MAX_THREADS=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 \
$PY stage/centralized_v1/core/centralized_stage4_sensitivity.py \
  --stage2-summary $STAGE2 --stage3-summary $STAGE3 \
  --frame-times-file $FRAMES200 \
  --out-dir centralized_v1_output/stage4_oi_baseline_200_20260614/tp26_metrics \
  --param-grid 8,4,2,1 --kernels gaussian --confidence-mode diagnostic_weighted \
  --physics-constraint-mode pydda_3dvar_proxy --current-weight-boost 2.0 \
  --context-weight-scale 0.5 --context-time-conf-power 2.6 \
  --role-conflict-mode current_priority_adaptive \
  --conflict-speed-threshold-mps 11 --conflict-context-factor 0.25 \
  --num-workers 12
```

**(c) S4-CMA-M1 display-only 兜底填充（不改 official recon）**

```bash
$PY stage/centralized_v1/core/centralized_stage4_ground_recon.py \
  --stage2-summary $STAGE2 --stage3-summary $STAGE3 \
  --frame-times-file $FRAMES200_JSON \
  --cma-fusion-mode off \
  --display-fill-mode low_conf_background \
  --display-fill-cma-proxy-dir centralized_v1_output/stage4_cma_background_v1 \
  --display-fill-source cma_reanalysis \
  --display-fill-confidence-cap 0.20 \
  --display-fill-qc-gating strict_temporal \
  --out-dir centralized_v1_output/stage4_cma_m1_fill_200_20260614
# 验收: 官方 holdout 指标必须 == baseline；新增价值只看 display_* 覆盖率、source、confidence
```

**(d) pairwise 正式比较（200 smoke / 5614 formal 同此模板）**

```bash
$PY stage/centralized_v1/core/centralized_stage4_pairwise_frame_compare.py \
  --baseline-csv <tp26>/stage4_localization_sensitivity.csv \
  --candidate-csv <cand>/stage4_localization_sensitivity.csv \
  --baseline-point-csv <tp26>/stage4_point_departures.csv \
  --candidate-point-csv <cand>/stage4_point_departures.csv \
  --baseline-label tp26 --candidate-label candidate \
  --out-dir <out> --out-prefix tp26_vs_candidate \
  --top-n 30 --promotion-tolerance 1e-9
```

### 9.5 实验矩阵

| ID | 阶段 | 只改 | 不许改 | 先看 | smoke 过 | formal 过 | 失败转向 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `S4-CMA-M1` | S4 product | display-only CRA40 兜底填充 | official recon / point eval | display 覆盖率/置信图 | 官方指标==baseline | 同 | 修 display fill |
| `S4-OI-DIAG` | S4 report | background innovation、obs_influence 诊断 | recon_u/v | OMB 分层、background reliability | 不需要 promotion | 只报告 | 不进 M2 |
| `S4-A` | S4 candidate | σ_repr 分层 | localization/bg | count_0/1,dist_ge6 | 全硬门槛过 | count层≥5% | S4-OI-1a |
| `S4-OI-1a` | S4 candidate | R 膨胀 + oi_diag_approx | bg official blend | count/dist | 不破light/12km+ | 持平+稳健 | S4-OI-1b |
| `S4-OI-1b` | S4 candidate | B 各向异性 | bg official blend | gap/vgap/alt9 | 全过 | ≥2层≥5% | S4-B |
| `S4-OI-1c` | S4 candidate | CRA40 local OI 背景 | 手调 broad rescue | 完整性+12km+ | 12km+/light不破 | count_0≥5% | 退 M1-only |
| `S4-OI-1d` | S4 report/candidate | Desroziers 校准 | holdout truth | 全局 | 持平 | R/B 自洽 | 保守值 |
| `S4-B` | S4 | 3 套约束 kernel | bg | gap/vgap/alt9 | 全过 | ≥2层≥5% | S4-C |
| `S4-C` | S4 | regime 时间衰减 | localization/bg | timeconf_0.4-0.6 | light不恶化 | 该层≥5% | 退baseline |
| `S5-A` | S5 | UQ-gated abstention | PINN架构 | coverage/tail | continuation gate | 200全过 | S5-B/目标B |
| `S5-B` | S5 | Adam→L-BFGS+动态权重 | apply gate | point dataset | RMSE≥0.02,P95≥0.10 | 进field | S5-C/目标B |
| `S5-C` | S5 | ensemble+conformal | 主架构 | coverage | 90%∈[87,93] | field全过 | 目标B |
| `S5-D` | S5 | observation-informed 架构 | S4主干 | point first | continuation | 200+5614全过 | 停 default 推进 |

执行规则：一次一个 ID；独立目录 + 独立 checklist；smoke 打穿即停，不进 formal。

---

## 10. 论文叙事建议（一句话主张升级版）

旧主张（仍成立）：centralized_v1 提供了以 aircraft strict holdout 为唯一正式 truth 的、可审计的中心化三维风场重构与验证框架。

M1 完成后可升级为：
> centralized_v1 在保持 strict aircraft holdout official accuracy 不变的前提下，新增了 CRA40 弱背景 display-fill 产品层，以 `display_source` 和低置信度显式区分观测重构区与背景填充区，从而把"完整产品图"与"已验证精度足迹"分离。

只有 M2/local OI 通过 200 + full-5614 后，才可进一步升级为：
> centralized_v1 将稀疏飞机风重构表述为**以 CRA40 为弱背景的局地 OI / OI-inspired 估计器**，在严格 aircraft holdout 验证下，通过**观测影响 / 分析误差方差**逐格点量化"观测约束 vs 背景主导"；Stage5 在此之上以**校准不确定性驱动的弃改残差**形式提供受控修正。

可写的方法学贡献分层：

```text
现在可写: strict holdout validation + data-role separation + display/product footprint vs validated accuracy footprint
M1后可写: weak-background display-fill with explicit source/confidence, official metrics unchanged
M2通过后才可写: kernel smoother upgraded to B/R-aware local OI with observation influence / analysis variance
Stage5通过后才可写: uncertainty-gated residual abstention
```

---

## 11. 给执行智能体的最终 checklist

```text
[ ] 第0步: P-LEAK-1 查 CRA40 reanalysis/forecast 与 holdout 独立性
[ ] 第0步: P-CMA-1 verify_cma_grib.py 校验 GRIB 可读/变量/层数/时间覆盖
[ ] 第0步: P-FLOOR-1 误差地板估计脚本, 给出理论可达 RMSE
[ ] 第0步: 把 FRAMES200/FRAMES5614 逐行 txt 转 JSON list, 供 ground_recon/CMA 脚本使用
[ ] 第1步: 用现有 centralized_cma_ra_virtual_radial_3dvar.py 生成 CMA NPZ
[ ] 第2步: 用现有 display-fill 跑 S4-CMA-M1:
         --cma-fusion-mode off + --display-fill-mode low_conf_background
         验收: 官方 holdout 指标 == baseline, display 覆盖率→~100%, display_source/conf 可分
[ ] 第3步: S4-OI-DIAG 只做 innovation/obs_influence/analysis_var report-only, 不改 recon
[ ] 第4步: 如 S4-OI-DIAG 通过, 实现 --recon-mode oi_diag_approx/local_oi 和 _accumulate_local_oi
[ ] 第5步: CRA40 OI 背景 (S4-OI-1c) + Desroziers 校准 (S4-OI-1d)
[ ] 第5步: 按失败 stratum 选 S4-B / S4-C
[ ] 第6步: 只有 Stage4 official branch 变更且通过 gate 后, 才重抽 Stage5 residual dataset
[ ] 第7步: Stage5 目标A UQ-gated abstention + 7.3 稳定化
[ ] 第8步: plateau → Stage5 目标B observation-informed 架构
每步: 独立输出目录 + promotion_checklist.json; smoke→formal 两道门; 一次一个 ID
红线: CMA 永不进真值; strict_holdout_no_leakage 不破; motion 不当风;
      背景填充区不进官方 RMSE; 12km+ 背景默认极低置信
```

---

## 12. 参考文献（本方案实际采用，含 URL）

数据同化理论侧：

- [R-OI] Barth, Alvera-Azcárate et al. *Introduction to Optimal Interpolation and Variational Analysis.* （OI=BLUE，A=(I-KH)B 误差方差图推导）
- [R-Card] Cardinali, Pezzulli, Andersson (2004). *Influence-matrix diagnostic of a data assimilation system.* QJRMS. （S=HK 自敏感度、DFS=trace(HK) 观测影响图）https://www.researchgate.net/publication/229471266
- [R-Desr] Desroziers et al. *Error Covariance Estimation Methods Based on Analysis Residuals.* （R≈⟨d_oa·d_obᵀ⟩, B≈⟨d_ab·d_obᵀ⟩ 在线校准）
- [R-Goux] Goux et al. (2025). *On the impact of observation error correlations in data assimilation.* arXiv:2503.09140 （相关长度短→方差膨胀近似）
- [R-Gilpin] Gilpin, Morzfeld, Lin (2025). *Numerical study of high-dimensional covariance estimation and localization.* arXiv:2508.18299 （距离型局地化最稳）
- [R-Er] Er, Meldi (2025). *Physics-based localization methodology for DA by EnKF.* arXiv:2511.08845 （局地化形状随流场各向异性）
- [R-Weaver] Weaver & Courtier (2001); Mirouze & Weaver (2010). 扩散算子相关模型，L=√(2κT)。Ocean Modelling 35:45.
- [R-deHaan] de Haan (2016). *Estimates of Mode-S EHS aircraft-derived wind observation errors using triple collocation.* AMT 9:4141. （仪器误差 1.1-1.4 m/s）https://amt.copernicus.org/articles/9/4141/2016/
- [R-EMADDC] de Haan et al. (2025). *EMADDC: high-volume … wind and temperature from Mode-S EHS.* AMT 18:3341.
- [R-KNMI] KNMI. *Quintuple collocation of in-situ/scatterometer/NWP winds.* （表示误差估计）
- [R-CRA40] Liu et al. (2023). *CRA-40/Atmosphere: First-Generation Chinese Atmospheric Reanalysis.* J. Meteorol. Res. https://link.springer.com/doi/10.1007/s13351-023-2086-x

机器学习 / 重构 / UQ 侧：

- [R-WangPINN] Wang, Sankaran, Wang, Perdikaris (2023). *An Expert's Guide to Training PINNs.* arXiv:2308.08468
- [R-Rathore] Rathore et al. (2024). *Challenges in Training PINNs: A Loss Landscape Perspective.* ICML. arXiv:2402.01868
- [R-Causal] Wang, Sankaran, Perdikaris (2022). *Respecting causality is all you need for training PINNs.* arXiv:2203.07404
- [R-ORCA] *Observation-driven correction of NWP for marine winds.* arXiv:2512.03606 （set-attention 残差 correction，1h 降误差 45%）
- [R-FNP] Chen et al. (2024). *FNP: Fourier Neural Processes for Arbitrary-Resolution Data Assimilation.* NeurIPS. arXiv:2406.01645
- [R-ET] Zhang, Krotov, Karniadakis (2025). *Operator Learning for Reconstructing Flow Fields from Sparse Measurements: Energy Transformer.* arXiv:2501.08339 （90% 缺测可重构）
- [R-PIConf] Gopakumar et al. (2025). *Calibrated Physics-Informed Uncertainty Quantification.* arXiv:2502.04406 （物理残差作 nonconformity score）
- [R-Confm] Yu, Ho, Wang (2025). *A Conformal Prediction Framework for UQ in PINNs.* arXiv:2509.13717
- [R-LSCP] Jiang, Xie (2024). *Spatial Conformal Inference through Localized Quantile Regression.* arXiv:2412.01098 （区间在稀疏区自动变宽）
- [R-DINCAE] Barth et al. (2020/2022). *DINCAE 1.0/2.0: CNN with error estimates to reconstruct satellite observations.* GMD 13:1609 / 15:2183. （填充场+逐像元误差图先例）
- [R-Ensemble] Lakshminarayanan et al. (2016). *Simple and Scalable Predictive Uncertainty via Deep Ensembles.* arXiv:1612.01474
- [R-Allen] Allen, Koh, Segers, Ziegel (2024). *Tail calibration of probabilistic forecasts.* arXiv:2407.03167; 续作 (2025) *Enforcing tail calibration when training.* arXiv:2506.13687

---

## 13. 与现有 06-12 文献方案的关系

本文**不推翻** `centralized_v1_stage45_literature_backed_optimization_plan_20260612.md`，而是：

1. 把它的 S4-A（representation sigma）、S4-B（constrained localization）、S4-C（temporal）、S5-A/B/C/D 全部保留为第 6、7 节，门槛口径一致。
2. **新增主干**：用 OI 把这些散点统一成一个估计器（第 3 节），并把 CMA 弱背景融合（第 4 节，你的新需求）作为 OI 的背景项落地。
3. **新增**第 5 节工程前置检查、第 8 节我发现的潜在问题、第 9 节可执行命令与矩阵。

执行智能体若时间有限，**最小可行路径 = 第 0 步前置 + 第 1 步 S4-CMA-M1**，即可交付"完整风场 + 低置信度标注 + CMA 弱背景"，且对官方指标零风险。其余为进阶。
