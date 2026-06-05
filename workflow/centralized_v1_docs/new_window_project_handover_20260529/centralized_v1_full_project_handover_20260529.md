# Centralized V1 Full Project Handover - 2026-05-29

This document is the new-window project handover for the current
`centralized_v1` wind-field reconstruction line. It integrates the current
workspace state, the latest TimePower15 full-run analysis, CMA/PINN/diffusion
planning, strict hold-out rules, visualization outputs, and the companion
optimization document:

```text
/data/LFT-W02_data/pengxu/stage/youhua.md
```

Use this file together with `stage/youhua.md`. This file is the project-wide
handover; `youhua.md` is the detailed TimePower15 optimization and aviation
risk analysis document.

## 0. New Window First Message

Copy this to a new window if needed:

```text
请先读：
/data/LFT-W02_data/pengxu/workflow/centralized_v1_docs/new_window_project_handover_20260529/centralized_v1_full_project_handover_20260529.md
/data/LFT-W02_data/pengxu/stage/youhua.md

当前主线是 centralized_v1 中心化地空风场重构，不回旧 Stage4/Stage5 冻结链路。
Stage4 当前最佳传统链路是 TimePower15 / candidate-v2 adaptive 全量 12w 结果。
全量 7395 帧已经跑完，但严格精度评估必须剔除 no-holdout 帧；no-holdout 帧保留业务重构，只标记为 unverified reconstruction。
CMA 可以作为弱背景、预训练先验、条件输入和物理约束，不能作为 aircraft truth。
PINN/diffusion 后续应作为 TimePower15 残差修正、不确定性估计和低置信补全层，不能直接替代 strict aircraft 主链路。
```

## 1. Project Identity

Current project line:

```text
centralized_v1 = all-in aircraft/radar observation organization
              -> Ground Center centralized reconstruction
              -> strict aircraft hold-out validation
              -> future PINN/diffusion/CMA-assisted refinement
              -> future wind/downlink ROI
```

Core source tree:

```text
/data/LFT-W02_data/pengxu/stage/centralized_v1
```

Current output root:

```text
/data/LFT-W02_data/pengxu/centralized_v1_output
```

Do not default back to the old frozen Stage4/Stage5 path. The old path is
historical reference only.

## 2. Stable Data And Code Entry Points

Primary full inputs:

```text
Stage2 full v2:
/data/LFT-W02_data/pengxu/centralized_v1_output/stage2_full_v2/stage2_multimodal_summary.json

Stage3 full v2 minimal:
/data/LFT-W02_data/pengxu/centralized_v1_output/stage3_full_v2_8w_minimal/stage3_center_summary.json
```

Important code:

```text
stage/centralized_v1/core/centralized_stage2_multimodal.py
stage/centralized_v1/core/centralized_stage3_center.py
stage/centralized_v1/core/centralized_stage4_ground_recon.py
stage/centralized_v1/core/centralized_stage4_sensitivity.py
stage/centralized_v1/core/centralized_stage4_error_trace.py
stage/centralized_v1/core/centralized_report_stage4_slices.py
stage/centralized_v1/core/centralized_cma_ra_virtual_radial_3dvar.py
stage/centralized_v1/core/centralized_report_cma_virtual_radial.py
stage/centralized_v1/core/centralized_stage4_cma_compare.py
stage/centralized_v1/core/centralized_training_manifest.py
```

Key documentation:

```text
workflow/centralized_v1_docs/README.md
workflow/centralized_v1_docs/new_window_handover_stage2_stage3.md
stage/handover_stage45_20260507/23_centralized_v1_new_window_handover.md
stage/youhua.md
```

## 3. Stage Meaning

Stage1:

```text
clean source + radar index preparation
```

Stage2:

```text
All-in observation organization.
Reads clean wind, clean location, radar index and radar/cloud PNG.
Builds 31 x 525 x 775 multimodal voxel records.
Does not reconstruct final wind.
```

Stage3:

```text
Ground Center intake / star-topology payload.
No Air-to-Air communication in the current mainline.
Packages current wind, context wind, motion/context motion, trajectories,
and confidence diagnostics.
```

Stage4:

```text
Strict aircraft hold-out wind reconstruction.
Only wind_records can be truth labels.
Selected hold-out wind_records are removed before fusion.
motion_records and context_motion_records are not wind truth.
```

Stage5:

```text
Future wind / downlink ROI direction.
Current PINN/diffusion code is still proxy/scaffold, not trained deep learning.
```

Stage6:

```text
Future cloud/wind-cloud coupling work. Do not force cloud prediction into
Stage1-5 current evaluation.
```

## 4. Non-Negotiable Validation Rules

Strict rules:

```text
hold-out truth = selected aircraft wind_records only
selected hold-out wind_records must be removed before fusion
context_wind_records are historical context, not truth labels
motion_records and context_motion_records must not be used as wind
CMA must not be used as truth
strict_holdout_no_leakage must remain true
motion_used_as_wind must remain false
```

Never report CMA agreement as aircraft skill. Aircraft hold-out skill and
CMA/background consistency are separate metrics.

## 5. Three Important Chains

### 5.1 Aircraft-Only Baseline

Role:

```text
Strict sparse truth baseline. No CMA.
```

Typical baseline characteristics:

```text
Gaussian localization
diagnostic_only confidence
proxy physics scaffold
no role-conflict adaptation
aircraft wind_records only for truth
```

This is the independent benchmark and should stay separate from CMA candidate
roots.

### 5.2 Stage4 Candidate-V2 / TimePower15

Role:

```text
Current best traditional aircraft-only Stage4 candidate.
```

Canonical parameters used in the full all-frame adaptive run:

```text
--localization-radius-xy 8
--localization-sigma-xy 4
--localization-radius-z 2
--localization-sigma-z 1
--localization-kernel gaussian
--confidence-mode diagnostic_weighted
--physics-constraint-mode pydda_3dvar_proxy
--current-weight-boost 2.0
--context-weight-scale 0.5
--context-time-conf-power 1.5
--role-conflict-mode current_priority_adaptive
--conflict-speed-threshold-mps 12
--conflict-context-factor 0.25
```

Interpretation:

```text
current wind anchors are protected
context wind is useful but downweighted
older context decays more aggressively
role-conflict adapts by height, density, and context age
```

### 5.3 CMA Standard Candidate

Role:

```text
CMA weak background / pseudo-observation / proxy-generation branch.
It supports training and fusion, but does not replace strict aircraft truth.
```

Conceptual CMA pipeline:

```text
1. CMA temporal interpolation: nearest / linear / linear_qc
2. Stage4 grid collocation: 31 x 525 x 775, 500 m vertical spacing
3. optional geometry-aware virtual radial velocity
4. class-3DVAR-style CMA proxy correction
5. Stage4 weak fusion:
   cma_proxy_background
   cma_reanalysis_background
   cma_pseudo_observation
```

Standard CMA candidate logic:

```text
--cma-time-method linear_qc
--geometry-balance-mode los_weighted
--cma-confidence-source temporal_conf
--cma-confidence-cap 0.30
--cma-qc-gating temporal_change
```

CMA caveat:

```text
CMA 6h -> 6min interpolation provides low-frequency background structure.
It does not create true 6min convective evolution.
```

## 6. Current Best Full Result

