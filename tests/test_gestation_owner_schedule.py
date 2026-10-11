# SPDX-License-Identifier: LicenseRef-CAL-0.4
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

    async def read_entries(
        self, stream: str, last_id: str = "0", count: int = 100
    ) -> tuple[list[tuple[str, Event]], str | None]:
        result = await self.read(stream, last_id, count)
        # Every fake entry decodes, so the last scanned id is the last returned.
        return result, result[-1][0] if result else None

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
    sample_hz = float(overrides.get("sample_hz", 10.0))
    band_high = min(2.0, 0.4 * sample_hz)
    band_low = min(0.3, band_high / 4.0)
    defaults: dict[str, Any] = {
        # These tests exercise one withdrawal's entrainment test; replication
        # across consecutive withdrawals is tested in
        # tests/test_gestation_entrainment_replication.py.
        "entrainment_replications": 1.0,
        # The fake surrogate provider below supplies three foreign mothers.
        "surrogate_count": 3.0,
        "readout_period_seconds": 10.0,
        "sample_hz": sample_hz,
        "withdrawal_period_seconds": 10.0,
        "withdrawal_seconds": 5.0,
        "perturbation_period_seconds": 20.0,
        "perturbation_seconds": 2.0,
        "baseline_drive_fraction": 0.5,
        "hrv_window_seconds": 10.0,
        "recovery_tolerance": 0.25,
        "recovery_cap_seconds": 30.0,
        "probe_jitter_fraction": 0.0,
        "entrainment_window_seconds": 300.0,
        "entrainment_band_low_hz": band_low,
        "entrainment_band_high_hz": band_high,
        "edge_trim_seconds": 2.0,
        "frequency_pull_floor": 0.5,
        "baseline_withdrawals": 3.0,
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
        surrogate_beat_phases: Any = None,
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
            surrogate_beat_phases=surrogate_beat_phases,
            is_paused=is_paused,
            config=config,
            clock=clock,
            state_path=state_path,
        )

    return _make


def _beat_phase(clock: FakeClock, freq: float = 1.0) -> Any:
    return lambda: clock.t * 2.0 * np.pi * freq


def _surrogate_phases(
    clock: FakeClock,
    freqs: tuple[float, ...] = (0.8, 1.2, 1.4),
    offsets: tuple[float, ...] = (0.0, 0.5, 1.0),
) -> Any:
    return lambda: tuple(
        clock.t * 2.0 * np.pi * f + off for f, off in zip(freqs, offsets)
    )


def _make_locking_callbacks(
    owner: GestationOwner,
    clock: FakeClock,
    *,
    beat_freq: float = 1.0,
    own_freq: float = 0.6,
    amplitude: float = 1.0,
    withdrawal_amplitude: float | None = None,
) -> tuple[Any, Any]:
    phase = 0.0
    last_t: float | None = None

    def _freq() -> float:
        target = int(owner._config.baseline_withdrawals)
        return own_freq if owner._self_rhythm_baseline_count < target else beat_freq

    def _amp() -> float:
        if owner._self_rhythm_baseline_count < int(owner._config.baseline_withdrawals):
            return amplitude
        if withdrawal_amplitude is not None and owner._probe_state == "withdrawal":
            return withdrawal_amplitude
        return amplitude

    def activity() -> float:
        nonlocal phase, last_t
        t = clock.t
        freq = _freq()
        if last_t is None:
            phase = 0.0
        else:
            phase += 2.0 * np.pi * freq * (t - last_t)
        last_t = t
        return 0.5 + 0.5 * np.cos(phase)

    def state() -> tuple[float, float]:
        return (0.0, _amp())

    return activity, state


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
    assert drive.scale == config.perturbation_drive_fraction

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
        readout_period_seconds=20.0,
        sample_hz=10.0,
        withdrawal_period_seconds=20.0,
        withdrawal_seconds=5.0,
        perturbation_period_seconds=1.0e9,
        perturbation_seconds=1.0,
        entrainment_window_seconds=10.0,
        edge_trim_seconds=1.0,
        baseline_withdrawals=1.0,
        frequency_pull_floor=0.5,
    )

    calls = {"n": 0}

    def beat():
        calls["n"] += 1
        if calls["n"] % 10 == 0:
            raise RuntimeError("missing beat")
        return clock.t * 2.0 * np.pi

    owner = owner_factory(
        clock=clock,
        bus=bus,
        drive=drive,
        beat_phase=beat,
        surrogate_beat_phases=_surrogate_phases(clock),
        config=config,
    )

    soma = owner._soma
    activity_fn, state_fn = _make_locking_callbacks(
        owner, clock, beat_freq=1.0, own_freq=0.6, amplitude=1.0
    )
    soma.self_rhythm_activity = activity_fn
    soma.self_rhythm_state = state_fn

    dt = 1.0 / config.sample_hz

    # First withdrawal: baseline withdrawn frequency is the own rhythm.
    for i in range(int(config.readout_period_seconds / dt) + 1):
        clock.t = i * dt
        await owner.step()

    assert owner._probe_state == "withdrawal"
    while owner._probe_state == "withdrawal":
        clock.t += dt
        await owner.step()

    # Second withdrawal: rhythm is locked to the beat; some beat samples are missing.
    while owner._probe_state != "withdrawal":
        clock.t += dt
        await owner.step()

    start_t = clock.t
    while owner._probe_state == "withdrawal":
        clock.t += dt
        await owner.step()

    assert owner._endogenous_self_sustain is True
    assert owner._entrain_then_autonomy is True

    from kaine.cycle.gestation import entrainment_plv

    window = config.entrainment_window_seconds
    trim_samples = int(config.edge_trim_seconds * config.sample_hz)
    valid_idle = [
        s
        for s in owner._samples
        if start_t - window <= s[0] < start_t
        and s[4] == "idle"
        and s[5] is not None
        and s[3] is not None
        and s[6] is not None
        and all(x is not None for x in s[6])
    ]
    acts = np.array([s[5] for s in valid_idle], dtype=float)
    beats = np.array([s[3] for s in valid_idle], dtype=float)
    surrs = [
        np.array([s[6][i] for s in valid_idle], dtype=float)
        for i in range(len(valid_idle[0][6]))
    ]
    expected_plv, expected_max = entrainment_plv(
        acts,
        beats,
        surrs,
        config.sample_hz,
        config.entrainment_band_low_hz,
        config.entrainment_band_high_hz,
        trim_samples,
    )

    assert owner._entrainment_plv == pytest.approx(float(expected_plv))
    assert owner._entrainment_plv_surrogate_max == pytest.approx(float(expected_max))


