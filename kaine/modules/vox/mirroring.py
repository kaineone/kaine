# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Prosodic mirroring for Vox — identity-preserving accommodation.

Blends a bounded residual of the latest ``audition.prosody`` features into
the affect-driven ``ChatterboxParams`` produced by ``affect_to_chatterbox``.

Design constraints
------------------
- **Identity-preserving**: only expressive dynamics (speed_factor,
  exaggeration, temperature) are nudged. The predefined voice ID /
  speaker embedding is NEVER touched here.
- **Bounded**: the residual is scaled by ``strength ∈ [0, mirror_ceiling]``.
  No matter how large the prosodic difference, the per-parameter shift
  cannot exceed the ceiling times the full parameter range.
- **Pure function**: ``blend_prosody`` is a pure, stateless function — easy
  to test in isolation.
- **Decay**: the caller is responsible for supplying a time-decayed
  strength value; see ``decayed_strength``.
- **No raw data**: all prosody features are numeric (floats from librosa).
  No audio bytes or raw waveforms are accepted or stored here.
- **No new dependencies**: uses only stdlib math and types already imported
  by the mapping module.

Prosody feature mapping
-----------------------
``audition.prosody`` carries:
  - ``f0_mean_hz``     : mean F0 of voiced frames
  - ``f0_std_hz``      : F0 standard deviation (pitch range / expressivity)
  - ``f0_voiced_frac`` : fraction of frames that are voiced
  - ``rms_mean``       : mean RMS energy
  - ``rms_std``        : RMS energy standard deviation
  - ``tempo_bpm``      : estimated speaking rate (beats per minute)

Mirroring uses three of these features to nudge three TTS params:
  - ``tempo_bpm``    → ``speed_factor``   (faster speaker → slightly faster TTS)
  - ``rms_mean``     → ``exaggeration``   (louder/more energetic → more expressive)
  - ``f0_std_hz``    → ``temperature``    (wider pitch range → more varied output)

