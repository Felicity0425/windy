# 研究生周报（2026-06-19 至 2026-06-25）

姓名：彭旭  
方向：飞机观测风场重建 / Stage4-Stage5 优化  
本周主题：完成 `P0` 前置审计、跑通 `S4-CMA-M1` 轻量 demo，并启动独立 `GFS forecast` 背景下载链路

---

## 一、本周进展概述

本周的工作重点不是盲目继续调参，而是先把 Stage4 后续优化必须依赖的“前置条件、可用背景、误差上限和产品化分支”系统梳理清楚。围绕这一目标，我本周完成了以下四块核心工作：

1. 完成了 `CMA/CRA40` 数据资产审计，确认本地再分析资料的可读性、变量完整性、层数覆盖和时间覆盖。
2. 完成了 `P0-LEAK` 审计，明确 `CMA-RA` 本质上是再分析/分析产品，暂时不能直接当作“严格独立背景”用于 `OI`（最优插值）或 `innovation`（创新量）分析。
3. 完成了 `P0-FLOOR` 工程版误差地板估计，量化当前系统距离理论可达水平还有多大空间，避免后续进入低效调参。
4. 跑通了 `S4-CMA-M1` 轻量 demo：采用 `25` 路并行完成 `200` 帧 baseline 复现实验，并在 `6` 个代表帧上实现 `display-only low-confidence background fill` 产品链路。

同时，本周还启动了新的独立背景路线：放弃直接将 `CMA-RA` 作为 `OI` 背景，改为构建 `GFS forecast` 历史背景下载链路，并已完成脚本开发、断点续跑与部分数据落盘。

本周整体工作量较大，既包含文档和科学口径审计，也包含代码开发、批量实验、日志核查、可视化、背景数据管线改造和外部数据下载联调。

---

## 二、本周详细工作安排与完成情况

## 2.1 文档阅读与计划对齐

本周首先系统梳理并比对了以下文档，以明确项目当前目标、边界条件和可推进顺序：

- [centralized_v1_ultimate_summary_20260612.md](/data/LFT-W02_data/pengxu/workflow/centralized_v1_docs/new_window_project_handover_20260529/centralized_v1_ultimate_summary_20260612.md)
- [centralized_v1_stage45_oi_cma_fusion_actionable_plan_20260614.md](/data/LFT-W02_data/pengxu/workflow/centralized_v1_docs/new_window_project_handover_20260529/centralized_v1_stage45_oi_cma_fusion_actionable_plan_20260614.md)
- [centralized_v1_stage45_literature_backed_optimization_plan_20260612.md](/data/LFT-W02_data/pengxu/workflow/centralized_v1_docs/new_window_project_handover_20260529/centralized_v1_stage45_literature_backed_optimization_plan_20260612.md)
- [plan_0625_executable.md](/data/LFT-W02_data/pengxu/workflow/plan/plan_0625_executable.md)
- [plan_0625_summary_and_S4-CMA-M1_runbook.md](/data/LFT-W02_data/pengxu/workflow/plan/plan_0625_summary_and_S4-CMA-M1_runbook.md)

这一阶段的目的，是把“该做什么”和“什么现在不能做”先分清楚。最终结论是：本周不宜直接推进 `S4-OI-*`，而应先完成 `P0-CMA / P0-LEAK / P0-FLOOR / S4-CMA-M1`。

## 2.2 完成 `P0-CMA`：再分析背景数据质量审计

为验证 `CMA/CRA40` 是否具备继续使用的基础条件，本周新增了：

- [verify_cma_grib.py](/data/LFT-W02_data/pengxu/stage/centralized_v1/core/verify_cma_grib.py)

该脚本完成了以下检查：

- 盘点本地 `CMA` 目录的所有文件数量和时间覆盖。
- 抽样读取 `GPH / RHU / TEM / VVP / WIU / WIV` 六类变量，确认 `GRIB2` 文件可读。
- 检查变量层数、经纬度范围、气压层高度范围。
- 检查 `200` 帧和 `5614` 帧时间列表是否都能在 `CMA` 时间序列中找到有效前后括号时次。

