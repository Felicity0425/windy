# Stage5 full-ROI 背景对比 demo 说明

## 这份文档的作用

这份文档记录一次和旧版 comparison 明确不同的 `Stage5` 小 demo：

```text
不再只比较 shared 250 points
而是：
1. 把 Stage5 当前帧全部 sparse refined voxels 完整展示出来
2. 把 ERA5 背景场在同一 ROI bbox 内的整块背景裁片完整展示出来
3. 再把 ERA5 采到全部 Stage5 sparse points 上，量化 Stage5 与 ERA5 的差异
```

这个 demo 的结果目录是：

```text
/data/LFT-W02_data/pengxu/stage5_visualizations/stage5_full_roi_background_demo
```

当前已新增 v3 structured 目录：

```text
/data/LFT-W02_data/pengxu/stage5_visualizations/stage5_full_roi_background_demo_v3_structured
```

新增脚本是：

- [report_stage5_full_roi_background_demo.py](/data/LFT-W02_data/pengxu/stage/report_stage5_full_roi_background_demo.py:1)

---

## 一、它和旧 comparison 的区别

旧 comparison，也就是：

```text
stage5_internal_bg_test_comparison
```

的设计目标是：

- 公平对齐
- 只看同一批共享点
- 便于直接目测 `Stage4 / Stage5 / background`

所以它的特点是：

1. 只保留 `Stage4` 和 `Stage5` 的交集点
2. 再从中挑 `N=250`
3. 背景也只在这 250 个点上采样

因此旧 comparison 回答的问题是：

```text
在同一批共享支撑点上，Stage4、Stage5 和背景看起来有什么差别？
```

而这次 `full-ROI demo` 回答的问题不同：

1. 你的 `Stage5` 当前帧一共保留了多少 sparse refined voxels？
2. ERA5 在同一 ROI bbox 内的完整背景场长什么样？
3. 如果把 ERA5 采到全部 Stage5 sparse 点上，数值到底差多少？

所以它更适合回答：

```text
我的 Stage5 和外部背景场，在“全部 Stage5 sparse ROI 点”这个口径下，到底差多大？
```

---

## 二、当前 demo 结果文件

### 1. 20260129114200

- [20260129114200_stage5_full_vs_background_full_roi.png](/data/LFT-W02_data/pengxu/stage5_visualizations/stage5_full_roi_background_demo/20260129114200_stage5_full_vs_background_full_roi.png)
- [20260129114200_stage5_minus_background_full_sparse.png](/data/LFT-W02_data/pengxu/stage5_visualizations/stage5_full_roi_background_demo/20260129114200_stage5_minus_background_full_sparse.png)
- [20260129114200_full_roi_demo_summary.json](/data/LFT-W02_data/pengxu/stage5_visualizations/stage5_full_roi_background_demo/20260129114200_full_roi_demo_summary.json)

### 2. 20260206174200

- [20260206174200_stage5_full_vs_background_full_roi.png](/data/LFT-W02_data/pengxu/stage5_visualizations/stage5_full_roi_background_demo/20260206174200_stage5_full_vs_background_full_roi.png)
- [20260206174200_stage5_minus_background_full_sparse.png](/data/LFT-W02_data/pengxu/stage5_visualizations/stage5_full_roi_background_demo/20260206174200_stage5_minus_background_full_sparse.png)
- [20260206174200_full_roi_demo_summary.json](/data/LFT-W02_data/pengxu/stage5_visualizations/stage5_full_roi_background_demo/20260206174200_full_roi_demo_summary.json)

### 3. v3 structured

新的 structured 版本结果目录：

```text
/data/LFT-W02_data/pengxu/stage5_visualizations/stage5_full_roi_background_demo_v3_structured
```

关键文件：

