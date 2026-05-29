# Stage4 论文实验矩阵

## 这份文档的作用
这份文档用于把当前 `Stage4` 固定成论文实验平台，直接服务于：

- 版本定义
- 消融实验
- 结果表格
- 实验章节写作

当前定位：

- `Stage3`：并行分片，负责 agent / communication graph
- `Stage4`：单卡串行，负责多源风场重建与状态构建
- `Stage5`：后续事件驱动实时预测

因此当前论文实验重点是：

- `Stage4` 是否稳定
- `Stage4` 各模块是否有贡献
- `Stage4` 是否适合作为 `Stage5` 的输入状态层

---

## 一、实验目标

实验目标不应表述为“让 coverage 越高越好”，而应表述为：

**验证 `Stage4` 作为稀疏多源风场状态构建层，是否同时满足：**

- sparse anchor fidelity 稳定
- 全场置信层次合理
- coverage 温和提升
- 运行成本可控
- 可为后续 `Stage5` 提供稳定输入

---

## 二、版本命名

## `S0 DirectOnly`
含义：

- 不做任何后处理增强
- 只保留最基础直接观测重建能力

用途：

- 最低基线

## `S1 BaseRecon`
含义：

- 保留基础 `_reconstruct_wind_field()` 重构
- 不启用补全、平滑、裁剪、扩展、锚点保护

用途：

- 基础重构层对照

## `S2 SupportTemporal`
含义：

- 在 `S1` 基础上启用：
  - support fill
  - temporal fill

用途：

- 验证稀疏补全与时序背景的贡献

## `S3 PhysicsSmooth`
含义：

- 在 `S2` 基础上再启用：
  - relax

用途：

- 验证轻量物理一致性松弛是否改善稳定性

## `S4 ConfPruneAnchor`
含义：

- 在 `S3` 基础上再启用：
  - prune
  - direct anchor restore
  - direct anchor force

用途：

- 验证 confidence shaping 与锚点保护

## `S5 FinalFast`
含义：

- 在 `S4` 基础上再启用：
  - expand
- profile：
  - `fast_balanced`

用途：

- `Stage4` 最终运行主版本
- 论文主结果版本

## `S6 FullAux`
含义：

- `full_aux_export` 版本
- profile：
  - `aux_aggressive`
- richer aux fields

用途：

- 训练前导出版本
- 不是运行主链版本

---

## 三、开关矩阵

### Shared Runtime Settings
所有 `Stage4` 版本默认共用：

- `Stage3` 多卡分片
- `Stage4` 单进程单卡
- 默认运行链路只保留 `readiness`
- 默认不跑：
  - `sparse_metrics`
  - `outliers`
  - `npz_check`
  - `keylog`

### Module Switches

| Version | SUPPORT_FILL | TEMPORAL_FILL | RELAX | PRUNE | EXPAND | ANCHOR_RESTORE | ANCHOR_FORCE |
|---|---:|---:|---:|---:|---:|---:|---:|
| S0 DirectOnly | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| S1 BaseRecon | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| S2 SupportTemporal | 1 | 1 | 0 | 0 | 0 | 0 | 0 |
| S3 PhysicsSmooth | 1 | 1 | 1 | 0 | 0 | 0 | 0 |
| S4 ConfPruneAnchor | 1 | 1 | 1 | 1 | 0 | 1 | 1 |
| S5 FinalFast | 1 | 1 | 1 | 1 | 1 | 1 | 1 |
| S6 FullAux | 1 | 1 | 1 | 1 | 1 | 1 | 1 |

对应环境变量：

- `WIND_STAGE4_ENABLE_SUPPORT_FILL`
- `WIND_STAGE4_ENABLE_TEMPORAL_FILL`
- `WIND_STAGE4_ENABLE_RELAX`
- `WIND_STAGE4_ENABLE_PRUNE`
- `WIND_STAGE4_ENABLE_EXPAND`
- `WIND_STAGE4_ENABLE_DIRECT_ANCHOR_RESTORE`
- `WIND_STAGE4_ENABLE_DIRECT_ANCHOR_FORCE`

补充：

- `S5` 默认 `WIND_STAGE4_OUTPUT_PROFILE=fast`
- `S6` 默认 `WIND_STAGE4_OUTPUT_PROFILE=full_aux_export`

---

## 四、指标矩阵

建议统一记录 4 组指标。

## A. Sparse Anchor Fidelity
来源：

- `report_stage4_sparse_metrics.py`

记录：

- `rmse_u`
- `rmse_v`
- `vector_rmse`
- `mae_u`
- `mae_v`
- `corr_u`
- `corr_v`
- `coverage`
- `robust_vector_rmse_p995`
- `outlier_count`

说明：

- 这是论文主准确性指标组
- 用于证明直接观测锚点没有被破坏

