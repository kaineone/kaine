# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the womb birth transition."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

from kaine.boot import _install_shared_womb_clock
from kaine.lifecycle import stage as lifecycle_stage
from kaine.lifecycle.gate_runner import MaturationGateRunner
from kaine.lifecycle.maturation_gate import MaturationConfig
from kaine.modules.audition.feed import WombProceduralAudioStream
from kaine.modules.topos.feed import (
    BIRTH_BLOOM_PEAK,
    WombClock,
    WombProceduralSource,
)
from tests.test_gate_birth_while_frozen import (
    _fresh_gestation_state,
    _make_bus,
    _make_clock,
    _make_registry,
)


@pytest.fixture
def fake_clock():
    class _FakeClock:
        def __init__(self):
            self._t = 0.0

        def __call__(self):
            return self._t

        def advance(self, dt: float) -> None:
            self._t += dt

    return _FakeClock()


@pytest.fixture
def video_schedule():
    return SimpleNamespace(
        seed=12345,
        width=32,
        height=24,
        frame_rate_hz=10.0,
    )


@pytest.fixture
def video_params():
    return SimpleNamespace(
        luminance_mean=0.05,
        luminance_contrast=0.02,
        luminance_pulse_depth=0.2,
        maternal_state_hue_gain=1.0,
    )


@pytest.fixture
def patched_video_signal(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "kaine.modules.womb_signal.maternal_state",
        lambda seed, t, p: (0.0, 0.0),
    )
    monkeypatch.setattr(
        "kaine.modules.womb_signal.flow_phase",
        lambda seed, t, p: 0.0,
    )
    monkeypatch.setattr(
        "kaine.modules.womb_signal.heartbeat_phase",
        lambda seed, t, p: 0.0,
    )
    monkeypatch.setattr(
        "kaine.modules.womb_signal.beat_pulse",
        lambda phase: 1.0,
    )
    monkeypatch.setattr(
        "kaine.modules.womb_signal.colour_saturation",
        lambda lived, p: 0.0,
    )
    monkeypatch.setattr(
        "kaine.modules.womb_signal.maternal_hue",
        lambda valence: 0.0,
    )


@pytest.fixture
def audio_schedule():
    return SimpleNamespace(
        frames_per_block=256,
        sample_rate=16000,
        channels=1,
        seed=1,
    )


@pytest.fixture
def audio_params():
    return SimpleNamespace(lowpass_hz=200.0)


@pytest.fixture
def patched_audio_signal(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        "kaine.modules.womb_signal.lowpassed_noise",
        lambda seed, idx, n, sr, lp: np.zeros(n, dtype=np.float64),
    )
    monkeypatch.setattr(
        "kaine.modules.womb_signal.heartbeat_phase",
        lambda seed, t, p: 0.0,
    )
    monkeypatch.setattr(
        "kaine.modules.womb_signal.beat_pulse",
        lambda phase: 0.0,
    )


def test_birth_progress_none_before_birth(fake_clock):
    clock = WombClock(lived_offset_seconds=0.0, clock=fake_clock)
    assert clock.birth_progress() is None
    assert not clock.born()


def test_birth_progress_advances_and_clamps(fake_clock):
    clock = WombClock(lived_offset_seconds=0.0, clock=fake_clock)
    clock.begin_birth(5.0)
    assert clock.birth_progress() == pytest.approx(0.0)

    fake_clock.advance(2.5)
    assert clock.birth_progress() == pytest.approx(0.5)

    fake_clock.advance(10.0)
    assert clock.birth_progress() == pytest.approx(1.0)
    assert clock.born()


def test_begin_birth_is_one_shot(fake_clock):
    clock = WombClock(lived_offset_seconds=0.0, clock=fake_clock)
    clock.begin_birth(5.0)
    fake_clock.advance(2.5)

    clock.begin_birth(1.0)
    assert clock.birth_progress() == pytest.approx(0.5)


def test_mark_born_short_circuits():
    clock = WombClock(lived_offset_seconds=0.0, clock=lambda: 0.0)
    clock.mark_born()
    assert clock.birth_progress() == 1.0
    assert clock.born()
    clock.begin_birth(5.0)
    assert clock.birth_progress() == 1.0


