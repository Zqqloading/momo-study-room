# Design: 数字人用户长期记忆（User Memory）

Date: 2026-11-26
Branch: feature-mood
Status: IMPLEMENTED v0.1（2026-11-26 Slice 2）
Related: `learning-companion-digital-human-v2.0.md`、`learning-unit-v0.1.md`、`persona-settings-v0.1.md`、`free-talk`、`coach-session`

## Problem Statement

现在的掌握度、薄弱知识点、复习时间都在学习进度里，回答“学得怎么样”。但 MOMO 不记得“用户是什么样的人”：用户说过什么、偏好怎么学、当下是什么感受。需要加一层独立的「关于用户」的长期记忆，和进度分离，有温度、有遗忘、可被主动唤起。

## Goals

- 只记三样：用户原话、偏好、感受。
- 三类记忆分三档温度；每条一句提炼过的话，不存诊断性结论。
- 写入：学习单元结束时异步提炼，≤5 条。
- 读取：单元开始时取最多 3 条、≤300 字，放进开场。
- 半衰期 14 天；越久越难想起；被回忆时半衰期 ±50% 波动。
- 沉底不删除，不主动唤醒；用户强烈帮助时可以唤起。
- SQLite + 全文索引，分词沿用现有 FTS5 trigram。

## Non-Goals

- 不把掌握度、分数、错题、薄弱知识点搬进记忆；它们继续留在 `concepts` / `sessions` / `session_questions`。
- 不存诊断性结论（性格、能力、智力、心理状态、家庭/健康）。
- 不做记忆编辑 UI、记忆列表页、手动删除 API。
- 不做向量检索；本期只用 FTS5。
- 不做跨用户记忆；仍是单用户。
- 不做自由对话的自动记忆写入；自由对话只在用户明确要求回忆时读取。
- 不改评分、出题、知识检索的提示词。
- 不把人设设定集和用户记忆混在一张表或一个 YAML 里。

## 现状与边界

### 进度仍然在原位

| 数据 | 位置 | 本设计动不动 |
|---|---|---|
| 掌握度 | `concepts.mastery` | 不动 |
| 复习时间 | `concepts.review_due_at` | 不动 |
| 每题分数/反馈 | `session_questions.score/feedback` | 不动 |
| 误解 | `misconceptions` | 不动 |
| 最近会话 | `sessions` / `agent_sessions` | 不动 |

用户记忆是一张新表，不读写这些字段。记忆提炼也不允许把分数、掌握度、错题写进记忆。

### 单元开始/结束的现有落点

- 开始：`bff/main.py:612` 调 `agent.start()`，`_send_session_ready`（`:402`）发 `session_ready`，`intro` 同时走 TTS。
- 结束：`bff/main.py:691` 的 `finish` 调 `agent.finish()`，`Coach.finish` 结算，随后发 `session_result`。
- 记忆读取在 `_send_session_ready` 前拼到 `intro`；记忆提炼在 `session_result` 之后异步跑。

### 现有全文索引

`chunk_fts` / `hot_fts` 都用：

```sql
tokenize='trigram'
```

查询侧复用 `core/store.py` 的 `_fts_match()`（按空白切词、加引号、OR）和 `_short_terms()`（少于 3 字的中文词走子串回退）。用户记忆的 FTS 沿用同一套，不引入新分词器。

### 现有 schema

`core/db.py` 的 `SCHEMA_VERSION = 7`。v7 一次迁移建 `emotion_states`、`user_memories`、`user_memories_fts`、`memory_runs`；只新增表，不改旧表；`init_schema()` 继续用 `CREATE TABLE IF NOT EXISTS`，老库原地升级。

### 会话里哪些用户原话能拿到

- `session_questions.answer_text`：逐题作答，已落库。
- `session_notes`：`probe` / `teach_back` 的 `input_text`，已落库。
- 会话内 `teach` / `clarify` 的对话只在 `bff/main.py` 的 `teach_state` 内存里，不落库，本期不进记忆提炼。

这条边界会直接影响提炼质量：如果用户只在“讲讲/这题什么意思”里说了偏好，本期记不到。开放问题里留了“要不要把 teach 消息落库”。

