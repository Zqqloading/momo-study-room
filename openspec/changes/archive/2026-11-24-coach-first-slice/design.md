# Design

## Context

- 当前 `bff/main.py` 是自由对话回环：`text/audio` → LLM 流式 → TTS → `reply`，没有会话状态、选题、评分与结算。
- `core/` 已有可复用的地基：`concepts.py`（YAML 校验、状态同步）、`planner.py`（active + 前置解锁）、`scoring.py`（评分 JSON 解析与校验）、`store.py`（逐题 commit、结算单事务）、`ports.py`（ASR/LLM/TTS/Scorer 协议）。`bff/providers/` 的 MiMo ASR/LLM、DeepSeek Scorer、Breeze TTS 适配器已接通；Breeze 适配器已有 `stream()`。
- `core/db.py` 是 schema v1：缺 `agent_sessions`、`session_notes`；`session_questions.question_role` 没有 `retention`；`sessions.kind` 为 `diagnostic|daily|synthesis|review`。
- `web/app.js` 已有录音、WAV 编码与音频队列，但没有 VAD、题目卡与会话结果。
- 约束：`core/` MUST NOT import httpx；BFF MUST NOT 直接写 SQL；`Store` 是唯一写入口；会话只读 `question_bank`。
- 术语以 `docs/designs/first-slice-v0.1.md` 为准：planned 指 start 时插入的题数，early 指到期复习题。

## Goals / Non-Goals

**Goals:**

- 让第一片的文本与语音走同一条 Coach 路径，事件与落库可回放。
- 把业务规则集中在 Coach，把 WS 编排与适配留在 BFF，边界不互相渗透。
- 用注入的 Clock / Scorer / ASR / LLM / TTS 让状态机可测，不依赖真实 API。

**Non-Goals:**

- 不做 retention、教学/澄清/命令、AI 题库生成审核、诊断、概念确认页、误解持久化。
- 不做间隔复习的多档规则（60-79 三天、14 天循环）。
- 不做音频缓存的淘汰策略与并发合流。

## Decisions

### D1 同日恢复用独立消息

新增客户端消息 `session_resume`（带 `session_id`），服务端同日 active 返回第一道未作答题，跨日或非 active 返回 `session_expired` 并把旧会话置 abandoned。

- 备选：`session_start` 幂等恢复（少一个消息类型，但把“开始”和“恢复”混在一起）；建连自动恢复（客户端无法表达意图）。
- 理由：与 `first-slice-v0.1.md` §7.7 一致，状态语义清楚。

### D2 fixture 放 seeds/fixture

新建 `seeds/fixture/fixture-concepts.yaml` 与 `seeds/fixture/fixture-question-bank.json`：3 个 active 概念、每概念 10 道题，启动时按 id upsert 导入（内容变化更新镜像，不变时返回 0 保持幂等）；pytest 复用同一份文件。

- 备选：测试内硬编码（生产不可运行）；复用知识库内容（跨工作区耦合、含版权摘录）。
- 理由：`.gitignore` 会忽略任意层级的 `concepts.yaml`，用不同文件名避免改 `.gitignore`；fixture 内容手写中性示例，不带第三方出处。

### D3 schema v2/v3 直接重建与增量

`SCHEMA_VERSION=3`。v2 新增 `agent_sessions`、`session_notes`；`question_role` 增加 `retention`；`sessions.kind` 缩窄为 `daily|review`。v3 新增 `conversations`、`conversation_messages`，v2 数据保留（只建新表，不重建）。v1 → v2 仍直接重建。

- 备选：v2→v3 也重建（丢学习进度与历史，不可取）；写完整迁移框架（第一片不需要）。
- 理由：v1 的 CHECK 必须重建；v3 只新增表，跑 `CREATE IF NOT EXISTS` 即可；`agent-infrastructure-v0.1.md` 仍写 `daily|diagnostic`，本轮不改该文档，留作已知文档偏差。

### D4 分层与依赖方向

