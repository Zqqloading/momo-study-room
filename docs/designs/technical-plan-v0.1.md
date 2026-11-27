# 技术方案 v0.1 —— 数字人学习伴侣

- 状态：DRAFT v0.1（2026-11-23 同步交互链路、逐题评分与自动结束）
- 对应设计：`docs/designs/learning-companion-digital-human-v2.0.md`（FROZEN 2026-11-23）
- 基线：v1.0 FROZEN + 2026-11-21 `/plan-eng-review` 决策 D3-D8
- 覆盖范围：v0 写到模块、接口、表结构与测试映射；v1/v2 只写边界、依赖与验收门槛
- 版本管理：`docs/designs/VERSIONS.md`

## 1. 目标与非目标

**v0 目标**：在 d0 语音闭环之上接教练内核。材料与概念由你手工放进 `concepts.yaml`，题库预写并导入 SQLite；每天一场会话，复习优先，五道题，评分、掌握度、复习入队全部落库。

**v0 非目标**：材料自动解析与切块、检索与 embedding、PDF、题目预生成、误解重问、完整间隔复习、综合场。这些属于 v1/v2，接口预留但不实现。

## 2. 现状

- d0 已实现：`bff/main.py` 的 WebSocket 与 provider 编排、`core/ports.py` 的四个协议、`web/app.js` 的 VRM 与半双工录音，63 个 pytest 测试。
- 三个外部 API 已确认（MiMo LLM / MiMo ASR / Breeze TTS，2026-11-22 实测连通）；DeepSeek Flash 仍未提供。
- 已有 SQLite schema、Store、YAML 加载、Planner 与评分解析；尚无 Coach、Tutor、题库种子与 v0 会话协议。

## 3. 架构总览

```
Web (VRM + push-to-talk + question UI)
        |
        | WebSocket
        v
BFF bff/main.py
  ├─ 传输协议翻译（audio/text/session_start/answer/finish）
  ├─ 外部 API 调用：ASR / LLM / TTS / Scorer 适配器
  └─ 静态资源：web/ 与 assets/
        |
        v
Core core/coach.py  <- 唯一会话入口（D7）
  ├─ Planner.next_concept()      选概念与复习优先级
  ├─ Tutor.ask() / feedback()    单题问法与反馈文本
  ├─ Scorer（core/scoring.py）   契约解析 + 本地辨析判分
  └─ Store（core/store.py）      SQLite 读写
        |
        +-- SQLite data/app.db
        +-- concepts.yaml（内容真相源，只读）
        +-- seeds/question_bank.json（题库种子）

外部 API 只由 BFF 调用；core 不 import httpx。

两层边界（2026-11-23 / P2）：
- 会话层（慢回路）：Coach/Planner/Tutor/Scorer/Store 拥有议程、五题配比、评分与结算；跨题、跨天。
- 实时语音层（快回路）：浏览器 VAD 切句/判停 → ASR → `answer.text`；题目/反馈文本 → TTS → `audio_chunk`；只负责传输。
- 两层只通过 WebSocket 事件交界；`core/` 不接触音频。联网只做材料入口或超纲兜底，不进每轮作答热路径。
```

约束：
- BFF 不实现复习优先、五题配比、结算顺序；这些只在 `core/coach.py`。
- YAML 是概念内容唯一真相源；SQLite 只存运行时状态与会话。
- 所有外部失败在 BFF 转成 `ProviderError`，Coach 决定降级，不让异常穿透到 WebSocket 循环。

## 4. 模块与职责

| 模块 | 职责 | v0 是否新建 |
|---|---|---|
| `bff/main.py` | WebSocket、静态资源、消息翻译、调用 Coach 与 provider | 改 |
| `bff/config.py` | 四 provider 配置、路径、超时 | 已有 |
| `bff/providers/*` | ASR/LLM/TTS/Scorer 适配器（真实 + fake） | 已有 |
| `bff/session.py` | 传输层对话历史（不写库） | 已有 |
| `core/coach.py` | 会话状态机、五题配比、mastery、review_due、结算事务 | 新建 |
| `core/planner.py` | 候选池、前置检查、优先级排序 | 新建 |
| `core/tutor.py` | 单题问法、评分后的反馈文本 | 新建 |
| `core/scoring.py` | 评分 JSON 契约解析、辨析题本地判分 | 已有，扩展 |
| `core/store.py` | SQLite 读写：会话、题目、概念状态、误解 | 新建 |
| `core/db.py` | schema 与迁移 | 新建 |
| `core/concepts.py` | YAML 加载、校验、运行时状态同步 | 新建 |
| `core/seed.py` | 题库种子导入（幂等） | 新建 |
| `web/app.js` | 会话界面、题目流、流式音频、VRM 口型、VAD 切句/判停 | 改 |
| `tests/*` | v0 验证映射逐条落地 | 扩展 |

