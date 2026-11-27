# Design

## Context

- 当前是 Web 单页：`web/index.html` + `web/app.js`；`#start` 直接发送 `session_start`，没有提议确认。
- `Coach.start()` 内部完成选题：`Planner.next_concept` 选主概念，`_pick_review_concept` 取最逾期 1 个复习概念，`build_session_plan` 固定 5 个槽位。
- `Settlement.mastery` 只有更新后的 map（concept id → 数字）；结果卡原样打印该 map，没有概念名、标签或 before 值。
- 没有知识库界面，也没有 JSON 读接口；只有 `/health`、`/ws` 与静态资源。
- 数据层已有 `concepts`、`sessions`、`session_questions`、`agent_sessions`；当前 `SCHEMA_VERSION=6`。
- 行为契约见 `specs/learning-unit/spec.md` 与 `specs/coach-session/spec.md`；完整产品口径、JSON 示例与测试映射见 `docs/designs/learning-unit-v0.1.md`。
- 约束：不改冻结的 mastery 公式、5 题配比与复习规则；不新增表/列；不改语音、3D 形象、出题与评分链路。

## Goals / Non-Goals

**Goals:**

- 在知识库面板里提供只读「今天学什么」提议，并复用现有选题，保证提议与实际开始一致。
- 单元结束后给出每概念 before→after、本场概念得分与全库掌握程度总览。
- 让面板与 `/api/kb/*` 成为可整体搬到管理后台的边界。
- 保持现有会话协议、mastery 规则与测试路径不回归。

**Non-Goals:**

- 不做跨天单元、课程编排、日历、单元状态机或独立单元表。
- 不做材料/概念管理、概念确认页、题库审计；这些属于后续管理后台。
- 不改 mastery 公式、5 题配比、复习间隔、出题/评分/语音/3D。
- 不在 v0 做「换一个提议」、plan token 或强制先看提议。

## Decisions

### D1：学习单元 = 一场 5 题会话，不新增单元状态

单元直接复用 `sessions` + `session_questions`，`session_id` 就是单元标识；当天可重开多场。这样不需要新表、迁移或跨天恢复逻辑，且与冻结版的每日闭环一致。

**Alternatives considered:**

- 独立 `learning_units` 表：能记录跨场次进度，但要定义开始/完成/放弃状态、迁移与恢复，超出当前需求。
- 单元 = 一个概念（跨多场）：需要「单元完成」判定与跨天状态机，且与现有 mastery 三次均值的节奏重叠。
- 单元 = 一份材料/章节：需要章节到概念的映射与编排，工作量最大。

### D2：提议是只读的 `Coach.propose()`，复用同一套选题

新增 `Coach.propose()`：调用 `Planner.next_concept`、`store.due_reviews` 与 `build_session_plan`，返回主概念、复习概念、理由、槽位与可用性。不写库、不调模型、不生成题目；`Coach.start()` 复用同一段选题代码，避免两套逻辑漂移。

**Alternatives considered:**

- 另写一套提议选题：会与 `start` 的优先级/排序产生偏差。
- 用 LLM 生成提议：慢、不可复现，且可能建议题库里没有出处的概念；提议只需要解释既有选择。
- 提议时预生成题目：会把只读预览变成写路径，并放大延迟；题目生成仍留在 `start`。

### D3：开始仍走 `session_start`，不传概念 id

面板只负责关闭自己并调用现有 `startSession()`；`session_start` 形状不变。提议是预览，`start` 重新计算；同一标签页、同一天内概念状态不变，结果一致。跨天/多标签页以 `start` 实际结果为准，v0 不引入 plan token。

**Alternatives considered:**

- 传 plan token 冻结提议：能消除漂移，但要新增提议存储/过期语义；当前单用户本地应用不需要。
- 提议时直接创建 `agent_sessions`：会让「只看一眼」也产生运行态会话，增加清理负担。

### D4：结算摘要的 before 在 `finalize` 前捕获，after/due 在 `finalize` 后读取

