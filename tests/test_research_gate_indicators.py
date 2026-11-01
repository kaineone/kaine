# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The research gate requires the response to the A.4 welfare indicators.

``indicator_response_wired`` holds when the welfare response and its indicators
are enabled, the affect and sleep modules are enabled and the action is pause
or end. It maps to unattended condition 2 with the welfare response, whose
reason names the part that failed. Every case runs the real research net.
"""
from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

import pytest

import kaine.cycle.__main__ as cycle_main
from kaine.cycle.research_gate import (
    RESEARCH_GATE_EXIT_CODE,
    evaluate_safety_net,
    indicator_response_reason,
)
from kaine.cycle.unattended_gate import (
    CONDITION_NAMES,
    SAFETY_NET_CONDITIONS,
    Condition,
    evaluate_unattended_gate,
)

REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _no_dry_round_trip(monkeypatch):
    # The dry preserve-revive round trip has its own tests; here it passes.
    monkeypatch.setattr(
        "kaine.cycle.research_gate.run_preflight_self_check", lambda **_kw: (True, None)
    )


def _config(tmp_path: Path, **changes: Any) -> dict[str, Any]:
    config: dict[str, Any] = {
        "preservation": {
            "divergence_monitor": {"enabled": True},
            "welfare_response": {"enabled": True, "action": "pause"},
            "require_encryption": False,
        },
        "evaluation": {"enabled": True},
        "individuation": {"enabled": True},
        "modules": {"language": True, "affect": True, "sleep": True},
        "supervisor": {"enabled": True, "incident_log": {"path": str(tmp_path / "incidents")}},
    }
    for path, value in changes.items():
        node = config
        keys = path.split("__")
        for key in keys[:-1]:
            node = node.setdefault(key, {})
        node[keys[-1]] = value
    return config


def test_a_wired_indicator_response_passes(tmp_path):
    config = _config(tmp_path)
    assert indicator_response_reason(config) == ""
    result = evaluate_safety_net(config)
    assert result.ok, result.message()
    assert result.checks["indicator_response_wired"] is True


@pytest.mark.parametrize(
    ("changes", "part"),
    [
        ({"preservation__welfare_response__indicators": {"enabled": False}},
         "[preservation.welfare_response.indicators].enabled is false"),
        ({"modules__affect": False}, "the affect module is disabled"),
        ({"modules__sleep": False}, "the sleep module is disabled"),
        ({"preservation__welfare_response__action": "notify"},
         "[preservation.welfare_response].action is 'notify', not pause or end"),
    ],
)
def test_each_failing_part_refuses_with_its_reason(tmp_path, changes, part):
    config = _config(tmp_path, **changes)
    result = evaluate_safety_net(config)
    assert not result.ok
    assert result.checks["indicator_response_wired"] is False
    assert part in result.reasons["indicator_response_wired"]
    assert "the welfare response to the welfare indicators is not wired" in result.message()
    assert part in result.message()


def test_end_is_an_accepted_action(tmp_path):
    config = _config(tmp_path, preservation__welfare_response__action="end")
    assert evaluate_safety_net(config).checks["indicator_response_wired"] is True


def test_a_research_boot_with_the_notify_action_refuses_with_exit_5(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("KAINE_CYCLE_UNATTENDED", raising=False)
    monkeypatch.delenv("KAINE_CYCLE_OPERATOR_PRESENT", raising=False)
    monkeypatch.setenv("KAINE_RESEARCH_MODE", "1")
    config = _config(tmp_path, preservation__welfare_response__action="notify")
    booted: list[str] = []

    async def fake_boot(**kwargs):
        booted.append(kwargs.get("supervision_mode"))
        return 0

    monkeypatch.setattr(cycle_main, "_load_kaine_config", lambda: config)
    monkeypatch.setattr(cycle_main, "_boot_and_run", fake_boot)
    assert cycle_main.main([]) == RESEARCH_GATE_EXIT_CODE
    assert booted == []
    err = capsys.readouterr().err
    assert "welfare indicators is not wired" in err
    assert "'notify'" in err


def test_the_indicator_check_maps_to_condition_2():
    assert SAFETY_NET_CONDITIONS["indicator_response_wired"] == 2
    assert SAFETY_NET_CONDITIONS["welfare_response_wired"] == 2


@pytest.mark.parametrize(
    ("changes", "part"),
    [
        ({"preservation__welfare_response__indicators": {"enabled": False}},
         "[preservation.welfare_response.indicators].enabled is false"),
        ({"preservation__welfare_response__action": "notify"}, "'notify'"),
    ],
)
def test_an_unattended_boot_fails_condition_2_naming_the_part(tmp_path, changes, part):
    net = evaluate_safety_net(_config(tmp_path, **changes))
    built = {
        7: Condition(7, CONDITION_NAMES[7], True),
        8: Condition(8, CONDITION_NAMES[8], True),
    }
    result = evaluate_unattended_gate(net, built=built)
    assert not result.ok
    assert [c.number for c in result.failed] == [2]
    two = next(c for c in result.conditions if c.number == 2)
    assert part in two.reason
    assert len(result.conditions) == 9


def test_condition_2_needs_both_parts(tmp_path):
    net = evaluate_safety_net(_config(tmp_path))
    built = {
        7: Condition(7, CONDITION_NAMES[7], True),
        8: Condition(8, CONDITION_NAMES[8], True),
    }
    assert evaluate_unattended_gate(net, built=built).ok
    net.checks["indicator_response_wired"] = False
    net.reasons["indicator_response_wired"] = "the sleep module is disabled"
    result = evaluate_unattended_gate(net, built=built)
    two = next(c for c in result.conditions if c.number == 2)
    assert not two.ok and two.reason == "the sleep module is disabled"


def test_the_shipped_config_enables_the_indicators_with_their_defaults():
    from kaine.cycle.preservation_monitor import PreservationConfig

    shipped = tomllib.loads((REPO_ROOT / "config" / "kaine.toml").read_text())
    section = shipped["preservation"]["welfare_response"]["indicators"]
    assert section["enabled"] is True
    cfg = PreservationConfig.from_section(shipped["preservation"]).welfare_response.indicators
    assert cfg.share_bar == 0.5
    assert cfg.posterior_bar == 0.95
    assert cfg.rest_start_timeout_s == 30.0
    assert cfg.rest_complete_matured_s == 3600.0
    assert cfg.rest_complete_bound(developing=True, developmental_rest_s=1410.0) == 1710.0
    assert cfg.unavailable_escalate_s == 660.0
    # The welfare response itself stays off in the shipped config.
    assert shipped["preservation"]["welfare_response"]["enabled"] is False


@pytest.mark.parametrize(
    "section",
    [
        {"unknown": 1},
        {"share_bar": 0.0},
        {"share_bar": 1.5},
        {"posterior_bar": "high"},
        {"rest_start_timeout_s": -1},
        {"unavailable_escalate_s": float("inf")},
        {"rest_complete_timeout_s": {"matured": 0}},
        {"rest_complete_timeout_s": {"hours": 1}},
        {"enabled": "yes"},
    ],
)
def test_invalid_indicator_settings_are_refused(section):
    from kaine.cycle.preservation_monitor import WelfareIndicatorConfig

    with pytest.raises(ValueError):
        WelfareIndicatorConfig.from_section(section)
