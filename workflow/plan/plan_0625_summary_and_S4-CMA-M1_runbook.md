# centralized_v1 执行摘要 + S4-CMA-M1 详细操作手册（2026-06-25）

> 配套 `plan_0625_executable.md`。本文 = 一页执行摘要 + 第一个实验 `S4-CMA-M1` 的逐步 runbook。

---

# 第一部分：一页执行摘要

## 现状一句话
默认主线 `tp26_thr11_preserve` 稳定但卡在高空 tail。误差 76% 来自 12km+，且 93% 是不可约表示误差，不是模型不够大。

## 三条红线（每步适用）
```
1. 真值只有 current aircraft wind strict holdout; strict_holdout_no_leakage=True
2. CMA/motion/radar 永不当真值; 背景填充区不进官方 RMSE
3. 一次一个实验; smoke(200)打穿即停, 不进 formal(5614)
```

## 两道门（数值对照）
```
smoke 200帧:  weighted RMSE 14.769 / P95 27.986 / P99 58.784 / 12km+ 19.918 / light 5.196 / floor10 0.283  —— 候选须全部 ≤
formal 5614帧: weighted RMSE 14.520 / P95 31.783 / P99 73.325 / 12km+ 17.585 / light 5.511 / floor10 0.255  —— 候选须全部 ≤
值得升默认: 还须 weighted RMSE 改善≥0.05  或  ≥2 目标层改善≥5%
```

## 执行顺序（按此推进）
```
第0步 前置:  P0-FRAME(txt→json) · P0-LEAK(CRA40独立性) · P0-CMA(GRIB校验) · P0-FLOOR(误差地板)
第1步 ★立即: S4-CMA-M1   零风险, 交付"完整场+低置信标注", 官方指标须==baseline
第2步:       S4-OI-DIAG  innovation/obs_influence report-only, 不改 recon
第3步:       S4-OI-1a/1b R分层膨胀 + B各向异性(先 oi_diag_approx)
第4步:       S4-OI-1c/1d CRA40背景OI + Desroziers校准(数学按修正版)
第5步:       按失败层选 S4-B(localization) / S4-C(时间) / S4-vert(垂直,强制report先行) / S4-E(tail gate)
第6步:       Stage4 过gate后才重抽 Stage5 dataset
第7步:       S5-A UQ弃改 + S5-B稳定化; plateau→S5-D observation-informed架构
```

## 分支线（按失败层选下一个实验）
```
count_0/count_1/dist_ge6  → S4-OI-1a + CMA背景
gap_ge30/role_conflict    → S4-B
timeconf_0.4-0.6          → S4-C
vertical_structure        → S4-vert (report-only先行)
tail 非 mean              → S4-E
```

## 已死方向（不得重复）
```
SRHA / sparse_temporal_cma / guarded_vertical / point_regime / rep_soft_weight(5614 FAIL) / Stage5 alt12_scale>0
```

## 相对原 plan_0625 的 4 个关键纠正
```
1. rep soft-weight 已 5614 FAIL → 不延续, 改 OI 的 R 建模
2. Desroziers O-A/O-B 数学写错 → 需背景x_b与分析x_a两个不同量 + 背景独立性
3. 各向异性扩散非"极低风险" → 垂直干预历史全失败, 强制 report-only
4. LETKF 自由调半径 → 改 3 套受约束 kernel family
```

---

# 第二部分：S4-CMA-M1 详细操作手册

> 目标：用 CRA40 弱背景做 **display-only 兜底填充**，交付"完整风场 + 逐格点低置信标注"，
> 且 **official holdout 指标必须与 baseline 完全一致**（M1 不碰 official recon）。
> 这是风险最低、最快出产品的一步，第一个做。

