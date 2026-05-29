# Stage3/Stage4 脚本深度说明索引

正式长文档入口：

- [16_stage34_script_deep_dive.md](/data/LFT-W02_data/pengxu/stage/handover_stage45_20260507/16_stage34_script_deep_dive.md)

这份索引文件只保留导航，不再复制长文内容，避免两份说明长期漂移。

## 文档内容概览

正式文档分三部分：

1. `Stage3`
   - 真实调用链
   - 输入输出
   - `agent_builder.py / communication_builder.py` 的主线作用
   - 关键参数和真实字段
   - 新增 `Stage3` 图形化展示命令

2. `Stage4`
   - 触发式重构逻辑
   - `_prepare_frame()` 与 `_build_lightweight_frame()` 的分工
   - 模块开关、输出 profile、forecast/hazard/full_aux 边界
   - 真实 `stage4_summary.json` 和 `frame_*.npz` 字段
   - 2D/3D/地理坐标可视化命令

3. `联合运行脚本`
   - `RUN_MODE / RUN_PHASE / RUN_PHASES`
   - shard / merge / collect / export / readiness / keylog
   - 当前主线目录关系和并行策略

## 当前新增脚本

本次新增的 `Stage3` 只读展示脚本：

- [report_stage3_agent_graph_visualization.py](/data/LFT-W02_data/pengxu/stage/report_stage3_agent_graph_visualization.py)

它只读取：

- `/data/LFT-W02_data/pengxu/stage2_output/stage2_summary.json`
- `/data/LFT-W02_data/pengxu/stage3_output_v2/stage3_summary.json`
- `/data/LFT-W02_data/pengxu/stage3_output_v2/agents/*.json`

不会改动 `Stage2/Stage3/Stage4` 主线产物。

