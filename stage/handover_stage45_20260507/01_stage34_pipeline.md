# Stage3 / Stage4 输入输出目录与调用关系

## 这份文档的作用
这份文档专门解释：

- 现在脚本实际调用的是哪份代码
- `Stage3` / `Stage4` 的输入输出目录到底是什么
- `stage3_output` 和 `stage3_output_v2` 有什么区别
- `stage4_only`、`full_fast_multi_gpu`、`full_aux_export` 分别怎么跑

如果你之前觉得“原版和 v2 混在一起看不懂”，先看这份。

---

## 当前脚本实际使用的代码

当前主控脚本：

- `run_stage34_workflow_v2.sh`

它实际调用的是：

- `Stage3`：`stage3_agents_v2.py`
- `Stage4`：`stage4_pack_v2.py`

它**不使用**老版：

- `stage3_agents.py`
- `stage4_pack.py`

也就是说：

- 调试和运行都以 `v2` 版本为准

---

## 关键目录变量及默认值

脚本中的关键目录变量如下。

### Stage2 输入
- `STAGE2_OUTPUT_DIR`
- 默认：
  - `$BASE_DIR/stage2_output`

内容：
- `stage2_summary.json`
- `frame 对应的 voxel npz`

### Stage3 正式输出目录
- `STAGE3_OUTPUT_DIR_V2`
- 默认：
  - `$BASE_DIR/stage3_output_v2`

内容：
- `stage3_summary.json`
- `agents/*.json`

### Stage3 旧默认输入目录
- `STAGE3_INPUT_DIR_ORIG`
- 默认：
  - `$BASE_DIR/stage3_output`

说明：
- 这是旧目录
- `stage4_only` 如果不显式指定输入目录，可能会默认读这里

### Stage4 正式输出目录
- `STAGE4_OUTPUT_DIR`
- 默认：
  - `$BASE_DIR/stage4_output_v2`

内容：
- `stage4_summary.json`
- `frame_*.npz`

### Stage4 当前 run 子集目录
- `STAGE4_RUN_ROOT`
- 默认：
  - `$BASE_DIR/stage4_output_runs_v2`

通常会形成：
- `$BASE_DIR/stage4_output_runs_v2/<RUN_LABEL>`

### Stage4 full aux 导出目录
- `STAGE4_FULL_AUX_OUTPUT_ROOT`
- 默认：
  - `$BASE_DIR/stage4_output_full_aux_v2`

通常会形成：
- `$BASE_DIR/stage4_output_full_aux_v2/<RUN_LABEL>`

### Stage4 fast 源目录
- `STAGE4_FAST_SOURCE_DIR`
- 默认：
  - 跟 `STAGE4_OUTPUT_DIR` 相同

主要用于：
- `full_aux_export` 从 fast 输出读源结果

---

## 四种典型调用链

## 1. `RUN_PHASE=stage3_only`

### 调用
- `run_stage3_script()`
- 实际执行：
  - `python stage3_agents_v2.py`

### 输入
- `STAGE2_OUTPUT_DIR/stage2_summary.json`
- `stage2_output/*.npz`

### 正式输出目录
- `STAGE3_OUTPUT_DIR_V2`
- 默认：
  - `$BASE_DIR/stage3_output_v2`

### 日志目录
- `$LOG_ROOT_DIR/<run_mode>_<run_label>__stage3_only`

---

## 2. `RUN_PHASE=stage4_only`

### 调用
- `run_stage4_script()`
- 实际执行：
  - `python stage4_pack_v2.py`

### 输入
- `Stage2`：
  - `STAGE2_OUTPUT_DIR`
- `Stage3`：
  - `ACTIVE_STAGE3_DIR`

而 `ACTIVE_STAGE3_DIR` 的逻辑是：

- 如果本次 phase 包含 `stage3`
  - 用 `STAGE3_OUTPUT_DIR_V2`
- 否则
  - 用 `${STAGE3_INPUT_DIR_FOR_STAGE4:-$STAGE3_INPUT_DIR_ORIG}`

### 重点
如果你单独跑 `stage4_only`，而且**没有指定**：

```bash
STAGE3_INPUT_DIR_FOR_STAGE4=$BASE_DIR/stage3_output_v2
```

那么它默认可能会读：

- `$BASE_DIR/stage3_output`

而不是：

- `$BASE_DIR/stage3_output_v2`

### 正式输出目录
- `STAGE4_OUTPUT_DIR`
- 默认：
  - `$BASE_DIR/stage4_output_v2`

### 日志目录
- `$LOG_ROOT_DIR/<run_mode>_<run_label>__stage4_only`

---

## 3. `RUN_PHASE=full_fast_multi_gpu`

这是当前最重要的运行链路。

### 调用
- `run_full_fast_multi_gpu()`

### Stage3 流程
第一步：
- 把要处理的 frame indices 切成若干 shard

第二步：
- 每个 shard 跑：
  - `python stage3_agents_v2.py`

中间输出目录：
- `$BASE_DIR/stage_shard_runs/<RUN_LABEL>/stage3/shard_*`

第三步：
- 调用 `merge_stage3_shards()`
- 合并到正式目录：
  - `STAGE3_OUTPUT_DIR_V2`
  - 即：
  - `$BASE_DIR/stage3_output_v2`

### Stage4 流程
默认：
- `MULTI_GPU_STAGE4_SHARD=0`

此时：
- `Stage4` 是单进程单卡
- 输入显式设为：
  - `WIND_STAGE3_INPUT_DIR=$STAGE3_OUTPUT_DIR_V2`
- 所以它一定吃：
  - `$BASE_DIR/stage3_output_v2`

### 正式输出目录
- `STAGE4_OUTPUT_DIR`
- 默认：
  - `$BASE_DIR/stage4_output_v2`

