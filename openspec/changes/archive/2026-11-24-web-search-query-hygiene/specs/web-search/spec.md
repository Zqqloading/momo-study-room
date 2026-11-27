# Spec Delta

## ADDED Requirements

### Requirement: 搜索 query 规范化

系统 MUST 在调用搜索前从用户原文剥离联网触发词（`联网`、`上网查`、`搜索一下`、`搜一下`、`查一下`），MUST 保留时效词（如 `最新`、`最近`）。时效问题 MUST 继续追加当前年月。剥离后没有剩余内容时 MUST NOT 调用搜索，直接视为没有网页结果。

#### Scenario: 显式联网请求
- **WHEN** 用户说「联网查一下 区块链 是什么」
- **THEN** 发给搜索的 query 不含「联网」「查一下」，只保留问题内容

#### Scenario: 时效问题
- **WHEN** 用户说「最新的 agent 版本」
- **THEN** query 保留「最新」，并追加当前年月

#### Scenario: 剥完为空
- **WHEN** 用户只说「联网查一下」，没有可检索内容
- **THEN** 不调用搜索，按没有网页结果处理

## MODIFIED Requirements

### Requirement: Tavily 搜索与结果预过滤

系统 SHALL 调用 Tavily 搜索，MUST 请求 `max_results=5`。注入提示词前 MUST 丢弃 content 为空或少于 80 字的结果，MUST 要求 content 与 query 至少共享一个 2 字以上的实义词项，词项提取 MUST 排除停用词与联网触发词，MUST 按 URL 去重，最终 MUST 最多取 top3。query 不含任何实义词项时 MUST 视为没有网页结果。

#### Scenario: 正常过滤
- **WHEN** Tavily 返回 5 条，其中 2 条 content 为空、1 条与问题无词面重叠
- **THEN** 最多 2 条进入提示词

#### Scenario: 重复 URL
- **WHEN** 多条结果指向同一 URL
- **THEN** 只保留一条，其余丢弃

#### Scenario: 全部不可用
- **WHEN** 所有结果都被过滤或 content 不足
- **THEN** 视为没有网页结果，不注入网页段

#### Scenario: 只有虚词重叠
- **WHEN** content 只与 query 的「不存在」「这个」「是什么」等停用词重叠，没有实义词重叠
- **THEN** 该结果被丢弃

#### Scenario: 无意义 query
- **WHEN** query 剥离触发词和停用词后没有实义词项
- **THEN** 所有结果都被丢弃，按没有网页结果处理，回答使用「联网也没查到」文案
