# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import asyncio
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.modules.vox import (
    Vox,
    FakePlayer,
    FakeTTSClient,
)
from kaine.modules.thymos.state import DimensionalState

# ---------------------------------------------------------------------------
# Helper: publish an audition.prosody event onto the bus
# ---------------------------------------------------------------------------

async def _publish_prosody(bus: AsyncBus, prosody: dict) -> None:
    await bus.client.xadd(
        "audition.out",
        {
            "source": "audition",
            "type": "audition.prosody",
            "salience": "0.3",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "causal_parent": "",
            "payload": json.dumps(prosody),
        },
    )


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield bus
    await bus.close()


def _make_vox(bus: AsyncBus, tmp_path: Path, **overrides) -> Vox:
    overrides.setdefault("player", FakePlayer())
    return Vox(
        bus,
        tts_client=FakeTTSClient(canned_audio=b"WAV-FAKE-DATA-1234"),
        sink_path=tmp_path / "vox",
        predefined_voice_id="default_sample.wav",
        **overrides,
    )


@pytest.mark.asyncio
async def test_invalid_construction(bus: AsyncBus, tmp_path: Path):
    with pytest.raises(ValueError):
        Vox(bus, tts_client=FakeTTSClient(), baseline_salience=2.0)
    with pytest.raises(ValueError):
        Vox(bus, tts_client=FakeTTSClient(), alert_salience=-0.1)


@pytest.mark.asyncio
async def test_synthesize_text_writes_audio_to_sink_when_enabled(
    bus: AsyncBus, tmp_path: Path
):
    vox = _make_vox(bus, tmp_path, sink_enabled=True, retain_count=1)
    await vox.initialize()
    try:
        result = await vox.synthesize_text("hello world")
        assert result.bytes_produced == len(b"WAV-FAKE-DATA-1234")
        files = list((tmp_path / "vox").glob("*.wav"))
        assert len(files) == 1
        assert files[0].read_bytes() == b"WAV-FAKE-DATA-1234"
    finally:
        await vox.shutdown()


@pytest.mark.asyncio
async def test_synthesize_plays_and_does_not_persist_by_default(
    bus: AsyncBus, tmp_path: Path
):
    player = FakePlayer()
    vox = _make_vox(bus, tmp_path, player=player)
    await vox.initialize()
    try:
        await vox.synthesize_text("hello world")
        # Played once...
        assert player.played == [b"WAV-FAKE-DATA-1234"]
        # ...and nothing written to disk (sink disabled by default).
        assert not list((tmp_path / "vox").glob("*.wav"))
    finally:
        await vox.shutdown()


@pytest.mark.asyncio
async def test_sink_retention_prunes_to_retain_count(bus: AsyncBus, tmp_path: Path):
    vox = _make_vox(bus, tmp_path, sink_enabled=True, retain_count=2)
    await vox.initialize()
    try:
        for i in range(4):
            await vox.synthesize_text(f"utterance {i}")
        files = list((tmp_path / "vox").glob("*.wav"))
        assert len(files) == 2
    finally:
        await vox.shutdown()


@pytest.mark.asyncio
async def test_synthesize_text_publishes_diagnostics_event(bus: AsyncBus, tmp_path: Path):
    vox = _make_vox(bus, tmp_path)
    await vox.initialize()
    try:
        await vox.synthesize_text("hello secret content")
        entries = await bus.read("vox.out", last_id="0")
        assert len(entries) == 1
        _, event = entries[0]
        assert event.type == "vox.synthesized"
        # No audio bytes anywhere in the payload.
        for v in event.payload.values():
            assert not isinstance(v, bytes)
        # No raw text leaked.
        for v in event.payload.values():
            if isinstance(v, str):
                assert "secret content" not in v
        # Documented metadata keys present.
        assert "bytes_produced" in event.payload
        assert "exaggeration" in event.payload
        assert "cfg_weight" in event.payload
        assert "temperature" in event.payload
    finally:
        await vox.shutdown()


