# Stage4 地理可视化 9组代表帧汇报讲稿版

## 这份文档的用途

这份文档不是技术实现说明，而是面向组会、答辩或对外展示的“可直接念”讲稿版。  
它专门整理下面这个目录中的 9 组非空代表帧图：

```text
/data/LFT-W02_data/pengxu/stage4_visualizations/stage4_output_v2_geo_representative
```

这批图的元数据入口是：

- [selected_frames_geo.json](/data/LFT-W02_data/pengxu/stage4_visualizations/stage4_output_v2_geo_representative/selected_frames_geo.json)

生成脚本是：

- [report_stage4_geo_wind_visualization.py](/data/LFT-W02_data/pengxu/stage/report_stage4_geo_wind_visualization.py:611)

三类图分别来自脚本中的三个函数：

- `*_country_roi.png` -> [_render_country_png()](/data/LFT-W02_data/pengxu/stage/report_stage4_geo_wind_visualization.py:357)
- `*_roi_layers.png` -> [_render_roi_layers_png()](/data/LFT-W02_data/pengxu/stage/report_stage4_geo_wind_visualization.py:420)
- `*_roi_3d.png` -> [_render_roi_3d_png()](/data/LFT-W02_data/pengxu/stage/report_stage4_geo_wind_visualization.py:496)

---

## 基础讲图规则

下面 9 组图都遵守同一套基本口径，汇报时只需要统一说一次：

1. 彩色点是 `Stage4` 的稀疏重构体素，不是全国满场真值风场。
2. 点的颜色表示 `recon confidence`，越偏黄说明置信度越高，越偏紫说明置信度越低。
3. `roi_layers` 和 `roi_3d` 里的箭头是为了可视化可读性做过缩放的水平风向，不是原始风矢量长度，也不表示垂直风。
4. `hazard_alert_voxels` 只能解释成“风险代理/风险提示结构”，不能直接说成真实危险事件。
5. 这些图表达的是“全国雷达网格上的稀疏局部三维风场重构”，不是全国范围的连续风场插值。

建议现场讲图顺序固定为：

1. 先讲 `country_roi`
2. 再讲 `roi_layers`
3. 最后讲 `roi_3d`

这样听众会先知道图在全国什么位置，再知道层高分布，最后再看三维结构。

---

## 1. 00018_20260123194800

### 标题

`source_index=18 | time=20260123194800 | selection_reason=coverage_q25`

### 指标头

- `coverage=0.041469`
- `conf_mean=0.204625`
- `hazard=0`
- `support_fill=0`
- `temporal_fill=0`
- `support_expand=1`
- `anchor_restore=0`
- `anchor_force=0`

### 图路径

- [00018_20260123194800_country_roi.png](/data/LFT-W02_data/pengxu/stage4_visualizations/stage4_output_v2_geo_representative/00018_20260123194800_country_roi.png)
- [00018_20260123194800_roi_layers.png](/data/LFT-W02_data/pengxu/stage4_visualizations/stage4_output_v2_geo_representative/00018_20260123194800_roi_layers.png)
- [00018_20260123194800_roi_3d.png](/data/LFT-W02_data/pengxu/stage4_visualizations/stage4_output_v2_geo_representative/00018_20260123194800_roi_3d.png)

### `country_roi` 可直接念

这张全国图代表的是当前代表帧里 coverage 比较低的一类结果。  
可以看到彩色点非常少，而且主要集中在 ROI 里的几个局部位置，这说明系统没有为了追求“满图都有风”去做无约束填充。  
这个画面最适合拿来强调我们当前的结果是保守的 sparse reconstruction，不是把全国风场硬插值成连续面。  
从汇报角度讲，这张图先帮听众建立一个边界感：Stage4 宁可稀疏，也不乱补。

### `roi_layers` 可直接念

