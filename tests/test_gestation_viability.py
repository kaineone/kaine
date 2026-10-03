# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for gestation viability watch."""

from __future__ import annotations

from pathlib import Path

import pytest

from kaine.bus.schema import Event
from kaine.cycle.gestation import (
    SOURCE,
    GestationOwner,
    GestationReadoutConfig,
    assess_viability,
)

CFG = GestationReadoutConfig.from_dict({})


def _history_none(t_hours: float) -> list[dict]:
    n = int(t_hours / 0.5) + 1
    return [{"lived_hours": i * 0.5, "pull": None} for i in range(n)]


def _history_flat(t_hours: float, pull: float = 0.05) -> list[dict]:
    n = int(t_hours / 0.5) + 1
    return [
        {"lived_hours": i * 0.5, "pull": pull + (0.001 if i % 2 else -0.001)}
        for i in range(n)
    ]


def _history_slow_learner(t_hours: float) -> list[dict]:
    def pull(t: float) -> float:
        if t <= 24.0:
            return 0.2 * t / 24.0
        if t <= 48.0:
            return 0.2 + 0.3 * (t - 24.0) / 24.0
        return 0.5

    n = int(t_hours / 0.5) + 1
    return [{"lived_hours": i * 0.5, "pull": pull(i * 0.5)} for i in range(n)]


def _history_rising_then_flat(t_hours: float) -> list[dict]:
    rise_until = 30.0
    plateau = 0.2

    def pull(t: float) -> float:
        if t >= rise_until:
            return plateau
        return plateau * t / rise_until

    n = int(t_hours / 0.5) + 1
    return [{"lived_hours": i * 0.5, "pull": pull(i * 0.5)} for i in range(n)]


def test_r0_fires_at_six_hours() -> None:
    v = assess_viability(_history_none(6.0), 6.0, False, CFG)
    assert v is not None
    assert v["verdict"] == "unviable"
    assert v["rule"] == "R0"
    assert v["evidence"]["conclusive_count"] == 0


def test_r0_not_before_six_hours() -> None:
    assert assess_viability(_history_none(5.5), 5.5, False, CFG) is None


def test_r1_fires_for_flat_history_at_twenty_four_hours() -> None:
    v = assess_viability(_history_flat(24.0), 24.0, False, CFG)
    assert v is not None
    assert v["rule"] == "R1"
    assert v["evidence"]["median_pull"] < CFG.viability_r1_pull
    assert v["evidence"]["slope_per_hour"] <= CFG.viability_r1_slope_per_hour


@pytest.mark.parametrize(
    "t_hours",
    [24.0, 30.0, 36.0, 42.0, 44.5, 48.0, 54.0, 60.0],
)
def test_slow_learner_80_bpm_does_not_fire_when_replicated_at_45h(t_hours: float) -> None:
    ever_replicated = t_hours >= 45.0
    assert (
        assess_viability(_history_slow_learner(t_hours), t_hours, ever_replicated, CFG)
        is None
    )


def test_r2_fires_at_forty_eight_hours() -> None:
    assert assess_viability(_history_rising_then_flat(24.0), 24.0, False, CFG) is None
    v = assess_viability(_history_rising_then_flat(48.0), 48.0, False, CFG)
    assert v is not None
    assert v["rule"] == "R2"
    assert v["evidence"]["median_pull"] < CFG.viability_r2_pull


def test_r3_fires_at_sixty_hours_with_high_pull() -> None:
    hist = [{"lived_hours": i * 0.5, "pull": 0.9} for i in range(121)]
    v = assess_viability(hist, 60.0, False, CFG)
    assert v is not None
    assert v["rule"] == "R3"


def test_ever_replicated_suppresses_r1_r2_r3() -> None:
    hist = [{"lived_hours": i * 0.5, "pull": 0.9} for i in range(121)]
    assert assess_viability(hist, 60.0, True, CFG) is None


def test_ever_replicated_suppresses_r1_for_a_flat_history() -> None:
    # The same flat history that triggers R1 must not trigger it once the
    # gestation has replicated: R1-R3 apply only before any replicated pass.
    cfg = CFG
    assert assess_viability(_history_flat(24.0), 24.0, False, cfg)["rule"] == "R1"
    assert assess_viability(_history_flat(24.0), 24.0, True, cfg) is None


