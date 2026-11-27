# Design

## Context

- `core/retrieval.py` 已实现设计里的 FTS5 trigram + 向量 + RRF；`bff/retrieval.py` 只有概念级 `retrieve_concept`，且只被测试调用。
- 主分支的自由对话在 `bff/main.py:_handle_free_talk`，当前只拼学习进度和历史，没有检索。
- 设计文件 `docs/designs/knowledge-retrieval-v0.1.md` 的消费者原本只有 v1 出题；自由对话是新增消费者。

## Decisions

### D1 复用 Retriever，不新建检索器

自由对话 query = 用户原文；BFF 异步嵌入一次，再调同步 `Retriever.search(top_k=3)`。

- 备选：为自由对话另写语义搜索。
- 理由：设计已有 FTS + 向量 + RRF 与出处回溯；复用能保证降级、过滤、引用口径一致。

### D2 所有自由对话都先检索

命中就直接带材料回答；没命中再走原来的 teach/chat 提示词。

- 备选：只有 `teach` 模式检索。
- 理由：关键词路由会漏判知识问题；检索优先 + 阈值兜底不依赖路由准确。

### D3 注入 top3 父块，每块截断 800 字

- 理由：设计的 top5 父块全文是给出题用；自由对话回答短，top3 足够，省 token 和延迟。

### D4 无命中用可配置余弦阈值 + 确定性前缀

FTS 命中直接算有依据；否则最高余弦 >= `RETRIEVAL_MIN_COSINE`（默认 0.35）才算。teach 模式无命中时，BFF 确定性加「材料里没有直接讲到。」前缀，不依赖模型自觉。

- 备选：让 LLM 判断检索结果是否相关。
- 理由：多一次调用且不可测；阈值可在冒烟时校准。

### D5 引用落库

`reply` 事件带 `sources`，同时写 `conversation_messages.sources_json`；`conversation_load` 原样返回。

- 备选：只在事件里带，不落库。
- 理由：刷新或切回旧对话后仍能核对出处；符合设计的可回放要求。

### D6 短词回退并入关键词臂

`Store.search_fts` 对少于 3 个字符的词用 `instr` 扫 `heading_path + text`，按命中词数排序，追加在 trigram 结果后；不新增第三路 RRF。

- 备选：把短词回退做成独立向量/关键词臂。
- 理由：保持设计的两路 RRF；当前语料小，截断影响可接受。

### D7 文本自由对话

无会话时 `text` 消息走自由对话；有会话仍用 `answer`。

- 理由：验证检索不必每次录音；BFF 和前端各加一个分支。

## Non-Goals

reranker、热项第三路 `hot_search`、Coach 出题检索、20 条 Recall@5 基线；这些在自由对话 RAG 稳定后复用同一接口。
