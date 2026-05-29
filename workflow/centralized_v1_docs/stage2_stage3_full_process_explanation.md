# centralized_v1 Stage2/Stage3 Full Process Explanation

This document explains the current Stage2/Stage3 prototype and answers the
nine recurring questions about the Stage1-3 data path, Stage2 slice figure,
voxelization, time windows, Ground Center, confidence, references, Stage4 entry
and handover.

## 0. Where Do The Data Come From?

Stage2/Stage3 do not read the old `stage2_output/voxels` as the main input.
The current regenerated chain reads Stage1 outputs:

```text
/data/LFT-W02_data/pengxu/stage1_output/clean_wind.parquet
/data/LFT-W02_data/pengxu/stage1_output/clean_loc.parquet
/data/LFT-W02_data/pengxu/stage1_output/radar_index.json
```

and the radar PNG files referenced by `radar_index.json`.

Yes, the Stage2 background uses the project weather-radar mosaic PNGs. Example
`radar_index.json` entry:

```text
filename = Z_RADA_C_BABJ_P_ACHN_CREF000_20260123180000_12.2_54.2_73.0_135.0.png
radar_path = /data/LFT-W02_data/pengxu/20260224/radar/Z_RADA_C_BABJ_P_ACHN_CREF000_20260123180000_12.2_54.2_73.0_135.0.png
usable = true
```

Stage1 file sizes currently observed:

```text
clean_wind.parquet rows = 431189
clean_loc.parquet rows = 19162638
radar_index.json rows = 7396
```

### What Is In `clean_wind.parquet`?

`clean_wind.parquet` is created from:

```text
amdar_parquet + turb_parquet -> clean_wind.parquet
```

Important fields:

```text
time_utc
lat_clean / lon_clean / alt_meters
wind_dir / wind_speed
u_wind / v_wind
flight_id
source
obs_conf
```

Wind component calculation in Stage1:

```text
u_wind = -wind_speed * sin(wind_dir)
v_wind = -wind_speed * cos(wind_dir)
```

`source` records whether the row comes from AMDAR or turbulence input, and
`obs_conf` is the source-level observation confidence.

Reference beside this operation: WMO aircraft-based observations describe
aircraft weather reports as meteorological values with position and time
metadata (`https://wmo.int/aircraft-based-observations-programme`). Local
knowledge-base cross-reference: `workflow/wiki/aircraft-derived-meteorological-observations.md`.

### What Is In `clean_loc.parquet`?

`clean_loc.parquet` is created from:

```text
location_location_parquet -> clean_loc.parquet
```

Important fields:

```text
time_utc
lat_clean / lon_clean / alt_meters
heading_deg
ground_speed_ms
flight_id
u_motion / v_motion
```

Motion component calculation in Stage1:

```text
ground_speed_ms = 地速 * GROUND_SPEED_TO_MPS
u_motion = ground_speed_ms * sin(heading_deg)
v_motion = ground_speed_ms * cos(heading_deg)
```

These motion vectors are aircraft motion components. They are not direct
atmospheric wind labels.

Reference beside this operation: separating aircraft kinematics from wind
observations avoids treating ground speed as atmospheric wind. See WMO
aircraft-based observations and the local note
`workflow/wiki/aircraft-derived-meteorological-observations.md`.

### What Is In `radar_index.json`?

`radar_index.json` is built by scanning radar mosaic PNG paths. Each item has:

```text
filename
time_str
timestamp_utc
radar_path
usable
```

Stage2 uses `radar_path` to read the actual PNG with OpenCV grayscale decoding,
keeps it as a `cloud_2d/radar_img` intensity layer, and downsamples it by
`xy_downsample=4` for the Stage2 grid. This radar layer is 2D cloud/radar
context only; it is not treated as a wind label and cannot by itself perform
3D Doppler wind retrieval.

Formula and reference beside this operation:

```text
gray = OpenCV IMREAD_GRAYSCALE intensity
cloud_2d = radar_img[::4, ::4]
horizontal cost ratio ~= 1 / (4 * 4) = 1/16
```

References: OpenCV grayscale image I/O/color conversion documentation
(`https://docs.opencv.org/4.x/`) and WeatherBench2 gridded-data organization
(`https://weatherbench2.readthedocs.io/en/latest/data-guide.html`).

## 1. What Do `traj voxels`, `motion voxels`, `context wind` And `wind vectors` Mean?

In the Stage2 figure for `20260208124800`, the fourth horizontal slice is
`z=23`, corresponding to approximately `11500 m`. Its title includes:

```text
traj voxels (112)
motion voxels (104)
context wind (115)
wind vectors (5)
```

These are counts of records on that selected z layer:

- `traj voxels (112)`:
  112 grid cells at z=23 contain `loc_records`. They show current-window
  aircraft trajectory density. Each voxel stores `density`, the number of
  current-window trajectory points grouped into that `(z,y,x)`. These come
  from `clean_loc.parquet` fields `time_utc`, `lat_clean`, `lon_clean` and
  `alt_meters`.
- `motion voxels (104)`:
  104 grid cells at z=23 contain `motion_records`. They store aircraft motion
  components `u_motion/v_motion` and `motion_count`. These come from
  `clean_loc.parquet` fields `heading_deg`, `ground_speed_ms`, `u_motion` and
  `v_motion`.
