# user-memory Specification

## Purpose

定义「关于用户」的长期记忆：只记原话、偏好、感受；有温度、有半衰期；单元结束异步写入，单元开始读取 top 3；自由对话可显式回忆；与学习进度完全分离。

## Requirements

### Requirement: 三类记忆与温度

记忆 MUST 只有三类：`quote`（原话，初始强度 1.0）、`preference`（偏好，0.75）、`feeling`（感受，0.5）。每条 MUST 有 `text`（一句提炼过的话，≤100 字，中性无主语）、`source_quote`（用户原话逐字摘录，≤200 字）、`source_session_id`、`source_question_id`（可空）、`user_id`。MUST NOT 存诊断性结论、分数、掌握度、错题、薄弱知识点、可识别身份信息。

#### Scenario: 原话与摘要

- **WHEN** 用户说了一句有信息量的话
- **THEN** 记忆保留 `source_quote` 原话，`text` 是一句中性摘要

#### Scenario: 诊断词被拒

- **WHEN** 模型输出“用户有数学焦虑”或“用户不擅长抽象概念”
- **THEN** 该条被丢弃并记 warning

### Requirement: 强度、半衰期与沉底

每条记忆 MUST 按 `current = strength * 0.5 ** (age_days / half_life_days)` 衰减；初始 `half_life_days=14`；被回忆时 MUST 保留当前强度，只把半衰期重抽为 `14 × U(0.5, 1.5)`（7-21 天），并更新 `last_recalled_at` / `recall_count`。`current < 0.05` MUST 视为沉底：不删除、不进主动排序。显式回忆 MUST 允许返回沉底记忆，并把强度拉到至少 0.1。

#### Scenario: 14 天减半

- **WHEN** 一条原话 14 天没有被回忆
- **THEN** 当前强度为初始值的一半

#### Scenario: 回忆只改半衰期

- **WHEN** 一条记忆被开场选中
- **THEN** 强度保留当前值，半衰期落在 7-21 天

#### Scenario: 沉底不主动

- **WHEN** 一条记忆当前强度 <0.05
- **THEN** 不出现在单元开场的主动排序里

### Requirement: 写入时机与提炼

系统 MUST 在学习单元结束（`completed` 或 `partial`）后异步提炼，≤5 条；MUST NOT 阻塞 `session_result`。输入 MUST 只含已落库的用户文本：`session_questions.answer_text` 与 `session_notes.input_text`（probe/teach_back）；MUST NOT 含 assistant 反馈、`why`、分数、掌握度。每条 `source_quote` MUST 是用户文本的逐字子串（空白归一化后）；否则丢弃。重复 `kind + 归一化 text` MUST 合并为一次显式回忆，不新增行。失败 MUST 重试 1 次，仍失败记 `memory_runs.status='failed'`，不向用户报错。

#### Scenario: 单元结束提炼

- **WHEN** 用户完成一场 5 题单元
- **THEN** 后台提炼 ≤5 条记忆并写入 `user_memories`

#### Scenario: 无内容

- **WHEN** 单元没有实质用户文本
- **THEN** 写 `memory_runs.status='empty'`，不新增记忆

#### Scenario: 来源不可追溯

- **WHEN** 模型给的 `source_quote` 不在用户文本里
- **THEN** 该条丢弃

### Requirement: 单元开场读取

单元开始时系统 MUST 取满足 `current >= 0.05` 的记忆，按当前强度降序、`last_recalled_at` 升序、`id` 升序；最多 3 条，渲染后 ≤300 字。渲染 MUST 用 `quote` 的原话（≤60 字）或 `text`，`preference`/`feeling` 用 `text`。选中后 MUST 按回忆公式更新强度/半衰期/时间。没有合格记忆时 MUST 不加块。

#### Scenario: 取 top 3

- **WHEN** 有 5 条可用记忆
- **THEN** 只取强度最高的 3 条，总渲染 ≤300 字

#### Scenario: 没有记忆

- **WHEN** 记忆表为空或全部沉底
- **THEN** 开场只保留生活句与原 intro

### Requirement: 用户显式回忆

自由对话（含 agent 自由对话）中，用户用“还记得/之前说过/帮我回忆”等意图并给出至少 2 个字的内容线索时，系统 MUST 用 FTS5 trigram 检索 `text` + `source_quote`，包含沉底记忆，取前 3 条；无命中时 MUST 返回空，让模型说没印象，不编造。会话内 `teach` / `clarify` 本期 MUST NOT 接入。

#### Scenario: 唤起沉底记忆

- **WHEN** 用户说“你还记得我之前说怕公式吗”
- **THEN** 即使该记忆已沉底，也能被检索并注入回忆块

#### Scenario: 没有线索

- **WHEN** 用户只说“你还记得吗”而没有内容
- **THEN** 不触发特殊检索，按普通对话处理

### Requirement: 与学习进度隔离

记忆 MUST 不读写 `concepts` / `sessions` / `session_questions` / `misconceptions`；MUST NOT 把分数、掌握度、错题、薄弱点写进 `user_memories`。`MEMORY_ENABLED=off` 时 MUST 不提炼、不读取、不拼开场，现有会话行为不变。

#### Scenario: 进度不变

- **WHEN** 记忆提炼成功
- **THEN** mastery、review_due_at、session_score 都不变

#### Scenario: 关闭记忆

- **WHEN** `MEMORY_ENABLED=off`
- **THEN** 单元开场没有记忆块，结束不提炼