## B. Full-Field Reconstruction Quality Proxies
来源：

- `stage4_summary.json`

记录：

- `recon_conf_mean`
- `recon_coverage_ratio`
- `recon_conf_p10`
- `recon_conf_p50`
- `recon_conf_p90`
- `recon_conf_spread_p10_p90`
- `recon_domain_voxels`
- `recon_support_domain_voxels`

说明：

- 用于描述全场状态质量
- 不把它解释成真实 full-field truth 误差

## C. Interpretability / Structure Indicators
来源：

- `stage4_summary.json`

记录：

- `support_fill_voxels`
- `support_fill_kept_voxels`
- `temporal_fill_voxels`
- `temporal_fill_kept_voxels`
- `support_expand_voxels`
- `anchor_restore_voxels`
- `anchor_force_voxels`
- `direct_agreement_mean`
- `physics_weight_mean`
- `source_diversity_mean`
- `comm_joint_voxels`

说明：

- 用于解释模块贡献
- 是消融分析的重要支撑

## D. Runtime Metrics
来源：

- `stage4` 主日志

记录：

- total `elapsed`
- `fps`
- `quality_profile`
- `support_fill=... temporal_fill=... relax=... prune=... expand=...`
- `stage3=sharded / stage4=single-gpu-serial`

说明：

- 用于证明系统“可运行”

---

## 五、结果表模板

## Table 1. Main Result Table

| Version | Vector RMSE | Corr(u/v) | Outlier Count | Recon Conf Mean | Recon Coverage | Conf Spread | Elapsed |
|---|---:|---:|---:|---:|---:|---:|---:|
| S0 |  |  |  |  |  |  |  |
| S1 |  |  |  |  |  |  |  |
| S2 |  |  |  |  |  |  |  |
| S3 |  |  |  |  |  |  |  |
| S4 |  |  |  |  |  |  |  |
| S5 |  |  |  |  |  |  |  |

说明：

- `S5 FinalFast` 作为主结果版本
- `S0-S4` 作为消融对照

## Table 2. Module Contribution Table

| Version | Support Fill | Temporal Fill | Relax | Prune | Expand | Anchor Protect | Coverage | Conf Mean |
|---|---|---|---|---|---|---|---:|---:|
| S1 | off | off | off | off | off | off |  |  |
| S2 | on | on | off | off | off | off |  |  |
| S3 | on | on | on | off | off | off |  |  |
| S4 | on | on | on | on | off | on |  |  |
| S5 | on | on | on | on | on | on |  |  |

## Table 3. Structural Statistics Table

| Version | Support Fill Voxels | Temporal Fill Voxels | Support Expand Voxels | Anchor Restore | Anchor Force | Direct Agreement | Physics Weight | Source Diversity |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| S1 |  |  |  |  |  |  |  |  |
| S2 |  |  |  |  |  |  |  |  |
| S3 |  |  |  |  |  |  |  |  |
| S4 |  |  |  |  |  |  |  |  |
| S5 |  |  |  |  |  |  |  |  |

## Table 4. Fast vs FullAux Table

| Version | Output Profile | Recon Changed? | Aux Fields Complete | Coverage | Conf Mean | Elapsed |
|---|---|---|---|---:|---:|---:|
| S5 FinalFast | fast | no | partial |  |  |  |
| S6 FullAux | full_aux_export | no | yes |  |  |  |

说明：

- `S6` 不改变 `recon_*`
- 只补 richer auxiliary fields

---

## 六、消融章节怎么写

## 4.1 Overall Stage4 Performance
写法重点：

- 用 `S5 FinalFast` 作为主版本
- 强调：
  - sparse anchor fidelity 稳定
  - coverage 温和提升
  - confidence 有层次
  - 运行链路可控

## 4.2 Effect of Support and Temporal Completion
比较：

- `S1`
- `S2`
- `S3`

回答的问题：

- support fill 是否扩展了有效区域
- temporal fill 是否增强了连续帧稳定性
- relax 是否改善了结构一致性

## 4.3 Effect of Confidence Shaping and Anchor Protection
比较：

- `S3`
- `S4`

回答的问题：

- confidence shaping 是否提升了层次性
- prune 是否压制了低质量尾部
- direct anchor protection 是否避免直接观测退化

## 4.4 Final Fast vs Training-Oriented FullAux
比较：

- `S5`
- `S6`

回答的问题：

- 为什么 `fast` 适合运行主链
- 为什么 `full_aux_export` 适合训练前导出
- 两条 profile 分工不同，而不是谁绝对更优

---

## 七、推荐运行命令