## 0. 前置条件（必须先完成）
```
[ ] P0-FRAME 已生成 FRAMES200_JSON
[ ] P0-CMA   已确认 CMA_DIR 的 GRIB 可读、含 WIU/WIV、与 200 帧时间有交集，用户手册：https://data.cma.cn/article/showPDFFile.html?file=/pic/static/doc/cra/%E4%B8%AD%E5%9B%BD%E6%B0%94%E8%B1%A1%E5%B1%80%E5%85%A8%E7%90%83%E5%A4%A7%E6%B0%94%EF%BC%8F%E9%99%86%E9%9D%A2%E5%86%8D%E5%88%86%E6%9E%90%E4%BA%A7%E5%93%81%EF%BC%88CMA-RA%EF%BC%89%E7%94%A8%E6%88%B7%E6%89%8B%E5%86%8C.pdf
[ ] P0-LEAK  对 M1 非阻塞(填充区不进 holdout, 天然免疫); 但仍要记录独立性结论备 OI 用
```

## 1. 固定变量（每个命令前 export）
```bash
PY=/data/LFT-W02_data/pengxu/.conda/envs/windy310/bin/python
ROOT=/data/LFT-W02_data/pengxu   # 按实际项目根调整
cd $ROOT
STAGE2=centralized_v1_output/stage2_full_v2/stage2_multimodal_summary.json
STAGE3=centralized_v1_output/stage3_full_v2_25w_payload_only/stage3_center_summary.json
FRAMES200_JSON=centralized_v1_output/stage4_guardrail_display_fill_200_20260605_25w/tp26_thr11_preserve_metrics/stage4_validation_frame_times.json
CMA_DIR=/data/LFT-W02_data/pengxu/cma
CMA_BG_DIR=centralized_v1_output/stage4_cma_background_v1
M1_OUT=centralized_v1_output/stage4_cma_m1_fill_200_20260625
```

## 2. Step 1 — 生成每帧 CRA40 背景 NPZ
```bash
$PY stage/centralized_v1/core/centralized_cma_ra_virtual_radial_3dvar.py \
  --cma-dir $CMA_DIR --stage2-summary $STAGE2 \
  --frame-times-file $FRAMES200_JSON \
  --cma-time-method linear_qc \
  --aircraft-anchor-mode stage4_train_wind \
  --stage4-holdout-fraction 0.125 --stage4-holdout-count 0 \
  --out-dir $CMA_BG_DIR --num-workers 12
```
**检查**
```
[ ] $CMA_BG_DIR 下生成 cma_ra_virtual_radial_3dvar_<frame>.npz, 数量 = 有背景的帧数(可少于200, 记录缺背景帧)
[ ] 抽1个npz确认含 u_cma_3d/v_cma_3d/cma_temporal_conf_3d, 形状 31x525x775, 非全 NaN
```
若某些帧时刻落在 CRA40 覆盖(2026-01-23~02-24)之外 → 该帧无背景，M1 不填，记录数量即可。

## 3. Step 2 — Stage4 display-only 兜底填充
```bash
$PY stage/centralized_v1/core/centralized_stage4_ground_recon.py \
  --stage2-summary $STAGE2 --stage3-summary $STAGE3 \
  --frame-times-file $FRAMES200_JSON \
  --cma-fusion-mode off \
  --display-fill-mode low_conf_background \
  --display-fill-cma-proxy-dir $CMA_BG_DIR \
  --display-fill-source cma_reanalysis \
  --display-fill-confidence-cap 0.20 \
  --display-fill-qc-gating strict_temporal \
  --out-dir $M1_OUT
```
关键：`--cma-fusion-mode off` 保证 official recon 完全不动；CMA 只进 `display_*` 字段。

## 4. Step 3 — 验收（产品门，非 RMSE 门）

