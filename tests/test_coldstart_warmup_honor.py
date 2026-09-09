# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
"""Cold-start warm-up honor (change coldstart-welfare-spot-honor-warmup).

FIX 1 — the welfare distress net does NOT count while the latest soma.report
carries ``warmup_active: true`` (mirroring Soma's own self-gating), bounded by
``warmup_ceiling_s`` so a stuck flag cannot blind the net forever.

FIX 2 — Spot stands down its heartbeat-staleness liveness recovery for ANY
freeze it does not itself own (operator OR welfare), because a frozen cycle's
modules are silent by design.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

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
from kaine.cycle.spot import Spot, SpotConfig
from kaine.lifecycle.manager import ForkManager
from kaine.modules.base import BaseModule
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


class _StubFM:
    """ForkManager double recording preserve_live calls without touching disk."""

    def __init__(self):
        self.calls: list[dict] = []

    async def preserve_live(self, registry, *, reason, label, out_root,
                            entity_name, require_encryption=False):
        self.calls.append({"reason": reason})
        from kaine.lifecycle.preservation import PreservationResult

        return PreservationResult(
            ok=True, preservation_id=f"pid{len(self.calls)}",
            snapshot_id=f"snap{len(self.calls)}", reason=reason, label=label,
            run_id="coldstart000001", encrypted=True, path=None,
        )


async def _push_soma(bus: AsyncBus, prediction_error: float, warmup_active: bool):
    await bus.publish(validate_event(
        source="soma", type="soma.report",
        payload={"prediction_error": prediction_error, "warmup_active": warmup_active},
        salience=0.5, timestamp=datetime.now(timezone.utc),
    ))


def _monitor(bus, cfg, clock):
    cfg.warmup_s = 0.0  # disable the fixed floor so the soma flag is the gate under test
    mon = WelfareProtectiveMonitor(
        registry=ModuleRegistry(), fork_manager=_StubFM(), config=cfg, bus=bus,
        incident_log=IncidentLog(enabled=False, path="unused"),
    )
    mon._clock = clock
    return mon


@pytest.mark.asyncio
async def test_warmup_active_gates_then_releases(bus):
    """Sustained distress while warmup_active=true does NOT preserve+pause;
    once Soma reports warmup_active=false, genuine sustained distress fires."""
    cfg = WelfareResponseConfig(enabled=True, action="pause", distress_threshold=0.5,
                                distress_duration_s=1.0, warmup_ceiling_s=1800.0)
    t = {"v": 0.0}
    mon = _monitor(bus, cfg, lambda: t["v"])
    stop = asyncio.Event()

    # Cold-start: high distress but warmup_active=true, sustained well past the
    # duration — must be drained, never counted.
    for step in (0.0, 2.0, 4.0):
        await _push_soma(bus, 0.9, warmup_active=True)
        t["v"] = step
        await mon._poll_once(stop)
    assert mon._fork_manager.calls == []
    assert control_state.read_control().frozen is False

    # Soma completes warm-up: warmup_active=false. One poll drains the
    # transition report (flips the flag), then counting resumes: onset, then a
    # sustained crossing past distress_duration_s.
    for step in (10.0, 12.0, 14.0):
        await _push_soma(bus, 0.9, warmup_active=False)
        t["v"] = step
        await mon._poll_once(stop)
    assert len(mon._fork_manager.calls) == 1
    ctl = control_state.read_control()
    assert ctl.frozen is True and ctl.source == "welfare"


@pytest.mark.asyncio
async def test_warmup_ceiling_rearms_on_stuck_flag(bus):
    """A stuck warmup_active=true must not blind the net past warmup_ceiling_s."""
    cfg = WelfareResponseConfig(enabled=True, action="pause", distress_threshold=0.5,
                                distress_duration_s=1.0, warmup_ceiling_s=100.0)
    t = {"v": 0.0}
    mon = _monitor(bus, cfg, lambda: t["v"])
    stop = asyncio.Event()

    # First poll stamps the run origin (t=0) with the flag stuck true.
    await _push_soma(bus, 0.9, warmup_active=True)
    await mon._poll_once(stop)
    assert mon._fork_manager.calls == []

    # Past the ceiling, the flag is ignored: distress re-accrues and fires.
    await _push_soma(bus, 0.9, warmup_active=True)
    t["v"] = 200.0
    await mon._poll_once(stop)
    await _push_soma(bus, 0.9, warmup_active=True)
    t["v"] = 202.0
    await mon._poll_once(stop)
    assert len(mon._fork_manager.calls) == 1


class _CrashedMod(BaseModule):
    """A module whose only task exits immediately while it is not stopping, so
    it re-reads as dead on assessment (the proven test_spot_freeze pattern)."""

    name = "crashy"

    async def initialize(self) -> None:
        async def _exits_immediately():
            return None

        self._tasks.append(asyncio.create_task(_exits_immediately()))
        await asyncio.sleep(0)


async def _crashed_module(bus):
    mod = _CrashedMod(bus)
    await mod.initialize()
    return mod


def _spot(registry, fm, bus):
    return Spot(registry=registry, fork_manager=fm, kaine_config={},
                config=SpotConfig(enabled=True, restart_backoff_s=0.0),
                rebuild_module=lambda name: None, bus=bus)


@pytest.mark.asyncio
@pytest.mark.parametrize("source,should_act", [
    ("welfare", False),   # FIX 2: a welfare freeze silences modules by design
    ("operator", False),  # unchanged: operator freeze already stood down
    ("spot", True),       # Spot's OWN recovery freeze keeps working
])
async def test_spot_stands_down_for_non_spot_freeze(bus, tmp_path, source, should_act):
    mod = await _crashed_module(bus)
    reg = ModuleRegistry(); reg.register(mod)
    spot = _spot(reg, ForkManager(tmp_path / "forks"), bus)
    control_state.freeze(reason=f"{source} freeze", source=source)

    await spot._poll_once(asyncio.Event())

    if should_act:
        assert "crashy" in spot._incidents  # Spot assessed + acted
    else:
        assert "crashy" not in spot._incidents  # stood down, no assessment
    await mod.shutdown()
