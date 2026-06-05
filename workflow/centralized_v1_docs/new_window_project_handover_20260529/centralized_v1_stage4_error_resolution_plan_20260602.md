# centralized_v1 Stage4 误差来源与逐步解决方案 - 2026-06-02

本文档用于接手 Stage4 后继续降低 strict aircraft holdout 误差。它把
`timepower15` 与 `adaptive_v3` 的 200 帧结果转成可执行路线：每一种误差
都说明机制、解决方法、建议实验、运行命令、验收标准和文献依据。

核心结论先写在前面：`adaptive_v3` 已经小幅优于 `timepower15`，但不是突破。
下一步不要继续盲目调一个全局 localization 半径，而要按
`vertical_structure -> representation_error -> sparse_support -> role_conflict
-> temporal_weighting -> tail_qc -> localization` 的顺序分层解决。

## 0. 固定验证边界

任何新实验都必须保持：

```text
truth = current aircraft wind_records strict holdout
holdout wind_records must be removed before fusion
motion_records / location_records are not wind truth
CMA/GFS/ERA are weak background or condition only, not truth
no-holdout frames are unverified reconstruction, not official RMSE/MAE
strict_holdout_no_leakage must be True
motion_used_as_wind must be False
```

论文里的 aircraft observation error 只能作为观测误差参考下限，不能直接当
Stage4 reconstruction RMSE 的目标值。当前 `component RMSE` 约 10.56 m/s，远高于
de Haan / EMADDC 的 aircraft wind observation sigma，说明主误差来自重构、
代表性、时空窗口、稀疏支撑和高空外推，而不是飞机风观测本身。

## 1. 当前基线证据

固定样本：

```text
frame list:
/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_three_method_compare_20260531/analysis/frame_times_200_holdout_seed20260531.txt

frames = 200
holdout_points = 530
```

主结果：

| method | weighted vector RMSE | component RMSE | frame RMSE | frame MAE | P95 RMSE | P99 RMSE | max RMSE |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `timepower15` | 15.038701 | 10.633968 | 8.636457 | 7.423151 | 28.147279 | 63.233730 | 108.858399 |
| `adaptive_v3` | 14.932605 | 10.558946 | 8.457016 | 7.306669 | 28.145171 | 63.233730 | 109.887173 |

解释：

1. `adaptive_v3` 的 weighted vector RMSE 改善 `0.106096 m/s`，约 `0.71%`。
2. 最大改善在 baseline RMSE `10-20 m/s` 区间：`14.640140 -> 12.549462`。
3. P99 基本不动，max 还略差，说明极端长尾没有被 localization v3 解决。
4. `adaptive_v3 + obs-error` 的 frame RMSE 更低，但 weighted RMSE 退化，暂不升为默认。

已生成的关键输出：

```text
comparison:
/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_adaptive_localization_v3_200_20260602/analysis_v3/timepower15_vs_adaptive_v3.md

paper-aligned tables:
/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_adaptive_localization_v3_200_20260602/analysis_v3/timepower15_vs_adaptive_v3_paper_summary.csv
/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_adaptive_localization_v3_200_20260602/analysis_v3/timepower15_vs_adaptive_v3_paper_height_bins.csv
/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_adaptive_localization_v3_200_20260602/analysis_v3/timepower15_vs_adaptive_v3_paper_point_departures.csv

error decomposition:
/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_adaptive_localization_v3_200_20260602/error_source_decomposition/timepower15_vs_adaptive_v3_error_sources.md
```

## 2. 误差优先级

来自 `timepower15_vs_adaptive_v3_error_sources_source_priority.csv`：

