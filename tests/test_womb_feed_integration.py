# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""End-to-end proof that the WOMB perception feed actually delivers.

Regression guard for the "awake but senseless" boot: with
``[perception_feed].mode = "womb"`` and the perception module enabled, the
entity's vision (Topos) and hearing (Audition) publish real events when the
virtual locus is selected. This harness wires the same locus-gated capture
supervisors against an in-memory bus, selects the virtual feed via
``perception_state.select_virtual_feed()``, and asserts that within a bounded
wait visual events land on ``topos.out`` and auditory events on
``audition.out`` — deterministically driven by the womb source.

Only the encoder / STT / emotion collaborators are faked (heavy models, not the
thing under test). The womb sources, the LiveCamera/LiveMicrophone supervisors,
the BGR->RGB conversion, the VAD/segmentation, and the locus gate are all REAL.
"""
from __future__ import annotations

import asyncio

import pytest

from kaine import perception_state
from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.modules.audition import (
    Audition,
    FakeEmotionClassifier,
    FakeSTTClient,
)
from kaine.modules.audition.live import LiveMicConfig
from kaine.modules.perception.module import PerceptionLocus
from kaine.modules.topos.live import LiveCameraConfig
from kaine.modules.topos.module import Topos


class _FakeEncoder:
    """Minimal Topos encoder double — no DINOv2 download, deterministic latent."""

    model_id = "fake/encoder-integration"
    latent_dim = 4

    def __init__(self) -> None:
        self.calls = 0

    async def load(self) -> None:  # noqa: D401
        return None

    async def shutdown(self) -> None:
        return None

    async def encode(self, image):  # noqa: ARG002
        # Vary the latent slightly per call so change-detection has something to
        # see; the salience path still publishes a topos.report every frame.
        self.calls += 1
        return [float(self.calls % 7), 0.0, 0.0, 0.0]


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield bus
    await bus.close()


@pytest.fixture
def womb_clock():
    from kaine.modules.topos.feed import WombClock

    return WombClock(lived_offset_seconds=0.0)


@pytest.fixture
def virtual_feed_state(tmp_path, monkeypatch):
    """Point perception_state at temp files and select the virtual feed exactly
    as ``build_registry`` now does for a configured seeded/playlist/womb feed."""
    desired = tmp_path / "desired.json"
    runtime = tmp_path / "runtime.json"
    monkeypatch.setattr(perception_state, "DESIRED_PATH", desired)
    monkeypatch.setattr(perception_state, "RUNTIME_PATH", runtime)
    state = perception_state.select_virtual_feed()
    # Precondition: the boot translation put us in the virtual locus with both
    # modalities desired — the state the locus-gated supervisors need.
    assert state.locus == "virtual"
    assert state.video_live_desired is True
    assert state.audio_live_desired is True
    return desired


def _make_topos(bus: AsyncBus, clock) -> Topos:
    # Womb video source factory (mirror of what boot injects in womb mode).
    from kaine.modules.topos.feed import WombProceduralSource, WombSchedule
    from kaine.modules.womb_signal import WombParams

    schedule = WombSchedule(seed=0, width=64, height=48)

    def _womb_factory(device, *, width, height):  # noqa: ANN001, ARG001
        return WombProceduralSource(
            schedule,
            params=WombParams(),
            clock=clock,
            lived_seconds=lambda: clock.womb_seconds(),
        )

    return Topos(
        bus,
        encoder=_FakeEncoder(),
        capture_enabled=True,
        source_factory=_womb_factory,
        # Fast capture cadence so the test runs quickly; geometry is tiny.
        live_camera_config=LiveCameraConfig(
            capture_interval_s=0.02, width=64, height=48, warmup_frames=0
        ),
    )


def _make_audition(bus: AsyncBus, clock) -> Audition:
    # Womb audio stream factory (mirror of what boot injects in womb mode).
    from kaine.modules.audition.feed import WombAudioSchedule, WombProceduralAudioStream
    from kaine.modules.womb_signal import WombParams

    schedule = WombAudioSchedule(
        seed=0, sample_rate=16000, channels=1, frames_per_block=480
    )

    def _womb_stream_factory(*, device, sample_rate, channels, frames_per_block, callback):  # noqa: ANN001, ARG001
        return WombProceduralAudioStream(
            schedule,
            params=WombParams(),
            clock=clock,
            callback=callback,
        )

    return Audition(
        bus,
        stt_client=FakeSTTClient(responses=["womb sound"]),
        emotion_classifier=FakeEmotionClassifier(),
        stt_model="fake-stt",
        capture_enabled=True,
        stream_factory=_womb_stream_factory,
        # RMS VAD on the continuous womb soundscape, flushed quickly so the
        # test does not wait the 30 s default max-utterance window.
        live_mic_config=LiveMicConfig(
            sample_rate=16000,
            channels=1,
            vad_backend="rms",
            vad_frame_ms=30,
            min_utterance_ms=30,
            max_utterance_ms=200,
            silence_hangover_ms=120,
        ),
    )


async def _wait_for_events(bus: AsyncBus, stream: str, *, timeout_s: float = 8.0):
    deadline = asyncio.get_running_loop().time() + timeout_s
    while asyncio.get_running_loop().time() < deadline:
        entries = await bus.read(stream, last_id="0", count=64)
        if entries:
            return [event for _, event in entries]
        await asyncio.sleep(0.05)
    return []


@pytest.mark.asyncio
async def test_womb_feed_delivers_vision_and_hearing(bus, virtual_feed_state, womb_clock):
    """The smoking gun: with the womb feed selected (virtual locus), Topos
    publishes to topos.out and Audition publishes to audition.out."""
    topos = _make_topos(bus, womb_clock)
    audition = _make_audition(bus, womb_clock)
    perception = PerceptionLocus(bus, desired_path=virtual_feed_state)

    await topos.initialize()
    await audition.initialize()
    await perception.initialize()
    try:
        topos_events = await _wait_for_events(bus, "topos.out")
        audition_events = await _wait_for_events(bus, "audition.out")

        assert topos_events, "topos.out received no events — vision is dark"
        assert any(e.type == "topos.report" for e in topos_events)

        assert audition_events, "audition.out received no events — hearing is dark"
        types = {e.type for e in audition_events}
        assert {"audition.transcription", "audition.emotion"} & types
    finally:
        await topos.shutdown()
        await audition.shutdown()
        await perception.shutdown()


@pytest.mark.asyncio
async def test_physical_locus_keeps_womb_feed_dark(bus, tmp_path, monkeypatch, womb_clock):
    """The locus model still holds: in the PHYSICAL locus the virtual womb feed
    must NOT run (it binds to `virtual`). This is the privacy-load-bearing XOR —
    proving the fix did not simply force the feed always-on."""
    desired = tmp_path / "desired.json"
    runtime = tmp_path / "runtime.json"
    monkeypatch.setattr(perception_state, "DESIRED_PATH", desired)
    monkeypatch.setattr(perception_state, "RUNTIME_PATH", runtime)
    # Operator wants video but stays in the physical locus — the virtual feed
    # gate (effective_virtual_video_capture) must stay False.
    perception_state.write_desired_video(True, desired)
    perception_state.write_desired_audio(True, desired)
    perception_state.write_desired_locus("physical", path=desired)

    topos = _make_topos(bus, womb_clock)
    await topos.initialize()
    try:
        topos_events = await _wait_for_events(bus, "topos.out", timeout_s=1.5)
        assert not topos_events, (
            "virtual womb feed published while locus=physical — XOR violated"
        )
    finally:
        await topos.shutdown()
