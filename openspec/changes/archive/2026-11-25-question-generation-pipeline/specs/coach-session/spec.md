# Spec Delta

## MODIFIED Requirements

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

### Requirement: 会话协议

BFF SHALL 通过 WebSocket 暴露会话消息：客户端发送 `session_start`、`session_resume`、`answer`、`skip`、`finish`；服务端推送 `session_ready`、`question`、`transcript`、`score`、`probe`、`feedback_end`、`session_result`、`session_expired`。`question` MUST 带 `index`、`total`（等于 planned）与 `question_type`；`score` MUST 带 `question_type`、`source_url`、`source_excerpt`；`session_result` 的 `scores` MUST 带题型与出处；作答前的 `question` MUST NOT 带出处。

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

## ADDED Requirements

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
