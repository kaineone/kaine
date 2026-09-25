# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import asyncio
import glob
import sys
import tempfile
from pathlib import Path

import pytest

from kaine.cycle import control_state, escalation_state
from kaine.cycle.spot import Spot
from kaine.cycle.spot_selftest import (
    check_spot_condition,
    run_spot_selftest,
)

pytestmark = pytest.mark.asyncio


async def test_spot_selftest_passes_with_minimal_section():
    section = {"enabled": True}
    result = await run_spot_selftest(section, timeout_s=2.0)
    assert result.ok, result.reason
    names = [name for name, _ in result.steps]
    for required in ("detect", "freeze", "snapshot", "restart"):
        assert required in names, names


def test_spot_selftest_disabled():
    result = asyncio.run(run_spot_selftest({"enabled": False}))
    assert not result.ok
    assert result.reason == "not enabled"


def test_spot_selftest_no_restart_ladder():
    result = asyncio.run(
        run_spot_selftest({"enabled": True, "max_restart_attempts": 0})
    )
    assert not result.ok
    assert result.reason == "no restart ladder"


def test_spot_selftest_broken_freeze(monkeypatch):
    def fake_freeze(reason=None, path=None, source="operator"):
        return None

    monkeypatch.setattr(control_state, "freeze", fake_freeze)
    result = asyncio.run(run_spot_selftest({"enabled": True}, timeout_s=1.0))
    assert not result.ok
    assert "freeze" in result.reason.lower()


def test_spot_selftest_restart_fails(monkeypatch):
    async def fail_restart(self, name):
        return Spot._RestartResult(False, "light", False)

    monkeypatch.setattr(Spot, "_restart_module", fail_restart)
    result = asyncio.run(run_spot_selftest({"enabled": True}, timeout_s=1.0))
    assert not result.ok
    assert "restart" in result.reason.lower()


def test_spot_selftest_timeout(monkeypatch):
    async def slow_poll(self, stop_event):
        await asyncio.sleep(1.0)

    monkeypatch.setattr(Spot, "_poll_once", slow_poll)
    result = asyncio.run(
        run_spot_selftest({"enabled": True}, timeout_s=0.2)
    )
    assert not result.ok
    assert "timed out" in result.reason.lower()


def test_spot_selftest_does_not_touch_global_state(tmp_path, monkeypatch):
    real_control = tmp_path / "real_control.json"
    real_escalation = tmp_path / "real_escalation.json"
    monkeypatch.setattr(control_state, "CONTROL_PATH", real_control)
    monkeypatch.setattr(escalation_state, "ESCALATION_PATH", real_escalation)

    result = asyncio.run(run_spot_selftest({"enabled": True}, timeout_s=2.0))
    assert result.ok, result.reason

    assert not real_control.exists()
    assert not real_escalation.exists()


def test_spot_selftest_removes_scratch_directory():
    pattern = str(Path(tempfile.gettempdir()) / "kaine-spot-selftest-*")
    before = set(glob.glob(pattern))

    result = asyncio.run(run_spot_selftest({"enabled": True}, timeout_s=2.0))
    assert result.ok, result.reason

    after = set(glob.glob(pattern))
    assert not (after - before)


def test_spot_selftest_does_not_import_entity_modules():
    before = {k for k in sys.modules if k.startswith("kaine.modules.")}

    result = asyncio.run(run_spot_selftest({"enabled": True}, timeout_s=2.0))
    assert result.ok, result.reason

    after = {k for k in sys.modules if k.startswith("kaine.modules.")}
    new = after - before
    allowed = {"kaine.modules.base", "kaine.modules.registry"}
    assert not (new - allowed), new - allowed


def test_check_spot_condition_disabled():
    cond = check_spot_condition({"enabled": False})
    assert cond.number == 6
    assert not cond.ok
    assert cond.reason == "not enabled"


def test_check_spot_condition_unwritable_incident_log(tmp_path):
    section = {
        "enabled": True,
        "incident_log": {"path": str(tmp_path / "f" / "x")},
    }
    (tmp_path / "f").write_text("not a directory")
    cond = check_spot_condition(section)
    assert not cond.ok
    assert "incident log not writable" in cond.reason


def test_check_spot_condition_healthy(tmp_path, monkeypatch):
    monkeypatch.setattr(
        escalation_state, "ESCALATION_PATH", tmp_path / "escalation.json"
    )
    section = {
        "enabled": True,
        "incident_log": {"path": str(tmp_path / "incidents")},
    }
    cond = check_spot_condition(section, timeout_s=2.0)
    assert cond.ok, cond.reason
    assert cond.number == 6


def test_spot_selftest_unfreeze_never_released(tmp_path, monkeypatch):
    real_control = tmp_path / "real_control.json"
    real_escalation = tmp_path / "real_escalation.json"
    monkeypatch.setattr(control_state, "CONTROL_PATH", real_control)
    monkeypatch.setattr(escalation_state, "ESCALATION_PATH", real_escalation)

    def fake_unfreeze(path=None):
        return None

    monkeypatch.setattr(control_state, "unfreeze", fake_unfreeze)

    result = asyncio.run(run_spot_selftest({"enabled": True}, timeout_s=2.0))
    assert not result.ok
    assert "not released" in result.reason.lower()
