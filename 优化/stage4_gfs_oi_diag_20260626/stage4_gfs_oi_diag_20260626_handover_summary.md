# stage4_gfs_oi_diag_20260626 交接总结

生成时间：2026-06-26  
适用对象：新窗口执行智能体 / 项目交接阅读者  
目标：把本窗口已经完成的 `GFS 背景补层 + verify + S4-OI-DIAG + 12km 截断诊断 + 可视化修正` 一次说明清楚，避免新窗口重新摸索。

---

## 0. 一句话结论

本窗口已经把 `GFS` 从“200 帧背景已下载完成但高空覆盖不足”的状态，推进到：

```text
1. 21层 / 1000..100 hPa / 顶层约 15.80 km
2. verify_gfs_background = ready_for_s4_oi_diag = true
3. S4-OI-DIAG 已完成 report-only 诊断
4. 结论：GFS 可以作为 diagnostic / weak background，但不适合直接进入 official OI 分支
5. 若把业务口径改成 <=12 km，baseline 观感会明显改善，但这是“改评估范围”，不是“官方全高度问题已解决”
```

---

## 1. 本窗口实际完成的工作

### 1.1 GFS 高层补齐，不重复下载已有层

原始 `GFS` 目录最初只有 `1000..200 hPa` 共 `19` 层，最高约 `11.78 km`，导致：

```text
supports_12km_plus = false
ready_for_s4_oi_diag = false
```

本窗口对以下脚本做了增量修改：

- [download_stage5_gfs_aws_cached_batch.py](/data/LFT-W02_data/pengxu/stage/download_stage5_gfs_aws_cached_batch.py)
- [stage4_gfs_historical_background_200_20260625.sh](/data/LFT-W02_data/pengxu/workflow/plan/stage4_gfs_historical_background_200_20260625.sh)

修改点：

```text
1. 支持检查已有 cache_npz 的 pressure_hpa 层集合
2. 若已有低层，只补缺失层，不重复下载整份 source
3. 支持 partial npz 转换后与旧 cache_npz 按 pressure level 合并
4. 当 cache 层集合变化时，自动刷新对应 frame npz
5. shell 脚本把 pressure levels 显式改为：
   1000,975,950,925,900,850,800,750,700,650,600,550,500,450,400,350,300,250,200,150,100
```

最终当前盘上 `GFS` frame NPZ 状态已变为：

```text
levels_count = 21
pressure_hpa = 1000..100
alt_km_max ≈ 15.7995
```

对应目录：

- [raw_grib](/data/LFT-W02_data/pengxu/优化/stage4_cma_m1_light_demo_20260625/gfs_historical_aws_200/raw_grib)
- [cache_npz](/data/LFT-W02_data/pengxu/优化/stage4_cma_m1_light_demo_20260625/gfs_historical_aws_200/cache_npz)
- [npz](/data/LFT-W02_data/pengxu/优化/stage4_cma_m1_light_demo_20260625/gfs_historical_aws_200/npz)
- [gfs_historical_aws_200_resume.log](/data/LFT-W02_data/pengxu/优化/stage4_cma_m1_light_demo_20260625/logs/gfs_historical_aws_200_resume.log)

### 1.2 新增并重跑 `verify_gfs_background`

新增脚本：

- [verify_gfs_background.py](/data/LFT-W02_data/pengxu/stage/centralized_v1/core/verify_gfs_background.py)
- [stage4_gfs_oi_diag_20260626.sh](/data/LFT-W02_data/pengxu/workflow/plan/stage4_gfs_oi_diag_20260626.sh)

最终重跑后的正式结果：

- [gfs_background_verify_report_200.json](/data/LFT-W02_data/pengxu/优化/stage4_gfs_oi_diag_20260626/reports/gfs_background_verify_report_200.json)
- [gfs_background_verify_report_200.md](/data/LFT-W02_data/pengxu/优化/stage4_gfs_oi_diag_20260626/reports/gfs_background_verify_report_200.md)

关键结论：

