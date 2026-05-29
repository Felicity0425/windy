# Stage3/Stage4 脚本深度说明

## 这份文档的作用

这份文档是对当前主线 `Stage3 / Stage4 / 联合运行脚本` 的深度交接说明。  
它不是“怎么跑一次命令”的速查表，而是把：

- 脚本到底在做什么
- 实际输入输出是什么
- 关键函数怎么串起来
- 关键参数和默认值是什么
- 为什么这样设计
- 如何可视化展示结果

系统地讲清楚。

当前主线边界仍然保持不变：

1. 主控脚本是 `stage/run_stage34_workflow_v2.sh`
2. 当前真实使用代码是 `stage/stage3_agents_v2.py` 和 `stage/stage4_pack_v2.py`
3. `Stage3` 正式输出目录是 `/data/LFT-W02_data/pengxu/stage3_output_v2`
4. `Stage4` 正式输出目录是 `/data/LFT-W02_data/pengxu/stage4_output_v2`
5. `full_aux_export` 输出目录是 `/data/LFT-W02_data/pengxu/stage4_output_full_aux_v2/<RUN_LABEL>`
6. `Stage3` 可以分片并行，`Stage4` 默认不能多进程分片
7. `Stage4` 当前定位是冻结主链，不继续无限追 `coverage`

---

# 第一部分：Stage3 深度说明

## 1. 含义

`Stage3` 的职责不是重构风场，而是把 `Stage2` 体素结果转成后续 `Stage4` 可消费的飞行智能体状态层。

它主要完成四件事：

1. 读取 `Stage2` 每帧 voxel npz 与 `stage2_summary.json`
2. 恢复风观测、轨迹观测、运动观测
3. 基于 flight motion / raw trajectory 构建 flight agents
4. 计算通信可达性、空空边、风能力边，并输出 `agents JSON + stage3_summary.json`

它的意义是：

- 给 `Stage4` 提供飞行体拓扑先验
- 给 `Stage4` 提供风能力节点、风边强弱、通信结构密度
- 把稀疏轨迹观测从“表格记录”提升成“图结构状态层”

`Stage3` 不负责：

- 3D 风场重构
- temporal background
- forecast
- hazard
- full aux 打包

---

## 2. 调用顺序

当前真实调用链是：

`run_stage34_workflow_v2.sh -> stage3_agents_v2.py -> build_agents_for_frame() -> build_flight_agents_sparse() -> select_ff_edges() -> _refine_flight_pack_with_wind_support()`

更细一点：

1. `main()`
   - 读取 `stage2_summary.json`
   - 根据 `WIND_FRAME_INDICES / WIND_FRAME_OFFSET / WIND_MAX_FRAMES` 选帧
   - 逐帧调用 `load_stage2_voxel()` 与 `build_agents_for_frame()`

2. `load_stage2_voxel(frame_item)`
   - 读取单帧 `Stage2` npz
   - 恢复 `wind_grouped / loc_grouped / loc_motion_grouped / flight_motion_grouped / flight_raw_records / amdar_grouped / turb_grouped`

3. `build_agents_for_frame(vox)`
   - 估计 ground reference
   - 调用 `build_flight_agents_sparse()` 构造初始 flight pack
   - 调用 `_refine_flight_pack_with_wind_support()` 做风能力增强
   - 写出 `agents/frame_<time>_agents.json`
   - 生成单帧 `stage3_summary` 行

4. `build_flight_agents_sparse()`
   - 是 `Stage3` 里真正的 agent builder 主体
   - 负责候选 flight 筛选、时空可达性计算、tier1/tier2 选择、agent 稀疏编码、air-air 图构建

5. `select_ff_edges()`
   - 对 `ff_allowed + ff_score` 做边选择
   - 输出稀疏边和三类边矩阵：
     - `ff_comm_allowed`
     - `ff_motion_allowed`
     - `ff_wind_allowed`

6. `_refine_flight_pack_with_wind_support()`
   - 对“风能力 flight”做二次激活增强
   - 防止 `valid_wind_capable_flights=0` 和 `flight_ff_wind_edges=0`

---

## 3. 输入

### 3.1 目录与文件

`Stage3` 当前输入来自：

- `/data/LFT-W02_data/pengxu/stage2_output/stage2_summary.json`
- `/data/LFT-W02_data/pengxu/stage2_output/voxels/frame_<time>_voxels.npz`

### 3.2 单帧 Stage2 npz 真实关键字段

真实 `Stage2` npz 包含这些 key：

- `filename`
- `time_str`
- `timestamp_utc`
- `radar_img`
- `radar_shape`
- `grid_shape`
- `wind_records`
- `loc_records`
- `motion_records`
- `flight_motion_records`
- `flight_raw_records`
- `amdar_records`
- `turb_records`

其中最重要的是：

- `flight_raw_records`
  - 用于恢复更真实的航班经纬高与时间
- `flight_motion_records`
  - 用于 agent 稀疏轨迹编码
- `motion_records`
  - 用于 motion-level 辅助
- `wind_records / amdar_records / turb_records`
  - 用于风能力和风边判断

### 3.3 环境变量输入

`Stage3` 自身直接读取的环境变量很少，主要是：

- `WIND_STAGE2_SUMMARY_PATH_OVERRIDE`
  - 覆盖 `Stage2 summary` 路径
- `WIND_STAGE3_OUTPUT_DIR`
  - 覆盖 `Stage3` 输出目录
- `WIND_FRAME_INDICES`
  - 精确抽帧
- `WIND_FRAME_OFFSET`
  - 跳过前若干帧
- `WIND_MAX_FRAMES`
  - 限制试跑帧数
- `WIND_PROGRESS_EVERY`
  - 进度日志间隔

---

## 4. 输出

### 4.1 正式输出目录

`Stage3` 正式输出目录：

- `/data/LFT-W02_data/pengxu/stage3_output_v2`

输出包括：

- `stage3_summary.json`
- `agents/frame_<time>_agents.json`

### 4.2 `stage3_summary.json` 真实字段

当前真实 key 包括：

- `agent_path`
- `candidate_flight_count`
- `filename`
- `flight_comm_allowed_agents`
- `flight_ff_allowed_edges`
- `flight_ff_motion_edges`
- `flight_ff_wind_edges`
- `ground_alt`
- `ground_lat`
- `ground_lon`
- `motion_voxels`
- `source_index`
- `space_likelihood_mode`
- `tier1_candidate_count`
- `tier2_candidate_count`
- `time_str`
- `timestamp_utc`
- `valid_flight_agents`
- `valid_wind_capable_flights`
- `vox_path`
- `wind_support_direct_hits`
- `wind_support_geo_hits`
- `wind_support_near_hits`
- `wind_support_score_p50`
- `wind_support_score_p90`
- `wind_support_soft_hits`
- `wind_voxels`

这些字段的意义：

- `valid_flight_agents`
  - 当前帧最终保留下来的有效 agent 数
- `flight_ff_allowed_edges`
  - air-air 通信允许边数
- `flight_ff_wind_edges`
  - 最终风能力边数
