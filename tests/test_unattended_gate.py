# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the unattended boot gate and supervision-mode resolution."""
from __future__ import annotations

from typing import Any

import pytest

from kaine.cycle.research_gate import GateResult, evaluate_research_gate, evaluate_safety_net
from kaine.cycle.unattended_gate import (
    BUILT_CONDITIONS,
    CONDITION_NAMES,
    NOT_BUILT_REASON,
    SAFETY_NET_CONDITIONS,
    Condition,
    SupervisionConfigError,
    conditions_from_safety_net,
    evaluate_unattended_gate,
    resolve_supervision_mode,
)


def _all_pass_net() -> object:
    return evaluate_research_gate(
        individuation_enabled=True,
        preservation_enabled=True,
        welfare_response_wired=True,
        logging_active=True,
        self_check_passed=True,
        encryption_satisfied=True,
        supervisor_armed=True,
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


def test_unattended_gate_without_built_fails_7_8():
    result = evaluate_unattended_gate(_all_pass_net())
    assert not result.ok
    assert [c.number for c in result.failed] == [7, 8]
    for c in result.failed:
        assert c.reason == NOT_BUILT_REASON


def test_unattended_gate_with_logging_failure():
    net = evaluate_research_gate(
        individuation_enabled=True,
        preservation_enabled=True,
        welfare_response_wired=True,
        logging_active=False,
        self_check_passed=True,
        encryption_satisfied=True,
        supervisor_armed=True,
    )
    result = evaluate_unattended_gate(net)
    assert not result.ok
    assert [c.number for c in result.failed] == [3, 7, 8]
    # The reason comes from the research net's own reasons.
    assert "neither [evaluation] nor [research_event_log] is enabled" in result.conditions[2].reason


def test_unattended_gate_with_built_7_8_passes():
    built = {
        7: Condition(7, CONDITION_NAMES[7], True),
        8: Condition(8, CONDITION_NAMES[8], True),
    }
    result = evaluate_unattended_gate(_all_pass_net(), built=built)
    assert result.ok
    assert result.message() == "Unattended gate VERIFIED: all nine conditions passed."


@pytest.mark.parametrize("number", [5, 6])
def test_unattended_gate_built_rejects_bad_key(number):
    # Condition 6 comes from the research net (its self-test runs once there),
    # so it may not be supplied from outside.
    with pytest.raises(ValueError):
        evaluate_unattended_gate(
            _all_pass_net(),
            built={number: Condition(number, CONDITION_NAMES[number], True)},
        )


def test_unattended_gate_built_rejects_mismatched_number():
    with pytest.raises(ValueError):
        evaluate_unattended_gate(
            _all_pass_net(),
            built={8: Condition(7, CONDITION_NAMES[7], True)},
        )


def test_unattended_gate_message_contains_failure_and_no_override():
    result = evaluate_unattended_gate(_all_pass_net())
    msg = result.message()
    assert "  7: caretaker told — " in msg
    assert "An unattended boot has no override." in msg


def test_unattended_gate_checks_keys_in_order():
    result = evaluate_unattended_gate(_all_pass_net())
    expected = [
        "1_preservation_enabled",
        "2_welfare_response_wired",
        "3_logging_active",
        "4_preserve_revive_round_trip",
        "5_encryption_satisfied",
        "6_Supervisor_armed_and_self_tested",
        "7_caretaker_told",
        "8_continuous_input",
        "9_individuation_wired",
    ]
    assert list(result.checks.keys()) == expected


def _supervisor_config(tmp_path) -> dict[str, Any]:
    return {
        "supervisor": {
            "enabled": True,
            "incident_log": {"path": str(tmp_path / "incidents")},
        }
    }


def _stub_conditions_7_and_8(monkeypatch) -> None:
    monkeypatch.setattr(
        "kaine.cycle.input_check.check_input_condition",
        lambda cfg: Condition(8, CONDITION_NAMES[8], True, ""),
    )
    monkeypatch.setattr(
        "kaine.cycle.caretaker.check_caretaker_condition",
        lambda cfg, prerequisites_ok, conditions: Condition(7, CONDITION_NAMES[7], True, ""),
    )
    monkeypatch.setattr(
        "kaine.cycle.research_gate.run_preflight_self_check", lambda **_kw: (True, None)
    )


def test_unattended_gate_runs_the_supervisor_selftest_once(monkeypatch, tmp_path):
    """Condition 6 is the research net's supervisor check: one real self-test."""
    from kaine.cycle import __main__ as cycle_main
    from kaine.cycle import supervisor_selftest

    real = supervisor_selftest.run_supervisor_selftest
    calls: list[dict[str, Any]] = []

    async def counting(section, *, timeout_s=10.0):
        calls.append(section)
        return await real(section, timeout_s=timeout_s)

    monkeypatch.setattr(supervisor_selftest, "run_supervisor_selftest", counting)
    _stub_conditions_7_and_8(monkeypatch)

    config = _supervisor_config(tmp_path)
    config.update(
        {
            "preservation": {
                "divergence_monitor": {"enabled": True},
                "welfare_response": {"enabled": True},
                "require_encryption": False,
            },
            "evaluation": {"enabled": True},
            "individuation": {"enabled": True},
            "modules": {"language": True},
        }
    )
    result = cycle_main._evaluate_unattended_gate(config)
    assert len(calls) == 1
    six = next(c for c in result.conditions if c.number == 6)
    assert six.ok, six.reason


def test_unattended_condition_6_carries_the_selftest_reason(monkeypatch, tmp_path):
    from kaine.cycle import __main__ as cycle_main
    from kaine.cycle import supervisor_selftest

    calls: list[dict[str, Any]] = []

    async def failing(section, *, timeout_s=10.0):
        calls.append(section)
        return supervisor_selftest.SelftestResult(
            False, "freeze did not take effect before restart"
        )

    monkeypatch.setattr(supervisor_selftest, "run_supervisor_selftest", failing)
    _stub_conditions_7_and_8(monkeypatch)

    result = cycle_main._evaluate_unattended_gate(_supervisor_config(tmp_path))
    assert len(calls) == 1
    six = next(c for c in result.conditions if c.number == 6)
    assert not six.ok
    # The self-test's own reason, not the fixed table's.
    assert six.reason == "selftest failed: freeze did not take effect before restart"
    assert "  6: Supervisor armed and self-tested — selftest failed:" in result.message()


def test_unattended_condition_6_not_enabled(monkeypatch):
    from kaine.cycle import __main__ as cycle_main

    _stub_conditions_7_and_8(monkeypatch)
    result = cycle_main._evaluate_unattended_gate({"supervisor": {"enabled": False}})
    six = next(c for c in result.conditions if c.number == 6)
    assert not six.ok
    assert six.reason == "not enabled"


def test_evaluate_unattended_gate_uses_input_condition(monkeypatch):
    from kaine.cycle import __main__ as main_module
    from kaine.cycle.unattended_gate import Condition

    net = type(
        "GateResult",
        (),
        {
            "checks": {
                "preservation_enabled": True,
                "welfare_response_wired": True,
                "logging_active": True,
                "dry_self_check_passed": True,
                "encryption_satisfied": True,
                "individuation_enabled": True,
                "supervisor_armed": True,
            }
        },
    )()

    eight_ok = Condition(number=8, name="continuous input", ok=True, reason="")
    seven = Condition(number=7, name="caretaker told", ok=True, reason="")

    monkeypatch.setattr(main_module, "_evaluate_research_safety_net", lambda cfg: net)
    monkeypatch.setattr(
        "kaine.cycle.input_check.check_input_condition", lambda cfg: eight_ok
    )
    monkeypatch.setattr(
        "kaine.cycle.caretaker.check_caretaker_condition",
        lambda cfg, prerequisites_ok, conditions: seven,
    )

    result = main_module._evaluate_unattended_gate({})
    assert result.ok

    # Now fail condition 8 and verify condition 7 reports prerequisites failed.
    caretaker_calls: list[bool] = []
    eight_fail = Condition(
        number=8, name="continuous input", ok=False, reason="no camera"
    )

    def fake_caretaker(cfg: Any, prerequisites_ok: bool, conditions: dict[str, bool]) -> Condition:
        caretaker_calls.append(prerequisites_ok)
        return Condition(
            number=7,
            name="caretaker told",
            ok=False,
            reason="prerequisites not attempted",
        )

    monkeypatch.setattr(
        "kaine.cycle.caretaker.check_caretaker_condition", fake_caretaker
    )
    monkeypatch.setattr(
        "kaine.cycle.input_check.check_input_condition", lambda cfg: eight_fail
    )

    result2 = main_module._evaluate_unattended_gate({})
    assert not result2.ok
    c7 = next(c for c in result2.conditions if c.number == 7)
    assert "not attempted" in c7.reason
    assert False in caretaker_calls


def test_unattended_gate_individuation_failure_is_condition_9():
    net = evaluate_research_gate(
        individuation_enabled=False,
        preservation_enabled=True,
        welfare_response_wired=True,
        logging_active=True,
        self_check_passed=True,
        encryption_satisfied=True,
        supervisor_armed=True,
    )
    built = {
        7: Condition(7, CONDITION_NAMES[7], True),
        8: Condition(8, CONDITION_NAMES[8], True),
    }
    result = evaluate_unattended_gate(net, built=built)
    assert not result.ok
    assert [c.number for c in result.failed] == [9]
    failed = next(c for c in result.conditions if c.number == 9)
    assert failed.name == "individuation wired"
    assert "[individuation].enabled" in failed.reason
    assert "  9: individuation wired — " in result.message()


def test_unattended_gate_conditions_ordered_by_number():
    result = evaluate_unattended_gate(_all_pass_net())
    assert [c.number for c in result.conditions] == list(range(1, 10))


def test_every_safety_net_check_maps_to_an_unattended_condition(monkeypatch):
    """A check added to the research net must become an unattended condition."""
    monkeypatch.setattr(
        "kaine.cycle.research_gate.run_preflight_self_check", lambda **_kw: (True, "")
    )
    net = evaluate_safety_net({})
    assert set(net.checks) == set(SAFETY_NET_CONDITIONS)

    numbers = set(SAFETY_NET_CONDITIONS.values())
    assert numbers.issubset(set(CONDITION_NAMES))
    assert numbers.isdisjoint(set(BUILT_CONDITIONS))
    assert numbers | set(BUILT_CONDITIONS) == set(CONDITION_NAMES)
    assert SAFETY_NET_CONDITIONS["supervisor_armed"] == 6

    # A mapped number without a failure reason raises KeyError here, so a gap fails CI.
    net = GateResult(ok=False, checks={key: False for key in SAFETY_NET_CONDITIONS})
    conditions = conditions_from_safety_net(net)
    assert {c.number for c in conditions} == set(SAFETY_NET_CONDITIONS.values())
    assert all(not c.ok for c in conditions)
    assert all(c.reason for c in conditions)


def test_individuation_failure_withholds_the_caretaker_start_notice(monkeypatch):
    from kaine.cycle import __main__ as main_module
    from kaine.cycle.unattended_gate import Condition

    net = type(
        "GateResult",
        (),
        {
            "checks": {
                "preservation_enabled": True,
                "welfare_response_wired": True,
                "logging_active": True,
                "dry_self_check_passed": True,
                "encryption_satisfied": True,
                "individuation_enabled": False,
                "supervisor_armed": True,
            }
        },
    )()

    eight_ok = Condition(number=8, name="continuous input", ok=True, reason="")

    caretaker_calls: list[tuple[bool, dict[str, bool]]] = []

    def fake_caretaker(
        cfg: Any, prerequisites_ok: bool, conditions: dict[str, bool]
    ) -> Condition:
        caretaker_calls.append((prerequisites_ok, dict(conditions)))
        return Condition(
            number=7,
            name="caretaker told",
            ok=False,
            reason="prerequisites not attempted",
        )

    monkeypatch.setattr(main_module, "_evaluate_research_safety_net", lambda cfg: net)
    monkeypatch.setattr(
        "kaine.cycle.input_check.check_input_condition", lambda cfg: eight_ok
    )
    monkeypatch.setattr(
        "kaine.cycle.caretaker.check_caretaker_condition", fake_caretaker
    )

    result = main_module._evaluate_unattended_gate({})
    assert not result.ok
    assert 9 in [c.number for c in result.failed]
    assert len(caretaker_calls) == 1
    prerequisites_ok, passed_conditions = caretaker_calls[0]
    assert prerequisites_ok is False
    assert passed_conditions.get("9_individuation_wired") is False
    assert "7_caretaker_told" not in passed_conditions
