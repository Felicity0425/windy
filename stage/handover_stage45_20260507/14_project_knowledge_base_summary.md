# 空地一体协同感知稀疏多源风场重建项目知识库总览

## 这份文档的作用

这是一份面向后续知识库构建的“项目全景总结”。  
目标不是只记录某个脚本怎么跑，而是把项目从数据、分阶段设计、关键脚本、真实输出、代表性结果、当前边界与后续方向完整讲清楚。

建议把这份文档当作后续知识库的总入口。  
如果需要继续深入某一阶段，再联动阅读：

- `stage/handover_stage45_20260507/00_overview.md`
- `stage/handover_stage45_20260507/01_stage34_pipeline.md`
- `stage/handover_stage45_20260507/02_stage4_modification_and_freeze.md`
- `stage/handover_stage45_20260507/03_stage4_paper_experiment_matrix.md`
- `stage/handover_stage45_20260507/12_stage4_anchor_fallback_and_3d_visualization.md`
- `stage/handover_stage45_20260507/13_stage5_and_real_3d_wind_plan.md`

---

## 一、项目总体目标

这个项目的目标可以概括为：

**面向空地一体协同感知的稀疏多源风场重建，以及在此基础上的事件驱动实时风场预测。**

从工程角度看，这个目标被拆成了 5 个阶段：

1. `Stage1`：读取和清洗原始观测，形成统一中间数据。
2. `Stage2`：把观测投影到与雷达拼图一致的三维体素网格。
3. `Stage3`：基于体素结果构建飞行智能体和通信图。
4. `Stage4`：融合 Stage2/Stage3 结果，重构稀疏多源风场状态层，并输出训练样本。
5. `Stage5`：在冻结后的 Stage4 状态层上，做事件驱动、ROI 聚焦的 refinement / 预测原型。

当前项目的实际重心是：

- `Stage4` 已经接近冻结，是当前主结果链路。
- `Stage5` 仍然是独立 scaffold，但已经可以读取 Stage4 输出、接入 ERA5 / GFS / GDAS 背景场，并做小样本 3D refinement 与对比。

---

## 二、数据与空间时间设定

### 1. 数据类型

项目当前主要使用四类观测 / 背景信息：

- 航空风观测：AMDAR、turbulence、派生 wind 记录。
- 航迹 / 位置观测：location 类原始轨迹数据。
- 雷达拼图：二维全国雷达拼图，作为空间参考底板和帧时间轴。
- 外部三维背景场：ERA5、GFS、GDAS 等 pressure-level 背景场。

### 2. 当前空间范围

项目默认覆盖中国区域 bbox：

```text
lat: 12.2 -> 54.2
lon: 73.0 -> 135.0
alt: 0 -> 15000 m
z step: 500 m
```

对应配置来自 [pipeline_config.py](/data/LFT-W02_data/pengxu/pipeline_config.py:1)。

项目内部三维网格的关键设定是：

- 水平范围由雷达图像的 `H x W` 决定。
- 垂直方向固定离散为 `0-15000m`，步长 `500m`。
- 因此 `Z_DIM = 31`。

### 3. 当前时间组织方式

- 雷达帧是整个项目的时间基准。
- Stage1/2 默认使用雷达帧前后 `5` 分钟时间窗聚合同步观测。
- Stage4 引入显式时序依赖，使用 `prev_recon_state`、temporal background 和 forecast。
- Stage5 在关键帧模式下读取指定历史 `time_str`，在 rolling ROI 模式下处理指定新到帧。

### 4. 当前原始清洗后的数据规模

来自 `stage1_output/stage1_summary.json` 的真实统计：

```text
clean_wind_rows = 431189
clean_loc_rows  = 19162638
radar_total     = 7396
radar_usable    = 7395
window_records  = 7395
```

这说明：

- 风观测总量远少于轨迹观测，属于典型稀疏监督场景。
- 雷达帧数量约 7395，是后续 Stage2-Stage4 的主时序长度。

---

## 三、Stage1：原始观测读取与清洗

### 1. 目标

`Stage1` 的职责是把不同来源、不同字段风格的原始观测整理成统一的中间表，并建立雷达帧索引。

它不做体素化、不做风场重构，只做：

- 读取 parquet / manifest
- 字段清洗和统一命名
- 时间字段归一化
- 风速 / 航向转换为 `u/v`
- 生成雷达帧索引和时间窗索引

### 2. 当前主脚本

[stage1_prepare.py](/data/LFT-W02_data/pengxu/stage/stage1_prepare.py:1)

脚本头部注释已经明确了 Stage1 的输出：

