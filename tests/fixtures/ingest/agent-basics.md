---
source_url: https://example.com/agent-basics
tags: [agent, basics]
---

# Agent 基础

Agent 是能感知环境并自主采取行动的系统。它通常包含感知、决策和行动三个部分。

## 工具调用

工具调用让模型调用外部工具拿到结果再继续想。模型通过工具描述决定何时调用哪个函数。

```python
# 这不是标题
def call_tool(name):
    return name
```

## 上下文窗口

上下文窗口是模型一次能看到的 token 上限。窗口越大，能放的材料越多。
