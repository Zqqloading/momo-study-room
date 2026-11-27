# 真实 provider 烟雾（2026-11-23）

- 服务：`127.0.0.1:8766`，默认 `PROVIDER_MODE=auto`；`asr/llm/tts/scorer` 全部 `real`
- 数据：`data/app.db`
- 方式：Python WebSocket 客户端直连；语音场用 Breeze 合成一段回答再送 MiMo ASR

## 文本一场

- session：`db9a12ea4663490d8a82f21bb644ad2a`
- 结果：`completed`，session_score 48，mastery `agent-loop: 2`
- DB 回放：5 行题目，分数与答案与事件一致

| 题 | 类型 | 得分 | 评分耗时 | 反馈结束耗时 | 反馈音频块 |
|---|---|---|---|---|---|
| 1 | recall | 40 | 1063ms | 7628ms | 175 |
| 2 | recall | 40 | 993ms | 6760ms | 358 |
| 3 | discriminate | 100 | 16ms | 26ms | 0 |
| 4 | discriminate | 40 | 6ms | 4629ms | 196 |
| 5 | apply | 20 | 1780ms | 10683ms | 406 |

- 辨析题答对：16ms 出分、无反馈音频；答错：4.6s 读完解析。
- 开放题评分 1.0–1.8s；反馈语音生成长度 4.6–10.7s（参考答案也在朗读）。

## 语音一场

- session：`d988bf0cc0934e8684c421e478918c24`
- 结果：`partial`（第一题后 `finish`），session_score 90，`input_mode=voice`
- Breeze 合成回答：4539ms，100608 bytes，`audio/mpeg`
- MiMo ASR 转写：`观察当前情况，再做出决策，最后执行行动，循环直到目标完成。`（confidence NULL）
- DeepSeek 评分：90 分，1799ms
- 反馈语音结束：8803ms
- 无 error / warning

## 结论

- 7.1 通过：真实 ASR / Scorer / TTS / LLM 全链路可用，无错误与降级。
- 文本场用通用答案回答 recall-3/4，低分是预期，不作为评分质量依据；评分质量看 7.2。
- 观察：Breeze 流式块很碎（单条反馈 175–406 块）；客户端已按 120ms 合批，后续可考虑服务端合并。
- `asr_confidence` 落库为 NULL，符合规格。
