# Stage2 Figure Explanation - 20260208124800

PNG:

```text
/data/LFT-W02_data/pengxu/centralized_v1_output/stage2_regenerated/slices/20260208124800_centralized_stage2_slices.png
```

Companion files:

```text
/data/LFT-W02_data/pengxu/centralized_v1_output/stage2_regenerated/slices/stage2_slice_explanation_20260208124800.md
/data/LFT-W02_data/pengxu/centralized_v1_output/stage2_regenerated/slices/stage2_slice_stats_20260208124800.csv
/data/LFT-W02_data/pengxu/centralized_v1_output/stage2_regenerated/slices/stage2_slice_points_20260208124800.csv
```

## What This Figure Is

This figure is a Stage2 observation-organization diagnostic. It is not a wind
field reconstruction result.

The data source is:

```text
clean_wind.parquet + clean_loc.parquet + radar_index.json + radar PNG mosaic
```

The gray background is read from the weather-radar mosaic PNG pointed to by
`radar_index.json.radar_path`, decoded as a grayscale intensity image, then
downsampled by `xy_downsample=4`.

Formula and reference beside this operation:

```text
radar_img = cv2.imdecode(file_bytes, cv2.IMREAD_GRAYSCALE)
cloud_2d = radar_img[::4, ::4]
horizontal cost ratio ~= 1/16
```

This is an image/grid preprocessing step. It keeps radar/cloud intensity aligned
with the Stage2 voxel grid; it is not a radar wind retrieval. References:
OpenCV image I/O/color conversion documentation (`https://docs.opencv.org/4.x/`)
and WeatherBench2 gridded data organization
(`https://weatherbench2.readthedocs.io/en/latest/data-guide.html`).

It shows how current wind labels, historical context wind, current trajectory
voxels, current motion voxels and radar/cloud intensity are arranged on the
shared Stage2 grid:

```text
grid_shape = 31 x 525 x 775
z altitude step = 500 m
radar/cloud layer = 525 x 775 after xy_downsample=4
rendered PNG size = 4216 x 1563 px
```

The PNG size is from matplotlib rendering:

```text
figsize = (6.2 * 4, 9.2) inch
dpi = 170
```

It is not the radar array resolution.

## Layout

- Top row: 4 automatically selected horizontal altitude slices.
- Bottom-left: y-z vertical slice near `x=387 +/-6`.
- Bottom-right: altitude profile showing count by z level.

For `20260208124800`, the selected z layers are:

| z | altitude | current wind | context wind | traj | motion |
| ---: | ---: | ---: | ---: | ---: | ---: |
| 27 | 13500 m | 12 | 107 | 0 | 0 |
| 29 | 14500 m | 7 | 119 | 0 | 0 |
| 25 | 12500 m | 5 | 121 | 28 | 26 |
| 23 | 11500 m | 5 | 115 | 112 | 104 |

The labels such as `traj voxels (112)`, `motion voxels (104)`,
`context wind (115)` and `wind vectors (5)` refer to the fourth horizontal
slice, z=23, altitude about 11500 m.

## Meaning Of The Four Counts

`traj voxels (112)` means:

```text
At z=23, 112 grid cells contain current-window trajectory density records.
```

The source is `loc_records`. Each record has `(z, y, x, density)`. The
`density` value is the number of trajectory points grouped into that voxel.
These records come from `clean_loc.parquet` fields `time_utc`, `lat_clean`,
`lon_clean` and `alt_meters`.

`motion voxels (104)` means:

```text
At z=23, 104 grid cells contain current-window aircraft motion component records.
```

The source is `motion_records`. Each record has `(z, y, x, u_motion, v_motion,
motion_count)`. `u_motion/v_motion` are calculated in Stage1 from
`heading_deg` and `ground_speed_ms` in `clean_loc.parquet`. They describe
aircraft motion components in the current window, not atmospheric wind labels.

`context wind (115)` means:

```text
At z=23, 115 grid cells contain historical context wind records.
```

The source is `context_wind_records`. These records come from target time
`+/-360 min`, excluding the current `+/-5 min` label window. They are context
observations for later Stage4 fusion, not ground-truth labels. They come from
`clean_wind.parquet` fields `u_wind/v_wind`, which are calculated from wind
direction and wind speed.

