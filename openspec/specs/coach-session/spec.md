# coach-session Specification

## Purpose
定义一场每日学习会话的行为契约：从选题、逐题评分到结算，保证分数、mastery 与复习到期时间可回放、可恢复；不覆盖语音输入与音频播放。

## Requirements

### Requirement: 会话启动按 planned 题数选题

Coach SHALL 在 `start` 时构建 SessionPlan 并调用出题生成；`planned` MUST 等于实际插入的 `session_questions` 行数。每场 5 题：最多 2 道复习 + 3 道新概念；复习只取 1 个最逾期概念；生成失败 MUST 回退旧题库，不阻塞会话。

#### Scenario: 无复习题的配比
- **WHEN** 没有到期复习且存在可出的新概念
- **THEN** 5 题全部属于该主概念，题型为概念、业务、取舍、成本、综合各 1

#### Scenario: 有一道到期复习
- **WHEN** 有到期复习且有可出的新概念
- **THEN** 复习概念出 2 题（成本、综合），主概念出 3 题（概念、业务、取舍），planned 为 5

#### Scenario: 有两道到期复习
- **WHEN** 有两个以上到期复习概念
- **THEN** 只取最逾期 1 个概念出 2 题，其余复习顺延，planned 仍为 5

#### Scenario: 没有新概念可出
- **WHEN** 没有可出的新概念且只有到期复习
- **THEN** 允许 review-only 会话，`kind=review`，5 题全部考复习概念、五型各 1

#### Scenario: 生成失败回退
- **WHEN** 生成与修复都失败
- **THEN** 从旧题库取 5 题，题目标记 fallback，会话照常开始

### Requirement: 逐题即时评分

每道题提交后 SHALL 立即评分并 commit。生成题 MUST 全部按开放题调用 Scorer；旧题库回退的辨析题 MUST 用 `answer_key` 本地判分（正确 100，错误 40）。开放题失败重试一次，仍失败则该题 `score=NULL`、`feedback="本题未评分"`，会话继续。

#### Scenario: 开放题评分成功
- **WHEN** 生成题提交且 Scorer 返回合法 JSON
- **THEN** 该题写入 score 与一句 why，并推送 `score` 事件

#### Scenario: 开放题评分重试后失败
- **WHEN** Scorer 第一次返回坏 JSON、第二次仍失败
- **THEN** 该题 score 为 NULL、feedback 为“本题未评分”，下一题照常进行

#### Scenario: 辨析题本地判分
- **WHEN** 用户提交旧题库回退的辨析题答案
- **THEN** 不调用 Scorer，按 `answer_key` 得到 100 或 40 并立即落库

#### Scenario: 辨析题答错朗读解析
- **WHEN** 回退辨析题答错
- **THEN** 反馈文本与语音包含正确答案与解析，解析要说明原因，不能只复述正确选项

#### Scenario: 辨析题答对不朗读
- **WHEN** 回退辨析题答对
- **THEN** 只显示“答对了”，不朗读反馈语音

### Requirement: 题型感知评分与反背诵

评分 SHALL 按题型应用封顶规则：只背定义或复述材料原句最高 60；业务运用没有具体动作/场景映射最高 60；取舍权衡没有明确选择、代价或反转条件最高 69；成本风险少于两项成本/风险或无兜底最高 69；综合判断没有决策、依据或边界最高 69。`session_misconception` MUST 为 null 或 `{text, concept_key}` 对象；字符串 MUST 视为解析失败并重试一次。

#### Scenario: 背诵定义被封顶
- **WHEN** 回答只复述材料原句，没有业务后果或场景判断
- **THEN** 该题得分不高于 60

#### Scenario: 取舍缺关键要素被封顶
- **WHEN** 取舍题回答没有说明放弃什么或反转条件
- **THEN** 该题得分不高于 69

#### Scenario: 误解字段形状非法
- **WHEN** 评分返回的 `session_misconception` 是字符串
- **THEN** 该次评分判为解析失败，重试一次

#### Scenario: 完整业务回答
- **WHEN** 回答给出业务场景、具体动作、代价或边界
- **THEN** 该题可进入 90–100 档

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

同一场会话内 MUST NOT 出现重复题目。生成题 MUST 把上一场同概念题干作为 negative examples 传给生成器；回退题 MUST 按从未出过优先、其次最久未出轮换。选题 MUST NOT 依赖随机数，保证可复现。

#### Scenario: 同一场不重复
- **WHEN** 生成一场 5 题
- **THEN** 5 道题互不重复

#### Scenario: 连续两场集合不同
- **WHEN** 用户连续开始两场同概念学习
- **THEN** 第二场把第一场题干作为 negative examples，题目集合不同

#### Scenario: 未出过的题优先
- **WHEN** 生成失败走旧题库且还有从未出过的题
- **THEN** 优先选从未出过的题

#### Scenario: 回退题最久未出轮换
- **WHEN** 旧题库的题都已经出过
- **THEN** 按最久未出轮换，不依赖随机数

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

