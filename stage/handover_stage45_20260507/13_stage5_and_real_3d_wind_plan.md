# Stage5 PINN/Diffusion Scaffold 与真实三维风场数据需求

## 这份文档的作用
这份文档补充两件事：

- 当前已经新增的 Stage4 地理坐标可视化脚本
- 当前已经新增的 Stage5 v1 独立 refinement 脚本

重点边界：

- 不把当前结果包装成“全国完整三维风场”
- 当前应表述为“全国雷达网格上的稀疏局部三维风场重构”
- Stage5 不污染已冻结 Stage4 主链
- PINN / diffusion 先作为 Stage5 独立模块推进

---

## 一、真实地理坐标可视化

新增脚本：

```text
stage/report_stage4_geo_wind_visualization.py
```

默认输入：

```text
/data/LFT-W02_data/pengxu/stage4_output_v2
```

默认输出：

```text
/data/LFT-W02_data/pengxu/stage4_visualizations/stage4_output_v2_geo_representative
```

该脚本只读 Stage4 sparse fields 和 `radar_2d`：

```text
recon_idx
recon_u_val
recon_v_val
recon_conf_val
recon_mask_val
radar_2d
```

地理映射固定为：

```text
lat = 54.2 - (y + 0.5) * (54.2 - 12.2) / H
lon = 73.0 + (x + 0.5) * (135.0 - 73.0) / W
alt_km = z * 0.5
```

当前已生成：

```text
/data/LFT-W02_data/pengxu/stage4_visualizations/stage4_output_v2_geo_representative
```

输出内容：

- `selected_frames_geo.json`
- 9 个非空代表帧，每帧 3 张 PNG
- 2 个空重构帧只写入 JSON，不生成误导性风场图

每个非空代表帧包含：

- `*_country_roi.png`：全国雷达背景 + ROI 框 + 稀疏重构点
- `*_roi_layers.png`：ROI 内多高度层风矢量
- `*_roi_3d.png`：ROI 内经纬度 / 高度 3D 风矢量

推荐命令：

```bash
/opt/miniconda3/bin/python stage/report_stage4_geo_wind_visualization.py \
  --stage4-dir /data/LFT-W02_data/pengxu/stage4_output_v2 \
  --summary /data/LFT-W02_data/pengxu/stage4_output_v2/stage4_summary.json \
  --out-dir /data/LFT-W02_data/pengxu/stage4_visualizations/stage4_output_v2_geo_representative \
  --selection representative
```

解释边界：

- 全国图只表达雷达网格范围和 ROI 位置
- 风矢量只在实际 sparse 重构点附近展示
- 不做全国范围无约束插值
- 不把稀疏点硬说成全国满场

---

## 二、真实三维风场还需要哪些数据

如果目标是更真实的三维风场，而不仅是 Stage4 sparse reconstruction 的可视化，需要额外数据约束。

### 1. 三维大气背景场
优先级最高。需要一个能覆盖同一时空范围的模式或再分析资料，例如：

- ERA5 pressure-level / model-level 风场
- GFS / ECMWF / CMA 数值预报场
- HRRR 类高分辨率模式资料，如果有中国区域对应产品

至少需要：

```text
u wind
v wind
w wind 或 vertical velocity
temperature
pressure / geopotential height
relative humidity
time
lat/lon grid
vertical levels
```

用途：

- 给 Stage5 提供三维背景先验
- 约束稀疏观测之外的大范围风场形态
- 避免把局部观测任意扩散成全国风场

### 2. 雷达三维产品
当前 Stage4 主要使用的是二维雷达拼图底板。若要更真实的三维风场，最好有：

- 多仰角体扫雷达资料
- 径向速度 `radial velocity`
- 反射率 `reflectivity`
- 谱宽 `spectrum width`
- 雷达站点经纬高、扫描仰角、方位角、距离库

用途：

- 约束低空 / 对流系统附近的风场结构
- 支持速度退模糊、径向速度到水平风的反演
- 让三维可视化不仅是二维雷达底图上的 sparse wind

### 3. 更多直接风观测
当前已有 wind / AMDAR / turbulence / flight motion 相关输入。若能补充会更好：

- 探空资料
- 风廓线雷达
- 地面自动站风
- GNSS 掩星或其他垂直廓线资料
- 机场 METAR / TAF 观测

用途：

- 约束不同高度层
- 检验 Stage5 refinement 是否真的变好
- 给 held-out validation 留出独立样本

### 4. 地理与投影元数据
当前经纬度映射使用固定 bbox：

```text
lat: 12.2 到 54.2
lon: 73.0 到 135.0
```

