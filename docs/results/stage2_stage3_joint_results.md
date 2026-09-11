# 大框架 Stage2 v8 + Stage3 v13 联合结果与下一步

生成日期：2026-07-16

## 1. 最终结论

大框架 Stage2 v8 和 Stage3 v13 已按 `25-slice / POLARS_MAX_THREADS=25 / workers=25` 正式全量运行并完成迭代修正。

- Stage2：全部工程与语义 gate 通过。
- Stage3：全部 locked-test hard quality gate 通过。
- truth/holdout 违规：`0`。
- 当前可以进入 **Stage5 v8 小集合 graph audit**，但不能跳过 Stage5 safety/utility gate 直接合并。

## 2. Stage2 核心结果

- 处理 ADS-B 点：`19,162,638`，守恒通过。
- diagnostic exclude：`7,744`，原始证据仍保留。
- legacy-compatible legs：`2,977,478`。
- clean tracklets：`2,953,850`。
- fragmentation 净减少：`23,628`，改善 `0.7936%`。
- physical graph edges：`11,306`。
- exact identity/date groups：`357,754`，跨 slice 违规 `0`。
- Stage2 formal bridge accepts：`0`。

## 3. Stage3 核心结果

- case bank：`151,951`。
- locked-test：`27,599` cases。
- wrong-tracklet/path：`0.0827%`。
- catastrophic：`0.0645%`。
- edge/path ECE：`0.000321 / 0.000321`。
- max corruption false acceptance：`0.8621%`。
- same-identity wrong-tracklet：`0.8621%`。
- unreachable bridge：`0%`。
- 全部硬质量门通过。

## 4. 数据利用率是否“极大提高”

应分两层解释：

1. **Stage2 证据利用率确实提高**：恢复 `23,628` 个被兼容 v4 边界切碎的 fragments，并生成 `11,306` 个可校准 graph hypotheses；这比继续扩大 Stage5 时间窗或 naive bridge 更安全、可解释。
2. **尚不能宣称 Stage5 unique 利用率极大提高**：本任务未运行 Stage5 v8，且历史 5 stitched rejects 中只有 1 个 identity group 产生物理 graph edge。真实 no-coverage 仍占主导，不能用放宽阈值伪造利用率。

因此，Stage2/3 已达到进入 Stage5 前的安全和工程要求；最终 unique/mixture utility 必须由 Stage5 v8 与 Stage6 strict holdout sensitivity 决定。

## 5. 必须冻结的内容

- Stage5 v7 prior：`229 unique batches / 345 matched rows`。
- Stage3 v12 Drop-DTW partial policy。
- Stage3 v13 model、Platt 参数、physical gates 和 `maximum formal gap=1800s`。
- AMDAR strict truth rows：`0`。
- AMDAR holdout eligible rows：`0`。
- interpolated graph states 不是 observed truth。

## 6. 下一步建议

1. 实现 `amdar_unified_stage5_v8_graph_matching_20260716.py`。
2. 第一轮只审计历史 5 stitched、graph-recoverable rejects、hard negatives 和 prior 229 regression。
3. covariance-normalized emission 必须读取 Stage2 covariance；bridge/path posterior 必须读取 Stage3 v13 model。
4. 输出 unique、mixture、rejected；mixture 不计 unique。
5. 若小集合 safety + utility 通过，再扩展 graph candidate scope并运行 Stage6 S0-S4 sensitivity。

