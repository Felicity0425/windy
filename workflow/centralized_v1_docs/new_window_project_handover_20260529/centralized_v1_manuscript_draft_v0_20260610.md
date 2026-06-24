# Aircraft-holdout validation of centralized three-dimensional wind-field reconstruction from sparse aircraft observations

Draft version: 2026-06-10

Detected writing axes: `paper_type=algorithmic/methods`, `section=full manuscript draft`, `language=zh-to-en`, `journal=generic Nature-leaning`.

This is a first manuscript draft built from the project handover documents in:

```text
workflow/centralized_v1_docs/new_window_project_handover_20260529/
```

The draft is intentionally conservative. Claims are restricted to results documented in the project reports. References are listed as citation placeholders to verify before submission.

## One-sentence argument

In sparse, aircraft-observed atmospheric wind reconstruction, we show that a centralized, role-aware reconstruction pipeline can produce auditable three-dimensional wind fields using aircraft wind observations as the only strict validation truth, supported by 7,395 reconstructed frames, 5,614 aircraft-holdout-evaluable frames, and 200-frame controlled comparisons, with accuracy claims restricted to aircraft-holdout locations rather than the full national grid.

## Terminology ledger

| Canonical term | First-use definition | Variants to avoid | Decision |
| --- | --- | --- | --- |
| centralized_v1 | The full centralized wind-field reconstruction pipeline used in this work | centralized V1, central v1 | Use `centralized_v1` in code context and "the centralized pipeline" in prose. |
| aircraft wind observations | AMDAR/TURB-derived wind records with `u_wind` and `v_wind` | aircraft motion, location wind | Use only for wind-bearing records. |
| motion records | Aircraft ground-motion vectors derived from heading and ground speed | motion wind, optical flow wind | Never call these wind observations. |
| strict aircraft holdout | Evaluation protocol in which selected current aircraft wind records are removed before reconstruction and used only as truth | holdout, strict truth | Define once, then use "strict holdout". |
| `tp26_thr11_preserve` | Current default Stage4 candidate with diagnostic adaptive localization, stronger context-time decay, conflict threshold 11 m/s, and vertical-structure preservation | tp26, TimePower26 | Use full code name at first mention. |
| `baseline_aircraft` | Initial aircraft-only wide-kernel baseline | baseline | Use full term when comparison matters. |
| `adaptive_v3` | Diagnostic weighted, non-leaking adaptive localization candidate | adaptive, v3 | Use `adaptive_v3`. |
| weighted RMSE | Holdout-point-weighted vector root mean squared error | weighted error | State units in m/s. |
| no-holdout frame | A reconstructed frame without current aircraft wind records for strict truth scoring | zero-error frame | Never include in official RMSE/MAE. |
| display-filled field | Low-confidence visualization/product layer filled outside official `recon_mask` by weak background | official field | Not used for official accuracy. |
| residual PINN | Stage5 gated residual neural correction on top of Stage4 | full-field PINN | Use only for the point-level and field-smoke candidate, not as default. |

## Title candidates

1. **Aircraft-holdout validation of centralized three-dimensional wind-field reconstruction from sparse aircraft observations**
2. Centralized reconstruction of three-dimensional wind fields with strict aircraft-observation holdout
3. Role-aware aircraft wind assimilation for auditable three-dimensional wind-field reconstruction
4. Strict aircraft-holdout evaluation exposes reliability limits in sparse three-dimensional wind reconstruction

Recommended title for this draft: candidate 1. It is searchable, names the validation principle, and does not overclaim operational wind-shear capability.

## Abstract

