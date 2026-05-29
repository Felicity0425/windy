# LLM Wiki

这是一个按 `llm-wiki` 方法初始化的本地知识库仓库。

它不是“把 Markdown 按主题分目录堆起来”的普通笔记库，而是一个由 LLM 持续维护的 Wiki：

- `raw/` 存放原始资料，作为不可变事实来源
- `wiki/` 存放 LLM 编译出的知识页、索引和日志
- `AGENTS.md` 定义 Codex 维护这个 Wiki 的规则和工作流
- `skill/SKILL.md` 保留这套方法的 Skill 版本说明

## 核心理念

和传统 RAG 不同，这个仓库强调“持续编译知识”而不是“每次查询临时检索”。

每当你放入一份新资料，LLM 不是只做切片和召回，而是会：

1. 阅读原始资料
2. 创建一页资料摘要
3. 创建或更新相关实体页、概念页、工作流页
4. 补全交叉引用
5. 更新 `wiki/index.md`
6. 在 `wiki/log.md` 追加一条操作记录

知识会随着每次导入和提问不断积累，而不是每次从零推导。

## 目录结构

```text
raw/                  原始资料，只增不改
  assets/             附件、图片
wiki/                 LLM 维护的 Wiki 页面
  index.md            内容索引
  log.md              操作日志
skill/                Skill 备份与说明
  SKILL.md
AGENTS.md             Codex 版知识库维护规则
README.md             使用说明
```

## 日常使用

### 1. 放入资料

把文章、论文、剪藏 Markdown、截图或附件放入 `raw/`。

推荐搭配：

- Obsidian Web Clipper：把网页剪藏成 Markdown
- Obsidian：浏览 `wiki/`、查看图谱、跟踪页面关系

### 2. 导入资料

直接对 Codex 说：

```text
请导入 raw/文件名.md 到知识库
```

Codex 会按照 [AGENTS.md](AGENTS.md) 的规则更新 Wiki。

### 3. 查询知识库

直接提问，例如：

```text
知识库里关于 RAG 的核心观点有哪些？
根据知识库，对比 A 和 B 的差异
把目前关于某个主题的内容整理成一页综述
```

### 4. 维护健康状态

```text
请检查知识库健康状态
```

典型检查项：

- 页面之间是否有矛盾
- 是否有孤立页面
- 是否存在被新资料取代的过时表述
- 是否缺少关键概念页或交叉引用

## 页面命名约定

- 资料摘要：`source-{关键词}.md`
- 实体页：`{实体名}.md`
- 概念页：`{概念名}.md`
- 工作流页：`{场景}-workflow.md`
- 综合分析页：`{主题}-analysis.md`

## 设计取向

这个初始化版本刻意保持轻量：

- 不预设复杂脚本和模板系统
- 优先依赖 `wiki/index.md` 作为导航入口
- 优先使用 `[[wikilink]]` 在页面之间交叉引用
- 让规则写在 `AGENTS.md`，而不是分散到很多工具里

如果后续资料规模变大，再补 BM25 / 向量检索、Dataview、Marp 或发布站点会更合适。

## 方法来源

- GitHub 仓库：<https://github.com/luotwo/llm-wiki>
- 当前仓库中的 Skill 备份：[skill/SKILL.md](skill/SKILL.md)
- 当前仓库中的 Codex 规则：[AGENTS.md](AGENTS.md)
