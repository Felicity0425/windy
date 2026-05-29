Stage 2 参数、输入和输出说明

一、Stage 2 的输入
1. stage1_output/clean_wind.parquet
   - 来源：Stage 1 清洗后的风观测数据
   - 关键字段：time_utc、lat_clean、lon_clean、alt_meters、wind_dir、wind_speed、u_wind、v_wind、obs_conf、source、flight_id

2. stage1_output/clean_loc.parquet
   - 来源：Stage 1 清洗后的轨迹数据
   - 关键字段：time_utc、lat_clean、lon_clean、alt_meters、heading_deg、ground_speed_ms、u_motion、v_motion、flight_id

3. stage1_output/radar_index.json
   - 来源：Stage 1 生成的雷达帧索引
   - 用途：遍历每一帧雷达图，获取文件名、时间戳、可用性和路径

4. stage1_output/frame_window_index.json
   - 来源：Stage 1 生成的时间窗索引
   - 用途：检查每帧雷达图的时间窗内是否有风/轨迹数据

5. radar/ 目录下的雷达图
   - 读取方式：_read_gray_image_robust
   - 用途：确定每帧的 x/y 网格尺寸

二、Stage 2 主要参数
1. cfg.TIME_WINDOW_MINUTES
   - 含义：雷达帧前后多少分钟的数据会被纳入体素化
   - 默认值：5

2. cfg.LAT_MIN / cfg.LAT_MAX
   - 含义：体素化空间的纬度范围

3. cfg.LON_MIN / cfg.LON_MAX
   - 含义：体素化空间的经度范围

4. cfg.ALT_MIN / cfg.ALT_MAX / cfg.DELTA_ALT / cfg.Z_DIM
   - 含义：高度离散化参数
   - 用于把连续高度转成 z 体素

5. radar 图像尺寸 H/W
   - 含义：由实际雷达拼图决定 x/y 方向的离散分辨率

三、Stage 2 主要函数
1. load_stage1_outputs()
   - 作用：读取 Stage 1 输出的 parquet 和索引文件

2. _df_to_records(df)
   - 作用：把 Polars DataFrame 转成普通 Python list[dict]
   - 用于写入 npz，方便 Stage 3 还原

3. voxelize_frame(df_wind, df_loc, radar_item)
   - 作用：对单帧雷达图执行体素化
   - 输出：该帧的 npz 文件和体素聚合摘要

4. main()
   - 作用：遍历所有可用雷达帧，依次调用 voxelize_frame，并写出 stage2_summary.json

四、Stage 2 输出
1. stage2_output/voxels/frame_XXXX_voxels.npz
   - 每一帧一个文件
   - 包含雷达图像、体素聚合结果、风观测、轨迹观测、运动观测

2. stage2_output/stage2_summary.json
   - 每帧的统计摘要
   - 可用于 Stage 3 继续读取

五、Stage 2 到 Stage 3 的衔接
Stage 3 会读取 stage2_summary.json，并使用 npz 中的 records 恢复为 DataFrame，再构建飞行智能体。

六、调试建议
1. 先用小批量 max_frames 验证单帧输出。
2. 检查 wind_voxels / traj_voxels / motion_voxels 是否合理。
3. 确认 npz 中的字段名和 schema_contract 一致。
4. 确认输出帧数可以被 Stage 3 正确读取。
