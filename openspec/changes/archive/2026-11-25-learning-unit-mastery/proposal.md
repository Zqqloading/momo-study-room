# Proposal

## Why

当前用户点「开始今天的学习」会直接进入 5 题会话：看不到今天为什么学这个、复习什么；学完结果卡只打印 concept id 级别的 mastery，也没有知识库界面承载单元与掌握程度。`docs/designs/learning-unit-v0.1.md` 已把产品口径定下来：学习单元 = 一场 5 题会话，先提议再开始，结束后展示本单元前后变化与全库总览。现在把这个设计落成可实施的变更。

## What Changes

- 新增只读「今日单元提议」：复用 Coach 的选题逻辑，返回主概念、复习概念、理由、5 个题型槽位与约 20 分钟；不写库、不调模型、不生成题目。
- 新增只读「掌握程度总览」：在学概念平均 mastery、0–5 分布、薄弱项、待复习、最近单元。
- 主页面新增临时「知识库」面板，承载今日单元、掌握程度与最近单元；开始单元仍走现有 `session_start`，会话、评分、语音、3D 形象不变。
- `session_ready` 增加只读 `unit` 字段（主概念/复习概念名）；`session_result` 增加 `concepts` 摘要（每概念 before/after、新题/复习均分、是否更新、结算后的复习到期日）。
- 结果卡改为显示概念名、标签与 before→after，不再显示原始 concept id；`partial`/`unscored`/review-only 必须显式写「掌握度未更新」及原因。
- 不新增表或列，不改 mastery 公式、5 题配比、复习规则、出题/评分/语音链路；WS 字段全部为加法，旧客户端忽略即可。

## Capabilities

### New Capabilities

- `learning-unit`: 今日单元提议、掌握程度总览、临时知识库面板；只读、不新增存储，后续可整体搬到管理后台。

### Modified Capabilities

- `coach-session`: `session_ready` 增加 `unit`；`session_result` 增加 `concepts` 摘要；明确 `partial`/`unscored`/review-only 的掌握度展示语义，mastery 计算与复习调度规则不变。

## Impact

- 代码：`core/models.py`、`core/coach.py`、`core/progress.py`、`core/store.py`、`bff/knowledge.py`、`bff/main.py`、`web/index.html`、`web/app.js`、`web/kb.js`、`web/style.css`
- API：新增 `GET /api/kb/unit/proposal`、`GET /api/kb/overview`；WS `session_ready`/`session_result` 加法字段
- 数据：无 schema 变更；只读 `concepts`、`sessions`、`session_questions`
- 测试：新增 `test_proposal`、`test_progress`、`test_kb_api`；扩展 `test_settlement`、`test_ws`；新增浏览器 smoke
- 依赖：无新增
