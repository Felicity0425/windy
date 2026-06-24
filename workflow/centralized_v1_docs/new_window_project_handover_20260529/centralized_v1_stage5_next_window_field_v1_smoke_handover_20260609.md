# Centralized V1 Stage5 Next Window Handover: Residual PINN Field V1 Smoke

Date: 2026-06-09

## 1. 当前结论

Stage5 residual PINN 已经从最初的小样本 point-level report，推进到 full tp26 point dataset 的 GPU sweep 和 truth-free narrow gate selection。

当前唯一可以进入下一窗口 `field_v1 smoke` 的非零候选是：

```text
candidate: cap1p0_seed20260609_w512_l6
checkpoint:
  centralized_v1_output/stage5_residual_pinn_full_tp26_gpu_sweep_narrow_train_20260609/train_cap1p0_seed20260609_w512_l6/checkpoint.pt
gate:
  vertical_gap_ge20_not_light
scale:
  1.0
```

严格边界：

```text
Stage4 default remains:
  tp26_thr11_preserve

Stage5 candidate formula:
  F_stage5 = F_tp26 + selected_gate * clipped_residual_delta

Stage5 must not replace tp26.
Stage5 must not become default before full-field smoke and strict holdout pairwise pass.
```

## 2. 本窗口完成的代码改动

已提交并推送：

```text
1d8b4d9 Refine Stage5 narrow gate selection
1b0cf15 Add Stage5 full-data GPU sweep runner
591eb1b Add Stage5 residual PINN gated audit
dfdc58b Add Stage5 residual PINN report workflow
6d66269 Add Stage5 residual PINN plan
```

核心代码：

| file | change |
| --- | --- |
| `stage/centralized_v1/core/centralized_stage5_residual_pinn_dataset.py` | 构建 point-level residual PINN 数据集，使用 frame/time split，排除 truth/eval leakage columns。 |
| `stage/centralized_v1/core/centralized_stage5_residual_pinn_train.py` | 训练 residual MLP，输出 checkpoint、normalizer、train metrics、predictions。 |
| `stage/centralized_v1/core/centralized_stage5_residual_pinn_regime_audit.py` | 做 regime/bucket audit，定位 PINN 改善和劣化区域。 |
| `stage/centralized_v1/core/centralized_stage5_residual_pinn_gate_select.py` | 新增 `narrow_safe` rule profile、`stable_safe` selection policy、`vertical_gap_ge10/20/30_not_light`、`--max-enabled-fraction`。 |
| `stage/centralized_v1/core/centralized_stage5_residual_pinn_gpu_sweep.py` | 新增 full-data GPU sweep、`--gate-only`、`--train-root`、GPU 0/1/2 并发训练、policy passthrough。 |
| `stage/centralized_v1/core/centralized_stage5_residual_pinn_apply.py` | 当前仍是 point-report apply，不是 full-field apply。下一窗口 field smoke 需要新增或扩展 full-field apply。 |

## 3. 数据集与训练情况

Full tp26 point dataset：

```text
source:
  centralized_v1_output/stage4_full_tp26_thr11_preserve_25w_taildiag_20260602_173319/stage4_point_departures.csv

output:
  centralized_v1_output/stage5_residual_pinn_full_tp26_gpu_sweep_narrow_train_20260609/dataset_full_tp26/

frames:
  5614

points:
  15054
```

Split：

| split | frames | points | baseline RMSE | baseline MAE | >=30mps tail |
| --- | ---: | ---: | ---: | ---: | ---: |
| train | 3930 | 11044 | 15.298961 | 6.807320 | 407 |
| val | 842 | 2117 | 13.805729 | 5.870153 | 64 |
| test | 842 | 1893 | 9.896785 | 5.217920 | 25 |

GPU：

```text
GPU IDs used:
  0,1,2

training command uses:
  CUDA_VISIBLE_DEVICES=<physical_gpu_id>

inside each process:
  resolved device = cuda:0
  cuda available = True
  cuda device = NVIDIA GeForce RTX 4090
```

注意：每个候选只使用约 113 MB GPU memory。原因不是没有用 GPU，而是当前模型仍是 point-level MLP，数据量 15054 点，网络宽度 512、6 层，对 4090 来说很小。

## 4. Full-Data Narrow Sweep 结果

Result root：

