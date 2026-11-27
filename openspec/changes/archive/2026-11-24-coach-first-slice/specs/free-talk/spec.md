# Spec Delta

## Purpose

定义会话开始前的语音入口：用户可以直接说话提问或闲聊，系统用关键词把学习问题路由到教学讲解，其余走自由对话；不写数据库、不评分。

## ADDED Requirements

### Requirement: 初始界面可直接说话

没有进行中的会话时，「开始说话」MUST 可点击并进入录音；录音结束后 MUST 提交 `audio` 消息（不带 `session_id`/`question_id`），由服务端走自由对话路径。

#### Scenario: 初始界面录音
- **WHEN** 用户在未开始学习时点击「开始说话」并说完一段话
- **THEN** 客户端提交一条不带会话信息的 audio 消息

#### Scenario: 会话中仍走答题
- **WHEN** 用户在有题目的会话中说话
- **THEN** audio 消息带 session_id 与 question_id，走评分路径

### Requirement: 关键词路由教学与闲聊

自由对话的转写 MUST 用关键词启发式路由：包含学习类疑问词或学习词（什么、为什么、怎么、解释、讲讲、区别、原理、定义、举例、教我）时走教学讲解，否则走自由对话。路由 MUST NOT 额外调用模型。

#### Scenario: 学习问题走教学
- **WHEN** 转写为“什么是 agent 循环”
- **THEN** 路由结果为 teach，用教学提示词生成解释

#### Scenario: 闲聊走自由对话
- **WHEN** 转写为“今天好累”
- **THEN** 路由结果为 chat，用闲聊提示词生成回应

### Requirement: 回复与朗读

自由对话 MUST 推送 `reply` 事件（带 mode 与文本），随后用 TTS 分块推送 `audio_chunk` 朗读回复；MUST NOT 写入 sessions/session_questions，MUST NOT 调用评分。

#### Scenario: 教学回复
- **WHEN** 教学路由完成
- **THEN** 收到 mode=teach 的 reply，随后收到 audio_chunk

#### Scenario: 不落库
- **WHEN** 完成一次自由对话
- **THEN** sessions 表没有新增记录

### Requirement: 失败可重试

ASR 或 LLM 失败时 MUST 推送 error，结束本次自由对话；「开始说话」MUST 保持可用，用户可直接重试。

#### Scenario: LLM 失败
- **WHEN** 生成回复时 LLM 报错
- **THEN** 收到 error(stage=llm)，按钮仍可点击重试

### Requirement: 对话长期持久化与切换

自由对话的用户与助手消息 MUST 写入 `conversations` 与 `conversation_messages`；同一对话 MUST 跨刷新、跨 WebSocket 连接保留。客户端 MUST 能新建对话、列出历史对话、加载并继续旧对话；发给模型的上下文 MUST 取当前对话最近 12 条消息。

#### Scenario: 刷新后继续
- **WHEN** 用户刷新页面后打开最近的对话
- **THEN** 历史消息全部可见，可以继续说话

#### Scenario: 新对话不影响旧对话
- **WHEN** 用户点「新对话」
- **THEN** 创建空对话；旧对话仍保留在历史列表中

#### Scenario: 切回旧对话
- **WHEN** 用户从历史列表选择旧对话
- **THEN** 加载该对话全部消息并继续使用

### Requirement: 学习进度上下文

每次自由对话 MUST 把当前 active 概念的 mastery、`review_due_at` 与最近 3 场会话成绩摘要注入系统提示；MUST NOT 逐条复述给用户。

#### Scenario: 摘要注入
- **WHEN** 用户问“我学到哪了”
- **THEN** 回答与当前进度摘要一致

#### Scenario: 无进度时不注入
- **WHEN** 没有任何 active 概念与会话记录
- **THEN** 系统提示不包含进度段
