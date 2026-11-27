# Spec Delta

## ADDED Requirements

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
