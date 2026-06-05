# centralized_v1 Stage4 重构质量提升方法建议（2026-06-01）

本文档用于新窗口直接接手实现。目标是在不破坏 centralized_v1 严格 aircraft holdout 规则的前提下，提升 Stage4 三维风场重构质量，尤其是 TimePower15 在局部失败帧、强风/垂直急变长尾、CMA 弱背景拉偏场景中的表现。

## 0. 当前基线和必须遵守的边界

当前最新三方法 200 帧 strict holdout 对比目录：

```text
/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_three_method_compare_20260531
```

关键结论：

```text
method              frames  holdout_points  frame RMSE/MAE       weighted RMSE/MAE
aircraft baseline   200     530             11.6898 / 10.3011    18.9184 / 10.3509
TimePower15         200     530              8.6365 /  7.4232    15.0387 /  7.1727
CMA weak bg         200     530              9.3770 /  8.0171    14.9638 /  7.8683
```

逐帧胜负：

```text
TimePower15 vs aircraft baseline: 143 win / 56 loss / 1 tie
CMA vs TimePower15:                66 win / 134 loss / 0 tie
CMA vs aircraft baseline:         115 win / 85 loss / 0 tie
```

解释边界：

1. TimePower15 总体优于纯航空器 baseline；旧 4 帧小样本中“TimePower15 更差”是抽样偏差。
2. TimePower15 仍有 56 帧输给 baseline，主要是局地支撑结构问题：8/4 窄核和 current-priority adaptive 会减少上下文外推；如果 holdout 点更依赖宽上下文，12/6 baseline 可能偶然更接近。
3. CMA 弱背景可以兜底部分极端坏帧，但会把局地飞机观测结构拉向大尺度背景，因此不是稳定增益项。

必须遵守：

```text
official truth = current aircraft wind holdout only
no-holdout frames = unverified reconstruction, not official RMSE/MAE
motion_records/context_motion_records = coverage diagnostics, not wind truth
CMA/CRA40/GFS/ERA = weak background / condition / prior, not truth
500 m grid point wind RMSE != 30 m wind shear threshold
```

## 1. 总体路线

最推荐的路线不是直接替换 TimePower15，而是：

```text
F_final = F_TimePower15 + calibrated_assimilation_delta + optional_residual_model_delta
```

优先级：

1. 观测误差感知权重：把经验 confidence 改成 aircraft observation-error-driven 权重。
2. 自适应 localization：不要固定 8/4 或 12/6，按局地诊断选择 radius/sigma 或混合权重。
3. 小窗口 OI/3DVar：把局地 bbox 中的重构改成 background + observation + regularization 的优化问题。
4. 动态 CMA/多背景 gating：CMA 只在高可信、低局地飞机支撑、低 rapid-change 时进入。
5. 残差学习：PINN/FNO/DeepONet/Diffusion 只做 TimePower15 之后的残差和不确定性，不直接替代主链路。

## 2. 方法一：Aircraft Observation-Error Calibration

### 2.1 为什么做

当前 TimePower15 的 `diagnostic_weighted` 已有：

```text
density_conf_factor
speed_qc_conf
local_consistency_conf
time_conf
obs_conf
```

但它们仍是经验型 confidence，不是真正的观测误差方差。Mode-S / aircraft-derived wind 文献强调飞机风观测需要系统 QC 和误差估计。de Haan & Stoffelen 2016 用 triple collocation 估计 Mode-S EHS 风误差；EMADDC 2025 也强调高质量 aircraft weather observations 必须经过 QC 和误差控制。

参考：

```text
https://amt.copernicus.org/articles/9/4141/2016/
https://amt.copernicus.org/articles/18/3341/2025/
https://wmo.int/aircraft-based-observations-programme
```

### 2.2 建议实现

新增 calibration 输出：

```text
stage4_aircraft_obs_error_calibration.json
stage4_aircraft_obs_error_calibration.md
```

每条 wind record 估计：

```text
sigma_obs_u
sigma_obs_v
sigma_obs_vector
obs_error_weight = 1 / max(sigma_obs_vector^2, sigma_floor^2)
```

可用特征：

```text
altitude
speed
u/v magnitude
time_conf
obs_conf
aircraft/local density
same-frame neighbor consistency
context departure
CMA/GFS/ERA departure, only as background departure, not truth
role_conflict_gap
vertical_context_mismatch flag
```

初版不用训练模型，可以做分箱统计：

```text
sigma_obs = f(alt_bin, speed_bin, density_bin, local_consistency_bin, context_departure_bin)
```

