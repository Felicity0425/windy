# Stage4 下一窗口执行计划：Tail-Risk、Confidence v2、Guarded Vertical Dynamic v2

## 新窗口交接摘要（2026-06-08）

当前默认仍是：

```text
tp26_thr11_preserve
```

已经完成 Step 1-3 的代码、smoke 验证和 Step 3 的 200 帧 formal gate，但没有把任何新分支升默认：

```text
Step 1 tail_risk_score report-only: 已完成，证明 tail-risk/no-claim 方向有效。
Step 2 confidence_v2_reliability: 已完成，新增 reliability/tail/no-claim 3D 输出，不改 recon。
Step 3 guarded_vertical_dynamic_v2: 已完成代码、两帧 smoke、200 帧/530 点 formal gate；结果 FAIL，不升默认。
Step 4 guarded_background_rescue: 未开始；Step 3 已明确失败，下一步应先分析 guard 诊断，不直接进入背景救援。
```

新窗口最重要的边界：

```text
strict holdout truth 只能来自 current aircraft wind_records。
motion_records / context_motion_records 不能当 wind。
CMA/GFS/ERA 只能当 weak background/prior，不能当 truth。
display-filled 只做可视化/product footprint，不进入 official RMSE。
reliability/no_claim 只做产品解释和后续 guard，不删除 official holdout 点。
```

### 已完成结果总览

| item | status | 关键结论 |
| --- | --- | --- |
| 200 帧 tp26 baseline | done | weighted RMSE `14.769036`，tail 由 21 个 `>=30 m/s` 点主导 |
| SRHA formal guardrail | done, reject | weighted RMSE `20.148615`，12km+ 和 P99 明显劣化 |
| sparse temporal CMA | done, reject | P95/P99 略好，但 weighted RMSE、12km+、light wind、floor10 FAIL |
| Step 1 tail-risk | done | `baseline_rule_v1` 捕获 21/21 高错点，unflagged RMSE `5.501192` |
| Step 2 reliability | done smoke | 新增 4 个 NPZ 合同字段和 point eval 字段，不改变 official recon |
| Step 3 guarded vertical | done, reject | all-holdout formal gate FAIL：weighted RMSE `14.853289`、P95 `28.681533`、12km+ `20.063442` 均劣化 |

### 关键输出路径

```text
Baseline 200-frame:
centralized_v1_output/stage4_guardrail_display_fill_200_20260605_25w/tp26_thr11_preserve_metrics/

Step 1 tail-risk report:
centralized_v1_output/stage4_tail_risk_confidence_v2_20260608/tail_risk_report/

Step 2 confidence/reliability smoke:
centralized_v1_output/stage4_confidence_v2_smoke_20260608/

Step 3 guarded vertical ground_recon smoke:
centralized_v1_output/stage4_guarded_vertical_dynamic_v2_smoke_20260608/

Step 3 guarded vertical sensitivity smoke:
centralized_v1_output/stage4_guarded_vertical_dynamic_v2_sensitivity_smoke_20260608/

Step 3 guarded vertical formal all-holdout:
centralized_v1_output/stage4_guarded_vertical_dynamic_v2_200_20260608/tp26_guarded_vertical_dynamic_v2_all_holdout_metrics/
centralized_v1_output/stage4_guarded_vertical_dynamic_v2_200_20260608/analysis/tp26_vs_guarded_vertical_dynamic_v2_all_holdout_formal_guardrail/
centralized_v1_output/stage4_guarded_vertical_dynamic_v2_200_20260608/analysis/tp26_vs_guarded_vertical_dynamic_v2_all_holdout_error_source/

Step 3 guarded vertical holdout-count=1 diagnostic only, not promotion:
centralized_v1_output/stage4_guarded_vertical_dynamic_v2_200_20260608/tp26_guarded_vertical_dynamic_v2_metrics/
centralized_v1_output/stage4_guarded_vertical_dynamic_v2_200_20260608/analysis/tp26_vs_guarded_vertical_dynamic_v2_formal_guardrail/

200-frame validation frame list:
centralized_v1_output/stage4_guardrail_display_fill_200_20260605_25w/tp26_thr11_preserve_metrics/stage4_validation_frame_times.txt
```

### Step 1 结果和分析

Tail-risk report-only 输入：

```text
centralized_v1_output/stage4_guardrail_display_fill_200_20260605_25w/tp26_thr11_preserve_metrics/stage4_point_departures.csv
```

整体：

| points | RMSE | MAE | P95 | P99 | high-error >=30mps |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 530 | 14.769036 | 6.854454 | 23.889507 | 63.542791 | 21 |

关键规则结果：