Full TimePower15 / adaptive all-frame result:

```text
/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_full_v2_best_adaptive_all_12w_20260529
```

Original aggregate file:

```text
/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_full_v2_best_adaptive_all_12w_20260529/stage4_localization_sensitivity_aggregate.csv
```

Original all-frame headline:

```text
frames = 7395
mean_rmse_vector = 6.601731724755013 m/s
mean_mae_vector  = 5.809264558182015 m/s
```

This headline is optimistic because no-holdout frames have RMSE/MAE equal to
zero only because no aircraft truth exists.

Correct stratified output:

```text
/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_full_v2_best_adaptive_all_12w_20260529/stratified_eval/stage4_localization_sensitivity_stratified_aggregate.md
```

Correct interpretation:

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
  RMSE = 0.0 only because there is no current aircraft truth
```

Additional useful strata:

```text
eval_multi_holdout_ge3:
  frames = 2450
  RMSE = 7.58
  MAE  = 5.88

eval_single_holdout_pressure_test:
  frames = 1688
  RMSE = 10.59
  MAE  = 10.59

eval_supported_wind_total_ge10:
  frames = 3719
  RMSE = 7.86
  MAE  = 6.34

eval_rmse_le6:
  frames = 3611
  RMSE = 3.61
  MAE  = 3.34

eval_rmse_gt6:
  frames = 2003
  RMSE = 17.86
  MAE  = 15.43
```

## 7. No-Holdout Logic

No-holdout means:

```text
no current aircraft wind_records are available for strict truth scoring
```

It does not mean:

```text
the frame cannot be reconstructed
the frame is not worth reconstructing
there is no hazardous weather
the model is perfect with zero error
```

For this full run:

```text
no_holdout frames = 1781
wind_records_total = 0 for all no-holdout frames
context_wind_records median ~= 505
effective_reconstructed_voxels median ~= 179318
low_conf_fill_voxels median ~= 85603
strong_wind_voxels median ~= 9278
vertical_context_mismatch_candidate_voxels median ~= 1732
```

Final rule:

```text
Keep no-holdout frames as business reconstruction products.
Exclude no-holdout frames from strict RMSE/MAE skill.
Report them as unverified reconstruction with coverage/confidence/vertical-risk diagnostics.
```

## 8. 500 m Grid Versus 30 m / 6 m/s Wind-Shear Threshold

Stage4 vertical grid:

```text
500 m vertical spacing
```

The aviation wind-shear reference discussed by the user:

```text
30 m vertical layer wind-speed difference around 6 m/s = critical severe shear threshold
```

These are not directly numerically equivalent:

```text
Stage4 metric = point u/v vector reconstruction error
30 m threshold = vertical wind-speed gradient / shear
```

Correct statement:

```text
Do not say RMSE 6 m/s equals severe 30 m wind shear.
Do say that if point wind error is already near 6 m/s, the safety margin for
30 m shear diagnosis is poor.
```

Current model status:

```text
research-grade sparse aircraft wind reconstruction candidate
not aviation operational low-level wind-shear warning system
```

Needed future metric:

```text
vertical jump
vertical mismatch
strong-layer consistency
wind_shear_risk_head
stratified aviation-risk metrics
```

## 9. Representative Visualization Outputs

Representative full NPZ and visual output root:

```text
/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_best_adaptive_representative_visuals_20260529
```

Selected frames:

```text
20260214172400: low-error normal sample
20260209104200: median-like error sample
20260210083600: near 6 m/s critical sample
20260131182400: high-error sample with multiple holdouts
20260204031800: extreme single-point anomaly sample
20260127203000: no-holdout high-risk unverified sample
```

Full-domain visual index:

```text
/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_best_adaptive_representative_visuals_20260529/representative_visual_index.md
```

ROI visual index:

```text
/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_best_adaptive_representative_visuals_20260529/representative_visual_index_roi.md
```

ROI image directory:

```text
/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_best_adaptive_representative_visuals_20260529/visuals_roi
```

ROI area coverage:

```text
/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_best_adaptive_representative_visuals_20260529/roi_area_coverage.csv
```

Why full-domain images looked sparse:

```text
full grid = 31 x 525 x 775 = 12,613,125 voxels
effective reconstruction fraction in full-domain visuals ~= 0.9% to 2.1%
```

New visualization default:

```text
--crop-mode bbox
--crop-pad 24
--z-levels auto
```

ROI effect:

```text
ROI effective visual fraction improved to roughly 9% to 17%
```

ROI crop-area versus actual footprint:

```text
ROI rectangle display area: about 28.5% to 37.9% of China land area
actual reconstruction footprint: about 6.7% to 11.7% of China land area
```

Province-level rough ROI coverage:

```text
main ROI regions:
广东, 广西, 海南, 福建, 江西, 湖南, 湖北, 安徽, 河南, 重庆,
贵州, 山西, 陕西, 四川东部, 云南东部, 江苏西部/南部,
浙江西部/南部, 山东西部/南部, 河北南部

edge-only regions:
甘肃东南部, 宁夏部分区域, 天津南缘, 内蒙古南缘极小部分,
台湾西缘极小部分
```

Important visualization caveat:

```text
Stage4 is evidence-driven local reconstruction, not continuous nationwide wind
claim. Pale/blank regions outside recon_mask mean no wind claim, not zero wind.
```

## 10. Latest Code Changes In This Work Session

### 10.1 Stage4 Ground Recon

File:

```text
stage/centralized_v1/core/centralized_stage4_ground_recon.py
```

Added/extended:

```text
adaptive role-conflict calibration by height, density, and context age
role_conflict_component_gap field
role_conflict_threshold field
role_conflict_context_factor field
point-level role-conflict diagnostics
vertical_context_mismatch_candidate diagnostics
strong_vertical_isolated diagnostics
strong-wind vertical oversmoothing diagnostics
high-error / extreme-speed / context-only / vertical-risk point QC flags
```

Important NPZ outputs now include:

```text
stage4_role_conflict_mask_3d
stage4_role_conflict_component_gap_3d
stage4_role_conflict_threshold_3d
stage4_role_conflict_context_factor_3d
```

### 10.2 Stage4 Error Trace

File:

```text
stage/centralized_v1/core/centralized_stage4_error_trace.py
```

Added:

```text
--auto-high-error
--auto-min-rmse
--auto-top-n-frames
qc_stratum
qc_action_hint
role-conflict point context
vertical-risk trace fields
```

### 10.3 Stage4 Sensitivity

File:

```text
stage/centralized_v1/core/centralized_stage4_sensitivity.py
```

Added aggregate diagnostics:

```text
adaptive role-conflict threshold/context-factor means
vertical mismatch / oversmoothing / isolated strong-wind counts
metrics-only rows with expanded QC fields
```

### 10.4 Stage4 Slice Visualization

File:

```text
stage/centralized_v1/core/centralized_report_stage4_slices.py
```

Added:

```text
--crop-mode full|bbox
--crop-pad
--z-levels auto
```

Use ROI mode for analysis. Use full-domain mode only for global coverage context.

## 11. Useful Commands

### 11.1 Full TimePower15 Metrics-Only Run

Already completed, but command shape:

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

### 11.2 Selected Full NPZ Reconstruction For Visualization

`centralized_stage4_ground_recon.py` expects `--frame-times-file` as a JSON list.
For simple selection, use comma-separated `--frame-times`.

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

### 11.3 ROI Visualization

`windy310` may not have matplotlib. Use `/opt/miniconda3/bin/python` for rendering
if needed.

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

## 12. CMA For PINN/Diffusion Training

CMA after 6min interpolation, alignment, and transformation can be used as:

```text
weak supervision
background field
pretraining target
condition input
physical/boundary constraint
teacher prior
```

It must not be used as:

```text
true 6min wind truth
aircraft-equivalent label
final operational skill target
30 m wind-shear label
```

Reason:

```text
linear interpolation from 6h CMA can smooth in time, but cannot recover real
6min convection, local gusts, or low-level shear evolution.
```

Correct training pattern:

```text
F_model = F_timepower15 + delta
```

Recommended model inputs:

```text
timepower15 u/v
timepower15 confidence and recon_mask
CMA interpolated u/v/w
CMA temporal_conf and rapid_change_flag
Stage2 cloud/radar 2D features
Stage3 context features
role_conflict diagnostics
vertical mismatch / oversmoothing diagnostics
low_conf_fill mask
```

Recommended outputs:

```text
delta_u
delta_v
uncertainty
wind_shear_risk score
```

## 13. PINN And Diffusion Roles

PINN:

```text
deterministic physical residual correction
weak divergence / smoothness / boundary constraints
vertical consistency
strong-wind anti-oversmoothing
role-conflict residual correction
```

Diffusion:

```text
conditional residual ensemble
high-error tail repair
local nonlinear correction
uncertainty field
no-holdout high-risk support
```

Recommended order:

```text
1. Train/evaluate PINN residual correction first.
2. Add conditional diffusion for local residual and uncertainty.
3. Fuse dynamically with TimePower15, not as replacement.
```

## 14. Future Fusion Logic

Final fusion concept:

```text
F_final =
    w_tp   * F_timepower15
  + w_pinn * F_pinn_residual_corrected
  + w_diff * F_diffusion_mean
  + w_cma  * F_cma_interp
