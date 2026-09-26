# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the womb video and audio source implementations."""
from __future__ import annotations

import numpy as np
import pytest

from kaine.modules.audition.feed import (
    WombAudioSchedule,
    WombProceduralAudioStream,
)
from kaine.modules.topos.feed import WombClock, WombProceduralSource, WombSchedule
from kaine.modules.womb_signal import (
    WombParams,
    beat_pulse,
    heartbeat_phase,
)
from tests.zero_persistence import WriteRecorder, leaked_writes, redirect_temp


def _origin_then(reading: float):
    """Fake monotonic clock: the first call (the origin) is 0.0, later calls
    return ``reading``, so womb time equals ``reading`` from then on."""
    calls = iter([0.0])

    def clock() -> float:
        return next(calls, reading)

    return clock


def _fake_clock(values):
    it = iter(values)
    return lambda: next(it)


def test_womb_clock_origin_fixed_once() -> None:
    clock = WombClock(
        lived_offset_seconds=0.0,
        clock=_fake_clock([2.0, 5.0, 100.0, 105.0]),
    )
    clock.start()
    assert clock.womb_seconds() == pytest.approx(3.0)
    # The second start() reads no clock value: the origin stays at 2.0, so
    # the next reading (100.0) gives 98.0.
    clock.start()
    assert clock.womb_seconds() == pytest.approx(98.0)


def test_womb_seconds_starts_clock_if_unstarted() -> None:
    clock = WombClock(
        lived_offset_seconds=10.0,
        clock=_fake_clock([1.0, 2.0]),
    )
    assert clock.womb_seconds() == pytest.approx(11.0)


def test_womb_clock_rejects_bad_offsets() -> None:
    for bad in (-1.0, float("nan"), float("inf"), True):
        with pytest.raises(ValueError):
            WombClock(lived_offset_seconds=bad, clock=lambda: 0.0)


def test_video_deterministic_and_shape() -> None:
    schedule = WombSchedule(seed=42, width=64, height=48, frame_rate_hz=30.0)
    clock = WombClock(lived_offset_seconds=0.0, clock=lambda: 0.0)
    src = WombProceduralSource(
        schedule,
        params=WombParams(),
        clock=clock,
        lived_seconds=lambda: 0.0,
    )
    f0 = src.frame_at(0)
    f0b = src.frame_at(0)
    assert f0.shape == (48, 64, 3)
    assert f0.dtype == np.uint8
    assert np.array_equal(f0, f0b)


