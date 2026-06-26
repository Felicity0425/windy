# centralized_v1 下一步优化计划（执行智能体版 · 2026-06-25）

> 本文是 `plan_0625.md` 的**修订 + 可执行化**版本。
> 读者是"执行智能体"：你不需要重读全部历史文档，按本文的
> 【实验ID → 改什么/不许改什么 → 文件:行号 → 命令 → 验收门 → if/else 回退】执行即可。
>
> 修订依据（已逐份核对）：
> 1. `centralized_v1_ultimate_summary_20260612.md`（项目全貌、边界、失败清单）
> 2. `centralized_v1_stage45_literature_backed_optimization_plan_20260612.md`（文献门槛、failed 候选数据）
> 3. `centralized_v1_stage45_oi_cma_fusion_actionable_plan_20260614.md`（**最新权威可执行口径**，代码地图、CMA 融合、潜在问题清单）
> 4. `workflow/Reference/风场重构论文/` 下 21 篇文献。
>
> **冲突解决规则：日期更晚的文档优先。即 0614 > 0612 > ultimate_summary。**

---

## 0A. 截至 2026-06-26 的执行进展与交接摘要（新增，交接窗口先读）

### 0A.1 这几天实际做到了什么

这份文档原本是“执行智能体版计划”。截至 2026-06-26，下面这些内容已经不再是待办，而是**已完成或已形成明确结论**：

| 项 | 当前状态 | 核心交付物 |
| --- | --- | --- |
| `P0-CMA` | 已完成 | [verify_cma_grib.py](/data/LFT-W02_data/pengxu/stage/centralized_v1/core/verify_cma_grib.py), [cma_grib_verify_report.json](/data/LFT-W02_data/pengxu/优化/stage4_cma_m1_light_demo_20260625/reports/cma_grib_verify_report.json) |
| `P0-LEAK`(CMA) | 已完成审计，未放行 OI | [cma_independence_report.md](/data/LFT-W02_data/pengxu/优化/stage4_cma_m1_light_demo_20260625/reports/cma_independence_report.md) |
| `P0-LEAK`(自有数据) | 已完成审计 | [own_data_p0_leak_audit_20260625.md](/data/LFT-W02_data/pengxu/优化/stage4_cma_m1_light_demo_20260625/reports/own_data_p0_leak_audit_20260625.md) |
| `P0-FLOOR` | 已完成工程版 | [centralized_stage4_error_floor_estimate.py](/data/LFT-W02_data/pengxu/stage/centralized_v1/core/centralized_stage4_error_floor_estimate.py), [stage4_error_floor_estimate.md](/data/LFT-W02_data/pengxu/优化/stage4_cma_m1_light_demo_20260625/reports/stage4_error_floor_estimate.md) |
| `S4-CMA-M1` | 已完成轻量 demo | [stage4_cma_m1_light_demo_20260625.sh](/data/LFT-W02_data/pengxu/workflow/plan/stage4_cma_m1_light_demo_20260625.sh), [stage4_cma_m1_light_demo_20260625_summary.md](/data/LFT-W02_data/pengxu/优化/stage4_cma_m1_light_demo_20260625/stage4_cma_m1_light_demo_20260625_summary.md) |
| `P0-GFS`(新增) | 已完成 | [download_stage5_gfs_aws_cached_batch.py](/data/LFT-W02_data/pengxu/stage/download_stage5_gfs_aws_cached_batch.py), [stage4_gfs_historical_background_200_20260625.sh](/data/LFT-W02_data/pengxu/workflow/plan/stage4_gfs_historical_background_200_20260625.sh) |
| `P0-GFS / verify_gfs_background` | 已完成并重跑 21 层最终版 | [verify_gfs_background.py](/data/LFT-W02_data/pengxu/stage/centralized_v1/core/verify_gfs_background.py), [gfs_background_verify_report_200.md](/data/LFT-W02_data/pengxu/优化/stage4_gfs_oi_diag_20260626/reports/gfs_background_verify_report_200.md) |
| `S4-OI-DIAG`(GFS) | 已完成 report-only | [centralized_stage4_oi_diag_report.py](/data/LFT-W02_data/pengxu/stage/centralized_v1/core/centralized_stage4_oi_diag_report.py), [s4_oi_diag_gfs_200.md](/data/LFT-W02_data/pengxu/优化/stage4_gfs_oi_diag_20260626/reports/s4_oi_diag_gfs_200.md) |
| `P0-ALT12-CUT`(新增) | 已完成 | [centralized_stage4_altitude_cutoff_report.py](/data/LFT-W02_data/pengxu/stage/centralized_v1/core/centralized_stage4_altitude_cutoff_report.py), [stage4_altitude_cutoff_lt12km_baseline_200.md](/data/LFT-W02_data/pengxu/优化/stage4_altitude_cutoff_20260626/reports/stage4_altitude_cutoff_lt12km_baseline_200.md) |

### 0A.2 当前状态总表（交接时先看这张）

| 计划项 | 当前状态 | 说明 |
| --- | --- | --- |
| `P0-FRAME` | 已核实，口径修正 | 当前代码已支持 `txt` 逐行直读和 `json list`，不再是 blocker |
| `P0-LEAK`(CMA) | 部分完成 | 已确认 `CMA-RA/CRA40` 是 `reanalysis / analysis product`，因此不放行 OI 主背景 |
| `P0-CMA` | 完成 | `773` 文件、`129` 时次、抽样可读 `18/18`，唯一缺口是 `2026022012` 缺 `GPH` |
| `P0-FLOOR` | 完成（工程版） | baseline `14.7690`，proxy floor `11.1126`，剩余空间 `3.6564 m/s` |
| `S4-CMA-M1` | 部分完成 | `200` 帧 baseline 已复现；`6` 代表帧 display-only 产品已跑通；full-200 pairwise 封口未做 |
| `P0-GFS`(新增) | 完成并补齐高层 | `178/178` unique source，`200/200` frame，`failed_count=0`，当前 `21` 层、`1000..100 hPa`、顶层约 `15.80 km` |
| `P0-GFS / verify_gfs_background` | 完成 | `ready_for_s4_oi_diag=true`，`supports_12km_plus=true`，`all_frame_shapes=(21,81,45)` |
| `S4-OI-DIAG` | 已完成 report-only | `train innovation RMSE=39.34`，`holdout background RMSE=35.23`；`0-3km/3-6km` 条件可用，其余尤其 `12km+` 高风险 |
| `S4-OI-1a/1b/1c/1d` | 未开始 | 现在已经具备进入 constrained OI 小步实验的前提，但不应直接进 official blend |
| `P0-ALT12-CUT` | 完成 | `12km+` 占点数 `41.89%`，但占 SSE `76.18%`；若只看 `<12km`，baseline `RMSE 14.77 -> 9.46` |
| `Stage5` | 未开始 | 仍应等 Stage4 official branch 真正变化并过 gate 后再谈 |

### 0A.3 当前最重要的 4 个结论

```text
1. CMA-RA 已确认是再分析/分析产品，因此可以做 display-only 弱背景补全，但当前不能作为 OI 独立背景。
2. 200 帧 25 路并行 baseline 已稳定复现，说明这一轮实验口径没有跑歪。
3. S4-CMA-M1 已跑通“完整风场 + 低置信标注”的产品链路，但还没完成 full-200 pairwise 正式封口。
4. GFS forecast 历史背景不但已下载完成，而且已补齐到 100 hPa / 15.80 km、通过 verify，并完成了 report-only S4-OI-DIAG；结论是“可做 weak/diagnostic background，但不宜直接进 official OI”。
```

### 0A.4 为什么这轮执行顺序和原计划相比有调整

```text
1. 没有直接从 S4-OI-* 开始：
   因为 P0-LEAK 未澄清前，OI / innovation / Desroziers 的统计解释不成立。

2. 没有让 CMA 直接进 official OI 背景：
   因为 CMA-RA 是再分析，不是 pure forecast，且没有拿到对 holdout 的独立性证明。

3. 200 帧先做 metrics-only 主跑、只挑代表帧写盘：
   因为当前 demo 明确要求轻量化运行，不铺满大量 npz。

4. 新增 GFS 分支：
   因为如果后续要做 OI，最需要的是独立 forecast 背景，而不是 reanalysis 背景。
```

### 0A.5 交接时优先给对方的文件

1. [stage4_cma_m1_light_demo_20260625_summary.md](/data/LFT-W02_data/pengxu/优化/stage4_cma_m1_light_demo_20260625/stage4_cma_m1_light_demo_20260625_summary.md)
2. [demo_summary_20260625.json](/data/LFT-W02_data/pengxu/优化/stage4_cma_m1_light_demo_20260625/reports/demo_summary_20260625.json)
3. [cma_independence_report.md](/data/LFT-W02_data/pengxu/优化/stage4_cma_m1_light_demo_20260625/reports/cma_independence_report.md)
4. [stage4_error_floor_estimate.md](/data/LFT-W02_data/pengxu/优化/stage4_cma_m1_light_demo_20260625/reports/stage4_error_floor_estimate.md)
5. [m1_promotion_checklist.json](/data/LFT-W02_data/pengxu/优化/stage4_cma_m1_light_demo_20260625/reports/m1_promotion_checklist.json)
6. [weekly_report_20260625.md](/data/LFT-W02_data/pengxu/优化/stage4_cma_m1_light_demo_20260625/weekly_report_20260625.md)
7. [stage4_gfs_oi_diag_20260626_handover_summary.md](/data/LFT-W02_data/pengxu/优化/stage4_gfs_oi_diag_20260626/stage4_gfs_oi_diag_20260626_handover_summary.md)
8. [gfs_background_verify_report_200.md](/data/LFT-W02_data/pengxu/优化/stage4_gfs_oi_diag_20260626/reports/gfs_background_verify_report_200.md)
9. [s4_oi_diag_gfs_200.md](/data/LFT-W02_data/pengxu/优化/stage4_gfs_oi_diag_20260626/reports/s4_oi_diag_gfs_200.md)
10. [stage4_altitude_cutoff_lt12km_baseline_200.md](/data/LFT-W02_data/pengxu/优化/stage4_altitude_cutoff_20260626/reports/stage4_altitude_cutoff_lt12km_baseline_200.md)

