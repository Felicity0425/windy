---
name: llm-wiki
description: "LLM Wiki - 用 LLM 构建和维护持续积累的 Markdown 知识库。适用于初始化 Wiki、导入资料、查询知识库和维护知识库健康状态。"
version: 1.1.0-codex
---

# LLM Wiki

## 核心理念

不同于传统 RAG 在每次查询时重新检索，LLM Wiki 强调让 LLM 持续维护一个结构化、可交叉引用的 Markdown Wiki。新资料进入后，不只是被索引，而是被阅读、总结、编译并整合进现有知识网络。

## 三层结构

### 1. Raw Sources

- 位于 `raw/`
- 只增不改
- 保存文章、论文、截图、数据文件等原始资料

### 2. Wiki

- 位于 `wiki/`
- 保存资料摘要页、实体页、概念页、工作流页、综合分析页
- 由 LLM 持续创建、更新和维护交叉引用

### 3. Schema

- 默认以 `AGENTS.md` 作为 Codex 的规则文件
- 如在 Claude Code 中使用，可迁移到 `CLAUDE.md`

## 三大操作

### Ingest

当用户要求导入资料时：

1. 读取 `raw/` 中的资料
2. 创建 `wiki/source-xxx.md` 摘要页
3. 创建或更新相关实体页、概念页、工作流页
4. 更新 `wiki/index.md`
5. 追加 `wiki/log.md`
6. 标注与既有知识的补充关系和矛盾关系

### Query

当用户基于知识库提问时：

1. 先读 `wiki/index.md`
2. 再读相关页面
3. 综合回答
4. 有价值的分析可以回写为新的 Wiki 页面

### Lint

当用户要求检查知识库健康状态时：

1. 查找矛盾
2. 查找孤立页面
3. 查找过时内容
4. 查找缺失概念和交叉引用
5. 建议下一步应补的资料

## 命名约定

- `source-{关键词}.md`
- `{实体名}.md`
- `{概念名}.md`
- `{场景}-workflow.md`
- `{主题}-analysis.md`

## 维护原则

- 原始资料层不可变
- Wiki 是可持续更新的编译层
- 交叉引用比单页摘要更重要
- 好的问答应回写进 Wiki
- `index.md` 管内容目录，`log.md` 管时间顺序

更详细的执行规则见仓库根目录的 `AGENTS.md`。
