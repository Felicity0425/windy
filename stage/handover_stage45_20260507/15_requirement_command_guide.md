# 项目需求命令总览

## 这份文档的作用

这份文档不是“所有脚本命令的简单堆叠”，而是一个面向知识库和交接使用的**需求场景命令入口页**。  
目标是让后续接手的人先按“我现在要做什么”来找命令，而不是先猜脚本名。

当前命令体系建议理解为四层：

1. `总览层`
   - 先看项目做什么、当前主线是什么。
2. `需求场景层`
   - 先明确自己现在是做数据检查、主链运行、可视化、Stage5 背景场还是服务器监控。
3. `详细命令层`
   - 再去看对应脚本的完整命令。
4. `结果核对层`
   - 跑完后看 summary、图、日志和输出目录。

推荐搭配阅读：

- `00_overview.md`
- `01_stage34_pipeline.md`
- `07_full_command_catalog.md`
- `14_project_knowledge_base_summary.md`

其中：

- 本文件：按场景查命令
- `07_full_command_catalog.md`：详细命令库，尤其适合 Stage3 / Stage4 全量、消融、full aux

---

## 一、如果你要做什么，先看这里

### 1. 我要检查原始数据和 Stage1 清洗是否正常

先看：

- `Stage1 数据清洗与对齐检查`

### 2. 我要做 Stage2 体素化，确认每帧体素结果有没有问题

先看：

- `Stage2 体素化与体素结果核查`

### 3. 我要构建 Stage3 agent / communication graph

先看：

- `Stage3 智能体构建`

### 4. 我要跑当前主结果链路

先看：

- `Stage4 主链运行`

### 5. 我要修 Stage4 后单独重跑，不想重跑 Stage3

先看：

- `Stage4 单独重跑`

### 6. 我要做 Stage4 指标诊断、日志核查、代表帧图

先看：

- `Stage4 结果检查与可视化`

### 7. 我要做 Stage5 ROI refinement 或关键帧对比

先看：

- `Stage5 ROI refinement`

### 8. 我要接入实时 GFS/GDAS 或历史 GFS archive

先看：

- `Stage5 背景场接入`

### 9. 我要看服务器上现在跑到哪里了

先看：

- `服务器监控与日志查看`

---

## 二、Stage1 数据清洗与对齐检查

### 场景

- 原始数据第一次接入
- 想检查 parquet 清洗是否成功
- 想确认雷达帧与轨迹 / 风观测时间是否重叠

### 推荐命令 1：直接跑 Stage1

```bash
/data/LFT-W02_data/pengxu/.conda/envs/windy310/bin/python stage/stage1_prepare.py
```

适用场景：

- 重新生成 `stage1_output`
- 替换输入数据源后重建 Stage1

跑完重点看：

- `stage1_output/clean_wind.parquet`
- `stage1_output/clean_loc.parquet`
- `stage1_output/radar_index.json`
- `stage1_output/frame_window_index.json`
- `stage1_output/stage1_summary.json`

### 推荐命令 2：检查 Stage1 / Stage2 对齐

```bash
/data/LFT-W02_data/pengxu/.conda/envs/windy310/bin/python check_stage1_stage2_alignment.py
```

适用场景：

- 想确认 Stage1 清洗结果是否能顺利进入 Stage2
- 想看 `loc_rows / wind_rows / in_range_ratio`

跑完重点看：

- `radar_frames_usable`
- 每帧时间窗里的 `loc_rows / wind_rows`
- `coverage.in_range_ratio`
- `coverage.unique_voxels`

### 推荐命令 3：快速查看 Stage1 汇总

```bash
python -m json.tool /data/LFT-W02_data/pengxu/stage1_output/stage1_summary.json
```

适用场景：

- 只想看清洗后的全局规模

跑完重点看：

- `clean_wind_rows`
- `clean_loc_rows`
- `radar_total`
- `radar_usable`

---

## 三、Stage2 体素化与体素结果核查

