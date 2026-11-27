from __future__ import annotations

import asyncio

import pytest

from bff.config import load_settings
from bff.providers.base import ProviderNotConfigured
from bff.providers.registry import build_providers


def test_auto_falls_back_to_fake_without_config() -> None:
    providers = build_providers(load_settings({}))
    assert providers.modes == {
        "asr": "fake",
        "llm": "fake",
        "tts": "fake",
        "scorer": "fake",
        "embedding": "fake",
        "search": "off",
    }
    assert providers.any_fake is True
    assert len(providers.notes) == 6


def test_search_is_off_without_key() -> None:
    providers = build_providers(load_settings({}))
    try:
        assert providers.modes["search"] == "off"
        assert providers.search.name == "search-off"
        assert asyncio.run(providers.search.search("agent")) == []
    finally:
        asyncio.run(providers.aclose())


def test_search_is_real_with_key() -> None:
    providers = build_providers(load_settings({"TAVILY_API_KEY": "tvly-test"}))
    try:
        assert providers.modes["search"] == "real"
        assert providers.search.name == "tavily"
    finally:
        asyncio.run(providers.aclose())


def test_search_is_fake_in_fake_mode() -> None:
    providers = build_providers(load_settings({"PROVIDER_MODE": "fake"}))
    try:
        assert providers.modes["search"] == "fake"
        assert providers.search.name == "fake-search"
    finally:
        asyncio.run(providers.aclose())


def test_search_kind_off_wins_over_key() -> None:
    providers = build_providers(
        load_settings({"TAVILY_API_KEY": "tvly-test", "SEARCH_KIND": "off"})
    )
    try:
        assert providers.modes["search"] == "off"
        assert providers.search.name == "search-off"
    finally:
        asyncio.run(providers.aclose())


def test_fake_mode_ignores_configured_endpoints() -> None:
    settings = load_settings({"PROVIDER_MODE": "fake", "LLM_BASE_URL": "https://example.com/v1"})
    providers = build_providers(settings)
    assert providers.modes["llm"] == "fake"


def test_real_mode_refuses_to_start_without_config() -> None:
    with pytest.raises(ProviderNotConfigured):
        build_providers(load_settings({"PROVIDER_MODE": "real"}))


def test_auto_builds_real_adapter_when_configured() -> None:
    settings = load_settings({"LLM_BASE_URL": "http://127.0.0.1:9/v1", "LLM_MODEL": "mimo-2.6"})
    providers = build_providers(settings)
    try:
        assert providers.modes["llm"] == "real"
        assert providers.modes["asr"] == "fake"
        assert providers.llm.name == "mimo-llm"
    finally:
        asyncio.run(providers.aclose())


def test_openai_compat_kind_selects_generic_llm() -> None:
    settings = load_settings(
        {
            "LLM_KIND": "openai_compat",
            "LLM_BASE_URL": "http://127.0.0.1:9/v1",
            "LLM_MODEL": "local-model",
        }
    )
    providers = build_providers(settings)
    try:
        assert providers.llm.name == "openai-compatible-llm"
    finally:
        asyncio.run(providers.aclose())


def test_default_kinds_select_mimo_and_breeze() -> None:
    settings = load_settings(
        {
            "LLM_BASE_URL": "https://api.xiaomimimo.com/v1",
            "LLM_API_KEY": "k",
            "ASR_BASE_URL": "https://api.xiaomimimo.com/v1",
            "ASR_API_KEY": "k",
            "TTS_BASE_URL": "https://api.breeze.blue",
            "TTS_API_KEY": "k",
            "TTS_VOICE": "voc_x",
        }
    )
    providers = build_providers(settings)
    try:
        assert providers.asr.name == "mimo-asr"
        assert providers.tts.name == "breeze-tts"
        assert providers.llm.name == "mimo-llm"
    finally:
        asyncio.run(providers.aclose())


def test_deepseek_tts_kind_selects_deepseek_adapter() -> None:
    settings = load_settings(
        {
            "TTS_KIND": "deepseek",
            "TTS_BASE_URL": "https://api.deepseek.com",
            "TTS_API_KEY": "k",
            "TTS_VOICE": "stella",
        }
    )
    providers = build_providers(settings)
    try:
        assert providers.tts.name == "deepseek-tts"
    finally:
        asyncio.run(providers.aclose())


def test_tts_kind_fake_uses_fake_adapter_even_with_endpoint() -> None:
    settings = load_settings(
        {
            "TTS_KIND": "fake",
            "TTS_BASE_URL": "https://api.deepseek.com",
            "TTS_API_KEY": "bad",
        }
    )
    providers = build_providers(settings)
    try:
        assert providers.modes["tts"] == "fake"
        assert providers.tts.name == "fake-tts"
    finally:
        asyncio.run(providers.aclose())


def test_deepseek_tts_reuses_scorer_key_when_tts_key_missing() -> None:
    settings = load_settings(
        {
            "TTS_KIND": "deepseek",
            "TTS_BASE_URL": "https://api.deepseek.com",
            "SCORER_API_KEY": "sk-shared",
        }
    )
    assert settings.tts.api_key == "sk-shared"


def test_invalid_mode_rejected() -> None:
    with pytest.raises(ValueError):
        load_settings({"PROVIDER_MODE": "production"})


def test_chat_uses_deepseek_endpoint_when_configured() -> None:
    settings = load_settings(
        {"SCORER_BASE_URL": "http://127.0.0.1:9/v1", "SCORER_MODEL": "deepseek-chat"}
    )
    providers = build_providers(settings)
    try:
        assert providers.chat is not None
        assert providers.chat.name == "deepseek-chat"
    finally:
        asyncio.run(providers.aclose())


def test_chat_falls_back_to_main_llm() -> None:
    providers = build_providers(load_settings({}))
    try:
        assert providers.chat is providers.llm
    finally:
        asyncio.run(providers.aclose())
