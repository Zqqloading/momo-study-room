# 进度驱动的「今天学什么」v0.1

- 状态：REVIEW（2026-11-25，待冻结）
- 日期：2026-11-25
- 依据：`docs/designs/learning-unit-v0.1.md`、`docs/designs/learning-companion-digital-human-v2.0.md`（FROZEN）、`openspec/changes/archive/2026-11-25-learning-unit-mastery/`、`openspec/specs/coach-session/spec.md`、`openspec/specs/learning-unit/spec.md`
- 范围：点「开始今天的学习」时按学习进度选主题，并用第一句话说出提议；跨对话保持判断
- 非范围：概念地图 UI、自动抽主题、mastery 公式、出题/评分/语音链路重写、跨对话聊天记忆

## 0. 验收标准（用户原话）

> 在页面上故意答错一个主题，再点一次开始今天的学习，它的第一句话应该是提议复习那个故意打错的主题，开一个新的对话，这个判断应该还要存在。

拆成可验证的步骤：

1. 在页面上完成一场会话，故意把主题 X 的题答错。
2. 结束本场，回到初始界面。
3. 点「新建对话」（自由对话换一个 conversation）。
4. 点「开始今天的学习」。
5. 第一句展示/朗读的文本包含 X，并说明“上次没答好/先复习/先补上”。
6. 第一道题属于 X。
7. 重启服务后重复，判断仍在（进度在 SQLite，不在内存）。

## 1. 结论摘要

1. **开始学习不再用 `Planner.next_concept` 单一路径**。新增一个进度选题器：最近失手 → 掌握度最低 → 无信号时稳定随机。
2. **被选中的主题作为本场主概念**（`role=new`），mastery 会更新；不采用“整场 review-only”，否则复习不涨 mastery，薄弱主题会被永远反复提议。
3. **开场白由程序按事实拼**，不用模型生成；`session_ready` 增加 `intro` 字段，先朗读开场白，再读第一题。
4. **长期记忆不新增存储**：`concepts`（当前状态）+ `sessions` / `session_questions`（历史得分）就是记忆；按需计算，不改 schema。对话表只存自由聊天，和进度表没有 `conversation_id` 关联，所以新建对话不会丢判断。
5. **主题清单继续用 `concepts.yaml`**，不新增管理 UI；`id` + `prerequisites` 已经足够作为未来概念地图的底座。
6. **提议与开始共用同一个选题函数**；无信号档用“按日期稳定的伪随机”，保证同一天面板提议和实际开始一致。

## 2. 现状与问题（已核对代码）

| 事实 | 位置 | 影响 |
|---|---|---|
| 主按钮直接发 `session_start`，不经过面板提议 | `web/app.js:1053` | 用户看到的“开始学习”和 KB 面板的提议是两条路 |
| `Coach.start()` 用 `Planner.next_concept` 选主概念 | `core/coach.py:346`、`core/planner.py:31` | 只按“难度低 + 最久没见”，不看最近得分 |
| `Planner` 的排序键是 `(difficulty, last_seen or "", id)` | `core/planner.py:48` | 从未学过的概念 `last_seen=""` 排最前；同级只剩一个可解锁概念时会一直选它 |
| 复习概念只取“最逾期 1 个” | `core/coach.py:150` | 与“最近答得不好”不是同一个信号 |
| `Coach.propose()` 是只读预览，面板在用 | `core/coach.py:176`、`web/kb.js` | 提议和开始各自算，按钮不读提议 |
| 现在没有开场白 | `bff/main.py:365` `_send_session_ready()` | `session_ready` 直接推第一题并播放题干 |
| 进度是全局 SQLite | `data/app-v5.db`（`.env` 的 `DB_PATH`），schema v6 | `concepts` / `sessions` / `session_questions` 没有 `conversation_id` |
| 对话是另一组表 | `core/db.py:143` `conversations`、`conversation_messages` | 新建/切换对话只动这两张表，不改进度 |
| 自由对话已经注入进度摘要 | `bff/main.py:668` `_progress_summary()`、`core/free_talk.py` `format_progress()` | “换对话内容”后，聊天里仍知道进度 |
| 现有“薄弱”口径是 `mastery <= 1` 且 `last_seen` 非空 | `core/progress.py:153` | 抓不到“历史 mastery 不低、但最近一次答错”的情况 |
| 复习到期在失败后设为“次日” | `core/coach.py:831` `_due_updates()` | 当天故意答错，`review_due_at` 是明天；验收不能依赖到期字段 |
| 结算时才写 `sessions` 行 | `core/store.py:1023` `finalize()` | 未结算但已作答的题在 `session_questions` 里有分、没有 `sessions` 行；薄弱信号要看 `agent_sessions` 兜底 |

