# Stage3 可视化 8组代表帧汇报讲稿版

## 这份文档的用途

这份文档不是代码说明，而是面向组会、答辩或对外展示的“可直接念”讲稿版。  
它专门整理下面这个目录里的 `Stage3` 代表帧可视化结果：

```text
/data/LFT-W02_data/pengxu/stage3_visualizations/stage3_output_v2_representative
```

这批图的元数据入口是：

- [selected_frames.json](/data/LFT-W02_data/pengxu/stage3_visualizations/stage3_output_v2_representative/selected_frames.json)

生成脚本是：

- [report_stage3_agent_graph_visualization.py](/data/LFT-W02_data/pengxu/stage/report_stage3_agent_graph_visualization.py:711)

这两类图来自脚本中的两个函数：

- `*_geo.png` -> [_render_geo_png()](/data/LFT-W02_data/pengxu/stage/report_stage3_agent_graph_visualization.py:433)
- `*_topology.png` -> [_render_topology_png()](/data/LFT-W02_data/pengxu/stage/report_stage3_agent_graph_visualization.py:564)

代表帧选择逻辑在：

- [_select_representative_rows()](/data/LFT-W02_data/pengxu/stage/report_stage3_agent_graph_visualization.py:98)

---

## 基础讲图规则

下面 8 组图都遵守同一套基本口径，汇报时只需要统一说一次：

1. `geo` 图里的点是 `Stage3` 构建出来的 `flight agents`，不是原始观测点，也不是 `Stage4` 风场体素。
2. `geo` 图里的蓝点是普通 agent，橙红点是 `wind-capable agent`，黑色星号是当前帧动态估计出来的 ground reference。
3. `topology` 图不是地理地图，而是通信图的抽象拓扑布局，强调“谁和谁相连”，不强调真实经纬位置。
4. `topology` 图里的红线是强风边，橙线是弱风边，灰线是普通通信边。
5. `topology` 图里节点的颜色也有含义：红节点表示风能力节点，蓝节点表示普通节点。

建议现场讲图顺序固定为：

1. 先讲 `geo`
2. 再讲 `topology`

这样听众会先知道这些智能体在空间上大概分布在哪里，再理解图结构为什么会变密、变强或变弱。

---

## 1. 20260123180000

### 标题

`time=20260123180000 | selection_reason=earliest_nonzero_wind_edge_frame`

### 指标头

- `nodes=120`
- `valid_flight_agents=127`
- `valid_wind_capable_flights=37`
- `flight_ff_allowed_edges=694`
- `flight_ff_wind_edges=236`
- `strong_wind_edges=176`
- `weak_wind_edges=59`

### 图路径

- [frame_20260123180000_geo.png](/data/LFT-W02_data/pengxu/stage3_visualizations/stage3_output_v2_representative/frame_20260123180000_geo.png)
- [frame_20260123180000_topology.png](/data/LFT-W02_data/pengxu/stage3_visualizations/stage3_output_v2_representative/frame_20260123180000_topology.png)

### `geo` 可直接念

这组图是最早出现非零风边的代表帧，所以它最适合拿来说明 `Stage3` 是怎么从“只有普通 agent”开始，逐渐长出风图结构的。  
地理图上能看到，蓝点还是多数，橙红色的风能力节点只在局部区域开始出现，说明这一时刻风图还只是刚刚被激活。  
黑色星号附近已经能形成一个小范围的橙色节点簇，但还远没有发展成全局性的风能力网络。  
所以这张图的关键词不是“强”，而是“第一次成形”。

### `topology` 可直接念

拓扑图里最重要的信息是，除了红色强风边之外，已经能看到一批橙色弱风边和灰色普通通信边。  
这说明当前图结构还处在混合阶段，也就是一部分节点已经具备风能力，另一部分节点还只是通信或运动支撑节点。  
从展示角度看，这张图很适合解释 `Stage3` 的风边不是一步到位全开，而是从弱激活慢慢过渡出来的。  
如果现场要讲风边生成机制，这组图最容易作为起点。

### 这组图最适合承担的角色

这组图最适合在汇报里承担“解释风边如何首次出现”的角色。

---

## 2. 20260124105400

### 标题

`time=20260124105400 | selection_reason=median_valid_flight_agents`

### 指标头

- `nodes=120`
- `valid_flight_agents=632`
- `valid_wind_capable_flights=88`
- `flight_ff_allowed_edges=6361`
- `flight_ff_wind_edges=1002`
- `strong_wind_edges=300`
- `weak_wind_edges=0`

### 图路径

