# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""In-memory speaker prosody extraction for Audition.

Extracts per-utterance prosodic features from a NumPy float32 audio array
held entirely in memory — NO disk I/O, NO NamedTemporaryFile.

Features extracted
------------------
- ``f0_mean_hz``     : mean F0 (Hz) over voiced frames (NaN-excluded)
- ``f0_std_hz``      : standard deviation of F0 over voiced frames
- ``f0_voiced_frac`` : fraction of frames that are voiced
- ``rms_mean``       : mean RMS energy over all frames (linear)
- ``rms_std``        : standard deviation of RMS energy
- ``tempo_bpm``      : estimated speaking rate (beats per minute via librosa)

Published as ``audition.prosody`` (numeric values only — no raw audio).

ZERO PERSISTENCE INVARIANT: the NumPy audio array is passed in from the
caller and released as soon as this function returns. Nothing here writes
to disk or emits bytes onto the event bus.
"""
from __future__ import annotations

import logging
import math
from typing import Any, Optional

import numpy as np

log = logging.getLogger(__name__)

# Voiced-pitch frequency range for human speech.
_FMIN_HZ: float = 65.0   # librosa.note_to_hz('C2')
_FMAX_HZ: float = 2093.0  # librosa.note_to_hz('C7')


def extract_prosody(
    audio: np.ndarray,
    *,
    sample_rate: int = 16000,
) -> dict[str, Any]:
    """Extract prosodic features from an in-memory float32 audio array.

    Parameters
    ----------
    audio:
        1-D float32 NumPy array of normalised audio samples (range [-1, 1]).
        Must be at least a few frames long; very short clips return zeroed
        features with a warning.
    sample_rate:
        Sample rate of *audio* in Hz.

    Returns
    -------
    dict containing:
        ``f0_mean_hz``, ``f0_std_hz``, ``f0_voiced_frac``,
        ``rms_mean``, ``rms_std``, ``tempo_bpm``

    All values are plain Python floats.  No bytes values are included.
    """
    import librosa  # ISC licence; listed in the optional [audio] extra.

    # ------------------------------------------------------------------ #
    # Sanity / minimum-length guard                                        #
    # ------------------------------------------------------------------ #
    min_samples = max(512, int(sample_rate * 0.05))  # at least ~50 ms
    if audio.ndim != 1 or len(audio) < min_samples:
        log.warning(
            "prosody: audio too short (%d samples < %d); returning zeroed features",
            len(audio) if audio.ndim == 1 else -1,
            min_samples,
        )
        return _zeroed_features()

    y = audio.astype(np.float32, copy=False)

    # ------------------------------------------------------------------ #
    # F0 via pyin                                                          #
    # ------------------------------------------------------------------ #
    try:
        f0, voiced_flag, _voiced_probs = librosa.pyin(
            y,
            fmin=_FMIN_HZ,
            fmax=min(_FMAX_HZ, sample_rate / 2.0 - 1.0),
            sr=float(sample_rate),
            fill_na=None,  # NaN for unvoiced frames
        )
        voiced_f0 = f0[voiced_flag] if voiced_flag is not None else np.array([], dtype=np.float32)
        voiced_f0 = voiced_f0[np.isfinite(voiced_f0)]
        f0_mean = float(np.mean(voiced_f0)) if len(voiced_f0) > 0 else 0.0
        f0_std = float(np.std(voiced_f0)) if len(voiced_f0) > 0 else 0.0
        voiced_frac = (
            float(np.sum(voiced_flag)) / float(len(voiced_flag))
            if voiced_flag is not None and len(voiced_flag) > 0
            else 0.0
        )
    except Exception:
        log.warning("prosody: pyin failed; using zeroed F0", exc_info=True)
        f0_mean = 0.0
        f0_std = 0.0
        voiced_frac = 0.0

    # ------------------------------------------------------------------ #
    # Energy via RMS                                                       #
    # ------------------------------------------------------------------ #
    try:
        rms = librosa.feature.rms(y=y)[0]  # shape (n_frames,)
        rms_mean = float(np.mean(rms)) if len(rms) > 0 else 0.0
        rms_std = float(np.std(rms)) if len(rms) > 0 else 0.0
    except Exception:
        log.warning("prosody: rms failed; using zeroed energy", exc_info=True)
        rms_mean = 0.0
        rms_std = 0.0

    # ------------------------------------------------------------------ #
    # Tempo via librosa.feature.tempo (or librosa.beat.tempo fallback)    #
    # librosa 0.11 exposes tempo at both librosa.feature.tempo and        #
    # librosa.beat.tempo; we prefer feature.tempo (keyword-only API).     #
    # ------------------------------------------------------------------ #
    try:
        tempo_result = librosa.feature.tempo(y=y, sr=float(sample_rate))
        # Returns a scalar ndarray or 1-D array; take the first element.
        tempo_bpm = float(np.atleast_1d(tempo_result)[0])
    except Exception:
        log.warning("prosody: tempo failed; using 0.0", exc_info=True)
        tempo_bpm = 0.0

    return {
        "f0_mean_hz": _safe_float(f0_mean),
        "f0_std_hz": _safe_float(f0_std),
        "f0_voiced_frac": _safe_float(voiced_frac),
        "rms_mean": _safe_float(rms_mean),
        "rms_std": _safe_float(rms_std),
        "tempo_bpm": _safe_float(tempo_bpm),
    }


def _safe_float(v: float) -> float:
    """Return *v* as a finite float; replace non-finite values with 0.0."""
    return float(v) if math.isfinite(v) else 0.0


def _zeroed_features() -> dict[str, Any]:
    return {
        "f0_mean_hz": 0.0,
        "f0_std_hz": 0.0,
        "f0_voiced_frac": 0.0,
        "rms_mean": 0.0,
        "rms_std": 0.0,
        "tempo_bpm": 0.0,
    }


def audio_bytes_to_float32(audio_bytes: bytes, *, sample_rate: int) -> np.ndarray:
    """Convert raw in-memory WAV/PCM bytes to a float32 NumPy array.

    Attempts to decode as WAV via the ``wave`` stdlib module (no disk I/O).
    Falls back to treating the bytes as raw int16 PCM if WAV decoding fails.

    The returned array is 1-D float32 in [-1, 1].  All processing is in
    memory; no temporary files are created.
    """
    import io
    import wave

    try:
        with wave.open(io.BytesIO(audio_bytes), "rb") as wf:
            n_channels = wf.getnchannels()
            sampwidth = wf.getsampwidth()
            pcm = wf.readframes(wf.getnframes())
    except Exception:
        # Not a WAV header — treat as raw int16 PCM.
        pcm = audio_bytes
        n_channels = 1
        sampwidth = 2

    if sampwidth == 2:
        samples = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
    elif sampwidth == 1:
        samples = (np.frombuffer(pcm, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    else:
        # Unsupported; return silence.
        return np.zeros(1, dtype=np.float32)

    if n_channels > 1:
        # Mix down to mono by averaging channels.
        samples = samples.reshape(-1, n_channels).mean(axis=1)

    return samples
