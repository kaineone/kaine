# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Snapshot-completeness tests for KAINE module state.

Covers:
- Thymos goal ledger round-trip and restore semantics.
- Hypnos rest-schedule persistence as time-remaining.
- Nous posterior restoration into the inference engine fallback.
"""
from __future__ import annotations

import logging
from pathlib import Path

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.modules.hypnos import FakeTrainer, Hypnos, RestScheduler, VoiceAlignmentConfig
from kaine.modules.nous import Nous
from kaine.modules.nous.engine import FakeEngine, PymdpEngine
from kaine.modules.thymos import Thymos
from kaine.modules.thymos.goals import GoalLedger, GoalState


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield bus
    await bus.close()


def _snap():
    class _Ev:
        def __init__(self, source: str, payload: dict, salience: float):
            self.source = source
            self.payload = payload
            self.salience = salience

    class _Snap:
        def __init__(self, events: list):
            self.selected_events = [(str(i), e) for i, e in enumerate(events)]

    return _Snap([_Ev("soma", {}, 0.9)])


def _make_hypnos(bus: AsyncBus, tmp_path: Path, *, scheduler: RestScheduler | None = None):
    log_path = tmp_path / "intent.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    config = VoiceAlignmentConfig(
        intent_log_path=log_path,
        adapter_output_dir=tmp_path / "adapters",
        enabled=False,
    )
    return Hypnos(
        bus,
        mnemos=None,
        scheduler=scheduler,
        trainer=FakeTrainer(),
        voice_alignment_config=config,
    )


# ---------------------------------------------------------------------------
# Goal ledger
# ---------------------------------------------------------------------------


def test_goal_ledger_round_trip():
    ledger = GoalLedger(clock=lambda: 1234.0)
    g_active = ledger.add("become wiser every day", priority=0.7)
    g_done = ledger.add("walk daily", priority=0.4)
    g_abandoned = ledger.add("read every book", priority=0.6)
    ledger.complete(g_done.id)
    ledger.abandon(g_abandoned.id)

    data = ledger.to_dict()
    restored = GoalLedger.from_dict(data)

    assert len(restored) == 3
    assert restored.get(g_active.id).state == GoalState.ACTIVE
    assert restored.get(g_done.id).state == GoalState.COMPLETED
    assert restored.get(g_abandoned.id).state == GoalState.ABANDONED
    assert restored.active() == [restored.get(g_active.id)]
    assert restored.relevance("wiser") > 0.0
    assert restored.relevance("walk") == 0.0  # completed goal is not active


def test_goal_ledger_from_dict_drops_invalid_entries(caplog):
    data = {
        "goals": [
            {
                "id": "g1",
                "description": "valid goal",
                "priority": 0.5,
                "state": "active",
                "created_at": 10.0,
            },
            {"description": "missing id", "priority": 0.5, "state": "active"},
            {"id": "g2", "priority": 0.5, "state": "active"},
            {
                "id": "g3",
                "description": "bad priority",
                "priority": 1.5,
                "state": "active",
            },
            {
                "id": "g4",
                "description": "bad state",
                "priority": 0.5,
                "state": "sleepy",
            },
        ]
    }
    with caplog.at_level(logging.WARNING, logger="kaine.modules.thymos.goals"):
        restored = GoalLedger.from_dict(data)

    assert len(restored) == 1
    assert "g1" in restored._goals
    assert any("missing id" in r.message for r in caplog.records)
    assert any("g2" in r.message and "description" in r.message for r in caplog.records)
    assert any("g3" in r.message and "priority" in r.message for r in caplog.records)
    assert any("g4" in r.message and "state" in r.message for r in caplog.records)


def test_goal_ledger_load_dict_drops_unparsable_created_at(caplog):
    ledger = GoalLedger()
    ledger.add("keep me", priority=0.5)
    data = {
        "goals": [
            {
                "id": "bad",
                "description": "bad created",
                "priority": 0.5,
                "state": "active",
                "created_at": "not a number",
            },
            {
                "id": "good",
                "description": "valid goal",
                "priority": 0.6,
                "state": "active",
                "created_at": 10.0,
            },
        ]
    }
    with caplog.at_level(logging.WARNING, logger="kaine.modules.thymos.goals"):
        ledger.load_dict(data)

    assert len(ledger) == 1
    assert "good" in ledger._goals
    assert any("bad" in r.message and "created_at" in r.message for r in caplog.records)


def test_goal_ledger_load_dict_drops_non_finite_fields(caplog):
    data = {
        "goals": [
            {
                "id": "nan_priority",
                "description": "x",
                "priority": float("nan"),
                "state": "active",
                "created_at": 1.0,
            },
            {
                "id": "inf_created",
                "description": "x",
                "priority": 0.5,
                "state": "active",
                "created_at": float("inf"),
            },
            {
                "id": "nan_completed",
                "description": "x",
                "priority": 0.5,
                "state": "completed",
                "created_at": 1.0,
                "completed_at": float("nan"),
            },
            {
                "id": "good",
                "description": "valid",
                "priority": 0.5,
                "state": "active",
                "created_at": 1.0,
            },
        ]
    }
    ledger = GoalLedger()
    with caplog.at_level(logging.WARNING, logger="kaine.modules.thymos.goals"):
        ledger.load_dict(data)

    assert len(ledger) == 1
    assert "good" in ledger._goals


def test_goal_ledger_load_dict_non_list_goals_leaves_existing(caplog):
    ledger = GoalLedger()
    g = ledger.add("keep me", priority=0.5)

    with caplog.at_level(logging.WARNING, logger="kaine.modules.thymos.goals"):
        ledger.load_dict({"goals": "not a list"})

    assert len(ledger) == 1
    assert g.id in ledger._goals
    assert any("non-list" in r.message for r in caplog.records)


def test_goal_ledger_load_dict_non_dict_data_leaves_existing(caplog):
    ledger = GoalLedger()
    g = ledger.add("keep me", priority=0.5)

    with caplog.at_level(logging.WARNING, logger="kaine.modules.thymos.goals"):
        ledger.load_dict("not a dict")

    assert len(ledger) == 1
    assert g.id in ledger._goals
    assert any("non-dict" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# Thymos goals persistence
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_thymos_serializes_and_restores_goals(bus: AsyncBus):
    thymos = Thymos(bus, publish_interval_s=999.0)
    g_active = thymos.goals.add("explore perimeter", priority=0.8)
    g_done = thymos.goals.add("finish puzzle", priority=0.6)
    g_abandoned = thymos.goals.add("climb ladder", priority=0.4)
    thymos.goals.complete(g_done.id)
    thymos.goals.abandon(g_abandoned.id)

    snapshot = thymos.serialize()
    assert "goals" in snapshot
    assert len(snapshot["goals"]["goals"]) == 3

    thymos2 = Thymos(bus, publish_interval_s=999.0)
    thymos2.deserialize(snapshot)

    assert len(thymos2.goals) == 3
    assert thymos2.goals.get(g_active.id).state == GoalState.ACTIVE
    assert thymos2.goals.get(g_done.id).state == GoalState.COMPLETED
    assert thymos2.goals.get(g_abandoned.id).state == GoalState.ABANDONED
    assert thymos2.goals.relevance("explore perimeter") > 0.0
    assert thymos2.goals.relevance("finish puzzle") == 0.0


@pytest.mark.asyncio
async def test_thymos_deserialize_without_goals_leaves_ledger(bus: AsyncBus):
    thymos = Thymos(bus, publish_interval_s=999.0)
    thymos.goals.add("owner goal", priority=0.3)
    snapshot = thymos.serialize()
    snapshot.pop("goals")

    thymos2 = Thymos(bus, publish_interval_s=999.0)
    local = thymos2.goals.add("local goal", priority=0.5)
    before_ledger = thymos2.goals
    thymos2.deserialize(snapshot)

    assert thymos2.goals is before_ledger
    assert len(thymos2.goals) == 1
    assert thymos2.goals.get(local.id).description == "local goal"


@pytest.mark.asyncio
async def test_thymos_deserialize_with_goals_keeps_ledger_identity(bus: AsyncBus):
    thymos = Thymos(bus, publish_interval_s=999.0)
    thymos.goals.add("explore perimeter", priority=0.8)
    snapshot = thymos.serialize()

    thymos2 = Thymos(bus, publish_interval_s=999.0)
    before = thymos2.goals
    thymos2.deserialize(snapshot)

    assert thymos2.goals is before
    assert len(thymos2.goals) == 1


@pytest.mark.asyncio
async def test_thymos_restore_does_not_publish_goal_events(bus: AsyncBus):
    thymos = Thymos(bus, publish_interval_s=999.0)
    thymos.goals.add("a goal", priority=0.5)
    snapshot = thymos.serialize()

    thymos2 = Thymos(bus, publish_interval_s=999.0)

    published: list[tuple[str, dict, float]] = []

    async def fake_publish(stream: str, payload: dict, *, salience: float = 0.0) -> None:
        published.append((stream, payload, salience))

    thymos2.publish = fake_publish  # type: ignore[method-assign]
    thymos2.deserialize(snapshot)

    goal_events = [e for e in published if e[0].startswith("thymos.goal")]
    assert goal_events == []


# ---------------------------------------------------------------------------
# Rest scheduler persistence
# ---------------------------------------------------------------------------


def test_scheduler_round_trips_across_long_gap():
    now1 = [1000.0]
    s1 = RestScheduler(
        interval_seconds=600.0,
        max_deferral_seconds=0.0,
        clock=lambda: now1[0],
    )
    assert s1.export_remaining() == pytest.approx(
        {"original_due_in": 600.0, "effective_due_in": 600.0}
    )

    now2 = [5_000_000.0]
    s2 = RestScheduler(
        interval_seconds=600.0,
        max_deferral_seconds=0.0,
        clock=lambda: now2[0],
    )
    s2.restore_remaining(600.0, 600.0)

    now2[0] = 5_000_599.0
    assert s2.is_due() is False
    now2[0] = 5_000_601.0
    assert s2.is_due() is True


def test_scheduler_deferral_is_preserved():
    now1 = [0.0]
    s1 = RestScheduler(
        interval_seconds=1000.0,
        max_deferral_seconds=200.0,
        per_defer_seconds=50.0,
        clock=lambda: now1[0],
    )
    now1[0] = 100.0
    assert s1.try_defer() is True  # effective due at 1150
    exported = s1.export_remaining()
    assert exported["original_due_in"] == pytest.approx(900.0)
    assert exported["effective_due_in"] == pytest.approx(950.0)

    now2 = [0.0]
    s2 = RestScheduler(
        interval_seconds=1000.0,
        max_deferral_seconds=200.0,
        per_defer_seconds=50.0,
        clock=lambda: now2[0],
    )
    s2.restore_remaining(exported["original_due_in"], exported["effective_due_in"])
    assert s2.total_deferral == pytest.approx(50.0)


def test_scheduler_overdue_stays_overdue():
    now1 = [1000.0]
    s1 = RestScheduler(
        interval_seconds=600.0,
        max_deferral_seconds=0.0,
        clock=lambda: now1[0],
    )
    now1[0] = 2500.0  # 900 s overdue
    exported = s1.export_remaining()
    assert exported["original_due_in"] == pytest.approx(-900.0)

    now2 = [10_000_000.0]
    s2 = RestScheduler(
        interval_seconds=600.0,
        max_deferral_seconds=0.0,
        clock=lambda: now2[0],
    )
    s2.restore_remaining(exported["original_due_in"], exported["effective_due_in"])
    now2[0] = 10_000_001.0
    assert s2.is_due() is True


def test_scheduler_restore_rejects_non_finite():
    s = RestScheduler(
        interval_seconds=10.0, max_deferral_seconds=0.0, clock=lambda: 0.0
    )
    with pytest.raises(ValueError):
        s.restore_remaining(float("inf"), 5.0)
    with pytest.raises(ValueError):
        s.restore_remaining(5.0, float("nan"))
    with pytest.raises(ValueError):
        s.restore_remaining(float("nan"), float("nan"))


def test_scheduler_restore_rejects_negative_deferral():
    s = RestScheduler(
        interval_seconds=10.0, max_deferral_seconds=0.0, clock=lambda: 0.0
    )
    with pytest.raises(ValueError):
        s.restore_remaining(5.0, 3.0)


# ---------------------------------------------------------------------------
# Hypnos schedule persistence
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hypnos_serializes_schedule(bus: AsyncBus, tmp_path: Path):
    now = [1000.0]
    scheduler = RestScheduler(
        interval_seconds=600.0, max_deferral_seconds=0.0, clock=lambda: now[0]
    )
    hypnos = _make_hypnos(bus, tmp_path, scheduler=scheduler)
    snapshot = hypnos.serialize()
    assert "schedule" in snapshot
    assert snapshot["schedule"]["original_due_in"] == pytest.approx(600.0)
    assert snapshot["schedule"]["effective_due_in"] == pytest.approx(600.0)


@pytest.mark.asyncio
async def test_hypnos_deserialize_restores_remaining_time(bus: AsyncBus, tmp_path: Path):
    now1 = [1000.0]
    scheduler1 = RestScheduler(
        interval_seconds=600.0, max_deferral_seconds=0.0, clock=lambda: now1[0]
    )
    hypnos1 = _make_hypnos(bus, tmp_path, scheduler=scheduler1)
    snapshot = hypnos1.serialize()

    now2 = [5_000_000.0]
    scheduler2 = RestScheduler(
        interval_seconds=600.0, max_deferral_seconds=0.0, clock=lambda: now2[0]
    )
    hypnos2 = _make_hypnos(bus, tmp_path, scheduler=scheduler2)
    hypnos2.deserialize(snapshot)

    now2[0] = 5_000_599.0
    assert hypnos2._scheduler.is_due() is False
    now2[0] = 5_000_601.0
    assert hypnos2._scheduler.is_due() is True


@pytest.mark.asyncio
async def test_hypnos_old_snapshot_starts_fresh(bus: AsyncBus, tmp_path: Path, caplog):
    now1 = [1000.0]
    scheduler1 = RestScheduler(
        interval_seconds=600.0, max_deferral_seconds=0.0, clock=lambda: now1[0]
    )
    hypnos1 = _make_hypnos(bus, tmp_path, scheduler=scheduler1)
    snapshot = hypnos1.serialize()
    snapshot.pop("schedule")

    now2 = [5_000_000.0]
    scheduler2 = RestScheduler(
        interval_seconds=600.0, max_deferral_seconds=0.0, clock=lambda: now2[0]
    )
    hypnos2 = _make_hypnos(bus, tmp_path, scheduler=scheduler2)
    with caplog.at_level(logging.INFO, logger="kaine.modules.hypnos"):
        hypnos2.deserialize(snapshot)

    assert hypnos2._scheduler.effective_due_at == pytest.approx(5_000_600.0)
    assert "snapshot has no schedule; starting a fresh interval" in caplog.text


@pytest.mark.asyncio
async def test_hypnos_malformed_schedule_logs_warning_and_stays_fresh(
    bus: AsyncBus, tmp_path: Path, caplog
):
    now2 = [5_000_000.0]
    scheduler2 = RestScheduler(
        interval_seconds=600.0, max_deferral_seconds=0.0, clock=lambda: now2[0]
    )
    hypnos2 = _make_hypnos(bus, tmp_path, scheduler=scheduler2)
    with caplog.at_level(logging.WARNING, logger="kaine.modules.hypnos"):
        hypnos2.deserialize({"schedule": {"original_due_in": "bad"}})

    assert hypnos2._scheduler.effective_due_at == pytest.approx(5_000_600.0)
    assert "malformed schedule" in caplog.text


# ---------------------------------------------------------------------------
# Nous posterior restoration into engine
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_nous_deserialize_seeds_fake_engine(bus: AsyncBus):
    restored_posterior = [
        [0.0, 1.0, 0.0, 0.0],
        [0.2, 0.6, 0.2],
        [0.1, 0.1, 0.7, 0.1],
        [0.25, 0.25, 0.25, 0.25],
    ]
    original = Nous(bus, engine=FakeEngine())
    original._last_posterior = restored_posterior
    snapshot = original.serialize()

    seeded_engine = FakeEngine(timeout_on=0)
    new = Nous(bus, engine=seeded_engine)
    new.deserialize(snapshot)

    assert new._last_posterior == restored_posterior
    assert seeded_engine._last_posterior == restored_posterior

    result = seeded_engine.step(_snap())
    assert result.timed_out is True
    assert result.posterior == restored_posterior


@pytest.mark.asyncio
async def test_nous_mismatched_posterior_ignored_and_warning(bus: AsyncBus, caplog):
    original = Nous(bus, engine=FakeEngine())
    original._last_posterior = [[0.5, 0.5], [0.3, 0.3, 0.4]]  # wrong shape
    snapshot = original.serialize()

    engine = FakeEngine()
    default_fallback = list(engine._last_posterior)
    new = Nous(bus, engine=engine)
    with caplog.at_level(logging.WARNING, logger="kaine.modules.nous"):
        new.deserialize(snapshot)

    assert engine._last_posterior == default_fallback
    assert "restored posterior does not match the model" in caplog.text


def test_pymdp_engine_seed_posterior_valid_and_invalid():
    pytest.importorskip("jax")
    pytest.importorskip("pymdp")
    engine = PymdpEngine(efe_timeout_ms=1000)
    sizes = engine.model.num_states
    valid = [[1.0 / n] * n for n in sizes]

    assert engine.seed_posterior(valid) is True
    assert engine._last_posterior == valid

    invalid = [[0.5, 0.5]]  # wrong factor count
    assert engine.seed_posterior(invalid) is False
    assert engine._last_posterior == valid

    engine.close()