| rule | flagged | high-error recall | precision | unflagged RMSE | SSE captured |
| --- | ---: | ---: | ---: | ---: | ---: |
| `qc_review_only` | 302 | 1.000000 | 0.069536 | 5.622848 | 0.937646 |
| `baseline_rule_v1` | 310 | 1.000000 | 0.067742 | 5.501192 | 0.942409 |
| `baseline_plus_neighbor_tail` | 314 | 1.000000 | 0.066879 | 4.404634 | 0.963751 |
| `score_ge_0p35` | 106 | 0.952381 | 0.188679 | 5.689871 | 0.881262 |
| `score_ge_0p45` | 35 | 0.619048 | 0.371429 | 8.970412 | 0.655452 |

分析：

```text
baseline_rule_v1 能抓住全部 21 个 >=30m/s 高错点，说明 tail-risk 诊断方向有效。
score_ge_0p35 更稀疏，抓 20/21 个高错点，precision 从 0.0677 提升到 0.1887。
unflagged RMSE 从 overall 14.769036 降到 5.501192，证明 no-claim/reliability 对产品解释有价值。
point_neighbor_mean_vector_error >=15mps 是最强局部 tail bucket 之一，但它依赖 holdout 邻域误差，不能直接进入 3D truth-free product field。
```

### Step 2 结果和分析

新增合同字段：

```text
stage4_reliability_confidence_3d
stage4_tail_risk_score_3d
stage4_no_claim_mask_3d
stage4_reliability_diagnostics_json
```

两帧 smoke：

| frame | RMSE | reliability mean active | tail score mean active | active no-claim fraction | truth used | changes recon |
| --- | ---: | ---: | ---: | ---: | --- | --- |
| `20260205190000` | 86.000000 | 0.101788 | 0.427755 | 0.771999 | False | False |
| `20260206074200` | 3.560328 | 0.121862 | 0.413794 | 0.741770 | False | False |

分析：

```text
Step 2 把 input weight confidence 和 output reliability confidence 分开。
3D reliability 只用 recon_conf/support/role/vertical proxy，不用 holdout truth、vector_error 或 qc_review_flag。
no_claim_mask 不影响 official point eval，只解释“哪里不能宣称可靠”。
这一步为 Step 3 guarded vertical 提供 truth-free provisional guard context。
```

### Step 3 结果和分析

新增 policy：

```text
guarded_vertical_dynamic_v2
guarded_dynamic_v2
```

实现：

```text
先 fixed-vertical provisional pass，生成 reliability/tail/no-claim/support/role-gap proxy。
最终 pass 中，只有低风险 observation 使用 dynamic vertical factor。
高风险 observation 回退 fixed vertical。
默认 vertical_localization_policy=fixed 不变。
```

ground_recon smoke：

| frame | fixed RMSE | guarded RMSE | guard active | fallback | dynamic active | 12km+ fallback | role-gap fallback | remote fallback | light/mod protected |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `20260205190000` | 86.000000 | 86.000000 | 0.784965 | 0.215035 | 0.708042 | 0 | 0 | 17 | 31 |
| `20260206074200` | 3.560328 | 3.566067 | 0.897537 | 0.102463 | 0.799015 | 7 | 17 | 23 | 29 |

sensitivity smoke：

```text
centralized_v1_output/stage4_guarded_vertical_dynamic_v2_sensitivity_smoke_20260608/stage4_localization_sensitivity.csv
centralized_v1_output/stage4_guarded_vertical_dynamic_v2_sensitivity_smoke_20260608/stage4_localization_sensitivity_aggregate.md
```

分析：

```text
两帧 smoke 证明代码链路、NPZ JSON、method markdown、sensitivity CSV/aggregate 都有 guard diagnostics。
20260206074200 单点 RMSE 比 fixed 多 0.005740mps，不能据此 promotion 或 reject。
20260205190000 高风险帧仍是 86mps，说明 guarded vertical 不能修复 near-zero/context-only remote tail；这类问题应留给 Step 4 guarded background rescue，但必须 guarded。
Step 3 已完成 200-frame/530-point formal gate，结果 FAIL，不是默认方法。
```

### 新窗口第一动作（已完成）

已完成 `tp26_guarded_vertical_dynamic_v2` 的 200 帧 formal sensitivity。正式 promotion 必须复用 baseline 的 200 帧 frame list，并保持 all-holdout 口径；不要带 `--holdout-count 1`。