Three-dimensional wind fields are difficult to reconstruct at high temporal resolution when direct wind measurements are sparse, irregularly sampled and mixed with non-wind aircraft state records. Aircraft reports provide valuable wind observations, but practical reconstruction systems must distinguish true wind measurements from aircraft motion, radar reflectivity context and large-scale numerical backgrounds. Here we introduce `centralized_v1`, a centralized reconstruction pipeline that organizes aircraft wind observations, aircraft trajectories, motion diagnostics and radar/cloud context into a common three-dimensional grid, then reconstructs horizontal wind components under a strict aircraft-holdout validation protocol. Current aircraft wind records are the only official truth source: selected holdout records are removed before fusion, whereas aircraft motion, radar imagery and numerical backgrounds are used only as diagnostics, context or weak priors. Across a full Stage4 run of 7,395 frames, 5,614 frames contained aircraft holdout truth and 1,781 frames were retained as unverified reconstructions. In a fixed 200-frame, 530-point strict-holdout comparison, the current default candidate `tp26_thr11_preserve` reduced holdout-weighted vector RMSE from 18.918 m/s for the initial aircraft-only baseline to 14.769 m/s, while preserving explicit leakage and motion-as-wind safeguards. Error analysis showed that the remaining RMSE was dominated by a small tail of high-altitude, sparse-support and role-conflict cases, rather than by uniform degradation across all points. A gated Stage5 residual PINN produced a nonzero point-level improvement under locked test guardrails, but the gain was small and is treated only as a field-smoke candidate. These results support centralized, auditable reconstruction as a research-grade wind-field product, while limiting validated accuracy claims to aircraft-holdout locations and separating product footprint from verified skill.

## Introduction

Wind-field information is central to aviation meteorology, numerical weather prediction and weather-aware flight operations. The operational need is not only to know that wind exists at a point, but to reconstruct a spatially coherent field from measurements that are sparse, asynchronous and unevenly distributed across altitude and geography. Aircraft observations are especially valuable because they sample wind along active flight routes, including levels that are poorly covered by fixed stations. Yet these observations arrive with a difficult engineering boundary: true aircraft wind reports, aircraft position records, ground-motion vectors, radar reflectivity images and numerical background fields do not have the same physical meaning.

The main bottleneck is that many available data streams are informative but cannot be used as truth. Aircraft wind reports can provide wind speed and direction, which can be converted into horizontal wind components. Aircraft location records provide position, heading and ground speed, but these variables describe aircraft kinematics rather than atmospheric wind unless air-vector information is also available. Radar mosaic images provide cloud or reflectivity context, but the images used here are not Doppler radial velocity. Reanalysis or forecast fields can provide large-scale structure, but their temporal and spatial resolution does not make them equivalent to current aircraft observations. A reconstruction pipeline that mixes these roles without explicit safeguards can obtain plausible-looking fields while contaminating its validation.

Previous approaches to wind-field estimation have used aircraft-derived observations, covariance localization, variational constraints, kriging or Gaussian-process-style interpolation, and numerical model backgrounds. These ideas provide useful building blocks, but they do not by themselves define a leakage-resistant validation protocol for a national-grid, aircraft-centered reconstruction product. In this setting, a method must answer three questions at the same time: which records are allowed to influence the reconstruction, which records can serve as independent truth, and where the reconstructed field is only a low-confidence product footprint rather than a verified accuracy claim.

We address this problem with `centralized_v1`, a staged pipeline for centralized, role-aware wind-field reconstruction. Stage1 standardizes aircraft wind, aircraft location and radar-index inputs. Stage2 maps sparse observations and radar context to a common three-dimensional grid. Stage3 packages the data at a logical Ground Center while preserving observation roles. Stage4 reconstructs horizontal wind components and evaluates them only against current aircraft wind records removed before fusion. The central contribution is not a claim of operational low-level wind-shear warning, but an auditable reconstruction and validation framework that separates wind truth, contextual support, weak background, product footprint and reliability diagnostics.

## Results

### A centralized pipeline separated wind truth from non-wind context

The pipeline organized heterogeneous inputs into explicit observation roles before reconstruction. Stage1 produced cleaned aircraft wind records and aircraft location records. The current project state reported 431,189 rows in `clean_wind.parquet` and 19,162,638 rows in `clean_loc.parquet`. The wind table contains `u_wind` and `v_wind` components derived from wind direction and wind speed. The location table contains `u_motion` and `v_motion`, which are aircraft ground-motion components and are not treated as atmospheric wind.

