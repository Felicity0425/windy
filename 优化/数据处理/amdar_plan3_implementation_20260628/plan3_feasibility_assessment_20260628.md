# plan3 可行性评估、实现结果与修正版执行口径

## 1. 任务范围与本报告目的

本报告用于对 [`plan3.md`](/data/LFT-W02_data/pengxu/优化/数据处理/plan3.md) 做一次完整的工程可行性评估，并把本轮已经完成的代码修改、数据验证、运行结果和后续执行口径收拢到一个统一文档中。

本轮工作的目标不是只回答“`plan3` 对不对”，而是把下面四件事同时做清楚：

1. 原始 AMDAR 数据是否真的存在大规模“同一航班、同一时间戳、但空间上分散成很多点”的现象。
2. 这种现象应如何解释，是否与数据提供方的回复一致。
3. `plan3` 中哪些部分可以直接执行，哪些部分必须收敛或修正后才能执行。
4. 当前代码和数据主链应如何修改，既保证 Stage1 语义更保守、更正确，又不破坏现有 Stage2 / Stage4 官方评估连续性。

本报告对应的实现目录为：

- [`amdar_plan3_implementation_20260628`](/data/LFT-W02_data/pengxu/优化/数据处理/amdar_plan3_implementation_20260628)

## 2. 最终结论

### 2.1 关于原始 AMDAR 数据本身

`plan3.md` 的核心判断是对的：

- 原始 AMDAR 的 `时间（北京时）` 不能再按“每条记录的真实逐点观测时间”理解。
- 原始 workbook 中确实存在大量“同一航班、同一时间戳、但空间分散成很多点”的记录，而且这不是少量脏数据，而是主体现象。
- 数据提供方关于“飞机在不同飞行阶段累计采样，批量下发，表中时间对应批次下发/接收时间”的说明，与原始数据统计是相互一致的。

### 2.2 关于 `plan3` 的总体方向

`plan3` 的总体方法方向也是对的：

- 必须把 AMDAR 原始时间改按“批次结束时间”语义解释；
- 必须把逐点观测时间重建与生产主链解耦；
- 必须把 ADS-B / location 时间重建放在独立研究分支推进；
- 必须允许低质量候选被拒绝，而不是为了覆盖率强制匹配。

### 2.3 关于 `plan3` 不能直接原样推进的地方

`plan3` 不能原样直接执行，主要有三点原因：

1. 不能立刻把当前官方 `wind_reconstruction_role` 主链整体切到“所有 AMDAR 全部 support-only”。
2. 批次边界不能只用 `flight_number + time`，还要保留原始连续块。
3. ADS-B 匹配不能继续按“同一 `flight_id + time_utc` 组”做弱身份匹配，至少要优先使用 `机尾号 + 航班号`，并加单侧时间上界和拒绝机制。

### 2.4 当前推荐的工程口径

当前应采用“修正版 `plan3`”而不是原文直推：

- 生产主链：
  - 保留当前 `wind_reconstruction_role` 以维持 Stage2 / Stage4 官方 strict holdout 评估连续性；
  - 但新增更保守的时间语义字段，把所有 AMDAR 统一标记为 `strict_time_truth=false`、`time_is_point_observation=false`；
  - 同时导出独立 conservative 产物，供后续迁移和研究使用。
- 研究分支：
  - 按 `机尾号 + 航班号` 优先构建 ADS-B 候选航段；
  - 使用单侧批次结束时间上界；
  - 使用整批单调匹配；
  - 输出歧义、拒绝原因和质量等级；
  - 在通过 pseudo-AMDAR 闭环验证前，不直接回写 Stage1 默认 `time_utc`，也不直接升格为 strict truth。

## 3. 数据背景与业务解释

### 3.1 原始 AMDAR 结构

原始文件：

- [`20260224/amdar.xlsx`](/data/LFT-W02_data/pengxu/20260224/amdar.xlsx)

原始表头中没有逐点真实观测时间，只包含：

- `机尾号`
- `航班号`
- `时间（北京时）`
- `飞行阶段`
- `纬度`
- `经度`
- `高度`
- `静温`
- `风向`
- `风速`