```bash
ROOT=/data/LFT-W02_data/pengxu
PY=$ROOT/.conda/envs/windy310/bin/python
STAGE2=$ROOT/centralized_v1_output/stage2_full_v2/stage2_multimodal_summary.json
STAGE3=$ROOT/centralized_v1_output/stage3_full_v2_25w_payload_only/stage3_center_summary.json
FRAMES=$ROOT/centralized_v1_output/stage4_guardrail_display_fill_200_20260605_25w/tp26_thr11_preserve_metrics/stage4_validation_frame_times.txt
OUT=$ROOT/centralized_v1_output/stage4_guarded_vertical_dynamic_v2_200_20260608

$PY stage/centralized_v1/core/centralized_stage4_sensitivity.py \
  --stage2-summary $STAGE2 \
  --stage3-summary $STAGE3 \
  --out-dir $OUT/tp26_guarded_vertical_dynamic_v2_all_holdout_metrics \
  --frame-times-file $FRAMES \
  --param-grid 8,4,2,1 \
  --kernels gaussian \
  --confidence-mode diagnostic_weighted \
  --physics-constraint-mode pydda_3dvar_proxy \
  --localization-policy diagnostic_adaptive_v3 \
  --localization-candidate-grid 8:4,10:5 \
  --current-weight-boost 2.0 \
  --context-weight-scale 0.5 \
  --context-time-conf-power 2.6 \
  --role-conflict-mode current_priority_adaptive \
  --conflict-speed-threshold-mps 11.0 \
  --conflict-context-factor 0.25 \
  --vertical-risk-mode preserve_strong_layers \
  --vertical-localization-policy guarded_vertical_dynamic_v2 \
  --vertical-gradient-preserve-weight 0.12 \
  --vertical-context-mismatch-damping 0.35 \
  --num-workers 25
```

跑完后必须和 baseline 做 pairwise/checklist，不能只看 aggregate mean：

```text
baseline:
centralized_v1_output/stage4_guardrail_display_fill_200_20260605_25w/tp26_thr11_preserve_metrics/

candidate:
centralized_v1_output/stage4_guarded_vertical_dynamic_v2_200_20260608/tp26_guarded_vertical_dynamic_v2_all_holdout_metrics/
```

promotion gate：

```text
candidate weighted RMSE <= 14.769036
candidate frame P95 <= 27.986111
candidate frame P99 <= 58.783770
candidate 12km+ RMSE <= 19.917698
candidate light RMSE <= 5.195877
candidate light MAE <= 4.185283
candidate floor10 relative MAE <= 0.282804
strict_holdout_no_leakage == True
motion_used_as_wind == False
```

正式结果：`PROMOTION_OVERALL = FAIL`，不要升级默认。

## 当前结论

默认仍然保持：

```text
tp26_thr11_preserve
```

不要推广：

```text
support_role_height_aware
sparse_temporal_gated CMA/NWP
guarded_vertical_dynamic_v2
```

固定验证边界：

```text
truth = current aircraft wind_records strict holdout
strict_holdout_no_leakage = True
motion_used_as_wind = False
CMA/GFS/ERA = weak background / prior only, never truth
display-filled = visualization/product footprint only, not official accuracy
```

200 帧结果根目录：

```text
centralized_v1_output/stage4_guardrail_display_fill_200_20260605_25w/
```

关键文件：

```text
Official tp26 tail:
centralized_v1_output/stage4_guardrail_display_fill_200_20260605_25w/tp26_thr11_preserve_metrics/tail_diagnostics/stage4_tail_diagnostics.md

tp26 rerun checklist:
centralized_v1_output/stage4_guardrail_display_fill_200_20260605_25w/analysis/tp26_existing_vs_rerun/tp26_existing_vs_rerun.md

SRHA formal guardrail:
centralized_v1_output/stage4_guardrail_display_fill_200_20260605_25w/analysis/tp26_vs_srha_formal_guardrail/tp26_vs_srha_formal_guardrail.md

CMA formal guardrail:
centralized_v1_output/stage4_guardrail_display_fill_200_20260605_25w/analysis/tp26_vs_sparse_temporal_cma_formal_guardrail/tp26_vs_sparse_temporal_cma_formal_guardrail.md

Guarded vertical formal guardrail:
centralized_v1_output/stage4_guarded_vertical_dynamic_v2_200_20260608/analysis/tp26_vs_guarded_vertical_dynamic_v2_all_holdout_formal_guardrail/tp26_vs_guarded_vertical_dynamic_v2_all_holdout.md

Guarded vertical promotion checklist:
centralized_v1_output/stage4_guarded_vertical_dynamic_v2_200_20260608/analysis/tp26_vs_guarded_vertical_dynamic_v2_all_holdout_formal_guardrail/tp26_vs_guarded_vertical_dynamic_v2_all_holdout_promotion_checklist.md

Representative display-filled visuals:
centralized_v1_output/stage4_guardrail_display_fill_200_20260605_25w/representative_display_filled_visuals/

Representative wind speed/direction table:
centralized_v1_output/stage4_guardrail_display_fill_200_20260605_25w/representative_display_filled_visuals/representative_wind_speed_direction_table.md
```

## 结果读法

200 帧、530 个 strict holdout 点：

