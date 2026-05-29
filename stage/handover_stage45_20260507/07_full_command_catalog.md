# Stage3 / Stage4 完整运行命令总表

## 这份文档的作用
这份文档集中整理当前 `Stage3/Stage4` 所有常用命令，包括：

- 主运行命令
- full fast / full aux
- `stage3_only / stage4_only`
- 代表性消融版本
- 论文实验版本

目的是避免命令散落在不同日志和 md 中。

---

## 一、基础约定

所有命令默认：

```bash
BASE_DIR=/data/LFT-W02_data/pengxu
STAGE_DIR=$BASE_DIR/stage
```

如果是 `stage4_only`，推荐显式指定：

```bash
STAGE3_INPUT_DIR_FOR_STAGE4=$BASE_DIR/stage3_output_v2
```

避免误读旧的 `stage3_output`。

补充：

- 当前默认 `Stage3` 按 **8 路 shard** 运行
- 如果命令里不显式写 `STAGE3_PARALLEL_SHARDS`，默认也是 8
- 为了实验可复现，建议命令里仍显式写出：

```bash
STAGE3_PARALLEL_SHARDS=8
STAGE3_CPU_THREADS_PER_WORKER=1
```

---

## 二、主运行命令

## 1. `S5 FinalFast` 全量主版本

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

用途：
- 当前 `Stage4` 冻结前主结果版本
- `Stage3` 默认 8 路并行分片，`Stage4` 单卡 + 6 核 CPU

## 2. `S6 FullAux` 全量训练导出版本

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

用途：
- 基于 fast 输出补 richer aux fields

---

## 三、单阶段命令

## 1. 只跑 Stage3

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

## 2. 只跑 Stage4

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

用途：
- 不重跑 `Stage3`
- 直接吃 `stage3_output_v2`

---

## 四、论文实验命令

## `S0 DirectOnly`

```bash
BASE_DIR=/data/LFT-W02_data/pengxu
STAGE_DIR=$BASE_DIR/stage

RUN_MODE=full \
RUN_LABEL_OVERRIDE=S0_direct_only \
RUN_PHASE=full_fast_multi_gpu \
RUN_VALIDATE=1 \
PROGRESS_EVERY=50 \
STAGE3_PARALLEL_SHARDS=8 \
STAGE3_CPU_THREADS_PER_WORKER=1 \
STAGE4_CPU_THREADS=6 \
MULTI_GPU_STAGE4_SHARD=0 \
WIND_STAGE4_USE_GPU=1 \
WIND_STAGE4_GPU_DEVICE=cuda:0 \
WIND_STAGE4_ENABLE_SUPPORT_FILL=0 \
WIND_STAGE4_ENABLE_TEMPORAL_FILL=0 \
WIND_STAGE4_ENABLE_RELAX=0 \
WIND_STAGE4_ENABLE_PRUNE=0 \
WIND_STAGE4_ENABLE_EXPAND=0 \
WIND_STAGE4_ENABLE_DIRECT_ANCHOR_RESTORE=0 \
WIND_STAGE4_ENABLE_DIRECT_ANCHOR_FORCE=0 \
bash $STAGE_DIR/run_stage34_workflow_v2.sh
```

## `S1 BaseRecon`

```bash
BASE_DIR=/data/LFT-W02_data/pengxu
STAGE_DIR=$BASE_DIR/stage

RUN_MODE=full \
RUN_LABEL_OVERRIDE=S1_base_recon \
RUN_PHASE=full_fast_multi_gpu \
RUN_VALIDATE=1 \
PROGRESS_EVERY=50 \
STAGE3_PARALLEL_SHARDS=8 \
STAGE3_CPU_THREADS_PER_WORKER=1 \
STAGE4_CPU_THREADS=6 \
MULTI_GPU_STAGE4_SHARD=0 \
WIND_STAGE4_USE_GPU=1 \
WIND_STAGE4_GPU_DEVICE=cuda:0 \
WIND_STAGE4_ENABLE_SUPPORT_FILL=0 \
WIND_STAGE4_ENABLE_TEMPORAL_FILL=0 \
WIND_STAGE4_ENABLE_RELAX=0 \
WIND_STAGE4_ENABLE_PRUNE=0 \
WIND_STAGE4_ENABLE_EXPAND=0 \
WIND_STAGE4_ENABLE_DIRECT_ANCHOR_RESTORE=0 \
WIND_STAGE4_ENABLE_DIRECT_ANCHOR_FORCE=0 \
bash $STAGE_DIR/run_stage34_workflow_v2.sh
```