| rank | source | worst diagnostic | worst group | priority | first fix |
| ---: | --- | --- | --- | ---: | --- |
| 1 | `vertical_structure` | `vertical_speed_gap_bin` | `vgap_ge30` | 154.696331 | 高度分层 localization，弱化跨层平滑，固定报告 9-12 km / 12 km+ |
| 2 | `representation_error` | `truth_speed_bin` | `speed_ge60` | 75.899148 | 把点观测 vs 500m 网格的代表性误差单独建模 |
| 3 | `sparse_support` | `nearest_distance_bin` | `dist_ge6` | 63.917190 | 最近 current wind 距离/数量进入 gating，低支撑单独报告 |
| 4 | `role_conflict` | `nearest_role_gap_bin` | `gap_ge30` | 54.371614 | role-conflict 阈值按高度/支撑/时间自适应 |
| 5 | `temporal_weighting` | `adaptive_context_time_conf_mean` | `timeconf_ge0_6` | 44.583552 | 用 holdout departure 分箱校准 context time decay |
| 6 | `tail_qc` | `qc_review_bin` | `qc_review` | 34.312897 | P95/P99/max tail audit 和 robust metrics |
| 7 | `localization` | `adaptive_selected_kernel` | `10:5` | 33.433039 | 从 frame-level kernel 改成 point/regime-aware kernel |

## 3. 总运行顺序

推荐按四个 Phase 推进：

```text
Phase 0: 固定 200 帧复现实验和误差分解，确认新改动没有破坏验证规则。
Phase 1: 先做 reporting / representation / temporal calibration，不急着大改模型。
Phase 2: 做 altitude-aware localization、sparse-support gating、role-conflict gating。
Phase 3: 专门处理 P95/P99/max 长尾，建立 tail audit 和 guardrail。
Phase 4: 200 帧过关后，再跑更大 holdout-only set 或 5614 帧 full holdout evaluation。
```

每次候选实验必须输出三类文件：

```text
stage4_localization_sensitivity.csv
stage4_point_departures.csv
pairwise comparison md/csv
error source decomposition md/csv
```

## 4. 可复制运行模板

### 4.1 准备变量

```bash
cd /data/LFT-W02_data/pengxu

PY=/data/LFT-W02_data/pengxu/.conda/envs/windy310/bin/python
STAGE2=/data/LFT-W02_data/pengxu/centralized_v1_output/stage2_full_v2/stage2_multimodal_summary.json
STAGE3=/data/LFT-W02_data/pengxu/centralized_v1_output/stage3_full_v2_25w_payload_only/stage3_center_summary.json
FRAMES200=/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_three_method_compare_20260531/analysis/frame_times_200_holdout_seed20260531.txt

TP_DIR=/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_three_method_compare_20260531/timepower15_metrics
TP_CSV=$TP_DIR/stage4_localization_sensitivity.csv
TP_POINT=$TP_DIR/stage4_point_departures.csv
```

### 4.2 复跑 TimePower15 基线

已有基线目录是 `$TP_DIR`。如需重跑到新目录：

```bash
POLARS_MAX_THREADS=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 \
$PY stage/centralized_v1/core/centralized_stage4_sensitivity.py \
  --stage2-summary $STAGE2 \
  --stage3-summary $STAGE3 \
  --frame-times-file $FRAMES200 \
  --out-dir /data/LFT-W02_data/pengxu/centralized_v1_output/stage4_error_resolution_phase0_200_20260602/timepower15_metrics \
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
  --num-workers 12
```

### 4.3 复跑当前最佳候选 adaptive_v3

已有候选目录：

```text
/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_adaptive_localization_v3_200_20260602/diagnostic_adaptive_v3_metrics
```

如需重跑：

```bash
POLARS_MAX_THREADS=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 \
$PY stage/centralized_v1/core/centralized_stage4_sensitivity.py \
  --stage2-summary $STAGE2 \
  --stage3-summary $STAGE3 \
  --frame-times-file $FRAMES200 \
  --out-dir /data/LFT-W02_data/pengxu/centralized_v1_output/stage4_error_resolution_phase0_200_20260602/adaptive_v3_metrics \
  --sample-count 0 \
  --param-grid 8,4,2,1 \
  --kernels gaussian \
  --confidence-mode diagnostic_weighted \
  --physics-constraint-mode pydda_3dvar_proxy \
  --localization-policy diagnostic_adaptive_v3 \
  --localization-candidate-grid 8:4,10:5 \
  --current-weight-boost 2.0 \
  --context-weight-scale 0.5 \
  --context-time-conf-power 1.5 \
  --role-conflict-mode current_priority_adaptive \
  --conflict-speed-threshold-mps 12 \
  --conflict-context-factor 0.25 \
  --num-workers 12
```

