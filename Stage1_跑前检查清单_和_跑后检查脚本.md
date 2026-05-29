# Stage 1 跑前检查清单 & 跑后检查脚本

> 目标：确保第一次跑 Stage 1 尽量不踩坑，并在跑完后快速判断结果是否正常。

---

## 一、Stage 1 跑前检查清单

### 1. 数据目录是否就绪
确认以下目录存在且内容完整：

- `20260224/location_location_parquet/`
- `20260224/amdar_parquet/`
- `20260224/turb_parquet/`
- `radar/` 或雷达图所在目录

建议先看：

```bash
cd /data/LFT-W02_data/pengxu
python - <<'PY'
from pathlib import Path
base = Path('/data/LFT-W02_data/pengxu/20260224')
for name in ['location_location_parquet', 'amdar_parquet', 'turb_parquet']:
    p = base / name
    print(name, p.exists(), p)
PY
```

---

### 2. parquet manifest 是否存在
每个 parquet 目录都应该有 `_manifest.json`。

检查命令：

```bash
python - <<'PY'
from pathlib import Path
base = Path('/data/LFT-W02_data/pengxu/20260224')
for name in ['location_location_parquet', 'amdar_parquet', 'turb_parquet']:
    p = base / name / '_manifest.json'
    print(name, p.exists(), p)
PY
```

---

### 3. 关键字段是否存在
Stage 1 新版本优先使用这些字段：

#### `location`
- `time_utc`
- `lat_clean`
- `lon_clean`
- `alt_meters`
- `heading_deg`
- `ground_speed_ms`
- `flight_id`

#### `amdar`
- `time_utc`
- `lat_clean`
- `lon_clean`
- `alt_meters`
- `wind_dir`
- `wind_speed`
- `flight_id`

#### `turb`
- `time_utc`
- `lat_clean`
- `lon_clean`
- `alt_meters`
- `wind_dir`
- `wind_speed`
- `flight_id`
- `俯仰`
- `旋转`
- `航向`
- `颠簸强度`

建议先抽样检查 parquet 列：

```bash
python - <<'PY'
import polars as pl
files = [
    '/data/LFT-W02_data/pengxu/20260224/location_location_parquet/sheet_00.parquet',
    '/data/LFT-W02_data/pengxu/20260224/amdar_parquet/sheet_00.parquet',
    '/data/LFT-W02_data/pengxu/20260224/turb_parquet/sheet_00.parquet',
]
for f in files:
    df = pl.read_parquet(f)
    print('\nFILE:', f)
    print(df.columns)
PY
```

---

### 4. 经纬度是否已经正常
`location` 的经纬度必须不是 0，并且在合理范围内。

你已经验证过类似：
- `N28203089 -> 28.203089`
- `E109390986 -> 109.390986`

跑前建议再确认一眼：

```bash
python - <<'PY'
import polars as pl
p = '/data/LFT-W02_data/pengxu/20260224/location_location_parquet/sheet_00.parquet'
df = pl.read_parquet(p)
print(df.select(['纬度_raw','经度_raw','纬度_clean','经度_clean']).head(5))
PY
```

如果 `lat_valid_rate / lon_valid_rate = 1.0`，说明坐标正常。

---

### 5. 时间是否正常
确认：
- `location` 的 `time_utc` 是正常 UTC 时间
- `amdar / turb` 的 `time_utc` 已由北京时间正确换算

抽样检查：

```bash
python - <<'PY'
import polars as pl
for f in [
    '/data/LFT-W02_data/pengxu/20260224/location_location_parquet/sheet_00.parquet',
    '/data/LFT-W02_data/pengxu/20260224/amdar_parquet/sheet_00.parquet',
    '/data/LFT-W02_data/pengxu/20260224/turb_parquet/sheet_00.parquet',
]:
    df = pl.read_parquet(f)
    cols = [c for c in ['time_utc','time_beijing','接收时间（UTC）','时间（北京时）'] if c in df.columns]
    print('\nFILE:', f)
    print(df.select(cols).head(3))
PY
```

---

### 6. Stage 1 是否已经优先读新 parquet
确认 `hello.py` 已经优先找：

- `location_location_parquet`
- `amdar_parquet`
- `turb_parquet`

而不是只看旧 Excel。

---

### 7. 运行环境是否可用
建议确认：
- `polars` 可用
- `pandas` 可用
- `openpyxl` 可用
- `cv2` 可用

