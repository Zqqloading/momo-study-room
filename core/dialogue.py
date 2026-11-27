"""d0 的对话逻辑：一个只做"逼你用大白话讲"的演示教练。

d0 不接知识库、不写数据库；这里只负责拼消息和管理历史窗口。
真正的 Tutor / Planner 在 v0 才落地。
"""

from __future__ import annotations

from typing import Sequence

from .ports import ChatMessage

# 规格里"What Makes This Cool"的第一条：它拒绝说黑话，只问"用你自己的话说一遍"。
D0_SYSTEM_PROMPT = """你是用户的学习搭子，陪他学 agent 理论。

规则：
0. 用户直接提问时，先用一句话正面回答，再追问一句让他用自己的话复述；不要只打招呼或反问开场。
1. 用户讲解一个概念时，先说他讲对的部分，再指出一处含糊或错误，最后追问一个问题。
2. 不说黑话。必须用术语时，紧跟一句人话解释。
3. 不要问"你懂了吗"，只问"用你自己的话说一遍"。
4. 一次回复不超过 120 字，因为下面会被念出来。
5. 用户说"不知道"时，用不超过 60 字给一个定义加一个生活类比，然后请他复述。
6. 用中文回答。
7. 不要假设之前聊过什么；只看当前消息和对话历史。
"""

# 半双工语音下，历史太长既拖延迟又没必要；保留最近 6 轮。
MAX_HISTORY_MESSAGES = 12


def build_messages(
    history: Sequence[ChatMessage],
    user_text: str,
) -> list[ChatMessage]:
    """把历史、本次输入和系统提示拼成发给 LLM 的消息序列。"""
    previous = list(history)[-MAX_HISTORY_MESSAGES:]
    return [
        ChatMessage(role="system", content=D0_SYSTEM_PROMPT),
        *previous,
        ChatMessage(role="user", content=user_text),
    ]