关键结果如下：

- 本地 `CMA` 数据总文件数：`773`
- 时间覆盖：`2026-01-23 00Z` 到 `2026-02-24 00Z`
- 抽样读取成功：`18 / 18`
- 风场主变量 `WIU/WIV` 时间覆盖完整：`129` 个时次
- 唯一已知缺口：`2026022012` 缺少 `GPH`
- `200` 帧与 `5614` 帧都能找到有效时间括号，无超出库存范围情况

这一步解决了“背景数据能不能正常用”的问题。结论是：`CMA` 数据本身可读、层数充足、时间覆盖满足当前实验；但存在一个可记录的数据缺口，后续做更严格垂直分析时需要注意。

对应审计结果见：

- [cma_grib_verify_report.json](/data/LFT-W02_data/pengxu/优化/stage4_cma_m1_light_demo_20260625/reports/cma_grib_verify_report.json)

## 2.3 完成 `P0-LEAK`：背景独立性与数据泄漏风险审计

本周重点之一，是回答一个核心问题：`CMA-RA` 能不能安全拿来做 `OI`（最优插值）和 `innovation`（创新量）分析？

这里需要先解释两个概念：

- `OI`（Optimal Interpolation，最优插值）：本质上是将“背景场”和“观测”按各自可信度加权融合，得到分析场。公式可写为 `x_a = x_b + K(y - Hx_b)`，其中 `x_b` 是背景，`y - Hx_b` 是创新量。
- `innovation`（创新量）：指 `观测 - 背景`。它反映背景场相对于真实观测偏差有多大，是诊断背景是否有价值的重要量。

这两类分析有一个前提：**背景必须尽量独立于评估所用 holdout 观测**。否则，如果背景里已经同化了同一批飞机风，那么再去计算 `观测 - 背景`，会把“背景偷看了真值”后的结果误当成真实性能，从而高估方法有效性。

本周我完成了两条审计：

1. `CMA-RA` 产品属性审计  
2. 项目自有观测数据是否可充当独立背景的审计

新增/整理的报告包括：

- [cma_independence_report.md](/data/LFT-W02_data/pengxu/优化/stage4_cma_m1_light_demo_20260625/reports/cma_independence_report.md)
- [own_data_p0_leak_audit_20260625.md](/data/LFT-W02_data/pengxu/优化/stage4_cma_m1_light_demo_20260625/reports/own_data_p0_leak_audit_20260625.md)

关键结论：

1. 官方页面和手册明确说明 `NAFP_CRA40_FTM_6HOR` 属于 `CMA-RA` 再分析产品，且使用 `三维变分` 同化。
2. 因此它不能被简单视为“纯预报背景（pure forecast background）”。
3. 当前没有证据证明这批 `2026` 年 `CRA40 FTM` 资料与本项目 strict holdout aircraft wind 完全独立。
4. 因而本周只能判定：
   - `CMA` 可以用于 `M1 display-only` 的弱背景填充。
   - `CMA` 暂时不能用于 `OI / innovation / Desroziers` 级别的严格独立背景论证。
5. 自有数据（`amdar / turb / location / Stage2 / Stage3`）可以继续作为训练观测，但不能直接替代独立背景。

也就是说，本周把 `P0-LEAK` 从“模糊怀疑”推进成了“有证据的审计结论”，虽然还没有彻底放行，但方向已经明确：后续若要推进 `OI`，应优先接入 `GFS forecast` 这类更容易论证独立性的外部背景。

## 2.4 完成 `P0-FLOOR`：误差地板估计

为了避免后续陷入“误差已经接近可达下限，却继续大量调参”的低效局面，本周新增了：

- [centralized_stage4_error_floor_estimate.py](/data/LFT-W02_data/pengxu/stage/centralized_v1/core/centralized_stage4_error_floor_estimate.py)

这一步的核心思想是：先估计当前系统误差里有多少是“理论上还可优化的部分”，有多少已经接近硬天花板。

这里的“误差地板（error floor）”可以通俗理解为：**在当前观测噪声、邻近代表性误差和任务定义不变的情况下，模型再怎么改，也很难低于的误差水平。**

