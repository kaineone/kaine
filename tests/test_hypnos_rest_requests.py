# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
"""Tests for Nous/Volition rest-request handling in Hypnos."""

import asyncio
import contextlib
from dataclasses import dataclass
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from kaine.bus import Event
from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig


@dataclass
class _PhaseResult:
    success: bool = True
    name: str = ""
    message: str = ""


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield bus
    await bus.close()


class _FakeClock:
    def __init__(self):
        self._now = 0.0

    def now(self):
        return self._now

    def advance(self, seconds):
        self._now += seconds


@pytest.fixture
def hypnos(bus, monkeypatch):
    from kaine.modules.hypnos.module import Hypnos

    clock = _FakeClock()
    h = Hypnos(
        bus,
        entity_clock=clock,
        requested_rest_min_interval_s=1800.0,
        fatigue_triggered=False,
    )
    h._sleep_pending = False
    h._baseline_salience = 0.5
    h._scheduler = SimpleNamespace(mark_completed=lambda: None)

    def _phase(name):
        async def _run(*args, **kwargs):
            return _PhaseResult(success=True, name=name, message="ok")

        return _run

    monkeypatch.setattr("kaine.modules.hypnos.module.light_consolidation", _phase("light"))
    monkeypatch.setattr("kaine.modules.hypnos.module.deep_consolidation", _phase("deep"))
    monkeypatch.setattr(
        "kaine.modules.hypnos.module.associative_replay", _phase("associative")
    )
    monkeypatch.setattr("kaine.modules.hypnos.module.affective_reset", _phase("affective"))

    async def _fake_voice_alignment():
        return (
            SimpleNamespace(
                accepted=False,
                adapter_path=None,
                capability_loss=None,
                reason="skipped",
                samples_used=0,
                dpo_loss=None,
                capability_score_before=None,
                capability_score_after=None,
                mean_intent_expression_similarity_before=None,
                mean_intent_expression_similarity_after=None,
            ),
            _PhaseResult(success=True, name="voice_alignment", message="skipped"),
        )

    monkeypatch.setattr(h, "_run_voice_alignment", _fake_voice_alignment)
    return h


async def _read_rest_requests(bus: AsyncBus):
    entries = await bus.read("hypnos.out", last_id="0")
    return [(id_, e) for id_, e in entries if e.type == "hypnos.rest_request"]


async def _read_typed_entries(bus: AsyncBus, stream: str = "hypnos.out"):
    entries = await bus.read(stream, last_id="0")
    return [(i, e.type, e.payload) for i, (_, e) in enumerate(entries)]


@pytest.mark.asyncio
async def test_real_requested_sleep_starts_and_publishes_accepted_after(hypnos):
    # The interval is measured from boot, so move past it first.
    hypnos._entity_clock.advance(1800.0)
    await hypnos._handle_rest_request({"origin": "nous", "proposal_id": "p1"})
    if getattr(hypnos, "_sleep_task", None):
        await hypnos._sleep_task

    requests = await _read_rest_requests(hypnos._bus)
    accepted = [(id_, r) for id_, r in requests if r.payload.get("accepted") is True]
    assert len(accepted) == 1
    assert accepted[0][1].payload["reason"] == "accepted"
    assert accepted[0][1].payload["proposal_id"] == "p1"

    entries = await _read_typed_entries(hypnos._bus)
    started_idx = next(i for i, t, _ in entries if t == "hypnos.sleep.started")
    accepted_idx = next(
        i
        for i, t, p in entries
        if t == "hypnos.rest_request" and p.get("accepted") is True
    )
    completed_idx = next(i for i, t, _ in entries if t == "hypnos.sleep.completed")
    assert started_idx < accepted_idx < completed_idx

    assert hypnos._last_sleep_ended_at is not None


