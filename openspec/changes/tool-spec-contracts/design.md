# Design

## Context

- `docs/designs/tool-specs-v0.1.md` 是本次的唯一设计来源；`agent-harness-runtime` 已于 2026-11-25 归档，main spec `openspec/specs/agent-harness/spec.md` 目前仍是 3 个只读工具 + 3/2/30 预算。
- 现有实现：`core/agent_tools.py` 的 `MAX_TOOL_CALLS=3` / `MAX_WEB_CALLS=2`，`core/agent_loop.py` 的预算与计数，`bff/agent_tools.py` 的三个适配器，`bff/main.py` 的事件路由，`core/agent_steps.py` 的 `last_scored` 裁剪。
- 约束：不改 schema；`AGENT_HARNESS=off` 可回旧路径；v1 不流式；单用户本地；出题/评分/结算算法不变。

## Goals / Non-Goals

**Goals:**

- 把 17 个当前工具 + 3 个回合的目录、A/P/U 结果分离、G1–G8、8/4/60 预算写进 `agent-harness` spec。
- 在现有循环里实现预算 8/4/60、单工具 4 次与计数口径；保持 3 个 agent 工具不变。
- 结果路由可验收：A 回模型、P 直传程序/前端、U 页面直显，agent 不得复述/改写。
- 程序工具次数不变量落在程序路径，不塞进 agent 循环。

**Non-Goals:**

- 不新增 agent 工具；不做 `read_material` / `read_progress` / `validate_questions` / `capture_hot_item`。
- 不改出题、评分、mastery、复习排期、知识入库/检索算法。
- 不加表、不做工具轨迹回放、不做多用户/云部署、不做流式。
- 不把“先本地后网页”做成执行器强制顺序。

## Decisions

### D1. 复用 `agent-harness` capability，不新建 `tool-contracts`

现有 `agent-harness` 已经拥有工具回合、预算、写边界和来源规则；工具规格书是同一行为的细化。新建 capability 会造成预算和工具边界两份真相。备选是新建 `tool-contracts`，代价是归档顺序与重复 requirement。

### D2. Agent 工具仍是 3 个，程序工具永不注册

`search_materials` / `search_web` / `read_concept` 保留；`generate_questions` / `score_answer` / 进度与会话工具只存在于程序路径。`ToolRegistry` 只注册 3 个 spec，任何程序工具名都走 `unknown_tool`。备选是把 `read_progress` 或 `read_material` 加给模型，当前收益不足，留作 v2 评测后再看。

### D3. A/P/U 在事件边界实现，不靠提示词

工具适配器返回结构化字段；`AgentLoop` 只把 A 类观测拼进 `tool` 消息，`bff/main.py` 只把 P 类写库/推进、U 类发 WS 事件，`agent_steps.py` 只把裁剪后的 `last_scored` 放进 StepBrief。备选是全部交给提示词，无法断言“模型复述了 P 类结果”。

### D4. 预算 8/4/60，单工具 4 次，按执行计数

`ToolBudget` 增加 `max_calls_per_tool=4`；`AgentLoop` 每次实际执行 `used += 1`，失败也加；被总预算/单工具/网页上限拦下的调用不加。模型调用上限仍为 `max_tool_calls + 1`。备选是只设总 8 次（一个工具可能吃满）或只设单工具 4 次（总次数无界）。

### D5. 程序工具次数不变量放在 `Coach` / `Agent` / `Store`

`generate_questions` 每场 1 次；`score_answer` 每题 1 次 + 重试 1 次；`save_answer` 幂等；`start_unit` / `finish_session` 每场 1 次；`resume_session` 每次重连 1 次。备选是把这些计数塞进 `AgentLoop`，但程序工具根本不经过 agent 循环。

### D6. 硬校验 + 软判断

执行器硬校验：工具白名单、步骤过滤、预算、结果路由、写权限、答案泄露过滤。提示词只负责：先本地后网页、换说法、何时停、是否引用来源。备选是全硬校验（连检索顺序也强制，模型失去判断空间）或全提示词（越权项不可靠）。

### D7. G1–G8 作为共享 guard，每工具特有禁令留在设计文档

通用禁令在 `ToolRegistry` / 执行器入口统一拦；每工具特有禁令写进 `tool-specs-v0.1.md`，不重复塞进 spec requirement。备选是每个工具一份 prompt 禁令，17 份会漂移。

### D8. `last_scored` 只做裁剪 + 提示词约束 + fixture 断言

StepBrief 只给题干、回答、分数、`why`、出处；提示词要求原样引用；测试用固定分数断言“改数/冒充评分”失败。备选是删掉 `last_scored`（丢失 AH-19 的“为什么只有 60 分”能力）或允许自由解释（数字会漂移）。

### D9. 验收在 WS/DB/Playwright 层

预算计数用 WS 事件与日志观测；A/P/U 用回复文本与事件字段断言；页面用 Playwright 检查来源、状态、分数。禁止断言内部函数调用顺序。备选是单测内部调用，脆弱且不符合项目验收规则。

## Risks / Trade-offs

- [60 秒等待] → 页面提前显示 `agent_status`；超时走兜底；后续按评测收紧到 45 秒或 6 次。
- [模型过度搜索] → 8/4/60 是 v1 宽松上限，先用评测观察自然停点；不合格先调提示词，不改硬边界。
- [P/U 语义复述无法完全机器判定] → 固定 fixture + 关键短语断言；更复杂的语义判断留给人工抽检。
- [单工具 4 次可能被本地检索吃满] → 总预算仍留 4 次给网页/概念；若评测发现本地挤压网页，改为按领域配额。
- [程序工具被误注册] → 只注册 3 个 spec；用 `unknown_tool` 测试覆盖所有程序工具名。
- [`AGENT_HARNESS=off` 行为漂移] → 新预算只在 on 路径生效；off 回归测试保持旧 3/2/30。
- [不改 schema 导致工具轨迹不可回放] → 只写日志 + `sources_json`；审计需求出现后再评估表。

## Migration Plan

1. 改预算常量与循环：`core/agent_tools.py`、`core/agent_loop.py`；先跑现有测试，确认 off 路径不变。
2. 改结果路由：`bff/agent_tools.py`、`bff/main.py`、`core/agent_steps.py`；补 A/P/U 断言。
3. 改页面展示：`web/app.js`；Playwright 检查来源、状态、分数。
4. 跑 `tool-specs-v0.1.md` §7 验收钩子 + 全量回归；`AGENT_HARNESS` 保持默认 off。
5. 更新文档哈希；评审通过后归档本 change。回滚只需 `AGENT_HARNESS=off`，无 schema 回滚。

## Open Questions

- 评测后预算收到 6/3/45 还是保留 8/4/60？只影响常量，不影响 spec 结构。
- `read_material` / `read_progress` 是否在 v2 加给模型？当前明确不做，评测出现“细节不够/进度答不准”再评估。
- “P 类结果被语义复述”是否需要 LLM 评审器？先用 fixture 断言，暂不引入额外模型调用。
