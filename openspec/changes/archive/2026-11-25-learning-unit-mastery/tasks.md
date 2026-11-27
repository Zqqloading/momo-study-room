# Tasks

依据：`proposal.md`、`design.md`、`specs/learning-unit/spec.md`、`specs/coach-session/spec.md`、`docs/designs/learning-unit-v0.1.md`。

## 1. 提议与领域模型

- [x] 1.1 在 `core/models.py` 增加 `MASTERY_LABELS`（0 未掌握、1 初识、2 有印象、3 基本掌握、4 熟练、5 精通）、`ProposalConcept`、`ProposalSlot`、`UnitProposal`、`ConceptUnitResult`；验证：导入模块后标签覆盖 0–5，数据类可序列化
- [x] 1.2 在 `core/coach.py` 抽出只读 `propose()`，复用 `Planner.next_concept`、`store.due_reviews` 与 `build_session_plan`；验证：`tests/test_proposal.py` 覆盖有/无复习、review-only、同概念、不可用与两次调用一致
- [x] 1.3 为提议补理由与字段：主概念难度/前置/上次学习、复习到期/逾期/上次得分、`deferred_reviews`；验证：`tests/test_proposal.py` 断言理由字段与 `available=false` 的 200 语义
- [x] 1.4 验证提议无副作用：连续调用前后 `sessions`、`agent_sessions`、`concepts` 行数不变；验证：`tests/test_proposal.py` 的写库计数断言

## 2. 掌握程度读模型

- [x] 2.1 在 `core/store.py` 增加 `recent_units(limit=5)`，返回 session 基本信息与涉及 concept id；验证：`tests/test_progress.py` 覆盖 daily/review-only 与空历史
- [x] 2.2 新增 `core/progress.py`：`build_overview()` 计算 active 数、平均 mastery（一位小数）、0–5 分布、weak（`mastery<=1` 且 `last_seen` 非空）、due/overdue、active 概念列表与最近单元；验证：`tests/test_progress.py` 覆盖统计、排序、空知识库
- [x] 2.3 在 `core/progress.py` 用 `MASTERY_LABELS` 输出展示标签，标签不写库；验证：`tests/test_progress.py` 断言标签覆盖 0–5 且不改变 mastery

## 3. 结算摘要

- [x] 3.1 在 `core/coach.py` 的 `finish()` 中，`store.finalize()` 前读取本场涉及概念的 mastery，结算后读取 after 与 `review_due_at`，构造 `Settlement.concepts`；验证：`tests/test_settlement.py` 覆盖 completed 的 before/after 与 due
- [x] 3.2 从 `session_questions` 按 `concept_id` + `question_role` 聚合已评分题，输出 `new_score`/`review_score` 与 `roles`；验证：`tests/test_settlement.py` 覆盖同概念 3 new + 2 review
- [x] 3.3 保持既有 mastery 与复习规则：partial/unscored/review-only 不更新 mastery，摘要 `mastery_updated=false`；验证：`tests/test_settlement.py` 四类场景与现有 mastery/结算测试全绿
- [x] 3.4 在 `bff/main.py` 的 `_result_event` 序列化 `concepts`，保留 `mastery`/`scores`/`review_due_at` 原字段；验证：`tests/test_ws.py` 断言字段形状与旧字段仍在

## 4. HTTP 只读接口

- [x] 4.1 新增 `bff/knowledge.py`，实现 `GET /api/kb/unit/proposal` 与 `GET /api/kb/overview`，使用 `app.state.store`/`concepts`/`clock`；验证：`tests/test_kb_api.py` 覆盖 200、`available=false`、空知识库与 JSON 字段
- [x] 4.2 在 `create_app()` 中把 router 注册在静态资源挂载之前；验证：`tests/test_kb_api.py` 请求两个路径不被 `StaticFiles` 吞掉，`/` 仍能打开页面
- [x] 4.3 验证两个接口不写库、不调 provider：fake 模式下无 LLM/TTS/搜索调用；验证：`tests/test_kb_api.py` 的调用计数与数据库行数断言

## 5. WS 加法字段

- [x] 5.1 在 `session_ready`（start 与同日 `session_resume`）增加 `unit`：`kind`、`main`、`review`，由 `session_questions` 的 `role` 推导，概念名缺失回退 id；验证：`tests/test_ws.py` 覆盖 daily、review-only、resume、未知概念
- [x] 5.2 确认 `session_start` 消息形状、事件顺序与既有必填字段不变；验证：现有 `tests/test_coach_flow.py`、`tests/test_ws.py` 不回归
- [x] 5.3 确认 `session_result.concepts` 在 completed/partial/unscored/review-only 下均可序列化且不新增写库；验证：`tests/test_ws.py` 与 `tests/test_settlement.py` 交叉断言

## 6. 知识库面板与结果卡

- [x] 6.1 在 `web/index.html` 增加「知识库」按钮、`#kbpanel` 覆盖层与会话顶部 `#unitlabel`，在 `web/style.css` 增加面板/分布条/掌握度点/移动端 sheet 样式；验证：页面静态加载无 404，`?v=` 缓存串已更新
- [x] 6.2 新增 `web/kb.js`：并行请求提议与总览、渲染今日单元/掌握程度/最近单元、处理加载/错误/空状态、`canStartUnit()` 与 `onStartUnit()` 回调；验证：浏览器 smoke 覆盖打开、不可用、错误重试
- [x] 6.3 在 `web/app.js` 接线「知识库」按钮与开始回调；`session_ready` 显示 `unit`；`showResult()` 使用 `result.concepts` 渲染 before→after、得分、标签与「查看知识库」，移除原始 `mastery` map；验证：浏览器 smoke 覆盖 completed/partial/unscored/review-only 结果卡
- [x] 6.4 新增 `tests/browser/check_kb_panel.mjs`，用真实 fake 后端或路由 mock 覆盖桌面/移动、开场、进行中、结果卡跳转与 Esc/遮罩关闭；验证：脚本运行通过且无 console error

## 7. 集成检查

- [x] 7.1 运行 `python -m pytest -q`，现有测试与新增测试全绿；验证：记录通过数，确认无回归
- [x] 7.2 运行浏览器 smoke（`PLAYWRIGHT_CORE=... BASE_URL=... node tests/browser/check_kb_panel.mjs`）；验证：桌面/移动均通过，结果卡与面板数据来自接口
- [x] 7.3 验证无 schema 迁移：`PRAGMA user_version` 仍为 6，`sqlite_master` 无新增表/列；验证：启动后查询数据库并对比
- [x] 7.4 验证提议与实际开始一致：同一天、同一状态连续提议后开始，`session_ready.unit` 与提议主/复习概念一致；验证：手工或 API+WS 联调记录

## Workflow follow-up

- 按项目评审要求完成 review 后，执行 `/opsx:archive` 归档并同步 specs。
- 归档后确认 `openspec/specs/learning-unit/spec.md` 与 `openspec/specs/coach-session/spec.md` 已包含本变更的新增 requirements。
- 若实现期间更新了 `docs/designs/learning-unit-v0.1.md`，同步更新 `docs/designs/VERSIONS.md` 的 SHA-256。