| metric | value |
| --- | ---: |
| frame mean RMSE | 8.224309 |
| frame mean MAE | 7.081909 |
| weighted vector RMSE | 14.769036 |
| weighted vector MAE | 6.854454 |
| frame P95 | 27.986111 |
| frame P99 | 58.783770 |
| max frame RMSE | 109.692698 |

`stage4_localization_sensitivity_aggregate.md` 里的 94/106 两行不是两个候选方法，而是同一个
tp26 adaptive 策略在 200 帧中选择到的两个 localization 桶。正式整体结论以 pairwise/checklist
和 tail diagnostics 为准。

## Tail 结构

当前不是全场平均都差，而是少数 tail 点支配 RMSE：

| stratum | points | RMSE | SSE share |
| --- | ---: | ---: | ---: |
| all_holdout_points | 530 | 14.769036 | 1.000000 |
| alt_12km_plus | 222 | 19.917698 | 0.761818 |
| qc_review_flag | 302 | 18.945495 | 0.937646 |
| no_qc_review_flag | 228 | 5.622848 | 0.062354 |
| high_vector_error_ge30mps | 21 | 66.820701 | 0.811075 |
| role_gap_ge30mps | 38 | 32.392820 | 0.344906 |
| nearest_distance_gt4vox | 27 | 32.499520 | 0.246682 |

所以下一轮主线不是继续堆全场融合，而是把这些风险类型变成正式 reliability/tail-risk 诊断和 guarded 分支。

## SRHA 结论

`support_role_height_aware` 当前版本不能升默认：

| gate | tp26 | SRHA | result |
| --- | ---: | ---: | --- |
| weighted RMSE | 14.769036 | 20.148615 | FAIL |
| frame P95 | 27.986111 | 34.727103 | FAIL |
| frame P99 | 58.783770 | 86.322454 | FAIL |
| 12km+ RMSE | 19.917698 | 28.454526 | FAIL |
| floor10 relative MAE | 0.282804 | 0.317724 | FAIL |

SRHA light-wind 平均略好，但高空/强风/role-conflict 长尾被放大。结论不是“垂直动态分层没用”，而是
当前 SRHA 的 height/role 调整太粗，不能全场启用。

## CMA 结论

`sparse_temporal_gated` CMA/NWP 也不能升默认：

| gate | tp26 | CMA | result |
| --- | ---: | ---: | --- |
| weighted RMSE | 14.769036 | 14.852237 | FAIL |
| frame P95 | 27.986111 | 26.226386 | PASS |
| frame P99 | 58.783770 | 53.532347 | PASS |
| 12km+ RMSE | 19.917698 | 19.951609 | FAIL |
| light RMSE | 5.195877 | 6.057278 | FAIL |
| light MAE | 4.185283 | 4.490680 | FAIL |
| floor10 relative MAE | 0.282804 | 0.293846 | FAIL |

CMA 能压低部分极端尾部，但污染 3-6km / light wind sparse 点。下一轮只能做 guarded background rescue，
不能进入高置信 aircraft 支撑区域。

## Display-Filled 语义

display-filled 已解决“白底/近白底”的可视化问题，但不改变正式精度。

字段：

```text
stage4_display_u_3d
stage4_display_v_3d
stage4_display_confidence_3d
stage4_display_mask_3d
stage4_display_source_3d
stage4_display_fill_diagnostics_json
```

语义：

```text
recon_u/v/conf/mask = official tp26 strict reconstruction
stage4_display_* = official recon where recon_mask true + low-confidence weak background elsewhere
CMA/background never enters official point evaluation
display_fill_is_official_accuracy = False
```

代表帧中 official recon 只占全网格约 1.3%-2.4%，其余大多是 weak background display fill。
图可以展示 product footprint，不能宣称全图 validated accuracy。

## 下一步总策略

按这个顺序做：

```text
1. tail_risk_score report-only，不改模型。
2. confidence_v2_reliability，把输出可信度和输入权重分开。
3. guarded_vertical_dynamic_v2，只在低风险区域启用动态垂直分层。
4. guarded_background_rescue，只救 near-zero/no-claim 区域，不碰高置信 aircraft 支撑。
```

不要先做：

```text
全场 CMA 融合
全场 height-aware/SRHA
把 display-filled 当 official recon
用 de Haan/EMADDC sigma 从 RMSE 里扣
把 u_motion/v_motion 当 wind
```

## Step 1：Tail-Risk Report-Only

目标：不改 `recon_u/v`，先证明哪些 flag 能预测 `vector_error >= 30 m/s` 和 P95/P99 tail。

建议新增脚本：

```text
stage/centralized_v1/core/centralized_stage4_tail_risk_model.py
```

输入：