## `S5 FinalFast` 全量
```bash
BASE_DIR=/data/LFT-W02_data/pengxu
STAGE_DIR=$BASE_DIR/stage

RUN_MODE=full \
RUN_LABEL_OVERRIDE=full_fast_stage4_frozen_v1 \
RUN_PHASE=full_fast_multi_gpu \
RUN_VALIDATE=1 \
PROGRESS_EVERY=50 \
STAGE3_PARALLEL_SHARDS=8 \
STAGE3_CPU_THREADS_PER_WORKER=1 \
STAGE4_CPU_THREADS=6 \
MULTI_GPU_STAGE4_SHARD=0 \
WIND_STAGE4_USE_GPU=1 \
WIND_STAGE4_GPU_DEVICE=cuda:0 \
WIND_STAGE4_ENABLE_SUPPORT_FILL=1 \
WIND_STAGE4_ENABLE_TEMPORAL_FILL=1 \
WIND_STAGE4_ENABLE_RELAX=1 \
WIND_STAGE4_ENABLE_PRUNE=1 \
WIND_STAGE4_ENABLE_EXPAND=1 \
WIND_STAGE4_ENABLE_DIRECT_ANCHOR_RESTORE=1 \
WIND_STAGE4_ENABLE_DIRECT_ANCHOR_FORCE=1 \
bash $STAGE_DIR/run_stage34_workflow_v2.sh
```

## `S6 FullAux` 全量
```bash
BASE_DIR=/data/LFT-W02_data/pengxu
STAGE_DIR=$BASE_DIR/stage

RUN_MODE=full \
RUN_LABEL_OVERRIDE=full_aux_export_stage4_frozen_v1 \
RUN_PHASE=full_aux_export \
RUN_VALIDATE=1 \
PROGRESS_EVERY=50 \
STAGE4_FAST_SOURCE_DIR=/data/LFT-W02_data/pengxu/stage4_output_v2 \
WIND_STAGE4_USE_GPU=1 \
WIND_STAGE4_ENABLE_SUPPORT_FILL=1 \
WIND_STAGE4_ENABLE_TEMPORAL_FILL=1 \
WIND_STAGE4_ENABLE_RELAX=1 \
WIND_STAGE4_ENABLE_PRUNE=1 \
WIND_STAGE4_ENABLE_EXPAND=1 \
WIND_STAGE4_ENABLE_DIRECT_ANCHOR_RESTORE=1 \
WIND_STAGE4_ENABLE_DIRECT_ANCHOR_FORCE=1 \
bash $STAGE_DIR/run_stage34_workflow_v2.sh
```

## 一个代表性消融命令：`S4 ConfPruneAnchor`
```bash
BASE_DIR=/data/LFT-W02_data/pengxu
STAGE_DIR=$BASE_DIR/stage

RUN_MODE=full \
RUN_LABEL_OVERRIDE=S4_conf_prune_anchor \
RUN_PHASE=full_fast_multi_gpu \
RUN_VALIDATE=1 \
PROGRESS_EVERY=50 \
STAGE3_PARALLEL_SHARDS=8 \
STAGE3_CPU_THREADS_PER_WORKER=1 \
STAGE4_CPU_THREADS=6 \
MULTI_GPU_STAGE4_SHARD=0 \
WIND_STAGE4_USE_GPU=1 \
WIND_STAGE4_GPU_DEVICE=cuda:0 \
WIND_STAGE4_ENABLE_SUPPORT_FILL=1 \
WIND_STAGE4_ENABLE_TEMPORAL_FILL=1 \
WIND_STAGE4_ENABLE_RELAX=1 \
WIND_STAGE4_ENABLE_PRUNE=1 \
WIND_STAGE4_ENABLE_EXPAND=0 \
WIND_STAGE4_ENABLE_DIRECT_ANCHOR_RESTORE=1 \
WIND_STAGE4_ENABLE_DIRECT_ANCHOR_FORCE=1 \
bash $STAGE_DIR/run_stage34_workflow_v2.sh
```

---

## 八、结果记录规范

每个版本至少保存：

- `stage4_summary.json`
- `stage4stats_*.log`
- `phase_status_*.log`
- `stage4_*.log`

如果需要补充论文结果：

- 再单独跑：
  - `reports_only`
  - 或 `RUN_PHASES=...`

去生成：

- `sparse_metrics`
- `outliers`
- `npz_check`

---

## 新窗口接手时的提醒

- 不建议一开始就把 `S0-S6` 全部做全量，成本太高。
- 建议顺序：
  1. 先跑 `S5 FinalFast` 全量
  2. 再跑 `S6 FullAux` 全量
  3. 消融版本先在固定子集上跑
  4. 结果稳定后再决定是否做全量消融
- 不要和外部论文做数值硬对比，因为数据不同。
- 论文里强调的是：
  - 问题结构差异
  - 方法迁移逻辑
  - 自己数据上的内部 baseline / ablation
