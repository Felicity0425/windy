# S4-A Metrics-Only 200帧试跑报告

## 结论

- 本轮按 `S4-A` 的轻量 metrics-only 口径完成 200 帧、25 worker 对照，不生成 3D NPZ。
- 两个候选均不满足 promotion gate，不能晋级 default 或 5614 formal。
- `s4a_obs_error_downweight_only` 有弱正信号：frame mean RMSE、P95/P99、12km+、light/floor10 均略好；但 weighted RMSE 变差，硬门失败。
- `s4a_obs_error_full_weight` 风险更高：weighted RMSE 变差更明显，且 12km+ 破门。

## 运行

- baseline: `tp26_baseline_metrics`
- candidate A: `s4a_obs_error_downweight_only`
- candidate B: `s4a_obs_error_full_weight`
- frame list: `stage45_oi_cma_m1_200_25w_20260614/assets/stage4_validation_frame_times_200.txt`
- workers: 25
- output size: about 19M
- NPZ files written: 0

## 关键数值

| metric | tp26 | downweight | full-weight |
| --- | ---: | ---: | ---: |
| frame mean RMSE | 8.403722 | 8.400417 | 8.477330 |
| frame mean MAE | 7.200442 | 7.223910 | 7.322168 |
| weighted RMSE | 14.868531 | 15.049371 | 15.305642 |
| frame P95 RMSE | 27.989640 | 27.975163 | 26.273547 |
| frame P99 RMSE | 58.783770 | 58.746097 | 58.573847 |
| 12km+ vector RMSE | 20.012159 | 19.980173 | 20.121955 |
| light wind RMSE | 5.191237 | 5.051847 | 4.992278 |
| floor10 relative MAE | 0.286411 | 0.282887 | 0.285153 |

## Gate 结果

- `downweight`: FAIL
  - failed gate: `weighted_rmse_no_worse`
  - weighted RMSE: 14.868531 -> 15.049371
- `full_weight`: FAIL
  - failed gate: `weighted_rmse_no_worse`
  - failed gate: `alt_12km_plus_vector_rmse_no_worse`
  - weighted RMSE: 14.868531 -> 15.305642
  - 12km+ vector RMSE: 20.012159 -> 20.121955

## 诊断解释

- 全局观测误差加权不是安全的 S4-A 晋级路径。
- downweight 对中等错误帧有改善：baseline RMSE 10-20 组从 13.958053 降到 13.166583。
- downweight 对高错误帧有反噬：baseline RMSE >20 组从 39.203224 升到 39.926942。
- full-weight 对 low-error 和 high-error 两端都更不稳定，因此不应继续。
- 目前可保留的信号是：轻风、floor10、P95/P99 对保守降权有轻微收益；但不能用全局开关进入 official branch。

## 下一步建议

- 不推进 `S4-A obs_error_weighted` 到 5614。
- 若继续 S4-A，只做更窄机制：仅在 light/moderate 或 baseline RMSE 10-20 类似风险层启用降权，且必须硬禁止 60mps+、6-12km 误伤。
- 更符合方案顺序的下一步是转 `S4-B` 或 `S4-C`：
  - `S4-B`: 处理 role-gap / vertical-gap / high-altitude 的受约束局地化。
  - `S4-C`: 处理 timeconf 0.4-0.6 的时间权重校准。

