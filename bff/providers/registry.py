"""按配置选择真实适配器或离线假实现。

规则：
- ``PROVIDER_MODE=real``：默认四个服务都必须配置，缺一个就启动失败（不静默造数据）。
- ``PROVIDER_MODE=auto``：配置了就真实调用，没配置的退回 fake 并记警告。
- ``PROVIDER_MODE=fake``：全部 fake，用于离线联调。
- 探针可以用 ``required`` 缩小必配范围，只测 ASR/TTS/LLM。

适配器按 ``LLM_KIND`` / ``ASR_KIND`` / ``TTS_KIND`` 选择：
- ``mimo`` + ``mimo_asr``：小米 MiMo 的 chat 与 input_audio ASR
- ``breeze``：Breeze Blue 的 text-to-speech
- 其他值：OpenAI 兼容形状
"""

from __future__ import annotations

from dataclasses import dataclass, field

from core.ports import ASRProvider, Embedder, JsonScorer, LLMProvider, SearchProvider, TTSProvider

from ..config import MODE_FAKE, MODE_REAL, MODES, Endpoint, Settings
from .base import ProviderNotConfigured
from .breeze import BreezeTTS
from .deepseek_tts import DeepSeekTTS
from .embeddings import OpenAICompatibleEmbedder
from .fake import FakeASR, FakeEmbedder, FakeLLM, FakeScorer, FakeSearch, FakeTTS, NullSearch
from .mimo import MiMoASR, MiMoLLM
from .openai_compat import (
    OpenAICompatibleASR,
    OpenAICompatibleLLM,
    OpenAICompatibleScorer,
    OpenAICompatibleTTS,
    require_base_url,
)
from .tavily import TavilySearch


@dataclass
class Providers:
    asr: ASRProvider
    llm: LLMProvider
    tts: TTSProvider
    scorer: JsonScorer
    embedder: Embedder
    search: SearchProvider
    chat: LLMProvider | None = None
    modes: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    @property
    def any_fake(self) -> bool:
        # embedding 未配置时是 fake，但不影响会话链路，不能把整站标成离线。
        return any(
            self.modes.get(key) == "fake" for key in ("asr", "llm", "tts", "scorer")
        )

    async def aclose(self) -> None:
        for adapter in (
            self.asr,
            self.llm,
            self.tts,
            self.scorer,
            self.embedder,
            self.search,
            self.chat,
        ):
            if adapter is self.llm:
                continue
            close = getattr(adapter, "aclose", None)
            if close is not None:
                await close()


def _auth_header(llm_auth: str) -> str:
    return "api-key" if llm_auth.replace("-", "_") == "api_key" else "authorization"


def _pick(
    *,
    key: str,
    settings: Settings,
    endpoint: Endpoint,
    build,
    fake_factory,
    required: set[str] | None,
    notes: list[str],
    kind: str = "",
) -> tuple[object, str]:
    if settings.mode == MODE_FAKE or kind == "fake":
        return fake_factory(), "fake"

    if not endpoint.configured:
        needs_it = required is None or key in required
        if settings.mode == MODE_REAL and needs_it:
            raise ProviderNotConfigured(f"{endpoint.label} 未配置 base_url，real 模式拒绝启动")
        if needs_it:
            notes.append(f"{endpoint.label} 未配置，使用离线假实现")
        else:
            notes.append(f"{endpoint.label} 未参与本次探针，使用假实现")
        return fake_factory(), "fake"

    try:
        return build(endpoint), "real"
    except ProviderNotConfigured:
        raise
    except Exception as exc:  # pragma: no cover - 构造期错误少见
        raise ProviderNotConfigured(f"{endpoint.label} 适配器构造失败：{exc}") from exc


