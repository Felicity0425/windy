# 项目一：旧版航班-风场 Stage1-4 / Stage3-Stage5 冻结链路总结

生成日期：2026-05-29

本文总结 `/data/LFT-W02_data/pengxu/stage` 与 `/data/LFT-W02_data/pengxu/workflow`
中旧版主线文档。这个项目可以称为：

```text
旧版航班-风场多阶段处理与重构流水线
```

它对应的核心目标是：

```text
原始航空/雷达/气象观测
  -> Stage1 清洗
  -> Stage2 体素化
  -> Stage3 flight agents / communication graph
  -> Stage4 风场状态层重构与训练样本打包
  -> Stage5 ROI refinement / background comparison scaffold
```

注意：本文只总结 Stage1-4 为主；Stage5 仅作为 Stage4 后续方向说明。

## 1. 项目定位

旧项目的核心定位不是单纯天气预报，也不是单纯雷达反演，而是：

```text
多源航空观测 + 雷达时间轴 + flight-agent 图结构
+ 稀疏风场重构 + 训练样本打包系统
```

它的核心思想是：

```text
普通帧轻量保留结构；
变化帧触发完整风场重构；
Stage4 产出可解释、可消融、可导出的风场状态层。
```

最重要的历史文档：

```text
stage/README_stage_pipeline.txt
stage/handover_stage45_20260507/00_overview.md
stage/handover_stage45_20260507/01_stage34_pipeline.md
stage/handover_stage45_20260507/02_stage4_modification_and_freeze.md
stage/handover_stage45_20260507/07_full_command_catalog.md
stage/handover_stage45_20260507/14_project_knowledge_base_summary.md
stage/handover_stage45_20260507/16_stage34_script_deep_dive.md
```

## 2. 总体目录与真实主线

项目根目录：

```text
/data/LFT-W02_data/pengxu
```

旧项目核心代码目录：

```text
/data/LFT-W02_data/pengxu/stage
```

主控脚本：

```text
stage/run_stage34_workflow_v2.sh
```

当前旧项目真实主线脚本：

```text
Stage1: stage/stage1_prepare.py
Stage2: stage/stage2_voxelize.py
Stage3: stage/stage3_agents_v2.py
Stage4: stage/stage4_pack_v2.py
```

非当前主线或历史脚本：

```text
stage/stage3_agents.py
stage/stage4_pack.py
stage/run_stage34_workflow.sh
```

核心配置/工具：

```text
stage/pipeline_config.py
stage/schema_contract.py  # 文档中提到的契约概念
stage/pipeline_utils.py
stage/reconstruct_utils.py
stage/reconstruct_utils_v2.py
stage/wind_reconstruction.py
```

## 3. 空间、时间和数据设定

空间范围：

```text
lat = 12.2 .. 54.2
lon = 73.0 .. 135.0
alt = 0 .. 15000 m
vertical step = 500 m
Z_DIM = 31
```

时间基准：

```text
雷达拼图帧时间是主时间轴。
Stage1/2 默认围绕雷达帧聚合前后 5 分钟窗口。
Stage4 引入 prev_recon_state / temporal_background / forecast_next_wind_field。
```

主要数据类型：

```text
clean_wind: AMDAR / turbulence / derived wind
clean_loc: aircraft location / trajectory / motion
radar mosaic PNG: 2D weather-radar background and time grid
external background: ERA5 / GFS / GDAS / MERRA-2 candidates for Stage5
```

已知 Stage1 清洗统计：

```text
clean_wind_rows = 431189
clean_loc_rows  = 19162638
radar_total     = 7396
radar_usable    = 7395
window_records  = 7395
```

## 4. Stage1：原始观测读取与清洗

### 4.1 Stage1 的职责

Stage1 不做体素化，也不做风场重构。它只负责把异构原始数据清洗成稳定中间产物。

主要任务：

```text
1. 读取 location / amdar / turb / radar 数据。
2. 清洗字段名。
3. 统一时间字段。
4. 北京时间转 UTC。
5. 解析经纬度、高度、航向、地速、风向、风速。
6. 计算 u/v 风分量和 aircraft motion 分量。
7. 生成雷达帧索引。
8. 生成每个雷达帧的时间窗索引。
```