- `valid_wind_capable_flights`
  - 具备风能力的 flight 节点数
- `wind_support_*`
  - 风能力激活证据分解

### 4.3 `agents/frame_*_agents.json` 真实字段

当前真实 key 包括：

- `candidate_flight_count`
- `comm_eligible_count`
- `comm_eligible_ratio`
- `ff_comm_allowed`
- `ff_comm_weight`
- `ff_edge_density`
- `ff_motion_allowed`
- `ff_motion_edges`
- `ff_motion_weight`
- `ff_space_conf`
- `ff_space_hdist_km`
- `ff_space_likelihood`
- `ff_space_vdist_m`
- `ff_sparse_dst`
- `ff_sparse_score`
- `ff_sparse_src`
- `ff_st_conf`
- `ff_st_likelihood`
- `ff_time_conf`
- `ff_time_gap_sec`
- `ff_time_likelihood`
- `ff_wind_allowed`
- `ff_wind_edges`
- `ff_wind_weight`
- `flight_agent_ids`
- `flight_comm_allowed`
- `flight_comm_weight`
- `flight_count_flat`
- `flight_has_wind_obs`
- `flight_idx_flat`
- `flight_intent`
- `flight_mask`
- `flight_offsets`
- `flight_space_conf`
- `flight_space_hdist_km`
- `flight_space_likelihood`
- `flight_space_vdist_m`
- `flight_st_conf`
- `flight_st_conf_p50`
- `flight_st_conf_p90`
- `flight_st_likelihood`
- `flight_st_likelihood_p50`
- `flight_st_likelihood_p90`
- `flight_time_conf`
- `flight_time_gap_sec`
- `flight_time_likelihood`
- `flight_topk`
- `flight_u_flat`
- `flight_v_flat`
- `flight_wind_support_score`
- `tier1_candidate_count`
- `tier2_candidate_count`
- `valid_flight_agents`
- `valid_wind_capable_flights`
- `wind_support_direct_hits`
- `wind_support_geo_hits`
- `wind_support_near_hits`
- `wind_support_score_p50`
- `wind_support_score_p90`
- `wind_support_soft_hits`

最重要的几类字段：

1. 节点稀疏编码
   - `flight_agent_ids`
   - `flight_offsets`
   - `flight_idx_flat`
   - `flight_u_flat`
   - `flight_v_flat`
   - `flight_count_flat`

2. 节点属性
   - `flight_has_wind_obs`
   - `flight_comm_weight`
   - `flight_st_likelihood`
   - `flight_intent`

3. 边结构
   - `ff_sparse_src`
   - `ff_sparse_dst`
   - `ff_sparse_score`
   - `ff_comm_allowed`
   - `ff_motion_allowed`
   - `ff_wind_allowed`

4. 图统计
   - `ff_edge_density`
   - `ff_motion_edges`
   - `ff_wind_edges`

---

## 5. 重点函数逐项解释

### 5.1 `load_stage2_voxel(frame_item)`

作用：

- 读取单帧 `Stage2` npz
- 把 records 恢复成 `Polars DataFrame`
- 统一补齐 `source_index`

意义：

- 是 `Stage3` 和 `Stage4` 的桥接入口
- 保证后续不直接操作原始 `numpy object array`

### 5.2 `_select_stage2_frames(stage2_summary)`

作用：

- 根据 `WIND_FRAME_INDICES / WIND_FRAME_OFFSET / WIND_MAX_FRAMES` 选帧

意义：

- 支持连续试跑、跳段试跑、代表帧试跑
- 为 summary 补充 `source_index`

### 5.3 `_estimate_ground_from_frame(vox, flight_frame)`

作用：

- 基于当前帧航班分布动态估计一个 ground reference

核心逻辑：

- 优先利用 `flight_raw_records`
- 用鲁棒中心 + 按 flight 加权中心
- 再轻微向 voxel-level 分布回拉
- 最终裁剪到中国固定 bbox

意义：

- 不把所有航班都拿去对固定中国域中心算距离
- 让当前帧的空间似然更敏感、更稳定

### 5.4 `build_flight_agents_sparse(...)`

这是 `Stage3` 的核心函数，来自 `stage/agent_builder.py`。

它做的事分为六步：

1. 统计每个 `flight_id` 的观测量
2. 用 `_eval_agent_geo()` 恢复 flight 的经纬高和时间位置
3. 按地理可达性拆成 `tier1 / tier2`
4. 从 `flight_motion_grouped` 构造 agent 稀疏体素表示
5. 计算 agent 级时空置信度和通信权重
6. 计算 air-air 图并调用 `select_ff_edges()`

### 5.5 `select_ff_edges(...)`

这是 `Stage3` 图结构真正落边的地方，来自 `stage/communication_builder.py`。

输入：

- `comm_round`
- `ff_allowed`
- `ff_score`
- `flight_has_wind_obs`
- `max_neighbors_per_agent`

逻辑：

- `comm_round == 0`
  - 物理允许边全连通
- `comm_round >= 1`
  - 每个节点按 `ff_score` 保留 top-k 邻居

输出：

- `ff_sparse_src / ff_sparse_dst / ff_sparse_score`
- `ff_allowed_out`
- `ff_motion_allowed`
- `ff_wind_allowed`

风边策略：

- 双端都有风能力：强风边，gate=`1.0`
- 只有一端有风能力：弱风边，gate=`0.5`
- 双端都无风能力：不建风边

### 5.6 `_refine_flight_pack_with_wind_support(vox, flight_pack, h_dim, w_dim)`

这是 `Stage3` 当前最关键的增强点。

它不是简单用 `AMDAR flight_id` 判定风能力，而是四层证据链：

1. `direct`
   - 自身体素直接命中 wind voxels
2. `near`
   - 命中 wind 邻域
3. `geo`
   - 几何中心接近风体素簇
4. `soft`
   - 时空似然和通信权重足够支持

触发规则：

- `direct_ratio > 0`
- 或 `near_ratio >= 0.08`
- 或 `geo_score >= 0.12`
- 或 `support_score >= 0.18`

意义：

- 解决当前风观测过稀疏导致的 `wind_edges 全零`
- 让 `Stage4` 能消费一个不至于塌掉的风图

### 5.7 `build_agents_for_frame(vox)`

作用：

- 串起 ground 估计、agent build、wind support refine、summary 导出

它是一帧级别的主函数。

---

## 6. Stage3 参数表

### 6.1 来自 `pipeline_config.py` 的真实默认值

这些参数是 `Stage3` 实际消费的主阈值。

