# Design

## Context

当前 `/admin` 是手写只读工作台，查询逻辑在 `core/admin_queries.py`、`core/admin_repair.py`，HTTP 入口在 `bff/admin.py`；BFF 在 `/` 静态托管 `web/`，`web/admin/` 自然映射到 `/admin/`。数据库为 `data/app-v5.db`，schema v7。

本设计的技术约束：

- 单用户本地应用，默认只监听 `127.0.0.1`，不做登录。
- 内容真相源是文件与 CLI：`materials/`、`concepts.yaml`、`seeds/question_bank.json`、`persona.yaml`；后台不能直接改。
- 现有长操作都是同步 CLI，不能在一个 HTTP 请求里等完成。
- 现有详情接口已经包含影响面、溯源自愈和修复计划，不能因换 UI 丢失。
- 完整资源矩阵、接口字段和 DDL 见 `docs/designs/admin-console-v0.1.md`；本文只记录实现层的选择。

## Goals / Non-Goals

**Goals:**

- react-admin 作为管理前端，构建产物由同一个 BFF 托管，使用 hash 路由。
- 为只读资源补齐列表接口；详情继续复用现有接口。
- 新增 `admin_tasks` 统一任务表和三类长任务（ingest、rebuild、evaluate）。
- 保留材料/概念/题/会话的双向影响面与修复计划，作为 react-admin 自定义组件。
- schema v7 → v8 只加表，不改现有表。

**Non-Goals:**

- 多用户、角色、登录体系。
- 外部来源采集器/域名策略。
- 在线编辑材料正文、`concepts.yaml`、题库 seeds、`persona.yaml`。
- 热项 discard/promote、人格/记忆/心情管理；这些放 Phase 2。
- 自动确认概念、自动重建索引、自动回滚已写数据。

## Decisions

### 1. react-admin + Vite + hash 路由

选择 react-admin（React + MUI）+ Vite + TypeScript；`vite.config.ts` 设置 `base="/admin/"`、`build.outDir="../web/admin"`。复用 react-admin 默认的 hash 路由，URL 形如 `/admin/#/materials`。

理由：列表、详情、筛选、分页、表单、通知、路由都由框架提供；hash 路由下服务端只看到 `/admin/`，不需要在 BFF 加 SPA fallback。

替代方案：
- 纯 React + 自写列表/表单：重复实现分页、筛选、错误提示，违背“不自己写 UI”。
- browser history：需要 BFF 增加 `/admin/{path}` 兜底，且与现有静态挂载顺序耦合；v1 不采用。
- Next.js/SSR：单用户本地管理台没有 SEO/首屏需求，增加构建复杂度。

### 2. 自定义 dataProvider，不直接套 `ra-data-simple-rest`

现有详情接口返回自定义结构（影响面、修复计划、溯源），不是简单的 REST 资源。实现 `admin-ui/src/dataProvider.ts`，把 react-admin 的 `getList/getOne/getMany/getManyReference/create` 映射到 `/api/admin/*`；`update/delete` 抛 `NotImplemented`。

理由：保留现有详情能力，不为了适配通用 REST 而改后端响应；写入口只有任务创建。

替代方案：把所有详情改成标准 REST 形状；会破坏现有测试与前端工作台，收益低。

### 3. 新增列表接口，详情接口保持

列表接口统一 `GET /api/admin/{slug}?page=&per_page=&sort=&order=&ids=&...`，返回 `{data,total}`。详情继续使用现有 `/api/admin/material/{id}`、`/api/admin/concept/{id}`、`/api/admin/question`、`/api/admin/session/{id}`、`/api/admin/conversation/{id}`。

理由：列表需要分页/筛选/排序，现有接口没有；详情已经把跨表影响面算好，重写浪费。

替代方案：一次性重写全部 API 为标准 REST；会牵动现有手写 UI、测试和验收，且本期不需要。