注意：`--param-grid` 用逗号，例如 `8,4,2,1`；`--localization-candidate-grid`
用冒号，例如 `8:4,10:5`。

### 4.4 每次候选跑完后的统一对比

```bash
CAND_DIR=/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_error_resolution_phase0_200_20260602/adaptive_v3_metrics
OUT_DIR=/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_error_resolution_phase0_200_20260602/analysis_adaptive_v3

$PY stage/centralized_v1/core/centralized_stage4_pairwise_frame_compare.py \
  --baseline-csv $TP_CSV \
  --candidate-csv $CAND_DIR/stage4_localization_sensitivity.csv \
  --baseline-point-csv $TP_POINT \
  --candidate-point-csv $CAND_DIR/stage4_point_departures.csv \
  --baseline-label timepower15 \
  --candidate-label adaptive_v3 \
  --out-dir $OUT_DIR \
  --out-prefix timepower15_vs_adaptive_v3 \
  --top-n 30

$PY stage/centralized_v1/core/centralized_stage4_error_source_decomposition.py \
  --baseline-csv $TP_CSV \
  --candidate-csv $CAND_DIR/stage4_localization_sensitivity.csv \
  --baseline-point-csv $TP_POINT \
  --candidate-point-csv $CAND_DIR/stage4_point_departures.csv \
  --baseline-label timepower15 \
  --candidate-label adaptive_v3 \
  --out-dir $OUT_DIR/error_source_decomposition \
  --out-prefix timepower15_vs_adaptive_v3_error_sources \
  --top-tail-n 30
```

验收时先看：

```text
weighted vector RMSE
component RMSE
frame RMSE / MAE
baseline_rmse_le6, 6_10, 10_20, gt20
9-12 km and 12km+ component/vector RMSE
P95 / P99 / max
strict_holdout_no_leakage
motion_used_as_wind
source_priority top 3 是否下降
```

## 5. 逐项误差解决方法

### 5.1 `vertical_structure`

机制：高空和强垂直结构层容易被跨层平滑污染。当前最坏诊断是
`vertical_speed_gap_bin = vgap_ge30`，候选 max vector error 达到
`180.322214 m/s`，12 km+ 仍是最重误差层。

解决方法：

1. 把 9-12 km 和 12 km+ 固定为官方报告层，不再只看全局均值。
2. 启用 `preserve_strong_layers`，在强垂直 jump 或 context mismatch 区域减弱跨层平滑。
3. 后续代码层面把 localization 改成高度分层参数：低空可保守，高空稀疏区允许更宽水平支撑但更谨慎垂直混合。

可直接跑的 200 帧实验：

```bash
POLARS_MAX_THREADS=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 \
$PY stage/centralized_v1/core/centralized_stage4_sensitivity.py \
  --stage2-summary $STAGE2 \
  --stage3-summary $STAGE3 \
  --frame-times-file $FRAMES200 \
  --out-dir /data/LFT-W02_data/pengxu/centralized_v1_output/stage4_error_resolution_phase1_200_20260602/adaptive_v3_vertical_preserve \
  --sample-count 0 \
  --param-grid 8,4,2,1 \
  --kernels gaussian \
  --confidence-mode diagnostic_weighted \
  --physics-constraint-mode pydda_3dvar_proxy \
  --localization-policy diagnostic_adaptive_v3 \
  --localization-candidate-grid 8:4,10:5 \
  --vertical-risk-mode preserve_strong_layers \
  --vertical-gradient-preserve-weight 0.12 \
  --vertical-context-mismatch-damping 0.35 \
  --current-weight-boost 2.0 \
  --context-weight-scale 0.5 \
  --context-time-conf-power 1.5 \
  --role-conflict-mode current_priority_adaptive \
  --conflict-speed-threshold-mps 12 \
  --conflict-context-factor 0.25 \
  --num-workers 12
```

成功标准：

