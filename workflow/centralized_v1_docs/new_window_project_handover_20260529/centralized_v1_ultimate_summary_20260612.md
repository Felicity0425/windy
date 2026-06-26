# centralized_v1 项目终极完整汇总（基于 `new_window_project_handover_20260529` 全目录逐份通读）

生成时间：2026-06-12  
汇总范围：已逐份阅读目录内 16 个文件，共约 12,394 行文档内容。  
最新口径优先级：`2026-06-11 > 2026-06-10 > 2026-06-09 > 2026-06-08 > 2026-06-05 > 2026-06-02 > 2026-06-01 > 2026-05-29`。  
如果不同文档之间有结论冲突，以下内容一律以更晚日期的文档为准。

---

## 0. 2026-06-26 最新补充状态（覆盖 2026-06-12 之后的新执行结果）

> 本节是对 `2026-06-12` 版本的**增补**，用于交接窗口和后续执行衔接。  
> 若本节与正文旧结论冲突，以本节为准。

### 0.1 这几天新增完成的工作

在 `2026-06-12` 之后，项目没有直接进入 `Stage5` 或盲目继续调 `Stage4` 参数，而是先完成了以下几项关键前置工作：

1. `P0-CMA`：新增并跑通 `verify_cma_grib.py`，系统审计本地 `CMA/CRA40` 数据。
2. `P0-LEAK`：完成 `CMA` 背景独立性审计，并单独审计了项目自有数据是否能替代独立背景。
3. `P0-FLOOR`：新增工程版误差地板估计脚本，量化当前 baseline 与可达 proxy floor 的差距。
4. `S4-CMA-M1`：完成轻量 `200` 帧 baseline 复现实验，并在 `6` 个代表帧上跑通 `display-only weak background fill`。
5. `P0-GFS`（新增）：放弃直接把 `CMA` 推到 `OI` 主背景，转而下载 `GFS forecast` 作为独立背景候选；当前 `200` 帧已全部完成。

这一轮最重要的改变，不是某个指标提升了多少，而是**项目主线从“可能把 CMA 继续往 OI 推”修正为“CMA 留在 display-only，OI 主线改走 GFS forecast”**。

### 0.2 当前最新执行状态总表

| 计划项 | 当前状态 | 说明 |
| --- | --- | --- |
| `P0-FRAME` | 已核实，口径修正 | 当前代码已支持 `txt` 和 `json list`，不再是 blocker |
| `P0-LEAK`(CMA) | 已完成审计，未放行 OI | `CMA-RA/CRA40` 被确认为 `reanalysis / analysis product` |
| `P0-CMA` | 完成 | `773` 文件、`129` 时次、抽样可读 `18/18` |
| `P0-FLOOR` | 完成（工程版） | baseline `14.7690`，proxy floor `11.1126`，剩余空间 `3.6564 m/s` |
| `S4-CMA-M1` | 部分完成 | `200` 帧 baseline 已复现；`6` 代表帧 display-only 产品已跑通；full-200 pairwise 封口未做 |
| `P0-GFS` | 完成 | `178/178` unique source，`200/200` frame，`failed_count = 0` |
| `S4-OI-DIAG` | 未开始 | 下一步背景优先切到 `GFS`，而不是继续用 `CMA` |
| `S4-OI-*` | 未开始 | 依赖 `P0-GFS` 体检和 `S4-OI-DIAG` 结果 |
| `Stage5` | 未开始 | 当前不应提前进入 |

### 0.3 现在最关键的新结论

#### 0.3.1 `CMA-RA` 现在应如何定位

现在已经可以明确：

```text
CMA-RA / CRA40 / NAFP_CRA40_FTM_6HOR = reanalysis / analysis product
```

这意味着：

1. 它通常可能比纯 forecast 更接近真实大气状态。
2. 但它与项目 holdout aircraft wind 的独立性**没有被证明**。
3. 因此它当前适合：
   - `display-only weak background fill`
   - 参考大尺度流场
   - 产品完整性分支
4. 它当前不适合：
   - 作为 `OI / innovation / Desroziers` 的正式独立背景

换句话说：

```text
CMA 可能更“准”
但 GFS 更“干净”
```

对于当前项目阶段，做 `OI-DIAG` 更需要“干净背景”，而不是单纯“更接近真实的再分析背景”。

#### 0.3.2 `S4-CMA-M1` 的真实定位

这一轮已经完成了 `S4-CMA-M1` 的轻量 demo：

1. `200` 帧 baseline `metrics-only` 已复现官方基线。
2. `6` 个代表帧已成功跑通 `display-only low-confidence background fill`。
3. 代表帧背景填充比例约 `97.72% ~ 98.49%`，均值约 `98.16%`。
4. 填充区域 `display_conf` 上限被压在 `0.20`。

因此当前最稳妥的说法是：

```text
S4-CMA-M1 已经证明“完整风场 + 低置信标注”这条产品分支可行
但 full-200 的 official == baseline pairwise 封口尚未做完
```

所以它是：

```text
已跑通的 product-completeness branch
而不是已经封口的 official default branch
```

#### 0.3.3 `P0-FLOOR` 给出的现实优化空间

工程版误差地板估计结果为：

```text
baseline vector RMSE = 14.769036
local proxy vector floor = 11.112602
distance to floor = 3.656433
12km+ baseline = 19.917698
12km+ proxy floor = 14.168927
```

这个结果很重要，因为它说明：

1. 系统确实还有改进空间，但不是无限大。
2. 高空 `12km+` 仍然是最主要的可攻克矛盾。
3. 后续任何复杂方法都必须对照“离地板还剩多少”，不能再假设全局 RMSE 还可以轻易大幅下降。

