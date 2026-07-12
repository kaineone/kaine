# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Pure measure functions for the workspace-mediation ablation.

These are deterministic, dependency-free numeric helpers so the ablation's
statistics are unit-testable in isolation from the cycle. Two families:

* **Cross-module error coupling** (primary measure 1): the Pearson correlation
  between two modules' precision-weighted error time series, over the whole run
  and over a sliding window. The thesis predicts this correlation is HIGHER
  under workspace-on (modules coupled through the shared broadcast) than under
  workspace-off (modules free-running against independent signal streams).

* **Coalition-selection structure** (primary measure 2): the Shannon entropy of
  the selected-coalition source distribution. A non-trivial workspace selects
  different sources as state changes, so the entropy sits strictly between the
  degenerate (always one source) and uniform extremes.

Correlation returns ``None`` where it is undefined (fewer than two paired
points, or a constant series with zero variance) so a caller never mistakes an
undefined correlation for 0.0. Callers treat ``None`` windows as absent, not as
zero coupling.
"""
from __future__ import annotations

import math
from collections import Counter
from typing import Optional, Sequence


def sign_test_pvalue(deltas: Sequence[Optional[float]]) -> float:
    """One-sided sign-test p-value that the median coupling delta is > 0.

    The primary criterion is a *significant increase* in cross-module coupling
    under workspace-on. Across seeds each run yields one ``coupling_delta``; this
    tests H0 (median delta <= 0) against H1 (median delta > 0) with the
    distribution-free sign test — no scipy, deterministic, and robust to the
    non-normal, sometimes-undefined per-seed deltas.

    ``None`` deltas (undefined coupling) and exact zeros (ties) are excluded, per
    the sign test. Returns 1.0 when no non-zero delta remains (nothing to test).
    The p-value is the upper binomial tail: P(X >= positives) for
    X ~ Binomial(n_nonzero, 0.5).
    """
    vals = [d for d in deltas if d is not None and d != 0.0]
    n = len(vals)
    if n == 0:
        return 1.0
    positives = sum(1 for d in vals if d > 0.0)
    tail = sum(math.comb(n, k) for k in range(positives, n + 1))
    return tail / (2.0**n)


def pearson(xs: Sequence[float], ys: Sequence[float]) -> Optional[float]:
    """Pearson correlation of two equal-length series, or ``None`` if undefined.

    Undefined (returns ``None``) when there are fewer than two paired points or
    when either series has zero variance (a constant series has no correlation,
    which is distinct from a correlation of zero).
    """
    n = min(len(xs), len(ys))
    if n < 2:
        return None
    mx = sum(xs[:n]) / n
    my = sum(ys[:n]) / n
    sxx = sum((x - mx) ** 2 for x in xs[:n])
    syy = sum((y - my) ** 2 for y in ys[:n])
    if sxx <= 0.0 or syy <= 0.0:
        return None
    sxy = sum((xs[i] - mx) * (ys[i] - my) for i in range(n))
    denom = math.sqrt(sxx * syy)
    r = sxy / denom
    # Clamp tiny floating-point overshoot into the valid [-1, 1] range.
    return max(-1.0, min(1.0, r))


def windowed_correlations(
    xs: Sequence[float], ys: Sequence[float], *, window: int
) -> list[float]:
    """Pearson correlation over each full sliding window of size ``window``.

    Returns one correlation per window position (windows that are undefined —
    too short or zero-variance — are skipped, not emitted as 0.0). An empty list
    means no window yielded a defined correlation.
    """
    if window < 2:
        raise ValueError(f"window must be >= 2, got {window}")
    n = min(len(xs), len(ys))
    out: list[float] = []
    for start in range(0, n - window + 1):
        r = pearson(xs[start : start + window], ys[start : start + window])
        if r is not None:
            out.append(r)
    return out


def mean_windowed_correlation(
    xs: Sequence[float], ys: Sequence[float], *, window: int
) -> Optional[float]:
    """Mean of the defined sliding-window correlations, or ``None`` if none.

    The primary coupling statistic: run this for each arm and compare. A higher
    mean under workspace-on than workspace-off is the pre-registered directional
    signature of cross-module coupling via the shared broadcast.
    """
    cors = windowed_correlations(xs, ys, window=window)
    if not cors:
        return None
    return sum(cors) / len(cors)


def shannon_entropy(sources: Sequence[str], *, base: float = 2.0) -> float:
    """Shannon entropy of a categorical sequence (0.0 for empty or single-value).

    Measured on the selected-coalition source labels. 0.0 means degenerate
    (always the same source, or nothing selected); the maximum ``log_base(k)``
    means uniform across ``k`` distinct sources. A healthy competitive workspace
    sits strictly between the two.
    """
    if not sources:
        return 0.0
    counts = Counter(sources)
    total = len(sources)
    ent = 0.0
    for c in counts.values():
        p = c / total
        ent -= p * math.log(p, base)
    return ent


def entropy_fraction(sources: Sequence[str], *, base: float = 2.0) -> Optional[float]:
    """Entropy normalized to [0, 1] against the uniform maximum, or ``None``.

    Returns ``None`` when fewer than two distinct sources appear (the maximum
    entropy is 0, so a normalized fraction is undefined). Otherwise returns the
    observed entropy divided by ``log_base(k)`` for ``k`` distinct sources — a
    scale-free "how far between degenerate and uniform" score.
    """
    if not sources:
        return None
    k = len(set(sources))
    if k < 2:
        return None
    return shannon_entropy(sources, base=base) / math.log(k, base)
