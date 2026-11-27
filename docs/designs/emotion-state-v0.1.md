# Design: 数字人情绪状态（Emotion State）

Date: 2026-11-26
Branch: feature-mood
Status: DRAFT v0.1
Related: `persona-settings-v0.1.md`、`user-memory-v0.1.md`、`free-talk`、`coach-session`、`agent-harness-v0.1.md`

## Problem Statement

MOMO 现在没有“今天状态”这回事：语气是固定的，用户说累、说开心，回复的劲头都一样。需要给她两个可变的数——舒不舒服、今天有没有劲——由模型每回合根据聊天微调；只影响语气，不影响教学规则；状态按用户身份/角色持久化，换对话不丢；每回合翻译成一句简短语气提示，交给上下文层，不写进人设。

## Goals

- 两个数：舒不舒服 [-1, 1]、今天有没有劲 [0, 1]，步长 0.1。
- 每回合由模型判断并微调；单回合每维常规最多动 0.3。
- 用户情绪波动特别大时，允许该回合超过 0.3，但最终值不越界。
- 没有情绪线索时，每 2 小时向中间态回一半。
- 按 `(user_id, role)` 存储；换对话、重启都不丢。
- 每回合生成一句语气提示，进上下文层；只影响语气，不影响教学规则。
- 不写进人设设定集，不占人设条目，不受人设开关控制。

## Non-Goals

- 不改 TTS 的音高/语速/音量；本期只影响措辞和句式。
- 不做情绪 UI、数值展示、手动重置。
- 不把情绪写进用户记忆；用户记忆的 `feeling` 是长期记住的用户感受，和 MOMO 的当前心情是两回事。
- 不做多账号体系；`user_id` / `role` 先留键，默认单用户。
- 不改评分、出题、知识检索的提示词。
- 不在人设 YAML 里加任何情绪字段。
- 不让情绪覆盖 TABOO 或教学纪律 D1-D5。

## 现状与边界

### 现在没有情绪层

代码里没有 `mood` / `emotion` 状态；分支名 `feature-mood` 是这次工作。现有语气完全由提示词和人设决定。

### 每回合的上下文层

| 面 | 代码 | 情绪提示怎么进 |
|---|---|---|
| 非 agent 自由对话 | `core/free_talk.py:85 build_free_talk_messages` | 新增 `tone_hint` 参数，拼成【当前语气】块 |
| agent 自由对话/教学/澄清 | `core/agent_loop.py:46 build_system_prompt` + `core/agent_steps.py:18 StepBrief` | `StepBrief.tone_hint`，`build_system_prompt` 插到人设之后 |
| 单元开场 | `bff/main.py:402 _send_session_ready` | 开场是确定性模板，本期不加情绪；第一句模型回复才用提示 |
| 评分/出题/抽取 | `core/scoring.py` / `core/question_generation.py` / `core/extraction.py` | 不进 |

### 和另外两层的关系

- **人设设定集**（`persona-settings-v0.1.md`）：MOMO 是谁、怎么说、不说什么。情绪不是人设，不改 `persona.yaml`，不加条目/开关。
- **用户记忆**（`user-memory-v0.1.md`）：用户说过什么、偏好、感受。情绪不是记忆，不写 `user_memories`，不参与 14 天半衰期。
- **学习进度**：掌握度、分数、复习。情绪不读写这些字段。

### 身份键

单用户应用没有账号表。情绪表先用 `(user_id, role)` 做主键：

- `USER_ID` 环境变量，默认 `owner`。
- `USER_ROLE` 环境变量，默认 `learner`。
- 换对话、换会话、重启进程都读同一行；以后接多账号时，一个用户一行。

## 两个数

| 数 | 范围 | 步长 | 中间态 | 含义 |
|---|---|---|---|---|
| 舒不舒服（comfort） | -1 到 1 | 0.1 | 0 | 负=不舒服，正=舒服 |
| 今天有没有劲（energy） | 0 到 1 | 0.1 | 0.5 | 低=没劲，高=有劲 |

- 存储为 REAL，但业务值只在 0.1 格上。
- 不向用户展示原始数字；原始数字只进出提示、日志和状态表。
- 中间态：comfort 0、energy 0.5。

## 状态转移

### 每回合更新

每回合在生成回复之前：

1. 读状态并按时间衰减，得到 `base_comfort` / `base_energy`。
2. 调一次小的情绪更新模型：输入当前状态、最近几轮对话、用户这句话；输出两个 delta 和一个 `intense` 标记。
3. 服务端应用：

