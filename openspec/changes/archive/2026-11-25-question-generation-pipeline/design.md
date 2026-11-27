# Design

## Context

当前 `Coach.start` 从 `question_bank` 取预写题，按 `recall / discriminate / apply` 配比；检索（`core/retrieval.py` 的 FTS5 trigram + 向量 + RRF）与逐题评分（`core/scoring.py` 的 DeepSeek 五档 JSON）都已可用，但没有接成出题链路。`session_questions` 缺题型与 chunk 级溯源字段，schema 为 v5。

2026-11-24 两轮 spike 已确认：MiMo 单次输出约 600-700 汉字，一次 5 题或单题完整 rubric 都会截断；DeepSeek 一次 5 题完整可解析。10 题盲评四项 10/10；8 条标准答案评分 8/8 同档，2/2 跳题不评分。详见 `docs/designs/review-20261124/`。

完整设计（题型定义、契约、验收细则）见 `docs/designs/assessment-pipeline-v0.1.md`；本文件只记录实现级决策。

## Goals / Non-Goals

**Goals:**

- `Coach.start` 现场生成 5 道五型业务题；失败可回退，不阻塞会话。
- 每题持久化题型、逐字摘录、chunk id 与生成元数据；评分后展示出处。
- 评分按题型封顶、反背诵；保留逐题即时、重试一次、unscored 语义。
- 出题只读本地知识库；外部补充链路记录为后续。

**Non-Goals:**

- 不做外部搜索/抓取/热项出题；不做题库自动回灌/审核。
- 不做综合场、跨概念讲解、语音链路改动。
- 不做自适应出题（根据上一题回答改下一题）。
- 不改自由对话检索的 top3 契约。

## Decisions

1. **生成模型用 DeepSeek，不用 MiMo**。MiMo 单次输出不够，5 路单题并行也只成功 2/5；DeepSeek 一次 5 题完整。评分也用 DeepSeek；自评偏好风险由 10 条人工一致率 gate 兜。备选：MiMo 分两次调用（更复杂、质量仍受限）。
2. **SessionPlan 固定槽位**。5 个槽位与题型由程序决定：无复习时五型各 1；有复习时主概念拿概念/业务/取舍，复习概念拿成本/综合；只有复习时五型全给复习概念；同概念时拆 2 review + 3 new。模型只写题，不改题型/配比。
3. **compact 生成契约**。模型返回题干、参考答案、`must_have`、`red_flags`、`source_ref`、`source_excerpt`；五档 rubric 由程序按 0/40/70/90/100 生成。备选：模型写五档（输出膨胀、易截断、档位漂移）。
4. **主出处优先的上下文**。概念主出处父块放 `[1]`，检索 top5 父块按父块去重后置 `[2..]`；检索为空只用主出处；主出处也没有则生成失败。备选：只按检索顺序（spike 发现会选无关/过短句）。
5. **校验一次修复、整场回退**。硬校验 5 槽位/题型/逐字摘录/禁词/去重；失败只修复失败槽位一次；仍失败整场回退旧题库，不混用生成题与旧题。回退题标记 `origin=fallback`，不进生成验收。
6. **Schema v6 加法**。`session_questions` 加 `question_type`、`source_chunk_id`、`generation_meta_json`；旧行为 NULL。`kind` 映射：concept→recall，其余→apply；生成题全开放，`discriminate` 只用于回退。`RetrievedChunk` 加 `chunk_id`/`parent_chunk_id`。
7. **评分提示词 v2**。输入题型、题干、摘录、`must_have`/`red_flags`、参考答案；加入反背诵与题型封顶；`session_misconception` 只能是 null 或对象，字符串触发重试一次。备选：通用提示词（会奖励背诵）。
8. **无外部补充**。出题模块不 import 搜索适配器、不读 `hot_items`、不写 `question_bank`/seeds；规则见 ADR 0002。备选：允许搜索补事实（破坏溯源）。
9. **验收 harness 独立于运行路径**。10 题盲评与 10 标准答案评分用 CLI 导出/复验，不自动改提示词、不自动改人工标签；改动后用全新 10 条 holdout。

## Risks / Trade-offs

- [同模型自评偏松] → 10 条人工一致率 gate；后续可换独立评分模型复跑 holdout。
- [材料覆盖不足] → 先补材料再开工；出题前检索为空/主出处缺失直接回退，不编外部事实。
- [生成延迟集中到开场] → 显示“正在根据材料出题”；后续可做预生成缓存，本轮不做。
- [回退污染验收] → 回退题标记、UI 显示、导出样本只含 `origin=generated`。
- [逐字溯源 ≠ 语义支撑] → 人工盲评按语义支撑判；提示词要求完整句、直接支撑题干。
- [Spec 冲突] → v2.0 五题配比被覆盖；已在 FREEZE 待变更登记，不暗改正文。
- [Coach 构造签名变更波及测试] → 测试工厂加 fake generator；生产路径必须注入真实生成器。

## Migration Plan

1. `SCHEMA_VERSION` 5 → 6，`init_schema` 按列名补三列；旧库原地升级，旧行 NULL 可读。
2. 先落 `core/question_generation.py` 契约与 fake 测试，再接 `bff/question_generation.py`，最后改 `Coach.start` 与 `bff/main.py` 注入。
3. 评分提示词 v2 与 `session_misconception` 约束先跑 fake，再跑真实 10 条 spike/holdout。
4. 回滚：代码回退到 v5 读取路径可忽略新列；生成失败/关闭生成器时走旧题库，会话仍可用；schema 新列不删除。
5. 材料已入库；新概念先在 DB 停 `proposed`，出题链路可用后转 `active`。

## Open Questions

- 是否在后续把评分换成独立模型复验自评偏好；本轮不改。
- 生成缓存/预生成是否值得做；本轮坚持现场生成，等延迟数据。
