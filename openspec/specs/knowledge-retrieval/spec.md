# knowledge-retrieval Specification

## Purpose
定义知识检索在自由对话里的行为：用户提问先查材料，命中就带出处回答，没命中明确说明；不改动出题检索的既有契约。

## Requirements

### Requirement: 自由对话先检索材料

自由对话 SHALL 在调用 LLM 前用用户原文检索材料；查询 MUST 走既有 `Retriever`（FTS5 trigram top20 + 向量 top20 + RRF k=60），最终取 top3 父块。命中结果 MUST 作为材料段注入系统提示，并要求回答引用编号。

#### Scenario: 材料内问题
- **WHEN** 用户问「模型自作主张是什么」且材料里有相关块
- **THEN** 回答包含材料内容与 `[1]` 引用，`reply` 带非空 `sources`

#### Scenario: 材料外问题
- **WHEN** 用户问「什么是区块链」且材料里没有相关块
- **THEN** 回答说明「材料里没有」，`reply.sources` 为空

### Requirement: 无命中判定

FTS 命中 MUST 视为有依据；否则最高向量余弦 MUST 不低于 `RETRIEVAL_MIN_COSINE`（默认 0.35）才视为有依据。teach 模式无命中时，服务端 MUST 在回答前加「材料里没有直接讲到。」，MUST NOT 只依赖模型自觉。

#### Scenario: 关键词命中但余弦低
- **WHEN** 检索结果包含 FTS 命中
- **THEN** 视为有依据，正常注入材料

#### Scenario: 双路都弱
- **WHEN** FTS 无命中且最高余弦低于阈值
- **THEN** 不注入材料，teach 模式加确定性前缀

### Requirement: 中文短词回退

关键词路 SHALL 对少于 3 个字符的词做子串回退，MUST 并入同一关键词臂，MUST NOT 新增独立 RRF 路。

#### Scenario: 两个字的术语
- **WHEN** 用户问「工具」且材料里有「工具调用」
- **THEN** 关键词路返回该块，不因 trigram 限制返回空

### Requirement: 引用落库

`reply` 事件 MUST 带 `sources`（序号、标题、URL、摘录）；助手消息 MUST 写入 `conversation_messages.sources_json`；`conversation_load` MUST 原样返回。

#### Scenario: 刷新后回看
- **WHEN** 用户刷新页面并加载同一对话
- **THEN** 助手消息仍显示原来的出处

### Requirement: 注入预算

每场自由对话 MUST 最多注入 top3 父块；每个父块 MUST 截断到约 800 字。

#### Scenario: 长父块
- **WHEN** 命中父块超过 800 字
- **THEN** 提示词里只放前 800 字并加省略号

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