```text
if not intense:
    dc = clamp(comfort_delta, -0.3, 0.3)
    de = clamp(energy_delta,  -0.3, 0.3)
else:
    dc = comfort_delta
    de = energy_delta

comfort = clamp(round_tenth(base_comfort + dc), -1, 1)
energy  = clamp(round_tenth(base_energy  + de),  0, 1)
```

4. 写回状态，`updated_at = now`。
5. 把新状态翻译成语气提示，进本回合提示词。
6. 生成回复。

关键点：

- **0.3 是常规上限，不是硬上限。** `intense=true` 时跳过 0.3 的夹取，只保留最终边界 [-1,1] / [0,1]。
- **先加 delta，再四舍五入，再夹边界。** 避免出现 1.04 这种值。
- **四舍五入用 half-up**，不用 Python 默认的 banker's rounding；-0.05 应该到 -0.1，不是 0.0。
- **更新失败或超时：不写状态，用衰减后的旧状态继续回复。** 不向用户报错。
- **没有情绪线索：两个 delta 给 0。** 状态只走衰减，不凭空波动。

### 为什么在回复前更新

用户说“我今天很难受”，这一句的回复就应该软下来，而不是下一轮才软。所以更新必须在回复生成之前，不能放到回复之后异步跑。

代价是多一次小模型调用。设计上用：

- 复用 `providers.scorer`（DeepSeek Flash），JSON 输出，快且便宜。
- 和检索并行跑；最迟等 800ms，超时就用衰减后的旧状态。
- 不把 delta 塞进主回复的 JSON 信封；主回复继续走原有文本路径，避免破坏 TTS 和 agent 工具循环。

如果真实使用中 800ms 仍然明显，开放问题里留了“折进主回复调用”和“接受一轮延迟”两个替代，不默认采用。

### 更新提示词（草案）

```text
你是 MOMO 的情绪状态更新器。只看用户这一轮和最近几轮聊天，
判断用户的话对 MOMO 两个数的影响。

当前状态（已按时间衰减）：
- 舒不舒服：{comfort}（-1 到 1）
- 今天有没有劲：{energy}（0 到 1）

用户这一轮说：
{user_text}

最近几轮（与回复同一历史窗口，最近 6 条）：
{recent_history}

规则：
- 只判断用户的情绪、语气、互动方式；不判断教学内容、题目难度、分数。
- 每个维度给一个 delta，常规范围 -0.3 到 0.3。
- 用户情绪波动特别大时，可以超过 0.3，但把 intense 设为 true。
- 没有明显情绪线索时，两个 delta 都给 0。
- 不要根据 assistant 的话判断 MOMO 自己的情绪；assistant 的话只作上下文。
- 只返回 JSON：
  {"comfort_delta":0.0,"energy_delta":0.0,"intense":false,"reason":"..."}
```

- `reason` 只进日志，不展示给用户。
- 解析复用 `core.scoring.extract_json_object()`；缺字段、非数字、非布尔一律按 0 / false 处理。
- `intense=true` 但两个 delta 都在 0.3 内时，按常规处理。
- 模型不能直接给最终值，只能给 delta；最终值和边界由服务端算。

### 衰减

没有提到情绪时，状态向中间态回落，每 2 小时距离减半：

```text
hours = max(0, (now - updated_at) / 1 小时)
factor = 0.5 ** (hours / 2)

comfort = 0   + (comfort - 0)   * factor
energy  = 0.5 + (energy  - 0.5) * factor
```

- 读的时候算，不写回；下一次成功更新时把衰减后的基线固化。
- 不需要定时任务，也不用后台扫描。
- 2 小时距离减半；4 小时剩 1/4；8 小时剩 1/16。
- 中间态是 comfort=0、energy=0.5；到了中间态就不再变。

例子：

```text
初始：comfort=0.8，energy=0.9，updated_at=10:00
12:00 读：comfort=0.4，energy=0.7
14:00 读：comfort=0.2，energy=0.6
18:00 读：comfort=0.05，energy=0.525
```

### 强波动

- `intense=true` 时允许单回合超过 0.3；服务端只保证最终值在 [-1,1] / [0,1]。
- 默认信任模型；不做额外 0.6 上限。如果实际使用中出现“一句话从 +1 跳到 -1”的过度反应，再加每回合最大摆幅。
- `intense` 事件打日志，便于回看。

## 存储

### 表

```sql
CREATE TABLE IF NOT EXISTS emotion_states (
  user_id TEXT NOT NULL,
  role TEXT NOT NULL DEFAULT 'learner',
  comfort REAL NOT NULL CHECK (comfort BETWEEN -1 AND 1),
  energy REAL NOT NULL CHECK (energy BETWEEN 0 AND 1),
  updated_at TEXT NOT NULL,
  PRIMARY KEY (user_id, role)
);
```

