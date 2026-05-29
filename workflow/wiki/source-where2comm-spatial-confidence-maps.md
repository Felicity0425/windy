---
tags: [source-summary, collaborative-perception, communication-efficient, spatial-confidence]
source: "Where2comm: Communication-Efficient Collaborative Perception via Spatial Confidence Maps"
author: Yue Hu et al.
date: 2022-10-31
url: "https://openreview.net/forum?id=dLL4KXzKUpS"
---

# Where2comm: Communication-Efficient Collaborative Perception via Spatial Confidence Maps

## 来源信息

- **本地原文**：[原始文稿](../raw/Where2comm基于空间置信图的高通信效率协同感知/where2comm.md)
- **发表位置**：NeurIPS 2022
- **代码仓库**：<https://github.com/MediaBrain-SJTU/where2comm>
- **核心对象**：受限带宽条件下的多智能体协同感知通信策略

## 核心观点

- 协同感知的核心矛盾不是“是否通信”，而是**感知性能与通信带宽之间的根本权衡**。
- 论文提出 [[spatial-confidence-map|spatial confidence map]]，显式刻画不同空间区域的感知价值，只让 agent 共享“空间上稀疏但感知上关键”的信息。
- 基于这一思想，作者提出 [[where2comm|Where2comm]]，把“哪里该传、谁该传、收到后如何融合”统一到一个通信高效框架中。

## 关键方法

- **Spatial confidence generator**：为每个空间位置生成置信度，表征其感知关键程度。
- **Confidence-aware communication**：利用置信图做消息打包和通信图构建，决定 *where* 和 *who* to communicate。
- **Confidence-aware message fusion**：用置信度引导的多头注意力融合来自其他 agent 的消息。
- **Multi-round communication**：支持多轮交互，并能随带宽动态调整参与通信的空间区域。

## 关键结果

- 论文在 OPV2V、V2X-Sim、DAIR-V2X 和 CoPerception-UAVs 四个数据集上评估，覆盖车/无人机两类 agent 与相机/LiDAR 两类模态。
- 文中指出，Where2comm 在 OPV2V 上可把通信量降到比 DiscoNet 和 V2X-ViT 低 100,000 倍以上，同时仍取得更好的检测性能。
- 这说明“空间选择性通信”本身就是可迁移的方法论，而不仅是具体模型技巧。

## 对当前知识库的意义

- 这篇论文不直接面向航空气象，但它给 [[multi-aircraft-collaborative-perception|Multi-aircraft collaborative perception]] 提供了可迁移的通信设计模式。
- 它补强了现有知识库中“多机协同感知”页面里关于通信区域筛选、稀疏图构建和注意力融合的实现来源。
- 也提示一个重要方向：未来航空自主运行中的协同气象感知，不一定需要传完整场，而可以只传“高风险、高价值”的空间片段。

## 相关概念

- [[where2comm|Where2comm]]
- [[spatial-confidence-map|Spatial confidence map]]
- [[multi-aircraft-collaborative-perception|Multi-aircraft collaborative perception]]
