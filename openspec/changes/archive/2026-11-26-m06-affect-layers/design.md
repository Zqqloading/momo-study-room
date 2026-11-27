# Design

## 1. 跨方案契约

### 1.1 提示词拼装

唯一顺序：

```text
ROLE → PERSONA → TONE → MEMORY → TASK → CONTEXT → DISCIPLINE → DATA
```

- `PERSONA`：`persona.yaml` 的启用条目，按 WHO → VOICE → TABOO → LEARN。
- `TONE`：情绪状态翻译成的一句语气提示；`EMOTION_ENABLED=off` 时为空。
- `MEMORY`：只在用户显式要求回忆时出现；不是每回合注入。
- `LIFE`：不进系统提示词，只在单元开场前导。
- `DISCIPLINE`：D1-D5 及当前调用面适用的条目；永远在数据之前。
- `DATA`：agent 工单 JSON；不是指令，永远最后。

`core/prompt.py` 是唯一实现；`core/free_talk.py` 和 `core/agent_loop.py` 不再各自拼字符串。

### 1.2 开场

```text
生活句（≤60 字） → 记忆块（≤300 字） → 原 intro
前导合计 ≤360 字；没有记忆就只拼生活句；没有生活句就只拼记忆。
```

- BFF 的 `_send_session_ready` 接 `opening_preamble`（组合后的前导），不再接单个 `intro_prefix`。
- 事件 `intro` 与开场 TTS 使用同一份拼接文本。
- `session_resume` 不重播开场；自由对话不注入 LIFE。

### 1.3 事件

| 事件 | 时机 | 负载 |
|---|---|---|
| `ready` | WebSocket 连接 | 增加 `emotion: {comfort, energy, tone}` |
| `session_ready` | 单元开始 | 增加 `emotion`；`intro` 含生活 + 记忆 + 原 intro |
| `emotion` | 自由对话/教学/澄清更新后、回复前 | `{type, comfort, energy, tone}` |
| `reply` / `teach_reply` / `score` / `session_result` | 现有 | 负载不变 |

- 答题/评分/结算回合不发 `emotion`，也不更新状态。
- 前端 `setMood(comfort, energy)` 接收 `ready.emotion`、`session_ready.emotion`、`emotion`；没有数据时默认 `{0, 0.5}`。

### 1.4 数据与身份

一次 schema v7，四张表：

```sql
CREATE TABLE emotion_states (
  user_id TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'learner',
  comfort REAL NOT NULL CHECK (comfort BETWEEN -1 AND 1),
  energy REAL NOT NULL CHECK (energy BETWEEN 0 AND 1),
  updated_at TEXT NOT NULL,
  PRIMARY KEY (user_id, role)
);

CREATE TABLE user_memories (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('quote','preference','feeling')),
  text TEXT NOT NULL,
  source_quote TEXT NOT NULL,
  source_session_id TEXT,
  source_question_id INTEGER,
  strength REAL NOT NULL,
  half_life_days REAL NOT NULL DEFAULT 14.0,
  last_recalled_at TEXT NOT NULL,
  recall_count INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);

CREATE VIRTUAL TABLE user_memories_fts USING fts5(
  memory_id UNINDEXED,
  text,
  source_quote,
  tokenize='trigram'
);

CREATE TABLE memory_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id TEXT NOT NULL,
  session_id TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('running','succeeded','empty','failed')),
  memory_count INTEGER NOT NULL DEFAULT 0,
  error TEXT,
  started_at TEXT NOT NULL,
  finished_at TEXT
);
```

- `SCHEMA_VERSION=7`；`init_schema()` 执行 `AFFECT_SCHEMA_SQL`。
- 进度表、会话表、`session_notes` 不改。
- `USER_ID` 默认 `owner`；`USER_ROLE` 默认 `learner`。
- 记忆按 `user_id`；情绪按 `(user_id, role)`；人设全局，不按用户。

### 1.5 配置与开关

| 配置 | 默认 | 作用 |
|---|---|---|
| `USER_ID` | `owner` | 记忆/情绪的用户键 |
| `USER_ROLE` | `learner` | 情绪的角色键 |
| `EMOTION_ENABLED` | `on` | 关掉：不调 updater、不发 `emotion`、前端 neutral |
| `MEMORY_ENABLED` | `on` | 关掉：不提炼、不读、不拼开场 |

人设不加 flag；要临时回退，把 `persona.yaml` 的 22 条 entries 全部 `enabled: false`，生活池保留。

## 2. 实现切片

### Slice 0 — 共享 composer + 人设/纪律