这意味着：

- Excel 汇总表本身不包含逐点秒级观测时间；
- 无法直接从原始表中恢复每个空间点各自的真实观测时刻；
- `时间（北京时）` 更合理的解释是一个批次标签，而不是严格逐点真值时间。

### 3.2 数据提供方回复的含义

数据提供方回复确认：

- 飞机在不同飞行阶段会累计采集一批数据；
- 原始逐点真实时间没有提供到这份表里；
- 这些点会成批下发；
- 表中的时间更接近该批数据的下发/接收时间；
- 飞机在爬升、巡航、下降阶段的累计和下发周期是动态变化的。

这与当前数据形态是吻合的：

- 同一 `航班号 + 时间（北京时）` 下会出现多个空间分散点；
- 同组点在原始行序上几乎总是连续排列；
- 同组点更像一段轨迹剖面，而不是“同一时刻多个地点同时观测”。

## 4. 原始 AMDAR 直接统计结果

### 4.1 是否存在大量“同航班同时间多点分散”

结论：**存在，而且是主体现象。**

基于原始 `amdar.xlsx` 的直接统计：

- 总行数：`431,008`
- 按 `航班号 + 时间（北京时）` 分组后的总组数：`56,365`
- 重复组数：`49,750`
- 落在重复组中的总行数：`424,393`
- 重复行占比：`98.4652%`
- 重复组占比：`88.2640%`
- 重复组大小中位数 / P90 / P99：`6 / 17 / 49`
- 最大同时间组大小：`50`

这说明绝大多数 AMDAR 记录都不属于“单时间单点”的简单结构，而属于“同时间多点批次结构”。

### 4.2 空间分散程度

重复组水平跨度：

- 中位数：`137.10 km`
- P90：`355.40 km`
- P99：`666.95 km`

重复组垂直跨度：

- 中位数：`530.35 m`
- P90：`2980.94 m`
- P99：`5227.32 m`

这已经足以否定“这些点只是同一局地点在同一时刻的细小抖动”这种解释。大量批次对应的是长距离沿航迹推进的多点段。

### 4.3 典型现象

最大组大小为 `50`，而且高频出现。当前目录中的分析结果还显示：

- `group_size_50_count = 392`
- 这些 `50` 点批次全部出现在 `ASC` 阶段

这非常像一个结构化的上升段批量剖面，而不是随机重复脏数据。

## 5. 为什么 `plan3` 不能原样直接推进

### 5.1 当前官方评估链依赖 `wind_reconstruction_role`

现有 Stage2 / Stage4 官方 strict holdout 评估，消费的是：

- `wind_reconstruction_role == strict_truth_candidate`

而不是仅仅依赖：

- `strict_time_truth`

因此，如果立刻把所有 AMDAR 在主链上都改成 `support_only_not_strict_truth`，当前官方评估链会被切断，现有 Stage4 指标将失去可比性。

这不是理论问题，而是当前代码结构决定的现实约束。

### 5.2 批次边界不能只看 `flight + time`

基于新 Stage1 输出反查可见：

- `56,365` 个同时间组里，有 `155` 个被切成多个原始连续块；
- 占全部同时间组 `0.275%`；
- 占重复同时间组 `0.312%`。

这个比例不大，但足以说明：

- “同航班同时间组 = 单一批次”并不恒成立；
- 有少量组实际上是多个原始连续块；
- 如果不保留原始连续块边界，会把少量本不应该合并的批次误并成一个 batch。

所以 `plan3` 里“批次边界不能只用 flight + time”这一点必须执行。

### 5.3 ADS-B 重建不能为了覆盖率牺牲可信度

旧原型的问题不是“不能匹配”，而是“虽然能匹配出很多，但几何质量不够强”。

因此新口径必须接受：

- 覆盖率下降；
- 拒绝率上升；
- 但保留下来的匹配更可解释。

这也是为什么重建研究分支需要：

- 机尾号优先；
- 航班号优先；
- 单侧时间上界；
- 候选歧义惩罚；
- 允许拒绝。

## 6. 本次代码实现与具体修改

