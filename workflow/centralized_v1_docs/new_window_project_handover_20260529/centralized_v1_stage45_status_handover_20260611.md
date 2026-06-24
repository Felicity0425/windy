# centralized_v1 Stage4/Stage5 handover - 2026-06-11

This handover records the current Stage4 representation-weight and Stage5 residual-PINN status after the 2026-06-10 runs. It is written for the next window to continue without re-discovering the same failure modes.

## Executive status

Default method remains:

```text
Stage4 default = tp26_thr11_preserve
```

Do not promote either of the current candidate branches yet:

```text
tp26_rep_soft_weight_v1 = 200-frame PASS, 5614-frame validation incomplete/stalled
Stage5 residual PINN field-v2 = gate-only replay has safe tiny signal, not a full-field/default replacement
```

The manuscript draft can keep the conservative claims:

```text
Stage4 tp26_thr11_preserve is the main validated method.
tp26_rep_soft_weight_v1 is a promising reliability/representation branch, not default.
Stage5 residual PINN is a narrow gated candidate, not default.
```

## Key artifacts

Manuscript draft:

```text
workflow/centralized_v1_docs/new_window_project_handover_20260529/centralized_v1_manuscript_draft_v0_20260610.md
```

Stage4 default full run:

```text
centralized_v1_output/stage4_full_tp26_thr11_preserve_25w_taildiag_20260602_173319/
```

Stage4 representation soft weight, completed 200-frame formal run:

```text
centralized_v1_output/stage4_representation_soft_weight_200_20260608/tp26_rep_soft_weight_v1_metrics/
centralized_v1_output/stage4_representation_soft_weight_200_20260608/analysis/tp26_vs_rep_soft_weight_v1_formal_guardrail/
```

Stage4 representation soft weight, attempted 5614-frame run:

```text
centralized_v1_output/stage4_representation_soft_weight_5614_20260610/tp26_rep_soft_weight_v1_metrics/
```

Stage5 field-v2 replay with corrected promotion tolerance:

```text
centralized_v1_output/stage5_residual_pinn_field_v2_gate_sweep_20260610_tol1e9/field_v2_replay/
```

Point-level Stage5 gate sweep used as the source for field-v1/field-v2 replay:

```text
centralized_v1_output/stage5_residual_pinn_field_v2_gate_sweep_20260610/point_gate_only/
```

## Code status

Intentional code change:

```text
stage/centralized_v1/core/centralized_stage4_pairwise_frame_compare.py
```

Change:

```text
promotion no-worse comparisons now use --promotion-tolerance, default 1e-9
```

Reason:

```text
The strict comparison falsely failed cases like:
baseline  = 19.91769778048141
candidate = 19.917697780481415
```

This is a floating-point zero-difference at the scale of the metric. The point-level gate selector already used tolerance logic; the pairwise promotion gate now matches that behavior.

Do not interpret this tolerance as allowing meaningful degradation. It only prevents double-precision formatting noise from failing a gate.

## Stage4: tp26_rep_soft_weight_v1

### Completed 200-frame formal result

`tp26_rep_soft_weight_v1` passed the 200-frame formal promotion checklist.

Known result:

```text
baseline tp26_thr11_preserve weighted RMSE = 14.769036 m/s
candidate tp26_rep_soft_weight_v1 weighted RMSE = 14.755381 m/s
delta = -0.013655 m/s
PROMOTION_OVERALL = PASS
```

Guardrail summary:

| Gate | Baseline | Candidate | Result |
| --- | ---: | ---: | --- |
| weighted RMSE | 14.769036 | 14.755381 | PASS |
| frame P95 | 27.986111 | 27.947974 | PASS |
| frame P99 | 58.783770 | 58.756881 | PASS |
| 12km+ vector RMSE | 19.917698 | 19.884741 | PASS |
| light wind RMSE | 5.195877 | 5.165311 | PASS |
| light wind MAE | 4.185283 | 4.160541 | PASS |
| floor10 relative MAE | 0.282804 | 0.281212 | PASS |
| new light/moderate catastrophic failure | 0 | 0 | PASS |

Interpretation:

```text
The branch is methodologically clean and useful as a reliability/representation-error direction.
The aggregate gain is very small.
Extreme tail is not solved.
Do not replace tp26_thr11_preserve from this 200-frame result alone.
```

### Attempted 5614-frame run status

Attempted root:

```text
centralized_v1_output/stage4_representation_soft_weight_5614_20260610/tp26_rep_soft_weight_v1_metrics/
```

Current state as checked on 2026-06-11:

```text
25 shard progress files exist
all shards still say status=running
total progress = 1729 / 5614 = 30.80%
latest progress/log updates stopped at about 2026-06-10 19:41 Asia/Hong_Kong
top-level merged outputs are missing
```

Missing top-level outputs:

```text
stage4_localization_sensitivity.csv
stage4_point_departures.csv
stage4_localization_sensitivity_aggregate.csv
stage4_localization_sensitivity_aggregate.md
```

Conclusion:

```text
The 5614-frame soft-weight run is incomplete/stalled.
Do not use this partial directory as evidence.
Rerun to a clean retry root rather than trying to manually salvage partial shards.
```

## Stage5: residual PINN status

### Point-level signal

The safest nonzero point-level candidate remains:

```text
candidate = cap1p0_seed20260609_w512_l6
gate = vertical_gap_ge20_not_light
scale = 1.0
locked test enabled = 33 / 1893 points
test RMSE = 9.896785 -> 9.892352 m/s
```

Interpretation:

```text
The signal is real but tiny.
It is a gated residual candidate only.
It is not a replacement for Stage4.
```

### Field-v2 replay result after promotion tolerance fix

Corrected replay root:

```text
centralized_v1_output/stage5_residual_pinn_field_v2_gate_sweep_20260610_tol1e9/field_v2_replay/
```

Result:

```text
variants = 64
promotion-pass variants = 16
```

All passing variants are `alt12_off`, meaning 12km+ residuals are completely disabled. The best passing variants are:

| Variant | Changed points | Weighted RMSE | 12km+ RMSE |
| --- | ---: | ---: | ---: |
| alt12_off_cap10p0_riskoff_cleanoff | 2 | 14.757868916 | 19.917697780 |
| alt12_off_cap10p0_riskoff_cleansup | 2 | 14.757868916 | 19.917697780 |
| alt12_off_cap1p0_riskoff_cleanoff | 2 | 14.760623318 | 19.917697780 |
| alt12_off_cap1p0_riskoff_cleansup | 2 | 14.760623318 | 19.917697780 |

Important negative finding:

```text
Any nonzero 12km+ residual scale still causes real 12km+ degradation.
The closest non-alt12-off failures improve weighted RMSE but worsen 12km+ RMSE by about 0.002 m/s or more.
```

Interpretation:

```text
Stage5 field-v2 has a safe tiny effect only by leaving 12km+ untouched.
This is not strong enough to update the manuscript main claim.
Keep Stage5 as a candidate/smoke result.
```

## Recommended next run order

Priority 1:

```text
Rerun tp26_rep_soft_weight_v1 on the full 5614 holdout-evaluable frame set.
```

Priority 2:

```text
Pairwise compare full-5614 tp26_rep_soft_weight_v1 against tp26_thr11_preserve.
```

Priority 3:

```text
Only if the full-5614 representation branch passes, decide whether to update the manuscript result language.
```

Priority 4:

```text
Do not retrain Stage5 or promote field-v2 before Stage4 representation validation is resolved.
```

## Recommended clean rerun command

Run this in a persistent shell or tmux session. Do not run it from an IDE command that may be killed when the window/session changes.

Recommended tmux setup:

```bash
cd /data/LFT-W02_data/pengxu
tmux new -s stage4_rep5614_20260611
```

Inside tmux:

