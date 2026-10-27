# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Hearing band schedule and FIR filter design.

The developmental stimulus's audio passes a hearing band that widens in steps,
following the order fetal hearing matures. A stage ends when audition's own
learning progress has saturated (or at a dwell cap), not at a fixed time; the
rule lives in ``hearing_stage_state.HearingStageState``, and this module only
holds the stage edges and the filter design. Band edges are
placed geometrically midway between the outermost tested tone the fetus can
hear and the next tested tone outside that range. Once the lowest tested
tone (100 Hz) is heard there is no unheard tone below it, so the low edge
disappears; likewise once the highest tested tone (3000 Hz) is heard the high
edge disappears. ``None`` in a stage edge means no filter on that side.

Stages:
    0: 500 Hz only (band-pass).
    1: 250 Hz and 500 Hz (band-pass).
    2: 100 Hz through 500 Hz (low-pass; the heartbeat thud and DC pass).
    3: 100 Hz through 1000 Hz (low-pass; the heartbeat thud and DC pass).
    4: 100 Hz through 3000 Hz (open; the heartbeat thud and DC pass).

The bed and voice streams are zero-mean, so passing DC is not audible; the
band-off stream also passes it unchanged.

Hepper and Shahidullah 1994, Archives of Disease in Childhood Fetal and
Neonatal Edition 71(2), F81-F87.
"""

from __future__ import annotations

import functools
import logging
import math
from dataclasses import dataclass

import numpy as np

from kaine.config import require_known_keys

log = logging.getLogger(__name__)

__all__ = (
    "HEARING_TONES_HZ",
    "HEARING_BAND_TAPS",
    "HEARING_BAND_STAGES",
    "HEARING_TOP_TONE_HZ",
    "HearingBandParams",
    "HEARING_FINAL_STAGE",
    "stage_edges",
    "band_taps",
    "band_frequency_response_db",
)

HEARING_TONES_HZ: tuple[float, ...] = (100.0, 250.0, 500.0, 1000.0, 3000.0)

HEARING_BAND_TAPS: int = 1025

# The last stage; the band is open and the schedule is complete.
HEARING_FINAL_STAGE: int = 4

_T0, _T1, _T2, _T3, _T4 = HEARING_TONES_HZ

# Highest tested tone (3000 Hz). With the band on, the maternal voice loads
# with its low-pass here, and the stream rate must exceed twice it.
HEARING_TOP_TONE_HZ: float = _T4

# Edges are geometric midpoints between adjacent tested tones; None means the
# edge disappears because there is no unheard tested tone beyond it.
HEARING_BAND_STAGES: tuple[tuple[float | None, float | None], ...] = (
    (math.sqrt(_T1 * _T2), math.sqrt(_T2 * _T3)),
    (math.sqrt(_T0 * _T1), math.sqrt(_T2 * _T3)),
    (None, math.sqrt(_T2 * _T3)),
    (None, math.sqrt(_T3 * _T4)),
    (None, None),
)


_MAX_SECONDS = 2592000.0

_RETIRED_KEYS = frozenset({"maturation_seconds"})

_TABLE = "[perception_feed.stimulus_source.hearing]"


def _seconds_field(section: dict, key: str, default: float) -> float:
    table = _TABLE
    value = section.get(key, default)
    if isinstance(value, bool):
        raise ValueError(
            f"{table} {key} must be a finite number in (0.0, {_MAX_SECONDS}], got bool"
        )
    if not isinstance(value, (int, float)):
        raise ValueError(
            f"{table} {key} must be a finite number in (0.0, {_MAX_SECONDS}], "
            f"got {type(value).__name__}"
        )
    value = float(value)
    if not math.isfinite(value):
        raise ValueError(
            f"{table} {key} must be a finite number in (0.0, {_MAX_SECONDS}], got non-finite"
        )
    if not (0.0 < value <= _MAX_SECONDS):
        raise ValueError(f"{table} {key} must be in (0.0, {_MAX_SECONDS}], got {value}")
    return value


@dataclass(frozen=True)
class HearingBandParams:
    """Parameters for the widening hearing band.

    Attributes:
        enabled: Whether the hearing band filter is active.
        saturation_window_seconds: Awake seconds audition's learning progress
            must stay below the floor for a stage to end by saturation.
        min_dwell_seconds: Awake seconds a stage must have run before
            saturation can end it.
        max_dwell_seconds: Awake seconds after which a stage ends regardless
            of learning progress.
    """

    enabled: bool = True
    saturation_window_seconds: float = 600.0
    min_dwell_seconds: float = 5400.0
    max_dwell_seconds: float = 25200.0

    @classmethod
    def from_section(cls, section: dict | None) -> "HearingBandParams":
        """Build parameters from a configuration table.

        Args:
            section: A mapping with optional keys ``enabled``,
                ``saturation_window_seconds``, ``min_dwell_seconds`` and
                ``max_dwell_seconds``. The retired key ``maturation_seconds``
                is accepted and ignored with a warning. ``None`` is treated
                as an empty table.

        Returns:
            A populated ``HearingBandParams`` instance.

        Raises:
            ValueError: If ``section`` is not a dict, contains unknown keys,
                holds invalid values, or violates
                ``0 < saturation_window_seconds <= min_dwell_seconds <=
                max_dwell_seconds``.
        """
        table = _TABLE
        if section is None:
            section = {}
        if not isinstance(section, dict):
            raise ValueError(f"{table} must be a table")

        require_known_keys(
            section,
            {
                "enabled",
                "saturation_window_seconds",
                "min_dwell_seconds",
                "max_dwell_seconds",
            }
            | _RETIRED_KEYS,
            table,
        )
        for key in sorted(_RETIRED_KEYS & set(section)):
            log.warning(
                "%s.%s is retired and ignored; delete it from the configuration file",
                table,
                key,
            )

        enabled = section.get("enabled", True)
        if not isinstance(enabled, bool):
            raise ValueError(
                f"{table} enabled must be a bool, got {type(enabled).__name__}"
            )

        window = _seconds_field(section, "saturation_window_seconds", 600.0)
        min_dwell = _seconds_field(section, "min_dwell_seconds", 5400.0)
        max_dwell = _seconds_field(section, "max_dwell_seconds", 25200.0)
        if not (window <= min_dwell <= max_dwell):
            raise ValueError(
                f"{table} requires saturation_window_seconds <= min_dwell_seconds "
                f"<= max_dwell_seconds, got {window}, {min_dwell}, {max_dwell}"
            )

        return cls(
            enabled=enabled,
            saturation_window_seconds=window,
            min_dwell_seconds=min_dwell,
            max_dwell_seconds=max_dwell,
        )


def stage_edges(stage: int) -> tuple[float | None, float | None]:
    """Return the low and high band edges for a hearing stage.

    A stage outside ``[0, HEARING_FINAL_STAGE]`` is clamped into range and a
    non-integer (or bool) stage is treated as stage 0.
    """
    if isinstance(stage, bool) or not isinstance(stage, int):
        stage = 0
    return HEARING_BAND_STAGES[max(0, min(HEARING_FINAL_STAGE, stage))]


def band_taps(
    low_hz: float | None, high_hz: float | None, sample_rate: float
) -> np.ndarray:
    """Design a windowed FIR hearing-band filter.

    The filter type depends on which edges are supplied:
    * both: band-pass, unity gain at the geometric centre;
    * only ``high_hz``: low-pass, unity DC gain;
    * only ``low_hz``: high-pass, total (no current stage uses this);
    * neither: identity, a single unit impulse so delay stays constant.

    All variants share ``HEARING_BAND_TAPS`` coefficients and are symmetric
    about the centre tap, so the group delay is ``(HEARING_BAND_TAPS - 1) / 2``
    samples regardless of stage.

    Args:
        low_hz: Lower cutoff frequency in Hz, or ``None`` for no high-pass edge.
        high_hz: Upper cutoff frequency in Hz, or ``None`` for no low-pass edge.
        sample_rate: Audio sample rate in Hz.

    Returns:
        A length ``HEARING_BAND_TAPS`` float64 coefficient array.

    Raises:
        ValueError: If ``sample_rate`` is not finite and positive, a supplied
            edge is not finite and in ``(0, sample_rate / 2)``, or both edges
            are supplied with ``low_hz >= high_hz``.
    """
    if not (math.isfinite(sample_rate) and sample_rate > 0.0):
        raise ValueError("sample_rate must be finite and positive")

    def _check_edge(edge: float) -> None:
        if not (
            math.isfinite(edge) and 0.0 < edge < sample_rate / 2.0
        ):
            raise ValueError(
                "each band edge must be finite and satisfy 0 < edge < sample_rate / 2"
            )

    if low_hz is not None:
        _check_edge(low_hz)
    if high_hz is not None:
        _check_edge(high_hz)
    if low_hz is not None and high_hz is not None and not (low_hz < high_hz):
        raise ValueError("low_hz must be less than high_hz")

    return _cached_band_taps(
        float(low_hz) if low_hz is not None else None,
        float(high_hz) if high_hz is not None else None,
        float(sample_rate),
    ).copy()


@functools.lru_cache(maxsize=16)
def _cached_band_taps(
    low_hz: float | None, high_hz: float | None, sample_rate: float
) -> np.ndarray:
    """Compute hearing-band taps; the result is cached and returned without copying."""
    N = HEARING_BAND_TAPS
    n = np.arange(N, dtype=np.float64) - (N - 1) / 2.0
    centre = (N - 1) // 2

    def _lowpass(cutoff_hz: float) -> np.ndarray:
        b = cutoff_hz / sample_rate
        h = 2.0 * b * np.sinc(2.0 * b * n)
        h *= np.hamming(N)
        return h / h.sum()

    if low_hz is None and high_hz is None:
        h = np.zeros(N, dtype=np.float64)
        h[centre] = 1.0
        return h

    if low_hz is None:
        return _lowpass(high_hz)

    if high_hz is None:
        delta = np.zeros(N, dtype=np.float64)
        delta[centre] = 1.0
        return delta - _lowpass(low_hz)

    a = low_hz / sample_rate
    b = high_hz / sample_rate

    h = 2.0 * b * np.sinc(2.0 * b * n) - 2.0 * a * np.sinc(2.0 * a * n)
    h *= np.hamming(N)

    fc = math.sqrt(low_hz * high_hz)
    g = abs(np.sum(h * np.exp(-2j * np.pi * (fc / sample_rate) * n)))
    if g == 0.0:
        raise ValueError(
            "unable to normalize bandpass filter with zero centre gain"
        )
    h = h / g

    return h


def band_frequency_response_db(
    taps: np.ndarray, freq_hz: float, sample_rate: float
) -> float:
    """Evaluate the magnitude response of ``taps`` at ``freq_hz`` in dB.

    Args:
        taps: FIR coefficient array.
        freq_hz: Frequency to evaluate in Hz.
        sample_rate: Audio sample rate in Hz.

    Returns:
        Magnitude in dB, or ``-inf`` for an exact zero response.
    """
    N = len(taps)
    n = np.arange(N, dtype=np.float64) - (N - 1) / 2.0
    response = np.sum(taps * np.exp(-2j * np.pi * (freq_hz / sample_rate) * n))
    amplitude = abs(response)

    if amplitude == 0.0:
        return float("-inf")
    return float(20.0 * np.log10(amplitude))
