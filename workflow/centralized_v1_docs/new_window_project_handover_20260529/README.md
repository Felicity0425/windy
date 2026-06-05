# Stage4 教师展示包：baseline / adaptive_v3 / tp26_thr11_preserve

本文件夹用于展示 `centralized_v1` Stage4 的三组对照结果。三组方法都遵守同一个验证边界：正式 truth 只使用 current aircraft `wind_records` strict holdout；被选为 holdout 的风观测在融合前移除；`location/motion` 不当作风；CMA/GFS/ERA 不当作 truth；no-holdout 帧不进入官方 RMSE/MAE。

## 1. 一句话结论

在固定 200 帧 strict aircraft holdout 样本上，最初纯航空器 `baseline` 的 holdout-weighted RMSE 为 `18.918 m/s`；`adaptive_v3` 降到 `14.933 m/s`；最新 `tp26_thr11_preserve` 进一步降到 `14.769 m/s`。主提升来自从“固定宽核经验插值”升级为“诊断加权 + adaptive localization + 3DVAR proxy + 垂直结构保护”。

## 2. 三组方法对照

| 方法 | 项目内含义 | 关键配置 | 文献借用点 |
| --- | --- | --- | --- |
| `baseline_aircraft` | 最初的纯航空器基线；只靠 aircraft wind 和 context wind 的宽核局地化。 | `gaussian 12/6`, `diagnostic_only`, `proxy`, `role_conflict=off`, `vertical_risk=off` | WMO aircraft observations 支持 aircraft wind 作为正式气象观测；de Haan/EMADDC 支持 aircraft-derived wind 需要 QC 和误差意识；DART/Gaspari-Cohn localization 文献支持“观测影响随距离衰减”的基本思想。 |
| `adaptive_v3` | 在 TimePower15 思路上加入诊断加权、current-priority role conflict、非泄漏 adaptive localization。 | `diagnostic_weighted`, `pydda_3dvar_proxy`, `localization_policy=diagnostic_adaptive_v3`, candidate `8:4,10:5`, `context_time_conf_power=1.5`, `conflict_threshold=12` | Gaspari-Cohn/DART：localization 不是一个永远固定的全局半径；PyDDA/3DVAR：观测锚定、平滑和弱散度约束共同塑造重构场；EMADDC/de Haan：aircraft wind 需要 QC-aware weighting。 |
| `tp26_thr11_preserve` | 当前最新 200 帧最佳候选；在 adaptive_v3 上加强时间衰减并保护强垂直结构。 | `context_time_conf_power=2.6`, `conflict_threshold=11`, `vertical_risk=preserve_strong_layers`, candidate `8:4,10:5` | Desroziers diagnostics：用 departure 行为调背景/观测权重；Janjic representation error：点观测与 500 m 网格/时间窗误差要分开解释；Perona-Malik：保边/保梯度平滑思想；PyDDA/3DVAR：保留观测约束与物理约束。 |

## 3. 200 帧 strict holdout 指标

| 方法 | frames | holdout points | frame RMSE | frame MAE | weighted RMSE | weighted MAE | P95 RMSE | P99 RMSE | max RMSE | leakage | motion as wind |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- |
| `baseline_aircraft` | 200 | 530 | 11.6898 | 10.3011 | 18.9184 | 10.3509 | 42.6407 | 74.2244 | 117.2358 | True | False |
| `adaptive_v3` | 200 | 530 | 8.4570 | 7.3067 | 14.9326 | 7.0682 | 28.1452 | 63.2337 | 109.8872 | True | False |
| `tp26_thr11_preserve` | 200 | 530 | 8.2243 | 7.0819 | 14.7690 | 6.8545 | 27.9861 | 58.7838 | 109.6927 | True | False |

从 `baseline_aircraft` 到 `tp26_thr11_preserve`：

- weighted RMSE: `18.9184 -> 14.7690`, 下降约 `21.9%`
- frame RMSE: `11.6898 -> 8.2243`, 下降约 `29.6%`
- P95 RMSE: `42.6407 -> 27.9861`, 下降约 `34.4%`

解释：`adaptive_v3` 完成了主体跃迁；`tp26_thr11_preserve` 是在高空、长尾和 temporal/context 权重上做的小幅稳定微调。

## 4. 小批量代表帧

这 6 帧来自固定 200 帧 strict holdout 对比集，覆盖“baseline 崩坏、baseline 胜出、临界误差、长尾压力测试”等典型场景。三组方法都重新生成了 full NPZ 和同一裁剪方式的 PNG 图。

