# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Deterministic perceptual-feed sources for reproducible research runs.

Both sources implement the ``_VideoSource`` protocol from
``kaine/modules/topos/live.py`` (``open()`` / ``read()`` / ``release()``) and
plug into ``LiveCamera`` via its ``source_factory`` seam. They return BGR uint8
ndarrays exactly like the cv2 camera path, so the downstream
BGR->RGB->PIL->``process_frame`` pipeline, habituation, and change-detection are
unchanged.

WHY DETERMINISTIC: a research run must present a bit-identical stimulus stream so
results replicate, and the stream must be copyright-free. Live camera / live
human input fail both. See openspec/changes/reproducible-perception-feed.

ZERO PERSISTENCE INVARIANT (eyes-and-ears): raw frames live only in process
memory. Neither source ever writes a frame to disk. The seeded source persists
only ``(seed, schedule)``; the playlist source persists nothing beyond the
manifest it is handed. The build-time guard in
tests/test_zero_persistence_invariant.py covers this module.
"""
from __future__ import annotations

import hashlib
import logging
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from kaine.modules.perception_prng import keyed_u64 as _keyed_u64
from kaine.modules.perception_prng import unit_float as _unit_float

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Seeded procedural source
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SeededSchedule:
    """Reproducible stimulus schedule. The whole stream is a pure function of
    these parameters plus the frame index — nothing else.

    ``width``/``height`` match the LiveCameraConfig frame geometry so the
    encoder sees the usual shape. ``surprise_interval`` is the base cadence (in
    frames) at which surprise events fire; ``surprise_strength`` scales their
    magnitude. The schedule carries no rendered pixels — only these knobs.
    """

    seed: int = 0
    width: int = 640
    height: int = 480
    surprise_interval: int = 150
    surprise_strength: float = 1.0

    def as_descriptor(self) -> dict[str, Any]:
        """The reproducible covariate: enough to regenerate the exact stream."""
        return {
            "seed": int(self.seed),
            "width": int(self.width),
            "height": int(self.height),
            "surprise_interval": int(self.surprise_interval),
            "surprise_strength": float(self.surprise_strength),
        }


@dataclass(frozen=True)
class _BaseParams:
    """Per-seed parameters of the learnable base visual world.

    Derived once from the seed (a pure function of it) so the base signal — not
    only the surprise schedule — varies with the seed. All values sit in bounded
    ranges so every seed is a *different but equally learnable* smooth,
    low-frequency world (no high-frequency noise that the world model could not
    fit).
    """

    phase_r: float
    phase_g: float
    phase_b: float
    drift_x: float
    drift_y: float
    wave_drift: float
    wave_freq: float


def _derive_base_params(seed: int, salt_base: int) -> _BaseParams:
    """Map a seed to its base-world parameters via the shared keyed PRNG.

    Each draw uses ``frame_index = 0`` and a distinct ``salt_base | channel`` so
    the streams never collide with the surprise draws (which use other salts).
    Drift rates and the wave frequency stay low so the world remains
    smooth/low-frequency and learnable; phases span a full turn.
    """
    phase_r = _unit_float(_keyed_u64(seed, 0, salt_base | 0x01))
    phase_g = _unit_float(_keyed_u64(seed, 0, salt_base | 0x02))
    phase_b = _unit_float(_keyed_u64(seed, 0, salt_base | 0x03))
    # Drift rates in [0.004, 0.020) cycles/frame — slow, smooth motion.
    drift_x = 0.004 + 0.016 * _unit_float(_keyed_u64(seed, 0, salt_base | 0x04))
    drift_y = 0.004 + 0.016 * _unit_float(_keyed_u64(seed, 0, salt_base | 0x05))
    wave_drift = 0.020 + 0.060 * _unit_float(_keyed_u64(seed, 0, salt_base | 0x06))
    # Wave spatial frequency in [2.0, 4.0) — a few cycles across the frame.
    wave_freq = 2.0 + 2.0 * _unit_float(_keyed_u64(seed, 0, salt_base | 0x07))
    return _BaseParams(
        phase_r=phase_r,
        phase_g=phase_g,
        phase_b=phase_b,
        drift_x=drift_x,
        drift_y=drift_y,
        wave_drift=wave_drift,
        wave_freq=wave_freq,
    )


class SeededProceduralSource:
    """A ``_VideoSource`` whose ``read()`` returns ``frame(seed, i)`` as a pure
    function of ``(seed, frame_index)`` — bit-identical across runs of a seed.

    Two layers, per the design:

    - a structured BASE SIGNAL (slow continuous drifts + periodic motion) the
      world model can learn to predict; prediction error on the base falls as
      the forward model fits it. This is genuine learnable structure.
    - SURPRISE EVENTS at the configured cadence whose onset jitter and content
      are drawn from the counter-based, seed-keyed PRNG above. Reproducible
      given the seed; not derivable from the observed frames without it.

    Persists only ``(seed, schedule)``; never a rendered frame.
    """

    # Salts namespace the keyed draws so the base, the surprise onset, and the
    # surprise content never collide for the same (seed, frame_index).
    _SALT_ONSET = 0xA1
    _SALT_CONTENT = 0xB2
    _SALT_NOISE = 0xC3
    # The base-world salt is keyed on (seed, 0, _SALT_BASE | channel) once at
    # construction to derive per-seed phase/frequency/drift offsets, so the BASE
    # signal — not only the surprise schedule — is a function of the seed.
    _SALT_BASE = 0xD400

    def __init__(self, schedule: SeededSchedule) -> None:
        self._schedule = schedule
        self._index = 0
        self._opened = False
        try:
            import numpy as np  # noqa: F401
        except ImportError as exc:  # pragma: no cover - numpy is a core dep
            raise RuntimeError("numpy is required for the seeded perception feed") from exc
        # Derive the per-seed BASE-WORLD parameters once. These keyed draws make
        # the base signal a function of (seed, frame_index): each seed gets its
        # own per-channel spatial phase, a drift rate, and a wave frequency, all
        # within bounded ranges so every seed is a *different but equally
        # learnable* smooth low-frequency world. Pure function of the seed.
        self._base = _derive_base_params(int(schedule.seed), self._SALT_BASE)

    @property
    def schedule(self) -> SeededSchedule:
        return self._schedule

    def open(self) -> bool:
        self._index = 0
        self._opened = True
        return True

    def read(self) -> tuple[bool, Any]:
        if not self._opened:
            return False, None
        frame = self.frame_at(self._index)
        self._index += 1
        return True, frame

    def release(self) -> None:
        self._opened = False

    # --- pure synthesis -----------------------------------------------------

    def frame_at(self, frame_index: int) -> Any:
        """Render ``frame(seed, frame_index)`` as a BGR uint8 ndarray.

        Pure function of ``(seed, frame_index)`` and the schedule: calling it
        twice with the same index returns byte-identical pixels, and the result
        does not depend on which frames were read before it (seek-safe).
        """
        import numpy as np

        s = self._schedule
        h, w = int(s.height), int(s.width)

        # Coordinate grids in [0, 1]. float32 keeps the arithmetic deterministic
        # and identical across runs on the same platform.
        ys = (np.arange(h, dtype=np.float32) / max(1, h - 1)).reshape(h, 1)
        xs = (np.arange(w, dtype=np.float32) / max(1, w - 1)).reshape(1, w)

        # --- Base signal: seed-keyed slow drift + periodic motion -----------
        # The world model can fit these because they are smooth, low-frequency,
        # and a deterministic function of the frame index. Two spatial gradients
        # drift in phase; a travelling sinusoid supplies periodic motion. Per
        # the design, the per-channel phase offsets, the drift rates, and the
        # wave frequency are SEED-DERIVED (self._base), so different seeds yield
        # genuinely different — but still equally learnable — base worlds (not
        # merely surprise-shifted). Each channel uses a distinct phase so the
        # frame is not grey.
        b = self._base
        two_pi = np.float32(2.0 * np.pi)
        t = np.float32(frame_index)
        drift_x = np.float32(b.drift_x) * t
        drift_y = np.float32(b.drift_y) * t
        wave_phase = np.float32(b.wave_drift) * t

        base_r = 0.5 + 0.5 * np.sin(two_pi * (xs + drift_x + np.float32(b.phase_r)))
        base_g = 0.5 + 0.5 * np.sin(two_pi * (ys + drift_y + np.float32(b.phase_g)))
        base_b = 0.5 + 0.5 * np.sin(
            two_pi * (xs + ys) * np.float32(b.wave_freq)
            + wave_phase
            + np.float32(b.phase_b)
        )

        # Stack to HxWx3 in RGB order, then convert to BGR at the end (the
        # camera path hands BGR ndarrays to _bgr_to_pil_rgb).
        rgb = np.empty((h, w, 3), dtype=np.float32)
        rgb[:, :, 0] = base_r
        rgb[:, :, 1] = np.broadcast_to(base_g, (h, w))
        rgb[:, :, 2] = base_b

        # --- Surprise events ------------------------------------------------
        # The cadence is regular (every surprise_interval frames) so the
        # experiment is legible, but WHETHER a given cadence slot actually fires
        # and WHAT it contains are seed-keyed draws — so onset/content are not
        # anticipable from the pixels.
        if self._is_surprise_frame(frame_index):
            content = _keyed_u64(s.seed, frame_index, self._SALT_CONTENT)
            # Decode the content draw into a localized high-contrast patch.
            cx = (content & 0xFFFF) % max(1, w)
            cy = ((content >> 16) & 0xFFFF) % max(1, h)
            radius = 20 + int(((content >> 32) & 0xFF) / 255.0 * (min(h, w) // 4))
            amp = np.float32(min(1.0, max(0.0, s.surprise_strength)))
            # Channel intensities from the draw — a vivid, unpredictable blob.
            cr = np.float32(((content >> 40) & 0xFF) / 255.0)
            cg = np.float32(((content >> 48) & 0xFF) / 255.0)
            cb = np.float32(((content >> 56) & 0xFF) / 255.0)

            yy = np.arange(h, dtype=np.float32).reshape(h, 1)
            xx = np.arange(w, dtype=np.float32).reshape(1, w)
            dist2 = (yy - cy) ** 2 + (xx - cx) ** 2
            mask = (dist2 <= np.float32(radius * radius)).astype(np.float32)
            mask *= amp
            inv = 1.0 - mask
            rgb[:, :, 0] = rgb[:, :, 0] * inv + cr * mask
            rgb[:, :, 1] = rgb[:, :, 1] * inv + cg * mask
            rgb[:, :, 2] = rgb[:, :, 2] * inv + cb * mask

        rgb = np.clip(rgb, 0.0, 1.0)
        bgr_u8 = (rgb[:, :, ::-1] * np.float32(255.0)).astype(np.uint8)
        return bgr_u8

    def _is_surprise_frame(self, frame_index: int) -> bool:
        """A surprise fires on cadence slots (every ``surprise_interval``
        frames, index > 0), with a seed-keyed coin flip on each slot so the
        onset detail is not anticipable. With strength 0 nothing fires."""
        interval = int(self._schedule.surprise_interval)
        if interval <= 0 or frame_index <= 0:
            return False
        if frame_index % interval != 0:
            return False
        if self._schedule.surprise_strength <= 0.0:
            return False
        slot = frame_index // interval
        onset = _keyed_u64(self._schedule.seed, slot, self._SALT_ONSET)
        # Fire on ~75% of slots so the cadence is visible but onset is seeded.
        return _unit_float(onset) < 0.75

    def surprise_indices(self, count: int) -> list[int]:
        """The frame indices in ``[0, count)`` on which a surprise fires —
        used by tests to assert cadence and seed-decorrelation."""
        return [i for i in range(count) if self._is_surprise_frame(i)]


# ---------------------------------------------------------------------------
# Playlist source
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PlaylistItem:
    path: str
    sha256: str
    fps: float
    order: int


@dataclass(frozen=True)
class PlaylistManifest:
    """Parsed operator manifest: ordered media items, each pinned by sha256."""

    manifest_path: str
    items: tuple[PlaylistItem, ...]

    def manifest_sha256(self) -> str:
        """Digest of the manifest file itself — the run's playlist covariate."""
        return hashlib.sha256(Path(self.manifest_path).read_bytes()).hexdigest()

    def as_descriptor(self) -> dict[str, Any]:
        """Reproducible covariate: manifest digest + per-item digests, enough to
        verify (not regenerate) the exact stream."""
        return {
            "manifest_sha256": self.manifest_sha256(),
            "item_digests": [
                {"order": it.order, "sha256": it.sha256, "fps": float(it.fps)}
                for it in self.items
            ],
        }

    def verify_against(self, root: Path) -> None:
        """Hash every item under ``root`` and compare to the manifest, failing
        CLOSED on the first missing file or sha256 mismatch.

        Shared by both the video (topos) and audio (audition) playlist sources
        so the fail-closed reproducibility semantics — and the exact error
        messages — never diverge. ``root`` is the media root; absolute item
        paths are used as-is, relative ones are resolved against it.
        """
        for item in self.items:
            p = Path(item.path)
            media = p if p.is_absolute() else (root / p)
            if not media.is_file():
                raise PlaylistVerificationError(
                    f"playlist media missing: {media} (order={item.order})"
                )
            actual = _sha256_file(media)
            if actual != item.sha256:
                raise PlaylistVerificationError(
                    f"sha256 mismatch for {media} (order={item.order}): "
                    f"manifest={item.sha256} actual={actual} — reproducibility void"
                )


