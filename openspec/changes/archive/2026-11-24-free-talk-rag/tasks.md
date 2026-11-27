# Tasks

## 1. 合并与 schema

- [x] 1.1 合并 `feat/knowledge-base` 到 `progress`；解决 `bff/main.py`、`core/db.py`、`core/store.py` 等 9 个冲突，保留 Coach/自由对话并把 KB 检索/嵌入/入库/热项服务带进来；验证：合并后 `pytest -q` 全绿。
- [x] 1.2 `SCHEMA_VERSION=5`；`init_schema` 改为按表名补齐，兼容 progress v3（conversations）与 KB v3（检索表）两种旧库；`conversation_messages` 增加 `sources_json`；验证：`test_db.py` 覆盖全表、两个 v3 变体、v4→v5 加列、拒绝高版本。
- [x] 1.3 `bff/config.py` 保留 `DATA_DIR`，增加 `DB_PATH`、`EMBEDDING_*`、`RETRIEVAL_MIN_COSINE`、`CONTENT_DIR`；`requirements.txt` 带 numpy；验证：`/health` 显示 embedding real。

## 2. 内容重建

- [x] 2.1 `data/app-v5.db` 新库：`core.ingest` 导入 `materials/示例材料-a.md`（1 材料、2 父块 + 8 子块）；验证：`materials=1`、`material_chunks=10`。
- [x] 2.2 `core.reindex` 用真实 DashScope `text-embedding-v4` 建索引；验证：`fts=8 embedded=8 failed=0`。
- [x] 2.3 `core.confirm --reapply` 应用 6 个概念（3 active / 3 skipped）与 6 条 `concept_sources`；导入 `seeds/question_bank.json` 15 题；验证：`concepts=6`、`concept_sources=6`、`question_bank=15`。
- [x] 2.4 启动时优先读 `CONTENT_DIR/concepts.yaml` + `seeds/question_bank.json`，缺失才退回 fixture；测试用 `CONTENT_DIR=tmp_path`；验证：真实库启动无 `NoSessionAvailable`，测试仍用 3 概念 fixture。

## 3. 检索与短词回退

- [x] 3.1 `Store.search_fts` 对 <3 字词加子串回退，并入关键词臂；验证：`test_short_terms_fall_back_to_substring`（「工具」「上下文」）。
- [x] 3.2 `RetrievedChunk` 增加 `fts_hit` 与 `vector_score`；`_vector_ids` 返回余弦分数；验证：自由对话无命中判定可区分关键词命中与余弦命中。
- [x] 3.3 `bff/retrieval.py` 增加 `retrieve_text`、`is_grounded`、`sources_payload`；验证：真实库查询「模型自作主张」返回 2 条出处。

## 4. 自由对话 RAG

- [x] 4.1 `_handle_free_talk` 在 LLM 前检索；`build_free_talk_messages` 接收材料段与 `grounded`；验证：真实 smoke 回答带 `[1]` 引用。
- [x] 4.2 无命中阈值 `RETRIEVAL_MIN_COSINE=0.35`；teach 模式确定性加「材料里没有直接讲到。」；验证：真实 smoke「什么是 区块链」输出前缀 + 标注「这不是材料内容」。
- [x] 4.3 `reply` 事件带 `sources` 与 `grounded`；验证：WebSocket 用例断言 sources 非空/为空。

## 5. 引用、文本入口与前端

- [x] 5.1 `append_conversation_message` 支持 `sources`，写 `sources_json`；`conversation_load` 返回 sources；验证：`test_assistant_sources_are_persisted`、WS 用例刷新后仍可见。
- [x] 5.2 无会话 `text` 消息走自由对话；`_handle_free_talk_text` 复用同一回复函数；验证：WS 文本用例。
- [x] 5.3 前端：无会话显示文本框；`sendFreeTalkText` 发 `type=text`；助手消息下方渲染「出处」；聊天区上移避免遮挡；验证：Playwright 输入「什么是 模型自作主张」出现 2 条出处、无控制台错误。

## 6. 验证

- [x] 6.1 `pytest -q`：252 passed。
- [x] 6.2 真实 provider smoke：知识库问题带 2 条出处；材料外问题 0 条出处且带「材料里没有」前缀。
- [x] 6.3 浏览器 smoke：新对话 → 输入 → 答案 + 出处；截图确认无重叠。

## Follow-up

- 20 条 Recall@5 基线：等材料补到 2–3 份后再跑（分块参数 280-420 也要同组查询对照）。
- 热项第三路、Coach 出题检索、reranker：不在本 change。
