# Aircraft-only / sparse-observation 风场重构文献定位与 tp26 说辞

本文用于回答老师可能追问的几个问题：

```text
1. 只有 AMDAR / TURB / location，能不能做风场重构？
2. 现在到底有没有人做 aircraft-only / sparse aircraft observation reconstruction？
3. 我的 tp26 和文献方法相比怎么样？
4. tp26 是不是要被抛弃？
5. 下一步应该怎么把文献方法接进来？
```

核心口径先固定：

```text
本项目不是完整业务级 NWP / Doppler radar retrieval。
本项目是 aircraft-supported sparse-observation 3D wind reconstruction。
official truth 只使用 current aircraft wind_records strict holdout。
location/motion 不是 wind truth。
TURB 只有在包含 wind_dir/wind_speed 时才能作为 wind observation；若只是 EDR/turbulence，则只能做风险/质量诊断。
tp26_thr11_preserve 不是终点，但必须保留为当前最强 aircraft-only baseline。
```

## 1. 本项目现在到底站在哪个赛道

本项目最准确的研究定位是：

```text
稀疏航空器观测条件下的 aircraft-only 三维风场局地重构。
```

不要把它说成：

```text
完整三维真实风场分析系统
运行级低空风切变预警系统
NWP 4DVar / EnKF 同化系统
Doppler radar wind retrieval
全国全域强对流风场反演
```

原因是当前数据条件只有：

| 数据 | 能做什么 | 不能做什么 |
| --- | --- | --- |
| AMDAR | 直接提供 aircraft wind、时间、位置、高度；可以作为 Stage4 truth/anchor/holdout。 | 稀疏，只在航路附近；不能覆盖完整三维大气。 |
| TURB | 如果包含 `wind_dir/wind_speed`，可作为 aircraft wind；如果只是 EDR/turbulence，只能做湍流风险和质量诊断。 | 单纯 turbulence 不能当 `u/v` 风真值。 |
| location | 提供轨迹覆盖、飞机运动、时空支撑诊断。 | 如果没有 true airspeed / Mach / air vector，不能单独反推 atmospheric wind。 |
| radar PNG | 只提供 cloud/radar intensity context 和可视化底图。 | 不是 Doppler radial velocity，不能当 wind truth。 |

因此，最公平的对标对象不是 ECMWF/WRF/COSMO 这类完整同化系统，而是：

```text
nearest / time-weighted aircraft wind
Barnes / Cressman / OI
Kriging / Gaussian Process Regression
aircraft-surveillance weather field reconstruction
incomplete air-route wind reconstruction
```

## 2. 现在谁在做类似方向

### 2.1 TU Delft / OpenSky / pyModeS：aircraft surveillance weather field reconstruction

最接近本项目的文献：

```text
Sun, Vû, Ellerbroek, Hoekstra (2018)
Weather field reconstruction using aircraft surveillance data and a novel meteo-particle model
PLOS ONE
https://doi.org/10.1371/journal.pone.0205029
```

它做的是：

```text
ADS-B / Mode-S aircraft surveillance data
-> aircraft-derived wind / temperature observations
-> Meteo-Particle model
-> real-time weather grid reconstruction
```

可借用内容：

| 文献思想 | 本项目对应 |
| --- | --- |
| aircraft 是 moving sensors | AMDAR/TURB wind 是移动稀疏风观测。 |
| 航路上观测密集，航路外稀疏 | 本项目 `recon_mask` 只声明 aircraft-supported 区域，不声称全域有真风。 |
| 观测会随距离、时间、同质性衰减 | 本项目 `obs_conf`, `time_conf`, localization, diagnostic weighting。 |
| sparse observations 可重构 weather field | 支撑本项目 aircraft-only reconstruction 方向。 |

不能照搬的地方：

```text
该文使用 ADS-B / Mode-S derived observations，数据状态比本项目 location 更完整。
它不是 current aircraft wind strict holdout 评价。
它的 MAE 不能和本项目 weighted RMSE 直接硬比。
```

### 2.2 GPR / Kriging：aircraft-derived wind profile / velocity field estimation

适合作为本项目下一步 baseline 的文献：