```text
centralized_v1_output/stage4_guardrail_display_fill_200_20260605_25w/tp26_thr11_preserve_metrics/stage4_point_departures.csv
```

候选特征：

```text
recon_confidence
nearest_train_distance_vox
nearest_train_source_role
nearest_current_count
nearest_context_count
nearest_role_gap_mps
vertical_speed_gap_mps
recon_vertical_jump_mps
point_neighbor_count
point_neighbor_mean_vector_error
representativeness_gap_point_minus_min_mps
role_conflict_at_point
role_conflict_component_gap_at_point_mps
qc_review_flag
qc_review_reasons
adaptive_current_support
adaptive_context_support
```

输出：

```text
tail_risk_feature_summary.csv
tail_risk_feature_summary.md
tail_risk_rule_candidates.csv
tail_risk_top_points.csv
```

最小 rule baseline：

```text
tail_risk_flag =
  qc_review_flag
  OR nearest_train_distance_vox > 4
  OR nearest_role_gap_mps >= 30
  OR recon_confidence < 0.05
  OR context_only_nearest_support
  OR strong_wind_vertically_isolated_candidate
```

评估表：

```text
flagged_points
flagged_error_rmse
unflagged_error_rmse
high_error_ge30_recall
high_error_ge30_precision
P95/P99 contribution
SSE share captured
```

通过标准：先不要求精度提升，只要求这个 risk score 能把大部分 `vector_error >= 30 m/s` tail 抓出来，
同时 unflagged 点 RMSE 明显低于 overall。

### 2026-06-08 Step 1 实施记录

已落地代码：

```text
stage/centralized_v1/core/centralized_stage4_tail_risk_model.py
```

输出：

```text
centralized_v1_output/stage4_tail_risk_confidence_v2_20260608/tail_risk_report/tail_risk_feature_summary.csv
centralized_v1_output/stage4_tail_risk_confidence_v2_20260608/tail_risk_report/tail_risk_feature_summary.md
centralized_v1_output/stage4_tail_risk_confidence_v2_20260608/tail_risk_report/tail_risk_rule_candidates.csv
centralized_v1_output/stage4_tail_risk_confidence_v2_20260608/tail_risk_report/tail_risk_top_points.csv
```

关键结果：

```text
overall points = 530
overall RMSE = 14.769036
high-error >=30mps count = 21
baseline_rule_v1 flagged = 310
baseline_rule_v1 high-error recall = 1.000000
baseline_rule_v1 high-error precision = 0.067742
baseline_rule_v1 unflagged RMSE = 5.501192
baseline_rule_v1 SSE share captured = 0.942409
score_ge_0p35 flagged = 106
score_ge_0p35 high-error recall = 0.952381
score_ge_0p35 high-error precision = 0.188679
```

结论：

```text
tail-risk/no-claim 方向有效，可以用于产品解释和 guarded 分支。
report-only 不能改变 official RMSE，也不能把 flagged 点从 strict holdout 中删掉。
```

## Step 2：Confidence v2 Reliability

当前 `diagnostic_weighted` 可以保留为默认输入权重，但它不是输出可靠性。下一版要拆成三套概念：

```text
input_weight_confidence:
  控制观测参与重构的权重。

output_reliability_confidence:
  表示该 voxel/point 的预测是否可信。

display_confidence:
  只控制展示层补色，不参与 official RMSE。
```

新增输出字段建议：

```text
stage4_reliability_confidence_3d
stage4_tail_risk_score_3d
stage4_no_claim_mask_3d
stage4_reliability_diagnostics_json
```

point eval 增加：

```text
tail_risk_score_at_point
reliability_confidence_at_point
no_claim_at_point
```

初始 reliability 规则：

```text
reliability_confidence =
  recon_confidence
  * distance_factor
  * role_consistency_factor
  * support_count_factor
  * vertical_consistency_factor
  * qc_factor
```

建议 factor：

```text
distance_factor:
  1.0 if nearest_train_distance_vox <= 2
  0.5 if 2 < distance <= 4
  0.15 if distance > 4

role_consistency_factor:
  1.0 if role_gap < 20
  0.5 if 20 <= role_gap < 30
  0.15 if role_gap >= 30

support_count_factor:
  1.0 if current_count >= 1 or context_count >= 2
  0.4 otherwise

vertical_consistency_factor:
  0.25 if strong_wind_vertically_isolated_candidate or rapid vertical jump at point
  1.0 otherwise

qc_factor:
  0.3 if qc_review_flag
  1.0 otherwise
```

注意：`no_claim_mask` 不能从 official RMSE 删除点。它只用于产品解释和后续 guarded 分支。

### 2026-06-08 Step 2 实施记录

已落地代码：

```text
stage/centralized_v1/configs/centralized_v1_contract.py
stage/centralized_v1/core/centralized_stage4_ground_recon.py
```