### 2.1 为什么现在“永远是同一个主题”

`Planner` 只在 active + 前置满足的概念里选；排序先看难度，再看 `last_seen`。如果当前可解锁的同难度概念只有一个（或其它概念被前置锁住），每次都会选它。最近答得好不好、是否刚答错过，完全不参与。KB 面板的提议虽然展示“复习”，但主按钮不经过它。

### 2.2 “换对话不能丢”现在已经成立的部分

- 学习进度：`concepts`、`sessions`、`session_questions` 是全局表，新建对话不会清空。
- 自由对话：`_progress_summary()` 每次从 `concepts` 读当前状态注入系统提示，所以换对话后仍能说“你学到哪了”。
- 不成立的部分：**开场白不存在**，所以换不换对话都听不到提议；选题也不读最近得分。这两点才是本次要补的。

## 3. 术语

| 术语 | 含义 | 避免 |
|---|---|---|
| 最近失手 | 某主题最近一次有评分的作答里，任一题 < 60，或该次均分 < 80 | 与“薄弱（mastery<=1）”混用 |
| 薄弱主题 | 用户口语里的“最近答得不好的主题”；本设计默认指“最近失手” | 当成新的 mastery 档位 |
| 回炉 | 对有历史、但最近失手的主题，用 `role=new` 的题重新学一遍 | 与复习档 `role=review` 混用 |
| 掌握度最低 | active 概念里 `mastery` 最小的主题；并列时看久未学 | 掌握率、百分比 |
| 无信号 | 所有 active 概念都没有掌握度差异（都是 0 且从未学过） | 没有主题、空知识库 |
| 主题清单 | `concepts.yaml` 里的概念条目 | 课程表、章节 |

## 4. 推荐选题算法

```text
today   = clock.today()
states  = store.concept_states()                 # 全局，与 conversation 无关
active  = [s for s in states if s.status == "active"]

# 1) 最近失手：每个主题取“最近一次有评分的作答”
assess  = store.latest_concept_assessments([s.id for s in active])
weak    = [a for a in assess if a.min_score < 60 or a.avg_score < 80]
if weak:
    pick = max(weak, key=(a.date, -a.avg_score, -a.min_score, a.concept_id))
    reason = "recent_miss"

# 2) 掌握度最低
else:
    candidates = [s for s in active if s.id in concepts]
    if not candidates:
        return None                               # 没有可出的主题
    lowest = min(s.mastery for s in candidates)
    pool   = [s for s in candidates if s.mastery == lowest]

    # 3) 无信号：整池都没学过 → 稳定随机
    if all(s.last_seen is None for s in pool):
        pick = stable_random(pool, seed=f"{today}:{sorted(ids)}")
        reason = "no_signal"
    else:
        pick = min(pool, key=(s.last_seen or "", s.id))
        reason = "lowest_mastery"
```

### 4.1 最近失手的取数口径

- **按主题取最近一次**，不是按“最近一场会话”取。昨天 X 答错、今天学了 Y，X 仍然是最近失手。
- 数据源：`session_questions`（`score`、`concept_id`、`question_role`）join `agent_sessions`（`date`）；有 `sessions` 行时优先用 `sessions.date`，没有时用 `agent_sessions.date`。
  - 这样**未结算但已作答**的题也算：用户答错一题后直接再点开始，旧会话被 abandon，分数仍在 `session_questions`，仍能命中。
- 同一场里该主题的所有已评分题（`new` + `review`）一起算 `avg` 和 `min`；`score IS NULL` 不计入。
- 如果该主题最近一场全是未评分题，跳过这一场，取上一场有评分的。
- **不要求** `sessions.status = completed`；`partial` 和 abandoned 也看，因为“答错”本身就是证据。
- 最近失手只看“最近一次有评分的作答”，一次好作答就会清掉；历史表现交给 mastery 公式，不在这里重复累积。