```bash
cd /data/LFT-W02_data/pengxu

PY=/data/LFT-W02_data/pengxu/.conda/envs/windy310/bin/python
OUT=centralized_v1_output/stage4_representation_soft_weight_5614_retry_20260611

$PY stage/centralized_v1/core/centralized_stage4_sensitivity.py \
  --stage2-summary centralized_v1_output/stage2_full_v2/stage2_multimodal_summary.json \
  --stage3-summary centralized_v1_output/stage3_full_v2_25w_payload_only/stage3_center_summary.json \
  --frame-times-file centralized_v1_output/stage4_full_tp26_thr11_preserve_25w_taildiag_20260602_173319/stage4_holdout_only_frame_times_5614.txt \
  --out-dir $OUT/tp26_rep_soft_weight_v1_metrics \
  --sample-count 0 \
  --sample-seed 20260527 \
  --param-grid "8,4,2,1" \
  --kernels gaussian \
  --confidence-mode representation_error_soft_weighted \
  --holdout-fraction 0.125 \
  --holdout-count 0 \
  --refine-iters 4 \
  --pinn-smoothness-weight 0.018 \
  --pinn-divergence-weight 0.010 \
  --diffusion-weight 0.22 \
  --low-conf-fill-weight 0.72 \
  --source-preserve 0.95 \
  --physics-constraint-mode pydda_3dvar_proxy \
  --observation-anchor-weight 0.10 \
  --speed-limit-mps 120.0 \
  --localization-policy diagnostic_adaptive_v3 \
  --localization-candidate-grid "8:4,10:5" \
  --vertical-risk-mode preserve_strong_layers \
  --vertical-localization-policy fixed \
  --vertical-gradient-preserve-weight 0.12 \
  --vertical-context-mismatch-damping 0.35 \
  --current-weight-boost 1.0 \
  --context-weight-scale 1.0 \
  --context-time-conf-power 2.6 \
  --role-conflict-mode current_priority_adaptive \
  --conflict-speed-threshold-mps 11.0 \
  --conflict-context-factor 0.25 \
  --progress-interval-seconds 60 \
  --num-workers 25
```

Notes:

```text
Use a clean retry root.
The old 20260610 partial root can be kept for audit, but should not be merged into the retry result.
Parent-shard mode should automatically merge shard outputs after all shard processes exit successfully.
```

## Monitoring command

From another shell:

```bash
cd /data/LFT-W02_data/pengxu

/data/LFT-W02_data/pengxu/.conda/envs/windy310/bin/python - <<'PY'
import json, time
from pathlib import Path

root = Path("centralized_v1_output/stage4_representation_soft_weight_5614_retry_20260611/tp26_rep_soft_weight_v1_metrics/shards")
items = []
for pf in sorted(root.glob("*_progress.json")):
    d = json.loads(pf.read_text())
    items.append(d)

if not items:
    print("no progress files yet")
else:
    done = sum(int(d.get("completed", 0)) for d in items)
    total = sum(int(d.get("total", 0)) for d in items)
    counts = {}
    for d in items:
        counts[str(d.get("status"))] = counts.get(str(d.get("status")), 0) + 1
    newest = max(float(d.get("updated_at", 0)) for d in items)
    print(f"progress: {done}/{total} = {done / total * 100:.2f}%")
    print("status:", counts)
    print("newest_update_age_sec:", int(time.time() - newest))
    print("slowest:", sorted((int(d.get('completed', 0)), d.get('total'), d.get('shard_id')) for d in items)[:5])
PY
```

Completion check:

```bash
cd /data/LFT-W02_data/pengxu

wc -l \
  centralized_v1_output/stage4_representation_soft_weight_5614_retry_20260611/tp26_rep_soft_weight_v1_metrics/stage4_localization_sensitivity.csv \
  centralized_v1_output/stage4_representation_soft_weight_5614_retry_20260611/tp26_rep_soft_weight_v1_metrics/stage4_point_departures.csv
```

Expected shape:

```text
stage4_localization_sensitivity.csv should be 5614 rows + header
stage4_point_departures.csv should be around 15054 rows + header if the holdout point set aligns with tp26 full holdout
```

## Pairwise command after successful 5614 rerun

Only run this after the top-level candidate CSVs exist.

