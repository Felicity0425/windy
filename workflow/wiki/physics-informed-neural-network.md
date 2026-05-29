---
tags: [concept]
type: concept
---

# Physics-informed neural network (PINN)

PINN 是把已知物理方程作为训练约束嵌入神经网络优化过程的一类方法，特别适合稀疏、缺失或难以获得完整标签的流场/气象重建问题。

## 为什么它在这批资料中反复出现

- LiDAR、实验测量和局部观测都只能提供稀疏数据。
- 直接做监督学习时，完整标签昂贵或不可得。
- 通过把 Navier-Stokes、连续性方程等残差加入损失函数，可以在缺标签条件下增强物理一致性。

## 这批资料中的典型用法

- 多尺度 PINN：扩展可表达的尺度范围，并改善收敛表现。
- 尾流重建 PINN：把时空坐标映射到速度和压力，并显式嵌入 NS 方程。
- 通用稀疏重建 PINN：即使只有 1% 的观测点，仍可恢复速度场和压力场。

## 局限与张力

- 它在数值试验和理想化案例中表现突出，但工程部署仍受训练成本和方程近似限制。
- 物理约束增强了一致性，但并不能自动解决传感器覆盖不足和实时计算压力。
- 在大尺度业务场景下，纯 PINN 还需要与观测设计、并行计算和数据同化策略结合。

## 来源

- [[source-lidar-multiscale-pinn-wind-field-reconstruction|Three-dimensional spatiotemporal wind field reconstruction based on LiDAR and multi-scale PINN]]
- [[source-dynamic-wake-pinn-sparse-lidar|Dynamic wake field reconstruction of wind turbine through Physics-Informed Neural Network and Sparse LiDAR data]]
- [[source-practical-flow-field-reconstruction-pinn|A practical approach to flow field reconstruction with sparse or incomplete data through physics informed neural network]]