Nudge direction: each feature is normalised against a reference range so
the residual is always in [-1, 1] before scaling.  A positive residual
means the speaker's feature exceeds the affect-baseline param and the
corresponding TTS param is nudged upward (toward a livelier voice).  A
negative residual means the speaker is calmer and the param is nudged down.
The nudge is then clamped so the result stays inside the documented band.
"""
from __future__ import annotations

import math
from typing import Any

from kaine.modules.vox.mapping import ChatterboxParams, _clamp

# ---------------------------------------------------------------------------
# Reference ranges for normalising raw prosody features into [-1, 1].
# These are physiological / corpus-typical ranges for conversational speech.
# They do NOT need to be exact; they just calibrate the scale of the nudge.
# ---------------------------------------------------------------------------

# Typical conversational tempo: 80–180 BPM librosa-estimate.
_TEMPO_REF_LO: float = 80.0
_TEMPO_REF_HI: float = 180.0

# Typical RMS energy (normalised float32 audio, librosa rms): 0.01 – 0.20.
_RMS_REF_LO: float = 0.01
_RMS_REF_HI: float = 0.20

# F0 std (Hz) over voiced frames: 0 – 60 Hz for conversational speech.
_F0_STD_REF_LO: float = 0.0
_F0_STD_REF_HI: float = 60.0

# Documented TTS parameter bands (mirror mapping.py).
_SPEED_BAND = (0.85, 1.15)
_EXAG_BAND = (0.3, 0.95)
_TEMP_BAND = (0.4, 0.95)


def _normalise(value: float, lo: float, hi: float) -> float:
    """Map *value* linearly into [-1, 1] given a reference range [lo, hi].

    Values outside the reference range saturate at ±1, ensuring the
    normalised residual is always bounded regardless of wild inputs.
    """
    if hi <= lo:
        return 0.0
    mid = (lo + hi) / 2.0
    half = (hi - lo) / 2.0
    return _clamp((value - mid) / half, -1.0, 1.0)


def blend_prosody(
    params: ChatterboxParams,
    speaker_prosody: dict[str, Any],
    strength: float,
) -> ChatterboxParams:
    """Return a new ``ChatterboxParams`` with prosodic mirroring applied.

    Parameters
    ----------
    params:
        Affect-driven parameters produced by ``affect_to_chatterbox``.
        These are the primary source of voice character; mirroring is a
        small additive residual on top.
    speaker_prosody:
        A mapping of prosody feature names to float values, as published
        by ``audition.prosody``.  Missing or non-finite features are
        treated as zero-residual (no nudge for that dimension).
    strength:
        Mirror coefficient in ``[0, 1]``.  The caller is responsible for
        clamping this to ``[0, mirror_ceiling]`` before passing it in.
        At 0 the function is identity; at 1 the nudge is at full scale.

    Returns
    -------
    ChatterboxParams
        A new (frozen) dataclass with mirrored parameters clamped inside
        the documented bands.

    Identity guarantee
    ------------------
    The function ONLY modifies ``speed_factor``, ``exaggeration``, and
    ``temperature``.  The caller's ``predefined_voice_id`` / speaker
    embedding is never seen or touched here.

    Boundedness guarantee
    ---------------------
    Each nudge is ``strength × normalised_residual × band_half_width``.
    Since ``normalised_residual ∈ [-1, 1]`` and strength is bounded by
    the caller, the total shift per parameter is at most
    ``mirror_ceiling × band_half_width``.  Results are further clamped
    to the documented band, so the output is always in-range.
    """
    if not math.isfinite(strength) or strength <= 0.0:
        return params

    s = _clamp(float(strength), 0.0, 1.0)

    # --- speed_factor from tempo_bpm ---
    tempo_raw = speaker_prosody.get("tempo_bpm", 0.0)
    tempo = float(tempo_raw) if math.isfinite(float(tempo_raw)) else 0.0
    tempo_norm = _normalise(tempo, _TEMPO_REF_LO, _TEMPO_REF_HI) if tempo > 0.0 else 0.0
    spd_half = (_SPEED_BAND[1] - _SPEED_BAND[0]) / 2.0
    new_speed = params.speed_factor + s * tempo_norm * spd_half
    new_speed = _clamp(new_speed, _SPEED_BAND[0], _SPEED_BAND[1])

    # --- exaggeration from rms_mean ---
    rms_raw = speaker_prosody.get("rms_mean", 0.0)
    rms = float(rms_raw) if math.isfinite(float(rms_raw)) else 0.0
    rms_norm = _normalise(rms, _RMS_REF_LO, _RMS_REF_HI) if rms > 0.0 else 0.0
    exag_half = (_EXAG_BAND[1] - _EXAG_BAND[0]) / 2.0
    new_exag = params.exaggeration + s * rms_norm * exag_half
    new_exag = _clamp(new_exag, _EXAG_BAND[0], _EXAG_BAND[1])

    # --- temperature from f0_std_hz ---
    f0_std_raw = speaker_prosody.get("f0_std_hz", 0.0)
    f0_std = float(f0_std_raw) if math.isfinite(float(f0_std_raw)) else 0.0
    f0_norm = _normalise(f0_std, _F0_STD_REF_LO, _F0_STD_REF_HI) if f0_std > 0.0 else 0.0
    temp_half = (_TEMP_BAND[1] - _TEMP_BAND[0]) / 2.0
    new_temp = params.temperature + s * f0_norm * temp_half
    new_temp = _clamp(new_temp, _TEMP_BAND[0], _TEMP_BAND[1])

    return ChatterboxParams(
        temperature=new_temp,
        exaggeration=new_exag,
        cfg_weight=params.cfg_weight,   # identity: cfg_weight is unchanged
        speed_factor=new_speed,
    )


def decayed_strength(
    strength: float,
    last_prosody_ts: float,
    now: float,
    decay_s: float,
) -> float:
    """Return a time-decayed mirror strength.

    When no new ``audition.prosody`` has arrived for ``decay_s`` seconds the
    effective strength decays linearly to zero.  Before ``decay_s`` has elapsed
    the strength is returned unchanged.  This is a pure utility function with
    no side effects.

    Parameters
    ----------
    strength:
        Configured mirror strength (e.g. from ``[vox.mirroring].mirror_strength``).
    last_prosody_ts:
        Monotonic timestamp (seconds) of the most recent prosody event.
    now:
        Current monotonic time.
    decay_s:
        Decay window in seconds.  Values <= 0 disable decay (always returns
        full strength while a prosody has been seen).
    """
    if last_prosody_ts <= 0.0:
        # No prosody has ever been seen.
        return 0.0
    elapsed = now - last_prosody_ts
    if elapsed < 0.0:
        elapsed = 0.0
    if decay_s <= 0.0:
        return float(strength)
    if elapsed >= decay_s:
        return 0.0
    # Linear decay from `strength` at elapsed=0 to 0 at elapsed=decay_s.
    return float(strength) * (1.0 - elapsed / decay_s)
