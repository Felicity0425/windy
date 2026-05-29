# 服务器上最常用的 10 条监控命令速查表

## 这份文档的作用
这是一页速查表，用于你在服务器上全量跑 `Stage3/Stage4` 时快速查看：

- 现在跑到哪一步
- 当前 Stage3 / Stage4 的进度
- 写了多少输出文件
- 当前日志文件名到底是什么
- 是否卡住

下面的命令默认你已经在服务器 shell 里。

---

## 1. 看当前 run 的目录里都有什么日志

```bash
LOG_DIR=/data/LFT-W02_data/pengxu/stage/logs_v2/full_S5_final_fast_full_v1__full_fast_multi_gpu
ls -lh "$LOG_DIR"
```

用途：
- 先确认这次 run 实际生成了哪些日志文件

---

## 2. 找 Stage3 主日志文件

```bash
LOG_DIR=/data/LFT-W02_data/pengxu/stage/logs_v2/full_S5_final_fast_full_v1__full_fast_multi_gpu
ls "$LOG_DIR"/stage3*.log
```

用途：
- 确认 `Stage3` 主日志真实文件名

---

## 3. 找 Stage4 主日志文件

```bash
LOG_DIR=/data/LFT-W02_data/pengxu/stage/logs_v2/full_full_fast_stage4_frozen_v1__stage4_only
ls "$LOG_DIR"/stage4*.log
```

用途：
- 确认 `Stage4` 主日志真实文件名

---

## 4. 看 Stage3 最近 3 条进度

```bash
LOG_DIR=/data/LFT-W02_data/pengxu/stage/logs_v2/full_S5_final_fast_full_v1__full_fast_multi_gpu
LOG_FILE=$(ls "$LOG_DIR"/stage3*.log | head -n 1)
grep "\[Stage-3\]\[progress\]" "$LOG_FILE" | tail -n 3
```

用途：
- 直接看 `Stage3` 当前推进到多少帧

---

## 5. 看 Stage4 最近 3 条进度

```bash
LOG_DIR=/data/LFT-W02_data/pengxu/stage/logs_v2/full_full_fast_stage4_frozen_v1__stage4_only
LOG_FILE=$(ls "$LOG_DIR"/stage4*.log | head -n 1)
grep "\[Stage-4\]\[progress\]" "$LOG_FILE" | tail -n 3
```

用途：
- 直接看 `Stage4` 当前推进到多少帧

---

## 6. 看 Stage4 最近 3 条 frame 结果

```bash
LOG_DIR=/data/LFT-W02_data/pengxu/stage/logs_v2/full_full_fast_stage4_frozen_v1__stage4_only
LOG_FILE=$(ls "$LOG_DIR"/stage4*.log | head -n 1)
grep "\[Stage-4\]\[frame\]" "$LOG_FILE" | tail -n 3
```

用途：
- 看最近几帧的 `coverage / conf_mean / support_fill / temporal_fill`

---

## 7. 看 Stage4 最近 3 条 diag 结果

```bash
LOG_DIR=/data/LFT-W02_data/pengxu/stage/logs_v2/full_full_fast_stage4_frozen_v1__stage4_only
LOG_FILE=$(ls "$LOG_DIR"/stage4*.log | head -n 1)
grep "\[Stage-4\]\[diag\]" "$LOG_FILE" | tail -n 3
```

用途：
- 看 `wind_primary / support_fill / support_expand / anchor_restore / pruned`

---

## 8. 看 Stage3 正式输出已经写了多少 agent 文件

```bash
OUT_DIR=/data/LFT-W02_data/pengxu/stage3_output_v2
find "$OUT_DIR/agents" -maxdepth 1 -name 'frame_*_agents.json' | wc -l
```

用途：
- 粗略估计 `Stage3` 已完成多少帧

---

## 9. 看 Stage4 正式输出已经写了多少 npz 文件

```bash
OUT_DIR=/data/LFT-W02_data/pengxu/stage4_output_v2
find "$OUT_DIR" -maxdepth 1 -name 'frame_*.npz' | wc -l
```

用途：
- 粗略估计 `Stage4` 已完成多少帧

---

## 10. 一条综合命令：同时看 Stage3 / Stage4

```bash
S3_LOG_DIR=/data/LFT-W02_data/pengxu/stage/logs_v2/full_S5_final_fast_full_v1__full_fast_multi_gpu
S4_LOG_DIR=/data/LFT-W02_data/pengxu/stage/logs_v2/full_full_fast_stage4_frozen_v1__stage4_only

S3_LOG=$(ls "$S3_LOG_DIR"/stage3*.log | head -n 1)
S4_LOG=$(ls "$S4_LOG_DIR"/stage4*.log | head -n 1)

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

## 常见判断

### 正常
- 进度条持续增长
- 输出文件数量持续增长
- `coverage / conf_mean` 有波动
- GPU 利用率不是一直满

### 异常
- 很久没有新的 `[progress]`
- 输出文件数完全不变
- 日志出现：
  - `TypeError`
  - `FileNotFoundError`
  - `Missing Stage-3 summary`
  - `NoneType`

---

## 新窗口接手时的提醒

- 先用命令 1-3 确认真正的日志文件名
- 再用命令 4-10 查进度
- 不要直接假设日志文件名，一定先 `ls`
