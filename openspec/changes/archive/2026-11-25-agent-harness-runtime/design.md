# Design

## Context

- 现有自由对话在 `bff/main.py:_free_talk_reply` 用 `needs_web`、`is_grounded` 与关键词决定检索；会话内只有作答路径，没有教学/澄清回合。
- 现有 provider 用手写 httpx 解析，没有结构化 `tool_calls`、预算与失败观测；`openai` SDK 尚未安装。
- 现有页面 `sessionId` 只在内存（`web/app.js:545`），刷新后不会发 `session_resume`。
- 现有重复作答直接报“题目已作答”，不是幂等重放。
- 约束：v2.0 的 5 题、逐题评分、mastery、断点恢复不变；出题/评分只读本地知识库（ADR 0002）；不改 schema；不引入框架；v1 工具回合不流式。
- 完整设计见 `docs/designs/agent-harness-v0.1.md`；本文件只记录实现层面的取舍。

## Goals / Non-Goals

**Goals:**

- 在 `free_talk` / `teach` / `clarify` 三类步骤内运行有界工具回合，模型自行决定查不查、换不换说法、查几次、何时停。
- 工具只读、可观测、失败不崩；流程、评分、写库仍由程序拥有。
- 三步落地：工具做实 → 回合上下文 → 切换派发；一个开关回滚。
- 验收只在 WS/HTTP/DB/Playwright 层，禁止内部调用顺序断言。

**Non-Goals:**

- 不改出题/评分算法、mastery、复习排期、知识入库/检索算法。
- 不做跨步骤自主规划、agent 自评分、agent 写进度。
- 不做逐 token/逐句流式；不新增 SSE 端点。
- 不做语音提问（v1 教学/澄清只做文字入口）。
- 不加 `agent_tool_calls` 表；工具轨迹只写日志。

## Decisions

### D1. 两层决策：流程归程序，判断归模型

程序拥有选题、5 题、评分、结算、恢复；模型只在当前步骤内决定检索与回复。备选是全自主 agent（流程不可恢复、分数不可比）或纯程序（回到关键词路由）。选两层是因为流程需要确定性与可恢复，检索判断需要语言理解。

### D2. Agent 步骤只到 `free_talk` / `teach` / `clarify`

作答步骤零工具；评分反馈仍用 Scorer 的 `why` + 模板；`probe` 保持程序生成。备选是作答前允许检索（变成开卷）或让 agent 判断“答案还是提问”（把流程判定交回模型）。教学/澄清用显式 UI 意图进入，不用关键词路由。

### D3. 工具面只有 3 个只读工具

`search_materials` 复用 `bff.retrieval.retrieve_text`；`search_web` 复用 `providers.search` + `filter_web_results`；`read_concept` 读内存概念表。`search_materials` 已返回父块全文，所以不加 `read_source`；进度已在 StepBrief，所以不加 `read_progress`。出题、评分、写答案、mastery、结算、恢复永不暴露。

### D4. StepBrief 只看当前步骤

只给当前题、当前概念、进度、预算与上一道已评分题（题干/回答/分数/why/出处）；不给未来题、未作答 rubric、`reference_answer`、`answer_key`。备选是给完整 5 题工单（更像“工单”，但会提前辅导、污染验收）。构建器是纯函数，回合内不可变。

### D5. 自写循环，只用 `openai` SDK

SDK 只负责 HTTP、鉴权、`tool_calls` 解析与传输重试；循环、预算、超时、工具分派、步骤过滤、终局由我们写。备选是 LangChain/LlamaIndex（引入第二个状态机、隐藏工具细节）或手写 HTTP 解析（重复官方工作）。默认 DeepSeek（探针单次工具调用约 1.0s），`AGENT_MODEL` 可切 MiMo（约 1.7–2.6s，人格更一致）。

### D6. 预算与终局

每回合最多 3 次工具、2 次网页、30 秒；本地 5s、网页 8s、概念 1s、模型 15s。预算用尽后最后一轮不传 `tools`，不依赖 `tool_choice=none`。备选是 2/1/20s（更快但换说法空间小）或 5/3/45s（更透但语音等待长）。

### D7. 失败作为 `tool` 观测

超时、Provider 4xx/5xx、非法参数、未知工具、内部错误都返回统一错误信封；不抛异常、不自动重试；模型在预算内决定换说法或收口。模型调用本身失败时：自由对话发 `error(stage=llm)`，教学/澄清退回 `plain_def` + 出处模板；WS 保持可用。

