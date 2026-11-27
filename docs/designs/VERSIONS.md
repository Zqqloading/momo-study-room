# 文档版本索引

- 目录：`docs/designs/`
- 版本规则：新版本新建文件，不改旧版本；文件名 `<文档名>-v<major>.<minor>.md`。
- 状态：`DRAFT` → `REVIEW` → `FROZEN`。FROZEN 版本必须记录 SHA-256；冻结后的正文改动走 `FREEZE.md`。
- 哈希算法：SHA-256，按文件字节计算。

## 当前版本

| 文档 | 版本 | 状态 | 日期 | SHA-256 | 替代 | 文件 |
|---|---|---|---|---|---|---|
| 设计：数字人学习伴侣 | v2.0 | FROZEN | 2026-11-24（三次修订） | `03c4b5dc42c7a8f38cad46c8021ce6faa8a0da1054fe9459260586fb31e0f1f5` | v1.0 | `learning-companion-digital-human-v2.0.md` |
| 设计：Agent 基础设施 | v0.1 | DRAFT | 2026-11-24 | `5efdc49256408b1fe4822e775cab070f5ea0dc2aac613f0c7d68d65a7e143eec` | — | `agent-infrastructure-v0.1.md` |
| 设计：Agent Harness 运行时 | v0.1 | REVIEW | 2026-11-25 | `3071b4a5eee8209f73e7c90d636ad177ab3595064a362271c092add6de6e9ae4` | — | `agent-harness-v0.1.md` |
| 设计：工具规格书 | v0.1 | DRAFT | 2026-11-25（基准 2026-11-20） | `6e3c8cafdfc893ebc5508f7c2b612b3a8ff318c9f0cc4d3cea36fcc56838cd3e` | — | `tool-specs-v0.1.md` |
| 实现规格：第一片 | v0.1 | DRAFT | 2026-11-23 | `e0fcc4b530a13936bd3556f15898ac07c6ae3a94e64b06c56a6e83214aa01013` | — | `first-slice-v0.1.md` |
| 设计：知识入库 | v0.1 | DRAFT | 2026-11-24 | `13da43a9a7008ea2038cb01af243d0e238c358b21d12709d46fda40d90fb0608` | — | `knowledge-ingestion-v0.1.md` |
| 设计：知识检索 | v0.1 | DRAFT | 2026-11-23 | `0c62027cda41d88121713518b77ad94f45c29cc789ae47692b3f01c6c58e3467` | — | `knowledge-retrieval-v0.1.md` |
| 设计：出题与评分管线 | v0.1 | DRAFT | 2026-11-24 | `87d969be2cdb66080de6ec7cdff8138a0adb76c8167cd42a2b7e38971d95cd28` | — | `assessment-pipeline-v0.1.md` |
| 设计：学习单元 | v0.1 | DRAFT | 2026-11-25 | `f5d04d373bb533ca60c621d189c3ae347b42dac1cc33fd50ef8d50ed31be78b4` | — | `learning-unit-v0.1.md` |
| 设计：数字人设定集 | v0.1 | DRAFT | 2026-11-26 | `2c8af5ccf7205cb09a61b0f7dfc0703308c613fbf3f26423f449b5e7f7466d0a` | — | `persona-settings-v0.1.md` |
| 设计：数字人情绪状态 | v0.1 | DRAFT | 2026-11-26 | `4c812d00c29fb55998e0ec38ce6bb31b3b3212a1274732af88e0803cd6fd854e` | — | `emotion-state-v0.1.md` |
| 设计：情绪表情与待机动作 | v0.1 | DRAFT | 2026-11-26 | `13752133cdbbf69537523410160733d4ef43450c71f0ae6e6a5e9486b1f27504` | — | `emotion-expression-v0.1.md` |
| 设计：用户长期记忆 | v0.1 | DRAFT | 2026-11-26 | `36cc0340cf285e204b39a7561ecac6f3c2efa166ee79545b08549ced43681a03` | — | `user-memory-v0.1.md` |
| 设计：管理后台（react-admin） | v0.1 | DRAFT | 2026-11-26 | `9602ec2e9ba92747f91e876b7791cd620955333c62cfa4bba93d4baf643d4410` | 手写 `web/admin/` 只读工作台 | `admin-console-v0.1.md` |
| 设计：进度驱动选题 | v0.1 | REVIEW | 2026-11-25 | `b173e9abeec9076be4e16a41adedd516d5a53d8527433c04b730fd75bbd47a1a` | — | `progress-driven-start-v0.1.md` |
| 设计：存储分层 | v0.1 | DRAFT | 2026-11-23 | `154918e3ce3c75e6d6b1208805d3ab045236fbd0fe5c804b209acd8590e85366` | — | `storage-layers-v0.1.md` |
| 设计：实时知识热注入 | v0.1 | DRAFT | 2026-11-24 | `6a0cc78a96ccf97e24acbd4dc78f49f8e9152194f27e57610f2afbaf5f10e2ea` | — | `realtime-knowledge-v0.1.md` |
| 技术方案：v0 | v0.1 | DRAFT | 2026-11-24（移除摸底、自由对话常开） | `fffa90b9de545c918b8f13b0e1a7c2a699999259d7d80062a72d073d5be272fe` | — | `technical-plan-v0.1.md` |
| 设计：数字人学习伴侣 | v1.0 | FROZEN | 2026-11-21 | `c76afc94897b84d86b3a68786cf8a2be24dd0dcaa573ccf3777a6225b3acc086` | — | `learning-companion-digital-human.md` |

