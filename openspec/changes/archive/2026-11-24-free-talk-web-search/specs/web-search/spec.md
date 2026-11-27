# Spec Delta

## Purpose

定义自由对话在本地材料不足时调用外部搜索、过滤结果、标注时间的契约；搜索结果只作对话来源，不进入主知识库、热项或计分题出处。

## ADDED Requirements

### Requirement: 搜索 Provider 可选

系统 SHALL 通过可替换的 `SearchProvider` 调用外部搜索。搜索未配置时 MUST 返回空结果并标记 `search=off`，MUST NOT 阻止 BFF 启动；`fake` 模式 MAY 使用确定性 FakeSearch 供测试。

#### Scenario: 未配置搜索
- **WHEN** 没有 `TAVILY_API_KEY` 或其他搜索配置
- **THEN** `/health` 的 `modes.search` 为 `off`，自由对话仍可用，`reply.sources` 不含网页来源

#### Scenario: fake 模式
- **WHEN** `PROVIDER_MODE=fake`
- **THEN** FakeSearch 返回确定性结果供测试，这些结果 MUST NOT 出现在真实用户对话里

### Requirement: Tavily 搜索与结果预过滤

系统 SHALL 调用 Tavily 搜索，MUST 请求 `max_results=5`。注入提示词前 MUST 丢弃 content 为空或少于 80 字的结果，MUST 要求 content 与 query 至少共享一个 2 字以上的词项，MUST 按 URL 去重，最终 MUST 最多取 top3。

#### Scenario: 正常过滤
- **WHEN** Tavily 返回 5 条，其中 2 条 content 为空、1 条与问题无词面重叠
- **THEN** 最多 2 条进入提示词

#### Scenario: 重复 URL
- **WHEN** 多条结果指向同一 URL
- **THEN** 只保留一条，其余丢弃

#### Scenario: 全部不可用
- **WHEN** 所有结果都被过滤或 content 不足
- **THEN** 视为没有网页结果，不注入网页段

### Requirement: 来源时间标注

每条网页来源 MUST 带 `domain` 与 `retrieved_at`。`published_at` 可用时 MUST 标注；不可用时 MUST 标「未标注日期」；MUST NOT 用 `retrieved_at` 冒充 `published_at`。

#### Scenario: 有发布时间
- **WHEN** Tavily 返回 `published_date`
- **THEN** 来源显示该日期，并同时保留 `retrieved_at`

#### Scenario: 无发布时间
- **WHEN** Tavily 没有返回日期
- **THEN** 来源显示「未标注日期」，并显示 `retrieved_at`

#### Scenario: 刷新后回看
- **WHEN** 用户加载同一对话
- **THEN** 网页来源的域名、发布日期和检索日期与当时一致

### Requirement: 搜索失败降级

搜索超过超时（默认 8 秒）或返回错误时 MUST 推送 `warning(stage=search)`，MUST 继续用本地结果回答，MUST NOT 让整轮自由对话失败。

#### Scenario: 搜索超时
- **WHEN** Tavily 调用超过 8 秒
- **THEN** 收到 `warning(stage=search)`，回答仍正常返回

#### Scenario: 本地有依据但搜索失败
- **WHEN** 本地 `grounded=True` 且搜索失败
- **THEN** 回答只依据本地材料，`sources` 不含网页来源

### Requirement: 搜索结果边界

搜索结果 MUST 只作为自由对话的 `sources`。MUST NOT 写入 `hot_items`、`concept_sources`、`materials` 或 `session_questions`；MUST NOT 参与评分或成为计分题出处。

#### Scenario: 不写知识库
- **WHEN** 一次自由对话使用了网页来源
- **THEN** `concept_sources`、`materials`、`hot_items` 行数不变

#### Scenario: 不进计分题
- **WHEN** 用户开始一场 Coach 会话
- **THEN** 题目与评分只使用本地题库与 `concept_sources`，不使用网页来源
