from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from core.persona import (
    DEFAULT_LIFE_TEXTS,
    DEFAULT_PERSONA_ENTRIES,
    LifeItem,
    LifePool,
    PersonaConfig,
    PersonaEntry,
    PersonaError,
    default_life_pool,
    default_persona,
    load_persona,
    render_persona,
)


def _write(path: Path, payload: dict) -> Path:
    path.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return path


def _life(**kwargs) -> dict:
    item = {"id": "life-01", "text": "今天没有特别的事，只是把桌面收拾干净了。"}
    item.update(kwargs)
    return {"enabled": True, "items": [item]}


def _payload(
    entries: list[dict] | None = None,
    *,
    life: dict | None = None,
    version: int = 1,
) -> dict:
    return {
        "version": version,
        "entries": entries or [],
        "life_pool": life or _life(),
    }


def test_default_persona_has_twenty_two_entries_and_thirty_lives() -> None:
    config = default_persona()
    assert len(DEFAULT_PERSONA_ENTRIES) == 22
    assert len(config.entries) == 22
    assert len(DEFAULT_LIFE_TEXTS) == 30
    assert len(config.life_pool.items) == 30
    assert all(entry.enabled for entry in config.entries)
    assert all(item.enabled for item in config.life_pool.items)


def test_load_persona_reads_entries_and_life(tmp_path) -> None:
    path = _write(
        tmp_path / "persona.yaml",
        _payload(
            [
                {
                    "id": "who-01",
                    "category": "who",
                    "text": "我是从你的学习材料里长出来的。",
                },
                {
                    "id": "voice-01",
                    "category": "voice",
                    "text": "我说话短，一次说一件事。",
                    "enabled": False,
                },
            ],
            life=_life(),
        ),
    )
    config = load_persona(path)
    assert [entry.id for entry in config.entries] == ["who-01", "voice-01"]
    assert config.entries[1].enabled is False
    assert config.life_pool.enabled is True
    assert len(config.life_pool.items) == 1


def test_life_only_file_is_allowed(tmp_path) -> None:
    path = _write(tmp_path / "persona.yaml", _payload([], life=_life()))
    config = load_persona(path)
    assert config.entries == ()
    assert len(config.life_pool.items) == 1


def test_render_persona_groups_and_skips_disabled() -> None:
    config = default_persona()
    text = render_persona(config)
    assert text.index("【她是谁】") < text.index("【说话方式】")
    assert "我是从你的学习材料里长出来的。" in text
    assert "我不说“宝”“亲”“亲爱的”" in text

    disabled = PersonaConfig(
        entries=tuple(
            PersonaEntry(
                id=entry.id,
                category=entry.category,
                text=entry.text,
                enabled=False,
            )
            for entry in config.entries
        ),
        life_pool=config.life_pool,
    )
    assert render_persona(disabled) == ""


def test_missing_life_pool_is_error(tmp_path) -> None:
    path = _write(tmp_path / "persona.yaml", {"version": 1})
    with pytest.raises(PersonaError, match="life_pool"):
        load_persona(path)


def test_bad_version_is_error(tmp_path) -> None:
    path = _write(
        tmp_path / "persona.yaml",
        _payload([], version=2),
    )
    with pytest.raises(PersonaError, match="version"):
        load_persona(path)


def test_duplicate_entry_id_is_error(tmp_path) -> None:
    entry = {
        "id": "same",
        "category": "who",
        "text": "我是 MOMO。",
    }
    path = _write(tmp_path / "persona.yaml", _payload([entry, dict(entry)]))
    with pytest.raises(PersonaError, match="id 重复"):
        load_persona(path)


def test_bad_category_is_error(tmp_path) -> None:
    path = _write(
        tmp_path / "persona.yaml",
        _payload(
            [{"id": "x", "category": "unknown", "text": "我是 MOMO。"}]
        ),
    )
    with pytest.raises(PersonaError, match="category"):
        load_persona(path)


def test_long_entry_text_is_error(tmp_path) -> None:
    path = _write(
        tmp_path / "persona.yaml",
        _payload([{"id": "long", "category": "who", "text": "长" * 121}]),
    )
    with pytest.raises(PersonaError, match="超过 120 字"):
        load_persona(path)


def test_enabled_entry_budget_is_error(tmp_path) -> None:
    entries = [
        {"id": f"e{i}", "category": "who", "text": "长" * 120}
        for i in range(11)
    ]
    path = _write(tmp_path / "persona.yaml", _payload(entries))
    with pytest.raises(PersonaError, match="超过 1200 字"):
        load_persona(path)


def test_unknown_top_key_is_error(tmp_path) -> None:
    payload = _payload([])
    payload["discipline"] = []
    path = _write(tmp_path / "persona.yaml", payload)
    with pytest.raises(PersonaError, match="未知顶层键"):
        load_persona(path)


def test_unknown_entry_key_is_error(tmp_path) -> None:
    path = _write(
        tmp_path / "persona.yaml",
        _payload(
            [
                {
                    "id": "who-01",
                    "category": "who",
                    "text": "我是 MOMO。",
                    "weight": 1,
                }
            ]
        ),
    )
    with pytest.raises(PersonaError, match="未知字段"):
        load_persona(path)


def test_unknown_life_item_key_is_error(tmp_path) -> None:
    path = _write(
        tmp_path / "persona.yaml",
        _payload([], life=_life(weight=1)),
    )
    with pytest.raises(PersonaError, match="未知字段"):
        load_persona(path)


def test_duplicate_life_id_is_error(tmp_path) -> None:
    path = _write(
        tmp_path / "persona.yaml",
        _payload(
            [],
            life={
                "enabled": True,
                "items": [
                    {"id": "same", "text": "今天没有特别的事。"},
                    {"id": "same", "text": "晚上关窗时听见远处有火车经过的声音。"},
                ],
            },
        ),
    )
    with pytest.raises(PersonaError, match="id 重复"):
        load_persona(path)


def test_long_life_text_is_error(tmp_path) -> None:
    path = _write(
        tmp_path / "persona.yaml",
        _payload([], life=_life(text="长" * 61)),
    )
    with pytest.raises(PersonaError, match="超过 60 字"):
        load_persona(path)


def test_for_date_is_stable_and_changes_next_day() -> None:
    pool = default_life_pool()
    first = pool.for_date("2026-11-26")
    assert first is not None
    assert first == pool.for_date("2026-11-26")
    assert first != pool.for_date("2026-11-27")


def test_disabled_items_are_skipped() -> None:
    pool = LifePool(
        enabled=True,
        items=(
            LifeItem("a", "今天把窗台那盆薄荷挪到了有太阳的一侧。", False),
            LifeItem("b", "早上泡茶时走神，等想起来，茶已经凉了。", True),
        ),
    )
    for day in ("2026-11-26", "2026-11-27", "2026-11-28"):
        assert pool.for_date(day) == "早上泡茶时走神，等想起来，茶已经凉了。"


def test_disabled_pool_returns_none() -> None:
    pool = LifePool(enabled=False, items=(LifeItem("a", "今天没有特别的事。"),))
    assert pool.for_date("2026-11-26") is None


def test_empty_pool_returns_none() -> None:
    assert LifePool(enabled=True, items=()).for_date("2026-11-26") is None


def test_invalid_date_returns_none() -> None:
    assert default_life_pool().for_date("not-a-date") is None