Stage2 mapped observations into a 31 x 525 x 775 grid covering 0-15 km altitude with 500 m vertical spacing. For each radar-frame time, observations were split into a current window and a context window. Current aircraft wind records became candidates for strict holdout truth. Context aircraft wind records were allowed to contribute background support with time decay. Location and motion records were retained for trajectory, support and diagnostic features. Radar PNG intensity was stored as two-dimensional cloud or reflectivity context, not as wind speed, wind direction or Doppler velocity.

Stage3 packaged these roles into a Ground Center representation. The Ground Center is a logical receiver and analysis point rather than a physical station. This design avoided distance-based filtering at the intake stage and left spatial localization to Stage4, where each target voxel can be weighted relative to nearby wind observations. The resulting payload preserved label candidates, context wind observations, trajectory observations, motion diagnostics and confidence features as separate groups.

### Strict aircraft holdout defined the official skill metric

Stage4 was the first stage to produce a three-dimensional wind reconstruction. Its official evaluation was defined by a strict aircraft-holdout protocol. For each evaluated frame, selected current aircraft wind records were removed from the fusion input. The reconstruction then used non-holdout current wind records and context wind records. The removed current aircraft wind records were sampled only after reconstruction to compute `u` error, `v` error and vector error.

This protocol enforced two audit flags throughout the candidate comparisons: `strict_holdout_no_leakage=True` and `motion_used_as_wind=False`. These flags are essential because the reconstructed field could otherwise be improved artificially by allowing held-out wind records to enter fusion, or by treating aircraft ground motion as wind. Numerical background fields, including CMA/GFS/ERA-style products, were treated as weak background or conditional input only. They were not used as official truth.

A full Stage4 TimePower/adaptive run reconstructed 7,395 frames. Of these, 5,614 frames contained current aircraft wind records and could be strictly evaluated. The remaining 1,781 frames had no current aircraft wind holdout truth. These no-holdout frames were retained as business or product reconstructions with coverage, confidence and risk diagnostics, but they were excluded from official RMSE/MAE. In the full run, mixing no-holdout frames into the mean as zero-error frames would have produced an optimistic all-frame RMSE of 6.60 m/s, whereas the corrected holdout-only RMSE was 8.70 m/s. This separation is a core part of the validation design.

### Adaptive Stage4 reconstruction improved the 200-frame strict-holdout baseline

We evaluated the main Stage4 method evolution on a fixed 200-frame strict-holdout set containing 530 holdout points. The initial aircraft-only baseline used a wider Gaussian localization, diagnostic-only confidence, proxy physical refinement and no role-conflict adaptation. This baseline achieved a frame RMSE of 11.690 m/s and a holdout-weighted vector RMSE of 18.918 m/s.

The `adaptive_v3` candidate introduced diagnostic weighting, non-leaking adaptive localization and current-priority role conflict handling. It reduced the holdout-weighted vector RMSE to 14.933 m/s and the frame RMSE to 8.457 m/s. The current default candidate, `tp26_thr11_preserve`, increased context time decay, used a conflict threshold of 11 m/s and enabled strong-layer preservation. It further reduced the holdout-weighted vector RMSE to 14.769 m/s and the frame RMSE to 8.224 m/s. Relative to the aircraft-only baseline, this corresponds to a 21.9% reduction in holdout-weighted vector RMSE and a 29.6% reduction in frame RMSE on the fixed 200-frame comparison.

The improvement was not uniform across all regimes. The adaptive stages gave their largest benefit by reducing failures in moderate-to-high baseline error bands and by limiting stale context influence. However, isolated cases remained where the wider aircraft-only baseline was closer to the holdout point. This occurred when the held-out point depended on broader context support that the narrower adaptive kernel suppressed. The comparison therefore supports the adaptive pipeline as the current default, but not as a universal solution for every local support geometry.

### Remaining error was dominated by high-altitude and sparse-support tails

The current default did not fail uniformly. In the 200-frame, 530-point diagnostic set, 21 holdout points had vector error at least 30 m/s, and these points dominated the squared-error budget. The documented tail analysis showed that the 12 km+ altitude group accounted for a large share of squared error, and that high-error points were enriched in role gaps, large nearest-support distances and vertical-structure risk.

