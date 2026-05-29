# centralized_v1 / TimePower15 新窗口总交接 - 2026-05-29

本文档用于新窗口快速接手项目。内容汇总自本轮对话、`workflow/centralized_v1_docs` 交接文档、`stage/youhua.md`、当前脚本阅读与目录检查结果。

## 0. 当前最重要结论

1. 当前主线是 centralized_v1 的 Stage2/Stage3/Stage4/Stage5 风场重建链路，核心产物在 `/data/LFT-W02_data/pengxu/centralized_v1_output`。
2. Stage4 当前最佳主线是 TimePower15 / full_v2 / best adaptive / 12-worker 全量版本：
   `/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_full_v2_best_adaptive_all_12w_20260529`
3. `stage/youhua.md` 给出的最新复盘结论必须作为后续优化主线：7395 帧全量重构已完成，5614 帧有 holdout 可严格评估，1781 帧 no-holdout 不能计入 RMSE/MAE，但必须保留业务重构结果。
4. 当前模型是研究型三维风场重建候选模型，不是航空运行级风切变预警系统。500m 垂直网格单点风速误差不能直接等价 30m 垂直风切变阈值。
5. 后续优化方向不是简单追全局 RMSE，而是分层评估、ROI 可视化、异常帧溯源、CMA 弱背景、PINN 物理残差修正、Diffusion 局地长尾修复、独立 wind_shear_risk_head。

## 1. 项目阶段边界

### Stage1

Stage1 负责把原始 Excel/雷达索引等数据清洗为稳定中间产物，例如：

- `stage1_output/clean_wind.parquet`
- `stage1_output/clean_loc.parquet`
- `stage1_output/radar_index.json`
- `stage1_output/frame_window_index.json`

Stage1 的关键风险是：Excel 时间、经纬度、高度、风向风速字段解析不稳，导致后续 Stage2 无法对齐雷达帧或体素网格。

### Stage2

Stage2 是观测组织与体素化阶段，不是风场反演本身。它把飞机位置、风、运动、上下文窗口、雷达/云图支撑组织到统一 Stage2 网格。

关键认知：

- current window 通常是雷达帧附近短时间窗口。
- context window 是更长时间背景窗口。
- `wind_records` 是当前飞机风观测，后续可作为 Stage4 holdout 候选。
- `context_wind_records` 是上下文背景观测，可参与 Stage4 融合。
- Stage2 图里稀疏/点状不是失败，而是观测组织诊断。

当前重要输出：

- `/data/LFT-W02_data/pengxu/centralized_v1_output/stage2_full_v2`
- `/data/LFT-W02_data/pengxu/centralized_v1_output/stage2_full_frame_times.json`

12-worker Stage2 命令：

```bash
cd /data/LFT-W02_data/pengxu

POLARS_MAX_THREADS=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 \
/data/LFT-W02_data/pengxu/.conda/envs/windy310/bin/python \
stage/centralized_v1/core/centralized_stage2_multimodal.py \
  --stage1-dir stage1_output \
  --out-dir centralized_v1_output/stage2_full_v2 \
  --frame-times-file centralized_v1_output/stage2_full_frame_times.json \
  --num-workers 12
```

### Stage3

Stage3 负责 Ground Center payload / agent payload 打包，把 Stage2 结果组织成 Stage4 可消费的中心化输入。

当前重要输出：

- `/data/LFT-W02_data/pengxu/centralized_v1_output/stage3_full_v2_8w_minimal`

Stage3 的 aircraft-agent freshness / confidence 是诊断信息，当前 Stage4 主要使用 record-level `time_conf` 和 `obs_conf`，而不是直接使用完整 agent confidence 做风场融合。

### Stage4

Stage4 是 centralized_v1 中第一个真正生成三维风场的阶段。

严格 holdout 原则：

```text
holdout_wind = 当前帧 selected wind_records
train_wind = 当前 wind_records - holdout_wind
fusion input = train_wind + context_wind_records
```

