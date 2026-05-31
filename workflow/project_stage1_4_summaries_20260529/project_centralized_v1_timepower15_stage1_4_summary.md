# 项目二：centralized_v1 / TimePower15 Stage1-4 总结

生成日期：2026-05-29

本文总结新的 `centralized_v1` 主线。这个项目从旧版 Stage3/4/5 继承了
“稀疏多源风场重构”的目标，但把架构改成：

```text
所有飞机观测全量回传 Ground Center
  -> Stage2 all-in observation organization
  -> Stage3 Ground Center payload
  -> Stage4 strict aircraft hold-out reconstruction
  -> TimePower15 / CMA / PINN / diffusion 后续优化
```

当前最重要的 companion 文档：

```text
stage/youhua.md
workflow/centralized_v1_docs/new_window_project_handover_20260529/centralized_v1_timepower15_full_handover.md
workflow/centralized_v1_docs/new_window_project_handover_20260529/centralized_v1_full_project_handover_20260529.md
workflow/centralized_v1_docs/stage2_stage3_full_process_explanation.md
workflow/centralized_v1_docs/stage4_strict_holdout_logic_and_results.md
```

## 1. 项目定位

`centralized_v1` 的核心目标：

```text
以 Ground Center 为中心，
把 sparse aircraft wind + aircraft trajectory/motion + radar/cloud context
组织成可严格验证的三维风场重构链路。
```

与旧项目的区别：

```text
旧项目：
  更强调 Stage3 flight-agent graph、通信边、Stage4 状态层与 Stage5 ROI scaffold。

centralized_v1：
  更强调 Ground Center、strict aircraft hold-out、point error、
  TimePower15 参数链路、CMA 弱背景、未来 PINN/diffusion residual learning。
```

当前主线不是旧 Stage4 冻结链路。新窗口默认从：

```text
/data/LFT-W02_data/pengxu/stage/centralized_v1
```

继续。

## 2. 当前核心目录

代码目录：

```text
/data/LFT-W02_data/pengxu/stage/centralized_v1
```

输出根目录：

```text
/data/LFT-W02_data/pengxu/centralized_v1_output
```

关键输入：

```text
Stage2 full v2:
/data/LFT-W02_data/pengxu/centralized_v1_output/stage2_full_v2/stage2_multimodal_summary.json

Stage3 full v2 minimal:
/data/LFT-W02_data/pengxu/centralized_v1_output/stage3_full_v2_8w_minimal/stage3_center_summary.json
```

当前最佳 Stage4 输出：

```text
/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_full_v2_best_adaptive_all_12w_20260529
```

## 3. 核心脚本

配置与契约：

```text
stage/centralized_v1/configs/centralized_v1_config.py
stage/centralized_v1/configs/centralized_v1_contract.py
```

Stage2：

```text
stage/centralized_v1/core/centralized_stage2_multimodal.py
stage/centralized_v1/core/centralized_report_stage2_slices.py
```

Stage3：

```text
stage/centralized_v1/core/centralized_stage3_center.py
stage/centralized_v1/core/centralized_report_stage3_ground_center.py
```

Stage4：

```text
stage/centralized_v1/core/centralized_stage4_ground_recon.py
stage/centralized_v1/core/centralized_stage4_sensitivity.py
stage/centralized_v1/core/centralized_stage4_error_trace.py
stage/centralized_v1/core/centralized_stage4_compare_sensitivity.py
stage/centralized_v1/core/centralized_stage4_expanded_analysis.py
stage/centralized_v1/core/centralized_stage4_optimize.py
stage/centralized_v1/core/centralized_stage4_query.py
stage/centralized_v1/core/centralized_report_stage4_slices.py
```

CMA / training：

```text
stage/centralized_v1/core/centralized_cma_ra_virtual_radial_3dvar.py
stage/centralized_v1/core/centralized_report_cma_virtual_radial.py
stage/centralized_v1/core/centralized_stage4_cma_compare.py
stage/centralized_v1/core/centralized_training_manifest.py
```