### 0A.6 交接后建议的下一步顺序

```text
第1优先级:
  A. 在新窗口里先读完已经生成的 verify / oi_diag / altitude_cutoff 三份报告
     - 先确认新窗口是否要坚持“全高度 official 目标”还是转向 “<=12km 业务口径”

第2优先级:
  B. 补做 S4-CMA-M1 的 full-200 pairwise 封口
     - 目标是把“产品逻辑已跑通”补成“official == baseline 的正式证明”

第3优先级:
  C. 如果坚持全高度 official 目标：
     - 只做 constrained S4-OI-1a / 1b
     - 重点保护 light wind / 12km+ / count_0-1 / gap_ge30

第4优先级:
  D. 如果项目允许改成 <=12km 业务口径：
     - 用统一 cutoff 重写 baseline / gate / summary
     - 不要把 “<12km 指标” 与 “全高度 official 指标” 混写
```

### 0A.7 外部参考资料（交接时要明确标出）

1. CMA-RA 用户手册：`https://data.cma.cn/article/showPDFFile.html?file=/pic/static/doc/cra/%E4%B8%AD%E5%9B%BD%E6%B0%94%E8%B1%A1%E5%B1%80%E5%85%A8%E7%90%83%E5%A4%A7%E6%B0%94%EF%BC%8F%E9%99%86%E9%9D%A2%E5%86%8D%E5%88%86%E6%9E%90%E4%BA%A7%E5%93%81%EF%BC%88CMA-RA%EF%BC%89%E7%94%A8%E6%88%B7%E6%89%8B%E5%86%8C.pdf`
2. CMA 产品页：`https://data.cma.cn/data/detail/dataCode/NAFP_CRA40_FTM_6HOR.html`
3. NOAA GFS AWS 历史归档：`https://registry.opendata.aws/noaa-gfs-bdp-pds/`
4. NOAA NOMADS：`https://nomads.ncep.noaa.gov/`

---

## 0. 本文相对原 `plan_0625.md` 的关键修订（先读，避免按旧假设执行）

原 `plan_0625.md` 是"7 方向 + 数学推导 + 周/月估时"的路线图。文献和数学扎实，但有 7 处与项目最新口径冲突或风险误判，本文已修正：

| 编号 | 原 plan 的问题 | 证据 | 本文修正 |
| --- | --- | --- | --- |
| R-1 | 优化3 称"与 `tp26_rep_soft_weight_v1` 方向一致，可平滑延续" | 0614 P-REP-1 / 0612 §2.3：该候选 **full-5614 明确 FAIL**（weighted RMSE 14.520→15.303，12km+ 17.585→18.631，新增 9 个 tail failure） | representation error 不再走 soft-weight 延续；改为把 `σ_repr` 作为 **OI 的 R** 显式建模（见 `S4-A`/`S4-OI-*`） |
| R-2 | 优化1 Desroziers 把 `d_a^o`(O-A) 和 `d_b^o`(O-B) 都定义成"holdout 减重构场"，两量塌缩、诊断失效 | Desroziers (2005) 要求 `x_b`(背景) 与 `x_a`(分析) 是**两个不同的量** | Desroziers 改为：背景=CRA40/NWP，分析=重构；且**强依赖 P-LEAK-1**（背景独立性），不再是"极低风险立即启动" |
| R-3 | 优化4 各向异性扩散标"实施风险极低" | 项目里**所有**垂直干预都失败过（SRHA 14.77→20.15 FAIL；guarded_vertical_dynamic_v2 FAIL） | 降级为"中风险"，必须 report-only 先行 + 12km+ 默认关闭 + 两道门 |
| R-4 | 优化2 LETKF 按局地 SVD 有效维度"动态调半径"，属更自由的 localization | R-Gilpin(2025)：高维下**距离型最稳**；`point_regime_localization_v1` 已 **FAIL** | 改为"3 套受约束 kernel family"切换，禁止自由 point-wise catalog |
| R-5 | 全文是"方向 + 估时"，缺实验ID/命令/门槛/回退，智能体无法直接执行 | 0614 已建好执行骨架 | 全面重写为实验矩阵 + 命令模板 + if/else 决策线 |
| R-6 | 完全缺"CMA 弱背景融合 → 完整场 + 低置信标注"这个**你的核心新需求** | 0614 §4 反复强调这是你的原话需求 | 新增 `S4-CMA-M1`（零风险、第一个做） |
| R-7 | 缺"误差地板"认知，优化5/6 在 holdout RMSE 上天花板被高估 | excess variance fraction=0.93，大部分 RMSE 是不可约表示误差 | 新增前置 `P0-FLOOR`，所有改善相对地板报告 skill |

**优先级也变了**：原 plan 把 Desroziers + 各向异性扩散列为"阶段一立即启动"。本文把**零风险的 CMA 兜底填充（S4-CMA-M1）和误差地板估计**提到最前，把 Desroziers 后置到"背景管线就绪 + 独立性确认后"。

---

## 1. 不可违反的红线（每个实验都适用）

```text
1. 唯一正式真值 = 当前帧 aircraft wind_records 的 strict holdout
2. strict_holdout_no_leakage = True        (ground_recon.py:3266-3273 fail-fast 守卫不可删)
3. motion_used_as_wind = False             (u_motion/v_motion 是飞机地面运动, 不是风)
4. CMA/CRA40/GFS/ERA 永远只能是背景 x_b, 绝不进入 holdout 评估真值
5. radar PNG 是云/强度背景, 不是 Doppler 风
6. 背景填充格点永不进入官方 RMSE/MAE  (不改 _point_eval_rows 读 official recon)
7. 12km+ 是最大 tail (SSE 76%) 且 CRA40 顶层可能缺失 → 背景默认极低置信
8. 一次只跑一个实验 ID; 每个 ID 独立输出目录 + 独立 promotion_checklist.json
9. 任一 200-frame smoke 打穿硬门槛 → 立即停, 不进 full-5614
```

---

## 2. 正式基线数值（执行时以此为对照，不要重算口径）

### 2.1 200 帧 smoke 基线（第一道门，cheap screen）

```text
frames = 200, holdout points = 530, 默认方法 = tp26_thr11_preserve
```

| 指标 | baseline | smoke 过线 |
| --- | ---: | --- |
| weighted RMSE | 14.769036 | ≤ baseline |
| frame P95 RMSE | 27.986111 | ≤ baseline |
| frame P99 RMSE | 58.783770 | ≤ baseline |
| 12km+ vector RMSE | 19.917698 | ≤ baseline |
| light wind(5-15) RMSE | 5.195877 | ≤ baseline |
| light wind(5-15) MAE | 4.185283 | ≤ baseline |
| floor10 relative MAE | 0.282804 | ≤ baseline |
| new light/mod tail failure | 0 | 必须仍为 0 |

### 2.2 full-5614 正式 promotion 门（第二道门，决定能否升默认）

```text
frames = 5614, holdout_points = 15054
```

| 指标 | full-5614 baseline | formal 过线 |
| --- | ---: | --- |
| frame mean RMSE | 8.418875 | ≤ baseline |
| frame mean MAE | 7.408240 | ≤ baseline |
| weighted RMSE | 14.520015 | ≤ baseline |
| weighted MAE | 6.475666 | ≤ baseline |
| frame P95 RMSE | 31.783087 | ≤ baseline |
| frame P99 RMSE | 73.325466 | ≤ baseline |
| 12km+ vector RMSE | 17.585340 | ≤ baseline |
| light(5-15) RMSE | 5.510587 | ≤ baseline |
| light(5-15) MAE | 4.188920 | ≤ baseline |
| floor10 relative MAE | 0.255017 | ≤ baseline |

### 2.3 "值得升默认"工程门（formal 通过后还要满足其一）

```text
A. full-5614 weighted RMSE 改善 >= 0.05 m/s, 或
B. 目标问题层(12km+ / gap_ge30 / count_0-1 / timeconf_0.4-0.6)中
   >=2 层 RMSE 改善 >= 5% 且所有硬门槛全过
若只持平但产品完整性+置信度图成立 → 不升默认, 作为 "product-completeness/reliability branch" 保留并写论文
```

### 2.4 误差结构（决定先改什么）

```text
200 帧 530 点 tail: alt_12km_plus(222点)占SSE 76.2%; high_vector_error_ge30mps(21点)占81%; qc_review_flag(302点)占93.8%
误差来源优先级(已稳定): vertical_structure > representation_error > sparse_support > role_conflict > temporal_weighting > tail_qc > localization
观测误差锚点(只能当 R 下界, 不能从 RMSE 硬扣): EMADDC 0-3km 2.2 / 3-6km 2.5 / 6-15km 2.8 m/s
component RMSE 10.27, EMADDC sigma RMS 2.74, excess variance fraction 0.93 → 绝大部分误差是表示误差+重构误差
```

### 2.5 已明确失败、不得重复的方向

```text
support_role_height_aware (SRHA)        FAIL  高空 role conflict 灾难性放大 (14.77->20.15)
sparse_temporal_gated CMA/NWP           FAIL  救 tail 但污染 light wind / 3-6km
guarded_vertical_dynamic_v2             FAIL  仍轻微污染 12km+ / light / floor10
tp26_point_regime_localization_v1       FAIL  500m/6min 稀疏支撑下, 过细 point-wise localization 更差
tp26_rep_soft_weight_v1                 FAIL(full-5614)  200帧小幅PASS, 但5614明确恶化 → 不再延续此路线
Stage5 residual PINN field-v1/v2        非默认  只要 alt12_scale>0 就 FAIL
```

