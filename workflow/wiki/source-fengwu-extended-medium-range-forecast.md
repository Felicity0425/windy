---
tags: [source-summary, ai-weather-forecasting, weather-forecasting, fengwu]
source: "The operational medium-range deterministic weather forecasting can be extended beyond a 10-day lead time"
author: Kang Chen et al.
date: 2025-07-03
url: "https://doi.org/10.1038/s43247-025-02502-y"
---

# The operational medium-range deterministic weather forecasting can be extended beyond a 10-day lead time

## 来源信息

- **本地原文**：[原始文稿](../raw/将业务级中期确定性天气预报延伸至十天以上/s43247-025-02502-y.md)
- **发表位置**：Communications Earth & Environment 6, 518
- **核心对象**：[[fengwu|FengWu]] 与 [[fengwu|FengWu-Ensemble]]

## 核心观点

- 论文提出 [[fengwu|FengWu]]，以多模态、多任务学习方式建模全球中期天气预报，并通过 replay buffer 机制抑制长时效误差传播。
- 与 [[pangu-weather|Pangu-Weather]] 和 GraphCast 相比，FengWu 更强调“多变量分模态建模 + 长时效精调”。
- 论文同时给出条件扩散式集合版本 FengWu-Ensemble，把 AI 预报从确定性扩展到概率性表达。

## 关键结果

- 论文报告 FengWu 在确定性预报上优于 ECMWF HRES、Pangu-Weather 和 GraphCast。
- 0.25° 分辨率、13 个气压层的设定说明其目标是业务级全球中期预报而不是研究级样例。
- FengWu-Ensemble 与 IFS ensemble 对比时，在多个变量和指标上表现更优。
- 文章明确提出将 skillful global weather forecasting 推到 10 天以上。

## 注意事项

- 文中也指出，和其他确定性 AI 模型一样，长时效平滑化仍是内在挑战。
- 其优势来自系统级设计，不只是单一网络结构，而是模态划分、损失设计、长时效训练策略共同作用。

## 相关概念

- [[fengwu|FengWu]]
- [[ai-medium-range-weather-forecasting|AI medium-range weather forecasting]]