这一组分层图显示出，当前帧的有效重构主要还是集中在低层，越往上点越少。  
各高度层之间没有形成很强的连续面，而是几个离散小簇，这和它被选成 `coverage_q25` 是一致的。  
也就是说，这一帧的意义不是展示“重构很多”，而是展示系统在弱支撑场景下仍然保持克制。  
如果现场有人问为什么看起来点少，这正是我们希望保留的物理保守性。

### `roi_3d` 可直接念

三维图里可以看到，点主要堆在低空附近，只有少量孤立的更高层点。  
这里没有明显的高空连续带，也没有强烈的风险结构，和 `hazard=0` 是一致的。  
这张图适合直接说明：弱场景下 Stage4 的输出就是 sparse 的、局部的、没有被人为“抹平放大”。  
所以这组图的价值不在于惊艳，而在于证明方法是保守可信的。

### 这组图最适合承担的角色

这组图最适合在汇报里承担“先立边界、说明我们不做暴力填满”的角色。

---

## 2. 00076_20260124013600

### 标题

`source_index=76 | time=20260124013600 | selection_reason=max_anchor_force`

### 指标头

- `coverage=0.073891`
- `conf_mean=0.250723`
- `hazard=92`
- `support_fill=41`
- `temporal_fill=15`
- `support_expand=0`
- `anchor_restore=0`
- `anchor_force=1`

### 图路径

- [00076_20260124013600_country_roi.png](/data/LFT-W02_data/pengxu/stage4_visualizations/stage4_output_v2_geo_representative/00076_20260124013600_country_roi.png)
- [00076_20260124013600_roi_layers.png](/data/LFT-W02_data/pengxu/stage4_visualizations/stage4_output_v2_geo_representative/00076_20260124013600_roi_layers.png)
- [00076_20260124013600_roi_3d.png](/data/LFT-W02_data/pengxu/stage4_visualizations/stage4_output_v2_geo_representative/00076_20260124013600_roi_3d.png)

### `country_roi` 可直接念

这一帧是 `max_anchor_force`，也就是最适合说明 direct anchor 强制回写作用的一帧。  
从全国图看，ROI 内的点数明显比上一帧多，而且已经能看出几个比较清楚的局部结构。  
同时它的 `hazard` 已经升到 92，说明这里不仅有重构，还伴随更明显的风险代理结构。  
所以这张图可以先作为过渡：从“保守稀疏”进入“有结构、有风险提示”的场景。

### `roi_layers` 可直接念

分层图最值得讲的是，0 到 1.5 公里各层都有点，而且 `30N` 到 `35N` 一带开始出现更成形的分布。  
这说明在 direct anchor 被压回结果以后，低层和浅中层的结构连续性比弱场景更强了。  
这里不是大面积扩张出来的，而更像是原本应该保留的关键观测约束被重新拉回来了。  
所以这组图里“层间更稳”是 anchor force 最值得讲的视觉结果。

### `roi_3d` 可直接念

三维图里最醒目的，是一条抬升到高空的连续结构，说明这帧已经不只是地面附近的零散点。  
从口播上可以直接说：anchor force 让原本容易被后处理压弱的关键风结构重新变得可见。  
同时，箭头方向在这条高空结构上比较一致，说明它不是随机噪声点，而是一段有组织的局部风带。  
因此这张图最适合拿来解释“为什么要做 anchor force，而不是只依赖平滑补全”。

### 这组图最适合承担的角色

这组图最适合在汇报里承担“解释 direct anchor 强制回写为何必要”的角色。

---

## 3. 00322_20260125021200

### 标题

`source_index=322 | time=20260125021200 | selection_reason=coverage_q75`

### 指标头

- `coverage=0.060487`
- `conf_mean=0.217645`
- `hazard=8`
- `support_fill=36`
- `temporal_fill=0`
- `support_expand=0`
- `anchor_restore=0`
- `anchor_force=0`

### 图路径

