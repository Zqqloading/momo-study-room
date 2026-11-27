# 出题与评分管线设计 v0.1

- 状态：DRAFT v0.1（2026-11-24）
- 父设计：`docs/designs/learning-companion-digital-human-v2.0.md`（FROZEN 2026-11-24）
- 关联：`docs/designs/knowledge-ingestion-v0.1.md`、`docs/designs/knowledge-retrieval-v0.1.md`、`docs/designs/agent-infrastructure-v0.1.md`、`docs/designs/first-slice-v0.1.md`
- 范围：现场出题、题型、溯源、类型感知评分、人工验收。
- 不范围：外部补充链路、agent harness 的工具调用、题库自动回灌/审核、综合场、语音链路。
- 评审状态：§16 的 7 项产品分叉已于 2026-11-24 确认；出题/评分 spike 已跑通（出题 10/10、评分 8/8），结果见 `docs/designs/review-20261124/`；技术决策已按现有代码与冻结约束落定。

## 1. 要解决的具体问题

### 1.1 表面问题

出题还是壳。`core/coach.py` 的 `_pick_new_questions` 从 `question_bank` 取预写题，按 `recall / discriminate / apply` 配比；题目与当天材料、检索结果没有关系。系统能回答“今天学哪个概念”，但回答不了“这道题凭什么是这个材料出的、为什么是这种题型”。

检索是真的：`core/retrieval.py` 已有 FTS5 trigram + 向量 + RRF，`bff/retrieval.py` 已把“概念 → query → 嵌入 → 检索”串起来；但它只服务自由对话，没接出题。评分也是真的：`core/scoring.py` 已有逐题五档 JSON 评分、重试一次、失败 `unscored`；但它用的是通用提示词，没有按题型区分，也没有人工一致率验收。

### 1.2 三个失真点

**① 题源失真。** 预写题库不等于当天材料。材料更新后题目不变，概念出处与题目出处可能对不上；生成的题也没有落库审计，无法回答“这句话从哪来”。

**② 题型失真。** 现有题库以定义、选项、应用题为主，考识别和背诵多，考业务判断少。题目按程序员视角问“hook 是什么”“循环有哪几步”，不是“在什么业务场景下用、放弃什么、带来什么成本”。

**③ 评分失真。** 通用 rubric 不区分题型；背定义可能拿高分，真正理解但表达朴素的回答可能被压低。没有“人工判断 vs 模型判断”的一致率门槛，分数只能当流程验证。

### 1.3 为什么是现在

- 知识入库与检索已经落地：`materials/` 有真实材料，`material_chunks`、`concept_sources`、`chunk_fts`、`chunk_embeddings` 可用。
- 会话、逐题评分、结算、mastery、复习调度已经跑通，291 个测试全绿。
- 用户要把“查资料考用户”做实；这是产品核心闭环里唯一还空着的一段。

### 1.4 明确不解决

- 不做外部补充：不搜网页、不抓网页、不把 `hot_items` 作为出题来源。
- 不改 agent harness / 工具调用；出题与评分是程序化编排，不是 agent 自主选工具。
- 不做题库自动回灌、跨模型预检、周审计（KB-15/KB-16 留后续）。
- 不做综合场、跨概念讲解、语音链路改动。
- 不引入 reranker、ANN、独立向量库。
- 不做自适应出题（根据上一题回答改下一题）；5 题在会话开始时一次生成。

## 2. 用户可感知的变化

| 场景 | 现在 | 实现后 |
|---|---|---|
| 开始学习 | 直接从题库取 5 题 | 先检索当天概念的材料，再现场生成 5 题；开始前显示“正在根据材料出题” |
| 题目本身 | 定义题、选择题、应用题混排 | 5 题覆盖概念、业务运用、取舍权衡、成本风险、综合判断；题卡显示题型 |
| 答题后 | 分数 + 一句为什么 | 分数 + 为什么 + 出处摘录 + 材料链接 |
| 验收卡 | 逐题分数 | 逐题分数、题型、出处；可回看“这题考的是哪段材料” |
| 材料不足 | 不感知 | 显示“本次有题来自旧题库”，不冒充生成题 |
| 验收 | 没有固定口径 | 10 题盲评题型/理解；10 个标准答案验评分一致率；报告落盘 |

## 3. 影响范围

### 3.1 代码边界

| 模块 | 归属 | 说明 |
|---|---|---|
| `core/question_generation.py` | 本文档（新增） | 题型常量、`SessionPlan`/`GeneratedQuestion` 数据类、出题提示词、JSON 解析、`validate_question_set`、修复提示词 |
| `bff/question_generation.py` | 本文档（新增） | 组装 `retrieve_concept` + `Embedder` + `LLMProvider`，实现 `QuestionGenerator` 端口；不 import 搜索 |
| `core/coach.py` | 修改 | `start` 调生成器；生成失败回退旧题库；`add_question` 写新字段；评分传题型/摘录/参考答案 |
| `core/scoring.py` | 修改 | `build_score_messages` 加题型、材料摘录、参考答案；提示词 v2；反背诵规则 |
| `core/retrieval.py` | 小改 | `RetrievedChunk` 增加 `chunk_id`/`parent_chunk_id`，供溯源映射；不改检索算法 |
| `core/store.py` | 小改 | `add_question` 新字段；查询上一场题干作为 negative examples；读取新字段 |
| `core/ports.py` | 小改 | `QuestionGenerator` 端口；或放 `core/question_generation.py` |
| `bff/main.py` | 修改 | 注入生成器；配置生成模型与提示词版本 |
| `web/` | 小改 | 题型 chip；score/result 显示出处；不改语音链路 |
| `tests/` | 新增/修改 | 出题契约、校验、回退、评分类型规则、验收 harness、无外部来源守卫 |

### 3.2 数据边界

- **只读**：`materials`、`material_chunks`、`concept_sources`、`concepts`（内容以 `concepts.yaml` 为准）、`concepts.yaml`。
- **可写**：`session_questions`（逐题 commit）、`agent_sessions`（生命周期）、`sessions`（结算）。
- **不写**：`materials`/`material_chunks`/`concept_sources`/`question_bank`/`seeds`/`hot_items`。生成题只落 `session_questions`，不进题库真相源。
- **不读**：`hot_items`、自由对话的搜索来源、任何外部网页内容。

