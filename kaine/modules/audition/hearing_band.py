# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Hearing band schedule and FIR filter design.

The developmental stimulus's audio passes a hearing band that widens over the
entity's awake time, following the order fetal hearing matures. Band edges are
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
import math
from dataclasses import dataclass

import numpy as np

from kaine.config import require_known_keys

__all__ = (
    "HEARING_TONES_HZ",
    "HEARING_BAND_TAPS",
    "HEARING_BAND_STAGES",
    "HEARING_TOP_TONE_HZ",
    "HearingBandParams",
    "hearing_stage",
    "band_edges",
    "band_taps",
    "band_frequency_response_db",
)

HEARING_TONES_HZ: tuple[float, ...] = (100.0, 250.0, 500.0, 1000.0, 3000.0)

HEARING_BAND_TAPS: int = 1025

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


@dataclass(frozen=True)
class HearingBandParams:
    """Parameters for the widening hearing band.

    Attributes:
        enabled: Whether the hearing band filter is active.
        maturation_seconds: Time over which the band widens from the initial
            500 Hz stage to the full range. Constrained to one minute to
            30 days.
    """

    enabled: bool = True
    maturation_seconds: float = 86400.0

    @classmethod
    def from_section(cls, section: dict | None) -> "HearingBandParams":
        """Build parameters from a configuration table.

        Args:
            section: A mapping with optional keys ``enabled`` and
                ``maturation_seconds``. ``None`` is treated as an empty table.

        Returns:
            A populated ``HearingBandParams`` instance.

        Raises:
            ValueError: If ``section`` is not a dict, contains unknown keys,
                or holds invalid values.
        """
        if section is None:
            section = {}
        if not isinstance(section, dict):
            raise ValueError(
                "[perception_feed.stimulus_source.hearing] must be a table"
            )

        table = "[perception_feed.stimulus_source.hearing]"
        require_known_keys(section, {"enabled", "maturation_seconds"}, table)

        enabled = section.get("enabled", True)
        if not isinstance(enabled, bool):
            raise ValueError(
                f"{table} enabled must be a bool, got {type(enabled).__name__}"
            )

        maturation_seconds = section.get("maturation_seconds", 86400.0)
        if isinstance(maturation_seconds, bool):
            raise ValueError(
                f"{table} maturation_seconds must be a finite number in "
                "[60.0, 2592000.0], got bool"
            )
        if not isinstance(maturation_seconds, (int, float)):
            raise ValueError(
                f"{table} maturation_seconds must be a finite number in "
                f"[60.0, 2592000.0], got {type(maturation_seconds).__name__}"
            )
        maturation_seconds = float(maturation_seconds)
        if not math.isfinite(maturation_seconds):
            raise ValueError(
                f"{table} maturation_seconds must be a finite number in "
                "[60.0, 2592000.0], got non-finite"
            )
        if not (60.0 <= maturation_seconds <= 2592000.0):
            raise ValueError(
                f"{table} maturation_seconds must be in [60.0, 2592000.0], "
                f"got {maturation_seconds}"
            )

        return cls(enabled=enabled, maturation_seconds=maturation_seconds)


def hearing_stage(awake_seconds: float, params: HearingBandParams) -> int:
    """Return the hearing band stage for the given awake time.

    Stages advance at exact quarter-marks of ``maturation_seconds`` so that
    boundary times such as ``W / 4`` evaluate unambiguously.

    Args:
        awake_seconds: Time the entity has been awake.
        params: Band parameters.

    Returns:
        An integer stage in ``[0, 4]``.
    """
    T = float(awake_seconds)
    W = params.maturation_seconds

    if not math.isfinite(T):
        return 0

    if T >= W:
        return 4
    if T >= 3.0 * W / 4.0:
        return 3
    if T >= W / 2.0:
        return 2
    if T >= W / 4.0:
        return 1

    return 0


def band_edges(
    awake_seconds: float, params: HearingBandParams
) -> tuple[float | None, float | None]:
    """Return the low and high band edges for the given awake time."""
    return HEARING_BAND_STAGES[hearing_stage(awake_seconds, params)]


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
