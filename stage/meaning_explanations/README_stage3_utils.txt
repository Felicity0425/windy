Stage 3 参数、输入和输出说明

一、Stage 3 的输入
1. stage2_output/stage2_summary.json
   - 来源：Stage 2 汇总文件
   - 作用：提供每帧 vox_path、时间戳、风体素数、轨迹体素数等摘要信息

2. stage2_output/voxels/*.npz
   - 来源：Stage 2 每帧体素输出
   - 作用：恢复风观测、轨迹观测、运动观测、AMDAR/TURB 分组结果

3. schema_contract.py
   - 来源：项目级字段契约
   - 作用：统一 Stage 2 / 3 / 4 的 npz key 和 JSON key 名称

4. pipeline_config.py
   - 来源：项目级配置
   - 作用：提供空间范围、时间窗、通信参数、是否限制帧数等配置

二、Stage 3 的主要参数
1. cfg.MAX_FRAMES
   - 含义：小批量试跑时最多处理多少帧
   - 作用：避免一次全量跑太久

2. cfg.FLIGHT_AGENT_TOPK
   - 含义：每帧候选 flight agent 的 top-k 截断
   - 作用：减少 agent 数量，控制通信图规模

3. cfg.FLIGHT_TIER2_MAX
   - 含义：二级候选 flight agent 最大数量
   - 作用：限制次级候选集合

4. cfg.COMM_TIME_LIMIT_SECONDS / cfg.COMM_SPACE_LIMIT_KM / cfg.COMM_VERTICAL_LIMIT_M
   - 含义：通信用的时间、空间、垂直阈值

5. cfg.FF_COMM_* 参数
   - 含义：flight-flight 通信边筛选阈值
   - 作用：限制飞行器之间的通信边数

6. cfg.FF_MAX_NEIGHBORS_PER_AGENT
   - 含义：每个 agent 最多保留多少邻居

三、Stage 3 主要函数
1. load_stage2_voxel(frame_item)
   - 作用：从单帧 npz 中恢复体素记录，并转成 DataFrame
   - 输入：stage2_summary.json 中的一条 frame 记录
   - 输出：包含 wind_grouped / loc_grouped / motion_grouped / flight_motion_grouped / flight_raw_records / amdar_grouped / turb_grouped 的字典

2. build_agents_for_frame(vox)
   - 作用：针对单帧体素数据构建 flight agents 和通信关系
   - 输入：load_stage2_voxel 返回的单帧体素字典
   - 输出：该帧的 agents JSON 摘要（统计字段 + 输出路径）

3. main()
   - 作用：遍历 Stage 2 的 summary，逐帧生成 agents JSON 和 stage3_summary.json
   - 支持：WIND_MAX_FRAMES 小批量试跑

四、Stage 3 逐步筛选流程（参数表）
1. raw candidates
   - 含义：从 flight_grouped 按 flight_id 聚合得到的初始候选数
   - 统计口径：motion_count 汇总后，每个 flight 视作一个候选

2. geo resolved
   - 含义：从 flight_frame 中成功解析出经纬度、高度、时间，并能计算 dt_sec 的候选数
   - 说明：这是最理想的候选来源

3. geo fallback filled
   - 含义：对解析失败的候选，用 flight_grouped 的体素中心做保守回退补全
   - 说明：仍然保留物理约束，不放弃所有候选

4. tier1/tier2 split
   - 含义：根据时间/空间/垂直约束，把候选分成一级/二级
   - tier1：满足通信阈值的高优先级候选
   - tier2：不完全满足通信阈值，但保留的补充候选
   - conf_mean：所有候选的平均置信度，通常由 time_likelihood × space_likelihood 得到

5. physics filter
   - 含义：在物理真实模式下，对 tier1/tier2 再做一次质量筛选
   - tier1_kept / tier2_kept：筛选后保留下来的数量
   - tier1_drop / tier2_drop：被剔除的数量
   - min_pair_score / min_tier2_score：物理模式下的最低筛选阈值

6. selected
   - 含义：最终参与 agent 构建的 flight 数量
   - tier1_sel / tier2_sel：最终从两类候选中选中的数量

五、Stage 3 输出
1. stage3_output/agents/frame_XXXX_agents.json
   - 每帧的 flight agent、通信边、风相关关系结果

2. stage3_output/stage3_summary.json
   - 每帧统计摘要
   - 供 Stage 4 继续读取

六、Stage 3 和 Stage 4 的衔接
Stage 4 会基于 Stage 3 的 agents 结果，再融合 Stage 2 体素结果，执行风场重构并打包最终训练样本。

七、调试建议
1. 先用 WIND_MAX_FRAMES=10 做小批量试跑。
2. 检查 stage3_summary.json 中 valid_flight_agents 是否为正。
3. 检查通信边统计是否合理，不要全部为 0。
4. 如果耗时较长，先缩小 top-k 和邻居数量再全量跑。

五、Stage 3 和 Stage 4 的衔接
Stage 4 会基于 Stage 3 的 agents 结果，再融合 Stage 2 体素结果，执行风场重构并打包最终训练样本。

六、调试建议
1. 先用 WIND_MAX_FRAMES=10 做小批量试跑。
2. 检查 stage3_summary.json 中 valid_flight_agents 是否为正。
3. 检查通信边统计是否合理，不要全部为 0。
4. 如果耗时较长，先缩小 top-k 和邻居数量再全量跑。
