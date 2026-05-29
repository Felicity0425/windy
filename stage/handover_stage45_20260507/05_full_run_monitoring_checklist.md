# 全量运行监控清单

## 这份文档的作用
这份文档用于全量运行时监控：

- 当前运行到哪一阶段
- Stage3 / Stage4 进度是否正常
- 输出文件是否在持续生成
- 是否存在卡死、读错目录、写错目录的风险

适用于当前 `v2` 主线：

- `run_stage34_workflow_v2.sh`
- `stage3_agents_v2.py`
- `stage4_pack_v2.py`

---

## 一、运行前先确认的 6 件事

1. 当前 `RUN_PHASE` 是什么  
2. 当前 `RUN_LABEL_OVERRIDE` 是什么  
3. 当前 `Stage3` 正式输出目录是不是 `stage3_output_v2`  
4. 当前 `Stage4` 正式输出目录是不是 `stage4_output_v2`  
5. 如果是 `stage4_only`，是否显式指定了：
   - `STAGE3_INPUT_DIR_FOR_STAGE4=$BASE_DIR/stage3_output_v2`
6. 如果是 `full_aux_export`，是否显式指定了：
   - `STAGE4_FAST_SOURCE_DIR=$BASE_DIR/stage4_output_v2`

---

## 二、最常用的进度查看命令

## 1. 查看 `Stage4` 当前进度

如果你当前跑的是：

- `RUN_MODE=full`
- `RUN_LABEL_OVERRIDE=full_fast_stage4_frozen_v1`
- `RUN_PHASE=stage4_only`

那么日志目录一般是：

- `/data/LFT-W02_data/pengxu/stage/logs_v2/full_full_fast_stage4_frozen_v1__stage4_only`

日志文件一般是：

- `/data/LFT-W02_data/pengxu/stage/logs_v2/full_full_fast_stage4_frozen_v1__stage4_only/stage4_full_fast_stage4_frozen_v1.log`

推荐综合命令：

```bash
LOG_DIR=/data/LFT-W02_data/pengxu/stage/logs_v2/full_full_fast_stage4_frozen_v1__stage4_only
LOG_FILE=$LOG_DIR/stage4_full_fast_stage4_frozen_v1.log
OUT_DIR=/data/LFT-W02_data/pengxu/stage4_output_v2

echo "=== Stage4 Latest Progress ==="
grep "\[Stage-4\]\[progress\]" "$LOG_FILE" | tail -n 3 || true
echo
echo "=== Stage4 Latest Frames ==="
grep "\[Stage-4\]\[frame\]" "$LOG_FILE" | tail -n 3 || true
echo
echo "=== Stage4 Latest Diag ==="
grep "\[Stage-4\]\[diag\]" "$LOG_FILE" | tail -n 3 || true
echo
echo "=== Stage4 Written NPZ Count ==="
find "$OUT_DIR" -maxdepth 1 -name 'frame_*.npz' | wc -l
```

---

## 2. 查看 `Stage3` 当前进度

如果你当前跑的是：

- `RUN_MODE=full`
- `RUN_LABEL_OVERRIDE=S5_final_fast_full_v1`
- `RUN_PHASE=full_fast_multi_gpu`

日志目录一般是：

- `/data/LFT-W02_data/pengxu/stage/logs_v2/full_S5_final_fast_full_v1__full_fast_multi_gpu`

Stage3 主日志一般是：

- `/data/LFT-W02_data/pengxu/stage/logs_v2/full_S5_final_fast_full_v1__full_fast_multi_gpu/stage3_S5_final_fast_full_v1.log`

推荐综合命令：

```bash
LOG_DIR=/data/LFT-W02_data/pengxu/stage/logs_v2/full_S5_final_fast_full_v1__full_fast_multi_gpu
LOG_FILE=$LOG_DIR/stage3_S5_final_fast_full_v1.log
OUT_DIR=/data/LFT-W02_data/pengxu/stage3_output_v2

echo "=== Stage3 Latest Progress ==="
grep "\[Stage-3\]\[progress\]" "$LOG_FILE" | tail -n 3 || true
echo
echo "=== Stage3 Latest Wind Diag ==="
grep "\[Stage-3\]\[wind\]" "$LOG_FILE" | tail -n 3 || true
echo
echo "=== Stage3 Latest General Diag ==="
grep "\[Stage-3\]\[diag\]" "$LOG_FILE" | tail -n 3 || true
echo
echo "=== Stage3 Summary Exists? ==="
ls -lh "$OUT_DIR/stage3_summary.json" 2>/dev/null || true
echo
echo "=== Stage3 Agent JSON Count ==="
find "$OUT_DIR/agents" -maxdepth 1 -name 'frame_*_agents.json' | wc -l
```

