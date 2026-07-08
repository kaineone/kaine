# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Cross-platform desktop-audio capture as an Audition ``_AudioStream``.

The companion to screen capture: when the entity watches a shared screen, this is
how it *hears* what is playing there — a media player, a browser, a game — by
capturing the desktop audio **monitor** (a loopback of the output). Like screen
capture it goes through the system ffmpeg binary, the one tool carrying every
platform's audio input device: ``pulse`` on Linux (a sink's ``.monitor`` source),
``dshow`` on Windows (a loopback device), ``avfoundation`` on macOS (a loopback
device index). Only the per-OS input spec differs; it is a pure function
(:func:`audio_capture_spec`), unit-tested per platform.

The stream emits int16 little-endian PCM to Audition's callback exactly like the
microphone source, so the VAD/utterance path downstream is unchanged. A reader
thread pulls fixed PCM blocks from ffmpeg and dispatches them; the process spawner
is injected so the block/lifecycle logic is testable without an audio device. As
with all perception, audio is held in memory and released, never written to disk.
"""

from __future__ import annotations

import logging
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from typing import Any, Callable

log = logging.getLogger(__name__)


def current_platform() -> str:
    """Coarse platform key: 'windows' | 'darwin' | 'linux'."""
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform == "darwin":
        return "darwin"
    return "linux"


@dataclass(frozen=True)
class AudioCaptureSpec:
    """The ffmpeg *input* arguments for one OS's desktop-audio monitor."""

    input_args: list[str] = field(default_factory=list)


def audio_capture_spec(device: str, *, platform: str | None = None) -> AudioCaptureSpec:
    """Pure per-OS mapping of a monitor ``device`` to ffmpeg input arguments.

    Linux uses ``pulse`` with a monitor source name (e.g.
    ``alsa_output....monitor``); Windows uses ``dshow`` with an audio loopback
    device name; macOS uses ``avfoundation`` with an audio-only device index
    (``:<index>``). The operator names the device (there is no universal default
    loopback); on Linux :func:`default_monitor_source` can supply the default
    sink's monitor.
    """
    platform = platform or current_platform()
    if not device:
        raise ValueError(
            "desktop-audio capture requires a monitor device "
            "(Linux: a pulse '<sink>.monitor' source; Windows: a dshow loopback "
            "device; macOS: an avfoundation audio index)"
        )
    if platform == "windows":
        return AudioCaptureSpec(["-f", "dshow", "-i", f"audio={device}"])
    if platform == "darwin":
        return AudioCaptureSpec(["-f", "avfoundation", "-i", f":{device}"])
    return AudioCaptureSpec(["-f", "pulse", "-i", device])


def default_monitor_source() -> str | None:
    """Best-effort Linux default desktop-audio monitor: the default sink's
    ``.monitor`` source, via ``pactl``. Returns None if it cannot be determined."""
    try:
        out = subprocess.run(
            ["pactl", "get-default-sink"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        return None
    sink = out.stdout.strip()
    return f"{sink}.monitor" if sink else None


def _default_open_process(cmd: list[str]) -> Any:
    """Spawn ffmpeg for audio capture; raise if the binary is absent."""
    from kaine.modules.audition.live import PerceptionUnavailableError

    try:
        return subprocess.Popen(  # noqa: S603 — cmd is built from a fixed spec
            cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0
        )
    except FileNotFoundError as exc:
        raise PerceptionUnavailableError(
            "ffmpeg not found on PATH — desktop-audio capture requires the system "
            "ffmpeg binary (Debian/Ubuntu: apt install ffmpeg)"
        ) from exc


class MonitorAudioStream:
    """An Audition ``_AudioStream`` backed by a system-ffmpeg desktop-audio monitor.

    ``start()`` spawns ffmpeg emitting int16 LE PCM and a reader thread that hands
    fixed ``frames_per_block`` PCM blocks to ``callback`` (the microphone source's
    contract); ``stop()`` / ``close()`` end ffmpeg and the thread. The process
    spawner is injected so the block/lifecycle logic is testable without an audio
    device.
    """

    def __init__(
        self,
        spec: AudioCaptureSpec,
        *,
        sample_rate: int,
        channels: int,
        frames_per_block: int,
        callback: Callable[[bytes], None],
        ffmpeg_path: str = "ffmpeg",
        open_process: Callable[[list[str]], Any] | None = None,
    ) -> None:
        self._spec = spec
        self._sample_rate = int(sample_rate)
        self._channels = int(channels)
        self._callback = callback
        self._ffmpeg_path = ffmpeg_path
        self._open_process = open_process or _default_open_process
        # int16 => 2 bytes per sample per channel
        self._block_bytes = max(1, int(frames_per_block)) * self._channels * 2
        self._proc: Any = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    def command(self) -> list[str]:
        """The full ffmpeg command: the OS monitor input, resampled to the target
        rate/channels, emitted as raw s16le on stdout."""
        return [
            self._ffmpeg_path,
            "-hide_banner",
            "-loglevel",
            "error",
            *self._spec.input_args,
            "-ar",
            str(self._sample_rate),
            "-ac",
            str(self._channels),
            "-f",
            "s16le",
            "-",
        ]

    def start(self) -> None:
        if self._proc is not None:
            return
        self._stop.clear()
        self._proc = self._open_process(self.command())
        self._thread = threading.Thread(
            target=self._pump, name="monitor-audio", daemon=True
        )
        self._thread.start()

    def _pump(self) -> None:
        proc = self._proc
        if proc is None or proc.stdout is None:
            return
        n = self._block_bytes
        while not self._stop.is_set():
            data = _read_exact(proc.stdout, n)
            if data is None:
                break
            try:
                self._callback(data)
            except Exception:
                log.debug("monitor audio callback raised", exc_info=True)

    def stop(self) -> None:
        self._stop.set()
        proc, self._proc = self._proc, None
        if proc is not None:
            try:
                proc.terminate()
                proc.wait(timeout=2)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    log.debug("monitor audio kill raised", exc_info=True)
        thread, self._thread = self._thread, None
        if thread is not None and thread.is_alive():
            thread.join(timeout=2)

    def close(self) -> None:
        self.stop()


def _read_exact(stream: Any, n: int) -> bytes | None:
    """Read exactly ``n`` bytes from ``stream``, or None at EOF/short read."""
    buf = bytearray()
    while len(buf) < n:
        chunk = stream.read(n - len(buf))
        if not chunk:
            return None
        buf += chunk
    return bytes(buf)