### 4. 内容只读，写只走任务

v1 只读资源：材料、概念、题库题、会话题、学习会话、自由对话、管线运行。唯一长写入口是 `POST /api/admin/tasks`；热项动作 Phase 2。

理由：真相源在文件/CLI，后台直接写会制造第二套真相源；任务表提供统一审计、超时、日志和恢复。

替代方案：后台直接编辑 `concepts.yaml`/seeds；需要 diff、校验、回滚和 git 冲突处理，超出本期。

### 5. `admin_tasks` 新表，不复用 `pipeline_runs`

新增 `admin_tasks`，字段包括 `id`、`kind`、`status`、`params_json`、`progress_json`、`result_json`、`log_text`、`error`、`created_at`、`started_at`、`finished_at`。`pipeline_runs` 继续作为管线审计，任务结果记录 `pipeline_run_ids`。

理由：`pipeline_runs` 缺少 `queued`/`cancelled`/`awaiting_review`、缺少 evaluate、缺少 params/progress；强行复用会让管线审计和任务状态互相污染。

替代方案：扩展现有 `pipeline_runs`；需要改 kind 枚举和语义，并让 CLI 与后台争用同一状态，风险更高。

### 6. 单 worker + 子进程

任务执行器是单 worker 队列，一次跑一个任务；每个任务通过 `asyncio.create_subprocess_exec(sys.executable, "-m", ...)` 调用已验证的 CLI，逐行收集 stdout/stderr。超时按 kind 设置；进程非 0 退出映射为 `failed`。执行器默认在非 fake 模式开启；fake 模式默认关闭，可 `ADMIN_TASK_RUNNER=on` 强制开启；测试环境用 off。

理由：单用户本地不需要并发；子进程隔离能避免 CLI 阻塞 BFF 事件循环，也方便超时终止和日志捕获。

替代方案：在 BFF 进程内直接调用 CLI 的 `main()`；会阻塞事件循环，且 `confirm` 的交互输入难以处理。

### 7. 轮询，不用 SSE/WebSocket

前端用自定义 `useTaskPolling` hook 轮询 `GET /api/admin/tasks/{id}`：`queued/running` 时 1.5s，30s 后降到 5s，终态停止。响应带 `Cache-Control: no-store`。

理由：任务状态是低频、可轮询的；现有 WebSocket 服务于学习会话，不应把管理任务混进去。

替代方案：复用 `/ws` 推送任务事件；会扩大会话协议、增加断线恢复复杂度，收益低。

### 8. ingest 停在 `awaiting_review`

`ingest` 任务支持 `dry_run`、`emit_chunks`、`extract`、`confirm`；v1 `confirm=true` 不可用（返回 400）。`extract=true` 且 `confirm=false` 时，任务以 `awaiting_review` 结束，结果返回 `candidates_path`。ingest 不自动跑 reindex。

理由：`core.confirm` 是交互式并会写 `concepts.yaml`；自动确认有误写风险。重建索引是独立任务，避免一次任务做太多不可逆动作。

替代方案：v1 实现非交互 `--decisions`；需要新增 CLI 契约和决策 JSON，推迟到 Phase 2。

### 9. evaluate 的 skipped 语义

`evaluate` 只跑输入齐全的 suite；缺失输入的 suite 标 `skipped` 并给原因；只有所有实际执行的 suite 都通过才 `passed=true`，全 skipped 为 false。

理由：ASR 录音、人工标签、标准答案不是每次都有；把 skipped 当通过会制造假绿灯。

替代方案：缺失就失败；会让评测任务在准备不全时无法使用。

### 10. 构建产物不提交

`admin-ui/` 是源码；`web/admin/` 是构建产物；两者都不提交 `node_modules`/构建输出。部署前 `cd admin-ui && npm ci && npm run build`。BFF 检测到 `web/admin/index.html` 缺失时，`/admin/` 返回 503 HTML 并给出构建命令，不返回裸 404。

