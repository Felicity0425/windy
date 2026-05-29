---
tags: [source-summary, wind-field-reconstruction, aviation, deep-learning]
source: "Wind Field Reconstruction Method Using Incomplete Wind Data Based on Vision Mamba Decoder Network"
author: Min Chen et al.
date: 2024-09-25
url: "https://doi.org/10.3390/aerospace11100791"
---

# Wind Field Reconstruction Method Using Incomplete Wind Data Based on Vision Mamba Decoder Network

## 来源信息

- **本地原文**：[原始文稿](../raw/基于Vision Mamba解码网络的不完整风数据风场重建方法/aerospace-11-00791.md)
- **发表位置**：Aerospace 11(10):791
- **核心对象**：基于航路分布的不完整风数据重建完整风场

## 核心观点

- 论文关注民航航路上的风场信息不完整问题，提出基于 Vision Mamba Decoder 的深度学习重建方法。
- 与 PINN 路线不同，这篇论文更偏向数据驱动重建：输入是沿航路分布的不完整风数据，输出是完整风场。
- 其应用目标直指民航飞行路线规划，因此与 [[airborne-meteorological-situational-awareness|Airborne meteorological situational awareness]] 联系紧密。

## 关键结果

- 文中报告风速 MAE 约 1.83 m/s，MRE 约 7.87%，R-square 约 0.92。
- 风向 MAE 约 5.78 度。
- 结果说明在缺测条件下，状态空间模型/序列建模路线可以作为 [[wind-field-reconstruction|Wind field reconstruction]] 的另一类技术路径。

## 注意事项

- 方法依赖训练数据分布与任务设定，泛化到新的航路、天气型态或观测噪声时需要额外验证。
- 相比物理约束方法，它的优势是推理速度和端到端性，但物理一致性约束较弱。

## 相关概念

- [[wind-field-reconstruction|Wind field reconstruction]]
- [[airborne-meteorological-situational-awareness|Airborne meteorological situational awareness]]
