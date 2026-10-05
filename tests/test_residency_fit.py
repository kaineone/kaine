# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for kaine.residency.fit."""

from __future__ import annotations

import json

from kaine.residency.budget import Domain
from kaine.residency.fit import Need, fit_report


def test_co_resides():
    budget = Domain(
        name="system",
        kind="system",
        total_bytes=8 * GIB,
        available_bytes=7 * GIB,
        reserve_bytes=GIB,
        budget_bytes=6 * GIB,
        derivation="test",
    )
    needs = (
        Need(component="lingua", domain="system", footprint_bytes=3 * GIB, interactive=True, rung="lingua-rung"),
        Need(component="audition", domain="system", footprint_bytes=2 * GIB, interactive=False, rung="audition-rung"),
    )
    report = fit_report((budget,), needs)
    assert report.co_resides
    assert report.domains[0].status == "co-resides"
    assert report.domains[0].feel == "everything stays loaded; no swaps"


def test_multiplex_respects_pin():
    budget = Domain(
        name="system",
        kind="system",
        total_bytes=8 * GIB,
        available_bytes=7 * GIB,
        reserve_bytes=GIB,
        budget_bytes=6 * GIB,
        derivation="test",
    )
    needs = (
        Need(component="lingua", domain="system", footprint_bytes=3 * GIB, interactive=True, rung="lingua-rung"),
        Need(component="audition", domain="system", footprint_bytes=2 * GIB, interactive=False, rung="audition-rung"),
        Need(component="vox", domain="system", footprint_bytes=2 * GIB, interactive=True, rung="vox-rung"),
    )
    report = fit_report((budget,), needs)
    assert not report.co_resides
    assert report.domains[0].status == "multiplex"
    assert report.domains[0].pinned == "lingua"
    assert report.domains[0].shortfall_bytes == 1 * GIB
    assert "lingua stays loaded" in report.domains[0].feel


def test_multiplex_pin_not_in_domain_uses_largest_interactive():
    budget = Domain(
        name="system",
        kind="system",
        total_bytes=8 * GIB,
        available_bytes=7 * GIB,
        reserve_bytes=GIB,
        budget_bytes=6 * GIB,
        derivation="test",
    )
    needs = (
        Need(component="audition", domain="system", footprint_bytes=2 * GIB, interactive=True, rung="audition-rung"),
        Need(component="vox", domain="system", footprint_bytes=3 * GIB, interactive=True, rung="vox-rung"),
        Need(component="batch", domain="system", footprint_bytes=2 * GIB, interactive=False, rung="batch-rung"),
    )
    report = fit_report((budget,), needs, pin="lingua")
    assert report.domains[0].pinned == "vox"  # largest interactive that fits
    assert report.domains[0].status == "multiplex"
    assert "vox stays loaded" in report.domains[0].feel


def test_does_not_fit():
    budget = Domain(
        name="system",
        kind="system",
        total_bytes=4 * GIB,
        available_bytes=3 * GIB,
        reserve_bytes=GIB,
        budget_bytes=2 * GIB,
        derivation="test",
    )
    needs = (
        Need(component="lingua", domain="system", footprint_bytes=3 * GIB, interactive=True, rung="lingua-rung"),
        Need(component="audition", domain="system", footprint_bytes=3 * GIB, interactive=False, rung="audition-rung"),
    )
    report = fit_report((budget,), needs)
    assert report.domains[0].status == "does-not-fit"
    assert report.domains[0].shortfall_bytes == 4 * GIB
    assert report.domains[0].pinned is None
    assert "short by" in report.domains[0].feel


def test_uncalibrated_with_estimate():
    budget = Domain(
        name="system",
        kind="system",
        total_bytes=8 * GIB,
        available_bytes=7 * GIB,
        reserve_bytes=GIB,
        budget_bytes=6 * GIB,
        derivation="test",
    )
    needs = (
        Need(component="lingua", domain="system", footprint_bytes=3 * GIB, interactive=True, rung="lingua-rung"),
        Need(component="vox", domain="system", footprint_bytes=None, estimate_bytes=2 * GIB, interactive=False, rung="vox-rung"),
    )
    report = fit_report((budget,), needs)
    assert report.co_resides
    assert report.uncalibrated == ("vox",)


