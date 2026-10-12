# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Faculty-relative maturation decisions.

A base-thesis entity without the sleep, world model or embodiment modules must still be able to
maturation once developmental readiness (C1, C3) is met. The gate skips the checks
and embodiment guards that depend on absent faculties.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from kaine.bus.schema import Event
from kaine.lifecycle import stage as lifecycle_stage
from kaine.lifecycle.gate_runner import (
    DEFAULT_STIMULUS_SOURCE_READOUT_STREAM,
    MaturationGateRunner,
)
from kaine.lifecycle.maturation_gate import (
    ACTION_HOLD_AWAITING_ACK,
    ACTION_HOLD_AWAITING_EMBODIMENT,
    ACTION_MATURATION,
    REASON_BORN_INTO_PERCEPTUAL_WORLD,
    Faculties,
    MaturationConfig,
    Readiness,
    _evaluate_c2,
    decide_maturation,
    evaluate_readiness,
    maturation_payload,
)

# Re-export under the canonical event name used by other tests.
STAGE_MATURATION = ACTION_MATURATION  # type: ignore[assignment]


@pytest.fixture(autouse=True)
def _patch_stage_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Isolate the stage file path so no test leaks STAGE_PATH globally."""
    monkeypatch.setattr(
        "kaine.lifecycle.stage.STAGE_PATH", tmp_path / "stage.json"
    )


def _make_bus(
    published: list[Event] | None = None,
    readout: dict[str, Any] | None = None,
    sleep_count: int = 0,
    boot_ms: int = 1_000_000,
    stimulus_source_stream: str = DEFAULT_STIMULUS_SOURCE_READOUT_STREAM,
    sleep_stream: str = "hypnos.out",
) -> Any:
    """Return a minimal async bus double with the new cursor API surface."""
    bus = MagicMock()

    async def _publish(event: Event) -> str:
        if published is not None:
            published.append(event)
        return "fake-id"

    bus.publish = _publish

    def _readout_entry() -> tuple[str, Event]:
        return (
            f"{boot_ms + 1}-0",
            Event(
                source="gestation",
                type="gestation.readiness",
                payload={"readout": readout},
                salience=0.5,
                timestamp=datetime.now(timezone.utc),
            ),
        )

    async def _latest(stream: str) -> tuple[str, Event] | None:
        if stream == stimulus_source_stream and readout is not None:
            return _readout_entry()
        return None

    bus.latest = AsyncMock(side_effect=_latest)

    async def _range(
        stream: str, start: str = "-", end: str = "+", count: int | None = None
    ) -> list[tuple[str, Event]]:
        if stream == stimulus_source_stream and readout is not None:
            return [_readout_entry()]
        return []

    bus.range = AsyncMock(side_effect=_range)

    async def _server_time_ms() -> int:
        return boot_ms

    bus.server_time_ms = AsyncMock(side_effect=_server_time_ms)

    sleep_events = [
        (
            f"{i + 1}-0",
            Event(
                source="hypnos",
                type="hypnos.sleep.completed",
                payload={},
                salience=0.5,
                timestamp=datetime.now(timezone.utc),
            ),
        )
        for i in range(sleep_count)
    ]

    async def _read_entries(
        stream: str, last_id: str = "0", count: int = 100, block_ms: int = 0
    ) -> tuple[list[tuple[str, Event]], str | None]:
        if stream != sleep_stream:
            return [], None

        start: tuple[int, int]
        if last_id in ("0", "0-0"):
            start = (0, 0)
        else:
            start = tuple(int(part) for part in last_id.split("-"))  # type: ignore[assignment]

        def _key(entry: tuple[str, Event]) -> tuple[int, int]:
            return tuple(int(part) for part in entry[0].split("-"))  # type: ignore[return-value]

        filtered = [entry for entry in sleep_events if _key(entry) > start]
        if not filtered:
            return [], None
        return filtered, filtered[-1][0]

    bus.read_entries = AsyncMock(side_effect=_read_entries)
    bus.client = MagicMock()
    return bus


def _make_base_registry() -> Any:
    """A registry with no sleep, world model or embodiment modules — base-thesis-like."""
    registry = MagicMock()
    registry.__contains__.return_value = False
    registry.get.return_value = None
    return registry


def _make_embodiment_only_registry() -> Any:
    """A registry that contains embodiment but no sleep or Phantasia."""
    registry = MagicMock()
    embodiment = MagicMock()
    embodiment.enabled_by_config = True
    embodiment.probe_available = AsyncMock(return_value=False)
    embodiment.activate = AsyncMock(return_value=False)
    registry.get.side_effect = lambda name: embodiment if name == "mundus" else None
    registry.__contains__.side_effect = lambda name: name == "mundus"
    return registry


def _make_registry(
    *,
    sleep_count: int = 0,
    consolidation_passes: int = 0,
    embodiment_enabled: bool = False,
    embodiment_approved: bool = False,
    embodiment_reachable: bool = False,
) -> Any:
    registry = MagicMock()

    world_model = MagicMock()
    world_model.successful_training_passes = consolidation_passes
    embodiment = MagicMock()
    embodiment.enabled_by_config = embodiment_enabled
    embodiment.probe_available = AsyncMock(
        return_value=embodiment_enabled and embodiment_approved and embodiment_reachable
    )
    embodiment.activate = AsyncMock(return_value=embodiment_enabled and embodiment_approved)

    def _get(name: str):
        return {"phantasia": world_model, "mundus": embodiment}[name]

    registry.get.side_effect = _get
    registry.__contains__.return_value = True
    return registry


def _make_clock(now: float = 0.0) -> Any:
    clock = MagicMock()
    clock.now = MagicMock(return_value=now)
    return clock


def _fresh_development_state(tmp_path: Path) -> lifecycle_stage.StageState:
    """Build a fresh developmental state without mutating the global STAGE_PATH."""
    p = tmp_path / "stage.json"
    return lifecycle_stage.resolve_boot_stage(has_prior_lived_history=False, path=p)


def _make_ready() -> Readiness:
    """Return a fully ready Readiness object using default faculties."""
    return evaluate_readiness(
        readiness_readout={
            "endogenous_self_sustain": True,
            "entrain_then_autonomy": True,
            "hrv_variability": 0.5,
            "womb_prediction_error": 0.1,
            "return_to_baseline_seconds": 10.0,
        },
        sleep_count=5,
        consolidation_passes=3,
        lived_seconds=100.0,
        config=MaturationConfig(min_lived_seconds=0),
    )


@pytest.mark.parametrize(
    "sleep,world_model,sleep_count,consolidation_passes,expected_met,expected_detail",
    [
        # Neither faculty present: C2 not applicable.
        (False, False, 0, 0, True, "not applicable"),
        (False, True, 0, 0, True, "not applicable"),
        # Only sleep faculty present.
        (True, False, 5, 0, True, "sleep required; evidence present"),
        (True, False, 4, 0, False, "sleep cycles 4 < 5"),
        # Both faculties present: both checks required.
        (True, True, 5, 3, True, "sleep + consolidation required; evidence present"),
        (True, True, 4, 3, False, "sleep cycles 4 < 5"),
        (True, True, 5, 2, False, "consolidation passes 2 < 3"),
    ],
)
def test_c2_faculty_relative_truth_table(
    sleep: bool,
    world_model: bool,
    sleep_count: int,
    consolidation_passes: int,
    expected_met: bool,
    expected_detail: str,
) -> None:
    cfg = MaturationConfig(min_sleep_cycles=5, min_consolidation_passes=3)
    faculties = Faculties(sleep=sleep, world_model=world_model, embodiment=False)
    result = _evaluate_c2(
        sleep_count, consolidation_passes, cfg, faculties=faculties
    )
    assert result.name == "C2_reality_model_consolidated"
    assert result.met is expected_met
    assert expected_detail in result.detail


def test_c2_not_applicable_not_reported_as_passed() -> None:
    """A not-applicable C2 must not appear in passed_markers but must appear in
    not_applicable, while readiness stays ready."""
    cfg = MaturationConfig(min_lived_seconds=0)
    faculties = Faculties(sleep=False, world_model=False, embodiment=False)
    readiness = evaluate_readiness(
        readiness_readout={
            "endogenous_self_sustain": True,
            "entrain_then_autonomy": True,
            "hrv_variability": 0.5,
            "womb_prediction_error": 0.1,
            "return_to_baseline_seconds": 10.0,
        },
        sleep_count=0,
        consolidation_passes=0,
        lived_seconds=0.0,
        config=cfg,
        faculties=faculties,
    )

    assert readiness.ready is True
    assert "C2_reality_model_consolidated" not in readiness.passed_markers
    assert readiness.not_applicable == ("C2_reality_model_consolidated",)

    payload = maturation_payload(
        readiness=readiness,
        sleep_count=0,
        lived_seconds=0.0,
        faculties=faculties,
    )
    assert "C2_reality_model_consolidated" not in payload["passed_markers"]
    assert payload["not_applicable"] == ["C2_reality_model_consolidated"]


def test_default_faculties_c2_is_applicable_and_passed() -> None:
    """With all faculties present and sufficient evidence, C2 is applicable
    and shows up in passed_markers."""
    readiness = _make_ready()
    assert readiness.not_applicable == ()
    assert "C2_reality_model_consolidated" in readiness.passed_markers

    payload = maturation_payload(
        readiness=readiness,
        sleep_count=5,
        lived_seconds=100.0,
    )
    assert payload["not_applicable"] == []
    assert "C2_reality_model_consolidated" in payload["passed_markers"]


def test_decide_maturation_without_embodiment_maturations_into_perceptual_world() -> None:
    ready = _make_ready()
    decision = decide_maturation(
        readiness=ready,
        embodiment_ready=False,  # ignored when the embodiment module is absent
        faculties=Faculties(embodiment=False),
    )
    assert decision.action == ACTION_MATURATION
    assert decision.reason == REASON_BORN_INTO_PERCEPTUAL_WORLD
    assert decision.should_maturation


def test_decide_maturation_without_embodiment_still_awaits_ack() -> None:
    ready = _make_ready()
    decision = decide_maturation(
        readiness=ready,
        embodiment_ready=False,
        require_operator_ack=True,
        operator_ack=False,
        faculties=Faculties(embodiment=False),
    )
    assert decision.action == ACTION_HOLD_AWAITING_ACK
    assert decision.reason == "awaiting_operator_ack"


def test_decide_maturation_with_embodiment_holds_awaiting_embodiment() -> None:
    ready = _make_ready()
    decision = decide_maturation(
        readiness=ready,
        embodiment_ready=False,
        faculties=Faculties(embodiment=True),
    )
    assert decision.action == ACTION_HOLD_AWAITING_EMBODIMENT
    assert decision.holding


def test_maturation_payload_records_world_and_conditions() -> None:
    ready = _make_ready()
    payload = maturation_payload(
        readiness=ready,
        sleep_count=5,
        lived_seconds=100.0,
        faculties=Faculties(sleep=True, world_model=True, embodiment=True),
    )
    assert payload["stage"] == "embodied"
    assert payload["world"] == "embodied"
    assert payload["conditions"] == {
        "c2_sleep_required": True,
        "c2_consolidation_required": True,
    }


def test_maturation_payload_perceptual_world() -> None:
    ready = _make_ready()
    payload = maturation_payload(
        readiness=ready,
        sleep_count=None,
        lived_seconds=100.0,
        faculties=Faculties(sleep=False, world_model=False, embodiment=False),
    )
    assert payload["world"] == "perceptual"
    assert payload["conditions"] == {
        "c2_sleep_required": False,
        "c2_consolidation_required": False,
    }


def test_default_faculties_preserves_existing_c2_and_decision() -> None:
    """Passing no faculties keeps the original three-faculty checks."""
    cfg = MaturationConfig(min_sleep_cycles=5, min_consolidation_passes=3)
    assert _evaluate_c2(5, 3, cfg).met is True

    ready = _make_ready()
    decision = decide_maturation(readiness=ready, embodiment_ready=True)
    assert decision.action == ACTION_MATURATION
    assert decision.reason == "ready_and_available"


@pytest.mark.asyncio
async def test_base_thesis_maturations_into_perceptual_world(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A registry without the sleep, world model and embodiment modules matures into the perceptual
    world without ever probing Mundus."""
    readout = {
        "endogenous_self_sustain": True,
        "entrain_then_autonomy": True,
        "hrv_variability": 0.5,
        "womb_prediction_error": 0.1,
        "return_to_baseline_seconds": 10.0,
    }
    published: list[Event] = []
    bus = _make_bus(published=published, readout=readout, sleep_count=0)
    state = _fresh_development_state(tmp_path)
    runner = MaturationGateRunner(
        bus=bus,
        config=MaturationConfig(
            enabled=True,
            min_sleep_cycles=1,
            min_consolidation_passes=1,
            min_lived_seconds=0,
            gate_cadence_seconds=0.01,
        ),
        registry=_make_base_registry(),
        entity_clock=_make_clock(),
        stage_state=state,
        staging_enabled=True,
        stimulus_source_feed_configured=True,
    )
    runner.set_pause_sources(paused_seconds=lambda: 0.0, is_paused=lambda: False)

    async def _explode() -> tuple[bool, bool, bool]:
        raise RuntimeError("_mundus_availability must not be called")

    runner._embodiment_availability = AsyncMock(side_effect=_explode)

    await runner._evaluate_once()
    await runner._evaluate_once()

    assert runner.stage.is_embodied
    assert not runner.stage.is_gestating
    assert len(published) == 1
    assert published[0].type == "stage.birth"
    assert published[0].payload["world"] == "perceptual"
    assert published[0].payload["conditions"] == {
        "c2_sleep_required": False,
        "c2_consolidation_required": False,
    }
    assert runner._last_status["world"] == "perceptual"
    assert runner._last_status["conditions"] == {
        "c2_sleep_required": False,
        "c2_consolidation_required": False,
    }
    runner._embodiment_availability.assert_not_awaited()