---

## 3. 同时看 Stage3 / Stage4

如果想一起看：

```bash
LOG_DIR=/data/LFT-W02_data/pengxu/stage/logs_v2/full_S5_final_fast_full_v1__full_fast_multi_gpu
S3_LOG=$LOG_DIR/stage3_S5_final_fast_full_v1.log
S4_LOG=$LOG_DIR/stage4_S5_final_fast_full_v1.log

echo "=== Stage3 Progress ==="
grep "\[Stage-3\]\[progress\]" "$S3_LOG" | tail -n 2 || true
echo
echo "=== Stage4 Progress ==="
grep "\[Stage-4\]\[progress\]" "$S4_LOG" | tail -n 2 || true
echo
echo "=== Stage4 Latest Frame ==="
grep "\[Stage-4\]\[frame\]" "$S4_LOG" | tail -n 1 || true
```

---

## 三、如何判断运行是否正常

## Stage3 正常的迹象

- `[Stage-3][progress]` 在持续增长
- `stage3_output_v2/agents/*.json` 数量在增加
- `stage3_summary.json` 最终生成
- CPU 利用率较高是正常现象
- GPU 利用率低是正常现象

## Stage4 正常的迹象

- `[Stage-4][progress]` 在持续增长
- `[Stage-4][frame]` 和 `[Stage-4][diag]` 在持续输出
- `stage4_output_v2/frame_*.npz` 数量在增加
- `recon_conf_mean` / `coverage` 有波动是正常现象
- GPU 有时高、有时低是正常现象，因为不是所有阶段都吃 GPU

---

## 四、如何判断运行可能出问题

## Stage3 可疑信号

- 很长时间没有新的 `[Stage-3][progress]`
- `agents/*.json` 数量不增加
- shard 日志里某一个 worker 长时间不结束
- CPU 打满但日志几乎不推进，可能是 shard 太多 / IO 过载

## Stage4 可疑信号

- 很长时间没有新的 `[Stage-4][frame]`
- `frame_*.npz` 数量停止增长
- `stage4_summary.json` 一直不生成
- 日志中出现：
  - `TypeError`
  - `FileNotFoundError`
  - `Missing Stage-3 summary`
  - `NoneType`

---

## 五、常见问题与解释

## 1. 为什么 `Stage3` GPU 利用率特别低
因为 `stage3_agents_v2.py` 基本是：

- `numpy`
- `polars`
- `json`
- 稀疏图和 agent 构建

它本质是 CPU / IO 主导程序，不是 GPU 程序。

## 2. 为什么 `Stage4` GPU 利用率也不是一直很高
因为 `Stage4` 里只有部分 dense 数值核吃 GPU，其他部分仍然是：

- `polars`
- `numpy`
- `json`
- 稀疏索引与后处理

所以 GPU 波动是正常现象。

## 3. 为什么 `stage4_only` 可能读错 `Stage3` 输入目录
因为默认它可能去读：

- `stage3_output`

而不是：

- `stage3_output_v2`

因此单独跑 `stage4_only` 时建议显式加：

```bash
STAGE3_INPUT_DIR_FOR_STAGE4=$BASE_DIR/stage3_output_v2
```

---

## 六、全量运行时建议盯的文件

推荐优先盯这些：

- `phase_status_<RUN_LABEL>.log`
- `stage3_<RUN_LABEL>.log`
- `stage4_<RUN_LABEL>.log`
- `stage3wind_<RUN_LABEL>.log`
- `stage4summary_<RUN_LABEL>.log`
- `stage4stats_<RUN_LABEL>.log`

如果你当前默认运行链路没开重报告，那看不到：

- `stage4_sparse_metrics_*.log`
- `stage4_outliers_*.log`
- `stage4_npz_fields_*.log`

这是正常的。

---

## 七、新窗口接手时的提醒

- 先确认当前 phase 是什么，再决定该看哪份日志。
- 先确认 `RUN_LABEL_OVERRIDE`，再拼日志文件名。
- 单独跑 `stage4_only` 时，先确认 `STAGE3_INPUT_DIR_FOR_STAGE4`。
- 不要把日志目录误当成正式输出目录。
---

## 补充：查看 Stage4 每一帧平均处理耗时

如果你想知道当前 `Stage4` 平均每帧花了多久，可以用：