#### 0.3.4 `GFS forecast` 已经成为下一阶段背景主线

当前 `200` 帧历史背景下载已经完成：

```text
178 / 178 unique sources
200 / 200 frame NPZ
failed_count = 0
```

并且已经确认：

1. 当前本地下载的是 `GFS 0.25°` 区域裁剪背景。
2. 当前默认提取层为 `1000 ... 200 hPa`。
3. 当前最高层约对应 `11.78 km`，因此对于真正的 `12km+` 尾部仍然偏紧。
4. 原始 `.idx` 已确认存在 `150 hPa` 和 `100 hPa` 的 `UGRD/VGRD` 记录，因此后续如要深入打高空，**可以补高层，不是数据源没有**。

当前最合理的判断是：

```text
这批 GFS 已足够支持第一阶段 S4-OI-DIAG
若 OI 路线显示有希望，再补 150/100 hPa 以增强 12km+ 背景
```

### 0.4 为什么项目现在要验证“背景 + 观测”这条路线

这个问题在 `2026-06-12` 版本里还没有被完全展开。  
现在需要明确：

项目当前的难点，不是低层观测密集区，而是：

```text
12km+
count_0 / count_1
dist_ge6km
gap_ge30
中等 time_conf 风险层
```

这些区域的共同问题是：

```text
观测约束不足
```

所以验证“背景 + 观测”路线的意义在于：

1. 不是让背景替代观测。
2. 而是在观测足够时依然以观测为主。
3. 只在观测稀疏、高空和空白区，让背景提供一个大尺度、连续、低置信的弱约束。

也就是说，项目现在想验证的不是：

```text
GFS 能不能直接生成更好的最终风场
```

而是：

```text
如果给系统一个相对独立、连续的大尺度先验，
它能不能在高空和稀疏区真正帮上忙，而且不破坏已有优势
```

这就是 `S4-OI-DIAG`、`innovation`、`obs_influence` 这些步骤存在的意义。

### 0.5 当前最务实的下一步

如果只给出一条最稳妥的后续执行线，现在建议是：

```text
1. 先补 verify_gfs_background 报告
2. 用 GFS 进入 S4-OI-DIAG (report-only)
3. 再决定是否值得继续做 oi_diag_approx / local_oi
4. 与此同时，可补 S4-CMA-M1 的 full-200 pairwise 封口
```

不建议当前直接做的事：

```text
1. 继续把 CMA 推向 OI 主背景
2. 跳过 GFS 体检直接做 local OI
3. 现在就重新大规模推进 Stage5
```

---

## 1. 先给结论：这个项目现在到底是什么

`centralized_v1` 是一个**中心化三维风场重构项目**。  
它的目标不是直接做“航空运行级低空风切变预警系统”，而是：

1. 把飞机风观测、飞机位置/运动、雷达云图背景、数值背景场组织到一个统一的三维网格里。
2. 在严格防泄漏的前提下，用**当前时刻飞机风观测**做唯一真值，重构 `u/v` 水平风场。
3. 给出一套可审计、可复现实验、可分层分析的验证框架。
4. 在 Stage4 得到稳定主线后，再探索 Stage5 的 PINN / residual / uncertainty / gated correction。

这个项目最重要的价值，不只是“做出一个风场”，而是**把真值、背景、诊断、展示层、未验证区域严格分开**。

---

## 2. 当前最新状态：默认方法、候选方法、哪些能用、哪些不能用

### 2.1 当前默认主线

当前默认方法仍然是：

```text
Stage4 default = tp26_thr11_preserve
```

它是当前**正式主线**，也是写论文和做后续对比时的主基线。

### 2.2 当前不能升默认的方法

以下分支都**不能升默认**：

```text
support_role_height_aware (SRHA)                  -> FAIL
sparse_temporal_gated CMA/NWP                     -> FAIL
guarded_vertical_dynamic_v2                       -> FAIL
tp26_point_regime_localization_v1                -> FAIL
Stage5 residual PINN field-v1 / field-v2         -> 只能算候选，不是默认
```

### 2.3 当前可以保留但不能自动升默认的方法

```text
tp26_rep_soft_weight_v1
```

它在 200 帧 formal gate 上是 **PASS**，但收益很小，而且 5614 帧全量验证尚未完成，因此目前结论是：

```text
可以保留为 representation / reliability 候选方向
不能仅凭 200 帧小幅提升就替换 tp26_thr11_preserve
```

### 2.4 Stage5 当前的真实地位

Stage5 不是默认方法，也不是 Stage4 的替代品。  
它目前只是：

```text
一个极窄门控的 residual PINN candidate
```

它已经证明：

1. 在点级别可以做出一个**很小但安全的非零改进**。
2. 但一旦把这个信号写回 full field，正式 200 帧 field smoke 仍然可能 fail。
3. 所以它现在只能作为“受控 smoke / candidate”，不能当主结论。

---

## 3. 这个项目最不能搞错的四条边界

### 3.1 真值边界

唯一正式真值：

```text
current aircraft wind_records strict holdout
```

意思是：当前帧的飞机风观测里，拿出一部分当 holdout，这部分在重构前必须移除，只能在重构后拿来比误差。

### 3.2 绝对不能当真值的东西

下面这些都**不能当正式 truth**：

```text
motion_records / context_motion_records
location derived motion u/v
radar PNG intensity
CMA / CRA40 / GFS / ERA / NWP 背景场
display-filled visualization layer
no-holdout frame 的“0误差”
```

### 3.3 严格防泄漏要求

任何正式候选都必须满足：

```text
strict_holdout_no_leakage = True
motion_used_as_wind = False
```

