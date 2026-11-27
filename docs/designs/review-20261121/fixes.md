# 修复记录（Round 1 → Round 2）

评审输入：`round1.md`（13 阻塞 / 23 次要）
修复日期：2026-11-21
状态说明：FIXED = 已改文档；DEFERRED = 已登记到待定区，不在本轮定；PARTIAL = 改了规则但仍有未验证假设。

| id | 严重度 | 状态 | 改了什么 / 为什么 |
|---|---|---|---|
| R1-01 | BLOCKING | FIXED | 五题配比按 0/1/2 道复习分别定义，任何情况都恰好 5 题；复习块改为前 4 分钟，时间账对齐到 20 分钟。 |
| R1-02 | BLOCKING | FIXED | 未作答不再按 0 计；新增 `status=completed|partial|unscored`，`session_questions.score` 可空；补分规则与验收卡一致。重试一次标为假设。 |
| R1-03 | BLOCKING | FIXED | 新增 `concept_session_score`（只算该概念自己的题），mastery 与 80 分验收都改用它；复习题/诊断/综合场明确排除。 |
| R1-04 | BLOCKING | FIXED | 补 `review_due_at` 状态机：入队次日到期；<60 次日、60-79 三天、>=80 出队；14 天循环；错过只标逾期不改日期。 |
| R1-05 | BLOCKING | FIXED | 明确 YAML 只拥有内容、SQLite 只拥有运行时状态；确认页写 SQLite status，不回写 YAML；id 消失→orphaned，回来→恢复；每日写入集补全 misconceptions 和 review_due_at。 |
| R1-06 | BLOCKING | FIXED | v0 题库改为 10 道摸底 + 每概念 5 道；v0 工时从 4-6 调到 8-12 小时。 |
| R1-07 | BLOCKING | FIXED | 定义“完成一次会话”（daily/synthesis/review 且至少 3 题已评分；partial 少于此不算；diagnostic 不算）和“完成一个概念”（至少一次 daily 的 concept_session_score >=80）。 |
| R1-08 | BLOCKING | FIXED | 使用场景明确标为假设（桌面麦克风）；手机/公共空间时语音降级为打字；ASR 测试录音改用实际使用的麦克风，不再用手机。 |
| R1-09 | BLOCKING | FIXED | 误解触发统一为第三次出现（times_seen>=3）；补 candidate→active 提升、resolved→active 重开、相关题定义。 |
| R1-10 | BLOCKING | FIXED | 补 2.5 秒逐跳预算（ASR 0.6 + LLM 0.8 + TTS 0.8 + 抖动 0.3）；定义测量点为松开按钮到第一帧音频；要求流式，不支持则目标改 4 秒并登记。 |
| R1-11 | BLOCKING | PARTIAL | 工时改为 d0 8-12、v0 8-12、v1 12-16、v2 12-16，并写明三个月只能覆盖 d0+v0+部分 v1；每周实际投入仍待确认（Open Question 3 / 待定区）。 |
| R1-12 | BLOCKING | FIXED | 状态行与 P4 改为“语音和 3D 形象已确认；口型精度待定”；口型精度进待定区，幅度驱动标为假设。 |
| R1-13 | BLOCKING | FIXED | 第 7 次综合场改为 20 分钟内 5 题 + 5 分钟跨概念讲解；讲解记 kind=review、写 session_concepts；新增综合场屏幕。 |
| R1-14 | MINOR | FIXED | 诊断 10 题明确不受五题规则限制；active 不足 10 个按实际数量；复习队列派生过滤 diagnostic。 |
| R1-15 | MINOR | FIXED | 拆分“错题（<60）”“待巩固（60-79）”“复习队列（concept_session_score<80）”；“最近一次”统一为概念最近一次 daily 分数；档案分两栏。 |
| R1-16 | MINOR | FIXED | 拆分 `asr_text`（原始）与 `explained_text`（纠错后可编辑）；错题详情两版都显示；置信度阈值设为 0.6（假设）；随时可改，低置信度才提示。 |
| R1-17 | MINOR | FIXED | 新增解析失败路径（格式不支持/损坏/空/编码错误→跳过并提示；整批 0 份→初始化暂停），与低产质量门槛分开。 |
| R1-18 | MINOR | FIXED | PDF 统一到 v2，删掉 v1 的 PDF。 |
| R1-19 | MINOR | FIXED | 正文删掉硬编码的 20 节点和材料占位数字，统一引用待定区；v2 负责扩到目标节点数。 |
| R1-20 | MINOR | FIXED | 工时改为“已包含 20% 缓冲”，并写明三个月覆盖范围。 |
| R1-21 | MINOR | FIXED | ASR 测试集改为音频目录 + manifest（路径/文本/术语/设备/环境）；录音设备改为实际使用麦克风；定义术语准确率为逐字匹配、同义替换不算对；2.5 秒单独测。 |
| R1-22 | MINOR | FIXED | “每第 7 次会话”改为“每第 7 次完成的日常会话（约 9 天）”，明确计数口径。 |
| R1-23 | MINOR | FIXED | 预生成改为 Windows 计划任务 + `question_cache` 表；无缓存时同步生成，超 30 秒退回旧题。 |
| R1-24 | MINOR | FIXED | question_bank/session_questions 增加 `answer_key`；辨析题确定性判分，不走 LLM。 |
| R1-25 | MINOR | FIXED | 统一出处字段：YAML 增加 source.url；抽概念字段加 source_url；materials 存 source_url/tags；v0 写 url+摘录；HTML 元数据规则写明。 |
| R1-26 | MINOR | FIXED | material_chunks 增加 material_version；旧版本块保留，检索只用最新版本。 |
| R1-27 | MINOR | FIXED | 删除“降级为子概念”（无层级字段），只保留同级合并。 |
| R1-28 | MINOR | PARTIAL | 明确 Ingestion/Scorer 通过 BFF 内部接口调用模型，core 不直接联网；embedding 模型登记到待定区，不再假装 FTS5 可独立成立。 |
| R1-29 | MINOR | FIXED | Distribution 明确 materials/data/*.vrm/concepts.yaml 默认 gitignore；私有备份可选包含；演示数据在 data/demo/。 |
| R1-30 | MINOR | FIXED | 权限边界写进 Constraints；演示目录固定项目内 data/demo/；清空只删该目录；定义“档案”=DB+YAML+materials。 |
| R1-31 | MINOR | FIXED | 删掉悬空的“v0 最小集”和“v3”；改为排期门槛与“后续独立实验”。 |
| R1-32 | MINOR | FIXED | “20 分钟硬约束”改为“设计目标，计时器建议不强制中断”，P2 同步。 |
| R1-33 | MINOR | FIXED | “四者都联网”改为“当前按云端 API 设计，托管方式见待定区”；四个 API 行加“托管方式”。 |
| R1-34 | MINOR | FIXED | “讲给别人听”落到每周综合场的 5 分钟讲解录音；删除无法验证的“被追问两轮”表述。 |
| R1-35 | MINOR | FIXED | 写明增量流程从 v0 起手工跑，v2 只是自动化。 |
| R1-36 | MINOR | FIXED | 抽查时机定为每次生成后约 10 分钟，算内容时间；跳过用旧题，不阻塞。 |

## 未修 / 延后

没有未处理的阻塞项。以下属于“登记但不在本轮定”的待定项，不是遗漏：

- 材料数量、节点数量：待定区占位，等材料实际进来再定。
- MiMo ASR / mimo-2.6 / breezeblue / DeepSeek Flash 的接口、鉴权、音频格式、流式与托管方式：待定区。
- embedding 模型与召回方式：待定区 + Open Question 5。
- 每周实际建设时间：待定区 + Open Question 3。
- 口型精度：待定区（当前假设幅度驱动）。
- 评分校准（20 条人工对照、75% 一致率）：Open Question 1。
- 2.5 秒与 80% 在接口实测前只是目标，不是承诺。