```bash
LOG_DIR=/data/LFT-W02_data/pengxu/stage/logs_v2/full_full_fast_stage4_frozen_v1__stage4_only
LOG_FILE=$(ls "$LOG_DIR"/stage4*.log | head -n 1)

echo "=== Stage4 Latest Progress Line ==="
grep "\[Stage-4\]\[progress\]" "$LOG_FILE" | tail -n 1 || true
echo
echo "=== Stage4 Latest 10 Frames ==="
grep "\[Stage-4\]\[frame\]" "$LOG_FILE" | tail -n 10 || true
echo
echo "=== Stage4 Average Time Per Frame (rough) ==="
python - <<'PY' "$LOG_FILE"
import re
import sys
from pathlib import Path

log_file = Path(sys.argv[1])
text = log_file.read_text(encoding="utf-8", errors="ignore")
lines = [x for x in text.splitlines() if "[Stage-4][progress]" in x]
if not lines:
    print("No progress lines found.")
    raise SystemExit(0)
last = lines[-1]
m_done = re.search(r"\]\s+(\d+)/(\d+)\s+\(", last)
m_elapsed = re.search(r"elapsed=([0-9hms]+)", last)
if not (m_done and m_elapsed):
    print("Failed to parse latest progress line.")
    print(last)
    raise SystemExit(0)
done = int(m_done.group(1))
elapsed_txt = m_elapsed.group(1)

def parse_duration(s: str) -> float:
    total = 0.0
    m = re.search(r"(\d+)h", s)
    if m:
        total += int(m.group(1)) * 3600
    m = re.search(r"(\d+)m", s)
    if m:
        total += int(m.group(1)) * 60
    m = re.search(r"(\d+)s", s)
    if m:
        total += int(m.group(1))
    return total

elapsed_sec = parse_duration(elapsed_txt)
if done > 0 and elapsed_sec > 0:
    print(f"done_frames={done}")
    print(f"elapsed_sec={elapsed_sec:.1f}")
    print(f"avg_sec_per_frame={elapsed_sec / done:.3f}")
    print(f"fps={done / elapsed_sec:.5f}")
else:
    print("Not enough information.")
PY
```

用途：
- 粗略估计当前全量运行的平均每帧耗时
- 判断 `Stage4` 是否明显变慢

说明：
- 这是平均耗时，不是逐帧精确耗时
- 如果以后要做论文里的逐帧耗时图，建议后续单独增加更细粒度日志

---

## 补充：查看 Stage4 最近 N 帧的逐帧耗时近似值

如果你想更接近“逐帧耗时”，可以利用日志里连续 `[Stage-4][frame]` 的时间戳差来估计最近 N 帧的处理间隔：

```bash
LOG_DIR=/data/LFT-W02_data/pengxu/stage/logs_v2/full_full_fast_stage4_frozen_v1__stage4_only
LOG_FILE=$(ls "$LOG_DIR"/stage4*.log | head -n 1)

python - <<'PY' "$LOG_FILE"
import re
import sys
from datetime import datetime
from pathlib import Path

log_file = Path(sys.argv[1])
text = log_file.read_text(encoding="utf-8", errors="ignore").splitlines()

rows = []
for line in text:
    if "[Stage-4][frame]" not in line:
        continue
    m = re.search(r"time=(\d{14})", line)
    if not m:
        continue
    ts = datetime.now()  # placeholder if wall clock not embedded
    rows.append((line, m.group(1)))

print("=== Latest Stage4 Frame Lines ===")
for line, tstr in rows[-10:]:
    print(line)

print()
print("=== Note ===")
print("当前日志没有记录每帧 wall-clock 时间戳，因此无法从日志严格恢复逐帧真实耗时。")
print("建议仍以 progress 行中的 avg_sec_per_frame 为主。")
print("如果后续确实需要论文级逐帧耗时图，应在 Stage4 日志中显式加入每帧 wall-clock 时间。")
PY
```

用途：
- 说明当前日志结构下，无法严格恢复逐帧真实耗时
- 提醒后续如果真要做论文图，需要单独加时间戳日志
## 补充：为什么 Stage4 多核 CPU 通常会更快

`Stage4` 的热点并不全在 GPU，上游和后处理里有大量：

- `polars`
- `numpy`
- `BLAS`
- 稀疏索引与后处理

因此：

- `Stage4_CPU_THREADS=6` 往往比 `1` 更快
- 但不会线性 6 倍提速
- 如果线程开太高，也可能因为调度和 IO 压力变慢

建议：

- 默认先用 `STAGE4_CPU_THREADS=6`
- 需要对比时，再跑：
  - `STAGE4_CPU_THREADS=1`
  - `STAGE4_CPU_THREADS=6`

并检查日志里是否已经打印：

- `omp_threads`
- `mkl_threads`
- `numexpr_threads`
- `polars_threads`
