# 大框架 Stage2 v8 Track Graph：稀疏 ADS-B 数据利用率提升完整实施方案

生成日期：2026-07-16

## 0. 文档目的

本文是可直接实施的工程方案，用于从现有单份 ADS-B 点表重建 local-consistency clean tracklets、IMM/Kalman 平滑状态、tracklet graph、stitched path 和概率 mixture，并在新的 bridge-specific pseudo validation 通过后接入大框架 Stage5。

本文中的阶段均指**大框架阶段**：

- 大框架 Stage2：ADS-B 组织、QC、轨迹状态与 track graph；
- 大框架 Stage3：pseudo-AMDAR / association validation；
- 大框架 Stage5：真实 AMDAR-ADS-B support-only matching；
- 大框架 Stage6：时间不确定性传播。

不要把这些编号与 `amdar_stage2_to_6_optimization_plan_20260706.md` 内部“小阶段1-7”混淆。

---

## 1. 当前基线与为什么需要 Track Graph

### 1.1 当前正式安全基线

截至 2026-07-16：

- 大框架 Stage3 v12 Drop-DTW validation 已通过全部 locked-test 门；
- 大框架 Stage5 v7 已通过 safety gate 与 merge target；
- Stage5 当前冻结基线：`229 unique batches / 345 matched rows`；
- 相对 Stage5 v5 `198/251`：unique `+31`，matched rows `+94`；
- Stage6 gate 当前为 `target_branch`；
- AMDAR 仍全部是 support-only，不是 strict truth；
- 旧 `1% / 566 batches` 目标仍未达到，当前约 `0.405%`。

Track Graph 的第一原则是：**不得破坏或覆盖当前 `229/345` 基线**。

### 1.2 现有 ADS-B 数据规模

正式输入：

`/data/LFT-W02_data/pengxu/优化/数据处理/amdar_unified_stage0_1_2_optimized_20260701/stage2_adsb_qc_v4/adsb_qc_v4_rows.parquet`

已确认：

- ADS-B point rows：约 `19,162,638`；
- 当前 leg fragments：约 `2,991,827`；
- tail 数：约 `8,181`；
- exact `tail/flight/date` groups：约 `357,754`；
- singleton legs：约 `247,063`；
- median points per leg：`7`；
- q90 points per leg：`10`；
- 当前 Stage3-ready legs：`13,432`；
- strong match candidates：`13,997`；
- broad candidates：`370,793`。

原始字段已足够构图：

- identity：`tail_norm / flight_norm / service_date_utc`；
- time：`time_utc`；
- geometry：`lat_clean / lon_clean / alt_meters`；
- motion：`heading_deg / ground_speed_ms`；
- local differences：时间、距离、速度、高度变化；
- hard break：speed/gap/position/altitude/time-order；
- 原始 leg：`adsb_leg_id / leg_index_v4`；
- QC：`adsb_qc_flag` 及各类 failure fields。

### 1.3 Track Graph 能解决和不能解决的问题

能解决：

1. 单个异常位置点造成的错误切段；
2. 单个异常时间戳造成的表观高速和错误切段；
3. 短时接收 gap 后的同身份轨迹重连接；
4. singleton/micro tracklet 合并回主轨迹；
5. 同一身份多个可达路径的 posterior mixture；
6. 用状态协方差替代固定 km/m emission 权重。

不能解决：

1. 区域内完全没有 ADS-B 点；
2. 长时间远洋/偏远区域无覆盖；
3. identity 字段本身错误且没有额外证据；
4. 用模型预测替代真实观测；
5. 把 AMDAR estimated time 变成 point truth。

因此 Track Graph 是“恢复已有但被切碎的证据”，不是“创造缺失观测”。

---

## 2. 总体架构

建议新建三个正式脚本：

1. `amdar_unified_stage2_v8_track_graph_20260716.py`
   - 从单份 ADS-B 点表生成 local consistency、clean tracklets、smoothed states、graph edges 和 graph paths。
