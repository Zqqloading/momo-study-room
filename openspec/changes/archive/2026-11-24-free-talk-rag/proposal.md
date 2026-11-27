# Proposal: 自由对话知识检索

## Why

前端自由对话已经能用语音或文字提问，但回答只依赖模型和最近 12 条历史，材料里的内容不会进入回答。知识库分支已经按 `docs/designs/knowledge-retrieval-v0.1.md` 实现了 FTS5 + 向量 + RRF，但生产代码没有调用；主分支没有检索。用户在前端问「模型自作主张是什么」时，页面答不出材料里的内容，也没有出处。

## What Changes

- 合并 `feat/knowledge-base` 到 `progress`；schema 升到 v5，`init_schema` 按表名补齐，`conversation_messages` 增加 `sources_json`。
- 自由对话在调 LLM 前走同一套 `Retriever`：query 用转写/输入原文；FTS top20 + 向量 top20 → RRF k=60 → top3 父块。
- 短词回退：少于 3 个字符的词用子串扫描并入关键词臂，解决 trigram 对「工具」这类中文短词不命中。
- 无命中判定：FTS 无命中且最高余弦低于 `RETRIEVAL_MIN_COSINE`（默认 0.35）视为没有材料；teach 模式确定性加「材料里没有直接讲到。」前缀。
- `reply` 事件带 `sources`（序号、标题、URL、摘录）；引用落 `conversation_messages.sources_json`，刷新或切回旧对话仍可见。
- 无会话时 `text` 消息走自由对话；前端显示文本输入框和「出处」列表。

## Capabilities

### New Capabilities

- `knowledge-retrieval`: 自由对话检索消费者、短词回退、无命中阈值、引用载荷。
- `free-talk`: 文本入口与引用展示。

### Modified Capabilities

（无；检索核心沿用 `knowledge-retrieval-v0.1.md`，不修改其正文。）

## Impact

- 代码：`core/db.py`（v5）、`core/store.py`（短词回退、sources 落库）、`core/retrieval.py`（`fts_hit`/`vector_score`）、`bff/retrieval.py`、`bff/main.py`、`core/free_talk.py`、`web/app.js`、`web/style.css`、`web/index.html`。
- 数据：新建 `data/app-v5.db`（内容重建）；旧 `data/app.db` 保留。
- 不做：reranker、热项第三路、Coach 出题检索、20 条 Recall@5 基线。
