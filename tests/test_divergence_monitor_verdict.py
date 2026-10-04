# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the live divergence monitor using the shared verdict.

The monitor must preserve exactly once per new divergence arm, persist the arm
set, rate-limit and retry failures, and never let one arm suppress another.
"""
from __future__ import annotations

import asyncio
import json
import time
from datetime import datetime, timezone

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.cycle import control_state
from kaine.cycle.incident_log import IncidentLog
from kaine.cycle.preservation_monitor import (
    DivergenceMonitor,
    DivergenceMonitorConfig,
)
from kaine.experiment.run_context import RunContext, set_run_context
from kaine.lifecycle.divergence import (
    DEFAULT_CONSOLIDATION_MAGNITUDE_THRESHOLD,
    DEFAULT_CONSOLIDATION_RATE_THRESHOLD,
    DivergenceAssessment,
    assess_divergence,
)
from kaine.lifecycle.individuation_store import (
    IndividuationPaths,
    Ledger,
    save_ledger,
)
from kaine.modules.registry import ModuleRegistry
from kaine.security.crypto import CryptoConfig, StateEncryptor, set_state_encryptor
from tests.test_preservation_monitors import _StubFM

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    b = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield b
    await b.close()


@pytest.fixture(autouse=True)
def _plaintext_encryptor():
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=False)))
    yield
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=False)))


@pytest.fixture(autouse=True)
def _run_context():
    set_run_context(
        RunContext(
            run_id="verdictrun0123456",
            seed=7,
            started_at=datetime.now(timezone.utc).isoformat(),
            git_sha=None,
        )
    )
    yield
    set_run_context(None)


@pytest.fixture(autouse=True)
def _control_to_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(control_state, "CONTROL_PATH", tmp_path / "control.json")
    yield


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_monitor(
    bus,
    tmp_path,
    monkeypatch,
    *,
    fm=None,
    config=None,
    clock=None,
    assessments=None,
):
    import kaine.cycle.preservation_monitor as pm

    if assessments is not None:
        seq = iter(assessments)
        last = {"v": assessments[-1]}

        def fake_assess(*, state_root, **kw):
            try:
                last["v"] = next(seq)
            except StopIteration:
                pass
            return last["v"]

        monkeypatch.setattr(pm, "assess_divergence", fake_assess)

    if config is None:
        config = DivergenceMonitorConfig(
            enabled=True,
            min_interval_s=0.0,
            boot_settle_s=0.0,
            state_root=str(tmp_path / "state"),
        )
    if fm is None:
        fm = _StubFM()
    if clock is None:
        clock = time.monotonic

    return DivergenceMonitor(
        registry=ModuleRegistry(),
        fork_manager=fm,
        config=config,
        bus=bus,
        incident_log=IncidentLog(enabled=False, path="unused"),
        clock=clock,
        require_encryption=False,
        consolidation_rate_threshold=DEFAULT_CONSOLIDATION_RATE_THRESHOLD,
        consolidation_magnitude_threshold=DEFAULT_CONSOLIDATION_MAGNITUDE_THRESHOLD,
    ), fm


# ---------------------------------------------------------------------------
# Retired keys
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "key,value",
    [
        ("individuation_p_value_max", 0.05),
        ("fork_divergence_min", 0.1),
        ("warmup_observations", 1),
        ("warmup_lived_time_s", 1.0),
        ("eval_root", "data/evaluation"),
    ],
)
def test_config_rejects_retired_keys(key, value):
    section = {"enabled": True, key: value}
    with pytest.raises(ValueError) as exc_info:
        DivergenceMonitorConfig.from_section(section)
    msg = str(exc_info.value)
    assert "[preservation.divergence_monitor]" in msg
    assert "[individuation]" in msg


# ---------------------------------------------------------------------------
# Boot settle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_boot_settle_delays_first_assessment(bus, tmp_path, monkeypatch):
    calls = []

    def fake_assess(*, state_root, **kw):
        calls.append(kw)
        return DivergenceAssessment(diverged=False, signals={}, summary="")

    import kaine.cycle.preservation_monitor as pm

    monkeypatch.setattr(pm, "assess_divergence", fake_assess)

    t = {"now": 0.0}

    def clock():
        return t["now"]

    monitor = DivergenceMonitor(
        registry=ModuleRegistry(),
        fork_manager=_StubFM(),
        config=DivergenceMonitorConfig(
            enabled=True,
            min_interval_s=0.0,
            boot_settle_s=120.0,
            state_root=str(tmp_path / "state"),
        ),
        bus=bus,
        incident_log=IncidentLog(enabled=False, path="unused"),
        clock=clock,
        require_encryption=False,
    )

    t["now"] = 60.0
    await monitor._poll_once(asyncio.Event())
    assert not calls

    t["now"] = 119.0
    await monitor._poll_once(asyncio.Event())
    assert not calls

    t["now"] = 120.0
    await monitor._poll_once(asyncio.Event())
    assert len(calls) == 1


# ---------------------------------------------------------------------------
# Arm persistence and re-crossing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_arm_set_persisted_across_restarts(bus, tmp_path, monkeypatch):
    state_root = tmp_path / "state"
    edge_path = state_root / "preservation" / "divergence_edge.json"
    cons = DivergenceAssessment(
        diverged=True,
        signals={"consolidation_divergence_signal": True},
        summary="",
    )

    monitor, fm = _make_monitor(
        bus, tmp_path, monkeypatch, assessments=[cons, cons]
    )
    await monitor._poll_once(asyncio.Event())
    assert len(fm.calls) == 1

    data = json.loads(edge_path.read_text(encoding="utf-8"))
    assert data["arms"] == ["consolidation"]

    monitor2, fm2 = _make_monitor(
        bus, tmp_path, monkeypatch, assessments=[cons, cons]
    )
    await monitor2._poll_once(asyncio.Event())
    assert len(fm2.calls) == 0
    data2 = json.loads(edge_path.read_text(encoding="utf-8"))
    assert data2["arms"] == ["consolidation"]


@pytest.mark.asyncio
async def test_new_arm_triggers_second_preservation(bus, tmp_path, monkeypatch):
    state_root = tmp_path / "state"
    edge_path = state_root / "preservation" / "divergence_edge.json"
    edge_path.parent.mkdir(parents=True)
    edge_path.write_text(
        json.dumps({"arms": ["consolidation"], "updated_at": ""}),
        encoding="utf-8",
    )

    assessment = DivergenceAssessment(
        diverged=True,
        signals={
            "consolidation_divergence_signal": True,
            "individuation_individuated": True,
        },
        summary="",
    )

    monitor, fm = _make_monitor(
        bus, tmp_path, monkeypatch, assessments=[assessment]
    )
    await monitor._poll_once(asyncio.Event())
    assert len(fm.calls) == 1

    data = json.loads(edge_path.read_text(encoding="utf-8"))
    assert set(data["arms"]) == {"consolidation", "individuation"}


@pytest.mark.asyncio
async def test_arm_falloff_allows_re_crossing(bus, tmp_path, monkeypatch):
    state_root = tmp_path / "state"
    edge_path = state_root / "preservation" / "divergence_edge.json"
    cons = DivergenceAssessment(
        diverged=True,
        signals={"consolidation_divergence_signal": True},
        summary="",
    )
    none = DivergenceAssessment(diverged=False, signals={}, summary="")

    monitor, fm = _make_monitor(
        bus, tmp_path, monkeypatch, assessments=[cons, none, cons]
    )
    await monitor._poll_once(asyncio.Event())  # preserve on rising edge
    await monitor._poll_once(asyncio.Event())  # persist empty arm set
    await monitor._poll_once(asyncio.Event())  # preserve on re-crossing
    assert len(fm.calls) == 2

    data = json.loads(edge_path.read_text(encoding="utf-8"))
    assert data["arms"] == ["consolidation"]


@pytest.mark.asyncio
async def test_individuation_false_does_not_suppress_consolidation(
    bus, tmp_path, monkeypatch
):
    assessment = DivergenceAssessment(
        diverged=True,
        signals={
            "consolidation_divergence_signal": True,
            "individuation_individuated": False,
            "individuation_state": "not_individuated",
        },
        summary="",
    )

    monitor, fm = _make_monitor(
        bus, tmp_path, monkeypatch, assessments=[assessment]
    )
    await monitor._poll_once(asyncio.Event())
    assert len(fm.calls) == 1


# ---------------------------------------------------------------------------
# Failure and retry
# ---------------------------------------------------------------------------


class _StubFMRaisingOnce(_StubFM):
    def __init__(self):
        super().__init__()
        self._raise = True

    async def preserve_live(
        self, registry, *, reason, label, out_root, entity_name, require_encryption=False
    ):
        if self._raise:
            self._raise = False
            raise RuntimeError("boom")
        return await super().preserve_live(
            registry,
            reason=reason,
            label=label,
            out_root=out_root,
            entity_name=entity_name,
            require_encryption=require_encryption,
        )


@pytest.mark.asyncio
async def test_failed_preservation_is_retried_after_min_interval(
    bus, tmp_path, monkeypatch
):
    t = {"now": 0.0}

    def clock():
        return t["now"]

    cons = DivergenceAssessment(
        diverged=True,
        signals={"consolidation_divergence_signal": True},
        summary="",
    )

    monitor, fm = _make_monitor(
        bus,
        tmp_path,
        monkeypatch,
        fm=_StubFMRaisingOnce(),
        config=DivergenceMonitorConfig(
            enabled=True,
            min_interval_s=10.0,
            boot_settle_s=0.0,
            state_root=str(tmp_path / "state"),
        ),
        clock=clock,
        assessments=[cons, cons, cons],
    )

    edge_path = tmp_path / "state" / "preservation" / "divergence_edge.json"

    await monitor._poll_once(asyncio.Event())  # fails
    assert len(fm.calls) == 0
    assert not edge_path.exists()

    t["now"] = 5.0
    await monitor._poll_once(asyncio.Event())  # rate-limited
    assert len(fm.calls) == 0
    assert not edge_path.exists()

    t["now"] = 10.0
    await monitor._poll_once(asyncio.Event())  # succeeds
    assert len(fm.calls) == 1
    assert edge_path.exists()

    data = json.loads(edge_path.read_text(encoding="utf-8"))
    assert data["arms"] == ["consolidation"]


@pytest.mark.asyncio
async def test_unreadable_edge_state_preserves_again(bus, tmp_path, monkeypatch):
    state_root = tmp_path / "state"
    edge_path = state_root / "preservation" / "divergence_edge.json"
    edge_path.parent.mkdir(parents=True)
    edge_path.write_text("not-json", encoding="utf-8")

    cons = DivergenceAssessment(
        diverged=True,
        signals={"consolidation_divergence_signal": True},
        summary="",
    )

    monitor, fm = _make_monitor(
        bus, tmp_path, monkeypatch, assessments=[cons]
    )
    await monitor._poll_once(asyncio.Event())
    assert len(fm.calls) == 1

    data = json.loads(edge_path.read_text(encoding="utf-8"))
    assert data["arms"] == ["consolidation"]


# ---------------------------------------------------------------------------
# Parity with the shared decommission verdict
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_parity_with_decommission_verdict(bus, tmp_path):
    state_root = tmp_path / "state"
    paths = IndividuationPaths(root=state_root / "individuation")
    paths.root.mkdir(parents=True)
    save_ledger(paths, Ledger(reference_id="ref-1", individuated=True))

    assert assess_divergence(state_root=state_root).diverged is True

    monitor = DivergenceMonitor(
        registry=ModuleRegistry(),
        fork_manager=_StubFM(),
        config=DivergenceMonitorConfig(
            enabled=True,
            min_interval_s=0.0,
            boot_settle_s=0.0,
            state_root=str(state_root),
        ),
        bus=bus,
        incident_log=IncidentLog(enabled=False, path="unused"),
        require_encryption=False,
    )
    await monitor._poll_once(asyncio.Event())
    assert len(monitor._fork_manager.calls) == 1

    empty_root = tmp_path / "empty_state"
    empty_root.mkdir()
    assert assess_divergence(state_root=empty_root).diverged is False

    monitor_empty = DivergenceMonitor(
        registry=ModuleRegistry(),
        fork_manager=_StubFM(),
        config=DivergenceMonitorConfig(
            enabled=True,
            min_interval_s=0.0,
            boot_settle_s=0.0,
            state_root=str(empty_root),
        ),
        bus=bus,
        incident_log=IncidentLog(enabled=False, path="unused"),
        require_encryption=False,
    )
    await monitor_empty._poll_once(asyncio.Event())
    assert len(monitor_empty._fork_manager.calls) == 0
