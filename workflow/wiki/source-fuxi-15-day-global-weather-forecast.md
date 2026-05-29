---
tags: [source-summary, ai-weather-forecasting, weather-forecasting, fuxi]
source: "FuXi: a cascade machine learning forecasting system for 15-day global weather forecast"
author: Lei Chen et al.
date: 2023-11-16
url: "https://doi.org/10.1038/s41612-023-00512-1"
---

# FuXi: a cascade machine learning forecasting system for 15-day global weather forecast

## 来源信息

- **本地原文**：[原始文稿](../raw/FuXi十五天全球天气预报级联机器学习系统/s41612-023-00512-1.md)
- **发表位置**：npj Climate and Atmospheric Science 6, 190
- **核心对象**：[[fuxi|FuXi]] 15 天全球天气预报系统

## 核心观点

- 论文认为单个模型很难同时在短时效和长时效上都最优，因此提出级联系统 [[fuxi|FuXi]]。
- 它把 15 天预报拆成 0–5、5–10、10–15 天三个窗口，用三套预训练模型串联生成 6 小时间隔、0.25° 分辨率的全球预报。
- 这是一种“结构化管理误差积累”的方案，是 [[ai-medium-range-weather-forecasting|AI medium-range weather forecasting]] 从 10 天迈向 15 天的重要一步。

## 关键结果

- 文中报告 FuXi 的 15 天预报性能与 ECMWF ensemble mean 可比。
- 对 Z500 的 skillful lead time 从 ECMWF HRES 的 9.25 天延长到 10.5 天。
- 对 T2M 的 skillful lead time 从 10 天延长到 14.5 天。
- 论文还构建了 FuXi ensemble，通过扰动初始条件和模型参数给出不确定性信息。

## 注意事项

- 级联架构解决了一部分长时效误差累积问题，但仍然依赖高质量初始场。
- 文中也指出，真正端到端的数据驱动预报系统还需要更成熟的数据同化和集合生成机制。

## 相关概念

- [[fuxi|FuXi]]
- [[ai-medium-range-weather-forecasting|AI medium-range weather forecasting]]