第二版再用 robust regression / quantile regression 学习。

### 2.3 代码落点

主要入口：

```text
stage/centralized_v1/core/centralized_stage4_ground_recon.py
stage/centralized_v1/core/centralized_stage4_sensitivity.py
```

建议新增：

```text
stage/centralized_v1/core/centralized_stage4_obs_error_calibration.py
```

然后在 `_build_wind_observations` 或 active weight 形成处，把：

```text
active_weight = obs_conf * time_conf * localization * diagnostic_factor
```

扩展为：

```text
active_weight = localization * time_conf * obs_error_weight * optional_diagnostic_factor
```

注意：holdout 观测不得进入 calibration target。可以使用训练侧非 holdout 记录之间的 leave-one-within-training consistency 做校准，或者用历史全量统计，但每次评估帧的 holdout 点不能泄漏。

### 2.4 评估

在 200 帧 metrics-only 上新增一条：

```text
timepower15_obs_error_calibrated
```

必须报：

```text
frame mean RMSE/MAE
holdout-point weighted RMSE/MAE
single vs multi holdout
baseline_rmse_band
strong wind subset
vertical mismatch subset
TimePower15 old vs calibrated win/loss
```

## 3. 方法二：Adaptive Localization / Multi-Kernel Gating

### 3.1 为什么做

200 帧结果已经说明：

```text
8/4 TimePower15 overall better
12/6 baseline still wins 56 frames
```

固定核不是最优。下一步应从固定 `localization_radius_xy=8, sigma_xy=4` 改成按局地诊断自适应。

Gaspari-Cohn / DART localization 文档说明 localization 是同化系统中的核心设计对象，而不是一次性常数。

参考：

```text
https://docs.dart.ucar.edu/en/latest/assimilation_code/modules/assimilation/cov_cutoff_mod.html
```

### 3.2 简单可实现版本

不要一开始做复杂神经网络。先做候选核集合：

```text
K1: radius/sigma = 6/3
K2: radius/sigma = 8/4
K3: radius/sigma = 10/5
K4: radius/sigma = 12/6
```

每帧或每 bbox 根据训练侧 proxy 选择：

```text
if current density high and context conflict high:
    prefer narrower kernel
elif current density low and context is fresh/stable:
    prefer wider kernel
elif vertical mismatch high:
    reduce vertical spread or anisotropic kernel
else:
    default TimePower15 8/4
```

### 3.3 不泄漏的 gating 特征

可用：

```text
wind_records_total
fusion_current_wind_records
context_wind_records
context time_conf stats
role_conflict_voxels
role_conflict_component_gap_mean_mps
vertical_context_mismatch_candidate_voxels
vertical_oversmoothing_candidate_voxels
CMA temporal_conf_mean
CMA rapid_change_fraction
effective_reconstructed_fraction
low_conf_fill_fraction
```

不可用：

```text
holdout RMSE
holdout MAE
holdout point residual
anything computed from withheld labels
```

### 3.4 更强版本：per-voxel anisotropic kernel

按风向、飞行航迹方向和高度层调整：

```text
along-flow sigma > cross-flow sigma
same-altitude sigma_z small when vertical mismatch high
context older -> smaller context radius
```

这能直接针对 TimePower15 窄核/宽核之间的 tradeoff。

## 4. 方法三：Local OI / 3DVar Solver

### 4.1 为什么做

当前 Stage4 是 weighted localization + proxy refinement。文献中更标准的方式是背景场和观测场共同进入代价函数：

```text
J(x) =
  (x - xb)^T B^-1 (x - xb)
  + (H x - y)^T R^-1 (H x - y)
  + lambda_smooth * smoothness
  + lambda_div * horizontal_divergence
  + lambda_shear * vertical_shear_preserve_or_penalty
```

ECMWF 4D-Var 和 NCEP GSI/3DVAR 都采用 background + observations + covariance/constraints 的思想。这里不需要实现完整全球同化，只需要在每帧 bbox 内做小窗口版本。

参考：

```text
https://www.ecmwf.int/en/newsletter/175/earth-system-science/linearised-physics-heart-ecmwfs-4d-var
https://www.emc.ncep.noaa.gov/emc/pages/numerical_forecast_systems/ncep_data_assimilation.php
```

### 4.2 建议实现

新增模式：

```text
--physics-constraint-mode local_oi_proxy
--physics-constraint-mode local_3dvar_proxy
```

输入：

