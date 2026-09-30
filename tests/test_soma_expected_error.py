# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for Soma's learned expected prediction error and unexpected error.

The harness follows tests/test_soma_warmup.py: deterministic fakes, a fakeredis
bus fixture, and ManualMonotonic clock. The new ExpectedErrorModel is tested
directly, and the real SubstrateForwardModel is driven on a synthetic noisy
periodic channel to show that fatigue driven by the unexpected error stays
below threshold while fatigue driven by the raw error crosses repeatedly.
"""

from __future__ import annotations

import math
import random
from typing import Any, Optional

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.entity_clock import EntityClock
from kaine.experiment.log_schema import _bound_for, _out_of_range
from kaine.modules.soma import AlertResult, Soma
from kaine.modules.soma.expected_error import ExpectedErrorModel
from kaine.modules.soma.forward import SubstrateForwardModel

# ---------------------------------------------------------------------------
# Deterministic fakes (copied/adapted from tests/test_soma_warmup.py)
# ---------------------------------------------------------------------------


class FakeReader:
    def __init__(self, metrics: Optional[dict[str, float]] = None) -> None:
        self._metrics = metrics or {"cpu_percent": 10.0, "ram_percent": 20.0}

    async def initialize(self) -> None:
        return

    async def shutdown(self) -> None:
        return

    async def read_metrics(self) -> dict[str, float]:
        return dict(self._metrics)

    def update_cycle_latency_sample(self, wall_duration_ms: float) -> None:
        return


class FakeForward:
    """Deterministic stand-in for SubstrateForwardModel."""

    def __init__(self, error: float = 0.0) -> None:
        self.error = float(error)
        self.suspended = False
        self.adaptation_steps = 0

    def step(self, feature: list[float]) -> float:
        if not self.suspended:
            self.adaptation_steps += 1
        return self.error

    def prediction_error_to_salience(
        self, raw_error, baseline_salience, alert_salience, *, error_window=None
    ) -> float:
        return baseline_salience

    def state_dict(self) -> dict[str, Any]:
        return {}

    def load_state_dict(self, state: dict[str, Any]) -> None:
        return


class ResidualForward:
    """Fake forward model that exposes signed per-channel residuals."""

    def __init__(self, residuals: tuple[float, ...] = (0.0,)) -> None:
        self.residuals = residuals
        self.suspended = False
        self.adaptation_steps = 0

    @property
    def last_residuals(self) -> tuple[float, ...]:
        return self.residuals

    def step(self, feature: list[float]) -> float:
        if not self.suspended:
            self.adaptation_steps += 1
        return math.sqrt(sum(r * r for r in self.residuals))

    def prediction_error_to_salience(
        self, raw_error, baseline_salience, alert_salience, *, error_window=None
    ) -> float:
        return baseline_salience

    def state_dict(self) -> dict[str, Any]:
        return {"residuals": self.residuals}

    def load_state_dict(self, state: dict[str, Any]) -> None:
        self.residuals = tuple(state.get("residuals", self.residuals))


class FirstNoneForward:
    """Forward fake whose first tick has last_residuals=None, then 8 channels."""

    def __init__(self, residuals: tuple[float, ...] = (0.0,) * 8) -> None:
        self.residuals = residuals
        self.suspended = False
        self.adaptation_steps = 0

    @property
    def last_residuals(self) -> Optional[tuple[float, ...]]:
        if self.adaptation_steps == 1:
            return None
        return self.residuals

    def step(self, feature: list[float]) -> float:
        if not self.suspended:
            self.adaptation_steps += 1
        return math.sqrt(sum(r * r for r in self.residuals))

    def prediction_error_to_salience(
        self, raw_error, baseline_salience, alert_salience, *, error_window=None
    ) -> float:
        return baseline_salience

    def state_dict(self) -> dict[str, Any]:
        return {}

    def load_state_dict(self, state: dict[str, Any]) -> None:
        return


class SkippableForward:
    """Forward fake that can produce one tick with last_residuals=None."""

    def __init__(self, residuals: tuple[float, ...] = (0.0,) * 8) -> None:
        self.residuals = residuals
        self.suspended = False
        self.adaptation_steps = 0
        self._skip_active = False
        self.skip_next = False

    @property
    def last_residuals(self) -> Optional[tuple[float, ...]]:
        if self._skip_active:
            return None
        return self.residuals

    def step(self, feature: list[float]) -> float:
        if not self.suspended:
            self.adaptation_steps += 1
        self._skip_active = self.skip_next
        self.skip_next = False
        return math.sqrt(sum(r * r for r in self.residuals))

    def prediction_error_to_salience(
        self, raw_error, baseline_salience, alert_salience, *, error_window=None
    ) -> float:
        return baseline_salience

    def state_dict(self) -> dict[str, Any]:
        return {}

    def load_state_dict(self, state: dict[str, Any]) -> None:
        return


class NeverAlert:
    def evaluate(self, metrics: dict[str, float]) -> AlertResult:
        return AlertResult()


class AlertDetector:
    def evaluate(self, metrics: dict[str, float]) -> AlertResult:
        return AlertResult(keys=("test",))


class ManualMonotonic:
    """A mutable monotonic source for a deterministic EntityClock."""

    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


@pytest.fixture
async def bus():
    fakeredis = pytest.importorskip("fakeredis.aioredis")
    client = fakeredis.FakeRedis(decode_responses=True)
    b = AsyncBus(BusConfig(password="x", audit_required=False), client=client)
    yield b
    await b.close()


def _make_soma(
    bus,
    *,
    error: float = 0.0,
    detector=None,
    clock_src=None,
    forward_model=None,
    **kw,
) -> tuple:
    src = clock_src or ManualMonotonic()
    clock = EntityClock(monotonic=src)
    soma = Soma(
        bus,
        reader=FakeReader(kw.pop("metrics", None)),
        detector=detector or NeverAlert(),
        entity_clock=clock,
        forward_model=forward_model,
        **kw,
    )
    if forward_model is None:
        soma._forward_model = FakeForward(error=error)
    return soma, src


def _steady_channel4_pattern():
    rng = random.Random(0)
    i = 0
    while True:
        mag = rng.uniform(0.2, 0.45)
        yield mag if i % 2 == 0 else -mag
        i += 1


# ---------------------------------------------------------------------------
# ExpectedErrorModel unit tests
# ---------------------------------------------------------------------------


def test_expected_error_validation() -> None:
    with pytest.raises(ValueError):
        ExpectedErrorModel(tau_s=0.0)
    with pytest.raises(ValueError):
        ExpectedErrorModel(tau_s=float("nan"))
    with pytest.raises(ValueError):
        ExpectedErrorModel(band=-1.0)


def test_expected_error_converges_on_steady_noise() -> None:
    model = ExpectedErrorModel(tau_s=60.0)
    rng = random.Random(0)
    last_residuals = []
    last_unexpected = []
    for i in range(600):
        mag = rng.uniform(0.2, 0.45)
        r = mag if i % 2 == 0 else -mag
        u = model.unexpected((r,), dt=1.0)
        last_residuals.append(abs(r))
        if i >= 500:
            last_unexpected.append(u)

    assert sum(last_unexpected) / len(last_unexpected) < 0.02
    assert sum(last_residuals) / len(last_residuals) > 0.2

    spike = model.unexpected((3.0,), dt=1.0)
    assert spike > 2.0


def test_expected_error_band_before_update() -> None:
    model = ExpectedErrorModel(tau_s=60.0)
    assert math.isclose(model.unexpected((1.23,), dt=1.0), 1.23)


def test_expected_error_learn_false_unchanged() -> None:
    model = ExpectedErrorModel(tau_s=60.0)
    model.unexpected((1.0,), dt=1.0)
    expected_before = list(model.expected)
    spread_before = list(model.spread)
    model.unexpected((2.0,), dt=1.0, learn=False)
    assert list(model.expected) == expected_before
    assert list(model.spread) == spread_before


def test_expected_error_state_dict_round_trip() -> None:
    m1 = ExpectedErrorModel(tau_s=60.0)
    for r in (0.1, 0.2, 0.3):
        m1.unexpected((r,), dt=1.0)
    state = m1.state_dict()
    m2 = ExpectedErrorModel(tau_s=60.0)
    m2.load_state_dict(state)
    assert m2.expected == m1.expected
    assert m2.spread == m1.spread


def test_expected_error_load_state_dict_bad_values_fresh() -> None:
    m = ExpectedErrorModel(tau_s=60.0)
    m.load_state_dict({"expected": [1.0], "spread": [1.0, 0.0]})
    assert m.expected == ()
    assert m.spread == ()

    m.load_state_dict({"expected": [-1.0], "spread": [0.0]})
    assert m.expected == ()
    assert m.spread == ()

    m.load_state_dict({"expected": [float("nan")], "spread": [0.0]})
    assert m.expected == ()
    assert m.spread == ()

    m.load_state_dict("not a mapping")
    assert m.expected == ()
    assert m.spread == ()


def test_expected_error_width_change_resets() -> None:
    m = ExpectedErrorModel(tau_s=60.0)
    for _ in range(5):
        m.unexpected((0.5, 0.2, 0.1), dt=1.0)
    assert len(m.expected) == 3
    assert not all(v == 0.0 for v in m.expected)

    m.unexpected((0.1, 0.1, 0.1, 0.1, 0.1), dt=1.0, learn=False)
    assert len(m.expected) == 5
    assert all(v == 0.0 for v in m.expected)
    assert all(v == 0.0 for v in m.spread)


# ---------------------------------------------------------------------------
# Soma integration tests with fake forward models
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_report_carries_raw_prediction_error_and_unexpected_error(bus) -> None:
    soma, src = _make_soma(
        bus, error=0.5, regulation_warmup_enabled=False, expected_error_tau_s=60.0
    )
    src.t += 1.0
    payload = await soma.tick_once()
    assert payload["prediction_error"] == 0.5
    assert payload["unexpected_error"] >= 0.0


@pytest.mark.asyncio
async def test_steady_residual_variability_no_cross_after_learning(bus) -> None:
    forward = ResidualForward((0.0,) * 8)
    soma, src = _make_soma(
        bus,
        forward_model=forward,
        detector=NeverAlert(),
        regulation_warmup_enabled=False,
        expected_error_tau_s=60.0,
        fatigue_maintenance_threshold=5.0,
    )
    gen = _steady_channel4_pattern()
    for _ in range(600):
        forward.residuals = tuple(next(gen) if i == 4 else 0.0 for i in range(8))
        src.t += 1.0
        await soma.tick_once()

    soma._fatigue.reset()
    for _ in range(600):
        forward.residuals = tuple(next(gen) if i == 4 else 0.0 for i in range(8))
        src.t += 1.0
        payload = await soma.tick_once()

    assert soma._fatigue.value < 5.0
    assert payload["prediction_error"] > 0.2


@pytest.mark.asyncio
async def test_sustained_spike_crosses_threshold(bus) -> None:
    forward = ResidualForward((0.0,) * 8)
    soma, src = _make_soma(
        bus,
        forward_model=forward,
        detector=NeverAlert(),
        regulation_warmup_enabled=False,
        expected_error_tau_s=60.0,
        fatigue_maintenance_threshold=5.0,
    )
    rng = random.Random(2)
    for _ in range(300):
        r = rng.uniform(0.2, 0.45) * (1 if _ % 2 == 0 else -1)
        forward.residuals = tuple(r if i == 0 else 0.0 for i in range(8))
        src.t += 1.0
        await soma.tick_once()

    for _ in range(60):
        forward.residuals = tuple(0.9 if i == 0 else 0.0 for i in range(8))
        src.t += 1.0
        await soma.tick_once()

    assert soma._fatigue.value >= 5.0


@pytest.mark.asyncio
async def test_hard_breach_uses_raw_error(bus) -> None:
    soma, src = _make_soma(
        bus,
        error=2.0,
        detector=NeverAlert(),
        regulation_warmup_enabled=False,
        expected_error_tau_s=10.0,
    )
    for _ in range(100):
        src.t += 1.0
        await soma.tick_once()

    soma._detector = AlertDetector()
    before = soma._fatigue.value
    for _ in range(10):
        src.t += 1.0
        await soma.tick_once()

    assert soma._fatigue.value > before


@pytest.mark.asyncio
async def test_regulation_uses_action_error(bus) -> None:
    forward = ResidualForward(tuple(0.5 if i == 0 else 0.0 for i in range(8)))
    soma, src = _make_soma(
        bus,
        forward_model=forward,
        detector=NeverAlert(),
        regulation_warmup_enabled=False,
        expected_error_tau_s=60.0,
        regulation_threshold=0.2,
        regulation_sustain_window_s=5.0,
    )

    # Phase 1: learn the steady 0.5 residual.
    for _ in range(600):
        src.t += 1.0
        await soma.tick_once()

    entries = await bus.read("soma.out", last_id="0", count=10000)
    last_id = entries[-1][0]

    # Phase 2: the learned residual should not trigger regulation.
    for _ in range(60):
        src.t += 1.0
        await soma.tick_once()

    entries_after = await bus.read("soma.out", last_id=last_id, count=10000)
    regulation_events = [ev for _, ev in entries_after if ev.type == "soma.regulation"]
    assert not regulation_events

    reports = [ev for _, ev in entries_after if ev.type == "soma.report"]
    last_report = reports[-1]
    assert last_report.payload["prediction_error"] == 0.5


@pytest.mark.asyncio
async def test_forward_without_last_residuals_works(bus) -> None:
    soma, src = _make_soma(
        bus, error=0.5, regulation_warmup_enabled=False, expected_error_tau_s=60.0
    )
    src.t += 1.0
    payload = await soma.tick_once()
    assert payload["unexpected_error"] >= 0.0


@pytest.mark.asyncio
async def test_first_tick_without_residuals_keeps_restored_expectations(bus) -> None:
    forward = FirstNoneForward((0.05,) * 8)
    soma, src = _make_soma(
        bus,
        forward_model=forward,
        detector=NeverAlert(),
        regulation_warmup_enabled=False,
        expected_error_tau_s=60.0,
    )
    soma._expected_error.load_state_dict({"expected": [0.1] * 8, "spread": [0.05] * 8})

    src.t += 1.0
    payload = await soma.tick_once()
    assert soma._expected_error.expected == (0.1,) * 8
    assert payload["unexpected_error"] == 0.0

    src.t += 1.0
    await soma.tick_once()
    assert len(soma._expected_error.expected) == 8


@pytest.mark.asyncio
async def test_skipped_tick_does_not_reset(bus) -> None:
    forward = SkippableForward((0.05,) * 8)
    soma, src = _make_soma(
        bus,
        forward_model=forward,
        detector=NeverAlert(),
        regulation_warmup_enabled=False,
        expected_error_tau_s=60.0,
    )
    for _ in range(50):
        src.t += 1.0
        await soma.tick_once()

    expected_before = soma._expected_error.expected
    spread_before = soma._expected_error.spread

    forward.skip_next = True
    src.t += 1.0
    await soma.tick_once()

    assert soma._expected_error.expected == expected_before
    assert soma._expected_error.spread == spread_before


@pytest.mark.asyncio
async def test_serialize_deserialize_expected_error(bus) -> None:
    forward = ResidualForward(tuple(0.3 if i == 0 else 0.0 for i in range(8)))
    soma1, src = _make_soma(
        bus,
        forward_model=forward,
        detector=NeverAlert(),
        regulation_warmup_enabled=False,
        expected_error_tau_s=60.0,
    )
    for _ in range(20):
        src.t += 1.0
        await soma1.tick_once()

    state = soma1.serialize()

    soma2, _ = _make_soma(
        bus,
        forward_model=ResidualForward((0.0,) * 8),
        detector=NeverAlert(),
        regulation_warmup_enabled=False,
        expected_error_tau_s=60.0,
    )
    soma2.deserialize(state)

    assert soma2._expected_error.expected == soma1._expected_error.expected
    assert soma2._expected_error.spread == soma1._expected_error.spread

    state.pop("expected_error")
    soma3, _ = _make_soma(
        bus,
        forward_model=ResidualForward((0.0,) * 8),
        detector=NeverAlert(),
        regulation_warmup_enabled=False,
        expected_error_tau_s=60.0,
    )
    soma3.deserialize(state)
    assert soma3._expected_error.expected == ()
    assert soma3._expected_error.spread == ()


# ---------------------------------------------------------------------------
# Real forward-model integration
# ---------------------------------------------------------------------------


def test_real_forward_model_unexpected_error_avoids_crossing() -> None:
    forward = SubstrateForwardModel(feature_dim=8, units=32, backend="numpy", seed=0)
    eem = ExpectedErrorModel(tau_s=600.0, band=2.0)

    rng = random.Random(1)
    phase = 0.0
    F_raw = 0.0
    F_unexp = 0.0
    raw_cross = 0
    unexp_cross = 0

    for step in range(3000):
        phase += rng.uniform(0.9, 1.4)
        feature = [0.2] * 8
        feature[4] = 0.5 + 0.5 * math.sin(phase)
        feature[5] = 0.5 + 0.5 * math.cos(phase)
        feature[6] = 0.5
        feature[7] = 0.0

        err = forward.step(feature)
        residuals = getattr(forward, "last_residuals", None)
        if residuals is None:
            residuals = (err,)
        unexp = eem.unexpected(residuals, dt=1.0, learn=True)

        F_raw = max(0.0, F_raw + err - 0.01)
        if F_raw >= 100.0:
            if step >= 1500:
                raw_cross += 1
            F_raw = 0.0

        F_unexp = max(0.0, F_unexp + unexp - 0.01)
        if F_unexp >= 100.0:
            if step >= 1500:
                unexp_cross += 1
            F_unexp = 0.0

    assert raw_cross >= 3
    assert unexp_cross == 0


# ---------------------------------------------------------------------------
# Log schema
# ---------------------------------------------------------------------------


def test_log_schema_soma_report_bounds() -> None:
    fat_bound = _bound_for("soma.report", "fatigue_value")
    assert fat_bound == (0.0, math.inf)
    assert not _out_of_range(57.3, fat_bound)

    unexp_bound = _bound_for("soma.report", "unexpected_error")
    assert unexp_bound == (0.0, math.inf)
    assert _out_of_range(-0.1, unexp_bound)
