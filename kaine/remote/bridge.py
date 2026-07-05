# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Remote perception bridge — WebSocket ingress/egress for operator clients.

A cycle-layer component (like Spot, not a registry module) that lets the
operator stream a remote camera/microphone into the entity's perception and
hear its speech / read the transcript back, over the operator's Tailscale
tailnet. Started by ``kaine.cycle.__main__`` when ``[remote_bridge].enabled``
is true; ships disabled and binds 127.0.0.1 by default. The tailnet ACL is
the security boundary; an optional shared-secret token adds cheap hardening.

Channels (path-routed on one port):

  * ``/ingest/video``  — client→entity binary JPEG/PNG frames. Decoded to an
    in-memory ``PIL.Image`` and handed to ``Topos.process_frame()``.
    Latest-wins: frames arriving faster than ``video_max_fps`` (or while a
    frame is still being encoded) are dropped, and drops are counted.
  * ``/ingest/audio``  — client→entity binary int16 mono PCM at
    ``audio_sample_rate``. Fed through a bridge-owned
    :class:`~kaine.modules.audition.live.LiveMicrophone` (network
    ``stream_factory``), so the EXISTING VAD/utterance assembly produces
    in-memory WAV utterances for ``Audition.process_audio(...,
    source_label="remote")``. No duplicated segmentation logic.
  * ``/speech``        — entity→client binary WAV clips, tapped from Vox via
    ``Vox.add_playback_tap`` (local playback unaffected).
  * ``/transcript``    — entity→client JSON: entity utterances
    (``lingua.external``) and heard transcriptions (``audition.out``).
  * ``/affect``        — entity→client JSON: the entity's dimensional affect
    (``thymos.out``: ``thymos.state`` heartbeat + ``thymos.emotion`` changes),
    a read-only feed clients can drive a "mood ring" from. Compact lines of
    ``{"valence", "arousal", "ts"[, "label"]}``; coalesced to <=~10/s.

ZERO-PERSISTENCE (load-bearing): remote frames, PCM, and tapped speech live
only in memory and are released after processing — nothing in this package
opens a file for writing. There are no process-termination or shell-exec
primitives here; the bridge only reads, decodes, and injects.

