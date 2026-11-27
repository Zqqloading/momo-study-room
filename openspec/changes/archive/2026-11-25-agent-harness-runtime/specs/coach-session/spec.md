# Spec Delta

## MODIFIED Requirements

### Requirement: 会话协议

BFF SHALL 通过 WebSocket 暴露会话消息：客户端发送 `session_start`、`session_resume`、`answer`、`skip`、`finish`；`text` / `audio` MAY 带可选 `intent`（`teach` 或 `clarify`）。服务端推送 `session_ready`、`question`、`transcript`、`score`、`probe`、`teach_reply`、`feedback_end`、`session_result`、`session_expired`；agent 回合 MAY 推送 `agent_status`。`question` MUST 带 `index`、`total`（等于 planned）与 `question_type`；`score` MUST 带 `question_type`、`source_url`、`source_excerpt`，重复提交时 MUST 带 `duplicate=true`；`session_result` 的 `scores` MUST 带题型与出处；作答前的 `question` MUST NOT 带出处。`audio_chunk` MUST 带 `utterance`（`feedback`、`question` 或 `teach`）与递增 `seq`。

#### Scenario: 文本完成一场
- **WHEN** 客户端依次发送 `session_start` 与 5 条 `answer`
- **THEN** 每答一题收到 `score`，最后收到 `session_result`，DB 可回放全部题目、题型与出处

#### Scenario: 提前结束
- **WHEN** 客户端在 planned 题未答完时发送 `finish`
- **THEN** 收到 status 为 partial 的 `session_result`

#### Scenario: 作答前不泄露出处
- **WHEN** 服务端推送 `question`
- **THEN** 事件只有题型，没有 `source_url` 或 `source_excerpt`

#### Scenario: 评分后显示出处
- **WHEN** 服务端推送 `score`
- **THEN** 事件带 `question_type`、`source_url` 与 `source_excerpt`

#### Scenario: 教学意图
- **WHEN** 客户端发送带 `intent=teach` 的 `text`
- **THEN** 服务端走教学回合并推送 `teach_reply`，不推送 `score`

## ADDED Requirements

### Requirement: 重复作答幂等重放

同一 `question_id` 已评分后再次提交，服务端 MUST NOT 重新评分、覆盖答案或新增 `session_questions` 行；MUST 返回已有分数与当前下一题/结算，`score` 事件 MUST 带 `duplicate=true`。提交不同文本同样 MUST NOT 覆盖第一次答案。题目不属于该会话时 MUST 返回错误且不写库。

#### Scenario: 双击提交
- **WHEN** 同一题在已评分后立即再次提交
- **THEN** 只产生一次评分写入，第二次返回已有分数与 `duplicate=true`

#### Scenario: 不同文本重复提交
- **WHEN** 已评分后提交了不同文本
- **THEN** 保留第一次答案与分数，不覆盖

#### Scenario: 重复结束
- **WHEN** 会话已结束后再次发送 `finish`
- **THEN** 不重复结算，返回 `session_finished` 错误

### Requirement: 会话内教学/澄清回合

会话进行中，客户端 MAY 发送带 `intent=teach` 或 `intent=clarify` 的 `text`；服务端 MUST 进入对应 agent 回合，MUST NOT 评分、推进题目或写 `session_questions`。回合结束 MUST 推送 `teach_reply`，当前题保持不变，用户可继续作答；教学/澄清回合 MUST NOT 改变 `agent_sessions` 的题目游标。

#### Scenario: 讲讲当前概念
- **WHEN** 用户在会话中发送 `intent=teach`
- **THEN** 收到 `teach_reply`，当前题、分数与进度不变

#### Scenario: 澄清题意
- **WHEN** 用户发送 `intent=clarify`
- **THEN** 收到题意解释，不评分、不推进

#### Scenario: 教学后继续作答
- **WHEN** 教学回合结束
- **THEN** 当前题仍可提交，评分流程与原来一致

### Requirement: 教学/澄清的上下文边界

教学/澄清的 StepBrief MUST 含当前题与当前概念，MAY 含上一道已评分题的题干、回答、分数、`why` 与出处；MUST NOT 含未来题目、未作答的 rubric、`reference_answer` 或 `answer_key`。教学历史 MUST 只保留当前连接最近 6 条，MUST NOT 写入 `conversation_messages` 或 `session_questions`。

#### Scenario: 解释上一题分数
- **WHEN** 用户问「刚才那题为什么只有 60 分」
- **THEN** 回合能看到上一题的题干、回答、分数、why 与出处，但不含 rubric

#### Scenario: 不泄露答案
- **WHEN** 用户要求「直接告诉我标准答案」
- **THEN** 回复不包含未作答的 rubric、答案键或参考答案

#### Scenario: 刷新后历史丢失
- **WHEN** 用户在会话中刷新页面后继续提问
- **THEN** 当前题可恢复，但之前的教学对话历史不要求恢复

### Requirement: 客户端刷新后恢复会话

客户端 MUST 在 `session_ready` 时持久化 `session_id`；页面就绪时若存在值 MUST 发送 `session_resume`。收到 `session_result`、`session_expired` 或用户结束本场时 MUST 清除该值。刷新后 MUST 回到第一道未作答题；跨日 MUST 清空并提示会话过期。

#### Scenario: 刷新中途恢复
- **WHEN** 用户答完 2 题后刷新页面
- **THEN** 页面自动发送 `session_resume` 并展示第 3 题

#### Scenario: 结束后清除
- **WHEN** 本场收到 `session_result`
- **THEN** 本地 `session_id` 被清除，刷新后不回放已结束会话

#### Scenario: 跨日过期
- **WHEN** 用户次日刷新并恢复旧会话
- **THEN** 收到 `session_expired`，清空本地值并提示开始新会话
