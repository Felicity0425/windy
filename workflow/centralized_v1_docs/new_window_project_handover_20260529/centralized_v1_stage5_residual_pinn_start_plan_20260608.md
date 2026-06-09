# Stage5 开端：Residual PINN 辅助风场重构原理、依据与执行顺序

## 0. 文档定位

本文是 `centralized_v1` 从 Stage4 进入 Stage5 的 PINN 路线起始文档。它不是代码实现记录，而是后续新建 `tp26_residual_pinn_*` 分支前必须遵守的方法定义、文献依据、数据边界、训练流程和正式 gate 顺序。

当前 Stage4 默认方法仍保持：

```text
tp26_thr11_preserve
```

Stage4 已完成的相关结论：

| branch | status | 结论 |
| --- | --- | --- |
| `tp26_thr11_preserve` | default | 200 帧 strict aircraft holdout weighted RMSE `14.769036`，仍有 21 个 `>=30 m/s` 长尾点。 |
| `representation_error_soft_weighted` | candidate pass | weighted RMSE `14.755381`，formal gate PASS，但提升很小，暂不升默认。 |
| `point_regime_localization_v1` | reject | weighted RMSE `15.075496`，P95/P99、12km+、light wind、floor10 全 FAIL，不升默认。 |
| `_pinn_diffusion_refine` / Stage5 demo | proxy only | 当前只是 smoothing/divergence/diffusion-style proxy，不是训练好的 PINN。 |

Stage5 的核心目标不是用神经网络替换 Stage4，而是在 `tp26_thr11_preserve` 稳定基线上训练一个受物理约束和不确定性约束的残差修正层：

```text
F_stage5 = F_tp26 + gated_residual_pinn_delta
```

## 1. 为什么 Stage5 可以考虑 PINN

PINN 的基本思想是：让神经网络同时满足观测数据和物理约束。普通监督学习只最小化预测值和 label 的误差，PINN 还会把 PDE residual、散度、平滑、边界条件、初始条件、守恒关系等写入 loss。

一般形式：

```text
network input:
  x, y, z, t, context features

network output:
  u, v, w, p, or residual delta_u/delta_v

data loss:
  L_obs = error(network prediction at observation points, observed wind)

physics loss:
  L_phys = PDE residual / divergence / smoothness / boundary / temporal consistency

total loss:
  L = w_obs * L_obs
    + w_phys * L_phys
    + w_bg * L_background
    + w_reg * L_regularization
```

在本项目中，aircraft wind 是稀疏点观测，Stage4 已经给出 500 m 体素网格、6 min 时间窗、confidence、tail-risk、support diagnostics 和 weak physics proxy。PINN 可用来学习：

```text
1. Stage4 系统性残差，而不是从零生成全场风。
2. sparse aircraft obs 与 dense grid 之间的可解释 correction。
3. uncertainty / no-claim gate，使模型知道哪里不能大胆修正。
4. weak divergence、edge-aware smoothness、vertical consistency 等物理先验。
```

## 2. 文献依据与本项目借用边界

| 文献/资料 | 链接 | 支持什么 | 本项目不能怎么宣称 |
| --- | --- | --- | --- |
| Raissi, Perdikaris and Karniadakis, 2019, Physics-informed neural networks | https://doi.org/10.1016/j.jcp.2018.10.045 | PINN 可把物理方程 residual 写入神经网络 loss，并用观测点约束连续场。 | 不能因为用了 smoothness/divergence proxy 就宣称已经训练了 PINN。必须有 trainable network、训练集、验证集和 physics loss。 |
| Karniadakis et al., 2021, Physics-informed machine learning | https://doi.org/10.1038/s42254-021-00314-5 | 物理约束机器学习适合数据不足、物理先验存在但不完整的问题。 | 不能把不完整物理方程当作绝对真值，尤其不能在高湍流大气边界层中强行闭合完整 Navier-Stokes。 |
| Krishnapriyan et al., 2021, PINN failure modes | https://papers.nips.cc/paper/2021/hash/df438e5206f31600e6ae4af72f2725f1-Abstract.html | PINN 在复杂 PDE、长时间域、多尺度和优化不平衡时会训练失败。 | 不能假设传统 PINN 直接套上就会比 Stage4 稳定。 |
| Wang, Yu and Perdikaris, 2022, When and why PINNs fail to train | https://doi.org/10.1016/j.jcp.2021.110768 | PINN 训练存在梯度病态、loss term 竞争、尺度不平衡问题，需要权重、归一化和训练策略。 | 不能用未经尺度化的 x/y/z/t/u/v 直接训练大网络后相信结果。 |
| Yan et al., 2024, wind flow field data assimilation with PINNs | https://doi.org/10.1016/j.apenergy.2024.123719 | 支持把 PINN 用于风场数据同化，把观测、背景和物理约束结合。 | 不能照搬为本项目全场 truth，因为我们的 aircraft 点观测、500 m 网格、6 min 窗口和北京低空业务场景不同。 |
| PyDDA, Pythonic Direct Data Assimilation | https://doi.org/10.5334/jors.264 | 3DVAR 风场反演把观测锚定、平滑、质量连续性等约束组合进目标函数。 | 本项目没有真实 Doppler radial velocity，不是真 PyDDA 雷达风反演，只能借用 variational loss 思路。 |
| Janjic et al., 2018, representation error in data assimilation | https://doi.org/10.1002/qj.3130 | representation error 包含尺度不匹配、观测算子、预处理/QC 等误差。aircraft 点观测 vs 500 m/6 min 体素正是此类问题。 | 不能把 aircraft observation error 与 representation error 混为一个固定 sigma。 |
| DART covariance localization / Gaspari-Cohn | https://docs.dart.ucar.edu/en/latest/assimilation_code/modules/assimilation/cov_cutoff_mod.html | 观测影响应随距离衰减，localization 是同化中的基本控制。 | 不能继续只做 frame-level 固定核后宣称 support-aware。Stage5 输入必须保留 point/regime support 诊断。 |
| Hunt, Kostelich and Szunyogh, 2007, LETKF | https://doi.org/10.1016/j.physd.2006.11.008 | 局地同化和 flow-dependent covariance 支持按目标附近观测、局地状态和不确定性调整影响。 | 不能把 LETKF 等同于 PINN；这里借用的是局地、flow-dependent、support-aware 的训练特征设计。 |
| Raissi et al., 2020, Hidden fluid mechanics | https://doi.org/10.1126/science.aaw4741 | 稀疏观测结合 Navier-Stokes 约束可反演部分流场状态。 | 该类问题通常需要更明确的 PDE、边界和状态变量；本项目不能直接用完整 Navier-Stokes PINN 解北京 3D 风场。 |

