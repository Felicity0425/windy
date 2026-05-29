# 航空风场重构项目论文与开源代码映射

> 更新时间：2026-04-27  
> 目的：把当前项目最相关的论文、官方代码和可落地的改进方向整理成一个长期可复用的研究备忘录。

---

## 1. 你的项目当前最像哪一类研究

从方法上看，你的项目不是单纯的天气预报，也不是单纯的雷达反演。

它更接近一个 **“多源稀疏观测驱动的局地/区域风场重构与训练数据生成系统”**，有四个显著特征：

1. 观测源是多源异构的  
   - 航迹 / location  
   - AMDAR / aircraft-derived wind  
   - turbulence  
   - radar mosaic

2. 目标不是直接做全局天气预报  
   - 而是为后续模型生成结构化训练样本

3. 中间显式构建了图结构  
   - `flight agents`
   - `communication edges`
   - `motion edges`
   - `wind edges`

4. 重构是事件触发式的  
   - 稳定帧轻量保留
   - 变化帧完整重构

因此，从论文定位上，建议把你的工作放在：

> **多源航空观测 + 图结构传播 + 稀疏风场重构 + 训练样本打包**

而不是硬往“纯天气大模型预测”上靠。

---

## 2. 直接相关论文

这些论文和你的项目最接近，优先读。

### 2.1 航空观测 / AMDAR / Mode-S 相关

#### 1. EMADDC: high-volume, high-quality, and timely wind and temperature observations from aircraft surveillance data (Mode-S EHS)
- 类型：国际，直接相关
- 链接：https://amt.copernicus.org/articles/18/3341/2025/
- 价值：
  - 直接讨论如何从 aircraft surveillance / Mode-S EHS 中提取高质量风温观测
  - 对你 Stage 1/2 的 aircraft-derived observations 很有参考价值
  - 特别适合支撑你论文中的“航空观测数据源可靠性与可用性”部分
- 官方/项目链接：
  - EMADDC 官方：https://www.emaddc.com/default.aspx

#### 2. Estimates of Mode-S EHS aircraft-derived wind observation errors using triple collocation
- 类型：国际，直接相关
- 链接：https://amt.copernicus.org/articles/9/4141/2016/
- 价值：
  - 给 aircraft-derived wind 的误差量级提供文献依据
  - 你论文里如果要说明“飞机派生风不是无噪声真值”，这篇非常好用

#### 3. ECMWF steps up assimilation of aircraft weather data
- 类型：国际，工程背景
- 链接：https://www.ecmwf.int/en/newsletter/148/news/ecmwf-steps-assimilation-aircraft-weather-data
- 价值：
  - 说明 aircraft observations 在业务数值天气预报中的重要性
  - 很适合写论文背景，不适合当核心方法论文

### 2.2 航空/航线不完整风场重构

#### 4. Wind Field Reconstruction Method Using Incomplete Wind Data Based on Vision Mamba Decoder Network
- 类型：国内，直接相关
- 链接：https://www.mdpi.com/2226-4310/11/10/791
- 作者单位：Civil Aviation University of China
- 价值：
  - 这是目前我找到的最接近你“沿航线/不完整风数据重建完整风场”的国内论文之一
  - 你后续写论文时，几乎肯定应该把它列为最重要对比对象之一
- 局限：
  - 它偏二维平面和监督式重构
  - 你的项目更偏 3D、多源、图传播、训练数据生成

#### 5. Wind-field reconstruction from flight data using an unbiased minimum-variance unscented filter
- 类型：国际，相关但更偏控制/估计
- 链接：https://journals.sagepub.com/doi/10.1177/0142331209342211
- 价值：
  - 可以支持“利用飞行器状态反推风场”的经典估计思路
  - 适合放在相关工作早期传统方法部分

---

## 3. 雷达 / 风场反演 / 多普勒风场相关

### 3.1 直接可借鉴的方法

#### 6. PyDDA: Pythonic Direct Data Assimilation（开源）
- GitHub：https://github.com/openradar/PyDDA
- 文档：https://openradarscience.org/PyDDA/
- 价值：
  - 这是目前最值得你认真看的开源项目之一
  - 它专门做多普勒雷达三维风场反演
  - 虽然你现在的数据不完全等同 dual-Doppler，但它的**变分约束、背景场约束、质量控制思路**非常值得借鉴
