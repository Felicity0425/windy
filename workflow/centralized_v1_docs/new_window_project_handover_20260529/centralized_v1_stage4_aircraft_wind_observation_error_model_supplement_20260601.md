# centralized_v1 Stage4 Aircraft Wind Observation Error Model 补充方案（2026-06-01）

本文档是对以下 Stage4 质量提升文档和实验报告的专项补充：

```text
workflow/centralized_v1_docs/new_window_project_handover_20260529/centralized_v1_stage4_quality_improvement_methods_20260601.md
centralized_v1_output/stage4_obs_error_weighted_200_20260601/analysis/obs_error_weighted_implementation_report.md
centralized_v1_output/stage4_adaptive_localization_200_20260601/analysis_adaptive_v2/adaptive_localization_phase2_report.md
```

目标是把 de Haan and Stoffelen 2016 与 EMADDC 2025 中关于 aircraft-derived wind 观测误差和业务质控的结论，整理成可直接接入 `centralized_v1` Stage4 的 `Aircraft Wind Observation Error Model`。

核心原则：

1. 该模型只直接作用于已有 aircraft wind observations，即 `wind_records` / `context_wind_records` 中的 `u_wind`、`v_wind`。
2. `location` 中由地速和航向角得到的 `u_motion`、`v_motion` 仍然是 aircraft kinematics，不是 atmospheric wind。
3. `location-derived pseudo wind` 可以作为后续实验分支，但不能直接进入 official truth，也不能使用 de Haan 2016 的 1.1-1.4 m/s 误差作为默认误差。
4. 正式验证仍然只使用 current aircraft wind strict holdout。
5. CMA/GFS/ERA 等背景场仍然只能作为 weak background、condition 或 prior，不能作为 truth。

---

## 1. 当前问题定位

### 1.1 AMDAR 少，但是真风观测

当前 Stage1 输出中：

```text
stage1_output/clean_wind.parquet rows = 431189
stage1_output/clean_loc.parquet rows  = 19162638
```

`clean_wind.parquet` 来自 AMDAR/TURB 等给出风向、风速的航空观测，当前被转换为：

```text
u_wind
v_wind
wind_dir
wind_speed
```

这类记录是 Stage4 的正式 aircraft wind observation，也是 strict holdout 的唯一 truth 来源。该定位符合 WMO Aircraft-Based Observations Programme 对航空器气象观测的定义：航空器观测可提供风、温度等气象变量，并用于业务气象系统。

参考：

```text
WMO Aircraft-Based Observations Programme
https://wmo.int/aircraft-based-observations-programme
```

### 1.2 Location 多，但不是风

`clean_loc.parquet` 来自 location 报文，当前字段包括：

```text
time_utc
lat_clean
lon_clean
alt_meters
heading_deg
ground_speed_ms
u_motion
v_motion
flight_id
```

其中：

```text
u_motion = ground_speed_ms * sin(heading_deg)
v_motion = ground_speed_ms * cos(heading_deg)
```

这代表飞机相对地面的运动矢量，不代表大气风矢量。风矢量需要：

```text
wind_vector = ground_vector - air_vector
```

如果没有 true airspeed / Mach / air vector / magnetic heading 等 Mode-S EHS 或等价 DAP 字段，仅靠地速和航向角无法唯一反推出风。EMADDC 2025 说明 operational aircraft-derived wind 需要 air vector 和 ground vector 的组合，并且需要完整 QC 流程；普通 ADS-B 或简化 location 报文通常不包含完整的风温反演参数。

参考：

```text
EMADDC aircraft weather observations and quality control, AMT 2025
https://amt.copernicus.org/articles/18/3341/2025/
```

### 1.3 当前 obs-error calibration 的问题

当前 Phase 1 实验已实现：

```text
confidence_mode = obs_error_weighted
stage/centralized_v1/core/centralized_stage4_obs_error_calibration.py
```

当前 200 帧校准输出：

```text
calibration samples: 150901
excluded holdout records: 530
global robust sigma: 13.643460 m/s
```

这个 `13.643460 m/s` 不应继续解释为纯 aircraft observation error。它更像：

```text
local representativeness error
+ neighbor mismatch
+ sparse aircraft geometry error
+ context/current time mismatch
+ unresolved local variability
```

也就是说，它是局地一致性/代表性诊断量，而不是 de Haan 2016 所估计的 aircraft wind observation error。后续应把它重命名或解释为：

