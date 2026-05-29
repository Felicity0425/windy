---
tags: [source-summary, aviation, collaborative-perception, situational-awareness]
source: "面向自主运行的多机态势智能协同感知方法研究"
author: 方宇航
date: 2025-06-10
url: ""
---

# 面向自主运行的多机态势智能协同感知方法研究

## 来源信息

- **本地原文**：[原始文稿](../raw/面向自主运行的多机态势智能协同感知方法研究/8-ZY2202521-方宇航.md)
- **文献类型**：北京航空航天大学硕士学位论文
- **研究背景**：高密度空域下，自主运行航空器需要更强的机载气象态势感知能力

## 核心观点

- 单机机载气象雷达的感知范围有限，而地面气象服务又存在实时性和精度约束，因此需要 [[multi-aircraft-collaborative-perception|Multi-aircraft collaborative perception]]。
- 论文核心问题不是“能否共享数据”，而是在通信资源受限的条件下如何保证协同感知精度。
- 作者采用“协同感知建模 -> 高效深度网络设计 -> 真实数据仿真验证”的完整路线，构建了面向 [[airborne-meteorological-situational-awareness|Airborne meteorological situational awareness]] 的方法框架。

## 关键结果

- 构建了协同气象态势感知优化模型，联合优化关键态势信息传输策略和特征融合策略。
- 提出了基于深度学习的多机协同感知网络，通过时空感知置信度和飞行意图筛选关键通信区域，并构建动态稀疏通信图。
- 基于广州飞行情报区真实数据建立机载气象雷达回波数据集和验证环境，文中报告该方法在互信息、峰值信噪比、平均梯度等指标上优于先进协同算法。

## 注意事项

- 论文聚焦“感知融合与通信约束”而不是全流程天气预报，因此更靠近运行层和协同决策层。
- 它与风场重建、飞机观测和中期预报形成互补关系：前者提供局部/全局天气场，本文解决机群如何共享并利用这些信息。

## 相关概念

- [[airborne-meteorological-situational-awareness|Airborne meteorological situational awareness]]
- [[multi-aircraft-collaborative-perception|Multi-aircraft collaborative perception]]