新增 Stage4 NPZ 合同字段：

```text
stage4_reliability_confidence_3d
stage4_tail_risk_score_3d
stage4_no_claim_mask_3d
stage4_reliability_diagnostics_json
```

新增 point eval 字段：

```text
tail_risk_score_at_point
reliability_confidence_at_point
no_claim_at_point
reliability_distance_factor_at_point
reliability_role_consistency_factor_at_point
reliability_support_count_factor_at_point
reliability_vertical_consistency_factor_at_point
```

实现口径：

```text
input_weight_confidence = 仍由 confidence_mode / diagnostic_weighted 控制观测融合权重。
output_reliability_confidence = 新增 report/product reliability 字段，不改变 recon_u/v/conf/mask。
display_confidence = 继续只服务 stage4_display_* 展示层。
```

关键边界：

```text
3D reliability 字段不使用 holdout truth、vector_error 或 qc_review_flag。
point eval 可以同时报告 qc_review_flag 和 reliability 字段，但 no_claim_at_point 不能删除 official RMSE 点。
reliability_confidence_changes_reconstruction = False
truth_used_for_3d_reliability = False
```

Smoke test 输出：

```text
centralized_v1_output/stage4_confidence_v2_smoke_20260608/
```

已验证：

```text
python -m py_compile:
  centralized_stage4_ground_recon.py
  centralized_stage4_sensitivity.py
  centralized_v1_contract.py

单帧 20260205190000:
  新增 4 个 NPZ 字段存在。
  point_eval CSV 包含新增 reliability/tail/no_claim 字段。
  method markdown 包含 Reliability Confidence Diagnostics。

单帧 20260206074200:
  新增字段链路同样通过。
```

## Step 3：Guarded Vertical Dynamic v2

当前 tp26 已有 `preserve_strong_layers`，继续保留。下一版垂直动态分层不是继续 SRHA，而是新分支：

```text
guarded_vertical_dynamic_v2
```

只允许在低风险区域启用动态垂直分层：

```text
nearest_train_distance_vox <= 2
nearest_role_gap_mps < 20 或 30
reliability_confidence >= 0.2
not context_only_extreme
not strong_vertical_isolated
not near_zero_reconstruction_confidence
```

禁止启用，回退 tp26 preserve：

```text
12km+ 且 role_gap_mps >= 30
nearest_train_distance_vox > 4
context_only + strong/extreme wind
recon_confidence < 0.05
light/moderate wind 中已有 relative/direction tail 风险
```

候选命名建议：

```text
tp26_guarded_vertical_dynamic_v2
```

必须报告：

```text
guard_active_fraction
guarded_fallback_fraction
dynamic_vertical_active_fraction
12km+ guard fallback count
role_gap fallback count
remote_support fallback count
light/moderate protected count
```

目标不是全场提升，而是：

```text
weighted RMSE 不劣化
P95/P99 不劣化
12km+ 不劣化
light-wind 不劣化
floor10 relative 不劣化
SRHA 当前新增 extreme tail 不再出现
```

### 2026-06-08 Step 3 实施记录

已落地代码：

```text
stage/centralized_v1/core/centralized_stage4_ground_recon.py
stage/centralized_v1/core/centralized_stage4_sensitivity.py
```

新增 vertical localization policy：

```text
guarded_vertical_dynamic_v2
guarded_dynamic_v2  # 短别名
```

实现口径：

```text
默认 tp26_thr11_preserve 不变；只有显式 --vertical-localization-policy guarded_vertical_dynamic_v2 才启用。
guarded 分支先跑 fixed-vertical provisional pass，生成 truth-free reliability/tail/no-claim/support/role-gap proxy。
最终 pass 只在 guard 允许的 observation 上启用现有 dynamic vertical factor；其余 observation 回退 fixed vertical。
guard 输入不使用 holdout truth、vector_error 或 qc_review_flag。
```

新增诊断：

```text
guard_active_fraction
guarded_fallback_fraction
dynamic_vertical_active_fraction
guard_12km_plus_fallback_count
guard_role_gap_fallback_count
guard_remote_support_fallback_count
guard_light_moderate_protected_count
guard_low_reliability_fallback_count
guard_high_tail_risk_fallback_count
guard_no_claim_fallback_count
guard_near_zero_confidence_fallback_count
guard_context_extreme_fallback_count
guard_strong_vertical_isolated_fallback_count
```

输出位置：

```text
centralized_v1_output/stage4_guarded_vertical_dynamic_v2_smoke_20260608/
centralized_v1_output/stage4_guarded_vertical_dynamic_v2_sensitivity_smoke_20260608/
```

Smoke test：

