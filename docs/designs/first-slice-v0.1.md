# 第一片实现规格 v0.1

- 状态：DRAFT v0.1（2026-11-23）
- 父设计：`docs/designs/agent-infrastructure-v0.1.md`（目标设计）
- 产品依据：`docs/designs/learning-companion-digital-human-v2.0.md`（FROZEN）
- 范围：第一片可运行切片——文本 + 点击说话、5 题、逐题评分、自动结算、mastery、同日恢复。
- 不包含：retention、教学/澄清/命令、AI 题库生成审核、诊断。
- 目的：用最小范围验证「Coach 状态机 + 评分 + 结算」是否成立，而不是一次性实现全部目标设计。

## 1. 目标

第一片 MUST 能在同一条 Coach 路径上跑通文本和语音：

```text
session_start
  -> 5 题（含次日复习）
  -> 每题答完立即评分
  -> 第 planned 题后自动结算
  -> session_result
  -> DB 可回放
```

语音链路：

```text
点击"开始说话"
  -> 浏览器能量 VAD 判停（1.5s 静音）
  -> 整段音频送 MiMo ASR
  -> 一步提交：直接评分
  -> Breeze 流式反馈 + 题目音频预合成
```

## 2. 非目标（MUST NOT 实现）

- retention（7 天抽查）、完整间隔复习。
- 教学、澄清、命令、完整四模式路由。
- AI 生成题、待审队列、抽查入库。
- 诊断场（已从产品流程移除）。
- 概念确认页、known/skipped 状态变更（第一片 fixture 全部 active）。
- 多用户、云、鉴权、打断、回声消除。
- 误解生命周期（`misconceptions` 保留但第一片不写）。
- 复杂命令确认、teach-back、评分校准 20 条 gate。

## 3. 用户流程

### 3.1 首次使用（第一片简化）

第一片不实现概念确认页；fixture 直接提供 3 个 active 概念，mastery 全 0。

```text
打开页面
  -> 服务端加载 fixture concepts + question_bank
  -> session_start(daily)
  -> 第一题
```

### 3.2 一场 daily

```text
Coach.start
  -> 选 early 题（第一片只有普通复习；最大 2 道）
  -> 选新概念（active，前置满足）
  -> 按 early 数量补新题
  -> 插入 agent_sessions(active) + session_questions
  -> 第一题 question 事件

逐题:
  文本输入 或 语音输入
  -> 答题 / 不知道 / 知道了
  -> score + 下一题
  -> 第 planned 题后自动结算

结算:
  session_score / mastery / review_due
  单事务写 sessions + concepts + session_concepts + agent_sessions
```

### 3.3 次日复习

第一片只实现“次日 / 清空”：

```text
daily 的 concept_session_score < 80 且 review_due_at 为空
  -> review_due_at = 次日

review 题的得分均值 < 80
  -> review_due_at = 次日

>= 80
  -> 清空 review_due_at / review_started_at
```

`60-79 三天`、`14 天循环` 留到目标设计的后续版本。

## 4. 架构

```text
[Web: 文本输入 / 点击说话 / 能量 VAD / 音频队列 / VRM 口型]
        |
        | WebSocket
        v
[BFF: WS 协议、ASR/TTS/Scorer 适配、音频缓存]
        |
        v
[Agent: 最小路由、agent_sessions 生命周期、事件翻译]
        |
        v
[Coach: 五题配比、评分编排、结算、mastery]
        |
        v
[Store: SQLite 唯一写入口]
```

约束：

- `core/` MUST NOT import httpx；外部调用只在 BFF。
- Agent MUST NOT 写业务规则；业务规则只在 Coach。
- BFF MUST NOT 直接写 SQL。
- 会话只读 `question_bank`（fixture 导入即 approved）。

## 5. 数据模型

第一片使用 7 张表；`misconceptions` 保留但不用；`question_candidates` 不创建。