Coach 负责配比、评分编排、结算、mastery、复习调度；Agent 只做最小路由与会话生命周期；BFF 负责 WS 协议、ASR/TTS 适配与事件翻译；Store 唯一写库。

- 备选：把路由塞进 Coach（规则与状态耦合）；BFF 直接调 Store（越层）。
- 理由：与 `first-slice-v0.1.md` §4 一致，后续加模式路由时不改 Coach 主体。

### D5 整句精确匹配路由

归一化（去空白、去标点）后整句命中白名单才触发“不知道/知道了”：

- 不知道：`不知道 / 不懂 / 不会 / 我不知道 / 不太知道 / 不清楚`
- 知道了：`知道了 / 懂了 / 明白了 / 会了`

长句一律按正常答案走评分，不做包含匹配。

- 备选：短句包含匹配（容忍“嗯不知道”，但误判长答案）；只认最短形式（漏判多）。
- 理由：可预测、可测；误判成本低（用户可改说一次）。

### D6 评分复用 core.scoring

辨析题按 `answer_key` 本地判分；答对反馈“答对了”且不朗读；答错反馈“正确答案 + 选项文本 + 解析”并朗读。解析优先取 rubric 的 `explanation`，没有再用 `criteria`；若解析与选项文本相同则丢弃，避免复述选项。开放题逐题调用 Scorer，`parse_score_result` 校验，失败重试一次，仍失败记 `score=NULL`。Scorer 同一次返回里附带 `reference_answer`，Coach 把它拼进反馈文本（“参考答案：…”），不额外增加模型调用。Scorer 返回的 `session_misconception` 第一片忽略。

- 备选：整场一次评分（与“逐题即时评分”冲突）；单独一次调用生成标准答案（多一次成本与延迟）。

### D7 probe 用主 LLM

追问由 `providers.llm`（MiMo）生成，输入为题面、用户回答与 rubric，MUST NOT 读 `answer_key`；失败退回模板“能举个例子吗？”。测试用 `FakeLLM`。

- 备选：复用 Scorer 端点（评分与生成职责混合）；固定模板（体验差）。

### D8 TTS 流式作为可选能力

`core/ports.py` 增加独立的 `StreamingTTS` 协议（`stream()`）：Breeze 适配器实现它，Fake/非流式适配器不实现；BFF 用 `getattr` 探测，缺失时折叠成单块。`audio_chunk` 的 `seq` 从 1 递增。缓存 key 为 `hash(text + voice + model + format)`，其中 model 前缀适配器名，避免 fake/real 缓存串用；目录 `data/audio_cache/`。

- 备选：只做非流式整段（首包慢）；BFF 里按适配器类型分支（耦合）。
- 理由：端口保持统一，BFF 不需要知道具体供应商；不强迫所有适配器实现流式。

### D9 结算复用 Store.finalize

结算继续用 `Store.finalize` 的单事务与 `SessionAlreadyFinalized` 幂等保护；补写 `agent_sessions.status=finished` 与 `session_notes`。逐题 commit 在 `answer`。

- 备选：新写一个结算模块（重复事务逻辑）。
- 理由：现有实现已覆盖 sessions/concepts/session_concepts 与 due_updates，扩展成本最低。

### D10 改造现有 Web 页面

在现有 `web/` 上做会话视图：题目卡、进度、score、结果卡；文本路径先通，语音阶段在现有录音路径前加能量 VAD。旧自由对话事件不再由页面消费。下一题/本场结果在上一题反馈语音播完后展示；反馈结束与下一题之间留 700ms 停顿，展示下一题时清空评分、参考答案、气泡与输入框，下一题页面不携带上一题内容。结果页主按钮为「结束今天的学习」，点击回到初始界面，不限制当天场次。

- 备选：新建独立页面（两套 UI 并存）；不做 UI（无法手工验收体验）。

### D11 初始自由对话入口

