from __future__ import annotations

from bff.config import load_settings


def test_search_defaults() -> None:
    settings = load_settings({})
    assert settings.search.base_url == "https://api.tavily.com"
    assert settings.search_kind == "tavily"
    assert settings.search_max_results == 5
    assert settings.search_timeout_seconds == 8.0
    assert settings.search.api_key == ""
    assert settings.summary()["search"]["configured"] is True


def test_search_explicit_overrides() -> None:
    settings = load_settings(
        {
            "SEARCH_KIND": "off",
            "SEARCH_BASE_URL": "https://search.example.com",
            "TAVILY_API_KEY": "tvly-test",
            "SEARCH_MAX_RESULTS": "3",
            "SEARCH_TIMEOUT_SECONDS": "2.5",
        }
    )
    assert settings.search_kind == "off"
    assert settings.search.base_url == "https://search.example.com"
    assert settings.search.api_key == "tvly-test"
    assert settings.search_max_results == 3
    assert settings.search_timeout_seconds == 2.5


def test_agent_harness_defaults_off_and_inherits_scorer() -> None:
    settings = load_settings({})
    assert settings.agent_harness is False
    assert settings.agent_model == ""
    assert settings.agent_base_url == ""

    settings = load_settings(
        {
            "AGENT_HARNESS": "on",
            "SCORER_BASE_URL": "https://api.deepseek.com/v1",
            "SCORER_API_KEY": "ds-key",
            "SCORER_MODEL": "deepseek-chat",
        }
    )
    assert settings.agent_harness is True
    assert settings.agent_model == "deepseek-chat"
    assert settings.agent_base_url == "https://api.deepseek.com/v1"
    assert settings.agent_api_key == "ds-key"


def test_agent_harness_explicit_overrides() -> None:
    settings = load_settings(
        {
            "AGENT_HARNESS": "true",
            "SCORER_BASE_URL": "https://api.deepseek.com/v1",
            "SCORER_API_KEY": "ds-key",
            "SCORER_MODEL": "deepseek-chat",
            "AGENT_BASE_URL": "https://api.xiaomimimo.com/v1",
            "AGENT_API_KEY": "mimo-key",
            "AGENT_MODEL": "mimo-v2.6-flash",
        }
    )
    assert settings.agent_harness is True
    assert settings.agent_model == "mimo-v2.6-flash"
    assert settings.agent_base_url == "https://api.xiaomimimo.com/v1"
    assert settings.agent_api_key == "mimo-key"
    assert settings.summary()["agent"] == {
        "enabled": True,
        "model": "mimo-v2.6-flash",
        "configured": True,
    }


def test_affect_defaults() -> None:
    settings = load_settings({})
    assert settings.user_id == "owner"
    assert settings.user_role == "learner"
    assert settings.emotion_enabled is True
    assert settings.memory_enabled is True


def test_affect_explicit_overrides() -> None:
    settings = load_settings(
        {
            "USER_ID": "alice",
            "USER_ROLE": "mentor",
            "EMOTION_ENABLED": "off",
            "MEMORY_ENABLED": "false",
        }
    )
    assert settings.user_id == "alice"
    assert settings.user_role == "mentor"
    assert settings.emotion_enabled is False
    assert settings.memory_enabled is False
