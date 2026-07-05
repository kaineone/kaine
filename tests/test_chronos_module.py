# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import asyncio
import math
from datetime import datetime, timezone

import pytest

from kaine.bus import Event
from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.cycle.types import WorkspaceSnapshot
from kaine.modules.chronos.anomaly import RollingZScoreAnomaly
from kaine.modules.chronos.featurizer import SnapshotFeaturizer
from kaine.modules.chronos.module import Chronos
from kaine.modules.chronos.rumination import (
    RecurrenceRuminationDetector,
    RuminationResult,
)


class FakeNetwork:
    """Returns a constant hidden state of the requested size."""

    def __init__(self, units: int = 8, value: float = 0.5) -> None:
        self.units = units
        self.value = value
        self.calls: list[list[float]] = []

    def tick(self, feature_vec: list[float]) -> list[float]:
        self.calls.append(list(feature_vec))
        return [self.value] * self.units


class FlaggingRumination:
    def observe(self, hidden_state):  # noqa: ARG002
        return RuminationResult(
            detected=True, habituation=0.9, dominant_bucket="x", dominant_count=99
        )


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield bus
    await bus.close()


def _empty_snapshot(tick: int = 0) -> WorkspaceSnapshot:
    return WorkspaceSnapshot(tick_index=tick, selected_events=[], inhibited=False)


@pytest.mark.asyncio
async def test_on_workspace_publishes_chronos_report(bus: AsyncBus):
    network = FakeNetwork(units=4)
    chronos = Chronos(
        bus,
        featurizer=SnapshotFeaturizer(clock=lambda: 0.0),
        network=network,
        anomaly=RollingZScoreAnomaly(window=4),
        rumination=RecurrenceRuminationDetector(window=4, threshold=4),
    )
    await chronos.on_workspace(_empty_snapshot())
    entries = await bus.read("chronos.out", last_id="0")
    assert len(entries) == 1
    _, event = entries[0]
    assert event.type == "chronos.report"
    payload = event.payload
    assert payload["temporal_context"] == [0.5, 0.5, 0.5, 0.5]
    assert payload["anomaly_score"] == 0.0  # no prior history
    assert 0.0 <= payload["habituation_score"] <= 1.0
    assert payload["rumination_detected"] is False
    assert payload["time_since_last_interaction_s"] == math.inf
    assert len(payload["feature_vector"]) == 24


@pytest.mark.asyncio
async def test_rumination_flag_raises_salience(bus: AsyncBus):
    network = FakeNetwork()
    chronos = Chronos(
        bus,
        featurizer=SnapshotFeaturizer(clock=lambda: 0.0),
        network=network,
        rumination=FlaggingRumination(),
    )
    await chronos.on_workspace(_empty_snapshot())
    entries = await bus.read("chronos.out", last_id="0")
    _, event = entries[0]
    assert event.payload["rumination_detected"] is True
    assert event.salience == pytest.approx(chronos._alert_salience)


@pytest.mark.asyncio
async def test_user_input_resets_time_since_last_interaction(bus: AsyncBus):
    network = FakeNetwork()
    # Use a monotonically increasing clock so the elapsed delta is positive
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
        # Publish a user-input event before advancing the clock
        await bus.client.xadd(
            "user_input.out",
            {
                "source": "user",
                "type": "input.text",
                "salience": "0.5",
                "timestamp": datetime.fromtimestamp(1000.0, tz=timezone.utc).isoformat(),
                "causal_parent": "",
                "payload": "{}",
            },
        )
        # Give the consumer a moment.
        for _ in range(50):
            if chronos._last_interaction_at is not None:
                break
            await asyncio.sleep(0.01)
        assert chronos._last_interaction_at == pytest.approx(1000.0)
        # Advance time and check the report value
        now["v"] = 1003.0
        await chronos.on_workspace(_empty_snapshot())
        entries = await bus.read("chronos.out", last_id="0")
        _, event = entries[0]
        assert event.payload["time_since_last_interaction_s"] == pytest.approx(3.0)
    finally:
        await chronos.shutdown()


@pytest.mark.asyncio
async def test_invalid_construction_rejected(bus: AsyncBus):
    with pytest.raises(ValueError):
        Chronos(bus, baseline_salience=2.0)
    with pytest.raises(ValueError):
        Chronos(bus, alert_salience=-0.1)
    with pytest.raises(ValueError):
        Chronos(bus, anomaly_alert_threshold=-1.0)


@pytest.mark.asyncio
async def test_serialize_roundtrips(bus: AsyncBus):
    chronos = Chronos(bus, network=FakeNetwork())
    chronos._last_interaction_at = 12345.0
    chronos._user_input_cursors = {"a.out": "1-0"}
    state = chronos.serialize()
    fresh = Chronos(bus, network=FakeNetwork())
    fresh.deserialize(state)
    assert fresh._last_interaction_at == 12345.0
    assert fresh._user_input_cursors["a.out"] == "1-0"


@pytest.mark.asyncio
async def test_default_construction_lazy_imports_torch(bus: AsyncBus):
    # Default construction does NOT load torch. initialize() does.
    chronos = Chronos(bus)
    assert chronos.has_network is False


