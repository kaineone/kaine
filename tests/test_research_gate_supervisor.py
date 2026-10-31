# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The research gate requires the module supervisor armed and self-tested.

Every case runs the real research net (``evaluate_safety_net``): the real
``check_supervisor_condition`` with its scratch self-test, and the real dry
preserve→revive round trip. A research boot that fails the supervisor
condition refuses with exit code 5 and names the condition and its reason.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

import kaine.cycle.__main__ as cycle_main
from kaine.cycle import control_state, escalation_state
from kaine.cycle.research_gate import RESEARCH_GATE_EXIT_CODE, evaluate_safety_net
from kaine.cycle.supervisor_selftest import check_supervisor_condition


def _net_config(tmp_path: Path, supervisor: dict[str, Any] | None) -> dict[str, Any]:
    config: dict[str, Any] = {
        "preservation": {
            "divergence_monitor": {"enabled": True},
            "welfare_response": {"enabled": True},
            "require_encryption": False,
        },
        "evaluation": {"enabled": True},
        "individuation": {"enabled": True},
        "modules": {"language": True},
    }
    if supervisor is not None:
        config["supervisor"] = supervisor
    return config


def _armed(tmp_path: Path, **extra: Any) -> dict[str, Any]:
    section: dict[str, Any] = {
        "enabled": True,
        "incident_log": {"path": str(tmp_path / "incidents")},
    }
    section.update(extra)
    return section


def test_a_passing_net_includes_the_supervisor(tmp_path):
    result = evaluate_safety_net(_net_config(tmp_path, _armed(tmp_path)))
    assert result.ok, result.message()
    assert result.checks["supervisor_armed"] is True
    assert "supervisor_armed" not in result.reasons


@pytest.mark.parametrize(
    ("section", "reason"),
    [
        (None, "not enabled"),
        ({"enabled": False}, "not enabled"),
        ({"enabled": True, "max_restart_attempts": 0}, "no restart ladder"),
    ],
)
def test_a_config_level_failure_refuses_with_its_reason(tmp_path, section, reason):
    result = evaluate_safety_net(_net_config(tmp_path, section))
    assert not result.ok
    assert result.checks["supervisor_armed"] is False
    assert result.reasons["supervisor_armed"] == reason
    message = result.message()
    assert "module supervisor is not armed and self-tested" in message
    assert reason in message


def test_an_unwritable_escalation_path_refuses(tmp_path, monkeypatch):
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("a file where the escalation directory should be")
    monkeypatch.setattr(escalation_state, "ESCALATION_PATH", blocker / "escalation.json")
    result = evaluate_safety_net(_net_config(tmp_path, _armed(tmp_path)))
    assert not result.ok
    assert result.reasons["supervisor_armed"] == "escalation path not writable"


def test_an_unwritable_incident_log_refuses(tmp_path):
    blocker = tmp_path / "f"
    blocker.write_text("not a directory")
    section = {"enabled": True, "incident_log": {"path": str(blocker / "x")}}
    result = evaluate_safety_net(_net_config(tmp_path, section))
    assert not result.ok
    assert result.reasons["supervisor_armed"] == "incident log not writable"


def test_a_selftest_whose_freeze_never_takes_effect_refuses(tmp_path, monkeypatch):
    def freeze_that_never_lands(reason=None, path=None, source="operator"):
        return None

    monkeypatch.setattr(control_state, "freeze", freeze_that_never_lands)
    result = evaluate_safety_net(
        _net_config(tmp_path, _armed(tmp_path, selftest_timeout_s=2.0))
    )
    assert not result.ok
    reason = result.reasons["supervisor_armed"]
    assert reason.startswith("selftest failed:")
    assert "freeze" in reason
    assert reason in result.message()


def test_the_supervisor_selftest_imports_no_entity_module(tmp_path):
    """No module under kaine.modules is newly imported by the supervisor check.

    The dry preserve→revive self-check (which builds a self-model in a scratch
    directory) is a separate check and is outside this one.
    """
    section = _armed(tmp_path, selftest_timeout_s=2.0)
    before = {name for name in sys.modules if name.startswith("kaine.modules.")}
    condition = check_supervisor_condition(section)
    after = {name for name in sys.modules if name.startswith("kaine.modules.")}
    assert condition.ok, condition.reason
    assert after - before == set()


def _research_main(monkeypatch, tmp_path, config: dict[str, Any]) -> int:
    monkeypatch.delenv("KAINE_CYCLE_UNATTENDED", raising=False)
    monkeypatch.delenv("KAINE_CYCLE_OPERATOR_PRESENT", raising=False)
    monkeypatch.setenv("KAINE_RESEARCH_MODE", "1")
    booted: list[str] = []

    async def fake_boot(*, supervision_mode="operator", gate_checks=None, kaine_config=None):
        booted.append(supervision_mode)
        return 0

    monkeypatch.setattr(cycle_main, "_load_kaine_config", lambda: config)
    monkeypatch.setattr(cycle_main, "_boot_and_run", fake_boot)
    rc = cycle_main.main([])
    if rc == 0:
        assert booted == ["research"]
    else:
        assert booted == []
    return rc


def test_a_research_boot_with_the_supervisor_off_refuses_with_exit_5(
    monkeypatch, tmp_path, capsys
):
    rc = _research_main(
        monkeypatch, tmp_path, _net_config(tmp_path, {"enabled": False})
    )
    assert rc == RESEARCH_GATE_EXIT_CODE == 5
    err = capsys.readouterr().err
    assert "module supervisor is not armed and self-tested: not enabled" in err
    assert "Traceback" not in err


def test_a_research_boot_with_a_failing_selftest_refuses_with_exit_5(
    monkeypatch, tmp_path, capsys
):
    def freeze_that_never_lands(reason=None, path=None, source="operator"):
        return None

    monkeypatch.setattr(control_state, "freeze", freeze_that_never_lands)
    rc = _research_main(
        monkeypatch,
        tmp_path,
        _net_config(tmp_path, _armed(tmp_path, selftest_timeout_s=2.0)),
    )
    assert rc == 5
    err = capsys.readouterr().err
    assert "module supervisor is not armed and self-tested: selftest failed:" in err


def test_a_research_boot_with_the_supervisor_armed_proceeds(monkeypatch, tmp_path):
    rc = _research_main(monkeypatch, tmp_path, _net_config(tmp_path, _armed(tmp_path)))
    assert rc == 0