### 3.3 对已冻结文档的影响

- v2.0 的“五题配比”（2 recall + 2 discriminate + 1 apply）与“题目来源”（题库全部预写）被本设计覆盖；按 `FREEZE.md` 变更规则登记为待变更，不直接改 v2.0 正文。
- v2.0 的评分契约（逐题即时、五档、重试一次、unscored）保持不变；本设计只细化提示词与题型 rubric。
- v2.0 的“每题必须带 source_url + source_excerpt”保持不变；本设计增加 `source_chunk_id` 与逐字校验。
- v2.0 的“联网只做材料入口或超纲兜底，不进每轮热路径”保持不变；本设计进一步收紧为“出题完全不用外部补充”。

### 3.4 测试与验收边界

本设计必须落地：题型定义与配比、现场生成、逐字溯源、生成失败回退、类型感知评分、10 题盲评、10 答案一致率、无外部来源守卫。

不测：材料解析/切块/抽取/确认（入库文档）、检索召回门槛（检索文档）、会话/结算（agent 文档）、VAD/TTS（语音链路）。

## 4. 设计决策记录

| ID | 日期 | 决策 | 背景 | 备选 | 影响 | 状态 |
|---|---|---|---|---|---|---|
| AP-01 | 2026-11-24 | 5 题在 `Coach.start` 时一次生成、整场校验，再逐题下发；生成模型用 DeepSeek；不是每题生成一次 | 需要保证整场题型配比和题目质量；MiMo 输出上限不够（spike 实测） | 每题生成 / 预生成缓存 / MiMo 分槽位 | 生成延迟集中到开场；后续题不再等模型 | accepted（spike 验证） |
| AP-02 | 2026-11-24 | 五型各 1：概念理解、业务运用、取舍权衡、成本风险、综合判断 | 用户要求“每道题题型都不一样”，但只列了四型；5 题必须有第 5 型 | 四型 + 重复一型 / 加误区诊断 | 题型不再重复；综合判断题承担多因素决策 | accepted（2026-11-24 用户确认） |
| AP-03 | 2026-11-24 | 每场 5 题 = 最多 2 道复习 + 3 道新概念；复习只取 1 个最逾期概念 | 保留 20 分钟节奏与前置解锁进度；避免弱概念连续占天 | 一场只考一个概念 / 旧格式复习混排 | 主概念 3 题（必含概念题），复习概念 2 题；5 型仍各 1 | accepted（2026-11-24 用户确认） |
| AP-04 | 2026-11-24 | 出题只读本地已确认知识库；外部补充链路本轮不做 | 出处可审计；外部内容未确认，不能进计分题 | 允许搜索补事实 / 热项出题 | 材料不足时回退或补材料，不编外部事实 | accepted |
| AP-05 | 2026-11-24 | 溯源 = 逐字摘录 + `source_chunk_id` + `source_url` + `generation_meta_json`；作答前不展示出处，评分后展示 | 防止把理解题变成开卷抄写；同时保证可审计 | 答前展示 / 只在数据库 | 题目可回溯到块；用户答后能看依据 | accepted |
| AP-06 | 2026-11-24 | 生成失败/材料不足：1 次生成 + 1 次修复，仍失败回退旧题库并标 `fallback`，不计入验收 | 不阻塞会话；不冒充生成题 | 阻塞 / 少出题 | 会话可继续；回退可见、可审计 | accepted（2026-11-24 用户确认） |
| AP-07 | 2026-11-24 | 评分按题型加规则；只背定义/复述材料最高 60；类型缺关键要素按题型封顶 | 通用 rubric 会奖励背诵；业务题需要业务判断 | 统一提示词 / 只改 rubric 文本 | 评分更贴合题型；需要重新校准 | accepted |
| AP-08 | 2026-11-24 | 评分验收 = 8 条已答（3 全对、3 对一半、2 跑题）+ 2 条跳题；一致 = 同一档位；通过 = 已答 ≥6/8 同档 + 跳题行为 2/2 | 跳题不进判分模型，不能用来凑一致率；6/8 = 75% 与设计门槛一致 | 10 条都计 / 精确分差 ≤15 | 验收口径可复现；跳题单独验状态 | accepted（2026-11-24 用户确认） |
| AP-09 | 2026-11-24 | 验收不通过、改了 prompt/rubric/标准后，用全新 10 条 holdout 做最终验收 | 同一组 10 条调完再跑会过拟合；评分校准第一轮已踩过 | 同一组重跑 / 一次 20 条 | 多一组样本成本；最终成绩可信 | accepted（2026-11-24 用户确认） |
| AP-10 | 2026-11-24 | Schema v6 只做加法：`question_type`、`source_chunk_id`、`generation_meta_json` | 旧库要能原地升级；不改 `kind` CHECK | 重建表 / 改 CHECK | 旧行新列为 NULL；生成题用新列 | accepted |
| AP-11 | 2026-11-24 | 生成题全部开放题，不出选择题 | 选择题考识别，不适合“理解优先”；语音作答也以开放题为主 | 保留辨析选择题 | 旧题库的 `discriminate` 只用于回退 | accepted |
| AP-12 | 2026-11-24 | 槽位、题型、概念归属由程序固定；模型只写题干/参考答案/rubric | 模型自由配比会漂移，验收不可复现 | 模型决定题型 / 模型决定概念 | 题型准确率可测；模型专注于内容质量 | accepted |
| AP-13 | 2026-11-24 | 出题验收：题型 ≥8/10、理解 ≥8/10、业务视角 10/10、溯源 10/10 | 用户只给了前两项门槛；业务视角是“严禁”要求，溯源是“每题”要求 | 视角 8/10 / 溯源 8/10 | 任何一道程序员视角题直接不通过 | accepted（由“严禁/每题”直接推出） |
| AP-14 | 2026-11-24 | 生成用 MiMo，评分用 DeepSeek；不交叉 | 生成与评分分离，减少自评偏好；与现有 provider 一致 | 同一模型 / 评分用 MiMo | 两套调用与 key；失败域分开 | superseded by AP-19（2026-11-24 spike：MiMo 输出上限不够） |
| AP-15 | 2026-11-24 | 生成题只落 `session_questions`，不写 `question_bank`/seeds | 题库回灌/审核不在本轮；避免未审核内容进真相源 | 生成即入库 | 题目可审计但不复用；后续再做 promotion | accepted |
| AP-16 | 2026-11-24 | 实现前先补 1–2 份业务型材料（PRD/业务案例），再开始出题管线与验收 | 现有材料的业务/成本/取舍素材薄；先跑很可能因“材料没依据”挂掉 | 先跑现有材料再补 / 允许通用常识 | 开工前多一步材料准备；验收样本有业务依据 | accepted（2026-11-24 用户确认；材料已入库） |
| AP-17 | 2026-11-24 | 模型只写题干、参考答案、`must_have`、`red_flags`；五档 rubric 由程序按 0/40/70/90/100 生成 | 模型一次写 5 题 + 每题五档会膨胀并截断；五档由程序生成更一致 | 模型写五档 / 程序生成 | 输出更短；评分提示词用 `must_have`/`red_flags`；持久化仍带五档 | accepted（spike 验证） |
| AP-18 | 2026-11-24 | 出题上下文：概念主出处放 `[1]`，检索结果按父块去重后置；`source_excerpt` 优先完整句、直接支撑题干 | spike 发现模型会选无关/过短句；主出处优先明显改善选题与溯源 | 只按检索顺序 / 只给主出处 | 溯源语义支撑更好；仍靠逐字校验 + 人工抽查 | accepted（spike 验证） |
| AP-19 | 2026-11-24 | 出题生成模型用 DeepSeek，不用 MiMo；评分也用 DeepSeek，自评偏好靠 10 条人工一致率 gate 兜 | MiMo 单次输出约 600-700 汉字，单题都截断；DeepSeek 一次 5 题完整可解析 | MiMo 分槽位 / MiMo 两次调用 / DeepSeek | 与评分同模型；需记录自评风险；不再依赖 MiMo 生成 | accepted（spike 验证） |