2. `amdar_unified_stage3_v13_bridge_validation_20260716.py`
   - 对 raw/clean/stitched/mixture states 做 bridge-specific calibration/validation/locked-test。
3. `amdar_unified_stage5_v8_graph_matching_20260716.py`
   - 冻结 Stage3 v13 policy，重新审计 graph 可恢复批次，输出 unique 与 mixture support。

依赖顺序：

```text
Stage2 v4 raw ADS-B points
        ↓
Stage2 v8 local consistency + clean tracklets
        ↓
Stage2 v8 IMM/Kalman smoothed states
        ↓
Stage2 v8 tracklet graph + top-k paths
        ↓
Stage3 v13 bridge-specific validation
        ↓
Stage5 v8 graph matching
        ↓
Stage6 unique / mixture / unmatched 分层时间分布
```

禁止直接从 Stage2 v8 graph 跳到 Stage5 accepted；必须经过 Stage3 v13。

---

## 3. 资源和 25-slice 省空间规则

### 3.1 分片键

Track graph 必须保证同一 identity/date group 不跨 slice：

```python
processing_slice_id = stable_hash(
    tail_norm + "__" + flight_norm + "__" + service_date_utc
) % 25
```

不能按原始行号随机切片，否则相邻 tracklets 会被分到不同进程，无法构图。

### 3.2 空间规则

- `POLARS_MAX_THREADS=25`；
- `slice_count=25`；
- 25 个 slice 是互斥分区，每个 ADS-B 点只出现一次；
- 禁止为每个 slice 复制一份 1,916 万点全量表；
- 使用 `scan_parquet + filter(processing_slice_id) + collect(engine="streaming")`；
- 每个 slice 只写自己的 compact output；
- 最终使用 parquet dataset 或 streaming concat，不生成 25 份全量副本；
- 不覆盖 Stage2 v4 文件；所有 v8 文件写入新目录。

### 3.3 建议输出目录

```text
/data/LFT-W02_data/pengxu/优化/数据处理/
  stage2_v8_track_graph_optimized_20260716/
    run_config.json
    stage2_track_graph_v8/
      local_consistency_points_v8/
      clean_tracklet_points_v8/
      clean_tracklet_summary_v8.parquet
      smoothed_track_states_v8/
      tracklet_graph_edges_v8.parquet
      track_graph_paths_v8.parquet
      graph_state_points_v8/
      stage2_v8_track_graph_report.json
```

`local_consistency_points_v8`、`clean_tracklet_points_v8`、`smoothed_track_states_v8` 和 `graph_state_points_v8` 可以是 25 个互斥 parquet shards；每条输入点只能属于一个 shard。

---

## 4. Stage2 v8 Phase A：数据审计与不可变字段

### 4.1 必须保留的字段

- 原始 identity、日期和时间；
- 原 `adsb_leg_id / leg_index_v4`；
- 原始 QC flags；
- 原始经纬度、高度、航向和地速；
- `raw_row_number` 或稳定 row ID；若输入没有则生成稳定 hash ID；
- `processing_slice_id`；
- 所有 v8 新字段必须使用 `_v8` 后缀，避免覆盖 v4 语义。

### 4.2 输入审计

每个 slice 必须统计：

- rows、identity groups、原 legs；
- null/duplicate/non-increasing timestamps；
- duplicate positions；
- speed、acceleration、turn rate、vertical rate 分布；
- hard break reason 分布；
- singleton/micro/short/medium/long leg 数量；
- 每个 identity/date group 的时间跨度和点密度。

审计结果写入：

`stage2_v8_input_profile.json`

若总行数、identity groups 或关键字段与当前输入不一致，必须停止正式运行并解释。

---

## 5. Stage2 v8 Phase B：Local Track Consistency

### 5.1 局部运动特征

在 exact `tail/flight/date` group 内按 `time_utc` 排序，计算：

- `dt_prev_s / dt_next_s`；
- haversine distance；
- apparent horizontal speed；
- signed vertical rate；
- heading residual；
- along-track acceleration；
- turn rate；
- jerk proxy；
- local median/MAD residual；
- forward residual 和 backward residual。