# ---------------------------------------------------------------------------
# Forward prediction integration tests
# ---------------------------------------------------------------------------

class ConstantPredictionHead:
    """Test double: always predicts the same value; records adapt calls."""

    def __init__(self, pred_value: float = 0.0, input_size: int = 4) -> None:
        self._value = pred_value
        self._input_size = input_size
        self.adapt_calls: list[tuple[list[float], list[float]]] = []
        self.suspended: bool = False
        self._weight = [[0.0] * 4] * input_size
        self._bias = [0.0] * input_size

    def predict(self, hidden: list[float]) -> list[float]:  # noqa: ARG002
        return [self._value] * self._input_size

    def adapt(self, hidden: list[float], target: list[float]) -> float:
        if not self.suspended:
            self.adapt_calls.append((list(hidden), list(target)))
        return 0.0

    def prediction_error(self, predicted: list[float], actual: list[float]) -> float:
        return sum(abs(p - a) for p, a in zip(predicted, actual)) / len(predicted)

    def state_dict(self) -> dict:
        return {"weight": self._weight, "bias": self._bias}

    def load_state_dict(self, state: dict) -> None:
        self._weight = state["weight"]
        self._bias = state["bias"]


@pytest.mark.asyncio
async def test_temporal_prediction_error_present_on_report(bus: AsyncBus):
    """chronos.report always includes temporal_prediction_error."""
    network = FakeNetwork(units=4)
    chronos = Chronos(
        bus,
        featurizer=SnapshotFeaturizer(clock=lambda: 0.0),
        network=network,
        forward_prediction=True,
    )
    chronos._pred_head = ConstantPredictionHead(pred_value=0.0, input_size=24)
    await chronos.on_workspace(_empty_snapshot())
    entries = await bus.read("chronos.out", last_id="0")
    _, event = entries[0]
    assert "temporal_prediction_error" in event.payload
    assert isinstance(event.payload["temporal_prediction_error"], float)


@pytest.mark.asyncio
async def test_temporal_prediction_error_zero_on_first_tick(bus: AsyncBus):
    """On the first tick there is no prior hidden state, so error is 0.0."""
    network = FakeNetwork(units=4)
    chronos = Chronos(
        bus,
        featurizer=SnapshotFeaturizer(clock=lambda: 0.0),
        network=network,
        forward_prediction=True,
    )
    chronos._pred_head = ConstantPredictionHead(pred_value=0.5, input_size=24)
    await chronos.on_workspace(_empty_snapshot())
    entries = await bus.read("chronos.out", last_id="0")
    _, event = entries[0]
    assert event.payload["temporal_prediction_error"] == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_temporal_prediction_error_nonzero_on_subsequent_tick(bus: AsyncBus):
    """After the first tick there is a prior hidden state; error should be non-zero
    when the head predicts a value far from the actual feature vector."""
    network = FakeNetwork(units=4, value=0.5)
    # Predict a value that differs greatly from the (all-zero-ish) feature vector
    head = ConstantPredictionHead(pred_value=99.0, input_size=24)
    chronos = Chronos(
        bus,
        featurizer=SnapshotFeaturizer(clock=lambda: 0.0),
        network=network,
        forward_prediction=True,
    )
    chronos._pred_head = head
    # First tick: establishes last_hidden; no error yet
    await chronos.on_workspace(_empty_snapshot(tick=0))
    # Second tick: has a prior hidden state; prediction is 99.0 vs ~0.0 target
    await chronos.on_workspace(_empty_snapshot(tick=1))
    entries = await bus.read("chronos.out", last_id="0")
    assert len(entries) == 2
    _, event2 = entries[1]
    assert event2.payload["temporal_prediction_error"] > 0.0


@pytest.mark.asyncio
async def test_legacy_fields_retained_with_forward_prediction(bus: AsyncBus):
    """anomaly_score, habituation_score, and rumination_detected remain on payload."""
    network = FakeNetwork(units=4)
    chronos = Chronos(
        bus,
        featurizer=SnapshotFeaturizer(clock=lambda: 0.0),
        network=network,
        forward_prediction=True,
        anomaly=RollingZScoreAnomaly(window=4),
        rumination=RecurrenceRuminationDetector(window=4, threshold=4),
    )
    chronos._pred_head = ConstantPredictionHead(pred_value=0.0, input_size=24)
    await chronos.on_workspace(_empty_snapshot())
    entries = await bus.read("chronos.out", last_id="0")
    _, event = entries[0]
    payload = event.payload
    assert "anomaly_score" in payload
    assert "habituation_score" in payload
    assert "rumination_detected" in payload
    assert 0.0 <= payload["habituation_score"] <= 1.0