## 5. 题型系统

### 5.1 五型定义

| code | 中文 | 合格题特征 | 不合格题特征 | 考什么 |
|---|---|---|---|---|
| `concept` | 概念理解 | 问“为什么需要/解决什么业务问题/不用会怎样/和相邻概念的区别”；要求说因果或业务后果 | “X 是什么”“X 的定义是”；可以逐字抄材料回答 | 因果理解 |
| `business` | 业务运用 | 给一个具体业务场景，问怎么用、先做什么、产出什么、怎么判断有效 | 只问概念解释；场景与概念无关；答案可以是通用套话 | 迁移应用 |
| `tradeoff` | 取舍权衡 | 给 A/B 或两种做法，问选哪个、放弃什么、什么条件下反转 | 只问“有什么优缺点”；没有选择；没有代价 | 判断力 |
| `cost_risk` | 成本风险 | 问成本/风险/谁承担/怎么兜底；至少两项 | 只问“有什么风险”且答案可泛泛而谈；没有承担者或缓解 | 风险意识 |
| `synthesis` | 综合判断 | 给完整场景和约束，要求做决策、说依据、说边界/失败信号 | 只列优缺点；没有决策；没有边界 | 综合 |

### 5.2 配比与槽位

槽位由 `SessionPlan` 固定，模型不决定题型：

| 场次构成 | 主概念槽位 | 复习概念槽位 |
|---|---|---|
| 无到期复习 | 5 题：`concept`、`business`、`tradeoff`、`cost_risk`、`synthesis` | — |
| 复习 + 新概念 | 3 题：`concept`、`business`、`tradeoff` | 2 题：`cost_risk`、`synthesis` |
| 只有复习 | — | 5 题：五型各 1 |
| 复习概念 = 新概念 | 5 题全考它；`question_role` 拆 2 review + 3 new | 同左 |

规则：

- 复习只取 `due_reviews(today)` 的第一个（最逾期）；不再从两个概念各取 1 题。
- 主概念必须拿到 `concept` 题；复习概念承担风险与综合题。
- 同一场 5 题题型互不重复；`question_role` 只影响 mastery/review_due，不影响题型。
- 无新概念且无到期复习 → `NoSessionAvailable`（沿用现有行为）。

### 5.3 业务视角规则

- 题干必须落到至少一个业务维度：客户、团队、预算、周期、合规、交付、收入、成本、售后。
- 禁止代码实现词：函数、参数、数据库表、写代码、SQL、部署脚本、API 参数、字段、后端实现。
- 技术概念必须翻译成业务后果：
  - Agent Loop → 客服工单自动处理什么时候停、停不下来多花什么成本。
  - 示例概念 A → 把团队现有工具打包给 AI 用，业务上解决什么问题、谁维护。
  - 示例概念 B → 门槛降低后谁受益、谁承担法律/交付风险。
- 题干不能是“以下哪个”或 Yes/No 判断；生成题全部开放题。
- 允许假设业务场景，但不得伪造数据/案例；场景只用于承载判断，不引入材料外的事实。

### 5.4 反背诵规则

- 概念题禁止“X 是什么/定义”；必须问“为什么需要/解决什么问题/不用会怎样/区别”。
- 所有题的 rubric 必须有 `must_have` 与 `red_flags`；只复述材料原句最高 60。
- 业务/取舍/成本/综合题必须要求具体动作、选择、代价、风险或边界；不能只要求复述概念。
- 评分提示词里明确：如果回答只是材料原句的近义复述，没有业务后果或场景判断，最高 60。

## 6. 出题管线

### 6.1 SessionPlan

```python
QuestionType = Literal["concept", "business", "tradeoff", "cost_risk", "synthesis"]

@dataclass(frozen=True, slots=True)
class Slot:
    slot: int                      # 1..5
    concept_id: str
    role: Literal["new", "review"]
    question_type: QuestionType

@dataclass(frozen=True, slots=True)
class SessionPlan:
    kind: Literal["daily", "review"]
    main_concept: Concept
    review_concept: Concept | None
    slots: tuple[Slot, ...]
```

