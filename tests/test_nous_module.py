# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Nous module tests.

Module-level tests drive a :class:`FakeEngine` (no pymdp, no JAX), so the green
build never requires the reasoning extra or a NAR binary. An opt-in
integration test exercises the real pymdp engine when
``KAINE_NOUS_RUN_REAL_PYMDP=1`` and the extra is installed.
"""
from __future__ import annotations

import os
from datetime import datetime, timezone

import pytest

from kaine.bus import Event
from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.cycle.types import WorkspaceSnapshot
from kaine.modules.nous import FakeEngine, Nous


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield bus
    await bus.close()


def _event(source="soma", type_="soma.report", salience=0.9, eid="e1") -> tuple[str, Event]:
    return eid, Event(
        source=source,
        type=type_,
        payload={},
        salience=salience,
        timestamp=datetime.now(timezone.utc),
    )


def _snapshot(events=None) -> WorkspaceSnapshot:
    return WorkspaceSnapshot(tick_index=0, selected_events=events or [], inhibited=False)


async def _read(bus: AsyncBus, type_: str):
    entries = await bus.read("nous.out", last_id="0")
    return [e for _, e in entries if e.type == type_]


@pytest.mark.asyncio
async def test_empty_snapshot_is_noop(bus: AsyncBus):
    fake = FakeEngine()
    nous = Nous(bus, engine=fake)
    await nous.initialize()
    try:
        await nous.on_workspace(_snapshot())
        assert fake.steps_called == 0
        entries = await bus.read("nous.out", last_id="0")
        assert entries == []
    finally:
        await nous.shutdown()


@pytest.mark.asyncio
async def test_broadcast_publishes_preserved_belief_shape(bus: AsyncBus):
    posterior = [
        [1.0, 0.0, 0.0, 0.0],
        [0.95, 0.025, 0.025],  # most certain perceptual factor
        [0.25, 0.25, 0.25, 0.25],
        [0.25, 0.25, 0.25, 0.25],
    ]
    fake = FakeEngine(posteriors=[posterior])
    nous = Nous(bus, engine=fake)
    await nous.initialize()
    try:
        await nous.on_workspace(_snapshot([_event()]))
        beliefs = await _read(bus, "nous.belief")
        assert len(beliefs) == 1
        payload = beliefs[0].payload
        # PRESERVED contract shape.
        assert set(["statement", "kind", "frequency", "confidence"]).issubset(payload)
        assert payload["kind"] == "belief"
        assert isinstance(payload["statement"], str)
        assert 0.0 <= payload["confidence"] <= 1.0
        # High-certainty factor -> confidence well above 0.
        assert payload["confidence"] > 0.5
    finally:
        await nous.shutdown()


@pytest.mark.asyncio
async def test_broadcast_publishes_policy_event(bus: AsyncBus):
    fake = FakeEngine(policy_efe=[0.9, 0.5, 0.05, 0.7])
    nous = Nous(bus, engine=fake)
    await nous.initialize()
    try:
        await nous.on_workspace(_snapshot([_event()]))
        policies = await _read(bus, "nous.policy")
        assert len(policies) == 1
        payload = policies[0].payload
        assert "expected_free_energy" in payload
        assert payload["policy"] == "request_speak"  # lowest EFE
        assert payload["horizon"] == 1
    finally:
        await nous.shutdown()


@pytest.mark.asyncio
async def test_epistemic_action_emitted_as_intent_act(bus: AsyncBus):
    # request_think (index 1) has the lowest EFE -> a think intent.act.
    fake = FakeEngine(policy_efe=[0.9, 0.05, 0.5, 0.7])
    nous = Nous(bus, engine=fake)
    await nous.initialize()
    try:
        await nous.on_workspace(_snapshot([_event()]))
        intents = await _read(bus, "intent.act")
        assert len(intents) == 1
        payload = intents[0].payload
        assert payload["kind"] == "think"
        # Source is nous; it published an intent, not a direct effector call.
        assert intents[0].source == "nous"
    finally:
        await nous.shutdown()


@pytest.mark.asyncio
async def test_no_op_emits_no_intent(bus: AsyncBus):
    # no_op (index 0) lowest -> belief+policy but NO intent.act.
    fake = FakeEngine(policy_efe=[0.05, 0.5, 0.6, 0.7])
    nous = Nous(bus, engine=fake)
    await nous.initialize()
    try:
        await nous.on_workspace(_snapshot([_event()]))
        intents = await _read(bus, "intent.act")
        assert intents == []
        assert len(await _read(bus, "nous.belief")) == 1
    finally:
        await nous.shutdown()


@pytest.mark.asyncio
async def test_timeout_publishes_nous_timeout(bus: AsyncBus):
    fake = FakeEngine(timeout_on=0)
    nous = Nous(bus, engine=fake)
    await nous.initialize()
    try:
        await nous.on_workspace(_snapshot([_event()]))
        timeouts = await _read(bus, "nous.timeout")
        assert len(timeouts) == 1
        assert timeouts[0].salience == pytest.approx(0.3)
        # Even on timeout it still publishes a belief from the last posterior.
        assert len(await _read(bus, "nous.belief")) == 1
    finally:
        await nous.shutdown()


@pytest.mark.asyncio
async def test_invalid_construction_rejected(bus: AsyncBus):
    with pytest.raises(ValueError):
        Nous(bus, engine=FakeEngine(), baseline_salience=2.0)
    with pytest.raises(ValueError):
        Nous(bus, engine=FakeEngine(), alert_salience=-0.1)


@pytest.mark.asyncio
async def test_serialize_roundtrips_numeric_only(bus: AsyncBus):
    fake = FakeEngine(posteriors=[[[1.0, 0.0], [0.5, 0.5]]])
    nous = Nous(bus, engine=fake)
    await nous.initialize()
    try:
        await nous.on_workspace(_snapshot([_event()]))
        state = nous.serialize()
        assert "posterior" in state
        assert "last_action" in state
        fresh = Nous(bus, engine=FakeEngine())
        fresh.deserialize(state)
        assert fresh._last_action == nous._last_action
    finally:
        await nous.shutdown()


# --------------------------------------------------------------------------
# Opt-in real-pymdp integration test.
# --------------------------------------------------------------------------


def _real_pymdp_enabled() -> bool:
    if os.environ.get("KAINE_NOUS_RUN_REAL_PYMDP") != "1":
        return False
    try:
        import jax  # noqa: F401
        import pymdp  # noqa: F401

        return True
    except Exception:
        return False


@pytest.mark.asyncio
@pytest.mark.skipif(
    not _real_pymdp_enabled(),
    reason="set KAINE_NOUS_RUN_REAL_PYMDP=1 and install the reasoning extra",
)
async def test_real_pymdp_module_publishes_belief_and_policy(bus: AsyncBus):
    from kaine.modules.nous.engine import PymdpEngine

    engine = PymdpEngine(efe_timeout_ms=10_000.0)
    nous = Nous(bus, engine=engine)
    await nous.initialize()
    try:
        await nous.on_workspace(_snapshot([_event(salience=0.95)]))
        assert len(await _read(bus, "nous.belief")) == 1
        assert len(await _read(bus, "nous.policy")) == 1
    finally:
        await nous.shutdown()


# --------------------------------------------------------------------------
# H1: inference crash → nous.error published; no fabricated belief/policy
# --------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_inference_crash_publishes_nous_error(bus: AsyncBus):
    """On a non-timeout engine crash, nous.error is published."""
    fake = FakeEngine(error_on=0)
    nous = Nous(bus, engine=fake)
    await nous.initialize()
    try:
        await nous.on_workspace(_snapshot([_event()]))
        errors = await _read(bus, "nous.error")
        assert len(errors) == 1
        payload = errors[0].payload
        assert "error_reason" in payload
        assert payload["error_reason"] != ""
    finally:
        await nous.shutdown()


@pytest.mark.asyncio
async def test_inference_crash_suppresses_belief_and_policy(bus: AsyncBus):
    """On an engine crash, belief and policy are NOT published (stale priors
    must not be re-broadcast as a fresh computation)."""
    fake = FakeEngine(error_on=0)
    nous = Nous(bus, engine=fake)
    await nous.initialize()
    try:
        await nous.on_workspace(_snapshot([_event()]))
        # No fabricated belief or policy this cycle.
        assert await _read(bus, "nous.belief") == []
        assert await _read(bus, "nous.policy") == []
        # The diagnostic IS emitted.
        assert len(await _read(bus, "nous.error")) == 1
    finally:
        await nous.shutdown()


@pytest.mark.asyncio
async def test_inference_crash_after_good_cycle_does_not_republish_stale(bus: AsyncBus):
    """A crash on cycle N+1 must not republish the N-th (stale) belief."""
    p1 = [[1.0, 0.0, 0.0, 0.0], [0.9, 0.05, 0.05], [0.25] * 4, [0.25] * 4]
    fake = FakeEngine(posteriors=[p1], error_on=1)
    nous = Nous(bus, engine=fake)
    await nous.initialize()
    try:
        # Cycle 0: good.
        await nous.on_workspace(_snapshot([_event()]))
        assert len(await _read(bus, "nous.belief")) == 1
        # Cycle 1: crash — should add a nous.error but NOT a second belief.
        await nous.on_workspace(_snapshot([_event()]))
        beliefs = await _read(bus, "nous.belief")
        errors = await _read(bus, "nous.error")
        assert len(beliefs) == 1   # still only the one from cycle 0
        assert len(errors) == 1    # the crash diagnostic
    finally:
        await nous.shutdown()


@pytest.mark.asyncio
async def test_timeout_still_publishes_belief_not_error(bus: AsyncBus):
    """Timeout is a planned degradation: belief/policy still published; no
    nous.error event."""
    fake = FakeEngine(timeout_on=0)
    nous = Nous(bus, engine=fake)
    await nous.initialize()
    try:
        await nous.on_workspace(_snapshot([_event()]))
        # Timeout: nous.timeout + belief + policy; but no error.
        assert len(await _read(bus, "nous.timeout")) == 1
        assert len(await _read(bus, "nous.belief")) == 1
        assert len(await _read(bus, "nous.policy")) == 1
        assert await _read(bus, "nous.error") == []
    finally:
        await nous.shutdown()
