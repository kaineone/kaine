# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Pure measure functions for the workspace-mediation development harness.

For each context-conditioned processor j, IG_j is the mean per-report
``context_gain`` over reports whose gain is a finite float and whose tick index
is at or above the warmup period. The headline IG is the mean of IG_j across
processors; it is undefined when any processor's IG_j is undefined, so a
frequently reporting processor cannot outweigh a processor that reports rarely.

The contrast dIG = IG(workspace_on) - IG(pooled) is the effect the verdict turns
on; it is undefined when either arm's IG is undefined.
"""
from __future__ import annotations

import math
from typing import Mapping, Optional, Sequence


def sign_test_pvalue(values: Sequence[Optional[float]]) -> float:
    """One-sided exact sign test that the values are reliably positive.

    Used for the WIN test on dIG - min_effect and for the NEGATIVE test on
    -min_effect - dIG (paper Appendix A.8). None values and exact zeros are
    dropped. The p-value is the upper binomial tail P(X >= positives) for
    X ~ Binomial(n_nonzero, 0.5). Returns 1.0 when no non-zero value remains.
    """
    vals = [v for v in values if v is not None and v != 0.0]
    n = len(vals)
    if n == 0:
        return 1.0
    positives = sum(1 for v in vals if v > 0.0)
    tail = sum(math.comb(n, k) for k in range(positives, n + 1))
    return tail / (2.0**n)


def mean_gain(gains: Sequence[Optional[float]], *, skip: int = 0) -> Optional[float]:
    """Mean of the finite, non-None gains in ``gains[skip:]``.

    ``skip`` is the initial learning period (warmup ticks) excluded from the
    information gain. Raises ValueError when ``skip < 0``.
    """
    if skip < 0:
        raise ValueError(f"skip must be >= 0, got {skip}")
    qualified = [g for g in gains[skip:] if g is not None and math.isfinite(g)]
    if not qualified:
        return None
    return sum(qualified) / len(qualified)


def headline_gain(per_processor: Mapping[str, Optional[float]]) -> Optional[float]:
    """Mean IG_j across processors; undefined if any processor is undefined.

    Returns None when the mapping is empty or when any processor's IG_j is None.
    This keeps a frequently reporting processor from outweighing a processor
    that reports rarely.
    """
    if not per_processor:
        return None
    if any(v is None for v in per_processor.values()):
        return None
    values = [float(v) for v in per_processor.values()]
    return sum(values) / len(values)