`SessionPlan` 在 `core/coach.py` 用确定性规则构造；不调用模型。构造失败（无概念/无题）沿用现有 `NoSessionAvailable`。

### 6.2 ContextBuilder

每个概念构造一份上下文：

```python
@dataclass(frozen=True, slots=True)
class GenerationContext:
    concept_id: str
    chunks: tuple[ContextChunk, ...]

@dataclass(frozen=True, slots=True)
class ContextChunk:
    ref: int                       # 1..N，给模型引用
    chunk_id: str                  # 命中子块 id
    parent_chunk_id: str | None
    heading_path: str | None
    text: str                      # 父块全文（无父块则子块）
    source_url: str
    origin: Literal["primary", "retrieval"]
```

- 先把概念主出处（`concept_sources` 主行）对应父块放 `[1]`，`origin="primary"`。
- 再调 `bff.retrieval.retrieve_concept(store, embedder, concept, top_k=5)`，按父块去重后追加 `[2..]`，`origin="retrieval"`。
- 检索为空 → 只用主出处；主出处也没有 → 生成失败，走回退。
- 每个父块截断到约 1200 字；保留 `chunk_id`/`parent_chunk_id` 供溯源。
- `RetrievedChunk` 增加 `chunk_id`/`parent_chunk_id` 字段；检索算法不变。
- 上下文里每条带 `heading_path` 与来源标签，便于模型选直接支撑题干的原文。

### 6.3 出题提示词

系统提示词（概要）：

```text
你是 B 端 AI 产品的产品教练，不是程序员。根据给定材料和概念，写 5 道中文开放题。
每道题只考业务/产品判断，不考代码实现、不考背诵定义。
槽位与题型已给定，不得改变；每题必须引用给定材料中的一段原文。
```

用户提示词包含：

1. 概念：`id`、`name`、`aliases`、`plain_def`、`source.excerpt`。
2. 每个概念的检索上下文，编号 `[1]...[N]`，带 `heading_path` 与正文。
3. 槽位表：slot、concept_id、role、question_type。
4. 题型定义（§5.1）与业务视角规则（§5.3）。
5. 反背诵规则（§5.4）。
6. 上一场同概念题干（negative examples），要求避免重复；没有则省略。
7. 输出 JSON schema（§6.3.1）。

#### 6.3.1 输出契约

```json
{
  "questions": [
    {
      "slot": 1,
      "concept_id": "mvp",
      "question_type": "concept",
      "question_text": "MVP 为什么能降低验证成本？如果直接做完整版，多花的那部分钱主要花在哪？",
      "reference_answer": "MVP 把验证范围压到核心流程，先看真实用户是否愿意用；完整版会提前投入未验证的功能、设计和交付成本。",
      "must_have": ["说清 MVP 缩小验证范围", "说清完整版提前投入的成本"],
      "red_flags": ["只背 MVP 定义", "把 MVP 说成功能少但完整"],
      "source_ref": 1,
      "source_excerpt": "MVP（最小可行性产品）..."
    }
  ]
}
```

- 模型不写五档；程序按 0/40/70/90/100 生成 `rubric.levels`，档位描述由 `must_have`/`red_flags` 和题型标准生成。
- `source_ref` 是上下文编号，不是 chunk id；BFF 映射到 `source_chunk_id` 与 `source_url`。
- `source_excerpt` 必须是对应上下文里的逐字子串；不得改写、概括、拼接；优先完整句，避免只选标题/单词。
- `reference_answer` 60–120 字；持久化时写入 `rubric_json.reference_answer`，不占用 `answer_key`。
- `must_have` 2–5 条；`red_flags` 1–3 条；`question_text` 15–200 字；可以包含假设场景，但不能伪造数据/案例。

### 6.4 校验

`core.question_generation.validate_question_set(drafts, contexts, plan)` 是纯函数，返回 `ValidationResult`（`ok` / `errors` / `warnings`）。

硬失败：

1. 不是恰好 5 题；slot 不是 1..5 或重复。
2. `concept_id`/`question_type` 与 plan 槽位不一致。
3. `source_ref` 越界；`source_excerpt` 不是该上下文文本的逐字子串。
4. `question_text` 为空、超过 200 字、或含代码实现禁词。
5. `reference_answer` 为空；`must_have`/`red_flags` 为空；程序生成的五档 levels 不是 0/40/70/90/100。
6. 同一场题干规范化后重复。

软警告（进修复提示词，不硬杀）：

- 概念题像“什么是 X”式定义题。
- 业务/取舍/成本/综合题缺少场景或判断标记。
- 题干与上一场同概念题目高度相似。
- `must_have` 与题型不匹配。
- `source_excerpt` 过短、像标题/单词，或语义上与题干关系弱；进修复提示词，要求换完整句。

### 6.5 修复与回退

```text
生成 1 次
  → 解析失败 / 硬失败：修复 1 次（只给失败槽位 + 错误原因）
  → 仍失败：回退旧题库
  → 旧题库也不足：NoSessionAvailable
```

- 修复调用只要求模型重写失败槽位，保留通过槽位，减少成本与漂移。
- 回退：`Coach` 从 `question_bank` 按现有轮换逻辑取题；`question_type=NULL`，`generation_meta_json={"origin":"fallback","reason":"..."}`；UI 显示“旧题回退”。
- 回退题不计入出题验收样本；会话仍可评分、结算。
- Provider 超时/5xx 与解析失败同等处理；生成调用重试一次（传输层），内容修复一次（语义层），不无限重试。

### 6.6 持久化

`Store.add_question` 增加：

```python
question_type: str | None = None,
source_chunk_id: str | None = None,
generation_meta_json: Any = None,
```

写入 `session_questions`：

- `question_type`：五型 code；回退题为 NULL。
- `source_chunk_id`：命中的子块 id；回退题为 NULL。
- `generation_meta_json`：`{"origin":"generated","model":"deepseek-chat","prompt_version":"qgen-v1","retrieved_chunk_ids":[...],"repair_count":0,"validation":"passed"}`；回退题为 `{"origin":"fallback","reason":"..."}`。
- `kind`：`concept` → `recall`；其余四型 → `apply`；回退题沿用题库的 `kind`。生成题从不使用 `discriminate`，因此不会走选择题本地判分。
- `rubric_json`：程序生成的五档 `levels` + 模型的 `must_have`/`red_flags` + `reference_answer`。
- `source_url`/`source_excerpt`：来自上下文映射；仍满足非空约束。

