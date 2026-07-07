# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Systems test: live perception → parent module entry point → bus event.

Fully fakeredis-backed. Verifies that:
  - LiveMicrophone's flushed utterance reaches Audition.process_audio
    which publishes audition.transcription on audition.out.
  - LiveCamera's polled frame reaches Topos.process_frame which publishes
    topos.report on topos.out.
"""
from __future__ import annotations

import asyncio
import struct

import pytest

from kaine.modules.audition.live import LiveMicConfig, LiveMicrophone
from kaine.modules.audition.module import Audition
from kaine.modules.audition.stt_client import FakeSTTClient
from kaine.modules.audition.emotion import FakeEmotionClassifier
from kaine.modules.topos.live import LiveCamera, LiveCameraConfig
from kaine.modules.topos.module import Topos

from tests.systems._harness import SubsystemHarness


# --- audio path ------------------------------------------------------


class _ScriptedSpeechStream:
    def __init__(self, *, callback):
        self._cb = callback
        self._stop = asyncio.Event()
        self._task = None

    def start(self):
        loop = asyncio.get_event_loop()
        self._task = loop.create_task(self._feed())

    def stop(self):
        self._stop.set()

    def close(self):
        return

    async def _feed(self):
        # 480 samples = 30 ms @ 16 kHz.
        loud = struct.pack(
            "<480h",
            *([6000 if i % 2 == 0 else -6000 for i in range(480)]),
        )
        silent = struct.pack("<480h", *([0] * 480))
        seq = [loud] * 8 + [silent] * 4
        for frame in seq:
            if self._stop.is_set():
                return
            self._cb(frame)
            await asyncio.sleep(0.003)


class _ScriptedVAD:
    def __init__(self):
        self._i = 0

    def is_speech(self, frame, sample_rate):
        # speech for first 8 frames, then silence
        v = self._i < 8
        self._i += 1
        return v


@pytest.mark.asyncio
async def test_live_microphone_drives_audition_subsystem_end_to_end():
    async with SubsystemHarness() as h:
        live_mic = LiveMicrophone(
            sink=lambda *a, **kw: None,  # patched below
            config=LiveMicConfig(
                sample_rate=16000,
                vad_frame_ms=30,
                min_utterance_ms=60,
                max_utterance_ms=500,
                silence_hangover_ms=60,
                desired_state_poll_ms=20,
            ),
            state_writer=lambda active: None,
            desired_state_reader=lambda: True,
            stream_factory=lambda **kw: _ScriptedSpeechStream(callback=kw["callback"]),
            vad_factory=_ScriptedVAD,
        )
        ai = Audition(
            h.bus,
            stt_client=FakeSTTClient(responses=["hello operator"]),
            emotion_classifier=FakeEmotionClassifier(),
            capture_enabled=True,
            live_microphone=live_mic,
        )
        # Rebind the live mic's sink to the actual Audition.process_audio
        # now that ai exists.
        live_mic._sink = ai.process_audio  # test-only seam

        await h.register(ai)
        events = await h.collect(
            "audition.out", count=1, timeout=3.0, filter_type="audition.transcription"
        )
        assert events, "live mic → Audition → bus pipeline produced no event"
        assert events[0].payload.get("source_label") == "live_mic"
        assert events[0].payload.get("text") == "hello operator"


# --- video path ------------------------------------------------------


class _StubEncoder:
    model_id = "fake/encoder"

    async def load(self):
        return

    async def encode(self, image):
        return [0.1, 0.2, 0.3]

    async def shutdown(self):
        return


class _ScriptedVideoSource:
    def __init__(self, *, device, width, height):
        self._frames = [f"f-{i}" for i in range(20)]
        self._i = 0
        self.device = device
        self.released = False

    def open(self):
        return True

    def read(self):
        if self._i >= len(self._frames):
            return False, None
        f = self._frames[self._i]
        self._i += 1
        return True, f

    def release(self):
        self.released = True


@pytest.mark.asyncio
async def test_live_camera_drives_topos_subsystem_end_to_end():
    async with SubsystemHarness() as h:
        live_cam = LiveCamera(
            sink=lambda image: None,  # patched below
            config=LiveCameraConfig(
                capture_interval_s=0.02,
                warmup_frames=0,
                desired_state_poll_ms=20,
            ),
            state_writer=lambda active: None,
            desired_state_reader=lambda: True,
            source_factory=lambda device, *, width, height: _ScriptedVideoSource(
                device=device, width=width, height=height
            ),
            bgr_to_rgb=lambda frame: ("rgb", frame),
        )
        topos = Topos(
            h.bus,
            encoder=_StubEncoder(),
            capture_enabled=True,
            live_camera=live_cam,
        )
        live_cam._sink = topos.process_frame  # test-only seam

        await h.register(topos)
        events = await h.collect(
            "topos.out", count=1, timeout=3.0, filter_type="topos.report"
        )
        assert events, "live camera → Topos → bus pipeline produced no event"
        assert events[0].payload.get("encoder_model_id") == "fake/encoder"