## 记忆模型

### 三类、三档温度

| kind | 中文 | 温度 | 初始强度 | 典型内容 |
|---|---|---|---|---|
| `quote` | 原话 | 热 | 1.0 | 用户自己说的一句有信息量的话，尽量保留原措辞 |
| `preference` | 偏好 | 温 | 0.75 | 稳定的喜好、习惯、学习方式 |
| `feeling` | 感受 | 冷 | 0.5 | 当下对题目/内容/难度的情绪或体感 |

按用户列的顺序，原话最热、偏好次之、感受最冷。如果实际使用中觉得感受应该更重，只改 `initial_strength`，不改结构。

### 一条记忆的字段

| 字段 | 含义 |
|---|---|
| `text` | 一句提炼过的话，≤100 字；中性、无主语，供提示词和开场直接用 |
| `source_quote` | 用户原话的逐字摘录，≤200 字；用于校验和 `quote` 展示 |
| `kind` | `quote` / `preference` / `feeling` |
| `source_session_id` | 来自哪场学习单元 |
| `source_question_id` | 可空；来自哪道题 |
| `strength` | 上次回忆时的强度；新建时按 kind 取 1.0 / 0.75 / 0.5 |
| `half_life_days` | 当前半衰期；新建 14.0，每次回忆重抽 14×U(0.5,1.5) |
| `last_recalled_at` | 上次被回忆的时间 |
| `recall_count` | 被回忆次数 |
| `created_at` | 写入时间 |

`text` 用中性、无主语的写法，例如：

- ✅ `更习惯先看例子，再看定义`
- ✅ `听到大段定义会有点烦`
- ❌ `我是一个抽象思维很差的人`
- ❌ `用户有数学焦虑`

这样开场可以说“你之前提过：更习惯先看例子”，系统提示可以说“关于用户：更习惯先看例子”，不会出现“我”指代错位。

`quote` 的 `text` 可以是原话的压缩；`source_quote` 保留逐字原话。开场时若 `source_quote` ≤60 字，直接用原话；否则用 `text` 的压缩版。

### 强度衰减

```text
age_days = max(0, (now - last_recalled_at) / 1 天)
current  = strength * 0.5 ** (age_days / half_life_days)
```

- 新建时 `last_recalled_at = created_at`，所以 `current = 初始强度`。
- 半衰期 14 天：14 天后强度减半；28 天后剩 1/4。
- 越久没被想起，`current` 越低；排序时自然靠后。

### 沉底

```text
current < 0.05  →  沉底
```

按 14 天半衰期估算：

- 原话（1.0）：约 61 天沉底。
- 偏好（0.75）：约 55 天沉底。
- 感受（0.5）：约 46 天沉底。

沉底不是删除，也不是状态列；每次读取时按公式算出来。

### 被回忆时的半衰期波动

被回忆时：

```text
current_strength = 按旧 half_life_days 算出的当前强度
strength         = current_strength          # 保留衰减，不重置为初始值
half_life_days   = 14.0 * uniform(0.5, 1.5)  # 7 到 21 天
last_recalled_at = now
recall_count    += 1
```

关键点：**回忆只改半衰期，不重置强度。** 如果每次想起都满血，记忆永远不会沉底，和“越久越难被想起来”矛盾。半衰期每次独立重抽，不在上一次的值上累积，避免随机游走越走越远。

“用户强烈帮助回忆”是唯一的例外：

```text
strength = max(current_strength, 0.1)   # 唤醒下限
```

把沉底的记忆拉回 0.1，让它有机会重新进入主动读取；不拉回初始值，避免一次提起就永久占位。

### 一个例子

```text
第 0 天写入原话：strength=1.0，half_life=14
第 14 天：current=0.50；被开场选中
  → strength=0.50，half_life 重抽为 19.3，last_recalled=第 14 天
第 28 天：current=0.50 * 0.5^(14/19.3)=0.302
第 42 天：current=0.302 * 0.5^(14/19.3)=0.183
...
```

## 写入路径

### 时机