## 3. 为什么不能用传统全场 PINN 直接解决

传统 PINN 通常假设：

```text
1. PDE 已知且适用于目标尺度。
2. 初始条件和边界条件可用。
3. 关键状态变量可观测或可被 PDE 约束住。
4. 观测算子和观测误差相对明确。
5. 训练域的尺度、边界和时间跨度可被网络稳定优化。
```

本项目同时违反多个前提。

### 3.1 只有 sparse aircraft u/v，没有完整状态

当前 strict truth 是 aircraft `wind_records` 的 `u_wind/v_wind`。没有密集的：

```text
w vertical wind
pressure
temperature
density
turbulent closure parameters
true boundary condition
true initial condition
```

如果直接训练 `PINN(x,y,z,t) -> u,v,w,p` 并约束完整 Navier-Stokes，网络会在缺失变量和边界上自由漂移。它可能得到一个 PDE residual 很小但 aircraft holdout 很差的场。

### 3.2 500 m 网格与 6 min 窗口不是点真值

aircraft 是沿航迹的点观测，Stage4 输出是 500 m 体素和 6 min 窗口的重构场。两者之间存在 representation error：

```text
point support != grid-cell support
instantaneous sample != window aggregate
aircraft altitude/time mismatch != voxel center
QC/preprocessing/operator error != pure sensor error
```

传统 PINN 如果把 aircraft 点值直接当作体素真值，会把 representation error 学成错误的物理修正。

### 3.3 大气边界层高 Reynolds 数，完整 Navier-Stokes 不闭合

北京低空风场包含建筑、地形、对流、低空急流、边界层湍流和时空非平稳性。500 m / 6 min 尺度下，完整 Navier-Stokes 需要亚格点闭合和边界 forcing。没有这些条件时，强 PDE loss 会过度平滑并抹掉局地强垂直结构。

这正对应 Stage4 已看到的问题：

```text
long tail still dominates official RMSE
guarded vertical dynamic v2 worsened P95/P99
point-regime localization v1 worsened weighted RMSE
soft representation weight only tiny improvement
```

### 3.4 PINN 本身训练不稳定

PINN loss 通常由多个项组成：

```text
observation fit
PDE residual
boundary condition
smoothness
background consistency
uncertainty calibration
```

这些项的尺度不同，梯度也不同。文献已指出 PINN 容易出现 loss 竞争、梯度病态和多尺度优化失败。对本项目来说，如果直接上全场 PINN，常见坏结果是：

```text
1. 训练 loss 下降，但 holdout RMSE 上升。
2. 平均 RMSE 小幅改善，但 P95/P99 长尾变差。
3. 低风速 relative error 变坏。
4. 高空/远支撑区域出现虚假强风。
5. no-claim 区域被模型硬填成看似连续但不可验证的风场。
```

### 3.5 formal gate 不允许数据泄漏

Stage5 必须继续遵守 Stage4 验证边界：

```text
strict holdout truth 只能来自 current aircraft wind_records。
motion_records / context_motion_records 不能当 wind。
CMA/GFS/ERA 只能当 weak background/prior，不能当 truth。
display-filled 只做可视化，不进入 official RMSE。
validation/test frame 的 aircraft label 不能进入训练输入。
```

传统 PINN 常用所有观测点一起训练一个连续场。如果把 200-frame formal holdout 点放进训练，就会直接破坏当前项目最重要的可信度。

## 4. Stage5 正确路线：Residual PINN，不是 Full-Field PINN

推荐 Stage5 第一条正式路线：

```text
tp26_residual_pinn_report_v1
```

它先做 report-only cross-frame 验证，不接入默认输出。通过后再做：

```text
tp26_residual_pinn_field_v1
```

核心公式：

```text
u_final = u_tp26 + gate * clip(delta_u_pinn, -cap, cap)
v_final = v_tp26 + gate * clip(delta_v_pinn, -cap, cap)
```

其中：

```text
u_tp26, v_tp26:
  Stage4 tp26_thr11_preserve 输出，是主链路锚点。

delta_u_pinn, delta_v_pinn:
  PINN 学到的残差修正，不允许单独替代主场。

gate:
  基于 confidence、tail-risk、sigma_rep、support、role_gap、vertical_gap 的安全门控。

cap:
  最大残差幅度，初始建议 3-5 m/s。长尾区域不直接大胆修，而是提高 uncertainty/no-claim。
```

这样做的原因：

```text
1. Stage4 已有稳定 baseline，残差学习比从零学全场更稳。
2. aircraft label 稀疏，训练 delta 比训练 absolute u/v 更容易。
3. gate 和 cap 能避免 PINN 在低支撑区域制造新长尾。
4. physics loss 只作为弱约束，不强迫不完整 Navier-Stokes。
5. 可以用同一套 200-frame formal gate 判断是否真的提升。
```

## 5. Stage5 PINN 输入、输出和标签设计

### 5.1 输入特征

每个训练样本至少包含：

```text
x_norm, y_norm, z_norm, t_norm
altitude_m_norm
u_tp26, v_tp26, speed_tp26
recon_confidence
reliability_confidence
tail_risk_score
no_claim_flag
sigma_rep
tail_probability
nearest_current_distance_vox
nearest_current_count
nearest_context_count
context_time_confidence
role_gap_mps
vertical_gap_mps
vertical_jump_mps
support_regime_id
truth_speed_bin or baseline_speed_bin for stratified weighting
```

可选输入：

```text
CMA/GFS/ERA u/v weak background
background_time_lag_hours
background_altitude_gap_m
radar/cloud intensity context
terrain/building proxy if available
```

注意：

```text
CMA/GFS/ERA 是 weak background，不是 label。
radar PNG intensity 不是 wind speed，也不是 Doppler velocity。
motion u/v 不是 wind，不能进入 wind label。
```

### 5.2 输出

第一版输出：

```text
delta_u
delta_v
log_sigma_u
log_sigma_v
```

其中 uncertainty 输出用于：

```text
1. gate residual correction。
2. no-claim/reliability 产品解释。
3. NLL 或 calibration loss。
4. formal gate 后的风险分层。
```

### 5.3 训练标签

训练标签来自 training split 中允许使用的 aircraft wind observations：

```text
target_delta_u = observed_u - u_tp26_at_observation
target_delta_v = observed_v - v_tp26_at_observation
```

validation/test split 的 aircraft observations 只能评估，不能训练。

正式 200-frame gate 仍沿用 Stage4 当前规则：

```text
holdout 点在 reconstruction 前移除。
candidate 输出在 holdout voxel 上采样。
只用 current aircraft wind_records 计算 official RMSE/MAE。
```