@pytest.mark.asyncio
async def test_comparison_window_ignores_perturbation_samples(owner_factory):
    """Probe samples never enter the comparisons: self-sustain skips them, and a
    probe inside the entrainment window makes that measurement inconclusive."""
    clock = FakeClock()
    drive = FakeDrive()
    bus = FakeBus()
    config = _config(
        readout_period_seconds=1000.0,
        sample_hz=10.0,
        withdrawal_period_seconds=1000.0,
        withdrawal_seconds=2.0,
        perturbation_period_seconds=1000.0,
        perturbation_seconds=1.0,
        entrainment_window_seconds=2.0,
        edge_trim_seconds=0.5,
        baseline_withdrawals=1.0,
        frequency_pull_floor=0.5,
    )

    owner = owner_factory(
        clock=clock,
        bus=bus,
        drive=drive,
        surrogate_beat_phases=_surrogate_phases(clock),
        config=config,
    )

    owner._settle_until = 0.0
    start_t = 20.0
    duration = config.withdrawal_seconds
    hz = config.sample_hz

    def activity(t: float, f: float = 1.0) -> float:
        return 0.5 + 0.5 * np.cos(2.0 * np.pi * f * t)

    def beat(t: float) -> float:
        return 2.0 * np.pi * t

    def surrs(t: float) -> tuple[float, ...]:
        return tuple(
            2.0 * np.pi * f * t + off
            for f, off in zip((0.8, 1.2, 1.4), (0.0, 0.5, 1.0))
        )

    samples: list[tuple] = []

    # Driven idle samples in the comparison/entrainment window.
    for i in range(int(duration * hz)):
        t = start_t - duration + i / hz
        samples.append((t, 0.0, 1.0, beat(t), "idle", activity(t), surrs(t)))

    # Perturbation samples that would corrupt self-sustain if included.
    for i in range(int(duration * hz * 2)):
        t = start_t - duration + i / (hz * 2)
        samples.append((t, 0.0, 10.0, None, "perturbation", activity(t, f=0.3), None))

    # Withdrawal samples.
    for i in range(int(duration * hz)):
        t = start_t + i / hz
        samples.append((t, 0.0, 1.0, beat(t), "withdrawal", activity(t), surrs(t)))

    samples.sort(key=lambda s: s[0])
    owner._samples = samples
    owner._next_withdrawal_at = start_t
    owner._self_rhythm_baseline_hz = 0.6
    owner._self_rhythm_baseline_count = 1

    await owner._compute_withdrawal_markers(start_t, start_t + duration)

    mixed = {
        "sustain": owner._endogenous_self_sustain,
        "marker": owner._entrain_then_autonomy,
        "plv": owner._entrainment_plv,
        "max": owner._entrainment_plv_surrogate_max,
        "fw": owner._self_rhythm_freq_withdrawn,
        "pull": owner._frequency_pull,
    }

    # Recompute after dropping the perturbation samples entirely.
    owner._samples = [s for s in samples if s[4] != "perturbation"]
    owner._self_rhythm_baseline_hz = 0.6
    owner._self_rhythm_baseline_count = 1
    await owner._compute_withdrawal_markers(start_t, start_t + duration)

    assert owner._endogenous_self_sustain is True
    assert owner._entrain_then_autonomy is True

    # Self-sustain still ignores probe samples.
    assert mixed["sustain"] == owner._endogenous_self_sustain
    # A probe inside the entrainment window is never spliced over: the window
    # must be one contiguous idle run, so the entrainment measurement is
    # inconclusive rather than computed across the gap.
    assert mixed["plv"] is None
    assert mixed["marker"] is None


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