## 7. 溯源

### 7.1 标准

- 每题至少一条 `source_excerpt`，逐字来自检索上下文；验证器拒绝改写/概括。
- 逐字通过不等于语义支撑：摘录必须与题干直接相关，优先完整句；人工验收按“语义支撑”判，不只看逐字。
- 存 `source_chunk_id`、`source_url`、`source_excerpt`、`generation_meta_json`。
- 题干可以构造假设业务场景，但概念前提和参考答案不得引入材料外的事实；场景必须是假设语气，不能伪造数据/案例。
- 检索为空时用 `concept_sources` 主出处兜底，`origin="primary"`；仍为空则生成失败，不硬编。
- 回退题沿用题库的 `source_url`/`source_excerpt`，但标记 `origin="fallback"`，不冒充生成题。

### 7.2 展示

- 作答前：题卡只显示题型（概念/业务/取舍/成本/综合），不显示出处。
- 评分后：`score` 事件带 `question_type`、`source_url`、`source_excerpt`，前端显示“出处”折叠块。
- 验收卡：逐题显示题型、分数、出处摘录；可回看材料链接。
- 回退题：显示“旧题回退”标签；不显示“根据材料生成”。

### 7.3 审计

- `session_questions` 是唯一审计真相：题目、回答、分数、反馈、题型、出处、生成元数据都在一行。
- `generation_meta_json` 记录模型、提示词版本、检索 chunk id、修复次数、校验结果；不记录完整提示词（避免膨胀）。
- 出题验收报告从 `session_questions` 导出，不另建题目表。

### 7.4 外部补充链路（本轮不做，记录待补）

**规则**：计分题出题只读本地已确认知识库；不调用 `SearchProvider`/Tavily/网页抓取；不读 `hot_items`；不使用自由对话的搜索来源。自由对话的联网搜索结果只能作为对话来源，不得写入 `materials`、`question_bank`、`session_questions`、`hot_items`。

**为什么**：外部内容未经过摄取、切块、抽概念、确认，直接进计分题会破坏出处与质量门槛；用户要求每题可溯源。

**后续实现时的链路**：

```text
外部搜索/抓取
  → 候选内容落成 materials/*.md（front matter 带 source_url）
  → core.ingest（解析、切块）
  → core.extract（抽概念）
  → core.confirm（人工确认）
  → core.reindex（建 FTS/向量索引）
  → Retriever 可检索
  → 才允许作为出题上下文
```

在完成上述链路前，`hot_items` 与网页搜索结果都不是计分题来源。详见 `docs/adr/0002-no-external-supplement-for-scoring-questions.md`。

**守卫**：静态检查 + 行为测试断言出题路径不 import 搜索适配器、不查询 `hot_items`；生成上下文只来自 `material_chunks`/`concept_sources`。

## 8. 评分

### 8.1 契约（不变）

- 逐题即时评分；每题 0–100；五档 rubric；一句 `why`；最多 1 条会话级误解。
- 解析失败/Provider 失败重试一次；仍失败该题 `score=NULL`、`feedback="本题未评分"`，会话继续。
- 只有一题都没评上才整场 `unscored`；`session_score` 只对已评分题取均值。
- mastery/review_due 仍在结算时更新；辨析题本地判分只用于回退题。
- `question_role=new` 指新题，不指新概念；复讲场也用 `new`。

### 8.2 类型感知提示词 `score-v2-business`

输入：

```text
题目类型：{question_type}
题目：{question_text}
材料出处：{source_excerpt}
评分标准：{rubric_json}
参考答案：{reference_answer}
用户回答：{answer}
```

系统提示词增加：

- 你是 B 端 AI 产品的评分员；按题型判断业务/产品理解，不按关键词匹配。
- 只背定义、只复述材料原句、没有业务后果或场景判断 → 最高 60。
- 业务运用：没有具体动作/场景映射 → 最高 60。
- 取舍权衡：没有明确选择/代价/反转条件 → 最高 69。
- 成本风险：少于 2 项成本或风险，或无兜底 → 最高 69。
- 综合判断：没有决策/依据/边界 → 最高 69。
- 参考答案只作对照，不要求逐字；用户用自己的例子说清也算对。
- `session_misconception` 只能是 `null` 或 `{"text":"...","concept_key":"..."}` 对象；返回字符串视为解析失败，重试一次。
- 输出 JSON 契约不变（`questions[].id/score/why/reference_answer/misconception_hit/certain`、`session_misconception`）。

### 8.3 分档

| 分数 | 含义 |
|---|---|
| 0–30 | 空白、不知道、完全跑题、概念相反 |
| 40–65 | 提到正确名词/部分要点，但关系说错或不完整 |
| 70–89 | 方向对、要点基本齐全，但缺自己的例子、边界或具体动作 |
| 90–100 | 正确、能结合业务场景/例子，并说出边界、代价或反例 |

- 参考答案显示：优先用生成题的 `rubric_json.reference_answer`；没有才用评分模型返回的 `reference_answer`；都没有才用 rubric 的 `criteria`/`explanation`。
- 评分模型返回的 `reference_answer` 只作补充，不覆盖生成题的参考答案。

### 8.4 跳题与不知道

- 跳题（点“下一题”/显式跳过）：不调用 Scorer，`score=NULL`，`answer_text` 留空；会话最终 `partial`（除非全部跳题→`unscored`）。
- 不知道：`score=0` + 60 字短定义（`plain_def` + `source_excerpt`），不调用 LLM；沿用现有行为。
- 评分验收里“跳题”只验状态，不验分数；不计入一致率。

### 8.5 失败语义

- Scorer 单题失败重试一次；仍失败 `score=NULL`、`feedback="本题未评分"`，下一题继续。
- Scorer 全部失败：整场 `unscored`，答案保留。
- 生成失败：回退旧题库；旧题库也没有 → `NoSessionAvailable`，不静默开空会话。
- 评分提示词变更：必须重新跑评分验收；旧分数不回溯重评。