不得只看单条 edge。每个点至少使用前后各 2–3 个邻点形成局部窗口。

### 5.2 异常类型

每个点/edge 输出互斥或多标签异常：

- `timestamp_duplicate`；
- `timestamp_bias_candidate`；
- `isolated_position_spike`；
- `isolated_altitude_spike`；
- `unreachable_speed_edge`；
- `unreachable_vertical_rate_edge`；
- `real_sampling_gap_candidate`；
- `identity_discontinuity`；
- `plausible_maneuver`；
- `insufficient_context`。

### 5.3 异常处理原则

不得删除原始点。输出三类状态：

- `raw_preserved`：原始证据保留；
- `clean_include`：可用于 clean tracklet；
- `diagnostic_exclude`：隔离但保留解释；
- `uncertain_keep_low_weight`：证据不足，不硬删。

阈值优先使用 robust distribution：median/MAD、phase-conditioned quantiles 和高度条件，而不是固定一刀切。

### 5.4 Local consistency 输出 schema

至少包含：

```text
raw_point_id
tail_norm / flight_norm / service_date_utc
time_utc / lat_clean / lon_clean / alt_meters
heading_deg / ground_speed_ms
raw_adsb_leg_id_v4
dt_prev_s_v8 / dt_next_s_v8
speed_prev_mps_v8 / speed_next_mps_v8
acceleration_mps2_v8
turn_rate_deg_s_v8
vertical_rate_mps_v8
forward_residual_v8 / backward_residual_v8
local_consistency_score_v8
point_anomaly_type_v8
clean_point_role_v8
processing_slice_id
```

---

## 6. Stage2 v8 Phase C：Clean Tracklet 重建

### 6.1 重建原则

从 `clean_include + uncertain_keep_low_weight` 点重新分段，不继承原 v4 leg 边界作为硬边界。

新的 hard break 只允许由以下原因触发：

- 时间倒序且无法纠正；
- exact identity 改变；
- 时间 gap 超过 graph 最大建边窗口；
- forward/backward 都判定物理不可达；
- 连续多个异常点导致状态不可辨识。

单个 isolated anomaly 不应自动把一条轨迹切成两个永久独立 tracklets。

### 6.2 Tracklet 最低要求

输出所有 tracklets，但分级：

- `T0_clean_core`：稳定、足够点数、低残差；
- `T1_clean_short`：短但局部一致；
- `T2_singleton_supported`：singleton 但前后存在可达主轨迹；
- `T3_uncertain_fragment`：可保留为 graph node，但不能单独用于 unique；
- `T4_reject`：身份/时间/物理不可用。

### 6.3 Tracklet summary schema

```text
clean_tracklet_id_v8
tail_norm / flight_norm / service_date_utc
start_time_utc / end_time_utc
point_count
start/end lat/lon/alt
start/end speed/heading/vertical_rate
local_consistency_q50/q90
anomaly_point_count
raw_leg_count_covered
raw_leg_ids_covered
tracklet_quality_tier_v8
stage3_source_allowed_v8
graph_node_allowed_v8
processing_slice_id
```

必须报告 v4→v8 的 fragmentation change：

- 原 legs 数；
- clean tracklets 数；
- singleton 减少量；
- 被合并的原 leg 数；
- 被隔离异常点数；
- 每类原因的变化。

---

## 7. Stage2 v8 Phase D：IMM/Kalman + Smoother

### 7.1 状态定义

建议在局部 ENU/切平面坐标中使用：

```text
x = [east_km, north_km, v_east_km_s, v_north_km_s,
     altitude_m, vertical_rate_m_s]
```

测量：

```text
z = [east_km, north_km, altitude_m]
```

### 7.2 模型模式

最低实现三个模式：

1. `CV_LEVEL`：水平常速度、低垂直率；
2. `CV_ASC_DES`：水平常速度、允许稳定垂直率；
3. `TURN_MANEUVER`：增加转弯过程噪声，适配进离场。

