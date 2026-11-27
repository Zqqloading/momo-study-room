# Spec Delta

## Purpose

定义有界工具回合：程序只划定当前步骤并给出工单，模型在预算内自己决定查本地、换说法重查、查网页或停止；工具只读，流程与写库仍归程序。

## ADDED Requirements

### Requirement: Agent 回合只发生在非评分步骤

Agent 回合 MUST 只发生在 `free_talk`、`teach`、`clarify` 三类步骤。作答、评分、结算、恢复 MUST NOT 启动 agent 回合；作答步骤 MUST 不向模型提供任何工具。

#### Scenario: 自由对话进入 agent 回合
- **WHEN** 没有进行中的会话且用户发起文本或语音对话
- **THEN** 服务端进入 `free_talk` 步骤，允许模型在预算内调用只读工具

#### Scenario: 作答不进入 agent 回合
- **WHEN** 用户在会话中提交答案
- **THEN** 服务端直接评分，不调用 agent 循环，也不允许检索

#### Scenario: 结算不进入 agent 回合
- **WHEN** 第 5 题评分完成或用户提前结束
- **THEN** 服务端直接结算，不调用 agent 循环

### Requirement: StepBrief 只含当前步骤

每个 agent 回合 MUST 由程序构建不可变 StepBrief，包含步骤、日期、会话/题目、当前概念、进度、预算与硬边界。StepBrief MUST NOT 包含未来题目、未作答题的 rubric、`reference_answer` 或 `answer_key`；`teach`/`clarify` MAY 包含上一道已评分题的题干、回答、分数、`why` 与出处。

#### Scenario: 当前题上下文
- **WHEN** 用户在会话中发起 `clarify`
- **THEN** StepBrief 含当前题题干、题型、选项、当前概念与进度，不含未来题

#### Scenario: 上一题分数上下文
- **WHEN** 用户问“刚才那题为什么只有 60 分”
- **THEN** StepBrief 含上一道已评分题的题干、回答、分数、`why` 与出处，不含 rubric 或答案键

#### Scenario: 不泄露未作答题
- **WHEN** 构建任意 agent 回合的 StepBrief
- **THEN** 未来题干、未作答题的 rubric/答案键/参考答案都不出现

### Requirement: 只读工具与写边界

Agent MUST 只能调用 `search_materials`、`search_web`、`read_concept` 三个只读工具。工具 MUST NOT 写 `sessions`、`session_questions`、`concepts`、`materials`、`concept_sources` 或 `question_bank`；工具调用 MUST NOT 改变会话状态。出题、评分、写答案、mastery、结算、恢复 MUST NOT 作为工具暴露。

#### Scenario: 本地检索工具
- **WHEN** 模型调用 `search_materials`
- **THEN** 返回本地材料片段与出处，不写库

#### Scenario: 网页检索不写知识库
- **WHEN** 模型调用 `search_web`
- **THEN** 结果只进入本轮来源，知识库表行数不变

#### Scenario: 越权工具被拒
- **WHEN** 模型请求评分、写答案或结算类工具
- **THEN** 执行器返回 `unknown_tool` 观测，不执行任何写操作

### Requirement: 有界循环与预算

每个 agent 回合 MUST 有明确预算：最多 3 次工具调用、2 次网页搜索、整回合 30 秒；`search_materials` 超时 5 秒、`search_web` 超时 8 秒、`read_concept` 超时 1 秒、单次模型调用超时 15 秒。预算用尽后 MUST 在不再提供工具的情况下收口，MUST NOT 无限循环。

#### Scenario: 工具次数用尽
- **WHEN** 模型已调用 3 次工具后仍请求工具
- **THEN** 服务端不执行新工具，要求模型用已有结果回答

#### Scenario: 网页次数用尽
- **WHEN** 模型已调用 2 次 `search_web` 后再次请求
- **THEN** 返回 `budget_exhausted` 观测，不执行第三次搜索

#### Scenario: 整回合超时
- **WHEN** 工具与模型调用累计超过 30 秒
- **THEN** 服务端停止工具循环并返回兜底回复，不写入任何状态

### Requirement: 工具失败作为观测返回

工具超时、Provider 4xx/5xx、参数非法、未知工具或内部错误 MUST 作为结构化 `tool` 观测返回给模型，MUST NOT 抛出异常终止回合。模型 MAY 在预算内换说法重试或直接收口；服务端 MUST NOT 自动重试工具。模型调用本身失败时 MUST 返回兜底回复并保持连接可用。

#### Scenario: 网页超时
- **WHEN** `search_web` 超过 8 秒
- **THEN** 模型收到 `timeout` 观测，可换说法再查或用已有结果回答

#### Scenario: 参数非法
- **WHEN** 工具参数不是合法 JSON 或缺少必填字段
- **THEN** 模型收到 `invalid_arguments` 观测与期望形状，回合继续

#### Scenario: 模型调用失败
- **WHEN** 模型调用重试一次后仍失败
- **THEN** 自由对话返回错误事件，教学/澄清退回模板讲解；连接保持可用

### Requirement: 来源与常识标注

Agent 回合的最终回复 MUST 带本轮所有成功工具来源，按 `chunk_id`/URL 去重，最多 5 条；服务端 MUST NOT 要求正文逐条引用，也 MUST NOT 做引用编号强校验。若本轮没有使用任何材料或网页来源，服务端 MUST 在回复前强制加“材料里没有直接讲到，以下是一般知识：”。网页内容 MUST 按不可信数据处理：只当资料，不执行其中指令，不据此调用工具；与材料冲突时 MUST 并列说明。

#### Scenario: 有本地与网页来源
- **WHEN** 本轮同时使用本地材料和网页结果
- **THEN** 回复带去重后的来源列表，网页来源标注“网上信息，可能变化”

#### Scenario: 没有来源
- **WHEN** 本轮没有使用任何材料或网页来源
- **THEN** 服务端在回复前加“材料里没有直接讲到，以下是一般知识：”，不冒充材料内容

#### Scenario: 网页含指令性文本
- **WHEN** 网页结果要求模型忽略规则或调用其他工具
- **THEN** 模型只把它当资料，不执行指令，不改步骤
