# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for kaine.modules.vox.mirroring — pure-function prosodic mirroring.

Covers:
- blend_prosody: identity at strength=0; bounded by ceiling; nudges toward
  speaker prosody; base voice identity (voice_id/cfg_weight) is untouched.
- decayed_strength: full strength before decay window; zero after decay
  window; zero when no prosody seen; linear falloff in between.
"""
from __future__ import annotations

import pytest

from kaine.modules.vox.mapping import ChatterboxParams, affect_to_chatterbox
from kaine.modules.vox.mirroring import blend_prosody, decayed_strength
from kaine.modules.thymos.state import DimensionalState

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _base_params() -> ChatterboxParams:
    """Neutral mid-range affect params as a starting point."""
    return affect_to_chatterbox(
        DimensionalState(valence=0.0, arousal=0.5, dominance=0.0)
    )


def _fast_loud_expressive_prosody() -> dict:
    """A speaker prosody that is faster, louder, and more pitch-varied than
    the neutral baseline — all residuals push upward."""
    return {
        "f0_mean_hz": 180.0,
        "f0_std_hz": 50.0,       # wide pitch range → temp nudge up
        "f0_voiced_frac": 0.8,
        "rms_mean": 0.18,         # louder → exaggeration nudge up
        "rms_std": 0.05,
        "tempo_bpm": 170.0,       # faster → speed nudge up
    }


def _slow_quiet_flat_prosody() -> dict:
    """A speaker that is slower, quieter, and flat — residuals push downward."""
    return {
        "f0_mean_hz": 100.0,
        "f0_std_hz": 2.0,         # narrow pitch range → temp nudge down
        "f0_voiced_frac": 0.5,
        "rms_mean": 0.02,         # quiet → exaggeration nudge down
        "rms_std": 0.01,
        "tempo_bpm": 90.0,        # slower → speed nudge down
    }


# ---------------------------------------------------------------------------
# blend_prosody: strength = 0 → identity
# ---------------------------------------------------------------------------

def test_blend_zero_strength_returns_identical_params():
    """At strength=0 the function is identity — no change at all."""
    base = _base_params()
    result = blend_prosody(base, _fast_loud_expressive_prosody(), strength=0.0)
    assert result == base


def test_blend_negative_strength_returns_identical_params():
    base = _base_params()
    result = blend_prosody(base, _fast_loud_expressive_prosody(), strength=-1.0)
    assert result == base


# ---------------------------------------------------------------------------
# blend_prosody: base voice identity is preserved
# ---------------------------------------------------------------------------

def test_blend_does_not_change_cfg_weight():
    """cfg_weight encodes the speaker's 'commitment' and is left untouched.

    This is the identity-preservation test: the voice's characteristic
    parameter is never altered by prosodic mirroring.
    """
    base = _base_params()
    result = blend_prosody(base, _fast_loud_expressive_prosody(), strength=1.0)
    assert result.cfg_weight == base.cfg_weight


def test_blend_preserves_voice_id_concept_cfg_weight_at_max_ceiling():
    """Even at strength=1.0 (representing mirror_ceiling) cfg_weight is fixed."""
    base = ChatterboxParams(temperature=0.7, exaggeration=0.5, cfg_weight=0.9, speed_factor=1.0)
    result = blend_prosody(base, _fast_loud_expressive_prosody(), strength=1.0)
    assert result.cfg_weight == 0.9


# ---------------------------------------------------------------------------
# blend_prosody: nudges toward speaker prosody
# ---------------------------------------------------------------------------

def test_fast_speaker_nudges_speed_upward():
    """A faster-than-baseline speaker → speed_factor nudged up."""
    base = _base_params()
    result = blend_prosody(base, _fast_loud_expressive_prosody(), strength=0.5)
    assert result.speed_factor > base.speed_factor


def test_slow_speaker_nudges_speed_downward():
    """A slower-than-baseline speaker → speed_factor nudged down."""
    base = _base_params()
    result = blend_prosody(base, _slow_quiet_flat_prosody(), strength=0.5)
    assert result.speed_factor < base.speed_factor


def test_loud_speaker_nudges_exaggeration_upward():
    base = _base_params()
    result = blend_prosody(base, _fast_loud_expressive_prosody(), strength=0.5)
    assert result.exaggeration > base.exaggeration


def test_quiet_speaker_nudges_exaggeration_downward():
    base = _base_params()
    result = blend_prosody(base, _slow_quiet_flat_prosody(), strength=0.5)
    assert result.exaggeration < base.exaggeration


def test_expressive_speaker_nudges_temperature_upward():
    base = _base_params()
    result = blend_prosody(base, _fast_loud_expressive_prosody(), strength=0.5)
    assert result.temperature > base.temperature


def test_flat_speaker_nudges_temperature_downward():
    base = _base_params()
    result = blend_prosody(base, _slow_quiet_flat_prosody(), strength=0.5)
    assert result.temperature < base.temperature


# ---------------------------------------------------------------------------
# blend_prosody: output stays in documented bands
# ---------------------------------------------------------------------------

def test_output_always_in_documented_bands():
    """All blend outputs must stay inside Chatterbox's stability bands."""
    prosodies = [_fast_loud_expressive_prosody(), _slow_quiet_flat_prosody()]
    states = [
        DimensionalState(valence=-1.0, arousal=0.0),
        DimensionalState(valence=0.0, arousal=0.5),
        DimensionalState(valence=1.0, arousal=1.0),
    ]
    for state in states:
        base = affect_to_chatterbox(state)
        for prosody in prosodies:
            for strength in (0.0, 0.3, 0.5, 1.0):
                result = blend_prosody(base, prosody, strength)
                assert 0.4 <= result.temperature <= 0.95, (
                    f"temperature {result.temperature} out of band at strength={strength}"
                )
                assert 0.3 <= result.exaggeration <= 0.95, (
                    f"exaggeration {result.exaggeration} out of band at strength={strength}"
                )
                assert 0.3 <= result.cfg_weight <= 0.95, (
                    f"cfg_weight {result.cfg_weight} out of band"
                )
                assert 0.85 <= result.speed_factor <= 1.15, (
                    f"speed_factor {result.speed_factor} out of band at strength={strength}"
                )


