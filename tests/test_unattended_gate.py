# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the unattended boot gate and supervision-mode resolution."""
from __future__ import annotations

import pytest

from kaine.cycle.research_gate import evaluate_research_gate
from kaine.cycle.unattended_gate import (
    CONDITION_NAMES,
    NOT_BUILT_REASON,
    Condition,
    SupervisionConfigError,
    evaluate_unattended_gate,
    resolve_supervision_mode,
)


def _all_pass_net() -> object:
    return evaluate_research_gate(
        preservation_enabled=True,
        welfare_response_wired=True,
        logging_active=True,
        self_check_passed=True,
        encryption_satisfied=True,
    )


def test_resolve_unattended_from_env():
    assert resolve_supervision_mode({}, env={"KAINE_CYCLE_UNATTENDED": "1"}) == "unattended"


def test_resolve_unattended_from_config():
    assert (
        resolve_supervision_mode(
            {"cycle": {"supervision_mode": "unattended"}}, env={}
        )
        == "unattended"
    )


def test_resolve_env_over_config():
    assert (
        resolve_supervision_mode(
            {"cycle": {"supervision_mode": "operator"}},
            env={"KAINE_CYCLE_UNATTENDED": "1"},
        )
        == "unattended"
    )


def test_resolve_invalid_supervision_mode_string():
    with pytest.raises(SupervisionConfigError) as exc_info:
        resolve_supervision_mode(
            {"cycle": {"supervision_mode": "maybe"}}, env={}
        )
    assert "operator" in str(exc_info.value)
    assert "unattended" in str(exc_info.value)


def test_resolve_invalid_supervision_mode_not_str():
    with pytest.raises(SupervisionConfigError) as exc_info:
        resolve_supervision_mode(
            {"cycle": {"supervision_mode": 3}}, env={}
        )
    assert "operator" in str(exc_info.value)
    assert "unattended" in str(exc_info.value)
    assert "3" not in str(exc_info.value)


def test_resolve_unattended_conflicts_with_research():
    with pytest.raises(SupervisionConfigError) as exc_info:
        resolve_supervision_mode(
            {"research": {"enabled": True}},
            env={"KAINE_CYCLE_UNATTENDED": "1"},
        )
    text = str(exc_info.value)
    assert "KAINE_CYCLE_UNATTENDED" in text
    assert "KAINE_RESEARCH_MODE" in text


def test_resolve_unattended_conflicts_with_operator():
    with pytest.raises(SupervisionConfigError) as exc_info:
        resolve_supervision_mode(
            {}, env={"KAINE_CYCLE_UNATTENDED": "1", "KAINE_CYCLE_OPERATOR_PRESENT": "1"}
        )
    text = str(exc_info.value)
    assert "KAINE_CYCLE_UNATTENDED" in text
    assert "KAINE_CYCLE_OPERATOR_PRESENT" in text


def test_resolve_research_with_operator_no_conflict():
    assert (
        resolve_supervision_mode(
            {}, env={"KAINE_RESEARCH_MODE": "1", "KAINE_CYCLE_OPERATOR_PRESENT": "1"}
        )
        == "research"
    )


def test_resolve_default_is_operator():
    assert resolve_supervision_mode({}, env={}) == "operator"


def test_resolve_unattended_env_zero_is_not_unattended():
    assert resolve_supervision_mode({}, env={"KAINE_CYCLE_UNATTENDED": "0"}) == "operator"


def test_unattended_gate_without_built_fails_6_7_8():
    result = evaluate_unattended_gate(_all_pass_net())
    assert not result.ok
    assert [c.number for c in result.failed] == [6, 7, 8]
    for c in result.failed:
        assert c.reason == NOT_BUILT_REASON


def test_unattended_gate_with_logging_failure():
    net = evaluate_research_gate(
        preservation_enabled=True,
        welfare_response_wired=True,
        logging_active=False,
        self_check_passed=True,
        encryption_satisfied=True,
    )
    result = evaluate_unattended_gate(net)
    assert not result.ok
    assert [c.number for c in result.failed] == [3, 6, 7, 8]
    assert result.conditions[2].reason == "neither [evaluation] nor [research_event_log] is enabled"


def test_unattended_gate_with_built_6_7_8_passes():
    built = {
        6: Condition(6, CONDITION_NAMES[6], True),
        7: Condition(7, CONDITION_NAMES[7], True),
        8: Condition(8, CONDITION_NAMES[8], True),
    }
    result = evaluate_unattended_gate(_all_pass_net(), built=built)
    assert result.ok
    assert result.message() == "Unattended gate VERIFIED: all eight conditions passed."


def test_unattended_gate_built_rejects_bad_key():
    with pytest.raises(ValueError):
        evaluate_unattended_gate(
            _all_pass_net(),
            built={5: Condition(5, CONDITION_NAMES[5], True)},
        )


def test_unattended_gate_built_rejects_mismatched_number():
    with pytest.raises(ValueError):
        evaluate_unattended_gate(
            _all_pass_net(),
            built={6: Condition(7, CONDITION_NAMES[7], True)},
        )


def test_unattended_gate_message_contains_failure_and_no_override():
    result = evaluate_unattended_gate(_all_pass_net())
    msg = result.message()
    assert "  6: Spot armed and self-tested — " in msg
    assert "An unattended boot has no override." in msg


def test_unattended_gate_checks_keys_in_order():
    result = evaluate_unattended_gate(_all_pass_net())
    expected = [
        "1_preservation_enabled",
        "2_welfare_response_wired",
        "3_logging_active",
        "4_preserve_revive_round_trip",
        "5_encryption_satisfied",
        "6_Spot_armed_and_self_tested",
        "7_caretaker_told",
        "8_continuous_input",
    ]
    assert list(result.checks.keys()) == expected


def test_evaluate_unattended_gate_includes_spot_condition(monkeypatch):
    from kaine.cycle import __main__ as cycle_main
    from kaine.cycle.research_gate import GateResult
    from kaine.cycle.unattended_gate import Condition

    def fake_research_net(config):
        return GateResult(
            ok=True,
            checks={
                "preservation_enabled": True,
                "welfare_response_wired": True,
                "logging_active": True,
                "dry_self_check_passed": True,
                "encryption_satisfied": True,
            }
        )

    monkeypatch.setattr(
        cycle_main, "_evaluate_research_safety_net", fake_research_net
    )

    passing = Condition(6, "Spot armed and self-tested", True, "")
    failing = Condition(
        6, "Spot armed and self-tested", False, "not enabled"
    )

    monkeypatch.setattr(
        "kaine.cycle.spot_selftest.check_spot_condition",
        lambda section, timeout_s=None: passing,
    )
    result = cycle_main._evaluate_unattended_gate({})
    assert not result.ok
    assert tuple(c.number for c in result.failed) == (7, 8)

    monkeypatch.setattr(
        "kaine.cycle.spot_selftest.check_spot_condition",
        lambda section, timeout_s=None: failing,
    )
    result = cycle_main._evaluate_unattended_gate({})
    assert not result.ok
    assert tuple(c.number for c in result.failed) == (6, 7, 8)
