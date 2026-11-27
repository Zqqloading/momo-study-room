# Tasks

## 1. Schema v4

- [x] 1.1 在 `tests/test_db.py` 写失败测试：v4 库存在 `pipeline_runs`、`hot_items`、`hot_fts`；v3 库能迁移到 v4；`user_version > 4` 被拒绝。验证：先确认测试失败，再进入 1.2。
- [x] 1.2 修改 `core/db.py`：`SCHEMA_VERSION = 4`，新增 `PIPELINE_SCHEMA_SQL` 与 `HOT_SCHEMA_SQL`，写入 `MIGRATIONS[4]`。验证：`pytest tests/test_db.py -q` 全绿。
- [x] 1.3 复制 `data/app.db` 到 `data/candidates/` 后跑一次真实迁移演练，确认 `materials` 1 行、`material_chunks` 10 行（2 父 + 8 子）、`concepts` 6 行、`question_bank` 15 行不变、三张新表存在。验证：迁移前后用 `sqlite3` 计数比对。

## 2. Pipeline runs

- [x] 2.1 在 `core/store.py` 实现 `start_pipeline_run(kind, input)` 与 `finish_pipeline_run(id, status, stats, error)`；`start` 先把同 kind 的残留 `running` 置 `failed`/`aborted`。验证：`tests/test_store.py` 新增用例覆盖成功、partial、残留收尾三种。
- [x] 2.2 `core/ingest.py` 与 `core/reindex.py` 接入 run 记录：开始、成功、失败、异常路径都收尾。验证：`tests/test_pipeline.py` 断言两次运行各产生一行且状态正确。
- [x] 2.3 `core/extract.py` 与 `core/confirm.py` 接入 run 记录，统计字段按 `storage-layers-v0.1.md` §3.6 的约定填写。验证：`tests/test_pipeline.py` 覆盖 extract 的 fake 路径与 confirm 的失败路径。

## 3. 入库到抽取链路（ingest → extract）

- [x] 3.1 在 `core/ingest.py` 增加 `--emit-chunks`：按本次实际写入版本输出 chunks.json；材料未变时用现有版本输出且不写块行；与 `--dry-run` 同时出现时 `--dry-run` 优先。验证：`tests/test_ingestion.py` 覆盖新材料 v1、更新材料 v2、未变材料沿用版本三种情况，断言输出中无旧版本 id。
- [x] 3.2 在 `core/confirm.py` 的写入前增加批量 `chunk_id` 存在性校验；缺失时列出 id 并退出，不写 YAML/DB；`--reapply` 同样校验。验证：`tests/test_confirm.py` 断言悬空 id 时 `concepts.yaml` 与两张表均无改动。
- [x] 3.3 补端到端用例：`ingest --emit-chunks` → `extract`（fake scorer）→ `confirm`，断言候选 `chunk_id` 与 `material_chunks` 同版本可 join。验证：`tests/test_pipeline.py` 新增用例通过。

## 4. 切块：表格行组

- [x] 4.1 在 `core/ingestion.py` 解析表格表头与数据行，按 token 预算切行组，每组重复表头，flag 记 `table_split`；无分隔行时按 20 行/组。验证：`tests/test_ingestion.py` 断言超长表格每块含表头且 flag 正确。
- [x] 4.2 回归代码块：超限代码块保持单块并标 `oversized`，不按字符切。验证：`tests/test_ingestion.py` 新增用例；现有切块用例全部保持通过。

## 5. 索引维护

- [x] 5.1 在 `core/store.py` 增加按 `content_hash + model + dim + heading_path` 查已有向量的方法；`core/embedding.py` 在调 API 前先复制命中向量。验证：`tests/test_embedding.py` 用计数 fake embedder 断言同文本二次入库的嵌入调用为 0。
- [x] 5.2 在 `core/reindex.py` 增加 `--prune`：删除 `chunk_embeddings` 与 `chunk_fts` 中 chunk_id 不存在的行，旧版本块保留。验证：`tests/test_embedding.py` 或 `tests/test_pipeline.py` 断言孤儿行被删、旧版本行仍在。
- [x] 5.3 更新 `core/reindex.py` 的过时 docstring（当前仍写"embedding 补建等适配器接入后补"）与 `--prune` 帮助文本。验证：`python -m core.reindex --help` 输出与实际行为一致。

## 6. 热项

- [x] 6.1 在 `core/store.py` 实现热项方法：`capture_hot_item`（`text_origin` 只接受 `user`/`question`、按 `content_hash` 去重累加 `seen_count`）、`hot_items_for_query`（只返回未过期 `hot`）、`discard_hot_item`、`expire_hot_items`、`rebuild_hot_fts`。验证：`tests/test_hot.py` 覆盖去重、过期、拒绝非法 `text_origin`。
- [x] 6.2 实现 `core/hot.py` CLI：`capture`、`list`、`discard`；`list` 只显示未过期 `hot` 并显示 `seen_count` 与年龄；入口惰性调用过期扫描。验证：`tests/test_hot.py` 断言 `list` 过滤与状态收敛。
- [x] 6.3 实现 `core/promote.py`：写 `materials/inbox/<slug>.md`（front matter 带 `source_url`、`captured_at`、`promoted_from`），回填 `material_id` 并置 `promoted`；文件写失败不更新状态；重跑幂等。验证：`tests/test_promote.py` 覆盖成功、写失败、重复执行。
- [x] 6.4 补隔离用例：热项结果不写 `concept_sources`，且 Store 不提供把热项作为题目出处的路径。验证：`tests/test_hot.py` 断言 `concept_sources` 行数不变。

## 7. 集成检查

- [x] 7.1 全量 `pytest -q`：现有 117 条加新增用例全部通过。验证：`144 passed`，0 failed。
- [x] 7.2 手工冒烟（fresh DB、不调外部 API）：`core.ingest --emit-chunks` → `core.reindex --fts-only --prune` → `core.hot capture/list` → `core.promote`；`extract`/`confirm` 由 `tests/test_pipeline.py` 的 fake 端到端覆盖（CLI 拒绝 fake scorer）。验证：每步退出码为 0，`pipeline_runs` 有 ingest/reindex 行，晋升文件落在临时 inbox。
- [x] 7.3 实现偏差已写回：KB-38 与 §6.5.3 复用键加入 `heading_path`；`VERSIONS.md` 哈希已更新。验证：`VERSIONS.md` 记录的哈希与文件实际哈希一致。

## Workflow follow-up

- 提交前跑 `code-review` 与 `verify`（测试 + fresh DB 冒烟）。
- 归档 change：评审通过后执行 `openspec archive implement-knowledge-pipeline`。
- 子块参数 280-420 的切换不在本 change；等 PRD 的 20 条 Recall@5 基线后另开 change。
- BFF / Coach 接入热项捕获与第三路检索不在本 change；等 `core/coach.py` 落地后另开 change。
