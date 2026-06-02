# centralized_v1 Stage1-Stage4 全流程说明

本文用于向老师说明 `centralized_v1` 项目从原始观测到 Stage4 三维风场重构的完整流程。核心主线是：

```text
原始航空器/雷达数据
-> Stage1 清洗与标准化
-> Stage2 多源观测体素化
-> Stage3 Ground Center 中心化接入与置信度打包
-> Stage4 strict aircraft holdout 三维风场重构与评估
```

必须先讲清楚的验证边界：

```text
official truth = current aircraft wind_records strict holdout
holdout wind_records must be removed before fusion
location/motion records are aircraft kinematics, not atmospheric wind truth
CMA/GFS/ERA can be weak background or condition only, not truth
radar PNG intensity is cloud/radar context, not Doppler wind
no-holdout frames are unverified reconstruction, not official RMSE/MAE
```

## 0. 一眼看懂版

| 阶段 | 解决的问题 | 输入 | 输出 | 不能误解的点 |
| --- | --- | --- | --- | --- |
| Stage1 | 把原始 Excel/parquet/雷达文件整理成统一数据表和索引。 | AMDAR/TURB wind、location、radar PNG | `clean_wind.parquet`, `clean_loc.parquet`, `radar_index.json`, `frame_window_index.json` | `u_motion/v_motion` 是飞机运动，不是风。 |
| Stage2 | 把稀疏飞机观测和雷达图组织到统一三维体素网格。 | Stage1 三个主文件 + radar PNG | 每帧 `.npz`, `stage2_multimodal_summary.json`, slices/audit | Stage2 不重构风场，只组织观测。 |
| Stage3 | Ground Center 中心化接收和打包所有观测角色。 | Stage2 `.npz` | `ground_center_payload`, agent payload, confidence package | Ground Center 是逻辑服务器，不是物理站点。 |
| Stage4 | 生成三维风场，并用严格 aircraft holdout 验证。 | Stage2/Stage3 summary + Stage2 `.npz` | reconstructed `u/v/conf/mask`, point errors, RMSE/MAE, PNG | 只有被拿掉的 aircraft wind holdout 是真值。 |

## 1. Stage1：清洗、标准化、建立雷达帧索引

Stage1 的目标是把异构原始数据变成后续阶段能稳定读取的标准表。当前主要入口包括：

```text
stage/stage1_prepare.py
stage/convert_excel_to_parquet_robust.py
stage/check_location_parquet_quality.py
stage/check_stage1_stage2_alignment.py
```

### 1.1 原始 Excel / workbook 转 parquet

处理对象：

```text
amdar.xlsx / turb.xlsx / location.xlsx
```

处理步骤：

1. 自动识别 workbook 类型：`amdar`, `turb`, `location`。
2. 逐 sheet 读取并输出 `sheet_XX.parquet`。
3. 保留原始列，同时补充标准字段。
4. 解析 Excel 时间、字符串时间和截断年份时间。
5. 将北京时间字段统一换算到 UTC。
6. 对 location 的特殊 sheet 结构补标准列名。
7. 写 `_manifest.json`，记录每个 sheet 的输出、行数和状态。

文献/资料借用点：

| 资料 | 借用内容 | 在本项目中的用法 |
| --- | --- | --- |
| WMO Aircraft-Based Observations Programme | 航空器气象观测必须带时间、位置和气象变量。 | 所有后续表都必须保留 `time_utc`, `lat/lon/alt`, wind 或 motion 字段。 |
| 工程数据治理原则 | 原始字段保留、标准字段补充、manifest 记录转换结果。 | 不直接覆盖原始字段，方便后续 QC 和追溯。 |

### 1.2 清洗 aircraft wind：生成 `clean_wind.parquet`

来源：

```text
amdar_parquet + turb_parquet -> clean_wind.parquet
```

关键字段：

```text
time_utc
lat_clean / lon_clean / alt_meters
wind_dir / wind_speed
u_wind / v_wind
flight_id
source
obs_conf
```

主要步骤：

1. 读取 AMDAR/TURB parquet shards。
2. 统一时间为 UTC。
3. 清洗经纬度、高度、航班号/机尾号。
4. 保留风向、风速。
5. 将风向风速转为水平风分量：

```text
u_wind = -wind_speed * sin(wind_dir*pi/180)
v_wind = -wind_speed * cos(wind_dir*pi/180)
```

解释：气象风向是“风从哪里来”。例如西风 `270 deg` 表示风从西向东吹，所以 `u_wind` 为正。

文献/资料借用点：

| 文献/资料 | 借用内容 | 在本项目中的用法 |
| --- | --- | --- |
| WMO aircraft observations | aircraft report 可以包含风、位置、高度和时间。 | `clean_wind` 是 Stage4 official truth 的唯一来源。 |
| de Haan and Stoffelen 2016 | aircraft-derived wind 有可估计的观测误差，需要 QC。 | 支持“aircraft wind 是高价值但要质控的稀疏观测”，不是把每条观测当完美真值。 |
| EMADDC 2025 | 业务 aircraft wind 系统需要完整 QC 和误差控制。 | 支持后续 `diagnostic_weighted` / obs-error diagnostic，而不是直接删数据。 |

