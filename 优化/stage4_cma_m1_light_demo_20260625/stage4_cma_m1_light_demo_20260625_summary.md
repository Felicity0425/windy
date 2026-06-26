# stage4_cma_m1_light_demo_20260625 执行总结

生成时间：2026-06-25  
对应计划：`workflow/plan/plan_0625_executable.md`

---

## 1. 这次我实际做了什么

这次不是把 `plan_0625_executable.md` 全部做完，而是先按优先级完成了：

1. `P0-CMA`：补了 `verify_cma_grib.py`，核对本地 `CMA/CRA40` 数据是否可读、变量是否齐、时间覆盖是否够。
2. `P0-LEAK`：读了 CMA-RA 手册，并结合本地文件名与产品属性，写了 `cma_independence_report.md`。
3. `P0-FLOOR`：补了 `centralized_stage4_error_floor_estimate.py`，先做一个**务实版误差地板估计**。
4. `第1步 S4-CMA-M1`：做了一个**轻量 demo**。
   - 200 帧主跑：`metrics-only`，25 路并行，不生成全量每帧 Stage4 NPZ。
   - 代表帧产品跑：只挑了 6 帧做 `display-fill`、CMA 背景 NPZ、可视化。

这次**没有**继续做：

1. `S4-OI-DIAG`
2. `S4-OI-1a/1b/1c/1d`
3. `S4-B / S4-C / S4-vert / S4-E`
4. `Stage5`

原因很明确：

1. `P0-LEAK` 还没有被彻底证明安全，当前不适合进入 OI / innovation / Desroziers 口径。
2. 你这次明确要求 demo 轻量化，不要铺满大量 NPZ，所以我先把 `M1 product branch` 跑通，而不是直接做 full-200 的 official M1 全量写盘。

---

## 2. 本次最重要的结论

### 2.1 200 帧 baseline 主跑成功复现

我重跑的 200 帧 `tp26` 指标，和计划里的 baseline 对齐：

| 指标 | 本次结果 | plan_0625 基线 |
| --- | ---: | ---: |
| holdout points | 530 | 530 |
| vector RMSE | 14.7690356 | 14.769036 |
| vector MAE | 6.8544542 | 6.854454 |
| frame mean RMSE | 8.2243094 | 8.2243 |
| frame P95 RMSE | 27.9861110 | 27.986111 |
| frame P99 RMSE | 58.7837702 | 58.783770 |
| 12km+ RMSE | 19.9176978 | 19.917698 |
| light RMSE | 5.1958768 | 5.195877 |
| light MAE | 4.1852831 | 4.185283 |
| floor10 relative MAE | 0.2828041 | 0.282804 |

说明：

1. 这次 25 路并行主跑口径是对的。
2. 当前轻量化跑法没有把 baseline 跑歪。
3. 后续所有候选实验都可以以这个输出目录下的主跑结果继续比。

汇总文件：

- `reports/demo_summary_20260625.json`
- `tp26_metrics_only_200_25w/stage4_point_departures.csv`

### 2.2 S4-CMA-M1 的产品层逻辑已经跑通

我用 6 个代表帧做了 `display-only weak background fill`：

1. `--cma-fusion-mode off`
2. `--display-fill-mode low_conf_background`
3. `display_confidence_cap = 0.20`

结果：

1. 6 个代表帧都成功生成了 `display-fill` 结果。
2. 背景填充区 `display_conf` 最大值都被压在 `0.20`。
3. `display_source_code_2 = low_confidence_weak_background_display_only`，语义正确。
4. 代表帧里，背景填充区占整个 display active grid 的比例大约在 `97.72%` 到 `98.49%`，均值 `98.16%`。

这说明：

1. `M1` 的“完整产品图 + 低置信标注”这条线在工程上是能工作的。
2. 而且当前实现遵守了你的红线：**CMA 只进 display，不进 official recon**。

对应文件：

- `reports/m1_promotion_checklist.json`
- `representative_stage4_display_fill/`
- `representative_visuals/stage4_visual_summary.json`