```text
local_consistency_or_representativeness_sigma
```

它可以继续用于 QC、adaptive localization 或低置信诊断，但不应作为 `sigma_obs` 主表。

---

## 2. 文献依据和可直接采用的误差模型

### 2.1 de Haan and Stoffelen 2016：物理观测误差下限

de Haan and Stoffelen 2016 使用 triple collocation 方法估计 Mode-S EHS 派生风的观测误差。其核心价值是给出 aircraft-derived wind 的真实观测误差量级：

```text
近地面：约 1.4 m/s
500 hPa 附近：约 1.1 m/s
高空误差更小
u/v 分量误差量级接近
```

这适合作为项目中的 `physical_lower_bound_sigma`，即 aircraft wind 观测误差下限。它可以用于说明：

1. aircraft wind observation 是高可信观测；
2. aircraft wind 应优先于 CMA/GFS/ERA 等背景场；
3. Stage4 的 `obs_error_sigma_floor_mps` 不应随意设得过大；
4. 当前 13.64 m/s 不是纯观测误差，而是代表性/局地差异混合误差。

参考：

```text
de Haan and Stoffelen 2016, AMT
https://amt.copernicus.org/articles/9/4141/2016/
```

建议建立 `dehaan_physical_sigma` profile：

| 高度层 | 气压近似 | sigma_obs | 用途 | 来源 |
| --- | --- | ---: | --- | --- |
| 0-1 km | 900-1000 hPa | 1.4 m/s | 物理观测误差下限 | de Haan 2016 |
| 1-3 km | 700-900 hPa | 1.3 m/s | 插值先验 | de Haan 2016 |
| 3-6 km | 500-700 hPa | 1.2 m/s | 插值先验 | de Haan 2016 |
| 6-10 km | 300-500 hPa | 1.1 m/s | 高空下限 | de Haan 2016 |
| 10-15 km | <300 hPa | 1.1 m/s | 高空下限 | de Haan 2016 |

注意：该表是项目化离散化后的高度表，不应写成 de Haan 2016 原文逐层表。原文关键值是近地面约 1.4 m/s 与 500 hPa 约 1.1 m/s，中间高度为项目插值先验。

### 2.2 EMADDC 2025：业务有效误差

EMADDC 2025 介绍了欧洲业务化 Mode-S EHS aircraft weather observations 处理系统。其价值不是给出纯物理仪器误差，而是给出经过大规模 QC 后的 operational aircraft-derived wind 在业务背景场比较中的误差量级。

可归纳为：

```text
低层：约 2.2 m/s
高层：约 2.8 m/s
随高度略有增大
```

该量级更适合当前 Stage4，因为 Stage4 面临的并不只是测量误差，还包括：

```text
500 m 垂直网格代表性差异
6 min 时间窗代表性差异
局地外推误差
飞机航路稀疏支撑
同一体素多源观测不一致
```

参考：

```text
EMADDC aircraft weather observations and quality control, AMT 2025
https://amt.copernicus.org/articles/18/3341/2025/
```

建议建立 `emaddc_operational_sigma` profile：

| 高度层 | sigma_obs | 用途 | 来源 |
| --- | ---: | --- | --- |
| 0-3 km | 2.2 m/s | Stage4 operational prior low level | EMADDC 2025 |
| 3-6 km | 2.5 m/s | Stage4 operational prior mid level | EMADDC 2025 + project interpolation |
| 6-15 km | 2.8 m/s | Stage4 operational prior upper level | EMADDC 2025 |

### 2.3 两个 profile 的项目定位

| profile | 误差含义 | 推荐用途 | 是否默认 |
| --- | --- | --- | --- |
| `dehaan_physical_sigma` | aircraft-derived wind 物理观测误差下限 | sanity check、敏感性分析、理论依据 | 否 |
| `emaddc_operational_sigma` | 业务有效 aircraft wind 误差 | Stage4 200 帧/全量候选 | 是，先作为候选 |
| `local_consistency_sigma` | 代表性/局地一致性混合误差 | QC、adaptive localization、诊断 | 否，不作纯 sigma_obs |

---

## 3. Stage4 中的模型定义

### 3.1 基本公式

对每条 aircraft wind observation：

```text
sigma_obs = f(height)
obs_error_weight_raw = 1 / sigma_obs^2
```

在当前代码中建议采用相对权重形式，以避免绝对量级直接改变整体数值尺度：

