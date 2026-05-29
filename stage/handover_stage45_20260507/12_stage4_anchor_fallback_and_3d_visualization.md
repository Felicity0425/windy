# Stage4 Primary Anchor Fallback 与 3D 可视化交接

## 这份文档的作用
这份文档记录 Stage4 冻结边界内最近一次低风险增强：

- `wind_primary` 高重叠去重后的保底直接锚点 fallback
- 代表帧 2D / 3D 风场 PNG 诊断脚本
- 当前全量 Stage4 结果、小样本 S5 校准结果和后续接手方式

它补充 `02_stage4_modification_and_freeze.md`，但不改变那份文档里的主结论：Stage4 仍应以冻结为主，不继续暴力追求 coverage。

---

## 一、当前新增代码位置

### 1. Stage4 主代码
真实主线仍然是：

- `stage/stage4_pack_v2.py`
- 不是 `stage/stage4_pack.py`

本轮新增逻辑在：

- `_dedupe_primary_wind_source()`
- frame diag 日志
- `stage4_summary.json` 每帧 summary 输出

### 2. 可视化脚本
新增独立只读脚本：

- `stage/report_stage4_recon_slices.py`
- `stage/report_stage4_geo_wind_visualization.py`

该脚本不参与 Stage3 / Stage4 主链，不修改重构结果，只读已有 `stage4_output_v2` 或指定 Stage4 输出目录。

---

## 二、为什么要加 primary anchor fallback

Stage4 之前已有 `wind_grouped` 与 `amdar_grouped` / `turb_grouped` 高重叠去重逻辑。  
这个逻辑的目的不是删风源，而是避免同一批 wind voxels 被 `wind_grouped + AMDAR/TURB 分源` 重复计权。

但在某些帧中会出现一个问题：

- `wind_grouped` 非空
- 与 AMDAR/TURB 的 `overlap_ratio >= 0.92`
- 去重后 `wind_primary` 被清空

这会让 raw wind 明明存在，却没有任何 primary direct wind anchors 进入后续解释链。  
因此本轮只加了一个保守 fallback：当高重叠去重把 primary 清空时，保留少量低权重代表性 wind primary anchors。

这个改动的目标是提升 direct anchor 可解释性，不是为了显著提高 coverage。

---

## 三、fallback 规则

默认启用：

```bash
WIND_STAGE4_ENABLE_PRIMARY_ANCHOR_FALLBACK=1
```

核心规则：

- 只在 `wind_grouped` 非空且高重叠去重后为空时触发
- 默认最多保留 `min(8, max(1, ceil(0.08 * wind_count)))` 个点
- 优先按 `qc_weight + obs_conf` 选择代表性点
- fallback 点统一乘低权重 `0.18`
- 不改变 Stage3，不改变 Stage4 输入输出目录关系

新增环境变量：

```bash
WIND_STAGE4_ENABLE_PRIMARY_ANCHOR_FALLBACK=1
WIND_STAGE4_PRIMARY_ANCHOR_FALLBACK_RATIO=0.08
WIND_STAGE4_PRIMARY_ANCHOR_FALLBACK_MAX=8
WIND_STAGE4_PRIMARY_ANCHOR_FALLBACK_WEIGHT=0.18
```

新增 summary 字段：

```text
wind_primary_fallback_voxels
```

新增 diag 日志字段：

```text
primary_fallback=<N>
```

---

## 四、小样本 S5 FinalFast 校准结论

校准输出目录：

```text
/data/LFT-W02_data/pengxu/stage4_output_runs_v2/S5_finalfast_anchorfallback_v1
```

校准日志目录：

```text
/data/LFT-W02_data/pengxu/stage/logs_v2/indices_S5_finalfast_anchorfallback_v1__stage4_only
```

校准帧：

```text
18,1436,3853,6228,7041
```

日志确认的关键配置：

```text
fast_mode=1
output_profile=fast
quality_profile=fast_balanced
quality_expand_enabled=0
omp_threads=6
mkl_threads=6
numexpr_threads=6
polars_threads=6
```

需要特别注意：

```text
gpu_mode=1 gpu_enabled=0 gpu_device=cpu
```

也就是说这轮校准虽然请求了 GPU，但实际运行环境里 CUDA 没有启用。正式全量 `S5 FinalFast` 前必须先确认 CUDA 可见性。

fallback 前后 5 帧对比结论：