@pytest.mark.asyncio
async def test_embodiment_present_but_unreachable_holds_awaiting_embodiment(
    tmp_path: Path,
) -> None:
    """When the embodiment module is present but unreachable, a ready entity holds in the stimulus source
    and emits stage.birth.ready with reason awaiting_embodiment."""
    readout = {
        "endogenous_self_sustain": True,
        "entrain_then_autonomy": True,
        "hrv_variability": 0.5,
        "womb_prediction_error": 0.1,
        "return_to_baseline_seconds": 10.0,
    }
    published: list[Event] = []
    bus = _make_bus(published=published, readout=readout, sleep_count=0)
    state = _fresh_development_state(tmp_path)
    runner = MaturationGateRunner(
        bus=bus,
        config=MaturationConfig(
            enabled=True,
            min_sleep_cycles=1,
            min_consolidation_passes=1,
            min_lived_seconds=0,
            gate_cadence_seconds=0.01,
        ),
        registry=_make_embodiment_only_registry(),
        entity_clock=_make_clock(),
        stage_state=state,
        staging_enabled=True,
        stimulus_source_feed_configured=True,
    )
    runner.set_pause_sources(paused_seconds=lambda: 0.0, is_paused=lambda: False)
    runner._embodiment_availability = AsyncMock(return_value=(True, True, False))

    await runner._evaluate_once()

    assert runner.stage.is_gestating
    assert not runner.stage.is_embodied
    assert len(published) == 1
    assert published[0].type == "stage.birth.ready"
    assert published[0].payload["reason"] == "awaiting_embodiment"
    runner._embodiment_availability.assert_awaited_once()


