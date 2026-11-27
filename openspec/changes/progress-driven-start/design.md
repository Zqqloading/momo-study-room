# Design

## Context

见 `proposal.md` 的 Why。实现边界与完整决策依据见 `docs/designs/progress-driven-start-v0.1.md`；本文件只记录落地方式。

当前集成点：

- `Coach._select_plan()` 用 `Planner.next_concept()` 选主概念、`store.due_reviews()` 选最逾期复习概念，再调用 `build_session_plan()`。
- `Coach.propose()` 与 `Coach.start()` 各自调用 `_select_plan()`；主按钮只走 `start()`，面板走 `propose()`。
- `StartedSession` 只有 `session_id/kind/questions`；`session_ready` 只带 `unit` 与第一题。
- `core/progress.py` 的 `build_overview()` 是纯函数，只接收 concepts/states/recent_units/today；`weak` 只按 `mastery<=1`。
- 数据库仍是 `data/app-v5.db`（schema v6）；`session_questions` 有逐题分数，`agent_sessions` 有会话日期，`sessions` 可能因未结算而缺失。

## Goals / Non-Goals

**Goals:**

- 用一个选题器同时服务 `propose()` 与 `start()`，保证面板提议和实际开始一致。
- 最近失手能覆盖“同一天答错、复习到期是次日”“答错后未结算就再开始”两种情况。
- 开场白先于第一题音频；TTS 失败不阻塞。
- 面板 `weak` 与 agent 口径一致，不新增存储。

**Non-Goals:**

- 不重写出题、评分、结算、mastery 公式。
- 不新增表/列/迁移；不改 schema v6。
- 不做“换一个提议”、plan token、确认弹窗或概念地图 UI。
- 不做跨对话聊天记忆；只保证学习进度跨对话。

## Decisions

### D1：新增 `core/selection.py`，选题是纯函数

新增 `select_topic(states, assessments, concepts, today) -> Selection | None`，返回选中状态与 `reason_kind`（`recent_miss` / `lowest_mastery` / `no_signal`）及事实字段（最近得分、均分、掌握度）。`Coach._select_plan()` 调用它；`propose()` 与 `start()` 共用。

**Alternatives considered:**

- 直接改 `Planner.next_concept()`：Planner 当前只负责“新概念解锁”，把最近失手/随机塞进去会让它同时承担复习与新课两种语义，测试也难拆。
- 写在 `Coach` 私有方法：可以少一个文件，但选题规则会被 800+ 行的 Coach 淹没，单测要构造整个 Coach。
- 放 `core/progress.py`：进度读模型会反向依赖会话选题，职责倒置。

### D2：`Store.latest_concept_assessments()` 取每个概念最近一次有评分的作答

新方法返回 `{concept_id: ConceptAssessment(date, session_id, avg_score, min_score, scored)}`：

- 数据源 `session_questions q` join `agent_sessions a`，left join `sessions s`；日期取 `COALESCE(s.date, a.date)`。
- 只取 `q.score IS NOT NULL`；按 `(session_id, concept_id)` 聚合 `AVG/MIN/COUNT`。
- 按日期倒序后，每个 concept 取第一条；`completed` / `partial` / abandoned 都算。
- 不要求 `sessions.status=completed`，因为“答错”本身就是证据；未结算会话也能命中。

**Alternatives considered:**

- 复用 `recent_concept_scores()`：它只取 `role=new` + `completed daily`，会漏掉 review 题和未结算会话，正好漏掉验收场景。
- 在 `concepts` 加 `last_score`：要迁移，且 abandoned 会话不好同步。

### D3：`StartedSession` 与 `ProposalConcept` 增加展示字段

- `StartedSession` 增加 `intro: str` 与 `focus: Focus | None`（`concept_id/name/reason_kind`）。`Coach.start()` 在选题后、生成题目后构造；文案由 `_intro_text()` 按事实拼。
- `ProposalConcept` 增加 `reason_kind: str`；`_main_reason()` 保留人类可读理由，`reason_kind` 供前端/测试判断档位。
- 不新增持久化字段；`focus` 只存在于本次事件。

**Alternatives considered:**

