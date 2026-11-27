"""与外部世界之间的唯一接口面。

这里定义外部能力（ASR / LLM / TTS / 评分 / 嵌入 / 搜索）的 Protocol 和数据结构。
BFF 用真实适配器实现它们，测试用假实现。core/ 只依赖本模块，不依赖 httpx。

对应冻结规格：`docs/designs/learning-companion-digital-human.md` 的架构图与
评分契约（v0 必须实现）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, AsyncIterator, Literal, Protocol, Sequence

if TYPE_CHECKING:
    from .agent_tools import ToolSpec

Role = Literal["system", "user", "assistant"]


@dataclass(frozen=True, slots=True)
class ChatMessage:
    role: Role
    content: str


AgentRole = Literal["system", "user", "assistant", "tool"]


@dataclass(frozen=True, slots=True)
class AgentToolCall:
    """模型请求的一次工具调用；arguments 保留原始 JSON 字符串。"""

    id: str
    name: str
    arguments: str = "{}"


@dataclass(frozen=True, slots=True)
class AgentMessage:
    """agent 循环里的消息；tool 消息必须带 tool_call_id。"""

    role: AgentRole
    content: str = ""
    tool_calls: tuple[AgentToolCall, ...] = ()
    tool_call_id: str = ""


@dataclass(frozen=True, slots=True)
class AgentResponse:
    content: str
    tool_calls: tuple[AgentToolCall, ...] = ()
    finish_reason: str | None = None


class AgentClientError(RuntimeError):
    """模型调用失败；由循环转成兜底回复，不冒到 WS。"""


class AgentClient(Protocol):
    """一次模型调用的端口；适配器只负责请求与 tool_calls 解析。"""

    name: str

    async def complete(
        self,
        messages: Sequence[AgentMessage],
        *,
        tools: Sequence["ToolSpec"] = (),
        tool_choice: str | None = "auto",
        timeout_seconds: float = 15.0,
    ) -> AgentResponse: ...


@dataclass(frozen=True, slots=True)
class ASRRequest:
    """一次按住说话的完整录音。

    半双工：松手时录音已经结束，所以是整段提交，不是流式。
    """

    audio: bytes
    mime: str = "audio/wav"
    sample_rate: int = 16000
    language: str = "zh"
    hotwords: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ASRResult:
    text: str
    # None 表示供应商不给置信度；不要用 0.0 冒充"不确定"。
    confidence: float | None = None
    latency_ms: int = 0


@dataclass(frozen=True, slots=True)
class TTSResult:
    audio: bytes
    mime: str
    latency_ms: int = 0
    # 流式首包耗时；非流式适配器为 None。
    first_chunk_ms: int | None = None


@dataclass(frozen=True, slots=True)
class QuestionScore:
    question_id: str
    score: int  # 0-100，五档 rubric
    why: str  # 一句为什么
    misconception_hit: bool = False
    certain: bool = False  # "确定检出"，决定 candidate 是否计数
    reference_answer: str = ""  # 开放题的标准答案；选择题可空


@dataclass(frozen=True, slots=True)
class SessionMisconception:
    text: str
    concept_key: str | None = None


@dataclass(frozen=True, slots=True)
class ScoreResult:
    questions: tuple[QuestionScore, ...]
    session_misconception: SessionMisconception | None = None
    latency_ms: int = 0


class ASRProvider(Protocol):
    name: str

    async def transcribe(self, request: ASRRequest) -> ASRResult: ...


class LLMProvider(Protocol):
    name: str
    supports_streaming: bool

    async def complete(
        self,
        messages: Sequence[ChatMessage],
        *,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> str: ...

    def stream(
        self,
        messages: Sequence[ChatMessage],
        *,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]: ...


class TTSProvider(Protocol):
    name: str
    supports_streaming: bool

    async def synthesize(self, text: str, *, voice: str | None = None) -> TTSResult: ...


class StreamingTTS(TTSProvider, Protocol):
    """可选能力：逐块返回音频。不实现本协议的适配器由 BFF 折叠成单块。"""

    def stream(self, text: str, *, voice: str | None = None) -> AsyncIterator[bytes]: ...


class JsonScorer(Protocol):
    """只返回模型原始 JSON 文本的端口（评分与概念抽取共用）。

    解析、校验与"解析失败重试一次、仍失败记 unscored"的编排在
    ``core.scoring`` 与 BFF 里完成，适配器不猜业务。
    """

    name: str

    async def grade(self, system_prompt: str, user_prompt: str) -> str: ...


class Embedder(Protocol):
    """批量文本嵌入；返回向量顺序必须与输入一致。"""

    name: str
    model: str
    dim: int

    async def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


@dataclass(frozen=True, slots=True)
class SearchHit:
    """一条外部搜索结果的原始形态；过滤与出处标注由 BFF 负责。"""

    title: str
    url: str
    content: str
    score: float = 0.0
    published_at: str | None = None


class SearchProvider(Protocol):
    """外部搜索端口；未配置时返回空列表，不阻塞自由对话。"""

    name: str

    async def search(
        self, query: str, *, max_results: int = 5
    ) -> list[SearchHit]: ...
