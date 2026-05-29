# 三篇核心论文的方法论拆解与工程映射

> 目标：把以下三篇最相关论文的方法、重构逻辑、训练/推理方式、优缺点，系统映射到当前项目中：
>
> 1. Vision Mamba 风场重构  
>    https://www.mdpi.com/2226-4310/11/10/791
> 2. Sparse / incomplete flow reconstruction with PINN  
>    https://link.springer.com/article/10.1007/s10409-022-22302-x
> 3. Multi-scale PINN for 3D wind reconstruction  
>    https://www.sciencedirect.com/science/article/pii/S0306261924019603

---

## 1. 论文一：Vision Mamba 风场重构（CAUC, 2024）

### 1.1 它在做什么

这篇论文的任务可以概括为：

> 用沿航路分布的不完整风观测，重构完整二维水平风场。

它不是做全球天气预报，也不是做纯数值同化，而是做：

- 不完整观测输入
- 完整风场输出
- 典型监督式重构问题

### 1.2 数据如何构造

从论文摘要和正文可见，它主要使用：

- ERA5 再分析风场作为“完整真值”
- 在完整风场上人为构造随机航迹
- 再通过 Mask 操作制造“不完整沿航路观测”

所以它本质上是：

1. 有完整风场标签
2. 把完整标签裁成稀疏观测输入
3. 训练网络学会“从稀疏输入恢复完整输出”

### 1.3 方法论

核心是 **Vision Mamba Decoder (VMD)**：

- 编码器：从不完整风观测中提取长程依赖特征
- 解码器：把低维特征上采样回原始风场分辨率
- 本质：一种面向图像/场重建的监督式 encoder-decoder

它的关键启发不是“风场物理建模”，而是：

> 序列/空间上下文可以帮助从稀疏观测中恢复缺失区域。

### 1.4 它如何实现风场重构

重构逻辑是：

1. 输入：沿轨迹分布的稀疏风观测
2. 编码：Vision Mamba 提取全局依赖
3. 解码：恢复到完整网格
4. 输出：完整二维风场

这是一个典型的数据驱动重建：

- 优点：速度快、端到端
- 缺点：依赖完整标签，物理约束弱

### 1.5 对你项目的启发

最重要的启发有两个：

#### 启发 A：时序/上下文补全

Vision Mamba 的强项在于：

- 上下文建模
- 长距离依赖
- 对缺失区域的恢复

在你的项目里，这已经落到了当前 `Stage 4` 的：

- `temporal background`
- `support-guided fill`

也就是说，你现在做的：

> 用前一帧重构结果帮助当前帧恢复缺失区域

就是对 Vision Mamba 思路的一个工程化、无训练版近似。

#### 启发 B：未来可以做“Stage 4 neural decoder”

如果你后面上神经网络，最自然的方向不是改 Stage 3，而是：

- 保留 Stage 3 的图结构和边
- 把 Stage 4 升成一个条件式重构网络

输入可以用：

- `trajectory_3d`
- `recon_u_3d / recon_v_3d / recon_confidence_3d`
- `comm_joint_idx / comm_wind_idx / comm_motion_idx`
- `physics_weight_3d`

输出：

- refined `u/v/conf`

所以对你而言，Vision Mamba 更像：

> **Stage 4 神经重构分支的参考架构思想**

而不是要直接照搬论文。

---

## 2. 论文二：Sparse / incomplete flow reconstruction with PINN（CAS, 2023）

### 2.1 它在做什么

这篇论文解决的是：

> 稀疏或缺失观测下，如何利用 PINN 重构完整流场。

它的目标不是天气，而是流体场重建。

但方法上和你项目高度相关，因为你也在做：

- sparse observations
- full field reconstruction
- 希望引入 physics-informed constraints

### 2.2 方法论

它的核心是标准 PINN 思想：

损失函数由两部分组成：

1. **数据项**
   - 在有观测的点上拟合观测
2. **物理项**
   - 满足 governing equations 的残差

文章还特别讨论了：

- 稀疏率很高时如何保持可重建
- 缺失关键区域时如何仍然恢复
- 学习率调度对收敛的重要性

### 2.3 它如何实现流场重构

它的流程本质是：