```

Weights should be adaptive:

```text
high current aircraft density and high TimePower15 confidence:
  w_tp high

no-holdout / low-conf fill:
  w_pinn and w_diff can increase, but output confidence must be lower

CMA temporal_conf high and rapid_change_flag low:
  w_cma can increase as background

strong wind / rapid vertical change:
  avoid over-smoothing; preserve shear-like gradients

diffusion uncertainty high:
  downweight diffusion correction and mark risk
```

Protect aircraft anchors:

```text
near current aircraft wind observations, the learned model must not override
observed-supported TimePower15 anchors.
```

## 15. High-Error And QC Lessons

Known extreme examples:

```text
20260204031800:
  gt_speed around extreme range in prior trace
  vector_error about 147 m/s
  context-only nearest support
  should be QC-marked / separately stratified

20260126003600 / 20260126003000:
  top full-run RMSE around 244 m/s
  single-holdout pressure-test style frames
```

Do not silently delete these frames. Instead:

```text
trace them
QC-stratify them
exclude invalid physical observations only with explicit rule
report normal-support skill separately from pressure-test skill
```

## 16. Reporting Standards Going Forward

Always report:

```text
all-frame reconstruction count
strict holdout-only RMSE/MAE
no-holdout count and unverified diagnostics
single-holdout pressure-test subset
multi-holdout supported subset
high-error tail p90/p95/p99
strong-wind / vertical-mismatch subset
role-conflict subset
leakage flags
motion_used_as_wind flag
```

Never report:

```text
all-frame RMSE including no-holdout zeros as the main skill metric
CMA agreement as aircraft truth skill
visual density as physical coverage without recon_mask distinction
```

## 17. Immediate Next Steps

Recommended next sequence:

```text
1. Keep TimePower15 full result as current best traditional baseline.
2. Use stratified_eval outputs as the official metric view.
3. Use ROI visualizations for frame-level diagnosis.
4. Run high-error trace on top normal-support and pressure-test frames.
5. Prepare train/val/test split by time.
6. Generate CMA linear_qc aligned fields as weak background inputs.
7. Build a training manifest linking:
   Stage2 frame
   Stage4 TimePower15 NPZ
   CMA proxy/interpolated NPZ
   aircraft train/holdout labels
   diagnostics masks
8. Train PINN residual correction.
9. Add conditional diffusion residual/uncertainty.
10. Validate only on strict aircraft holdout.
```

## 18. Known Practical Caveats

```text
Sensitivity full run is metrics-only; it does not store full 3D NPZ for every frame.
To visualize a frame, rerun centralized_stage4_ground_recon.py for selected times.

No-holdout frames are business-useful but unverified.

ROI crop makes images readable but does not mean every pixel in the ROI has a
valid wind claim; always respect recon_mask.

The current Stage4 500 m vertical grid cannot directly evaluate 30 m wind shear.

windy310 may lack matplotlib; use /opt/miniconda3/bin/python for rendering.
```

## 19. One-Sentence Current State

The project now has a completed full TimePower15 adaptive 12-worker traditional
Stage4 reconstruction run, a corrected stratified evaluation framework, ROI
visual diagnostics, adaptive role-conflict and vertical-risk diagnostics, and a
clear next path: use CMA as weak background/pretraining condition, keep aircraft
strict holdout as truth, and train PINN/diffusion as residual correction and
uncertainty layers on top of TimePower15 rather than replacing it.

# 中心化风场重构项目整体交接文档（2026-05-29）
本文档为 `centralized_v1` 风场重构主线**新版全流程项目交接文件**，整合当前工作区状态、最新TimePower15全量实验分析、CMA/物理信息神经网络/扩散模型整体规划、严格留一验证规则、可视化输出说明，并关联配套优化文档：
```
/data/LFT-W02_data/pengxu/stage/youhua.md
```
**使用说明**：本文档为项目级总交接文档，`youhua.md` 为TimePower15专项优化及航空风场风险分析细则文档，两份文件需配合查阅。

---

## 0. 新接手人员必读提示
新接入工作窗口请优先查看以下文件：
```
请先阅读：
/data/LFT-W02_data/pengxu/workflow/centralized_v1_docs/new_window_project_handover_20260529/centralized_v1_full_project_handover_20260529.md
/data/LFT-W02_data/pengxu/stage/youhua.md
```
项目核心规则简述：
1. 当前主线为 **centralized_v1 中心化地空风场重构**，不再回退至已冻结的旧版Stage4/Stage5链路；
2. Stage4现阶段最优传统链路：TimePower15 / candidate-v2 自适应方案 12进程全量实验结果；
3. 全量共计7395帧数据已完成运算；**精度评估必须剔除无留一真值帧**，无留一帧可正常用于业务重构，仅标记为「未验证重构结果」；
4. CMA数据仅可作为弱背景场、预训练先验、模型条件输入与物理约束，**严禁当作飞机观测真值**；
5. 后续PINN、扩散模型定位为：基于TimePower15结果做残差修正、不确定性评估、低置信区域补全，**不可直接替代以飞机观测为核心的主链路**。

---

## 1. 项目定位
当前项目主线架构：
```
centralized_v1 = 整合飞机/雷达全源观测数据
              -> 地面中心统一重构风场
              -> 基于飞机观测的严格留一验证
              -> 后续接入PINN/扩散模型/CMA辅助优化
              -> 远期规划：风场下传、重点关注区域(ROI)应用