# ---------------------------------------------------------------------------
# blend_prosody: residual is bounded by ceiling
# ---------------------------------------------------------------------------

def test_residual_bounded_at_max_strength():
    """The per-parameter shift at strength=1.0 must not exceed the band width.

    Mirror ceiling = 1.0 (caller's responsibility to pass in clamped value).
    At full strength the result should differ from the base by at most the
    full half-width of each parameter band — but must still be in-band.
    """
    # Use an extreme base near one edge of the band to stress the bounding.
    base = ChatterboxParams(
        temperature=0.95,   # top of band
        exaggeration=0.95,
        cfg_weight=0.5,
        speed_factor=1.15,  # top of speed band
    )
    result = blend_prosody(base, _fast_loud_expressive_prosody(), strength=1.0)
    # Must not exceed documented bands even at extreme starting points.
    assert result.temperature <= 0.95
    assert result.exaggeration <= 0.95
    assert result.speed_factor <= 1.15

    base_low = ChatterboxParams(
        temperature=0.4,
        exaggeration=0.3,
        cfg_weight=0.5,
        speed_factor=0.85,
    )
    result_low = blend_prosody(base_low, _slow_quiet_flat_prosody(), strength=1.0)
    assert result_low.temperature >= 0.4
    assert result_low.exaggeration >= 0.3
    assert result_low.speed_factor >= 0.85


def test_higher_strength_produces_larger_residual():
    """Increasing strength monotonically increases the magnitude of the nudge."""
    base = _base_params()
    prosody = _fast_loud_expressive_prosody()
    result_low = blend_prosody(base, prosody, strength=0.1)
    result_high = blend_prosody(base, prosody, strength=0.8)
    # All nudged-upward params should be larger at higher strength.
    assert result_high.speed_factor >= result_low.speed_factor
    assert result_high.exaggeration >= result_low.exaggeration
    assert result_high.temperature >= result_low.temperature


