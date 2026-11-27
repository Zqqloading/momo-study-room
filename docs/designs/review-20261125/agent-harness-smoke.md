# Agent Harness 真实冒烟（2026-11-25）

## 1.8 适配器探针

| provider | model | latency_ms | tool_calls | ok |
|---|---|---|---|---|
| DeepSeek | deepseek-chat | 1879 | search_materials | True |
| MiMo | mimo-v2.6-flash | 2625 | search_materials | True |

## 3.8 判断力冒烟

通过：10/10（门槛 8）

| # | 期望 | 实际工具 | web | ok | 输入 |
|---|---|---|---|---|---|
| 1 | local | search_materials, read_concept | 0 | True | 材料里的 Agent Loop 是什么？ |
| 2 | local | search_materials, read_concept | 0 | True | 工具调用和 function calling 有什么区别？ |
| 3 | web | search_web, search_web | 2 | True | 今天 agent 领域有什么最新发布？ |
| 4 | web | search_web, search_web | 2 | True | 联网查一下 2026 年 agent 框架对比 |
| 5 | none | — | 0 | True | 不用查资料，直接说说 agent 和 workflow 的区别。 |
| 6 | none | — | 0 | True | 你好，今天有点累。 |
| 7 | local | read_concept, search_materials | 0 | True | 解释一下 ReAct 这个说法。 |
| 8 | web | search_web, search_materials | 1 | True | 2026 年 11 月有什么新的 AI 模型发布？ |
| 9 | none | — | 0 | True | 先说结论，不要查：Agent Loop 为什么需要停止条件？ |
| 10 | local | read_concept, search_materials | 0 | True | 换个说法再查：智能体循环和 agent loop 是一回事吗？ |

工具失败与预算耗尽由 `tests/test_agent_loop.py` 的脚本化用例覆盖；
本冒烟只验证真实模型在正常工具面下的判断。

## 观察与修正

- 10/10 通过；但 case 2/7 在已有本地来源时仍自称“材料里没有直接讲到”，case 9 把前缀重复了两次。
- 已改：提示词不再要求模型自加前缀，统一由服务端按本轮来源添加；`_with_grounding_note` 折叠重复前缀。
- 未重跑 10 条以避免额外真实调用；该修正由 `tests/test_agent_loop.py` 的前缀用例覆盖。
