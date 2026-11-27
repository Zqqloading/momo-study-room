"""一次 WebSocket 连接内的会话状态。

d0 不写数据库；会话只保留对话历史。v0 起 sessions 表落 SQLite。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from core.dialogue import MAX_HISTORY_MESSAGES
from core.ports import ChatMessage


@dataclass
class Session:
    history: list[ChatMessage] = field(default_factory=list)

    def add_user(self, text: str) -> None:
        self._append(ChatMessage(role="user", content=text))

    def add_assistant(self, text: str) -> None:
        self._append(ChatMessage(role="assistant", content=text))

    def _append(self, message: ChatMessage) -> None:
        self.history.append(message)
        del self.history[:-MAX_HISTORY_MESSAGES]
