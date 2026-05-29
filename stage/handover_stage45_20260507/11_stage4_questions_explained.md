# Stage4 疑惑讲解与论文口径整理

> 本文根据 `讲解.pdf` 所在交接材料、当前 `Stage4` 本地日志、代码配置和 `workflow` 知识库整理。  
> 本文只作为新的 Markdown 讲解稿，不修改原始 `讲解.pdf`。

---

## 一、当前日志分析

当前分析对象：

```text
C:\Users\W11\Desktop\windy\stage\log\full_full_fast_stage4_frozen_v1__stage4_only
```

日志文件：

```text
stage4_full_fast_stage4_frozen_v1_stage4_only.log
```

### 1. 当前运行状态

日志中最后一次进度行显示：

```text
5350/7395 = 72.35%
elapsed=144h52m32s
eta=55h22m40s
```

说明：

- 总共计划处理 `7395` 帧。
- 当前已经处理到第 `5350` 帧左右。
- 当前日志处于中途运行状态，还不是最终完整结果。
- `stage4_summary.json` 通常要等 Stage4 完整结束后才会稳定生成，因此中途主要看 `stage4*.log`。

### 2. 已处理日志统计

当前日志中已统计到：

```text
frame_lines=5395
diag_lines=3144
triggered=3144
nontriggered=2251
trigger_ratio≈58.3%
```

含义：

- `frame_lines`：Stage4 已经写出的帧级日志行数。
- `diag_lines`：真正执行完整 `_prepare_frame()` 的诊断帧数量。
- `triggered`：触发完整重构的帧数。
- `nontriggered`：没有触发完整重构的轻量帧数。
- `trigger_ratio≈58.3%`：约 58.3% 的已处理帧做了完整重构。

这符合当前 Stage4 的事件触发式设计：不是每一帧都强行完整重构，而是在风、运动、通信结构、seed 等发生明显变化时触发完整处理。

### 3. 当前核心数值

触发帧上的重构质量代理指标大致为：

```text
coverage mean≈0.0553
coverage p50≈0.0518
coverage p90≈0.0773

conf_mean mean≈0.2640
conf_mean p50≈0.2558
conf_mean p90≈0.3081

recon_vox mean≈199
recon_vox p50=222
recon_vox p90=342

comm_joint mean≈1095
comm_joint p50=1448
comm_joint p90=1693
```

通俗解释：

- `coverage`：当前帧有效重构体素占目标重构域的比例。
- `conf_mean`：有效重构区域的平均置信度。
- `recon_vox`：实际重构出来的有效风场体素数量。
- `comm_joint`：Where2Comm 风格体素级通信目标数量。

当前结果说明：

- Stage4 不是空跑，已经持续生成有效风场体素。
- coverage 不高，但这是稀疏航空观测数据下的正常现象。
- confidence 处于温和区间，没有被暴力抬高。
- 通信目标规模较大，说明 Stage4 仍在构建协同感知相关的空间目标。

### 4. `wind_primary=0` 的真实含义

当前最容易误解的现象是：

```text
wind_raw_positive=2275/3144
wind_primary_nonzero=0/3144
```

也就是说：

- 很多帧有 `wind_raw > 0`。
- 但所有已统计诊断帧中 `wind_primary` 都是 `0`。

这不等于：

```text
Stage4 完全没有风观测
```

也不等于：

```text
Stage4 已经失效
```

更准确的解释是：

```text
aggregate wind_grouped 与 amdar/turb 分源风观测高度重叠。
为了避免同一批风体素在 wind_grouped + amdar_grouped/turb_grouped 中被重复计权，
Stage4 将 wind_grouped 中的重叠项去掉。
```

因此日志里会出现：

```text
wind_raw=61
wind=61
overlap=1.000
removed=61
wind_primary=0
```

它的意思是：

```text
这 61 个聚合风体素与 amdar/turb 分源体素完全重叠，
aggregate wind 分支被去重清空。
```