## 替代关系

- v2.0 与 v1.0 的差异只来自 2026-11-21 `/plan-eng-review` 的决策 D3-D8 与发现 F1-F6；产品层面的冻结决定不变。
- 2026-11-23 的 POC 调整只改交互链路、考评位置与检索边界，不改上述产品冻结决定。
- v2.0 于 2026-11-23 冻结；实现依据以 v2.0 为准，历史讨论以 v1.0 为准。
- 2026-11-24 按实现收敛：撤销摸底与自由对话配置开关，详见 `FREEZE.md`。
- 2026-11-25 新增 `agent-harness-v0.1.md`：取代 `agent-infrastructure-v0.1.md` 的运行时决策（AI-06/AI-21/AI-22/AI-23 与 §1.4/§1.5/§6.4），存储、`agent_sessions`、事件契约与同日恢复继续沿用；v2.0 只登记 P3 的检索触发方式变更。
- 2026-11-25 新增 `tool-specs-v0.1.md`：细化 `agent-harness-v0.1.md` 的工具契约、次数与 A/P/U 结果分离；不替代运行时决策，不改 v2.0 正文。
- v1.0 文件保持字节不变，作为冻结基线保留。

## v2.0 冻结记录

- 冻结日期：2026-11-23；正文 SHA-256 见上表。
- 冻结原因：POC 验证后修正交互链路（点击 + VAD）、补会话层/语音层与考评位置、收敛联网边界与 TTS 边界。
- 后续改冻结版：先在 `FREEZE.md` 记录原因、影响章节与新哈希，再改正文。
- 2026-11-24 冻结后调整：撤销摸底（P7）与自由对话配置开关（P8 开关部分），见 `FREEZE.md`。

## 命名规则

| 文档 | 文件名 |
|---|---|
| 设计 | `learning-companion-digital-human-v<major>.<minor>.md` |
| 知识入库 | `knowledge-ingestion-v<major>.<minor>.md` |
| 知识检索 | `knowledge-retrieval-v<major>.<minor>.md` |
| 出题与评分管线 | `assessment-pipeline-v<major>.<minor>.md` |
| Agent Harness 运行时 | `agent-harness-v<major>.<minor>.md` |
| 工具规格书 | `tool-specs-v<major>.<minor>.md` |
| 学习单元 | `learning-unit-v<major>.<minor>.md` |
| 数字人设定集 | `persona-settings-v<major>.<minor>.md` |
| 数字人情绪状态 | `emotion-state-v<major>.<minor>.md` |
| 情绪表情与待机动作 | `emotion-expression-v<major>.<minor>.md` |
| 用户长期记忆 | `user-memory-v<major>.<minor>.md` |
| 存储分层 | `storage-layers-v<major>.<minor>.md` |
| 实时知识 | `realtime-knowledge-v<major>.<minor>.md` |
| 技术方案 | `technical-plan-v<major>.<minor>.md` |
| 实现规格 | `first-slice-v<major>.<minor>.md` |
| 评审记录 | `review-YYYYMMDD/` 目录 |
| API 探针报告 | `api-probe/YYYY-MM-DD-HHMMSS.md` |
| ASR 验收报告 | `asr-test-set/report-YYYY-MM-DD-HHMMSS.md` |

