# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Unit tests for kaine.modules.audition.prosody.

Covers:
- Feature extraction on a synthetic waveform (sine wave)
- Payload carries only numeric features (no bytes values)
- audio_bytes_to_float32 in-memory conversion (WAV + raw PCM fallback)
- Zero-duration / too-short audio returns zeroed features without raising
"""
import wave
import io
import math

import numpy as np

from kaine.modules.audition.prosody import (
    extract_prosody,
    audio_bytes_to_float32,
    _zeroed_features,
)


# ---------------------------------------------------------------------------
# Synthetic waveform helpers
# ---------------------------------------------------------------------------

def _sine_wave(freq_hz: float = 200.0, duration_s: float = 1.0,
               sample_rate: int = 16000, amplitude: float = 0.5) -> np.ndarray:
    """Return a float32 sine wave in [-amplitude, amplitude]."""
    t = np.linspace(0.0, duration_s, int(sample_rate * duration_s), endpoint=False)
    return (amplitude * np.sin(2.0 * math.pi * freq_hz * t)).astype(np.float32)


def _wav_bytes(audio: np.ndarray, sample_rate: int = 16000) -> bytes:
    """Encode float32 audio as an in-memory 16-bit mono WAV blob."""
    pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16).tobytes()
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# extract_prosody: feature extraction
# ---------------------------------------------------------------------------

def test_extract_prosody_returns_all_keys():
    """extract_prosody must return the six required numeric keys."""
    audio = _sine_wave(freq_hz=200.0, duration_s=1.0)
    features = extract_prosody(audio, sample_rate=16000)

    expected_keys = {"f0_mean_hz", "f0_std_hz", "f0_voiced_frac",
                     "rms_mean", "rms_std", "tempo_bpm"}
    assert set(features.keys()) == expected_keys


def test_extract_prosody_values_are_finite_floats():
    """All returned values must be plain finite floats (no bytes, no tensors)."""
    audio = _sine_wave(freq_hz=200.0, duration_s=1.0)
    features = extract_prosody(audio, sample_rate=16000)

    for key, val in features.items():
        assert isinstance(val, float), f"{key} is not a float: {type(val)}"
        assert math.isfinite(val), f"{key} is not finite: {val}"


def test_extract_prosody_no_bytes_in_payload():
    """The payload must contain no bytes values — zero-persistence invariant."""
    audio = _sine_wave(freq_hz=200.0, duration_s=1.0)
    features = extract_prosody(audio, sample_rate=16000)

    for key, val in features.items():
        assert not isinstance(val, (bytes, bytearray)), (
            f"Bytes value found in prosody payload at key '{key}'"
        )


def test_extract_prosody_rms_positive_on_sine():
    """A non-silent sine wave must produce non-zero RMS mean."""
    audio = _sine_wave(freq_hz=200.0, duration_s=1.0, amplitude=0.5)
    features = extract_prosody(audio, sample_rate=16000)
    assert features["rms_mean"] > 0.0, (
        f"Expected positive RMS on a sine wave; got {features['rms_mean']}"
    )


def test_extract_prosody_rms_near_zero_on_silence():
    """Silence should produce near-zero RMS mean."""
    silence = np.zeros(16000, dtype=np.float32)
    features = extract_prosody(silence, sample_rate=16000)
    assert features["rms_mean"] < 0.01, (
        f"Expected near-zero RMS on silence; got {features['rms_mean']}"
    )


def test_extract_prosody_too_short_returns_zeroed():
    """Very short arrays (< 50 ms) must return zeroed features without raising."""
    tiny = np.zeros(8, dtype=np.float32)
    features = extract_prosody(tiny, sample_rate=16000)
    assert features == _zeroed_features()


def test_extract_prosody_2d_array_returns_zeroed():
    """2-D arrays (wrong shape) must return zeroed features without raising."""
    bad = np.zeros((2, 8000), dtype=np.float32)
    features = extract_prosody(bad, sample_rate=16000)
    assert features == _zeroed_features()


def test_extract_prosody_no_disk_io(tmp_path, monkeypatch):
    """extract_prosody must not call open() on a disk path.

    We monkeypatch the builtins.open at module level in prosody to
    confirm no file is opened during extraction.
    """
    import builtins

    opened_paths: list[str] = []
    original_open = builtins.open

    def _spy_open(file, *args, **kwargs):
        if isinstance(file, str):
            opened_paths.append(file)
        return original_open(file, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", _spy_open)

    audio = _sine_wave(freq_hz=200.0, duration_s=0.5)
    extract_prosody(audio, sample_rate=16000)

    assert opened_paths == [], (
        f"extract_prosody opened disk files: {opened_paths}"
    )


# ---------------------------------------------------------------------------
# audio_bytes_to_float32: in-memory conversion
# ---------------------------------------------------------------------------

def test_bytes_to_float32_wav_roundtrip():
    """audio_bytes_to_float32 must decode a WAV blob without disk I/O."""
    original = _sine_wave(freq_hz=200.0, duration_s=0.5)
    wav = _wav_bytes(original, sample_rate=16000)

    recovered = audio_bytes_to_float32(wav, sample_rate=16000)
    assert recovered.dtype == np.float32
    assert len(recovered) > 0
    assert recovered.ndim == 1
    # All values should be in [-1, 1].
    assert np.all(np.abs(recovered) <= 1.0 + 1e-6)


def test_bytes_to_float32_raw_pcm_fallback():
    """audio_bytes_to_float32 falls back to raw int16 PCM if not WAV."""
    raw_int16 = (np.ones(1600, dtype=np.float32) * 0.5 * 32767).astype(np.int16)
    raw_bytes = raw_int16.tobytes()

    recovered = audio_bytes_to_float32(raw_bytes, sample_rate=16000)
    assert recovered.ndim == 1
    assert len(recovered) == 1600
    assert np.all(np.abs(recovered) <= 1.0 + 1e-6)


def test_bytes_to_float32_no_files_opened(monkeypatch):
    """audio_bytes_to_float32 must not open any disk files."""
    import builtins

    opened_paths: list[str] = []
    original_open = builtins.open

    def _spy_open(file, *args, **kwargs):
        if isinstance(file, str):
            opened_paths.append(file)
        return original_open(file, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", _spy_open)

    audio = _sine_wave(freq_hz=200.0, duration_s=0.5)
    wav = _wav_bytes(audio)
    audio_bytes_to_float32(wav, sample_rate=16000)

    assert opened_paths == [], (
        f"audio_bytes_to_float32 opened disk files: {opened_paths}"
    )