## 6. Loss 设计

### 6.1 Observation residual loss

基础监督项：

```text
pred_u = u_tp26 + gate * delta_u
pred_v = v_tp26 + gate * delta_v

L_obs = Huber(pred_u - observed_u)
      + Huber(pred_v - observed_v)
```

建议使用 Huber 而不是纯 MSE：

```text
1. 长尾点很少但幅度极大，MSE 容易让模型为少数极端点牺牲主体样本。
2. Huber 对中小误差像 MSE，对极端误差像 MAE，训练更稳。
```

### 6.2 Representation-aware weighting

每个样本权重：

```text
w_obs = 1 / (sigma_obs^2 + sigma_rep^2 + sigma_model^2 + epsilon)
```

其中：

```text
sigma_obs:
  aircraft wind observation error proxy。

sigma_rep:
  点观测到 500 m / 6 min 体素的 representation error。

sigma_model:
  PINN 输出的不确定性或 calibration residual。
```

原则：

```text
不是删除高 sigma 样本，而是 soft weighting。
tail-risk 高时，优先降低 gate、提高 uncertainty，不直接强修。
```

### 6.3 Uncertainty calibration loss

如果输出 `log_sigma_u/log_sigma_v`，使用高斯 NLL 或 clipped NLL：

```text
L_unc =
  0.5 * ((error_u / sigma_u)^2 + log(sigma_u^2))
  + 0.5 * ((error_v / sigma_v)^2 + log(sigma_v^2))
```

目标：

```text
1. 模型在不可靠区域承认 uncertainty 高。
2. 不让模型靠无限增大 sigma 逃避误差。
3. 后续 no-claim/reliability 有可训练依据。
```

### 6.4 Weak physics loss

第一阶段不要上完整 Navier-Stokes。建议从弱物理开始：

```text
L_div = mean((d pred_u / dx + d pred_v / dy)^2)

L_smooth = edge_aware_mean(
  |grad pred_u|^2 + |grad pred_v|^2,
  lower weight where vertical shear or strong-layer proxy is high
)

L_vertical = preserve strong observed/background vertical gradients,
  not blindly minimize all vertical gradients

L_temporal = consistency with nearby time context where current support is strong
```

这与 Stage4 经验一致：不能一味平滑垂直结构，否则会伤害强垂直层和高空 long-tail。

### 6.5 Weak background loss

如果使用 CMA/GFS/ERA：

```text
L_bg = background_weight * mask_bg * ||pred_u/v - background_u/v||^2
```

权重必须小，并且按背景时间差、空间差、支撑诊断衰减：

```text
background_weight <= observation_weight
far time lag -> lower weight
large aircraft-background mismatch -> lower weight
tail-risk high -> background can inform uncertainty, not force correction
```

### 6.6 Correction magnitude and gate regularization

必须限制残差：

```text
L_delta = mean(confidence_weight * (delta_u^2 + delta_v^2))
```

并且 gate 初始规则保守：

```text
gate = 0 if no current support and tail-risk high
gate small if sigma_rep high
gate small if role_gap high
gate small if vertical_gap high
gate small if predicted_sigma high
gate normal only where support strong and uncertainty low
```

## 7. 两个版本定义

### 7.1 `tp26_residual_pinn_report_v1`

目的：

```text
用现有 Stage4 point_departures 和 diagnostics 做 frame-level cross-fit。
先证明 residual PINN 是否有统计收益。
不写回 3D full field。
不进入默认 reconstruction。
```

特点：

```text
输入：point-level features。
输出：point-level delta_u/delta_v/sigma。
physics：只能做 weak feature regularization 或局部近似，不能宣称 full PDE PINN。
评估：frame split 或 time-block split，validation/test frame 不进训练。
```

它回答的问题：

```text
在不接入 full 3D 场前，残差神经网络是否能降低 holdout point error？
哪些 regime 有收益，哪些 regime 有风险？
uncertainty/gate 是否能减少 P95/P99 新失败？
```

### 7.2 `tp26_residual_pinn_field_v1`

目的：

```text
在 3D field collocation 上真正训练 physics-informed residual field。
把 residual correction 写回 Stage4/Stage5 full NPZ。
接受 2-frame smoke 和 200-frame formal gate。
```

特点：

```text
输入：3D grid collocation points + point observations。
输出：3D delta_u/delta_v/sigma field。
physics：用 finite difference 或 autograd 计算 field residual。
评估：严格复用 Stage4 formal gate。
```

它才可以称为本项目真正的 PINN-assisted wind reconstruction。

## 8. 数据切分和防泄漏规则

Stage5 必须采用 time/frame split，而不是随机 point split。

推荐：

```text
train frames: 70%
validation frames: 15%
test frames: 15%
formal gate frames: 固定 200-frame list，最后才跑
```

原因：

```text
同一 frame 内点之间高度相关。
随机 point split 会让同一时刻/同一区域的支撑信息泄漏到验证点。
```

硬规则：

```text
1. formal holdout aircraft point 不得进入 Stage4 reconstruction input。
2. validation/test frame 的 aircraft label 不得进入 PINN train loss。
3. no-holdout frame 不能当作 0 error 样本。
4. CMA/GFS/ERA 不能当 official truth。
5. display-filled voxel 不能进入 official point RMSE。
6. motion/location u/v 不能当 aircraft wind label。
7. point_departures 中的 holdout error 可以用于离线 report，但不能反向污染 formal candidate。
```

## 9. 建议新增代码文件

第一批新增文件建议：

```text
stage/centralized_v1/core/centralized_stage5_residual_pinn_dataset.py
stage/centralized_v1/core/centralized_stage5_residual_pinn_train.py
stage/centralized_v1/core/centralized_stage5_residual_pinn_apply.py
stage/centralized_v1/core/centralized_stage5_residual_pinn_compare.py
```

职责：

| file | responsibility |
| --- | --- |
| `centralized_stage5_residual_pinn_dataset.py` | 从 Stage4 point departures、Stage4 NPZ、Stage2/Stage3 summaries、support diagnostics、representation diagnostics 构建训练 parquet/csv/npz。 |
| `centralized_stage5_residual_pinn_train.py` | 用 PyTorch 训练 residual network，保存 checkpoint、normalizer、feature schema、loss curve 和 split metrics。 |
| `centralized_stage5_residual_pinn_apply.py` | 在 Stage4 candidate output 上加载 checkpoint，生成 gated residual field 或 point-level report。 |
| `centralized_stage5_residual_pinn_compare.py` | 对 baseline vs candidate 跑 formal guardrail、stratified eval、tail-risk eval、error-source report。 |

