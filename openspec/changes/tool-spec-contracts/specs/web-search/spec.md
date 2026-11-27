# Spec Delta

## MODIFIED Requirements

### Requirement: 搜索触发由 agent 决定

自由对话与会话内 teach/clarify 是否需要调用 `search_web` MUST 由 agent 在回合预算内决定；MUST NOT 再用关键词、时效词或 grounded 阈值作为程序触发条件。每回合最多 4 次 `search_web`；用户显式要求联网时模型 SHOULD 直接查网页。

#### Scenario: 用户显式要求联网
- **WHEN** 用户说「联网查一下 X」
- **THEN** 模型可以直接调用 `search_web`，不必先满足任何关键词条件

#### Scenario: 材料足够
- **WHEN** 本地材料已能回答问题且用户没有要求联网
- **THEN** 模型可以不调用 `search_web`

#### Scenario: 网页次数用尽
- **WHEN** 本回合已调用 4 次 `search_web`
- **THEN** 第五次请求返回 `budget_exhausted` 观测，不执行搜索
