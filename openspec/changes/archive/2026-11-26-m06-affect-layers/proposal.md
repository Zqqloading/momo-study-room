# Proposal

## Why

三份 DRAFT 设计已经成形，但还没有落到代码：`persona-settings-v0.1.md`（设定集 + 硬编码纪律）、`user-memory-v0.1.md`（关于用户的长期记忆）、`emotion-state-v0.1.md`（两个情绪数 + 语气提示 + 待机表情）。它们都改提示词、都用 SQLite 状态、都影响会话开场或回复；分开落会各自拼一套 prompt、各自算开场，最后一定打架。

本次把三块一起落，先建共享 composer 和身份键，再按“人设 → 情绪 → 记忆”三刀实现，最后一刀联调。

## What Changes

- **共享 composer**：新增 `core/prompt.py`，统一 `ROLE → PERSONA → TONE → MEMORY → TASK → CONTEXT → DISCIPLINE → DATA`；free talk 和 agent 都走它。
- **人设**：`core/persona.py` 从只读生活池升级为 `PersonaConfig`（22 条 entries + 30 条 life pool）；新增 `core/discipline.py` D1-D5；`persona.yaml` 补 entries。
- **情绪状态**：`comfort` [-1,1]、`energy` [0,1]，0.1 步长；回复前同步更新，答题不更新；`ready.emotion` + 独立 `emotion` 事件。
- **情绪表情**：`web/app.js` 把 `(comfort, energy)` 映射到 `happy` / `relaxed` / `sad` / `angry` / `neutral`，加轻微 `head` / `neck` 动作；说话时压到 15%。
- **用户记忆**：`user_memories` + FTS5 trigram + `memory_runs`；单元结束异步提炼 ≤5 条；单元开始取 top 3、≤300 字拼开场；自由对话支持显式回忆。
- **一次 schema v7**：`emotion_states`、`user_memories`、`user_memories_fts`、`memory_runs` 同一次迁移；记忆带 `user_id`，情绪带 `(user_id, role)`。
- **配置**：`USER_ID=owner`、`USER_ROLE=learner`、`MEMORY_ENABLED=on`、`EMOTION_ENABLED=on`；人设不加 flag。
- **开场**：生活句 → 记忆块 → 原 intro；前导 ≤360 字；LIFE 不进自由对话。

## Capabilities

### New Capabilities

- `persona`：设定集、生活素材池、教学纪律硬编码。
- `user-memory`：三类记忆、半衰期、异步提炼、开场读取、显式回忆。
- `emotion-state`：两个情绪数、衰减、更新、事件、持久化。
- `emotion-expression`：VRM 表情映射、轻微头部动作、说话/眨眼冲突。

### Modified Capabilities

- `free-talk`：人设/语气/记忆上下文；情绪事件；teach 任务层。
- `coach-session`：开场生活 + 记忆句；评分反馈措辞；`session_ready.emotion`。
- `agent-harness`：`StepBrief` 加 `tone_hint` / `memory_context`；系统提示拼装顺序；答题回合不更新情绪。

## Impact

- 代码：新增 `core/prompt.py`、`core/discipline.py`、`core/emotion.py`、`core/memory.py`、`core/memory_extraction.py`、`bff/emotion.py`、`bff/memory_extraction.py`；改 `core/persona.py`、`core/free_talk.py`、`core/agent_loop.py`、`core/agent_steps.py`、`core/scoring.py`、`bff/main.py`、`bff/config.py`、`core/db.py`、`core/store.py`、`bff/probe.py`、`web/app.js`、`persona.yaml`。
- 数据：schema v6 → v7，只加表；不改进度表；迁移前必须备份 `data/app-v5.db`。
- 外部服务：情绪 updater 和记忆提炼复用 `providers.scorer`；无新依赖。
- 测试：新增 composer/persona/discipline/emotion/memory 测试与页面表情验收；全量回归。

## Out of Scope

- 会话内 `teach` / `clarify` 落库并进入记忆提炼（本期只读作答 + probe/teach_back）。
- 自由对话注入 LIFE（本期 LIFE 只在单元开场）。
- 情绪答题回合更新（本期只在自由对话/教学/澄清的回复前更新）。
- 大动作、TTS 音高/语速变化、`Surprised` / `Extra` 待机。
- 改评分口径、题目数量、引用规则、答案揭示规则。
