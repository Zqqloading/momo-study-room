# Design: 情绪表情与待机头部动作（Emotion Expression）

Date: 2026-11-26
Branch: feature-mood
Status: DRAFT v0.1
Related: `emotion-state-v0.1.md`、`persona-settings-v0.1.md`、`web/app.js`

## Problem Statement

情绪状态已经有设计（`comfort` / `energy` 两个数），但还没有落到数字人的脸上。现在待机只有呼吸式眨眼和口型，表情固定。需要把两个数映射到当前 VRM 模型自带的表情，并加一点轻微头部动作；不做大动作，不改教学规则，不改 TTS 参数。

## 模型确认

`assets/avatar.vrm`：

| 项 | 值 |
|---|---|
| 格式 | VRM 0.x（`extensions.VRM`，UniGLTF-1.24） |
| title | Sendagaya Shino |
| author | 空 |
| license | **CC0** |
| 允许用户 | Everyone |
| 商用 | Allow |
| humanoid 骨骼 | 有 `head`、`neck`、`chest`、`upperChest` |
| 表情组 | 15 个 blend shape group |

**结论：不用换模型。** 模型自带 5 个情绪表情（`angry` / `relaxed` / `happy` / `sad` / `Surprised`），满足“4 个以上”。

## 表情清单

three-vrm 实际暴露的 `expressionManager` 名字：

| 名字 | VRM 来源 | 用途 |
|---|---|---|
| `neutral` | Neutral | 平静待机 |
| `aa` / `ih` / `ou` / `ee` / `oh` | A / I / U / E / O | 口型，给 TTS 用 |
| `blink` / `blinkLeft` / `blinkRight` | Blink / Blink_L / Blink_R | 眨眼 |
| `angry` | Angry | 皱眉、嘴角下压 |
| `relaxed` | Fun | 温和微笑，眼睛睁开 |
| `happy` | Joy | 大笑；低强度是微笑 |
| `sad` | Sorrow | 撇嘴、眉毛下垂 |
| `Surprised` | 自定义组（`presetName: unknown`） | 睁大眼睛、张嘴 |
| `Extra` | 自定义组（`presetName: unknown`） | “><”闭眼，像害羞/用力眯眼 |

渲染观察（本地逐表情截图确认）：

- `relaxed` 是最自然的待机微笑，适合“舒服/正常”。
- `happy` 1.0 是张嘴大笑、眼睛闭上；0.35-0.45 才是待机微笑。
- `sad` 0.2 是轻微撇嘴，0.4 很明显；待机建议 0.15-0.35。
- `angry` 0.15-0.3 只是轻微皱眉；待机建议 ≤0.2，避免“耍脾气”。
- `Surprised` 是瞬态表情，不适合当待机底色。
- `Extra` 是闭眼“><”，适合瞬态，不适合待机。

## 情绪到表情的映射

沿用 `emotion-state-v0.1.md` 的分档：

- 舒服：高 `comfort >= 0.4`；中 `-0.3 < comfort < 0.4`；低 `comfort <= -0.3`。
- 有劲：高 `energy >= 0.7`；中 `0.4 <= energy < 0.7`；低 `energy < 0.4`。

| 舒服 | 有劲 | 待机表情 | 目标强度 | 头部 |
|---|---|---|---|---|
| 高 | 高 | `happy` | 0.40 | 轻微抬头 + 小幅点头 |
| 高 | 中 | `relaxed` | 0.50 | 轻微侧头 |
| 高 | 低 | `relaxed` | 0.30 | 头略低，动作放慢 |
| 中 | 高 | `relaxed` | 0.40 | 小幅点头 |
| 中 | 中 | `neutral` | 0 | 几乎不动 |
| 中 | 低 | `sad` | 0.15 | 头低 0.02 rad，放慢 |
| 低 | 高 | `angry` | 0.12 | 头略低，不点头 |
| 低 | 中 | `sad` | 0.20 | 头低 0.025 rad |
| 低 | 低 | `sad` | 0.30 | 头低 0.04 rad，最慢 |

约束：

- `happy` 不超过 0.45，避免变成大笑/闭眼。
- `angry` 不超过 0.20，避免变成凶。
- `sad` 不超过 0.35，避免变成哭丧。
- `Surprised` / `Extra` 不做待机；只在后续做瞬态反应时用。
- 表情强度用 0.5-1 秒向目标过渡，不跳变。