本周得到的工程版结果如下：

- 当前 baseline vector RMSE：`14.7690 m/s`
- 估计的 local proxy vector floor：`11.1126 m/s`
- 当前系统距离该地板仍有：`3.6564 m/s`
- 相当于仍存在约 `25%` 左右的优化空间

其中最重要的分层发现是高空：

- `12km+` 当前 RMSE：`19.9177 m/s`
- `12km+` proxy floor：`14.1689 m/s`

这说明：

- 系统整体仍有改进空间，但不是无限大。
- 后续最值得发力的方向仍然是 `12km+` 高空稀疏区域。
- 低层和轻风指标已经相对接近稳定区，不宜用激进方法去牺牲它们。

对应结果见：

- [stage4_error_floor_estimate.md](/data/LFT-W02_data/pengxu/优化/stage4_cma_m1_light_demo_20260625/reports/stage4_error_floor_estimate.md)
- [stage4_error_floor_estimate.json](/data/LFT-W02_data/pengxu/优化/stage4_cma_m1_light_demo_20260625/reports/stage4_error_floor_estimate.json)

## 2.5 跑通 `S4-CMA-M1`：轻量 200 帧 demo 与代表帧产品分支

本周按“先轻量验证，再决定是否大规模写盘”的原则，完成了 `S4-CMA-M1` 的轻量化实施：

- 主跑：`200` 帧、`25` 路并行、`metrics-only`
- 代表帧：仅选择 `6` 个关键时间做 `display-fill`、可视化和产品逻辑验证

新增 runbook：

- [stage4_cma_m1_light_demo_20260625.sh](/data/LFT-W02_data/pengxu/workflow/plan/stage4_cma_m1_light_demo_20260625.sh)

### 2.5.1 200 帧 baseline 复现结果

在不生成大量全量 `npz` 的前提下，本周先做了 `metrics-only` 主跑，确认当前流程没有跑偏。

核心指标如下：

| 指标 | 结果 |
| --- | ---: |
| holdout points | 530 |
| vector RMSE | 14.7690 |
| vector MAE | 6.8545 |
| frame mean RMSE | 8.2243 |
| frame P95 RMSE | 27.9861 |
| frame P99 RMSE | 58.7838 |
| `12km+` RMSE | 19.9177 |
| light RMSE | 5.1959 |
| light MAE | 4.1853 |
| floor10 relative MAE | 0.2828 |

这说明：

- `25` 路并行口径正确。
- 轻量化运行没有破坏 baseline。
- 可以把本次结果当作后续所有 Stage4 候选方案的对照基线。

对应结果见：

- [demo_summary_20260625.json](/data/LFT-W02_data/pengxu/优化/stage4_cma_m1_light_demo_20260625/reports/demo_summary_20260625.json)
- [stage4_point_departures.csv](/data/LFT-W02_data/pengxu/优化/stage4_cma_m1_light_demo_20260625/tp26_metrics_only_200_25w/stage4_point_departures.csv)

### 2.5.2 `M1 display-only` 产品链路验证

本周在 `6` 个代表帧上，完成了 `M1` 逻辑验证：

- `cma_fusion_mode = off`
- `display_fill_mode = low_conf_background`
- `display_confidence_cap = 0.20`

这里需要解释一个概念：

- `display-only background fill`：只把背景场用于“显示层补全”，即为了得到更完整的风场图像，让空白区域也有一个低置信度的显示值；但它**不进入官方评估的 `recon_u / recon_v / recon_conf / recon_mask`**，因此不影响 strict holdout 官方 RMSE。

代表帧结果：

- 背景填充比例：`97.72%` 到 `98.49%`
- 平均填充比例：`98.16%`
- 背景填充区最大显示置信度：`0.20`
- 所有代表帧的 `display_source_code_2` 均符合 `low_confidence_weak_background_display_only`

说明：

- `M1` 已经跑通“完整图像展示 + 明确低置信标注”的产品线。
- 该方案在视觉层面改善了大面积空白区域的问题。
- 同时遵守了本项目红线：**背景填充区不进入官方 RMSE**。