### 4.2 Stage1 主脚本

```text
stage/stage1_prepare.py
```

辅助脚本：

```text
stage/convert_excel_to_parquet_robust.py
stage/check_location_parquet_quality.py
stage/check_stage1_stage2_alignment.py
stage/checkstage1.py
stage/normalize_manifest_paths.py
```

### 4.3 Stage1 输入

典型输入：

```text
location.xlsx / location parquet shards
amdar.xlsx / amdar parquet shards
turbulence tables / turb parquet shards
radar PNG directory
```

当前 `20260224` 原始数据状态：

```text
/data/LFT-W02_data/pengxu/20260224/amdar.xlsx    readable
/data/LFT-W02_data/pengxu/20260224/location.xlsx corrupted / incomplete
```

已验证 AMDAR 转换命令：

```bash
cd /data/LFT-W02_data/pengxu

POLARS_MAX_THREADS=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 \
/data/LFT-W02_data/pengxu/.conda/envs/windy310/bin/python \
stage/convert_excel_to_parquet_robust.py \
  --excel /data/LFT-W02_data/pengxu/20260224/amdar.xlsx \
  --out-root /data/LFT-W02_data/pengxu/20260224
```

### 4.4 Stage1 输出

标准输出：

```text
stage1_output/clean_wind.parquet
stage1_output/clean_loc.parquet
stage1_output/radar_index.json
stage1_output/frame_window_index.json
stage1_output/stage1_summary.json
```

字段标准化示例：

```text
clean_wind:
  time_utc
  lat_clean
  lon_clean
  alt_meters
  u_wind
  v_wind
  obs_conf
  source
  flight_id

clean_loc:
  time_utc
  lat_clean
  lon_clean
  alt_meters
  heading_deg
  ground_speed_ms
  u_motion
  v_motion
  flight_id
```

### 4.5 Stage1 概念

`u_wind / v_wind`：

```text
由风向风速换算得到的大气水平风分量。
```

`u_motion / v_motion`：

```text
由飞机航向和地速换算得到的飞机运动分量。
它不是大气风，不能直接当 wind truth。
```

`radar_index.json`：

```text
雷达 PNG 文件索引，提供 time_str / timestamp_utc / radar_path / usable。
```

`frame_window_index.json`：

```text
每个雷达帧的 +/- 时间窗内有多少 location / wind 记录。
```

### 4.6 Stage1 检查

主要检查方式：

```text
stage1_summary.json
radar_index.json
frame_window_index.json
check_stage1_stage2_alignment.py
Stage2 是否能产生非空 wind/traj/motion voxels
```

失败信号：

```text
时间字段解析率低
雷达帧无法解析
location 点大比例落不进中国 bbox
clean_wind/clean_loc 缺核心字段
```

## 5. Stage2：体素化与空间离散化

### 5.1 Stage2 的职责

Stage2 把 Stage1 的连续空间观测投影到每个雷达帧对应的 3D 体素网格。

主要任务：

```text
1. 读取 radar PNG，确定水平 H x W。
2. 读取当前帧前后 5 分钟窗口内的 wind/location/motion/turb。
3. 经纬度映射到 x/y。
4. 高度映射到 z。
5. 相同 voxel 内聚合。
6. 输出逐帧 npz 和 stage2_summary.json。
```

### 5.2 Stage2 主脚本

```text
stage/stage2_voxelize.py
```

### 5.3 Stage2 输入

```text
stage1_output/clean_wind.parquet
stage1_output/clean_loc.parquet
stage1_output/radar_index.json
stage1_output/frame_window_index.json
radar PNG files
```

### 5.4 Stage2 输出

```text
stage2_output/voxels/*.npz
stage2_output/stage2_summary.json
```

每帧核心字段：

```text
wind_records
loc_records
motion_records
flight_motion_records
flight_raw_records
amdar_records
turb_records
radar_img
radar_shape
grid_shape
```

