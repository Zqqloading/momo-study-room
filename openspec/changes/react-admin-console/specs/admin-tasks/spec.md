# Spec Delta

## Purpose

把知识摄取、知识重建和整体评测统一成可查询、可轮询、可恢复的长任务，避免管理请求同步等待 CLI，并为后台写操作留下统一审计入口。

## ADDED Requirements

### Requirement: 统一任务号与持久化

每个长任务 SHALL 拥有稳定的 `task_id`、`kind`、`status`、`params`、创建/开始/结束时间，并持久化；服务重启后 MUST 仍能通过 `task_id` 查询到任务记录。

#### Scenario: 提交后获得任务号

- **WHEN** 客户端提交一个合法的长任务
- **THEN** 响应包含 `task_id`，后续查询使用该 id

#### Scenario: 重启后仍可查询

- **WHEN** 服务重启后客户端用原 `task_id` 查询
- **THEN** 系统返回该任务记录，而不是 404

### Requirement: 任务提交契约

系统 SHALL 提供 `POST /api/admin/tasks`，接受 `kind` 与 `params`；合法请求 MUST 返回 202、`task_id` 与 `status=queued`；参数非法 MUST 返回 400；相同 `kind+params` 已在排队或执行时 MUST 返回已有任务号，不重复执行。

#### Scenario: 提交合法任务

- **WHEN** 客户端提交 `{"kind":"rebuild","params":{"fts_only":true}}`
- **THEN** 系统返回 202 与新的 `task_id`

#### Scenario: 参数非法

- **WHEN** 客户端提交未知的 `kind` 或缺少必填参数
- **THEN** 系统返回 400，不创建任务

#### Scenario: 重复提交

- **WHEN** 相同 `kind+params` 的任务仍在 `queued` 或 `running`
- **THEN** 系统返回已有 `task_id`，不新建任务

### Requirement: 任务轮询契约

系统 SHALL 提供 `GET /api/admin/tasks/{task_id}`，返回状态、进度、日志尾、结果与错误；响应 MUST 使用 `no-store`；未知任务 MUST 返回 404。

#### Scenario: 查询运行中的任务

- **WHEN** 客户端轮询一个 `running` 任务
- **THEN** 响应包含 `status`、`progress` 与 `log_tail`

#### Scenario: 查询终态任务

- **WHEN** 任务已进入 `succeeded`、`failed`、`cancelled` 或 `awaiting_review`
- **THEN** 响应包含终态，`succeeded` 带 `result`，`failed` 带 `error`

#### Scenario: 未知任务

- **WHEN** 客户端查询不存在的 `task_id`
- **THEN** 系统返回 404

### Requirement: 任务状态机与重启恢复

任务状态 SHALL 从 `queued` 进入 `running`，再进入 `succeeded`、`failed`、`cancelled` 或 `awaiting_review`；服务重启时 MUST 把遗留的 `running` 任务标为失败，`queued` 任务 MUST 重新入队。

#### Scenario: 重启时运行中任务

- **WHEN** 服务重启时存在 `running` 任务
- **THEN** 该任务变为 `failed`，错误说明服务在完成前重启

#### Scenario: 重启时排队任务

- **WHEN** 服务重启时存在 `queued` 任务
- **THEN** 该任务重新进入队列，继续等待执行

### Requirement: 任务执行安全

系统 SHALL 使用单 worker 顺序执行任务，通过子进程运行已验证的 CLI；每个任务 MUST 有超时；`params` MUST 经过路径与枚举白名单校验；系统 MUST NOT 接受原始命令字符串；日志 MUST 脱敏并限制长度。

#### Scenario: 路径穿越

- **WHEN** `ingest` 任务提交包含 `..` 或项目外绝对路径的 `path`
- **THEN** 系统返回 400，不启动子进程

#### Scenario: 超时

- **WHEN** 子进程超过该 kind 的超时时间
- **THEN** 系统终止子进程，任务变为 `failed`，错误说明超时

#### Scenario: 日志脱敏

- **WHEN** CLI 输出包含 API key 或 Authorization 值
- **THEN** 任务日志中对应值被替换为掩码

### Requirement: ingest 知识摄取任务

`ingest` 任务 SHALL 接受 `path`、`dry_run`、`emit_chunks`、`extract`、`confirm` 与 `out`；`path` MUST 位于 `materials/` 且后缀为 `.md` 或 `.html`；`dry_run=true` MUST NOT 写数据库；`extract=true` 且 `confirm=false` 时任务 MUST 以 `awaiting_review` 结束并返回候选文件路径；v1 MUST NOT 自动确认或自动重建索引。

#### Scenario: 干跑

- **WHEN** 客户端提交 `dry_run=true` 的 ingest 任务
- **THEN** 任务成功结束，材料、块和 `pipeline_runs` 均不新增

#### Scenario: 抽取后等待确认

- **WHEN** 客户端提交 `extract=true`、`confirm=false` 的 ingest 任务
- **THEN** 任务以 `awaiting_review` 结束，结果包含 `candidates_path`

#### Scenario: 路径不在 materials

- **WHEN** `path` 指向 `materials/` 之外
- **THEN** 系统返回 400，不创建任务

### Requirement: rebuild 知识重建任务

`rebuild` 任务 SHALL 接受 `fts_only`、`prune`、`model` 与 `dim`；任务 MUST 调用既有重建逻辑重建 FTS，并在非 `fts_only` 时补齐向量；embedding provider 不可用且未开启 `fts_only` 时 MUST 失败并给出可读错误。

#### Scenario: 只重建 FTS

- **WHEN** 客户端提交 `fts_only=true` 的 rebuild 任务
- **THEN** 任务完成，FTS 行被重建，且不调用 embedding provider

#### Scenario: 缺少 embedding provider

- **WHEN** 客户端提交 `fts_only=false` 且 embedding provider 未配置
- **THEN** 任务变为 `failed`，错误说明 provider 不可用

### Requirement: evaluate 整体评测任务

`evaluate` 任务 SHALL 接受 `suites`、`mode`、`inputs` 与 `out`；`suites` MUST 限于 `probe`、`asr`、`questions`、`scoring`、`agent`；缺少输入的 suite MUST 标记为 `skipped`；任务 MUST 只在所有实际执行的 suite 都通过时返回 `passed=true`；评测 MUST NOT 写内容库。

#### Scenario: 缺少 ASR 录音

- **WHEN** ASR 测试目录没有录音文件
- **THEN** 结果把 `asr` 标为 `skipped`，并给出原因

#### Scenario: 跳过不算通过

- **WHEN** 所有 suite 都是 `skipped`
- **THEN** 任务结果 `passed=false`

#### Scenario: 全部执行并通过

- **WHEN** 实际执行的 suite 全部通过
- **THEN** 任务结果 `passed=true`，并返回每个 suite 的报告路径

### Requirement: 任务列表与审计

系统 SHALL 提供 `GET /api/admin/tasks` 的分页列表，支持 `kind`、`status` 与时间过滤；任务记录 MUST 保留提交参数、结果、错误和日志尾；内容管线任务的结果 MUST 关联对应的 `pipeline_run_ids`，作为后台操作审计。

#### Scenario: 按状态筛选任务

- **WHEN** 客户端请求 `GET /api/admin/tasks?status=failed`
- **THEN** 响应只包含失败任务，并返回 `{data,total}`

#### Scenario: 关联管线运行

- **WHEN** 一个 ingest 或 rebuild 任务完成
- **THEN** 任务结果包含本次调用产生的 `pipeline_run_ids`