- `stage1_output/clean_wind.parquet`
- `stage1_output/clean_loc.parquet`
- `stage1_output/radar_index.json`
- `stage1_output/frame_window_index.json`
- `stage1_output/stage1_summary.json`

### 3. 关键输入

输入目录由 [pipeline_config.py](/data/LFT-W02_data/pengxu/pipeline_config.py:1) 统一控制，当前核心包括：

- `location_location_parquet`
- `amdar_parquet`
- `turb_parquet`
- `radar/` 或同级雷达拼图目录

### 4. 关键处理逻辑

Stage1 做了几件很重要的规范化工作：

- 把风类输入统一到 `time_utc / lat_clean / lon_clean / alt_meters / u_wind / v_wind / obs_conf / source / flight_id`
- 把轨迹类输入统一到 `time_utc / lat_clean / lon_clean / alt_meters / heading_deg / ground_speed_ms / u_motion / v_motion / flight_id`
- 生成 `radar_index.json`，记录每帧雷达文件名、时间戳、路径和是否可用
- 生成 `frame_window_index.json`，记录每帧雷达对应时间窗里有多少风/轨迹记录

### 5. 当前真实输出示例

`clean_wind.parquet` 的真实字段示例：

```text
rows = 431189
cols = 40
columns = ['机尾号', '航班号', '时间（北京时）', '飞行阶段', '纬度', '经度', '高度', '静温', '风向', '风速', ... , 'time_utc', 'lat_clean', 'lon_clean', 'alt_meters']
```

`clean_loc.parquet` 的真实字段示例：

```text
rows = 19162638
cols = 25
columns = ['接收时间（UTC）', '机尾号', '航班号', '纬度', '经度', '高度', '航向角', '地速', ... , 'time_utc', 'lat_clean', 'lon_clean', 'alt_meters', 'heading_deg', 'ground_speed_ms', 'flight_id', 'u_motion', 'v_motion']
```

可以看到：

- 风观测更稀疏，但字段更丰富，包含风向风速等物理量。
- 轨迹观测量级巨大，是后续轨迹体素化和 flight agent 构建的主体来源。

### 6. 当前边界

- Stage1 不做空间投影和体素化。
- 它只是中间层，不直接面向 Stage4/Stage5 可视化。
- 但它的字段统一程度决定了后续各阶段是否稳定。

### 7. Stage1 的验证与“可视化/日志”链路

Stage1 当前没有单独的 PNG 类可视化产物，但并不等于没有验证链路。  
它的正确性主要通过以下几类“数据检查型可视化/日志”来判断：

1. `stage1_summary.json`
   - 看总行数、雷达帧数、可用帧数是否合理。

2. `radar_index.json`
   - 检查雷达帧是否成功解析时间戳、是否可用。

3. `frame_window_index.json`
   - 检查每帧时间窗内是否确实能匹配到风/轨迹记录。

4. `check_stage1_stage2_alignment.py`
   - 这是当前最接近“Stage1 数据处理可视化/诊断”的检查脚本。
   - 它会检查：
     - 雷达帧与 location 时间范围是否重叠
     - 每帧时间窗内有多少 `loc_rows / wind_rows`
     - 清洗后的轨迹数据能否落进 Stage2 的体素网格
     - `in_range_ratio` 是否合理

5. Stage2 日志反推 Stage1 是否正确
   - 例如早期运行日志中的 `stage2_topwind.log`
   - 如果 Stage2 能稳定输出非空 `wind_voxels / traj_voxels / motion_voxels`，通常说明 Stage1 的时间归一化和空间字段清洗没有跑偏。

因此，在知识库中更合适的说法是：

- Stage1 的“可视化”以表格、索引、时间窗和对齐检查报告为主；
- Stage2 开始才进入真正的逐帧空间可视化和后续 2D/3D 图形解释。

---

## 四、Stage2：雷达帧体素化

### 1. 目标

`Stage2` 把 Stage1 清洗后的观测投影到与雷达帧一致的三维体素网格里，为后续 Stage3/Stage4 建立统一空间参考系。

核心思想是：

- 每一帧雷达拼图对应一个 `z-y-x` 三维体素空间。
- 把风观测、轨迹观测、运动观测都映射到这个空间里。
- 在同一体素内做聚合，形成体素级统计。

### 2. 当前主脚本

[stage2_voxelize.py](/data/LFT-W02_data/pengxu/stage/stage2_voxelize.py:1)

### 3. 当前输入

来自 Stage1：

- `stage1_output/clean_wind.parquet`
- `stage1_output/clean_loc.parquet`
- `stage1_output/radar_index.json`
- `stage1_output/frame_window_index.json`

以及雷达图像本身：

- `radar/` 目录下的每帧 PNG

### 4. 关键处理逻辑