现有文件关系：

```text
stage/centralized_v1/core/centralized_training_manifest.py
  已经是 PINN/proxy/diffusion 的 manifest scaffold，可作为 Stage5 split 起点。

stage/centralized_v1/core/centralized_stage5_wind_cloud.py
  只是 demo/proxy，不是训练好的 PINN。后续应保留其 demo 定位，不把它作为 formal candidate。

stage/centralized_v1/core/centralized_stage4_ground_recon.py
  当前有 _pinn_diffusion_refine，但注释已说明它不是 trained PINN。
```

## 10. 模型结构建议

第一版不要做大模型。建议用小型 MLP/SIREN-style neural field 或 Fourier-feature MLP：

```text
input_dim:
  20-40 engineered features

hidden:
  4-6 layers
  128-256 width
  SiLU/Tanh activation
  optional Fourier features for x/y/z/t

output:
  delta_u, delta_v, log_sigma_u, log_sigma_v
```

残差输出约束：

```text
delta = cap * tanh(raw_delta / cap)
cap initial = 3.0 or 5.0 m/s
```

归一化：

```text
x/y/z/t normalized to [-1, 1]
u/v/speed standardized by training split only
distance/count/log features clipped then standardized
tail-risk/sigma/gate features kept in [0, 1] or log scale
```

训练策略：

```text
optimizer: AdamW
initial lr: 1e-3
scheduler: cosine or plateau
batching: point batches for report_v1, mixed point+collocation batches for field_v1
early stopping: validation weighted RMSE/P95, not just train loss
random seed: fixed and logged
```

## 11. 运行顺序

### Step 0: 确认环境和依赖

```bash
/data/LFT-W02_data/pengxu/.conda/envs/windy310/bin/python - <<'PY'
import sys
print(sys.version)
try:
    import torch
    print("torch", torch.__version__)
except Exception as exc:
    print("torch_missing", exc)
PY
```

如果 `torch` 不存在，先不要改算法逻辑。应单独记录依赖缺口，再决定是否安装 PyTorch。

### Step 1: 生成 Stage5 manifest

使用现有 manifest 脚本先生成 split 和 weak-background availability：

```bash
/data/LFT-W02_data/pengxu/.conda/envs/windy310/bin/python \
  stage/centralized_v1/core/centralized_training_manifest.py \
  --stage2-summary centralized_v1_output/stage2_full_v2/stage2_multimodal_summary.json \
  --stage4-csv centralized_v1_output/stage4_guardrail_display_fill_200_20260605_25w/tp26_thr11_preserve_metrics/stage4_localization_sensitivity.csv \
  --out-dir centralized_v1_output/stage5_residual_pinn_manifest_20260608 \
  --require-stage4-metrics
```

输出应包含：

```text
centralized_v1_output/stage5_residual_pinn_manifest_20260608/centralized_training_manifest.json
centralized_v1_output/stage5_residual_pinn_manifest_20260608/centralized_training_manifest.md
```

### Step 2: 构建 point-level report dataset

计划新增命令：

```bash
/data/LFT-W02_data/pengxu/.conda/envs/windy310/bin/python \
  stage/centralized_v1/core/centralized_stage5_residual_pinn_dataset.py \
  --point-departures centralized_v1_output/stage4_guardrail_display_fill_200_20260605_25w/tp26_thr11_preserve_metrics/stage4_point_departures.csv \
  --manifest centralized_v1_output/stage5_residual_pinn_manifest_20260608/centralized_training_manifest.json \
  --out-dir centralized_v1_output/stage5_residual_pinn_report_v1_20260608/dataset \
  --mode point_report
```

输出：

```text
features_train.npz
features_val.npz
features_test.npz
feature_schema.json
dataset_summary.md
```

最小字段检查：

```text
time_str
x/y/z or voxel indices
u_tp26/v_tp26
observed_u/observed_v
target_delta_u/target_delta_v
recon_confidence
tail_risk_score
sigma_rep or representation proxy
support diagnostics
split
```

### Step 3: 训练 `tp26_residual_pinn_report_v1`

计划新增命令：

```bash
/data/LFT-W02_data/pengxu/.conda/envs/windy310/bin/python \
  stage/centralized_v1/core/centralized_stage5_residual_pinn_train.py \
  --dataset-dir centralized_v1_output/stage5_residual_pinn_report_v1_20260608/dataset \
  --out-dir centralized_v1_output/stage5_residual_pinn_report_v1_20260608/train \
  --model residual_mlp_v1 \
  --max-epochs 500 \
  --early-stop-metric val_weighted_rmse \
  --delta-cap-mps 3.0 \
  --loss-mode representation_weighted_huber_uncertainty \
  --seed 20260608
```

输出：

```text
checkpoint.pt
normalizer.json
feature_schema.json
train_history.csv
train_metrics.json
train_report.md
```

必须报告：

```text
train weighted RMSE/MAE
val weighted RMSE/MAE/P95/P99
test weighted RMSE/MAE/P95/P99
tail >=30 count
light wind 5-15 m/s RMSE/MAE
floor10_relative_error_mae
calibration curve or sigma bucket table
```

### Step 4: point-level candidate 对比

计划新增命令：

```bash
/data/LFT-W02_data/pengxu/.conda/envs/windy310/bin/python \
  stage/centralized_v1/core/centralized_stage5_residual_pinn_compare.py \
  --baseline-point-departures centralized_v1_output/stage4_guardrail_display_fill_200_20260605_25w/tp26_thr11_preserve_metrics/stage4_point_departures.csv \
  --candidate-point-predictions centralized_v1_output/stage5_residual_pinn_report_v1_20260608/train/test_predictions.csv \
  --out-dir centralized_v1_output/stage5_residual_pinn_report_v1_20260608/analysis \
  --formal-guardrail
```

通过条件：

```text
weighted RMSE 不劣化
P95 不劣化
P99 不劣化
12km+ RMSE 不劣化
light wind RMSE/MAE 不劣化
floor10_relative_error_mae 不劣化
relative_error_ratio > 2 and delta_vector_error > 5 m/s 的新失败为 0
```

如果 point-level report 都无法通过，不进入 field_v1。

### Step 5: 生成 field-collocation dataset

只有 Step 4 通过后才做。

计划新增命令：

