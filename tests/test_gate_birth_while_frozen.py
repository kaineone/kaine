# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Birth must not occur while the cycle is paused/frozen."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from kaine.bus.schema import Event
from kaine.lifecycle import stage as lifecycle_stage
from kaine.lifecycle.gate_runner import (
    DEFAULT_WOMB_READOUT_STREAM,
    MaturationGateRunner,
)
from kaine.lifecycle.maturation_gate import (
    STAGE_BIRTH,
    MaturationConfig,
)


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
    womb_stream: str = DEFAULT_WOMB_READOUT_STREAM,
    hypnos_stream: str = "hypnos.out",
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
        if stream == womb_stream and readout is not None:
            return _readout_entry()
        return None

    bus.latest = AsyncMock(side_effect=_latest)

    # The runner scans the readout stream over a time window.
    async def _range(
        stream: str, start: str = "-", end: str = "+", count: int | None = None
    ) -> list[tuple[str, Event]]:
        if stream == womb_stream and readout is not None:
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
        if stream != hypnos_stream:
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


def _make_registry(
    *,
    sleep_count: int = 0,
    consolidation_passes: int = 0,
    mundus_enabled: bool = False,
    mundus_approved: bool = False,
    mundus_reachable: bool = False,
) -> Any:
    registry = MagicMock()

    phantasia = MagicMock()
    phantasia.successful_training_passes = consolidation_passes
    mundus = MagicMock()
    # Public Mundus API the gate uses (operator approval itself is read from
    # KAINE_MUNDUS_OPERATOR_APPROVED; tests that need it set the variable).
    mundus.enabled_by_config = mundus_enabled
    mundus.probe_available = AsyncMock(
        return_value=mundus_enabled and mundus_approved and mundus_reachable
    )
    mundus.activate = AsyncMock(return_value=mundus_enabled and mundus_approved)

    vox = MagicMock()
    vox.set_dormant = MagicMock()

    # Hypnos is present so the gate applies the sleep and consolidation floors.
    modules = {"hypnos": MagicMock(), "phantasia": phantasia, "mundus": mundus, "vox": vox}

    def _get(name: str):
        return modules[name]

    registry.get.side_effect = _get
    registry.__contains__.side_effect = lambda name: name in modules
    return registry


def _make_clock(now: float = 0.0) -> Any:
    clock = MagicMock()
    clock.now = MagicMock(return_value=now)
    return clock


def _fresh_gestation_state(tmp_path: Path) -> lifecycle_stage.StageState:
    """Build a fresh gestation state without mutating the global STAGE_PATH."""
    p = tmp_path / "stage.json"
    return lifecycle_stage.resolve_boot_stage(has_prior_lived_history=False, path=p)


@pytest.mark.asyncio
async def test_birth_deferred_while_frozen_then_births_when_unfrozen(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("KAINE_MUNDUS_OPERATOR_APPROVED", "1")
    readout = {
        "endogenous_self_sustain": True,
        "entrain_then_autonomy": True,
        "hrv_variability": 0.5,
        "womb_prediction_error": 0.1,
        "return_to_baseline_seconds": 10.0,
    }
    published: list[Event] = []
    bus = _make_bus(published=published, readout=readout, sleep_count=1)
    state = _fresh_gestation_state(tmp_path)
    runner = MaturationGateRunner(
        bus=bus,
        config=MaturationConfig(
            enabled=True,
            min_sleep_cycles=1,
            min_consolidation_passes=1,
            min_lived_seconds=0,
            gate_cadence_seconds=0.01,
        ),
        registry=_make_registry(
            consolidation_passes=1,
            mundus_enabled=True,
            mundus_approved=True,
            mundus_reachable=True,
        ),
        entity_clock=_make_clock(),
        stage_state=state,
        staging_enabled=True,
        womb_feed_configured=True,
    )

    runner.set_pause_sources(paused_seconds=lambda: 0.0, is_paused=lambda: True)

    await runner._evaluate_once()
    await runner._evaluate_once()

    assert runner.stage.is_gestating
    assert not any(e.type == STAGE_BIRTH for e in published)
    assert len(published) == 0

    runner.set_pause_sources(paused_seconds=lambda: 0.0, is_paused=lambda: False)

    await runner._evaluate_once()
    await runner._evaluate_once()

    assert len(published) == 1
    assert published[0].type == STAGE_BIRTH
    assert runner.stage.is_embodied


@pytest.mark.asyncio
async def test_birth_deferred_when_is_paused_raises(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("KAINE_MUNDUS_OPERATOR_APPROVED", "1")
    readout = {
        "endogenous_self_sustain": True,
        "entrain_then_autonomy": True,
        "hrv_variability": 0.5,
        "womb_prediction_error": 0.1,
        "return_to_baseline_seconds": 10.0,
    }
    published: list[Event] = []
    bus = _make_bus(published=published, readout=readout, sleep_count=1)
    state = _fresh_gestation_state(tmp_path)
    runner = MaturationGateRunner(
        bus=bus,
        config=MaturationConfig(
            enabled=True,
            min_sleep_cycles=1,
            min_consolidation_passes=1,
            min_lived_seconds=0,
            gate_cadence_seconds=0.01,
        ),
        registry=_make_registry(
            consolidation_passes=1,
            mundus_enabled=True,
            mundus_approved=True,
            mundus_reachable=True,
        ),
        entity_clock=_make_clock(),
        stage_state=state,
        staging_enabled=True,
        womb_feed_configured=True,
    )

    def _broken_is_paused() -> bool:
        raise RuntimeError("pause probe unavailable")

    runner.set_pause_sources(
        paused_seconds=lambda: 0.0, is_paused=_broken_is_paused
    )

    await runner._evaluate_once()
    await runner._evaluate_once()

    assert runner.stage.is_gestating
    assert not any(e.type == STAGE_BIRTH for e in published)
    assert len(published) == 0
