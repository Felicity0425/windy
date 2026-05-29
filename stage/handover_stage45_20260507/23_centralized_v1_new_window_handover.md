# centralized_v1 新窗口交接入口话术

## 这份文档的作用

这份文档是给新窗口直接进入当前项目状态用的入口说明。

当前项目口径已经发生变化：

```text
当前主线不是继续修旧 Stage4/Stage5 冻结链路，
而是进入新的 centralized_v1 中心化地空风场重构原型。
```

旧的 `Stage4 / Stage5` 主线仍然保留为历史参考，但新窗口默认应该从：

```text
/data/LFT-W02_data/pengxu/stage/centralized_v1
```

继续工作。

---

## 一、最短可复制给新窗口的话术

请先阅读并理解当前项目的新主线：

```text
当前项目已经切到 centralized_v1 新原型。

Stage1 暂时冻结接口。
Stage2-Stage5 聚焦中心化地面风场重构：
所有 Flight Agents 的观测数据先全量回传到 Ground Center，
飞机之间暂时不做 Air-to-Air 通信，
地面中心先用时间置信度组织观测；Stage2/Stage3 中空间置信度保持中性，
Stage4 再按 observation-to-target-voxel 距离做空间局地化权重。

当前云图预测不要再混进 Stage1-5 主线，
云图强耦合预测先放到 Stage6。

当前 Stage5 的主任务是：
PINN-proxy / diffusion-style 风场精炼、
future wind 生成、
以及把飞机前方关心区域的未来风场作为 downlink ROI 输出。

请不要先回到旧 Stage4 冻结主线。
请先看：
1. stage/handover_stage45_20260507/23_centralized_v1_new_window_handover.md
2. stage/handover_stage45_20260507/22_centralized_v1_architecture_notes.md
3. stage/centralized_v1/core/
4. workflow/centralized_v1_docs/stage4_20260527_nine_question_summary.md
5. workflow/centralized_v1_docs/stage4_20260527_four_followup_summary.md

下一步优先做：
1. 先读 `workflow/centralized_v1_docs/README.md` 和完整流程解释；
2. 确认 Stage1/2/3 已达标并暂时冻结接口；
3. 进入 Stage4 strict hold-out，让抽出的真实点不参与融合，并输出具体 point error；
4. Stage5 继续固定为 PINN-proxy / diffusion-style refine、future wind 和 downlink ROI；
5. 先做 2-10 帧可信 demo 验证，不建议现在全量跑 Stage2 或训练。
```

---

## 二、当前项目新主线

当前架构假设是：

```text
全量地空回传 -> Ground Center 中心化重构 -> PINN/Diffusion-like 风场精炼 -> future wind -> downlink ROI
```

具体含义：

1. `Stage1` 暂时不改。
2. `Stage2` 做粗网格多模态准备，但当前云图只作为后续接口背景，不是主目标。
3. `Stage3` 不再以空空通信图作为主线，而是退化成地面中心星型拓扑。
4. `Stage4` 在地面中心统一接收全量观测，做加权融合、盲区初构建和点对点误差评估。
5. `Stage5` 聚焦未来风场生成和飞机关心区域的定向下发。
6. 云图强耦合预测、风驱云图演变、飞机间云图稀疏通信，统一推迟到 `Stage6`。

---

## 三、当前代码入口

当前新项目代码目录：

```text
/data/LFT-W02_data/pengxu/stage/centralized_v1
```

长期解释文档入口：

- [README.md](/data/LFT-W02_data/pengxu/workflow/centralized_v1_docs/README.md)
- [stage2_stage3_full_process_explanation.md](/data/LFT-W02_data/pengxu/workflow/centralized_v1_docs/stage2_stage3_full_process_explanation.md)
- [stage4_strict_holdout_logic_and_results.md](/data/LFT-W02_data/pengxu/workflow/centralized_v1_docs/stage4_strict_holdout_logic_and_results.md)
- [new_window_handover_stage2_stage3.md](/data/LFT-W02_data/pengxu/workflow/centralized_v1_docs/new_window_handover_stage2_stage3.md)
- [stage4_20260527_nine_question_summary.md](/data/LFT-W02_data/pengxu/workflow/centralized_v1_docs/stage4_20260527_nine_question_summary.md)
- [stage4_20260527_four_followup_summary.md](/data/LFT-W02_data/pengxu/workflow/centralized_v1_docs/stage4_20260527_four_followup_summary.md)

统一 demo runner：

- [run_centralized_v1_demo.py](/data/LFT-W02_data/pengxu/stage/centralized_v1/run_centralized_v1_demo.py)

核心脚本：

- [centralized_stage2_multimodal.py](/data/LFT-W02_data/pengxu/stage/centralized_v1/core/centralized_stage2_multimodal.py)
- [centralized_stage3_center.py](/data/LFT-W02_data/pengxu/stage/centralized_v1/core/centralized_stage3_center.py)
- [centralized_stage4_ground_recon.py](/data/LFT-W02_data/pengxu/stage/centralized_v1/core/centralized_stage4_ground_recon.py)
- [centralized_stage4_sensitivity.py](/data/LFT-W02_data/pengxu/stage/centralized_v1/core/centralized_stage4_sensitivity.py)
- [centralized_cma_ra_virtual_radial_3dvar.py](/data/LFT-W02_data/pengxu/stage/centralized_v1/core/centralized_cma_ra_virtual_radial_3dvar.py)
- [centralized_report_cma_virtual_radial.py](/data/LFT-W02_data/pengxu/stage/centralized_v1/core/centralized_report_cma_virtual_radial.py)
- [centralized_stage5_wind_cloud.py](/data/LFT-W02_data/pengxu/stage/centralized_v1/core/centralized_stage5_wind_cloud.py)

