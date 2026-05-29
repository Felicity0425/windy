# Stage5 vs GFS 两组关键帧汇报讲稿版

## 这份文档的用途

这份文档不是代码实现说明，而是面向组会、答辩或对外展示的“可直接念”讲稿版。  
它专门整理当前已经跑通的两组 `Stage5` vs 历史 `GFS` 关键帧对比结果：

- `20260129114200`
- `20260206174200`

其中：

- `20260129114200` 是相对稳的帧，适合讲“背景先验没有破坏主结果”
- `20260206174200` 是高风险帧，适合讲“背景不能直接硬融，只能弱引导”

这份讲稿只基于当前本地已经跑出的结果，不要求再次重绘或改主链代码。

---

## 图源与脚本入口

### 1. Stage5 refine 脚本

- [stage5_pinn_diffusion_refine.py](/data/LFT-W02_data/pengxu/stage/stage5_pinn_diffusion_refine.py:945)

### 2. GFS 背景场 3D 可视化脚本

- [report_stage5_background_field.py](/data/LFT-W02_data/pengxu/stage/report_stage5_background_field.py:143)

### 3. Stage4 / Stage5 / GFS 三栏对比脚本

- [report_stage5_background_comparison.py](/data/LFT-W02_data/pengxu/stage/report_stage5_background_comparison.py:310)

### 4. 本次结果目录

无背景 tuned 结果：

```text
/data/LFT-W02_data/pengxu/stage5_output_v1_demo_tuned_no_background_keyframes
```

带历史 GFS 弱先验结果：

```text
/data/LFT-W02_data/pengxu/stage5_output_v1_demo_tuned_historical_gfs_keyframes
```

历史 GFS 背景场 3D 图：

```text
/data/LFT-W02_data/pengxu/stage5_visualizations/stage5_vs_gfs_tuned_background
```

共享 sparse support 的三栏对比图：

```text
/data/LFT-W02_data/pengxu/stage5_visualizations/stage5_vs_gfs_tuned_keyframes
```

---

## 先把结论讲清楚

### 1. 当前 Stage5 逻辑对不对

当前 `Stage5` 的逻辑是对的，但前提是要把它理解成：

```text
局地稀疏风场 refinement + 背景弱先验引导
```

而不是：

```text
把 GFS 直接并成最终结果
```

当前代码里，背景场只在两处进入：

1. expanded ROI 的初始化混合
2. 非 anchor 区域的轻量 relax 引导

直接对应代码位置在：

- [stage5_pinn_diffusion_refine.py](/data/LFT-W02_data/pengxu/stage/stage5_pinn_diffusion_refine.py:655)
- [stage5_pinn_diffusion_refine.py](/data/LFT-W02_data/pengxu/stage/stage5_pinn_diffusion_refine.py:673)

也就是说，当前逻辑本来就不是“硬融合”，而是弱先验。

### 2. GFS 能不能直接和 Stage5 合并

不能直接硬合并。

原因不是 GFS 错，而是它的角色不同：

- `Stage5`：局地 sparse anchor 主导的 ROI refinement
- `GFS`：大尺度 pressure-level 背景场

两者的空间分辨率、时间对齐粒度、物理角色都不一样。  
当前更稳妥的口径是：

```text
Stage5 保持主导，GFS 只作为背景弱先验与对照，不直接拼成单一真值结果。
```

### 3. GFS 是不是正确数据

是正确的大尺度背景资料，但不是局地风场真值。

更准确地说：

- 历史 `GFS archive` 对应的时间对齐是正确的
- 但它仍然是整点 cycle + forecast hour 的模式背景
- 不是分钟级、局地航空观测意义上的真值

所以不能把它直接当成：

```text
Stage5 局地风场的标准答案
```

### 4. Stage5 还有没有优化空间

有，而且主要是三类空间：

1. 参数层优化
   - 背景权重
   - diffusion/pinn 强度
   - original delta cap
   - 高风险帧保守模式

2. 融合策略优化
   - 让背景只在低置信区和扩张区发挥作用
   - 避免背景过早影响强 anchor 区

3. 数据层优化
   - 引入更多局地观测
   - 用更高分辨率模式背景
   - 如果未来能接入局地真值类数据，再做更强监督

---

## 本次 tuned 弱先验参数

