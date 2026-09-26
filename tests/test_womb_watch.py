# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import asyncio
from dataclasses import dataclass
from typing import Any

import pytest
import pytest_asyncio

from kaine.cycle import __main__ as cycle_main
from kaine.cycle.control_state import (
    CycleControl,
    push_freeze,
    read_control,
    unfreeze,
)
from kaine.cycle.engine import CognitiveCycle
from kaine.cycle.womb_watch import (
    GESTATION_FREEZE_SOURCE,
    STAGE_GESTATION_WOMB_LOST,
    STAGE_GESTATION_WOMB_RETURNED,
    WombLossWatcher,
    hold_until_womb_ready,
)
from kaine.lifecycle import stage as lifecycle_stage
from kaine.lifecycle import womb_liveness
from kaine.lifecycle.gate_runner import MaturationGateRunner
from kaine.lifecycle.maturation_gate import MaturationConfig


class FakeClock:
    def __init__(self, start: float = 0.0):
        self.t = start

    def __call__(self) -> float:
        return self.t


@dataclass(frozen=True)
class FakeDesired:
    audio_live_desired: bool = True
    video_live_desired: bool = True


class Recorder:
    def __init__(self):
        self.publishes: list[tuple[str, dict[str, Any], float]] = []
        self.notifies: list[str] = []

    async def publish(self, type_: str, payload: dict[str, Any], salience: float) -> None:
        self.publishes.append((type_, payload, salience))

    async def notify(self, msg: str) -> None:
        self.notifies.append(msg)


class QueuedLiveCheck:
    def __init__(self):
        self.results: list[womb_liveness.WombLiveness] = []

    async def __call__(
        self, config: dict[str, Any], bus: Any, *, window_s: float
    ) -> womb_liveness.WombLiveness:
        if not self.results:
            return womb_liveness.WombLiveness(
                live=False, provider="local", reason="empty queue"
            )
        return self.results.pop(0)


@pytest.fixture
def recorder():
    return Recorder()


@pytest_asyncio.fixture
async def watcher(tmp_path, recorder):
    clock = FakeClock(0.0)
    live_check = QueuedLiveCheck()
    control_path = tmp_path / "control.json"
    w = WombLossWatcher(
        config={},
        bus=None,
        publish=recorder.publish,
        is_gestating=lambda: True,
        notify=recorder.notify,
        live_check=live_check,
        control_path=control_path,
        check_seconds=1.0,
        loss_after_seconds=5.0,
        window_s=2.0,
        clock=clock,
    )
    live_check.results.append(
        womb_liveness.WombLiveness(live=True, provider="local", reason="armed")
    )
    await w.step()
    return w, clock, live_check, recorder


@pytest.mark.asyncio
async def test_hold_until_womb_ready_first_check_ready(recorder):
    async def ready(config, bus):
        return womb_liveness.WombLiveness(live=True, provider="external", reason="")

    result = await hold_until_womb_ready(
        {},
        None,
        asyncio.Event(),
        publish=recorder.publish,
        ready_check=ready,
        retry_seconds=0.01,
    )
    assert result is True
    assert recorder.publishes == []


@pytest.mark.asyncio
async def test_hold_until_womb_ready_not_ready_then_ready(recorder):
    results = [
        womb_liveness.WombLiveness(live=False, provider="local", reason="no feed"),
        womb_liveness.WombLiveness(
            live=False, provider="local", reason="still none"
        ),
        womb_liveness.WombLiveness(live=True, provider="local", reason=""),
    ]

    async def ready(config, bus):
        return results.pop(0)

    result = await hold_until_womb_ready(
        {},
        None,
        asyncio.Event(),
        publish=recorder.publish,
        ready_check=ready,
        retry_seconds=0.01,
    )
    assert result is True
    assert len(recorder.publishes) == 2
    assert recorder.publishes[0][0] == "stage.gestation.no_stimulus"
    assert recorder.publishes[0][1]["detail"] == "no feed"
    assert recorder.publishes[0][1]["provider"] == "local"
    assert recorder.publishes[0][2] == 0.7
    assert recorder.publishes[1][1]["detail"] == "still none"


@pytest.mark.asyncio
async def test_hold_until_womb_ready_stop_event_returns_false(recorder):
    async def ready(config, bus):
        return womb_liveness.WombLiveness(live=False, provider="local", reason="x")

    stop = asyncio.Event()
    stop.set()
    result = await hold_until_womb_ready(
        {},
        None,
        stop,
        publish=recorder.publish,
        ready_check=ready,
        retry_seconds=0.01,
    )
    assert result is False