切面可视化脚本：

- [centralized_report_stage4_slices.py](/data/LFT-W02_data/pengxu/stage/centralized_v1/core/centralized_report_stage4_slices.py)
- [centralized_report_stage5_slices.py](/data/LFT-W02_data/pengxu/stage/centralized_v1/core/centralized_report_stage5_slices.py)

配置与字段契约：

- [centralized_v1_config.py](/data/LFT-W02_data/pengxu/stage/centralized_v1/configs/centralized_v1_config.py)
- [centralized_v1_contract.py](/data/LFT-W02_data/pengxu/stage/centralized_v1/configs/centralized_v1_contract.py)

---

## 四、当前输出目录与已跑通结果

当前输出根目录：

```text
/data/LFT-W02_data/pengxu/centralized_v1_output
```

旧最小链路已经跑通的两个 demo 帧：

```text
20260129114200
20260206174200
```

旧 Stage2 输出，当前只作为历史参考：

- [stage2_multimodal_summary.json](/data/LFT-W02_data/pengxu/centralized_v1_output/stage2_multimodal/stage2_multimodal_summary.json)
- `/data/LFT-W02_data/pengxu/centralized_v1_output/stage2_multimodal/voxels`

当前 Stage2 主输出应使用：

- [stage2_multimodal_summary.json](/data/LFT-W02_data/pengxu/centralized_v1_output/stage2_regenerated/stage2_multimodal_summary.json)
- `/data/LFT-W02_data/pengxu/centralized_v1_output/stage2_regenerated/shards`
- `/data/LFT-W02_data/pengxu/centralized_v1_output/stage2_regenerated/slices`

旧 Stage3 输出，下一步需要改为读取 `stage2_regenerated`：

- [stage3_center_summary.json](/data/LFT-W02_data/pengxu/centralized_v1_output/stage3_center/stage3_center_summary.json)
- `/data/LFT-W02_data/pengxu/centralized_v1_output/stage3_center/agents`

Stage4 输出：

- [stage4_center_summary.json](/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_center/stage4_center_summary.json)
- [point_eval_20260129114200.txt](/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_center/point_eval_20260129114200.txt)
- [point_eval_20260206174200.txt](/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_center/point_eval_20260206174200.txt)
- [20260206174200_centralized_stage4_slices.png](/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_center/slices/20260206174200_centralized_stage4_slices.png)

当前新 strict Stage4 输出应使用：

- `/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_center_strict`
- `stage4_center_summary.json`
- `point_eval_<time>.json/csv/txt`
- `stage4_method_<time>.md`
- `slices/<time>_centralized_stage4_slices.png`

扩展 strict Stage4 小批量输出：

- `/data/LFT-W02_data/pengxu/centralized_v1_output/stage3_center_expanded`
- `/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_center_strict_expanded`
- `/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_center_strict_expanded/sensitivity/stage4_localization_sensitivity.csv`

扩展结果不覆盖旧 `stage4_center_strict` 两帧 baseline。

已验证 strict 两帧：

```text
20260208124800:
  hold-out = 15 / 114 current wind voxels
  fusion current wind = 99
  context wind = 1284
  pre-refine voxels = 276198
  final voxels = 417438
  final domain fraction = 3.309553%
  bbox = lat 17.240-36.760, lon 106.360-118.280, alt 0-15000 m
  diffusion fill = 141240
  RMSE vector = 6.468737 m/s
  MAE vector = 5.422913 m/s

20260211060600:
  hold-out = 1 / 1 current wind voxels
  fusion current wind = 0
  context wind = 1079
  pre-refine voxels = 217861
  final voxels = 339248
  final domain fraction = 2.689643%
  bbox = lat 19.000-37.480, lon 106.920-118.200, alt 500-15000 m
  diffusion fill = 121387
  RMSE vector = 3.390634 m/s
  MAE vector = 3.390634 m/s
  note = sparse-label pressure test
```

Stage4 refreshed slice figures now separate observation-supported voxels from
low-confidence proxy fill. A block-like footprint should be explained as
Gaussian localization radius plus neighbor fill, not as evidence that the real
flow is physically one block.

最新 Stage4 strict expanded 已验证：

```text
frames = 10
sensitivity rows = 60
localization kernels = gaussian, gaspari_cohn
default confidence_mode = diagnostic_only
strict_holdout_no_leakage = true for all expanded/sensitivity rows
motion_used_as_wind = false
mask_conf_positive_mismatch_voxels = 0 for all expanded Stage4 rows
Gaspari-Cohn mean RMSE ~= 8.535, MAE ~= 6.362
Gaussian mean RMSE ~= 8.918, MAE ~= 6.980
```

Stage2 full v2 和 Stage3 full v2 minimal 已经可用。当前不要直接全量跑
all-frame Stage4；下一步应先从 full Stage2/3 抽 100-300 帧做 Stage4
strict validation batch，并比较 baseline Gaussian 与 role-conflict
candidate。10 帧 expanded 指标、Gaussian/Gaspari-Cohn 灵敏度以及
`20260206174200` / `20260207022400` 两个高误差帧仍是解释和诊断参考。

Stage4 当前解释口径：

