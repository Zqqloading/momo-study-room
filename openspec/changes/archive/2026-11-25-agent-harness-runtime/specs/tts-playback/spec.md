# Spec Delta

## MODIFIED Requirements

### Requirement: TTS 失败只显示文字

TTS 调用失败时 MUST 推送 warning(stage=tts)，只展示反馈或教学文字，MUST NOT 阻塞答题、教学回合或结算。

#### Scenario: 反馈合成失败
- **WHEN** Breeze 返回错误
- **THEN** 用户看到文字反馈，可继续下一题

#### Scenario: 教学回复合成失败
- **WHEN** `teach_reply` 的 TTS 失败
- **THEN** 用户看到教学文字，当前题仍可继续作答

## ADDED Requirements

### Requirement: 教学/澄清回复朗读

会话内 `teach_reply` MUST 用 TTS 朗读；`audio_chunk` MUST 带 `utterance=teach` 与递增 `seq`，前端 MUST 按 seq 顺序播放。朗读结束后 MUST 回到当前题，MUST NOT 推进题目或改变分数。TTS 失败 MUST 只显示文字，不阻塞回合。

#### Scenario: 讲讲朗读
- **WHEN** 用户发送 `intent=teach` 并收到 `teach_reply`
- **THEN** 服务端推送 utterance=teach 的 audio_chunk，前端按序播放

#### Scenario: 澄清朗读
- **WHEN** 用户发送 `intent=clarify`
- **THEN** 解释文本被朗读，结束后仍停留在当前题

#### Scenario: 朗读失败
- **WHEN** 教学回复的 TTS 调用失败
- **THEN** 只显示文字，当前题与分数不变