def test_uncalibrated_without_estimate_unknown_budget():
    budget = Domain(
        name="system",
        kind="system",
        total_bytes=8 * GIB,
        available_bytes=7 * GIB,
        reserve_bytes=GIB,
        budget_bytes=6 * GIB,
        derivation="test",
    )
    needs = (
        Need(component="lingua", domain="system", footprint_bytes=3 * GIB, interactive=True, rung="lingua-rung"),
        Need(component="vox", domain="system", footprint_bytes=None, estimate_bytes=None, interactive=False, rung="vox-rung"),
    )
    report = fit_report((budget,), needs)
    assert report.domains[0].status == "unknown-budget"
    assert "cannot plan" in report.domains[0].feel
    assert "vox" in report.domains[0].feel
    assert report.uncalibrated == ("vox",)


def test_lines_contains_shortfall_gib():
    budget = Domain(
        name="system",
        kind="system",
        total_bytes=8 * GIB,
        available_bytes=7 * GIB,
        reserve_bytes=GIB,
        budget_bytes=6 * GIB,
        derivation="test",
    )
    needs = (
        Need(component="lingua", domain="system", footprint_bytes=5 * GIB, interactive=True, rung="lingua-rung"),
        Need(component="audition", domain="system", footprint_bytes=3 * GIB, interactive=False, rung="audition-rung"),
    )
    report = fit_report((budget,), needs)
    lines = report.lines()
    assert any("shortfall 2.00 GiB" in line for line in lines)


def test_to_dict_json_serialisable():
    budget = Domain(
        name="system",
        kind="system",
        total_bytes=8 * GIB,
        available_bytes=7 * GIB,
        reserve_bytes=GIB,
        budget_bytes=6 * GIB,
        derivation="test",
    )
    needs = (
        Need(component="lingua", domain="system", footprint_bytes=3 * GIB, interactive=True, rung="lingua-rung"),
        Need(component="audition", domain="system", footprint_bytes=2 * GIB, interactive=False, rung="audition-rung"),
    )
    report = fit_report((budget,), needs)
    # should not raise
    json.dumps(report.to_dict())


GIB = 1 << 30


def test_each_fits_alone_but_no_pin_leaves_room():
    budget = Domain(
        name="system",
        kind="system",
        total_bytes=8 * GIB,
        available_bytes=7 * GIB,
        reserve_bytes=GIB,
        budget_bytes=6 * GIB,
        derivation="test",
    )
    needs = (
        Need(component="lingua", domain="system", footprint_bytes=5 * GIB, interactive=True, rung="l"),
        Need(component="audition", domain="system", footprint_bytes=3 * GIB, interactive=True, rung="a"),
    )
    fit = fit_report((budget,), needs).domains[0]
    assert fit.status == "multiplex"
    assert fit.pinned is None
    assert "every organ takes turns" in fit.feel


def test_does_not_fit_reports_largest_single_shortfall():
    budget = Domain(
        name="system",
        kind="system",
        total_bytes=8 * GIB,
        available_bytes=7 * GIB,
        reserve_bytes=GIB,
        budget_bytes=4 * GIB,
        derivation="test",
    )
    needs = (
        Need(component="lingua", domain="system", footprint_bytes=5 * GIB, interactive=True, rung="l"),
        Need(component="vox", domain="system", footprint_bytes=1 * GIB, interactive=True, rung="v"),
    )
    fit = fit_report((budget,), needs).domains[0]
    assert fit.status == "does-not-fit"
    assert fit.shortfall_bytes == 2 * GIB
    assert "short by 1.00 GiB" in fit.feel

