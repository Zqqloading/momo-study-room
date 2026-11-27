# Tasks

## 1. 基线与 schema v8

- [x] 1.1 在 `core/db.py` 增加 `admin_tasks` 建表与索引，`SCHEMA_VERSION` 改为 8；验证 `tests/test_db.py` 覆盖新版本与表存在
- [x] 1.2 用 `data/app-v5.db`（v7）副本跑 `init_schema`，验证升级到 v8 且原有表/行不变；在测试中保留该迁移用例
- [x] 1.3 更新 `docs/designs/admin-console-v0.1.md` 的 schema 版本引用与 `VERSIONS.md` 哈希（如正文有改动）；验证哈希与文件一致

## 2. 任务模型与 API

- [x] 2.1 新增 `core/admin_tasks.py`：任务创建/查询/列表、`queued/running/终态` 状态、参数校验、同 kind+params 去重；验证单元测试覆盖状态与去重
- [x] 2.2 在 `bff/admin.py` 增加 `POST /api/admin/tasks`、`GET /api/admin/tasks/{task_id}`、`GET /api/admin/tasks`；验证 TestClient 测试覆盖 202/400/404 与 `{data,total}`
- [x] 2.3 实现任务启动恢复：`running` → `failed`，`queued` 重新入队；验证单元测试覆盖两种状态
- [x] 2.4 实现 `log_text` 上限、日志尾截断与 API key/Authorization 脱敏；验证单元测试覆盖截断与掩码
- [x] 2.5 为任务 API 增加无写保护：GET 不写库；验证 `PRAGMA data_version` 前后不变

## 3. 任务执行器与三类任务

- [x] 3.1 实现单 worker 队列与子进程执行器（超时、逐行日志、非 0 退出映射 `failed`）；验证 fake runner 单元测试
- [x] 3.2 实现 `ingest` 参数与命令映射：`materials/` 路径白名单、`dry_run` 不写库、`extract=true` 时停在 `awaiting_review`、不自动 confirm/reindex；验证参数测试与库副本 dry-run
- [x] 3.3 实现 `rebuild` 参数与命令映射：`fts_only`、`prune`、`model`、`dim`；验证缺少 embedding provider 时非 fts-only 失败
- [x] 3.4 实现 `evaluate` 参数与结果汇总：suite 白名单、缺输入 `skipped`、全 skipped 不为通过；验证单元测试
- [x] 3.5 给 `core.ingest`、`core.extract`、`core.confirm`、`core.reindex` 增加机器可读的 `pipeline_run_id` 输出，并在任务结果中汇总；验证解析测试
- [x] 3.6 用库副本提交 `rebuild --fts-only` 任务，轮询到 `succeeded`，验证 FTS 行数变化且不调用 embedding

## 4. 只读列表 API

- [x] 4.1 实现材料/概念/题库题/会话题列表接口：分页、排序白名单、过滤、`ids`、`{data,total}`；验证 API 测试
- [x] 4.2 实现学习会话/自由对话/管线运行列表接口：分页、状态/日期/关键词过滤；验证 API 测试
- [x] 4.3 为所有只读 GET 增加无写测试；验证 `data_version` 与写入计数不变
- [x] 4.4 在 `docs/designs/admin-console-v0.1.md` 或 README 记录列表接口契约；验证文档中的示例与实际响应一致

## 5. react-admin 脚手架

- [x] 5.1 创建 `admin-ui/`（Vite + React + TypeScript + react-admin），配置 `base="/admin/"`、`build.outDir="../web/admin"`；验证 `npm run build` 产出 `web/admin/index.html`
- [x] 5.2 实现自定义 `dataProvider`：`getList/getOne/getMany/getManyReference/create`，`update/delete` 抛错；验证 vitest 单测覆盖 URL 与包装
- [x] 5.3 实现 Layout、中文菜单、Dashboard 与 `HealthStrip`；验证 Playwright 打开 `/admin/` 无 console error，健康条显示三红/黄
- [x] 5.4 在 README 增加 `npm ci && npm run build` 与 BFF 启动顺序；验证按文档命令能从零构建并访问 `/admin/`
- [x] 5.5 实现 `PageState`、`ErrorPanel`、`EmptyState`、`NotFound`、`GlobalBanner` 与 loading 15s 超时转 error；验证组件测试与 Playwright 状态切换
- [x] 5.6 实现 BFF 构建缺失时的 `/admin/` 503 提示页（写明 `npm ci && npm run build`）；验证缺失构建产物时不返回裸 404、不循环刷新