- [00322_20260125021200_country_roi.png](/data/LFT-W02_data/pengxu/stage4_visualizations/stage4_output_v2_geo_representative/00322_20260125021200_country_roi.png)
- [00322_20260125021200_roi_layers.png](/data/LFT-W02_data/pengxu/stage4_visualizations/stage4_output_v2_geo_representative/00322_20260125021200_roi_layers.png)
- [00322_20260125021200_roi_3d.png](/data/LFT-W02_data/pengxu/stage4_visualizations/stage4_output_v2_geo_representative/00322_20260125021200_roi_3d.png)

### `country_roi` 可直接念

这一帧被选成 `coverage_q75`，代表的是 coverage 比较高、但仍然保持 sparse 的上四分位场景。  
全国图上能看到 ROI 内的点比低覆盖帧更丰富，但仍然是沿着局部结构分布，而不是把整块区域全铺满。  
这正好可以拿来说明，我们的 coverage 提升是温和的，是跟着观测和 support 结构走的。  
所以这张图要强调的是“多了一些，但没有失控”。

### `roi_layers` 可直接念

从分层图看，多个高度层都有散点，说明结果并不是只停留在最底层。  
但这些点之间仍然保持簇状分布，而不是形成一整片平滑风面，这一点很重要。  
也就是说，coverage 更高并不意味着图会变假，结构仍然是局部、分层、可解释的。  
这一页适合拿来回答“你们提高 coverage 之后，会不会把结果做得太满”的问题。

### `roi_3d` 可直接念

三维图里可以看到，主要还是低层和浅中层的点簇，只有少量更高的孤立结构。  
整体空间分布比最稀疏帧更完整，但没有出现特别强的高空连续带。  
这说明这帧更适合作为“coverage 提升”的典型，而不是“高风险高结构”的典型。  
现场讲这张图时，可以把它定义成一个比较稳妥的中上水平示例。

### 这组图最适合承担的角色

这组图最适合在汇报里承担“解释 coverage 提升但仍保持稀疏局部结构”的角色。

---

## 4. 01376_20260129114200

### 标题

`source_index=1376 | time=20260129114200 | selection_reason=max_temporal_fill`

### 指标头

- `coverage=0.056090`
- `conf_mean=0.231161`
- `hazard=28`
- `support_fill=15`
- `temporal_fill=40`
- `support_expand=1`
- `anchor_restore=0`
- `anchor_force=0`

### 图路径

- [01376_20260129114200_country_roi.png](/data/LFT-W02_data/pengxu/stage4_visualizations/stage4_output_v2_geo_representative/01376_20260129114200_country_roi.png)
- [01376_20260129114200_roi_layers.png](/data/LFT-W02_data/pengxu/stage4_visualizations/stage4_output_v2_geo_representative/01376_20260129114200_roi_layers.png)
- [01376_20260129114200_roi_3d.png](/data/LFT-W02_data/pengxu/stage4_visualizations/stage4_output_v2_geo_representative/01376_20260129114200_roi_3d.png)

### `country_roi` 可直接念

这一帧是 `max_temporal_fill`，也就是时序补全作用最明显的代表帧。  
从全国图上看，ROI 北侧和中部的点并不是特别多，但排列已经更有延续性。  
这说明 temporal background 的作用不是“凭空变多”，而是把原本会断掉的结构尽量接起来。  
所以这张图适合先告诉听众：时序信息的价值主要在连续性，不只是数量。

### `roi_layers` 可直接念

分层图最明显的特征是，多个高度层在相近位置都重复出现，层间呼应感比普通帧更强。  
尤其是 `30N` 到 `34N` 一带，可以看出同一个局部结构在不同高度层都保留了下来。  
这正是 temporal fill 最有说服力的地方，它不是乱补点，而是在时间维上保持结构不轻易断裂。  
这组图里，最推荐你把重点放在“连续性增强”这四个字上。

### `roi_3d` 可直接念