### 4.1 硬约束：官方指标必须 == baseline
```bash
# 与 baseline tp26 的 point_departures / metrics 对比, 必须逐项完全相等
$PY - <<'PY'
import pandas as pd, numpy as np
base="centralized_v1_output/<tp26_baseline_200>/stage4_point_departures.csv"   # 填真实 baseline 路径
cand="centralized_v1_output/stage4_cma_m1_fill_200_20260625/stage4_point_departures.csv"
b=pd.read_csv(base).sort_values("point_id").reset_index(drop=True)
c=pd.read_csv(cand).sort_values("point_id").reset_index(drop=True)
col="vector_error"   # 或实际误差列名
diff=np.abs(b[col].values-c[col].values).max()
print("max abs diff:", diff)
print("PASS (M1 不动 official)" if diff < 1e-9 else "FAIL — 有 bug, 误填了观测点!")
PY
```
```
判定:
  if max abs diff < 1e-9: PASS, M1 正确(未碰 official recon)
  else: STOP — display fill 误改了 official 场, 排查 _make_display_filled_field 是否写回了 recon_u/v
```

### 4.2 产品价值检查
```bash
$PY - <<'PY'
import numpy as np, glob, os, json
# 抽1帧输出 npz, 检查 display 字段
f=sorted(glob.glob("centralized_v1_output/stage4_cma_m1_fill_200_20260625/*.npz"))[0]
d=np.load(f, allow_pickle=True)
src=d["C4_DISPLAY_SOURCE"] if "C4_DISPLAY_SOURCE" in d else d["display_source_3d"]
conf=d["C4_DISPLAY_CONF"] if "C4_DISPLAY_CONF" in d else d["display_conf_3d"]
print("source 取值:", np.unique(src))                       # 期望 {0/1=官方重构, 2=CRA40填充}
fill=(src==2)
print("背景填充区 conf max:", np.nanmax(conf[fill]) if fill.any() else "no fill")  # 期望 <=0.20
print("官方重构区占比:", (src==1).mean(), " 背景填充区占比:", fill.mean())
PY
```
```
[ ] display_source: official_mask 内=1, 背景填充区=2
[ ] 背景填充区 display_conf <= 0.20, 与观测区明显可分
[ ] 全场覆盖率(source>0) 接近 100% (CRA40 覆盖范围内)
```

### 4.3 可视化抽查（可选但推荐给老师看）
```
- 画一张切片图: 观测重构区正常饱和度, 背景填充区降饱和度/加阴影, 标 "background-filled, low confidence"
- 复用 centralized_report_stage4_slices.py, 增加 display_source 着色
```

## 5. 产出与记录
```
[ ] $M1_OUT/promotion_checklist.json: 记录 frame list 路径、baseline csv、官方指标 diff、display 覆盖率
[ ] 缺背景帧数 + CRA40 时间覆盖交集统计
[ ] 一句话结论: "M1 在官方指标零变化前提下, 将产品覆盖率提升到 ~X%, 背景区以 conf<=0.2 显式标注"
```

## 6. if/else 决策
```
if 4.1 官方指标 != baseline:
    STOP, 修 display fill bug (绝不能让背景进 official recon)
elif 4.2/4.3 全过:
    M1 完成 → 产品需求(完整场+低置信标注)已满足
    → 进 S4-OI-DIAG (用 innovation 诊断背景是否值得做 OI)
elif CRA40 时间覆盖与 200 帧交集太少(如 <50%):
    先扩展 CRA40 数据时段, 或换覆盖更全的背景源, 再重跑 Step1
```

## 7. 论文可写句（M1 完成后）
> centralized_v1 在保持 strict aircraft holdout official accuracy 不变的前提下，新增 CRA40 弱背景 display-fill 产品层，
> 以 `display_source` 和低置信度显式区分观测重构区与背景填充区，从而把"完整产品图"与"已验证精度足迹"分离。

---

## 附：S4-CMA-M1 一图流
```
P0(frame/leak/cma/floor) ─→ Step1 CRA40背景NPZ ─→ Step2 display-fill ─┐
                                                                       │
        ┌──────────────────────────────────────────────────────────────┘
        ▼
   验收4.1 官方==baseline? ──no──→ STOP 修bug(误填official)
        │yes
        ▼
   验收4.2/4.3 source/conf/覆盖率OK? ──no──→ 调 confidence-cap / qc-gating 重跑
        │yes
        ▼
   产品需求达成 ─→ 进 S4-OI-DIAG
```
</content>