## `S2 SupportTemporal`

```bash
BASE_DIR=/data/LFT-W02_data/pengxu
STAGE_DIR=$BASE_DIR/stage

RUN_MODE=full \
RUN_LABEL_OVERRIDE=S2_support_temporal \
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
WIND_STAGE4_ENABLE_RELAX=0 \
WIND_STAGE4_ENABLE_PRUNE=0 \
WIND_STAGE4_ENABLE_EXPAND=0 \
WIND_STAGE4_ENABLE_DIRECT_ANCHOR_RESTORE=0 \
WIND_STAGE4_ENABLE_DIRECT_ANCHOR_FORCE=0 \
bash $STAGE_DIR/run_stage34_workflow_v2.sh
```

## `S3 PhysicsSmooth`

```bash
BASE_DIR=/data/LFT-W02_data/pengxu
STAGE_DIR=$BASE_DIR/stage

RUN_MODE=full \
RUN_LABEL_OVERRIDE=S3_physics_smooth \
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
WIND_STAGE4_ENABLE_PRUNE=0 \
WIND_STAGE4_ENABLE_EXPAND=0 \
WIND_STAGE4_ENABLE_DIRECT_ANCHOR_RESTORE=0 \
WIND_STAGE4_ENABLE_DIRECT_ANCHOR_FORCE=0 \
bash $STAGE_DIR/run_stage34_workflow_v2.sh
```

## `S4 ConfPruneAnchor`

```bash
BASE_DIR=/data/LFT-W02_data/pengxu
STAGE_DIR=$BASE_DIR/stage

RUN_MODE=full \
RUN_LABEL_OVERRIDE=S4_conf_prune_anchor \
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
WIND_STAGE4_ENABLE_EXPAND=0 \
WIND_STAGE4_ENABLE_DIRECT_ANCHOR_RESTORE=1 \
WIND_STAGE4_ENABLE_DIRECT_ANCHOR_FORCE=1 \
bash $STAGE_DIR/run_stage34_workflow_v2.sh
```

## `S5 FinalFast`
见上文主运行命令。

## `S6 FullAux`
见上文主运行命令。

---

## 五、对比实验命令

## 1. `fast` vs `full_aux_export`
就是：

- `S5 FinalFast`
- `S6 FullAux`

## 2. `stage4_only` 对比单独重跑
适合你在修复 `Stage4` bug 后，不重跑 `Stage3`：

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

---

## 六、运行策略建议

### 1. 不要一开始就把 `S0-S6` 全部做全量
成本太高。

### 1.1 关于 Stage3 的统一表述

本文件中所有涉及 `Stage3` 的推荐命令，默认统一理解为：

- `Stage3` 使用 `stage3_agents_v2.py`
- `Stage3` 使用 **8 路 shard**
- 推荐线程配置：
  - `STAGE3_PARALLEL_SHARDS=8`
  - `STAGE3_CPU_THREADS_PER_WORKER=1`

如果后续你要临时改成 6 路或别的值，应在命令里显式覆盖，而不要依赖默认值。

### 2. 推荐顺序

1. 全量先跑 `S5 FinalFast`
2. 再跑 `S6 FullAux`
3. `S0-S4` 先在固定子集上跑
4. 结果稳定后再决定哪些版本值得做全量

### 3. 默认不和外部论文做数值硬对比
因为数据不同。

论文里应该强调：

- 问题结构差异
- 方法迁移逻辑
- 自己数据上的内部 baseline / ablation

---

## 八、每个实验的详细介绍

这部分不是“再贴一遍命令”，而是解释：