class PlaylistManifestError(RuntimeError):
    """Raised when a manifest is malformed (missing fields, bad types)."""


def load_playlist_manifest(manifest_path: str | Path) -> PlaylistManifest:
    """Parse an operator playlist manifest (TOML).

    Schema (per item): ``path`` (str), ``sha256`` (64-hex str), ``fps`` (number).
    Items are ordered by their position in the file; an explicit ``order`` key
    is honoured if present, else the file order is used.
    """
    path = Path(manifest_path)
    if not path.is_file():
        raise PlaylistManifestError(f"playlist manifest not found: {path}")
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    raw_items = data.get("item")
    if not isinstance(raw_items, list) or not raw_items:
        raise PlaylistManifestError(
            f"playlist manifest {path} has no [[item]] entries"
        )
    items: list[PlaylistItem] = []
    for i, raw in enumerate(raw_items):
        if not isinstance(raw, dict):
            raise PlaylistManifestError(f"item {i} is not a table")
        try:
            item_path = str(raw["path"])
            sha = str(raw["sha256"]).lower()
            fps = float(raw["fps"])
        except (KeyError, TypeError, ValueError) as exc:
            raise PlaylistManifestError(
                f"item {i} missing path/sha256/fps: {raw!r}"
            ) from exc
        if len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
            raise PlaylistManifestError(f"item {i} sha256 is not 64 hex chars")
        if fps <= 0:
            raise PlaylistManifestError(f"item {i} fps must be > 0")
        order = int(raw.get("order", i))
        items.append(PlaylistItem(path=item_path, sha256=sha, fps=fps, order=order))
    items.sort(key=lambda it: it.order)
    return PlaylistManifest(manifest_path=str(path), items=tuple(items))


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class PlaylistVerificationError(RuntimeError):
    """Raised when a media file's sha256 does not match the manifest.

    A mismatch voids reproducibility, so the source fails CLOSED — the run must
    not proceed on unverified media.
    """