```sql
concepts (
  id TEXT PRIMARY KEY,
  mastery INTEGER NOT NULL DEFAULT 0 CHECK (mastery BETWEEN 0 AND 5),
  status TEXT NOT NULL CHECK (status IN ('proposed','active','known','skipped','orphaned')),
  prior_status TEXT,
  last_seen TEXT,
  review_started_at TEXT,
  review_due_at TEXT
);

question_bank (
  id TEXT PRIMARY KEY,
  concept_id TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('recall','discriminate','apply')),
  question_text TEXT NOT NULL,
  rubric_json TEXT NOT NULL,
  options_json TEXT,
  answer_key TEXT,
  source_url TEXT NOT NULL,
  source_excerpt TEXT NOT NULL
);

sessions (
  id TEXT PRIMARY KEY,
  date TEXT NOT NULL,
  concept_id TEXT,
  kind TEXT NOT NULL CHECK (kind IN ('daily','review')),
  status TEXT NOT NULL CHECK (status IN ('completed','partial','unscored')),
  started_at TEXT NOT NULL,
  minutes INTEGER,
  asr_text TEXT,
  explained_text TEXT,
  input_mode TEXT NOT NULL CHECK (input_mode IN ('voice','text')),
  asr_confidence REAL,
  session_score REAL,
  created_at TEXT NOT NULL
);

session_concepts (
  session_id TEXT NOT NULL,
  concept_id TEXT NOT NULL,
  PRIMARY KEY (session_id, concept_id)
);

session_questions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id TEXT NOT NULL,
  concept_id TEXT,
  question_bank_id TEXT,
  question_role TEXT NOT NULL CHECK (question_role IN ('new','review','retention','misconception')),
  kind TEXT NOT NULL,
  question_text TEXT NOT NULL,
  rubric_json TEXT NOT NULL,
  options_json TEXT,
  answer_key TEXT,
  answer_text TEXT,
  score INTEGER CHECK (score BETWEEN 0 AND 100),
  feedback TEXT,
  misconception_id INTEGER,
  source_url TEXT NOT NULL,
  source_excerpt TEXT NOT NULL,
  created_at TEXT NOT NULL
);

agent_sessions (
  session_id TEXT PRIMARY KEY,
  kind TEXT NOT NULL CHECK (kind IN ('daily','review')),
  date TEXT NOT NULL,
  started_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('active','finished','abandoned')),
  concept_id TEXT,
  last_question_id INTEGER,
  input_mode TEXT NOT NULL DEFAULT 'text'
);

session_notes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id TEXT NOT NULL,
  question_id INTEGER,
  mode TEXT NOT NULL CHECK (mode IN ('probe','teach_back')),
  input_text TEXT NOT NULL,
  output_text TEXT NOT NULL,
  created_at TEXT NOT NULL
);
```

约束：

- `question_role=retention|misconception` 为后续预留；第一片只写 `new|review`。
- `session_notes.mode=teach_back` 为后续预留；第一片只写 `probe`。
- `sessions.kind=review` 只用于“无新概念的复习场”；第一片不做综合场/讲解场。
- `SCHEMA_VERSION` 升到 2；第一片直接重建数据库，不做数据迁移。

写边界：

1. `start`：插入 `agent_sessions(active)`；逐题插入 `session_questions` 并 commit。
2. `answer`：写 `session_questions.answer_text/score/feedback`；更新 `agent_sessions.last_question_id/input_mode/updated_at`；commit。
3. `probe`：写 `session_notes(mode=probe)`；不写答案/分数。
4. 结算：单事务写 `sessions`、`concepts`、`session_concepts`，并把 `agent_sessions.status` 置 `finished`。
5. `abandon`：启动时把 `date < today` 的 `active` 置 `abandoned`；不删除题目行。

## 6. WebSocket 协议

### 6.1 客户端 → 服务端

```json
{"type":"session_start","kind":"daily"}
{"type":"audio","session_id":"...","question_id":123,"turn_id":"...","data":"<base64>","sample_rate":16000,"mime":"audio/wav"}
{"type":"answer","session_id":"...","question_id":123,"turn_id":"...","text":"...","input_mode":"voice"|"text"}
{"type":"finish","session_id":"..."}
{"type":"ping"}
```