```text
y = non-holdout aircraft wind observations
R = calibrated aircraft observation error
xb = TimePower15 pre-refine field or CMA/GFS weak background
B = anisotropic/local covariance kernel
H = voxel sampling operator
```

求解：

```text
small bbox + sparse matrices + conjugate gradient
```

初版可以只在 effective bbox 上求解，不必全域 12,613,125 个体素。

### 4.3 保持项目规则

1. `xb` 可以来自 CMA/GFS/ERA/TimePower15，但只能作为 background。
2. `y` 只能用非 holdout aircraft wind。
3. 评估只看 holdout aircraft wind。
4. no-holdout 帧只输出诊断，不进官方 RMSE/MAE。

## 5. 方法四：LETKF / Ensemble Background Covariance

### 5.1 为什么做

单 CMA 背景会拉偏；多个背景组成 ensemble 可以估计 flow-dependent covariance。LETKF 是成熟的局地集合 Kalman filter 方法，适合稀疏观测和大状态空间。

参考：

```text
Hunt, Kostelich, Szunyogh 2007 LETKF:
https://experts.azregents.edu/en/publications/efficient-data-assimilation-for-spatiotemporal-chaos-a-local-ense/
```

### 5.2 项目内轻量实现

先不要接完整 LETKF 框架。先构造小 ensemble：

```text
member 1: TimePower15 8/4
member 2: aircraft baseline 12/6
member 3: CMA weak bg
member 4: GFS/GDAS bg, if available
member 5: ERA5/MERRA2 bg, if available
member 6+: parameter perturbations
```

在 bbox 内计算：

```text
ensemble_mean
ensemble_spread
background_error_covariance_proxy
```

然后用于 OI/3DVar 的 `B` 或用于 adaptive gating。

### 5.3 预期收益

1. 对极端坏帧提供更稳背景。
2. 对 CMA 拉偏场景降低单背景依赖。
3. 输出 uncertainty/spread，可用于风险分层。

## 6. 方法五：Dynamic CMA Gating

### 6.1 为什么做

200 帧结果：

```text
CMA vs TimePower15: 66 win / 134 loss
```

说明 CMA 不是全局开关，而是条件开关。

### 6.2 gating 规则初版

CMA 只在以下条件满足时增强：

```text
aircraft current support sparse
TimePower15 confidence low
CMA temporal_conf high
CMA rapid_change_fraction low
role_conflict_component_gap high but current density low
baseline/TP proxy diagnostics indicate low support or extreme fill
```

CMA 应减弱或关闭：

```text
current aircraft density high
TimePower15 confidence high
CMA rapid_change_fraction high
CMA temporal_change_speed_mean high
vertical mismatch high but CMA smooth field conflicts with aircraft
```

### 6.3 实现方式

新增：

```text
--cma-background-weight-mode fixed|diagnostic_gated
--cma-background-weight-min
--cma-background-weight-max
```

权重：

```text
w_cma = base_weight
        * cma_temporal_conf
        * (1 - cma_rapid_change_fraction)
        * low_aircraft_support_factor
        * low_tp_confidence_factor
```

继续输出 `cma_used_as_background_not_truth=True`。

## 7. 方法六：真实 Doppler Radar Wind Retrieval（有数据再做）

当前 radar PNG 只能作为云/回波强度 context，不能当风速观测。如果后续能拿到雷达径向速度，则可做 PyDDA / dual-Doppler / 3DVAR 风场反演。

参考：

```text
PyDDA:
https://openresearchsoftware.metajnl.com/articles/264
https://openradarscience.org/PyDDA/
```

注意：

```text
radar intensity PNG != radial velocity
radar reflectivity pattern != wind vector truth
```

## 8. 方法七：Residual PINN / FNO / DeepONet / Diffusion

### 8.1 正确定位

深度学习不应该直接替换 Stage4 主链路。推荐公式：

```text
F_residual = Model(
  TimePower15 u/v/conf/mask,
  aircraft density/support diagnostics,
  CMA/GFS/ERA background,
  radar/cloud context,
  vertical diagnostics,
  role conflict diagnostics
)

F_final = F_TimePower15 + F_residual
```

### 8.2 PINN

PINN 适合把弱物理约束写入 loss：

```text
aircraft holdout/train fitting loss
smoothness loss
weak divergence loss
background consistency loss
vertical shear preservation / non-oversmoothing loss
uncertainty calibration loss
```

参考：

```text
Raissi et al. 2019 PINN:
https://doi.org/10.1016/j.jcp.2018.10.045
```