### 5.5 Stage2 概念

`voxel`：

```text
三维网格单元，相当于 3D pixel。
x = 经度方向
y = 纬度方向
z = 高度方向
```

`wind_records`：

```text
当前雷达时间窗内的飞机风观测体素，是后续 Stage4 直接风锚点/监督来源。
```

`loc_records`：

```text
当前窗口飞机轨迹/位置体素。
```

`motion_records`：

```text
当前窗口飞机运动分量体素。它是 aircraft kinematics，不是 wind truth。
```

`turb_records`：

```text
湍流/扰动记录，非常稀疏，但对风险诊断有价值。
```

### 5.6 Stage2 真实统计

旧项目 Stage2 总帧数：

```text
7395
```

总体统计：

```text
wind_voxels mean   ~= 13.761
traj_voxels mean   ~= 3943.035
motion_voxels mean ~= 3539.923
nonzero_wind_frames = 5552
nonzero_turb_frames = 87
```

典型高风帧：

```text
20260208124800: wind_voxels=140, motion_voxels=5225, amdar_voxels=140
20260206174200: wind_voxels=120, motion_voxels=1441, amdar_voxels=120
20260207022400: wind_voxels=111, motion_voxels=5040, amdar_voxels=111
```

结论：

```text
风观测很稀疏，轨迹/运动很密集，turb 更稀疏。
```

### 5.7 Stage2 检查与可视化

主要检查：

```text
stage2_summary.json
stage/logs/topwind_auto/stage2_topwind.log
check_stage1_stage2_alignment.py
高风帧/高轨迹帧样例
```

解释口径：

```text
Stage2 不是风场重构层。
Stage2 图像稀疏说明观测稀疏，不等于失败。
```

## 6. Stage3：飞行智能体与通信图

### 6.1 Stage3 的职责

Stage3 把 Stage2 的体素观测升级成 flight agents 和通信图结构。

它解决的问题是：

```text
哪些飞机在当前帧是有效 agent？
哪些 agent 能通信？
哪些 agent 在运动上相关？
哪些 agent 能承担风传播关系？
```

### 6.2 Stage3 主脚本

当前真实主线：

```text
stage/stage3_agents_v2.py
```

历史脚本：

```text
stage/stage3_agents.py
```

### 6.3 Stage3 输入

```text
stage2_output/stage2_summary.json
stage2_output/voxels/*.npz
```

### 6.4 Stage3 输出

```text
stage3_output_v2/agents/*.json
stage3_output_v2/stage3_summary.json
```

### 6.5 Stage3 三层边

第一层：通信可达边

```text
flight_comm_allowed
ff_comm_allowed
```

含义：

```text
两个 flight agents 在时间、水平距离、垂直距离上足够近，可以交换信息。
```

第二层：运动相关边

```text
ff_motion_allowed
flight_ff_motion_edges
```

含义：

```text
不仅能连，而且轨迹/运动趋势相容。
```

第三层：风传播边

```text
ff_wind_allowed
flight_ff_wind_edges
```

含义：

```text
该边对风场传播或风信息扩散有意义。
```

`valid_wind_capable_flights`：

```text
满足至少一种风传播条件的节点数量。
```

### 6.6 Stage3 并行原则

Stage3 可以多进程 shard 并行，因为它更接近 frame-level 独立任务：

```text
CPU / IO / Polars / sparse graph dominated
no prev_recon_state dependency
```

### 6.7 Stage3 真实统计

```text
frames = 7395
valid_flight_agents mean      ~= 492.362
flight_comm_allowed mean      ~= 97.172
flight_ff_allowed_edges mean  ~= 4670.483
flight_ff_wind_edges mean     ~= 1345.936
```

高 agent 帧：

```text
20260212061200: valid_flight_agents=782
20260215103000: valid_flight_agents=776
20260214064200: valid_flight_agents=771
```

高 wind-edge 帧：

```text
20260215062400: flight_ff_wind_edges=7644
20260215051800: flight_ff_wind_edges=7615
20260214063600: flight_ff_wind_edges=7612
```

