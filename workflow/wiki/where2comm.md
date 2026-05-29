---
tags: [entity, model]
type: entity
---

# Where2comm

Where2comm 是一个面向多智能体协同感知的通信高效框架，核心思想是用 [[spatial-confidence-map|spatial confidence map]] 选择“真正值得传输”的空间区域。

## 核心特点

- 不是默认共享完整特征图，而是只共享空间上稀疏、感知上关键的信息。
- 同时解决三个问题：哪里通信、谁与谁通信、消息如何融合。
- 支持随带宽约束动态调整通信区域，并支持多轮协同交互。

## 为什么它重要

- 它把“通信预算”从外部约束变成模型内部显式优化对象。
- 相比只做特征压缩的方法，Where2comm 更强调**空间选择性**而不是均匀压缩。
- 该框架虽然主要验证于车路协同和无人机场景，但其通信策略对 [[multi-aircraft-collaborative-perception|Multi-aircraft collaborative perception]] 有直接借鉴价值。

## 在当前知识网络中的位置

- 它是现有“多机协同感知”页面中通信区域选择、稀疏图构建和注意力融合机制的跨领域方法来源。
- 它与航空硕士论文页面的关系不是应用场景一致，而是方法机制可迁移。

## 来源

- [[source-where2comm-spatial-confidence-maps|Where2comm: Communication-Efficient Collaborative Perception via Spatial Confidence Maps]]