| frame | 选择原因 | baseline RMSE | adaptive_v3 RMSE | tp26 RMSE | baseline 图 | adaptive_v3 图 | tp26 图 |
| --- | --- | ---: | ---: | ---: | --- | --- | --- |
| `20260206074200` | baseline 极差、adaptive 类方法显著修复 | 74.1055 | 3.3418 | 3.0785 | [slices](visuals/baseline_aircraft/20260206074200_centralized_stage4_slices.png) / [diag](visuals/baseline_aircraft/20260206074200_centralized_stage4_diagnostics.png) | [slices](visuals/adaptive_v3/20260206074200_centralized_stage4_slices.png) / [diag](visuals/adaptive_v3/20260206074200_centralized_stage4_diagnostics.png) | [slices](visuals/tp26_thr11_preserve/20260206074200_centralized_stage4_slices.png) / [diag](visuals/tp26_thr11_preserve/20260206074200_centralized_stage4_diagnostics.png) |
| `20260125124200` | baseline 偶然胜出，说明宽核在个别点有利 | 4.1319 | 32.5936 | 32.5967 | [slices](visuals/baseline_aircraft/20260125124200_centralized_stage4_slices.png) / [diag](visuals/baseline_aircraft/20260125124200_centralized_stage4_diagnostics.png) | [slices](visuals/adaptive_v3/20260125124200_centralized_stage4_slices.png) / [diag](visuals/adaptive_v3/20260125124200_centralized_stage4_diagnostics.png) | [slices](visuals/tp26_thr11_preserve/20260125124200_centralized_stage4_slices.png) / [diag](visuals/tp26_thr11_preserve/20260125124200_centralized_stage4_diagnostics.png) |
| `20260205190000` | 单点极端压力测试，三组航空器方法都失败 | 86.0000 | 86.0000 | 86.0000 | [slices](visuals/baseline_aircraft/20260205190000_centralized_stage4_slices.png) / [diag](visuals/baseline_aircraft/20260205190000_centralized_stage4_diagnostics.png) | [slices](visuals/adaptive_v3/20260205190000_centralized_stage4_slices.png) / [diag](visuals/adaptive_v3/20260205190000_centralized_stage4_diagnostics.png) | [slices](visuals/tp26_thr11_preserve/20260205190000_centralized_stage4_slices.png) / [diag](visuals/tp26_thr11_preserve/20260205190000_centralized_stage4_diagnostics.png) |
| `20260216015400` | 中高误差帧，adaptive 类方法略优 | 32.7135 | 28.9648 | 29.0054 | [slices](visuals/baseline_aircraft/20260216015400_centralized_stage4_slices.png) / [diag](visuals/baseline_aircraft/20260216015400_centralized_stage4_diagnostics.png) | [slices](visuals/adaptive_v3/20260216015400_centralized_stage4_slices.png) / [diag](visuals/adaptive_v3/20260216015400_centralized_stage4_diagnostics.png) | [slices](visuals/tp26_thr11_preserve/20260216015400_centralized_stage4_slices.png) / [diag](visuals/tp26_thr11_preserve/20260216015400_centralized_stage4_diagnostics.png) |
| `20260126090000` | 接近 6 m/s 边界；adaptive_v3 最好，tp26 略回退但仍优于 baseline | 5.9990 | 2.2302 | 2.4497 | [slices](visuals/baseline_aircraft/20260126090000_centralized_stage4_slices.png) / [diag](visuals/baseline_aircraft/20260126090000_centralized_stage4_diagnostics.png) | [slices](visuals/adaptive_v3/20260126090000_centralized_stage4_slices.png) / [diag](visuals/adaptive_v3/20260126090000_centralized_stage4_diagnostics.png) | [slices](visuals/tp26_thr11_preserve/20260126090000_centralized_stage4_slices.png) / [diag](visuals/tp26_thr11_preserve/20260126090000_centralized_stage4_diagnostics.png) |
| `20260223133000` | 高误差 multi-holdout 长尾压力测试 | 117.2358 | 109.8872 | 109.6927 | [slices](visuals/baseline_aircraft/20260223133000_centralized_stage4_slices.png) / [diag](visuals/baseline_aircraft/20260223133000_centralized_stage4_diagnostics.png) | [slices](visuals/adaptive_v3/20260223133000_centralized_stage4_slices.png) / [diag](visuals/adaptive_v3/20260223133000_centralized_stage4_diagnostics.png) | [slices](visuals/tp26_thr11_preserve/20260223133000_centralized_stage4_slices.png) / [diag](visuals/tp26_thr11_preserve/20260223133000_centralized_stage4_diagnostics.png) |

看图时建议按同一帧横向比较三组 `slices.png`。灰白区域是 outside recon_mask / no wind claim，不是零风；橙色框是 ROI 裁剪范围；`diagnostics.png` 用来看有效重构、低置信补全、垂直结构和强风诊断。

## 5. 文件夹内容