### 场景

- 重新做雷达帧体素化
- 检查某批数据体素结果是否为空
- 想确认风/轨迹/运动体素是否合理

### 推荐命令 1：直接跑 Stage2

```bash
/data/LFT-W02_data/pengxu/.conda/envs/windy310/bin/python stage/stage2_voxelize.py
```

适用场景：

- 重新生成 `stage2_output`
- Stage1 改完后重新体素化

跑完重点看：

- `stage2_output/voxels/*.npz`
- `stage2_output/stage2_summary.json`

### 推荐命令 2：快速查看 Stage2 汇总

```bash
python -m json.tool /data/LFT-W02_data/pengxu/stage2_output/stage2_summary.json
```

适用场景：

- 只想看每帧体素统计

重点看：

- `wind_voxels`
- `traj_voxels`
- `motion_voxels`
- `amdar_voxels`
- `turb_voxels`

### 推荐命令 3：Stage2 高风帧抽样检查

```bash
python - <<'PY'
import json
from pathlib import Path
p=Path('/data/LFT-W02_data/pengxu/stage2_output/stage2_summary.json')
data=json.loads(p.read_text())
for r in sorted(data, key=lambda x: x.get('wind_voxels', 0), reverse=True)[:10]:
    print(r['time_str'], r['wind_voxels'], r['motion_voxels'], r['amdar_voxels'], r['turb_voxels'])
PY
```

适用场景：

- 想找高风支撑帧做 Stage3/4 代表样本

---

## 四、Stage3 智能体构建

### 场景

- 重新构建 flight agents
- 检查 communication graph 是否非零
- 为 Stage4 提供正式 `stage3_output_v2`

### 推荐命令 1：只跑 Stage3

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

适用场景：

- 单独调试 `stage3_agents_v2.py`
- 不想跑 Stage4

重点看：

- `stage3_output_v2/stage3_summary.json`
- `stage3_output_v2/agents/*.json`
- `valid_flight_agents`
- `flight_ff_allowed_edges`
- `flight_ff_wind_edges`

### 推荐命令 2：直接读 Stage3 汇总

```bash
python -m json.tool /data/LFT-W02_data/pengxu/stage3_output_v2/stage3_summary.json
```

### 推荐命令 3：挑高 agent / 高边数帧

```bash
python - <<'PY'
import json
from pathlib import Path
p=Path('/data/LFT-W02_data/pengxu/stage3_output_v2/stage3_summary.json')
data=json.loads(p.read_text())
for key in ['valid_flight_agents','flight_ff_allowed_edges','flight_ff_wind_edges']:
    print('\\nTOP', key)
    for r in sorted(data, key=lambda x: x.get(key, 0), reverse=True)[:5]:
        print(r['time_str'], r.get(key), r.get('wind_voxels'), r.get('motion_voxels'))
PY
```

---

## 五、Stage4 主链运行

### 场景

- 跑当前主结果版本
- 生成正式 `stage4_output_v2`
- 为论文主结果、代表帧图和 Stage5 输入提供基础状态层

### 推荐命令：`S5 FinalFast` 全量主版本

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

适用场景：

- 当前主运行链
- 正式全量输出

重点看：

- `/data/LFT-W02_data/pengxu/stage4_output_v2`
- `stage4_summary.json`
- `run_info.txt`
- `phase_status*.log`

### 推荐命令：`S6 FullAux` 训练导出

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

适用场景：

- 补 rich aux fields
- 训练前样本导出

---

## 六、Stage4 单独重跑

### 场景

- 你刚改了 `stage4_pack_v2.py`
- 不想重跑 Stage3
- 想快速重新写 `stage4_output_v2`

### 推荐命令

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

注意：

- 一定显式指定 `STAGE3_INPUT_DIR_FOR_STAGE4`
- 否则可能误读旧的 `stage3_output`

---

## 七、Stage4 结果检查与可视化

### 场景