@pytest.mark.asyncio
async def test_hold_until_womb_ready_raising_ready_check(recorder):
    calls = 0

    async def ready(config, bus):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("boom")
        return womb_liveness.WombLiveness(live=True, provider="local", reason="")

    result = await hold_until_womb_ready(
        {},
        None,
        asyncio.Event(),
        publish=recorder.publish,
        ready_check=ready,
        retry_seconds=0.01,
    )
    assert result is True
    assert len(recorder.publishes) == 1
    assert recorder.publishes[0][0] == "stage.gestation.no_stimulus"
    assert recorder.publishes[0][1]["detail"].startswith("RuntimeError")


@pytest.mark.asyncio
async def test_hold_until_womb_ready_bad_retry_raises(recorder):
    with pytest.raises(ValueError):
        await hold_until_womb_ready(
            {},
            None,
            asyncio.Event(),
            publish=recorder.publish,
            retry_seconds=0,
        )


@pytest.mark.asyncio
async def test_watcher_no_judgement_inside_grace(watcher):
    w, clock, live_check, recorder = watcher
    live_check.results.append(
        womb_liveness.WombLiveness(live=False, provider="local", reason="x")
    )
    await w.step()
    assert not w.womb_lost
    assert len(recorder.publishes) == 0
    assert len(live_check.results) == 1


@pytest.mark.asyncio
async def test_watcher_loss_after_continuous_not_live(watcher):
    w, clock, live_check, recorder = watcher
    clock.t = 10.0
    live_check.results.append(
        womb_liveness.WombLiveness(live=False, provider="local", reason="quiet")
    )
    await w.step()
    assert not w.womb_lost

    clock.t = 15.0
    live_check.results.append(
        womb_liveness.WombLiveness(live=False, provider="local", reason="quiet")
    )
    await w.step()
    assert w.womb_lost

    control = read_control(w._control_path)
    assert any(entry.get("source") == GESTATION_FREEZE_SOURCE for entry in control.stack)
    assert len(recorder.publishes) == 1
    assert recorder.publishes[0][0] == STAGE_GESTATION_WOMB_LOST
    assert recorder.publishes[0][1]["stage"] == "gestation"
    assert recorder.publishes[0][2] == 0.9
    assert recorder.notifies == ["womb_lost"]


@pytest.mark.asyncio
async def test_watcher_single_live_resets_loss_timer(watcher):
    w, clock, live_check, recorder = watcher
    clock.t = 10.0
    live_check.results.append(
        womb_liveness.WombLiveness(live=False, provider="local", reason="quiet")
    )
    await w.step()

    clock.t = 13.0
    live_check.results.append(
        womb_liveness.WombLiveness(live=True, provider="local", reason="")
    )
    await w.step()
    assert not w.womb_lost

    clock.t = 14.0
    live_check.results.append(
        womb_liveness.WombLiveness(live=False, provider="local", reason="quiet")
    )
    await w.step()
    assert not w.womb_lost

    clock.t = 19.0
    live_check.results.append(
        womb_liveness.WombLiveness(live=False, provider="local", reason="quiet")
    )
    await w.step()
    assert w.womb_lost


@pytest.mark.asyncio
async def test_watcher_return_needs_two_consecutive_live(watcher):
    w, clock, live_check, recorder = watcher
    clock.t = 10.0
    live_check.results.extend(
        [
            womb_liveness.WombLiveness(live=False, provider="local", reason="quiet"),
            womb_liveness.WombLiveness(live=False, provider="local", reason="quiet"),
        ]
    )
    await w.step()
    # Loss needs loss_after_seconds (5 s) of continuous not-live.
    clock.t += 5.0
    await w.step()
    assert w.womb_lost

    clock.t = 20.0
    live_check.results.append(
        womb_liveness.WombLiveness(live=True, provider="local", reason="")
    )
    await w.step()
    assert w.womb_lost
    assert w._live_streak == 1

    live_check.results.append(
        womb_liveness.WombLiveness(live=False, provider="local", reason="quiet")
    )
    await w.step()
    assert w._live_streak == 0
    assert w.womb_lost

    live_check.results.extend(
        [
            womb_liveness.WombLiveness(live=True, provider="local", reason=""),
            womb_liveness.WombLiveness(live=True, provider="local", reason=""),
        ]
    )
    await w.step()
    await w.step()
    assert not w.womb_lost
    returned = [p for p in recorder.publishes if p[0] == STAGE_GESTATION_WOMB_RETURNED]
    assert len(returned) == 1
    assert returned[0][2] == 0.6