### 3.4 论文和汇报时绝对不能说的话

不能说：

1. `u_motion/v_motion` 就是风。
2. 雷达 PNG 就是风速或径向速度。
3. CMA/NWP 与模型一致，就等于 aircraft truth 精度高。
4. no-holdout 帧的误差是 0，所以模型表现更好。
5. 500m 网格点 RMSE 约等于 30m 风切变阈值。

---

## 4. 项目核心定义：到底在重建什么

项目重建的是：

```text
三维网格上的水平风场分量 u / v
```

不是：

```text
完整真实大气状态
不是 w/pressure/temperature 全状态求解
不是运行级低空风切变告警
不是真实 Doppler radar wind retrieval
```

当前网格为：

```text
lat: 12.2 - 54.2
lon: 73.0 - 135.0
alt: 0 - 15000 m
vertical step: 500 m
grid shape: 31 x 525 x 775
total voxels: 12,613,125
```

---

## 5. 项目全流程总览：每一步在做什么、怎么做、解决什么问题

---

### 5.1 Stage1：原始数据清洗、标准化、索引化

#### 目标

把原始 Excel / workbook / radar 文件整理成后续阶段能稳定读取的标准中间产物。

#### 主要输入

```text
amdar.xlsx
turb.xlsx
location.xlsx
radar PNG
```

#### 主要输出

```text
stage1_output/clean_wind.parquet
stage1_output/clean_loc.parquet
stage1_output/radar_index.json
stage1_output/frame_window_index.json
```

#### 关键脚本

```text
stage/convert_excel_to_parquet_robust.py
stage/check_location_parquet_quality.py
stage/check_stage1_stage2_alignment.py
stage/stage1_prepare.py
```

#### 具体在做什么

1. 把 Excel workbook 按 sheet 转成 parquet。
2. 统一时间到 UTC。
3. 清洗经纬度、高度、航班号等字段。
4. 对 AMDAR/TURB 风向风速转成 `u_wind/v_wind`。
5. 对 location 的 heading + ground speed 转成 `u_motion/v_motion`。
6. 扫描雷达文件，建立时间和文件路径索引。

#### 关键公式

飞机风观测：

```text
u_wind = -wind_speed * sin(wind_dir * pi / 180)
v_wind = -wind_speed * cos(wind_dir * pi / 180)
```

飞机地面运动：

```text
u_motion = ground_speed_ms * sin(heading_deg * pi / 180)
v_motion = ground_speed_ms * cos(heading_deg * pi / 180)
```

#### Stage1 解决的问题

1. 原始表结构不统一。
2. 时间、坐标、高度格式不稳。
3. 同类观测字段命名不一致。
4. 后续 Stage2 无法直接对齐 radar frame 和 aircraft observation。

#### Stage1 最重要的认知

```text
u_motion / v_motion = 飞机地面运动
不是风
```

---

### 5.2 Stage2：多源观测组织与体素化

#### 目标

把稀疏 aircraft wind、location、motion、雷达背景组织到统一三维网格。  
Stage2 **不是风场重构**，只是“组织观测”。

#### 主要输入

```text
clean_wind.parquet
clean_loc.parquet
radar_index.json
radar PNG
```

#### 主要输出

```text
每帧 .npz
stage2_multimodal_summary.json
切片图 / stats / audit
```

#### 关键脚本

```text
stage/centralized_v1/core/centralized_stage2_multimodal.py
```

#### 具体在做什么

1. 选择每一个目标雷达时刻 `T`。
2. 取 `T±5min` 作为 current window。
3. 取 `T±360min` 且排除 current window 作为 context window。
4. 把 aircraft wind、location、motion 映射到三维 voxel。
5. 生成：
   - `wind_records`
   - `context_wind_records`
   - `loc_records`
   - `motion_records`
   - `context_motion_records`
   - `cloud_2d`

#### 关键窗口定义

```text
current window = [T - 5 min, T + 5 min]
context window = [T - 360 min, T + 360 min], excluding current
```

#### 时间衰减

`context_wind_records` 使用时间置信度：

```text
time_conf = 0.5 ** (abs(delta_time_minutes) / 180)
```

#### Stage2 解决的问题

1. 原始观测极其稀疏且时空不齐。
2. 不同源数据不在统一网格上。
3. 后续 Stage4 需要明确 current truth 候选和 context support。

#### Stage2 最重要的认知

```text
Stage2 = all-in observation organization
not final wind reconstruction
```

---

### 5.3 Stage3：Ground Center 中心化打包

#### 目标

把 Stage2 输出按“中心化接收端”逻辑封装成 Stage4 易于消费的 payload。

#### 主要输出

```text
stage3_center_summary.json
ground_center_payload
agent payload
confidence package
```

#### 关键脚本

```text
stage/centralized_v1/core/centralized_stage3_center.py
```

#### 具体在做什么

1. 读取 Stage2 每帧 `.npz`。
2. 按 `flight_id` 聚合飞机 agent。
3. 为每架飞机生成位置、中位高度、最近时刻等 agent 状态。
4. 保留不同 observation role：
   - `label_candidates`
   - `context_wind_observations`
   - `trajectory_observations`
   - `motion_observations`
   - `context_motion_observations`
   - `confidence_package`

#### Stage3 解决的问题

1. Stage4 需要有清晰的角色分层，不然会把 truth、context、motion 混起来。
2. 需要把“谁是候选真值、谁是背景、谁只是诊断”明确下来。

#### Stage3 最重要的认知

```text
Ground Center = 逻辑中心接收端
不是物理站点
不是按“离某个点远近”做筛选
```

---

### 5.4 Stage4：strict holdout 三维风场重构与正式评估

