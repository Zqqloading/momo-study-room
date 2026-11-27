# Spec Delta

## Purpose

定义一场每日学习会话的行为契约：从选题、逐题评分到结算，保证分数、mastery 与复习到期时间可回放、可恢复；不覆盖语音输入与音频播放。

## ADDED Requirements

### Requirement: 会话启动按 planned 题数选题

Coach SHALL 在 `start` 时选出一个会话的题目集合并逐题落库；`planned` MUST 等于实际插入的 `session_questions` 行数，而非固定 5。早期复习最多 2 道；新题按 0/1/2 early 三种配比补齐。

#### Scenario: 无复习题的配比
- **WHEN** 没有到期复习且存在可出的新概念
- **THEN** planned 为 5，构成为 2 recall + 2 discriminate + 1 apply

#### Scenario: 有一道到期复习
- **WHEN** 到期复习数量为 1
- **THEN** planned 为 5，构成为 1 review + 1 recall + 2 discriminate + 1 apply

#### Scenario: 有两道到期复习
- **WHEN** 到期复习数量不少于 2
- **THEN** planned 为 5，构成为 2 review + 1 recall + 1 discriminate + 1 apply

#### Scenario: 没有新概念可出
- **WHEN** 所有 active 概念的前置未满足，且只有到期复习
- **THEN** 允许 review-only 会话，`kind=review`，planned 等于早期复习数量

### Requirement: 逐题即时评分

每道题提交后 SHALL 立即评分并 commit。辨析题 MUST 用 `answer_key` 本地判分（正确 100，错误 40）；开放题 MUST 调用 Scorer，失败重试一次，仍失败则该题 `score=NULL`、`feedback="本题未评分"`，会话继续。

#### Scenario: 辨析题本地判分
- **WHEN** 用户提交辨析题答案
- **THEN** 不调用 Scorer，按 answer_key 得到 100 或 40 并立即落库

#### Scenario: 辨析题答错朗读解析
- **WHEN** 辨析题答错
- **THEN** 反馈文本与语音包含正确答案与解析，解析要说明原因，不能只复述正确选项

#### Scenario: 辨析题答对不朗读
- **WHEN** 辨析题答对
- **THEN** 只显示“答对了”，不朗读反馈语音

#### Scenario: 开放题评分成功
- **WHEN** Scorer 返回合法 JSON
- **THEN** 该题写入 score 与一句 why，并推送 score 事件

#### Scenario: 开放题评分重试后失败
- **WHEN** Scorer 第一次返回坏 JSON、第二次仍失败
- **THEN** 该题 score 为 NULL、feedback 为“本题未评分”，下一题照常进行

### Requirement: 开放题给出参考答案

开放题评分完成后，反馈 MUST 附带一句标准答案（不超过 80 字）；辨析题答错时 MUST 给出正确选项。标准答案 MUST 与评分在同一次调用中返回，不额外增加一次模型调用。

#### Scenario: 开放题评分后给出参考答案
- **WHEN** 开放题完成评分
- **THEN** 反馈文本包含“参考答案：…”且不超过 80 字

#### Scenario: 辨析题答错给出正确选项
- **WHEN** 辨析题判为错误
- **THEN** 反馈文本给出正确答案

### Requirement: 本场结束后回到初始状态

本场结果页主按钮 MUST 为「结束今天的学习」。点击后 MUST 回到初始界面：「开始说话」可用、「开始今天的学习」可用；MUST NOT 限制当天场次。

#### Scenario: 结果页按钮文案
- **WHEN** 本场结果展示
- **THEN** 主按钮显示「结束今天的学习」

#### Scenario: 结束本场回到初始
- **WHEN** 点击「结束今天的学习」
- **THEN** 回到初始界面，开始说话与开始今天的学习都可用

#### Scenario: 不限制当天场次
- **WHEN** 结束后立即再点「开始今天的学习」
- **THEN** 可以正常开始新一场

### Requirement: 题目去重与轮换

同一场会话内 MUST NOT 出现重复题目。选题 MUST 优先使用从未出过的题，其次使用最久未出的题；同一概念题库耗尽后 MUST 按最久未出轮换。选题 MUST NOT 依赖随机数，保证可复现。

#### Scenario: 同一场不重复
- **WHEN** 生成一场 5 题
- **THEN** 5 道题互不重复

#### Scenario: 连续两场集合不同
- **WHEN** 用户连续点击两次「开始今天的学习」
- **THEN** 第二场的题目集合与第一场不同

#### Scenario: 未出过的题优先
- **WHEN** 题库里还有从未出过的题
- **THEN** 下一场优先选中这些题

### Requirement: 会话中可手动切下一题

进入会话后主按钮 MUST 显示「下一题」且可点。当前题未作答时，点击 MUST 记该题未作答并进入下一题；已作答且反馈仍在播放时，点击 MUST 跳过剩余反馈、保留已评分并立即进入下一题；最后一题时 MUST 进入结算。

#### Scenario: 未作答就切题
- **WHEN** 用户没作答就点「下一题」
- **THEN** 该题记为未作答，展示下一题

#### Scenario: 反馈中切题
- **WHEN** 已评分但反馈语音仍在播放时点「下一题」
- **THEN** 停止剩余反馈，评分保留，立即展示下一题

#### Scenario: 最后一题切题
- **WHEN** 最后一题点「下一题」
- **THEN** 进入本场结算

### Requirement: 下一题在反馈之后展示

客户端 MUST 等上一题的反馈语音播放结束后，再展示下一题或本场结果；反馈结束与下一题展示之间 MUST 留出约 700ms 的停顿，避免听感上像连续说话。展示下一题时 MUST 清除上一题的评分与参考答案，MUST NOT 把上一题内容带入下一题页面。

