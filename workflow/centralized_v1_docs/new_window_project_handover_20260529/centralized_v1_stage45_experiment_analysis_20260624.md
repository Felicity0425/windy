# centralized_v1 Stage45 实验分析上传版（2026-06-24）

## 1. 范围

本文整理三组已经完成的 Stage45 试验，目标是给 GitHub 保留一份小体积、可追踪、可复现的分析摘要，而不是上传完整原始 NPZ 产物。

纳入的试验：

1. `S4-CMA-M1 display-only`，200 帧，25 worker。
2. `S4-OI-DIAG report-only`，200 帧轻量诊断。
3. `S4-A metrics-only`，200 帧，25 worker。

不纳入的内容：

1. `centralized_v1_output/` 下的大体积重构 NPZ、shard 目录、代表性可视化图片。
2. 任何会把 CMA/CRA40 直接写入 official `recon_u/v/conf/mask` 的 M2 分支结果，因为本轮没有通过准入门。

## 2. 关键结论

### 2.1 S4-CMA-M1：通过，但仅限产品展示层

- 200/200 帧完成。
- `display_fill_mode=low_conf_background` 成功把低置信区域补成完整展示层。
- 官方 `recon_u/v/conf/mask` 与 baseline 逐帧完全一致。
- official 指标差值全部为 `0.0`。
- `strict_holdout_no_leakage=True` 在 200 帧全部成立。

结论：

`M1` 可以保留为“完整风场产品层”，但不能声称它提升了官方重构精度。它解决的是产品完整性，不是 official RMSE。

### 2.2 S4-OI-DIAG：完成诊断，但不允许进入 M2

- 200/200 帧完成。
- 不写任何 3D reconstruction NPZ。
- baseline Stage4 frame mean RMSE: `8.224309 m/s`
- train OMB RMSE: `38.628995 m/s`
- holdout report-only OMB RMSE: `34.615552 m/s`
- train OMB P95: `66.807629 m/s`
- `background_independent_of_holdout=unknown`

结论：

当前 CMA/CRA40 背景还不能进入 official OI/M2 分支。原因有两个：

1. 背景与 holdout 的独立性没有被证明。
2. train OMB RMSE 约为 baseline frame mean RMSE 的 `4.70x`，背景误差过大。

### 2.3 S4-A：存在弱局部信号，但整体失败

baseline 指标：

- frame mean RMSE: `8.403722`
- weighted RMSE: `14.868531`
- 12km+ vector RMSE: `20.012159`

候选 1，`s4a_obs_error_downweight_only`：

- frame mean RMSE: `8.400417`
- weighted RMSE: `15.049371`
- 结论：`FAIL`

候选 2，`s4a_obs_error_full_weight`：

- frame mean RMSE: `8.477330`
- weighted RMSE: `15.305642`
- 12km+ vector RMSE 也变差。
- 结论：`FAIL`

结论：

`S4-A` 的全局 obs-error / representation weighting 不能晋升。`downweight_only` 虽然在部分局部指标上有弱正信号，但破坏了 weighted RMSE 硬门；`full_weight` 风险更高。

## 3. 当前技术判断

基于这三组试验，Stage45 当前可接受的逻辑是：

1. 保留 `M1 display-only`，把“完整产品层”和“official 精度评估层”分开。
2. 暂停 `M2 / OI official fusion`，直到背景独立性和背景 OMB 同时满足更严格条件。
3. 不推进 `S4-A` 到 full-5614，也不应改成 default。
4. 后续主线应转向 `S4-B` 或 `S4-C`，而不是继续放大全局 CMA/OI 或全局 obs-error weighting。

## 4. 已纳入 GitHub 的分析文件

本次上传保留以下小体积分析工件：

1. `centralized_v1_output/stage45_oi_cma_m1_200_25w_20260614/analysis/experiment_report_20260614.md`
2. `centralized_v1_output/stage45_oi_cma_m1_200_25w_20260614/analysis/experiment_summary_20260614.json`
3. `centralized_v1_output/stage45_oi_diag_light_200_20260614/oi_diag_200/oi_diag_report.md`
4. `centralized_v1_output/stage45_oi_diag_light_200_20260614/oi_diag_200/oi_diag_summary.json`
5. `centralized_v1_output/stage45_s4a_metrics_200_25w_20260614/analysis/s4a_metrics_200_report_20260614.md`
6. `centralized_v1_output/stage45_s4a_metrics_200_25w_20260614/analysis/s4a_metrics_200_summary_20260614.json`

这些文件总量约 `36 KB`，足以支持复核结论，不会把数 GB 的原始输出带进仓库。
