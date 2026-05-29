# Stage5 internal_bg_test 输出与可视化详细解说

## 这份文档的作用

这份文档专门解释下面两组结果：

1. `Stage5` 输出目录

```text
/data/LFT-W02_data/pengxu/stage5_output_v1_internal_bg_test
```

2. `Stage4 / Stage5 / background` 对比图目录

```text
/data/LFT-W02_data/pengxu/stage5_visualizations/stage5_internal_bg_test_comparison
```

它的目的不是解释代码实现细节，而是告诉后续接手的人：

- 图里每个点表示什么
- 点的颜色表示什么
- 箭头表示什么
- 三栏图和差值图各自想表达什么
- 哪些地方最容易被误读

如果需要看“不只比较 shared 250 points，而是把 Stage5 全部 sparse ROI 点与整块 ERA5 ROI 背景裁片直接对比”的版本，请继续看：

- `stage/handover_stage45_20260507/21_stage5_full_roi_background_demo_explained.md`

如果需要看已经统一 raw/scaled 口径、并加入结构化背景约束后的版本，也继续看：

- `stage5_output_v1_internal_bg_test_v3_structured`
- `stage5_visualizations/stage5_internal_bg_test_comparison_v3_structured`
- `stage5_visualizations/stage5_full_roi_background_demo_v3_structured`

---

## 一、当前结果是什么

这次 `internal_bg_test` 是一组 `Stage5` 小样本测试，关键帧有两帧：

```text
20260129114200
20260206174200
```

正式 summary 在：

- [stage5_summary.json](/data/LFT-W02_data/pengxu/stage5_output_v1_internal_bg_test/stage5_summary.json)

对比图 summary 在：

- [comparison_summary.json](/data/LFT-W02_data/pengxu/stage5_visualizations/stage5_internal_bg_test_comparison/comparison_summary.json)

当前这组测试的定位是：

```text
Stage5 ROI refinement + 多背景候选 + internal Stage5 temporal background 候选
```

补充：

- 当前已新增 v3 structured 版本；
- v3 不改变这份文档讲图的基本口径；
- 但在数值解释上要额外区分：
  - raw background
  - scaled background
  - 结构化背景约束后的 Stage5 结果

这里的 `internal background` 指的是：

- 把上一帧 `Stage5` 输出恢复成一个可采样的背景场候选
- 再和 `ERA5 / historical GFS / MERRA-2` 这类外部背景一起做候选比较

但这次两帧测试里，最终被选中的主背景仍然是：

```text
historical GFS
```

不是 `internal Stage5 background`。

这一点很重要，因为它说明：

- 内部时序背景已经接进流程了；
- 但它并不是天然更优；
- 仍然要和当前帧 anchor 的一致性比较之后才能决定是否采用。

---

## 二、Stage5 单帧 3D 图怎么读

这类图来自目录：

```text
/data/LFT-W02_data/pengxu/stage5_output_v1_internal_bg_test
```

当前文件包括：

- [01376_20260129114200_stage5_roi_3d.png](/data/LFT-W02_data/pengxu/stage5_output_v1_internal_bg_test/01376_20260129114200_stage5_roi_3d.png)
- [03338_20260206174200_stage5_roi_3d.png](/data/LFT-W02_data/pengxu/stage5_output_v1_internal_bg_test/03338_20260206174200_stage5_roi_3d.png)

这些图由：

- [stage5_pinn_diffusion_refine.py](/data/LFT-W02_data/pengxu/stage/stage5_pinn_diffusion_refine.py:986)

中的 `_render_stage5_3d_png()` 生成。

### 1. 图里的点表示什么

图里的每一个点，表示一个：

```text
Stage5 refined sparse voxel
```

也就是：

- 它不是原始观测点；
- 也不是全国满场网格；
- 而是 `Stage5` 在当前 ROI 中保留下来的非空 refined 体素点。

更具体地说，这些点来自：

