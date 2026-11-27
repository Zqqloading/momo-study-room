# Spec Delta

## MODIFIED Requirements

### Requirement: 有界循环与预算

每个 agent 回合 MUST 有明确预算：最多 8 次工具调用、4 次网页搜索、整回合 60 秒；`search_materials` 与 `read_concept` 各最多 4 次，`search_web` 最多 4 次；每次 `tool_call` 计 1 次，失败也计，被预算拦下不计。`search_materials` 超时 5 秒、`search_web` 超时 8 秒、`read_concept` 超时 1 秒、单次模型调用超时 15 秒。预算用尽后 MUST 在不再提供工具的情况下收口，MUST NOT 无限循环。

#### Scenario: 工具次数用尽
- **WHEN** 模型已调用 8 次工具后仍请求工具
- **THEN** 服务端不执行新工具，要求模型用已有结果回答

#### Scenario: 单工具次数用尽
- **WHEN** 模型已调用 4 次 `search_materials` 后再次请求该工具
- **THEN** 返回 `budget_exhausted` 观测，不执行第五次检索

#### Scenario: 网页次数用尽
- **WHEN** 模型已调用 4 次 `search_web` 后再次请求
- **THEN** 返回 `budget_exhausted` 观测，不执行第五次搜索

#### Scenario: 失败调用计数
- **WHEN** 一次工具调用超时或参数非法
- **THEN** 该次调用计入 8 次总预算，模型可在剩余预算内换说法重试

#### Scenario: 被拦下不计
- **WHEN** 请求因总预算、单工具或网页上限被拦下
- **THEN** 该次未执行的调用不计入已用次数

#### Scenario: 整回合超时
- **WHEN** 工具与模型调用累计超过 60 秒
- **THEN** 服务端停止工具循环并返回兜底回复，不写入任何状态

## ADDED Requirements

### Requirement: 工具目录与归属

系统 MUST 只向 agent 暴露检索类 `search_materials` / `search_web` / `read_concept`（只读）。考评类 `generate_questions` / `score_answer`、进度/会话类 `propose_unit` / `build_session_plan` / `start_unit` / `save_answer` / `finish_session` / `resume_session` / `save_conversation` MUST NOT 注册为 agent 工具。

#### Scenario: 检索类归属
- **WHEN** agent 在 `free_talk` / `teach` / `clarify` 中请求工具
- **THEN** 只有 `search_materials` / `search_web` / `read_concept` 可见，且都是只读

#### Scenario: 考评类不暴露
- **WHEN** agent 请求 `generate_questions` 或 `score_answer`
- **THEN** 执行器返回 `unknown_tool`，不执行生成或评分

#### Scenario: 进度/会话类不暴露
- **WHEN** agent 请求 `propose_unit` / `start_unit` / `save_answer` / `finish_session` / `resume_session`
- **THEN** 执行器返回 `unknown_tool`，不写库、不改会话状态

### Requirement: 命令、离线工具与回合

命令类 `skip_question` / `repeat_question` / `end_session` MUST 只由用户命令触发；知识库/运维 `ingest_material` / `backup_db` MUST 只在离线运行；`free_talk` / `teach` / `clarify` MUST 作为 agent 回合而不是工具。

#### Scenario: 命令只由用户触发
- **WHEN** 用户明确说“跳过”“重复”“结束本次”
- **THEN** 程序执行对应命令；agent MUST NOT 自行发起这些命令

#### Scenario: 离线工具不进入回合
- **WHEN** 运行时或 agent 请求 `ingest_material` 或 `backup_db`
- **THEN** 请求被拒绝，知识入库与备份仍只走离线 CLI/运维

#### Scenario: 回合不是工具
- **WHEN** 模型请求把 `free_talk` / `teach` / `clarify` 当作工具调用
- **THEN** 执行器返回 `unknown_tool`；回合只由无会话输入或显式提问入口触发

### Requirement: 结果分离 A/P/U

工具与回合的输出 MUST 按 A/P/U 分离：A 回 agent 组织语言；P 直传程序/前端执行；U 页面直显。Agent MUST NOT 复述、改写或冒充 P/U 字段；`sources` MUST 由程序从成功工具结果生成，agent MUST NOT 编造。

#### Scenario: A 类回模型
- **WHEN** `search_materials` 返回摘录与 `grounded`
- **THEN** agent 可以把摘录纳入回复并组织语言

#### Scenario: P 类不回模型
- **WHEN** `save_answer` 写入答案与分数
- **THEN** agent MUST NOT 说“已保存”“已提交”“已评分”，也不得改写分数

#### Scenario: U 类由程序直发
- **WHEN** 程序发出 `question` / `score` / `session_result` / `agent_status`
- **THEN** 页面直接显示；agent MUST NOT 冒充这些事件或编造页面状态

