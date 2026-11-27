# Proposal

## Why

自由对话目前只查本地材料：材料里没有就直接回答「材料里没有」，即使问题具有时效性（最新版本、今天的新闻、当前价格）或用户明确要求联网，也无法给出可用答案。现有设计 P3 允许「超纲兜底」，但 `knowledge-ingestion-v0.1.md` 的 KB-06 把它标为不实现，`realtime-knowledge-v0.1.md` 的 RT-02 也明确不接外部网页，所以这条能力一直没有落地。

## What Changes

- 新增自由对话的联网兜底：本地材料优先；只有显式要求（联网/查一下/最新）、命中时效关键词，或本地检索未 grounded 时才调用联网搜索。
- 新增 `web-search` 能力：搜索 provider 端口、Tavily 适配器、未配置时的 `NullSearch`、测试用 `FakeSearch`；搜索结果做 content 预过滤（非空、≥80 字、与问题有词面重叠）、URL 去重、取 top3。
- 时间标注：`published_at` 有就标，没有标「未标注日期」；始终记录 `retrieved_at`；来源显示域名。
- 回答与引用：1–3 句口语答案 + 1–3 条来源；材料优先，网页与材料冲突时并列说明；搜索失败或超时发 `warning(stage=search)`，回退本地结果。
- 来源落 `conversation_messages.sources_json`，不建新表；网页来源带 `kind=web`、`domain`、`published_at`、`retrieved_at`。
- **边界收敛**：联网结果只作自由对话来源，MUST NOT 进入 hot 项、主知识库或计分题出处；不改 v2.0 P3 的「不进每日五题热路径」。
- 记录设计变更：新 OpenSpec change `free-talk-web-search`；`FREEZE.md` 登记「超纲兜底从‘不实现’改为‘仅自由对话兜底’」；KB-06 与 RT-02 的措辞同步。

## Capabilities

### New Capabilities

- `web-search`: 外部搜索的 provider 契约、Tavily 调用、结果预过滤、时间标注、失败降级与配置可选性。

### Modified Capabilities

- `free-talk`: 新增联网兜底的路由条件、材料与网页的来源合并、冲突表述、搜索失败回退与来源持久化。

## Impact

- 代码：`core/ports.py`（`SearchProvider`/`SearchHit`）、`bff/providers/tavily.py`、`bff/providers/fake.py`、`bff/providers/registry.py`、`bff/config.py`、`core/router.py`、`core/free_talk.py`、`bff/retrieval.py`、`bff/main.py`、`web/app.js`、`web/style.css`。
- 配置：`.env.example` 新增 `SEARCH_KIND`、`TAVILY_API_KEY`、`SEARCH_BASE_URL`、`SEARCH_MAX_RESULTS`、`SEARCH_TIMEOUT_SECONDS`；真实调用需要用户自行申请 Tavily key。
- 文档：`docs/designs/FREEZE.md`、`docs/designs/knowledge-ingestion-v0.1.md`（KB-06）、`docs/designs/realtime-knowledge-v0.1.md`（RT-02）、`docs/designs/VERSIONS.md`、`GLOSSARY.md`。
- 不做：hot 第三路、知识库自动入库、Coach 出题、reranker、逐句事实核对、域名白名单、搜索结果缓存。
