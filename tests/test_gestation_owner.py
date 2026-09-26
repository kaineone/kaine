# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for GestationOwner step behaviour and probe protocol."""

from __future__ import annotations

import json
from datetime import datetime, timezone
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
async def test_baseline_drive_set_at_construction(owner_factory):
    drive = FakeDrive()
    owner_factory(drive=drive)
    assert drive.scale == 0.5


@pytest.mark.asyncio
async def test_no_probe_in_first_readout_period(owner_factory):
    clock = FakeClock()
    drive = FakeDrive()
    bus = FakeBus()
    owner = owner_factory(clock=clock, bus=bus, drive=drive)
    config = owner._config
    dt = 1.0 / config.sample_hz

    for i in range(int(config.readout_period_seconds / dt)):
        clock.t = i * dt
        await owner.step()

    assert owner._probe_state == "idle"
    assert drive.scale == config.baseline_drive_fraction
    assert len(_events(bus, f"{SOURCE}.out", PROBE_TYPE)) == 0


@pytest.mark.asyncio
async def test_withdrawal_produces_true_markers(owner_factory):
    clock = FakeClock()
    drive = FakeDrive()
    bus = FakeBus()
    config = _config(
        readout_period_seconds=10.0,
        withdrawal_period_seconds=10.0,
        withdrawal_seconds=5.0,
    )

    def beat():
        return clock.t * 2 * np.pi

    soma = FakeSoma(phase=0.0, amplitude=1.0)

    def soma_state():
        return (clock.t * 2 * np.pi, soma.amplitude)

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

    # Run until withdrawal starts at t=10.
    for i in range(int(config.readout_period_seconds / dt) + 1):
        clock.t = i * dt
        await owner.step()

    assert owner._probe_state == "withdrawal"
    assert drive.scale == 0.0

    starts = _events(bus, f"{SOURCE}.out", PROBE_TYPE)
    assert len([e for e in starts if e.payload.get("phase") == "start"]) == 1

    start_t = clock.t
    while clock.t < start_t + config.withdrawal_seconds + dt / 2:
        clock.t += dt
        await owner.step()

    assert owner._probe_state == "idle"
    assert drive.scale == config.baseline_drive_fraction

    ends = _events(bus, f"{SOURCE}.out", PROBE_TYPE)
    end_events = [e for e in ends if e.payload.get("phase") == "end"]
    assert len(end_events) == 1
    assert end_events[0].payload.get("aborted") is False

    assert owner._endogenous_self_sustain is True
    assert owner._entrain_then_autonomy is True


@pytest.mark.asyncio
async def test_withdrawal_false_marker_when_amplitude_drops(owner_factory):
    clock = FakeClock()
    drive = FakeDrive()
    bus = FakeBus()
    config = _config(
        readout_period_seconds=10.0,
        withdrawal_period_seconds=10.0,
        withdrawal_seconds=5.0,
    )

    def beat():
        return clock.t * 2 * np.pi

    soma = FakeSoma(phase=0.0, amplitude=1.0)

    def soma_state():
        phase = clock.t * 2 * np.pi
        amp = 1.0 if clock.t < 10.0 else 0.1
        return (phase, amp)

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

    start_t = clock.t
    while clock.t < start_t + config.withdrawal_seconds + dt / 2:
        clock.t += dt
        await owner.step()

    assert owner._endogenous_self_sustain is False
    assert owner._entrain_then_autonomy is False


@pytest.mark.asyncio
async def test_pause_aborts_withdrawal(owner_factory):
    clock = FakeClock()
    drive = FakeDrive()
    bus = FakeBus()
    config = _config(
        readout_period_seconds=10.0,
        withdrawal_period_seconds=10.0,
        withdrawal_seconds=5.0,
    )
    paused = {"value": False}

    owner = owner_factory(
        clock=clock,
        bus=bus,
        drive=drive,
        soma=FakeSoma(),
        beat_phase=lambda: clock.t * 2 * np.pi,
        is_paused=lambda: paused["value"],
        config=config,
    )
    dt = 1.0 / config.sample_hz

    for i in range(int(config.readout_period_seconds / dt) + 1):
        clock.t = i * dt
        await owner.step()

    assert owner._probe_state == "withdrawal"
    assert drive.scale == 0.0

    paused["value"] = True
    clock.t += dt
    await owner.step()

    assert owner._probe_state == "idle"
    assert drive.scale == config.baseline_drive_fraction

    end_events = [
        e for e in _events(bus, f"{SOURCE}.out", PROBE_TYPE)
        if e.payload.get("phase") == "end"
    ]
    assert len(end_events) == 1
    assert end_events[0].payload.get("aborted") is True

    assert owner._endogenous_self_sustain is None
    assert owner._entrain_then_autonomy is None

    # No further probe starts while paused.
    paused["value"] = True
    for _ in range(int(config.withdrawal_period_seconds / dt) + 5):
        clock.t += dt
        await owner.step()
    assert owner._probe_state == "idle"


def test_withdrawal_seconds_hard_maximum_rejected():
    with pytest.raises(ValueError):
        GestationReadoutConfig.from_dict({"withdrawal_seconds": 31.0})


def test_perturbation_seconds_hard_maximum_rejected():
    with pytest.raises(ValueError):
        GestationReadoutConfig.from_dict({"perturbation_seconds": 11.0})


def test_unknown_keys_rejected():
    with pytest.raises(ValueError):
        GestationReadoutConfig.from_dict({"unknown_key": 1.0})