每一帧主要做以下工作：

1. 读取雷达图，得到水平网格 `H x W`。
2. 根据当前雷达时间，取前后 `5` 分钟窗的风/轨迹观测。
3. 用 bbox 和雷达图尺寸把经纬度映射到 `x/y`。
4. 用 `alt_meters` 映射到离散高度层 `z`。
5. 对相同体素做聚合，得到：
   - `wind_grouped`
   - `loc_grouped`
   - `loc_motion_grouped`
   - `flight_motion_grouped`
   - `flight_raw_records`
   - `amdar_grouped`
   - `turb_grouped`
6. 把结果写成逐帧 `frame_<time>_voxels.npz`。

### 5. 当前输出

- `stage2_output/voxels/*.npz`
- `stage2_output/stage2_summary.json`

### 6. 当前真实统计

`stage2_summary.json` 总帧数：

```text
7395
```

总体统计：

```text
wind_voxels mean   = 13.761
traj_voxels mean   = 3943.035
motion_voxels mean = 3539.923
nonzero_wind_frames = 5552
nonzero_turb_frames = 87
```

这说明：

- 轨迹 / 运动体素远多于风体素，稀疏性非常明显。
- turbulence 相关体素极少，是高价值但极稀疏来源。

### 7. 代表性结果示例

按 `wind_voxels` 排名前几的帧：

- `20260208124800`: `wind_voxels=140`, `motion_voxels=5225`, `amdar_voxels=140`
- `20260206174200`: `wind_voxels=120`, `motion_voxels=1441`, `amdar_voxels=120`
- `20260207022400`: `wind_voxels=111`, `motion_voxels=5040`, `amdar_voxels=111`

按 `traj_voxels` 排名前几的帧：

- `20260215063600`: `traj_voxels=6213`, `motion_voxels=5276`
- `20260215063000`: `traj_voxels=6191`, `motion_voxels=5354`

按 `turb_voxels` 排名前几的帧：

- `20260215152400`: `turb_voxels=3`, `wind_voxels=65`
- `20260223134200`: `turb_voxels=2`, `wind_voxels=73`

这些例子说明 Stage2 已经把“风很稀疏、轨迹很密集、turb 更稀疏”的数据现实保留下来了。

### 8. 当前边界

- Stage2 仍然是观测组织层，不做通信图和风场重构。
- 它决定了 Stage3/4 是否能在统一空间里工作。

### 9. Stage2 的验证、日志与可视化解释

Stage2 是第一个真正进入“逐帧空间结果检查”的阶段。  
它的正确性主要通过以下方式判断：

1. `stage2_summary.json`
   - 检查每帧 `wind_voxels / traj_voxels / motion_voxels / amdar_voxels / turb_voxels` 是否合理。

2. 代表性高风帧 / 高轨迹帧样例
   - 例如 `20260208124800`、`20260206174200`、`20260215063600`。
   - 这些帧可用来判断体素聚合是否和原始观测密度变化一致。

3. Stage2 运行日志
   - 例如 `stage/logs/topwind_auto/stage2_topwind.log`
   - 主要用于确认体素化批处理是否顺利完成、时间窗是否命中数据。

4. Stage1/Stage2 对齐检查脚本
   - `check_stage1_stage2_alignment.py`
   - 它本质上也是 Stage2 的前置验证工具，因为它直接检查清洗结果是否能成功落到体素网格。

在知识库里，可以把 Stage2 的结果解释成：

- “观测点 -> 雷达帧三维体素”的映射是否成功；
- 哪些帧风观测特别强、哪些帧主要靠轨迹 / 运动支撑；
- turbulence 在整个时间轴上有多稀疏。

---

## 五、Stage3：飞行智能体与通信图构建

### 1. 目标

`Stage3` 的目标不是重构风场，而是把 Stage2 的体素结果转换成“飞行智能体 + 通信图”。

可以理解为：

- Stage2 解决“观测点在哪”。
- Stage3 解决“哪些飞行体在这一帧是有效 agent，它们之间如何通信、如何形成 flight-flight 关系”。

### 2. 当前主脚本

[stage3_agents_v2.py](/data/LFT-W02_data/pengxu/stage/stage3_agents_v2.py:1)

注意：

- 当前真实主线是 `stage3_agents_v2.py`
- `stage3_agents.py` 不是当前主线

### 3. 当前输入

来自 Stage2：

- `stage2_output/stage2_summary.json`
- `stage2_output/voxels/*.npz`

### 4. 关键处理逻辑

Stage3 做了以下几层事情：

1. 逐帧恢复 Stage2 的 grouped records。
2. 从 `flight_raw_records` / `flight_motion_grouped` 中构建 flight candidates。
3. 解析每个 flight 的地理状态：
   - `lat/lon/alt`
   - `dt_sec`
   - 代表性轨迹位置
