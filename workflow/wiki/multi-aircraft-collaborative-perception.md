---
tags: [concept]
type: concept
---

# Multi-aircraft collaborative perception

多机协同感知是指多架航空器在通信受限条件下共享局部观测和中间特征，以形成优于单机感知的整体态势理解。

## 核心问题

- 感知信息量大，但空空/空地通信资源有限。
- 不是所有观测都值得传输，关键在于筛选高价值区域和高价值特征。
- 多轮交互和特征融合必须兼顾性能与通信开销。

## 这批资料提供的方法线索

- 通过时空感知置信度和飞行意图选择通信区域。
- 构建动态稀疏通信图，避免全连接式的高昂通信代价。
- 使用多头注意力引导的特征融合策略，提高最终态势感知质量。

## 跨领域可迁移机制

- [[where2comm|Where2comm]] 虽然主要验证于车路协同和无人机场景，但它把“感知价值的空间异质性”做成了显式机制。
- 其 [[spatial-confidence-map|spatial confidence map]] 与当前航空场景中的“关键通信区域筛选”高度一致，只是粒度更细、学习式更强。
- 这说明航空多机协同感知后续可以借鉴的，不只是注意力融合，而是整套“区域选择 -> 稀疏图构建 -> 置信感知融合”的通信设计。

## 与其他页面的关系

- 它是 [[airborne-meteorological-situational-awareness|Airborne meteorological situational awareness]] 的协同实现机制。
- 它依赖更上游的局部观测、风场重建和预报背景场，但自身更接近运行决策层。

## 来源

- [[source-multi-aircraft-collaborative-situational-awareness|面向自主运行的多机态势智能协同感知方法研究]]
- [[source-where2comm-spatial-confidence-maps|Where2comm: Communication-Efficient Collaborative Perception via Spatial Confidence Maps]]