本次两帧统一采用的弱先验参数是：

```bash
--background-init-weight 0.12
--background-relax-weight 0.02
--background-data-weight 0.20
--diffusion-strength 0.18
--pinn-strength 0.022
--anchor-preserve 0.94
--original-delta-cap 1.0
--hazard-conservative
--iterations 4
--local-expand-iters 1
--max-expand-voxels 1000
```

这套参数的目的不是让 `Stage5` 更像 `GFS`，而是：

- 保住 anchor fidelity
- 让背景只做弱引导
- 在高风险帧避免过度扩散

---

## 关键帧 1：20260129114200

### 这组图的角色

这是当前最适合讲“背景不破坏主结果”的稳帧。

### 结果指标

无背景 tuned：

- `refined_voxels = 443`
- `anchor_rmse_after ≈ 0.0249`
- `heldout_anchor_rmse_after ≈ 0.0349`

带历史 GFS tuned：

- `refined_voxels = 443`
- `anchor_rmse_after ≈ 0.0249`
- `heldout_anchor_rmse_after ≈ 0.0349`
- `background_vector_rmse ≈ 9.75`
- `background_speed_bias ≈ -8.03`

### 图路径

无背景 Stage5：

- [01376_20260129114200_stage5_roi_3d.png](/data/LFT-W02_data/pengxu/stage5_output_v1_demo_tuned_no_background_keyframes/01376_20260129114200_stage5_roi_3d.png)

带历史 GFS 背景 Stage5：

- [01376_20260129114200_stage5_roi_3d.png](/data/LFT-W02_data/pengxu/stage5_output_v1_demo_tuned_historical_gfs_keyframes/01376_20260129114200_stage5_roi_3d.png)

GFS 背景自身：

- [gfs_roi_20260129114200_background_3d.png](/data/LFT-W02_data/pengxu/stage5_visualizations/demo_historical_gfs_20260129114200_background/gfs_roi_20260129114200_background_3d.png)

三栏对比：

- [20260129114200_stage4_stage5_background_3d.png](/data/LFT-W02_data/pengxu/stage5_visualizations/stage5_vs_gfs_tuned_keyframes/20260129114200_stage4_stage5_background_3d.png)

差值图：

- [20260129114200_stage5_minus_background_3d.png](/data/LFT-W02_data/pengxu/stage5_visualizations/stage5_vs_gfs_tuned_keyframes/20260129114200_stage5_minus_background_3d.png)

### 无背景 Stage5 可直接念

先看这张无背景 `Stage5` 图，可以看到它是在 `Stage4` 的 sparse 局地结构上继续做 refinement。  
这里最重要的是，它并没有把结果大面积铺开，而是仍然保留了几个局地结构簇和一条高层主结构。  
它的 `anchor_rmse_after` 和 `heldout_anchor_rmse_after` 都很低，说明这张图最大的优点是“保住了 anchor”。  
所以这张图先要传达的不是“更满”，而是“更稳”。

### 带历史 GFS 背景 Stage5 可直接念

再看带 `GFS` 背景的 `Stage5`，它的整体形态和无背景版本很接近，说明背景并没有把主结构拉偏。  
两个版本在 `anchor_rmse_after` 和 `heldout_anchor_rmse_after` 上几乎一样，这正是我们希望看到的结果。  
也就是说，在稳帧里，`GFS` 可以作为背景先验参与进来，但不会破坏局地观测主导的结构。  
所以这张图适合讲“弱先验是能接进去的，但它不是来替代 Stage5 的”。

### GFS 背景图可直接念

这张 `GFS` 背景图看起来更规整，因为它本质上是规则 pressure-level 背景格点。  
它展示的是大尺度三维风场先验，而不是我们最终要交付的局地 sparse reconstruction。  
所以这张图不能和 Stage5 一一对位去比较“谁更对”，它更像是给局地 refinement 提供一个大气背景框架。  
这也是为什么我们说 `GFS` 是正确背景，但不是局地真值。

### 三栏对比图可直接念

这张三栏图把 `Stage4`、`Stage5` 和背景场放在同一批共享 sparse support 点上比较，所以它已经避免了不同点集硬比的偏差。  
这里最重要的观察是，`Stage5` 和 `Stage4` 的主结构保持一致，但 `Stage5` 在局地上更平滑、更像 refinement，而不是完全贴向背景。  
右侧背景栏虽然规整，但它和中间 `Stage5` 的局地结构并不是一模一样的，这正说明我们没有在做硬合并。  
所以这张图最适合一句话总结：背景参与了，但主结果还是 Stage5 自己的。

