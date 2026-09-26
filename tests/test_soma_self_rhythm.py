import asyncio

import numpy as np
import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.entity_clock import EntityClock
from kaine.modules.soma import AlertResult, Soma


class FakeMetricsReader:
    def __init__(self, metrics: dict[str, float] | None = None) -> None:
        self._metrics = metrics or {"cpu_percent": 10.0, "ram_percent": 20.0}
        self.latencies: list[float] = []
        self.initialized = False
        self.shutdown_called = False

    async def initialize(self) -> None:
        self.initialized = True

    async def shutdown(self) -> None:
        self.shutdown_called = True

    async def read_metrics(self) -> dict[str, float]:
        out = dict(self._metrics)
        if self.latencies:
            out["cycle_latency_avg_ms"] = sum(self.latencies) / len(self.latencies)
        return out

    def update_cycle_latency_sample(self, wall_duration_ms: float) -> None:
        self.latencies.append(float(wall_duration_ms))


class NeverAlertDetector:
    def evaluate(self, metrics: dict[str, float]) -> AlertResult:
        return AlertResult()


class CaptureForwardModel:
    def __init__(self):
        self.captured = None
        self.adaptation_steps = 0
        self._suspended = False

    @property
    def suspended(self):
        return self._suspended

    @suspended.setter
    def suspended(self, value):
        self._suspended = bool(value)

    def step(self, feature_vec):
        self.captured = np.asarray(feature_vec, dtype=float).copy()
        return 0.0

    def prediction_error_to_salience(
        self, prediction_error, baseline_salience, alert_salience, error_window
    ):
        return baseline_salience

    def state_dict(self):
        return {}

    def load_state_dict(self, state):
        pass


class RecordingSelfRhythm:
    def __init__(self, phase=0.0, amplitude=0.25):
        self.steps = []
        self._phase = float(phase)
        self._amplitude = float(amplitude)
        self._serialized = {"kind": "fake_self_rhythm", "phase": self._phase}
        self.deserialized = None

    def step(self, drive, *, external_drive=None):
        self.steps.append((float(drive), external_drive))

    def phase(self):
        return self._phase

    def amplitude(self):
        return self._amplitude

    def serialize(self):
        return dict(self._serialized)

    def deserialize(self, state):
        self.deserialized = state


class RecordingCoalitionOscillator:
    def __init__(self):
        self.steps = []
        self._phase = 0.321

    def step(self, drive):
        self.steps.append(float(drive))

    def phase(self):
        return self._phase

    def set_frequency(self, scale):
        pass

    def serialize(self):
        return {"kind": "coalition_fake"}

    def deserialize(self, state):
        pass


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield bus
    await bus.close()


@pytest.fixture
def base_metrics():
    return {
        "cpu_percent": 10.0,
        "ram_percent": 20.0,
        "cycle_latency_avg_ms": 100.0,
    }


@pytest.mark.asyncio
async def test_feature_vector_receives_self_rhythm_slots(bus, base_metrics):
    rhythm = RecordingSelfRhythm(phase=0.0, amplitude=0.5)
    forward = CaptureForwardModel()
    soma = Soma(
        bus,
        reader=FakeMetricsReader(base_metrics),
        detector=NeverAlertDetector(),
        forward_model=forward,
        self_rhythm=rhythm,
        self_rhythm_step_hz=20.0,
    )

    captured = {}

    original_step = soma._forward_model.step

    def capturing_step(feature_vec):
        captured["before"] = np.asarray(feature_vec, dtype=float).copy()
        result = original_step(feature_vec)
        captured["after"] = np.asarray(feature_vec, dtype=float).copy()
        return result

    soma._forward_model.step = capturing_step

    await soma.tick_once()
    vec = captured["before"]
    assert vec is not None
    assert vec[4] == pytest.approx(0.5 + 0.5 * np.sin(0.0), abs=1e-9)
    assert vec[5] == pytest.approx(0.5 + 0.5 * np.cos(0.0), abs=1e-9)
    assert vec[6] == pytest.approx(min(1.0, 2.0 * 0.5), abs=1e-9)
    assert vec[7] == pytest.approx(0.0, abs=1e-9)


