# Design

## Context

见 `proposal.md` 的「Why」与真实 smoke 记录 `docs/designs/web-search-smoke-20261124.md`。

现状：

- `core/router.py` 的 `_WEB_EXPLICIT` 已定义 5 个联网触发词（联网、上网查、搜索一下、搜一下、查一下），`needs_web` 用它们判断显式联网。
- `search_query(text, today)` 对非时效问题原样返回用户原文，时效问题追加年月；`bff/main.py` 用它作为 Tavily query，也用它做预过滤的匹配基准。
- `bff/web_sources.py` 的 `filter_web_results` 把 query 按空白切词，中文词再展开成全部 2-gram，任一 2-gram 出现在 content 就保留。

## Goals / Non-Goals

**Goals:**

- 显式联网请求的 Tavily query 不带指令词，只有问题本身。
- 停用词与触发词不再构成「词项重叠」，垃圾结果落不到「至少共享一个词项」的口子。
- 没有实义词项的 query 不产生网页来源，走已有 `empty` 文案。

**Non-Goals:**

- 不改触发条件、Tavily 参数、top3、来源结构、日期标注与兜底文案。
- 不做 LLM query 改写、不扩写、不加同义词；不改 reranker/域名白名单（仍是 non-goal）。
- 不动本地检索的 grounding 阈值（smoke 的 3.4 发现单独记录）。
- 不处理英文停用词；当前问题集是中文。

## Decisions

### D1 触发词剥离放在 `search_query`，复用 `_WEB_EXPLICIT`

- 把 `_WEB_EXPLICIT` 改名为公开的 `WEB_TRIGGER_WORDS`，`explicit_web_request` 与 `search_query` 共用，`bff/web_sources.py` 也导入它作为停用词来源，避免三处维护两份词表。
- `search_query` 先按长度倒序把触发词替换为空格，再压缩空白；`needs_web` 仍用用户原文判断，剥离不影响触发。
- 剥离后只剩空白/标点时返回空字符串，表示「没有可检索内容」。

备选：在 `main.py` 里先剥再传给 `search_query`（多一处调用点，且过滤侧还要再剥一次）；用正则匹配「联网」等词（现有实现就是子串匹配，保持一致）。

### D2 停用词表：小表 + 复用触发词

`bff/web_sources.py` 维护一个约 20 词的 `WEB_STOPWORDS`：触发词（来自 `WEB_TRIGGER_WORDS`）+ 高频虚词（这个/那个/这些/那些/什么是/是什么/什么/为什么/怎么/如何/可以/没有/不存在/是不是/能不能/可不可以/帮我/一下/请问/哪个/哪里/词条）。

匹配时先按长度倒序删除停用词，再提取词项，避免「不存在」被拆成「不存」「存在」后仍能命中。选小表而不是通用停用词表：可预测、可测、误杀面小；通用表会连专有名词组合一起删掉。

### D3 词项提取与空集处理

- 删除停用词后按空白/标点切词，长度 ≥2 的 token 进入词项；含中文的 token 再展开 2-gram。
- 词项集为空时 `filter_web_results` 直接返回 `[]`，不再遍历 hits。
- 有实义词项但都不在 content 里时，结果照旧被丢弃；全部丢弃后 `main.py` 已把 `web_status` 设为 `empty`，无需改。

### D4 剥空的 query 不调用搜索

`main.py` 拿到 `search_query` 后先判空：为空则不调用 Tavily，直接 `web_status="empty"`，省一次付费调用，并让回答走「联网也没查到」而不是「搜索暂时不可用」。这是唯一的行为分支新增。

## Risks / Trade-offs

- [停用词误杀] 例如「存在与不存在」这类把虚词当主题的问题会被过滤 → 词表保持小，测试同时覆盖「垃圾被丢」与「正常问题保留」两类用例。
- [只匹配一个实义 2-gram 仍可能放行] 例如 content 恰好含「词条」 → 把「词条」纳入停用词；仍属概率性过滤，报告里已注明不做 reranker。
- [显式请求被剥空] 用户只说「联网查一下」时不搜索，回答「联网也没查到」 → 符合 D4 预期，spec 已写场景。
- [时效词注入的日期 token] query 末尾「2026年11月」会贡献 `11` 等弱词项 → 现状已如此，本次不扩大处理；如需更严可后续单独评估。
- [改名 `_WEB_EXPLICIT`] 只是常量改名，无外部调用；测试与 `needs_web` 覆盖其语义。

## Migration Plan

无数据迁移。回滚即还原 `core/router.py` 与 `bff/web_sources.py` 两个函数及常量名；已落库的 `sources_json` 不受影响。

## Open Questions

无。