## 头部动作

模型有 `head` / `neck` 归一化骨骼，支持轻微动作。只动头部和脖子，不动肩膀、脊柱、手臂。

实现建议：

```js
// 加载后记录基准，避免覆盖 VRM 的 rest pose
headBase = head.rotation.clone();
neckBase = neck.rotation.clone();

// 每帧
const t = clock.elapsedTime;
const speed = 0.35 + energy * 0.35;              // 0.35-0.70
const lowEnergy = Math.max(0, 0.5 - energy);     // 0-0.5
const lowComfort = comfort < -0.3 ? 0.02 : 0;

head.rotation.x = headBase.x + lowEnergy * 0.08 + lowComfort
                + Math.sin(t * speed) * 0.015;
head.rotation.y = headBase.y + Math.sin(t * speed * 0.6 + 1.2) * 0.025;
neck.rotation.x = neckBase.x + (lowEnergy * 0.04 + lowComfort * 0.5)
                + Math.sin(t * speed + 0.5) * 0.008;
```

幅度上限：

- 头部 pitch ±0.04 rad（约 2.3°）。
- 头部 yaw ±0.03 rad（约 1.7°）。
- 脖子 pitch 为头部的一半。
- 不做快速摇头、点头或歪头杀。

低劲：速度慢、头略低；高劲：速度略快、幅度仍小；低舒服：头略低，不左右晃。

## 说话与眨眼的冲突

### 说话时的口型

`aa` 由 TTS 音量驱动。情绪表情（`happy` / `sad` 等）也带嘴部 morph，直接叠加会和口型打架。处理：

- 说话时把情绪表情压到目标的 **15%**，或直接淡到 0.1。
- 说完后再淡回目标强度。
- `aa` 和 `blink` 保持现有逻辑，不被情绪层覆盖。

### 眨眼

- `blink` 继续每 2.5-5.5 秒随机触发。
- `happy` 控制在 0.45 以内；如果 `happy` + `blink` 出现闭眼过度，在眨眼帧把 `happy` 临时压到 0.25。
- `Surprised` / `Extra` 不进待机，避免和眨眼叠加。

### 表情切换

维护每个情绪表情的当前值，向目标 lerp：

```js
const EMOTIONS = ["happy", "relaxed", "sad", "angry"]; // 待机四个
const targets = new Map(EMOTIONS.map((n) => [n, 0]));
targets.set(currentEmotion, currentIntensity);

for (const name of EMOTIONS) {
  const now = expressionValues.get(name) ?? 0;
  const target = targets.get(name) ?? 0;
  const next = now + (target - now) * Math.min(1, delta * 4);
  expressionValues.set(name, next);
  vrm.expressionManager.setValue(name, next);
}
```

- 切换表情时旧表情淡出、新表情淡入，不跳。
- `neutral` 就是所有情绪表情为 0。
- 不要每帧把未选中的表情直接设为 0；用 lerp，避免闪。

## 数据流

情绪后端已随 Slice 1 落地。前端只依赖两个数，不依赖后端内部结构：

- `ready` 事件带当前状态：`emotion: { comfort, energy, tone }`。
- `session_ready` 带 `emotion`。
- 每回合更新后发独立 `emotion` 事件：`{ type: "emotion", comfort, energy, tone }`，先于 `reply` / `teach_reply`。
- `EMOTION_ENABLED=off` 时 `ready.emotion` 为中间态、没有 `emotion` 事件，前端保持 neutral。
- 前端 `setMood(comfort, energy)` 更新目标；没有事件时默认 `{0, 0.5}` → `neutral`。

前端接线点：

- `web/app.js` 的 WebSocket `message` 处理：识别 `emotion`，调用 `setMood`。
- `ready` 分支：读取 `message.emotion`。
- `buildAvatar`：记录 `head` / `neck` 基准旋转。
- `animate`：算目标表情 + 头部偏移；调 `expressionManager.setValue`。
- `placeholder` 分支：不接表情层，保持现状。

## 非目标

- 不换模型；当前 CC0 模型已有 5 个情绪表情。
- 不做大动作（不摇头、不耸肩、不挥手）。
- 不用 `Surprised` / `Extra` 做待机底色。
- 不改 TTS 音高/语速/音量。
- 不改评分、出题、检索、教学纪律。
- 本文档只定前端表情层和数据契约；情绪状态与更新器见 `emotion-state-v0.1.md`。