@pytest.mark.parametrize(
    "duration",
    [0.0, -1.0, float("nan"), 31.0],
)
def test_begin_birth_rejects_invalid_durations(duration):
    clock = WombClock(lived_offset_seconds=0.0, clock=lambda: 0.0)
    with pytest.raises(ValueError):
        clock.begin_birth(duration)


def test_video_frame_birth_progress_none_identical(
    video_schedule, video_params, patched_video_signal
):
    clock = WombClock(lived_offset_seconds=0.0, clock=lambda: 0.0)
    source = WombProceduralSource(
        video_schedule,
        params=video_params,
        clock=clock,
        lived_seconds=lambda: 0.0,
    )
    source.open()
    f_none = source.frame_at(0, birth_progress=None)
    f_omit = source.frame_at(0)
    assert np.array_equal(f_none, f_omit)


def test_video_frame_blooms_and_stays_bounded(
    video_schedule, video_params, patched_video_signal
):
    clock = WombClock(lived_offset_seconds=0.0, clock=lambda: 0.0)
    source = WombProceduralSource(
        video_schedule,
        params=video_params,
        clock=clock,
        lived_seconds=lambda: 0.0,
    )
    source.open()
    f0 = source.frame_at(0, birth_progress=0.0)
    f9 = source.frame_at(0, birth_progress=0.9)
    assert f9.mean() > f0.mean()
    assert f9.max() <= 255 * BIRTH_BLOOM_PEAK + 1


def test_video_read_stops_after_birth(
    video_schedule, video_params, patched_video_signal
):
    clock = WombClock(lived_offset_seconds=0.0, clock=lambda: 0.0)
    source = WombProceduralSource(
        video_schedule,
        params=video_params,
        clock=clock,
        lived_seconds=lambda: 0.0,
    )
    source.open()
    ok, frame = source.read()
    assert ok
    last = clock.last_delivery("video")

    clock.mark_born()
    assert source.read() == (False, None)
    assert clock.last_delivery("video") == last


def test_audio_pcm_birth_progress_none_identical(
    audio_schedule, audio_params, patched_audio_signal
):
    clock = WombClock(lived_offset_seconds=0.0, clock=lambda: 0.0)
    stream = WombProceduralAudioStream(
        audio_schedule,
        params=audio_params,
        clock=clock,
        callback=lambda pcm: None,
    )
    pcm_none = stream.pcm_at(0, birth_progress=None)
    pcm_omit = stream.pcm_at(0)
    assert pcm_none == pcm_omit


def test_audio_pcm_fades_with_birth_progress(
    audio_schedule, audio_params, patched_audio_signal
):
    clock = WombClock(lived_offset_seconds=0.0, clock=lambda: 0.0)
    stream = WombProceduralAudioStream(
        audio_schedule,
        params=audio_params,
        clock=clock,
        callback=lambda pcm: None,
    )
    full = np.frombuffer(
        stream.pcm_at(0, birth_progress=0.0), dtype=np.int16
    )
    half = np.frombuffer(
        stream.pcm_at(0, birth_progress=0.5), dtype=np.int16
    )
    rms_full = np.sqrt(np.mean(full.astype(np.float64) ** 2))
    rms_half = np.sqrt(np.mean(half.astype(np.float64) ** 2))
    assert rms_full > 0
    assert rms_half == pytest.approx(rms_full * 0.5, rel=0.05)


def test_audio_producer_stops_after_birth(
    audio_schedule, audio_params, patched_audio_signal
):
    times = [0.0]
    lock = threading.Lock()

    def monotonic() -> float:
        with lock:
            times[0] += 0.001
            return times[0]

    clock = WombClock(lived_offset_seconds=0.0, clock=monotonic)
    clock.start()

    delivered: list[bytes] = []

    def callback(pcm: bytes) -> None:
        delivered.append(pcm)

    stream = WombProceduralAudioStream(
        audio_schedule,
        params=audio_params,
        clock=clock,
        callback=callback,
    )
    stream.start()

    for _ in range(200):
        if delivered:
            break
        time.sleep(0.005)

    assert delivered, "no block delivered before birth"

    clock.mark_born()
    thread = stream._thread
    if thread is not None:
        thread.join(timeout=2.0)
        assert not thread.is_alive()

    stream.stop()
    final_count = len(delivered)
    time.sleep(0.05)
    assert len(delivered) == final_count