## 5. 数据模型（v0）

v0 只用 6 张表；v1 再加 materials/material_chunks/concept_sources/question_cache 与 FTS5 索引。

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
  id TEXT PRIMARY KEY,                -- session_id，幂等键
  date TEXT NOT NULL,
  concept_id TEXT,
  kind TEXT NOT NULL CHECK (kind IN ('daily','synthesis','review')),
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
  question_role TEXT NOT NULL CHECK (question_role IN ('new','review','misconception')),
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

misconceptions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  concept_id TEXT NOT NULL,
  key TEXT NOT NULL,
  text TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('candidate','active','resolved')),
  times_seen INTEGER NOT NULL DEFAULT 1,
  clean_streak INTEGER NOT NULL DEFAULT 0,
  last_seen TEXT,
  UNIQUE (concept_id, key)
);
```

写入边界（D5）：
1. 每题答完：一个短事务写 `session_questions`，立即 commit。
2. 会话结算：一个事务写 `sessions.status/session_score`、`concepts.mastery/status/last_seen/review_due_at/review_started_at`、`misconceptions`；任一步失败整体回滚。
3. 重放：`session_id` 已存在且 `status != unscored` 时拒绝重复结算，返回已有结果。

## 6. 关键接口

### 6.1 Coach

```python
@dataclass
class Question:
    id: int                  # session_questions.id
    role: str                # new | review | misconception
    kind: str                # recall | discriminate | apply
    text: str
    options: list[str] | None
    index: int               # 1..5
    total: int

@dataclass
class SessionResult:
    session_id: str
    status: str              # completed | partial | unscored
    session_score: float | None
    scores: list[QuestionScore]
    mastery_updates: dict[str, int]
    review_due_at: str | None

class Coach:
    async def start(self, kind: str = "daily") -> tuple[str, Question]: ...
    async def resume(self, session_id: str) -> Question | None: ...
    async def submit_answer(self, session_id: str, question_id: int, text: str, input_mode: str) -> tuple[QuestionScore, Question | None]: ...
    async def finish(self, session_id: str) -> SessionResult: ...
```

- `start`：创建 session；有到期复习先出最多 2 道复习题，否则出一个新概念并出第一题。
- `submit_answer`：落库即 commit；立即调用 Scorer 给本题评分，返回 `(score, 下一题)`；五题答完返回 `(score, None)`，由 Agent 自动调 `finish`。
- `finish`：不再评分；只做结算——`session_score` 按已评分题均值、`concept_session_score`、mastery（最近三次）、review_due（v0 只做次日/清空）、status（completed/partial/unscored），单事务提交。提前结束也走 `finish`，记 `partial`。

### 6.2 Store

```python
class Store:
    def create_session(self, session_id: str, kind: str, date: str) -> None: ...
    def add_question(self, session_id: str, question: Question, bank_row) -> int: ...
    def save_answer(self, question_id: int, text: str, score: int | None, feedback: str | None) -> None: ...
    def finalize(self, result: SessionResult) -> None:   # 单事务
    def concept_states(self) -> list[ConceptState]: ...
    def due_reviews(self, today: str) -> list[ConceptState]: ...
```

### 6.3 Planner / Tutor / Scorer

```python
class Planner:
    def next_concept(self, states: list[ConceptState], today: str) -> ConceptState | None: ...

class Tutor:
    def ask(self, concept, question) -> str: ...       # 默认题库原文，必要时用 LLM 改写
    def feedback(self, score: int, why: str) -> str: ...

class Scorer:   # core/scoring.py
    async def score_open(self, questions, answers) -> ScoreResult: ...  # 重试一次
    def score_discriminate(self, question, answer_key, answer) -> int:  # 确定性
