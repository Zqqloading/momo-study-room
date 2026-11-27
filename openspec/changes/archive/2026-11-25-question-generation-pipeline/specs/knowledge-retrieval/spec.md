# Spec Delta

## ADDED Requirements

### Requirement: 出题检索按概念取主出处与 top5 父块

出题检索 SHALL 用概念名、别名与 `plain_def` 组成 query，走既有 Retriever（FTS5 trigram top20 + 向量 top20 + RRF k=60）；结果 MUST 先返回概念主出处块，再返回按父块去重的 top5 父块；每条结果 MUST 带 `chunk_id` 与 `parent_chunk_id`。自由对话检索契约不变。

#### Scenario: 检索有命中
- **WHEN** 概念主出处与检索结果都存在
- **THEN** 结果第一条是主出处父块，后续是去重后的检索父块，最多 5 条

#### Scenario: 检索为空
- **WHEN** FTS 与向量都没有命中
- **THEN** 只返回概念主出处块

#### Scenario: 主出处也缺失
- **WHEN** 检索为空且概念没有可用的主出处块
- **THEN** 返回空列表，调用方回退旧题库

#### Scenario: 自由对话不变
- **WHEN** 用户自由对话提问
- **THEN** 仍按用户原文检索、取 top3 父块，行为与本 change 前一致