```bash
/data/LFT-W02_data/pengxu/.conda/envs/windy310/bin/python \
  stage/centralized_v1/core/centralized_stage5_residual_pinn_dataset.py \
  --stage2-summary centralized_v1_output/stage2_full_v2/stage2_multimodal_summary.json \
  --stage3-summary centralized_v1_output/stage3_full_v2_25w_payload_only/stage3_center_summary.json \
  --stage4-csv centralized_v1_output/stage4_guardrail_display_fill_200_20260605_25w/tp26_thr11_preserve_metrics/stage4_localization_sensitivity.csv \
  --manifest centralized_v1_output/stage5_residual_pinn_manifest_20260608/centralized_training_manifest.json \
  --out-dir centralized_v1_output/stage5_residual_pinn_field_v1_20260608/dataset \
  --mode field_collocation \
  --collocation-per-frame 20000 \
  --include-current-aircraft-train-only \
  --include-weak-background
```

输出：

```text
field_train_shards/
field_val_shards/
field_test_shards/
point_obs_train.npz
point_obs_val.npz
point_obs_test.npz
collocation_schema.json
field_dataset_summary.md
```

### Step 6: 训练 `tp26_residual_pinn_field_v1`

计划新增命令：

```bash
/data/LFT-W02_data/pengxu/.conda/envs/windy310/bin/python \
  stage/centralized_v1/core/centralized_stage5_residual_pinn_train.py \
  --dataset-dir centralized_v1_output/stage5_residual_pinn_field_v1_20260608/dataset \
  --out-dir centralized_v1_output/stage5_residual_pinn_field_v1_20260608/train \
  --model residual_fourier_mlp_v1 \
  --mode field_collocation \
  --max-epochs 300 \
  --delta-cap-mps 3.0 \
  --loss-mode obs_plus_weak_physics_plus_uncertainty \
  --obs-loss-weight 1.0 \
  --div-loss-weight 0.02 \
  --smooth-loss-weight 0.02 \
  --background-loss-weight 0.05 \
  --delta-reg-weight 0.10 \
  --seed 20260608
```

训练 batch 应混合：

```text
aircraft observation points
3D collocation voxels
boundary/background voxels
high-risk regime samples
light wind regime samples
12km+ samples
```

### Step 7: 两帧 smoke

计划新增命令：

```bash
/data/LFT-W02_data/pengxu/.conda/envs/windy310/bin/python \
  stage/centralized_v1/core/centralized_stage5_residual_pinn_apply.py \
  --stage2-summary centralized_v1_output/stage2_full_v2/stage2_multimodal_summary.json \
  --stage3-summary centralized_v1_output/stage3_full_v2_25w_payload_only/stage3_center_summary.json \
  --checkpoint centralized_v1_output/stage5_residual_pinn_field_v1_20260608/train/checkpoint.pt \
  --out-dir centralized_v1_output/stage5_residual_pinn_field_v1_smoke_20260608 \
  --frame-times 20260205190000,20260206074200 \
  --base-stage4-mode tp26_thr11_preserve \
  --candidate-name tp26_residual_pinn_field_v1
```

smoke 必查：

```text
strict_holdout_no_leakage == True
motion_used_as_wind == False
uses_holdout_truth_in_recon == False
delta_u/v max <= cap
no_claim/gate diagnostics present
sigma outputs finite
NPZ contract includes base and candidate fields
```

### Step 8: 200-frame formal gate

只有 smoke 通过后跑。

计划新增命令：

```bash
/data/LFT-W02_data/pengxu/.conda/envs/windy310/bin/python \
  stage/centralized_v1/core/centralized_stage5_residual_pinn_apply.py \
  --stage2-summary centralized_v1_output/stage2_full_v2/stage2_multimodal_summary.json \
  --stage3-summary centralized_v1_output/stage3_full_v2_25w_payload_only/stage3_center_summary.json \
  --checkpoint centralized_v1_output/stage5_residual_pinn_field_v1_20260608/train/checkpoint.pt \
  --out-dir centralized_v1_output/stage5_residual_pinn_field_v1_200_20260608/tp26_residual_pinn_field_v1_metrics \
  --frame-times-file centralized_v1_output/stage4_guardrail_display_fill_200_20260605_25w/tp26_thr11_preserve_metrics/stage4_validation_frame_times.txt \
  --base-stage4-mode tp26_thr11_preserve \
  --candidate-name tp26_residual_pinn_field_v1 \
  --num-workers 25
```

之后复用 pairwise/error-source：

```bash
/data/LFT-W02_data/pengxu/.conda/envs/windy310/bin/python \
  stage/centralized_v1/core/centralized_stage4_pairwise_frame_compare.py \
  --baseline-csv centralized_v1_output/stage4_guardrail_display_fill_200_20260605_25w/tp26_thr11_preserve_metrics/stage4_localization_sensitivity.csv \
  --candidate-csv centralized_v1_output/stage5_residual_pinn_field_v1_200_20260608/tp26_residual_pinn_field_v1_metrics/stage4_localization_sensitivity.csv \
  --baseline-point-csv centralized_v1_output/stage4_guardrail_display_fill_200_20260605_25w/tp26_thr11_preserve_metrics/stage4_point_departures.csv \
  --candidate-point-csv centralized_v1_output/stage5_residual_pinn_field_v1_200_20260608/tp26_residual_pinn_field_v1_metrics/stage4_point_departures.csv \
  --baseline-label tp26_thr11_preserve \
  --candidate-label tp26_residual_pinn_field_v1 \
  --out-dir centralized_v1_output/stage5_residual_pinn_field_v1_200_20260608/analysis/tp26_vs_residual_pinn_field_v1_formal_guardrail \
  --out-prefix tp26_vs_residual_pinn_field_v1
```

```bash
/data/LFT-W02_data/pengxu/.conda/envs/windy310/bin/python \
  stage/centralized_v1/core/centralized_stage4_error_source_decomposition.py \
  --baseline-csv centralized_v1_output/stage4_guardrail_display_fill_200_20260605_25w/tp26_thr11_preserve_metrics/stage4_localization_sensitivity.csv \
  --candidate-csv centralized_v1_output/stage5_residual_pinn_field_v1_200_20260608/tp26_residual_pinn_field_v1_metrics/stage4_localization_sensitivity.csv \
  --baseline-point-csv centralized_v1_output/stage4_guardrail_display_fill_200_20260605_25w/tp26_thr11_preserve_metrics/stage4_point_departures.csv \
  --candidate-point-csv centralized_v1_output/stage5_residual_pinn_field_v1_200_20260608/tp26_residual_pinn_field_v1_metrics/stage4_point_departures.csv \
  --baseline-label tp26_thr11_preserve \
  --candidate-label tp26_residual_pinn_field_v1 \
  --out-dir centralized_v1_output/stage5_residual_pinn_field_v1_200_20260608/analysis/tp26_vs_residual_pinn_field_v1_error_source \
  --out-prefix tp26_vs_residual_pinn_field_v1
```

## 12. Promotion 标准

