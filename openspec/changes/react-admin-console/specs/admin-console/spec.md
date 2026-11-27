# Spec Delta

## Purpose

为单用户本地应用提供统一的管理后台读取面：资源列表与详情、只读/可写边界、内容影响面、健康状态与全局搜索，由同一个 BFF 托管。

## ADDED Requirements

### Requirement: 管理后台由同一个 BFF 托管

系统 SHALL 在同一个 BFF 的 `/admin/` 路径提供管理后台单页应用，使用 hash 路由；MUST NOT 要求额外前端服务或服务端 SPA fallback。

#### Scenario: 访问管理后台

- **WHEN** 浏览器请求 `GET /admin/`
- **THEN** BFF 返回管理后台的 `index.html`，静态资源从 `/admin/` 下加载

#### Scenario: 深链接

- **WHEN** 浏览器打开 `/admin/#/materials`
- **THEN** 管理后台显示材料列表，服务端只收到 `/admin/` 请求

### Requirement: 资源列表契约

系统 SHALL 为材料、概念、题库题、会话题、学习会话、自由对话、管线运行和任务提供列表接口；每个列表 MUST 返回 `{data,total}`，并支持 `page`、`per_page`、`sort`、`order`、资源过滤与 `ids` 批量。

#### Scenario: 分页与过滤

- **WHEN** 客户端请求 `GET /api/admin/materials?page=2&per_page=10&status=active`
- **THEN** 响应包含第二页的 `data` 与过滤后的 `total`

#### Scenario: 批量取记录

- **WHEN** 客户端请求 `GET /api/admin/concepts?ids=a,b,c`
- **THEN** 响应只包含这三个概念的记录

#### Scenario: 非法排序

- **WHEN** 客户端请求未在排序白名单中的 `sort` 值
- **THEN** 响应返回 400 与可读错误

### Requirement: 内容资源只读

材料、概念、题库题、会话题、学习会话、自由对话和管线运行 SHALL 只读；系统 MUST NOT 为这些资源提供创建、更新或删除接口，读取请求 MUST NOT 写数据库。

#### Scenario: 拒绝对内容资源的写请求

- **WHEN** 客户端对 `/api/admin/materials/{id}` 发起 `PUT`、`PATCH` 或 `DELETE`
- **THEN** 响应返回 405 或 404，数据库内容不变

#### Scenario: 读取不写库

- **WHEN** 客户端连续调用只读列表与详情接口
- **THEN** 数据库的 `data_version` 与写入计数保持不变

### Requirement: 唯一长写入口是任务提交

系统 SHALL 只通过 `POST /api/admin/tasks` 接受会改变数据库内容或派生数据的后台长写操作；材料上传 SHALL 只新增 `materials/inbox/` 文件，不写 DB；热项动作在 Phase 2 单独增加；内容真相源 MUST NOT 通过后台直接编辑。

#### Scenario: 接受任务提交

- **WHEN** 客户端提交合法的 `kind` 与 `params`
- **THEN** 系统返回 202、`task_id` 与 `status=queued`

#### Scenario: 拒绝直接内容写入

- **WHEN** 客户端尝试通过后台更新材料正文、`concepts.yaml` 或题库 seeds
- **THEN** 系统不提供对应接口，请求返回 404 或 405

### Requirement: 材料上传

系统 SHALL 提供 `POST /api/admin/uploads` 接收 multipart 文件，只允许 `.md` / `.html`，保存到 `materials/inbox/`；同名文件 MUST NOT 被覆盖；单文件 MUST 限制大小；上传 MUST NOT 写数据库或自动触发摄取，成功时返回相对路径供摄取任务使用。

#### Scenario: 上传合法材料

- **WHEN** 客户端上传 `note.md`
- **THEN** 文件保存为 `materials/inbox/note.md`，响应返回该相对路径

#### Scenario: 拒绝不支持的扩展名

- **WHEN** 客户端上传 `note.txt`
- **THEN** 响应返回 400，不写文件

#### Scenario: 同名文件

- **WHEN** `materials/inbox/note.md` 已存在，客户端再次上传同名文件
- **THEN** 响应返回 409，不覆盖原文件

#### Scenario: 超出大小限制

- **WHEN** 单个文件超过配置上限
- **THEN** 响应返回 413，不写文件

#### Scenario: 文件名带路径