```text
On the Estimation of Vector Wind Profiles Using Aircraft-Derived Data and Gaussian Process Regression
Aerospace, 2022
https://www.mdpi.com/2226-4310/9/7/377
```

它做的是：

```text
aircraft-derived wind observations
-> Gaussian Process Regression
-> vector wind profile nowcast
```

论文报告的典型结果：

```text
GPR wind speed RMSE = 3.0 m/s
GPR wind speed MAE  = 2.2 m/s
```

适合作为本项目的：

```text
GPR_profile_baseline
local_Kriging_baseline
airport / route-local wind-profile baseline
```

边界：

```text
它主要是局地 wind profile，不是全国 31 x 525 x 775 三维网格。
它使用 aircraft-derived wind，通常需要比普通 location 更完整的 aircraft state。
```

另一个 GPR 相关文献：

```text
Polynomial Chaos Expansion-Based Enhanced Gaussian Process Regression for Wind Velocity Field Estimation from Aircraft-Derived Data
Mathematics, 2023
https://www.mdpi.com/2227-7390/11/4/1018
```

该文报告：

```text
observation split:
  u/v RMSE ~= 1.464 / 2.262 m/s
  u/v MAE  ~= 0.830 / 1.172 m/s

flight split:
  u/v RMSE ~= 4.790 / 6.057 m/s
  u/v MAE  ~= 3.447 / 4.459 m/s

short-term prediction:
  u/v RMSE ~= 5.162 / 6.367 m/s
  u/v MAE  ~= 3.931 / 4.400 m/s
```

这个对本项目最有用的点是：**split by flight / short-term prediction 已经不再是特别轻松的随机点切分，其误差量级和本项目普通帧 frame RMSE 更接近。**

### 2.3 Incomplete air-route wind data reconstruction：航路不完整风数据补全

和本项目名字很接近的文献：

```text
Wind Field Reconstruction Method Using Incomplete Wind Data Based on Vision Mamba Decoder Network
Aerospace, 2024
https://www.mdpi.com/2226-4310/11/10/791
```

它的任务是：

```text
incomplete wind data distributed along air routes
-> complete wind field reconstruction
```

论文报告：

```text
wind speed MAE  ~= 1.83 m/s
wind speed RMSE ~= 2.87 m/s
wind direction MAE ~= 5.78 deg
```

适合引用它证明：

```text
“航路稀疏风数据重构完整风场”这个问题有人做。
```

但比较时必须谨慎：

```text
该类 deep-learning reconstruction 往往需要 ERA5 或完整风场样本构造训练标签。
本项目当前没有完整三维真值，只能使用 aircraft strict holdout。
因此不能把它的 1-3 m/s 结果直接拿来压本项目。
```

### 2.4 EMADDC / KNMI：从 aircraft surveillance 生产高质量 wind observations

文献：

```text
EMADDC aircraft weather observations and quality control
Atmospheric Measurement Techniques, 2025
https://amt.copernicus.org/articles/18/3341/2025/
```

它不是重构方法，而是 aircraft-derived weather observations 的业务化数据来源。

可借用内容：

```text
aircraft surveillance data 可以生成 wind speed / wind direction / temperature observations。
这些 observations 需要完整 QC、heading correction、误差分层。
```

本项目对应：

```text
diagnostic_weighted
speed QC
local consistency
obs-error diagnostic
```

边界：

```text
EMADDC 说明 aircraft-derived wind 可用，但也说明必须 QC。
不能把 location/motion 直接当 wind truth。
```

### 2.5 Mode-S / AMDAR assimilation：证明 aircraft observations 有价值，但不是直接对标

文献：

```text
de Haan and Stoffelen (2012)
Assimilation of High-Resolution Mode-S Wind and Temperature Observations in a Regional NWP Model for Nowcasting Applications
https://doi.org/10.1175/WAF-D-11-00088.1

Lange and Janjic (2016)
Assimilation of Mode-S EHS Aircraft Observations in COSMO-KENDA
https://doi.org/10.1175/MWR-D-15-0112.1

Petersen (2016)
On the Impact and Benefits of AMDAR Observations in Operational Forecasting
https://doi.org/10.1175/BAMS-D-14-00055.1

Cardinali, Isaksen, Andersson (2003)
Use and Impact of Automated Aircraft Data in a Global 4DVAR Data Assimilation System
https://doi.org/10.1175/1520-0493(2003)131%3C1865:UAIOAA%3E2.0.CO;2
```