4. 基于时间、空间、垂直差计算：
   - `time confidence`
   - `space confidence`
   - `time likelihood`
   - `space likelihood`
5. 对候选做 `tier1 / tier2` 分层。
6. 在物理真实模式下再做筛选。
7. 构建：
   - `flight_comm_allowed`
   - `ff_allowed`
   - `ff_motion_allowed`
   - `ff_wind_allowed`

### 5. 当前输出

- `stage3_output_v2/agents/*.json`
- `stage3_output_v2/stage3_summary.json`

### 6. 当前真实统计

`stage3_summary.json` 总帧数：

```text
7395
```

总体统计：

```text
valid_flight_agents mean      = 492.362
flight_comm_allowed mean      = 97.172
flight_ff_allowed_edges mean  = 4670.483
flight_ff_wind_edges mean     = 1345.936
```

这说明：

- 每帧 flight agents 数量相当可观，Stage3 已经形成了稠密通信图基础。
- `ff_wind_edges` 虽然低于 `ff_allowed_edges`，但已经远不是全 0。

### 7. 代表性结果示例

按 `valid_flight_agents` 排名前几的帧：

- `20260212061200`: `valid_flight_agents=782`
- `20260215103000`: `valid_flight_agents=776`
- `20260214064200`: `valid_flight_agents=771`

按 `flight_ff_allowed_edges` 排名前几的帧：

- `20260205061200`: `flight_ff_allowed_edges=7783`
- `20260212060600`: `flight_ff_allowed_edges=7779`
- `20260223063000`: `flight_ff_allowed_edges=7754`

按 `flight_ff_wind_edges` 排名前几的帧：

- `20260215062400`: `flight_ff_wind_edges=7644`
- `20260215051800`: `flight_ff_wind_edges=7615`
- `20260214063600`: `flight_ff_wind_edges=7612`

这些结果说明：

- Stage3 已经把稀疏体素观测转换成了规模化的时空图结构。
- 这一步为 Stage4 后续的通信引导和多源融合提供了结构信息，而不仅是观测密度信息。

### 8. 当前边界

- Stage3 可以多进程 shard 并行，因为更接近 frame-level 独立任务。
- 它不依赖 `prev_recon_state`，所以天然比 Stage4 更适合并行。

### 9. Stage3 的验证、日志与解释

Stage3 的验证重点不是“图像好不好看”，而是：

- agent 数量是否合理
- 通信边是否非零
- wind relation 是否长期全灭

当前主要检查材料包括：

1. `stage3_summary.json`
   - 看 `valid_flight_agents`
   - 看 `flight_comm_allowed_agents`
   - 看 `flight_ff_allowed_edges`
   - 看 `flight_ff_wind_edges`

2. Stage3 运行日志
   - 例如：
     - `stage3wind_*.log`
     - `stage3_*.log`
   - 用于看候选 flight、tier1/tier2、风能力激活是否正常。

3. Stage3 调试说明文档
   - `stage/meaning_explanations/README_stage3_utils.txt`
   - `stage/meaning_explanations/README_stage3_debug_flow.txt`

4. 代表性统计样例
   - 高 `valid_flight_agents` 帧
   - 高 `flight_ff_allowed_edges` 帧
   - 高 `flight_ff_wind_edges` 帧

从知识库角度，Stage3 的核心解释应是：

- 它把稀疏体素观测升级成“可通信的 flight graph”；
- 它的正确性主要体现在图结构统计，而不是平面图像。

---

## 六、Stage4：多源风场重构与状态层构建

### 1. 目标

`Stage4` 是当前整个项目的核心。  
它负责把 Stage2 的体素观测和 Stage3 的智能体/通信图真正融合成“风场状态层”。

它不是单纯做插值，而是把以下模块组合起来：

- support fill
- temporal fill
- relax
- prune
- expand
- direct anchor restore
- direct anchor force
- primary anchor fallback
- fast / full_aux_export 双路径

### 2. 当前主脚本

[stage4_pack_v2.py](/data/LFT-W02_data/pengxu/stage/stage4_pack_v2.py:1)

注意：

- 当前真实主线是 `stage4_pack_v2.py`
- `stage4_pack.py` 不是当前主线

### 3. 当前输入与输出

输入：

- `stage2_output/*.npz`
- `stage3_output_v2/agents/*.json`

正式输出：

- `/data/LFT-W02_data/pengxu/stage4_output_v2/frame_*.npz`
- `/data/LFT-W02_data/pengxu/stage4_output_v2/stage4_summary.json`

训练前 full aux 导出目录：

