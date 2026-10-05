# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Cursor follow-ups: break-then-jump fixes and undecodable-entry drains."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

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
from kaine.cycle.types import WorkspaceSnapshot
from kaine.experiment.run_context import RunContext, set_run_context
from kaine.modules.chronos.featurizer import SnapshotFeaturizer
from kaine.modules.chronos.module import Chronos
from kaine.modules.eidolon import Eidolon, SelfModel
from kaine.modules.hypnos.module import Hypnos
from kaine.modules.hypnos.voice_alignment import VoiceAlignmentConfig
from kaine.modules.registry import ModuleRegistry
from kaine.security.crypto import CryptoConfig, StateEncryptor, set_state_encryptor

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
            run_id="cursrun012345678",
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


def _str_id(entry_id: str | bytes) -> str:
    return entry_id.decode() if isinstance(entry_id, bytes) else entry_id


def _make_clock(start: float = 0.0, step: float = 0.1):
    state = {"v": start - step}

    def clock():
        state["v"] += step
        return state["v"]

    return clock


class _StubFM:
    def __init__(self):
        self.calls = []

    async def preserve(self, entity, reason=""):
        self.calls.append({"reason": reason})

    async def preserve_and_pause(self, entity, reason=""):
        self.calls.append({"reason": reason})

    async def preserve_and_end(self, entity, reason=""):
        self.calls.append({"reason": reason})


class _FakeNetwork:
    def __init__(self, units: int = 8, value: float = 0.5) -> None:
        self.units = units
        self.value = value
        self.calls: list[list[float]] = []

    def tick(self, feature_vec: list[float]) -> list[float]:
        self.calls.append(list(feature_vec))
        return [self.value] * self.units


class _FakeMnemos:
    pass


class _FakeThymos:
    async def affective_reset(self) -> None:
        pass


class _FakeTrainer:
    async def train(self, *args, **kwargs) -> None:
        pass


async def _entity(bus: AsyncBus, tmp_path: Path, *, name="Aria"):
    reg = ModuleRegistry()
    eid = Eidolon(bus, persistence_path=tmp_path / "sm.json", save_interval_s=60)
    await eid.initialize()
    eid._model = SelfModel(name=name, values=["honesty"])
    reg.register(eid)
    return reg, eid


async def _push_soma_report(bus: AsyncBus, prediction_error: float):
    await bus.publish(
        validate_event(
            source="soma",
            type="soma.report",
            payload={"prediction_error": prediction_error},
            salience=0.5,
            timestamp=datetime.now(timezone.utc),
        )
    )


async def _push_gray_zone(bus_obj: AsyncBus, label: str) -> None:
    await bus_obj.publish(
        validate_event(
            source="welfare",
            type="welfare.gray_zone",
            payload={"gray_zone_event": label, "replay_overload_count": 1},
            salience=0.5,
            timestamp=datetime.now(timezone.utc),
        )
    )


def _welfare_monitor(bus, registry, fm, cfg, *, on_end=None, clock=None, warmup_s=0.0):
    cfg.warmup_s = warmup_s
    mon = WelfareProtectiveMonitor(
        registry=registry,
        fork_manager=fm,
        config=cfg,
        bus=bus,
        incident_log=IncidentLog(enabled=False, path="unused"),
        on_end=on_end,
    )
    if clock is not None:
        mon._clock = clock
    return mon


def _empty_snapshot(tick: int = 0) -> WorkspaceSnapshot:
    return WorkspaceSnapshot(tick_index=tick, selected_events=[], inhibited=False)


# ---------------------------------------------------------------------------
# WelfareProtectiveMonitor — every poll feeds the whole batch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_welfare_notify_cursor_advances_to_end_after_one_poll(
    bus, tmp_path
):
    reg, eid = await _entity(bus, tmp_path)
    fm = _StubFM()
    cfg = WelfareResponseConfig(
        enabled=True,
        action="notify",
        distress_threshold=0.5,
        distress_duration_s=1.0,
        out_root=str(tmp_path / "backups"),
    )
    mon = _welfare_monitor(bus, reg, fm, cfg, clock=_make_clock(0.0, 0.1))

    # Push enough above-threshold reports for a sustained-distress crossing.
    for _ in range(20):
        await _push_soma_report(bus, 0.9)

    stream_ids = await bus.client.xrange("soma.out")
    last_id = _str_id(stream_ids[-1][0])

    observed: list[float] = []
    original_observe = mon._distress.observe

    def _counting_observe(magnitude: float, now: float) -> bool:
        observed.append(magnitude)
        return original_observe(magnitude, now)

    mon._distress.observe = _counting_observe  # type: ignore[method-assign]

    async def _noop_respond(_reason: str) -> None:
        pass

    mon._respond = _noop_respond  # type: ignore[method-assign]

    stop = asyncio.Event()
    await mon._poll_once(stop)

    # The poll now feeds every decoded entry, so the cursor jumps straight to
    # the end of the batch and the tracker saw every report.
    assert _str_id(mon._cursor) == last_id
    assert len(observed) == len(stream_ids)
    await eid.shutdown()