### 1.3 清洗 location / motion：生成 `clean_loc.parquet`

来源：

```text
location_location_parquet -> clean_loc.parquet
```

关键字段：

```text
time_utc
lat_clean / lon_clean / alt_meters
heading_deg
ground_speed_ms
flight_id
u_motion / v_motion
```

主要步骤：

1. 读取 location parquet shards。
2. 统一时间为 UTC。
3. 清洗经纬度、高度、航向角、地速。
4. 将地速从 km/h 转为 m/s：

```text
ground_speed_ms = ground_speed_kmh * 1000 / 3600
```

5. 将地速和航向角转为飞机地面运动分量：

```text
u_motion = ground_speed_ms * sin(heading_deg*pi/180)
v_motion = ground_speed_ms * cos(heading_deg*pi/180)
```

关键解释：

```text
ground_vector = air_vector + wind_vector
```

当前 location 只有 ground vector，缺少 true airspeed / Mach / air vector，因此不能唯一反推出 atmospheric wind。`u_motion/v_motion` 只能做轨迹、覆盖和运动诊断。

文献/资料借用点：

| 文献/资料 | 借用内容 | 在本项目中的用法 |
| --- | --- | --- |
| EMADDC 2025 | aircraft-derived wind 需要 ground vector 和 air vector 组合以及 QC。 | 说明 location motion 不能直接当 wind truth。 |
| WMO aircraft observations | 区分气象观测变量和飞机状态/位置变量。 | `clean_loc` 支持覆盖、轨迹和 motion diagnostics，不进入 official truth。 |

### 1.4 建立雷达索引：`radar_index.json`

处理对象：

```text
weather radar mosaic PNG
```

主要步骤：

1. 扫描雷达 PNG 文件。
2. 从文件名解析 `time_str`，例如 `20260123180000`。
3. 记录 `timestamp_utc`, `radar_path`, `usable`。
4. 写入 `radar_index.json`。
5. 同时建立 `frame_window_index.json`，记录每个雷达帧时间窗内有多少 wind/location 行。

文献/资料借用点：

| 文献/资料 | 借用内容 | 在本项目中的用法 |
| --- | --- | --- |
| OpenCV image I/O | 雷达 PNG 可作为灰度强度图读入。 | Stage2 用 `cv2.IMREAD_GRAYSCALE` 读取 radar intensity。 |
| PyDDA / dual-Doppler retrieval | 真风场雷达反演需要 Doppler velocity 和几何约束。 | 明确当前 radar PNG intensity 只是背景层，不能当风速观测。 |

### 1.5 Stage1 质量检查

主要检查：

1. `clean_wind.parquet` / `clean_loc.parquet` 是否存在。
2. 时间字段是否能解析。
3. 经纬度/高度是否在合理范围。
4. 雷达帧是否能解析时间。
5. wind/location 与 radar time 是否有重叠。
6. location 点是否能落入 Stage2 网格。

输出解释：

```text
Stage1 = pass
```

含义是：数据契约、时间、空间字段足够稳定，可以进入 Stage2。它不表示原始观测没有噪声，也不表示后续不需要 QC。

## 2. Stage2：多源观测组织与体素化

Stage2 入口：

```text
stage/centralized_v1/core/centralized_stage2_multimodal.py
```

当前稳定输入：

```text
stage1_output/clean_wind.parquet
stage1_output/clean_loc.parquet
stage1_output/radar_index.json
radar_index.json.radar_path 指向的 radar PNG
```

当前全量输出：

```text
centralized_v1_output/stage2_full_v2/stage2_multimodal_summary.json
```

### 2.1 选择目标雷达帧

对每个 usable radar frame，取目标时间：

```text
T = radar frame timestamp
```

Stage2 围绕 `T` 组织该帧的所有相关观测。

文献借用点：

| 文献/资料 | 借用内容 | 在本项目中的用法 |
| --- | --- | --- |
| ECMWF IFS / ERA5 4D-Var | 数据同化使用有限时间窗，而不是无限历史。 | Stage2 使用 current/context 两个时间窗组织观测。 |

### 2.2 划分 current window 和 context window

时间窗：

```text
current window = [T - 5 min, T + 5 min]
context window = [T - 360 min, T + 360 min]
context excludes abs(delta_time_minutes) <= 5 min
```

意义：

| 记录类型 | 时间窗 | 作用 |
| --- | --- | --- |
| `wind_records` | current | Stage4 holdout truth 候选 |
| `context_wind_records` | context | 背景/上下文风观测，可参与 Stage4 融合 |
| `loc_records` | current | 当前轨迹覆盖 |
| `motion_records` | current | 当前飞机运动诊断 |
| `context_motion_records` | context | 历史飞机运动诊断 |

文献借用点：

| 文献/资料 | 借用内容 | 在本项目中的用法 |
| --- | --- | --- |
| ECMWF IFS / ERA5 4D-Var | 观测围绕分析时刻进入有限同化窗口。 | `current +/-5 min` 和 `context +/-6 h` 是显式时间组织。 |

### 2.3 将地理坐标映射到 3D 体素

当前网格：

```text
lat: 12.2 - 54.2
lon: 73.0 - 135.0
alt: 0 - 15000 m
vertical step: 500 m
grid shape: 31 x 525 x 775
```