不能只看 overall RMSE。必须同时通过：

| metric | gate |
| --- | --- |
| strict no leakage | 必须为 True |
| motion used as wind | 必须为 False |
| weighted RMSE | 不劣化，最好下降 |
| weighted MAE | 不劣化 |
| frame P95 | 不劣化 |
| frame P99 | 不劣化 |
| 12km+ RMSE | 不劣化 |
| 5-15 m/s light wind RMSE/MAE | 不劣化 |
| floor10_relative_error_mae | 不劣化 |
| new light/moderate catastrophic failures | 必须为 0 |
| high-error >=30 m/s count | 不能增加，最好下降 |
| uncertainty calibration | 高 sigma bucket 应对应更高实际误差 |
| no-claim/reliability | 只能解释可信度，不能删除 official holdout |

如果 Stage5 PINN 只降低平均 RMSE 但加重 P95/P99 或 light wind relative error，应判为 FAIL。

## 13. 预期结果与风险

### 13.1 合理预期

第一版 residual PINN 不应承诺大幅修复所有长尾。合理目标：

```text
weighted RMSE 下降 0.1-0.5 m/s
P95/P99 不劣化
light wind 不劣化
tail-risk/no-claim calibration 更清晰
部分 support-strong regime 有稳定提升
```

### 13.2 主要风险

| risk | 表现 | 处理 |
| --- | --- | --- |
| label 太稀疏 | train loss 好，test 不稳 | 用 frame/time split、small model、delta cap、early stopping。 |
| representation error 被学成风场误差 | 高 sigma 区域乱修 | representation-aware weight + gate + uncertainty。 |
| physics loss 过强 | 垂直结构被抹平，P95/P99 变坏 | weak physics、edge-aware smoothing、vertical preservation。 |
| background 过强 | CMA/GFS bias 进入 candidate | background small weight，永不当 truth。 |
| 数据泄漏 | formal 指标虚高 | split manifest、holdout exclusion、run audit。 |
| no-claim 被误用 | 通过删点提升 RMSE | official holdout 点不能删除，只能报告 confidence。 |

## 14. 最小可交付清单

Stage5 第一轮真正完成时，应至少产生：

```text
workflow/centralized_v1_docs/new_window_project_handover_20260529/
  centralized_v1_stage5_residual_pinn_start_plan_20260608.md

stage/centralized_v1/core/
  centralized_stage5_residual_pinn_dataset.py
  centralized_stage5_residual_pinn_train.py
  centralized_stage5_residual_pinn_apply.py
  centralized_stage5_residual_pinn_compare.py

centralized_v1_output/stage5_residual_pinn_report_v1_YYYYMMDD/
  dataset/
  train/
  analysis/

centralized_v1_output/stage5_residual_pinn_field_v1_YYYYMMDD/
  dataset/
  train/
  smoke/
  200-frame formal gate/
  analysis/
```

## 15. 一句话口径

Stage5 PINN 的正确说法：

```text
We use a residual, uncertainty-gated, physics-informed neural correction on top of the strict Stage4 aircraft-based reconstruction. The PINN is not used as truth and does not replace aircraft holdout validation. Weak physics and background fields regularize the residual, while formal accuracy is still judged only by current aircraft wind_records strict holdout.
```

中文口径：

```text
Stage5 不是用 PINN 直接生成真风场，而是在 tp26_thr11_preserve 的稳定风场上训练一个带不确定性门控的物理信息残差修正层。飞机风观测仍是唯一正式验证 truth，CMA/GFS/ERA 只做弱背景，representation error 和 support diagnostics 决定样本权重与修正强度。
```

## 16. 下一步执行建议

立即下一步：

```text
1. 检查 windy310 环境是否有 PyTorch。
2. 用 centralized_training_manifest.py 生成 Stage5 split manifest。
3. 新建 point-level residual PINN dataset/train/report 三个脚本。
4. 先跑 tp26_residual_pinn_report_v1，不接 full field。
5. 若 report_v1 通过，再做 field-collocation PINN。
6. 最后才跑 2-frame smoke 和 200-frame formal gate。
```

硬边界：

```text
report_v1 未通过，不进入 field_v1。
smoke 未通过，不跑 200-frame formal gate。
formal gate 未通过，不升默认。
```

## 17. 2026-06-08 report_v1 实施记录

本轮已把 Stage5 Residual PINN 的第一阶段从方案落到可执行脚本和 point-level report 实验。重要边界保持不变：

```text
Stage5 PINN 是 tp26 后处理残差层，不替换 tp26_thr11_preserve。
候选形式仍是 F_stage5 = F_tp26 + gate * clipped_delta。
report_v1 只在 point-level departures 上验证统计收益，不写回 3D field。
official truth 仍只来自 current aircraft wind_records strict holdout。
```

### 17.1 新增代码

新增文件：

```text
stage/centralized_v1/core/centralized_stage5_residual_pinn_dataset.py
stage/centralized_v1/core/centralized_stage5_residual_pinn_train.py
stage/centralized_v1/core/centralized_stage5_residual_pinn_apply.py
stage/centralized_v1/core/centralized_stage5_residual_pinn_compare.py
```

静态检查：

```text
python -m py_compile:
  centralized_stage5_residual_pinn_dataset.py
  centralized_stage5_residual_pinn_train.py
  centralized_stage5_residual_pinn_apply.py
  centralized_stage5_residual_pinn_compare.py

结果：通过
```

`centralized_stage5_residual_pinn_train.py` 已支持：

```text
--device auto|cpu|cuda
--allow-tf32
```

本次环境检查：

```text
torch = 2.6.0+cu124
torch.cuda.is_available() = False
resolved device = cpu
```

因此本轮训练没有调用显卡。后续如果运行环境能看到 CUDA，默认 `--device auto` 会使用 `cuda:0`；如需强制显卡，可用 `--device cuda --allow-tf32`。如果 CUDA 不可见而强制 `--device cuda`，脚本会直接报错，避免误以为已经用 GPU。

### 17.2 输出路径

manifest：

```text
centralized_v1_output/stage5_residual_pinn_manifest_20260608/
  centralized_training_manifest.json
  centralized_training_manifest.md
```

report_v1：

```text
centralized_v1_output/stage5_residual_pinn_report_v1_20260608/
  dataset/
  train/
  train_cap1/
  analysis_cap3/
  analysis_cap1/
  apply_cap1/
```

### 17.3 数据集情况

输入：

```text
centralized_v1_output/stage4_guardrail_display_fill_200_20260605_25w/tp26_thr11_preserve_metrics/stage4_point_departures.csv
```

数据集：