```text
PINN/diffusion 当前只是 proxy gap-fill scaffold，不是训练模型；
后续可以训练，但必须先扩大 strict 数据集并建立 train/val/test。

expanded 10 帧目前有数值输出，切面 PNG 需要另跑 centralized_report_stage4_slices.py。

Stage4 ground recon 原已验证 8 路 shard 并行；现在 12 路 shard 并行和
12 路 metrics-only smoke 也已验证。metrics-only sensitivity 支持
`--num-workers N`、`--sample-count` 和百分比进度输出，但要注意
每帧多个 3D array 的内存占用。

有效区域 = recon_mask_3d > 0，不等于完整中国区域网格。

diagnostic_only 是为了保持 baseline 可比；
diagnostic_weighted 要先做对照实验再决定是否默认启用。
```

当前 full-v2 validation batch 口径：

```text
Stage2 full v2:
/data/LFT-W02_data/pengxu/centralized_v1_output/stage2_full_v2/stage2_multimodal_summary.json

Stage3 full v2 minimal:
/data/LFT-W02_data/pengxu/centralized_v1_output/stage3_full_v2_8w_minimal/stage3_center_summary.json

Recommended Stage4 validation root:
/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_full_v2_validation_200_8w

Use --frame-times "" when sampling from the full Stage2 summary.
Use --sample-count 200 and --sample-seed 20260527 for the current comparison.
Historical 200-frame comparison used --num-workers 8. New candidate/demo runs
can use --num-workers 12 when memory allows.
Use --progress-interval-seconds 30 for metrics-only sensitivity.
Do not write validation-batch visualizations or per-parameter 3D NPZ outputs.
```

新增可视化：

- Stage2 点类型/颜色/大小编码图：`stage2_visual_encoding_<time>.png`
- Stage4 重构诊断图：`<time>_centralized_stage4_diagnostics.png`
- Stage4 切面精确统计：`<time>_centralized_stage4_slice_stats.csv`

Stage5 输出：

- [stage5_center_summary.json](/data/LFT-W02_data/pengxu/centralized_v1_output/stage5_center/stage5_center_summary.json)
- [20260206174200_centralized_stage5_future_slices.png](/data/LFT-W02_data/pengxu/centralized_v1_output/stage5_center/slices/20260206174200_centralized_stage5_future_slices.png)

运行日志：

```text
/data/LFT-W02_data/pengxu/stage/centralized_v1/logs
```

包括：

- `stage2_multimodal.log`
- `stage3_center.log`
- `stage4_center.log`
- `stage5_center.log`

---

## 五、当前已实现能力

### Stage2：all-in 观测组织

当前主线已经切到 `stage2_regenerated`：

- 从 Stage1 的 `clean_wind.parquet`、`clean_loc.parquet`、`radar_index.json`
  和雷达 PNG 重新生成 centralized_v1 专用输出；
- 把当前窗口真实风候选点、6 小时前后历史上下文风点、轨迹和运动观测统一投到
  `31 x 525 x 775` 的 3D 网格；
- 输出 voxel 网格记录，同时保留 point CSV，用于后续 strict hold-out 和点误差；
- 保留基础 radar/cloud 字段作为后续可视化和 Stage6 接口背景。

当前不要把 Stage2 理解成风场重构层，也不要理解成 ROI 裁剪层。  
它现在的主要价值是做“时间窗内、网格域内、字段可用、voxel 聚合”的 all-in
观测组织，为地面中心化风场重构准备统一输入。

### Stage3：地面中心星型拓扑

旧 demo 已经实现：

- 所有 Flight Agents 默认全量回传到 Ground Center
- 暂时不做 Air-to-Air 通信
- 输出每个 agent 的时间、空间与联合置信度

旧 demo 置信度公式：

```text
C_time = exp(-alpha * delta_time_minutes)
C_space = exp(-beta * distance_km)
C_joint = C_time * C_space
```

物理含义：

- `C_time`：观测越新，越可信；几分钟前的数据仍可用，但权重会衰减。
- `C_space`：离目标区域越近，越可信；距离越远，对局地重构影响越小。
- `C_joint`：同时考虑时间新鲜度和空间接近度，是 Stage4 加权融合的重要依据。

下一步 Stage3 要接新的 `stage2_regenerated` 输出，优先生成每帧
`ground_center_payload` 和 confidence package。新 Stage2 已经在记录级保存
`time_conf / space_conf / joint_likelihood`，Stage3 应先负责清楚打包、分组和解释，
不要在这里做最终风场重构。

### Stage4：地面中心 strict hold-out 重构

当前新 strict 口径：

- 接收 `stage2_regenerated` 和 Stage3 Ground Center 输出
- 从 `wind_records` 选择 hold-out 真值点
- 被抽出的真值点在融合前剔除，避免数据泄漏
- 使用非 hold-out current wind + `context_wind_records` 重构三维风场
- 对每个目标 voxel 使用 Gaussian observation-to-target-voxel localization
- 输出 `recon_u_3d / recon_v_3d / recon_confidence_3d`
- 输出 `c_time_3d / c_space_3d / c_joint_3d`
- 输出逐点误差 JSON / CSV / TXT 日志
- 输出切面图

Stage4 strict 公式：

```text
localization = exp(-0.5 * ((dx/sigma_xy)^2 + (dy/sigma_xy)^2 + (dz/sigma_z)^2))
active_weight = obs_conf * time_conf * localization
```

`motion_records` 和 `context_motion_records` 先只作为覆盖诊断，不直接当作风参与融合。

Stage4 当前还启用了轻量 PINN-proxy / diffusion-style 低置信填补：

```text
pinn smoothness / weak divergence regularization
+ diffusion-style low-confidence neighbor propagation
+ source-supported voxels preserve 0.95
```

它是物理启发的 gap-fill scaffold，不是训练好的 PINN 或 GenCast 式扩散模型。

### Stage5：未来风场与下行 ROI

当前已经实现：