理由：保持仓库干净，避免构建产物 diff；单用户本地可以接受构建步骤；503 构建提示让失败落点可执行。

替代方案：提交构建产物免 Node 运行；会带来大 diff，且构建产物与源码容易不一致。

### 11. 页面状态、导航与失败落点

页面状态收敛为 `PageState` 的 loading/empty/error/notFound/partial/stale/forbidden；列表的 page/per_page/sort/order/筛选/q 写入 URL；任务提交成功用 `replace` 进入任务详情；失败一律落在同一路由并提供重试或返回入口。

理由：react-admin 的默认页面只处理数据成功路径；不统一状态会出现白屏、无限 loading 或错误后跳走。把列表状态放进 URL，才能让 back、刷新、deep link 可复现。

替代方案：每个页面各自处理 loading/error；实现快但行为不一致，测试也无法统一。错误后重定向到列表；会丢上下文且容易循环。

详细状态矩阵、导航规则、失败落点与 URL 契约见 `docs/designs/admin-console-v0.1.md` §4–§5。

### 12. 材料上传与扫描是短写/只读

摄取页支持把 `.md`/`.html` 拖到 `materials/inbox/`，上传只新增文件、不覆盖同名、不写 DB；另提供 `GET /api/admin/materials/scan` 递归扫描 `materials/`，按 `path + content_hash` 与 DB 对比，返回新增/变更/未变/缺失。批量提交时每个选中文件创建一个 ingest 任务。

理由：上传解决“文件还没进项目”，扫描解决“文件已经在 materials/ 但没入库”；两者都不绕过任务模型，DB 写入仍由 ingest 任务完成。

替代方案：上传即自动摄取；会跳过 dry-run/确认，且一个请求里混合多个写操作，失败难定位。扫描接口直接写库；违反只读边界。

## Risks / Trade-offs

- [schema v8 单向迁移] → 升级前备份 `data/app-v5.db`；回滚必须恢复备份，不能只回退代码。
- [单 worker 串行] → 单用户可接受；任务列表显示排队；同 kind+params 去重。
- [子进程继承环境] → 日志脱敏；不接收原始命令；路径/枚举白名单；任务表记录参数。
- [confirm 仍走 CLI] → 摄取任务停在 `awaiting_review`，后台不冒充完成；Phase 2 再做决策 UI。
- [构建产物缺失导致管理后台不可用] → BFF 返回 503 构建提示；README/启动日志提示 `npm run build`；验收前先构建。
- [任务进度粒度有限] → v1 至少到阶段；`current/total` 在能解析 CLI 输出时提供，否则 null；日志尾补足。
- [评测产生真实 API 费用] → `mode=real` 提交前二次确认；缺输入 skipped。
- [SQLite 读写竞争] → WAL；单 worker；只读 GET 不写；任务写集中在 worker。
- [旧代码无法打开 v8 库] → 部署时同时升级代码与库；保留备份。

## Migration Plan

1. 备份 `data/app-v5.db`（schema v7）。
2. 新增 `admin_tasks` 表与 `SCHEMA_VERSION=8`；启动时迁移。
3. 新增列表/任务 API 与任务执行器；保留现有详情 API。
4. 构建 `admin-ui/` 到 `web/admin/`；删除手写 `web/admin/index.html`、`admin.css`、`admin.js`。
5. 在 8799 端口用库副本冒烟：Dashboard、材料列表/详情、提交 `rebuild --fts-only`、轮询到终态。
6. 切到 8000 真实库；升级前确认备份。

回滚：代码回滚到旧版；数据库恢复 schema v7 备份。已执行的任务写入不回滚，必要时用备份恢复或重跑管线修正。

## Open Questions

无。构建产物不提交、ingest 停在 `awaiting_review`、热项动作 Phase 2 已在提案前确认；其余技术选择不影响规格或任务拆分。