核心规则：

- holdout 是答案，不能进入融合。
- context_wind_records 可以作为背景参与融合。
- strict_holdout_no_leakage 必须为 true。
- Stage4 的验证真值是稀疏飞机观测，不是完整 3D 真风场。
- `recon_mask_3d` 表示模型声明有效重构的体素范围，不等于全国全域都有风场。

当前主线输出：

- `/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_full_v2_best_adaptive_all_12w_20260529`
- `/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_best_adaptive_representative_visuals_20260529`
- `/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_best_vs_baseline_200_12w_20260528`

## 2. TimePower15 / full_v2 / best adaptive 全量复盘

`stage/youhua.md` 是当前最重要的优化复盘文档。

固定实验路径：

```text
/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_full_v2_best_adaptive_all_12w_20260529
```

全量统计：

- 总推理帧数：7395
- no-holdout 帧：1781
- 有 holdout 可严格评估帧：5614
- 含 no-holdout 的乐观均值：RMSE 6.60 m/s，MAE 5.81 m/s
- 有效 holdout 子集真实均值：RMSE 8.70 m/s，MAE 7.65 m/s
- 测点加权真实 MAE：6.72 m/s

关键修正：

- no-holdout 帧不是无效预测，也不是无业务价值样本。
- no-holdout 帧没有当前飞机真值，所以不能参与严格 RMSE/MAE。
- no-holdout 帧仍具备大量 context wind 支撑、有效重构体素、强风体素和低置信补全区域，必须保留。
- 过去把 no-holdout 误差置 0 后混入均值，会显著美化指标。

标准评估分层：

1. A 类：有当前 aircraft wind_records 的 holdout 帧，唯一用于严格 RMSE/MAE。
2. B/C 类：no-holdout 无真值帧，保留重构，标记为 unverified reconstruction，只做覆盖率、置信度、强风、垂直失配、低置信填补等诊断。
3. 稀疏测点压力测试帧单独统计。
4. QC 异常或物理不可能风速帧单独过滤。
5. 强风层、气象急变层、特征冲突区域单独评估。

## 3. 航空风切变指标边界

民航常见风险阈值是 30m 垂直层内风速差达到约 6m/s 的严重风切变临界量级。当前 TimePower15 评估的是 500m 网格上的飞机单点 u/v 水平风矢量重构误差。

必须固定以下边界：

- 不能把 Stage4 的 6-9 m/s 单点 RMSE 直接等价为 30m 风切变阈值。
- 二者物理定义、垂直尺度、空间维度不同。
- 但当前误差与航空安全阈值处于同一量级，会侵蚀风切变诊断安全裕度。
- 因此当前模型不能作为运行级风切变预警落地。
- 后续必须增加 vertical jump、vertical mismatch、strong-layer consistency、wind_shear_risk_head 等航空风险诊断能力。

## 4. ROI 可视化与有效覆盖

全域图稀疏不是模型完全失败，而是 Stage4 只在有证据支撑区域做局地重构。原始网格为：

```text
31 x 525 x 775 = 12,613,125 voxels
```

全域图大量灰白，是因为有效 footprint 被全国大网格稀释。

`youhua.md` 固定的 ROI 范围：

```text
纬度: 15.32N - 39.08N
经度: 104.84E - 120.04E
```

该 ROI 覆盖中国中东部、华南至华北南缘的核心区域。真实有效风场 footprint 只覆盖 ROI 中有飞机/雷达/云图证据支撑的区域，不是矩形全域都有可信风。

ROI 面积结论：

- ROI crop area 覆盖中国陆域约 28.5%-37.9%
- actual footprint area 覆盖中国陆域约 6.7%-11.7%

默认可视化参数：

```bash
--crop-mode bbox
--crop-pad 24
--z-levels auto
```

重点路径：