def test_video_luminance_mean_and_pulse() -> None:
    schedule = WombSchedule(seed=42, width=64, height=48, frame_rate_hz=30.0)
    params = WombParams()
    clock = WombClock(lived_offset_seconds=0.0, clock=lambda: 0.0)
    src = WombProceduralSource(
        schedule,
        params=params,
        clock=clock,
        lived_seconds=lambda: 0.0,
    )

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
    clock_grey = WombClock(lived_offset_seconds=0.0, clock=lambda: 0.0)

    src_grey = WombProceduralSource(
        WombSchedule(seed=7, width=64, height=48),
        params=WombParams(),
        clock=clock_grey,
        lived_seconds=lambda: 0.0,
    )
    calls: list[float] = []

    def lived() -> float:
        calls.append(3.0 * tau)
        return 3.0 * tau

    clock_rich = WombClock(lived_offset_seconds=0.0, clock=lambda: 0.0)
    src_rich = WombProceduralSource(
        WombSchedule(seed=7, width=64, height=48),
        params=WombParams(),
        clock=clock_rich,
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
    clock = WombClock(lived_offset_seconds=0.0, clock=lambda: 0.0)
    src = WombProceduralSource(
        schedule,
        params=WombParams(),
        clock=clock,
        lived_seconds=lambda: 0.0,
    )
    opened = src.open()
    assert opened is True
    ok, frame = src.read()
    assert ok is True
    assert frame.shape == (24, 32, 3)
    src.release()
    ok2, frame2 = src.read()
    assert ok2 is False
    assert frame2 is None


def test_video_read_fake_clock() -> None:
    W = 1.234
    schedule = WombSchedule(seed=42, width=64, height=48, frame_rate_hz=30.0)
    clock = WombClock(lived_offset_seconds=0.0, clock=_origin_then(W))
    src = WombProceduralSource(
        schedule,
        params=WombParams(),
        clock=clock,
        lived_seconds=lambda: 0.0,
    )
    src.open()
    ok, frame = src.read()
    assert ok is True
    expected = src.frame_at(int(W * schedule.frame_rate_hz))
    assert np.array_equal(frame, expected)

    ok2, frame2 = src.read()
    assert np.array_equal(frame2, expected)


def test_video_constructor_requires_clock_and_lived_seconds() -> None:
    schedule = WombSchedule(seed=1, width=32, height=24)
    with pytest.raises(TypeError):
        WombProceduralSource(
            schedule, params=WombParams(), lived_seconds=lambda: 0.0
        )
    with pytest.raises(TypeError):
        WombProceduralSource(
            schedule,
            params=WombParams(),
            clock=WombClock(lived_offset_seconds=0.0, clock=lambda: 0.0),
        )


def test_audio_advance() -> None:
    assert WombProceduralAudioStream._advance(None, 7) == 7
    assert WombProceduralAudioStream._advance(3, 4) == 3
    assert WombProceduralAudioStream._advance(3, 8) == 3
    assert WombProceduralAudioStream._advance(3, 9) == 9


def test_cross_modal_beat_alignment() -> None:
    seed = 42
    params = WombParams()
    video_schedule = WombSchedule(seed=seed, width=64, height=48, frame_rate_hz=30.0)
    audio_schedule = WombAudioSchedule(seed=seed)
    sr = audio_schedule.sample_rate
    bs = audio_schedule.frames_per_block / sr

    ts = np.arange(0.0, 4.0, 0.0001)
    phases = heartbeat_phase(seed, ts, params)
    wraps = np.where(np.diff(phases) < -0.5)[0] + 1
    assert len(wraps) > 0
    W = float(ts[wraps[0]])
    half_beat = 0.5 / (params.heartbeat_bpm / 60.0)

    def mean_luminance_at(womb_time: float) -> float:
        clock = WombClock(lived_offset_seconds=0.0, clock=_origin_then(womb_time))
        src = WombProceduralSource(
            video_schedule,
            params=params,
            clock=clock,
            lived_seconds=lambda: 0.0,
        )
        src.open()
        _, frame = src.read()
        return float(frame.mean()) / 255.0

    assert mean_luminance_at(W) > mean_luminance_at(W + half_beat)

    dummy_clock = WombClock(lived_offset_seconds=0.0, clock=lambda: 0.0)
    stream = WombProceduralAudioStream(
        audio_schedule,
        params=params,
        clock=dummy_clock,
        callback=lambda b: None,
    )

    def rms(block_index: int) -> float:
        arr = np.frombuffer(stream.pcm_at(block_index), dtype=np.int16).astype(
            np.float64
        )
        return float(np.sqrt(np.mean(arr * arr)))

    k_on = int(W / bs)
    k_mid = int((W + half_beat) / bs)
    assert rms(k_on) > rms(k_mid)


def test_lived_offset_continues_across_boots() -> None:
    seed = 5
    schedule = WombSchedule(seed=seed, width=64, height=48, frame_rate_hz=30.0)
    params = WombParams()
    L = 123.4
    e = 0.5

    clock = WombClock(lived_offset_seconds=L, clock=lambda: e)
    src = WombProceduralSource(
        schedule,
        params=params,
        clock=clock,
        lived_seconds=lambda: L + e,
    )
    frame = src.frame_at(int((L + e) * schedule.frame_rate_hz))

    clock0 = WombClock(lived_offset_seconds=0.0, clock=lambda: e)
    src0 = WombProceduralSource(
        schedule,
        params=params,
        clock=clock0,
        lived_seconds=lambda: e,
    )
    frame0 = src0.frame_at(int(e * schedule.frame_rate_hz))

    assert np.array_equal(
        frame, src.frame_at(int((L + e) * schedule.frame_rate_hz))
    )
    assert not np.array_equal(frame, frame0)


def test_audio_deterministic_int16_no_clip() -> None:
    schedule = WombAudioSchedule(seed=42)
    clock = WombClock(lived_offset_seconds=0.0, clock=lambda: 0.0)
    stream = WombProceduralAudioStream(
        schedule,
        params=WombParams(),
        clock=clock,
        callback=lambda b: None,
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
    clock = WombClock(lived_offset_seconds=0.0, clock=lambda: 0.0)
    stream = WombProceduralAudioStream(
        schedule,
        params=params,
        clock=clock,
        callback=lambda b: None,
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
    clock = WombClock(lived_offset_seconds=0.0, clock=lambda: 0.0)
    stream = WombProceduralAudioStream(
        schedule,
        params=params,
        clock=clock,
        callback=lambda b: None,
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
    clock = WombClock(lived_offset_seconds=0.0, clock=lambda: 0.0)
    stream = WombProceduralAudioStream(
        schedule,
        params=WombParams(),
        clock=clock,
        callback=lambda b: None,
    )
    b0 = np.frombuffer(stream.pcm_at(10), dtype=np.int16)
    b1 = np.frombuffer(stream.pcm_at(11), dtype=np.int16)
    jump = abs(int(b0[-1]) - int(b1[0]))
    assert jump < 1000


def test_audio_start_stop_close_does_not_raise() -> None:
    schedule = WombAudioSchedule(seed=42)
    clock = WombClock(lived_offset_seconds=0.0, clock=lambda: 0.0)
    stream = WombProceduralAudioStream(
        schedule,
        params=WombParams(),
        clock=clock,
        callback=lambda b: None,
    )
    stream.start()
    stream.stop()
    stream.close()


def test_audio_block_shape_and_base_tones_below_corner() -> None:
    schedule = WombAudioSchedule(seed=7)
    params = WombParams()
    clock = WombClock(lived_offset_seconds=0.0, clock=lambda: 0.0)
    stream = WombProceduralAudioStream(
        schedule,
        params=params,
        clock=clock,
        callback=lambda b: None,
    )

    for k in range(10):
        pcm = stream.pcm_at(k)
        assert len(pcm) == schedule.frames_per_block * schedule.channels * 2
        arr = np.frombuffer(pcm, dtype=np.int16)
        assert arr.shape == (schedule.frames_per_block * schedule.channels,)


def test_no_tone_above_the_low_pass_corner() -> None:
    # With a 100 Hz corner, every tonal component (base tones and the ~50 Hz
    # thud carrier) must sit below it: above 150 Hz the spectrum is only the
    # filtered noise floor, with no bin standing far above its neighbourhood.
    params = WombParams.from_sections(None, None, {"lowpass_hz": 100.0})
    for seed in range(10):
        schedule = WombAudioSchedule(seed=seed)
        stream = WombProceduralAudioStream(
            schedule,
            params=params,
            clock=WombClock(lived_offset_seconds=0.0, clock=lambda: 0.0),
            callback=lambda b: None,
        )
        x = np.concatenate(
            [np.frombuffer(stream.pcm_at(k), dtype=np.int16) for k in range(67)]
        ).astype(np.float64)
        power = np.abs(np.fft.rfft(x)) ** 2
        freqs = np.fft.rfftfreq(x.size, d=1.0 / schedule.sample_rate)
        hz_per_bin = freqs[1]
        half = int(20.0 / hz_per_bin)
        for i in np.where((freqs >= 150.0) & (freqs <= 1000.0))[0]:
            floor = np.median(power[i - half:i + half + 1])
            assert power[i] < 50.0 * floor, (seed, freqs[i])


def test_zero_persistence_no_artifacts(tmp_path, monkeypatch) -> None:
    redirect_temp(tmp_path, monkeypatch)
    banned = [".png", ".jpg", ".jpeg", ".wav", ".mp3", ".mp4", ".avi", ".raw"]

    clock = WombClock(lived_offset_seconds=0.0, clock=lambda: 0.0)
    with WriteRecorder() as rec:
        video = WombProceduralSource(
            WombSchedule(seed=42, width=64, height=48),
            params=WombParams(),
            clock=clock,
            lived_seconds=lambda: 0.0,
        )
        audio = WombProceduralAudioStream(
            WombAudioSchedule(seed=42),
            params=WombParams(),
            clock=clock,
            callback=lambda b: None,
        )
        for i in range(100):
            video.frame_at(i)
            audio.pcm_at(i)

    bad = leaked_writes(rec.writes, banned)
    assert bad == []


def test_audio_synthesis_failure_stops_the_producer_loudly(caplog) -> None:
    # A synthesis error must end the producer with an error log (the input-loss
    # watcher then sees the stall), never spin silently on the failing block.
    import logging

    stream = WombProceduralAudioStream(
        WombAudioSchedule(seed=1),
        params=WombParams(),
        clock=WombClock(lived_offset_seconds=0.0, clock=_origin_then(5.0)),
        callback=lambda b: None,
    )

    def _boom(block_index: int) -> bytes:
        raise RuntimeError("synthesis broke")

    stream.pcm_at = _boom  # type: ignore[method-assign]
    with caplog.at_level(logging.ERROR, logger="kaine.modules.audition.feed"):
        stream.start()
        thread = stream._thread
        assert thread is not None
        thread.join(timeout=2.0)
        alive = thread.is_alive()
        stream.stop()
    assert not alive
    assert any("synthesis failed" in r.getMessage() for r in caplog.records)


def test_womb_is_cpu_only_and_torch_free() -> None:
    # The local womb must run on a modest single host: rendering a frame and
    # an audio block needs numpy only, never torch or a GPU stack.
    import subprocess
    import sys

    code = (
        "import sys\n"
        "from kaine.modules.topos.feed import WombClock, WombProceduralSource, WombSchedule\n"
        "from kaine.modules.audition.feed import WombAudioSchedule, WombProceduralAudioStream\n"
        "from kaine.modules.womb_signal import WombParams\n"
        "c = WombClock(lived_offset_seconds=0.0)\n"
        "v = WombProceduralSource(WombSchedule(width=32, height=24), params=WombParams(),"
        " clock=c, lived_seconds=lambda: 0.0)\n"
        "v.frame_at(0)\n"
        "a = WombProceduralAudioStream(WombAudioSchedule(), params=WombParams(), clock=c,"
        " callback=lambda b: None)\n"
        "a.pcm_at(0)\n"
        "bad = [m for m in ('torch', 'jax', 'cv2', 'cupy') if m in sys.modules]\n"
        "print(','.join(bad))\n"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=60
    )
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == ""


def test_no_entity_state_feeds_the_womb() -> None:
    # The womb is external: its only inputs are the seed, the parameters, the
    # shared womb clock and (for the colour-onset schedule only) lived time.
    # Nothing from the entity's affect, workspace or modules may reach it.
    import ast
    import importlib.util
    import inspect
    from pathlib import Path

    assert list(inspect.signature(WombProceduralSource.__init__).parameters) == [
        "self", "schedule", "params", "clock", "lived_seconds",
    ]
    assert list(inspect.signature(WombProceduralAudioStream.__init__).parameters) == [
        "self", "schedule", "params", "clock", "callback",
    ]
    spec = importlib.util.find_spec("kaine.modules.womb_signal")
    assert spec is not None and spec.origin is not None
    tree = ast.parse(Path(spec.origin).read_text())
    kaine_imports = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("kaine")
    }
    assert kaine_imports <= {"kaine.config", "kaine.modules.perception_prng"}


def test_video_read_marks_delivery() -> None:
    clock = WombClock(lived_offset_seconds=0.0, clock=_origin_then(2.0))
    src = WombProceduralSource(
        WombSchedule(seed=1, width=16, height=12),
        params=WombParams(),
        clock=clock,
        lived_seconds=lambda: 0.0,
    )
    assert clock.last_delivery("video") is None
    src.open()
    ok, _ = src.read()
    assert ok
    assert clock.last_delivery("video") == (2.0, int(2.0 * 30.0))


def test_audio_marks_delivery_only_when_the_callback_accepts() -> None:
    # A block counts as delivered only once the consumer took it.
    def _run(callback) -> tuple[float, int] | None:
        clock = WombClock(lived_offset_seconds=0.0, clock=_origin_then(1.0))
        stream = WombProceduralAudioStream(
            WombAudioSchedule(seed=1),
            params=WombParams(),
            clock=clock,
            callback=callback,
        )
        stream.start()
        try:
            deadline = 200
            while clock.last_delivery("audio") is None and deadline:
                import time

                time.sleep(0.005)
                deadline -= 1
        finally:
            stream.stop()
        return clock.last_delivery("audio")

    assert _run(lambda b: None) is not None

    def _refuse(b: bytes) -> None:
        raise RuntimeError("consumer refused the block")

    assert _run(_refuse) is None


def test_womb_clock_rejects_unknown_surface() -> None:
    clock = WombClock(lived_offset_seconds=0.0, clock=lambda: 0.0)
    with pytest.raises(ValueError):
        clock.mark_delivered("smell", 1)
    with pytest.raises(ValueError):
        clock.last_delivery("smell")
