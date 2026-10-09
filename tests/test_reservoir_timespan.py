# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import numpy as np
import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.cfc_numpy import (
    ReservoirWeights,
    numpy_cfc_step,
)
from kaine.cycle.types import WorkspaceSnapshot
from kaine.modules.chronos.featurizer import SnapshotFeaturizer
from kaine.modules.chronos.module import Chronos
from kaine.modules.soma import AlertResult, Soma
from kaine.modules.soma.forward import SubstrateForwardModel, metrics_to_feature_vector

_TORCH = False
try:
    import torch  # noqa: F401
    from ncps.torch import CfC  # noqa: F401

    _TORCH = True
except Exception:
    pass


def _sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(x, -50.0, 50.0)))


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    bus = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield bus
    await bus.close()


class FakeMetricsReader:
    def __init__(self, metrics: dict[str, float] | None = None) -> None:
        self._metrics = metrics or {"cpu_percent": 10.0, "ram_percent": 20.0}

    async def read_metrics(self) -> dict[str, float]:
        return dict(self._metrics)

    def update_cycle_latency_sample(self, wall_duration_ms: float) -> None:
        pass


class NeverAlertDetector:
    def evaluate(self, metrics: dict[str, float]) -> AlertResult:
        return AlertResult()


class _FakeClock:
    def __init__(self, t: float = 0.0) -> None:
        self.t = float(t)

    def now(self) -> float:
        return self.t


# ---------------------------------------------------------------------------
# A. NumPy CfC timespan
# ---------------------------------------------------------------------------

def test_numpy_cfc_ts_1_matches_old_formula_bit_for_bit():
    r = ReservoirWeights.generate(seed=3, input_size=4, units=8)
    x = [0.1, -0.2, 0.3, 0.4]
    h = [0.05] * 8

    h_new = numpy_cfc_step(r, x, h, ts=1.0)

    z = np.asarray(x + h, dtype=np.float32)
    bb = z @ r.backbone_w.T + r.backbone_b
    z_bb = np.float32(1.7159) * np.tanh(np.float32(0.666) * bb)
    f1 = np.tanh(z_bb @ r.ff1_w.T + r.ff1_b)
    f2 = np.tanh(z_bb @ r.ff2_w.T + r.ff2_b)
    t = _sigmoid((z_bb @ r.time_a_w.T + r.time_a_b) + (z_bb @ r.time_b_w.T + r.time_b_b))
    h_old = f1 * (1.0 - t) + t * f2

    assert np.array_equal(np.asarray(h_new, dtype=np.float32), h_old)


def test_numpy_cfc_ts_varies_hidden_state():
    r = ReservoirWeights.generate(seed=3, input_size=4, units=8)
    x = [0.1, -0.2, 0.3, 0.4]
    h = [0.05] * 8

    h1 = numpy_cfc_step(r, x, h, ts=1.0)
    h025 = numpy_cfc_step(r, x, h, ts=0.25)
    h3 = numpy_cfc_step(r, x, h, ts=3.0)

    assert not np.array_equal(h1, h025)
    assert not np.array_equal(h1, h3)


@pytest.mark.skipif(not _TORCH, reason="torch/ncps not installed")
def test_soma_numpy_torch_parity_with_timespans():
    m_np = SubstrateForwardModel(
        backend="numpy", feature_dim=8, units=16, seed=123, lr=0.01
    )
    m_torch = SubstrateForwardModel(
        backend="torch", feature_dim=8, units=16, seed=123, lr=0.01
    )

    rng = np.random.default_rng(7)
    for _ in range(200):
        x = rng.uniform(0.0, 1.0, size=8)
        ts = rng.uniform(0.2, 4.0)

        err_np = float(m_np.step(x, timespan=ts))
        err_torch = float(m_torch.step(x, timespan=ts))
        assert err_np == pytest.approx(err_torch, abs=1e-5)

        h_np = np.ravel(m_np._last_hidden)
        h_torch = m_torch._last_hidden
        if isinstance(h_torch, torch.Tensor):
            h_torch = h_torch.detach().cpu().numpy()
        h_torch = np.ravel(h_torch)
        assert np.allclose(h_np, h_torch, atol=1e-5)


