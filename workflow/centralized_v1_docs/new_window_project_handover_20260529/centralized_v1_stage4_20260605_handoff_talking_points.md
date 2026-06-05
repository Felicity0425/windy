# Stage4 2026-06-05 接手执行话术

## 当前结论

默认仍然是 `tp26_thr11_preserve`。不要推广 `support_role_height_aware`，也不要推广
`sparse_temporal_gated` CMA/NWP。

固定验证边界：

```text
truth = current aircraft wind_records strict holdout
strict_holdout_no_leakage = True
motion_used_as_wind = False
CMA/GFS/ERA = weak background / prior only, never truth
```

## 为什么不推广

SRHA 失败很明确：

```text
weighted RMSE: 14.769036 -> 20.148615
frame P95:     27.986111 -> 34.727103
frame P99:     58.783770 -> 86.322454
12km+ RMSE:    19.917698 -> 28.454526
```

最坏点是高空 role-conflict：

```text
20260202013600 z/y/x=29/281/519, 12km+, gt_speed=60 m/s
baseline error 18.236828 -> SRHA error 253.572554
relative_error_ratio = 4.226209
direction_error_deg = 162.97
```

CMA/NWP gate 不是全场融合，但仍不通过：

```text
cma_background_gate_active_fraction mean = 0.007787
cma_background_gate_active_fraction max  = 0.015512

weighted RMSE: 14.769036 -> 14.852237
weighted MAE:  6.854454 -> 7.040594
12km+ RMSE:    19.917698 -> 19.951609
```

CMA 的新增风险在轻风/中低空 sparse 点：

```text
20260210011200 z/y/x=10/295/510, 3-6km, gt_speed=13 m/s
baseline error 10.363190 -> CMA error 34.218618
relative_error_ratio = 2.632201
direction_error_deg = 97.95
```

## Wind-Scale 解释口径

不要只看 RMSE/MSE 绝对值。相同的 `8 m/s`：

```text
80-100 m/s 强风里可能只是 8%-10% 相对误差。
5-15 m/s 轻风里可能已经是 50%-160% 相对误差。
近静风里风向不稳定，方向误差只做解释，不做均值硬门槛。
```

这轮新增分析脚本：

```text
stage/centralized_v1/core/centralized_stage4_wind_scale_impact.py
```

核心指标：

```text
relative_error_ratio = vector_error / gt_speed
floor10_relative_error = vector_error / max(gt_speed, 10)
direction_error_deg = abs circular angle difference from atan2(v, u)
```

输出入口：

```text
SRHA:
centralized_v1_output/stage4_srha_tail_200_20260605_25w/analysis/tp26_vs_srha_wind_scale/tp26_vs_srha_wind_scale.md

CMA:
centralized_v1_output/stage4_sparse_temporal_cma_200_20260605_25w/analysis/tp26_vs_sparse_temporal_cma_wind_scale/tp26_vs_sparse_temporal_cma_wind_scale.md
```

## 下一步怎么做

先做 guardrail/reporting，再做模型改动。

下一轮候选必须同时满足：

```text
weighted RMSE 不劣化
P95 不劣化
P99 不劣化
12km+ vector RMSE 不劣化
5-15mps_light bin 不明显劣化
0-5mps_calm / 5-15mps_light 不新增 delta > 5 m/s top-tail
floor10_relative_error_mae 不劣化
light/moderate wind 若 relative_error_ratio > 2 且 delta > 5 m/s，直接失败
```

建议优先项：

```text
1. 不继续调当前 SRHA 因子。
2. CMA/NWP 保留 sparse_temporal_gated 实现和诊断列，但不升默认。
3. 下一版 CMA gate 加 height/speed/source-role guard，重点排除 3-6km light-wind 新长尾。
4. 把 truth_speed_bin、floor10_relative_error、direction_error_deg 纳入正式 pairwise/checklist。
```

## Skills GitHub

按用户确认，skills 只处理独立仓库，不纳入 windy 主仓库。

```text
local repo:
/data/LFT-W02_data/pengxu/nature-skills

remote:
https://github.com/Yuan1z0825/nature-skills.git

branch:
main

HEAD == upstream:
c9b874a675e29e40fed88af89509092665d5a236

status:
clean, no ahead commit
```

结论：

```text
nature-skills 当前已与 GitHub origin/main 对齐，没有本地改动需要提交或推送。
windy 主仓库里的 nature-skills/ 保持 untracked，不要误加。
```

主交接文档：

```text
workflow/centralized_v1_docs/new_window_project_handover_20260529/centralized_v1_stage4_error_resolution_plan_20260602.md
```

## Guardrail/Display-Fill 已固化

2026-06-05 已完成代码和 200 帧试跑。默认仍然是：

```text
tp26_thr11_preserve
```

正式 promotion checklist 已纳入：

```text
truth_speed_bin
relative_error_ratio
floor10_relative_error
direction_error_deg
```

下一轮候选必须全部满足：

```text
weighted RMSE 不劣化
frame P95 不劣化
frame P99 不劣化
12km+ vector RMSE 不劣化
5-15mps_light vector RMSE/MAE 不劣化
overall floor10_relative_error_mae 不劣化
light/moderate wind 中若 relative_error_ratio > 2 且 delta_vector_error > 5 m/s，直接失败
```

200 帧 formal checklist：

| comparison | result | path |
| --- | --- | --- |
| tp26 existing vs rerun | PASS | `centralized_v1_output/stage4_guardrail_display_fill_200_20260605_25w/analysis/tp26_existing_vs_rerun/tp26_existing_vs_rerun_promotion_checklist.md` |
| tp26 vs SRHA | FAIL | `centralized_v1_output/stage4_guardrail_display_fill_200_20260605_25w/analysis/tp26_vs_srha_formal_guardrail/tp26_vs_srha_formal_guardrail_promotion_checklist.md` |
| tp26 vs sparse-temporal CMA | FAIL | `centralized_v1_output/stage4_guardrail_display_fill_200_20260605_25w/analysis/tp26_vs_sparse_temporal_cma_formal_guardrail/tp26_vs_sparse_temporal_cma_formal_guardrail_promotion_checklist.md` |

display-filled 只解决“全图可视化不要白底/近白底”的展示问题，不改变正式精度：

```text
recon_u/v/conf/mask 仍是 official tp26。
stage4_display_* 用 official recon 保留高置信区域，低置信/无 claim 区域用弱背景补色。
CMA/background 不进入 official point evaluation。
display_fill_is_official_accuracy = False
```

代表帧可视化与风速/风向表：

```text
centralized_v1_output/stage4_guardrail_display_fill_200_20260605_25w/representative_display_filled_visuals/
centralized_v1_output/stage4_guardrail_display_fill_200_20260605_25w/representative_display_filled_visuals/representative_wind_speed_direction_table.md
```

observation-error 解释必须固定：

```text
de Haan / EMADDC sigma = aircraft wind observation-error prior 或 QC 诊断权重。
13.64 m/s = local consistency / representativeness sigma，不是飞机风观测误差。
sigma 不能从 Stage4 RMSE/MAE 里扣。
u_motion/v_motion = aircraft ground motion，不是 wind。
```
