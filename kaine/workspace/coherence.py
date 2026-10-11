# SPDX-License-Identifier: LicenseRef-CAL-0.4
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

**Freshness rule.** ``CoherenceScorer.observe`` stores each phase together with a
freshness flag. A sample is fresh only when the reported phase is finite and
differs from that source's previously reported phase. Pairwise PLV is computed
only over jointly fresh observations (the common suffix of the two windows,
restricted to positions where both samples are fresh). If fewer than
``MIN_FRESH_SAMPLES`` jointly fresh observations are available, the pair
contributes the **neutral PLV** instead. The neutral PLV maps to a coherence
factor of exactly 1.0 whenever ``floor <= 1.0 <= ceiling``.

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
MIN_FRESH_SAMPLES: int = 3


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
        # restart). Keyed by module name (== event source). Each entry is a
        # deque of (phase_value, is_fresh) tuples.
        self._buffers: dict[str, deque[tuple[float, bool]]] = defaultdict(
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

        Modules absent from ``phases`` simply do not advance this tick. A missing
        or non-finite phase is stored as ``NEUTRAL_PHASE`` and marked not fresh.
        A finite phase is marked fresh only when it differs from the source's
        previous stored phase (the very first sample is therefore never fresh).
        Each stored sample is a ``(value, fresh)`` tuple.
        """
        for source, ph in phases.items():
            if ph is not None and math.isfinite(ph):
                value = float(ph)
                input_finite = True
            else:
                value = NEUTRAL_PHASE
                input_finite = False

            buf = self._buffers[source]
            fresh = False
            if buf and input_finite and value != buf[-1][0]:
                fresh = True
            buf.append((value, fresh))

    def neutral_plv(self) -> float:
        """The PLV value that maps to a coherence factor of 1.0.

        Returns ``(1.0 - floor) / (ceiling - floor)`` clipped to ``[0, 1]``.
        When ``ceiling == floor`` the division is degenerate and 1.0 is returned
        directly.
        """
        if self._ceiling == self._floor:
            return 1.0
        val = (1.0 - self._floor) / (self._ceiling - self._floor)
        if val < 0.0:
            return 0.0
        if val > 1.0:
            return 1.0
        return val

    def _pair_plv(self, a: str, b: str) -> float | None:
        """PLV between two sources over their jointly fresh observations.

        The two buffers are aligned on their common suffix (the last ``n``
        samples, where ``n`` is the minimum buffer length). Only positions where
        both samples are fresh are kept. If fewer than ``MIN_FRESH_SAMPLES``
        remain, ``None`` is returned (the caller should substitute
        ``neutral_plv()``). If one or both sources have no observations,
        ``None`` is returned.
        """
        buf_a = self._buffers.get(a)
        buf_b = self._buffers.get(b)
        if not buf_a or not buf_b:
            return None

        n = min(len(buf_a), len(buf_b))
        if n == 0:
            return None

        samples_a = list(buf_a)[-n:]
        samples_b = list(buf_b)[-n:]

        fresh_a: list[float] = []
        fresh_b: list[float] = []
        for (va, fa), (vb, fb) in zip(samples_a, samples_b):
            if fa and fb:
                fresh_a.append(va)
                fresh_b.append(vb)

        if len(fresh_a) < MIN_FRESH_SAMPLES:
            return None
        return phase_locking_value(fresh_a, fresh_b)

    def plv(self, sources: Iterable[str]) -> float:
        """Mean pairwise PLV among the given source modules, in ``[0, 1]``.

        For each unordered pair the per-pair PLV is computed over jointly fresh
        observations; if fewer than ``MIN_FRESH_SAMPLES`` jointly fresh
        observations are available, the pair contributes ``neutral_plv()``.
        With fewer than two sources ``neutral_plv()`` is returned.
        """
        sources = list(sources)
        m = len(sources)
        if m < 2:
            return self.neutral_plv()

        total = 0.0
        pairs = 0
        for i in range(m):
            for j in range(i + 1, m):
                p = self._pair_plv(sources[i], sources[j])
                if p is None:
                    p = self.neutral_plv()
                total += p
                pairs += 1

        if pairs == 0:
            return self.neutral_plv()
        return total / pairs

    def factor(self, sources: Iterable[str]) -> float:
        """Bounded coherence multiplier for a coalition's source modules.

        Maps mean PLV in ``[0, 1]`` linearly onto
        ``[coherence_floor, coherence_ceiling]``.
        """
        return self.factor_from_plv(self.plv(sources))

    def factor_for_source(self, source: str, cohort: Iterable[str]) -> float:
        """Coherence multiplier for one source given the candidate cohort.

        For each other source in the cohort, the pairwise PLV is computed over
        jointly fresh observations; if there are not enough jointly fresh
        observations, ``neutral_plv()`` is used for that pair. The mean of
        those per-pair PLVs is then mapped onto
        ``[coherence_floor, coherence_ceiling]``. A source alone in its cohort
        returns the neutral factor, which is ``1.0`` whenever
        ``floor <= 1 <= ceiling``.
        """
        others = [s for s in cohort if s != source]
        if not others:
            return self.factor_from_plv(self.neutral_plv())

        values: list[float] = []
        for other in others:
            p = self._pair_plv(source, other)
            if p is None:
                p = self.neutral_plv()
            values.append(p)

        return self.factor_from_plv(sum(values) / len(values))

    def factor_from_plv(self, plv: float) -> float:
        """Linear map of a PLV value onto ``[floor, ceiling]``, bounded."""
        p = plv
        if p < 0.0:
            p = 0.0
        elif p > 1.0:
            p = 1.0
        return self._floor + (self._ceiling - self._floor) * p