如果实现真正 CTRV/IMM 过于复杂，第一版可以使用三个不同过程噪声矩阵的线性 Kalman IMM，但必须输出 mode probability，不能假称完整 CTRV。

### 7.3 噪声设置

- measurement covariance 根据 local consistency、原 QC 和点密度自适应；
- process covariance 根据 ASC/DES/LVR、速度、转弯率自适应；
- timestamp bias candidate 提高时间/位置等效不确定性；
- uncertain points 低权进入 filter，不直接删除；
- 参数只能在 Stage3 calibration/validation 上确定，不得在 locked-test 或真实 AMDAR 上调。

### 7.4 平滑

每个 clean tracklet 使用：

- forward Kalman/IMM filter；
- backward RTS smoother；
- 输出 smoothed state 和 covariance；
- tracklet 首尾状态必须单独保存，供 graph edge 预测。

### 7.5 状态输出 schema

```text
clean_tracklet_id_v8
state_time_utc
smoothed_lat/lon/alt_v8
smoothed_v_east/v_north/v_vertical_v8
mode_prob_level/asc_des/turn_v8
cov_xx/cov_xy/cov_yy_v8
cov_alt/cov_vertical_rate_v8
state_uncertainty_radius_km_v8
state_source_role_v8 = observed | interpolated_short_gap
```

任何 gap prediction 必须明确标记 `interpolated_short_gap`，不能伪装成观测点。

---

## 8. Stage2 v8 Phase E：Tracklet Graph

### 8.1 Graph node

每个 `graph_node_allowed_v8=true` 的 clean tracklet 是一个 node。

Graph 必须是按时间前向的 DAG：

```text
end_time(node_i) < start_time(node_j)
```

### 8.2 Edge 候选生成

只在 exact `tail_norm + flight_norm + service_date_utc` 内生成边。第一版候选窗口：

- `0 < gap_seconds <= 1800`；
- 如果 gap `<=300s`，进入 short-gap 候选；
- `300–900s` 为 medium-gap；
- `900–1800s` 为 long-gap，只允许高不确定性 hypothesis；
- `>1800s` 不进入正式 stitched unique，只可保留 coverage diagnostic。

### 8.3 Edge 特征

至少计算：

- `gap_seconds`；
- Kalman forward prediction residual；
- backward prediction residual；
- position Mahalanobis distance；
- altitude/vertical-rate Mahalanobis distance；
- speed difference；
- heading difference；
- turn-rate compatibility；
- phase transition compatibility；
- point density before/after gap；
- anomaly/break reason at both ends；
- competing outgoing/incoming edge counts；
- whether original v4 boundary was speed/gap/position/altitude break。

### 8.4 Edge gate

先使用宽物理 gate 生成候选，不在 Stage2 直接宣告 accepted：

- exact identity/date：必须；
- time forward：必须；
- covariance-normalized position residual：有限；
- altitude和速度不可明显物理不可达；
- edge posterior 在 Stage3 v13 冻结前只叫 `bridge_prior_score`。

禁止把 `distance <= speed_limit * gap` 单一规则当作正式 bridge acceptance。

### 8.5 Edge 输出 schema

```text
from_tracklet_id / to_tracklet_id
tail_norm / flight_norm / service_date_utc
gap_seconds
forward_mahalanobis_v8
backward_mahalanobis_v8
position_residual_km_v8
altitude_residual_m_v8
speed_delta_mps_v8
heading_delta_deg_v8
vertical_rate_delta_mps_v8
phase_transition_v8
original_break_reason_v4
bridge_prior_score_v8
physical_candidate_gate_v8
formal_bridge_accepted_v8 = false
```

Stage2 输出中 `formal_bridge_accepted_v8` 必须始终为 false；正式 gate 属于 Stage3 v13。

---

## 9. Stage2 v8 Phase F：Graph Paths 与 Mixture

### 9.1 Path 搜索

对每个 identity/date DAG：

- 使用动态规划/Viterbi或 beam search；
- 保存 top-k，建议 `k=5`；
- path score 由 node quality + edge prior 组成；
- 不提前把 prior score 解释为 calibrated posterior。

