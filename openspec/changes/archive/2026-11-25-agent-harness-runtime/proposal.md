# Proposal

## Why

当前会话外的自由对话由关键词和 grounded 阈值决定“查不查、换不换说法、查几次”，模型没有判断空间；会话内也没有教学/澄清的 agent 回合。产品要的是“程序给一张工单，模型在当前步骤内自己决定检索与停止”，同时不破坏 5 题、逐题评分、断点恢复这些必须确定的行为。

## What Changes

- 新增有界工具回合运行时：程序划定 `free_talk` / `teach` / `clarify` 三类步骤；模型在步骤内决定查资料、换说法重查、何时停止；每回合最多 3 次工具、2 次网页，工具超时 5s/8s/1s，整回合 30s。
- 新增 3 个只读工具：`search_materials`、`search_web`、`read_concept`。出题、评分、写答案、mastery、结算、恢复仍是程序专属，不暴露给模型。
- 循环自写，只用 `openai` Python SDK 发请求与解析 `tool_calls`；不引入框架。默认模型 DeepSeek，`AGENT_MODEL` 可切 MiMo。
- **BREAKING**：自由对话不再用 `needs_web` / `classify_free_talk` 决定检索；是否查、查哪个工具、查几次由模型决定。`search_query` 不再作为触发条件。
- **BREAKING**：重复作答从“题目已作答”报错改为幂等重放：不重评、不覆盖，返回已有分数与当前状态，`score.duplicate=true`。
- 会话内新增显式“提问”入口：`text`/`audio` 带 `intent=teach|clarify`，走 agent 回合；不评分、不推进、不写答题行。回复用新的 `teach_reply` 事件并朗读。
- 没有材料/网页依据时允许模型常识回答，服务端强制加“材料里没有直接讲到，以下是一般知识：”前缀；网页结果按不可信数据隔离。
- 来源列表列本轮所有成功来源（材料 + 网页，最多 5 条）；工具调用只写日志，不改 schema。
- 页面持久化 `session_id`，刷新后可 `session_resume`；`AGENT_HARNESS` 默认 off，三步落地验收后 on。
- 不变：5 题、题型配比、逐题评分、评分失败语义、mastery/review_due、断点恢复、出题/评分程序化、网页不写知识库、作答步骤零工具。

## Capabilities

### New Capabilities

- `agent-harness`: 有界工具回合的契约——StepBrief 上下文、3 个只读工具、预算/超时、失败观测、工具调用不写库、默认模型与开关。

### Modified Capabilities

- `free-talk`: 检索触发从关键词/grounded 改为 agent 判断；来源展示、常识前缀、网页不可信隔离；保留对话持久化与进度上下文。
- `web-search`: 搜索触发条件改为 agent 决定；query 由 agent 写；网页内容按不可信数据隔离；结果仍只作对话来源。
- `coach-session`: 重复作答幂等重放；新增 `intent` / `teach_reply` 的教学/澄清回合，不评分不推进；`last_scored` 上下文；页面刷新恢复。
- `tts-playback`: 教学/澄清回复也朗读；`audio_chunk` 的 `utterance` 增加 `teach`；TTS 失败仍只显示文字。

## Impact

- 代码：`core/agent.py`、新增 `core/agent_loop.py` / `core/agent_tools.py` / `core/agent_steps.py`、新增 `bff/agent_llm.py` / `bff/agent_tools.py`、`bff/main.py`、`core/ports.py`、`core/coach.py`（重复提交）、`web/app.js`、`requirements.txt`（`openai`）。
- 数据：不改 schema；自由对话来源继续写 `conversation_messages.sources_json`；工具调用只写日志。
- 依赖：新增 `openai` Python SDK；DeepSeek / MiMo 均走 OpenAI 兼容端点。
- 不变：`core/question_generation.py`、`core/scoring.py`、`core/store.py` 的写路径、知识入库/检索算法、语音输入链路。