This finding changed the optimization target. Further improvements could not be judged only by mean RMSE. Candidate branches were required to pass formal guardrails on holdout-weighted RMSE, frame P95, frame P99, 12 km+ vector RMSE, light-wind RMSE/MAE, floor10 relative error and new catastrophic failures in light or moderate winds. These guardrails rejected several superficially plausible modifications. A support-role-height-aware localization branch worsened holdout-weighted RMSE from 14.769 to 20.149 m/s and increased 12 km+ RMSE. A sparse temporal CMA/NWP branch improved some P95/P99 tail values but worsened weighted RMSE, 12 km+ error, light-wind error and floor10 relative error. A guarded vertical dynamic branch reduced the risk of catastrophic amplification but still failed the formal gate.

The representation-error analysis was more promising as a diagnostic layer. A truth-free representation-error report separated low-risk and high-risk holdout regimes without deleting any official evaluation points. A conservative rule captured all 21 high-error points and reduced unflagged RMSE to 5.520 m/s. A soft representation-weighted candidate, `tp26_rep_soft_weight_v1`, passed the 200-frame formal guardrail and reduced weighted RMSE from 14.769 to 14.755 m/s. The improvement was too small to justify replacing the default without larger validation, but it supports representation-aware reliability as a useful next step.

### Display-filled fields improved product readability without changing official accuracy

The official reconstruction is evidence-driven and sparse. In representative full-domain views, most of the national grid lies outside `recon_mask` and therefore carries no official wind claim. Display-filled output was introduced to make product visualization more interpretable. In this layer, official `recon_u`, `recon_v`, confidence and mask values are preserved where the model claims reconstruction, while low-confidence or no-claim regions can be filled by weak background for visualization.

This design separates two questions that are often conflated. The product footprint asks where a user can inspect a continuous-looking field. The validated accuracy footprint asks where strict aircraft holdout supports an RMSE/MAE statement. Display-filled fields answer the first question but do not enter point evaluation. The diagnostics explicitly mark `display_fill_is_official_accuracy=False`. This distinction is important because nationwide visualization does not imply that every national-grid voxel has aircraft-holdout-verified accuracy.

### A gated residual PINN showed a small point-level signal but remained a candidate

Stage5 explored whether a residual neural correction could improve Stage4 without replacing it. The working formula was:

```text
F_stage5 = F_tp26 + gate * clipped_residual_delta
```

Initial point-level residual models showed that all-point residual correction was unsafe. It could lower aggregate RMSE while worsening P95, light-wind error or floor10 relative error on locked test splits. Regime audit showed that residual correction helped more in high vertical-gap or strong-tail regimes and harmed more in light-wind or floor10-sensitive regimes. The correction therefore had to be gated by truth-free features rather than applied globally.

The full-data Stage5 sweep used a larger point-level dataset from the full `tp26_thr11_preserve` departure table: 5,614 frames and 15,054 aircraft holdout points split by frame into 3,930 train frames, 842 validation frames and 842 test frames. GPU sweeps over residual caps and seeds identified one nonzero locked-test PASS candidate: `cap1p0_seed20260609_w512_l6` with the gate `vertical_gap_ge20_not_light` and scale 1.0. On the locked test split, this candidate enabled 33 of 1,893 points and reduced RMSE from 9.896785 to 9.892352 m/s, with no degradation in P95, P99, light-wind RMSE or floor10 relative MAE.

This result is deliberately interpreted as narrow. The residual PINN produced a safe point-level signal only under a conservative gate and with a very small effect size. It is ready for a controlled field-v1 smoke test, where non-gated grid cells must remain unchanged from Stage4. It is not ready to replace `tp26_thr11_preserve` and should not be made the default before full-field smoke and strict 200-frame pairwise validation.

## Methods

### Task formulation

The task was to reconstruct horizontal wind components on a three-dimensional grid from sparse aircraft wind observations and related context. The model output consisted of reconstructed `u` and `v` wind components, reconstruction confidence and a reconstruction mask. The official validation target was not a dense gridded truth field. It was a set of current aircraft wind observations removed before reconstruction and sampled afterward at their corresponding voxels.

