# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Live microphone stream — eyes and ears for the audio surface.

LiveMicrophone runs as a sibling task launched from Audition.initialize()
when [audition].capture_enabled = true. It opens sounddevice.InputStream
in a background thread, segments speech using webrtcvad (or simple RMS
fallback), and on utterance boundaries wraps the buffered PCM as an
in-memory WAV blob (wave.open(io.BytesIO(), 'wb')) and hands it to
Audition.process_audio().

ZERO PERSISTENCE INVARIANT: raw PCM lives only in a bounded asyncio
Queue, the in-memory WAV blob lives only in a BytesIO, and every
reference is released after the sink call returns. Nothing in this file
opens a file for writing. Ever.
"""
from __future__ import annotations

import asyncio
import io
import logging
import threading
import wave
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Literal, Protocol, runtime_checkable

log = logging.getLogger(__name__)


class PerceptionUnavailableError(RuntimeError):
    """Raised when capture is enabled but the required extras aren't installed."""


SinkFn = Callable[[bytes, int, str], Awaitable[Any]]
StateWriter = Callable[[bool], Any]
DesiredReader = Callable[[], bool]
OnStateChange = Callable[[str, dict], None]


@runtime_checkable
class _VAD(Protocol):
    def is_speech(self, frame: bytes, sample_rate: int) -> bool: ...


@runtime_checkable
class _AudioStream(Protocol):
    def start(self) -> None: ...
    def stop(self) -> None: ...
    def close(self) -> None: ...


@dataclass(frozen=True)
class LiveMicConfig:
    device: str | int | None = None
    sample_rate: int = 16000
    channels: int = 1
    vad_backend: Literal["webrtcvad", "rms"] = "webrtcvad"
    vad_aggressiveness: int = 2
    vad_frame_ms: int = 30
    min_utterance_ms: int = 300
    max_utterance_ms: int = 30_000
    silence_hangover_ms: int = 600
    desired_state_poll_ms: int = 250
    source_label: str = "live_mic"


class _RMSVAD:
    """Threshold-based VAD fallback when webrtcvad isn't available.

    Computes RMS over the int16 PCM frame and compares against a fixed
    threshold. Cheap, not great, good enough for environments where
    webrtcvad won't build.
    """

    def __init__(self, threshold: int = 500) -> None:
        self._threshold = int(threshold)

    def is_speech(self, frame: bytes, sample_rate: int) -> bool:
        if not frame:
            return False
        import struct
        n = len(frame) // 2
        if n == 0:
            return False
        samples = struct.unpack(f"<{n}h", frame[: n * 2])
        rms = (sum(s * s for s in samples) / n) ** 0.5
        return rms >= self._threshold


def _load_webrtcvad(aggressiveness: int) -> _VAD:
    try:
        import webrtcvad  # type: ignore[import-untyped]
    except ImportError as exc:
        raise PerceptionUnavailableError(
            "webrtcvad not installed — install with: pip install -e .[audio]"
        ) from exc
    vad = webrtcvad.Vad(int(aggressiveness))
    return vad


def _default_stream_factory(
    *,
    device: str | int | None,
    sample_rate: int,
    channels: int,
    frames_per_block: int,
    callback: Callable[[bytes], None],
) -> _AudioStream:
    """Build a real sounddevice.InputStream that pushes int16 PCM bytes
    into `callback` from the audio thread."""
    try:
        import sounddevice as sd  # type: ignore[import-untyped]
    except ImportError as exc:
        raise PerceptionUnavailableError(
            "sounddevice not installed — install with: pip install -e .[audio]"
        ) from exc

    def _cb(indata, frames, time_info, status):  # type: ignore[no-untyped-def]
        if status:
            log.debug("sounddevice status: %s", status)
        # indata is a numpy int16 array shaped (frames, channels).
        # Convert to little-endian PCM bytes.
        callback(bytes(indata))

    stream = sd.RawInputStream(
        samplerate=sample_rate,
        blocksize=frames_per_block,
        device=device if device not in (None, "") else None,
        dtype="int16",
        channels=channels,
        callback=_cb,
    )
    return stream


def _tap_audio_level(frame: bytes, sample_rate: int) -> None:
    """Dev-gated audio-level preview tap. Computes the normalised RMS (0..1) of a
    single int16 PCM frame and hands it to the in-memory preview holder. No-op
    (and no computation) unless KAINE_PERCEPTION_PREVIEW is set; retains and
    persists nothing — a single float only."""
    try:
        from kaine import perception_preview

        if not perception_preview.preview_enabled():
            return
        if not frame:
            perception_preview.set_audio_level(0.0)
            return
        import struct

        n = len(frame) // 2
        if n <= 0:
            return
        samples = struct.unpack(f"<{n}h", frame[: n * 2])
        rms = (sum(s * s for s in samples) / n) ** 0.5
        # int16 full-scale is 32768; clamp to [0, 1] for a meter.
        perception_preview.set_audio_level(min(1.0, rms / 32768.0))
    except Exception:
        # Never let the diagnostic tap disturb the hearing path.
        pass