- [frame_20260124105400_geo.png](/data/LFT-W02_data/pengxu/stage3_visualizations/stage3_output_v2_representative/frame_20260124105400_geo.png)
- [frame_20260124105400_topology.png](/data/LFT-W02_data/pengxu/stage3_visualizations/stage3_output_v2_representative/frame_20260124105400_topology.png)

### `geo` 可直接念

这一帧是 `valid_flight_agents` 的中位代表帧，可以把它理解成“普通规模下的典型 Stage3 图”。  
从地理图看，星号附近已经出现了比较稳定的 agent 聚集区，而且橙色风能力节点和蓝色普通节点是同时存在的。  
这说明到了一个比较典型的时刻，`Stage3` 不是只有一种节点，而是已经形成了普通通信节点和风能力节点并存的结构。  
所以这张图非常适合用来讲“常态下的 Stage3 长什么样”。

### `topology` 可直接念

拓扑图里强风边已经明显成网，但蓝色普通节点仍然在外围保留了一圈，这一点很有代表性。  
它说明当前网络已经足够稠密，可以支撑协同感知，但又没有极端到所有节点都变成风能力节点。  
换句话说，这是一张最适合解释“普通时刻图结构规模和层次”的图。  
如果你想展示 Stage3 的常态，而不是极值，这组图是最稳妥的。

### 这组图最适合承担的角色

这组图最适合在汇报里承担“常态规模、普通代表帧”的角色。

---

## 3. 20260128031200

### 标题

`time=20260128031200 | selection_reason=median_flight_ff_wind_edges`

### 指标头

- `nodes=120`
- `valid_flight_agents=613`
- `valid_wind_capable_flights=114`
- `flight_ff_allowed_edges=5691`
- `flight_ff_wind_edges=1272`
- `strong_wind_edges=300`
- `weak_wind_edges=0`

### 图路径

- [frame_20260128031200_geo.png](/data/LFT-W02_data/pengxu/stage3_visualizations/stage3_output_v2_representative/frame_20260128031200_geo.png)
- [frame_20260128031200_topology.png](/data/LFT-W02_data/pengxu/stage3_visualizations/stage3_output_v2_representative/frame_20260128031200_topology.png)

### `geo` 可直接念

这组图是风边数量的中位代表帧，所以最适合解释“一个典型的风图密度长什么样”。  
地理图上可以看到，橙色风能力节点已经明显比前一组更多，说明风图已经成为空间结构里的主导部分。  
但它又没有像后面极值帧那样几乎全图都是风能力节点，所以这张图很适合当“典型风边规模”的标准样本。  
也就是说，这组图更强调风边数量的常态水平，而不是节点总数的极值。

### `topology` 可直接念

拓扑图里强风边几乎占满了展示出的主结构，说明当前网络里风信息传播已经是核心关系。  
同时它的规模还没有冲到最大，所以这张图比后面的极值帧更适合说明“常规情况下风边已经足够成网”。  
如果听众想知道 Stage3 的风边不是偶然几条，而是真的能稳定形成结构，这一页最有说服力。  
它相当于告诉大家，风图在中位场景下就已经是主角了。

### 这组图最适合承担的角色

这组图最适合在汇报里承担“解释典型风边规模”的角色。

---

## 4. 20260205061200

### 标题

`time=20260205061200 | selection_reason=max_flight_ff_allowed_edges`

### 指标头

- `nodes=120`
- `valid_flight_agents=770`
- `valid_wind_capable_flights=138`
- `flight_ff_allowed_edges=7783`
- `flight_ff_wind_edges=1590`
- `strong_wind_edges=300`
- `weak_wind_edges=0`

### 图路径

- [frame_20260205061200_geo.png](/data/LFT-W02_data/pengxu/stage3_visualizations/stage3_output_v2_representative/frame_20260205061200_geo.png)
- [frame_20260205061200_topology.png](/data/LFT-W02_data/pengxu/stage3_visualizations/stage3_output_v2_representative/frame_20260205061200_topology.png)

### `geo` 可直接念

这一帧是总允许边数最大的代表帧，所以最适合拿来说明 `Stage3` 的通信图可以有多密。  
地理图里几乎看不到蓝点，当前被展示出来的 120 个核心节点基本都已经是风能力节点。  
这意味着在这个时刻，系统不只是“有一些风节点”，而是进入了一个高连接、高传播潜力的状态。  
所以这张图最重要的关键词是“通信图极密”。

### `topology` 可直接念