While a remote producer is connected (and ``claim_senses`` is true) the
matching physical sense is marked not-desired via the existing
``perception_state`` API so the physical camera/mic and the remote stream
never fight; the prior desired state is restored on disconnect.
"""
from __future__ import annotations

import asyncio
import hmac
import io
import json
import logging
import ssl
import time
import urllib.parse
from dataclasses import dataclass
from typing import Any, Optional

from kaine.bus.client import AsyncBus
from kaine.bus.schema import Event

log = logging.getLogger(__name__)

LINGUA_EXTERNAL_STREAM = "lingua.external"
AUDITION_STREAM = "audition.out"
# Thymos publishes via BaseModule.publish (source="thymos"), so both the
# `thymos.state` heartbeat and the `thymos.emotion` change events land on the
# single `thymos.out` stream. Both carry dimensional affect nested under the
# payload `"state"` key ({valence, arousal, dominance}) and a discrete label
# under `"emotion"`. The /affect channel tails this stream read-only.
THYMOS_STREAM = "thymos.out"
THYMOS_AFFECT_TYPES = ("thymos.state", "thymos.emotion")
# Coalesce affect forwarding to at most ~10/s (keep-latest) so a chatty thymos
# can't flood mood-ring clients. Lines arriving sooner than this are dropped.
AFFECT_MIN_INTERVAL_S = 0.1

# Token offered by browser clients as a Sec-WebSocket-Protocol subprotocol,
# since browsers cannot set arbitrary WS handshake headers. The client offers
# ``kaine.bearer.<token>``; the server authenticates on a constant-time match
# and (RFC-compliantly) selects no subprotocol in its response.
BEARER_SUBPROTOCOL_PREFIX = "kaine.bearer."

# Default origins permitted to open a browser WebSocket. ``None`` admits
# native/non-browser clients that send no Origin header. The two app origins
# are the desktop shell and the Android WebView asset host.
DEFAULT_ALLOWED_ORIGINS: tuple[Optional[str], ...] = (
    None,
    "http://127.0.0.1:17893",
    "https://appassets.androidplatform.net",
)

# Decompression-bomb guard for /ingest/video: reject any frame whose declared
# pixel count exceeds this (~2000x2000, far above any real camera frame).
MAX_FRAME_PIXELS = 4_000_000


@dataclass(frozen=True)
class RemoteBridgeConfig:
    enabled: bool = False
    host: str = "127.0.0.1"
    port: int = 8089
    # Optional shared-secret. When non-empty, clients must present it as a
    # `?token=` query parameter (or `Authorization: Bearer`) at handshake.
    token: str = ""
    # Latest-wins ceiling for remote frames handed to Topos.
    video_max_fps: float = 4.0
    # Remote PCM format (int16 mono). Mirrors LiveMicConfig defaults.
    audio_sample_rate: int = 16000
    audio_vad_backend: str = "webrtcvad"  # or "rms"
    # Mark the matching physical sense not-desired while a remote producer
    # is connected (restored on disconnect).
    claim_senses: bool = True
    # Per-/speech-client outbound queue (clips). Oldest dropped when full.
    speech_queue_size: int = 8
    # Browser-WebSocket Origin allowlist. ``None`` admits native/non-browser
    # clients (no Origin header). Passed straight to ``websockets.serve(origins=)``.
    allowed_origins: tuple[Optional[str], ...] = DEFAULT_ALLOWED_ORIGINS
    # Hard cap on a single inbound WS message (bytes). Frame-appropriate but
    # small enough to blunt memory-amplification; audio chunks are tiny.
    max_message_bytes: int = 2 * 1024 * 1024
    # Optional wss/TLS. When BOTH are set, the bridge serves over TLS. Pairs
    # well with a Tailscale-issued cert (`tailscale cert <host>.ts.net`).
    ssl_certfile: str = ""
    ssl_keyfile: str = ""

    @classmethod
    def from_section(cls, section: dict[str, Any] | None) -> "RemoteBridgeConfig":
        s = section or {}
        return cls(
            enabled=bool(s.get("enabled", cls.enabled)),
            host=str(s.get("host", cls.host)),
            port=int(s.get("port", cls.port)),
            token=str(s.get("token", cls.token)),
            video_max_fps=float(s.get("video_max_fps", cls.video_max_fps)),
            audio_sample_rate=int(s.get("audio_sample_rate", cls.audio_sample_rate)),
            audio_vad_backend=str(s.get("audio_vad_backend", cls.audio_vad_backend)),
            claim_senses=bool(s.get("claim_senses", cls.claim_senses)),
            speech_queue_size=int(s.get("speech_queue_size", cls.speech_queue_size)),
            allowed_origins=cls._parse_origins(s.get("allowed_origins")),
            max_message_bytes=int(s.get("max_message_bytes", cls.max_message_bytes)),
            ssl_certfile=str(s.get("ssl_certfile", cls.ssl_certfile)),
            ssl_keyfile=str(s.get("ssl_keyfile", cls.ssl_keyfile)),
        )

    @staticmethod
    def _parse_origins(raw: Any) -> tuple[Optional[str], ...]:
        """Map a TOML array of strings to the ``origins=`` sequence.

        The sentinels ``"null"`` and ``""`` become Python ``None`` (admit
        no-Origin native clients). An omitted/empty key keeps the secure
        default allowlist."""
        if raw is None:
            return DEFAULT_ALLOWED_ORIGINS
        out: list[Optional[str]] = []
        for item in raw:
            text = str(item)
            out.append(None if text in ("null", "") else text)
        return tuple(out)


class NetworkAudioStream:
    """`_AudioStream` fed by WebSocket PCM instead of a sound card.

    LiveMicrophone's stream contract is start()/stop()/close() plus a
    callback receiving exact ``frames_per_block``-sample int16 blocks. The
    bridge pushes arbitrary-size PCM chunks into :meth:`feed`; this object
    re-chunks them to the block size the VAD expects. In-memory only.
    """

    def __init__(self, *, frames_per_block: int, callback, max_buffer_bytes: int = 0) -> None:
        self._block_bytes = int(frames_per_block) * 2  # int16 mono
        self._callback = callback
        self._buffer = bytearray()
        self._running = False
        # Cap the un-drained backlog so a slow/blocked VAD (e.g. during a cycle
        # freeze) can't grow the buffer without bound. <=0 disables the cap.
        # Never below one block, or feed() could never assemble a callback.
        self._max_buffer_bytes = (
            max(int(max_buffer_bytes), self._block_bytes) if max_buffer_bytes > 0 else 0
        )

    def start(self) -> None:
        self._running = True

    def stop(self) -> None:
        self._running = False

    def close(self) -> None:
        self._running = False
        self._buffer.clear()

    def feed(self, chunk: bytes) -> None:
        if not self._running or not chunk:
            return
        self._buffer.extend(chunk)
        if self._max_buffer_bytes and len(self._buffer) > self._max_buffer_bytes:
            overflow = len(self._buffer) - self._max_buffer_bytes
            del self._buffer[:overflow]
            log.warning(
                "network audio buffer over cap (%d B); dropped %d B of oldest PCM",
                self._max_buffer_bytes,
                overflow,
            )
        while len(self._buffer) >= self._block_bytes:
            block = bytes(self._buffer[: self._block_bytes])
            del self._buffer[: self._block_bytes]
            self._callback(block)


class SpeechTapPlayer:
    """Vox `Player` that broadcasts each synthesized clip to /speech clients.

    Composed via ``Vox.add_playback_tap`` — the local player still runs.
    Per-client bounded queues; when a slow client falls behind, the oldest
    clip is dropped (and counted) rather than blocking synthesis.
    """

    def __init__(self, queue_size: int = 8) -> None:
        self._queues: set[asyncio.Queue[bytes]] = set()
        self._queue_size = int(queue_size)
        self.dropped_clips = 0

    def subscribe(self) -> asyncio.Queue[bytes]:
        q: asyncio.Queue[bytes] = asyncio.Queue(maxsize=self._queue_size)
        self._queues.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[bytes]) -> None:
        self._queues.discard(q)

    async def play(self, audio: bytes, *, output_format: str = "wav") -> None:
        if not audio:
            return
        for q in list(self._queues):
            try:
                q.put_nowait(audio)
            except asyncio.QueueFull:
                try:
                    q.get_nowait()
                    q.put_nowait(audio)
                except (asyncio.QueueEmpty, asyncio.QueueFull):
                    # Concurrent get/put race during the eviction — dropping
                    # is the intended drop-oldest behavior, counted below.
                    pass
                self.dropped_clips += 1


class _SenseClaim:
    """Tracks remote producers per sense and (un)claims the physical sense.

    On the FIRST connected producer for a sense, records the prior desired
    state and writes desired=False; on the LAST disconnect, restores the
    recorded prior value. Honest about failures: perception_state errors are
    logged, never swallowed into pretend success silently.
    """

    def __init__(self, enabled: bool) -> None:
        self._enabled = bool(enabled)
        self._counts = {"video": 0, "audio": 0}
        self._prior: dict[str, Optional[bool]] = {"video": None, "audio": None}

    def _write(self, sense: str, active: bool) -> None:
        from kaine import perception_state

        if sense == "video":
            perception_state.write_desired_video(active)
        else:
            perception_state.write_desired_audio(active)

    def _read(self, sense: str) -> bool:
        from kaine import perception_state

        desired = perception_state.read_desired()
        return bool(getattr(desired, sense, False))

    def acquire(self, sense: str) -> None:
        self._counts[sense] += 1
        if not self._enabled or self._counts[sense] != 1:
            return
        try:
            self._prior[sense] = self._read(sense)
            self._write(sense, False)
            log.info(
                "remote bridge claimed %s sense (physical desired %s -> False)",
                sense,
                self._prior[sense],
            )
        except Exception:
            log.error("remote bridge failed to claim %s sense", sense, exc_info=True)

    def release(self, sense: str) -> None:
        self._counts[sense] = max(0, self._counts[sense] - 1)
        if not self._enabled or self._counts[sense] != 0:
            return
        prior = self._prior[sense]
        self._prior[sense] = None
        if prior is None:
            return
        try:
            self._write(sense, prior)
            log.info("remote bridge released %s sense (restored desired=%s)", sense, prior)
        except Exception:
            log.error("remote bridge failed to restore %s sense", sense, exc_info=True)

    def connected(self, sense: str) -> bool:
        return self._counts[sense] > 0


class RemoteBridge:
    """The WebSocket server. Construct with the live module instances the
    cycle already built; ``start()`` binds, ``stop()`` tears down."""

    def __init__(
        self,
        config: RemoteBridgeConfig,
        *,
        bus: AsyncBus,
        topos: Any = None,
        audition: Any = None,
        vox: Any = None,
    ) -> None:
        self._cfg = config
        self._bus = bus
        self._topos = topos
        self._audition = audition
        self._vox = vox
        self._server: Any = None
        self._tasks: list[asyncio.Task[None]] = []
        self._claims = _SenseClaim(config.claim_senses)
        self._speech_tap = SpeechTapPlayer(config.speech_queue_size)
        self._transcript_queues: set[asyncio.Queue[str]] = set()
        self._affect_queues: set[asyncio.Queue[str]] = set()
        # Last monotonic time an affect line was forwarded (coalescing throttle).
        self._last_affect_ts = 0.0
        self._mic: Any = None  # bridge-owned LiveMicrophone
        self._net_stream: Optional[NetworkAudioStream] = None
        self._last_frame_ts = 0.0
        self._frame_busy = False
        self.frames_in = 0
        self.frames_dropped = 0
        self.utterances_hint = 0  # PCM chunks fed (utterance count lives in audition logs)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        import websockets

        if self._vox is not None and hasattr(self._vox, "add_playback_tap"):
            self._vox.add_playback_tap(self._speech_tap)
        if self._audition is not None:
            await self._start_network_mic()
        self._tasks.append(
            asyncio.create_task(self._transcript_loop(), name="remote-bridge-transcript")
        )
        self._tasks.append(
            asyncio.create_task(self._affect_loop(), name="remote-bridge-affect")
        )
        ssl_context = self._build_ssl_context()
        self._server = await websockets.serve(
            self._handle,
            self._cfg.host,
            self._cfg.port,
            max_size=self._cfg.max_message_bytes,
            origins=list(self._cfg.allowed_origins),
            ssl=ssl_context,
        )
        log.info(
            "remote bridge listening on %s://%s:%d (token %s; origins=%s; "
            "video->%s audio->%s vox-tap=%s)",
            "wss" if ssl_context is not None else "ws",
            self._cfg.host,
            self._cfg.port,
            "set" if self._cfg.token else "NOT set — tailnet ACL is the only boundary",
            list(self._cfg.allowed_origins),
            "topos" if self._topos is not None else "absent",
            "audition" if self._audition is not None else "absent",
            self._vox is not None,
        )

    def _build_ssl_context(self) -> Optional[ssl.SSLContext]:
        """Build a TLS server context when BOTH cert and key are configured,
        else None (plain ws, exactly as before). Pairs with a Tailscale cert."""
        certfile = self._cfg.ssl_certfile
        keyfile = self._cfg.ssl_keyfile
        if not (certfile and keyfile):
            return None
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(certfile, keyfile)
        log.info("remote bridge TLS enabled (wss) using cert %s", certfile)
        return ctx

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            try:
                await self._server.wait_closed()
            except Exception:
                # Best-effort shutdown: a close-time transport error must not
                # block the rest of the teardown. Visible when debugging.
                log.debug("server wait_closed raised during stop", exc_info=True)
            self._server = None
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            try:
                await task
            except asyncio.CancelledError:
                # Expected: we cancelled the task just above.
                pass
            except Exception:
                log.debug("bridge task raised during stop", exc_info=True)
        self._tasks.clear()
        if self._mic is not None:
            try:
                await self._mic.shutdown()
            except Exception:
                log.debug("network mic shutdown raised", exc_info=True)
            self._mic = None
        log.info("remote bridge stopped")

    # ------------------------------------------------------------------
    # Connection handling
    # ------------------------------------------------------------------

    def _token_ok(self, presented: str) -> bool:
        """Constant-time compare of a presented token against the configured
        one (timing-oracle hardening); empty presented never matches."""
        if not presented:
            return False
        return hmac.compare_digest(
            presented.encode("utf-8"), self._cfg.token.encode("utf-8")
        )

    def _authorized(self, connection: Any) -> bool:
        # No token configured → tailnet ACL is the boundary; allow (fast path).
        if not self._cfg.token:
            return True
        try:
            # 1) ?token= query parameter.
            query = urllib.parse.urlparse(connection.request.path).query
            params = urllib.parse.parse_qs(query)
            if self._token_ok(params.get("token", [""])[0]):
                return True
            # 2) Authorization: Bearer <token>.
            auth = connection.request.headers.get("Authorization", "")
            if auth.startswith("Bearer ") and self._token_ok(auth[len("Bearer ") :]):
                return True
            # 3) Sec-WebSocket-Protocol: kaine.bearer.<token> (browser clients
            #    can't set arbitrary WS headers; they offer the token as a
            #    subprotocol). We authenticate but do NOT echo a selected
            #    subprotocol — absent Sec-WebSocket-Protocol is RFC-compliant.
            offered = connection.request.headers.get("Sec-WebSocket-Protocol", "")
            for proto in offered.split(","):
                proto = proto.strip()
                if proto.startswith(BEARER_SUBPROTOCOL_PREFIX) and self._token_ok(
                    proto[len(BEARER_SUBPROTOCOL_PREFIX) :]
                ):
                    return True
            return False
        except Exception:
            return False

    async def _handle(self, connection: Any) -> None:
        path = urllib.parse.urlparse(connection.request.path).path
        if not self._authorized(connection):
            log.warning("remote bridge rejected unauthenticated client on %s", path)
            await connection.close(code=4401, reason="unauthorized")
            return
        if path == "/ingest/video":
            await self._serve_video(connection)
        elif path == "/ingest/audio":
            await self._serve_audio(connection)
        elif path == "/speech":
            await self._serve_speech(connection)
        elif path == "/transcript":
            await self._serve_transcript(connection)
        elif path == "/affect":
            await self._serve_affect(connection)
        else:
            await connection.close(code=4404, reason=f"unknown path {path}")

    # -- video ----------------------------------------------------------

    async def _serve_video(self, connection: Any) -> None:
        if self._topos is None:
            await connection.close(code=4503, reason="topos not enabled")
            return
        self._claims.acquire("video")
        log.info("remote video producer connected")
        try:
            async for message in connection:
                if not isinstance(message, (bytes, bytearray)):
                    continue
                await self._ingest_frame(bytes(message))
        finally:
            self._claims.release("video")
            log.info(
                "remote video producer disconnected (frames=%d dropped=%d)",
                self.frames_in,
                self.frames_dropped,
            )

    async def _ingest_frame(self, payload: bytes) -> None:
        now = time.monotonic()
        min_interval = 1.0 / max(0.1, self._cfg.video_max_fps)
        if self._frame_busy or (now - self._last_frame_ts) < min_interval:
            self.frames_dropped += 1
            return
        self._last_frame_ts = now
        self._frame_busy = True
        try:
            from PIL import Image

            # Decompression-bomb guard: cap PIL's own global ceiling and reject
            # frames whose DECLARED dimensions (read from the header, before the
            # expensive .load()) exceed our frame cap. Drop, don't crash.
            if Image.MAX_IMAGE_PIXELS is None or Image.MAX_IMAGE_PIXELS > MAX_FRAME_PIXELS:
                Image.MAX_IMAGE_PIXELS = MAX_FRAME_PIXELS
            # In-memory decode; the image is released after process_frame.
            image = Image.open(io.BytesIO(payload))
            width, height = image.size
            if width * height > MAX_FRAME_PIXELS:
                self.frames_dropped += 1
                log.warning(
                    "remote frame dropped: %dx%d exceeds %d-pixel cap",
                    width,
                    height,
                    MAX_FRAME_PIXELS,
                )
                return
            image.load()
            await self._topos.process_frame(image)
            self.frames_in += 1
        except Exception:
            log.warning("remote frame decode/process failed", exc_info=True)
        finally:
            self._frame_busy = False

    # -- audio ----------------------------------------------------------

    async def _start_network_mic(self) -> None:
        from kaine.modules.audition.live import LiveMicConfig, LiveMicrophone

        cfg = LiveMicConfig(
            sample_rate=self._cfg.audio_sample_rate,
            channels=1,
            vad_backend=self._cfg.audio_vad_backend,  # type: ignore[arg-type]
            source_label="remote",
        )

        # ~2 seconds of int16 mono at the configured rate bounds the un-drained
        # backlog (2 bytes/sample). Excess oldest PCM is trimmed in feed().
        max_buffer_bytes = int(self._cfg.audio_sample_rate) * 2 * 2

        def factory(*, device, sample_rate, channels, frames_per_block, callback):
            self._net_stream = NetworkAudioStream(
                frames_per_block=frames_per_block,
                callback=callback,
                max_buffer_bytes=max_buffer_bytes,
            )
            return self._net_stream

        self._mic = LiveMicrophone(
            sink=self._audition.process_audio,
            config=cfg,
            # The "device" is the network: active while a producer is connected.
            desired_state_reader=lambda: self._claims.connected("audio"),
            stream_factory=factory,
        )
        await self._mic.initialize()

    async def _serve_audio(self, connection: Any) -> None:
        if self._audition is None or self._mic is None:
            await connection.close(code=4503, reason="audition not enabled")
            return
        self._claims.acquire("audio")
        log.info("remote audio producer connected")
        try:
            async for message in connection:
                if not isinstance(message, (bytes, bytearray)):
                    continue
                stream = self._net_stream
                if stream is not None:
                    stream.feed(bytes(message))
                    self.utterances_hint += 1
        finally:
            self._claims.release("audio")
            log.info("remote audio producer disconnected")

    # -- speech out ------------------------------------------------------

    @staticmethod
    async def _pump_queue(connection: Any, queue: asyncio.Queue) -> None:
        """Send queue items to the client until it disconnects.

        Races each get() against the connection closing so a disconnected
        client never leaves the handler parked on an empty queue (which
        would deadlock server.wait_closed() at shutdown)."""
        closed = asyncio.ensure_future(connection.wait_closed())
        try:
            while True:
                getter = asyncio.ensure_future(queue.get())
                done, _ = await asyncio.wait(
                    {getter, closed}, return_when=asyncio.FIRST_COMPLETED
                )
                if closed in done:
                    getter.cancel()
                    return
                await connection.send(getter.result())
        except Exception:
            # Expected on the disconnect path (send to a closing socket);
            # the finally + caller's finally do all cleanup.
            log.debug("queue pump ended", exc_info=True)
        finally:
            closed.cancel()

    async def _serve_speech(self, connection: Any) -> None:
        queue = self._speech_tap.subscribe()
        log.info("remote speech consumer connected")
        try:
            await self._pump_queue(connection, queue)
        finally:
            self._speech_tap.unsubscribe(queue)
            log.info("remote speech consumer disconnected")

    # -- transcript -------------------------------------------------------

    async def _serve_transcript(self, connection: Any) -> None:
        queue: asyncio.Queue[str] = asyncio.Queue(maxsize=64)
        self._transcript_queues.add(queue)
        log.info("remote transcript consumer connected")
        try:
            await self._pump_queue(connection, queue)
        finally:
            self._transcript_queues.discard(queue)
            log.info("remote transcript consumer disconnected")

    async def _transcript_loop(self) -> None:
        """Forward entity speech + heard transcriptions to transcript clients."""
        cursors: dict[str, str] = {}
        for stream in (LINGUA_EXTERNAL_STREAM, AUDITION_STREAM):
            try:
                latest = await self._bus.client.xrevrange(stream, count=1)
            except Exception:
                latest = []
            if latest:
                entry_id = latest[0][0]
                if isinstance(entry_id, bytes):
                    entry_id = entry_id.decode()
                cursors[stream] = entry_id
            else:
                cursors[stream] = "0-0"
        try:
            while True:
                progressed = False
                for stream in (LINGUA_EXTERNAL_STREAM, AUDITION_STREAM):
                    try:
                        entries = await self._bus.read(
                            stream,
                            last_id=cursors.get(stream, "0"),
                            count=32,
                            block_ms=0,
                        )
                    except Exception:
                        continue
                    if entries:
                        progressed = True
                        cursors[stream] = entries[-1][0]
                        for _, event in entries:
                            line = self._transcript_line(stream, event)
                            if line is not None:
                                self._fanout_transcript(line)
                if not progressed:
                    await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            raise

    @staticmethod
    def _transcript_line(stream: str, event: Event) -> Optional[str]:
        payload = event.payload or {}
        if stream == LINGUA_EXTERNAL_STREAM and event.type == "external_speech":
            role, text = "entity", str(payload.get("text", ""))
        elif stream == AUDITION_STREAM and event.type == "audition.transcription":
            role, text = "heard", str(payload.get("text", ""))
        else:
            return None
        if not text:
            return None
        ts = event.timestamp.isoformat() if hasattr(event.timestamp, "isoformat") else str(
            event.timestamp
        )
        return json.dumps(
            {
                "role": role,
                "text": text,
                "type": event.type,
                "source_label": payload.get("source_label") or payload.get("source"),
                "ts": ts,
            }
        )

    def _fanout_transcript(self, line: str) -> None:
        for q in list(self._transcript_queues):
            try:
                q.put_nowait(line)
            except asyncio.QueueFull:
                try:
                    q.get_nowait()
                    q.put_nowait(line)
                except (asyncio.QueueEmpty, asyncio.QueueFull):
                    # Concurrent get/put race during the eviction — dropping
                    # the line for this slow client is the intended behavior.
                    pass

    # -- affect -----------------------------------------------------------

    async def _serve_affect(self, connection: Any) -> None:
        queue: asyncio.Queue[str] = asyncio.Queue(maxsize=64)
        self._affect_queues.add(queue)
        log.info("remote affect consumer connected")
        try:
            await self._pump_queue(connection, queue)
        finally:
            self._affect_queues.discard(queue)
            log.info("remote affect consumer disconnected")

    async def _affect_loop(self) -> None:
        """Forward the entity's dimensional affect to /affect clients.

        Tails ``thymos.out`` (both the ``thymos.state`` heartbeat and the
        ``thymos.emotion`` change events) and fans out compact JSON to mood-ring
        subscribers. Read-only: this loop never writes to the bus or disk.
        Coalesced to <=~10/s so a chatty thymos can't flood clients."""
        try:
            latest = await self._bus.client.xrevrange(THYMOS_STREAM, count=1)
        except Exception:
            latest = []
        if latest:
            entry_id = latest[0][0]
            if isinstance(entry_id, bytes):
                entry_id = entry_id.decode()
            cursor = entry_id
        else:
            cursor = "0-0"
        try:
            while True:
                try:
                    entries = await self._bus.read(
                        THYMOS_STREAM,
                        last_id=cursor,
                        count=32,
                        block_ms=0,
                    )
                except Exception:
                    entries = []
                if entries:
                    cursor = entries[-1][0]
                    for _, event in entries:
                        line = self._affect_line(THYMOS_STREAM, event)
                        if line is not None:
                            self._fanout_affect(line)
                else:
                    await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            raise

    @staticmethod
    def _affect_line(stream: str, event: Event) -> Optional[str]:
        if stream != THYMOS_STREAM or event.type not in THYMOS_AFFECT_TYPES:
            return None
        payload = event.payload or {}
        # Both thymos.state and thymos.emotion nest the dimensional values under
        # "state"; never invent affect — bail if it's absent or malformed.
        dims = payload.get("state")
        if not isinstance(dims, dict):
            return None
        valence = dims.get("valence")
        arousal = dims.get("arousal")
        if not isinstance(valence, (int, float)) or not isinstance(arousal, (int, float)):
            return None
        ts = event.timestamp.isoformat() if hasattr(event.timestamp, "isoformat") else str(
            event.timestamp
        )
        line: dict[str, Any] = {
            "valence": float(valence),
            "arousal": float(arousal),
            "ts": ts,
        }
        # Forward the discrete emotion label only when thymos actually provides
        # one (it does on both event types via the "emotion" key).
        label = payload.get("emotion")
        if isinstance(label, str) and label:
            line["label"] = label
        return json.dumps(line)

    def _fanout_affect(self, line: str) -> None:
        # Coalesce: keep-latest at <=~10/s. A line arriving sooner than
        # AFFECT_MIN_INTERVAL_S after the last forwarded one is dropped.
        now = time.monotonic()
        if (now - self._last_affect_ts) < AFFECT_MIN_INTERVAL_S:
            return
        self._last_affect_ts = now
        for q in list(self._affect_queues):
            try:
                q.put_nowait(line)
            except asyncio.QueueFull:
                try:
                    q.get_nowait()
                    q.put_nowait(line)
                except (asyncio.QueueEmpty, asyncio.QueueFull):
                    # Concurrent get/put race during the eviction — dropping
                    # the line for this slow client is the intended behavior.
                    pass


def build_remote_bridge(
    kaine_config: dict[str, Any],
    *,
    bus: AsyncBus,
    registry: Any,
) -> Optional[RemoteBridge]:
    """Construct the bridge from config + the live registry, or None when
    disabled. Called by the cycle entrypoint after modules initialize."""
    cfg = RemoteBridgeConfig.from_section(kaine_config.get("remote_bridge"))
    if not cfg.enabled:
        return None

    def _get(name: str) -> Any:
        try:
            return registry.get(name) if name in registry else None
        except Exception:
            return None

    topos = _get("topos")
    audition = _get("audition")
    vox = _get("vox")
    if topos is None and audition is None and vox is None:
        log.warning(
            "remote bridge enabled but none of topos/audition/vox are — not starting"
        )
        return None
    return RemoteBridge(cfg, bus=bus, topos=topos, audition=audition, vox=vox)