| 参数 | 默认值 | 解释 |
|---|---:|---|
| `LAT_MIN` | `12.2` | 中国域最小纬度 |
| `LAT_MAX` | `54.2` | 中国域最大纬度 |
| `LON_MIN` | `73.0` | 中国域最小经度 |
| `LON_MAX` | `135.0` | 中国域最大经度 |
| `ALT_MIN` | `0` | 最低高度，米 |
| `ALT_MAX` | `15000` | 最高高度，米 |
| `DELTA_ALT` | `500` | 垂向层高，米 |
| `Z_DIM` | `31` | 垂向离散层数 |
| `COMM_TIME_LIMIT_SECONDS` | `300` | ground-flight 可达时间阈值，秒 |
| `COMM_SPACE_LIMIT_KM` | `300` | ground-flight 水平距离阈值，公里 |
| `COMM_VERTICAL_LIMIT_M` | `5000` | ground-flight 垂直距离阈值，米 |
| `FF_COMM_TIME_LIMIT_SECONDS` | `120` | flight-flight 时间阈值，秒 |
| `FF_COMM_SPACE_LIMIT_KM` | `200` | flight-flight 水平距离阈值，公里 |
| `FF_COMM_VERTICAL_LIMIT_M` | `2000` | flight-flight 垂直距离阈值，米 |
| `FLIGHT_PREFER_COMM_ELIGIBLE` | `1` | 优先保留物理可通信 flight |
| `FLIGHT_TIER2_MAX` | `0` | tier2 回填上限，`0` 表示不额外截断 |
| `COMM_ROUND` | `1` | 边选择模式，`1` 表示 top-k sparse |
| `FF_MAX_NEIGHBORS_PER_AGENT` | `12` | 每个 agent 最多保留邻居数 |
| `PHYSICS_REALISM_MODE` | `1` | 启用更保守的物理筛选 |
| `SPACE_LIKELIHOOD_SIGMA_KM` | `180.0` | 固定空间似然水平尺度 |
| `SPACE_LIKELIHOOD_SIGMA_Z_M` | `2500.0` | 固定空间似然垂向尺度 |
| `ADAPTIVE_SPACE_LIKELIHOOD` | `1` | 按当前帧分布自适应空间尺度 |

### 6.2 `stage3_agents_v2.py` 直接读取的运行参数

| 参数 | 默认值 | 解释 |
|---|---:|---|
| `WIND_STAGE2_SUMMARY_PATH_OVERRIDE` | `BASE_DIR/stage2_output/stage2_summary.json` | 覆盖 Stage2 summary 路径 |
| `WIND_STAGE3_OUTPUT_DIR` | `BASE_DIR/stage3_output_v2` | 覆盖 Stage3 输出目录 |
| `WIND_PROGRESS_EVERY` | `25` | 日志进度打印间隔 |
| `WIND_FRAME_INDICES` | 空 | 精确抽帧 |
| `WIND_FRAME_OFFSET` | `0` | 跳过前若干帧 |
| `WIND_MAX_FRAMES` | `0/None` | 限制试跑帧数 |

### 6.3 `agent_builder.py` 内部补充环境参数

只有在 `PHYSICS_REALISM_MODE=1` 时，会再读：

| 参数 | 默认值 | 解释 |
|---|---:|---|
| `WIND_PHYSICS_MIN_PAIR_SCORE` | `0.06` | tier1 物理筛选最小分数 |
| `WIND_PHYSICS_MIN_TIER2_SCORE` | `0.03` | tier2 物理筛选最小分数 |

---

## 7. Stage3 原理说明

### 7.1 为什么要先做 Stage3 再做 Stage4

因为 `Stage4` 不是只做观测点插值，它还要用 flight topology、风能力节点、通信结构来构造 support、wind comm targets、forecast 先验。  
如果没有 `Stage3`，`Stage4` 就只剩稀疏点云和局部平滑，无法形成“协同感知”的图结构层。

### 7.2 为什么 Stage3 可以并行分片

`Stage3` 是 frame-level 相对独立任务：

- 主要依赖当前帧 `Stage2` npz
- 不依赖 `prev_recon_state`
- 更偏 CPU / IO / Polars

所以可以安全做 shard 并行，合并成 `stage3_output_v2`。

### 7.3 当前 Stage3 的边界

`Stage3` 当前主要提供：

- flight nodes
- comm edges
- motion edges
- wind edges
- wind support diagnostics

它不是最终展示层。  
因此之前更多依赖 `summary/json/log` 来核查，而不是图像展示。  
本次新增的 `Stage3` 可视化脚本，就是把已有结构结果转换成对外可讲解的图。

---

## 8. Stage3 可视化命令

### 8.1 代表帧展示

```bash
/opt/miniconda3/bin/python stage/report_stage3_agent_graph_visualization.py \
  --stage2-summary /data/LFT-W02_data/pengxu/stage2_output/stage2_summary.json \
  --stage3-summary /data/LFT-W02_data/pengxu/stage3_output_v2/stage3_summary.json \
  --stage3-dir /data/LFT-W02_data/pengxu/stage3_output_v2 \
  --out-dir /data/LFT-W02_data/pengxu/stage3_visualizations/stage3_output_v2_representative \
  --selection representative
```

输出：

- `selected_frames.json`
- `frame_<time>_geo.png`
- `frame_<time>_topology.png`

### 8.2 指定帧展示

```bash
/opt/miniconda3/bin/python stage/report_stage3_agent_graph_visualization.py \
  --stage2-summary /data/LFT-W02_data/pengxu/stage2_output/stage2_summary.json \
  --stage3-summary /data/LFT-W02_data/pengxu/stage3_output_v2/stage3_summary.json \
  --stage3-dir /data/LFT-W02_data/pengxu/stage3_output_v2 \
  --out-dir /data/LFT-W02_data/pengxu/stage3_visualizations/stage3_selected_frames \
  --selection frames \
  --frame-times 20260129174200,20260218211800
```

### 8.3 只做快速核查的命令

```bash
python -m json.tool /data/LFT-W02_data/pengxu/stage3_output_v2/stage3_summary.json
```

```bash
python - <<'PY'
import json
from pathlib import Path
p=Path('/data/LFT-W02_data/pengxu/stage3_output_v2/stage3_summary.json')
data=json.loads(p.read_text())
for key in ['valid_flight_agents','flight_ff_allowed_edges','flight_ff_wind_edges']:
    vals=[x.get(key,0) for x in data]
    print(key, 'min=', min(vals), 'mean=', sum(vals)/len(vals), 'max=', max(vals))
PY
```

---

# 第二部分：Stage4 深度说明

## 1. 含义

`Stage4` 的职责是把 `Stage2 + Stage3` 融合成当前论文主线里的风场状态层。

它主要做：

1. 对齐 `Stage2` 和 `Stage3`
2. 判断每帧是否值得做完整重构
3. 对触发帧执行多源风场重构
4. 生成 support / temporal / relax / prune / expand / anchor protect / forecast / hazard
5. 打包稀疏 lossless NPZ
6. 写 `stage4_summary.json`

它的意义不是“生成真值满场风场”，而是：

- 在全国雷达网格上构造一个可运行、可解释、可为 Stage5 提供输入的稀疏局部 3D 风场状态层

---

## 2. 调用顺序

当前真实调用链是：

`run_stage34_workflow_v2.sh -> stage4_pack_v2.py -> main() -> [_should_trigger_reconstruction()] -> _prepare_frame() / _build_lightweight_frame() -> _build_sparse_stage4_payload()`

更具体：

1. `main()`
   - 读取 `Stage2 summary`
   - 读取 `Stage3 summary + agents map`
   - 对齐帧
   - 逐帧判断是否触发重构

