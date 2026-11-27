# Tasks

## 1. Schema v2 与 fixture

- [x] 1.1 `core/db.py` 升 `SCHEMA_VERSION=2`：新增 `agent_sessions`、`session_notes`；`session_questions.question_role` 允许 `retention`；`sessions.kind` 缩窄为 `daily|review`；旧库检测到 v1 时走重建；验证：`test_db.py` 断言新表、CHECK 约束与版本号
- [x] 1.2 新建 `seeds/fixture/fixture-concepts.yaml`（3 个 active 概念）与 `seeds/fixture/fixture-question-bank.json`（每概念 10 题，含 rubric、source_url、source_excerpt；辨析题含 explanation）；验证：加载后概念数 3、题目数 30，缺出处即报错
- [x] 1.3 新增 fixture 幂等导入入口（概念走 `concepts.load_concepts`，题库走 `Store.import_question_bank`，按 id 内容 upsert），启动与测试复用；验证：连续导入两次行数不变、内容变化能更新，`test_store.py`/新增导入测试通过
- [x] 1.4 `Store` 补 `agent_sessions` 与 `session_notes` 读写：start 插入 active、answer 更新 last_question_id/input_mode/updated_at、finish 置 finished、跨日置 abandoned、resume 取第一道未答题；验证：`test_agent_sessions.py` 覆盖全部状态转移
- [x] 1.5 schema v3：新增 `conversations`/`conversation_messages`，v2 → v3 只建表不重建；验证：`test_db.py` v2→v3 数据保留用例、`test_conversations.py` 通过

## 2. 测试替身与 Coach

- [x] 2.1 注入 Clock 与 ScriptedScorer（按题号返回分数/坏 JSON/异常）、FakeASR、FakeLLM、FakeTTS；验证：单测可固定 today/now，评分可复现且无需网络
- [x] 2.2 Coach `start`：0/1/2 early 三种配比、无新概念时 review-only、planned 等于实际插入行数；验证：`test_ratios.py` 三组配比与 review-only 用例通过
- [x] 2.3 Coach `answer`：辨析题本地判分 100/40；开放题逐题调用 Scorer，失败重试一次后 `score=NULL`+“本题未评分”；每题立即 commit；验证：`test_scoring.py` 与 `test_coach_flow.py` 通过
- [x] 2.4 Coach 结算：完成全部题 → completed，`finish` → partial，零评分 → unscored；单事务写 sessions/concepts/session_concepts 并置 `agent_sessions=finished`，重复结算被拒；验证：`test_settlement.py` 覆盖四种状态与幂等
- [x] 2.5 mastery 与次日复习：mastery 取最近三次 completed daily 的 `role=new` 均分/20，partial 不计；daily <80 置次日、review ≥80 清空、非 active 不入队；验证：`test_mastery.py`、`test_review.py` 通过
- [x] 2.6 开放题反馈附带参考答案：Scorer 同一次返回 `reference_answer`，Coach 拼进反馈文本；验证：`test_scoring.py` 解析用例与 `test_coach_flow.py` 参考答案用例通过
- [x] 2.7 题目去重与轮换：未出过优先、其次最久未出，同场不重复；fixture 每概念 10 题；验证：`test_dedup.py` 三组用例通过
- [x] 2.8 辨析题反馈分支：答错朗读正确答案+解析，答对只显示不朗读；验证：`test_coach_flow.py` 与 `test_ws.py` 对应用例通过

## 3. Agent 最小路由

- [x] 3.1 整句精确匹配路由：归一化去空白/标点后命中不知道、不会、我知道了等白名单；长句按正常答案；验证：`test_router.py` 覆盖白名单、长句与标点变体
- [x] 3.2 “不知道”返回 0 分与 ≤60 字短定义+例子，不调 LLM；“知道了”第一次生成 probe（不读 answer_key）、第二次记未作答、LLM 失败退回模板；验证：`test_router.py` 对应用例通过
- [x] 3.3 Agent 会话生命周期：`session_start`/`session_resume`/`answer`/`finish` 翻译成 Coach 调用；同日 resume 返回第一道未答题，跨日返回 `session_expired`；验证：`test_agent_sessions.py` 与 `test_coach_flow.py` 通过

## 4. BFF WS 文本路径与页面