- `context wind (115)`:
  115 grid cells at z=23 contain `context_wind_records`. They come from the
  historical context window and are used later as reconstruction context, not
  as ground-truth labels. These come from `clean_wind.parquet` fields
  `time_utc`, `lat_clean`, `lon_clean`, `alt_meters`, `u_wind`, `v_wind` and
  `obs_conf`.
- `wind vectors (5)`:
  5 grid cells at z=23 contain `wind_records`. These are current-window wind
  label candidates from `clean_wind.parquet`. Their arrows use `u/v`, and they
  are candidates for Stage4 strict hold-out.

## 2. What Do The Colors, Transparency, Arrows And X Marks Mean?

The gray image is `cloud_2d/radar_img`. Brighter pixels mean stronger radar
echo intensity. This is a 2D radar/cloud background, not a reconstructed wind
field.

Orange arrows and dots:

```text
source = wind_records
color = #ff7a00
quiver alpha = 0.85
dot size = 22
dot edge = black
```

They are current `+/-5 min` wind label candidates. Arrow direction comes from
`u/v`. These points should be used as Stage4 hold-out candidates, not as input
after they are selected as ground truth.

Purple/magenta x marks:

```text
source = context_wind_records
horizontal marker = x
horizontal cmap = magma
horizontal alpha = 0.55
horizontal size = 8 + 28 * time_conf
vertical color = #d936c9
vertical alpha = 0.45
```

They are historical context wind. In horizontal slices, color follows wind
speed and size follows `time_conf`.

Blue dots:

```text
source = loc_records
color = #2aa8ff
horizontal size = 4
horizontal alpha = 0.22
vertical alpha = 0.20
```

They show current-window trajectory density voxels.

Green dots:

```text
source = motion_records
color = #20b25f
size = 6
alpha = 0.28
```

They show current-window aircraft motion component voxels.

## 3. What Do Current `+/-5 min` And Context `+/-6 h` Mean?

For a target radar time `T`:

```text
current window = [T - 5 min, T + 5 min]
context window = [T - 360 min, T + 360 min]
```

The current window is 10 minutes total. It produces current `wind_records`,
`loc_records`, `motion_records` and `flight_raw_records`. Current
`wind_records` are the only Stage4 ground-truth label candidates.

The context window is 12 hours total. It excludes the current label window:

```text
abs(delta_time_minutes) <= 5 min is excluded from context
```

This follows finite-window data-assimilation practice: observations are grouped
around the target analysis time instead of mixing unlimited history.

## 4. What Is The Ground Reference Center?

There are two different ideas:

1. `Ground Center`
   - A logical server that receives all aircraft observations.
   - It is not a physical station coordinate.
   - It does not filter by communication distance.
2. `reference_center`
   - A diagnostic/rendering reference point stored in Stage2 metadata.
   - It is selected as the median `lat_clean/lon_clean/alt_meters` from
     current-window flight raw records.
   - If current-window flight raw records are empty, it falls back to the China
     domain bbox center: `lat=33.2`, `lon=104.0`, `alt=0`.

The reference center is not computed from all records in the full database and
does not represent the whole country. It is not used for weighting, deletion or
ROI cropping.

Current all-in scope means:

```text
per-frame time window
+ Stage2 China-domain grid
+ 0-15000 m altitude range
+ required fields available
+ voxel grouping
```

It does not mean that every row from the full historical database is inserted
into every frame.

## 5. What Does Stage2 Do, And How Is It Different From Stage3?

Stage2:

- Reads Stage1 `clean_wind.parquet`, `clean_loc.parquet`, `radar_index.json`
  and radar PNG frames.
- Selects current and context windows around each target radar time.
- Converts latitude/longitude/altitude observations to `(z,y,x)` grid cells.
- Aggregates records into:
  `wind_records`, `context_wind_records`, `loc_records`, `motion_records`,
  `context_motion_records`, `flight_raw_records`, and `cloud_2d/radar_img`.
- Writes `.npz` files, summary JSON, slice PNGs, stats CSVs, point CSVs and
  data integrity audits.
- Does not reconstruct a wind field.

Stage3:

- Reads Stage2 regenerated `.npz` paths from the Stage2 summary.
- Treats Ground Center as a logical receiver of all aircraft observations.
- Does not do Air-to-Air communication.
- Does not filter by communication distance.
- Outputs a `ground_center_payload` with grouped observation roles:
  `label_candidates`, `context_wind_observations`,
  `context_motion_observations`, `trajectory_observations`,
  `motion_observations`, and `confidence_package`.
- Does not reconstruct a wind field.

Stage4 is where strict hold-out, target-voxel localization and point error
evaluation should happen.

## 5.1 What Does "Orange Points Are Stage4 Validation Candidates" Mean?

Orange points/arrows come from `wind_records`, which are current-window real
wind candidate observations.

Stage4 point evaluation must avoid data leakage:

```text
1. Select hold-out points only from wind_records.
2. Remove selected hold-out points from the fusion input.
3. Reconstruct/predict wind at those voxel locations.
4. Compare prediction with the removed ground truth:
   gt_u / gt_v vs pred_u / pred_v.
```