如果要严谨论文级地图，需要确认：

- 雷达拼图真实投影方式
- 每个像素对应经纬度是否线性
- 是否有 Lambert / Mercator / 等经纬投影信息
- 是否有海岸线、省界或国界矢量底图

用途：

- 避免地图位置偏移
- 让 ROI 图能叠加真实行政区或地形

### 5. 评估标签
Stage5 不能只看图“更满”。需要独立验证：

- held-out AMDAR / wind observations
- direct agreement
- divergence / smoothness
- temporal consistency
- forecast next-step error
- hazard event consistency

---

## 三、Stage5 v1 独立脚本

新增脚本：

```text
stage/stage5_pinn_diffusion_refine.py
```

默认输入：

```text
/data/LFT-W02_data/pengxu/stage4_output_v2
```

默认输出：

```text
/data/LFT-W02_data/pengxu/stage5_output_v1
```

当前定位：

- 独立 Stage5 scaffold
- 只读 Stage4 sparse outputs
- 不覆盖 Stage4
- 不接入 `run_stage34_workflow_v2.sh`
- 输出 sparse ROI refinement
- 不是训练好的神经 diffusion 模型

当前方法：

- 读取 Stage4 sparse reconstruction
- 读取 direct source anchors：`wind / amdar / turb`
- 构建 ROI local volume
- 保持 direct anchors
- 做 diffusion-style 局部平滑
- 做 PINN-proxy divergence damping
- 输出 refined sparse values
- 写 `stage5_summary.json`

输出字段包括：

```text
storage_mode = stage5_roi_sparse_v1
method = pinn_proxy_diffusion_style_v1
grid_shape
bbox_zyx
local_shape
refined_idx
refined_u_val
refined_v_val
refined_conf_val
refined_divergence_val
refined_smoothness_val
anchor_idx
metrics_json
```

推荐小样本命令：

```bash
/opt/miniconda3/bin/python stage/stage5_pinn_diffusion_refine.py \
  --stage4-dir /data/LFT-W02_data/pengxu/stage4_output_v2 \
  --summary /data/LFT-W02_data/pengxu/stage4_output_v2/stage4_summary.json \
  --out-dir /data/LFT-W02_data/pengxu/stage5_output_v1_smoke \
  --selection frames \
  --frame-times 20260129174200,20260218211800 \
  --iterations 4 \
  --local-expand-iters 1 \
  --max-expand-voxels 1000 \
  --make-plots 1 \
  --max-plot-vectors 250
```

当前 smoke test 结果：

- `20260129174200` 成功输出 Stage5 NPZ 和 3D 预览图
- `20260218211800` 因 Stage4 空重构被跳过
- `20260129174200` 从 Stage4 `198` 个重构体素扩展到 Stage5 `326` 个 ROI refined 体素
- direct source anchors：`wind=50, amdar=50, turb=0`
- anchor RMSE after：约 `0.0957`
- 输出目录：`/data/LFT-W02_data/pengxu/stage5_output_v1_smoke`

---

## 四、Stage5 下一步建议

### 1. 不急着全量跑 Stage5
当前 Stage5 v1 是 scaffold，不是最终论文模型。建议先只跑代表帧：

- 高 coverage 帧
- 最大 hazard 帧
- 最大 anchor_restore 帧
- 中位 coverage 帧
- 空重构帧

### 2. 加入真实背景场后再做 learned diffusion
真正的 diffusion / PINN 应该输入：

- Stage4 sparse reconstruction
- direct anchors
- radar 2D / 3D products
- NWP / reanalysis 3D background
- topography / land-sea mask
- time embedding

输出：

- ROI refined `u/v/w`
- confidence / uncertainty
- physics residuals
- short-term forecast

### 3. 先定义验证协议
Stage5 是否更好，不能只看 coverage 或图像更满。必须同时看：

- held-out wind RMSE / MAE
- direct anchor preservation error
- divergence / smoothness
- temporal consistency
- hazard event consistency
- uncertainty calibration

### 4. 与 Stage4 论文主结果分开
建议论文表达：

- Stage4：稀疏多源风场重构主链
- Stage5：事件驱动、ROI 聚焦、物理约束 refinement / short-term forecast 原型

这样 Stage5 可以成为后续创新点，不会破坏 Stage4 已冻结的实验矩阵。

---

## 五、Stage5 实时化与外部背景场 v2 更新

当前新增的实现仍然不修改 Stage4 主链，重点从“把 Stage5 图做得更满”调整为：

```text
离线全量重构 + 在线事件驱动 ROI 增量重构
```

新增脚本：

