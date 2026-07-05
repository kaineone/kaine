# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for Soma's developmental cold-start warm-up gate.

The warm-up (soma-coldstart-regulation-warmup) gates ONLY the action path —
the reduce_rate/shed_module/request_maintenance regulation advisories and the
fatigue-accumulator INPUT — while the interoceptive forward model learns the
host substrate baseline. It NEVER alters the published prediction-error signal,
and any concurrent hard-threshold breach overrides it unconditionally.

The forward model is swapped for a deterministic fake so prediction error,
adaptation-sample count, and Hypnos-suspension are all controllable without a
real CfC. Construction still builds the real model, so torch is required.
"""
from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Optional

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.entity_clock import EntityClock
from kaine.modules.soma import AlertResult, Soma, ThresholdAnomalyDetector

pytest.importorskip("torch")


# ---------------------------------------------------------------------------
# Deterministic fakes
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


class NeverAlert:
    def evaluate(self, metrics: dict[str, float]) -> AlertResult:
        return AlertResult()


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


def _make_soma(bus, *, error=0.0, detector=None, clock_src=None, **kw) -> tuple:
    src = clock_src or ManualMonotonic()
    clock = EntityClock(monotonic=src)
    soma = Soma(
        bus,
        reader=FakeReader(kw.pop("metrics", None)),
        detector=detector or NeverAlert(),
        entity_clock=clock,
        **kw,
    )
    soma._forward_model = FakeForward(error=error)
    return soma, src


async def _types_on(bus) -> list[str]:
    entries = await bus.read("soma.out", last_id="0", count=200)
    return [ev.type for _, ev in entries]


async def _events_on(bus, type_: str) -> list:
    entries = await bus.read("soma.out", last_id="0", count=200)
    return [ev for _, ev in entries if ev.type == type_]


# ---------------------------------------------------------------------------
# End-condition: conjunction of samples AND lived time (paper §6.6 shape)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_warmup_end_requires_both_samples_and_time(bus: AsyncBus):
    soma, src = _make_soma(
        bus,
        regulation_warmup_min_samples=5,
        regulation_warmup_min_seconds=10.0,
    )
    # Anchor boot time at t=0 so lived_seconds tracks src.t.
    soma._boot_subjective_time = 0.0

    # Neither reached.
    soma._samples_seen = 0
    src.t = 0.0
    assert soma.warmup_active is True

    # Only samples reached.
    soma._samples_seen = 5
    src.t = 3.0
    assert soma.warmup_active is True

    # Only time reached.
    soma._samples_seen = 2
    src.t = 20.0
    assert soma.warmup_active is True

    # Both reached → warm-up ends.
    soma._samples_seen = 5
    src.t = 20.0
    assert soma.warmup_active is False


@pytest.mark.asyncio
async def test_stabilization_guard_can_only_extend(bus: AsyncBus):
    soma, src = _make_soma(
        bus,
        regulation_warmup_min_samples=1,
        regulation_warmup_min_seconds=1.0,
        regulation_warmup_require_error_stabilized=True,
        regulation_warmup_stable_window=4,
        regulation_warmup_stable_variance=0.01,
    )
    soma._boot_subjective_time = 0.0
    soma._samples_seen = 5
    src.t = 100.0
    # Samples + time satisfied, but the error window is empty/unstable →
    # the guard keeps warm-up active.
    assert soma.warmup_active is True
    # Feed a flat (zero-variance) error window → guard satisfied → ends.
    for _ in range(4):
        soma._prediction_error_window.append(0.10)
    assert soma.warmup_active is False


# ---------------------------------------------------------------------------
# Action path: advisory withheld during warm-up (cold-start only)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_coldstart_advisory_withheld_during_warmup(bus: AsyncBus):
    soma, src = _make_soma(
        bus,
        error=1.0,  # sustained above regulation_threshold 0.5
        regulation_sustain_window_s=1.0,
        regulation_warmup_min_samples=10_000,  # never completes here
        regulation_warmup_min_seconds=10_000.0,
    )
    src.t = 0.0
    await soma.tick_once()  # episode starts
    src.t = 2.0
    await soma.tick_once()  # > one sustain window → advisory would fire

    types = await _types_on(bus)
    assert "soma.regulation" not in types, "advisory must be withheld in warm-up"
    withheld = await _events_on(bus, "soma.regulation.withheld")
    assert len(withheld) == 1
    p = withheld[0].payload
    assert p["would_be_action"] in ("reduce_rate", "shed_module", "request_maintenance")
    assert p["prediction_error"] == pytest.approx(1.0)
    assert p["reason"] == "warmup"
    assert p["sustain_elapsed_s"] > 0.0

    # Signal path intact: the report still carries the RAW prediction error and
    # flags warm-up without lowering any numeric field.
    reports = await _events_on(bus, "soma.report")
    assert reports
    assert reports[-1].payload["prediction_error"] == pytest.approx(1.0)
    assert reports[-1].payload["warmup_active"] is True

    # Warm-up start marker emitted, and no completion yet.
    assert await _events_on(bus, "soma.warmup.started")
    assert not await _events_on(bus, "soma.warmup.completed")


@pytest.mark.asyncio
async def test_coldstart_fatigue_dampened_not_crossed(bus: AsyncBus):
    # Warm-up ON: sustained cold-start error must not inflate fatigue across the
    # maintenance threshold.
    soma_on, src_on = _make_soma(
        bus,
        error=1.0,
        fatigue_decay_per_s=0.0,
        fatigue_maintenance_threshold=2.0,
        regulation_warmup_min_samples=10_000,
        regulation_warmup_min_seconds=10_000.0,
    )
    for i in range(6):
        src_on.t = float(i)
        await soma_on.tick_once()
    assert soma_on._fatigue.value < soma_on._fatigue.threshold
    # No fatigue crossing was published.
    assert not await _events_on(bus, "soma.fatigue")
    # And the report's prediction_error stays raw.
    reports = await _events_on(bus, "soma.report")
    assert reports[-1].payload["prediction_error"] == pytest.approx(1.0)


@pytest.mark.asyncio
async def test_disabled_warmup_accrues_full_fatigue(bus: AsyncBus):
    # Regression guard: with warm-up disabled, the same cold-start error drives
    # fatigue at full weight (today's behavior).
    soma_off, src_off = _make_soma(
        bus,
        error=1.0,
        fatigue_decay_per_s=0.0,
        fatigue_maintenance_threshold=2.0,
        regulation_warmup_enabled=False,
    )
    for i in range(6):
        src_off.t = float(i)
        await soma_off.tick_once()
    # Full accrual crosses the threshold.
    assert soma_off._fatigue.value >= soma_off._fatigue.threshold
    assert await _events_on(bus, "soma.fatigue")
    # No warm-up markers when disabled.
    assert not await _events_on(bus, "soma.warmup.started")
    reports = await _events_on(bus, "soma.report")
    assert reports[-1].payload["warmup_active"] is False


@pytest.mark.asyncio
async def test_disabled_warmup_publishes_advisory(bus: AsyncBus):
    soma_off, src_off = _make_soma(
        bus,
        error=1.0,
        regulation_sustain_window_s=1.0,
        regulation_warmup_enabled=False,
    )
    src_off.t = 0.0
    await soma_off.tick_once()
    src_off.t = 2.0
    await soma_off.tick_once()
    types = await _types_on(bus)
    assert "soma.regulation" in types
    assert "soma.regulation.withheld" not in types


# ---------------------------------------------------------------------------
# Hard-threshold override: a real breach bypasses the gate unconditionally
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hard_threshold_breach_overrides_warmup(bus: AsyncBus):
    # A real GPU-temp breach during warm-up must STILL actuate regulation and
    # integrate fatigue at full weight.
    detector = ThresholdAnomalyDetector({"gpu_*_temp_c": 83.0})
    soma, src = _make_soma(
        bus,
        error=1.0,
        detector=detector,
        metrics={"cpu_percent": 10.0, "gpu_0_temp_c": 90.0},  # breaching
        fatigue_decay_per_s=0.0,
        fatigue_maintenance_threshold=1.0,
        regulation_sustain_window_s=1.0,
        regulation_warmup_min_samples=10_000,  # still deep in warm-up
        regulation_warmup_min_seconds=10_000.0,
    )
    src.t = 0.0
    await soma.tick_once()
    src.t = 2.0
    await soma.tick_once()

    # Still in warm-up...
    reports = await _events_on(bus, "soma.report")
    assert reports[-1].payload["warmup_active"] is True
    assert "gpu_0_temp_c" in reports[-1].payload["alerts"]

    # ...yet the advisory actuated (published as soma.regulation, NOT withheld).
    types = await _types_on(bus)
    assert "soma.regulation" in types
    assert "soma.regulation.withheld" not in types

    # ...and fatigue integrated at full weight, crossing the threshold.
    assert await _events_on(bus, "soma.fatigue")
    assert soma._fatigue.value >= soma._fatigue.threshold


# ---------------------------------------------------------------------------
# Completion boundary + resumption of normal behavior
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_warmup_completes_and_emits_completed(bus: AsyncBus):
    soma, src = _make_soma(
        bus,
        error=0.1,  # below regulation_threshold; no advisories
        regulation_warmup_min_samples=3,
        regulation_warmup_min_seconds=5.0,
    )
    # Tick until BOTH the sample and time minimums are met.
    for i in range(4):
        src.t = float(i * 2)  # 0, 2, 4, 6 → lived reaches 6 >= 5
        await soma.tick_once()

    started = await _events_on(bus, "soma.warmup.started")
    completed = await _events_on(bus, "soma.warmup.completed")
    assert started, "warm-up start marker should have been emitted"
    assert len(completed) == 1, "warm-up should complete exactly once"
    payload = completed[0].payload
    assert payload["samples_seen"] >= 3
    assert payload["lived_seconds"] >= 5.0

    # After completion the report flags warm-up inactive.
    reports = await _events_on(bus, "soma.report")
    assert reports[-1].payload["warmup_active"] is False


@pytest.mark.asyncio
async def test_regulation_resumes_after_warmup(bus: AsyncBus):
    soma, src = _make_soma(
        bus,
        error=1.0,
        regulation_sustain_window_s=1.0,
        regulation_warmup_min_samples=2,
        regulation_warmup_min_seconds=2.0,
    )
    # Drive past warm-up completion.
    src.t = 0.0
    await soma.tick_once()
    src.t = 3.0
    await soma.tick_once()  # completes warm-up (samples=2, lived=3)
    assert soma.warmup_active is False
    # A subsequent sustained advisory now publishes normally.
    src.t = 6.0
    await soma.tick_once()
    types = await _types_on(bus)
    assert "soma.regulation" in types


# ---------------------------------------------------------------------------
# Defaults ship per the design
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_warmup_defaults(bus: AsyncBus):
    soma, _ = _make_soma(bus)
    assert soma._warmup_enabled is True
    assert soma._warmup_min_samples == 1000
    assert soma._warmup_min_seconds == pytest.approx(1200.0)
    assert soma._warmup_require_error_stabilized is False


def test_shipped_config_ships_warmup_knobs():
    root = Path(__file__).parent.parent
    cfg = tomllib.loads((root / "config" / "kaine.toml").read_text())
    soma = cfg["soma"]
    assert soma["regulation_warmup_enabled"] is True
    assert soma["regulation_warmup_min_samples"] == 1000
    assert soma["regulation_warmup_min_seconds"] == pytest.approx(1200.0)
    assert soma["regulation_warmup_require_error_stabilized"] is False