```

**核心代码根目录**
```
/data/LFT-W02_data/pengxu/stage/centralized_v1
```

**结果输出根目录**
```
/data/LFT-W02_data/pengxu/centralized_v1_output
```
> 重要说明：禁止默认切换至旧版冻结的Stage4/Stage5路径，旧链路仅作历史参考。

---

## 2. 稳定数据源与代码入口
### 2.1 核心输入数据
Stage2 完整版v2：
```
/data/LFT-W02_data/pengxu/centralized_v1_output/stage2_full_v2/stage2_multimodal_summary.json
```
Stage3 完整版v2精简版：
```
/data/LFT-W02_data/pengxu/centralized_v1_output/stage3_full_v2_8w_minimal/stage3_center_summary.json
```

### 2.2 关键代码文件
```
stage/centralized_v1/core/centralized_stage2_multimodal.py
stage/centralized_v1/core/centralized_stage3_center.py
stage/centralized_v1/core/centralized_stage4_ground_recon.py
stage/centralized_v1/core/centralized_stage4_sensitivity.py
stage/centralized_v1/core/centralized_stage4_error_trace.py
stage/centralized_v1/core/centralized_report_stage4_slices.py
stage/centralized_v1/core/centralized_cma_ra_virtual_radial_3dvar.py
stage/centralized_v1/core/centralized_report_cma_virtual_radial.py
stage/centralized_v1/core/centralized_stage4_cma_compare.py
stage/centralized_v1/core/centralized_training_manifest.py
```

### 2.3 配套文档
```
workflow/centralized_v1_docs/README.md
workflow/centralized_v1_docs/new_window_handover_stage2_stage3.md
stage/handover_stage45_20260507/23_centralized_v1_new_window_handover.md
stage/youhua.md
```

---

## 3. 各阶段功能说明
### Stage1
原始数据清洗 + 雷达索引预处理

### Stage2
全源观测数据整合：
读取清洗后的风场数据、定位数据、雷达索引及雷达/云体图像，构建 **31 × 525 × 775** 多模态体素数据集；本阶段**不执行最终风场重构**。

### Stage3
地面中心数据接入、星型拓扑数据封装：
当前主线暂未实现空空通信功能；整合实时风场、历史背景风场、光流场/历史光流场、轨迹数据及置信度诊断指标。

### Stage4
基于**飞机观测严格留一机制**的风场重构：
1. 仅飞机风观测记录可作为真值标签；
2. 融合计算前，必须移除被选为留一样本的飞机观测数据；
3. 光流场、历史光流场**不得作为风场真值**；
4. CMA数据**不得作为真值**。

### Stage5
远期方向：风场应用、数据下传及重点关注区域(ROI)开发；
当前PINN、扩散模型代码仅为代理框架与基础结构，尚未完成深度学习训练。

### Stage6
远期规划：风场-云场耦合研究；**现阶段Stage1~Stage5的评估体系不纳入云量预测任务**。

---

## 4. 不可违背的验证规则
硬性约束条款：
1. 唯一留一真值来源：选定的飞机风观测记录；
2. 融合运算前，必须剔除留一飞机观测数据；
3. 历史风场仅作背景参考，不作为真值标签；
4. 光流场、历史光流场严禁等效为风场使用；
5. CMA数据严禁作为真值；
6. 强制开启：`strict_holdout_no_leakage`（严防数据泄露）；
7. 强制关闭：`motion_used_as_wind`（禁止光流充当风场）。

> 补充说明：禁止将「CMA数据拟合效果」等同于「模型对飞机观测真值的拟合精度」，两类指标需分开统计。

---

## 5. 三大核心技术链路
### 5.1 纯飞机观测基线
**定位**：纯稀疏观测基准模型，不引入CMA数据。
**特性**：
- 采用高斯局地化算法；
- 置信度仅作诊断用途；
- 基于物理规则搭建代理框架；
- 无角色冲突自适应逻辑；
- 仅使用飞机风观测作为真值。
> 该基线为独立评测标准，需与CMA相关分支区分管理。

### 5.2 Stage4 候选版本V2 / TimePower15
**定位**：当前效果最优的传统纯飞机观测Stage4方案。

全帧自适应实验标准参数：
```
--localization-radius-xy 8
--localization-sigma-xy 4
--localization-radius-z 2
--localization-sigma-z 1
--localization-kernel gaussian
--confidence-mode diagnostic_weighted
--physics-constraint-mode pydda_3dvar_proxy
--current-weight-boost 2.0
--context-weight-scale 0.5
--context-time-conf-power 1.5
--role-conflict-mode current_priority_adaptive
--conflict-speed-threshold-mps 12
--conflict-context-factor 0.25
```

参数解读：
1. 优先保障实时风场观测的主导地位；
2. 历史背景风场具备参考价值，但权重做衰减处理；
3. 时间越久远的历史风场，权重衰减越快；
4. 角色冲突逻辑可根据高度、数据密度、历史时长自适应调整。

### 5.3 CMA标准分支
**定位**：CMA作为弱背景场、伪观测、代理场生成的配套链路；用于模型训练与数据融合，**不替代飞机观测真值**。

#### CMA完整流程
1. CMA时间插值：最近邻插值 / 线性插值 / 线性插值+质控；
2. 匹配Stage4标准网格：31 × 525 × 775，垂直层间隔500米；
3. 可选模块：几何感知虚拟径向速度计算；
4. 类三维变分算法完成CMA代理场订正；
5. Stage4弱约束融合：代理场作为背景、再分析场作为背景、CMA作为低置信伪观测。

#### CMA标准运行参数
```
--cma-time-method linear_qc
--geometry-balance-mode los_weighted
--cma-confidence-source temporal_conf
--cma-confidence-cap 0.30
--cma-qc-gating temporal_change
```

#### 注意事项
CMA由6小时分辨率插值至6分钟，仅能提供**低频背景风场结构**，无法还原真实6分钟尺度的对流演变过程。

---

## 6. 当前最优全量实验结果
TimePower15自适应方案全帧结果目录：
```
/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_full_v2_best_adaptive_all_12w_20260529
```

原始汇总指标文件：
```
/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_full_v2_best_adaptive_all_12w_20260529/stage4_localization_sensitivity_aggregate.csv
```

#### 原始全帧总指标（存在偏差）
总帧数：7395
矢量均方根误差：6.6017 m/s
矢量平均绝对误差：5.8093 m/s
> 说明：该结果偏乐观，无留一真值的帧误差会被计为0，不能作为正式评估依据。

#### 分层校正后指标（官方标准）
分层评估文件路径：
```
/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_full_v2_best_adaptive_all_12w_20260529/stratified_eval/stage4_localization_sensitivity_stratified_aggregate.md
```

分层结果解读：
1. **全部帧（原始统计）**
   总帧数：7395 | 均方根误差：6.60 | 平均绝对误差：5.81
2. **仅含留一真值帧（正式评估集）**
   帧数：5614 | 均方根误差：8.70 | 平均绝对误差：7.65
3. **无留一真值帧（未验证重构）**
   帧数：1781 | 误差记为0（无飞机观测真值，无法评测）

#### 细分数据集指标
1. 多留一观测帧（观测数≥3）：2450帧，RMSE=7.58，MAE=5.88
2. 单留一观测压力测试帧：1688帧，RMSE=10.59，MAE=10.59
3. 有效风场观测总数≥10帧：3719帧，RMSE=7.86，MAE=6.34
4. 低误差帧（RMSE≤6）：3611帧，RMSE=3.61，MAE=3.34
5. 高误差帧（RMSE＞6）：2003帧，RMSE=17.86，MAE=15.43

---

## 7. 无留一真值帧说明
**定义**：当前帧无可用飞机风观测数据作为严格评测真值。
**误区纠正**：
- 不代表该帧无法重构；
- 不代表该帧无研究/业务价值；
- 不代表无危险天气；
- 不代表模型结果零误差。

#### 本次全量实验统计
无留一真值帧：1781帧
- 历史风场记录中位数：约505条
- 有效重构体素中位数：约179318个
- 低置信补全体素中位数：约85603个
- 强风体素中位数：约9278个
- 垂直方向风场失配候选体素中位数：约1732个

#### 最终执行规则
1. 无留一帧保留，正常产出业务重构结果；
2. 严格精度评估时**剔除**无留一帧；
3. 对外标注为「未验证重构结果」，同步输出覆盖度、置信度、垂直风场风险等诊断信息。

---

## 8. 500米网格 & 30米风切变阈值说明
1. Stage4 垂直网格：层间隔 **500米**
2. 航空领域临界强风切变标准：**30米垂直层风速差达到6m/s**

#### 两者区别
- Stage4评估指标：单点u/v风矢量重构误差；
- 航空风切变指标：垂直风速梯度/风切变强度；

#### 规范表述
1. 禁止直接等同：不能说「单点误差6m/s 等同于 30米尺度强危险风切变」；
2. 合理表述：若单点风场重构误差接近6m/s，那么模型对30米尺度风切变的研判安全余量不足。

#### 项目定位与后续指标规划
- 当前定位：科研级稀疏飞机观测风场重构模型，**非航空低空风切变预警业务系统**；
- 后续新增指标：垂直风场跳变值、垂直失配度、强风层一致性、风切变风险评分、面向航空场景的分层评估指标。

---

## 9. 典型可视化输出
可视化结果总目录：
```
/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_best_adaptive_representative_visuals_20260529
```

### 典型样例帧
1. 20260214172400：低误差正常样本
2. 20260209104200：误差中等样本
3. 20260210083600：误差接近6m/s临界样本
4. 20260131182400：多留一观测高误差样本
5. 20260204031800：单点极值异常样本
6. 20260127203000：无留一真值、高风险未验证样本

### 可视化索引文件
全域可视化索引：
```
/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_best_adaptive_representative_visuals_20260529/representative_visual_index.md
```
重点区域(ROI)可视化索引：
```
/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_best_adaptive_representative_visuals_20260529/representative_visual_index_roi.md
```
ROI图像目录：
```
/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_best_adaptive_representative_visuals_20260529/visuals_roi
```
ROI区域覆盖统计表：
```
/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_best_adaptive_representative_visuals_20260529/roi_area_coverage.csv
```

### 图像稀疏原因说明
全域总网格：31 × 525 × 775 = 12613125 个体素
全域图中**有效重构区域占比**：0.9% ~ 2.1%

### 可视化默认新参数
```
--crop-mode bbox
--crop-pad 24
--z-levels auto
```

### ROI裁剪效果
1. ROI视图有效可视化占比提升至：9% ~ 17%
2. ROI矩形展示范围：约占中国陆地面积 28.5% ~ 37.9%
3. 实际有效重构范围：约占中国陆地面积 6.7% ~ 11.7%

### 省级覆盖范围
**主要覆盖区域**：广东、广西、海南、福建、江西、湖南、湖北、安徽、河南、重庆、贵州、山西、陕西、四川东部、云南东部、江苏西部/南部、浙江西部/南部、山东西部/南部、河北南部
**边缘零星覆盖**：甘肃东南部、宁夏局部、天津南部、内蒙古南缘极小区域、台湾西缘极小区域

### 可视化重要提醒
Stage4 是**基于观测证据的局部重构模型**，并非全域连续风场产品。图像中浅色/空白区域代表**无有效风场反演结果**，不代表风速为0。

---

## 10. 本次迭代代码更新内容
### 10.1 Stage4 地面风场重构
文件：`stage/centralized_v1/core/centralized_stage4_ground_recon.py`
新增/扩展功能：
1. 支持基于高度、数据密度、历史时长的**角色冲突自适应校准**；
2. 新增字段：角色冲突差值、角色冲突阈值、角色冲突历史因子；
3. 逐点角色冲突诊断、垂直风场失配诊断、孤立强风诊断、强风垂直过度平滑诊断；
4. 新增高误差、极端风速、纯历史风场、垂直风险等点位质控标记。

#### NPZ输出新增字段
```
stage4_role_conflict_mask_3d
stage4_role_conflict_component_gap_3d
stage4_role_conflict_threshold_3d
stage4_role_conflict_context_factor_3d
```

### 10.2 Stage4 误差溯源
文件：`stage/centralized_v1/core/centralized_stage4_error_trace.py`
新增参数：
`--auto-high-error`、`--auto-min-rmse`、`--auto-top-n-frames`
新增内容：分层质控标签、优化建议、逐点角色冲突信息、垂直风险溯源字段。

### 10.3 Stage4 敏感性分析
文件：`stage/centralized_v1/core/centralized_stage4_sensitivity.py`
新增聚合诊断指标：
角色冲突阈值/历史因子均值、垂直失配/过度平滑/孤立强风统计量、扩展型质控指标行。

### 10.4 Stage4 切片可视化
文件：`stage/centralized_v1/core/centralized_report_stage4_slices.py`
新增参数：`--crop-mode full|bbox`、`--crop-pad`、`--z-levels auto`

> 使用规范：分析诊断优先使用ROI裁剪模式；仅查看全域覆盖情况时使用完整视图模式。

---

## 11. 常用运行命令
### 11.1 TimePower15全量指标统计（已完成）
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

### 11.2 选定帧重构（用于可视化）
支持直接使用逗号分隔帧编号
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

### 11.3 ROI区域可视化渲染
`windy310`环境可能缺失绘图依赖，渲染请使用`/opt/miniconda3/bin/python`
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

---

## 12. CMA数据在PINN/扩散模型训练中的定位
### 可用用途
弱监督标签、背景场、预训练目标、模型条件输入、物理/边界约束、教师模型先验。

### 严禁用途
真实6分钟风场真值、等效飞机观测标签、业务最终精度评估标准、30米风切变真值标签。

### 限制原因
CMA由6小时数据插值得到，仅能做时间平滑，**无法还原真实6分钟尺度对流、局地阵风与低空风切变演变**。

### 标准训练范式
$$F_{模型} = F_{TimePower15} + \Delta(残差)$$

#### 推荐模型输入
1. TimePower15输出风场u/v、置信度、重构掩码；
2. 插值后CMA风场u/v/w、时序置信度、风场剧变标记；
3. Stage2雷达/云场二维特征；
4. Stage3历史风场特征；
5. 角色冲突诊断量、垂直失配/过度平滑诊断量、低置信补全掩码。

#### 推荐模型输出
残差$\Delta_u$、残差$\Delta_v$、不确定性场、风切变风险评分。

---

## 13. PINN与扩散模型功能定位
### 物理信息神经网络（PINN）
1. 确定性物理残差修正；
2. 弱散度、平滑性、边界约束建模；
3. 保障垂直风场一致性；
4. 抑制强风区域过度平滑；
5. 修正角色冲突带来的残差。

### 扩散模型（Diffusion）
1. 条件残差集成预测；
2. 修复高误差尾部样本；
3. 局地非线性误差修正；
4. 输出不确定性场；
5. 补强无留一真值高风险区域。

### 执行顺序
1. 先训练、验证PINN残差修正模块；
2. 再接入条件扩散模型，优化局地残差与不确定性；
3. 与TimePower15主链路动态融合，**不做整体替换**。

---

## 14. 多模型融合逻辑
### 最终融合公式
$$
F_{最终} = w_{tp} \cdot F_{TimePower15}
+ w_{pinn} \cdot F_{PINN残差修正结果}
+ w_{diff} \cdot F_{扩散模型均值结果}
+ w_{cma} \cdot F_{CMA插值场}
$$

### 自适应权重规则
1. 飞机观测密集、TimePower15置信度高：提升$w_{tp}$权重；
2. 无留一真值/低置信区域：适度提升$w_{pinn}$、$w_{diff}$，同时降低整体输出置信度；
3. CMA时序置信度高、无风场剧变标记：可小幅提升$w_{cma}$作为背景补充；
4. 强风/垂直风场剧烈变化区域：避免过度平滑，保留风切变梯度特征；
5. 扩散模型不确定性高：降低其权重，并标记风险等级。

### 核心约束
飞机观测点位附近，深度学习模型**不得覆盖/篡改**基于实测数据的TimePower15结果。

---

## 15. 高误差样本与质控经验
### 典型极值样本
1. 20260204031800：先验场风速超出合理范围，矢量误差约147m/s，仅依赖历史风场支撑，需单独标记、分层统计；
2. 20260126003600 / 20260126003000：全量实验最高误差约244m/s，属于单留一观测压力测试样本。

### 处理原则
1. 禁止直接删除异常帧；
2. 统一做误差溯源、分层质控；
3. 仅依据明确规则剔除无效观测数据；
4. 正常观测样本精度、压力测试样本精度分开汇报。

---

## 16. 后续报告规范
### 必须包含内容
1. 全量重构总帧数；
2. 仅留一真值集的RMSE/MAE（核心指标）；
3. 无留一帧数量及未验证诊断信息；
4. 单留一压力测试子集指标；
5. 多留一有效观测子集指标；
6. 高误差尾部分位数（P90/P95/P99）；
7. 强风、垂直失配、角色冲突子集指标；
8. 数据泄露开关、光流禁用开关状态。

### 禁止出现内容
1. 将「包含无留一零误差帧的全量指标」作为核心精度结果；
2. 将CMA拟合效果等效为飞机观测真值精度；
3. 仅用图像视觉疏密程度描述物理覆盖范围（必须区分重构掩码）。

---

## 17. 下一步执行计划
1. 固定TimePower15全量结果为当前最优传统基线；
2. 以分层评估结果作为官方精度依据；
3. 使用ROI可视化完成逐帧诊断；
4. 对正常样本、压力测试样本开展高误差溯源分析；
5. 按时间维度划分训练集/验证集/测试集；
6. 生成线性插值+质控后的CMA对齐场，作为模型弱背景输入；
7. 构建训练清单，关联Stage2原始帧、Stage4结果、CMA数据、飞机观测标签、各类掩码；
8. 训练PINN残差修正模块；
9. 接入条件扩散模型，优化残差与不确定性；
10. 所有验证工作**仅基于飞机严格留一数据集**。

---

## 18. 已知实际限制与注意事项
1. 敏感性分析仅输出指标，**不存储全量三维NPZ文件**；如需可视化，单独运行重构脚本；
2. 无留一帧可用于业务，但结果属于未验证状态；
3. ROI裁剪优化了图像可读性，不代表裁剪区域内所有像素均有有效风场结果，必须以重构掩码为准；
4. 当前Stage4垂直网格500米间隔，**无法直接评估30米尺度风切变**；
5. `windy310`环境缺少绘图库，可视化渲染请使用`/opt/miniconda3/bin/python`。

---

## 19. 项目现状总结（一句话）
本项目已完成TimePower15自适应方案12进程全量Stage4传统风场重构、分层评估体系、ROI可视化诊断、自适应角色冲突与垂直风险诊断模块；后续核心路线：以CMA为弱背景与模型条件输入，坚守飞机严格留一真值规则，在TimePower15主链路基础上叠加PINN、扩散模型，实现残差修正与不确定性评估，**不替换原有主链路**。

---

## 20. 2026-05-29 Stage4/CMA 最新补充

### 20.1 TimePower15 全量结果复核

Stage4 全量结果符合当前 strict holdout 要求：

```text
目录: /data/LFT-W02_data/pengxu/centralized_v1_output/stage4_full_v2_best_adaptive_all_12w_20260529
帧数: 7395
strict_holdout_no_leakage: true for all frames
motion_used_as_wind: false for all frames
```

官方误差只看：

```text
/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_full_v2_best_adaptive_all_12w_20260529/stratified_eval/stage4_localization_sensitivity_stratified_aggregate.md
```

核心指标：

```text
eval_holdout_only RMSE/MAE: 8.696082 / 7.652211 m/s
weighted RMSE/MAE: 14.819533 / 6.724179 m/s
multi_holdout_supported RMSE/MAE: 7.882480 / 6.389791 m/s
single_holdout_pressure_test RMSE/MAE: 10.588383 / 10.588383 m/s
no_holdout_unverified_reconstruction: 1781 frames, RMSE/MAE blank by design
```

依据：飞机风观测是本项目正式 truth，no-holdout 只做业务诊断。参考 WMO aircraft-based observations `https://wmo.int/aircraft-based-observations-programme` 和 Mode-S/EHS 风观测误差研究 `https://amt.copernicus.org/articles/9/4141/2016/`。