```text
stage/download_stage5_era5_roi.py
stage/run_stage5_rolling_roi.py
stage/report_stage5_background_comparison.py
```

### 1. ERA5 ROI 背景场工具

`stage/download_stage5_era5_roi.py` 用于生成 keyframes 的 ERA5 pressure-level CDS 请求清单，并在配置好 CDS token 后下载 / 转换为 Stage5 可读的 ROI NPZ。

默认关键帧：

```text
20260124013600
20260129114200
20260129174200
20260205173000
20260206174200
20260222063600
```

默认 ROI：

```text
lat 17.0 到 37.0
lon 106.5 到 117.5
```

默认压力层：

```text
1000,975,950,925,900,875,850,800,750,700,600,500,400,300,250,225,200 hPa
```

默认变量：

```text
u_component_of_wind
v_component_of_wind
vertical_velocity
geopotential
temperature
```

先生成 manifest：

```bash
/opt/miniconda3/bin/python stage/download_stage5_era5_roi.py
```

配置好 `$HOME/.cdsapirc` 且安装 `cdsapi` 后再下载：

```bash
/opt/miniconda3/bin/python stage/download_stage5_era5_roi.py --download
```

如果已下载 NetCDF / GRIB，再转 Stage5 NPZ：

```bash
/opt/miniconda3/bin/python stage/download_stage5_era5_roi.py --convert-existing
```

注意：

- ERA5 是历史再分析背景场 / benchmark，不是实时业务输入。
- ERA5 有延迟和 ERA5T 修订问题，实时系统应使用 GFS、ECMWF Open Data 或 CMA-GFS 一类预报场。
- 本地当前未发现 `$HOME/.cdsapirc`，且两个 Python 环境都未安装 `cdsapi/xarray/cfgrib`，下载和转换前需要补依赖。

### 2. Stage5 指标与背景场接口增强

`stage/stage5_pinn_diffusion_refine.py` 当前已新增：

- `--background-dir`：读取 `era5_roi_<time_str>.npz` 或单个背景场 NPZ
- `--holdout-every`：把每 N 个 direct source anchor 留出做 held-out 验证
- `delta_speed_original_*` 与 `delta_speed_expanded_*`
- `heldout_anchor_rmse_after`
- `background_vector_rmse`
- `normalized_divergence_abs_mean_after`
- `normalized_smoothness_mean_after`
- `--hazard-conservative`：对高 hazard 帧降低 diffusion / PINN 强度和 original delta cap

当前 Stage5 结论仍应保守表达：

- 好帧如 `20260124013600`、`20260222063600` 能扩展 ROI sparse voxels，且 anchor RMSE 与物理 proxy 较低。
- 风险帧如 `20260206174200`、`20260205173000` 容易出现较大 delta speed / divergence / smoothness，不能宣称整体显著提升。

### 3. 实时化 rolling ROI 入口

`stage/run_stage5_rolling_roi.py` 是现有 Stage3/Stage4/Stage5 的轻量 orchestration helper。

它的原则：

- 不修改 Stage4 主重构逻辑
- 只处理指定新到帧 / 小批量帧
- Stage4 保持单进程时序顺序
- 默认跳过 full aux / 重报告 / 可视化重任务
- 可选跑 Stage5 ROI refinement

dry-run 示例：

```bash
/opt/miniconda3/bin/python stage/run_stage5_rolling_roi.py \
  --frame-indices 76,7041 \
  --run-label rolling_roi_smoke_v1 \
  --run-stage5 \
  --dry-run
```

真正实时化的下一步不是把 7395 帧反复全量重跑，而是：

1. Stage2/Stage3 对新增帧增量缓存
2. Stage4 只在事件触发 ROI 上顺序更新 `prev_recon_state`
3. Stage5 只对高风险 / 高价值 ROI 做 refinement
4. 报告、full aux、论文图统一放到离线批处理

### 4. Stage4 / Stage5 / 背景场并排可视化

新增：

```text
stage/report_stage5_background_comparison.py
```

默认输出：

```text
/data/LFT-W02_data/pengxu/stage5_visualizations/stage5_background_comparison
```

示例：

```bash
/opt/miniconda3/bin/python stage/report_stage5_background_comparison.py \
  --stage4-dir /data/LFT-W02_data/pengxu/stage4_output_v2 \
  --stage5-dir /data/LFT-W02_data/pengxu/stage5_output_v1_keyframes \
  --background-dir /data/LFT-W02_data/pengxu/stage5_external_background/era5_roi_npz \
  --frame-times 20260124013600,20260222063600,20260129114200,20260206174200
```