```text
python -m py_compile:
  centralized_stage4_ground_recon.py
  centralized_stage4_sensitivity.py

ground_recon 单帧 20260206074200:
  fixed Step2 RMSE = 3.56032770944409
  guarded RMSE = 3.566067286521
  guard_active_fraction = 0.8975369458128079
  guarded_fallback_fraction = 0.10246305418719212
  dynamic_vertical_active_fraction = 0.7990147783251231
  12km+ fallback = 7
  role-gap fallback = 17
  remote fallback = 23
  light/mod protected = 29

ground_recon 单帧 20260205190000:
  fixed Step2 RMSE = 86.0
  guarded RMSE = 86.0
  guard_active_fraction = 0.784965034965035
  guarded_fallback_fraction = 0.21503496503496503
  dynamic_vertical_active_fraction = 0.708041958041958
  12km+ fallback = 0
  role-gap fallback = 0
  remote fallback = 17
  light/mod protected = 31

sensitivity 单帧 20260206074200:
  stage4_localization_sensitivity.csv 包含 guard 诊断列。
  stage4_localization_sensitivity_aggregate.md 包含 Guarded Vertical Dynamic Diagnostics 表。
```

当前边界：

```text
两帧 smoke 只验证代码链路和诊断，不构成 promotion。
200 帧 all-holdout Formal Promotion Gate 已完成，结果 FAIL。
```

### 2026-06-08 Step 3 Formal Gate 实施记录

先按原计划命令跑过一次 `--holdout-count 1`：

```text
centralized_v1_output/stage4_guarded_vertical_dynamic_v2_200_20260608/tp26_guarded_vertical_dynamic_v2_metrics/
```

该输出只有：

```text
stage4_point_departures.csv = 200 rows + header
```

而 baseline tp26 正式 200 帧 point departures 是：

```text
stage4_point_departures.csv = 530 rows + header
```

因此 `--holdout-count 1` 结果只能作为代码链路/诊断输出，不作为 promotion。正式 gate 已重跑 all-holdout 口径，不带 `--holdout-count`：

```text
centralized_v1_output/stage4_guarded_vertical_dynamic_v2_200_20260608/tp26_guarded_vertical_dynamic_v2_all_holdout_metrics/
```

正式输出完整性：

```text
stage4_localization_sensitivity.csv = 200 rows + header
stage4_point_departures.csv = 530 rows + header
strict_holdout_no_leakage = True
motion_used_as_wind = False
```

formal checklist：

```text
centralized_v1_output/stage4_guarded_vertical_dynamic_v2_200_20260608/analysis/tp26_vs_guarded_vertical_dynamic_v2_all_holdout_formal_guardrail/tp26_vs_guarded_vertical_dynamic_v2_all_holdout_promotion_checklist.md
```

结果：

| gate | tp26 baseline | guarded vertical all-holdout | result |
| --- | ---: | ---: | --- |
| weighted RMSE | 14.769036 | 14.853289 | FAIL |
| weighted MAE | 6.854454 | 6.902063 | FAIL |
| frame mean RMSE | 8.224309 | 8.254518 | FAIL |
| frame P95 | 27.986111 | 28.681533 | FAIL |
| frame P99 | 58.783770 | 58.783770 | PASS |
| 12km+ vector RMSE | 19.917698 | 20.063442 | FAIL |
| 5-15mps light RMSE | 5.195877 | 5.219127 | FAIL |
| 5-15mps light MAE | 4.185283 | 4.199608 | FAIL |
| floor10 relative MAE | 0.282804 | 0.284927 | FAIL |
| light/moderate new relative tail | 0 | 0 | PASS |

guard diagnostics aggregate：

| selected kernel bucket | frames | holdout points | guard active frac | fallback frac | dynamic active frac | 12km+ fallback | role-gap fallback | remote fallback | light/mod protected |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `10/5` | 94 | 192 | 0.785995 | 0.214005 | 0.744112 | 1117 | 2574 | 1236 | 7889 |
| `8/4` | 106 | 338 | 0.712270 | 0.287730 | 0.669684 | 2635 | 5994 | 1700 | 15159 |

error-source decomposition：

```text
centralized_v1_output/stage4_guarded_vertical_dynamic_v2_200_20260608/analysis/tp26_vs_guarded_vertical_dynamic_v2_all_holdout_error_source/tp26_vs_guarded_vertical_dynamic_v2_all_holdout.md
```

关键解释：

```text
Candidate vector RMSE worsens by 0.084253 m/s (0.57%): 14.769036 -> 14.853289.
最大失败源仍是 vertical_structure、representation_error、sparse_support、role_conflict。
guarded vertical 能限制 SRHA 那种灾难性放大，但当前动态垂直启用仍轻微污染 12km+、light wind 和 floor10 relative error。
因此 Step 3 不升默认，默认继续 tp26_thr11_preserve。
```

## Step 4：Guarded Background Rescue

