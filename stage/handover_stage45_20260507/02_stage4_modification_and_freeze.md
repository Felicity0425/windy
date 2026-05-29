# Stage4 修改、收敛与冻结说明

## 这份文档的作用
这份文档把当前 `Stage4` 的演化过程、关键修改、设计决策和冻结理由整理成一份清晰版说明。

它回答的问题是：

- 为什么 `Stage4` 现在长成这样
- 哪些改动已经落地
- 为什么现在应该冻结而不是继续追更高指标

---

## 一、最初的问题

最初的 `Stage4` 主要有四类问题。

### 1. 运行链路过重
特点：

- 每次跑全量时，`collect / sparse_metrics / outliers / npz_check / keylog` 都跟着跑
- 这些都是后置诊断，不参与主重构
- 会明显拖慢运行链路

### 2. `full_aux_export` 名义上是补导出，实际上在重算
最初它虽然叫“补导出”，但会重新走 `_prepare_frame()` 的大部分逻辑，导致：

- 耗时很长
- 不是真正的后处理补场
- 有可能影响 fast 主结果理解

### 3. Stage4 多卡分片会破坏时序行为
`Stage4` 内部存在：

- `temporal_background`
- `forecast_next_wind_field`
- `trigger_reconstruction`

这意味着它依赖前一帧状态。  
如果像 `Stage3` 一样做 frame-level 分片：

- 会切断 `prev_recon_state`
- 会产生 `first_frame` / `discontiguous_frame_gap`
- 会改变结果

### 4. 重构质量偏保守
基线版本里：

- `recon_conf_mean_avg` 偏低
- `recon_coverage_avg` 偏低
- 一些帧的直接风源被高重叠去重得过空

因此需要做温和提质，但不能为了追 coverage 无限放宽。

---

## 二、基线版本结论

## `fast_single_gpu_baseline_v2`
这是当前 fast 路径的重要基准版本。

典型结论：

- `output_profile=fast`
- `quality_expand_enabled=0`
- `gpu_enabled=1`
- `recon_conf_mean_avg≈0.249393`
- `recon_coverage_avg≈0.113614`
- `fullfield_confidence_spread_p10_p90≈0.474462`
- `outlier_count=0`

这版的意义：

- 锚点保真非常强
- 全场 coverage 偏保守
- 适合作为“稳定但保守”的对照基线

## `fast_single_gpu_baseline_v3_quality`
这是在保守前提下做过一轮提质的版本。

典型结论：

- `recon_conf_mean_avg≈0.2719`
- `recon_coverage_avg≈0.1150`
- 运行耗时略有增长

为什么说它是“温和提升”：

- `conf_mean` 已明显超过 `v2`
- `coverage` 只做了轻微提升，没有暴力拉高
- `fullfield_confidence_spread` 没有塌缩

这说明：

- `Stage4` 可以做有控制的提质
- 但不适合再继续无限放宽

---

## 三、核心代码修改脉络

## 1. fast 主线固定为稳定路径
明确做法：

- `WIND_STAGE4_OUTPUT_PROFILE=fast`
- `WIND_STAGE4_ENABLE_QUALITY_EXPAND=0`

含义：

- fast 是运行主链
- 不是训练前 richest aux 导出链
- 不把最激进的 expand / enhancement 直接混进默认运行版本

## 2. `full_aux_export` 改成真正不走 `_prepare_frame()`
当前实现里：

- 从 fast `npz` 读：
  - `recon_u_3d`
  - `recon_v_3d`
  - `recon_confidence_3d`
  - `recon_mask_3d`
  - `trajectory_3d`
  - `physics_weight_3d`
- 再补：
  - `pinn_divergence_3d`
  - `pinn_smoothness_3d`
  - `hazard_*`
  - `diffusion_condition_4d`
  - `direct_agreement_3d`
  - `direct_source_count_3d`
  - `source_diversity_3d`

这意味着：

- fast 目录只读
- full aux 输出目录独立
- 不再重跑主重构链

## 3. 报告链默认减负，只保留 `readiness`
现在默认：

- `full`
- `full_fast_multi_gpu`
- `full_aux_export`

运行链路只保留：

- `stage3`
- `stage3_summary`
- `stage4`
- `stage4_summary`
- `validate`
- `collect`
- `readiness`

默认不跑：

- `sparse_metrics`
- `outliers`
- `npz_check`
- `keylog`
- `export`

作用：

- 提高主链运行效率
- 报告按需单独跑

## 4. `Stage3` 并行、`Stage4` 单卡的原因

### `Stage3`
- frame-level 相对独立
- CPU / IO 主导
- 适合多进程 shard

### `Stage4`
- 依赖前一帧状态
- 不适合默认多进程分片
- 默认：
  - 单进程
  - 单卡
  - 可配多线程 CPU

## 5. `Stage4` 加入 CPU 线程控制
在脚本层加入了：

- `STAGE3_PARALLEL_SHARDS`
- `STAGE3_CPU_THREADS_PER_WORKER`
- `STAGE4_CPU_THREADS`

