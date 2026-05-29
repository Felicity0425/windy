# 新窗口交接话术

## 用途

这份文档不是旧式的“提示词堆叠集合”，而是新窗口进入项目后的第一入口。  
目标是让新的助手在几乎没有历史上下文的情况下，先判断：

1. 当前项目主线是什么
2. 现在应先读哪份文档
3. 如果任务已明确，应先去哪里找命令

推荐配合当前真实交接包目录一起使用：

- `stage/handover_stage45_20260507/`

---

## 当前状态与下一步工作重点

当前主线仍然是：

- `Stage4` 冻结、结果整理、全量运行、内部 baseline / ablation

当前不应混写的边界是：

- `Stage4` 是当前主结果链路，已经接近冻结，不再无限追 `coverage`
- `Stage5` 是后续创新层，负责事件驱动、ROI refinement、短时实时预测
- `historical GFS comparison`
- `实时 GFS / GDAS 背景图`
- `Stage4 / Stage5` 重构结果

上面三类图和结果不能混用，也不能互相当真值。

如果任务目标已经明确，优先从：

- `stage/handover_stage45_20260507/15_requirement_command_guide.md`

按需求场景找命令，再回具体阶段文档看细节。  
如果任务还不明确，先读：

- `stage/handover_stage45_20260507/00_overview.md`
- `stage/handover_stage45_20260507/14_project_knowledge_base_summary.md`

---

## 最短可复制版

```text
这是当前项目的新窗口入口。请先判断你现在的任务类型，再决定先读哪份文档：

1. 如果是命令型任务，例如我要跑 Stage4、做可视化、跑 Stage5、看监控日志：
   先读 `stage/handover_stage45_20260507/15_requirement_command_guide.md`

2. 如果是项目理解型任务，例如我要先理解当前主线、阶段关系、输入输出目录：
   先读 `stage/handover_stage45_20260507/00_overview.md`
   再读 `stage/handover_stage45_20260507/14_project_knowledge_base_summary.md`

3. 如果是论文 / 方法型任务，例如我要梳理实验矩阵、论文定位、Stage5 后续方向：
   再读 `stage/handover_stage45_20260507/03_stage4_paper_experiment_matrix.md`
   和 `stage/handover_stage45_20260507/13_stage5_and_real_3d_wind_plan.md`

当前真实运行使用：
- `stage/run_stage34_workflow_v2.sh`
- `stage/stage3_agents_v2.py`
- `stage/stage4_pack_v2.py`

当前重点：
- `Stage4` 已接近冻结，当前主线是全量运行、结果整理、内部 baseline / ablation
- `Stage5` 是后续事件驱动 / ROI refinement / 短时预测方向，不要和 Stage4 主结果混写
- 如果需求已明确，优先从 `15_requirement_command_guide.md` 找命令

请先复述你理解的：
1. `Stage3 / Stage4` 的目录关系
2. `Stage4` 当前冻结原则
3. 命令入口关系：什么时候先看 `15`，什么时候再看 `07`
4. `historical GFS comparison` 和实时 `GFS / GDAS` 背景图有什么区别

确认这些后，再继续执行后续任务。
```

---

## 完整工程版

```text
这是一个面向空地一体协同感知的稀疏多源风场重建项目。请先按下面顺序阅读文档，不要一开始就在多个 md 之间来回翻：

第一层入口页：
- `stage/handover_stage45_20260507/00_overview.md`
- `stage/handover_stage45_20260507/14_project_knowledge_base_summary.md`
- `stage/handover_stage45_20260507/15_requirement_command_guide.md`

第二层专题页：
- `stage/handover_stage45_20260507/01_stage34_pipeline.md`
- `stage/handover_stage45_20260507/02_stage4_modification_and_freeze.md`
- `stage/handover_stage45_20260507/03_stage4_paper_experiment_matrix.md`
- `stage/handover_stage45_20260507/12_stage4_anchor_fallback_and_3d_visualization.md`
- `stage/handover_stage45_20260507/13_stage5_and_real_3d_wind_plan.md`

如果任务涉及监控、全量运行或详细命令，再看：
- `stage/handover_stage45_20260507/05_full_run_monitoring_checklist.md`
- `stage/handover_stage45_20260507/06_server_top10_monitor_commands.md`
- `stage/handover_stage45_20260507/07_full_command_catalog.md`

请特别注意以下事实：

1. 当前主控脚本是 `stage/run_stage34_workflow_v2.sh`
2. 当前真实使用代码是 `stage/stage3_agents_v2.py` 和 `stage/stage4_pack_v2.py`
3. 老版 `stage/stage3_agents.py` / `stage/stage4_pack.py` 不是当前主线
4. `Stage3` 正式输出目录是 `/data/LFT-W02_data/pengxu/stage3_output_v2`
5. `Stage4` 正式输出目录是 `/data/LFT-W02_data/pengxu/stage4_output_v2`
6. `full_aux_export` 输出目录是 `/data/LFT-W02_data/pengxu/stage4_output_full_aux_v2/<RUN_LABEL>`
7. `Stage3` 可以分片并行，`Stage4` 默认不能多进程分片，因为它依赖 `prev_recon_state`、temporal background 和 forecast 等时序状态
8. `Stage4` 已接近冻结，不再无限追 `coverage`
9. `Stage5` 是后续创新层，负责事件驱动、ROI refinement、短时预测，不和 `Stage4` 主结果混写
10. `historical GFS comparison`、实时 `GFS / GDAS` 背景图、`Stage4 / Stage5` 重构结果不能混用
11. 如果任务已经明确，优先从 `15_requirement_command_guide.md` 进入对应场景，再按需去 `07_full_command_catalog.md` 找详细命令

你开始工作前，请先输出：

- 你理解的 `Stage3 / Stage4` 目录关系
- 你理解的 `Stage4` 冻结标准
- 你理解的当前论文实验矩阵与主结果版本
- 你理解的命令检索入口关系：什么时候先看 `15`，什么时候再看 `07`
- 你理解的 `historical GFS comparison` 与实时背景图边界

确认后，再开始执行新的任务。
```

