# Spec Delta

## Purpose

定义自由对话的两个前端行为：没有会话时可以直接打字提问；助手回答下方显示材料出处。

## ADDED Requirements

### Requirement: 无会话可文本提问

没有进行中的会话时，前端 MUST 显示文本输入框；提交 MUST 发送 `{"type":"text","text":...}`（不带 `session_id`/`question_id`），由服务端走自由对话。有会话时文本仍 MUST 走 `answer` 答题路径。

#### Scenario: 初始界面打字
- **WHEN** 页面就绪且没有会话
- **THEN** 输入框可见，回车发送 `type=text`，收到 `transcript` 与 `reply`

#### Scenario: 会话中打字
- **WHEN** 当前有题目
- **THEN** 回车发送 `answer`，不触发自由对话

### Requirement: 出处展示

助手消息带 `sources` 时，前端 MUST 在消息下方按序号列出「标题：摘录」；历史对话加载时 MUST 同样展示。

#### Scenario: 回答带出处
- **WHEN** `reply.sources` 非空
- **THEN** 助手气泡下方出现编号列表

#### Scenario: 刷新后回看
- **WHEN** 加载带 `sources` 的历史消息
- **THEN** 出处列表仍然显示