- 一行一个 `(user_id, role)`；单用户默认 `owner` / `learner`。
- 第一次读时 `INSERT OR IGNORE` 默认行：comfort=0、energy=0.5、updated_at=now。
- 换对话不换行；换角色才换行。
- 不建 FTS，不建 embedding；这是两个数，不需要全文索引。
- 不加 `conversation_id`、`session_id`；状态不属于某个对话。

### schema 版本

- v7 一次迁移建四张表：`emotion_states`、`user_memories`、`user_memories_fts`、`memory_runs`；不改旧表。
- 进度表、会话表、记忆表都不动。
- v7 是单向门：旧代码拒绝打开 `user_version > 6`；回退代码必须恢复 `data/app-v5.pre-v7.db`。

### 并发

- 每个 `(user_id, role)` 一把 `asyncio.Lock`；更新调用可以并行，写状态串行。
- 连续两轮快速到达时，后一轮读到的必须是前一轮写回的值；不能丢更新。
- 锁只包“读基线 → 应用 delta → 写回”，不包模型调用；模型调用仍在锁外并行。

## 语气提示

### 三档 × 三档

舒适度分档：

- 高：`comfort >= 0.4`
- 中：`-0.3 < comfort < 0.4`
- 低：`comfort <= -0.3`

有没有劲分档：

- 高：`energy >= 0.7`
- 中：`0.4 <= energy < 0.7`
- 低：`energy < 0.4`

| 舒服 | 有劲 | 一句提示 |
|---|---|---|
| 高 | 高 | 语气轻快一点，可以带一点调侃，但只调侃话题，不调侃用户。 |
| 高 | 中 | 语气放松，正常聊，不用刻意热络。 |
| 高 | 低 | 心情不差，但没什么劲；语气温和，别硬撑热情。 |
| 中 | 高 | 有精神，语气可以明快一点。 |
| 中 | 中 | 语气平稳自然。 |
| 中 | 低 | 有点累，语气放轻，别硬撑。 |
| 低 | 高 | 不太舒服但还有劲；语气直接一点，别赔笑。 |
| 低 | 中 | 不太舒服；语气收着点，不耍脾气。 |
| 低 | 低 | 又累又不舒服；语气低一点，简短，别硬撑也别冷脸。 |

### 注入方式

拼成一个短块，放在人设之后、任务之前：

```text
【当前语气】
{hint}
（只影响语气，不影响教学规则；和人设/底线冲突时以底线为准。）
```

- 提示是一句；括号是边界说明，不是第二句语气。
- 不把原始两个数写进提示词；原始数只进日志和状态表。
- 不是人设条目，不进 `persona.yaml`，不受人设开关控制。
- TONE 是软修饰：TABOO、D1-D5、任务约束（字数、评分、题目数、引用、答案揭示）都优先。
- “调侃”只针对话题，不针对用户；“别硬撑”不等于冷淡；“不耍脾气”不等于摆脸色。

### 合并顺序

```text
ROLE → PERSONA → TONE → MEMORY → TASK → CONTEXT → DISCIPLINE → DATA
```

- TONE 紧跟 PERSONA，作为本回合的语气修饰。
- LIFE 不进系统提示词，只在单元开场前导。
- MEMORY 是用户记忆（如果已落地），放在 TONE 之后。
- DISCIPLINE 永远最后；TONE 不能覆盖它。
- 开场模板不走系统提示词，本期不加 TONE；第一句模型回复开始生效。
- 三份设计（人设/记忆/情绪）合并时，以本节的顺序为准。

## 每回合流程

### 非 agent 自由对话

```text
用户文本 → 读状态/衰减 → 并行：检索 + 情绪更新
→ 应用 delta（或超时用旧状态）→ 生成 tone_hint
→ build_free_talk_messages(..., tone_hint=...)
→ 生成回复 → TTS
```

### agent 自由对话 / 教学 / 澄清

```text
用户文本 → 读状态/衰减 → 情绪更新（800ms 上限）
→ 应用 delta → 生成 tone_hint
→ build_*_brief(..., tone_hint=...)
→ build_system_prompt 插【当前语气】→ AgentLoop
→ 回复
```

### 单元开场

开场是确定性模板（`StartedSession.intro`），本期不加情绪；开场后的第一句模型回复使用当前状态。

### 失败与降级