如果 ERA5/GFS NPZ 尚未准备好，脚本仍会生成 Stage4 vs Stage5 两栏图；有背景场时自动加第三栏。

### 5. ERA5 是否让本系统失去必要性

不会。

ERA5 / GFS / ECMWF / CMA-GFS 的价值是提供大尺度三维背景场和先验；你的系统价值在于：

- 接入航空相关 sparse direct observations
- 在雷达网格上构建事件驱动 ROI 状态层
- 保留 anchor fidelity 与可解释 hazard / confidence 结构
- 对局地、短时、航空关注区域做增量修正

论文表述上应避免说“替代 ERA5”，而应说：

```text
以粗分辨率背景场为先验，结合空地多源稀疏观测，面向航空事件 ROI 做近实时局地风场状态更新与风险辅助。
```

---

## 六、GFS / GDAS 实时背景场接入

ERA5 适合历史 keyframes 与论文基准；实时 / 准实时 Stage5 背景场建议优先使用 NOAA GFS 0.25°，GDAS 作为分析场或短延迟对照。

新增脚本：

```text
stage/download_stage5_gfs_gdas_roi.py
```

补充新增脚本：

```text
stage/download_stage5_merra2_roi.py
```

默认输出：

```text
GRIB: /data/LFT-W02_data/pengxu/stage5_external_background/gfs_gdas_roi
NPZ : /data/LFT-W02_data/pengxu/stage5_external_background/gfs_gdas_roi_npz
```

MERRA-2 对应目录：

```text
NC4 : /data/LFT-W02_data/pengxu/stage5_external_background/merra2_roi
NPZ : /data/LFT-W02_data/pengxu/stage5_external_background/merra2_roi_npz
```

默认 ROI：

```text
leftlon=106.5
rightlon=117.5
toplat=37.0
bottomlat=17.0
```

默认变量：

```text
UGRD,VGRD,VVEL,TMP,HGT
```

### 6. MERRA-2 背景场接入

当前已新增：

```text
stage/download_stage5_merra2_roi.py
```

定位：

- 为 Stage5 提供第三个外部背景候选源
- 主要面向历史关键帧 replay、benchmark 和与 ERA5/GFS 的交叉对比
- 不替代 Stage4 / Stage5 重构真值

当前实现能力：

- 生成 MERRA-2 ROI manifest
- 输出 Earthdata 下载 URL
- 支持把本地下载好的 `merra2_roi_<time>.nc4` 转成 Stage5 可读 NPZ
- 当前按 `M2I3NVASM` 3-hourly analysis collection 组织

推荐命令：

```bash
/opt/miniconda3/bin/python stage/download_stage5_merra2_roi.py \
  --frame-times 20260129114200,20260206174200
```

如果已手动下载好 `.nc4`，再转换：

```bash
/opt/miniconda3/bin/python stage/download_stage5_merra2_roi.py \
  --frame-times 20260129114200,20260206174200 \
  --convert-existing
```

当前输出：

```text
/data/LFT-W02_data/pengxu/stage5_external_background/merra2_roi/merra2_roi_manifest.json
```

当前边界：

- 本地尚未确认 Earthdata 登录凭证，因此本轮先补脚本与 manifest，不声称已完成远程下载
- `merra2_roi_npz` 目录当前可作为候选背景源目录保留，待实际 NC4 下载后再转换补齐

### 7. Stage5 多背景候选与内部时序背景

当前 `stage/stage5_pinn_diffusion_refine.py` 已从“单一背景目录”升级为：

```text
多背景候选 + 锚点一致性评分 + 自动选择/保守融合 + 内部时序背景候选
```

新增能力包括：

- `--background-dirs`
  - 可同时提供 `ERA5 / historical GFS / MERRA-2` 多个候选目录
- `--background-top-k`
  - 支持对最一致的前 K 个背景做保守融合
- `--internal-stage5-dir`
  - 可把上一帧 Stage5 输出作为“内部时序背景候选”
- `--disable-internal-stage5-background`
  - 显式关闭内部时序背景

当前默认候选顺序已包含：

```text
stage5_external_background/era5_roi
stage5_external_background/gfs_historical_aws_npz
stage5_external_background/merra2_roi_npz
```

内部时序背景的含义：

- 不依赖外部 NWP / reanalysis
- 直接把上一帧 Stage5 sparse ROI 输出恢复成可采样背景场
- 再与当前帧 anchors 比一致性
- 作为外部背景失败或明显冲突时的内部候选先验

这不是把 Stage5 变成真正 forecast，而是：

```text
把已有时序状态显式纳入 Stage5 背景候选层
```

### 8. 当前测试结果与解释

本轮新增测试目录：