`Coach.finish()` 在调用 `store.finalize()` 之前读取本场涉及概念的 `mastery`，结算后重新读取 after 与 `review_due_at`，据此构造 `ConceptUnitResult`。概念得分从本次 `session_questions` 按 `concept_id` + `question_role` 聚合已评分题；mastery 仍由既有 `_mastery_updates` 计算，摘要不重复计算、不额外写库。

**Alternatives considered:**

- 结算后从 `sessions` 反推 before：需要重建历史 mastery，且错过事件后不可靠；在 `finish` 内捕获最简单。
- 新增摘要表/列：会引入冗余与迁移；摘要可以按需重算，v0 不持久化。
- 单独再查一次空会话：没有解决 before 已被覆盖的问题。

### D5：读接口用 HTTP，事件用 WS 加法字段

提议与总览是只读、无会话状态的数据，使用 `GET /api/kb/unit/proposal` 与 `GET /api/kb/overview`；会话事件仍走 WS，只给 `session_ready` 加 `unit`、给 `session_result` 加 `concepts`。这样面板不需要长连接，旧客户端忽略新字段即可。

**Alternatives considered:**

- 全部走 WS：要新增消息类型与请求/响应关联，读接口却与会话生命周期无关。
- 全部走 HTTP：结算摘要在会话事务内产生，走 WS 更自然，也避免结算后再查一次。

### D6：读模型独立成 `core/progress.py` + `bff/knowledge.py`

`core/progress.py` 负责 active 概念平均 mastery、0–5 分布、weak/due/overdue、标签与最近单元；`bff/knowledge.py` 只做 HTTP 序列化与路由。`core/models.py` 放 `MASTERY_LABELS` 与提议/摘要数据类，避免 Coach 与 progress 相互依赖。

**Alternatives considered:**

- 全部写在 `bff/main.py`：会让本已 1000+ 行的入口继续膨胀，也不利于单测。
- 全部写在 `core/coach.py`：Coach 会混入读模型与展示口径，职责过重。
- 让前端算总览：需要多轮查询与重复口径，且管理后台无法复用。

### D7：面板自包含，可整体搬到管理后台

新增 `web/kb.js` + `#kbpanel` + `.kb-*` 样式；`app.js` 只接线「知识库」按钮、`canStartUnit()` 与 `onStartUnit()`。面板只依赖 `/api/kb/*` 和开始回调，不碰 3D、音频、WS 内部状态。

**Alternatives considered:**

- 直接写进 `app.js`：文件已 1500+ 行，搬迁时要拆。
- 新建 `/knowledge` 独立页面：要处理路由、跨页状态与开始会话的交接，v0 成本更高。
- 改主界面为左右两栏：会动现有布局与验收路径，超出临时宿主的需求。

### D8：数据口径

- 总览只列 `active` 概念；`known`/`skipped`/`proposed`/`orphaned` 只给计数。
- `weak` = `mastery <= 1` 且 `last_seen` 非空；从未学过的 0 不算薄弱。
- `due` = `review_due_at <= today`；`overdue` = 早于 today。
- 标签只用于展示：0 未掌握、1 初识、2 有印象、3 基本掌握、4 熟练、5 精通；不写库、不参与计算。
- 平均掌握度显示一位小数 + `/ 5`，不换算百分比。

**Alternatives considered:**

- 总览列全部概念：临时面板会膨胀，且 known/skipped 不是「在学」。
- weak 包含未学概念：会把「新」误标成「弱」。
- 持久化标签：文案调整需要迁移，收益低。

### D9：旧「开始今天的学习」保留为快捷开始

不改变现有浏览器验收脚本的点击路径（`tests/browser/check_question_ui.mjs` 点 `#start` 等 `session_start`），也不给熟练用户增加一次点击；带提议的入口是新的「知识库」面板。

**Alternatives considered:**

- 主按钮改为先开面板：产品上更统一，但会改变现有交互与测试；等管理后台落地后再统一入口。

## Data Flow

