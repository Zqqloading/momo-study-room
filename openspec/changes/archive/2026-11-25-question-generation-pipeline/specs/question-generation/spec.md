# Spec Delta

## Purpose

定义计分题如何从本地已确认知识库现场生成、校验、溯源与回退，保证题目可审计、可复现且不依赖外部补充。

## ADDED Requirements

### Requirement: 每场固定五型五题

每场会话 SHALL 生成 5 道题，题型为概念理解、业务运用、取舍权衡、成本风险、综合判断各 1 道；槽位、题型与概念归属 MUST 由程序计划固定，生成模型 MUST NOT 自行改题型或配比。

#### Scenario: 无到期复习
- **WHEN** 当天没有到期复习且有可出主概念
- **THEN** 5 个槽位全部属于主概念，题型五型各 1

#### Scenario: 有到期复习
- **WHEN** 当天有到期复习且有可出主概念
- **THEN** 主概念承担概念、业务、取舍 3 题，复习概念承担成本、综合 2 题

#### Scenario: 只有复习
- **WHEN** 没有可出主概念但有到期复习
- **THEN** 5 个槽位全部属于复习概念，题型五型各 1

#### Scenario: 复习概念与主概念相同
- **WHEN** 到期复习概念就是当天主概念
- **THEN** 5 题全考该概念，角色拆为 2 review + 3 new

### Requirement: 出题只读本地已确认知识库

出题生成 MUST 只使用本地已确认知识库（`material_chunks`、`concept_sources`、`concepts.yaml` 对应的概念）；MUST NOT 调用外部搜索/抓取、读取 `hot_items`，或把生成题写入 `question_bank`/seeds。

#### Scenario: 外部搜索不可用
- **WHEN** 出题时外部搜索 provider 未配置或不可用
- **THEN** 生成仍能完成，题目只引用本地材料

#### Scenario: 生成题不写题库
- **WHEN** 生成题落库
- **THEN** 只写 `session_questions`，`question_bank` 与 seeds 不变

### Requirement: 生成上下文主出处优先

每次生成 SHALL 先取概念主出处父块作为 `[1]`，再追加按父块去重的检索结果 `[2..]`；检索为空时只保留主出处；主出处也没有时 MUST 判定生成失败。

#### Scenario: 检索有命中
- **WHEN** 概念主出处与检索结果都存在
- **THEN** 上下文 `[1]` 是主出处，后续是去重后的检索父块

#### Scenario: 检索为空
- **WHEN** 检索没有返回任何块
- **THEN** 上下文只含主出处，生成继续

#### Scenario: 主出处也缺失
- **WHEN** 检索为空且概念没有可用的主出处块
- **THEN** 不生成题目，走回退

### Requirement: 生成契约与程序五档 rubric

生成模型 SHALL 为每个槽位返回题干、参考答案、`must_have`、`red_flags`、`source_ref` 与 `source_excerpt`；系统 MUST 按 0/40/70/90/100 生成五档 rubric；`source_excerpt` MUST 是 `source_ref` 对应上下文的逐字子串。

#### Scenario: 合法输出
- **WHEN** 模型返回 5 个槽位的完整字段
- **THEN** 每题 `source_excerpt` 逐字命中对应上下文，`must_have` 2–5 条、`red_flags` 1–3 条，程序生成五档 rubric

#### Scenario: 摘录不是原文
- **WHEN** `source_excerpt` 不是对应上下文的逐字子串
- **THEN** 该槽位校验失败，进入修复

#### Scenario: 字段缺失
- **WHEN** 任一题缺参考答案、`must_have` 或 `red_flags`
- **THEN** 该槽位校验失败，进入修复

### Requirement: 生成校验与一次修复

生成结果 SHALL 校验 5 个槽位、题型与计划一致、逐字溯源、业务视角禁词与题内去重；任一硬失败 MUST 触发一次修复，只重写失败槽位；修复后仍失败 MUST 回退。

#### Scenario: 一次修复成功
- **WHEN** 首轮有 1–2 个槽位溯源失败
- **THEN** 只重写失败槽位，复验通过后整场可用

#### Scenario: 修复仍失败
- **WHEN** 修复后仍有槽位不合法
- **THEN** 整场回退旧题库，不混用生成题与旧题

#### Scenario: 业务视角禁词
- **WHEN** 题干出现代码实现禁词
- **THEN** 该槽位判硬失败，进入修复

### Requirement: 生成失败回退旧题库并标记

生成或修复失败时，Coach SHALL 从 `question_bank` 取题回退，并把该场标记为 fallback；回退题 MUST NOT 冒充生成题，MUST NOT 计入生成题验收。

#### Scenario: 回退可见
- **WHEN** 生成失败走旧题库
- **THEN** 题目生成元数据标记 fallback，前端显示“旧题回退”

#### Scenario: 回退题不参与生成验收
- **WHEN** 导出出题验收样本
- **THEN** 只包含生成元数据 `origin=generated` 的题

### Requirement: 每题可溯源

每道生成题 MUST 持久化 `source_chunk_id`、`source_url`、`source_excerpt` 与生成元数据；`source_excerpt` MUST 逐字且语义上支撑题干。作答前 MUST 只展示题型，评分后 MUST 展示出处。

#### Scenario: 作答前
- **WHEN** 题目下发
- **THEN** `question` 事件带题型，不带出处

#### Scenario: 评分后
- **WHEN** 该题评分完成
- **THEN** `score` 事件与验收卡带 `source_url` 与 `source_excerpt`

#### Scenario: 溯源审计
- **WHEN** 从 `session_questions` 回放
- **THEN** 能定位到 `chunk_id`、材料 URL 与逐字摘录