This means a selected orange point becomes the answer key for evaluation. Once
selected as ground truth, it cannot also be used as an input to reconstruct the
same wind field.

## 6. What Confidence Constraints Are Used Now?

Active confidence:

```text
time_conf = 0.5 ** (abs(delta_time_minutes) / 180)
space_conf = 1.0
joint_likelihood = obs_conf * time_conf
```

`time_conf` is active because wind evolves with time. A half-life of 180 min
means observations 3 hours away receive weight 0.5, 6 hours away receive 0.25,
before any later Stage4 localization.

`space_conf` is neutral in Stage2/Stage3 because Ground Center is logical. A
far observation should not be downweighted just because it is far from a
reference center. Stage4 should compute spatial localization from each
observation voxel to each target voxel.

Diagnostic-only fields added in this round:

```text
quality_conf_diagnostic = 1.0
density_conf_diagnostic = 1 - exp(-count / 3)
qc_flags = ok | high_speed_qc_candidate
```

For context wind, `count` is `obs_count`; high-speed QC is flagged when
diagnostic wind speed is above `120 m/s`.

For context motion, `count` is `motion_count`; high-speed QC is flagged when
diagnostic motion speed is above `320 m/s`.

These are diagnostics only. They are not used in the active
`joint_likelihood`, and Stage2 does not delete these records.

Verified diagnostics after the latest two-frame run:

```text
20260208124800:
  context records with qc_flags=ok: 39967
  context records with high_speed_qc_candidate: 8

20260211060600:
  context records with qc_flags=ok: 39839
  context records with high_speed_qc_candidate: 1
```

## 7. Quick Reference Index

The formulas and references are now placed beside each operation in the
calculation ledger below. This section is only a quick index for lookup.

ECMWF IFS/4D-Var:

- 4D-Var uses observations inside an assimilation time window.
- This supports Stage2 finite current/context windows instead of unrestricted
  all-history mixing.
- Reference:
  https://www.ecmwf.int/en/publications/ifs-documentation
  and
  https://confluence.ecmwf.int/pages/viewpage.action?pageId=315559375

ERA5:

- ERA5 uses 4D-Var and time-windowed observations, supporting explicit time
  organization.
- Reference:
  https://confluence.ecmwf.int/display/CKB/ERA5%3A%2Bdata%2Bdocumentation

WMO AMDAR / aircraft-based observations:

- Aircraft observations include wind, position and time information.
- This supports keeping wind, trajectory, motion and raw flight records as
  separate groups.
- Reference:
  https://wmo.int/activities/aircraft-based-observations/aircraft-based-observations
  and
  https://wmo.int/aircraft-based-observations-programme

DART / Gaspari-Cohn localization:

- Localization is a target-state or target-gridpoint idea.
- This supports deferring spatial weighting to Stage4, where each target voxel
  is known.
- Reference:
  https://docs.dart.ucar.edu/en/latest/assimilation_code/modules/assimilation/cov_cutoff_mod.html

WeatherBench2 / GraphCast / GenCast / Aurora / FourCastNet:

- Modern weather ML pipelines use gridded multivariate states and time context.
- Stage2 borrows the data organization idea, not model training.
- References:
  https://weatherbench2.readthedocs.io/en/latest/data-guide.html
  https://github.com/google-deepmind/graphcast
  https://github.com/microsoft/aurora
  https://github.com/NVlabs/FourCastNet

## 8. Current Verified Outputs

Stage2 summary:

```text
/data/LFT-W02_data/pengxu/centralized_v1_output/stage2_regenerated/stage2_multimodal_summary.json
```

Stage2 slice outputs:

```text
/data/LFT-W02_data/pengxu/centralized_v1_output/stage2_regenerated/slices
```

Stage3 summary:

```text
/data/LFT-W02_data/pengxu/centralized_v1_output/stage3_center/stage3_center_summary.json
```

Stage3 visual reports:

```text
/data/LFT-W02_data/pengxu/centralized_v1_output/stage3_center/reports
```

Verified Stage3 rows:

```text
20260208124800:
  agents = 746
  label_candidates = 114
  context_wind_observations = 1284
  context_motion_observations = 38691
  trajectory_observations = 5175
  motion_observations = 4887

20260211060600:
  agents = 773
  label_candidates = 1
  context_wind_observations = 1079
  context_motion_observations = 38761
  trajectory_observations = 5247
  motion_observations = 4506
```

## Next Step

Do not go back to the old Stage4 frozen chain.

Next implementation target:

```text
Stage4 strict hold-out
+ observation-to-target-voxel localization
+ point eval with concrete numerical errors
```

## 9. Do We Need Full Output Now?

No. Current recommendation:

```text
Do not run full Stage2/Stage3 now.
Use 2-10 representative frames for Stage4 strict hold-out and point eval first.
Run full Stage2/Stage3 only after Stage4 metrics and reports are stable.
```

Reason:

- Stage2 already proves data ingestion, radar mosaic use, voxel/point records,
  and integrity audit.
- Stage3 already proves all-agent Ground Center payload and confidence package.
- Full output is useful later for aggregate statistics, but it does not solve
  the immediate risk: Stage4 must first avoid hold-out leakage and implement
  target-voxel localization.

Current gate conclusion:

```text
Stage2: pass as all-in observation organization.
Stage3: pass as Ground Center intake and confidence packaging.
Next: Stage4 small-batch strict hold-out.
```

## 10. Stage1-3 Calculation Ledger And Freeze Conclusion

This section is the detailed calculation ledger requested before starting
Stage4. It states what each stage computes, why the computation is used, and
which part is physical, mathematical or reference-based.

### 10.1 Stage1 Wind Standardization

Stage1 reads:

```text
DATA_ROOT/amdar_parquet
DATA_ROOT/turb_parquet
```

Both directories contain parquet shards listed by `_manifest.json`. Stage1
reads the shards and concatenates them with a relaxed diagonal schema so that
AMDAR and turbulence-specific columns can coexist.

The cleaned wind table is:

```text
clean_wind.parquet = normalize(amdar_parquet) + normalize(turb_parquet)
```

Important field calculations:

| Stage1 field | Source column or rule | Formula / rule | Basis |
| --- | --- | --- | --- |
| `time_utc` | existing `time_utc`, or `time_beijing`, or `时间（北京时间）` | Beijing time is shifted by `-8h` when needed | All later windows require one UTC time axis |
| `lat_clean` | `纬度_clean` | cast to float | WMO aircraft observations include position |
| `lon_clean` | `经度_clean` | cast to float | WMO aircraft observations include position |
| `alt_meters` | `高度` | cast to float | 3D wind field needs vertical coordinate |
| `wind_dir` | `风向` | cast to float degrees | Aircraft wind reports include wind direction |
| `wind_speed` | `风速` | cast to float m/s as provided | Aircraft wind reports include wind speed |
| `u_wind` | `wind_speed`, `wind_dir` | `-wind_speed * sin(wind_dir*pi/180)` | Meteorological wind direction is the direction wind comes from |
| `v_wind` | `wind_speed`, `wind_dir` | `-wind_speed * cos(wind_dir*pi/180)` | Converts speed/direction into east/north components |
| `source` | input table | `amdar` or `turb` | Keep provenance for QC and weighting |
| `obs_conf` | source confidence | AMDAR=`1.0`, turbulence=`0.9` | Source-level diagnostic confidence |

Example:

```text
wind_speed = 20 m/s
wind_dir = 270 deg
sin(270 deg) = -1
cos(270 deg) ~= 0

u_wind = -20 * -1 = 20 m/s
v_wind = -20 * 0 = 0 m/s
```

Interpretation: wind from the west blows toward the east, so the eastward
component `u_wind` is positive.

### 10.2 Stage1 Location And Motion Standardization

Stage1 reads:

```text
DATA_ROOT/location_location_parquet
```

The cleaned location table is:

```text
clean_loc.parquet = normalize(location_location_parquet)
```

Important field calculations:

| Stage1 field | Source column or rule | Formula / rule | Basis |
| --- | --- | --- | --- |
| `time_utc` | `接收时间（UTC）` or existing `time_utc` | parse as UTC datetime | All frames need one time axis |
| `lat_clean` | `纬度_clean` | cast to float | Aircraft position |
| `lon_clean` | `经度_clean` | cast to float | Aircraft position |
| `alt_meters` | `高度` | cast to float | Vertical grid placement |
| `heading_deg` | `航向角` | cast to float degrees | Aircraft motion direction |
| `ground_speed_ms` | `地速` | `地速 * 1000/3600` | Convert km/h to m/s |
| `flight_id` | `flight_id`, `航班号`, or `机尾号` | first available ID | Group Flight Agents |
| `u_motion` | `ground_speed_ms`, `heading_deg` | `ground_speed_ms * sin(heading*pi/180)` | Eastward aircraft motion |
| `v_motion` | `ground_speed_ms`, `heading_deg` | `ground_speed_ms * cos(heading*pi/180)` | Northward aircraft motion |

Example:

```text
地速 = 540 km/h
ground_speed_ms = 540 * 1000 / 3600 = 150 m/s
heading_deg = 90 deg

u_motion = 150 * sin(90 deg) = 150 m/s
v_motion = 150 * cos(90 deg) ~= 0 m/s
```

Interpretation: the aircraft is moving east. This is aircraft motion, not
atmospheric wind truth. Stage4 must not silently treat motion as wind.

### 10.3 Stage1 Radar Index

Stage1 scans radar mosaic PNG files and parses the timestamp from the filename,
for example:

```text
Z_RADA_C_BABJ_P_ACHN_CREF000_20260123180000_12.2_54.2_73.0_135.0.png
```

The parsed `time_str` is:

```text
20260123180000
```

`radar_index.json` stores:

```text
filename
time_str
timestamp_utc
radar_path
usable
```

Stage2 uses `radar_path` to read the real weather-radar mosaic PNG. The radar
image is not the Stage2 rendered figure size. It is the data layer that becomes
`radar_img/cloud_2d` after OpenCV grayscale decoding and `xy_downsample=4`.

Formula and reference beside this operation:

```text
radar_img = cv2.imdecode(..., cv2.IMREAD_GRAYSCALE)
cloud_2d = radar_img[::xy_downsample, ::xy_downsample]
```

