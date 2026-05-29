---
tags: [analysis, aviation, weather, ai]
type: analysis
---

# Aviation weather intelligence analysis

这批资料共同构成了一个较完整的“航空气象智能链路”，从原始观测、局部场重建、全球中期预报，一直到自主运行场景中的协同感知与使用。

## 四层知识结构

### 1. 观测层

- [[mode-s-ehs|Mode-S EHS]] 和 [[emaddc|EMADDC]] 提供高体量、分钟级更新的飞机衍生风温观测。
- LiDAR、双多普勒雷达和机载气象雷达提供更局部、更高分辨率的场信息。

### 2. 重建层

- [[wind-field-reconstruction|Wind field reconstruction]] 是把不完整观测变成可用天气场的关键桥梁。
- 该层目前存在三条主线：变分法、[[physics-informed-neural-network|PINN]]、纯数据驱动解码器。
- 这说明“稀疏观测”不是例外，而是航空气象问题的默认前提。

### 3. 预报层

- [[pangu-weather|Pangu-Weather]]、[[fuxi|FuXi]] 和 [[fengwu|FengWu]] 展示了 AI 中期预报正在从 10 天内领先推进到 15 天及概率预报竞争。
- 这一层主要解决全局背景场和长 lead time 认知，不直接替代局部感知。

### 4. 运行层

- [[airborne-meteorological-situational-awareness|Airborne meteorological situational awareness]] 与 [[multi-aircraft-collaborative-perception|Multi-aircraft collaborative perception]] 说明，最终问题不是“有没有模型”，而是“在通信、时延和安全约束下，航空器如何真正利用这些信息”。
- 新导入的 [[where2comm|Where2comm]] 进一步说明，运行层的关键不只是“多机共享”，而是“只共享真正高价值的空间片段”。

## 跨资料的共同主题

- **物理约束反复出现**：无论是变分法还是 PINN，物理一致性都是处理稀疏观测的核心手段。
- **时效和体量同等重要**：EMADDC 证明高质量分钟级观测是业务系统的竞争力来源。
- **误差积累是核心矛盾**：从 FuXi 的 cascade 到 FengWu 的 replay buffer，本质都在处理长 lead time 误差扩散。
- **航空应用是系统问题**：局部感知、重建、全局预报和协同共享必须联动，单点模型无法独立解决自主运行问题。
- **协同感知的通信必须选择性进行**：Where2comm 证明空间异质性可以被显式建模，这对未来航空气象协同共享很关键。

## 当前知识网络中的空白

- 还缺“局部重建结果如何与全局 AI 预报背景场融合”的专门页面。
- 还缺“机载雷达、地面雷达、飞机衍生观测、AI 预报之间的实时数据融合架构”资料。
- 若后续继续导入，可重点补充数据同化、航迹优化和概率风险决策相关文献。
- 还可以继续补“风险驱动通信”“事件级天气片段共享”“协同感知中的不确定性通信”相关资料。

## 来源

- [[source-mode-s-ehs-wind-observation-errors|Estimates of Mode-S EHS aircraft-derived wind observation errors using triple collocation]]
- [[source-emaddc-mode-s-ehs-observations|EMADDC: high-volume, high-quality, and timely wind and temperature observations from aircraft surveillance data (Mode-S EHS)]]
- [[source-lidar-multiscale-pinn-wind-field-reconstruction|Three-dimensional spatiotemporal wind field reconstruction based on LiDAR and multi-scale PINN]]
- [[source-dynamic-wake-pinn-sparse-lidar|Dynamic wake field reconstruction of wind turbine through Physics-Informed Neural Network and Sparse LiDAR data]]
- [[source-vision-mamba-incomplete-wind-data|Wind Field Reconstruction Method Using Incomplete Wind Data Based on Vision Mamba Decoder Network]]
- [[source-dual-doppler-variational-wind-field|Three-Dimensional Wind Field Retrieved from Dual-Doppler Radar Based on a Variational Method: Refinement of Vertical Velocity Estimates]]
- [[source-practical-flow-field-reconstruction-pinn|A practical approach to flow field reconstruction with sparse or incomplete data through physics informed neural network]]
- [[source-pangu-weather-3d-neural-networks|Accurate medium-range global weather forecasting with 3D neural networks]]
- [[source-fuxi-15-day-global-weather-forecast|FuXi: a cascade machine learning forecasting system for 15-day global weather forecast]]
- [[source-fengwu-extended-medium-range-forecast|The operational medium-range deterministic weather forecasting can be extended beyond a 10-day lead time]]
- [[source-multi-aircraft-collaborative-situational-awareness|面向自主运行的多机态势智能协同感知方法研究]]
- [[source-where2comm-spatial-confidence-maps|Where2comm: Communication-Efficient Collaborative Perception via Spatial Confidence Maps]]
