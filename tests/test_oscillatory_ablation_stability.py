# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Integration test: the oscillatory-ablation runner is stable across seeds.

Demonstrates the multi-seed stability harness on a real experiment. The ablation
runner is deterministic per seed, so across K seeds its effect metric should be
stable (CV within tolerance) and its verdict unanimous — the multi-seed analog of
the bit-for-bit determinism guarantee. Kept small (few seeds, few ticks) so the
test is fast and offline.

Spec-scenario coverage (longitudinal-stability):
* "Stable experiment across seeds -> stable report"
* "Verdict unanimity captured"
"""
from __future__ import annotations

from kaine.evaluation.benchmarks.oscillatory_ablation.stability import (
    run_ablation_stability,
)


def test_ablation_is_stable_across_seeds():
    """3 seeds, few ticks -> stable report: verdict unanimous WIN, effect CV small.

    The ablation runner is deterministic per seed AND its scripted stimulus does
    not depend on the seed, so the effect metric is in fact identical across
    seeds (CV == 0) — the strongest possible demonstration that the experiment is
    seed-robust. A small tolerance is used so the assertion would still catch any
    future seed-dependence regression.
    """
    report = run_ablation_stability([1234, 2025, 7], ticks=16, tolerance=0.01)

    assert report.seeds == (1234, 2025, 7)
    assert len(report.values) == 3
    # The runner wins on this crafted stimulus; the verdict must be unanimous WIN.
    assert report.verdict_counts == {"WIN": 3}
    assert report.verdict_unanimous is True
    # Effect is a measurable, bounded fraction on every seed.
    assert all(0.0 < v <= 1.0 for v in report.values)
    # Effect is in fact identical across seeds: CV well within tolerance.
    assert report.cv <= report.tolerance
    assert report.std == 0.0
    # Stable: CV within tolerance AND verdicts unanimous.
    assert report.stable is True
    assert any("unanimous" in r for r in report.reasons())


def test_ablation_stability_report_serializes():
    """The integration report serializes to a JSON-safe dict."""
    report = run_ablation_stability([1234, 2025], ticks=16, tolerance=0.5)
    d = report.to_dict()
    assert d["stable"] is True
    assert d["verdict_counts"] == {"WIN": 2}
    assert d["cv_is_infinite"] is False
    assert isinstance(d["reasons"], list) and d["reasons"]