```text
centralized_v1_output/stage5_residual_pinn_full_tp26_gpu_sweep_narrow_train_20260609/
```

Main report：

```text
centralized_v1_output/stage5_residual_pinn_full_tp26_gpu_sweep_narrow_train_20260609/sweep_report.md
```

Ranking：

| candidate | cap | seed | gate | scale | test enabled | raw test dRMSE | gated test dRMSE | dP95 | dP99 | dLight | dFloor10 | test gate |
| --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| `cap1p0_seed20260609_w512_l6` | 1.000 | 20260609 | `vertical_gap_ge20_not_light` | 1.000 | 33/1893 | -0.004006 | -0.004433 | -0.119179 | -0.035294 | +0.000000 | -0.000029 | PASS |
| `cap1p0_seed20260610_w512_l6` | 1.000 | 20260610 | `baseline_no_stage5` | 0.000 | 0/1893 | +0.009151 | +0.000000 | +0.000000 | +0.000000 | +0.000000 | +0.000000 | PASS |
| `cap3p0_seed20260608_w512_l6` | 3.000 | 20260608 | `risk_0p20_to_0p50_not_light` | 1.000 | 308/1893 | +0.013458 | -0.022809 | -0.159469 | +0.307052 | +0.012600 | +0.000036 | FAIL |
| `cap3p0_seed20260610_w512_l6` | 3.000 | 20260610 | `vertical_gap_ge10_not_light` | 0.750 | 94/1893 | -0.003672 | -0.018084 | -0.147291 | +0.300427 | +0.002270 | -0.000055 | FAIL |
| `cap3p0_seed20260609_w512_l6` | 3.000 | 20260609 | `risk_ge_0p25_not_light` | 1.000 | 185/1893 | +0.010779 | -0.008911 | -0.038714 | +0.238181 | +0.004622 | -0.000183 | FAIL |

Interpretation：

```text
cap=3.0:
  RMSE gain can be larger, but P99/light/floor10 guardrails fail.

cap=0.5:
  correction is too weak or unstable; P95/floor10 often fail.

cap=1.0 seed20260609:
  only nonzero locked test PASS.
```

## 5. Winner Locked Metrics

Selected gate：

```text
rule:
  vertical_gap_ge20_not_light

description:
  enable where vertical gap/jump proxy >= 20 m/s and not pred-light

selection:
  val only

test:
  locked after val selection
```

Locked test：

| metric | baseline | gated Stage5 | delta |
| --- | ---: | ---: | ---: |
| RMSE | 9.896785 | 9.892352 | -0.004433 |
| MAE | 5.217920 | 5.216535 | -0.001385 |
| P95 | 13.157155 | 13.037976 | -0.119179 |
| P99 | 43.020285 | 42.984991 | -0.035294 |
| light RMSE | 5.086997 | 5.086997 | +0.000000 |
| floor10 relative MAE | 0.197422 | 0.197393 | -0.000029 |

Guardrail：

```text
weighted_rmse_not_worse: PASS
p95_not_worse: PASS
p99_not_worse: PASS
light_rmse_not_worse: PASS
light_mae_not_worse: PASS
floor10_not_worse: PASS
no_new_light_moderate_tail_failure: PASS
high_error_count_not_worse: PASS
POINT_REPORT_OVERALL: PASS
```

Important caution：

```text
Raw all-point residual for this same checkpoint worsens test light RMSE:
  5.086998 -> 5.133368

Therefore do not apply Stage5 globally.
Only apply it through the selected truth-free gate.
```

## 6. Visualizations

All images are generated from the narrow train output and stored here:

```text
centralized_v1_output/stage5_residual_pinn_full_tp26_gpu_sweep_narrow_train_20260609/visualizations/
```

### 6.1 Locked Test Ranking

![locked test ranking](../../../centralized_v1_output/stage5_residual_pinn_full_tp26_gpu_sweep_narrow_train_20260609/visualizations/stage5_locked_test_rmse_ranking.png)

### 6.2 Guardrail Delta Heatmap

![guardrail heatmap](../../../centralized_v1_output/stage5_residual_pinn_full_tp26_gpu_sweep_narrow_train_20260609/visualizations/stage5_guardrail_delta_heatmap.png)

### 6.3 Dataset Split Summary

