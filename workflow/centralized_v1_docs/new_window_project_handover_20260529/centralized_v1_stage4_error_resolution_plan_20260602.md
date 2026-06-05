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

## 10. 2026-06-05 SRHA + Sparse Temporal CMA/NWP 结果

本节是 2026-06-05 新窗口执行结果，覆盖上面旧的下一步推荐口径。用户已确认当前主基线固定为
`tp26_thr11_preserve`，不是 `timepower_2_0` 或 `tp22_thr12_preserve`。所有结果仍只使用：

```text
truth = current aircraft wind_records strict holdout
strict_holdout_no_leakage = True
motion_used_as_wind = False
CMA/GFS/ERA = weak background / prior only, never truth
```

### 10.1 已改代码

主要修改文件：

```text
stage/centralized_v1/core/centralized_stage4_ground_recon.py
stage/centralized_v1/core/centralized_stage4_sensitivity.py
stage/centralized_v1/core/centralized_stage4_error_source_decomposition.py
```

实现内容：

```text
1. support_role_height_aware 进入 metrics-only adaptive selector。
2. support_role_height_aware 新增 per-observation horizontal sigma/radius factor：
   - alt >= 12000m、speed >= 60m/s、role gap >= 18m/s、stale context、dense current support 时收窄。
   - 只有 current_count <= 2、context fresh、local consistency stable、role gap low 且无高空/强风/stale 风险时才允许扩大。
3. support_role_height_aware 同步影响 support_adaptive vertical localization，对 role gap / stale context 做垂直收窄。
4. CSV 新增 SRHA 诊断：
   srha_horizontal_sigma_factor_mean/min/max
   srha_horizontal_reason_counts
   srha_high_altitude_gate_count
   srha_high_speed_gate_count
   srha_role_gap_gate_count
   srha_stale_context_gate_count
   srha_sparse_fresh_widen_gate_count
   srha_dense_current_gate_count
5. 新增 CMA/NWP background weight mode:
   cma_background_weight_mode = sparse_temporal_gated
6. 新增 strict temporal gating：
   temporal_conf >= 0.55
   rapid-change flag must be 0 when available
   temporal-change-speed must stay below calibrated threshold when available
7. sparse_temporal_gated 只在 sparse/no-current-support 且已有 localized aircraft support 的体素上给背景权重；
   current-supported / non-sparse 区域背景权重强制为 0。
8. CLI、parent shards、metrics-only 全链路透传 --cma-background-weight-mode。
9. CSV 新增 CMA gate 诊断：
   cma_background_weight_mode
   cma_background_gate_active_fraction
   cma_background_sparse_current_gate_fraction
   cma_background_localized_support_gate_fraction
   cma_background_no_current_gate_voxels
   cma_strict_temporal_gate_active_fraction
10. 修正 error_source_decomposition markdown 文案：
    候选劣化时不再错误写成 "improves"。
```

静态检查：

```text
python -m py_compile
  stage/centralized_v1/core/centralized_stage4_ground_recon.py
  stage/centralized_v1/core/centralized_stage4_sensitivity.py
  stage/centralized_v1/core/centralized_stage4_error_source_decomposition.py

结果：通过
```

smoke test：

```text
SRHA 2 帧 smoke:
  rows = 2
  strict_holdout_no_leakage = True
  motion_used_as_wind = False
  srha_horizontal_sigma_factor_mean 有输出

CMA sparse_temporal_gated 1 帧 smoke:
  cma_background_weight_mode = sparse_temporal_gated
  cma_background_gate_active_fraction = 0.008180
  cma_background_localized_support_gate_fraction = 0.008297
  strict_holdout_no_leakage = True
  motion_used_as_wind = False
```

### 10.2 Phase 1: tp26 vs SRHA

输出目录：

```text
/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_srha_tail_200_20260605_25w

baseline:
  baseline_tp26_thr11_preserve

candidate:
  tp26_srha_tail

pairwise:
  analysis/tp26_vs_srha/tp26_vs_srha.md

error-source / top-tail:
  analysis/tp26_vs_srha_error_source/tp26_vs_srha.md
  analysis/tp26_vs_srha_error_source/tp26_vs_srha_tail_audit.csv
```