- ROI 总索引：`/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_best_adaptive_representative_visuals_20260529/representative_visual_index_roi.md`
- ROI 图目录：`/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_best_adaptive_representative_visuals_20260529/visuals_roi`
- 面积统计：`/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_best_adaptive_representative_visuals_20260529/roi_area_coverage.csv`
- 可视化脚本：`/data/LFT-W02_data/pengxu/stage/centralized_v1/core/centralized_report_stage4_slices.py`

## 5. CMA / 3DVAR / virtual radial 的正确定位

CMA-RA / CRA40 路线的核心是：

```text
CMA u/v/w -> Stage2 grid -> synthetic radar line-of-sight virtual radial velocity
+ sparse Stage4 prior inside recon_mask_3d
+ aircraft anchors
-> class-PyDDA / 3DVAR proxy product
```

关键边界：

- CMA 是弱背景、伪观测、预训练结构先验或条件输入。
- CMA 不是飞机观测真值。
- CMA 不能作为最终严格精度判定依据。
- CMA 6h 到 6min 的 linear/QC 插值不能生成真实 6min 对流突变细节。
- CMA branch 应与 aircraft-only strict baseline 分开报告。

已做过的 CMA 分支包括：

- `cma_ra_virtual_radial_3dvar`
- `cma_ra_virtual_radial_3dvar_linear6min`
- `cma_ra_virtual_radial_3dvar_linear_12w_20260528`
- `stage4_cma_fused_linear_10frames_12w_20260528`
- `stage4_cma_linear_qc_10frames_12w_20260528`
- `stage4_cma_geometry_corrected_10frames_12w_20260528`
- `stage4_cma_standard_demo_2frames_12w_20260528`

这些是有价值的实验分支，但不是当前 strict baseline 的真值来源。

## 6. PINN + Diffusion 后续优化路线

`youhua.md` 固定的最优路线：

```text
TimePower15 主干基础场
+ CMA 6min 插值弱背景/条件输入
+ 飞机观测作为唯一真实监督
+ PINN 全局物理残差修正
+ 条件 Diffusion 局地极端/长尾修复
+ wind_shear_risk_head 独立风切变风险分支
```

禁止路线：

- 禁止用 CMA 当真值训练。
- 禁止用 Diffusion 全场替换 TimePower15 主干。
- 禁止用 no-holdout 的 CMA 一致性当作模型精度。
- 禁止只追逐全局 RMSE 而抹平强风层和风切变信号。

推荐残差范式：

```text
input:
  F_timepower15, confidence_3d, recon_mask_3d,
  role_conflict_mask, vertical_mismatch, low_conf_fill,
  CMA background, radar/cloud context

output:
  delta_u, delta_v, uncertainty, wind_shear_risk

final:
  u_final = u_timepower15 + delta_u
  v_final = v_timepower15 + delta_v
```

PINN 负责确定性物理残差与垂直一致性，Diffusion 负责长尾、局地非线性、强对流/突变细节和不确定性。

## 7. 当前脚本理解

### `stage/convert_excel_to_parquet_robust.py`

用途：把 `location` / `amdar` / `turb` Excel 转成 parquet shards，并写 `_manifest.json`。

功能：

- 自动识别 workbook 类型。
- 每个 sheet 输出 `sheet_XX.parquet`。
- 保留原始列，同时增加标准列。
- 解析 Excel 时间、字符串时间、年份截断时间。
- 将 AMDAR/TURB 北京时间转 UTC。
- 解析航空紧凑经纬度，如 `N28203089` / `E109399986`。
- 标准化字段包括 `time_utc`、`time_beijing`、`lat_clean`、`lon_clean`、`alt_meters`、`flight_id`、`u_wind`、`v_wind`、`u_motion`、`v_motion`。
- location 特殊处理：第一个 sheet 有表头，后续 sheet 无表头，脚本补 8 个固定列。

当前限制：

- 目前脚本是串行逐 workbook / 逐 sheet 转换。
- 不支持 `--num-workers`。
- 不能直接用多个外部进程切同一个 workbook 并行，因为会互相覆盖 `_manifest.json`。

计划改造：