```text
obs_error_weight =
    clip((reference_sigma / sigma_obs)^2,
         obs_error_weight_min,
         obs_error_weight_max)
```

最终 Stage4 active weight：

```text
active_weight =
    localization_weight
  * time_conf
  * obs_error_weight
  * optional_diagnostic_factor
```

其中：

```text
localization_weight = target voxel localization
time_conf = Stage2/Stage3 时间新鲜度
obs_error_weight = aircraft wind observation error prior
optional_diagnostic_factor = density / QC / consistency 等诊断因子
```

### 3.2 downweight-only 是当前推荐形式

当前 200 帧 Phase 1 结果：

| method | frame RMSE | frame MAE | weighted RMSE | weighted MAE | P95 RMSE | P99 RMSE |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| TimePower15 baseline | 8.636457 | 7.423151 | 15.038701 | 7.172653 | 28.147279 | 63.233730 |
| obs_error full inverse-variance | 8.693788 | 7.553384 | 15.354362 | 7.378215 | 29.123066 | 61.437458 |
| obs_error downweight-only | 8.604297 | 7.437403 | 15.133321 | 7.183285 | 28.126912 | 63.106674 |

解释：

1. full inverse-variance 会增强部分观测，可能加重局地过拟合；
2. downweight-only 只降低相对不可靠观测权重，更稳；
3. downweight-only frame RMSE 和 P95/P99 略有改善，但 weighted RMSE/MAE 仍略差；
4. 因此不应直接推广为默认主线。

建议继续使用：

```text
obs_error_weight_min = 0.2
obs_error_weight_max = 1.0
```

### 3.3 建议的 JSON calibration 文件

建议新增候选 calibration 文件：

```text
centralized_v1_output/stage4_literature_obs_error_200_20260601/calibration/literature_emaddc_operational_height_sigma.json
centralized_v1_output/stage4_literature_obs_error_200_20260601/calibration/literature_dehaan_physical_height_sigma.json
```

`literature_emaddc_operational_height_sigma.json`：

```json
{
  "calibration_role": "literature_height_prior_emaddc2025_operational",
  "calibration_note": "Operational effective aircraft wind error prior from EMADDC 2025, used as Stage4 downweight-only observation-error prior.",
  "references": [
    "https://amt.copernicus.org/articles/18/3341/2025/",
    "https://wmo.int/aircraft-based-observations-programme"
  ],
  "obs_error_sigma_floor_mps": 1.0,
  "obs_error_sigma_default_mps": 2.5,
  "obs_error_reference_sigma_mps": 2.2,
  "obs_error_weight_min": 0.2,
  "obs_error_weight_max": 1.0,
  "obs_error_use_diagnostic_factor": 1.0,
  "obs_error_altitude_bin_edges_m": [0.0, 3000.0, 6000.0, 15000.0, 20000.0],
  "obs_error_altitude_bin_sigma_mps": {
    "bin0": 2.2,
    "bin1": 2.5,
    "bin2": 2.8,
    "bin3": 2.8
  }
}
```

`literature_dehaan_physical_height_sigma.json`：

```json
{
  "calibration_role": "literature_height_prior_dehaan2016_physical_lower_bound",
  "calibration_note": "Physical lower-bound aircraft-derived wind observation error prior from de Haan and Stoffelen 2016; use for sensitivity analysis, not default promotion.",
  "references": [
    "https://amt.copernicus.org/articles/9/4141/2016/",
    "https://wmo.int/aircraft-based-observations-programme"
  ],
  "obs_error_sigma_floor_mps": 1.0,
  "obs_error_sigma_default_mps": 1.2,
  "obs_error_reference_sigma_mps": 1.4,
  "obs_error_weight_min": 0.2,
  "obs_error_weight_max": 1.0,
  "obs_error_use_diagnostic_factor": 1.0,
  "obs_error_altitude_bin_edges_m": [0.0, 1000.0, 3000.0, 6000.0, 10000.0, 15000.0, 20000.0],
  "obs_error_altitude_bin_sigma_mps": {
    "bin0": 1.4,
    "bin1": 1.3,
    "bin2": 1.2,
    "bin3": 1.1,
    "bin4": 1.1,
    "bin5": 1.1
  }
}
```

注意：当前代码 `_obs_error_sigma_for_row` 会优先使用 composite bin，再使用 altitude/speed/density/consistency marginal bin。文献 height-prior JSON 不应包含 `obs_error_bin_sigma_mps`，否则会覆盖高度先验。