![dataset split summary](../../../centralized_v1_output/stage5_residual_pinn_full_tp26_gpu_sweep_narrow_train_20260609/visualizations/stage5_dataset_split_summary.png)

### 6.4 Selected Gate Before/After

![selected gate before after](../../../centralized_v1_output/stage5_residual_pinn_full_tp26_gpu_sweep_narrow_train_20260609/visualizations/stage5_selected_gate_before_after.png)

### 6.5 Selected Candidate Training Curve

![training curve](../../../centralized_v1_output/stage5_residual_pinn_full_tp26_gpu_sweep_narrow_train_20260609/visualizations/stage5_selected_candidate_training_curve.png)

## 7. Reproduction Commands

### 7.1 Full GPU Narrow Train

```bash
cd /data/LFT-W02_data/pengxu
sudo nvidia-modprobe -u -c=0
nvidia-smi

/data/LFT-W02_data/pengxu/.conda/envs/windy310/bin/python \
  stage/centralized_v1/core/centralized_stage5_residual_pinn_gpu_sweep.py \
  --point-departures centralized_v1_output/stage4_full_tp26_thr11_preserve_25w_taildiag_20260602_173319/stage4_point_departures.csv \
  --out-root centralized_v1_output/stage5_residual_pinn_full_tp26_gpu_sweep_narrow_train_20260609 \
  --gpu-ids 0,1,2 \
  --caps 0.5,1.0,3.0 \
  --seeds 20260608,20260609,20260610 \
  --width 512 \
  --layers 6 \
  --batch-size 2048 \
  --max-epochs 1200 \
  --patience 160 \
  --learning-rate 8e-4 \
  --rule-profile narrow_safe \
  --selection-policy stable_safe \
  --promotion-safe-retain-fraction 0.50 \
  --max-enabled-fraction 0.35 \
  --min-enabled 10
```

### 7.2 Fast Gate-Only Re-Eval

Use this when the checkpoints already exist and only the gate policy changes.

```bash
cd /data/LFT-W02_data/pengxu

/data/LFT-W02_data/pengxu/.conda/envs/windy310/bin/python \
  stage/centralized_v1/core/centralized_stage5_residual_pinn_gpu_sweep.py \
  --point-departures centralized_v1_output/stage4_full_tp26_thr11_preserve_25w_taildiag_20260602_173319/stage4_point_departures.csv \
  --dataset-dir centralized_v1_output/stage5_residual_pinn_full_tp26_gpu_sweep_narrow_train_20260609/dataset_full_tp26 \
  --train-root centralized_v1_output/stage5_residual_pinn_full_tp26_gpu_sweep_narrow_train_20260609 \
  --out-root centralized_v1_output/stage5_residual_pinn_full_tp26_gpu_sweep_narrow_gate_retry_20260609 \
  --gpu-ids 0,1,2 \
  --caps 0.5,1.0,3.0 \
  --seeds 20260608,20260609,20260610 \
  --width 512 \
  --layers 6 \
  --rule-profile narrow_safe \
  --selection-policy stable_safe \
  --promotion-safe-retain-fraction 0.50 \
  --max-enabled-fraction 0.35 \
  --min-enabled 10 \
  --gate-only
```

### 7.3 Point Apply Sanity Check

This does not produce a full field. It only verifies the checkpoint can be applied to the point dataset.

```bash
cd /data/LFT-W02_data/pengxu

/data/LFT-W02_data/pengxu/.conda/envs/windy310/bin/python \
  stage/centralized_v1/core/centralized_stage5_residual_pinn_apply.py \
  --dataset-dir centralized_v1_output/stage5_residual_pinn_full_tp26_gpu_sweep_narrow_train_20260609/dataset_full_tp26 \
  --checkpoint centralized_v1_output/stage5_residual_pinn_full_tp26_gpu_sweep_narrow_train_20260609/train_cap1p0_seed20260609_w512_l6/checkpoint.pt \
  --out-dir centralized_v1_output/stage5_residual_pinn_field_v1_smoke_20260609/point_apply_winner
```

## 8. 下一窗口执行顺序

### Step 1: 不改默认

Do not modify Stage4 default.

```text
default:
  tp26_thr11_preserve

candidate only:
  tp26_residual_pinn_field_v1_smoke
```

### Step 2: 新增或扩展 full-field apply