运行口径：

```text
frames = 200
holdout_points = 530
num_workers = 25
baseline = tp26_thr11_preserve
candidate = tp26 + support_role_height_aware
candidate grid = 8:4,10:5,12:6
vertical_localization_policy = support_adaptive
```

Phase 1 指标：

| method | weighted RMSE | weighted MAE | frame RMSE | frame P95 | frame P99 | point P95 | 12km+ vector RMSE | 12km+ P95 | max point |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `tp26_thr11_preserve` | 14.769036 | 6.854454 | 8.224309 | 27.986111 | 58.783770 | 23.889507 | 19.917698 | 35.523490 | 180.131789 |
| `tp26_srha_tail` | 20.148615 | 8.206679 | 10.246083 | 34.727103 | 86.322454 | 31.540111 | 28.454526 | 45.670509 | 253.572554 |

SRHA 诊断汇总：

```text
mean(srha_horizontal_sigma_factor_mean over frames) = 0.822454
srha_high_altitude_gate_count total = 69113
srha_high_speed_gate_count total = 6156
srha_role_gap_gate_count total = 28145
srha_stale_context_gate_count total = 34232
srha_sparse_fresh_widen_gate_count total = 1849
srha_dense_current_gate_count total = 2517
```

promotion rule 结论：

```text
FAIL, do not promote SRHA.

原因：
weighted RMSE: 14.769036 -> 20.148615, worse by 5.379579 m/s
frame P95:     27.986111 -> 34.727103, worse
frame P99:     58.783770 -> 86.322454, worse
12km+ RMSE:    19.917698 -> 28.454526, worse by 8.536828 m/s
```

top-tail 结论：

```text
SRHA 确实触发了高空/强风/role/stale gate，但当前实现过于激进。
最坏新增长尾来自 12km+ role_conflict：
  20260202013600 z/y/x=29/281/519
  baseline error 18.236828 -> SRHA error 253.572554

Phase 2 baseline 因此继续使用 tp26_thr11_preserve。
```

### 10.3 Phase 2: tp26 vs Sparse Temporal CMA/NWP

输出目录：

```text
/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_sparse_temporal_cma_200_20260605_25w

baseline:
  baseline_tp26_thr11_preserve

candidate:
  tp26_sparse_temporal_cma

pairwise:
  analysis/tp26_vs_sparse_temporal_cma/tp26_vs_sparse_temporal_cma.md

error-source / top-tail:
  analysis/tp26_vs_sparse_temporal_cma_error_source/tp26_vs_sparse_temporal_cma.md
  analysis/tp26_vs_sparse_temporal_cma_error_source/tp26_vs_sparse_temporal_cma_tail_audit.csv
```

运行口径：

```text
frames = 200
holdout_points = 530
num_workers = 25
baseline = tp26_thr11_preserve
candidate = tp26 + cma_reanalysis_background
cma_proxy_dir = centralized_v1_output/stage4_three_method_compare_20260531/cma_proxy
cma_background_weight = 0.01
cma_background_weight_mode = sparse_temporal_gated
cma_confidence_source = temporal_conf
cma_qc_gating = strict_temporal
cma_confidence_cap = 0.20
```

Phase 2 指标：

| method | weighted RMSE | weighted MAE | frame RMSE | frame P95 | frame P99 | point P95 | 12km+ vector RMSE | 12km+ P95 | max point |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `tp26_thr11_preserve` | 14.769036 | 6.854454 | 8.224309 | 27.986111 | 58.783770 | 23.889507 | 19.917698 | 35.523490 | 180.131789 |
| `tp26_sparse_temporal_cma` | 14.852237 | 7.040594 | 8.408913 | 26.226386 | 53.532347 | 26.210852 | 19.951609 | 35.522361 | 179.636076 |

CMA gate 诊断：