### 日志目录
- `$LOG_ROOT_DIR/<run_mode>_<run_label>__full_fast_multi_gpu`

### 重要结论
这条链路下：

- `Stage3` 正式输出一定是 `stage3_output_v2`
- `Stage4` 输入也一定是 `stage3_output_v2`

---

## 4. `RUN_PHASE=full_aux_export`

### 调用
- `run_stage4_script()`
- 实际执行：
  - `python stage4_pack_v2.py`

### 它不是重新做主重构
而是：

- 从已有 fast 输出读取：
  - `stage4_summary.json`
  - `frame_*.npz`
- 补完整辅助场

### 输入来源
- `STAGE4_FAST_SOURCE_DIR`
- 通过：
  - `WIND_STAGE4_AUX_SOURCE_DIR`

### 正式输出目录
- `STAGE4_OUTPUT_DIR`
- 在这条 phase 下会被改成：
  - `STAGE4_FULL_AUX_OUTPUT_ROOT/<RUN_LABEL>`

默认就是：
- `$BASE_DIR/stage4_output_full_aux_v2/<RUN_LABEL>`

### 日志目录
- `$LOG_ROOT_DIR/<run_mode>_<run_label>__full_aux_export`

---

## `stage3_output` vs `stage3_output_v2`

### `stage3_output`
- 旧默认输入目录
- 来自老逻辑或旧历史运行
- `stage4_only` 在不显式指定输入目录时可能会读它

### `stage3_output_v2`
- 当前 `v2` 正式输出目录
- `stage3_agents_v2.py` 的目标输出
- `full_fast_multi_gpu` 合并后的正式目录
- 推荐所有 `Stage4` 都显式吃这个目录

### 实际建议
以后只要单独跑 `stage4_only`，都建议显式加：

```bash
STAGE3_INPUT_DIR_FOR_STAGE4=$BASE_DIR/stage3_output_v2
```

---

## `stage4_output_v2` / `stage4_output_runs_v2` / `stage4_output_full_aux_v2`

### `stage4_output_v2`
- `Stage4` 正式输出目录
- 主重构结果都在这里
- 包含：
  - `stage4_summary.json`
  - `frame_*.npz`

### `stage4_output_runs_v2`
- 当前 run 的子集复制目录
- 用于避免 export 混入历史结果
- 一般形式：
  - `$BASE_DIR/stage4_output_runs_v2/<RUN_LABEL>`

### `stage4_output_full_aux_v2`
- full aux 导出目录
- 用于训练前 richer aux fields
- 一般形式：
  - `$BASE_DIR/stage4_output_full_aux_v2/<RUN_LABEL>`

---

## Stage3 多进程分片 -> merge -> `stage3_output_v2`

文字版：

```text
stage2_output/
  ├─ stage2_summary.json
  └─ frame_stage2_*.npz
        ↓
run_full_fast_multi_gpu()
        ↓
stage_shard_runs/<RUN_LABEL>/stage3/shard_*/
  ├─ stage3_summary.json
  └─ agents/*.json
        ↓ merge_stage3_shards()
stage3_output_v2/
  ├─ stage3_summary.json
  └─ agents/*.json
```

---

## Stage4 单进程单卡 -> `stage4_output_v2`

文字版：

```text
stage2_output/
  ├─ stage2_summary.json
  └─ frame_stage2_*.npz

stage3_output_v2/
  ├─ stage3_summary.json
  └─ agents/*.json
        ↓
stage4_pack_v2.py
        ↓
stage4_output_v2/
  ├─ stage4_summary.json
  └─ frame_stage4_*.npz
```

---

## 一页文字版关系图

```text
stage2_output
  ├─ stage2_summary.json
  └─ frame_stage2_*.npz
        ↓
stage3_agents_v2.py
        ↓
stage3_output_v2
  ├─ stage3_summary.json
  └─ agents/*.json
        ↓
stage4_pack_v2.py (fast)
        ↓
stage4_output_v2
  ├─ stage4_summary.json
  └─ frame_stage4_*.npz
        ↓
stage4_pack_v2.py (full_aux_export)
        ↓
stage4_output_full_aux_v2/<RUN_LABEL>
  ├─ stage4_summary.json
  └─ frame_stage4_*.npz
```

---

## 常见误区

### 1. 日志目录不是正式数据输出目录
例如：

- `stage/logs_v2/full_S5_final_fast_full_v1__full_fast_multi_gpu`

这里放的是日志，不是正式结果数据。

正式数据输出在：

- `stage3_output_v2`
- `stage4_output_v2`
- `stage4_output_full_aux_v2`

### 2. `full_aux_export` 不会跑 `Stage3`
它只做：

- `Stage4 + summary + validate + collect + readiness`

### 3. `stage4_only` 默认可能读到旧的 `stage3_output`
除非你显式指定：

```bash
STAGE3_INPUT_DIR_FOR_STAGE4=$BASE_DIR/stage3_output_v2
```

### 4. `Stage4` 单进程 + 多线程 CPU 不等于 `Stage4` 多进程分片
前者：
- 不切断时序链
- 只是提高 CPU 利用率

后者：
- 会破坏 `prev_recon_state`
- 不适合作为默认主链

---

## 新窗口接手时的提醒

- 看 `Stage4` 输入目录时，不要只看日志目录，要看 `ACTIVE_STAGE3_DIR` 的来源。
- 如果要单独重跑 `Stage4`，优先显式指定：
  - `STAGE3_INPUT_DIR_FOR_STAGE4=$BASE_DIR/stage3_output_v2`
- 如果跑的是 `full_aux_export`，要确认它读取的是：
  - `STAGE4_FAST_SOURCE_DIR`
  而不是重新跑主重构。