- `/data/LFT-W02_data/pengxu/stage4_output_full_aux_v2/<RUN_LABEL>`

### 4. 当前运行链路特点

Stage4 与 Stage3 最大的区别是它带时序状态：

- `prev_recon_state`
- `temporal_background`
- `forecast_next_wind_field`
- `trigger_reconstruction`

因此：

- `Stage4` 默认必须单进程顺序运行
- 不建议默认多进程分片
- 当前推荐主控脚本是 [run_stage34_workflow_v2.sh](/data/LFT-W02_data/pengxu/stage/run_stage34_workflow_v2.sh:1)

### 5. 当前冻结状态

Stage4 已接近冻结，冻结的含义是：

- 不再无限追更高 coverage
- 不再继续引入过多 heuristic
- 以稳定、可复现、可消融为优先

当前正式实验矩阵使用 `S0-S6`：

- `S0 DirectOnly`
- `S1 BaseRecon`
- `S2 SupportTemporal`
- `S3 PhysicsSmooth`
- `S4 ConfPruneAnchor`
- `S5 FinalFast`
- `S6 FullAux`

其中：

- `S5 FinalFast` 是当前主结果版本
- `S6 FullAux` 是 richer aux fields 导出版本，不是主运行链

### 6. 当前真实统计

`stage4_summary.json` 总帧数与触发情况：

```text
frames     = 7395
triggered  = 4244
nonempty   = 4243
```

总体统计：

```text
coverage all mean      = 0.030367
conf all mean          = 0.150769
coverage nonempty mean = 0.052926
conf nonempty mean     = 0.262771
```

### 7. 代表性结果示例

按 `recon_filled_voxels` 排名前几：

- `20260126073000`: `recon_filled_voxels=511`, `recon_coverage_ratio≈0.1038`, `recon_conf_mean≈0.2181`
- `20260201025400`: `recon_filled_voxels=500`, `recon_coverage_ratio≈0.0949`, `recon_conf_mean≈0.2666`

按 `recon_coverage_ratio` 排名前几：

- `20260205020000`: `recon_coverage_ratio=1.0`, `recon_filled_voxels=29`, `recon_conf_mean≈0.6123`
- `20260205020600`: `recon_coverage_ratio=1.0`, `recon_filled_voxels=43`, `recon_conf_mean≈0.6126`
- `20260129174200`: `recon_coverage_ratio≈0.1560`, `recon_filled_voxels=198`
- `20260206174200`: `recon_coverage_ratio≈0.1547`, `recon_filled_voxels=266`

按 `recon_conf_mean` 排名前几：

- `20260205020600`: `recon_conf_mean≈0.6126`
- `20260205020000`: `recon_conf_mean≈0.6123`
- `20260215214800`: `recon_conf_mean≈0.5317`

按 `hazard_alert_voxels` 排名前几：

- `20260206174200`: `hazard_alert_voxels=328`
- `20260209041800`: `hazard_alert_voxels=292`
- `20260130174200`: `hazard_alert_voxels=268`

按 `temporal_fill_voxels` 排名前几：

- `20260129114200`: `temporal_fill_voxels=40`
- `20260210154800`: `temporal_fill_voxels=38`

按 `support_expand_voxels` 排名前几：

- `20260204095400`: `support_expand_voxels=18`
- `20260204171800`: `support_expand_voxels=14`

这些示例很重要，因为它们直接说明了：

- Stage4 不是“每帧都重构很多”，而是在有信息时触发、有支撑时填充。
- 高 coverage 和高 confidence 帧往往对应强风支撑或局地事件。
- temporal fill、support expand、hazard alert 都已经具备解释性。

### 8. 当前可视化链路

Stage4 当前已经有两类代表性可视化：

1. 代表帧 2D / 3D slices
   - [report_stage4_recon_slices.py](/data/LFT-W02_data/pengxu/stage/report_stage4_recon_slices.py:1)
   - 输出目录：
     `/data/LFT-W02_data/pengxu/stage4_visualizations/stage4_output_v2_representative`

2. 地理坐标 ROI 可视化
   - [report_stage4_geo_wind_visualization.py](/data/LFT-W02_data/pengxu/stage/report_stage4_geo_wind_visualization.py:1)
   - 输出目录：
     `/data/LFT-W02_data/pengxu/stage4_visualizations/stage4_output_v2_geo_representative`

当前代表帧目录里可以看到例如：

- `00076_20260124013600_3d.png`
- `01376_20260129114200_3d.png`
- `01436_20260129174200_3d.png`
- `03338_20260206174200_3d.png`
- `07041_20260222063600_3d.png`

地理坐标目录里则有：