### 4.2 掌握度最低的取数口径

- 只看 `status=active` 的概念；`known` / `skipped` / `proposed` / `orphaned` 不参与。
- `mastery` 最小；并列时 `last_seen` 早的优先（`None` 视为最早）。
- 如果整池都从未学过（`last_seen IS NULL`），走稳定随机。
- 从未学过的概念要不要进“掌握度最低”池：**推荐进**。理由：0 就是最低；这样新主题会自然进入；否则“永远复习已学过的”会另一种形式地卡住。见 Q2（已确认：包含）。

### 4.3 无信号时的稳定随机

- 只在“最低掌握度池里全是未学过”时使用。
- 种子 = `sha256(f"{today}:{sorted(concept_ids)}")`，取模选一个；同一天、同一主题池结果一致。
- 这样 `GET /api/kb/unit/proposal` 和随后 `session_start` 重算不会漂移；第二天池子或日期变了，结果自然变化。
- 不改变“题目生成/轮换不依赖随机数”的既有约束：随机只用于**主题的平局**，不用于题目。

### 4.4 选中主题后怎么出题

推荐：**选中主题作为本场主概念**，沿用 `build_session_plan(main_concept=选中主题, review_concept=最逾期到期概念)`：

| 情况 | 本场构成 | mastery 是否更新 |
|---|---|---|
| 选中的是薄弱/最低掌握度主题，且它也是到期复习 | 3 道 `new` + 2 道 `review`（同概念） | 是（`new` 部分） |
| 选中的是薄弱/最低掌握度主题，另有其他到期复习 | 3 道 `new`（选中主题）+ 2 道 `review`（另一个） | 是（选中主题） |
| 选中的主题没有到期复习 | 5 道 `new`（选中主题） | 是 |
| 没有任何 active 概念 | 不可用，提示补材料/确认概念 | — |

- **不推荐 review-only**：现有规则 review-only 不更新 mastery（`_mastery_updates` 只看 `role=new`），薄弱的 X 会一直是“掌握度最低”，下次还会被选中，形成死循环。
- **不推荐把 X 只放复习档**：第 1 题会是主概念，和开场白“先复习 X”不一致，验收也会失败。
- 结果卡里 X 的角色仍是“主学”；如果 UI 需要区分，可加 `focus_reason=recent_miss`，显示“主学（回炉）”，但系统角色不变。

## 5. 开场白

### 5.1 文案（程序拼，不用模型）

| 档位 | 文案 | 备注 |
|---|---|---|
| 最近失手 | 「上次「X」这道题你没答好（最低 40 分），今天先把它补上。」 | 有均分低于 80 但没有单题 <60 时，改说「上次「X」平均 70 分，没到 80，今天先巩固一下。」 |
| 掌握度最低 | 「现在掌握度最低的是「X」（初识），今天先学它。」 | 从未学过时说「今天从「X」开始。」 |
| 无信号 | 「今天从「X」开始。」 | 随机选中的主题 |

- 控制在 40 字以内，避免 TTS 延迟和听感冗长。
- 只陈述事实，不编造“你忘了”“你薄弱”这类判断。

### 5.2 协议与播放

- `session_ready` 增加加法字段 `intro`（string）与 `focus`（可选：`{concept_id, name, reason}`）。
- BFF 顺序：发 `session_ready` → 推 `intro` 的 TTS 音频 → 推第一题题干 TTS 音频 → 后续不变。
- 前端：在题目卡片上方显示 `intro`，并把它作为第一句朗读；不写入自由对话的 chatlog。
- TTS 失败：`intro` 文本仍然显示，第一题音频照常；不阻塞会话。
- `session_resume` 不重播 `intro`（用户已经听过；重播会打断恢复）。
- **不等待确认**：点开始就是快捷开始，开场白说完直接第一题。想先看提议的用户走 KB 面板；面板里的“开始这个单元”也走同一条 `session_start`，开场白一致。

## 6. 长期记忆的存储位置

### 6.1 推荐：复用现有 SQLite，不新增表/列

