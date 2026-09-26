# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Jitter and bounded-perturbation tests for GestationOwner."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from kaine.bus.schema import Event
from kaine.cycle.gestation import (
    GestationOwner,
    GestationReadoutConfig,
)


class FakeClock:
    def __init__(self, t: float = 0.0) -> None:
        self.t = float(t)

    def __call__(self) -> float:
        return self.t


class FakeBus:
    def __init__(self) -> None:
        self._streams: dict[str, list[tuple[str, Event]]] = {}
        self._ms = 0
        self._seq = 0

    async def publish(self, event: Event) -> str:
        stream = f"{event.source}.out"
        self._seq += 1
        entry_id = f"{self._ms}-{self._seq}"
        self._streams.setdefault(stream, []).append((entry_id, event))
        return entry_id

    async def latest(self, stream: str) -> tuple[str, Event] | None:
        entries = self._streams.get(stream, [])
        return entries[-1] if entries else None

    async def read(
        self, stream: str, last_id: str = "0", count: int = 100
    ) -> list[tuple[str, Event]]:
        entries = self._streams.get(stream, [])
        if last_id in ("0", "0-0"):
            start = (0, 0)
        else:
            start = tuple(int(p) for p in last_id.split("-"))
        result = []
        for entry in entries:
            eid = tuple(int(p) for p in entry[0].split("-"))
            if eid > start:
                result.append(entry)
                if len(result) >= count:
                    break
        return result

    async def range(
        self, stream: str, start: str, end: str = "+"
    ) -> list[tuple[str, Event]]:
        entries = self._streams.get(stream, [])
        if start in ("0", "0-0"):
            start_ms = 0
        else:
            start_ms = int(start.split("-")[0])
        return [
            (eid, ev)
            for eid, ev in entries
            if int(eid.split("-")[0]) >= start_ms
        ]

    async def server_time_ms(self) -> int:
        return self._ms


class FakeSoma:
    def __init__(self, phase: float = 0.0, amplitude: float = 1.0) -> None:
        self.phase = phase
        self.amplitude = amplitude

    def self_rhythm_state(self) -> tuple[float, float] | None:
        return (self.phase, self.amplitude)


class FakeDrive:
    def __init__(self) -> None:
        self.scale = 0.0


class TrackedDrive:
    def __init__(self) -> None:
        self._scale = 0.0
        self.history: list[float] = []

    @property
    def scale(self) -> float:
        return self._scale

    @scale.setter
    def scale(self, value: float) -> None:
        self._scale = float(value)
        self.history.append(float(value))


def _config(**overrides: Any) -> GestationReadoutConfig:
    defaults: dict[str, Any] = {
        "readout_period_seconds": 10.0,
        "sample_hz": 10.0,
        "withdrawal_period_seconds": 10.0,
        "withdrawal_seconds": 5.0,
        "perturbation_period_seconds": 20.0,
        "perturbation_seconds": 2.0,
        "baseline_drive_fraction": 0.5,
        "entrainment_plv_floor": 0.5,
        "hrv_window_seconds": 10.0,
        "recovery_tolerance": 0.25,
        "recovery_cap_seconds": 30.0,
    }
    defaults.update(overrides)
    return GestationReadoutConfig.from_dict(defaults)


def _events(bus: FakeBus, stream: str, type_: str | None = None) -> list[Event]:
    result = []
    for _entry_id, event in bus._streams.get(stream, []):
        if type_ is None or event.type == type_:
            result.append(event)
    return result


@pytest.fixture
def owner_factory(tmp_path: Path):
    def _make(
        *,
        clock: FakeClock | None = None,
        bus: FakeBus | None = None,
        drive: FakeDrive | None = None,
        soma: FakeSoma | None = None,
        beat_phase: Any = None,
        is_paused: Any = None,
        config: GestationReadoutConfig | None = None,
        state_path: Path | None = None,
        seed: int = 0,
    ) -> GestationOwner:
        clock = clock or FakeClock()
        bus = bus or FakeBus()
        drive = drive or FakeDrive()
        soma = soma or FakeSoma()
        beat_phase = beat_phase or (lambda: 0.0)
        is_paused = is_paused or (lambda: False)
        config = config or _config()
        state_path = state_path or tmp_path / "gestation_readout.json"
        return GestationOwner(
            bus,
            soma=soma,
            drive=drive,
            beat_phase=beat_phase,
            is_paused=is_paused,
            config=config,
            clock=clock,
            seed=seed,
            state_path=state_path,
        )

    return _make