@pytest.mark.asyncio
async def test_watcher_return_keeps_other_freeze_source(watcher):
    w, clock, live_check, recorder = watcher
    clock.t = 10.0
    live_check.results.extend(
        [
            womb_liveness.WombLiveness(live=False, provider="local", reason="quiet"),
            womb_liveness.WombLiveness(live=False, provider="local", reason="quiet"),
        ]
    )
    await w.step()
    # Loss needs loss_after_seconds (5 s) of continuous not-live.
    clock.t += 5.0
    await w.step()
    assert w.womb_lost

    push_freeze(source="operator", path=w._control_path)

    live_check.results.extend(
        [
            womb_liveness.WombLiveness(live=True, provider="local", reason=""),
            womb_liveness.WombLiveness(live=True, provider="local", reason=""),
        ]
    )
    await w.step()
    await w.step()
    assert not w.womb_lost

    control = read_control(w._control_path)
    assert any(entry.get("source") == "operator" for entry in control.stack)
    assert not any(
        entry.get("source") == GESTATION_FREEZE_SOURCE for entry in control.stack
    )


@pytest.mark.asyncio
async def test_watcher_repush_after_operator_unfreeze(watcher):
    w, clock, live_check, recorder = watcher
    clock.t = 10.0
    live_check.results.extend(
        [
            womb_liveness.WombLiveness(live=False, provider="local", reason="quiet"),
            womb_liveness.WombLiveness(live=False, provider="local", reason="quiet"),
        ]
    )
    await w.step()
    # Loss needs loss_after_seconds (5 s) of continuous not-live.
    clock.t += 5.0
    await w.step()
    assert w.womb_lost

    unfreeze(w._control_path)
    control = read_control(w._control_path)
    assert not any(
        entry.get("source") == GESTATION_FREEZE_SOURCE for entry in control.stack
    )

    live_check.results.append(
        womb_liveness.WombLiveness(live=False, provider="local", reason="quiet")
    )
    await w.step()
    control = read_control(w._control_path)
    assert any(entry.get("source") == GESTATION_FREEZE_SOURCE for entry in control.stack)
    assert w.womb_lost


@pytest.mark.asyncio
async def test_watcher_stops_gestating_pops_freeze(watcher):
    w, clock, live_check, recorder = watcher
    clock.t = 10.0
    live_check.results.extend(
        [
            womb_liveness.WombLiveness(live=False, provider="local", reason="quiet"),
            womb_liveness.WombLiveness(live=False, provider="local", reason="quiet"),
        ]
    )
    await w.step()
    # Loss needs loss_after_seconds (5 s) of continuous not-live.
    clock.t += 5.0
    await w.step()
    assert w.womb_lost

    w._is_gestating = lambda: False
    await w.step()
    assert not w.womb_lost
    control = read_control(w._control_path)
    assert not any(
        entry.get("source") == GESTATION_FREEZE_SOURCE for entry in control.stack
    )


@pytest.mark.asyncio
async def test_watcher_run_stops_and_absorbs_exception(watcher):
    w, clock, live_check, recorder = watcher

    async def raising(config, bus, *, window_s):
        raise RuntimeError("boom")

    w._live_check = raising
    w._check_seconds = 0.01
    clock.t = 100.0
    stop = asyncio.Event()
    task = asyncio.create_task(w.run(stop))
    await asyncio.sleep(0.05)
    stop.set()
    await asyncio.wait_for(task, timeout=0.5)


class FakeCycle:
    def __init__(self):
        self._paused = False
        self.paused_count = 0
        self.resumed_count = 0

    @property
    def is_paused(self) -> bool:
        return self._paused

    async def pause(self) -> None:
        self._paused = True
        self.paused_count += 1

    async def resume(self) -> None:
        self._paused = False
        self.resumed_count += 1