---

## 4. 对 current calibration 的修正方案

### 4.1 不删除现有 calibration

现有 calibration 文件仍然保留：

```text
centralized_v1_output/stage4_obs_error_weighted_200_20260601/calibration/stage4_aircraft_obs_error_calibration.json
centralized_v1_output/stage4_obs_error_weighted_200_20260601/calibration_downweight_only/stage4_aircraft_obs_error_calibration.json
```

但文档解释需要调整：

旧解释：

```text
aircraft observation-error calibration
global robust sigma = 13.643460 m/s
```

新解释：

```text
local aircraft-wind consistency / representativeness calibration
global robust local departure sigma = 13.643460 m/s
not pure aircraft observation error
```

### 4.2 保留用途

该 local-consistency calibration 可继续用于：

1. 标记局地多 aircraft wind 不一致区域；
2. 识别 role conflict 或 context/current 冲突；
3. 作为 adaptive localization 的非 holdout gating 特征；
4. 作为高误差溯源字段；
5. 为 location-derived pseudo wind 实验提供保守误差上限参考。

### 4.3 禁止用途

禁止把 13.64 m/s 直接写成：

```text
aircraft wind observation error
AMDAR measurement error
Mode-S EHS equivalent observation error
```

它不等价于 de Haan 2016 的 triple-collocation observation error，也不等价于 EMADDC 2025 的 operational QC wind error。

---

## 5. Holdout 验证中的使用方式

### 5.1 sigma_obs 不修正 RMSE

正式 RMSE/MAE 仍然按原始误差统计：

```text
error_u = recon_u - holdout_u
error_v = recon_v - holdout_v
error_vector = sqrt(error_u^2 + error_v^2)
```

禁止使用：

```text
corrected_error = error - sigma_obs
```

或：

```text
RMSE_adjusted_by_obs_error
```

### 5.2 sigma_obs 用于不确定性诊断

可以新增诊断字段：

```text
holdout_sigma_obs_mps
holdout_normalized_error = error_vector / max(sigma_obs, eps)
holdout_error_exceeds_2sigma
holdout_error_exceeds_3sigma
height_bin
height_bin_error_mean
height_bin_normalized_error_mean
```

推荐报告：

| 指标 | 说明 |
| --- | --- |
| `mean_normalized_error` | 模型误差相对观测误差的平均倍数 |
| `p95_normalized_error` | 尾部误差相对观测误差倍数 |
| `fraction_error_gt_3sigma` | 是否存在系统性重构误差 |
| `height_bin_rmse` | 各高度层 RMSE |
| `height_bin_weighted_mae` | 各高度层 holdout-point weighted MAE |

解释边界：

```text
sigma_obs 是观测误差，不是重构误差。
如果 normalized_error 远大于 1，说明主要误差来自重构、代表性、稀疏支撑、局地急变等。
```

---

## 6. Adaptive localization 中的使用方式

### 6.1 只能作为一个 gating 特征

Adaptive localization 不能只由高度 sigma 表决定。Phase 2 adaptive v2 已证明，核选择对低误差带和高误差带的影响不同：

| method | frame RMSE | weighted RMSE | weighted MAE | 结论 |
| --- | ---: | ---: | ---: | --- |
| TimePower15 fixed 8/4 | 8.636457 | 15.038701 | 7.172653 | 当前基线 |
| Adaptive v2 + obs-error downweight | 8.540259 | 15.034469 | 7.080333 | 均值改善，但低误差带退化 |

Adaptive v2 的主要问题：

```text
baseline_rmse_le6:
TimePower15 RMSE = 3.655491
adaptive v2 RMSE = 3.793112
delta = +0.137621
```

因此，`sigma_obs` 应只作为以下非 holdout 特征之一：

```text
obs_error_weight_mean
current wind support
context wind support
context freshness
role conflict gap
vertical mismatch count
low_conf_fill_fraction
effective reconstructed fraction
```

参考：

```text
DART covariance localization / Gaspari-Cohn
https://docs.dart.ucar.edu/en/latest/assimilation_code/modules/assimilation/cov_cutoff_mod.html
```

### 6.2 推荐 v3 gating 方向

Phase 2 报告建议 v3 不再增加复杂启发式，而做 lean ablation：

