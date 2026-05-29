---
tags: [entity, model]
type: entity
---

# FengWu

面向业务级全球中期天气预报的 AI 系统，强调多模态、多任务学习和长时效误差控制。

## 核心特点

- 把不同变量视为不同模态，采用编码-融合-解码结构进行跨模态建模。
- 通过 replay buffer 机制降低自回归长时效预报中的误差累积。
- 提供条件扩散式集合版本 FengWu-Ensemble，用于概率预报。

## 在当前知识网络中的位置

- 它代表当前这批资料中最系统的“确定性 + 概率性”一体化 AI 预报方案。
- 相比 [[pangu-weather|Pangu-Weather]]，FengWu 更强调模态定制与集合扩展。
- 相比 [[fuxi|FuXi]]，FengWu 更强调多任务优化和长时效微调策略。

## 来源

- [[source-fengwu-extended-medium-range-forecast|The operational medium-range deterministic weather forecasting can be extended beyond a 10-day lead time]]