但 Stage4 仍然可能通过以下通道使用直接风源：

```text
amdar_grouped
turb_grouped
direct_source_count
direct_agreement
```

所以论文或汇报中不能简单说：

```text
直接风观测为 0
```

应该说：

```text
aggregate wind_primary 在当前去重策略下为 0；
直接风源贡献需要从 amdar/turb/direct_source_count/direct_agreement_mean 进一步统计。
```

### 5. 当前日志暴露出的注意点

当前目录名是：

```text
full_fast_stage4_frozen_v1
```

但日志开头显示实际 profile 为：

```text
output_profile=full_aux
quality_profile=aux_aggressive
quality_expand_enabled=1
```

这说明命名和实际运行配置存在不一致。后续记录实验结果时，必须按日志里的真实配置写清楚，避免把它误写成纯 `S5 FinalFast`。

---

## 二、Stage3 智能体与通信机制

### 1. 同一个航班是否会被当成多架飞机

不会。

当前逻辑是：

```text
原始航班号/机尾号/flight_id
  -> 统一成 flight_id
  -> 同一帧内按 flight_id 聚合
  -> 每个 flight_id 构建一个 flight agent
```

同一个航班连续发出多条数据时，系统理解为：

```text
同一架飞机在同一时间窗内的多条观测记录
```

而不是：

```text
多架不同飞机
```

但如果同一航班跨越多个雷达时间帧，它会在不同帧中分别出现。这表示该航班在不同时间的状态，不是重复计作多架飞机。

### 2. 智能体筛选分层

Stage3 将候选航班分成两类：

```text
Tier1：空地可通信 agent
Tier2：不可直接空地通信，但仍有感知价值的 agent
```

候选 agent 会根据当前帧的动态地面参考点计算：

```text
dt_sec：航班观测时间与当前雷达帧时间差
dh_km：航班位置与地面参考点水平距离
dz_m：航班高度与地面参考点高度差
```

### 3. 空地通信物理门槛

当前配置中，空地通信可达的基本条件为：

```text
dt_sec <= 300 秒
dh_km <= 300 km
dz_m <= 5000 m
```

满足这些条件的航班进入 Tier1。

同时会计算：

```text
time_conf
space_conf
time_likelihood
space_likelihood
st_conf = time_conf * space_conf
st_likelihood = time_likelihood * space_likelihood
```

这些值用于描述该航班对当前帧的时空可信程度。

### 4. 空空通信物理门槛

飞机之间是否建立空空通信边，使用更严格的物理约束：

```text
dt_ff <= 120 秒
dh_ff <= 200 km
dz_ff <= 2000 m
```

含义：

- 两架飞机时间上要足够接近。
- 水平距离不能太远。
- 垂直高度差不能太大。

这样可以避免把相隔很远、不同高度层、不同时间状态的飞机强行连边。

### 5. 风能力节点与风边

每个 flight agent 会判断是否具备风能力：

```text
有 AMDAR 证据
或时空置信度足够高
```

飞机间风边采用强弱两级：

```text
两端都有风能力：强风边
只有一端有风能力：弱风边
两端都无风能力：不建风边
```

这使得 Stage3 不会只依赖硬 AMDAR 映射，而是允许在稀疏数据条件下建立软风传播结构。

### 6. 当前通信和卫星的关系

当前代码事实是：

```text
没有真实 satellite/卫星 数值变量。
```

当前真实通信链路是三层：

```text
1. 飞机 -> 地面参考点
2. 飞机 -> 飞机
3. Stage4 体素级 Where2Comm 通信目标
```

因此不能在论文中写成：

```text
当前实验包含显式卫星链路建模
```

更合理的表达是：

```text
当前系统建模的是空地一体协同感知中的通信可达性和高价值区域选择。
卫星可作为未来空天地通信体系中的中继或回传基础设施，
但当前数值实验尚未显式建模卫星链路。
```

### 7. Where2Comm 体素级通信目标

