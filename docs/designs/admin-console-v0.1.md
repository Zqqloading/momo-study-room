# 管理后台设计 v0.1（react-admin）

- 状态：DRAFT v0.1（2026-11-26）
- 范围：用 react-admin 替换当前手写 `/admin` 页面；构建产物由同一个 BFF 托管；明确资源/接口/读写矩阵；知识摄取、知识重建、整体评测统一任务号 + 轮询。
- 非范围：多用户与权限体系、外部来源采集器、直接在线编辑 `materials/`、`concepts.yaml`、`seeds/question_bank.json`、`persona.yaml` 等真相源。
- 基线：`feature-mood` 分支，`data/app-v5.db` 当前 schema v7；本设计新增 schema v8。

## 1. 目标与现状

### 1.1 目标

1. **不自己写 UI**：管理界面用 react-admin（React + MUI）搭建，列表、详情、筛选、分页、表单、路由、通知都由框架提供。
2. **同一个 BFF 托管**：react-admin 构建产物输出到 `web/admin/`，由现有 FastAPI 静态挂载在 `/admin/` 提供；不新起前端服务。
3. **资源接口明确**：每个资源对应哪些列表/详情接口、哪些只读、哪些可写，一张表说清。
4. **长任务统一模型**：知识摄取、知识重建、整体评测三类长任务都返回 `task_id`，前端只轮询任务状态，不在 HTTP 请求里等完成。
5. **保留内容影响面**：当前手写工作台的“材料 → 块 → 概念 → 题 → 会话”双向影响面与修复计划，作为 react-admin 的自定义详情组件保留，不丢能力。

### 1.2 现状

- 现有管理 API：`bff/admin.py`，全部只读，路径为 `/api/admin/health`、`/api/admin/search`、`/api/admin/material/{id}`、`/api/admin/concept/{id}`、`/api/admin/question`、`/api/admin/session/{id}`、`/api/admin/conversation/{id}`。
- 现有手写前端：`web/admin/index.html`、`admin.css`、`admin.js`；功能是健康条、全局搜索、双向影响面、修复计划。
- 现有内容真相源：`materials/`、`concepts.yaml`、`seeds/question_bank.json`、`persona.yaml`；运行时 `materials/` 只读，写入走 CLI 管线。
- 现有长任务：都是同步 CLI（`core.ingest`、`core.extract`、`core.confirm`、`core.reindex`、`bff.probe`、`bff.asr_eval`、`core.eval_questions`、`core.eval_scoring`、`bff.agent_smoke`），没有统一任务号、状态、进度或轮询接口。
- 现有 BFF 静态挂载：`bff/main.py` 在最后 `app.mount("/", StaticFiles(directory=web_dir, html=True))`；`web/admin/` 会自然映射到 `/admin/`。

### 1.3 关键决定

| 决定 | 选择 | 理由 |
|---|---|---|
| 前端框架 | react-admin + Vite + TypeScript | 列表/详情/筛选/表单/路由开箱即用；MUI 组件足够 |
| 托管方式 | 构建产物 `web/admin/`，同一个 BFF | 不新增进程、不改端口、复用现有静态挂载 |
| 路由 | react-admin 默认的 hash 路由，URL 形如 `/admin/#/materials` | 深链接不需要 BFF 做 SPA fallback；静态挂载直接可用 |
| 读写模型 | 内容资源只读；v1 写操作只有提交任务；热项动作 Phase 2 | 真相源仍在文件/CLI；任务表是统一审计入口 |
| 长任务 | 新表 `admin_tasks` + 单 worker 队列 + 轮询 | 统一任务号；避免 HTTP 长时间挂起；服务重启可恢复状态 |
| 认证 | 默认仅绑定 `127.0.0.1`，无登录 | 单用户本地应用；远程访问另加 token，不进入 v1 |

## 2. 总体架构

### 2.1 目录

```text
admin-ui/                     # 新增：react-admin 源码
  package.json
  vite.config.ts
  index.html
  src/
    main.tsx
    App.tsx
    dataProvider.ts
    layout.tsx
    i18n.ts
    dashboard.tsx
    pages/
      globalSearch.tsx
      taskCreate.tsx
      audit.tsx               # Phase 2
    resources/
      materials.tsx
      concepts.tsx
      bankQuestions.tsx
      sessionQuestions.tsx
      sessions.tsx
      conversations.tsx
      hotItems.tsx            # Phase 2
      pipelineRuns.tsx
      tasks.tsx
    components/
      HealthStrip.tsx
      ImpactPanel.tsx
      RepairPlan.tsx
      ProvenanceBadge.tsx
      TaskProgress.tsx
      CopyCommand.tsx
web/admin/                    # 构建产物，BFF 托管
bff/admin.py                  # 扩展：列表 + 任务接口
core/admin_tasks.py           # 新增：任务模型、队列、执行器
core/admin_queries.py         # 保留：现有只读查询
core/admin_repair.py          # 保留：修复计划
```

### 2.2 运行时

```text
浏览器 /admin/#/materials
  → BFF StaticFiles 返回 web/admin/index.html
  → react-admin 读取 hash 路由
  → dataProvider 请求 /api/admin/*
  → BFF 读 SQLite / 写 admin_tasks
  → 任务 worker 调 subprocess 跑 CLI
  → 前端轮询 /api/admin/tasks/{task_id}
```

### 2.3 构建与 BFF

`admin-ui/vite.config.ts`：

```ts
export default defineConfig({
  base: "/admin/",
  build: { outDir: "../web/admin", emptyOutDir: true },
  server: {
    proxy: { "/api": "http://127.0.0.1:8000" },
  },
});
```

- 生产：`cd admin-ui && npm ci && npm run build`，产物写到 `web/admin/`；BFF 直接托管。
- 开发：`npm run dev`，Vite 在 5173，`/api` 代理到 8000。
- hash 路由下，服务端只看到 `/admin/`；`#/materials` 不参与 HTTP 请求，所以不需要 `app.get("/admin/{path}")` 兜底。
- 旧的 `web/admin/index.html`、`admin.css`、`admin.js` 在 react-admin 构建通过后删除，避免两套 UI 并存。

### 2.4 认证

- v1：仅监听 `127.0.0.1`，不做登录；react-admin 不挂 `authProvider`。
- 如果以后需要从别的机器访问，再加 `ADMIN_TOKEN`：BFF 校验 `Authorization: Bearer`，react-admin 加一个最小 `authProvider`。不在 v1 实现。

## 3. API 约定

### 3.1 通用