- **WHEN** 客户端上传的文件名是 `../evil.md`
- **THEN** 系统只取 basename，保存为 `materials/inbox/evil.md`，不写到 inbox 之外

### Requirement: 材料扫描与批量摄取

系统 SHALL 提供 `GET /api/admin/materials/scan`，递归扫描 `materials/` 下的 `.md` / `.html`，按 `path + content_hash` 与数据库比较，返回新增、变更、未变和缺失；扫描 MUST NOT 写数据库或自动提交任务。客户端 SHALL 能对选中的新增/变更文件逐个提交 ingest 任务。

#### Scenario: 发现新增文件

- **WHEN** `materials/` 下存在数据库没有的 `.md` 文件
- **THEN** 扫描结果的 `new` 包含该文件路径

#### Scenario: 发现内容变化

- **WHEN** 已入库材料文件内容哈希与 DB 不一致
- **THEN** 扫描结果的 `changed` 包含该文件与当前 DB 版本

#### Scenario: 发现磁盘缺失

- **WHEN** DB 中材料路径在 `materials/` 下不存在
- **THEN** 扫描结果的 `missing` 包含该材料

#### Scenario: 批量提交摄取

- **WHEN** 客户端对一个或多个扫描结果提交摄取
- **THEN** 每个选中文件创建一个独立 ingest 任务，扫描接口本身不写库



### Requirement: 内容影响面与修复计划

材料、概念、题库题、会话题和学习会话的详情 SHALL 保留双向影响面、溯源级别（块级、URL 级、仅概念级、未匹配）与修复计划；每个修复步骤 MUST 说明前置条件与可跳过条件。

#### Scenario: 材料影响面

- **WHEN** 客户端查看材料详情
- **THEN** 响应包含块、概念、题库题、会话题、会话与自由对话引用的计数和列表

#### Scenario: 题库题与生成题的溯源差异

- **WHEN** 客户端查看一条题库题和一条生成题
- **THEN** 题库题标为 URL 级，生成题在能解析 `source_chunk_id` 时标为块级

#### Scenario: 修复计划

- **WHEN** 客户端查看材料、概念或题库题详情
- **THEN** 响应包含带前置条件、命令和可跳过条件的修复步骤

### Requirement: Dashboard 健康状态

系统 SHALL 在 Dashboard 显示库版本不匹配、provider fake、最近一次管线失败三类红色状态，以及索引缺失黄色状态；同时显示材料、题库题、会话等计数。

#### Scenario: provider 在 fake 模式

- **WHEN** 任一 provider 使用 fake 模式
- **THEN** Dashboard 显示红色 provider 状态

#### Scenario: 索引待补

- **WHEN** 当前版本存在缺失的 FTS 或 embedding 行
- **THEN** Dashboard 显示黄色索引状态

### Requirement: 全局搜索

系统 SHALL 提供跨材料、概念、题库题、会话题、学习会话和自由对话的全局搜索，结果 MUST 按组返回并支持空查询。

#### Scenario: 搜索分组

- **WHEN** 客户端搜索一个同时命中材料和概念的关键词
- **THEN** 响应按材料、概念、题、会话分组返回结果

#### Scenario: 空查询

- **WHEN** 客户端提交空关键词
- **THEN** 响应返回空分组，不报错

### Requirement: 页面状态、导航与失败落点

每个列表与详情页面 SHALL 定义 loading、empty、error、partial 状态；列表状态（page、per_page、sort、order、筛选、q）MUST 保存在 URL；失败 MUST 落在同一页面并提供重试或明确的返回入口，MUST NOT 出现白屏或裸 JSON。

#### Scenario: 列表加载失败

- **WHEN** 列表请求返回 5xx
- **THEN** 原列表路由显示错误面板与重试，筛选与分页保留

#### Scenario: 详情不存在

- **WHEN** 客户端打开不存在的实体 id
- **THEN** 显示 NotFound 与返回列表入口，不自动重定向

#### Scenario: 任务提交成功后的导航

- **WHEN** 任务提交返回 202
- **THEN** 页面 replace 到任务详情；浏览器 back 回到来源页而不是已提交的表单

#### Scenario: 非法 query

- **WHEN** 列表 URL 的 `page` 不是合法数字
- **THEN** 页面回到第 1 页并提示，不显示 400 错误页

#### Scenario: 部分数据失败

- **WHEN** 详情页只有部分子区块请求失败
- **THEN** 可用区块继续渲染，失败区块标注原因，不整页失败

