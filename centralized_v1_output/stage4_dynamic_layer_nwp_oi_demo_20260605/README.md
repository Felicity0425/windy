# Stage4 Dynamic Vertical Localization and Weak NWP Background Demo

日期：2026-06-05

本 demo 用同一组 25 个抽样 frame、25 路并行、同一 strict holdout 口径比较两件事：

1. 动态垂直 localization 是否比固定垂直分层更好。
2. OI / 3DVar-style 弱背景是否比 aircraft-only 更好。

共同评价边界：

```text
truth = current aircraft wind_records strict holdout
holdout 在融合前移除
CMA/GFS/ERA 只能作为 weak background / prior
location/motion 不作为 wind truth
radar PNG 不作为 Doppler wind
```

## Demo 配置

共同参数：

```text
stage2_summary = centralized_v1_output/stage2_full_v2/stage2_multimodal_summary.json
stage3_summary = centralized_v1_output/stage3_full_v2_25w_payload_only/stage3_center_summary.json
frame_times_file = centralized_v1_output/stage4_three_method_compare_20260531/analysis/frame_times_200_holdout_seed20260531.txt
sample_count = 25
sample_seed = 20260605
num_workers = 25
kernel = gaussian
param_grid = 8,4,2,1
confidence_mode = diagnostic_weighted
physics_constraint_mode = pydda_3dvar_proxy
localization_policy = diagnostic_adaptive_v3
localization_candidate_grid = 8:4,10:5
context_time_conf_power = 2.6
conflict_speed_threshold_mps = 11.0
vertical_risk_mode = preserve_strong_layers
```

本地没有发现可直接消费的 GFS/ERA ROI NPZ，所以 OI/3DVar-style demo 使用已有 CMA proxy/reanalysis 背景。代码和评价口径仍然按 weak NWP background 处理：背景只进 accumulator，不进 truth。

## 结果

点级 strict holdout 指标，58 个 holdout 点：

| branch | background | vertical loc | RMSE | MAE | P95 | max | leakage |
| --- | --- | --- | ---: | ---: | ---: | ---: | --- |
| `dynamic_fixed_aircraft_only` | off | fixed | 26.589947 | 9.812196 | 40.764004 | 180.131789 | ok |
| `dynamic_support_adaptive_aircraft_only` | off | support_adaptive | 26.742449 | 9.876736 | 39.704757 | 180.613923 | ok |
| `oi_weak_cma_background` | CMA weight 0.03 | fixed | 26.745099 | 9.905763 | 40.764000 | 180.159394 | ok |
| `oi_very_weak_cma_background` | CMA weight 0.01 | fixed | 26.639229 | 9.839657 | 40.764003 | 180.141075 | ok |

帧级平均 RMSE：

| branch | frame mean RMSE | frame P95 RMSE |
| --- | ---: | ---: |
| `dynamic_fixed_aircraft_only` | 10.763076 | 40.764004 |
| `dynamic_support_adaptive_aircraft_only` | 10.778750 | 39.704757 |
| `oi_weak_cma_background` | 10.832510 | 40.764000 |
| `oi_very_weak_cma_background` | 10.782844 | 40.764003 |

动态垂直 localization 的实际效果：

```text
fixed vertical sigma factor mean = 1.000000
support_adaptive vertical sigma factor mean = 0.865060
```

说明 `support_adaptive` 确实把垂直影响范围收窄了，尤其高空、强风、稠密观测或 stale context 条件下会更细。但这次 25-frame demo 中，它没有改善总 RMSE/MAE，只略微降低 P95。

弱 CMA 背景的实际效果：

```text
CMA active voxels mean = 7489.36
weight 0.03: RMSE/MAE 均变差
weight 0.01: 接近 aircraft-only，但仍未超过 aircraft-only
```

## 结论

1. 当前 official 主线暂时不建议把 `support_adaptive` 设为默认。它有减少垂直过平滑的迹象，但 strict holdout RMSE/MAE 没有改善。
2. 当前 OI/3DVar-style 弱 CMA 背景不能直接替代 aircraft-only。更稳妥的下一步是把 NWP background 限制在 sparse/no-current fallback 或按高度/区域/时间 conf 分层触发。
3. aircraft-only strict holdout 仍然是 official truth line。CMA/GFS/ERA 可以继续做背景分支，但必须用同一 holdout 点比较。
4. 这只是 25-frame demo，不是 200-frame 或 5614-frame 结论。任何默认参数切换必须再跑 200-frame strict holdout。

## 直接可对比的论文方向

| 文献方向 | 代表文献 | 能直接比较什么 | 不能直接比较什么 |
| --- | --- | --- | --- |
| aircraft surveillance weather-field reconstruction | Sun et al. 2018, Meteo-Particle Model | aircraft-derived wind -> local weather/wind grid；可做 MP/GPR 类 baseline | 他们常用 Mode-S/ADS-B 推风和 NWP/reanalysis 对比，不等同于本项目 current aircraft strict holdout |
| aircraft-derived wind GPR | Marinescu et al. 2022, PLOS ONE | GPR/Kriging 风场重构 baseline；很适合做下一步统计 baseline | 文献区域是局部 TMA，评价常对 ERA5，不是全国 current-wind holdout |
| Mode-S EHS observation error | de Haan 2016, AMT | aircraft wind 观测误差/QC/高度分层 sigma | 不能把文献 1-2 m/s 观测误差当成本项目重构 RMSE 目标 |
| EMADDC operational aircraft weather observations | de Haan et al. 2025, AMT | QC、误差分层、业务 aircraft observation pipeline | 不是本项目三维重构算法的直接 RMSE baseline |
| aircraft data in 4DVAR/NWP | Cardinali et al. 2003; Petersen 2016 | OI/3DVar/4DVar-style background+observation 思路 | 评价目标是 NWP analysis/forecast impact，不是本项目 holdout 点位重构 |

## 全国重构与局部 holdout 的口径

全国境内重构可以作为 product footprint；局部 holdout 只能证明局部观测支撑区的误差。不能说“全国范围都已被 strict holdout 验证”。

更合理的论文/答辩表述：

```text
本项目在全国网格上生成三维风场，但 official accuracy 只在 current aircraft wind_records strict holdout 覆盖到的时空点上报告。对全国无飞机覆盖区域，只报告 coverage/confidence/background diagnostics，不报告 validated RMSE。
```

下一步建议增加：

1. 按华北、华东、华南、西南、西北、东北分区统计 holdout。
2. 按高度层统计：0-3 km、3-6 km、6-9 km、9-12 km、12 km+。
3. 单独做 local-region paper baseline：选一个机场/TMA 或一个高密航路区域，与 Sun/Marinescu 这类局部论文对齐。
4. 全国产品继续保留，但全国 accuracy claim 只在 holdout coverage 足够的区域成立。