---

## 3. 关键代码地图（执行时直接定位，省去重新找）

### 3.1 Stage4 主链 `stage/centralized_v1/core/centralized_stage4_ground_recon.py`(4812 行)

| 功能 | 位置 | 说明 |
| --- | --- | --- |
| 观测权重基 obs_conf*time_conf | `:341-346 _active_base_weight` | 权重起点 |
| 观测构建+各置信因子相乘 | `:588-741 _build_wind_observations` | density/quality/speed_qc/local_consistency/obs_error/representation_soft 都在此乘入 |
| 核加权累加(**重构核心循环**) | `:1694-~2050 _accumulate_localized` | `acc_u += u*local_w; acc_w += local_w` |
| 核权重函数 | `:744-791 _localization_weights` | gaussian / gaspari_cohn |
| 自适应核选择 | `:1357-1387, 1474-1487` | diagnostic_adaptive_v3, 候选格 8:4,10:5 |
| 角色冲突处理 | `:1616-1691, 1957-2028` | current_priority_adaptive |
| **成场(除权)** | `:2625-2645 _make_reconstruction` | `recon_u=acc_u/acc_w`; recon_conf 按 90 分位归一(`:2632`) |
| 物理细化 | `:2693-2886 _pinn_diffusion_refine` | pydda_3dvar_proxy + 垂直保结构 |
| **可靠性/tail/no-claim 场** | `:2158-2242 _compute_reliability_fields` | 已有 reliability_confidence_3d / tail_risk_score_3d / no_claim_mask_3d |
| **展示填充层** | `:2905-3025 _make_display_filled_field` | 已有 display-only CMA 填充; 输出 display_u/v/conf/mask/source |
| holdout 切分 | `:312-338 _split_holdout` | 确定性 linspace 选点 |
| 泄漏守卫(**不可破**) | `:3266-3273 _leakage_report` | strict_holdout_no_leakage, fail-fast |
| 点评估 | `:3502-3627 _point_eval_rows / _metric_summary` | vector_error, rmse_vector |
| 方法 dispatch | `:4040-4078 process_frame` | 按 localization_policy / confidence_mode 分支 |
| argparse | `:4654-4719` | 所有 CLI 旋钮 |

### 3.2 CMA 弱背景骨架（已存在，是融合落点）

```text
ground_recon.py:
  :92        CMA_FUSION_MODES = {off, cma_proxy_background, cma_reanalysis_background, cma_pseudo_observation}
  :2385-2506 _load_cma_background            读 NPZ u/v/conf, 支持 qc_gating
  :2509-2598 _apply_cma_background_to_accumulator  当前是裸加法 acc_u+=cma_u*weight (要改成 OI 增量)
  :2905-3025 _make_display_filled_field      已能做 display-only low-conf fill, 不改 official 场
  已有 CLI: --cma-fusion-mode --cma-proxy-dir --cma-background-weight(-mode)
            --display-fill-mode low_conf_background --display-fill-cma-proxy-dir
            --display-fill-source --display-fill-confidence-cap --display-fill-qc-gating
  尚不存在(写到这些参数=需先实现): --recon-mode --cma-background-dir --cma-fill-* --oi-*

centralized_cma_ra_virtual_radial_3dvar.py (1212 行, CRA40 读取+伪径向3DVar):
  :217-299 GRIB2 读取(cfgrib 优先, eccodes 回退)
  :68-76   变量码 WIU->u_wind_mps, WIV->v_wind_mps
  :315-348 水平最近邻 + 气压->高度插值 44330*(1-(p/1013.25)^0.1903)
  :408-468 时间匹配 nearest/linear/linear_qc (temporal_conf=exp(-change_speed/24))
  :654-776 _three_dvar_proxy  已有 8 项软约束(smoothness/divergence/vertical_shear/background/stage4_prior/observation/radial/boundary)
  :968-990 np.savez_compressed 已输出 u_cma_3d/v_cma_3d/cma_temporal_conf_3d/u_proxy_3d/v_proxy_3d/coverage_conf_3d
  argparse 是 --cma-time-method {nearest,linear,linear_qc} (不是 --time-match-mode)
```

### 3.3 Stage5 残差 PINN

```text
centralized_stage5_residual_pinn_train.py:49-67 ResidualMLP  输入60+无泄漏特征, 输出(delta_u,delta_v,sigma_u,sigma_v)
                                                              delta=cap*tanh(...), sigma=0.25+softplus(...)
                                          :183-198 损失 = Huber + 高斯NLL + delta正则
centralized_stage5_residual_pinn_field_apply.py:721-758  锁定门 vertical_gap_ge20_not_light
centralized_stage5_residual_pinn_field_v2_replay.py:75-136 变体扫描 alt12_scale∈{1,0.5,0.25,0}; 结论: alt12_scale>0 即 FAIL
centralized_stage5_residual_pinn_dataset.py:37-61,122-137  按帧时间切 train/val/test(防泄漏), truth 列严格排除
```

### 3.4 固定资产路径

```text
PY=/data/LFT-W02_data/pengxu/.conda/envs/windy310/bin/python
STAGE2=centralized_v1_output/stage2_full_v2/stage2_multimodal_summary.json
STAGE3=centralized_v1_output/stage3_full_v2_25w_payload_only/stage3_center_summary.json
FRAMES200=centralized_v1_output/stage4_guardrail_display_fill_200_20260605_25w/tp26_thr11_preserve_metrics/stage4_validation_frame_times.txt
FRAMES200_JSON= 同上 .json (需先转换)
FRAMES5614=centralized_v1_output/stage4_full_tp26_thr11_preserve_25w_taildiag_20260602_173319/stage4_holdout_only_frame_times_5614.txt
FRAMES5614_JSON= 同上 .json (需先转换)
CMA_DIR=/data/LFT-W02_data/pengxu/cma   (CRA40 GRIB2, 6h一帧, ~34km, 覆盖 2026-01-23~02-24)
```

---

## 4. 前置任务（第 0 步，全部完成才能进阶段 A 之后）

这些是 0614 文档点明、原 plan_0625 完全缺失的"地基"。不做这些，后面的 OI / Desroziers / 文献方法全部失效或踩雷。

### P0-FRAME：frame-times 文本转 JSON list（已核实，当前不再是 blocker）

【执行更新】当前已核实：`ground_recon.py` 和 `centralized_cma_ra_virtual_radial_3dvar.py` 都支持 `JSON list` 与逐行 `txt` 双格式，因此 `txt→json` 不再是当前主线 blocker。保留这一步仅出于兼容性与整洁性考虑。

```bash
$PY - <<'PY'
import json
from pathlib import Path
pairs = [
  ("centralized_v1_output/stage4_guardrail_display_fill_200_20260605_25w/tp26_thr11_preserve_metrics/stage4_validation_frame_times.txt",
   "centralized_v1_output/stage4_guardrail_display_fill_200_20260605_25w/tp26_thr11_preserve_metrics/stage4_validation_frame_times.json"),
  ("centralized_v1_output/stage4_full_tp26_thr11_preserve_25w_taildiag_20260602_173319/stage4_holdout_only_frame_times_5614.txt",
   "centralized_v1_output/stage4_full_tp26_thr11_preserve_25w_taildiag_20260602_173319/stage4_holdout_only_frame_times_5614.json"),
]
for s,d in pairs:
    s,d = Path(s),Path(d)
    fr = [x.strip() for x in s.read_text(encoding="utf-8").splitlines() if x.strip()]
    d.write_text(json.dumps(fr, ensure_ascii=False, indent=2), encoding="utf-8")
    print(d, len(fr))
PY
```

验收：两个 .json 生成，长度分别 = 200 帧文件行数、5614 帧文件行数。

### P0-LEAK：CRA40 与 holdout AMDAR 独立性检查（最高优先，决定 Desroziers/OI 是否成立）

【执行更新】已完成两份审计报告：

- [cma_independence_report.md](/data/LFT-W02_data/pengxu/优化/stage4_cma_m1_light_demo_20260625/reports/cma_independence_report.md)
- [own_data_p0_leak_audit_20260625.md](/data/LFT-W02_data/pengxu/优化/stage4_cma_m1_light_demo_20260625/reports/own_data_p0_leak_audit_20260625.md)

当前结论已经明确：

```text
1. CMA-RA / CRA40 / NAFP_CRA40_FTM_6HOR = reanalysis / analysis product
2. 不按 pure forecast background 对待
3. 它可以安全用于 S4-CMA-M1 的 display-only 弱背景填充
4. 它当前不放行 OI / innovation / Desroziers 的“独立背景”口径
5. 所以后续 OI 主线已切到 GFS forecast
```

**风险**：CRA40 再分析通常同化全球飞机观测。若它同化了你 holdout 的同批 AMDAR，背景 `x_b` 就"偷看"了真值 → Desroziers 诊断、obs-minus-background 创新量、OI 误差统计**全部失效**。这是原 plan_0625 优化1 完全没考虑的致命点。

```text
任务:
1. 查清 CMA_DIR 这批 2026-01~02 数据是 reanalysis(同化了AMDAR) 还是 forecast(纯预报)
   - 看产品文档 / 文件元数据 / 询问数据提供方：https://data.cma.cn/article/showPDFFile.html?file=/pic/static/doc/cra/%E4%B8%AD%E5%9B%BD%E6%B0%94%E8%B1%A1%E5%B1%80%E5%85%A8%E7%90%83%E5%A4%A7%E6%B0%94%EF%BC%8F%E9%99%86%E9%9D%A2%E5%86%8D%E5%88%86%E6%9E%90%E4%BA%A7%E5%93%81%EF%BC%88CMA-RA%EF%BC%89%E7%94%A8%E6%88%B7%E6%89%8B%E5%86%8C.pdf，这个是数据应用手册，参考一下。
2. 决策:
   if forecast(未同化当前AMDAR):  背景与holdout独立, 安全, OI/Desroziers 可做
   elif 同化了本项目同源AMDAR:
       (a) 只把CRA40用作 M1 兜底填充(填充区不进holdout) → 仍安全, 可先上 M1
       (b) 若要做 OI 并报 obs-minus-bg 统计 → 必须换独立背景(如纯GFS预报场)
3. 在 leakage_report 新增字段 background_independent_of_holdout: bool, 论文显式声明
```