### 20.2 代表帧可视化

已生成 6 帧 baseline 与 vertical-risk candidate 对照图：

```text
/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_timepower15_representative_20260529/baseline_visuals
/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_timepower15_representative_20260529/vertical_risk_visuals
```

每套包含 6 张 slices PNG、6 张 diagnostics PNG、6 个 slice stats CSV。代表帧覆盖 low-error、median、6m/s边界、高误差多候选、极端单候选、no-holdout高风险。参考：PyDDA/3DVAR 约束风场反演需要同时审查场、约束和诊断，不应只看单一全局平均。PyDDA `https://openradarscience.org/PyDDA/`。

### 20.3 垂直失配和过平滑修补

代码补丁：

```text
stage/centralized_v1/core/centralized_stage4_ground_recon.py
stage/centralized_v1/core/centralized_stage4_sensitivity.py
```

新增参数：

```text
--vertical-risk-mode off|preserve_strong_layers
--vertical-gradient-preserve-weight
--vertical-context-mismatch-damping
```

默认值仍为 `off`。`preserve_strong_layers` 采用各向异性思路：强风/垂直失配/过平滑候选体素不再使用完整 6 邻域跨层平滑，而使用水平 4 邻域，并对高置信锚点回拉，避免跨高度层过度扩散。代表帧小样本没有稳定改善 RMSE 或垂直诊断，因此该补丁当前只是消融候选，不能作为主线默认。参考：Perona-Malik 各向异性扩散 `https://doi.org/10.1109/34.56205`；PyDDA/3DVAR 风场约束 `https://openradarscience.org/PyDDA/`。