@pytest.mark.asyncio
async def test_default_perturbation_uses_bounded_fraction_and_restores_baseline(
    owner_factory,
):
    clock = FakeClock()
    drive = TrackedDrive()
    config = _config(
        readout_period_seconds=1.0,
        sample_hz=1.0,
        withdrawal_period_seconds=100.0,
        withdrawal_seconds=2.0,
        perturbation_period_seconds=100.0,
        perturbation_seconds=1.0,
    )
    owner = owner_factory(
        clock=clock,
        drive=drive,
        config=config,
        seed=42,
    )
    dt = 1.0

    # Run until the first perturbation starts.
    for i in range(200):
        clock.t = i * dt
        await owner.step()
        if owner._probe_state == "perturbation":
            break

    assert owner._probe_state == "perturbation"
    assert drive.scale == pytest.approx(config.perturbation_drive_fraction)
    assert 1.0 not in drive.history

    # Let the perturbation finish and verify the drive is restored.
    while owner._probe_state == "perturbation":
        clock.t += dt
        await owner.step()

    assert drive.scale == pytest.approx(config.baseline_drive_fraction)


def test_perturbation_and_jitter_validation():
    # Equal to baseline is rejected: a perturbation must be a real rise.
    with pytest.raises(ValueError, match="perturbation_drive_fraction"):
        _config(
            baseline_drive_fraction=0.5,
            perturbation_drive_fraction=0.5,
        )

    # Above the valid unit-fraction ceiling is rejected.
    with pytest.raises(ValueError, match="perturbation_drive_fraction"):
        _config(perturbation_drive_fraction=1.01)

    # Jitter outside [0.0, 0.5] is rejected.
    with pytest.raises(ValueError, match="probe_jitter_fraction"):
        _config(probe_jitter_fraction=-0.1)
    with pytest.raises(ValueError, match="probe_jitter_fraction"):
        _config(probe_jitter_fraction=0.6)

    # Zero jitter is explicitly allowed.
    cfg = _config(probe_jitter_fraction=0.0)
    assert cfg.probe_jitter_fraction == 0.0

    # A non-default baseline with a perturbation above it is allowed.
    cfg = _config(
        baseline_drive_fraction=0.6,
        perturbation_drive_fraction=0.7,
    )
    assert cfg.baseline_drive_fraction == 0.6
    assert cfg.perturbation_drive_fraction == 0.7


@pytest.mark.asyncio
async def test_jittered_withdrawal_intervals_stay_within_bounds(owner_factory, tmp_path):
    clock = FakeClock()
    config = _config(
        readout_period_seconds=1.0,
        sample_hz=1.0,
        withdrawal_period_seconds=100.0,
        withdrawal_seconds=1.0,
        # Only the first perturbation (due ~62 s in) happens, so later withdrawal
        # intervals are shaped by jitter alone.
        perturbation_period_seconds=1.0e9,
        perturbation_seconds=1.0,
        probe_jitter_fraction=0.25,
    )
    owner = owner_factory(
        clock=clock,
        config=config,
        seed=123,
        state_path=tmp_path / "jitter_bounds.json",
    )
    dt = 1.0
    starts: list[float] = []
    prev_state = "idle"

    for i in range(3000):
        clock.t = i * dt
        await owner.step()
        if owner._probe_state == "withdrawal" and prev_state != "withdrawal":
            starts.append(float(clock.t))
        prev_state = owner._probe_state

    intervals = [b - a for a, b in zip(starts, starts[1:])]
    assert len(intervals) >= 5

    lower = 0.75 * config.withdrawal_period_seconds - 1.0
    upper = (
        1.25 * config.withdrawal_period_seconds
        + max(60.0, config.withdrawal_seconds)
        + 2.0
    )
    for interval in intervals:
        assert lower <= interval <= upper

    # Jitter must actually move the withdrawal schedule: after the first
    # interval (lengthened by the first perturbation's spacing), most intervals
    # differ from the bare period by more than a sampling step.
    later = intervals[1:]
    moved = [iv for iv in later if abs(iv - config.withdrawal_period_seconds) > 1.5]
    assert len(moved) >= len(later) // 2