验收：产出一份 `cma_independence_report.md`，结论是 forecast/reanalysis 二选一 + 处置路径。

### P0-CMA：GRIB 可读性 + 时间覆盖校验

【执行更新】已完成脚本与报告：

- [verify_cma_grib.py](/data/LFT-W02_data/pengxu/stage/centralized_v1/core/verify_cma_grib.py)
- [cma_grib_verify_report.json](/data/LFT-W02_data/pengxu/优化/stage4_cma_m1_light_demo_20260625/reports/cma_grib_verify_report.json)

当前结论：

```text
file_count = 773
time_count = 129
time_range = 2026012300 ~ 2026022400
read_probe_success = 18 / 18
唯一已知缺口 = 2026022012 缺 GPH
200帧 / 5614帧 frame coverage 均可 bracket
```

```text
写 verify_cma_grib.py, 批量确认每个 CMA_DIR 文件:
1. 能被 cfgrib/eccodes 打开 (文件名带 ?AWSAccessKeyId 后缀不影响, 但要确认 .grib2 解析)
2. 含 WIU/WIV 变量, 层数与顶层气压达标 (顶层须覆盖到 ~120hPa 才有 12km+ 背景)
3. 时间覆盖与 5614 帧雷达时刻做交集统计, 报告多少帧无背景(需 fallback)
注意: 34km->500m 是大尺度弱先验, 明确只用于"弱背景", 不宣称中小尺度能力
```

验收：`cma_grib_verify_report.json`，含可读文件数、变量/层数检查、无背景帧数。

### P0-FLOOR：误差地板估计（决定优化5/6 的天花板，避免无意义内卷）

【执行更新】已完成脚本与报告：

- [centralized_stage4_error_floor_estimate.py](/data/LFT-W02_data/pengxu/stage/centralized_v1/core/centralized_stage4_error_floor_estimate.py)
- [stage4_error_floor_estimate.md](/data/LFT-W02_data/pengxu/优化/stage4_cma_m1_light_demo_20260625/reports/stage4_error_floor_estimate.md)

当前结论：

```text
baseline vector RMSE = 14.769036
local proxy vector floor = 11.112602
distance to floor = 3.656433
12km+ baseline = 19.917698
12km+ proxy floor = 14.168927
```

原 plan_0625 优化5/6 隐含假设"holdout RMSE 还能大幅降"。但 excess variance fraction=0.93 说明大部分 RMSE 是"点 vs 500m/6min 体素"的不可约表示误差。

```text
新建 centralized_stage4_error_floor_estimate.py:
- 用三重配置(triple collocation)/representativeness 估计 σ_repr 不可约部分
- 给出 "点 vs 500m/6min 体素" 的 RMSE 理论地板 (预计 5-8 m/s 量级)
- 之后所有 Stage4/5 改善都相对地板报告: skill = 1 - (RMSE-floor)/(baseline-floor)
文献支撑: de Haan(2016) triple collocation, KNMI quintuple collocation, EMADDC(2025)
对应文献PDF: "Estimates of Mode-S EHS aircraft-derived wind observation errors using triple collocation.pdf"
            "EMADDC aircraft weather observations and quality control...2025.pdf"
            "On the representation error in data assimilation.pdf"
```

验收：理论地板 RMSE 数值 + 当前 baseline 距地板的差距，作为后续所有改善的参照系。

### P0-GFS（新增）：独立 forecast 背景获取与缓存（已完成）

【为什么新增】原计划里已经隐含写明：如果 `CRA40` 不能证明对 holdout 独立，则 `OI` 主线必须切到更干净的 forecast 背景。实际执行后，这条分支已被落地成脚本与数据资产。

已新增：

- [download_stage5_gfs_aws_cached_batch.py](/data/LFT-W02_data/pengxu/stage/download_stage5_gfs_aws_cached_batch.py)
- [stage4_gfs_historical_background_200_20260625.sh](/data/LFT-W02_data/pengxu/workflow/plan/stage4_gfs_historical_background_200_20260625.sh)

结果（截至 2026-06-26，已完成）：

```text
unique GFS sources = 178 / 178
frame NPZ = 200 / 200
failed_count = 0
变量 = UGRD / VGRD
策略 = source-level 去重缓存 + frame fan-out + 断点续跑 + 无限重试
```

【本窗口最新补充】最初这批 `GFS` 只提取到 `200 hPa`，顶层约 `11.78 km`，因此旧版 verify 一度给出：

```text
supports_12km_plus = false
ready_for_s4_oi_diag = false
```

随后已补齐 `150 hPa / 100 hPa`，并在不重复下载已有层的前提下刷新全部 cache/frame NPZ。当前最终盘上状态已变为：

```text
levels_count = 21
pressure_hpa = 1000..100
alt_km_max ≈ 15.7995
supports_12km_plus = true
ready_for_s4_oi_diag = true
all_frame_shapes = (21, 81, 45)
```

相关脚本 / 报告：

- [verify_gfs_background.py](/data/LFT-W02_data/pengxu/stage/centralized_v1/core/verify_gfs_background.py)
- [gfs_background_verify_report_200.md](/data/LFT-W02_data/pengxu/优化/stage4_gfs_oi_diag_20260626/reports/gfs_background_verify_report_200.md)
- [gfs_background_verify_report_200.json](/data/LFT-W02_data/pengxu/优化/stage4_gfs_oi_diag_20260626/reports/gfs_background_verify_report_200.json)

输出目录：

- [raw_grib](/data/LFT-W02_data/pengxu/优化/stage4_cma_m1_light_demo_20260625/gfs_historical_aws_200/raw_grib)
- [cache_npz](/data/LFT-W02_data/pengxu/优化/stage4_cma_m1_light_demo_20260625/gfs_historical_aws_200/cache_npz)
- [npz](/data/LFT-W02_data/pengxu/优化/stage4_cma_m1_light_demo_20260625/gfs_historical_aws_200/npz)

#### `P0-GFS / verify_gfs_background` 通俗解释（交接/汇报可直接复用）

`P0-GFS` 现在要解决的，不是“数据有没有下载下来”，因为下载这一步已经做完了。  
它现在真正要回答的是：

```text
这批 GFS 背景，能不能放心地接到后面的 S4-OI-DIAG？
```

也就是要先做一轮“背景体检”。

##### 1. 为什么下载完还不够，还要 `verify_gfs_background`

因为“文件存在”不等于“背景可用”。  
后面的 `S4-OI-DIAG` 需要的是一个真正可对齐、可解释、可分层诊断的背景场，而不只是把一堆 `npz` 放在磁盘上。

所以 `verify_gfs_background` 的作用是确认：

```text
1. 变量是不是齐全
2. 层数是不是够
3. 高空是不是覆盖到 12km+
4. 200帧是不是都能正确映射到 GFS 背景
5. 有没有坏文件、缺文件、空文件、错时次文件
6. 背景的时间、空间、高度语义是否和 Stage4 能接起来
```

##### 2. 它和 `P0-CMA` 的区别是什么

`P0-CMA` 检查的是：

```text
CMA 这批再分析能不能读、变量全不全、时间覆盖够不够
```

`P0-GFS` 检查的是：

```text
GFS 这批 forecast 背景能不能成为 OI 的候选独立背景
```

两者看起来都在“验数据”，但科学角色不同：

```text
CMA 更偏 display-only / 参考背景
GFS 更偏 OI / innovation 背景
```

##### 3. `P0-GFS` 真正想确认什么

本质上是想确认下面这句话能不能成立：

```text
GFS 200帧背景在变量、层数、时次、高度和 frame 对齐上都没问题，
可以作为后续 S4-OI-DIAG 的背景输入。
```

如果这个结论不成立，后面的 `innovation` 统计就会很混乱。

##### 4. 它做完之后，你应该得到什么

做完 `verify_gfs_background` 后，你应该能够一眼回答这些问题：

```text
1. 200帧是不是 200/200 都有背景
2. 每帧的背景来自哪个 GFS cycle 和 forecast hour
3. 当前背景变量只有 UGRD/VGRD，是否足够支撑 S4-OI-DIAG
4. 背景层数和高度覆盖是否支持 12km+ 分层诊断
5. 有没有 frame 映射异常、时次异常或文件损坏
6. 后续是可以直接做 OI-DIAG，还是还需要补变量/补脚本
```

##### 5. 一句话概括 `P0-GFS`

```text
它不是“再下载一遍 GFS”，
而是“确认已经下载好的 GFS 能不能被正式接入 OI 诊断链路”。
```

#### `verify_gfs_background` 执行版（建议新增报告与检查项）

建议新增：

```text
脚本:    stage/centralized_v1/core/verify_gfs_background.py
报告:    优化/stage4_cma_m1_light_demo_20260625/reports/gfs_background_verify_report_200.json
摘要md:  优化/stage4_cma_m1_light_demo_20260625/reports/gfs_background_verify_report_200.md
```

##### 1. 需要检查的内容