### 20.4 CMA/PINN/Diffusion manifest

已启动 CMA 数据接入清单：

```text
/data/LFT-W02_data/pengxu/centralized_v1_output/training_manifest_cma_pinn_diffusion_20260529/centralized_training_manifest.json
/data/LFT-W02_data/pengxu/centralized_v1_output/training_manifest_cma_pinn_diffusion_20260529/centralized_training_manifest.md
```

统计：

```text
frames_total: 7395
frames_with_stage4_metrics: 7395
frames_with_cma_raw_wind_bracket: 7395
cma_raw_file_count: 773
cma_raw_wind_time_count: 129
train/val/test: 5176/1109/1110
```

训练边界：

```text
CMA/CRA40 = 弱背景、条件输入、边界/物理约束，不是 truth
PINN = F_timepower15 + delta_u/delta_v
Diffusion = PINN 后的局地残差、不确定性、低置信补全
正式验证 = aircraft holdout only
```

参考：PINN 物理约束神经网络 `https://doi.org/10.1016/j.jcp.2018.10.045`；GenCast 扩散集合天气预报与不确定性表达 `https://www.nature.com/articles/s41586-024-08252-9`；CRA40/CMA 再分析背景资料 `https://doi.org/10.1007/s13351-023-2086-x`。

## 21. 2026-06-01 三方法 200 帧严格 holdout 对比补充