- 关键支撑论文：
  - Potvin et al., 2012
  - Shapiro et al., 2009

#### 7. Three-Dimensional Wind Field Retrieved from Dual-Doppler Radar Based on a Variational Method: Refinement of Vertical Velocity Estimates
- 类型：国内，直接相关
- 链接：https://link.springer.com/article/10.1007/s00376-021-1035-9
- 价值：
  - 对“如何从雷达反演 3D 风场”有直接方法参考
  - 特别适合给你论文里的“雷达约束重构”部分补物理基线

### 3.2 对你当前项目的现实意义

你当前 Stage 4 主要是：
- 稀疏体素融合
- support-guided fill
- 局部 IDW

而 PyDDA / variational radar retrieval 这一路的方法启发你下一步可以考虑：

1. 增加显式质量函数
2. 增加质量守恒/平滑约束
3. 增加垂直速度或层间一致性约束
4. 用背景场而不是单纯局部插值

---

## 4. PINN / 稀疏流场重构相关

### 4.1 国内高相关论文

#### 8. A practical approach to flow field reconstruction with sparse or incomplete data through physics informed neural network
- 类型：国内，高相关
- 链接：https://link.springer.com/article/10.1007/s10409-022-22302-x
- 代码信息（论文内给出）：
  - https://github.com/Shengfeng233/PINN-for-NS-equation
- 价值：
  - 这是一个非常好的“稀疏观测 + PINN 重构”基线
  - 你以后如果要把 Stage 4 升级成更像论文的方法，这篇值得重点读

#### 9. Three-dimensional spatiotemporal wind field reconstruction based on LiDAR and multi-scale PINN
- 类型：国内，高相关
- 链接：
  - SSRN 预印本：https://papers.ssrn.com/sol3/papers.cfm?abstract_id=4819818
  - Applied Energy 正式版：https://www.sciencedirect.com/science/article/pii/S0306261924019603
- 作者单位：Southern University of Science and Technology
- 价值：
  - 很接近你现在的目标：3D、时空、稀疏观测、风场重构
  - 它对“为什么多尺度 PINN 有帮助”提供了很好的论据

### 4.2 国际高相关论文

#### 10. Dynamic wake field reconstruction of wind turbine through Physics-Informed Neural Network and Sparse LiDAR data
- 类型：国际，高相关
- 链接：https://www.sciencedirect.com/science/article/pii/S0360544224001725
- 价值：
  - 虽然场景是风机尾流，但方法上是“稀疏观测 + PINN + 动态重构”
  - 对你论文中“为什么 PINN 适合稀疏风场重构”很有帮助

#### 11. Flow field reconstruction and wind pressure estimation from sparse measurements using physics-informed neural networks
- 类型：国际，高相关
- 链接：https://www.sciencedirect.com/science/article/pii/S036013232501087X
- 价值：
  - 重点价值在于它明确讨论了 sparse measurements 下的 flow reconstruction
  - 对你后续若做“从 sparse sensors 到完整风场”的论证很有帮助

### 4.3 更前沿的生成式 / 扩散方法

#### 12. Physics-guided score-based diffusion for 3D reconstruction of tropical cyclones from sparse observations
- 类型：国际，前沿强相关
- 链接：https://www.nature.com/articles/s41612-026-01413-9
- 价值：
  - 这是你以后做“生成式/扩散式风场重构”最值得参考的前沿方向之一
  - 如果你打算把当前 Stage 4 当 baseline，后续这条线非常适合作为论文升级版

---

## 5. 天气 AI 大模型 / 图模型 / 扩散模型

这些论文不是和你项目一一对应，但它们能支持你论文中的“大方向合理性”。

### 国外

#### 13. GraphCast: Learned Global Weather Forecasting
- 论文页：https://deepmind.google/research/publications/graphcast-learned-global-weather-forecasting/
- 代码：https://github.com/google-deepmind/graphcast
- 价值：
  - 证明图结构在天气建模里是强路线
  - 你 Stage 3 的 graph design 在论文背景里可以借这类工作建立可信度

