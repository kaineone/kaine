# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for Nous proposals and taken-action feedback."""

from __future__ import annotations

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


def _event(source="soma", type_="soma.report", salience=0.9, eid="e1"):
    return eid, Event(
        source=source,
        type=type_,
        payload={},
        salience=salience,
        timestamp=datetime.now(timezone.utc),
    )


def _snapshot(events=None):
    return WorkspaceSnapshot(tick_index=0, selected_events=events or [], inhibited=False)


async def _read(bus: AsyncBus, type_: str):
    entries = await bus.read("nous.out", last_id="0")
    return [e for _, e in entries if e.type == type_]


class _RecordingFakeEngine(FakeEngine):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.recorded: list[int] = []

    def record_taken_action(self, action_index: int) -> None:
        self.recorded.append(int(action_index))


class _VaryingFakeEngine(FakeEngine):
    def __init__(self, policy_efe_vectors, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._policy_efe_vectors = list(policy_efe_vectors)
        self._step_count = 0

    def step(self, snapshot):
        if self._step_count < len(self._policy_efe_vectors):
            self._policy_efe = self._policy_efe_vectors[self._step_count]
        self._step_count += 1
        return super().step(snapshot)


class _RecordingVaryingFakeEngine(_RecordingFakeEngine, _VaryingFakeEngine):
    """Varying fake engine that also records record_taken_action calls."""


class _TimedOutOnEngine(_RecordingFakeEngine):
    """Recording fake engine that marks a chosen step call as timed_out."""

    def __init__(self, timed_out_on: int, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._timed_out_on = timed_out_on
        self._internal_step = 0

    def step(self, snapshot):
        self._internal_step += 1
        result = super().step(snapshot)
        if self._internal_step == self._timed_out_on:
            result.timed_out = True
        return result


async def _publish_outcome(bus: AsyncBus, proposal_id: str, realized: bool, reason: str = "realized"):
    await bus.publish(
        Event(
            source="volition_feedback",
            type="volition.proposal_outcome",
            payload={"proposal_id": proposal_id, "realized": realized, "reason": reason},
            salience=0.5,
            timestamp=datetime.now(timezone.utc),
        )
    )


async def _publish_rest_request(bus: AsyncBus, proposal_id: str, accepted: bool, reason: str = ""):
    await bus.publish(
        Event(
            source="hypnos",
            type="hypnos.rest_request",
            payload={"proposal_id": proposal_id, "accepted": accepted, "reason": reason},
            salience=0.5,
            timestamp=datetime.now(timezone.utc),
        )
    )


@pytest.mark.asyncio
async def test_request_speak_gives_speak_proposal(bus: AsyncBus):
    fake = FakeEngine(policy_efe=[0.9, 0.5, 0.05, 0.7])
    nous = Nous(bus, engine=fake)
    await nous.initialize()
    try:
        await nous.on_workspace(_snapshot([_event()]))
        proposals = await _read(bus, "nous.proposal")
        assert len(proposals) == 1
        p = proposals[0].payload
        assert p["kind"] == "speak"
        assert p["action"] == "request_speak"
        assert "proposal_id" in p
        assert isinstance(p["proposal_id"], str)
        assert "step" in p
        assert isinstance(p["step"], int)
        assert 0.0 <= p["preference"] <= 1.0
        assert await _read(bus, "intent.act") == []
    finally:
        await nous.shutdown()


@pytest.mark.asyncio
async def test_speak_proposal_salience_grows_with_preference(bus: AsyncBus):
    fake = _VaryingFakeEngine([
        [5.0, 5.0, 0.0, 5.0],    # clear winner -> high preference
        [0.12, 0.11, 0.0, 0.10],  # closer race -> lower preference
    ])
    nous = Nous(bus, engine=fake, baseline_salience=0.4, alert_salience=0.8)
    await nous.initialize()
    try:
        await nous.on_workspace(_snapshot([_event()]))
        await nous.on_workspace(_snapshot([_event()]))
        proposals = await _read(bus, "nous.proposal")
        assert len(proposals) == 2
        saliences = [p.salience for p in proposals]
        for s in saliences:
            assert 0.4 <= s <= 0.8
        assert saliences[0] > saliences[1]
    finally:
        await nous.shutdown()


@pytest.mark.asyncio
async def test_request_maintenance_gives_rest_proposal(bus: AsyncBus):
    fake = FakeEngine(policy_efe=[0.9, 0.5, 0.7, 0.05])
    nous = Nous(bus, engine=fake)
    await nous.initialize()
    try:
        await nous.on_workspace(_snapshot([_event()]))
        proposals = await _read(bus, "nous.proposal")
        assert len(proposals) == 1
        p = proposals[0].payload
        assert p["kind"] == "rest"
        assert p["action"] == "request_maintenance"
        assert await _read(bus, "intent.act") == []
    finally:
        await nous.shutdown()


@pytest.mark.asyncio
async def test_no_op_publishes_no_proposal(bus: AsyncBus):
    fake = FakeEngine(policy_efe=[0.05, 0.5, 0.6, 0.7])
    nous = Nous(bus, engine=fake)
    await nous.initialize()
    try:
        await nous.on_workspace(_snapshot([_event()]))
        proposals = await _read(bus, "nous.proposal")
        assert proposals == []
    finally:
        await nous.shutdown()


@pytest.mark.asyncio
async def test_realized_true_records_proposed_action(bus: AsyncBus):
    fake = _RecordingFakeEngine(policy_efe=[0.9, 0.5, 0.05, 0.7])
    nous = Nous(bus, engine=fake)
    await nous.initialize()
    try:
        await nous.on_workspace(_snapshot([_event()]))
        proposals = await _read(bus, "nous.proposal")
        pid = proposals[0].payload["proposal_id"]
        await _publish_outcome(bus, pid, True)
        await nous.on_workspace(_snapshot([_event()]))
        speak_index = fake.actions.index("request_speak")
        no_op_index = fake.actions.index("no_op")
        # record_taken_action is now called at the start of every tick.
        assert fake.recorded == [no_op_index, speak_index]
    finally:
        await nous.shutdown()


@pytest.mark.asyncio
async def test_realized_false_records_no_op(bus: AsyncBus):
    fake = _RecordingFakeEngine(policy_efe=[0.9, 0.5, 0.05, 0.7])
    nous = Nous(bus, engine=fake)
    await nous.initialize()
    try:
        await nous.on_workspace(_snapshot([_event()]))
        proposals = await _read(bus, "nous.proposal")
        pid = proposals[0].payload["proposal_id"]
        await _publish_outcome(bus, pid, False, reason="in_flight")
        await nous.on_workspace(_snapshot([_event()]))
        no_op_index = fake.actions.index("no_op")
        # record_taken_action is now called at the start of every tick.
        assert fake.recorded == [no_op_index, no_op_index]
    finally:
        await nous.shutdown()


@pytest.mark.asyncio
async def test_no_outcome_records_no_op(bus: AsyncBus):
    fake = _RecordingFakeEngine(policy_efe=[0.9, 0.5, 0.05, 0.7])
    nous = Nous(bus, engine=fake)
    await nous.initialize()
    try:
        await nous.on_workspace(_snapshot([_event()]))
        await nous.on_workspace(_snapshot([_event()]))
        no_op_index = fake.actions.index("no_op")
        # record_taken_action is now called at the start of every tick.
        assert fake.recorded == [no_op_index, no_op_index]
    finally:
        await nous.shutdown()


@pytest.mark.asyncio
async def test_outcome_for_older_proposal_increments_unknown_outcomes(bus: AsyncBus):
    fake = _RecordingFakeEngine(policy_efe=[0.9, 0.5, 0.05, 0.7])
    nous = Nous(bus, engine=fake)
    await nous.initialize()
    try:
        await nous.on_workspace(_snapshot([_event()]))
        proposals = await _read(bus, "nous.proposal")
        pid1 = proposals[0].payload["proposal_id"]
        await _publish_outcome(bus, pid1, True)
        await nous.on_workspace(_snapshot([_event()]))
        speak_index = fake.actions.index("request_speak")
        no_op_index = fake.actions.index("no_op")
        # record_taken_action is now called at the start of every tick.
        assert fake.recorded == [no_op_index, speak_index]

        await _publish_outcome(bus, pid1, True)
        await nous.on_workspace(_snapshot([_event()]))
        assert fake.recorded == [no_op_index, speak_index, no_op_index]
        assert nous._unknown_outcomes == 1
    finally:
        await nous.shutdown()


@pytest.mark.asyncio
async def test_drive_actions_false_never_reads_feedback_and_records_no_op(bus: AsyncBus):
    fake = _RecordingFakeEngine(policy_efe=[0.9, 0.5, 0.05, 0.7])
    nous = Nous(bus, engine=fake, drive_actions=False)
    await nous.initialize()
    try:
        await nous.on_workspace(_snapshot([_event()]))
        proposals = await _read(bus, "nous.proposal")
        assert len(proposals) == 1
        pid = proposals[0].payload["proposal_id"]
        await _publish_outcome(bus, pid, True)
        await nous.on_workspace(_snapshot([_event()]))
        no_op_index = fake.actions.index("no_op")
        # With drive_actions=False the taken action is always no_op, every tick.
        assert fake.recorded == [no_op_index, no_op_index]
    finally:
        await nous.shutdown()


@pytest.mark.asyncio
async def test_first_boot_cursor_ignores_pre_boot_outcome(bus: AsyncBus):
    fake = _RecordingFakeEngine(policy_efe=[0.9, 0.5, 0.05, 0.7])
    await _publish_outcome(bus, "pre-boot-id", True)
    nous = Nous(bus, engine=fake)
    await nous.initialize()
    try:
        await nous.on_workspace(_snapshot([_event()]))
        proposals = await _read(bus, "nous.proposal")
        pid = proposals[0].payload["proposal_id"]
        await _publish_outcome(bus, pid, True)
        await nous.on_workspace(_snapshot([_event()]))
        speak_index = fake.actions.index("request_speak")
        no_op_index = fake.actions.index("no_op")
        # record_taken_action is now called at the start of every tick.
        assert fake.recorded == [no_op_index, speak_index]
        assert nous._unknown_outcomes == 0
    finally:
        await nous.shutdown()


@pytest.mark.asyncio
async def test_realized_late_outcome_records_action_at_arrival_tick(bus: AsyncBus):
    """A proposal outcome that arrives after Nous missed its broadcast is learned when it arrives."""
    fake = _RecordingFakeEngine(policy_efe=[0.9, 0.5, 0.05, 0.7])
    nous = Nous(bus, engine=fake)
    await nous.initialize()
    try:
        await nous.on_workspace(_snapshot([_event()]))
        proposals = await _read(bus, "nous.proposal")
        pid = proposals[0].payload["proposal_id"]

        # One full tick passes with no outcome for the original proposal.
        await nous.on_workspace(_snapshot([_event()]))

        # The late outcome finally arrives.
        await _publish_outcome(bus, pid, True)

        # Next tick learns the action that was realized.
        await nous.on_workspace(_snapshot([_event()]))
        speak_index = fake.actions.index("request_speak")
        no_op_index = fake.actions.index("no_op")
        assert fake.recorded == [no_op_index, no_op_index, speak_index]
        assert nous._unknown_outcomes == 0
    finally:
        await nous.shutdown()


@pytest.mark.asyncio
async def test_two_proposals_last_realized_decides_taken_action(bus: AsyncBus):
    """If outcomes for two proposals arrive before one tick, the last realized one wins."""
    fake = _RecordingVaryingFakeEngine([
        [0.9, 0.5, 0.05, 0.7],   # tick 1 -> request_speak (idx 2)
        [0.9, 0.05, 0.5, 0.7],   # tick 2 -> request_think (idx 1)
    ])
    nous = Nous(bus, engine=fake)
    await nous.initialize()
    try:
        await nous.on_workspace(_snapshot([_event()]))
        proposals = await _read(bus, "nous.proposal")
        pid1 = proposals[0].payload["proposal_id"]

        await nous.on_workspace(_snapshot([_event()]))
        proposals = await _read(bus, "nous.proposal")
        pid2 = proposals[-1].payload["proposal_id"]

        # P1 is declined, P2 is realized, both before the next tick.
        await _publish_outcome(bus, pid1, False, reason="declined")
        await _publish_outcome(bus, pid2, True)

        await nous.on_workspace(_snapshot([_event()]))
        think_index = fake.actions.index("request_think")
        no_op_index = fake.actions.index("no_op")
        assert fake.recorded == [no_op_index, no_op_index, think_index]
        assert nous._unknown_outcomes == 0
    finally:
        await nous.shutdown()


@pytest.mark.asyncio
async def test_unknown_proposal_outcome_counts_unknown_and_records_no_op(bus: AsyncBus):
    fake = _RecordingFakeEngine(policy_efe=[0.9, 0.5, 0.05, 0.7])
    nous = Nous(bus, engine=fake)
    await nous.initialize()
    try:
        await nous.on_workspace(_snapshot([_event()]))

        # Outcome for a proposal id Nous never published (e.g. from before restart).
        await _publish_outcome(bus, "unknown-id", True)

        await nous.on_workspace(_snapshot([_event()]))
        no_op_index = fake.actions.index("no_op")
        assert fake.recorded == [no_op_index, no_op_index]
        assert nous._unknown_outcomes == 1
    finally:
        await nous.shutdown()


@pytest.mark.asyncio
async def test_error_step_does_not_insert_extra_no_op(bus: AsyncBus):
    """A failed engine step keeps the realized action pending for the next commit."""
    fake = _RecordingFakeEngine(policy_efe=[0.9, 0.5, 0.05, 0.7], error_on=1)
    nous = Nous(bus, engine=fake)
    await nous.initialize()
    try:
        await nous.on_workspace(_snapshot([_event()]))
        proposals = await _read(bus, "nous.proposal")
        pid = proposals[0].payload["proposal_id"]

        await _publish_outcome(bus, pid, True)

        # This tick applies the realized outcome, then the engine step errors.
        await nous.on_workspace(_snapshot([_event()]))

        # Recovery tick: the pending speak is recorded again and the step commits.
        await nous.on_workspace(_snapshot([_event()]))

        # After a committed step, no pending realized action -> no_op.
        await nous.on_workspace(_snapshot([_event()]))

        speak_index = fake.actions.index("request_speak")
        no_op_index = fake.actions.index("no_op")
        assert fake.recorded == [no_op_index, speak_index, speak_index, no_op_index]
        assert nous._unknown_outcomes == 0
    finally:
        await nous.shutdown()


@pytest.mark.asyncio
async def test_rest_proposal_forwarded_then_accepted(bus: AsyncBus):
    """A forwarded rest proposal is kept until Hypnos accepts it."""
    fake = _RecordingFakeEngine(policy_efe=[0.9, 0.5, 0.7, 0.05])
    nous = Nous(bus, engine=fake)
    await nous.initialize()
    try:
        await nous.on_workspace(_snapshot([_event()]))
        proposals = await _read(bus, "nous.proposal")
        pid = proposals[0].payload["proposal_id"]

        rest_index = fake.actions.index("request_maintenance")
        no_op_index = fake.actions.index("no_op")

        # Volition forwards the rest proposal to Hypnos; not a final outcome.
        await _publish_outcome(bus, pid, False, reason="forwarded")
        await nous.on_workspace(_snapshot([_event()]))
        assert fake.recorded == [no_op_index, no_op_index]
        assert pid in nous._recent_proposals

        # Hypnos accepts the rest request.
        await _publish_rest_request(bus, pid, True, reason="accepted")
        await nous.on_workspace(_snapshot([_event()]))
        assert fake.recorded == [no_op_index, no_op_index, rest_index]
        assert pid not in nous._recent_proposals
    finally:
        await nous.shutdown()


@pytest.mark.asyncio
async def test_rest_proposal_forwarded_then_refused(bus: AsyncBus):
    """A forwarded rest proposal removed on hypnos.rest_request accepted: false."""
    fake = _RecordingFakeEngine(policy_efe=[0.9, 0.5, 0.7, 0.05])
    nous = Nous(bus, engine=fake)
    await nous.initialize()
    try:
        await nous.on_workspace(_snapshot([_event()]))
        proposals = await _read(bus, "nous.proposal")
        pid = proposals[0].payload["proposal_id"]

        no_op_index = fake.actions.index("no_op")

        await _publish_outcome(bus, pid, False, reason="forwarded")
        await nous.on_workspace(_snapshot([_event()]))
        assert fake.recorded == [no_op_index, no_op_index]
        assert pid in nous._recent_proposals

        # Hypnos declines the rest request.
        await _publish_rest_request(bus, pid, False, reason="busy")
        await nous.on_workspace(_snapshot([_event()]))
        assert fake.recorded == [no_op_index, no_op_index, no_op_index]
        assert pid not in nous._recent_proposals

        # A later accepted event for the same id is ignored.
        await _publish_rest_request(bus, pid, True)
        await nous.on_workspace(_snapshot([_event()]))
        assert fake.recorded == [no_op_index, no_op_index, no_op_index, no_op_index]
        assert nous._unknown_outcomes == 0
    finally:
        await nous.shutdown()


@pytest.mark.asyncio
async def test_unknown_rest_request_is_ignored(bus: AsyncBus):
    """A hypnos.rest_request for an unknown id does not affect pending proposals."""
    fake = _RecordingFakeEngine(policy_efe=[0.9, 0.5, 0.7, 0.05])
    nous = Nous(bus, engine=fake)
    await nous.initialize()
    try:
        await nous.on_workspace(_snapshot([_event()]))
        proposals = await _read(bus, "nous.proposal")
        pid = proposals[0].payload["proposal_id"]

        no_op_index = fake.actions.index("no_op")

        await _publish_rest_request(bus, "unknown-id", True)
        await nous.on_workspace(_snapshot([_event()]))
        assert fake.recorded == [no_op_index, no_op_index]
        assert pid in nous._recent_proposals
        assert nous._unknown_outcomes == 0
    finally:
        await nous.shutdown()


@pytest.mark.asyncio
async def test_realized_action_survives_error_step(bus: AsyncBus):
    """A realized action is re-recorded when the step that first sees it errors."""
    fake = _RecordingFakeEngine(policy_efe=[0.9, 0.05, 0.7, 0.5], error_on=1)
    nous = Nous(bus, engine=fake)
    await nous.initialize()
    try:
        await nous.on_workspace(_snapshot([_event()]))
        proposals = await _read(bus, "nous.proposal")
        pid = proposals[0].payload["proposal_id"]

        think_index = fake.actions.index("request_think")
        no_op_index = fake.actions.index("no_op")

        await _publish_outcome(bus, pid, True)

        # The step records the realized think, then the engine errors.
        await nous.on_workspace(_snapshot([_event()]))

        # Next tick re-records the pending think and commits.
        await nous.on_workspace(_snapshot([_event()]))

        # After a committed step there is no pending action.
        await nous.on_workspace(_snapshot([_event()]))

        assert fake.recorded == [no_op_index, think_index, think_index, no_op_index]
    finally:
        await nous.shutdown()


@pytest.mark.asyncio
async def test_realized_action_survives_timeout_step(bus: AsyncBus):
    """A realized action is re-recorded when the step that first sees it times out."""
    fake = _TimedOutOnEngine(2, policy_efe=[0.9, 0.05, 0.7, 0.5])
    nous = Nous(bus, engine=fake)
    await nous.initialize()
    try:
        await nous.on_workspace(_snapshot([_event()]))
        proposals = await _read(bus, "nous.proposal")
        pid = proposals[0].payload["proposal_id"]

        think_index = fake.actions.index("request_think")
        no_op_index = fake.actions.index("no_op")

        await _publish_outcome(bus, pid, True)

        # The step records the realized think, then the engine times out.
        await nous.on_workspace(_snapshot([_event()]))

        # Next tick re-records the pending think and commits.
        await nous.on_workspace(_snapshot([_event()]))

        # After a committed step there is no pending action.
        await nous.on_workspace(_snapshot([_event()]))

        assert fake.recorded == [no_op_index, think_index, think_index, no_op_index]
    finally:
        await nous.shutdown()


@pytest.mark.asyncio
async def test_forwarded_outcome_after_hypnos_refusal_is_not_unknown(bus: AsyncBus):
    """A forwarded rest outcome that arrives after Hypnos refused it is not unknown."""
    fake = _RecordingFakeEngine(policy_efe=[0.9, 0.5, 0.7, 0.05])
    nous = Nous(bus, engine=fake)
    await nous.initialize()
    try:
        await nous.on_workspace(_snapshot([_event()]))
        proposals = await _read(bus, "nous.proposal")
        pid = proposals[0].payload["proposal_id"]

        no_op_index = fake.actions.index("no_op")

        # Hypnos refuses the rest request before Volition's forwarded outcome is read.
        await _publish_rest_request(bus, pid, False, reason="too_soon")
        await nous.on_workspace(_snapshot([_event()]))
        assert fake.recorded == [no_op_index, no_op_index]
        assert pid not in nous._recent_proposals

        # The matching forwarded outcome arrives on the next tick.
        await _publish_outcome(bus, pid, False, reason="forwarded")
        await nous.on_workspace(_snapshot([_event()]))
        assert fake.recorded == [no_op_index, no_op_index, no_op_index]
        assert nous._unknown_outcomes == 0
    finally:
        await nous.shutdown()