```text
/data/LFT-W02_data/pengxu/stage5_output_v1_multi_background_test
/data/LFT-W02_data/pengxu/stage5_output_v1_internal_bg_test
/data/LFT-W02_data/pengxu/stage5_visualizations/stage5_multi_background_test_comparison
/data/LFT-W02_data/pengxu/stage5_visualizations/stage5_internal_bg_test_comparison
```

#### 单帧多背景测试

关键帧：

```text
20260129114200
```

结果：

- 已成功同时比较 `ERA5` 与 `historical GFS`
- 最终自动选择：

```text
/data/LFT-W02_data/pengxu/stage5_external_background/gfs_historical_aws_npz/gfs_roi_20260129114200.npz
```

原因：

- 它与当前 anchors 的冲突略小于 ERA5
- 但两者 `background_anchor_rmse` 都很高，说明外部背景与局地锚点整体冲突明显

结论：

- 新逻辑不会因为“有背景”就硬贴背景
- 它先做候选比较，再选择相对没那么差的一方

#### 两帧内部时序背景测试

关键帧：

```text
20260129114200
20260206174200
```

结果：

- 第一帧没有更早的 Stage5 输出，因此内部时序背景不可用
- 第二帧已允许从上一帧 Stage5 输出构造内部背景候选
- 但在当前这两帧上，最终仍然选择了 `historical GFS`

解释：

- 说明“上一帧 Stage5 输出”并不天然优于外部背景
- 它必须和当前帧 anchors 足够一致，才值得被选为主背景

这个结果本身是合理的，不应误判为失败。
它表明当前框架已经具备：

```text
外部背景优先级不是写死的，内部时序背景也不是一定更好
```

真正的判断依据是：

- `background_anchor_rmse`
- `background_anchor_speed_bias`
- `heldout_anchor_rmse_after`
- `background_vector_rmse`

### 9. 当前保守结论

- `Stage5` 现在更准确的定位是：
  - 物理感知 ROI refinement scaffold
  - 多背景候选选择器
  - 时序背景候选试验台
- 它仍然不是训练好的 neural diffusion
- `MERRA-2` 已接入工程链路，但当前本地还没有完成 NC4 实数据下载与转换
- 内部时序背景已经能参与候选比较，但还没有在当前测试帧上超过 `historical GFS`

### 10. v3 structured 背景约束升级

当前已新增一轮 v3 structured 升级，输出目录：

```text
/data/LFT-W02_data/pengxu/stage5_output_v1_internal_bg_test_v3_structured
/data/LFT-W02_data/pengxu/stage5_visualizations/stage5_internal_bg_test_comparison_v3_structured
/data/LFT-W02_data/pengxu/stage5_visualizations/stage5_full_roi_background_demo_v3_structured
```

这轮升级做了三件事：

1. full-ROI demo 现在同时输出：
   - `raw background` 差异
   - `scaled background` 差异

2. Stage5 现在显式记录：
   - `background_speed_scale`
   - `background_anchor_rmse_scaled`
   - `background_anchor_cosine_mean`
   - `direction_consistency_mean_after`
   - `expanded_background_relax_voxels`
   - `internal_background_zone_counts`

3. 对高风险帧新增结构化背景约束：
   - internal temporal background 分区权重
   - 外部背景默认只在 expanded 区参与 relax
   - expanded 区方向一致性约束

### 11. v3 structured 结果结论

#### 20260129114200

这是一个典型弱场帧。

full-ROI demo v3：

```text
raw_vector_rmse_on_stage5_points    ≈ 10.0953
scaled_vector_rmse_on_stage5_points ≈ 3.1721
```

Stage5 summary v3：

```text
background_vector_rmse ≈ 3.1530
anchor_rmse_after      ≈ 0.0249
heldout_anchor_rmse    ≈ 0.0349
```

解释：

- 这帧的主要问题是背景幅值失配；
- `background_speed_scale` 生效后，背景差异显著下降；
- 同时没有破坏 anchor fidelity。

#### 20260206174200

这是一个典型高风险强场帧。

full-ROI demo v3：

```text
raw_vector_rmse_on_stage5_points    ≈ 18.3423
scaled_vector_rmse_on_stage5_points ≈ 18.7720
```

Stage5 summary v3：

```text
background_vector_rmse          ≈ 17.7760
direction_consistency_mean_after ≈ 0.3845
delta_speed_expanded_mean        ≈ 17.9511
```

解释：

- 这帧的问题不是幅值失配，而是结构/方向冲突；
- 速度缩放对它帮助不大，甚至 full-ROI demo 中略差；
- 结构化约束的价值主要是“更可解释”，并没有显著把它变好。