#### 目标

真正生成三维风场，并且用严格 aircraft holdout 做验证。

#### 关键脚本

```text
stage/centralized_v1/core/centralized_stage4_ground_recon.py
stage/centralized_v1/core/centralized_stage4_sensitivity.py
stage/centralized_v1/core/centralized_stage4_pairwise_frame_compare.py
stage/centralized_v1/core/centralized_stage4_error_source_decomposition.py
stage/centralized_v1/core/centralized_report_stage4_slices.py
```

#### 重构时允许输入的东西

```text
train_current_wind = wind_records - holdout
context_wind_records
```

#### 重构时禁止输入的东西

```text
holdout wind_records
motion_records as wind
context_motion_records as wind
CMA/GFS/ERA as truth
```

#### 基础权重逻辑

```text
active_weight = obs_conf * time_conf * localization
```

在更复杂模式下还会乘：

```text
density_conf_factor
speed_qc_conf_factor
local_consistency_conf_factor
representation / reliability / tail-risk related factors
```

#### localization 核心思想

1. baseline：固定宽核。
2. adaptive 系列：根据非 holdout 诊断在多个核之间选择。
3. 目标不是全局固定最优半径，而是根据当前支撑结构做更稳的选择。

#### Stage4 输出

```text
recon_u_3d
recon_v_3d
recon_confidence_3d
recon_mask_3d
point departures
frame metrics
tail diagnostics
visualization slices
```

#### Stage4 解决的问题

1. 如何在 aircraft wind 稀疏、context 旧、支撑不均的情况下重构三维风场。
2. 如何防止 truth 泄漏。
3. 如何把“可重构区域”和“无 claim 区域”分开。
4. 如何用分层指标而不是单一均值描述模型质量。

---

### 5.5 Stage5：Residual PINN / gated neural correction

#### 目标

不是替代 Stage4，而是在 `tp26_thr11_preserve` 上叠加一个非常保守的 residual correction。

#### 正确公式

```text
F_stage5 = F_tp26 + gate * clipped_delta
```

不是：

```text
直接让 PINN 生成最终全场真风
```

#### 当前设计分两步

1. `report_v1`：点级 residual 学习，先验证统计上是否有信号。
2. `field_v1`：再把通过 gate 的 residual 写回 full field。

#### Stage5 解决的问题

1. Stage4 剩余长尾误差是否能通过受控 residual 学到一点修正。
2. 能否在不伤害 light wind / floor10 / 12km+ 的前提下做极小幅度改进。

#### 当前最大限制

```text
Residual PINN 的信号存在，但很小
且一旦写回 field，极易触碰 formal guardrail
```

---

## 6. 数据角色：哪些数据做什么

| 数据 | 项目内角色 | 能否做 truth | 备注 |
| --- | --- | --- | --- |
| AMDAR/TURB `u_wind/v_wind` | 正式风观测 | 能 | Stage4 唯一官方真值来源 |
| location `u_motion/v_motion` | 飞机运动诊断 | 不能 | 不是 atmospheric wind |
| radar PNG intensity | 云/雷达背景 | 不能 | 不是 Doppler velocity |
| CMA/CRA40/GFS/ERA | 弱背景、先验、条件输入 | 不能 | 只能 background/prior |
| display-filled field | 展示层补色 | 不能 | 不进入 official RMSE |
| no-holdout frame | 未验证重构产品 | 不能 | 保留业务价值，但不进官方精度 |

---

## 7. Stage4 方法演进主线：从 baseline 到 tp26

### 7.1 三个主对比方法

| 方法 | 本质 | 关键特征 |
| --- | --- | --- |
| `baseline_aircraft` | 最早纯 aircraft 宽核基线 | 固定宽核、diagnostic_only、无复杂冲突控制 |
| `adaptive_v3` | 主体升级版 | diagnostic_weighted + non-leaking adaptive localization + role conflict |
| `tp26_thr11_preserve` | 当前默认 | 更强 context time decay + threshold 11 + vertical preserve |

### 7.2 最新默认 tp26 的核心参数

```text
confidence-mode diagnostic_weighted
physics-constraint-mode pydda_3dvar_proxy
localization-policy diagnostic_adaptive_v3
localization-candidate-grid 8:4,10:5
current-weight-boost 2.0
context-weight-scale 0.5
context-time-conf-power 2.6
role-conflict-mode current_priority_adaptive
conflict-speed-threshold-mps 11.0
conflict-context-factor 0.25
vertical-risk-mode preserve_strong_layers
vertical-gradient-preserve-weight 0.12
vertical-context-mismatch-damping 0.35
```

### 7.3 这条主线到底解决了什么

从最早 baseline 到 tp26，主要解决的是：

1. 不再只靠固定宽核做经验插值。
2. current anchor 与旧 context 冲突时，会保护 current。
3. 更 aggressively 衰减 stale context。
4. 在强垂直结构区域尽量少做跨层抹平。

但它**还没有**完全解决：

1. 高空长尾。
2. sparse support 外推。
3. representation error。
4. 极少数 role-conflict 灾难点。

---

## 8. 当前最重要的正式指标

---

### 8.1 全量主线结果：7395 帧

完整全量主线来自：

```text
stage4_full_v2_best_adaptive_all_12w_20260529
```

或其后续 tp26 全量版本语境。

#### 全量统计

