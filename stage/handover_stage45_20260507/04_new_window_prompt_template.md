# 新窗口提示词模板

## 这份文档的作用
这份文档给你一个可直接复制到“新窗口 / 新对话”的提示词模板。  
目标是让新的对话在几乎没有历史上下文的情况下，也能迅速接住当前项目。

建议搭配以下交接文档一起使用：

- `stage/handover_stage45_20260507/00_overview.md`
- `stage/handover_stage45_20260507/01_stage34_pipeline.md`
- `stage/handover_stage45_20260507/02_stage4_modification_and_freeze.md`
- `stage/handover_stage45_20260507/03_stage4_paper_experiment_matrix.md`
- `stage/handover_stage45_20260507/12_stage4_anchor_fallback_and_3d_visualization.md`
- `stage/handover_stage45_20260507/13_stage5_and_real_3d_wind_plan.md`
- `stage/handover_stage45_20260507/15_requirement_command_guide.md`
- 如果任务涉及 historical GFS comparison，还应把 `stage5_external_background/gfs_historical_aws_npz`、`stage5_output_v1_historical_gfs_keyframes`、`stage5_visualizations/historical_gfs_keyframes_comparison` 一并作为当前事实来源

如果任务涉及全量运行、服务器监控、论文组织或结果记录，也建议继续阅读：

- `stage/handover_stage45_20260507/05_full_run_monitoring_checklist.md`
- `stage/handover_stage45_20260507/07_full_command_catalog.md`
- `stage/handover_stage45_20260507/15_requirement_command_guide.md`
- `stage/handover_stage45_20260507/08_paper_recommendations.md`
- `stage/handover_stage45_20260507/10_stage4_result_record_template.md`
- `stage/handover_stage45_20260507/11_stage4_questions_explained.md`

---

## 最短版提示词

```text
这是一个面向空地一体协同感知的稀疏多源风场重建项目。请先阅读以下 6 份交接文档，再继续工作：

1. stage/handover_stage45_20260507/00_overview.md
2. stage/handover_stage45_20260507/01_stage34_pipeline.md
3. stage/handover_stage45_20260507/02_stage4_modification_and_freeze.md
4. stage/handover_stage45_20260507/03_stage4_paper_experiment_matrix.md
5. stage/handover_stage45_20260507/12_stage4_anchor_fallback_and_3d_visualization.md
6. stage/handover_stage45_20260507/13_stage5_and_real_3d_wind_plan.md
7. stage/handover_stage45_20260507/15_requirement_command_guide.md

当前真实运行使用：
- stage/run_stage34_workflow_v2.sh
- stage/stage3_agents_v2.py
- stage/stage4_pack_v2.py

当前状态：
- Stage3 正式输出目录是 /data/LFT-W02_data/pengxu/stage3_output_v2
- Stage4 正式输出目录是 /data/LFT-W02_data/pengxu/stage4_output_v2
- Stage4 默认不做多进程分片，因为它依赖时序状态
- Stage4 已接近冻结，支持显式模块开关，可做消融
- Stage4 现在包含保守的 wind_primary anchor fallback
- 当前代表帧 2D/3D 可视化脚本是 stage/report_stage4_recon_slices.py
- 当前地理坐标可视化脚本是 stage/report_stage4_geo_wind_visualization.py
- 当前 Stage5 v1 独立脚本是 stage/stage5_pinn_diffusion_refine.py
- 当前 Stage5 外部背景场脚本包括 stage/download_stage5_era5_roi.py、stage/download_stage5_gfs_gdas_roi.py、stage/run_stage5_rolling_roi.py、stage/report_stage5_background_field.py、stage/report_stage5_background_comparison.py
- GFS/GDAS 背景场是 Stage5 的大尺度先验和对比基准，不是 Stage4/Stage5 重构真值
- 历史 GFS archive 已跑通，`stage/download_stage5_gfs_aws_historical_roi.py` 可以把 `20260124013600`、`20260129114200`、`20260206174200`、`20260222063600` 对齐到对应的 GFS cycle / forecast hour
- `report_stage5_background_comparison.py` 已可识别 `era5_roi_*` / `gfs_roi_*` / `gdas_roi_*` / `background_*`
- 历史 GFS 三栏图目录是 `stage5_visualizations/historical_gfs_keyframes_comparison`
- 当前全量 full_fast_stage4_frozen_v1 stage4_only 结果是诊断基线，不直接当作最终 S5 FinalFast 主结果
- 如果已经知道当前需求是什么，优先去 `15_requirement_command_guide.md` 按场景找命令，不要在多个 md 中来回翻
- 后续方向是先校准并跑真正 S5 FinalFast 全量，再把 Stage5 作为事件驱动、ROI 聚焦、PINN/diffusion refinement 与短时预测模块单独推进

请先基于这些文档复述你理解的当前 Stage3/Stage4 目录关系、Stage4 冻结原则、S0-S6 论文实验矩阵、primary anchor fallback、地理坐标可视化、Stage5 v1 状态、historical GFS comparison 与实时 GFS 背景图的区别，以及现在应该先从哪份命令文档里找对应需求的命令，再继续执行后续任务。
```