但 Stage 1 正式跑 parquet 时，最关键是 `polars`。

---

### 8. 雷达目录是否存在
确认雷达图能被找到，例如：
- `radar/`
- `气象雷达拼图（UTC）/`

至少要保证目录中有 `Z_RADA_*.png`。

---

### 9. 输出目录是否可写
确认 `dataset_output/` 可以写入。

---

### 10. 先小批验证
如果你担心第一次全量跑出问题，建议先：
- 只抽一个时间窗
- 或先跑小样本/少量雷达图

---

## 二、Stage 1 跑后检查脚本

Stage 1 跑完后，建议按下面这个顺序检查。

### 检查 1：Stage 1 输出目录是否生成
先看 `dataset_output/` 是否出现新的结果文件。

```bash
find /data/LFT-W02_data/pengxu/dataset_output -maxdepth 2 -type f | head
```

如果你不想用 `find`，也可以用 Python：

```bash
python - <<'PY'
from pathlib import Path
base = Path('/data/LFT-W02_data/pengxu/dataset_output')
for p in sorted(base.rglob('*'))[:50]:
    print(p)
PY
```

---

### 检查 2：Stage 1 是否成功输出关键中间文件
通常你需要确认是否有这些类文件：
- 风场重构结果
- 飞行智能体/轨迹聚合结果
- 每帧样本 JSON / npz / npy / parquet（取决于你的 Stage 1 输出设计）

如果你不确定具体文件名，可以先列出输出目录内容。

---

### 检查 3：Stage 1 运行日志里是否有异常
重点看是否有：
- 找不到 parquet 目录
- 找不到 `_manifest.json`
- 字段缺失报错
- `drop_nulls` 后数据量为 0
- 时间解析失败
- 经纬度全空

---

### 检查 4：抽查 Stage 1 使用的中间数据
如果 Stage 1 输出了中间表，重点确认：
- `time_utc` 非空
- `lat_clean / lon_clean` 非空
- `alt_meters` 非空
- `u_wind / v_wind` 非空（风观测表）
- `u_motion / v_motion` 非空（轨迹表）

---

### 检查 5：确认体素统计不是空的
你需要至少看到这些统计不是 0：
- 风体素数
- 轨迹体素数
- 有效飞行智能体数
- 有效通信体素数

如果这些都是 0，说明上游输入或筛选条件还有问题。

---

### 检查 6：对照 Stage 1 对齐脚本
如果 Stage 1 已经跑完，再运行：

```bash
cd /data/LFT-W02_data/pengxu
python check_stage1_stage2_alignment.py
```

重点看：
- `lat_clean / lon_clean` 是否被正确识别
- `time_utc` 是否存在
- `df_loc` 是否能进入 Stage 2 的体素逻辑
- 是否还存在 schema mismatch

---

## 三、Stage 1 跑后判断标准

### 通过标准
如果你看到：
- parquet 目录读取成功
- `lat_valid_rate = 1.0`
- `lon_valid_rate = 1.0`
- `time_utc` 正常
- `u_wind / v_wind` 正常
- `u_motion / v_motion` 正常
- 体素数不是 0

那说明 Stage 1 基本跑通。

### 失败信号
如果你看到：
- 全部字段都空
- 体素数为 0
- 只剩下少量行甚至 0 行
- 仍然在读旧 Excel 而不是新 parquet

那就说明 Stage 1 还需要继续收口。

---

## 四、建议的最短验证顺序

### 跑前
1. 检查 parquet 目录
2. 检查 manifest
3. 抽查 `sheet_00` 的字段和值
4. 确认 `hello.py` 优先读新 parquet

### 跑后
1. 看输出目录
2. 看日志有没有报错
3. 看体素统计
4. 跑 `check_stage1_stage2_alignment.py`

---

## 五、当前最推荐的一条命令组合

```bash
cd /data/LFT-W02_data/pengxu
python check_location_parquet_quality.py --dir /data/LFT-W02_data/pengxu/20260224/location_location_parquet
python check_stage1_stage2_alignment.py
```

如果 Stage 1 已经跑完，再配合看 `dataset_output/`。

---

## 六、简短结论

- 你现在的新 parquet 已经是 Stage 1 的正确输入方向。
- Stage 1 跑前最重要的是确认路径、manifest、字段、时间、经纬度。
- 跑后最重要的是确认输出不空、体素不空、对齐检查通过。

