# knowledge-ingestion Specification

## Purpose

定义材料从入库、切块、确认到索引维护的可观察行为，保证内容版本、出处完整性与派生索引可重建，并让确认结果可回滚。

## Requirements

### Requirement: Pipeline runs are recorded

每条管线运行（ingest、extract、confirm、reindex）SHALL 记录 kind、开始时间、结束时间、状态、输入标识、统计与错误摘要；进程异常退出遗留的 `running` 行 SHALL 在下次同类运行启动时置为 `failed`。

#### Scenario: 成功运行

- **WHEN** 管线正常完成
- **THEN** `pipeline_runs` 行状态为 `succeeded`，并带 `stats_json`

#### Scenario: 部分失败

- **WHEN** 管线完成但有文件因错误被跳过、或因缺失无法处理，或存在单块失败
- **THEN** 状态为 `partial`，统计里记录失败数

#### Scenario: 内容未变

- **WHEN** 材料哈希与库中一致，管线没有实际写入
- **THEN** 状态为 `succeeded`，统计 `skipped_unchanged=1`

#### Scenario: 异常退出

- **WHEN** 上次同类运行停留在 `running`
- **THEN** 本次启动先把残留行置为 `failed`、`error='aborted'`

### Requirement: Ingest emits version-correct chunks

`core.ingest --emit-chunks <path>` SHALL 输出与本次实际写入 `material_chunks` 同一 `material_version` 的 chunks.json；材料内容未变时 SHALL 按现有版本输出，MUST NOT 回落为 v1。

#### Scenario: 新材料

- **WHEN** 新材料带 `--emit-chunks` 入库
- **THEN** 输出文件中的块 id 全部为 `v1`

#### Scenario: 更新材料

- **WHEN** 材料哈希变化、写入版本 2 时带 `--emit-chunks`
- **THEN** 输出文件中的块 id 全部为 `v2`，不含任何 `v1` 块

#### Scenario: 材料未变

- **WHEN** 材料哈希与库中一致时带 `--emit-chunks`
- **THEN** 输出文件按库中现有版本生成，且不写新的块行

### Requirement: Confirm rejects dangling sources

`core.confirm` SHALL 在写库事务内校验每个候选的 `chunk_id` 存在于 `material_chunks`；任一缺失 SHALL 使整批失败，MUST NOT 写 `concepts.yaml`、`concepts.status` 或 `concept_sources`。

#### Scenario: 全部存在

- **WHEN** 所有 `chunk_id` 都能在 `material_chunks` 找到
- **THEN** 按原写序完成 YAML 与 DB 写入

#### Scenario: 存在悬空出处

- **WHEN** 任一 `chunk_id` 不在 `material_chunks`
- **THEN** 命令报错并列出缺失 id，YAML 与 DB 均无改动

### Requirement: Oversized tables split by row groups

超过子块上限的表格 SHALL 按行组切分，每组 SHALL 重复表头行，并标 `table_split`；代码块 SHALL NOT 切分，超限只标 `oversized`。

#### Scenario: 超长表格

- **WHEN** 单个表格超过 `CHILD_MAX`
- **THEN** 生成多个子块，每个子块都含表头，flag 含 `table_split`

#### Scenario: 超长代码块

- **WHEN** 单个代码块超过 `CHILD_MAX`
- **THEN** 它保持为一个子块，flag 含 `oversized`

### Requirement: Index maintenance reuses and prunes

`core.reindex` 补向量前 SHALL 按 `content_hash + model + dim + heading_path` 复用库中已有向量，命中时 MUST NOT 调用嵌入接口；`--prune` SHALL 删除 `chunk_embeddings` 与 `chunk_fts` 中 chunk_id 已不存在的行，MUST NOT 删除旧版本块的行。

#### Scenario: 相同文本跨版本

- **WHEN** 新版本子块与旧版本子块 `content_hash` 相同且模型维度一致
- **THEN** 直接复制旧向量，嵌入调用数为零

#### Scenario: 清理孤儿

- **WHEN** 带 `--prune` 运行
- **THEN** 只删除找不到对应 `material_chunks` 行的索引行，旧版本块仍保留
