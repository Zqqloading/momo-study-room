"""BFF 配置：全部来自环境变量 / .env，无硬编码密钥。

四个外部 API 的接口地址、鉴权、音频格式仍在冻结规格的"待定区"，
所以这里只定义字段，不假设形状；没配置时由注册表退回离线 fake。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

MODE_AUTO = "auto"
MODE_REAL = "real"
MODE_FAKE = "fake"
MODES = (MODE_AUTO, MODE_REAL, MODE_FAKE)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True, slots=True)
class Endpoint:
    """一个外部服务的连接信息。base_url 为空即视为未配置。"""

    label: str
    base_url: str = ""
    api_key: str = ""
    model: str = ""

    @property
    def configured(self) -> bool:
        return bool(self.base_url.strip())

    def describe(self) -> dict[str, object]:
        return {
            "label": self.label,
            "base_url": self.base_url,
            "model": self.model,
            "configured": self.configured,
            "has_key": bool(self.api_key.strip()),
        }


@dataclass(frozen=True, slots=True)
class Settings:
    mode: str
    llm: Endpoint
    asr: Endpoint
    tts: Endpoint
    scorer: Endpoint
    embedding: Endpoint
    search: Endpoint
    llm_kind: str
    llm_auth: str
    llm_send_temperature: bool
    asr_kind: str
    tts_kind: str
    search_kind: str
    tts_language: str
    tts_output_format: str
    asr_language: str
    tts_voice: str
    scorer_json_mode: bool
    http_timeout: float
    agent_harness: bool = False
    agent_model: str = ""
    agent_base_url: str = ""
    agent_api_key: str = ""
    user_id: str = "owner"
    user_role: str = "learner"
    emotion_enabled: bool = True
    memory_enabled: bool = True
    admin_task_runner: bool = False
    embedding_dim: int = 1024
    retrieval_min_cosine: float = 0.35
    search_max_results: int = 5
    search_timeout_seconds: float = 8.0
    project_root: Path = PROJECT_ROOT
    content_dir: Path = PROJECT_ROOT
    web_dir: Path = field(default=PROJECT_ROOT / "web")
    assets_dir: Path = field(default=PROJECT_ROOT / "assets")
    data_dir: Path = field(default=PROJECT_ROOT / "data")
    db_path: Path = field(default=PROJECT_ROOT / "data" / "app.db")

    def summary(self) -> dict[str, object]:
        return {
            "mode": self.mode,
            "kinds": {
                "llm": self.llm_kind,
                "asr": self.asr_kind,
                "tts": self.tts_kind,
            },
            "asr": self.asr.describe(),
            "llm": self.llm.describe(),
            "tts": self.tts.describe(),
            "scorer": self.scorer.describe(),
            "embedding": self.embedding.describe(),
            "search": self.search.describe(),
            "agent": {
                "enabled": self.agent_harness,
                "model": self.agent_model,
                "configured": bool(self.agent_base_url),
            },
        }


def _get(env: Mapping[str, str], key: str, default: str = "") -> str:
    return (env.get(key) or default).strip()


def load_settings(env: Mapping[str, str] | None = None) -> Settings:
    """从给定映射或进程环境读取配置。测试可传入纯 dict。"""
    if env is None:
        try:
            from dotenv import load_dotenv

            load_dotenv(PROJECT_ROOT / ".env", override=False)
        except ImportError:  # pragma: no cover - .env 只是便利，不是必需
            pass
        env = os.environ

    mode = _get(env, "PROVIDER_MODE", MODE_AUTO).lower()
    if mode not in MODES:
        raise ValueError(f"PROVIDER_MODE 只能是 {'/'.join(MODES)}，收到 {mode!r}")

    llm_kind = _get(env, "LLM_KIND", "mimo").lower()
    asr_kind = _get(env, "ASR_KIND", "mimo_asr").lower()
    tts_kind = _get(env, "TTS_KIND", "breeze").lower()
    search_kind = _get(env, "SEARCH_KIND", "tavily").lower()

    llm_auth = _get(env, "LLM_AUTH", "api_key" if llm_kind == "mimo" else "bearer").lower()
    llm_send_temperature = _get(
        env, "LLM_SEND_TEMPERATURE", "0" if llm_kind == "mimo" else "1"
    ) in {"1", "true", "yes"}

    mimo_key = _get(env, "MIMO_API_KEY")
    llm_model = _get(env, "LLM_MODEL", "mimo-v2.6-flash" if llm_kind == "mimo" else "")
    asr_model = _get(
        env, "ASR_MODEL_NAME", "mimo-v2.5-asr" if asr_kind == "mimo_asr" else ""
    )
    tts_model = _get(env, "TTS_MODEL", "breeze-tts-2" if tts_kind == "breeze" else "")
    data_dir = Path(_get(env, "DATA_DIR", str(PROJECT_ROOT / "data")))
    scorer_base_url = _get(env, "SCORER_BASE_URL")
    scorer_api_key = _get(env, "SCORER_API_KEY")
    scorer_model = _get(env, "SCORER_MODEL")
    agent_harness = _get(env, "AGENT_HARNESS", "off").lower() in {
        "1",
        "on",
        "true",
        "yes",
    }
    emotion_enabled = _get(env, "EMOTION_ENABLED", "on").lower() in {
        "1",
        "on",
        "true",
        "yes",
    }
    memory_enabled = _get(env, "MEMORY_ENABLED", "on").lower() in {
        "1",
        "on",
        "true",
        "yes",
    }
    admin_task_runner = _get(
        env,
        "ADMIN_TASK_RUNNER",
        "off" if mode == MODE_FAKE else "on",
    ).lower() in {
        "1",
        "on",
        "true",
        "yes",
    }

    return Settings(
        mode=mode,
        llm=Endpoint(
            label="MiMo LLM" if llm_kind == "mimo" else "LLM",
            base_url=_get(env, "LLM_BASE_URL"),
            api_key=_get(env, "LLM_API_KEY") or mimo_key,
            model=llm_model,
        ),
        asr=Endpoint(
            label="MiMo ASR" if asr_kind == "mimo_asr" else "ASR",
            base_url=_get(env, "ASR_BASE_URL"),
            api_key=_get(env, "ASR_API_KEY") or mimo_key,
            model=asr_model,
        ),
        tts=Endpoint(
            label={"breeze": "Breeze TTS", "deepseek": "DeepSeek TTS"}.get(
                tts_kind, "TTS"
            ),
            base_url=_get(env, "TTS_BASE_URL"),
            api_key=_get(env, "TTS_API_KEY")
            or (
                _get(env, "SCORER_API_KEY")
                if tts_kind == "deepseek"
                else _get(env, "BREEZE_API_KEY")
            ),
            model=tts_model,
        ),
        scorer=Endpoint(
            label="DeepSeek Flash",
            base_url=scorer_base_url,
            api_key=scorer_api_key,
            model=scorer_model,
        ),
        embedding=Endpoint(
            label="Aliyun Embedding",
            base_url=_get(env, "EMBEDDING_BASE_URL"),
            api_key=_get(env, "EMBEDDING_API_KEY"),
            model=_get(env, "EMBEDDING_MODEL", "text-embedding-v4"),
        ),
        search=Endpoint(
            label="Tavily",
            base_url=_get(env, "SEARCH_BASE_URL", "https://api.tavily.com"),
            api_key=_get(env, "TAVILY_API_KEY"),
        ),
        llm_kind=llm_kind,
        llm_auth=llm_auth,
        llm_send_temperature=llm_send_temperature,
        asr_kind=asr_kind,
        tts_kind=tts_kind,
        search_kind=search_kind,
        tts_language=_get(env, "TTS_LANGUAGE", "zh"),
        tts_output_format=_get(env, "TTS_OUTPUT_FORMAT", "mp3_24000_128"),
        asr_language=_get(env, "ASR_LANGUAGE", "zh"),
        tts_voice=_get(env, "TTS_VOICE"),
        scorer_json_mode=_get(env, "SCORER_JSON_MODE", "0") in {"1", "true", "yes"},
        http_timeout=float(_get(env, "HTTP_TIMEOUT_SECONDS", "60")),
        agent_harness=agent_harness,
        agent_model=_get(env, "AGENT_MODEL") or scorer_model,
        agent_base_url=_get(env, "AGENT_BASE_URL") or scorer_base_url,
        agent_api_key=_get(env, "AGENT_API_KEY") or scorer_api_key,
        user_id=_get(env, "USER_ID", "owner"),
        user_role=_get(env, "USER_ROLE", "learner"),
        emotion_enabled=emotion_enabled,
        memory_enabled=memory_enabled,
        admin_task_runner=admin_task_runner,
        data_dir=data_dir,
        db_path=Path(_get(env, "DB_PATH") or str(data_dir / "app.db")),
        embedding_dim=int(_get(env, "EMBEDDING_DIM", "1024")),
        retrieval_min_cosine=float(_get(env, "RETRIEVAL_MIN_COSINE", "0.35")),
        search_max_results=int(_get(env, "SEARCH_MAX_RESULTS", "5")),
        search_timeout_seconds=float(_get(env, "SEARCH_TIMEOUT_SECONDS", "8")),
        content_dir=Path(_get(env, "CONTENT_DIR") or str(PROJECT_ROOT)),
    )
