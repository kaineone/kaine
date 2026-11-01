# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Fakes for the playlist perception feed: a scripted video decoder for
``PlaylistSource(decoder_factory=...)`` and a fake PyAV module for
``PlaylistAudioStream``. No media, no real decoder, nothing written.
"""

from __future__ import annotations

import os
from types import SimpleNamespace
from typing import Any, Callable

import numpy as np


class FakeVideoDecoder:
    """One item's video: frame ``i`` at ``times[i]`` seconds (``i / fps`` by
    default). A frame is ``(basename, i)`` unless ``frame_fn`` makes one.
    Keyframes every ``keyframe_every`` frames, for ``seek``."""

    def __init__(
        self,
        path: str,
        frame_count: int,
        fps: float,
        *,
        times: list[float] | None = None,
        duration: float | None | str = "auto",
        frame_fn: Callable[[int], Any] | None = None,
        keyframe_every: int = 10,
    ) -> None:
        self.path = os.path.basename(str(path))
        self._times = list(times) if times is not None else [i / fps for i in range(frame_count)]
        self.duration = (len(self._times) / fps) if duration == "auto" else duration
        self.frame_interval = 1.0 / fps
        self._frame_fn = frame_fn
        self._keyframe_every = max(1, keyframe_every)
        self._i = 0
        self.seeks: list[float] = []
        self.decoded = 0
        self.closed = False

    def next(self) -> tuple[float, Any] | None:
        if self._i >= len(self._times):
            return None
        i = self._i
        self._i += 1
        self.decoded += 1
        frame = self._frame_fn(i) if self._frame_fn is not None else (self.path, i)
        return self._times[i], frame

    def seek(self, seconds: float) -> None:
        self.seeks.append(seconds)
        at_or_before = [i for i, t in enumerate(self._times) if t <= seconds]
        idx = at_or_before[-1] if at_or_before else 0
        self._i = idx - (idx % self._keyframe_every)

    @staticmethod
    def image(frame: Any) -> Any:
        return frame

    def close(self) -> None:
        self.closed = True


class FakeVideoDecoders:
    """``decoder_factory(path, item)``: a ``FakeVideoDecoder`` per open, CFR
    at the manifest item's ``fps`` with ``frame_counts[basename]`` frames."""

    def __init__(self, frame_counts: dict[str, int] | int, **decoder_kwargs: Any) -> None:
        self._frame_counts = frame_counts
        self._kwargs = decoder_kwargs
        self.opened: list[FakeVideoDecoder] = []

    def __call__(self, path: Any, item: Any) -> FakeVideoDecoder:
        base = os.path.basename(str(path))
        n = self._frame_counts if isinstance(self._frame_counts, int) else self._frame_counts[base]
        decoder = FakeVideoDecoder(base, n, float(item.fps), **self._kwargs)
        self.opened.append(decoder)
        return decoder


class FakeAudioFrame:
    """A packed s16 audio frame whose plane is PADDED past its samples, the way
    PyAV's planes are: only ``samples`` and ``to_ndarray()`` are the audio."""

    def __init__(
        self,
        pcm: bytes,
        *,
        channels: int = 1,
        pts: int | None = None,
        time_base: float | None = None,
        sample_rate: int | None = None,
        plane_padding: int = 64,
    ) -> None:
        self._pcm = bytes(pcm)
        self.samples = len(self._pcm) // (2 * channels)
        self.pts = pts
        self.time_base = time_base
        if sample_rate is not None:
            self.sample_rate = sample_rate
        self.format = SimpleNamespace(name="s16", is_planar=False)
        self.planes = [self._pcm + b"\x7f" * plane_padding]

    def to_ndarray(self) -> np.ndarray:
        return np.frombuffer(self._pcm, dtype=np.int16).reshape(1, -1)


class PassThroughResampler:
    """A resampler that hands each frame back unchanged (flush yields none)."""

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs

    def resample(self, frame: Any) -> list[Any]:
        return [] if frame is None else [frame]


def fake_av_module(open_fn: Callable[[str], Any]) -> SimpleNamespace:
    """A stand-in ``av`` module: ``av.open`` is ``open_fn`` and the resampler
    passes frames through."""
    return SimpleNamespace(
        open=open_fn,
        audio=SimpleNamespace(resampler=SimpleNamespace(AudioResampler=PassThroughResampler)),
    )


class ConstantAudioContainer:
    """``frames`` frames of ``frame_bytes`` bytes of ``fill`` each, with a
    container duration in AV_TIME_BASE units; no timestamps."""

    def __init__(self, *, frames: int = 8, frame_bytes: int = 32_000, fill: int = 1,
                 duration_us: int = 8_000_000) -> None:
        self.duration = duration_us
        self.streams = SimpleNamespace(audio=[object()])
        self._frames = frames
        self._frame_bytes = frame_bytes
        self._fill = fill

    def decode(self, stream: Any):  # noqa: ANN201
        for _ in range(self._frames):
            yield FakeAudioFrame(bytes([self._fill]) * self._frame_bytes)

    def close(self) -> None:
        return None
