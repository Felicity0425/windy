# Wiki 索引

> 这是知识库的内容目录。每次 ingest 后更新。查询时先读这里，再深入具体页面。

## 资料摘要

| 页面 | 说明 | 来源日期 |
|------|------|---------|
| [Mode-S EHS wind observation errors](source-mode-s-ehs-wind-observation-errors.md) | 用 triple collocation 评估飞机衍生风观测误差，为业务应用建立可信性前提 | 2016-08-30 |
| [EMADDC Mode-S EHS observations](source-emaddc-mode-s-ehs-observations.md) | 介绍欧洲业务系统如何把监视数据批量转成高质量风温观测 | 2025-07-22 |
| [Dual-Doppler variational wind field](source-dual-doppler-variational-wind-field.md) | 用三维变分和 Poisson 方程从双多普勒雷达恢复三维风场 | 2022-01-12 |
| [Practical flow field reconstruction with PINN](source-practical-flow-field-reconstruction-pinn.md) | 展示 PINN 在极稀疏或局部缺失数据下的流场恢复能力 | 2022-11-14 |
| [LiDAR multi-scale PINN wind field reconstruction](source-lidar-multiscale-pinn-wind-field-reconstruction.md) | 用多尺度 PINN 从真实约束 LiDAR 测量中恢复三维时空风场 | 2025-01-01 |
| [Dynamic wake PINN with sparse LiDAR](source-dynamic-wake-pinn-sparse-lidar.md) | 用 PINN 重建风机偏航条件下的动态尾流场 | 2024-03-15 |
| [Vision Mamba incomplete wind data](source-vision-mamba-incomplete-wind-data.md) | 用 Vision Mamba Decoder 从航路缺测风数据重建完整风场 | 2024-09-25 |
| [Pangu-Weather 3D neural networks](source-pangu-weather-3d-neural-networks.md) | 以三维神经网络实现强于 ECMWF IFS 的中期全球天气预报 | 2023-07-05 |
| [FuXi 15-day global weather forecast](source-fuxi-15-day-global-weather-forecast.md) | 用级联模型把 AI 全球天气预报推进到 15 天 | 2023-11-16 |
| [FengWu extended medium-range forecast](source-fengwu-extended-medium-range-forecast.md) | 用多模态多任务和 replay buffer 延展 10 天以上的业务级预报 | 2025-07-03 |
| [Multi-aircraft collaborative situational awareness](source-multi-aircraft-collaborative-situational-awareness.md) | 在受限通信条件下实现多机气象态势协同感知 | 2025-06-10 |
| [Where2comm spatial confidence maps](source-where2comm-spatial-confidence-maps.md) | 用空间置信图在协同感知中选择真正值得通信的空间区域 | 2022-10-31 |

## 实体

| 页面 | 说明 |
|------|------|
| [Mode-S EHS](mode-s-ehs.md) | 可从飞机监视数据推断风温信息的关键观测来源 |
| [EMADDC](emaddc.md) | 欧洲业务化飞机衍生气象观测处理系统 |
| [Pangu-Weather](pangu-weather.md) | 3D 神经网络中期全球天气预报系统 |
| [FuXi](fuxi.md) | 面向 15 天预报的级联 AI 天气系统 |
| [FengWu](fengwu.md) | 多模态、多任务并带集合扩展的中期全球天气预报系统 |
| [Where2comm](where2comm.md) | 以空间置信图为核心的通信高效协同感知框架 |

## 概念

| 页面 | 说明 |
|------|------|
| [Aircraft-derived meteorological observations](aircraft-derived-meteorological-observations.md) | 利用飞机监视或机载数据反演风温等气象观测的业务方向 |
| [Airborne meteorological situational awareness](airborne-meteorological-situational-awareness.md) | 面向自主运行航空器的机载气象环境理解能力 |
| [AI medium-range weather forecasting](ai-medium-range-weather-forecasting.md) | 10 到 15 天量级全球 AI 天气预报方法群 |
| [Multi-aircraft collaborative perception](multi-aircraft-collaborative-perception.md) | 多机在通信受限下共享与融合气象态势信息的方法 |
| [Physics-informed neural network (PINN)](physics-informed-neural-network.md) | 把物理方程残差嵌入训练过程的稀疏观测重建方法 |
| [Spatial confidence map](spatial-confidence-map.md) | 对空间位置感知价值进行评分并驱动选择性通信的表示 |
| [Wind field reconstruction](wind-field-reconstruction.md) | 从稀疏或不完整观测恢复完整风场的核心问题 |

## 工作流

| 页面 | 说明 |
|------|------|
| _暂无_ | - |

## 综合分析

| 页面 | 说明 |
|------|------|
| [Aviation weather intelligence analysis](aviation-weather-intelligence-analysis.md) | 把观测、重建、预报和协同感知串成一条完整航空气象智能链路 |