Stage5 prototype:

```text
stage/centralized_v1/core/centralized_stage5_wind_cloud.py
stage/centralized_v1/core/centralized_report_stage5_slices.py
```

## 4. Stage1：clean source 与雷达索引

### 4.1 Stage1 的职责

Stage1 在 centralized_v1 中仍然是上游清洗层，负责生成：

```text
stage1_output/clean_wind.parquet
stage1_output/clean_loc.parquet
stage1_output/radar_index.json
```

它不直接属于 `stage/centralized_v1/core`，但 centralized_v1 Stage2 读取它的输出。

### 4.2 Stage1 数据来源

`clean_wind.parquet` 来源：

```text
amdar_parquet + turb_parquet
```

核心字段：

```text
time_utc
lat_clean
lon_clean
alt_meters
wind_dir
wind_speed
u_wind
v_wind
flight_id
source
obs_conf
```

风分量公式：

```text
u_wind = -wind_speed * sin(wind_dir)
v_wind = -wind_speed * cos(wind_dir)
```

`clean_loc.parquet` 来源：

```text
location_location_parquet
```

核心字段：

```text
time_utc
lat_clean
lon_clean
alt_meters
heading_deg
ground_speed_ms
u_motion
v_motion
flight_id
```

运动分量公式：

```text
ground_speed_ms = 地速 * GROUND_SPEED_TO_MPS
u_motion = ground_speed_ms * sin(heading_deg)
v_motion = ground_speed_ms * cos(heading_deg)
```

关键边界：

```text
u_motion / v_motion 是飞机运动，不是大气风。
motion_records / context_motion_records 不能作为 wind truth。
```

`radar_index.json`：

```text
filename
time_str
timestamp_utc
radar_path
usable
```

雷达 PNG 只作为 2D cloud/radar context，不是 3D Doppler wind truth。

### 4.3 Stage1 当前数据规模

文档记录：

```text
clean_wind.parquet rows = 431189
clean_loc.parquet rows = 19162638
radar_index.json rows = 7396
```

## 5. Stage2：all-in observation organization

### 5.1 Stage2 的职责

Stage2 在 centralized_v1 中不是最终风场重构，而是：

```text
把当前窗口、上下文窗口、轨迹、运动和 radar/cloud 背景统一组织到 Stage4 网格。
```

Stage2 关键理念：

```text
all-in observation organization
current label candidates
context background observations
voxel-level records
diagnostic confidence
```

### 5.2 Stage2 主脚本

```text
stage/centralized_v1/core/centralized_stage2_multimodal.py
```

可视化：

```text
stage/centralized_v1/core/centralized_report_stage2_slices.py
```

### 5.3 Stage2 输入

```text
stage1_output/clean_wind.parquet
stage1_output/clean_loc.parquet
stage1_output/radar_index.json
radar_index.json 中 radar_path 指向的 radar PNG
```

### 5.4 Stage2 网格

```text
z x y x = 31 x 525 x 775
lat = 12.2 .. 54.2
lon = 73.0 .. 135.0
alt = 0 .. 15000 m
z step = 500 m
xy_downsample ~= 4 relative to radar PNG
```

### 5.5 Stage2 时间窗口

对目标雷达时间 `T`：

```text
current window = [T - 5 min, T + 5 min]
context window = [T - 360 min, T + 360 min]
```

上下文窗口排除当前标签窗口：

```text
abs(delta_time_minutes) <= 5 min is excluded from context
```

### 5.6 Stage2 输出

当前主输出：

```text
/data/LFT-W02_data/pengxu/centralized_v1_output/stage2_full_v2
```

summary：

```text
/data/LFT-W02_data/pengxu/centralized_v1_output/stage2_full_v2/stage2_multimodal_summary.json
```

重要记录：

```text
wind_records
context_wind_records
loc_records
motion_records
context_motion_records
flight_raw_records
cloud_2d
multimodal_meta_json
```

### 5.7 Stage2 概念

