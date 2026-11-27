# Spec Delta

## ADDED Requirements

### Requirement: 人设、语气与记忆上下文

自由对话（非 agent 与 agent）MUST 在系统提示中注入 PERSONA 与 TONE；用户显式要求回忆时 MUST 再注入 MEMORY 块；MUST NOT 注入 LIFE（生活素材只在单元开场）。PERSONA、TONE、MEMORY 的顺序 MUST 由共享 composer 统一为 `PERSONA → TONE → MEMORY → TASK → CONTEXT → DISCIPLINE`（agent 工单 JSON 最后）。

#### Scenario: 自由对话带人设和语气

- **WHEN** 用户闲聊
- **THEN** 系统提示含 PERSONA 与 TONE，不含 LIFE

#### Scenario: 显式回忆

- **WHEN** 用户说“你还记得我之前说怕公式吗”
- **THEN** 系统提示增加 MEMORY 块，只含检索到的记忆

### Requirement: 情绪事件

自由对话在回复生成前更新情绪后 MUST 推送独立 `emotion` 事件 `{comfort, energy, tone}`；随后才推送 `reply`。答题/评分路径 MUST NOT 推送 `emotion`。

#### Scenario: 闲聊先更新情绪

- **WHEN** 用户说“今天好累”
- **THEN** 先收到 `emotion`，再收到 `reply`

### Requirement: teach 任务层

自由对话 teach 模式 MUST 采用“先正面解释，再最多追问一句，请对方用自己的话说一遍”；MUST NOT 再用笼统的“不要反问”压掉追问。解释 MUST 仍不超过 100 字、不说黑话、不评分。

#### Scenario: 讲完追问

- **WHEN** 用户问“什么是 agent”
- **THEN** 先正面解释，再最多追问一句请对方复述

#### Scenario: 不变成课堂

- **WHEN** 用户在闲聊模式
- **THEN** 不强制走“讲概念 → 复述”流程