这些文献说明：

```text
aircraft wind observations 对 NWP 分析/预报有价值。
```

但它们有 NWP 背景场、同化循环、背景误差协方差，所以不能和本项目 aircraft-only 方法直接硬比。

## 3. 本项目 tp26 和文献结果的数值对比

当前本项目展示包结果：

```text
method = tp26_thr11_preserve
frames = 200
holdout points = 530
frame RMSE = 8.2243 m/s
frame MAE  = 7.0819 m/s
weighted RMSE = 14.7690 m/s
weighted MAE  = 6.8545 m/s
P95 RMSE = 27.9861 m/s
P99 RMSE = 58.7838 m/s
max RMSE = 109.6927 m/s
truth = current aircraft wind_records strict holdout
```

来源：

```text
centralized_v1_output/stage4_teacher_showcase_20260602_baseline_adaptive_v3_tp26/README.md
```

横向对比表：

| 方法/论文 | 任务 | 文献指标 | 本项目对比 | 是否公平 |
| --- | --- | ---: | --- | --- |
| Sun et al. 2018 Meteo-Particle | aircraft surveillance weather field reconstruction | wind MAE 约 `1.3 m/s` | 本项目 weighted MAE `6.85 m/s` 明显更高。 | 不完全公平：对方有 ADS-B/Mode-S derived observations，评价不是 current aircraft strict holdout。 |
| GPR wind profile 2022 | aircraft-derived vector wind profile | wind speed RMSE `3.0 m/s`, MAE `2.2 m/s` | 本项目 frame RMSE `8.22`, weighted RMSE `14.77` 更高。 | 不完全公平：对方是局地 profile，不是全国 3D sparse grid。 |
| PCE-GPR 2023 flight split | aircraft-derived wind velocity field | u/v RMSE `4.79/6.06 m/s` | 若换成 vector 量级，约 `7-9 m/s`，与本项目 frame RMSE `8.22` 接近。 | 较公平：都是 aircraft-derived sparse wind，但对方数据状态可能更完整。 |
| PCE-GPR 2023 short-term prediction | short-term wind field prediction | u/v RMSE `5.16/6.37 m/s` | vector 量级仍接近本项目 frame RMSE，但低于本项目 weighted RMSE。 | 较公平。 |
| Vision Mamba 2024 | incomplete air-route wind -> complete wind field | wind speed RMSE `2.87 m/s`, MAE `1.83 m/s` | 本项目明显更差。 | 不公平：深度学习方法通常有 ERA5/完整风场标签，本项目没有完整三维 truth。 |

## 4. 对比结论

严谨结论：

```text
本项目 tp26 在普通 frame-level RMSE 上，已经接近部分 flight-split / short-term aircraft-derived wind estimation 文献的 vector error 量级。
但本项目在 holdout-point weighted RMSE、P95、P99 和 max error 上明显落后。
差距主要来自长尾点，而不是所有帧都完全失败。
```

可以对老师说：

> 与 aircraft-derived wind field reconstruction 文献相比，`tp26_thr11_preserve` 的 frame-level RMSE 已接近部分 PCE-GPR flight-split / short-term prediction 的 vector error 量级；但 holdout-point weighted RMSE 和 P95/P99 长尾仍显著偏高。主要原因是本项目数据条件更弱，没有 Mode-S EHS true airspeed/Mach、没有 ERA5 完整监督标签，也没有 NWP 背景场作为 truth；同时采用 current aircraft wind strict holdout，评价更严格。因此下一步不应继续小范围调参，而应引入 GPR/Kriging、OI/3DVAR weak-background 和 support-aware localization 等文献 baseline，专门治理长尾误差。

## 5. tp26 是否被抛弃

结论：

