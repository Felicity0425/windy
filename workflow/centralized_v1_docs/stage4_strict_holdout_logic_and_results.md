# Stage4 Strict Hold-Out Logic And Results

## Role

Stage4 is the first centralized_v1 stage that reconstructs a 3D wind field.
Stage1 prepares clean sources, Stage2 organizes all in-domain observations, and
Stage3 packages the Ground Center payload. Stage4 then performs strict
hold-out evaluation:

```text
hold-out labels = selected current-window wind_records only
fusion input = non-holdout current wind_records + context_wind_records
motion_records / context_motion_records = coverage diagnostics only
```

The current two-frame baseline in `stage4_center_strict` is not a failure. It
is an early strict demo. `20260208124800` has 15 hold-out wind voxels and is a
normal demo frame. `20260211060600` has only one current wind voxel, so it is a
sparse-label pressure test, not an average-performance claim.

## Method

Strict leakage guard:

```text
1. choose hold-out labels from wind_records
2. remove exact hold-out records before fusion
3. allow only current_wind_train and context_wind as wind sources
4. fail immediately if train/hold-out overlap or motion enters fusion
```

Default active weight remains comparable with the baseline:

```text
active_weight = obs_conf * time_conf * target_voxel_localization
```

Optional diagnostic weighting can be enabled by CLI:

```text
--confidence-mode diagnostic_weighted
active_weight *= density_conf * quality_conf * speed_qc_conf * local_consistency_conf
```

Default mode is `diagnostic_only`, so new confidence/QC fields are recorded but
do not change the historical metric baseline.

Localization kernels:

```text
--localization-kernel gaussian
--localization-kernel gaspari_cohn
```

Gaussian uses:

```text
localization = exp(-0.5 * ((dx/sigma_xy)^2 + (dy/sigma_xy)^2 + (dz/sigma_z)^2))
```

Gaspari-Cohn uses compact-support fifth-order localization. In this mode,
`localization_sigma_xy` and `localization_sigma_z` are interpreted as the
halfwidth/c parameters for the horizontal and vertical normalized distances.

The PINN/diffusion-style layer remains a proxy gap-fill scaffold. It records
smoothness, weak horizontal divergence, vertical shear, and speed plausibility
diagnostics. It is not a trained PINN or diffusion model.

## Outputs

Baseline two-frame strict output remains preserved:

```text
/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_center_strict
```

Expanded 10-frame strict output is written separately:

```text
/data/LFT-W02_data/pengxu/centralized_v1_output/stage3_center_expanded
/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_center_strict_expanded
```

Sensitivity output is metrics-only:

```text
/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_center_strict_expanded/sensitivity/stage4_localization_sensitivity.csv
/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_center_strict_expanded/sensitivity/stage4_localization_sensitivity.md
```

The sensitivity grid is:

```text
kernels = gaussian, gaspari_cohn
(radius_xy, sigma_xy, radius_z, sigma_z) =
  (8, 4, 2, 1)
  (12, 6, 2, 1)
  (16, 8, 3, 1.5)
```

## Expanded Result Snapshot

The expanded strict run uses the existing 10 regenerated Stage2 frames:

```text
20260131073000
20260206174200
20260207022400
20260208124800
20260210060000
20260211060600
20260213053600
20260215063000
20260215063600
20260215100600
```

Verified checks:

```text
Stage3 expanded rows = 10
Stage4 expanded rows = 10
Sensitivity rows = 60
strict_holdout_no_leakage = true for all rows
motion_used_as_wind = false for all rows
mask_conf_positive_mismatch_voxels = 0 for all Stage4 expanded rows
NaN values in sensitivity table = false
```

Default Gaussian expanded summary:

| time | hold-out | RMSE vector | MAE vector | effective voxels | low-conf fill | note |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| `20260131073000` | 13 | 6.777242 | 5.990721 | 337139 | 110647 | normal demo |
| `20260206174200` | 11 | 20.248046 | 14.126716 | 316888 | 117202 | high-error frame; needs diagnosis |
| `20260207022400` | 13 | 15.947578 | 8.894733 | 343325 | 119785 | high-error frame; needs diagnosis |
| `20260208124800` | 15 | 6.468737 | 5.422913 | 417438 | 141240 | baseline normal demo |
| `20260210060000` | 1 | 5.693201 | 5.693201 | 347436 | 132755 | sparse-label pressure test |
| `20260211060600` | 1 | 3.390634 | 3.390634 | 339248 | 121387 | sparse-label pressure test |
| `20260213053600` | 1 | 6.910204 | 6.910204 | 263035 | 108743 | sparse-label pressure test |
| `20260215063000` | 3 | 5.925957 | 4.098377 | 214732 | 78990 | sparse labels |
| `20260215063600` | 3 | 5.779233 | 3.910550 | 211646 | 77665 | sparse labels |
| `20260215100600` | 4 | 9.918892 | 9.241952 | 202879 | 73158 | sparse labels |

Interpretation:

- Effective domain fractions around a few percent are expected in the strict
  demo because support is defined by `recon_mask_3d > 0`, not the full China
  grid.
- Low-confidence fill is separated from observation-supported voxels. A
  block-like footprint means finite-radius localization plus neighbor
  propagation, not proof of a physically solid wind block.
- The high-error frames should guide parameter sensitivity and QC diagnostics;
  they are exactly why full Stage2/3/4 should wait.

## Commands

Stage3 expanded:

```bash
/data/LFT-W02_data/pengxu/.conda/envs/windy310/bin/python \
  stage/centralized_v1/core/centralized_stage3_center.py \
  --frame-times 20260131073000,20260206174200,20260207022400,20260208124800,20260210060000,20260211060600,20260213053600,20260215063000,20260215063600,20260215100600 \
  --out-dir /data/LFT-W02_data/pengxu/centralized_v1_output/stage3_center_expanded \
  --num-workers 8
```

Stage4 expanded default:

```bash
/data/LFT-W02_data/pengxu/.conda/envs/windy310/bin/python \
  stage/centralized_v1/core/centralized_stage4_ground_recon.py \
  --frame-times 20260131073000,20260206174200,20260207022400,20260208124800,20260210060000,20260211060600,20260213053600,20260215063000,20260215063600,20260215100600 \
  --stage3-summary /data/LFT-W02_data/pengxu/centralized_v1_output/stage3_center_expanded/stage3_center_summary.json \
  --out-dir /data/LFT-W02_data/pengxu/centralized_v1_output/stage4_center_strict_expanded \
  --localization-kernel gaussian \
  --confidence-mode diagnostic_only
```

Sensitivity table:

```bash
/data/LFT-W02_data/pengxu/.conda/envs/windy310/bin/python \
  stage/centralized_v1/core/centralized_stage4_sensitivity.py \
  --stage3-summary /data/LFT-W02_data/pengxu/centralized_v1_output/stage3_center_expanded/stage3_center_summary.json \
  --out-dir /data/LFT-W02_data/pengxu/centralized_v1_output/stage4_center_strict_expanded/sensitivity
```

## Full-Run Gate

Do not run full Stage2/Stage3/Stage4 yet. Full runs should wait until:

```text
1. expanded 2-10 frame metrics are reviewed
2. leakage checks remain mandatory and all pass
3. Gaussian vs Gaspari-Cohn sensitivity is interpreted
4. high-error frames have a diagnosis path
5. confidence/QC weighting policy is explicitly chosen
```

## References

- ECMWF ERA5 4D-Var 12h assimilation window:
  https://confluence.ecmwf.int/display/CKB/ERA5%3A%2Bdata%2Bdocumentation
- ECMWF 4D-Var observation accuracy and representativeness:
  https://confluence.ecmwf.int/pages/viewpage.action?pageId=315559375
- DART Gaspari-Cohn localization:
  https://docs.dart.ucar.edu/en/latest/assimilation_code/modules/assimilation/cov_cutoff_mod.html
- PyDDA 3DVAR wind retrieval constraints:
  https://openresearchsoftware.metajnl.com/articles/264
- WMO aircraft-based observations / AMDAR:
  https://wmo.int/aircraft-based-observations-programme
- WMO aircraft observations QC/process context:
  https://wmo.int/activities/aircraft-based-observations/aircraft-based-observations
- EMADDC aircraft surveillance wind QC:
  https://amt.copernicus.org/articles/18/3341/2025/
