# Stage45 OI/CMA M1 200帧25进程试跑报告

## 结论

- 本次修改只影响展示层与兼容性读取，不改变官方 `recon_u/v/conf/mask` 和点检评估链路。
- `baseline_tp26_ground_recon` 与 `s4_cma_m1_display_fill` 都完成了 200 帧、25 worker 的全量试跑。
- 两组结果的官方逐帧指标完全一致，`rmse_vector`、`mae_vector`、`bias_u`、`bias_v`、`effective_reconstructed_*`、`confidence_*`、`strict_holdout_no_leakage` 的逐帧最大绝对差均为 0。
- M1 仅把展示层补成弱背景填充，`display_fill_is_official_accuracy=False`，不会污染官方精度。

## 本次代码改动

- `centralized_stage4_ground_recon.py`
  - 兼容行式 `frame_times` 文本和 JSON 列表。
  - 增加 `background_independent_of_holdout` 透传与泄漏报告字段。
  - 子进程和主进程都能接收该标志。
- `centralized_stage4_sensitivity.py`
  - 同步增加 `background_independent_of_holdout` 透传。
- `centralized_cma_ra_virtual_radial_3dvar.py`
  - 同步修正 `frame_times` 读取兼容性。

## 运行记录

- smoke: `smoke_one_frame_display_fill`
  - 1 帧通过，确认展示层可工作，且官方准确率标志保持关闭。
- baseline: `baseline_tp26_ground_recon`
  - 200/200 帧完成，`display_fill_mode=off`。
  - 平均 `display_fill_active_voxels=216826.395`，`display_fill_background_voxels=0`。
- M1: `s4_cma_m1_display_fill`
  - 200/200 帧完成，`display_fill_mode=low_conf_background`。
  - 平均 `display_fill_active_voxels=12613125`，平均 `display_fill_background_voxels=12396298.605`。

## 对比结果

- 官方指标逐帧零差异。
- 代表帧 NPZ 抽检中，`recon_u_3d`、`recon_v_3d`、`recon_confidence_3d`、`recon_mask_3d` 的最大绝对差均为 0。
- M1 展示层覆盖的是全网格弱背景，不改官方重建：
  - `display_fill_active_voxels=12613125`
  - `display_fill_source` 只出现 `1/2`
  - `strict_holdout_no_leakage=True` 在 200 帧上全部成立

## 风险备注

- `background_independent_of_holdout` 目前仍是 `unknown`。
- `background_independence_confirmed=False`，所以不能把这次 M1 解释成“已证明与 holdout 完全独立”的结论。