- PINN-proxy refine
- diffusion-style refine
- future wind 生成
- downlink ROI 输出
- Stage5 future wind 切面图

当前 Stage5 的正确口径是：

```text
Stage5 = 未来风场生成 + 飞机关心区域下发
```

虽然当前文件名和输出里仍保留 `wind_cloud_demo` / `future_cloud` 字段，但云图主任务已经推迟到 `Stage6`，不要再把云图当成当前 Stage1-5 的主目标。

---

## 六、当前不能误读的边界

这些话新窗口必须先知道：

1. `centralized_v1` 已经跑通最小 demo，但不是最终论文版。
2. 当前 PINN / Diffusion 是 proxy / scaffold，不是训练好的深度模型。
3. 当前 Stage4 point eval 还需要严格化，现有结果不能直接当最终泛化误差。
4. 当前 blind-zone 是轻量初步构建，不是最终物理最优盲区重构。
5. 当前 Stage5 仍有 `future_cloud` demo 残留，但云图预测已经推迟到 `Stage6`。
6. 当前不建议马上全量运行，也不建议马上训练。
7. 旧 `Stage4` 冻结主线只作为历史参考，新窗口默认从 `centralized_v1` 继续。

---

## 七、下一步优先级

### 1. Stage3 Ground Center payload

当前先不要直接跳到旧 Stage4。Stage2 regenerated 已经达标，下一步应先让
Stage3 接入新的 summary：

```text
centralized_v1_output/stage2_regenerated/stage2_multimodal_summary.json
```

Stage3 每帧输出应清楚分组：

```text
label_candidates = wind_records
context_observations = context_wind_records / context_motion_records
trajectory_observations = loc_records
motion_observations = motion_records
confidence_package = time_conf / space_conf / joint_likelihood
```

### 2. 明确置信度含义

Stage3 文档和输出里必须解释：

- `time_conf`：时间新鲜度，观测离目标时刻越近越可信。
- `space_conf`：Stage2/Stage3 中性空间项，当前固定为 `1.0`；Ground Center
  只是逻辑汇聚中心，不代表空间物理中心。
- `joint_likelihood`：联合候选权重，当前 Stage2/Stage3 口径是
  `obs_conf * time_conf`。

这些置信度是 Stage4 融合权重候选，不是 Stage2/Stage3 的删数据条件。
真正的空间局地化留到 Stage4：重构某个目标 voxel 时，再按观测 voxel
到目标 voxel 的距离计算权重。

### 3. 严格化 Stage4 hold-out

Stage3 契约稳定后，再进入 Stage4 point eval。当前点误差日志已经有了，但下一步要做得更严谨：

```text
hold-out 只能从 wind_records 抽；
抽出的真实风点不能参与 Stage4 融合；
context_wind_records 只能作为历史上下文参与融合，不能作为真实标签。
```

输出仍应保留具体数值：

```text
[Point Eval] voxel=(z,y,x)
gt_u=...
gt_v=...
pred_u=...
pred_v=...
u_error=...
v_error=...
rmse=...
mae=...
bias=...
```

Stage4 汇总报告需要按下面维度统计：

- 分高度层
- 分强风 / 弱风
- 分稀疏程度
- top-k 最大误差点
- 每帧 RMSE / MAE / bias

这一步的目标是回答：

```text
这套中心化重构在哪些高度、哪些风速范围、哪些稀疏条件下稳定？
```

### 4. 固定 Stage5 当前口径

当前 Stage5 只服务：

- refined wind
- future wind
- downlink ROI

不要继续把云图预测混进 Stage1-5 当前验证目标。  
云图强耦合预测放到 `Stage6`。

最终验证方式是：重构出流动风场后，选择飞机关注的一点或前方 ROI，
对比真实风、Stage4 当前重构风、Stage5 future wind，给出具体数值误差和切面可视化。

### 5. 做 2-10 帧可信 demo 验证

暂时不要全量跑。  
建议先选：

- 弱风帧
- 强风帧
- 高风险帧
- 时空稀疏帧

目标不是追最优指标，而是确认：

```text
centralized_v1 在不同帧类型下是否稳定、可解释、可度量。
```

---

## 八、新窗口第一步建议

新窗口进入后，建议按这个顺序：

1. 先读本文档：
   - [23_centralized_v1_new_window_handover.md](/data/LFT-W02_data/pengxu/stage/handover_stage45_20260507/23_centralized_v1_new_window_handover.md)
2. 再读架构说明：
   - [22_centralized_v1_architecture_notes.md](/data/LFT-W02_data/pengxu/stage/handover_stage45_20260507/22_centralized_v1_architecture_notes.md)
3. 再看当前代码：
   - `/data/LFT-W02_data/pengxu/stage/centralized_v1/core`
4. 再看当前 demo 输出：
   - `/data/LFT-W02_data/pengxu/centralized_v1_output`

第一件应该做的工程任务：

```text
让 Stage3 默认读取 stage2_regenerated/stage2_multimodal_summary.json，
输出 ground_center_payload 和 confidence package；
随后再进入 Stage4 strict hold-out 和 point eval。
```

不要一上来做：

- 全量运行
- 训练 PINN / Diffusion
- 继续写云图预测
- 回到旧 Stage4 冻结主线

---

## 九、一句话总结

```text
centralized_v1 是当前新主线：
先用地面中心接收所有飞机观测，
用时空置信度做三维风场重构，
再用 PINN/Diffusion-like 方法精炼并生成未来风场，
最后把飞机前方关心区域作为 downlink ROI 输出。

当前最重要的下一步不是全量跑，
而是先用 2-10 帧把 Stage3 Ground Center payload 和 confidence package 做稳，
再严格化 Stage4 hold-out / point eval，
最后进入 Stage5 future wind 和 downlink ROI 验证。
```

