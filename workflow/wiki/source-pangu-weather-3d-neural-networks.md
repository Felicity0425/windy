---
tags: [source-summary, ai-weather-forecasting, weather-forecasting, pangu-weather]
source: "Accurate medium-range global weather forecasting with 3D neural networks"
author: Kaifeng Bi et al.
date: 2023-07-05
url: "https://doi.org/10.1038/s41586-023-06185-3"
---

# Accurate medium-range global weather forecasting with 3D neural networks

## 来源信息

- **本地原文**：[原始文稿](../raw/基于三维神经网络的高精度中期全球天气预报/s41586-023-06185-3.md)
- **发表位置**：Nature 619, 533–538
- **核心对象**：[[pangu-weather|Pangu-Weather]] 中期全球天气预报系统

## 核心观点

- 论文提出 [[pangu-weather|Pangu-Weather]]，用 3D 深度网络和 Earth-specific priors 做准确的全球中期天气预报。
- 它的关键不只是“用 AI 做天气”，而是通过分层时间聚合策略抑制中期预报中的误差积累。
- 论文把 AI 预报的比较基线直接对准 ECMWF IFS，标志着 [[ai-medium-range-weather-forecasting|AI medium-range weather forecasting]] 进入可与顶级 NWP 系统正面对比的阶段。

## 关键结果

- 论文指出在所有测试变量上，Pangu-Weather 的确定性预报结果均强于 ECMWF 的业务 IFS。
- 方法同时在极端天气预报、集合预报和热带气旋路径跟踪上表现出竞争力。
- 训练数据覆盖 39 年全球数据，说明规模化再分析资料是这类系统的关键基础设施。

## 注意事项

- 论文主要证明确定性预报能力和 AI 架构潜力，不等于解决了全部业务化问题。
- 实际部署仍受到初始场质量、误差积累、集合不确定性表达和业务评估体系约束。

## 相关概念

- [[pangu-weather|Pangu-Weather]]
- [[ai-medium-range-weather-forecasting|AI medium-range weather forecasting]]