- `refined_idx`
- `refined_u_val`
- `refined_v_val`
- `refined_conf_val`

也就是说，图中每个点都对应一个真正输出到 `frame_<time>_stage5.npz` 里的 sparse voxel。

### 2. 点的颜色表示什么

在 `Stage5 ROI 3D 图` 里，点的颜色表示：

```text
refined confidence
```

对应代码里是：

- 使用 `plasma` colormap
- 颜色条标题是 `refined confidence`

颜色越接近亮黄 / 浅色，表示：

- refined confidence 越高

颜色越接近深紫 / 暗色，表示：

- refined confidence 越低

所以这张图里颜色不是风速，也不是危险程度，而是：

**当前 Stage5 对这个 refined voxel 的置信度。**

### 3. 点的大小表示什么

点大小也和置信度有关。

代码里是：

```text
s = 18 + 34 * clip(conf, 0, 1)
```

也就是说：

- 置信度越高，点越大；
- 置信度越低，点越小。

所以在 `Stage5 ROI 3D 图` 里，点的“颜色和大小”都在重复表达同一件事：

```text
这个点有多可信
```

### 4. 箭头表示什么

箭头表示：

```text
该 voxel 的水平风向与相对风速方向
```

更准确地说：

- 箭头来自 `u` 和 `v`
- 先计算风速 `speed = sqrt(u^2 + v^2)`
- 再按相对速度做缩放

因此箭头的作用是：

- 表示风向；
- 同时给出一个“经过可视化缩放后的相对长度”。

它不是绝对风速尺，也不是原始物理长度直接按米/秒画出来。

所以讲图时要明确：

**箭头长度只是为了读图，不要把它直接当成真实速度标尺。**

### 5. 坐标轴表示什么

这张图的三轴含义是：

- `Longitude (deg)`
- `Latitude (deg)`
- `Altitude (km)`

所以它已经不是抽象网格坐标，而是：

**在当前固定中国区域 bbox 下映射出来的经纬高三维视图。**

---

## 三、三栏 comparison 图怎么读

这类图来自目录：

```text
/data/LFT-W02_data/pengxu/stage5_visualizations/stage5_internal_bg_test_comparison
```

当前文件包括：

- [20260129114200_stage4_stage5_background_3d.png](/data/LFT-W02_data/pengxu/stage5_visualizations/stage5_internal_bg_test_comparison/20260129114200_stage4_stage5_background_3d.png)
- [20260206174200_stage4_stage5_background_3d.png](/data/LFT-W02_data/pengxu/stage5_visualizations/stage5_internal_bg_test_comparison/20260206174200_stage4_stage5_background_3d.png)

这些图由：

- [report_stage5_background_comparison.py](/data/LFT-W02_data/pengxu/stage/report_stage5_background_comparison.py:327)

生成。

### 1. 三栏分别是什么

从左到右三栏分别是：

1. `Stage4 sparse reconstruction`
2. `Stage5 ROI refinement`
3. `ERA5/GFS ROI background`

注意第三栏虽然标签里写的是 `ERA5/GFS ROI background`，但具体使用了哪一个背景，要看：

- [comparison_summary.json](/data/LFT-W02_data/pengxu/stage5_visualizations/stage5_internal_bg_test_comparison/comparison_summary.json)

当前这组 comparison 图里记录的是：

- `background_path = .../era5_roi_20260129114200.nc`
- `background_path = .../era5_roi_20260206174200.nc`

也就是说：

**comparison 图这次右栏显示的是 ERA5 背景采样结果。**

这和 `Stage5 summary` 里真正选中的 refinement 背景源不是同一个字段，后面会单独解释。

### 2. 这三栏图里的点表示什么

三栏图中的所有点都不是“各自原始全集”，而是：

```text
Stage4 和 Stage5 共享 sparse support 上的同一批点
```

代码里叫：

```text
shared_stage4_stage5_intersection
```

也就是说：

- 先取 `Stage4` 非空点；
- 再取 `Stage5` 非空点；
- 只保留两者交集；
- 最后背景场也只在这同一批点上采样。