### 差值图可直接念

这张 `Stage5 - background` 差值图里仍然能看到系统性的结构残差，说明 `Stage5` 并没有被 `GFS` 吃掉。  
如果差值图几乎一片零，那才说明我们只是把背景场抄了一遍；现在显然不是这样。  
因此这张图反而是一个正面证据，说明 Stage5 保留了局地观测驱动下的独立修正。  
这也是我们坚持“弱先验融合”而不是“硬合并”的原因。

### 这组图最适合承担的角色

这组图最适合在汇报里承担“说明 GFS 可以作为背景先验接入，但不会破坏稳帧主结果”的角色。

---

## 关键帧 2：20260206174200

### 这组图的角色

这是当前最适合讲“高风险帧里背景不能直接硬融”的反例帧。

### 结果指标

无背景 tuned：

- `refined_voxels = 406`
- `anchor_rmse_after ≈ 0.0680`
- `heldout_anchor_rmse_after ≈ 0.5293`

带历史 GFS tuned：

- `refined_voxels = 406`
- `anchor_rmse_after ≈ 0.0677`
- `heldout_anchor_rmse_after ≈ 0.5081`
- `background_vector_rmse ≈ 17.54`
- `background_speed_bias ≈ -0.68`

### 图路径

无背景 Stage5：

- [03338_20260206174200_stage5_roi_3d.png](/data/LFT-W02_data/pengxu/stage5_output_v1_demo_tuned_no_background_keyframes/03338_20260206174200_stage5_roi_3d.png)

带历史 GFS 背景 Stage5：

- [03338_20260206174200_stage5_roi_3d.png](/data/LFT-W02_data/pengxu/stage5_output_v1_demo_tuned_historical_gfs_keyframes/03338_20260206174200_stage5_roi_3d.png)

GFS 背景自身：

- [gfs_roi_20260206174200_background_3d.png](/data/LFT-W02_data/pengxu/stage5_visualizations/stage5_vs_gfs_tuned_background/gfs_roi_20260206174200_background_3d.png)

三栏对比：

- [20260206174200_stage4_stage5_background_3d.png](/data/LFT-W02_data/pengxu/stage5_visualizations/stage5_vs_gfs_tuned_keyframes/20260206174200_stage4_stage5_background_3d.png)

差值图：

- [20260206174200_stage5_minus_background_3d.png](/data/LFT-W02_data/pengxu/stage5_visualizations/stage5_vs_gfs_tuned_keyframes/20260206174200_stage5_minus_background_3d.png)

### 无背景 Stage5 可直接念

先看这张高风险帧的无背景 `Stage5`，可以看到高层结构非常强，而且局地主结构已经很明显。  
但它的 `heldout_anchor_rmse_after` 也明显高于稳帧，说明这不是一张可以轻松处理的样本。  
也就是说，这一帧的价值就在于它是“难帧”，不是为了展示 Stage5 看起来很漂亮。  
这张图的关键词是“风险结构很强，但局地约束也更难平衡”。

### 带历史 GFS 背景 Stage5 可直接念

再看带 `GFS` 背景的版本，整体主结构并没有崩掉，这说明弱先验策略至少没有把图拉坏。  
但它和稳帧不一样，虽然 `anchor_rmse_after` 和 `heldout_anchor_rmse_after` 稍微有改善，`background_vector_rmse` 仍然很大。  
这说明在高风险帧里，背景先验和局地 anchor 之间天然可能存在冲突，不能指望简单融合就“自动更对”。  
所以这里最重要的结论是：高风险帧必须保守地用背景，只能弱引导，不能硬贴合。

### GFS 背景图可直接念

这张 `GFS` 背景图在高层上也有很明显的规则结构，但它是模式背景的格点场，不是局地航空观测真值。  
从视觉上看，它比 Stage5 更平整、更整齐，这恰恰是模式背景和局地结果之间的典型差别。  
所以不能因为它看起来更规整，就把它当成局地结果的标准答案。  
这张图最适合帮助听众理解：背景场“正确”，不等于“局地上必须完全贴合”。