---

## 十、2026-05-24 Stage2 regenerated 最新交接

Stage2 已经继续增强，不再沿用旧 `stage2_output/voxels` 作为输入，而是从
`stage1_output/clean_wind.parquet`、`clean_loc.parquet`、`radar_index.json`
和雷达 PNG 重新生成 centralized_v1 专用体素输出。

当前 Stage2 新输出目录：

```text
/data/LFT-W02_data/pengxu/centralized_v1_output/stage2_regenerated
```

核心代码：

- [centralized_stage2_multimodal.py](/data/LFT-W02_data/pengxu/stage/centralized_v1/core/centralized_stage2_multimodal.py)
- [centralized_report_stage2_slices.py](/data/LFT-W02_data/pengxu/stage/centralized_v1/core/centralized_report_stage2_slices.py)

新增知识库说明：

- [centralized_v1_stage2_authoritative_params.md](/data/LFT-W02_data/pengxu/workflow/centralized_v1_stage2_authoritative_params.md)

### Stage2 当前口径

Stage2 现在输出两类风观测：

```text
wind_records = 当前 +/-5 min 真实风候选点，用于后续 Stage4 strict hold-out
context_wind_records = +/-6 h 历史上下文风点，排除当前窗口，带置信度和似然
context_motion_records = +/-6 h 历史上下文轨迹运动点，带置信度和似然
```

这里的 `+/-6 h` 指以目标雷达时刻为中心，向前 6 小时、向后 6 小时，
总跨度 12 小时；并且 context 会排除 `abs(delta_time_minutes) <= 5`
的当前标签窗口。

注意：

```text
Stage2 的 all-in 是“当前帧时间窗内 + Stage2 中国区域网格内 + 字段可用”
意义上的 all-in；
不是把整库所有历史记录都塞进每一帧；
也不是逐点无聚合保存，而是按 (z,y,x) voxel 聚合；
历史 context 不是 Ground Truth 标签，
不能直接拿去做 point eval 的真实值。
它们只作为 Stage4 地面中心融合重构时的上下文观测。
```

### 高度层解释

当前 Stage2 使用：

```text
ALT_MAX = 15000 m
DELTA_ALT = 500 m
Z_DIM = 31
```

这表示高度范围仍然是 `0-15000m`，只是每 `500m` 一个高度箱。  
不是把高度上限改成 `500m`。

### Ground Center / reference_center / 置信度设定

Ground Center 是逻辑地面中心：

```text
所有 Flight Agent 观测都允许回传；
不因为飞机之间距离或通信可达性删数据；
Stage2 是 all-in observations 数据组织层；
reference_center 只作为图像和审计的参考点，
不是 ROI 裁剪区域，也不会在 Stage2 删除数据；
Stage2/Stage3 的 space_conf 固定为 1.0，
不会因为观测离 reference_center 远而降权。
```

reference_center 当前按帧设置：

1. 优先使用当前窗口 flight raw records 的 `lat/lon/alt` 中位数；
2. 如果当前窗口没有轨迹，退回中国区域 bbox 中心：

```text
lat = 33.2
lon = 104.0
alt = 0
```

当前 Stage2 metadata 同时写入新字段和兼容旧字段：

```text
stage2_role = observation_organization_not_reconstruction
all_in_observations = true
all_in_scope = per_frame_time_window_grid_domain_required_fields_before_voxel_grouping
reference_center_does_not_filter_records = true
reference_center_used_for_weighting = false
stage2_space_conf_mode = neutral_all_in
target_voxel_localization_deferred_to_stage4 = true
reference_center_policy = current_window_flight_median_after_voxel_domain_filter
reference_center_source / lat / lon / alt_m
roi_center_source / lat / lon / alt_m  # 兼容别名
```

当前 context 置信度公式：

```text
time_conf = 0.5 ** (abs(delta_time_minutes) / 180)
space_conf = 1.0
space_likelihood = 1.0
joint_likelihood = obs_conf * time_conf
```

为兼容已有字段名，记录里仍保留 `distance_to_roi_km` /
`vertical_delta_to_roi_m`，但它们只作为诊断信息保留，不参与 Stage2/Stage3
权重。后续 Stage4 应该按“观测 voxel 到目标 voxel”的距离做 Gaussian 或
Gaspari-Cohn-style 局地化，而不是按观测到 reference_center 的距离。

参数依据已整理到 workflow 知识库，主要参考：

- ECMWF ERA5 / IFS 4D-Var 的小时级资料与 6h/12h assimilation window 思路
- WMO AMDAR aircraft-based observations
- DART localization / Gaspari-Cohn 思路：支持目标状态/目标 voxel 的局地化，
  不支持把逻辑 Ground Center 当成物理降权中心
- WeatherBench2 / GraphCast / GenCast / Aurora / FourCastNet 的规则网格与时序上下文组织

### 8 路 shard 运行命令

已实现真正 8 路 shard subprocess，不是线程池：

```bash
/data/LFT-W02_data/pengxu/.conda/envs/windy310/bin/python \
  stage/centralized_v1/core/centralized_stage2_multimodal.py \
  --num-workers 8 \
  --current-window-minutes 5 \
  --context-window-minutes 360 \
  --alt-step-m 500 \
  --time-conf-halflife-minutes 180 \
  --space-sigma-km 180 \
  --vertical-sigma-m 2500 \
  --frame-times 20260208124800,20260206174200,20260207022400,20260131073000,20260215063600,20260215063000,20260215100600,20260211060600,20260213053600,20260210060000
```