---

## 完整版提示词

```text
这是一个面向空地一体协同感知的稀疏多源风场重建项目。请先完整阅读以下文档：

- stage/handover_stage45_20260507/00_overview.md
- stage/handover_stage45_20260507/01_stage34_pipeline.md
- stage/handover_stage45_20260507/02_stage4_modification_and_freeze.md
- stage/handover_stage45_20260507/03_stage4_paper_experiment_matrix.md
- stage/handover_stage45_20260507/12_stage4_anchor_fallback_and_3d_visualization.md
- stage/handover_stage45_20260507/13_stage5_and_real_3d_wind_plan.md
- stage/handover_stage45_20260507/15_requirement_command_guide.md

请注意以下事实：

1. 当前主控脚本是 `stage/run_stage34_workflow_v2.sh`
2. 当前真实使用代码是 `stage/stage3_agents_v2.py` 和 `stage/stage4_pack_v2.py`
3. `stage/stage3_agents.py` / `stage/stage4_pack.py` 不是当前主线
4. `Stage3` 的正式输出目录是 `/data/LFT-W02_data/pengxu/stage3_output_v2`
5. `Stage4` 的正式输出目录是 `/data/LFT-W02_data/pengxu/stage4_output_v2`
6. `full_aux_export` 的输出目录是 `/data/LFT-W02_data/pengxu/stage4_output_full_aux_v2/<RUN_LABEL>`
7. `Stage4` 默认不做多进程分片，因为它依赖 `prev_recon_state`、temporal background 和 forecast 等时序状态
8. `Stage4` 当前支持显式模块开关，已接近冻结
9. 论文实验矩阵使用 `S0-S6` 命名，其中 `S5 FinalFast` 是当前主结果版本
10. 当前 `stage4_pack_v2.py` 已加入保守的 `wind_primary` primary anchor fallback，新增 summary 字段 `wind_primary_fallback_voxels`
11. fallback 相关环境变量包括 `WIND_STAGE4_ENABLE_PRIMARY_ANCHOR_FALLBACK`、`WIND_STAGE4_PRIMARY_ANCHOR_FALLBACK_RATIO`、`WIND_STAGE4_PRIMARY_ANCHOR_FALLBACK_MAX`、`WIND_STAGE4_PRIMARY_ANCHOR_FALLBACK_WEIGHT`
12. 当前代表帧可视化脚本是 `stage/report_stage4_recon_slices.py`，支持 `--viz-mode slices|3d|both`
13. 代表帧 2D/3D PNG 默认输出目录是 `/data/LFT-W02_data/pengxu/stage4_visualizations/stage4_output_v2_representative`
14. 当前地理坐标可视化脚本是 `stage/report_stage4_geo_wind_visualization.py`，输出 `/data/LFT-W02_data/pengxu/stage4_visualizations/stage4_output_v2_geo_representative`
15. 当前 Stage5 v1 独立脚本是 `stage/stage5_pinn_diffusion_refine.py`，默认输出 `/data/LFT-W02_data/pengxu/stage5_output_v1`
16. Stage5 v1 是 `PINN-proxy + diffusion-style` ROI refinement scaffold，不是训练好的 neural diffusion，也不接入 Stage4 主链
17. Stage5 当前已新增外部三维背景场工具：`stage/download_stage5_era5_roi.py`、`stage/download_stage5_gfs_gdas_roi.py`、`stage/report_stage5_background_field.py`、`stage/report_stage5_background_comparison.py`
18. Stage5 rolling ROI 入口是 `stage/run_stage5_rolling_roi.py`，可用 `--frame-times 20260124013600,20260222063600` 或真实 `--frame-indices 76,7041`，不要输入 `<new_frame_indices>` 这类尖括号占位符
19. GFS/GDAS 背景场 3D 图只是 NOAA GFS/GDAS pressure-level 背景场可视化，不是本项目重构结果；历史 GFS comparison 才是把你的 Stage4 / Stage5 sparse ROI 重构和对应历史背景场放在一起看的三栏图
20. 历史 GFS archive 已跑通，`stage/download_stage5_gfs_aws_historical_roi.py` 可以把 `20260124013600`、`20260129114200`、`20260206174200`、`20260222063600` 对齐到对应的 GFS cycle / forecast hour
21. `report_stage5_background_comparison.py` 已可识别 `era5_roi_*` / `gfs_roi_*` / `gdas_roi_*` / `background_*`
22. `stage5_visualizations/historical_gfs_keyframes_comparison` 是当前 historical GFS 三栏图目录
23. 当前 `historical_gfs_keyframes` 的 summary 里 `background_available=1`，但背景场与局地 anchor 可能冲突，不能只看图像形态判断好坏
24. 当前全量 `full_fast_stage4_frozen_v1 stage4_only` 结果应视为 full-aux 风格诊断基线，不直接作为论文最终 `S5 FinalFast` 主结果引用
25. 真正 `S5 FinalFast` 校准或全量运行必须在日志中确认 `fast_mode=1`、`output_profile=fast`、`quality_profile=fast_balanced`、`quality_expand_enabled=0`、`omp_threads=6`
26. 如果要求 GPU，必须额外确认日志里是 `gpu_enabled=1` 和 `gpu_device=cuda:0`；已有小样本校准日志曾出现 `gpu_mode=1 gpu_enabled=0 gpu_device=cpu`
27. Stage4 运行建议使用 `/data/LFT-W02_data/pengxu/.conda/envs/windy310/bin/python`，可视化和 Stage5 smoke test 可使用 `/opt/miniconda3/bin/python`
28. 更真实的三维风场需要额外 3D 背景场、三维雷达产品、更多垂直风观测和独立验证标签
29. 后续目标是在 Stage4 冻结后设计 Stage5：事件驱动、ROI 聚焦、PINN/diffusion refinement、短时实时风场预测

你开始工作前，请先输出：

- 你对当前 Stage3 / Stage4 目录关系的理解
- 你对 Stage4 冻结标准的理解
- 你对论文实验矩阵 `S0-S6` 的理解
- 你对 `wind_primary` primary anchor fallback 的理解
- 你对当前 2D/3D 代表帧可视化、地理坐标可视化、S5 FinalFast 校准、Stage5 v1，以及 historical GFS comparison 和实时 GFS 背景图区别的理解

确认这些后，再继续执行后续任务。
```

