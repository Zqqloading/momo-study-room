# Tasks

## 0. 前置

- [x] 0.1 停服务，备份 `data/app-v5.db` 到 `data/app-v5.pre-v7.db`；验证备份可打开、`PRAGMA user_version` 为 6
- [x] 0.2 确认 `USER_ID=owner`、`USER_ROLE=learner`、`EMOTION_ENABLED=on`、`MEMORY_ENABLED=on` 的默认值写入 `bff/config.py`；Slice 1 没有记忆读取点，flag 保持 on
- [x] 0.3 在 `docs/designs/persona-settings-v0.1.md`、`user-memory-v0.1.md`、`emotion-state-v0.1.md`、`emotion-expression-v0.1.md` 标注本次落地的口径（LIFE 只在开场、评分只多一句、`user_id`、事件契约）；四份均已跟随各自 slice 更新

## 1. Slice 0 — 共享 composer + 人设/纪律

- [x] 1.1 新增 `core/prompt.py`：`PromptBlocks`、`compose_system_prompt()`；固定顺序 `ROLE → PERSONA → TONE → MEMORY → TASK → CONTEXT → DISCIPLINE → DATA`；空块跳过；`DATA` 最后；验证 `tests/test_prompt.py`
- [x] 1.2 改 `core/persona.py`：`PersonaConfig`（entries + life_pool）、`PersonaEntry`、`load_persona()` 返回 config、`default_persona()`、`render_persona()`；保留 `LifePool.for_date()`；验证 `tests/test_persona.py`
- [x] 1.3 `persona.yaml` 补 22 条 entries（5 WHO / 5 VOICE / 6 TABOO / 6 LEARN，第一人称），保留 30 条 life items；验证加载、预算 1200/120、单条 ≤120
- [x] 1.4 新增 `core/discipline.py`：D1-D5 文本 + 面映射；自由对话 D1/D2，教学/澄清 D1/D2/D5；评分 D3，出题 D2/D4，抽取 D2；验证 `tests/test_discipline.py`
- [x] 1.5 改 `core/free_talk.py`：`build_free_talk_messages` 改接 `PromptBlocks`；teach 任务层改为“先正面解释，再最多追问一句”；验证 `tests/test_free_talk.py`
- [x] 1.6 改 `core/agent_loop.py` / `core/agent_steps.py`：`AgentLoop` 构造接 `PersonaConfig`，纪律用 `core.discipline` 模块函数；`build_system_prompt` 走 composer；`StepBrief` 加 `tone_hint` / `memory_context`（本刀留空）；验证 `tests/test_agent_loop.py` / `test_agent_steps.py`
- [x] 1.7 改 `bff/main.py`：`app.state.persona`；`_send_session_ready` 接 `opening_preamble`；开场先只拼生活句；验证 `tests/test_ws.py`
- [x] 1.8 改 `bff/probe.py:162` 开场白为“我是 MOMO，你的学习搭子”；改 `core/scoring.py:44` 只加“反馈只评价答案，不评价用户本人；不讽刺、不贬低”；验证 `tests/test_probe.py` / `tests/test_scoring.py`
- [x] 1.9 快照测试：FT-C、FT-T、AG-F、AG-T；断言 block 顺序、无 LIFE、data 最后、全关仍有纪律
- [x] 1.10 跑 `python -m pytest -q`；563 passed

## 2. Slice 1 — schema v7 + 情绪 + 表情