- `00076_20260124013600_country_roi.png`
- `00076_20260124013600_roi_layers.png`
- `00076_20260124013600_roi_3d.png`

### 9. 当前边界

- 当前全量 `full_fast_stage4_frozen_v1 stage4_only` 结果应视为诊断基线，不直接作为论文 `S5 FinalFast` 主结果引用。
- 真正 `S5 FinalFast` 必须在日志中确认：
  - `fast_mode=1`
  - `output_profile=fast`
  - `quality_profile=fast_balanced`
  - `quality_expand_enabled=0`
  - `omp_threads=6`
- 如果要求 GPU，还必须确认：
  - `gpu_enabled=1`
  - `gpu_device=cuda:0`

### 10. Stage4 的日志、可视化与解释链路

Stage4 是目前“图最多、日志最多、解释性最强”的阶段。  
当前验证链路主要包括：

1. 运行日志
   - `stage4_*.log`
   - `stage4summary*.log`
   - `stage4stats*.log`
   - `run_info.txt`
   - `phase_status*.log`

2. 诊断报告
   - `stage4_sparse_metrics*.json`
   - `stage4_outliers*.json`
   - `stage4_npz_fields*.log`

3. 代表帧 2D/3D slices
   - `stage4_visualizations/stage4_output_v2_representative`
   - 适合解释 coverage、confidence、hazard、anchor_restore 等局部形态

4. 地理坐标 ROI 可视化
   - `stage4_visualizations/stage4_output_v2_geo_representative`
   - 适合解释重构点落在全国雷达网格的什么位置、在哪些高度层出现

5. 小样本校准图
   - 例如 `stage4_visualizations/S5_finalfast_anchorfallback_v1`
   - 用于检查校准帧的 3D 形态是否符合预期

因此，Stage4 在知识库里应该同时记录：

- 数值 summary
- 代表帧图
- 地理坐标图
- 日志口径

这样后续检索时，既能按“哪个阶段干什么”查，也能按“某个异常帧怎么解释”查。

---

## 七、Stage5：ROI 局部 refinement 与背景场接入

### 1. 目标

`Stage5` 当前不是训练完成的 diffusion 模型，而是一个独立的、可运行的 ROI refinement scaffold。

它的目标是：

- 读取 Stage4 的 sparse reconstruction
- 在局地 ROI 上做 diffusion-style 平滑
- 加上 PINN-proxy 的 divergence damping
- 在需要时引入 ERA5 / GFS / GDAS 背景场作为先验
- 输出更适合后续预测和风险分析的局地 refined sparse field

### 2. 当前主脚本

[stage5_pinn_diffusion_refine.py](/data/LFT-W02_data/pengxu/stage/stage5_pinn_diffusion_refine.py:1)

以及相关背景场工具：

- [download_stage5_era5_roi.py](/data/LFT-W02_data/pengxu/stage/download_stage5_era5_roi.py:1)
- [download_stage5_gfs_gdas_roi.py](/data/LFT-W02_data/pengxu/stage/download_stage5_gfs_gdas_roi.py:1)
- [download_stage5_gfs_aws_historical_roi.py](/data/LFT-W02_data/pengxu/stage/download_stage5_gfs_aws_historical_roi.py:1)
- [run_stage5_rolling_roi.py](/data/LFT-W02_data/pengxu/stage/run_stage5_rolling_roi.py:1)
- [report_stage5_background_field.py](/data/LFT-W02_data/pengxu/stage/report_stage5_background_field.py:1)
- [report_stage5_background_comparison.py](/data/LFT-W02_data/pengxu/stage/report_stage5_background_comparison.py:1)

### 3. 当前输入输出

主要输入：

- `stage4_output_v2/frame_*.npz`
- `stage4_output_v2/stage4_summary.json`
- 可选背景场 NPZ：
  - `era5_roi_<time>.npz`
  - `gfs_roi_<time>.npz`
  - `gdas_roi_<time>.npz`
  - `background_<time>.npz`

主要输出：

- `stage5_output_v1*`
- `stage5_summary.json`
- 关键帧 3D ROI 图

### 4. 当前 Stage5 无背景关键帧结果

目录：

- `/data/LFT-W02_data/pengxu/stage5_output_v1_no_background_keyframes`

真实结果：

- `20260124013600`: `403 -> 654`, `expanded=251`, `anchor_rmse≈0.0713`, `heldout≈0.7845`
- `20260129114200`: `268 -> 443`, `expanded=175`, `anchor_rmse≈0.0389`, `heldout≈0.0464`
- `20260206174200`: `266 -> 406`, `expanded=140`, `anchor_rmse≈0.1119`, `heldout≈0.6774`
- `20260222063600`: `295 -> 482`, `expanded=187`, `anchor_rmse≈0.0470`, `heldout≈0.4669`