`wind_records`：

```text
当前 +/-5 min 飞机风观测。
它们是 Stage4 strict hold-out 的唯一候选真值来源。
```

`context_wind_records`：

```text
历史上下文风观测。
可参与 Stage4 融合，但不能作为当前帧真值。
```

`loc_records`：

```text
当前窗口飞机轨迹/位置体素。
```

`motion_records`：

```text
当前窗口飞机运动分量体素。只能作为覆盖/运动诊断，不是 wind truth。
```

`context_motion_records`：

```text
历史上下文飞机运动体素。同样不是 wind truth。
```

`cloud_2d`：

```text
雷达/云图灰度背景，用于空间上下文和可视化。
不是风标签。
```

`time_conf`：

```text
时间新鲜度。当前口径通常类似：
time_conf = 0.5 ** (abs(delta_time_minutes) / 180)
```

`space_conf`：

```text
Stage2/Stage3 中保持中性，当前为 1.0。
真正目标 voxel 空间局地化在 Stage4 做。
```

`joint_likelihood`：

```text
obs_conf * time_conf
```

### 5.8 Stage2 12-worker 全量命令

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

### 5.9 Stage2 图怎么读

Stage2 图中的常见元素：

```text
gray background = radar/cloud intensity
orange arrows/dots = current wind_records
magenta x = context_wind_records
blue dots = loc_records
green dots = motion_records
```

图上稀疏不是失败，而是观测本身稀疏。

## 6. Stage3：Ground Center payload

### 6.1 Stage3 的职责

centralized_v1 Stage3 不再主打 Air-to-Air graph，而是：

```text
Ground Center logical intake
all aircraft observations upload to ground
package per-frame payload and confidence package
```

Ground Center 是逻辑服务器，不是物理雷达站或物理权重中心。

### 6.2 Stage3 主脚本

```text
stage/centralized_v1/core/centralized_stage3_center.py
```

可视化/报告：

```text
stage/centralized_v1/core/centralized_report_stage3_ground_center.py
```

### 6.3 Stage3 输入

```text
Stage2 full v2 summary
Stage2 per-frame multimodal npz
```

### 6.4 Stage3 输出

当前重要输出：

```text
/data/LFT-W02_data/pengxu/centralized_v1_output/stage3_full_v2_8w_minimal
```

summary：

```text
/data/LFT-W02_data/pengxu/centralized_v1_output/stage3_full_v2_8w_minimal/stage3_center_summary.json
```

Stage3 输出概念：

```text
label_candidates = wind_records
context_observations = context_wind_records / context_motion_records
trajectory_observations = loc_records
motion_observations = motion_records
confidence_package = time_conf / space_conf / joint_likelihood
```

### 6.5 Stage3 当前边界

```text
Stage3 不做最终风场重构。
Stage3 不把 reference center 当物理权重中心。
Stage3 主要负责打包、分组、解释和传给 Stage4。
```

## 7. Stage4：strict aircraft hold-out reconstruction

### 7.1 Stage4 的职责

Stage4 是 centralized_v1 中第一个真正生成三维风场的阶段。

它完成：

```text
1. 从 wind_records 中选择 hold-out truth。
2. 在融合前删除 hold-out 点。
3. 用剩余 current wind + context wind 重构三维风场。
4. 输出 recon_u / recon_v / recon_confidence / recon_mask。
5. 对 withheld aircraft wind_records 做点误差。
6. 记录 leakage guard 与 motion_used_as_wind。
```

### 7.2 Stage4 主脚本

```text
stage/centralized_v1/core/centralized_stage4_ground_recon.py
```

metrics-only sensitivity：

```text
stage/centralized_v1/core/centralized_stage4_sensitivity.py
```

error trace：

```text
stage/centralized_v1/core/centralized_stage4_error_trace.py
```

visualization：

```text
stage/centralized_v1/core/centralized_report_stage4_slices.py
```

### 7.3 Stage4 strict rule

唯一真值：

```text
selected current-window wind_records
```

