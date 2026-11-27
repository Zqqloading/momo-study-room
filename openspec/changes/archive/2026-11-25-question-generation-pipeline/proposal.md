# Proposal

## Why

出题仍是壳：`Coach.start` 从 `question_bank` 取预写题，按 `recall / discriminate / apply` 配比；题目与当天材料、检索结果没有关系，也无法回答“这道题从哪来”。检索（FTS5 + 向量 + RRF）与逐题评分已经可用，但两者没有接成一条考评管线。

本 change 把“查资料考用户”做实：每次学习现场从本地知识库检索材料，生成 5 道业务/产品视角题，逐题作答、逐题评分，每题可溯源。外部补充链路本轮不做，按 ADR 0002 记录为后续。

两轮 spike 已先验：DeepSeek 一次 5 题完整可解析；10 题盲评题型/理解/业务视角/溯源均 10/10；8 条标准答案评分 8/8 同档，2/2 跳题不评分。MiMo 因单次输出约 600-700 汉字被淘汰。

## What Changes

- 新增现场出题管线：`Coach.start` 先建 `SessionPlan`，把概念主出处放 `[1]`、检索结果去重后置，调 DeepSeek 一次生成 5 题；整场校验后逐题下发。
- 五型各 1：概念理解、业务运用、取舍权衡、成本风险、综合判断；槽位与题型由程序固定，模型只写题干/参考答案/`must_have`/`red_flags`；五档 rubric 由程序生成。
- 场次构成：最多 2 道复习 + 3 道新概念；复习只取 1 个最逾期概念；无复习时 5 题全考新概念；只有复习时 5 题全考复习概念。
- **BREAKING**：每日会话不再使用“2 recall + 2 discriminate + 1 apply”配比；生成题全部开放题，旧题库只在生成失败时回退。
- 生成失败/材料不足：1 次生成 + 1 次修复；仍失败回退旧题库并标 `fallback`，不阻塞会话、不计入生成验收。
- 溯源：每题携带逐字 `source_excerpt`、`source_chunk_id`、`source_url`、生成元数据；作答前只显示题型，评分后显示出处。
- 评分：保留逐题即时、五档、重试一次、`unscored` 语义；新增题型封顶与反背诵规则；显式约束 `session_misconception` 只能是 null 或对象。
- 数据：`session_questions` 加法 `question_type`、`source_chunk_id`、`generation_meta_json`（schema v6）。
- 出题只用本地已确认知识库；不搜网页、不读 `hot_items`、不写 `question_bank`/seeds。

## Capabilities

### New Capabilities

- `question-generation`: 现场生成五型业务题、槽位/题型固定、compact 契约、逐字+语义溯源、修复与回退、无外部来源；题目落 `session_questions`。

### Modified Capabilities

- `coach-session`: 会话启动从题库配比改为 SessionPlan + 生成 + 回退；2 复习 + 3 新概念；生成题全开放；题型感知评分与反背诵；`question`/`score`/`session_result` 事件带题型与出处。
- `knowledge-retrieval`: 增加“出题检索”场景：概念名 + 别名 + 定义 → 主出处 + top5 父块；返回 `chunk_id`/`parent_chunk_id`；自由对话检索契约不变。

## Impact

- 代码：`core/question_generation.py`（新增）、`bff/question_generation.py`（新增）、`core/coach.py`、`core/scoring.py`、`core/retrieval.py`、`core/store.py`、`core/ports.py`、`bff/main.py`、`web/app.js`、`web/style.css`。
- 数据：`SCHEMA_VERSION` 5 → 6，`session_questions` 加三列；旧行新列为 NULL；不重建表。
- 依赖：DeepSeek 同时承担生成与评分；MiMo 不再用于出题。自评偏好风险靠 10 条人工一致率 gate。
- 文档：`docs/designs/assessment-pipeline-v0.1.md`、`docs/designs/review-20261124/`、`docs/adr/0002-no-external-supplement-for-scoring-questions.md`、`FREEZE.md` 待变更登记、`VERSIONS.md`。
- 验收：10 题盲评（题型/理解 ≥8/10，业务视角/溯源 10/10）；10 个标准答案评分（8 条已答 ≥6/8 同档 + 2 条跳题不评分）；改动后用全新 10 条 holdout。