```text
一、文件级检查
  1. cache_npz 数量是否 = 178
  2. frame npz 数量是否 = 200
  3. failed_frames.txt 是否为空
  4. 每个 npz 是否可读、是否非空、是否键完整

二、字段级检查
  1. 是否包含 u / v
  2. 是否包含 pressure_hpa / alt_km / lat / lon / time_str
  3. shape 是否一致
  4. 数值中是否存在大面积 NaN / inf

三、时次级检查
  1. 每个 frame_time 映射到哪个 cycle + forecast_hour
  2. 是否存在 frame 缺映射
  3. source_frame_times 写入是否正确

四、高度覆盖检查
  1. 顶层是否足以支撑 12km+ 分层
  2. pressure_hpa / alt_km 的单调性是否正确
  3. 最高层高度是否达到当前高空诊断所需范围

五、空间/区域检查
  1. ROI 经纬度范围是否和当前项目区域一致
  2. 水平网格分辨率是否稳定
  3. 是否存在异常裁剪
```

##### 2. 建议报告里至少输出这些字段

```text
frame_count
unique_source_count
failed_count
variables_present
levels_count
pressure_hpa_min / max
alt_km_min / max
lat_min / max
lon_min / max
nan_fraction_u / v
frame_coverage_ok_count
frame_coverage_fail_count
cycle_hour_mapping_preview
supports_12km_plus = true/false
ready_for_s4_oi_diag = true/false
```

##### 3. 建议的验收门

```text
硬门:
  1. frame npz = 200 / 200
  2. failed_count = 0
  3. 所有 frame npz 可读
  4. u / v / pressure_hpa / alt_km 字段齐全
  5. 高度覆盖支持 12km+ 分层诊断
  6. 没有明显异常 NaN / inf / shape mismatch

结论门:
  if ready_for_s4_oi_diag = true:
      直接进入 GFS 版 S4-OI-DIAG
  else:
      先修背景数据或补转换逻辑，再进入 S4-OI-DIAG
```

##### 4. 和后续 `S4-OI-DIAG` 的衔接关系

`P0-GFS` 做完后，后面的链路就会顺成这样：

```text
P0-GFS:
  证明 GFS 背景“可读、可对齐、可分层、可用于诊断”

S4-OI-DIAG:
  用这批背景去算 innovation / obs_influence

S4-OI-1a / 1b:
  只有当前面的诊断说明背景确实有信息量，才值得继续做 oi_diag_approx / local_oi
```

##### 5. 交接窗口里对 `P0-GFS` 的一句话说法

```text
GFS 已经从“200帧下载完成”推进到“21层 / 100hPa / verify通过 / ready_for_s4_oi_diag=true”，
因此后续新窗口不需要再补下载或补 verify，可以直接基于当前结果决定要不要做 constrained OI。
```

---

## 5. 阶段 A：零风险产品交付 + 诊断（先做，立刻有产出）

### 实验 `S4-CMA-M1`：CMA display-only 兜底填充 →"完整风场 + 低置信标注"

**这是你的核心新需求（稀疏数据要完整场 + 标注低置信），且对 official holdout 零风险，第一个做。**

【执行更新】这一分支已经跑通，但当前只完成了“轻量 demo 版”，还没有补 full-200 的 pairwise 正式封口。已产出：

- [stage4_cma_m1_light_demo_20260625_summary.md](/data/LFT-W02_data/pengxu/优化/stage4_cma_m1_light_demo_20260625/stage4_cma_m1_light_demo_20260625_summary.md)
- [demo_summary_20260625.json](/data/LFT-W02_data/pengxu/优化/stage4_cma_m1_light_demo_20260625/reports/demo_summary_20260625.json)
- [m1_promotion_checklist.json](/data/LFT-W02_data/pengxu/优化/stage4_cma_m1_light_demo_20260625/reports/m1_promotion_checklist.json)

已验证事实：

```text
1. 200帧 baseline metrics-only 已复现官方基线
2. 6个代表帧 display-only fill 已完成
3. 背景填充区 display_conf 上限 = 0.20
4. 代表帧背景填充比例约 97.72% ~ 98.49%，均值 98.16%
5. 当前未证明 full-200 official == baseline 的 pairwise 封口
```

```text
只改:   display-only 字段 (display_u/v/conf/mask/source)
不许改: official recon_u/v/conf/mask; _point_eval_rows; --cma-fusion-mode 保持 off
对应文献: DINCAE(填充场+逐像元误差图先例); 各向异性扩散等不涉及
```

命令（全部用现有 CLI，无需写新代码）：

```bash
# Step1: 生成每帧 CMA 背景 NPZ (复用现有脚本, 先用 200 帧)
$PY stage/centralized_v1/core/centralized_cma_ra_virtual_radial_3dvar.py \
  --cma-dir $CMA_DIR --stage2-summary $STAGE2 \
  --frame-times-file $FRAMES200_JSON \
  --cma-time-method linear_qc \
  --aircraft-anchor-mode stage4_train_wind \
  --stage4-holdout-fraction 0.125 --stage4-holdout-count 0 \
  --out-dir centralized_v1_output/stage4_cma_background_v1 --num-workers 12

# Step2: Stage4 display-only 兜底填充
$PY stage/centralized_v1/core/centralized_stage4_ground_recon.py \
  --stage2-summary $STAGE2 --stage3-summary $STAGE3 \
  --frame-times-file $FRAMES200_JSON \
  --cma-fusion-mode off \
  --display-fill-mode low_conf_background \
  --display-fill-cma-proxy-dir centralized_v1_output/stage4_cma_background_v1 \
  --display-fill-source cma_reanalysis \
  --display-fill-confidence-cap 0.20 \
  --display-fill-qc-gating strict_temporal \
  --out-dir centralized_v1_output/stage4_cma_m1_fill_200_20260625
```

验收门（产品门，非 RMSE 门）：

```text
硬约束(必须全过):
  1. 官方 holdout RMSE/MAE/P95/P99/12km+/light/floor10 与 baseline 完全一致
     (M1 不动 official recon, 必须严格 ==; 若有任何变化 = 有 bug, 误填了观测点)
  2. display_source_3d: official_mask 内 source=1, 背景填充区 source=2
  3. 背景填充区 display_conf <= 0.20, 与观测区 confidence 明显可分
产品价值:
  4. 全场覆盖率从重构覆盖率提升到 ~100% (CRA40 覆盖范围内)
if 官方指标 != baseline → 停, 排查误填 bug
if 通过 → 产品需求(完整场+低置信标注)已满足, 进 S4-OI-DIAG
```

### 实验 `S4-OI-DIAG`：背景创新量 / obs_influence report-only 诊断（不改 recon）

为后续 OI 提供"背景到底可不可靠"的证据。**依赖 P0-LEAK 通过。**

【执行更新】这里已经改为 `GFS forecast` 并跑完 report-only 版本。原因是：

```text
1. CMA 已被审计为 reanalysis / analysis product
2. CMA 可做 M1 display-only，但不宜承载 OI 独立背景角色
3. GFS 200帧背景已经补齐到 `100 hPa` 并通过 verify，具备进入 OI-DIAG 的现实条件
```

【本窗口最终结果】正式结果见：

- [s4_oi_diag_gfs_200.md](/data/LFT-W02_data/pengxu/优化/stage4_gfs_oi_diag_20260626/reports/s4_oi_diag_gfs_200.md)
- [s4_oi_diag_gfs_200.json](/data/LFT-W02_data/pengxu/优化/stage4_gfs_oi_diag_20260626/reports/s4_oi_diag_gfs_200.json)

核心数字：

```text
train innovation:
  inside_background_count = 154332
  vector RMSE = 39.3400
  vector MAE  = 33.8918

strict holdout background:
  inside_background_count = 530
  vector RMSE = 35.2337
  vector MAE  = 29.7866

conditionally usable strata:
  0-3km, 3-6km

high-risk strata:
  12km+, 6-9km, 9-12km,
  count_0, count_1, count_ge2,
  gap_10_30, gap_ge30, gap_lt10
```

因此这里现在的正确口径不是：

```text
GFS 已经准备好直接做 official OI
```

而是：

```text
GFS 已经准备好作为 diagnostic / weak background，
只值得进入 very constrained 的 S4-OI-1a / 1b 小步实验。
```

#### `S4-OI-DIAG` 通俗解释（交接/汇报可直接复用）

`S4-OI-DIAG` 可以理解成：**先不给系统“做手术”，先做一次完整体检。**

它现在的目的不是直接把 Stage4 指标变好，而是先回答 4 个更基础的问题：

```text
1. 背景和观测到底差多少？
2. 这个差值主要出现在什么高度层、什么支撑条件下？
3. 背景在 12km+ 和稀疏区，到底是在帮忙，还是在带偏？
4. OI 这条线值不值得继续投入开发？
```

##### 1. 它为什么要先做，而不是直接上 OI

因为如果不先诊断，直接把背景融合进重构，会有两个问题：

```text
1. 你不知道背景在哪些区域是可信的，哪些区域是有系统偏差的
2. 一旦指标变差，你无法判断是背景本身有问题，还是 OI 参数有问题
```

所以 `S4-OI-DIAG` 的角色是：**先建立对背景的认识，再决定要不要做正式 OI。**

##### 2. `innovation` 是什么意思

这里的核心量是：

```text
innovation = observation - background
```

也就是：

```text
观测值 - 背景值
```

它表示的是：**背景和真实观测之间到底差了多少。**

举例：

```text
若 GFS 认为某点风速是 20 m/s，而观测是 28 m/s，
则 innovation = +8 m/s
→ 说明背景在这里偏低，后面若做 OI，观测应把背景往上拉

若 GFS = 25 m/s，观测 = 24 m/s，
则 innovation = -1 m/s
→ 说明背景本来就比较接近观测，没必要做大改动
```

所以 `innovation` 不是为了简单看“背景准不准”，而是为了看：

```text
1. 背景误差主要集中在哪些层
2. 背景偏差有没有系统性
3. 哪些区域观测能真正提供增量信息
4. 哪些区域背景本身已经足够接近观测
```

##### 3. `obs_influence` 是什么意思

`obs_influence` 可以通俗理解为：