- `20260129174200`：`wind_primary` 从 0 变为 4，`wind_primary_fallback_voxels=4`
- `20260208234200`：`wind_primary` 从 0 变为 1，`wind_primary_fallback_voxels=1`
- `20260222063600`：`wind_primary` 从 0 变为 2，`wind_primary_fallback_voxels=2`
- 平均 coverage 基本不变：`0.053712 -> 0.053712`
- 平均 confidence 小幅提升：`0.183249 -> 0.183872`
- 未出现异常 coverage 跳变
- 所选样本里 `anchor_restore` / `anchor_force` 未明显变化

解释：fallback 按预期只恢复少量 direct wind anchors，提高解释性，不把 coverage 当唯一目标。

---

## 五、当前全量 Stage4 结果定位

用户已有一次全量运行：

```text
/data/LFT-W02_data/pengxu/stage/logs_v2/full_full_fast_stage4_frozen_v1__stage4_only
```

对应 Stage4 输出：

```text
/data/LFT-W02_data/pengxu/stage4_output_v2
```

这次运行应作为 full-aux 风格全量 Stage4 诊断基线消化，不建议直接作为论文最终 `S5 FinalFast` 主结果引用。

从 `stage4_summary.json` 粗看：

- 总帧数：`7395`
- 触发重构帧：`4244`
- 非空重构帧：`4243`
- `triggered=1` 但 `recon_filled_voxels=0` 的异常帧：`1`
- 全部帧平均 coverage：`0.030367`
- 全部帧平均 confidence：`0.150769`
- 非空重构帧平均 coverage：`0.052926`
- 非空重构帧平均 confidence：`0.262771`

代表性极值帧：

- 最大 hazard：`idx=3338 time=20260206174200 hazard_alert_voxels=328`
- 最大 anchor_restore：`idx=3096 time=20260205173000 anchor_restore_voxels=16`
- 最大 anchor_force：`idx=76 time=20260124013600 anchor_force_voxels=1`
- 最大 temporal_fill：`idx=1376 time=20260129114200 temporal_fill_voxels=40`
- 最大 support_expand：`idx=2781 time=20260204095400 support_expand_voxels=18`

---

## 六、代表帧 2D / 3D 可视化

脚本：

```text
stage/report_stage4_recon_slices.py
```

默认输入：

```text
/data/LFT-W02_data/pengxu/stage4_output_v2
```

默认 summary：

```text
/data/LFT-W02_data/pengxu/stage4_output_v2/stage4_summary.json
```

默认输出：

```text
/data/LFT-W02_data/pengxu/stage4_visualizations/stage4_output_v2_representative
```

脚本只读 `sparse_lossless` NPZ 里的 sparse 字段：

```text
recon_idx
recon_u_val
recon_v_val
recon_conf_val
recon_mask_val
```

它不会展开完整 `31 x 2100 x 3100` dense 体，因此单帧内存可控。

### 推荐命令：当前全量结果代表帧

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

当前已生成：

```text
/data/LFT-W02_data/pengxu/stage4_visualizations/stage4_output_v2_representative
```

内容包括：

- `selected_frames.json`
- 每个代表帧 1 张 2D 六面板 PNG
- 非空重构代表帧 1 张 3D scatter + quiver PNG

当前代表帧输出为 11 帧，其中 9 帧有 3D PNG，2 帧因空重构跳过 3D。

### 推荐命令：S5 fallback 小样本 3D

```bash
/opt/miniconda3/bin/python stage/report_stage4_recon_slices.py \
  --stage4-dir /data/LFT-W02_data/pengxu/stage4_output_runs_v2/S5_finalfast_anchorfallback_v1 \
  --summary /data/LFT-W02_data/pengxu/stage4_output_runs_v2/S5_finalfast_anchorfallback_v1/stage4_summary.json \
  --out-dir /data/LFT-W02_data/pengxu/stage4_visualizations/S5_finalfast_anchorfallback_v1 \
  --selection representative \
  --viz-mode 3d \
  --max-vectors 250 \
  --z-exaggeration 40 \
  --min-conf 0.0
```

当前已生成 5 个代表记录，其中 4 帧有 3D PNG，`20260218211800` 因 `recon_filled_voxels=0` 跳过 3D。

---

## 七、真实地理坐标可视化

新增脚本：

```text
stage/report_stage4_geo_wind_visualization.py
```

默认输出：

```text
/data/LFT-W02_data/pengxu/stage4_visualizations/stage4_output_v2_geo_representative
```

该脚本用固定地理映射把 Stage4 sparse reconstruction 画到经纬度 / 高度坐标：

```text
lat = 54.2 - (y + 0.5) * (54.2 - 12.2) / H
lon = 73.0 + (x + 0.5) * (135.0 - 73.0) / W
alt_km = z * 0.5
```

每个非空代表帧输出：