| 指标 | 数值 |
| --- | ---: |
| 总帧数 | 7395 |
| 有 holdout 可严格评估帧 | 5614 |
| no-holdout 帧 | 1781 |
| 全部帧混算乐观 RMSE | 6.60 m/s |
| holdout-only 真实 RMSE | 8.696082 m/s |
| holdout-only 真实 MAE | 7.652211 m/s |
| weighted RMSE | 14.819533 m/s |
| weighted MAE | 6.724179 m/s |
| multi-holdout supported RMSE/MAE | 7.882480 / 6.389791 |
| single-holdout pressure-test RMSE/MAE | 10.588383 / 10.588383 |

#### 最重要解释

```text
1781 个 no-holdout 帧必须保留重构结果
但不能进入官方 RMSE/MAE
```

---

### 8.2 200 帧 strict holdout 主基准

这是目前最常用的正式对比 benchmark：

```text
frames = 200
holdout points = 530
```

#### 三方法核心表

| 方法 | frame RMSE | frame MAE | weighted RMSE | weighted MAE | P95 | P99 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `baseline_aircraft` | 11.6898 | 10.3011 | 18.9184 | 10.3509 | 42.6407 | 74.2244 |
| `adaptive_v3` | 8.4570 | 7.3067 | 14.9326 | 7.0682 | 28.1452 | 63.2337 |
| `tp26_thr11_preserve` | 8.2243 | 7.0819 | 14.7690 | 6.8545 | 27.9861 | 58.7838 |

#### 主提升幅度

从 `baseline_aircraft` 到 `tp26_thr11_preserve`：

```text
weighted RMSE: 18.9184 -> 14.7690   (下降约 21.9%)
frame RMSE:    11.6898 -> 8.2243    (下降约 29.6%)
P95 RMSE:      42.6407 -> 27.9861    (下降约 34.4%)
```

---

### 8.3 当前 Stage4 默认 tp26 的 tail 结构

200 帧 / 530 点下，当前问题不是“全体都差”，而是少数 tail 点主导误差。

| stratum | points | RMSE | SSE share |
| --- | ---: | ---: | ---: |
| all_holdout_points | 530 | 14.769036 | 1.000000 |
| alt_12km_plus | 222 | 19.917698 | 0.761818 |
| qc_review_flag | 302 | 18.945495 | 0.937646 |
| no_qc_review_flag | 228 | 5.622848 | 0.062354 |
| high_vector_error_ge30mps | 21 | 66.820701 | 0.811075 |
| role_gap_ge30mps | 38 | 32.392820 | 0.344906 |
| nearest_distance_gt4vox | 27 | 32.499520 | 0.246682 |

这说明：

```text
RMSE 被很少量高空 / 稀疏支撑 / role-gap / vertical-risk tail 点支配
```

---

### 8.4 Stage4 representation soft-weight 候选

这是 Stage4 近期最稳的非默认候选。

#### 200 帧 formal gate 结果

| gate | baseline `tp26_thr11_preserve` | candidate `tp26_rep_soft_weight_v1` | result |
| --- | ---: | ---: | --- |
| weighted RMSE | 14.769036 | 14.755381 | PASS |
| frame P95 | 27.986111 | 27.947974 | PASS |
| frame P99 | 58.783770 | 58.756881 | PASS |
| 12km+ vector RMSE | 19.917698 | 19.884741 | PASS |
| light wind RMSE | 5.195877 | 5.165311 | PASS |
| light wind MAE | 4.185283 | 4.160541 | PASS |
| floor10 relative MAE | 0.282804 | 0.281212 | PASS |
| new light/mod tail failure | 0 | 0 | PASS |

#### 结论

```text
200帧 formal gate 通过
但 weighted RMSE 只提升 0.013655 m/s
提升非常小
5614 帧全量验证尚未完成，旧尝试还 stalled
因此目前不能直接升默认
```

---

### 8.5 Stage5 point-level gated residual 候选

当前 safest nonzero PASS candidate：

```text
checkpoint = cap1p0_seed20260609_w512_l6
gate       = vertical_gap_ge20_not_light
scale      = 1.0
```

#### full-data point dataset

| split | frames | points | baseline RMSE | baseline MAE |
| --- | ---: | ---: | ---: | ---: |
| train | 3930 | 11044 | 15.298961 | 6.807320 |
| val | 842 | 2117 | 13.805729 | 5.870153 |
| test | 842 | 1893 | 9.896785 | 5.217920 |

#### locked test 结果

| metric | baseline | gated Stage5 | delta |
| --- | ---: | ---: | ---: |
| RMSE | 9.896785 | 9.892352 | -0.004433 |
| MAE | 5.217920 | 5.216535 | -0.001385 |
| P95 | 13.157155 | 13.037976 | -0.119179 |
| P99 | 43.020285 | 42.984991 | -0.035294 |
| light RMSE | 5.086997 | 5.086997 | 0.000000 |
| floor10 relative MAE | 0.197422 | 0.197393 | -0.000029 |

#### 关键解释

```text
这是点级别、极窄 gate、极小改进
说明 residual PINN 有信号
但绝不意味着可以全场直接应用
```

---

### 8.6 Stage5 field-v1 smoke 正式结果

根据 `centralized_v1_stage5_field_v1_optimization_plan_20260610.md`，  
Stage5 field-v1 正式 200 帧 smoke 结果：

```text
FAIL
```

#### 关键数值

| Metric | `tp26_thr11_preserve` | Stage5 field-v1 | Direction |
| --- | ---: | ---: | --- |
| Holdout-weighted RMSE | 14.7690356 | 14.7714931 | worse |
| Holdout-weighted MAE | 6.8544542 | 6.8541252 | slightly better |
| Frame mean RMSE | 8.2243094 | 8.2190661 | better |
| Frame mean MAE | 7.0819089 | 7.0812025 | better |
| Frame P95 RMSE | 27.9861110 | 27.9861110 | tie |
| Frame P99 RMSE | 58.7837702 | 58.7837702 | tie |
| 12km+ vector RMSE | 19.9176978 | 19.9417944 | worse |