本节记录 2026-05-31 重新覆盖的 Stage4 三方法对比。旧 4 帧小样本结论已作废，正式参考本节和输出目录：

```text
/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_three_method_compare_20260531
```

### 21.1 三条分支定义

1. 纯航空器 baseline：
   `gaussian`，`diagnostic_only`，`proxy` 物理约束，XY radius/sigma = 12/6，Z radius/sigma = 2/1，`role_conflict_mode=off`，不引入 CMA。
2. TimePower15 optimal adaptive：
   `gaussian`，`diagnostic_weighted`，`pydda_3dvar_proxy`，XY radius/sigma = 8/4，Z radius/sigma = 2/1，`current_weight_boost=2.0`，`context_weight_scale=0.5`，`context_time_conf_power=1.5`，`role_conflict_mode=current_priority_adaptive`。
3. CMA weak-background branch：
   继承 TimePower15 optimal adaptive 参数，并加入 `cma_proxy_background`，`cma_background_weight=0.1`，`cma_confidence_source=temporal_conf`，`cma_confidence_cap=0.3`，`cma_qc_gating=temporal_change`。CMA 只作弱背景，不作 truth。

### 21.2 200 帧轻量指标结论

样本为固定 seed `20260531` 抽取的 200 个 strict aircraft holdout 帧，共 530 个 holdout 点。主对比只输出 CSV/MD 指标，不保存 200 帧 full NPZ。

```text
method              frames  holdout_points  frame RMSE/MAE       weighted RMSE/MAE
aircraft baseline   200     530             11.6898 / 10.3011    18.9184 / 10.3509
TimePower15         200     530              8.6365 /  7.4232    15.0387 /  7.1727
CMA weak bg         200     530              9.3770 /  8.0171    14.9638 /  7.8683
```

逐帧胜负：

```text
TimePower15 vs baseline: 143 win / 56 loss / 1 tie, mean delta RMSE = -3.053 m/s
CMA vs TimePower15:       66 win / 134 loss / 0 tie, mean delta RMSE = +0.741 m/s
CMA vs baseline:         115 win / 85 loss / 0 tie, mean delta RMSE = -2.313 m/s
```

结论：200 帧结果证明 TimePower15 总体优于纯航空器 baseline。此前 4 帧小样本中“TimePower15 更差”的判断是抽样偏差。TimePower15 输给 baseline 的 56 帧多属于局部情形：8/4 窄核和 current-priority adaptive 会减少上下文外推；当 holdout 点恰好依赖更宽核上下文支撑时，baseline 的 12/6 宽核平滑可能偶然更接近 holdout。CMA 弱背景能兜底部分极端坏帧，但也会把局地飞机观测结构拉向大尺度背景，因此整体不如 TimePower15 稳定。

严格边界保持不变：

```text
all_strict_holdout_no_leakage = True
any_motion_used_as_wind = False
CMA used as background_not_truth = True
no-holdout frames are not official RMSE/MAE
```

### 21.3 代表帧 full NPZ 和可视化

代表帧只对 6 帧生成 full NPZ 与图件：

```text
20260206074200  TimePower15 strongest improvement: baseline 74.105, TP 3.265, CMA 5.221
20260125124200  baseline strongest win: baseline 4.132, TP 32.594, CMA 8.602
20260205190000  CMA strongest improvement vs TP: baseline 86.000, TP 86.000, CMA 32.619
20260216015400  CMA strongest degradation vs TP: baseline 32.713, TP 29.007, CMA 66.290
20260126090000  near 6 m/s boundary: baseline 5.999, TP 2.230, CMA 5.401
20260223133000  high-error multi-holdout: baseline 117.236, TP 108.858, CMA 109.389
```

输出：

```text
analysis report:
/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_three_method_compare_20260531/analysis/three_method_compare_analysis.md

merged frame table:
/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_three_method_compare_20260531/analysis/three_method_200_frame_merged.csv

representative NPZ:
/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_three_method_compare_20260531/representative_npz/aircraft_baseline
/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_three_method_compare_20260531/representative_npz/timepower15
/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_three_method_compare_20260531/representative_npz/cma_proxy_background

representative visuals:
/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_three_method_compare_20260531/representative_visuals/aircraft_baseline
/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_three_method_compare_20260531/representative_visuals/timepower15
/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_three_method_compare_20260531/representative_visuals/cma_proxy_background
/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_three_method_compare_20260531/representative_visuals/cma_proxy_field
```

校验：

```text
representative frames: 6
baseline/timepower15/cma NPZ: 6 / 6 / 6
baseline/timepower15/cma Stage4 slice PNG: 6 / 6 / 6
CMA proxy field PNG: 6
max representative RMSE diff between full NPZ and metrics CSV: 0.0
```

校验文件：

```text
/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_three_method_compare_20260531/analysis/representative_npz_visual_validation.json
```

### 21.4 代码修改

`stage/centralized_v1/core/centralized_stage4_sensitivity.py` 已扩展为支持 CMA weak-background 的 metrics-only 对比，避免为了 200 帧指标主对比保存 full NPZ。新增能力：

```text
--cma-fusion-mode off|cma_proxy_background|cma_reanalysis_background|cma_pseudo_observation
--cma-proxy-dir
--cma-proxy-npz
--cma-background-weight
--cma-confidence-source
--cma-confidence-cap
--cma-time-confidence
--cma-space-confidence
--cma-pseudo-source
--cma-qc-gating
```