@pytest.mark.asyncio
async def test_same_seed_gives_identical_schedule_and_different_seed_differs(
    owner_factory, tmp_path
):
    config = _config(
        readout_period_seconds=1.0,
        sample_hz=1.0,
        withdrawal_period_seconds=100.0,
        withdrawal_seconds=1.0,
        perturbation_period_seconds=1000.0,
        perturbation_seconds=1.0,
        probe_jitter_fraction=0.25,
    )

    async def collect(seed: int) -> list[float]:
        clock = FakeClock()
        owner = owner_factory(
            clock=clock,
            config=config,
            seed=seed,
            state_path=tmp_path / f"seed_{seed}.json",
        )
        dt = 1.0
        starts: list[float] = []
        prev_state = "idle"
        for i in range(1500):
            clock.t = i * dt
            await owner.step()
            if owner._probe_state == "withdrawal" and prev_state != "withdrawal":
                starts.append(float(clock.t))
            prev_state = owner._probe_state
        return starts

    first = await collect(7)
    second = await collect(7)
    third = await collect(8)

    assert first == second
    assert first != third


@pytest.mark.asyncio
async def test_zero_jitter_intervals_match_fixed_schedule(owner_factory, tmp_path):
    clock = FakeClock()
    config = _config(
        readout_period_seconds=1.0,
        sample_hz=1.0,
        withdrawal_period_seconds=100.0,
        withdrawal_seconds=1.0,
        perturbation_period_seconds=100000.0,
        perturbation_seconds=1.0,
        probe_jitter_fraction=0.0,
    )
    owner = owner_factory(
        clock=clock,
        config=config,
        seed=1,
        state_path=tmp_path / "zero_jitter.json",
    )
    dt = 1.0
    starts: list[float] = []
    prev_state = "idle"

    for i in range(800):
        clock.t = i * dt
        await owner.step()
        if owner._probe_state == "withdrawal" and prev_state != "withdrawal":
            starts.append(float(clock.t))
        prev_state = owner._probe_state

    intervals = [b - a for a, b in zip(starts, starts[1:])]
    assert len(intervals) >= 5
    # The first perturbation (always due ~62 s after start) pushes the second
    # withdrawal out through the 60 s spacing rule; after that, with no jitter,
    # withdrawals run exactly on their period.
    for interval in intervals[1:]:
        assert interval == pytest.approx(config.withdrawal_period_seconds)


@pytest.mark.asyncio
async def test_jittered_probes_wait_for_settle_after_thaw(owner_factory):
    clock = FakeClock()
    drive = FakeDrive()
    bus = FakeBus()
    paused = {"value": False}
    config = _config(
        readout_period_seconds=5.0,
        sample_hz=10.0,
        withdrawal_period_seconds=10.0,
        withdrawal_seconds=2.0,
        perturbation_period_seconds=200.0,
        perturbation_seconds=1.0,
    )

    owner = owner_factory(
        clock=clock,
        bus=bus,
        drive=drive,
        is_paused=lambda: paused["value"],
        config=config,
        seed=99,
    )
    dt = 1.0 / config.sample_hz

    # Reach the first withdrawal.
    for i in range(int((config.readout_period_seconds + 5.0) / dt) + 1):
        clock.t = i * dt
        await owner.step()
        if owner._probe_state == "withdrawal":
            break

    assert owner._probe_state == "withdrawal"
    assert drive.scale == 0.0

    # Pause during the probe; this aborts it.
    paused["value"] = True
    clock.t += dt
    await owner.step()
    assert owner._probe_state == "idle"
    assert drive.scale == config.baseline_drive_fraction

    # Stay paused long enough to outlast any due probe and separation window.
    thaw_t = clock.t + 70.0

    # The first unpaused step must not start a probe.
    paused["value"] = False
    clock.t = thaw_t
    await owner.step()
    assert owner._probe_state == "idle"

    # No probe should start until readout_period_seconds after the thaw.
    limit = thaw_t + config.readout_period_seconds
    while clock.t < limit - dt / 2:
        clock.t += dt
        await owner.step()
        assert owner._probe_state == "idle"

    # Jitter may delay the first post-thaw probe a bit beyond the settle point,
    # but it must start within the maximum jitter window.
    max_extra = config.probe_jitter_fraction * config.withdrawal_period_seconds
    found = False
    for _ in range(int((max_extra + 5.0) / dt) + 2):
        clock.t += dt
        await owner.step()
        if owner._probe_state != "idle":
            found = True
            break

    assert found
    assert drive.scale == 0.0