### 6.8 Stage3 检查

检查重点：

```text
agent 数量是否合理
flight_comm_allowed 是否长期为 0
ff_allowed_edges 是否合理
ff_wind_edges 是否长期全灭
```

辅助文档：

```text
stage/meaning_explanations/README_stage3_utils.txt
stage/meaning_explanations/README_stage3_debug_flow.txt
stage/handover_stage45_20260507/18_stage3_representative_presentation_script.md
```

## 7. Stage4：多源风场重构与状态层构建

### 7.1 Stage4 的职责

Stage4 是旧项目的核心结果层。它把 Stage2 体素观测和 Stage3 agents/graph
融合为风场状态层，并输出训练样本。

主要任务：

```text
1. 读取 Stage2 体素结果。
2. 读取 Stage3 agent/graph。
3. 融合风观测、轨迹、图关系和前一帧背景。
4. 判断是否触发完整重构。
5. 执行 support / temporal / relax / prune / expand。
6. 保护 direct anchors。
7. 输出 frame_*.npz 和 stage4_summary.json。
8. 为 full_aux_export 补充 richer training fields。
```

### 7.2 Stage4 主脚本

当前真实主线：

```text
stage/stage4_pack_v2.py
```

历史脚本：

```text
stage/stage4_pack.py
```

### 7.3 Stage4 输入

```text
stage2_output/voxels/*.npz
stage2_output/stage2_summary.json
stage3_output_v2/agents/*.json
stage3_output_v2/stage3_summary.json
```

单独跑 `stage4_only` 时必须显式指定：

```bash
STAGE3_INPUT_DIR_FOR_STAGE4=/data/LFT-W02_data/pengxu/stage3_output_v2
```

否则可能误读旧目录：

```text
/data/LFT-W02_data/pengxu/stage3_output
```

### 7.4 Stage4 输出

正式 fast 输出：

```text
/data/LFT-W02_data/pengxu/stage4_output_v2/frame_*.npz
/data/LFT-W02_data/pengxu/stage4_output_v2/stage4_summary.json
```

full aux 输出：

```text
/data/LFT-W02_data/pengxu/stage4_output_full_aux_v2/<RUN_LABEL>
```

运行子集输出：

```text
/data/LFT-W02_data/pengxu/stage4_output_runs_v2/<RUN_LABEL>
```

### 7.5 Stage4 为什么默认不分片

Stage4 有明确时序状态：

```text
prev_recon_state
temporal_background
forecast_next_wind_field
trigger_reconstruction
```

因此多进程分片会切断时序，产生：

```text
first_frame
discontiguous_frame_gap
changed temporal behavior
```

默认策略：

```text
Stage3 shard parallel
Stage4 single process / single GPU / multi-thread CPU
```

### 7.6 Stage4 模块

`support fill`：

```text
从空间邻近和 agent 支撑扩展风场。
```

`temporal fill`：

```text
利用前一帧或时间背景补足当前帧缺口。
```

`relax`：

```text
物理启发式平滑/松弛，降低突兀噪声。
```

`prune`：

```text
剪掉低置信或不合理区域。
```

`expand`：

```text
温和扩大重构区域，但不应暴力糊满全域。
```

`direct anchor restore`：

```text
恢复直接观测锚点，防止后处理破坏观测点。
```

`direct anchor force`：

```text
强制保护直接观测风锚点。
```

`primary anchor fallback`：

```text
当直接锚点过少或被去重过空时，允许保守 fallback，避免空重构。
```

### 7.7 Stage4 模块开关

```text
WIND_STAGE4_ENABLE_SUPPORT_FILL
WIND_STAGE4_ENABLE_TEMPORAL_FILL
WIND_STAGE4_ENABLE_RELAX
WIND_STAGE4_ENABLE_PRUNE
WIND_STAGE4_ENABLE_EXPAND
WIND_STAGE4_ENABLE_DIRECT_ANCHOR_RESTORE
WIND_STAGE4_ENABLE_DIRECT_ANCHOR_FORCE
```

### 7.8 Stage4 冻结逻辑

