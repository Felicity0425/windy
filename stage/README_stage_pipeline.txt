# 航班-风场多阶段处理与重构流水线

> 面向项目成员、新人学习、后续调参与排查的完整说明文档
> 适用于 Stage 1 / Stage 2 / Stage 3 / Stage 4 的数据处理、建图、重构与导出流程

---

## 目录

- [1. 项目目标](#1-项目目标)
- [2. 总体流程](#2-总体流程)
- [3. 数据输入说明](#3-数据输入说明)
- [4. Stage 1：数据清洗与统一](#4-stage-1数据清洗与统一)
- [5. Stage 2：体素化与空间离散化](#5-stage-2体素化与空间离散化)
- [6. Stage 3：飞行智能体与三层边建图](#6-stage-3飞行智能体与三层边建图)
- [7. Stage 4：风场重构与训练样本打包](#7-stage-4风场重构与训练样本打包)
- [8. 重构模块说明](#8-重构模块说明)
- [9. 导出阶段说明](#9-导出阶段说明)
- [10. 契约检查说明](#10-契约检查说明)
- [11. 推荐运行顺序](#11-推荐运行顺序)
- [12. 小批量测试命令](#12-小批量测试命令)
- [13. 检查命令](#13-检查命令)
- [14. 常见问题](#14-常见问题)
- [15. 关键术语表](#15-关键术语表)
- [16. 经验总结](#16-经验总结)
- [17. 新成员操作建议](#17-新成员操作建议)

---

## 1. 项目目标

本项目的目标是把原始航空观测、雷达图像、风观测、轨迹信息、AMDAR 和湍流等多源数据，逐步整理成可用于风场分析、图结构建模和后续训练的标准化数据集。

整个流水线分为四个核心阶段：

1. **Stage 1**：初始数据清洗与统一  
2. **Stage 2**：体素化与空间离散化  
3. **Stage 3**：飞行智能体构建与三层边建图  
4. **Stage 4**：风场重构与训练样本打包  

后续还可以扩展 **Stage 5**，用于 PINN、diffusion 或其他生成式细化模型。

---

## 2. 总体流程

```text
原始数据
  ↓
Stage 1：清洗与统一
  ↓
Stage 2：体素化
  ↓
Stage 3：智能体与建图
  ↓
Stage 4：风场重构与打包
  ↓
训练数据集
```

### 总体设计思想

整条流水线采用“先清洗、再体素化、再建图、再重构、最后导出”的分层设计。这样做的好处是：

- 每一步都可单独检查
- 便于定位错误
- 可以保留轻量样本与事件样本
- 方便后续训练和在线推理
- 适合从稀疏观测逐步恢复结构化风场

核心思想不是每帧都做最重计算，而是：

- **普通帧**：轻量处理，保留结构和基础状态
- **变化帧**：触发完整风场重构

---

## 3. 数据输入说明

项目常见输入包括：

### 3.0 统一的字段约定与函数约定

为了避免 Stage 1–4 之间字段名混乱，项目中已经约定了一组统一的字段常量和辅助函数。后续阅读代码时，建议优先看 `schema_contract.py`、`pipeline_config.py` 和 `reconstruct_utils.py`。

#### 3.0.1 常见字段常量

这些字段通常在 `schema_contract.py` 中统一维护：

- `STAGE2_FILENAME`：Stage 2 中单帧文件名字段
- `STAGE2_TIME_STR`：雷达帧时间字符串
- `STAGE2_TIMESTAMP_UTC`：UTC 时间戳
- `STAGE2_RADAR_IMG`：雷达图像数组
- `STAGE2_WIND_RECORDS`：风体素记录
- `STAGE2_LOC_RECORDS`：轨迹体素记录
- `STAGE2_MOTION_RECORDS`：运动体素记录
- `STAGE2_FLIGHT_RAW_RECORDS`：飞行原始记录
- `STAGE2_AMDAR_RECORDS`：AMDAR 体素记录
- `STAGE2_TURB_RECORDS`：湍流体素记录

Stage 3 / 4 常见字段：

- `FLIGHT_COMM_ALLOWED`
- `FLIGHT_FF_COMM_ALLOWED`
- `FLIGHT_FF_MOTION_ALLOWED`
- `FLIGHT_FF_WIND_ALLOWED`
- `RECON_U_3D`
- `RECON_V_3D`
- `RECON_CONF_3D`
- `RECON_MASK_3D`

#### 3.0.2 常见配置常量

这些常量通常在 `pipeline_config.py` 中定义或从环境变量读取：

- `BASE_DIR`：项目根目录
- `DATA_ROOT`：当前数据根目录
- `OUTPUT_DIR`：输出目录名
- `Z_DIM`：垂直方向体素数
- `MAX_WIND_SPEED_MS`：最大有效风速
- `COMM_TIME_LIMIT_SECONDS`：通信时间阈值
- `COMM_SPACE_LIMIT_KM`：通信水平距离阈值
- `COMM_VERTICAL_LIMIT_M`：通信垂直距离阈值
- `FF_COMM_TIME_LIMIT_SECONDS`：飞行-飞行通信时间阈值
- `FF_COMM_SPACE_LIMIT_KM`：飞行-飞行通信水平距离阈值
- `FF_COMM_VERTICAL_LIMIT_M`：飞行-飞行通信垂直距离阈值
- `RECON_ENABLE_IDW`：是否启用局部 IDW 补全
- `RECON_IDW_MAX_FILL`：IDW 最大补全体素数

#### 3.0.3 常见函数定义

以下函数是 Stage 3 / Stage 4 中最常见、最关键的函数：

- `_reconstruct_wind_field(...)`
  - 所在文件：`stage/reconstruct_utils.py`
  - 作用：融合多源体素观测，生成 `recon_u / recon_v / recon_conf / recon_mask`

- `_should_trigger_reconstruction(...)`
  - 所在文件：`stage/stage4_pack.py`
  - 作用：判断当前帧是否需要做完整风场重构

- `_sanitize_observations(...)`
  - 所在文件：`stage/stage4_pack.py`
  - 作用：清洗体素观测，生成 `qc_weight`

- `build_flight_agents_sparse(...)`
  - 所在文件：`stage/agent_builder.py`
  - 作用：构建飞行智能体、通信边、风边和运动边

- `select_ff_edges(...)`
  - 所在文件：`stage/communication_builder.py`
  - 作用：选择飞行-飞行边，并给出权重

- `load_stage2_voxel(...)`
  - 所在文件：`stage/stage3_agents.py`
  - 作用：读取 Stage 2 的单帧 voxel 文件并恢复为可处理结构

- `_save_sparse_lossless_npz(...)`
  - 所在文件：`stage/pipeline_utils.py`
  - 作用：把最终样本打包为可落盘的 npz 文件

#### 3.0.4 常见辅助逻辑

- `np.nan_to_num(...)`
  - 用于把 NaN 转成 0，避免导出失败
- `pl.DataFrame(...)`
  - Polars 表结构，用于处理体素记录
- `pl.concat(...)`
  - 拼接 DataFrame，注意 schema 要一致
- `np.quantile(...)`
  - 分位数统计，用于判断重构置信度和质量
- `np.argmax / np.argsort`
  - 常用于排序和筛选候选

### 3.1 location / trajectory 类数据
用于表示飞机轨迹、位置点、速度、航向等。

### 3.1 location / trajectory 类数据
用于表示飞机轨迹、位置点、速度、航向等。

常见字段：

- `flight_id`
- `time_utc`
- `lat_clean`
- `lon_clean`
- `alt_meters`
- `heading`
- `ground_speed`
- `vertical_speed`

### 3.2 AMDAR 类数据
用于提供飞行器气象观测，常常携带风相关信息。

常见字段：

- `flight_id`
- `time_utc`
- `lat_clean`
- `lon_clean`
- `alt_meters`
- `u`
- `v`
- `wind_speed`
- `wind_dir`

### 3.3 turb 类数据
用于提供湍流或扰动信息。

### 3.4 雷达图像
用于定义每一帧的时间、空间范围和图像尺寸。

---

## 4. Stage 1：数据清洗与统一

### 4.1 Stage 1 的职责

Stage 1 负责读取原始数据并清洗成统一中间表，主要完成：

1. 读取 location、amdar、turb 三类原始数据；
2. 清洗字段名；
3. 统一时间格式；
4. 将北京时间转换为 UTC；
5. 解析经纬度、高度、速度、风向风速；
6. 输出清洗后的 parquet 文件；
7. 生成 radar 帧索引和时间窗口索引。

### 4.2 Stage 1 的主要输出

常见输出包括：

- `clean_wind.parquet`
- `clean_loc.parquet`
- `radar_index.json`
- `frame_window_index.json`

这些文件会被 Stage 2 继续使用。

### 4.3 Stage 1 的常见参数

- `WIND_DATASET_DATE`  
  数据集日期目录，例如 `20260224`

- `WIND_TIME_WINDOW_MINUTES`  
  雷达帧时间窗口大小，通常为 5 分钟

- `WIND_MIN_VALID_YEAR` / `WIND_MAX_VALID_YEAR`  
  用于过滤异常时间戳

- `WIND_OVERLAP_ONLY`  
  是否只保留与雷达窗口有交集的数据

### 4.4 Stage 1 常见问题

#### 问题 1：时间字段解析失败
原因通常是原始时间格式不一致。  
解决方式：在清洗阶段采用宽容解析策略。

#### 问题 2：字段缺失
原因通常是原始表结构不稳定。  
解决方式：加入空值保护和保守回退逻辑。

---

## 5. Stage 2：体素化与空间离散化

### 5.1 Stage 2 的职责

Stage 2 将连续空间观测投影到三维体素网格中，主要做：

1. 读取 Stage 1 的清洗结果；
2. 读取每一帧雷达图；
3. 在时间窗口内筛选对应观测；
4. 计算体素坐标 `x / y / z`；
5. 将风、轨迹、运动、AMDAR、湍流投影到 voxel；
6. 输出每帧 `.npz` 和 `stage2_summary.json`。

### 5.2 体素概念说明

`voxel` 是三维网格中的一个小立方体，相当于 3D 像素。

- `x`：经向离散
- `y`：纬向离散
- `z`：高度离散

`Z_DIM` 由高度范围和垂直分辨率决定。

### 5.3 Stage 2 的主要输出

每帧通常输出：

- `wind_records`
- `loc_records`
- `motion_records`
- `flight_motion_records`
- `flight_raw_records`
- `amdar_records`
- `turb_records`
- `radar_img`
- `radar_shape`
- `grid_shape`

summary 统计包括：

- `wind_voxels`
- `traj_voxels`
- `motion_voxels`
- `amdar_voxels`
- `turb_voxels`

### 5.4 Stage 2 的意义

Stage 2 的作用是把原始连续观测变成结构化的 3D 输入，为 Stage 3 的图构建和 Stage 4 的重构提供基础。

---

## 6. Stage 3：飞行智能体与三层边建图

### 6.1 Stage 3 的职责

Stage 3 读取 Stage 2 的体素结果，构建飞行智能体和通信关系。主要完成：

1. 从体素和轨迹中恢复 `flight agents`
2. 计算通信可达性
3. 计算空空关系
4. 计算风传播关系
5. 输出每帧 `agents JSON`
6. 输出 `stage3_summary.json`

### 6.2 Stage 3 的三层边定义

Stage 3 的图结构分为三层。

#### 第一层：结构通信边
表示节点之间可以交流。

对应字段：

- `ff_comm_allowed`
- `flight_comm_allowed`

含义：

- 两个飞行智能体在时间、空间、垂直方向上足够接近
- 因此可以交换信息

#### 第二层：运动相关边
表示通信关系在轨迹和运动上也合理。

对应字段：

- `ff_motion_allowed`
- `flight_ff_motion_edges`

含义：

- 不仅“能连”，而且“运动趋势上合理”
- 常用于表达局部传播、轨迹相似、速度趋势一致

#### 第三层：风传播边
表示这条边对风场传播有意义。

对应字段：

- `ff_wind_allowed`
- `flight_ff_wind_edges`

风边建议采用软权重，而不是纯 0/1。

建议触发条件至少满足以下之一：

1. 两端都观测到风相关证据
2. 一端有风证据，另一端在空间上足够接近
3. 一端是风源节点，另一端是风传播接收节点
4. 当前帧存在局部风突变或颠簸事件

建议风边权重：

- 强风边：`1.0`
- 弱风边：`0.5`
- 无风边：`0`

### 6.3 `valid_wind_capable_flights` 的含义

这是风能力节点数量。

更合理的定义是：

> 满足至少一种风传播条件的节点数量。

例如：

- 有 AMDAR 风信息
- 与风体素邻近
- 与风观测节点在通信图上连通
- 周围存在显著风梯度或扰动

这比“必须同时满足很严格条件”更符合物理直觉，也更有利于风边生成。

### 6.4 Stage 3 的意义

Stage 3 不只是“建图”，而是在为后续风传播与重构提供结构基础。

---

## 7. Stage 4：风场重构与训练样本打包

### 7.1 Stage 4 的职责

Stage 4 读取 Stage 2 和 Stage 3 的结果，进一步做风场重构并打包最终训练样本。主要做：

1. 读取 Stage 2 的体素结果
2. 读取 Stage 3 的智能体结果
3. 融合风观测、轨迹、智能体信息
4. 进行三维风场重构
5. 保存成最终训练用的 `frame_*.npz`
6. 输出 `stage4_summary.json`

### 7.2 Stage 4 的双层模式

建议将 Stage 4 固定为两层模式。

#### 模式 A：普通帧轻量模式
适用于风场变化不明显的帧。

特点：

- 只保留轻量特征
- 保留通信图和基础状态
- 不强制做完整三维重构
- 降低计算成本
- 保持样本量

#### 模式 B：触发帧完整重构模式
适用于风场变化明显的帧。

特点：

- 执行完整 `reconstruct_wind_field`
- 生成：
  - `recon_u_3d`
  - `recon_v_3d`
  - `recon_mask_3d`
  - `recon_confidence_3d`
- 提供更高质量训练输入

### 7.3 Stage 4 的触发逻辑建议

建议在以下情况触发完整重构：

- `wind_voxels` 突变
- `motion_voxels` 突变
- `flight_ff_wind_edges` 突变
- `flight_comm_allowed_agents` 突变
- `recon_seed_strength` 超过阈值

这样可以做到“变化时重构、平稳时轻量”。

### 7.4 Stage 4 的意义

Stage 4 是把前面的中间结果合成最终可训练数据包的阶段，供训练脚本直接使用。

---

## 8. 重构模块说明

### 8.1 `reconstruct_utils.py`

这是重构逻辑的独立模块，核心函数是：

- `_reconstruct_wind_field(...)`

职责是：

- 融合多源体素观测
- 构建初始风场
- 输出：
  - `recon_u`
  - `recon_v`
  - `recon_conf`
  - `recon_mask`

### 8.2 重构策略

当前重构遵循保守原则：

1. 先用高可信观测直接落点
2. 再做体素级融合
3. 最后做局部 IDW 补全
4. 控制补全范围，避免把整幅图“糊满”

### 8.3 关键重构参数

- `RECON_ENABLE_IDW`  
  是否启用局部 IDW 补全

- `RECON_IDW_MAX_FILL`  
  最多补多少个缺失体素

- `MAX_WIND_SPEED_MS`  
  风速过滤上限，过大视为异常

---

## 9. 导出阶段说明

### 9.1 `export_stage4_dataset.py`

该脚本用于把 `stage4_output/frame_*.npz` 转成更适合训练的数据集。

它通常会检查：

- `storage_mode`
- `grid_shape`
- `radar_2d`
- `trajectory_3d`
- `recon_u_3d`
- `recon_v_3d`
- `recon_mask_3d`
- `recon_confidence_3d`
- flight 图相关字段

### 9.2 导出失败常见原因

#### 1. `recon field contains NaN`
说明 `recon_u_3d` 或 `recon_v_3d` 中存在 NaN。  
解决方式：保存前使用 `np.nan_to_num(..., nan=0.0)`。

#### 2. `recon_mask sum is zero`
说明完全没有有效重构。  
解决方式：放宽触发条件、放宽风能力节点定义、提升 Stage 3 风边激活。

#### 3. 字段缺失
说明 Stage 4 没把兼容字段写进去。  
解决方式：检查 `stage4_pack.py` 输出字段。

---

## 10. 契约检查说明

`validate_pipeline_contracts.py` 用于检查 Stage 2 / 3 / 4 是否对齐，以及关键字段是否存在。

典型检查项：

- Stage 2 summary 是否存在
- Stage 3 summary 是否存在
- Stage 4 summary 是否存在
- `wind_reconstruction` 是否可导入
- Stage 4 summary 字段是否齐全

如果你只跑了小批量帧，它可能会提示 `stage3 missing frames`，这不一定是错误，只是因为它默认按全量对齐检查。

---

## 11. 推荐运行顺序

1. 初始数据导出 / 清洗
2. Stage 1
3. 检查 Stage 1 输出
4. Stage 2
5. 检查 Stage 2 输出
6. Stage 3
7. 检查 Stage 3 风边
8. Stage 4
9. 检查 Stage 4 重构质量
10. 导出训练数据集
11. 最终检查导出结果

---

## 12. 运行前环境检查

在正式运行前，建议先确认以下内容：

### 12.1 Python / Conda 环境

```bash
source ~/.bashrc
eval "$(conda shell.bash hook)"
conda activate windy310
```

### 12.2 目录是否存在

- `stage1` 输入目录
- `stage2_output`
- `stage3_output`
- `stage4_output`
- `stage/logs`

### 12.3 代码文件是否存在

- `stage1_prepare.py`
- `stage2_voxelize.py`
- `stage3_agents.py`
- `stage4_pack.py`
- `export_stage4_dataset.py`

### 12.4 关键配置是否正确

建议先确认：

- `WIND_DATASET_DATE`
- `WIND_TIME_WINDOW_MINUTES`
- `WIND_MAX_FRAMES`
- `MAX_WIND_SPEED_MS`
- `COMM_TIME_LIMIT_SECONDS`
- `COMM_SPACE_LIMIT_KM`
- `COMM_VERTICAL_LIMIT_M`
- `RECON_ENABLE_IDW`
- `RECON_IDW_MAX_FILL`

---

## 13. 小批量测试命令

### Stage 3 小批量
```bash
WIND_MAX_FRAMES=3 python /data/LFT-W02_data/pengxu/stage/stage3_agents.py > /data/LFT-W02_data/pengxu/stage/logs/stage3_3frames_new.log 2>&1
```

### Stage 4 小批量
```bash
WIND_MAX_FRAMES=3 python /data/LFT-W02_data/pengxu/stage/stage4_pack.py > /data/LFT-W02_data/pengxu/stage/logs/stage4_3frames_new.log 2>&1
```

### 导出 Stage 4 数据集
```bash
python /data/LFT-W02_data/pengxu/stage/export_stage4_dataset.py --src /data/LFT-W02_data/pengxu/stage4_output --dst /data/LFT-W02_data/pengxu/dataset_output_stage4_clean --progress_every 1 > /data/LFT-W02_data/pengxu/stage/logs/export_stage4.log 2>&1
```

---

## 14. 检查命令

### 14.1 检查 Stage 3
```bash
python - <<'PY'
import json
from pathlib import Path
p = Path('/data/LFT-W02_data/pengxu/stage3_output/stage3_summary.json')
data = json.loads(p.read_text())
print('frames =', len(data))
for item in data:
    print(
        item['time_str'],
        'valid_wind_capable=', item.get('valid_wind_capable_flights'),
        'wind_edges=', item.get('flight_ff_wind_edges'),
        'comm_agents=', item.get('flight_comm_allowed_agents'),
        'ff_edges=', item.get('flight_ff_allowed_edges'),
    )
PY
```

#### 14.1.1 检查 Stage 3 summary 中关键字段是否存在

```bash
python - <<'PY'
import json
from pathlib import Path
p = Path('/data/LFT-W02_data/pengxu/stage3_output/stage3_summary.json')
data = json.loads(p.read_text())
keys = [
    'time_str', 'valid_wind_capable_flights', 'flight_ff_wind_edges',
    'flight_comm_allowed_agents', 'flight_ff_allowed_edges'
]
for k in keys:
    print(k, '=>', all(k in x for x in data))
PY
```

### 14.2 检查 Stage 4
```bash
python - <<'PY'
import json
from pathlib import Path
p = Path('/data/LFT-W02_data/pengxu/stage4_output/stage4_summary.json')
data = json.loads(p.read_text())
print('frames =', len(data))
for item in data:
    print(
        item['time_str'],
        'triggered=', item.get('recon_triggered'),
        'seed=', item.get('recon_seed_strength'),
        'recon_mean=', item.get('recon_conf_mean'),
        'coverage=', item.get('recon_coverage_ratio'),
    )
PY
```

#### 14.2.1 检查 Stage 4 npz 字段

```bash
python - <<'PY'
import numpy as np
from pathlib import Path
p = Path('/data/LFT-W02_data/pengxu/stage4_output')
for fp in sorted(p.glob('frame_*.npz'))[:3]:
    with np.load(fp, allow_pickle=True) as npz:
        print('\n', fp.name)
        print('keys:', sorted(npz.files))
        print('has_recon_u_3d:', 'recon_u_3d' in npz.files)
        print('has_recon_v_3d:', 'recon_v_3d' in npz.files)
        print('has_recon_mask_3d:', 'recon_mask_3d' in npz.files)
        print('has_recon_confidence_3d:', 'recon_confidence_3d' in npz.files)
PY
```

### 14.3 检查导出结果
```bash
tail -n 120 /data/LFT-W02_data/pengxu/stage/logs/export_stage4.log
```

#### 14.3.1 检查导出报告

```bash
python - <<'PY'
import json
from pathlib import Path
p = Path('/data/LFT-W02_data/pengxu/dataset_output_stage4_clean/stage4_clean_report.json')
if p.exists():
    data = json.loads(p.read_text())
    print('total =', data.get('total'))
    print('kept =', data.get('kept'))
    print('bad =', data.get('bad'))
    print('filtered_ratio =', data.get('filtered_ratio'))
    print('bad_samples =', data.get('bad_samples', [])[:3])
else:
    print('stage4_clean_report.json not found')
PY
```

---

## 15. 常见问题

### 风边全 0
说明风能力节点定义太严，或风边规则太苛刻。

### 重构质量低
说明风观测太稀疏，或者触发不够好。

### 导出失败
多半是 NaN、mask 全 0 或字段缺失。

### 契约检查报缺帧
如果你只跑了小批量，这是正常现象。

---

## 16. 关键术语表

- `voxel`
- `agent`
- `communication graph`
- `wind edge`
- `motion edge`
- `recon_mask`
- `recon_confidence`
- `recon_seed_strength`
- `triggered reconstruction`
- `event-triggered`
- `IDW`
- `nan_to_num`
- `physics-informed`
- `sparse fusion`

---

## 17. 经验总结

1. Stage 3 的风边不能依赖太严格条件，否则容易全 0。  
2. 风能力节点应该软判定，而不是只有硬门槛。  
3. Stage 4 不适合每帧都强重构，应该采用事件触发。  
4. 导出阶段最怕 NaN，所以重构字段必须清洗。  
5. 小批量测试非常重要，建议每次只先跑 3 帧确认链路。  

---

## 18. 新成员操作建议

如果你刚接手这个项目，建议按下面顺序来：

1. 先看本 README
2. 先理解 Stage 1–4 各自职责
3. 先跑小批量，不要直接全量
4. 先看 Stage 3 是否有风边
5. 再看 Stage 4 是否触发重构
6. 最后做导出检查
7. 全量前先保证小批量稳定