`audio` 用于语音；默认一步提交。`answer` 用于文本输入，以及语音的例外确认。

### 6.2 服务端 → 客户端

```json
{"type":"ready","modes":{...},"notes":[...]}
{"type":"session_ready","session_id":"...","question":{...}}
{"type":"question","id":...,"role":"new","kind":"recall","text":"...","options":null,"index":1,"total":5}
{"type":"transcript","turn_id":"...","text":"...","confidence":null,"needs_confirmation":false,"reason":null}
{"type":"score","question_id":...,"score":70,"why":"..."}
{"type":"probe","question_id":...,"text":"那你举个例子？"}
{"type":"session_result","status":"completed","session_score":78.0,"mastery":{...},"review_due_at":"2026-11-24","scores":[...]}
{"type":"audio_chunk","seq":1,"mime":"audio/mpeg","data":"<base64>"}
{"type":"warning","stage":"tts","message":"..."}
{"type":"error","stage":"asr","message":"..."}
```

### 6.3 一步提交与例外

```text
默认:
  audio -> ASR -> transcript(needs_confirmation=false)
        -> 服务端直接调用 Agent.answer -> score -> 下一题

例外:
  可疑转写 / 混合句
        -> transcript(needs_confirmation=true, reason="suspicious"|"mixed")
        -> 客户端显示转写，用户编辑/确认
        -> answer -> 评分
```

规则：

- `turn_id` 由客户端生成；`audio`、`transcript`、`answer`、`score` 必须带同一 `turn_id`。
- 可疑转写：空文本、少于 4 字、纯语气词、明显重复乱码。
- 白名单：`不知道 / 不懂 / 知道了 / 明白了 / 会了 / 不会` MUST NOT 触发可疑暂停。
- 混合句：包含疑问词且不是纯确认；命中则 `reason="mixed"`。
- 第一片不做教学；混合句的“提问部分”不回答，只保留评分路径。
- `audio_confidence` 为 `NULL`（MiMo 不返回）；字段保留。

## 7. 会话规则

### 7.1 早期题与配比

第一片没有 active 误解、没有 retention；early 队列只有普通复习。

```text
early = min(2, due_reviews 数量)

0 early: 2 recall + 2 discriminate + 1 apply
1 early: 1 early + 1 recall + 2 discriminate + 1 apply
2 early: 2 early + 1 recall + 1 discriminate + 1 apply
```

- 新概念首日拿 3-5 道新题；`question_bank` fixture 每概念 6-7 道，剩余留后续。
- `question` 事件的 `total` = 本场计划题数（planned）。
- 无新概念可出时，允许 review-only 场：`kind=review`，planned = early 数量。

### 7.2 自动结算

```text
planned = start 时插入的 session_questions 行数
自动结算条件：已评分题数 == planned，或没有未作答题
提前结束：finish -> partial
```

不按固定 5；retention/review 场按各自 planned。

### 7.3 评分

- 辨析题：本地按 `answer_key` 判分（正确 100，错误 40）。
- 开放题：调用 Scorer（DeepSeek）；失败重试一次；仍失败该题 `score=NULL`，`feedback="本题未评分"`，会话继续。
- 每题评分后立即 commit；mastery/review_due 在结算时更新。
- Scorer 返回的 `session_misconception` 第一片忽略。

### 7.4 状态与 mastery

```text
session_score = 已评分题均值
completed: 所有 planned 题都作答且已评分
partial:   至少 1 题评分，但不足 planned 或有未评分题
unscored:  一题都没评上

mastery = round(最近三次 completed daily 的 role=new 均值 / 20)
partial daily 不计
```

第一片没有 retention；高分概念不会再次复习，这是已知限制。

### 7.5 “不知道”

```text
用户说/点"不知道"
  -> 答题模式，score=0
  -> 反馈：一句短定义 + 一个例子（<=60 字）
  -> 下一题
```

短定义来自当前概念的 `plain_def` + `source_excerpt`，不调用 LLM，不占教学预算。

### 7.6 “知道了”