对应核查文件：

- [m1_promotion_checklist.json](/data/LFT-W02_data/pengxu/优化/stage4_cma_m1_light_demo_20260625/reports/m1_promotion_checklist.json)
- [stage4_visual_summary.json](/data/LFT-W02_data/pengxu/优化/stage4_cma_m1_light_demo_20260625/representative_visuals/stage4_visual_summary.json)

建议在周报或汇报中插入以下图片：

- [20260131123000_centralized_stage4_slices.png](/data/LFT-W02_data/pengxu/优化/stage4_cma_m1_light_demo_20260625/representative_visuals/20260131123000_centralized_stage4_slices.png)
- [20260207001200_centralized_stage4_slices.png](/data/LFT-W02_data/pengxu/优化/stage4_cma_m1_light_demo_20260625/representative_visuals/20260207001200_centralized_stage4_slices.png)
- [20260211031200_centralized_stage4_diagnostics.png](/data/LFT-W02_data/pengxu/优化/stage4_cma_m1_light_demo_20260625/representative_visuals/20260211031200_centralized_stage4_diagnostics.png)
- [20260223133000_centralized_stage4_diagnostics.png](/data/LFT-W02_data/pengxu/优化/stage4_cma_m1_light_demo_20260625/representative_visuals/20260223133000_centralized_stage4_diagnostics.png)

## 2.6 启动独立背景路线：`GFS forecast` 历史数据下载管线

由于 `CMA-RA` 不能直接放行到 `OI` 背景，本周新开了一条更合理的路线：使用 `GFS forecast` 历史预报场作为未来 `OI` 和 `innovation` 分析的候选独立背景。

本周新写了：

- [download_stage5_gfs_aws_cached_batch.py](/data/LFT-W02_data/pengxu/stage/download_stage5_gfs_aws_cached_batch.py)
- [stage4_gfs_historical_background_200_20260625.sh](/data/LFT-W02_data/pengxu/workflow/plan/stage4_gfs_historical_background_200_20260625.sh)

为了提高效率，本周没有采用“200 帧逐帧直接下载”的笨方法，而是做了以下工程优化：

1. **按唯一源去重**  
   将 `200` 帧映射到 `cycle + forecast_hour` 后，只剩 `178` 个唯一 `GFS source`，避免重复下载同一份背景。

2. **缓存式 fan-out**  
   先生成 `gfs_src_*.npz` 缓存，再将其展开成多个 `gfs_roi_*.npz`，对应多个 frame。

3. **断点续跑与无限重试**  
   考虑到 NOAA 历史归档存在 `DNS / timeout` 抖动，脚本设计为失败重连、跳过已完成项、不中断全流程。

4. **轻量字段下载**  
   当前只下载 `UGRD/VGRD` 两个核心风分量，先满足 OI 背景试验需求，不额外增加冗余字段。

截至本周撰写周报时，下载进度为：

- 已完成唯一源缓存：`20 / 178`
- 已完成最终 frame `npz`：`25 / 200`
- 当前仍在持续下载中

这部分工作虽然尚未结束，但已经完成了：

- 方法选型
- 官方数据源确认
- 历史下载脚本开发
- 去重缓存策略实现
- 断点续跑日志体系建立
- 批量下载实测联通

对后续 `S4-OI-DIAG` 至关重要。

---

## 三、本周优化点与优化方式

本周不仅完成了跑实验，更重要的是对项目执行方式本身做了优化。

## 3.1 运行层优化

- 将 `200` 帧 demo 改为 `metrics-only + 25 workers`，避免全量生成大规模 Stage4 `npz`，显著降低 I/O 与磁盘占用。
- 只为 `6` 个代表帧生成可视化和产品 `npz`，既保留调试依据，也控制了总体开销。

## 3.2 方法层优化

- 没有直接把 `CMA` 生硬并入官方重构，而是先把它限定在 `M1 display-only` 安全分支。
- 明确把 `CMA` 和 `official recon` 隔离，避免出现指标改善但科学口径不成立的问题。