- [20260129114200_full_roi_demo_summary.json](/data/LFT-W02_data/pengxu/stage5_visualizations/stage5_full_roi_background_demo_v3_structured/20260129114200_full_roi_demo_summary.json)
- [20260206174200_full_roi_demo_summary.json](/data/LFT-W02_data/pengxu/stage5_visualizations/stage5_full_roi_background_demo_v3_structured/20260206174200_full_roi_demo_summary.json)

---

## 三、图怎么读

### 1. 左右两栏图

文件名：

```text
*_stage5_full_vs_background_full_roi.png
```

左栏表示：

```text
当前帧 Stage5 的全部 sparse refined voxels
```

右栏表示：

```text
ERA5 在同一 Stage5 ROI bbox 内的整块背景裁片
```

这里的“整块背景裁片”有两个重点：

1. 它不是旧 comparison 里的 `shared 250 points`
2. 它是按 `Stage5 bbox_zyx` 对应的经纬高范围，把整个背景 ROI 都裁出来

也就是说，右栏现在更接近“这块背景场本身长什么样”，而不是“背景在 250 个共享点上长什么样”。

### 2. 差值图

文件名：

```text
*_stage5_minus_background_full_sparse.png
```

它表示：

```text
在 Stage5 当前帧全部 sparse voxels 上，
Stage5 相对 ERA5 的向量差
```

这里仍然不是“背景全体素减 Stage5 全体素”，因为你当前 `Stage5` 还是 sparse 输出。  
所以差值统计是在：

```text
全部 Stage5 sparse points
```

上完成的。

### 3. v3 之后的变化

v3 之后，full-ROI demo 不再只输出“原始背景差异”，而是同时输出：

```text
raw background
scaled background
```

其中：

- `raw`：直接用原始 ERA5 背景值
- `scaled`：先读取 `Stage5 summary` 中的 `background_speed_scale`，再对背景 `u/v` 做缩放

因此现在 full-ROI demo 和 Stage5 summary 的口径已经统一，不会再出现：

```text
Stage5 summary 看起来改善了
但 full-ROI demo 数值没动
```

这种表面矛盾。

---

## 四、当前两帧数值结果分析

### 1. 20260129114200

来自：

- [20260129114200_full_roi_demo_summary.json](/data/LFT-W02_data/pengxu/stage5_visualizations/stage5_full_roi_background_demo/20260129114200_full_roi_demo_summary.json)

关键结果：

```text
Stage5 sparse voxels                     = 443
Stage5 speed mean                        ≈ 0.354
ERA5 speed mean on Stage5 points         ≈ 8.576
vector RMSE on Stage5 points             ≈ 10.093
vector diff mean on Stage5 points        ≈ 8.402
vector diff p90 on Stage5 points         ≈ 12.416
```

### 这一帧怎么解释

这一帧上，`Stage5` 和 ERA5 的差异非常大，而且不是一点点偏差，是风速量级就已经明显不同：

- `Stage5` 平均风速只有 `0.35`
- ERA5 在相同这些点上的平均风速约 `8.58`

这说明什么：

1. 在这帧上，`Stage5` 当前保留的是一个非常保守、非常弱风的 sparse ROI 结果；
2. ERA5 给出的背景场在这同一批位置上要强得多；
3. 两者之间不是“有一点不同”，而是明显不在一个量级上。

因此，这一帧不能说：

```text
Stage5 只是和 ERA5 稍微不同
```

而应该说：

```text
Stage5 和 ERA5 在这帧上的差异非常大
```

但还要再强调一句：

这说明的是：

```text
Stage5 与 ERA5 背景差得大
```

不是：

```text
Stage5 与真实真值一定差得大
```

因为 ERA5 仍然只是背景场，不是真值。

### 1.1 20260129114200 的 v3 结果

v3 structured summary：

```text
background_speed_scale                  ≈ 0.3054
raw_background_speed_mean_on_stage5_points     ≈ 8.5763
raw_vector_rmse_on_stage5_points               ≈ 10.0953
scaled_background_speed_mean_on_stage5_points  ≈ 2.6194
scaled_vector_rmse_on_stage5_points            ≈ 3.1721
scaled_vector_diff_mean_on_stage5_points       ≈ 2.5134
```

