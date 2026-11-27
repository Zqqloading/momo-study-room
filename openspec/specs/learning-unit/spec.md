# learning-unit Specification

## Purpose

让用户每天先看到「今天学什么」的只读提议，再开始一场 5 题学习单元，并在单元结束后看到本单元概念的掌握度变化与全库掌握程度总览；面板临时寄居在主页面，后续可整体搬到管理后台。

## Requirements

### Requirement: 今日单元提议只读且复用会话选题

系统 SHALL 提供 `GET /api/kb/unit/proposal`，按当天日期复用 Coach 的主概念选题、最逾期复习概念与 `build_session_plan` 的 5 个槽位；响应 MUST 包含主概念、复习概念、理由、题型、预计 20 分钟与 `available`。该接口 MUST NOT 写数据库、调用 LLM/TTS/搜索或生成题目。

#### Scenario: 有主概念且有到期复习

- **WHEN** 存在可解锁的新概念且存在到期复习
- **THEN** 提议返回 `kind=daily`，主概念承担概念/业务/取舍 3 题，复习概念承担成本/综合 2 题，并给出两者理由

#### Scenario: 没有到期复习

- **WHEN** 没有到期复习且存在可解锁的新概念
- **THEN** 提议返回 5 个属于主概念的槽位，题型五型各 1

#### Scenario: 只有到期复习

- **WHEN** 没有可解锁的新概念但有到期复习
- **THEN** 提议返回 `kind=review`，5 个槽位全部属于复习概念

#### Scenario: 主概念与复习概念相同

- **WHEN** 最逾期复习概念就是当天主概念
- **THEN** 提议返回 `same_concept=true`，5 题同概念且角色为 3 new + 2 review

#### Scenario: 没有可出题

- **WHEN** 既没有可解锁的新概念也没有到期复习
- **THEN** 返回 200 且 `available=false`，带不可用原因，不创建会话

#### Scenario: 提议不写库

- **WHEN** 连续调用提议接口
- **THEN** `sessions`、`agent_sessions`、`concepts` 不因该请求发生变化，且两次结果一致

### Requirement: 学习单元是一场 5 题会话

学习单元 MUST 对应一场现有 5 题会话；开始单元 MUST 复用 `session_start`，系统 MUST NOT 为单元引入独立表、独立状态机或跨天进度。单元历史 MUST 由 `sessions` 与 `session_questions` 承载；当天结束后 MUST 允许再次开始新单元。

#### Scenario: 从提议开始

- **WHEN** 用户在知识库面板点「开始这个单元」
- **THEN** 客户端关闭面板并发送现有 `session_start`，不额外传概念 id，实际选题仍由 Coach 决定

#### Scenario: 当天重开

- **WHEN** 用户结束一场单元后再次从面板开始
- **THEN** 系统正常创建新一场会话，不限制当天场次

#### Scenario: 有进行中的单元

- **WHEN** 已有一场未结束的会话
- **THEN** 面板的开始按钮禁用并提示「当前单元进行中」，不打断当前会话

### Requirement: 掌握程度总览只读

系统 SHALL 提供 `GET /api/kb/overview`，返回在学（`active`）概念的数量、平均 mastery（一位小数）、0–5 分布、薄弱项数、待复习/逾期数、概念列表与最近 5 个单元。总览 MUST NOT 写数据库或调用外部服务；`known`/`skipped`/`proposed`/`orphaned` MUST 只给计数，不展开列表。

#### Scenario: 正常总览

- **WHEN** 存在多个 active 概念
- **THEN** 返回 active 数、平均 mastery、0–5 分布、due/overdue/weak 与按 mastery 升序的概念列表

#### Scenario: 薄弱与待复习口径

- **WHEN** 概念 `mastery <= 1` 且 `last_seen` 非空
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

### Requirement: 掌握程度展示口径

结果卡与面板 MUST 以概念名、0–5 mastery 与展示标签呈现掌握程度；MUST NOT 只显示 concept id。平均掌握度 MUST 显示为 `x.x / 5`，MUST NOT 换算百分比。标签 MUST 只用于展示，MUST NOT 参与 mastery 计算或写库。

#### Scenario: 单元完成且有更新

- **WHEN** completed daily 更新了某概念 mastery
- **THEN** 结果卡显示该概念 before→after、本场新题均分与 after 标签

#### Scenario: 提前结束或未评分

- **WHEN** 单元状态为 partial 或 unscored
- **THEN** 结果卡显著显示「掌握度未更新」及原因，不把未评分题按 0 分展示

#### Scenario: review-only

- **WHEN** 单元只有复习题
- **THEN** 结果卡显示复习均分与复习排期，标明 mastery 未更新

#### Scenario: 标签不写库

- **WHEN** 展示掌握度标签
- **THEN** `concepts.mastery` 与任何持久化字段不因标签文案变化

### Requirement: 临时知识库面板

主页面 SHALL 提供临时「知识库」面板，包含今日单元、掌握程度与最近单元三块；面板 MUST 不加载 3D 形象、不播放音频、不采集麦克风，MUST 支持关闭与错误重试。面板 MUST 是后续管理后台可整体搬走的边界：只依赖 `/api/kb/*` 与开始单元回调。

#### Scenario: 打开面板

- **WHEN** 用户点「知识库」
- **THEN** 面板并行请求提议与总览并展示三块内容，不触发会话或外部模型调用

#### Scenario: 提议不可用

- **WHEN** 提议返回 `available=false`
- **THEN** 面板显示原因与「补材料/确认概念」和「先自由对话」引导，开始按钮禁用

#### Scenario: 结果卡跳转

- **WHEN** 单元结果卡展示且用户点「查看知识库」
- **THEN** 面板打开并刷新总览与最近单元

#### Scenario: 面板不依赖会话渲染

- **WHEN** 移除或关闭面板
- **THEN** 头像、语音会话与答题主流程仍可正常工作
