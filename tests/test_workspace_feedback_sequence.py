# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import pytest

from kaine.boot.errors import ConfigurationError
from kaine.boot.factories.sequence import make_sequence
from kaine.boot.registry import construct_module
from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.cycle.types import WorkspaceSnapshot
from kaine.modules.registry import ModuleRegistry
from kaine.modules.sequence.featurizer import SnapshotFeaturizer
from kaine.modules.sequence.module import Sequence


class FakeNetwork:
    """A tiny stand-in network that exposes a fixed hidden width."""

    def __init__(self, units: int = 4, value: float = 0.0) -> None:
        self.units = units
        self.value = value

    def tick(self, feature_vec, timespan: float | None = None):
        return [self.value] * self.units


class ConstantPredictionHead:
    """A deterministic prediction head that always returns the same vector."""

    def __init__(self, pred_value: float, input_size: int = 24) -> None:
        self.pred_value = float(pred_value)
        self.input_size = int(input_size)
        self.suspended = False

    def predict(self, hidden):
        return [self.pred_value] * self.input_size

    def prediction_error(self, predicted, target):
        n = len(predicted)
        if n == 0:
            return 0.0
        return sum((p - t) ** 2 for p, t in zip(predicted, target)) / n

    def adapt(self, hidden, target) -> None:
        pass


def _empty_snapshot(tick: int = 0) -> WorkspaceSnapshot:
    return WorkspaceSnapshot(tick_index=tick, selected_events=[], inhibited=False)


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield bus
    await bus.close()


async def _read_reports(bus: AsyncBus) -> list[dict]:
    entries = await bus.read("sequence.out", last_id="0")
    return [event.payload for _, event in entries]


@pytest.mark.asyncio
async def test_publish_next_prediction_off_by_default(bus: AsyncBus):
    """Without the flag, sequence.report is bit-for-bit unchanged."""
    head = ConstantPredictionHead(pred_value=0.0, input_size=24)
    sequence_default = Sequence(
        bus,
        featurizer=SnapshotFeaturizer(clock=lambda: 0.0),
        network=FakeNetwork(units=4),
        forward_prediction=True,
    )
    sequence_default._pred_head = head

    sequence_explicit = Sequence(
        bus,
        featurizer=SnapshotFeaturizer(clock=lambda: 0.0),
        network=FakeNetwork(units=4),
        forward_prediction=True,
        publish_next_prediction=False,
    )
    sequence_explicit._pred_head = ConstantPredictionHead(pred_value=0.0, input_size=24)

    for i in range(3):
        await sequence_default.on_workspace(_empty_snapshot(tick=i))
    for i in range(3):
        await sequence_explicit.on_workspace(_empty_snapshot(tick=i))

    payloads = await _read_reports(bus)
    assert len(payloads) == 6
    default_reports = payloads[:3]
    explicit_reports = payloads[3:]

    for payload in default_reports + explicit_reports:
        assert "predicted_next_feature_vector" not in payload

    for default_payload, explicit_payload in zip(default_reports, explicit_reports):
        assert default_payload == explicit_payload


@pytest.mark.asyncio
async def test_publish_next_prediction_on_adds_key(bus: AsyncBus):
    """With the flag, every report carries the predicted next feature vector."""
    value = 0.5
    units = 4
    head = ConstantPredictionHead(pred_value=7.0, input_size=24)
    seq_on = Sequence(
        bus,
        featurizer=SnapshotFeaturizer(clock=lambda: 0.0),
        network=FakeNetwork(units=units, value=value),
        forward_prediction=True,
        publish_next_prediction=True,
    )
    seq_on._pred_head = head

    seq_off = Sequence(
        bus,
        featurizer=SnapshotFeaturizer(clock=lambda: 0.0),
        network=FakeNetwork(units=units, value=value),
        forward_prediction=True,
        publish_next_prediction=False,
    )
    seq_off._pred_head = ConstantPredictionHead(pred_value=7.0, input_size=24)

    for i in range(1, 4):
        await seq_on.on_workspace(_empty_snapshot(tick=i))
        expected = seq_on._pred_head.predict([value] * units)
        entries = await bus.read("sequence.out", last_id="0")
        _, event = entries[-1]
        payload = event.payload

        assert "predicted_next_feature_vector" in payload
        vector = payload["predicted_next_feature_vector"]
        assert isinstance(vector, list)
        assert len(vector) == 24
        assert all(isinstance(x, float) and abs(x) < float("inf") for x in vector)
        assert vector == expected

        await seq_off.on_workspace(_empty_snapshot(tick=i))
        entries_off = await bus.read("sequence.out", last_id="0")
        _, event_off = entries_off[-1]
        off_payload = event_off.payload

        on_without_key = dict(payload)
        on_without_key.pop("predicted_next_feature_vector")
        assert on_without_key == off_payload


@pytest.mark.asyncio
async def test_publish_next_prediction_requires_forward_prediction(bus: AsyncBus):
    """The extra key is only produced when the prediction head is active."""
    sequence = Sequence(
        bus,
        featurizer=SnapshotFeaturizer(clock=lambda: 0.0),
        network=FakeNetwork(units=4),
        forward_prediction=False,
        publish_next_prediction=True,
    )

    for i in range(3):
        await sequence.on_workspace(_empty_snapshot(tick=i))

    payloads = await _read_reports(bus)
    assert len(payloads) == 3
    for payload in payloads:
        assert "predicted_next_feature_vector" not in payload


@pytest.mark.asyncio
async def test_factory_enables_publish_flag_from_workspace_feedback(bus: AsyncBus):
    """make_sequence pops [workspace.feedback] and sets publish_next_prediction."""
    section = {
        "forward_prediction": True,
        "workspace_feedback": {"enabled": True, "arm": "full"},
    }
    seq = make_sequence(bus, section)
    assert isinstance(seq, Sequence)
    assert seq._publish_next_prediction is True
    assert "workspace_feedback" in section  # caller's dict was copied, not mutated

    off_section = {"forward_prediction": True, "workspace_feedback": {}}
    seq_off = make_sequence(bus, off_section)
    assert seq_off._publish_next_prediction is False
    assert "workspace_feedback" in off_section

    missing_section = {"forward_prediction": True}
    seq_missing = make_sequence(bus, missing_section)
    assert seq_missing._publish_next_prediction is False

    bad_section = {
        "forward_prediction": True,
        "workspace_feedback": {"enabled": True, "arm": "bogus"},
    }
    with pytest.raises(ConfigurationError):
        make_sequence(bus, bad_section)


@pytest.mark.asyncio
async def test_registry_injects_feedback_section_for_sequence(bus: AsyncBus):
    """construct_module passes [workspace.feedback] into the sequence factory."""
    kaine_config = {
        "sequence": {"forward_prediction": True},
        "workspace": {"feedback": {"enabled": True, "arm": "head_only"}},
    }
    seq = construct_module(
        "sequence", bus, kaine_config, registry=ModuleRegistry()
    )
    assert isinstance(seq, Sequence)
    assert seq._publish_next_prediction is True

    off_config = {"sequence": {"forward_prediction": True}}
    seq_off = construct_module(
        "sequence", bus, off_config, registry=ModuleRegistry()
    )
    assert isinstance(seq_off, Sequence)
    assert seq_off._publish_next_prediction is False
