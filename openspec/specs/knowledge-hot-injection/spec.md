# knowledge-hot-injection Specification

## Purpose

承接会话中出现但知识库未覆盖的知识点，使其可即时检索，同时保证未核实内容不进入已核实知识库；晋升是进入主库的唯一路径。

## Requirements

### Requirement: Capture only user-side text

热项捕获 SHALL 只接受用户输入或会话问题文本；MUST NOT 存储 agent 生成内容；相同 `content_hash` SHALL 去重为一行并累加 `seen_count`。

#### Scenario: 重复捕获

- **WHEN** 同一文本再次捕获
- **THEN** 不新增行，`seen_count` 加一，`last_seen` 更新

#### Scenario: agent 生成内容

- **WHEN** 捕获请求来自 agent 生成的回答文本
- **THEN** 请求被拒绝，不写入 `hot_items`

### Requirement: Hot items expire

每条热项 SHALL 带 `expires_at`（默认捕获后 7 天）；状态非 `hot` 或已过期的行 SHALL NOT 出现在检索结果中；过期扫描 SHALL 把仍为 `hot` 的过期行置为 `expired`。

#### Scenario: 过期热项

- **WHEN** 查询时某热项 `expires_at` 已过
- **THEN** 它不返回；下次扫描后状态为 `expired`

#### Scenario: 晋升后的热项

- **WHEN** 某热项已 `promoted`
- **THEN** 热项检索不再返回它

### Requirement: Hot results are isolated

热项 SHALL NOT 写入 `concept_sources`；SHALL NOT 作为计分题的出处；检索结果 SHALL 带 `verified=false` 与年龄，供调用方在 prompt 中标注未核实。

#### Scenario: 计分题引用热项

- **WHEN** 题目草稿的出处只能指向热项
- **THEN** 不生成该题，退回同概念旧题

#### Scenario: 正常检索

- **WHEN** 热项命中
- **THEN** 结果标记未核实，且 `concept_sources` 无新增行

### Requirement: Promotion is the only path into the KB

晋升 SHALL 把热项写成 `materials/inbox/<slug>.md` 并回填 `material_id`，再走正常 ingest；MUST NOT 直接写 `materials` 或 `material_chunks`；文件写失败时 MUST NOT 更新热项状态。

#### Scenario: 晋升成功

- **WHEN** 对一个 `hot` 状态热项执行晋升
- **THEN** 生成 inbox 文件、状态置 `promoted`、`material_id` 回填

#### Scenario: 文件写失败

- **WHEN** inbox 目录不可写
- **THEN** 命令失败，热项仍为 `hot`

### Requirement: Hot CLI

系统 SHALL 提供 `core.hot capture|list|discard` 命令；`list` SHALL 只列出未过期且状态为 `hot` 的条目，并显示 `seen_count` 与年龄。

#### Scenario: 列出热项

- **WHEN** 执行 `core.hot list`
- **THEN** 只显示未过期 `hot` 条目

#### Scenario: 丢弃热项

- **WHEN** 执行 `core.hot discard <id>`
- **THEN** 状态置 `discarded`，后续检索不返回