The main boundary is that only wind-bearing aircraft records were eligible as official truth. Aircraft motion records, radar PNG intensity and numerical background fields were not treated as truth. This boundary was enforced at data organization, reconstruction and evaluation stages.

### Stage1 data standardization

Stage1 converted raw aircraft and radar-index inputs into stable tables and manifests. AMDAR/TURB wind observations were standardized into a wind table containing UTC time, cleaned latitude, longitude, altitude, wind direction, wind speed, `u_wind`, `v_wind`, flight identifiers, source labels and observation confidence. The wind direction convention followed meteorological usage, where wind direction indicates where the wind comes from. Thus:

```text
u_wind = -wind_speed * sin(wind_dir*pi/180)
v_wind = -wind_speed * cos(wind_dir*pi/180)
```

Aircraft location records were standardized separately. They contained UTC time, position, altitude, heading, ground speed and ground-motion components:

```text
u_motion = ground_speed_ms * sin(heading_deg*pi/180)
v_motion = ground_speed_ms * cos(heading_deg*pi/180)
```

These variables describe aircraft ground motion. They were retained for trajectory and support diagnostics but were not used as wind truth.

### Stage2 multimodal voxel organization

Stage2 organized each usable radar-frame time into a common grid. The grid covered latitude 12.2-54.2 degrees, longitude 73.0-135.0 degrees and altitude 0-15,000 m, with 500 m vertical spacing and a 31 x 525 x 775 shape. Each radar-frame time defined a current window and a context window. The current window was approximately the target time plus or minus five minutes. The context window extended to plus or minus 360 minutes, excluding the current window.

Current aircraft wind observations were mapped to `wind_records`. These records became candidates for strict holdout truth. Context aircraft wind observations were mapped to `context_wind_records` with time confidence decay. Location records and motion records were mapped to trajectory and motion diagnostics. Radar PNG images were read as grayscale intensity and downsampled to the Stage2 horizontal grid as `cloud_2d`.

Stage2 did not reconstruct wind. It created a role-preserving multimodal representation so that later stages could distinguish wind observations, contextual wind support, aircraft motion, trajectory density and radar/cloud context.

### Stage3 Ground Center packaging

Stage3 converted Stage2 frame data into a centralized Ground Center payload. The Ground Center was treated as a logical receiver and data-integration node, not as a physical station. Current aircraft agents were grouped by flight identifier, and each payload preserved observation roles: label candidates, context wind observations, trajectory observations, motion observations, context motion observations and confidence diagnostics.

This step made the centralized data contract explicit. Candidate truth records and non-truth diagnostics remained separate, which simplified the downstream leakage audit.

### Stage4 reconstruction

Stage4 reconstructed wind by accumulating non-holdout wind observations around target voxels. For each evaluated frame, selected current `wind_records` were removed before reconstruction. The allowed wind inputs were:

```text
train_current_wind = wind_records - holdout_wind
context_wind_records
```

The disallowed wind inputs were:

```text
holdout wind_records
motion_records
context_motion_records
CMA/GFS/ERA as truth
```

Observation influence was controlled by time confidence, observation confidence, diagnostic factors and spatial localization. The baseline used a fixed wide Gaussian kernel. Adaptive candidates selected between narrower kernels using only non-holdout diagnostics, including current support, context support, context time confidence, local consistency, role gap and observation-error proxies. Holdout RMSE, holdout MAE and holdout residuals were not permitted as adaptive-selection inputs.

The `tp26_thr11_preserve` candidate combined diagnostic weighting, non-leaking adaptive localization, current-priority role conflict handling, stronger context-time decay and vertical-structure preservation. The vertical-preservation mode reduced cross-layer smoothing in strong-wind or vertical-mismatch regions and applied a weak pullback to high-confidence anchors. This was intended to reduce vertical oversmoothing without claiming 30 m wind-shear prediction.

### Stage4 evaluation

