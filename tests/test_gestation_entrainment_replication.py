# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for entrainment replication / consecutive-pass gating."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from kaine.cycle import gestation


class FakeClock:
    def __init__(self, t: float = 0.0) -> None:
        self.t = float(t)

    def __call__(self) -> float:
        return self.t


class FakeSoma:
    def self_rhythm_state(self) -> tuple[float, float] | None:
        return (0.0, 1.0)


class FakeDrive:
    def __init__(self) -> None:
        self.scale = 0.0


def _config(**overrides: Any) -> gestation.GestationReadoutConfig:
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
        # The prefilled samples carry one surrogate beat.
        "surrogate_count": 1.0,
    }
    defaults.update(overrides)
    return gestation.GestationReadoutConfig.from_dict(defaults)


def _owner(tmp_path: Path, **cfg_overrides: Any) -> gestation.GestationOwner:
    clock = FakeClock(0.0)
    config = _config(**cfg_overrides)
    owner = gestation.GestationOwner(
        bus=None,
        soma=FakeSoma(),
        drive=FakeDrive(),
        beat_phase=lambda: 0.0,
        is_paused=lambda: False,
        config=config,
        clock=clock,
        seed=0,
        state_path=tmp_path / "gestation.json",
    )
    # Satisfy the baseline-withdrawal requirement so frequency_pull is computed.
    owner._self_rhythm_baseline_hz = 1.17
    owner._self_rhythm_baseline_count = 3
    return owner


def _prefill_samples(owner: gestation.GestationOwner) -> None:
    # idle 0..10 s, then withdrawal 10..15 s at sample_hz.
    dt = 1.0 / owner._config.sample_hz
    stop = int(15.0 * owner._config.sample_hz)
    for i in range(stop):
        t = i * dt
        state = "idle" if t < 10.0 else "withdrawal"
        owner._samples.append((t, 0.0, 1.0, 0.0, state, 1.0, (0.0,)))


def _patch_outcome(monkeypatch: pytest.MonkeyPatch, outcome: tuple[float | None, float | None] | None) -> None:
    monkeypatch.setattr(gestation, "self_sustains", lambda _driven, _withdrawn: True)
    monkeypatch.setattr(gestation, "withdrawn_frequency", lambda *_a, **_k: 1.17)
    monkeypatch.setattr(gestation, "beat_frequency", lambda *_a, **_k: 1.17)
    monkeypatch.setattr(gestation, "frequency_pull", lambda *_a, **_k: 0.9)

    if outcome is None:
        monkeypatch.setattr(gestation, "entrainment_plv", lambda *_a, **_k: (None, None))
    else:
        monkeypatch.setattr(gestation, "entrainment_plv", lambda *_a, **_k: outcome)


@pytest.mark.asyncio
async def test_entrainment_replication_counter_gating(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner = _owner(tmp_path, entrainment_replications=3.0)
    _prefill_samples(owner)

    # Two passes: not yet enough consecutive passes.
    _patch_outcome(monkeypatch, (0.9, 0.3))
    await owner._compute_withdrawal_markers(10.0, 15.0)
    assert owner._entrainment_consecutive_passes == 1
    assert owner._entrain_then_autonomy is False
    assert owner.readout()["entrainment_consecutive_passes"] == 1

    await owner._compute_withdrawal_markers(10.0, 15.0)
    assert owner._entrainment_consecutive_passes == 2
    assert owner._entrain_then_autonomy is False

    # Third consecutive pass flips the marker.
    await owner._compute_withdrawal_markers(10.0, 15.0)
    assert owner._entrainment_consecutive_passes == 3
    assert owner._entrain_then_autonomy is True
    readout = owner.readout()
    assert readout["entrain_then_autonomy"] is True
    assert readout["entrainment_consecutive_passes"] == 3

    # A fail resets the counter and the marker.
    _patch_outcome(monkeypatch, (0.2, 0.3))
    await owner._compute_withdrawal_markers(10.0, 15.0)
    assert owner._entrainment_consecutive_passes == 0
    assert owner._entrain_then_autonomy is False
    readout = owner.readout()
    assert readout["entrainment_consecutive_passes"] == 0
    assert readout["entrain_then_autonomy"] is False


@pytest.mark.asyncio
async def test_none_outcome_resets_counter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    owner = _owner(tmp_path, entrainment_replications=3.0)
    _prefill_samples(owner)

    _patch_outcome(monkeypatch, (0.9, 0.3))
    await owner._compute_withdrawal_markers(10.0, 15.0)
    await owner._compute_withdrawal_markers(10.0, 15.0)
    assert owner._entrainment_consecutive_passes == 2

    _patch_outcome(monkeypatch, None)
    await owner._compute_withdrawal_markers(10.0, 15.0)
    assert owner._entrainment_consecutive_passes == 0
    assert owner._entrain_then_autonomy is None
    assert "entrainment_consecutive_passes" not in owner.readout()


def test_config_rejects_invalid_replication_counts() -> None:
    with pytest.raises(ValueError):
        _config(entrainment_replications=0)

    with pytest.raises(ValueError):
        _config(entrainment_replications=2.5)

    with pytest.raises(ValueError):
        _config(entrainment_replications=True)

    assert _config(entrainment_replications=1.0).entrainment_replications == 1.0
    assert _config(entrainment_replications=3.0).entrainment_replications == 3.0
