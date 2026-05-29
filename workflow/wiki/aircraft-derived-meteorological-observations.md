---
tags: [concept]
type: concept
---

# Aircraft-derived meteorological observations

飞机衍生气象观测指利用飞机监视、导航或机载测量信息推断风、温度等气象变量，并将其接入航空气象或数值预报系统。

## 核心价值

- **体量大**：高密度航路网络能够提供传统探空之外的大规模上空观测。
- **时效高**：分钟级更新对航空运行和同化系统都很关键。
- **补充强**：能在常规观测稀疏区域提供更细致的上层大气信息。

## 当前资料中的关键节点

- [[mode-s-ehs|Mode-S EHS]] 提供原始飞机监视数据能力边界。
- [[source-mode-s-ehs-wind-observation-errors|2016 误差评估论文]] 说明其风观测误差水平具有业务应用潜力。
- [[emaddc|EMADDC]] 代表把该类数据规模化、标准化、业务化的处理系统。

## 关键挑战

- 必须做严格质量控制，否则大体量会放大误差污染。
- 温度反演通常比风更难，偏差控制要求更高。
- 从“能算出来”到“能稳定进入业务系统”之间，最大的门槛是处理链和验证体系。

## 来源

- [[source-mode-s-ehs-wind-observation-errors|Estimates of Mode-S EHS aircraft-derived wind observation errors using triple collocation]]
- [[source-emaddc-mode-s-ehs-observations|EMADDC: high-volume, high-quality, and timely wind and temperature observations from aircraft surveillance data (Mode-S EHS)]]