融合输入：

```text
non-holdout current wind_records
context_wind_records
```

禁止：

```text
holdout wind entering fusion
motion_records used as wind
context_motion_records used as wind
CMA used as truth
```

必须为真：

```text
strict_holdout_no_leakage = true
motion_used_as_wind = false
```

### 7.4 Stage4 权重

默认 active weight：

```text
active_weight = obs_conf * time_conf * target_voxel_localization
```

Gaussian localization：

```text
localization = exp(-0.5 * ((dx/sigma_xy)^2 + (dy/sigma_xy)^2 + (dz/sigma_z)^2))
```

Gaspari-Cohn：

```text
compact-support fifth-order localization
```

`diagnostic_only`：

```text
记录 density/quality/speed/local consistency 等诊断，但不改历史 baseline 权重。
```

`diagnostic_weighted`：

```text
active_weight *= density_conf * quality_conf * speed_qc_conf * local_consistency_conf
```

### 7.5 Stage4 输出

每帧完整重构输出：

```text
frame_<time>_center_strict.npz
point_eval_<time>.json
point_eval_<time>.csv
point_eval_<time>.txt
stage4_method_<time>.md
```

NPZ 重要字段：

```text
recon_u_3d
recon_v_3d
recon_confidence_3d
recon_mask_3d
c_time_3d
c_space_3d
c_joint_3d
blindzone_initialized_mask_3d
cloud_2d
point_eval_json
```

后续新增诊断：

```text
stage4_role_conflict_mask_3d
stage4_role_conflict_component_gap_3d
stage4_role_conflict_threshold_3d
stage4_role_conflict_context_factor_3d
```

### 7.6 Stage4 baseline / TimePower15 / CMA 三条链

Aircraft-only baseline：

```text
Gaussian 12/6/2/1
diagnostic_only
proxy
no role-conflict adaptive
no CMA
```

TimePower15 / candidate-v2 / best adaptive：

```text
Gaussian 8/4/2/1
diagnostic_weighted
pydda_3dvar_proxy
current_weight_boost = 2.0
context_weight_scale = 0.5
context_time_conf_power = 1.5
role_conflict_mode = current_priority_adaptive
conflict_speed_threshold_mps = 12
conflict_context_factor = 0.25
```

CMA branch：

```text
CMA linear_qc / virtual radial / class-3DVAR proxy
used as weak background or pseudo-observation
not aircraft truth
```

## 8. Stage4 Current Best Full Run

Output:

```text
/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_full_v2_best_adaptive_all_12w_20260529
```

Original aggregate:

```text
frames = 7395
mean_rmse_vector = 6.601731724755013
mean_mae_vector  = 5.809264558182015
```

Correct stratified view:

```text
all_frames_original:
  frames = 7395
  RMSE = 6.60
  MAE  = 5.81

eval_holdout_only:
  frames = 5614
  RMSE = 8.70
  MAE  = 7.65

no_holdout_unverified_reconstruction:
  frames = 1781
  RMSE = 0.0 only because no truth exists
```

Stratified output:

```text
/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_full_v2_best_adaptive_all_12w_20260529/stratified_eval/stage4_localization_sensitivity_stratified_aggregate.md
```

### 8.1 No-holdout rule

No-holdout means:

```text
there is no current aircraft wind truth for scoring
```

It does not mean:

```text
no reconstruction
no hazard
no business value
perfect zero error
```

Rule:

```text
keep no-holdout frames as unverified reconstruction products
exclude them from strict RMSE/MAE
report coverage/confidence/strong-wind/vertical-risk diagnostics
```

### 8.2 500 m vs 30 m wind-shear threshold

Stage4 grid:

```text
500 m vertical spacing
```

Discussed aviation reference:

```text
30 m vertical wind-speed difference around 6 m/s
```

Correct relation:

```text
not directly comparable as the same metric
but point wind error near 6 m/s consumes safety margin for shear diagnosis
```

Current status:

```text
research-grade 3D sparse aircraft wind reconstruction
not operational 30 m wind-shear warning system
```

