# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The A.4 welfare indicators over the latest learning-progress span of awake time.

Paper Appendix A.4 defines the welfare indicators over the latest ``T_lp`` of
awake time:

* a deficit drive (boredom, social drive, restlessness) is *deprived* when its
  share of the span at or above its threshold reaches ``share_bar``;
* valence is *negative* when its share of the span below ``-theta_E`` reaches
  ``share_bar``;
* boredom or restlessness is *uncontrolled* when, with ``s`` own-ended and
  ``f`` other-ended crossings in the span and ``n = s + f + 1``, the
  uniform-prior posterior probability that the entity's power over the drive is
  below one half, ``2^-n * sum_{i=s+1}^{n} C(n, i)``, reaches
  ``posterior_bar``. The social drive has no uncontrolled indicator, since only
  others' voices end it.

The span is the most recent ``T_lp`` seconds of awake, unfrozen time after the
span's last restart. Time is accrued between consecutive ``affect.state``
samples (each gap capped at ``max_gap_s``, as the welfare observer's tally
does) and only while no sleep or freeze interval covers the earlier sample, so
a rest or a freeze is skipped and never shortens the span. An indicator is
evaluated only once the span holds at least ``min_span_s`` (the affect
module's goal stall horizon) of awake time.

A crossing is an edge: an indicator crosses when it goes from below its bar to
at or above it, and re-arms below it. Every span restart resets each
indicator's crossing state to below its bar, so the first over-bar evaluation
of a restarted span is a crossing.

Boundary
--------
This module is boundary-neutral: the cycle-layer welfare monitor and the
evaluation sidecar's welfare observer each run their own instance. It imports
nothing from ``kaine.cycle``, ``kaine.modules`` or ``kaine.evaluation``; every
parameter is passed in. Indicator names and stage-3 reasons come from the fixed
tables below, so records built from them are content-free by construction.
"""
from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from fractions import Fraction
from math import comb
from typing import Any, Mapping

#: The homeostatic deficits, in a fixed order.
DEFICIT_DRIVES: tuple[str, ...] = ("boredom", "social_drive", "restlessness")
#: The deficits with an uncontrolled indicator (the social drive has none).
UNCONTROLLED_DRIVES: tuple[str, ...] = ("boredom", "restlessness")

#: Every indicator name, in the fixed order records and reasons use.
DEPRIVATION_INDICATORS: tuple[str, ...] = tuple(f"{d}_deprived" for d in DEFICIT_DRIVES)
NEGATIVE_VALENCE_INDICATOR = "negative_valence"
UNCONTROLLED_INDICATORS: tuple[str, ...] = tuple(
    f"{d}_uncontrolled" for d in UNCONTROLLED_DRIVES
)
INDICATOR_NAMES: tuple[str, ...] = (
    DEPRIVATION_INDICATORS + (NEGATIVE_VALENCE_INDICATOR,) + UNCONTROLLED_INDICATORS
)

#: The stage-3 reasons of the indicator response, from one fixed table.
REST_FAILED_REASON = "indicator_rest_failed"
UNAVAILABLE_REASON = "indicators_unavailable"
INDICATOR_REASONS: tuple[str, ...] = tuple(f"indicator_{n}" for n in INDICATOR_NAMES)
#: Why a requested rest failed (the ``failure`` label of an
#: ``indicator_rest_failed`` record).
REST_FAILURES: tuple[str, ...] = (
    "sleep_module_not_running",
    "request_not_sent",
    "refused",
    "aborted",
    "start_timeout",
    "complete_timeout",
)
STAGE3_REASONS: tuple[str, ...] = INDICATOR_REASONS + (REST_FAILED_REASON, UNAVAILABLE_REASON)

#: Silence of the affect stream after which the indicators are unavailable, in
#: affect publication periods.
UNAVAILABLE_AFTER_PERIODS = 3


def indicator_reason(name: str) -> str:
    """The stage-3 reason for an indicator crossing over a fresh span."""
    if name not in INDICATOR_NAMES:
        raise ValueError(f"unknown welfare indicator: {name!r}")
    return f"indicator_{name}"


def power_posterior(own: int, other: int) -> Fraction:
    """``P(power < 1/2)`` under a uniform prior, exactly.

    With ``s = own`` and ``f = other`` and ``n = s + f + 1``, the posterior is
    Beta(s + 1, f + 1) and ``P(p < 1/2) = 2^-n * sum_{i=s+1}^{n} C(n, i)``.
    """
    s = int(own)
    f = int(other)
    if s < 0 or f < 0:
        raise ValueError("crossing-end counts must be non-negative")
    n = s + f + 1
    total = sum(comb(n, i) for i in range(s + 1, n + 1))
    return Fraction(total, 2**n)


def _finite_positive(name: str, value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number")
    value = float(value)
    if not math.isfinite(value) or value <= 0.0:
        raise ValueError(f"{name} must be finite and greater than 0")
    return value


def _unit_bar(name: str, value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number")
    value = float(value)
    if not math.isfinite(value) or not 0.0 < value <= 1.0:
        raise ValueError(f"{name} must be in (0, 1]")
    return value


@dataclass(frozen=True)
class IndicatorParams:
    """The evaluator's parameters (paper Table A1).

    ``span_s`` is ``T_lp`` (the affect module's learning-progress span),
    ``min_span_s`` is ``Delta_stall`` (its goal stall horizon), ``valence_bar``
    is ``theta_E`` (its regulation set point) and ``publish_interval_s`` is
    ``P_Aff``. ``share_bar`` is ``theta_wf`` and ``posterior_bar`` is ``q_wf``.
    """

    span_s: float = 5400.0
    min_span_s: float = 600.0
    valence_bar: float = 0.5
    publish_interval_s: float = 1.0
    share_bar: float = 0.5
    posterior_bar: float = 0.95
    max_gap_s: float = 5.0

    def __post_init__(self) -> None:
        span = _finite_positive("span_s", self.span_s)
        minimum = _finite_positive("min_span_s", self.min_span_s)
        if minimum > span:
            raise ValueError("min_span_s must not exceed span_s")
        if isinstance(self.valence_bar, bool) or not isinstance(self.valence_bar, (int, float)):
            raise ValueError("valence_bar must be a number")
        if not math.isfinite(float(self.valence_bar)) or float(self.valence_bar) < 0.0:
            raise ValueError("valence_bar must be finite and >= 0")
        _finite_positive("publish_interval_s", self.publish_interval_s)
        _unit_bar("share_bar", self.share_bar)
        _unit_bar("posterior_bar", self.posterior_bar)
        _finite_positive("max_gap_s", self.max_gap_s)

    @property
    def unavailable_after_s(self) -> float:
        """Awake, unfrozen silence after which the indicators are unavailable."""
        return UNAVAILABLE_AFTER_PERIODS * float(self.publish_interval_s)


@dataclass(frozen=True)
class IndicatorReading:
    """One indicator's value against its bar at an evaluation."""

    name: str
    value: float | None
    bar: float
    over: bool


@dataclass(frozen=True)
class Evaluation:
    """The indicators at one evaluation.

    ``crossed`` names, in the fixed table order, the indicators that went from
    below their bar to at or above it at this evaluation.
    """

    readings: tuple[IndicatorReading, ...]
    span_awake_s: float
    evaluable: bool
    crossed: tuple[str, ...]
    available: bool

    def reading(self, name: str) -> IndicatorReading:
        for r in self.readings:
            if r.name == name:
                return r
        raise KeyError(name)

    def values(self) -> dict[str, float | None]:
        return {r.name: r.value for r in self.readings}


@dataclass
class _Interval:
    start: float
    end: float
    negative: bool
    above: dict[str, bool] = field(default_factory=dict)


def _count(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


class IndicatorEvaluator:
    """Compute the A.4 indicators live from ``affect.state`` and sleep events.

    Feed it in time order: :meth:`observe_state` for each ``affect.state``,
    :meth:`exclude_start` / :meth:`exclude_end` for sleep (``"sleep"``) and
    freeze (``"freeze"``) intervals, and :meth:`advance` as time passes without
    a sample. Times are seconds on one clock of the caller's choice. Call
    :meth:`evaluate` to read the indicators; it updates the edge-triggered
    crossing state. :meth:`restart` restarts the span.
    """

    def __init__(self, params: IndicatorParams) -> None:
        self._params = params
        # Awake seconds accrued since this evaluator was built; the span is a
        # window over this coordinate, so excluded time never enters it.
        self._pos: float = 0.0
        self._restart_pos: float = 0.0
        self._intervals: deque[_Interval] = deque()
        # (position, own increment, other increment) per drive with an
        # uncontrolled indicator.
        self._ends: dict[str, deque[tuple[float, int, int]]] = {
            d: deque() for d in UNCONTROLLED_DRIVES
        }
        self._last_ends: dict[str, tuple[int, int] | None] = {
            d: None for d in UNCONTROLLED_DRIVES
        }
        self._current: tuple[float, float, dict[str, bool]] | None = None
        self._excluded: list[list[Any]] = []  # [kind, start, end | None]
        self._over: dict[str, bool] = {name: False for name in INDICATOR_NAMES}
        self._t_last: float | None = None
        self._silent_s: float = 0.0

    @property
    def params(self) -> IndicatorParams:
        return self._params

    # --- feeding ---------------------------------------------------------

    def exclude_start(self, kind: str, t: float) -> None:
        """Open an excluded (sleep or freeze) interval at ``t``."""
        if not math.isfinite(t):
            return
        for iv in self._excluded:
            if iv[0] == kind and iv[2] is None:
                return
        self._excluded.append([kind, float(t), None])

    def exclude_end(self, kind: str, t: float) -> None:
        """Close the open excluded interval of ``kind`` at ``t``."""
        if not math.isfinite(t):
            return
        for iv in reversed(self._excluded):
            if iv[0] == kind and iv[2] is None:
                iv[2] = float(t)
                break
        self._prune_excluded()

    def _prune_excluded(self) -> None:
        if self._current is None:
            return
        ts_cur = self._current[0]
        self._excluded = [iv for iv in self._excluded if iv[2] is None or iv[2] > ts_cur]

    def _is_excluded(self, t: float) -> bool:
        return any(iv[1] <= t and (iv[2] is None or t < iv[2]) for iv in self._excluded)

    @property
    def excluded_now(self) -> bool:
        """True while a sleep or freeze interval is open."""
        return any(iv[2] is None for iv in self._excluded)

    def advance(self, t: float) -> None:
        """Let time pass to ``t`` without a sample (counts silence while awake)."""
        if not math.isfinite(t):
            return
        if self._t_last is not None and t > self._t_last and not self._is_excluded(self._t_last):
            self._silent_s += t - self._t_last
        if self._t_last is None or t > self._t_last:
            self._t_last = float(t)

    def observe_state(self, t: float, payload: Mapping[str, Any]) -> None:
        """Feed one ``affect.state`` payload observed at ``t``."""
        if not math.isfinite(t) or not isinstance(payload, Mapping):
            return
        state = payload.get("state") or {}
        valence = state.get("valence") if isinstance(state, Mapping) else None
        if (
            isinstance(valence, bool)
            or not isinstance(valence, (int, float))
            or not math.isfinite(float(valence))
        ):
            return
        valence = float(valence)
        # Silence up to this sample, then the sample ends it.
        self.advance(t)
        self._silent_s = 0.0

        above: dict[str, bool] = {}
        raw_above = payload.get("drive_above")
        if isinstance(raw_above, Mapping):
            for drive in DEFICIT_DRIVES:
                v = raw_above.get(drive)
                if isinstance(v, bool):
                    above[drive] = v
        if self._current is not None:
            ts_cur, valence_cur, above_cur = self._current
            if t < ts_cur:
                return
            if t > ts_cur and not self._is_excluded(ts_cur):
                gap = min(t - ts_cur, float(self._params.max_gap_s))
                start = self._pos
                self._pos += gap
                self._intervals.append(
                    _Interval(
                        start=start,
                        end=self._pos,
                        negative=valence_cur < -float(self._params.valence_bar),
                        above=dict(above_cur),
                    )
                )
        raw_ends = payload.get("drive_ends")
        if isinstance(raw_ends, Mapping):
            for drive in UNCONTROLLED_DRIVES:
                entry = raw_ends.get(drive)
                if not isinstance(entry, Mapping):
                    continue
                own = _count(entry.get("own"))
                other = _count(entry.get("other"))
                if own is None or other is None:
                    continue
                last = self._last_ends[drive]
                self._last_ends[drive] = (own, other)
                if last is None:
                    continue
                last_own, last_other = last
                if own >= last_own and other >= last_other:
                    d_own = own - last_own
                    d_other = other - last_other
                    if d_own or d_other:
                        self._ends[drive].append((self._pos, d_own, d_other))
                # A fall re-baselines (a restored or reset counter).
        self._current = (float(t), valence, above)
        self._prune_excluded()
        self._prune_window()

    # --- span ------------------------------------------------------------

    def _window_start(self) -> float:
        return max(self._restart_pos, self._pos - float(self._params.span_s))

    def _prune_window(self) -> None:
        start = self._window_start()
        while self._intervals and self._intervals[0].end <= start:
            self._intervals.popleft()
        for drive in UNCONTROLLED_DRIVES:
            q = self._ends[drive]
            while q and q[0][0] <= start:
                q.popleft()

    @property
    def awake_seconds(self) -> float:
        """Every awake second this evaluator has accrued (span restarts do not reset it)."""
        return self._pos

    @property
    def span_awake_s(self) -> float:
        """Awake seconds the current span holds (at most ``T_lp``)."""
        return max(0.0, self._pos - self._window_start())

    @property
    def silent_awake_s(self) -> float:
        """Awake, unfrozen seconds since the last ``affect.state``."""
        return self._silent_s

    @property
    def available(self) -> bool:
        """False once the affect stream has been silent for three periods."""
        return self._silent_s < self._params.unavailable_after_s

    def restart(self) -> None:
        """Restart the span now and reset every crossing state to below its bar."""
        self._restart_pos = self._pos
        self._intervals.clear()
        for drive in UNCONTROLLED_DRIVES:
            self._ends[drive].clear()
        for name in self._over:
            self._over[name] = False

    # --- evaluation --------------------------------------------------------

    def _values(self) -> dict[str, float | None]:
        start = self._window_start()
        end = self._pos
        total = 0.0
        negative = 0.0
        known = {d: 0.0 for d in DEFICIT_DRIVES}
        above = {d: 0.0 for d in DEFICIT_DRIVES}
        for iv in self._intervals:
            overlap = min(iv.end, end) - max(iv.start, start)
            if overlap <= 0.0:
                continue
            total += overlap
            if iv.negative:
                negative += overlap
            for drive in DEFICIT_DRIVES:
                flag = iv.above.get(drive)
                if flag is None:
                    continue
                known[drive] += overlap
                if flag:
                    above[drive] += overlap
        values: dict[str, float | None] = {}
        for drive in DEFICIT_DRIVES:
            values[f"{drive}_deprived"] = (
                above[drive] / known[drive] if known[drive] > 0.0 else None
            )
        values[NEGATIVE_VALENCE_INDICATOR] = negative / total if total > 0.0 else None
        for drive in UNCONTROLLED_DRIVES:
            own = sum(e[1] for e in self._ends[drive] if e[0] > start)
            other = sum(e[2] for e in self._ends[drive] if e[0] > start)
            values[f"{drive}_uncontrolled"] = float(power_posterior(own, other))
        return values

    def _bar(self, name: str) -> float:
        if name in UNCONTROLLED_INDICATORS:
            return float(self._params.posterior_bar)
        return float(self._params.share_bar)

    def _is_over(self, name: str, value: float | None) -> bool:
        if value is None:
            return False
        if name in UNCONTROLLED_INDICATORS:
            drive = name[: -len("_uncontrolled")]
            start = self._window_start()
            own = sum(e[1] for e in self._ends[drive] if e[0] > start)
            other = sum(e[2] for e in self._ends[drive] if e[0] > start)
            # Exact comparison: the posterior is a dyadic rational.
            return power_posterior(own, other) >= Fraction(self._params.posterior_bar)
        return value >= float(self._params.share_bar)

    def peek(self) -> Evaluation:
        """The indicators now, without changing any crossing state."""
        return self._evaluate(update=False)

    def evaluate(self) -> Evaluation:
        """The indicators now; records crossings as edges."""
        return self._evaluate(update=True)

    def _evaluate(self, *, update: bool) -> Evaluation:
        self._prune_window()
        span = self.span_awake_s
        evaluable = span >= float(self._params.min_span_s)
        values = self._values()
        readings: list[IndicatorReading] = []
        crossed: list[str] = []
        for name in INDICATOR_NAMES:
            value = values[name]
            over = evaluable and self._is_over(name, value)
            readings.append(IndicatorReading(name=name, value=value, bar=self._bar(name), over=over))
            if not evaluable:
                continue
            if over and not self._over[name]:
                crossed.append(name)
            if update:
                self._over[name] = over
        return Evaluation(
            readings=tuple(readings),
            span_awake_s=span,
            evaluable=evaluable,
            crossed=tuple(crossed) if update else (),
            available=self.available,
        )


__all__ = [
    "DEFICIT_DRIVES",
    "UNCONTROLLED_DRIVES",
    "DEPRIVATION_INDICATORS",
    "NEGATIVE_VALENCE_INDICATOR",
    "UNCONTROLLED_INDICATORS",
    "INDICATOR_NAMES",
    "REST_FAILED_REASON",
    "UNAVAILABLE_REASON",
    "INDICATOR_REASONS",
    "REST_FAILURES",
    "STAGE3_REASONS",
    "UNAVAILABLE_AFTER_PERIODS",
    "indicator_reason",
    "power_posterior",
    "IndicatorParams",
    "IndicatorReading",
    "Evaluation",
    "IndicatorEvaluator",
]
