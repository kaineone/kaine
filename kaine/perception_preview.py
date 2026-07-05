# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Dev-gated, in-memory perception PREVIEW holder (never persisted).

The live perception path is eyes and ears, not a recorder: raw frames/audio are
transduced and dropped (topos.out / audition.out carry metadata only, no
pixels/PCM). This module adds the *explicit development override* the privacy
architecture (paper §4.4) allows for cognitive content: when the operator sets
the dev flag ``KAINE_PERCEPTION_PREVIEW=1`` the perception modules may mirror the
single most-recent frame (JPEG) and the current audio level into a process-local
holder so a Nexus diagnostic can show what the entity is currently seeing/hearing.

Load-bearing invariants (zero raw-sense persistence):
  * OFF by default. With the flag unset every write is a no-op and every read
    returns ``None`` — the preview simply does not exist.
  * The holder is a SINGLE overwritten slot in ordinary process memory. It opens
    NO file, touches NO disk, and uses NO OS shared-memory object — nothing here
    can land raw sense data on durable storage.
  * Because it is process-local, the holder only carries a preview when the
    perception module and the reader run in the SAME process. A reader in a
    separate process (a standalone ``python -m kaine.nexus``) sees an empty slot
    and its route 404s / the PiP stays hidden — an honest "no preview" rather
    than a cross-process frame channel (which would require a named RAM segment,
    i.e. a file, and is therefore intentionally NOT built here).
"""
from __future__ import annotations

import os
import threading
from typing import Optional

DEV_ENV_VAR = "KAINE_PERCEPTION_PREVIEW"


def preview_enabled() -> bool:
    """True only when the operator's explicit dev override is set.

    Read live (not cached) so a test / operator can toggle it per process. Any
    value other than exactly ``"1"`` is treated as disabled.
    """
    return os.environ.get(DEV_ENV_VAR) == "1"


class _PreviewHolder:
    """A single overwritten in-memory slot for the latest frame + audio level.

    No file, no disk, no OS shared memory — just two Python attributes guarded by
    a lock. Writes are dropped unless the dev flag is set; reads always return the
    current slot (``None`` when empty)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._video_jpeg: Optional[bytes] = None
        self._audio_level: Optional[float] = None

    # ---- video ----------------------------------------------------------
    def set_video_jpeg(self, data: Optional[bytes]) -> None:
        """Overwrite the single frame slot. No-op unless the dev flag is set."""
        if not preview_enabled():
            return
        with self._lock:
            self._video_jpeg = bytes(data) if data else None

    def get_video_jpeg(self) -> Optional[bytes]:
        with self._lock:
            return self._video_jpeg

    # ---- audio level ----------------------------------------------------
    def set_audio_level(self, rms: Optional[float]) -> None:
        """Overwrite the current audio level (normalised RMS). No-op unless the
        dev flag is set."""
        if not preview_enabled():
            return
        with self._lock:
            self._audio_level = float(rms) if rms is not None else None

    def get_audio_level(self) -> Optional[float]:
        with self._lock:
            return self._audio_level

    # ---- lifecycle ------------------------------------------------------
    def clear(self) -> None:
        """Drop both slots — called on perception shutdown and in tests so no
        stale preview lingers in memory once capture stops."""
        with self._lock:
            self._video_jpeg = None
            self._audio_level = None


# Process-global holder. Both the perception writers (Topos/Audition) and the
# Nexus preview reader resolve THIS instance, so a preview is visible only within
# one process (see the module docstring's cross-process note).
_HOLDER = _PreviewHolder()


def holder() -> _PreviewHolder:
    return _HOLDER


# Convenience module-level accessors (thin wrappers over the singleton).
def set_video_jpeg(data: Optional[bytes]) -> None:
    _HOLDER.set_video_jpeg(data)


def get_video_jpeg() -> Optional[bytes]:
    return _HOLDER.get_video_jpeg()


def set_audio_level(rms: Optional[float]) -> None:
    _HOLDER.set_audio_level(rms)


def get_audio_level() -> Optional[float]:
    return _HOLDER.get_audio_level()


def clear() -> None:
    _HOLDER.clear()


def encode_jpeg_preview(image: object, *, quality: int = 50) -> Optional[bytes]:
    """JPEG-encode a PIL image entirely in memory (BytesIO — never a file path).

    Returns ``None`` (rather than raising) when the object is not a PIL image or
    Pillow is unavailable, so the preview tap can never break the perception
    path. The encode writes ONLY into an ``io.BytesIO`` — it opens no file.
    """
    save = getattr(image, "save", None)
    if save is None:
        return None
    try:
        import io

        buf = io.BytesIO()
        # RGBA/other modes → RGB so JPEG can encode them.
        img = image
        mode = getattr(image, "mode", None)
        if mode not in (None, "RGB", "L"):
            to_rgb = getattr(image, "convert", None)
            if to_rgb is not None:
                img = to_rgb("RGB")
        img.save(buf, format="JPEG", quality=int(quality))
        return buf.getvalue()
    except Exception:
        return None