For each holdout point, the reconstructed `u` and `v` components were sampled at the corresponding voxel and compared with the removed aircraft wind observation:

```text
u_error = pred_u - gt_u
v_error = pred_v - gt_v
vector_error = sqrt(u_error^2 + v_error^2)
```

Frame RMSE/MAE, holdout-point-weighted RMSE/MAE, median, P90, P95, P99, maximum error, altitude bins, wind-speed bins, single-holdout pressure-test subsets and multi-holdout supported subsets were reported. No-holdout frames were excluded from official RMSE/MAE but retained for product diagnostics.

Formal candidate promotion required strict no-leakage and no-motion-as-wind flags. It also required no degradation in weighted RMSE, P95, P99, 12 km+ vector RMSE, 5-15 m/s light-wind RMSE/MAE and floor10 relative MAE. Any new light or moderate wind point with relative error ratio above 2 and delta vector error above 5 m/s was treated as a direct failure.

### Stage5 residual PINN

Stage5 treated neural correction as a residual layer on top of Stage4, not as a replacement. Point-level training samples were built from Stage4 point departures. The input features excluded ground-truth wind, vector error, component error, review flags that depend on truth, and point-neighbor error quantities. The target was:

```text
target_delta_u = gt_u - pred_u_tp26
target_delta_v = gt_v - pred_v_tp26
```

Training used frame-based splits to avoid placing points from the same frame in both training and evaluation. Residual MLP candidates produced clipped `delta_u` and `delta_v` outputs. Gate selection was performed on validation data using truth-free rules and then locked for test evaluation. The selected candidate for the next field-smoke step used a narrow vertical-gap gate and applied residual correction only where the gate fired.

## Discussion

This work shows that the most important design choice in sparse wind-field reconstruction may be the validation contract rather than the interpolation kernel alone. A plausible-looking wind field can be produced by mixing aircraft wind, aircraft motion, radar context and numerical background, but such a field is hard to trust unless each data source has a fixed role. By keeping aircraft wind observations as the only strict truth source and treating other inputs as context or weak priors, `centralized_v1` makes its accuracy claims auditable.

The Stage4 results suggest that diagnostic weighting and adaptive localization provide a clear improvement over the initial aircraft-only baseline. The improvement is meaningful on the fixed 200-frame comparison, where weighted RMSE fell from 18.918 to 14.769 m/s. However, the remaining error structure indicates that this is not simply a smooth interpolation problem. A small number of high-error points dominate the squared-error budget, and these points are associated with high altitude, sparse support, role conflict and vertical-structure mismatch. This explains why several intuitive modifications failed: they improved one regime while contaminating another.

The representation-error and reliability analyses are therefore central to the next stage. A 500 m, six-minute grid cell is not identical to an instantaneous aircraft point observation. The departure between them includes measurement error, representation error, support geometry and unresolved local variability. Treating all departures as pure observation error would misstate the problem. Conversely, deleting difficult points would overstate model skill. The current solution is to retain all official holdout points while reporting reliability, tail-risk and no-claim diagnostics separately.

The Stage5 residual PINN results are promising but intentionally limited. A global residual correction is unsafe because it can reduce RMSE while worsening light-wind or floor10-sensitive regimes. The only locked-test PASS candidate used a narrow gate and affected a small fraction of points. This supports the idea that learned residuals may help in selected vertical-gap regimes, but it does not support replacing the Stage4 reconstruction. The appropriate next step is a field-smoke test that verifies unchanged non-gated cells, bounded residuals and no degradation under strict pairwise evaluation.

The present system should not be interpreted as an operational low-level wind-shear warning product. Stage4 uses a 500 m vertical grid, whereas aviation wind-shear thresholds can involve much smaller vertical scales. A 6 m/s point reconstruction error and a 6 m/s wind difference across 30 m are not equivalent quantities. The current contribution is a research-grade, audit-ready reconstruction and validation framework. A future operational risk head would need separate vertical-jump, strong-layer and low-level shear metrics, supported by appropriate observations and validation protocols.

## Limitations