Stage4 接近冻结的原因：

```text
anchor fidelity 稳
coverage 温和提升即可
confidence 有层次
运行链路稳定
模块开关齐全，可直接做消融
```

冻结不是不再改代码，而是不再无限追 coverage 或继续叠加 heuristic。

### 7.9 Stage4 真实统计

```text
frames = 7395
triggered = 4244
nonempty = 4243
coverage all mean ~= 0.030367
conf all mean ~= 0.150769
coverage nonempty mean ~= 0.052926
conf nonempty mean ~= 0.262771
```

代表帧：

```text
20260126073000: recon_filled_voxels=511, coverage~=0.1038, conf~=0.2181
20260201025400: recon_filled_voxels=500, coverage~=0.0949, conf~=0.2666
20260206174200: hazard_alert_voxels=328
20260209041800: hazard_alert_voxels=292
```

### 7.10 Stage4 可视化

代表帧 2D/3D slices：

```text
stage/report_stage4_recon_slices.py
/data/LFT-W02_data/pengxu/stage4_visualizations/stage4_output_v2_representative
```

地理坐标 ROI：

```text
stage/report_stage4_geo_wind_visualization.py
/data/LFT-W02_data/pengxu/stage4_visualizations/stage4_output_v2_geo_representative
```

解释原则：

```text
不要把 block-like footprint 当成真实大气整块移动。
它更多反映有限半径 localization、support fill 和 gap fill。
```

## 8. 旧项目运行类型与命令

### 8.1 主运行：S5 FinalFast

用途：

```text
Stage4 冻结前主结果版本。
Stage3 8 路并行，Stage4 单卡 + 6 CPU threads。
```

命令：

```bash
BASE_DIR=/data/LFT-W02_data/pengxu
STAGE_DIR=$BASE_DIR/stage

RUN_MODE=full \
RUN_LABEL_OVERRIDE=full_fast_stage4_frozen_v1 \
RUN_PHASE=full_fast_multi_gpu \
RUN_VALIDATE=1 \
PROGRESS_EVERY=50 \
STAGE3_PARALLEL_SHARDS=8 \
STAGE3_CPU_THREADS_PER_WORKER=1 \
STAGE4_CPU_THREADS=6 \
MULTI_GPU_STAGE4_SHARD=0 \
WIND_STAGE4_USE_GPU=1 \
WIND_STAGE4_GPU_DEVICE=cuda:0 \
WIND_STAGE4_ENABLE_SUPPORT_FILL=1 \
WIND_STAGE4_ENABLE_TEMPORAL_FILL=1 \
WIND_STAGE4_ENABLE_RELAX=1 \
WIND_STAGE4_ENABLE_PRUNE=1 \
WIND_STAGE4_ENABLE_EXPAND=1 \
WIND_STAGE4_ENABLE_DIRECT_ANCHOR_RESTORE=1 \
WIND_STAGE4_ENABLE_DIRECT_ANCHOR_FORCE=1 \
bash $STAGE_DIR/run_stage34_workflow_v2.sh
```

### 8.2 训练辅助导出：S6 FullAux

用途：

```text
从 fast 输出读取，补 fuller auxiliary fields。
不是重新跑主重构。
```

命令：

```bash
BASE_DIR=/data/LFT-W02_data/pengxu
STAGE_DIR=$BASE_DIR/stage

RUN_MODE=full \
RUN_LABEL_OVERRIDE=full_aux_export_stage4_frozen_v1 \
RUN_PHASE=full_aux_export \
RUN_VALIDATE=1 \
PROGRESS_EVERY=50 \
STAGE4_FAST_SOURCE_DIR=/data/LFT-W02_data/pengxu/stage4_output_v2 \
WIND_STAGE4_USE_GPU=1 \
WIND_STAGE4_ENABLE_SUPPORT_FILL=1 \
WIND_STAGE4_ENABLE_TEMPORAL_FILL=1 \
WIND_STAGE4_ENABLE_RELAX=1 \
WIND_STAGE4_ENABLE_PRUNE=1 \
WIND_STAGE4_ENABLE_EXPAND=1 \
WIND_STAGE4_ENABLE_DIRECT_ANCHOR_RESTORE=1 \
WIND_STAGE4_ENABLE_DIRECT_ANCHOR_FORCE=1 \
bash $STAGE_DIR/run_stage34_workflow_v2.sh
```