映射公式：

```text
delta_lat = (LAT_MAX - LAT_MIN) / radar_h
delta_lon = (LON_MAX - LON_MIN) / radar_w

x = floor(((lon_clean - LON_MIN) / delta_lon) / xy_downsample)
y = floor(((LAT_MAX - lat_clean) / delta_lat) / xy_downsample)
z = floor((alt_meters - ALT_MIN) / alt_step_m)
```

解释：Stage2 把不规则飞机点和二维雷达图组织到统一三维网格，但不声称每个网格都有真实风。

文献借用点：

| 文献/资料 | 借用内容 | 在本项目中的用法 |
| --- | --- | --- |
| WeatherBench2 / GraphCast / FourCastNet / Aurora | 天气模型常以规则格点组织多变量状态。 | Stage2 借用 gridded multivariate state 的组织方式，不借用它们的训练目标。 |

### 2.4 聚合 current wind：`wind_records`

步骤：

1. 取 `clean_wind` 中 `T +/-5 min` 的 aircraft wind。
2. 按 `(z,y,x)` 分组。
3. 计算每个 voxel 的 `u/v`、`obs_count`、`obs_conf`。
4. 写入 `wind_records`。

作用：

```text
wind_records = Stage4 strict holdout candidate
```

文献借用点：

| 文献/资料 | 借用内容 | 在本项目中的用法 |
| --- | --- | --- |
| WMO aircraft observations | aircraft wind 可作为气象风观测。 | `wind_records` 是唯一 official truth 候选。 |
| de Haan / EMADDC | aircraft wind 有误差，需要 QC 分层。 | 后续报告区分 observation error 和 reconstruction error。 |

### 2.5 聚合 context wind：`context_wind_records`

步骤：

1. 取 `clean_wind` 中 `T +/-360 min` 的 aircraft wind。
2. 排除 current window。
3. 计算时间置信度：

```text
time_conf = 0.5 ** (abs(delta_time_minutes) / 180)
```

4. 对每个 voxel 做加权平均：

```text
u = sum(u_wind * obs_conf * time_conf) / sum(obs_conf * time_conf)
v = sum(v_wind * obs_conf * time_conf) / sum(obs_conf * time_conf)
```

作用：

```text
context_wind_records = Stage4 background/context observations
```

它可以参与融合，但不是 official truth。

文献借用点：

| 文献/资料 | 借用内容 | 在本项目中的用法 |
| --- | --- | --- |
| ECMWF IFS / ERA5 4D-Var | 时间窗内不同时间观测影响分析场。 | `time_conf` 给旧观测衰减权重。 |
| Desroziers diagnostics | 可用 departure 行为调观测/背景权重。 | Stage4 后续用 departure 调 `context_time_conf_power`。 |

### 2.6 聚合 location / motion

`loc_records` 步骤：

1. 取 current-window location。
2. 映射到 `(z,y,x)`。
3. 统计 trajectory density。

`motion_records` 步骤：

1. 取 current-window location。
2. 使用 Stage1 的 `u_motion/v_motion`。
3. 按 `(z,y,x)` 聚合平均 motion 和 `motion_count`。

解释：

```text
loc_records = aircraft coverage
motion_records = aircraft kinematics
```

它们不是 atmospheric wind truth。

文献借用点：

| 文献/资料 | 借用内容 | 在本项目中的用法 |
| --- | --- | --- |
| WMO aircraft observations | 区分时间/位置/飞机状态/气象变量。 | location 和 motion 只做覆盖和运动诊断。 |
| EMADDC 2025 | 缺少 air vector 不能直接由 ground vector 得风。 | 防止把 `u_motion/v_motion` 当 wind label。 |

### 2.7 读取 radar PNG 为 `cloud_2d`

步骤：

1. 从 `radar_index.json.radar_path` 读取 PNG。
2. OpenCV 灰度解码：

```text
radar_img = cv2.imdecode(file_bytes, cv2.IMREAD_GRAYSCALE)
cloud_2d = radar_img[::4, ::4]
```

3. 与 Stage2 水平网格对齐。

解释：`cloud_2d` 是雷达/云图强度 context，不是风速、风向、径向速度。

文献借用点：

| 文献/资料 | 借用内容 | 在本项目中的用法 |
| --- | --- | --- |
| OpenCV docs | 灰度图读取和图像下采样。 | 构建 radar/cloud 2D context。 |
| PyDDA / dual-Doppler | 真风场雷达反演需要 Doppler velocity。 | 说明 radar PNG intensity 不可当 wind truth。 |

### 2.8 Stage2 输出

每帧输出：

```text
multimodal voxel .npz
stage2_multimodal_summary.json
slice PNG / stats CSV / point CSV
integrity audit
```

Stage2 的结论：

```text
Stage2 = all-in observation organization
not final wind reconstruction
```

## 3. Stage3：Ground Center 中心化接入与置信度打包

Stage3 入口：

```text
stage/centralized_v1/core/centralized_stage3_center.py
```

当前稳定输出：

```text
centralized_v1_output/stage3_full_v2_25w_payload_only/stage3_center_summary.json
```

### 3.1 读取 Stage2 `.npz`

Stage3 对每个 Stage2 frame 读取：