---

## 论文导向版提示词

```text
请把当前项目理解为：

“面向空地一体协同感知的稀疏多源风场重建（Stage4）与后续事件驱动实时风场预测（Stage5）”

当前阶段的重点不是继续无限调 Stage4，而是：

1. 确认 Stage4 已经可冻结
2. 梳理 Stage4 的论文实验矩阵
3. 组织内部 baseline / ablation
4. 用代表帧 2D/3D 可视化解释重构形态
5. 在 Stage4 冻结后规划 Stage5

请先阅读：
- stage/handover_stage45_20260507/00_overview.md
- stage/handover_stage45_20260507/01_stage34_pipeline.md
- stage/handover_stage45_20260507/02_stage4_modification_and_freeze.md
- stage/handover_stage45_20260507/03_stage4_paper_experiment_matrix.md
- stage/handover_stage45_20260507/12_stage4_anchor_fallback_and_3d_visualization.md
- stage/handover_stage45_20260507/13_stage5_and_real_3d_wind_plan.md

阅读后，请按论文视角总结：
- 当前方法链路
- 当前真正创新空间
- Stage4 冻结后还能做哪些低风险解释性增强
- 当前 full_fast_stage4_frozen_v1 stage4_only 为什么只是诊断基线
- 真正 S5 FinalFast 应如何校准并作为论文主结果
- Stage5 v1 为什么只是独立 scaffold
- 真实三维风场还需要哪些外部数据
- Stage5 应该怎么接成 PINN/diffusion refinement 与短时预测模块
```

---

## 运行 / 可视化导向版提示词