## 9. 验收

### 9.1 出题验收（10 题）

**样本**：真实材料、真实 DeepSeek，2 场 × 5 题；全部 `generation_status=generated`，不抽回退题；覆盖 5 种题型（每型 2 道）。

**盲评**：评审只看到题干 + 对应材料摘录 + 题型定义；不看到模型声称的题型，也不看到 rubric。逐题标：

| 字段 | 取值 | 说明 |
|---|---|---|
| 题型 | 对/错 | 是否符合该型定义 |
| 理解 | 理解/背诵 | 是否必须真正理解才能答；能逐字抄材料算背诵 |
| 视角 | 业务/程序 | 是否业务/产品视角；出现代码实现即程序 |
| 溯源 | 可/不可 | 摘录是否逐字、是否支撑题干 |

**通过线**：

- 题型 ≥8/10。
- 理解 ≥8/10。
- 业务视角 10/10（硬门槛；任何一道程序员视角题直接不通过）。
- 溯源 10/10。

**失败处理**：先讨论，改提示词/题型定义/材料；用全新的 10 题（holdout）复验，不用调过的 10 题当最终依据。

### 9.2 评分验收（10 个标准答案）

**样本**：从出题验收通过的 10 题里取题，写 10 个标准答案：

- 3 条全对（90–100 档）
- 3 条对一半（40–69 档）
- 2 条跑题（0–39 档）
- 2 条跳题（无答案，期望 `score=NULL`）
- 覆盖 5 种题型；每条答案先写人工档位与一句理由，再跑模型。

**一致定义**：模型分数映射到同一档位（0–39 / 40–69 / 70–89 / 90–100）即算一致；跳题单独验行为。

**通过线**：

- 8 条已答题中 ≥6 条同档（75%，与设计文件 75% 门槛对齐）。
- 2 条跳题：不调用 Scorer、`score=NULL`、会话 `partial`，2/2 正确。

**不一致处理**：

1. 逐条看模型 `why` 与人工理由。
2. 先讨论是标准答案、rubric、题目还是提示词的问题，不直接改人工标签。
3. 记录决定；改标准后，用全新的 10 条 holdout 重跑，不在原 10 条上刷分。
4. 报告保留“改了什么、为什么改、谁确认”。

### 9.3 Holdout

- 第一组 10 条只做诊断；如果改了提示词/rubric/标准，最终验收必须用全新 10 条。
- 如果第一组直接通过，不需要额外 holdout。
- Holdout 的题目、标准答案、人工档位同样落盘，避免事后补写。

### 9.4 验收工具与报告

- `python -m core.eval_questions --prepare`：生成 2 场，导出盲评表（题干 + 摘录 + 题型定义，隐藏声称题型）。
- `python -m core.eval_questions --score`：读人工标签，计算题型/理解/视角/溯源通过率。
- `python -m core.eval_scoring --prepare`：导出 10 题 + 标准答案模板（人工写档位）。
- `python -m core.eval_scoring --run --mode real`：跑 DeepSeek，输出对照表与一致率。
- 报告：`docs/designs/review-<YYYYMMDD>/question-acceptance.md`、`scoring-acceptance.md`；原始 JSON/CSV 同目录。
- 验收工具不进入日常会话路径；不自动改提示词、不自动改人工标签。

### 9.5 回归与守卫

- 现有 291 个测试必须全绿；受配比影响的 `test_ratios.py` 改为五型/2+3 配比测试。
- 新增：生成契约、校验、修复、回退、评分类型规则、跳题状态、无外部来源守卫。
- 无外部来源守卫：静态 import 检查 + 行为测试（搜索 provider 被调用即失败；生成仍能跑）。
- 真实 provider 验收不放进 `pytest` 默认路径；用独立 gate，避免 CI/本地无 key 时失败。

## 10. 数据模型与迁移

### 10.1 Schema v6

`SCHEMA_VERSION` 5 → 6；只做加法：

```sql
ALTER TABLE session_questions ADD COLUMN question_type TEXT;
ALTER TABLE session_questions ADD COLUMN source_chunk_id TEXT;
ALTER TABLE session_questions ADD COLUMN generation_meta_json TEXT;
```

- 旧行新列为 NULL；读取方把 NULL 当“旧题库/未标记”。
- 不在 `ALTER TABLE` 上加 CHECK；五型合法性由 `core.question_generation` 校验。
- 新建库在 `SCHEMA_SQL` 里直接带三列；旧库由 `init_schema` 按列名补齐。
- `question_bank` 不改；回退题沿用旧字段。
- 迁移测试：v5 库升级到 v6 后，旧会话可读、旧题可评分、新列可写。

### 10.2 Store 与读取

- `Store.add_question` 新增三个 keyword 参数（默认 None），INSERT 写入。
- `Store.question` / `session_questions` 是 `SELECT *`，新列自动返回；无需改查询。
- 新增 `Store.previous_question_texts(concept_id, limit=10)`：取该概念最近题干，供生成器避免重复；只读 `session_questions`。
- `Store.session_questions` 读取时把 `generation_meta_json` 解析为 dict；解析失败返回 `{}`，不抛。

### 10.3 RetrievedChunk

```python
@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    concept_id: str | None
    text: str
    source_excerpt: str
    source_url: str
    score: float
    chunk_id: str = ""
    parent_chunk_id: str | None = None
    vector_score: float | None = None
    fts_hit: bool = False
```

- 新增字段有默认值，现有构造调用不破。
- `core/retrieval.py` 在组装结果时填入 `chunk_id` 与 `parent_chunk_id`。
- 不改 FTS/向量/RRF 逻辑。

## 11. 接口

### 11.1 QuestionGenerator（BFF 实现）

```python
@dataclass(frozen=True, slots=True)
class GeneratedQuestion:
    slot: int
    concept_id: str
    question_type: str
    question_text: str
    reference_answer: str
    rubric: dict[str, Any]
    source_chunk_id: str
    source_url: str
    source_excerpt: str

@dataclass(frozen=True, slots=True)
class GeneratedSet:
    questions: tuple[GeneratedQuestion, ...]
    meta: dict[str, Any]  # model / prompt_version / retrieved_chunk_ids / repair_count

class GenerationError(RuntimeError):
    """生成、解析、校验均失败；调用方回退旧题库。"""

class QuestionGenerator(Protocol):
    async def generate(self, plan: SessionPlan) -> GeneratedSet: ...
```

