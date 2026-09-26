# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Schedule and windowing regression tests for GestationOwner."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pytest

from kaine.bus.schema import Event
from kaine.cycle.gestation import (
    PROBE_TYPE,
    READINESS_TYPE,
    SOURCE,
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
            state_path=state_path,
        )

    return _make


@pytest.mark.asyncio
async def test_probe_after_thaw_waits_for_readout_period(owner_factory):
    clock = FakeClock()
    drive = FakeDrive()
    bus = FakeBus()
    paused = {"value": False}
    config = _config(
        readout_period_seconds=5.0,
        sample_hz=10.0,
        withdrawal_period_seconds=10.0,
        withdrawal_seconds=2.0,
    )

    owner = owner_factory(
        clock=clock,
        bus=bus,
        drive=drive,
        is_paused=lambda: paused["value"],
        config=config,
    )
    dt = 1.0 / config.sample_hz

    # Reach the first withdrawal at the end of the initial readout period.
    for i in range(int(config.readout_period_seconds / dt) + 1):
        clock.t = i * dt
        await owner.step()

    assert owner._probe_state == "withdrawal"
    assert drive.scale == 0.0

    # Pause while the withdrawal is active; this aborts the probe.
    paused["value"] = True
    clock.t += dt
    await owner.step()
    assert owner._probe_state == "idle"
    assert drive.scale == config.baseline_drive_fraction

    # Stay paused long enough to outlast the due withdrawal and the
    # separation window after the abort.
    thaw_t = clock.t + 70.0

    # First unpaused step must not start a probe.
    paused["value"] = False
    clock.t = thaw_t
    await owner.step()
    assert owner._probe_state == "idle"

    start_events = [
        e for e in _events(bus, f"{SOURCE}.out", PROBE_TYPE)
        if e.payload.get("phase") == "start"
    ]
    assert len(start_events) == 1

    # No probe should start until readout_period_seconds after the thaw.
    limit = thaw_t + config.readout_period_seconds
    while clock.t < limit - dt / 2:
        clock.t += dt
        await owner.step()
        assert owner._probe_state == "idle"

    # Exactly at/after the settle point a new withdrawal starts.
    clock.t = limit
    await owner.step()
    assert owner._probe_state == "withdrawal"
    assert drive.scale == 0.0

    start_events = [
        e for e in _events(bus, f"{SOURCE}.out", PROBE_TYPE)
        if e.payload.get("phase") == "start"
    ]
    assert len(start_events) == 2


@pytest.mark.asyncio
async def test_perturbation_after_withdrawal_waits_for_separation(owner_factory):
    clock = FakeClock()
    drive = FakeDrive()
    bus = FakeBus()
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
        bus=bus,
        drive=drive,
        config=config,
    )
    dt = 1.0

    # Run into the first withdrawal.
    for i in range(int(config.readout_period_seconds / dt) + 1):
        clock.t = i * dt
        await owner.step()

    assert owner._probe_state == "withdrawal"
    start_t = clock.t

    # Let the withdrawal finish normally.
    while clock.t < start_t + config.withdrawal_seconds:
        clock.t += dt
        await owner.step()

    assert owner._probe_state == "idle"
    end_t = clock.t

    # Force a perturbation to be "due" immediately after the withdrawal ends.
    owner._next_perturbation_at = end_t + 0.1

    # It must not start before the separation window closes.
    separation = max(60.0, config.withdrawal_seconds)
    earliest = end_t + separation

    clock.t = end_t + 0.1
    await owner.step()
    assert owner._probe_state == "idle"

    while clock.t + dt < earliest:
        clock.t += dt
        await owner.step()
        assert owner._probe_state == "idle"

    clock.t = earliest
    await owner.step()
    assert owner._probe_state == "perturbation"
    assert drive.scale == 1.0

    starts = [
        e
        for e in _events(bus, f"{SOURCE}.out", PROBE_TYPE)
        if e.payload.get("phase") == "start"
        and e.payload.get("kind") == "perturbation"
    ]
    assert len(starts) == 1


@pytest.mark.asyncio
async def test_pause_does_not_burst_readouts(owner_factory):
    clock = FakeClock()
    bus = FakeBus()
    paused = {"value": False}
    config = _config(readout_period_seconds=1.0, sample_hz=10.0)

    owner = owner_factory(
        clock=clock,
        bus=bus,
        is_paused=lambda: paused["value"],
        config=config,
    )
    dt = 1.0 / config.sample_hz

    # Produce the first readout.
    for i in range(int(config.readout_period_seconds / dt) + 1):
        clock.t = i * dt
        await owner.step()

    readouts = _events(bus, f"{SOURCE}.out", READINESS_TYPE)
    assert len(readouts) == 1

    # Pause across several readout periods, then take one unpaused step.
    paused["value"] = True
    clock.t += 5.0

    paused["value"] = False
    await owner.step()

    readouts = _events(bus, f"{SOURCE}.out", READINESS_TYPE)
    assert len(readouts) == 2