```text
主进程读取 sheet 列表
19 个 worker 分别处理不同 sheet
每个 sheet 写唯一 sheet_XX.parquet
全部完成后主进程统一写一次 _manifest.json
```

### `stage/check_location_parquet_quality.py`

用途：检查 `location_location_parquet` 是否健康。

检查：

- manifest 是否存在。
- sheet parquet 是否缺失。
- 行数/列数是否异常。
- 是否缺少 location 基础列。
- 时间解析率。
- 纬度、经度、高度有效率。
- 是否存在超大且疑似空数据 shard。

范围阈值：

```text
lat: 12.2 - 54.2
lon: 73.0 - 135.0
alt: 0 - 15000
```

### `stage/check_stage1_stage2_alignment.py`

用途：检查 Stage1 输出能否正确对齐 Stage2。

检查：

- `clean_wind.parquet`、`clean_loc.parquet` 是否存在。
- 雷达文件是否能找到、能解析时间。
- location/wind 时间是否与雷达帧有重叠。
- 每个雷达窗口内 loc_rows / wind_rows 数量。
- location 点能否落入 Stage2 体素网格。
- `in_range_ratio` 和 `unique_voxels` 是否足够。

如果无可用雷达帧、少于 20% location 点落入网格、或无体素点，会失败退出。

## 8. `20260224` 原始数据当前状态

目录：

```text
/data/LFT-W02_data/pengxu/20260224
```

当前文件：

```text
amdar.xlsx      24M
location.xlsx   252M
```

检查结论：

- `amdar.xlsx` 完整，可读，1 个 sheet：`Sheet1`
- `location.xlsx` 损坏，`pandas` 和 `unzip -t` 都读不了，报 `End-of-central-directory signature not found` / `BadZipFile`

因此现在只能先转换 AMDAR。location 需要重新传输或重新导出完整 xlsx 后再跑。

AMDAR 转换命令：

```bash
cd /data/LFT-W02_data/pengxu

POLARS_MAX_THREADS=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 \
/data/LFT-W02_data/pengxu/.conda/envs/windy310/bin/python \
stage/convert_excel_to_parquet_robust.py \
  --excel /data/LFT-W02_data/pengxu/20260224/amdar.xlsx \
  --out-root /data/LFT-W02_data/pengxu/20260224
```

输出：

```text
/data/LFT-W02_data/pengxu/20260224/amdar_parquet/sheet_00.parquet
/data/LFT-W02_data/pengxu/20260224/amdar_parquet/_manifest.json
```

## 9. 磁盘与清理状态

之前普通 Codex 沙箱失败，原因是 `/tmp` 在根分区 `/` 上，而根分区一度 100% 满。后来根分区恢复：

```text
/      约 79%，可用约 336G
/data  约 55%，可用约 26T
```

已清理：

- `/tmp/codex-bwrap-synthetic-mount-targets-1001`

未完全删除：

- `/tmp/codex-ipc` 只剩 4K，其中 socket 权限不属于当前用户，空间影响可忽略。

注意：

- 删除 `/data/LFT-W02_data/pengxu/centralized_v1_output` 释放的是 `/data` 空间，不直接解决 `/tmp` 根分区问题。
- 当前 `/data` 空间还够，主要应避免误删主线结果。

## 10. `centralized_v1_output` 保留/可删判断

暂时不要删：

```text
stage2_full_v2
stage2_full_frame_times.json
stage3_full_v2_8w_minimal
stage4_full_v2_best_adaptive_all_12w_20260529
stage4_full_v2_best_adaptive_all_12w_20260529.log
stage4_best_adaptive_representative_visuals_20260529
stage4_best_vs_baseline_200_12w_20260528
stage4_full_v2_validation_200_8w
stage4_full_v2_validation_200_8w.log
training_manifest
```

低风险可删类型：

- `*_smoke`
- `*_sleep_run`
- `*_debug_one`
- old `stage2_regenerated`
- old `stage3_center`
- old `stage4_center`
- old two-frame demos
- `cma_ra_virtual_radial_3dvar_linear_test`

