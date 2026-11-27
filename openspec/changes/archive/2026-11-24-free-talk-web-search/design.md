# Design

## Context

- 自由对话的唯一编排点是 `bff/main.py:_free_talk_reply`：本地 `retrieve_text` → `is_grounded` → 提示词 → LLM → `sources_json` → TTS。
- 代码里没有任何联网搜索、网页抓取或 Search provider；`core/` 不依赖 httpx。本机没有搜索 key，DuckDuckGo/Google/Brave/Jina 不可达，Tavily/Bing API/SerpAPI/Exa 可达；没有 HTML 解析库。
- 设计 P3 允许「超纲兜底」，但 KB-06 把它标为不实现，RT-02 明确不接外部网页；本 change 只实现「自由对话兜底」，不改「不进每日五题热路径」。
- 现有来源载荷是 `{index,title,url,excerpt}`，落 `conversation_messages.sources_json`；加网页来源不需要 schema 变更。

## Goals / Non-Goals

**Goals:**

- 本地材料优先；只在显式要求、时效关键词或本地未 grounded 时联网。
- 搜索结果经过 content 预过滤和时间标注后，改写成 1–3 句口语答案，并带 1–3 条来源。
- 搜索失败可降级，不阻塞自由对话；来源可持久化、刷新可回看。

**Non-Goals:**

- 不做逐句事实核对、域名白名单、二次 LLM 核查、reranker、搜索结果缓存。
- 不把网页结果写进 hot 项、主知识库、`concept_sources` 或计分题。
- 不做 LLM query 改写；不做多轮搜索/多查询扩展。

## Decisions

### D1 Tavily + 可替换 Provider

用 Tavily（`POST https://api.tavily.com/search`，`search_depth=basic`，`max_results=5`，`include_answer=false`）。`core/ports.py` 定义 `SearchProvider`/`SearchHit`；BFF 实现 `TavilySearch`、`NullSearch`（未配置返回空）与 `FakeSearch`（仅 fake/测试）。

- 备选：Bing API / SerpAPI（都要订阅 key，配置更重）；DuckDuckGo 抓取（本机不可达）；自建爬虫（没有 HTML 解析库）。
- 理由：Tavily 返回清洗后的 content，能同时支撑预过滤和口语化改写；免费额度足够个人使用。

### D2 触发规则

`core/router.py` 增加纯函数 `needs_web(text)`：显式词（联网/上网查/搜索一下/查一下/搜一下/最新消息）+ 时效词（最新/最近/今天/现在/当前/目前/新闻/价格/股价/汇率/发布/上线/更新/版本/谁/什么时候/哪年/今年）。`should_search = explicit or needs_web(text) or not local_grounded`。

- 备选：每轮 LLM 分类（多一次调用和延迟）；只认显式（漏掉时效问题）。
- 理由：规则可测、零额外调用；误判最多多搜一次。

### D3 Query 构造

搜索 query = 用户原文；时效问题追加当前年份/月份（例如「2026年11月」）。不改写、不扩写。

- 备选：LLM 改写成搜索 query（更准但多一次调用）。
- 理由：先验证主链路；真实问题出现搜不准时再加改写。

### D4 结果预过滤

Tavily 返回后：丢弃 content 为空或少于 80 字的结果；要求 content 与 query 至少共享一个 2 字以上词项（中文用 2-gram，英文用词）；按 URL 去重；按 Tavily score 排序取 top3。

- 备选：只信 snippet/score，不过滤（容易注入空页或无关页）；抓页面正文（要新增 HTML 解析库）。
- 理由：预过滤是纯规则、可测，能在不抓页面的前提下满足「来源校验」的最低要求。

### D5 时间标注

每条网页来源带 `domain`、`retrieved_at`；`published_at` 可用就标，不可用标「未标注日期」。`retrieved_at` 用当前日期，不冒充发布时间。

- 备选：只显示域名；只显示发布时间。
- 理由：用户要判断时效，必须同时知道「页面什么时候写的」和「我什么时候查的」。

### D6 提示词与冲突