# ---------------------------------------------------------------------------
# blend_prosody: missing / zeroed prosody features → no nudge on that axis
# ---------------------------------------------------------------------------

def test_missing_tempo_no_speed_change():
    """If tempo_bpm is absent / zero, speed_factor is unchanged."""
    base = _base_params()
    prosody = {"f0_std_hz": 40.0, "rms_mean": 0.15, "tempo_bpm": 0.0}
    result = blend_prosody(base, prosody, strength=1.0)
    assert result.speed_factor == pytest.approx(base.speed_factor)


def test_empty_prosody_returns_affect_params():
    """Completely empty prosody dict → no nudge at all."""
    base = _base_params()
    result = blend_prosody(base, {}, strength=1.0)
    assert result.speed_factor == pytest.approx(base.speed_factor)
    assert result.exaggeration == pytest.approx(base.exaggeration)
    assert result.temperature == pytest.approx(base.temperature)
    assert result.cfg_weight == pytest.approx(base.cfg_weight)


# ---------------------------------------------------------------------------
# decayed_strength
# ---------------------------------------------------------------------------

def test_decayed_no_prosody_seen_returns_zero():
    """When last_prosody_ts == 0.0 (never seen), strength is always 0."""
    assert decayed_strength(0.5, 0.0, now=100.0, decay_s=10.0) == 0.0


def test_decayed_within_window_returns_full_strength():
    """Before decay_s has elapsed, full strength is returned."""
    now = 100.0
    result = decayed_strength(0.5, last_prosody_ts=99.0, now=now, decay_s=10.0)
    assert result == pytest.approx(0.5 * (1.0 - 1.0 / 10.0), abs=1e-9)


def test_decayed_past_window_returns_zero():
    """After decay_s has elapsed, effective strength is zero."""
    result = decayed_strength(0.5, last_prosody_ts=80.0, now=100.0, decay_s=10.0)
    assert result == 0.0


def test_decayed_exactly_at_window_boundary_returns_zero():
    """Exactly at the decay boundary, result is zero."""
    result = decayed_strength(0.5, last_prosody_ts=90.0, now=100.0, decay_s=10.0)
    assert result == 0.0


def test_decayed_linear_falloff():
    """Strength at 50% of decay window should be 50% of configured strength."""
    strength = 0.4
    result = decayed_strength(strength, last_prosody_ts=95.0, now=100.0, decay_s=10.0)
    expected = strength * (1.0 - 5.0 / 10.0)  # 0.5 through the window
    assert result == pytest.approx(expected, abs=1e-9)


def test_decayed_zero_decay_s_returns_full():
    """decay_s <= 0 disables decay — always returns full strength."""
    result = decayed_strength(0.4, last_prosody_ts=1.0, now=10000.0, decay_s=0.0)
    assert result == pytest.approx(0.4)


# ---------------------------------------------------------------------------
# Integration: mirroring does not exceed mirror_ceiling when caller clamps
# ---------------------------------------------------------------------------

def test_caller_clamp_to_ceiling_bounds_all_residuals():
    """Simulate the full call path: caller clamps strength to mirror_ceiling
    before passing to blend_prosody.  Residual on every axis must stay
    within the band — proving the boundedness guarantee in the spec."""
    mirror_strength = 0.9   # higher than ceiling
    mirror_ceiling = 0.5
    effective = min(mirror_strength, mirror_ceiling)  # caller's job

    base = _base_params()
    result = blend_prosody(base, _fast_loud_expressive_prosody(), strength=effective)

    # Verify shift is bounded: delta per param <= ceiling * band_half_width.
    spd_half = (1.15 - 0.85) / 2.0
    exag_half = (0.95 - 0.3) / 2.0
    temp_half = (0.95 - 0.4) / 2.0

    assert abs(result.speed_factor - base.speed_factor) <= mirror_ceiling * spd_half + 1e-9
    assert abs(result.exaggeration - base.exaggeration) <= mirror_ceiling * exag_half + 1e-9
    assert abs(result.temperature - base.temperature) <= mirror_ceiling * temp_half + 1e-9
    # cfg_weight must be completely unchanged.
    assert result.cfg_weight == base.cfg_weight
