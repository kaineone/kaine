# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Oscillatory coherence for Syneidesis selection (oscillatory-binding).

This module computes the **phase-locking value (PLV)** among the modules
contributing to a candidate coalition, over a sliding window of recent phases,
and maps the coalition's mean pairwise PLV into a bounded coherence multiplier
``[coherence_floor, coherence_ceiling]``.

PLV between two phase series ``a`` and ``b`` is
``|mean(exp(i*(a_k - b_k)))|`` over the window — 1.0 when the two are perfectly
phase-locked, ~0.0 when independent. It lies in ``[0, 1]``.

The coherence factor multiplies a coalition's aggregate salience in
``Syneidesis.select`` BEFORE top-k/threshold. The factor is bounded so a
pathologically self-reinforcing coalition cannot run away (paper §9).

**Disabled is bit-for-bit.** When ``enabled`` is false, `Syneidesis` never
constructs or consults a `CoherenceScorer`, so selection is identical to the
pre-change behavior. This module's logic only runs on the enabled path.

The per-module phase sliding-window buffers held here are EPHEMERAL: they are
not serialized and re-initialise to neutral on restart (design.md).
"""
from __future__ import annotations

import math
from collections import defaultdict, deque
from typing import Iterable

from kaine.oscillator import NEUTRAL_PHASE

MIN_PLV_WINDOW: int = 10


def phase_locking_value(phases_a: list[float], phases_b: list[float]) -> float:
    """PLV between two equal-length phase series, in ``[0, 1]``.

    Uses the overlapping suffix when the series differ in length. Returns 1.0
    for a degenerate single-sample overlap (a single phase difference has unit
    magnitude), and 0.0 when there is no overlap.
    """
    n = min(len(phases_a), len(phases_b))
    if n == 0:
        return 0.0
    a = phases_a[-n:]
    b = phases_b[-n:]
    real = 0.0
    imag = 0.0
    for pa, pb in zip(a, b):
        d = pa - pb
        real += math.cos(d)
        imag += math.sin(d)
    plv = math.hypot(real, imag) / n
    # Guard floating point overshoot into [0, 1].
    if plv < 0.0:
        return 0.0
    if plv > 1.0:
        return 1.0
    return plv


def mean_pairwise_plv(windows: list[list[float]]) -> float:
    """Mean PLV over all unordered pairs of phase windows.

    A coalition with fewer than two source modules has no pair to lock; it is
    treated as fully coherent (1.0), so a single-source coalition is never
    attenuated by the coherence term.
    """
    m = len(windows)
    if m < 2:
        return 1.0
    total = 0.0
    pairs = 0
    for i in range(m):
        for j in range(i + 1, m):
            total += phase_locking_value(windows[i], windows[j])
            pairs += 1
    if pairs == 0:
        return 1.0
    return total / pairs


class CoherenceScorer:
    """Tracks per-module phase windows and derives the coherence multiplier.

    Constructed only when ``[oscillator].enabled`` is true. Each tick the cycle
    calls `observe` with the current per-module phases; `factor` then returns
    the bounded coherence multiplier for a coalition's set of source modules,
    and `plv` returns the raw mean pairwise PLV (written to snapshot metadata).
    """

    def __init__(
        self,
        *,
        plv_window: int,
        coherence_floor: float,
        coherence_ceiling: float,
    ) -> None:
        if plv_window < MIN_PLV_WINDOW:
            raise ValueError(
                f"plv_window must be >= {MIN_PLV_WINDOW}, got {plv_window}"
            )
        if not 0.0 <= coherence_floor <= coherence_ceiling:
            raise ValueError(
                "require 0.0 <= coherence_floor <= coherence_ceiling, got "
                f"floor={coherence_floor}, ceiling={coherence_ceiling}"
            )
        if coherence_ceiling <= 0.0:
            # A non-positive ceiling collapses every coalition's factor to 0,
            # turning all scores into a degenerate tie whose sort order is an
            # artefact — never a legitimate coherence-gain setting. (floor ==
            # ceiling > 0, the unit-gain null control, stays valid.)
            raise ValueError(
                "coherence_ceiling must be > 0 (a non-positive ceiling zeroes "
                f"every salience score); got ceiling={coherence_ceiling}"
            )
        self._window = int(plv_window)
        self._floor = float(coherence_floor)
        self._ceiling = float(coherence_ceiling)
        # Ephemeral sliding windows; NOT serialized (re-init to neutral on
        # restart). Keyed by module name (== event source).
        self._buffers: dict[str, deque[float]] = defaultdict(
            lambda: deque(maxlen=self._window)
        )

    @property
    def plv_window(self) -> int:
        return self._window

    @property
    def coherence_floor(self) -> float:
        return self._floor

    @property
    def coherence_ceiling(self) -> float:
        return self._ceiling

    def observe(self, phases: dict[str, float]) -> None:
        """Append this tick's per-module phases to their sliding windows.

        Modules absent from ``phases`` simply do not advance this tick. A
        module's missing phase falls back to the neutral phase.
        """
        for source, ph in phases.items():
            value = float(ph) if ph is not None and math.isfinite(ph) else NEUTRAL_PHASE
            self._buffers[source].append(value)

    def _windows_for(self, sources: Iterable[str]) -> list[list[float]]:
        windows: list[list[float]] = []
        for source in sources:
            buf = self._buffers.get(source)
            if buf:
                windows.append(list(buf))
            else:
                # No observed phase yet → neutral, single-sample window. Two
                # such modules lock perfectly (both neutral), matching the
                # "absent oscillator is neutral" requirement.
                windows.append([NEUTRAL_PHASE])
        return windows

    def plv(self, sources: Iterable[str]) -> float:
        """Mean pairwise PLV among the given source modules, in ``[0, 1]``."""
        return mean_pairwise_plv(self._windows_for(sources))

    def factor(self, sources: Iterable[str]) -> float:
        """Bounded coherence multiplier for a coalition's source modules.

        Maps mean PLV in ``[0, 1]`` linearly onto
        ``[coherence_floor, coherence_ceiling]``.
        """
        return self.factor_from_plv(self.plv(sources))

    def factor_for_source(self, source: str, cohort: Iterable[str]) -> float:
        """Coherence multiplier for one source given the candidate cohort.

        The candidate's coalition is itself plus the other modules active this
        round; its factor reflects how phase-locked it is with them. A source
        locked to the cohort is boosted toward the ceiling; a desynchronized
        source is attenuated toward the floor. A source alone in the cohort has
        no pair to lock and maps from PLV 1.0 (never penalised for solitude).
        """
        others = [s for s in cohort if s != source]
        if not others:
            return self.factor_from_plv(1.0)
        source_window = self._windows_for([source])[0]
        other_windows = self._windows_for(others)
        # Source-centric coherence: how locked this source is with the rest of
        # the cohort (mean PLV of source↔each other), so a phase-locked source
        # is boosted and a desynchronized one attenuated independently.
        total = 0.0
        for win in other_windows:
            total += phase_locking_value(source_window, win)
        return self.factor_from_plv(total / len(other_windows))

    def factor_from_plv(self, plv: float) -> float:
        """Linear map of a PLV value onto ``[floor, ceiling]``, bounded."""
        p = plv
        if p < 0.0:
            p = 0.0
        elif p > 1.0:
            p = 1.0
        return self._floor + (self._ceiling - self._floor) * p