| diagnostic | mean | min | max |
| --- | ---: | ---: | ---: |
| `cma_background_gate_active_fraction` | 0.007787 | 0.003273 | 0.015512 |
| `cma_background_sparse_current_gate_fraction` | 0.007787 | 0.003273 | 0.015512 |
| `cma_background_localized_support_gate_fraction` | 0.009937 | 0.004267 | 0.017334 |
| `cma_strict_temporal_gate_active_fraction` | 0.854742 | 0.705739 | 1.000000 |
| `cma_background_gate_mean` | 0.007666 | 0.003230 | 0.015360 |

gate 结论：

```text
sparse_temporal_gated 不是全场融合。
background active fraction 平均约 0.78%，最大约 1.55%。
非 sparse/current-supported 区域权重被强制压到 0。
```

promotion rule 结论：

```text
FAIL, do not promote CMA/NWP candidate.

原因：
weighted RMSE: 14.769036 -> 14.852237, worse by 0.083201 m/s
weighted MAE:  6.854454 -> 7.040594, worse by 0.186140 m/s
12km+ RMSE:    19.917698 -> 19.951609, worse by 0.033911 m/s

虽然 frame P95/P99 和 max point 有改善：
frame P95: 27.986111 -> 26.226386
frame P99: 58.783770 -> 53.532347
max point: 180.131789 -> 179.636076

但验收规则要求 weighted RMSE、P95、P99、12km+ 全部不劣化，因此不推广。
```

top-tail 结论：

```text
CMA weak background 对最极端 12km+ 点有轻微缓和：
  20260223133000 z/y/x=29/345/498
  baseline error 180.131789 -> CMA error 179.636076

但它也在部分低空/中低空 sparse 点引入新误差：
  20260210011200 z/y/x=10/295/510, 3-6km
  baseline error 10.363190 -> CMA error 34.218618

这说明当前 CMA proxy 在 sparse 区域仍需要更细的 height / speed / source-role gate，
不能因为 P95/P99 下降就升级默认。
```

### 10.4 Wind-scale impact: 绝对误差必须结合原始风速/风向解释

补充结论：RMSE/MSE 是必要主指标，但不能单独解释影响大小。相同的 `8 m/s` 误差：

```text
1. 在 80-100 m/s 高空强风中，可能只是 8%-10% 相对误差。
2. 在 5-15 m/s 轻风中，可能已经是 50%-160% 相对误差。
3. 在近静风中，风向本身不稳定，方向误差不应直接参与均值。
```

因此新增 wind-scale impact 分析脚本：

```text
stage/centralized_v1/core/centralized_stage4_wind_scale_impact.py
```

分析定义：

```text
relative_error_ratio = vector_error / gt_speed
floor10_relative_error = vector_error / max(gt_speed, 10)
direction_error_deg = abs circular angle difference from atan2(v, u)

direction_error_deg exclusion:
  gt_speed < 5 m/s or pred_speed < 1 m/s -> NA
```

新增输出：

```text
SRHA wind-scale:
/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_srha_tail_200_20260605_25w/analysis/tp26_vs_srha_wind_scale/tp26_vs_srha_wind_scale.md
/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_srha_tail_200_20260605_25w/analysis/tp26_vs_srha_wind_scale/tp26_vs_srha_wind_scale_method_groups.csv
/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_srha_tail_200_20260605_25w/analysis/tp26_vs_srha_wind_scale/tp26_vs_srha_wind_scale_delta_groups.csv
/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_srha_tail_200_20260605_25w/analysis/tp26_vs_srha_wind_scale/tp26_vs_srha_wind_scale_top_candidate_worsening.csv

CMA wind-scale:
/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_sparse_temporal_cma_200_20260605_25w/analysis/tp26_vs_sparse_temporal_cma_wind_scale/tp26_vs_sparse_temporal_cma_wind_scale.md
/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_sparse_temporal_cma_200_20260605_25w/analysis/tp26_vs_sparse_temporal_cma_wind_scale/tp26_vs_sparse_temporal_cma_wind_scale_method_groups.csv
/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_sparse_temporal_cma_200_20260605_25w/analysis/tp26_vs_sparse_temporal_cma_wind_scale/tp26_vs_sparse_temporal_cma_wind_scale_delta_groups.csv
/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_sparse_temporal_cma_200_20260605_25w/analysis/tp26_vs_sparse_temporal_cma_wind_scale/tp26_vs_sparse_temporal_cma_wind_scale_top_candidate_worsening.csv
```