- 看 Stage4 summary
- 跑稀疏指标 / outlier / npz 字段检查
- 生成代表帧 2D/3D 图和地理坐标图

### 推荐命令 1：看 Stage4 汇总

```bash
python -m json.tool /data/LFT-W02_data/pengxu/stage4_output_v2/stage4_summary.json
```

### 推荐命令 2：生成代表帧 2D/3D 图

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

### 推荐命令 3：生成地理坐标 ROI 图

```bash
/opt/miniconda3/bin/python stage/report_stage4_geo_wind_visualization.py \
  --stage4-dir /data/LFT-W02_data/pengxu/stage4_output_v2 \
  --summary /data/LFT-W02_data/pengxu/stage4_output_v2/stage4_summary.json \
  --out-dir /data/LFT-W02_data/pengxu/stage4_visualizations/stage4_output_v2_geo_representative \
  --selection representative
```

### 推荐命令 4：训练 readiness

```bash
/data/LFT-W02_data/pengxu/.conda/envs/windy310/bin/python stage/report_stage4_training_readiness.py
```

适用场景：

- 看当前样本是否适合进入训练 / 下游

---

## 八、Stage5 ROI refinement

### 场景

- 跑无背景关键帧 refinement
- 跑历史 GFS 对齐关键帧 refinement
- 研究 Stage5 在 ROI 上的增量价值

### 推荐命令 1：无背景关键帧

```bash
/opt/miniconda3/bin/python stage/stage5_pinn_diffusion_refine.py \
  --stage4-dir /data/LFT-W02_data/pengxu/stage4_output_v2 \
  --summary /data/LFT-W02_data/pengxu/stage4_output_v2/stage4_summary.json \
  --out-dir /data/LFT-W02_data/pengxu/stage5_output_v1_no_background_keyframes \
  --selection frames \
  --frame-times 20260124013600,20260129114200,20260206174200,20260222063600 \
  --holdout-every 5 \
  --hazard-conservative \
  --make-plots 1 \
  --max-plot-vectors 250
```

### 推荐命令 2：历史 GFS 对齐关键帧

```bash
/opt/miniconda3/bin/python stage/stage5_pinn_diffusion_refine.py \
  --stage4-dir /data/LFT-W02_data/pengxu/stage4_output_v2 \
  --summary /data/LFT-W02_data/pengxu/stage4_output_v2/stage4_summary.json \
  --out-dir /data/LFT-W02_data/pengxu/stage5_output_v1_historical_gfs_keyframes \
  --selection frames \
  --frame-times 20260124013600,20260129114200,20260206174200,20260222063600 \
  --background-dir /data/LFT-W02_data/pengxu/stage5_external_background/gfs_historical_aws_npz \
  --holdout-every 5 \
  --hazard-conservative \
  --background-data-weight 0.55 \
  --make-plots 1 \
  --max-plot-vectors 250
```

跑完看：

- `stage5_summary.json`
- `anchor_rmse_after`
- `heldout_anchor_rmse_after`
- `background_vector_rmse`
- `background_speed_bias`

---

## 九、Stage5 背景场接入

### 场景

- 接入实时 GFS/GDAS
- 接入历史 GFS archive
- 做背景场独立图

### 推荐命令 1：下载实时 GFS ROI 背景场

```bash
/opt/miniconda3/bin/python stage/download_stage5_gfs_gdas_roi.py \
  --dataset gfs \
  --mode latest \
  --forecast-hour 0 \
  --download \
  --convert-existing
```

### 推荐命令 2：下载实时 GDAS ROI 背景场

```bash
/opt/miniconda3/bin/python stage/download_stage5_gfs_gdas_roi.py \
  --dataset gdas \
  --mode latest \
  --forecast-hour 0 \
  --download \
  --convert-existing
```

### 推荐命令 3：只生成实时 GFS manifest

```bash
/opt/miniconda3/bin/python stage/download_stage5_gfs_gdas_roi.py \
  --dataset gfs \
  --mode latest \
  --forecast-hour 0
```

