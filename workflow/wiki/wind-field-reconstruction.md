---
tags: [concept]
type: concept
---

# Wind field reconstruction

风场重建指从稀疏、局部或不完整的观测中恢复更完整的二维或三维风场结构，是气象感知和流场数据同化中的核心问题。

## 主要技术路线

- **变分/物理反演**：例如双多普勒雷达三维变分方法，强调可解释性和约束一致性。
- **物理约束神经网络**：以 [[physics-informed-neural-network|PINN]] 为代表，把观测损失与控制方程残差一起优化。
- **纯数据驱动重建**：例如 Vision Mamba Decoder，从不完整风数据直接回归完整风场。

## 当前资料体现出的共性

- 稀疏观测不是例外，而是常态；LiDAR、航路观测、雷达布设都天然不完整。
- 物理一致性是高频诉求，因此即便使用深度学习，也经常显式引入 Navier-Stokes 或连续性约束。
- 传感器布局和多源协同对重建性能影响显著，例如多 LiDAR 能改善体积重建。

## 代表资料

- [[source-lidar-multiscale-pinn-wind-field-reconstruction|Three-dimensional spatiotemporal wind field reconstruction based on LiDAR and multi-scale PINN]]
- [[source-dynamic-wake-pinn-sparse-lidar|Dynamic wake field reconstruction of wind turbine through Physics-Informed Neural Network and Sparse LiDAR data]]
- [[source-vision-mamba-incomplete-wind-data|Wind Field Reconstruction Method Using Incomplete Wind Data Based on Vision Mamba Decoder Network]]
- [[source-dual-doppler-variational-wind-field|Three-Dimensional Wind Field Retrieved from Dual-Doppler Radar Based on a Variational Method: Refinement of Vertical Velocity Estimates]]
- [[source-practical-flow-field-reconstruction-pinn|A practical approach to flow field reconstruction with sparse or incomplete data through physics informed neural network]]

## 来源

- [[source-lidar-multiscale-pinn-wind-field-reconstruction]]
- [[source-dynamic-wake-pinn-sparse-lidar]]
- [[source-vision-mamba-incomplete-wind-data]]
- [[source-dual-doppler-variational-wind-field]]
- [[source-practical-flow-field-reconstruction-pinn]]

