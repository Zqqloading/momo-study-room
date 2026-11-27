# emotion-state Specification

## Purpose

定义 MOMO 的两个情绪数：舒不舒服 [-1,1]、今天有没有劲 [0,1]；逐回合由模型微调，按 2 小时半衰期回落；按用户/角色持久化；只影响语气，不影响教学规则。

## Requirements

### Requirement: 两个数与衰减

系统 MUST 维护 `comfort` [-1,1] 与 `energy` [0,1]，业务值只在 0.1 格上；中间态 MUST 为 comfort=0、energy=0.5。没有情绪线索时 MUST 每 2 小时向中间态距离减半：`factor = 0.5 ** (hours/2)`；衰减 MUST 在读取时计算，不写回、不需要定时任务。

#### Scenario: 2 小时减半

- **WHEN** comfort=0.8 且 2 小时没有新输入
- **THEN** 读取时 comfort=0.4；4 小时后为 0.2

#### Scenario: 中间态不再变

- **WHEN** comfort=0、energy=0.5
- **THEN** 衰减后仍是 0 / 0.5

### Requirement: 更新时机与边界

情绪更新 MUST 发生在自由对话、教学、澄清的回复生成之前；MUST NOT 在答题/评分/结算回合触发。更新器 MUST 只返回 `comfort_delta` / `energy_delta` / `intense`；服务端 MUST 在非 intense 时把每维 delta 夹到 ±0.3，intense 时跳过该夹取；最终 comfort MUST 夹到 [-1,1]，energy 夹到 [0,1]；四舍五入 MUST 为 half-up 到 0.1。更新失败或超时 MUST 使用衰减后的旧状态，不写状态、不向用户报错。

#### Scenario: 常规微调

- **WHEN** 更新器返回 comfort_delta=0.5、intense=false
- **THEN** 服务端按 0.3 应用

#### Scenario: 强波动

- **WHEN** 更新器返回 comfort_delta=-0.8、intense=true，当前 comfort=0.4
- **THEN** 最终 comfort=-0.4，不越 -1

#### Scenario: 超时降级

- **WHEN** 更新器 800ms 未返回
- **THEN** 本回合使用衰减后的旧状态继续回复

### Requirement: 持久化与身份

状态 MUST 存在 `emotion_states`，主键 `(user_id, role)`；`USER_ID` 默认 `owner`，`USER_ROLE` 默认 `learner`；换对话、换会话、重启进程 MUST 不丢失。首次读取 MUST `INSERT OR IGNORE` 默认行 comfort=0、energy=0.5、`updated_at=now`。每个 `(user_id, role)` MUST 有独立锁，锁只包状态读写，不包模型调用。

#### Scenario: 换对话不丢

- **WHEN** 用户新建对话后继续聊天
- **THEN** 读到同一 `(user_id, role)` 的情绪行

#### Scenario: 连续回合不丢更新

- **WHEN** 两个回合快速到达
- **THEN** 后一回合读到前一回合写回的值

### Requirement: 事件

WebSocket `ready` MUST 带 `emotion: {comfort, energy, tone}`；`session_ready` MUST 带 `emotion`；自由对话/教学/澄清更新后、回复前 MUST 推送独立 `emotion` 事件 `{type, comfort, energy, tone}`。答题/评分/结算 MUST NOT 推送 `emotion`。`reply` / `teach_reply` / `score` / `session_result` 负载 MUST 保持不变。

#### Scenario: 自由对话更新

- **WHEN** 用户说“今天好累”
- **THEN** 回复前收到 `emotion` 事件，comfort/energy 下降

#### Scenario: 答题不更新

- **WHEN** 用户提交一道题
- **THEN** 不调用情绪更新器，不推送 `emotion`

### Requirement: 开关

`EMOTION_ENABLED=off` 时 MUST 不调用更新器、不推送 `emotion`、`ready.emotion` 返回中间态；前端 MUST 保持 neutral；其余会话行为不变。更新器 MUST 复用 `providers.scorer` 的 JSON 调用；fake 模式 MUST 返回零 delta。

#### Scenario: 关闭情绪

- **WHEN** `EMOTION_ENABLED=off`
- **THEN** 回复照常，但没有 `emotion` 事件，待机表情保持 neutral