The downsampled layer aligns the 2D radar context with the Stage2 horizontal
voxel grid. It is not a wind observation. True radar wind retrieval needs
Doppler velocity geometry and variational/3DVAR methods such as PyDDA or
dual-Doppler retrieval. References: `https://docs.opencv.org/4.x/`,
`https://openresearchsoftware.metajnl.com/articles/10.5334/jors.264`, and
`workflow/wiki/source-dual-doppler-variational-wind-field.md`.

### 10.4 Stage2 Voxel And Confidence Calculations

Stage2 converts each in-domain observation into a `(z,y,x)` voxel. With current
settings:

```text
LAT_MIN=12.2, LAT_MAX=54.2
LON_MIN=73.0, LON_MAX=135.0
ALT_MIN=0, ALT_MAX=15000
alt_step_m=500
xy_downsample=4
radar original shape ~= 2100 x 3100
Stage2 grid shape = 31 x 525 x 775
```

The exact code-level mapping is:

```text
delta_lat = (LAT_MAX - LAT_MIN) / radar_h
delta_lon = (LON_MAX - LON_MIN) / radar_w

x = floor(((lon_clean - LON_MIN) / delta_lon) / xy_downsample)
y = floor(((LAT_MAX - lat_clean) / delta_lat) / xy_downsample)
z = floor((alt_meters - ALT_MIN) / alt_step_m)
```

Example:

```text
lat=27.24, lon=112.55, alt=11500 m
radar_h=2100, radar_w=3100
delta_lat=(54.2-12.2)/2100 = 0.02 deg
delta_lon=(135.0-73.0)/3100 = 0.02 deg

x=floor(((112.55-73.0)/0.02)/4)=floor(1977.5/4)=494
y=floor(((54.2-27.24)/0.02)/4)=floor(1348/4)=337
z=floor(11500/500)=23
```

A voxel is a 3D grid cell. Voxelization does not invent data; it groups
irregular aircraft points into a regular grid so Stage4 can reconstruct a 3D
field and Stage5 can refine or predict future fields.

Reference beside this operation: gridded weather-state organization is the
standard interface used by WeatherBench2 and many weather ML systems. Stage2
borrows the grid organization idea, not their model training objective:
`https://weatherbench2.readthedocs.io/en/latest/data-guide.html`.

Stage2 time confidence:

```text
time_conf = 0.5 ** (abs(delta_time_minutes) / 180)
```

Examples:

```text
dt=0 min   -> time_conf=1.0
dt=180 min -> time_conf=0.5
dt=360 min -> time_conf=0.25
```

Stage2 active joint likelihood:

```text
space_conf = 1.0
joint_likelihood = obs_conf * time_conf
```

`space_conf` is neutral because Ground Center is logical. Spatial influence is
computed later in Stage4 from observation voxel to target voxel.

Stage2 diagnostic density confidence:

```text
density_conf_diagnostic = 1 - exp(-count/3)
```

Examples:

```text
count=1 -> 0.283
count=3 -> 0.632
count=9 -> 0.950
```

This is only a report field. It does not change `joint_likelihood`.

Reference beside confidence operations: finite current/context windows follow
the same data-assimilation idea as ECMWF ERA5/IFS 4D-Var. References:
`https://confluence.ecmwf.int/display/CKB/ERA5%3A%2Bdata%2Bdocumentation` and
`https://confluence.ecmwf.int/pages/viewpage.action?pageId=315559375`.

### 10.5 Stage3 Ground Center Calculations

Stage3 reads each Stage2 `.npz` and emits a Ground Center payload. It does not
reconstruct wind.

Agent grouping:

```text
group by flight_id
agent_lat = median(lat_clean)
agent_lon = median(lon_clean)
agent_alt = median(alt_meters)
agent_time = max(time_utc)
```

Agent confidence:

```text
agent_delta_time_minutes = abs(agent_time - target_time)
agent_time_conf = exp(-0.12 * agent_delta_time_minutes)
agent_space_conf = 1.0
agent_joint_conf = agent_time_conf
```

Examples:

```text
dt=0 min -> exp(0)=1.000
dt=1 min -> exp(-0.12)=0.887
dt=5 min -> exp(-0.60)=0.549
```

This agent confidence is a payload freshness diagnostic. It is not a
communication-distance filter.

### 10.6 Freeze Conclusion For Stage1-3

Current gate:

```text
Stage1 = pass as cleaned source and radar index preparation.
Stage2 = pass as all-in observation organization with voxel and point records.
Stage3 = pass as Ground Center intake, grouping and confidence packaging.
```

The stages can be temporarily frozen for the small-batch demo. Freeze means:

```text
do not change the data contract or rerun everything unless Stage4 exposes a blocking defect
```

It does not mean:

```text
never add QC, never run full data, or never tune parameters
```

The next risk is no longer Stage2/Stage3 completeness. The next risk is Stage4
evaluation leakage and target-voxel localization, so Stage4 should be the next
implementation target.

## 11. Stage4 Strict Hold-Out Design

Stage4 is the first reconstruction stage. It must do three things:

```text
1. select current wind hold-out labels from wind_records
2. remove those labels before fusion
3. reconstruct their voxel values and report numeric errors
```

The active Stage4 fusion inputs are:

```text
non-holdout current wind_records
context_wind_records
```