```text
candidate kernels: 8/4, 10/5
remove rare 6/3 branch
avoid 12/6 aggressive fallback
add low-error guard
test with and without obs-error downweight
```

低误差保护应只使用非 holdout 诊断：

```text
high current support
high local consistency
low low_conf_fill_fraction
low role_conflict_gap
high confidence current aircraft anchor
```

---

## 7. Location-derived pseudo wind：后续实验分支

### 7.1 当前不能直接做的事

不能直接执行：

```text
location u_motion/v_motion -> wind u/v
```

原因：

```text
ground_vector = air_vector + wind_vector
```

当前 location 只有 ground vector，缺少 air vector。没有 true airspeed / Mach / heading 等参数时，方程不可唯一解。

### 7.2 可以做的实验分支

如果要利用 1900 万 location，应新增独立数据源：

```text
source = loc_pseudo_wind
used_as_truth = False
used_as_background_or_pseudo_observation = True
```

步骤：

1. 按 `flight_id`、时间、空间、高度匹配 AMDAR/TURB wind 与 location motion；
2. 在匹配点计算：

```text
estimated_air_u = u_motion - u_wind
estimated_air_v = v_motion - v_wind
estimated_air_speed = sqrt(estimated_air_u^2 + estimated_air_v^2)
```

3. 按同一 flight segment 平滑 `estimated_air_u/v`；
4. 过滤异常 flight phase：

```text
rapid climb/descent
large turn rate
unrealistic air speed
low altitude terminal phase if too noisy
time gap too large from AMDAR anchor
```

5. 对邻近 location 生成：

```text
pseudo_wind_u = u_motion - smoothed_air_u
pseudo_wind_v = v_motion - smoothed_air_v
```

6. 用未参与平滑的 AMDAR holdout 验证 pseudo wind；
7. 若通过验证，再低权重进入 Stage4。

### 7.3 pseudo wind 的误差不能套用 de Haan

`loc_pseudo_wind` 不应使用：

```text
sigma_obs = 1.1-1.4 m/s
```

推荐初始：

```text
sigma_obs_initial = 8-20 m/s
obs_error_weight_max <= 0.2
```

只有当 independent AMDAR holdout 证明 pseudo wind 稳定后，才能降低 sigma。

---

## 8. 建议实验路线

### 8.1 Phase 1b：文献高度 sigma prior

目标：

```text
把 de Haan / EMADDC 文献高度 sigma 表接入 obs_error_weighted，替代当前 13.64 m/s 作为主 sigma_obs。
```

候选：

```text
timepower15_baseline
obs_error_downweight_current_local_consistency
obs_error_dehaan_height_prior
obs_error_emaddc_height_prior
```

固定评估集：

```text
centralized_v1_output/stage4_three_method_compare_20260531/analysis/frame_times_200_holdout_seed20260531.txt
```

推荐输出目录：

```text
centralized_v1_output/stage4_literature_obs_error_200_20260601
```

### 8.2 Phase 1b 运行模板

EMADDC operational prior：

```bash
ROOT=/data/LFT-W02_data/pengxu
PY=$ROOT/.conda/envs/windy310/bin/python
OUT=$ROOT/centralized_v1_output/stage4_literature_obs_error_200_20260601/emaddc_operational_metrics

$PY $ROOT/stage/centralized_v1/core/centralized_stage4_sensitivity.py \
  --stage2-summary $ROOT/centralized_v1_output/stage2_full_v2/stage2_multimodal_summary.json \
  --stage3-summary $ROOT/centralized_v1_output/stage3_full_v2_8w_minimal/stage3_center_summary.json \
  --frame-times-file $ROOT/centralized_v1_output/stage4_three_method_compare_20260531/analysis/frame_times_200_holdout_seed20260531.txt \
  --out-dir $OUT \
  --sample-count 0 \
  --param-grid 8,4,2,1 \
  --kernels gaussian \
  --confidence-mode obs_error_weighted \
  --qc-calibration $ROOT/centralized_v1_output/stage4_literature_obs_error_200_20260601/calibration/literature_emaddc_operational_height_sigma.json \
  --physics-constraint-mode pydda_3dvar_proxy \
  --current-weight-boost 2.0 \
  --context-weight-scale 0.5 \
  --context-time-conf-power 1.5 \
  --role-conflict-mode current_priority_adaptive \
  --conflict-speed-threshold-mps 12 \
  --conflict-context-factor 0.25 \
  --progress-interval-seconds 30 \
  --num-workers 12
```

