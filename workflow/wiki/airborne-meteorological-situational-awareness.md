---
tags: [concept]
type: concept
---

# Airborne meteorological situational awareness

机载气象态势感知指航空器在运行过程中，对周边天气系统、风场和潜在风险环境形成实时、可行动的理解能力。

## 在这批资料中的含义

- 它不是单一传感器能力，而是“观测 -> 重建 -> 预测 -> 协同共享”的系统能力。
- 对自主运行航空器来说，感知质量直接影响路径规划、安全间隔维持和运行鲁棒性。
- 单机机载雷达难以覆盖复杂空域，因此需要与重建模型、地面服务、协同感知机制结合。

## 支撑它的几类能力

- **局部场重建**：[[wind-field-reconstruction|Wind field reconstruction]] 让不完整观测变成更完整的场信息。
- **飞机观测供给**：[[aircraft-derived-meteorological-observations|Aircraft-derived meteorological observations]] 提供更高时效的上空观测来源。
- **全局预报能力**：[[ai-medium-range-weather-forecasting|AI medium-range weather forecasting]] 提供更长 lead time 的背景场。
- **机群协同共享**：[[multi-aircraft-collaborative-perception|Multi-aircraft collaborative perception]] 解决受限通信下的共享与融合问题。

## 新补充的方法启发

- [[where2comm|Where2comm]] 表明，协同感知未必需要传输完整天气场或完整特征图，而可以只交换高价值空间区域。
- 这对航空场景尤其重要，因为强对流、危险回波和局地风切变本身就是空间异质、风险高度集中的信息。

## 当前主要瓶颈

- 单机感知范围有限。
- 通信资源和融合时延限制多机协同效果。
- 局部高分辨率感知和大尺度中期预报之间仍需桥接层。

## 来源

- [[source-multi-aircraft-collaborative-situational-awareness|面向自主运行的多机态势智能协同感知方法研究]]
- [[source-vision-mamba-incomplete-wind-data|Wind Field Reconstruction Method Using Incomplete Wind Data Based on Vision Mamba Decoder Network]]
- [[source-emaddc-mode-s-ehs-observations|EMADDC: high-volume, high-quality, and timely wind and temperature observations from aircraft surveillance data (Mode-S EHS)]]
- [[source-pangu-weather-3d-neural-networks|Accurate medium-range global weather forecasting with 3D neural networks]]
- [[source-fuxi-15-day-global-weather-forecast|FuXi: a cascade machine learning forecasting system for 15-day global weather forecast]]
- [[source-fengwu-extended-medium-range-forecast|The operational medium-range deterministic weather forecasting can be extended beyond a 10-day lead time]]
- [[source-where2comm-spatial-confidence-maps|Where2comm: Communication-Efficient Collaborative Perception via Spatial Confidence Maps]]