#### Scenario: 反馈播放中不切题
- **WHEN** 反馈语音仍在播放
- **THEN** 当前题保持展示，评分与参考答案可见

#### Scenario: 反馈结束进入下一题
- **WHEN** 反馈语音播放结束
- **THEN** 展示下一题，评分区清空

#### Scenario: 最后一题后进入结果
- **WHEN** 最后一题的反馈语音播放结束
- **THEN** 展示本场结果卡

### Requirement: 自动结算与会话状态

会话 MUST 在已评分题数等于 planned 或没有未作答题时自动结算；`finish` 提前结束记为 partial。结算 MUST 在单事务内写 `sessions`、`concepts`、`session_concepts`，并把 `agent_sessions` 置为 finished；事务失败 MUST 整体回滚且保持未结算。

#### Scenario: 完成全部题目
- **WHEN** planned 题全部作答且评分成功
- **THEN** 状态为 completed，session_score 为已评分题均值，返回 `session_result`

#### Scenario: 提前结束
- **WHEN** 用户在仍有未作答题时发送 `finish`
- **THEN** 状态为 partial，已评分题保留

#### Scenario: 全部未评分
- **WHEN** 所有 planned 题都未拿到分数
- **THEN** 状态为 unscored，答案文本保留

#### Scenario: 结算事务失败
- **WHEN** 写结算事务时数据库报错
- **THEN** 回滚，会话保持未结算，允许重试

### Requirement: mastery 计算

mastery SHALL 取该概念最近三次 completed daily 中 `role=new` 题均分的五分之一并四舍五入；partial daily 与未评分题 MUST NOT 计入。

#### Scenario: 三次 completed daily
- **WHEN** 概念有最近三次 completed daily 的新题均分
- **THEN** mastery 为三者均值除以 20 后四舍五入

#### Scenario: partial 不计入
- **WHEN** 最近一次同概念会话是 partial
- **THEN** 该次分数不参与 mastery 计算

### Requirement: 次日复习调度

第一片只实现“次日 / 清空”：daily 的 concept_session_score 小于 80 且 `review_due_at` 为空时 MUST 置为次日；review 场得分均值小于 80 MUST 继续顺延次日，大于等于 80 MUST 清空 `review_due_at` 与 `review_started_at`。只有 active 概念 MUST 进入到期复习。

#### Scenario: 低分进入次日复习
- **WHEN** daily 场该概念得分 60 且 review_due_at 为空
- **THEN** review_due_at 为次日日期

#### Scenario: 复习达标清空
- **WHEN** review 场该概念得分均值 85
- **THEN** review_due_at 与 review_started_at 被清空

#### Scenario: 非 active 概念不进队列
- **WHEN** 概念状态为 skipped 且 review_due_at 已到期
- **THEN** 不进入 early 队列

### Requirement: 同日恢复

同日且 `agent_sessions` 为 active 时，`session_resume` MUST 返回第一道未作答题；没有未作答题时 MUST 直接结算。跨日或非 active MUST 返回 `session_expired` 并由客户端开新会话。

#### Scenario: 同日重连
- **WHEN** 用户断开后同日重连且会话仍为 active
- **THEN** 返回第一道未作答题，不新建会话

#### Scenario: 跨日重连
- **WHEN** 用户次日重连，旧会话仍为 active
- **THEN** 旧会话置 abandoned，返回 session_expired

### Requirement: 不知道

用户表达“不知道”时 MUST 记该题 0 分并继续下一题；反馈 MUST 使用当前概念的 `plain_def` 与 `source_excerpt` 组成不超过 60 字的短定义与一个例子，MUST NOT 调用 LLM。

#### Scenario: 回答不知道
- **WHEN** 文本或语音提交“不知道”
- **THEN** 该题 score 为 0，反馈为短定义加例子，进入下一题

### Requirement: 知道了触发一次 probe

用户第一次表达“知道了/懂了/明白了/会了”时 MUST NOT 评分或推进，而是生成一个追问并推送 `probe`；追问 MUST NOT 读取 `answer_key`。同一题最多一次 probe；第二次仍是纯确认时 MUST 记该题未作答并进入下一题。probe 失败 MUST 退回模板追问“能举个例子吗？”。

#### Scenario: 第一次纯确认
- **WHEN** 用户对当前题说“知道了”
- **THEN** 推送一个 probe 问题，题目与分数不变

#### Scenario: 第二次纯确认
- **WHEN** probe 之后用户再次说“知道了”
- **THEN** 该题记为未作答，进入下一题

#### Scenario: probe 生成失败
- **WHEN** 追问的 LLM 调用失败
- **THEN** 使用模板“能举个例子吗？”继续

### Requirement: 会话协议

BFF SHALL 通过 WebSocket 暴露会话消息：客户端发送 `session_start`、`session_resume`、`answer`、`skip`、`finish`；服务端推送 `session_ready`、`question`、`transcript`、`score`、`probe`、`feedback_end`、`session_result`、`session_expired`。`question` MUST 带 `index` 与 `total`（等于 planned）；`audio_chunk` MUST 带 `utterance`（`feedback` 或 `question`）与递增 `seq`。

#### Scenario: 文本完成一场
- **WHEN** 客户端依次发送 session_start 与 5 条 answer
- **THEN** 每答一题收到 score，最后收到 session_result，DB 可回放全部题目

#### Scenario: 提前结束
- **WHEN** 客户端在 planned 题未答完时发送 finish
- **THEN** 收到 status 为 partial 的 session_result