### 9.2 输出类型

- `raw_tracklet`：不连接；
- `clean_tracklet`：local consistency 修复后单 node；
- `stitched_hypothesis`：两个及以上 nodes 的候选路径；
- `graph_mixture`：多个竞争路径及归一化 prior weights；
- `unreachable`：无物理候选边；
- `no_coverage`：相关时空区域没有 ADS-B 点。

### 9.3 Stitched state points

gap 中只输出有限频率的预测状态，例如每 `30–60s` 一个 state，并携带 covariance。禁止密集生成看似真实的伪 ADS-B 点。

每个 state 必须包含：

```text
graph_path_id
state_time_utc
state_role = observed | smoothed_observed | interpolated_gap
lat/lon/alt mean
horizontal/vertical covariance
path_prior_weight
source_tracklet_ids
```

---

## 10. Stage3 v13：Bridge-Specific Validation

当前 Stage3 v12 只授权 Drop-DTW partial row exclusion，**不能授权 stitched graph**。必须新建 Stage3 v13。

### 10.1 Case bank

从 Stage3 v8/v12 clean pseudo cases 和真实 Stage5 graph 分布生成：

- clean single-tracklet；
- correct split + reachable bridge；
- correct split + short/medium/long gap；
- wrong same-identity tracklet；
- wrong flight same tail/date；
- competing fork paths；
- isolated position spike 导致假断点；
- timestamp bias 导致假断点；
- altitude spike；
- heading discontinuity；
- physically unreachable bridge；
- missing middle block；
- reverse/local swap/random order；
- bridge前后 phase transition。

必须保存：

- raw points；
- clean points；
- graph nodes/edges；
- row-level truth；
- true edge correspondence；
- true path ID；
- gap state 是否为 prediction。

### 10.2 Split

使用 group-level split，至少按 `tail/date` 隔离：

- calibration；
- validation；
- locked-test。

同一 aircraft/date 不能跨 split。

### 10.3 模型对照

至少比较：

- B0：不允许 bridge；
- B1：旧基础物理 bridge；
- B2：Kalman forward residual；
- B3：forward + backward smoother residual；
- B4：IMM mode + covariance-normalized edge；
- B5：graph top-k + calibrated edge/path posterior。

### 10.4 冻结参数

只允许在 validation 选择：

- maximum formal gap；
- Mahalanobis thresholds；
- process/measurement noise scale；
- edge posterior threshold；
- path posterior threshold；
- unique path margin；
- mixture minimum posterior mass；
- maximum covariance radius；
- interpolated-state maximum fraction。

locked-test 只报告。

### 10.5 Stage3 v13 质量门

必须全部满足：

- wrong-tracklet / wrong-path accepted rate `<=1%`；
- catastrophic bridge rate `<3%`；
- edge posterior ECE `<=0.05`；
- path posterior ECE `<=0.05`；
- 每种 corruption false acceptance `<=2%`；
- same-identity wrong-tracklet false acceptance `<=1%`；
- unreachable bridge false acceptance `<=0.5%`；
- gap prediction coverage calibration 按 short/medium/long 分类型报告；
- clean no-bridge cases 不得明显退化；
- truth/holdout 违规为 0。

如果任一门失败，stitched path 只能作为 diagnostic/mixture，不能进入 Stage5 unique。

---

## 11. Stage5 v8：Graph Matching

### 11.1 回退保护

Stage5 v7 当前 `229/345` 全部冻结。Stage5 v8 只能增量追加：

```text
combined_v8 = frozen_stage5_v7 + safe_graph_incremental
```

不得重新解释、删除或覆盖已有 229 个 unique batches。

### 11.2 第一轮目标集合

先审计，不全量盲跑：

1. 当前 5 个 physical stitched cases；
2. 历史 strict bridge 影响范围中的 Stage5 rejects；
3. `no_candidate_leg` 中存在 graph path 的批次；
4. `best_cost_gt_3` 中 graph state 显著降低 covariance-normalized cost 的批次；
5. 同 identity/date hard negatives；
6. 当前 229 unique 作为 regression protection。

