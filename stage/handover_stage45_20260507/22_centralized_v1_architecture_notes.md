# centralized_v1 中心化地空风云联合重构原型说明

## 这份文档的作用

这份文档记录一条与当前 `Stage1-Stage5` 主线并行存在的新原型链路：

```text
centralized_v1
```

它对应的研究假设是：

```text
先不考虑飞机之间的真实物理通信限制，
假设所有飞机观测都能完整回传到地面中心，
由地面中心统一完成风场重构、盲区构建、物理精炼、云图预测和定向下发。
```

这条链路当前是：

- 新实验架构原型
- 不替代现有 Stage4 冻结主链
- 但已经能跑通最小 demo

当前讨论边界再明确一条：

```text
云图强耦合预测先暂时下放到 Stage6 讨论，
当前 centralized_v1 先聚焦 Stage1-Stage5 的中心化风场重构、点预测误差、未来风场生成与定向下发。
```

---

## 一、当前目录结构

代码目录：

```text
/data/LFT-W02_data/pengxu/stage/centralized_v1
```

主要包括：

- `configs/`
- `core/`
- `logs/`

输出目录：

```text
/data/LFT-W02_data/pengxu/centralized_v1_output
```

当前输出分层：

- `stage2_multimodal`
- `stage3_center`
- `stage4_center`
- `stage5_center`

---

## 二、当前已实现的模块

### 1. centralized Stage2

脚本：

- [centralized_stage2_multimodal.py](/data/LFT-W02_data/pengxu/stage/centralized_v1/core/centralized_stage2_multimodal.py)

当前实现：

- 从现有 `stage2_output/voxels/frame_*.npz` 读取原始体素
- 做更粗的 XY 下采样
- 构造：
  - `cloud_2d`
  - `cloud_feature_records`
  - `multimodal_meta_json`
- 输出到：

```text
/data/LFT-W02_data/pengxu/centralized_v1_output/stage2_multimodal
```

当前两帧示例：

- `20260129114200`
- `20260206174200`

### 2. centralized Stage3

脚本：

- [centralized_stage3_center.py](/data/LFT-W02_data/pengxu/stage/centralized_v1/core/centralized_stage3_center.py)

当前实现：

- 不再以 air-to-air graph 作为主结果
- 所有 agent 都指向 ground center
- 输出：
  - `agent_delta_time_minutes`
  - `agent_distance_to_roi_km`
  - `agent_time_conf`
  - `agent_space_conf`
  - `agent_joint_conf`

输出目录：

```text
/data/LFT-W02_data/pengxu/centralized_v1_output/stage3_center
```

当前两帧结果：

- `20260129114200`：`center_agent_count=634`
- `20260206174200`：`center_agent_count=221`

### 3. centralized Stage4

脚本：

- [centralized_stage4_ground_recon.py](/data/LFT-W02_data/pengxu/stage/centralized_v1/core/centralized_stage4_ground_recon.py)

当前实现：

- 使用 `Stage2` 多模态体素和 `Stage3` 的时空置信度
- 做地面中心加权融合
- 做轻量 blind-zone 初步构建
- 输出 point-level holdout 日志

输出目录：

```text
/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_center
```

当前两帧结果摘要：

- `blindzone_initialized_voxels`
- `point_eval_rmse`
- `cloud_feature_count`

并输出：

- `frame_<time>_center.npz`
- `point_eval_<time>.json`
- `stage4_center_summary.json`

### 4. centralized Stage5

脚本：

- [centralized_stage5_wind_cloud.py](/data/LFT-W02_data/pengxu/stage/centralized_v1/core/centralized_stage5_wind_cloud.py)

当前实现：

- PINN-proxy 风场精炼
- diffusion-style 风场平滑
- 未来风场生成
- 生成简单的 downlink ROI 包
- 保留最小 future cloud demo，但当前不把它当主目标

输出目录：

```text
/data/LFT-W02_data/pengxu/centralized_v1_output/stage5_center
```

当前输出包括：

- `frame_<time>_wind_cloud_demo.npz`
- `stage5_center_summary.json`

当前 summary 中已经包含：

