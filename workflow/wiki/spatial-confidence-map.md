---
tags: [concept]
type: concept
---

# Spatial confidence map

空间置信图是一种对空间位置“感知价值”进行显式评分的表示，用于决定在受限带宽条件下哪些区域值得被通信和融合。

## 核心含义

- 并非所有空间区域对协同感知同等重要。
- 真正值得传输的往往是**空间上稀疏、感知上关键**的区域。
- 因此，通信问题可以从“压缩整张特征图”转为“优先发送关键区域”。

## 在 Where2comm 中的作用

- 用来决定 *where to communicate*。
- 作为消息打包和通信图构建的依据。
- 进一步影响消息融合时的注意力分配。

## 对当前知识库的启发

- 现有 [[multi-aircraft-collaborative-perception|Multi-aircraft collaborative perception]] 页面已经有“选择关键通信区域”的思想，但此前主要来自航空场景论文中的工程设计。
- Where2comm 给出了更通用、更细粒度的实现范式：通过空间置信度把通信问题变成显式、可学习的区域选择问题。
- 这对未来航空气象协同感知很重要，因为高风险天气感知往往天然具有空间异质性。

## 来源

- [[source-where2comm-spatial-confidence-maps|Where2comm: Communication-Efficient Collaborative Perception via Spatial Confidence Maps]]

