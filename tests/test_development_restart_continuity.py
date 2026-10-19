# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for developmental readout restart continuity and entrainment-window gating."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

import pytest

from kaine.cycle import development
from kaine.lifecycle import maturation_gate


class FakeClock:
    def __init__(self, t: float = 0.0) -> None:
        self.t = float(t)

    def __call__(self) -> float:
        return self.t


class FakeInteroception:
    def self_rhythm_state(self) -> tuple[float, float] | None:
        return (0.0, 1.0)


class ActiveInteroception(FakeInteroception):
    def self_rhythm_activity(self) -> float:
        return 1.0


class FakeDrive:
    def __init__(self) -> None:
        self.scale = 0.0


class FakeBus:
    def __init__(self) -> None:
        self._counter = 0

    async def publish(self, _event: Any) -> str:
        self._counter += 1
        return str(self._counter)

    async def latest(self, _stream: str) -> tuple[str, Any] | None:
        return None

    async def read_entries(
        self, _stream: str, last_id: str = "0", count: int = 100
    ) -> tuple[list[tuple[str, Any]], str | None]:
        return [], None


def _config(**overrides: Any) -> development.DevelopmentReadoutConfig:
    sample_hz = float(overrides.get("sample_hz", 10.0))
    band_high = min(2.0, 0.4 * sample_hz)
    band_low = min(0.3, band_high / 4.0)
    defaults: dict[str, Any] = {
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
        "entrainment_window_seconds": 10.0,
        "entrainment_band_low_hz": band_low,
        "entrainment_band_high_hz": band_high,
        "edge_trim_seconds": 2.0,
        "frequency_pull_floor": 0.5,
        "baseline_withdrawals": 3.0,
        "surrogate_count": 1.0,
    }
    defaults.update(overrides)
    return development.DevelopmentReadoutConfig.from_dict(defaults)


def _owner(
    tmp_path: Path,
    bus: Any = None,
    seed: int = 0,
    is_paused: Callable[[], bool] | None = None,
    interoception: Any = None,
    **cfg_overrides: Any,
) -> development.DevelopmentOwner:
    clock = FakeClock(0.0)
    config = _config(**cfg_overrides)
    if interoception is None:
        interoception = FakeInteroception()
    owner = development.DevelopmentOwner(
        bus=bus,
        interoception=interoception,
        drive=FakeDrive(),
        beat_phase=lambda: 0.0,
        is_paused=(is_paused if is_paused is not None else lambda: False),
        config=config,
        clock=clock,
        seed=seed,
        state_path=tmp_path / "development.json",
    )
    owner._self_rhythm_baseline_hz = 1.17
    owner._self_rhythm_baseline_count = 3
    return owner


def _prefill_samples(owner: development.DevelopmentOwner) -> None:
    dt = 1.0 / owner._config.sample_hz
    stop = int(15.0 * owner._config.sample_hz)
    for i in range(stop):
        t = i * dt
        state = "idle" if t < 10.0 else "withdrawal"
        owner._samples.append((t, 0.0, 1.0, 0.0, state, 1.0, (0.0,)))


def _patch_outcome(
    monkeypatch: pytest.MonkeyPatch,
    outcome: tuple[float | None, float | None] | None,
) -> None:
    monkeypatch.setattr(development, "self_sustains", lambda _driven, _withdrawn: True)
    monkeypatch.setattr(development, "withdrawn_frequency", lambda *_a, **_k: 1.17)
    monkeypatch.setattr(development, "beat_frequency", lambda *_a, **_k: 1.17)
    monkeypatch.setattr(development, "frequency_pull", lambda *_a, **_k: 0.9)

    if outcome is None:
        monkeypatch.setattr(development, "entrainment_plv", lambda *_a, **_k: (None, None))
    else:
        monkeypatch.setattr(development, "entrainment_plv", lambda *_a, **_k: outcome)


@pytest.mark.asyncio
async def test_withdrawal_waits_the_entrainment_window_after_boot(
    tmp_path: Path,
) -> None:
    owner = _owner(
        tmp_path,
        bus=FakeBus(),
        readout_period_seconds=10.0,
        withdrawal_period_seconds=10.0,
        probe_jitter_fraction=0.0,
        entrainment_window_seconds=120.0,
        perturbation_period_seconds=20.0,
    )
    withdrawals: list[float] = []
    perturbations: list[float] = []
    prev_state = owner._probe_state
    for _ in range(201):
        await owner.step()
        clock = owner._clock
        if owner._probe_state == "withdrawal" and prev_state != "withdrawal":
            withdrawals.append(clock.t)
        if owner._probe_state == "perturbation" and prev_state != "perturbation":
            perturbations.append(clock.t)
        prev_state = owner._probe_state
        clock.t += 1.0
    assert withdrawals and withdrawals[0] >= 120.0
    assert perturbations and perturbations[0] < 120.0