@pytest.mark.asyncio
async def test_requested_sleep_aborted_publishes_accepted_then_aborted(hypnos, monkeypatch):
    async def _raise(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("kaine.modules.hypnos.module.deep_consolidation", _raise)

    hypnos._entity_clock.advance(1800.0)
    await hypnos._handle_rest_request({"origin": "nous", "proposal_id": "abort-p1"})
    # The requested-sleep task reports the abort itself and does not raise.
    await hypnos._sleep_task

    requests = await _read_rest_requests(hypnos._bus)
    assert len(requests) == 2
    assert requests[0][1].payload["accepted"] is True
    assert requests[0][1].payload["reason"] == "accepted"
    assert requests[0][1].payload["proposal_id"] == "abort-p1"
    assert requests[1][1].payload["accepted"] is False
    assert requests[1][1].payload["reason"] == "aborted"
    assert requests[1][1].payload["proposal_id"] == "abort-p1"

    entries = await _read_typed_entries(hypnos._bus)
    assert any(
        t == "hypnos.sleep.completed" and p.get("aborted") is True
        for _, t, p in entries
    )


@pytest.mark.asyncio
async def test_rest_request_busy_at_start_time_rejected(hypnos):
    hypnos._sleep_pending = True
    await hypnos._handle_rest_request({"origin": "nous", "proposal_id": "busy-p1"})
    assert getattr(hypnos, "_sleep_task", None) is None

    requests = await _read_rest_requests(hypnos._bus)
    busy = [
        r
        for _, r in requests
        if r.payload.get("accepted") is False and r.payload.get("reason") == "busy"
    ]
    assert busy
    assert busy[0].payload["proposal_id"] == "busy-p1"
    assert not any(r.payload.get("accepted") is True for _, r in requests)


@pytest.mark.asyncio
async def test_rest_request_boot_seeding_immediate_request_too_soon(hypnos):
    # Clock is at 0; _last_sleep_ended_at was seeded at construction time.
    await hypnos._handle_rest_request({"origin": "nous", "proposal_id": "soon-p1"})
    requests = await _read_rest_requests(hypnos._bus)
    refusal = [(id_, r) for id_, r in requests if r.payload.get("accepted") is False][0]
    assert refusal[1].payload["reason"] == "too_soon"
    assert refusal[1].payload["proposal_id"] == "soon-p1"
    assert not any(r.payload.get("accepted") is True for _, r in requests)


@pytest.mark.asyncio
async def test_rest_request_refusal_salience_is_zero(hypnos):
    await hypnos._handle_rest_request({})
    requests = await _read_rest_requests(hypnos._bus)
    assert requests
    for _, r in requests:
        assert r.salience == 0.0


@pytest.mark.asyncio
async def test_rest_request_no_frozen_reason(hypnos):
    await hypnos._handle_rest_request({})
    requests = await _read_rest_requests(hypnos._bus)
    assert all(r.payload.get("reason") != "frozen" for _, r in requests)
    assert not hasattr(hypnos, "_operator_frozen")


@pytest.mark.asyncio
async def test_rest_request_after_interval_accepted(hypnos):
    hypnos._last_sleep_ended_at = 0.0
    hypnos._entity_clock.advance(1800.0)
    await hypnos._handle_rest_request({"origin": "nous", "proposal_id": "ok-p1"})
    if getattr(hypnos, "_sleep_task", None):
        await hypnos._sleep_task
    requests = await _read_rest_requests(hypnos._bus)
    accepted = [r for _, r in requests if r.payload.get("accepted") is True]
    assert accepted
    assert accepted[0].payload["reason"] == "accepted"
    assert accepted[0].payload["proposal_id"] == "ok-p1"


@pytest.mark.asyncio
async def test_audit_window_counts_events_before_requested_sleep(hypnos):
    intent = Event(
        source="volition",
        type="intent.rest",
        payload={
            "kind": "rest",
            "entry_id": "rest-1",
            "origin": "nous",
            "proposal_id": "audit-p1",
            "salience": 0.5,
        },
        salience=0.5,
        timestamp=datetime.now(timezone.utc),
    )
    await hypnos._bus.publish(intent)

    # The interval is measured from boot, so move past it first.
    hypnos._entity_clock.advance(1800.0)
    await hypnos._handle_rest_request({"origin": "nous", "proposal_id": "audit-p1"})
    if getattr(hypnos, "_sleep_task", None):
        await hypnos._sleep_task

    entries = await hypnos._bus.read("hypnos.out", last_id="0")
    completed = [e for _, e in entries if e.type == "hypnos.sleep.completed"]
    assert completed
    audit = completed[0].payload["ignition_audit"]
    assert audit["realized_total"] == 1
    assert audit["nous_initiated"] == 1
    assert audit["self_initiated"] == 0


@pytest.mark.asyncio
async def test_volition_consumer_loop_publishes_rest_request(hypnos):
    intent = Event(
        source="volition",
        type="intent.rest",
        payload={
            "kind": "rest",
            "origin": "nous",
            "proposal_id": "loop-p1",
            "salience": 0.5,
        },
        salience=0.5,
        timestamp=datetime.now(timezone.utc),
    )
    await hypnos._bus.publish(intent)

    task = asyncio.create_task(hypnos._volition_consumer_loop())
    requests = []
    for _ in range(50):
        requests = await _read_rest_requests(hypnos._bus)
        if requests:
            break
        await asyncio.sleep(0.05)

    task.cancel()
    # The consumer loop ends by cancellation; that is the expected exit.
    with contextlib.suppress(asyncio.CancelledError):
        await task

    assert requests
    assert any(r.payload.get("proposal_id") == "loop-p1" for _, r in requests)