```text
12km+ vector RMSE decreases
9-12 km vector RMSE does not worsen by more than 0.2 m/s
P95/P99 do not worsen
vertical_speed_gap_bin vgap_ge30 candidate max decreases
weighted vector RMSE no worse than adaptive_v3 by 0.1 m/s
```

文献依据：Gaspari-Cohn localization；DART vertical/localization practice；
PyDDA/3DVAR smoothness and physical constraints；Perona-Malik edge-preserving
diffusion。

### 5.2 `representation_error`

机制：现在把飞机点观测直接和 500m 网格、6 分钟窗口的重构值比较。这个 departure
不是纯 aircraft observation error，而是包含采样尺度、插值、局地梯度和时间窗口不一致。
最坏诊断是 `truth_speed_bin = speed_ge60`。

解决方法：

1. 报告层面加入 `representativeness sigma`，和 de Haan / EMADDC sigma 分开。
2. 加入 neighborhood verification：除点值外，同时比较 holdout 周围 1-2 个 voxel 内的最佳/均值/加权邻域误差。
3. 强风、强垂直 jump、低支撑点单独成层，不能和普通风速层混在一个均值里。

需要先做的代码改动：

```text
stage/centralized_v1/core/centralized_stage4_pairwise_frame_compare.py
  add representativeness sigma columns into paper_summary / height_bins

stage/centralized_v1/core/centralized_stage4_sensitivity.py
  for every holdout point, add optional neighborhood departures:
  point_error, neighborhood_mean_error, neighborhood_min_error, neighborhood_weighted_error
```

跑法：代码改完后仍使用 4.4 的 pairwise 和 decomposition 命令。

成功标准：

```text
paper table can explain component RMSE as:
aircraft obs sigma + representativeness sigma + reconstruction residual

ordinary-support / low-gradient bins should move closer to EMADDC sigma
strong-wind and low-support bins may remain high, but must be labeled
component RMSE must no longer be presented as aircraft observation error
```

文献依据：Janjic et al. 2018 representation error in data assimilation；
de Haan 2016 / EMADDC 2025 aircraft wind observation error。

### 5.3 `sparse_support`

机制：当最近非 holdout current wind 太远或数量不足时，Stage4 实际是在外推。最坏诊断是
`nearest_distance_bin = dist_ge6`，低支撑点的 P95/max 长尾很重。

解决方法：

1. 把 `nearest_current_distance`、`nearest_current_count`、`nearest_context_count`
写入 adaptive gating。
2. 建立 `low_support` 官方分层，不和密集支撑插值点混报。
3. 只有在低支撑且低快速变化时才允许 CMA/GFS 弱背景兜底，仍不能当 truth。

当前可先跑的消融：

```bash
POLARS_MAX_THREADS=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 \
$PY stage/centralized_v1/core/centralized_stage4_sensitivity.py \
  --stage2-summary $STAGE2 \
  --stage3-summary $STAGE3 \
  --frame-times-file $FRAMES200 \
  --out-dir /data/LFT-W02_data/pengxu/centralized_v1_output/stage4_error_resolution_phase1_200_20260602/adaptive_v3_sparse_wider_grid \
  --sample-count 0 \
  --param-grid 8,4,2,1 \
  --kernels gaussian \
  --confidence-mode diagnostic_weighted \
  --physics-constraint-mode pydda_3dvar_proxy \
  --localization-policy diagnostic_adaptive_v3 \
  --localization-candidate-grid 8:4,10:5,12:6 \
  --current-weight-boost 2.0 \
  --context-weight-scale 0.5 \
  --context-time-conf-power 1.5 \
  --role-conflict-mode current_priority_adaptive \
  --conflict-speed-threshold-mps 12 \
  --conflict-context-factor 0.25 \
  --num-workers 12
```

需要再做的代码改动：

```text
stage/centralized_v1/core/centralized_stage4_ground_recon.py
  _select_adaptive_localization(...)
  add support-aware branch:
    if current_count <= 1 or nearest_current_distance is large:
      allow wider XY candidate only when context_time_conf is fresh and role_gap is not high
    if high vertical risk:
      do not widen Z blindly
```