### 推荐命令 4：下载历史 GFS archive 对齐关键帧

```bash
/opt/miniconda3/bin/python stage/download_stage5_gfs_aws_historical_roi.py \
  --frame-times 20260124013600,20260129114200,20260206174200,20260222063600 \
  --out-dir /data/LFT-W02_data/pengxu/stage5_external_background/gfs_historical_aws \
  --npz-dir /data/LFT-W02_data/pengxu/stage5_external_background/gfs_historical_aws_npz \
  --download \
  --convert-existing
```

### 推荐命令 5：生成 MERRA-2 manifest

```bash
/opt/miniconda3/bin/python stage/download_stage5_merra2_roi.py \
  --frame-times 20260129114200,20260206174200
```

用途：

- 生成 Stage5 的第三个外部背景候选源清单
- 为后续 Earthdata 下载和 `.nc4 -> .npz` 转换做准备

### 推荐命令 6：转换本地 MERRA-2 NC4

```bash
/opt/miniconda3/bin/python stage/download_stage5_merra2_roi.py \
  --frame-times 20260129114200,20260206174200 \
  --convert-existing
```

用途：

- 已有本地 `merra2_roi_<time>.nc4` 时，转换成 Stage5 可读 NPZ
- 输出目录：
  - `/data/LFT-W02_data/pengxu/stage5_external_background/merra2_roi_npz`

### 推荐命令 7：背景场独立 3D 图

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

---

## 十、Stage5 comparison 图与差值图

### 场景

- 生成 Stage4 / Stage5 / background 三栏图
- 生成 `Stage5 - background` 差值图
- 对齐 historical GFS comparison

### 推荐命令

```bash
/opt/miniconda3/bin/python stage/report_stage5_background_comparison.py \
  --stage4-dir /data/LFT-W02_data/pengxu/stage4_output_v2 \
  --stage5-dir /data/LFT-W02_data/pengxu/stage5_output_v1_historical_gfs_keyframes \
  --background-dir /data/LFT-W02_data/pengxu/stage5_external_background/gfs_historical_aws_npz \
  --out-dir /data/LFT-W02_data/pengxu/stage5_visualizations/historical_gfs_keyframes_comparison \
  --frame-times 20260124013600,20260129114200,20260206174200,20260222063600 \
  --max-vectors 250
```

### 推荐命令：多背景候选 comparison

```bash
/opt/miniconda3/bin/python stage/report_stage5_background_comparison.py \
  --stage4-dir /data/LFT-W02_data/pengxu/stage4_output_v2 \
  --stage5-dir /data/LFT-W02_data/pengxu/stage5_output_v1_internal_bg_test \
  --background-dirs /data/LFT-W02_data/pengxu/stage5_external_background/era5_roi,/data/LFT-W02_data/pengxu/stage5_external_background/gfs_historical_aws_npz,/data/LFT-W02_data/pengxu/stage5_external_background/merra2_roi_npz \
  --out-dir /data/LFT-W02_data/pengxu/stage5_visualizations/stage5_internal_bg_test_comparison \
  --frame-times 20260129114200,20260206174200 \
  --max-vectors 250
```

跑完看：

- `comparison_summary.json`
- `background=true`
- `shared_points=250`
- `sample_mode=shared_stage4_stage5_intersection`
- `*_stage5_minus_background_3d.png`

---

## 十一、rolling ROI 与实时化入口

### 场景

- 想模拟在线事件 ROI
- 只对少量新到帧做 Stage5

### 推荐命令 1：用 frame times dry-run

```bash
/opt/miniconda3/bin/python stage/run_stage5_rolling_roi.py \
  --frame-times 20260124013600,20260222063600 \
  --run-stage5 \
  --dry-run
```

### 推荐命令 2：用真实 frame indices dry-run

