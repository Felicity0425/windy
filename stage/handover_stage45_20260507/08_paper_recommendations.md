# 论文建议

## 这份文档的作用
这份文档用于明确：

- 现在这套代码最适合支撑什么论文
- 不适合怎样写
- 当前应该怎样组织研究叙述

---

## 一、当前方向有没有论文意义

有，而且不是普通工程调参意义上的“有点意思”，而是：

**具备完整研究链路的论文胚子。**

你当前项目已经对应了知识库中的完整链条：

- aircraft-derived observations
- wind-field reconstruction
- airborne meteorological situational awareness
- multi-aircraft collaborative perception
- Where2Comm
- PINN / physics-aware reconstruction
- 事件驱动后续预测的自然延伸

所以这条线不是“做一个更高 coverage 的 Stage4”，而是：

**面向空地一体协同感知的航空风场状态构建与后续事件驱动预测。**

---

## 二、当前代码最适合支撑哪类论文

我建议优先考虑两条：

### 方向 A：系统型论文
题目风格：

- 面向机载气象态势感知的多源协同风场重建框架
- A multi-source collaborative wind-field reconstruction framework for airborne meteorological situational awareness

特点：

- 强调系统链路完整
- 强调 `Stage3 + Stage4`
- 强调运行可用性、协同性、状态层构建

### 方向 B：训练样本 / 状态层构建论文
题目风格：

- 面向稀疏航空风观测的三维风场状态构建与训练样本生成方法
- Stage4-based wind-field state construction and training-sample generation from sparse aviation observations

特点：

- 更稳
- 更贴合你当前代码强项
- 不要求你立即拿出一个最强 end-to-end 预测网络

---

## 三、当前不建议怎么写

### 不建议写成：
- “我们发明了一个全新的最强风场预测网络”
- “我们的方法显著优于所有已有文献”

原因：

- 你的数据和公开文献数据不同
- 当前更强的是系统层与状态层设计
- 不是单一 end-to-end 网络创新

### 不建议把 `Stage4` 和 `Stage5` 一起硬写成一篇完成版方法
原因：

- `Stage4` 现在刚接近冻结
- `Stage5` 还没开始正式训练
- 混在一起会让论文结构过散

---

## 四、最稳妥的论文叙述方式

建议先把论文问题收缩成：

**在稀疏、多源、空地混合观测条件下，如何构建一个稳定、可解释、可运行的局部风场状态层。**

然后把 `Stage4` 定义成：

- 不是最终预测器
- 而是风场状态构建层
- 为后续 `Stage5` 预测提供输入

这样有几个好处：

1. 你现有代码和论文叙述高度一致  
2. 不需要现在就证明 `Stage5` 最终性能  
3. 可以把 `Stage4` 写成清晰的方法层与实验层  

---

## 五、论文里的核心贡献怎么写

当前最合适的贡献，不建议写成“全新神经网络”，而建议写成以下三类之一。

### Contribution 1
提出了一个适用于航空稀疏多源风观测的局部风场状态构建框架，统一融合：

- 直接风观测
- 轨迹 / 运动观测
- flight seed
- 时序背景
- 风险与通信辅助表征

### Contribution 2
提出了一个可解释的 `Stage4` 状态层设计，使风场重建输出同时包含：

- `recon_*`
- `physics_weight`
- `source_diversity`
- `where2comm_targets`
- `forecast_*`
- `hazard_*`

从而不仅服务于重建本身，也为后续协同预测提供输入。

### Contribution 3
建立了一套面向航空稀疏观测的内部 baseline / ablation 实验矩阵：

- `S0-S6`
- 可复现
- 可消融
- 可运行

这对你的论文很重要，因为你的数据与公开文献不同。

---

## 六、实验应该怎么比

### 1. 不做外部数值硬对比
不直接和：

- PINN 文献
- Vision Mamba 文献
- 变分法文献

做绝对数值硬比。

原因：

- 数据不同
- 场景不同
- 输入条件不同

### 2. 做“结构对比 + 内部 baseline”

外部文献用于：

- 方法动机
- 结构对照
- 设计合理性说明

真正的实验核心是：

- `S0-S6` 内部版本对比
- full fast vs full aux
- 运行性 vs 状态质量对比

---

## 七、当前最推荐的论文结构

### 第 1 章：问题背景
- 航空气象态势感知
- 空地一体协同感知
- 稀疏风观测的困难

### 第 2 章：系统框架
- Stage2：voxelization
- Stage3：agent / communication graph
- Stage4：wind-field state construction

### 第 3 章：Stage4 方法
- 多源融合
- support / temporal / relax
- confidence shaping
- direct anchor protection
- communication target construction

### 第 4 章：实验
- 数据与任务定义
- `S0-S6` 矩阵
- 主结果
- 消融
- 运行成本

### 第 5 章：讨论
- 稀疏数据边界
- 为什么 Stage4 应冻结
- 为什么 Stage5 应该事件驱动

---

## 八、对 Stage5 的论文建议

当前建议是：

- 先不要把 `Stage5` 写进当前 Stage4 论文主结果
- 只把它写成后续方向

最合适的表述是：

> 当前 Stage4 作为稳定的风场状态构建层，为后续事件驱动、ROI 聚焦的空地一体协同实时风场预测提供输入表示。

这样：

- 不会让当前论文结构失焦
- 又能自然引出下一阶段工作

---

## 九、当前最重要的研究策略建议

### 建议 1
先冻结 `Stage4`，再做全量和消融。

### 建议 2
论文主线先围绕 `Stage4`，不要过早扩到 `Stage5` 训练。

### 建议 3
后续如果进入 `Stage5`，应采用：

- 事件驱动
- ROI 聚焦
- 短时预测

而不是“每帧都做全域预测”。

---

## 新窗口接手时的提醒

- 现在最有价值的不是继续大调 `Stage4`，而是组织好 `Stage4` 的全量结果和消融。
- 论文应该先把 `Stage4` 写稳，再开 `Stage5`。