Needed:

```text
vertical jump
vertical mismatch
strong-layer consistency
wind_shear_risk_head
```

## 9. Stage4 Representative Visuals

Representative output root:

```text
/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_best_adaptive_representative_visuals_20260529
```

Selected frames:

```text
20260214172400: low-error normal
20260209104200: median-like
20260210083600: near 6 m/s critical
20260131182400: high-error with multiple holdouts
20260204031800: extreme single-point anomaly
20260127203000: no-holdout high-risk unverified
```

ROI visual index:

```text
/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_best_adaptive_representative_visuals_20260529/representative_visual_index_roi.md
```

ROI command:

```bash
ROOT=/data/LFT-W02_data/pengxu
MPLCONFIGDIR=/tmp/matplotlib /opt/miniconda3/bin/python \
  $ROOT/stage/centralized_v1/core/centralized_report_stage4_slices.py \
  --stage4-dir $ROOT/centralized_v1_output/stage4_best_adaptive_representative_visuals_20260529/recon \
  --out-dir $ROOT/centralized_v1_output/stage4_best_adaptive_representative_visuals_20260529/visuals_roi \
  --z-levels auto \
  --crop-mode bbox \
  --crop-pad 24 \
  --num-workers 6
```

Full-domain image caveat:

```text
full grid = 31 x 525 x 775
effective reconstruction fraction ~= 0.9% to 2.1%
```

ROI display:

```text
ROI crop area = about 28.5% to 37.9% of China land area
actual reconstruction footprint = about 6.7% to 11.7% of China land area
```

## 10. Stage4 Runs And Commands

### 10.1 Full TimePower15 adaptive all-frame metrics-only

```bash
ROOT=/data/LFT-W02_data/pengxu
PY=$ROOT/.conda/envs/windy310/bin/python
OUT=$ROOT/centralized_v1_output/stage4_full_v2_best_adaptive_all_12w_20260529

$PY $ROOT/stage/centralized_v1/core/centralized_stage4_sensitivity.py \
  --stage2-summary $ROOT/centralized_v1_output/stage2_full_v2/stage2_multimodal_summary.json \
  --stage3-summary $ROOT/centralized_v1_output/stage3_full_v2_8w_minimal/stage3_center_summary.json \
  --frame-times "" \
  --out-dir $OUT \
  --sample-count 0 \
  --param-grid 8,4,2,1 \
  --kernels gaussian \
  --confidence-mode diagnostic_weighted \
  --physics-constraint-mode pydda_3dvar_proxy \
  --current-weight-boost 2.0 \
  --context-weight-scale 0.5 \
  --context-time-conf-power 1.5 \
  --role-conflict-mode current_priority_adaptive \
  --conflict-speed-threshold-mps 12 \
  --conflict-context-factor 0.25 \
  --progress-interval-seconds 30 \
  --num-workers 12
```

### 10.2 Baseline 200-frame metrics-only

```bash
ROOT=/data/LFT-W02_data/pengxu
PY=$ROOT/.conda/envs/windy310/bin/python
OUT=$ROOT/centralized_v1_output/stage4_baseline_200_12w_20260529

$PY $ROOT/stage/centralized_v1/core/centralized_stage4_sensitivity.py \
  --stage2-summary $ROOT/centralized_v1_output/stage2_full_v2/stage2_multimodal_summary.json \
  --stage3-summary $ROOT/centralized_v1_output/stage3_full_v2_8w_minimal/stage3_center_summary.json \
  --frame-times "" \
  --out-dir "$OUT" \
  --sample-count 200 \
  --sample-seed 20260527 \
  --param-grid 12,6,2,1 \
  --kernels gaussian \
  --confidence-mode diagnostic_only \
  --physics-constraint-mode proxy \
  --progress-interval-seconds 30 \
  --num-workers 12
```

### 10.3 Selected-frame full NPZ for visuals