成功标准：

```text
nearest_distance_bin dist_ge6 vector RMSE decreases
nearest_current_count count_0/count_1 P95 decreases
baseline_rmse_le6 does not degrade
candidate P99 does not worsen
CMA/GFS branch, if used, reports used_as_background_not_truth=True
```

文献依据：representation error literature；Gaspari-Cohn / DART localization。

### 5.4 `role_conflict`

机制：current aircraft anchors 与 context wind 可能冲突。当前 current-priority 能保护当前观测，
但在 current 支撑太少、holdout 又依赖 context 的位置，会过度削弱上下文。最坏诊断是
`nearest_role_gap_bin = gap_ge30`。

解决方法：

1. role-conflict 阈值按高度、current support、context time confidence 动态变化。
2. current support 小于等于 1 或距离 holdout 远时，不要过度移除 context。
3. 在 holdout 点上正式记录 `role_conflict_at_point` 和 `role_conflict_component_gap`。

可直接跑的阈值消融：

```bash
POLARS_MAX_THREADS=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 \
$PY stage/centralized_v1/core/centralized_stage4_sensitivity.py \
  --stage2-summary $STAGE2 \
  --stage3-summary $STAGE3 \
  --frame-times-file $FRAMES200 \
  --out-dir /data/LFT-W02_data/pengxu/centralized_v1_output/stage4_error_resolution_phase1_200_20260602/adaptive_v3_role_threshold_16 \
  --sample-count 0 \
  --param-grid 8,4,2,1 \
  --kernels gaussian \
  --confidence-mode diagnostic_weighted \
  --physics-constraint-mode pydda_3dvar_proxy \
  --localization-policy diagnostic_adaptive_v3 \
  --localization-candidate-grid 8:4,10:5 \
  --current-weight-boost 2.0 \
  --context-weight-scale 0.5 \
  --context-time-conf-power 1.5 \
  --role-conflict-mode current_priority_adaptive \
  --conflict-speed-threshold-mps 16 \
  --conflict-context-factor 0.25 \
  --num-workers 12
```

再对比 `--conflict-speed-threshold-mps 10`、`12`、`16`，不要只看全局均值，
重点看 `gap_ge30`、`count_0/count_1`、`12km+` 和 P99。

成功标准：

```text
nearest_role_gap_bin gap_ge30 vector RMSE decreases
role_conflict_at_point group does not worsen
baseline_rmse_le6 remains stable
10-20 m/s band keeps adaptive_v3 improvement
```

文献依据：observation/background departure diagnostics in variational DA；
Desroziers diagnostics；PyDDA observation/background constraints。

### 5.5 `temporal_weighting`

机制：context observations 不是同步观测。`context_time_conf_power=1.5` 当前整体有效，
但 `timeconf_ge0_6` 和高 role gap 场景仍有不稳。

解决方法：

1. 用 strict holdout departure 按 time confidence 分箱，拟合 time decay。
2. 对比 `context_time_conf_power = 1.0 / 1.5 / 2.0`。
3. 在高 role gap 时加 stale-context guard。

直接跑的 200 帧消融：

```bash
for POWER in 1.0 2.0
do
  POLARS_MAX_THREADS=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 \
  $PY stage/centralized_v1/core/centralized_stage4_sensitivity.py \
    --stage2-summary $STAGE2 \
    --stage3-summary $STAGE3 \
    --frame-times-file $FRAMES200 \
    --out-dir /data/LFT-W02_data/pengxu/centralized_v1_output/stage4_error_resolution_phase1_200_20260602/adaptive_v3_timepower_${POWER} \
    --sample-count 0 \
    --param-grid 8,4,2,1 \
    --kernels gaussian \
    --confidence-mode diagnostic_weighted \
    --physics-constraint-mode pydda_3dvar_proxy \
    --localization-policy diagnostic_adaptive_v3 \
    --localization-candidate-grid 8:4,10:5 \
    --current-weight-boost 2.0 \
    --context-weight-scale 0.5 \
    --context-time-conf-power $POWER \
    --role-conflict-mode current_priority_adaptive \
    --conflict-speed-threshold-mps 12 \
    --conflict-context-factor 0.25 \
    --num-workers 12
done
```