BFF SHALL 通过 WebSocket 暴露会话消息：客户端发送 `session_start`、`session_resume`、`answer`、`skip`、`finish`；`text` / `audio` MAY 带可选 `intent`（`teach` 或 `clarify`）。服务端推送 `session_ready`、`question`、`transcript`、`score`、`probe`、`teach_reply`、`feedback_end`、`session_result`、`session_expired`；agent 回合 MAY 推送 `agent_status`。`question` MUST 带 `index`、`total`（等于 planned）与 `question_type`；`score` MUST 带 `question_type`、`source_url`、`source_excerpt`，重复提交时 MUST 带 `duplicate=true`；`session_result` 的 `scores` MUST 带题型与出处；作答前的 `question` MUST NOT 带出处。`audio_chunk` MUST 带 `utterance`（`feedback`、`question` 或 `teach`）与递增 `seq`。

#### Scenario: 文本完成一场
- **WHEN** 客户端依次发送 `session_start` 与 5 条 `answer`
- **THEN** 每答一题收到 `score`，最后收到 `session_result`，DB 可回放全部题目、题型与出处

#### Scenario: 提前结束
- **WHEN** 客户端在 planned 题未答完时发送 `finish`
- **THEN** 收到 status 为 partial 的 `session_result`

#### Scenario: 作答前不泄露出处
- **WHEN** 服务端推送 `question`
- **THEN** 事件只有题型，没有 `source_url` 或 `source_excerpt`

#### Scenario: 评分后显示出处
- **WHEN** 服务端推送 `score`
- **THEN** 事件带 `question_type`、`source_url` 与 `source_excerpt`

#### Scenario: 教学意图
- **WHEN** 客户端发送带 `intent=teach` 的 `text`
- **THEN** 服务端走教学回合并推送 `teach_reply`，不推送 `score`

### Requirement: session_ready 带学习单元信息

`session_ready` MUST 带只读 `unit` 字段：`kind`、`main`（主概念 id/name 或 null）、`review`（复习概念 id/name 或 null）。`main` MUST 来自本场 `role=new` 的概念，`review` MUST 来自 `role=review` 的概念；start 与同日 `session_resume` 返回的 `session_ready` MUST 都带该字段。字段为加法，MUST NOT 改变既有事件顺序或必填字段。

#### Scenario: daily 有复习

- **WHEN** 会话包含主概念与复习概念
- **THEN** `unit.main` 是主概念，`unit.review` 是复习概念，名称来自 concepts.yaml

#### Scenario: review-only

- **WHEN** 会话只有复习题
- **THEN** `unit.main=null`，`unit.review` 是复习概念

#### Scenario: 同日恢复

- **WHEN** 用户断开后同日发送 `session_resume`
- **THEN** 返回的 `session_ready.unit` 与开始时的主/复习概念一致

#### Scenario: 概念名缺失

- **WHEN** 概念不在 concepts.yaml 中
- **THEN** 名称回退为 concept id，不抛错

### Requirement: session_result 带本单元概念摘要

`session_result` MUST 带 `concepts` 数组，每项包含概念 id、name、`roles`、`new_score`、`review_score`、`mastery_before`、`mastery_after`、对应标签、`mastery_updated` 与结算后的 `review_due_at`。`new_score`/`review_score` MUST 只聚合已评分题；`mastery_before` MUST 在结算事务前读取；`mastery_after` 与 `review_due_at` MUST 反映结算后的状态。既有 `mastery` map、`scores` 与 `review_due_at` 字段 MUST 保留。

#### Scenario: completed daily

- **WHEN** 一场 daily 全部作答并评分成功
- **THEN** 每个概念返回 before/after、本场 new/review 均分、`mastery_updated` 与结算后的 due

#### Scenario: partial

- **WHEN** 用户在未答完时提前结束
- **THEN** 摘要仍返回概念与已评分题均分，`mastery_updated=false`，mastery 前后相同

#### Scenario: unscored

- **WHEN** 所有题都没有评上分
- **THEN** 摘要中 `new_score`/`review_score` 为 null，`mastery_updated=false`，答案文本与 `scores` 语义不变

#### Scenario: 同概念两角色

- **WHEN** 主概念与复习概念相同
- **THEN** 该概念 `roles=["new","review"]`，同时给出新题与复习均分；mastery 只按 new 更新，due 只按 review 更新

#### Scenario: 不额外写入

- **WHEN** 生成摘要
- **THEN** 不新增数据库写入，`mastery_updated=true` 仅当既有 mastery 规则实际更新该概念

### Requirement: 重复作答幂等重放

同一 `question_id` 已评分后再次提交，服务端 MUST NOT 重新评分、覆盖答案或新增 `session_questions` 行；MUST 返回已有分数与当前下一题/结算，`score` 事件 MUST 带 `duplicate=true`。提交不同文本同样 MUST NOT 覆盖第一次答案。题目不属于该会话时 MUST 返回错误且不写库。