- 全部在 `/api/admin` 下。
- 读接口：`GET`；写接口：只有 `POST /api/admin/tasks` 和 Phase 2 的热项动作。
- 响应 UTF-8 JSON；错误 `{"error": "...", "field": "..."}`（`field` 可选）。
- 读接口统一 `Cache-Control: no-store`；单用户本地不做缓存协商。
- 详情接口沿用现有形状（`material_detail`、`concept_detail` 等）；`dataProvider` 负责包成 react-admin 的 `{ data }`。
- 列表接口统一返回：

```json
{ "data": [ ... ], "total": 123 }
```

- 分页参数：`page`（1 开始）、`per_page`（默认 25，上限 100）。
- 排序：`sort` + `order=asc|desc`；每个资源有排序白名单。
- 批量：`ids=a,b,c` 供 `getMany` 使用，最多 100 个。
- 过滤：资源自己的 query 参数；非法枚举值返回 400，未知参数忽略。

### 3.2 列表接口

| 资源 | 列表接口 | 主要过滤 | 默认排序 |
|---|---|---|---|
| 材料 | `GET /api/admin/materials` | `q`、`status`、`format`、`ids` | `title asc` |
| 概念 | `GET /api/admin/concepts` | `q`、`status`、`mastery`、`ids` | `mastery asc, id asc` |
| 题库题 | `GET /api/admin/bank-questions` | `q`、`concept_id`、`kind`、`ids` | `id asc` |
| 会话题 | `GET /api/admin/session-questions` | `q`、`session_id`、`concept_id`、`question_bank_id`、`min_score`、`max_score`、`ids` | `id desc` |
| 学习会话 | `GET /api/admin/sessions` | `q`、`status`、`kind`、`concept_id`、`start`、`end`、`ids` | `date desc` |
| 自由对话 | `GET /api/admin/conversations` | `q`、`start`、`end`、`ids` | `updated_at desc` |
| 热项 | `GET /api/admin/hot-items` | `q`、`status`、`ids` | `captured_at desc` |
| 管线运行 | `GET /api/admin/pipeline-runs` | `kind`、`status`、`start`、`end`、`ids` | `id desc` |
| 任务 | `GET /api/admin/tasks` | `kind`、`status`、`start`、`end`、`ids` | `created_at desc` |

### 3.3 详情接口

| 资源 | 详情接口 | 备注 |
|---|---|---|
| 材料 | `GET /api/admin/material/{id}?history=0\|1` | 现有；含影响面、溯源、修复计划 |
| 材料扫描 | `GET /api/admin/materials/scan` | 新增；对比 `materials/` 与 DB，返回 new/changed/unchanged/missing |
| 概念 | `GET /api/admin/concept/{id}` | 现有；含出处、题、会话、后继概念、最近评分 |
| 题库题 | `GET /api/admin/question?bank_id={id}` | 现有；含使用记录、出处 |
| 会话题 | `GET /api/admin/question?session_question_id={id}` | 现有；含生成元数据、命中块 |
| 学习会话 | `GET /api/admin/session/{id}` | 现有；含题、追问/讲解 |
| 自由对话 | `GET /api/admin/conversation/{id}` | 现有；含消息与引用 |
| 任务 | `GET /api/admin/tasks/{task_id}` | 新增；任务状态 + 进度 + 日志尾 + 结果 |

### 3.4 写接口

| 接口 | 用途 | 说明 |
|---|---|---|
| `POST /api/admin/uploads` | 上传材料文件 | multipart；只允许 `.md`/`.html`，保存到 `materials/inbox/`；单文件 ≤10MB，最多 10 个；不覆盖同名文件 |
| `POST /api/admin/tasks` | 提交长任务 | 返回 202 + `task_id`；唯一的长任务写入口 |
| `POST /api/admin/tasks/{task_id}/cancel` | 取消任务（可选） | 只终止子进程，不自动回滚已写数据 |
| `POST /api/admin/hot-items/{id}/discard` | 丢弃热项（Phase 2） | 短写；写 `hot_items.status` |
| `POST /api/admin/hot-items/{id}/promote` | 晋升热项（Phase 2） | 短写；写 `materials/inbox/` 文件，随后需提交 ingest 任务 |

内容资源没有 `PUT/PATCH/DELETE`。react-admin 的资源统一 `hasCreate={false}`、`hasEdit={false}`、`hasDelete={false}`；`dataProvider.update/delete` 直接抛 `NotImplemented`。

## 4. 信息架构

### 4.1 菜单与路由

| 菜单组 | 页面 | hash 路由 | 资源 | 读写 | 默认落点 |
|---|---|---|---|---|---|
| 总览 | Dashboard | `/#/` | health + 最近任务 | 只读 | 全局默认 |
| 学习 | 学习会话 | `/#/sessions` | sessions | 只读 | 列表第 1 页 |
| 学习 | 自由对话 | `/#/conversations` | conversations | 只读 | 列表第 1 页 |
| 内容 | 材料 | `/#/materials` | materials | 只读 | 列表第 1 页 |
| 内容 | 概念 | `/#/concepts` | concepts | 只读 | 列表第 1 页 |
| 内容 | 题库题 | `/#/bank-questions` | bank_questions | 只读 | 列表第 1 页 |
| 内容 | 会话题 | `/#/session-questions` | session_questions | 只读 | 列表第 1 页 |
| 内容 | 管线运行 | `/#/pipeline-runs` | pipeline_runs | 只读 | 列表第 1 页 |
| 任务 | 任务列表 | `/#/tasks` | tasks | 读取 + 创建 | 列表第 1 页 |
| 任务 | 新建摄取 | `/#/tasks/create/ingest` | tasks | 写 | 表单 |
| 任务 | 新建重建 | `/#/tasks/create/rebuild` | tasks | 写 | 表单 |
| 任务 | 新建评测 | `/#/tasks/create/evaluate` | tasks | 写 | 表单 |
| 搜索 | 全局搜索 | `/#/search` | search | 只读 | 空查询提示 |
| Phase 2 | 热项 | `/#/hot-items` | hot_items | 读写 | 列表第 1 页 |
| Phase 2 | 审计 | `/#/audit` | tasks + pipeline_runs | 只读 | 组合视图 |
| Phase 2 | 人格/记忆/心情 | `/#/persona`、`/#/memories`、`/#/emotions` | 对应只读资源 | 只读 | 只读视图 |

