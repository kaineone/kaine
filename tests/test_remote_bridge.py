# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Remote perception bridge (remote-perception-bridge change).

Real localhost WebSocket server in every networked test — nothing mocked at
the transport layer. Covers: shipped-disabled guard, no-kill source guard,
token auth, video → Topos, PCM → VAD → Audition (source_label="remote"),
Vox speech tap broadcast, transcript forwarding, claim/restore of physical
senses, and zero-persistence during a full exchange.
"""
from __future__ import annotations

import asyncio
import io
import json
import struct
from datetime import datetime, timezone
from pathlib import Path

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.modules.vox.playback import FakePlayer, TeePlayer
from kaine.remote.bridge import (
    NetworkAudioStream,
    RemoteBridge,
    RemoteBridgeConfig,
    SpeechTapPlayer,
    build_remote_bridge,
)

websockets = pytest.importorskip("websockets")

PROJECT_ROOT = Path(__file__).parent.parent


# ---------------------------------------------------------------------------
# Stub modules (the bridge composes live instances; these record the calls)
# ---------------------------------------------------------------------------


class _StubTopos:
    def __init__(self) -> None:
        self.frames: list = []

    async def process_frame(self, image) -> str:
        self.frames.append(image)
        return "ok"


class _StubAudition:
    def __init__(self) -> None:
        self.calls: list[tuple[bytes, int, str]] = []

    async def process_audio(self, wav_bytes, sample_rate, *, source_label="mic"):
        self.calls.append((bytes(wav_bytes), int(sample_rate), str(source_label)))
        return None, None


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    b = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield b
    await b.close()


def _config(**kw) -> RemoteBridgeConfig:
    defaults = dict(
        enabled=True,
        host="127.0.0.1",
        port=0,  # ephemeral
        claim_senses=False,  # opt in per-test (touches perception_state)
        audio_vad_backend="rms",  # dependency-free in CI
    )
    defaults.update(kw)
    return RemoteBridgeConfig(**defaults)


async def _started(bridge: RemoteBridge) -> str:
    await bridge.start()
    sock = next(iter(bridge._server.sockets))
    host, port = sock.getsockname()[:2]
    return f"ws://{host}:{port}"


def _jpeg_bytes() -> bytes:
    PIL = pytest.importorskip("PIL.Image")
    buf = io.BytesIO()
    PIL.new("RGB", (32, 24), (200, 30, 30)).save(buf, format="JPEG")
    return buf.getvalue()


def _pcm(ms: int, *, loud: bool, sample_rate: int = 16000) -> bytes:
    n = sample_rate * ms // 1000
    amp = 12000 if loud else 0
    # Square-ish wave: trivially loud RMS, dead-silent otherwise.
    return struct.pack(f"<{n}h", *(((-amp, amp)[i % 2]) for i in range(n)))


# ---------------------------------------------------------------------------
# Guards
# ---------------------------------------------------------------------------


def test_shipped_config_disables_bridge():
    import tomllib

    cfg = tomllib.loads((PROJECT_ROOT / "config" / "kaine.toml").read_text())
    section = cfg["remote_bridge"]
    assert section["enabled"] is False
    assert section["host"] == "127.0.0.1"
    assert build_remote_bridge({"remote_bridge": section}, bus=None, registry=None) is None


def test_bridge_source_has_no_kill_or_exec_primitives():
    """The bridge reads, decodes, and injects — it must never gain the power
    to terminate processes or shell out."""
    for path in (PROJECT_ROOT / "kaine" / "remote").rglob("*.py"):
        source = path.read_text()
        for banned in ("subprocess", "os.kill", "os.system", ".terminate(", ".kill("):
            assert banned not in source, f"{banned!r} found in {path}"


def test_network_audio_stream_rechunks_exactly():
    blocks: list[bytes] = []
    stream = NetworkAudioStream(frames_per_block=480, callback=blocks.append)
    stream.start()
    stream.feed(b"\x00" * 1000)
    stream.feed(b"\x00" * 1000)
    assert all(len(b) == 960 for b in blocks)
    assert len(blocks) == 2  # 2000 bytes -> 2 full blocks + 80 buffered
    stream.close()
    stream.feed(b"\x00" * 4000)
    assert len(blocks) == 2  # closed stream feeds nowhere


# ---------------------------------------------------------------------------
# Token auth
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_token_rejects_and_accepts(bus):
    topos = _StubTopos()
    bridge = RemoteBridge(_config(token="s3cret"), bus=bus, topos=topos)
    url = await _started(bridge)
    try:
        # No token → closed with 4401 before any payload is processed.
        async with websockets.connect(f"{url}/ingest/video") as ws:
            with pytest.raises(websockets.exceptions.ConnectionClosed) as exc_info:
                await ws.recv()
            assert exc_info.value.rcvd.code == 4401
        assert topos.frames == []

        # Correct token (query param) → frame accepted.
        async with websockets.connect(f"{url}/ingest/video?token=s3cret") as ws:
            await ws.send(_jpeg_bytes())
            await _wait_for(lambda: len(topos.frames) == 1)
    finally:
        await bridge.stop()


# ---------------------------------------------------------------------------
# Video
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_video_frame_reaches_topos_as_pil_image(bus):
    topos = _StubTopos()
    bridge = RemoteBridge(_config(), bus=bus, topos=topos)
    url = await _started(bridge)
    try:
        async with websockets.connect(f"{url}/ingest/video") as ws:
            await ws.send(_jpeg_bytes())
            await _wait_for(lambda: len(topos.frames) == 1)
        image = topos.frames[0]
        assert image.size == (32, 24)  # a real decoded PIL image
        assert bridge.frames_in == 1
    finally:
        await bridge.stop()


@pytest.mark.asyncio
async def test_video_rate_limit_drops_excess_frames(bus):
    topos = _StubTopos()
    bridge = RemoteBridge(_config(video_max_fps=1.0), bus=bus, topos=topos)
    url = await _started(bridge)
    try:
        frame = _jpeg_bytes()
        async with websockets.connect(f"{url}/ingest/video") as ws:
            for _ in range(10):
                await ws.send(frame)
            await _wait_for(lambda: bridge.frames_in + bridge.frames_dropped >= 10)
        assert bridge.frames_in <= 2  # 1 fps ceiling — burst collapses
        assert bridge.frames_dropped >= 8
    finally:
        await bridge.stop()


# ---------------------------------------------------------------------------
# Audio (through the real LiveMicrophone VAD/utterance assembly)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pcm_utterance_reaches_audition_with_remote_label(bus):
    audition = _StubAudition()
    bridge = RemoteBridge(_config(), bus=bus, audition=audition)
    url = await _started(bridge)
    try:
        async with websockets.connect(f"{url}/ingest/audio") as ws:
            # Producer connected → the network mic stream spins up (poll).
            await _wait_for(
                lambda: bridge._net_stream is not None and bridge._net_stream._running,
                timeout=3.0,
            )
            # ~600 ms of loud PCM, then >hangover of silence to flush.
            await ws.send(_pcm(600, loud=True))
            await ws.send(_pcm(900, loud=False))
            await _wait_for(lambda: len(audition.calls) >= 1, timeout=5.0)
        wav_bytes, sample_rate, label = audition.calls[0]
        assert label == "remote"
        assert sample_rate == 16000
        assert wav_bytes[:4] == b"RIFF"  # in-memory WAV framing
    finally:
        await bridge.stop()


# ---------------------------------------------------------------------------
# Speech out + transcript
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_speech_tap_broadcasts_to_client(bus):
    bridge = RemoteBridge(_config(), bus=bus, vox=None)
    url = await _started(bridge)
    try:
        async with websockets.connect(f"{url}/speech") as ws:
            await asyncio.sleep(0.05)  # let the consumer subscribe
            await bridge._speech_tap.play(b"RIFFfakewav")
            clip = await asyncio.wait_for(ws.recv(), timeout=2.0)
        assert clip == b"RIFFfakewav"
    finally:
        await bridge.stop()


@pytest.mark.asyncio
async def test_tee_player_mirrors_and_survives_tap_failure():
    primary = FakePlayer()
    tap = SpeechTapPlayer()
    q = tap.subscribe()
    tee = TeePlayer(primary, tap)
    await tee.play(b"clip1")
    assert primary.played == [b"clip1"]
    assert q.get_nowait() == b"clip1"

    class _Boom:
        async def play(self, audio, *, output_format="wav"):
            raise RuntimeError("tap died")

    tee2 = TeePlayer(primary, _Boom())
    await tee2.play(b"clip2")  # must not raise
    assert primary.played == [b"clip1", b"clip2"]


@pytest.mark.asyncio
async def test_vox_add_playback_tap_composes(bus):
    from kaine.modules.vox.module import Vox

    primary = FakePlayer()
    vox = Vox(bus, player=primary)
    tap = SpeechTapPlayer()
    q = tap.subscribe()
    vox.add_playback_tap(tap)
    assert isinstance(vox._player, TeePlayer)
    await vox._player.play(b"RIFFclip")
    assert primary.played == [b"RIFFclip"]  # local playback unchanged
    assert q.get_nowait() == b"RIFFclip"


@pytest.mark.asyncio
async def test_transcript_forwards_entity_and_heard_lines(bus):
    bridge = RemoteBridge(_config(), bus=bus)
    url = await _started(bridge)
    try:
        async with websockets.connect(f"{url}/transcript") as ws:
            await asyncio.sleep(0.15)  # consumer + cursor seeding
            await _publish(bus, "lingua.external", "lingua", "external_speech",
                           {"text": "hello operator"})
            await _publish(bus, "audition.out", "audition", "audition.transcription",
                           {"text": "hello kaine", "source_label": "remote"})
            lines = [
                json.loads(await asyncio.wait_for(ws.recv(), timeout=3.0))
                for _ in range(2)
            ]
        by_role = {line["role"]: line for line in lines}
        assert by_role["entity"]["text"] == "hello operator"
        assert by_role["heard"]["text"] == "hello kaine"
        assert by_role["heard"]["source_label"] == "remote"
    finally:
        await bridge.stop()


# ---------------------------------------------------------------------------
# Affect (/affect — read-only mood-ring feed from thymos.out)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_affect_forwards_dimensional_state_line(bus):
    """A connected /affect client gets a JSON line with valence/arousal after a
    matching thymos.state event is xadd-ed to thymos.out."""
    bridge = RemoteBridge(_config(), bus=bus)
    url = await _started(bridge)
    try:
        async with websockets.connect(f"{url}/affect") as ws:
            await asyncio.sleep(0.15)  # consumer + cursor seeding
            await _publish(
                bus,
                "thymos.out",
                "thymos",
                "thymos.state",
                {
                    "state": {"valence": 0.42, "arousal": 0.66, "dominance": -0.1},
                    "emotion": "joy",
                },
            )
            line = json.loads(await asyncio.wait_for(ws.recv(), timeout=3.0))
        assert line["valence"] == pytest.approx(0.42)
        assert line["arousal"] == pytest.approx(0.66)
        assert line["label"] == "joy"
        assert "ts" in line
        # Read-only feed: no dominance/raw payload leakage beyond the contract.
        assert set(line) == {"valence", "arousal", "ts", "label"}
    finally:
        await bridge.stop()


@pytest.mark.asyncio
async def test_affect_forwards_emotion_change_event(bus):
    """thymos.emotion events also carry the nested state dict and are forwarded."""
    bridge = RemoteBridge(_config(), bus=bus)
    url = await _started(bridge)
    try:
        async with websockets.connect(f"{url}/affect") as ws:
            await asyncio.sleep(0.15)
            await _publish(
                bus,
                "thymos.out",
                "thymos",
                "thymos.emotion",
                {
                    "emotion": "fear",
                    "state": {"valence": -0.5, "arousal": 0.8, "dominance": -0.3},
                },
            )
            line = json.loads(await asyncio.wait_for(ws.recv(), timeout=3.0))
        assert line["valence"] == pytest.approx(-0.5)
        assert line["arousal"] == pytest.approx(0.8)
        assert line["label"] == "fear"
    finally:
        await bridge.stop()


def test_affect_line_returns_none_for_unrelated_stream_and_type():
    """_affect_line forwards only thymos.out affect events; everything else is
    None (never invents affect values)."""
    from datetime import datetime, timezone

    from kaine.bus.schema import Event
    from kaine.remote.bridge import THYMOS_STREAM

    def _ev(type_: str, payload: dict) -> Event:
        return Event(
            source="thymos",
            type=type_,
            payload=payload,
            salience=0.5,
            timestamp=datetime.now(timezone.utc),
        )

    good = {"state": {"valence": 0.1, "arousal": 0.2}, "emotion": "calm"}
    # Right stream + type → a line.
    assert RemoteBridge._affect_line(THYMOS_STREAM, _ev("thymos.state", good)) is not None
    # Wrong stream → None.
    assert RemoteBridge._affect_line("audition.out", _ev("thymos.state", good)) is None
    # Wrong type on the right stream → None.
    assert RemoteBridge._affect_line(THYMOS_STREAM, _ev("thymos.drive", good)) is None
    # Right type but no nested state → None (never invent values).
    assert RemoteBridge._affect_line(THYMOS_STREAM, _ev("thymos.state", {})) is None
    # Right type, state present but missing arousal → None.
    assert (
        RemoteBridge._affect_line(
            THYMOS_STREAM, _ev("thymos.state", {"state": {"valence": 0.1}})
        )
        is None
    )
    # No discrete label in payload → line omits "label" (only forwards what exists).
    line = RemoteBridge._affect_line(
        THYMOS_STREAM, _ev("thymos.state", {"state": {"valence": 0.1, "arousal": 0.2}})
    )
    assert line is not None and "label" not in json.loads(line)


def test_affect_coalescing_throttle_drops_too_soon(bus):
    """_fanout_affect coalesces to <=~10/s: a too-soon second line is dropped,
    a later one (past the min interval) forwards."""
    import time as _time

    bridge = RemoteBridge(_config(), bus=bus)
    q: asyncio.Queue[str] = asyncio.Queue(maxsize=64)
    bridge._affect_queues.add(q)

    # Pin the throttle clock to a known recent value, then fire two lines.
    bridge._last_affect_ts = 0.0
    bridge._fanout_affect('{"a": 1}')  # first one always passes (long gap)
    first_passed = q.qsize()
    bridge._fanout_affect('{"a": 2}')  # immediately after → dropped
    after_too_soon = q.qsize()
    # Backdate the last-forward time past the min interval → next one forwards.
    bridge._last_affect_ts = _time.monotonic() - 1.0
    bridge._fanout_affect('{"a": 3}')
    after_later = q.qsize()

    assert first_passed == 1
    assert after_too_soon == 1  # the too-soon line was coalesced away
    assert after_later == 2     # the later line forwarded


@pytest.mark.asyncio
async def test_affect_respects_origin_allowlist(bus):
    """/affect honors the same Origin allowlist as the other channels: a
    disallowed browser Origin is refused at handshake; an allowed one connects."""
    bridge = RemoteBridge(
        _config(allowed_origins=(None, "http://127.0.0.1:17893")),
        bus=bus,
    )
    url = await _started(bridge)
    try:
        # Disallowed Origin → websockets refuses the handshake (403).
        with pytest.raises(websockets.exceptions.InvalidStatus) as exc_info:
            async with websockets.connect(
                f"{url}/affect", origin="https://evil.example"
            ):
                pass
        assert exc_info.value.response.status_code == 403

        # Allowed Origin → connects and receives a forwarded affect line.
        async with websockets.connect(
            f"{url}/affect", origin="http://127.0.0.1:17893"
        ) as ws:
            await asyncio.sleep(0.15)
            await _publish(
                bus,
                "thymos.out",
                "thymos",
                "thymos.state",
                {"state": {"valence": 0.0, "arousal": 0.3}, "emotion": "neutral"},
            )
            line = json.loads(await asyncio.wait_for(ws.recv(), timeout=3.0))
        assert line["arousal"] == pytest.approx(0.3)
    finally:
        await bridge.stop()


@pytest.mark.asyncio
async def test_affect_respects_token_auth(bus):
    """/affect enforces the shared-secret token like every other channel."""
    bridge = RemoteBridge(_config(token="s3cret"), bus=bus)
    url = await _started(bridge)
    try:
        # No token → closed with 4401.
        async with websockets.connect(f"{url}/affect") as ws:
            with pytest.raises(websockets.exceptions.ConnectionClosed) as exc_info:
                await ws.recv()
            assert exc_info.value.rcvd.code == 4401

        # Correct token (query param) → connects and receives an affect line.
        async with websockets.connect(f"{url}/affect?token=s3cret") as ws:
            await asyncio.sleep(0.15)
            await _publish(
                bus,
                "thymos.out",
                "thymos",
                "thymos.state",
                {"state": {"valence": 0.2, "arousal": 0.4}, "emotion": "content"},
            )
            line = json.loads(await asyncio.wait_for(ws.recv(), timeout=3.0))
        assert line["valence"] == pytest.approx(0.2)
    finally:
        await bridge.stop()


# ---------------------------------------------------------------------------
# Sense claiming + zero-persistence
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_claim_senses_sets_and_restores_physical_video(bus, monkeypatch):
    import kaine.perception_state as ps

    writes: list[tuple[str, bool]] = []

    class _Desired:
        video = True
        audio = False

    monkeypatch.setattr(ps, "read_desired", lambda path=None: _Desired())
    monkeypatch.setattr(
        ps, "write_desired_video", lambda active, path=None: writes.append(("video", active))
    )
    monkeypatch.setattr(
        ps, "write_desired_audio", lambda active, path=None: writes.append(("audio", active))
    )

    topos = _StubTopos()
    bridge = RemoteBridge(_config(claim_senses=True), bus=bus, topos=topos)
    url = await _started(bridge)
    try:
        async with websockets.connect(f"{url}/ingest/video") as ws:
            await ws.send(_jpeg_bytes())
            await _wait_for(lambda: ("video", False) in writes)
        # Disconnect → restore the recorded prior (True).
        await _wait_for(lambda: ("video", True) in writes)
        assert writes == [("video", False), ("video", True)]
    finally:
        await bridge.stop()


BANNED_EXTENSIONS = (".pt", ".pkl", ".npy", ".arrow", ".jsonl", ".wav", ".jpg", ".jpeg", ".png", ".webm", ".mp4")


def _scan(root: Path) -> set[Path]:
    found: set[Path] = set()
    if not root.exists():
        return found
    for path in root.rglob("*"):
        try:
            if path.is_file() and path.suffix.lower() in BANNED_EXTENSIONS:
                found.add(path)
        except OSError:
            continue
    return found


@pytest.mark.asyncio
async def test_full_exchange_writes_nothing_to_disk(bus):
    """ZERO-PERSISTENCE: a complete ingest/egress exchange leaves no media
    artifacts in /tmp or the project tree."""
    topos = _StubTopos()
    audition = _StubAudition()
    bridge = RemoteBridge(_config(), bus=bus, topos=topos, audition=audition)
    url = await _started(bridge)

    pre_tmp = _scan(Path("/tmp"))
    pre_project = _scan(PROJECT_ROOT)
    try:
        async with websockets.connect(f"{url}/ingest/video") as wsv:
            await wsv.send(_jpeg_bytes())
            await _wait_for(lambda: topos.frames)
        async with websockets.connect(f"{url}/ingest/audio") as wsa:
            await _wait_for(
                lambda: bridge._net_stream is not None and bridge._net_stream._running,
                timeout=3.0,
            )
            await wsa.send(_pcm(600, loud=True))
            await wsa.send(_pcm(900, loud=False))
            await _wait_for(lambda: audition.calls, timeout=5.0)
        async with websockets.connect(f"{url}/speech") as wss:
            await asyncio.sleep(0.05)
            await bridge._speech_tap.play(b"RIFFfake")
            await asyncio.wait_for(wss.recv(), timeout=2.0)
    finally:
        await bridge.stop()

    leaked = (_scan(Path("/tmp")) - pre_tmp) | (_scan(PROJECT_ROOT) - pre_project)
    assert leaked == set(), (
        "ZERO-PERSISTENCE VIOLATED: remote bridge wrote disk artifacts: "
        f"{sorted(str(p) for p in leaked)}"
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _wait_for(predicate, timeout: float = 2.0) -> None:
    deadline = asyncio.get_event_loop().time() + timeout
    while not predicate():
        if asyncio.get_event_loop().time() > deadline:
            raise AssertionError("condition not met within timeout")
        await asyncio.sleep(0.02)


async def _publish(bus: AsyncBus, stream: str, source: str, type_: str, payload: dict) -> None:
    await bus.client.xadd(
        stream,
        {
            "source": source,
            "type": type_,
            "salience": "0.5",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "causal_parent": "",
            "payload": json.dumps(payload),
        },
    )


def _oversized_png() -> bytes:
    """A real PNG whose declared dimensions exceed the frame pixel cap.

    Built at a size beyond MAX_FRAME_PIXELS so the bridge's header-time guard
    rejects it WITHOUT ever calling .load() on a decompression bomb. Kept as a
    flat single-color image so PIL encodes it cheaply despite the dimensions."""
    from kaine.remote.bridge import MAX_FRAME_PIXELS

    PIL = pytest.importorskip("PIL.Image")
    # 3000x2000 = 6,000,000 px > 4,000,000 cap, but trivially compressible.
    width, height = 3000, 2000
    assert width * height > MAX_FRAME_PIXELS
    buf = io.BytesIO()
    PIL.new("RGB", (width, height), (0, 0, 0)).save(buf, format="PNG")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Security hardening: Sec-WebSocket-Protocol token, constant-time, origin
# allowlist, decompression-bomb guard, audio buffer cap, TLS context.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_token_via_subprotocol_authenticates(bus):
    """Browser clients offer the token as `kaine.bearer.<token>`; a matching
    subprotocol authenticates. The server selects NO subprotocol in response."""
    topos = _StubTopos()
    bridge = RemoteBridge(_config(token="s3cret"), bus=bus, topos=topos)
    url = await _started(bridge)
    try:
        async with websockets.connect(
            f"{url}/ingest/video", subprotocols=["kaine.bearer.s3cret"]
        ) as ws:
            # RFC-compliant: server did not echo/select a subprotocol.
            assert ws.subprotocol is None
            await ws.send(_jpeg_bytes())
            await _wait_for(lambda: len(topos.frames) == 1)
    finally:
        await bridge.stop()


@pytest.mark.asyncio
async def test_wrong_subprotocol_token_is_rejected(bus):
    topos = _StubTopos()
    bridge = RemoteBridge(_config(token="s3cret"), bus=bus, topos=topos)
    url = await _started(bridge)
    try:
        async with websockets.connect(
            f"{url}/ingest/video", subprotocols=["kaine.bearer.WRONG"]
        ) as ws:
            with pytest.raises(websockets.exceptions.ConnectionClosed) as exc_info:
                await ws.recv()
            assert exc_info.value.rcvd.code == 4401
        assert topos.frames == []
    finally:
        await bridge.stop()


@pytest.mark.asyncio
async def test_bearer_header_path_still_works(bus):
    """The Authorization: Bearer path remains valid (constant-time compare)."""
    topos = _StubTopos()
    bridge = RemoteBridge(_config(token="s3cret"), bus=bus, topos=topos)
    url = await _started(bridge)
    try:
        async with websockets.connect(
            f"{url}/ingest/video",
            additional_headers={"Authorization": "Bearer s3cret"},
        ) as ws:
            await ws.send(_jpeg_bytes())
            await _wait_for(lambda: len(topos.frames) == 1)
    finally:
        await bridge.stop()


def test_constant_time_token_predicate():
    """_token_ok uses hmac.compare_digest semantics: exact match only, empty
    never matches, and the no-token-configured fast path still allows."""
    bridge = RemoteBridge(_config(token="s3cret"), bus=None, topos=_StubTopos())
    assert bridge._token_ok("s3cret") is True
    assert bridge._token_ok("s3crxt") is False
    assert bridge._token_ok("") is False
    assert bridge._token_ok("s3cret-longer") is False
    # No token configured → _authorized short-circuits to allow.
    open_bridge = RemoteBridge(_config(token=""), bus=None, topos=_StubTopos())

    class _Conn:
        class request:
            path = "/ingest/video"
            headers: dict = {}

    assert open_bridge._authorized(_Conn()) is True


@pytest.mark.asyncio
async def test_origin_allowlist_refuses_and_accepts(bus):
    """A disallowed browser Origin is refused at handshake; an allowed Origin
    and a no-Origin native client are accepted."""
    topos = _StubTopos()
    bridge = RemoteBridge(
        # High fps ceiling so back-to-back accepted frames aren't rate-dropped.
        _config(allowed_origins=(None, "http://127.0.0.1:17893"), video_max_fps=1000.0),
        bus=bus,
        topos=topos,
    )
    url = await _started(bridge)
    try:
        # Disallowed Origin → websockets refuses the handshake (403).
        with pytest.raises(websockets.exceptions.InvalidStatus) as exc_info:
            async with websockets.connect(
                f"{url}/ingest/video", origin="https://evil.example"
            ):
                pass
        assert exc_info.value.response.status_code == 403

        # Allowed Origin → accepted, frame ingested.
        async with websockets.connect(
            f"{url}/ingest/video", origin="http://127.0.0.1:17893"
        ) as ws:
            await ws.send(_jpeg_bytes())
            await _wait_for(lambda: len(topos.frames) == 1)

        # No Origin (native client) → accepted (None is in the allowlist).
        async with websockets.connect(f"{url}/ingest/video") as ws:
            await ws.send(_jpeg_bytes())
            await _wait_for(lambda: len(topos.frames) == 2)
    finally:
        await bridge.stop()


def test_parse_origins_maps_null_and_empty_to_none():
    cfg = RemoteBridgeConfig.from_section(
        {"allowed_origins": ["null", "", "https://app.example"]}
    )
    assert cfg.allowed_origins == (None, None, "https://app.example")
    # Omitted key keeps the secure default allowlist.
    from kaine.remote.bridge import DEFAULT_ALLOWED_ORIGINS

    assert RemoteBridgeConfig.from_section({}).allowed_origins == DEFAULT_ALLOWED_ORIGINS


@pytest.mark.asyncio
async def test_oversized_image_is_dropped_without_reaching_topos(bus):
    """A frame whose declared size exceeds the pixel cap is dropped (counted)
    without raising and without calling topos.process_frame."""
    topos = _StubTopos()
    bridge = RemoteBridge(_config(), bus=bus, topos=topos)
    url = await _started(bridge)
    try:
        async with websockets.connect(f"{url}/ingest/video") as ws:
            await ws.send(_oversized_png())
            await _wait_for(lambda: bridge.frames_dropped >= 1, timeout=3.0)
        assert topos.frames == []  # never decoded/processed
        assert bridge.frames_in == 0
    finally:
        await bridge.stop()


def test_audio_buffer_cap_trims_oldest_and_stays_bounded():
    """Feeding far more than the cap trims the oldest PCM; the backlog never
    grows past the cap (plus at most one partial block)."""
    blocks: list[bytes] = []
    # Cap = 1000 bytes; block = 2000 bytes (so nothing drains; pure backlog).
    stream = NetworkAudioStream(
        frames_per_block=1000, callback=blocks.append, max_buffer_bytes=1000
    )
    # Cap is floored to one block (2000 B) so a block can still assemble.
    assert stream._max_buffer_bytes == 2000
    stream.start()
    for _ in range(50):
        stream.feed(b"\x00" * 1500)  # 75,000 B total, way over cap
    # Backlog is bounded: <= cap, and one full block flushes when reached.
    assert len(stream._buffer) <= stream._max_buffer_bytes
    # Drop-oldest semantics still produced exact-size blocks.
    assert all(len(b) == 2000 for b in blocks)
    stream.close()


def test_ssl_context_built_only_when_cert_and_key_present(tmp_path):
    """Providing both cert+key builds a TLS server context; either alone (or
    neither) yields None (plain ws, unchanged behavior)."""
    import ssl as _ssl

    bridge_none = RemoteBridge(_config(), bus=None, topos=_StubTopos())
    assert bridge_none._build_ssl_context() is None

    # Only one of the pair → still plain ws.
    bridge_partial = RemoteBridge(
        _config(ssl_certfile="/x/cert.pem"), bus=None, topos=_StubTopos()
    )
    assert bridge_partial._build_ssl_context() is None

    # A real self-signed cert+key → a usable SSLContext.
    cert_path, key_path = _make_self_signed(tmp_path)
    bridge_tls = RemoteBridge(
        _config(ssl_certfile=str(cert_path), ssl_keyfile=str(key_path)),
        bus=None,
        topos=_StubTopos(),
    )
    ctx = bridge_tls._build_ssl_context()
    assert isinstance(ctx, _ssl.SSLContext)


def test_config_threads_new_security_fields():
    cfg = RemoteBridgeConfig.from_section(
        {
            "max_message_bytes": 1234,
            "ssl_certfile": "/c.pem",
            "ssl_keyfile": "/k.pem",
            "allowed_origins": ["null"],
        }
    )
    assert cfg.max_message_bytes == 1234
    assert cfg.ssl_certfile == "/c.pem"
    assert cfg.ssl_keyfile == "/k.pem"
    assert cfg.allowed_origins == (None,)
    # Defaults when section omits them.
    d = RemoteBridgeConfig.from_section({})
    assert d.max_message_bytes == 2 * 1024 * 1024
    assert d.ssl_certfile == "" and d.ssl_keyfile == ""


def _make_self_signed(tmp_path):
    """Write a throwaway self-signed cert+key PEM pair, or skip if the host
    lacks a way to mint one. Used only to prove load_cert_chain succeeds."""
    cert_path = tmp_path / "cert.pem"
    key_path = tmp_path / "key.pem"
    try:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID
        import datetime as _dt

        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
        cert = (
            x509.CertificateBuilder()
            .subject_name(name)
            .issuer_name(name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(_dt.datetime.now(_dt.timezone.utc))
            .not_valid_after(
                _dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(days=1)
            )
            .sign(key, hashes.SHA256())
        )
        key_path.write_bytes(
            key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.TraditionalOpenSSL,
                serialization.NoEncryption(),
            )
        )
        cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        return cert_path, key_path
    except Exception:
        pytest.skip("cannot mint a self-signed cert on this host")
        return None