三维图会把这种连续性看得更直观：上层出现一串相对整齐、方向也比较一致的高点。  
这不是大面积扩张造成的，而更像是上一时刻的合理背景在当前时刻被保留下来。  
因此这张图可以直接用来解释：Stage4 不是一帧一帧完全独立在猜，而是在做时序一致的状态层构建。  
讲到这里，听众通常就能理解为什么 Stage4 默认不能随便切成多进程分片。

### 这组图最适合承担的角色

这组图最适合在汇报里承担“解释 temporal fill 如何增强层间和时序连续性”的角色。

---

## 5. 01436_20260129174200

### 标题

`source_index=1436 | time=20260129174200 | selection_reason=max_coverage_domain_ge_500`

### 指标头

- `coverage=0.156028`
- `conf_mean=0.334735`
- `hazard=116`
- `support_fill=31`
- `temporal_fill=7`
- `support_expand=2`
- `anchor_restore=0`
- `anchor_force=0`

### 图路径

- [01436_20260129174200_country_roi.png](/data/LFT-W02_data/pengxu/stage4_visualizations/stage4_output_v2_geo_representative/01436_20260129174200_country_roi.png)
- [01436_20260129174200_roi_layers.png](/data/LFT-W02_data/pengxu/stage4_visualizations/stage4_output_v2_geo_representative/01436_20260129174200_roi_layers.png)
- [01436_20260129174200_roi_3d.png](/data/LFT-W02_data/pengxu/stage4_visualizations/stage4_output_v2_geo_representative/01436_20260129174200_roi_3d.png)

### `country_roi` 可直接念

这一帧可以把它当成当前地理可视化里最像“主结果展示图”的一组，因为它在 coverage、confidence 和 hazard 上都比较平衡。  
全国图里，ROI 内的重构点已经很集中，北侧和中部都有比较清楚的高置信区域。  
和低 coverage 的帧相比，这里不仅点更多，而且位置组织得更像一个成形的局部风结构。  
所以汇报里如果只能选一张全国视角主图，这组通常是最稳妥的。

### `roi_layers` 可直接念

分层图里可以看到，多个高度层都在 `28N` 到 `34N` 一带留下了连续支撑。  
虽然每一层都还是 sparse，但已经能看出结构在不同高度上的重复出现，而不是每层都各自零散。  
这就说明它不是单层偶然碰到几个点，而是一个比较完整的局部三维结构。  
现场讲这一页时，可以直接把它定义成“当前主结果的平衡型代表帧”。

### `roi_3d` 可直接念

三维图里最醒目的，是上空一条比较连续、置信度也较高的风带。  
与此同时，低层还有一些支撑点，所以这不是只有高空一条线，而是高低层都有结构。  
这张图最适合说明：当观测和 support 条件都比较合适时，Stage4 可以给出既有层次、又有空间形态的结果。  
因此这组图是最推荐放在汇报中间位置作为“主结果示意”的。

### 这组图最适合承担的角色

这组图最适合在汇报里承担“主结果平衡展示图”的角色。

---

## 6. 02781_20260204095400

### 标题

`source_index=2781 | time=20260204095400 | selection_reason=max_support_expand`

### 指标头

- `coverage=0.039859`
- `conf_mean=0.221917`
- `hazard=0`
- `support_fill=20`
- `temporal_fill=0`
- `support_expand=18`
- `anchor_restore=0`
- `anchor_force=0`

### 图路径

- [02781_20260204095400_country_roi.png](/data/LFT-W02_data/pengxu/stage4_visualizations/stage4_output_v2_geo_representative/02781_20260204095400_country_roi.png)
- [02781_20260204095400_roi_layers.png](/data/LFT-W02_data/pengxu/stage4_visualizations/stage4_output_v2_geo_representative/02781_20260204095400_roi_layers.png)
- [02781_20260204095400_roi_3d.png](/data/LFT-W02_data/pengxu/stage4_visualizations/stage4_output_v2_geo_representative/02781_20260204095400_roi_3d.png)

### `country_roi` 可直接念

