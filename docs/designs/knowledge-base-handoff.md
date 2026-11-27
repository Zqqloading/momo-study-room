# 知识库设计交接文档

- 日期：2026-11-23
- 用途：本会话只推进 agent 基础设施；知识库设计移交到另一个工作区继续。
- 接收方先读：本文 → `docs/designs/learning-companion-digital-human-v2.0.md` 的知识库章节 → `docs/designs/agent-infrastructure-v0.1.md`。
- 本文**不是**知识库设计正文，只是交接简报：已定什么、没定什么、接口边界、建议的下一步。
- 2026-11-23 更新：知识库设计已拆分为 `knowledge-ingestion-v0.1.md`（入库）与 `knowledge-retrieval-v0.1.md`（检索）；本文档保留为交接快照，旧文件名 `knowledge-base-v0.1.md` 不再使用。

## 1. 项目上下文（最少必要）

产品是一个数字人学习伴侣：每天 20 分钟，围绕一个 agent 理论概念，要求用户用大白话讲解，再做五道自测题；分数、误解、掌握度进入记忆，第二天按 `review_due_at` 调整内容。语音为主，打字兜底；单用户、本地、Windows。

当前状态：

- 设计 v2.0 已 **FROZEN**（2026-11-23，SHA-256 `c9e604c4…`）。
- 本会话新增 `docs/designs/agent-infrastructure-v0.1.md`（DRAFT），只覆盖 agent 运行时。
- 知识库的设计、实现、材料与题库都还没有落地；仓库里没有 `materials/`、`concepts.yaml`、`seeds/`。
- 代码里已有 `core/db.py` 的 `question_bank` 表、`core/concepts.py` 的 YAML 加载、`core/store.py` 的幂等导入；这些是给知识库预留的落点。

分工：

| 文档 | 负责 |
|---|---|
| `learning-companion-digital-human-v2.0.md` | 产品与知识库的冻结依据 |
| `agent-infrastructure-v0.1.md` | 会话编排、考评、运行时存储、WS 事件 |
| `knowledge-base-v0.1.md`（待写） | 材料、切块、概念、题库、检索、联网入口 |

## 2. 知识库必须支撑的产品行为

1. **首次初始化**：用户把 1-3 份材料放进 `materials/` → 抽取候选概念 → 逐条确认“要学/已掌握/不学” → 生成首批题目 → 抽查。不做摸底，概念从 `mastery=0` 开始，首批须含无前置的根概念。
2. **每日会话**：Planner 只从 `active` 概念里选；前置 `mastery >= 3` 或 `skipped` 才解锁；优先级是未解误解 > 到期复习 > 新概念；每天一个新概念、最多 2 道复习、总量 5 题。
3. **出题**：每题必须能指到 `concept_sources` 的 `source_url` 和 `source_excerpt`；指不到就不出题。
4. **增量更新**：只对新增/变更的材料块抽概念；已有概念只更新出处，不重置 mastery。
5. **检索（v1）**：题目生成前用子块召回，命中后回溯父块；FTS5 trigram + 向量混合，RRF 融合。
6. **联网**：只作为材料入口或超纲兜底，**不进入每轮作答热路径**。

## 3. 已经定下的决策（不要重新论证）

| 决策 | 内容 | 来源 |
|---|---|---|
| 材料格式 | v0/v1 收 Markdown/HTML；v2 加 PDF。HTML 只取正文 | v2.0 §材料怎么进来 |
| 切块 | 父块按标题 600-1000 token；子块按段落 150-250 token；子块 10% 重叠 | v2.0 §切块与抽概念 |
| 抽概念 | 用父块，每块最多 3 个；字段 `name, aliases, plain_def, prerequisites, source_url, source_excerpt, difficulty 1-3` | v2.0 §切块与抽概念 |
| 质量门槛 | `plain_def` ≤60 字、无套话、必须有摘录、名字必须是术语；同块最多 3 个概念 | v2.0 §切块与抽概念 / §失败与降级 |
| 去重 | 语义相似度 >0.9 合并；0.75-0.9 进待确认，不自动合并 | v2.0 §切块与抽概念 |
| 出处 | 每个概念、每道题都必须有 `source_url` + `source_excerpt`；v0 就记录 | v2.0 Constraints / 出题质量门槛 |
| 内容真相 | `concepts.yaml` 是概念内容唯一真相源；SQLite 只存运行时状态 | v2.0 §概念地图 |
| 检索 | v1 采用 FTS5 trigram + 向量相似度混合、RRF；embedding 模型待定 | v2.0 D3 / Open Question 5 |
| 检索时机 | v0 不检索；v1 在题目生成前检索，题目与出处一起缓存 `question_cache` | v2.0 §题目来源 / tech plan §12 |
| 联网边界 | 只做材料入口或超纲兜底；不进每轮热路径 | v2.0 P3 / agent 文档 §1.4、§3.1 |
| 数据模型 | `materials`、`material_chunks`、`concept_sources`、`question_cache` | v2.0 §数据模型补充 |
| 增量 | 按内容哈希 + version；旧版本块保留，检索只用最新版本 | v2.0 §材料更新 |

## 4. 尚未定、需要在新工作区拍板

