# persona Specification

## Purpose

定义 MOMO 的可编辑设定集：四类人设条目、生活素材池、硬编码教学纪律；人设只影响对话口吻与互动方式，不进入评分、出题、抽取。

## Requirements

### Requirement: 设定集加载与校验

系统 SHALL 从 `persona.yaml` 读取 `entries` 与 `life_pool`。`version` MUST 为 1；`entries` MUST 是对象列表，每条有唯一 `id`、`category`（`who|voice|taboo|learn`）、非空 `text`（≤120 字）与布尔 `enabled`；启用条目合计 MUST ≤1200 字。`life_pool.items` MUST 有唯一 `id`、非空 `text`（≤60 字）与布尔 `enabled`。未知顶层键与未知条目字段 MUST 报错。文件不存在时 MUST 使用内置默认人设；文件存在但格式错时 MUST 启动失败并指出坏节点。

#### Scenario: 正常加载

- **WHEN** `persona.yaml` 含 22 条 entries 与 30 条 life items
- **THEN** 启动成功，四类条目与生活池都可用

#### Scenario: 全部关闭

- **WHEN** 22 条 entries 全部 `enabled: false`
- **THEN** PERSONA 块为空，纪律块仍然注入

#### Scenario: 格式损坏

- **WHEN** `version` 不是 1、`text` 超长、`id` 重复或出现 `discipline` 键
- **THEN** 启动失败，错误信息包含坏节点

### Requirement: 人设注入面

PERSONA 块 MUST 注入自由对话（含 agent）、会话内教学与澄清；MUST NOT 注入评分、出题、概念抽取、probe 或确定性开场模板。条目 MUST 第一人称、按 WHO → VOICE → TABOO → LEARN 分组；关闭的条目不出现。

#### Scenario: 自由对话带人设

- **WHEN** 用户在没有会话时发文字或语音
- **THEN** 系统提示含 PERSONA 块，不含 LIFE 块

#### Scenario: 评分不带人设

- **WHEN** 系统调用 Scorer
- **THEN** 评分提示词没有人设条目，只有评分规则与新增的反馈措辞约束

#### Scenario: probe 不带人设

- **WHEN** 用户说“知道了”触发 probe
- **THEN** probe 系统提示不加 PERSONA 块

### Requirement: 教学纪律硬编码

系统 MUST 在代码中维护 D1-D5：不会就说不会、不编造引用、评分不许注水、题目数量严格按规范、不主动替用户答题。对话面 MUST 注入 D1/D2，教学面 MUST 再加 D5；评分面 MUST 保持 D3 与 0-100 校验；出题面 MUST 保持 D2/D4；抽取面 MUST 保持 D2。`persona.yaml` MUST NOT 提供修改纪律的字段。

#### Scenario: 人设不能改纪律

- **WHEN** `persona.yaml` 顶层出现 `discipline` 或 `rules`
- **THEN** 启动失败

#### Scenario: 全关仍有纪律

- **WHEN** 所有人设条目关闭
- **THEN** 对话面仍注入 D1/D2（教学面再加 D5）

### Requirement: 生活素材只在单元开场

系统 SHALL 从启用的 `life_pool.items` 按 `date.toordinal() % len(enabled)` 取一条；同一天稳定，相邻两天不同（启用条目大于 1 时）。素材 MUST 只在学习单元开始注入一句；MUST NOT 注入自由对话、`session_resume` 或系统提示词。池子关闭/空池时 MUST 返回空。文件缺失时使用内置 30 条；格式错时启动失败。

#### Scenario: 同日稳定

- **WHEN** 同一天连续开始两个单元
- **THEN** 使用同一条生活素材

#### Scenario: 自由对话不注入

- **WHEN** 用户在没有会话时闲聊
- **THEN** 回复提示词不含生活素材

#### Scenario: 恢复不重播

- **WHEN** 用户发送 `session_resume`
- **THEN** 不返回生活句