```text
用户说"知道了/懂了/明白了/会了"（纯确认）
  -> 不评分、不推进
  -> LLM 生成 1 个追问（题目 + 用户回答 + rubric；不读 answer_key）
  -> probe 事件；用户再答 -> 评分
  -> 同题最多 1 次 probe
  -> 第二次仍是纯确认 -> 该题记未作答，下一题
```

- 追问失败 -> 模板“能举个例子吗？”。
- probe 记录写 `session_notes(mode=probe)`；不写答案/分数。
- 第一片没有教学，因此没有 teach-back。

### 7.7 同日恢复

```text
session_resume（同日 active）
  -> 返回第一道未作答题
  -> 没有未作答题 -> 自动结算
跨日 / 非 active -> session_expired，开新会话
```

## 8. 语音与音频

### 8.1 收音

- 浏览器端能量 VAD；不依赖服务端 VAD。
- 点击“开始说话”后采集；短停不切；1.5s 静音或点“结束作答”提交。
- 半双工：它说话时麦克风关闭；不打断、不做回声消除。
- 一次录音对应一个 `audio` 消息；MiMo 整段识别，无 partial。

### 8.2 TTS 与缓存

- 反馈：Breeze `stream()`，逐块推 `audio_chunk(seq)`；前端按 seq 排队播放。
- 题目：会话开始时第一题同步合成，其余后台预合成；缓存 key = hash(text + voice + model + format)。
- 缓存目录：`data/audio_cache/`（不进 git）；失败或未命中 -> 实时合成。
- 前端口型跟音频幅度；不追求音素级。

## 9. 失败与降级

| 故障 | 处理 |
|---|---|
| ASR 超时/5xx | 前端提示切文字；`input_mode=text`；会话继续 |
| 可疑转写 | 暂停，显示转写让用户确认/编辑 |
| 混合句 | 暂停，显示转写；用户选择整句评分或改一下再评 |
| Scorer 单题失败 | 重试一次；仍失败该题未评分，继续 |
| Scorer 全部失败 | 整场 `unscored`，答案保留 |
| TTS 失败 | 只显示文字；不阻塞答题 |
| probe LLM 失败 | 退回模板追问 |
| SQLite 结算失败 | 事务回滚；会话保持未结算，可重试 |
| 题目音频缓存失败 | 实时合成；不阻塞 |

## 10. 测试策略

### 10.1 注入

- `Clock`：注入 `today` / `now`，测次日复习、mastery、resume。
- `ScriptedScorer`：按题号返回分数 / 坏 JSON / 异常。
- `FakeASR`：按脚本返回文本；无 confidence。
- `FakeLLM`：返回 probe 文本或异常。
- `FakeTTS`：返回固定音频字节；支持 stream。

### 10.2 必测

| 行为 | 测试 |
|---|---|
| 五题配比 0/1/2 early | `tests/test_ratios.py` |
| 辨析题本地判分 | `tests/test_scoring.py` |
| 开放题评分成功/重试/失败 | `tests/test_scoring.py` |
| 单题失败 -> 未评分，continue | `tests/test_coach_flow.py` |
| 结算事务 / 幂等 | `tests/test_settlement.py` |
| partial / unscored | `tests/test_settlement.py` |
| mastery 最近三次 completed daily | `tests/test_mastery.py` |
| partial daily 不计 mastery | `tests/test_mastery.py` |
| 次日复习入队/清空 | `tests/test_review.py` |
| 不知道 -> 0 | `tests/test_router.py` |
| 知道了 -> 一次 probe；第二次未作答 | `tests/test_router.py` |
| probe 失败 -> 模板 | `tests/test_router.py` |
| 同日 resume / 跨日 abandoned | `tests/test_agent_sessions.py` |
| 文本 5 题 -> 自动结算 | `tests/test_ws.py` |
| 语音一步提交 / 可疑暂停 / 混合暂停 | `tests/test_ws.py` |
| 题目缓存命中/未命中 | `tests/test_tts_cache.py` |
| audio_chunk 顺序 | `tests/test_ws.py` |

### 10.3 VAD