Shard 输出：

```text
/data/LFT-W02_data/pengxu/centralized_v1_output/stage2_regenerated/shards
```

合并 summary：

```text
/data/LFT-W02_data/pengxu/centralized_v1_output/stage2_regenerated/stage2_multimodal_summary.json
```

### 已验证 10 帧结果

本轮 10 帧 demo 已用 `--num-workers 8` 跑通。

所有帧：

```text
grid_shape = [31, 525, 775]
parallel_mode = shard_subprocess
num_workers = 8
```

代表帧 `20260208124800`：

```text
wind_records = 114
context_wind_records = 1284
reference_center_source = current_flight_raw_median
```

新版 Stage2 切面图：

```text
/data/LFT-W02_data/pengxu/centralized_v1_output/stage2_regenerated/slices/20260208124800_centralized_stage2_slices.png
/data/LFT-W02_data/pengxu/centralized_v1_output/stage2_regenerated/slices/20260211060600_centralized_stage2_slices.png
```

每张切面图对应的解释输出：

```text
/data/LFT-W02_data/pengxu/centralized_v1_output/stage2_regenerated/slices/stage2_slice_explanation_<time>.md
/data/LFT-W02_data/pengxu/centralized_v1_output/stage2_regenerated/slices/stage2_slice_stats_<time>.csv
/data/LFT-W02_data/pengxu/centralized_v1_output/stage2_regenerated/slices/stage2_slice_points_<time>.csv
/data/LFT-W02_data/pengxu/centralized_v1_output/stage2_regenerated/slices/stage2_data_integrity_<time>.md
/data/LFT-W02_data/pengxu/centralized_v1_output/stage2_regenerated/slices/stage2_data_integrity_<time>.csv
/data/LFT-W02_data/pengxu/centralized_v1_output/stage2_regenerated/slices/stage2_data_integrity_summary.md
```

图像解释口径：

```text
灰度底图 = cloud_2d / radar_img，越亮表示雷达回波越强；
橙色箭头/圆点 = wind_records，当前 +/-5min 真实风候选点；
紫/洋红色 x = context_wind_records，+/-6h 历史上下文风点；
蓝色小点 = loc_records，当前窗口轨迹密度体素；
绿色小点 = motion_records，当前窗口飞机运动分量体素。
```

两张图均为 `4216 x 1563`，上排是 4 个自动选择的水平高度切面，
下排是 `x=387 +/-6` 的 y-z 垂直剖面和高度统计曲线。
这个尺寸来自 matplotlib 渲染设置：

```text
figsize = (6.2 * 4, 9.2) inch
dpi = 170
输出像素约为 4216 x 1563
```

它不是雷达拼图分辨率。当前 Stage2 的 `cloud_2d/radar_img` 是
`525 x 775`，来自原始雷达 PNG 按 `xy_downsample=4` 下采样。

当前两帧关键解释：

```text
20260208124800:
  wind_records = 114
  context_wind_records = 1284
  auto z = 27,29,25,23
  altitude = 13500m,14500m,12500m,11500m
  cloud_2d nonzero pixels = 2676
  cloud_2d max = 225

20260211060600:
  wind_records = 1
  context_wind_records = 1079
  auto z = 23,21,29,25
  altitude = 11500m,10500m,14500m,12500m
  cloud_2d nonzero pixels = 845
  cloud_2d max = 225
  注意：唯一 current wind 不在自动展示的四个 z 层内，
  所以图上四个水平切面的 current 数都是 0。
```

### Stage2 数据完整性审计结论

Stage1 当前规模：

```text
clean_wind rows = 431189
clean_loc rows = 19162638
radar_index rows = 7396
usable radar frames = 7395
```

`20260208124800`：

```text
wind raw window = 9319
current wind raw = 483
current wind in-domain = 136
current wind voxel records = 114
context wind raw = 8836
context wind in-domain = 1689
context wind voxel records = 1284
loc current raw = 7224
motion usable current = 6697
traj voxel records = 5175
motion voxel records = 4887
context loc raw = 334167
context motion usable = 306898
context motion voxel records = 38691
```

`20260211060600`：

```text
wind raw window = 10127
current wind raw = 124
current wind in-domain = 1
current wind voxel records = 1
context wind raw = 10003
context wind in-domain = 1507
context wind voxel records = 1079
loc current raw = 7478
motion usable after grid filtering = 6110
traj voxel records = 5247
motion voxel records = 4506
context loc raw = 409376
context motion usable = 345481
context motion voxel records = 38761
```

当前完成度判断：

```text
Stage2 作为数据组织层已经可用：
它能从 Stage1 重新生成 current wind labels、historical wind context、
trajectory、motion 和 radar/cloud features，并统一投到 3D 网格。

短板主要是数据质量诊断，而不是数据接入：
某些帧 current wind 极稀疏，例如 20260211060600；
某些 context wind / motion speed 数值很大，应作为 QC candidate 报告。
Stage2 默认不删除这些值，避免在进入 Stage4 前静默丢信息。
```

### Stage2 gate 结论

当前 Stage2 可以判定为“数据组织层达标，可以进入 Stage3 小批量开发”。

达标含义是：

```text
Stage2 已经从 Stage1 clean parquet 和 radar PNG 重新生成：
current wind labels、historical context wind、trajectory、motion、radar/cloud；
并统一组织到 31 x 525 x 775 规则网格。

Stage2 的 all-in 是：
每帧时间窗内 + 中国区域网格内 + 0-15000m + 字段可用 + voxel 聚合。

Stage2 没有 ROI 裁剪，也没有按照 reference_center 距离删数据或降权。
reference_center 只作为图像/审计参考点；空间局地化推迟到 Stage4 的目标 voxel 重构。
```

