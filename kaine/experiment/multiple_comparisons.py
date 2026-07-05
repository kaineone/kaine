# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Family-wise multiple-comparisons correction for the evaluation suite.

The suite runs several hypothesis tests that each emit a p-value (the
active-inference Mann–Whitney per task, the individuation permutation test, and
any others). Reporting each at an uncorrected ``alpha`` inflates the family-wise
error rate: with a falsification posture we control the probability of *any*
false positive across the family, so we apply the **Holm–Bonferroni** step-down
procedure (FWER control). Holm is uniformly more powerful than plain Bonferroni
and makes no independence assumption, which is the safe default for a small
family of tests that are not guaranteed independent.

This helper is boundary-neutral (stdlib only) and lives in ``kaine.experiment``
so both the core and the evaluation sidecar may use it.

Procedure (Holm 1979)
---------------------
Given ``m`` raw p-values ``p_(1) <= ... <= p_(m)`` (ascending):

- The **adjusted** p-value for the rank-``k`` (1-indexed) test is
  ``p̃_(k) = max_{j<=k} min( (m - j + 1) * p_(j), 1 )`` — the cumulative-max
  enforces the monotonicity Holm requires.
- Reject H0 for a test iff its adjusted p-value ``< alpha`` (equivalent to the
  step-down rule: reject the smallest raw p-values until the first one that
  fails ``p_(k) < alpha / (m - k + 1)``, then stop).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence


@dataclass(frozen=True)
class Comparison:
    """One hypothesis test's raw and Holm-corrected decision."""

    name: str
    raw_p: float
    holm_p: float
    reject: bool  # reject H0 (i.e. the effect is significant) at the family alpha

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "raw_p": self.raw_p,
            "holm_p": self.holm_p,
            "reject": self.reject,
        }


def holm_bonferroni(
    named_pvalues: Mapping[str, float] | Sequence[tuple[str, float]],
    *,
    alpha: float = 0.05,
) -> list[Comparison]:
    """Holm–Bonferroni-correct a family of named p-values.

    Parameters
    ----------
    named_pvalues:
        Either a mapping ``{name: p}`` or a sequence of ``(name, p)`` pairs. Each
        ``p`` must be in ``[0, 1]``. An empty family returns an empty list.
    alpha:
        Family-wise significance level (must be in ``(0, 1)``).

    Returns
    -------
    list[Comparison]
        One entry per input, in the SAME order the inputs were given (not sorted
        by p-value), each carrying ``raw_p``, the monotone Holm-adjusted
        ``holm_p``, and the ``reject`` decision (``holm_p < alpha``).
    """
    if not (0.0 < alpha < 1.0):
        raise ValueError("alpha must be in (0, 1).")

    items = (
        list(named_pvalues.items())
        if isinstance(named_pvalues, Mapping)
        else [(str(n), float(p)) for n, p in named_pvalues]
    )
    for name, p in items:
        if not (0.0 <= p <= 1.0):
            raise ValueError(f"p-value for {name!r} is {p}, must be in [0, 1].")

    m = len(items)
    if m == 0:
        return []

    # Order indices by ascending p-value (stable, so ties keep input order).
    order = sorted(range(m), key=lambda i: items[i][1])

    holm_by_index: dict[int, float] = {}
    running_max = 0.0
    for rank, idx in enumerate(order):  # rank is 0-indexed here
        raw_p = items[idx][1]
        adjusted = min((m - rank) * raw_p, 1.0)
        running_max = max(running_max, adjusted)  # enforce monotonicity
        holm_by_index[idx] = running_max

    return [
        Comparison(
            name=items[i][0],
            raw_p=float(items[i][1]),
            holm_p=float(holm_by_index[i]),
            reject=bool(holm_by_index[i] < alpha),
        )
        for i in range(m)
    ]


def holm_report(
    named_pvalues: Mapping[str, float] | Sequence[tuple[str, float]],
    *,
    alpha: float = 0.05,
) -> dict[str, Any]:
    """Serializable Holm-corrected family view for a combined suite report.

    Returns ``{method, alpha, n, any_significant, comparisons: [...]}`` where
    ``comparisons`` is the per-test list from :func:`holm_bonferroni`.
    """
    comparisons = holm_bonferroni(named_pvalues, alpha=alpha)
    return {
        "method": "holm-bonferroni",
        "alpha": float(alpha),
        "n": len(comparisons),
        "any_significant": any(c.reject for c in comparisons),
        "comparisons": [c.to_dict() for c in comparisons],
    }


__all__ = ["Comparison", "holm_bonferroni", "holm_report"]
