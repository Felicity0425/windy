# CMA-RA Virtual Radial 3DVAR Proxy - 20260210041800

## Boundary

This output uses CMA-RA/CRA40 as an external reanalysis background, projects its gridded wind to virtual radial velocities, and combines those virtual radial constraints with the sparse Stage4 reconstructed wind prior plus aircraft wind anchors. It is not a standard Doppler-radar PyDDA retrieval because no real radar radial-velocity volume is available.

## Inputs

- Stage2 frame: `20260210041800`
- CMA time: `2026021000->2026021006` (`delta_hours=4.300`)
- CMA time method: `linear_qc`
- Stage2 npz: `/data/LFT-W02_data/pengxu/centralized_v1_output/stage2_full_v2/voxels/frame_20260210041800_multimodal.npz`
- CMA directory: `/data/LFT-W02_data/pengxu/cma`
- Stage4 sparse prior: `not supplied`
- Aircraft anchor mode: `stage4_train_wind`

## Virtual Radar Sites

| site | lat | lon | alt_m |
| --- | ---: | ---: | ---: |
| `stage2_roi` | 33.200000 | 104.000000 | 0.0 |

## Outputs

- NPZ: `/data/LFT-W02_data/pengxu/优化/stage4_cma_m1_light_demo_20260625/representative_cma_proxy/cma_ra_virtual_radial_3dvar_20260210041800.npz`
- sample CSV: `/data/LFT-W02_data/pengxu/优化/stage4_cma_m1_light_demo_20260625/representative_cma_proxy/cma_ra_virtual_radial_3dvar_20260210041800_sample.csv`

## Proxy Losses

| metric | value |
| --- | ---: |
| `loss_observation_fit_proxy` | 49.495529 |
| `loss_background_fit_proxy` | 0.077232 |
| `loss_stage4_sparse_prior_fit_proxy` | 0.000000 |
| `loss_virtual_radial_velocity_fit_proxy` | 0.045325 |
| `loss_smoothness_proxy` | 0.262972 |
| `loss_weak_horizontal_divergence_proxy` | 0.187943 |
| `loss_vertical_shear_proxy` | 2.124722 |
| `loss_boundary_background_proxy` | 0.004290 |
| `coverage_conf_positive_fraction` | 0.001192 |
| `iterations` | 6.000000 |
| `geometry_balance_mode` | 0.000000 |

## Method Notes

- Virtual radial velocity is the projection of CMA u/v/w onto the line-of-sight vector from a synthetic radar site to each Stage2 voxel.
- When `cma_time_method=linear`, the CMA field is linearly interpolated in time between adjacent 6-hour analyses: `F(t) = (1-alpha)*F(T0) + alpha*F(T1)`, then projected to virtual radial velocity at the Stage2/radar frame time.
- When `cma_time_method=linear_qc`, the same linear interpolation is used, and voxels with large 6-hour vector change are flagged through `cma_rapid_change_flag_3d` for later weak-background downweighting.
- When `geometry_balance_mode=los_weighted`, virtual-radial residuals are weighted by line-of-sight horizontal observability and range so that site geometry has less opportunity to dominate the proxy update.
- The class-3DVAR proxy blends virtual radial velocity fit, Stage4 sparse reconstruction-prior fit, aircraft observation fit, background fit, neighbor smoothness, weak horizontal divergence suppression, vertical shear regularization, boundary/background retention and speed clipping.
- Aircraft anchor records used: `25`; Stage4-like anchor hold-out excluded: `4`.
- CMA-RA is an external weak/background field. It can support training and comparison, but it must not replace strict aircraft hold-out labels.
- Real PyDDA would ingest radar radial-velocity volumes and radar geometry; this file only creates a proxy source until those observations exist.
