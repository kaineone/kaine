# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the womb video and audio source implementations."""
from __future__ import annotations

import numpy as np

from kaine.modules.audition.feed import (
    WombAudioSchedule,
    WombProceduralAudioStream,
)
from kaine.modules.topos.feed import WombProceduralSource, WombSchedule
from kaine.modules.womb_signal import WombParams, beat_pulse, heartbeat_phase
from tests.zero_persistence import WriteRecorder, leaked_writes, redirect_temp


def test_video_deterministic_and_shape() -> None:
    schedule = WombSchedule(seed=42, width=64, height=48, frame_rate_hz=30.0)
    src = WombProceduralSource(schedule, params=WombParams())
    f0 = src.frame_at(0)
    f0b = src.frame_at(0)
    assert f0.shape == (48, 64, 3)
    assert f0.dtype == np.uint8
    assert np.array_equal(f0, f0b)


def test_video_luminance_mean_and_pulse() -> None:
    schedule = WombSchedule(seed=42, width=64, height=48, frame_rate_hz=30.0)
    params = WombParams()
    src = WombProceduralSource(schedule, params=params)

    onset_i = next(
        i
        for i in range(200)
        if beat_pulse(heartbeat_phase(42, i / 30.0, params)) > 0.9
    )
    mid_i = next(
        i
        for i in range(200)
        if beat_pulse(heartbeat_phase(42, i / 30.0, params)) < 0.1
    )

    onset_mean = src.frame_at(onset_i).mean() / 255.0
    mid_mean = src.frame_at(mid_i).mean() / 255.0
    assert abs(mid_mean - params.luminance_mean) < 0.05
    assert onset_mean > mid_mean


def test_video_colour_saturation_ramp() -> None:
    tau = WombParams().colour_ramp_seconds

    src_grey = WombProceduralSource(
        WombSchedule(seed=7, width=64, height=48),
        params=WombParams(),
        lived_seconds=lambda: 0.0,
    )
    calls: list[float] = []

    def lived() -> float:
        calls.append(3.0 * tau)
        return 3.0 * tau

    src_rich = WombProceduralSource(
        WombSchedule(seed=7, width=64, height=48),
        params=WombParams(),
        lived_seconds=lived,
    )

    grey = src_grey.frame_at(10)
    rich = src_rich.frame_at(10)

    def mean_channel_spread(img: np.ndarray) -> float:
        return float(np.mean(np.std(img / 255.0, axis=2)))

    assert mean_channel_spread(grey) < 0.005
    assert mean_channel_spread(rich) > 0.02
    assert calls == [3.0 * tau]


def test_video_open_read_release_protocol() -> None:
    schedule = WombSchedule(seed=1, width=32, height=24)
    src = WombProceduralSource(schedule, params=WombParams())
    assert src.open() is True
    ok, frame = src.read()
    assert ok is True
    assert frame.shape == (24, 32, 3)
    src.release()
    ok2, frame2 = src.read()
    assert ok2 is False
    assert frame2 is None


def test_audio_deterministic_int16_no_clip() -> None:
    schedule = WombAudioSchedule(seed=42)
    stream = WombProceduralAudioStream(
        schedule, params=WombParams(), callback=lambda b: None
    )
    pcm_a = stream.pcm_at(0)
    pcm_b = stream.pcm_at(0)
    assert pcm_a == pcm_b
    arr = np.frombuffer(pcm_a, dtype=np.int16)
    assert arr.max() <= 32767
    assert arr.min() >= -32767
    # With the fixed headroom it stays well below clipping.
    assert arr.max() < 32000
    assert arr.min() > -32000


def test_audio_lowpass_energy() -> None:
    schedule = WombAudioSchedule(seed=42)
    params = WombParams()
    stream = WombProceduralAudioStream(
        schedule, params=params, callback=lambda b: None
    )
    sr = schedule.sample_rate
    n_blocks = int(2.0 * sr / schedule.frames_per_block)
    pcm = np.concatenate(
        [
            np.frombuffer(stream.pcm_at(i), dtype=np.int16)
            for i in range(n_blocks)
        ]
    )
    fft = np.fft.rfft(pcm)
    power = np.abs(fft) ** 2
    freqs = np.fft.rfftfreq(len(pcm), d=1.0 / sr)
    below = power[freqs < params.lowpass_hz].sum()
    total = power.sum()
    assert total > 0.0
    assert below / total >= 0.90


def test_audio_beat_alignment() -> None:
    schedule = WombAudioSchedule(seed=42)
    params = WombParams()
    stream = WombProceduralAudioStream(
        schedule, params=params, callback=lambda b: None
    )
    sr = schedule.sample_rate
    duration = 4.0
    n_blocks = int(duration * sr / schedule.frames_per_block)
    pcm = np.concatenate(
        [
            np.frombuffer(stream.pcm_at(i), dtype=np.int16)
            for i in range(n_blocks)
        ]
    )
    t = np.arange(len(pcm)) / sr
    phase = heartbeat_phase(42, t, params)
    dphase = np.diff(phase)
    onsets = np.where(dphase < -0.5)[0] + 1

    assert len(onsets) >= 2
    win = int(0.05 * sr)  # ±50 ms
    for onset in onsets:
        if onset - win < 0 or onset + win >= len(pcm):
            continue
        window = pcm[onset - win : onset + win]
        peak_offset = int(np.argmax(np.abs(window))) - win
        assert abs(peak_offset) <= win


def test_audio_continuity_across_block_boundary() -> None:
    schedule = WombAudioSchedule(seed=42)
    stream = WombProceduralAudioStream(
        schedule, params=WombParams(), callback=lambda b: None
    )
    b0 = np.frombuffer(stream.pcm_at(10), dtype=np.int16)
    b1 = np.frombuffer(stream.pcm_at(11), dtype=np.int16)
    jump = abs(int(b0[-1]) - int(b1[0]))
    assert jump < 1000


def test_audio_start_stop_close_does_not_raise() -> None:
    schedule = WombAudioSchedule(seed=42)
    stream = WombProceduralAudioStream(
        schedule, params=WombParams(), callback=lambda b: None
    )
    stream.start()
    stream.stop()
    stream.close()


def test_zero_persistence_no_artifacts(tmp_path, monkeypatch) -> None:
    redirect_temp(tmp_path, monkeypatch)
    banned = [".png", ".jpg", ".jpeg", ".wav", ".mp3", ".mp4", ".avi", ".raw"]

    with WriteRecorder() as rec:
        video = WombProceduralSource(
            WombSchedule(seed=42, width=64, height=48),
            params=WombParams(),
        )
        audio = WombProceduralAudioStream(
            WombAudioSchedule(seed=42),
            params=WombParams(),
            callback=lambda b: None,
        )
        for i in range(100):
            video.frame_at(i)
            audio.pcm_at(i)

    bad = leaked_writes(rec.writes, banned)
    assert bad == []