@pytest.mark.asyncio
async def test_withdrawal_waits_again_after_a_thaw(tmp_path: Path) -> None:
    paused = False

    def is_paused() -> bool:
        return paused

    owner = _owner(
        tmp_path,
        bus=FakeBus(),
        readout_period_seconds=10.0,
        withdrawal_period_seconds=10.0,
        probe_jitter_fraction=0.0,
        entrainment_window_seconds=60.0,
        perturbation_period_seconds=20.0,
        is_paused=is_paused,
    )
    withdrawals: list[float] = []
    prev_state = owner._probe_state
    for i in range(201):
        if i == 100:
            paused = True
        if i == 120:
            paused = False
        await owner.step()
        if owner._probe_state == "withdrawal" and prev_state != "withdrawal":
            withdrawals.append(owner._clock.t)
        prev_state = owner._probe_state
        owner._clock.t += 1.0
    assert not any(120.0 <= t < 180.0 for t in withdrawals)
    assert any(t <= 200.0 for t in withdrawals)


@pytest.mark.asyncio
async def test_restart_continues_the_jitter_draws(tmp_path: Path) -> None:
    owner_a = _owner(tmp_path, seed=7, probe_jitter_fraction=0.25)
    a_first = owner_a._next_withdrawal_at - owner_a._started_at
    a_counter = owner_a._jitter_counter_withdrawal
    owner_a._jitter_unit("withdrawal")
    owner_a._jitter_unit("withdrawal")
    owner_a._jitter_unit("withdrawal")
    assert owner_a._jitter_counter_withdrawal == a_counter + 3
    owner_a._persist_progress()

    owner_b = _owner(tmp_path, seed=7, probe_jitter_fraction=0.25)
    assert owner_b._jitter_counter_withdrawal == owner_a._jitter_counter_withdrawal + 1
    b_first = owner_b._next_withdrawal_at - owner_b._started_at
    assert b_first != a_first


@pytest.mark.asyncio
async def test_restart_keeps_a_pass_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner_a = _owner(tmp_path, entrainment_replications=3.0)
    _prefill_samples(owner_a)
    _patch_outcome(monkeypatch, (0.9, 0.3))
    await owner_a._compute_withdrawal_markers(10.0, 15.0)
    await owner_a._compute_withdrawal_markers(10.0, 15.0)
    assert owner_a._entrainment_consecutive_passes == 2
    assert owner_a._entrain_then_autonomy is False
    assert owner_a._endogenous_self_sustain is True
    owner_a._persist_progress()

    owner_b = _owner(tmp_path, entrainment_replications=3.0)
    assert owner_b._entrainment_consecutive_passes == 2
    assert owner_b._entrain_then_autonomy is False
    assert owner_b._endogenous_self_sustain is True
    readout = owner_b.readout()
    assert readout["entrain_then_autonomy"] is False
    assert readout["endogenous_self_sustain"] is True

    _prefill_samples(owner_b)
    _patch_outcome(monkeypatch, (0.9, 0.3))
    await owner_b._compute_withdrawal_markers(10.0, 15.0)
    assert owner_b._entrainment_consecutive_passes == 3
    assert owner_b._entrain_then_autonomy is True


