# Tasks

## 1. 预算与循环（8/4/60）

- [x] 1.1 更新 `core/agent_tools.py` 的预算常量与 `ToolBudget`：`MAX_TOOL_CALLS=8`、`MAX_WEB_CALLS=4`、新增单工具上限 4、`deadline_seconds=60`；同步 `core/agent_steps.py` 的默认 Brief；验证 `tests/test_agent_tools.py` 与 `tests/test_agent_steps.py` 通过
- [x] 1.2 更新 `core/agent_loop.py`：每次实际执行 `used += 1`（失败也计），总预算/单工具/网页上限拦下的调用不计；模型调用上限保持 `max_tool_calls + 1`；验证 `tests/test_agent_loop.py` 覆盖 8 次总上限、单工具 4 次、网页 4 次、失败计数、拦下不计
- [x] 1.3 验证 60 秒硬截止与收口：用可控 `clock` 让回合超时，断言返回兜底且不写任何状态；验证 `tests/test_agent_loop.py` 的超时用例
- [x] 1.4 验证 `AGENT_HARNESS=off` 旧路径不受新预算影响（旧路径不经过 `AgentLoop`）；跑 `tests/test_free_talk.py` / `tests/test_ws.py` 全绿

## 2. 工具目录与不暴露

- [x] 2.1 确认 `ToolRegistry` 只注册 `search_materials` / `search_web` / `read_concept`；用 `tests/test_agent_tools.py` 断言其余 14 个工具名 + 3 个回合名全部返回 `unknown_tool`
- [x] 2.2 验证三个步骤的工具面：`free_talk` / `teach` / `clarify` 都只给 3 个只读工具；作答路径不给任何工具；验证 `tests/test_agent_loop.py` 与 `tests/test_agent_ws.py`
- [x] 2.3 验证命令只由用户触发：`skip_question` / `repeat_question` / `end_session` 走 `_handle_text` / WS 命令分支；agent 请求这些名字返回 `unknown_tool`；验证 `tests/test_agent_ws.py` 命令用例
- [x] 2.4 验证离线工具不可调用：`ingest_material` / `backup_db` 不在运行时注册；验证 `tests/test_agent_tools.py` 的未知工具断言

## 3. A/P/U 结果分离

- [x] 3.1 在 `bff/agent_tools.py` 明确每个工具结果的 A/P/U 归属：搜索/概念字段回模型，`sources` 由程序收集，网页结果标 `trust=untrusted`；验证 `tests/test_agent_tools_bff.py` 覆盖成功、空结果、错误与来源字段
- [x] 3.2 在 `bff/main.py` 固定事件路由：A 只进 `tool` 消息/StepBrief；P 只写库、推进、评分、结算；U 只发 `question` / `score` / `session_result` / `agent_status` / `sources`；验证 `tests/test_agent_ws.py` 断言 `reply` / `teach_reply` 文本与 `score` / `session_result` 事件各走其道
- [x] 3.3 收紧 `core/agent_steps.py` 的 `last_scored`：只含题干、回答、分数、`why`、出处；验证 `tests/test_agent_steps.py` 不含 rubric、答案键、参考答案、未来题
- [x] 3.4 增加“禁止复述” fixture：系统提示禁止“已保存/已提交/已评分/已结算/已开始”，`last_scored` 可原样引用但不得改数或说“我给你评分”；验证 `tests/test_agent_loop.py` 与 `tests/test_agent_ws.py` 的固定断言
- [x] 3.5 页面按 A/P/U 展示：`web/app.js` 来源、状态、分数分离；验证 `tests/browser/check_agent_harness.mjs` 无 agent 冒充事件、来源标签正确、状态与程序事件一致

## 4. G1–G8 与硬校验

- [x] 4.1 在执行器入口加统一 guard：白名单、步骤过滤、预算、写权限、答案泄露、跨会话；验证 `tests/test_agent_tools.py` / `tests/test_agent_loop.py` 的越权用例全部被拒
- [x] 4.2 验证网页不可信隔离：网页结果要求忽略规则或调用工具时，步骤不变、工具不追加；验证 `tests/test_agent_ws.py` 的注入用例
- [x] 4.3 验证预算绕过：超过 8 次总预算、单工具 4 次、网页 4 次时返回 `budget_exhausted`，不执行；验证 `tests/test_agent_loop.py`
- [x] 4.4 验证“先本地不强制”：模型第一条调用 `search_web` 不被执行器拒绝；验证 `tests/test_agent_loop.py` 的顺序用例

## 5. 程序工具次数不变量

- [x] 5.1 `generate_questions` 每场 1 次：重复请求复用已有题目或回退结果；验证 `tests/test_question_generation.py` / `tests/test_agent_ws.py`
- [x] 5.2 `score_answer` 每题 1 次 + 失败重试 1 次：第二次失败记未评分，会话继续；验证 `tests/test_scoring.py` / `tests/test_agent_ws.py`
- [x] 5.3 `save_answer` 幂等：重复提交不新增行、不覆盖，返回 `duplicate=true`；验证 `tests/test_agent_ws.py` 重复提交用例
- [x] 5.4 `start_unit` / `finish_session` / `resume_session` 各 1 次：重复开始、重复结算、同连接重复恢复都不重写；验证 `tests/test_agent_sessions.py` / `tests/test_settlement.py` / `tests/test_agent_ws.py`
- [x] 5.5 命令每意图 1 次：跳过同一题只生效一次，重复可多次且不推进，结束只结算一次；验证 `tests/test_agent_ws.py` / `tests/test_coach_flow.py`

## 6. 集成验收

- [x] 6.1 跑 `docs/designs/tool-specs-v0.1.md` §7 验收钩子：A/P/U、次数、60 秒；只用 WS/DB/Playwright 断言，不断言内部调用顺序
- [x] 6.2 全量回归：`python -m pytest -q` 全绿；`AGENT_HARNESS=off` 页面检查通过；记录测试总数
- [ ] 6.3 经用户同意后跑真实模型冒烟（10 条判断力 + 8/4/60 自然停点），记录结果；不放进 pytest 默认路径
- [x] 6.4 更新 `docs/designs/tool-specs-v0.1.md` / `docs/designs/VERSIONS.md` 的实现状态与哈希；确认 `AGENT_HARNESS=off` 回滚路径可用

## Workflow follow-up

- 评审通过后运行 `openspec archive tool-spec-contracts`，同步 `agent-harness` / `web-search` main specs。
- 归档后确认 `agent-harness` 已包含 8/4/60、单工具 4 次、A/P/U、G1–G8 与程序工具不暴露；`web-search` 已从 2 次改为 4 次。
