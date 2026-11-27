# Spec Delta

## REMOVED Requirements

### Requirement: 关键词路由教学与闲聊
**Reason**: 自由对话不再用关键词决定教学/闲聊；由 agent 回合根据上下文与工具使用处理。
**Migration**: 客户端无改动；服务端不再调用关键词路由决定模式。

### Requirement: 联网兜底触发条件
**Reason**: 是否检索、查本地还是网页、查几次由 agent 在预算内决定，不再由关键词或 grounded 阈值触发。
**Migration**: 客户端无改动；旧关键词/阈值逻辑不再参与检索决策。

## MODIFIED Requirements

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

## ADDED Requirements

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