- 详情路由：`/#/materials/:id`、`/#/concepts/:id`、`/#/bank-questions/:id`、`/#/session-questions/:id`、`/#/sessions/:id`、`/#/conversations/:id`、`/#/tasks/:id`。
- 默认落点：`/admin/` 进入 Dashboard；未知 hash 路由进入 NotFound。
- 菜单点击：进入该资源列表第 1 页与默认筛选；不保留上一次的筛选/排序。
- Deep link：列表与详情都可直接打开；非法 id 进入 NotFound，非法 query 回退默认值并提示。

### 4.2 页面层级与跨实体链接

- L0 菜单 → L1 列表 → L2 详情 → L3 跨实体详情。
- 列表只放摘要列；详情放全量数据；长列表分页，长文本折叠。
- 跨实体链接：
  - 材料 → 概念 / 题库题 / 会话题 / 会话 / 自由对话引用
  - 概念 → 材料 / 题库题 / 会话题 / 会话 / 后继概念
  - 题 → 概念 / 材料 / 会话
  - 会话 → 题 / 概念 / 材料 / 追问
  - 自由对话 → 材料引用 / 网页引用
- 每次跨实体跳转使用 push 历史；浏览器 back 回到上一个实体，不回到列表起点。
- 详情页顶部提供「返回列表」；返回时使用列表在 history 中的 URL，不重置筛选。

### 4.3 信息密度与页面边界

- Dashboard 只做总览，不放完整任务表单；任务提交是独立页面。
- 全局搜索是独立页面，v1 不做命令面板。
- 只读资源不显示新建/编辑/删除；任务资源只显示新建/查看。
- 管理后台与学习界面是两个入口；学习界面只保留右上角「管理」链接。
- 摄取页支持拖拽 `.md` / `.html` 到 `materials/inbox/`；上传只新增文件，不写 DB、不覆盖同名；摄取仍是单独的任务提交。
- 摄取页提供扫描：递归扫描 `materials/`，按 `path + content_hash` 与 DB 比较；新增默认全选、变更默认不选；批量提交时每个文件一个 ingest 任务。

## 5. 页面流程与状态

### 5.1 全局状态与优先级

全局状态按优先级从高到低覆盖页面：

| 优先级 | 状态 | 触发 | 页面行为 | 恢复 |
|---|---|---|---|---|
| 1 | `build_missing` | BFF 找不到 `web/admin/index.html` | 返回 503 HTML，写明 `cd admin-ui && npm ci && npm run build`；不进入 SPA，不循环重试 | 构建后刷新 |
| 2 | `unauthenticated` | 配置了 `ADMIN_TOKEN` 且请求未带合法 token | 显示 token 输入页；不显示菜单；保留 `returnTo` | 输入 token 后回到原路由 |
| 3 | `db_mismatch` | health 报告库版本与代码不一致 | 全局红色 banner；只读页面可看；新建任务按钮禁用 | 修库/迁移后点「重新检查」 |
| 4 | `offline` / `health_error` | health 请求失败或网络断开 | 全局黄色/红色 banner；页面数据可能为旧值；新建任务禁用 | 恢复网络后重试 |
| 5 | `page_error` | 页面自身请求 4xx/5xx | 页面内错误面板；保留全局 banner | 页面内「重试」 |
| 6 | `empty` | 请求成功但没有数据 | 空状态 + 下一步动作 | 清除筛选/去创建/返回列表 |
| 7 | `loading` | 页面首次加载 | 骨架屏；不显示空白页 | 自动进入 data/empty/error |

- 全局 banner 跨路由保留；页面错误不自动清掉全局 banner。
- `provider_fake` 单独作为健康红项：只读页面可用；任务提交允许，但 `evaluate` 必须显式选择 `real`/`fake`，并在 UI 标注结果不代表真实 provider。
- `index_missing` 是健康黄项：只读页面可用，任务页提示可提交 `rebuild`。

### 5.2 页面状态矩阵

| 页面 | loading | empty | error | partial / stale | 失败落点与恢复 |
|---|---|---|---|---|---|
| Dashboard | 计数卡与健康条骨架 | 全为 0 时显示「暂无数据」+ 去摄取/去任务 | health 5xx/超时：页内错误 + 重试；菜单仍可用 | health 成功但计数部分失败：显示可用计数，缺失项标「读取失败」 | 留在 Dashboard；不跳转 |
| 列表页（通用） | 表格骨架 5 行 | 「无结果」+ 清除筛选；任务列表额外给新建入口 | 4xx/5xx：表格上方错误面板 + 重试；保留筛选/分页 | `total` 与当前页不一致：显示警告，不自动跳页 | 留在当前 URL；非法 page 回第 1 页并 toast |
| 材料详情 | 标题/计数骨架 | 不存在：NotFound + 返回材料列表 | 5xx：页内错误 + 重试；保留已加载数据 | 历史开关请求失败：保留当前版本 + 行内错误；未匹配溯源标「未匹配」 | 留在详情；返回列表用 history |
| 概念详情 | 标题/计数骨架 | 不存在：NotFound + 返回概念列表 | 5xx：页内错误 + 重试 | YAML 无此 id：显示 orphaned 状态与 DB 状态；无出处/无评分给明确空态 | 留在详情；后继/来源链接可继续 |
| 题详情 | 题干/溯源骨架 | 不存在：NotFound + 返回题列表 | 5xx：页内错误 + 重试 | 块不存在：回退 URL 级并标「块级溯源缺失」；无生成元数据：明确空态 | 留在详情；可跳概念/会话 |
| 会话详情 | 题列表骨架 | 无题：显示「本场无题」；无追问：空态 | 5xx：页内错误 + 重试 | abandoned/partial 用状态 chip；某题不存在：行内「题 #id 不存在」 | 留在详情；可跳题/概念 |
| 自由对话详情 | 消息骨架 | 无消息：空对话空态 | 5xx：页内错误 + 重试 | `sources_json` 解析失败：行内「引用解析失败」；未匹配材料保留 URL 文本 | 留在详情；可跳材料 |
| 任务列表 | 表格骨架 | 「暂无任务」+ 三个新建入口 | 4xx/5xx：错误面板 + 重试；筛选无结果给清除筛选 | 任务状态未知：显示「状态未知」+ 查看详情 | 留在列表；不自动刷新详情 |
| 任务详情 | 状态/进度骨架 | 不存在：NotFound + 返回任务列表 | 5xx：页内错误 + 重试；轮询连续失败 3 次停止并显示「状态未知」 | `awaiting_review` 显示候选路径；`failed` 显示错误 + 日志尾 | 留在任务详情；可重新提交/刷新资源 |
| 任务创建 | 表单骨架 | 无 | 400：字段级错误；5xx/网络：保留表单值 + 重试 | 重复提交：跳已有任务并 toast；dirty 离开需确认 | 400 留在表单；成功 replace 到任务详情 |
| 上传区（摄取页） | 拖拽高亮 | 未选择文件：提示可拖拽或点击 | 400 类型错误 / 409 同名 / 413 超限：表单内错误 | 上传中禁用提交；成功后填入 path | 留在表单；不创建任务 |
| 扫描面板（摄取页） | 扫描中 | 没有新增/变更：显示空态 | 扫描失败：面板内错误 + 重试 | 新增默认全选、变更默认不选；缺失只读 | 留在表单；批量提交后跳任务列表 |
| 全局搜索 | 搜索中提示 | 空查询：提示输入；无结果：建议换词 | 5xx：错误 + 重试；保留查询 | 部分分组失败：显示可用分组 + 警告 | 留在搜索页；查询在 URL |
| 404 | 无 | 未知路由/id | 无 | 无 | 提供 Dashboard/材料/任务三个入口；不自动跳转 |

