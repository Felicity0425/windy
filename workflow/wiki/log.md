# Wiki 操作日志

## [2026-04-28] init | LLM Wiki 初始化

- **创建目录**：`raw/`、`raw/assets/`、`wiki/`、`skill/`
- **创建文件**：`README.md`、`AGENTS.md`、`skill/SKILL.md`、`wiki/index.md`、`wiki/log.md`
- **采用方法**：`llm-wiki` 的三层模型，按 `raw sources / wiki / schema` 组织
- **当前状态**：等待导入第一份资料

## [2026-04-29] ingest | 航空气象智能文献批量导入

- **来源目录**：
  - `raw/1-s2.0-S0306261924019603-main`
  - `raw/1-s2.0-S0360544224001725-main`
  - `raw/8-ZY2202521-方宇航`
  - `raw/aerospace-11-00791`
  - `raw/amt-9-4141-2016`
  - `raw/amt-18-3341-2025`
  - `raw/s00376-021-1035-9`
  - `raw/s10409-022-22302-x`
  - `raw/s41586-023-06185-3`
  - `raw/s41612-023-00512-1`
  - `raw/s43247-025-02502-y`
- **创建页面**：
  - 11 个资料摘要页：Mode-S EHS 误差评估、EMADDC、双多普勒雷达风场反演、PINN 稀疏流场重建、LiDAR 多尺度 PINN、动态尾流 PINN、Vision Mamba 风场重建、Pangu-Weather、FuXi、FengWu、多机协同感知
  - 5 个实体页：`mode-s-ehs.md`、`emaddc.md`、`pangu-weather.md`、`fuxi.md`、`fengwu.md`
  - 7 个概念/分析页：`wind-field-reconstruction.md`、`physics-informed-neural-network.md`、`aircraft-derived-meteorological-observations.md`、`airborne-meteorological-situational-awareness.md`、`multi-aircraft-collaborative-perception.md`、`ai-medium-range-weather-forecasting.md`、`aviation-weather-intelligence-analysis.md`
- **更新页面**：`wiki/index.md`、`wiki/log.md`
- **关键要点**：
  - 这批资料形成了“观测 -> 重建 -> 预报 -> 运行”的完整链路
  - 稀疏观测是默认前提，因此物理约束方法和质量控制方法反复出现
  - AI 中期天气预报的主要矛盾是长 lead time 的误差积累和不确定性表达
  - 面向自主运行航空器，最终问题不是单个模型精度，而是协同感知和系统集成
- **与已有知识的关联**：
  - 这是知识库初始化后的第一批正式资料，建立了航空气象智能主题的主干结构
  - 后续可继续向“数据同化”“航迹优化”“概率风险决策”“多源实时融合”方向扩展

## [2026-04-29] ingest | Where2comm 协同感知通信机制导入

- **来源目录**：
  - `raw/where2comm`
- **创建页面**：
  - `source-where2comm-spatial-confidence-maps.md`
  - `where2comm.md`
  - `spatial-confidence-map.md`
- **更新页面**：
  - `multi-aircraft-collaborative-perception.md`
  - `airborne-meteorological-situational-awareness.md`
  - `aviation-weather-intelligence-analysis.md`
  - `wiki/index.md`
  - `wiki/log.md`
- **关键要点**：
  - 协同感知中的核心约束不仅是带宽不足，更是“哪些空间区域值得传”
  - Where2comm 用空间置信图把选择性通信显式化，并把区域选择、稀疏图构建和消息融合连成一体
  - 该论文虽不直接面向航空气象，但对多机气象协同感知具有强方法迁移价值
- **与已有知识的关联**：
  - 它为 `multi-aircraft-collaborative-perception` 页面补上了更通用的通信机制来源
  - 它强化了当前知识库中“高风险区域优先共享”的运行层设计方向

## [2026-04-29] maintain | raw 文献目录改为中文命名

- **调整范围**：`raw/` 下 12 个文献目录
- **处理原则**：仅重命名文献文件夹，保留目录内原始 `.md`、`_meta.json` 和图片文件名不变
- **同步更新**：修正 12 个 `source-*` 页面里的本地原文链接
- **目录映射**：
  - `1-s2.0-S0306261924019603-main` -> `基于LiDAR和多尺度PINN的三维时空风场重建`
  - `1-s2.0-S0360544224001725-main` -> `基于PINN和稀疏LiDAR数据的风力机动态尾流场重建`
  - `8-ZY2202521-方宇航` -> `面向自主运行的多机态势智能协同感知方法研究`
  - `aerospace-11-00791` -> `基于Vision Mamba解码网络的不完整风数据风场重建方法`
  - `amt-9-4141-2016` -> `基于三重协同法的Mode-S EHS飞机风观测误差估计`
  - `amt-18-3341-2025` -> `EMADDC基于Mode-S EHS飞机监视数据的高体量高质量高时效风温观测`
  - `s00376-021-1035-9` -> `基于变分法的双多普勒雷达三维风场反演与垂直速度优化`
  - `s10409-022-22302-x` -> `基于物理信息神经网络的稀疏或不完整数据流场重建实用方法`
  - `s41586-023-06185-3` -> `基于三维神经网络的高精度中期全球天气预报`
  - `s41612-023-00512-1` -> `FuXi十五天全球天气预报级联机器学习系统`
  - `s43247-025-02502-y` -> `将业务级中期确定性天气预报延伸至十天以上`
  - `where2comm` -> `Where2comm基于空间置信图的高通信效率协同感知`