| split | frames | points | baseline RMSE | baseline MAE | >=30mps tail |
| --- | ---: | ---: | ---: | ---: | ---: |
| `train` | 140 | 381 | 13.725408 | 7.078873 | 16 |
| `val` | 30 | 86 | 8.617390 | 5.458972 | 3 |
| `test` | 30 | 63 | 24.379358 | 7.402198 | 2 |

解释：

```text
split 是 frame/time split，不是随机 point split。
同一 frame 内的点不会同时进入 train 和 val/test。
test split 本身更难，baseline RMSE 24.379358，适合检验残差模型是否会在困难时段乱修。
```

feature policy：

```text
truth-free feature count = 64
gt_u / gt_v / gt_speed / vector_error / u_error / v_error 不作为模型输入。
qc_review_flag / qc_review_reasons 不作为模型输入。
point_neighbor_*_vector_error 和 representativeness_gap_point_minus_min_mps 不作为模型输入。
motion_records / context_motion_records 不作为 wind label。
```

### 17.4 模型原理

本轮 `report_v1` 不是 full-field PINN，而是残差神经网络的第一步统计验证：

```text
输入：tp26 point prediction + support/role/vertical/confidence/reliability proxy features
标签：target_delta_u = gt_u - pred_u, target_delta_v = gt_v - pred_v
输出：delta_u, delta_v, sigma_u, sigma_v
候选：candidate = tp26 + residual_gate * clipped_delta
```

训练约束：

```text
small residual MLP
Huber residual loss
representation-aware sample weight
uncertainty output
delta cap = 3.0m/s 或 1.0m/s
truth-free residual_gate_initial
```

这回答的是：

```text
在不写回 3D 场之前，残差网络是否能在 frame split 的 held-out points 上稳定改善 tp26？
```

它还不能称为真正的 `field_v1` PINN，因为没有在 3D collocation field 上计算 divergence/smoothness physics loss，也没有生成 Stage5 full NPZ。

### 17.5 训练与对比结果

`delta_cap_mps=3.0`：

| split | points | baseline RMSE | candidate RMSE | delta RMSE | P95 base/cand | P99 base/cand | light RMSE base/cand | floor10 base/cand |
| --- | ---: | ---: | ---: | ---: | --- | --- | --- | --- |
| `train` | 381 | 13.725409 | 13.491567 | -0.233841 | 27.009253 / 25.683163 | 66.457703 / 66.828355 | 5.543500 / 5.157649 | 0.304833 / 0.282287 |
| `val` | 86 | 8.617390 | 8.727690 | +0.110300 | 16.937550 / 17.250517 | 35.747788 / 37.074938 | 4.799782 / 4.938477 | 0.273249 / 0.282020 |
| `test` | 63 | 24.379358 | 24.350354 | -0.029004 | 11.790345 / 12.303475 | 105.904659 / 105.517558 | 3.420118 / 4.142161 | 0.162625 / 0.180124 |
| `all` | 530 | 14.769036 | 14.618196 | -0.150840 | 23.889508 / 22.642983 | 63.542788 / 63.739192 | 5.266499 / 5.044990 | 0.282804 / 0.270100 |

`delta_cap_mps=1.0`：

| split | points | baseline RMSE | candidate RMSE | delta RMSE | P95 base/cand | P99 base/cand | light RMSE base/cand | floor10 base/cand |
| --- | ---: | ---: | ---: | ---: | --- | --- | --- | --- |
| `train` | 381 | 13.725409 | 13.625758 | -0.099651 | 27.009253 / 26.219658 | 66.457703 / 66.616774 | 5.543500 / 5.353065 | 0.304833 / 0.292559 |
| `val` | 86 | 8.617390 | 8.622928 | +0.005537 | 16.937550 / 17.081438 | 35.747788 / 36.643507 | 4.799782 / 4.789573 | 0.273249 / 0.272001 |
| `test` | 63 | 24.379358 | 24.370117 | -0.009241 | 11.790345 / 12.566282 | 105.904659 / 105.784732 | 3.420118 / 3.721781 | 0.162625 / 0.165183 |
| `all` | 530 | 14.769036 | 14.701260 | -0.067776 | 23.889508 / 23.578447 | 63.542788 / 63.640361 | 5.266499 / 5.136388 | 0.282804 / 0.274083 |

test split guardrail：

```text
weighted_rmse_not_worse = PASS
p95_not_worse = FAIL
p99_not_worse = PASS
light_rmse_not_worse = FAIL
light_mae_not_worse = FAIL
floor10_not_worse = FAIL
no_new_light_moderate_tail_failure = PASS
high_error_count_not_worse = PASS
POINT_REPORT_OVERALL = FAIL
```

结论：

```text
all-points 表面上有改善，说明 residual learning 有信号。
但 frame-split test 中 P95、light wind、floor10 relative 被污染。
当前 report_v1 没有通过 guardrail。
```

### 17.6 “不进入 field_v1” 的含义

这里的“不进入 field_v1”不是说 PINN 不能作为 Stage5 后处理，也不是说它必须替换 tp26 才算成功。含义是：

```text
当前 point-level report_v1 还没有证明 residual model 在未见过的 frame 上足够安全。
因此暂时不要把它扩展成 3D field-collocation PINN，也不要生成 Stage5 full-field candidate 去跑 200-frame formal gate。
```

用户目标“在需要的地方用 PINN”是正确方向。下一步应把 `gate` 做得更严格、更分 regime，而不是全体 holdout 点都允许小残差：

```text
只在 support-strong、role-gap-low、非 light-wind 敏感、非 high-tail-risk 的 bucket 中启用 residual。
在 5-15mps light wind、floor10 relative 敏感区，默认 gate=0 或极低。
在 high sigma_rep / no-claim / remote-support 区域，PINN 主要输出 uncertainty，不做大幅修正。
```

### 17.7 下一步优化方向

下一轮不要直接进入 `field_v1`。建议先做 `tp26_residual_pinn_report_v2_guarded`：

```text
1. 对 test split 做 regime audit：
   找出 residual 改善/劣化分别集中在哪些 truth-free bucket。

2. 改 gate：
   light wind 5-15mps proxy 或 pred_speed 5-15mps 默认强保护；
   floor10-sensitive bucket 降 gate；
   role_gap>=20、nearest_distance>4、recon_confidence<0.2、context_only 均降 gate；
   high reliability + current support >=1 + role_gap<20 才允许较大 gate。

3. 改 loss：
   light/floor10 penalty 进入 validation objective；
   early stopping 用 val_guardrail_score，而不是只看 val RMSE；
   对 P95/P99 劣化加入 soft penalty。

4. 改模型：
   先用更小模型或 linear/GBDT residual baseline 做对照；
   residual head 分 regime 训练或 mixture-of-experts；
   uncertainty 高时自动 shrink delta。

5. 通过标准：
   test split weighted RMSE、P95、P99、light RMSE/MAE、floor10 relative 全部不劣化；
   再进入 field_v1。
```