The following are diagnostics/support only in the first strict demo:

```text
loc_records
motion_records
context_motion_records
```

Reason: aircraft motion is not atmospheric wind truth. It can describe coverage
and future features, but it should not be directly averaged into the wind field
as if it were measured wind.

Stage4 target-voxel localization:

```text
localization = exp(-0.5 * ((dx/sigma_xy)^2 + (dy/sigma_xy)^2 + (dz/sigma_z)^2))
active_weight = obs_conf * time_conf * localization
```

This follows the DART/Gaspari-Cohn localization principle: spatial influence is
relative to the target state or target grid point, not relative to the logical
Ground Center. The current implementation uses a Gaussian kernel as the first
demo kernel; Gaspari-Cohn can be added as a selectable kernel later.

Point evaluation fields:

```text
gt_u, gt_v
pred_u, pred_v
u_error = pred_u - gt_u
v_error = pred_v - gt_v
vector_error = sqrt(u_error^2 + v_error^2)
mae_u, mae_v, mae_vector
rmse_vector
bias_u, bias_v
```

## 12. Stage2 Detailed Count Meanings And Visual Encoding

### 12.1 Trajectory Voxels vs Motion Voxels

Both `traj voxels` and `motion voxels` come from aircraft observation data in
`clean_loc.parquet`, but they mean different things.

`traj voxels` answer:

```text
Where did aircraft pass during the current window?
```

Calculation:

```text
1. take clean_loc current-window rows
2. require time_utc, lat_clean, lon_clean, alt_meters
3. map each row to z,y,x
4. group by z,y,x
5. density = number of location rows in that voxel
```

`motion voxels` answer:

```text
What aircraft motion vector was observed in those current-window voxels?
```

Calculation:

```text
1. start from the same clean_loc current-window rows
2. require u_motion and v_motion in addition to position
3. u_motion = ground_speed_ms * sin(heading_deg*pi/180)
4. v_motion = ground_speed_ms * cos(heading_deg*pi/180)
5. group by z,y,x
6. motion voxel stores mean u_motion, mean v_motion, and motion_count
```

Why they are separate:

```text
traj voxels = coverage/density of aircraft paths
motion voxels = aircraft kinematics, not atmospheric wind truth
```

Reference and physical basis: WMO aircraft-based observations define aircraft
reports as time/position/altitude plus meteorological or aircraft-state fields.
Separating trajectory coverage from motion vectors avoids treating aircraft
ground speed as wind speed.

### 12.2 Background Wind And Current Wind Vectors

`context wind` or background wind answers:

```text
What historical wind observations are near the target time, excluding the true-label window?
```

Calculation:

```text
1. take clean_wind rows inside target time +/-360 min
2. remove abs(delta_time_minutes) <= 5 min
3. require time_utc, lat_clean, lon_clean, alt_meters, u_wind, v_wind
4. map to z,y,x
5. compute time_conf = 0.5 ** (abs(delta_time_minutes)/180)
6. aggregate each voxel by weighted mean:
   u = sum(u_wind * obs_conf * time_conf) / sum(obs_conf * time_conf)
   v = sum(v_wind * obs_conf * time_conf) / sum(obs_conf * time_conf)
```

Reference and physical basis: ECMWF IFS/4D-Var uses finite assimilation
windows, so Stage2 uses a finite 12-hour context instead of unlimited history.
Time confidence follows the same idea as the local workflow note in
`workflow/raw/面向自主运行的多机态势智能协同感知方法研究/8-ZY2202521-方宇航.md`,
where old meteorological observations decay with data age.

`wind vectors` answer:

```text
Which current-window true wind observations can be used as Stage4 labels?
```

Calculation:

```text
1. take clean_wind rows inside target time +/-5 min
2. map to z,y,x
3. group by z,y,x
4. u = mean(u_wind), v = mean(v_wind), obs_count = grouped rows
```

These are orange arrows/dots. In Stage4, selected orange points become
hold-out truth and are removed from fusion input before prediction.

### 12.3 Radar Grayscale And 4x Downsampling

Stage2 reads the real radar mosaic PNG from `radar_index.json.radar_path`,
converts it to grayscale with OpenCV image decoding, and keeps it as
`radar_img/cloud_2d`.

Why grayscale:

```text
The current Stage2 uses radar echo intensity as a background/support layer.
For the Stage2/Stage4 wind demo, only intensity is needed; color-table details
are not used as wind labels.
```

Formula and reference beside this operation:

```text
radar_img = cv2.imdecode(file_bytes, cv2.IMREAD_GRAYSCALE)
```

This is an image preprocessing step. It does not convert radar reflectivity into
wind. Reference: OpenCV image read/color conversion documentation
(`https://docs.opencv.org/4.x/`).

Why `xy_downsample=4`:

```text
original radar mosaic ~= 2100 x 3100
Stage2 grid after downsample = 525 x 775
3D grid = 31 x 525 x 775
```

This keeps the radar layer aligned with the voxel grid while reducing memory and
plotting cost by about 16x in the horizontal plane. The operation is a grid
organization step, not a meteorological claim that the radar has lower native
resolution.

Formula and reference beside this operation:

```text
cloud_2d = radar_img[::4, ::4]
horizontal cost ratio ~= 1/16
grid_shape = z_dim x (radar_h/4) x (radar_w/4)
```

Reference and method basis: WeatherBench2, GraphCast, GenCast, Aurora and
FourCastNet all organize weather states on regular grids. Stage2 borrows this
regular-grid organization, not their training objective. See
`https://weatherbench2.readthedocs.io/en/latest/data-guide.html`.

Boundary: because the input is a 2D radar mosaic PNG, it is not equivalent to a
Doppler radar volume with radial velocity. If later radar wind retrieval is
needed, use a 3DVAR/dual-Doppler route such as PyDDA or the dual-Doppler
variational method summarized in
`workflow/wiki/source-dual-doppler-variational-wind-field.md`.

### 12.4 Visual Encoding Chart Outputs

In addition to CSV tables, Stage2 now writes a visual encoding diagnostic chart:

```text
/data/LFT-W02_data/pengxu/centralized_v1_output/stage2_regenerated/slices/stage2_visual_encoding_<time>.png
```

The chart shows:

```text
1. voxel counts by altitude for current wind, context wind, trajectory and motion
2. bar chart of displayed-layer counts by encoded point type
3. context wind scatter: x=time_conf, y=wind_speed, marker size=time_conf, color=speed
4. legend explaining orange arrows, purple x marks, blue dots and green dots
```

For `20260208124800`, selected-layer examples include:

```text
z=23 / 11500 m:
  current wind vectors = 5
  context wind voxels = 115
  traj voxels = 112
  motion voxels = 104

z=27 / 13500 m:
  current wind vectors = 12
  context wind voxels = 107
```

## 13. Observation Confidence

Current active confidence contains:

```text
obs_conf
time_conf
space_conf
joint_likelihood
```

`obs_conf`:

```text
AMDAR wind rows = 1.0
turbulence wind rows = 0.9
motion context rows = 1.0 diagnostic default
```

Source basis: source provenance is preserved because AMDAR and turbulence rows
are not identical instruments/fields. Current values are simple source priors,
not learned calibration.

`time_conf`:

```text
time_conf = 0.5 ** (abs(delta_time_minutes)/180)
```

Examples:

```text
0 min -> 1.0
180 min -> 0.5
360 min -> 0.25
```

Physical basis: wind is time-varying, so older observations should influence
the target time less. This is consistent with finite-window assimilation in
ECMWF IFS/4D-Var and the local workflow's dynamic time confidence discussion.

`space_conf`:

```text
Stage2/Stage3 space_conf = 1.0
```

Reason: Ground Center is logical. Distance to a reference center should not
make a nationwide observation less trustworthy. Stage4 computes distance from
each observation voxel to the target voxel instead.

`joint_likelihood`:

```text
Stage2/Stage3 joint_likelihood = obs_conf * time_conf
Stage4 active_weight = obs_conf * time_conf * target_voxel_localization
```

Diagnostic fields:

```text
quality_conf_diagnostic = 1.0 after required-field checks
density_conf_diagnostic = 1 - exp(-count/3)
qc_flags = ok | high_speed_qc_candidate
```

These diagnostics are shown in reports but do not silently delete data.

## 14. Stage4 Strict Small-Batch Result

The strict Stage4 demo was run only on:

```text
20260208124800
20260211060600
```

Output directory:

```text
/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_center_strict
```

Generated files per frame:

```text
frame_<time>_center_strict.npz
point_eval_<time>.json
point_eval_<time>.csv
point_eval_<time>.txt
stage4_method_<time>.md
slices/<time>_centralized_stage4_slices.png
slices/<time>_centralized_stage4_diagnostics.png
slices/<time>_centralized_stage4_slice_stats.csv
```

Result summary after the strict layered visualization update:

| time | wind_records | hold-out | fusion current wind | context wind | pre-refine support voxels | final effective voxels | domain fraction | low-conf fill | bbox lat | bbox lon | bbox alt | RMSE vector | MAE vector | note |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | --- | ---: | ---: | --- |
| `20260208124800` | 114 | 15 | 99 | 1284 | 276198 | 417438 | 3.309553% | 141240 | 17.240-36.760 | 106.360-118.280 | 0-15000 m | 6.468737 | 5.422913 | normal demo frame; support and low-confidence fill are shown separately |
| `20260211060600` | 1 | 1 | 0 | 1079 | 217861 | 339248 | 2.689643% | 121387 | 19.000-37.480 | 106.920-118.200 | 500-15000 m | 3.390634 | 3.390634 | sparse-label pressure test; reconstruction uses context wind only |

Leakage check:

```text
strict_holdout_no_leakage = true
motion_used_as_wind = false
```

Interpretation:

- The Stage4 contract is now usable for strict point evaluation.
- The first frame is suitable as a normal demo because it has enough current
  wind labels for train/hold-out splitting.
- The second frame is useful as a pressure test, not as a standalone
  performance claim, because all current wind labels are held out and the
  reconstruction must rely on historical context.
- The old Stage4 image used `x=387`, where this frame had zero reconstructed
  coverage, so the vertical panel looked like a flat low-value color. The report
  now auto-selects a representative x slice from hold-out/nonzero coverage; for
  `20260208124800` it selects `x=502`.
