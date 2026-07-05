# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""LiveMicrophone unit tests with FakeMicrophoneStream + FakeVAD.

No real audio hardware. No disk writes. Verifies the utterance
segmenter respects min/max/hangover thresholds and never writes a WAV
file (only in-memory BytesIO via wave.open)."""
from __future__ import annotations

import asyncio
import io
import os
import struct
import wave
from typing import Any, Callable

import pytest

from kaine.modules.audition.live import (
    LiveMicConfig,
    LiveMicrophone,
    encode_wav,
    _RMSVAD,
)


def _silent_pcm(samples: int) -> bytes:
    return struct.pack(f"<{samples}h", *([0] * samples))


def _loud_pcm(samples: int, amp: int = 8000) -> bytes:
    pattern = [amp if i % 2 == 0 else -amp for i in range(samples)]
    return struct.pack(f"<{samples}h", *pattern)


class FakeMicrophoneStream:
    """Implements the _AudioStream protocol but feeds scripted PCM
    frames into the callback at controlled cadence."""

    def __init__(
        self,
        frames: list[bytes],
        *,
        callback: Callable[[bytes], None],
        feed_interval_s: float = 0.005,
    ) -> None:
        self._frames = list(frames)
        self._callback = callback
        self._feed_interval_s = feed_interval_s
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self.started = False
        self.stopped = False
        self.closed = False

    def start(self) -> None:
        self.started = True
        # Schedule feed task on the running loop.
        loop = asyncio.get_event_loop()
        self._task = loop.create_task(self._feed())

    def stop(self) -> None:
        self.stopped = True
        self._stop.set()

    def close(self) -> None:
        self.closed = True

    async def _feed(self) -> None:
        for frame in self._frames:
            if self._stop.is_set():
                return
            self._callback(frame)
            await asyncio.sleep(self._feed_interval_s)


class FakeVAD:
    def __init__(self, schedule: list[bool]) -> None:
        self._schedule = list(schedule)
        self._i = 0

    def is_speech(self, frame: bytes, sample_rate: int) -> bool:
        if not self._schedule:
            return False
        v = self._schedule[self._i % len(self._schedule)]
        self._i += 1
        return v


@pytest.mark.asyncio
async def test_encode_wav_returns_bytes_no_file_written(tmp_path):
    pcm = _silent_pcm(1600)  # 100 ms @ 16k
    cwd_before = set(os.listdir(tmp_path))
    wav = encode_wav(pcm, sample_rate=16000, channels=1)
    cwd_after = set(os.listdir(tmp_path))
    assert isinstance(wav, bytes)
    assert wav[:4] == b"RIFF"
    assert cwd_before == cwd_after  # nothing written to tmp_path


def test_encode_wav_decodes_round_trip():
    pcm = _loud_pcm(800)
    wav = encode_wav(pcm, sample_rate=16000, channels=1)
    with wave.open(io.BytesIO(wav), "rb") as wf:
        assert wf.getframerate() == 16000
        assert wf.getnchannels() == 1
        assert wf.readframes(wf.getnframes()) == pcm


def test_rms_vad_classifies_silence_and_speech():
    vad = _RMSVAD(threshold=500)
    silent = _silent_pcm(160)
    loud = _loud_pcm(160, amp=4000)
    assert vad.is_speech(silent, 16000) is False
    assert vad.is_speech(loud, 16000) is True


@pytest.mark.asyncio
async def test_live_mic_flushes_utterance_to_sink_after_silence():
    # Build a sequence: 6 frames silent (skip), 5 frames speech,
    # 3 frames silent (trigger flush).
    sample_rate = 16000
    frame_ms = 30
    samples_per_frame = sample_rate * frame_ms // 1000
    silence_frame = _silent_pcm(samples_per_frame)
    speech_frame = _loud_pcm(samples_per_frame)
    schedule = [False] * 6 + [True] * 5 + [False] * 3
    pcm_frames = [silence_frame] * 6 + [speech_frame] * 5 + [silence_frame] * 3

    sink_calls: list[tuple[bytes, int, str]] = []

    async def sink(wav: bytes, sr: int, label: str):
        sink_calls.append((wav, sr, label))

    cfg = LiveMicConfig(
        sample_rate=sample_rate,
        vad_frame_ms=frame_ms,
        min_utterance_ms=30,
        silence_hangover_ms=frame_ms * 2,
        max_utterance_ms=1000,
        desired_state_poll_ms=50,
    )

    mic = LiveMicrophone(
        sink,
        config=cfg,
        state_writer=lambda active: None,
        desired_state_reader=lambda: True,
        stream_factory=lambda **kw: FakeMicrophoneStream(
            pcm_frames, callback=kw["callback"], feed_interval_s=0.002
        ),
        vad_factory=lambda: FakeVAD(schedule),
    )
    await mic.initialize()
    try:
        # Give the supervisor a moment to consume + flush.
        for _ in range(40):
            await asyncio.sleep(0.05)
            if sink_calls:
                break
    finally:
        await mic.shutdown()

    assert sink_calls, "LiveMicrophone never flushed an utterance"
    wav, sr, label = sink_calls[0]
    assert sr == sample_rate
    assert label == "live_mic"
    assert wav[:4] == b"RIFF"


@pytest.mark.asyncio
async def test_live_mic_drops_utterance_below_min_duration():
    sample_rate = 16000
    frame_ms = 30
    samples = sample_rate * frame_ms // 1000
    silence = _silent_pcm(samples)
    speech = _loud_pcm(samples)
    # 1 frame speech then 3 silent → below min_utterance_ms.
    schedule = [False, True, False, False, False]
    pcm_frames = [silence, speech, silence, silence, silence]

    sink_calls: list[Any] = []

    async def sink(wav, sr, label):
        sink_calls.append((wav, sr, label))

    cfg = LiveMicConfig(
        sample_rate=sample_rate,
        vad_frame_ms=frame_ms,
        min_utterance_ms=200,
        silence_hangover_ms=frame_ms * 2,
        max_utterance_ms=1000,
        desired_state_poll_ms=50,
    )
    mic = LiveMicrophone(
        sink,
        config=cfg,
        state_writer=lambda active: None,
        desired_state_reader=lambda: True,
        stream_factory=lambda **kw: FakeMicrophoneStream(
            pcm_frames, callback=kw["callback"], feed_interval_s=0.002
        ),
        vad_factory=lambda: FakeVAD(schedule),
    )
    await mic.initialize()
    try:
        for _ in range(20):
            await asyncio.sleep(0.05)
    finally:
        await mic.shutdown()

    # Short utterance must be discarded.
    assert sink_calls == []


@pytest.mark.asyncio
async def test_live_mic_calls_state_writer_on_start_and_stop():
    sample_rate = 16000
    frame_ms = 30
    samples = sample_rate * frame_ms // 1000
    silence = _silent_pcm(samples)
    schedule = [False] * 20
    pcm = [silence] * 20

    states: list[bool] = []
    mic = LiveMicrophone(
        sink=lambda w, s, l: asyncio.sleep(0),
        config=LiveMicConfig(
            sample_rate=sample_rate,
            vad_frame_ms=frame_ms,
            desired_state_poll_ms=20,
        ),
        state_writer=lambda active: states.append(bool(active)),
        desired_state_reader=lambda: True,
        stream_factory=lambda **kw: FakeMicrophoneStream(
            pcm, callback=kw["callback"], feed_interval_s=0.005
        ),
        vad_factory=lambda: FakeVAD(schedule),
    )
    await mic.initialize()
    # Wait until the supervisor reports active.
    for _ in range(30):
        if any(states):
            break
        await asyncio.sleep(0.05)
    await mic.shutdown()
    assert True in states
    assert False in states


@pytest.mark.asyncio
async def test_live_mic_respects_desired_state_off():
    """Operator commanded off → supervisor never opens the stream."""
    factory_calls = []

    def factory(**kw):
        factory_calls.append(kw)
        return FakeMicrophoneStream([], callback=kw["callback"])

    mic = LiveMicrophone(
        sink=lambda w, s, l: asyncio.sleep(0),
        config=LiveMicConfig(desired_state_poll_ms=20),
        state_writer=lambda active: None,
        desired_state_reader=lambda: False,
        stream_factory=factory,
        vad_factory=lambda: FakeVAD([False]),
    )
    await mic.initialize()
    await asyncio.sleep(0.2)
    await mic.shutdown()
    assert factory_calls == []