- `future_wind_generated`
- `future_cloud_generated`
- `cloud_forwarding_enabled`
- `downlink_roi_count`
- `pinn_loss_divergence_proxy`
- `pinn_loss_smoothness_proxy`

---

## 三、当前最小 demo 已经跑通的事实

统一 runner：

- [run_centralized_v1_demo.py](/data/LFT-W02_data/pengxu/stage/centralized_v1/run_centralized_v1_demo.py)

日志目录：

```text
/data/LFT-W02_data/pengxu/stage/centralized_v1/logs
```

当前已经成功生成：

- `stage2_multimodal.log`
- `stage3_center.log`
- `stage4_center.log`
- `stage5_center.log`

也就是说，这条 `centralized_v1` 最小链路已经从：

```text
Stage2 -> Stage3 -> Stage4 -> Stage5
```

完整打通。

---

## 四、当前已经满足的需求点

### 已满足

1. `Stage1` 不改
2. `Stage2` 已支持粗网格 + 云图 2D 特征打包
3. `Stage3` 已改成地面中心星型拓扑
4. `Stage3` 已输出时间置信度、空间置信度、联合置信度
5. `Stage4` 已做地面中心加权融合
6. `Stage4` 已做 blind-zone 初步构建
7. `Stage4` 已输出逐点 holdout 误差日志
8. `Stage5` 已接上 PINN/Diffusion-like refine
9. `Stage5` 已能生成未来风场并做定向下行 ROI 包
10. `Stage5` 保留了最小 future cloud demo，但当前不是主目标
11. 已新增切面图脚本，能看不同高度层和垂直剖面

### 还只是最小 demo

1. 云图特征目前还是 2D patch 统计，不是完整 3D 云体建模
2. Blind-zone 初始化还是轻量版本，不是最终物理最优方案
3. Stage5 里的 diffusion 还不是训练好的生成模型
4. future cloud 目前只是保留的最小演示，更适合后续作为 Stage6 议题
5. 当前 Stage5 主目标应理解为“未来风场生成 + 定向下发”
6. 下行通知只是裁片输出，不是真正通信仿真

---

## 五、时空置信度的当前含义

当前 `Stage3` 已显式定义：

```text
C_time = exp(-alpha * delta_time_minutes)
C_space = exp(-beta * distance_km)
C_joint = C_time * C_space
```

物理含义是：

1. 时间越近，置信度越高
2. 空间越近，置信度越高
3. 两者共同决定该 agent 对地面中心重构的权重

它对应的是你提出的核心思想：

```text
历史数据也可以用，但必须按“距离当前有多远、离当前区域有多远”衰减权重
```

---

## 六、切面可视化

新增脚本：

- [centralized_report_stage4_slices.py](/data/LFT-W02_data/pengxu/stage/centralized_v1/core/centralized_report_stage4_slices.py)

当前已成功生成一张切面图：

- [20260206174200_centralized_stage4_slices.png](/data/LFT-W02_data/pengxu/centralized_v1_output/stage4_center/slices/20260206174200_centralized_stage4_slices.png)

这张图当前已经满足：

1. 水平切面
2. 垂直剖面
3. 标出 `z level` 与近似高度
4. 云图 2D 底图联合显示

因此它已经符合你提的：

```text
切面看，标具体高度维度等，从不同切面和方向来看
```

这一条需求。

---

## 七、当前保守结论

这条 `centralized_v1` 原型当前应该怎么表述：

```text
它已经不是单纯想法，而是一条最小可运行的新架构原型。
```

但它还不是：

- 最终论文版本
- 最优物理重构版本
- 真正训练完成的 PINN / Diffusion 系统

更准确的口径是：

```text
centralized_v1 已经把“地空中心化、多模态风云耦合、风驱云预测、定向下发”这套逻辑跑成了最小 demo。
```

---

## 八、下一步最值得继续做的事

1. 把 `Stage4` 的 point eval 日志再做成聚合 summary 和示例展示
2. 把 `Stage5` 的 future cloud demo 升级为多步预测而不是单步平移
3. 给 `centralized_v1` 单独做一份结果可视化总入口
4. 如果要继续论文化，再把：
   - cloud feature 设计
   - blind-zone 构建
   - PINN/Diffusion 条件输入
   做得更系统