### 8.3 FNO / DeepONet

FNO / DeepONet 适合学习格点场到格点场的残差算子。它们比普通 CNN 更适合连续场问题，但要注意 sparse truth 限制。

参考：

```text
FNO:
https://openreview.net/pdf?id=c8P9NQVtmnO

DeepONet:
https://pubmed.ncbi.nlm.nih.gov/34586842/
```

### 8.4 Diffusion / Ensemble Residual

Diffusion 更适合做概率集合、不确定性和长尾残差，而不是输出单一确定性真值。GenCast 说明 diffusion/ensemble forecast 可以表达不确定性。

参考：

```text
GenCast:
https://deepmind.google/research/publications/gencast-learning-skillful-ensemble-forecasting-of-medium-range-weather/
```

### 8.5 训练时必须避免的泄漏

1. holdout 点不能进入输入。
2. no-holdout 不能当 0 误差样本。
3. CMA/GFS/ERA 不能当 label。
4. 训练标签只能来自 aircraft wind holdout/train split 中允许作为 label 的 aircraft observations。
5. 模型输出必须报告 uncertainty，不能只报平均 RMSE。

## 9. 推荐实施顺序

### Phase 0：冻结评估协议

目标：避免后续优化时改坏评估口径。

必须保留：

```text
strict holdout only
stratified eval
no-holdout excluded
motion not wind
CMA not truth
```

输出继续写：

```text
stage4_localization_sensitivity.csv
stage4_localization_sensitivity_aggregate.csv
stratified_eval/
```

### Phase 1：Observation-error calibration

新增脚本：

```text
stage/centralized_v1/core/centralized_stage4_obs_error_calibration.py
```

新增模式：

```text
--confidence-mode obs_error_weighted
```

先做 200 帧 metrics-only：

```text
baseline
timepower15
timepower15_obs_error_weighted
```

成功标准：

```text
TimePower15 old vs obs_error_weighted win/loss improves
single_holdout_pressure_test not worse
high-error tail p95/p99 improves
no increase in leakage
```

### Phase 2：Adaptive localization

新增参数：

```text
--localization-policy fixed|diagnostic_adaptive
--localization-candidate-grid 6:3,8:4,10:5,12:6
```

先做 frame-level gating，不做 voxel-level。

成功标准：

```text
reduce the 56 TP-loss frames vs baseline
do not sacrifice high-error gains
improve baseline_rmse_le6 band where TP currently averages worse than baseline
```

当前 200 帧分层里，baseline low-error band：

```text
baseline_rmse_le6:
baseline RMSE 3.854
TimePower15 RMSE 4.249
CMA RMSE 5.495
```

这组是 adaptive localization 最重要的靶区。

2026-06-01 200-frame strict-holdout execution result:

```text
Baseline TimePower15 fixed 8/4:
  frame RMSE 8.636457
  frame MAE  7.423151
  weighted RMSE 15.038701
  weighted MAE   7.172653
  p95/p99 RMSE 28.147279 / 63.233730

Best fixed non-adaptive reference:
  fixed 10/5 frame RMSE 8.604561
  fixed 12/6 frame RMSE 8.615016

Diagnostic adaptive v2 + obs-error downweight:
  frame RMSE 8.540259
  frame MAE  7.427026
  weighted RMSE 15.034469
  weighted MAE   7.080333
  p95/p99 RMSE 28.856288 / 60.737784
  candidate wins/losses/ties vs TimePower15: 89 / 105 / 6
  selected kernels: 10/5 = 115 frames, 8/4 = 82 frames, 6/3 = 3 frames, 12/6 = 0 frames
  strict_holdout_no_leakage = True
  motion_used_as_wind = False
  adaptive_no_holdout_inputs_used = True
```

Band result:

```text
baseline_rmse_le6:  TimePower15 3.655491 -> adaptive v2 3.793112, delta +0.137621
baseline_rmse_6_10: TimePower15 7.602940 -> adaptive v2 7.562589, delta -0.040351
baseline_rmse_10_20: TimePower15 14.640140 -> adaptive v2 12.662909, delta -1.977230
baseline_rmse_gt20: TimePower15 38.670484 -> adaptive v2 38.270658, delta -0.399826
```

Recommendation after Phase 2:

```text
Adaptive v2 is the best deployable Phase 2 candidate so far and improves mean frame RMSE and weighted MAE,
but it still worsens the low-error band and p95 RMSE. Do not replace official TimePower15 8/4 yet.
Next step should be a lean v3 ablation, not a larger heuristic tree:
  1. use only 8/4 vs 10/5 selection,
  2. remove the rare 6/3 path,
  3. add a non-holdout low-error guard,
  4. compare with and without obs-error downweight.
```

