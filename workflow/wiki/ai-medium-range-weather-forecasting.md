---
tags: [concept]
type: concept
---

# AI medium-range weather forecasting

AI 中期天气预报指利用深度学习系统替代或补充传统数值天气预报，在全球尺度上进行 10 到 15 天量级的确定性或概率性预测。

## 当前资料中的方法演进

- [[pangu-weather|Pangu-Weather]]：强调 3D 网络和 Earth-specific priors，把 AI 中期预报推进到可正面对比 ECMWF IFS。
- [[fuxi|FuXi]]：强调 cascade，把 15 天拆成多个窗口，控制不同 lead time 的最优性。
- [[fengwu|FengWu]]：强调多模态、多任务和 replay buffer，并进一步把集合不确定性一并纳入系统设计。

## 共性特征

- 都依赖大规模 ERA5 等再分析资料训练。
- 都把误差积累视为中期预报的核心瓶颈。
- 都开始把集合或概率预报纳入设计，而不仅是追求单次确定性最优。

## 主要张力

- **准确率 vs. 稳定性**：长 lead time 下的平滑化和误差扩散仍未根治。
- **研究评估 vs. 业务部署**：真实业务初始场与离线再分析初始化之间存在差异。
- **确定性 vs. 概率性**：单模型最优不等于集合最优，不确定性表达仍是竞争焦点。

## 来源

- [[source-pangu-weather-3d-neural-networks|Accurate medium-range global weather forecasting with 3D neural networks]]
- [[source-fuxi-15-day-global-weather-forecast|FuXi: a cascade machine learning forecasting system for 15-day global weather forecast]]
- [[source-fengwu-extended-medium-range-forecast|The operational medium-range deterministic weather forecasting can be extended beyond a 10-day lead time]]