- `*_country_roi.png`：全国雷达网格背景 + ROI 框
- `*_roi_layers.png`：ROI 内多高度层风矢量
- `*_roi_3d.png`：ROI 内经纬度 / 高度 3D 风矢量

当前已生成 11 个代表帧记录，其中 9 帧有地理 PNG，2 个空重构帧只写入 `selected_frames_geo.json`。

重要解释边界：

- 这不是全国完整三维风场
- 这是全国雷达网格上的稀疏局部三维风场重构
- 不做全国范围无约束插值
- 风矢量只在实际重构点 / ROI 内展示

推荐命令：

```bash
/opt/miniconda3/bin/python stage/report_stage4_geo_wind_visualization.py \
  --stage4-dir /data/LFT-W02_data/pengxu/stage4_output_v2 \
  --summary /data/LFT-W02_data/pengxu/stage4_output_v2/stage4_summary.json \
  --out-dir /data/LFT-W02_data/pengxu/stage4_visualizations/stage4_output_v2_geo_representative \
  --selection representative
```

---

## 八、Stage5 v1 独立 refinement

新增脚本：

```text
stage/stage5_pinn_diffusion_refine.py
```

定位：

- 独立 Stage5 scaffold
- 只读 Stage4 sparse outputs
- 不覆盖 Stage4
- 不接入 `run_stage34_workflow_v2.sh`
- 当前不是训练好的 neural diffusion
- 当前是 `PINN-proxy + diffusion-style` ROI 局部 refinement

默认输出：

```text
/data/LFT-W02_data/pengxu/stage5_output_v1
```

smoke test 已完成：

```text
/data/LFT-W02_data/pengxu/stage5_output_v1_smoke
```

结果：

- `20260129174200` 成功输出 Stage5 sparse NPZ 和 3D 预览图
- `20260218211800` 因 Stage4 空重构被跳过
- `20260129174200` 从 Stage4 `198` 个体素扩展到 Stage5 `326` 个 ROI refined 体素
- anchor RMSE after 约 `0.0957`

更多细节见：

```text
stage/handover_stage45_20260507/13_stage5_and_real_3d_wind_plan.md
```

---

## 九、接下来建议

### 1. 先用 PNG 消化当前重构形态
优先查看：

- 高 coverage 合理帧
- 中位 coverage 触发帧
- 最大 hazard 帧
- 最大 anchor_restore 帧
- `triggered=1` 但空重构帧

重点不是看图好不好看，而是确认：

- sparse 重构是否集中在合理空间区域
- confidence 是否和风矢量密度相匹配
- hazard / anchor_restore / temporal_fill 触发帧形态是否可解释
- 空重构帧是否确实是低信息帧或触发逻辑边界帧

### 2. 正式 S5 FinalFast 全量前先确认配置
必须在日志中看到：

```text
fast_mode=1
output_profile=fast
quality_profile=fast_balanced
quality_expand_enabled=0
omp_threads=6
```

如果要求 GPU，还必须看到：

```text
gpu_enabled=1
gpu_device=cuda:0
```

Stage4 运行建议使用：

```text
/data/LFT-W02_data/pengxu/.conda/envs/windy310/bin/python
```

可视化建议使用：

```text
/opt/miniconda3/bin/python
```

原因是当前环境里 `windy310` 有 `polars/torch`，系统 Python 有 `matplotlib`。

### 3. 再跑真正 full_fast_multi_gpu 主结果
只有在小样本确认无误后，才建议启动真正的 `RUN_PHASE=full_fast_multi_gpu` 全量主结果。  
跑完后再补 `reports_only` 或自定义 `RUN_PHASES` 生成：

- `sparse_metrics`
- `outliers`
- `readiness`

---

## 十、新窗口接手提醒

如果在新窗口继续工作，务必先确认这些边界：

- Stage3 正式输出仍是 `stage3_output_v2`
- Stage4 正式输出仍是 `stage4_output_v2`
- 当前主线代码仍是 `stage3_agents_v2.py` / `stage4_pack_v2.py`
- `stage3_agents.py` / `stage4_pack.py` 不是当前主线
- Stage4 默认不做多进程分片，因为依赖时序状态
- primary anchor fallback 是保守解释性增强，不是新的激进重构方案
- 当前全量 `full_fast_stage4_frozen_v1 stage4_only` 是诊断基线，不是最终论文 `S5 FinalFast`
- 代表帧 3D 可视化是静态 PNG，不是 MP4 或交互 HTML
- 地理坐标可视化脚本是 `stage/report_stage4_geo_wind_visualization.py`
- Stage5 v1 脚本是 `stage/stage5_pinn_diffusion_refine.py`
- Stage5 当前是独立 scaffold，不是 Stage4 主链，也不是训练完成的 diffusion 模型
