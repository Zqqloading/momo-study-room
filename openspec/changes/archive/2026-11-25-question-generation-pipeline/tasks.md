# Tasks

## 1. Schema 与检索基础

- [x] 1.1 `SCHEMA_VERSION` 升到 6，`session_questions` 加法 `question_type`/`source_chunk_id`/`generation_meta_json`；验证：v5 库升级后旧行可读、新列可写，迁移测试与旧测试全绿
- [x] 1.2 `RetrievedChunk` 增加 `chunk_id`/`parent_chunk_id`，检索组装时填入；验证：`tests/test_retrieval.py` 断言字段存在且不改变 FTS/向量/RRF 结果
- [x] 1.3 `Store.add_question` 接受三个新字段；新增 `previous_question_texts(concept_id, limit)`；验证：`tests/test_store.py` 覆盖读写与旧行 NULL

## 2. 出题契约与校验

- [x] 2.1 `core/question_generation.py` 定义五型、`Slot`/`SessionPlan`、`GeneratedQuestion`/`GeneratedSet`；验证：`tests/test_question_plan.py` 覆盖无复习/有复习/只有复习/同概念四种配比
- [x] 2.2 实现 compact 出题提示词与 JSON 解析；程序按 0/40/70/90/100 生成五档 rubric；验证：`tests/test_question_generation.py` 断言 5 槽位、字段齐全、五档固定
- [x] 2.3 实现 `validate_question_set`：槽位/题型/逐字摘录/业务禁词/题内去重/字段完整性；验证：单测覆盖每条硬失败与软警告
- [x] 2.4 实现修复提示词与失败槽位重写；验证：单测覆盖一次修复成功、修复仍失败 → `GenerationError`
- [x] 2.5 无外部来源守卫：出题模块不 import 搜索适配器、不读 `hot_items`、不写 `question_bank`/seeds；验证：静态 import 检查 + 行为测试（搜索 provider 被调用即失败，生成仍能跑）

## 3. BFF 生成器

- [x] 3.1 `bff/question_generation.py` 构建上下文：主出处 `[1]` + 检索 top5 父块去重；检索为空只用主出处；主出处缺失抛 `GenerationError`；验证：fake embedder + 真实 material_chunks 的集成测试
- [x] 3.2 接 DeepSeek 生成、解析、校验、修复；验证：`ScriptedLLM` 返回合法/坏 JSON/缺字段/坏摘录，覆盖成功与回退
- [x] 3.3 生成元数据记录 model/prompt_version/retrieved_chunk_ids/repair_count/validation；验证：落库后 `generation_meta_json` 可解析

## 4. Coach 接线

- [x] 4.1 `Coach.start` 构建 `SessionPlan`，调生成器；`GenerationError` 时回退旧题库；验证：`tests/test_coach_flow.py` 覆盖生成成功、生成失败回退、回退题不足 → `NoSessionAvailable`
- [x] 4.2 生成题落 `session_questions` 带 `question_type`/`source_chunk_id`/`generation_meta_json`；`question` 事件带题型不带出处；验证：`tests/test_ws.py` 断言事件字段
- [x] 4.3 `answer` 评分传题型、摘录、参考答案；`score`/`session_result` 带出处；验证：`tests/test_ws.py` 断言 score 与 result 字段
- [x] 4.4 2 复习 + 3 新概念的角色拆分与 mastery/review_due 计算；验证：`tests/test_ratios.py` 改为五型配比，`test_mastery.py`/`test_review.py` 覆盖混合场

## 5. 评分 v2

- [x] 5.1 `core/scoring.py` 类型感知提示词：反背诵 + 题型封顶；验证：`tests/test_scoring.py` 覆盖五型封顶与完整答案
- [x] 5.2 `session_misconception` 只能是 null 或对象；字符串判解析失败并重试一次；验证：坏 shape → 重试成功/失败语义
- [x] 5.3 生成题参考答案优先 `rubric_json.reference_answer`；验证：反馈文本使用生成答案，不覆盖

## 6. 前端

- [x] 6.1 题卡显示五型中文标签；`kindLabel` 保留回退题旧标签；验证：浏览器/WS 测试断言题型文本
- [x] 6.2 评分后显示出处（摘录 + 材料链接），验收卡逐题显示题型/分数/出处；验证：`tests/browser` 或 WebSocket 事件断言
- [x] 6.3 回退题显示“旧题回退”，不显示“根据材料生成”；验证：回退会话的页面/事件断言

## 7. 验收 harness

- [x] 7.1 出题验收 CLI：生成 2 场、导出盲评表（隐藏声称题型）、读人工标签计算四项通过率；验证：fake 生成器的 harness 单测
- [x] 7.2 评分验收 CLI：导出 10 题 + 标准答案模板、跑真实 scorer、按档位计算一致率；验证：fake scorer 的 harness 单测
- [x] 7.3 真实出题验收：10 题盲评，记录题型/理解/业务视角/溯源；验证：报告落 `docs/designs/review-<日期>/question-acceptance.md`，通过线见设计 §9.1
- [x] 7.4 真实评分验收：3 全对 + 3 对一半 + 2 跑题 + 2 跳题；验证：≥6/8 同档 + 2/2 跳题；报告落 `scoring-acceptance.md`
- [x] 7.5 若改过 prompt/rubric/标准，用全新 10 条 holdout 复验；验证：holdout 报告，不在原 10 条上刷分

## 8. 文档与上线

- [x] 8.1 同步 OpenSpec 主 spec、`FREEZE.md` 待变更登记、`VERSIONS.md` 哈希；验证：`openspec validate question-generation-pipeline --strict` 通过
- [x] 8.2 出题链路可用后，把新材料确认的 14 个 `proposed` 概念转 `active`；验证：Planner 能选出新概念且生成 5 题
- [x] 8.3 全量回归：`python -m pytest -q` 全绿；真实 provider 烟雾（生成 + 5 题评分 + 结算）通过
- [x] 8.4 更新 `README.md` 当前阶段与已知缺口；验证：文档命令可照抄运行

## Workflow follow-up

- 实现完成、验收报告通过后，按 OpenSpec 流程归档 change，并同步主 specs。
- 归档后复核 `FREEZE.md` 与 `VERSIONS.md` 的哈希与偏离登记。
