# Stage3-Stage5 项目总览

## 这份文档的作用
这是一份给“新窗口/新对话”快速接手项目的总览页。  
只要先读这一页，再按文末推荐顺序读另外 3 份文档，就能快速理解当前项目的目标、状态和下一步方向。

---

## 当前项目目标
一句话定义：

**面向空地一体协同感知的稀疏多源风场重建与后续事件驱动实时风场预测。**

当前已经完成的重点是：

- 把稀疏、多源、时序不连续的风观测整理成统一的 `Stage4` 风场状态层
- 让这套状态层既可运行、可解释，又适合作为后续 `Stage5` 预测的输入

---

## 当前阶段状态

### Stage1-Stage2
负责：

- 原始观测数据整理
- 体素化
- 输出 `stage2_summary.json` 和逐帧 `voxel npz`

当前状态：

- 已存在并作为 `Stage3` / `Stage4` 的上游输入

### Stage3
负责：

- flight agents 构建
- communication graph / edge 选择
- 产出逐帧 `agents JSON`

当前真实使用代码：

- `stage3_agents_v2.py`

当前状态：

- 可以分片并行
- 支持多核 CPU 和多进程 shard
- 正式输出目录是 `stage3_output_v2`

### Stage4
负责：

- 多源风场重建
- support / temporal / relax / prune / expand / anchor protect
- 训练样本打包
- fast 与 full-aux 双路径输出

当前真实使用代码：

- `stage4_pack_v2.py`

当前状态：

- 作为风场状态构建层，已经接近冻结
- 默认：
  - `Stage3` 并行
  - `Stage4` 单进程单卡
  - 默认不跑重报告，只保留 `readiness`
- 已具备显式模块开关，可直接做消融

### Stage5
尚未开始正式实现。

目标不是“每帧都全场预测”，而是：

- 面向飞机辅助飞行
- 事件驱动
- ROI 聚焦
- 短时前瞻

更准确的目标表达是：

**基于 `Stage4` 状态层的事件驱动实时风场预测与风险辅助决策。**

补充说明：

- Stage5 已具备把历史 GFS archive 对齐到 keyframes 的工程链路。
- Stage5 已新增 MERRA-2 背景场 manifest / 转换脚本，可作为第三个外部背景候选源。
- Stage5 已支持多背景候选选择，以及把上一帧 Stage5 输出作为内部时序背景候选。
- Stage5 已新增 v3 structured 背景约束与 full-ROI raw/scaled 双口径 demo，用于区分“幅值失配帧”和“结构冲突帧”。
- 背景场是先验和对比基线，不是重构真值。
- 图像看起来差异大并不意外，必须结合 `background_vector_rmse`、`background_speed_bias`、`heldout_anchor_rmse_after` 一起判断。

---

## 当前关键结论

### 1. Stage3 可以并行分片
原因：

- 更接近 frame-level 独立任务
- 主要是 CPU / IO / Polars / 稀疏图构建
- 不依赖 `prev_recon_state`

因此：

- 可以多进程 shard
- 可以提高到 6 路、8 路，甚至更多，受 CPU 与 IO 约束

### 2. Stage4 必须默认单进程单卡
原因：

- 存在明确时序依赖：
  - `temporal_background`
  - `forecast_next_wind_field`
  - `trigger_reconstruction`
- 如果做多进程分片，会切断 `prev_recon_state`

因此：

- `Stage4` 默认必须单进程
- 可以单进程 + 多线程 CPU
- 可以单卡 GPU
- 不建议默认多进程分片

### 3. Stage4 已接近冻结
冻结的含义不是“不再改任何代码”，而是：

- 不再无限追更高 `coverage`
- 不再继续引入更复杂的 heuristic
- 以稳定、可复现、可消融为优先

当前冻结标准：

- anchor fidelity 稳
- coverage 温和提升即可
- confidence 有层次
- 运行链路稳定
- 模块可开关，可做消融

### 4. 后续重点不应继续大改 Stage4
而应转向：

- 全量运行
- `Stage4` 消融实验
- 论文组织
- `Stage5` 事件驱动预测设计

---

## 新对话最重要的上下文

如果新窗口只需要记住 6 件事，就记住下面这些：

1. 当前主控脚本是：
   - `run_stage34_workflow_v2.sh`

2. 当前真实使用的代码是：
   - `stage3_agents_v2.py`
   - `stage4_pack_v2.py`

3. `Stage3` 正式输出目录是：
   - `stage3_output_v2`

4. `Stage4` 正式输出目录是：
   - `stage4_output_v2`

5. `Stage4` 训练前 full aux 导出目录是：
   - `stage4_output_full_aux_v2/<RUN_LABEL>`

6. `Stage4` 已支持显式模块开关，可直接做消融：
   - `WIND_STAGE4_ENABLE_SUPPORT_FILL`
   - `WIND_STAGE4_ENABLE_TEMPORAL_FILL`
   - `WIND_STAGE4_ENABLE_RELAX`
   - `WIND_STAGE4_ENABLE_PRUNE`
   - `WIND_STAGE4_ENABLE_EXPAND`
   - `WIND_STAGE4_ENABLE_DIRECT_ANCHOR_RESTORE`
   - `WIND_STAGE4_ENABLE_DIRECT_ANCHOR_FORCE`

如果后续接手的人已经知道“现在要做什么”，推荐直接再看：

- `15_requirement_command_guide.md`

它是按需求场景整理的命令入口页，用来快速定位 Stage1-Stage5、可视化、历史 GFS、监控和结果核对命令。

---

## 推荐阅读顺序

1. 先看：
   - `01_stage34_pipeline.md`
   - 解决目录、输入输出、调用关系问题

2. 再看：
   - `02_stage4_modification_and_freeze.md`
   - 解决为什么 `Stage4` 现在要冻结的问题

3. 最后看：
   - `03_stage4_paper_experiment_matrix.md`
   - 进入论文实验与消融设计

---

## 新窗口接手时的提醒

- 不要把 `stage3_output` 和 `stage3_output_v2` 混为一谈。
- 不要把日志目录和正式数据输出目录混为一谈。
- 不要再默认尝试把 `Stage4` 改成多进程分片。
- 不要继续只为追高 `coverage` 而大放宽 `Stage4`。
- `Stage5` 应单独设计，不应继续塞进 `Stage4`。
