# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from typing import Any

import pytest
import pytest_asyncio

from kaine.cycle.control_state import read_control
from kaine.cycle.womb_watch import (
    GESTATION_FREEZE_SOURCE,
    STAGE_GESTATION_WOMB_LOST,
    WombLossWatcher,
)
from kaine.lifecycle import womb_liveness


class FakeClock:
    def __init__(self, start: float = 0.0):
        self.t = start

    def __call__(self) -> float:
        return self.t


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


@pytest_asyncio.fixture
async def env(tmp_path):
    clock = FakeClock(0.0)
    live_check = QueuedLiveCheck()
    recorder = Recorder()
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
        arm_timeout_seconds=120.0,
        clock=clock,
    )
    return w, clock, live_check, recorder, control_path


@pytest.mark.asyncio
async def test_not_live_within_arm_timeout_does_not_freeze(env):
    w, clock, live_check, recorder, _control_path = env
    for _ in range(10):
        clock.t += 10.0
        live_check.results.append(
            womb_liveness.WombLiveness(
                live=False, provider="local", reason="starting"
            )
        )
        await w.step()

    assert not w.womb_lost
    assert not w._armed
    assert len(recorder.publishes) == 0
    assert recorder.notifies == []


@pytest.mark.asyncio
async def test_live_arms_then_continuous_not_live_declares_loss(env):
    w, clock, live_check, recorder, control_path = env
    clock.t = 30.0
    live_check.results.append(
        womb_liveness.WombLiveness(live=True, provider="local", reason="frames")
    )
    await w.step()
    assert w._armed
    assert not w.womb_lost

    # After arming the grace is window_s + 2*check_seconds = 4 s.
    clock.t = 40.0
    live_check.results.append(
        womb_liveness.WombLiveness(live=False, provider="local", reason="quiet")
    )
    await w.step()
    assert not w.womb_lost

    clock.t = 45.0
    live_check.results.append(
        womb_liveness.WombLiveness(live=False, provider="local", reason="quiet")
    )
    await w.step()
    assert w.womb_lost

    control = read_control(control_path)
    assert any(
        entry.get("source") == GESTATION_FREEZE_SOURCE for entry in control.stack
    )
    lost = [p for p in recorder.publishes if p[0] == STAGE_GESTATION_WOMB_LOST]
    assert len(lost) == 1
    assert lost[0][1]["reason"] == "quiet"
    assert recorder.notifies == ["womb_lost"]


@pytest.mark.asyncio
async def test_never_live_declares_loss_at_arm_timeout(env):
    w, clock, live_check, recorder, control_path = env
    for i in range(13):
        clock.t = (i + 1) * 10.0  # 10, 20, ..., 130
        live_check.results.append(
            womb_liveness.WombLiveness(
                live=False, provider="local", reason="timeout reason"
            )
        )
        await w.step()
        if clock.t < 120.0:
            assert not w.womb_lost
        else:
            assert w.womb_lost

    control = read_control(control_path)
    assert any(
        entry.get("source") == GESTATION_FREEZE_SOURCE for entry in control.stack
    )
    lost = [p for p in recorder.publishes if p[0] == STAGE_GESTATION_WOMB_LOST]
    assert len(lost) == 1
    assert lost[0][1]["reason"] == "timeout reason"
    assert recorder.notifies == ["womb_lost"]


def test_arm_timeout_zero_raises(tmp_path):
    recorder = Recorder()
    with pytest.raises(ValueError):
        WombLossWatcher(
            config={},
            bus=None,
            publish=recorder.publish,
            is_gestating=lambda: True,
            notify=recorder.notify,
            control_path=tmp_path / "control.json",
            arm_timeout_seconds=0.0,
        )


def test_boot_holds_for_the_womb_before_any_module_exists() -> None:
    # maturation-gate-liveness 2.1: a gestating entity is never spawned without
    # a ready womb. _boot_and_run cannot run in tests (it boots an entity), so
    # pin the order of its statements: the hold comes after the bus exists and
    # before the registry is built and any module initializes; the locus pin and
    # the womb-loss watcher follow.
    import ast
    import importlib.util
    from pathlib import Path

    spec = importlib.util.find_spec("kaine.cycle.__main__")
    assert spec is not None and spec.origin is not None
    tree = ast.parse(Path(spec.origin).read_text())
    fn = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.AsyncFunctionDef) and n.name == "_boot_and_run"
    )

    def first_line(pred) -> int:
        lines = [n.lineno for n in ast.walk(fn) if pred(n)]
        assert lines, "expected call not found"
        return min(lines)

    def calls(name: str):
        def pred(n) -> bool:
            if not isinstance(n, ast.Call):
                return False
            f = n.func
            return (isinstance(f, ast.Name) and f.id == name) or (
                isinstance(f, ast.Attribute) and f.attr == name
            )

        return pred

    bus_created = first_line(calls("AsyncBus"))
    hold = first_line(calls("hold_until_womb_ready"))
    pin = first_line(calls("write_desired_locus"))
    registry = first_line(calls("build_registry"))
    init = first_line(calls("initialize"))
    watcher = first_line(calls("WombLossWatcher"))
    assert bus_created < hold < pin < registry < init < watcher