@pytest.mark.asyncio
async def test_a_restart_neither_resets_nor_repeats_a_pass_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[Any] = []

    def fake_entrainment_plv(*args: Any, **kwargs: Any) -> tuple[float, float]:
        calls.append((args, kwargs))
        return (0.9, 0.3)

    monkeypatch.setattr(development, "self_sustains", lambda _driven, _withdrawn: True)
    monkeypatch.setattr(development, "withdrawn_frequency", lambda *_a, **_k: 1.17)
    monkeypatch.setattr(development, "beat_frequency", lambda *_a, **_k: 1.17)
    monkeypatch.setattr(development, "frequency_pull", lambda *_a, **_k: 0.9)
    monkeypatch.setattr(development, "entrainment_plv", fake_entrainment_plv)

    cfg: dict[str, Any] = {
        "readout_period_seconds": 10.0,
        "sample_hz": 10.0,
        "withdrawal_period_seconds": 10.0,
        "withdrawal_seconds": 5.0,
        "probe_jitter_fraction": 0.0,
        "perturbation_period_seconds": 100000.0,
        "entrainment_window_seconds": 30.0,
        "edge_trim_seconds": 2.0,
        "entrainment_replications": 3.0,
    }

    owner_a = _owner(
        tmp_path,
        bus=FakeBus(),
        interoception=ActiveInteroception(),
        **cfg,
    )
    owner_a._entrainment_consecutive_passes = 2
    owner_a._entrain_then_autonomy = False
    owner_a._endogenous_self_sustain = True
    owner_a._persist_progress()
    a_counter = owner_a._jitter_counter_withdrawal

    owner_b = _owner(
        tmp_path,
        bus=FakeBus(),
        interoception=ActiveInteroception(),
        **cfg,
    )
    assert owner_b._entrainment_consecutive_passes == 2
    assert owner_b._jitter_counter_withdrawal == a_counter + 1

    withdrawals: list[float] = []
    prev_state = owner_b._probe_state
    for _ in range(600):
        await owner_b.step()
        if owner_b._probe_state == "withdrawal" and prev_state != "withdrawal":
            withdrawals.append(owner_b._clock.t)
        if prev_state == "withdrawal" and owner_b._probe_state != "withdrawal":
            break
        prev_state = owner_b._probe_state
        owner_b._clock.t += 0.1

    assert withdrawals and withdrawals[0] >= 30.0
    assert calls
    assert owner_b._entrainment_consecutive_passes == 3
    assert owner_b._entrain_then_autonomy is True


@pytest.mark.asyncio
async def test_older_progress_file_migrates(tmp_path: Path) -> None:
    probe_owner = _owner(tmp_path)
    key = probe_owner._baseline_key
    progress_path = tmp_path / "development_progress.json"

    progress_path.write_text(
        json.dumps(
            {
                "key": key,
                "awake_seconds": 100.0,
                "consecutive_passes": 3,
                "viability_history": [],
                "ever_replicated": True,
                "viability_verdict": None,
            }
        ),
        encoding="utf-8",
    )
    owner = _owner(tmp_path)
    assert owner._jitter_counter_withdrawal == 1
    assert owner._jitter_counter_perturbation == 1
    assert owner._entrain_then_autonomy is True
    assert owner._endogenous_self_sustain is None

    progress_path.write_text(
        json.dumps(
            {
                "key": key,
                "awake_seconds": 100.0,
                "consecutive_passes": 1,
                "viability_history": [],
                "ever_replicated": True,
                "viability_verdict": None,
            }
        ),
        encoding="utf-8",
    )
    owner_one = _owner(tmp_path)
    assert owner_one._entrain_then_autonomy is None

    owner._persist_progress()
    data = json.loads(progress_path.read_text(encoding="utf-8"))
    assert "jitter_counters" in data
    assert "entrain_then_autonomy" in data
    assert "endogenous_self_sustain" in data


def test_hrv_floor_default_is_below_fetal_values() -> None:
    assert maturation_gate.RegulationThresholds().hrv_variability_floor == 0.02


@pytest.mark.asyncio
async def test_progress_from_another_entity_is_ignored(tmp_path: Path) -> None:
    owner_a = _owner(tmp_path)
    key_a = owner_a._baseline_key
    progress_path = tmp_path / "development_progress.json"
    progress_path.write_text(
        json.dumps(
            {
                "key": "some-other-key",
                "awake_seconds": 100.0,
                "consecutive_passes": 3,
                "viability_history": [],
                "ever_replicated": True,
                "viability_verdict": None,
                "jitter_counters": {"withdrawal": 99, "perturbation": 99},
                "entrain_then_autonomy": True,
                "endogenous_self_sustain": True,
            }
        ),
        encoding="utf-8",
    )
    owner_b = _owner(tmp_path)
    assert owner_b._baseline_key == key_a
    assert owner_b._jitter_counter_withdrawal == 1
    assert owner_b._jitter_counter_perturbation == 1
    assert owner_b._entrain_then_autonomy is None
    assert owner_b._endogenous_self_sustain is None