# ---------------------------------------------------------------------------
# B/D. Soma timespan plumbing and feature layout
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_soma_passes_timespan_to_forward_model(bus: AsyncBus):
    class RecordingForwardModel(SubstrateForwardModel):
        def __init__(self) -> None:
            super().__init__(backend="numpy", feature_dim=8, units=8, seed=1)
            self.calls: list[float] = []

        def step(self, feature, timespan: float = 1.0):
            self.calls.append(timespan)
            return super().step(feature, timespan=timespan)

    clock = _FakeClock(0.0)
    fm = RecordingForwardModel()
    soma = Soma(
        bus,
        reader=FakeMetricsReader(),
        detector=NeverAlertDetector(),
        forward_model=fm,
        entity_clock=clock,
    )

    await soma.tick_once()
    clock.t += 3.0
    await soma.tick_once()

    assert fm.calls == [1.0, 3.0]


@pytest.mark.asyncio
async def test_soma_legacy_forward_model_called_without_timespan(bus: AsyncBus):
    class LegacyForwardModel(SubstrateForwardModel):
        accepts_timespan = False

        def __init__(self) -> None:
            super().__init__(backend="numpy", feature_dim=8, units=8, seed=1)
            self.calls: list[int] = []

        def step(self, feature):
            self.calls.append(len(feature))
            return super().step(feature)

    fm = LegacyForwardModel()
    soma = Soma(
        bus,
        reader=FakeMetricsReader(),
        detector=NeverAlertDetector(),
        forward_model=fm,
    )

    await soma.tick_once()
    await soma.tick_once()

    # Two ticks reached the legacy model without a timespan keyword.
    assert fm.calls == [8, 8]


def test_soma_feature_layout_serialization():
    soma = Soma(
        bus=None,  # type: ignore[arg-type]
        reader=FakeMetricsReader(),
        detector=NeverAlertDetector(),
    )
    assert soma.serialize()["feature_layout"] == 2

    soma.deserialize({})
    assert soma._feature_layout == 1


# ---------------------------------------------------------------------------
# B. metrics_to_feature_vector VRAM slot
# ---------------------------------------------------------------------------

def test_metrics_vram_slot_layout_2():
    vec = metrics_to_feature_vector(
        {"gpu_0_vram_percent": 40.0, "gpu_1_vram_percent": 60.0},
        8,
    )
    assert vec[7] == pytest.approx(0.6)


def test_metrics_vram_slot_layout_1():
    vec = metrics_to_feature_vector(
        {"gpu_0_vram_percent": 40.0, "gpu_1_vram_percent": 60.0},
        8,
        layout=1,
    )
    assert vec[7] == 0.0


# ---------------------------------------------------------------------------
# E/F. Chronos timespan from featurizer clock
# ---------------------------------------------------------------------------

def _empty_snapshot(tick: int = 0) -> WorkspaceSnapshot:
    return WorkspaceSnapshot(tick_index=tick, selected_events=[], inhibited=False)


@pytest.mark.asyncio
async def test_chronos_timespan_from_featurizer_dt(bus: AsyncBus):
    class TimespanNetwork:
        accepts_timespan: bool = True

        def __init__(self) -> None:
            self.calls: list[float] = []

        def tick(self, feature_vec: list[float], timespan: float = 1.0) -> list[float]:
            self.calls.append(timespan)
            return [0.0] * 4

    times = [0.0]
    featurizer = SnapshotFeaturizer(clock=lambda: times[0])
    net = TimespanNetwork()
    chronos = Chronos(
        bus,
        featurizer=featurizer,
        network=net,
    )

    await chronos.on_workspace(_empty_snapshot())
    times[0] = 1.0
    await chronos.on_workspace(_empty_snapshot())
    times[0] = 2.0
    await chronos.on_workspace(_empty_snapshot())
    times[0] = 3.0
    await chronos.on_workspace(_empty_snapshot())
    times[0] = 7.0
    await chronos.on_workspace(_empty_snapshot())

    assert net.calls[0] == pytest.approx(1.0)
    assert net.calls[-1] > 1.5