只有完成 Step 1-3 后再做。当前 Step 3 已明确 FAIL；如果继续 Step 4，必须先基于 guard fallback diagnostics 约束触发区域。CMA/NWP 只救 official recon near-zero/no-claim 区域，不能污染高置信 aircraft 支撑。

候选命名：

```text
tp26_guarded_background_rescue_v1
```

允许 background rescue：

```text
recon_confidence < 0.05
pred_speed < 1 m/s 或 official no-claim
nearest_train_distance_vox > 4
no current high-confidence support
background temporal gate passed
not 3-6km light-wind risk region
not high-confidence aircraft-supported voxel
```

禁止 background rescue：

```text
recon_confidence >= 0.2
current_count >= 1 且 role_gap < 30
5-15mps_light / 3-6km sparse risk point
background/current direction difference too large
```

必须保留诊断：

```text
background_rescue_active_fraction
background_rescue_point_count
background_rescue_light_wind_count
background_rescue_3_6km_count
background_rescue_delta_vector_error
background_used_as_truth = False
```

## Formal Promotion Gate

任何候选必须同时满足：

```text
strict_holdout_no_leakage == True
motion_used_as_wind == False
candidate weighted RMSE <= baseline
candidate frame P95 <= baseline
candidate frame P99 <= baseline
candidate 12km+ vector RMSE <= baseline
candidate 5-15mps_light vector RMSE <= baseline
candidate 5-15mps_light vector MAE <= baseline
candidate overall floor10_relative_error_mae <= baseline
light/moderate wind 中若任一点 relative_error_ratio > 2 且 delta_vector_error > 5 m/s，直接 FAIL
```

正式 pairwise/checklist 已支持：

```text
truth_speed_bin
relative_error_ratio
floor10_relative_error
direction_error_deg
```

## Observation-Error 固定口径

必须这样写：

```text
de Haan / EMADDC sigma = aircraft wind observation-error prior 或 QC 诊断权重。
当前 13.64 m/s = local consistency / representativeness sigma，不是飞机风观测误差。
sigma 不能从 Stage4 RMSE/MAE 中扣除。
u_motion/v_motion = aircraft ground motion，不是 wind。
```

## 下一窗口建议执行顺序

当前 Step 1-3 已完成代码、smoke 和 Step 3 all-holdout formal gate。新窗口不要重复从 Step 1 开始，建议按以下顺序：

```text
1. 先读 guarded_vertical_dynamic_v2 all-holdout formal checklist 和 error-source decomposition。
2. 不推广 guarded_vertical_dynamic_v2；它已 FAIL：weighted/P95/12km+/light/floor10 均劣化。
3. 分析 guard fallback diagnostics，重点看 12km+、vertical_speed_gap、role_gap、light wind 的新增劣化。
4. 如果继续垂直方向，只做更保守的 per-point/regime-aware guard，不要直接调大动态垂直范围。
5. Step 4 guarded_background_rescue 只针对 near-zero/no-claim/remote-support，不允许污染 high-confidence aircraft-supported voxels。
```

200 帧 guarded candidate 正式复现命令已写在本文顶部“新窗口第一动作”。核心参数必须保持：

```text
--param-grid 8,4,2,1
--localization-policy diagnostic_adaptive_v3
--localization-candidate-grid 8:4,10:5
--confidence-mode diagnostic_weighted
--physics-constraint-mode pydda_3dvar_proxy
--current-weight-boost 2.0
--context-weight-scale 0.5
--context-time-conf-power 2.6
--role-conflict-mode current_priority_adaptive
--conflict-speed-threshold-mps 11.0
--conflict-context-factor 0.25
--vertical-risk-mode preserve_strong_layers
--vertical-localization-policy guarded_vertical_dynamic_v2
```

不要做：

```text
不要把 guarded_vertical_dynamic_v2 直接升默认。
不要用 smoke 的两帧结果宣称通过。
不要把 reliability/no_claim 从 official RMSE 中剔除。
不要先做全场 CMA/NWP 融合。
不要把 Step 4 background rescue 用到 current-supported 高置信区域。
```

## 成功标准

短期成功：

```text
tail_risk_score 能解释/捕获大部分 vector_error >= 30 m/s 点。
unflagged 点 RMSE 明显低于 overall。
confidence=1.0 但 context-only/role-conflict 大错点被 reliability 降权或 no-claim。
```

中期成功：

```text
下一版 guarded vertical 必须比当前 v2 更保守。
weighted RMSE / P95 / P99 / 12km+ / light wind / floor10 relative 全部不劣化后，才能重新讨论候选保留。
```

后续成功：

```text
guarded_background_rescue 能修复 near-zero / remote-support 的 display/product failure，
同时不污染 high-confidence aircraft observation 支撑区域。
```