@pytest.mark.asyncio
async def test_plv_pairing_ignores_missing_beat_phases(owner_factory):
    clock = FakeClock()
    drive = FakeDrive()
    bus = FakeBus()
    config = _config(
        readout_period_seconds=5.0,
        sample_hz=10.0,
        withdrawal_period_seconds=5.0,
        withdrawal_seconds=2.0,
    )

    calls = {"n": 0}

    def beat():
        calls["n"] += 1
        if calls["n"] % 2:
            raise RuntimeError("missing beat")
        return clock.t * 2 * np.pi

    soma = FakeSoma()

    def soma_state():
        return (clock.t * 2 * np.pi, 1.0)

    soma.self_rhythm_state = soma_state  # type: ignore[method-assign]

    owner = owner_factory(
        clock=clock,
        bus=bus,
        drive=drive,
        soma=soma,
        beat_phase=beat,
        config=config,
    )
    dt = 1.0 / config.sample_hz

    for i in range(int(config.readout_period_seconds / dt) + 1):
        clock.t = i * dt
        await owner.step()

    assert owner._probe_state == "withdrawal"

    start_t = clock.t
    while clock.t < start_t + config.withdrawal_seconds + dt / 2:
        clock.t += dt
        await owner.step()

    assert owner._endogenous_self_sustain is True
    assert owner._entrain_then_autonomy is True


@pytest.mark.asyncio
async def test_comparison_window_ignores_perturbation_samples(owner_factory):
    clock = FakeClock()
    drive = FakeDrive()
    bus = FakeBus()
    config = _config(
        readout_period_seconds=100.0,
        sample_hz=1.0,
        withdrawal_period_seconds=100.0,
        withdrawal_seconds=2.0,
    )

    owner = owner_factory(
        clock=clock,
        bus=bus,
        drive=drive,
        soma=FakeSoma(amplitude=0.2),
        config=config,
    )

    start_t = 50.0
    duration = config.withdrawal_seconds

    # Seed idle samples in the driven window with low amplitude.
    for i in range(int(duration * config.sample_hz)):
        t = start_t - duration + i / config.sample_hz
        owner._samples.append((t, 0.0, 0.1, 0.0, "idle"))

    # Contaminate the same window with high-amplitude perturbation samples.
    for i in range(int(duration * config.sample_hz * 2)):
        t = start_t - duration + i / (config.sample_hz * 2)
        owner._samples.append((t, 0.0, 1.0, None, "perturbation"))

    # Bypass the post-boot settle window and start the withdrawal.
    owner._settle_until = 0.0
    owner._next_withdrawal_at = start_t
    clock.t = start_t
    await owner.step()
    assert owner._probe_state == "withdrawal"

    dt = 1.0 / config.sample_hz
    while clock.t < start_t + duration:
        clock.t += dt
        await owner.step()

    # The high-amplitude perturbation samples must not enter the comparison
    # window, otherwise self-sustain would be reported as False.
    assert owner._endogenous_self_sustain is True
    assert owner._entrain_then_autonomy is True


@pytest.mark.asyncio
async def test_neither_probe_kind_starves_the_other(owner_factory):
    # With withdrawals due constantly, the more-overdue rule still lets the
    # perturbation run once it has waited longest.
    clock = FakeClock()
    bus = FakeBus()
    config = _config(
        readout_period_seconds=1.0,
        sample_hz=1.0,
        withdrawal_period_seconds=1.0,
        withdrawal_seconds=1.0,
        perturbation_period_seconds=1.0,
        perturbation_seconds=1.0,
    )
    owner = owner_factory(clock=clock, bus=bus, drive=FakeDrive(), config=config)
    kinds = []
    for i in range(400):
        clock.t = float(i)
        await owner.step()
        if owner._probe_state != "idle" and (not kinds or kinds[-1] != owner._probe_state):
            kinds.append(owner._probe_state)
    assert "withdrawal" in kinds and "perturbation" in kinds


@pytest.mark.asyncio
async def test_an_unreadable_pause_state_counts_as_frozen(owner_factory):
    # If the frozen state cannot be read, the owner must assume the entity is
    # frozen: no probe starts, and a running probe is aborted.
    clock = FakeClock()
    bus = FakeBus()
    drive = FakeDrive()
    config = _config(readout_period_seconds=1.0, sample_hz=1.0, withdrawal_seconds=5.0)
    broken = {"on": False}

    def is_paused() -> bool:
        if broken["on"]:
            raise RuntimeError("control file unreadable")
        return False

    owner = owner_factory(
        clock=clock, bus=bus, drive=drive, config=config, is_paused=is_paused
    )
    for i in range(3):
        clock.t = float(i)
        await owner.step()
    assert owner._probe_state == "withdrawal"
    broken["on"] = True
    clock.t = 3.0
    await owner.step()
    assert owner._probe_state == "idle"
    assert drive.scale == config.baseline_drive_fraction


def test_an_absent_readout_table_means_the_defaults() -> None:
    assert GestationReadoutConfig.from_dict(None) == GestationReadoutConfig()