大空间但需确认后再删的 CMA 实验分支：

```text
stage4_cma_linear_qc_10frames_12w_20260528
stage4_cma_geometry_corrected_10frames_12w_20260528
cma_ra_virtual_radial_3dvar_linear_12w_20260528
stage4_cma_standard_demo_2frames_12w_20260528
stage4_cma_fused_linear_10frames_12w_20260528
cma_ra_virtual_radial_3dvar_linear6min
cma_ra_virtual_radial_3dvar
stage4_cma_fused_linear_demo_12w_20260528
stage4_cma_fused_linear6min_demo_12w_20260527
```

这些 CMA 分支不是当前 strict baseline，但如果还要复查 CMA 图、几何校正或 proxy 对比，就先不要删。

## 11. 下一步建议

### 短期

1. 先转换 `amdar.xlsx`。
2. 重新获取完整的 `location.xlsx`。
3. 改造 `convert_excel_to_parquet_robust.py`，支持 `--num-workers 19`，并保证 manifest 由主进程统一写。
4. 跑 `check_location_parquet_quality.py`。
5. 跑 `check_stage1_stage2_alignment.py`。

### Stage4 评估

1. 不再使用含 no-holdout 的全量混算 RMSE/MAE 作为真实性能。
2. 固定输出 holdout-only 指标。
3. no-holdout 单独输出重构覆盖、置信度、强风体素、垂直失配、低置信填补。
4. 高误差长尾帧单独追踪 P90/P95/max。
5. 高风险 no-holdout 帧单独可视化，不因无真值而忽略。

### 可视化

1. 默认使用 ROI 裁剪图复盘细节。
2. full-domain 图只用于覆盖范围与全局背景，不用于精度细节判断。
3. 固定六类代表帧：优质、临界、长尾、冲突失效、no-holdout 常规补全、no-holdout 高危未验证。

### 模型优化

1. TimePower15 保留为主干，不替换。
2. CMA 仅作为弱背景和条件输入。
3. PINN 做物理残差修正。
4. Diffusion 做局地极端/长尾/不确定性补强。
5. 新增 wind_shear_risk_head，专门服务航空风切变风险。
6. 损失函数从单一 MSE 升级为复合损失：飞机观测拟合、TimePower15 残差正则、CMA 弱一致性、弱散度、垂直风切变保留、强风层防过平滑、角色冲突惩罚、边界背景一致性。

## 12. 关键源文档

建议新窗口按这个顺序读：

1. 本文件。
2. `/data/LFT-W02_data/pengxu/stage/youhua.md`
3. `/data/LFT-W02_data/pengxu/workflow/centralized_v1_docs/new_window_handover_stage2_stage3.md`
4. `/data/LFT-W02_data/pengxu/workflow/centralized_v1_docs/stage4_20260528_cma_fusion_technical_handover.md`
5. `/data/LFT-W02_data/pengxu/workflow/centralized_v1_docs/stage4_20260528_cma_standard_12w_pipeline.md`
6. `/data/LFT-W02_data/pengxu/workflow/centralized_v1_docs/stage4_strict_holdout_logic_and_results.md`
7. `/data/LFT-W02_data/pengxu/workflow/centralized_v1_docs/stage2_stage3_full_process_explanation.md`

## 13. 新窗口第一句话建议

```text
请先阅读 /data/LFT-W02_data/pengxu/workflow/new_window_project_handover_20260529/centralized_v1_timepower15_full_handover.md 和 /data/LFT-W02_data/pengxu/stage/youhua.md。当前主线是 TimePower15 Stage4 full_v2 best adaptive 7395 帧全量结果；no-holdout 帧保留重构但不参与严格 RMSE/MAE；接下来优先改造 Excel->Parquet 脚本支持 location 19 sheet 并行转换，然后做分层评估、ROI 可视化和 PINN/Diffusion/CMA 弱背景残差优化。
```