拓扑图上最直观的感受就是边很多，而且主结构的跨簇连接非常强。  
这说明当前帧里不仅局部团簇内部连得紧，不同区域之间也在持续建立强连接。  
如果你要说明 Stage3 的 air-air 图不是稀稀拉拉几条边，这张图就是最直接的证据。  
从汇报角度，它适合放在“图结构复杂度上升”的位置来讲。

### 这组图最适合承担的角色

这组图最适合在汇报里承担“说明通信图最稠密状态”的角色。

---

## 5. 20260212061200

### 标题

`time=20260212061200 | selection_reason=max_valid_flight_agents`

### 指标头

- `nodes=120`
- `valid_flight_agents=782`
- `valid_wind_capable_flights=135`
- `flight_ff_allowed_edges=7740`
- `flight_ff_wind_edges=1559`
- `strong_wind_edges=300`
- `weak_wind_edges=0`

### 图路径

- [frame_20260212061200_geo.png](/data/LFT-W02_data/pengxu/stage3_visualizations/stage3_output_v2_representative/frame_20260212061200_geo.png)
- [frame_20260212061200_topology.png](/data/LFT-W02_data/pengxu/stage3_visualizations/stage3_output_v2_representative/frame_20260212061200_topology.png)

### `geo` 可直接念

这一帧是 `valid_flight_agents` 最大的代表帧，也就是当前 Stage3 能构建出的最大节点规模。  
地理图里展示出的核心节点几乎全是橙色，说明不只是节点数多，而且这些核心节点大多还能参与风图传播。  
所以这张图适合讲“节点规模上限”，强调当前系统在高交通密度时仍然能稳定构图。  
它对应的是 Stage3 的“最大节点承载能力”。

### `topology` 可直接念

拓扑图里你会看到比中位帧更厚、更饱满的主结构，图上几乎没有明显空心地带。  
这说明节点一旦多起来，图不是简单变大，而是会同时变得更密、更连通。  
换句话说，这一页既能讲节点数极值，也能顺带讲图连通性不会因为规模上升而塌掉。  
从展示效果看，它很适合作为“最大节点规模的能力证明”。

### 这组图最适合承担的角色

这组图最适合在汇报里承担“说明最大节点规模与大图稳定性”的角色。

---

## 6. 20260213063600

### 标题

`time=20260213063600 | selection_reason=max_valid_wind_capable_flights`

### 指标头

- `nodes=120`
- `valid_flight_agents=759`
- `valid_wind_capable_flights=759`
- `flight_ff_allowed_edges=7485`
- `flight_ff_wind_edges=7485`
- `strong_wind_edges=300`
- `weak_wind_edges=0`

### 图路径

- [frame_20260213063600_geo.png](/data/LFT-W02_data/pengxu/stage3_visualizations/stage3_output_v2_representative/frame_20260213063600_geo.png)
- [frame_20260213063600_topology.png](/data/LFT-W02_data/pengxu/stage3_visualizations/stage3_output_v2_representative/frame_20260213063600_topology.png)

### `geo` 可直接念

这一帧最极端的地方是，`valid_flight_agents` 和 `valid_wind_capable_flights` 完全相等。  
也就是说，在这一个代表帧里，所有有效智能体都被激活成了风能力节点。  
地理图上因此几乎清一色都是橙红色节点，没有再保留普通节点的可见主体。  
这张图最适合一句话讲清楚：这是 `Stage3` 风能力激活最彻底的一帧。

### `topology` 可直接念

拓扑图也和地理图完全一致，几乎变成了一张纯红色的强风边网络。  
这说明当前不仅是节点都具备风能力，连节点之间的主要关系也几乎都变成了风边。  
所以这张图特别适合解释“全图风化”的极端场景，也最容易让听众直观理解风图是怎样完全占主导的。  
这不是常态图，但它很适合作为上限案例。

### 这组图最适合承担的角色

这组图最适合在汇报里承担“展示风能力节点最极端上限”的角色。

---

## 7. 20260215062400

### 标题

`time=20260215062400 | selection_reason=max_flight_ff_wind_edges`

### 指标头

- `nodes=120`
- `valid_flight_agents=751`
- `valid_wind_capable_flights=751`
- `flight_ff_allowed_edges=7644`
- `flight_ff_wind_edges=7644`
- `strong_wind_edges=300`
- `weak_wind_edges=0`

### 图路径

- [frame_20260215062400_geo.png](/data/LFT-W02_data/pengxu/stage3_visualizations/stage3_output_v2_representative/frame_20260215062400_geo.png)
- [frame_20260215062400_topology.png](/data/LFT-W02_data/pengxu/stage3_visualizations/stage3_output_v2_representative/frame_20260215062400_topology.png)