```

### 6.4 WebSocket 协议（v0 增量）

客户端 → 服务端：
- `{"type":"session_start","kind":"daily"}`
- `{"type":"session_resume","session_id":"..."}`
- `{"type":"answer","question_id":123,"text":"...","input_mode":"voice"|"text"}`
- `{"type":"finish","session_id":"..."}`（仅提前结束；第 5 题后自动结算，不需要发）
- 既有 `audio` / `text` 保留：`audio` 先转写，再作为 `answer.text`；`text` 直接作答。

服务端 → 客户端：
- `{"type":"session_ready","session_id":"...","question":{...}}`
- `{"type":"question","id":...,"role":"new","kind":"recall","text":"...","options":null,"index":1,"total":5}`
- `{"type":"score","question_id":...,"score":70,"why":"..."}`（每题答完立即发）
- `{"type":"session_result","status":"completed","session_score":78.0,"mastery":{...},"review_due_at":"2026-11-23"}`（第 5 题后自动发；提前结束也发）
- `{"type":"session_expired","session_id":"..."}`
- `{"type":"audio_chunk","seq":1,"mime":"audio/mpeg","data":"<base64>"}`（D8）
- 既有 `transcript` / `reply` / `warning` / `error` 保留。

协议约定（2026-11-23 / P1）：
- 收音：前端点"开始说话"后持续采集，VAD 切句、长停或手动结束提交；它说话时麦克风关闭（半双工），不做打断/回声消除。
- `audio_chunk` 带 `seq`；前端按 `seq` 排队播放，切题或结束时丢弃未播音频。
- 题目音频优先预合成缓存；`delta` 只用于反馈/讲解的流式文本。

## 7. 会话流程

```
start(kind=daily)
  ├─ due_reviews(today) 非空 -> 复习题（最多 2，role=review）
  └─ 否则 -> planner.next_concept() -> 新概念（role=new）
        |
        v
  ASKING --answer--> 落库 + 本题评分 --未满5题--> ASKING
        |                          |
        |                          +--满5题--> 自动结算
        |                                          |
        +--用户点结束(partial)---------------------+
                                                   v
                                    FINISHED / PARTIAL / UNSCORED
