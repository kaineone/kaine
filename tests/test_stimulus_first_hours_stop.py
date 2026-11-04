# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""First-hours stop criterion (stimulus-control-act 5.4).

Unit tests for the criterion checker, the ProgrammeEndWatcher callback-
returns-True path, and the runner's verdict-file reading.
"""
from __future__ import annotations

import json
import time

import pytest

from kaine.cycle.programme_end import ProgrammeEndWatcher
from kaine.research.ignition_study.first_hours_criterion import (
    FIRST_HOURS_WINDOW_S,
    PAUSED_SHARE_CEILING,
    VERDICT_RELPATH,
    check_first_hours,
    write_verdict,
)
from kaine.research.ignition_study.runner import (
    HOLD_REASONS,
    REVIEW_HOLD_REASONS,
    VIABILITY_MTIME_SLACK_S,
    StudyRunner,
)

pytestmark = pytest.mark.asyncio


def _record(
    awake_s: float = 3600.0,
    paused_share_max: float = 0.0,
    refusals: int = 0,
) -> dict:
    return {
        "record": "stimulus_control",
        "awake_s": awake_s,
        "paused_share_last_awake_hour_max": paused_share_max,
        "pause_share_refusals": refusals,
        "readout": {
            "after_own_act_by_action": {
                "pause": {"seconds": 10.0, "boredom_above_share": 0.5,
                          "mean_alert_excess": None, "mean_learning_progress": None},
            },
        },
    }


# -- Criterion unit tests ---------------------------------------------------


def test_below_threshold_no_stop():
    rec = _record(awake_s=7200.0, paused_share_max=0.15, refusals=0)
    assert check_first_hours(rec, pass_number=1, readout_pause=None) is None


def test_above_threshold_stops():
    rec = _record(awake_s=7200.0, paused_share_max=0.25)
    verdict = check_first_hours(rec, pass_number=2, readout_pause={"seconds": 5.0})
    assert verdict is not None
    assert verdict["verdict"] == "stopped"
    assert verdict["rule"] == "stimulus_control_first_hours"
    assert "paused_share" in verdict["reason"]
    assert verdict["paused_share_last_awake_hour_max"] == 0.25
    assert verdict["pass_number"] == 2
    assert verdict["after_own_act_by_action_pause"] == {"seconds": 5.0}
    assert verdict["record"] is rec


def test_refusals_trigger_stops():
    rec = _record(awake_s=5400.0, refusals=1)
    verdict = check_first_hours(rec, pass_number=0, readout_pause=None)
    assert verdict is not None
    assert verdict["verdict"] == "stopped"
    assert "refusals" in verdict["reason"]
    assert verdict["pause_share_refusals"] == 1


def test_past_first_hours_no_stop():
    rec = _record(awake_s=12000.0, paused_share_max=0.30, refusals=5)
    assert check_first_hours(rec, pass_number=10, readout_pause=None) is None


def test_boundary_exact_no_stop():
    rec = _record(awake_s=7200.0, paused_share_max=PAUSED_SHARE_CEILING)
    assert check_first_hours(rec, pass_number=1, readout_pause=None) is None


def test_verdict_file_written(tmp_path):
    rec = _record(awake_s=3600.0, paused_share_max=0.25)
    verdict = check_first_hours(rec, pass_number=1, readout_pause={"s": 1.0})
    path = write_verdict(verdict, tmp_path)
    assert path == tmp_path / VERDICT_RELPATH
    data = json.loads(path.read_text())
    assert data["verdict"] == "stopped"
    assert data["rule"] == "stimulus_control_first_hours"
    assert data["awake_s"] == 3600.0
    assert data["pass_number"] == 1
    assert data["paused_share_last_awake_hour_max"] == 0.25
    assert data["pause_share_refusals"] == 0
    assert data["after_own_act_by_action_pause"] == {"s": 1.0}
    assert data["record"] is not None


def test_constants():
    assert FIRST_HOURS_WINDOW_S == 10800.0
    assert PAUSED_SHARE_CEILING == 0.20
    assert "stimulus_control_first_hours" in HOLD_REASONS
    assert "stimulus_control_first_hours" in REVIEW_HOLD_REASONS


# -- ProgrammeEndWatcher callback-returns-True tests -------------------------


class _FakeClock:
    def __init__(self, *, started=False, paused=False, index=-1):
        self.started = started
        self.paused = paused
        self._index = index
        self._t = 0.0
        self.pass_number = 0

    def locate(self):
        return (self._index, 0.0, 1.0)

    def monotonic(self):
        return self._t

    def advance(self, dt: float) -> None:
        self._t += dt


async def test_callback_returns_true_preserves_and_stops():
    clock = _FakeClock(started=True, paused=False, index=0)
    writes = []

    async def on_pass(n: int) -> bool:
        return True

    def read_ok():
        if writes:
            return {"request_id": writes[-1].request_id, "ok": True}
        return None

    watcher = ProgrammeEndWatcher(
        clock,
        3,
        mode="continue",
        on_pass_end=on_pass,
        write_request=writes.append,
        read_result=read_ok,
        freeze=lambda _r, _s: None,
        sleep=lambda _dt: clock.advance(_dt),
        clock_fn=clock.monotonic,
    )

    clock.pass_number = 1
    result = await watcher.step()
    assert result is True
    assert len(writes) == 1


async def test_callback_returns_false_continues():
    clock = _FakeClock(started=True, paused=False, index=0)
    passes_completed: list[int] = []

    async def on_pass(n: int) -> bool:
        passes_completed.append(n)
        return False

    watcher = ProgrammeEndWatcher(
        clock,
        3,
        mode="continue",
        on_pass_end=on_pass,
        write_request=lambda _: None,
        read_result=lambda: None,
        freeze=lambda _r, _s: None,
        sleep=lambda _dt: clock.advance(_dt),
        clock_fn=clock.monotonic,
    )

    clock.pass_number = 1
    result = await watcher.step()
    assert result is False
    assert passes_completed == [0]

    clock.pass_number = 2
    result = await watcher.step()
    assert result is False
    assert passes_completed == [0, 1]


async def test_callback_returns_none_continues():
    clock = _FakeClock(started=True, paused=False, index=0)

    async def on_pass(n: int):
        return None

    watcher = ProgrammeEndWatcher(
        clock,
        3,
        mode="continue",
        on_pass_end=on_pass,
        write_request=lambda _: None,
        read_result=lambda: None,
        freeze=lambda _r, _s: None,
        sleep=lambda _dt: clock.advance(_dt),
        clock_fn=clock.monotonic,
    )

    clock.pass_number = 1
    result = await watcher.step()
    assert result is False


async def test_callback_true_then_handled():
    clock = _FakeClock(started=True, paused=False, index=0)
    writes = []

    async def on_pass(n: int) -> bool:
        return True

    def read_ok():
        if writes:
            return {"request_id": writes[-1].request_id, "ok": True}
        return None

    watcher = ProgrammeEndWatcher(
        clock,
        3,
        mode="continue",
        on_pass_end=on_pass,
        write_request=writes.append,
        read_result=read_ok,
        freeze=lambda _r, _s: None,
        sleep=lambda _dt: clock.advance(_dt),
        clock_fn=clock.monotonic,
    )

    clock.pass_number = 1
    assert await watcher.step() is True
    clock.pass_number = 2
    assert await watcher.step() is True
    assert len(writes) == 1


# -- Runner integration tests ------------------------------------------------


def test_verdict_file_sets_outcome_and_hold(tmp_path):
    verdict = {
        "verdict": "stopped",
        "rule": "stimulus_control_first_hours",
        "reason": "paused_share_last_awake_hour_max exceeded 0.20",
        "awake_s": 3600.0,
        "pass_number": 1,
        "paused_share_last_awake_hour_max": 0.25,
        "pause_share_refusals": 0,
        "after_own_act_by_action_pause": None,
        "record": {},
    }
    step_dir = tmp_path / "step"
    lifecycle = step_dir / "state" / "lifecycle"
    lifecycle.mkdir(parents=True)
    verdict_path = lifecycle / "stimulus_control_first_hours.json"
    verdict_path.write_text(json.dumps(verdict))

    record = _simulate_runner_verdict_read(step_dir, verdict_path)
    assert record["outcome"] == "failed:stimulus_control_first_hours"
    assert record["stimulus_control_first_hours"] == verdict
    assert "welfare_hold" in record
    assert "stimulus_control_first_hours" in record["welfare_hold"]["reasons"]


def test_verdict_file_absent_no_change(tmp_path):
    step_dir = tmp_path / "step"
    lifecycle = step_dir / "state" / "lifecycle"
    lifecycle.mkdir(parents=True)
    record = _simulate_runner_verdict_read(step_dir)
    assert record["outcome"] == "complete"
    assert "stimulus_control_first_hours" not in record


def test_verdict_file_stale_mtime_ignored(tmp_path):
    verdict = {
        "verdict": "stopped",
        "rule": "stimulus_control_first_hours",
        "reason": "test",
        "awake_s": 3600.0,
        "pass_number": 1,
        "paused_share_last_awake_hour_max": 0.25,
        "pause_share_refusals": 0,
        "after_own_act_by_action_pause": None,
        "record": {},
    }
    step_dir = tmp_path / "step"
    lifecycle = step_dir / "state" / "lifecycle"
    lifecycle.mkdir(parents=True)
    verdict_path = lifecycle / "stimulus_control_first_hours.json"
    verdict_path.write_text(json.dumps(verdict))
    import os
    stale_time = time.time() - 3600
    os.utime(verdict_path, (stale_time, stale_time))

    record = _simulate_runner_verdict_read(step_dir, verdict_path, step_started_wall=time.time())
    assert record["outcome"] == "complete"
    assert "stimulus_control_first_hours" not in record


def _simulate_runner_verdict_read(
    line_dir,
    verdict_path=None,
    step_started_wall=None,
):
    """Reproduce the runner's verdict-file reading logic without booting a cycle."""
    import json as _json

    if step_started_wall is None:
        step_started_wall = time.time() - 10

    outcome = "complete"
    stimulus_first_hours_verdict = None
    stimulus_path = line_dir / "state" / "lifecycle" / "stimulus_control_first_hours.json"
    try:
        if stimulus_path.stat().st_mtime < step_started_wall - VIABILITY_MTIME_SLACK_S:
            raise FileNotFoundError("verdict predates this step")
        stimulus_data = _json.loads(stimulus_path.read_text())
    except FileNotFoundError:
        stimulus_data = None
    except Exception:
        stimulus_data = None
    if isinstance(stimulus_data, dict) and stimulus_data.get("verdict") == "stopped":
        stimulus_first_hours_verdict = stimulus_data
        outcome = "failed:stimulus_control_first_hours"

    record: dict = {"outcome": outcome}
    if stimulus_first_hours_verdict is not None:
        record["stimulus_control_first_hours"] = stimulus_first_hours_verdict
        hold = record.get("welfare_hold")
        if isinstance(hold, dict) and isinstance(hold.get("reasons"), list):
            hold["reasons"].append("stimulus_control_first_hours")
        else:
            record["welfare_hold"] = {"reasons": ["stimulus_control_first_hours"]}
    return record