### 2.3 目前还不能说“P0-LEAK 已完全解决”

我读了你给的 CMA 手册，并补查了官方产品页 `https://data.cma.cn/data/detail/dataCode/NAFP_CRA40_FTM_6HOR.html`，结合本地文件命名，当前可以得到这个更明确的结论：

1. 官方页面明确写的是 `中国第一代全球大气再分析产品（CMA-RA）-逐6小时产品`。
2. 官方页面明确写了 `同化方法为三维变分`。
3. 手册明确把 `CMA-RA` 定义成再分析产品家族，本质上依赖观测、模式和资料同化。
4. 手册文件名规则里，`0_0` 表示 `分析产品`；而本地 2026 文件名正是 `CRA40_* ... V1_0_0.grib2?...dataCode=NAFP_CRA40_FTM_6HOR...`。
5. 但**即便如此，仍没有证据**能证明这批 2026 `FTM` 数据与本项目 strict holdout aircraft wind 是独立的。

所以我现在的结论是：

1. `forecast / reanalysis` 这一半已经判清：它应按 `reanalysis / analysis product` 对待，不应按 `pure forecast background` 对待。
2. `M1 display-only`：可以安全继续，因为它不进 official RMSE。
3. `OI / innovation / Desroziers`：**暂时不能按“独立背景”来宣称成立**。

也就是说，`P0-LEAK` 这一步我做到了“形成审计结论”，但没有做到“彻底解锁 OI”。

对应文件：

- `reports/cma_independence_report.md`

### 2.4 误差地板已经有了一个可用的工程估计

我先做了一个 pragmatic floor，而不是正式 triple-collocation 论文级实现。

核心结果：

| 指标 | 数值 |
| --- | ---: |
| baseline vector RMSE | 14.7690 |
| baseline component RMSE | 10.4433 |
| EMADDC prior component sigma RMS | 2.7346 |
| observation-only vector lower bound | 3.8674 |
| local proxy vector floor | 11.1126 |
| baseline - proxy floor | 3.6564 |
| excess variance fraction vs EMADDC | 0.9314 |

高度分层里最关键的是：

1. `12km+` 的 proxy floor 已经到 `14.1689`
2. `12km+` 当前 baseline 是 `19.9177`

这说明：

1. 当前系统确实还有改进空间，但没有你想象中那么大。
2. 高空 `12km+` 仍然是最大主矛盾。
3. 后续 Stage4/5 的所有讨论，都应该带着“离地板只剩多少”的意识，不然很容易陷入无效调参。

对应文件：

- `reports/stage4_error_floor_estimate.md`
- `reports/stage4_error_floor_estimate.json`

---

## 3. 这次发现的问题

### 3.1 `P0-FRAME` 在当前代码里已经不是 blocker

原计划写的是 `FRAMES200/5614 txt→JSON` 必做。  
但我核对代码后发现：

1. `centralized_stage4_ground_recon.py` 现在已经支持 `JSON list` **或** `逐行 txt`
2. `centralized_cma_ra_virtual_radial_3dvar.py` 也支持这两种格式

所以这一步在当前代码里**不再是强制 blocker**。

结论：

1. 计划里的 `P0-FRAME` 需要更新口径。
2. 可以保留为“兼容性整理”，但不是这次 demo 的阻塞项。

### 3.2 `verify_cma_grib` 发现一个真实数据缺口

审计发现：

1. `WIU/WIV/TEM/RHU/VVP` 都是 129 个时次
2. `GPH` 只有 128 个时次
3. 缺的是 `2026022012`

影响：

1. 对 `M1 display-fill` 不致命，因为 wind 主变量还在。
2. 但对后续更严格的背景诊断、垂直解释、OI 推理，需要把这个缺口记录清楚。

### 3.3 当前 `M1` 还没有完成 full-200 的“official==baseline”正式 pairwise 封口

这点必须说清楚。

我本次做的是：

1. 200 帧 full baseline metrics-only
2. 6 个代表帧的 M1 display-fill

我**没有**做的是：