- `core/prompt.py`：`PromptBlocks`、`compose_system_prompt()`、空块跳过、data 最后。
- `core/persona.py`：`PersonaConfig`、22 条 entries、30 条 life pool、预算 1200/120。
- `core/discipline.py`：D1-D5、按面映射。
- `core/free_talk.py`：接 `PromptBlocks`；teach 任务层改成“先正面解释，再最多追问一句”。
- `core/agent_loop.py`：`build_system_prompt` 走 composer；构造时接 `PersonaConfig`，纪律用 `core.discipline` 模块函数。
- `core/agent_steps.py`：`StepBrief` 加 `tone_hint`、`memory_context`（本刀留空）。
- `bff/main.py`：`app.state.persona`；`_send_session_ready` 接 `opening_preamble`；开场先只拼生活句。
- `bff/probe.py`：开场白改“我是 MOMO，你的学习搭子”。
- `core/scoring.py`：只加一句反馈措辞。

验收：prompt 快照、22 条开关、全关仍有纪律、评分只多一句、开场生活句+原 intro。

### Slice 1 — schema v7 + 情绪 + 表情

- 迁移前停服务、备份 `data/app-v5.db`。
- `core/db.py`：`SCHEMA_VERSION=7`、`AFFECT_SCHEMA_SQL` 四张表一次建好。
- `core/emotion.py`：衰减、夹取、0.1 取整、3×3 提示、更新提示词/解析。
- `bff/emotion.py`：scorer、800ms 超时、失败用旧状态、每用户锁。
- `bff/config.py`：`USER_ID`、`USER_ROLE`、`EMOTION_ENABLED`、`MEMORY_ENABLED`。
- `bff/main.py`：自由对话/教学/澄清回复前更新；`ready.emotion`、`session_ready.emotion`、`emotion` 事件；答题不更新。
- `web/app.js`：mood → 表情 lerp、`head`/`neck` 轻微动作、说话压到 15%、眨眼保持。
- `MEMORY_ENABLED` 在本刀期间先 `off`，等 Slice 2 完成再 `on`。

验收：衰减/夹取/解析单测；事件顺序；页面 mood→表情；`EMOTION_ENABLED=off` 中性。

### Slice 2 — 用户记忆

- `core/memory.py`：强度/半衰期/沉底/排序/渲染/解析。
- `core/memory_extraction.py`：提炼提示词、JSON schema、子串校验、诊断/进度词。
- `bff/memory_extraction.py`：finish 后异步任务、`app.state.memory_tasks`、scorer、1 次重试、`memory_runs`。
- `core/store.py`：`add_user_memory`、`user_memories(user_id)`、`update_memory_recall`、`search_user_memories`、`rebuild_user_memory_fts`、`memory_runs`。
- `bff/main.py`：单元开始读 top 3、拼开场；自由对话（含 agent）显式回忆；`StepBrief.memory_context`。
- `MEMORY_ENABLED` 完成后改回 `on`。

验收：同一天稳定、次日变化、top 3/300、沉底不主动、显式召回、异步提炼/审计、进度表不变。

### Slice 3 — 联调 + 文档

- 端到端：开始 → 开场生活+记忆 → 自由对话 tone/emotion → 结束提炼 → 下一单元记忆。
- 更新四份设计文档的冲突点（LIFE 注入面、评分一句、`user_id`、事件契约）。
- 登记 `VERSIONS.md` / `GLOSSARY.md`；归档本 change。

## 3. 迁移与回滚

- **v7 是单向门**：旧代码遇到 `user_version > 6` 会拒绝打开。迁移前备份 `data/app-v5.db`；回退代码必须恢复备份。
- 迁移只加表，不 backfill，不改进度表。
- 功能回滚用 `MEMORY_ENABLED=off` / `EMOTION_ENABLED=off`，不需要恢复 DB。
- 人设回滚：`persona.yaml` 的 entries 全关；生活池保留。
- Slice 0 不改 DB，可单独 revert。

## 4. 测试矩阵

| 层 | 测试 |
|---|---|
| composer | 顺序、空块、data 最后、预算 |
| persona | 22 条加载/开关/预算/未知键；全关仍有纪律 |
| discipline | D1-D5 面映射；评分只多一句；出题/抽取不变 |
| emotion | 衰减/夹取/取整/3×3 提示/解析 |
| emotion WS | `ready`/`session_ready`/`emotion`；答题不发；超时降级 |
| expression | Playwright：mood→表情值；说话 ≤0.15；头部不越界 |
| memory | 衰减/排序/沉底/显式召回/FTS 短词回退 |
| memory extraction | 子串校验/诊断词/进度词/去重/重试/审计 |
| integration | 开始→开场→对话→结束→下一单元；切换对话不丢状态 |
| flags | `MEMORY_ENABLED=off` / `EMOTION_ENABLED=off` 两套回归 |

## 5. 已解决的跨方案冲突

- **LIFE 注入面**：只在单元开场；`persona-settings-v0.1.md` 的自由对话 LIFE 改为后续。
- **评分提示词**：只允许新增“反馈只评价答案，不评价用户本人；不讽刺、不贬低”一句；分档、封顶、JSON 契约逐字不变；测试按这个口径断言。
- **身份键**：记忆 `user_id`，情绪 `(user_id, role)`；人设全局。
- **开场前缀**：`intro_prefix` 单字符串改成 `opening_preamble` 组合；生活句 + 记忆块 + 原 intro。
