# tts-playback Specification

## Purpose
定义反馈语音与题目语音的播放契约：反馈流式推送、题目音频预合成与缓存，以及 TTS 失败时不影响答题的降级行为。

## Requirements

### Requirement: 反馈流式推送

反馈语音 MUST 由 Breeze 流式合成，并按块推送 `audio_chunk`；每块 MUST 带单调递增的 `seq`，前端 MUST 按 seq 顺序播放。首块到达前 MUST NOT 要求整段合成完成。

#### Scenario: 流式反馈
- **WHEN** 评分完成并生成反馈文本
- **THEN** 服务端按 seq 依次推送多个 audio_chunk，前端按序播放

#### Scenario: 块序稳定
- **WHEN** 前端收到乱序或重复的 seq
- **THEN** 按 seq 排序去重后播放

### Requirement: 题目音频预合成与缓存

会话开始时第一题 MUST 同步合成，其余题目 MAY 后台预合成。音频缓存 MUST 以文本、音色、模型与格式的哈希为 key；命中 MUST 直接复用，未命中或合成失败 MUST 退回实时合成且 MUST NOT 阻塞答题。

#### Scenario: 缓存命中
- **WHEN** 同一题目文本、音色、模型与格式已缓存
- **THEN** 直接返回缓存音频，不重新调用 TTS

#### Scenario: 未命中
- **WHEN** 缓存不存在
- **THEN** 调用 TTS 合成并写入缓存目录

#### Scenario: 预合成失败
- **WHEN** 后台预合成某题失败
- **THEN** 该题播放时实时合成，会话继续

### Requirement: TTS 失败只显示文字

TTS 调用失败时 MUST 推送 warning(stage=tts)，只展示反馈或教学文字，MUST NOT 阻塞答题、教学回合或结算。

#### Scenario: 反馈合成失败
- **WHEN** Breeze 返回错误
- **THEN** 用户看到文字反馈，可继续下一题

#### Scenario: 教学回复合成失败
- **WHEN** `teach_reply` 的 TTS 失败
- **THEN** 用户看到教学文字，当前题仍可继续作答

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