这一帧是 `max_support_expand`，但全国图一眼看上去并没有变成特别密的结果。  
这恰恰说明 support expand 的作用是温和的，它只在局部边缘把结构往外带一点，而不是整块铺开。  
从视觉上看，点仍然是 sparse 的，只是边缘位置比更保守的帧多了一些支撑。  
所以这张图最适合用来回应“expand 会不会把结果做假”的担心。

### `roi_layers` 可直接念

分层图能更直接看出 expand 的特点：不少点出现在原本结构外围，而不是只挤在中心。  
但这些外围点的置信度并不极端高，说明它们更像是合理的边缘补足，而不是强观测锚点。  
这类结构最适合解读成 support 区域里有限度的空间外延，而不是新造出来的一整层风场。  
所以这里要强调的是“补边缘”，不是“补满场”。

### `roi_3d` 可直接念

三维图里看得更明显，它主要还是低层和浅中层的小簇，几乎没有夸张的高空连续带。  
这意味着 expand 并没有把结构夸大成一个完整三维体，而只是把已有支撑轻微向外推开。  
如果听众担心模块一开就会把结果搞得太满，这张图就是最好的反例。  
讲这张图时，可以直接用一句话概括：expand 是保守补边，不是激进填充。

### 这组图最适合承担的角色

这组图最适合在汇报里承担“说明 support expand 只做局部边缘补足”的角色。

---

## 7. 03096_20260205173000

### 标题

`source_index=3096 | time=20260205173000 | selection_reason=max_anchor_restore`

### 指标头

- `coverage=0.100868`
- `conf_mean=0.346262`
- `hazard=160`
- `support_fill=9`
- `temporal_fill=7`
- `support_expand=1`
- `anchor_restore=16`
- `anchor_force=0`

### 图路径

- [03096_20260205173000_country_roi.png](/data/LFT-W02_data/pengxu/stage4_visualizations/stage4_output_v2_geo_representative/03096_20260205173000_country_roi.png)
- [03096_20260205173000_roi_layers.png](/data/LFT-W02_data/pengxu/stage4_visualizations/stage4_output_v2_geo_representative/03096_20260205173000_roi_layers.png)
- [03096_20260205173000_roi_3d.png](/data/LFT-W02_data/pengxu/stage4_visualizations/stage4_output_v2_geo_representative/03096_20260205173000_roi_3d.png)

### `country_roi` 可直接念

这一帧是 `max_anchor_restore`，也是我最推荐拿去讲 direct anchor 恢复作用的一组图。  
全国图里最亮眼的是 ROI 北侧那一条高置信弧段，它不像随机散点，更像一段被重新保留下来的核心结构。  
同时 `hazard=160` 也说明，这条被恢复的结构和风险代理信息是联动增强的。  
所以这张图非常适合用来说明：有些关键锚点如果不恢复，整段结构就会被后处理削弱。

### `roi_layers` 可直接念

这一组分层图有一个非常适合讲的细节：这里显示的层不是简单的 `0/0.5/1.0/1.5 km`，而是一直跳到了 `11.0 km`。  
这说明脚本挑出来的最代表性层里，高空层已经足够重要，值得单独展示。  
在 `11 km` 那一层上，可以看到一小段方向一致、置信度较高的高空结构，这是 anchor restore 最核心的可视化证据。  
现场讲这一页时，可以明确说：恢复的不是零散点，而是一段本来应该保留的高空风结构。

### `roi_3d` 可直接念

三维图里，这条 `10 到 11 km` 左右的连续弧带看得最清楚，是整组图的视觉中心。  
低层虽然也有点，但真正让这组图有说服力的是高空连续带被重新拉回来了。  
这张图最适合用来解释 direct anchor restore 的价值，它让结构重新“站起来”，而不是只增加几个孤立点。  
所以如果你要讲模块贡献，这一页的冲击力会比单纯看数字更强。

### 这组图最适合承担的角色

这组图最适合在汇报里承担“解释 anchor restore 如何恢复高空连续结构”的角色。

---