```text
wind_records
context_wind_records
loc_records
motion_records
context_motion_records
cloud_2d
metadata
```

它不重新清洗原始数据，也不做最终风场重构。

### 3.2 定义 Ground Center

Ground Center 是逻辑中心：

```text
Ground Center = centralized server / receiver
```

它不是物理站点坐标，不按通信距离过滤观测。

文献/资料借用点：

| 文献/资料 | 借用内容 | 在本项目中的用法 |
| --- | --- | --- |
| 中心化数据同化/观测处理思想 | 所有观测先汇入中心端，再统一分析。 | Stage3 构造 star-topology payload，而不是 Air-to-Air 通信。 |

### 3.3 按 flight_id 聚合 agent

步骤：

1. 读取 current-window `loc_records` / `flight_raw_records`。
2. 按 `flight_id` 分组。
3. 计算 agent 位置：

```text
agent_lat = median(lat_clean)
agent_lon = median(lon_clean)
agent_alt = median(alt_meters)
agent_time = max(time_utc)
```

4. 写入 agent payload。

作用：表示每架飞机在该帧的观测载体状态，用于 Ground Center 接收和诊断。

### 3.4 打包观测角色

Stage3 payload 中保留清晰角色：

| payload group | 来自 Stage2 | 用途 |
| --- | --- | --- |
| `label_candidates` | `wind_records` | Stage4 holdout truth 候选 |
| `context_wind_observations` | `context_wind_records` | Stage4 背景/上下文风 |
| `trajectory_observations` | `loc_records` | 覆盖诊断 |
| `motion_observations` | `motion_records` | 飞机运动诊断 |
| `context_motion_observations` | `context_motion_records` | 历史运动诊断 |
| `confidence_package` | Stage2 confidence fields | 新鲜度、密度、质量诊断 |

关键边界：

```text
label_candidates can become truth
motion_observations cannot become wind truth
```

文献借用点：

| 文献/资料 | 借用内容 | 在本项目中的用法 |
| --- | --- | --- |
| WMO aircraft observations | 位置、时间、气象值、飞机状态要区分。 | Stage3 保留 observation roles，不混成一类风。 |
| EMADDC 2025 | aircraft-derived weather observations 要有 QC 和角色管理。 | 支持 `confidence_package` 和后续 QC 分层。 |

### 3.5 Stage3 置信度

agent freshness：

```text
agent_delta_time_minutes = abs(agent_time - target_time)
agent_time_conf = exp(-0.12 * agent_delta_time_minutes)
agent_space_conf = 1.0
agent_joint_conf = agent_time_conf
```

解释：

```text
dt=0 min -> 1.000
dt=1 min -> 0.887
dt=5 min -> 0.549
```

`space_conf=1.0` 是因为 Ground Center 是逻辑中心；空间权重应留到 Stage4 对目标 voxel 计算。

文献借用点：

| 文献/资料 | 借用内容 | 在本项目中的用法 |
| --- | --- | --- |
| ECMWF / ERA5 finite-window assimilation | 时间新鲜度影响观测可用性。 | Stage3 把 freshness 作为诊断包保留。 |
| DART/Gaspari-Cohn localization | 空间 localization 应针对 target state。 | Stage3 不用 reference center 做空间删选。 |

## 4. Stage4：strict holdout 风场重构与评估

Stage4 入口：

```text
stage/centralized_v1/core/centralized_stage4_ground_recon.py
stage/centralized_v1/core/centralized_stage4_sensitivity.py
stage/centralized_v1/core/centralized_report_stage4_slices.py
```

### 4.1 选择待评估帧和方法

Stage4 可以跑：

```text
single / representative frames -> full NPZ + PNG
200-frame metrics-only -> 方法比较
5614 strict holdout frames -> 大样本正式验证
```

当前展示包中的三组方法：

| 方法 | 角色 |
| --- | --- |
| `baseline_aircraft` | 最初纯航空器宽核 baseline |
| `adaptive_v3` | 诊断加权 + adaptive localization |
| `tp26_thr11_preserve` | 最新 200 帧最佳候选：加强时间衰减 + 垂直结构保护 |

### 4.2 从 `wind_records` 中选择 holdout

步骤：

1. 读取 Stage2 frame `.npz`。
2. 取 current `wind_records`。
3. 按规则抽出 holdout。
4. 把 holdout 从融合输入里移除。
5. 保存 `holdout_records_json` 供审计。

泄漏检查：

```text
strict_holdout_no_leakage = True
motion_used_as_wind = False
train_holdout_overlap_count = 0
```

文献借用点：

| 文献/资料 | 借用内容 | 在本项目中的用法 |
| --- | --- | --- |
| WMO aircraft observations | aircraft wind 是有效气象观测。 | 只有 aircraft `wind_records` 可成为 official truth。 |
| de Haan / EMADDC | aircraft wind 有观测误差，但仍是独立观测源。 | 用 strict holdout 验证重构，不用背景场当答案。 |

### 4.3 构建融合观测

允许输入：

```text
train_current_wind = wind_records - holdout
context_wind_records
```

禁止输入：

```text
holdout wind_records
motion_records as wind
context_motion_records as wind
CMA/GFS/ERA as truth
```

基本 active weight：

