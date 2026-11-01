# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The programme under stimulus control: its channels and a seekable clock.

:class:`ProgrammeClock` is a :class:`~kaine.modules.vision.feed.PlaylistClock`
that both playlist feeds share in place of the plain clock when stimulus
control is enabled. Elapsed time stays the perceived programme time: it
excludes every paused span, as before. What the feeds present is read through
an anchor that a seek or a channel switch moves:

    presented = anchor_presented + (perceived - anchor_perceived)   (mod channel length)

so ``next`` and ``previous`` land on the start of the adjacent item and wrap at
both ends, and running past a channel's last item wraps to its first. The
viewing ends when perceived time reaches the length of channel 0, the
operator's programme, whatever was skipped or chosen (design D2): skipping
changes what the entity sees, not how long it is awake, and cannot end its
viewing. ``locate()`` then returns the past-the-end index, which the
end-of-programme watcher reads as before.

Without a seek or a channel switch, the presented position equals perceived
time and ``locate()`` walks the same durations as the plain clock, so the
mapping is the plain clock's until the programme ends.

``position_epoch()`` changes whenever the presented position jumps (a seek, a
switch, or a wrap past a channel's end); the feeds compare it to know when to
reopen their decoders.

A channel is one operator manifest. The feeds read one combined manifest (every
channel's items in turn, with absolute paths) so a channel is a contiguous run of
items in it.
"""
from __future__ import annotations

import logging
import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence

from kaine.modules.effectors.stimulus.config import StimulusControlError
from kaine.modules.vision.feed import (
    PlaylistClock,
    PlaylistItem,
    PlaylistManifest,
    load_playlist_manifest,
)

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Programme:
    """The combined manifest the feeds read, and each channel's run of items."""

    manifest: PlaylistManifest
    segments: tuple[tuple[int, int], ...]  # (first item index, item count) per channel
    channel_manifests: tuple[PlaylistManifest, ...]

    @property
    def channel_count(self) -> int:
        return len(self.segments)

    def channel_of(self, item_idx: int) -> int | None:
        for k, (first, count) in enumerate(self.segments):
            if first <= item_idx < first + count:
                return k
        return None

    def descriptor(self) -> list[dict[str, Any]]:
        """Per-channel manifest digests for the run manifest (no paths)."""
        return [m.as_descriptor() for m in self.channel_manifests]


def _absolute_items(manifest: PlaylistManifest) -> list[PlaylistItem]:
    root = Path(manifest.manifest_path).parent
    items = []
    for it in manifest.items:
        p = Path(it.path)
        media = p if p.is_absolute() else (root / p)
        items.append(PlaylistItem(path=str(media), sha256=it.sha256, fps=it.fps, order=it.order))
    return items


def load_programme(primary_manifest: str, channels: Sequence[str] = ()) -> Programme:
    """Load channel 0 from ``primary_manifest`` and each further channel in turn.

    With one channel the combined manifest is channel 0's manifest unchanged.
    """
    primary = load_playlist_manifest(primary_manifest)
    manifests = [primary] + [load_playlist_manifest(p) for p in channels]
    if len(manifests) == 1:
        return Programme(
            manifest=primary,
            segments=((0, len(primary.items)),),
            channel_manifests=(primary,),
        )
    items: list[PlaylistItem] = []
    segments: list[tuple[int, int]] = []
    for m in manifests:
        segments.append((len(items), len(m.items)))
        items.extend(_absolute_items(m))
    combined = PlaylistManifest(manifest_path=primary.manifest_path, items=tuple(items))
    return Programme(
        manifest=combined, segments=tuple(segments), channel_manifests=tuple(manifests)
    )


def _probe_cv2(path: str, fps: float) -> float | None:
    try:
        import cv2  # type: ignore[import-untyped]
    except ImportError:
        return None
    cap = cv2.VideoCapture(path)
    try:
        if not cap.isOpened():
            return None
        frames = float(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    finally:
        cap.release()
    if frames > 0 and fps > 0:
        return frames / float(fps)
    return None


def _probe_av(path: str) -> float | None:
    try:
        import av  # type: ignore[import-untyped]
    except ImportError:
        return None
    container = av.open(path)
    try:
        if container.duration:
            return float(container.duration) / 1_000_000.0
    finally:
        container.close()
    return None


def probe_durations(
    manifest: PlaylistManifest,
    clock: PlaylistClock,
    *,
    probe: Callable[[PlaylistItem], float | None] | None = None,
) -> None:
    """Register every item's duration on ``clock`` before playback.

    Wrapping and the perceived-time end need the whole programme's length up
    front. The default probe uses the video source's own rule (frame count over
    the manifest's fps), so the first-writer-wins registration matches what the
    video source would register, and PyAV's container duration when OpenCV is
    absent (as the audio source would). Any item that cannot be measured raises
    :class:`StimulusControlError`.
    """

    def _default(item: PlaylistItem) -> float | None:
        seconds = _probe_cv2(item.path, item.fps)
        if seconds is None:
            seconds = _probe_av(item.path)
        return seconds

    measure = probe or _default
    root = Path(manifest.manifest_path).parent
    for idx, item in enumerate(manifest.items):
        p = Path(item.path)
        resolved = item if p.is_absolute() else PlaylistItem(
            path=str(root / p), sha256=item.sha256, fps=item.fps, order=item.order
        )
        try:
            seconds = measure(resolved)
        except Exception as exc:
            raise StimulusControlError(
                f"stimulus control cannot measure programme item {idx}: {type(exc).__name__}"
            ) from exc
        if seconds is None or not math.isfinite(seconds) or seconds <= 0.0:
            raise StimulusControlError(
                f"stimulus control cannot measure programme item {idx} (order={item.order})"
            )
        clock.set_duration(idx, seconds)


class ProgrammeClock(PlaylistClock):
    """The shared playlist clock with seek, channels and the perceived-time end."""

    def __init__(
        self,
        item_count: int,
        *,
        segments: Sequence[tuple[int, int]] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        super().__init__(item_count, clock=clock)
        segs = tuple(segments) if segments else ((0, int(item_count)),)
        expected = 0
        for first, count in segs:
            if first != expected or count < 1:
                raise ValueError("programme channels must be contiguous, non-empty runs of items")
            expected = first + count
        if expected != int(item_count):
            raise ValueError("programme channels must cover every item")
        self._segments = segs
        self._channel = 0
        self._anchor_perceived = 0.0
        self._anchor_presented = 0.0
        self._repositions = 0

    # -- channel arithmetic (all *_locked helpers expect self._lock held) --

    @property
    def item_count(self) -> int:
        return self._n

    @property
    def channel_count(self) -> int:
        return len(self._segments)

    @property
    def channel(self) -> int:
        with self._lock:
            return self._channel

    def _channel_length_locked(self, channel: int) -> float | None:
        first, count = self._segments[channel]
        total = 0.0
        for idx in range(first, first + count):
            d = self._durations[idx]
            if d is None:
                return None
            total += d
        return total

    @property
    def viewing_length(self) -> float | None:
        """Perceived programme time at which the viewing ends (channel 0's length)."""
        with self._lock:
            return self._channel_length_locked(0)

    def _item_start_locked(self, channel: int, local_idx: int) -> float:
        first, _ = self._segments[channel]
        acc = 0.0
        for idx in range(first, first + local_idx):
            acc += self._durations[idx] or 0.0
        return acc

    def _walk_locked(self, elapsed: float) -> tuple[int, float]:
        # The plain clock's walk, for a programme whose durations are not all known.
        acc = 0.0
        for idx in range(self._n):
            d = self._durations[idx]
            if d is None:
                return idx, max(0.0, elapsed - acc)
            if elapsed < acc + d:
                return idx, elapsed - acc
            acc += d
        return self._n, 0.0

    def _presented_locked(self, perceived: float) -> tuple[int, int, float] | None:
        """``(lap, item index, offset)`` on the current channel; None if unmeasured."""
        length = self._channel_length_locked(self._channel)
        if length is None or length <= 0.0:
            return None
        t = max(0.0, self._anchor_presented + (perceived - self._anchor_perceived))
        lap = int(t // length)
        local = t - lap * length
        first, count = self._segments[self._channel]
        acc = 0.0
        for idx in range(first, first + count):
            d = self._durations[idx] or 0.0
            if local < acc + d:
                return lap, idx, local - acc
            acc += d
        # Rounding put ``local`` on the channel's end: that is the next lap's start.
        return lap + 1, first, 0.0

    def _ended_locked(self, perceived: float) -> bool:
        length = self._channel_length_locked(0)
        return length is not None and perceived >= length

    def locate(self, elapsed: float | None = None) -> tuple[int, float]:
        with self._lock:
            perceived = self._elapsed_locked() if elapsed is None else float(elapsed)
            if self._ended_locked(perceived):
                return self._n, 0.0
            pos = self._presented_locked(perceived)
            if pos is None:
                return self._walk_locked(perceived)
            _, idx, offset = pos
            return idx, offset

    def ended(self) -> bool:
        """True once perceived programme time reaches the viewing length."""
        with self._lock:
            return self._ended_locked(self._elapsed_locked())

    def position_epoch(self) -> tuple[int, int]:
        """Changes whenever the presented position jumps (seek, switch, wrap)."""
        with self._lock:
            pos = self._presented_locked(self._elapsed_locked())
            return self._repositions, (pos[0] if pos is not None else 0)

    def current_position(self) -> tuple[int, int, int]:
        """``(channel, item index, local index in the channel)`` presented now."""
        with self._lock:
            perceived = self._elapsed_locked()
            pos = self._presented_locked(perceived)
            first, _ = self._segments[self._channel]
            if pos is None:
                idx, _ = self._walk_locked(perceived)
            else:
                idx = pos[1]
            return self._channel, idx, idx - first

    def _anchor_locked(self, channel: int, local_idx: int) -> None:
        self._channel = channel
        self._anchor_perceived = self._elapsed_locked()
        self._anchor_presented = self._item_start_locked(channel, local_idx)
        self._repositions += 1

    def seek(self, step: int) -> int:
        """Move to the start of the item ``step`` items away, wrapping; return its index.

        Requires every duration of the current channel to be known.
        """
        with self._lock:
            pos = self._presented_locked(self._elapsed_locked())
            if pos is None:
                raise StimulusControlError("programme durations are not all known")
            first, count = self._segments[self._channel]
            local = (pos[1] - first + int(step)) % count
            self._anchor_locked(self._channel, local)
            return first + local

    def switch_channel(self, channel: int) -> int:
        """Move to the start of channel ``channel``; return its first item index."""
        with self._lock:
            if not 0 <= channel < len(self._segments):
                raise StimulusControlError(f"no programme channel {channel}")
            if self._channel_length_locked(channel) is None:
                raise StimulusControlError("programme durations are not all known")
            self._anchor_locked(channel, 0)
            return self._segments[channel][0]


__all__ = [
    "Programme",
    "ProgrammeClock",
    "load_programme",
    "probe_durations",
]