def test_viability_watch_default_true() -> None:
    assert CFG.viability_watch is True


def test_viability_watch_must_be_bool() -> None:
    with pytest.raises(ValueError, match="viability_watch must be a bool"):
        GestationReadoutConfig.from_dict({"viability_watch": 1})


def test_viability_hour_ordering_required() -> None:
    with pytest.raises(ValueError, match="viability_r0_hours"):
        GestationReadoutConfig.from_dict(
            {"viability_r0_hours": 24.0, "viability_r1_hours": 24.0}
        )
    with pytest.raises(ValueError, match="viability_r2_hours"):
        GestationReadoutConfig.from_dict(
            {"viability_r2_hours": 70.0, "viability_r3_hours": 60.0}
        )
    assert GestationReadoutConfig.from_dict(
        {"viability_r2_hours": 60.0, "viability_r3_hours": 60.0}
    )


def test_viability_min_points_integer_at_least_two() -> None:
    with pytest.raises(ValueError, match="viability_min_points"):
        GestationReadoutConfig.from_dict({"viability_min_points": 1.0})
    with pytest.raises(ValueError, match="viability_min_points"):
        GestationReadoutConfig.from_dict({"viability_min_points": 2.5})
    cfg = GestationReadoutConfig.from_dict({"viability_min_points": 2.0})
    assert cfg.viability_min_points == 2.0


def test_viability_r1_slope_must_be_nonnegative() -> None:
    with pytest.raises(ValueError, match="viability_r1_slope_per_hour"):
        GestationReadoutConfig.from_dict({"viability_r1_slope_per_hour": -0.001})
    cfg = GestationReadoutConfig.from_dict({"viability_r1_slope_per_hour": 0.0})
    assert cfg.viability_r1_slope_per_hour == 0.0


class _FakeClock:
    def __init__(self, t: float) -> None:
        self.t = float(t)

    def __call__(self) -> float:
        return self.t


class _RecordingBus:
    def __init__(self) -> None:
        self.events: list[Event] = []

    async def publish(self, event: Event) -> str:
        self.events.append(event)
        return "1-1"


class _FakeDrive:
    def __init__(self) -> None:
        self.scale = 0.0


class _FakeSoma:
    pass


@pytest.mark.asyncio
async def test_owner_publishes_viability_r1(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state_path = tmp_path / "gestation_readout.json"
    clock = _FakeClock(0.0)
    bus = _RecordingBus()
    drive = _FakeDrive()
    soma = _FakeSoma()
    cfg = GestationReadoutConfig.from_dict({})

    owner = GestationOwner(
        bus,
        soma=soma,
        drive=drive,
        beat_phase=lambda: 0.0,
        is_paused=lambda: False,
        config=cfg,
        clock=clock,
        state_path=state_path,
    )

    # 48 flat withdrawals up to 24 h.
    owner._viability_history = [
        {"lived_hours": i * 0.5, "pull": 0.05} for i in range(48)
    ]
    owner._self_rhythm_baseline_hz = 1.0
    owner._self_rhythm_baseline_count = 3

    monkeypatch.setattr(
        "kaine.cycle.gestation.frequency_pull", lambda *args, **kwargs: 0.05
    )
    monkeypatch.setattr(
        "kaine.cycle.gestation.entrainment_plv", lambda *args, **kwargs: (0.2, 0.5)
    )
    monkeypatch.setattr("kaine.cycle.gestation.self_sustains", lambda *args, **kwargs: True)

    clock.t = 24.5 * 3600.0
    await owner._compute_withdrawal_markers(0.0, 1.0)

    assert owner._viability_verdict is not None
    assert owner._viability_verdict["rule"] == "R1"
    assert (tmp_path / "gestation_viability.json").exists()

    viability_events = [e for e in bus.events if e.type == "gestation.viability"]
    assert len(viability_events) == 1
    assert viability_events[0].source == SOURCE
    assert viability_events[0].payload["rule"] == "R1"