### `geo` 可直接念

这一帧和上一帧很像，但它的重点不是“所有节点都能成风能力”，而是“风边数量冲到了全组最高”。  
地理图里同样几乎全是橙色节点，但这里更值得强调的是它们在空间上已经形成了非常稳定的主体轮廓。  
换句话说，这一帧更像是“风图连接最充分”的极值，而不是单纯节点颜色最极端。  
所以这张图要讲的关键词是“风边数量上限”。

### `topology` 可直接念

拓扑图是这批图里最适合讲“风边极密”的一张，因为总的 `flight_ff_wind_edges` 已经达到 `7644`。  
主结构内部几乎所有展示出的核心边都是强风边，跨簇连接也非常多。  
如果上一帧讲的是“所有节点都能成风能力”，这一帧更适合接着讲“这些风能力节点之间还能连成最密的风图”。  
所以这张图是风边数量极值最好的可视化代表。

### 这组图最适合承担的角色

这组图最适合在汇报里承担“展示最大风边数量与风图最密状态”的角色。

---

## 8. 20260221174200

### 标题

`time=20260221174200 | selection_reason=max_wind_support_score_p90`

### 指标头

- `nodes=103`
- `valid_flight_agents=103`
- `valid_wind_capable_flights=26`
- `flight_ff_allowed_edges=594`
- `flight_ff_wind_edges=241`
- `strong_wind_edges=206`
- `weak_wind_edges=35`

### 图路径

- [frame_20260221174200_geo.png](/data/LFT-W02_data/pengxu/stage3_visualizations/stage3_output_v2_representative/frame_20260221174200_geo.png)
- [frame_20260221174200_topology.png](/data/LFT-W02_data/pengxu/stage3_visualizations/stage3_output_v2_representative/frame_20260221174200_topology.png)

### `geo` 可直接念

这一帧很特别，它不是节点最多，也不是边最多，但它的 `wind_support_score_p90` 最高。  
地理图上可以看到，橙色风能力节点数量并不多，只集中在中间一小块区域，而外围蓝点仍然占了很大一部分。  
这说明它强调的不是“规模”，而是少数风能力节点的支撑证据特别强。  
所以这张图适合用来讲“风支持质量高，不等于全图都大”。

### `topology` 可直接念

拓扑图里最关键的细节是，除了红色强风边，还重新出现了一批橙色弱风边和灰色普通边。  
这说明当前图又回到了混合型结构，也就是一小部分高支持风节点在带动周围普通节点，而不是全图一起变红。  
因此这张图特别适合解释 `wind_support_score` 这种指标，它更关心局部支撑强度，而不是全图规模极值。  
从讲图角度说，这是一张“质量型代表帧”，不是“数量型代表帧”。

### 这组图最适合承担的角色

这组图最适合在汇报里承担“解释高风支持分数代表局部强证据，而不是全图极大规模”的角色。

---

## 汇报推荐选图顺序

### 3图精简版

如果时间很短，推荐讲这 3 组：

1. `20260123180000`
   - 解释风边如何第一次出现
2. `20260205061200`
   - 解释通信图最稠密的状态
3. `20260215062400`
   - 解释风边最密的状态

这个顺序的好处是：

- 先讲起点
- 再讲通信图做大
- 最后讲风图做到最强

### 5图完整版

如果时间更充分，推荐讲这 5 组：

1. `20260123180000`
   - 首次出现非零风边
2. `20260124105400`
   - 常态规模代表帧
3. `20260205061200`
   - 最大总边数
4. `20260213063600`
   - 风能力节点最极端上限
5. `20260221174200`
   - 高风支持分数的质量型代表帧

这个顺序适合完整叙事：

- 从初始激活
- 到常态结构
- 到大图稠密
- 到全图风化
- 再回到“局部强支撑但不是极大图”的细粒度解释

---

## 结束时可以直接念的总括

如果最后只留一段总结，可以直接这样说：

当前这 8 组代表帧共同说明，`Stage3` 的核心价值是把原始稀疏轨迹和风观测组织成可解释的 flight-agent 通信图。  
在较弱场景下，图里会同时保留普通节点、弱风边和强风边；而在极端强场景下，几乎所有核心节点都可以被激活成风能力节点。  
这说明 `Stage3` 既能表达“图什么时候开始长出来”，也能表达“图什么时候已经变得很密很强”。  
所以从汇报角度看，这批图最重要的作用，是把 `Stage3` 从数据预处理层讲成真正的协同感知图结构层。

