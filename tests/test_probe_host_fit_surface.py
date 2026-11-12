# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the probe-host fit report surface."""

from __future__ import annotations

import importlib
from pathlib import Path

from kaine.hardware import TierRecommendation
from kaine.residency.fit import FitReport


def _load_probe_host():
    path = Path("scripts/probe-host")
    loader = importlib.machinery.SourceFileLoader("probe_host", str(path))
    spec = importlib.util.spec_from_loader("probe_host", loader, origin=str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _make_rec(residency: bool = False) -> TierRecommendation:
    return TierRecommendation(
        tier=2,
        reason="test reason",
        total_ram_gb=16.0,
        cpu_arch="x86_64",
        accelerator="cuda",
        torch_importable=True,
        gpu_count=1,
        memory_budget_gb=10.0,
        memory_state="discrete",
        residency_required=residency,
    )


def test_fit_report_shown_when_residency_required(monkeypatch):
    mod = _load_probe_host()
    report = FitReport(domains=(), co_resides=True, uncalibrated=())
    monkeypatch.setattr("kaine.setup.footprint.quick_fit", lambda *a, **kw: report)
    rec = _make_rec(residency=True)
    text = mod._render_text(rec)
    assert "residency" in text.lower()
    assert "fit report" in text.lower()


def test_no_fit_report_when_residency_not_required():
    mod = _load_probe_host()
    rec = _make_rec(residency=False)
    text = mod._render_text(rec)
    assert "fit report" not in text.lower()


def test_fit_report_no_catalogue(monkeypatch):
    mod = _load_probe_host()
    monkeypatch.setattr("kaine.setup.footprint.quick_fit", lambda *a, **kw: None)
    rec = _make_rec(residency=True)
    text = mod._render_text(rec)
    assert "no catalogue" in text