2. 若当前帧触发：
   - 调用 `_prepare_frame(stage2_item, stage3_item, prev_recon_state)`

3. 若当前帧不触发：
   - 调用 `_build_lightweight_frame(stage2_item, stage3_item)`

4. 统一调用 `_build_sparse_stage4_payload(frame, trigger, trigger_reason)`
   - 生成最终 `frame_<time>.npz`

5. 汇总每帧统计到 `stage4_summary.json`

6. 若 `output_profile=full_aux_export`
   - 走 `full_aux_export` 分支
   - 从已有 fast 结果补完整辅助场，不重跑主重构

---

## 3. 输入

### 3.1 目录与文件

`Stage4` 当前输入来自：

- `/data/LFT-W02_data/pengxu/stage2_output/stage2_summary.json`
- `/data/LFT-W02_data/pengxu/stage2_output/voxels/frame_<time>_voxels.npz`
- `/data/LFT-W02_data/pengxu/stage3_output_v2/stage3_summary.json`
- `/data/LFT-W02_data/pengxu/stage3_output_v2/agents/frame_<time>_agents.json`

`stage4_only` 特别注意：

- 如果不显式指定 `STAGE3_INPUT_DIR_FOR_STAGE4`
- 它有机会默认读旧目录 `stage3_output`
- 当前正式主线应明确使用 `stage3_output_v2`

### 3.2 `Stage4` 实际读入的关键 Stage2 / Stage3 信息

来自 Stage2：

- 风观测 voxel
- 轨迹 density voxel
- motion voxel
- AMDAR voxel
- TURB voxel
- radar image

来自 Stage3：

- `flight_pack`
- `ground_lat/lon/alt`
- `flight_ff_wind_edges`
- `flight_comm_allowed_agents`
- wind-capable flights

---

## 4. 输出

### 4.1 正式输出目录

主输出目录：

- `/data/LFT-W02_data/pengxu/stage4_output_v2`

每帧输出：

- `frame_<time>.npz`

汇总输出：

- `stage4_summary.json`

`full_aux_export` 独立输出目录：

- `/data/LFT-W02_data/pengxu/stage4_output_full_aux_v2/<RUN_LABEL>`

### 4.2 `stage4_summary.json` 真实字段

当前真实 key 包括：

- `amdar_keep_ratio`
- `amdar_voxels`
- `amdar_voxels_raw`
- `anchor_force_voxels`
- `anchor_restore_voxels`
- `candidate_flight_count`
- `comm_joint_voxels`
- `comm_motion_voxels`
- `comm_uncertainty_voxels`
- `comm_wind_voxels`
- `direct_agreement_mean`
- `filename`
- `flight_comm_allowed_agents`
- `flight_ff_allowed_edges`
- `flight_ff_motion_edges`
- `flight_ff_wind_edges`
- `forecast_conf_mean`
- `forecast_coverage_ratio`
- `ground_alt`
- `ground_lat`
- `ground_lon`
- `hazard_alert_voxels`
- `hazard_shear_mean`
- `hazard_turbulence_mean`
- `motion_keep_ratio`
- `motion_voxels`
- `motion_voxels_raw`
- `outlier_drop_voxels`
- `physics_weight_mean`
- `pinn_div_mean`
- `pinn_div_p90`
- `pinn_smooth_mean`
- `recon_conf_mean`
- `recon_conf_p10`
- `recon_conf_p25`
- `recon_conf_p50`
- `recon_conf_p75`
- `recon_conf_p90`
- `recon_conf_spread_p10_p90`
- `recon_coverage_ratio`
- `recon_domain_voxels`
- `recon_filled_voxels`
- `recon_pruned_voxels`
- `recon_seed_strength`
- `recon_support_domain_voxels`
- `recon_trigger_reason`
- `recon_triggered`
- `relax_steps_used`
- `source_diversity_mean`
- `source_index`
- `support_expand_voxels`
- `support_fill_kept_voxels`
- `support_fill_voxels`
- `support_voxels`
- `temporal_fill_kept_voxels`
- `temporal_fill_voxels`
- `tier1_candidate_count`
- `tier2_candidate_count`
- `time_str`
- `timestamp_utc`
- `traj_voxels`
- `traj_voxels_raw`
- `turb_voxels`
- `turb_voxels_raw`
- `valid_flight_agents`
- `wind_conflict_keep_voxels`
- `wind_keep_ratio`
- `wind_overlap_ratio`
- `wind_overlap_removed`
- `wind_seed_voxels`
- `wind_voxels`
- `wind_voxels_primary`
- `wind_voxels_raw`

### 4.3 `frame_<time>.npz` 真实 key 分组

当前真实 key 包括这些大组：

#### A. 稀疏观测输入层

- `trajectory_idx`
- `trajectory_val`
- `uv_idx`
- `u_val`
- `v_val`
- `wind_count_val`
- `wind_conf_val`
- `motion_idx`
- `motion_u_val`
- `motion_v_val`
- `motion_count_val`
- `amdar_idx`
- `amdar_u_val`
- `amdar_v_val`
- `turb_idx`
- `turb_u_val`
- `turb_v_val`

#### B. 通信/图目标层

- `comm_idx`
- `comm_score`
- `comm_joint_idx`
- `comm_joint_score`
- `comm_wind_idx`
- `comm_wind_score`
- `comm_motion_idx`
- `comm_motion_score`

#### C. Stage3 agent 层

- `flight_agent_ids`
- `flight_offsets`
- `flight_idx_flat`
- `flight_u_flat`
- `flight_v_flat`
- `flight_count_flat`
- `flight_mask`
- `flight_comm_allowed`
- `flight_comm_weight`
- `flight_has_wind_obs`
- `ff_comm_allowed`
- `ff_comm_weight`
- `ff_motion_allowed`
- `ff_motion_weight`
- `ff_wind_allowed`
- `ff_wind_weight`

#### D. 主重构层

- `recon_u_3d`
- `recon_v_3d`
- `recon_confidence_3d`
- `recon_mask_3d`
- `recon_idx`
- `recon_u_val`
- `recon_v_val`
- `recon_conf_val`
- `recon_mask_val`
- `recon_triggered`
- `recon_trigger_reason`

#### E. 物理/辅助层

- `trajectory_3d`
- `physics_weight_3d`
- `pinn_divergence_3d`
- `pinn_smoothness_3d`
- `source_diversity_3d`
- `direct_agreement_3d`
- `direct_source_count_3d`
- `diffusion_condition_4d`
- `diffusion_prior_u_3d`
- `diffusion_prior_v_3d`
- `diffusion_prior_confidence_3d`

#### F. forecast / hazard 层

- `forecast_u_3d`
- `forecast_v_3d`
- `forecast_confidence_3d`
- `forecast_mask_3d`
- `hazard_shear_3d`
- `hazard_turbulence_3d`
- `hazard_alert_mask_3d`

#### G. 元信息

- `storage_mode`
- `grid_shape`
- `radar_2d`
- `ground_agent_id`
- `ground_agent_type`
- `ground_agent_lat`
- `ground_agent_lon`
- `ground_agent_alt_m`