- `bff/question_generation.py` 实现：构造上下文 → 拼提示词 → 调 LLM → 解析 → `core.validate_question_set` → 修复一次 → 返回 `GeneratedSet` 或抛 `GenerationError`。
- `core/` 只依赖端口，不 import httpx；BFF 负责外部调用。
- `Coach.start`：

```python
try:
    generated = await self._question_generator.generate(plan)
except GenerationError:
    generated = self._fallback_from_bank(plan)
```

- 生成器不读 `hot_items`、不调搜索、不写库；写库仍在 Coach/Store。

### 11.2 Coach 变更

- `start`：构造 `SessionPlan`；调生成器；把 `GeneratedQuestion` 转 `SessionQuestion` 并落库；回退时走旧题库轮换。
- `SessionQuestion` 增加 `question_type: str | None`；question 事件带题型。
- `ScoredAnswer` 增加 `question_type`、`source_url`、`source_excerpt`；score 事件与验收卡显示出处。
- `_score_open`：把题型、摘录、参考答案传给 `build_score_messages`；参考答案优先用 `rubric_json.reference_answer`。
- `_mastery_updates` / `_due_updates` 不变；复习/新题的角色仍由 `question_role` 决定。

## 12. 失败与降级

| 故障 | 处理 |
|---|---|
| 检索为空 | 用 `concept_sources` 主出处兜底；仍空 → 生成失败 → 旧题库回退 |
| 生成 Provider 超时/5xx | 传输层重试一次；仍失败 → 旧题库回退 |
| 生成 JSON 解析失败 | 修复调用一次；仍失败 → 旧题库回退 |
| 部分槽位校验失败 | 只修复失败槽位一次；仍失败 → 整场回退（不混用生成题与旧题？见下） |
| 旧题库不足 5 题 | `NoSessionAvailable`，提示补材料/题库；不静默开空会话 |
| 评分 Provider 失败 | 重试一次；仍失败该题未评分，会话继续 |
| 全部评分失败 | 整场 `unscored`，答案保留 |
| 结算 DB 失败 | 事务回滚，会话保持未结算，可重试 |
| 回退题被用于会话 | UI 标“旧题回退”；不计入验收；评分照常 |

**部分槽位失败是否混用**：默认整场回退，不把 3 道生成题 + 2 道旧题混在一场。混用会让题型验收失真，也难解释“为什么这题有出处、那题没有”。如果整场回退不可用（旧题库不足），才允许少题并记 `partial`；这是最后的降级。

## 13. 测试与验收映射

| ID | 断言 | 阶段 | 文件 |
|---|---|---|---|
| AP-T01 | SessionPlan：无复习 5 题五型；2+3 时主概念含 concept、复习概念拿 cost_risk+synthesis；同概念拆角色 | v1 | `tests/test_question_plan.py` |
| AP-T02 | 生成契约：5 槽位、题型匹配、紧凑字段（题干/参考答案/must_have/red_flags/source_ref/source_excerpt）；程序生成五档 | v1 | `tests/test_question_generation.py` |
| AP-T03 | 溯源：source_ref 有效；source_excerpt 逐字命中；改写/概括被拒 | v1 | `tests/test_question_generation.py` |
| AP-T04 | 业务视角：代码实现词被拒；技术概念翻译规则在提示词中 | v1 | `tests/test_question_generation.py` |
| AP-T05 | 修复：坏槽位只重写一次；仍坏 → GenerationError | v1 | `tests/test_question_generation.py` |
| AP-T06 | 回退：生成失败 → 旧题库 5 题；标 fallback；不计入 generated 样本 | v1 | `tests/test_coach_flow.py` |
| AP-T07 | 持久化：question_type/source_chunk_id/generation_meta_json 落库；旧行 NULL 可读 | v1 | `tests/test_store.py` |
| AP-T08 | 评分：题型、摘录、must_have/red_flags、参考答案进入提示词；反背诵封顶；`session_misconception` 字符串触发重试 | v1 | `tests/test_scoring.py` |
| AP-T09 | 跳题：不调用 Scorer；score NULL；会话 partial | v1 | `tests/test_coach_flow.py` |
| AP-T10 | 不知道：0 分 + 短定义；不调用 LLM | v1 | `tests/test_coach_flow.py` |
| AP-T11 | 无外部来源：出题模块不 import 搜索；搜索 provider 被调用即失败 | v1 | `tests/test_question_generation.py` |
| AP-T12 | 迁移：v5 → v6；旧库升级后可读可写 | v1 | `tests/test_db.py` |
| AP-T13 | 端到端：start → 5 题 → 逐题评分 → 结算；DB 可回放 | v1 | `tests/test_ws.py` |
| AP-T14 | 出题验收 harness：10 题盲评表、隐藏声称题型、计算通过率 | 验收 | `tests/test_question_acceptance.py` |
| AP-T15 | 评分验收 harness：10 条标准答案、同档一致率、跳题行为 | 验收 | `tests/test_scoring_acceptance.py` |
| AP-T16 | 回归：现有 291 测试全绿；配比测试改为五型 | v1 | 全量 |

## 14. 开放问题与风险

