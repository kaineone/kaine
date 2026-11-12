# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from kaine.preboot import check_residency_fit
from kaine.residency.fit import DomainFit, FitReport

GIB = 1 << 30


def test_co_resides_passes(monkeypatch):
    report = FitReport(domains=(), co_resides=True, uncalibrated=())
    monkeypatch.setattr("kaine.setup.footprint.quick_fit", lambda config: report)

    result = check_residency_fit({})[0]

    assert result.status == "PASS"
    assert "co-reside" in result.detail


def test_no_catalogue_skips(monkeypatch):
    monkeypatch.setattr("kaine.setup.footprint.quick_fit", lambda config: None)

    result = check_residency_fit({})[0]

    assert result.status == "SKIP"
    assert "calibrate" in result.detail


def test_does_not_fit_fails(monkeypatch):
    fit = DomainFit(
        domain="language",
        budget_bytes=None,
        need_bytes=2 * GIB,
        status="does-not-fit",
        shortfall_bytes=GIB,
        pinned=None,
        multiplexed=(),
        rungs={},
        feel="even one at a time this domain is short by 1.00 GiB",
    )
    report = FitReport(domains=(fit,), co_resides=False, uncalibrated=())
    monkeypatch.setattr("kaine.setup.footprint.quick_fit", lambda config: report)

    result = check_residency_fit({})[0]

    assert result.status == "FAIL"
    assert "shortfall" in result.detail


def test_multiplex_passes_with_plan(monkeypatch):
    fit = DomainFit(
        domain="language",
        budget_bytes=None,
        need_bytes=2 * GIB,
        status="multiplex",
        shortfall_bytes=0,
        pinned="language",
        multiplexed=("vocal", "audition"),
        rungs={},
        feel="",
    )
    report = FitReport(domains=(fit,), co_resides=False, uncalibrated=())
    monkeypatch.setattr("kaine.setup.footprint.quick_fit", lambda config: report)

    result = check_residency_fit({})[0]

    assert result.status == "PASS"
    assert "language pinned" in result.detail
    assert "2 multiplexed" in result.detail


def test_multiplex_no_pin(monkeypatch):
    fit = DomainFit(
        domain="language",
        budget_bytes=None,
        need_bytes=2 * GIB,
        status="multiplex",
        shortfall_bytes=0,
        pinned=None,
        multiplexed=("language", "vocal"),
        rungs={},
        feel="",
    )
    report = FitReport(domains=(fit,), co_resides=False, uncalibrated=())
    monkeypatch.setattr("kaine.setup.footprint.quick_fit", lambda config: report)

    result = check_residency_fit({})[0]

    assert result.status == "PASS"
    assert "no pin" in result.detail