---

## 5. 重点函数逐项解释

### 5.1 `_should_trigger_reconstruction(curr_item, prev_item)`

作用：

- 决定当前帧是否值得做完整重构

触发依据：

- `wind_voxels`
- `motion_voxels`
- `flight_ff_wind_edges`
- `flight_comm_allowed_agents`
- `recon_seed_strength`

规则特点：

- 同时看相对变化和绝对变化
- 对不连续抽帧直接标记 `discontiguous_frame_gap`
- 首帧必触发

意义：

- 避免每帧都做重计算
- 保留事件驱动语义

### 5.2 `_prepare_frame(stage2_item, stage3_item, prev_recon_state=None)`

这是 `Stage4` 真正的主重构函数。

它做的事很多，按顺序可以分成：

1. 读取 Stage2 voxel 和 Stage3 agent json
2. 清洗 `wind / loc / motion / amdar / turb`
3. 执行 `_dedupe_primary_wind_source()`
4. 构造 `flight_seed_df`
5. 构造 `trajectory_3d` 与 `support_strength`
6. 根据活动区域裁剪成局部 bbox
7. 调用 `_reconstruct_wind_field()` 做基础重构
8. 依次执行：
   - `support fill`
   - `temporal fill`
   - `relax`
   - `confidence refine`
   - `outlier suppress`
   - `prune`
   - `expand`
   - `anchor restore`
   - `anchor force`
9. 生成：
   - `pinn proxy`
   - `where2comm targets`
   - `forecast`
   - `hazard`
10. 回填到 full-size 3D volume

### 5.3 `_build_lightweight_frame(stage2_item, stage3_item)`

作用：

- 给非触发帧生成极简样本

它保留：

- 原始 sparse observations
- radar
- Stage3 agent layer
- 必要元信息

它不做：

- 完整风场重构
- support fill
- temporal fill
- forecast
- hazard
- diffusion condition

意义：

- 保证 Stage4 不是“每帧都全量重构”
- 让非事件帧仍然可被后续流水线识别

### 5.4 `_dedupe_primary_wind_source(wind_grouped, amdar_grouped, turb_grouped)`

作用：

- 避免 `wind_grouped` 和 `amdar/turb` 在高重叠时重复计权

规则：

- 只有当 `overlap_ratio >= 0.92` 才启动去重
- 若去重后 primary 为空，且启用了 fallback
  - 保留少量代表性 `wind_primary`

当前 fallback 参数：

- `WIND_STAGE4_ENABLE_PRIMARY_ANCHOR_FALLBACK=1`
- `WIND_STAGE4_PRIMARY_ANCHOR_FALLBACK_RATIO=0.08`
- `WIND_STAGE4_PRIMARY_ANCHOR_FALLBACK_MAX=8`
- `WIND_STAGE4_PRIMARY_ANCHOR_FALLBACK_WEIGHT=0.18`

意义：

- 控制重复加权
- 同时不把 direct anchor 完全删空

### 5.5 `_reconstruct_wind_field(...)`

来自 `stage/reconstruct_utils_v2.py`，是 `Stage4` 的基础重构器。

核心逻辑：

1. 汇总 `wind / motion / amdar / turb`
2. 用不同 source 的误差尺度做加权融合
3. 在同 voxel 内融合 `u/v`
4. 生成 `recon_u / recon_v / recon_conf / recon_mask`
5. 可选做 bounded local IDW 补洞

当前 source error sigma 默认值：

- `wind = 2.2`
- `motion = 5.5`
- `amdar = 1.4`
- `turb = 2.8`

意义：

- 这是 `Stage4` 基础“多源观测融合核”
- 后续 support/temporal/relax 都是在它之上继续塑形

### 5.6 `_support_guided_fill(...)`

作用：

- 用 `support_strength` 引导当前重构缺失区补全

特点：

- 只在 support 区域里补
- 需要最少邻居数
- 有 local spread 限制

意义：

- coverage 温和提升
- 不做无约束全域扩散

### 5.7 `_apply_temporal_background(...)`

作用：

- 用上一帧重构作为当前帧背景场

前提：

- `prev_recon_state` 存在
- `source_index` 连续
- 当前 support 区域缺值

意义：

- 提供时序一致性
- 这也是为什么 `Stage4` 默认不能像 `Stage3` 一样分片并行

### 5.8 `_physics_guided_relaxation(...)`

作用：

- 对低置信度区做轻量邻域平滑

意义：

- 不是严格 PINN
- 但提供了工程上可运行的物理一致性 proxy

### 5.9 `_prune_low_quality_reconstruction(...)`

作用：

- 去掉低质量重构体素

意义：

- 防止只追 coverage
- 让最终 mask 更保守、更可解释

### 5.10 `_expand_supported_reconstruction(...)`

作用：

- 在 support 强、置信度条件满足时适度扩张

意义：

- 是 `S5 FinalFast` 的最终 coverage 提升组件
- 但当前已冻结，不再无限追扩张

### 5.11 `_restore_direct_anchor_voxels(...)`

作用：

- 恢复被后处理误删的 direct observation anchors

### 5.12 `_enforce_direct_anchor_values(...)`

作用：

- 对明显偏离 direct anchors 的值做保守回写

意义：

- 这两步一起保证 `anchor fidelity`
- 是 `Stage4` 当前非常重要的硬边界

### 5.13 `_forecast_next_wind_field(...)`

作用：

- 生成下一时刻 forecast proxy

注意：

- 它属于 Stage4 状态层内部的短期 forecast 辅助
- 不是 Stage5 独立预测系统

### 5.14 `_compute_hazard_proxies(...)`

作用：

- 基于 forecast、support、divergence、smoothness 生成 hazard proxy

输出：

- `hazard_shear_3d`
- `hazard_turbulence_3d`
- `hazard_alert_mask_3d`

### 5.15 `_build_sparse_stage4_payload(frame, trigger, trigger_reason)`

作用：

- 将前面得到的一切统一打包到最终 `npz`

意义：

- 让 fast/full_aux 共享一套稳定输出协议

### 5.16 `_augment_existing_stage4_npz_with_full_aux(...)`

作用：

- `full_aux_export` 模式下，从已有 fast npz 补写完整辅助场

意义：

- 这是当前 `full_aux_export` 的正确边界：
  - 基于已有 fast 结果后处理
  - 不是重新走主重构链

---

## 6. Stage4 参数表

## 6.1 support / temporal / relax

| 参数 | 默认值 | 解释 |
|---|---:|---|
| `WIND_RECON_SUPPORT_RADIUS_XY` | `4` | support fill 水平邻域半径 |
| `WIND_RECON_SUPPORT_RADIUS_Z` | `2` | support fill 垂向邻域半径 |
| `WIND_RECON_SUPPORT_MAX_FILL` | `20000` | support fill 最大补点数 |
| `WIND_RECON_SUPPORT_FILL_MIN_SUPPORT` | `0.12` | 允许 support fill 的最小 support |
| `WIND_RECON_SUPPORT_FILL_MIN_NEIGHBORS` | `3` | 最少邻居数 |
| `WIND_RECON_SUPPORT_FILL_MAX_LOCAL_SPREAD` | `18.0` | 局地 spread 上限 |
| `WIND_RECON_TEMPORAL_BG_BLEND` | `0.36` | temporal 背景混合强度 |
| `WIND_RECON_TEMPORAL_BG_MAX_GAP` | `1` | 允许 temporal 引用的最大帧间隔 |
| `WIND_RECON_RELAX_STEPS` | `2` | relax 迭代步数 |
| `WIND_RECON_RELAX_BLEND` | `0.15` | relax 混合强度 |