- 这个实验为什么要跑
- 适合什么时候跑
- 跑完重点看什么
- 希望得出什么结论

## 1. `S5 FinalFast` 全量主版本

### 目的
- 作为当前 `Stage4` 冻结前的正式主版本
- 给后续论文主结果、全量样本和 `Stage5` 输入层提供统一基线

### 适用场景
- 全量正式运行
- 生成主结果 `stage4_output_v2`
- 后续 `full_aux_export` 的源结果

### 核心特点
- `Stage3` 默认 8 路并行分片
- `Stage4` 单进程单卡 + 多线程 CPU
- 默认只保留 `readiness`
- 开启：
  - support fill
  - temporal fill
  - relax
  - prune
  - expand
  - direct anchor restore / force

### 跑完重点看什么
- `recon_conf_mean_avg`
- `recon_coverage_avg`
- `fullfield_confidence_spread_p10_p90`
- `outlier_count`
- `wind_primary` 是否长期为 0
- `support_fill / temporal_fill / support_expand`
- 总 `elapsed`

### 希望得到的结论
- 这是当前最适合冻结的运行主版本
- anchor fidelity 稳
- coverage 温和提升
- confidence 有层次
- 全量运行链路稳定

## 2. `S6 FullAux` 全量训练导出版本

### 目的
- 在不改 `recon_*` 的前提下，补 richer aux fields
- 为后续训练、PINN / diffusion / Stage5 提供完整输入条件

### 适用场景
- `S5 FinalFast` 全量跑完之后
- 训练前样本导出

### 核心特点
- 从 fast `npz` 读取源结果
- 不重跑主重构链
- 输出到独立 `stage4_output_full_aux_v2/<RUN_LABEL>`

### 跑完重点看什么
- `recon_*` 是否保持不变
- `pinn_divergence_3d`
- `pinn_smoothness_3d`
- `physics_weight_3d`
- `diffusion_condition_4d`
- `hazard_*`
- `where2comm_targets`
- 总 `elapsed`

### 希望得到的结论
- `S6` 适合训练，不适合运行主链
- 它是 `Stage4` 的训练增强分支，不是更优运行版本

## 3. `stage3_only`

### 目的
- 只验证 `Stage3` 是否正常
- 单独看 flight agent / communication graph 构建

### 适用场景
- `Stage3` 逻辑调试
- 想确认 shard / merge 前单独运行没问题

### 并行说明
- 默认按 8 路 shard
- 若命令中显式写 `STAGE3_PARALLEL_SHARDS`，则以命令为准

### 跑完重点看什么
- `valid_wind_capable_flights`
- `flight_ff_wind_edges`
- `flight_comm_allowed_agents`
- `stage3_output_v2/agents/*.json` 数量

### 希望得到的结论
- `Stage3` 可以稳定生成 agent JSON
- 通信图构建逻辑正常

## 4. `stage4_only`

### 目的
- 不重跑 `Stage3`
- 直接基于已有 `stage3_output_v2` 重跑 `Stage4`
- 常用于修 bug、调 `Stage4`、重新生成结果

### 适用场景
- 你刚修了 `stage4_pack_v2.py`
- `Stage3` 早就跑完了

### 关键前提
- 一定显式指定：
  - `STAGE3_INPUT_DIR_FOR_STAGE4=$BASE_DIR/stage3_output_v2`

### 跑完重点看什么
- `[Stage-4][progress]`
- `[Stage-4][frame]`
- `frame_*.npz` 是否持续增长
- 是否还报：
  - `NoneType`
  - `Missing Stage-3 summary`
  - `FileNotFoundError`

### 希望得到的结论
- `Stage4` 修复后可单独稳定重跑
- 不需要每次都重跑 `Stage3`

## 5. `S0 DirectOnly`

### 目的
- 提供最低基线
- 验证只靠直接观测的效果到底有多差

### 适用场景
- 论文内部 baseline

### 跑完重点看什么
- sparse anchor fidelity 通常仍不差
- 但 coverage 应明显偏低
- 全场结构信息明显不足

