# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Synthetic programme media for the stimulus-control tests.

Each clip is a real media file (MPEG-4 video plus PCM audio in Matroska)
written with PyAV under the test's tmp_path: a solid colour and a pure tone, so
a test can tell from a decoded frame or a PCM block which item it came from.
These are input fixtures only; the sources under test never write.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np

RATE = 16000
WIDTH = 64
HEIGHT = 48


def make_clip(path: Path, *, rgb: tuple[int, int, int], tone_hz: float, seconds: float, fps: int = 10) -> None:
    import av  # type: ignore[import-untyped]

    container = av.open(str(path), mode="w")
    video = container.add_stream("mpeg4", rate=fps)
    video.width, video.height, video.pix_fmt = WIDTH, HEIGHT, "yuv420p"
    audio = container.add_stream("pcm_s16le", rate=RATE)
    audio.layout = "mono"
    image = np.zeros((HEIGHT, WIDTH, 3), np.uint8)
    image[:] = rgb
    for i in range(int(round(seconds * fps))):
        frame = av.VideoFrame.from_ndarray(image, format="rgb24")
        frame.pts = i
        for packet in video.encode(frame):
            container.mux(packet)
    for packet in video.encode(None):
        container.mux(packet)
    t = np.arange(int(RATE * seconds))
    samples = (0.25 * np.sin(2 * np.pi * tone_hz * t / RATE) * 32767).astype(np.int16)
    for k in range(0, len(samples), 1600):
        chunk = av.AudioFrame.from_ndarray(
            samples[k:k + 1600].reshape(1, -1), format="s16", layout="mono"
        )
        chunk.rate = RATE
        chunk.pts = k
        for packet in audio.encode(chunk):
            container.mux(packet)
    for packet in audio.encode(None):
        container.mux(packet)
    container.close()


def write_manifest(directory: Path, items: list[tuple[str, tuple[int, int, int], float, float]], *, fps: int = 10, name: str = "programme.toml") -> Path:
    """Write clips ``(file name, rgb, tone_hz, seconds)`` and their checksummed manifest."""
    directory.mkdir(parents=True, exist_ok=True)
    lines = []
    for file_name, rgb, tone_hz, seconds in items:
        media = directory / file_name
        make_clip(media, rgb=rgb, tone_hz=tone_hz, seconds=seconds, fps=fps)
        digest = hashlib.sha256(media.read_bytes()).hexdigest()
        lines.append(f'[[item]]\npath = "{file_name}"\nsha256 = "{digest}"\nfps = {fps}\n')
    manifest = directory / name
    manifest.write_text("\n".join(lines), encoding="utf-8")
    return manifest


def dominant_bgr(frame: np.ndarray) -> tuple[int, int, int]:
    """The frame's mean colour as BGR integers (decoded frames are BGR)."""
    b, g, r = (int(round(float(c))) for c in frame.reshape(-1, 3).mean(axis=0))
    return b, g, r


def tone_of(pcm: bytes) -> float:
    """The dominant frequency of an int16 mono block, in Hz (0 for silence)."""
    x = np.frombuffer(pcm, dtype="<i2").astype(np.float64)
    if not np.any(x):
        return 0.0
    spectrum = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    freqs = np.fft.rfftfreq(len(x), d=1.0 / RATE)
    return float(freqs[int(np.argmax(spectrum))])


def rms(pcm: bytes) -> float:
    x = np.frombuffer(pcm, dtype="<i2").astype(np.float64)
    return float(np.sqrt(np.mean(x * x))) if len(x) else 0.0