de Haan physical prior：

```bash
ROOT=/data/LFT-W02_data/pengxu
PY=$ROOT/.conda/envs/windy310/bin/python
OUT=$ROOT/centralized_v1_output/stage4_literature_obs_error_200_20260601/dehaan_physical_metrics

$PY $ROOT/stage/centralized_v1/core/centralized_stage4_sensitivity.py \
  --stage2-summary $ROOT/centralized_v1_output/stage2_full_v2/stage2_multimodal_summary.json \
  --stage3-summary $ROOT/centralized_v1_output/stage3_full_v2_8w_minimal/stage3_center_summary.json \
  --frame-times-file $ROOT/centralized_v1_output/stage4_three_method_compare_20260531/analysis/frame_times_200_holdout_seed20260531.txt \
  --out-dir $OUT \
  --sample-count 0 \
  --param-grid 8,4,2,1 \
  --kernels gaussian \
  --confidence-mode obs_error_weighted \
  --qc-calibration $ROOT/centralized_v1_output/stage4_literature_obs_error_200_20260601/calibration/literature_dehaan_physical_height_sigma.json \
  --physics-constraint-mode pydda_3dvar_proxy \
  --current-weight-boost 2.0 \
  --context-weight-scale 0.5 \
  --context-time-conf-power 1.5 \
  --role-conflict-mode current_priority_adaptive \
  --conflict-speed-threshold-mps 12 \
  --conflict-context-factor 0.25 \
  --progress-interval-seconds 30 \
  --num-workers 12
```

### 8.3 Phase 1b 成功标准

必须同时满足：

```text
strict_holdout_no_leakage = True for all rows
motion_used_as_wind = False for all rows
frame RMSE <= TimePower15 baseline
frame MAE not materially worse
weighted RMSE not materially worse
weighted MAE not materially worse
P95/P99 improve or remain flat
baseline_rmse_le6 not degraded
single_holdout_pressure_test not degraded
```

建议决策口径：

| 条件 | 结论 |
| --- | --- |
| frame RMSE 改善但 low-error band 退化 | 保留候选，不推广 |
| weighted MAE 退化明显 | 不推广 |
| P95/P99 改善但均值退化 | 只作为 tail-repair candidate |
| 全指标小幅改善且无泄漏 | 可进入 5614 帧 holdout-only 全量验证 |

### 8.4 Phase 2b：adaptive localization v3

在 literature sigma prior 稳定后，再做 adaptive v3：

```text
fixed 8/4
fixed 10/5
adaptive v3 without obs-error downweight
adaptive v3 with emaddc operational obs-error downweight
adaptive v3 with dehaan physical obs-error downweight
```

优先目标：

1. 保住 `baseline_rmse_le6`；
2. 继续改善 `baseline_rmse_10_20` 和 `baseline_rmse_gt20`；
3. 不牺牲 weighted MAE；
4. 不引入 12/6 过宽核导致的局地抹平。

---

## 9. 必须写入报告的字段

每次 obs-error 或 adaptive localization 实验，报告至少包含：

```text
calibration_role
sigma_profile_name
sigma_source_references
obs_error_sigma_default_mps
obs_error_reference_sigma_mps
obs_error_weight_min
obs_error_weight_max
obs_error_use_diagnostic_factor
mean_obs_error_sigma
mean_obs_error_weight
frame_mean_rmse_vector
frame_mean_mae_vector
holdout_point_weighted_rmse_vector
holdout_point_weighted_mae_vector
median_rmse
p90_rmse
p95_rmse
p99_rmse
single_holdout_pressure_test
multi_holdout_supported
baseline_rmse_le6
baseline_rmse_6_10
baseline_rmse_10_20
baseline_rmse_gt20
method A vs method B win/loss/tie
top wins
top losses
strict_holdout_no_leakage
any_motion_used_as_wind
cma_used_as_background_not_truth
```

新增建议字段：

```text
height_bin
height_bin_sigma_obs_mps
height_bin_frame_rmse
height_bin_weighted_mae
height_bin_normalized_error
fraction_error_gt_2sigma
fraction_error_gt_3sigma
```

---

## 10. 对外报告标准表述

推荐表述：