### 6.1 Stage1 主链修改

修改文件：

- [`stage/stage1_prepare.py`](/data/LFT-W02_data/pengxu/stage/stage1_prepare.py:1)

已完成修改：

1. AMDAR 批次 ID 现在按原始连续块生成，而不是简单把同 `flight_id + time_utc` 整组并成一个批次。
2. 新增字段：
   - `amdar_batch_id`
   - `amdar_observation_order`
   - `raw_row_number`
   - `time_quality`
   - `usage_role`
3. 所有 AMDAR 统一拥有更保守的时间语义：
   - `strict_time_truth=false`
   - `time_is_point_observation=false`
4. 但当前官方 `wind_reconstruction_role` 兼容逻辑被保留：
   - 重复同时间组仍是 `support_only_not_strict_truth`
   - 单点同时间组仍维持 `strict_truth_candidate`

这样做的好处是：

- 保证主链不被批次时间误解释污染；
- 不破坏现有 Stage2 / Stage4 官方评估；
- 为后续迁移预留完整的保守字段和独立导出。

### 6.2 ADS-B 重建研究分支修改

修改文件：

- [`stage/reconstruct_amdar_time_from_adsb.py`](/data/LFT-W02_data/pengxu/stage/reconstruct_amdar_time_from_adsb.py:1)

已完成修改：

1. 使用 `机尾号 + 航班号` 优先构建候选航段。
2. 引入单侧批次结束时间上界，而不再使用宽松的对称时间窗。
3. 匹配单位改为“批次对航段”，不再按逐点贪心最近邻。
4. 输出：
   - 身份匹配模式
   - 第二候选代价
   - 歧义比
   - 拒绝原因
5. 移除了 AMDAR 风向与 ADS-B 航向差的错误比较。

当前这条分支的定位仍然是：

- 研究分支
- reconstruction smoke
- 不直接回写 Stage1 默认时间字段

### 6.3 分析与验证脚本

新增或修正：

- [`stage/analyze_raw_amdar_contiguous_blocks.py`](/data/LFT-W02_data/pengxu/stage/analyze_raw_amdar_contiguous_blocks.py:1)
- [`stage/analyze_amdar_batch_sequence.py`](/data/LFT-W02_data/pengxu/stage/analyze_amdar_batch_sequence.py:1)
- [`stage/check_stage1_stage2_alignment.py`](/data/LFT-W02_data/pengxu/stage/check_stage1_stage2_alignment.py:1)

其中：

- `analyze_raw_amdar_contiguous_blocks.py` 用于直接在原始 workbook 上检查“同时间组是否包含多个连续块”；
- `analyze_amdar_batch_sequence.py` 用于诊断批次内高度趋势和路径连续性；
- `check_stage1_stage2_alignment.py` 现在支持 `--stage1-dir`，可以直接验证新输出目录。

## 7. 本次重跑与验证结果

### 7.1 运行方式

本轮所有核心重跑和验证均按你要求使用 `25` 路并行口径执行。

新输出目录：

- [`stage1_output_plan3_v1`](/data/LFT-W02_data/pengxu/优化/数据处理/amdar_plan3_implementation_20260628/stage1_output_plan3_v1)

### 7.2 新 Stage1 输出结果

核心结果：

- `clean_wind_rows = 431,189`
- `clean_loc_rows = 19,162,638`
- `wind_reconstruction_role_counts`：
  - `support_only_not_strict_truth = 424,393`
  - `strict_truth_candidate = 6,796`
- `wind_usage_role_counts`：
  - `support_only_not_strict_truth = 431,008` for AMDAR
  - `strict_truth_candidate = 181` for TURB
- `wind_strict_time_truth_counts`：
  - `false = 431,008`
  - `true = 181`

这里有一个非常关键的解释：

- `wind_reconstruction_role` 仍保留官方兼容口径；
- `usage_role` 和 `strict_time_truth` 则已经切换到了更保守的时间语义；
- 这就是当前推荐的“双字段、双口径、双产物”过渡方案。

新增独立产物：

