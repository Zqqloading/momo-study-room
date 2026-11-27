# 修复记录（Round 2 → Round 3）

评审输入：`round2.md`（6 新阻塞 / 11 新次要；8 个 R1 项 PARTIAL）
修复日期：2026-11-21

| id | 严重度 | 状态 | 改了什么 / 为什么 |
|---|---|---|---|
| N-01 | BLOCKING | FIXED | 复习队列的唯一真相源改为 `concepts.review_due_at`：非空即在队列；日常分数 <80 且为空→次日，>=80→清空；复习结果 <60/60-79/>=80 分别次日/3 天后/清空。删掉“由 concept_session_score 派生”的矛盾。 |
| N-02 | BLOCKING | FIXED | `kind=review` 讲解场豁免五题校验，也豁免“至少 3 题已评分”的完成定义；不计入 30 天完成数；综合场当天只算一次。 |
| N-03 | BLOCKING | FIXED | 新增每第 4 次日常会话为复讲场，重选 <80 或最久没见的概念按 daily 计分，更新 mastery；补 40 概念 × 1.5 次 ≈ 60 次日常的账。 |
| N-04 | BLOCKING | FIXED | `skipped` 视为已满足前置，后继照常解锁；确认页提示会解锁哪些后继（三处 Planner 规则同步）。 |
| N-05 | BLOCKING | FIXED | 复习块条件改为“有到期复习或未解误解触发”；复习屏条件同步；误解占两个复习名额之一。 |
| N-06 | BLOCKING | FIXED | 2.5 秒目标限定为短答（录音 ≤10 秒）；讲解（4-5 分钟）单独要求录音结束后 60 秒内转写就绪；预算改为 2.3 秒，留 0.2 秒余量。 |
| N-07 | MINOR | FIXED | 误解数改为“每题标是否命中，整场最多 1 条会话级误解”。 |
| N-08 | MINOR | FIXED | misconceptions 增加 `clean_streak`；会话结束检查：无相关题+1，有且 >=80 +1，否则清零；>=2 置 resolved。 |
| N-09 | MINOR | FIXED | concepts 增加 `prior_status`；YAML 同步在启动和文件变更时触发；id 消失记 prior_status 并置 orphaned，回来恢复并清空。 |
| N-10 | MINOR | FIXED | session_questions 增加 `question_bank_id` 与 `question_role: new|review|misconception`；mastery 只算 `question_role=new`。 |
| N-11 | MINOR | FIXED | 预算合计 2.3 秒（ASR .6 + LLM .8 + TTS .7 + 抖动 .2），目标 ≤2.5 秒；待定区新增延迟目标与 4 秒回退行。 |
| N-12 | MINOR | FIXED | 周数按 40-56 小时重算为 13-28 周；三个月最多 36 小时，只能覆盖 d0+v0，周投入 3 小时时可覆盖 v1 下限；d0 拆成 d0a 连通性 2-3h 与 d0b 形象音频 6-9h。 |
| N-13 | MINOR | FIXED | v0 阶段补“最小概念确认页”。 |
| N-14 | MINOR | FIXED | 首批抽查 10 道，每晚抽查 2 道（或全部 5 道）；首批约 10 分钟、每晚约 2 分钟，算内容时间。 |
| N-15 | MINOR | FIXED | 月度复盘明确不记会话、不算 24/30、用额外 20 分钟，不占当天预算。 |
| N-16 | MINOR | FIXED | 80 分均分的分母定义为“至少有一次 daily 分数的概念”；proposed/skipped/orphaned 和无分数 known 不计入。 |
| N-17 | MINOR | FIXED | 正文改为“按待定区当前占位”引用，不再单独硬写周工时。 |
| R1-04 | PARTIAL→FIXED | FIXED | 由 N-01 解决：review_due_at 为唯一真相源，出队清空。 |
| R1-10 | PARTIAL→FIXED | FIXED | 由 N-06 解决：短答与讲解分开计量；Q4 删除“ASR 2.5 秒”的混用表述。 |
| R1-11 | PARTIAL→FIXED | FIXED | 由 N-12 解决：工时重算、d0 拆分、三个月覆盖范围写清。 |
| R1-16 | PARTIAL→FIXED | FIXED | 输入段落改为 ASR 原文落 `asr_text`、纠错后可编辑文本落 `explained_text`；术语纠错归属明确。 |
| R1-19 | PARTIAL→FIXED | FIXED | 待定区新增“中间目标节点数 20（占位）”，正文引用成立。 |
| R1-28 | PARTIAL→FIXED | FIXED | 外部 API 列表增加 Embedding（待定区，本地或 API，由 BFF 调用）；core 通过 BFF 调用。 |
| R1-33 | PARTIAL→FIXED | FIXED | 删除 Q4 的“MiMo（云端）”断言；托管方式只在待定区。 |
| R1-34 | PARTIAL→FIXED | FIXED | 3 分钟标准改为能力标准，每周综合场抽 1 个概念验证录音；不要求每个概念留录音。 |

## 未修 / 延后

- 没有未处理的阻塞项。
- 仍需用户提供的：四个 API 接口/鉴权/音频格式/流式、embedding 模型、材料与节点数量、每周实际工时、口型精度。全部在待定区。
- 仍需实测的：DeepSeek Flash 评分一致性（20 条对照、75% 门槛）、短答 2.5 秒与讲解 60 秒转写、ASR 80% 术语准确率。
