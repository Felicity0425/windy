---
tags: [source-summary, wind-field-reconstruction, pinn, sparse-data]
source: "A practical approach to flow field reconstruction with sparse or incomplete data through physics informed neural network"
author: Shengfeng Xu et al.
date: 2022-11-14
url: "https://doi.org/10.1007/s10409-022-22302-x"
---

# A practical approach to flow field reconstruction with sparse or incomplete data through physics informed neural network

## 来源信息

- **本地原文**：[原始文稿](../raw/基于物理信息神经网络的稀疏或不完整数据流场重建实用方法/s10409-022-22302-x.md)
- **发表位置**：Acta Mechanica Sinica 39, 322302
- **核心对象**：基于 PINN 的稀疏/缺失流场重建

## 核心观点

- 论文将 [[physics-informed-neural-network|PINN]] 作为不完美数据条件下的流场重建方案，把已知观测与物理规律直接耦合。
- 测试案例是圆柱尾流，重点考察两类训练集：不同稀疏度的数据，以及不同区域缺失的数据。
- 这篇文章为更具体的 LiDAR 风场重建工作提供了一个通用方法学底座。

## 关键结果

- 文中指出余弦退火学习率有助于加快训练收敛。
- 在数据稀疏度低至 1% 或核心流动区域数据缺失的情况下，方法仍能高精度恢复速度场。
- 即使速度数据严重不完备，也能较准确预测压力场。

## 注意事项

- 论文强调的是实验流体力学中的数据同化可行性，不直接面向气象业务部署。
- 但它清楚展示了为什么 PINN 会成为稀疏观测重建问题中的高频路线。

## 相关概念

- [[wind-field-reconstruction|Wind field reconstruction]]
- [[physics-informed-neural-network|Physics-informed neural network (PINN)]]
