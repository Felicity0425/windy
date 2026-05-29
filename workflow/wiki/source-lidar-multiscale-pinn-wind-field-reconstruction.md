---
tags: [source-summary, wind-field-reconstruction, pinn, lidar]
source: "Three-dimensional spatiotemporal wind field reconstruction based on LiDAR and multi-scale PINN"
author: Yuanqing Chen et al.
date: 2025-01-01
url: "https://doi.org/10.1016/j.apenergy.2024.124577"
---

# Three-dimensional spatiotemporal wind field reconstruction based on LiDAR and multi-scale PINN

## 来源信息

- **本地原文**：[原始文稿](../raw/基于LiDAR和多尺度PINN的三维时空风场重建/1-s2.0-S0306261924019603-main.md)
- **发表位置**：Applied Energy, Volume 377, Part C
- **核心对象**：基于 LiDAR 稀疏测量的三维时空风场重建

## 核心观点

- 论文使用多尺度 [[physics-informed-neural-network|Physics-informed neural network (PINN)]]，把 LiDAR 观测误差项和控制方程残差联合优化，用于三维时空 [[wind-field-reconstruction|Wind field reconstruction]]。
- 多尺度层的加入带来三个直接收益：捕获更宽尺度范围、重建扫描区域之外的流场、加快收敛。
- 对体积风场重建和风向不确定性场景，多个 LiDAR 的联合部署能明显改善结果。

## 关键结果

- 参考场来自中性大气边界层的大涡模拟（LES），测量策略约束为真实 LiDAR 扫描方式。
- 文中报告所有实验的归一化重建误差都低于 5%。
- 在典型 LiDAR 噪声水平下，误差没有明显劣化，说明方法对测量噪声具有一定鲁棒性。

## 注意事项

- 这是数值研究，主要验证了“物理约束 + 稀疏观测”的可行性，距离实时工程部署仍依赖传感器布局与计算效率。
- 论文强调其优势是不依赖先验训练数据，但这也意味着优化过程本身的成本仍然重要。

## 相关概念

- [[wind-field-reconstruction|Wind field reconstruction]]
- [[physics-informed-neural-network|Physics-informed neural network (PINN)]]
