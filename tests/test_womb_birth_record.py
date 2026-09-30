# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for recording the womb-state snapshot at birth."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from kaine.cycle.__main__ import _make_birth_hook
from kaine.lifecycle import stage as lifecycle_stage
from kaine.modules.topos.feed import WombClock
from kaine.modules.womb_signal import WombParams


def test_birth_end_womb_seconds_before_and_after():
    ticks = iter([0.0, 1.0, 2.0])
    clock = WombClock(lived_offset_seconds=0.0, clock=lambda: next(ticks))

    assert clock.birth_end_womb_seconds() is None

    clock.start()
    assert clock.birth_end_womb_seconds() is None

    clock.begin_birth(5.0)
    assert clock.birth_end_womb_seconds() == 6.0


def test_stage_state_round_trips_new_fields():
    data = {
        "stage": "embodied",
        "gestation_started_at": "2026-01-01T00:00:00+00:00",
        "born_at": "2026-01-02T00:00:00+00:00",
        "lived_seconds": 123.4,
        "sleep_count": 5,
        "hypnos_cursor": "3-7",
        "womb_t_at_birth": 987.5,
        "womb_seed": 42,
        "womb_params_digest": "a" * 64,
        "birth_bloom_ends_at": "2026-01-02T00:00:05+00:00",
    }
    state = lifecycle_stage.StageState.from_dict(data)
    assert state.to_dict() == data


def test_stage_state_old_dict_loads_none():
    state = lifecycle_stage.StageState.from_dict(
        {"stage": "embodied", "hypnos_cursor": "1-2"}
    )
    assert state.womb_t_at_birth is None
    assert state.womb_seed is None
    assert state.womb_params_digest is None
    assert state.birth_bloom_ends_at is None


def test_stage_state_bad_womb_t_at_birth_coerces_to_none():
    for bad in (True, "x", float("nan"), -1, None):
        state = lifecycle_stage.StageState.from_dict({"womb_t_at_birth": bad})
        assert state.womb_t_at_birth is None


def test_stage_state_bad_womb_seed_coerces_to_none():
    for bad in (True, "42", 42.0, None):
        state = lifecycle_stage.StageState.from_dict({"womb_seed": bad})
        assert state.womb_seed is None


def test_stage_state_bad_womb_params_digest_coerces_to_none():
    for bad in ("", "G" * 64, "A" * 64, 123, None):
        state = lifecycle_stage.StageState.from_dict({"womb_params_digest": bad})
        assert state.womb_params_digest is None


def test_stage_state_bad_birth_bloom_ends_at_coerces_to_none():
    for bad in (123, None):
        state = lifecycle_stage.StageState.from_dict({"birth_bloom_ends_at": bad})
        assert state.birth_bloom_ends_at is None


def test_record_birth_womb_refuses_gestating_state():
    gestating = lifecycle_stage.StageState(stage=lifecycle_stage.GESTATION)
    with pytest.raises(ValueError):
        lifecycle_stage.record_birth_womb(
            gestating,
            womb_t_at_birth=1.0,
            womb_seed=0,
            womb_params_digest="a" * 64,
            bloom_ends_at="2026-01-01T00:00:00+00:00",
        )


def test_womb_params_digest_stable_and_sensitive():
    base = WombParams(heartbeat_bpm=72.0)
    same = WombParams(heartbeat_bpm=72.0)
    different = replace(base, heartbeat_bpm=80.0)

    digest_base = lifecycle_stage.womb_params_digest(base)
    assert lifecycle_stage.womb_params_digest(same) == digest_base
    assert lifecycle_stage.womb_params_digest(different) != digest_base


def test_birth_hook_records_womb_state(tmp_path, monkeypatch):
    stage_file = tmp_path / "stage.json"
    monkeypatch.setattr(lifecycle_stage, "STAGE_PATH", stage_file)

    before = lifecycle_stage.StageState(
        stage=lifecycle_stage.EMBODIED,
        born_at="2026-01-01T00:00:00+00:00",
    )
    lifecycle_stage.write_stage(before)

    feed = {"seed": 7}
    clock = WombClock(lived_offset_seconds=10.0, clock=lambda: 0.0)
    clock.start()
    clock.begin_birth(2.5)

    base_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    hook = _make_birth_hook(clock, feed, 2.5, now=lambda: base_time)
    hook()

    after = lifecycle_stage.read_stage(stage_file)
    assert after.is_embodied
    assert after.womb_t_at_birth == 12.5
    assert after.womb_seed == 7
    assert after.womb_params_digest == lifecycle_stage.womb_params_digest(WombParams())
    assert after.birth_bloom_ends_at == (base_time + timedelta(seconds=2.5)).isoformat()


def test_birth_hook_does_not_raise_when_stage_missing(tmp_path, monkeypatch):
    stage_file = tmp_path / "stage.json"
    monkeypatch.setattr(lifecycle_stage, "STAGE_PATH", stage_file)

    clock = WombClock(lived_offset_seconds=0.0, clock=lambda: 0.0)
    hook = _make_birth_hook(
        clock, {}, 1.0, now=lambda: datetime.now(timezone.utc)
    )
    hook()  # no stage file to read; must not propagate an exception