### 5.3 导航规则

| 场景 | 规则 | 验收 |
|---|---|---|
| 默认落点 | `/admin/` → Dashboard；未知路由 → NotFound | 打开根路径看到 Dashboard；乱输 hash 看到 404 |
| 菜单点击 | 进入列表第 1 页 + 默认筛选；不保留旧筛选 | 从有筛选的材料列表点「概念」再点回「材料」，筛选已重置 |
| 列表状态 | `page`、`per_page`、`sort`、`order`、`q`、资源过滤都在 URL | 刷新/复制 URL/前进后退都恢复同一列表状态 |
| 进入详情 | push 到详情路由 | back 回到刚才的列表，筛选/分页不丢 |
| 跨实体跳转 | push 到目标详情 | back 回到上一个实体详情，不回到列表起点 |
| 返回列表 | 详情顶部「返回列表」使用 history 中的列表 URL | 返回后页码/排序/筛选与进入前一致 |
| 任务提交成功 | 202 后 `replace` 到任务详情 | back 回到来源页，不回到已提交的表单 |
| 任务终态 | 不自动跳转；显示「刷新受影响资源」链接 | 成功/失败后用户仍停在任务详情，自己选择下一步 |
| 刷新页面 | 列表从 URL 恢复；详情重新请求；任务详情恢复轮询 | 刷新任务详情后状态继续更新 |
| 无效路由/id | NotFound；详情页 404 不重定向到列表 | 地址栏保留原 URL，页面给返回入口 |
| 无效 query | 回退默认值 + toast；不返回 400 页 | `?page=abc` 显示第 1 页并提示 |
| 未保存表单 | 任务创建表单 dirty 时离开需确认 | 填写参数后点菜单会弹出确认 |
| 全局搜索 | `q` 写入 URL；空查询不请求 | 刷新后搜索词与结果保持 |

### 5.4 失败落点

| 失败 | 落点 | 保留状态 | 用户动作 | 验收 |
|---|---|---|---|---|
| 列表 4xx/5xx | 原列表路由 | 筛选、分页、排序 | 重试；不改 URL | 错误面板出现，表格不消失为白屏 |
| 详情 404 | NotFound 页面 | 原 URL；返回列表入口 | 返回列表/搜索 | 不自动跳转，不循环 |
| 详情 5xx | 原详情路由 | 已加载数据（如有） | 重试 | 旧数据不被清空 |
| 网络断开 | 全局 banner + 页面错误 | 当前 URL 与表单值 | 恢复后重试 | 不静默失败，不重复提交 |
| 任务提交 400 | 任务创建表单 | 所有表单值 | 按字段修正 | 不创建任务，不跳转 |
| 任务提交重复 | 已有任务详情 | — | 查看已有任务 | 不新建第二个任务 |
| 任务提交 5xx/网络 | 任务创建表单 | 所有表单值 | 重试 | 按钮恢复可用，不双提交 |
| 轮询连续失败 3 次 | 任务详情 | 最后一次状态 | 手动刷新/回任务列表 | 停止轮询，显示「状态未知」 |
| 任务 failed | 任务详情 | 参数、日志尾、错误 | 重新提交（预填参数） | 不自动重试，不自动跳转 |
| 任务 awaiting_review | 任务详情 | 候选文件路径 | 按 CLI 确认；或返回来源页 | 不自动确认，不显示成功 |
| health 5xx | Dashboard | 菜单可用 | 重试 | 其他页面仍可打开 |
| 构建缺失 | BFF 503 页面 | — | 按提示构建 | 不是裸 404，不循环刷新 |
| 库版本不匹配 | 全局 banner + Dashboard | 只读页面 | 修复后重新检查 | 新建任务禁用 |
| 无效 query | 原页面 | 其他有效参数 | 修正筛选 | 回退默认值 + toast |
| 未授权（token 模式） | token 页面 | `returnTo` | 输入 token | 成功后回原路由 |
| 未知路由/id | NotFound | 原 URL | 返回入口 | 不自动重定向 |

### 5.5 URL 与状态契约

| 页面 | URL | URL 中的状态 | 默认值 | 非法值回退 |
|---|---|---|---|---|
| 列表 | `/#/{resource}?page=&per_page=&sort=&order=&q=&...` | 分页、排序、搜索、资源过滤 | `page=1`、`per_page=25`、资源默认排序 | 非法 page → 1；非法 sort → 默认；未知过滤丢弃 |
| 材料详情 | `/#/materials/:id?history=0\|1` | 历史版本开关 | `history=0` | 非法 history → 0 |
| 概念/题/会话/自由对话详情 | `/#/{resource}/:id` | 无 | — | 非法 id → NotFound |
| 任务列表 | `/#/tasks?kind=&status=&page=&per_page=` | kind/status/分页 | `page=1`、`per_page=25` | 非法枚举 → 不过滤 |
| 任务详情 | `/#/tasks/:id` | 任务号 | — | 非法 id → NotFound |
| 任务创建 | `/#/tasks/create/:kind` | kind | `ingest` 表单默认值 | 非法 kind → 404 |
| 全局搜索 | `/#/search?q=` | 搜索词 | 空 | 空查询不请求 |
| Phase 2 | `/#/hot-items`、`/#/audit`、`/#/persona` 等 | 各自筛选 | 列表第 1 页 | 同通用规则 |

