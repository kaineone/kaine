# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Hearing band schedule and FIR filter design.

The developmental stimulus's audio passes a hearing band that widens over the
entity's awake time, following the order fetal hearing matures: fetuses first
respond to a 500 Hz tone; the range of tones responded to then widens
downwards to 250 Hz and 100 Hz, and then upwards to 1000 Hz and 3000 Hz.

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
    "HEARING_BAND_END_HIGH_HZ",
    "HearingBandParams",
    "hearing_stage",
    "band_edges",
    "band_taps",
    "band_frequency_response_db",
)

HEARING_TONES_HZ: tuple[float, ...] = (100.0, 250.0, 500.0, 1000.0, 3000.0)

HEARING_BAND_TAPS: int = 1025

_T0, _T1, _T2, _T3, _T4 = HEARING_TONES_HZ
HEARING_BAND_STAGES: tuple[tuple[float, float], ...] = (
    (math.sqrt(_T1 * _T2), math.sqrt(_T2 * _T3)),
    (math.sqrt(_T0 * _T1), math.sqrt(_T2 * _T3)),
    (_T0, math.sqrt(_T2 * _T3)),
    (_T0, math.sqrt(_T3 * _T4)),
    (_T0, _T4),
)

HEARING_BAND_END_HIGH_HZ: float = HEARING_BAND_STAGES[-1][1]


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

    if not math.isfinite(T) or T < W / 4.0:
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


def band_edges(awake_seconds: float, params: HearingBandParams) -> tuple[float, float]:
    """Return the low and high band edges for the given awake time."""
    return HEARING_BAND_STAGES[hearing_stage(awake_seconds, params)]


def band_taps(low_hz: float, high_hz: float, sample_rate: float) -> np.ndarray:
    """Design a windowed FIR bandpass filter.

    The filter is a Hamming-windowed difference of two sinc lowpass kernels
    with cutoffs at ``low_hz`` and ``high_hz``. It is normalized so that the
    response at the geometric centre frequency is unity.

    Args:
        low_hz: Lower cutoff frequency in Hz.
        high_hz: Upper cutoff frequency in Hz.
        sample_rate: Audio sample rate in Hz.

    Returns:
        A length ``HEARING_BAND_TAPS`` float64 coefficient array.

    Raises:
        ValueError: If the edges do not satisfy
            ``0 < low_hz < high_hz < sample_rate / 2``.
    """
    if not (
        math.isfinite(low_hz)
        and math.isfinite(high_hz)
        and math.isfinite(sample_rate)
    ):
        raise ValueError(
            "band edges must satisfy 0 < low_hz < high_hz < sample_rate / 2"
        )
    if not (0.0 < low_hz < high_hz < sample_rate / 2.0):
        raise ValueError(
            "band edges must satisfy 0 < low_hz < high_hz < sample_rate / 2"
        )

    return _cached_band_taps(float(low_hz), float(high_hz), float(sample_rate)).copy()


@functools.lru_cache(maxsize=16)
def _cached_band_taps(low_hz: float, high_hz: float, sample_rate: float) -> np.ndarray:
    """Compute bandpass taps; the result is cached and returned without copying."""
    N = HEARING_BAND_TAPS
    n = np.arange(N, dtype=np.float64) - (N - 1) / 2.0
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