#### 14. GenCast: Diffusion-based ensemble forecasting for medium-range weather
- 论文页：https://huggingface.co/papers/2312.15796
- 代码运行插件：https://github.com/ecmwf-lab/ai-models-gencast
- 价值：
  - 支撑“扩散/生成式天气重建是可行方向”
  - 你后续想把 Stage 4 升成 diffusion 版，这是强参考

#### 15. FourCastNet: A Global Data-driven High-resolution Weather Model using Adaptive Fourier Neural Operators
- 论文页：https://huggingface.co/papers/2202.11214
- 官方代码：https://github.com/NVlabs/FourCastNet
- 价值：
  - 说明频域/神经算子路线在天气和风场任务里是有竞争力的
  - 若你后续做 “voxel grid -> neural operator” baseline，可参考

#### 16. NeuralGCM
- 代码：https://github.com/neuralgcm/neuralgcm
- 价值：
  - 这是混合 physics + ML 的代表路线
  - 对你后续把 Stage 4 往“显式物理先验”方向加强很有帮助

#### 17. WeatherBench 2
- 论文/基准代码：https://github.com/google-research/weatherbench2
- 文档：https://weatherbench2.readthedocs.io/en/latest/official-evaluation.html
- 价值：
  - 这是你后续规范实验和评估设计非常值得学习的项目
  - 你的项目虽然不是全球天气预报，但“如何做系统性评估”可以借鉴它

### 国内

#### 18. Pangu-Weather
- Nature 论文：https://www.nature.com/articles/s41586-023-06185-3
- 官方代码：https://github.com/198808xc/Pangu-Weather
- 价值：
  - 证明中国团队在天气 AI 上的强基线
  - 适合作为论文 related work 中的国内代表

#### 19. FengWu
- 代码：https://github.com/OpenEarthLab/FengWu
- 论文（正式版摘要页）：https://www.nature.com/articles/s43247-025-02502-y
- 价值：
  - 中国团队在 medium-range weather AI 方向的代表
  - 适合支持你论文中的“国内 AI 天气路线”部分

#### 20. FuXi
- 论文：https://www.nature.com/articles/s41612-023-00512-1
- 官方代码：https://github.com/tpys/FuXi
- 价值：
  - 国内公开实现较完整
  - 对你后续做更规范的训练/评估流程设计也有借鉴意义

#### 21. FuXi Weather
- 论文：https://www.nature.com/articles/s41467-025-62024-1
- 价值：
  - 重点不在你当前直接任务，而在于“端到端数据同化 + 预报”的方向
  - 可以作为你以后论文展望部分的重要参考

---

## 6. 现成开源代码，哪个最值得你看

### 第一优先级：直接能借鉴到你当前工程

1. **PyDDA**  
   https://github.com/openradar/PyDDA  
   适合借鉴：风场反演、变分约束、背景场约束、质量控制

2. **PINN-for-NS-equation**  
   https://github.com/Shengfeng233/PINN-for-NS-equation  
   适合借鉴：稀疏流场重构、PINN baseline、损失函数设计

3. **Google DeepMind GraphCast**  
   https://github.com/google-deepmind/graphcast  
   适合借鉴：图结构建模、多尺度图传播

### 第二优先级：后续升级方向

4. **GenCast / diffusion weather**
   - https://github.com/google-deepmind/graphcast
   - https://github.com/ecmwf-lab/ai-models-gencast

5. **FourCastNet**
   - https://github.com/NVlabs/FourCastNet

6. **NeuralGCM**
   - https://github.com/neuralgcm/neuralgcm

### 第三优先级：国内开放实现参考

7. **Pangu-Weather**
   - https://github.com/198808xc/Pangu-Weather

8. **FengWu**
   - https://github.com/OpenEarthLab/FengWu

9. **FuXi**
   - https://github.com/tpys/FuXi

---

## 7. 这些论文对你当前代码的直接启发

### 7.1 Stage 2

从 `stage2_summary.json` 的统计看：