### 8.3 单阶段 Stage3

```bash
BASE_DIR=/data/LFT-W02_data/pengxu
STAGE_DIR=$BASE_DIR/stage

RUN_MODE=full \
RUN_LABEL_OVERRIDE=stage3_only_v1 \
RUN_PHASE=stage3_only \
RUN_VALIDATE=0 \
PROGRESS_EVERY=50 \
STAGE3_PARALLEL_SHARDS=8 \
STAGE3_CPU_THREADS_PER_WORKER=1 \
bash $STAGE_DIR/run_stage34_workflow_v2.sh
```

### 8.4 单阶段 Stage4

```bash
BASE_DIR=/data/LFT-W02_data/pengxu
STAGE_DIR=$BASE_DIR/stage

RUN_MODE=full \
RUN_LABEL_OVERRIDE=full_fast_stage4_frozen_v1 \
RUN_PHASE=stage4_only \
RUN_VALIDATE=1 \
PROGRESS_EVERY=50 \
STAGE3_INPUT_DIR_FOR_STAGE4=$BASE_DIR/stage3_output_v2 \
WIND_STAGE4_USE_GPU=1 \
WIND_STAGE4_GPU_DEVICE=cuda:0 \
OMP_NUM_THREADS=6 \
MKL_NUM_THREADS=6 \
NUMEXPR_NUM_THREADS=6 \
POLARS_MAX_THREADS=6 \
WIND_STAGE4_ENABLE_SUPPORT_FILL=1 \
WIND_STAGE4_ENABLE_TEMPORAL_FILL=1 \
WIND_STAGE4_ENABLE_RELAX=1 \
WIND_STAGE4_ENABLE_PRUNE=1 \
WIND_STAGE4_ENABLE_EXPAND=1 \
WIND_STAGE4_ENABLE_DIRECT_ANCHOR_RESTORE=1 \
WIND_STAGE4_ENABLE_DIRECT_ANCHOR_FORCE=1 \
bash $STAGE_DIR/run_stage34_workflow_v2.sh
```

## 9. 论文消融矩阵

S0 DirectOnly：

```text
所有 fill/relax/prune/expand/anchor restore/force 关闭。
只保留最直接观测逻辑。
```

S1 BaseRecon：

```text
基础重构版本，仍不启用主要增强模块。
```

S2 SupportTemporal：

```text
support fill + temporal fill 开启。
```

S3 PhysicsSmooth：

```text
support + temporal + relax。
```

S4 ConfPruneAnchor：

```text
加入 prune 和 anchor 保护。
```

S5 FinalFast：

```text
当前主结果版本。
```

S6 FullAux：

```text
训练导出版本，补 richer aux fields。
```

## 10. 实际运行日志清单

旧日志：

```text
stage/logs/full_v1/run_info.txt
stage/logs/topwind_auto/run_info.txt
stage/logs/topwind_auto_v1_1/run_info.txt
```

v2 full runs：

```text
stage/logs_v2/full_S5_final_fast_full_v1__full_fast_multi_gpu/run_info.txt
stage/logs_v2/full_full_fast_multi_gpu_safe_v3__full_fast_multi_gpu/run_info.txt
stage/logs_v2/full_full_fast_stage4_frozen_v1__stage4_only/run_info.txt
```

v2 indices runs：

```text
indices_S5_finalfast_anchorfallback_v1
indices_S5_finalfast_calibration_v1
indices_hw3
indices_hw3_fix1
indices_hw3_fix2
indices_hw3_fix3
indices_stage4_speed_ab_10_fast_baseline
indices_stage4_speed_ab_10_frozen_current
indices_stage4_speed_ab_10_write_cost_check
indices_stage4_speed_ab_50_fast_baseline
indices_stage4_speed_ab_50_frozen_current
indices_stage4_speed_ab_50_write_cost_check
```

