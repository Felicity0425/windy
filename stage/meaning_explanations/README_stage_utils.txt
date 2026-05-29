转换脚本与阶段脚本的参数和函数含义说明

tmux attach -t windy

一、convert_excel_to_parquet_robust.py 主要参数
1. --excel
   - 含义：要转换的 Excel 文件路径。
   - 用法：可以重复多次，表示多个工作簿一起转换。

2. --out-root
   - 含义：parquet 输出根目录。
   - 作用：根据工作簿类型自动创建对应的输出子目录。

3. --max-sheets
   - 含义：每个工作簿最多转换多少个 sheet。
   - 作用：用于小批量测试，避免一次全量跑完。

4. --sheet-offset
   - 含义：从第几个 sheet 开始转换（从 0 开始）。
   - 作用：用于分批处理长工作簿。

二、convert_excel_to_parquet_robust.py 主要函数
1. _parse_excel_time_to_dt(v)
   - 作用：把 Excel 里的单个时间单元格解析为 pandas.Timestamp。
   - 支持：字符串时间、Excel 序列日期、截断年份格式等。

2. _series_to_beijing_utc(series)
   - 作用：把一列北京时间解析成北京时间字符串和 UTC 字符串。
   - 返回：time_beijing / time_utc。

3. _parse_coord(v, axis)
   - 作用：把单个经纬度单元格解析成十进制度。
   - 支持：N28203089、E109390986、纯数字、带方向前缀的格式。

4. _normalize_location_df(df, pd)
   - 作用：标准化 location 工作簿的一张 sheet。
   - 输出：time_utc、lat_clean、lon_clean、alt_meters、heading_deg、ground_speed_ms、flight_id、u_motion、v_motion。

5. _normalize_amdar_df(df, pd)
   - 作用：标准化 amdar 工作簿的一张 sheet。
   - 输出：time_beijing、time_utc、lat_clean、lon_clean、alt_meters、wind_dir、wind_speed、u_wind、v_wind、flight_id。

6. _normalize_turb_df(df, pd)
   - 作用：标准化 turb 工作簿的一张 sheet。
   - 输出：time_beijing、time_utc、lat_clean、lon_clean、alt_meters、wind_dir、wind_speed、u_wind、v_wind、flight_id，以及姿态/扰动原始字段。

三、Stage 1 脚本含义
- 读取三个 parquet 输入：location / amdar / turb。
- 统一成标准字段。
- 生成 Stage 2、Stage 3、Stage 4 会使用的中间数据。

四、Stage 2 脚本含义
- 把 Stage 1 的数据投影到雷达帧对应的体素网格里。
- 输出每帧的 voxel npz。

五、Stage 3 脚本含义
- 根据 Stage 2 体素结果构建飞行智能体和通信关系。
- 输出每帧 agent json。

六、Stage 4 脚本含义
- 读取 Stage 2 / Stage 3 结果，重构风场并打包最终训练样本。
- 输出最终 npz。

七、调试建议
- 先小批量跑，再看 null_ratio。
- 先验证时间列，再验证坐标列，最后再看风向风速。
- 如果时间列仍为空，优先回头检查 Excel 原始列名和原始值格式。