```bash
ROOT=/data/LFT-W02_data/pengxu
PY=$ROOT/.conda/envs/windy310/bin/python
OUT=$ROOT/centralized_v1_output/stage4_best_adaptive_representative_visuals_20260529/recon

$PY $ROOT/stage/centralized_v1/core/centralized_stage4_ground_recon.py \
  --stage2-summary $ROOT/centralized_v1_output/stage2_full_v2/stage2_multimodal_summary.json \
  --stage3-summary $ROOT/centralized_v1_output/stage3_full_v2_8w_minimal/stage3_center_summary.json \
  --frame-times 20260214172400,20260209104200,20260210083600,20260131182400,20260204031800,20260127203000 \
  --out-dir $OUT \
  --localization-radius-xy 8 \
  --localization-sigma-xy 4 \
  --localization-radius-z 2 \
  --localization-sigma-z 1 \
  --localization-kernel gaussian \
  --confidence-mode diagnostic_weighted \
  --physics-constraint-mode pydda_3dvar_proxy \
  --current-weight-boost 2.0 \
  --context-weight-scale 0.5 \
  --context-time-conf-power 1.5 \
  --role-conflict-mode current_priority_adaptive \
  --conflict-speed-threshold-mps 12 \
  --conflict-context-factor 0.25 \
  --num-workers 6
```

## 11. CMA Pipeline

CMA role:

```text
weak background
pseudo-observation
pretraining teacher prior
condition input
physical/boundary constraint
```

CMA must not be:

```text
aircraft truth
true 6min convective evolution
final skill metric
30 m wind-shear label
```

Standard CMA processing concept:

```text
CMA u/v/w
  -> linear_qc interpolation to Stage2/Stage4 time
  -> Stage4 grid collocation
  -> temporal_conf / rapid_change_flag
  -> optional virtual radial velocity
  -> optional class-3DVAR proxy
  -> Stage4 weak fusion or training condition
```

Important CMA candidate modes:

```text
cma_proxy_background
cma_reanalysis_background
cma_pseudo_observation
```

Safety:

```text
CMA agreement != aircraft truth skill
```

## 12. PINN / Diffusion Future Plan

Recommended residual pattern:

```text
F_final = F_timepower15 + delta
```

Model inputs:

```text
timepower15 u/v
timepower15 confidence
recon_mask
role_conflict diagnostics
vertical mismatch / oversmoothing diagnostics
low_conf_fill mask
CMA interpolated u/v/w
CMA temporal_conf
CMA rapid_change_flag
radar/cloud context
```

Outputs:

```text
delta_u
delta_v
uncertainty
wind_shear_risk score
```

PINN role:

```text
deterministic physical residual correction
weak divergence / smoothness / boundary constraints
vertical consistency
strong-wind anti-oversmoothing
```

Diffusion role:

```text
conditional residual ensemble
high-error tail repair
local nonlinear correction
uncertainty field
```

Training sequence:

```text
1. CMA + TimePower15 residual pretraining for large-scale structure.
2. Aircraft train wind_records fine-tuning.
3. Strict holdout validation.
4. Add diffusion ensemble for uncertainty and long-tail local correction.
5. Add wind_shear_risk_head for aviation-risk diagnosis.
```

## 13. Latest Code Changes In Current Context

`centralized_stage4_ground_recon.py`:

```text
adaptive role-conflict calibration
role conflict component gap / threshold / context factor fields
point-level role-conflict diagnostics
vertical context mismatch diagnostics
strong vertical isolated diagnostics
point QC review fields
```

`centralized_stage4_error_trace.py`:

```text
--auto-high-error
--auto-min-rmse
--auto-top-n-frames
qc_stratum
qc_action_hint
vertical and role-conflict trace fields
```

`centralized_stage4_sensitivity.py`:

```text
adaptive / vertical diagnostics in metrics-only and aggregate outputs
```

`centralized_report_stage4_slices.py`:

```text
--crop-mode full|bbox
--crop-pad
--z-levels auto
```

## 14. Documentation And Literature Context