- 情绪更新超时/报错：用衰减后的旧状态；不写 delta；日志记 `emotion_update_failed`。
- 状态表读写失败：本回合不加 TONE；回复照常。
- 模型输出非法 JSON：按 0 delta 处理；不阻塞。
- 情绪层永远不能导致回复失败。

## 事件

| 事件 | 时机 | 负载 |
|---|---|---|
| `ready` | WebSocket 连接 | `emotion: {comfort, energy, tone}` |
| `session_ready` | 单元开始/恢复 | `emotion` |
| `emotion` | 自由对话/教学/澄清更新后、回复前 | `{type, comfort, energy, tone}` |

- 答题/评分/结算不回写、也不发 `emotion`。
- `reply` / `teach_reply` / `score` / `session_result` 负载保持不变。
- 前端 `setMood(comfort, energy)` 接收三个入口；没有数据时默认 `{0, 0.5}`。

## 配置与开关

| 配置 | 默认 | 作用 |
|---|---|---|
| `USER_ID` | `owner` | 情绪/记忆的用户键 |
| `USER_ROLE` | `learner` | 情绪的角色键 |
| `EMOTION_ENABLED` | `on` | 关掉：不调更新器、不发 `emotion`、`ready.emotion` 返回中间态、前端 neutral |
| `MEMORY_ENABLED` | `on` | Slice 2 使用；Slice 1 期间没有代码读取 |

## 和用户记忆、人设、进度的区别

| 层 | 内容 | 时间尺度 | 影响 |
|---|---|---|---|
| 情绪状态 | MOMO 当前舒不舒服、有没有劲 | 每 2 小时向中间态减半 | 语气 |
| 用户记忆 | 用户原话、偏好、感受 | 14 天半衰期 | 内容背景 |
| 人设 | MOMO 的来历、说话方式、禁忌 | 静态 | 语气基线 |
| 学习进度 | 掌握度、复习、分数、误解 | 天/周 | 教学 |

- 情绪不是记忆：`feeling` 记忆是“用户曾经说过自己什么感受”；情绪是“MOMO 现在什么状态”。
- 情绪不是人设：人设是“她是谁”；情绪是“她今天怎么样”。
- 情绪不碰进度：不写分数、不读掌握度、不改题目。
- 情绪不写回记忆：单元结束的记忆提炼不读情绪表；情绪更新也不写 `user_memories`。

## 决策记录

| ID | 决策 | 理由 |
|---|---|---|
| EM-01 | 两个数：comfort [-1,1]、energy [0,1]，步长 0.1，中间态 0 / 0.5 | 按用户给定区间；0.1 格让状态稳定、可解释 |
| EM-02 | 每回合回复前更新；小 JSON 调用；和检索并行；800ms 超时；复用 scorer | 当前这句就要软/轻，不能等下一轮；超时降级不阻塞 |
| EM-03 | 模型只给 delta；服务端常规夹 ±0.3，`intense=true` 时跳过；最终夹边界；half-up 到 0.1 | 上限和边界必须由程序保证，不能只靠提示词 |
| EM-04 | 无情绪线索时 2 小时半衰期向中间态回落；读时计算，不写回 | 符合“每两小时距离减半”；不需要定时任务 |
| EM-05 | `(user_id, role)` 主键；默认 owner/learner；跨对话/重启持久 | 换对话不丢状态；为未来多账号留键 |
| EM-06 | 3×3 分档，固定 9 句语气提示；一句一档 | 确定、可测、不额外调模型；边界值可回归 |
| EM-07 | TONE 是软修饰；TABOO、D1-D5、任务约束优先 | 用户明确要求只影响语气，不影响教学规则 |
| EM-08 | 不进 `persona.yaml`，不做条目/开关 | 情绪是运行时状态，不是人设内容 |
| EM-09 | 不改 TTS 音高/语速；只改措辞和句式 | 本期最小；参数化 TTS 是另一刀 |
| EM-10 | 更新失败/超时用衰减后的旧状态，不报错 | 情绪层不能拖垮回复 |
| EM-11 | 每个 `(user_id, role)` 一把锁；锁只包状态读写 | 连续回合不丢更新；模型调用仍在锁外 |
| EM-12 | 不做情绪历史表；只打日志 | 两个数足够；历史表是另一层需求 |

## 开放问题