Stage4 中的 `comm_joint` 不是飞机数量，而是体素级通信目标数量。

当前 Where2Comm 风格目标包含三类分支：

```text
wind branch：高置信风观测体素优先通信
motion branch：高运动密度/高 support 区域优先通信
uncertainty branch：support 高但当前重构置信度低的区域优先通信
```

最后三者合成：

```text
joint branch
```

这对应 Where2Comm 的核心思想：

```text
不是传完整场，而是只传空间上高价值的位置。
```

---

## 三、气象雷达拼图与地面点

### 1. 气象雷达拼图在当前工程中的作用

气象雷达拼图不是当前 Stage4 中的直接三维风场真值。

它主要有三层作用：

```text
1. 时间帧基准
2. 二维空间网格底板
3. 后续训练/refinement 的条件背景
```

具体来说：

- 每张雷达拼图对应一个时间帧。
- Stage2 根据这张雷达图的时间，筛选前后时间窗内的风观测和轨迹观测。
- 雷达图像的 H/W 决定 x/y 网格尺寸。
- 风观测、航迹观测、运动观测都会投影到这个网格上。
- Stage4 输出中会保存 `radar_2d`，并在 diffusion 条件中把雷达图复制成 3D 背景条件。

### 2. 气象雷达拼图的经纬度范围

当前代码中，气象雷达拼图使用固定地理范围：

```text
纬度 lat：12.2 到 54.2
经度 lon：73.0 到 135.0
```

也就是覆盖中国及周边较大区域。

注意：

```text
这个范围不是从每张 PNG 图片里自动读取的。
```

它来自全局配置：

```text
pipeline_utils.py
LAT_MIN, LAT_MAX = 12.2, 54.2
LON_MIN, LON_MAX = 73.0, 135.0
```

### 3. 高度范围

垂直方向配置为：

```text
ALT_MIN = 0 m
ALT_MAX = 15000 m
DELTA_ALT = 500 m
Z_DIM = 31
```

也就是说：

```text
0 到 15000 米，每 500 米一层，共 31 个高度层。
```

### 4. 像素如何映射到经纬度

假设雷达图像大小为：

```text
H_DIM x W_DIM
```

则每个像素对应的经纬度分辨率大致为：

```text
delta_lat = (54.2 - 12.2) / H_DIM
delta_lon = (135.0 - 73.0) / W_DIM
```

投影公式大致是：

```text
x = (lon - LON_MIN) / delta_lon
y = (LAT_MAX - lat) / delta_lat
z = (alt - ALT_MIN) / DELTA_ALT
```

因此：

- `x` 表示东西向网格位置。
- `y` 表示南北向网格位置。
- `z` 表示高度层。

### 5. 地面点为什么要动态选取

Stage3 里有一个地面参考点，也就是：

```text
ground_radar_center
```

它不是固定取中国区域几何中心，而是根据每帧航班分布动态估计。

估计逻辑包括：

```text
1. 当前帧航班经纬高的鲁棒中心
2. 按 flight_id 观测数加权的中心
3. 体素中心的轻微回拉
4. 最后裁剪到有效经纬高范围内
```

这样做的意义是：

- 避免固定地理中心导致所有航班距离过大。
- 让空地通信可达性更贴近当前帧真实航班分布。
- 给每帧构建一个合理的 ground agent。
- 作为 flight agent 时空置信度和通信权重的参考点。

通俗解释：

```text
地面点就是当前帧航空观测群的动态服务中心。
它不代表真实雷达站坐标，而是用于空地协同建模的参考代理。
```

---

## 四、如何解释当前工作

### 1. 不建议这样解释

不建议把当前项目说成：

```text
我们做了一个最强天气预报模型。
```

也不建议说成：

```text
我们用雷达直接反演了完整三维风场。
```

原因：