Current script status：

```text
centralized_stage5_residual_pinn_apply.py
  supports point-report dataset only
  does not write Stage5 full-field NPZ
```

Next script should be one of：

```text
stage/centralized_v1/core/centralized_stage5_residual_pinn_field_apply.py
```

or extend `centralized_stage5_residual_pinn_apply.py` with a separate full-field mode.

Required field behavior：

```text
1. Load Stage4 tp26 field for a small list of frames.
2. Build the same normalized feature schema used by report_v1 where possible.
3. Run checkpoint:
     train_cap1p0_seed20260609_w512_l6/checkpoint.pt
4. Compute truth-free gate:
     vertical_gap_ge20_not_light
5. Apply:
     u_stage5 = u_tp26 + gate * delta_u
     v_stage5 = v_tp26 + gate * delta_v
6. Use scale = 1.0.
7. Do not change cells where gate is false.
8. Do not overwrite Stage4 default outputs.
9. Write a separate candidate directory.
```

Candidate output name：

```text
centralized_v1_output/stage5_residual_pinn_field_v1_smoke_20260609/
```

### Step 3: Field smoke on 2-5 representative frames

Use val frames first for smoke selection. These are frames where the selected truth-free gate has hits in val：

```text
20260215010000
20260216081800
20260215151200
20260216163000
20260217000000
```

Smoke checks：

```text
NPZ exists for each frame.
u/v arrays have the same shape as Stage4 tp26.
Only gate-hit cells differ from tp26.
Non-gate cells are bitwise or near-bitwise identical to tp26.
No NaN/Inf.
Max absolute residual <= 1.0 m/s before scale.
No unexpected change in display-filled/no-claim areas.
Visual slices show local corrections only, not global smoothing.
```

### Step 4: Point projection check on smoke frames

After field NPZ is written, project aircraft holdout points onto the Stage5 field using the same Stage4 point departure evaluator.

Required comparison：

```text
baseline:
  Stage4 tp26 field

candidate:
  Stage4 tp26 + selected_gate * residual_delta
```

The candidate may continue only if：

```text
weighted RMSE not worse
P95 not worse
P99 not worse
light RMSE not worse
light MAE not worse
floor10 relative MAE not worse
new light/moderate tail failures = 0
high error >=30 count not worse
```

### Step 5: Strict holdout pairwise

Only after smoke passes：

```text
run 200-frame strict pairwise against tp26_thr11_preserve
candidate label:
  tp26_residual_pinn_field_v1_smoke
```

Promotion rule：

```text
Stage5 can be discussed as a candidate only if full-field strict pairwise passes.
Stage5 still should not become default unless it improves more than numerical noise and does not harm long-tail/light/floor10.
```

## 9. 禁止事项

Do not：

```text
1. Do not use cap=3.0 globally.
2. Do not enable broad risk gates to chase RMSE.
3. Do not correct pred-light cells.
4. Do not use test labels to choose a new gate.
5. Do not train on validation/test aircraft labels.
6. Do not use motion_records/context_motion_records as wind truth.
7. Do not overwrite Stage4 tp26 outputs.
8. Do not call current report_v1 MLP a full-field PINN.
```

## 10. 后续优化方向

The current gain is small because the safe gate covers only 33/1893 test points.

Correct direction：

```text
Increase data in high-altitude / strong-wind / vertical-gap regimes.
Keep narrow gates.
Improve field feature construction.
Add truth-free field collocation losses later.
Use weak physical regularization carefully.
```

Wrong direction：

```text
Widen the gate just to improve RMSE.
Use cap=3.0 as default.
Apply raw residual everywhere.
Treat background/NWP/CMA/motion as truth.
```

## 11. Handover Summary

下一窗口可以直接从以下固定配置开始：

```text
Stage4 baseline:
  tp26_thr11_preserve

Stage5 checkpoint:
  centralized_v1_output/stage5_residual_pinn_full_tp26_gpu_sweep_narrow_train_20260609/train_cap1p0_seed20260609_w512_l6/checkpoint.pt

Stage5 gate:
  vertical_gap_ge20_not_light

Stage5 scale:
  1.0

Stage5 mode:
  field_v1 smoke only

Default promotion:
  not allowed before full-field smoke + 200-frame strict pairwise PASS
```