## 6.2 communication / forecast / hazard

| 参数 | 默认值 | 解释 |
|---|---:|---|
| `COMM_TOPK_RATIO` | `0.30` | 通信优先体素 top-k 比例 |
| `COMM_MIN_TOPK` | `32` | 通信优先体素最小 top-k |
| `COMM_WIND_WEIGHT` | `0.70` | joint comm 里 wind 权重 |
| `COMM_MOTION_WEIGHT` | `0.30` | joint comm 里 motion 权重 |
| `WIND_FORECAST_BLEND` | `0.35` | forecast 混合强度 |
| `WIND_FORECAST_CONF_DECAY` | `0.85` | forecast 置信衰减 |
| `WIND_FORECAST_COMM_CONF_BOOST` | `0.10` | forecast 中 comm 置信提升 |
| `WIND_HAZARD_SHEAR_ALERT` | `0.40` | hazard shear 阈值 |
| `WIND_HAZARD_TURB_ALERT` | `0.45` | hazard turbulence 阈值 |

## 6.3 confidence / outlier / pruning

| 参数 | 默认值 | 解释 |
|---|---:|---|
| `WIND_RECON_OUTLIER_SPEED_PENALTY` | `0.35` | 高速异常惩罚 |
| `WIND_RECON_OUTLIER_GRAD_PENALTY` | `0.30` | 梯度异常惩罚 |
| `WIND_RECON_OUTLIER_GRAD_Q` | `0.995` | 梯度异常分位阈值 |
| `WIND_RECON_CONF_KEEP_FLOOR` | `0.08` | 置信保底 |
| `WIND_RECON_SUPPORT_KEEP_Q` | `0.10` | support keep 分位阈值 |
| `WIND_RECON_SUPPORT_COVERAGE_EXPAND_Q` | `0.82` | expand support 分位阈值 |
| `WIND_RECON_SUPPORT_COVERAGE_EXPAND_MIN` | `0.18` | expand 最小 support |
| `WIND_RECON_SUPPORT_COVERAGE_CONF_MIN` | `0.10` | expand 最小置信度 |
| `WIND_RECON_CONF_MID_BAND_BOOST` | `0.04` | 中段置信提升 |
| `WIND_RECON_SUPPORT_CONF_BOOST` | `0.01` | support fill 置信 boost |
| `WIND_RECON_TEMPORAL_CONF_BOOST` | `0.03` | temporal fill 置信 boost |
| `WIND_RECON_INDIRECT_CONF_BOOST` | `0.03` | indirect recon 置信 boost |
| `WIND_RECON_RELAX_KEEP_RATIO` | `0.95` | relax 后保留比例 |
| `WIND_RECON_ENABLE_CONF_BOOSTS` | `0` | 是否启用 boost 逻辑 |

## 6.4 primary anchor / direct anchor

| 参数 | 默认值 | 解释 |
|---|---:|---|
| `WIND_PRIMARY_CONFLICT_KEEP_MS` | `8.0` | primary 冲突保留阈值 |
| `WIND_STAGE4_ENABLE_PRIMARY_ANCHOR_FALLBACK` | `1` | 启用 primary fallback |
| `WIND_STAGE4_PRIMARY_ANCHOR_FALLBACK_RATIO` | `0.08` | fallback 比例 |
| `WIND_STAGE4_PRIMARY_ANCHOR_FALLBACK_MAX` | `8` | fallback 最大点数 |
| `WIND_STAGE4_PRIMARY_ANCHOR_FALLBACK_WEIGHT` | `0.18` | fallback 权重缩放 |
| `WIND_DIRECT_AGREEMENT_SCALE_MS` | `12.0` | direct agreement 尺度 |
| `WIND_DIRECT_SOURCE_SOFT_SPEED_CAP_MS` | `120.0` | soft speed cap |
| `WIND_DIRECT_SOURCE_SOFT_SPEED_PENALTY` | `0.35` | soft speed penalty |
| `WIND_DIRECT_ANCHOR_FORCE_DIFF_MS` | `8.0` | direct anchor force 差值阈值 |
| `WIND_DIRECT_ANCHOR_ZERO_SPEED_MS` | `1.0` | 零速误回写阈值 |

## 6.5 base recon / fast / profile / switches

| 参数 | 默认值 | 解释 |
|---|---:|---|
| `WIND_STAGE4_BASE_RECON_ENABLE_IDW` | `0` | 基础重构是否启用 IDW |
| `WIND_STAGE4_BASE_RECON_IDW_MAX_FILL` | `512` | IDW 最大补点数 |
| `WIND_STAGE4_FAST_MODE` | `0` | 是否 fast mode |
| `WIND_STAGE4_FAST_SKIP_DENSE_AUX` | `1` | fast 模式跳过 dense aux |
| `WIND_STAGE4_FAST_SKIP_POST` | `1` | fast 模式跳过重 post |
| `WIND_STAGE4_SAVE_COMPRESSED` | `1` | 是否保存压缩 npz |
| `WIND_STAGE4_OUTPUT_PROFILE` | `fast/full_aux...` | 输出 profile |
| `WIND_STAGE4_ENABLE_QUALITY_EXPAND` | `profile dependent` | 是否启用更激进扩张 |
| `WIND_STAGE4_ENABLE_SUPPORT_FILL` | `1` | support fill 开关 |
| `WIND_STAGE4_ENABLE_TEMPORAL_FILL` | `1` | temporal fill 开关 |
| `WIND_STAGE4_ENABLE_RELAX` | `1` | relax 开关 |
| `WIND_STAGE4_ENABLE_PRUNE` | `1` | prune 开关 |
| `WIND_STAGE4_ENABLE_EXPAND` | `1` | expand 开关 |
| `WIND_STAGE4_ENABLE_DIRECT_ANCHOR_RESTORE` | `1` | anchor restore 开关 |
| `WIND_STAGE4_ENABLE_DIRECT_ANCHOR_FORCE` | `1` | anchor force 开关 |

## 6.6 GPU / thread

| 参数 | 默认值 | 解释 |
|---|---:|---|
| `WIND_STAGE4_USE_GPU` | `auto` | GPU 使用模式 |
| `WIND_STAGE4_GPU_DEVICE` | `cuda:0` | 默认 GPU 设备 |
| `WIND_STAGE4_GPU_MIN_NUMEL` | `1200000` | 小规模张量不启用 GPU |
| `OMP_NUM_THREADS` | 外部注入 | OpenMP 线程数 |
| `MKL_NUM_THREADS` | 外部注入 | MKL 线程数 |
| `NUMEXPR_NUM_THREADS` | 外部注入 | numexpr 线程数 |
| `POLARS_MAX_THREADS` | 外部注入 | Polars 线程数 |