不建议现在全量运行 Stage2。当前更合理的路线是：

```text
2-10 个代表帧 -> Stage3 Ground Center payload/confidence package ->
Stage4 strict hold-out + point eval -> 链路稳定后再决定是否全量 Stage2。
```

全量 Stage2 对最终统计指标和稳定报告有价值，但不阻塞当前 Stage3/Stage4
契约开发。现在直接全量跑，容易把时间花在批处理吞吐上，而不是验证核心链路。

### 体素化解释与保留策略

体素化就是把连续空间里的飞机观测点，放进统一 3D 小格子：

```text
voxel = (z, y, x)
z = 高度层，当前每层 500m
y/x = 雷达图按 xy_downsample=4 下采样后的网格坐标
```

它不是把数据变假，而是把零散点组织成后续可重构、可切片、可补盲区的规则结构。
当前必须同时保留两种形态：

1. `voxel grid`：用于三维风场重构、水平/垂直切面、无观测区域构建、
   PINN-proxy refine 和 diffusion-style smoothing。
2. `point table`：用于 strict hold-out、真实风标签、逐点误差数字。

因此不建议取消体素化。后续“预测某一点并和真实风比较”仍然从 `wind_records`
点表抽 hold-out，不会被 voxel 聚合替代。

### Stage3 小批量启动方向

Stage3 现在应该先做“地面中心全量接收层”，不要做飞机间通信。

建议实现方向：

1. 默认输入改为
   `centralized_v1_output/stage2_regenerated/stage2_multimodal_summary.json`。
2. Ground Center 作为逻辑服务器，接收所有 Flight Agents 的观测；
   不做 Air-to-Air 通信，也不做通信距离过滤。
3. 每帧输出 `ground_center_payload`，清楚区分：
   `label_candidates`、`context_observations`、`trajectory_observations`
   和 `motion_observations`。
4. 明确传递或汇总置信度：
   `time_conf` 表示时间新鲜度，观测离目标时刻越近越可信；
   `space_conf=1.0` 表示 Stage2/Stage3 不按 Ground Center 或 reference_center 降权；
   `joint_likelihood = obs_conf * time_conf`。
5. Stage3 不做最终风场重构，只把观测和权重候选整理好交给 Stage4。
   Stage4 再对每个目标 voxel 计算观测距离局地化权重。

### Stage4 / Stage5 后续验证目标

Stage4 负责在 Ground Center 侧重构当前三维风场，并严格做 point eval：

```text
hold-out 只能从 wind_records 抽；
抽出的真实点在融合前必须剔除；
输出 gt_u/gt_v/pred_u/pred_v/u_error/v_error/rmse/mae/bias。
```

Stage5 再在 Stage4 当前风场上做 PINN-proxy / diffusion-style refine，
生成 future wind，并输出飞机关注点或前方 ROI 的未来风场。

最终验证方式应该是：

```text
选飞机关注的一点或区域，
对比真实风、Stage4 当前重构风、Stage5 未来预测风，
给出具体数值误差和切面可视化。
```

### Stage3 小批量 demo 已验证

本轮已经用新的 `stage2_regenerated` 输入跑通两帧 Stage3：

```text
/data/LFT-W02_data/pengxu/centralized_v1_output/stage3_center/stage3_center_summary.json
```

结果：

```text
20260208124800:
  agents = 746
  label_candidates = 114
  context_wind_observations = 1284
  context_motion_observations = 38691
  trajectory_observations = 5175
  motion_observations = 4887
  agent_space_conf_mean = 1.0
  stage3_space_conf_mode = neutral_logical_ground_center

20260211060600:
  agents = 773
  label_candidates = 1
  context_wind_observations = 1079
  context_motion_observations = 38761
  trajectory_observations = 5247
  motion_observations = 4506
  agent_space_conf_mean = 1.0
  stage3_space_conf_mode = neutral_logical_ground_center
```

Stage3 payload 已确认：

```text
all_agents_downlinked = true
no_air_to_air = true
no_comm_distance_filter = true
space_conf = neutral 1.0 in Stage2/Stage3
joint_likelihood = obs_conf * time_conf
```

### 更新后的新窗口第一句话