```text
知识库面板打开
  ├─ GET /api/kb/unit/proposal → Coach.propose() → Planner + due_reviews + build_session_plan
  └─ GET /api/kb/overview      → core.progress.build_overview() → concepts + sessions + questions
点「开始这个单元」
  └─ 关闭面板 → WS session_start → Coach.start()（原流程）
       └─ session_ready + unit（主/复习概念名）
5 题逐题评分
  └─ session_result + concepts[]（before/after、均分、updated、due）
       └─ 结果卡 + 异步 GET /api/kb/overview 全库一行
```

## Code Landing

| 文件 | 改动 |
|---|---|
| `core/models.py` | `MASTERY_LABELS`、`ProposalConcept`、`ProposalSlot`、`UnitProposal`、`ConceptUnitResult` |
| `core/coach.py` | `propose()`；`start()` 复用选题；`finish()` 捕获 before、生成 `concepts` 摘要 |
| `core/progress.py` | 新增 `build_overview()`、`ConceptProgress`/`ProgressStats`/`UnitHistoryItem`/`ProgressOverview` |
| `core/store.py` | 增加 `recent_units(limit=5)`；不改表结构 |
| `bff/knowledge.py` | 新增两个 GET 路由；用 `app.state.store`/`concepts`/`clock` |
| `bff/main.py` | 注册 router；`session_ready`/`session_resume` 增加 `unit`；`_result_event` 序列化 `concepts` |
| `web/index.html` | `#actions` 加「知识库」；新增 `#kbpanel` 与 `#unitlabel` |
| `web/kb.js` | 面板打开/关闭、并行请求、提议/总览/最近单元渲染、开始回调、错误与空状态 |
| `web/app.js` | 接线面板；`showResult()` 用 `result.concepts`；`session_ready` 显示 `unit` |
| `web/style.css` | 面板、分布条、掌握度点、概念列表、移动端 sheet |

`unit` 由 BFF 统一从 `session_questions` 推导（`role=new` 为主概念、`role=review` 为复习概念），start 与 resume 共用同一 helper；概念名缺失时回退 id。

## Risks / Trade-offs

- **提议与开始漂移**（跨天/多标签页）→ 提议只作预览，`start` 重算并以实际结果为准；v0 不冻结计划，后续需要再加 token。
- **错过 `session_result` 丢 before→after** → 总览与最近单元仍显示最新 mastery 与本场分数；摘要可按历史 `sessions` + `session_questions` 重算，不落库。
- **before 捕获时机错误** → 必须在 `finalize()` 前读取；用 completed/partial/unscored/review-only/同概念五类结算测试锁住。
- **总览查询拖慢面板** → 只查 active 概念；最近单元限 5 条；当前数据量小，必要时再加索引。
- **面板扩大成知识库管理页** → 明确 v0 只做今日单元/掌握程度/最近单元，材料管理留管理后台。
- **旧客户端不识别新字段** → 全部加法；`mastery`、`scores`、`review_due_at` 保留原语义。
- **标签文案与 mastery 混淆** → 标签只展示、不写库；总览用 `x.x / 5`，不换算百分比。

## Migration Plan

- 无 schema/数据迁移；`SCHEMA_VERSION=6` 不变。
- 部署顺序：core 读模型与提议 → 结算摘要 → HTTP 路由 → WS 加法字段 → 前端面板与结果卡。
- 回滚：隐藏「知识库」按钮与面板即可停用新入口；服务端新字段为加法，旧前端不受影响；无数据库回滚步骤。
- 后续搬到管理后台时，复用 `/api/kb/*`、`web/kb.js` 与 `#kbpanel` 标记，只替换入口与 `onStartUnit()` 回调。

## Open Questions

- `known`/`skipped` 是否需要在总览展开列表？v0 只给计数，管理后台再加。
- 单元历史是否需要详情页？v0 只显示日期/状态/分数/概念名，逐题明细留在 `session_questions`。
- 掌握度标签文案是否要更学术？当前为中性六级，可只改文案。
- 管理后台落地后是否加鉴权？当前本地应用无鉴权，搬到后台时再加。
