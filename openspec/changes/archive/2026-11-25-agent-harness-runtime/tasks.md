# Tasks

## 1. 工具做实（第一步）

- [x] 1.1 在 `requirements.txt` 增加 `openai` 依赖，安装后跑 `python -m pytest -q`，验证现有测试全绿且 `core/` 不 import SDK
- [x] 1.2 新建 `core/agent_tools.py`：`ToolSpec` / `ToolCall` / `ToolResult` / `ToolError` / `ToolBudget` / `ToolRegistry`；用单测验证成功、空结果、错误信封与预算计数
- [x] 1.3 在 `bff/agent_tools.py` 实现 `search_materials`（复用 `bff.retrieval.retrieve_text`）；用 fake embedder/retriever 验证成功、空结果、provider error，且不写库
- [x] 1.4 实现 `search_web`（复用 `providers.search` + `filter_web_results`）；验证成功、空结果、`search-off`、超时四种观测，并断言 `materials`/`concept_sources`/`question_bank` 行数不变
- [x] 1.5 实现 `read_concept`；验证命中、`not_found`、`invalid_arguments` 三种结果
- [x] 1.6 新建 `bff/agent_llm.py`：`openai.AsyncOpenAI` 适配器，把 SDK 的 `tool_calls` 转成 core 数据类型；用 fake transport 验证一次工具调用与最终文本
- [x] 1.7 实现来源去重/截断与工具结果大小上限（材料 ≤1200 字/条且 ≤3 条，网页 ≤600 字/条且 ≤3 条）；用单测验证去重、上限与来源顺序
- [x] 1.8 真实冒烟：经用户同意后，用 DeepSeek 与 MiMo 各跑 1 次工具调用；记录延迟与 `tool_calls` 形状，不放进 pytest 默认路径

## 2. 回合上下文与循环（第二步）

- [x] 2.1 在 `core/ports.py` 增加 `AgentClient` / `AgentMessage` / `AgentToolCall` / `AgentResponse`；静态检查 `core/` 不 import `openai`/`httpx`
- [x] 2.2 新建 `core/agent_steps.py` 的 `build_free_talk_brief`；快照测试字段齐全，且不含当前会话题、rubric、答案键
- [x] 2.3 增加 `build_teach_brief` / `build_clarify_brief`；验证包含当前题与 `last_scored`（题干/回答/分数/why/出处），且不含 rubric/答案键/未来题
- [x] 2.4 新建 `core/agent_loop.py`：预算、工具分派、超时、失败信封、预算用尽后无工具收口；用脚本化 `AgentClient` 验证工具→观测→最终、3 次上限、2 次网页上限、30 秒截止
- [x] 2.5 在 `core/agent_loop.py` 实现终局与兜底：无 tool_calls 收口、空文本兜底、模型调用失败返回 fallback；单测验证每种终局都返回非空结果
- [x] 2.6 实现来源组装与常识前缀：无来源时服务端加强制前缀，有来源时去重列最多 5 条；单测验证前缀只加一次、来源顺序稳定
- [x] 2.7 泄露与注入测试：`teach`/`clarify` 的 brief 不含未来题/rubric/答案键；网页指令性文本不改变步骤、不触发工具
- [x] 2.8 更新 `docs/designs/agent-harness-v0.1.md` 的 §11.2 技术假设与实现落点，确保文档与代码一致（若实现中调整了截断/历史条数）

## 3. 派发切换与页面（第三步）

- [x] 3.1 增加 `AGENT_HARNESS` 配置，默认 `off`；验证 `off` 下现有 WS/页面测试全绿、用户可见行为不变
- [x] 3.2 把 `bff/main.py:_free_talk_reply` 切到 `run_turn(free_talk)`；WS 测试验证 `reply` + `sources`、工具失败不崩、下一回合可用
- [x] 3.3 在 `_handle_text`/`_handle_audio` 按 `intent=teach|clarify` 分流；WS 测试验证 `teach_reply`、当前题不变、`session_questions` 无新行、`agent_sessions` 游标不变
- [x] 3.4 在 `Agent.submit`/`Coach` 实现重复作答幂等重放；WS 测试验证第二次提交只返回已有分数、`duplicate=true`，DB 只有一行
- [x] 3.5 在 `web/app.js` 持久化 `session_id`（`session_ready` 写、`ready` 恢复、结束/过期/重开清除）；Playwright 验证答 2 题后刷新回到第 3 题
- [x] 3.6 在页面增加“提问”按钮与二选一菜单、`teach_reply` 气泡与朗读、`agent_status` 状态、来源列表；Playwright 验证题目不变、无新分数、无 console error
- [x] 3.7 补齐 WS 协议加法字段（`intent`、`agent_status`、`teach_reply`、`score.duplicate`、`reply.sources`），验证旧事件形状不回归
- [x] 3.8 经用户同意后跑 10 条判断力冒烟（该查/不该查/换说法/拿到就停/工具失败/预算耗尽）；记录 ≥8/10 结果，不合格先调提示词
- [x] 3.9 跑接口/页面验收 H-A1…H-A14：5 题、重复提交、断点恢复、页面行为、工具回合、网页边界、失败、预算、作答零工具、教学不评分、不泄露答案；只用 WS/HTTP/DB/Playwright 断言，不断言内部调用顺序
- [x] 3.10 更新 `VERSIONS.md` / `FREEZE.md` / 设计文档的实现状态与哈希；确认 `AGENT_HARNESS=off` 回滚路径可用

## Workflow follow-up

- 评审通过后运行 `openspec archive agent-harness-runtime`，同步 main specs。
- 归档后确认 `free-talk` / `web-search` / `coach-session` / `tts-playback` 的新 requirement 已进入 main specs，`agent-harness` 新 spec 已创建。
