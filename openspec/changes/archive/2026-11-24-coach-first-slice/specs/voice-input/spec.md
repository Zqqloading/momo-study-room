# Spec Delta

## Purpose

定义点击说话的语音输入契约：从浏览器端判停、整段识别到一步提交评分，并规定可疑转写与混合句何时暂停确认、识别失败如何降级。

## ADDED Requirements

### Requirement: 点击说话与浏览器端判停

语音输入 MUST 由用户点击“开始说话”触发，由浏览器能量 VAD 判定结束：1.5 秒静音或用户点击“结束作答”才提交；短停 MUST NOT 切断录音。一次录音 MUST 对应一条 `audio` 消息，MUST NOT 产生部分转写。

#### Scenario: 静音判停
- **WHEN** 用户说话后停止 1.5 秒
- **THEN** 客户端提交一条 audio 消息

#### Scenario: 短停不切断
- **WHEN** 用户在句中停顿 0.5 秒后继续
- **THEN** 录音不提交，继续采集

#### Scenario: 手动结束
- **WHEN** 用户点击“结束作答”
- **THEN** 立即提交当前录音

### Requirement: 一步提交直接评分

默认识别成功后 MUST 直接进入评分，不要求用户确认：服务端收到 `audio` 后做 ASR，推送 `transcript`（`needs_confirmation=false`），随即评分并推送 `score`。`audio`、`transcript`、`answer`、`score` MUST 携带同一 `turn_id`。

#### Scenario: 普通语音作答
- **WHEN** 用户完整说出一段可识别答案
- **THEN** 收到 transcript 后无需确认即收到 score

### Requirement: 可疑转写暂停确认

空文本、少于 4 字、纯语气词或明显重复乱码 MUST 视为可疑，暂停评分并把转写交给用户确认或编辑。白名单 `不知道 / 不懂 / 知道了 / 明白了 / 会了 / 不会` MUST NOT 触发暂停。

#### Scenario: 可疑转写
- **WHEN** ASR 返回空文本或少于 4 字的非白名单内容
- **THEN** 推送 needs_confirmation=true 且 reason=suspicious 的 transcript

#### Scenario: 白名单不暂停
- **WHEN** ASR 返回“不知道”
- **THEN** 不暂停，按不知道规则得 0 分并进入下一题

### Requirement: 混合句暂停

转写包含疑问词且不是纯确认时 MUST 视为混合句，暂停评分并推送 reason=mixed 的 transcript，由用户选择整句评分或修改后再评。第一片 MUST NOT 回答其中的提问。

#### Scenario: 答案中夹带提问
- **WHEN** 转写为带疑问词的混合句
- **THEN** 暂停评分，推送 needs_confirmation=true 且 reason=mixed

### Requirement: ASR 失败降级到文本

ASR 超时或返回 5xx 时 MUST 提示用户改用文字输入，并把该题 `input_mode` 记为 text；会话 MUST NOT 中断。

#### Scenario: ASR 超时
- **WHEN** ASR 调用超时
- **THEN** 推送 error(stage=asr)，用户可改用文本继续作答

### Requirement: 不伪造识别置信度

MiMo 不返回置信度时 `asr_confidence` MUST 保持 NULL，MUST NOT 用 0.0 或其他数值冒充；transcript 事件中的 confidence 字段 MAY 为 null。

#### Scenario: 无置信度
- **WHEN** ASR 结果没有 confidence
- **THEN** transcript 的 confidence 为 null，落库的 asr_confidence 为 NULL