| 记忆 | 存储 | 用途 |
|---|---|---|
| 当前掌握度、状态、上次学习、复习到期 | `concepts` 表 | 选题的“掌握度最低”档 |
| 每次作答的分数、题型、角色 | `session_questions` 表 | 选题的“最近失手”档 |
| 会话日期、状态、本场得分 | `sessions` + `agent_sessions` | 取最近一次作答的日期；兜底未结算会话 |
| 自由对话内容 | `conversations` + `conversation_messages` | 与学习进度解耦；新建对话不影响进度 |

- 不新增 `memory` / `learning_events` 表：`session_questions` 已经是逐题事实，重复存一份会漂移，还要迁移和历史回填。
- 不在 `concepts` 加 `last_score` / `weak_since`：派生状态容易和逐题事实不一致；当前数据量（本地单用户）读时计算足够。
- DB 仍是 `data/app-v5.db`（`.env` 的 `DB_PATH`），schema v6 不变。
- 如果以后要升级概念地图，再单独加图结构；不要为了未发生的需求现在加表（符合项目“简约至上”）。

### 6.2 备选与代价

| 方案 | 优点 | 代价 | 结论 |
|---|---|---|---|
| 新建 `learning_events` 追加表 | 查询快、可审计、方便做概念地图分析 | 迁移 + 回填；与 `session_questions` 双写，易漂移 | 暂不做 |
| `concepts` 加 `last_score` / `weak_since` | 读快、实现短 | 派生状态；未结算/abandoned 会话难同步 | 暂不做 |
| Markdown / GBrain 记忆文件 | 跨工具可读 | 不参与事务；评分链路要额外写；一致性差 | 不做 |
| 现有 SQLite 读模型 | 单一事实源、零迁移、跨对话天然成立 | 每次读要 join；数据量大时可能要索引 | **推荐** |

### 6.3 “换对话内容也不能丢”的边界

- **学习进度**：全局，换对话不丢；本次新增回归测试证明。
- **自由对话的聊天内容**：每个 conversation 独立；新建对话从空历史开始，只带进度摘要，不带上一个对话的逐句聊天。验收只要求“判断还在”，不要求“聊天记录还在”。
- 如果以后要“换对话也记得聊过什么”，那是另一套记忆摘要/检索，不在本次范围。

## 7. 主题清单怎么维护

- **继续用 `concepts.yaml`**：它已经是概念内容的唯一真相源（`core/concepts.py` 的模块注释明确写了）；`concepts` 表只存运行时状态。
- 新增主题：在 `concepts.yaml` 加一条（`id`、`name`、`plain_def`、`difficulty`、`prerequisites`、`source`），启动/同步后生成 `proposed` 状态，再走现有确认流程变成 `active`。
- 不新增管理 UI、不新增 DB 表；主题清单只有 20 条，YAML 是最简维护方式。
- 升级到概念地图时，`id` 和 `prerequisites` 可以直接作为节点和边；不需要现在改结构。

## 8. 提议、开始与面板的一致性

- 新增一个共用函数（建议 `core/selection.py` 或 `Coach._select_topic`），`Coach.propose()` 和 `Coach.start()` 都调用它。
- KB 面板的 `GET /api/kb/unit/proposal` 显示的 `main` 就是开始后的主概念；`review` 仍是最逾期到期概念。
- 无信号档的稳定随机保证同一天面板与开始一致；跨天/状态变化时以 `start` 为准，不引入 plan token。
- `progress.stats.weak` 是否改成同一口径：**推荐改**，让面板“薄弱”与 agent 的“最近失手”一致；否则用户会看到“面板薄弱 0，agent 说你薄弱”。见 Q5（已确认：统一）。

## 9. 规格与测试

### 9.1 规格改动

- `openspec/specs/coach-session/spec.md`（或新 change 的 spec）增加：
  - 启动时按“最近失手 → 掌握度最低 → 无信号稳定随机”选主概念。
  - 选中主题作为主概念（`role=new`）；5 题配比不变。
  - `session_ready` 带 `intro`；第一题属于选中主题；开场白先于第一题音频。
  - 同一天答错、`review_due_at` 为次日时仍能命中。
  - 新建对话不改变选择。
- `openspec/changes/learning-unit-mastery/specs/learning-unit/spec.md` 增加：提议 `main.reason` 的三种档位；`review` 仍取最逾期。
- 现有“选题 MUST NOT 依赖随机数”只约束题目轮换；主题平局的稳定伪随机要在规格里写明例外。