```bash
/opt/miniconda3/bin/python stage/run_stage5_rolling_roi.py \
  --frame-indices 76,7041 \
  --run-stage5 \
  --dry-run
```

### 推荐命令 3：正式运行，带背景

```bash
/opt/miniconda3/bin/python stage/run_stage5_rolling_roi.py \
  --frame-times 20260124013600,20260222063600 \
  --run-stage5 \
  --background-dir /data/LFT-W02_data/pengxu/stage5_external_background/gfs_gdas_roi_npz
```

### 推荐命令 4：正式运行，无背景

```bash
/opt/miniconda3/bin/python stage/run_stage5_rolling_roi.py \
  --frame-times 20260124013600,20260222063600 \
  --run-stage5 \
  --no-background
```

---

## 十一点五、Stage5 多背景候选与内部时序背景

### 场景

- 想让 Stage5 同时比较 `ERA5 / historical GFS / MERRA-2`
- 想把上一帧 Stage5 输出作为内部时序背景候选

### 推荐命令 1：多背景候选 Stage5

```bash
/opt/miniconda3/bin/python stage/stage5_pinn_diffusion_refine.py \
  --stage4-dir /data/LFT-W02_data/pengxu/stage4_output_v2 \
  --summary /data/LFT-W02_data/pengxu/stage4_output_v2/stage4_summary.json \
  --out-dir /data/LFT-W02_data/pengxu/stage5_output_v1_internal_bg_test \
  --selection frames \
  --frame-times 20260129114200,20260206174200 \
  --background-dirs /data/LFT-W02_data/pengxu/stage5_external_background/era5_roi,/data/LFT-W02_data/pengxu/stage5_external_background/gfs_historical_aws_npz,/data/LFT-W02_data/pengxu/stage5_external_background/merra2_roi_npz \
  --internal-stage5-dir /data/LFT-W02_data/pengxu/stage5_output_v1_internal_bg_test \
  --background-top-k 1 \
  --iterations 4 \
  --holdout-every 4 \
  --make-plots 1
```

跑完看：

- `background_selected_path`
- `background_candidates`
- `background_anchor_rmse`
- `background_anchor_speed_bias`
- `heldout_anchor_rmse_after`

### 推荐命令 2：关闭内部时序背景，只看外部背景候选

```bash
/opt/miniconda3/bin/python stage/stage5_pinn_diffusion_refine.py \
  --stage4-dir /data/LFT-W02_data/pengxu/stage4_output_v2 \
  --summary /data/LFT-W02_data/pengxu/stage4_output_v2/stage4_summary.json \
  --out-dir /data/LFT-W02_data/pengxu/stage5_output_v1_multi_background_test \
  --selection frames \
  --frame-times 20260129114200 \
  --background-dirs /data/LFT-W02_data/pengxu/stage5_external_background/era5_roi,/data/LFT-W02_data/pengxu/stage5_external_background/gfs_historical_aws_npz,/data/LFT-W02_data/pengxu/stage5_external_background/merra2_roi_npz \
  --disable-internal-stage5-background \
  --background-top-k 1 \
  --iterations 4 \
  --holdout-every 4 \
  --make-plots 1
```

### 推荐命令 3：v3 structured 两帧重跑

```bash
/opt/miniconda3/bin/python stage/stage5_pinn_diffusion_refine.py \
  --stage4-dir /data/LFT-W02_data/pengxu/stage4_output_v2 \
  --summary /data/LFT-W02_data/pengxu/stage4_output_v2/stage4_summary.json \
  --out-dir /data/LFT-W02_data/pengxu/stage5_output_v1_internal_bg_test_v3_structured \
  --selection frames \
  --frame-times 20260129114200,20260206174200 \
  --background-dirs /data/LFT-W02_data/pengxu/stage5_external_background/era5_roi,/data/LFT-W02_data/pengxu/stage5_external_background/gfs_historical_aws_npz,/data/LFT-W02_data/pengxu/stage5_external_background/merra2_roi_npz \
  --internal-stage5-dir /data/LFT-W02_data/pengxu/stage5_output_v1_internal_bg_test_v3_structured \
  --background-relax-on-original-nonanchor 0 \
  --background-consistency-threshold 0.35 \
  --internal-background-expanded-weight 1.0 \
  --internal-background-near-anchor-weight 0.65 \
  --internal-background-original-weight 0.10 \
  --anchor-neighborhood-radius-xy 3 \
  --anchor-neighborhood-radius-z 1 \
  --direction-consistency-weight 0.12 \
  --direction-consistency-hazard-weight 0.08 \
  --direction-consistency-reference background_or_anchor_neighborhood \
  --iterations 4 \
  --holdout-every 4 \
  --make-plots 1
```