成功标准：

```text
context_time_conf_bin timeconf_ge0_6 improves
weighted vector RMSE improves or stays within 0.05 m/s
P95/P99 do not worsen
role_conflict gap_ge30 does not worsen
```

文献依据：ECMWF 4D-Var observation-window logic；Desroziers et al. 2005
observation/background diagnostics。

### 5.6 `tail_qc`

机制：少量极端点主导 weighted RMSE、P99 和 max。当前 tail audit 显示最极端点集中在
12 km+、强风、低支撑、role conflict 或 vertical gap。

解决方法：

1. 每次候选都生成 top-tail audit，不再只看 mean RMSE。
2. 官方表中加入 median、P90、P95、P99、trimmed RMSE。
3. tail guardrail 只能防止灾难退化，不能用 max error 单独决定默认模型。

已可直接生成：

```bash
$PY stage/centralized_v1/core/centralized_stage4_error_source_decomposition.py \
  --baseline-csv $TP_CSV \
  --candidate-csv $CAND_DIR/stage4_localization_sensitivity.csv \
  --baseline-point-csv $TP_POINT \
  --candidate-point-csv $CAND_DIR/stage4_point_departures.csv \
  --baseline-label timepower15 \
  --candidate-label candidate \
  --out-dir $OUT_DIR/error_source_decomposition \
  --out-prefix timepower15_vs_candidate_error_sources \
  --top-tail-n 50
```

成功标准：

```text
P95 no worse than timepower15
P99 no worse than timepower15
max cannot worsen by more than 2 m/s unless mean/weighted gain is substantial and tail is explained
qc_review group vector RMSE decreases
top 20 tail cases have suspected_source tags
```

文献依据：EMADDC aircraft QC；Desroziers-style departure monitoring。

### 5.7 `localization`

机制：窄核会错过有用 context，宽核会纳入不相关或陈旧观测。当前 `adaptive_v3`
只是在 frame-level 选择 `8:4` 或 `10:5`，仍不能解决点级低支撑和高空结构问题。

解决方法：

1. 保留 `adaptive_v3` 作为当前默认候选。
2. 下一步把 `_select_adaptive_localization(...)` 从 frame-level 发展成 regime-aware：
   height bin、support、role gap、context time、vertical risk 一起决定候选。
3. 增加 tail-risk guard：若某类候选在 P95/P99 上持续恶化，则只在低风险 bin 使用。

先跑的轻量候选：

```bash
POLARS_MAX_THREADS=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 \
$PY stage/centralized_v1/core/centralized_stage4_sensitivity.py \
  --stage2-summary $STAGE2 \
  --stage3-summary $STAGE3 \
  --frame-times-file $FRAMES200 \
  --out-dir /data/LFT-W02_data/pengxu/centralized_v1_output/stage4_error_resolution_phase1_200_20260602/adaptive_v3_kernel_8_10_12_vertical_preserve \
  --sample-count 0 \
  --param-grid 8,4,2,1 \
  --kernels gaussian \
  --confidence-mode diagnostic_weighted \
  --physics-constraint-mode pydda_3dvar_proxy \
  --localization-policy diagnostic_adaptive_v3 \
  --localization-candidate-grid 8:4,10:5,12:6 \
  --vertical-risk-mode preserve_strong_layers \
  --current-weight-boost 2.0 \
  --context-weight-scale 0.5 \
  --context-time-conf-power 1.5 \
  --role-conflict-mode current_priority_adaptive \
  --conflict-speed-threshold-mps 12 \
  --conflict-context-factor 0.25 \
  --num-workers 12
```

成功标准：

```text
baseline_rmse_10_20 improvement remains >= 1.5 m/s
baseline_rmse_le6 degradation <= 0.05 m/s
P99 does not worsen
12km+ vector RMSE improves
source_priority localization score decreases
```

文献依据：Gaspari and Cohn 1999 covariance localization；DART localization；
LETKF/local data assimilation。