```text
active_weight = obs_conf * time_conf * localization
```

`diagnostic_weighted` 模式进一步乘上：

```text
density_conf_factor
speed_qc_conf_factor
local_consistency_conf_factor
```

文献借用点：

| 文献/资料 | 借用内容 | 在本项目中的用法 |
| --- | --- | --- |
| EMADDC 2025 | aircraft weather observations 需要 QC。 | density/speed/local consistency 进入 diagnostic weighting。 |
| de Haan 2016 | aircraft-derived wind 可估计 observation error。 | sigma 只做观测误差参考，不直接修正 RMSE。 |

### 4.4 target-voxel localization

对每个目标 voxel，计算观测到目标的距离权重。

Gaussian localization：

```text
localization = exp(-0.5 * ((dx/sigma_xy)^2 + (dy/sigma_xy)^2 + (dz/sigma_z)^2))
```

baseline：

```text
radius/sigma = 12/6, z=2/1
```

adaptive_v3 / tp26：

```text
candidate grid = 8:4,10:5
selection uses non-holdout diagnostics only
```

非泄漏 adaptive 特征包括：

```text
current wind support
context wind support
context time_conf
local consistency
role gap
obs_error_weight diagnostic
```

不能使用：

```text
holdout RMSE
holdout MAE
holdout residual
```

文献借用点：

| 文献/资料 | 借用内容 | 在本项目中的用法 |
| --- | --- | --- |
| Gaspari and Cohn 1999 / DART | localization 是数据同化核心，观测影响应随 target distance 衰减。 | 从固定宽核走向 adaptive localization。 |
| Weather data assimilation practice | 不同支撑条件下需要不同 localization。 | `adaptive_v3` 用非 holdout 诊断选核。 |

### 4.5 role conflict 与时间权重

问题：current aircraft wind 和 context wind 可能冲突。

`current_priority_adaptive` 做法：

```text
if current/context overlap and wind component gap is high:
    protect current anchors
    downweight or remove conflicting context contribution
```

时间衰减：

```text
context_time_conf_power = 1.5  # adaptive_v3
context_time_conf_power = 2.6  # tp26
```

解释：`tp26` 对旧 context 衰减更强，减少 stale context 拉偏。

文献借用点：

| 文献/资料 | 借用内容 | 在本项目中的用法 |
| --- | --- | --- |
| Desroziers et al. 2005 | 用 observation/background departure 诊断观测和背景权重。 | 微调 context time decay 和 role conflict 阈值。 |
| ECMWF / ERA5 time-window assimilation | 背景/观测随时间窗口组织。 | context wind 不是同步 truth，必须时间衰减。 |

### 4.6 重构风场与物理 proxy

Stage4 先把带权观测累积到三维网格：

```text
recon_u = weighted mean u
recon_v = weighted mean v
recon_conf = accumulated confidence
recon_mask = confidence > threshold
```

`pydda_3dvar_proxy` 进一步加入：

```text
observation anchoring
masked neighbor smoothness
weak horizontal divergence reduction
speed plausibility clipping
```

重要边界：这只是 aircraft-observation proxy，不是真 PyDDA Doppler retrieval，也不是训练好的 PINN/diffusion。

文献借用点：

| 文献/资料 | 借用内容 | 在本项目中的用法 |
| --- | --- | --- |
| PyDDA / 3DVAR | 三维风场反演同时考虑观测约束、平滑、弱物理约束。 | `pydda_3dvar_proxy` 做观测锚定和平滑/散度 proxy。 |
| PINN 文献 | 物理约束可写入损失或正则。 | 当前只是 proxy refine，不宣称已训练 PINN。 |

### 4.7 垂直结构保护：`preserve_strong_layers`

`tp26_thr11_preserve` 开启：

```text
vertical_risk_mode = preserve_strong_layers
vertical_gradient_preserve_weight = 0.12
vertical_context_mismatch_damping = 0.35
```

目的：

1. 识别强风、垂直失配、垂直过平滑候选体素。
2. 在这些区域降低跨高度层过度扩散。
3. 尽量保留强风层和垂直梯度。

文献借用点：

| 文献/资料 | 借用内容 | 在本项目中的用法 |
| --- | --- | --- |
| Perona and Malik 1990 | edge-preserving / gradient-preserving smoothing。 | `preserve_strong_layers` 借用保梯度思想。 |
| PyDDA / 3DVAR | 平滑约束不能抹掉真实强梯度结构。 | 垂直结构保护作为 smoothness 的反向约束。 |

### 4.8 点位评估和分层报告

对每个 holdout 点：

```text
gt_u, gt_v = removed aircraft wind truth
pred_u, pred_v = reconstructed wind at same voxel
u_error = pred_u - gt_u
v_error = pred_v - gt_v
vector_error = sqrt(u_error^2 + v_error^2)
```

报告指标：

```text
frame RMSE / MAE
holdout-point weighted RMSE / MAE
median / P90 / P95 / P99 / max
height bins
single vs multi holdout
strong wind subset
vertical mismatch subset
role conflict subset
tail audit
```

文献借用点：

