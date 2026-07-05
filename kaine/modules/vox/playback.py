# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Audio playback for vox.

Synthesized speech is played through the host's output device and then
released. This module provides:

- `Player` — the protocol vox depends on.
- `SoundDevicePlayer` — real playback via `sounddevice`, decoding the WAV
  in memory (no temp file). Playback is serialized so clips play in order
  and runs off the event loop. If `sounddevice`/PortAudio is unavailable it
  degrades to a no-op with a single warning, mirroring the live-perception
  soft-disable.
- `NullPlayer` — explicit no-op (playback disabled).
- `FakePlayer` — records played clips for tests.
- `build_player` / `wav_duration_s` helpers.
"""
from __future__ import annotations

import asyncio
import io
import logging
import wave
from typing import Optional, Protocol, runtime_checkable

log = logging.getLogger(__name__)


def wav_duration_s(audio: bytes) -> float:
    """Duration of a WAV clip in seconds, or 0.0 if it can't be parsed.

    Used to size the self-hearing window; a parse failure must never raise
    into the synthesis path, so it degrades to 0.0 (the hangover alone then
    bounds the window).
    """
    try:
        with wave.open(io.BytesIO(audio), "rb") as w:
            frames = w.getnframes()
            rate = w.getframerate()
            if rate <= 0:
                return 0.0
            return frames / float(rate)
    except Exception:
        return 0.0


@runtime_checkable
class Player(Protocol):
    async def play(self, audio: bytes, *, output_format: str = "wav") -> None: ...


class NullPlayer:
    """Playback disabled / unavailable. Does nothing, never raises."""

    async def play(self, audio: bytes, *, output_format: str = "wav") -> None:
        return None


class SoundDevicePlayer:
    """Plays WAV bytes on the configured (or default) output device.

    `sounddevice` is imported lazily on first play so construction never
    touches the audio system (keeps import/test cost off the hot path). On
    ImportError or a device error the player logs once and becomes a no-op
    for the rest of its life — synthesis and eventing continue unaffected.
    """

    def __init__(self, *, output_device: Optional[str | int] = None) -> None:
        self._device = output_device or None
        self._lock = asyncio.Lock()
        self._disabled = False
        self._warned = False

    def _warn_once(self, msg: str, exc: BaseException) -> None:
        if not self._warned:
            log.warning("%s; audio playback disabled for this run. (%s)", msg, exc)
            self._warned = True
        self._disabled = True

    async def play(self, audio: bytes, *, output_format: str = "wav") -> None:
        if self._disabled or not audio:
            return
        try:
            import numpy as np  # noqa: F401
            import sounddevice  # noqa: F401
        except Exception as exc:  # ImportError, or PortAudio not found
            self._warn_once("sounddevice/PortAudio unavailable", exc)
            return
        # Serialize so clips play in order even under concurrent syntheses.
        async with self._lock:
            try:
                await asyncio.to_thread(self._play_sync, audio)
            except Exception as exc:
                self._warn_once("audio playback failed", exc)

    def _play_sync(self, audio: bytes) -> None:
        import numpy as np
        import sounddevice as sd

        with wave.open(io.BytesIO(audio), "rb") as w:
            rate = w.getframerate()
            channels = w.getnchannels()
            sampwidth = w.getsampwidth()
            frames = w.readframes(w.getnframes())
        if sampwidth != 2:
            # Chatterbox emits 16-bit PCM; anything else we don't decode here.
            raise ValueError(f"unsupported sample width {sampwidth} bytes")
        data = np.frombuffer(frames, dtype=np.int16)
        if channels > 1:
            data = data.reshape(-1, channels)
        sd.play(data, rate, device=self._device)
        sd.wait()


class TeePlayer:
    """Plays through the primary player AND mirrors each clip to a tap.

    Used by ``Vox.add_playback_tap`` (e.g. the remote bridge streaming
    speech to operator clients). The primary plays first and its errors
    propagate exactly as before; a failing tap is logged and never breaks
    local playback.
    """

    def __init__(self, primary: Player, tap: Player) -> None:
        self._primary = primary
        self._tap = tap

    async def play(self, audio: bytes, *, output_format: str = "wav") -> None:
        try:
            await self._primary.play(audio, output_format=output_format)
        finally:
            try:
                await self._tap.play(audio, output_format=output_format)
            except Exception:
                log.warning(
                    "playback tap raised; local playback unaffected", exc_info=True
                )


class FakePlayer:
    """Records played clips; for tests. Never touches a device."""

    def __init__(self) -> None:
        self.played: list[bytes] = []

    async def play(self, audio: bytes, *, output_format: str = "wav") -> None:
        self.played.append(audio)


def build_player(
    *,
    playback_enabled: bool,
    output_device: str | int = "",
) -> Player:
    """Construct the player vox should use.

    `playback_enabled=False` → `NullPlayer`. Otherwise a `SoundDevicePlayer`
    (which itself degrades to a no-op if the audio system is unavailable).
    """
    if not playback_enabled:
        return NullPlayer()
    device: Optional[str | int] = output_device if output_device != "" else None
    return SoundDevicePlayer(output_device=device)
