# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Deterministic auditory-feed sources for reproducible research runs.

Both sources implement the ``_AudioStream`` protocol from
``kaine/modules/audition/live.py`` (``start()`` / ``stop()`` / ``close()``) and
plug into ``LiveMicrophone`` via its ``stream_factory`` seam. They run a small
producer thread that pushes ``frames_per_block``-sized int16 little-endian PCM
blocks into the ``callback`` at the configured ``sample_rate`` — the exact
contract ``_default_stream_factory`` (sounddevice) fulfils today, so the VAD /
segmentation pipeline downstream is unchanged.

WHY DETERMINISTIC: a research run must present a bit-identical stimulus stream so
results replicate, and the stream must be copyright-free. A live microphone is
neither replayable nor copyright-free. See
openspec/changes/unified-perception-feed.

CROSS-MODAL COHERENCE: the seeded audio source shares the seed and the
``surprise_interval`` cadence with the seeded VIDEO source, so a surprise slot
fires both a visual blob and an audio burst — coherent and cross-modally bound by
construction (NOT frame-locked across the two module loops; coherence is via the
shared seed + cadence). The playlist audio source walks the SAME checksummed
manifest as the playlist video source, so picture and sound come from the same
media (clip-level synchronization).

ZERO PERSISTENCE INVARIANT (eyes-and-ears): raw PCM lives only in process memory
— a bounded producer thread emits blocks straight into the callback and never
opens a file for writing. The seeded source persists only ``(seed, schedule)``;
the playlist source persists nothing beyond the manifest it is handed. The
build-time guard in tests/test_zero_persistence_invariant.py covers this module.
"""
from __future__ import annotations

import logging
import math
import struct
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from kaine.modules.audition.live import PerceptionUnavailableError
from kaine.modules.perception_prng import keyed_u64 as _keyed_u64
from kaine.modules.perception_prng import unit_float as _unit_float
from kaine.modules.topos.feed import PlaylistManifest

log = logging.getLogger(__name__)

_INT16_MAX = 32767


# ---------------------------------------------------------------------------
# Seeded procedural audio schedule
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SeededAudioSchedule:
    """Reproducible auditory schedule. The whole soundscape is a pure function
    of these parameters plus the frame (block) index — nothing else.

    ``surprise_interval`` is SHARED with the video schedule so surprises are
    cross-modal; ``base_strength`` scales the learnable base soundscape and
    ``surprise_strength`` scales the seed-keyed bursts (either may be 0 to
    silence one layer). The schedule carries no PCM — only these knobs.
    """

    seed: int = 0
    sample_rate: int = 16000
    channels: int = 1
    frames_per_block: int = 480  # 30 ms @ 16 kHz — matches the mic's VAD frame
    surprise_interval: int = 150
    base_strength: float = 0.3
    surprise_strength: float = 1.0

    def as_descriptor(self) -> dict[str, Any]:
        """The reproducible covariate: enough to regenerate the exact stream."""
        return {
            "seed": int(self.seed),
            "sample_rate": int(self.sample_rate),
            "channels": int(self.channels),
            "frames_per_block": int(self.frames_per_block),
            "surprise_interval": int(self.surprise_interval),
            "base_strength": float(self.base_strength),
            "surprise_strength": float(self.surprise_strength),
        }


# Salts namespace the keyed draws. The base soundscape and the surprise CONTENT
# use audio-only salts (independent of the video draws). The surprise ONSET
# salt is DELIBERATELY shared with the video source so that — for the same seed
# and the same surprise_interval — both modalities decide a slot fires from the
# identical coin flip, making surprises cross-modal (a video blob and an audio
# burst on the same slot). See SeededProceduralSource._SALT_ONSET in
# kaine/modules/topos/feed.py.
_SALT_AUDIO_BASE = 0xE100
_SALT_AUDIO_CONTENT = 0xE3
# Shared with the video source's onset draw (topos.feed _SALT_ONSET = 0xA1).
_SALT_SHARED_ONSET = 0xA1


@dataclass(frozen=True)
class _AudioBaseParams:
    """Per-seed parameters of the learnable base soundscape — a small sum of
    low-frequency sinusoids whose frequencies/phases/amplitudes are seed-derived.
    All bounded so the texture is smooth and learnable (the auditory analogue of
    the drifting visual gradients)."""

    freqs: tuple[float, ...]
    phases: tuple[float, ...]
    amps: tuple[float, ...]


def _derive_audio_base_params(seed: int, n_partials: int = 3) -> _AudioBaseParams:
    """Map a seed to its base-soundscape partials via the shared keyed PRNG.

    Frequencies sit in [80, 440) Hz (low, learnable, well below Nyquist for
    16 kHz); phases span a full turn; amplitudes are normalised so the partials
    sum to ~1.0 before ``base_strength`` scales them."""
    freqs: list[float] = []
    phases: list[float] = []
    raw_amps: list[float] = []
    for k in range(n_partials):
        f = 80.0 + 360.0 * _unit_float(_keyed_u64(seed, 0, _SALT_AUDIO_BASE | (0x10 + k)))
        ph = _unit_float(_keyed_u64(seed, 0, _SALT_AUDIO_BASE | (0x20 + k)))
        a = 0.4 + 0.6 * _unit_float(_keyed_u64(seed, 0, _SALT_AUDIO_BASE | (0x30 + k)))
        freqs.append(f)
        phases.append(ph)
        raw_amps.append(a)
    total = sum(raw_amps) or 1.0
    amps = [a / total for a in raw_amps]
    return _AudioBaseParams(
        freqs=tuple(freqs), phases=tuple(phases), amps=tuple(amps)
    )


class SeededProceduralAudioStream:
    """An ``_AudioStream`` that emits ``pcm(seed, block_index)`` as a pure
    function of ``(seed, block_index)`` — byte-identical across runs of a seed.

    Two layers, mirroring the seeded video source:

    - a learnable BASE SOUNDSCAPE: a sum of a few seed-derived low-frequency
      sinusoids — continuous, smooth texture the world model can learn to
      predict. Keeps Audition's RMS/VAD seeing continuous input (no dead
      silence), so segmentation still chunks it into "utterances" of sound.
    - SURPRISE BURSTS on the SHARED cadence (``surprise_interval``), whose timbre
      and amplitude come from a seed-keyed content draw. Reproducible given the
      seed; not derivable from the observed audio without it.

    HONEST NOTE: this is *sound*, not speech. STT may transcribe a block as
    empty; the research signal is auditory prediction-error + salience, not
    words. Documented in docs and the spec.

    Persists only ``(seed, schedule)``; never a sample of PCM.
    """

    def __init__(
        self,
        schedule: SeededAudioSchedule,
        *,
        callback: Callable[[bytes], None],
    ) -> None:
        self._schedule = schedule
        self._callback = callback
        self._base = _derive_audio_base_params(int(schedule.seed))
        self._index = 0
        self._thread: threading.Thread | None = None
        self._stopped = threading.Event()

    @property
    def schedule(self) -> SeededAudioSchedule:
        return self._schedule

    # --- _AudioStream protocol ---------------------------------------------

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stopped.clear()
        self._thread = threading.Thread(
            target=self._produce, name="seeded-audio-producer", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stopped.set()
        thread = self._thread
        self._thread = None
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2.0)

    def close(self) -> None:
        self.stop()

    # --- producer ----------------------------------------------------------

    def _produce(self) -> None:
        s = self._schedule
        block_seconds = max(1, s.frames_per_block) / float(max(1, s.sample_rate))
        next_deadline = time.monotonic()
        while not self._stopped.is_set():
            pcm = self.pcm_at(self._index)
            self._index += 1
            try:
                self._callback(pcm)
            except Exception:
                log.debug("seeded audio callback raised", exc_info=True)
            # Pace emission at real time so the downstream queue is not flooded;
            # the data itself is independent of timing (seek-safe).
            next_deadline += block_seconds
            sleep_for = next_deadline - time.monotonic()
            if sleep_for > 0:
                self._stopped.wait(timeout=sleep_for)
            else:
                # We fell behind — reset the clock so we don't busy-spin.
                next_deadline = time.monotonic()

    # --- pure synthesis -----------------------------------------------------

    def pcm_at(self, block_index: int) -> bytes:
        """Synthesize the int16 LE PCM block at ``block_index`` as a pure
        function of ``(seed, block_index)``. Byte-identical across runs and
        independent of read order (seek-safe)."""
        s = self._schedule
        n = max(1, int(s.frames_per_block))
        sr = float(max(1, s.sample_rate))
        channels = max(1, int(s.channels))
        two_pi = 2.0 * math.pi

        # Absolute sample offset of this block, so phase is continuous across
        # blocks (a function of block_index, not of any running accumulator).
        sample0 = block_index * n
        base_amp = max(0.0, float(s.base_strength))

        # --- Base soundscape: sum of seed-derived low-freq sinusoids --------
        samples = [0.0] * n
        if base_amp > 0.0:
            for f, ph, a in zip(self._base.freqs, self._base.phases, self._base.amps):
                w = two_pi * f / sr
                p0 = two_pi * ph
                amp = base_amp * a
                for i in range(n):
                    samples[i] += amp * math.sin(w * (sample0 + i) + p0)

        # --- Surprise burst -------------------------------------------------
        # On a shared cadence slot the burst is a seed-keyed band-limited tone +
        # noise, so the surprise is cross-modal (a video blob fires the same
        # slot) yet not anticipable from the audio without the seed.
        if self._is_surprise_block(block_index):
            content = _keyed_u64(s.seed, block_index, _SALT_AUDIO_CONTENT)
            burst_amp = min(1.0, max(0.0, float(s.surprise_strength)))
            # Burst carrier in [600, 3000) Hz — clearly distinct from the base.
            burst_f = 600.0 + 2400.0 * (((content >> 8) & 0xFFFF) / 65535.0)
            w = two_pi * burst_f / sr
            # A short envelope so the burst is a transient within the block.
            burst_len = min(n, max(1, n // 2))
            for i in range(burst_len):
                env = 0.5 - 0.5 * math.cos(two_pi * i / max(1, burst_len - 1))
                # Seed-keyed deterministic "noise" overlay (no RNG state).
                noise_u = _keyed_u64(s.seed, sample0 + i, _SALT_AUDIO_CONTENT)
                noise = (_unit_float(noise_u) * 2.0 - 1.0)
                samples[i] += burst_amp * env * (0.7 * math.sin(w * (sample0 + i)) + 0.3 * noise)

        # Clip to [-1, 1] then quantise to int16 LE; replicate across channels.
        out = bytearray()
        for v in samples:
            if v > 1.0:
                v = 1.0
            elif v < -1.0:
                v = -1.0
            q = int(round(v * _INT16_MAX))
            if q > _INT16_MAX:
                q = _INT16_MAX
            elif q < -_INT16_MAX - 1:
                q = -_INT16_MAX - 1
            packed = struct.pack("<h", q)
            for _ in range(channels):
                out += packed
        return bytes(out)

    def _is_surprise_block(self, block_index: int) -> bool:
        """A surprise fires on shared cadence slots (every ``surprise_interval``
        blocks, index > 0), with a seed-keyed coin flip on each slot — mirroring
        the video source so the modalities share the same slots. Strength 0
        silences it."""
        interval = int(self._schedule.surprise_interval)
        if interval <= 0 or block_index <= 0:
            return False
        if block_index % interval != 0:
            return False
        if self._schedule.surprise_strength <= 0.0:
            return False
        slot = block_index // interval
        onset = _keyed_u64(self._schedule.seed, slot, _SALT_SHARED_ONSET)
        return _unit_float(onset) < 0.75

    def surprise_indices(self, count: int) -> list[int]:
        """The block indices in ``[0, count)`` on which a surprise fires — used
        by tests to assert cadence and cross-modal alignment with the video."""
        return [i for i in range(count) if self._is_surprise_block(i)]


# ---------------------------------------------------------------------------
# Playlist audio source
# ---------------------------------------------------------------------------


class PlaylistAudioStream:
    """An ``_AudioStream`` over the SAME operator-supplied, checksummed manifest
    as the playlist video source.

    ``start()`` verifies EVERY item's sha256 before the run (shared ``verify()``
    semantics); any mismatch raises ``PlaylistVerificationError`` (fail-closed).
    It then decodes each media file's AUDIO track in manifest order via PyAV
    (``av``), resamples to ``sample_rate`` / ``channels``, and emits int16 LE PCM
    blocks into the callback. cv2 cannot decode audio, so ``av`` is required; if
    it is absent the source raises ``PerceptionUnavailableError`` with an install
    hint — honest failure, NEVER a silent no-op or synthetic substitute.

    Persists nothing beyond the manifest it is handed (zero-persistence).
    """

    def __init__(
        self,
        manifest: PlaylistManifest,
        *,
        callback: Callable[[bytes], None],
        sample_rate: int = 16000,
        channels: int = 1,
        frames_per_block: int = 480,
        media_root: str | Path | None = None,
    ) -> None:
        self._manifest = manifest
        self._callback = callback
        self._sample_rate = int(sample_rate)
        self._channels = int(channels)
        self._frames_per_block = int(frames_per_block)
        self._root = (
            Path(media_root)
            if media_root is not None
            else Path(manifest.manifest_path).parent
        )
        self._thread: threading.Thread | None = None
        self._stopped = threading.Event()

    @property
    def manifest(self) -> PlaylistManifest:
        return self._manifest

    def _resolve(self, path: str) -> Path:
        p = Path(path)
        return p if p.is_absolute() else (self._root / p)

    def verify(self) -> None:
        """Hash every item and compare to the manifest (shared fail-closed
        semantics with the video source). A mismatch voids reproducibility, so
        the run must not proceed on unverified media."""
        self._manifest.verify_against(self._root)

    # --- _AudioStream protocol ---------------------------------------------

    def start(self) -> None:
        if self._thread is not None:
            return
        # Verify BEFORE importing/decoding anything — a changed file must stop
        # the run before a single sample is read.
        self.verify()
        try:
            import av  # type: ignore[import-untyped]  # noqa: F401
        except ImportError as exc:
            raise PerceptionUnavailableError(
                "PyAV (av) not installed — playlist audio decode requires it; "
                "install with: pip install -e .[audio]"
            ) from exc
        self._stopped.clear()
        self._thread = threading.Thread(
            target=self._produce, name="playlist-audio-producer", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._stopped.set()
        thread = self._thread
        self._thread = None
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2.0)

    def close(self) -> None:
        self.stop()

    # --- producer ----------------------------------------------------------

    def _produce(self) -> None:
        import av  # type: ignore[import-untyped]

        block_bytes = self._frames_per_block * self._channels * 2
        block_seconds = max(1, self._frames_per_block) / float(max(1, self._sample_rate))
        carry = bytearray()
        next_deadline = time.monotonic()

        def _emit(pcm: bytes) -> None:
            nonlocal next_deadline
            try:
                self._callback(pcm)
            except Exception:
                log.debug("playlist audio callback raised", exc_info=True)
            next_deadline += block_seconds
            sleep_for = next_deadline - time.monotonic()
            if sleep_for > 0:
                self._stopped.wait(timeout=sleep_for)
            else:
                next_deadline = time.monotonic()

        try:
            for item in self._manifest.items:
                if self._stopped.is_set():
                    return
                media = self._resolve(item.path)
                container = av.open(str(media))
                try:
                    if not container.streams.audio:
                        log.warning("playlist item has no audio track: %s", media)
                        continue
                    resampler = av.audio.resampler.AudioResampler(
                        format="s16",
                        layout="mono" if self._channels == 1 else "stereo",
                        rate=self._sample_rate,
                    )
                    stream = container.streams.audio[0]
                    for frame in container.decode(stream):
                        if self._stopped.is_set():
                            return
                        for rframe in resampler.resample(frame):
                            carry += bytes(rframe.planes[0])
                            while len(carry) >= block_bytes:
                                if self._stopped.is_set():
                                    return
                                _emit(bytes(carry[:block_bytes]))
                                del carry[:block_bytes]
                finally:
                    container.close()
            # Flush a final short block (zero-padded) so no audio is dropped.
            if carry and not self._stopped.is_set():
                pad = block_bytes - len(carry)
                if pad > 0:
                    carry += b"\x00" * pad
                _emit(bytes(carry[:block_bytes]))
        except Exception:
            log.exception("playlist audio producer crashed")


__all__ = [
    "SeededAudioSchedule",
    "SeededProceduralAudioStream",
    "PlaylistAudioStream",
]