## 6. 扩大样本前的决策门槛

200 帧候选通过以下条件后，才建议扩大：

```text
strict_holdout_no_leakage=True
motion_used_as_wind=False
weighted vector RMSE <= current best 14.788591
component RMSE <= current best 10.457113
P95 <= 28.066373 or nearly unchanged
P99 <= 59.457648 or explained by tail audit
baseline_rmse_le6 degradation <= 0.05 m/s
baseline_rmse_10_20 keeps clear improvement
12km+ vector RMSE improves or does not worsen
```

扩大顺序：

```text
1. larger holdout-only sample, e.g. 500-1000 frames metrics-only
2. all 5614 strict holdout frames metrics-only
3. only after metrics pass, generate representative full NPZ/visuals
4. update teacher-facing summary tables
```

5614 帧全量 strict holdout 运行时，把 `--frame-times-file` 换成只含有 holdout 的
frame list。不要把 1781 个 no-holdout 帧混入 official RMSE/MAE。

## 7. 文献映射

| 用途 | 文献/资料 |
| --- | --- |
| aircraft-derived wind observation error lower bound | de Haan and Stoffelen 2016, AMT, `https://amt.copernicus.org/articles/9/4141/2016/` |
| operational aircraft wind QC and EMADDC sigma prior | EMADDC 2025, AMT, `https://amt.copernicus.org/articles/18/3341/2025/` |
| aircraft observation programme boundary | WMO Aircraft-Based Observations Programme, `https://wmo.int/aircraft-based-observations-programme` |
| representation error | Janjic et al. 2018, `https://doi.org/10.1002/qj.3130` |
| covariance localization | Gaspari and Cohn 1999, `https://doi.org/10.1002/qj.49712555417` |
| observation/background diagnostics | Desroziers et al. 2005, `https://doi.org/10.1256/qj.05.108` |
| variational wind retrieval constraints | PyDDA official docs, `https://openradarscience.org/PyDDA/` |
| edge-preserving diffusion idea | Perona and Malik 1990, `https://doi.org/10.1109/34.56205` |

## 8. 新窗口第一步

新窗口接手时先读：

```text
/data/LFT-W02_data/pengxu/workflow/centralized_v1_docs/new_window_project_handover_20260529/centralized_v1_stage4_error_resolution_plan_20260602.md
/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_adaptive_localization_v3_200_20260602/analysis_v3/timepower15_vs_adaptive_v3.md
/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_adaptive_localization_v3_200_20260602/error_source_decomposition/timepower15_vs_adaptive_v3_error_sources.md
```

然后优先跑两个轻量候选：

```text
1. adaptive_v3_vertical_preserve
2. adaptive_v3_timepower_1.0 / adaptive_v3_timepower_2.0
```

如果这两个都不能压低 12 km+ 和 P99，就不要继续只调全局半径，转向
support-aware / role-aware 的 `_select_adaptive_localization(...)` 代码改动。

## 9. 2026-06-02 晚间更新：25 路顺序优化和窄网格微调

本日后续已完成两轮额外 25 路 metrics-only 优化：

```text
priority pass:
/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_error_resolution_priority_20260602_25w

focused refinement:
/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_error_resolution_refine_20260602_25w

narrow 3x3 grid refinement:
/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_error_resolution_narrow_grid_20260602_25w
```

新增代码入口：

```text
stage/centralized_v1/error_resolution/stage4_priority_runner.py
stage/centralized_v1/error_resolution/stage4_refinement_runner.py
stage/centralized_v1/error_resolution/stage4_narrow_grid_refinement_runner.py
```

### 9.1 当前最新最优 200 帧候选

当前最佳 200 帧 strict holdout 候选已从 `adaptive_v3` 继续提升到：

```text
tp24_thr11_preserve
```

对应运行目录：

```text
/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_error_resolution_narrow_grid_20260602_25w/runs/07_tp24_thr11_preserve
```

对应参数：

