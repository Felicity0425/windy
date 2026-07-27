# Stage5 V5 最终运行结果分析与下一步建议

生成日期：2026-07-14

## 最终结论

Stage5 已达到当前数据和已验证候选策略下的**安全最优状态**。原 2026-07-13 结果存在候选作用域遗漏，修复并加入独立验证的 tiny-leg 分支后，accepted batches 从 `157` 提升到 `198`，accepted rows 从 `203` 提升到 `251`。全部安全门通过，但原 `1%` 数量目标仍不通过。

## 运行结果

- AMDAR batches：`56521`；
- candidate rows：`231172`；
- accepted batches：`198`；
- accepted rows：`251`；
- accepted fraction：`0.3503%`；
- no-candidate batches：`1368`；
- grades：`A=7, B=41, C=150`；
- identity：v4 strong exact `86`，v9 micro `100`，v10 tiny `12`。

相对版本变化：

- v4：`86 batches / 118 rows`；
- 原 v5：`157 / 203`；
- 修复全 rejected micro scope：`186 / 239`；
- 最终 micro + tiny：`198 / 251`。

最终结果保留 v4 的 `86/86`、原 v5 的 `157/157` 和全-scope micro 版本的 `186/186` accepted batches，没有回退。

## 数据利用率改善

修订前只审计 no-candidate micro 范围；最终对全部 `56435` 个 v4 rejected batches 执行候选扩展：

- 5-9 点 micro：`173307` candidate rows / `52704` batches；
- 2-4 点 tiny：`12474` candidate rows / `11113` batches；
- 候选 pair 重复数：`0`；
- 最终 no-candidate 从原 v4 的 `27775` 降至 `1368`。

这说明候选可用性已基本释放，剩余瓶颈主要是实际空间几何不一致，而不是未搜索到 leg。

## 匹配质量

198 个 accepted batches 的诊断分布：

- best cost：p50 `0.677`，p90 `1.185`，max `1.832`；
- cross-track q90：p50 `0.676 km`，p90 `1.141 km`，max `1.476 km`；
- vertical q90：p50 `1.524 m`，p90 `206.87 m`，max `762 m`；
- sampling gap max：p50 `61 s`，p90 `69 s`，max `537 s`；
- max projected after batch end：p99 `54.65 s`，max `72.97 s`。

扩展分支采用更窄的 v9/v10 门；较宽的最大值来自被冻结保留的 v4 已验证 C-grade 边界。

## 安全与真值边界

全部检查通过：

- Stage3 v9 micro gate：`true`；
- Stage3 v10 tiny gate：`true`；
- Stage4 v3 gate：`true`；
- batch diagnostics：`56521/56521` 且 batch id 唯一；
- accepted match batches：`198`，accepted rows：`251`；
- `effective_strict_truth=true`：`0` 行；
- `holdout_eligible=true`：`0` 行；
- `estimated_time_is_strict_point_truth=true`：`0` 行；
- micro confidence `<=0.40`；
- tiny confidence `<=0.30`；
- 所有 accepted rows 的 usage role 均为 support-only。

## 为什么数量目标仍不通过

`1%` 的一致门槛需要 `566` 个批次，最终只有 `198`，差 `368`。主要拒绝原因：

- `best_cost_gt_3`：`48615`；
- Stage4 T4：`3026`；
- monotonic violation：`1961`；
- no candidate：`1368`；
- projected after batch end：`1048`；
- cross-track 超界：`158`；
- validation compound gate：`63`；
- Stage1 blocked：`60`；
- vertical 超界：`24`。

其中主瓶颈 `best_cost_gt_3` 是 AMDAR 批次空间位置与对应 ADS-B leg 的真实几何不一致。继续放宽 cost/cross-track、取消 monotonic、忽略 batch-end 上界、接纳 T4 或 date-shift 未验证候选，都会越过当前 pseudo validation 和数据语义边界，不能作为“提高利用率”的合法手段。

## Stage6 决策

Stage6 target branch 不允许。只允许 conservative diagnostic：

1. 仅把 `251` 条 accepted rows 作为窄时间分布 support-only seeds；
2. rejected/unmatched AMDAR 保持批次区间或物理约束分布；
3. 明确报告 Stage5 target miss；
4. 不把 `estimated_time_utc` 或 batch end 当逐点真值；
5. 不改变 AMDAR strict truth/holdout 状态。

## 真正继续提高 Stage5 的前置条件

如果必须达到 `>=1%`，需要改变上游可观测证据，而不是继续调 Stage5 阈值：

1. 增加相同日期、机尾和航班覆盖的原始 ADS-B 数据源；
2. 基于新原始证据重新生成 service date / flight identity；
3. 重新运行 Stage2 leg construction 与 QC；
4. 对新增候选策略重新执行 Stage3 validation/locked-test；
5. 再运行 Stage4 confidence 与 Stage5。

在上游候选宇宙没有实质变化前，本结果是进入 Stage6 conservative diagnostic 前应冻结的 Stage5 产品。
