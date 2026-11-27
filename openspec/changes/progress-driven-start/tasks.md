# Tasks

依据：`proposal.md`、`design.md`、`specs/coach-session/spec.md`、`specs/learning-unit/spec.md`、`docs/designs/progress-driven-start-v0.1.md`。

## 1. 取数与选题器

- [x] 1.1 在 `core/store.py` 增加 `latest_concept_assessments(concept_ids)`：join `session_questions` / `agent_sessions` / 可选 `sessions`，按概念取最近一次有评分的 `avg_score`/`min_score`/`date`；验证：新增 `tests/test_store.py` 用例覆盖 completed、partial、abandoned、review 角色、未评分跳过
- [x] 1.2 新增 `core/selection.py` 的 `select_topic()`：最近失手 → 掌握度最低（含 0）→ 全 0 按天稳定随机；验证：新增 `tests/test_topic_selection.py` 覆盖各档位、并列、同一天两次一致、空 active
- [x] 1.3 实现稳定随机（`hashlib.sha256(today + ids)`）并验证不依赖 Python `hash()`；验证：同进程两次与跨进程（子进程）结果一致

## 2. Coach 复用与开场白

- [x] 2.1 `Coach._select_plan()` 改用 `select_topic()`，`propose()` 与 `start()` 共用；主概念作为 `role=new`，复习概念仍取最逾期；验证：`tests/test_proposal.py` 断言两处选中同一主题，`tests/test_coach_flow.py` 不回归
- [x] 2.2 `StartedSession` 增加 `intro`/`focus`，`ProposalConcept` 增加 `reason_kind`；实现 `_intro_text()` 三档文案；验证：`tests/test_proposal.py` 断言 `reason_kind` 与理由，`tests/test_coach_flow.py` 断言 `intro` 含主题名与档位
- [x] 2.3 覆盖同日答错场景：完成一场低分会话后，即使 `review_due_at` 为次日，`propose()/start()` 仍选中 X；验证：新增测试用固定 clock 写入当天会话后断言

## 3. BFF 协议与音频

- [x] 3.1 `session_ready`（start）序列化 `intro`/`focus`；`_send_session_ready()` 先推 intro TTS 再推第一题音频；`session_resume` 不带 intro、不重播；验证：`tests/test_ws.py` 断言字段、事件顺序与 resume 行为
- [x] 3.2 `GET /api/kb/overview` 传入 `latest_concept_assessments()`，`weak` 口径改为“最近失手或 mastery<=1 且学过”；验证：`tests/test_progress.py`、`tests/test_kb_api.py` 更新并通过
- [x] 3.3 TTS 失败降级：intro 音频失败时仍发第一题音频、文本可见；验证：`tests/test_ws.py` 用失败 TTS 假实现断言会话继续

## 4. 前端开场白

- [x] 4.1 `web/index.html` 增加题目上方的 `#intro` 容器；`web/app.js` 在 `session_ready` 写入 `intro`，`question` 事件不清除；`web/style.css` 增加样式；验证：`tests/browser/check_progress_start.mjs` 或现有 browser smoke 断言可见
- [x] 4.2 保持音频队列顺序：intro 音频先于第一题；前端不额外控制；验证：浏览器 smoke 断言首题出现前 intro 已显示，且无 console error

## 5. 验收与回归

- [x] 5.1 新增“答错 → 结束 → 新建对话 → 开始”验收用例：断言 `intro` 含 X、第一题 `concept_id=X`、新建对话前后 `concepts` 行不变；验证：WS/浏览器脚本通过
- [x] 5.2 运行 `.venv/Scripts/python.exe -m pytest -q`，全绿；记录通过数，确认 `test_proposal`/`test_progress`/`test_ws`/`test_store` 无回归
- [x] 5.3 重启服务后重复 5.1，确认判断来自 `data/app-v5.db` 而非内存；验证：手工记录 `propose()` 结果与 `PRAGMA user_version` 仍为 6
- [x] 5.4 更新 `docs/designs/progress-driven-start-v0.1.md` 状态为 REVIEW，并按字节重算 `docs/designs/VERSIONS.md` 的 SHA-256；验证：哈希与文件一致

## Workflow follow-up

- 按项目评审要求完成 review 后，执行 `/opsx:archive` 归档并同步 specs。
- 归档后确认 `openspec/specs/coach-session/spec.md` 与 `openspec/specs/learning-unit/spec.md` 已包含本变更的新增/修改 requirements。
- 若实现期间改动决策文档，同步 `VERSIONS.md` 的 SHA-256。
