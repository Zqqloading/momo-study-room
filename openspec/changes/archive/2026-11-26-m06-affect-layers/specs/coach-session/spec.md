# Spec Delta

## ADDED Requirements

### Requirement: 开场生活 + 记忆

`session_ready.intro` MUST 按“生活句（≤60 字） → 记忆块（≤300 字） → 原进度 intro”拼接；前导合计 MUST ≤360 字。事件 `intro` 与开场 TTS MUST 使用同一份文本。没有生活句或没有记忆时 MUST 跳过对应段；`session_resume` MUST NOT 重播开场。

#### Scenario: 生活 + 记忆

- **WHEN** 当天有生活素材且有 2 条合格记忆
- **THEN** `intro` 以生活句开头，随后是记忆块与进度 intro

#### Scenario: 只有生活

- **WHEN** 记忆为空但生活池有当日素材
- **THEN** `intro` = 生活句 + 原进度 intro

#### Scenario: 恢复

- **WHEN** 用户同日 `session_resume`
- **THEN** 不返回 `intro`

### Requirement: 评分反馈措辞

评分提示词 MUST 只新增一句“反馈只评价答案，不评价用户本人；不讽刺、不贬低”。分档、题型封顶、0-100 校验、JSON 契约与参考答案流程 MUST 逐字保持不变；MUST NOT 因这句话改变分数。

#### Scenario: 措辞约束

- **WHEN** 用户答错
- **THEN** `why` 只评价答案，不评价用户本人

#### Scenario: 评分口径不变

- **WHEN** 同一答案在改动前后评分
- **THEN** 分档、封顶和分数不变

### Requirement: session_ready 带情绪

`session_ready` MUST 带 `emotion: {comfort, energy, tone}`；没有情绪数据时 MUST 返回中间态。该字段 MUST NOT 改变题目、评分、复习或结算行为。

#### Scenario: 开始单元

- **WHEN** 用户开始每日或复习单元
- **THEN** `session_ready` 含当前 emotion