默认气压层：

```text
1000,975,950,925,900,850,800,750,700,650,600,550,500,450,400,350,300,250,200 mb
```

### 1. 生成 GFS manifest

```bash
/opt/miniconda3/bin/python stage/download_stage5_gfs_gdas_roi.py \
  --dataset gfs \
  --mode latest \
  --forecast-hour 0
```

如果只想看 URL，不下载，就不要加 `--download`。

### 2. 下载实时 GFS ROI GRIB

```bash
/opt/miniconda3/bin/python stage/download_stage5_gfs_gdas_roi.py \
  --dataset gfs \
  --mode latest \
  --forecast-hour 0 \
  --download
```

说明：

- `--mode latest` 默认选择当前 UTC 时间往前留 6 小时安全滞后的最新 `00/06/12/18` cycle。
- 如果要取 cycle 后第 1、2、3 小时预报，可改 `--forecast-hour 1/2/3`。

### 3. 下载 GDAS 分析 / 对照场

```bash
/opt/miniconda3/bin/python stage/download_stage5_gfs_gdas_roi.py \
  --dataset gdas \
  --mode latest \
  --forecast-hour 0 \
  --download
```

### 4. 转成 Stage5 背景场 NPZ

需要当前 Python 环境有：

```text
xarray
cfgrib
eccodes
```

转换命令：

```bash
/opt/miniconda3/bin/python stage/download_stage5_gfs_gdas_roi.py \
  --dataset gfs \
  --mode latest \
  --forecast-hour 0 \
  --convert-existing
```

输出 NPZ 字段与 ERA5 工具一致：

```text
lat
lon
alt_km
pressure_hpa
u
v
vertical_velocity
temperature
geopotential
```

当前已完成一次端到端 smoke：

```text
GRIB: /data/LFT-W02_data/pengxu/stage5_external_background/gfs_gdas_roi_smoke_fallback_download2/gfs_roi_20260519120000.grib2
NPZ : /data/LFT-W02_data/pengxu/stage5_external_background/gfs_gdas_roi_npz_smoke_fallback_download2/gfs_roi_20260519120000.npz
```

该 smoke 验证了：

- NOMADS GFS ROI URL 可下载
- `xarray + cfgrib + eccodes` 可读 GRIB2
- NPZ 包含 `lat/lon/pressure_hpa/alt_km/u/v/vertical_velocity/temperature/geopotential`

注意：NOMADS GFS/GDAS pressure levels 不完全等同 ERA5 pressure levels；脚本默认使用 NOMADS 支持的层次，避免 `875 mb` / `225 mb` 这类不支持层次导致 HTTP 500。

### 5. 给 Stage5 使用 GFS/GDAS 背景场

```bash
/opt/miniconda3/bin/python stage/stage5_pinn_diffusion_refine.py \
  --stage4-dir /data/LFT-W02_data/pengxu/stage4_output_v2 \
  --summary /data/LFT-W02_data/pengxu/stage4_output_v2/stage4_summary.json \
  --out-dir /data/LFT-W02_data/pengxu/stage5_output_v1_gfs_smoke \
  --selection frames \
  --frame-times 20260124013600,20260222063600 \
  --background-dir /data/LFT-W02_data/pengxu/stage5_external_background/gfs_gdas_roi_npz \
  --holdout-every 5 \
  --hazard-conservative \
  --make-plots 1
```

注意：

- GFS/GDAS 第一版主要服务在线新帧，不保证能直接回放 2026-01/02 历史帧。
- 历史关键帧仍优先使用 ERA5；如果 ERA5 卡住，再走 NCEI/NCAR archive。
- Stage5 会用 `background_vector_rmse`、`background_speed_bias` 等指标评估与背景场的一致性。

### 6. rolling ROI 默认背景

`stage/run_stage5_rolling_roi.py` 当前默认把 Stage5 背景目录指向：

```text
/data/LFT-W02_data/pengxu/stage5_external_background/gfs_gdas_roi_npz
```

`stage5_pinn_diffusion_refine.py` 会自动识别：

```text
era5_roi_<time_str>.npz
gfs_roi_<time_str>.npz
gdas_roi_<time_str>.npz
background_<time_str>.npz
```

如果要临时不用背景场：

```bash
/opt/miniconda3/bin/python stage/run_stage5_rolling_roi.py \
  --frame-indices 76,7041 \
  --run-stage5 \
  --no-background \
  --dry-run
```

也可以直接用 `time_str`，脚本会从 `stage2_summary.json` 自动解析 source indices：