```text
expected_frame_count = 200
frame_npz_count = 200
cache_npz_count = 178
manifest_unique_source_count = 178
failed_count = 0
all_frame_shapes_u/v = (21, 81, 45)
all_axes_monotonic = true
max_nan_fraction_u/v = 0
supports_12km_plus = true
ready_for_s4_oi_diag = true
```

注意：

```text
本目录里最早的一版 verify 报告曾记录过 19 层 / 11.78 km 的状态，
但当前已经基于补层后的 21 层背景重跑并覆盖为最终结果。
新窗口以后请以当前 json/md 为准。
```

### 1.3 新增并重跑 `S4-OI-DIAG`

新增脚本：

- [centralized_stage4_oi_diag_report.py](/data/LFT-W02_data/pengxu/stage/centralized_v1/core/centralized_stage4_oi_diag_report.py)

最终重跑后的正式结果：

- [s4_oi_diag_gfs_200.json](/data/LFT-W02_data/pengxu/优化/stage4_gfs_oi_diag_20260626/reports/s4_oi_diag_gfs_200.json)
- [s4_oi_diag_gfs_200.md](/data/LFT-W02_data/pengxu/优化/stage4_gfs_oi_diag_20260626/reports/s4_oi_diag_gfs_200.md)
- [s4_oi_diag_gfs_200_train_strata.csv](/data/LFT-W02_data/pengxu/优化/stage4_gfs_oi_diag_20260626/reports/s4_oi_diag_gfs_200_train_strata.csv)
- [s4_oi_diag_gfs_200_holdout_strata.csv](/data/LFT-W02_data/pengxu/优化/stage4_gfs_oi_diag_20260626/reports/s4_oi_diag_gfs_200_holdout_strata.csv)
- [00_rerun_after_high_level_refresh.log](/data/LFT-W02_data/pengxu/优化/stage4_gfs_oi_diag_20260626/logs/00_rerun_after_high_level_refresh.log)

关键总体结果：

```text
train innovation:
  inside_background_count = 154332
  outside_background_count = 0
  vector RMSE = 39.3400 m/s
  vector MAE  = 33.8918 m/s
  mean obs_influence_proxy = 0.1722

strict holdout background:
  inside_background_count = 530
  outside_background_count = 0
  vector RMSE = 35.2337 m/s
  vector MAE  = 29.7866 m/s
  departures join hit rate = 1.0
```

关键分层结论：

```text
conditionally usable strata:
  0-3km
  3-6km

high-risk strata:
  12km+
  6-9km
  9-12km
  count_0
  count_1
  count_ge2
  gap_10_30
  gap_ge30
  gap_lt10
```

其中最需要记住的数字是：

```text
holdout altitude RMSE:
  0-3km  = 13.07
  3-6km  = 22.76
  6-9km  = 30.44
  9-12km = 38.95
  12km+  = 39.16
```

因此当前 `GFS` 的角色应定义为：

```text
diagnostic background / weak background
```

而不是：

```text
ready-to-blend official strong background
```

### 1.4 新增 `12km+` 截断诊断脚本

新增脚本：

- [centralized_stage4_altitude_cutoff_report.py](/data/LFT-W02_data/pengxu/stage/centralized_v1/core/centralized_stage4_altitude_cutoff_report.py)

新产物：

- [stage4_altitude_cutoff_lt12km_baseline_200.json](/data/LFT-W02_data/pengxu/优化/stage4_altitude_cutoff_20260626/reports/stage4_altitude_cutoff_lt12km_baseline_200.json)
- [stage4_altitude_cutoff_lt12km_baseline_200.md](/data/LFT-W02_data/pengxu/优化/stage4_altitude_cutoff_20260626/reports/stage4_altitude_cutoff_lt12km_baseline_200.md)
- [stage4_point_departures_lt12km.csv](/data/LFT-W02_data/pengxu/优化/stage4_altitude_cutoff_20260626/reports/stage4_point_departures_lt12km.csv)
- [stage4_point_departures_ge12km.csv](/data/LFT-W02_data/pengxu/优化/stage4_altitude_cutoff_20260626/reports/stage4_point_departures_ge12km.csv)

关键结论：

