# Stage4 结果记录表模板

## 这份文档的作用
这是一份**实验结果填写模板**。  
用途是：

- 每跑完一个 `Stage4` 实验版本，就把结果填进来
- 避免结果散落在日志、命令历史和临时笔记里
- 后续写论文表格时可以直接复制

建议配合下面两份文档一起使用：

- `03_stage4_paper_experiment_matrix.md`
- `07_full_command_catalog.md`

---

## 使用规则

每跑完一个实验，至少记录以下内容：

1. 本次实验的版本名
2. 运行命令
3. 输出目录
4. 日志目录
5. 主指标
6. 备注和异常

建议不要等所有实验跑完再统一填写。  
最稳妥的是：**每跑完一版就立即补一行。**

---

## 一、实验元信息

| 项目 | 内容 |
|---|---|
| 日期 |  |
| 数据集范围 | 例如：全量 7395 帧 / offset 子集 / topwind 子集 |
| 运行机器 |  |
| GPU |  |
| CPU |  |
| Stage3 并行设置 | 例如：`STAGE3_PARALLEL_SHARDS=8`, `STAGE3_CPU_THREADS_PER_WORKER=1` |
| Stage4 设置 | 例如：`single-gpu + 6 CPU threads` |
| 正式主版本 | 例如：`S5 FinalFast` |
| 训练导出版本 | 例如：`S6 FullAux` |

---

## 二、运行命令记录

| 版本 | RUN_LABEL_OVERRIDE | RUN_PHASE | 命令摘要 | Stage3 输入目录 | Stage4 输出目录 | 日志目录 |
|---|---|---|---|---|---|---|
| S0 |  |  |  |  |  |  |
| S1 |  |  |  |  |  |  |
| S2 |  |  |  |  |  |  |
| S3 |  |  |  |  |  |  |
| S4 |  |  |  |  |  |  |
| S5 |  |  |  |  |  |  |
| S6 |  |  |  |  |  |  |

说明：

- `命令摘要` 不需要粘完整命令，写关键开关即可
- 完整命令在 `07_full_command_catalog.md` 里查

---

## 三、主结果表

这是最接近论文主表的一张。

| Version | Vector RMSE | Corr(u/v) | Outlier Count | Recon Conf Mean | Recon Coverage | Conf Spread | Elapsed |
|---|---:|---:|---:|---:|---:|---:|---:|
| S0 DirectOnly |  |  |  |  |  |  |  |
| S1 BaseRecon |  |  |  |  |  |  |  |
| S2 SupportTemporal |  |  |  |  |  |  |  |
| S3 PhysicsSmooth |  |  |  |  |  |  |  |
| S4 ConfPruneAnchor |  |  |  |  |  |  |  |
| S5 FinalFast |  |  |  |  |  |  |  |
| S6 FullAux |  |  |  |  |  |  |  |

字段来源建议：

- `Vector RMSE / Corr / Outlier Count`
  - 来自 `report_stage4_sparse_metrics.py`
- `Recon Conf Mean / Recon Coverage / Conf Spread`
  - 来自 `stage4_summary.json` 或 `stage4summary_*.log`
- `Elapsed`
  - 来自 `stage4_*.log`

---

## 四、模块贡献表

这张表用来写消融。

| Version | Support Fill | Temporal Fill | Relax | Prune | Expand | Anchor Protect | Coverage | Conf Mean |
|---|---|---|---|---|---|---|---:|---:|
| S1 BaseRecon | off | off | off | off | off | off |  |  |
| S2 SupportTemporal | on | on | off | off | off | off |  |  |
| S3 PhysicsSmooth | on | on | on | off | off | off |  |  |
| S4 ConfPruneAnchor | on | on | on | on | off | on |  |  |
| S5 FinalFast | on | on | on | on | on | on |  |  |
| S6 FullAux | on | on | on | on | on | on |  |  |

说明：

- 这张表适合直接放进论文消融章节

---

## 五、结构性指标表

这张表用于解释为什么某个版本更好或更稳。

| Version | Support Fill Voxels | Temporal Fill Voxels | Support Expand Voxels | Anchor Restore | Anchor Force | Direct Agreement | Physics Weight | Source Diversity |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| S1 BaseRecon |  |  |  |  |  |  |  |  |
| S2 SupportTemporal |  |  |  |  |  |  |  |  |
| S3 PhysicsSmooth |  |  |  |  |  |  |  |  |
| S4 ConfPruneAnchor |  |  |  |  |  |  |  |  |
| S5 FinalFast |  |  |  |  |  |  |  |  |
| S6 FullAux |  |  |  |  |  |  |  |  |