### 11.3 匹配 emission

Stage5 不再只使用：

```text
horizontal_km + 0.001 * vertical_m
```

改为 covariance-normalized emission：

```text
d² = residual_positionᵀ Σ_position⁻¹ residual_position
   + residual_altitude² / variance_altitude
```

同时加入：

- path posterior；
- edge posterior；
- matched fraction；
- contiguous fraction；
- drop fraction；
- interpolated-state fraction；
- path stability；
- candidate/path margin；
- batch-end upper bound。

### 11.4 Stage5 输出分层

#### Unique graph match

必须同时通过：

- exact identity；
- Stage3 v13 bridge/path gate；
- physical/covariance gate；
- unique path posterior/margin；
- Stage3 v12 partial gate（若还发生 row drop）；
- batch-end upper bound；
- truth invariants。

#### Graph mixture support

当多个 path 合理但不唯一：

- 不计 unique accepted；
- 保存 top-k path posterior；
- Stage6 使用 mixture time distribution；
- 报告 entropy/effective path count；
- 不生成单一 `estimated_time_utc` truth。

#### Rejected/unmatched

- 保持 batch interval 或物理约束宽分布；
- 不因为构图存在就强行缩窄。

### 11.5 Stage5 v8 质量门

Safety gate：

- Stage3 v13 全部门通过；
- prior 229 batches 全保留；
- prior overlap/duplicate 为 0；
- 所有新增 exact identity；
- 所有新增 physical + posterior + path gates；
- truth/holdout/time-point-truth 违规为 0；
- 5 个原 stitched cases 只能按新 gate 决定，不保证必须接受。

Utility gate：至少满足其一，才值得形成正式 v8 merge：

- 新增 safe unique `>=3`；或
- 新增 calibrated graph mixtures `>=20`，并在 Stage6 sensitivity 中提供可测量覆盖改善且不损害 strict holdout；或
- singleton/micro fragments 明显减少，且 graph candidate coverage 对 Stage5 rejects 有可解释提升。

不得为了通过 utility gate 降低 safety gate。

---

## 12. Stage6 接入规则

Stage6 必须使用三种不同语义：

### 12.1 Unique graph match

- 使用 path posterior 和 covariance 形成窄但非零时间分布；
- gap prediction covariance 必须传播；
- estimated time 不是 point truth。

### 12.2 Graph mixture

时间分布为：

```text
p(t) = Σ_k path_posterior_k * p(t | path_k)
```

不得先选最大 posterior path 后丢弃其他路径的不确定性。

### 12.3 Unmatched

- 保留 AMDAR batch interval；
- 可加入物理上下界；
- 不使用 graph 中不可达路径缩窄。

最终正式评价仍只使用 strict aircraft holdout。

---

## 13. 实施顺序与检查点

### Step 0：冻结基线

- 复制机器可读路径引用，不复制数据；
- 确认 Stage5 v7 `229/345`；
- 写 baseline manifest；
- 验证 truth/holdout invariant。

### Step 1：约 1% 输入点/identity groups 小样本 smoke

- 选 25 个 slice 中每个 slice 少量 identity groups，总规模约为输入的 1%；这里的“1%”是 smoke 数据抽样比例，不是 `566 batches` 的旧利用率目标；
- 验证 local features、clean tracklets 和 graph DAG；
- 不跑 Stage5 acceptance。

### Step 2：严格 bridge audit subset

- 只处理 5 个 known stitched cases；
- 加入同 identity/date hard negatives；
- 检查状态、协方差、edge features 和 competing paths。

### Step 3：Stage3 v13 case bank

- 先生成 calibration/validation/locked-test；
- locked-test 一次冻结；
- 不允许边跑真实 Stage5 边调阈值。

### Step 4：Stage2 v8 全量 25-slice

- 每个 slice 互斥处理；
- 完成后核对总输入点守恒；
- 输出 compact shards 和全局 summary。