@pytest.mark.asyncio
async def test_welfare_gray_zone_cursor_advances_to_end_after_one_drain(
    bus, tmp_path
):
    reg, eid = await _entity(bus, tmp_path)
    fm = _StubFM()
    cfg = WelfareResponseConfig(
        enabled=True,
        action="notify",
        distress_threshold=0.5,
        distress_duration_s=9999.0,
        repeat_window_s=300.0,
        repeat_threshold=3,
        out_root=str(tmp_path / "backups"),
    )
    mon = _welfare_monitor(bus, reg, fm, cfg, clock=_make_clock(0.0, 1.0))

    for _ in range(10):
        await _push_gray_zone(bus, "replay_overload")

    stream_ids = await bus.client.xrange("welfare.out")
    last_id = _str_id(stream_ids[-1][0])

    recorded: list[float] = []
    recorded_returns: list[bool] = []
    original_record = mon._repeat.record

    def _counting_record(now: float) -> bool:
        ret = original_record(now)
        recorded.append(now)
        recorded_returns.append(ret)
        return ret

    mon._repeat.record = _counting_record  # type: ignore[method-assign]

    reasons = await mon._drain_gray_zone()

    assert _str_id(mon._welfare_cursor) == last_id
    assert len(recorded) == len(stream_ids)
    assert all(r == "repeated_gray_zone" for r in reasons)
    assert len(reasons) == recorded_returns.count(True)
    await eid.shutdown()


# ---------------------------------------------------------------------------
# Hypnos audit drain
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hypnos_audit_drain_continues_past_undecodable_entries(bus, tmp_path):
    config = VoiceAlignmentConfig(
        intent_log_path=tmp_path / "intent.jsonl",
        adapter_output_dir=tmp_path / "adapters",
        enabled=False,
    )
    hypnos = Hypnos(
        bus,
        mnemos=_FakeMnemos(),
        thymos=_FakeThymos(),
        trainer=_FakeTrainer(),
        voice_alignment_config=config,
    )

    for _ in range(70):
        await bus.client.xadd("volition.out", {"junk": "x"})

    await bus.client.xadd(
        "volition.out",
        {
            "source": "volition",
            "type": "volition.choice",
            "salience": "0.5",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "causal_parent": "",
            "payload": "{}",
        },
    )

    events = await hypnos._drain_audit_stream("volition.out")
    assert len(events) == 1
    assert events[0][1].type == "volition.choice"


# ---------------------------------------------------------------------------
# Chronos user-input stream
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chronos_ignores_undecodable_user_input_then_updates(bus, tmp_path):
    network = _FakeNetwork()
    now = {"v": 1000.0}
    chronos = Chronos(
        bus,
        featurizer=SnapshotFeaturizer(clock=lambda: now["v"]),
        network=network,
        user_input_streams=("user_input.out",),
        clock=lambda: now["v"],
    )
    await chronos.initialize()
    try:
        for _ in range(5):
            await bus.client.xadd("user_input.out", {"junk": "x"})

        for _ in range(100):
            if "user_input.out" in chronos._user_input_cursors:
                break
            await asyncio.sleep(0.01)

        assert "user_input.out" in chronos._user_input_cursors
        assert chronos._last_interaction_at is None

        await bus.client.xadd(
            "user_input.out",
            {
                "source": "audition",
                "type": "audition.emotion",
                "salience": "0.5",
                "timestamp": datetime.fromtimestamp(1000.0, tz=timezone.utc).isoformat(),
                "causal_parent": "",
                "payload": "{\"source_label\": \"live_mic\"}",
            },
        )

        for _ in range(100):
            if chronos._last_interaction_at is not None:
                break
            await asyncio.sleep(0.01)

        assert chronos._last_interaction_at == pytest.approx(1000.0)
    finally:
        await chronos.shutdown()