### 希望得到的结论
- 单靠直接观测不足以支撑完整状态构建

## 6. `S1 BaseRecon`

### 目的
- 验证基础 `_reconstruct_wind_field()` 能做到什么程度

### 适用场景
- 论文里的“基础重构层”对照

### 跑完重点看什么
- 比 `S0` 是否提升 coverage
- conf 是否仍偏低
- 没有后处理时结构是否不稳定

### 希望得到的结论
- 基础重构有用，但不足以成为最终运行版本

## 7. `S2 SupportTemporal`

### 目的
- 单独评估 support fill + temporal fill 的贡献

### 适用场景
- 论文消融 4.2

### 跑完重点看什么
- `support_fill_voxels`
- `temporal_fill_voxels`
- coverage 是否明显上升
- 时序稳定性是否改善

### 希望得到的结论
- 稀疏补全与时序背景是 Stage4 的重要增益来源

## 8. `S3 PhysicsSmooth`

### 目的
- 评估 `relax` 的作用

### 适用场景
- 论文消融 4.2 / 4.3 之间的过渡版本

### 跑完重点看什么
- conf 层次是否更平滑
- 局地结构是否更稳定
- 是否没有引入明显 outlier

### 希望得到的结论
- 轻量物理一致性松弛有利于稳定状态层

## 9. `S4 ConfPruneAnchor`

### 目的
- 单独评估：
  - prune
  - anchor restore / force

### 适用场景
- 论文消融 4.3

### 跑完重点看什么
- `anchor_restore_voxels`
- `anchor_force_voxels`
- `recon_pruned_voxels`
- outlier 是否更少
- direct anchor fidelity 是否更稳

### 希望得到的结论
- confidence shaping + anchor protect 是最终可运行版本的关键稳定层

## 10. `fast` vs `full_aux_export`

### 目的
- 证明：
  - `fast` 适合运行主链
  - `full_aux_export` 适合训练导出

### 适用场景
- 论文对比章节
- 方法职责划分说明

### 跑完重点看什么
- `recon_*` 是否不变
- aux fields 是否更完整
- elapsed 是否合理

### 希望得到的结论
- 两条 profile 分工明确，而不是谁绝对更好
## 补充：Stage4 CPU 线程统一说明

当前所有涉及 `Stage4` 的推荐命令，统一按以下原则理解：

- `Stage4` 是单进程单卡
- 通过：
  - `OMP_NUM_THREADS`
  - `MKL_NUM_THREADS`
  - `NUMEXPR_NUM_THREADS`
  - `POLARS_MAX_THREADS`
  统一吃多核 CPU
- 当前推荐线程起点：
  - `STAGE4_CPU_THREADS=6`

原因：

- 多核 CPU 对 `Stage4` 通常会更快
- 但 `Stage4` 是单进程时序链，不适合盲目把线程拉到所有逻辑核
- `6` 是当前较稳的起点

---

## 补充：Stage5 / GFS-GDAS 实时背景场命令

这一节只服务 Stage5 独立工具链，不修改冻结的 Stage4 主链。

### 1. 下载并转换实时 GFS ROI 背景场

```bash
/opt/miniconda3/bin/python stage/download_stage5_gfs_gdas_roi.py \
  --dataset gfs \
  --mode latest \
  --forecast-hour 0 \
  --download \
  --convert-existing
```

默认输出：

```text
GRIB: /data/LFT-W02_data/pengxu/stage5_external_background/gfs_gdas_roi
NPZ : /data/LFT-W02_data/pengxu/stage5_external_background/gfs_gdas_roi_npz
```

说明：

- GFS 是实时 / 准实时背景预报场，不是重构真值。
- 脚本会自动尝试前几个 6 小时 cycle，降低最新 cycle 未发布时失败的概率。
- NOMADS pressure levels 与 ERA5 不完全一致，脚本已使用 NOMADS 支持层次。

### 2. 下载并转换 GDAS 对照背景场

```bash
/opt/miniconda3/bin/python stage/download_stage5_gfs_gdas_roi.py \
  --dataset gdas \
  --mode latest \
  --forecast-hour 0 \
  --download \
  --convert-existing
```