### Step 5：Stage3 v13 正式验证

- 选择 policy；
- locked-test 报告；
- 失败则停止 unique branch。

### Step 6：Stage5 v8 小集合审计

- 5 known stitched；
- graph recoverable rejects；
- hard negatives；
- prior 229 regression。

### Step 7：Stage5 v8 扩展

只有小集合满足 safety + utility gate 才扩展到全 graph candidate scope。

### Step 8：Stage6 sensitivity

至少比较：

- S0：当前 Stage5 v7；
- S1：v7 + graph unique；
- S2：v7 + graph unique + graph mixture；
- S3：关闭高 covariance/long-gap paths；
- S4：关闭 singleton-supported paths。

正式选择依据是 strict aircraft holdout，不是 AMDAR 自身拟合度。

---

## 14. 失败回退矩阵

| 失败现象 | 解释 | 回退动作 |
|---|---|---|
| local consistency 删除过多 | 阈值过硬 | 改为 uncertain low-weight，不直接删除 |
| singleton 数不降反升 | 重分段逻辑仍过碎 | 检查 isolated anomaly 是否被当 hard break |
| edge candidates 爆炸 | 窗口/identity gate 太宽 | 保持 exact identity/date，缩小时间和 covariance gate |
| same-identity wrong path 高 | graph competition 未建模 | 增加 top-k path margin/posterior，不放宽 |
| posterior ECE 高 | calibration 不匹配 | 重新做 validation calibration，不动 locked-test |
| 5 stitched 仍全拒绝 | 可能本来就不可靠 | 保持 rejected，不视为失败 |
| unique 增量少但 mixtures 增加 | 稀疏数据的合理结果 | 在 Stage6 做 mixture sensitivity |
| strict holdout 变差 | support 过强或 covariance 过窄 | 回退高 uncertainty/long-gap/singleton branches |
| 仍达不到 1% | 真实覆盖不足 | 新增 ADS-B/ADS-C，不继续放宽 graph gate |

---

## 15. 禁止操作

- 不得覆盖 Stage2 v4 输入或 Stage5 v7 基线；
- 不得把 25 slices 做成 25 份全量复制；
- 不得跨 identity/date 建 edge；
- 不得把 Kalman prediction 写成 observed ADS-B；
- 不得未经 Stage3 v13 接受 stitched path；
- 不得在 locked-test 上选阈值；
- 不得把 graph mixture 计为 unique；
- 不得取消 batch-end upper bound；
- 不得把 AMDAR accepted/estimated time 改成 strict truth；
- 不得以达到 1% 为理由放宽 wrong-path safety gate。

---

## 16. 最终交付物

Stage2：

- 正式脚本；
- local consistency points；
- clean tracklets；
- smoothed states + covariance；
- graph edges；
- top-k graph paths；
- graph state points；
- report、run config、结果分析。

Stage3：

- bridge case bank；
- raw/clean/stitched row truth；
- calibration/validation/locked-test；
- edge/path posterior model；
- corruption 与 hard-negative reports；
- quality gate JSON；
- 结果分析。

Stage5：

- graph candidate scores；
- unique incremental matches；
- graph mixtures；
- row/path diagnostics；
- combined match product；
- Stage6 gate；
- 结果分析。

项目级：

- 联合结果与下一步；
- 新的下一智能体交接文档；
- 明确说明是否满足 safety gate、utility gate、Stage6 sensitivity 和旧 1% 目标。

---

## 17. 成功定义

本任务成功不等于“5 个 stitched cases 全部接受”，而是：

1. 从现有 ADS-B 中恢复被错误切碎的可用轨迹证据；
2. 对 unique、mixture、unmatched 提供不同且正确的语义；
3. Stage3 bridge locked-test 安全；
4. Stage5 prior `229/345` 不回退；
5. 新增证据不违反 truth/holdout；
6. Stage6 strict holdout 不恶化，最好改善；
7. 对无法恢复的数据明确判定为 no-coverage，而不是伪造轨迹。