## 8. 03338_20260206174200

### 标题

`source_index=3338 | time=20260206174200 | selection_reason=max_hazard_alert`

### 指标头

- `coverage=0.154651`
- `conf_mean=0.393143`
- `hazard=328`
- `support_fill=14`
- `temporal_fill=9`
- `support_expand=1`
- `anchor_restore=1`
- `anchor_force=1`

### 图路径

- [03338_20260206174200_country_roi.png](/data/LFT-W02_data/pengxu/stage4_visualizations/stage4_output_v2_geo_representative/03338_20260206174200_country_roi.png)
- [03338_20260206174200_roi_layers.png](/data/LFT-W02_data/pengxu/stage4_visualizations/stage4_output_v2_geo_representative/03338_20260206174200_roi_layers.png)
- [03338_20260206174200_roi_3d.png](/data/LFT-W02_data/pengxu/stage4_visualizations/stage4_output_v2_geo_representative/03338_20260206174200_roi_3d.png)

### `country_roi` 可直接念

这一帧是 `max_hazard_alert`，也是整批代表帧里风险代理结构最强的一帧。  
从全国图看，ROI 内不只是点多，而且高置信区域在上部和中部都有比较清楚的聚集。  
它的 `coverage` 和 `conf_mean` 也都处在很高的位置，所以这不是“风险高但图很虚”的情况，而是结构和风险一起变强。  
因此这张图可以直接作为风险展示主图来讲。

### `roi_layers` 可直接念

分层图里最值得注意的是，脚本直接把一个高层切片选到了 `10.0 km`，说明高层在这帧里是主要结构之一。  
低层和中层当然也有支撑，但真正拉开和普通帧差距的，是高层结构在多个位置都变得清楚了。  
从可视化上看，这种“层数不多但层层都关键”的状态，很适合解释为什么 hazard 会达到全组最高。  
这里你可以把它讲成一个风险结构最完整的代表场景。

### `roi_3d` 可直接念

三维图里能看到多条高空结构并排出现，而且箭头方向在局部是有组织的，不像随机散点。  
和前几帧相比，这里不是只有一条高空带，而是出现了更复杂的高层簇和并行结构。  
这就是它被选成 `max_hazard_alert` 的视觉原因：不仅有结构，而且结构更复杂、更集中。  
所以这张图特别适合在汇报后段回答“风险代理到底长什么样”。

### 这组图最适合承担的角色

这组图最适合在汇报里承担“风险代理结构最强代表帧”的角色。

---

## 9. 07041_20260222063600

### 标题

`source_index=7041 | time=20260222063600 | selection_reason=coverage_q50`

### 指标头

- `coverage=0.049672`
- `conf_mean=0.255668`
- `hazard=28`
- `support_fill=43`
- `temporal_fill=16`
- `support_expand=0`
- `anchor_restore=0`
- `anchor_force=0`

### 图路径

- [07041_20260222063600_country_roi.png](/data/LFT-W02_data/pengxu/stage4_visualizations/stage4_output_v2_geo_representative/07041_20260222063600_country_roi.png)
- [07041_20260222063600_roi_layers.png](/data/LFT-W02_data/pengxu/stage4_visualizations/stage4_output_v2_geo_representative/07041_20260222063600_roi_layers.png)
- [07041_20260222063600_roi_3d.png](/data/LFT-W02_data/pengxu/stage4_visualizations/stage4_output_v2_geo_representative/07041_20260222063600_roi_3d.png)

### `country_roi` 可直接念

这一帧是 `coverage_q50`，也就是最接近中位水平的典型帧。  
全国图看上去不算特别惊艳，但也绝不是空的，说明这更像是系统日常表现的平均面貌。  
它的意义不是拿来展示极值，而是告诉听众：即便不挑最强帧，Stage4 也能稳定给出局部稀疏结构。  
所以这张图最适合做“普通典型帧”的说明。

### `roi_layers` 可直接念