这说明：

1. 这帧的主要问题确实是背景风速量级过大；
2. 在保持 `anchor_rmse_after` 与 `heldout_anchor_rmse_after` 不恶化的前提下，
3. 仅仅做背景速度缩放，就能把 full-ROI demo 的背景 RMSE 从约 `10.10` 压到约 `3.17`。

因此：

```text
20260129114200 = 典型的幅值失配帧
```

### 1.2 20260206174200 的 v3 结果

v3 structured summary：

```text
background_speed_scale                  ≈ 1.0587
raw_background_speed_mean_on_stage5_points     ≈ 27.2055
raw_vector_rmse_on_stage5_points               ≈ 18.3423
scaled_background_speed_mean_on_stage5_points  ≈ 28.8031
scaled_vector_rmse_on_stage5_points            ≈ 18.7720
scaled_vector_diff_mean_on_stage5_points       ≈ 13.2537
```

这说明：

1. 这帧的原始背景和 Stage5 在风速量级上本来就比较接近；
2. 强行做速度缩放以后，full-ROI demo 反而略差；
3. 所以这帧的问题不是幅值失配，而是方向和局部结构冲突。

因此：

```text
20260206174200 = 典型的结构/方向冲突帧
```

### 2. 20260206174200

来自：

- [20260206174200_full_roi_demo_summary.json](/data/LFT-W02_data/pengxu/stage5_visualizations/stage5_full_roi_background_demo/20260206174200_full_roi_demo_summary.json)

关键结果：

```text
Stage5 sparse voxels                     = 406
Stage5 speed mean                        ≈ 25.000
ERA5 speed mean on Stage5 points         ≈ 27.205
vector RMSE on Stage5 points             ≈ 18.414
vector diff mean on Stage5 points        ≈ 13.023
vector diff p90 on Stage5 points         ≈ 32.540
```

### 这一帧怎么解释

这一帧比上一帧更复杂。

从平均风速看：

- `Stage5 ≈ 25.0`
- `ERA5 ≈ 27.2`

表面上看，两者量级是接近的。  
但向量 RMSE 反而更大，到了 `18.41`，而且 `p90 ≈ 32.54`。

这说明：

1. 这一帧并不是“整体强度不对”；
2. 更可能是方向、局部结构、局部速度梯度差异很大；
3. 也就是说它的问题不是单纯“偏强 / 偏弱”，而是：

```text
风场结构本身和 ERA5 差得更厉害
```

这和它本来就是高风险帧是一致的：

- 当前帧在 `Stage5 summary` 里：
  - `anchor_rmse_after ≈ 0.0834`
  - `heldout_anchor_rmse_after ≈ 0.5360`
  - `delta_speed_expanded_mean ≈ 17.97`

说明这帧本身就是一个不稳定、变化剧烈、背景和局地 anchor 更容易冲突的场景。

---

## 五、和现有 Stage5 summary 结合起来看

如果只看 `Stage5 summary`，你能看到：

### 20260129114200

```text
anchor_rmse_after              ≈ 0.0249
heldout_anchor_rmse_after      ≈ 0.0349
background_vector_rmse         ≈ 9.8799
background_speed_bias          ≈ -8.1786
delta_speed_mean               ≈ 0.0134
```

这说明：

- 它保住了本地 anchor；
- 但和背景差距大。

### 20260206174200

```text
anchor_rmse_after              ≈ 0.0834
heldout_anchor_rmse_after      ≈ 0.5360
background_vector_rmse         ≈ 17.6434
background_speed_bias          ≈ -0.6812
delta_speed_mean               ≈ 6.2470
delta_speed_expanded_mean      ≈ 17.9704
```

这说明：

- 它本地就更不稳定；
- 和背景差异也更大；
- 扩展区变化尤其大。

把 `full-ROI demo` 和 `Stage5 summary` 放在一起之后，结论就更清楚了：