- 让 LLM 生成开场白：慢、不可复现、可能编造理由；模板足够。
- 把 `intro` 写进题目正文：会污染题目文本、缓存键和评分上下文。

### D4：BFF 先发 `session_ready`，再推 intro 音频，再推第一题音频

`_send_session_ready()` 增加 `intro` 参数：

1. `session_ready` 带 `intro` / `focus` / `unit` / `question`。
2. 若有 `intro`，先调用现有 TTS 流推送 `utterance="intro"` 的音频；失败只记 warning，继续。
3. 再推送第一题音频；其余预生成逻辑不变。

`session_resume` 的 `session_ready` 不带 `intro`，避免重播。

**Alternatives considered:**

- 把 intro 拼进第一题 TTS：音频缓存键和预生成会混，且前端无法单独显示开场白。
- 前端先显示再等用户点击播放：破坏现有自动播放顺序和验收的“第一句话”。

### D5：`build_overview()` 增加可选 `assessments` 参数

`core/progress.py` 保持纯函数：新增可选 `assessments: Mapping[str, ConceptAssessment] | None = None`；`weak` 判定为 `recent_miss(id)` 或原有 `mastery<=1 且 last_seen`。`bff/knowledge.py` 调 `store.latest_concept_assessments()` 后传入；`Coach` 也复用同一方法，避免两套取数。

**Alternatives considered:**

- 在 `build_overview()` 内部查 store：纯函数变成有 IO，现有单测要造 DB。
- 只在 BFF 算 weak：`progress.py` 的单测和面板口径会分叉。

### D6：前端只增加一行开场白，不碰音频队列

`web/app.js` 在 `showQuestion()` 上方增加 `#intro` 元素（或复用题目卡片顶部一行），`session_ready` 时写入 `message.intro` 并显示；`question` 事件不清除它。音频仍由现有 `audio_chunk` 顺序播放，前端不额外控制。

**Alternatives considered:**

- 把 intro 塞进 chatlog：会话面板与自由对话是两套 UI，会把会话内容混进聊天记录。
- 前端定时隐藏 intro：验收需要第一句可见，隐藏会让回看变难；保留到本场结束更简单。

### D7：稳定随机的种子与实现

`seed = f"{today}:{','.join(sorted(ids))}"`；`index = int(hashlib.sha256(seed.encode()).hexdigest(), 16) % len(ids)`。同一天、同一池稳定；不依赖 Python `hash()`（进程间不稳定）。

**Alternatives considered:**

- `random.choice()`：每次调用不同，面板提议与开始会漂移。
- 按 `day_of_year % len`：可预测的循环，用户容易感觉“总是这几个”。

### D8：不新增 schema、不新增依赖

- 不新增表/列；schema v6 不变。
- 不新增 Python 依赖；`hashlib` 是标准库。
- 可选索引 `session_questions(concept_id, session_id)` 留到数据量变大再加；本次不加，避免迁移。

## Risks / Trade-offs

- [任一题 <60 就标记失手，可能对粗心错一题过于敏感] → 一次好作答就清掉；且用户明确要求“答错就要复习”。
- [最近一次作答来自 abandoned 会话，可能不是用户想复习的] → 分数是真实作答；下一次好作答会覆盖。
- [同一天重复开始会选同一主题] → 这是稳定随机的代价；跨天或状态变化后会变。需要“换一个”时再引入 plan token。
- [开场白多一次 TTS，增加首题延迟] → 限制 40 字内；TTS 失败降级纯文本；可复用缓存。
- [weak 口径变更会影响面板现有测试] → 更新 `test_progress` / `test_kb_api`，并在结果中说明这是有意变更。
- [review-only 路径在 start 中变得不可达] → 旧代码路径保留；本次不删除，避免影响历史 resume/测试。

## Migration Plan

1. 旧 change 已归档并同步 specs（2026-11-25）。
2. 本 change 实现后运行 `pytest -q`；无数据库迁移。
3. 回滚：删掉新 change 的代码改动即可；数据库不需要回滚（没有 schema/数据写入格式变化）。
4. 验收：按 `docs/designs/progress-driven-start-v0.1.md` 第 0 节的 7 步执行。

## Open Questions

（无；Q7/Q8 与 UI 细节已作为默认假设记录在决策文档第 10 节。）