1. 把空间坐标（和时间）输入神经网络
2. 网络输出流场变量
3. 在观测点上约束数据误差
4. 在采样点上约束 PDE 残差
5. 通过联合优化重建完整场

这类方法的典型特点：

- 不一定需要大规模先验训练集
- 物理一致性强
- 训练慢

### 2.4 对你项目的启发

#### 启发 A：PINN 不适合放在 Stage 3

Stage 3 本质是：

- 构图
- 选边
- 风能力节点激活

这是图结构问题，不是连续场 PDE 重建问题。

所以 PINN 不适合直接塞进 Stage 3。

#### 启发 B：PINN 非常适合 Stage 4 之后做 refinement

你当前 Stage 4 已经有：

- baseline `recon_u / recon_v / recon_conf`
- `trajectory_3d`
- `support_strength`
- `pinn_divergence_3d`
- `pinn_smoothness_3d`
- `physics_weight_3d`

这意味着你现在已经具备做以下事情的接口条件：

1. 用当前 heuristic reconstruction 作为初值
2. 用观测点拟合项约束
3. 用 divergence / smoothness / continuity 做物理项
4. 用 `physics_weight_3d` 控制物理约束强度

也就是说，当前工程已经适合往：

> **Stage 4 PINN refinement**

迈进。

#### 启发 C：你现在做的物理引导平滑，是 PINN 的前置 baseline

你当前加进去的：

- `_physics_guided_relaxation`
- `pinn_divergence_3d`
- `physics_weight_3d`

并不等于真正 PINN，
但它们相当于：

> 给后续 PINN 建立了可解释、可训练、可对照的 baseline 接口。

---

## 3. 论文三：Multi-scale PINN for 3D wind reconstruction（SUSTech, 2025）

### 3.1 它在做什么

这篇论文更接近你当前目标：

> 用稀疏 LiDAR 观测重构三维、时空风场。

和前两篇相比，它的关键区别是：

- 三维
- 时空联合
- 多尺度
- 强物理约束

### 3.2 方法论

核心是 **multi-scale PINN**：

1. 网络输入坐标与时间
2. 输出 3D 风速场
3. 数据项拟合 LiDAR 观测
4. PDE 残差项约束物理一致性
5. 通过多尺度层增强对不同尺度结构的表达能力

论文强调：

- 多尺度结构能显著改善重构范围
- 能恢复 LiDAR 扫描区域外的流场
- 收敛更快

### 3.3 它如何实现 3D 风场重构

与普通 PINN 相比，它多了两层能力：

1. 多尺度表达  
   能同时描述粗尺度背景流和细尺度扰动

2. 三维时空建模  
   不是单帧 2D，而是完整 3D + time

### 3.4 对你项目的启发

#### 启发 A：你的 Stage 4 已经天然适合做多尺度 refinement

你当前 Stage 4 里已经有多层不同语义的条件：

- `radar_2d`
- `trajectory_3d`
- `support_strength`
- `recon_confidence_3d`
- `flight seeds`
- `comm targets`

这些天然可以对应多尺度信息：

- 粗尺度：support / trajectory / radar
- 中尺度：baseline reconstructed field
- 细尺度：uncertainty / comm targets / local physical residuals

#### 启发 B：多尺度 PINN 比普通 PINN 更适合你

如果你后面真的上 PINN，我更建议的不是“最原始 PINN”，而是：

> **以 Stage 4 baseline 为初值的多尺度 PINN refinement**

理由：

1. 你的输入本身是多源异构的
2. 稀疏帧和高风帧的信息密度差异很大
3. 你既要保持大尺度背景，又要恢复局地结构

#### 启发 C：Stage 4 未来可以拆成两阶段

当前：

- heuristic baseline reconstruction

未来：

1. baseline reconstruction
2. multi-scale PINN refinement

再未来：

3. diffusion refinement

这条线非常适合写论文。

---

## 4. 这三篇论文综合起来，对你项目意味着什么

三篇论文代表三种互补思想：

### 4.1 Vision Mamba

重点在：

- 缺失区域恢复
- 上下文建模
- 快速重建

适合你：

- Stage 4 neural decoder
- temporal / spatial completion

### 4.2 Sparse PINN

重点在：

- 稀疏观测
- 物理约束
- 无完整标签也能重建

适合你：