实现上复用 `centralized_stage4_ground_recon.py` 中的 CMA helper：读取 CMA proxy、应用 CMA background 到 accumulator、对 CMA-only 体素置信度封顶，并在输出表中记录 `cma_temporal_conf_mean`、`cma_rapid_change_fraction`、`cma_background_active_voxels`、`cma_used_as_background_not_truth` 等诊断列。分片并行路径也同步透传 CMA 参数。

后续新窗口注意：如果继续做三方法或 CMA 消融，优先使用该 metrics-only 路径批量评估；只在筛出的代表帧上生成 NPZ/PNG。不要再用 4 帧小样本推断总体优劣。

## 22. 2026-06-02 Stage4 误差来源与逐步解决路线

新增正式交接文档：

```text
/data/LFT-W02_data/pengxu/workflow/centralized_v1_docs/new_window_project_handover_20260529/centralized_v1_stage4_error_resolution_plan_20260602.md
```

该文档把 `timepower15` 与 `adaptive_v3` 的 200 帧 strict holdout 结果转成下一步执行计划：

```text
timepower15 weighted vector RMSE = 15.038701 m/s
adaptive_v3 weighted vector RMSE = 14.932605 m/s
improvement = -0.106096 m/s, about -0.71%
holdout points = 530
strict_holdout_no_leakage = True
motion_used_as_wind = False
```

结论：`adaptive_v3` 是当前更均衡的 Phase 2 候选，但只是小幅稳定提升。它改善了
`baseline_rmse_10_20` 区间，未解决 P99/max 长尾。

当前误差优先级：

```text
1. vertical_structure
2. representation_error
3. sparse_support
4. role_conflict
5. temporal_weighting
6. tail_qc
7. localization
```

下一步不要继续只调一个全局 localization 半径。先按路线图跑：

```text
Phase 1: adaptive_v3_vertical_preserve
Phase 1: adaptive_v3_timepower_1.0 / adaptive_v3_timepower_2.0
Phase 2: support-aware / role-aware adaptive localization code patch
Phase 3: P95/P99/max tail audit and guardrail
Phase 4: 200 frames pass before larger holdout-only or 5614-frame strict evaluation
```

每个候选跑完后统一执行：

```text
stage/centralized_v1/core/centralized_stage4_pairwise_frame_compare.py
stage/centralized_v1/core/centralized_stage4_error_source_decomposition.py
```

新增/已使用输出：

```text
/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_adaptive_localization_v3_200_20260602/analysis_v3/timepower15_vs_adaptive_v3.md
/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_adaptive_localization_v3_200_20260602/error_source_decomposition/timepower15_vs_adaptive_v3_error_sources.md
```

论文指标解释边界：de Haan / EMADDC 的 aircraft observation sigma 只能说明飞机风观测误差下限。
当前 Stage4 的 `component RMSE` 约 `10.56 m/s`，主要是 reconstruction、representativeness、
sparse support、temporal mismatch、vertical extrapolation 等误差叠加，不能写成飞机观测本身不准。

## 23. 2026-06-05 dynamic vertical localization 与 weak NWP background demo

新增输出：

```text
/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_dynamic_layer_nwp_oi_demo_20260605/
```

新增/补齐代码：

```text
stage/centralized_v1/core/centralized_stage4_sensitivity.py
```

补齐点：

```text
--vertical-localization-policy fixed|support_adaptive
```

该参数现在可进入 metrics-only sensitivity 路径、25 路 shard 子进程、聚合 CSV/MD 和 run metadata。底层实现仍复用 `centralized_stage4_ground_recon.py` 的 `_dynamic_vertical_localization()`。

### 23.1 demo 口径

共同设置：

```text
sample_count = 25
sample_seed = 20260605
num_workers = 25
param_grid = 8,4,2,1
kernel = gaussian
confidence_mode = diagnostic_weighted
physics_constraint_mode = pydda_3dvar_proxy
localization_policy = diagnostic_adaptive_v3
localization_candidate_grid = 8:4,10:5
context_time_conf_power = 2.6
conflict_speed_threshold_mps = 11.0
vertical_risk_mode = preserve_strong_layers
```

评价边界：

```text
truth = current aircraft wind_records strict holdout
holdout 在融合前移除
CMA/GFS/ERA 只能作为 weak background / prior
location/motion 不作为 wind truth
radar PNG 不作为 Doppler wind
```

本地未发现可直接消费的 GFS/ERA ROI NPZ，所以 weak NWP demo 使用已有 CMA proxy/reanalysis 背景。这个分支只验证 weak-background 接入和 strict-holdout 比较口径，不把 CMA 当 truth。

### 23.2 dynamic vertical localization 结果

点级 strict holdout，58 个 holdout 点：

```text
dynamic_fixed_aircraft_only:
  RMSE = 26.589947
  MAE  = 9.812196
  P95  = 40.764004
  max  = 180.131789

dynamic_support_adaptive_aircraft_only:
  RMSE = 26.742449
  MAE  = 9.876736
  P95  = 39.704757
  max  = 180.613923
```

`support_adaptive` 的 vertical sigma factor mean 为 `0.865060`，说明它确实收窄了垂直影响范围。但本 demo 中总 RMSE/MAE 没有改善，只是 P95 略好。结论：暂不升为 official 默认，继续作为分层触发候选。

### 23.3 OI / 3DVar-style weak background 结果

对比：

```text
aircraft-only fixed:
  RMSE = 26.589947
  MAE  = 9.812196

aircraft + weak CMA background, weight 0.03:
  RMSE = 26.745099
  MAE  = 9.905763

aircraft + very weak CMA background, weight 0.01:
  RMSE = 26.639229
  MAE  = 9.839657
```

结论：weak CMA background 当前没有超过 aircraft-only。下一步不要全场固定权重融合 NWP；应改成 sparse/no-current-support fallback，或按 altitude / region / context_time_conf 分层启用。

### 23.4 文献对比口径

可以直接做对比的方向：

```text
1. Sun et al. 2018, aircraft surveillance weather-field reconstruction / Meteo-Particle Model
2. Marinescu et al. 2022, aircraft-derived wind GPR / Kriging-style local reconstruction
3. de Haan 2016, Mode-S EHS aircraft-derived wind observation error
4. EMADDC 2025, operational aircraft weather observations and QC
5. Cardinali et al. 2003 / Petersen 2016, aircraft data in 4DVAR/NWP
```

注意：这些文献多数是局部 TMA/receiver coverage、NWP assimilation impact 或 aircraft-derived observation QC，不是全国 current-aircraft strict holdout。对比时要把它们改造成同一 strict-holdout benchmark，不能直接拿文献指标和本项目 RMSE 做绝对优劣比较。

### 23.5 全国重构与局部 holdout

当前正确表述：

```text
全国重构 = product footprint
局部 holdout = validated accuracy footprint
```

可以在全国境内生成三维风场，但 official accuracy 只能在 aircraft `wind_records` strict holdout 覆盖到的时空点上报告。无飞机 holdout 的全国区域只能报告 coverage/confidence/background diagnostics，不能报告 validated RMSE。

建议下一步做两个实验包：

```text
1. 全国产品包：recon + confidence + coverage + weak background diagnostics。
2. 局部论文对比包：选机场/TMA 或高密航路区域，对齐 Sun/Marinescu 这类局部重构论文。
```