## 决策记录

| ID | 决策 | 理由 |
|---|---|---|
| EE-01 | 继续用 `assets/avatar.vrm`（CC0，Sendagaya Shino） | 已有 `angry`/`relaxed`/`happy`/`sad`/`Surprised` 5 个情绪表情，满足 4+ |
| EE-02 | 3×3 映射到 `happy`/`relaxed`/`sad`/`angry`/`neutral` | 和情绪方案的分档一一对应，可测 |
| EE-03 | `happy` ≤0.45、`angry` ≤0.20、`sad` ≤0.35 | 1.0 的大笑/凶/哭不适合待机 |
| EE-04 | `Surprised` / `Extra` 只做瞬态 | 睁眼张嘴/闭眼“><”不适合长时间待机 |
| EE-05 | 只动 `head` / `neck`，pitch ≤0.04 rad、yaw ≤0.03 rad | 用户要求轻微动作；大动作会抢戏 |
| EE-06 | 说话时情绪表情压到 15% | 避免和 `aa` 口型打架 |
| EE-07 | 表情用 lerp 交叉淡化，约 0.25-0.5 秒 | 避免切换时闪脸 |
| EE-08 | 数据契约：`ready.emotion`、`session_ready.emotion` + 每回合 `emotion` 事件 | 前端只需要两个数 + 一句 tone；不依赖后端内部结构 |
| EE-09 | 没有情绪数据时默认 neutral | 情绪后端未落地时也能正常待机 |

## 开放问题

1. `happy` 0.40 是否还是太像大笑？真实用一周后再调。
2. `sad` 在“中/低”用 0.15 会不会看不出来？可能要 0.2。
3. 低舒服 + 高劲用 `angry` 0.12 是否会被读成“生气”？也可以改成 `neutral` + 头略低。
4. `Surprised` / `Extra` 要不要做“用户说了意外/好笑的话”的瞬态反应？
5. 头部动作频率 0.35-0.7 是否合适；是否需要更慢的呼吸式摆动？
6. 眨眼 + `happy` 的叠加是否需要额外压低；本地截图只测了单表情。
7. 情绪后端的事件用独立 `emotion` 事件，还是挂在 `reply` / `score` / `teach_reply` 上？
8. 移动端/低配机器上每帧 setValue 4 个表情是否有性能问题；当前只有 4 个，预计可忽略。

## 验收

### 自动化 / 页面

- 加载后 `expressionManager.expressions` 包含 `angry`、`relaxed`、`happy`、`sad`、`Surprised`、`Extra`。
- `setMood(0.8, 0.9)` → `happy` 目标 0.40；`setMood(-0.8, 0.2)` → `sad` 目标 0.30；`setMood(-0.8, 0.9)` → `angry` 目标 0.12。
- 切换 mood 时旧表情值下降、新表情值上升，不出现同时为 1 的叠加。
- 说话时情绪表情值 ≤0.15；说完回到目标。
- 头部 pitch/yaw 始终在 ±0.04 / ±0.03 rad 内。
- 没有 `emotion` 事件时保持 `neutral`，不报错。

### 人工

- 高舒服 + 高劲：轻微微笑，不是大笑；头部有小幅点头。
- 高舒服 + 低劲：温和微笑，头略低，动作慢。
- 低舒服 + 低劲：轻微撇嘴，头低，不哭丧、不甩脸。
- 低舒服 + 高劲：轻微皱眉，不凶、不耍脾气。
- 说话时口型正常，不被表情嘴部 morph 扭曲。
- 眨眼仍自然；没有闭眼过度。
- 整体动作幅度小，不影响左侧气泡和镜头构图。

## Next Steps

Slice 1 已落地：

1. `web/app.js`：`mood` / `setMood` / 3×3 表情 lerp / `head`/`neck` 基准与轻微动作。
2. WebSocket 处理 `ready.emotion`、`session_ready.emotion` 与独立 `emotion` 事件。
3. 说话时情绪表情压到目标的 15%；`happy` + 眨眼时临时压到 0.25。
4. `tests/browser/check_emotion_face.mjs` 验收 mood → 表情、说话压制、头部幅度。

剩余：真实用一周后按体感调 `happy` 0.40、`sad` 0.15 与头部速度。