The official accuracy footprint is limited to current aircraft wind holdout locations. The pipeline can generate national-grid products and display-filled fields, but areas without aircraft holdout truth cannot be assigned validated RMSE/MAE. Those areas should be reported through coverage, confidence, background-source and reliability diagnostics.

The aircraft wind observations themselves carry measurement and quality-control uncertainty, but the dominant Stage4 error is larger than published aircraft wind observation-error priors. This draft therefore treats de Haan-style and EMADDC-style values as observation-error references, not as quantities to subtract from reconstruction RMSE.

The current radar input is a PNG intensity or mosaic context. It is not Doppler radial velocity. The pipeline therefore does not claim radar wind retrieval in the PyDDA or dual-Doppler sense.

The current residual PINN is point-level and gate-selected. It is not yet a full field-collocation physics-informed reconstruction. A full Stage5 field candidate must pass smoke tests and strict 200-frame pairwise validation before it can be discussed as more than a candidate.

## Conclusion

We present a centralized wind-field reconstruction pipeline that separates aircraft wind truth from non-wind context and evaluates reconstructed three-dimensional horizontal wind fields under a strict aircraft-holdout protocol. The current default Stage4 candidate substantially improves over the initial aircraft-only baseline on a fixed 200-frame strict-holdout benchmark, but the remaining error is concentrated in identifiable high-risk regimes. Reliability, representation-error and gated residual-learning analyses provide a path toward safer incremental improvement. The current system supports research-grade, auditable wind-field reconstruction and product-footprint visualization, while restricting validated skill claims to aircraft-holdout locations.

## Figure plan

Figure 1. Pipeline overview. Stage1 standardization, Stage2 voxel organization, Stage3 Ground Center packaging, Stage4 strict holdout reconstruction, Stage5 gated residual candidate.

Figure 2. Data-role schematic. Separate aircraft wind records, aircraft motion records, radar/cloud context and numerical background. Highlight which streams can be truth and which cannot.

Figure 3. Stage4 method evolution. Compare `baseline_aircraft`, `adaptive_v3` and `tp26_thr11_preserve` on 200-frame strict holdout: weighted RMSE, frame RMSE, P95 and P99.

Figure 4. Representative reconstruction frames. Show one low-error frame, one adaptive-improvement frame, one baseline-win frame and one extreme tail frame, with `recon_mask` and diagnostics.

Figure 5. Tail-risk and reliability. Show high-error point concentration by altitude, support distance, role gap and representation-risk score.

Figure 6. Stage5 residual PINN gate. Show point-level before/after metrics for the selected narrow gate and a schematic of field-smoke constraints.

## References to verify before submission

These are citation placeholders extracted from the project documents. Verify bibliographic details, journal style and relevance before submission.

1. WMO Aircraft-Based Observations Programme. Aircraft-based observations as meteorological data sources.
2. de Haan, S. and Stoffelen, A. Characterization of high-resolution aircraft-derived wind and temperature observations from Mode-S. Atmospheric Measurement Techniques, 2016.
3. EMADDC aircraft weather observations and quality control. Atmospheric Measurement Techniques, 2025.
4. Gaspari, G. and Cohn, S. E. Construction of correlation functions in two and three dimensions. Quarterly Journal of the Royal Meteorological Society, 1999.
5. DART covariance localization documentation.
6. Desroziers et al. Diagnostics of observation, background and analysis-error statistics in observation space, 2005.
7. Janjic et al. On the representation error in data assimilation, 2018.
8. PyDDA documentation and Journal of Open Research Software paper.
9. Perona, P. and Malik, J. Scale-space and edge detection using anisotropic diffusion, 1990.
10. Raissi, M., Perdikaris, P. and Karniadakis, G. E. Physics-informed neural networks, 2019.
11. Marinescu et al. Aircraft-derived wind reconstruction with Gaussian-process or kriging-style methods, 2022. [Verify exact title and venue.]
12. Hunt, Kostelich and Szunyogh. Efficient data assimilation for spatiotemporal chaos: LETKF, 2007.

## Assumptions or missing inputs

