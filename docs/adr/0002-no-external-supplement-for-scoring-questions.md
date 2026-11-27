# ADR 0002: 计分题出题只用本地已确认知识库

- 日期：2026-11-24
- 状态：Accepted
- 关联：`docs/designs/assessment-pipeline-v0.1.md`、`docs/designs/knowledge-ingestion-v0.1.md`、`docs/designs/knowledge-retrieval-v0.1.md`

## 背景

出题要可溯源、可审计。外部搜索/抓取的内容未经过摄取、切块、抽概念与人工确认，直接进计分题会破坏出处与质量门槛。v2.0 已定“联网只做材料入口或超纲兜底，不进每轮作答热路径”；本 ADR 把出题路径进一步收紧为完全不使用外部补充。

## 决定

- 计分题出题只读本地知识库：`materials/`、`material_chunks`、`concept_sources`、`concepts.yaml`。
- 不调用 `SearchProvider`/Tavily/网页抓取；不读 `hot_items`；不使用自由对话的搜索来源。
- 自由对话的联网搜索结果只能作为对话来源，不得写入 `materials`、`question_bank`、`session_questions`、`hot_items`。
- 材料不足时回退旧题库或提示补材料，不得用模型常识补外部事实。

## 后果

- 出题完全可审计；题目质量受本地材料覆盖限制。
- 外部内容必须先经“材料入口 → ingest → extract → confirm → reindex”，成为已确认材料后才能作为题目出处。
- 需要测试守卫：出题模块不 import 搜索适配器；生成上下文只来自知识表。

## 后续（本次不做）

外部补充链路：

1. 外部搜索/抓取得到候选内容；
2. 落成 `materials/*.md`（front matter 带 `source_url`）；
3. `core.ingest` 解析切块；
4. `core.extract` 抽概念；
5. `core.confirm` 人工确认；
6. `core.reindex` 建索引；
7. `Retriever` 可检索后，才允许出题使用。

在完成上述链路前，`hot_items` 与网页搜索结果都不是计分题来源。