没有进行中的会话时，「开始说话」可用。BFF 收到不带 `session_id`/`question_id` 的 `audio` 时走自由对话：ASR → `classify_free_talk` 关键词分为 `teach`/`chat` → 两套提示词调 `providers.chat`（优先 DeepSeek 端点，实测 ~1.2s；未配置或 fake 模式回退主 LLM）→ 推送 `reply` 并用 `_stream_feedback` 朗读。

对话消息写入 `conversations`/`conversation_messages`；客户端通过 `conversation_new`/`conversation_list`/`conversation_load` 新建、列出、加载历史；上下文取当前对话最近 12 条。每次调用把 active 概念的 mastery、review_due 与最近 3 场成绩摘要注入系统提示。不评分。

- 备选：用一次 LLM 调用先分类（更准但多一次延迟与成本）；一个提示词让模型自己决定讲解或闲聊（路由不可观测）；只存内存（刷新丢失）。
- 理由：关键词可测、零额外调用；SQLite 持久化成本低，学习进度可作为稳定上下文。

### D12 选题去重与轮换

Coach 选题按 `Store.question_usage`（题库 id → 最近一次 `session_questions.id`）排序：未用过（0）优先，其次最久未用，同分按题库 id；早期复习同样取该概念最久未用的题。fixture 每个概念扩到 10 道，保证连续 5 题场次能换开。

- 备选：随机选题（不可复现、难测）；只按题库 id（永远同一套题）。
- 理由：确定性轮换可测，且不引入额外状态表。

### D13 会话中的「下一题」

会话中主按钮改为「下一题」：未作答时发送 `skip`，Agent 写跳过标记（不写分数）并推进；已作答且反馈仍在播时，客户端停止剩余反馈音频、静音迟到块，立即展示已暂存的下一题；最后一题推进到结算。跳过题在结算里按未作答计（partial/unscored）。

协议上把 `question`/`session_result` 提到反馈语音之前发送，反馈流结束后再发 `feedback_end`；`audio_chunk` 带 `utterance`（feedback/question）区分两类音频。这样点击「下一题」不必等 TTS 生成完。

- 备选：按钮保持禁用（用户只能等反馈）；只允许跳过未作答题。
- 理由：把切题时机交给用户，同时不破坏评分完整性。

### D14 TTS 全局串行

题目预合成、反馈流式、自由对话的所有 TTS 调用共享 app 级 `asyncio.Lock`，失败等 1 秒重试一次。Breeze 的并发上限是账号级的，单连接内串行不够。

- 备选：每连接一把锁（仍可能并发超限）；不重试（用户收不到反馈）。
- 理由：429 只在高并发时出现，串行 + 一次重试是最小代价。

## Risks / Trade-offs

- [直接重建数据库会丢现有运行时状态] → 重建前保留 `.bak` 或在 fresh DB 上验收；fixture 可重导。
- [逐题评分增加调用次数与延迟] → 单题评分、失败不阻塞；Scorer 超时按未评分继续。
- [VAD 占位参数误判] → 判定抽成纯函数用合成 PCM 测；真实麦克风只做烟雾并记录参数。
- [整句匹配漏判“嗯不知道”] → 按答案评分可能得 0 分，用户可重说；后续可加短句规则。
- [TTS 预合成浪费配额] → 只预合成本场 planned 题目；缓存命中复用；失败降级实时合成。
- [fixture 内容与知识库脱节] → 只用于流程验证，真实内容由知识库接管。

## Migration Plan

1. 升 `SCHEMA_VERSION=2`，启动时检测旧版本并拒绝或重建（第一片选择重建）。
2. 重建后幂等导入 `seeds/fixture/` 的概念与题库。
3. 回滚：回退代码到 `5cf9a39` 并删除新建的 `data/app.db`，用旧 schema 重建。

## Open Questions

- VAD 能量阈值、最短语音时长需要真实麦克风校准；第一片用占位值。
- 10 条评分校准 gate 独立于本切片，未校准前分数只作流程验证。
- 混合句检测只靠疑问词与位置，覆盖有限；第一片接受。
- MiMo 不返回 ASR 置信度，`asr_confidence` 字段保留不用。