- [`amdar_stage1_conservative.parquet`](/data/LFT-W02_data/pengxu/优化/数据处理/amdar_plan3_implementation_20260628/stage1_output_plan3_v1/amdar_stage1_conservative.parquet)
- [`amdar_batch_statistics.parquet`](/data/LFT-W02_data/pengxu/优化/数据处理/amdar_plan3_implementation_20260628/stage1_output_plan3_v1/amdar_batch_statistics.parquet)

### 7.3 Stage1 / Stage2 对齐结果

对新目录运行对齐检查的结果为：

- `ok = true`
- `radar_frames_usable = 7395 / 7396`
- `in_range_ratio = 1.0`
- `unique_voxels = 816,392`

这说明：

- 新 Stage1 输出不会破坏当前 Stage2 入口；
- 时间窗重合仍然正常；
- location 的时空映射与体素范围保持一致；
- 主链数据组织仍然稳定。

### 7.4 批次序列诊断结果

批次序列诊断 summary 已完成，文件为：

- [`amdar_sequence_diagnostics_summary.json`](/data/LFT-W02_data/pengxu/优化/数据处理/amdar_plan3_implementation_20260628/amdar_sequence_diagnostics_summary.json)

关键结果：

- `batch_count = 56,521`
- `group_size_50_count = 392`
- `group_size_50_phase_counts`：
  - `ASC = 392`
- `phase_altitude_increase_ratio_mean`：
  - `ASC = 0.6535`
  - `DES = 0.1011`
  - `LVR = 0.2391`
- `phase_altitude_decrease_ratio_mean`：
  - `ASC = 0.0771`
  - `DES = 0.5932`
  - `LVR = 0.3310`
- `phase_path_efficiency_mean`：
  - `ASC = 0.9171`
  - `DES = 0.9414`
  - `LVR = 0.8757`

这些结果说明：

- 批次内部原始行序具有较强的轨迹连续性；
- `ASC` 组总体表现为高度上升趋势；
- `DES` 组总体表现为高度下降趋势；
- 路径效率高，符合“沿航迹顺序排列”的批次特征。

这进一步支持了一个关键判断：

- 原始行序确实含有有价值的时序信息；
- 后续重建逐点时间时，原始顺序应作为硬约束之一。

### 7.5 ADS-B 重建 smoke test 结果

结果文件：

- [`amdar_adsb_reconstruction_summary.json`](/data/LFT-W02_data/pengxu/优化/数据处理/amdar_plan3_implementation_20260628/reconstruction_smoke_test/amdar_adsb_reconstruction_summary.json)

在更严格约束下，对 `5000` 行样本的结果为：

- `amdar_rows = 5000`
- `amdar_groups = 524`
- `matched_groups = 272`
- `rejected_groups = 167`
- `unmatched_groups = 85`
- `matched_rows = 1287`
- `matched_row_ratio = 0.2574`
- `match_horizontal_km_q50 = 18.66`
- `match_horizontal_km_q90 = 34.49`
- `match_vertical_m_q50 = 12.19`
- `match_vertical_m_q90 = 1106.42`

这个结果的正确解读不是“覆盖率不高，所以失败”，而是：

- 在加入 `机尾号/航班号优先`、`批次结束时间单侧上界`、`候选歧义拒绝` 后；
- 原型不再为了覆盖率强行配对；
- 现在保留下来的候选更可信、更接近可以进入后续闭环验证的研究分支口径。

因此，相比旧原型：

- 覆盖率下降是预期行为；
- 可解释性提升才是当前真正重要的改进。

## 8. 目录中已整理的产物

当前目录下已整理的核心内容包括：

- 主报告：
  - [`plan3_feasibility_assessment_20260628.md`](/data/LFT-W02_data/pengxu/优化/数据处理/amdar_plan3_implementation_20260628/plan3_feasibility_assessment_20260628.md)
- Stage1 新输出：
  - [`stage1_output_plan3_v1`](/data/LFT-W02_data/pengxu/优化/数据处理/amdar_plan3_implementation_20260628/stage1_output_plan3_v1)
