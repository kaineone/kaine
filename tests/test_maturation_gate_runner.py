# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Live maturation-gate runner (`developmental-maturation-gate`).

Tests the periodic gate component without booting a full entity. The runner only
reads injected signals and triggers the monotonic birth transition.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from kaine.bus.schema import Event
from kaine.lifecycle import stage as lifecycle_stage
from kaine.lifecycle.gate_runner import MaturationGateRunner
from kaine.lifecycle.maturation_gate import (
    STAGE_BIRTH,
    STAGE_BIRTH_READY,
    STAGE_GESTATION_NO_STIMULUS,
    MaturationConfig,
)
from kaine.perception_state import read_desired


def _make_bus(published: list[Event] | None = None, readout: dict[str, Any] | None = None) -> Any:
    """Return a minimal async bus double."""
    bus = MagicMock()

    async def _publish(event: Event) -> str:
        if published is not None:
            published.append(event)
        return "fake-id"

    bus.publish = _publish
    client = MagicMock()
    client.xrevrange = AsyncMock(return_value=_readout_entries(readout))
    bus.client = client
    return bus


def _readout_entries(readout: dict[str, Any] | None) -> list:
    if readout is None:
        return []
    payload = {"type": "gestation.readiness", "readout": readout}
    return [("1-0", {b"payload": json.dumps(payload).encode()})]


def _make_registry(
    *,
    sleep_count: int = 0,
    consolidation_passes: int = 0,
    mundus_enabled: bool = False,
    mundus_approved: bool = False,
    mundus_reachable: bool = False,
) -> Any:
    registry = MagicMock()

    hypnos = MagicMock()
    hypnos.sleep_count = sleep_count
    phantasia = MagicMock()
    phantasia.successful_training_passes = consolidation_passes
    mundus = MagicMock()
    mundus._config_enabled = mundus_enabled
    mundus._enabled = lambda: mundus_enabled and mundus_approved
    mundus._tasks = ["task"] if mundus_reachable else []

    def _get(name: str):
        return {"hypnos": hypnos, "phantasia": phantasia, "mundus": mundus}[name]

    registry.get.side_effect = _get
    registry.__contains__.return_value = True
    return registry


def _make_clock(now: datetime | None = None) -> Any:
    clock = MagicMock()
    target = now if now is not None else datetime.now(timezone.utc)
    clock.now = MagicMock(return_value=target)
    return clock


def _fresh_gestation_state(tmp_path: Path) -> lifecycle_stage.StageState:
    p = tmp_path / "stage.json"
    lifecycle_stage.STAGE_PATH = p  # type: ignore[misc]
    return lifecycle_stage.resolve_boot_stage(has_prior_lived_history=False, path=p)


@pytest.mark.asyncio
async def test_no_stimulus_when_gestating_without_womb_feed(tmp_path: Path) -> None:
    published: list[Event] = []
    bus = _make_bus(published=published)
    state = _fresh_gestation_state(tmp_path)
    runner = MaturationGateRunner(
        bus=bus,
        config=MaturationConfig(enabled=True, gate_cadence_seconds=0.01),
        registry=_make_registry(),
        entity_clock=_make_clock(datetime.now(timezone.utc)),
        stage_state=state,
        staging_enabled=True,
        womb_feed_configured=False,
    )
    stop = asyncio.Event()
    asyncio.get_running_loop().call_later(0.05, stop.set)
    await runner.run(stop)

    assert len(published) == 1
    assert published[0].source == "lifecycle"
    assert published[0].type == STAGE_GESTATION_NO_STIMULUS


@pytest.mark.asyncio
async def test_gate_keeps_gestating_when_conditions_unmet(tmp_path: Path) -> None:
    published: list[Event] = []
    bus = _make_bus(published=published, readout={"endogenous_self_sustain": True})
    state = _fresh_gestation_state(tmp_path)
    runner = MaturationGateRunner(
        bus=bus,
        config=MaturationConfig(
            enabled=True,
            min_sleep_cycles=5,
            min_consolidation_passes=3,
            min_lived_seconds=86400,
            gate_cadence_seconds=0.01,
        ),
        registry=_make_registry(sleep_count=1, consolidation_passes=1),
        entity_clock=_make_clock(datetime.now(timezone.utc)),
        stage_state=state,
        staging_enabled=True,
        womb_feed_configured=True,
    )
    stop = asyncio.Event()
    asyncio.get_running_loop().call_later(0.05, stop.set)
    await runner.run(stop)

    assert not published
    assert runner.stage.is_gestating


@pytest.mark.asyncio
async def test_gate_holds_awaiting_embodiment_when_ready_but_mundus_unavailable(
    tmp_path: Path,
) -> None:
    readout = {
        "endogenous_self_sustain": True,
        "entrain_then_autonomy": True,
        "hrv_variability": 0.5,
        "womb_prediction_error": 0.1,
        "return_to_baseline_seconds": 10.0,
    }
    published: list[Event] = []
    bus = _make_bus(published=published, readout=readout)
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
        registry=_make_registry(sleep_count=1, consolidation_passes=1, mundus_enabled=False),
        entity_clock=_make_clock(),
        stage_state=state,
        staging_enabled=True,
        womb_feed_configured=True,
    )
    stop = asyncio.Event()
    asyncio.get_running_loop().call_later(0.05, stop.set)
    await runner.run(stop)

    assert len(published) == 1
    assert published[0].type == STAGE_BIRTH_READY
    assert published[0].payload["reason"] == "awaiting_embodiment"
    assert runner.stage.is_gestating


@pytest.mark.asyncio
async def test_gate_births_when_ready_and_embodiment_available(tmp_path: Path) -> None:
    readout = {
        "endogenous_self_sustain": True,
        "entrain_then_autonomy": True,
        "hrv_variability": 0.5,
        "womb_prediction_error": 0.1,
        "return_to_baseline_seconds": 10.0,
    }
    published: list[Event] = []
    bus = _make_bus(published=published, readout=readout)
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
            sleep_count=1,
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
    stop = asyncio.Event()
    asyncio.get_running_loop().call_later(0.05, stop.set)
    await runner.run(stop)

    assert len(published) == 1
    assert published[0].type == STAGE_BIRTH
    assert runner.stage.is_embodied
    # Stage file persisted the transition.
    persisted = lifecycle_stage.read_stage(tmp_path / "stage.json")
    assert persisted is not None
    assert persisted.is_embodied


@pytest.mark.asyncio
async def test_birth_unlocks_gestation_locus(tmp_path: Path, monkeypatch) -> None:
    readout = {
        "endogenous_self_sustain": True,
        "entrain_then_autonomy": True,
        "hrv_variability": 0.5,
        "womb_prediction_error": 0.1,
        "return_to_baseline_seconds": 10.0,
    }
    published: list[Event] = []
    bus = _make_bus(published=published, readout=readout)
    state = _fresh_gestation_state(tmp_path)

    desired_path = tmp_path / "desired.json"
    monkeypatch.setattr("kaine.perception_state.DESIRED_PATH", desired_path)
    from kaine import perception_state as _ps

    _ps.write_desired_locus("virtual", locked=True, locked_by="gestation", path=desired_path)

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
            sleep_count=1,
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
    stop = asyncio.Event()
    asyncio.get_running_loop().call_later(0.05, stop.set)
    await runner.run(stop)

    desired = read_desired(desired_path)
    assert desired.locus == "virtual"
    assert desired.locus_locked is False
