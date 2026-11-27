# Spec Delta

## ADDED Requirements

### Requirement: StepBrief 增加语气与记忆

`StepBrief` MUST 增加可选 `tone_hint` 与 `memory_context`；两者 MUST 只含当前回合的一句话语气提示和显式回忆结果。`StepBrief` MUST 仍不可变，MUST NOT 含未来题目、未作答题的 rubric、`reference_answer` 或 `answer_key`。

#### Scenario: 自由对话带语气

- **WHEN** 用户在没有会话时闲聊
- **THEN** StepBrief 含当前 `tone_hint`

#### Scenario: 显式回忆

- **WHEN** 用户要求回忆
- **THEN** StepBrief 含检索到的 `memory_context`，不含其他记忆

### Requirement: 系统提示拼装顺序

Agent 系统提示 MUST 由共享 composer 按 `ROLE → PERSONA → TONE → MEMORY → TASK → CONTEXT → DISCIPLINE → DATA` 拼装；`DATA` MUST 是工单 JSON，永远最后；MUST NOT 在工单 JSON 之后再追加指令。

#### Scenario: 工单最后

- **WHEN** 构建任意 agent 回合
- **THEN** 工单 JSON 是最后一段

#### Scenario: 纪律优先

- **WHEN** 人设/语气与纪律冲突
- **THEN** 纪律生效

### Requirement: 答题回合不更新情绪

Agent 回合 MUST 仍只发生在 `free_talk` / `teach` / `clarify`；作答、评分、结算 MUST NOT 启动 agent 回合，也 MUST NOT 触发情绪更新或推送 `emotion`。

#### Scenario: 答题

- **WHEN** 用户提交答案
- **THEN** 不进入 agent 回合，不更新情绪