```text
总点数 = 530
12km+ 点数 = 222 (41.89%)
但 12km+ 贡献 SSE = 76.18%

全高度 baseline:
  vector RMSE = 14.7690
  vector MAE  = 6.8545
  frame P95   = 27.9861
  frame P99   = 58.7838

只看 <12km:
  vector RMSE = 9.4552
  vector MAE  = 5.6532
  frame P95   = 20.9539
  frame P99   = 39.0449
```

但要特别注意：

```text
light wind 5-15 m/s 并没有一起变好，反而略差：
  all-alt   RMSE = 5.1959
  <12km     RMSE = 5.4589
```

这说明：

```text
“去掉 12km+ 后整体指标好看很多” 是真的，
但它本质上是“重定义业务范围”，不是“全高度官方问题已经解决”。
```

### 1.5 改进了 S4-CMA-M1 代表帧可视化

用户指出原图无法直观看出 `confidence` 差别，因此本窗口修改了：

- [centralized_report_stage4_slices.py](/data/LFT-W02_data/pengxu/stage/centralized_v1/core/centralized_report_stage4_slices.py)

新增：

```text
1. reliability confidence 单独切片
2. display confidence 单独切片
3. display source class 单独切片
   - green = official support
   - red   = low-confidence background fill
   - white = outside recon mask
```

新版代表图：

- [20260131123000_centralized_stage4_slices.png](/data/LFT-W02_data/pengxu/优化/stage4_cma_m1_light_demo_20260625/representative_visuals/20260131123000_centralized_stage4_slices.png)
- [20260131123000_centralized_stage4_diagnostics.png](/data/LFT-W02_data/pengxu/优化/stage4_cma_m1_light_demo_20260625/representative_visuals/20260131123000_centralized_stage4_diagnostics.png)

这个修改不影响 official RMSE/MAE，只是把 `display-only fill` 的来源和置信度解释得更清楚。

---

## 2. 本窗口新增或修改的关键代码文件

### 2.1 新增

- [stage/centralized_v1/core/verify_gfs_background.py](/data/LFT-W02_data/pengxu/stage/centralized_v1/core/verify_gfs_background.py)
- [stage/centralized_v1/core/centralized_stage4_oi_diag_report.py](/data/LFT-W02_data/pengxu/stage/centralized_v1/core/centralized_stage4_oi_diag_report.py)
- [stage/centralized_v1/core/centralized_stage4_altitude_cutoff_report.py](/data/LFT-W02_data/pengxu/stage/centralized_v1/core/centralized_stage4_altitude_cutoff_report.py)
- [workflow/plan/stage4_gfs_oi_diag_20260626.sh](/data/LFT-W02_data/pengxu/workflow/plan/stage4_gfs_oi_diag_20260626.sh)

### 2.2 修改

- [stage/download_stage5_gfs_aws_cached_batch.py](/data/LFT-W02_data/pengxu/stage/download_stage5_gfs_aws_cached_batch.py)
- [workflow/plan/stage4_gfs_historical_background_200_20260625.sh](/data/LFT-W02_data/pengxu/workflow/plan/stage4_gfs_historical_background_200_20260625.sh)
- [stage/centralized_v1/core/centralized_report_stage4_slices.py](/data/LFT-W02_data/pengxu/stage/centralized_v1/core/centralized_report_stage4_slices.py)

---

## 3. 对方法和结果的解释

### 3.1 为什么要分成两条线

当前项目必须区分两件事：

```text
1. official accuracy branch
2. product completeness / reliability branch
```

`CMA-RA` 更适合：

```text
display-only fill
完整场产品展示
低置信标注
```

`GFS forecast` 更适合：

```text
independent background candidate
innovation / OI 诊断
判断 OI 是否值得继续
```

### 3.2 这次 GFS 诊断真正说明了什么

它说明：

```text
GFS 作为“弱背景/诊断背景”是可用的，
因为它现在已经能和全部 200 帧 / 530 个 strict holdout 点对齐；
但它本身与 holdout 的差距仍然很大，
尤其在 12km+、6-9km、9-12km、低支撑和 role-gap 风险层上不够稳。
```

所以不能把它理解成：

```text
“背景一加进来就能直接把 official OI 做好”
```