@pytest.mark.asyncio
async def test_gate_runner_calls_birth_hook_once_after_embodied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("KAINE_MUNDUS_OPERATOR_APPROVED", "1")
    readout = {
        "endogenous_self_sustain": True,
        "entrain_then_autonomy": True,
        "hrv_variability": 0.5,
        "womb_prediction_error": 0.1,
        "return_to_baseline_seconds": 10.0,
    }
    published: list[Any] = []
    bus = _make_bus(published=published, readout=readout, sleep_count=1)
    state = _fresh_gestation_state(tmp_path)
    runner = MaturationGateRunner(
        bus=bus,
        config=MaturationConfig(
            enabled=True,
            min_sleep_cycles=1,
            min_consolidation_passes=1,
            min_lived_seconds=0,
            gate_cadence_seconds=0.01,
        ),
        registry=_make_registry(
            consolidation_passes=1,
            mundus_enabled=True,
            mundus_approved=True,
            mundus_reachable=True,
        ),
        entity_clock=_make_clock(),
        stage_state=state,
        staging_enabled=True,
        womb_feed_configured=True,
    )
    runner.set_pause_sources(paused_seconds=lambda: 0.0, is_paused=lambda: False)

    calls: list[Any] = []

    def hook() -> None:
        calls.append(lifecycle_stage.read_stage(lifecycle_stage.STAGE_PATH))

    runner.set_birth_hook(hook)

    await runner._evaluate_once()
    await runner._evaluate_once()

    assert runner.stage.is_embodied
    assert len(calls) == 1
    assert calls[0].is_embodied


@pytest.mark.asyncio
async def test_gate_runner_raising_birth_hook_does_not_stop_birth(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("KAINE_MUNDUS_OPERATOR_APPROVED", "1")
    readout = {
        "endogenous_self_sustain": True,
        "entrain_then_autonomy": True,
        "hrv_variability": 0.5,
        "womb_prediction_error": 0.1,
        "return_to_baseline_seconds": 10.0,
    }
    published: list[Any] = []
    bus = _make_bus(published=published, readout=readout, sleep_count=1)
    state = _fresh_gestation_state(tmp_path)
    runner = MaturationGateRunner(
        bus=bus,
        config=MaturationConfig(
            enabled=True,
            min_sleep_cycles=1,
            min_consolidation_passes=1,
            min_lived_seconds=0,
            gate_cadence_seconds=0.01,
        ),
        registry=_make_registry(
            consolidation_passes=1,
            mundus_enabled=True,
            mundus_approved=True,
            mundus_reachable=True,
        ),
        entity_clock=_make_clock(),
        stage_state=state,
        staging_enabled=True,
        womb_feed_configured=True,
    )
    runner.set_pause_sources(paused_seconds=lambda: 0.0, is_paused=lambda: False)

    def bad_hook() -> None:
        raise RuntimeError("birth hook failed")

    runner.set_birth_hook(bad_hook)

    await runner._evaluate_once()
    await runner._evaluate_once()

    assert runner.stage.is_embodied


def test_boot_clock_marked_born_when_stage_embodied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "stage.json"
    monkeypatch.setattr("kaine.lifecycle.stage.STAGE_PATH", path)
    lifecycle_stage.write_stage(
        lifecycle_stage.StageState(stage="embodied"), path
    )
    feed: dict[str, Any] = {}
    _install_shared_womb_clock(feed, None, None, stage_path=path)
    assert feed["_shared_womb_clock"].born()


def test_boot_clock_not_born_when_stage_gestating(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "stage.json"
    monkeypatch.setattr("kaine.lifecycle.stage.STAGE_PATH", path)
    lifecycle_stage.write_stage(
        lifecycle_stage.StageState(stage="gestation"), path
    )
    feed: dict[str, Any] = {}
    _install_shared_womb_clock(feed, None, None, stage_path=path)
    assert not feed["_shared_womb_clock"].born()


@pytest.mark.parametrize("bad", [0.0, -1.0, 31.0])
def test_birth_transition_seconds_is_bounded(bad) -> None:
    from kaine.modules.womb_signal import WombParams

    with pytest.raises(ValueError):
        WombParams.from_sections({"birth_transition_seconds": bad}, None, None)
    assert WombParams.from_sections(None, None, None).birth_transition_seconds == 5.0