---

## 论文导向版

```text
请把当前项目理解为：

“面向空地一体协同感知的稀疏多源风场重建（Stage4）与后续事件驱动实时风场预测（Stage5）”

请先阅读：

- `stage/handover_stage45_20260507/00_overview.md`
- `stage/handover_stage45_20260507/14_project_knowledge_base_summary.md`
- `stage/handover_stage45_20260507/03_stage4_paper_experiment_matrix.md`
- `stage/handover_stage45_20260507/12_stage4_anchor_fallback_and_3d_visualization.md`
- `stage/handover_stage45_20260507/13_stage5_and_real_3d_wind_plan.md`
- `stage/handover_stage45_20260507/08_paper_recommendations.md`

请注意：

- 当前重点不是继续无限修改 `Stage4`，而是把 `Stage4` 作为论文实验平台冻结
- 当前 `S5 FinalFast` 是主结果版本
- 当前 `S6 FullAux` 是训练导出版本
- 论文优先围绕 `Stage4` 的状态构建层、内部 baseline 和消融展开
- `Stage5` 暂时作为后续方向单列，不要和 `Stage4` 主结果混写成一篇完成版方法
- 如果要找实验或运行命令，优先先看 `15_requirement_command_guide.md`

请先总结：

1. 这篇论文当前最适合写成什么方向
2. `Stage4` 为什么应该先冻结
3. 现有代码最适合支撑哪些实验
4. `Stage5` 应该以什么方式作为后续创新层进入论文叙事

之后再继续后续工作。
```

---

## 最简提醒

如果你只想给新窗口一句最短的话，可以直接复制下面这段：

```text
先判断你的任务是“找命令”还是“理解项目”。找命令先看 `stage/handover_stage45_20260507/15_requirement_command_guide.md`；理解项目先看 `stage/handover_stage45_20260507/00_overview.md` 和 `stage/handover_stage45_20260507/14_project_knowledge_base_summary.md`。当前真实运行使用 `stage/run_stage34_workflow_v2.sh`、`stage/stage3_agents_v2.py`、`stage/stage4_pack_v2.py`。`Stage4` 已接近冻结，当前先做全量、结果整理、baseline / ablation；`Stage5` 是后续事件驱动实时预测方向。`historical GFS comparison`、实时 `GFS / GDAS` 背景图和 `Stage4 / Stage5` 重构结果不要混用。
```

---

## 新窗口第一步建议

新窗口接手后，先做下面这个判断：

1. 如果当前任务是找命令：
   先读 `15_requirement_command_guide.md`

2. 如果当前任务是理解项目：
   先读 `00_overview.md` 和 `14_project_knowledge_base_summary.md`

3. 如果当前任务涉及 `Stage5`、背景场或历史 GFS 分析：
   再读 `13_stage5_and_real_3d_wind_plan.md`

4. 如果当前任务涉及 `Stage4` 运行、冻结原则或消融：
   再读 `01_stage34_pipeline.md`、`02_stage4_modification_and_freeze.md`、`03_stage4_paper_experiment_matrix.md`

---

## 备注

- `15_requirement_command_guide.md` 是命令入口页
- `07_full_command_catalog.md` 是详细命令库
- `14_project_knowledge_base_summary.md` 是项目总理解入口
- `09` 的职责不是重复全部背景，而是让新窗口一进来就知道先看什么、先做什么
