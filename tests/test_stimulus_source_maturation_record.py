# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for recording the stimulus-source-state snapshot at maturation."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import pytest

from kaine.cycle.__main__ import _make_maturation_hook
from kaine.lifecycle import stage as lifecycle_stage
from kaine.modules.stimulus_source_signal import StimulusSourceParams
from kaine.modules.vision.feed import StimulusSourceClock


def test_maturation_end_stimulus_source_seconds_before_and_after():
    ticks = iter([0.0, 1.0, 2.0])
    clock = StimulusSourceClock(lived_offset_seconds=0.0, clock=lambda: next(ticks))

    assert clock.maturation_end_stimulus_source_seconds() is None

    clock.start()
    assert clock.maturation_end_stimulus_source_seconds() is None

    clock.begin_maturation(5.0)
    assert clock.maturation_end_stimulus_source_seconds() == 6.0


def test_stage_state_round_trips_new_fields():
    data = {
        "stage": "embodied",
        "development_started_at": "2026-01-01T00:00:00+00:00",
        "born_at": "2026-01-02T00:00:00+00:00",
        "lived_seconds": 123.4,
        "sleep_count": 5,
        "sleep_cursor": "3-7",
        "stimulus_source_t_at_maturation": 987.5,
        "stimulus_source_seed": 42,
        "stimulus_source_params_digest": "a" * 64,
        "maturation_bloom_ends_at": "2026-01-02T00:00:05+00:00",
    }
    state = lifecycle_stage.StageState.from_dict(data)
    assert state.to_dict() == data


def test_stage_state_old_dict_loads_none():
    state = lifecycle_stage.StageState.from_dict(
        {"stage": "embodied", "sleep_cursor": "1-2"}
    )
    assert state.stimulus_source_t_at_maturation is None
    assert state.stimulus_source_seed is None
    assert state.stimulus_source_params_digest is None
    assert state.maturation_bloom_ends_at is None


def test_stage_state_bad_stimulus_source_t_at_maturation_coerces_to_none():
    for bad in (True, "x", float("nan"), -1, None):
        state = lifecycle_stage.StageState.from_dict({"stimulus_source_t_at_maturation": bad})
        assert state.stimulus_source_t_at_maturation is None


def test_stage_state_bad_stimulus_source_seed_coerces_to_none():
    for bad in (True, "42", 42.0, None):
        state = lifecycle_stage.StageState.from_dict({"stimulus_source_seed": bad})
        assert state.stimulus_source_seed is None


def test_stage_state_bad_stimulus_source_params_digest_coerces_to_none():
    for bad in ("", "G" * 64, "A" * 64, 123, None):
        state = lifecycle_stage.StageState.from_dict({"stimulus_source_params_digest": bad})
        assert state.stimulus_source_params_digest is None


def test_stage_state_bad_maturation_bloom_ends_at_coerces_to_none():
    for bad in (123, None):
        state = lifecycle_stage.StageState.from_dict({"maturation_bloom_ends_at": bad})
        assert state.maturation_bloom_ends_at is None


def test_record_maturation_stimulus_source_refuses_developing_state():
    developing = lifecycle_stage.StageState(stage=lifecycle_stage.DEVELOPMENT)
    with pytest.raises(ValueError):
        lifecycle_stage.record_maturation_stimulus_source(
            developing,
            stimulus_source_t_at_maturation=1.0,
            stimulus_source_seed=0,
            stimulus_source_params_digest="a" * 64,
            bloom_ends_at="2026-01-01T00:00:00+00:00",
        )


def test_stimulus_source_params_digest_stable_and_sensitive():
    base = StimulusSourceParams(heartbeat_bpm=72.0)
    same = StimulusSourceParams(heartbeat_bpm=72.0)
    different = replace(base, heartbeat_bpm=80.0)

    digest_base = lifecycle_stage.stimulus_source_params_digest(base)
    assert lifecycle_stage.stimulus_source_params_digest(same) == digest_base
    assert lifecycle_stage.stimulus_source_params_digest(different) != digest_base


def test_maturation_hook_records_stimulus_source_state(tmp_path, monkeypatch):
    stage_file = tmp_path / "stage.json"
    monkeypatch.setattr(lifecycle_stage, "STAGE_PATH", stage_file)

    before = lifecycle_stage.StageState(
        stage=lifecycle_stage.EMBODIED,
        born_at="2026-01-01T00:00:00+00:00",
    )
    lifecycle_stage.write_stage(before)

    feed = {"seed": 7}
    clock = StimulusSourceClock(lived_offset_seconds=10.0, clock=lambda: 0.0)
    clock.start()
    clock.begin_maturation(2.5)

    base_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    hook = _make_maturation_hook(clock, feed, 2.5, now=lambda: base_time)
    hook()

    after = lifecycle_stage.read_stage(stage_file)
    assert after.is_embodied
    assert after.stimulus_source_t_at_maturation == 12.5
    assert after.stimulus_source_seed == 7
    assert after.stimulus_source_params_digest == lifecycle_stage.stimulus_source_params_digest(StimulusSourceParams())
    assert after.maturation_bloom_ends_at == (base_time + timedelta(seconds=2.5)).isoformat()


def test_maturation_hook_does_not_raise_when_stage_missing(tmp_path, monkeypatch):
    stage_file = tmp_path / "stage.json"
    monkeypatch.setattr(lifecycle_stage, "STAGE_PATH", stage_file)

    clock = StimulusSourceClock(lived_offset_seconds=0.0, clock=lambda: 0.0)
    hook = _make_maturation_hook(
        clock, {}, 1.0, now=lambda: datetime.now(timezone.utc)
    )
    hook()  # no stage file to read; must not propagate an exception