def encode_wav(pcm: bytes, *, sample_rate: int, channels: int, sampwidth: int = 2) -> bytes:
    """Wrap raw PCM as a WAV blob entirely in memory. NO file path,
    EVER. The output bytes are handed to the parent's process_audio."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sampwidth)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm)
    return buf.getvalue()


class LiveMicrophone:
    """Eyes-and-ears microphone stream. Constructed by AudioInput when
    [audition].capture_enabled is true. Lifecycle owned by the parent.

    `sink` is `AudioInput.process_audio`. The microphone hands utterance
    bytes to it and never touches the result.
    """

    def __init__(
        self,
        sink: SinkFn,
        *,
        config: LiveMicConfig | None = None,
        state_writer: StateWriter | None = None,
        desired_state_reader: DesiredReader | None = None,
        on_state_change: OnStateChange | None = None,
        stream_factory: Callable[..., _AudioStream] | None = None,
        vad_factory: Callable[..., _VAD] | None = None,
    ) -> None:
        self._sink = sink
        self._cfg = config or LiveMicConfig()
        self._state_writer = state_writer
        self._desired_reader = desired_state_reader
        self._on_state_change = on_state_change
        self._stream_factory = stream_factory or _default_stream_factory
        self._vad_factory = vad_factory
        self._task: asyncio.Task[None] | None = None
        self._stopped = asyncio.Event()
        self._active = False
        self._stream: _AudioStream | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._pcm_queue: asyncio.Queue[bytes] | None = None
        self._lock = threading.Lock()

    @property
    def active(self) -> bool:
        return self._active

    @property
    def config(self) -> LiveMicConfig:
        return self._cfg

    async def initialize(self) -> None:
        if self._task is not None:
            return
        self._loop = asyncio.get_running_loop()
        # Queue is large enough to hold ~5 s of audio at the configured
        # frame rate before the supervisor pulls. If backpressure kicks
        # in we drop, not block.
        frames_per_second = max(1, 1000 // max(1, self._cfg.vad_frame_ms))
        self._pcm_queue = asyncio.Queue(maxsize=frames_per_second * 5)
        self._stopped.clear()
        self._task = asyncio.create_task(
            self._supervise(), name="live-mic-supervisor"
        )

    async def shutdown(self) -> None:
        self._stopped.set()
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=5.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                self._task.cancel()
            self._task = None
        self._close_stream()
        if self._active:
            self._set_active(False)

    async def _supervise(self) -> None:
        try:
            while not self._stopped.is_set():
                desired = self._read_desired()
                if desired and not self._active:
                    await self._start_stream()
                elif not desired and self._active:
                    await self._stop_stream()
                if self._active:
                    await self._consume_one_utterance()
                else:
                    try:
                        await asyncio.wait_for(
                            self._stopped.wait(),
                            timeout=self._cfg.desired_state_poll_ms / 1000.0,
                        )
                    except asyncio.TimeoutError:
                        continue
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("live mic supervisor crashed")
        finally:
            self._close_stream()
            if self._active:
                self._set_active(False)

    def _read_desired(self) -> bool:
        if self._desired_reader is None:
            return True  # supervised but no toggle — boot-time enabled means active
        try:
            return bool(self._desired_reader())
        except Exception:
            log.warning("desired_state_reader raised", exc_info=True)
            return self._active

    async def _start_stream(self) -> None:
        frames_per_block = max(1, self._cfg.sample_rate * self._cfg.vad_frame_ms // 1000)
        try:
            self._stream = self._stream_factory(
                device=self._cfg.device,
                sample_rate=self._cfg.sample_rate,
                channels=self._cfg.channels,
                frames_per_block=frames_per_block,
                callback=self._on_audio_frame_threadsafe,
            )
            self._stream.start()
        except PerceptionUnavailableError:
            raise
        except Exception:
            log.exception("failed to open microphone stream")
            self._stream = None
            return
        self._set_active(True)
        log.info(
            "live mic capture_started device=%s sample_rate=%d channels=%d vad=%s",
            self._cfg.device or "default",
            self._cfg.sample_rate,
            self._cfg.channels,
            self._cfg.vad_backend,
        )

    async def _stop_stream(self) -> None:
        self._close_stream()
        self._set_active(False)
        log.info("live mic capture_stopped")

    def _close_stream(self) -> None:
        # Drop any dev audio-level preview so a stale level never lingers once
        # the mic stops (no-op unless the dev flag is set).
        try:
            from kaine import perception_preview

            perception_preview.set_audio_level(None)
        except Exception:
            pass
        stream = self._stream
        self._stream = None
        if stream is None:
            return
        try:
            stream.stop()
        except Exception:
            log.debug("stream.stop raised", exc_info=True)
        try:
            stream.close()
        except Exception:
            log.debug("stream.close raised", exc_info=True)

    def _on_audio_frame_threadsafe(self, frame: bytes) -> None:
        """Called from the sounddevice callback thread. Hands the PCM
        frame to the asyncio loop via call_soon_threadsafe."""
        loop = self._loop
        queue = self._pcm_queue
        if loop is None or queue is None:
            return

        def _put():
            try:
                queue.put_nowait(frame)
            except asyncio.QueueFull:
                # Drop oldest, push newest — recent audio matters more.
                try:
                    queue.get_nowait()
                    queue.put_nowait(frame)
                except (asyncio.QueueEmpty, asyncio.QueueFull):
                    pass

        loop.call_soon_threadsafe(_put)

    def _build_vad(self) -> _VAD:
        if self._vad_factory is not None:
            return self._vad_factory()
        if self._cfg.vad_backend == "rms":
            return _RMSVAD()
        return _load_webrtcvad(self._cfg.vad_aggressiveness)

    async def _consume_one_utterance(self) -> None:
        vad = self._build_vad()
        sample_rate = self._cfg.sample_rate
        frame_ms = self._cfg.vad_frame_ms
        hangover_frames = max(1, self._cfg.silence_hangover_ms // frame_ms)
        max_frames = max(hangover_frames + 1, self._cfg.max_utterance_ms // frame_ms)
        min_frames = max(1, self._cfg.min_utterance_ms // frame_ms)

        assert self._pcm_queue is not None
        buffer: list[bytes] = []
        silent_run = 0
        in_speech = False

        while not self._stopped.is_set() and self._active:
            if self._desired_reader is not None and not self._read_desired():
                await self._stop_stream()
                return
            try:
                frame = await asyncio.wait_for(
                    self._pcm_queue.get(),
                    timeout=self._cfg.desired_state_poll_ms / 1000.0,
                )
            except asyncio.TimeoutError:
                continue
            # Dev-gated audio-level tap (KAINE_PERCEPTION_PREVIEW=1): publish the
            # current normalised RMS of this PCM frame so a Nexus meter can show
            # how loud what the entity hears is. Metadata only (a single float) —
            # no PCM is retained or persisted; no-op unless the dev flag is set.
            _tap_audio_level(frame, self._cfg.sample_rate)
            try:
                speaking = vad.is_speech(frame, sample_rate)
            except Exception:
                log.debug("VAD raised on a frame; treating as silence", exc_info=True)
                speaking = False
            if not in_speech:
                if speaking:
                    in_speech = True
                    silent_run = 0
                    buffer = [frame]
                    log.info("live mic utterance_started")
                    continue
                # Silent frames between utterances — discard immediately.
                continue
            buffer.append(frame)
            if speaking:
                silent_run = 0
            else:
                silent_run += 1
            if silent_run >= hangover_frames or len(buffer) >= max_frames:
                await self._flush_utterance(buffer, min_frames)
                return

    async def _flush_utterance(self, frames: list[bytes], min_frames: int) -> None:
        try:
            if len(frames) < min_frames:
                log.info("live mic utterance_ended duration_frames=%d (below min)", len(frames))
                return
            pcm = b"".join(frames)
            wav_bytes = encode_wav(
                pcm,
                sample_rate=self._cfg.sample_rate,
                channels=self._cfg.channels,
            )
            log.info(
                "live mic utterance_ended frames=%d pcm_bytes=%d wav_bytes=%d",
                len(frames),
                len(pcm),
                len(wav_bytes),
            )
            try:
                # AudioInput.process_audio takes source_label keyword-only.
                # Some sinks (tests) accept it positionally; fall back below.
                await self._sink(
                    wav_bytes,
                    self._cfg.sample_rate,
                    source_label=self._cfg.source_label,
                )
            except TypeError:
                try:
                    await self._sink(
                        wav_bytes, self._cfg.sample_rate, self._cfg.source_label
                    )
                except Exception:
                    log.exception("live mic sink raised (fallback path)")
            except Exception:
                log.exception("live mic sink raised")
        finally:
            # Drop every reference so GC can reclaim the buffer eagerly.
            frames.clear()

    def _set_active(self, active: bool) -> None:
        with self._lock:
            if self._active == active:
                return
            self._active = active
        if self._state_writer is not None:
            try:
                self._state_writer(active)
            except Exception:
                log.warning("perception state_writer raised", exc_info=True)
        if self._on_state_change is not None:
            try:
                self._on_state_change(
                    "capture_started" if active else "capture_stopped",
                    {"surface": "audio", "device": self._cfg.device},
                )
            except Exception:
                log.debug("on_state_change raised", exc_info=True)