```bash
cd /data/LFT-W02_data/pengxu

PY=/data/LFT-W02_data/pengxu/.conda/envs/windy310/bin/python
BASE=centralized_v1_output/stage4_full_tp26_thr11_preserve_25w_taildiag_20260602_173319
CAND=centralized_v1_output/stage4_representation_soft_weight_5614_retry_20260611/tp26_rep_soft_weight_v1_metrics
ANALYSIS=centralized_v1_output/stage4_representation_soft_weight_5614_retry_20260611/analysis/tp26_vs_rep_soft_weight_v1_full5614

$PY stage/centralized_v1/core/centralized_stage4_pairwise_frame_compare.py \
  --baseline-csv $BASE/stage4_localization_sensitivity.csv \
  --candidate-csv $CAND/stage4_localization_sensitivity.csv \
  --baseline-point-csv $BASE/stage4_point_departures.csv \
  --candidate-point-csv $CAND/stage4_point_departures.csv \
  --baseline-label tp26_thr11_preserve \
  --candidate-label tp26_rep_soft_weight_v1 \
  --out-dir $ANALYSIS \
  --out-prefix tp26_vs_rep_soft_weight_v1_full5614 \
  --top-n 50 \
  --promotion-tolerance 1e-9
```

Primary output to read:

```text
centralized_v1_output/stage4_representation_soft_weight_5614_retry_20260611/analysis/tp26_vs_rep_soft_weight_v1_full5614/tp26_vs_rep_soft_weight_v1_full5614_promotion_checklist.md
centralized_v1_output/stage4_representation_soft_weight_5614_retry_20260611/analysis/tp26_vs_rep_soft_weight_v1_full5614/tp26_vs_rep_soft_weight_v1_full5614.md
```

## Full-5614 promotion criteria

Require all of these before considering any default change:

```text
strict_holdout_no_leakage_all_true = PASS
motion_used_as_wind_all_false = PASS
weighted_rmse_no_worse = PASS
frame_p95_no_worse = PASS
frame_p99_no_worse = PASS
alt_12km_plus_vector_rmse_no_worse = PASS
light_wind_vector_rmse_mps_no_worse = PASS
light_wind_vector_mae_mps_no_worse = PASS
floor10_relative_error_mae_no_worse = PASS
light_moderate_relative_tail_no_new_failure = PASS
```

Interpretation rule:

```text
If full-5614 PASS with only tiny gain: keep as candidate/reliability layer, not automatic default.
If full-5614 FAIL: keep manuscript unchanged and document as failed scale-up.
If full-5614 PASS with meaningful tail reduction and no guardrail regression: then update manuscript cautiously.
```

## Stage5 next-step advice

Do not spend the next run budget retraining Stage5. The safer next action is Stage4 full-5614 representation validation.

If Stage5 must be continued later, use field-v2 replay results as constraints:

```text
Keep 12km+ residual scale off unless a new hard gate prevents 12km+ degradation.
Do not accept a candidate that improves weighted RMSE but worsens 12km+ RMSE.
Treat changed holdout points <= 7 as a diagnostic target, not a promotion criterion by itself.
```

A later Stage5 full-field experiment should start from:

```text
field_v2 rule family = alt12_off + conservative support-risk/non-light gates
base model = cap1p0_seed20260609_w512_l6
baseline = tp26_thr11_preserve
formal evaluation = strict 200-frame pairwise first, then larger holdout set
```

## Manuscript guidance

Current manuscript language can remain conservative:

```text
Do not claim tp26_rep_soft_weight_v1 is default.
Do not claim Stage5 improves full fields.
Do not claim full national-grid accuracy outside aircraft-holdout locations.
```

Potential update only after full-5614 representation run:

```text
If tp26_rep_soft_weight_v1 passes 5614-frame gate, add one sentence that representation-aware soft weighting scaled to the full holdout-evaluable set.
If it fails, add no new claim; optionally mention it as a failed scale-up in internal docs only.
```

The strongest paper claim remains:

```text
centralized_v1 provides an auditable, role-aware aircraft-holdout validation framework.
```

## Dirty worktree caution

Known intended code change:

```text
stage/centralized_v1/core/centralized_stage4_pairwise_frame_compare.py
```

There are unrelated dirty/untracked files in the workspace from earlier work. Do not revert unrelated files unless explicitly requested.