---

## 7. Stage4 原理说明

### 7.1 为什么 Stage4 默认必须串行

因为 `Stage4` 显式依赖：

- `prev_recon_state`
- `temporal background`
- `forecast_next_wind_field`
- 触发器的前帧比较

如果像 `Stage3` 一样 frame-level 分片：

- 时序连续性会断
- `first_frame/discontiguous_frame_gap` 行为会变
- 结果会变

所以默认策略必须是：

- `Stage3` 并行
- `Stage4` 单进程单卡串行

### 7.2 为什么 Stage4 不是每帧都全量重构

因为 `Stage4` 当前被设计成事件驱动式状态更新层。  
大量相邻帧变化不大时，没必要每次都重建 full pipeline。  
因此非触发帧只输出轻量样本，触发帧才走 `_prepare_frame()`。

### 7.3 当前 Stage4 的冻结标准

当前不再以“coverage 越高越好”为目标，而是：

1. anchor fidelity 稳
2. coverage 温和提升即可
3. confidence 有层次
4. 运行链路稳定
5. 模块可开关，可消融

### 7.4 `fast` 与 `full_aux_export` 的边界

`fast`：

- 当前主运行结果语境
- 主结果版本对应 `S5 FinalFast`

`full_aux_export`：

- 从已有 fast 结果补 richer aux fields
- 输出到独立目录
- 不与主结果混写

---

## 8. Stage4 可视化命令

### 8.1 代表帧 2D/3D 风场展示

```bash
/opt/miniconda3/bin/python stage/report_stage4_recon_slices.py \
  --stage4-dir /data/LFT-W02_data/pengxu/stage4_output_v2 \
  --summary /data/LFT-W02_data/pengxu/stage4_output_v2/stage4_summary.json \
  --out-dir /data/LFT-W02_data/pengxu/stage4_visualizations/stage4_output_v2_representative \
  --selection representative \
  --viz-mode both \
  --max-vectors 250 \
  --z-exaggeration 40 \
  --min-conf 0.0
```

### 8.2 指定帧 2D/3D 风场展示

```bash
/opt/miniconda3/bin/python stage/report_stage4_recon_slices.py \
  --stage4-dir /data/LFT-W02_data/pengxu/stage4_output_v2 \
  --summary /data/LFT-W02_data/pengxu/stage4_output_v2/stage4_summary.json \
  --out-dir /data/LFT-W02_data/pengxu/stage4_visualizations/stage4_selected_frames \
  --selection frames \
  --frame-times 20260129174200,20260218211800 \
  --viz-mode both \
  --max-vectors 250 \
  --z-exaggeration 40 \
  --min-conf 0.0
```

### 8.3 地理坐标 3D 风场展示

```bash
/opt/miniconda3/bin/python stage/report_stage4_geo_wind_visualization.py \
  --stage4-dir /data/LFT-W02_data/pengxu/stage4_output_v2 \
  --summary /data/LFT-W02_data/pengxu/stage4_output_v2/stage4_summary.json \
  --out-dir /data/LFT-W02_data/pengxu/stage4_visualizations/stage4_output_v2_geo_representative \
  --selection representative
```

说明：

- `report_stage4_recon_slices.py`
  - 强调重构切片、3D sparse quiver
- `report_stage4_geo_wind_visualization.py`
  - 强调经纬高坐标下的真实位置表达
- 这些图表达的是“全国雷达网格上的稀疏局部三维风场重构”
  - 不是全国满场风真值

---

# 第三部分：联合运行脚本深度说明

## 1. 含义

`stage/run_stage34_workflow_v2.sh` 是当前 `Stage3 + Stage4` 的统一主控脚本。

它不是简单的 shell 包装，而是完整的运行编排器，负责：

1. 选帧
2. 规划 phase
3. 配置输入输出目录
4. 运行 Stage3 / Stage4
5. 支持多 shard Stage3
6. 汇总 summary 日志
7. validate
8. collect 本次 run 输出
9. export
10. readiness / sparse metrics / outliers / npz check / keylog

---

## 2. 输入与输出目录关系

### 2.1 默认目录

| 变量 | 默认值 | 含义 |
|---|---|---|
| `STAGE2_OUTPUT_DIR` | `$BASE_DIR/stage2_output` | Stage2 输入目录 |
| `STAGE3_OUTPUT_DIR_V2` | `$BASE_DIR/stage3_output_v2` | Stage3 正式输出目录 |
| `STAGE3_INPUT_DIR_ORIG` | `$BASE_DIR/stage3_output` | Stage4_only 默认旧输入目录 |
| `STAGE4_OUTPUT_DIR` | `$BASE_DIR/stage4_output_v2` | Stage4 正式输出目录 |
| `STAGE4_FAST_SOURCE_DIR` | `$STAGE4_OUTPUT_DIR` | full_aux_export 的 fast 源目录 |
| `STAGE4_FULL_AUX_OUTPUT_ROOT` | `$BASE_DIR/stage4_output_full_aux_v2` | full aux 独立输出根目录 |
| `STAGE4_RUN_ROOT` | `$BASE_DIR/stage4_output_runs_v2` | 本次 run 子集收集目录 |
| `EXPORT_DST` | `$BASE_DIR/dataset_output_stage4_v2_clean` | export 目标目录 |

### 2.2 当前主线关系

最重要的关系是：

- `Stage3` 正式结果写入 `stage3_output_v2`
- `Stage4` 主线应读取 `stage3_output_v2`
- `Stage4` 正式结果写入 `stage4_output_v2`
- `full_aux_export` 单独写 `stage4_output_full_aux_v2/<RUN_LABEL>`

---

## 3. 重点函数逐项解释

### 3.1 `plan_run_phases()`

作用：

- 根据 `RUN_PHASE` 或 `RUN_PHASES` 决定启用哪些 phase

支持 phase 包括：

- `stage3`
- `stage3_summary`
- `stage4`
- `stage4_summary`
- `validate`
- `collect`
- `export`
- `readiness`
- `sparse_metrics`
- `outliers`
- `npz_check`
- `keylog`

### 3.2 `select_run_mode()`

作用：

- 根据 `RUN_MODE` 设置选帧方式和日志目录

支持模式：

- `first3`
- `offset`
- `indices`
- `topwind_auto`
- `full`

同时还会针对：

- `RUN_PHASE=full`
- `RUN_PHASE=full_fast_multi_gpu`
- `RUN_PHASE=full_aux_export`

自动注入合适的 `Stage4` profile 环境变量。

### 3.3 `run_stage3_script()`

作用：

- 设置：
  - `WIND_STAGE2_SUMMARY_PATH_OVERRIDE`
  - `WIND_STAGE3_OUTPUT_DIR`
- 执行 `python stage3_agents_v2.py`

### 3.4 `run_stage4_script()`

作用：