wind-scale 完整性检查：

```text
aligned points = 530
strict_holdout_no_leakage = True
motion_used_as_wind = False
truth speed bins sum = 530
```

SRHA 按 truth speed 分层：

| truth speed bin | points | baseline RMSE | SRHA RMSE | mean delta | worse >5m/s | floor10 rel delta |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `0-5mps_calm` | 34 | 5.582881 | 5.400053 | -0.257366 | 0 | -0.025737 |
| `5-15mps_light` | 129 | 5.195877 | 5.183379 | -0.098104 | 2 | -0.006038 |
| `15-30mps_moderate` | 205 | 8.727973 | 10.442562 | 0.930695 | 14 | 0.043517 |
| `30-60mps_strong` | 137 | 12.312020 | 16.553500 | 1.668888 | 10 | 0.045909 |
| `60mps_plus_extreme` | 25 | 54.655257 | 77.668477 | 12.746208 | 5 | 0.198031 |

SRHA 风速/风向解释：

```text
SRHA 的问题不是普通弱风，而是高空强风和 role-conflict 下的灾难性方向/幅值错误。
最坏点：
  20260202013600 z/y/x=29/281/519, 12km+, gt_speed=60 m/s
  baseline error 18.236828 -> SRHA error 253.572554
  candidate relative_error_ratio = 4.226209
  candidate direction_error_deg = 162.97

这不是“强风下差 8 m/s 可接受”的情况，而是方向几乎反向且幅值严重偏离。
```

CMA 按 truth speed 分层：

| truth speed bin | points | baseline RMSE | CMA RMSE | mean delta | worse >5m/s | floor10 rel delta |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `0-5mps_calm` | 34 | 5.582881 | 5.524242 | -0.054784 | 0 | -0.005478 |
| `5-15mps_light` | 129 | 5.195877 | 6.057278 | 0.305396 | 2 | 0.024890 |
| `15-30mps_moderate` | 205 | 8.727973 | 8.980202 | 0.230951 | 4 | 0.012310 |
| `30-60mps_strong` | 137 | 12.312020 | 12.273071 | 0.093998 | 1 | 0.001988 |
| `60mps_plus_extreme` | 25 | 54.655257 | 54.396091 | 0.035925 | 0 | 0.001260 |

CMA 风速/风向解释：

```text
CMA 的绝对 P95/P99 有改善，但 wind-scale 暴露出更关键风险：
  20260210011200 z/y/x=10/295/510, 3-6km, gt_speed=13 m/s
  baseline error 10.363190 -> CMA error 34.218618
  candidate relative_error_ratio = 2.632201
  candidate direction_error_deg = 97.95

这个点说明：在轻风/中低空 sparse 区域，CMA weak background 可能把小风场拉成严重错误。
这种错误比高风速下 8 m/s 绝对差异更不可接受。
```

升级后的下一轮 promotion gate：

```text
仍必须满足原 gate：
  weighted RMSE 不劣化
  P95 不劣化
  P99 不劣化
  12km+ vector RMSE 不劣化

新增 wind-scale guard：
  5-15mps_light bin 不允许 RMSE/MAE 明显劣化
  0-5mps_calm 和 5-15mps_light 不允许新增 delta > 5 m/s 的 top-tail
  floor10_relative_error_mae 不允许劣化
  低风速点 direction_error_deg 只作解释，不作均值硬门槛
  若 light/moderate wind 出现 candidate relative_error_ratio > 2 且 delta > 5 m/s，候选直接失败
```

下一步建议相应调整：

