Stage 3 运行逻辑详解

一、Stage 3 的目标
Stage 3 的任务不是重新读取 Excel，而是站在 Stage 2 的结果之上，把体素化后的风观测和轨迹观测整理成飞行智能体（flight agents）以及它们之间的通信关系。

换句话说，Stage 3 负责把“点/体素”变成“可通信的智能体图”。

二、Stage 3 的输入
1. stage2_output/stage2_summary.json
   - 每一帧雷达对应的体素 npz 路径、时间戳、体素统计信息。

2. stage2_output/voxels/*.npz
   - 每一帧的体素结果。
   - 内含 wind_records、loc_records、motion_records、flight_motion_records、flight_raw_records、amdar_records、turb_records。

3. pipeline_config.py
   - 控制 Stage 3 的物理阈值、时间窗、通信邻居数、是否启用物理现实模式。

4. agent_builder.py
   - 真正构建 flight agent、通信边、风关联边的核心逻辑。

5. communication_builder.py
   - 负责 flight-flight 边的稀疏选择策略。

三、Stage 3 的整体流程

流程 1：读取 Stage 2 汇总
- 读取 stage2_summary.json。
- 获得每一帧的 vox_path 和时间信息。
- 若设置 WIND_MAX_FRAMES，则只取前 N 帧做小批量试跑。

流程 2：逐帧恢复 npz
- 对每一帧，读取对应的 npz。
- 将 npz 中的 records 恢复成 DataFrame。
- 得到 wind_grouped、loc_grouped、loc_motion_grouped、flight_motion_grouped、flight_raw_records、amdar_grouped、turb_grouped。

流程 3：构建航班候选
- 先按 flight_id 聚合，得到 raw candidates。
- 候选越多，不代表最终保留越多。
- 这些候选会继续经过地理解析、置信度评估、物理筛选。

流程 4：地理状态解析
- 对每个 flight，尝试从 flight_raw_records 中找经纬度、高度、时间。
- 计算与当前雷达帧的时间差 dt_sec。
- 如果原始记录解析失败，则用 flight_grouped 的体素中心做 fallback。
- 这里的原则是“尽量保留物理上合理的候选”，但不能脱离实际空间范围。

流程 5：逐个 flight 计算时空指标
对每个候选 flight，计算：
- dt_sec：与当前帧的时间差（秒）
- dh_km：飞行器位置到雷达原点（或参考点）的水平距离（千米）
- dz_m：飞行器高度与参考高度的垂直差（米）
- tc：时间置信度（time confidence）
- sc：空间置信度（space confidence）
- tl：时间似然（time likelihood）
- sl：空间似然（space likelihood）

其中：
- tc、sc 更像“硬阈值归一化后的置信度”
- tl、sl 更像“高斯衰减式概率/似然”

流程 6：tier1 / tier2 分层
- tier1：满足通信时间窗、空间窗、垂直窗的候选。
- tier2：不完全满足通信窗，但仍保留的补充候选。
- conf_mean：所有候选的平均置信度，通常用 tl × sl 计算。

流程 7：物理筛选
- 在启用 PHYSICS_REALISM_MODE 时，再进行一次质量过滤。
- 该步骤会根据 min_pair_score、min_tier2_score 去掉过弱候选。
- 目的不是删光，而是去掉显著不合理的候选。

流程 8：selected
- 从 tier1 / tier2 中选出最终 agent。
- 这些 agent 会参与通信边构建、风关联边构建和后续 Stage 4。

流程 9：通信构建
- 若 comm_round == 0，则在物理允许边内全连接。
- 若 comm_round >= 1，则对每个 agent 仅保留 top-k 邻居。
- 这样可以控制图规模。

流程 10：风关联和 flight-flight 关系
- 如果两个 flight 都有风观测，则可记录 wind relation。
- flight-flight 边会进一步区分：
  - ff_allowed
  - ff_motion_allowed
  - ff_wind_allowed

四、逐步调试日志的含义
1. raw candidates
   - 初始候选 flight 数。

2. geo resolved
   - 成功从原始 flight_frame 里解析出地理状态的候选数。

3. geo fallback filled
   - 用体素中心回退补齐后，最终可用于下游处理的候选数。

4. tier1/tier2 split
   - 按时空约束分层后的候选数。
   - conf_mean：平均置信度。

5. physics filter
   - 物理真实模式筛选后的保留数。
   - tier1_kept / tier2_kept：保留数。
   - tier1_drop / tier2_drop：删除数。
   - min_pair_score / min_tier2_score：当前阈值。

6. selected
   - 最终用于构建 agent 的数量。

7. 单 flight 详细日志
   - 每个 flight 都会打印：
     - dt_sec
     - dh_km
     - dz_m
     - tc
     - sc
     - tl
     - sl
   - 这样能精确判断某个候选为什么被筛掉。

五、Stage 3 输出
1. stage3_output/agents/frame_XXXX_agents.json
   - 每帧 flight agent 和通信图结构。

2. stage3_output/stage3_summary.json
   - 每帧统计摘要。
   - 用于 Stage 4 继续读取。

六、Stage 3 和 Stage 4 的关系
Stage 4 不再重新做 Stage 3 的筛选，而是直接读取：
- Stage 2 的体素结果
- Stage 3 的 agents 结果
并进一步执行风场重构和最终训练样本打包。

七、排错建议
1. 如果 valid_flight_agents 始终为 0，先看 geo resolved 和 conf_mean。
2. 如果 geo resolved 很高但 conf_mean 仍接近 0，说明时间窗或空间窗可能过严。
3. 如果 physics filter 一次把所有候选删光，先打印单 flight 日志，查看 dt_sec / dh_km / dz_m / tc / sc / tl / sl。
4. 如果通信边为 0，但 valid_flight_agents 不为 0，再检查 comm_round 和 max_neighbors_per_agent。
