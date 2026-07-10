# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""General auditory perception core — represent and attend to any sound.

The auditory analog of ``topos/foveation.py``. Hearing is a perceptual sense, not
a transcription front end: an incoming audio window is turned into a general
acoustic embedding that represents speech, music, and environmental sound alike,
so a novel or sudden sound is salient by its change and prediction error whether
or not it is a voice. The entity's arousal sets the breadth of the auditory
attentional window (Easterbrook narrowing — the same distinct affective coupling
that sizes the visual fovea), and speech is a specialization routed off the
general path by a voice-activity heuristic.

Pure and dependency-light (numpy only). No disk I/O: embeddings exist only in
memory, preserving the zero-raw-sense-data invariant. The default encoder is a
log-spectral embedding — a real, download-free general acoustic representation
whose novelty drives salience; a stronger self-supervised audio encoder plugs in
through the same ``AcousticEncoder`` protocol.
"""

from __future__ import annotations

import hashlib
import math
from typing import Protocol, runtime_checkable

import numpy as np


@runtime_checkable
class AcousticEncoder(Protocol):
    """Turns an audio window into a fixed general acoustic embedding."""

    @property
    def embedding_dim(self) -> int:
        """The fixed embedding dimension the encoder produces."""

    @property
    def model_id(self) -> str:
        """A stable identifier for the encoder (recorded with the perception)."""

    def embed(self, audio_bytes: bytes, sample_rate: int) -> list[float]:
        """Encode one audio window into an ``embedding_dim``-length embedding."""


def _pcm16_to_float(audio_bytes: bytes) -> np.ndarray:
    """int16 little-endian PCM bytes → float32 mono in [-1, 1] (empty on no data)."""
    if not audio_bytes:
        return np.zeros(0, dtype=np.float32)
    # Drop a trailing odd byte so the buffer is a whole number of int16 samples.
    if len(audio_bytes) % 2:
        audio_bytes = audio_bytes[:-1]
    samples = np.frombuffer(audio_bytes, dtype="<i2").astype(np.float32)
    return samples / 32768.0


def _log_spaced_edges(n_bands: int, sample_rate: int, n_fft_bins: int) -> np.ndarray:
    """Band edges (indices into the rFFT bins) on a log-frequency scale, so low
    frequencies — where speech and most environmental structure live — get finer
    resolution than the high end, mel-style without a full mel filterbank."""
    lo, hi = 20.0, max(80.0, sample_rate / 2.0)
    freqs = np.logspace(math.log10(lo), math.log10(hi), n_bands + 1)
    bin_hz = (sample_rate / 2.0) / max(1, n_fft_bins - 1)
    edges = np.clip((freqs / bin_hz).astype(int), 0, n_fft_bins - 1)
    return edges


class SpectralAcousticEncoder:
    """Download-free general acoustic encoder: log-energy in log-spaced frequency
    bands, mean/std-pooled across frames and L2-normalized. The embedding is
    ``2 * n_bands``-dimensional and represents the spectral profile of *any* sound,
    so cosine change over it tracks acoustic novelty (a new sound, not a new word)."""

    def __init__(
        self, *, n_bands: int = 32, frame_ms: float = 25.0, hop_ms: float = 10.0
    ) -> None:
        self._n_bands = int(n_bands)
        self._frame_ms = float(frame_ms)
        self._hop_ms = float(hop_ms)

    @property
    def embedding_dim(self) -> int:
        return 2 * self._n_bands

    @property
    def model_id(self) -> str:
        return f"spectral-logband-{self._n_bands}"

    def embed(self, audio_bytes: bytes, sample_rate: int) -> list[float]:
        x = _pcm16_to_float(audio_bytes)
        dim = self.embedding_dim
        if x.size == 0 or sample_rate <= 0:
            return [0.0] * dim
        frame = max(16, int(sample_rate * self._frame_ms / 1000.0))
        hop = max(1, int(sample_rate * self._hop_ms / 1000.0))
        if x.size < frame:
            x = np.pad(x, (0, frame - x.size))
        window = np.hanning(frame).astype(np.float32)
        n_fft_bins = frame // 2 + 1
        edges = _log_spaced_edges(self._n_bands, sample_rate, n_fft_bins)

        band_frames = []
        for start in range(0, x.size - frame + 1, hop):
            seg = x[start : start + frame] * window
            mag = np.abs(np.fft.rfft(seg)) ** 2
            bands = np.empty(self._n_bands, dtype=np.float32)
            for b in range(self._n_bands):
                a, c = int(edges[b]), int(edges[b + 1])
                bands[b] = mag[a:c].sum() if c > a else mag[a]
            band_frames.append(np.log1p(bands))
        if not band_frames:
            return [0.0] * dim
        bf = np.stack(band_frames, axis=0)  # [n_frames, n_bands]
        emb = np.concatenate([bf.mean(axis=0), bf.std(axis=0)]).astype(np.float32)
        norm = float(np.linalg.norm(emb))
        if norm > 0:
            emb = emb / norm
        return emb.astype(float).tolist()


class FakeAcousticEncoder:
    """Deterministic embedding from the audio bytes, for tests (no numpy FFT path
    dependence). Distinct byte content yields distinct, unit-norm embeddings."""

    def __init__(self, embedding_dim: int = 8) -> None:
        self._dim = int(embedding_dim)

    @property
    def embedding_dim(self) -> int:
        return self._dim

    @property
    def model_id(self) -> str:
        return f"fake/acoustic-{self._dim}"

    def embed(self, audio_bytes: bytes, sample_rate: int) -> list[float]:  # noqa: ARG002
        digest = hashlib.blake2b(audio_bytes, digest_size=self._dim).digest()
        v = np.frombuffer(digest, dtype=np.uint8).astype(np.float32) - 127.5
        norm = float(np.linalg.norm(v))
        return (v / norm).astype(float).tolist() if norm > 0 else [0.0] * self._dim


def cosine_change(embedding: list[float], previous: list[float] | None) -> float:
    """1 − cosine similarity to the previous embedding; 0.0 on the first window.
    The auditory change score, mirroring the vision change detector."""
    if previous is None:
        return 0.0
    a = np.asarray(embedding, dtype=np.float32)
    b = np.asarray(previous, dtype=np.float32)
    na, nb = float(np.linalg.norm(a)), float(np.linalg.norm(b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return float(1.0 - float(np.dot(a, b) / (na * nb)))


def arousal_to_window(
    arousal: float, *, window_range: tuple[float, float] = (0.15, 1.0)
) -> float:
    """Map arousal in [0, 1] to a normalized auditory attentional window.
    Easterbrook narrowing: higher arousal → tighter window (nearer the min). The
    sign is a tuning choice; flip ``window_range`` to widen under arousal."""
    lo, hi = window_range
    a = float(np.clip(arousal, 0.0, 1.0))
    return hi - (hi - lo) * a


def detect_speech(
    audio_bytes: bytes,
    sample_rate: int,
    *,
    energy_floor: float = 1.0e-4,
    centroid_hz_range: tuple[float, float] = (85.0, 3500.0),
) -> bool:
    """Cheap voice-activity heuristic: enough energy AND a spectral centroid in the
    band where speech concentrates. Routes windows to the speech (STT + vocal
    emotion) specialization; the general acoustic path perceives everything else.
    A heuristic, not a classifier — the sign/thresholds are tuning parameters."""
    x = _pcm16_to_float(audio_bytes)
    if x.size == 0 or sample_rate <= 0:
        return False
    energy = float(np.mean(x * x))
    if energy < energy_floor:
        return False
    mag = np.abs(np.fft.rfft(x * np.hanning(x.size).astype(np.float32)))
    freqs = np.fft.rfftfreq(x.size, d=1.0 / sample_rate)
    total = float(mag.sum())
    if total <= 0:
        return False
    centroid = float(np.dot(freqs, mag) / total)
    lo, hi = centroid_hz_range
    return lo <= centroid <= hi