- `wind_voxels` 中位数只有 `9`
- `wind_voxels=0` 的帧很多
- `wind_voxels<=5` 的帧很多

所以 Stage 2 的主要问题不是“坏”，而是：

> 数据天然稀疏，绝大多数帧本来就不适合期待高质量重构。

因此 Stage 2 更适合做的优化不是“大改结构”，而是：

1. 更精细地保留 `obs_conf`
2. 增加源类型标签和质量标签
3. 让 `wind_grouped` / `amdar_grouped` / `turb_grouped` 的统计更可解释

### 7.2 Stage 3

文献启发最明确的是：

- 风边不应该过严
- 风能力节点应该是软判定
- 图结构需要保留多尺度传播可能性

这和你当前代码方向一致。

但从日志看，你当前仍然有一个明显短板：

> `valid_wind_capable_flights` 里很多是 `soft` 激活，`direct / near / geo` 命中仍偏少。

这说明：

- 当前图已经可用
- 但物理证据还不够“硬”

### 7.3 Stage 4

从 PINN / sparse reconstruction 文献看，你当前 Stage 4 最大可提升点有两个：

1. **把当前 heuristic reconstruction 提升成 physics-guided reconstruction**
   - 例如加入质量守恒、平滑正则、层间一致性

2. **把当前 deterministic fill 提升成 generative / probabilistic refinement**
   - 例如 diffusion 或 score-based reconstruction

当前代码作为论文 baseline 是合理的，但如果你的目标是科研论文，后续最值得发力的创新点大概率会在 Stage 4。

---

## 8. 对你科研论文的建议定位

### 方案 A：工程型论文

题目方向：

> 多源航空观测驱动的事件触发式三维风场重构与训练数据生成框架

优点：

- 离你当前工程最近
- 很容易写成系统论文
- Stage 1/2/3/4 可以形成完整方法链

创新点可写成：

1. 多源航空观测统一体素化
2. 飞行智能体三层图结构
3. 事件触发式风场重构
4. 训练样本标准化导出

### 方案 B：方法型论文

题目方向：

> 图结构风传播与物理约束融合的稀疏航空风场重构方法

优点：

- 更学术
- 更容易突出 Stage 3 + Stage 4 的方法创新

创新点可以放在：

1. 风能力节点定义
2. 风传播边激活机制
3. support-guided reconstruction
4. 物理约束增强

### 方案 C：升级版论文

题目方向：

> 面向稀疏航空观测的图传播-物理引导生成式风场重构

这条线适合你在当前 baseline 稳定后，再引入：

- PINN
- diffusion / score-based model

---

## 9. 最建议你下一步做什么

### 先做

1. 用当前代码跑一版全量 Stage 3 / Stage 4
2. 用 `report_stage4_training_readiness.py` 做 summary 分布统计
3. 做一版 baseline 训练

### 再做

4. 挑 Stage 4 做更像论文方法的升级
   - PINN baseline
   - physics-guided loss
   - diffusion refinement

### 暂时不建议

5. 现在就大改 Stage 2

因为从现有证据看，Stage 2 不是主瓶颈。

---

## 10. 我建议你优先精读的 8 篇

如果时间有限，先读这 8 篇：

1. EMADDC (2025)  
   https://amt.copernicus.org/articles/18/3341/2025/

2. Mode-S EHS wind observation errors (2016)  
   https://amt.copernicus.org/articles/9/4141/2016/

3. Vision Mamba wind reconstruction (2024, CAUC)  
   https://www.mdpi.com/2226-4310/11/10/791

4. Multi-scale PINN for 3D wind reconstruction (2025, SUSTech)  
   https://www.sciencedirect.com/science/article/pii/S0306261924019603

5. Sparse/incomplete flow reconstruction with PINN (2023, CAS)  
   https://link.springer.com/article/10.1007/s10409-022-22302-x

6. PyDDA and cited dual-Doppler variational papers  
   https://github.com/openradar/PyDDA

7. GraphCast  
   https://github.com/google-deepmind/graphcast

8. Physics-guided score-based diffusion for sparse 3D TC reconstruction (2026)  
   https://www.nature.com/articles/s41612-026-01413-9