## 6. 资源页面

- [x] 6.1 实现材料列表与详情：当前/历史版本、块、概念、题库题、会话题、会话、引用；保留影响面、溯源徽标、修复计划与复制命令；验证 Playwright 与真实样本计数
- [x] 6.2 实现概念列表与详情：掌握度、状态、出处、题库题、会话题、会话、后继概念、最近评分；验证 Playwright
- [x] 6.3 实现题库题/会话题列表与详情：两条溯源路径、生成元数据、命中块、使用记录；验证 Playwright 与 API 测试
- [x] 6.4 实现学习会话/自由对话列表与详情：题→概念→材料、追问/讲解、消息引用；验证 Playwright
- [x] 6.5 实现管线运行列表与详情：kind、status、stats、error、code_version；验证 Playwright
- [x] 6.6 实现全局搜索页：材料/概念/题/会话分组，复用 `/api/admin/search`；验证 Playwright 搜索中文关键词
- [x] 6.7 实现列表 URL 状态（page/per_page/sort/order/filter/q）、菜单重置、刷新与 back 恢复；验证 Playwright 前进/后退/复制 URL
- [x] 6.8 实现详情「返回列表」与跨实体 push/back，保留进入前的列表筛选与分页；验证 Playwright 材料→概念→返回

## 7. 任务页面

- [x] 7.1 实现任务列表与详情页：状态、kind、进度、日志尾、结果、错误；`queued/running` 时轮询并在终态停止；验证 fake 任务端到端
- [x] 7.2 实现新建摄取/重建/评测表单：参数校验、`mode=real` 二次确认、路径提示；验证非法参数在客户端被拦截
- [x] 7.3 实现任务结果渲染：ingest 的 `candidates_path`、rebuild 的计数、evaluate 的 suite 状态与报告路径；验证 Playwright
- [x] 7.4 实现任务提交成功 replace、400/重复/5xx/轮询连续失败/failed/awaiting_review 的导航与失败落点；验证 Playwright 覆盖每条路径

## 8. 集成与迁移

- [x] 8.1 构建 react-admin 后删除手写 `web/admin/index.html`、`admin.css`、`admin.js`；验证 `/admin/` 由构建产物提供，学习界面「管理」链接仍可用
- [x] 8.2 用 `data/app-v5.db` 副本完成 v7→v8 迁移冒烟：Dashboard、材料列表/详情、`rebuild --fts-only`、`ingest --dry-run`、`evaluate` 缺输入 skipped；验证结果与备份
- [x] 8.3 跑全量 `pytest` 与 Playwright 冒烟；验证无回归、无 console error、只读 GET 不写库
- [x] 8.4 更新 README/文档：构建步骤、任务 API、迁移与回滚口径；验证文档命令可执行
- [x] 8.5 页面状态与失败落点验收：每个列表/详情模拟 200/空/404/500/超时，验证无白屏、无裸 JSON、重试与返回入口可用

## 9. 材料上传与扫描

- [x] 9.1 实现 `POST /api/admin/uploads`：只收 `.md`/`.html`，保存到 `materials/inbox/`，限制大小与同名；验证 200/400/409/413
- [x] 9.2 摄取页增加拖拽/点击上传区，上传成功后填入路径；验证 Playwright 拖拽
- [x] 9.3 实现 `GET /api/admin/materials/scan`：按 `path + content_hash` 对比 DB，返回 new/changed/unchanged/missing；验证扫描测试
- [x] 9.4 摄取页增加扫描面板：新增默认全选、变更默认不选；批量提交时每个文件一个 ingest 任务；验证 UI 与任务列表

## Workflow follow-up

- 代码评审通过后运行 `/opsx:apply` 进入实现。
- 实现完成后运行 `/opsx:archive` 归档变更并同步主 specs。
