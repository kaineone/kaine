# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""General auditory perception core: acoustic encoding, change, arousal window,
voice-activity routing."""

from __future__ import annotations

import numpy as np
import pytest

from kaine.modules.audition.acoustic import (
    FakeAcousticEncoder,
    SpectralAcousticEncoder,
    arousal_to_window,
    cosine_change,
    detect_speech,
)

SR = 16000


def _tone(freq: float, seconds: float = 0.2, amp: float = 0.3, sr: int = SR) -> bytes:
    t = np.arange(int(seconds * sr)) / sr
    x = (amp * np.sin(2 * np.pi * freq * t) * 32767).astype("<i2")
    return x.tobytes()


def _silence(seconds: float = 0.2, sr: int = SR) -> bytes:
    return np.zeros(int(seconds * sr), dtype="<i2").tobytes()


# --------------------------------------------------------------------------- #
# spectral encoder
# --------------------------------------------------------------------------- #


def test_spectral_embedding_shape_and_unit_norm():
    enc = SpectralAcousticEncoder(n_bands=16)
    assert enc.embedding_dim == 32
    emb = enc.embed(_tone(300), SR)
    assert len(emb) == 32
    assert np.isclose(np.linalg.norm(emb), 1.0, atol=1e-5)


def test_different_sounds_have_different_embeddings():
    enc = SpectralAcousticEncoder(n_bands=16)
    low = enc.embed(_tone(200), SR)
    high = enc.embed(_tone(4000), SR)
    # A 200 Hz tone and a 4 kHz tone occupy different bands -> clearly distinct.
    assert cosine_change(high, low) > 0.2


def test_silence_encodes_without_crashing():
    enc = SpectralAcousticEncoder(n_bands=16)
    emb = enc.embed(_silence(), SR)
    assert len(emb) == 32  # all-zero band energies -> finite embedding


# --------------------------------------------------------------------------- #
# fake encoder (tests) + change
# --------------------------------------------------------------------------- #


def test_fake_encoder_is_deterministic_and_distinct():
    enc = FakeAcousticEncoder(embedding_dim=8)
    a1 = enc.embed(b"aaaa", SR)
    a2 = enc.embed(b"aaaa", SR)
    b = enc.embed(b"bbbb", SR)
    assert a1 == a2 and a1 != b
    assert np.isclose(np.linalg.norm(a1), 1.0, atol=1e-5)


def test_cosine_change_zero_on_first_then_positive():
    enc = FakeAcousticEncoder()
    first = enc.embed(b"one", SR)
    assert cosine_change(first, None) == 0.0
    assert cosine_change(enc.embed(b"two", SR), first) > 0.0
    assert cosine_change(first, first) == pytest.approx(0.0, abs=1e-6)


# --------------------------------------------------------------------------- #
# arousal -> auditory window (Easterbrook)
# --------------------------------------------------------------------------- #


def test_arousal_narrows_the_auditory_window():
    lo, hi = 0.15, 1.0
    assert arousal_to_window(1.0, window_range=(lo, hi)) == pytest.approx(lo)
    assert arousal_to_window(0.0, window_range=(lo, hi)) == pytest.approx(hi)
    assert arousal_to_window(0.5, window_range=(lo, hi)) == pytest.approx((lo + hi) / 2)


# --------------------------------------------------------------------------- #
# voice-activity routing
# --------------------------------------------------------------------------- #


def test_speech_band_tone_routes_to_speech():
    # A 300 Hz tone with energy sits in the speech centroid band.
    assert detect_speech(_tone(300, amp=0.3), SR) is True


def test_silence_is_not_speech():
    assert detect_speech(_silence(), SR) is False


def test_out_of_band_high_tone_is_not_speech():
    # A 7 kHz tone's centroid is above the speech band -> general path, not STT.
    assert detect_speech(_tone(7000, amp=0.3), SR) is False