只有 `report_v2_guarded` 通过后，才建议做：

```text
tp26_residual_pinn_field_v1
  3D collocation dataset
  weak divergence loss
  edge-aware smoothness loss
  vertical gradient preservation
  two-frame smoke
  200-frame formal gate
```

## 18. 2026-06-09 regime audit 与 truth-free gate selection 更新

本节记录在 `report_v1` 原始全点 residual PINN 失败之后做的下一步诊断与 guarded gate 试验。

### 18.1 新增脚本

```text
stage/centralized_v1/core/centralized_stage5_residual_pinn_regime_audit.py
stage/centralized_v1/core/centralized_stage5_residual_pinn_gate_select.py
```

`regime_audit` 用于回答：

```text
PINN residual 在哪些 bucket 改善，哪些 bucket 劣化？
```

`gate_select` 用于回答：

```text
只用 truth-free 特征，在 val split 上选择门控规则；
规则锁定后再评估 test split；
test 不参与规则选择。
```

### 18.2 regime audit 结论

原始全点 residual correction 的主要问题不是完全无信号，而是 regime 不稳定。

改善更明显的 bucket：

```text
context_count_bin=ctx0
representation_risk_score roughly 0.20-0.35
truth_speed 60mps_plus_extreme
altitude 9-12km / 12km_plus
non-pred-light strong/tail cases
```

劣化更明显的 bucket：

```text
pred_light_wind=true
truth_speed 5-15mps_light
truth_speed 15-30mps_moderate 的一部分
altitude 6-9km
representation_risk_score 0.10-0.20
sigma_rep_proxy 5-10mps
role_gap 10-20mps
```

因此 Stage5 residual PINN 不应全点启用。正确方向是：

```text
tp26 remains baseline.
Stage5 residual only acts as a small, truth-free, regime-gated correction.
Light-wind and floor10-sensitive regimes default protected.
```

### 18.3 broad gate selection 结果

先用 broad candidate pool 在 val 上按最大 RMSE 改善选门控。

`delta_cap_mps=1.0`：

```text
selected rule = risk_ge_0p2_or_pred30_not_light
scale = 1.0
val:  RMSE 8.617390 -> 8.603763, POINT_REPORT_OVERALL PASS
test: RMSE 24.379357 -> 24.362418, but P95/floor10 FAIL
```

`delta_cap_mps=3.0`：

```text
selected rule = risk_ge_0p3_or_pred30_not_light
scale = 0.75
val:  RMSE 8.617390 -> 8.586695, POINT_REPORT_OVERALL PASS
test: RMSE 24.379357 -> 24.337143, but P95/floor10 FAIL
```

结论：

```text
broad pool 会倾向启用 pred_speed>=30mps 的中等风点。
这能降低 RMSE，但仍会污染 test P95/floor10。
不适合作为 field_v1 前置门控。
```

### 18.4 tail_safe + promotion_safe 结果

随后使用更保守的 `tail_safe` rule profile：

```text
排除 pred_light_wind；
排除 pred30 中风扩张；
只允许 pred_speed>=45mps 或中高 representation risk 的小范围 residual。
```

并使用 `promotion_safe` selection policy：

```text
仍只看 val；
候选必须 val guardrail PASS 且 val RMSE 改善；
在保留至少 50% val RMSE 改善的候选中，优先选择更小 residual scale 和更好的 val floor10 margin。
```

`delta_cap_mps=1.0` promote-safe locked result：

```text
selected rule = risk_ge_0p2_or_pred45_not_light
scale = 0.50
val enabled points = 18 / 86
test enabled points = 18 / 63

val:
  RMSE 8.617390 -> 8.614037
  P95 16.937550 -> 16.937550
  P99 35.747789 -> 35.747418
  light RMSE 4.799782 -> 4.798943
  floor10 0.273249 -> 0.273137
  POINT_REPORT_OVERALL PASS

locked test:
  RMSE 24.379357 -> 24.367270
  P95 11.790345 -> 11.790345
  P99 105.904655 -> 105.844654
  light RMSE 3.420118 -> 3.420118
  floor10 0.162625 -> 0.162602
  POINT_REPORT_OVERALL PASS
```

`delta_cap_mps=3.0` promote-safe locked result：

```text
selected rule = risk_ge_0p3_or_pred45_not_light
scale = 0.25
val enabled points = 8 / 86
test enabled points = 12 / 63

val:
  RMSE 8.617390 -> 8.612720
  P95 16.937550 -> 16.937550
  P99 35.747789 -> 35.747585
  light RMSE 4.799782 -> 4.798463
  floor10 0.273249 -> 0.273079
  POINT_REPORT_OVERALL PASS

locked test:
  RMSE 24.379357 -> 24.362658
  P95 11.790345 -> 11.790345
  P99 105.904655 -> 105.807634
  light RMSE 3.420118 -> 3.420118
  floor10 0.162625 -> 0.162489
  POINT_REPORT_OVERALL PASS
```

报告输出：

```text
centralized_v1_output/stage5_residual_pinn_report_v1_20260608/regime_audit_cap1/
centralized_v1_output/stage5_residual_pinn_report_v1_20260608/regime_audit_cap3/
centralized_v1_output/stage5_residual_pinn_report_v1_20260608/gate_select_tail_safe_promote_cap1/
centralized_v1_output/stage5_residual_pinn_report_v1_20260608/gate_select_tail_safe_promote_cap3/
```

### 18.5 当前判断

`tail_safe + promotion_safe` 已经让 point-level locked test 通过 guardrail，但改善幅度很小：

```text
cap1 test RMSE delta = -0.012087 m/s
cap3 test RMSE delta = -0.016699 m/s
```

因此当前结论是：

```text
可以进入 field_v1 smoke 试制；
不能宣布替代 tp26；
不能把 Stage5 设为默认；
field_v1 必须继续过 full-field smoke、200-frame strict holdout pairwise、P95/P99/light/floor10 全 guardrail。
```

推荐先做：

```text
tp26_residual_pinn_field_v1_tail_safe_smoke
  use cap1 or cap3 checkpoint only through selected truth-free gate
  write 2-5 frame NPZ smoke first
  compare Stage4 tp26 vs Stage5 gated field at aircraft holdout points
  verify no light/floor10/P95 regressions
```

如果 smoke 通过，再扩展到 200-frame formal candidate。