```text
这个格点最后有多大程度是“观测在说话”，而不是“背景在说话”
```

语义上：

```text
obs_influence 越接近 1:
  说明这里观测支撑强，后面如果做 OI，结果主要由观测决定

obs_influence 越接近 0:
  说明这里观测支撑弱，后面如果做 OI，结果会更多依赖背景
```

这个量非常重要，因为它能把“完整场”和“可信度”联系起来：

```text
有观测的地方 = 可以高置信
无观测或观测极弱的地方 = 即使有背景补全，也必须低置信标注
```

##### 4. 为什么重点看 `12km+` 和稀疏区

因为当前系统最难的部分恰恰不是低层观测密集区，而是：

```text
1. 12km+ 高空
2. count_0 / count_1 这类极低支撑区
3. dist_ge6km / gap_ge30 这类观测远离区
4. timeconf_0.4-0.6 这类时间连续性一般的区
```

这些地方的问题本质都是：

```text
观测对结果的约束不够强
```

所以这里才最需要背景提供“弱约束”。

##### 5. “弱约束”是什么意思

“弱约束”不是说背景直接替你给答案，而是说：

```text
在观测不足时，不让结果完全漂掉
```

也就是：

```text
有足够观测时，还是以观测为主
观测不足时，背景只提供一个大尺度、连续、物理上还说得过去的骨架
```

它的作用不是“强行改写观测”，而是：

```text
1. 防止无观测区发散
2. 防止高空结构完全断裂
3. 给稀疏区一个最低限度合理的场
```

##### 6. `S4-OI-DIAG` 的输入是什么

可以直接理解成三类输入：

```text
输入1：背景场
  当前推荐使用 GFS forecast 200帧背景，而不是 CMA

输入2：训练观测
  即 Stage4 中已经剔除了 strict holdout 后，剩下可用于重构的观测

输入3：分层标签
  包括 altitude band、support count、distance gap、time_conf 等
```

##### 7. `S4-OI-DIAG` 的输出是什么

建议它至少输出 4 类结果：

```text
输出1：innovation 总体统计
  如均值、MAE、RMSE、分位数

输出2：innovation 分层统计
  按 0-3km、3-6km、6-9km、9-12km、12km+
  按 count_0/count_1/dist_ge6/gap_ge30/timeconf_0.4-0.6 等 strata

输出3：obs_influence / background_used 诊断
  判断哪些区域主要是观测主导，哪些区域未来会更多依赖背景

输出4：结论性建议
  例如：
  - GFS 在 12km+ 是否值得继续做 OI
  - GFS 在 light wind 是否风险较大
  - 哪些 strata 可以继续做 local OI
  - 哪些 strata 应保持 M1 display-only，不建议进入 official branch
```

##### 8. `S4-OI-DIAG` 做完之后，你应该期待看到什么

它不会直接告诉你“指标已经提升了多少”，因为它本来就不改 `recon`。  
它真正会给你的是下面这种判断能力：

```text
1. 背景到底有没有信息量
2. 背景的信息量主要体现在什么层
3. 是不是只有高空/稀疏区值得做 OI
4. 低层和 light wind 是否要避免背景介入
5. OI 到底值不值得继续推进成正式分支
```

##### 9. 一句话概括 `S4-OI-DIAG`

```text
它不是“让结果立刻变好”的步骤，
而是“判断背景有没有资格进入下一步 OI”的步骤。
```

如果这个诊断结论是正面的，就继续做：

```text
S4-OI-1a / 1b / local_oi
```

如果结论是负面的，也不是白做，因为它至少会明确告诉你：

```text
1. 背景在哪些层不可用
2. OI 不值得继续投入
3. 项目应转回 M1 display-only 或其他 Stage4 分支
```

```text
只改:   新增诊断输出 (innovation, obs_influence, analysis_var bins)
不许改: recon_u/v
步骤:
  1. 读 CMA 背景 + train 观测(已剔 holdout)
  2. 计算 train innovation: d_ob = y - H x_b
  3. 按 height/support/timeconf 分层输出 innovation 分布 + obs_influence
判定:
  if innovation 分层显示背景在 light/12km+/timeconf 风险层不可靠:
      保持 M1, 不进入 OI official branch
  if 背景在某些层可靠(innovation 合理, 无系统偏差):
      记录"哪些层背景可用", 进阶段 B 的 constrained OI
```

验收：`s4_oi_diag_report.md`，含分层 innovation/obs_influence，结论"哪些层背景可信"。

【执行后补充判断】本次 GFS 版 `S4-OI-DIAG` 已经给出明确分层判断：

```text
1. 0-3km / 3-6km 可视为“条件可用”
2. 6-9km / 9-12km / 12km+ 仍然明显高风险
3. count_0 / count_1 / gap_ge30 这些稀疏支撑层也仍高风险
4. 所以当前更像“弱背景 / 诊断背景”，而不是“可直接混入 official recon 的强背景”
```

【关于 12km+ 的额外补充】本窗口还新增了：

- [centralized_stage4_altitude_cutoff_report.py](/data/LFT-W02_data/pengxu/stage/centralized_v1/core/centralized_stage4_altitude_cutoff_report.py)
- [stage4_altitude_cutoff_lt12km_baseline_200.md](/data/LFT-W02_data/pengxu/优化/stage4_altitude_cutoff_20260626/reports/stage4_altitude_cutoff_lt12km_baseline_200.md)

它回答的是：

```text
如果业务上把 12km+ 区域去掉，剩余部分 baseline 表现会怎样？
```

结果为：

```text
12km+ 点数占比 = 41.89%
12km+ SSE 占比 = 76.18%

全高度 baseline vector RMSE = 14.7690
<12km baseline vector RMSE   =  9.4552

全高度 frame P95 = 27.9861
<12km frame P95  = 20.9539
```

但要明确：

```text
这说明“12km+ 是主要误差污染源”是真的，
不代表官方全高度目标已经解决；
它本质上是“若业务允许改成 <=12km，则当前系统会显得更可接受”。
```

---

## 6. 阶段 B：Stage4 核心估计器升级（OI 弱背景，吃掉 4 类误差）

> 本阶段把原 plan_0625 的"优化1/3/7"统一进一个有统计意义的估计器：OI。
> representation error(R 膨胀)、sparse support(B 相关长度)、role conflict(创新量加权)、
> temporal weighting(R 时间膨胀)四类误差在同一 R/B 框架里被自然处理，而不是再手调乘法因子。

### 6.1 OI 数学形式（执行智能体必须按此实现，**勿用原 plan 的 nudging 写法**）

逐局地块求解（局地化，避免全局求逆）：

```text
对每个目标格点 g:
  d_i = y_i - x_b(i)                                # 训练观测 innovation (已剔 holdout)
  k_i = sigma_b(g)*sigma_b(i)*rho(g,i)             # 背景协方差(rho 复用现有 gaussian/Gaspari-Cohn 核)
  S_ij = sigma_b(i)*sigma_b(j)*rho(i,j) + delta_ij*sigma_i^2
  alpha = solve(S, d)
  x_a(g) = x_b(g) + k^T alpha
  analysis_var(g) = sigma_b(g)^2 - k^T solve(S, k)
  obs_influence(g) = clip(1 - analysis_var(g)/sigma_b(g)^2, 0, 1)

其中 sigma_i^2 = sigma_obs_i^2 + sigma_repr_i^2
  sigma_obs: EMADDC 分层 (0-3km 2.2 / 3-6km 2.5 / 6-15km 2.8)
  sigma_repr: 见 6.3 分层膨胀
```

语义（正好满足你的三诉求）：

```text
有观测: obs_influence→1, x_a→观测加权, analysis_var→0   (高置信)
无观测: obs_influence→0, x_a→x_b(CRA40背景), analysis_var→sigma_b^2  (低置信, 明确标注)
→ 完整风场 + 逐格点置信度 + CMA 弱背景, 一次性全给
```

> **命名纪律（防止论文被质疑）**：
> - 实现局地 S 矩阵求解 → 命名 `local_oi`
> - 只做对角近似(下式) → 必须命名 `oi_diag_approx`, 不得称完整 OI
> - 原 plan 的 `Σw_i·innovation_i/(Σw_i+ε_bg)` 量纲不严谨, 只能算 nudging heuristic, **禁止**直接当 OI 实现
>
> 对角近似(算力受限时):
> ```text
> raw_increment = Σ k_i*d_i/(sigma_b(i)^2+sigma_i^2)
> raw_var = sigma_b(g)^2 - Σ k_i^2/(sigma_b(i)^2+sigma_i^2)
> analysis_var = clip(raw_var, sigma_floor^2, sigma_b(g)^2)
> x_a(g) = x_b(g) + gain_cap(obs_influence)*raw_increment
> ```

### 6.2 为什么 OI 比历史失败分支更可能过门 + 诚实预期

```text
为什么更可能过: 历史失败分支(SRHA/sparse_temporal_cma/guarded_vertical/point_regime)
  都败在"用确定性规则在某 regime 强行改写场"→ light/12km+/floor10 反噬.
  OI 在有观测处几乎不动(obs_influence→1, 背景几乎无贡献)→ light/低层 dense 区结构不被污染.
  只在无观测处用背景填充, 那些地方本就进不了 holdout → 对 holdout RMSE 风险低, 对产品完整性收益大.

诚实预期(必须写给老师): OI 对 holdout RMSE 提升可能有限, 因为 holdout 点恰在观测密集处、本就被观测主导.
  OI 的最大价值是: (a)产品完整性(全场+置信度) (b)tail/12km+/sparse 区稳健性 (c)方法学正确性(可写论文).
  跑完若 weighted RMSE 只动 0.0x, 不算失败 — 按 §2.3 工程门作为"reliability branch"保留即可.
```

### 6.3 落地步骤（实验 ID `S4-OI-1`，依赖 S4-OI-DIAG 通过）

