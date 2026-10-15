# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Developmental-phase stimulus-source pinning + honest lock attribution (`developmental-maturation-gate`).

Exercises the `perception_state` touch point: a developmental-phase gate lock is logged as
a developmental-gate action, not an operator lock. No entity is booted.
"""
from __future__ import annotations

from pathlib import Path

from kaine import perception_state as ps


def _d(tmp_path: Path) -> Path:
    return tmp_path / "desired.json"


# --- locked_by attribution (W2.1b) ------------------------------------------


def test_desired_state_defaults_to_operator_attribution() -> None:
    assert ps.DesiredState().locked_by == "operator"


def test_write_desired_locus_records_development_lock(tmp_path: Path) -> None:
    p = _d(tmp_path)
    d = ps.write_desired_locus("virtual", locked=True, path=p, locked_by="development")
    assert d.locus == "virtual" and d.locus_locked is True and d.locked_by == "development"
    # Persisted and re-read.
    assert ps.read_desired(p).locked_by == "development"


def test_unknown_locked_by_coerces_to_operator(tmp_path: Path) -> None:
    d = ps.write_desired_locus("virtual", locked=True, path=_d(tmp_path), locked_by="hacker")
    assert d.locked_by == "operator"


def test_write_desired_locus_preserves_attribution_when_omitted(tmp_path: Path) -> None:
    p = _d(tmp_path)
    ps.write_desired_locus("virtual", locked=True, path=p, locked_by="development")
    # A later write that does not pass locked_by keeps the existing attribution.
    d = ps.write_desired_locus("virtual", path=p)
    assert d.locked_by == "development"


# --- honest denial reason (W2.2, spec: self-switch refused during the developmental phase) --


def _switch(locked_by: str):
    return ps.evaluate_locus_switch(
        "physical",
        current="virtual",
        locked=True,
        allow_self_switch=True,
        inhibited=False,
        since_last_switch_s=999.0,
        min_dwell_s=1.0,
        locked_by=locked_by,
    )


def test_development_lock_denial_is_attributed_to_the_gate() -> None:
    allowed, reason = _switch("development")
    assert allowed is False
    assert "development" in reason and "operator" not in reason


def test_operator_lock_denial_unchanged() -> None:
    allowed, reason = _switch("operator")
    assert allowed is False
    assert reason == "locus locked by operator"


def test_self_switch_refused_while_developing() -> None:
    # The load-bearing behaviour: while the stimulus source lock is held the entity cannot
    # leave the stimulus source, regardless of dwell/policy.
    allowed, _ = _switch("development")
    assert allowed is False