```

评分时机（2026-11-23 / P5）：每题答完立即评分并 commit；辨析题本地判分，开放题调用 Scorer；单题失败重试一次，仍失败该题记未评分、继续；第 5 题后自动结算。mastery/review_due 在结算时更新。

五题配比（唯一实现处：`core/coach.py` 的 `RATIO_TABLE`）：

| 早期题 | 组成 |
|---|---|
| 0 | 新 2 回忆 + 2 辨析 + 1 应用 |
| 1 复习 | 复习 1 + 新 1 回忆 + 2 辨析 + 1 应用 |
| 1 误解 | 误解 1 + 新 1 回忆 + 2 辨析 + 1 应用 |
| 2 复习 | 复习 2 + 新 1 回忆 + 1 辨析 + 1 应用 |
| 1 复习 + 1 误解 | 复习 1 + 误解 1 + 新 1 回忆 + 1 辨析 + 1 应用 |

计算口径：
- `session_score` = **已评分题目**得分的算术平均；未作答或未评分的题不按 0 计。5 题都作答且都评分 → `completed`；至少 1 题评分但不足 5 题或有未评分题 → `partial`；一题都没评上 → `unscored`。
- `concept_session_score` = 该概念本次 `question_role=new` 且已评分的题得分均值。
- `mastery` = round(最近三次 `concept_session_score` 均值 / 20)，不足三次用已有。
- 复习入队：daily 后 `concept_session_score < 80` 且 `review_due_at` 为空 → 次日；`>= 80` 清空。
- 复习结果（v0）：review 题均值；<80 → 次日；>=80 清空。60-79 三天、14 天循环留 v2。

## 8. 错误与降级

| 故障 | 处理 | 用户看到 |
|---|---|---|
| ASR 超时/5xx | BFF 发 `warning`，前端切文字并聚焦输入框；`input_mode=text` | “语音不可用，已切文字” |
| LLM 流中断 | 本轮 `error`，历史不更新，可重试 | 明确错误 |
| TTS 失败 | 只显示文字，不阻塞答题 | 文字 + 警告 |
| 评分超时/5xx/JSON 不合约 | 该题重试一次；仍失败该题记未评分，会话继续；一题都没评上才整场 `unscored` | 该题显示“未评分”，答题不丢 |
| SQLite 结算失败 | 事务回滚，session 保持未结算，可重试 | “结算失败，请重试” |
| 题库缺题 | 不出该题，退回同概念旧题；无旧题则跳过该概念并提示 | 明确提示 |

## 9. 测试与验证映射（v0）

| 行为 | 测试文件 | 断言 |
|---|---|---|
| YAML 校验：id 唯一、前置存在、无环、必填字段 | `tests/test_concepts_yaml.py` | 每类坏输入都报错并指出节点 |
| 题库种子导入幂等 | `tests/test_seed.py` | 重复导入不产生重复行 |
| 五题配比五种组合 | `tests/test_ratios.py` | 每种组合长度 5，角色计数正确 |
| 辨析题本地判分 | `tests/test_discriminate.py` | 正确选项 100，错误选项按 rubric 档位 |
| 评分解析失败重试一次 | `tests/test_scoring_retry.py` | 第一次坏 JSON、第二次好 JSON → 成功；两次都坏 → 该题未评分，会话继续 |
| mastery 计算 | `tests/test_mastery.py` | 最近三次均值/20；不足三次用已有 |
| review_due 次日/清空 | `tests/test_review.py` | v0：<80 次日、>=80 清空；三天/14 天留 v2 |
| 逐题评分 + 自动结束 | `tests/test_coach_flow.py` | 每题写 score/feedback；第 5 题后自动结算 |
| 结算事务 | `tests/test_session_finalize.py` | 模拟中途失败 → 四张表无半更新 |
| agent_sessions 生命周期 | `tests/test_agent_sessions.py` | active → finished/abandoned；同日 resume 返回未答题 |
| ASR 降级 | `tests/test_ws.py` | ASR 抛错后前端收到切文字提示，会话可继续 |
| unscored / partial | `tests/test_coach_flow.py` | 全部评分失败 → unscored；单题失败 → partial，答案保留 |
| Coach 主流程 | `tests/test_coach_flow.py` | start→answer×5→自动结算；提前结束 partial |

评分一致性（Open Question 1）：DeepSeek 已接通（3/3 可解析，979ms）；先做 10 条人工对照 smoke，再做 20 条完整对照，一致率 >=75%；低于门槛换提示词或加二次校验。该 eval 属 v0 后独立 gate，结果写入 `docs/designs/`。

## 10. 依赖与配置

- v0 不需要 embedding，不需要 FTS5，不需要材料解析。
- 真实 provider 接入前必须先跑 `python -m bff.probe --mode real --repeat 5`，四项全通才进入 v0 联调（F1 门禁）。
- 环境变量见 `.env.example`；`PROVIDER_MODE=auto|real|fake`。
- 数据路径：`data/app.db`（gitignore）；演示用 `data/demo/app.db`，一键清空只删该目录。
- 题库种子：`seeds/question_bank.json`（进仓库），首次运行 `python -m core.seed` 导入。

## 11. 实施顺序

| 顺序 | 任务 | 依赖 | 说明 |
|---|---|---|---|
| 0 | T0 协议与交互 | 设计 v2.0 | WS 事件协议；点击收音 + VAD 判停；保留按住 fallback |
| 1 | T1 冻结记录 | — | v2.0 已于 2026-11-23 冻结，哈希见 `FREEZE.md` |
| 2 | T2 四 API probe 门禁 | 接口 | 四项全通才继续 |
| 3 | T4 SQLite schema 与两段式写入 | — | 先有表与事务，再有 Coach |
| 4 | T3 core/coach.py | T4 | 状态机、配比、mastery、review_due |
| 5 | T5 ASR 降级 | — | 可与 T3 并行 |
| 6 | T6 TTS 端到端流式 | T5 | 同改 `web/app.js`，需顺序 |
| 7 | T7 验证映射与 v0 测试 | T3-T6 | 按第 9 节逐条落测试 |

## 12. v1 概要

- 模块：`core/ingestion.py`（Markdown/HTML 解析、父子切块）、`core/extraction.py`（概念抽取与质量门槛）、`core/retrieval.py`（FTS5 + 向量 + RRF）、`core/question_cache.py`（前一晚预生成）。
- 表：`materials`、`material_chunks`、`concept_sources`、`question_cache`，以及 FTS5 虚拟表与向量表。
- 检索：v1 直接采用 FTS5 trigram + 向量混合，RRF 融合（D3）；embedding 模型、维度、成本必须在 v1 开工前定。
- 门槛：20 条查询召回率对照；达不到就调融合权重或换切块，不宣称 v1 完成。
- 风险：`sqlite-vec` 仍是 pre-v1，必须锁版本；中文 trigram 召回需实测。
- 不做：PDF、增量自动化、完整间隔复习、综合场（v2）。

## 13. v2 概要

- PDF 解析；材料增量更新自动化，只对新增/变更块抽概念。
- 完整间隔复习：<60/60-79/>=80 与 14 天循环全部上线。
- 误解生命周期：candidate → active（第二次确定检出）→ 第三次触发重问 → clean_streak>=2 resolved；resolved 再检出回 active。
- 第 7 次完成的日常会话为综合场：5 道综合题 + 5 分钟跨概念讲解，不更新单概念 mastery。
- 音素级口型可选；不做预生成视频。

## 14. 风险与开放问题

| 项 | 现状 | 影响 | 处理 |
|---|---|---|---|
| 四个 API 契约 | 未提供 | 适配器可能重写 | T2 probe 门禁 |
| 2.5 秒短答 | 未实测 | d0 验收 | D8 流式 + 实测；不支持则改 4 秒 |
| ASR 80% | 未录音 | d0 验收 | 20 句测试集 + `bff.asr_eval` |
| embedding 模型 | 未定 | v1 开工 | v1 前定模型/维度/成本 |
| 评分一致性 | DeepSeek 已接通但未校准 | 分数可信度 | 10 条 smoke + 20 条人工对照，75% 门槛 |
| DeepSeek Flash | 已接通（3/3 可解析，979ms） | 逐题评分约 +1s | 已写入 `.env`；校准后定稿提示词 |
| 节点/材料数量 | 占位 | 90 天目标 | 确认页与月度复盘时定 |
| v2.0 冻结 | FROZEN（2026-11-23） | 实现依据 | 变更走 `FREEZE.md` |

## 15. 验收清单

- d0：短答从判停（VAD 长停或点"结束作答"）到第一帧音频 <=2.5 秒；20 句术语准确率 >=80%；麦克风在播放期间关闭（点击收音 + VAD；保留按住 fallback）。
- v0：每概念 5 题；逐题评分，第 5 题自动结算；mastery 落库；次日复习入队；ASR 失败可切文字；单题评分失败记未评分，零评分才 `unscored`，答案不丢。
- 90 天：完成目标节点数；每个概念最新分 >=80；最近 30 天 >=24 次完成。

## 16. 实测记录（2026-11-22）

- 探针：MiMo LLM / MiMo ASR / Breeze TTS 三项真实调用全部通过，报告 `docs/designs/api-probe/2026-11-22-211620.md`。
- ASR：419ms（合成提示音）、725ms（Breeze 合成真实语音，转写与原文一致：`用你自己的话说说，agent和workflow的区别。`）。
- LLM：`mimo-v2.6-flash`，首 token 1.05-2.16s，总 2.4-6.4s；默认不发送 temperature。
- TTS：`breeze-tts-2`，流式首包 468-620ms；整段 2.8-4.4s（探针）到 12s（页面长回复）；音色 `voc_rc894j8q2auu`（知绘小姐）。
- 结论：2.5 秒目标未达，4 秒兜底更现实；T6 端到端流式按用户决定暂缓，先继续 v0。
- DeepSeek Flash：2026-11-23 接通，`https://api.deepseek.com/v1` + `deepseek-chat`；3 次评分 3/3 可解析，平均 979ms，分数 90/90/90；报告 `docs/designs/api-probe/2026-11-23-112742.md`。