@pytest.mark.asyncio
async def test_feature_vector_zero_without_self_rhythm(bus, base_metrics):
    forward = CaptureForwardModel()
    soma = Soma(
        bus,
        reader=FakeMetricsReader(base_metrics),
        detector=NeverAlertDetector(),
        forward_model=forward,
    )
    await soma.tick_once()
    vec = forward.captured
    assert vec is not None
    assert np.all(vec[4:8] == 0.0)


@pytest.mark.asyncio
async def test_self_rhythm_state_none_without_oscillator(bus, base_metrics):
    soma = Soma(
        bus,
        reader=FakeMetricsReader(base_metrics),
        detector=NeverAlertDetector(),
        forward_model=CaptureForwardModel(),
    )
    assert soma.self_rhythm_state() is None


@pytest.mark.asyncio
async def test_serialize_deserialize_round_trips_self_rhythm(bus, base_metrics):
    rhythm = RecordingSelfRhythm()
    soma = Soma(
        bus,
        reader=FakeMetricsReader(base_metrics),
        detector=NeverAlertDetector(),
        forward_model=CaptureForwardModel(),
        self_rhythm=rhythm,
    )
    await soma.tick_once()
    state = soma.serialize()
    assert "self_rhythm" in state
    assert state["self_rhythm"]["kind"] == "fake_self_rhythm"

    soma.deserialize(state)
    assert rhythm.deserialized == state["self_rhythm"]


@pytest.mark.asyncio
async def test_self_rhythm_loop_steps_with_external_drive(bus, base_metrics):
    rhythm = RecordingSelfRhythm()
    provider_values = [0.25]

    def maternal_drive():
        return provider_values[0]

    soma = Soma(
        bus,
        reader=FakeMetricsReader(base_metrics),
        detector=NeverAlertDetector(),
        forward_model=CaptureForwardModel(),
        self_rhythm=rhythm,
        self_rhythm_step_hz=200.0,
        maternal_drive=maternal_drive,
        entity_clock=EntityClock(),
    )
    await soma.initialize()
    await asyncio.sleep(0.05)
    await soma.shutdown()
    assert len(rhythm.steps) > 0
    drives, externals = zip(*rhythm.steps)
    assert any(ext == 0.25 for ext in externals)


@pytest.mark.asyncio
async def test_self_rhythm_loop_survives_raising_provider(bus, base_metrics):
    rhythm = RecordingSelfRhythm()

    def raising_drive():
        raise RuntimeError("provider unavailable")

    soma = Soma(
        bus,
        reader=FakeMetricsReader(base_metrics),
        detector=NeverAlertDetector(),
        forward_model=CaptureForwardModel(),
        self_rhythm=rhythm,
        self_rhythm_step_hz=200.0,
        maternal_drive=raising_drive,
        entity_clock=EntityClock(),
    )
    await soma.initialize()
    await asyncio.sleep(0.05)
    await soma.shutdown()
    assert len(rhythm.steps) > 0
    assert all(ext is None for _, ext in rhythm.steps)


@pytest.mark.asyncio
async def test_coalition_oscillator_never_receives_external_drive(bus, base_metrics):
    forward = CaptureForwardModel()
    coalition = RecordingCoalitionOscillator()
    rhythm = RecordingSelfRhythm(phase=1.0, amplitude=0.1)
    soma = Soma(
        bus,
        reader=FakeMetricsReader(base_metrics),
        detector=NeverAlertDetector(),
        forward_model=forward,
        self_rhythm=rhythm,
        self_rhythm_step_hz=20.0,
    )
    soma._oscillator = coalition
    # Let the self-rhythm step with a maternal drive while Soma publishes.
    rhythm.step(0.5, external_drive=0.7)
    await soma.tick_once()
    # The coalition oscillator's step(drive) takes no external drive at all (a
    # keyword would raise TypeError), it was stepped only by Soma's publishes
    # with their saliences, and the self-rhythm never reached it.
    assert coalition.steps, "Soma published nothing"
    assert all(0.0 <= d <= 1.0 for d in coalition.steps)
    assert 0.7 not in coalition.steps
    assert soma.phase() == coalition.phase()