- 不放进 URL 的状态：折叠面板、滚动位置、toast、临时勾选；刷新后不保留。
- 刷新：列表从 URL 重建；详情重新请求；任务详情按 `task_id` 恢复轮询。
- 菜单点击：重置到默认列表 URL，不继承旧 query。

### 5.6 状态组件与验收

- 统一组件：`PageState`（loading/empty/error/notFound/partial/stale/forbidden）、`ErrorPanel`（状态码 + 消息 + 重试）、`EmptyState`（说明 + 下一步）、`NotFound`、`GlobalBanner`、`TaskProgress`。
- 页面规则：
  - 每个列表/详情必须使用 `PageState`；MUST NOT 出现白屏或裸 JSON。
  - loading 超过 15s 必须转为 error + 重试，不能无限转圈。
  - error 必须显示 HTTP 状态与可读消息；不能只显示堆栈。
  - empty 必须给下一步动作：清除筛选、去创建任务、返回列表。
  - partial 必须渲染可用区段，并标注缺失区段；不能整页失败。
- 验收：每个页面模拟 200/空/404/500/超时；导航覆盖 back、deep link、跨实体、任务 replace；任务覆盖成功/失败/awaiting_review/轮询失败；全流程无 console error。

## 6. 权限与读写矩阵

| 资源 | react-admin 操作 | 接口 | 读写 | 阶段 | 备注 |
|---|---|---|---|---|---|
| 总览 Dashboard | 自定义页面 | `GET /api/admin/health` | 只读 | v1 | 三红 + 索引黄 + 计数 + 最近任务 |
| 学习会话 | list / show | `GET /api/admin/sessions`、`GET /api/admin/session/{id}` | 只读 | v1 | 含 finished/abandoned/unscored |
| 自由对话 | list / show | `GET /api/admin/conversations`、`GET /api/admin/conversation/{id}` | 只读 | v1 | 引用只到 URL 级 |
| 材料 | list / show | `GET /api/admin/materials`、`GET /api/admin/material/{id}` | 只读 | v1 | 详情含影响面/修复计划 |
| 材料扫描 | 摄取页扫描面板 | `GET /api/admin/materials/scan` | 只读 | v1 | 不写库；批量提交走任务 |
| 材料上传 | 摄取页拖拽/选择 | `POST /api/admin/uploads` | 写（仅新增） | v1 | 只写 `materials/inbox/`；不写 DB，不覆盖同名 |
| 概念 | list / show | `GET /api/admin/concepts`、`GET /api/admin/concept/{id}` | 只读 | v1 | 含掌握度、出处、后继 |
| 题库题 | list / show | `GET /api/admin/bank-questions`、`GET /api/admin/question?bank_id=` | 只读 | v1 | 题库题只到 URL 级 |
| 会话题 | list / show | `GET /api/admin/session-questions`、`GET /api/admin/question?session_question_id=` | 只读 | v1 | 生成题到块级 |
| 管线运行 | list / show | `GET /api/admin/pipeline-runs`、`GET /api/admin/pipeline-runs/{id}` | 只读 | v1 | ingest/extract/confirm/reindex |
| 任务 | list / show / create | `GET /api/admin/tasks`、`GET /api/admin/tasks/{id}`、`POST /api/admin/tasks` | 写（仅创建） | v1 | 统一长任务 |
| 全局搜索 | 自定义页面 | `GET /api/admin/search?q=` | 只读 | v1 | 材料/概念/题/会话分组 |
| 热项 | list / show + 动作 | `GET /api/admin/hot-items`、`GET /api/admin/hot-items/{id}`、`POST .../discard`、`POST .../promote` | 读写 | Phase 2 | 晋升后仍需 ingest |
| 审计 | 自定义页面 | `GET /api/admin/tasks` + `GET /api/admin/pipeline-runs` | 只读 | Phase 2 | 不建独立 audit 表 |
| 人格 | 自定义页面 | `GET /api/admin/persona` | 只读 | Phase 2 | `persona.yaml` 真相源不改 |
| 记忆 | list / show | `GET /api/admin/memories`、`GET /api/admin/memories/{id}` | 只读 | Phase 2 | 删除/遗忘另议 |
| 心情 | 自定义页面 | `GET /api/admin/emotions` | 只读 | Phase 2 | 按 `user_id+role` |
| 题目审核 | list / show | `GET /api/admin/question-review` | 暂不做 | — | `question_cache` 目前无读写代码 |
| 外部来源 | — | — | 不做 | — | 没有来源表/采集器，只能做引用审计 |

“写”现在有四种：上传新材料文件（只新增 `materials/inbox/`）、提交任务、热项动作（Phase 2）、任务取消（可选）。上传不写 DB，摄取与索引重建仍由任务完成；人格/记忆/心情在 Phase 2 也只读；直接改 `persona.yaml` 或 `concepts.yaml` 不进入后台。

## 7. react-admin 数据提供器与页面组件

### 7.1 dataProvider 映射

自定义 `admin-ui/src/dataProvider.ts`，不使用 `ra-data-simple-rest` 直接套：

| 方法 | 资源 | 实际请求 |
|---|---|---|
| `getList` | 所有列表资源 | `GET /api/admin/{slug}?page=&per_page=&sort=&order=&...`（`slug` 见 §3.2，如 `bank-questions`、`session-questions`） |
| `getOne` | materials | `GET /api/admin/material/{id}?history={0\|1}` |
| `getOne` | concepts | `GET /api/admin/concept/{id}` |
| `getOne` | bank_questions | `GET /api/admin/question?bank_id={id}` |
| `getOne` | session_questions | `GET /api/admin/question?session_question_id={id}` |
| `getOne` | sessions | `GET /api/admin/session/{id}` |
| `getOne` | conversations | `GET /api/admin/conversation/{id}` |
| `getOne` | tasks | `GET /api/admin/tasks/{id}` |
| `getMany` | 所有列表资源 | `GET /api/admin/{slug}?ids=a,b,c` |
| `getManyReference` | session_questions / bank_questions 等 | 列表接口 + 引用过滤（如 `session_id`、`concept_id`） |
| `create` | tasks | `POST /api/admin/tasks` |
| `update` / `delete` | 所有资源 | 抛 `NotImplemented` |
| 自定义 | hot_items | `POST /api/admin/hot-items/{id}/discard\|promote`（Phase 2） |

`getOne` 的返回值统一包成 `{ data: record }`；列表接口直接返回 `{ data, total }`。

材料详情的“含历史版本”开关不经过 `getOne` 的固定参数：`dataProvider.getOne` 默认 `history=0`，`MaterialShow` 用本地 state 直接请求 `GET /api/admin/material/{id}?history=1`，避免把 UI 状态塞进 data provider。