1. **更新调用延迟**：800ms 是拍的。如果真实语音回合里仍然明显，两个替代是“把 delta 折进主回复的同一次调用”或“接受一轮延迟、回复后再更新”。当前选“回复前小调用”。
2. **分档阈值**：0.4 / -0.3 / 0.7 / 0.4 是初版；真实用一周后按体感调。
3. **强波动上限**：现在信任 `intense`，只夹最终边界。如果出现一句话从 +1 到 -1 的过度反应，再加每回合最大摆幅（例如 0.6）。
4. **身份键**：`owner` / `learner` 是默认值。要不要在设置里暴露 `USER_ID` / `USER_ROLE`，还是写死单用户？
5. **TTS 参数**：本期只改措辞。如果“有劲/没劲”也应该影响语速或音高，需要给 TTS 端口加参数，另一刀。
6. **开场**：单元开场模板不加情绪。要不要让开场也按当前状态换一句问候？
7. **手动重置/查看**：没有 UI。要不要加一个只读调试接口或“重置到今天中间态”的命令？
8. **多数字人**：现在是 MOMO 一个。如果以后有多个人设，`emotion_states` 需要加 `persona_id`。
9. **更新模型看什么**：现在看当前状态 + 最近几轮 + 用户这句话；assistant 的话只作上下文。要不要把上一轮 assistant 回复也作为情绪线索？当前不。
10. **情绪 vs 教学挫败**：用户因为题目难而烦躁，算情绪波动还是教学反馈？当前算情绪（用户表达的是感受），但不改教学规则。
11. **四舍五入**：统一 half-up；不用 banker's rounding。实现时用 `floor(x*10+0.5)/10` 或 Decimal。
12. **状态和对话**：状态不属于任何 `conversation_id` / `session_id`；这是“换对话不丢”的实现方式。确认这是你要的粒度。

## 验收

### 自动化

- 衰减：comfort 0.8 在 0/2/4/8 小时后为 0.8/0.4/0.2/0.05；energy 0.9 为 0.9/0.7/0.6/0.525；中间态不变。
- 夹取：非 intense 的 delta 0.5 → 0.3；intense 的 0.5 → 0.5；最终 comfort 不越 [-1,1]，energy 不越 [0,1]。
- 取整：所有写回值都是 0.1 的倍数；-0.05 → -0.1（half-up）。
- 持久化：同 `(user_id, role)` 跨对话/跨连接读到同一行；首次读自动建默认行。
- 提示：3×3 全覆盖；边界值（0.4/-0.3/0.7/0.4）落到预期档；提示是一句；不含原始数字。
- 注入：非 agent 的 `build_free_talk_messages` 有【当前语气】；agent 的 `StepBrief.tone_hint` 进 `build_system_prompt`；评分/出题/抽取提示词不变。
- 隔离：`persona.yaml` 没有情绪字段；`user_memories` 没有情绪写入。
- 更新：合法 JSON、缺字段、非数字、非布尔、超时、异常分别按预期降级。
- 并发：两轮快速到达，后一轮读到前一轮写回的值；锁不包模型调用。
- fake 模式：零 delta；测试可注入脚本化 updater。

### 真实模型验收

1. 用户说“今天好累，脑子转不动” → comfort/energy 下降；回复变轻、别硬撑，但不冷脸。
2. 用户说“太好了，我终于懂了” → comfort/energy 上升；回复轻快，允许一点调侃，但不抢戏。
3. 用户说“随便吧，不想学了” → 不舒服/低劲；回复不哄、不训，给一个很小的下一步。
4. 换一个对话继续聊 → 状态不回到中间态。
5. 隔 4 小时再聊 → 状态明显靠近中间态。
6. 用户情绪极端（大哭/大怒）→ 单回合允许超过 0.3，最终值仍在边界内。
7. 情绪提示生效时，TABOO 和教学纪律不被破坏：不讽刺用户、不卖萌、不抬分、不多出题、不直接给答案。
8. TTS 听感：轻快/低劲只体现在措辞，不出现音高/语速的突兀变化（本期不改 TTS 参数）。

## Next Steps

Slice 1 已落地：

1. `core/db.py`：schema v7，`emotion_states` 与记忆四表一次建好。
2. `core/emotion.py`：衰减、夹取、取整、3×3 提示、更新提示词/解析。
3. `core/store.py`：情绪行读取（首次建默认行）与写回。
4. `bff/emotion.py`：scorer 调用、800ms 超时、失败降级、每 `(user_id, role)` 锁。
5. `bff/main.py`：三个事件入口；自由对话/教学/澄清回复前更新；答题不更新。
6. `web/app.js`：mood → 表情、头部动作、说话压制；`EMOTION_ENABLED=off` 保持 neutral。

剩余：真实模型/真实语音下量一次回合延迟；`intense` 是否过度反应按真实使用回看。