| 文献/资料 | 借用内容 | 在本项目中的用法 |
| --- | --- | --- |
| Janjic et al. 2018 | representation error：点观测与模型网格/时间窗不完全等价。 | 把 aircraft obs error 与 500 m 网格/6 min 重构误差分开解释。 |
| de Haan / EMADDC | aircraft wind observation sigma 是观测误差参考。 | normalized error 可用于诊断，但不能从 RMSE 里扣除 sigma。 |

### 4.9 可视化

Stage4 可视化入口：

```text
stage/centralized_v1/core/centralized_report_stage4_slices.py
```

当前展示包可视化：

```text
visuals/baseline_aircraft/
visuals/adaptive_v3/
visuals/tp26_thr11_preserve/
```

图像解释：

```text
slices.png = 水平/垂直切片、风速、矢量、recon bbox
diagnostics.png = 有效重构、低置信补全、强风/垂直结构等诊断
gray/pale outside recon_mask = no wind claim, not zero wind
```

文献借用点：

| 文献/资料 | 借用内容 | 在本项目中的用法 |
| --- | --- | --- |
| PyDDA / variational retrieval practice | 风场反演需要同时检查风场、约束和诊断，不只看一个平均 RMSE。 | 代表帧 slices + diagnostics 一起展示。 |

## 5. 方法与文献逐项对照

本节是给老师看的“方法旁注版”。它的口径是：我们没有把某一篇文献的完整模型原样搬进来，而是把文献中的某个成熟思想放到 `centralized_v1` 的飞机观测重构场景里。正式精度只看 Stage4 current aircraft `wind_records` strict holdout；CMA/GFS/ERA、PINN、Diffusion 都不能当 truth。

### 5.1 已进入 Stage4 展示包的三组方法

| 方法 | 在流程中的位置 | 输入 | 处理步骤 | 输出 | 旁边要标的文献 | 借用的是文献哪一部分 | 汇报边界 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `baseline_aircraft` | Stage4 最初对照组。 | `train_current_wind`, `context_wind_records`。 | 1. 抽出 holdout；2. holdout 从融合输入移除；3. 用固定宽核 Gaussian localization；4. 按 `obs_conf*time_conf*localization` 加权平均；5. 做基础 proxy refine。 | `recon_u/v/conf/mask`, holdout point RMSE/MAE。 | WMO aircraft observations；de Haan and Stoffelen 2016；EMADDC 2025；Gaspari-Cohn/DART。 | WMO 借用 aircraft wind 是气象观测来源；de Haan/EMADDC 借用 aircraft wind 需要 QC 和误差意识；Gaspari-Cohn/DART 借用观测影响随距离衰减。 | 这是最初纯航空器 baseline，不是最终方法；宽核容易把旧 context 或远处观测带进局地强变化。 |
| `adaptive_v3` | Stage4 主体升级版。 | 同 baseline，但增加非 holdout 诊断字段。 | 1. 诊断加权；2. current/context role conflict 检查；3. 在 `8:4,10:5` candidate grid 中选 localization；4. 用 `pydda_3dvar_proxy` 做观测锚定、平滑和弱散度 proxy。 | 更稳定的三维风场和分层误差表。 | Gaspari-Cohn/DART；PyDDA / 3DVAR；EMADDC 2025；Desroziers et al. 2005。 | localization 文献借用“局地相关半径要随支撑条件变化”；PyDDA/3DVAR 借用观测项、平滑项、弱物理项联合约束；EMADDC 借用 QC-aware weighting；Desroziers 借用 departure 诊断调权思想。 | adaptive 选择不能看 holdout 误差，只能看非答案诊断；否则就是泄漏。 |
| `tp26_thr11_preserve` | 当前展示包最新候选。 | `adaptive_v3` 同源输入。 | 1. 把 `context_time_conf_power` 调到 `2.6`；2. 把 conflict threshold 调到 `11`；3. 开启 `preserve_strong_layers`；4. 保留强垂直梯度，减少跨层过平滑。 | 当前 200 帧 strict holdout 最优候选：weighted RMSE 从 baseline `18.918 m/s` 降到 `14.769 m/s`。 | Desroziers et al. 2005；Perona and Malik 1990；Janjic et al. 2018；PyDDA / 3DVAR。 | Desroziers 借用 departure 诊断调时间/背景权重；Perona-Malik 借用保边/保梯度平滑；Janjic 借用 representation error 解释点观测和 500 m 网格/时间窗差异；PyDDA 借用平滑不能压掉真实结构的思想。 | 这是 200 帧候选最佳，不等于已完成全量 5614 帧最终定版；极端长尾帧仍需单独治理。 |

### 5.2 历史主线和背景方法的正确定位