#### Scenario: 双击提交
- **WHEN** 同一题在已评分后立即再次提交
- **THEN** 只产生一次评分写入，第二次返回已有分数与 `duplicate=true`

#### Scenario: 不同文本重复提交
- **WHEN** 已评分后提交了不同文本
- **THEN** 保留第一次答案与分数，不覆盖

#### Scenario: 重复结束
- **WHEN** 会话已结束后再次发送 `finish`
- **THEN** 不重复结算，返回 `session_finished` 错误

### Requirement: 会话内教学/澄清回合

会话进行中，客户端 MAY 发送带 `intent=teach` 或 `intent=clarify` 的 `text`；服务端 MUST 进入对应 agent 回合，MUST NOT 评分、推进题目或写 `session_questions`。回合结束 MUST 推送 `teach_reply`，当前题保持不变，用户可继续作答；教学/澄清回合 MUST NOT 改变 `agent_sessions` 的题目游标。

#### Scenario: 讲讲当前概念
- **WHEN** 用户在会话中发送 `intent=teach`
- **THEN** 收到 `teach_reply`，当前题、分数与进度不变

#### Scenario: 澄清题意
- **WHEN** 用户发送 `intent=clarify`
- **THEN** 收到题意解释，不评分、不推进

#### Scenario: 教学后继续作答
- **WHEN** 教学回合结束
- **THEN** 当前题仍可提交，评分流程与原来一致

### Requirement: 教学/澄清的上下文边界

教学/澄清的 StepBrief MUST 含当前题与当前概念，MAY 含上一道已评分题的题干、回答、分数、`why` 与出处；MUST NOT 含未来题目、未作答的 rubric、`reference_answer` 或 `answer_key`。教学历史 MUST 只保留当前连接最近 6 条，MUST NOT 写入 `conversation_messages` 或 `session_questions`。

#### Scenario: 解释上一题分数
- **WHEN** 用户问「刚才那题为什么只有 60 分」
- **THEN** 回合能看到上一题的题干、回答、分数、why 与出处，但不含 rubric

#### Scenario: 不泄露答案
- **WHEN** 用户要求「直接告诉我标准答案」
- **THEN** 回复不包含未作答的 rubric、答案键或参考答案

#### Scenario: 刷新后历史丢失
- **WHEN** 用户在会话中刷新页面后继续提问
- **THEN** 当前题可恢复，但之前的教学对话历史不要求恢复

### Requirement: 客户端刷新后恢复会话

客户端 MUST 在 `session_ready` 时持久化 `session_id`；页面就绪时若存在值 MUST 发送 `session_resume`。收到 `session_result`、`session_expired` 或用户结束本场时 MUST 清除该值。刷新后 MUST 回到第一道未作答题；跨日 MUST 清空并提示会话过期。

#### Scenario: 刷新中途恢复
- **WHEN** 用户答完 2 题后刷新页面
- **THEN** 页面自动发送 `session_resume` 并展示第 3 题

#### Scenario: 结束后清除
- **WHEN** 本场收到 `session_result`
- **THEN** 本地 `session_id` 被清除，刷新后不回放已结束会话

#### Scenario: 跨日过期
- **WHEN** 用户次日刷新并恢复旧会话
- **THEN** 收到 `session_expired`，清空本地值并提示开始新会话

### Requirement: 开场生活 + 记忆

`session_ready.intro` MUST 按“生活句（≤60 字） → 记忆块（≤300 字） → 原进度 intro”拼接；前导合计 MUST ≤360 字。事件 `intro` 与开场 TTS MUST 使用同一份文本。没有生活句或没有记忆时 MUST 跳过对应段；`session_resume` MUST NOT 重播开场。

#### Scenario: 生活 + 记忆

- **WHEN** 当天有生活素材且有 2 条合格记忆
- **THEN** `intro` 以生活句开头，随后是记忆块与进度 intro

#### Scenario: 只有生活

- **WHEN** 记忆为空但生活池有当日素材
- **THEN** `intro` = 生活句 + 原进度 intro

#### Scenario: 恢复

- **WHEN** 用户同日 `session_resume`
- **THEN** 不返回 `intro`

### Requirement: 评分反馈措辞

评分提示词 MUST 只新增一句“反馈只评价答案，不评价用户本人；不讽刺、不贬低”。分档、题型封顶、0-100 校验、JSON 契约与参考答案流程 MUST 逐字保持不变；MUST NOT 因这句话改变分数。

#### Scenario: 措辞约束

- **WHEN** 用户答错
- **THEN** `why` 只评价答案，不评价用户本人

#### Scenario: 评分口径不变

- **WHEN** 同一答案在改动前后评分
- **THEN** 分档、封顶和分数不变

### Requirement: session_ready 带情绪

`session_ready` MUST 带 `emotion: {comfort, energy, tone}`；没有情绪数据时 MUST 返回中间态。该字段 MUST NOT 改变题目、评分、复习或结算行为。

#### Scenario: 开始单元

- **WHEN** 用户开始每日或复习单元
- **THEN** `session_ready` 含当前 emotion