分层图里可以看到，低层到 `1.5 km` 都有支撑，而且点分布比最稀疏帧更均匀一些。  
不过它又不像高风险帧那样出现非常突出的高空强结构，所以整体气质是“稳”，不是“猛”。  
这正符合中位帧的定义：它不靠某个极端模块撑起来，而是多个模块一起维持一个还不错的平均结果。  
因此这组图很适合用来回答“如果不挑最好的帧，你们平时大概长什么样”。

### `roi_3d` 可直接念

三维图里低层和中层的小簇都在，而且高空还有几组离散高点，但没有形成特别夸张的连续带。  
这说明它既不是弱到只有低空散点，也不是强到有整条高空主结构，是一个相对中庸、但很真实的状态。  
从口播角度，这张图非常适合作为收尾，强调系统的常态输出不是只靠极端好帧撑门面。  
也就是说，它展示的是一个“普通但可信”的 Stage4 结果。

### 这组图最适合承担的角色

这组图最适合在汇报里承担“普通典型帧、说明系统常态表现”的角色。

---

## 汇报推荐选图顺序

### 3图精简版

如果汇报时间很短，只推荐讲这 3 组：

1. `01436_20260129174200`
   - 作为主结果平衡展示图
2. `03096_20260205173000`
   - 作为 `anchor_restore` 代表图
3. `03338_20260206174200`
   - 作为最大风险代理结构图

这个顺序的好处是：

- 先给一个“整体最像主结果”的图
- 再讲一个关键模块贡献
- 最后用风险代理结构收尾

### 5图完整版

如果时间更充分，推荐讲这 5 组：

1. `00018_20260123194800`
   - 先立边界：我们不做暴力填满
2. `01376_20260129114200`
   - 解释 temporal fill 的价值
3. `01436_20260129174200`
   - 展示主结果平衡帧
4. `03096_20260205173000`
   - 展示 anchor restore 的高空连续结构
5. `03338_20260206174200`
   - 展示风险代理最强帧

这个顺序适合完整叙事：

- 从保守 sparse
- 到时序连续
- 到主结果
- 到模块贡献
- 到风险结构

---

## 两帧空重构记录说明

虽然 `selected_frames_geo.json` 里一共记录了 11 个代表帧，但其中有 2 帧没有 PNG，只保留了元数据：

### 1. `20260208234200`

- `selection_reason = nontriggered_mid_time`
- `skipped_reason = empty_reconstruction`
- `recon_triggered = 0`
- `recon_filled_voxels = 0`

可以直接这样解释：

这一帧被选中，是为了保留一个“非触发典型帧”的代表记录。  
但因为主链没有触发完整重构，所以这里没有实际 sparse recon 可画。  
脚本因此只把它写进 JSON，没有生成空图，避免误导成“这也是一张有内容的风场图”。

### 2. `20260218211800`

- `selection_reason = triggered_zero_recon`
- `skipped_reason = empty_reconstruction`
- `recon_triggered = 1`
- `recon_filled_voxels = 0`

可以直接这样解释：

这一帧虽然触发了重构流程，但最终没有留下有效重构体素。  
所以它的价值在于提示“触发不等于一定产出非空风场”，而不是拿来展示风结构。  
脚本对这种情况也选择不出图，这样汇报时不会出现一张看似空白却让人误会的结果图。

---

## 结束时可以直接念的总括

如果最后只留一段总结，可以直接这样说：

当前这 9 组代表帧共同说明，`Stage4` 的输出是稀疏、局部、分层的三维风场重构，而不是全国范围的满场插值。  
不同模块的作用在图上是可分辨的，比如 `temporal fill` 更像是在维持连续性，`anchor restore` 更像是在恢复关键高空结构，`support expand` 只是温和补边。  
而最强的几组图同时表明，当支撑条件较好时，系统可以形成比较清楚的高空连续带和风险代理结构。  
所以从汇报角度看，这批图最重要的价值，是把“保守但可解释”的结果风格讲清楚。