字段来源建议：

- 主要来自 `stage4_summary.json`

---

## 六、运行性记录表

这张表用于记录工程可运行性。

| Version | Stage3 Policy | Stage4 Policy | CPU Threads | GPU | Progress Stable? | Summary Generated? | NPZ Growing? | Notes |
|---|---|---|---:|---|---|---|---|---|
| S0 |  |  |  |  |  |  |  |  |
| S1 |  |  |  |  |  |  |  |  |
| S2 |  |  |  |  |  |  |  |  |
| S3 |  |  |  |  |  |  |  |  |
| S4 |  |  |  |  |  |  |  |  |
| S5 |  |  |  |  |  |  |  |  |
| S6 |  |  |  |  |  |  |  |  |

推荐填写说明：

- `Stage3 Policy`
  - 例如：`sharded(8) x cpu_threads=1`
- `Stage4 Policy`
  - 例如：`single-gpu-serial + cpu_threads=6`
- `Progress Stable?`
  - yes / no
- `Summary Generated?`
  - yes / no
- `NPZ Growing?`
  - yes / no

---

## 七、Fast vs FullAux 对比表

这张表单独留给 `S5` 和 `S6`。

| Version | Output Profile | Recon Changed? | Aux Fields Complete | Coverage | Conf Mean | Elapsed | 说明 |
|---|---|---|---|---:|---:|---:|---|
| S5 FinalFast | fast | no | partial |  |  |  |  |
| S6 FullAux | full_aux_export | no | yes |  |  |  |  |

---

## 八、按实验逐条记录

如果你不想只填表，也可以每个实验单独补一段记录。

---

### Experiment: S0 DirectOnly

**日期**  

**命令**  

**日志目录**  

**输出目录**  

**主结果**  
- Vector RMSE:
- Corr:
- Outlier Count:
- Recon Conf Mean:
- Recon Coverage:
- Conf Spread:
- Elapsed:

**观察**  

**结论**  

---

### Experiment: S1 BaseRecon

**日期**  

**命令**  

**日志目录**  

**输出目录**  

**主结果**  
- Vector RMSE:
- Corr:
- Outlier Count:
- Recon Conf Mean:
- Recon Coverage:
- Conf Spread:
- Elapsed:

**观察**  

**结论**  

---

### Experiment: S2 SupportTemporal

**日期**  

**命令**  

**日志目录**  

**输出目录**  

**主结果**  
- Vector RMSE:
- Corr:
- Outlier Count:
- Recon Conf Mean:
- Recon Coverage:
- Conf Spread:
- Elapsed:

**观察**  

**结论**  

---

### Experiment: S3 PhysicsSmooth

**日期**  

**命令**  

**日志目录**  

**输出目录**  

**主结果**  
- Vector RMSE:
- Corr:
- Outlier Count:
- Recon Conf Mean:
- Recon Coverage:
- Conf Spread:
- Elapsed:

**观察**  

**结论**  

---

### Experiment: S4 ConfPruneAnchor

**日期**  

**命令**  

**日志目录**  

**输出目录**  

**主结果**  
- Vector RMSE:
- Corr:
- Outlier Count:
- Recon Conf Mean:
- Recon Coverage:
- Conf Spread:
- Elapsed:

**观察**  

**结论**  

---

### Experiment: S5 FinalFast

**日期**  

**命令**  

**日志目录**  

**输出目录**  

**主结果**  
- Vector RMSE:
- Corr:
- Outlier Count:
- Recon Conf Mean:
- Recon Coverage:
- Conf Spread:
- Elapsed:

**观察**  

**结论**  

---

### Experiment: S6 FullAux

**日期**  

**命令**  

**日志目录**  

**输出目录**  

**主结果**  
- Vector RMSE:
- Corr:
- Outlier Count:
- Recon Conf Mean:
- Recon Coverage:
- Conf Spread:
- Elapsed:

**观察**  

**结论**  

---

## 九、填写建议

### 如果你时间紧
至少填：

- 主结果表
- Fast vs FullAux 表
- S5 / S6 单条记录

### 如果你准备写论文
建议全部填：

- 主结果表
- 模块贡献表
- 结构性指标表
- 运行性记录表
- 每个实验的单条记录

---

## 十、新窗口接手时的提醒

- 这份文件是“跑完实验之后填”的，不是命令手册。
- 命令去 `07_full_command_catalog.md` 查。
- 指标定义去 `03_stage4_paper_experiment_matrix.md` 查。
