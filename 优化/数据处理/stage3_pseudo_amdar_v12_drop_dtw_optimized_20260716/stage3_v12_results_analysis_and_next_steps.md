# 大框架 Stage3 v12 结果分析与下一步建议

生成日期：2026-07-16

## 1. 阶段定义

本文的 **Stage3 v12** 是大框架 Stage3 的 pseudo-AMDAR 序列验证，不是 `amdar_stage2_to_6_optimization_plan_20260706.md` 内部“小阶段3（置信度优化）”。本轮目的仅是验证 Stage5 partial matching 是否可以安全显式丢弃离群 AMDAR 行；不把 AMDAR 变成 strict truth，也不在 locked-test 上调参。

## 2. 实现内容

- 新脚本：`/data/LFT-W02_data/pengxu/优化/数据处理/amdar_unified_stage3_v12_drop_dtw_20260716.py`。
- 使用 Drop-DTW 风格单调动态规划，显式比较“匹配当前行”和“以 validation 选择的 penalty 丢弃当前行”。
- emission 使用 Huber robust loss，联合水平距离与垂直差。
- 保存 raw sequence case bank 和 row-level ground truth，不再只保存 aggregate feature。
- 生成 clean、单点/连续块空间 outlier、10%-50% drop、reverse、local swap、random order、单点缺测、连续 gap、receiver time bias 等序列情形。
- hard negative 优先级为：同 tail/flight/date 错误 tracklet、同 tail/date 错航班、domain-matched wrong leg、全局 wrong leg。
- calibration 训练 posterior；validation 选择 drop penalty、minimum matched fraction、minimum contiguous fraction 和 posterior threshold；locked-test 只报告。

## 3. 正式运行口径

```bash
POLARS_MAX_THREADS=25 \
/data/LFT-W02_data/pengxu/.conda/envs/windy310/bin/python \
/data/LFT-W02_data/pengxu/优化/数据处理/amdar_unified_stage3_v12_drop_dtw_20260716.py \
  --out-dir /data/LFT-W02_data/pengxu/优化/数据处理/stage3_pseudo_amdar_v12_drop_dtw_optimized_20260716 \
  --slice-count 25 \
  --workers 25 \
  --cases-per-split 900
```

空间策略是一份共享 case bank 和压缩 parquet/json 输出，没有复制 25 份全量中间数据。整个 Stage3 v12 输出约 `12 MB`。

## 4. 数据规模与冻结策略

- base pseudo cases：`2,700`，calibration/validation/locked-test 各最多 `900`。
- sequence cases：`25,004`。
- row-level sequence truth：`163,461` 行。
- candidate evaluations：`150,024`。
- locked-test evaluation：`8,302`；最终 selected：`7,347`。
- validation 冻结策略：
  - row drop penalty：`3.0`；
  - minimum matched fraction：`0.50`；
  - minimum contiguous fraction：`0.40`；
  - association posterior：`>=0.90`；
  - leave-one-out path stability：Stage5 使用 `>=0.60`。

## 5. Locked-test 结果

- wrong-leg / hard-negative rate：`0.0136%`，要求 `<=1%`，通过。
- catastrophic rate：`0.0602%`，要求 `<3%`，通过。
- posterior ECE：`0.000361`，要求 `<=0.05`，通过。
- 最大单类 corruption false acceptance：`0.1686%`，要求 `<=2%`，通过。
- 最大单类 hard-negative false acceptance：`0.0423%`，要求 `<=2%`，通过。
- 同身份错误 tracklet：`2,366` 个 locked evaluations，误接纳 `1`，false acceptance `0.0423%`。
- 同 tail/date 错航班：`1,176` 个 locked evaluations，误接纳 `0`。
- domain-matched wrong leg：`4,760` 个 locked evaluations，误接纳 `0`。

全部 Stage3 v12 质量门通过。唯一 false acceptance 出现在 reverse corruption + same-identity wrong-tracklet 的交叉情形，但仍远低于冻结上限；不得据此继续降低 posterior 或 coverage 门。

## 6. Drop 识别解释

- point outlier 的 drop precision/recall：`1.0 / 1.0`。
- block outlier 的 drop precision/recall：`1.0 / 0.9992`。
- random order 和 reverse 的 drop precision 较低，是因为这两类没有“空间 outlier”真值，但单调模型会丢弃破坏顺序的行；因此这些 precision 不应解释为空间离群检测精度。
- 输出的 dropped rows 只作为 excluded diagnostic，不写入 Stage5 unique match 产品。

## 7. 真值与边界

- pseudo case 仅用于模型验证。
- real AMDAR `effective_strict_truth=true` 新增 `0` 行。
- real AMDAR `holdout_eligible=true` 新增 `0` 行。
- locked-test 未参与 policy 选择。

## 8. 下一步建议

Stage3 v12 已足以支持 Stage5 v7 对 partial mixture 的小集合审计。不要继续调 v12 阈值来扩大数量。若以后启用 stitched track，必须增加候选侧 track split/bridge corruption，并单独冻结 bridge probability；当前 v12 不能直接授权 5 个 physical stitched cases。