- Stage 4 PINN refinement
- 作为强 baseline / 对照方法

### 4.3 Multi-scale PINN

重点在：

- 3D
- 时空
- 多尺度

适合你：

- 最终论文主方法升级

---

## 5. 当前工程应该怎么升级

### 阶段 A：你现在已经做完的

当前已经有：

- Stage 3 图传播 + 风边
- Stage 4 baseline reconstruction
- Where2Comm 风格体素通信目标
- PINN 物理代理量
- diffusion 条件先验接口

也就是说：

> 你的数据与接口层已经足够支持下一阶段神经网络研究。

### 阶段 B：下一步最推荐的升级

#### B1. PINN refinement baseline

最先做这个。

理由：

- 最可解释
- 最容易和当前 heuristic baseline 对照
- 最适合写论文 ablation

输入建议：

- `pinn_prior_u_3d`
- `pinn_prior_v_3d`
- `pinn_prior_confidence_3d`
- `trajectory_3d`
- `physics_weight_3d`
- 稀疏风观测点

损失建议：

1. 数据误差项
2. divergence 项
3. 平滑项
4. 边界/速度上界项

#### B2. diffusion refinement

第二步做。

理由：

- 你已经有 `training/diffusion_baseline.py`
- 当前 Stage 4 也已写出：
  - `diffusion_condition_4d`
  - `diffusion_prior_*`

它可以作为：

> 在 PINN baseline 之后，进一步提高局地细节恢复的生成式方法。

### 阶段 C：论文最终主方法

最合理的题目方向是：

> 面向稀疏航空观测的图传播-物理引导生成式风场重构

具体方法结构可以写成：

1. 多源体素化
2. 空地一体图传播
3. Where2Comm 体素通信目标选择
4. baseline heuristic reconstruction
5. PINN refinement
6. diffusion refinement

---

## 6. 你的“协同感知 + PINN + diffusion + 神经网络”路线是否可行

答案是：**可行，而且路线很清晰。**

但最重要的是顺序：

### 不建议

- 现在立刻把 PINN 和 diffusion 直接塞进 Stage 3 在线逻辑里

### 建议

1. 保持 Stage 3 可解释图结构
2. 把 PINN 与 diffusion 放在 Stage 4 之后
3. 把当前 Stage 4 作为 baseline
4. 神经网络只做 refinement

这条线：

- 工程上稳
- 论文上清晰
- ablation 好做

---

## 7. 你下一步最该做什么

### 先做

1. 跑一版 full
2. 看 `stage4stats_full.log`
3. 确认当前 baseline 的全量分布

### 再做

4. 实现 PINN refinement baseline
5. 实现 diffusion refinement baseline

### 最后做

6. 写论文实验：
   - baseline
   - + graph propagation
   - + Where2Comm voxel targets
   - + PINN refinement
   - + diffusion refinement

---

## 8. 如果最终目标是飞机端实时风场预测

你的最终目标不是单纯“离线重构一张风场图”，而是：

> 在飞机飞行过程中，结合雷达拼图、颠簸报文、飞机间通信，  
> 做机载端的实时风场监控与短时预测，从而提升民航安全。

在这个目标下，当前工程应理解成：

### 8.1 Stage 3 的角色

Stage 3 更像：

- 空地一体协同感知图
- 飞机间风信息传播图
- 机载端可交换的协同先验

而不是最终预测器本身。

### 8.2 Stage 4 的角色

Stage 4 更像：

- 当前时刻风场重构器
- 短时一阶预测器
- 危险区代理量生成器

因此，最终机载端真正可部署的结构更适合是：

1. 当前时刻 baseline reconstruction
2. 下一时刻 short-horizon forecast
3. 风切变 / 颠簸代理风险提示
4. PINN / diffusion refinement

### 8.3 为什么这条路线合理

因为真实机载环境里通常没有 dense full-field 真值。

所以：

- 离线阶段做的是“可监督重构训练”
- 在线阶段做的是“无真值下的预测与风险监控”

这与当前工程已经补进去的：

- `forecast_u_3d`
- `forecast_v_3d`
- `forecast_confidence_3d`
- `hazard_shear_3d`
- `hazard_turbulence_3d`
- `hazard_alert_mask_3d`

是完全一致的。