#### 结论

```text
field 应用结构上是安全的
但 formal promotion gate 没过
因此不能升默认
```

---

### 8.7 Stage5 field-v2 replay 最新状态

根据 2026-06-11 最新状态文档：

1. 修正了 promotion tolerance 的浮点比较问题。
2. field-v2 replay 里出现了 16 个 PASS 变体。
3. 但这些 PASS 变体都满足一个共同条件：

```text
alt12_off
```

也就是：

```text
12km+ residual 完全关闭
```

#### 说明

这意味着：

1. Stage5 的“安全 tiny signal”是存在的。
2. 但只要在 12km+ 上允许 residual，就仍容易带来 real degradation。
3. 所以 Stage5 目前仍只能算 gated candidate，不是默认 full-field method。

---

## 9. 当前已经明确失败的方向：为什么失败

---

### 9.1 SRHA：support_role_height_aware

结果非常明确：

| gate | tp26 | SRHA | result |
| --- | ---: | ---: | --- |
| weighted RMSE | 14.769036 | 20.148615 | FAIL |
| frame P95 | 27.986111 | 34.727103 | FAIL |
| frame P99 | 58.783770 | 86.322454 | FAIL |
| 12km+ RMSE | 19.917698 | 28.454526 | FAIL |
| floor10 relative MAE | 0.282804 | 0.317724 | FAIL |

#### 根因

当前 height/role/shrink-widen 逻辑过粗，高空 role conflict 场景会出现灾难性方向错误。

---

### 9.2 sparse_temporal_gated CMA/NWP

它不是全场强融合，gate 其实已经很窄，但仍 fail：

| gate | tp26 | CMA | result |
| --- | ---: | ---: | --- |
| weighted RMSE | 14.769036 | 14.852237 | FAIL |
| frame P95 | 27.986111 | 26.226386 | PASS |
| frame P99 | 58.783770 | 53.532347 | PASS |
| 12km+ RMSE | 19.917698 | 19.951609 | FAIL |
| light RMSE | 5.195877 | 6.057278 | FAIL |
| light MAE | 4.185283 | 4.490680 | FAIL |
| floor10 relative MAE | 0.282804 | 0.293846 | FAIL |

#### 根因

它能救部分极端 tail，但会污染 3-6km / light wind sparse 点。

---

### 9.3 guarded_vertical_dynamic_v2

200 帧 all-holdout formal gate：

| gate | tp26 baseline | guarded vertical | result |
| --- | ---: | ---: | --- |
| weighted RMSE | 14.769036 | 14.853289 | FAIL |
| weighted MAE | 6.854454 | 6.902063 | FAIL |
| frame P95 | 27.986111 | 28.681533 | FAIL |
| 12km+ vector RMSE | 19.917698 | 20.063442 | FAIL |
| 5-15mps light RMSE | 5.195877 | 5.219127 | FAIL |
| floor10 relative MAE | 0.282804 | 0.284927 | FAIL |

#### 根因

它确实比 SRHA 更保守，也能避免那种灾难性放大；  
但即便如此，动态垂直分层在当前系统下仍会轻微污染：

```text
12km+
light wind
floor10 relative error
```

所以它不适合作为当前默认。

---

### 9.4 point_regime_localization_v1

200 帧 formal gate：

| gate | baseline | candidate | result |
| --- | ---: | ---: | --- |
| weighted RMSE | 14.769036 | 15.075496 | FAIL |
| frame P95 | 27.986111 | 28.145400 | FAIL |
| frame P99 | 58.783770 | 58.861576 | FAIL |
| 12km+ vector RMSE | 19.917698 | 20.284326 | FAIL |
| light wind RMSE | 5.195877 | 5.242838 | FAIL |
| light wind MAE | 4.185283 | 4.192387 | FAIL |
| floor10 relative MAE | 0.282804 | 0.288906 | FAIL |

#### 根因

当前 500m/6min aircraft support 太稀疏：

```text
active support voxel remote current fraction ≈ 0.987
```

也就是说，`nearest_current_distance` 在现在这个任务里不够稳，  
把它直接写进 point-wise localization 反而更容易污染多个 regime。

---

## 10. 误差根因：现在真正卡住项目的是什么

根据多个 Stage4 误差分解文档，当前主误差优先级基本稳定为：

1. `vertical_structure`
2. `representation_error`
3. `sparse_support`
4. `role_conflict`
5. `temporal_weighting`
6. `tail_qc`
7. `localization`

### 10.1 vertical_structure

高空和强垂直结构层很容易被跨层平滑污染。

### 10.2 representation_error

当前比的是：

```text
aircraft point observation
vs
500m / 6min voxel reconstruction
```

它们本来就不是同一个物理尺度，所以误差里天然混有 representation error。

### 10.3 sparse_support

很多点本质上不是“插值”，而是“外推”。  
current support 一旦太远或太少，误差很容易爆。

### 10.4 role_conflict

current 与 context 可能冲突。  
保护 current 是对的，但保护得过头也会损失上下文支撑。

### 10.5 temporal_weighting

context 不是同步观测。  
旧 context 用得太多会 stale；用得太少又会失去支撑。

### 10.6 tail_qc

少量极端点主导 weighted RMSE/P99。  
不能只看 mean，不做 tail audit。

---

## 11. 现在最值得做的方向，不是继续乱调，而是这几条

### 11.1 第一优先：representation-error / reliability 方向

这是当前最稳、最论文友好的方向。

原因：