这说明：

- Stage5 在无背景条件下已经可以扩展 sparse ROI voxels。
- 但效果不是所有帧都稳定。
- `20260129114200` 是相对稳的帧。
- `20260206174200` 是典型风险帧。

### 5. 当前历史 GFS 对齐关键帧结果

目录：

- `/data/LFT-W02_data/pengxu/stage5_external_background/gfs_historical_aws_npz`
- `/data/LFT-W02_data/pengxu/stage5_output_v1_historical_gfs_keyframes`
- `/data/LFT-W02_data/pengxu/stage5_visualizations/historical_gfs_keyframes_comparison`

当前已对齐并验证的历史关键帧：

- `20260124013600 -> 2026012400 f001`
- `20260129114200 -> 2026012906 f005`
- `20260206174200 -> 2026020612 f005`
- `20260222063600 -> 2026022206 f000`

Stage5 历史 GFS 融合结果：

- `20260124013600`: `403 -> 654`, `background_available=1`, `anchor_rmse≈0.0887`, `heldout≈1.2304`, `background_vector_rmse≈12.85`
- `20260129114200`: `268 -> 443`, `background_available=1`, `anchor_rmse≈0.0389`, `heldout≈0.0464`, `background_vector_rmse≈8.76`
- `20260206174200`: `266 -> 406`, `background_available=1`, `anchor_rmse≈0.1095`, `heldout≈0.6917`, `background_vector_rmse≈17.14`
- `20260222063600`: `295 -> 482`, `background_available=1`, `anchor_rmse≈0.0456`, `heldout≈1.7326`, `background_vector_rmse≈8.93`

这说明：

- 背景场已经真正进入 Stage5 计算，不只是单独画图。
- 但背景场不是“真值”，它和局地 sparse anchor 可能冲突。
- `20260129114200` 依然是相对稳的帧。
- `20260206174200` 与 `20260222063600` 仍需要谨慎解释。

### 6. 当前关键帧 3D 对比图

当前已经实现两类关键图：

1. `Stage4 / Stage5 / background` 三栏图
2. `Stage5 - background` 差值诊断图

目录：

- `/data/LFT-W02_data/pengxu/stage5_visualizations/historical_gfs_keyframes_comparison`

真实输出文件包括：

- `20260124013600_stage4_stage5_background_3d.png`
- `20260124013600_stage5_minus_background_3d.png`
- `20260129114200_stage4_stage5_background_3d.png`
- `20260129114200_stage5_minus_background_3d.png`
- `20260206174200_stage4_stage5_background_3d.png`
- `20260206174200_stage5_minus_background_3d.png`
- `20260222063600_stage4_stage5_background_3d.png`
- `20260222063600_stage5_minus_background_3d.png`

新的对比图已经改成：

- 只在 `Stage4` 和 `Stage5` 的共享 sparse support 上比较
- 背景场只在同一批点上采样
- `comparison_summary.json` 中记录：
  - `background=true`
  - `shared_points=250`
  - `sample_mode=shared_stage4_stage5_intersection`

### 7. Stage5 当前的工程意义

Stage5 目前已经具备三种工程能力：

1. 无背景的 ROI 局部 refinement
2. 历史背景场对齐后的离线关键帧 refinement
3. rolling ROI / realtime-style 小样本入口

但它还不是最终论文模型，因为：

- 仍是 `PINN-proxy + diffusion-style` scaffold
- 还没有 learned diffusion
- 还没有更完整的独立验证协议

### 8. 当前边界

- 背景场是先验和对比基线，不是重构真值。
- 图像看起来“像背景”不一定代表更好，必须结合：
  - `background_vector_rmse`
  - `background_speed_bias`
  - `anchor_rmse_after`
  - `heldout_anchor_rmse_after`
- 当前更适合把 Stage5 表述为：
  - `Stage4` 状态层上的 ROI refinement / short-term forecast 原型

### 9. Stage5 的日志、可视化与解释链路

Stage5 当前已经形成比较完整的“数值 + 图 + 背景场对比”链路：

1. `stage5_summary.json`
   - 核心字段包括：
     - `initial_voxels`
     - `refined_voxels`
     - `expanded_voxels`
     - `anchor_rmse_after`
     - `heldout_anchor_rmse_after`
     - `background_vector_rmse`
     - `background_speed_bias`
     - `background_available`

2. Stage5 关键帧 3D ROI 图
   - 例如：
     - `stage5_output_v1_no_background_keyframes/*.png`
     - `stage5_output_v1_historical_gfs_keyframes/*.png`

