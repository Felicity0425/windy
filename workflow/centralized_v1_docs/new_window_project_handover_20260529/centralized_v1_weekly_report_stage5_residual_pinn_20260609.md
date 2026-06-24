# Centralized V1 Weekly Report: Stage5 Residual PINN

Date: 2026-06-09

## 1. 本周目标

本周目标是判断 Stage5 residual PINN 是否能作为 Stage4 `tp26_thr11_preserve` 后面的安全 residual correction，而不是替换 Stage4。

重点问题：

```text
1. PINN 是否真的改善 Stage4 tp26 的 aircraft point error。
2. 改善在哪些 regime/bucket 出现，劣化在哪些 bucket 出现。
3. 是否能用 validation-only truth-free gate 锁定 test。
4. 是否可以进入 field_v1 smoke。
5. 是否使用 GPU 训练。
```

## 2. 本周完成

### 2.1 建立 Stage5 point-level residual PINN workflow

完成内容：

```text
dataset builder
residual MLP trainer
point apply
point compare
regime audit
validation-only gate selector
GPU sweep runner
```

代码提交：

```text
6d66269 Add Stage5 residual PINN plan
dfdc58b Add Stage5 residual PINN report workflow
591eb1b Add Stage5 residual PINN gated audit
1b0cf15 Add Stage5 full-data GPU sweep runner
1d8b4d9 Refine Stage5 narrow gate selection
```

### 2.2 明确边界

当前 Stage5 是：

```text
point-level residual MLP + truth-free gate selection
```

当前 Stage5 不是：

```text
full-field PINN
Stage4 replacement
default production recon
```

正式公式：

```text
F_stage5 = F_tp26 + gate * clipped_delta
```

Stage4 default remains：

```text
tp26_thr11_preserve
```

### 2.3 从小样本扩展到 full tp26 point dataset

Full dataset：

```text
centralized_v1_output/stage5_residual_pinn_full_tp26_gpu_sweep_narrow_train_20260609/dataset_full_tp26/
```

| split | frames | points | baseline RMSE | baseline MAE | >=30mps tail |
| --- | ---: | ---: | ---: | ---: | ---: |
| train | 3930 | 11044 | 15.298961 | 6.807320 | 407 |
| val | 842 | 2117 | 13.805729 | 5.870153 | 64 |
| test | 842 | 1893 | 9.896785 | 5.217920 | 25 |

### 2.4 GPU sweep

训练命令使用：

```text
GPU IDs:
  0,1,2

caps:
  0.5,1.0,3.0

seeds:
  20260608,20260609,20260610

model:
  width 512
  layers 6
  max epochs 1200
  batch size 2048
```

训练确认：

```text
resolved device: cuda:0
cuda available: True
cuda device: NVIDIA GeForce RTX 4090
```

说明：每个进程看到 `cuda:0` 是因为 `CUDA_VISIBLE_DEVICES` 将物理 GPU 0/1/2 分别映射为进程内的 device 0。

### 2.5 新增 conservative gate policy

本周发现：宽门控虽然可能改善 RMSE，但容易伤害 P99、light wind、floor10。

因此新增：

```text
rule profile:
  narrow_safe

selection policy:
  stable_safe

additional rules:
  vertical_gap_ge10_not_light
  vertical_gap_ge20_not_light
  vertical_gap_ge30_not_light

controls:
  --gate-only
  --train-root
  --max-enabled-fraction
```

## 3. 关键结果

Full-data narrow train result：

```text
centralized_v1_output/stage5_residual_pinn_full_tp26_gpu_sweep_narrow_train_20260609/sweep_report.md
```

唯一非零 PASS：

```text
candidate:
  cap1p0_seed20260609_w512_l6

gate:
  vertical_gap_ge20_not_light

scale:
  1.0

test enabled:
  33 / 1893
```

Locked test metrics：

| metric | baseline | gated Stage5 | delta |
| --- | ---: | ---: | ---: |
| RMSE | 9.896785 | 9.892352 | -0.004433 |
| MAE | 5.217920 | 5.216535 | -0.001385 |
| P95 | 13.157155 | 13.037976 | -0.119179 |
| P99 | 43.020285 | 42.984991 | -0.035294 |
| light RMSE | 5.086997 | 5.086997 | +0.000000 |
| floor10 relative MAE | 0.197422 | 0.197393 | -0.000029 |