更准确的理解是：

```text
“它可以作为 report-only / weak prior，
接下来只值得做非常受约束的 S4-OI-1a/1b 风格实验”
```

### 3.3 为什么 `<=12km` 看起来好很多

因为当前 baseline 的主要误差污染源确实是 `12km+`：

```text
12km+ 点数占比 = 41.89%
12km+ SSE 占比 = 76.18%
```

所以一旦把它剔除，整体 `RMSE / P95 / P99` 会立刻明显改善。  
但这不等于官方全高度任务被解决了，只能说明：

```text
如果产品范围改成“更贴近国内民航常用巡航层的 <=12 km”，
那么当前 Stage4 baseline 会显得更可接受。
```

---

## 4. 新窗口建议怎么接

### 4.1 若坚持全高度 official 目标

建议顺序：

```text
1. 不要把 GFS 直接进 official OI 分支
2. 只做 constrained S4-OI-1a / 1b
3. 把 12km+、light wind、count_0/1、gap_ge30 当成强保护层
4. 一旦 light wind / P95 / P99 变坏就立即停
```

### 4.2 若业务上允许改成 <=12km

建议顺序：

```text
1. 明确把 “<=12 km” 写成新评估范围
2. 用同一 cutoff 重新生成 baseline/gate/summary
3. 产品层默认弱化或关闭 12km+ 展示
4. official 与 product 都同步改口径，避免文档混用两套指标
```

### 4.3 与 S4-CMA-M1 的关系

当前最稳的组合其实是：

```text
official / diagnosis:
  baseline + GFS diagnostic

product / display:
  S4-CMA-M1 display-only weak background fill
```

也就是：

```text
“官方评价不混背景，产品展示允许低置信背景补全”
```

---

## 5. 建议新窗口优先阅读的文件

1. [gfs_background_verify_report_200.md](/data/LFT-W02_data/pengxu/优化/stage4_gfs_oi_diag_20260626/reports/gfs_background_verify_report_200.md)
2. [s4_oi_diag_gfs_200.md](/data/LFT-W02_data/pengxu/优化/stage4_gfs_oi_diag_20260626/reports/s4_oi_diag_gfs_200.md)
3. [stage4_altitude_cutoff_lt12km_baseline_200.md](/data/LFT-W02_data/pengxu/优化/stage4_altitude_cutoff_20260626/reports/stage4_altitude_cutoff_lt12km_baseline_200.md)
4. [stage4_cma_m1_light_demo_20260625_summary.md](/data/LFT-W02_data/pengxu/优化/stage4_cma_m1_light_demo_20260625/stage4_cma_m1_light_demo_20260625_summary.md)
5. [cma_independence_report.md](/data/LFT-W02_data/pengxu/优化/stage4_cma_m1_light_demo_20260625/reports/cma_independence_report.md)

---

## 6. 可直接复用的 rerun 命令

### 6.1 GFS 背景补层 / 刷新

```bash
bash /data/LFT-W02_data/pengxu/workflow/plan/stage4_gfs_historical_background_200_20260625.sh
```

### 6.2 GFS verify + OI-DIAG

```bash
bash /data/LFT-W02_data/pengxu/workflow/plan/stage4_gfs_oi_diag_20260626.sh
```

### 6.3 12km 截断评估

```bash
/data/LFT-W02_data/pengxu/.conda/envs/windy310/bin/python \
  /data/LFT-W02_data/pengxu/stage/centralized_v1/core/centralized_stage4_altitude_cutoff_report.py \
  --point-csv /data/LFT-W02_data/pengxu/centralized_v1_output/stage4_guardrail_display_fill_200_20260605_25w/tp26_thr11_preserve_metrics/stage4_point_departures.csv \
  --max-alt-m 12000 \
  --out-json /data/LFT-W02_data/pengxu/优化/stage4_altitude_cutoff_20260626/reports/stage4_altitude_cutoff_lt12km_baseline_200.json \
  --out-md /data/LFT-W02_data/pengxu/优化/stage4_altitude_cutoff_20260626/reports/stage4_altitude_cutoff_lt12km_baseline_200.md
```

