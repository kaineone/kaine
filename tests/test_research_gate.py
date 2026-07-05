# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""PR-2: research boot gate — safety-net-present replaces operator-present
(entity-preservation-on-divergence §5.1).

Covers:
* research_mode_requested — env flag and [research].enabled.
* evaluate_research_gate — refuse when ANY of the four conditions is missing;
  allow when all hold; the refusal message names the missing condition.
* run_preflight_self_check — real dry preserve→revive round-trip passes on this
  install; a broken preservation path makes it fail (so the gate refuses).
* The shipped config ships the safety net + research mode disabled.
"""
from __future__ import annotations

import pytest

from kaine.cycle.research_gate import (
    RESEARCH_GATE_EXIT_CODE,
    evaluate_research_gate,
    research_mode_requested,
    run_preflight_self_check,
)


# ---------------------------------------------------------------------------
# research_mode_requested
# ---------------------------------------------------------------------------


def test_research_mode_from_env():
    assert research_mode_requested({}, env={"KAINE_RESEARCH_MODE": "1"}) is True
    assert research_mode_requested({}, env={"KAINE_RESEARCH_MODE": "0"}) is False
    assert research_mode_requested({}, env={}) is False


def test_research_mode_from_config():
    assert research_mode_requested({"research": {"enabled": True}}, env={}) is True
    assert research_mode_requested({"research": {"enabled": False}}, env={}) is False


# ---------------------------------------------------------------------------
# evaluate_research_gate
# ---------------------------------------------------------------------------


def _all_ok(**overrides):
    base = dict(
        preservation_enabled=True,
        welfare_response_wired=True,
        logging_active=True,
        self_check_passed=True,
        encryption_satisfied=True,
    )
    base.update(overrides)
    return base


def test_gate_allows_when_all_conditions_hold():
    r = evaluate_research_gate(**_all_ok())
    assert r.ok is True
    assert r.failures == []
    assert "VERIFIED" in r.message()


@pytest.mark.parametrize(
    "missing,needle",
    [
        ("preservation_enabled", "preservation is not enabled"),
        ("welfare_response_wired", "welfare-protective response is not wired"),
        ("logging_active", "logging / admissibility is not active"),
        ("self_check_passed", "self-check did not pass"),
        ("encryption_satisfied", "encryption is required but not active"),
    ],
)
def test_gate_refuses_when_any_condition_missing(missing, needle):
    r = evaluate_research_gate(**_all_ok(**{missing: False}))
    assert r.ok is False
    assert any(needle in f for f in r.failures), r.failures
    msg = r.message()
    assert "Refusing to boot" in msg
    assert needle in msg


def test_gate_exit_code_is_distinct():
    # 2 = operator-present; 3 = eval; 4 = gpu; 5 = research safety net.
    assert RESEARCH_GATE_EXIT_CODE == 5


# ---------------------------------------------------------------------------
# run_preflight_self_check (real dry round-trip)
# ---------------------------------------------------------------------------


def test_self_check_passes_on_this_install():
    ok, reason = run_preflight_self_check()
    assert ok is True, f"dry preserve→revive self-check failed: {reason}"
    assert reason is None


def test_self_check_fails_when_preservation_broken(monkeypatch):
    """If preserve_live cannot capture the individual on this install, the dry
    self-check fails (so the gate refuses) rather than passing falsely."""
    import kaine.lifecycle.preservation as preservation

    async def _boom(*a, **k):
        raise preservation.PreservationError("simulated broken install")

    monkeypatch.setattr(preservation, "preserve_live", _boom)
    ok, reason = run_preflight_self_check()
    assert ok is False
    assert reason and "broken install" in reason


# ---------------------------------------------------------------------------
# Shipped config guard
# ---------------------------------------------------------------------------


def test_shipped_config_ships_safety_net_and_research_disabled():
    import tomllib
    from pathlib import Path

    root = Path(__file__).parent.parent
    config = tomllib.loads((root / "config" / "kaine.toml").read_text())
    pres = config.get("preservation", {})
    assert pres.get("divergence_monitor", {}).get("enabled", False) is False
    assert pres.get("welfare_response", {}).get("enabled", False) is False
    assert pres.get("retention", {}).get("auto_evict", False) is False
    assert config.get("research", {}).get("enabled", False) is False