1. Target journal is not specified. This draft uses a generic Nature-leaning structure. A Nature Communications version would need a 150-word abstract and a roughly 5,000-word total budget including Methods.
2. Exact author list, affiliations and contribution statements are missing.
3. Figure files and final figure numbering are not yet assigned.
4. The draft assumes the current default remains `tp26_thr11_preserve` and Stage5 remains a candidate only.
5. Reference details need verification against the papers actually read.
6. Statistical significance tests are not included because the project documents mainly report deterministic benchmark metrics, not repeated statistical tests.
7. Data/code availability statements are not drafted because release scope is not specified.

## Claim-evidence map

| Claim | Evidence | Status |
| --- | --- | --- |
| The pipeline separates wind truth from aircraft motion and radar context. | Stage1-Stage4 process documents and strict validation rules. | supported |
| Official truth is current aircraft wind strict holdout only. | Repeated validation rules in handover, Stage4 and README documents. | supported |
| Full Stage4 run has 7,395 frames, with 5,614 holdout-evaluable and 1,781 no-holdout frames. | Full project handover and TimePower15 handover. | supported |
| No-holdout frames must not enter official RMSE/MAE. | Full project handover and reporting standards. | supported |
| `tp26_thr11_preserve` improves over `baseline_aircraft` on the 200-frame comparison. | README and Stage4 comparison tables: weighted RMSE 18.918 to 14.769 m/s. | supported |
| Tail error is concentrated in high-altitude, sparse-support and role-conflict regimes. | Tail-risk and error-source decomposition documents. | supported |
| Representation soft weighting passed 200-frame guardrail but was too small to promote. | Stage4 next-window plan: 14.769036 to 14.755381 m/s. | supported |
| Stage5 residual PINN is a narrow gated candidate, not a replacement. | Stage5 weekly report and next-window field-smoke handover. | supported |
| The system is not an operational 30 m wind-shear warning product. | Stage4 and TimePower15 boundary documents. | supported |
| The approach generalizes to operational deployment. | Not demonstrated by current documents. | needs evidence |

## Section outline

1. Introduction: field need, data-role bottleneck, gap in auditable validation, present centralized pipeline.
2. Results: data-role separation, strict holdout protocol, Stage4 performance, tail-risk analysis, display-filled product semantics, Stage5 residual candidate.
3. Methods: Stage1 to Stage5 pipeline, formulas, evaluation, guardrails.
4. Discussion: validation contract, remaining tail errors, representation error, cautious Stage5 interpretation.
5. Limitations and conclusion: verified footprint, radar/NWP boundaries, non-operational wind-shear scope.

## Why this structure

1. The manuscript is framed as an algorithmic/methods paper, so the draft separates system definition, design rationale, evaluation and failure modes.
2. The strongest defensible contribution is the strict aircraft-holdout validation framework plus a role-aware reconstruction pipeline, not a claim of operational wind-shear prediction.
3. The Results section leads with validation integrity before performance numbers because the project would be vulnerable if truth definitions were unclear.
4. Stage5 is included as a candidate result, but the draft keeps it bounded because the documented effect size is small and field validation is not complete.

## 中文结构说明

这版初稿把论文定位成"方法/系统论文"，不是业务预警论文。主线不是说模型已经可以做运行级风切变预警，而是说你建立了一个能把飞机风、飞机运动、雷达背景、数值背景严格分角色处理的三维风场重构系统，并且用 aircraft strict holdout 做可信验证。

引言没有直接堆所有技术细节，而是先讲清楚核心矛盾：很多数据源有用，但只有 current aircraft wind 可以做正式 truth。这样后面的 Stage1-5 才有逻辑基础。

结果部分按证据强度排序：先证明数据角色和验证协议，再给 Stage4 性能，再讲 tail-risk 和失败分支，最后讲 Stage5 residual PINN 只是候选。这样可以避免审稿人认为你在用 PINN 或 CMA 替代真实飞机观测。

下一版最应该补的是图、引用和目标期刊格式。如果目标是 Nature Communications，需要重新压缩摘要到 150 words，并按 5,000-word article budget 重新分配 Introduction、Results、Discussion 和 Methods。