```text
tp26 不被抛弃。
tp26 应从“候选最终方法”降级为“当前最强 aircraft-only strict baseline / 主干基础场”。
```

tp26 的正确定位：

| 角色 | 是否保留 | 原因 |
| --- | --- | --- |
| 当前展示包最佳候选 | 保留 | 200 帧 strict holdout 中优于 baseline/adaptive_v3。 |
| aircraft-only 主线 baseline | 必须保留 | 它是目前最干净的 aircraft-only 对照组。 |
| 后续方法基础场 | 可以保留 | 可作为 residual refine / weak-background compare 的 starting point。 |
| 最终论文级最强方法 | 暂时不能这么说 | weighted RMSE 和长尾仍过大。 |
| 无限继续微调 tp 参数 | 不建议 | tp24 -> tp26 的增益已经很小。 |

老师版说法：

> `tp26_thr11_preserve` 不是失败结果，而是当前 aircraft-only strict holdout 条件下的最佳内部基线。它证明 adaptive localization、时间衰减和垂直结构保护有效。但与 aircraft-derived wind reconstruction 文献相比，长尾误差仍偏大，因此后续会把 tp26 作为主干基础场，与 GPR/OI/3DVAR weak-background 方法进行公平比较，而不是直接丢弃。

## 6. 为什么不用别人的方法直接做

可以用别人的思想，但不能原样搬。

| 文献方法 | 不能直接搬的原因 | 本项目应该怎么借 |
| --- | --- | --- |
| Mode-S / ADS-B derived wind | 需要 true airspeed / Mach / heading / track 等完整 aircraft state。 | 如果 location 有足够 air-data，可尝试 derived wind；否则 location 只做 coverage/motion diagnostics。 |
| PyDDA / Doppler retrieval | 需要 Doppler radial velocity，radar PNG intensity 不够。 | 借观测约束、平滑约束、弱散度约束，做 proxy refine。 |
| NWP 4DVar / EnKF | 需要完整背景场、误差协方差和循环同化系统。 | 借 OI/3DVAR background + innovation 思想，用 CMA/GFS/ERA 作 weak background，不当 truth。 |
| Deep learning complete wind reconstruction | 通常需要 ERA5/完整风场标签训练。 | 只能作为后续 residual / uncertainty route，不能现在替代 strict holdout。 |
| GPR / Kriging | 可以直接做，但要处理规模和局地化。 | 最适合作为下一步 baseline。 |

## 7. 下一步最应该做什么

不要继续只在 `tp26` 附近微调。下一步应该做一个正式的 literature-baseline comparison：

```text
stage4_aircraft_only_literature_baselines_202606xx
```

建议方法：

| 方法 | 意义 |
| --- | --- |
| `nearest_current_wind` | 最朴素 baseline：最近 current train wind。 |
| `time_weighted_context_wind` | 只用 context + time decay。 |
| `barnes_cressman_oi` | 文献级传统稀疏观测插值 baseline。 |
| `local_gpr_profile` | 对标 GPR wind profile 文献。 |
| `tp26_thr11_preserve` | 当前最强 aircraft-only baseline。 |
| `tp26_plus_support_aware_localization` | 专门处理长尾和稀疏支撑。 |
| `tp26_plus_cma_weak_background` | 只把 CMA/GFS/ERA 当 background，不当 truth。 |

评价方式保持不变：

```text
truth = current aircraft wind_records strict holdout
holdout removed before fusion
motion/location not wind
CMA/GFS/ERA not truth
no-holdout not official RMSE/MAE
```

关键分层：

```text
frame RMSE / MAE
holdout-point weighted RMSE / MAE
P90 / P95 / P99 / max
single-holdout vs multi-holdout
height bins
support count bins
context age bins
vertical mismatch subset
role conflict subset
```

如果下一步只选一句路线：

```text
保留 tp26 作为 aircraft-only 主干 baseline，
补 GPR/OI 两个文献 baseline，
再做 support-aware localization 专门压 P95/P99 长尾。
```

## 8. 答辩问答模板

### Q1：只有 AMDAR/TURB/location，是不是和别人比不了？

答：