### 三栏对比图可直接念

这张三栏图里，左边是 `Stage4`，中间是 `Stage5`，右边是共享点集上采样的 `GFS` 背景。  
可以看到，`Stage5` 和 `Stage4` 保持了局地主结构的一致性，但右边背景场在一些位置和中间结果差异仍然明显。  
这说明 Stage5 的目标不是把局地结构洗成背景，而是在 anchor 主导下做局地 refinement。  
所以这张图最适合讲“为什么我们不能直接把 GFS 拼进结果里当成最终答案”。

### 差值图可直接念

差值图在这帧上更有说服力，因为它显示出来的不是零星小差别，而是沿着高层主结构持续存在的系统性偏差。  
如果现在直接做硬合并，这些真正由局地观测支持出来的差异就会被背景场抹平。  
因此这张图其实是在告诉我们：高风险帧最应该保住 anchor-led 结构，而不是追求“和 GFS 看起来更像”。  
这也是为什么我们把它定义成“反例帧”，专门用来说明不能硬融。

### 这组图最适合承担的角色

这组图最适合在汇报里承担“说明高风险帧里 GFS 只能弱引导，不能直接硬合并”的角色。

---

## Stage5 和 GFS 的最终口径

### 可以直接念的版本

当前 `Stage5` 的正确定位，是以局地 sparse anchors 为主导的 ROI refinement，`GFS` 只提供大尺度背景先验。  
`GFS` 是正确的背景资料，但它不是局地风场真值，所以不能直接拿来和 `Stage5` 硬合并成单一结果。  
在稳帧上，背景参与可以不破坏主结构；在高风险帧上，背景仍然可能和局地 anchor 冲突，所以只能保守使用。  
因此当前最合理的策略不是“把 Stage5 变成 GFS”，而是“让 GFS 成为 Stage5 的弱先验背景”。

---

## Stage5 还有哪些优化空间

### 1. 参数层

当前最现实、最稳的优化空间仍然是参数层：

- 更细的 `background_init_weight`
- 更细的 `background_relax_weight`
- 更细的 `background_data_weight`
- 针对高风险帧单独收紧 `original_delta_cap`
- 针对高风险帧进一步降低 diffusion / PINN 强度

### 2. 融合策略层

下一步最值得做的不是“更强融合”，而是“更聪明的弱融合”：

- 只在 expanded ROI 用背景
- 只在低置信区用背景
- 对 direct anchors 周边做更强屏蔽
- 根据背景一致性动态调权

### 3. 数据层

如果未来要真正接近“局地真值”，最重要的不是继续提高 GFS 权重，而是引入更多局地约束：

- 更多航空风观测
- 探空 / 风廓线
- 地面站风
- 多仰角雷达三维产品
- 更高分辨率区域模式背景

---

## 汇报推荐顺序

### 3图精简版

如果时间很短，只讲这三部分：

1. `20260129114200_stage4_stage5_background_3d.png`
   - 说明背景不会破坏稳帧主结果
2. `20260206174200_stage4_stage5_background_3d.png`
   - 说明高风险帧不能硬融
3. `20260206174200_stage5_minus_background_3d.png`
   - 用差值图直接证明“Stage5 没有被 GFS 吃掉”

### 5图完整版

如果时间更充分，推荐按这个顺序讲：

1. `20260129114200` 无背景 Stage5
2. `20260129114200` 三栏对比
3. `20260206174200` 无背景 Stage5
4. `20260206174200` 三栏对比
5. `20260206174200` 差值图

这个顺序可以从“正例稳帧”讲到“反例风险帧”，逻辑最完整。

---

## 最后可以直接念的总结

如果最后只留一段结论，可以直接这样说：

当前 `Stage5` 和 `GFS` 的关系，不应该理解成“谁替代谁”，而应该理解成“局地 refinement 和大尺度背景先验的协同”。  
在稳帧上，GFS 可以作为弱先验进入，而不会破坏 anchor 主导的局地结构。  
在高风险帧上，Stage5 和背景场仍然会存在明显差异，这说明背景不能直接硬合并成最终结果。  
所以当前最合理的技术路线，是继续坚持 `Stage5` 主导、`GFS` 弱引导，而不是把两者简单拼成一个统一真值。

