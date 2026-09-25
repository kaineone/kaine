# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Adaptive conscious-access rate for the cognitive cycle.

The experiential (conscious-access) rate is not fixed. It rests at the P3b
rate (~3.33 Hz) and rises toward the 10 Hz processing rate when predictions
fail or modules report something salient. This mirrors the locus
coeruleus–noradrenaline (LC-NE) account of the P3b: LC-NE has a tonic mode
that tracks arousal and a phasic mode triggered by salient or unexpected
events, and phasic LC-NE bursts reset and re-engage cortical networks.

References
----------
- Aston-Jones, G., & Cohen, J. D. (2005). An integrative theory of locus
  coeruleus–norepinephrine function: adaptive gain and optimal performance.
  Annual Review of Neuroscience, 28, 403–450.
- Bouret, S., & Sara, S. J. (2005). Network reset: a simplified overarching
  theory of locus coeruleus noradrenaline function. Trends in Neurosciences,
  28(11), 574–582.
- Nieuwenhuis, S., Aston-Jones, G., & Cohen, J. D. (2005). Decision making,
  the P3, and the locus coeruleus–norepinephrine system. Psychological
  Bulletin, 131(4), 510–532.

The linear map from access drive to effective experiential rate is a
deliberate modelling assumption, bounded below by the resting P3b rate and
above by the processing rate. The literature supports the direction and the
bounds, not a measured dose-response curve.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable

from kaine.bus.schema import Event
from kaine.config import require_known_keys


@dataclass(frozen=True)
class AccessRateConfig:
    enabled: bool = True
    salience_floor: float = 0.5
    phasic_decay_s: float = 1.0
    baseline_arousal: float = 0.3

    @classmethod
    def from_section(
        cls, section: dict | None, *, default_baseline: float = 0.3
    ) -> "AccessRateConfig":
        if not section:
            return cls(baseline_arousal=default_baseline)
        require_known_keys(
            section,
            {"enabled", "salience_floor", "phasic_decay_s", "baseline_arousal"},
            "[cycle.access_rate]",
        )

        enabled = section.get("enabled", True)
        if not isinstance(enabled, bool):
            raise ValueError("[cycle.access_rate].enabled must be a bool")

        def _float(key: str, default: float, lo: float, hi: float | None) -> float:
            value = section.get(key, default)
            if isinstance(value, bool):
                raise ValueError(f"[cycle.access_rate].{key} must be a float, not bool")
            try:
                value = float(value)
            except (TypeError, ValueError):
                raise ValueError(f"[cycle.access_rate].{key} must be a float")
            if not math.isfinite(value):
                raise ValueError(f"[cycle.access_rate].{key} must be finite")
            if hi is None:
                if not (lo < value):
                    raise ValueError(f"[cycle.access_rate].{key} must be > {lo}")
            else:
                if not (lo <= value < hi):
                    raise ValueError(f"[cycle.access_rate].{key} must be in [{lo}, {hi})")
            return value

        salience_floor = _float("salience_floor", 0.5, 0.0, 1.0)
        phasic_decay_s = _float("phasic_decay_s", 1.0, 0.0, None)

        baseline_raw = section.get("baseline_arousal", default_baseline)
        if isinstance(baseline_raw, bool):
            raise ValueError("[cycle.access_rate].baseline_arousal must be a float, not bool")
        try:
            baseline_arousal = float(baseline_raw)
        except (TypeError, ValueError):
            raise ValueError("[cycle.access_rate].baseline_arousal must be a float")
        if not math.isfinite(baseline_arousal):
            raise ValueError("[cycle.access_rate].baseline_arousal must be finite")
        if not (0.0 <= baseline_arousal < 1.0):
            raise ValueError("[cycle.access_rate].baseline_arousal must be in [0, 1)")

        return cls(
            enabled=enabled,
            salience_floor=salience_floor,
            phasic_decay_s=phasic_decay_s,
            baseline_arousal=baseline_arousal,
        )


EXCLUDED_SOURCES = frozenset({"cycle", "syneidesis"})


def tonic_drive(arousal: float | None, baseline: float) -> float:
    """Tonic access drive from arousal above its resting baseline.

    ``clamp((arousal - baseline) / (1 - baseline), 0, 1)``. ``None`` or
    non-finite arousal is treated as the resting value (drive 0).
    """
    if arousal is None or not math.isfinite(arousal):
        return 0.0
    if baseline >= 1.0:
        return 0.0
    return max(0.0, min(1.0, (arousal - baseline) / (1.0 - baseline)))


def phasic_input(max_salience: float | None, floor: float) -> float:
    """Normalised salience of the most salient module report this tick.

    ``clamp((s - floor) / (1 - floor), 0, 1)``. ``None`` or non-finite
    salience is treated as below the floor (input 0).
    """
    if max_salience is None or not math.isfinite(max_salience):
        return 0.0
    if floor >= 1.0:
        return 0.0
    return max(0.0, min(1.0, (max_salience - floor) / (1.0 - floor)))


def max_report_salience(events: Iterable[tuple[str, Event]]) -> float | None:
    """Highest salience among module reports in ``events``.

    Events whose source is ``cycle`` or ``syneidesis`` are ignored (the
    cycle's own telemetry and the workspace's own broadcasts are not module
    reports). Returns ``None`` when there are no qualifying reports.
    """
    max_s: float | None = None
    for _entry_id, event in events:
        if event.source in EXCLUDED_SOURCES:
            continue
        salience = getattr(event, "salience", None)
        if salience is None or not math.isfinite(salience):
            continue
        if max_s is None or salience > max_s:
            max_s = salience
    return max_s


class AccessRateController:
    """Stateful LC-NE-like access-drive calculator.

    Holds the decaying phasic peak between ticks. ``step`` is pure aside
    from this state: it uses no clocks and performs no I/O.
    """

    def __init__(self, config: AccessRateConfig) -> None:
        self._config = config
        self.drive: float = 0.0
        self.phasic: float = 0.0

    def step(
        self,
        *,
        events,
        arousal: float | None,
        dt_s: float,
        resting_hz: float,
        ceiling_hz: float,
    ) -> tuple[float, float]:
        """Compute this tick's access drive and effective experiential rate.

        Parameters
        ----------
        events:
            Canonically-ordered ``(entry_id, Event)`` pairs gathered this tick.
        arousal:
            Current Thymos arousal, or ``None`` when unavailable.
        dt_s:
            Subjective time since the previous tick (used for phasic decay).
        resting_hz:
            The configured/resting experiential rate.
        ceiling_hz:
            The processing rate (access cannot exceed sampling).

        Returns
        -------
        ``(drive, effective_hz)`` with ``drive`` in ``[0, 1]`` and
        ``effective_hz`` clamped between ``resting_hz`` and ``ceiling_hz``.
        """
        if not self._config.enabled:
            self.phasic = 0.0
            self.drive = 0.0
            return 0.0, float(resting_hz)

        decayed = self.phasic * math.exp(-max(dt_s, 0.0) / self._config.phasic_decay_s)
        input_val = phasic_input(max_report_salience(events), self._config.salience_floor)
        self.phasic = max(input_val, decayed)
        drive = max(tonic_drive(arousal, self._config.baseline_arousal), self.phasic)
        self.drive = drive

        if resting_hz >= ceiling_hz:
            effective = float(resting_hz)
        else:
            effective = resting_hz + (ceiling_hz - resting_hz) * drive

        lo, hi = min(resting_hz, ceiling_hz), max(resting_hz, ceiling_hz)
        effective = max(lo, min(effective, hi))
        return drive, float(effective)