```text
README.md
aircraft_only_literature_positioning.md
stage1_to_stage4_pipeline.md
recon/
  baseline_aircraft/        full NPZ + point_eval + method markdown
  adaptive_v3/
  tp26_thr11_preserve/
visuals/
  baseline_aircraft/        6 frames slices/diagnostics PNG
  adaptive_v3/
  tp26_thr11_preserve/
tables/
  three_method_200_frame_summary.csv
  timepower15_vs_adaptive_v3_summary.csv
  tp25_vs_tp26_summary.csv
  representative_frames_selected.csv
```

## 6. 口头展示建议

1. 先讲验证边界：truth 只有 aircraft wind holdout，motion/location 不当风，CMA/GFS/ERA 不当 truth。
2. 再讲方法演进：`baseline_aircraft` 是宽核经验重构；`adaptive_v3` 加入诊断加权、非泄漏核选择和 3DVAR proxy；`tp26` 再加强时间衰减和垂直结构保护。
3. 然后讲指标：baseline 到 tp26，weighted RMSE 下降约 21.9%，P95 下降约 34.4%。
4. 最后讲限制：极端长尾还没有根治，例如 `20260205190000` 和 `20260223133000`；下一步应做更大 holdout-only 验证和 per-point support-aware localization。

## 7. 两个基础概念：u/v 与 radar PNG

### 7.1 u/v 的意义

`u/v` 是水平风矢量的两个正交分量，不是两个不同的风场。

```text
u = east-west component
v = north-south component
```

在本项目里约定：

```text
u > 0：风向东吹
u < 0：风向西吹
v > 0：风向北吹
v < 0：风向南吹
```

航空气象里常见的 `wind_dir / wind_speed` 表示“风从哪里来”。因此 Stage1 把风向风速转成 `u/v` 时使用：

```text
u_wind = -wind_speed * sin(wind_dir*pi/180)
v_wind = -wind_speed * cos(wind_dir*pi/180)
```

例子：

```text
wind_dir = 270 deg  表示西风，从西向东吹
所以 u_wind 为正
```

Stage4 评估误差时也在 `u/v` 上比较：

```text
u_error = pred_u - gt_u
v_error = pred_v - gt_v
vector_error = sqrt(u_error^2 + v_error^2)
```

注意：`location` 里的 `u_motion/v_motion` 是飞机地面运动分量，不是大气风。只有 AMDAR/TURB 里的 `u_wind/v_wind` 才能作为 aircraft wind observation。

### 7.2 radar PNG 为什么要这样处理

当前 radar PNG 是二维雷达/云图拼图强度，不是 Doppler 径向速度。因此它在本项目里只作为背景 context 和可视化底图：

```text
radar PNG intensity = cloud/radar echo context
radar PNG intensity != wind speed
radar PNG intensity != wind direction
radar PNG intensity != Doppler radial velocity
```

Stage2 对 radar PNG 的处理是：

```text
1. 从 radar_index.json 读取 radar_path
2. 用 OpenCV 按灰度图读取 PNG
3. 下采样到 Stage2 水平网格
4. 存成 cloud_2d
```

这样处理的原因：

| 处理 | 目的 |
| --- | --- |
| 灰度读取 | 保留雷达/云图强度，不引入颜色表误差。 |
| 下采样 | 与 Stage2 的 `31 x 525 x 775` 三维体素网格对齐，减少计算量。 |
| 只存 `cloud_2d` | 明确它只是二维背景层，不是三维风观测。 |
| 不进 official truth | 防止把雷达回波强度误当风速/风向。 |

所以不用 radar PNG 也能做 aircraft-only 重构；只是少了天气结构背景和可视化底图。真正参与 Stage4 风场重构的是：

```text
train_current_wind = wind_records - holdout
context_wind_records
obs_conf / time_conf / localization / diagnostic weighting
```

## 8. 参考文献与借用边界

- WMO Aircraft-Based Observations Programme, https://wmo.int/aircraft-based-observations-programme
  借用点：aircraft wind observations 是正式气象观测来源；本项目据此把 aircraft `wind_records` 作为 strict holdout truth。
- de Haan and Stoffelen (2016), AMT, https://amt.copernicus.org/articles/9/4141/2016/
  借用点：aircraft-derived wind 有明确观测误差和 QC 问题；本项目只把 sigma 当观测误差参考，不把它当 Stage4 重构 RMSE 目标。
- EMADDC aircraft weather observations and quality control (2025), AMT, https://amt.copernicus.org/articles/18/3341/2025/
  借用点：业务 aircraft wind 需要质量控制和误差分层；本项目用来支持 diagnostic weighting / obs-error diagnostic 的解释。