> 不能和完整 NWP / Doppler radar retrieval 系统硬比，但可以和 aircraft-only / sparse aircraft-observation reconstruction 方法比较。本项目定位是数据受限条件下的 aircraft-supported 风场重构，不是完整业务级三维风场分析。

### Q2：既然别人能做到 1-3 m/s，为什么我们现在是 8-15 m/s？

答：

> 别人的低误差通常来自更完整的数据条件，例如 Mode-S EHS airspeed/Mach、ADS-B/Mode-S 高密度观测、ERA5 完整标签或 NWP 背景场。本项目当前只用 AMDAR/TURB/location，并采用 strict aircraft holdout。我们的普通 frame-level RMSE 已接近部分 flight-split aircraft-derived wind 文献的 vector error 量级，但 weighted RMSE 和 P95/P99 长尾仍需治理。

### Q3：tp26 是不是失败了？

答：

> 不是。tp26 是当前 aircraft-only strict holdout 下最好的内部基线，不能丢。它的问题是还不能作为最终最强方法，因为长尾误差过重。下一步应以 tp26 为 baseline，引入 GPR/OI/3DVAR weak-background 对照。

### Q4：location 能不能反推风？

答：

> 纯 location/motion 不能直接当 wind truth。只有当数据中有 true airspeed / Mach / heading / track 等完整 aircraft state 时，才能按 Mode-S/ADS-B derived wind 文献反推出风。当前如果缺少 air vector，location 只能作为轨迹覆盖和运动诊断。

### Q5：不用气象雷达拼图还能不能重构？

答：

> 可以。当前 Stage4 真正用于重构的是 aircraft wind_records 和 context_wind_records，雷达 PNG 只是 cloud/radar context 和可视化底图，不是 wind truth。不用雷达会降低天气结构解释性，但不会让 aircraft-only reconstruction 不能跑。

### Q6：时间格点缩小或放大有什么影响？

答：

> 时间格点缩小会增加帧数和连续性，但相邻帧会复用大量观测，不能把帧数当独立样本数。时间格点放大会让评估更独立、计算更轻，但可能漏掉短时变化并增加 no-holdout。当前建议保持 6 min 左右做展示/业务重构，严格评估时报告 point-weighted 和分层指标。

## 9. 参考文献

- Sun, J., Vû, H., Ellerbroek, J., Hoekstra, J. M. (2018). Weather field reconstruction using aircraft surveillance data and a novel meteo-particle model. PLOS ONE.  
  https://doi.org/10.1371/journal.pone.0205029
- On the Estimation of Vector Wind Profiles Using Aircraft-Derived Data and Gaussian Process Regression. Aerospace, 2022.  
  https://www.mdpi.com/2226-4310/9/7/377
- Polynomial Chaos Expansion-Based Enhanced Gaussian Process Regression for Wind Velocity Field Estimation from Aircraft-Derived Data. Mathematics, 2023.  
  https://www.mdpi.com/2227-7390/11/4/1018
- Wind Field Reconstruction Method Using Incomplete Wind Data Based on Vision Mamba Decoder Network. Aerospace, 2024.  
  https://www.mdpi.com/2226-4310/11/10/791
- EMADDC aircraft weather observations and quality control. Atmospheric Measurement Techniques, 2025.  
  https://amt.copernicus.org/articles/18/3341/2025/
- de Haan and Stoffelen (2012). Assimilation of High-Resolution Mode-S Wind and Temperature Observations in a Regional NWP Model for Nowcasting Applications.  
  https://doi.org/10.1175/WAF-D-11-00088.1
- Lange and Janjic (2016). Assimilation of Mode-S EHS Aircraft Observations in COSMO-KENDA.  
  https://doi.org/10.1175/MWR-D-15-0112.1
- Petersen (2016). On the Impact and Benefits of AMDAR Observations in Operational Forecasting.  
  https://doi.org/10.1175/BAMS-D-14-00055.1
- Cardinali, Isaksen, Andersson (2003). Use and Impact of Automated Aircraft Data in a Global 4DVAR Data Assimilation System.  
  https://doi.org/10.1175/1520-0493(2003)131%3C1865:UAIOAA%3E2.0.CO;2