```text
Step A: CRA40 背景 NPZ (P0-CMA + S4-CMA-M1 Step1 已产出, 复用)
Step B: ground_recon.py 新增 OI 累加分支
  - 不动 _accumulate_localized; 新增 _accumulate_local_oi / _accumulate_oi_diag_approx (紧邻它)
  - 新增 CLI(需实现): --recon-mode {kernel_idw, oi_diag_approx, local_oi}
    kernel_idw 必须保持默认(保证 tp26 可复现)
  - 新增 CLI(需实现): --oi-sigma-obs-mode --oi-sigma-repr-config --oi-sigma-bg-mps
                      --oi-length-h-vox --oi-length-z-vox --oi-min-obs-influence --oi-max-increment-mps
  - 成场输出新场: recon_obs_influence_3d, recon_analysis_error_var_3d, recon_background_u/v_3d
    (只有 OI 分支过 200+5614 gate 后, 才考虑让 official recon_confidence_3d 改用 obs_influence)
Step C: R 的表示误差分层膨胀 (吃掉 representation_error)
  sigma_repr^2 = sigma_repr_base^2 * f_height(alt) * f_support(count,dist) * f_rolegap(role_gap) * f_time(time_conf)
    12km+ ×1.5~2.0; count_0/dist_ge6 ×1.5~2.5; gap_ge30 ×1.5~2.0; timeconf_0.4-0.6 ×1.3~1.6
  起步用 Desroziers 在线校准(6.5), 不要纯手猜
Step D: 先 report-only, 再允许改 official field (见 S4-OI-DIAG)
```

验收门 `S4-OI-1`：

```text
smoke(200): 全硬门槛不劣于 baseline (重点盯 light/12km+/floor10 不破)
formal(5614): 全硬门槛不劣
工程增益(满足其一即可升默认): A. weighted RMSE 改善>=0.05  或  B. >=2 目标层 RMSE 改善>=5%
若只持平但完整性+置信度图成立: 不升默认, 作为 product-completeness/reliability branch 保留写论文
```

### 6.4 拆分子实验（`S4-OI-1` 整体过不了时，一次只跑一个，smoke 打穿即停）

| 子ID | 只改 | 先看 | 过线 |
| --- | --- | --- | --- |
| `S4-OI-1a` | R 表示误差分层膨胀(仍 kernel_idw, 不引背景) | count_0/count_1/dist_ge6 | 这些层 RMSE 改善且硬门槛不破 |
| `S4-OI-1b` | B 各向异性相关长度(扩散核替高斯核) | gap_ge30/vgap_ge10/alt>=9km | ≥2 层改善 5% |
| `S4-OI-1c` | 引 CRA40 背景兜底(仅 obs_influence<0.1 格点) | 产品完整性+12km+ | 12km+/light 不破 |
| `S4-OI-1d` | Desroziers 在线校准 R/B | 全局 | 持平或更好, R/B 自洽 |

### 6.5 Desroziers 在线校准 R/B（修正原 plan_0625 优化1 的数学错误）

> **原 plan 错误**：把 O-A 和 O-B 都写成"holdout 减重构场"，两量塌缩。
> **正确**：需要背景 `x_b`(CRA40, 经 P0-LEAK 确认独立) 和分析 `x_a`(重构) 两个不同量，且只用 train 观测。

```text
d_ob = y - H x_b        (obs minus background, 用 train 观测, x_b=CRA40)
d_oa = y - H x_a        (obs minus analysis, x_a=OI重构)
d_ab = H x_a - H x_b
则: R ≈ <d_oa · d_ob^T>      (对角即可)
    HBH^T ≈ <d_ab · d_ob^T>
迭代: 用当前 R/B 跑 OI → 算 d_oa/d_ab → 更新 R/B → 收敛
实现为 centralized_stage4_oi_desroziers_calibrate.py, 输出每层 sigma_obs/sigma_repr/L_h/L_z 写入 OI 配置
对应文献PDF: "Diagnosis of observation, background and analysis-error statistics in observation space.pdf" (Desroziers 2005)
前提: P0-LEAK 必须确认 x_b 独立于 holdout, 否则 d_ob 统计无意义
```

---

## 7. 阶段 C：按失败 stratum 选做的 Stage4 受约束优化

> 这些与 OI 兼容（OI 里它们就是 R/B 的具体形式），也可独立做。按 §9.2 分支线，依据失败来源选一个做。

### `S4-B`：受约束的物理化局地化（修正原 plan_0625 优化2 的过自由方向）

```text
只改:   3 套 kernel family 间切换 + horizontal radius / vertical anisotropy / context-current ratio
不许改: 禁止再引入更细 point-wise 核 (point_regime 已证明 FAIL)
文献: R-Gilpin(2025) 高维下距离型局地化最稳; R-Er(2025) 局地化形状可随流场各向异性变化
  K1: dense/low-risk;  K2: sparse-current/fresh-context;  K3: high-alt/high-vgap/role-conflict
if/else:
  if alt>=9km and nearest_current_count<=1: 更强垂直 shrink + 更保守水平 widen
  if role_gap>=30: 不清空 context; 仅当 current_count>=2 且 dist<=1.5vox 才显著抬 current
  if vertical_gap>=10: 降低跨层耦合; else 维持 baseline 垂直保结构
验收: 200 smoke 先过; gap_ge30/vgap_ge10/alt>=9km 至少两层改善>=5%; full-5614 全过
```

### `S4-C`：regime-aware 时间权重校准

```text
只改:   context_time_conf_power 从全局常数 → 分层(timeconf 0.2-0.4/0.4-0.6/>=0.6, 再按 height×support 拟合半衰期)
不许改: localization / background
机制: 旧 context 不删, 通过抬高 σ(OI 模式下即 R 时间膨胀)降权
验收: timeconf_0.4-0.6 层 RMSE 改善>=5%; light wind 不恶化; 全局硬门槛过
```

### `S4-vert`：各向异性扩散垂直保护（原 plan_0625 优化4，**降级为中风险 + 强制 report-only 先行**）

> **原 plan 错误**：标"极低风险"。但项目里所有垂直干预(SRHA/guarded_vertical)都失败过。

```text
只改:   垂直方向权重核, 用 Perona-Malik 形式 w_vert = 1/(1+(|Δu_vert|/K)^2)
不许改: 水平核; 12km+ 默认关闭(field-v2 经验)
文献: Perona&Malik(1990) "Scale-space and edge detection using anisotropic diffusion.pdf"
  K(z)=K0*(1+β*z/z_max) 高空阈值更大(允许保留更强垂直梯度)
强制流程:
  1. 先 report-only: 只计算扩散调制后的垂直权重, 输出诊断, 不改 recon
  2. 200 smoke: 重点盯 12km+/light/floor10 — 任一恶化立即停(SRHA/guarded_vertical 都死在这)
  3. 过 smoke 才 full-5614
验收: vertical_structure 相关层改善 且 12km+/light/floor10 全不破
```

### `S4-E`：把 tail-risk / no-claim 升级为正式 gate（审批纪律，不改重构）

```text
把 P95/P99/max/tail coverage/risk-strata hit-rate 固定为二级主表; 任何候选:
  改善均值却恶化 P95/P99/12km+ → reject
  只改善 tail 却恶化 light/floor10 → 只能 report-only
对应文献: Allen(2024) tail calibration
```

---

## 8. 阶段 D：Stage5 残差（先修目标定义，再谈模型）

> **核心认知（原 plan_0625 优化5 缺失）**：Stage5 一直过不了门不是模型不够大，而是目标定义错了。
> 点级最安全候选改善仅 -0.004433 m/s；excess variance fraction 0.93 是表示误差，不是残差网络能在"点 vs 500m 体素"尺度学回来的可恢复信号。
> **结论：Stage5 必须换目标——从"降点 RMSE"改为"学在哪里不要改"。** 且只有 Stage4 official branch 变更并过 gate 后才重抽 residual dataset。

### `S5-A`：不确定性驱动的弃改残差（uncertainty-gated abstention，推荐主线）

```text
只改:   把 Stage5 重定义为"学在哪里 abstain", 不是"在哪里改一点"
不许改: alt>=12km 固定 residual=0 (field-v2 已证)
做法:
  - 模型已有异方差输出(delta,sigma), 扩展为 deep ensemble(多seed)得 epistemic 方差
  - split/局地空间 conformal 把 90% 区间校准到 holdout 覆盖率 87-93%
  - 应用规则: residual 仅在 (区间宽<阈) 且 (alt<12km) 且 (not light) 且 (support good) 时施加; 否则 abstain→保持 Stage4 场
文献: R-PIConf(physics-informed conformal), R-LSCP(local conformal quantile), R-Confm
  对应PDF: 无直接, 但 PINN 基础在 "Physics-informed neural networks...PDF" (Raissi 2019)
价值: 即使 RMSE 不降, 也产出校准良好的不确定性场(论文可写、产品可用)
验收: point continuation gate(RMSE改善>=0.02, P95改善>=0.10, 90% coverage∈[87,93], 多seed符号一致) → 才进 200 field smoke(alt12 关)
```

### `S5-B`：PINN 训练稳定化（无论哪个目标都要做）

```text
文献: R-WangPINN(2023 Expert's Guide), R-Rathore(2024 loss landscape)
  1. Fourier feature embedding + modified MLP (抗谱偏差)
  2. 动态损失权重 (NTK/grad-norm 平衡 PDE/data/BC)
  3. 优化器 Adam warmup → L-BFGS refine; 仍不稳再二阶
  if 不同 seed 结果符号不一致 → 是噪声不是信号, 停
```

### `S5-D`：observation-informed 残差架构（PINN plateau 后 fallback）

