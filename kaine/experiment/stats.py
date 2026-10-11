# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Small shared summary-statistic helpers.

These definitions are the canonical replacements for the former local copies in
``kaine.experiment.stability`` (``_mean`` and ``_std``),
``kaine.research.ignition_study.analysis`` (``_percentile`` and ``_mean``), and
``kaine.evaluation.observers.prediction_error_observer`` (``_percentile``).
They match those copies, except that the ignition analysis mean used
``statistics.mean``, which can differ from ``sum / len`` in the last bit.
"""
from __future__ import annotations

import math
from collections.abc import Sequence


def mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def std(values: Sequence[float]) -> float:
    """Population standard deviation (the canonical definition used here)."""
    if len(values) < 2:
        return 0.0
    m = mean(values)
    variance = sum((v - m) ** 2 for v in values) / len(values)
    return math.sqrt(variance)


def percentile(values: Sequence[float], pct: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * pct / 100.0
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return float(s[int(k)])
    d = k - f
    return float(s[f] * (1.0 - d) + s[c] * d)