并通过环境变量控制：

- `OMP_NUM_THREADS`
- `MKL_NUM_THREADS`
- `NUMEXPR_NUM_THREADS`
- `POLARS_MAX_THREADS`

结论：

- `Stage3` 支持更高 CPU 并发
- `Stage4` 保持单进程逻辑不变，但可以提高 CPU 利用率

## 6. `Stage4` 加入显式模块开关
这一步是为了冻结前“可做消融”。

---

## 四、当前 `Stage4` 模块开关清单

当前已支持：

- `WIND_STAGE4_ENABLE_SUPPORT_FILL`
- `WIND_STAGE4_ENABLE_TEMPORAL_FILL`
- `WIND_STAGE4_ENABLE_RELAX`
- `WIND_STAGE4_ENABLE_PRUNE`
- `WIND_STAGE4_ENABLE_EXPAND`
- `WIND_STAGE4_ENABLE_DIRECT_ANCHOR_RESTORE`
- `WIND_STAGE4_ENABLE_DIRECT_ANCHOR_FORCE`

它们都已经：

- 接到主流程
- 写入启动日志

因此后续做消融时：

- 不需要再改代码
- 只需要换命令

---

## 五、为什么现在建议冻结 `Stage4`

当前 `Stage4` 冻结不是因为它绝对完美，而是因为它已经满足论文前一阶段最重要的 5 个条件。

### 1. anchor fidelity 稳
当前稀疏监督锚点误差已经很强，属于 `Stage4` 的硬优点。

### 2. coverage 温和提升即可
你的数据本身就稀疏，因此：

- 不要求暴力拉高 coverage
- 只要比最初版本有温和提升即可

### 3. confidence 有层次
重点不是单纯抬高 `conf_mean`，而是：

- direct 区域高
- fill 区域低
- 全场 spread 不塌缩

### 4. 运行链路稳定
现在已经形成稳定组合：

- `Stage3` 并行
- `Stage4` 单进程单卡
- 默认不跑重报告

### 5. 已具备消融条件
模块开关已经齐全，可以直接构造 `S0-S6` 版本矩阵。

---

## 六、当前仍已知的边界 / 风险

### 1. 数据稀疏导致 coverage 天花板有限
这是数据条件决定的，不应完全归咎于算法。

### 2. `wind_primary` 高重叠去重仍需关注
在某些帧里，直接风源可能被过度去重，导致：

- `wind_primary=0`
- 重构更依赖 `seed + motion + temporal fill`

这应作为实验观察点保留。

### 3. 多线程 CPU 可能带来极小数值波动
但这不改变核心时序逻辑，只会带来很小的浮点归约差异。

因此：

- 工程上可接受
- 论文实验里要固定线程配置

---

## 七、当前推荐的 `Stage4` 冻结版本定义

## `S5 FinalFast`
定义：

- 作为 `Stage4` 主结果版本
- 用于运行主链
- profile：
  - `fast_balanced`

用途：

- 全量正式运行
- 论文主结果

## `S6 FullAux`
定义：

- 作为训练前导出版本
- profile：
  - `aux_aggressive`

用途：

- 训练前 richer aux fields 导出
- 不作为主运行版本

---

## 八、下一个对话应该避免的坑

1. 不要再无限追更高 coverage  
2. 不要把 `Stage5` 混进 `Stage4`  
3. 不要把 `Stage4` 重新改回多进程分片  
4. 不要在没明确输入目录时单独跑 `stage4_only`  
5. 不要把日志目录当成正式输出目录  

---

## 新窗口接手时的提醒

如果下一个对话要继续往下走，应该优先做：

1. `Stage4` 全量运行结果整理
2. `Stage4` 内部 baseline / ablation
3. 在 `Stage4` 冻结基础上设计 `Stage5`

而不是继续大改 `Stage4` 主重构逻辑。
## 补充：Stage4 CPU 多线程利用说明

### 多核 CPU 对 Stage4 通常会更快
原因：

- `Stage4` 中能吃多核 CPU 的主要是：
  - `polars` 的 filter / group / group_by
  - `numpy / BLAS` 的数组计算和归约
  - CPU fallback 的局部数值核

但它不会线性提速，原因是仍然存在：

- Python loops
- `npz` / `json` 读写
- 单进程时序链

因此：

- `Stage4_CPU_THREADS=6` 通常比 `1` 更快
- 但不会是 6 倍
- 当前推荐把 `6` 作为稳定起点

### 当前所有 Stage4 入口都已统一接入线程环境
当前以下入口都会统一导出：

- `OMP_NUM_THREADS`
- `MKL_NUM_THREADS`
- `NUMEXPR_NUM_THREADS`
- `POLARS_MAX_THREADS`

覆盖入口：

- `RUN_PHASE=stage4_only`
- `RUN_PHASE=full`
- `RUN_PHASE=full_aux_export`
- `RUN_PHASE=full_fast_multi_gpu`

因此后续只要设置：

- `STAGE4_CPU_THREADS=6`

就能在所有 Stage4 入口稳定生效。
