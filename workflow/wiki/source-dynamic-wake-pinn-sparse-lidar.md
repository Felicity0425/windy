---
tags: [source-summary, wind-field-reconstruction, pinn, lidar, wake]
source: "Dynamic wake field reconstruction of wind turbine through Physics-Informed Neural Network and Sparse LiDAR data"
author: Longyan Wang et al.
date: 2024-03-15
url: "https://doi.org/10.1016/j.energy.2024.130401"
---

# Dynamic wake field reconstruction of wind turbine through Physics-Informed Neural Network and Sparse LiDAR data

## 来源信息

- **本地原文**：[原始文稿](../raw/基于PINN和稀疏LiDAR数据的风力机动态尾流场重建/1-s2.0-S0360544224001725-main.md)
- **发表位置**：Energy, Volume 291
- **核心对象**：风机偏航场景下的动态尾流重建

## 核心观点

- 论文把稀疏 LiDAR 尾流观测与 Navier-Stokes 方程结合，使用 [[physics-informed-neural-network|PINN]] 重建动态尾流流场。
- 网络将时空坐标映射到速度和压力，重点研究偏航操作导致的尾流轨迹和偏转演化。
- 与只做插值或稳态预测的方法相比，这类物理约束方法更适合描述动态尾流变化。

## 关键结果

- 作者系统测试了扫描角度间隔、测点间距、采样频率和噪声水平变化下的鲁棒性。
- 方法既能在模拟数据上捕捉偏航期间的尾流演化趋势，也能在真实测量数据上有效重建流场。
- 论文将其定位为风场实时监测和偏航控制设计的数据基础。

## 注意事项

- 方法仍以局部尾流重建为主，距离整个风场的全局实时建模还有尺度扩展问题。
- 论文证明了实际 LiDAR 数据下的可用性，但工程部署仍取决于测量布设和实时优化能力。

## 相关概念

- [[wind-field-reconstruction|Wind field reconstruction]]
- [[physics-informed-neural-network|Physics-informed neural network (PINN)]]