| 方法/分支 | 在项目中的角色 | 输入 | 处理步骤 | 输出 | 旁边要标的文献 | 借用的是文献哪一部分 | 不能怎么说 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `TimePower15` | 传统 Stage4 主线/历史强 baseline；用于和 adaptive 系列对照。 | current train wind、context wind、time confidence、localization。 | 1. 保持 aircraft-only strict holdout；2. 对 context wind 做时间衰减；3. 用经验 localization 和 proxy refine 生成三维风场；4. 只在有 holdout 帧算正式误差。 | full_v2 / best adaptive 历史结果、no-holdout 业务重构结果。 | ECMWF / ERA5 4D-Var；Gaspari-Cohn/DART；WMO/de Haan/EMADDC。 | ECMWF 借用有限时间窗和观测新鲜度；Gaspari-Cohn 借用空间局地化；aircraft 文献借用飞机风作为唯一 strict truth。 | 不能把 no-holdout 置 0 混入 RMSE；不能把 TimePower15 说成运行级风切变预警系统。 |
| CMA/GFS/ERA 背景层 | 背景场、弱先验、条件输入。 | 再分析/预报格点场、Stage4 recon mask、aircraft anchors。 | 1. 插值到 Stage2/Stage4 网格；2. 作为 background 或 condition；3. 用 aircraft holdout 检验是否真的帮助。 | background feature、proxy prior、对照分支。 | ECMWF / ERA5 documentation；CMA-RA/再分析资料说明；3DVAR/OI 文献。 | 借用数值天气背景场作为 prior 的思想；借用 background/innovation 的同化表达。 | 不能当 truth；不能用和 CMA 一致来证明 aircraft reconstruction 精度。 |
| `cma_ra_virtual_radial_3dvar` | CMA 弱背景 + 虚拟径向速度的实验分支。 | CMA u/v/w、radar geometry proxy、aircraft anchors、Stage4 prior。 | 1. 把 CMA 风场插到项目网格；2. 按雷达视线几何构造 synthetic radial velocity；3. 用 3DVAR/PyDDA 风格约束重构；4. 和 aircraft holdout 对照。 | class-PyDDA / 3DVAR proxy product。 | PyDDA / 3DVAR；Doppler radar wind retrieval 文献；ECMWF/CMA background。 | 借用径向速度约束、观测项、平滑项、弱散度项；借用背景场作 first guess。 | 这是 proxy，不是真双多普勒观测；CMA 不是真实 6 min 对流突变答案。 |
| PINN residual refine | 后续残差修正路线，不是当前 Stage4 truth。 | TimePower15/adaptive wind、confidence、mask、vertical mismatch、CMA/radar context。 | 1. 预测 `delta_u/delta_v`；2. 在损失中加入散度、平滑、垂直一致性等物理残差；3. 用 aircraft holdout 做监督/验证。 | deterministic residual correction。 | Raissi et al. 2019 PINN；PyDDA / variational constraints。 | 借用“物理方程/残差写进神经网络损失函数”的思想。 | 不能说已经有训练好的 PINN 主模型；也不能用 CMA 当监督真值。 |
| Diffusion local tail repair | 后续长尾和不确定性路线。 | TimePower15/adaptive residual、uncertainty、strong-wind/tail masks、radar/CMA condition。 | 1. 条件式生成局地残差候选；2. 重点处理强对流、稀疏支撑和长尾误差；3. 输出不确定性或 ensemble。 | local residual samples、uncertainty map。 | Ho et al. 2020 DDPM；Song et al. 2021 score-based SDE。 | 借用“从噪声逐步去噪生成样本”和“用条件信息约束生成分布/不确定性”的思想。 | 不能全场替代 TimePower15 主干；不能无 holdout 自证精度。 |
| `wind_shear_risk_head` | 后续独立航空风险头。 | Stage4 wind、vertical gradient、strong-layer diagnostics、confidence。 | 1. 从重构风场提取垂直跃变和风险特征；2. 单独输出 wind shear risk；3. 与 Stage4 RMSE 分开评估。 | risk score / risk mask。 | ICAO Doc 9817；Janjic representation error；WMO aircraft obs。 | 借用低空风切变 warning/risk 应独立定义和分级的思想；借用 representation error 说明尺度不同。 | 不能把 500 m Stage4 点位 RMSE 直接等价为 30 m 风切变阈值。 |

### 5.3 一句话讲清主线

```text
Stage1/2/3 负责把 aircraft wind、location、motion、radar context 分角色组织好；
Stage4 只用被拿掉的 current aircraft wind_records 做 truth；
baseline -> adaptive_v3 -> tp26 是 aircraft-only strict holdout 主线；
CMA/PINN/Diffusion 只能做背景、残差或不确定性，不改变 truth 定义。
```

## 6. 当前展示包中的结果位置

Stage4 三组展示结果：

```text
centralized_v1_output/stage4_teacher_showcase_20260602_baseline_adaptive_v3_tp26/README.md
centralized_v1_output/stage4_teacher_showcase_20260602_baseline_adaptive_v3_tp26/recon/
centralized_v1_output/stage4_teacher_showcase_20260602_baseline_adaptive_v3_tp26/visuals/
centralized_v1_output/stage4_teacher_showcase_20260602_baseline_adaptive_v3_tp26/tables/
```

Stage2 / Stage3 稳定输入：

```text
centralized_v1_output/stage2_full_v2/stage2_multimodal_summary.json
centralized_v1_output/stage3_full_v2_25w_payload_only/stage3_center_summary.json
```

Stage4 最新候选来源：

```text
centralized_v1_output/stage4_error_resolution_micro_grid_20260602_12w/reports/micro_grid_summary.md
```

## 7. 讲给老师时的推荐顺序