- The PINN/diffusion-style layer is a proxy gap-fill layer, not a trained deep
  model. It uses weak divergence/smoothness regularization and low-confidence
  neighbor propagation while preserving source-supported voxels.
- The block-like Stage4 footprint is mainly produced by finite-radius Gaussian
  target-voxel localization plus low-confidence neighbor propagation. It is not
  evidence that the real wind field is physically moving as one solid block.
- `recon_mask_3d > 0` is now the effective reconstruction definition. The
  code forces `recon_confidence_3d > 0` to match this mask; both verified frames
  have `mask_conf_positive_mismatch_voxels = 0`.

Formula and reference beside Stage4 localization:

```text
localization = exp(-0.5 * ((dx/sigma_xy)^2 + (dy/sigma_xy)^2 + (dz/sigma_z)^2))
active_weight = obs_conf * time_conf * localization
```

Reference: DART/Gaspari-Cohn localization treats observation influence as a
target-state/gridpoint relation, supporting observation-to-target-voxel
localization rather than weighting by the logical Ground Center:
`https://docs.dart.ucar.edu/en/latest/assimilation_code/modules/assimilation/cov_cutoff_mod.html`.

Formula and reference beside strict hold-out:

```text
train_wind = wind_records - holdout_wind
point_error = [pred_u - gt_u, pred_v - gt_v]
vector_error = sqrt(u_error^2 + v_error^2)
```

Aircraft-derived weather-field reconstruction exists in the literature, but the
observations are sparse and noisy rather than perfect truth. References:
`https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0205029`,
`https://amt.copernicus.org/articles/18/3341/2025/`, and
`https://amt.copernicus.org/articles/9/4141/2016/`.

Representative Stage4 slice stats for `20260208124800`:

```text
horizontal z=23 / 11500 m:
  active_voxels = 20113
  support_voxels = 14764
  low_conf_fill_voxels = 5349
  speed_mean = 13.697357 m/s
  speed_max = 101.124153 m/s
  conf_mean = 0.247147

horizontal z=27 / 13500 m:
  active_voxels = 21168
  support_voxels = 17588
  low_conf_fill_voxels = 3580
  speed_mean = 20.278200 m/s
  speed_max = 149.328720 m/s
  conf_mean = 0.279798

vertical x=502:
  active_voxels = 4857
  support_voxels = 3953
  low_conf_fill_voxels = 904
  speed_mean = 9.571013 m/s
  speed_max = 33.710575 m/s
  conf_mean = 0.364953
```

Method basis beside operations:

The references are placed directly above beside the operations: finite
current/context window, target-voxel localization, strict hold-out, proxy
gap-fill, radar PNG boundary, and regular 3D grid organization.

Stage4 expanded work has now been implemented:

```text
1. Stage3 supports --num-workers shard subprocess mode and --out-dir.
2. Stage4 supports localization_kernel = gaussian | gaspari_cohn.
3. Stage4 keeps leakage checks mandatory and fails on leakage.
4. Stage4 writes confidence diagnostics and 3D proxy diagnostics.
5. Sensitivity writes metrics-only CSV/MD tables for radius/sigma/kernel sweeps.
```

Expanded outputs:

```text
/data/LFT-W02_data/pengxu/centralized_v1_output/stage3_center_expanded/stage3_center_summary.json
/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_center_strict_expanded/stage4_center_summary.json
/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_center_strict_expanded/sensitivity/stage4_localization_sensitivity.csv
```

Expanded verification:

```text
Stage3 expanded rows = 10
Stage4 expanded rows = 10
Sensitivity rows = 60
strict_holdout_no_leakage = true for all rows
motion_used_as_wind = false for all rows
mask_conf_positive_mismatch_voxels = 0 for all expanded Stage4 rows
```

Default Gaussian expanded metrics:

| time | hold-out | RMSE vector | MAE vector | effective voxels | low-conf fill |
| --- | ---: | ---: | ---: | ---: | ---: |
| `20260131073000` | 13 | 6.777242 | 5.990721 | 337139 | 110647 |
| `20260206174200` | 11 | 20.248046 | 14.126716 | 316888 | 117202 |
| `20260207022400` | 13 | 15.947578 | 8.894733 | 343325 | 119785 |
| `20260208124800` | 15 | 6.468737 | 5.422913 | 417438 | 141240 |
| `20260210060000` | 1 | 5.693201 | 5.693201 | 347436 | 132755 |
| `20260211060600` | 1 | 3.390634 | 3.390634 | 339248 | 121387 |
| `20260213053600` | 1 | 6.910204 | 6.910204 | 263035 | 108743 |
| `20260215063000` | 3 | 5.925957 | 4.098377 | 214732 | 78990 |
| `20260215063600` | 3 | 5.779233 | 3.910550 | 211646 | 77665 |
| `20260215100600` | 4 | 9.918892 | 9.241952 | 202879 | 73158 |

Full-run gate remains:

```text
Do not run full Stage2/Stage3/Stage4 yet.
Review expanded 10-frame metrics, Gaussian vs Gaspari-Cohn sensitivity,
and high-error frame diagnostics first.
```

Dedicated Stage4 handover:

```text
workflow/centralized_v1_docs/stage4_strict_holdout_logic_and_results.md
```