`workflow` 文档提供以下方法依据：

```text
Aircraft-derived observations / AMDAR / Mode-S / EMADDC:
  支撑 aircraft wind_records 的观测价值和误差问题。

Vision Mamba incomplete wind reconstruction:
  支撑从不完整航路风观测恢复风场的神经重构方向。

PINN sparse flow reconstruction:
  支撑稀疏观测 + 物理约束的风场重构。

Multi-scale PINN 3D wind reconstruction:
  支撑三维、时空、多尺度物理重构。

PyDDA / dual-Doppler variational retrieval:
  支撑 3DVAR、背景约束、Doppler/虚拟径向速度思路。

Pangu / FengWu / FuXi / GraphCast / GenCast:
  支撑天气 AI 和 diffusion/ensemble forecast 的大方向。
```

## 15. 当前必须避免的误读

```text
1. 不要把 no-holdout 0 误差当模型好。
2. 不要把 motion_records 当风。
3. 不要把 CMA 当真值。
4. 不要把 500 m 点风误差直接等价 30 m 风切变阈值。
5. 不要把 ROI 矩形全域当有效风场 footprint。
6. 不要把 Stage4 当前 PINN/diffusion scaffold 当训练好的模型。
7. 不要只追全局 RMSE 而抹平强风层和垂直急变。
```

## 16. 当前结论

```text
1. centralized_v1 已完成 Stage2 full v2、Stage3 full v2 minimal、
   Stage4 TimePower15 full adaptive 7395-frame metrics-only run。

2. 当前最佳传统链路是 TimePower15 / candidate-v2 / adaptive，
   但真实性能必须看 holdout-only 分层指标。

3. no-holdout 帧全部保留业务重构，但从严格 RMSE/MAE 中剔除。

4. ROI 可视化已经解决 full-domain 图稀疏问题，但有效风场仍由 recon_mask 决定。

5. CMA 是未来训练和融合的重要弱背景，不是 truth。

6. 后续最稳路线是：
   TimePower15 主干 + CMA 条件 + PINN 残差 + Diffusion 不确定性
   + aircraft strict holdout 最终验证。
```

## 17. 2026-05-29 Stage4 结果复盘、垂直风险补丁与 CMA 启动

### 17.1 Stage4 TimePower15 分层结论

当前全量结果目录：

```text
/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_full_v2_best_adaptive_all_12w_20260529
```

验收结论：

```text
总帧数: 7395
strict_holdout_no_leakage: 全真
motion_used_as_wind: 全假
no-holdout: 不进入官方 RMSE/MAE
```

官方指标只看 `eval_holdout_only`：

```text
eval_holdout_only: 5614 frames, 15054 holdout points
frame-mean RMSE/MAE: 8.696082 / 7.652211 m/s
holdout-point-weighted RMSE/MAE: 14.819533 / 6.724179 m/s
single_holdout_pressure_test: 1688 frames, frame RMSE/MAE 10.588383 / 10.588383 m/s
multi_holdout_supported: 3926 frames, frame RMSE/MAE 7.882480 / 6.389791 m/s
no_holdout_unverified_reconstruction: 1781 frames, RMSE/MAE 留空，仅保留业务诊断
```

解释：结果符合当前 strict holdout 评估要求，但精度仍属于传统基线，不是最终模型。单候选压力测试和强风/垂直失配长尾是主要误差来源。参考：WMO aircraft-based observations 说明飞机风观测适合作为航空气象观测基准，Mode-S/EHS 风场论文说明飞机派生风观测需要质控和分层评估；因此本项目继续坚持 aircraft holdout-only 验证。文献：WMO ABO `https://wmo.int/aircraft-based-observations-programme`；de Haan and Stoffelen 2016 `https://amt.copernicus.org/articles/9/4141/2016/`。

### 17.2 代表帧可视化

已重建并可视化 6 类代表帧：

```text
20260217120000  low_error
20260127110000  median_error
20260209134200  near_6ms_boundary
20260129001800  high_multi_holdout
20260126003600  extreme_single_holdout
20260206191200  no_holdout_high_risk
```