`wind vectors (5)` means:

```text
At z=23, 5 grid cells contain current-window wind label candidates.
```

The source is `wind_records`. The arrows use the `u/v` wind components. These
points are candidates for Stage4 strict hold-out evaluation. If one is selected
as ground truth, it must be removed from Stage4 fusion input before prediction.

## Colors, Markers And Transparency

### Gray Background

Source:

```text
cloud_2d / radar_img
```

Meaning:

```text
Brighter pixels indicate stronger radar echo intensity.
```

The radar/cloud layer shown in Stage2 is `525 x 775`, downsampled from the
original radar PNG by `xy_downsample=4`. The gray value is radar/cloud
intensity, not wind speed.

Boundary reference: true radar wind retrieval needs Doppler velocity geometry,
for example PyDDA/3DVAR or dual-Doppler variational retrieval, not just a
single radar mosaic PNG. See `https://openresearchsoftware.metajnl.com/articles/10.5334/jors.264`
and `workflow/wiki/source-dual-doppler-variational-wind-field.md`.

### Orange Arrows And Dots

Source:

```text
wind_records
```

Style:

```text
color = #ff7a00
quiver alpha = 0.85
quiver scale = 450
quiver width = 0.003
dot size = 22
dot edge = black
dot edge width = 0.25
```

Meaning:

Current `+/-5 min` wind label candidates. The arrow direction comes from
`u/v`. In the plot code the v component is negated for image coordinates, so
the arrow visually follows the image y-axis orientation. Units: `u/v` and wind
speed are in `m/s`.

### Purple/Magenta X Markers

Source:

```text
context_wind_records
```

Style in horizontal slices:

```text
cmap = magma
marker = x
alpha = 0.55
size = 8 + 28 * time_conf
color encodes wind speed (m/s)
```

Style in the vertical slice:

```text
color = #d936c9
marker = x
alpha = 0.45
size = 16
```

Meaning:

Historical context wind. Color in the horizontal slice follows wind speed, and
marker size follows `time_conf`: observations closer to the target time appear
larger.

Formula and reference beside this visual encoding:

```text
context_wind_speed = sqrt(u^2 + v^2)  # m/s
marker_size = 8 + 28 * time_conf
time_conf = 0.5 ** (abs(delta_time_minutes) / 180)
```

Finite time windows and decaying observation influence are consistent with
ECMWF ERA5/IFS 4D-Var organization:
`https://confluence.ecmwf.int/display/CKB/ERA5%3A%2Bdata%2Bdocumentation`.

### Blue Dots

Source:

```text
loc_records
```

Style:

```text
color = #2aa8ff
horizontal size = 4
horizontal alpha = 0.22
vertical size = 5
vertical alpha = 0.20
```

Meaning:

Current-window trajectory density voxels. These show where aircraft trajectories
exist in the current window.

### Green Dots

Source:

```text
motion_records
```

Style:

```text
color = #20b25f
size = 6
alpha = 0.28
```

Meaning:

Current-window aircraft motion component voxels. These are not direct wind
labels; they provide motion support for later reconstruction experiments.

## Current And Context Windows

Current window:

```text
target time +/- 5 min
total span = 10 min
```

For this frame, current-window `wind_records` are candidates for Stage4
ground-truth hold-out.

Context window:

```text
target time +/- 360 min
total span = 720 min = 12 h
exclude abs(delta_time_minutes) <= 5 min
```

Context wind and context motion improve data reuse, but they are not labels.

## Confidence And QC Diagnostics

Active confidence in Stage2/Stage3:

```text
time_conf = 0.5 ** (abs(delta_time_minutes) / 180)
space_conf = 1.0
joint_likelihood = obs_conf * time_conf
```

The logical Ground Center is not a spatial weighting center. Stage4 will later
compute observation-to-target-voxel localization.

Diagnostic-only fields now available in the context records:

```text
quality_conf_diagnostic
density_conf_diagnostic
qc_flags
```

They are not used in the active `joint_likelihood` in this stage. `qc_flags`
marks high-speed candidates for review without deleting them.
