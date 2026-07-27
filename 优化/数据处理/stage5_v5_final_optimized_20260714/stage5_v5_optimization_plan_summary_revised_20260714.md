# Stage5 V5 最终修订优化方案

生成日期：2026-07-14

## 阶段映射

本工作是**大框架 Stage5：真实 AMDAR-ADS-B matching**，对应 Stage2-6 优化计划中的**小阶段/优化计划阶段4**。下一步优化计划阶段5才是大框架 Stage6 时间不确定性建模。

## 原方案发现的问题

2026-07-13 版本虽然完成了 5-9 点 micro-leg 的专项 pseudo validation，但真实 Stage5 只把该候选分支应用到 v4 的 `no_candidate_leg` 批次。这会遗漏“已有 v4 候选、但该候选几何很差，同时存在更好的已验证 micro leg”的批次。

全量审计结果：

- v4 rejected batches：`56435`；
- 原 no-candidate 范围的 micro candidates：`96178` 行 / `25967` 批次；
- 被遗漏的已有候选范围：`77129` 行 / `26737` 批次；
- 全 rejected 范围 micro candidates：`173307` 行 / `52704` 批次。

因此，候选扩展必须覆盖全部 v4 rejected batches，同时冻结并保留 v4 已接受的 86 个批次。

## 最终候选策略

### 1. v4 基线候选

- 保留原 exact `tail_norm + flight_norm + service_date_utc` 候选；
- A/B/C 门限、monotonic、batch-end、Stage1/Stage4 gate 不变；
- 86 个 v4 accepted batches 全部保留。

### 2. 5-9 点 micro-leg

- exact tail + flight + service date；
- `point_count=5-9`；
- 无 Stage2 v7 core hard failure；
- `stage2_v7_weighted_score>=0.90`；
- Stage3 v9 validation-selected gate：`cost<=2`、`cross_track_q90<=1.0km`、`vertical_q90<=500m`、`sampling_gap<=600s`、多候选时 `ambiguity>=1.5`；
- 仅 C 级，confidence cap `0.40`，support-only。

### 3. 2-4 点 tiny-leg

- exact tail + flight + service date；
- `point_count=2-4`；
- 只允许 point-count 本身造成 core hard failure，其他核心失败全部禁止；
- `stage2_v7_weighted_score>=0.65`；
- pseudo 生成器新增小批次 `[1,3]` case 支持；
- Stage3 v10 validation/locked-test 独立通过；
- 使用同一保守复合门；
- 仅 C 级，confidence cap `0.30`，support-only。

## 运行口径

- `POLARS_MAX_THREADS=25`；
- `slice_count=25`；
- `workers=25`；
- `candidate_topk=10`；
- 单份 compact candidate/output tables；
- ADS-B point table 复用一次；
- scorer 中间结果放 `/tmp`；
- 不生成 25 份全量中间数据。

## 最终验收标准

安全门必须全部通过：

- Stage3 v9 micro gate；
- Stage3 v10 tiny gate；
- Stage4 v3 next-window gate；
- 56521 个批次诊断完整且唯一；
- accepted rows 全部有 matched leg；
- AMDAR strict truth 和 holdout 均为 0；
- estimated time 不是 point truth；
- micro/tiny 全部 exact identity、C 级、受各自 confidence cap 和复合门约束。

数量目标仍按一致口径：`accepted_batches>=566` 且 accepted fraction `>=1%`。如果安全门通过而数量门不通过，只允许 Stage6 conservative diagnostic，禁止通过放宽真实匹配边界伪造达标。
