# 大框架 Stage3 v13 Bridge Validation 结果分析与下一步建议

生成日期：2026-07-16

## 1. 阶段定义

本文的 Stage3 v13 是**大框架 Stage3** bridge-specific pseudo validation。它使用 ADS-B clean source tracklets 建立 calibration/validation/locked-test，验证 edge/path posterior；AMDAR 没有参与 pseudo truth。

Stage3 v12 只授权 Drop-DTW partial row exclusion，Stage3 v13 才授权经过本 policy 的 graph bridge/path。两者不能互相替代。

## 2. 正式 case bank

- selected base tracklets：`15,000`。
- selected state rows：`231,416`。
- case bank rows：`151,951`。
- calibration：`80,971`。
- validation：`28,381`。
- locked-test：`27,599`。
- split 使用 identity/date group hash；同一 aircraft/date 不跨 split。

Case bank 包含 reachable short/medium/long bridge、missing middle、position spike、timestamp bias、altitude spike、heading discontinuity、physically unreachable、same-identity wrong-tracklet、competing fork 和 wrong-flight same-tail/date。

`clean_no_bridge` 只用于 retention 审计，不进入 edge acceptance 分类；这是为了正确区分“保留原 tracklet”和“接受新 bridge”。

## 3. 冻结 policy

- posterior threshold：`0.0005426103460326424`。
- maximum formal gap：`1800s`。
- unique path margin 建议初值：`0.15`。
- validation positive recall：`1.0`。
- locked-test 未参与阈值选择。

阈值数值较小是 logistic + Platt 输出尺度的结果，不能脱离对应 model JSON 单独解释或手工替换。正式实现必须同时读取 weights、mean/scale、Platt 参数和 physical safety gates。

## 4. Locked-test 结果

| 指标 | 正式结果 | 硬门 | 结论 |
|---|---:|---:|---|
| cases | 27,599 | - | - |
| positives / negatives | 12,088 / 15,511 | - | - |
| positive recall | 100% | 报告项 | 通过 |
| wrong-tracklet/path rate | `0.0827%` | `<=1%` | 通过 |
| catastrophic bridge rate | `0.0645%` | `<3%` | 通过 |
| edge ECE | `0.000321` | `<=0.05` | 通过 |
| path ECE | `0.000321` | `<=0.05` | 通过 |
| max corruption false acceptance | `0.8621%` | `<=2%` | 通过 |
| same-identity wrong-tracklet | `0.8621%` | `<=1%` | 通过 |
| unreachable bridge | `0%` | `<=0.5%` | 通过 |
| clean no-bridge retention | `100%` | 不明显退化 | 通过 |
| truth/holdout violations | `0` | `0` | 通过 |

Stage3 v13 hard quality gate：**全部通过**。

## 5. 迭代修正记录

1. 初始 smoke 把 no-bridge retention 混入 edge acceptance，语义错误；已拆分。
2. 初始 pseudo gap 只增加时间、不推进右端状态，制造了假不可达 positive；已改为从左端状态物理传播生成 reachable pseudo bridge。
3. 首轮正式 locked-test 的 same-identity wrong-tracklet 为 `2/113 = 1.77%`；审计发现一个 false accept gap `2869s`，超过方案规定的 maximum formal gap。加入通用 `gap <=1800s` gate 后重跑，不使用 locked label 调阈值。
4. identity normalization 修正后重新生成 Stage2 和 Stage3，最终 same-identity wrong-tracklet 为 `1/116 = 0.8621%`。

## 6. 正确解释

- “全部质量门通过”只表示 Stage3 bridge policy 在当前 pseudo/hard-negative locked-test 上安全。
- 它不意味着所有 Stage2 physical edges 都可成为 Stage5 unique。
- Stage5 仍必须同时满足 exact identity、Stage3 v13 posterior/path margin、covariance emission、Stage3 v12 partial gate、batch-end upper bound 和 frozen prior regression。
- graph mixture 不能计 unique；interpolated gap state 不能当 observed truth。

## 7. 下一步

1. 新建大框架 Stage5 v8 graph matcher，读取 Stage2 graph products 和 Stage3 v13 frozen model。
2. 先做小集合：历史 5 stitched、graph recoverable rejects、同身份 hard negatives、prior 229 regression。
3. 输出 unique、graph mixture、rejected 三层；`combined_v8 = frozen_v7 + safe incremental`。
4. 只有 safety gate 全过且满足 `safe unique +3`、`mixture +20 with Stage6 benefit` 或显著 candidate coverage 改善之一，才形成正式 Stage5 v8 merge。