- 把能量判定与静音计时抽成纯函数；用合成 PCM 测：
  - 静音不触发；
  - 说话后 1.5s 静音触发；
  - 短停不触发；
  - 手动结束优先。
- 真实麦克风做一次烟雾测试；不在 pytest 里模拟浏览器麦克风。

### 10.4 手工烟雾

1. 文本答 5 题 -> 自动结算 -> 验收卡。
2. 语音走同一路径 -> 同一结果。
3. 说“不知道” -> 0 分 + 短定义。
4. 说“知道了” -> 追问一次 -> 再答。
5. 说“知道了”两次 -> 该题未作答，下一题。
6. 断开重连 -> 同日回到未答题。

## 11. 实现顺序与估算

| 顺序 | 任务 | 依赖 |
|---|---|---|
| 1 | schema v2 + Store + fixture（3 概念 x 6-7 题） | — |
| 2 | Clock / scripted scorer / fake ASR/LLM/TTS + Coach 单测 | 1 |
| 3 | Coach：start / answer / finish；配比、评分、结算、mastery | 2 |
| 4 | Agent + 最小路由（答题/不知道/知道了 + probe） | 3 |
| 5 | BFF WS：文本路径 + TestClient E2E | 4 |
| 6 | TTS 流式 + 题目预合成 + audio_chunk | 5 |
| 7 | 语音：能量 VAD + 一步提交 + 可疑/混合例外 | 6 |
| 8 | 真实 provider 烟雾 + 10 条评分校准（独立 gate） | 7 |

估算：14-18 小时（不含 10 条校准后的提示词迭代）。比原 v0 大，因为 VAD、流式 TTS、probe、测试注入都进了第一片。

## 12. 验收清单

- [ ] 文本 5 题 -> 自动结算 -> `session_result`；DB 可回放。
- [ ] 语音走同一路径 -> 同一结果。
- [ ] 0/1/2 early 三种配比正确；planned = 实际插入题数。
- [ ] 单题评分失败 -> 该题未评分，会话继续；零评分 -> `unscored`。
- [ ] partial 不计 mastery；mastery 取最近三次 completed daily。
- [ ] 次日复习入队/清空正确。
- [ ] “不知道” -> 0；“知道了” -> 一次 probe；第二次 -> 未作答。
- [ ] 可疑转写/混合句暂停确认；普通语音一步提交。
- [ ] 同日 resume 回到未答题；跨日 `session_expired`。
- [ ] 题目音频缓存命中/未命中；`audio_chunk` 顺序正确。
- [ ] 无 retention / 教学 / 命令 / AI 题库生成路径。

## 13. 假设与开放问题

1. **VAD 参数**：能量阈值、1.5s 静音、最短语音 200ms 都是占位值，需真实麦克风校准。
2. **可疑转写启发式**：空/极短/纯语气词/乱码；规则可能误判，第一片接受。
3. **混合句检测**：靠疑问词与位置，不依赖标点；覆盖有限。
4. **ASR 置信度**：MiMo 返回 NULL；`asr_confidence` 字段保留，第一片不用。
5. **评分校准**：10 条人工对照的数据从真实会话或手写 fixture 来；未校准前分数只作流程验证。
6. **隐私与成本**：音频发 MiMo、答案发 DeepSeek、TTS 发 Breeze；调用量与费用未估算。
7. **混合句的提问部分**：第一片不回答（无教学），只保留评分；用户可在后续版本再问。
8. **fixture 内容**：3 个概念的题目、rubric、出处需要人工写；真实内容归知识库。
9. **数据库**：第一片直接重建 schema v2；无迁移。
10. **高分不复习**：retention 不在第一片；高分概念第一片不会再次出现，这是已知限制。

## 14. 与目标设计的关系

- 本规格是 `agent-infrastructure-v0.1.md` 的子集；目标设计里的 retention、教学、题库审核、完整路由不在第一片。
- 第一片跑通后，按目标设计逐层加：retention -> 教学/澄清/命令 -> 题库生成审核 -> 完整四模式路由。
- 本规格不修改 `v2.0` 冻结正文；若后续实现需要改变冻结规则，按 `FREEZE.md` 记录。