### 7.2 自定义组件

| 组件 | 用途 | 数据来源 |
|---|---|---|
| `HealthStrip` | 三红（库版本、provider fake、最近管线失败）+ 索引黄 | `/api/admin/health` |
| `ImpactPanel` | 材料/概念/题/会话的双向影响面 | 现有详情接口 |
| `RepairPlan` | 修复步骤、前置条件、可跳过条件、复制命令 | 现有详情接口的 `repair` |
| `ProvenanceBadge` | 块级 / URL 级 / 仅概念级 / 未匹配 | 现有详情接口 |
| `TaskProgress` | 状态、阶段、进度、日志尾 | `/api/admin/tasks/{id}` |
| `CopyCommand` | 复制 CLI 命令 | `repair.steps[].command` |
| `GlobalSearch` | 材料/概念/题/会话分组搜索 | `/api/admin/search` |
| `PageState` | loading/empty/error/notFound/partial/stale/forbidden | 页面局部状态 |

### 7.3 详情页组合

材料详情页布局沿用当前手写工作台：顶部材料信息 + 历史开关；计数卡；概念/题库题/会话题/会话/引用/块；底部修复计划。react-admin 的 `<Show>` 用自定义布局，不套默认 `<SimpleShowLayout>`。

状态与页面组件的关系：列表/详情的数据请求结果先进入 `PageState`，再由 `ImpactPanel`/`RepairPlan`/`ProvenanceBadge` 渲染内容；错误与空态不穿透到子组件。

## 8. 长任务：统一任务号 + 轮询

### 8.1 任务模型

所有长任务共用一张 `admin_tasks` 表和一个 `task_id`。任务类型只有三个：

| kind | 用途 | 典型 CLI |
|---|---|---|
| `ingest` | 知识摄取：材料入库，可选抽取/确认 | `core.ingest`、`core.extract`、`core.confirm` |
| `rebuild` | 知识重建：重建 FTS/向量索引 | `core.reindex` |
| `evaluate` | 整体评测：跑可用的评测套件 | `bff.probe`、`bff.asr_eval`、`core.eval_questions`、`core.eval_scoring`、`bff.agent_smoke` |

`task_id` 用 UUID4 hex（32 字符），提交时生成，之后所有状态/日志/结果都挂在它下面。

### 8.2 状态机

```text
queued ──► running ──► succeeded
                  ├──► failed
                  ├──► cancelled（可选）
                  └──► awaiting_review
```

- `queued`：已接收，等待 worker。
- `running`：子进程执行中。
- `succeeded`：全部阶段成功。
- `failed`：参数错误之外的执行失败；`error` 必填。
- `awaiting_review`：仅 `ingest`；extract 产出候选，但没有 confirm 决策；任务终止，结果里给 `candidates_path`。
- `cancelled`：用户取消；可选。
- 终态：`succeeded`、`failed`、`cancelled`、`awaiting_review`。

### 8.3 API

**提交任务**

```http
POST /api/admin/tasks
Content-Type: application/json

{"kind": "rebuild", "params": {"fts_only": false, "prune": false}}
```

```http
202 Accepted
{"task_id": "9f2c...", "status": "queued"}
```

- 相同 `kind + params` 已在 `queued/running` 时，返回 200 + 已有 `task_id`，不重复执行。
- 参数非法返回 400，`{"error": "...", "field": "path"}`。

**查询任务**

```http
GET /api/admin/tasks/{task_id}
Cache-Control: no-store
```

```json
{
  "task_id": "9f2c...",
  "kind": "rebuild",
  "status": "running",
  "params": {"fts_only": false, "prune": false},
  "progress": {"phase": "embedding", "current": 40, "total": 120, "message": "..."},
  "log_tail": ["[12:01:03] rebuilding FTS", "[12:01:05] 40/120"],
  "result": null,
  "error": null,
  "created_at": "2026-11-26T12:00:00+08:00",
  "started_at": "2026-11-26T12:00:01+08:00",
  "finished_at": null
}
```

- `log_tail` 只返回最后 20 行或 4KB，避免轮询包变大。
- 终态时 `result` 有值；`failed` 时 `error` 有值。
- `progress` 的 `phase` 一定存在；`current`/`total` 只在能解析 CLI 输出时提供，否则为 `null`。v1 不承诺细粒度百分比。
- 列表：`GET /api/admin/tasks?kind=&status=&page=&per_page=`，返回 `{data,total}`。
- 可选取消：`POST /api/admin/tasks/{task_id}/cancel`，只终止子进程；不回滚已写数据。

### 8.4 轮询契约

- 前端在 `status ∈ {queued, running}` 时轮询 `GET /api/admin/tasks/{task_id}`，间隔 1.5s。
- 超过 30s 仍非终态，间隔退到 5s，避免长任务刷请求。
- 终态停止轮询；`succeeded/failed/awaiting_review` 都显示结果。
- 不使用 HTTP long-poll / SSE / WebSocket；react-admin 页面用自定义 `useTaskPolling` hook，不依赖 react-admin 版本的 query 选项。
- 轮询只读任务表，不触发 provider、不写库。

### 8.5 执行器

- 单 worker 队列：单用户本地，同一时间只跑一个任务；新任务 `queued`。
- 执行器默认在非 fake 模式开启；fake 模式默认关闭，可 `ADMIN_TASK_RUNNER=on` 强制开启；测试环境用 off。
- 子进程：`asyncio.create_subprocess_exec(sys.executable, "-m", ...)`，`cwd=project_root`，`PYTHONUNBUFFERED=1`；逐行读 stdout/stderr 写日志。
- 超时：`ingest` 30 分钟、`rebuild` 60 分钟、`evaluate` 60 分钟；超时终止子进程并标 `failed`。
- 日志：`admin_tasks.log_text` 上限 64KB，只保留尾部；`progress_json` 存结构化进度。
- 重启恢复：启动时把 `running` 标为 `failed`（`error="server restarted before completion"`），`queued` 重新入队；不自动重跑 `running`，避免重复写入。
- 去重：同 `kind + params` 的 `queued/running` 任务返回已有 `task_id`。
- 路径校验：`ingest` 的 `path` 必须是 `materials/` 下的相对路径，后缀 `.md`/`.html`，拒绝 `..`、绝对路径和项目外路径。
- 日志脱敏：`*_API_KEY`、`Authorization`、`Bearer` 等值替换成 `***`。
- 不接收原始命令字符串；kind 到命令的映射在代码里写死。