```text
if PINN 稳定化+UQ 后点级改善仍<0.02 m/s: 停止拧 PINN, 转:
  B1: set-transformer/cross-attention 残差 (R-ORCA, marine wind 1h 降误差45%)
  B2: FNP 任意分辨率同化 (R-FNP)
  B3: Energy Transformer 稀疏场重构 (R-ET, 90%缺测可恢复)
```

---

## 9. 执行顺序、分支线、实验矩阵

### 9.1 推荐执行顺序（严格按此，先低风险高价值）

```text
第0步(前置必做): P0-FRAME + P0-LEAK + P0-CMA + P0-FLOOR
第0.5步(新增):   P0-GFS 完成独立 forecast 背景下载与缓存
第1步: S4-CMA-M1  display-only 兜底 → 立刻交付"完整场+置信图", 对 official 零风险
第2步: S4-OI-DIAG report-only innovation/obs_influence 诊断, 背景优先改用 GFS, 不改 recon
第3步: 若背景可靠 → S4-OI-1a/1b (R膨胀+B各向异性, 先 oi_diag_approx)
第4步: S4-OI-1c/1d 引独立背景 OI + Desroziers 校准
第5步: 按失败 stratum 选 S4-B / S4-C / S4-vert / S4-E
第6步: 只有 Stage4 official branch 变更且过 gate 后, 才重抽 Stage5 residual dataset
第7步: S5-A (UQ-gated abstention) + S5-B 稳定化; plateau 后 S5-D
全程: S4-E tail gate 纪律
```

### 9.2 分支选择线（按失败来源决定先做哪个）

```text
失败主来自 count_0/count_1/dist_ge6 → S4-OI-1a + S4-CMA-M1/OI-1c
失败主来自 gap_ge30/role_conflict   → S4-B
失败主来自 timeconf_0.4-0.6         → S4-C
失败主来自 vertical_structure       → S4-vert (强制 report-only 先行)
失败主来自 tail 非 mean             → S4-E
想同时改 localization+background+temporal → 拒绝, 必须拆成单机制 ablation
```

### 9.3 实验矩阵

| ID | 阶段 | 只改 | 不许改 | 先看 | smoke 过 | formal 过 | 失败转向 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `S4-CMA-M1` | A product | display-only CRA40 兜底 | official recon / point eval | display 覆盖率/置信图 | 官方指标==baseline | 同 | 修 display fill |
| `S4-OI-DIAG` | A report | innovation/obs_influence 诊断 | recon_u/v | OMB 分层/背景可靠性 | 无需 promotion | 只报告 | 不进 OI |
| `S4-OI-1a` | B | R 膨胀 + oi_diag_approx | bg official blend | count/dist | 不破 light/12km+ | 持平+稳健 | S4-OI-1b |
| `S4-OI-1b` | B | B 各向异性 | bg official blend | gap/vgap/alt9 | 全过 | ≥2层≥5% | S4-B |
| `S4-OI-1c` | B | CRA40 local OI 背景 | 手调 broad rescue | 完整性+12km+ | 12km+/light 不破 | count_0≥5% | 退 M1-only |
| `S4-OI-1d` | B | Desroziers 校准 | holdout truth | 全局 | 持平 | R/B 自洽 | 保守值 |
| `S4-B` | C | 3 套约束 kernel | bg | gap/vgap/alt9 | 全过 | ≥2层≥5% | S4-C |
| `S4-C` | C | regime 时间衰减 | localization/bg | timeconf_0.4-0.6 | light 不恶化 | 该层≥5% | 退 baseline |
| `S4-vert` | C | 各向异性扩散垂直核 | 水平核; 12km+关 | 12km+/light/floor10 | report-only先过 | vert层改善且tail不破 | 退 baseline |
| `S4-E` | C | tail/no-claim gate | 重构本身 | P95/P99/12km+/floor10 | gate 无歧义 | 后续按新 gate 审批 | 不适用 |
| `S5-A` | D | UQ-gated abstention | PINN 架构 | coverage/tail | continuation gate | 200 全过 | S5-B/S5-D |
| `S5-B` | D | Adam→L-BFGS+动态权重 | apply gate | point dataset | RMSE≥0.02,P95≥0.10 | 进 field | S5-D |
| `S5-D` | D | observation-informed 架构 | S4 主干 | point first | continuation | 200+5614 全过 | 停 default 推进 |

执行规则：一次一个 ID；独立目录 + 独立 promotion_checklist.json；固定 `--promotion-tolerance 1e-9`；smoke 打穿即停。

### 9.4 pairwise 正式比较模板（200 smoke / 5614 formal 同此）

```bash
$PY stage/centralized_v1/core/centralized_stage4_pairwise_frame_compare.py \
  --baseline-csv <tp26>/stage4_localization_sensitivity.csv \
  --candidate-csv <cand>/stage4_localization_sensitivity.csv \
  --baseline-point-csv <tp26>/stage4_point_departures.csv \
  --candidate-point-csv <cand>/stage4_point_departures.csv \
  --baseline-label tp26 --candidate-label candidate \
  --out-dir <out> --out-prefix tp26_vs_candidate \
  --top-n 30 --promotion-tolerance 1e-9
```

---

## 10. 文献—方法—代码对应表（21 篇 PDF 全覆盖，便于写论文引用）

| 优化 | 文献 PDF | 在本计划中的角色 |
| --- | --- | --- |
| OI 估计器 + 置信度图 | NCEP Data Assimilation; PyDDA | OI = BLUE, A=(I-KH)B 误差方差图 |
| Desroziers R/B 校准 | Diagnosis of observation, background and analysis-error statistics... | S4-OI-1d 在线校准（**已修正数学**） |
| representation error | On the representation error in data assimilation | S4-OI Step C 的 σ_repr 理论 |
| 观测误差地板 | Estimates of Mode-S EHS...triple collocation; EMADDC 2025 | P0-FLOOR 误差地板 + R 下界 |
| 各向异性扩散垂直保护 | Scale-space and edge detection using anisotropic diffusion (Perona-Malik) | S4-vert（**已降级为中风险**） |
| 线性化物理弱约束 | Linearised physics the heart of ECMWF's 4D-Var | OI 物理约束设计哲学(散度/涡度平滑作正则) |
| LETKF 局地化 | Efficient data assimilation...local ensemble transform Kalman filter | S4-B 受约束 localization（**改为3套kernel family**） |
| Residual PINN | Physics-informed neural networks (Raissi 2019) | S5 残差框架基础 |
| 神经算子探索 | Fourier Neural Operator; DeepONet | S5-D fallback(长期) |
| observation-informed / 扩散 DA | DiffDA; Neural GCM; GraphCast; Probabilistic weather forecasting ML | S5-D 架构 fallback 参考 |
| 飞机风重构对照 | GPR(2 篇); Polynomial Chaos EGPR; meteo-particle model; dual-Doppler 3D wind retrieval; spatial interpolation effects | 论文 related work + 方法对照基线 |

---

## 11. 给执行智能体的最终 checklist

```text
[x] 第0步 P0-FRAME : 已核实 txt / json 双支持; txt→json 不再 blocker
[△] 第0步 P0-LEAK  : 已形成 cma_independence_report.md; 结论是 CMA 不放行 OI 主背景
[x] 第0步 P0-CMA   : verify_cma_grib.py 已写并跑完
[x] 第0步 P0-FLOOR : 误差地板估计脚本已完成工程版
[x] 第0.5步 P0-GFS : 200帧 GFS 历史背景已全部下载完成，并补齐到 21层 / 100hPa / 15.80km
[x] 第0.6步 P0-GFS-VERIFY : verify_gfs_background 已完成，ready_for_s4_oi_diag=true
[△] 第1步 S4-CMA-M1: baseline 已跑; 6代表帧 display-only 已跑; full-200 pairwise 封口待补
[x] 第2步 S4-OI-DIAG: GFS 版 report-only 已跑完，不改 recon；结论是 weak/diagnostic background，可做 constrained OI，小心 high-risk strata
[x] 第2.5步 P0-ALT12-CUT: <12km 评估脚本已补；已证实 12km+ 占 SSE 76.18%
[ ] 第3步 S4-OI-1a/1b: --recon-mode oi_diag_approx/local_oi + _accumulate_local_oi
[ ] 第4步 S4-OI-1c/1d: 独立背景 OI + Desroziers 校准(数学按 6.5, 非原 plan 写法)
[ ] 第5步 按失败 stratum 选 S4-B / S4-C / S4-vert / S4-E
[ ] 第6步 仅 Stage4 official branch 过 gate 后, 重抽 Stage5 residual dataset
[ ] 第7步 S5-A UQ-gated abstention + S5-B 稳定化; plateau→S5-D
每步: 独立输出目录 + promotion_checklist.json; smoke→formal 两道门; 一次一个 ID
红线: CMA 永不进真值; strict_holdout_no_leakage 不破; motion 不当风; 背景填充区不进官方 RMSE; 12km+ 背景默认极低置信
交接后首要任务: 先读完 GFS verify / OI-DIAG / altitude-cutoff 三份报告，再决定走“全高度 constrained OI”还是“<=12km 业务口径”
```

---

## 12. 一句话总纲

> 先做**零风险的 CMA display 兜底填充**满足"完整场+低置信标注"产品需求，并估出**误差地板**框定真实改进空间；
> 再把 Stage4 从启发式核插值升级为**有 B/R 协方差的局地 OI**，用 Desroziers 在线校准（修正了原 plan 的数学错误），让 representation/sparse/role/temporal 四类误差在统一框架里被处理；
> 受约束的 localization / 时间校准 / 各向异性垂直保护按失败来源择一推进（**所有垂直干预强制 report-only 先行**，因历史全部失败过）；
> Stage5 不再追"降点 RMSE"（已逼近误差地板），改为**学习在哪里弃改 + 校准不确定性**。
> 每一步都有文献支撑、200→5614 两道门、明确 if/else 回退，且严守 strict holdout、CMA 不进真值、motion 不当风三条红线。
</content>
</invoke>