- 批次序列诊断：
  - [`amdar_sequence_diagnostics.parquet`](/data/LFT-W02_data/pengxu/优化/数据处理/amdar_plan3_implementation_20260628/amdar_sequence_diagnostics.parquet)
  - [`amdar_sequence_diagnostics_summary.json`](/data/LFT-W02_data/pengxu/优化/数据处理/amdar_plan3_implementation_20260628/amdar_sequence_diagnostics_summary.json)
  - [`amdar_group_size_50_diagnostics.parquet`](/data/LFT-W02_data/pengxu/优化/数据处理/amdar_plan3_implementation_20260628/amdar_group_size_50_diagnostics.parquet)
- ADS-B 重建 smoke test：
  - [`reconstruction_smoke_test`](/data/LFT-W02_data/pengxu/优化/数据处理/amdar_plan3_implementation_20260628/reconstruction_smoke_test)

## 9. 当前推荐执行口径

### 9.1 生产主链

当前建议保持：

- `wind_reconstruction_role` 主链不变；
- 当前官方 Stage2 / Stage4 评估协议不直接重构；
- 继续使用当前 strict holdout 评估连续性。

### 9.2 AMDAR 时间语义

当前建议明确采用：

- 原始 AMDAR 时间：
  - 批次结束时间
  - 不是逐点真实观测时间
- 所有 AMDAR：
  - `strict_time_truth=false`
  - `time_is_point_observation=false`

### 9.3 研究分支

当前建议继续推进：

- 批次级顺序诊断
- ADS-B 航段构建
- pseudo-AMDAR 闭环验证
- 重建质量等级 A/B/C
- 独立消融验证

但在通过闭环验证前，不建议：

- 回写 Stage1 默认 `time_utc`
- 把重建结果升为 strict truth
- 直接让重建 AMDAR 进入官方精细风场评估主链

## 10. GitHub 整理与提交边界

本次实现目录里既包含代码和报告，也包含完整重跑产物。二者需要区分处理：

- 适合进入 GitHub 的内容：
  - 代码修改；
  - 主报告；
  - 轻量级 summary JSON；
  - 用于说明研究结论的必要小体量产物。
- 保留在本地实现目录、但不建议直接作为普通 Git 对象提交的大产物：
  - `stage1_output_plan3_v1/clean_loc.parquet`，约 `1.40 GB`；
  - `stage1_output_plan3_v1/clean_wind.parquet`，约 `24.02 MB`；
  - `stage1_output_plan3_v1/amdar_stage1_conservative.parquet`，约 `23.96 MB`；
  - 其他 parquet 诊断产物。

这样处理的原因不是这些产物不重要，而是：

- 它们已经在本地实现目录中完整保留；
- 它们可以通过当前脚本和报告中的口径重新生成；
- 如果把 `1GB+` 的中间产物直接作为普通 Git 对象推送，仓库维护成本会迅速失控；
- 当前最应该进入版本库的是“可复现逻辑 + 明确结论 + 轻量摘要”，而不是把所有重型中间文件都塞进主仓库历史。

因此，本次 GitHub 提交的目标应明确为：

- 把 AMDAR `plan3` 修正版所需的代码逻辑固化；
- 把关键分析结论和运行结果固化；
- 把可复现入口和摘要结果固化；
- 把重型本地产物继续保留在当前实现目录，供后续复查或二次导出使用。

## 11. 最终判断

`plan3.md` 不应原样直接执行，而应按本报告给出的“修正版”执行。

最核心的一句话是：

> AMDAR 原始时间应按批次结束时间解释；Stage1 主链应先把时间语义保守化、把批次边界修正正确、把评估兼容性保住；ADS-B 逐点时间重建继续作为研究分支推进，并以闭环验证而不是覆盖率作为准入标准。

如果只保留最关键的三条执行结论，就是：

1. 生产主链暂时保留当前 `wind_reconstruction_role`，不要直接切断 Stage4 官方评估链。
2. AMDAR 时间语义已经应当统一改按“批次结束时间”理解，相关保守字段与独立产物已经落地。
3. ADS-B 重建可以继续做，但当前仍是研究分支，不能直接作为 Stage1 默认逐点真值时间回并主链。