### 8.6 三类任务参数

#### 8.6.1 `ingest` 知识摄取

```json
{
  "path": "materials/示例材料-a.md",
  "dry_run": false,
  "emit_chunks": true,
  "extract": true,
  "confirm": false,
  "decisions": [],
  "out": null
}
```

- 必填 `path`；其余有默认值。`out` 默认 `data/candidates/{material_id}.chunks.json`，只允许落在 `data/candidates/` 下。
- 阶段：
  1. `dry_run=true`：只跑 `core.ingest --dry-run`，不写 DB，直接 `succeeded`。
  2. `ingest`：`core.ingest --emit-chunks --out data/candidates/{material_id}.chunks.json`；写 `materials`、`material_chunks`、`pipeline_runs`。
  3. `extract`（可选）：`core.extract`；写 `data/candidates/{material_id}.candidates.json`、`pipeline_runs`；调 LLM。
  4. `confirm`（可选）：`core.confirm`；写 `concepts.yaml`、`concept_sources`、`pipeline_runs`。
- **v1 不自动确认**：`confirm=true` 需要非交互的 `--decisions` 适配；未实现前 `confirm=true` 返回 400。`extract=true` 且 `confirm=false` 时任务以 `awaiting_review` 结束，`result.candidates_path` 指向候选文件；确认仍走人工/CLI。
- 不自动跑 `reindex`；材料变更后由用户提交 `rebuild` 任务，或在 UI 提示“下一步重建索引”。
- `result` 包含：`material_id`、`version`、`chunks_parent`、`chunks_child`、`candidates_path`、`pipeline_run_ids`、`skipped_unchanged`。

#### 8.6.2 `rebuild` 知识重建

```json
{
  "fts_only": false,
  "prune": false,
  "model": "text-embedding-v4",
  "dim": 1024
}
```

- 跑 `core.reindex --db ... [--fts-only] [--prune] --model ... --dim ...`。
- `fts_only=true` 不调 embedding provider；否则 provider 未配置时任务 `failed`，错误信息要可读。
- `prune=true` 删除找不到块行的派生索引；是可逆重建，但任务仍会写 DB。
- `result` 包含：`fts_rows`、`embeddings_added`、`embeddings_pruned`、`fts_pruned`、`pipeline_run_ids`。

#### 8.6.3 `evaluate` 整体评测

```json
{
  "suites": ["probe", "asr", "questions", "scoring", "agent"],
  "mode": "auto",
  "inputs": {
    "questions": "docs/designs/review-20261125/questions.json",
    "labels": "docs/designs/review-20261125/labels.json",
    "answers": "docs/designs/review-20261125/answers.json"
  },
  "out": "data/admin-eval"
}
```

- `suites` 白名单：`probe`、`asr`、`questions`、`scoring`、`agent`。
- `mode`：`auto`/`real`/`fake`；`real` 可能产生 API 费用，提交前 UI 二次确认。
- 每个 suite 独立执行：
  - `probe`：`bff.probe`；报告写到 `docs/designs/api-probe/`。
  - `asr`：`bff.asr_eval`；`docs/designs/asr-test-set/audio/` 为空时 `skipped`。
  - `questions`：`core.eval_questions --score`；缺 `questions/labels` 时 `skipped`。
  - `scoring`：`core.eval_scoring --run`；缺 `answers` 时 `skipped`。
  - `agent`：`bff.agent_smoke`；`AGENT_HARNESS=off` 或无配置时 `skipped`。
- 结果：

```json
{
  "passed": false,
  "items": [
    {"name": "probe", "status": "succeeded", "passed": true, "report": "docs/designs/api-probe/..."},
    {"name": "asr", "status": "skipped", "reason": "audio/ 为空"},
    {"name": "scoring", "status": "succeeded", "passed": false, "report": "docs/designs/review-.../scoring-acceptance.md"}
  ]
}
```

- 只有“所有实际执行的 suite 都通过”时 `passed=true`；`skipped` 不计为通过。
- 评测任务只写报告和 `admin_tasks`，不写内容库。
- 报告路径以项目相对路径返回；v1 显示路径 + 复制，不做文件下载/浏览（Phase 2）。

### 8.7 审计与安全

- `admin_tasks` 是后台操作审计：谁在何时提交了什么 kind/params、结果如何。
- `pipeline_runs` 仍是管线审计；任务结果里的 `pipeline_run_ids` 把两者关联起来。
- CLI 需要补一行机器可读的 `pipeline_run_id=<id>`（或 JSON），任务执行器解析；不改现有 stdout 语义。
- 单用户本地默认无认证；远端访问必须加 token。
- 任务执行器不接受任意命令；`path`、`model`、`suites` 都走白名单/路径校验。
- 写任务前 UI 提示备份；`data/app-v5.db` 的 schema v8 迁移是单向的。

### 8.8 失败与恢复

| 场景 | 行为 |
|---|---|
| 参数非法 | 400，不建任务 |
| 已有同 kind+params 在跑 | 200 + 已有 task_id |
| 子进程非 0 | `failed`，`error` 带最后一段 stderr |
| 超时 | 终止子进程，`failed`，`error` 标 timeout |
| 服务重启 | `running` → `failed`；`queued` 重新入队 |
| 用户取消 | 终止子进程，`cancelled`；已写数据保留，需要时用备份恢复 |

## 9. 数据模型

### 9.1 `admin_tasks`（schema v8）

```sql
CREATE TABLE IF NOT EXISTS admin_tasks (
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL CHECK (kind IN ('ingest','rebuild','evaluate')),
  status TEXT NOT NULL CHECK (
    status IN ('queued','running','succeeded','failed','cancelled','awaiting_review')
  ),
  params_json TEXT NOT NULL,
  progress_json TEXT,
  result_json TEXT,
  log_text TEXT,
  error TEXT,
  created_at TEXT NOT NULL,
  started_at TEXT,
  finished_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_admin_tasks_status
  ON admin_tasks(status, created_at);
```

- 只加表，不改现有表；`SCHEMA_VERSION` 7 → 8。
- `log_text` 有 64KB 上限；完整日志不落库。
- 不使用 `pipeline_runs` 代替任务表：`pipeline_runs` 缺 `queued`/`cancelled`/`awaiting_review`、缺 evaluate、缺 params/progress。

### 9.2 迁移