def test_bool_values_rejected():
    with pytest.raises(ValueError):
        GestationReadoutConfig.from_dict({"withdrawal_seconds": True})


@pytest.mark.asyncio
async def test_readout_persists_topos_baseline(owner_factory, tmp_path: Path):
    clock = FakeClock()
    drive = FakeDrive()
    bus = FakeBus()
    config = _config(
        readout_period_seconds=5.0,
        sample_hz=10.0,
        hrv_window_seconds=5.0,
    )
    state_path = tmp_path / "gestation_readout.json"
    owner = owner_factory(
        clock=clock,
        bus=bus,
        drive=drive,
        soma=FakeSoma(),
        beat_phase=lambda: 0.0,
        config=config,
        state_path=state_path,
    )
    dt = 1.0 / config.sample_hz

    # Initialise cursor.
    await owner.step()

    # Publish three Topos reports in the first readout period.
    for err in [1.0, 1.1, 0.9]:
        event = Event(
            source="topos",
            type="topos.report",
            payload={"prediction_error": err},
            salience=0.5,
            timestamp=datetime.now(timezone.utc),
        )
        await bus.publish(event)

    for i in range(1, int(config.readout_period_seconds / dt) + 1):
        clock.t = i * dt
        await owner.step()

    readout_events = _events(bus, f"{SOURCE}.out", READINESS_TYPE)
    assert len(readout_events) >= 1
    readout = readout_events[0].payload["readout"]
    assert "womb_prediction_error" in readout
    assert readout["womb_prediction_error"] == pytest.approx(1.0)

    data = json.loads(state_path.read_text(encoding="utf-8"))
    assert data["prediction_error_baseline"] == pytest.approx(1.0)

    # Lower errors in the next period produce a falling ratio.
    for err in [0.4, 0.5, 0.6]:
        event = Event(
            source="topos",
            type="topos.report",
            payload={"prediction_error": err},
            salience=0.5,
            timestamp=datetime.now(timezone.utc),
        )
        await bus.publish(event)

    for i in range(
        int(config.readout_period_seconds / dt) + 1,
        int(2 * config.readout_period_seconds / dt) + 1,
    ):
        clock.t = i * dt
        await owner.step()

    readout_events = _events(bus, f"{SOURCE}.out", READINESS_TYPE)
    assert len(readout_events) >= 2
    readout2 = readout_events[1].payload["readout"]
    assert readout2["womb_prediction_error"] == pytest.approx(0.5)


@pytest.mark.asyncio
async def test_new_owner_restores_baseline(owner_factory, tmp_path: Path):
    clock = FakeClock()
    bus = FakeBus()
    state_path = tmp_path / "gestation_readout.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(
        json.dumps({"prediction_error_baseline": 2.0}), encoding="utf-8"
    )

    owner = owner_factory(
        clock=clock,
        bus=bus,
        soma=FakeSoma(),
        beat_phase=lambda: 0.0,
        state_path=state_path,
    )
    assert owner._baseline == pytest.approx(2.0)

    await owner.step()
    for err in [1.0, 1.0, 1.0]:
        event = Event(
            source="topos",
            type="topos.report",
            payload={"prediction_error": err},
            salience=0.5,
            timestamp=datetime.now(timezone.utc),
        )
        await bus.publish(event)

    config = owner._config
    dt = 1.0 / config.sample_hz
    for i in range(1, int(config.readout_period_seconds / dt) + 1):
        clock.t = i * dt
        await owner.step()

    readout = _events(bus, f"{SOURCE}.out", READINESS_TYPE)[0].payload["readout"]
    assert readout["womb_prediction_error"] == pytest.approx(0.5)


@pytest.mark.asyncio
async def test_perturbation_sets_full_drive(owner_factory):
    clock = FakeClock()
    drive = FakeDrive()
    bus = FakeBus()
    config = _config(
        readout_period_seconds=1.0,
        withdrawal_seconds=0.5,
        withdrawal_period_seconds=1.0,
        perturbation_period_seconds=1.0,
        perturbation_seconds=2.0,
        sample_hz=10.0,
    )
    owner = owner_factory(
        clock=clock,
        bus=bus,
        drive=drive,
        soma=FakeSoma(),
        beat_phase=lambda: 0.0,
        config=config,
    )
    dt = 1.0 / config.sample_hz
    first_perturbation = (
        config.readout_period_seconds
        + config.withdrawal_seconds
        + 60.0
    )

    in_perturbation = False
    max_steps = int((first_perturbation + config.perturbation_seconds + 2.0) / dt)
    for i in range(max_steps):
        clock.t = i * dt
        await owner.step()
        if owner._probe_state == "perturbation" and not in_perturbation:
            in_perturbation = True
            assert drive.scale == 1.0
            starts = [
                e
                for e in _events(bus, f"{SOURCE}.out", PROBE_TYPE)
                if e.payload.get("phase") == "start"
                and e.payload.get("kind") == "perturbation"
            ]
            assert len(starts) == 1
            assert starts[0].payload["seconds"] == pytest.approx(
                config.perturbation_seconds
            )
        if in_perturbation and owner._probe_state == "idle":
            break

    assert in_perturbation
    assert drive.scale == config.baseline_drive_fraction
    ends = [
        e
        for e in _events(bus, f"{SOURCE}.out", PROBE_TYPE)
        if e.payload.get("phase") == "end"
        and e.payload.get("kind") == "perturbation"
    ]
    assert len(ends) == 1
    assert ends[0].payload.get("aborted") is False