@pytest.mark.asyncio
async def test_lingua_external_event_triggers_synthesis(bus: AsyncBus, tmp_path: Path):
    vox = _make_vox(bus, tmp_path)
    await vox.initialize()
    try:
        # Simulate a lingua.external event using bus.client.xadd directly
        # (matches how Lingua actually publishes — it bypasses the
        # default <module>.out routing for the dedicated stream).
        await bus.client.xadd(
            "lingua.external",
            {
                "source": "lingua",
                "type": "lingua.external",
                "salience": "0.4",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "causal_parent": "",
                "payload": json.dumps({"text": "hello from lingua", "mode": "external"}),
            },
        )
        for _ in range(50):
            await asyncio.sleep(0.02)
            if vox.tts_client.requests:
                break
        assert len(vox.tts_client.requests) == 1
        assert vox.tts_client.requests[0].text == "hello from lingua"
    finally:
        await vox.shutdown()


@pytest.mark.asyncio
async def test_thymos_state_updates_affect_used(bus: AsyncBus, tmp_path: Path):
    vox = _make_vox(bus, tmp_path)
    await vox.initialize()
    try:
        # Publish a thymos.state event with high arousal.
        await bus.client.xadd(
            "thymos.out",
            {
                "source": "thymos",
                "type": "thymos.state",
                "salience": "0.1",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "causal_parent": "",
                "payload": json.dumps({
                    "state": {"valence": -0.5, "arousal": 0.9, "dominance": 0.0},
                    "drives": {},
                    "emotion": "fear",
                }),
            },
        )
        # Wait for the consumer task to ingest the state.
        for _ in range(50):
            await asyncio.sleep(0.02)
            if vox.current_affect.arousal > 0.5:
                break
        assert vox.current_affect.arousal == pytest.approx(0.9)
        # Now synthesize — the request should use the high-arousal mapping.
        await vox.synthesize_text("test")
        request = vox.tts_client.requests[-1]
        # Exaggeration should be near top of band for arousal 0.9.
        assert request.exaggeration is not None and request.exaggeration > 0.7
    finally:
        await vox.shutdown()


@pytest.mark.asyncio
async def test_shutdown_closes_client(bus: AsyncBus, tmp_path: Path):
    client = FakeTTSClient()
    vox = Vox(
        bus,
        tts_client=client,
        sink_path=tmp_path / "vox",
        predefined_voice_id="default_sample.wav",
    )
    await vox.initialize()
    await vox.shutdown()
    assert client.closed is True


@pytest.mark.asyncio
async def test_serialize_roundtrips_affect(bus: AsyncBus, tmp_path: Path):
    vox = _make_vox(bus, tmp_path)
    vox._current_state = DimensionalState(
        valence=0.5, arousal=0.7, dominance=-0.2
    )
    state = vox.serialize()
    fresh = _make_vox(bus, tmp_path)
    fresh.deserialize(state)
    assert fresh.current_affect.valence == 0.5
    assert fresh.current_affect.arousal == 0.7


REAL_TTS_ENV = "KAINE_VOX_RUN_REAL"


@pytest.mark.skipif(
    os.environ.get(REAL_TTS_ENV) != "1",
    reason=f"set {REAL_TTS_ENV}=1 to hit live Chatterbox TTS",
)
@pytest.mark.asyncio
async def test_real_chatterbox_synthesis(bus: AsyncBus, tmp_path: Path):
    """Hits Chatterbox at 127.0.0.1:8883. Operator must have started it.

    Chatterbox's ``predefined`` voice mode REQUIRES a ``predefined_voice_id``
    that exists on the server (it 400s otherwise — the same failure an
    unconfigured ``[vox]`` boot would hit). Fetch an actual voice from the
    server's ``/get_predefined_voices`` so this validates synthesis rather than
    the missing-id error; skip if the server exposes no predefined voices.
    """
    import httpx

    from kaine.modules.vox.client import ChatterboxClient, TTSRequest

    base = "http://127.0.0.1:8883"
    async with httpx.AsyncClient(base_url=base, timeout=15.0) as probe:
        resp = await probe.get("/get_predefined_voices")
        resp.raise_for_status()
        voices = resp.json()
    if not voices:
        pytest.skip("Chatterbox exposes no predefined voices to synthesize with")
    voice_id = voices[0]["filename"]

    client = ChatterboxClient()
    try:
        result = await client.synthesize(
            TTSRequest(
                text="The system is online.",
                voice_mode="predefined",
                predefined_voice_id=voice_id,
                output_format="wav",
            )
        )
        assert result.bytes_produced > 0
        assert result.content_type.startswith("audio/")
    finally:
        await client.aclose()


