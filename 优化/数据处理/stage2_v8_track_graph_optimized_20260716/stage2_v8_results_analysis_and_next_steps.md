# 大框架 Stage2 v8 Track Graph 结果分析与下一步建议

生成日期：2026-07-16

## 1. 阶段定义

本文的 Stage2 v8 是**大框架 Stage2**：ADS-B 组织、local consistency、clean tracklet、状态平滑和 tracklet graph。它不是 `amdar_stage2_to_6_optimization_plan_20260706.md` 内部的小阶段2。

Stage2 只生成未校准 graph prior，`formal_bridge_accepted_v8` 始终为 false。任何 stitched path 必须经过大框架 Stage3 v13 后才能进入 Stage5。

## 2. 输入与运行口径

- 正式源表：`/data/LFT-W02_data/pengxu/stage1_output/clean_loc.parquet`。
- 输入点数：`19,162,638`，与项目文档记录完全一致。
- 文档指定的 `adsb_qc_v4_rows.parquet` 派生目录已被清理，因此本版本从同一 Stage1 源表重建 v4-compatible 边界审计字段；没有伪造缺失文件。
- `POLARS_MAX_THREADS=25`、`slice_count=25`、`workers=25`。
- exact `tail_norm + flight_norm + service_date_utc` 稳定 hash 分片；25 shards 互斥，每个源点只属于一个 shard。
- identity normalization 与旧链一致：大写并删除非字母数字字符，例如 `B-1353 -> B1353`。
- 输出使用 zstd parquet；没有复制 25 份全量输入。

## 3. 正式结果

### 3.1 点守恒与异常隔离

- input/local rows：`19,162,638 / 19,162,638`，点守恒通过。
- clean rows：`19,154,894`。
- diagnostic excluded rows：`7,744`，仅占输入约 `0.0404%`。
- 被排除点仍保存在 local-consistency 产品中并带异常解释；未从原始证据层删除。

### 3.2 fragmentation 改善

- v4-compatible legacy legs：`2,977,478`。
- v8 clean tracklets：`2,953,850`。
- 净减少：`23,628` 个 fragments。
- fragmentation reduction：`0.7936%`。
- singleton tracklets：`234,439`。

该改善不是通过放宽所有速度/时间边实现，而是通过隔离 isolated spikes、保留 uncertain low-weight 点、重建 clean 边界实现。改善幅度真实但有限，说明数据主体的碎片化并不全部来自单点异常。

### 3.3 Tracklet 分层

| Tier | Tracklets | Points | 语义 |
|---|---:|---:|---|
| `T0_clean_core` | 1,210,173 | 11,817,640 | 稳定核心轨迹，可用于 Stage3 source |
| `T1_clean_short` | 1,275,732 | 6,635,803 | 短但局部一致，可用于 Stage3 source |
| `T2_singleton_supported` | 142,279 | 142,279 | singleton support，不能单独形成 unique |
| `T3_uncertain_fragment` | 325,666 | 559,172 | graph/diagnostic，不能直接 unique |

### 3.4 Graph 产品

- 全部候选 edges：`6,627,625`。
- 宽物理 gate 后 edges：`11,306`。
- short `0-300s`：`2,990`。
- medium `300-900s`：`4,151`。
- long `900-1800s`：`4,165`。
- graph paths：`2,965,156`，其中 clean single paths `2,953,850`、stitched hypotheses `11,306`。
- Stage2 formal bridge accepts：`0`。

## 4. 25-slice 与语义审计

- exact identity/date groups：`357,754`。
- group 跨 slice 最大值：`1`。
- 跨 slice 违规：`0`。
- graph edge 只在 exact identity/date 内生成。
- smoothed states 标记为 `smoothed_observed`；Stage2 没有把 gap prediction 写成 observed point。
- AMDAR 未参与 Stage2 truth，truth/holdout 违规为 `0`。

## 5. 5 个历史 stitched cases 的只读审计

Stage5 v7 的 5 个历史 stitched rejects 对应 4 个唯一 identity/date groups（其中两个批次同属 `B1661/3U3551/2026-02-17`）：

| Identity/date | Clean tracklets | Physical graph edges | 结论 |
|---|---:|---:|---|
| `B1353/MF8286/2026-02-09` | 10 | 0 | 无 Stage2 物理可达 bridge，保持 no-coverage/rejected |
| `B1661/3U3551/2026-02-17` | 4 | 0 | 两个历史批次均无物理 edge，不应强行恢复 |
| `B1355/MF8773/2026-01-28` | 19 | 1 | 存在 294 秒 graph hypothesis，需 Stage3 posterior 与 Stage5 emission 再审计 |
| `B1820/3U6920/2026-02-13` | 4 | 0 | 无物理 edge，保持 rejected |

因此 Track Graph 没有“自动救回 5/5”。只有一个 identity group 产生可继续验证的 hypothesis，这符合 safety-first 设计。

## 6. 是否符合 Stage2 要求

全部 Stage2 硬要求已满足：

- 点守恒：通过。
- 25-slice group locality：通过。
- fragmentation 不恶化：通过，净减少 `23,628`。
- graph candidates 非零：通过，`11,306`。
- Stage2 不提前接受 bridge：通过，formal accepts `0`。
- truth/holdout 违规：`0`。

## 7. 限制与下一步

1. 当前 smoother 是明确标注的 diagonal constant-velocity IMM-style forward/backward covariance smoother，不是假称完整 CTRV/IMM；后续如需更强 maneuver modeling，可在 Stage3 validation 上比较完整 RTS/CTRV。
2. `0.7936%` fragmentation reduction 是有价值但不是数量级突破；真实 no-coverage 不能靠算法消除。
3. `11,306` edges 只是 Stage2 prior。必须使用 Stage3 v13 posterior model，禁止直接按 `bridge_prior_score_v8` 接入 Stage5。
4. 下一步应构建 Stage5 v8 graph candidate audit：prior 229/345 冻结，先审计历史 5 cases、graph-recoverable rejects 和 hard negatives，再决定 unique/mixture/rejected。