- [x] 4.1 重写 `bff/main.py` 协议：`session_start`/`session_resume`/`answer`/`finish` 入，`session_ready`/`question`/`transcript`/`score`/`probe`/`session_result`/`session_expired` 出；`turn_id` 全链路透传；验证：`test_ws.py` 文本 5 题自动结算用例通过
- [x] 4.2 启动时导入 fixture 并保持 fake 模式可离线跑通；`ready` 事件带模式说明；验证：`PROVIDER_MODE=fake` 下从空库启动、连 WS 完成一场并检查 DB 回放
- [x] 4.3 改造 `web/` 为会话视图（题目卡、进度、score、结果卡）；文本输入先通；验证：手工文本 5 题到结果卡，页面无控制台错误
- [x] 4.4 下一题/结果在反馈语音播完后展示，下一题页清空上一题评分与参考答案；验证：浏览器实测 Q1 评分约 1.5s 出现、Q2 在反馈播完后出现且评分区隐藏
- [x] 4.5 会话中主按钮改为「下一题」：未作答发 skip 推进，已作答可跳过剩余反馈；验证：`test_agent_sessions.py` 跳过用例、`test_ws.py` skip 用例与浏览器实测
- [x] 4.6 结果页「结束今天的学习」回到初始界面，开始说话与开始今天的学习可用，不限制当天场次；验证：浏览器实测连续开局

## 5. TTS 流式与题目预合成

- [x] 5.1 `TTSProvider` 增加可选 `stream()`，Fake/非流式适配器折叠成单块；BFF 推送带递增 `seq` 的 `audio_chunk`；验证：`test_ws.py` 断言 seq 从 1 递增且前端按序播放
- [x] 5.2 题目音频预合成：会话开始首题同步、其余后台；缓存 key 为文本+音色+模型+格式哈希，目录 `data/audio_cache/`；命中复用、未命中或失败实时合成；验证：`test_tts_cache.py` 覆盖命中/未命中/失败
- [x] 5.3 TTS 失败只推 `warning(stage=tts)` 并显示文字，不阻塞答题；验证：`test_ws.py` TTS 失败用例通过

## 6. 语音链路

- [x] 6.1 能量 VAD 抽成纯函数（阈值、1.5s 静音、最短语音 200ms 占位）；验证：合成 PCM 测试静音不触发、说话后静音触发、短停不触发、手动结束优先
- [x] 6.2 一步提交：`audio` → ASR → `transcript(needs_confirmation=false)` → 直接评分，`turn_id` 一致；验证：`test_ws.py` 语音 5 题用例通过
- [x] 6.3 可疑转写与混合句暂停：空/极短/语气词/乱码 → `reason=suspicious`，疑问词混合 → `reason=mixed`；白名单不暂停；验证：`test_ws.py` 与 `test_router.py` 对应用例通过
- [x] 6.4 ASR 超时/5xx 降级到文本并记 `input_mode=text`；`asr_confidence` 保持 NULL；验证：`test_ws.py` 失败用例与落库断言通过
- [x] 6.5 页面录音路径接入 VAD 与“开始说话/结束作答”，复用现有 WAV 编码与音频队列；验证：真实 Edge 麦克风跑完一场（5 题全语音，session_score 50，`input_mode=voice`，DB 回放一致）

## 7. 真实 provider 烟雾与校准 gate

- [x] 7.1 真实 MiMo/DeepSeek/Breeze 冒烟：文本一场 + 语音一场，记录延迟与失败点；验证：两场都到 `session_result`，DB 回放一致（记录：`docs/designs/review-20261123/real-provider-smoke.md`）
- [x] 7.2 10 条人工对照的评分校准（独立 gate）：首轮 7/10 未通过，按失败模式调整分档后，新 10 条 holdout 第二轮 8/10 差值 ≤15、MAE 10.5，通过；记录：`docs/designs/review-20261123/scoring-calibration.md`、`scoring-calibration-round2.md`

## 8. 初始自由对话入口

- [x] 8.1 会话外「开始说话」可用：无 session 的 audio 不带会话字段，BFF 路由到自由对话；验证：`test_router.py` 与 `test_ws.py` 自由对话用例通过
- [x] 8.2 关键词路由 teach/chat + 两套提示词；验证：学习问题与闲聊分别命中对应 mode
- [x] 8.3 回复推 `reply` 并朗读 audio_chunk，不写库不评分；验证：自由对话后 sessions 表无新增
- [x] 8.4 同一连接保留 12 条短期历史；验证：`test_free_talk.py` 截断单测通过
- [x] 8.5 自由对话延迟：优先 DeepSeek 端点（回退主 LLM），实测首块 ~3.2s（ASR 0.4s + 回复 1.4s + TTS 首块）；验证：`test_registry.py` chat 用例与真实自由对话计时
- [x] 8.6 对话长期持久化：新增/列出/加载/续聊，消息落 `conversations`/`conversation_messages`；验证：`test_conversations.py`、`test_ws.py` conversation 用例
- [x] 8.7 学习进度摘要注入自由对话系统提示；验证：`test_free_talk.py` 进度用例与实测摘要
- [x] 8.8 前端「新对话 + 历史下拉 + 聊天记录面板」；验证：浏览器实测新建、切回旧对话、刷新回看

## Workflow follow-up

- 评审通过后归档 change：`openspec archive coach-first-slice`。