```text
--confidence-mode diagnostic_weighted
--physics-constraint-mode pydda_3dvar_proxy
--localization-policy diagnostic_adaptive_v3
--localization-candidate-grid 8:4,10:5
--current-weight-boost 2.0
--context-weight-scale 0.5
--context-time-conf-power 2.4
--role-conflict-mode current_priority_adaptive
--conflict-speed-threshold-mps 11
--conflict-context-factor 0.25
--vertical-risk-mode preserve_strong_layers
--vertical-gradient-preserve-weight 0.12
--vertical-context-mismatch-damping 0.35
--num-workers 25
```

### 9.2 指标更新

与最初 `timepower15` 相比：

```text
timepower15:
  weighted RMSE 15.038701
  frame RMSE    8.636457
  weighted MAE  7.172653
  P95           28.147279
  P99           63.233730

tp24_thr11_preserve:
  weighted RMSE 14.788591
  frame RMSE    8.253448
  weighted MAE  6.880177
  P95           28.066373
  P99           59.457648
```

与上一版 `tp22_thr12_preserve` 相比：

```text
tp22_thr12_preserve:
  weighted RMSE 14.812760
  frame RMSE    8.292031
  weighted MAE  6.913243
  P99           60.190239

tp24_thr11_preserve:
  weighted RMSE 14.788591
  frame RMSE    8.253448
  weighted MAE  6.880177
  P99           59.457648
```

关键 band 变化（`tp22_thr12_preserve -> tp24_thr11_preserve`）：

```text
baseline_rmse_le6:   -0.033440
baseline_rmse_6_10:  -0.019015
baseline_rmse_10_20: -0.117066
baseline_rmse_gt20:  -0.044934
12km+ vector RMSE:   -0.022560
```

说明：这次窄网格微调不是只提升某一个尾部指标，而是 low-error band、mid band、
12km+ 和 P99 一起小幅变好，因此它可以作为新的最优 200 帧候选。

### 9.3 focused refinement 和 obs_error 结论

focused refinement 先证明：

```text
tp22_thr12_preserve > timepower_2_0
```

narrow-grid refinement 再证明：

```text
tp24_thr11_preserve > tp22_thr12_preserve
```

obs-error 线的当前结论保持不变：

```text
EMADDC height-prior obs_error_weighted 没有在当前最优链路上带来稳定净收益，
因此暂不作为默认主线。
```

后续如果继续做 `obs_error`，建议先重做：

```text
1. 明确分离 observation error 与 representativeness error
2. 让 obs_error 进入 per-point / regime-aware gating，而不是只做全局 weight 替换
3. 与 support-aware localization 联合设计，而不是单独接一张 height sigma 表
```

### 9.4 接下来最值得投入的方向

当前不建议再做大范围乱扫。推荐顺序：

```text
1. 先把 tp24_thr11_preserve 作为新的最优 200 帧候选
2. 若还要微调，只做更窄的局部搜索，例如：
   context_time_conf_power = 2.4 / 2.5
   conflict_speed_threshold_mps = 10 / 11 / 12
3. 下一阶段最值得投入的不是继续堆全局参数，
   而是更强的 per-point support-aware localization / regime-aware localization
4. 通过 200 帧后，再扩大到 500-1000 holdout-only metrics-only，
   最后再上 5614 帧 strict holdout 全量验证
```

### 9.5 当前推荐全量 25 路配置

若直接做下一次全量 strict holdout / 全帧 metrics-only 推荐优先使用：

```text
--confidence-mode diagnostic_weighted
--physics-constraint-mode pydda_3dvar_proxy
--localization-policy diagnostic_adaptive_v3
--localization-candidate-grid 8:4,10:5
--current-weight-boost 2.0
--context-weight-scale 0.5
--context-time-conf-power 2.4
--role-conflict-mode current_priority_adaptive
--conflict-speed-threshold-mps 11
--conflict-context-factor 0.25
--vertical-risk-mode preserve_strong_layers
--vertical-gradient-preserve-weight 0.12
--vertical-context-mismatch-damping 0.35
--num-workers 25
```

如果需要生成全量命令模板，可参考：

```text
/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_error_resolution_narrow_grid_20260602_25w/reports/run_best_full_25w.sh
```
