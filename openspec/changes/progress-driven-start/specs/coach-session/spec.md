# Spec Delta

## ADDED Requirements

### Requirement: 会话启动按进度选主概念

Coach SHALL 在 `start` 时按“最近失手 → 掌握度最低 → 无信号稳定随机”选主概念。最近失手 MUST 取该主题最近一次有评分的作答（`new` 或 `review`），任一题 <60 或该次均分 <80 即命中；未结算但已作答的题 MUST 参与。选中主题 MUST 作为本场主概念（`role=new`），5 题配比与最逾期复习概念 MUST 保持不变。没有 active 概念时 MUST 报无可用会话。新建或切换对话 MUST NOT 改变选择。

#### Scenario: 最近失手优先

- **WHEN** 主题 X 最近一次作答有题 <60，且其他主题没有失手
- **THEN** 主概念为 X，第 1 题属于 X，开场白提到 X

#### Scenario: 同日答错也能命中

- **WHEN** 用户今天答错 X 并结束会话，X 的 `review_due_at` 为次日
- **THEN** 再次开始时仍选 X

#### Scenario: 没有失手选最低掌握度

- **WHEN** 没有最近失手，存在 mastery 更低的 active 主题
- **THEN** 主概念为 mastery 最低者；并列时久未学者优先

#### Scenario: 全 0 稳定随机

- **WHEN** 没有失手，active 主题都是 mastery 0 且从未学过
- **THEN** 从池中按当天种子稳定选一个；同一天两次选择一致

#### Scenario: 新建对话不改变判断

- **WHEN** 用户新建自由对话后再次开始学习
- **THEN** 仍选中同一个最近失手主题

#### Scenario: 没有 active 概念

- **WHEN** 没有 `status=active` 的概念
- **THEN** 返回无可用会话，不创建空会话

### Requirement: session_ready 带开场白

start 返回的 `session_ready` MUST 带 `intro`（非空字符串）与可选 `focus`（`concept_id`、`name`、`reason_kind`）。`intro` MUST 由程序按事实拼，点名本场主概念并说明档位（最近失手/掌握度最低/随机）；BFF MUST 先推送 `intro` 的 TTS 音频，再推送第一题音频。`intro` 的 TTS 失败 MUST NOT 阻塞会话，文本仍 MUST 可见。`session_resume` MUST NOT 重播 `intro`。

#### Scenario: 最近失手开场

- **WHEN** 主概念因最近失手被选中
- **THEN** `intro` 包含主题名与“没答好/先补上”类事实，先于第一题音频播放

#### Scenario: 最低掌握度开场

- **WHEN** 主概念因掌握度最低被选中
- **THEN** `intro` 包含主题名与当前掌握度

#### Scenario: TTS 失败

- **WHEN** `intro` 的 TTS 调用失败
- **THEN** 会话继续，第一题照常展示与播放，`intro` 文本仍可见

#### Scenario: 同日恢复

- **WHEN** 用户同日发送 `session_resume`
- **THEN** 返回的 `session_ready` 不重播 `intro`