## 变更记录

| 日期 | 文档 | 从 | 到 | 摘要 |
|---|---|---|---|---|
| 2026-11-21 | 设计 | v1.0 FROZEN | v2.0 DRAFT | 合并 `/plan-eng-review` 决策 D3-D8 与发现 F1-F6 |
| 2026-11-21 | 技术方案 | — | v0.1 DRAFT | v0 详细（模块、表、接口、测试映射）+ v1/v2 概要 |
| 2026-11-22 | 设计 + 技术方案 | v2.0/v0.1 DRAFT | 同版本更新 | 记录 MiMo LLM/ASR 与 Breeze TTS 实测连通和延迟；2.5s 未达，4s 兜底 |
| 2026-11-23 | 设计 | v2.0 DRAFT | v2.0 FROZEN | POC 后调整交互链路：点击收音 + VAD 切句/判停；补会话层/语音层两层链路与考评位置；联网只做材料入口；题目音频优先预合成；哈希 `c9e604…` |
| 2026-11-23 | 技术方案 | v0.1 DRAFT | 同版本更新 | 同步点击 + VAD、两层链路、WS 事件协议、评分时机与验收口径；现状更新为 63 测试 |
| 2026-11-23 | Agent 基础设施 | — | v0.1 DRAFT | 新建子设计：问题主线、可感知变化、影响范围、决策记录、agent_sessions 存储规范、最小 Agent 与回合管线 |
| 2026-11-23 | 设计 | v2.0 FROZEN | 同版本二次修订 | 逐题即时评分、第 5 题自动结算、摸底纳入 v0、自由对话改配置开关；DeepSeek Flash 接通；哈希 `5a8f58…` |
| 2026-11-23 | Agent 基础设施 | v0.1 DRAFT | 同版本更新 | 落定逐题评分失败语义、自动结束、摸底、自由对话开关、同日恢复、次日复习、误解一场一条、评分校准单列；新增模式路由（教学/答题/澄清/命令）与 v0 路由规则；哈希 `5408e3…` |
| 2026-11-23 | 技术方案 | v0.1 DRAFT | 同版本更新 | 同步逐题评分、单题失败语义、第 5 题自动结算、次日复习、摸底统计口径与 DeepSeek 实测 |
| 2026-11-23 | 第一片实现规格 | — | v0.1 DRAFT | 新建第一片切片规格：文本 + 语音、5 题、逐题评分、自动结算、mastery、同日恢复；含 WS 协议、失败降级、测试映射与实现顺序；哈希 `e0fcc4…` |
| 2026-11-23 | 知识库 | — | v0.1 DRAFT | 新建子设计：三个失真点、KB 决策表、文件真相源 + 同库镜像、v0 手工/v1 自动管线、`Retriever` 端口、验收与测试映射；首批材料与确认契约见开放问题 |
| 2026-11-23 | 知识库 + Agent 基础设施 | v0.1 DRAFT | 同版本更新 | DB grill：v0 接入 6 表、版本迁移、写路径收紧、chunk 哈希、cache slot、自动回灌 + 跨模型预检、全量镜像、seeds 原子写、停应用备份、旧出处人工确认；FREEZE 登记偏离与加法变更 |
| 2026-11-23 | 知识库 | v0.1 DRAFT | 同版本更新 | 摄取 grill：v1 离线 CLI、标准库解析 + 字符 token、切块边界、DeepSeek 抽取 + 候选暂存、硬/软门槛、CLI 两步确认 + ruamel、通过率基线；FREEZE 记三条偏离 |
| 2026-11-23 | 知识库 | v0.1 DRAFT | 同版本更新 | 确认 CLI 落地：两步确认、YAML 先 + status 后、`--reapply`、`ruamel.yaml` 依赖；新增 KB-27/KB-T27 |
| 2026-11-23 | 知识库 | v0.1 DRAFT | 同版本更新 | 端到端集成测试：ingest → extract(fake) → confirm，产物 join 校验；新增 KB-T28 |
| 2026-11-23 | 知识库 | v0.1 DRAFT | 同版本更新 | 检索 grill：阿里 text-embedding-v3/1024、chunk_embeddings BLOB + numpy、FTS5 trigram、query=名称+别名+定义、top20+RRF k=60→top5、20 条 Recall@5≥0.8、入库批量嵌入 + reindex；新增 KB-28…KB-35 |
| 2026-11-23 | 知识库 | v0.1 DRAFT | 同版本更新 | 检索核心落地：schema v3 + chunk_embeddings/chunk_fts、Retriever（FTS+numpy+RRF+父块去重+降级）、reindex FTS 重建；Retriever 增加 query_vector 入参；新增 KB-T29…T31 |
| 2026-11-23 | 知识库 | v0.1 DRAFT | 同版本更新 | 阿里 embedding 接入：`EMBEDDING_*` 配置、OpenAI 兼容 `/embeddings` 适配器、FakeEmbedder、ingest 批量嵌入 + `--no-embed`、reindex 补缺失；新增 KB-T32 |
| 2026-11-23 | 知识库 | v0.1 DRAFT | 同版本更新 | 查询侧封装：`bff/retrieval.py` 拼名称+别名+定义、异步嵌入一次、失败退 FTS；FTS query 改为按词 OR；新增 KB-T33 |
| 2026-11-23 | 知识库 | v0.1 DRAFT | 同版本更新 | 澄清 embedding 批次文案：每批 10 个 chunk，不是 10 元 |
| 2026-11-23 | 知识库 | v0.1 DRAFT | 同版本更新 | embedding 切到阿里 `text-embedding-v4`（同价、100 万 token 免费额度/90 天）；默认模型与配置同步 |
| 2026-11-23 | 知识库 | v0.1 DRAFT | 同版本更新 | 真实 smoke：DeepSeek 抽取 3 候选、v4/1024 嵌入 4 块、检索命中；修子块 heading_path/跨小节合并，摘录按 query 选句；新增 KB-T34 |
| 2026-11-23 | 知识库 | v0.1 DRAFT | 同版本更新 | 首批材料 ingest 8 块 + 抽取 6 候选；`concept_sources` 父块→子块回溯，摘录优先概念主出处；新增 KB-T35 |
| 2026-11-23 | 知识库 | v0.1 DRAFT | 同版本更新 | 确认 3 active / 3 skipped；生成 15 题并落 `seeds/question_bank.json` + `question_bank`；真实检索修复同父块多概念归属；新增 KB-T36 |
| 2026-11-23 | 知识库 | v0.1 DRAFT | 拆分为入库/检索 | 原 `knowledge-base-v0.1.md` 拆成 `knowledge-ingestion-v0.1.md` 与 `knowledge-retrieval-v0.1.md`；检索决策改为 KR-01…KR-09；`core.ingest` 不再调 embedding/FTS，索引由 `core.reindex` 建 |
| 2026-11-23 | 存储分层 | — | v0.1 DRAFT | 新建子设计：L0–L5 分层定义、层间不变量、重建矩阵、写边界；L0/L1/L2 不新增结构，只新增 `pipeline_runs`（L5 管线运行审计） |
| 2026-11-23 | 知识入库 | v0.1 DRAFT | 同版本更新 | 新增 §6.5 切块细则与调参基线：候选参数 280-420、表格行组切分、`content_hash` 向量复用、`reindex --prune`；新增 KB-36…KB-38 与 KB-T37…KB-T39 |
| 2026-11-23 | 存储分层 | v0.1 DRAFT | 同版本更新 | L4 增加 `hot_items`/`hot_fts` 未核实缓冲区；新增 IN-L4-4 与 SL-09/SL-10 |
| 2026-11-23 | 实时知识 | — | v0.1 DRAFT | 新建子设计：会话内超纲与高频问题的双层捕获、`hot_items`/`hot_fts`（L4）、TTL 7 天、晋升 CLI；RT-01…RT-06 |
| 2026-11-23 | 知识入库 | v0.1 DRAFT | 同版本更新 | 实现回写：KB-38 复用键加入 `heading_path`（嵌入输入含小节路径，只比 `content_hash` 会复制错上下文向量） |
| 2026-11-23 | 存储分层 | v0.1 DRAFT | 同版本更新 | 全分支审查回写：IN-L0-3 澄清同哈希不同 path 按新材料建行，只有旧路径消失才识别为改名 |
| 2026-11-24 | 设计 | v2.0 FROZEN | 同版本三次修订 | 撤销摸底与初始 mastery 校准；撤销自由对话配置开关，改为初始界面常开；哈希 `03c4b5…` |
| 2026-11-24 | Agent 基础设施 | v0.1 DRAFT | 同版本更新 | 移除摸底与 `FREE_CHAT_ENABLED`；自由对话常开；哈希 `902faf…` |
| 2026-11-24 | 技术方案 | v0.1 DRAFT | 同版本更新 | 移除摸底与 `session_start` 的 diagnostic；同步自由对话常开 |
| 2026-11-24 | Agent 基础设施 | v0.1 DRAFT | 同版本更新 | 合并知识库分支：`SCHEMA_VERSION=5`、按表名补齐、`conversation_messages.sources_json`；哈希 `5efdc4…` |
| 2026-11-24 | 知识入库 | v0.1 DRAFT | 同版本更新 | KB-06 超纲兜底改为由 `free-talk-web-search` 实现（仅自由对话，不写知识库）；哈希 `13da43…` |
| 2026-11-24 | 实时知识 | v0.1 DRAFT | 同版本更新 | RT-02 澄清 hot 不接网页；自由对话联网兜底见新 change；哈希 `6a0cc7…` |
| 2026-11-24 | 出题与评分管线 | v0.1 DRAFT | 同版本更新 | 两轮 spike：出题 10/10（题型/理解/业务视角/溯源），评分 8/8 同档 + 2/2 跳题；生成模型 MiMo→DeepSeek，compact 契约，主出处优先，`session_misconception` 约束；材料已入库、14 个新概念先 proposed；新增 `review-20261124/question-spike.md`、`scoring-spike.md`；哈希 `50831c…` |
| 2026-11-24 | 出题与评分管线 | — | v0.1 DRAFT | 新建子设计：现场检索出题、五型各 1、2 复习 + 3 新概念、逐字溯源、生成失败回退、类型感知评分、10 题盲评与 10 答案一致率验收；外部补充链路记录为后续；材料策略确认先补 1–2 份业务型材料再开工；新概念先 proposed 等出题管线可用；哈希 `50831c…` |
| 2026-11-25 | 出题与评分管线 | v0.1 DRAFT | 同版本更新 | 实现验收：出题 10 题（题型 10/10、业务视角 10/10、溯源 10/10、理解 8/10）；评分 7/8 同档 + 2/2 跳题；报告 `review-20261125/`；哈希不变 `50831c…` |
| 2026-11-25 | 学习单元 | — | v0.1 DRAFT | 新建：学习单元 = 一场 5 题会话；知识库面板承载今日提议/掌握程度/最近单元；只读提议与总览 API；结算新增概念 before/after；不改 schema、mastery 公式与语音链路；哈希 `f5d04d…` |
| 2026-11-25 | Agent Harness 运行时 | — | v0.1 REVIEW | 新建：单元流程留程序，模型在步骤内决定检索/换说法/停止；3 个只读检索工具归 agent，出题/评分/进度归程序；自写有界循环（仅用 `openai` SDK）；预算/超时/失败观测；v1 不流式；三步落地；接口与页面验收。取代 v2.0 P3 的检索触发方式与 agent-infrastructure v0.1 的 AI-06/AI-21/AI-22/AI-23；哈希 `c90a21…` |
| 2026-11-25 | Agent Harness 运行时 | v0.1 REVIEW | 同版本更新（grill 定稿） | 18 项结论：free_talk + teach/clarify；作答零工具；本地优先仅提示；无依据允许常识但服务端强制前缀；重复提交幂等重放；默认模型改 DeepSeek（可切 MiMo）；预算 3/2/30；3 个工具；工单只看当前题；显式提问入口；讲解朗读；历史仅连接内；日志审计；网页不可信隔离；8/10 软门槛；上一题分数上下文；来源列全部；开关默认 off。新增 AH-16…AH-22、`StepBrief.last_scored`、§4.7、§11；哈希 `c90a21…` |
| 2026-11-25 | Agent Harness 运行时 | v0.1 REVIEW | 同版本更新（实现） | 三步落地：工具契约/三个适配器、StepBrief/有界循环、`AGENT_HARNESS` 派发、重复提交幂等、页面提问/状态/刷新恢复；真实冒烟 10/10（DeepSeek 1879ms / MiMo 2625ms）；497 测试与页面检查通过；前缀改为服务端唯一处理；未改 schema；哈希 `3071b4…` |
| 2026-11-25 | 工具规格书 | — | v0.1 DRAFT | 新建：17 个当前工具 + 3 个回合的“4 问 + 3 规矩”；A/P/U 结果分离；G1–G8 通用禁令；8/4/60 预算（取代 agent-harness §4.3/AH-05 的 3/2/30）；程序工具每场/每题不变量；4 个选做不写规格；已实现 8/4/60、A/P/U、网页 trust=untrusted、repeat 命令（含页面输入）与 web-search 4 次上限，526 测试与页面检查通过；哈希 `6e3c8c…` |
| 2026-11-26 | 数字人设定集 | — | v0.1 DRAFT | 新建：四类可编辑人设条目（WHO/VOICE/TABOO/LEARN，22 条，第一人称，逐条开关，默认全开）、生活素材池（30 条静态种子 + 日期轮换，只在自由对话注入）、教学纪律 D1-D5 硬编码（人设 YAML 拒绝 `discipline` 键）、MOMO 名字锁在 `core/persona.py` 常量；新增自由对话 teach 任务层、评分 `why` 措辞约束、probe 开场白三处连带改动；明确注入矩阵与合并顺序；不含 Web 面板、SQLite 表或 schema 变更；哈希 `884ff6…` |
| 2026-11-26 | 数字人设定集 | v0.1 DRAFT | 同版本更新（Slice 0 落地） | LIFE 改为只在单元开场；系统提示顺序补 TONE/MEMORY/DATA；评分只多一句反馈措辞；哈希 `2c8af5…` |
| 2026-11-26 | 数字人情绪状态 | — | v0.1 DRAFT | 新建：comfort [-1,1] / energy [0,1]、0.1 格、2 小时半衰期、回复前小模型更新（800ms 超时降级）、`(user_id, role)` 持久化、3×3 语气提示、`ready.emotion` / `session_ready.emotion` / 独立 `emotion` 事件；Slice 1 落地 schema v7；哈希 `4c812d…` |
| 2026-11-26 | 情绪表情与待机动作 | — | v0.1 DRAFT | 新建：`assets/avatar.vrm` 的 `happy`/`relaxed`/`sad`/`angry`/`neutral` 3×3 映射，`happy` ≤0.45、`sad` ≤0.35、`angry` ≤0.20；只动 `head`/`neck`（pitch ≤0.04、yaw ≤0.03）；说话压到 15%；Slice 1 落地并跑通 Playwright 页面验收；哈希 `137521…` |
| 2026-11-26 | 用户长期记忆 | — | v0.1 DRAFT | 新建：quote/preference/feeling 三档温度、14 天半衰期、沉底 <0.05、开场 top 3（≤300，前导 ≤360）、显式回忆（FTS5 trigram + 2 字回退，含沉底）、单元结束异步提炼 ≤5 条、`memory_runs` 审计、`user_id` 隔离；Slice 2 落地；655 测试通过；哈希 `36cc03…` |
| 2026-11-26 | 管理后台（react-admin） | — | v0.1 DRAFT | 新建：react-admin 替换手写 `/admin`，构建产物由同一 BFF 托管；信息架构 / 页面流程与状态 / 权限与读写矩阵三层；页面状态、导航规则、失败落点与 URL 契约；资源/接口/读写矩阵；内容资源只读，写只走任务提交；摄取/重建/整体评测统一 `task_id` + 轮询；新增 `admin_tasks`（schema v8）；构建产物不提交、ingest 停在 `awaiting_review`、热项动作 Phase 2；实现期补 `ADMIN_TASK_RUNNER`、`start/end` 过滤器、材料上传与目录扫描；哈希 `fac0ce…` |
| 2026-11-27 | 全部设计文档 | 同版本 | 同版本（脱敏） | 移除私有材料名与概念名，统一改为“首批材料/示例概念”等通用说法；同步 3 份文档 SHA；私有题库与 2026-11-25 验收数据移出版本库 |