输出：

```text
baseline NPZ:
/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_timepower15_representative_20260529/baseline_recon

baseline PNG/CSV:
/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_timepower15_representative_20260529/baseline_visuals

vertical-risk candidate NPZ:
/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_timepower15_representative_20260529/vertical_risk_recon

vertical-risk candidate PNG/CSV:
/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_timepower15_representative_20260529/vertical_risk_visuals
```

每套输出包含 6 张 `*_centralized_stage4_slices.png`、6 张 `*_centralized_stage4_diagnostics.png` 和 6 个 `*_centralized_stage4_slice_stats.csv`。Stage4 图是重构结果诊断图；有效范围仍以 `recon_mask_3d` 为准。参考：PyDDA/3DVAR 风场反演强调约束与诊断场共同解释重构结果，不能只看图像填色。文献：PyDDA `https://openradarscience.org/PyDDA/`。

### 17.3 垂直失配/过平滑补丁

新增代码：

```text
stage/centralized_v1/core/centralized_stage4_ground_recon.py
  --vertical-risk-mode off|preserve_strong_layers
  --vertical-gradient-preserve-weight
  --vertical-context-mismatch-damping

stage/centralized_v1/core/centralized_stage4_sensitivity.py
  同步支持 metrics-only 消融评估
```

实现原则：

```text
1. 默认 off，确保既有 TimePower15 全量结果可复现。
2. preserve_strong_layers 打开后，只在强风层/垂直失配/过平滑候选体素上降低跨层扩散。
3. 风险体素的平滑邻域从 6 邻域改为水平 4 邻域，减少垂直方向跨层抹平。
4. 对高置信原始锚点向原始场回拉，避免低置信填补覆盖观测支撑层。
```

小样本结果：6 个代表帧的 holdout RMSE 基本不变，垂直 mismatch/oversmooth 诊断略有波动，没有证据支持把该补丁设为默认主线。它当前是候选消融开关，后续应在 200 帧/7395 帧分层表里再验证。参考：Perona-Malik 各向异性扩散支持“保边/保梯度而非全方向平滑”；PyDDA/3DVAR 使用平滑、背景、质量连续等约束，但需要避免把真实强垂直梯度过度抹平。文献：Perona and Malik 1990 `https://doi.org/10.1109/34.56205`；PyDDA `https://openradarscience.org/PyDDA/`。

### 17.4 CMA / PINN / Diffusion 已启动的 manifest

已生成训练清单：

```text
/data/LFT-W02_data/pengxu/centralized_v1_output/training_manifest_cma_pinn_diffusion_20260529/centralized_training_manifest.json
/data/LFT-W02_data/pengxu/centralized_v1_output/training_manifest_cma_pinn_diffusion_20260529/centralized_training_manifest.md
```

清单统计：

```text
frames_total: 7395
frames_with_stage4_metrics: 7395
frames_with_cma_raw_wind_bracket: 7395
cma_raw_file_count: 773
cma_raw_wind_time_count: 129
split_counts: train 5176 / val 1109 / test 1110
```

CMA 使用边界：

```text
CMA/CRA40 只作弱背景、条件输入、边界/物理约束；
PINN 输出 delta_u/delta_v；
F_pinn = F_timepower15 + delta；
Diffusion 在 PINN 后处理局地残差、不确定性、低置信补全；
正式验证仍只用飞机 holdout，不用 CMA 作 truth。
```

参考：PINN 原始框架支持把 PDE/物理约束写入神经网络训练损失；GenCast 说明扩散模型适合概率集合和不确定性表达；CRA40/CMA 再分析适合作背景场而非本项目 truth。文献：Raissi et al. 2019 `https://doi.org/10.1016/j.jcp.2018.10.045`；GenCast Nature 2024 `https://www.nature.com/articles/s41586-024-08252-9`；CRA40 `https://doi.org/10.1007/s13351-023-2086-x`。
