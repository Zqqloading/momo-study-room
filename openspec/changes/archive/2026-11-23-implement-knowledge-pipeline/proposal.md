# Proposal

## Why

设计已落成三份 DRAFT：`storage-layers-v0.1`、`realtime-knowledge-v0.1`、`knowledge-ingestion-v0.1` §6.5；但代码仍停在 `SCHEMA_VERSION=3`，存在四个缺口：管线运行无持久记录、会话内超纲内容无承接、`ingest → extract` 的 CLI 链路要跑两次且可能把出处挂到旧版本块、`confirm` 能把出处写到不存在的块上。先补齐这四块，后续 20 条召回基线与 Coach 才有稳定底座。

## What Changes

- **Schema v4（加法迁移）**：新增 `pipeline_runs`（L5 管线审计）、`hot_items` 与 `hot_fts`（L4 未核实缓冲区）；高于当前版本的库仍拒绝打开。
- **Store**：新增 `start_pipeline_run` / `finish_pipeline_run`；新增热项捕获、查询、丢弃、晋升与 FTS 重建方法；新增块存在性校验方法。
- **CLI**：
  - `core.ingest` 增加 `--emit-chunks`：按实际写入的 `version` 产出 `chunks.json`；材料未变时按现有 version 产出。
  - `core.confirm`：单事务内校验每个 `chunk_id` 存在于 `material_chunks`；缺失整批报错，不写 YAML/DB。
  - `core.reindex`：补向量前按 `content_hash + model + dim` 复用已有向量；新增 `--prune` 删除孤儿索引行。
  - 新增 `core.hot capture|list|discard` 与 `core.promote <hot_id>`。
- **切块**：表格超过子块上限时按行组切并重复表头，标 `table_split`；不改子块参数。
- **运行记录接入**：四条管线（ingest/extract/confirm/reindex）各写一行 `pipeline_runs`。

不包含（MUST NOT）：

- 子块参数 150-250 → 280-420 的切换（等 PRD 的 20 条 Recall@5 基线）。
- BFF / 会话链路接入（`core/coach.py` 尚未实现）。
- 热点向量（`hot_embeddings`）、外部网页抓取、agent 联网。
- 20 条召回基线与真实 API 调用。

## Capabilities

### New Capabilities

- `knowledge-ingestion`: 管线运行记录、ingest→extract 的版本正确契约、confirm 的出处完整性、索引增量复用与孤儿清理、表格行组切分。
- `knowledge-hot-injection`: 未核实热项的捕获、过期、检索隔离与晋升；晋升是进入主知识库的唯一路径。

### Modified Capabilities

无。项目当前没有已归档的 spec；本次两份都是新能力。

## Impact

- 代码：`core/db.py`（`SCHEMA_VERSION` 3→4、`MIGRATIONS[4]`）、`core/store.py`、`core/ingest.py`、`core/confirm.py`、`core/reindex.py`、`core/embedding.py`；新增 `core/hot.py`、`core/promote.py`。
- 测试：`tests/test_db.py`、`tests/test_store.py`、`tests/test_pipeline.py`、`tests/test_confirm.py`、`tests/test_ingestion.py`、`tests/test_embedding.py`；新增 `tests/test_hot.py`、`tests/test_promote.py`。
- 数据：`data/app.db` 由 v3 迁移到 v4；现有 1 份材料 / 8 子块 / 6 概念 / 15 题不受影响；迁移只做加法。
- 依赖：无新增；仍用标准库 + numpy + 现有 provider。
- 已知风险：`hot_items` 的捕获触发精度、TTL 与 FTS 召回都是第一版占位，需真实会话数据校准。