这件事非常关键，因为它保证了：

**三栏图比较的是同一批空间位置，而不是三种完全不同采样密度的点云。**

### 3. 三栏图里的点颜色表示什么

在三栏图中，点的颜色表示：

```text
speed
```

不是 confidence。

代码里：

- 使用 `turbo` colormap
- `color_key = "speed"`

所以这里颜色的含义是：

- 颜色越偏暖，表示该点水平风速越大；
- 颜色越偏冷，表示该点水平风速越小。

### 4. 三栏图里的点大小表示什么

三栏图中的点大小仍然和 `conf` 有关：

```text
s = 14 + 18 * clip(conf, 0, 1)
```

因此：

- 点越大，表示这个点在该栏里的置信度越高；
- 点越小，表示置信度越低。

但要特别注意：

- 第三栏背景场的 `conf` 是人为设成常数 `0.55`
- 所以背景栏点大小基本没有真实概率含义，只是为了让图能统一画出来

也就是说：

**第三栏背景点的大小不要过度解读。**

### 5. 三栏图里的箭头表示什么

三栏图的箭头表示：

```text
每一栏对应风场的水平风向与经过缩放后的相对速度方向
```

和单独 `Stage5 ROI 3D 图` 一样：

- 箭头方向有意义；
- 相对长短有参考意义；
- 但绝对长度不应直接当成真实速度标尺。

### 6. 三栏图标题里的 `N=250` 是什么

标题里的：

```text
N=250
```

表示当前三栏图里最终画出来的共享点数量。

当前 comparison summary 里也写了：

```text
shared_points = 250
```

所以：

- 这不是该帧真实全部 sparse 点数；
- 而是为了可视化可读性，取了共享支持上的前 250 个代表点。

---

## 四、`Stage5 - background` 差值图怎么读

当前差值图包括：

- [20260129114200_stage5_minus_background_3d.png](/data/LFT-W02_data/pengxu/stage5_visualizations/stage5_internal_bg_test_comparison/20260129114200_stage5_minus_background_3d.png)
- [20260206174200_stage5_minus_background_3d.png](/data/LFT-W02_data/pengxu/stage5_visualizations/stage5_internal_bg_test_comparison/20260206174200_stage5_minus_background_3d.png)

这类图是最容易被误读，但其实最有诊断价值的一类图。

### 1. 图里的点表示什么

这些点仍然是：

```text
共享 sparse support 上的同一批点
```

并不是新的点集。

### 2. 点的颜色表示什么

这里颜色表示：

```text
|Stage5 - background| 的向量差幅值
```

更准确地说，是：

```text
sqrt(du^2 + dv^2)
```

其中：

- `du = stage5_u - background_u`
- `dv = stage5_v - background_v`

所以：

- 颜色越亮，表示 `Stage5` 和背景差得越大；
- 颜色越暗，表示两者更接近。

### 3. 箭头表示什么

箭头不是 `Stage5` 的绝对风向，也不是背景的绝对风向，而是：

```text
Stage5 相对于 background 的风矢量差方向
```

也就是说，箭头在回答的问题是：

> 在这个点上，Stage5 相比 background，偏向哪个方向、偏了多少。

这类图非常适合解释：

- `Stage5` 是不是只是在机械复制背景；
- 或者它是否在某些区域显著偏离背景。

### 4. 这类图该怎么讲

讲解差值图时，建议这样说：

1. 如果差值整体很小：
   - 说明 `Stage5` 在这些共享点上和背景接近；
   - 但不代表一定更好，只能说明两者相似。

2. 如果差值局部很大：
   - 说明 `Stage5` 在这些局部点上明显没有跟着背景走；
   - 可能是 anchor 主导的局地修正；
   - 也可能是风险帧里 refinement 不稳定。

所以差值图不能单独下结论，必须和 `stage5_summary.json` 里的指标一起看。

---

