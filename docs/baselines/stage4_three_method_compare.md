# Stage4 三方法 200 帧严格 holdout 对比（2026-05-31）

本报告覆盖旧的 4 帧解释。样本为 `seed=20260531` 固定抽取的 200 个严格航空器 holdout 帧；官方评价只看 holdout 点，no-holdout 帧不参与本次官方 RMSE/MAE。CMA 仅作为弱背景/伪观测输入，不作为真值；motion 未作为风。

## 结论

- 200 帧结果与早先 4 帧小样本相反：TimePower15 平均 RMSE/MAE = 8.636/7.423 m/s，优于纯航空器 baseline 的 11.690/10.301 m/s。
- CMA 弱背景分支平均 RMSE/MAE = 9.377/8.017 m/s，优于纯航空器 baseline，但劣于 TimePower15；它不是稳定增益项。
- TimePower15 对 baseline 的逐帧胜负：143 胜 / 56 负 / 1 平，平均 RMSE 差值为 -3.053 m/s。
- CMA 对 TimePower15：66 胜 / 134 负 / 0 平，平均 RMSE 差值为 0.741 m/s。

## 方法总表

| method | frames | holdout pts | frame RMSE | frame MAE | median RMSE | p95 RMSE | holdout-weighted RMSE | strict | motion-as-wind |
|---|---:|---:|---:|---:|---:|---:|---:|---|---|
| baseline | 200 | 530 | 11.690 | 10.301 | 6.787 | 42.641 | 18.918 | True | False |
| timepower15 | 200 | 530 | 8.636 | 7.423 | 4.733 | 28.147 | 15.039 | True | False |
| cma | 200 | 530 | 9.377 | 8.017 | 5.952 | 24.329 | 14.964 | True | False |

## 分层结论

| grouping | group | frames | baseline RMSE | TimePower15 RMSE | CMA RMSE | TP-base | CMA-TP | TP wins | CMA wins vs TP |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| holdout_class | single_holdout | 57 | 11.259 | 8.741 | 8.413 | -2.518 | -0.328 | 39 | 23 |
| holdout_class | multi_holdout_2 | 53 | 10.440 | 7.289 | 7.913 | -3.150 | 0.624 | 38 | 17 |
| holdout_class | multi_holdout_ge3 | 90 | 12.699 | 9.363 | 10.850 | -3.335 | 1.486 | 66 | 26 |
| baseline_rmse_band | base_rmse_le6 | 88 | 3.854 | 4.249 | 5.495 | 0.395 | 1.246 | 47 | 23 |
| baseline_rmse_band | base_rmse_6_10 | 47 | 7.738 | 6.035 | 7.467 | -1.703 | 1.432 | 40 | 15 |
| baseline_rmse_band | base_rmse_10_20 | 38 | 13.972 | 8.514 | 10.395 | -5.458 | 1.881 | 32 | 13 |
| baseline_rmse_band | base_rmse_gt20 | 27 | 40.896 | 27.637 | 23.923 | -13.259 | -3.715 | 24 | 15 |

## 为什么会出现 TimePower15 输给纯航空器的帧

整体上 TimePower15 并不差；它输的帧主要是局部情形。当前对比里，TimePower15 把 XY 半径从 12/6 收到 8/4，并启用 current-priority adaptive 冲突规则和更强 current 权重，这会减少有效重建体素与低置信扩散填充。多数帧这能抑制过度外推，所以赢；但如果被 holdout 的点刚好依赖周边更宽的上下文支撑，收窄影响半径后就可能把有用上下文也压掉。

输给 baseline 的帧还常伴随 role-conflict 区域较大或局地分量差值高：adaptive 规则会保护当前帧观测、削弱上下文；若当前观测稀疏或与 holdout 点不在同一局地结构上，纯航空器 baseline 的宽核平滑反而更接近 holdout。也就是说，baseline 有时赢不是因为物理更强，而是因为宽核偶然把邻近飞机点外推到了被遮蔽点。

CMA 分支的主要问题也很清楚：它填满全域背景，低置信空洞减少为 0，但背景场更平滑、更大尺度。对缺测或 baseline 崩坏的帧会兜底；对已经由 TimePower15 局地观测约束得很好的帧，会把重构拉向大尺度背景，损害局地航空器 holdout。

## 代表帧

| order | time_str | reason | baseline RMSE | TimePower15 RMSE | CMA RMSE | TP-base | CMA-TP |
|---:|---|---|---:|---:|---:|---:|---:|
| 1 | 20260206074200 | TimePower15 strongest improvement over pure aircraft baseline | 74.105 | 3.265 | 5.221 | -70.841 | 1.957 |
| 2 | 20260125124200 | Pure aircraft baseline strongest win over TimePower15 | 4.132 | 32.594 | 8.602 | 28.462 | -23.991 |
| 3 | 20260205190000 | CMA weak background strongest improvement over TimePower15 | 86.000 | 86.000 | 32.619 | 0.000 | -53.381 |
| 4 | 20260216015400 | CMA weak background strongest degradation vs TimePower15 | 32.713 | 29.007 | 66.290 | -3.706 | 37.283 |
| 5 | 20260126090000 | Near 6 m/s boundary / method ranking-sensitive case | 5.999 | 2.230 | 5.401 | -3.769 | 3.171 |
| 6 | 20260223133000 | High-error multi-holdout stress case | 117.236 | 108.858 | 109.389 | -8.377 | 0.530 |

## 输出文件

- `three_method_200_frame_summary.csv`
- `three_method_pairwise_rmse_deltas.csv`
- `three_method_stratified_pairwise.csv`
- `timepower15_win_loss_feature_means.csv`
- `three_method_200_frame_merged.csv`
- `representative_frames_selected.csv`
- `representative_frames_selected.txt`
- `representative_npz_visual_validation.json`

## 代表帧 NPZ / 可视化

- NPZ:
  - `../representative_npz/aircraft_baseline/`
  - `../representative_npz/timepower15/`
  - `../representative_npz/cma_proxy_background/`
- Stage4 切片与诊断图:
  - `../representative_visuals/aircraft_baseline/`
  - `../representative_visuals/timepower15/`
  - `../representative_visuals/cma_proxy_background/`
- CMA proxy 背景场图:
  - `../representative_visuals/cma_proxy_field/`

校验结果：6 个代表帧在三条 Stage4 分支中均生成 NPZ；三条 Stage4 分支各 6 张切片图；CMA proxy 场 6 张图；代表帧 full NPZ 的 RMSE 与 200 帧轻量 CSV 的最大差值为 0.0。

注意：本轮 200 帧主对比为轻量指标输出；完整 NPZ 和可视化只对代表帧生成。