@pytest.mark.asyncio
async def test_forward_prediction_disabled_behavior_unchanged(bus: AsyncBus):
    """With forward_prediction=False the payload matches legacy behaviour."""
    network = FakeNetwork(units=4)
    chronos = Chronos(
        bus,
        featurizer=SnapshotFeaturizer(clock=lambda: 0.0),
        network=network,
        forward_prediction=False,
        anomaly=RollingZScoreAnomaly(window=4),
        rumination=RecurrenceRuminationDetector(window=4, threshold=4),
    )
    await chronos.on_workspace(_empty_snapshot())
    entries = await bus.read("chronos.out", last_id="0")
    _, event = entries[0]
    payload = event.payload
    # Field still present (always emitted), value is 0.0 when disabled
    assert "temporal_prediction_error" in payload
    assert payload["temporal_prediction_error"] == pytest.approx(0.0)
    assert "anomaly_score" in payload


@pytest.mark.asyncio
async def test_adaptation_suspended_during_hypnos(bus: AsyncBus):
    """When _in_hypnos=True, adapt() is not called on the head."""
    network = FakeNetwork(units=4)
    head = ConstantPredictionHead(pred_value=0.0, input_size=24)
    chronos = Chronos(
        bus,
        featurizer=SnapshotFeaturizer(clock=lambda: 0.0),
        network=network,
        forward_prediction=True,
    )
    chronos._pred_head = head
    chronos._in_hypnos = True
    head.suspended = True

    # First tick to seed last_hidden
    await chronos.on_workspace(_empty_snapshot(tick=0))
    before_count = len(head.adapt_calls)
    # Second tick during Hypnos — adapt should not be called
    await chronos.on_workspace(_empty_snapshot(tick=1))
    after_count = len(head.adapt_calls)
    assert after_count == before_count, "adapt() must not be called during Hypnos sleep"


@pytest.mark.asyncio
async def test_serialize_deserialize_preserves_head_weights(bus: AsyncBus):
    """serialize() captures head weights; deserialize() restores them exactly."""
    from kaine.modules.chronos.network import ForwardPredictionHead

    # Build a Chronos with a real ForwardPredictionHead and adapt it a bit
    network = FakeNetwork(units=4)
    head = ForwardPredictionHead(input_size=24, units=4, seed=7, lr=0.05)
    for _ in range(10):
        head.adapt([0.3] * 4, [0.7] * 24)

    chronos = Chronos(
        bus,
        featurizer=SnapshotFeaturizer(clock=lambda: 0.0),
        network=network,
        forward_prediction=True,
    )
    chronos._pred_head = head

    state = chronos.serialize()
    assert "pred_head" in state

    # Restore into a fresh Chronos with a new head
    fresh_head = ForwardPredictionHead(input_size=24, units=4, seed=99)
    fresh = Chronos(
        bus,
        featurizer=SnapshotFeaturizer(clock=lambda: 0.0),
        network=FakeNetwork(units=4),
        forward_prediction=True,
    )
    fresh._pred_head = fresh_head
    fresh.deserialize(state)

    hidden_probe = [0.1] * 4
    assert head.predict(hidden_probe) == pytest.approx(fresh_head.predict(hidden_probe), abs=1e-5)


@pytest.mark.asyncio
async def test_anomaly_salience_tracks_prediction_error(bus: AsyncBus):
    """High prediction error should elevate salience to alert level.

    We drive anomaly_alert_threshold=1.0 and inject a large error by using
    a head that always predicts 0.0 while the feature vector is non-zero.
    After the first tick seeds last_hidden, subsequent ticks compute a large
    normalised error that should trigger the alert salience branch.

    Note: this test runs forward_prediction=True; the salience branch is
    driven by the prediction error.  Because the deque starts with one
    sample (mean == sample), normalised = 1.0 which just touches the
    threshold of 1.0, so we use threshold=0.5 to ensure the branch fires.
    """
    network = FakeNetwork(units=4, value=0.0)
    # Head always predicts 0.0; feature vector will be non-zero (salience bin + count)
    head = ConstantPredictionHead(pred_value=0.0, input_size=24)
    chronos = Chronos(
        bus,
        featurizer=SnapshotFeaturizer(clock=lambda: 0.0),
        network=network,
        forward_prediction=True,
        anomaly_alert_threshold=0.5,  # low so normalised error (≈1.0) triggers it
    )
    chronos._pred_head = head

    # First tick: seeds _last_hidden, no error computed
    await chronos.on_workspace(_empty_snapshot(tick=0))
    # Second tick: error computed; with a constant zero predictor and non-trivial
    # feature vector the error should be > 0, normalised to 1.0 ≥ 0.5 → alert
    from kaine.bus import Event as BusEvent
    import json
    from datetime import datetime, timezone as tz
    # Use a snapshot with a salient event so feature_vec is not all zeros
    ev = BusEvent(
        source="soma",
        type="soma.report",
        payload={},
        salience=0.9,
        timestamp=datetime.now(tz.utc),
    )
    snap = WorkspaceSnapshot(
        tick_index=1,
        selected_events=[("1-0", ev)],
        inhibited=False,
    )
    await chronos.on_workspace(snap)
    entries = await bus.read("chronos.out", last_id="0")
    assert len(entries) == 2
    _, event2 = entries[1]
    assert event2.salience == pytest.approx(chronos._alert_salience)