v2 offset runs:

```text
offset_fast_single_gpu_baseline_v3_quality
offset_seq3337x5
offset_seq3337x5_fast_gpu
offset_seq3337x5_fast_multi_gpu_shard
offset_seq3337x5_fast_multi_gpu_shard_v2
offset_seq3337x5_fast_single_gpu_baseline
offset_seq3337x5_fast_single_gpu_baseline_v2
offset_seq3337x5_fastcheck*
offset_seq3337x5_fix*
offset_seq3337x5_full_aux_export_from_fast*
offset_seq3337x5_fullaux_gpu
offset_seq3337x5_gpucheck
```

Latest v2 run info at the time of the docs:

```text
stage/logs_v2/run_info_latest.txt
run_mode=indices
run_phase=stage4_only
run_label=S5_finalfast_anchorfallback_v1_stage4_only
frame_indices=18,1436,3853,6228,7041
```

## 11. Stage4 诊断与解释概念

`coverage`：

```text
有效重构区域比例，不要求越高越好。
过高可能代表过度填补。
```

`confidence`：

```text
重构置信度。理想状态是 direct/support 区域高，fill 区域低，全场 spread 不塌缩。
```

`anchor fidelity`：

```text
直接观测锚点保真。旧项目冻结 Stage4 的核心原因之一。
```

`hazard_alert_voxels`：

```text
风险/强变化候选体素，适合代表帧解释和 Stage5 事件触发。
```

`full_aux_export`：

```text
训练导出补字段，不应重新改变 fast 主结果。
```

## 12. Stage5 与外部背景的旧项目口径

Stage5 不是当前 Stage1-4 的一部分，但旧项目文档把它作为后续方向。

Stage5 目标：

```text
读取 Stage4 sparse reconstruction
做 ROI refinement
加入 PINN-proxy divergence damping
可选接入 ERA5/GFS/GDAS/MERRA-2 背景
输出 refined sparse field / future ROI
```

Stage5 主脚本：

```text
stage/stage5_pinn_diffusion_refine.py
stage/run_stage5_rolling_roi.py
stage/download_stage5_era5_roi.py
stage/download_stage5_gfs_gdas_roi.py
stage/download_stage5_gfs_aws_historical_roi.py
stage/report_stage5_background_field.py
stage/report_stage5_background_comparison.py
```

核心边界：

```text
Stage5 是 scaffold，不是训练好的 diffusion。
背景场是先验和对比基线，不是重构真值。
```

## 13. 文献与方法论支撑

旧项目相关文献方向：

```text
aircraft-derived wind observations: AMDAR / Mode-S / EMADDC
incomplete wind field reconstruction: Vision Mamba
PINN sparse flow reconstruction
multi-scale PINN 3D wind reconstruction
PyDDA / dual-Doppler variational wind retrieval
GraphCast / GenCast / Pangu / FengWu / FuXi as weather-AI context
Where2comm as spatial confidence / collaborative perception inspiration
```

重要方法映射：

```text
Vision Mamba -> Stage4 neural decoder / missing wind completion inspiration
PINN sparse flow -> Stage4/Stage5 physical residual refinement
multi-scale PINN -> 3D/time wind reconstruction future path
PyDDA -> variational constraints and background-field logic
Where2comm -> confidence-map and communication-efficient graph inspiration
```

## 14. 旧项目当前结论

```text
1. Stage1/2 已解决多源观测统一到雷达体素空间。
2. Stage3 已解决 flight agent / communication graph 组织。
3. Stage4 已形成稳定、可解释、可消融的风场状态层。
4. Stage4 默认不继续无限追 coverage，应以冻结版本和消融矩阵为主。
5. Stage5 已有 ROI refinement/background scaffold，但不是最终深度模型。
6. 旧项目主线现在更多是历史稳定基线和论文工程资产。
7. 新的 centralized_v1 / TimePower15 项目继承了很多概念，但验证逻辑改为 strict aircraft hold-out。
```