### Phase 3：Local OI / 3DVar proxy

新增模式：

```text
--physics-constraint-mode local_oi_proxy
--physics-constraint-mode local_3dvar_proxy
```

先只在 6 个代表帧和 200 帧 metrics-only 上跑。

成功标准：

```text
frame mean RMSE improves
weighted MAE improves
high-error p95/p99 improves
vertical jump diagnostics do not collapse unrealistically
effective_reconstructed_fraction remains interpretable
```

### Phase 4：Dynamic CMA gating

新增：

```text
--cma-background-weight-mode diagnostic_gated
```

与 fixed CMA weak-background 对比：

```text
cma_fixed
cma_gated
timepower15_no_cma
```

成功标准：

```text
CMA vs TimePower15 win count increases
CMA degradation cases shrink
CMA still marked background_not_truth
```

### Phase 5：Residual model

只有 Phase 1-4 稳定后再做。先训练小模型，不要直接大 diffusion。

建议顺序：

```text
1. linear/GBDT residual baseline
2. small MLP/CNN residual on bbox features
3. PINN residual loss
4. FNO/DeepONet residual field
5. diffusion ensemble residual and uncertainty
```

## 10. 必须报告的指标模板

每次实验至少报告：

```text
frames
holdout_points
frame_mean_rmse_vector
frame_mean_mae_vector
holdout_point_weighted_rmse_vector
holdout_point_weighted_mae_vector
median_rmse
p90/p95/p99_rmse
max_rmse
single_holdout_pressure_test
multi_holdout_supported
baseline_rmse_le6
baseline_rmse_6_10
baseline_rmse_10_20
baseline_rmse_gt20
strong_wind_subset
vertical_mismatch_subset
method A vs method B win/loss/tie
top wins / top losses
strict_holdout_no_leakage
any_motion_used_as_wind
cma_used_as_background_not_truth
```

## 11. 代码入口清单

当前核心脚本：

```text
stage/centralized_v1/core/centralized_stage4_ground_recon.py
stage/centralized_v1/core/centralized_stage4_sensitivity.py
stage/centralized_v1/core/centralized_stage4_stratified_eval.py
stage/centralized_v1/core/centralized_stage4_compare_sensitivity.py
stage/centralized_v1/core/centralized_cma_ra_virtual_radial_3dvar.py
stage/centralized_v1/core/centralized_report_stage4_slices.py
stage/centralized_v1/core/centralized_report_cma_virtual_radial.py
```

新增建议：

```text
stage/centralized_v1/core/centralized_stage4_obs_error_calibration.py
stage/centralized_v1/core/centralized_stage4_adaptive_localization.py
stage/centralized_v1/core/centralized_stage4_local_oi.py
```

## 12. 不建议做的事

1. 不要把 CMA/CRA40/GFS/ERA 当真值。
2. 不要把 no-holdout 帧计入官方 RMSE/MAE。
3. 不要让模型读取 holdout labels 再做 gating。
4. 不要用 radar intensity PNG 冒充 Doppler wind。
5. 不要只优化全局均值而牺牲 single-holdout、强风层、vertical mismatch 长尾。
6. 不要把 500 m 网格点 RMSE 直接解释成 30 m 风切变阈值。
7. 不要一上来用大模型替代 TimePower15；先做 calibrated assimilation 和 residual correction。

## 13. 新窗口建议第一步

最小可执行任务：

```text
目标：实现 obs_error_weighted metrics-only 分支。

1. 新建 centralized_stage4_obs_error_calibration.py
2. 从 200 帧 / 全量 strict-holdout 可用帧中统计非 holdout aircraft observations 的局地一致性和 background departure
3. 输出 calibration JSON/MD
4. 在 centralized_stage4_ground_recon.py 和 centralized_stage4_sensitivity.py 增加 --confidence-mode obs_error_weighted
5. 跑 200 帧 metrics-only：
   - current TimePower15
   - obs_error_weighted TimePower15
6. 输出三张表：
   - aggregate
   - stratified
   - pairwise win/loss/top cases
```

最小成功标准：

```text
200-frame TimePower15 old vs obs_error_weighted:
mean RMSE/MAE not worse
p95/p99 RMSE improves
baseline_rmse_le6 band improves
strict_holdout_no_leakage remains True
```