def build_providers(settings: Settings, required: set[str] | None = None) -> Providers:
    if settings.mode not in MODES:
        raise ValueError(f"未知的 PROVIDER_MODE：{settings.mode}")

    notes: list[str] = []
    modes: dict[str, str] = {}
    timeout = settings.http_timeout

    def pick(key: str, endpoint: Endpoint, build, fake_factory, kind: str = ""):
        adapter, modes[key] = _pick(
            key=key,
            settings=settings,
            endpoint=endpoint,
            build=build,
            fake_factory=fake_factory,
            required=required,
            notes=notes,
            kind=kind,
        )
        return adapter

    def build_llm(ep: Endpoint):
        if settings.llm_kind == "mimo":
            return MiMoLLM(
                require_base_url(ep),
                timeout=timeout,
                send_temperature=settings.llm_send_temperature,
                auth_header=_auth_header(settings.llm_auth),
            )
        return OpenAICompatibleLLM(require_base_url(ep), timeout=timeout)

    def build_asr(ep: Endpoint):
        if settings.asr_kind == "mimo_asr":
            return MiMoASR(
                require_base_url(ep),
                timeout=timeout,
                language=settings.asr_language,
            )
        return OpenAICompatibleASR(
            require_base_url(ep), timeout=timeout, language=settings.asr_language
        )

    def build_tts(ep: Endpoint):
        if settings.tts_kind == "breeze":
            return BreezeTTS(
                require_base_url(ep),
                timeout=timeout,
                voice=settings.tts_voice,
                language=settings.tts_language,
                output_format=settings.tts_output_format,
            )
        if settings.tts_kind == "deepseek":
            return DeepSeekTTS(
                require_base_url(ep), timeout=timeout, voice=settings.tts_voice
            )
        return OpenAICompatibleTTS(
            require_base_url(ep), timeout=timeout, voice=settings.tts_voice
        )

    asr = pick("asr", settings.asr, build_asr, FakeASR, settings.asr_kind)
    llm = pick("llm", settings.llm, build_llm, FakeLLM, settings.llm_kind)
    tts = pick("tts", settings.tts, build_tts, FakeTTS, settings.tts_kind)
    scorer = pick(
        "scorer",
        settings.scorer,
        lambda ep: OpenAICompatibleScorer(
            require_base_url(ep), timeout=timeout, json_mode=settings.scorer_json_mode
        ),
        FakeScorer,
    )
    embedder = pick(
        "embedding",
        settings.embedding,
        lambda ep: OpenAICompatibleEmbedder(
            require_base_url(ep), timeout=timeout, dim=settings.embedding_dim
        ),
        lambda: FakeEmbedder(settings.embedding_dim),
    )

    search: SearchProvider
    if settings.search_kind == "off":
        search = NullSearch()
        modes["search"] = "off"
    elif settings.mode == MODE_FAKE:
        search = FakeSearch()
        modes["search"] = "fake"
    elif not settings.search.api_key.strip():
        search = NullSearch()
        modes["search"] = "off"
        notes.append("Tavily 未配置 API key，搜索关闭")
    else:
        try:
            if settings.search_kind != "tavily":
                raise ProviderNotConfigured(f"未知的 SEARCH_KIND：{settings.search_kind}")
            search = TavilySearch(
                settings.search, timeout=settings.search_timeout_seconds
            )
            modes["search"] = "real"
        except Exception as exc:
            search = NullSearch()
            modes["search"] = "off"
            notes.append(f"搜索未启用：{exc}")

    chat: LLMProvider | None = None
    if settings.mode != MODE_FAKE and settings.scorer.configured:
        try:
            chat = OpenAICompatibleLLM(
                settings.scorer, timeout=timeout, auth_header="authorization"
            )
            chat.name = "deepseek-chat"
            notes.append("自由对话使用 DeepSeek Flash（比 MiMo LLM 快）")
        except ProviderNotConfigured:
            chat = llm  # type: ignore[assignment]
    else:
        chat = llm  # type: ignore[assignment]

    return Providers(
        asr=asr,  # type: ignore[arg-type]
        llm=llm,  # type: ignore[arg-type]
        tts=tts,  # type: ignore[arg-type]
        scorer=scorer,  # type: ignore[arg-type]
        embedder=embedder,  # type: ignore[arg-type]
        search=search,
        chat=chat,
        modes=modes,
        notes=notes,
    )