```bash
/opt/miniconda3/bin/python stage/run_stage5_rolling_roi.py \
  --frame-times 20260124013600,20260222063600 \
  --run-stage5 \
  --dry-run
```

不要把文档里的 `<new_frame_indices>` 原样输入 shell；尖括号会被 bash 当成重定向。应写真实数字，例如：

```bash
--frame-indices 76,7041
```

如果要在线使用 GFS/GDAS 背景场：

```bash
/opt/miniconda3/bin/python stage/run_stage5_rolling_roi.py \
  --frame-times 20260124013600,20260222063600 \
  --run-stage5 \
  --background-dir /data/LFT-W02_data/pengxu/stage5_external_background/gfs_gdas_roi_npz
```

### 7. GFS / GDAS 背景场 3D 可视化

新增：

```text
stage/report_stage5_background_field.py
```

用途：

- 只看 GFS/GDAS/ERA5 背景场本身
- 检查 ROI、气压层、高度映射和水平风矢量是否合理

示例：

```bash
/opt/miniconda3/bin/python stage/report_stage5_background_field.py \
  --background-dir /data/LFT-W02_data/pengxu/stage5_external_background/gfs_gdas_roi_npz \
  --out-dir /data/LFT-W02_data/pengxu/stage5_visualizations/gfs_gdas_background \
  --lon-range 106.5,117.5 \
  --lat-range 17,37 \
  --alt-range 0,12 \
  --xy-stride 3 \
  --z-stride 2 \
  --max-vectors 900
```

当前已生成：

```text
/data/LFT-W02_data/pengxu/stage5_visualizations/gfs_gdas_background/gfs_roi_20260519120000_background_3d.png
/data/LFT-W02_data/pengxu/stage5_visualizations/gfs_gdas_background/gfs_roi_20260519120000_background_summary.json
```

图中：

- 点表示 GFS/GDAS/ERA5 pressure-level 背景格点，不是 Stage4/Stage5 sparse voxel。
- 点颜色表示背景风速。
- 黑色箭头表示背景水平风 `u/v`，长度已缩放。
- 竖轴高度来自气压层近似换算，不等同于真实地形跟随高度。

### 如何理解当前 GFS 背景场 3D 图

当前目录：

```text
/data/LFT-W02_data/pengxu/stage5_visualizations/gfs_gdas_background
```

里面的 `gfs_roi_20260519120000_background_3d.png` 是 **NOAA GFS 实时背景场可视化**，不是你的 Stage4 / Stage5 风场重构结果。

这张图的含义：

- `Longitude (deg)` / `Latitude (deg)`：GFS ROI 背景场的经纬度网格。
- `Altitude (km)`：由 GFS pressure level 近似换算出来的高度。
- 每个点：一个 GFS pressure-level 背景格点，不是 Stage4 sparse voxel，也不是 Stage5 refined voxel。
- 点颜色：该 GFS 背景格点的水平风速大小。
- 黑色箭头：GFS 背景水平风矢量，东西向来自 `u`，南北向来自 `v`。
- 箭头长度：经过绘图缩放，只表示方向和相对强弱，不表示地图真实距离。

它和本项目的关系：

- 它不直接基于你的 Stage4 / Stage5 重构结果。
- 它基于 NOAA GFS 实时预报资料。
- 它使用了你项目定义的 ROI、Stage5 背景场 NPZ 格式和可视化工具。
- 它的作用是给 Stage5 提供大尺度三维背景先验，并作为后续 Stage4 / Stage5 / background 对比图的第三方背景层。

特别注意：

- 当前 GFS 文件 `gfs_roi_20260519120000.npz` 是 `2026-05-19` 的实时背景场。
- 它不能直接对应 `2026-01/02` 的历史 keyframes。
- 如果要和 `20260124013600`、`20260222063600` 等历史帧严格对齐，要使用历史 GFS archive 或 ERA5，而不是把实时 GFS 直接拿来回放。
- 当前图适合作为“实时背景场接入成功”的汇报图，不适合作为“重构效果提升图”。

### 8. 历史 GFS archive 对齐 keyframes 已跑通

为了把历史 keyframes 和真实背景场对齐，新增了历史 GFS archive 下载脚本：

```text
stage/download_stage5_gfs_aws_historical_roi.py
```

它的做法是：

- 从 NOAA GFS public AWS archive 读取对应日期的 `.idx`
- 只按 byte-range 下载所需 pressure-level 消息
- 转成 Stage5 可读的 ROI NPZ

当前已验证的历史 keyframes 对应关系：

```text
20260124013600 -> 2026012400 f001
20260129114200 -> 2026012906 f005
20260206174200 -> 2026020612 f005
20260222063600 -> 2026022206 f000
```

