# Tasks

## 1. Provider 与配置

- [x] 1.1 在 `core/ports.py` 增加 `SearchHit` 与 `SearchProvider` 协议；在 `bff/providers/fake.py` 增加 `FakeSearch`，并加一个未配置时返回空列表的 `NullSearch`；验证：端口契约测试覆盖 `search()` 返回结构与空结果。
- [x] 1.2 新建 `bff/providers/tavily.py`：`POST {base_url}/search`，`search_depth=basic`、`max_results=5`、`include_answer=false`，解析 `title/url/content/score/published_date`，错误统一 `ProviderError`；验证：`httpx.MockTransport` 测试请求体、鉴权头、返回解析与 HTTP 错误。
- [x] 1.3 `bff/config.py` 增加 `search: Endpoint`、`search_max_results`、`search_timeout_seconds`，读 `SEARCH_KIND/TAVILY_API_KEY/SEARCH_BASE_URL/SEARCH_MAX_RESULTS/SEARCH_TIMEOUT_SECONDS`；`SEARCH_BASE_URL` 默认 Tavily 域名，保证「只有 key」也算已配置；验证：config 单测覆盖默认值与显式覆盖。
- [x] 1.4 `bff/providers/registry.py` 增加可选 `search`：`real` 模式缺搜索配置 MUST NOT 启动失败；`modes["search"]` 为 `real/off/fake`，不纳入 `any_fake`；`aclose` 关闭搜索客户端；验证：`test_registry.py` 覆盖 off/real/fake 三种模式，旧断言同步更新。
- [x] 1.5 `.env.example` 与 `README.md` 增加搜索配置块（含「未配置则 search=off」与隐私提示）；验证：按文档填入 key 后 `/health` 显示 `modes.search=real`。

## 2. 路由与 Query

- [x] 2.1 `core/router.py` 增加纯函数 `needs_web(text)`：显式词 + 时效词；验证：单测覆盖显式、时效、普通问题、空字符串。
- [x] 2.2 `bff/main.py:_free_talk_reply` 接入 `should_search = explicit or needs_web(text) or not grounded`；本地已 grounded 且无显式/时效信号时 MUST NOT 调用搜索；验证：WS 用例覆盖「本地命中不搜」「显式联网即使命中」「时效问题」「本地未命中」。
- [x] 2.3 Query 构造：默认用用户原文；时效问题追加当前年月；验证：单测固定时钟断言 query 文本；真实搜索前不调用 LLM 改写。

## 3. 结果预过滤与时间标注

- [x] 3.1 实现 `filter_web_results(query, hits)`：丢弃 content 为空或少于 80 字、无 2 字以上词项重叠的结果；按 URL 去重；按 score 取 top3；验证：单测覆盖空 content、短 content、无重叠、重复 URL、超过 3 条。
- [x] 3.2 实现来源归一化：`domain` 从 URL 提取，`published_at` 缺失时置 None，`retrieved_at` 用当前日期；验证：单测覆盖有日期/无日期/非法 URL。
- [x] 3.3 搜索超时 8 秒与异常：发 `warning(stage=search)`，继续本地回答；验证：WS 用例用超时 fake 搜索断言 warning + 回答仍返回。

## 4. 提示词、来源与前端

- [x] 4.1 `core/free_talk.py` 增加网络检索段与指令：材料编号在前、网页编号在后；材料优先、冲突并列、1–3 句口语化、提示「网上信息，可能变化」；验证：提示词单测覆盖 grounded/un-grounded 与冲突指令。
- [x] 4.2 `bff/retrieval.py` 统一来源结构：本地 `kind=material`，网页 `kind=web` 且带 `domain/published_at/retrieved_at`；`sources_payload` 输出统一编号；验证：单测断言混合来源的编号、字段与顺序。
- [x] 4.3 `conversation_messages.sources_json` 保存混合来源；`conversation_load` 原样返回；验证：WS 用例刷新后网页来源仍可见。
- [x] 4.4 前端 `web/app.js`/`web/style.css` 在网页来源下显示「域名 · 日期」，材料来源保持现状；验证：Playwright 输入时效问题出现网页来源与日期，刷新后仍显示。

## 5. 边界与文档

- [x] 5.1 加边界测试：一次联网自由对话后 `concept_sources`、`materials`、`hot_items`、`session_questions` 行数不变；Coach 开始会话不使用网页来源；验证：Store 计数断言 + WS 用例。
- [x] 5.2 更新 `docs/designs/FREEZE.md`：登记「超纲兜底从‘不实现’改为‘仅自由对话兜底’」，明确不进每日五题/知识库/计分题；验证：FREEZE 记录与实现一致。
- [x] 5.3 更新 `knowledge-ingestion-v0.1.md` 的 KB-06 与 `realtime-knowledge-v0.1.md` 的 RT-02 措辞；`VERSIONS.md` 更新哈希；验证：SHA-256 与 `VERSIONS.md` 一致。
- [x] 5.4 `GLOSSARY.md` 补「联网搜索」「来源」「检索」三个词，区分本地检索/联网搜索/热项；验证：词条不含实现细节，术语与代码一致。

## 6. 验收

- [x] 6.1 10 条场景验收：5 条材料内（不联网）、3 条时效（联网）、2 条材料外非时效（联网或明确说没有）；验证：逐条检查路由、`sources`、日期、冲突表述。
- [x] 6.2 用户补 `TAVILY_API_KEY` 后跑真实 smoke：记录延迟、返回条数、日期字段与单次成本；验证：真实调用报告写入 `docs/designs/`；没有 key 时标记 deferred，不伪造结果。（2026-11-24 完成：`docs/designs/web-search-smoke-20261124.md`）
- [x] 6.3 全量 `pytest -q` 与 `openspec validate free-talk-web-search --strict`；验证：0 failed、change valid。

## Workflow follow-up

- 先归档 `free-talk-rag`，确保主 `free-talk` spec 已包含本地检索与引用要求，再归档本 change。
- 评审通过后归档 change：`openspec archive free-talk-web-search`。
- 归档后确认 `openspec/specs/web-search/spec.md` 与 `openspec/specs/free-talk/spec.md` 已同步。