- [x] 2.1 `core/db.py`：`SCHEMA_VERSION=7`；`AFFECT_SCHEMA_SQL` 建 `emotion_states`、`user_memories`、`user_memories_fts`、`memory_runs`；`init_schema()` 执行；验证 v6 库升级后四表存在、旧表不变
- [x] 2.2 `bff/config.py`：加 `USER_ID`、`USER_ROLE`、`EMOTION_ENABLED`、`MEMORY_ENABLED`；默认值正确；验证 `tests/test_config.py`
- [x] 2.3 新增 `core/emotion.py`：衰减、夹取、0.1 half-up 取整、3×3 语气提示、更新提示词/解析；验证 `tests/test_emotion.py`
- [x] 2.4 新增 `bff/emotion.py`：scorer JSON、800ms 超时、失败用旧状态、每 `(user_id, role)` 锁；验证 `tests/test_emotion_bff.py`
- [x] 2.5 改 `bff/main.py`：自由对话/教学/澄清回复前更新；`ready.emotion`、`session_ready.emotion`、独立 `emotion` 事件；答题不更新；验证 `tests/test_ws.py`
- [x] 2.6 改 `web/app.js`：mood/setMood、3×3 表情 lerp、`head`/`neck` 轻微动作、说话压到 15%、眨眼保持；处理 `emotion` 事件；验证 `tests/browser/check_emotion_face.mjs`
- [x] 2.7 `EMOTION_ENABLED=off` 回归：不调 updater、不发事件、前端 neutral；验证 `tests/test_ws.py`
- [x] 2.8 更新 `docs/designs/emotion-state-v0.1.md` / `emotion-expression-v0.1.md` 的 schema/事件/开关
- [x] 2.9 跑 `python -m pytest -q`；596 passed

## 3. Slice 2 — 用户记忆

- [x] 3.1 新增 `core/memory.py`：强度/半衰期/沉底/排序/渲染/解析；验证 `tests/test_memory.py`
- [x] 3.2 新增 `core/memory_extraction.py`：提炼提示词、JSON schema、子串校验、诊断/进度词、去重；验证 `tests/test_memory_extraction.py`
- [x] 3.3 新增 `bff/memory_extraction.py`：finish 后异步任务、`app.state.memory_tasks`、scorer、1 次重试、`memory_runs`；验证 `tests/test_memory_async.py`
- [x] 3.4 改 `core/store.py`：`add_user_memory`、`user_memories(user_id)`、`update_memory_recall`、`search_user_memories`、`rebuild_user_memory_fts`、`memory_runs`；验证 `tests/test_store_memory.py`
- [x] 3.5 改 `bff/main.py`：单元开始取 top 3、拼 `opening_preamble`；自由对话（含 agent）显式回忆；`StepBrief.memory_context`；验证 `tests/test_ws.py` / `tests/test_memory_bff.py`
- [x] 3.6 `MEMORY_ENABLED=on`；关闭回归：不提炼、不读、不拼开场；验证 `tests/test_ws.py`
- [x] 3.7 更新 `docs/designs/user-memory-v0.1.md`：`user_id`、schema v7、开场顺序、teach 不进记忆
- [x] 3.8 跑 `python -m pytest -q`；655 passed

## 4. Slice 3 — 联调 + 文档

- [x] 4.1 端到端：开始 → 开场生活+记忆 → 自由对话 tone/emotion → 结束提炼 → 下一单元记忆；验证 `tests/test_affect_integration.py` + `tests/browser/check_affect_integration.mjs`
- [x] 4.2 两套 flag 回归：`MEMORY_ENABLED=off` / `EMOTION_ENABLED=off`；验证 `tests/test_ws.py`
- [x] 4.3 全量 `python -m pytest -q`；656 passed
- [x] 4.4 更新 `VERSIONS.md` / `GLOSSARY.md`：设定集、人设条目、生活素材、教学纪律、注入面、用户记忆、情绪状态、待机表情
- [x] 4.5 评审通过后 `openspec archive m06-affect-layers`，同步 main specs
- [x] 4.6 不提交；等用户明确“提交”后再按指定信息提交

## 回滚

- v7 前：`data/app-v5.pre-v7.db` 备份；旧代码拒绝打开 v7，回退代码必须恢复备份。
- 功能回滚：`MEMORY_ENABLED=off` / `EMOTION_ENABLED=off`，不需要恢复 DB。
- 人设回滚：`persona.yaml` 的 22 条 entries 全部 `enabled: false`；生活池保留。
- Slice 0 不改 DB，可单独 revert。