```text
请先阅读以下文档：

- stage/handover_stage45_20260507/00_overview.md
- stage/handover_stage45_20260507/01_stage34_pipeline.md
- stage/handover_stage45_20260507/02_stage4_modification_and_freeze.md
- stage/handover_stage45_20260507/03_stage4_paper_experiment_matrix.md
- stage/handover_stage45_20260507/12_stage4_anchor_fallback_and_3d_visualization.md
- stage/handover_stage45_20260507/13_stage5_and_real_3d_wind_plan.md

我接下来要继续做 Stage4 结果检查、S5 FinalFast 校准、地理坐标可视化或 Stage5 ROI refinement。请特别注意：

- Stage4 输入应来自 /data/LFT-W02_data/pengxu/stage3_output_v2
- Stage4 默认输出是 /data/LFT-W02_data/pengxu/stage4_output_v2
- 当前可视化脚本是 stage/report_stage4_recon_slices.py
- 当前地理坐标可视化脚本是 stage/report_stage4_geo_wind_visualization.py
- 当前 Stage5 v1 脚本是 stage/stage5_pinn_diffusion_refine.py
- 当前 Stage5 外部背景场工具是 stage/download_stage5_era5_roi.py、stage/download_stage5_gfs_gdas_roi.py、stage/report_stage5_background_field.py、stage/report_stage5_background_comparison.py
- 当前 rolling ROI 入口是 stage/run_stage5_rolling_roi.py，优先用 `--frame-times` 或真实 `--frame-indices`，不要输入尖括号占位符
- 可视化默认输出是 /data/LFT-W02_data/pengxu/stage4_visualizations/stage4_output_v2_representative
- 地理坐标可视化默认输出是 /data/LFT-W02_data/pengxu/stage4_visualizations/stage4_output_v2_geo_representative
- Stage5 v1 默认输出是 /data/LFT-W02_data/pengxu/stage5_output_v1
- 可视化只读 sparse_lossless NPZ，不要展开完整 dense 体
- Stage5 v1 只读 Stage4 sparse 输出，不覆盖 Stage4
- GFS/GDAS 背景场是第三方预报背景和先验，不是本项目重构真值
- historical GFS comparison 才是把 Stage4 / Stage5 sparse ROI 重构和对应历史背景场放在一起看的结果
- S5 FinalFast 校准需要显式确认 fast_mode=1、output_profile=fast、quality_profile=fast_balanced、quality_expand_enabled=0、omp_threads=6
- 若要求 GPU，必须确认 gpu_enabled=1 gpu_device=cuda:0

请先复述你理解的当前运行状态和下一步风险点，特别是如何区分实时 GFS 背景图、historical GFS comparison 和 Stage4/Stage5 重构真值，以及现在应先从 `15_requirement_command_guide.md` 的哪个场景入口去找命令，再执行我的具体任务。
```

---

## 使用建议

### 适合什么时候用“最短版”
- 你只想让新窗口快速接住上下文
- 任务偏工程执行

### 适合什么时候用“完整版”
- 你希望新窗口充分理解目录、版本、逻辑关系
- 任务偏复杂协作、代码修改或结果分析

### 适合什么时候用“论文导向版”
- 你要进入论文组织、实验设计、章节写作

### 适合什么时候用“运行 / 可视化导向版”
- 你要继续跑 Stage4 / S5 校准
- 你要生成代表帧 2D / 3D PNG
- 你要生成地理坐标 ROI PNG
- 你要跑 Stage5 v1 小样本 refinement
- 你要分析 `stage4_summary.json`、日志或 selected frames

---

## 新窗口接手时的提醒

- 不要忘记告诉新窗口当前使用的是 `v2` 代码，不是老版
- 如果任务涉及 `stage4_only`，要强调输入目录可能需要显式指定 `STAGE3_INPUT_DIR_FOR_STAGE4=/data/LFT-W02_data/pengxu/stage3_output_v2`
- 如果任务涉及论文，优先让新窗口读 `02`、`03` 和 `12`
- 如果任务涉及 Stage5 或真实三维风场，必须读 `13`
- 如果任务一开始就很明确，例如“我要重跑 Stage4_only”“我要做历史 GFS comparison”“我要看监控日志”，优先让新窗口先读 `15_requirement_command_guide.md`
- 如果任务涉及正式 `S5 FinalFast` 全量，先小样本校准，再全量，不要直接把诊断基线当论文主结果
- 如果任务涉及 GPU，必须检查日志里的实际 `gpu_enabled`，不能只看传入了 `WIND_STAGE4_USE_GPU=1`
- 如果任务涉及 Stage5，强调当前 `stage5_pinn_diffusion_refine.py` 是独立 scaffold，不是训练完成的 diffusion 模型
