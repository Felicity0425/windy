---
tags: [entity, model]
type: entity
---

# FuXi

面向 15 天全球天气预报的级联机器学习系统，通过多模型串联管理不同预报时效窗口。

## 核心特点

- 由三个针对不同 lead time 窗口优化的模型级联组成。
- 提供 6 小时分辨率、0.25° 分辨率的 15 天全球预报。
- 通过 ensemble 设计提供不确定性信息。

## 在当前知识网络中的位置

- 它把 AI 预报从“10 天内明显强势”推进到“15 天可与 ECMWF ensemble mean 比肩”。
- 相比 [[pangu-weather|Pangu-Weather]]，FuXi 更强调分阶段预报架构。
- 相比 [[fengwu|FengWu]]，FuXi 的长时效能力依赖 cascade，而不是 multi-modal + replay buffer。

## 来源

- [[source-fuxi-15-day-global-weather-forecast|FuXi: a cascade machine learning forecasting system for 15-day global weather forecast]]