跑完重点看：

- `background_vector_rmse`
- `background_anchor_rmse_scaled`
- `background_anchor_cosine_mean`
- `direction_consistency_mean_after`
- `delta_speed_expanded_mean`

### 推荐命令 4：v3 full-ROI demo

```bash
/opt/miniconda3/bin/python stage/report_stage5_full_roi_background_demo.py \
  --stage5-dir /data/LFT-W02_data/pengxu/stage5_output_v1_internal_bg_test_v3_structured \
  --background-dir /data/LFT-W02_data/pengxu/stage5_external_background/era5_roi \
  --frame-time 20260129114200 \
  --out-dir /data/LFT-W02_data/pengxu/stage5_visualizations/stage5_full_roi_background_demo_v3_structured
```

再对 `20260206174200` 重跑一次：

```bash
/opt/miniconda3/bin/python stage/report_stage5_full_roi_background_demo.py \
  --stage5-dir /data/LFT-W02_data/pengxu/stage5_output_v1_internal_bg_test_v3_structured \
  --background-dir /data/LFT-W02_data/pengxu/stage5_external_background/era5_roi \
  --frame-time 20260206174200 \
  --out-dir /data/LFT-W02_data/pengxu/stage5_visualizations/stage5_full_roi_background_demo_v3_structured
```

重点看：

- `raw_vector_rmse_on_stage5_points`
- `scaled_vector_rmse_on_stage5_points`
- `background_speed_scale`

### 推荐命令 5：v3 shared-support comparison

```bash
/opt/miniconda3/bin/python stage/report_stage5_background_comparison.py \
  --stage4-dir /data/LFT-W02_data/pengxu/stage4_output_v2 \
  --stage5-dir /data/LFT-W02_data/pengxu/stage5_output_v1_internal_bg_test_v3_structured \
  --background-dirs /data/LFT-W02_data/pengxu/stage5_external_background/era5_roi,/data/LFT-W02_data/pengxu/stage5_external_background/gfs_historical_aws_npz,/data/LFT-W02_data/pengxu/stage5_external_background/merra2_roi_npz \
  --out-dir /data/LFT-W02_data/pengxu/stage5_visualizations/stage5_internal_bg_test_comparison_v3_structured \
  --frame-times 20260129114200,20260206174200 \
  --max-vectors 250
```

---

## 十二、服务器监控与日志查看

### 场景

- 看 Stage3/4 现在跑到哪
- 检查有没有卡死
- 看输出文件是否持续增长

### 推荐入口文档

- `stage/handover_stage45_20260507/05_full_run_monitoring_checklist.md`
- `stage/handover_stage45_20260507/06_server_top10_monitor_commands.md`

### 最常用命令 1：看 Stage4 当前进度

```bash
LOG_DIR=/data/LFT-W02_data/pengxu/stage/logs_v2/full_full_fast_stage4_frozen_v1__stage4_only
LOG_FILE=$(ls "$LOG_DIR"/stage4*.log | head -n 1)
grep "\[Stage-4\]\[progress\]" "$LOG_FILE" | tail -n 3
```

### 最常用命令 2：看 Stage3 当前进度