1. 先说项目目标：用中心化 Ground Center 汇聚飞机/雷达上下文，重构三维风场。
2. 讲 Stage1：原始数据统一成 wind/location/radar index；特别强调 motion 不是 wind。
3. 讲 Stage2：用 current/context window 和 31x525x775 网格组织多源观测；不做风场重构。
4. 讲 Stage3：Ground Center 只是逻辑接收端，按 flight agent 和 observation role 打包。
5. 讲 Stage4：只用 aircraft wind holdout 做 truth，先拿掉答案，再重构，再比较。
6. 讲方法演进：`baseline_aircraft` -> `adaptive_v3` -> `tp26_thr11_preserve`，分别对应 localization、3DVAR proxy、departure diagnostics、vertical preserve。
7. 补一句历史和后续：`TimePower15` 是传统主线 baseline；CMA/PINN/Diffusion 是后续背景/残差/不确定性路线，不是 truth。
8. 讲限制：Stage4 是稀疏 aircraft wind reconstruction，不是 30 m operational low-level wind-shear warning system。

## 8. 参考文献清单与借用口径

- WMO Aircraft-Based Observations Programme  
  https://wmo.int/aircraft-based-observations-programme
  - 借用口径：aircraft wind 是正式气象观测来源；本项目据此把 current aircraft `wind_records` 作为 strict holdout truth 候选。
- de Haan, S. and Stoffelen, A. (2016), AMT  
  https://amt.copernicus.org/articles/9/4141/2016/
  - 借用口径：aircraft-derived wind 有观测误差和质量控制问题；本项目用它解释 observation error，不用它把重构 RMSE 合理化。
- EMADDC aircraft weather observations and quality control (2025), AMT  
  https://amt.copernicus.org/articles/18/3341/2025/
  - 借用口径：业务 aircraft weather observations 需要 QC 和误差分层；本项目据此使用 diagnostic weighting、speed QC、local consistency。
- ECMWF IFS / ERA5 4D-Var documentation  
  https://www.ecmwf.int/en/publications/ifs-documentation  
  https://confluence.ecmwf.int/display/CKB/ERA5%3A%2Bdata%2Bdocumentation
  - 借用口径：有限时间窗、背景场、观测新鲜度和 background/innovation 思想；本项目用在 current/context window 和 CMA/GFS/ERA 弱背景解释。
- DART covariance localization / Gaspari-Cohn localization  
  https://docs.dart.ucar.edu/en/latest/assimilation_code/modules/assimilation/cov_cutoff_mod.html
  - 借用口径：观测影响随空间距离衰减，且 localization 半径可影响分析结果；本项目用在 Gaussian/Gaspari-Cohn/adaptive localization。
- WeatherBench2 data guide  
  https://weatherbench2.readthedocs.io/en/latest/data-guide.html
  - 借用口径：规则格点多变量天气状态组织；本项目只借用 gridded state 组织方式，不借用其训练任务。
- OpenCV image I/O documentation  
  https://docs.opencv.org/4.x/
  - 借用口径：PNG 灰度读取和下采样；本项目用来把 radar mosaic 读成 `cloud_2d` context，不把图像强度当风速。
- PyDDA documentation / JORS paper  
  https://openradarscience.org/PyDDA/  
  https://openresearchsoftware.metajnl.com/articles/10.5334/jors.264
  - 借用口径：三维风场反演中的观测约束、平滑约束、弱散度/物理约束；本项目实现的是 aircraft-observation proxy，不是真 Doppler retrieval。
- Desroziers et al. (2005) observation/background diagnostics  
  https://doi.org/10.1256/qj.05.108
  - 借用口径：用 observation/background departure 诊断误差和权重；本项目用在 context time decay、role conflict、obs-error diagnostic 调参解释。
- Janjic et al. (2018) representation error  
  https://doi.org/10.1002/qj.3130
  - 借用口径：点观测与模型网格/时间窗之间存在 representation error；本项目用来区分 aircraft observation error 和 500 m 网格重构误差。
- Perona and Malik (1990) anisotropic diffusion  
  https://doi.org/10.1109/34.56205
  - 借用口径：保边/保梯度平滑；本项目用在 `preserve_strong_layers`，避免强垂直结构被跨层平滑抹掉。
- Raissi, Perdikaris and Karniadakis (2019), Physics-informed neural networks  
  https://doi.org/10.1016/j.jcp.2018.10.045
  - 借用口径：物理方程/残差进入神经网络损失；本项目只作为后续 residual refine 设想，不宣称当前 Stage4 已训练 PINN。
- Ho, Jain and Abbeel (2020), Denoising Diffusion Probabilistic Models  
  https://arxiv.org/abs/2006.11239
  - 借用口径：逐步加噪/去噪生成样本；本项目只把它放在后续局地长尾残差和不确定性分支。
- Song et al. (2021), Score-based generative modeling through stochastic differential equations  
  https://research.google/pubs/score-based-generative-modeling-through-stochastic-differential-equations/
  - 借用口径：score-based / SDE 生成框架和不确定性采样；本项目不把 diffusion 当全场主干替代。
- ICAO Doc 9817, Manual on Low-Level Wind Shear and Turbulence  
  https://store.icao.int/en/manual-on-low-level-wind-shear-and-turbulence-doc-9817
  - 借用口径：低空风切变 warning/risk 需要独立定义和业务口径；本项目据此把 `wind_shear_risk_head` 与 Stage4 点位 RMSE 分开。