### 9.2 测试

| 层 | 用例 |
|---|---|
| Store | `latest_concept_assessments`：completed / partial / abandoned；`new` + `review` 都算；未评分跳过；按主题取最近一次 |
| Selector | 最近失手优先；多个失手按日期/均分；无失手选最低 mastery；全 0 走稳定随机；同一天两次结果一致；空 active 返回 None |
| Coach | `propose()` 与 `start()` 选中同一主题；intro 文案含主题名与档位；`build_session_plan` 仍是 3+2 或 5 题 |
| WS | `session_ready.intro` 存在；第一题 `concept_id` 等于选中主题；新建 conversation 后再次 start 仍选中 X |
| 浏览器 | 页面上答错 X → 结束 → 新建对话 → 开始 → 断言第一句含 X、第一题属于 X |
| 回归 | `pytest -q` 全绿；现有 `test_proposal` / `test_planner` / `test_progress` 按新口径更新 |

### 9.3 验收映射

| 验收步骤 | 覆盖 |
|---|---|
| 故意答错 X | 浏览器/WS 测试写入低分 |
| 结束本场 | `finish` 结算，`review_due_at` 次日 |
| 新建对话 | `conversation_new` 不改 `concepts` |
| 再点开始 | `session_start` 选 X |
| 第一句含 X | `session_ready.intro` |
| 第一题属于 X | `question.concept_id` |
| 重启后仍在 | 新进程读同一 `data/app-v5.db` |

## 10. 已确认与待确认

### 已确认（2026-11-25）

| # | 决定 |
|---|---|
| Q1 | 最近失手时，X 作为本场主概念（`role=new`），沿用 3 新 + 2 复习；mastery 更新 |
| Q2 | “掌握度最低”包含从未学过的 0；全 0 平局按天稳定随机 |
| Q3 | 最近失手 = 最近一次有评分作答里任一题 <60，或该次均分 <80；按主题取最近一次 |
| Q4 | 开场白说完直接第一题，不等用户确认 |
| Q5 | 面板“薄弱”与 agent 统一口径：最近失手或 `mastery<=1` |
| Q6 | 长期记忆复用现有 SQLite 读模型；不新增表/列，schema 仍为 v6 |

### 默认假设（未反对即采用）

| # | 假设 | 理由 |
|---|---|---|
| Q7 | 无信号随机按天稳定（`sha256(today + ids)`） | 现有设计要求提议与开始一致；真随机会让面板与开始漂移 |
| Q8 | 主题清单继续 `concepts.yaml` | 用户明确“先挑一个最简单的方法”；YAML 已是唯一真相源 |
| A1 | 结果卡对回炉主题显示“主学（回炉）” | 系统角色仍是 `new`；UI 区分“回炉”不改变 mastery 规则 |
| A2 | `session_resume` 不重播开场白 | 用户已听过；重播会打断恢复 |
| A3 | 开场白用“复习/补上”的口语，不改变 `role=review` 语义 | 用户验收原话是“提议复习”；系统仍按 `role=new` 计分和更新 mastery |

## 11. 风险与边界

- **同日验收**：`review_due_at` 是次日，不能靠它；必须用 `session_questions` 的分数。测试要显式覆盖。
- **未结算会话**：答错后直接再点开始，旧会话会被 abandon；信号必须能从 `agent_sessions` + `session_questions` 取到。
- **单题误判**：任一题 <60 就标记薄弱，可能对“粗心错一题”过于敏感；但一次好作答就会清掉，且符合用户“答错就要复习”的直觉。
- **mastery 5 的概念**：如果所有 active 都是 5，仍会选最低（5）继续练；如果不想练，用户应把概念标成 `known`。不在本次加规则。
- **旧 spec 冲突**：`learning-unit-v0.1.md` 的 D9 说主按钮保持“无提议快捷开始”；本设计**取代**该条：主按钮现在会带开场白和进度选题。
- **归档依赖**：`learning-unit-mastery` 已实现但未归档；建议先归档并同步 spec，再开新 change，避免两个 change 同时改 `coach-session` / `learning-unit`。
- **性能**：每次提议多一次按概念的最近作答查询；本地单用户数据量小，先不加索引；若变慢再加 `session_questions(concept_id, session_id)` 索引。