```bash
LOG_DIR=/data/LFT-W02_data/pengxu/stage/logs_v2/full_S5_final_fast_full_v1__full_fast_multi_gpu
LOG_FILE=$(ls "$LOG_DIR"/stage3*.log | head -n 1)
grep "\[Stage-3\]\[progress\]" "$LOG_FILE" | tail -n 3
```

### 最常用命令 3：看 Stage4 最近帧诊断

```bash
LOG_DIR=/data/LFT-W02_data/pengxu/stage/logs_v2/full_full_fast_stage4_frozen_v1__stage4_only
LOG_FILE=$(ls "$LOG_DIR"/stage4*.log | head -n 1)
grep "\[Stage-4\]\[frame\]" "$LOG_FILE" | tail -n 3
grep "\[Stage-4\]\[diag\]" "$LOG_FILE" | tail -n 3
```

### 最常用命令 4：看输出文件增长

```bash
find /data/LFT-W02_data/pengxu/stage3_output_v2/agents -maxdepth 1 -name 'frame_*_agents.json' | wc -l
find /data/LFT-W02_data/pengxu/stage4_output_v2 -maxdepth 1 -name 'frame_*.npz' | wc -l
```

---

## 十三、结果核对与摘要抽查

### 场景

- 想快速做知识库级抽查
- 想看每个阶段是否已经产出合理样例

### 推荐命令 1：Stage2 高风帧

```bash
python - <<'PY'
import json
from pathlib import Path
p=Path('/data/LFT-W02_data/pengxu/stage2_output/stage2_summary.json')
data=json.loads(p.read_text())
for r in sorted(data, key=lambda x: x.get('wind_voxels', 0), reverse=True)[:10]:
    print(r['time_str'], r['wind_voxels'], r['motion_voxels'], r['amdar_voxels'], r['turb_voxels'])
PY
```

### 推荐命令 2：Stage3 高 agent / 高边数帧

```bash
python - <<'PY'
import json
from pathlib import Path
p=Path('/data/LFT-W02_data/pengxu/stage3_output_v2/stage3_summary.json')
data=json.loads(p.read_text())
for key in ['valid_flight_agents','flight_ff_allowed_edges','flight_ff_wind_edges']:
    print('\\nTOP', key)
    for r in sorted(data, key=lambda x: x.get(key, 0), reverse=True)[:5]:
        print(r['time_str'], r.get(key))
PY
```

### 推荐命令 3：Stage4 高 hazard / 高 coverage 帧

```bash
python - <<'PY'
import json
from pathlib import Path
p=Path('/data/LFT-W02_data/pengxu/stage4_output_v2/stage4_summary.json')
data=json.loads(p.read_text())
for key in ['recon_coverage_ratio','hazard_alert_voxels','temporal_fill_voxels','support_expand_voxels']:
    print('\\nTOP', key)
    for r in sorted(data, key=lambda x: x.get(key, 0), reverse=True)[:5]:
        print(r['time_str'], r.get(key), r.get('recon_filled_voxels'), r.get('recon_conf_mean'))
PY
```

### 推荐命令 4：Stage5 关键帧 summary

```bash
python -m json.tool /data/LFT-W02_data/pengxu/stage5_output_v1_historical_gfs_keyframes/stage5_summary.json
```

看什么：

- `refined_voxels`
- `expanded_voxels`
- `anchor_rmse_after`
- `heldout_anchor_rmse_after`
- `background_vector_rmse`
- `background_speed_bias`

---

## 十四、文档使用关系

如果你已经知道自己要做什么：

- 先看本文件
- 直接跳到对应场景

如果你还不知道脚本和目录关系：

- 先看 `00_overview.md`
- 再看 `01_stage34_pipeline.md`
- 再回本文件找命令

如果你要看完整命令而不是场景入口：

- 去 `07_full_command_catalog.md`

如果你要看运行监控细节：

- 去 `05_full_run_monitoring_checklist.md`
- 去 `06_server_top10_monitor_commands.md`
