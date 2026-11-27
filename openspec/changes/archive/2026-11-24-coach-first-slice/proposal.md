# Proposal

## Why

第一片要验证「Coach 状态机 + 评分 + 结算」是否成立：在同一条路径上跑通文本和点击说话，完成 5 题、逐题评分、自动结算、mastery 与同日恢复。当前 `bff/main.py` 仍是自由对话回环，没有会话状态、五题配比、结算与恢复；`core/` 里只有 Planner、评分解析和 Store，没有 Coach 与最小路由。

## What Changes

- 新增 Coach：`start` 选题（早期复习 + 新概念、0/1/2 early 配比）、`answer` 逐题评分、`finish`、自动结算、mastery、`review_due`、同日恢复。
- 新增 Agent 最小路由：答题 / 不知道 / 知道了（触发一次 probe，不评分）；**BREAKING** 当前自由对话路径被会话路径替换。
- 新增 `agent_sessions`、`session_notes` 表；`SCHEMA_VERSION` 升到 2；`session_questions.question_role` 增加 `retention`；第一片直接重建数据库，不做迁移。
- **BREAKING** BFF WS 协议改为 `session_start` / `audio` / `answer` / `finish` + `question` / `score` / `probe` / `session_result`；文本路径先跑通，再接语音。
- 语音链路：浏览器能量 VAD（1.5s 静音判停）、MiMo 整段 ASR、一步提交直评；可疑转写与混合句暂停确认。
- 会话外自由对话：初始界面「开始说话」可用，关键词路由教学/闲聊，回复走 LLM + TTS；不写库、不评分。
- TTS：Breeze 流式反馈逐块推送；题目音频会话开始时首题同步合成、其余后台预合成，缓存到 `data/audio_cache/`。
- 明确不做：retention、完整四模式路由（澄清/命令）、teach-back、AI 题库生成审核、诊断场、概念确认页、误解生命周期；教学只覆盖自由对话里的概念讲解。

## Capabilities

### New Capabilities

- `coach-session`: 会话生命周期与考评——start 选题与配比、逐题评分、自动结算事务、mastery、次日复习、同日恢复、partial/unscored 语义、不知道/知道了的 probe。
- `voice-input`: 点击说话的语音输入链路——浏览器 VAD 判停、整段 ASR、一步提交、可疑转写与混合句的确认例外、ASR 失败降级到文本。
- `tts-playback`: 反馈流式 TTS 与题目音频——`audio_chunk` 顺序、题目预合成与缓存命中/未命中、TTS 失败只显示文字。
- `free-talk`: 会话外语音入口——初始界面直接说话、关键词路由教学/闲聊、回复朗读、失败可重试、对话长期持久化与历史切换、学习进度上下文。

### Modified Capabilities

（无；`openspec/specs/` 目前为空。）

## Impact

- 代码：`core/db.py`（schema v2、两张新表）、`core/store.py`、`core/models.py`；新增 `core/coach.py`、`core/agent.py`（最小路由）、`core/tts_cache.py` 或等价模块；`bff/main.py` 重写 WS 协议；`web/app.js`、`web/index.html` 跟进会话 UI。
- 测试：新增 `test_ratios`、`test_coach_flow`、`test_settlement`、`test_mastery`、`test_review`、`test_router`、`test_agent_sessions`、`test_tts_cache`；改造 `test_ws` 覆盖文本/语音两条路径。
- 依赖：复用现有 MiMo ASR、DeepSeek Scorer、Breeze TTS 适配器；fixture 提供 3 个 active 概念、每概念 6-7 道题。
- 数据：`data/app.db` 直接重建；新增 `data/audio_cache/`（gitignored）；fixture 题库随 seeds 进 git。
- 文档：实现依据 `docs/designs/first-slice-v0.1.md`；不修改 v2.0 冻结正文。