1. **embedding 模型**：本地还是 API、维度、成本、中文效果。v1 开工前必须定。
2. **首批材料**：具体放哪 1-3 份、每份多大、从哪来；90 天目标节点数（起步 10 / 目标 40 是占位）。
3. **联网种子流程**：怎么抓网页、怎么记录 `source_url`、版权/可引用边界、是否人工确认。
4. **中文切块**：tokenizer 选型（模型分词器 / tiktoken 近似）、中文 trigram 召回实测。
5. **题目生成**：v0 手写题库 vs 模型生成后人工抽查；生成失败/超时的回退策略。
6. **DB 布局**：知识表与 agent 运行时表同库（`data/app.db`）还是分库（`data/knowledge.db`）。建议 v0/v1 同库，减少连接与事务复杂度；分库留到材料量变大时再评估。
7. **Retriever 端口形状**：见第 5 节建议；是否同步/异步、返回 top_k 与分数、是否返回父块全文。
8. **概念确认页的交互**：批量勾选、按难度筛选、已掌握/不学的后果提示；这是 UI，但会影响知识库接口。
9. **材料删除/回滚**：`orphaned` 状态、`prior_status` 恢复、是否保留历史块。
10. **文档版本**：`knowledge-base-v0.1.md` 是否也按六条框架，决策 ID 用 `KB-01…`。

## 5. 与 agent 基础设施的接口

知识库与 agent 的边界：

- **知识库拥有**：材料、切块、概念抽取、`concepts.yaml`、题库生成、检索、联网入口。
- **agent 拥有**：会话、五题配比、作答、评分、mastery、review_due、误解、`agent_sessions`。
- **内容真相**：`materials/` + `concepts.yaml` + `seeds/question_bank.json` 进 git；SQLite 里的 `question_bank` 只是幂等镜像。
- **禁止**：agent 不解析材料；知识库不写 `sessions` / `session_questions` / `agent_sessions`。

建议的 `Retriever` 端口（v1 实现，v0 只留空接口）：

```python
@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    concept_id: str | None
    text: str             # 子块或父块全文
    source_url: str
    source_excerpt: str
    score: float

class Retriever(Protocol):
    def search(self, query: str, *, top_k: int = 5) -> list[RetrievedChunk]: ...
```

题目生成/反馈需要出处时调用它；结果写入 `session_questions.source_url/source_excerpt`，不能只留在内存。

## 6. 当前代码与数据现状

| 项 | 状态 |
|---|---|
| `core/db.py` `question_bank` 表 | 已有：`id, concept_id, kind, question_text, rubric_json, options_json, answer_key, source_url, source_excerpt` |
| `core/store.py.import_question_bank` | 已有：按 id 幂等导入，缺出处直接报错 |
| `core/concepts.py.load_concepts` | 已有：YAML 校验（id 唯一、前置存在、无环、必填字段） |
| `core/store.py.sync_runtime` | 已有：YAML 增删 → `proposed`/`orphaned`/恢复 |
| `materials/` | **不存在**，需要新建 |
| `concepts.yaml` | **不存在**，需要按 v2.0 的 YAML 结构建 |
| `seeds/question_bank.json` | **不存在**，需要建 |
| 检索 / embedding / FTS5 | 未实现（v1） |
| 题目生成 / question_cache | 未实现（v1） |

## 7. 建议的 `knowledge-base-v0.1.md` 结构

沿用 agent 文档的六条框架，保持两份文档可对照：

1. 要解决的具体问题（深挖：材料→概念→题目→检索的失真点）
2. 用户可感知的变化（初始化 30-60 分钟、每天题目有出处、档案能看到材料覆盖缺口）
3. 影响范围（知识表、文件、检索端口、与 agent 的边界）
4. 设计决策记录（`KB-01…`：切块、抽取、去重、检索、联网、DB 布局）
5. 知识库存储规范（文件真相源 + SQLite 镜像 + 版本/哈希）
6. 最小入库/检索管线 + Mermaid（材料 → 切块 → 抽概念 → 确认 → 题库 → 检索）
7. 接口（Retriever / Ingestor / QuestionGenerator）
8. 验收与测试映射（召回 20 条门槛、切块边界、去重、出处必填）
9. 开放问题与风险

## 8. 建议的第一步

1. 先读 v2.0 的 `knowledge` 章节（`docs/designs/learning-companion-digital-human-v2.0.md:301-456`）和技术方案 v1 概要（`technical-plan-v0.1.md:333`）。
2. 选 1-3 份首批材料，确定格式与来源；没有材料就先用手写 `materials/agent-basics.md` 占位。
3. 按六条框架逐条讨论，先写 `KB-01…` 决策，再写正文。
4. 定 DB 布局与 `Retriever` 端口，与 agent 文档对齐。
5. 最后再写代码；v1 检索前不要引入 embedding 依赖。

## 9. 给新工作区的开场指令（可直接复制）

```text
我在 D:\football agent 做数字人学习伴侣。请先读：
1) docs/designs/knowledge-base-handoff.md
2) docs/designs/learning-companion-digital-human-v2.0.md 的知识库章节（301-456 行）
3) docs/designs/agent-infrastructure-v0.1.md（接口边界与存储分工）

然后按交接文档第 7 节的六条框架，和我一条一条讨论，并写 docs/designs/knowledge-base-v0.1.md。
先不要写代码；每条先给我选项和推荐，我确认后再落文档。决策 ID 用 KB-01 起。
```

## 10. 交接检查清单

- [ ] 首批 1-3 份材料已选定，格式与来源明确
- [ ] DB 布局（同库/分库）已定
- [ ] embedding 模型与成本已定（v1 前）
- [ ] `Retriever` 端口与 agent 文档对齐
- [ ] `KB-01…` 决策表已建立
- [ ] `concepts.yaml` 与 `seeds/question_bank.json` 的字段与出处规则已确认
- [ ] 切块/抽取/去重/召回门槛已写成可测断言
- [ ] `knowledge-base-v0.1.md` 已落盘并在 `VERSIONS.md` 登记
