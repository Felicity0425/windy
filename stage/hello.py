import sys
import io
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ('utf-8', 'utf8'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import polars as pl
import numpy as np
import cv2
import os
import glob
import json
import ctypes
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timedelta
import time

from communication_builder import select_ff_edges
from agent_builder import build_flight_agents_sparse

BASE_DIR = os.path.dirname(os.path.abspath(__file__))  # 脚本所在目录（作为统一路径基准）
DATASET_DATE = os.environ.get("WIND_DATASET_DATE", "20260224")  # 默认只使用 20260224 数据集
DATASET_ROOT = os.path.join(BASE_DIR, DATASET_DATE)


def _resolve_data_root():
    """优先使用指定日期数据目录，不存在时回退 BASE_DIR。"""
    if os.path.isdir(DATASET_ROOT):
        return DATASET_ROOT
    return BASE_DIR


DATA_ROOT = _resolve_data_root()

# 训练/数据构建实验配置：BASE / A / B / C
# - BASE: 历史默认（保守）
# - A: 放宽通信门限 + 增大似然 sigma（推荐先跑）
# - B: 在 A 基础上增加稀疏通信连接密度
# - C: 在 B 基础上增加候选飞机上限与 tier2 补充能力
ABLATION_PROFILE = os.environ.get("WIND_ABLATION_PROFILE", "A").strip().upper()
if ABLATION_PROFILE not in {"BASE", "A", "B", "C"}:
    ABLATION_PROFILE = "A"

# 物理真实模式：优先物理可达性与时空一致性，减少“为了补样本而放宽门限”
PHYSICS_REALISM_MODE = os.environ.get("WIND_PHYSICS_REALISM_MODE", "1") not in ("0", "false", "False")

# ==========================================
# 1. 全局配置参数
# ==========================================
LAT_MIN, LAT_MAX = 12.2, 54.2  # 数据集覆盖纬度范围（南到北）
LON_MIN, LON_MAX = 73.0, 135.0  # 数据集覆盖经度范围（西到东）
ALT_MIN, ALT_MAX = 0, 15000  # 垂直方向高度范围（单位：米）
DELTA_ALT = 500  # 垂直层厚（单位：米）
Z_DIM = int((ALT_MAX - ALT_MIN) / DELTA_ALT) + 1  # 垂直层数（包含顶层 15000m）

ALT_MULTIPLIER = 1.0  # 高度缩放系数（用于源数据单位换算，当前保持不变）
TIME_WINDOW_MINUTES = 5  # 每张雷达图对应的时间匹配窗口（前后各5分钟）
GROUND_SPEED_TO_MPS = 1000.0 / 3600.0  # 地速单位换算到 m/s（若原始为 km/h）
SOURCE_CONFIDENCE = {"amdar": 1.0, "turb": 0.9, "loc_motion": 0.7}  # 不同来源观测置信度
SPLIT_RATIOS = (0.7, 0.15, 0.15)  # 训练/验证/测试切分比例（按时间连续切分）
EXPORT_AGENT_VIEWS = True  # 导出代理级观测（amdar/turb/loc_motion）
COMM_TOPK_RATIO = 0.3  # 通信优先体素占比（Where2comm风格）
COMM_MIN_TOPK = 32  # 每帧最少保留通信体素数
if ABLATION_PROFILE in {"B", "C"}:
    COMM_TOPK_RATIO = 0.4
    COMM_MIN_TOPK = 64
COMM_WIND_WEIGHT = 0.7  # 联合通信打分中风观测权重
COMM_MOTION_WEIGHT = 0.3  # 联合通信打分中运动观测权重

GROUND_AGENT_ID = "ground_radar_center"  # 地面代理唯一标识
GROUND_AGENT_TYPE = "radar_mosaic_center"  # 地面代理类型

# ── 动态飞机智能体配置 ──────────────────────────────────────────────
# 用户要求：数据处理不丢候选飞行智能体，不设上限（有多少保留多少）
FLIGHT_AGENT_MAX = int(os.environ.get("WIND_FLIGHT_AGENT_MAX", "0"))  # 0=不封顶（动态）
FLIGHT_AGENT_TOPK = FLIGHT_AGENT_MAX  # 向后兼容别名（建议使用 FLIGHT_AGENT_MAX）
FLIGHT_PREFER_COMM_ELIGIBLE = True    # True: 优先选通信可达飞机填前排槽位
FLIGHT_TIER2_MAX = int(os.environ.get("WIND_FLIGHT_TIER2_MAX", "0"))  # 0=不限制 tier2 补位

# 空地通信物理约束（飞机→地面雷达）
# 物理真实模式下使用更保守门限，避免把明显不同时空/不可达样本当作可通信。
COMM_TIME_LIMIT_SECONDS = float(os.environ.get("WIND_COMM_TIME_LIMIT_SECONDS", "600"))
COMM_SPACE_LIMIT_KM = float(os.environ.get("WIND_COMM_SPACE_LIMIT_KM", "450"))
COMM_VERTICAL_LIMIT_M = float(os.environ.get("WIND_COMM_VERTICAL_LIMIT_M", "7000"))
if PHYSICS_REALISM_MODE:
    COMM_TIME_LIMIT_SECONDS = min(COMM_TIME_LIMIT_SECONDS, 300.0)
    COMM_SPACE_LIMIT_KM = min(COMM_SPACE_LIMIT_KM, 300.0)
    COMM_VERTICAL_LIMIT_M = min(COMM_VERTICAL_LIMIT_M, 5000.0)

# 空空通信物理约束（飞机→飞机）
FF_COMM_TIME_LIMIT_SECONDS = float(os.environ.get("WIND_FF_COMM_TIME_LIMIT_SECONDS", "300"))
FF_COMM_SPACE_LIMIT_KM = float(os.environ.get("WIND_FF_COMM_SPACE_LIMIT_KM", "300"))
FF_COMM_VERTICAL_LIMIT_M = float(os.environ.get("WIND_FF_COMM_VERTICAL_LIMIT_M", "3500"))
if PHYSICS_REALISM_MODE:
    FF_COMM_TIME_LIMIT_SECONDS = min(FF_COMM_TIME_LIMIT_SECONDS, 120.0)
    FF_COMM_SPACE_LIMIT_KM = min(FF_COMM_SPACE_LIMIT_KM, 200.0)
    FF_COMM_VERTICAL_LIMIT_M = min(FF_COMM_VERTICAL_LIMIT_M, 2000.0)

# B方案：空空通信采用“需求+置信度”驱动的稀疏边，而非全连接通信
FF_MAX_NEIGHBORS_PER_AGENT = int(os.environ.get("WIND_FF_MAX_NEIGHBORS", "12"))
if ABLATION_PROFILE in {"B", "C"}:
    FF_MAX_NEIGHBORS_PER_AGENT = max(FF_MAX_NEIGHBORS_PER_AGENT, 16)
FF_SCORE_DEMAND_W = float(os.environ.get("WIND_FF_SCORE_DEMAND_W", "0.45"))
FF_SCORE_CONF_W = float(os.environ.get("WIND_FF_SCORE_CONF_W", "0.35"))
FF_SCORE_LIKE_W = float(os.environ.get("WIND_FF_SCORE_LIKE_W", "0.20"))
COMM_ROUND = int(os.environ.get("WIND_COMM_ROUND", "1"))  # 0=物理约束内全连，>=1=按需稀疏通信

TIME_LIKELIHOOD_SIGMA_SECONDS = 180.0  # 时间似然因子高斯尺度（秒）
SPACE_LIKELIHOOD_SIGMA_KM = 100.0      # 空间似然因子高斯尺度（水平公里）
SPACE_LIKELIHOOD_SIGMA_Z_M = 1000.0   # 空间似然因子高斯尺度（垂直米）
if ABLATION_PROFILE in {"A", "B", "C"}:
    TIME_LIKELIHOOD_SIGMA_SECONDS = 360.0
    SPACE_LIKELIHOOD_SIGMA_KM = 180.0
    SPACE_LIKELIHOOD_SIGMA_Z_M = 2500.0

# 通信权重融合系数（空地/空空共用一套“可解释加权”）
COMM_WEIGHT_TIME_CONF = 0.35
COMM_WEIGHT_SPACE_CONF = 0.15
COMM_WEIGHT_TIME_LIKE = 0.25
COMM_WEIGHT_SPACE_LIKE = 0.25
COMM_WEIGHT_WIND_BONUS = 0.10  # 具备风观测能力时的额外增益（上限受 clip 控制）

# 数据质量保护阈值
MAX_WIND_SPEED_MS = 250.0
MAX_GROUND_SPEED_MS = 380.0
MIN_VALID_YEAR = 2020
MAX_VALID_YEAR = 2035

# 对电脑更友好的运行参数
MAX_FRAMES = int(os.environ.get("WIND_MAX_FRAMES", "0")) or None  # 0/空=全量，建议调试时设 100~500
BATCH_SIZE = int(os.environ.get("WIND_BATCH_SIZE", "20"))  # 每批处理帧数
BATCH_PAUSE_SECONDS = float(os.environ.get("WIND_BATCH_PAUSE_SECONDS", "0.2"))  # 每批结束后暂停秒数
SAVE_COMPRESSED = os.environ.get("WIND_SAVE_COMPRESSED", "1") not in ("0", "false", "False")  # 是否压缩存储
NPZ_STORAGE_MODE = os.environ.get("WIND_NPZ_STORAGE_MODE", "sparse_lossless")  # dense 或 sparse_lossless

# 自动友好模式（按内存动态调整暂停时长）
AUTO_FRIENDLY_MODE = os.environ.get("WIND_AUTO_FRIENDLY_MODE", "1") not in ("0", "false", "False")  # True 时启用自动节流
AUTO_MIN_FREE_MEM_GB = float(os.environ.get("WIND_AUTO_MIN_FREE_MEM_GB", "3.0"))  # 低于该可用内存阈值时增加暂停
AUTO_MAX_EXTRA_PAUSE_SECONDS = float(os.environ.get("WIND_AUTO_MAX_EXTRA_PAUSE_SECONDS", "2.0"))  # 自动增加暂停的上限

# 性能模式
OVERLAP_ONLY = os.environ.get("WIND_OVERLAP_ONLY", "1") not in ("0", "false", "False")  # 仅处理与 LOC 时间重叠的雷达帧
PROGRESS_EVERY = int(os.environ.get("WIND_PROGRESS_EVERY", "20"))  # 每 N 帧打印一次进度

# 样本质量过滤（用于 split 与训练建议）
FILTER_LOW_QUALITY_FOR_SPLIT = os.environ.get("WIND_FILTER_LOW_QUALITY_FOR_SPLIT", "1") not in ("0", "false", "False")

# 训练重采样与自适应 min_obs（写入 dataset_split.json，供训练脚本读取）
WIND_RESAMPLE_ENABLE = os.environ.get("WIND_RESAMPLE_ENABLE", "1") not in ("0", "false", "False")
WIND_RESAMPLE_ALPHA = float(os.environ.get("WIND_RESAMPLE_ALPHA", "0.35"))
WIND_RESAMPLE_MIN_REPEAT = int(os.environ.get("WIND_RESAMPLE_MIN_REPEAT", "1"))
WIND_RESAMPLE_MAX_REPEAT = int(os.environ.get("WIND_RESAMPLE_MAX_REPEAT", "3"))
if PHYSICS_REALISM_MODE:
    # 物理真实优先：降低重采样强度，避免训练分布被过度“人工拉平”
    WIND_RESAMPLE_ALPHA = min(WIND_RESAMPLE_ALPHA, 0.30)
    WIND_RESAMPLE_MAX_REPEAT = min(max(1, WIND_RESAMPLE_MAX_REPEAT), 2)

ADAPTIVE_MIN_OBS_ENABLE = os.environ.get("WIND_ADAPTIVE_MIN_OBS_ENABLE", "1") not in ("0", "false", "False")
ADAPTIVE_MIN_OBS_QUANTILE = float(os.environ.get("WIND_ADAPTIVE_MIN_OBS_QUANTILE", "0.15"))
ADAPTIVE_MIN_OBS_CAP = int(os.environ.get("WIND_ADAPTIVE_MIN_OBS_CAP", "8"))

# 实时监控与动态调参
ENABLE_REALTIME_MONITOR = os.environ.get("WIND_ENABLE_REALTIME_MONITOR", "1") not in ("0", "false", "False")
MONITOR_WINDOW = int(os.environ.get("WIND_MONITOR_WINDOW", "60"))
TARGET_FLIGHT_MIN = int(os.environ.get("WIND_TARGET_FLIGHT_MIN", "12"))
TARGET_FLIGHT_MAX = int(os.environ.get("WIND_TARGET_FLIGHT_MAX", "96"))
TIER2_MAX_MIN = int(os.environ.get("WIND_TIER2_MAX_MIN", "0"))
TIER2_MAX_MAX = int(os.environ.get("WIND_TIER2_MAX_MAX", "64"))
# 当 FLIGHT_TIER2_MAX<=0（表示不限）时，默认不让实时监控把它收紧成有限值
TIER2_AUTO_TUNE_ALLOW_UNLIMITED_SHRINK = os.environ.get("WIND_TIER2_AUTO_TUNE_ALLOW_UNLIMITED_SHRINK", "0") in ("1", "true", "True")

# LOC 大数据模式（Excel 多 sheet -> parquet 分片）
LOC_BIGDATA_MODE = os.environ.get("WIND_LOC_BIGDATA_MODE", "1") not in ("0", "false", "False")
LOC_PARQUET_DIRNAME = os.environ.get("WIND_LOC_PARQUET_DIR", "location_parquet")
LOC_SHEET_PAUSE_SECONDS = float(os.environ.get("WIND_LOC_SHEET_PAUSE_SECONDS", "0.4"))
LOC_REQUIRE_FULL_SHEETS = os.environ.get("WIND_LOC_REQUIRE_FULL_SHEETS", "1") not in ("0", "false", "False")

# 优先读取已重导出的 parquet 目录；找不到再回退 Excel/CSV
LOC_PARQUET_DIR_CANDIDATES = [
    os.path.join(DATASET_DATE, "location_location_parquet"),
    "location_location_parquet",
]
AMDAR_PARQUET_DIR_CANDIDATES = [
    os.path.join(DATASET_DATE, "amdar_parquet"),
    "amdar_parquet",
]
TURB_PARQUET_DIR_CANDIDATES = [
    os.path.join(DATASET_DATE, "turb_parquet"),
    "turb_parquet",
]

AMDAR_CANDIDATES = [
    os.path.join(DATASET_DATE, "amdar.xlsx"),
    "amdar.xlsx",
    "amdar.csv",
    "AMDAR报文.xlsx - Sheet1.csv",
    "AMDAR报文.csv",
    "AMDAR报文.xlsx",
]  # AMDAR 候选文件名
TURB_CANDIDATES = [
    os.path.join(DATASET_DATE, "turb.xlsx"),
    "turb.xlsx",
    "turb.csv",
    "Turb颠簸报文.xlsx - Sheet1.csv",
    "Turb颠簸报文.csv",
    "Turb颠簸报文.xlsx",
]  # 颠簸报文候选文件名
LOC_CANDIDATES = [
    os.path.join(DATASET_DATE, "location.xlsx"),
    "location.xlsx",
    "location.csv",
    "航空器位置报.xlsx - Sheet1.csv",
    "航空器位置报.csv",
    "航空器位置报.xlsx",
]  # 航空器位置报文候选文件名
RADAR_PATTERNS = [
    os.path.join("radar", "Z_RADA_*.png"),
    os.path.join("气象雷达拼图（UTC）", "Z_RADA_*.png"),
    "Z_RADA_*.png",
    os.path.join("**", "Z_RADA_*.png")
]  # 雷达文件搜索模式（优先子目录）
OUTPUT_DIR = "dataset_output"  # 输出数据集目录（保持与训练脚本兼容）
OUTPUT_DIR_ABS = os.path.join(BASE_DIR, OUTPUT_DIR)  # 输出数据集绝对目录

os.makedirs(OUTPUT_DIR_ABS, exist_ok=True)  # 创建输出目录，若已存在则忽略


def _read_table(candidates):
    """按候选名自动读取 CSV/XLSX/Parquet 目录，优先匹配现有文件。"""
    last_error = None

    for path in candidates:
        if os.path.isabs(path):
            candidates_abs = [path]
        else:
            candidates_abs = [os.path.join(DATA_ROOT, path), os.path.join(BASE_DIR, path)]

        full_path = None
        for p in candidates_abs:
            if os.path.exists(p):
                full_path = p
                break
        if full_path is None:
            continue

        lower = full_path.lower()
        if os.path.isdir(full_path):
            try:
                df = _read_parquet_dir(full_path)
                if df is not None:
                    return df, full_path
            except Exception as e:
                last_error = e
                continue

        if lower.endswith(".csv"):
            return pl.read_csv(full_path), full_path

        if lower.endswith((".xlsx", ".xls")):
            try:
                # 优先读单表或默认首个 sheet
                return pl.read_excel(full_path), full_path
            except Exception as e:
                last_error = e
                try:
                    import pandas as pd
                except Exception as e2:
                    raise RuntimeError(
                        "检测到 Excel 文件，但当前环境缺少读取依赖。"
                        "请先安装: pandas openpyxl。"
                        f" | polars.read_excel 错误: {e}"
                    ) from e2

                try:
                    xls = pd.ExcelFile(full_path)
                    frames = []
                    for s in xls.sheet_names:
                        df_s = pd.read_excel(xls, sheet_name=s)
                        if df_s is None or len(df_s) == 0:
                            continue
                        frames.append(df_s)
                    if not frames:
                        raise RuntimeError(f"Excel 无可用 sheet 数据: {full_path}")
                    merged = pd.concat(frames, ignore_index=True)
                    return pl.from_pandas(merged), full_path
                except Exception as e2:
                    last_error = e2

    if last_error is not None:
        raise RuntimeError(f"文件存在但读取失败: {candidates}，最后错误: {last_error}")
    raise FileNotFoundError(f"未找到任何输入文件: {candidates}")


def _resolve_first_existing_path(candidates):
    """返回候选路径中第一个存在的文件或目录绝对路径。"""
    for path in candidates:
        if os.path.isabs(path):
            cands = [path]
        else:
            cands = [os.path.join(DATA_ROOT, path), os.path.join(BASE_DIR, path)]
        for p in cands:
            if os.path.exists(p):
                return p
    return None


def _read_parquet_dir(parquet_dir):
    """读取包含 _manifest.json 的 parquet 分片目录并拼接。"""
    manifest_path = os.path.join(parquet_dir, "_manifest.json")
    if not os.path.exists(manifest_path):
        return None
    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            mf = json.load(f)
    except Exception:
        return None

    shards = mf.get("shards", []) or []
    shard_paths = []
    for s in shards:
        p = s.get("out_parquet") or s.get("parquet")
        if not p:
            continue
        if not os.path.isabs(p):
            p = os.path.join(parquet_dir, os.path.basename(p))
        shard_paths.append(p)

    if not shard_paths:
        return None

    parts = []
    for p in shard_paths:
        if not os.path.exists(p):
            return None
        parts.append(pl.read_parquet(p))

    if not parts:
        return None
    return pl.concat(parts, how="diagonal_relaxed")


def _build_loc_parquet_dir(loc_file_path):
    """基于原始 location 文件生成 parquet 分片目录。"""
    stem = os.path.splitext(os.path.basename(loc_file_path))[0]
    return os.path.join(DATA_ROOT, f"{stem}_{LOC_PARQUET_DIRNAME}")


def _normalize_location_sheet_df(df_pandas):
    """标准化 location sheet 字段，兼容“首行不是表头”的异常 sheet。"""
    import pandas as pd

    expected = ["接收时间（UTC）", "机尾号", "航班号", "纬度", "经度", "高度", "航向角", "地速"]
    cols = [str(c).strip() for c in df_pandas.columns]
    hit = sum(1 for c in expected if c in cols)

    # 若命中列太少，说明该 sheet 很可能把首行数据误当成了表头
    if hit < 4:
        df2 = pd.DataFrame(df_pandas).copy()
        # 尽量按前8列对齐到标准字段
        use_n = min(len(expected), df2.shape[1])
        rename_map = {df2.columns[i]: expected[i] for i in range(use_n)}
        df2 = df2.rename(columns=rename_map)
        # 只保留标准字段，缺失字段补空
        for c in expected:
            if c not in df2.columns:
                df2[c] = None
        df2 = df2[expected]
        return df2

    # 正常 sheet：若有多余列，截到标准字段并补齐缺失
    df2 = df_pandas.copy()
    for c in expected:
        if c not in df2.columns:
            df2[c] = None
    return df2[expected]


def _convert_location_excel_to_parquet_shards(excel_path, out_dir):
    """将 location.xlsx 的每个 sheet 独立转换为 parquet，降低峰值内存与卡顿风险。"""
    try:
        import pandas as pd
    except Exception as e:
        raise RuntimeError("LOC 大数据模式需要 pandas/openpyxl，请先安装。") from e

    os.makedirs(out_dir, exist_ok=True)
    xls = pd.ExcelFile(excel_path)
    sheet_names = list(xls.sheet_names)
    if len(sheet_names) == 0:
        raise RuntimeError(f"location 文件无可用 sheet: {excel_path}")

    converted = []
    for i, s in enumerate(sheet_names):
        df_s = pd.read_excel(xls, sheet_name=s)
        out_name = f"sheet_{i:02d}.parquet"
        out_path = os.path.join(out_dir, out_name)

        if df_s is None or len(df_s) == 0:
            # 空 sheet 也生成占位 parquet（0行），用于“完整性校验”
            pl.DataFrame().write_parquet(out_path)
            converted.append({"sheet": s, "rows": 0, "parquet": out_path})
        else:
            df_s_norm = _normalize_location_sheet_df(df_s)
            pl.from_pandas(df_s_norm).write_parquet(out_path)
            converted.append({"sheet": s, "rows": int(len(df_s_norm)), "parquet": out_path})

        free_mem = _get_free_memory_gb()
        pause_s = LOC_SHEET_PAUSE_SECONDS
        if AUTO_FRIENDLY_MODE:
            pause_s = _calc_auto_pause(LOC_SHEET_PAUSE_SECONDS, free_mem)
        print(f"   - LOC sheet {i+1}/{len(sheet_names)}: {s} -> {out_name}, rows={converted[-1]['rows']}")
        time.sleep(pause_s)

    # 完整性保护：必须每个 sheet 都有对应分片
    expected_files = {f"sheet_{i:02d}.parquet" for i in range(len(sheet_names))}
    actual_files = {os.path.basename(x["parquet"]) for x in converted}
    if LOC_REQUIRE_FULL_SHEETS and expected_files != actual_files:
        missing = sorted(list(expected_files - actual_files))
        raise RuntimeError(f"LOC parquet 分片不完整，缺失: {missing}")

    manifest = {
        "source": excel_path,
        "sheet_count": len(sheet_names),
        "generated_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "shards": converted,
    }
    with open(os.path.join(out_dir, "_manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    return converted


def _load_location_bigdata(candidates):
    """LOC 大数据加载：优先 parquet 分片；不存在则从 Excel 全 sheet 转换后加载。"""
    loc_path = _resolve_first_existing_path(candidates)
    if loc_path is None:
        raise FileNotFoundError(f"未找到任何输入文件: {candidates}")

    lower = loc_path.lower()
    if lower.endswith(".csv"):
        return pl.read_csv(loc_path), loc_path

    if lower.endswith((".xlsx", ".xls")):
        pq_dir = _build_loc_parquet_dir(loc_path)
        manifest_path = os.path.join(pq_dir, "_manifest.json")

        need_convert = True
        if os.path.isdir(pq_dir) and os.path.exists(manifest_path):
            try:
                with open(manifest_path, "r", encoding="utf-8") as f:
                    mf = json.load(f)
                sheet_count = int(mf.get("sheet_count", 0))
                shard_files = [os.path.join(pq_dir, f"sheet_{i:02d}.parquet") for i in range(sheet_count)]
                if sheet_count > 0 and all(os.path.exists(p) for p in shard_files):
                    need_convert = False
            except Exception:
                need_convert = True

        if need_convert:
            print("   - LOC 大数据模式：开始将 Excel 全 sheet 转 parquet 分片（一次性）...")
            _convert_location_excel_to_parquet_shards(loc_path, pq_dir)

        with open(manifest_path, "r", encoding="utf-8") as f:
            mf = json.load(f)
        sheet_count = int(mf.get("sheet_count", 0))
        if sheet_count <= 0:
            raise RuntimeError("LOC parquet manifest 无效，sheet_count<=0")

        parts = []
        total_rows = 0
        for i in range(sheet_count):
            p = os.path.join(pq_dir, f"sheet_{i:02d}.parquet")
            if not os.path.exists(p):
                if LOC_REQUIRE_FULL_SHEETS:
                    raise RuntimeError(f"LOC parquet 缺失分片: {p}")
                continue
            dfp = pl.read_parquet(p)
            parts.append(dfp)
            total_rows += len(dfp)

        if not parts:
            raise RuntimeError("LOC parquet 分片为空，无法继续")

        print(f"   - LOC parquet 分片加载完成: sheets={sheet_count}, rows={total_rows}")
        return pl.concat(parts, how="diagonal_relaxed"), f"{loc_path} -> {pq_dir}"

    return _read_table([loc_path])


def _parse_coord(v):
    """兼容 N/E/S/W 前缀、带符号十进制度、百万分之一度整数坐标。"""
    if v is None:
        return None

    s = str(v).strip()
    if not s:
        return None

    sign = 1
    if s[0] in "NnEe":
        sign = 1
        s_num = s[1:]
    elif s[0] in "SsWw":
        sign = -1
        s_num = s[1:]
    elif s[0] in "+-":
        sign = -1 if s[0] == "-" else 1
        s_num = s[1:]
    else:
        s_num = s

    try:
        num = float(s_num)
    except ValueError:
        return None

    if abs(num) > 180:
        num = num / 1000000.0

    if s[0] in "NnEeSsWw+-":
        return sign * abs(num)
    return num


def _get_free_memory_gb():
    """获取系统当前可用内存GB优先 psutil失败时使用 Windows API。"""
    try:
        import psutil
        return psutil.virtual_memory().available / (1024 ** 3)
    except Exception:
        pass

    try:
        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        mem_status = MEMORYSTATUSEX()
        mem_status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(mem_status)):
            return mem_status.ullAvailPhys / (1024 ** 3)
    except Exception:
        pass

    return None


def _calc_auto_pause(base_pause, free_mem_gb):
    """根据可用内存计算动态暂停时长。"""
    if free_mem_gb is None:
        return base_pause

    if free_mem_gb >= AUTO_MIN_FREE_MEM_GB:
        return base_pause

    gap = max(0.0, AUTO_MIN_FREE_MEM_GB - free_mem_gb)
    extra = min(AUTO_MAX_EXTRA_PAUSE_SECONDS, gap * 0.8)
    return base_pause + extra


def _to_datetime_expr(col_name, fmt):
    """兼容 datetime 原生列与字符串时间列。"""
    return pl.coalesce([
        pl.col(col_name).cast(pl.Datetime, strict=False),
        pl.col(col_name).cast(pl.Utf8).str.strptime(pl.Datetime, fmt, strict=False)
    ])


def _safe_parse_datetime_col(df, col_name, fmts):
    """多格式时间解析容错；列不存在时返回全空 Datetime 表达式。"""
    if col_name not in df.columns:
        return pl.lit(None, dtype=pl.Datetime)

    exprs = [pl.col(col_name).cast(pl.Datetime, strict=False)]
    for fmt in fmts:
        exprs.append(pl.col(col_name).cast(pl.Utf8).str.strptime(pl.Datetime, fmt, strict=False))
    return pl.coalesce(exprs)


def _safe_float_col(df, col_name, default=None):
    """缺失列容错：返回可 cast 为 Float64 的表达式。"""
    if col_name in df.columns:
        return pl.col(col_name).cast(pl.Float64, strict=False)
    return pl.lit(default, dtype=pl.Float64)


def _prefer_first_col(df, preferred, fallback=None):
    """返回第一个存在的新字段列名；不存在则返回 None。"""
    for name in preferred:
        if name in df.columns:
            return name
    return None


def _time_expr_prefer(df, preferred, fallback_formats):
    """优先使用已经标准化的时间列；若不存在则返回空值。"""
    for name in preferred:
        if name in df.columns:
            return pl.col(name).cast(pl.Datetime, strict=False)
    return pl.lit(None, dtype=pl.Datetime)


def _coord_expr_prefer(df, preferred, fallback):
    """优先使用清洗后的坐标列；若不存在则返回空值。"""
    for name in preferred:
        if name in df.columns:
            return pl.col(name).cast(pl.Float64, strict=False)
    return pl.lit(None, dtype=pl.Float64)


def _clip_float(expr, min_v=None, max_v=None):
    out = expr
    if min_v is not None:
        out = pl.when(out < min_v).then(min_v).otherwise(out)
    if max_v is not None:
        out = pl.when(out > max_v).then(max_v).otherwise(out)
    return out


def _read_gray_image_robust(path):
    """兼容 Windows 中文路径的灰度图读取。"""
    if not os.path.exists(path):
        return None

    # 先用 fromfile + imdecode（对中文路径更稳，避免 OpenCV 警告）
    try:
        data = np.fromfile(path, dtype=np.uint8)
        if data.size > 0:
            img = cv2.imdecode(data, cv2.IMREAD_GRAYSCALE)
            if img is not None:
                return img
    except Exception:
        pass

    # 再退回常规 imread
    img = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
    if img is not None:
        return img

    return None


def _pick_first_existing_column(columns, candidates):
    """从候选列名中挑选第一个存在的列。"""
    col_set = set(columns)
    for name in candidates:
        if name in col_set:
            return name
    return None


def _zyx_to_linear_idx(z, y, x, h_dim, w_dim):
    """将 (z,y,x) 转为线性索引，便于无损稀疏存储。"""
    max_idx = int(z.max(initial=0)) * h_dim * w_dim + int(y.max(initial=0)) * w_dim + int(x.max(initial=0))
    idx_dtype = np.uint32 if max_idx <= np.iinfo(np.uint32).max else np.uint64
    linear = z.astype(np.uint64) * (h_dim * w_dim) + y.astype(np.uint64) * w_dim + x.astype(np.uint64)
    return linear.astype(idx_dtype)


def _build_agent_sparse(grouped, h_dim, w_dim, u_col="u", v_col="v"):
    """把代理分组结果转为稀疏索引和值。"""
    if len(grouped) == 0:
        return np.array([], dtype=np.uint32), np.array([], dtype=np.float32), np.array([], dtype=np.float32)

    idx = _zyx_to_linear_idx(grouped["z"].to_numpy(), grouped["y"].to_numpy(), grouped["x"].to_numpy(), h_dim, w_dim)
    u_val = grouped[u_col].to_numpy().astype(np.float32, copy=False)
    v_val = grouped[v_col].to_numpy().astype(np.float32, copy=False)
    return idx, u_val, v_val


def _topk_comm_targets(idx, score):
    """对给定体素索引和分数执行 top-k 并降序输出。"""
    if idx.size == 0:
        return np.array([], dtype=np.uint32), np.array([], dtype=np.float32)

    uniq_idx, inv = np.unique(idx, return_inverse=True)
    uniq_score = np.zeros(len(uniq_idx), dtype=np.float32)
    np.maximum.at(uniq_score, inv, score.astype(np.float32, copy=False))

    k = max(COMM_MIN_TOPK, int(len(uniq_idx) * COMM_TOPK_RATIO))
    k = min(k, len(uniq_idx))
    if k <= 0:
        return np.array([], dtype=np.uint32), np.array([], dtype=np.float32)

    top_pos = np.argpartition(-uniq_score, k - 1)[:k]
    top_idx = uniq_idx[top_pos]
    top_score = uniq_score[top_pos]
    order = np.argsort(-top_score)
    return top_idx[order], top_score[order]


def _build_comm_targets(wind_grouped, loc_motion_grouped, h_dim, w_dim):
    """分开构造风观测/运动观测/联合通信优先体素。"""
    wind_idx = np.array([], dtype=np.uint32)
    wind_score = np.array([], dtype=np.float32)
    motion_idx = np.array([], dtype=np.uint32)
    motion_score = np.array([], dtype=np.float32)

    if len(wind_grouped) > 0:
        wind_idx = _zyx_to_linear_idx(
            wind_grouped["z"].to_numpy(), wind_grouped["y"].to_numpy(), wind_grouped["x"].to_numpy(), h_dim, w_dim
        )
        wind_score = (
            0.6 * wind_grouped["obs_conf"].to_numpy().astype(np.float32, copy=False)
            + 0.4 * np.log1p(wind_grouped["obs_count"].to_numpy().astype(np.float32, copy=False))
        ).astype(np.float32, copy=False)

    if len(loc_motion_grouped) > 0:
        motion_idx = _zyx_to_linear_idx(
            loc_motion_grouped["z"].to_numpy(), loc_motion_grouped["y"].to_numpy(), loc_motion_grouped["x"].to_numpy(), h_dim, w_dim
        )
        motion_score = (
            0.5 * float(SOURCE_CONFIDENCE["loc_motion"])
            + 0.5 * np.log1p(loc_motion_grouped["motion_count"].to_numpy().astype(np.float32, copy=False))
        ).astype(np.float32, copy=False)

    wind_top_idx, wind_top_score = _topk_comm_targets(wind_idx, wind_score)
    motion_top_idx, motion_top_score = _topk_comm_targets(motion_idx, motion_score)

    if wind_idx.size > 0 and motion_idx.size > 0:
        all_idx = np.concatenate([wind_idx, motion_idx])
        all_score = np.concatenate([
            COMM_WIND_WEIGHT * wind_score,
            COMM_MOTION_WEIGHT * motion_score,
        ]).astype(np.float32, copy=False)
        joint_idx, joint_score = _topk_comm_targets(all_idx, all_score)
    elif wind_idx.size > 0:
        joint_idx, joint_score = wind_top_idx, wind_top_score
    else:
        joint_idx, joint_score = motion_top_idx, motion_top_score

    return {
        "wind_idx": wind_top_idx,
        "wind_score": wind_top_score,
        "motion_idx": motion_top_idx,
        "motion_score": motion_top_score,
        "joint_idx": joint_idx,
        "joint_score": joint_score,
    }


def _haversine_km(lat1, lon1, lat2, lon2):
    """计算两经纬点水平大圆距离（公里）。"""
    r = 6371.0
    lat1_rad = np.radians(lat1)
    lon1_rad = np.radians(lon1)
    lat2_rad = np.radians(lat2)
    lon2_rad = np.radians(lon2)
    dlat = lat2_rad - lat1_rad
    dlon = lon2_rad - lon1_rad
    a = np.sin(dlat / 2.0) ** 2 + np.cos(lat1_rad) * np.cos(lat2_rad) * np.sin(dlon / 2.0) ** 2
    c = 2.0 * np.arctan2(np.sqrt(a), np.sqrt(1.0 - a))
    return float(r * c)


def _time_likelihood(time_gap_sec):
    t = float(max(0.0, time_gap_sec))
    sigma = max(1e-6, float(TIME_LIKELIHOOD_SIGMA_SECONDS))
    return float(np.exp(-0.5 * (t / sigma) ** 2))


def _space_likelihood(hdist_km, vdist_m):
    h = float(max(0.0, hdist_km))
    v = float(max(0.0, vdist_m))
    sigma_h = max(1e-6, float(SPACE_LIKELIHOOD_SIGMA_KM))
    sigma_v = max(1e-6, float(SPACE_LIKELIHOOD_SIGMA_Z_M))
    lh = np.exp(-0.5 * (h / sigma_h) ** 2)
    lv = np.exp(-0.5 * (v / sigma_v) ** 2)
    return float(lh * lv)


def _inverse_distance_weight(values, distances, eps=1e-6):
    values = np.asarray(values, dtype=np.float32)
    distances = np.asarray(distances, dtype=np.float32)
    w = 1.0 / np.maximum(distances, eps)
    w = w / max(float(w.sum()), eps)
    return float(np.sum(values * w))


RECON_MAX_FILL = int(os.environ.get("WIND_RECON_MAX_FILL", "8000"))
RECON_ENABLE_IDW = os.environ.get("WIND_RECON_ENABLE_IDW", "1") not in ("0", "false", "False")


def _reconstruct_wind_field(
    z_dim,
    h_dim,
    w_dim,
    wind_grouped,
    loc_motion_grouped,
    amdar_grouped,
    turb_grouped,
):
    """空地一体三维风场重构的保守基线。

    设计原则：
    1) 先用高可信观测直接落点；
    2) 再按来源权重融合；
    3) 最后只对缺失体素做局部、鲁棒的 IDW 补全；
    4) 输出显式置信度与掩码，避免把低置信结果伪装成真值。
    """
    recon_u = np.full((z_dim, h_dim, w_dim), np.nan, dtype=np.float32)
    recon_v = np.full((z_dim, h_dim, w_dim), np.nan, dtype=np.float32)
    recon_conf = np.zeros((z_dim, h_dim, w_dim), dtype=np.float32)
    recon_mask = np.zeros((z_dim, h_dim, w_dim), dtype=np.float32)

    def _safe_cols(df, u_name, v_name, weight_name=None):
        if len(df) == 0:
            return None
        if u_name not in df.columns or v_name not in df.columns:
            return None
        z = df["z"].to_numpy().astype(np.int32, copy=False)
        y = df["y"].to_numpy().astype(np.int32, copy=False)
        x = df["x"].to_numpy().astype(np.int32, copy=False)
        u = df[u_name].to_numpy().astype(np.float32, copy=False)
        v = df[v_name].to_numpy().astype(np.float32, copy=False)
        if weight_name is not None and weight_name in df.columns:
            w = df[weight_name].to_numpy().astype(np.float32, copy=False)
        elif "obs_conf" in df.columns:
            w = df["obs_conf"].to_numpy().astype(np.float32, copy=False)
        else:
            w = np.ones(len(df), dtype=np.float32)
        w = np.clip(w, 0.0, 1.0)
        return z, y, x, u, v, w

    # 1) 收集各源观测，给不同来源不同基础权重
    source_specs = []
    if len(wind_grouped) > 0:
        source_specs.append(("wind", wind_grouped, "u", "v", "obs_conf", 1.00))
    if len(loc_motion_grouped) > 0:
        source_specs.append(("motion", loc_motion_grouped, "u_motion", "v_motion", "motion_count", 0.55))
    if len(amdar_grouped) > 0:
        source_specs.append(("amdar", amdar_grouped, "u", "v", None, 0.90))
    if len(turb_grouped) > 0:
        source_specs.append(("turb", turb_grouped, "u", "v", None, 0.80))

    observed_coords = []
    observed_vals_u = []
    observed_vals_v = []
    observed_weight = []

    for source_name, df, u_name, v_name, weight_name, base_w in source_specs:
        cols = _safe_cols(df, u_name, v_name, weight_name)
        if cols is None:
            continue
        z, y, x, u, v, w = cols
        if len(z) == 0:
            continue

        # 轻量异常过滤：极端风速不参与重构
        speed = np.sqrt(u * u + v * v)
        keep = np.isfinite(u) & np.isfinite(v) & np.isfinite(speed) & (speed <= MAX_WIND_SPEED_MS)
        if not np.any(keep):
            continue

        # 同体素时，先按来源权重累积，后面再做体素级融合
        for zi, yi, xi, uu, vv, ww in zip(z[keep], y[keep], x[keep], u[keep], v[keep], w[keep]):
            if zi < 0 or yi < 0 or xi < 0 or zi >= z_dim or yi >= h_dim or xi >= w_dim:
                continue
            observed_coords.append((int(zi), int(yi), int(xi)))
            observed_vals_u.append(float(uu))
            observed_vals_v.append(float(vv))
            observed_weight.append(float(base_w * max(1e-4, float(ww))))

    if not observed_coords:
        return recon_u, recon_v, recon_conf, recon_mask

    observed_coords = np.asarray(observed_coords, dtype=np.int32)
    observed_vals_u = np.asarray(observed_vals_u, dtype=np.float32)
    observed_vals_v = np.asarray(observed_vals_v, dtype=np.float32)
    observed_weight = np.asarray(observed_weight, dtype=np.float32)

    # 2) 体素级融合：同一 voxel 多源观测时做加权平均
    linear = observed_coords[:, 0].astype(np.int64) * (h_dim * w_dim) + observed_coords[:, 1].astype(np.int64) * w_dim + observed_coords[:, 2].astype(np.int64)
    uniq_lin, inv = np.unique(linear, return_inverse=True)

    sum_w = np.zeros(len(uniq_lin), dtype=np.float32)
    sum_u = np.zeros(len(uniq_lin), dtype=np.float32)
    sum_v = np.zeros(len(uniq_lin), dtype=np.float32)
    np.add.at(sum_w, inv, observed_weight)
    np.add.at(sum_u, inv, observed_vals_u * observed_weight)
    np.add.at(sum_v, inv, observed_vals_v * observed_weight)

    z = (uniq_lin // (h_dim * w_dim)).astype(np.int32)
    rem = uniq_lin % (h_dim * w_dim)
    y = (rem // w_dim).astype(np.int32)
    x = (rem % w_dim).astype(np.int32)

    valid = sum_w > 1e-8
    if np.any(valid):
        u0 = sum_u[valid] / sum_w[valid]
        v0 = sum_v[valid] / sum_w[valid]
        c0 = np.clip(1.0 - np.exp(-sum_w[valid]), 0.0, 1.0)
        recon_u[z[valid], y[valid], x[valid]] = u0.astype(np.float32, copy=False)
        recon_v[z[valid], y[valid], x[valid]] = v0.astype(np.float32, copy=False)
        recon_conf[z[valid], y[valid], x[valid]] = c0.astype(np.float32, copy=False)
        recon_mask[z[valid], y[valid], x[valid]] = 1.0

    if not RECON_ENABLE_IDW:
        return recon_u, recon_v, recon_conf, recon_mask

    # 3) 局部鲁棒 IDW 补全：只补较近、较少量的缺失体素
    missing = np.argwhere(recon_mask <= 0)
    if missing.size == 0:
        return recon_u, recon_v, recon_conf, recon_mask

    max_fill = int(min(RECON_MAX_FILL, missing.shape[0]))
    # 归一化距离：z 轴更敏感，避免跨层过度平滑
    z_scale = max(1.0, float(z_dim))
    y_scale = max(1.0, float(h_dim))
    x_scale = max(1.0, float(w_dim))

    for zi, yi, xi in missing[:max_fill]:
        dz = (observed_coords[:, 0] - zi).astype(np.float32) / z_scale
        dy = (observed_coords[:, 1] - yi).astype(np.float32) / y_scale
        dx = (observed_coords[:, 2] - xi).astype(np.float32) / x_scale
        dist = np.sqrt(dz * dz + dy * dy + dx * dx)

        # 仅使用近邻观测，避免全局抹平
        keep = dist <= 0.15
        if not np.any(keep):
            continue

        w = observed_weight[keep] / np.maximum(dist[keep], 1e-4)
        w_sum = float(w.sum())
        if w_sum <= 1e-8:
            continue
        w = w / w_sum

        recon_u[zi, yi, xi] = float(np.sum(observed_vals_u[keep] * w))
        recon_v[zi, yi, xi] = float(np.sum(observed_vals_v[keep] * w))
        recon_conf[zi, yi, xi] = float(np.clip(np.sum(observed_weight[keep] * w), 0.0, 1.0))
        recon_mask[zi, yi, xi] = 1.0 if recon_conf[zi, yi, xi] >= 0.08 else 0.0

    return recon_u, recon_v, recon_conf, recon_mask


def _linear_conf(value, limit):
    lim = max(1e-6, float(limit))
    v = float(max(0.0, value))
    return float(max(0.0, 1.0 - v / lim))


def _blend_comm_weight(time_conf, space_conf, time_like, space_like, wind_bonus=0.0):
    """融合线性置信度与高斯似然，输出 [0,1] 可解释通信权重。"""
    w = (
        COMM_WEIGHT_TIME_CONF * float(time_conf)
        + COMM_WEIGHT_SPACE_CONF * float(space_conf)
        + COMM_WEIGHT_TIME_LIKE * float(time_like)
        + COMM_WEIGHT_SPACE_LIKE * float(space_like)
        + COMM_WEIGHT_WIND_BONUS * float(wind_bonus)
    )
    return float(np.clip(w, 0.0, 1.0))


def _ff_demand_score(obs_i, obs_j, same_wind_capability):
    """通信需求分数：观测密度越高，风协同能力越高，需求越高。"""
    base = 0.5 * np.log1p(float(max(0.0, obs_i))) + 0.5 * np.log1p(float(max(0.0, obs_j)))
    bonus = 0.3 if same_wind_capability > 0 else 0.0
    return float(np.clip(base / 4.0 + bonus, 0.0, 1.0))


def _ff_edge_score(demand, conf, like):
    """空空边综合分数（用于按需选择有限通信边）。"""
    s = FF_SCORE_DEMAND_W * float(demand) + FF_SCORE_CONF_W * float(conf) + FF_SCORE_LIKE_W * float(like)
    return float(np.clip(s, 0.0, 1.0))


def _compute_flight_intent(flight_frame, flight_id):
    """计算单架航班的飞行意图特征: (转向率 deg/s, 爬升率 m/s, 加速度 m/s^2)。"""
    try:
        one = flight_frame.filter(pl.col("flight_id") == flight_id)
        needed = ["time_utc", "heading_deg", "alt_meters", "ground_speed_ms"]
        for c in needed:
            if c not in one.columns:
                return np.zeros(3, dtype=np.float32)
        one = one.drop_nulls(subset=needed).sort("time_utc")
        if len(one) < 2:
            return np.zeros(3, dtype=np.float32)

        times = one["time_utc"].to_list()
        headings = one["heading_deg"].to_numpy().astype(np.float64)
        alts = one["alt_meters"].to_numpy().astype(np.float64)
        speeds = one["ground_speed_ms"].to_numpy().astype(np.float64)

        heading_rates, climb_rates, speed_trends = [], [], []
        for i in range(len(times) - 1):
            dt = max((times[i + 1] - times[i]).total_seconds(), 0.1)
            dh = headings[i + 1] - headings[i]
            if dh > 180:
                dh -= 360
            elif dh < -180:
                dh += 360
            heading_rates.append(dh / dt)
            climb_rates.append((alts[i + 1] - alts[i]) / dt)
            speed_trends.append((speeds[i + 1] - speeds[i]) / dt)

        return np.array([
            float(np.nanmean(heading_rates)) if heading_rates else 0.0,
            float(np.nanmean(climb_rates)) if climb_rates else 0.0,
            float(np.nanmean(speed_trends)) if speed_trends else 0.0,
        ], dtype=np.float32)
    except Exception:
        return np.zeros(3, dtype=np.float32)


def _eval_agent_geo(flight_frame, fid, target_time):
    """计算单架飞机相对地面参考点的时空指标（用于预筛选排序）。"""
    one_raw = flight_frame.filter(pl.col("flight_id") == fid)
    if len(one_raw) == 0:
        return None
    lat_mean = float(one_raw["lat_clean"].mean())
    lon_mean = float(one_raw["lon_clean"].mean())
    alt_mean = float(one_raw["alt_meters"].mean())
    t_min = one_raw["time_utc"].min()
    t_max = one_raw["time_utc"].max()
    t_mid = t_min + (t_max - t_min) / 2
    dt_sec = abs((target_time - t_mid).total_seconds())
    return lat_mean, lon_mean, alt_mean, t_mid, dt_sec


def _build_flight_agents_sparse_legacy_removed(*args, **kwargs):
    raise RuntimeError("Legacy _build_flight_agents_sparse has been removed. Use agent_builder.build_flight_agents_sparse.")

'''
    """动态选取飞机智能体：优先选通信可达飞机，不足时补充高似然飞机。

    分级策略
    --------
    Tier-1（空地可达）：dt ≤ COMM_TIME_LIMIT_SECONDS
                        hdist ≤ COMM_SPACE_LIMIT_KM
                        vdist ≤ COMM_VERTICAL_LIMIT_M
              → 参与空地通信 + 空空通信
    Tier-2（感知但不通信）：不满足以上约束，但时间似然较高
              → 仅作为感知补充，comm_allowed=0，不参与通信
    空空通信使用独立更严格的约束（FF_COMM_*），确保只有同时段、近距离飞机才互传。
    """
    def _make_empty(n=0, candidate_count=0, tier1_count=0, tier2_count=0):
        return {
            "flight_agent_ids": np.array([""] * n, dtype="<U64"),
            "flight_offsets": np.zeros(n + 1, dtype=np.int64),
            "flight_idx_flat": np.array([], dtype=np.uint32),
            "flight_u_flat": np.array([], dtype=np.float32),
            "flight_v_flat": np.array([], dtype=np.float32),
            "flight_count_flat": np.array([], dtype=np.float32),
            "flight_mask": np.zeros(n, dtype=np.uint8),
            "flight_time_gap_sec": np.full(n, np.inf, dtype=np.float32),
            "flight_space_hdist_km": np.full(n, np.inf, dtype=np.float32),
            "flight_space_vdist_m": np.full(n, np.inf, dtype=np.float32),
            "flight_time_conf": np.zeros(n, dtype=np.float32),
            "flight_space_conf": np.zeros(n, dtype=np.float32),
            "flight_time_likelihood": np.zeros(n, dtype=np.float32),
            "flight_space_likelihood": np.zeros(n, dtype=np.float32),
            "flight_st_conf": np.zeros(n, dtype=np.float32),
            "flight_st_likelihood": np.zeros(n, dtype=np.float32),
            "flight_comm_allowed": np.zeros(n, dtype=np.float32),
            "flight_comm_weight": np.zeros(n, dtype=np.float32),
            "flight_intent": np.zeros((n, 3), dtype=np.float32),
            "flight_has_wind_obs": np.zeros(n, dtype=np.float32),
            "ff_time_gap_sec": np.full((n, n), np.inf, dtype=np.float32),
            "ff_space_hdist_km": np.full((n, n), np.inf, dtype=np.float32),
            "ff_space_vdist_m": np.full((n, n), np.inf, dtype=np.float32),
            "ff_time_conf": np.zeros((n, n), dtype=np.float32),
            "ff_space_conf": np.zeros((n, n), dtype=np.float32),
            "ff_time_likelihood": np.zeros((n, n), dtype=np.float32),
            "ff_space_likelihood": np.zeros((n, n), dtype=np.float32),
            "ff_st_conf": np.zeros((n, n), dtype=np.float32),
            "ff_st_likelihood": np.zeros((n, n), dtype=np.float32),
            "ff_comm_allowed": np.zeros((n, n), dtype=np.float32),
            "ff_comm_weight": np.zeros((n, n), dtype=np.float32),
            "ff_motion_allowed": np.zeros((n, n), dtype=np.float32),
            "ff_motion_weight": np.zeros((n, n), dtype=np.float32),
            "ff_wind_allowed": np.zeros((n, n), dtype=np.float32),
            "ff_wind_weight": np.zeros((n, n), dtype=np.float32),
            "flight_topk": np.array(n, dtype=np.int32),
            "valid_flight_agents": 0,
            "candidate_flight_count": int(candidate_count),
            "tier1_candidate_count": int(tier1_count),
            "tier2_candidate_count": int(tier2_count),
            "valid_wind_capable_flights": 0,
            "ff_motion_edges": 0,
            "ff_wind_edges": 0,
        }

    if len(flight_grouped) == 0:
        n_empty = topk if topk > 0 else 0
        return _make_empty(n_empty, candidate_count=0, tier1_count=0, tier2_count=0)

    # ── 第一步：汇总各飞机观测量，并计算时空指标 ──────────────────────────────
    totals = (
        flight_grouped.group_by("flight_id")
        .agg(pl.col("motion_count").sum().alias("total_obs"))
    )
    fid_obs = {row["flight_id"]: row["total_obs"] for row in totals.iter_rows(named=True)}

    geo_cache = {}  # fid -> (lat, lon, alt, t_mid, dt_sec)
    for fid in fid_obs:
        g = _eval_agent_geo(flight_frame, fid, target_time)
        if g is not None:
            geo_cache[fid] = g

    # ── 第二步：分级筛选 ──────────────────────────────────────────────────────
    tier1, tier2 = [], []
    for fid, (lat, lon, alt, t_mid, dt_sec) in geo_cache.items():
        dh_km = _haversine_km(lat, lon, ground_lat, ground_lon)
        dz_m = abs(alt - ground_alt)
        ag_comm = (
            dt_sec <= COMM_TIME_LIMIT_SECONDS
            and dh_km <= COMM_SPACE_LIMIT_KM
            and dz_m <= COMM_VERTICAL_LIMIT_M
        )
        tl = _time_likelihood(dt_sec)
        sl = _space_likelihood(dh_km, dz_m)
        score = fid_obs.get(fid, 0)
        if ag_comm:
            tier1.append((fid, score, tl * sl))
        else:
            tier2.append((fid, score, tl * sl))

    tier1.sort(key=lambda x: x[1], reverse=True)  # 按观测量排
    tier2.sort(key=lambda x: x[2], reverse=True)  # 按时空似然排

    candidate_count = len(geo_cache)

    # 动态槽位：topk<=0 时不封顶（使用全部候选）；topk>0 时作为安全上限
    effective_topk = candidate_count if topk <= 0 else min(topk, candidate_count)
    if effective_topk <= 0:
        return _make_empty(0, candidate_count=candidate_count, tier1_count=len(tier1), tier2_count=len(tier2))

    max_tier1 = effective_topk
    selected_tier1 = [f for f, _, _ in tier1[:max_tier1]]
    remaining = effective_topk - len(selected_tier1)

    # 关键修正：Tier2 仅作为“补充上限”时，若 Tier1 稀缺会长期卡在固定值（如 8）。
    # 这里改成：
    # - 有 Tier1 时：Tier2 仍受 FLIGHT_TIER2_MAX 约束（保持偏通信可达）
    # - Tier1 为空时：Tier2 允许补满 effective_topk，避免“全是 8”
    effective_tier2_max = FLIGHT_TIER2_MAX if tier2_max_override is None else int(max(0, tier2_max_override))
    if FLIGHT_PREFER_COMM_ELIGIBLE:
        if len(selected_tier1) > 0:
            tier2_cap = min(effective_tier2_max, remaining)
        else:
            tier2_cap = remaining
        selected_tier2 = [f for f, _, _ in tier2[:tier2_cap]]
    else:
        selected_tier2 = []

    selected = selected_tier1 + selected_tier2

    if not selected:
        return _make_empty(effective_topk, candidate_count=candidate_count, tier1_count=len(tier1), tier2_count=len(tier2))

    # ── 第三步：分配槽位，填充稀疏数据 ──────────────────────────────────────────
    n_slots = len(selected)  # 动态槽位数（不再固定 32）
    ids = np.array(["" for _ in range(n_slots)], dtype="<U64")
    offsets = [0]
    idx_parts, u_parts, v_parts, c_parts = [], [], [], []
    mask = np.zeros(n_slots, dtype=np.uint8)

    time_gap_sec = np.full(n_slots, np.inf, dtype=np.float32)
    hdist_km_arr = np.full(n_slots, np.inf, dtype=np.float32)
    vdist_m_arr = np.full(n_slots, np.inf, dtype=np.float32)
    time_conf = np.zeros(n_slots, dtype=np.float32)
    space_conf = np.zeros(n_slots, dtype=np.float32)
    time_like = np.zeros(n_slots, dtype=np.float32)
    space_like = np.zeros(n_slots, dtype=np.float32)
    st_conf = np.zeros(n_slots, dtype=np.float32)
    st_like = np.zeros(n_slots, dtype=np.float32)
    comm_allowed = np.zeros(n_slots, dtype=np.float32)
    comm_weight = np.zeros(n_slots, dtype=np.float32)
    flight_intent = np.zeros((n_slots, 3), dtype=np.float32)
    flight_has_wind_obs = np.zeros(n_slots, dtype=np.float32)
    agent_lat = np.full(n_slots, np.nan, dtype=np.float64)
    agent_lon = np.full(n_slots, np.nan, dtype=np.float64)
    agent_alt = np.full(n_slots, np.nan, dtype=np.float64)
    agent_tsec = np.full(n_slots, np.nan, dtype=np.float64)
    agent_obs_count = np.zeros(n_slots, dtype=np.float32)

    # 空空通信矩阵（使用独立的更严格约束）
    ff_time_gap_sec = np.full((n_slots, n_slots), np.inf, dtype=np.float32)
    ff_hdist_km = np.full((n_slots, n_slots), np.inf, dtype=np.float32)
    ff_vdist_m = np.full((n_slots, n_slots), np.inf, dtype=np.float32)
    ff_time_conf = np.zeros((n_slots, n_slots), dtype=np.float32)
    ff_space_conf = np.zeros((n_slots, n_slots), dtype=np.float32)
    ff_time_like = np.zeros((n_slots, n_slots), dtype=np.float32)
    ff_space_like = np.zeros((n_slots, n_slots), dtype=np.float32)
    ff_st_conf = np.zeros((n_slots, n_slots), dtype=np.float32)
    ff_st_like = np.zeros((n_slots, n_slots), dtype=np.float32)
    ff_demand = np.zeros((n_slots, n_slots), dtype=np.float32)
    ff_score = np.zeros((n_slots, n_slots), dtype=np.float32)
    ff_allowed = np.zeros((n_slots, n_slots), dtype=np.float32)
    ff_weight = np.zeros((n_slots, n_slots), dtype=np.float32)
    ff_motion_allowed = np.zeros((n_slots, n_slots), dtype=np.float32)
    ff_motion_weight = np.zeros((n_slots, n_slots), dtype=np.float32)
    ff_wind_allowed = np.zeros((n_slots, n_slots), dtype=np.float32)
    ff_wind_weight = np.zeros((n_slots, n_slots), dtype=np.float32)

    if amdar_flight_ids is None:
        amdar_flight_ids = set()

    for i, fid in enumerate(selected):
        if i >= n_slots:
            break
        one = flight_grouped.filter(pl.col("flight_id") == fid)
        if len(one) == 0 or fid not in geo_cache:
            offsets.append(offsets[-1])
            continue

        idx = _zyx_to_linear_idx(one["z"].to_numpy(), one["y"].to_numpy(), one["x"].to_numpy(), h_dim, w_dim)
        idx_parts.append(idx)
        u_parts.append(one["u_motion"].to_numpy().astype(np.float32, copy=False))
        v_parts.append(one["v_motion"].to_numpy().astype(np.float32, copy=False))
        c_parts.append(one["motion_count"].to_numpy().astype(np.float32, copy=False))

        ids[i] = str(fid)
        mask[i] = 1
        offsets.append(offsets[-1] + len(idx))

        own_obs = float(one["motion_count"].sum()) if "motion_count" in one.columns else float(len(one))
        agent_obs_count[i] = own_obs

        lat, lon, alt, t_mid, dt_sec = geo_cache[fid]
        dh_km = _haversine_km(lat, lon, ground_lat, ground_lon)
        dz_m = abs(alt - ground_alt)

        # 空地通信指标
        tc = _linear_conf(dt_sec, COMM_TIME_LIMIT_SECONDS)
        sc_h = _linear_conf(dh_km, COMM_SPACE_LIMIT_KM)
        sc_v = _linear_conf(dz_m, COMM_VERTICAL_LIMIT_M)
        sc = float(np.sqrt(sc_h * sc_v))
        tl = _time_likelihood(dt_sec)
        sl = _space_likelihood(dh_km, dz_m)
        ag_allowed = 1.0 if (
            dt_sec <= COMM_TIME_LIMIT_SECONDS
            and dh_km <= COMM_SPACE_LIMIT_KM
            and dz_m <= COMM_VERTICAL_LIMIT_M
        ) else 0.0

        time_gap_sec[i] = dt_sec
        hdist_km_arr[i] = dh_km
        vdist_m_arr[i] = dz_m
        time_conf[i] = tc
        space_conf[i] = sc
        time_like[i] = tl
        space_like[i] = sl
        st_conf[i] = tc * sc
        st_like[i] = tl * sl
        comm_allowed[i] = ag_allowed
        wind_bonus = 1.0 if str(fid) in amdar_flight_ids else 0.0
        comm_weight[i] = ag_allowed * _blend_comm_weight(tc, sc, tl, sl, wind_bonus=wind_bonus)
        agent_lat[i] = lat
        agent_lon[i] = lon
        agent_alt[i] = alt
        agent_tsec[i] = float((t_mid - datetime(1970, 1, 1)).total_seconds())
        flight_intent[i] = _compute_flight_intent(flight_frame, fid)
        flight_has_wind_obs[i] = 1.0 if str(fid) in amdar_flight_ids else 0.0

    while len(offsets) < n_slots + 1:
        offsets.append(offsets[-1])

    # ── 第四步：空空通信矩阵（独立约束，比空地更严格）────────────────────────────
    valid_idx = np.where(mask > 0)[0]
    for i in valid_idx:
        for j in valid_idx:
            if i == j:
                continue
            if not (np.isfinite(agent_tsec[i]) and np.isfinite(agent_tsec[j])):
                continue
            dt_ff = abs(float(agent_tsec[i] - agent_tsec[j]))
            dh_ff = _haversine_km(agent_lat[i], agent_lon[i], agent_lat[j], agent_lon[j])
            dz_ff = abs(float(agent_alt[i] - agent_alt[j]))

            # 空空通信判定：使用更严格的时间限制（只有同时段观测的飞机才能互传信息）
            ff_ok = (
                dt_ff <= FF_COMM_TIME_LIMIT_SECONDS
                and dh_ff <= FF_COMM_SPACE_LIMIT_KM
                and dz_ff <= FF_COMM_VERTICAL_LIMIT_M
            )

            tc_ff = _linear_conf(dt_ff, FF_COMM_TIME_LIMIT_SECONDS)
            sc_h_ff = _linear_conf(dh_ff, FF_COMM_SPACE_LIMIT_KM)
            sc_v_ff = _linear_conf(dz_ff, FF_COMM_VERTICAL_LIMIT_M)
            sc_ff = float(np.sqrt(sc_h_ff * sc_v_ff))
            tl_ff = _time_likelihood(dt_ff)
            sl_ff = _space_likelihood(dh_ff, dz_ff)

            ff_time_gap_sec[i, j] = dt_ff
            ff_hdist_km[i, j] = dh_ff
            ff_vdist_m[i, j] = dz_ff
            ff_time_conf[i, j] = tc_ff
            ff_space_conf[i, j] = sc_ff
            ff_time_like[i, j] = tl_ff
            ff_space_like[i, j] = sl_ff
            ff_st_conf[i, j] = tc_ff * sc_ff
            ff_st_like[i, j] = tl_ff * sl_ff
            pair_wind_bonus = 1.0 if (flight_has_wind_obs[i] > 0 and flight_has_wind_obs[j] > 0) else 0.0
            demand_ij = _ff_demand_score(agent_obs_count[i], agent_obs_count[j], pair_wind_bonus)
            score_ij = _ff_edge_score(demand_ij, tc_ff * sc_ff, tl_ff * sl_ff)
            ff_demand[i, j] = demand_ij
            ff_score[i, j] = score_ij
            ff_allowed[i, j] = 1.0 if ff_ok else 0.0
            ff_weight[i, j] = ff_allowed[i, j] * score_ij
            ff_motion_allowed[i, j] = ff_allowed[i, j]
            ff_motion_weight[i, j] = ff_weight[i, j]
            both_have_wind = 1.0 if (flight_has_wind_obs[i] > 0 and flight_has_wind_obs[j] > 0) else 0.0
            ff_wind_allowed[i, j] = ff_allowed[i, j] * both_have_wind
            ff_wind_weight[i, j] = ff_weight[i, j] * both_have_wind

    # 交给独立通信构图模块：round0 全连，round>=1 按需稀疏
    ff_sel = select_ff_edges(
        comm_round=COMM_ROUND,
        ff_allowed=ff_allowed,
        ff_score=ff_score,
        flight_has_wind_obs=flight_has_wind_obs,
        max_neighbors_per_agent=FF_MAX_NEIGHBORS_PER_AGENT,
    )
    ff_allowed = ff_sel["ff_allowed"]
    ff_weight = ff_sel["ff_weight"]
    ff_motion_allowed = ff_sel["ff_motion_allowed"]
    ff_motion_weight = ff_sel["ff_motion_weight"]
    ff_wind_allowed = ff_sel["ff_wind_allowed"]
    ff_wind_weight = ff_sel["ff_wind_weight"]

    return {
        "flight_agent_ids": ids,
        "flight_offsets": np.asarray(offsets, dtype=np.int64),
        "flight_idx_flat": np.concatenate(idx_parts) if idx_parts else np.array([], dtype=np.uint32),
        "flight_u_flat": np.concatenate(u_parts) if u_parts else np.array([], dtype=np.float32),
        "flight_v_flat": np.concatenate(v_parts) if v_parts else np.array([], dtype=np.float32),
        "flight_count_flat": np.concatenate(c_parts) if c_parts else np.array([], dtype=np.float32),
        "flight_mask": mask,
        "flight_time_gap_sec": time_gap_sec,
        "flight_space_hdist_km": hdist_km_arr,
        "flight_space_vdist_m": vdist_m_arr,
        "flight_time_conf": time_conf,
        "flight_space_conf": space_conf,
        "flight_time_likelihood": time_like,
        "flight_space_likelihood": space_like,
        "flight_st_conf": st_conf,
        "flight_st_likelihood": st_like,
        "flight_comm_allowed": comm_allowed,
        "flight_comm_weight": comm_weight,
        "flight_intent": flight_intent,
        "flight_has_wind_obs": flight_has_wind_obs,
        "ff_time_gap_sec": ff_time_gap_sec,
        "ff_space_hdist_km": ff_hdist_km,
        "ff_space_vdist_m": ff_vdist_m,
        "ff_time_conf": ff_time_conf,
        "ff_space_conf": ff_space_conf,
        "ff_time_likelihood": ff_time_like,
        "ff_space_likelihood": ff_space_like,
        "ff_st_conf": ff_st_conf,
        "ff_st_likelihood": ff_st_like,
        "ff_comm_allowed": ff_allowed,
        "ff_comm_weight": ff_weight,
        "ff_motion_allowed": ff_motion_allowed,
        "ff_motion_weight": ff_motion_weight,
        "ff_wind_allowed": ff_wind_allowed,
        "ff_wind_weight": ff_wind_weight,
        "flight_topk": np.array(n_slots, dtype=np.int32),
        "valid_flight_agents": int(mask.sum()),
        "candidate_flight_count": int(candidate_count),
        "tier1_candidate_count": int(len(tier1)),
        "tier2_candidate_count": int(len(tier2)),
        "valid_wind_capable_flights": int(flight_has_wind_obs.sum()),
        "ff_motion_edges": int(ff_motion_allowed.sum()),
        "ff_wind_edges": int(ff_wind_allowed.sum()),
        "comm_eligible_ratio": float(np.mean(comm_allowed)) if n_slots > 0 else 0.0,
        "ff_edge_density": float(np.mean(ff_allowed)) if n_slots > 1 else 0.0,
    }

'''

def _save_sparse_lossless_npz(
    path,
    radar_img,
    h_dim,
    w_dim,
    z_dim,
    wind_grouped,
    loc_grouped,
    loc_motion_grouped,
    amdar_grouped,
    turb_grouped,
    flight_pack,
    ground_lat,
    ground_lon,
    ground_alt,
):
    """无损稀疏存储：默认值 + 线性索引 + 值，可 100% 还原稠密数组。"""
    if len(wind_grouped) > 0:
        z_w = wind_grouped["z"].to_numpy()
        y_w = wind_grouped["y"].to_numpy()
        x_w = wind_grouped["x"].to_numpy()
        uv_idx = _zyx_to_linear_idx(z_w, y_w, x_w, h_dim, w_dim)
        u_val = wind_grouped["u"].to_numpy().astype(np.float32, copy=False)
        v_val = wind_grouped["v"].to_numpy().astype(np.float32, copy=False)
        wind_count_val = wind_grouped["obs_count"].to_numpy().astype(np.float32, copy=False)
        wind_conf_val = wind_grouped["obs_conf"].to_numpy().astype(np.float32, copy=False)
    else:
        uv_idx = np.array([], dtype=np.uint32)
        u_val = np.array([], dtype=np.float32)
        v_val = np.array([], dtype=np.float32)
        wind_count_val = np.array([], dtype=np.float32)
        wind_conf_val = np.array([], dtype=np.float32)

    if len(loc_grouped) > 0:
        z_t = loc_grouped["z"].to_numpy()
        y_t = loc_grouped["y"].to_numpy()
        x_t = loc_grouped["x"].to_numpy()
        traj_idx = _zyx_to_linear_idx(z_t, y_t, x_t, h_dim, w_dim)
        traj_val = loc_grouped["density"].to_numpy().astype(np.float32, copy=False)
    else:
        traj_idx = np.array([], dtype=np.uint32)
        traj_val = np.array([], dtype=np.float32)

    if len(loc_motion_grouped) > 0:
        z_m = loc_motion_grouped["z"].to_numpy()
        y_m = loc_motion_grouped["y"].to_numpy()
        x_m = loc_motion_grouped["x"].to_numpy()
        motion_idx = _zyx_to_linear_idx(z_m, y_m, x_m, h_dim, w_dim)
        motion_u_val = loc_motion_grouped["u_motion"].to_numpy().astype(np.float32, copy=False)
        motion_v_val = loc_motion_grouped["v_motion"].to_numpy().astype(np.float32, copy=False)
        motion_count_val = loc_motion_grouped["motion_count"].to_numpy().astype(np.float32, copy=False)
    else:
        motion_idx = np.array([], dtype=np.uint32)
        motion_u_val = np.array([], dtype=np.float32)
        motion_v_val = np.array([], dtype=np.float32)
        motion_count_val = np.array([], dtype=np.float32)

    amdar_idx, amdar_u_val, amdar_v_val = _build_agent_sparse(amdar_grouped, h_dim, w_dim)
    turb_idx, turb_u_val, turb_v_val = _build_agent_sparse(turb_grouped, h_dim, w_dim)
    comm_targets = _build_comm_targets(wind_grouped, loc_motion_grouped, h_dim, w_dim)
    recon_u, recon_v, recon_conf, recon_mask = _reconstruct_wind_field(
        z_dim, h_dim, w_dim, wind_grouped, loc_motion_grouped, amdar_grouped, turb_grouped
    )

    np.savez_compressed(
        path,
        storage_mode=np.array("sparse_lossless"),
        grid_shape=np.array([z_dim, h_dim, w_dim], dtype=np.int32),
        radar_2d=radar_img,
        trajectory_fill=np.array(0.0, dtype=np.float32),
        trajectory_idx=traj_idx,
        trajectory_val=traj_val,
        uv_fill=np.array(np.nan, dtype=np.float32),
        uv_idx=uv_idx,
        u_val=u_val,
        v_val=v_val,
        wind_count_val=wind_count_val,
        wind_conf_val=wind_conf_val,
        motion_fill=np.array(np.nan, dtype=np.float32),
        motion_idx=motion_idx,
        motion_u_val=motion_u_val,
        motion_v_val=motion_v_val,
        motion_count_val=motion_count_val,
        comm_idx=comm_targets["joint_idx"],
        comm_score=comm_targets["joint_score"],
        comm_joint_idx=comm_targets["joint_idx"],
        comm_joint_score=comm_targets["joint_score"],
        comm_wind_idx=comm_targets["wind_idx"],
        comm_wind_score=comm_targets["wind_score"],
        comm_motion_idx=comm_targets["motion_idx"],
        comm_motion_score=comm_targets["motion_score"],
        agent_export=np.array(bool(EXPORT_AGENT_VIEWS)),
        ground_agent_id=np.array(GROUND_AGENT_ID),
        ground_agent_type=np.array(GROUND_AGENT_TYPE),
        ground_agent_lat=np.array(float(ground_lat), dtype=np.float32),
        ground_agent_lon=np.array(float(ground_lon), dtype=np.float32),
        ground_agent_alt_m=np.array(float(ground_alt), dtype=np.float32),
        amdar_idx=amdar_idx,
        amdar_u_val=amdar_u_val,
        amdar_v_val=amdar_v_val,
        turb_idx=turb_idx,
        turb_u_val=turb_u_val,
        turb_v_val=turb_v_val,
        recon_u_3d=recon_u,
        recon_v_3d=recon_v,
        recon_confidence_3d=recon_conf,
        recon_mask_3d=recon_mask,
        flight_topk=flight_pack["flight_topk"],
        flight_agent_ids=flight_pack["flight_agent_ids"],
        flight_offsets=flight_pack["flight_offsets"],
        flight_idx_flat=flight_pack["flight_idx_flat"],
        flight_u_flat=flight_pack["flight_u_flat"],
        flight_v_flat=flight_pack["flight_v_flat"],
        flight_count_flat=flight_pack["flight_count_flat"],
        flight_mask=flight_pack["flight_mask"],
        flight_time_gap_sec=flight_pack["flight_time_gap_sec"],
        flight_space_hdist_km=flight_pack["flight_space_hdist_km"],
        flight_space_vdist_m=flight_pack["flight_space_vdist_m"],
        flight_time_conf=flight_pack["flight_time_conf"],
        flight_space_conf=flight_pack["flight_space_conf"],
        flight_time_likelihood=flight_pack["flight_time_likelihood"],
        flight_space_likelihood=flight_pack["flight_space_likelihood"],
        flight_st_conf=flight_pack["flight_st_conf"],
        flight_st_likelihood=flight_pack["flight_st_likelihood"],
        flight_comm_allowed=flight_pack["flight_comm_allowed"],
        flight_comm_weight=flight_pack["flight_comm_weight"],
        flight_intent=flight_pack["flight_intent"],
        flight_has_wind_obs=flight_pack["flight_has_wind_obs"],
        ff_time_gap_sec=flight_pack["ff_time_gap_sec"],
        ff_space_hdist_km=flight_pack["ff_space_hdist_km"],
        ff_space_vdist_m=flight_pack["ff_space_vdist_m"],
        ff_time_conf=flight_pack["ff_time_conf"],
        ff_space_conf=flight_pack["ff_space_conf"],
        ff_time_likelihood=flight_pack["ff_time_likelihood"],
        ff_space_likelihood=flight_pack["ff_space_likelihood"],
        ff_st_conf=flight_pack["ff_st_conf"],
        ff_st_likelihood=flight_pack["ff_st_likelihood"],
        ff_comm_allowed=flight_pack["ff_comm_allowed"],
        ff_comm_weight=flight_pack["ff_comm_weight"],
        ff_motion_allowed=flight_pack["ff_motion_allowed"],
        ff_motion_weight=flight_pack["ff_motion_weight"],
        ff_wind_allowed=flight_pack["ff_wind_allowed"],
        ff_wind_weight=flight_pack["ff_wind_weight"],
    )


def load_frame_npz(path):
    """读取 frame npz；若是 sparse_lossless，会自动还原为稠密数组。"""
    data = np.load(path)
    mode = str(data["storage_mode"].item()) if "storage_mode" in data.files else "dense"

    if mode != "sparse_lossless":
        return {
            "radar_2d": data["radar_2d"],
            "trajectory_3d": data["trajectory_3d"],
            "u_wind_3d": data["u_wind_3d"],
            "v_wind_3d": data["v_wind_3d"],
            "ground_agent_id": data["ground_agent_id"] if "ground_agent_id" in data.files else None,
            "ground_agent_type": data["ground_agent_type"] if "ground_agent_type" in data.files else None,
            "ground_agent_lat": data["ground_agent_lat"] if "ground_agent_lat" in data.files else None,
            "ground_agent_lon": data["ground_agent_lon"] if "ground_agent_lon" in data.files else None,
            "ground_agent_alt_m": data["ground_agent_alt_m"] if "ground_agent_alt_m" in data.files else None,
            "wind_mask_3d": data["wind_mask_3d"] if "wind_mask_3d" in data.files else None,
            "wind_count_3d": data["wind_count_3d"] if "wind_count_3d" in data.files else None,
            "wind_confidence_3d": data["wind_confidence_3d"] if "wind_confidence_3d" in data.files else None,
            "recon_u_3d": data["recon_u_3d"] if "recon_u_3d" in data.files else None,
            "recon_v_3d": data["recon_v_3d"] if "recon_v_3d" in data.files else None,
            "recon_confidence_3d": data["recon_confidence_3d"] if "recon_confidence_3d" in data.files else None,
            "recon_mask_3d": data["recon_mask_3d"] if "recon_mask_3d" in data.files else None,
            "u_motion_3d": data["u_motion_3d"] if "u_motion_3d" in data.files else None,
            "v_motion_3d": data["v_motion_3d"] if "v_motion_3d" in data.files else None,
            "motion_mask_3d": data["motion_mask_3d"] if "motion_mask_3d" in data.files else None,
            "motion_count_3d": data["motion_count_3d"] if "motion_count_3d" in data.files else None,
            "comm_idx": data["comm_idx"] if "comm_idx" in data.files else None,
            "comm_score": data["comm_score"] if "comm_score" in data.files else None,
            "comm_joint_idx": data["comm_joint_idx"] if "comm_joint_idx" in data.files else (data["comm_idx"] if "comm_idx" in data.files else None),
            "comm_joint_score": data["comm_joint_score"] if "comm_joint_score" in data.files else (data["comm_score"] if "comm_score" in data.files else None),
            "comm_wind_idx": data["comm_wind_idx"] if "comm_wind_idx" in data.files else None,
            "comm_wind_score": data["comm_wind_score"] if "comm_wind_score" in data.files else None,
            "comm_motion_idx": data["comm_motion_idx"] if "comm_motion_idx" in data.files else None,
            "comm_motion_score": data["comm_motion_score"] if "comm_motion_score" in data.files else None,
            "flight_topk": data["flight_topk"] if "flight_topk" in data.files else None,
            "flight_agent_ids": data["flight_agent_ids"] if "flight_agent_ids" in data.files else None,
            "flight_offsets": data["flight_offsets"] if "flight_offsets" in data.files else None,
            "flight_idx_flat": data["flight_idx_flat"] if "flight_idx_flat" in data.files else None,
            "flight_u_flat": data["flight_u_flat"] if "flight_u_flat" in data.files else None,
            "flight_v_flat": data["flight_v_flat"] if "flight_v_flat" in data.files else None,
            "flight_count_flat": data["flight_count_flat"] if "flight_count_flat" in data.files else None,
            "flight_mask": data["flight_mask"] if "flight_mask" in data.files else None,
            "flight_time_gap_sec": data["flight_time_gap_sec"] if "flight_time_gap_sec" in data.files else None,
            "flight_space_hdist_km": data["flight_space_hdist_km"] if "flight_space_hdist_km" in data.files else None,
            "flight_space_vdist_m": data["flight_space_vdist_m"] if "flight_space_vdist_m" in data.files else None,
            "flight_time_conf": data["flight_time_conf"] if "flight_time_conf" in data.files else None,
            "flight_space_conf": data["flight_space_conf"] if "flight_space_conf" in data.files else None,
            "flight_time_likelihood": data["flight_time_likelihood"] if "flight_time_likelihood" in data.files else None,
            "flight_space_likelihood": data["flight_space_likelihood"] if "flight_space_likelihood" in data.files else None,
            "flight_st_conf": data["flight_st_conf"] if "flight_st_conf" in data.files else None,
            "flight_st_likelihood": data["flight_st_likelihood"] if "flight_st_likelihood" in data.files else None,
            "flight_comm_allowed": data["flight_comm_allowed"] if "flight_comm_allowed" in data.files else None,
            "flight_comm_weight": data["flight_comm_weight"] if "flight_comm_weight" in data.files else None,
            "flight_intent": data["flight_intent"] if "flight_intent" in data.files else None,
            "flight_has_wind_obs": data["flight_has_wind_obs"] if "flight_has_wind_obs" in data.files else None,
            "ff_time_gap_sec": data["ff_time_gap_sec"] if "ff_time_gap_sec" in data.files else None,
            "ff_space_hdist_km": data["ff_space_hdist_km"] if "ff_space_hdist_km" in data.files else None,
            "ff_space_vdist_m": data["ff_space_vdist_m"] if "ff_space_vdist_m" in data.files else None,
            "ff_time_conf": data["ff_time_conf"] if "ff_time_conf" in data.files else None,
            "ff_space_conf": data["ff_space_conf"] if "ff_space_conf" in data.files else None,
            "ff_time_likelihood": data["ff_time_likelihood"] if "ff_time_likelihood" in data.files else None,
            "ff_space_likelihood": data["ff_space_likelihood"] if "ff_space_likelihood" in data.files else None,
            "ff_st_conf": data["ff_st_conf"] if "ff_st_conf" in data.files else None,
            "ff_st_likelihood": data["ff_st_likelihood"] if "ff_st_likelihood" in data.files else None,
            "ff_comm_allowed": data["ff_comm_allowed"] if "ff_comm_allowed" in data.files else None,
            "ff_comm_weight": data["ff_comm_weight"] if "ff_comm_weight" in data.files else None,
            "ff_motion_allowed": data["ff_motion_allowed"] if "ff_motion_allowed" in data.files else (data["ff_comm_allowed"] if "ff_comm_allowed" in data.files else None),
            "ff_motion_weight": data["ff_motion_weight"] if "ff_motion_weight" in data.files else (data["ff_comm_weight"] if "ff_comm_weight" in data.files else None),
            "ff_wind_allowed": data["ff_wind_allowed"] if "ff_wind_allowed" in data.files else None,
            "ff_wind_weight": data["ff_wind_weight"] if "ff_wind_weight" in data.files else None,
        }

    z_dim, h_dim, w_dim = data["grid_shape"].tolist()
    total = int(z_dim) * int(h_dim) * int(w_dim)

    trajectory = np.full(total, data["trajectory_fill"].item(), dtype=np.float32)
    if data["trajectory_idx"].size > 0:
        trajectory[data["trajectory_idx"]] = data["trajectory_val"]
    trajectory = trajectory.reshape((z_dim, h_dim, w_dim))

    u = np.full(total, data["uv_fill"].item(), dtype=np.float32)
    v = np.full(total, data["uv_fill"].item(), dtype=np.float32)
    wind_mask = np.zeros(total, dtype=np.float32)
    wind_count = np.zeros(total, dtype=np.float32)
    wind_conf = np.zeros(total, dtype=np.float32)
    if data["uv_idx"].size > 0:
        u[data["uv_idx"]] = data["u_val"]
        v[data["uv_idx"]] = data["v_val"]
        wind_mask[data["uv_idx"]] = 1.0
        if "wind_count_val" in data.files:
            wind_count[data["uv_idx"]] = data["wind_count_val"]
        if "wind_conf_val" in data.files:
            wind_conf[data["uv_idx"]] = data["wind_conf_val"]
    u = u.reshape((z_dim, h_dim, w_dim))
    v = v.reshape((z_dim, h_dim, w_dim))
    wind_mask = wind_mask.reshape((z_dim, h_dim, w_dim))
    wind_count = wind_count.reshape((z_dim, h_dim, w_dim))
    wind_conf = wind_conf.reshape((z_dim, h_dim, w_dim))

    motion_fill = data["motion_fill"].item() if "motion_fill" in data.files else np.nan
    motion_u = np.full(total, motion_fill, dtype=np.float32)
    motion_v = np.full(total, motion_fill, dtype=np.float32)
    motion_mask = np.zeros(total, dtype=np.float32)
    motion_count = np.zeros(total, dtype=np.float32)
    if "motion_idx" in data.files and data["motion_idx"].size > 0:
        motion_u[data["motion_idx"]] = data["motion_u_val"]
        motion_v[data["motion_idx"]] = data["motion_v_val"]
        motion_mask[data["motion_idx"]] = 1.0
        if "motion_count_val" in data.files:
            motion_count[data["motion_idx"]] = data["motion_count_val"]
    motion_u = motion_u.reshape((z_dim, h_dim, w_dim))
    motion_v = motion_v.reshape((z_dim, h_dim, w_dim))
    motion_mask = motion_mask.reshape((z_dim, h_dim, w_dim))
    motion_count = motion_count.reshape((z_dim, h_dim, w_dim))

    return {
        "radar_2d": data["radar_2d"],
        "trajectory_3d": trajectory,
        "u_wind_3d": u,
        "v_wind_3d": v,
        "ground_agent_id": data["ground_agent_id"] if "ground_agent_id" in data.files else None,
        "ground_agent_type": data["ground_agent_type"] if "ground_agent_type" in data.files else None,
        "ground_agent_lat": data["ground_agent_lat"] if "ground_agent_lat" in data.files else None,
        "ground_agent_lon": data["ground_agent_lon"] if "ground_agent_lon" in data.files else None,
        "ground_agent_alt_m": data["ground_agent_alt_m"] if "ground_agent_alt_m" in data.files else None,
        "wind_mask_3d": wind_mask,
        "wind_count_3d": wind_count,
        "wind_confidence_3d": wind_conf,
        "recon_u_3d": recon_u,
        "recon_v_3d": recon_v,
        "recon_confidence_3d": recon_conf,
        "recon_mask_3d": recon_mask,
        "u_motion_3d": motion_u,
        "v_motion_3d": motion_v,
        "motion_mask_3d": motion_mask,
        "motion_count_3d": motion_count,
        "comm_idx": data["comm_idx"] if "comm_idx" in data.files else None,
        "comm_score": data["comm_score"] if "comm_score" in data.files else None,
        "comm_joint_idx": data["comm_joint_idx"] if "comm_joint_idx" in data.files else (data["comm_idx"] if "comm_idx" in data.files else None),
        "comm_joint_score": data["comm_joint_score"] if "comm_joint_score" in data.files else (data["comm_score"] if "comm_score" in data.files else None),
        "comm_wind_idx": data["comm_wind_idx"] if "comm_wind_idx" in data.files else None,
        "comm_wind_score": data["comm_wind_score"] if "comm_wind_score" in data.files else None,
        "comm_motion_idx": data["comm_motion_idx"] if "comm_motion_idx" in data.files else None,
        "comm_motion_score": data["comm_motion_score"] if "comm_motion_score" in data.files else None,
        "flight_topk": data["flight_topk"] if "flight_topk" in data.files else None,
        "flight_agent_ids": data["flight_agent_ids"] if "flight_agent_ids" in data.files else None,
        "flight_offsets": data["flight_offsets"] if "flight_offsets" in data.files else None,
        "flight_idx_flat": data["flight_idx_flat"] if "flight_idx_flat" in data.files else None,
        "flight_u_flat": data["flight_u_flat"] if "flight_u_flat" in data.files else None,
        "flight_v_flat": data["flight_v_flat"] if "flight_v_flat" in data.files else None,
        "flight_count_flat": data["flight_count_flat"] if "flight_count_flat" in data.files else None,
        "flight_mask": data["flight_mask"] if "flight_mask" in data.files else None,
        "flight_time_gap_sec": data["flight_time_gap_sec"] if "flight_time_gap_sec" in data.files else None,
        "flight_space_hdist_km": data["flight_space_hdist_km"] if "flight_space_hdist_km" in data.files else None,
        "flight_space_vdist_m": data["flight_space_vdist_m"] if "flight_space_vdist_m" in data.files else None,
        "flight_time_conf": data["flight_time_conf"] if "flight_time_conf" in data.files else None,
        "flight_space_conf": data["flight_space_conf"] if "flight_space_conf" in data.files else None,
        "flight_time_likelihood": data["flight_time_likelihood"] if "flight_time_likelihood" in data.files else None,
        "flight_space_likelihood": data["flight_space_likelihood"] if "flight_space_likelihood" in data.files else None,
        "flight_st_conf": data["flight_st_conf"] if "flight_st_conf" in data.files else None,
        "flight_st_likelihood": data["flight_st_likelihood"] if "flight_st_likelihood" in data.files else None,
        "flight_comm_allowed": data["flight_comm_allowed"] if "flight_comm_allowed" in data.files else None,
        "flight_comm_weight": data["flight_comm_weight"] if "flight_comm_weight" in data.files else None,
        "flight_intent": data["flight_intent"] if "flight_intent" in data.files else None,
        "flight_has_wind_obs": data["flight_has_wind_obs"] if "flight_has_wind_obs" in data.files else None,
        "ff_time_gap_sec": data["ff_time_gap_sec"] if "ff_time_gap_sec" in data.files else None,
        "ff_space_hdist_km": data["ff_space_hdist_km"] if "ff_space_hdist_km" in data.files else None,
        "ff_space_vdist_m": data["ff_space_vdist_m"] if "ff_space_vdist_m" in data.files else None,
        "ff_time_conf": data["ff_time_conf"] if "ff_time_conf" in data.files else None,
        "ff_space_conf": data["ff_space_conf"] if "ff_space_conf" in data.files else None,
        "ff_time_likelihood": data["ff_time_likelihood"] if "ff_time_likelihood" in data.files else None,
        "ff_space_likelihood": data["ff_space_likelihood"] if "ff_space_likelihood" in data.files else None,
        "ff_st_conf": data["ff_st_conf"] if "ff_st_conf" in data.files else None,
        "ff_st_likelihood": data["ff_st_likelihood"] if "ff_st_likelihood" in data.files else None,
        "ff_comm_allowed": data["ff_comm_allowed"] if "ff_comm_allowed" in data.files else None,
        "ff_comm_weight": data["ff_comm_weight"] if "ff_comm_weight" in data.files else None,
        "ff_motion_allowed": data["ff_motion_allowed"] if "ff_motion_allowed" in data.files else (data["ff_comm_allowed"] if "ff_comm_allowed" in data.files else None),
        "ff_motion_weight": data["ff_motion_weight"] if "ff_motion_weight" in data.files else (data["ff_comm_weight"] if "ff_comm_weight" in data.files else None),
        "ff_wind_allowed": data["ff_wind_allowed"] if "ff_wind_allowed" in data.files else None,
        "ff_wind_weight": data["ff_wind_weight"] if "ff_wind_weight" in data.files else None,
    }


def _build_time_contiguous_splits(dataset_metadata):
    """按“天块(day-block)”连续切分，避免跨天过程泄漏。"""
    frames = sorted(dataset_metadata, key=lambda x: x["frame_id"])
    n = len(frames)
    if n == 0:
        return {
            "train": [], "val": [], "test": [],
            "day_groups": {"train": [], "val": [], "test": []},
            "day_frame_counts": {}
        }

    # 1) 先按 UTC 日期分组（同一天尽量不拆到不同 split）
    day_to_frames = {}
    for f in frames:
        ts = f.get("timestamp_utc")
        day = str(ts)[:10] if ts else "unknown"
        day_to_frames.setdefault(day, []).append(f)

    days = sorted(day_to_frames.keys())
    day_counts = [len(day_to_frames[d]) for d in days]
    total = sum(day_counts)

    # 2) 以“天”为单位按比例切分（连续）
    train_target = total * SPLIT_RATIOS[0]
    val_target = total * SPLIT_RATIOS[1]

    train_days, val_days, test_days = [], [], []
    acc_train, acc_val = 0, 0

    for d, c in zip(days, day_counts):
        if acc_train < train_target or len(train_days) == 0:
            train_days.append(d)
            acc_train += c
        elif acc_val < val_target or len(val_days) == 0:
            val_days.append(d)
            acc_val += c
        else:
            test_days.append(d)

    # 兜底：保证 test 不为空（有足够天数时）
    if len(test_days) == 0 and len(days) >= 3:
        if len(val_days) > 1:
            test_days = [val_days.pop()]
        elif len(train_days) > 1:
            test_days = [train_days.pop()]

    train = [x["filename"] for d in train_days for x in day_to_frames[d]]
    val = [x["filename"] for d in val_days for x in day_to_frames[d]]
    test = [x["filename"] for d in test_days for x in day_to_frames[d]]

    return {
        "train": train,
        "val": val,
        "test": test,
        "day_groups": {
            "train": train_days,
            "val": val_days,
            "test": test_days,
        },
        "day_frame_counts": {d: len(day_to_frames[d]) for d in days}
    }


def _build_weighted_train_filenames(train_frames):
    """依据观测稀缺度对训练样本做重复采样，返回 train_weighted 文件名列表。"""
    if not train_frames:
        return []

    obs = np.array([int(max(0, x.get("valid_wind_voxels", 0))) for x in train_frames], dtype=np.float32)
    if obs.size == 0:
        return [x.get("filename") for x in train_frames if x.get("filename")]

    # 稀缺样本（观测少）权重更高：w = (max_obs / obs)^alpha
    obs_safe = np.clip(obs, 1.0, None)
    max_obs = float(np.max(obs_safe))
    alpha = float(max(0.0, WIND_RESAMPLE_ALPHA))
    raw_w = (max_obs / obs_safe) ** alpha

    min_r = int(max(1, WIND_RESAMPLE_MIN_REPEAT))
    max_r = int(max(min_r, WIND_RESAMPLE_MAX_REPEAT))

    reps = np.clip(np.rint(raw_w).astype(np.int64), min_r, max_r)

    out = []
    for f, r in zip(train_frames, reps):
        fn = f.get("filename")
        if not fn:
            continue
        out.extend([fn] * int(r))

    return out


# ==========================================
# 2. 全局数据读取与清洗
# ==========================================
def load_global_data():
    print("🚀 [1/3] 正在将风场/轨迹表格载入内存...")  # 打印阶段进度
    start_time = time.time()  # 记录开始时间
    
    df_amdar, amdar_path = _read_table(AMDAR_PARQUET_DIR_CANDIDATES + AMDAR_CANDIDATES)  # 新 parquet 优先，旧文件兜底
    df_turb, turb_path = _read_table(TURB_PARQUET_DIR_CANDIDATES + TURB_CANDIDATES)  # 新 parquet 优先，旧文件兜底
    print(f"   - AMDAR: {amdar_path}")  # 打印实际使用的 AMDAR 文件
    print(f"   - Turb:  {turb_path}")  # 打印实际使用的颠簸报文文件
    
    wind_flight_candidates = [
        "航班号", "航班编号", "航班", "航班代码", "航班ID", "航班识别码",
        "呼号", "呼号标识", "机号", "飞机号", "航空器识别码", "航空器ID", "ICAO",
    ]
    amdar_flight_col = _pick_first_existing_column(df_amdar.columns, ["flight_id", "航班号", "机尾号"])
    turb_flight_col = _pick_first_existing_column(df_turb.columns, ["flight_id", "航班号", "机尾号"])
    if amdar_flight_col:
        print(f"   - AMDAR 航班标识列: {amdar_flight_col}")
    else:
        print("   - AMDAR 未检测到航班标识列，风观测仅按体素聚合")

    amdar_time_col = _prefer_first_col(df_amdar, ["time_utc"])
    turb_time_col = _prefer_first_col(df_turb, ["time_utc"])

    amdar_lat_col = _prefer_first_col(df_amdar, ["lat_clean"])
    amdar_lon_col = _prefer_first_col(df_amdar, ["lon_clean"])
    amdar_alt_col = _prefer_first_col(df_amdar, ["alt_meters"])
    amdar_wdir_col = _prefer_first_col(df_amdar, ["wind_dir"])
    amdar_wspd_col = _prefer_first_col(df_amdar, ["wind_speed"])

    turb_lat_col = _prefer_first_col(df_turb, ["lat_clean"])
    turb_lon_col = _prefer_first_col(df_turb, ["lon_clean"])
    turb_alt_col = _prefer_first_col(df_turb, ["alt_meters"])
    turb_wdir_col = _prefer_first_col(df_turb, ["wind_dir"])
    turb_wspd_col = _prefer_first_col(df_turb, ["wind_speed"])

    cols = []
    amdar_select_cols = [c for c in [amdar_time_col, amdar_lat_col, amdar_lon_col, amdar_alt_col, amdar_wdir_col, amdar_wspd_col] if c]
    turb_select_cols = [c for c in [turb_time_col, turb_lat_col, turb_lon_col, turb_alt_col, turb_wdir_col, turb_wspd_col] if c]
    amdar_select_cols += ([amdar_flight_col] if amdar_flight_col and amdar_flight_col not in amdar_select_cols else [])
    turb_select_cols += ([turb_flight_col] if turb_flight_col and turb_flight_col not in turb_select_cols else [])

    df_wind_raw = pl.concat([
        df_amdar.select(amdar_select_cols).with_columns([
            pl.lit("amdar").alias("source"),
            pl.lit(float(SOURCE_CONFIDENCE["amdar"])).alias("obs_conf"),
            (pl.col(amdar_flight_col).cast(pl.Utf8, strict=False) if amdar_flight_col else pl.lit(None, dtype=pl.Utf8)).alias("wind_flight_id")
        ]),
        df_turb.select(turb_select_cols).with_columns([
            pl.lit("turb").alias("source"),
            pl.lit(float(SOURCE_CONFIDENCE["turb"])).alias("obs_conf"),
            (pl.col(turb_flight_col).cast(pl.Utf8, strict=False) if turb_flight_col else pl.lit(None, dtype=pl.Utf8)).alias("wind_flight_id")
        ])
    ])  # 合并两类风观测源并注入来源置信度
    
    wind_time_expr = _time_expr_prefer(df_wind_raw, ["time_utc"], ["%Y/%m/%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M", "%Y-%m-%d %H:%M"])
    wind_speed_expr = _clip_float(_safe_float_col(df_wind_raw, "wind_speed", default=None), 0.0, MAX_WIND_SPEED_MS)
    wind_dir_expr = _safe_float_col(df_wind_raw, "wind_dir", default=0.0)

    df_wind = df_wind_raw.with_columns([
        wind_time_expr.alias("time_utc"),
        (-wind_speed_expr * (wind_dir_expr * np.pi / 180).sin()).alias("u_wind"),
        (-wind_speed_expr * (wind_dir_expr * np.pi / 180).cos()).alias("v_wind"),
        _coord_expr_prefer(df_wind_raw, ["lat_clean"], []).alias("lat_clean"),
        _coord_expr_prefer(df_wind_raw, ["lon_clean"], []).alias("lon_clean"),
        _clip_float(_safe_float_col(df_wind_raw, "alt_meters", default=None), ALT_MIN, ALT_MAX).mul(ALT_MULTIPLIER).alias("alt_meters")
    ]).filter(
        pl.col("time_utc").is_not_null()
        & (pl.col("time_utc").dt.year() >= MIN_VALID_YEAR)
        & (pl.col("time_utc").dt.year() <= MAX_VALID_YEAR)
    ).drop_nulls(subset=["u_wind", "v_wind", "lat_clean", "lon_clean"])
    
    if LOC_BIGDATA_MODE:
        df_loc, loc_path = _load_location_bigdata(LOC_PARQUET_DIR_CANDIDATES + LOC_CANDIDATES)  # 新 parquet 优先，旧文件兜底
    else:
        df_loc, loc_path = _read_table(LOC_PARQUET_DIR_CANDIDATES + LOC_CANDIDATES)  # 新 parquet 优先，旧文件兜底
    print(f"   - LOC:   {loc_path}")  # 打印实际使用的航空器位置报文文件
    flight_col = _pick_first_existing_column(df_loc.columns, [
        "航班号", "航班编号", "航班", "航班代码", "航班ID", "航班识别码",
        "呼号", "呼号标识", "机号", "飞机号", "航空器识别码", "航空器ID", "ICAO",
    ])
    if flight_col is None:
        print("   - LOC 航班标识列未命中，使用行号作为临时 flight_id")
        flight_expr = (pl.lit("flight_") + pl.int_range(0, pl.len()).cast(pl.Utf8))
    else:
        print(f"   - LOC 航班标识列: {flight_col}")
        flight_expr = pl.col(flight_col).cast(pl.Utf8, strict=False)

    loc_time_expr = _time_expr_prefer(df_loc, ["time_utc"], ["%Y/%m/%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M", "%Y-%m-%d %H:%M"])
    loc_alt_expr = _clip_float(_safe_float_col(df_loc, "alt_meters", default=None), ALT_MIN, ALT_MAX).mul(ALT_MULTIPLIER)
    loc_heading_expr = _safe_float_col(df_loc, "heading_deg", default=None)
    loc_speed_expr = _clip_float(_safe_float_col(df_loc, "ground_speed_ms", default=None), 0.0, MAX_GROUND_SPEED_MS)

    df_loc = df_loc.with_columns([
        loc_time_expr.alias("time_utc"),
        _coord_expr_prefer(df_loc, ["lat_clean"], []).alias("lat_clean"),
        _coord_expr_prefer(df_loc, ["lon_clean"], []).alias("lon_clean"),
        loc_alt_expr.alias("alt_meters"),
        loc_heading_expr.alias("heading_deg"),
        loc_speed_expr.alias("ground_speed_ms"),
        flight_expr.alias("flight_id")
    ]).with_columns([
        (pl.col("ground_speed_ms") * (pl.col("heading_deg") * np.pi / 180).sin()).alias("u_motion"),
        (pl.col("ground_speed_ms") * (pl.col("heading_deg") * np.pi / 180).cos()).alias("v_motion")
    ]).filter(
        pl.col("time_utc").is_not_null()
        & (pl.col("time_utc").dt.year() >= MIN_VALID_YEAR)
        & (pl.col("time_utc").dt.year() <= MAX_VALID_YEAR)
    ).drop_nulls(subset=["lat_clean", "lon_clean", "flight_id"]) 
    
    print(f"✅ 数据清洗完毕！耗时: {time.time() - start_time:.2f} 秒\n")  # 打印清洗耗时
    return df_wind, df_loc  # 返回风观测表和轨迹表

# ==========================================
# 3. 批量循环处理雷达图，并生成 JSON
# ==========================================
def _process_frame_worker(args):
    (idx, total_files, radar_path, time_window_minutes, df_wind_sorted, df_loc_sorted, ground_lat, ground_lon, ground_alt, rt_tier2_max) = args
    t0 = time.time()
    filename = os.path.basename(radar_path)
    time_str = filename.split('_')[7]
    target_time = datetime.strptime(time_str, "%Y%m%d%H%M%S")
    time_start = target_time - timedelta(minutes=time_window_minutes)
    time_end = target_time + timedelta(minutes=time_window_minutes)

    radar_img = _read_gray_image_robust(radar_path)
    if radar_img is None:
        return None

    H_DIM, W_DIM = radar_img.shape
    DELTA_LAT = (LAT_MAX - LAT_MIN) / H_DIM
    DELTA_LON = (LON_MAX - LON_MIN) / W_DIM

    wind_frame = df_wind_sorted.filter((pl.col("time_utc") >= time_start) & (pl.col("time_utc") <= time_end))
    wind_frame = wind_frame.with_columns([
        ((pl.col("lon_clean") - LON_MIN) / DELTA_LON).cast(pl.Int32).alias("x"),
        ((LAT_MAX - pl.col("lat_clean")) / DELTA_LAT).cast(pl.Int32).alias("y"),
        ((pl.col("alt_meters") - ALT_MIN) / DELTA_ALT).cast(pl.Int32).alias("z")
    ]).filter(
        (pl.col("x") >= 0) & (pl.col("x") < W_DIM) & (pl.col("y") >= 0) & (pl.col("y") < H_DIM) & (pl.col("z") >= 0) & (pl.col("z") < Z_DIM)
    )

    wind_grouped = wind_frame.group_by(["z", "y", "x"]).agg([
        pl.col("u_wind").mean().alias("u"),
        pl.col("v_wind").mean().alias("v"),
        pl.len().alias("obs_count"),
        pl.col("obs_conf").mean().alias("obs_conf")
    ])
    amdar_grouped = wind_frame.filter(pl.col("source") == "amdar").group_by(["z", "y", "x"]).agg([
        pl.col("u_wind").mean().alias("u"),
        pl.col("v_wind").mean().alias("v")
    ])
    turb_grouped = wind_frame.filter(pl.col("source") == "turb").group_by(["z", "y", "x"]).agg([
        pl.col("u_wind").mean().alias("u"),
        pl.col("v_wind").mean().alias("v")
    ])

    loc_frame = df_loc_sorted.filter((pl.col("time_utc") >= time_start) & (pl.col("time_utc") <= time_end))
    loc_frame = loc_frame.with_columns([
        ((pl.col("lon_clean") - LON_MIN) / DELTA_LON).cast(pl.Int32).alias("x"),
        ((LAT_MAX - pl.col("lat_clean")) / DELTA_LAT).cast(pl.Int32).alias("y"),
        ((pl.col("alt_meters") - ALT_MIN) / DELTA_ALT).cast(pl.Int32).alias("z")
    ]).filter(
        (pl.col("x") >= 0) & (pl.col("x") < W_DIM) & (pl.col("y") >= 0) & (pl.col("y") < H_DIM) & (pl.col("z") >= 0) & (pl.col("z") < Z_DIM)
    )

    loc_grouped = loc_frame.group_by(["z", "y", "x"]).agg(pl.len().alias("density"))
    loc_motion_grouped = loc_frame.drop_nulls(subset=["u_motion", "v_motion"]).group_by(["z", "y", "x"]).agg([
        pl.col("u_motion").mean().alias("u_motion"),
        pl.col("v_motion").mean().alias("v_motion"),
        pl.len().alias("motion_count")
    ])
    flight_motion_grouped = loc_frame.drop_nulls(subset=["u_motion", "v_motion", "flight_id"]).group_by(["flight_id", "z", "y", "x"]).agg([
        pl.col("u_motion").mean().alias("u_motion"),
        pl.col("v_motion").mean().alias("v_motion"),
        pl.len().alias("motion_count")
    ])
    flight_raw_valid = loc_frame.drop_nulls(subset=["u_motion", "v_motion", "flight_id", "time_utc", "lat_clean", "lon_clean", "alt_meters"])

    amdar_ids_frame = set()
    if "wind_flight_id" in wind_frame.columns:
        for val in wind_frame.filter(pl.col("source") == "amdar").drop_nulls(subset=["wind_flight_id"])["wind_flight_id"].to_list():
            sval = str(val).strip()
            if sval:
                amdar_ids_frame.add(sval)

    recon_u, recon_v, recon_conf, recon_mask = _reconstruct_wind_field(
        Z_DIM, H_DIM, W_DIM, wind_grouped, loc_motion_grouped, amdar_grouped, turb_grouped
    )

    flight_pack_for_meta = build_flight_agents_sparse(
        flight_motion_grouped,
        flight_raw_valid,
        H_DIM,
        W_DIM,
        FLIGHT_AGENT_TOPK,
        target_time,
        ground_lat,
        ground_lon,
        ground_alt,
        amdar_flight_ids=amdar_ids_frame,
        tier2_max_override=rt_tier2_max,
        config={
            "COMM_TIME_LIMIT_SECONDS": COMM_TIME_LIMIT_SECONDS,
            "COMM_SPACE_LIMIT_KM": COMM_SPACE_LIMIT_KM,
            "COMM_VERTICAL_LIMIT_M": COMM_VERTICAL_LIMIT_M,
            "FF_COMM_TIME_LIMIT_SECONDS": FF_COMM_TIME_LIMIT_SECONDS,
            "FF_COMM_SPACE_LIMIT_KM": FF_COMM_SPACE_LIMIT_KM,
            "FF_COMM_VERTICAL_LIMIT_M": FF_COMM_VERTICAL_LIMIT_M,
            "FLIGHT_PREFER_COMM_ELIGIBLE": FLIGHT_PREFER_COMM_ELIGIBLE,
            "FLIGHT_TIER2_MAX": FLIGHT_TIER2_MAX,
            "COMM_ROUND": COMM_ROUND,
            "FF_MAX_NEIGHBORS_PER_AGENT": FF_MAX_NEIGHBORS_PER_AGENT,
            "PHYSICS_REALISM_MODE": PHYSICS_REALISM_MODE,
        },
        helpers={
            "haversine_km": _haversine_km,
            "eval_agent_geo": _eval_agent_geo,
            "linear_conf": _linear_conf,
            "time_likelihood": _time_likelihood,
            "space_likelihood": _space_likelihood,
            "blend_comm_weight": _blend_comm_weight,
            "compute_flight_intent": _compute_flight_intent,
            "ff_demand_score": _ff_demand_score,
            "ff_edge_score": _ff_edge_score,
            "zyx_to_linear_idx": _zyx_to_linear_idx,
            "select_ff_edges": select_ff_edges,
        },
    )
    comm_targets_frame = _build_comm_targets(wind_grouped, loc_motion_grouped, H_DIM, W_DIM)

    save_name = f"frame_{time_str}.npz"
    if NPZ_STORAGE_MODE == "sparse_lossless":
        _save_sparse_lossless_npz(
            os.path.join(OUTPUT_DIR_ABS, save_name),
            radar_img, H_DIM, W_DIM, Z_DIM, wind_grouped, loc_grouped, loc_motion_grouped, amdar_grouped, turb_grouped,
            flight_pack_for_meta, ground_lat, ground_lon, ground_alt,
        )

    return {
        "filename": save_name,
        "time_str": time_str,
        "valid_flight_agents": int(flight_pack_for_meta["valid_flight_agents"]),
        "wind_voxels": int(len(wind_grouped)),
        "traj_voxels": int(len(loc_grouped)),
        "recon_coverage_ratio": float(np.count_nonzero(recon_mask) / max(1, Z_DIM * H_DIM * W_DIM)),
        "flight_comm_eligible_ratio": float(flight_pack_for_meta.get("comm_eligible_ratio", 0.0)),
        "flight_ff_edge_density": float(flight_pack_for_meta.get("ff_edge_density", 0.0)),
        "runtime_tier2_max": int(rt_tier2_max),
        "frame_elapsed": float(time.time() - t0),
        "timestamp_utc": target_time.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def batch_process(df_wind, df_loc):
    radar_files = []
    for pattern in RADAR_PATTERNS:
        if os.path.isabs(pattern):
            search_patterns = [pattern]
        else:
            # 优先扫描 DATA_ROOT（默认 20260224），避免混入其他日期数据
            search_patterns = [os.path.join(DATA_ROOT, pattern)]

        for search_pattern in search_patterns:
            radar_files.extend(glob.glob(search_pattern, recursive=True))  # 按候选模式搜雷达图
    radar_files = sorted(set(radar_files))  # 去重并排序

    if MAX_FRAMES is not None:
        radar_files = radar_files[:MAX_FRAMES]  # 限制处理帧数，防止一次任务过重

    total_files = len(radar_files)  # 雷达图总数
    
    if total_files == 0:  # 若没有输入雷达文件则直接返回
        print("❌ 当前目录下未找到任何 Z_RADA_ 开头的雷达图片！")
        return

    print(f"🚀 [2/3] 找到 {total_files} 张雷达图，启动流水线处理...")  # 打印阶段进度

    loc_min_time = df_loc["time_utc"].min() if len(df_loc) > 0 else None
    loc_max_time = df_loc["time_utc"].max() if len(df_loc) > 0 else None
    if OVERLAP_ONLY and loc_min_time is not None and loc_max_time is not None:
        before = len(radar_files)
        filtered = []
        for rp in radar_files:
            fn = os.path.basename(rp)
            try:
                ts = fn.split('_')[7]
                t = datetime.strptime(ts, "%Y%m%d%H%M%S")
            except Exception:
                continue
            if loc_min_time <= t <= loc_max_time:
                filtered.append(rp)
        radar_files = filtered
        total_files = len(radar_files)
        print(f"   - OVERLAP_ONLY=1，按 LOC 时间覆盖过滤: {before} -> {total_files} 帧")
    print(
        f"   - 低占用参数: MAX_FRAMES={MAX_FRAMES}, BATCH_SIZE={BATCH_SIZE}, "
        f"BATCH_PAUSE_SECONDS={BATCH_PAUSE_SECONDS}, SAVE_COMPRESSED={SAVE_COMPRESSED}, "
        f"NPZ_STORAGE_MODE={NPZ_STORAGE_MODE}"
    )
    if AUTO_FRIENDLY_MODE:
        print(
            f"   - 自动友好模式: AUTO_MIN_FREE_MEM_GB={AUTO_MIN_FREE_MEM_GB}, "
            f"AUTO_MAX_EXTRA_PAUSE_SECONDS={AUTO_MAX_EXTRA_PAUSE_SECONDS}"
        )
    
    # ★ 新增：用于存储整个数据集元数据的列表
    dataset_metadata = []  # 每处理一帧，追加一条元数据记录
    ground_lat = (LAT_MIN + LAT_MAX) * 0.5
    ground_lon = (LON_MIN + LON_MAX) * 0.5
    ground_alt = 0.0

    # 预排序（避免每帧重复 group_by）可显著降低批处理开销
    df_wind_sorted = df_wind.sort("time_utc") if len(df_wind) > 0 else df_wind
    df_loc_sorted = df_loc.sort("time_utc") if len(df_loc) > 0 else df_loc
    frame_process_seconds = []

    # 运行时监控状态
    rt_tier2_max = FLIGHT_TIER2_MAX
    recent_valid_agents = []
    recent_wind_ok = []
    monitor_events = []

    tasks = [
        (idx, total_files, radar_path, TIME_WINDOW_MINUTES, df_wind_sorted, df_loc_sorted, ground_lat, ground_lon, ground_alt, rt_tier2_max)
        for idx, radar_path in enumerate(radar_files)
    ]

    use_mp = int(os.environ.get("WIND_MP_WORKERS", "0")) > 1 and len(tasks) > 1
    results = []
    if use_mp:
        workers = int(os.environ.get("WIND_MP_WORKERS", "4"))
        with ProcessPoolExecutor(max_workers=workers) as ex:
            futs = [ex.submit(_process_frame_worker, t) for t in tasks]
            for fut in as_completed(futs):
                res = fut.result()
                if res is not None:
                    results.append(res)
        results.sort(key=lambda x: x["time_str"])
    else:
        for t in tasks:
            res = _process_frame_worker(t)
            if res is not None:
                results.append(res)

    for idx, res in enumerate(results):
        dataset_metadata.append({
            "frame_id": idx,
            "filename": res["filename"],
            "timestamp_utc": res["timestamp_utc"],
            "valid_flight_agents": res["valid_flight_agents"],
            "valid_wind_voxels": res["wind_voxels"],
            "valid_traj_voxels": res["traj_voxels"],
            "recon_coverage_ratio": res["recon_coverage_ratio"],
            "flight_comm_eligible_ratio": res["flight_comm_eligible_ratio"],
            "flight_ff_edge_density": res["flight_ff_edge_density"],
            "runtime_tier2_max": res["runtime_tier2_max"],
        })
        frame_process_seconds.append(res["frame_elapsed"])
        if PROGRESS_EVERY <= 1 or (idx + 1) % PROGRESS_EVERY == 0 or (idx + 1) == len(results):
            print(
                f"[{idx+1:04d}/{len(results)}] ✅ 生成: {res['time_str']} | 风体素: {res['wind_voxels']} "
                f"| 轨迹体素: {res['traj_voxels']} | 有效飞行智能体: {res['valid_flight_agents']} "
                f"| 耗时: {res['frame_elapsed']:.2f}s"
            )

    # ★ 新增：所有图片跑完后，生成全局 JSON 文件
    print("\n🚀 [3/3] 正在生成数据集索引 JSON 文件...")  # 打印阶段进度
    json_path = os.path.join(OUTPUT_DIR_ABS, "dataset_metadata.json")  # JSON 索引输出路径
    
    frame_times = np.array(frame_process_seconds, dtype=np.float64) if frame_process_seconds else np.array([], dtype=np.float64)
    perf_summary = {
        "frame_count_measured": int(frame_times.size),
        "frame_time_sec_mean": float(frame_times.mean()) if frame_times.size > 0 else 0.0,
        "frame_time_sec_p50": float(np.percentile(frame_times, 50)) if frame_times.size > 0 else 0.0,
        "frame_time_sec_p90": float(np.percentile(frame_times, 90)) if frame_times.size > 0 else 0.0,
        "frame_time_sec_max": float(frame_times.max()) if frame_times.size > 0 else 0.0,
    }

    global_info = {
        "dataset_name": "Aviation_Wind_Radar_3D_Dataset",  # 数据集名称
        "generated_at": datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ"),  # 生成时间（UTC）
        "schema_version": "2.1",
        "spatial_config": {
            "bbox_lon": [LON_MIN, LON_MAX],  # 经度边界
            "bbox_lat": [LAT_MIN, LAT_MAX],  # 纬度边界
            "altitude_meters": {"min": ALT_MIN, "max": ALT_MAX, "delta": DELTA_ALT, "layers": Z_DIM}  # 高度配置
        },
        "total_frames": len(dataset_metadata),  # 总帧数
        "performance": perf_summary,
        "runtime_config": {
            "ablation_profile": ABLATION_PROFILE,
            "physics_realism_mode": PHYSICS_REALISM_MODE,
            "max_frames": MAX_FRAMES,
            "batch_size": BATCH_SIZE,
            "batch_pause_seconds": BATCH_PAUSE_SECONDS,
            "save_compressed": SAVE_COMPRESSED,
            "npz_storage_mode": NPZ_STORAGE_MODE,
            "ground_speed_to_mps": GROUND_SPEED_TO_MPS,
            "source_confidence": SOURCE_CONFIDENCE,
            "export_agent_views": EXPORT_AGENT_VIEWS,
            "ground_agent": {
                "id": GROUND_AGENT_ID,
                "type": GROUND_AGENT_TYPE,
                "lat": ground_lat,
                "lon": ground_lon,
                "alt_m": ground_alt
            },
            "comm_topk_ratio": COMM_TOPK_RATIO,
            "comm_min_topk": COMM_MIN_TOPK,
            "comm_wind_weight": COMM_WIND_WEIGHT,
            "comm_motion_weight": COMM_MOTION_WEIGHT,
            "flight_agent_topk": FLIGHT_AGENT_TOPK,
            "flight_agent_max": FLIGHT_AGENT_MAX,
            "flight_tier2_max": FLIGHT_TIER2_MAX,
            "comm_round": COMM_ROUND,
            "ff_max_neighbors_per_agent": FF_MAX_NEIGHBORS_PER_AGENT,
            "comm_time_limit_seconds": COMM_TIME_LIMIT_SECONDS,
            "comm_space_limit_km": COMM_SPACE_LIMIT_KM,
            "comm_vertical_limit_m": COMM_VERTICAL_LIMIT_M,
            "ff_comm_time_limit_seconds": FF_COMM_TIME_LIMIT_SECONDS,
            "ff_comm_space_limit_km": FF_COMM_SPACE_LIMIT_KM,
            "ff_comm_vertical_limit_m": FF_COMM_VERTICAL_LIMIT_M,
            "time_likelihood_sigma_seconds": TIME_LIKELIHOOD_SIGMA_SECONDS,
            "space_likelihood_sigma_km": SPACE_LIKELIHOOD_SIGMA_KM,
            "space_likelihood_sigma_z_m": SPACE_LIKELIHOOD_SIGMA_Z_M,
            "comm_weight_components": {
                "time_conf": COMM_WEIGHT_TIME_CONF,
                "space_conf": COMM_WEIGHT_SPACE_CONF,
                "time_likelihood": COMM_WEIGHT_TIME_LIKE,
                "space_likelihood": COMM_WEIGHT_SPACE_LIKE,
                "wind_bonus": COMM_WEIGHT_WIND_BONUS
            },
            "quality_guard": {
                "max_wind_speed_ms": MAX_WIND_SPEED_MS,
                "max_ground_speed_ms": MAX_GROUND_SPEED_MS,
                "valid_year_range": [MIN_VALID_YEAR, MAX_VALID_YEAR]
            },
            "auto_friendly_mode": AUTO_FRIENDLY_MODE,
            "auto_min_free_mem_gb": AUTO_MIN_FREE_MEM_GB,
            "auto_max_extra_pause_seconds": AUTO_MAX_EXTRA_PAUSE_SECONDS
        },  # 运行配置
        "monitor": {
            "enabled": ENABLE_REALTIME_MONITOR,
            "window": MONITOR_WINDOW,
            "target_flight_min": TARGET_FLIGHT_MIN,
            "target_flight_max": TARGET_FLIGHT_MAX,
            "tier2_max_bounds": [TIER2_MAX_MIN, TIER2_MAX_MAX],
            "events": monitor_events,
        },
        "frames": dataset_metadata  # 每帧元数据清单
    }
    
    with open(json_path, "w", encoding="utf-8") as f:  # 以 UTF-8 打开 JSON 文件
        json.dump(global_info, f, indent=4, ensure_ascii=False)  # 写出格式化 JSON，保留中文

    split_source = dataset_metadata
    if FILTER_LOW_QUALITY_FOR_SPLIT:
        # 仅剔除“双零帧”：风观测=0 且 运动观测=0。
        # 只要任一观测存在（风>0 或 运动>0）就保留，避免过度删样本。
        split_source = [
            x for x in dataset_metadata
            if x.get("valid_wind_voxels", 0) > 0 or x.get("valid_motion_voxels", 0) > 0
        ]
        print(f"   - 低质量样本过滤（剔除风=0且运动=0）: {len(dataset_metadata)} -> {len(split_source)}")

    split_info = _build_time_contiguous_splits(split_source)

    train_set = set(split_info.get("train", []))
    train_frames = [x for x in split_source if x.get("filename") in train_set]
    train_weighted = _build_weighted_train_filenames(train_frames) if WIND_RESAMPLE_ENABLE else list(split_info.get("train", []))

    adaptive_min_obs = 1
    obs_totals = np.array([int(max(0, x.get("valid_wind_voxels", 0))) for x in split_source], dtype=np.int64)
    if ADAPTIVE_MIN_OBS_ENABLE and obs_totals.size > 0:
        q = float(np.clip(ADAPTIVE_MIN_OBS_QUANTILE, 0.0, 0.9))
        qv = int(np.quantile(obs_totals, q))
        adaptive_min_obs = int(max(1, min(ADAPTIVE_MIN_OBS_CAP, qv)))

    split_path = os.path.join(OUTPUT_DIR_ABS, "dataset_split.json")
    with open(split_path, "w", encoding="utf-8") as f:
        split_payload = {
            "schema_version": "2.3",
            "strategy": "day_block_time_contiguous",
            "ratios": {
                "train": SPLIT_RATIOS[0],
                "val": SPLIT_RATIOS[1],
                "test": SPLIT_RATIOS[2]
            },
            "counts": {
                "train": len(split_info["train"]),
                "train_weighted": len(train_weighted),
                "val": len(split_info["val"]),
                "test": len(split_info["test"])
            },
            "boundaries": {
                "train": {
                    "first": split_info["train"][0] if split_info["train"] else None,
                    "last": split_info["train"][-1] if split_info["train"] else None,
                },
                "val": {
                    "first": split_info["val"][0] if split_info["val"] else None,
                    "last": split_info["val"][-1] if split_info["val"] else None,
                },
                "test": {
                    "first": split_info["test"][0] if split_info["test"] else None,
                    "last": split_info["test"][-1] if split_info["test"] else None,
                },
            },
            "day_groups": split_info.get("day_groups", {"train": [], "val": [], "test": []}),
            "day_frame_counts": split_info.get("day_frame_counts", {}),
            "splits": {
                "train": split_info.get("train", []),
                "train_weighted": train_weighted,
                "val": split_info.get("val", []),
                "test": split_info.get("test", []),
            },
            "recommendations": {
                "adaptive_min_obs": adaptive_min_obs,
                "resample": {
                    "enabled": bool(WIND_RESAMPLE_ENABLE),
                    "alpha": WIND_RESAMPLE_ALPHA,
                    "min_repeat": WIND_RESAMPLE_MIN_REPEAT,
                    "max_repeat": WIND_RESAMPLE_MAX_REPEAT,
                },
            },
        }
        json.dump(split_payload, f, indent=4, ensure_ascii=False)

    print(f"🎉 全部处理完毕！数据集目录已保存为: {json_path}")  # 打印完成信息
    print(f"📦 训练切分文件已保存为: {split_path}")

if __name__ == "__main__":  # 脚本入口
    df_w, df_l = load_global_data()  # 先读取并清洗全局数据
    batch_process(df_w, df_l)  # 再逐帧处理雷达图并输出数据集