1. 它能解释为什么某些点风险高。
2. 它不需要强行改变 recon。
3. `tp26_rep_soft_weight_v1` 已经在 200 帧 formal gate 通过。
4. 比 Stage5 或 background rescue 更稳。

### 11.2 第二优先：完整跑完 5614 帧 representation soft-weight 验证

这是目前最应该补上的正式动作。

当前状态：

```text
旧 5614-run 尝试 stalled / incomplete
不能拿 partial 结果当证据
应该 clean retry 到新目录
```

### 11.3 第三优先：继续保留 tail-risk / reliability / no-claim 作为解释层

因为它们能很好地回答：

```text
哪里可信
哪里不可信
哪里是产品 footprint
哪里不能宣称 validated accuracy
```

### 11.4 第四优先：Stage5 只做 gated residual candidate，不做默认替换

当前 Stage5 的正解不是更大模型，而是：

1. 更保守的 gate。
2. 更清晰的 altitude suppressor。
3. 只在 high vertical-gap / non-light / supported regime 做极小 correction。

---

## 12. 产品语义：为什么图上“有风”不等于“有验证精度”

这个项目必须把两个概念分开：

### 12.1 product footprint

意思是：

```text
全国网格上可以生成一张风场产品
或者一张 display-filled 的连续可视化图
```

### 12.2 validated accuracy footprint

意思是：

```text
只有 aircraft holdout 覆盖到的时空点
才能报告 official RMSE/MAE
```

因此正确说法是：

```text
全国重构 = product footprint
局部 holdout = validated accuracy footprint
```

不能说：

```text
全国所有格点都经过 strict holdout 验证
```

---

## 13. 论文当前应该怎么写

根据 `centralized_v1_manuscript_draft_v0_20260610.md` 和 2026-06-11 最新状态：

### 13.1 可以稳定写进论文的主结论

1. `centralized_v1` 建立了一个 role-aware、strict aircraft holdout 的三维风场重构与验证框架。
2. 在固定 200 帧、530 点 strict holdout 对比中，`tp26_thr11_preserve` 相比最早 `baseline_aircraft` 明显提升。
3. 当前验证只对 aircraft holdout 覆盖到的位置成立。
4. 剩余误差主要来自高空、稀疏支撑、role conflict、representation error。
5. Stage5 residual PINN 只有 narrow gated point-level signal，不能当默认方法。

### 13.2 不能写成主结论的东西

1. `tp26_rep_soft_weight_v1` 已经取代默认。
2. Stage5 field-v1 已正式提升全场效果。
3. 全国网格全部有 validated accuracy。
4. 项目已经是运行级低空风切变业务系统。

### 13.3 当前最强的一句话论文主张

```text
centralized_v1 提供了一套以 aircraft strict holdout 为唯一正式 truth 的、可审计的中心化三维风场重构与验证框架。
```

---

## 14. 逐文件提炼：这个目录里每份文件到底讲了什么

### 14.1 `README.md`

角色：Stage4 教师展示包入口。  
最重要信息：

1. 明确了三方法对照：`baseline_aircraft`、`adaptive_v3`、`tp26_thr11_preserve`。
2. 给出 200 帧 strict holdout 主表。
3. 把 truth 边界、motion 非风、CMA 非 truth、display 语义讲得最直白。

### 14.2 `centralized_v1_full_project_handover_20260529.md`

角色：项目级总交接文档。  
最重要信息：

1. 从项目身份、数据入口、Stage1-5 主线，到 full run、ROI、CMA/PINN/Diffusion 都讲了。
2. 明确了 no-holdout 帧要保留但不能进官方 RMSE。
3. 后半段持续追加了 6 月 1 日、2 日、5 日的更新，是一份“会长大的总文档”。

### 14.3 `centralized_v1_manuscript_draft_v0_20260610.md`

角色：论文初稿。  
最重要信息：

1. 给出当前最保守、最适合发文的叙述口径。
2. 明确“validated accuracy 只限 aircraft holdout location”。
3. Stage5 只作为 candidate 叙述，不夸大。

### 14.4 `centralized_v1_stage45_status_handover_20260611.md`

角色：当前最新 Stage4/5 总状态。  
最重要信息：

1. 最新默认仍是 `tp26_thr11_preserve`。
2. `tp26_rep_soft_weight_v1` 200 帧 PASS，但 5614 验证未完成。
3. Stage5 field-v2 replay 只有 tiny safe signal，不是 full-field/default replacement。

### 14.5 `centralized_v1_stage4_20260605_handoff_talking_points.md`

角色：简洁口头交接提纲。  
最重要信息：

1. 明确 SRHA 不要推广。
2. 明确 sparse-temporal CMA 不要推广。
3. 强调 wind-scale 解释不能只看绝对 RMSE。

### 14.6 `centralized_v1_stage4_aircraft_wind_observation_error_model_supplement_20260601.md`

角色：飞机风观测误差模型专项补充。  
最重要信息：

1. 13.64 m/s 不是 aircraft observation error，而是 local consistency / representativeness sigma。
2. de Haan / EMADDC 只能给 observation-error prior，不是直接拿来给 Stage4 RMSE“扣分”。
3. location-derived pseudo wind 不能直接上主线。

### 14.7 `centralized_v1_stage4_error_resolution_plan_20260602.md`

角色：Stage4 误差来源与逐步解决路线图。  
最重要信息：

1. 明确误差优先级不是单一 localization 半径问题。
2. 给出 `vertical_structure -> representation_error -> sparse_support -> role_conflict -> temporal_weighting -> tail_qc -> localization` 的顺序。
3. 这是后续分支设计的“总攻略”。

