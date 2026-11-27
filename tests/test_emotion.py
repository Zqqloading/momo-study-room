from __future__ import annotations

from datetime import datetime, timedelta

from core.emotion import (
    Emotion,
    EmotionUpdate,
    apply_delta,
    decay,
    parse_emotion_update,
    round_tenth,
    tone_hint,
)

START = datetime(2026, 11, 26, 10, 0, 0)


def _after(hours: float, state: Emotion = Emotion(0.8, 0.9)) -> Emotion:
    return decay(state, "2026-11-26T10:00:00", START + timedelta(hours=hours))


def test_decay_halves_every_two_hours() -> None:
    assert _after(0) == Emotion(0.8, 0.9)
    assert _after(2) == Emotion(0.4, 0.7)
    assert _after(4) == Emotion(0.2, 0.6)
    assert _after(8) == Emotion(0.05, 0.525)


def test_midpoint_does_not_move() -> None:
    assert _after(6, Emotion(0.0, 0.5)) == Emotion(0.0, 0.5)


def test_decay_ignores_future_timestamps() -> None:
    future = (START + timedelta(hours=2)).isoformat(timespec="seconds")
    assert decay(Emotion(0.8, 0.9), future, START) == Emotion(0.8, 0.9)


def test_non_intense_delta_is_clamped_to_three_tenths() -> None:
    state = apply_delta(Emotion(0.0, 0.5), EmotionUpdate(0.5, -0.9))
    assert state == Emotion(0.3, 0.2)


def test_intense_delta_skips_clamp_but_stays_in_bounds() -> None:
    state = apply_delta(
        Emotion(0.4, 0.5), EmotionUpdate(-0.8, 0.9, intense=True)
    )
    assert state == Emotion(-0.4, 1.0)


def test_final_values_never_leave_bounds() -> None:
    high = apply_delta(Emotion(0.9, 0.9), EmotionUpdate(0.9, 0.9, intense=True))
    low = apply_delta(Emotion(-0.9, 0.1), EmotionUpdate(-0.9, -0.9, intense=True))
    assert high == Emotion(1.0, 1.0)
    assert low == Emotion(-1.0, 0.0)


def test_round_tenth_is_half_up_away_from_zero() -> None:
    assert round_tenth(0.05) == 0.1
    assert round_tenth(-0.05) == -0.1
    assert round_tenth(0.04) == 0.0
    assert round_tenth(-0.04) == 0.0
    assert round_tenth(0.25) == 0.3


def test_applied_values_are_on_tenth_grid() -> None:
    state = apply_delta(Emotion(0.05, 0.55), EmotionUpdate(0.05, -0.05))
    for value in (state.comfort, state.energy):
        assert round(value * 10, 6) == int(round(value * 10))


def test_tone_hint_covers_three_by_three() -> None:
    hints = {
        tone_hint(Emotion(comfort, energy))
        for comfort in (0.8, 0.0, -0.8)
        for energy in (0.9, 0.5, 0.1)
    }
    assert len(hints) == 9


def test_tone_boundaries_follow_design() -> None:
    assert "轻快" in tone_hint(Emotion(0.4, 0.7))
    assert "明快" in tone_hint(Emotion(0.39, 0.7))
    assert "直接" in tone_hint(Emotion(-0.3, 0.7))
    assert "平稳" in tone_hint(Emotion(-0.29, 0.5))
    assert "收着" in tone_hint(Emotion(-0.3, 0.5))
    assert "放轻" in tone_hint(Emotion(0.0, 0.39))
    assert "平稳" in tone_hint(Emotion(0.0, 0.4))


def test_tone_hint_has_no_raw_numbers() -> None:
    for comfort in (0.8, 0.0, -0.8):
        for energy in (0.9, 0.5, 0.1):
            hint = tone_hint(Emotion(comfort, energy))
            assert not any(char.isdigit() for char in hint)


def test_parse_valid_update() -> None:
    update = parse_emotion_update(
        '{"comfort_delta":0.2,"energy_delta":-0.1,'
        '"intense":true,"reason":"用户很累"}'
    )
    assert update == EmotionUpdate(0.2, -0.1, True, "用户很累")


def test_parse_missing_and_wrong_typed_fields_defaults_to_zero() -> None:
    update = parse_emotion_update(
        '{"comfort_delta":"0.5","energy_delta":null,"intense":1}'
    )
    assert update == EmotionUpdate()


def test_parse_invalid_json_defaults_to_zero() -> None:
    assert parse_emotion_update("不是 JSON") == EmotionUpdate()


def test_parse_fenced_json() -> None:
    raw = "```json\n{\"comfort_delta\":-0.3,\"energy_delta\":0.2}\n```"
    assert parse_emotion_update(raw) == EmotionUpdate(-0.3, 0.2, False, "")