# ---------------------------------------------------------------------------
# Prosodic mirroring — module-level tests (task 4.2)
# ---------------------------------------------------------------------------

def _make_vox_with_mirroring(bus: AsyncBus, tmp_path: Path, **overrides) -> Vox:
    """Build a Vox instance with mirroring enabled."""
    overrides.setdefault("player", FakePlayer())
    return Vox(
        bus,
        tts_client=FakeTTSClient(canned_audio=b"WAV-FAKE-DATA-1234"),
        sink_path=tmp_path / "vox",
        predefined_voice_id="default_sample.wav",
        mirroring_enabled=True,
        mirror_strength=0.5,
        mirror_ceiling=0.5,
        mirror_decay_s=10.0,
        **overrides,
    )


@pytest.mark.asyncio
async def test_mirroring_disabled_uses_affect_only(bus: AsyncBus, tmp_path: Path):
    """When mirroring is disabled, prosody events are ignored and synthesis
    uses affect-only parameters — no change from pre-mirroring behavior."""
    vox = _make_vox(bus, tmp_path)  # mirroring disabled by default
    await vox.initialize()
    try:
        # Publish a prosody event — should be ignored.
        await _publish_prosody(bus, {
            "f0_mean_hz": 200.0,
            "f0_std_hz": 55.0,
            "f0_voiced_frac": 0.9,
            "rms_mean": 0.19,
            "rms_std": 0.05,
            "tempo_bpm": 175.0,
        })
        await asyncio.sleep(0.15)
        # Latest prosody should remain None (not subscribed).
        assert vox._latest_prosody is None
        # Synthesize and capture params.
        await vox.synthesize_text("hello")
        req = vox.tts_client.requests[-1]
        # With default neutral state, speed_factor should be ~1.0.
        assert req.speed_factor is not None and 0.85 <= req.speed_factor <= 1.15
    finally:
        await vox.shutdown()


@pytest.mark.asyncio
async def test_mirroring_enabled_caches_prosody_event(bus: AsyncBus, tmp_path: Path):
    """When mirroring is enabled, Vox caches the audition.prosody payload."""
    vox = _make_vox_with_mirroring(bus, tmp_path)
    await vox.initialize()
    try:
        prosody_payload = {
            "f0_mean_hz": 180.0,
            "f0_std_hz": 45.0,
            "f0_voiced_frac": 0.8,
            "rms_mean": 0.15,
            "rms_std": 0.04,
            "tempo_bpm": 165.0,
        }
        await _publish_prosody(bus, prosody_payload)
        # Wait for the consumer loop to process the event.
        for _ in range(50):
            await asyncio.sleep(0.02)
            if vox._latest_prosody is not None:
                break
        assert vox._latest_prosody is not None, "prosody event was not cached"
        assert vox._latest_prosody_ts > 0.0
        # Verify the cached features are numeric (no raw audio bytes).
        for key, value in vox._latest_prosody.items():
            assert isinstance(value, float), f"feature {key!r} is not a float"
        assert vox._latest_prosody["tempo_bpm"] == pytest.approx(165.0)
    finally:
        await vox.shutdown()