### 14.8 `centralized_v1_stage4_next_window_tail_risk_confidence_vertical_plan_20260608.md`

角色：Stage4 下一窗口执行计划与结果落地文档。  
最重要信息：

1. tail-risk report-only、confidence v2、guarded vertical、representation soft weight、point-regime localization 全部在这里形成闭环。
2. 明确：representation soft weight PASS；guarded vertical FAIL；point-regime localization FAIL。
3. 对“下一步该做什么、不该做什么”约束很强。

### 14.9 `centralized_v1_stage4_quality_improvement_methods_20260601.md`

角色：Stage4 提升方法菜单。  
最重要信息：

1. 罗列了 obs error、adaptive localization、local OI/3DVar、LETKF 风格、多背景 gating、PINN/diffusion 等方向。
2. 它更像“方法备忘录”，不是最终结论。
3. 后来很多方向都在后续文档里被实测筛掉或保留下来。

### 14.10 `centralized_v1_stage5_field_v1_optimization_plan_20260610.md`

角色：Stage5 field-v1 smoke 后的优化计划。  
最重要信息：

1. 明确 field-v1 formal promotion FAIL。
2. 指出下一步不是更大模型，而是更保守 gate、altitude suppressor。
3. 建议如果 gate-v2 还不过，就先暂停 Stage5，转向 Stage4 representation-error 分支。

### 14.11 `centralized_v1_stage5_next_window_field_v1_smoke_handover_20260609.md`

角色：Stage5 下一窗口 smoke 交接。  
最重要信息：

1. 点级 narrow GPU sweep 找到了唯一非零 PASS 候选。
2. 给出 checkpoint、gate、scale、reproduce command。
3. 强调 default 不改，只能先做 full-field smoke。

### 14.12 `centralized_v1_stage5_residual_pinn_start_plan_20260608.md`

角色：Stage5 理论与实施总起点。  
最重要信息：

1. 明确 Stage5 正确路线是 residual PINN，不是 full-field PINN。
2. 讲清输入、输出、loss、gate、split、防泄漏、训练脚本设计。
3. 是 Stage5 的方法学基石。

### 14.13 `centralized_v1_timepower15_full_handover.md`

角色：较早期的 TimePower15 总交接。  
最重要信息：

1. 最早完整讲清了 7395 帧 / 5614 holdout / 1781 no-holdout 的边界。
2. 把“不能把 no-holdout 0 误差混到主指标里”这件事彻底说透。
3. 是理解项目初期主线很重要的一份文档。

### 14.14 `centralized_v1_weekly_report_stage5_residual_pinn_20260609.md`

角色：Stage5 周报。  
最重要信息：

1. 用周报形式总结了 point-level residual PINN 工作流已经完成哪些模块。
2. 明确 current PASS candidate 的数值、失败候选的类型、下周动作。
3. 对“当前不是 default，只能 smoke”的判断非常清晰。

### 14.15 `pengxu.code-workspace`

角色：VS Code workspace 配置。  
最重要信息：

1. 只说明 workspace 打开的文件夹路径和 Python env manager。
2. 不包含项目方法、结果或指标。
3. 对项目理解几乎无实质影响。

### 14.16 `stage1_to_stage4_pipeline.md`

角色：Stage1-4 全流程说明。  
最重要信息：

1. 是最适合给老师讲流程的一份文档。
2. 从 Stage1 到 Stage4 的“做什么、怎么做、为什么这样做”写得最系统。
3. 对 u/v、motion、radar PNG、truth 边界解释尤其清楚。

---

## 15. 这个目录所有文档合在一起后，真正的项目主线应该怎么理解

### 15.1 项目的主任务

```text
用 sparse aircraft wind observations 在中心化框架下重建三维风场
并且只用 aircraft strict holdout 来做正式验证
```

### 15.2 最重要的方法学贡献

不是“某个 fancy 模型”，而是：

1. 数据角色严格分离。
2. strict holdout 防泄漏。
3. no-holdout 业务价值与官方精度分离。
4. tail / reliability / no-claim / product footprint 语义分离。

### 15.3 当前最稳的技术路线

```text
Stage4 default = tp26_thr11_preserve
```

### 15.4 当前最值得继续投入的方向

```text
representation-error / reliability / soft-weight
```

### 15.5 当前最应该克制的方向

```text
全场 CMA 救援
全场动态 vertical localization
nearest-distance 驱动的 point-wise localization
大范围 residual neural correction
```

---

## 16. 现在最务实的下一步建议

1. 先把 `tp26_rep_soft_weight_v1` 的 5614 帧全量 holdout-only 验证 clean rerun 跑完。
2. 如果 full-5614 也 PASS，再谨慎决定是否把它写成“scaled reliability branch”。
3. Stage5 暂时不要继续重训大模型；先把已有 gate-only/field-v2 结果作为约束。
4. 如果继续 Stage5，只允许：
   - 保守 gate
   - 12km+ suppressor
   - 不改默认 tp26
   - 先 smoke，再 strict pairwise
5. 论文主叙述继续坚持：**centralized_v1 的核心贡献是 auditable aircraft-holdout validation framework**。

---

## 17. 最后一版一句话总括

`centralized_v1` 目前已经建立了一条**逻辑清晰、边界严格、可审计**的中心化三维风场重构主线：Stage1-3 负责把飞机风、位置、运动和雷达背景分角色组织好，Stage4 用 `tp26_thr11_preserve` 在严格 aircraft holdout 下给出当前最稳的正式结果，Stage5 只在极窄 gated residual 候选层面看到很小但真实的增益；真正还没完全解决的，是高空 tail、representation error、sparse support 和 role conflict，而不是“再叠一个更大的模型”。