```text
1. 不继续调当前 SRHA shrink/widen 因子。
2. CMA/NWP 只保留 sparse_temporal_gated 实现和诊断列，不升默认。
3. 下一轮先做 guardrail/reporting，再做模型改动：
   - 把 truth_speed_bin、floor10_relative_error、direction_error_deg 写入正式 pairwise/checklist。
   - 对 3-6km、5-15mps、15-30mps 的新坏点单独设失败门槛。
   - CMA gate 需要额外 height/speed/source-role guard，特别是 3-6km light-wind current-supported sparse 点。
```

### 10.5 Skills GitHub 状态

按用户确认，skills 只处理独立仓库，不纳入 windy 主仓库：

```text
local repo:
/data/LFT-W02_data/pengxu/nature-skills

remote:
https://github.com/Yuan1z0825/nature-skills.git

branch:
main

HEAD:
c9b874a675e29e40fed88af89509092665d5a236

upstream:
c9b874a675e29e40fed88af89509092665d5a236

status:
clean, no ahead commit
```

结论：

```text
nature-skills 当前已与 GitHub origin/main 对齐，没有本地改动需要提交或推送。
未把 /data/LFT-W02_data/pengxu/nature-skills 加入 windy 主仓库；
windy 主仓库里仍保持 nature-skills/ 为 untracked 状态。
```

### 10.6 当前默认与下一步

当前默认保持：

```text
tp26_thr11_preserve

--confidence-mode diagnostic_weighted
--physics-constraint-mode pydda_3dvar_proxy
--localization-policy diagnostic_adaptive_v3
--localization-candidate-grid 8:4,10:5
--current-weight-boost 2.0
--context-weight-scale 0.5
--context-time-conf-power 2.6
--role-conflict-mode current_priority_adaptive
--conflict-speed-threshold-mps 11.0
--conflict-context-factor 0.25
--vertical-risk-mode preserve_strong_layers
--vertical-gradient-preserve-weight 0.12
--vertical-context-mismatch-damping 0.35
--num-workers 25
```

不要推广：

```text
support_role_height_aware
sparse_temporal_gated CMA/NWP
```

下一步建议：

```text
1. SRHA 不要继续用当前 shrink/widen 因子直接放大到默认；
   需要先按 holdout-nearest distance、nearest role、vertical_speed_gap、truth_speed_bin 做更细 guard。
2. CMA/NWP 可以保留 sparse_temporal_gated 实现和诊断列，
   但后续候选必须额外排除 3-6km 新长尾，并对 role_gap/source_role 加更硬 gate。
3. 后续文档引用 decomposition markdown 时，以修正后的 "Candidate vs Baseline" 版本为准。
```

### 10.7 2026-06-05 formal guardrail + display-filled visualization

本轮已把 promotion guardrail 从“临时分析口径”固化进正式 pairwise/checklist，并新增只服务展示层的
display-filled 风场字段。默认模型仍是 `tp26_thr11_preserve`，SRHA 和 CMA sparse-temporal
candidate 仍不升默认。

代码入口：

```text
stage/centralized_v1/core/centralized_stage4_pairwise_frame_compare.py
stage/centralized_v1/core/centralized_stage4_ground_recon.py
stage/centralized_v1/core/centralized_report_stage4_slices.py
stage/centralized_v1/core/centralized_stage4_representative_wind_table.py
```

新增正式 pairwise/checklist 输出：

```text
*_wind_scale_method_groups.csv
*_wind_scale_delta_groups.csv
*_promotion_checklist.csv
*_promotion_checklist.md
```

point-level wind-scale 字段已进入 pairwise：

```text
gt_speed_mps
truth_speed_bin
baseline/candidate relative_error_ratio
baseline/candidate floor10_relative_error
baseline/candidate direction_error_deg
delta_vector_error
```

promotion gate 固定为全部同时满足：

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

200 帧、25 worker 复跑入口：

```text
centralized_v1_output/stage4_guardrail_display_fill_200_20260605_25w/tp26_thr11_preserve_metrics/
```

静态检查已通过：

```text
python -m py_compile
centralized_stage4_ground_recon.py
centralized_stage4_sensitivity.py
centralized_stage4_pairwise_frame_compare.py
centralized_stage4_wind_scale_impact.py
centralized_report_stage4_slices.py
centralized_stage4_representative_wind_table.py
```