提示词分两段：「材料摘录（已核实，编号 1..n）」与「网络检索（未核实时效内容，编号 n+1..）」。系统指令：材料优先；网页只作补充；冲突时并列说「材料说 X，网上有来源说 Y」；联网答案 1–3 句口语化，并提示「网上信息，可能变化」。

- 备选：把网页混进材料段（模型会误当已核实）；只给网页不给材料（丢失内部优先）。
- 理由：分开标注能让模型和用户都看清依据层级。

### D7 来源统一与持久化

本地与网页来源统一成 `{index,title,url,domain,excerpt,kind,published_at,retrieved_at}`；本地 `kind=material`，网页 `kind=web`。保持 `sources_json` 自由 JSON，不建新表；前端在网页来源下显示域名和日期。

- 备选：新建 `web_sources` 表（当前不需要按来源查询）；只存事件不落库（刷新丢失）。
- 理由：现有 `sources_json` 已覆盖回放需求；等搜索量上来再考虑缓存表。

### D8 失败与超时

搜索超时 8 秒；失败发 `warning(stage=search)`，继续用本地结果。本地也未 grounded 时：搜索失败说「材料里没有直接讲到，联网搜索暂时不可用」；搜索成功但无可用结果说「材料里没有直接讲到，联网也没查到」。

- 备选：搜索失败直接报错（阻塞对话）；无限重试（拖长等待）。
- 理由：自由对话要保证可用性；两种失败要区分，便于用户判断是网络问题还是没搜到。

### D9 配置与注册表

`SEARCH_KIND=tavily`；`TAVILY_API_KEY`；`SEARCH_BASE_URL` 默认 `https://api.tavily.com`；`SEARCH_MAX_RESULTS=5`；`SEARCH_TIMEOUT_SECONDS=8`。`real` 模式缺搜索配置 MUST NOT 导致启动失败；`modes.search` 为 `real|off|fake`，不纳入 `any_fake`。

- 备选：把搜索加入 `required`（破坏现有 real 部署）；未配置时用 FakeSearch（会把伪造出处写进用户可见引用）。
- 理由：搜索是可选增强，失败应降级；FakeSearch 只用于测试。

### D10 设计文档同步

P3 不改（「材料入口或超纲兜底」本来就允许）。更新 KB-06 与 RT-02 的「超纲兜底不实现 / 不接外部网页」措辞，明确「仅自由对话兜底，仍不进每日五题/知识库/计分题」；`FREEZE.md` 登记这次边界澄清；`VERSIONS.md` 更新哈希；`GLOSSARY.md` 补「联网搜索/来源/检索」三个词。

- 备选：只在代码里加开关，不改文档（会与已 accepted 的设计冲突）。
- 理由：仓库的治理规则要求改变已接受边界必须有记录。

## Risks / Trade-offs

- [没有 Tavily key] → 先实现 NullSearch/FakeSearch 与全部测试；真实 smoke 等用户补 key。
- [Tavily 不返回发布日期] → 标「未标注日期」并显示 `retrieved_at`；不假装有日期。
- [预过滤误杀相关结果] → 2 字词项重叠是宽松下限；top3 保留冗余；真实 smoke 后调阈值。
- [搜索延迟拖慢回答] → 只在必要时搜；8 秒超时；失败不阻塞。
- [成本] → 触发规则限制调用；先不做缓存；真实 smoke 记录每次查询成本。
- [模型忽略网页或覆盖材料] → 提示词分开材料/网页并要求冲突并列；WS 用例覆盖冲突场景。
- [隐私] → 搜索 query 会发给 Tavily；在 `.env.example` 与 README 标注。
- [边界回归] → 测试断言 `concept_sources`/`materials`/`hot_items` 行数不变；Coach 不使用网页来源。

## Migration Plan

1. 加配置与 `.env.example`；没有 key 时 `search=off`，行为与现在一致。
2. 实现 provider、路由、提示词、来源合并与前端展示；默认只在触发条件满足时调用。
3. 用户补 `TAVILY_API_KEY` 后跑真实 smoke；不达标可用 `SEARCH_KIND=off` 回滚。
4. 文档与 FREEZE 记录随实现一起提交。

## Open Questions

- Tavily 中文查询的召回质量和免费额度是否足够，需要真实 key 后实测；不影响当前契约与任务拆分。