- 学习单元结束（`completed` 或 `partial`）后，异步提炼。
- `unscored` 或没有任何实质用户文本时跳过，记 `empty`。
- 不阻塞 `session_result`；用户在结算页看到结果时，提炼在后台跑。
- 任务挂在服务端后台任务集合，不挂在单条 WebSocket 连接上；用户关页面也继续跑。

### 输入

只送用户自己说过的话：

- `session_questions` 的 `answer_text`；排除空、`不知道`、少于 4 字的短答。
- `session_notes` 的 `input_text`（`probe` / `teach_back`）。
- 题目文本可以作为上下文一起送，但明确标注“题目不是用户原话”，`source_quote` 只能来自用户文本。
- 不送 assistant 的反馈、`why`、分数、掌握度。

### 提炼提示词（草案）

```text
你是用户记忆提炼器。只从本轮学习单元里用户自己说过的话提炼，最多 5 条。

允许三类：
- quote 原话：用户自己说的一句有信息量的话，尽量保留原措辞。
- preference 偏好：稳定的喜好、习惯、学习方式。
- feeling 感受：当下对题目、内容或难度的情绪或体感。

每条规则：
- text 写一句提炼过的话，≤100 字，用中性、无主语的写法；
  不要写“用户是……的人”。
- source_quote 逐字引用用户原话中的一个片段，≤200 字；
  必须是用户原话的子串，不得改写。
- 只记录用户明确说过的内容；不推断性格、能力、智力、心理状态、家庭或健康。
- 不记录分数、掌握度、错题、薄弱知识点；这些留在学习进度。
- 不记录姓名、住址、联系方式等可识别身份的信息。
- 没有足够依据就返回空列表，不要凑数。

只返回 JSON：
{"memories":[{"kind":"quote|preference|feeling","text":"...","source_quote":"..."}]}
```

### 解析与校验

复用 `core/scoring.py` 的 `extract_json_object()` 处理围栏和前后废话。

逐条校验：

| 检查 | 处理 |
|---|---|
| `memories` 不是列表 | 整批失败 |
| 条数 >5 | 按原顺序取前 5 条 |
| `kind` 不在三类 | 丢弃该条 |
| `text` 空或 >100 字 | 丢弃该条 |
| `source_quote` 空或 >200 字 | 丢弃该条 |
| `source_quote` 不是用户文本的逐字子串（空白归一化后） | 丢弃该条 |
| `text` 命中诊断词（性格/智力/能力/焦虑/抑郁/自卑/基础差/不擅长/心理/家庭/病史） | 丢弃该条并记 warning |
| `text` 命中进度词（掌握度/分数/mastery/错题/薄弱/第 N 题） | 丢弃该条并记 warning |
| 同批 `text` 重复 | 保留第一条 |

`source_quote` 的子串校验是最硬的一道门：它保证每条记忆都能回到用户说过的话，模型不能凭印象写“用户不擅长 X”。

### 去重

- 归一化 `text`：去首尾空白、压缩连续空白、去掉句末标点。
- 已有相同 `kind` + 归一化 `text`：不新增，按“显式回忆”更新已有记忆——`strength = max(current, 0.1)`、半衰期重抽、`last_recalled_at = now`、`recall_count += 1`。
- 近似重复（换一种说法）本期不合并；记在开放问题。

### 异步与失败

- 用 `asyncio.create_task`；任务放在 `app.state.memory_tasks`，不跟 WebSocket 连接生命周期绑定。
- LLM 或解析失败重试 1 次；仍失败记 `memory_runs.status='failed'`，打日志，不弹用户错误。
- 不在 `await` 期间持有数据库事务；LLM 返回后一次性短事务写入。
- 提炼模型复用 `providers.scorer`（DeepSeek Flash，JSON 输出）；如果质量不够，再换 `providers.llm`。

### 审计表

`memory_runs` 只做审计，不参与读取：

