# New Window Handover - Stage2/Stage3/Stage4

Use this as the first message for a new window:

```text
请先读：
1. workflow/centralized_v1_docs/README.md
2. workflow/centralized_v1_docs/stage2_stage3_full_process_explanation.md
3. workflow/centralized_v1_docs/stage2_figure_20260208124800_explanation.md
4. workflow/centralized_v1_docs/stage4_strict_holdout_logic_and_results.md
5. stage/handover_stage45_20260507/23_centralized_v1_new_window_handover.md

当前 centralized_v1 新主线已经完成 Stage1/Stage2/Stage3/stage4 小批量 demo：
Stage1 是 clean source + radar index preparation，
Stage2 是 all-in observation organization，
Stage3 是 Ground Center intake + confidence package。
Stage4 strict baseline 两帧和 expanded 10 帧已经跑通，用于严格 hold-out
重构与灵敏度检查。

Stage2 数据来自：
stage1_output/clean_wind.parquet、
stage1_output/clean_loc.parquet、
stage1_output/radar_index.json、
以及 radar_index.json.radar_path 指向的气象雷达拼图 PNG。

不要回旧 Stage4 冻结主线。
不要把 reference_center 当物理权重中心。
不要取消体素化。
不要现在全量跑，先继续 2-10 帧可信 demo。

当前 Stage2/Stage3 置信度口径：
time_conf = 0.5 ** (abs(delta_time_minutes) / 180)
space_conf = 1.0
joint_likelihood = obs_conf * time_conf

新增 quality_conf_diagnostic / density_conf_diagnostic / qc_flags
只是诊断字段，不参与当前 joint_likelihood，不默认删数据。

Stage1/2/3 当前可以暂时冻结接口进入 Stage4：
freeze = 暂不改数据契约和 demo 输出，不代表以后不能做 QC 或全量补跑。

下一步进入 Stage4 strict：
1. strict hold-out 只能从 wind_records 抽；
2. 抽出的真实点必须在融合前剔除；
3. 对每个目标 voxel 做 observation-to-target-voxel localization；
4. 输出 gt_u/gt_v/pred_u/pred_v/u_error/v_error/rmse/mae/bias；
5. 用切面图和逐点数字验证重构结果。
6. motion_records / context_motion_records 先只作覆盖诊断，不直接当风参与融合。

Stage4 新增：
1. localization_kernel = gaussian | gaspari_cohn；
2. confidence_mode 默认 diagnostic_only，可选 diagnostic_weighted；
3. 泄露校验强制执行，失败直接报错；
4. 10 帧 expanded 输出写到 stage4_center_strict_expanded，不覆盖旧 strict；
5. sensitivity 只输出表格，不保存每组大体积 3D NPZ。
```

Current verified outputs:

```text
Stage2:
C:\Users\exo\Desktop\windy\stage\centralized_v1_output\stage2_regenerated\stage2_multimodal_summary.json

Stage2 slices:
C:\Users\exo\Desktop\windy\stage\centralized_v1_output\stage2_regenerated\slices

Stage3:
C:\Users\exo\Desktop\windy\stage\centralized_v1_output\stage3_center\stage3_center_summary.json

Stage3 expanded:
C:\Users\exo\Desktop\windy\stage\centralized_v1_output\stage3_center_expanded\stage3_center_summary.json

Stage3 reports:
C:\Users\exo\Desktop\windy\stage\centralized_v1_output\stage3_center\reports

Stage4 strict:
C:\Users\exo\Desktop\windy\stage\centralized_v1_output\stage4_center_strict
C:\Users\exo\Desktop\windy\stage\centralized_v1_output\stage4_center_strict\slices

Stage4 strict expanded:
C:\Users\exo\Desktop\windy\stage\centralized_v1_output\stage4_center_strict_expanded

Stage4 sensitivity:
C:\Users\exo\Desktop\windy\stage\centralized_v1_output\stage4_center_strict_expanded\sensitivity

Stage2 visual encoding charts:
C:\Users\exo\Desktop\windy\stage\centralized_v1_output\stage2_regenerated\slices\stage2_visual_encoding_<time>.png

Stage4 diagnostics charts:
C:\Users\exo\Desktop\windy\stage\centralized_v1_output\stage4_center_strict\slices\<time>_centralized_stage4_diagnostics.png
```

Verified Stage3 demo:

```text
20260208124800:
  agents = 746
  label_candidates = 114
  context_wind_observations = 1284
  context_motion_observations = 38691
  trajectory_observations = 5175
  motion_observations = 4887

20260211060600:
  agents = 773
  label_candidates = 1
  context_wind_observations = 1079
  context_motion_observations = 38761
  trajectory_observations = 5247
  motion_observations = 4506
```

Current gate:

```text
Stage1 = pass
Stage2 = pass
Stage3 = pass
Go to Stage4 small-batch strict hold-out
Do not run full output yet
```

Stage4 strict method reminder:

```text
active fusion input = non-holdout current wind_records + context_wind_records
active_weight = obs_conf * time_conf * target_voxel_localization
default localization_kernel = gaussian
optional localization_kernel = gaspari_cohn
default confidence_mode = diagnostic_only
hold-out labels are answer keys and must not participate in fusion
PINN-proxy/diffusion-style low-confidence fill is enabled, but it is not a trained model yet
```

Verified Stage4 strict demo:

```text
20260208124800:
  wind_records_total = 114
  holdout_wind_records = 15
  fusion_current_wind_records = 99
  context_wind_records = 1284
  pre-refine voxels = 276198
  final voxels = 417438
  final domain fraction = 3.309553%
  bbox = lat 17.240-36.760, lon 106.360-118.280, alt 0-15000 m
  diffusion fill = 141240
  RMSE vector = 6.468737 m/s
  MAE vector = 5.422913 m/s

20260211060600:
  wind_records_total = 1
  holdout_wind_records = 1
  fusion_current_wind_records = 0
  context_wind_records = 1079
  pre-refine voxels = 217861
  final voxels = 339248
  final domain fraction = 2.689643%
  bbox = lat 19.000-37.480, lon 106.920-118.200, alt 500-15000 m
  diffusion fill = 121387
  RMSE vector = 3.390634 m/s
  MAE vector = 3.390634 m/s
  note = sparse-label pressure test
```

Stage4 slice images now show observation-supported voxels and low-confidence
fill separately. A block-like footprint means finite-radius localization plus
proxy gap fill, not proof that the real atmosphere is moving as one solid block.

Verified Stage4 expanded demo:

```text
frames = 10
sensitivity rows = 60
strict_holdout_no_leakage = true for all rows
motion_used_as_wind = false
mask_conf_positive_mismatch_voxels = 0 for all expanded Stage4 rows

20260206174200 and 20260207022400 are high-error frames in the expanded run.
Use them for diagnosis and sensitivity review before any full run.
```

Current full-run gate:

```text
Do not run full Stage2/Stage3/Stage4 yet.
Review expanded 10-frame metrics, Gaussian vs Gaspari-Cohn sensitivity,
and high-error frame diagnostics first.
```