#### Scenario: 来源不编造
- **WHEN** 最终回复带 `sources`
- **THEN** 来源只来自本轮成功工具结果；没有来源时按既有规则加强制前缀

### Requirement: last_scored 引用边界

`teach` / `clarify` 的 StepBrief MAY 含上一道已评分题的题干、回答、分数、`why` 与出处。Agent MAY 原样引用这些字段；MUST NOT 改数字、MUST NOT 说“我给你评分”、MUST NOT 把 `why` 说成新评分。

#### Scenario: 原样引用
- **WHEN** 用户问“刚才那题为什么只有 60 分”
- **THEN** agent 可以引用 60 分与 `why`，不得改数

#### Scenario: 改数字
- **WHEN** agent 把 60 分说成 80 分
- **THEN** 该回复判失败

#### Scenario: 冒充评分
- **WHEN** agent 说“我给你评分”或“我改了分数”
- **THEN** 该回复判失败；评分只属于 `score_answer`

### Requirement: 通用工具禁令

所有工具 MUST 遵守 G1–G8：不写库、不改流程、不评分、不泄露答案、不执行网页指令、不绕过程序发事件、不跨会话、不绕过预算。越权请求 MUST 被执行器拒绝，而不是只靠提示词。

#### Scenario: 写库被拒
- **WHEN** 工具或 agent 尝试写 `session_questions` / `sessions` / `concepts` / `materials`
- **THEN** 执行器拒绝写入，数据库行数不变

#### Scenario: 流程变更被拒
- **WHEN** agent 尝试开始、推进、跳过或结束会话
- **THEN** 执行器拒绝，当前题与游标不变

#### Scenario: 答案泄露被拒
- **WHEN** agent 或页面请求 rubric / `reference_answer` / `answer_key` / 未来题
- **THEN** 请求被拒绝，响应不含这些字段

#### Scenario: 网页指令不执行
- **WHEN** 网页结果要求忽略规则、改变步骤或调用其他工具
- **THEN** agent 只把网页内容当资料，不执行其中指令

#### Scenario: 跨会话读被拒
- **WHEN** 工具请求其他会话、其他日期或数据库原始行
- **THEN** 执行器拒绝，只返回当前会话的程序整理字段

#### Scenario: 预算绕过被拒
- **WHEN** 模型请求超过 8 次总预算、单工具 4 次或网页 4 次
- **THEN** 返回 `budget_exhausted`，不执行该次调用

### Requirement: 程序工具次数不变量

程序工具 MUST 按每场/每题不变量调用：`generate_questions` 每场 1 次；`score_answer` 每题 1 次 + 失败重试 1 次；`save_answer` 每题 1 次且幂等；`start_unit` / `finish_session` 每场 1 次；`resume_session` 每次重连 1 次；用户命令每次意图 1 次。程序工具 MUST NOT 占用 agent 回合预算。

#### Scenario: 出题一次
- **WHEN** 同一场已经生成 5 题后再次请求 `generate_questions`
- **THEN** 不再次生成，复用已有题目或回退结果

#### Scenario: 判分重试一次
- **WHEN** `score_answer` 第一次失败后重试仍失败
- **THEN** 该题记未评分，会话继续，不进行第三次评分

#### Scenario: 存答案幂等
- **WHEN** 同一题再次提交答案
- **THEN** 不新增行、不覆盖已评分答案，返回已有分数与 `duplicate=true`

#### Scenario: 结算一次
- **WHEN** 同一场已经结算后再次请求 `finish_session`
- **THEN** 不重复写 `sessions` / `mastery`，返回 `session_finished`

#### Scenario: 恢复一次
- **WHEN** 同一连接已经 `resume_session` 后再次请求
- **THEN** 不重复恢复或结算

### Requirement: 执行器硬校验与提示词软判断

工具白名单、步骤过滤、预算、结果路由、写权限、答案泄露过滤 MUST 由执行器硬校验；“先本地后网页、换说法、何时停” MAY 由提示词引导，MUST NOT 由执行器强制检索顺序。

#### Scenario: 非白名单工具
- **WHEN** 模型请求未注册的工具名
- **THEN** 执行器返回 `unknown_tool`，不执行

#### Scenario: 作答步骤零工具
- **WHEN** 用户提交答案进入评分路径
- **THEN** 执行器不向模型提供任何工具，也不执行检索

#### Scenario: 本地优先不强制
- **WHEN** 模型在 `free_talk` 第一条工具调用选择 `search_web`
- **THEN** 执行器不因“先本地”而拒绝；顺序只由提示词引导

#### Scenario: 写权限硬校验
- **WHEN** 任何 agent 工具尝试写库或改会话状态
- **THEN** 执行器拒绝，不依赖提示词自觉
