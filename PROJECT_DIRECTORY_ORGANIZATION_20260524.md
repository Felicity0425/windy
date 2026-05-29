# 项目目录整理说明

## 这次整理的原则

这次没有采用“直接暴力搬空旧目录”的方式，而是采用：

```text
新分组目录 + 原路径兼容 symlink
```

原因很简单：

- 你的项目里有大量脚本、交接文档、报告直接写死了绝对路径；
- 如果直接移动目录，不留兼容层，主链和文档会同时断掉；
- 现在这种方式既能让目录结构清晰，又不破坏现有运行逻辑。

---

## 一、顶层整理结果

新的总分组目录在：

```text
/data/LFT-W02_data/pengxu/_organized_outputs
```

里面按功能分成：

### 1. datasets

```text
20260114
20260224
```

### 2. stage_outputs

```text
stage1_output
stage1_output copy
stage2_output
stage3_output
stage3_output_v2
stage4_output
stage4_output_v2
stage4_output_runs
stage4_output_runs_v2
stage4_speed_ab_runs
stage_shard_runs
stage5_external_background
```

### 3. stage_visualizations

```text
stage3_visualizations
stage4_visualizations
stage5_visualizations
teacher_discussion_assets
```

### 4. stage5_experiments

```text
stage5_output_v1_*
```

也就是说，所有 `Stage5` 的各种 demo / smoke / tuned / internal_bg_test / v3_structured 结果，都集中放在这一个组里。

### 5. assets_and_refs

```text
report
workflow
windpaper
```

### 6. training_and_misc

```text
training
__pycache__
```

---

## 二、stage/logs_v2 整理结果

`logs_v2` 现在按运行类型重新分组到了：

```text
/data/LFT-W02_data/pengxu/stage/logs_v2/_by_type
```

里面分成：

### 1. full_runs

```text
full_*
```

### 2. indices_runs

```text
indices_*
```

### 3. offset_runs

```text
offset_*
```

### 4. misc_runs

其他不符合上述前缀的目录。

同时旧的：

```text
/data/LFT-W02_data/pengxu/stage/logs_v2/<原目录名>
```

仍然存在为 symlink，所以以前的脚本和文档仍然能用。

---

## 三、stage 目录整理结果

`stage/` 里的源码主文件没有直接搬走，避免打断 import 和脚本调用。

但是我新增了一套清晰的组织视图：

```text
/data/LFT-W02_data/pengxu/stage/_organized_stage
```

它里面按职责分成：

### 1. `01_pipeline_entrypoints`

- `run_stage34_workflow.sh`
- `run_stage34_workflow_v2.sh`
- `run_stage4_speed_ab.py`
- `run_stage5_rolling_roi.py`

### 2. `02_core_stage_scripts`

- `stage1_prepare.py`
- `stage2_voxelize.py`
- `stage3_agents.py`
- `stage3_agents_v2.py`
- `stage4_pack.py`
- `stage4_pack_v2.py`
- `stage5_pinn_diffusion_refine.py`

### 3. `03_stage5_background_tools`

- `download_stage5_era5_roi.py`
- `download_stage5_gfs_gdas_roi.py`
- `download_stage5_gfs_aws_historical_roi.py`
- `download_stage5_merra2_roi.py`
- `stage5_background_utils.py`

### 4. `04_reporting_and_visualization`

- 所有 `report_stage*.py`

### 5. `05_configs_and_utils`

- `config.py`
- `pipeline_config.py`
- `pipeline_utils.py`
- `reconstruct_utils.py`
- `reconstruct_utils_v2.py`
- `agent_builder.py`
- `communication_builder.py`
- `validate_pipeline_constracts.py`
- `export_stage4_dataset.py`

### 6. `06_docs_and_handover`

- `handover_stage45_20260507`
- `meaning_explanations`

### 7. `07_legacy_and_misc`

- `README_stage_pipeline.txt`
- `hello.py`
- `realtime_wind_scaffold.py`
- `render_teacher_discussion_pdf.py`
- `generate_teacher_discussion_figures.py`
- `wind_reconstruction.py`
- `convert_excel_to_parquet_robust.py`
- `stage1_run.log`

### 8. `08_logs_views`

- `logs`
- `logs_v2`

这里全部是 symlink 视图，所以：

- 你可以用它来找文件；
- 但真实脚本路径还是原位置；
- 不会破坏现有主链。

---

## 四、哪些目录我故意没有“硬移动”

下面这些我没有彻底重命名，只做了归组或保留原位兼容：

1. `stage/` 下源码脚本  
   因为 import、脚本调用、文档引用都非常多。

2. `stage4_output_v2` / `stage3_output_v2` / `stage2_output` / `stage1_output`  
   这些是主线正式输出目录，文档和脚本引用太多。

3. `report/` 和 `workflow/`  
   它们虽然已经归入 `_organized_outputs/assets_and_refs`，但原路径必须继续保留。

---

## 五、当前建议的“以后怎么找东西”

以后如果只是找内容，不想记老路径，推荐优先从这里进入：

### 1. 看数据与输出

```text
/data/LFT-W02_data/pengxu/_organized_outputs
```

### 2. 看 stage 脚本

```text
/data/LFT-W02_data/pengxu/stage/_organized_stage
```

### 3. 看日志

```text
/data/LFT-W02_data/pengxu/stage/logs_v2/_by_type
```

---

## 六、后续如果还要进一步清理

下一轮最值得继续做的是：

1. 把明显废弃的 `stage5_output_v1_demo_*` 再归档到一个 `archive_stage5_demos` 组
2. 给 `stage4_output_runs_v2` 和 `stage/logs_v2` 做一份“运行名 -> 含义”索引表
3. 统一旧文档里还在引用的 `stage3_output` / `stage4_output` 老路径说明

当前这轮整理，重点是：

```text
先让目录有逻辑、能找东西、又不把项目跑坏
```
