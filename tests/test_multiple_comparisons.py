# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Unit tests for the Holm–Bonferroni family-wise correction helper.

Known-input tests: a hand-worked family of raw p-values maps to the expected
Holm-adjusted p-values and reject/no-reject decisions under a stated alpha.
"""
from __future__ import annotations

import pytest

from kaine.experiment.multiple_comparisons import (
    holm_bonferroni,
    holm_report,
)


def test_holm_known_family_adjusted_pvalues_and_decisions():
    """Hand-worked example (m=4, alpha=0.05).

    Raw p, ascending: 0.01, 0.02, 0.04, 0.30.
    Holm multipliers (m-rank+1): 4, 3, 2, 1.
      0.01*4 = 0.04
      0.02*3 = 0.06  -> cummax = 0.06
      0.04*2 = 0.08  -> cummax = 0.08
      0.30*1 = 0.30  -> cummax = 0.30
    Reject where adjusted < 0.05: only the first (0.04).
    """
    raw = {"a": 0.01, "b": 0.02, "c": 0.04, "d": 0.30}
    out = {c.name: c for c in holm_bonferroni(raw, alpha=0.05)}

    assert out["a"].holm_p == pytest.approx(0.04)
    assert out["b"].holm_p == pytest.approx(0.06)
    assert out["c"].holm_p == pytest.approx(0.08)
    assert out["d"].holm_p == pytest.approx(0.30)

    assert out["a"].reject is True
    assert out["b"].reject is False
    assert out["c"].reject is False
    assert out["d"].reject is False


def test_holm_preserves_input_order():
    """Results come back in input order, not sorted by p-value."""
    pairs = [("z", 0.30), ("y", 0.01), ("x", 0.02)]
    names = [c.name for c in holm_bonferroni(pairs, alpha=0.05)]
    assert names == ["z", "y", "x"]


def test_holm_monotonicity_enforced():
    """Adjusted p-values are non-decreasing in raw-p rank (never invert)."""
    raw = {"p1": 0.001, "p2": 0.049, "p3": 0.05, "p4": 0.9}
    comps = sorted(holm_bonferroni(raw, alpha=0.05), key=lambda c: c.raw_p)
    holm = [c.holm_p for c in comps]
    assert holm == sorted(holm), f"Holm-adjusted p must be monotone: {holm}"


def test_holm_all_below_alpha_all_reject():
    raw = {"a": 0.001, "b": 0.002, "c": 0.003}
    # 0.003*1=0.003, 0.002*2=0.004, 0.001*3=0.003 -> all well under 0.05.
    comps = holm_bonferroni(raw, alpha=0.05)
    assert all(c.reject for c in comps)


def test_holm_bonferroni_is_more_conservative_than_uncorrected():
    """A p-value that is significant uncorrected can fail to reject under Holm."""
    # 0.03 < 0.05 uncorrected, but with 3 tests the smallest multiplier applied
    # to the two larger ones pushes them over 0.05.
    raw = {"a": 0.001, "b": 0.03, "c": 0.04}
    out = {c.name: c for c in holm_bonferroni(raw, alpha=0.05)}
    assert out["a"].reject is True
    # 0.03 * 2 = 0.06 > 0.05 -> not rejected once corrected.
    assert out["b"].reject is False
    assert out["c"].reject is False


def test_holm_empty_family_is_empty():
    assert holm_bonferroni({}) == []
    rep = holm_report({})
    assert rep["n"] == 0
    assert rep["any_significant"] is False


def test_holm_report_shape():
    rep = holm_report({"a": 0.001, "b": 0.5}, alpha=0.05)
    assert rep["method"] == "holm-bonferroni"
    assert rep["alpha"] == pytest.approx(0.05)
    assert rep["n"] == 2
    assert rep["any_significant"] is True
    assert {c["name"] for c in rep["comparisons"]} == {"a", "b"}


def test_holm_rejects_bad_alpha():
    with pytest.raises(ValueError):
        holm_bonferroni({"a": 0.1}, alpha=0.0)
    with pytest.raises(ValueError):
        holm_bonferroni({"a": 0.1}, alpha=1.0)


def test_holm_rejects_out_of_range_pvalue():
    with pytest.raises(ValueError, match="must be in"):
        holm_bonferroni({"a": 1.5})


# --------------------------------------------------------------------------
# Boundary / tie / single-item coverage
# --------------------------------------------------------------------------


def test_holm_boundary_pvalues_zero_and_one_do_not_raise():
    """Exactly 0.0 and 1.0 are valid p-values and must not raise; 0.0 rejects
    (any alpha in (0,1) exceeds it) and 1.0 never rejects."""
    out = {c.name: c for c in holm_bonferroni({"a": 0.0, "b": 1.0}, alpha=0.05)}
    assert out["a"].holm_p == pytest.approx(0.0)
    assert out["a"].reject is True
    assert out["b"].holm_p == pytest.approx(1.0)
    assert out["b"].reject is False


def test_holm_two_equal_pvalues_tie_keeps_input_order():
    """Two identical p-values are a tie; results still come back in input order
    (stable), and both get the same adjusted p-value."""
    comps = holm_bonferroni([("first", 0.03), ("second", 0.03)], alpha=0.05)
    assert [c.name for c in comps] == ["first", "second"]
    # m=2: 0.03*2=0.06 then cummax 0.06 -> both 0.06, neither rejects at 0.05.
    assert comps[0].holm_p == pytest.approx(0.06)
    assert comps[1].holm_p == pytest.approx(0.06)
    assert comps[0].reject is False and comps[1].reject is False


def test_holm_single_item_family_equals_uncorrected():
    """With m=1 the Holm multiplier is 1, so the adjusted p equals the raw p."""
    comps = holm_bonferroni({"only": 0.04}, alpha=0.05)
    assert len(comps) == 1
    assert comps[0].holm_p == pytest.approx(0.04)
    assert comps[0].reject is True
    # And a single non-significant p stays non-significant.
    comps2 = holm_bonferroni({"only": 0.20}, alpha=0.05)
    assert comps2[0].holm_p == pytest.approx(0.20)
    assert comps2[0].reject is False