## 3.3 风险控制优化

- 新增 `P0-LEAK` 审计，先判断背景能否独立，再决定是否允许进入 `OI`。
- 新增 `P0-FLOOR` 地板估计，先算“还剩多少可提升空间”，再决定是否值得投入大规模调参。

## 3.4 数据工程优化

- 新增 `verify_cma_grib.py`，将“数据可用性确认”从人工查验改为脚本化。
- 新增 `GFS` 去重下载链路，把 `200` 帧压缩成 `178` 个唯一源，提高整体效率。

---

## 四、本周关键名词解释

为了便于汇报，本周涉及的关键术语解释如下：

- `baseline`：当前系统尚未加入新优化前的标准对照结果，后续所有改动都需要与它比较。
- `holdout`：从观测中专门留出来、不参与训练/重构、只用于最终评估的一部分真值点。
- `strict_holdout_no_leakage`：保证评估点既不参与训练，也不通过别的路径被背景“偷看到”。
- `background`：用于提供大尺度先验信息的背景场，例如 `CMA` 或未来的 `GFS forecast`。
- `OI`（最优插值）：根据背景和观测的可信度，对两者进行加权融合的方法。
- `innovation`（创新量）：`观测 - 背景`，用来诊断背景误差。
- `display-only`：只用于图像展示，不进入官方评价的重构变量。
- `error floor`（误差地板）：在当前任务条件下理论上难以再显著降低的误差下限。
- `12km+`：高空样本层，当前是项目中最难、也是最值得优化的部分。

---

## 五、当前存在的问题与待解决事项

## 5.1 背景独立性仍未完全解决

虽然本周已明确 `CMA-RA` 是再分析产品，但仍缺乏其对 holdout aircraft wind 的独立性证明。因此：

- `S4-OI-DIAG` 暂不能用 `CMA` 直接立项为正式结论。
- 后续必须尽快完成 `GFS forecast` 背景替代方案验证。

## 5.2 `S4-CMA-M1` 还未完成 full-200 pairwise 封口

本周完成的是：

- `200` 帧 baseline 主跑
- `6` 个代表帧的 `M1 display-fill`

尚未完成的是：

- 对 `200` 帧全部做 `M1` 产品链路
- 对 full-200 候选结果与 baseline 做严格 pairwise 证明 `official == baseline`

因此，`S4-CMA-M1` 当前应定义为“机制已跑通、正式收口未完成”。

## 5.3 高空误差仍然是核心瓶颈

尽管产品层已补全，但官方误差主矛盾依然集中在 `12km+`。如果后续优化不能对高空稀疏区提供更合理的弱背景或局地分析增量，那么总体 RMSE 降幅不会很大。

## 5.4 外部 `GFS` 数据源网络稳定性一般

NOAA 历史源存在间歇性 `DNS/timeout` 抖动，本周已通过断点续跑和无限重试缓解，但整体下载时间仍偏长。后续若规模进一步扩大，可能需要考虑更稳定的镜像或分时段批量拉取。

---

## 六、下周安排（按优先级）

## 优先级 A：必须完成

1. 持续完成 `200` 帧 `GFS forecast` 历史背景下载，确保生成完整 `200 / 200` frame `npz`。
2. 基于 `GFS` 背景做 `P0-GFS` 校验，包括变量、层数、时次覆盖和 frame 对齐检查。
3. 启动 `S4-OI-DIAG` 的 report-only 版本，先做 `innovation = observation - background` 诊断，不直接改官方重构。

## 优先级 B：应当推进

1. 完成 `S4-CMA-M1` 的 full-200 pairwise 封口，严格证明 `display-only` 方案不改变官方指标。
2. 对 `12km+`、轻风、低计数、低时序置信度等 strata 做分层诊断，确认后续最值得投入的子问题。

## 优先级 C：视前两项结果决定

1. 若 `GFS` 背景表现稳定，则尝试 `S4-OI-1a/1b` 的局地 OI 近似实现。
2. 若 `GFS` 背景效果一般，则转入 `S4-B / S4-C / S4-vert / S4-E` 的局部失败分层补救路线。