```text
Aircraft wind observations are the only official truth source in Stage4 strict holdout validation. We use literature-based aircraft wind observation-error priors from de Haan and Stoffelen (2016) and EMADDC (2025) to weight existing aircraft wind records by height. The prior is applied only to wind_records and context_wind_records. Motion/location records remain aircraft kinematic diagnostics and are not treated as wind truth.
```

中文表述：

```text
Stage4 正式验证只以 current aircraft wind holdout 为真值。本文采用 de Haan and Stoffelen 2016 与 EMADDC 2025 给出的 aircraft-derived wind 误差量级，构建按高度分箱的飞机风观测误差先验，并仅用于已有 wind_records / context_wind_records 的权重计算。location/motion 记录只作为轨迹、覆盖和运动诊断，不作为大气风真值。
```

禁止表述：

```text
location 地速可以直接当风
1900 万 location 已经全部变成飞机风
13.64 m/s 是 aircraft wind 观测误差
CMA/GFS/ERA 是验证真值
no-holdout 帧的 0 误差代表模型正确
de Haan 2016 证明 Stage4 三维重构误差应为 1.1 m/s
```

---

## 11. 最终建议

短期应执行：

1. 新增两个 literature height-prior calibration JSON：
   - `literature_emaddc_operational_height_sigma.json`
   - `literature_dehaan_physical_height_sigma.json`
2. 跑固定 200 帧 metrics-only：
   - TimePower15 baseline
   - current local-consistency downweight-only
   - EMADDC operational height prior
   - de Haan physical height prior
3. 新增 pairwise 对比：
   - TimePower15 vs EMADDC prior
   - TimePower15 vs de Haan prior
   - current downweight-only vs EMADDC prior
4. 更新报告，将 `13.643460 m/s` 明确改称为 local representativeness sigma。
5. 若 200 帧通过，再跑 5614 帧 holdout-only 全量验证。
6. location-derived pseudo wind 仅作为后续独立实验，不进入本轮 official Stage4 truth 或主线融合。

当前最佳判断：

```text
最稳的立即行动不是把 location 变成风，
而是用 de Haan / EMADDC 文献高度 sigma 表替换当前误解释的 13.64 m/s obs-error sigma，
并把 current 13.64 m/s calibration 下放为局地一致性/代表性诊断。
```

---

## 12. 参考文献

### Aircraft observations and observation-error modeling

1. WMO Aircraft-Based Observations Programme
   https://wmo.int/aircraft-based-observations-programme

2. de Haan, S. and Stoffelen, A. (2016). Characterization of high-resolution aircraft-derived wind and temperature observations from Mode-S. Atmospheric Measurement Techniques.
   https://amt.copernicus.org/articles/9/4141/2016/

3. EMADDC aircraft weather observations and quality control, Atmospheric Measurement Techniques, 2025.
   https://amt.copernicus.org/articles/18/3341/2025/

### Localization and data assimilation

4. DART covariance cutoff / Gaspari-Cohn localization documentation.
   https://docs.dart.ucar.edu/en/latest/assimilation_code/modules/assimilation/cov_cutoff_mod.html

5. ECMWF 4D-Var overview article.
   https://www.ecmwf.int/en/newsletter/175/earth-system-science/linearised-physics-heart-ecmwfs-4d-var

6. NCEP data assimilation / GSI overview.
   https://www.emc.ncep.noaa.gov/emc/pages/numerical_forecast_systems/ncep_data_assimilation.php

7. Hunt, Kostelich, and Szunyogh (2007), LETKF paper page.
   https://experts.azregents.edu/en/publications/efficient-data-assimilation-for-spatiotemporal-chaos-a-local-ense/

### Radar and variational wind retrieval

8. PyDDA documentation.
   https://openradarscience.org/PyDDA/

9. PyDDA Journal of Open Research Software paper.
   https://openresearchsoftware.metajnl.com/articles/10.5334/jors.264

### Residual modeling and uncertainty

10. Raissi, Perdikaris, and Karniadakis (2019), Physics-informed neural networks.
    https://doi.org/10.1016/j.jcp.2018.10.045

11. Fourier Neural Operator, Li et al.
    https://openreview.net/forum?id=c8P9NQVtmnO

12. DeepONet, Lu et al.
    https://www.nature.com/articles/s42256-021-00302-5

13. GenCast diffusion ensemble weather forecasting.
    https://www.nature.com/articles/s41586-024-08252-9

### Gradient-preserving smoothing

14. Perona and Malik anisotropic diffusion.
    https://doi.org/10.1109/34.56205