用途：

- 作为分析场 / 短延迟对照背景。
- 与 GFS 一样，只作为 Stage5 大尺度先验和对比基准。

### 3. 只生成 GFS manifest，不下载

```bash
/opt/miniconda3/bin/python stage/download_stage5_gfs_gdas_roi.py \
  --dataset gfs \
  --mode latest \
  --forecast-hour 0
```

用途：

- 检查 NOMADS URL、ROI、变量和 pressure levels。
- 网络不稳定或只想核对参数时使用。

### 4. GFS/GDAS 背景场 3D 可视化

```bash
/opt/miniconda3/bin/python stage/report_stage5_background_field.py \
  --background-dir /data/LFT-W02_data/pengxu/stage5_external_background/gfs_gdas_roi_npz \
  --out-dir /data/LFT-W02_data/pengxu/stage5_visualizations/gfs_gdas_background \
  --lon-range 106.5,117.5 \
  --lat-range 17,37 \
  --alt-range 0,12 \
  --xy-stride 3 \
  --z-stride 2 \
  --max-vectors 900
```

当前已生成：

```text
/data/LFT-W02_data/pengxu/stage5_visualizations/gfs_gdas_background/gfs_roi_20260519120000_background_3d.png
```

解释：

- 这张图是 GFS/GDAS pressure-level 背景场，不是 Stage4/Stage5 重构结果。
- 点是背景格点，颜色是背景风速，黑色箭头是背景水平风 `u/v`。
- 它适合说明“外部实时背景场已接入”，不适合作为“重构效果图”。

### 5. rolling ROI dry-run：用 frame times

```bash
/opt/miniconda3/bin/python stage/run_stage5_rolling_roi.py \
  --frame-times 20260124013600,20260222063600 \
  --run-stage5 \
  --dry-run
```

用途：

- 从 `stage2_summary.json` 自动解析 source indices。
- 推荐优先用这个命令，避免手动查 index。

### 6. rolling ROI dry-run：用真实 frame indices

```bash
/opt/miniconda3/bin/python stage/run_stage5_rolling_roi.py \
  --frame-indices 76,7041 \
  --run-stage5 \
  --dry-run
```

注意：

- 不要输入 `<new_frame_indices>`。
- 尖括号会被 bash 当成重定向，导致 `No such file or directory`。

### 7. rolling ROI 正式运行，使用 GFS/GDAS 背景场

```bash
/opt/miniconda3/bin/python stage/run_stage5_rolling_roi.py \
  --frame-times 20260124013600,20260222063600 \
  --run-stage5 \
  --background-dir /data/LFT-W02_data/pengxu/stage5_external_background/gfs_gdas_roi_npz
```

用途：

- 小批量模拟在线事件 ROI。
- Stage4 仍然保持单进程顺序，不做多进程分片。
- Stage5 使用 GFS/GDAS 背景场作为先验。

### 8. rolling ROI 正式运行，无背景场

```bash
/opt/miniconda3/bin/python stage/run_stage5_rolling_roi.py \
  --frame-times 20260124013600,20260222063600 \
  --run-stage5 \
  --no-background
```

用途：

- 与背景场版本做对照。
- 结果只能说明无背景 `PINN-proxy + diffusion-style` refinement 行为。

### 9. Stage4 / Stage5 / 背景场并排图

```bash
/opt/miniconda3/bin/python stage/report_stage5_background_comparison.py \
  --stage4-dir /data/LFT-W02_data/pengxu/stage4_output_v2 \
  --stage5-dir /data/LFT-W02_data/pengxu/stage5_output_v1_keyframes \
  --background-dir /data/LFT-W02_data/pengxu/stage5_external_background/gfs_gdas_roi_npz \
  --frame-times 20260124013600,20260222063600
```

用途：

- 后续在时间匹配的背景场准备好后，生成 Stage4 sparse reconstruction、Stage5 ROI refinement、GFS/GDAS background 的对比图。
- 如果背景场时间不匹配，不应把它当作严格验证图。