对应输出目录：

```text
/data/LFT-W02_data/pengxu/stage5_external_background/gfs_historical_aws
/data/LFT-W02_data/pengxu/stage5_external_background/gfs_historical_aws_npz
/data/LFT-W02_data/pengxu/stage5_output_v1_historical_gfs_keyframes
/data/LFT-W02_data/pengxu/stage5_visualizations/historical_gfs_keyframes_comparison
```

历史 GFS NPZ 已确认包含 19 个 pressure levels；`comparison_summary.json` 中 4 帧均为 `status=ok` 且 `background=true`；`stage5_summary.json` 中 4 帧均 `background_available=1`。

这一步的意义是：

- 证明历史 keyframes 不必只靠 ERA5，也可以直接对齐 NOAA GFS archive
- 证明 Stage5 的背景场接口不仅能接实时背景，也能接历史背景
- 证明三栏图里“差异大”不等于“流程错了”

### 9. 历史 GFS 三栏图差异大的原因

这不是单一问题，而是几个因素叠加：

- Stage4 / Stage5 是 sparse ROI 点，GFS 是规则 pressure-level 背景格点
- Stage5 只把背景场当弱先验，不会强制贴合 GFS
- 三栏图右侧背景栏的展示受 `max_vectors=250` 和常数 `conf=0.55` 影响，视觉上会更规整
- 历史 GFS 是按整点 cycle + forecast hour 对齐，不是分钟级真值
- 因此三栏图形态差异大是预期现象，不能直接当作 refinement 失败

对应的数值也支持这个判断：

- `20260124013600`：`background_vector_rmse≈12.55`，`background_speed_bias≈-5.52`
- `20260129114200`：`background_vector_rmse≈8.08`，`background_speed_bias≈-5.96`
- `20260206174200`：`background_vector_rmse≈16.85`，`background_speed_bias≈-0.10`
- `20260222063600`：`background_vector_rmse≈8.64`，`background_speed_bias≈-4.09`

保守结论：

- `20260129114200` 是相对稳的帧
- `20260206174200` 仍是风险帧
- `20260124013600` 与 `20260222063600` 在带历史 GFS 后 held-out 指标偏高，说明背景场与局地 anchor 可能冲突

### 9.1 对比图已改成共享 ROI mask 版本

为了避免“不同点集硬比”带来的视觉偏差，`report_stage5_background_comparison.py` 已更新为共享 sparse support 版本：

- Stage4 和 Stage5 先取交集 support
- 背景场只在这批共享 support 上做最近邻采样
- 三栏图只画同一批点
- 额外输出 `Stage5 - background` 差值图

当前对应输出目录是：

```text
/data/LFT-W02_data/pengxu/stage5_visualizations/historical_gfs_keyframes_comparison
```

`comparison_summary.json` 里现在会写：

- `background=true`
- `shared_points=250`
- `sample_mode=shared_stage4_stage5_intersection`

这意味着当前的差异已经比原始版本更接近“同一批点上的真差异”，而不是抽样方式造成的假差异。

### 10. 当前无背景 keyframes 结果判断

目录：

```text
/data/LFT-W02_data/pengxu/stage5_output_v1_no_background_keyframes
```

结论：

- 4 帧均成功，说明 Stage5 scaffold 可运行。
- `background_available=0`，这些结果只能说明无背景场 refinement 行为，不能作为最终强结论。
- `20260129114200` 最稳：`268 -> 443`，`anchor_rmse_after≈0.0389`，`heldout_anchor_rmse_after≈0.0464`。
- `20260222063600` 适合作为中位 coverage 展示：`295 -> 482`，`anchor_rmse_after≈0.0470`，原始点改动很小。
- `20260124013600` 原始点保持较好，但 held-out 误差偏高，适合作为诊断帧。
- `20260206174200` 是风险帧：expanded delta、divergence 和 held-out 误差偏大，应作为 failure / risk diagnostic。

3D 图解释：

- 每个点是一个 Stage5 refined sparse voxel，不是全国连续满场。
- `Longitude / Latitude` 来自 Stage4 雷达网格 x/y 到经纬度的线性映射。
- `Altitude (km)` 来自 `z * 0.5 km`。
- 点颜色是 `refined_conf_val`。
- 黑色箭头是水平风矢量，东西向来自 `u`，南北向来自 `v`。
- 箭头长度经过绘图缩放，只表示方向和相对强弱。
- 当前没有真实 `w` 垂直风箭头；有 GFS/GDAS/ERA5 后可进一步把 `vertical_velocity` 作为背景诊断层展示。
