# Spec Delta

## MODIFIED Requirements

### Requirement: 今日单元提议只读且复用会话选题

系统 SHALL 提供 `GET /api/kb/unit/proposal`，按当天日期复用 Coach 的进度主概念选题、最逾期复习概念与 `build_session_plan` 的 5 个槽位；响应 MUST 包含主概念、复习概念、`main.reason_kind`（`recent_miss` / `lowest_mastery` / `no_signal`）、理由、题型、预计 20 分钟与 `available`。该接口 MUST NOT 写数据库、调用 LLM/TTS/搜索或生成题目。

#### Scenario: 最近失手主概念

- **WHEN** 某主题最近一次作答有题 <60
- **THEN** 提议的 `main` 是该主题，`reason_kind=recent_miss`，理由说明最近得分

#### Scenario: 最低掌握度主概念

- **WHEN** 没有最近失手，存在 mastery 最低的 active 主题
- **THEN** `main` 是该主题，`reason_kind=lowest_mastery`

#### Scenario: 无信号随机

- **WHEN** 没有最近失手，active 主题都是 mastery 0 且从未学过
- **THEN** `main` 从池中按当天种子稳定选一个，`reason_kind=no_signal`

#### Scenario: 有主概念且有到期复习

- **WHEN** 存在 active 主概念且存在到期复习
- **THEN** 提议返回 `kind=daily`，主概念承担概念/业务/取舍 3 题，复习概念承担成本/综合 2 题，并给出两者理由

#### Scenario: 没有到期复习

- **WHEN** 没有到期复习且存在 active 主概念
- **THEN** 提议返回 5 个属于主概念的槽位，题型五型各 1

#### Scenario: 主概念与复习概念相同

- **WHEN** 最逾期复习概念就是当天主概念
- **THEN** 提议返回 `same_concept=true`，5 题同概念且角色为 3 new + 2 review

#### Scenario: 只有到期复习

- **WHEN** 没有可出的新概念但有到期复习
- **THEN** 提议仍按进度选题选一个已学过的 active 主题作为主概念，复习概念承担 2 题；不再主动进入 review-only

#### Scenario: 没有可出题

- **WHEN** 没有 `status=active` 的概念
- **THEN** 返回 200 且 `available=false`，带不可用原因，不创建会话

#### Scenario: 提议不写库

- **WHEN** 连续调用提议接口
- **THEN** `sessions`、`agent_sessions`、`concepts` 不因该请求发生变化，且两次结果一致

### Requirement: 掌握程度总览只读

系统 SHALL 提供 `GET /api/kb/overview`，返回在学（`active`）概念的数量、平均 mastery（一位小数）、0–5 分布、薄弱项数、待复习/逾期数、概念列表与最近 5 个单元。薄弱项 MUST 包含“最近失手”（任一题 <60 或该次均分 <80）以及 `mastery<=1` 且学过的 active 概念。总览 MUST NOT 写数据库或调用外部服务；`known`/`skipped`/`proposed`/`orphaned` MUST 只给计数，不展开列表。

#### Scenario: 正常总览

- **WHEN** 存在多个 active 概念
- **THEN** 返回 active 数、平均 mastery、0–5 分布、due/overdue/weak 与按 mastery 升序的概念列表

#### Scenario: 薄弱与待复习口径

- **WHEN** 概念最近一次作答有题 <60，或 `mastery<=1` 且 `last_seen` 非空
- **THEN** 计入 `weak`；`review_due_at <= today` 计入 `due`，早于 today 计入 `overdue`

#### Scenario: 空知识库

- **WHEN** 没有 active 概念
- **THEN** 返回零计数、`avg_mastery=null`、空概念列表，不报错

#### Scenario: 最近单元

- **WHEN** 已有多场已结算会话
- **THEN** 返回最近 5 场的日期、kind、status、得分与涉及概念名，review-only 也包含

#### Scenario: 总览不写库

- **WHEN** 调用总览接口
- **THEN** 数据库中的 concepts/sessions/session_questions 不因该请求变化