@pytest.mark.asyncio
async def test_no_prosody_before_synthesis_uses_affect_only(bus: AsyncBus, tmp_path: Path):
    """When mirroring is enabled but no audition.prosody has arrived,
    synthesis falls back to affect-only parameters (graceful degradation)."""
    vox = _make_vox_with_mirroring(bus, tmp_path)
    await vox.initialize()
    try:
        # Synthesize immediately without any prosody event.
        from kaine.modules.vox.mapping import affect_to_chatterbox
        from kaine.modules.thymos.state import DimensionalState
        expected = affect_to_chatterbox(
            DimensionalState(),
            baseline_temperature=0.7,
            baseline_exaggeration=0.5,
            baseline_cfg_weight=0.5,
        )
        await vox.synthesize_text("hello")
        req = vox.tts_client.requests[-1]
        assert req.speed_factor == pytest.approx(expected.speed_factor)
        assert req.exaggeration == pytest.approx(expected.exaggeration)
        assert req.temperature == pytest.approx(expected.temperature)
        assert req.cfg_weight == pytest.approx(expected.cfg_weight)
    finally:
        await vox.shutdown()


@pytest.mark.asyncio
async def test_mirroring_enabled_nudges_params_after_prosody(bus: AsyncBus, tmp_path: Path):
    """After receiving an audition.prosody event, synthesis parameters
    are nudged toward the speaker's prosody — they differ from affect-only."""
    vox = _make_vox_with_mirroring(bus, tmp_path)
    await vox.initialize()
    try:
        # First, establish baseline (affect-only).
        await vox.synthesize_text("hello baseline")
        baseline_req = vox.tts_client.requests[-1]

        # Publish a fast / loud / expressive prosody.
        await _publish_prosody(bus, {
            "f0_mean_hz": 180.0,
            "f0_std_hz": 50.0,
            "f0_voiced_frac": 0.9,
            "rms_mean": 0.18,
            "rms_std": 0.05,
            "tempo_bpm": 170.0,
        })
        for _ in range(50):
            await asyncio.sleep(0.02)
            if vox._latest_prosody is not None:
                break
        assert vox._latest_prosody is not None

        await vox.synthesize_text("hello mirrored")
        mirrored_req = vox.tts_client.requests[-1]

        # At least one dynamic param should differ from the affect-only baseline.
        changed = (
            mirrored_req.speed_factor != pytest.approx(baseline_req.speed_factor, abs=1e-6)
            or mirrored_req.exaggeration != pytest.approx(baseline_req.exaggeration, abs=1e-6)
            or mirrored_req.temperature != pytest.approx(baseline_req.temperature, abs=1e-6)
        )
        assert changed, "mirroring had no effect on synthesis parameters"

        # cfg_weight (voice identity proxy) must be unchanged.
        assert mirrored_req.cfg_weight == pytest.approx(baseline_req.cfg_weight)
    finally:
        await vox.shutdown()


@pytest.mark.asyncio
async def test_mirroring_base_voice_id_never_altered(bus: AsyncBus, tmp_path: Path):
    """The predefined_voice_id sent to TTS is always the configured value.

    This is the explicit identity-preservation test: no matter what prosody
    arrives, the voice identity parameter sent to Chatterbox is unchanged.
    """
    configured_voice_id = "default_sample.wav"
    vox = _make_vox_with_mirroring(bus, tmp_path)
    await vox.initialize()
    try:
        # Publish an extreme prosody.
        await _publish_prosody(bus, {
            "f0_mean_hz": 300.0,
            "f0_std_hz": 80.0,
            "f0_voiced_frac": 1.0,
            "rms_mean": 0.99,
            "rms_std": 0.5,
            "tempo_bpm": 220.0,
        })
        for _ in range(50):
            await asyncio.sleep(0.02)
            if vox._latest_prosody is not None:
                break

        await vox.synthesize_text("identity check")
        req = vox.tts_client.requests[-1]
        # The voice_id sent to Chatterbox must be the configured value.
        assert req.predefined_voice_id == configured_voice_id
    finally:
        await vox.shutdown()
