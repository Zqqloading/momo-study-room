# Spec Delta

## ADDED Requirements

### Requirement: 生活素材池来源与校验

系统 SHALL 从 `persona.yaml` 的 `life_pool` 读取生活素材。文件 MUST 是对象，`version` MUST 为 1，`life_pool.items` MUST 是对象列表；每条 MUST 有非空 `id` 与非空 `text`，`text` MUST 不超过 60 字，`id` MUST 唯一，`enabled` MUST 是布尔（缺省视为 true）。一条一句是写作规则；加载器只校验非空与长度，不解析句数。未知顶层键 MUST 报错；`entries` 可作为已知键保留但不校验、不注入。文件不存在时 MUST 使用内置 30 条默认池；文件存在但格式错时 MUST 启动失败并指出坏节点。

#### Scenario: 正常读取

- **WHEN** `persona.yaml` 含 30 条 `life_pool.items`，全部 `enabled: true`
- **THEN** 启动成功，池中有 30 条可用素材

#### Scenario: 文件缺失

- **WHEN** `CONTENT_DIR` 下没有 `persona.yaml`
- **THEN** 使用内置 30 条默认池，启动成功

#### Scenario: 格式损坏

- **WHEN** `version` 不是 1，或某条 `text` 超过 60 字，或 `id` 重复
- **THEN** 启动失败，错误信息包含坏节点或条目 id

#### Scenario: 未知键

- **WHEN** `persona.yaml` 顶层出现 `discipline` 等未知键
- **THEN** 启动失败，不静默忽略

#### Scenario: 单条关闭

- **WHEN** 某条素材 `enabled: false`
- **THEN** 该条不参与抽取，但仍在文件中保留

### Requirement: 按日期确定性抽取

系统 SHALL 只从启用的素材中按 `date.toordinal() % len(enabled)` 取一条。同一池子内容下，同一天多次调用 MUST 返回同一条；相邻两天 MUST 不同（启用条目大于 1 时）；抽取 MUST NOT 使用随机数、MUST NOT 写数据库、MUST NOT 依赖会话或对话 id。编辑池子属于配置变更，可能改变当日选择。池子关闭、没有启用条目或日期不合法时 MUST 返回空，不报错。

#### Scenario: 同日稳定

- **WHEN** 同一天连续开始两个学习单元
- **THEN** 两次使用同一条生活素材

#### Scenario: 次日变化

- **WHEN** 日期从 2026-11-26 变为 2026-11-27，池中启用条目大于 1
- **THEN** 取到的素材与前一天不同

#### Scenario: 关闭的条目不参与

- **WHEN** 池中只有 2 条启用，其余 `enabled: false`
- **THEN** 只在这 2 条之间按日期轮换

#### Scenario: 池子关闭或为空

- **WHEN** `life_pool.enabled: false`，或没有启用条目
- **THEN** 返回空，开场不注入生活句，会话照常开始

### Requirement: 只在单元开场注入一句

生活素材 MUST 只在学习单元开始（`session_ready`）时注入一句。BFF MUST 把它拼在 `StartedSession.intro` 之前，事件 `intro` 与开场 TTS MUST 使用同一份拼接文本；MUST NOT 注入自由对话、`session_resume`、`propose()` 预览或系统提示词。没有素材时 MUST 保持原 `intro` 不变。注入 MUST NOT 写会话、题目、分数或进度。

#### Scenario: 单元开始

- **WHEN** 用户点「开始今天的学习」，池中有当日素材
- **THEN** `session_ready.intro` 以该素材句开头，随后是原有进度开场；开场 TTS 读同一段文本

#### Scenario: 同日恢复

- **WHEN** 用户发送 `session_resume`
- **THEN** 返回的事件不包含生活素材，不重播开场

#### Scenario: 自由对话

- **WHEN** 用户在没有会话时发文字或语音闲聊
- **THEN** 回复提示词不包含生活素材

#### Scenario: 没有素材

- **WHEN** 池子关闭或当天没有可用素材
- **THEN** `session_ready.intro` 与改动前一致