1. **材料薄**：当前只有一份材料、6 个概念；业务/成本/取舍可能缺依据。用户已确认**先补 1–2 份业务型材料（PRD/业务案例）再开工**；补完后按正常 `ingest → extract → confirm → reindex` 入库，再实现与验收。不降标准。
2. **生成延迟**：1 次生成约 3–8 秒 + 5 次评分；start 时显示“正在根据材料出题”。如果实际不可接受，后续做预生成缓存；本轮坚持现场。
3. **生成质量**：DeepSeek 仍可能出“是什么”题、程序题或空洞 rubric；MiMo 已因输出上限淘汰。validator + 人工盲评双保险；不合格重生成，不手改题目（手改破坏可审计性）。
4. **回退污染**：旧题库题不是五型；必须标记、UI 显示、不计入验收。回退率要记录；回退率高说明材料/提示词有问题。
5. **评分一致性**：新题型 rubric 更主观；先 10 条诊断，再 holdout；不达标不改标准硬刷。
6. **Spec 冲突**：v2.0 冻结的五题配比被覆盖；按 FREEZE 规则登记，不暗改。
7. **成本**：每次会话约 6 次 LLM 调用（1 生成 + 5 评分），修复/重试另计；单用户可接受，未做成本上限。
8. **模型分工**：生成与评分都用 DeepSeek；同模型自评可能偏宽松。10 条人工一致率 gate 已验证 8/8；后续可换独立评分模型复验。
9. **题型边界**：综合判断与取舍权衡可能重叠；盲评时按“是否多因素决策”区分，报告里记录边界案例。
10. **材料链接**：`local://` 路径在 Web 上不可点击；本轮显示摘录 + 材料路径，后续再做本地材料查看页。
11. **抽取上限**：抽取器每个父块最多 3 个概念；长父块里业务概念可能被技术概念挤掉。首批用人工补候选并校验逐字摘录；后续考虑按小节切父块或提高上限（需设计变更）。
12. **同模型自评**：生成和评分都是 DeepSeek；可能奖励自己出的题。人工一致率是主 gate；若后续发现系统性偏松，换独立评分模型重跑 10 条 holdout。
13. **语义溯源**：逐字校验通过不等于语义支撑；本轮人工确认 10/10，但后续仍需抽查，必要时加 reviewer 模型做语义预检。

## 15. 与 v2.0 / FREEZE 的关系

- 本设计是 v2.0 的子设计；优先级 v2.0 > 本文档 > 技术方案。
- 覆盖 v2.0 的具体条款：
  - §评分契约的“2 recall + 2 discriminate + 1 apply”配比 → 五型各 1 + 2+3 场次构成。
  - §题目来源的“v0 题库全部预写 / v1 自动解析抽题” → 现场检索生成 + 旧题库回退。
  - §数据模型的 `session_questions` → 追加三列（加法）。
- 不改变 v2.0 的：逐题评分、五档 rubric、单题失败语义、mastery/review_due、每题出处、无外部热路径。
- 实现前在 `FREEZE.md` 的“待变更登记”表补一行；不直接改 v2.0 正文。实现完成并稳定后，再决定是否把 v2.0 升到 v2.1 并重算哈希。

## 16. 产品分叉确认记录（2026-11-24）

| # | 分叉 | 确认结果 | 备选 |
|---|---|---|---|
| 1 | 第五道题型 | 已确认：加“综合判断”，五型各 1 | 四型 + 业务 2 / 四型 + 取舍 2 / 四型 + 误区诊断 |
| 2 | 场次构成 | 已确认：2 复习 + 3 新概念；复习只取 1 个最逾期概念 | 一场只考一个概念 / 旧格式复习混排 |
| 3 | 生成失败 | 已确认：回退旧题库并标记，不阻塞 | 阻塞要求补材料 / 少出几题 |
| 4 | 溯源展示 | 已确认：作答前只给题型；评分后给出处 | 答前给出处 / 只在数据库 |
| 5 | 评分一致口径 | 已确认：8 已答 + 2 跳题；同档；6/8 + 2/2 | 10 条都计 / 精确分差 ≤15 |
| 6 | 验收重跑 | 已确认：改动后用全新 10 条 holdout | 同一组 10 条重跑 / 一次 20 条 |
| 7 | 材料策略 | 已确认：先补 1–2 份业务型材料，再开工 | 先跑现有材料再补 / 允许通用业务常识 |

以上 7 项已确认；实现按此执行。后续如需变更，走本设计文档更新与 `FREEZE.md` 登记。

## 16.5 Spike 结果（2026-11-24）

- **出题**：MiMo 一次 5 题在第 2-3 题截断；5 路单题并行也只成功 2/5。DeepSeek 一次 5 题完整可解析。10 题盲评：题型 10/10、理解 10/10、业务视角 10/10、溯源 10/10；首轮 9/10 逐字溯源，1 题修复后通过。
- **评分**：10 条标准答案（3 全对、3 对一半、2 跑题、2 跳题）；8/8 同档一致，2/2 跳题不评分。第 3 题首次把 `session_misconception` 写成字符串，契约校验拒绝；重试一次后返回对象，分数 45 与人工 half 同档。
- **报告**：`docs/designs/review-20261124/question-spike.md`、`scoring-spike.md`。
- **影响**：生成模型改 DeepSeek（AP-19）；契约收窄（AP-17）；主出处优先（AP-18）；评分提示词显式约束 `session_misconception`。

## 17. 实施顺序

| 顺序 | 任务 | 验证 |
|---|---|---|
| 0 | 补 1–2 份业务型材料（PRD/业务案例），走 `ingest → extract → confirm → reindex` | 已完成 2026-11-24：2 份材料、14 个新概念、13 条 FTS、5 条 embedding；新概念先停留 `proposed` |
| 1 | Schema v6 + Store 三字段 + `RetrievedChunk.chunk_id` | 迁移测试、旧测试全绿、读写新字段 |
| 2 | `core/question_generation.py`：类型/Plan/compact 契约/校验/修复 | AP-T01–T05 单测 |
| 3 | `bff/question_generation.py`：主出处 + 检索上下文 + DeepSeek + 解析（先 fake） | 端到端 fake、无外部来源守卫 |
| 4 | Coach 接线：start 生成、回退、持久化、question 事件带题型 | AP-T06/T07/T13 |
| 5 | 评分提示词 v2 + 类型规则 + `session_misconception` 约束 + score 事件带出处 | AP-T08–T10 |
| 6 | 验收 harness：10 题盲评、10 答案评分、报告 | AP-T14/T15 |
| 7 | 真实跑验收：2 场生成、10 题盲评、10 答案评分；spike 已先验一轮，实现后按正式链路复跑 | 报告落盘；通过线见 §9 |
| 8 | OpenSpec change + FREEZE 登记 + VERSIONS 更新；实现稳定后归档 | 文档一致、测试全绿 |

估算：材料准备已做；实现 3–5 个工作日；正式验收与校准另计 0.5–1 天。