## 五、哪些字段最容易被混淆

这组结果里，有几个最容易被混淆的地方，需要单独强调。

### 1. `background_selected_path` 和 `background_path` 不是一回事

`Stage5 summary` 里的：

```text
background_selected_path
```

表示：

```text
Stage5 精炼逻辑真正选中的背景候选源
```

当前两帧里，它选中的是：

```text
historical GFS
```

而 `comparison_summary.json` 里的：

```text
background_path
```

表示：

```text
当前 comparison 图右栏实际显示的是哪一个背景文件
```

当前两帧里，右栏显示的是：

```text
ERA5
```

因此：

**不要把图右栏显示的背景，误认为是 Stage5 内部真正采用的背景源。**

### 2. `background_available=1` 不代表背景一定有帮助

它只表示：

```text
当前帧确实成功加载了背景场并参与计算
```

并不表示：

- 背景一定和 anchor 一致；
- 背景一定提升了结果；
- 背景一定比内部时序背景更好。

### 3. `background_consistency_score=0` 代表什么

当前两帧里，这个值是 `0`，说明：

- 背景与当前 anchor 的冲突比较大；
- 在一致性门控里，它并没有被认为“和本地锚点相容”。

但由于当前候选里其他背景也更差，所以它依然可能被选成“相对最不差”的背景。

这说明：

```text
背景被选中 != 背景很好
```

而是：

```text
在当前候选里，它是相对更不差的那一个
```

---

## 六、当前两帧图各自想表达什么

### 1. `20260129114200`

这是一帧相对稳的帧。

从 `stage5_summary.json` 看：

- `anchor_rmse_after ≈ 0.0249`
- `heldout_anchor_rmse_after ≈ 0.0349`
- `delta_speed_mean ≈ 0.0134`

这说明：

- `Stage5` 在这帧上几乎没有破坏原始 anchor；
- refinement 非常保守；
- 更适合拿来说明：

```text
弱背景先验没有把局地主结果冲坏
```

### 2. `20260206174200`

这是一帧风险更高的帧。

从 `stage5_summary.json` 看：

- `hazard` 本来就强
- `anchor_rmse_after ≈ 0.0834`
- `heldout_anchor_rmse_after ≈ 0.5360`
- `delta_speed_expanded_mean ≈ 17.97`

这说明：

- 这帧上 Stage5 的扩展区变化非常大；
- 背景和局地 anchor 的冲突更明显；
- 更适合拿来说明：

```text
高风险帧里，背景不能硬融，只能弱引导
```

---

## 七、建议的讲图口径

如果你要给别人讲这组图，建议固定下面这套口径。

### 对单独 Stage5 ROI 图

可以这样讲：

> 图中的点是 Stage5 输出的 sparse ROI refined voxels；颜色和点大小都表示 refined confidence；箭头表示水平风向和经过缩放后的相对速度方向；这不是全国满场风场，而是局地稀疏 refinement 结果。

### 对三栏 comparison 图

可以这样讲：

> 左中右三栏分别是 Stage4、Stage5 和背景场，但它们是在同一批共享 sparse support 点上比较的。点颜色表示风速，点大小表示置信度，箭头表示水平风向。右栏不是本项目真值，而是外部背景场在同一批点上的采样结果。

### 对差值图

可以这样讲：

> 差值图显示的是 Stage5 相比背景场的向量差。点颜色越亮，表示两者在该点差得越大；箭头表示这种差异的方向。它主要用于判断 Stage5 是否只是机械地复制背景，还是在局地 anchor 驱动下做了自己的修正。

---

## 八、最重要的边界提醒

最后有三条边界一定要反复强调：

1. `Stage5 ROI 图` 里的点不是原始观测点，而是 refined sparse voxels。
2. `comparison` 右栏背景图不是本项目真值，只是背景先验 / 对照。
3. `Stage5 summary` 里真正选中的背景源，与 comparison 图右栏显示的背景源不是同一个字段，不能混用。