---

## 七、本周产出清单

### 代码与脚本

- [verify_cma_grib.py](/data/LFT-W02_data/pengxu/stage/centralized_v1/core/verify_cma_grib.py)
- [centralized_stage4_error_floor_estimate.py](/data/LFT-W02_data/pengxu/stage/centralized_v1/core/centralized_stage4_error_floor_estimate.py)
- [download_stage5_gfs_aws_cached_batch.py](/data/LFT-W02_data/pengxu/stage/download_stage5_gfs_aws_cached_batch.py)
- [stage4_cma_m1_light_demo_20260625.sh](/data/LFT-W02_data/pengxu/workflow/plan/stage4_cma_m1_light_demo_20260625.sh)
- [stage4_gfs_historical_background_200_20260625.sh](/data/LFT-W02_data/pengxu/workflow/plan/stage4_gfs_historical_background_200_20260625.sh)

### 核心报告

- [stage4_cma_m1_light_demo_20260625_summary.md](/data/LFT-W02_data/pengxu/优化/stage4_cma_m1_light_demo_20260625/stage4_cma_m1_light_demo_20260625_summary.md)
- [cma_independence_report.md](/data/LFT-W02_data/pengxu/优化/stage4_cma_m1_light_demo_20260625/reports/cma_independence_report.md)
- [own_data_p0_leak_audit_20260625.md](/data/LFT-W02_data/pengxu/优化/stage4_cma_m1_light_demo_20260625/reports/own_data_p0_leak_audit_20260625.md)
- [cma_grib_verify_report.json](/data/LFT-W02_data/pengxu/优化/stage4_cma_m1_light_demo_20260625/reports/cma_grib_verify_report.json)
- [stage4_error_floor_estimate.md](/data/LFT-W02_data/pengxu/优化/stage4_cma_m1_light_demo_20260625/reports/stage4_error_floor_estimate.md)
- [demo_summary_20260625.json](/data/LFT-W02_data/pengxu/优化/stage4_cma_m1_light_demo_20260625/reports/demo_summary_20260625.json)
- [m1_promotion_checklist.json](/data/LFT-W02_data/pengxu/优化/stage4_cma_m1_light_demo_20260625/reports/m1_promotion_checklist.json)

### 可视化素材

- [20260131123000_centralized_stage4_slices.png](/data/LFT-W02_data/pengxu/优化/stage4_cma_m1_light_demo_20260625/representative_visuals/20260131123000_centralized_stage4_slices.png)
- [20260207001200_centralized_stage4_slices.png](/data/LFT-W02_data/pengxu/优化/stage4_cma_m1_light_demo_20260625/representative_visuals/20260207001200_centralized_stage4_slices.png)
- [20260211031200_centralized_stage4_diagnostics.png](/data/LFT-W02_data/pengxu/优化/stage4_cma_m1_light_demo_20260625/representative_visuals/20260211031200_centralized_stage4_diagnostics.png)
- [20260223133000_centralized_stage4_diagnostics.png](/data/LFT-W02_data/pengxu/优化/stage4_cma_m1_light_demo_20260625/representative_visuals/20260223133000_centralized_stage4_diagnostics.png)

---

## 八、周报总结

本周最大的价值，不是简单“又跑了一批实验”，而是把 Stage4 后续优化真正需要的前置条件梳理清楚了：

- 把 `CMA` 从“可疑背景”审成了“可用于 display-only、不可直接用于 OI”的明确口径。
- 把 `baseline` 和 `error floor` 都量化出来了，知道当前离理论可达水平还有多远。
- 把 `S4-CMA-M1` 产品链路跑通了，既补足了显示完整性，又没有破坏官方评估红线。
- 把下一步真正可行的独立背景路线切换到了 `GFS forecast`，并已经完成实质性数据下载和工程管线搭建。

从科研推进角度看，本周完成的是“把问题定义清楚、把工程链路打通、把错误方向排除掉”的关键性工作，为下周进入更严格的 `OI / innovation` 阶段奠定了基础。
