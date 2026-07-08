# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Attention-driven foveation core — spatial attention and view derivation.

Given a native-resolution frame, compute a coarse spatial saliency map (per-tile
change), select a single fovea target by the precision-weighted combination of that
bottom-up saliency with an optional top-down bias, size the fovea from arousal
(Easterbrook narrowing — higher arousal, tighter fovea), and derive a downsampled
peripheral view plus a high-resolution foveal crop from the *same* in-memory frame.

Pure and dependency-light (numpy + a lazily-imported cv2 for resizes). No disk I/O:
frames and views exist only in memory, preserving the zero-raw-sense-data invariant.
The direction and exact magnitude of the arousal→size mapping are tuning parameters,
not asserted results. This is the algorithmic heart; Topos wires it into the
perception path and the capture layer supplies the native frame.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np


@dataclass(frozen=True)
class FoveaTarget:
    """Normalized fovea. ``x``/``y`` are the centre in [0, 1]; ``size`` is the crop
    half-extent as a fraction of ``min(H, W)`` in [0, 1]. Content-free."""

    x: float
    y: float
    size: float

    def to_dict(self) -> dict[str, float]:
        return {"x": float(self.x), "y": float(self.y), "size": float(self.size)}


def _lazy_cv2() -> Any:
    try:
        import cv2  # type: ignore[import-untyped]

        return cv2
    except ImportError as exc:
        from kaine.modules.topos.live import PerceptionUnavailableError

        raise PerceptionUnavailableError(
            "opencv-python-headless is required for foveation; "
            "install with: pip install -e .[vision]"
        ) from exc


def tile_change(
    frame: np.ndarray, prev_tiles: np.ndarray | None, *, grid: tuple[int, int]
) -> tuple[np.ndarray, np.ndarray]:
    """Reduce ``frame`` to per-tile grayscale means on ``grid`` and return
    ``(change_map, tiles)`` where change is the absolute difference against
    ``prev_tiles`` (zeros on the first frame)."""
    cv2 = _lazy_cv2()
    gh, gw = grid
    gray = frame.mean(axis=2) if frame.ndim == 3 else frame
    tiles = cv2.resize(gray.astype(np.float32), (gw, gh), interpolation=cv2.INTER_AREA)
    if prev_tiles is None:
        return np.zeros((gh, gw), dtype=np.float32), tiles
    return np.abs(tiles - prev_tiles).astype(np.float32), tiles


class SpatialSaliency:
    """Stateful coarse per-tile change map over consecutive frames (memory only)."""

    def __init__(self, grid: tuple[int, int] = (12, 12)) -> None:
        self._grid = (int(grid[0]), int(grid[1]))
        self._prev: np.ndarray | None = None

    @property
    def grid(self) -> tuple[int, int]:
        return self._grid

    def observe(self, frame: np.ndarray) -> np.ndarray:
        change, self._prev = tile_change(frame, self._prev, grid=self._grid)
        return change


def combine_saliency(
    bottom_up: np.ndarray,
    top_down: np.ndarray | None = None,
    *,
    w_bottom_up: float = 1.0,
    w_top_down: float = 1.0,
) -> np.ndarray:
    """Precision-weighted combination of a bottom-up saliency map with an optional
    same-shape top-down bias map. The weights are precisions."""
    bu = np.asarray(bottom_up, dtype=np.float32)
    if top_down is None:
        return w_bottom_up * bu
    td = np.asarray(top_down, dtype=np.float32)
    if td.shape != bu.shape:
        raise ValueError(f"top_down shape {td.shape} != bottom_up shape {bu.shape}")
    return w_bottom_up * bu + w_top_down * td


def arousal_to_size(
    arousal: float, *, size_range: tuple[float, float] = (0.12, 0.5)
) -> float:
    """Map arousal in [0, 1] to a normalized fovea size. Easterbrook narrowing:
    higher arousal → tighter fovea (nearer ``size_range`` min). The sign is a tuning
    choice; flip ``size_range`` to widen under arousal instead."""
    lo, hi = size_range
    a = float(np.clip(arousal, 0.0, 1.0))
    return hi - (hi - lo) * a


def select_fovea(
    saliency: np.ndarray,
    *,
    arousal: float = 0.0,
    size_range: tuple[float, float] = (0.12, 0.5),
    prev: FoveaTarget | None = None,
    hysteresis: float = 0.0,
) -> FoveaTarget:
    """Select the single fovea target: the argmax tile of ``saliency`` (a grid map),
    sized from arousal. When the map is flat (no salient region) the target is the
    centre. Hysteresis holds ``prev`` unless the new argmax beats the saliency at
    ``prev``'s tile by more than ``hysteresis`` (fraction), damping thrash between
    comparable tiles."""
    sal = np.asarray(saliency, dtype=np.float32)
    gh, gw = sal.shape
    size = arousal_to_size(arousal, size_range=size_range)
    if float(sal.max()) <= float(sal.min()):  # flat / all-zero → no salient region
        return FoveaTarget(0.5, 0.5, size)
    flat = int(np.argmax(sal))
    ty, tx = divmod(flat, gw)
    if prev is not None and hysteresis > 0.0:
        pty = min(gh - 1, int(prev.y * gh))
        ptx = min(gw - 1, int(prev.x * gw))
        if float(sal[ty, tx]) <= float(sal[pty, ptx]) * (1.0 + hysteresis):
            return FoveaTarget(prev.x, prev.y, size)  # hold location, resize
    return FoveaTarget((tx + 0.5) / gw, (ty + 0.5) / gh, size)


def foveate(
    frame: np.ndarray,
    target: FoveaTarget,
    *,
    peripheral_size: tuple[int, int] = (320, 180),
    foveal_size: tuple[int, int] = (224, 224),
) -> tuple[np.ndarray, np.ndarray]:
    """From a native ``frame`` (H, W, 3) return ``(peripheral, foveal)`` arrays, both
    derived from the one in-memory frame. ``peripheral`` is the whole frame resized
    to ``peripheral_size`` (w, h); ``foveal`` is the native crop centred on
    ``target`` at half-extent ``target.size * min(H, W)``, resized to ``foveal_size``
    (w, h)."""
    cv2 = _lazy_cv2()
    h, w = frame.shape[:2]
    pw, ph = peripheral_size
    peripheral = cv2.resize(frame, (pw, ph), interpolation=cv2.INTER_AREA)
    half = max(1, int(round(target.size * min(h, w))))
    cx, cy = int(round(target.x * w)), int(round(target.y * h))
    x0 = max(0, min(w - 1, cx - half))
    x1 = max(x0 + 1, min(w, cx + half))
    y0 = max(0, min(h - 1, cy - half))
    y1 = max(y0 + 1, min(h, cy + half))
    fw, fh = foveal_size
    foveal = cv2.resize(frame[y0:y1, x0:x1], (fw, fh), interpolation=cv2.INTER_AREA)
    return peripheral, foveal