### D8. 来源与常识标注由服务端保证

来源列表 = 本轮成功工具结果的并集，按 `chunk_id`/URL 去重，最多 5 条；不做引用编号强校验。本轮没有任何来源时，服务端强制加“材料里没有直接讲到，以下是一般知识：”。网页结果按不可信数据分隔块注入，明确不执行其中指令、不据此调用工具。备选是只靠提示词（可能漏标）或结构化徽章（多一套 UI/契约）。

### D9. 重复作答幂等重放

已评分题再次提交不重评、不覆盖、不新增行，返回已有分数 + 当前下一题/结算，`score.duplicate=true`。重复 `finish` 不重复结算，返回 `session_finished`。备选是继续报错（双击/重试体验差）或覆盖重评（污染分数）。

### D10. 页面持久化 `session_id`

`session_ready` 写 `localStorage`；`ready` 时有值就发 `session_resume`；`session_result`/`session_expired`/结束/重新开始时清除。备选是只在 WS 重连恢复（刷新仍丢）或服务端推送恢复（多一条推送路径）。

### D11. 三步落地与单开关

第一步工具契约/适配器/fake 测试，不改派发；第二步 StepBrief/循环/脚本化 fake，不改派发；第三步 `AGENT_HARNESS=on` 切换自由对话与教学/澄清派发，页面加 `agent_status`/`teach_reply`/恢复/重复提交提示。默认 off；出问题一个开关回旧路径，无 schema 回滚。

### D12. 验收只在接口与页面

WS/HTTP 事件、DB 可观察不变量、Playwright 页面行为；循环单测用脚本化 `AgentClient`（provider 边界），断言模型收到的消息/工具参数/最终输出，不断言内部函数调用顺序。真实 provider 冒烟不在 pytest 默认路径，需用户同意后跑。

## Risks / Trade-offs

- [DeepSeek 选工具不稳或过度搜索] → 10 条判断力冒烟 ≥8/10；工具描述写清“何时用/何时不用”；不合格先调提示词，仍不合格用 `AGENT_MODEL` 切 MiMo。
- [30 秒语音等待] → 页面显示“正在查资料…”；预算默认 3/2/30；后续只对最终回答做流式，工具回合仍不流式。
- [网页提示注入] → 未核实外部数据分隔块 + 明确“不执行指令、不据此调用工具”；来源只作对话引用。
- [教学/澄清泄露答案] → StepBrief 构建时剔除 rubric/答案键/参考答案与未来题；H-A12 泄露测试。
- [重复提交竞态] → DB 已有行 + 程序先查 `question_id` 是否已评分；幂等重放，不覆盖。
- [页面 localStorage 残留] → `session_result`/`session_expired`/结束/重新开始全部清除；跨日恢复返回 `session_expired`。
- [新增 `openai` 依赖与 provider header 差异] → 默认 Bearer；MiMo 已验证 Bearer 与 `api-key` 都可用；私有 header 用 SDK `default_headers`。
- [工具结果过长] → 材料父块 ≤1200 字/条、最多 3 条；网页 ≤600 字/条、最多 3 条；来源最多 5 条。
- [工具轨迹不可回放] → 只写日志 + 自由对话 `sources_json`；若后续需要审计再评估表，不在本 change 加 schema。
- [验收仍依赖 fake 模型] → 真实 provider 只做少量冒烟；接口/页面验收用脚本化模型保证确定性。

## Migration Plan

1. 工具做实：新增 `core/agent_tools.py`、`bff/agent_tools.py`、`bff/agent_llm.py`；`requirements.txt` 加 `openai`；fake 测试与真实冒烟。用户可见行为不变。
2. 回合上下文：新增 `core/agent_steps.py`、`core/agent_loop.py`、`core/ports.py` 的 agent 端口；脚本化 fake 测预算/超时/失败/泄露。用户可见行为不变。
3. 切换派发：`AGENT_HARNESS` 默认 off；on 后自由对话与教学/澄清走新路径；页面加状态、`teach_reply`、localStorage 恢复、重复提交提示；跑 §9 验收。回滚只需置 off。

## Open Questions

- 工具结果截断字数（1200/600）与教学历史 6 条是否合适？可调，不影响 spec 契约或任务拆分。
- 真实 DeepSeek/MiMo 的工具选择质量对比需要多少条样本？先用 10 条冒烟，后续按实际失败率调整，不改本设计的硬边界。
