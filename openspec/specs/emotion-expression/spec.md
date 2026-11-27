# emotion-expression Specification

## Purpose

把情绪状态映射到当前 VRM 模型的待机表情，并加轻微头部动作；不做大动作，不改 TTS 参数。前端只消费两个数和一句语气提示，不展示原始数值。

## Requirements

### Requirement: 模型与表情

系统 MUST 继续使用 `assets/avatar.vrm`（VRM 0.x，CC0）。待机表情 MUST 只使用 `happy` / `relaxed` / `sad` / `angry` / `neutral`；`Surprised` / `Extra` MUST NOT 用于待机。强度 MUST 满足：`happy` ≤0.45、`sad` ≤0.35、`angry` ≤0.20。

#### Scenario: 模型自带表情

- **WHEN** 加载 `assets/avatar.vrm`
- **THEN** `expressionManager` 暴露 `angry`、`relaxed`、`happy`、`sad`、`Surprised`、`Extra`、`neutral`

#### Scenario: 大笑不用于待机

- **WHEN** comfort/energy 都是高
- **THEN** 使用 `happy` 0.40，不使用 1.0 的大笑

### Requirement: 3×3 映射

前端 MUST 按 comfort/energy 的分档映射：

| 舒服 | 有劲 | 表情 | 强度 |
|---|---|---|---|
| 高 | 高 | `happy` | 0.40 |
| 高 | 中 | `relaxed` | 0.50 |
| 高 | 低 | `relaxed` | 0.30 |
| 中 | 高 | `relaxed` | 0.40 |
| 中 | 中 | `neutral` | 0 |
| 中 | 低 | `sad` | 0.15 |
| 低 | 高 | `angry` | 0.12 |
| 低 | 中 | `sad` | 0.20 |
| 低 | 低 | `sad` | 0.30 |

表情值 MUST 用约 0.25-0.5 秒交叉淡化到目标，不跳变。

#### Scenario: 高舒服高有劲

- **WHEN** comfort=0.8、energy=0.9
- **THEN** `happy` 目标 0.40

#### Scenario: 低舒服低有劲

- **WHEN** comfort=-0.8、energy=0.2
- **THEN** `sad` 目标 0.30

### Requirement: 轻微头部动作

系统 MUST 只动 `head` / `neck` 归一化骨骼；pitch MUST ≤0.04 rad、yaw MUST ≤0.03 rad；MUST NOT 动肩膀、脊柱、手臂。低劲时 MUST 放慢并略低头；高劲时 MAY 小幅点头；低舒服时 MUST 不左右大幅晃。基准旋转 MUST 在加载后记录，MUST NOT 覆盖 VRM rest pose。

#### Scenario: 低劲

- **WHEN** energy=0.2
- **THEN** 头部动作更慢、pitch 略向下，幅度仍在上限内

#### Scenario: 不抢戏

- **WHEN** 任意 mood
- **THEN** 头部 pitch/yaw 始终 ≤0.04 / 0.03 rad

### Requirement: 说话与眨眼

说话时情绪表情 MUST 压到目标的 15% 或 0.1，避免和 `aa` 口型打架；说完 MUST 淡回目标。`blink` MUST 保持现有随机眨眼；`happy` + `blink` 出现闭眼过度时 MAY 在眨眼帧把 `happy` 压到 0.25。

#### Scenario: 说话

- **WHEN** TTS 正在播放
- **THEN** 情绪表情值 ≤0.15，口型正常

#### Scenario: 眨眼

- **WHEN** 随机眨眼触发
- **THEN** 眨眼仍可见，不出现长时间闭眼

### Requirement: 默认与降级

没有情绪数据、情绪事件缺失或 VRM 未加载时 MUST 保持 `neutral` / 占位形象，不报错。`EMOTION_ENABLED=off` 时 MUST 保持 neutral。

#### Scenario: 后端未接

- **WHEN** 前端没有收到任何 emotion 数据
- **THEN** 表情保持 neutral，头部只做极轻默认摆动

#### Scenario: VRM 加载失败

- **WHEN** `assets/avatar.vrm` 不可用
- **THEN** 使用占位形象，不调用 expressionManager