- `init_schema` 追加 `ADMIN_TASK_SCHEMA_SQL`，设置 `user_version=8`。
- 旧代码（`SCHEMA_VERSION=7`）会拒绝打开 v8 库；升级前必须备份 `data/app-v5.db`。
- 回滚需要恢复备份，不能只回退代码。

### 9.3 与 `pipeline_runs` 的关系

- 任务执行器每次调用 CLI，CLI 仍写 `pipeline_runs`。
- 任务结果记录 `pipeline_run_ids`；审计页可以把任务和管线运行串起来。
- 评测任务不写 `pipeline_runs`（不是内容管线）；报告文件 + `admin_tasks` 足够。

## 10. 构建与部署

### 10.1 开发

```bash
cd admin-ui
npm ci
npm run dev          # 5173，/api 代理到 127.0.0.1:8000
```

### 10.2 构建

```bash
cd admin-ui
npm run build        # 产物到 ../web/admin
```

- `vite.config.ts` 的 `base` 必须是 `/admin/`，否则静态资源 404。
- `emptyOutDir: true` 会清掉旧的 `web/admin/`，包括手写 UI；构建前确认已不再需要手写文件。

### 10.3 BFF 托管

- 现有 `bff/main.py` 的 `app.mount("/", StaticFiles(directory=web_dir, html=True))` 直接服务 `web/admin/index.html`。
- 访问 `/admin/`；react-admin 的 hash 路由显示 `/admin/#/materials`。
- 没有 SPA fallback；如果以后改用 browser history，必须在静态挂载前加 `/admin/{path:path}` 返回 `index.html`。
- 学习界面右上角的「管理」链接保持指向 `/admin/`。

### 10.4 回滚

- 代码回滚：`git` 恢复旧版 `bff/`、`core/`、`web/admin/`。
- 数据库回滚：恢复 schema v7 备份；v8 迁移不向下兼容。
- 任务回滚：`ingest`/`rebuild` 的已写数据不回滚；用备份恢复，或重新跑管线修正。

## 11. 测试与验收

### 11.1 API

- 列表接口：分页、排序、过滤、`ids`、空结果、非法枚举 400。
- 详情接口：保持现有测试；新增任务详情。
- 写接口：只允许 `POST /api/admin/tasks`；`PUT/PATCH/DELETE` 404/405。
- 无写：所有只读 GET 前后 `PRAGMA data_version` / `total_changes` 不变。

### 11.2 任务执行器

- 用 fake command runner 替代真实子进程，测试：
  - `queued → running → succeeded`
  - 非 0 退出 → `failed`
  - 超时 → `failed`
  - 重复提交 → 返回已有 task_id
  - 重启恢复：`running` → `failed`，`queued` 重新入队
  - 路径穿越/绝对路径 → 400
  - 日志脱敏
- 真实 CLI 只在验收环境跑一次 `rebuild`（fts-only）和 `ingest --dry-run`；不在单测里调 LLM/embedding。

### 11.3 前端

- 数据提供器单测（vitest）：URL 映射、分页参数、`getOne` 包装、`update/delete` 抛错。
- Playwright：
  - `/admin/` 加载 Dashboard，健康条渲染。
  - 材料列表 → 详情 → 影响面/修复计划 → 复制命令。
  - 任务列表 → 新建 `rebuild`（fts-only）→ 轮询到终态。
  - 评测任务缺输入时显示 skipped。
  - 无 console error。

### 11.4 验收标准

1. `/admin/` 由 react-admin 构建产物提供，不再有手写 `web/admin/*.js`。
2. 9 个 v1 资源都有列表 + 详情；只读资源没有新建/编辑/删除入口。
3. 三类任务都返回 `task_id`，前端只轮询；任务结束后结果可见。
4. `rebuild` 任务能在真实库副本上完成，并更新 FTS（`fts_only=true` 不调 embedding）。
5. `ingest --dry-run` 任务不写库；`ingest` 任务写 `materials`/`pipeline_runs`。
6. `evaluate` 任务对缺失输入显示 `skipped`，不把跳过算通过。
7. 只读 GET 不写库；任务接口是唯一长写入口。
8. schema v7 → v8 迁移在库副本上通过；升级前有备份。

## 12. 分阶段

### Phase 1（本设计）

- `admin-ui/` 脚手架、Vite 构建、BFF 托管。
- Dashboard + 8 个只读资源（sessions、conversations、materials、concepts、bank_questions、session_questions、pipeline_runs、tasks）。
- 材料/概念详情保留影响面与修复计划。
- `admin_tasks` v8、任务 API、单 worker、轮询 UI。
- `ingest`（含 dry-run/extract，不自动 confirm）、`rebuild`、`evaluate` 三类任务。
- 删除手写 `web/admin/index.html`、`admin.css`、`admin.js`。

### Phase 2

- 热项 discard/promote。
- 题目审核（先补 `question_cache` 状态机）。
- 人格/记忆/心情只读页面。
- 审计页（任务 + 管线运行合并视图）。
- 评测报告浏览/对比、任务取消。
- 可选 `ADMIN_TOKEN`。

### 不做

- 多用户、角色、登录体系。
- 外部来源采集器/域名策略。
- 在线编辑 `materials/`、`concepts.yaml`、`seeds/question_bank.json`、`persona.yaml`。
- 直接在后台改历史 `session_questions` 的分数/答案。

## 13. 已确认决定

1. **构建产物不提交**：`admin-ui/node_modules/` 与 `web/admin/` 都忽略；部署前 `cd admin-ui && npm ci && npm run build`，再启动 BFF。仓库只保留 `admin-ui/` 源码。
2. **ingest 不自动确认**：v1 任务最多跑到 extract，产出 candidates 后停在 `awaiting_review`；`concepts.yaml` 的确认仍走人工/CLI。非交互 `--decisions` 留到 Phase 2。
3. **热项动作放 Phase 2**：v1 热项只读；放弃/晋升在 Phase 2 再加，避免第一版多一个写接口和审计口径。

## 14. 与当前手写后台的关系

- 保留 `core/admin_queries.py`、`core/admin_repair.py`、`bff/admin.py` 的查询逻辑；新增列表与任务接口。
- 保留材料/概念/题/会话详情的影响面与修复计划，作为 react-admin 自定义组件。
- 删除手写 `web/admin/index.html`、`admin.css`、`admin.js`；构建产物覆盖 `web/admin/`。
- 现有 `tests/test_admin_queries.py`、`tests/test_admin_api.py`、`tests/test_admin_acceptance.py` 继续覆盖 API；新增列表/任务/数据提供器测试。
- 学习界面右上角的「管理」链接不变，仍指向 `/admin/`。