- Gaspari and Cohn (1999) / DART covariance localization docs, https://docs.dart.ucar.edu/en/latest/assimilation_code/modules/assimilation/cov_cutoff_mod.html
  借用点：空间 localization / covariance tapering；本项目从固定宽核 baseline 走向 adaptive localization。
- PyDDA / 3DVAR wind retrieval, https://openradarscience.org/PyDDA/
  借用点：观测约束、平滑约束、弱散度/物理约束共同塑造三维风场；本项目实现的是 aircraft-observation proxy，不是真 Doppler radar retrieval。
- Desroziers et al. (2005), https://doi.org/10.1256/qj.05.108
  借用点：用 observation/background departure diagnostics 调整观测与背景权重；本项目用这个思想解释 context time decay 的微调。
- Janjic et al. (2018), https://doi.org/10.1002/qj.3130
  借用点：representation error；本项目把 aircraft 点观测与 500 m 网格/6 min 窗口之间的误差从 aircraft observation error 中分离出来解释。
- Perona and Malik (1990), https://doi.org/10.1109/34.56205
  借用点：edge-preserving / gradient-preserving smoothing；本项目的 `preserve_strong_layers` 用来降低强垂直结构被跨层平滑抹掉的风险。

## 9. 2026-06-05 新增 demo 结论

新增输出：

```text
centralized_v1_output/stage4_dynamic_layer_nwp_oi_demo_20260605/
```

25 个抽样 frame、25 路并行、58 个 strict holdout 点：

| branch | RMSE | MAE | P95 | 结论 |
| --- | ---: | ---: | ---: | --- |
| aircraft-only fixed vertical loc | 26.589947 | 9.812196 | 40.764004 | 当前小样本最稳。 |
| aircraft-only support_adaptive vertical loc | 26.742449 | 9.876736 | 39.704757 | P95 略好，但总 RMSE/MAE 变差，暂不升主线。 |
| aircraft + weak CMA background 0.03 | 26.745099 | 9.905763 | 40.764000 | 弱背景未超过 aircraft-only。 |
| aircraft + very weak CMA background 0.01 | 26.639229 | 9.839657 | 40.764003 | 接近 aircraft-only，但仍未超过。 |

结论：动态垂直 localization 和 weak CMA/NWP background 都值得继续做分层触发实验，但当前不能替代 `tp26_thr11_preserve` aircraft-only strict holdout 主线。全国重构可以作为 product footprint；validated accuracy 只能写在 aircraft holdout 覆盖到的局部时空点上。

## 9. 2026-06-05 guardrail/reporting 固化

正式 promotion checklist 已写入 pairwise：

```text
truth_speed_bin
relative_error_ratio
floor10_relative_error
direction_error_deg
```

候选必须同时满足：

```text
strict_holdout_no_leakage == True
motion_used_as_wind == False
weighted RMSE / P95 / P99 不劣化
12km+ vector RMSE 不劣化
5-15mps_light vector RMSE/MAE 不劣化
overall floor10_relative_error_mae 不劣化
light/moderate wind 中 relative_error_ratio > 2 且 delta_vector_error > 5 m/s 直接 FAIL
```

200 帧、25 worker 输出：

```text
centralized_v1_output/stage4_guardrail_display_fill_200_20260605_25w/
```

checklist：

```text
analysis/tp26_existing_vs_rerun/tp26_existing_vs_rerun_promotion_checklist.md
analysis/tp26_vs_srha_formal_guardrail/tp26_vs_srha_formal_guardrail_promotion_checklist.md
analysis/tp26_vs_sparse_temporal_cma_formal_guardrail/tp26_vs_sparse_temporal_cma_formal_guardrail_promotion_checklist.md
```

结果：

```text
tp26 existing vs rerun: PASS
tp26 vs SRHA: FAIL
tp26 vs sparse-temporal CMA: FAIL
```

display-filled 是展示层补全：

```text
stage4_display_* = official tp26 where recon_mask true + low-confidence weak background elsewhere
official recon_u/v/conf/mask unchanged
CMA/background not used as strict holdout truth
display_fill_is_official_accuracy = False
```

代表帧图和风速/风向差异表：

```text
centralized_v1_output/stage4_guardrail_display_fill_200_20260605_25w/representative_display_filled_visuals/
centralized_v1_output/stage4_guardrail_display_fill_200_20260605_25w/representative_display_filled_visuals/representative_wind_speed_direction_table.md
```

observation-error 口径：

```text
de Haan / EMADDC sigma 只作为 aircraft wind observation-error prior 或 QC 诊断权重。
13.64 m/s 是 local consistency / representativeness sigma，不是飞机风观测误差。
sigma 不能从 Stage4 RMSE/MAE 里扣。
u_motion/v_motion 是 aircraft ground motion，不是 wind。
```