class PlaylistSource:
    """A ``_VideoSource`` over an operator-supplied, checksummed manifest.

    ``open()`` verifies EVERY item's sha256 before the run; any mismatch raises
    ``PlaylistVerificationError`` (fail-closed). Item order + per-item fps define
    a stable frame index, so frame ``i`` maps to the same decoded media frame
    across runs. Frames are decoded to in-memory ndarrays; nothing beyond the
    manifest is persisted.
    """

    def __init__(self, manifest: PlaylistManifest, *, media_root: str | Path | None = None) -> None:
        self._manifest = manifest
        # Relative item paths resolve against the manifest's own directory by
        # default, so a playlist is relocatable as a unit.
        self._root = Path(media_root) if media_root is not None else Path(manifest.manifest_path).parent
        self._cap: Any = None
        self._cv2: Any = None
        self._item_idx = 0
        self._verified = False

    @property
    def manifest(self) -> PlaylistManifest:
        return self._manifest

    def _resolve(self, item: PlaylistItem) -> Path:
        p = Path(item.path)
        return p if p.is_absolute() else (self._root / p)

    def verify(self) -> None:
        """Hash every item and compare to the manifest. Fail closed on any
        mismatch or missing file (shared loop in ``PlaylistManifest``)."""
        self._manifest.verify_against(self._root)
        self._verified = True

    def open(self) -> bool:
        # Verify BEFORE opening any decoder — a changed file must stop the run
        # before a single frame is read.
        self.verify()
        try:
            import cv2  # type: ignore[import-untyped]
        except ImportError as exc:
            from kaine.modules.topos.live import PerceptionUnavailableError

            raise PerceptionUnavailableError(
                "opencv-python-headless not installed — install with: pip install -e .[vision]"
            ) from exc
        self._cv2 = cv2
        self._item_idx = 0
        return self._open_current_item()

    def _open_current_item(self) -> bool:
        if self._item_idx >= len(self._manifest.items):
            return False
        item = self._manifest.items[self._item_idx]
        media = self._resolve(item)
        cap = self._cv2.VideoCapture(str(media))
        if not cap.isOpened():
            log.warning("playlist item could not be opened: %s", media)
            return False
        self._cap = cap
        return True

    def read(self) -> tuple[bool, Any]:
        if self._cap is None or not self._verified:
            return False, None
        ok, frame = self._cap.read()
        while not ok:
            # Current clip exhausted — advance to the next in manifest order.
            self._cap.release()
            self._cap = None
            self._item_idx += 1
            if self._item_idx >= len(self._manifest.items):
                return False, None
            if not self._open_current_item():
                return False, None
            ok, frame = self._cap.read()
        return True, frame

    def release(self) -> None:
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:
                log.debug("playlist VideoCapture.release raised", exc_info=True)
            self._cap = None
        self._verified = False


__all__ = [
    "SeededSchedule",
    "SeededProceduralSource",
    "PlaylistItem",
    "PlaylistManifest",
    "PlaylistManifestError",
    "PlaylistVerificationError",
    "load_playlist_manifest",
    "PlaylistSource",
]