1. 对 200 帧全部跑一遍 `ground_recon.py + display-fill`
2. 然后把 full-200 的 M1 candidate 与 baseline 做严格 pairwise，证明“official metrics 完全一致”

原因：

1. 你要求 demo 轻量化
2. 我优先避免为 200 帧铺大量 Stage4 NPZ

所以当前状态是：

1. `M1` 的产品机制是通的
2. 代表帧行为是对的
3. 但 `Step 1` 在计划口径下只能算**部分完成，不是完全收口**

### 3.4 `tp26_metrics_only_200_25w/stage4_localization_sensitivity_aggregate.csv` 容易误读

这个文件不是“一条总 baseline”。

原因：

1. `diagnostic_adaptive_v3` 会在不同帧上选不同的自适应半径
2. aggregate CSV 会按 `adaptive_selected_radius_xy` 分组
3. 所以里面你会看到多行，不是一条总指标

如果你只想看本次 200 帧总结果，优先看：

1. `reports/demo_summary_20260625.json`
2. `tp26_metrics_only_200_25w/stage4_point_departures.csv`
3. `tp26_metrics_only_200_25w/stratified_eval/`

---

## 4. 对照 plan_0625_executable.md，我现在做到哪一步了

### 4.1 当前完成度总表

| 计划项 | 当前状态 | 说明 |
| --- | --- | --- |
| `P0-FRAME` | 部分完成 / 口径修正 | 没有单独生成 json，但核实当前代码已支持 txt 直接读，因此不再是 blocker |
| `P0-LEAK` | 部分完成 | 已形成 `cma_independence_report.md`，但没有拿到“独立背景已确认”的证据 |
| `P0-CMA` | 完成 | `verify_cma_grib.py` 已写并跑完 |
| `P0-FLOOR` | 完成（工程版） | 已有 floor estimate，但还不是 formal triple-collocation 版 |
| `S4-CMA-M1` | 部分完成 | 200帧 baseline 已跑；6个代表帧 M1 已跑；full-200 的 M1 pairwise 尚未做 |
| `S4-OI-DIAG` | 未开始 | 受 `P0-LEAK` 未完全解锁影响 |
| `S4-OI-1a/1b` | 未开始 | 同上 |
| `S4-OI-1c/1d` | 未开始 | 同上 |
| `S4-B / S4-C / S4-vert / S4-E` | 未开始 | 还没进入这一层 |
| `Stage5` | 未开始 | 这次没有推进 |

### 4.2 如果严格按计划定义，“当前停在哪”

严格说，我现在停在：

1. `P0-CMA` 已完成
2. `P0-FLOOR` 已完成
3. `P0-LEAK` 已做出审计结论，但还没解锁
4. `S4-CMA-M1` 已完成**轻量 demo 版**

更准确的一句话：

> 我已经把“前置审计 + 轻量 baseline + 代表帧 M1 product branch”跑通了，但还没有进入 `S4-OI-DIAG`，也还没有做 full-200 M1 official pairwise 封口。

---

## 5. 这个目录太多文件，怎么读

目录总大小大约如下：

| 子目录 | 大小 | 作用 |
| --- | ---: | --- |
| `logs/` | 32K | 每一步执行日志 |
| `reports/` | 48K | 你最该先看的报告汇总 |
| `representative_cma_proxy/` | 1.8G | 6 个代表帧的 CMA 背景 NPZ 与代理产物 |
| `representative_stage4_display_fill/` | 99M | 6 个代表帧的 Stage4 M1 输出 |
| `representative_visuals/` | 20M | 6 个代表帧的 PNG 图与切片统计 |
| `tp26_metrics_only_200_25w/` | 6.0M | 200 帧 baseline 的轻量指标结果 |

### 5.1 如果你只想看“最重要的 6 个文件”

按优先级看这几个：

1. `reports/demo_summary_20260625.json`
2. `reports/cma_independence_report.md`
3. `reports/cma_grib_verify_report.json`
4. `reports/stage4_error_floor_estimate.md`
5. `reports/m1_promotion_checklist.json`
6. `representative_visuals/stage4_visual_summary.json`

