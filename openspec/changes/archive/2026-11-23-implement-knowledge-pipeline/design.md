# Design

## Context

- 当前 `SCHEMA_VERSION=3`（`core/db.py`），迁移只做加法，`MIGRATIONS` 已有 2/3 两档；高于代码版本的库拒绝打开。
- 唯一写入口是 `core/store.py`；四条 CLI 各自组装连接：`core/ingest.py`、`core/extract.py`、`core/confirm.py`、`core/reindex.py`。
- `core/embedding.py::_text()` 已把 `heading_path` 拼到正文前；`Store.rebuild_fts()` 重建 `chunk_fts` 时同样拼前缀。
- 工作区里入库/检索代码尚未提交（`feat/knowledge-base` 分支），本次实现叠加在现有工作区之上，不先动提交。
- 设计依据：`docs/designs/storage-layers-v0.1.md`、`realtime-knowledge-v0.1.md`、`knowledge-ingestion-v0.1.md` §6.5。动机见 `proposal.md`。

## Goals / Non-Goals

**Goals:**

- 一次加法迁移到 `SCHEMA_VERSION=4`，三张新表可用且可回滚测试。
- 四条管线各有运行记录，异常退出可被下一次同类运行收尾。
- `ingest → extract` 一条命令链跑通，块 id 与实际版本一致。
- confirm 在任何写入前拒绝悬空出处。
- 索引维护在文本未变时不重复调用嵌入接口，并能清理孤儿行。
- 热项的捕获、过期、隔离、晋升全部在 Store + CLI 层可测试。

**Non-Goals:**

- 不改子块参数（150-250 → 280-420 等基线结论）。
- 不接 BFF / 会话链路；不实现捕获触发策略（等 `core/coach.py`）。
- 不建 `hot_embeddings`；不做外部网页抓取。
- 不跑真实 API 与 20 条召回基线。

## Decisions

### D1 单次迁移 3 → 4

三张表一次进 `MIGRATIONS[4]`。备选是分两次（先 `pipeline_runs`、再热项表），但当前没有已部署的 v4 消费者，分批只会多一次迁移分支与测试组合。迁移仍只做加法；`SCHEMA_VERSION` 升到 4 后，旧代码打开新库会被现有版本守卫拒绝——迁移前先复制 `data/app.db`（`docs/designs/storage-layers-v0.1.md` §5）。

### D2 `core.ingest --emit-chunks`

在正式入库路径上按本次实际写入的 `version` 生成 chunks.json，供 `core.extract` 直接消费。备选是给 `extract` 加 `--db` 直读 `material_chunks`：那会让 extract 依赖库连接与版本选择，且仍要处理"读哪个版本"，破坏"extract 只吃文件"的解耦。实现注意：

- 新材料 → v1；更新材料 → 新版本；材料未变 → 用库中现有 `version` 生成，不写块行。
- `--emit-chunks` 与 `--dry-run` 同时给出时，`--dry-run` 优先（只出 JSON、不写库），两者语义不叠加。
- 输出路径默认 `data/candidates/<timestamp>.chunks.json`，`--out` 可覆盖。

### D3 confirm 在任何写入前校验出处

在校验通过前不写 `concepts.yaml`，否则违反"缺失时 YAML 与 DB 均无改动"。顺序：

1. 解析候选 → 收集全部 `chunk_id`。
2. 一次查询 `material_chunks` 求差集；缺失则报错并列出 id，退出。
3. 原子写 YAML。
4. 单事务写 `concepts.status` + `concept_sources`，事务内再校验一次（防并发删除）。

`--reapply` 同样先校验归档里的 `chunk_id`，再重放状态。备选是只在检索侧兜底，已否决：悬空出处会静默污染 `concept_sources`。

### D4 表格按行组切分

把表格 Block 解析为表头（首行 + 分隔行）与数据行；按 token 预算分组，每组输出「表头 + 行组」，flag 记 `table_split`。无分隔行（不是合法 Markdown 表）按 20 行/组处理。单行本身超限时保留该行并标 `oversized`，不再硬切字符。

### D5 向量复用与孤儿清理

- 复用键：`content_hash + model + dim + heading_path`。加 `heading_path` 是因为它会被拼进嵌入文本（`core/embedding.py::_text`）；只比 `content_hash` 会把不同小节上下文下的向量复制过来，复用结果与重算不一致。
- `--prune`：删除 `chunk_embeddings` 中 `chunk_id` 不在 `material_chunks` 的行。`chunk_fts` 在 `reindex` 里全量重建，孤儿自然消失；`--prune` 仍显式清理 FTS 中不存在的 id，保证只跑 `--fts-only` 时也一致。
- 旧版本块仍在 `material_chunks`，不会被误删；被删的是"块行已不存在"的索引残留。

### D6 热项存储与检索

`hot_items` + `hot_fts`（trigram）按 `realtime-knowledge-v0.1.md` 的 DDL 落地。热项检索只走 FTS，top 3，过滤 `status='hot'` 与未过期。`Store.rebuild_hot_fts()` 从 `hot_items` 全量重建，供捕获、丢弃、晋升后保持一致。

### D7 只捕获用户侧文本

`capture_hot_item(..., text_origin)` 必填且只接受 `'user'` / `'question'`；不接受其他值，从 API 层杜绝 agent 生成内容入库。`text_origin` 不落库（DDL 不增列），只作为调用契约；审计靠 `source_kind` 与 `source_url`。

### D8 运行记录接入方式

每个 CLI 在 `main()` 开头 `start_pipeline_run(kind, input)`，结束按结果 `finish_pipeline_run`；异常路径统一 `failed` + `error` 摘要。`start` 时先把同 kind 的残留 `running` 置 `failed`（`error='aborted'`）。run 行独立提交，不包进业务事务。

### D9 过期扫描

`expire_hot_items(now)` 由 `core.hot list` 与 `capture` 入口惰性调用；服务启动钩子留到 BFF 接入时再加。热项查询本身也按 `expires_at` 过滤，扫描只负责状态收敛。

## Risks / Trade-offs

- [旧代码打开 v4 库会被拒] → 迁移前复制 `data/app.db`；回滚需同时回滚库文件。
- [现有测试断言 `SCHEMA_VERSION=3`] → 先改测试到 4，再改实现，避免"实现改了测试没改"的假通过。
- [热项 FTS 对短中文命中弱] → 接受 v0；量上来或召回不足再评估 `hot_embeddings`（RT-05 已标 revisit）。
- [`--emit-chunks` 在未变材料上生成文件可能被误当成"有变更"] → 文件只进 `data/candidates/`（gitignore），并在输出里标注 `unchanged`。
- [confirm 多一次查询] → 一次批量查询求差集，不按候选逐条查。
- [prune 误删正在使用的向量] → 只删"chunk 行不存在"的 id；有块行的旧版本向量保留。

## Migration Plan

1. 先写 v4 schema 测试（期望失败）。
2. 改 `core/db.py`：`SCHEMA_VERSION=4`、`MIGRATIONS[4]`。
3. 实现 Store 方法、四条 CLI 接入、`core.hot` / `core.promote`。
4. 全量 `pytest`；再用复制出的 `data/app.db` 跑一次真实迁移（不调 API）。
5. 回滚策略：停 BFF → 恢复迁移前的 `data/app.db` 副本 → 代码回退。

## Open Questions

- 捕获触发精度（何时算"超纲"）留到 Coach 接入时定；本次只提供显式 API 与 CLI。
- TTL 7 天与 hot FTS 召回率需要真实会话数据校准。