1. `20260129114200`
   - 本地结果很稳；
   - 但整体上和 ERA5 差得非常大；
   - 所以这是一帧“稳，但和背景不一致”的帧。

2. `20260206174200`
   - 本地结果本身就更激烈；
   - 背景和它的差异更像结构性差异；
   - 所以这是一帧“高风险、结构冲突大”的帧。

### 补充：v3 structured 对 Stage5 summary 的影响

当前 v3 structured `stage5_summary.json` 在：

- [stage5_summary.json](/data/LFT-W02_data/pengxu/stage5_output_v1_internal_bg_test_v3_structured/stage5_summary.json)

关键变化：

#### 20260129114200

```text
background_vector_rmse            ≈ 3.1530
direction_consistency_mean_after  ≈ 0.0113
delta_speed_expanded_mean         ≈ 0.0137
```

相较旧版：

- `background_vector_rmse` 大幅下降
- `anchor_rmse_after` 与 `heldout_anchor_rmse_after` 保持不恶化

#### 20260206174200

```text
background_vector_rmse            ≈ 17.7760
direction_consistency_mean_after  ≈ 0.3845
delta_speed_expanded_mean         ≈ 17.9511
```

相较旧版：

- `background_vector_rmse` 仅小幅变化
- `heldout_anchor_rmse_after` 没有明显改善
- 但 `delta_speed_expanded_mean` 没有明显变差

这说明：

```text
v3 对弱场帧有效；
对高风险强场帧主要是“更可解释”，而不是“显著变好”。
```

---

## 六、这个 demo 最重要的价值

这次 `full-ROI demo` 最重要的价值，不是图更好看，而是把一个之前比较模糊的问题说清楚了：

```text
Stage5 和 ERA5 到底差多大？
```

旧 comparison 会让人产生一种错觉：

- 因为三栏点位对齐；
- 因为点数只取 250；
- 看起来像是在做“形态比较”；
- 但不容易直接感觉出“整体差多少”。

而 `full-ROI demo` 做了两件更硬的事：

1. 右栏不再只显示 250 个共享点，而是把整块 ROI 背景裁片显示出来；
2. 数值上明确计算：
   - 全部 Stage5 sparse points 上的背景对比
   - 均值
   - RMSE
   - p90

所以这个 demo 更适合回答：

```text
如果把 ERA5 当背景参照，我的 Stage5 当前到底离它有多远？
```

---

## 七、当前应该怎么表述这两个结果

当前最稳妥的表述是：

### 对 20260129114200

> 这一帧 Stage5 在 anchor 保真上表现很好，但它与 ERA5 背景场在同一批 sparse ROI 点上的差异很大，说明当前结果更接近一个保守的局地 sparse refinement，而不是接近 ERA5 大尺度背景。

### 对 20260206174200

> 这一帧 Stage5 与 ERA5 在平均风速量级上更接近，但向量差和结构差异更大，说明这是一帧典型的高风险、高冲突场景，Stage5 与背景场之间的偏差主要不是幅值问题，而是结构和方向问题。

---

## 八、后续建议

这次 `full-ROI demo` 跑完之后，最值得继续做的有三件事：

1. 对 `historical GFS` 也跑同样的 full-ROI demo  
   当前这次用的是 `ERA5`。  
   由于 `Stage5 summary` 里实际选中的背景源是 `historical GFS`，下一步很自然应该对 `GFS` 也跑一版同口径全量 ROI 对比。

2. 明确“背景场差异大”不等于“Stage5 一定错误”  
   需要继续强调：
   - 背景场不是局地真值；
   - 它只是先验和参照。

3. 如果要进一步判断“谁更接近真实”，必须补独立验证
   - 探空
   - 风廓线雷达
   - 地面风
   - 机场观测
   - 雷达体扫 / 径向速度

否则现在最多能说：

```text
Stage5 与 ERA5 / GFS 差多少
```

还不能说：

```text
Stage5 与真实真值差多少
```
