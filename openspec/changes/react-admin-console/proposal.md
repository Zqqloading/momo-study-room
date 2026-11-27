# Proposal

## Why

当前 `/admin` 是手写的只读工作台，只覆盖“内容影响面 + 修复计划”，没有资源列表、筛选、分页、标准详情页，也没有长任务模型。知识摄取、知识重建、整体评测仍然只能同步跑 CLI：请求会长时间挂起，没有统一任务号、状态、进度或失败恢复。

用 react-admin 替换手写 UI，可以把列表/详情/筛选/表单交给框架；用一张 `admin_tasks` 表统一三类长任务，可以让前端只提交任务、轮询状态，避免 HTTP 等完成。

## What Changes

- **替换管理前端**：删除手写 `web/admin/index.html`、`admin.css`、`admin.js`，新增 `admin-ui/`（react-admin + Vite + TypeScript）；构建产物输出到 `web/admin/`，由同一个 BFF 在 `/admin/` 托管。
- **react-admin 路由**：使用默认 hash 路由（`/admin/#/materials`），不要求 BFF 做 SPA fallback。
- **新增资源列表接口**：材料、概念、题库题、会话题、学习会话、自由对话、管线运行、任务；统一 `{data,total}`、分页、排序、过滤、`ids` 批量。
- **明确读写矩阵**：内容资源只读；唯一长写入口是 `POST /api/admin/tasks`；热项 discard/promote 放 Phase 2；人格/记忆/心情 Phase 2 只读；外部来源不做。
- **新增统一长任务模型**：`admin_tasks`（schema v8），`POST /api/admin/tasks` 返回 `task_id`，`GET /api/admin/tasks/{task_id}` 轮询状态、进度、日志尾和结果；单 worker、子进程执行、超时、重启恢复、路径白名单、日志脱敏。
- **三类任务**：`ingest`（ingest → 可选 extract，停在 `awaiting_review`，不自动 confirm）、`rebuild`（`core.reindex`，支持 `fts_only`/`prune`）、`evaluate`（probe/asr/questions/scoring/agent，缺输入 `skipped`，跳过不算通过）。
- **保留内容影响面**：材料/概念/题/会话的双向影响面与修复计划改为 react-admin 自定义详情组件，不丢现有能力。
- **定义页面流程与状态**：列表/详情统一 loading、empty、error、partial、notFound 状态；列表的 page/per_page/sort/order/筛选/q 写入 URL；任务提交成功 replace 到任务详情；404、5xx、轮询失败、`awaiting_review` 都有明确落点与返回入口。
- **摄取页支持拖拽上传**：`.md` / `.html` 上传到 `materials/inbox/`，不覆盖同名文件，单文件 ≤10MB；上传只新增文件，不写 DB，摄取仍走任务。
- **摄取页支持扫描与批量提交**：递归扫描 `materials/` 的新增/变更文件，按 `path + content_hash` 与 DB 对比；勾选后每个文件提交一个 ingest 任务，扫描本身只读。
- **构建产物不提交**：`admin-ui/node_modules/`、`web/admin/` 忽略；部署前 `npm ci && npm run build`。

不在本变更内：多用户/登录、外部来源采集、在线编辑 `materials/`/`concepts.yaml`/`seeds/question_bank.json`/`persona.yaml`、热项动作、人格/记忆/心情管理。

## Capabilities

### New Capabilities

- `admin-console`: 管理后台资源读取与导航。覆盖 react-admin SPA、BFF 托管、资源列表/详情接口、只读/可写矩阵、Dashboard/全局搜索、材料/概念/题/会话的影响面与修复计划组件、页面状态/导航/失败落点，以及摄取页材料上传。
- `admin-tasks`: 长任务统一模型。覆盖 `admin_tasks` 表、任务 API、任务状态机、轮询契约、单 worker 执行器、超时/恢复/日志/路径校验，以及 ingest/rebuild/evaluate 三类任务的参数与结果。

### Modified Capabilities

无。现有 `knowledge-ingestion`、`knowledge-retrieval`、`knowledge-hot-injection`、`coach-session`、`free-talk`、`question-generation`、`learning-unit` 的行为不变；本变更只是新增管理读取面与任务封装。

## Impact

- 前端：新增 `admin-ui/`（react-admin、Vite、TypeScript、MUI）；`web/admin/` 变为构建产物；学习界面右上角保留「管理」链接并指向 `/admin/`。
- BFF：`bff/admin.py` 扩展列表与任务接口；`bff/main.py` 继续用现有静态挂载；新增任务 worker 生命周期。
- 核心：新增 `core/admin_tasks.py`；`core/db.py` schema v7 → v8（只加 `admin_tasks` 表）；现有 `core/admin_queries.py`、`core/admin_repair.py` 保留。
- 数据：`data/app-v5.db` 升级到 v8 是单向的；升级前必须备份。`pipeline_runs` 继续作为管线审计，任务结果记录 `pipeline_run_ids`。
- 依赖：react-admin、Vite、TypeScript、MUI；仅构建时需要 Node，运行时 BFF 不依赖 Node。
- 测试：新增列表/任务 API、任务执行器、数据提供器、Playwright 冒烟；现有 admin 查询/验收测试保留。
