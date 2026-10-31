# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The welfare response re-arms once its pause is lifted, and a welfare freeze
survives a restart."""

from __future__ import annotations

import asyncio
import json
import signal
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.bus.schema import validate_event
from kaine.cycle import control_state
from kaine.cycle.incident_log import IncidentLog
from kaine.cycle.preservation_monitor import (
    WelfareProtectiveMonitor,
    WelfareResponseConfig,
)
from kaine.cycle.unfrozen_clock import UnfrozenClock
from kaine.lifecycle.preservation import PreservationResult
from kaine.modules.registry import ModuleRegistry


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    b = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield b
    await b.close()


@pytest.fixture(autouse=True)
def _control_to_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(control_state, "CONTROL_PATH", tmp_path / "control.json")
    monkeypatch.setattr(control_state, "OVERRIDE_AUDIT_PATH", tmp_path / "audit.jsonl")


class _Mono:
    def __init__(self, value: float = 0.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value


class _StubFM:
    def __init__(self):
        self.calls: list[dict] = []

    async def preserve_live(
        self, registry, *, reason, label, out_root, entity_name, require_encryption=False
    ):
        self.calls.append({"reason": reason})
        return PreservationResult(
            ok=True,
            preservation_id=f"pid{len(self.calls)}",
            snapshot_id=f"snap{len(self.calls)}",
            reason=reason,
            label=label,
            run_id="rearm0000001",
            world_model_captured=False,
        )


def _cfg(**overrides) -> WelfareResponseConfig:
    values = dict(
        enabled=True,
        action="pause",
        distress_threshold=0.5,
        distress_duration_s=30.0,
        repeat_window_s=1000.0,
        repeat_threshold=2,
        warmup_s=0.0,
        warmup_ceiling_s=0.0,
    )
    values.update(overrides)
    return WelfareResponseConfig(**values)


def _monitor(
    bus, u: _Mono, cfg=None, on_end=None, on_response=None
) -> WelfareProtectiveMonitor:
    return WelfareProtectiveMonitor(
        registry=ModuleRegistry(),
        fork_manager=_StubFM(),
        config=cfg or _cfg(),
        bus=bus,
        incident_log=IncidentLog(enabled=False, path="unused"),
        clock=u,
        on_end=on_end,
        on_response=on_response,
        unfrozen_clock=UnfrozenClock(
            control_state.read_frozen_state, unknown_counts_as="unfrozen", monotonic=u
        ),
    )


async def _distress(bus: AsyncBus, error: float = 0.9) -> None:
    await bus.publish(
        validate_event(
            source="interoception",
            type="interoception.report",
            payload={"prediction_error": error, "warmup_active": False},
            salience=0.5,
            timestamp=datetime.now(timezone.utc),
        )
    )


async def _gray_zone(bus: AsyncBus, category: str) -> None:
    await bus.publish(
        validate_event(
            source="welfare",
            type="welfare.gray_zone",
            payload={"gray_zone_event": category},
            salience=0.8,
            timestamp=datetime.now(timezone.utc),
        )
    )


async def _act(mon, bus, u: _Mono) -> None:
    """Drive one sustained-distress crossing: the response preserves and pauses."""
    stop = asyncio.Event()
    await _distress(bus)
    await mon._poll_once(stop)
    u.value += 31.0
    await mon._poll_once(stop)


@pytest.mark.asyncio
async def test_act_clear_rearm_act_again(bus):
    u = _Mono(0.0)
    mon = _monitor(bus, u)
    stop = asyncio.Event()

    await _act(mon, bus, u)
    assert len(mon._fork_manager.calls) == 1
    assert "welfare" in control_state.read_holder_sources()

    # The pause is lifted by a named override.
    control_state.override(["welfare"])
    await mon._poll_once(stop)
    assert mon._acted is False

    # A new episode: the condition must accrue a full new sustained duration.
    await _distress(bus)
    await mon._poll_once(stop)
    u.value += 15.0
    await mon._poll_once(stop)
    assert len(mon._fork_manager.calls) == 1
    u.value += 16.0
    await mon._poll_once(stop)
    assert len(mon._fork_manager.calls) == 2
    assert "welfare" in control_state.read_holder_sources()


@pytest.mark.asyncio
async def test_no_repeat_firing_while_the_pause_stands_and_the_crossing_holds(bus):
    u = _Mono(0.0)
    mon = _monitor(bus, u)
    stop = asyncio.Event()

    await _act(mon, bus, u)
    for _ in range(6):
        u.value += 40.0
        await _distress(bus)
        await mon._poll_once(stop)
    assert len(mon._fork_manager.calls) == 1
    assert mon._acted is True

    # An operator resume does not lift a welfare freeze, so it does not re-arm.
    control_state.stand_down(source="operator")
    u.value += 40.0
    await mon._poll_once(stop)
    assert len(mon._fork_manager.calls) == 1
    assert mon._acted is True


@pytest.mark.asyncio
async def test_a_condition_still_present_at_release_fires_once_per_new_episode(bus):
    u = _Mono(0.0)
    mon = _monitor(bus, u)
    stop = asyncio.Event()

    await _act(mon, bus, u)
    control_state.override(["welfare"])
    await mon._poll_once(stop)  # re-armed
    # Distress never lets up. Each poll feeds a sample; the response acts again
    # only after a full sustained duration, then latches until the next release.
    for _ in range(10):
        u.value += 10.0
        await _distress(bus)
        await mon._poll_once(stop)
    assert len(mon._fork_manager.calls) == 2


@pytest.mark.asyncio
async def test_events_published_while_frozen_do_not_fire_after_release(bus):
    u = _Mono(0.0)
    mon = _monitor(bus, u)
    stop = asyncio.Event()

    await _act(mon, bus, u)
    # Two gray-zone events (the repeat threshold) arrive during the pause.
    await _gray_zone(bus, "sustained_extreme_vad")
    await _gray_zone(bus, "unmaintained_fatigue")
    await _distress(bus)
    control_state.override(["welfare"])
    for _ in range(3):
        u.value += 5.0
        await mon._poll_once(stop)
    assert len(mon._fork_manager.calls) == 1
    assert mon._acted is False


@pytest.mark.asyncio
async def test_an_unreadable_control_file_is_not_a_release(bus, tmp_path):
    u = _Mono(0.0)
    mon = _monitor(bus, u)
    stop = asyncio.Event()

    await _act(mon, bus, u)
    (tmp_path / "control.json").write_text("{not json")
    assert control_state.read_holder_sources() is None
    await mon._poll_once(stop)
    assert mon._acted is True


@pytest.mark.asyncio
async def test_an_end_never_rearms(bus):
    u = _Mono(0.0)
    ended: list[bool] = []
    mon = _monitor(bus, u, cfg=_cfg(action="end"), on_end=lambda: ended.append(True))
    stop = asyncio.Event()

    await _act(mon, bus, u)
    assert ended == [True]
    await mon._poll_once(stop)
    await mon._poll_once(stop)
    assert mon._acted is True
    assert len(mon._fork_manager.calls) == 1


@pytest.mark.asyncio
async def test_a_standing_welfare_freeze_from_an_earlier_process_latches_then_rearms(bus):
    control_state.freeze(reason="welfare: sustained_distress", source="welfare")
    u = _Mono(0.0)
    mon = _monitor(bus, u)
    stop = asyncio.Event()

    await _distress(bus)
    await mon._poll_once(stop)
    u.value += 60.0
    await mon._poll_once(stop)
    assert mon._acted is True
    assert mon._fork_manager.calls == []

    control_state.override(["welfare"])
    await mon._poll_once(stop)
    assert mon._acted is False


# ---- A welfare freeze survives a restart -----------------------------------


def test_boot_unfreeze_keeps_only_the_welfare_freeze():
    for source in ("operator", "supervisor", "development", "programme_end", "preserve"):
        control_state.push_freeze(reason="x", source=source)
    control_state.push_freeze(reason="distress", source="welfare")

    state = control_state.unfreeze_for_boot()
    assert [e["source"] for e in state.stack] == ["welfare"]
    assert state.frozen is True

    # Only a named override lifts it.
    control_state.override(["welfare"])
    assert control_state.unfreeze_for_boot().stack == ()


@pytest.mark.asyncio
async def test_the_cycle_boot_does_not_lift_a_welfare_freeze(monkeypatch):
    from kaine.cycle import __main__ as cycle_main

    monkeypatch.setattr(cycle_main, "clear_escalation", lambda: None)
    control_state.push_freeze(reason="x", source="operator")
    control_state.push_freeze(reason="distress", source="welfare")
    try:
        await cycle_main._phase_signals(SimpleNamespace(registry={}))
    finally:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.remove_signal_handler(sig)
    assert control_state.read_holder_sources() == frozenset({"welfare"})


def test_the_control_cli_lifts_a_welfare_freeze_by_name(capsys):
    from kaine.cycle import control

    control_state.push_freeze(reason="distress", source="welfare")
    control_state.push_freeze(reason="x", source="operator")
    assert control.run_override(["welfare"]) == 0
    assert "still frozen by: operator" in capsys.readouterr().out
    assert control_state.read_holder_sources() == frozenset({"operator"})
    # A second override finds nothing to lift and says so.
    assert control.run_override(["welfare"]) == 1
    assert "Override refused" in capsys.readouterr().out


def test_the_control_cli_override_handles_os_error(monkeypatch, capsys):
    from kaine.cycle import control

    def _raise_oserror(sources):
        raise OSError(13, f"Permission denied: {sources}")

    monkeypatch.setattr(control_state, "override", _raise_oserror)
    assert control.run_override(["welfare"]) == 2
    assert "Override failed" in capsys.readouterr().out


# ---- unfreeze_for_boot fail-closed behaviour -------------------------------


def test_boot_unfreeze_with_corrupt_control_json_keeps_freeze_and_does_not_overwrite():
    control_state.CONTROL_PATH.write_text("{not json")
    state = control_state.unfreeze_for_boot()
    assert control_state.CONTROL_PATH.read_text() == "{not json"
    assert state.frozen is True
    assert state.source == "welfare"
    assert [e["source"] for e in state.stack] == ["welfare"]


def test_boot_unfreeze_lifts_only_non_welfare_holders_from_readable_file():
    for source in ("operator", "supervisor", "development", "programme_end", "preserve"):
        control_state.push_freeze(reason="x", source=source)
    control_state.push_freeze(reason="distress", source="welfare")

    state = control_state.unfreeze_for_boot()
    assert [e["source"] for e in state.stack] == ["welfare"]
    assert state.frozen is True


class _FakeCycle:
    def __init__(self):
        self._paused = False

    @property
    def is_paused(self):
        return self._paused

    async def pause(self):
        self._paused = True

    async def resume(self):
        self._paused = False


@pytest.mark.asyncio
async def test_corrupt_control_json_makes_freeze_watch_loop_pause_the_cycle(tmp_path, monkeypatch):
    import kaine.cycle.__main__ as cycle_main

    ctrl = tmp_path / "control.json"
    ctrl.write_text("{not json")
    monkeypatch.setattr(cycle_main, "read_control", lambda: control_state.read_control(ctrl))
    monkeypatch.setattr(cycle_main, "write_desired_audio", lambda *a, **k: None)
    monkeypatch.setattr(cycle_main, "write_desired_video", lambda *a, **k: None)

    cycle = _FakeCycle()
    stop = asyncio.Event()
    task = asyncio.create_task(cycle_main._freeze_watch_loop(cycle, stop))
    try:
        waited = 0.0
        while not cycle.is_paused and waited < 2.0:
            await asyncio.sleep(0.02)
            waited += 0.02
        assert cycle.is_paused
    finally:
        stop.set()
        await asyncio.wait_for(task, timeout=2.0)


def test_override_on_corrupt_control_json_replaces_file_and_records_audit(tmp_path):
    control_state.CONTROL_PATH.write_text("{not json")
    state = control_state.override(["welfare"])
    assert state.frozen is False
    assert state.stack == ()
    # The corrupt file is replaced by a clean, readable one.
    loaded = control_state.read_control()
    assert loaded.frozen is False
    assert loaded.stack == ()
    # The audit log records the override and notes the file was unreadable.
    lines = control_state.OVERRIDE_AUDIT_PATH.read_text().strip().split("\n")
    assert lines
    last = json.loads(lines[-1])
    assert last["sources"] == ["welfare"]
    assert last["remaining"] == []
    assert "unreadable" in last.get("note", "")


def test_freeze_and_pop_on_corrupt_control_json_are_no_op(tmp_path):
    p = tmp_path / "control.json"
    p.write_text("{not json")
    original = p.read_bytes()

    state = control_state.freeze(reason="supervisor fault", path=p, source="supervisor")
    assert p.read_bytes() == original
    assert state.frozen is True
    assert state.source == "welfare"

    state = control_state.pop_freeze(path=p, source="supervisor")
    assert p.read_bytes() == original
    assert state.frozen is True
    assert state.source == "welfare"



@pytest.mark.parametrize("content", ["null", "[]", '"frozen"'])
def test_json_that_is_not_an_object_reads_frozen_and_only_a_welfare_override_replaces_it(
    tmp_path, content
):
    p = tmp_path / "control.json"
    p.write_text(content)
    original = p.read_bytes()
    assert control_state.read_control(p).source == "welfare"

    state = control_state.stand_down(path=p, source="operator")
    assert p.read_bytes() == original
    assert state.frozen is True

    with pytest.raises(LookupError):
        control_state.override(["development"], path=p, audit_path=tmp_path / "audit.jsonl")
    assert p.read_bytes() == original

    state = control_state.override(["welfare"], path=p, audit_path=tmp_path / "audit.jsonl")
    assert state.frozen is False
    assert control_state.read_control(p).frozen is False

def test_read_control_on_corrupt_file_has_stable_frozen_at(tmp_path):
    p = tmp_path / "control.json"
    p.write_text("{not json")
    a = control_state.read_control(p)
    b = control_state.read_control(p)
    assert a.frozen_at == b.frozen_at
    assert a.frozen_at is not None


def test_override_development_on_corrupt_file_is_refused(tmp_path):
    p = tmp_path / "control.json"
    p.write_text("{not json")
    original = p.read_bytes()
    with pytest.raises(LookupError, match="welfare"):
        control_state.override(["development"], path=p)
    assert p.read_bytes() == original


@pytest.mark.asyncio
async def test_welfare_monitor_freeze_on_corrupt_file_records_unreadable(bus, tmp_path):
    u = _Mono(0.0)
    mon = _monitor(bus, u)

    control_state.CONTROL_PATH.write_text("{not json")
    await _act(mon, bus, u)
    assert control_state.read_holder_sources() is None

    entries, _ = await bus.read_entries("preservation.out", last_id="0", count=128, block_ms=0)
    protective = [e for _, e in entries if e.type == "welfare.protective_action"]
    assert protective
    assert protective[-1].payload.get("freeze_failed_unreadable") is True


@pytest.mark.asyncio
async def test_end_action_finds_standing_welfare_freeze_at_first_poll(bus):
    control_state.freeze(reason="welfare: sustained_distress", source="welfare")
    u = _Mono(0.0)
    ended: list[bool] = []
    mon = _monitor(bus, u, cfg=_cfg(action="end"), on_end=lambda: ended.append(True))
    stop = asyncio.Event()

    # A welfare freeze from an earlier process is found at the first poll.
    await _distress(bus)
    await mon._poll_once(stop)
    assert mon._acted is True
    assert ended == []
    assert len(mon._fork_manager.calls) == 0

    # The standing freeze is a pause, not an enacted end: once a person lifts
    # it, the monitor re-arms so the running entity is protected again.
    control_state.override(["welfare"])
    await mon._poll_once(stop)
    assert mon._acted is False
    assert ended == []
    assert len(mon._fork_manager.calls) == 0


@pytest.mark.parametrize("content", ["null", "[]"])
def test_read_frozen_state_returns_none_for_non_object_control(content):
    control_state.CONTROL_PATH.write_text(content)
    assert control_state.read_frozen_state() is None


@pytest.mark.asyncio
async def test_pause_if_frozen_at_launch_applies_standing_freeze():
    from kaine.cycle import __main__ as cycle_main

    control_state.push_freeze(reason="distress", source="welfare")

    class FakeCycle:
        def __init__(self):
            self.paused = False

        async def pause(self):
            self.paused = True

    class FakeClock:
        def __init__(self):
            self.calls = []

        def pause(self, reason):
            self.calls.append(reason)

    cycle = FakeCycle()
    clock = FakeClock()
    await cycle_main._pause_if_frozen_at_launch(cycle, clock)
    assert cycle.paused is True
    assert clock.calls == ["freeze"]


@pytest.mark.asyncio
async def test_pause_if_frozen_at_launch_no_control_file_does_not_pause():
    from kaine.cycle import __main__ as cycle_main

    class FakeCycle:
        def __init__(self):
            self.paused = False

        async def pause(self):
            self.paused = True

    class FakeClock:
        def __init__(self):
            self.calls = []

        def pause(self, reason):
            self.calls.append(reason)

    cycle = FakeCycle()
    clock = FakeClock()
    await cycle_main._pause_if_frozen_at_launch(cycle, clock)
    assert cycle.paused is False
    assert clock.calls == []


@pytest.mark.asyncio
async def test_pause_fallback_rearms_after_override(bus):
    u = _Mono(0.0)
    mon = _monitor(bus, u, cfg=_cfg(action="end"), on_end=None)

    await _act(mon, bus, u)
    assert "welfare" in control_state.read_holder_sources()

    control_state.override(["welfare"])
    stop = asyncio.Event()
    await mon._poll_once(stop)
    assert mon._acted is False


@pytest.mark.asyncio
async def test_failed_end_hook_pause_fallback_rearms_after_override(bus):
    def _failing_end() -> None:
        raise RuntimeError("stop failed")

    u = _Mono(0.0)
    mon = _monitor(bus, u, cfg=_cfg(action="end"), on_end=_failing_end)

    await _act(mon, bus, u)
    assert "welfare" in control_state.read_holder_sources()
    assert mon._acted is True

    stop = asyncio.Event()
    await mon._poll_once(stop)
    assert mon._acted is True            # still latched while the freeze stands

    control_state.override(["welfare"])
    await mon._poll_once(stop)
    assert mon._acted is False


def test_run_override_replaces_unreadable_control_file(capsys):
    from kaine.cycle import control

    control_state.CONTROL_PATH.write_text("{not json")
    assert control.run_override(["welfare"]) == 0
    captured = capsys.readouterr()
    assert "The control file was unreadable and was replaced with a clean one" in captured.out


# ---------------------------------------------------------------------------
# A welfare freeze that cannot be written is recorded, notified and retried
# ---------------------------------------------------------------------------


def _failing_end_hook() -> None:
    raise RuntimeError("stop failed")


# The three branches that place the welfare freeze: the pause, an end with no
# stop hook wired, and an end whose stop hook fails.
_FREEZE_PATHS = [
    pytest.param("pause", None, "pause", id="pause"),
    pytest.param("end", None, "pause_fallback", id="end-no-hook"),
    pytest.param("end", _failing_end_hook, "pause_fallback", id="end-failed-hook"),
]


def _freeze_failing(monkeypatch, failures: int | None) -> list[str]:
    """Make control_state.freeze raise OSError for the first ``failures`` calls
    (every call when None); return the list of attempted freeze reasons."""
    real_freeze = control_state.freeze
    attempts: list[str] = []

    def _freeze(reason=None, path=None, *, source="operator"):
        attempts.append(reason)
        if failures is None or len(attempts) <= failures:
            raise OSError(28, "No space left on device")
        return real_freeze(reason=reason, path=path, source=source)

    monkeypatch.setattr(control_state, "freeze", _freeze)
    return attempts


async def _protective_records(bus) -> list[dict]:
    entries, _ = await bus.read_entries("preservation.out", last_id="0", count=256, block_ms=0)
    return [e.payload for _, e in entries if e.type == "welfare.protective_action"]


@pytest.mark.asyncio
@pytest.mark.parametrize(("action", "on_end", "action_taken"), _FREEZE_PATHS)
async def test_freeze_write_failure_is_recorded_notified_and_retried(
    bus, monkeypatch, action, on_end, action_taken
):
    attempts = _freeze_failing(monkeypatch, failures=1)
    notices: list[str] = []
    u = _Mono(0.0)
    mon = _monitor(
        bus, u, cfg=_cfg(action=action), on_end=on_end, on_response=notices.append
    )
    stop = asyncio.Event()

    await _act(mon, bus, u)
    # The preservation bundle is made once, the freeze failed, and the entity
    # is not paused: the response is latched but the pause is not placed.
    assert len(mon._fork_manager.calls) == 1
    assert len(attempts) == 1
    assert control_state.read_holder_sources() == frozenset()
    assert mon._acted is True
    assert mon._pause_placed is False
    records = await _protective_records(bus)
    assert len(records) == 1
    assert records[0]["transition"] == "protective_action_freeze_failed"
    assert records[0]["action"] == action_taken
    assert "OSError" in records[0]["freeze_error"]
    assert "No space left on device" in records[0]["freeze_error"]
    assert records[0]["preservation_id"] == "pid1"
    # The caretaker is told the freeze failed, not that a pause was placed.
    assert notices == ["protective_action_freeze_failed"]

    # The next poll retries only the freeze, and this time it is written.
    u.value += 1.0
    await _distress(bus)
    await mon._poll_once(stop)
    assert len(attempts) == 2
    assert "welfare" in control_state.read_holder_sources()
    assert len(mon._fork_manager.calls) == 1
    assert mon._acted is True
    assert mon._pause_placed is True
    records = await _protective_records(bus)
    assert len(records) == 2
    placed = records[-1]
    assert placed["transition"] == "protective_action_freeze_placed"
    assert placed["incident_id"] == records[0]["incident_id"]
    assert placed["action"] == action_taken
    assert placed["freeze_attempts"] == 2
    assert placed["freeze_error"] is None
    assert placed["freeze_found_in_place"] is False
    # The caretaker hears once more that the pending freeze is now placed.
    assert notices == ["protective_action_freeze_failed", "protective_action_freeze_placed"]

    # Latched like a normal pause: still latched while the freeze stands, and
    # re-armed only by the named override.
    u.value += 40.0
    await _distress(bus)
    await mon._poll_once(stop)
    assert mon._acted is True
    assert len(attempts) == 2
    assert len(mon._fork_manager.calls) == 1
    control_state.stand_down(source="operator")
    await mon._poll_once(stop)
    assert mon._acted is True
    control_state.override(["welfare"])
    await mon._poll_once(stop)
    assert mon._acted is False
    assert mon._pause_placed is False


@pytest.mark.asyncio
@pytest.mark.parametrize(("action", "on_end", "action_taken"), _FREEZE_PATHS)
async def test_freeze_failing_every_poll_retries_without_new_responses(
    bus, monkeypatch, caplog, action, on_end, action_taken
):
    attempts = _freeze_failing(monkeypatch, failures=None)
    notices: list[str] = []
    u = _Mono(0.0)
    mon = _monitor(
        bus, u, cfg=_cfg(action=action), on_end=on_end, on_response=notices.append
    )
    stop = asyncio.Event()

    with caplog.at_level("DEBUG", logger="kaine.cycle.preservation_monitor"):
        await _act(mon, bus, u)
        # Distress keeps going and every poll retries the freeze, which keeps
        # failing. Ten polls inside one log interval, then one past it.
        for _ in range(10):
            u.value += 1.0
            await _distress(bus)
            await mon._poll_once(stop)
        u.value += 61.0
        await mon._poll_once(stop)

    assert len(attempts) == 12               # the first try plus one per poll
    assert len(mon._fork_manager.calls) == 1  # no second preservation bundle
    records = await _protective_records(bus)
    assert [r["transition"] for r in records] == ["protective_action_freeze_failed"]
    assert notices == ["protective_action_freeze_failed"]
    assert mon._acted is True
    assert mon._pause_placed is False
    assert control_state.read_holder_sources() == frozenset()
    freeze_errors = [
        r for r in caplog.records
        if r.levelname == "ERROR" and "welfare freeze" in r.getMessage()
    ]
    # The first failure, then one more only once the log interval has passed.
    assert len(freeze_errors) == 2


@pytest.mark.asyncio
async def test_successful_freeze_records_no_freeze_error(bus):
    u = _Mono(0.0)
    mon = _monitor(bus, u)
    await _act(mon, bus, u)
    records = await _protective_records(bus)
    assert len(records) == 1
    assert records[0]["transition"] == "protective_action"
    assert records[0]["freeze_error"] is None
    assert mon._pause_placed is True


def _welfare_entries() -> int:
    return sum(
        1 for e in control_state.read_control().stack if e.get("source") == "welfare"
    )


@pytest.mark.asyncio
async def test_freeze_that_landed_but_raised_is_found_in_place_not_written_twice(
    bus, monkeypatch
):
    # The first freeze writes the welfare entry and then raises, as a write
    # that landed but reported failure would.
    real_freeze = control_state.freeze
    attempts: list[str] = []

    def _freeze(reason=None, path=None, *, source="operator"):
        attempts.append(reason)
        result = real_freeze(reason=reason, path=path, source=source)
        if len(attempts) == 1:
            raise OSError(28, "No space left on device")
        return result

    monkeypatch.setattr(control_state, "freeze", _freeze)
    notices: list[str] = []
    u = _Mono(0.0)
    mon = _monitor(bus, u, on_response=notices.append)
    stop = asyncio.Event()

    await _act(mon, bus, u)
    assert len(attempts) == 1
    assert _welfare_entries() == 1
    assert mon._pause_placed is False
    assert notices == ["protective_action_freeze_failed"]

    # Later polls find the welfare holder already in place: no second freeze.
    for _ in range(3):
        u.value += 1.0
        await _distress(bus)
        await mon._poll_once(stop)
    assert len(attempts) == 1
    assert _welfare_entries() == 1
    assert mon._pending_freeze is None
    assert mon._pause_placed is True
    records = await _protective_records(bus)
    assert [r["transition"] for r in records] == [
        "protective_action_freeze_failed",
        "protective_action_freeze_placed",
    ]
    assert records[-1]["freeze_found_in_place"] is True
    assert records[-1]["freeze_attempts"] == 1
    assert notices == ["protective_action_freeze_failed", "protective_action_freeze_placed"]

    # The named override re-arms, and the monitor does not put the freeze back.
    control_state.override(["welfare"])
    for _ in range(3):
        u.value += 1.0
        await mon._poll_once(stop)
    assert mon._acted is False
    assert control_state.read_holder_sources() == frozenset()
    assert len(attempts) == 1
    assert [r["transition"] for r in await _protective_records(bus)] == [
        "protective_action_freeze_failed",
        "protective_action_freeze_placed",
        "rearmed",
    ]


@pytest.mark.asyncio
async def test_unreadable_holders_fall_through_to_the_normal_retry(bus, monkeypatch):
    attempts = _freeze_failing(monkeypatch, failures=1)
    u = _Mono(0.0)
    mon = _monitor(bus, u)
    stop = asyncio.Event()

    await _act(mon, bus, u)
    assert len(attempts) == 1
    mon._read_holders = lambda: None
    u.value += 1.0
    await mon._poll_once(stop)
    assert len(attempts) == 2
    assert mon._pause_placed is True
    records = await _protective_records(bus)
    assert records[-1]["transition"] == "protective_action_freeze_placed"
    assert records[-1]["freeze_found_in_place"] is False