Conclusion：

```text
Stage5 residual PINN can enter field_v1 smoke.
It must be used only through the selected narrow truth-free gate.
It must not replace Stage4 tp26.
```

## 4. 失败原因总结

| candidate type | observation | decision |
| --- | --- | --- |
| cap=3.0 | RMSE gain larger, but P99/light/floor10 fail. | Reject for promotion. |
| cap=0.5 | Correction too weak or unstable; P95/floor10 can fail. | Reject for field smoke. |
| broad risk gates | Can improve RMSE but introduces tail/light regressions. | Do not use. |
| raw all-point residual | For winner checkpoint, raw test light RMSE worsens from 5.086998 to 5.133368. | Never apply globally. |

## 5. Visual Summary

Visualization directory：

```text
centralized_v1_output/stage5_residual_pinn_full_tp26_gpu_sweep_narrow_train_20260609/visualizations/
```

### 5.1 Locked Test RMSE Ranking

![locked test ranking](../../../centralized_v1_output/stage5_residual_pinn_full_tp26_gpu_sweep_narrow_train_20260609/visualizations/stage5_locked_test_rmse_ranking.png)

### 5.2 Guardrail Delta Heatmap

![guardrail heatmap](../../../centralized_v1_output/stage5_residual_pinn_full_tp26_gpu_sweep_narrow_train_20260609/visualizations/stage5_guardrail_delta_heatmap.png)

### 5.3 Dataset Split Summary

![dataset split summary](../../../centralized_v1_output/stage5_residual_pinn_full_tp26_gpu_sweep_narrow_train_20260609/visualizations/stage5_dataset_split_summary.png)

### 5.4 Winner Before/After

![winner before after](../../../centralized_v1_output/stage5_residual_pinn_full_tp26_gpu_sweep_narrow_train_20260609/visualizations/stage5_selected_gate_before_after.png)

### 5.5 Winner Training Curve

![training curve](../../../centralized_v1_output/stage5_residual_pinn_full_tp26_gpu_sweep_narrow_train_20260609/visualizations/stage5_selected_candidate_training_curve.png)

## 6. 下周计划

### 6.1 Field V1 Smoke

Use only：

```text
checkpoint:
  centralized_v1_output/stage5_residual_pinn_full_tp26_gpu_sweep_narrow_train_20260609/train_cap1p0_seed20260609_w512_l6/checkpoint.pt

gate:
  vertical_gap_ge20_not_light

scale:
  1.0
```

Do：

```text
1. Add full-field apply mode or new field apply script.
2. Apply residual only on gate-hit grid cells.
3. Write separate candidate output.
4. Smoke test 2-5 val representative frames.
5. Verify non-gate cells remain unchanged.
```

Recommended smoke frames：

```text
20260215010000
20260216081800
20260215151200
20260216163000
20260217000000
```

### 6.2 Strict Pairwise After Smoke

Only after field smoke passes：

```text
run 200-frame strict holdout pairwise
baseline:
  tp26_thr11_preserve
candidate:
  tp26_residual_pinn_field_v1_smoke
```

Must pass：

```text
weighted RMSE
P95
P99
light RMSE
light MAE
floor10 relative MAE
new light/moderate tail failures
high error >=30 count
```

### 6.3 Data Growth Direction

To increase effect size, do not widen gates. Instead:

```text
increase high-altitude samples
increase strong-wind samples
increase vertical-gap regimes
improve field feature construction
add truth-free collocation physics/background losses later
```

## 7. Risks

Main risks：

```text
1. Field feature mismatch: point-level features may not all exist on every grid cell.
2. Gate implementation mismatch: field gate must match validation gate exactly.
3. Over-application: applying raw residual globally will hurt light wind.
4. Promotion overreach: point-level PASS is not full-field PASS.
5. Small gain: current safe gain is real but tiny.
```

Risk control：

```text
default remains tp26
field_v1 only smoke
candidate output separate
validation gate frozen
test not used for new selection
strict pairwise required before promotion
```

## 8. Weekly Bottom Line

Stage5 residual PINN has produced one safe, narrow, nonzero point-level PASS candidate.

It is not ready as default, but it is ready for controlled field_v1 smoke:

```text
cap1p0_seed20260609_w512_l6
vertical_gap_ge20_not_light
scale=1.0
```

The next week should focus on full-field application correctness and strict pairwise validation, not on wider gates.