## 17. 决策来源

- 设计 v2.0：`docs/designs/learning-companion-digital-human-v2.0.md`
- 评审报告：`C:/Users/11528/.gstack/projects/Zqqloading-football-agent/master-eng-review-20261121-162456.md`
- Test Plan：`C:/Users/11528/.gstack/projects/Zqqloading-football-agent/11528-master-eng-review-test-plan-20261121-165900.md`
- 决策：D3 混合检索、D4 三阶段验证映射、D5 两段式写入、D6 ASR 降级、D7 Coach 入口、D8 TTS 流式。
- 2026-11-23 POC 调整：P1 点击收音 + VAD 判停（半双工保留，不做打断/AEC）；P2 会话层/语音层分离，考评是慢回路；P3 联网只做材料入口或超纲兜底；P4 题目音频优先预合成，反馈才逐句流式。
- 2026-11-23 评分/会话调整：P5 逐题即时评分（单题失败记未评分，继续）；P6 第 5 题自动结算（保留提前结束）；P7 摸底纳入 v0；P8 自由对话改配置开关；评分改用 DeepSeek Flash。
- 2026-11-24 按实现收敛：R1 撤销摸底与初始 mastery 校准（AI-24）；R2 撤销自由对话配置开关，初始界面常开（AI-25）。