async def _until(predicate, timeout: float = 2.0) -> None:
    """Wait for the freeze loop's next poll (it polls every 0.25 s)."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not predicate() and loop.time() < deadline:
        await asyncio.sleep(0.02)
    # Never return silently on a timeout: a later step could otherwise mask a
    # transition that never happened.
    assert predicate(), "condition not reached before the timeout"


class FreezeLoopEnv:
    def __init__(self):
        self.control = CycleControl()
        self.cycle = FakeCycle()
        self.writes: list[tuple[str, bool]] = []


@pytest.fixture
def freeze_loop_env(monkeypatch):
    env = FreezeLoopEnv()

    def read_control_fn(path=None):
        return env.control

    def read_desired_fn():
        return FakeDesired()

    def write_desired_audio_fn(val: bool) -> None:
        env.writes.append(("audio", val))

    def write_desired_video_fn(val: bool) -> None:
        env.writes.append(("video", val))

    monkeypatch.setattr(cycle_main, "read_control", read_control_fn)
    monkeypatch.setattr(cycle_main, "read_desired", read_desired_fn)
    monkeypatch.setattr(cycle_main, "write_desired_audio", write_desired_audio_fn)
    monkeypatch.setattr(cycle_main, "write_desired_video", write_desired_video_fn)
    return env


@pytest.mark.asyncio
async def test_freeze_watch_gestation_only_does_not_touch_perception(freeze_loop_env):
    env = freeze_loop_env
    stop = asyncio.Event()
    task = asyncio.create_task(cycle_main._freeze_watch_loop(env.cycle, stop))
    await asyncio.sleep(0.05)
    env.control = CycleControl(
        frozen=True,
        source=GESTATION_FREEZE_SOURCE,
        stack=(
            {
                "source": GESTATION_FREEZE_SOURCE,
                "reason": "womb lost",
                "frozen_at": "x",
            },
        ),
    )
    await _until(lambda: env.cycle.is_paused)
    assert env.cycle.is_paused
    assert env.cycle.paused_count >= 1
    assert env.writes == []
    stop.set()
    await asyncio.wait_for(task, timeout=0.5)


@pytest.mark.asyncio
async def test_freeze_watch_non_gestation_freezes_and_restores_perception(
    freeze_loop_env,
):
    env = freeze_loop_env
    stop = asyncio.Event()
    task = asyncio.create_task(cycle_main._freeze_watch_loop(env.cycle, stop))
    await asyncio.sleep(0.05)
    env.control = CycleControl(
        frozen=True,
        source="operator",
        stack=(
            {"source": "operator", "reason": "hold", "frozen_at": "x"},
        ),
    )
    await _until(lambda: env.cycle.is_paused)
    assert env.cycle.is_paused
    assert env.writes == [("audio", False), ("video", False)]

    env.control = CycleControl()
    await _until(lambda: not env.cycle.is_paused)
    assert not env.cycle.is_paused
    assert env.writes == [
        ("audio", False),
        ("video", False),
        ("audio", True),
        ("video", True),
    ]
    stop.set()
    await asyncio.wait_for(task, timeout=0.5)


@pytest.mark.asyncio
async def test_freeze_watch_perception_reconciled_while_paused(freeze_loop_env):
    env = freeze_loop_env
    stop = asyncio.Event()
    task = asyncio.create_task(cycle_main._freeze_watch_loop(env.cycle, stop))
    await asyncio.sleep(0.05)

    # 1. Gestation-only freeze: cycle pauses, perception stays on.
    env.control = CycleControl(
        frozen=True,
        source=GESTATION_FREEZE_SOURCE,
        stack=(
            {
                "source": GESTATION_FREEZE_SOURCE,
                "reason": "womb lost",
                "frozen_at": "x",
            },
        ),
    )
    await _until(lambda: env.cycle.is_paused)
    assert env.cycle.is_paused
    assert env.writes == []

    # 2. Operator added on top: perception is turned off.
    env.control = CycleControl(
        frozen=True,
        source="operator",
        stack=(
            {
                "source": GESTATION_FREEZE_SOURCE,
                "reason": "womb lost",
                "frozen_at": "x",
            },
            {"source": "operator", "reason": "hold", "frozen_at": "y"},
        ),
    )
    await _until(lambda: env.writes == [("audio", False), ("video", False)])
    assert env.cycle.is_paused

    # 3. Operator removed while gestation remains: perception restored, cycle stays paused.
    env.control = CycleControl(
        frozen=True,
        source=GESTATION_FREEZE_SOURCE,
        stack=(
            {
                "source": GESTATION_FREEZE_SOURCE,
                "reason": "womb lost",
                "frozen_at": "x",
            },
        ),
    )
    await _until(
        lambda: env.writes
        == [
            ("audio", False),
            ("video", False),
            ("audio", True),
            ("video", True),
        ]
    )
    assert env.cycle.is_paused

    # 4. Stack empties: cycle resumes; no further perception writes.
    env.control = CycleControl()
    await _until(lambda: not env.cycle.is_paused)
    assert not env.cycle.is_paused
    assert env.writes == [
        ("audio", False),
        ("video", False),
        ("audio", True),
        ("video", True),
    ]

    stop.set()
    await asyncio.wait_for(task, timeout=0.5)


class NoopHooks:
    async def fire(self, name: str, **kwargs: Any) -> None:
        return


class MutableClock:
    def __init__(self, now: float = 0.0):
        self._now = now

    def now(self) -> float:
        return self._now


@pytest.mark.asyncio
async def test_cognitive_cycle_paused_subjective_seconds():
    clock = MutableClock(0.0)
    cycle = object.__new__(CognitiveCycle)
    cycle._paused = asyncio.Event()
    cycle._paused.set()
    cycle._paused_total = 0.0
    cycle._paused_at = None
    cycle._entity_clock = clock
    cycle.hooks = NoopHooks()

    assert cycle.paused_subjective_seconds() == 0.0

    clock._now = 10.0
    await cycle.pause()
    assert cycle.is_paused
    assert cycle._paused_at == 10.0

    clock._now = 25.0
    await cycle.resume()
    assert not cycle.is_paused
    assert cycle._paused_at is None
    assert cycle.paused_subjective_seconds() == 15.0

    clock._now = 40.0
    await cycle.pause()
    assert cycle._paused_at == 40.0

    clock._now = 45.0
    assert cycle.paused_subjective_seconds() == 20.0

    # A second pause() while already paused must not reset the start time.
    clock._now = 50.0
    await cycle.pause()
    assert cycle._paused_at == 40.0
    assert cycle.paused_subjective_seconds() == 25.0

    clock._now = 55.0
    await cycle.resume()
    assert cycle.paused_subjective_seconds() == 30.0


class FakeEntityClock:
    def __init__(self):
        self._now = 0.0
        self.scale = 1.0

    def now(self) -> float:
        return self._now

    def sleep(self, seconds: float) -> None:
        self._now += seconds * self.scale


def build_runner(clock: FakeEntityClock, paused_seconds=None):
    stage = lifecycle_stage.StageState(stage="gestation", lived_seconds=0.0)
    return MaturationGateRunner(
        bus=None,
        config=MaturationConfig.from_dict({}),
        registry=None,
        entity_clock=clock,
        stage_state=stage,
        paused_seconds=paused_seconds,
    )


@pytest.mark.asyncio
async def test_lived_time_adds_unpaused_elapsed():
    clock = FakeEntityClock()
    runner = build_runner(clock, paused_seconds=lambda: 0.0)

    clock._now = 0.0
    runner._accumulate_lived_time()
    assert runner._stage.lived_seconds == 0.0

    clock._now = 10.0
    runner._accumulate_lived_time()
    assert runner._stage.lived_seconds == 10.0


@pytest.mark.asyncio
async def test_lived_time_subtracts_paused_seconds_exactly():
    clock = FakeEntityClock()
    paused = {"s": 0.0}
    runner = build_runner(clock, paused_seconds=lambda: paused["s"])

    clock._now = 0.0
    runner._accumulate_lived_time()
    assert runner._stage.lived_seconds == 0.0

    clock._now = 30.0
    paused["s"] = 20.0
    runner._accumulate_lived_time()
    assert runner._stage.lived_seconds == 10.0


@pytest.mark.asyncio
async def test_lived_time_raising_paused_seconds_reanchors():
    clock = FakeEntityClock()
    calls = 0

    def paused_seconds():
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("boom")
        return 0.0

    runner = build_runner(clock, paused_seconds=paused_seconds)

    clock._now = 0.0
    runner._accumulate_lived_time()
    assert runner._clock_baseline == 0.0

    clock._now = 20.0
    runner._accumulate_lived_time()
    assert runner._stage.lived_seconds == 0.0
    assert runner._clock_baseline is None
    assert runner._paused_baseline is None

    # The span around the failed reading is unknown: the next good tick only
    # re-anchors, and counting resumes from there.
    clock._now = 25.0
    runner._accumulate_lived_time()
    assert runner._stage.lived_seconds == 0.0

    clock._now = 30.0
    runner._accumulate_lived_time()
    assert runner._stage.lived_seconds == 5.0


@pytest.mark.asyncio
async def test_lived_time_without_paused_source_counts_all_elapsed():
    clock = FakeEntityClock()
    runner = build_runner(clock)

    clock._now = 0.0
    runner._accumulate_lived_time()
    assert runner._stage.lived_seconds == 0.0

    clock._now = 7.0
    runner._accumulate_lived_time()
    assert runner._stage.lived_seconds == 7.0