formal checklist 结果：

| comparison | checklist | result | key reason |
| --- | --- | --- | --- |
| tp26 existing vs 200-frame rerun | `centralized_v1_output/stage4_guardrail_display_fill_200_20260605_25w/analysis/tp26_existing_vs_rerun/tp26_existing_vs_rerun_promotion_checklist.md` | PASS | metrics identical; no drift. |
| tp26 vs SRHA | `centralized_v1_output/stage4_guardrail_display_fill_200_20260605_25w/analysis/tp26_vs_srha_formal_guardrail/tp26_vs_srha_formal_guardrail_promotion_checklist.md` | FAIL | weighted RMSE, P95, P99, 12km+, floor10 relative error and light/moderate tail fail. |
| tp26 vs sparse-temporal CMA | `centralized_v1_output/stage4_guardrail_display_fill_200_20260605_25w/analysis/tp26_vs_sparse_temporal_cma_formal_guardrail/tp26_vs_sparse_temporal_cma_formal_guardrail_promotion_checklist.md` | FAIL | weighted RMSE, 12km+, light wind RMSE/MAE, floor10 relative error and light/moderate tail fail. |

关键数值：

```text
tp26 existing vs rerun:
weighted RMSE 14.769035584178605 -> 14.769035584178605
frame P95     27.986110980146194 -> 27.986110980146194
frame P99     58.78377017267204  -> 58.78377017267204

tp26 vs SRHA:
weighted RMSE 14.769035584178605 -> 20.148614706594163
frame P95     27.986110980146194 -> 34.72710322612249
frame P99     58.78377017267204  -> 86.32245410423373
12km+ RMSE    19.917697780481415 -> 28.454525761392187

tp26 vs sparse-temporal CMA:
weighted RMSE 14.769035584178605 -> 14.852237035605219
12km+ RMSE    19.917697780481415 -> 19.951608908326953
light RMSE    5.195876810373414  -> 6.057278442944428
light MAE     4.185283061205855  -> 4.490679519582376
```

display-filled 字段只用于展示层补全：

```text
stage4_display_u_3d
stage4_display_v_3d
stage4_display_confidence_3d
stage4_display_mask_3d
stage4_display_source_3d
stage4_display_fill_diagnostics_json
```

语义边界：

```text
recon_u/v/conf/mask = official tp26 strict reconstruction
stage4_display_* = official recon where recon_mask true + low-confidence weak background elsewhere
CMA/background never enters official point evaluation
display_fill_is_official_accuracy = False
```

代表帧 display-filled NPZ：

```text
centralized_v1_output/stage4_guardrail_display_fill_200_20260605_25w/representative_display_filled_npz/
```

代表帧全图彩色可视化：

```text
centralized_v1_output/stage4_guardrail_display_fill_200_20260605_25w/representative_display_filled_visuals/
```

代表帧：

```text
20260206074200
20260125124200
20260205190000
20260210011200
20260202013600
20260223133000
```

代表帧风速/风向差异表：

```text
centralized_v1_output/stage4_guardrail_display_fill_200_20260605_25w/representative_display_filled_visuals/representative_wind_speed_direction_table.csv
centralized_v1_output/stage4_guardrail_display_fill_200_20260605_25w/representative_display_filled_visuals/representative_wind_speed_direction_table.md
```

表格字段包括：

```text
gt_speed_mps
pred_speed_mps
speed_delta_mps
gt_direction_deg
pred_direction_deg
direction_error_deg
vector_error_mps
relative_error_ratio
floor10_relative_error
truth_speed_bin
```

observation-error 口径修正：

```text
de Haan / EMADDC 的 sigma 只能作为 aircraft wind observation-error prior 或 QC 诊断权重。
本项目当前 13.64 m/s 应解释为 local consistency / representativeness sigma。
任何 sigma 都不能从 Stage4 strict-holdout RMSE/MAE 里扣除。
location 的 u_motion/v_motion 仍是 aircraft ground motion，不是 atmospheric wind。
```