3. 背景场独立 3D 图
   - `stage5_visualizations/gfs_gdas_background/gfs_roi_20260519120000_background_3d.png`
   - 这类图只说明背景场自身，不代表本项目重构结果

4. Stage4 / Stage5 / background 三栏 comparison
   - `no_background_keyframes_comparison`
   - `realtime_smoke_comparison`
   - `historical_gfs_keyframes_comparison`

5. `Stage5 - background` 差值图
   - 当前已在 `historical_gfs_keyframes_comparison` 中补齐
   - 用于判断 Stage5 相比背景场到底偏离多少，而不只是看三栏图“像不像”

因此，Stage5 在知识库里最重要的解释原则是：

- 先看 summary 指标，再看 comparison 图，再看 delta 图；
- 不要只凭“Stage5 和 background 像不像”做结论。

---

## 八、当前主控脚本与真实主线

当前真实主控脚本：

- [run_stage34_workflow_v2.sh](/data/LFT-W02_data/pengxu/stage/run_stage34_workflow_v2.sh:1)

当前真实主线代码：

- `Stage3`: [stage3_agents_v2.py](/data/LFT-W02_data/pengxu/stage/stage3_agents_v2.py:1)
- `Stage4`: [stage4_pack_v2.py](/data/LFT-W02_data/pengxu/stage/stage4_pack_v2.py:1)

非当前主线：

- `stage3_agents.py`
- `stage4_pack.py`

---

## 九、当前正式目录关系

### 1. 正式输出目录

- `Stage1`: `/data/LFT-W02_data/pengxu/stage1_output`
- `Stage2`: `/data/LFT-W02_data/pengxu/stage2_output`
- `Stage3`: `/data/LFT-W02_data/pengxu/stage3_output_v2`
- `Stage4`: `/data/LFT-W02_data/pengxu/stage4_output_v2`
- `Stage5`: 多个实验目录并存，常见包括：
  - `stage5_output_v1_no_background_keyframes`
  - `stage5_output_v1_historical_gfs_keyframes`
  - `stage5_output_v1_realtime_smoke`

### 2. 可视化目录

- `stage4_visualizations/`
- `stage5_visualizations/`

### 3. 背景场目录

- `stage5_external_background/gfs_gdas_roi_npz`
- `stage5_external_background/gfs_historical_aws_npz`

---

## 十、当前项目的关键结论

### 1. Stage1-Stage2 解决了“多源观测统一到雷达体素空间”的问题

- 项目已经把稀疏风观测、密集轨迹观测和雷达时间轴对齐起来。
- 这是后续所有时空融合的基础。

### 2. Stage3 解决了“从体素观测到 flight agent 图”的问题

- 项目不只是做体素统计，而是构建了可通信、可分层的 flight agent 图。
- 这是 Stage4 能利用通信和协同结构的前提。

### 3. Stage4 已经形成了稳定、可解释、可消融的风场状态层

- 当前真正主结果仍然在 Stage4。
- Stage4 已具备论文实验矩阵、模块开关和代表帧解释能力。

### 4. Stage5 已经从“空想接口”变成“可运行 scaffold”

- 已可做无背景 refinement
- 已可做历史 GFS 对齐 refinement
- 已可生成三栏图和差值图

但 Stage5 仍然需要更谨慎地解释：

- 它是原型，不是真值
- 背景场是先验，不是标签
- “像不像背景”不等于“有没有更好”

---

## 十一、当前仍存在的核心边界

1. 数据本身是稀疏、多源、时序不连续的，coverage 天花板有限。  
2. Stage4 具有显式时序状态，因此默认不适合多进程分片。  
3. Stage5 当前没有真实 learned diffusion，也没有完整独立验证集。  
4. 背景场与局地 sparse anchor 之间可能存在物理冲突。  
5. 当前所有 3D 图都应理解为：
   - 稀疏局地状态层可视化
   - 或外部背景场可视化
   - 不是全国连续满场重构真值

---

## 十二、后续知识库推荐拆分方式

如果后续要把知识库做得更系统，建议从这份总文档再拆出 5 类主题页：

1. `数据层`
   - 原始 parquet、雷达帧、bbox、时间窗、字段清洗规则

2. `阶段层`
   - Stage1-Stage5 各阶段目标、输入、输出、关键脚本

3. `结果层`
   - 代表性关键帧、Stage4 代表帧、Stage5 关键帧、历史 GFS 对齐结果

4. `运行层`
   - 主控脚本、目录关系、全量运行、日志检查、GPU/CPU 口径

5. `方法层`
   - 稀疏多源重构逻辑、agent/communication graph、Stage4 模块矩阵、Stage5 背景场融合逻辑

这份文档可以直接作为这些主题页的上级索引。