### 5.2 每个目录具体是什么

#### `reports/`

这是最重要的目录，属于“人读的总结层”。

- `demo_summary_20260625.json`
  这次 demo 的总指标与 M1 代表帧摘要。
- `cma_independence_report.md`
  解释为什么当前 `M1` 可以做，但 `OI` 还不能直接宣称独立背景成立。
- `cma_grib_verify_report.json`
  CMA 文件完整性、变量、层数、时间覆盖、抽样可读性审计。
- `stage4_error_floor_estimate.md/json`
  误差地板估计。
- `m1_promotion_checklist.json`
  代表帧 M1 的具体验收结果。

#### `tp26_metrics_only_200_25w/`

这是 200 帧 baseline 主跑结果，**没有每帧 full Stage4 NPZ**，所以比较轻。

重要文件：

- `stage4_point_departures.csv`
  最底层 holdout 点误差明细，最关键。
- `stage4_localization_sensitivity.csv`
  每帧 metrics row。
- `stage4_localization_sensitivity_aggregate.csv/md`
  分组后的 aggregate，不是单条总 summary。
- `stratified_eval/`
  分层评估结果。
- `tail_diagnostics/`
  尾部诊断。

#### `representative_cma_proxy/`

这是 6 个代表帧对应的 CMA 背景结果。

每帧会有：

1. `*.npz`：三维背景场
2. `*.json`：本帧摘要
3. `*.md`：本帧说明
4. `*_sample.csv`：稀疏采样导出

它大，是因为 3D 场本身就大。

#### `representative_stage4_display_fill/`

这是 6 个代表帧的 Stage4 `M1 display-fill` 输出。

每帧会有：

1. `frame_*_center_strict.npz`
2. `point_eval_*.csv/json/txt`
3. `stage4_method_*.md`

这层是把 `display_source/display_conf/display_u/v` 真正写出来的地方。

#### `representative_visuals/`

这是最适合直接看图的目录。

每帧 3 个核心文件：

1. `*_centralized_stage4_slices.png`
2. `*_centralized_stage4_diagnostics.png`
3. `*_centralized_stage4_slice_stats.csv`

再加一个总索引：

- `stage4_visual_summary.json`

#### `logs/`

这是命令执行日志。  
如果你只想排查某一步为什么跑错，直接看这里：

1. `03_tp26_metrics_only_200_25w.log`
2. `04_representative_cma_proxy.log`
3. `05_representative_stage4_m1.log`
4. `06_representative_visuals.log`

---

## 6. 我建议你现在怎么用这个目录

如果你现在只是想快速理解我做到了什么，建议按这个顺序看：

1. `stage4_cma_m1_light_demo_20260625_summary.md`（本文件）
2. `reports/demo_summary_20260625.json`
3. `reports/cma_independence_report.md`
4. `reports/stage4_error_floor_estimate.md`
5. `reports/m1_promotion_checklist.json`
6. `representative_visuals/` 里面的 PNG

如果你下一步要继续推进实验，建议顺序是：

1. 先决定要不要做 **full-200 的 M1 official pairwise 封口**
2. 然后解决 `P0-LEAK` 的 provider-level 独立性确认
3. 解锁后再进 `S4-OI-DIAG`

---

## 7. 下一步最务实建议

我建议你下一步不要立刻跳到 `S4-OI-1`，而是先做这两个动作：

1. 把 `S4-CMA-M1` 做一次 **full-200 official pairwise 封口**
   - 目的：把 `Step1` 从“轻量 demo 成功”升级成“正式完成”
   - 代价：会多产出一些 Stage4 文件，但逻辑风险低
2. 把 `P0-LEAK` 再向前推进一层
   - 最好拿到数据提供方或产品说明，确认 `2026 FTM` 到底是不是 independent forecast / extension
   - 不然 `S4-OI-DIAG` 很容易在方法学上站不住

如果你愿意，我下一步可以直接继续做：

1. `full-200 的 M1 pairwise 封口版`
2. 或者 `S4-OI-DIAG 的 report-only 实现骨架`
