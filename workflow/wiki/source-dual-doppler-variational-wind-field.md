---
tags: [source-summary, wind-field-reconstruction, radar, variational-method]
source: "Three-Dimensional Wind Field Retrieved from Dual-Doppler Radar Based on a Variational Method: Refinement of Vertical Velocity Estimates"
author: Chenbin Xue et al.
date: 2022-01-12
url: "https://doi.org/10.1007/s00376-021-1035-9"
---

# Three-Dimensional Wind Field Retrieved from Dual-Doppler Radar Based on a Variational Method: Refinement of Vertical Velocity Estimates

## 来源信息

- **本地原文**：[原始文稿](../raw/基于变分法的双多普勒雷达三维风场反演与垂直速度优化/s00376-021-1035-9.md)
- **发表位置**：Advances in Atmospheric Sciences 39, 145–160
- **核心对象**：双多普勒雷达的三维风场反演

## 核心观点

- 论文提出两步式三维变分方案：先通过径向观测项和共轭梯度法恢复水平风场，再通过求解由质量连续方程推导的 Poisson 方程细化垂直速度。
- 相比传统双多普勒合成方法，它减少了“雷达观测 -> 分析网格”迭代过程中插值引入的误差。
- 这是 [[wind-field-reconstruction|Wind field reconstruction]] 中典型的“传统物理反演”路线，与 PINN 和 Vision Mamba 路线形成对照。

## 关键结果

- 论文指出该方法避免了额外的权重参数设定步骤。
- 相比 O'Brien 方法，对边界条件不确定性更不敏感，稳定性和可靠性更好。
- 在飑线过程中的真实雷达观测验证表明，反演出的垂直廓线、辐合辐散结构和上升/下沉气流与雷达观测一致。

## 注意事项

- 方法高度依赖雷达几何布设和观测条件。
- 与深度学习方法相比，它物理解释性强，但实时性和复杂场景泛化依赖数值求解链路。

## 相关概念

- [[wind-field-reconstruction|Wind field reconstruction]]