- 当前数据不是全球再分析数据，也不是完整真值风场。
- 当前雷达拼图主要提供网格、时间帧和背景条件，不是双多普勒三维风反演输入。
- 当前 Stage4 是稀疏多源观测下的状态构建层，不是最终端到端预测网络。

### 2. 推荐解释

更合理的项目定位是：

```text
面向空地一体协同感知的多源稀疏航空观测风场状态构建方法。
```

或者：

```text
多源稀疏航空观测驱动的局地三维风场状态构建与协同感知样本生成系统。
```

通俗表达：

```text
我们不是直接预测未来天气，
而是先把飞机观测、风观测、运动轨迹、雷达拼图和通信结构整理成一个可解释的三维风场状态层。
这个状态层可以用于论文消融，也可以作为后续 Stage5 事件驱动短时预测的输入。
```

### 3. 当前工作和知识库文献的对照

`workflow` 知识库给出的合理对照如下。

#### Aircraft-derived meteorological observations / EMADDC / Mode-S

对应当前项目中的：

```text
AMDAR
飞机衍生风观测
航迹/运动数据
```

可用于说明：

```text
飞机本身可以成为高体量、高时效的气象观测源。
```

#### Wind field reconstruction

对应当前项目中的：

```text
Stage4 recon_u/recon_v/recon_confidence/recon_mask
```

可用于说明：

```text
稀疏观测恢复更完整风场是一个合理研究问题。
```

#### Where2Comm / Spatial confidence map

对应当前项目中的：

```text
comm_wind
comm_motion
comm_uncertainty
comm_joint
```

可用于说明：

```text
通信不需要传完整场，而应只传高价值空间区域。
```

#### Multi-aircraft collaborative perception

对应当前项目中的：

```text
flight agents
flight-communication graph
flight-flight wind/motion edges
ground agent
```

可用于说明：

```text
航空气象态势感知不是单机问题，而是通信受限下的多机协同感知问题。
```

#### PINN / Multi-scale PINN / diffusion

对应当前项目中的：

```text
pinn_divergence_3d
pinn_smoothness_3d
physics_weight_3d
diffusion_condition_4d
```

可用于说明：

```text
当前 Stage4 已经为后续物理约束 refinement 或生成式 refinement 预留接口。
```

### 4. 当前结果的论文口径

当前结果应该这样说：

```text
Stage4 已经能够在稀疏航空观测条件下，持续生成局地三维风场状态、置信度层、通信目标和风险代理量。
```

但也要诚实说明：

```text
当前 aggregate wind_primary 在去重策略下长期为 0。
这说明直接风源贡献不能只看 wind_primary，
需要进一步统计 amdar/turb/direct_source_count/direct_agreement_mean。
```

建议论文中把当前 Stage4 定义为：

```text
可解释的状态构建 baseline
```

而不是：

```text
最终最优风场重构模型
```

---

## 五、后续建议补查指标

为了证明 Stage4 仍然使用了直接风源，建议后续补查：

```text
amdar_voxels
amdar_voxels_raw
turb_voxels
turb_voxels_raw
direct_source_count
direct_agreement_mean
recon_conf_mean
recon_coverage_ratio
sparse anchor metrics
```

推荐解释逻辑：

```text
如果 amdar/turb/direct_source_count 非 0，
说明直接风源仍然存在，只是 aggregate wind_grouped 被去重逻辑清空。
```

这能避免误把：

```text
wind_primary=0
```

解释成：

```text
Stage4 完全没有直接风观测。
```

---

## 六、一句话总结

当前 Stage4 的意义不是“把 coverage 做到很高”，而是：

```text
在稀疏、多源、时序不连续的航空观测条件下，
构建一个可解释、可运行、可消融、可作为后续预测输入的局地三维风场状态层。
```

当前最重要的注意事项是：

```text
wind_primary=0 是去重策略下的统计现象，不应直接等同于风源失效；
卫星尚未进入当前数值通信链路；
气象雷达拼图负责时间帧、二维网格和训练条件，不是直接三维风场真值。
```