```text
当前先不要回旧 Stage4 冻结主线。
请先读 workflow/centralized_v1_docs/README.md，
workflow/centralized_v1_docs/stage2_stage3_full_process_explanation.md，
workflow/centralized_v1_docs/stage4_strict_holdout_logic_and_results.md，
workflow/centralized_v1_docs/stage4_14_item_completion_20260526.md，
以及 workflow/centralized_v1_docs/new_window_handover_stage2_stage3.md。
Stage2 regenerated 已经通过数据组织层 gate：
它从 Stage1 clean parquet 和 radar PNG 重新生成 current wind、historical context wind、
trajectory、motion 和 radar/cloud features，并统一投到 31 x 525 x 775 网格。
Stage2 不做风场重构，不做 ROI 裁剪；reference_center 不参与权重，空间局地化推迟到 Stage4 目标 voxel。
Stage3 小批量 demo 已经跑通两帧，输出 ground_center_payload 和 confidence package。
Stage2 full v2 和 Stage3 full v2 minimal 也已经跑完：
/data/LFT-W02_data/pengxu/centralized_v1_output/stage2_full_v2/stage2_multimodal_summary.json
/data/LFT-W02_data/pengxu/centralized_v1_output/stage3_full_v2_8w_minimal/stage3_center_summary.json
新增 quality_conf_diagnostic / density_conf_diagnostic / qc_flags 只是诊断字段，
不参与当前 joint_likelihood，也不默认删数据。
数据来源明确为 clean_wind.parquet、clean_loc.parquet、radar_index.json
和 radar_index.json.radar_path 指向的气象雷达拼图 PNG。
下一步不要直接全量 Stage4；先从 full Stage2/3 抽 100-300 帧做
Stage4 strict validation batch。
当前 200 帧历史比较使用 8 路 metrics-only sensitivity；新 candidate/demo 已验证 12 路：
baseline = gaussian (12,6,2,1), diagnostic_only, proxy, role_conflict_mode=off；
candidate = gaussian/gaspari_cohn + (8,4,2,1)/(12,6,2,1),
diagnostic_weighted, pydda_3dvar_proxy, current_weight_boost=2.0,
context_weight_scale=0.5, role_conflict_mode=current_priority。
命令必须带 --frame-times ""、--sample-count 200、--sample-seed 20260527。
历史 200-frame root 用 --num-workers 8；新 candidate/demo 可用 --num-workers 12。
metrics-only sensitivity 继续带 --progress-interval-seconds 30。
输出比较表目标：
/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_full_v2_validation_200_8w/comparison/stage4_validation_comparison.md
2026-05-27 新增：CMA-RA/CRA40 虚拟径向速度 + 稀疏 Stage4 先验
类 3DVAR 代理路线已经放到独立脚本：
/data/LFT-W02_data/pengxu/stage/centralized_v1/core/centralized_cma_ra_virtual_radial_3dvar.py
九问集中解释入口：
/data/LFT-W02_data/pengxu/workflow/centralized_v1_docs/stage4_20260527_nine_question_summary.md
四个追问集中解释入口：
/data/LFT-W02_data/pengxu/workflow/centralized_v1_docs/stage4_20260527_four_followup_summary.md
样例输出：
/data/LFT-W02_data/pengxu/centralized_v1_output/cma_ra_virtual_radial_3dvar/cma_ra_virtual_radial_3dvar_20260208124800.md
虚拟径向速度模式图：
/data/LFT-W02_data/pengxu/centralized_v1_output/cma_ra_virtual_radial_3dvar/visuals/20260208124800_cma_virtual_radial_pattern.png
训练清单脚本：
/data/LFT-W02_data/pengxu/stage/centralized_v1/core/centralized_training_manifest.py
训练清单输出：
/data/LFT-W02_data/pengxu/centralized_v1_output/training_manifest/centralized_training_manifest.md
注意：CMA 生成的是虚拟径向速度，不是真实 Doppler 径向速度；
这是 class-PyDDA/3DVAR proxy，不是标准雷达 PyDDA。
稀疏飞机点可以做观测拟合和 strict hold-out 评估，但不能单独作为
稠密三维真值；CMA/NWP/再分析只能作为弱背景或伪标签。
Stage4 200 帧新增 12 路 candidate-v2 比较：
/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_full_v2_validation_200_8w/comparison/stage4_validation_comparison_with_timepower15.md
当前最好候选 = gaussian (8,4,2,1), diagnostic_weighted,
pydda_3dvar_proxy, role_conflict=current_priority,
context_time_conf_power=1.5，RMSE ~= 6.031, MAE ~= 5.412；
仍然不是默认 baseline。
Stage4 12 路小 demo 已生成：
/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_current_demo_12w_20260527
```

### 给新窗口的下一步建议

下一步不要回旧 Stage4 冻结主线。  
建议基于新的 Stage2 regenerated 输出继续：

1. 先看 `workflow/centralized_v1_docs/README.md`；
2. 再看 `workflow/centralized_v1_docs/stage2_stage3_full_process_explanation.md`；
3. 再看 `stage2_data_integrity_summary.md`，确认 Stage2 数据完整性；
4. 检查 sparse current wind 帧和 high-speed context/motion QC candidate；
5. 检查 Stage3 输出的
   `stage3_center/stage3_center_summary.json`、每帧 `ground_center_payload`
   和 `stage3_center/reports`；
6. 让 Stage3/Stage4 明确消费
   `context_wind_records/context_motion_records` 的
   `time_conf/space_conf/joint_likelihood`，其中 Stage2/Stage3 的 `space_conf=1.0`；
7. 严格化 Stage4 hold-out：hold-out 只能从 `wind_records` 抽，抽出的当前真实点
   不能参与融合，`context_wind_records` 只能作为历史上下文参与融合；
8. 在 Stage4 对每个目标 voxel 实现 observation-to-target-voxel 空间局地化；
9. 再做 Stage4 point eval 汇总报告，按高度、强弱风、稀疏程度和 top-k 最大误差分析。
10. 生成更多 CMA-RA class-3DVAR proxy 帧后，再基于
    centralized_training_manifest.py 的 train/val/test split 进入
    PINN/proxy 或 diffusion 训练；训练报告必须把 sparse aircraft
    hold-out metrics 和 CMA/NWP background-consistency metrics 分开写。

当前 gate 结论：

```text
Stage2 = 达标，可以作为 all-in observation organization 输入；
Stage3 = 达标，可以作为 Ground Center payload/confidence package 输入；
Stage2 full v2 = 已完成；
Stage3 full v2 minimal = 已完成；
下一步 = Stage4 100-300 帧 strict validation batch；
暂不建议 all-frame Stage4 输出。
CMA-RA class-3DVAR proxy = 已有独立脚本和单帧样例；
PINN/diffusion = 已有训练清单和损失配置，尚未正式训练。
```