- 设置：
  - `WIND_STAGE2_SUMMARY_PATH_OVERRIDE`
  - `WIND_STAGE3_INPUT_DIR`
  - `WIND_STAGE4_OUTPUT_DIR`
  - 线程变量
- 执行 `python stage4_pack_v2.py`

### 3.5 `run_full_fast_multi_gpu()`

作用：

- `Stage3` 分 shard 并行
- 合并 `Stage3` shards
- 默认 `Stage4` 仍单进程单卡串行
- 只有 `MULTI_GPU_STAGE4_SHARD=1` 时才允许实验性 Stage4 shard

意义：

- 这正是当前推荐的：
  - `Stage3=sharded`
  - `Stage4=single-gpu-serial`

### 3.6 `merge_stage3_shards()`

作用：

- 合并每个 shard 的 `stage3_summary.json`
- 复制 `agents/*.json`
- 重写 merged `agent_path`

### 3.7 `merge_stage4_shards()`

作用：

- 合并每个 shard 的 `frame_*.npz`
- 合并 `stage4_summary.json`

注意：

- 这只适用于实验性 Stage4 shard
- 当前默认主线不推荐依赖它

### 3.8 `run_validate()`

作用：

- 自动定位 `validate_pipeline_constracts.py`
- 对当前 Stage3/Stage4 输出做契约验证

### 3.9 `write_stage3_summary_logs()`

作用：

- 从 `stage3_summary.json` 提取关键统计，生成可阅读日志

### 3.10 `write_stage4_summary_logs()`

作用：

- 从 `stage4_summary.json` 提取关键统计，生成可阅读日志

### 3.11 `collect_current_stage4_run()`

作用：

- 把当前一次运行涉及的 `Stage4` 输出复制到独立 `run dir`

意义：

- 防止 export 混入历史旧帧

### 3.12 `run_export()`

作用：

- 自动定位 `export_stage4_dataset.py`
- 从本次 run 子集目录做 export

### 3.13 `run_stage4_readiness_report()`

作用：

- 执行 `report_stage4_training_readiness.py`
- 生成 readiness 统计

### 3.14 `run_stage4_sparse_metrics_report()`

作用：

- 执行 `report_stage4_sparse_metrics.py`
- 生成稀疏监督主指标

### 3.15 `run_stage4_outlier_report()`

作用：

- 执行 `report_stage4_outlier_report.py`
- 定位异常帧

### 3.16 `check_stage4_npz_fields_current_run()`

作用：

- 抽样检查 Stage4 NPZ 关键字段是否存在

### 3.17 `build_key_log()`

作用：

- 汇总：
  - phase status
  - Stage3 wind log
  - Stage4 diag/frame log
  - summary logs
  - validate
  - readiness
  - sparse metrics
  - outliers
  - export

是最适合新窗口快速看本次运行结果的总入口日志。

---

## 4. 运行参数表

### 4.1 模式与阶段

| 参数 | 默认值 | 解释 |
|---|---|---|
| `RUN_MODE` | `topwind_auto` | 选帧模式 |
| `RUN_PHASE` | `stage4_only` | 预定义阶段方案 |
| `RUN_PHASES` | 空 | 自定义 phase 列表 |
| `MAX_FRAMES` | `3` | 连续试跑帧数 |
| `FRAME_OFFSET` | `300` | offset 模式起始偏移 |
| `FRAME_INDICES` | 空 | indices 模式下标列表 |
| `TOPWIND_COUNT` | `3` | topwind_auto 代表帧数量 |
| `RUN_LABEL_OVERRIDE` | 空 | 自定义运行标签 |

### 4.2 控制与验证

| 参数 | 默认值 | 解释 |
|---|---:|---|
| `EXPORT_AFTER_RUN` | `1` | 跑完后是否 export |
| `RUN_VALIDATE` | `1` | 是否做 validate |
| `PROGRESS_EVERY` | `1` | export/汇总类进度间隔 |
| `FAST_FULL_MODE` | `1` | full 模式是否启用 Stage4 fast full |

### 4.3 并行与线程

| 参数 | 默认值 | 解释 |
|---|---:|---|
| `STAGE3_PARALLEL_SHARDS` | `8` | Stage3 shard 数 |
| `STAGE3_CPU_THREADS_PER_WORKER` | `2` | 每个 Stage3 worker 线程数 |
| `STAGE4_CPU_THREADS` | `8` | Stage4 CPU 线程数 |
| `MULTI_GPU_STAGE4_SHARD` | `0` | 是否实验性启用 Stage4 分片 |

### 4.4 典型 phase 语义

| `RUN_PHASE` | 含义 |
|---|---|
| `stage3_only` | 只跑 Stage3 |
| `stage4_only` | 只跑 Stage4 |
| `stage34_core` | 跑 Stage3 + Stage4 主链 |
| `reports_only` | 不重算，只出报告 |
| `full_fast_multi_gpu` | Stage3 shard + Stage4 fast 主链 |
| `full_aux_export` | 基于 fast 结果补完整辅助场 |
| `full` | 当前全量运行入口，通常也走 fast 风格主链 |

---

## 5. 联合脚本原理说明

### 5.1 为什么要有这一层脚本

因为 `Stage3/Stage4` 不只是两个 Python 文件，真实工作流还需要：

- 选帧
- 切 shard
- 目录切换
- 环境变量设置
- 日志收集
- 结果打包
- 质量报告

这些逻辑如果每次手工拼，会非常容易出错。

### 5.2 为什么 Stage3 和 Stage4 的并行策略要不同

因为二者物理语义不同：

- `Stage3`：frame-level 独立，可 shard
- `Stage4`：时序状态层，不应默认 shard

联合脚本的最大价值之一，就是把这个工程事实固化下来，避免误操作。

### 5.3 当前主结果版本语境

对论文主结果来说：

- `Stage3` 是前置图结构层
- `Stage4` 主结果应放在 `S5 FinalFast`
- `full_aux_export` 是训练前 richer aux 导出
- 不能把 `full_aux_export` 当主结果图混写

---

## 6. 推荐阅读和使用顺序

如果你已经知道要做什么：

1. 先看 `15_requirement_command_guide.md`
2. 再按需看 `07_full_command_catalog.md`
3. 涉及全量运行和监控时补看：
   - `05_full_run_monitoring_checklist.md`
   - `06_server_top10_monitor_commands.md`

如果你需要解释代码和设计：

1. 先看本文件
2. 再看：
   - `01_stage34_pipeline.md`
   - `02_stage4_modification_and_freeze.md`
   - `03_stage4_paper_experiment_matrix.md`
   - `12_stage4_anchor_fallback_and_3d_visualization.md`

---

## 7. 边界提醒

1. 不要把 `stage3_output` 和 `stage3_output_v2` 混为一谈
2. 不要把 `Stage4` 轻量非触发帧和触发重构帧混为一谈
3. 不要把 `fast` 主结果与 `full_aux_export` 输出混写
4. 不要把 `historical GFS comparison`、实时 `GFS/GDAS` 背景图和 `Stage4/Stage5` 重构结果混图
5. `Stage4` 当前是冻结主链，不再无限追 coverage

