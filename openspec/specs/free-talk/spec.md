# free-talk Specification

## Purpose
定义会话开始前的语音入口：用户可以直接说话提问或闲聊，系统用关键词把学习问题路由到教学讲解，其余走自由对话；不写数据库、不评分。

## Requirements

### Requirement: 初始界面可直接说话

没有进行中的会话时，「开始说话」MUST 可点击并进入录音；录音结束后 MUST 提交 `audio` 消息（不带 `session_id`/`question_id`），由服务端走自由对话路径。

#### Scenario: 初始界面录音
- **WHEN** 用户在未开始学习时点击「开始说话」并说完一段话
- **THEN** 客户端提交一条不带会话信息的 audio 消息

#### Scenario: 会话中仍走答题
- **WHEN** 用户在有题目的会话中说话
- **THEN** audio 消息带 session_id 与 question_id，走评分路径

### Requirement: 回复与朗读

自由对话 MUST 推送 `reply` 事件（带 `mode`、文本与 `sources`），随后用 TTS 分块推送 `audio_chunk` 朗读回复；MUST NOT 写入 sessions/session_questions，MUST NOT 调用评分。`mode` MUST 由本轮是否使用检索工具决定：使用过至少一个检索工具为 `teach`，否则为 `chat`；MUST NOT 再用关键词判定。

#### Scenario: 教学回复
- **WHEN** agent 回合使用过至少一个检索工具
- **THEN** 收到 mode=teach 的 reply 与 sources，随后收到 audio_chunk

#### Scenario: 闲聊回复
- **WHEN** agent 回合没有使用任何检索工具
- **THEN** 收到 mode=chat 的 reply，随后收到 audio_chunk

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

### Requirement: 无会话可文本提问

没有进行中的会话时，前端 MUST 显示文本输入框；提交 MUST 发送 `{"type":"text","text":...}`（不带 `session_id`/`question_id`），由服务端走自由对话。有会话时文本仍 MUST 走 `answer` 答题路径。

#### Scenario: 初始界面打字
- **WHEN** 页面就绪且没有会话
- **THEN** 输入框可见，回车发送 `type=text`，收到 `transcript` 与 `reply`

#### Scenario: 会话中打字
- **WHEN** 当前有题目
- **THEN** 回车发送 `answer`，不触发自由对话

### Requirement: 出处展示

助手消息带 `sources` 时，前端 MUST 在消息下方按序号列出「标题：摘录」；来源列表 MUST 是本轮所有成功工具结果的并集，按 `chunk_id`/URL 去重，最多 5 条；网页来源 MUST 带域名与检索日期。历史对话加载时 MUST 同样展示。

#### Scenario: 回答带出处
- **WHEN** `reply.sources` 非空
- **THEN** 助手气泡下方出现编号列表，材料与网页来源都可辨认

#### Scenario: 来源数量
- **WHEN** 本轮成功来源超过 5 条
- **THEN** 最多展示 5 条，按本轮调用顺序

#### Scenario: 刷新后回看
- **WHEN** 加载带 `sources` 的历史消息
- **THEN** 出处列表仍然显示

### Requirement: 材料优先与冲突并列

系统提示 MUST 默认先查本地材料；模型 MAY 对显式联网要求或时效问题直接查网页。网页与材料冲突时 MUST 并列说明「材料说 X，网上有来源说 Y」，MUST NOT 用网页覆盖材料。

#### Scenario: 材料与网页冲突
- **WHEN** 材料说 A，网页来源说非 A
- **THEN** 回答同时说明两种说法，并标明材料优先

#### Scenario: 材料与网页一致
- **WHEN** 材料与网页说法一致
- **THEN** 回答统一表述，并同时列出材料与网页来源

#### Scenario: 显式联网要求
- **WHEN** 用户说「联网查一下 X」或「搜一下最新的 X」
- **THEN** 模型可以直接查网页，不必先查本地

### Requirement: 联网答案与引用

联网答案 MUST 为 1–3 句口语化文本。回答 MUST 附本轮所有成功来源（材料 + 网页，最多 5 条；网页最多 3 条），网页来源带标题、域名、日期与链接，并 MUST 明确「网上信息，可能变化」。网页来源 MUST 写入 `conversation_messages.sources_json`，刷新或切回旧对话后仍 MUST 可见。

#### Scenario: 正常联网回答
- **WHEN** 搜索返回可用结果
- **THEN** 回答简短口语化，附来源，并提示网上信息可能变化

#### Scenario: 刷新后回看
- **WHEN** 用户刷新页面并加载同一对话
- **THEN** 网页来源仍显示标题、域名、日期和链接

#### Scenario: 来源数量
- **WHEN** 可用网页结果超过 3 条
- **THEN** 最多展示 3 条网页来源，材料来源另计但总数不超过 5 条

### Requirement: 搜索失败与空结果的兜底文案

本轮没有使用任何材料或网页来源时，服务端 MUST 在回复前强制加「材料里没有直接讲到，以下是一般知识：」。用户显式要求联网而搜索失败或空结果时，回复 MUST 说明「联网搜索暂时不可用」或「联网也没查到」；两种情况 MUST NOT 冒充材料内容。

#### Scenario: 搜索失败
- **WHEN** 搜索报错或超时，本地也没有可用来源，用户显式要求联网
- **THEN** 回复说明「联网搜索暂时不可用」，并加强制的一般知识前缀

#### Scenario: 搜索空结果
- **WHEN** 搜索成功但没有可用结果，本地也没有可用来源
- **THEN** 回复说明「联网也没查到」，并加强制的一般知识前缀

#### Scenario: 本地有依据但搜索失败
- **WHEN** 本地有可用来源，搜索失败
- **THEN** 回答只依据材料，不出现联网失败文案

### Requirement: 自由对话由 agent 回合处理

没有进行中的会话时，自由对话 MUST 进入 `free_talk` agent 回合；模型 MUST 在预算内自行决定是否查本地、换说法重查、查网页或直接回答。回合 MUST 只使用只读检索工具，MUST NOT 评分、推进、写 `session_questions` 或改 `concepts`。

#### Scenario: 该查时查
- **WHEN** 用户问一个材料里可能有的概念
- **THEN** agent 调用 `search_materials` 或 `read_concept`，依据结果回答

#### Scenario: 不需要查
- **WHEN** 用户只是闲聊或明确说“不用查”
- **THEN** agent 不调用检索工具，直接回复

#### Scenario: 不评分不推进
- **WHEN** 自由对话完成
- **THEN** 不产生 `session_questions` 行，不更新 mastery，不结算

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