@pytest.mark.asyncio
async def test_status_reports_not_applicable_for_base_thesis(
    tmp_path: Path,
) -> None:
    """After evaluating a base-thesis registry, status exposes the perceptual
    world, the faculty-relative conditions, and C2 as not applicable."""
    readout = {
        "endogenous_self_sustain": True,
        "entrain_then_autonomy": True,
        "hrv_variability": 0.5,
        "womb_prediction_error": 0.1,
        "return_to_baseline_seconds": 10.0,
    }
    published: list[Event] = []
    bus = _make_bus(published=published, readout=readout, sleep_count=0)
    state = _fresh_development_state(tmp_path)
    runner = MaturationGateRunner(
        bus=bus,
        config=MaturationConfig(
            enabled=True,
            min_sleep_cycles=1,
            min_consolidation_passes=1,
            min_lived_seconds=0,
            gate_cadence_seconds=0.01,
        ),
        registry=_make_base_registry(),
        entity_clock=_make_clock(),
        stage_state=state,
        staging_enabled=True,
        stimulus_source_feed_configured=True,
    )
    runner.set_pause_sources(paused_seconds=lambda: 0.0, is_paused=lambda: False)

    async def _explode() -> tuple[bool, bool, bool]:
        raise RuntimeError("_mundus_availability must not be called")

    runner._embodiment_availability = AsyncMock(side_effect=_explode)

    await runner._evaluate_once()

    status = runner.status
    assert status["world"] == "perceptual"
    assert status["conditions"] == {
        "c2_sleep_required": False,
        "c2_consolidation_required": False,
    }
    assert status["readiness"]["not_applicable"] == [
        "C2_reality_model_consolidated"
    ]
    runner._embodiment_availability.assert_not_awaited()