```sql
CREATE TABLE IF NOT EXISTS memory_runs (
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

## 读取路径 A：单元开始

### 取哪 3 条

```text
加载所有记忆 → 算 current → 过滤 current >= 0.05
→ 按 current 降序、last_recalled_at 升序、id 升序
→ 依次 render，直到 3 条或渲染后 >300 字
```

- 不按当前概念做相关性排序；这是“最应该想起来”，不是“最相关”。
- 同分时优先更久没被想起的那条，避免老面孔一直占位。
- 300 字是**记忆块渲染后的总长**，含“你说过/你提过”和分隔符；不含原有 `intro`。

### 渲染

| kind | 渲染 |
|---|---|
| `quote` | `source_quote` ≤60 字：`你说过“{source_quote}”`；否则 `你说过{text}` |
| `preference` | `你提过{text}` |
| `feeling` | `你说过{text}` |

拼成：

```text
先想起几件你说过的事：{r1}；{r2}；{r3}。
{原有 intro}
```

例：

```text
先想起几件你说过的事：你说过“我先看例子再看定义”；你提过听到大段定义会有点烦。今天从「agent loop」开始。
```

### 更新回忆

选中的每条按“被回忆”公式更新：`strength = current`、`half_life_days = 14×U(0.5,1.5)`、`last_recalled_at = now`、`recall_count += 1`。选择和更新在同一个短事务里完成。

### 接线

- `_send_session_ready` 接组合后的 `opening_preamble`（生活句 → 记忆块）；`event["intro"]` 和 TTS 都用 `preamble + started.intro`。
- 记忆块最多 300 字；生活句 + 记忆块合计 ≤360 字；放不下就少放记忆条目。
- 读取失败或没有合格记忆：不加记忆块，原 `intro` 不变。
- 只在单元开始（`session_ready`）注入；`session_resume` 不重复开场。
- 复习单元和每日单元都适用。

## 读取路径 B：用户主动唤起

### 触发

轻量意图检测，不调模型。命中以下说法之一，并且去掉说法后还剩至少 2 个字的内容线索：

- `还记得`
- `记不记得`
- `之前说过`
- `我以前说`
- `帮我回忆`
- `想想我之前`
- `我说过什么`

只有“你还记得吗”而没有内容线索，不触发特殊读取；按普通对话处理，不主动注入记忆。

### 检索

- 用内容线索查 `user_memories_fts`（`text` + `source_quote`）。
- `MATCH` 复用 `_fts_match()`；trigram 命中不了 2 字词，因此 FTS 无命中时把线索切成 2 字片段，用 `instr` 子串计分回退。仍然只用 SQLite，不引入向量或模型。
- 排序：`bm25` 升序（回退时按命中 2 字片段数降序），再按 `current` 降序；取前 3。
- **包含沉底记忆**；这是“用户强烈帮助”的唯一入口。
- 没有命中：返回空记忆；服务端注入“（没有找到相关记忆）”，让模型直接说没印象，不编造（D1）。

### 注入

```text
【用户要求回忆】
用户问你是否记得以下内容。只依据这些记忆回答；没有就说没印象，不要编造。
- {text}
- {text}
```

- 放在 PERSONA 之后、TASK/CONTEXT 之前。
- 不写回新记忆；只更新被选中记忆的回忆字段（唤醒公式 `max(current, 0.1)`）。
- 本期只接自由对话（含 agent 自由对话）：非 agent 路径直接拼提示词；agent 自由对话给 `StepBrief` 加可选 `memory_context`；会话内 `teach` / `clarify` 留到后续。

## 存储

### schema v7

```sql
CREATE TABLE IF NOT EXISTS user_memories (
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

CREATE VIRTUAL TABLE IF NOT EXISTS user_memories_fts USING fts5(
  memory_id UNINDEXED,
  text,
  source_quote,
  tokenize='trigram'
);

-- memory_runs 表见「审计表」一节（v7 也带 user_id）。

CREATE INDEX IF NOT EXISTS idx_user_memories_last_recalled
  ON user_memories(last_recalled_at);
CREATE INDEX IF NOT EXISTS idx_user_memories_kind
  ON user_memories(kind);
CREATE INDEX IF NOT EXISTS idx_memory_runs_session
  ON memory_runs(session_id);
```

- `SCHEMA_VERSION = 7`；记忆四表与情绪表同一次迁移建好。
- 只新增表，不改旧表；v6 数据库原地升级。
- FTS 同步用显式 insert/delete，和 `chunk_fts` / `hot_fts` 一致；不建触发器。
- `strength` 是“上次回忆时”的强度，不是永久初始值。
- 不存 `status`；沉底是算出来的。
- 记忆按 `user_id` 隔离；情绪按 `(user_id, role)`；人设全局。
- 不存 embedding。

### Store 方法

- `add_user_memory(... user_id ...) -> int`：写 `user_memories` + `user_memories_fts`，同一事务。
- `user_memories(user_id) -> list[dict]`：读取该用户全部记忆，供排序。
- `update_memory_recall(memory_id, strength, half_life_days, last_recalled_at, recall_count)`。
- `search_user_memories(user_id, query, limit)`：FTS + 2 字子串回退 + 强度排序。
- `rebuild_user_memory_fts()`：维护用，和 `rebuild_hot_fts()` 同型。
- `user_texts_for_session(session_id)`：作答 + probe/teach_back 笔记，过滤短答/不知道/重复。
- `start_memory_run` / `finish_memory_run` / `memory_run_for_session`：审计。

## 和进度、设定集的关系

| 层 | 内容 | 存储 | 谁写 |
|---|---|---|---|
| 学习进度 | 掌握度、复习、分数、误解 | `concepts` / `sessions` / `session_questions` | Coach / 评分 |
| 用户记忆 | 原话、偏好、感受 | `user_memories` | 单元结束提炼 |
| 人设设定集 | MOMO 是谁、怎么说、不说什么 | `persona.yaml` | 用户手改 |

三张皮，不混：

- 记忆不是进度：不写分数、掌握度、错题。
- 记忆不是人设：不进 `persona.yaml`，不受人设条目开关控制。
- 人设的生活素材池不是用户记忆：那是 MOMO 自己的“今天的小事”，不是用户说过的话。

## 提示词合并顺序

记忆进入提示词时，统一放在人设之后、任务之前：

```text
ROLE → PERSONA → TONE → MEMORY → TASK → CONTEXT → DISCIPLINE → DATA
```

- `MEMORY` 是背景，不是硬事实；和当前材料冲突时以当前材料为准。
- 开场不走系统提示词，直接拼在 `intro` 前面。
- 显式回忆块放 `MEMORY` 位置，标明“只依据这些记忆回答；没有就说没印象”。

## 决策记录

| ID | 决策 | 理由 |
|---|---|---|
| UM-01 | 三类/三档：quote 1.0、preference 0.75、feeling 0.5；基础半衰期统一 14 天 | 按用户列的顺序定强弱；结构简单，数值可调 |
| UM-02 | 指数衰减；回忆保留强度、只重抽半衰期 14×U(0.5,1.5)；沉底 <0.05；显式唤醒下限 0.1 | 回忆不重置强度，否则记忆永不沉底；半衰期独立重抽避免随机游走 |
| UM-03 | 单元结束异步提炼，≤5 条；只送用户文本；输入 = 作答 + probe/teach_back 笔记 | 不阻塞结算；assistant 反馈不进记忆；teach 目前不落库 |
| UM-04 | 单元开始取最多 3 条、渲染后 ≤300 字、拼在 `intro` 前 | 和现有 TTS/开场链路兼容，不加模型调用 |
| UM-05 | 显式回忆 = 意图词 + 内容线索 + FTS；FTS 无命中时 2 字子串回退；包含沉底；无命中注入“没有找到相关记忆”；本期只接自由对话 | “强烈帮助”需要一个确定入口；trigram 命中不了 2 字词，验收例子需要回退 |
| UM-06 | schema v7；`user_memories` + `user_memories_fts`（trigram）+ `memory_runs`；不动旧表 | 只加表，老库原地升级；FTS 沿用现有方式 |
| UM-07 | `text` 中性无主语；`source_quote` 逐字；子串校验 + 诊断/进度词黑名单 | 每条记忆可回到用户原话；不存诊断结论 |
| UM-08 | 重复写入按 `kind + 归一化 text` 合并，按显式回忆更新 | 重复偏好不堆行；近似重复留后续 |
| UM-09 | 提炼复用 `providers.scorer`；JSON；失败重试 1 次；审计表记录 | 和评分/抽取的 JSON 路径一致；异步失败可查 |
| UM-10 | 不做记忆 UI、编辑、删除 API；不做向量检索 | 本期先跑通写入/读取/衰减；保持小 |
| UM-11 | `memory_runs` 只审计，不进读取 | 异步失败容易静默；留一条可查记录 |
| UM-12 | 自由对话不自动写记忆；只在显式回忆时读 | 写入时机严格限定在单元结束，避免把闲聊噪音记成事实 |

## 开放问题

1. **温度顺序**：现在按“原话最热、偏好次之、感受最冷”。如果你觉得感受应该更重，改 `initial_strength` 即可。
2. **数值**：初始 1.0/0.75/0.5、沉底 0.05、唤醒下限 0.1、14 天半衰期，都是第一版估计；真实用两周后再调。
3. **teach/clarify 进不进记忆**：现在不落库，所以提炼不到。如果要，需要把 `teach_state` 的消息写入 `session_notes`（新 mode 或新表），这是另一刀。
4. **显式回忆要不要进会话内 teach/clarify**：本期只接自由对话；接会话内需要给 `StepBrief` 加 `memory_context`。
5. **近似重复**：本期只合并完全相同 `text`；换一种说法的同一偏好会变成两条，后续再做语义合并。
6. **300 字口径**：已同时限制记忆块 ≤300、生活句 + 记忆块 ≤360；生活句存在时记忆块自动缩到剩余预算。
7. **提炼模型**：现在复用 scorer（DeepSeek Flash）；如果觉得提炼太浅，换 `providers.llm`。
8. **记忆查看/删除**：本期没有 UI；如果发现记错，只能 SQL 处理。要不要下一刀加一个只读列表 + 删除？

## 验收

### 自动化

- 衰减：每个 kind 在第 0/7/14/28 天的 `current` 符合公式。
- 回忆：`strength` 保留当前值；`half_life_days` 落在 [7,21]；`last_recalled_at`/`recall_count` 更新。
- 沉底：`current < 0.05` 不进主动排序；显式回忆能返回；唤醒后 `strength >= 0.1`。
- 开场：最多 3 条；渲染后 ≤300 字；无记忆时 `intro` 不变；`quote` 长于 60 字时用 `text`。
- 检索：trigram 命中；<3 字走子串回退；bm25 + 强度排序；无命中返回空。
- 解析：缺字段、坏 kind、text >100、source_quote 非子串、诊断词、进度词、>5 条、同批重复，逐条断言。
- 去重：同 kind + 同 text 不新增，按显式回忆更新。
- 异步：finish 后任务启动；失败重试 1 次；`memory_runs` 状态正确；不阻塞 `session_result`。
- 隔离：`user_memories` 不出现分数/掌握度；评分/出题/检索提示词逐字不变。

### 真实模型验收

1. 完成一个单元，用户明显说过“我更喜欢先看例子”；下一个单元开场出现这条偏好。
2. 单元结束时没有值得记的话 → 不写记忆，`memory_runs.status='empty'`。
3. 问“你还记得我之前说过喜欢怎么学吗” → 能返回那条偏好；没有就说没印象。
4. 把一条记忆的时间拨到 70 天后 → 不再出现在主动开场；用具体线索问 → 能唤起。
5. 检查 `user_memories.text/source_quote`：没有分数、掌握度、错题、性格/能力诊断。
6. 开场 TTS 念记忆块不生硬，不超过 300 字。

## Next Steps

Slice 2 已落地：

1. `core/db.py`：schema v7 已包含记忆四表与索引。
2. `core/store.py`：写入、读取、回忆更新、FTS + 2 字回退、审计、用户文本。
3. `core/memory.py`：强度/半衰期/沉底/排序/渲染/开场拼接/线索提取。
4. `core/memory_extraction.py`：提炼提示词 + JSON 校验。
5. `bff/memory_extraction.py`：结算后异步提炼、一次重试、`memory_runs`。
6. `bff/memory.py`：开场 top 3 + 显式回忆。
7. `bff/main.py`：开场拼记忆、自由对话回忆、`app.state.memory_tasks`。

剩余：真实模型跑一条“单元结束 → 提炼 → 下一单元开场”的 smoke；按真实语料调温度/半衰期/线索填充词。
