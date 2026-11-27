# Spec Delta

## ADDED Requirements

### Requirement: 单元开场可带一句生活素材

`session_ready` 的 `intro` MUST 允许在原有进度开场前加一句生活素材。该句 MUST 来自 `persona-life-pool` 的当日确定性抽取，且 MUST 与开场 TTS 使用同一份文本。没有可用素材时 MUST 保持原 `intro`。此要求 MUST NOT 改变题目、评分、复习、结算或 `session_resume` 的既有行为。

#### Scenario: 带生活句的开场

- **WHEN** 池中有当日素材，用户开始每日或复习单元
- **THEN** `session_ready.intro` 是“生活句 + 原进度开场”，开场 TTS 读同一段

#### Scenario: 无素材

- **WHEN** 池子关闭或当日没有可用素材
- **THEN** `session_ready.intro` 与原进度开场完全一致

#### Scenario: 恢复不重播

- **WHEN** 用户同日 `session_resume`
- **THEN** 不返回 `intro`，不注入生活句

#### Scenario: 不影响题目

- **WHEN** 开场带生活句
- **THEN** 第一题题干、题型、数量、评分与结算均不变
