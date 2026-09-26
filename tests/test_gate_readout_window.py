# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the maturation gate runner's windowed womb readout search."""

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


@pytest.fixture(autouse=True)
def _patch_stage_path(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        "kaine.lifecycle.stage.STAGE_PATH", tmp_path / "stage.json"
    )


def _make_registry() -> Any:
    registry = MagicMock()
    registry.get.side_effect = lambda _name: MagicMock()
    registry.__contains__.return_value = True
    return registry


def _make_config(**overrides: Any) -> Any:
    config = MagicMock()
    config.gate_cadence_seconds = 1.0
    config.readout_max_age_cadences = 5
    config.threshold_minutes = 1
    for key, value in overrides.items():
        setattr(config, key, value)
    return config


def _fresh_stage(tmp_path: Path) -> lifecycle_stage.StageState:
    p = tmp_path / "stage.json"
    return lifecycle_stage.resolve_boot_stage(
        has_prior_lived_history=False, path=p
    )


def _make_bus(
    entries: dict[str, list[tuple[str, Event]]] | None = None,
    boot_ms: int = 1_000_000,
) -> Any:
    entries = entries or {}
    bus = MagicMock()
    bus.publish = AsyncMock(return_value="fake-id")
    bus.latest = AsyncMock(return_value=None)

    async def _server_time_ms() -> int:
        return boot_ms

    bus.server_time_ms = AsyncMock(side_effect=_server_time_ms)

    async def _range(
        stream: str, start: str, end: str = "+"
    ) -> list[tuple[str, Event]]:
        stream_entries = entries.get(stream, [])
        if start in ("0", "0-0"):
            start_ms = 0
        else:
            start_ms = int(start.split("-")[0])
        return [
            (eid, ev)
            for eid, ev in stream_entries
            if int(eid.split("-")[0]) >= start_ms
        ]

    bus.range = AsyncMock(side_effect=_range)
    bus.read_entries = AsyncMock(return_value=([], None))
    bus.client = MagicMock()
    return bus


def _event(
    source: str,
    type_: str,
    payload: dict[str, Any],
    ms: int,
) -> tuple[str, Event]:
    return (
        f"{ms}-0",
        Event(
            source=source,
            type=type_,
            payload=payload,
            salience=0.5,
            timestamp=datetime.now(timezone.utc),
        ),
    )


@pytest.mark.asyncio
async def test_default_stream_is_gestation_out():
    assert DEFAULT_WOMB_READOUT_STREAM == "gestation.out"


@pytest.mark.asyncio
async def test_readout_found_behind_presence(tmp_path: Path):
    readout_payload = {"endogenous_self_sustain": True}
    stream_entries = [
        _event("gestation", "gestation.readiness", {"readout": readout_payload}, 1_001_000),
        _event("gestation", "gestation.womb", {}, 1_002_000),
        _event("gestation", "gestation.womb", {}, 1_003_000),
        _event("gestation", "gestation.womb", {}, 1_004_000),
    ]
    bus = _make_bus({"gestation.out": stream_entries}, boot_ms=1_000_000)
    runner = MaturationGateRunner(
        bus=bus,
        config=_make_config(),
        registry=_make_registry(),
        entity_clock=MagicMock(),
        stage_state=_fresh_stage(tmp_path),
        womb_readout_stream="gestation.out",
    )
    await runner._begin_boot()
    result = await runner._womb_readiness_readout()
    assert result == readout_payload


@pytest.mark.asyncio
async def test_readout_older_than_max_age_ignored(tmp_path: Path):
    stream_entries = [
        _event("gestation", "gestation.readiness", {"readout": {}}, 994_000),
    ]
    bus = _make_bus({"gestation.out": stream_entries}, boot_ms=1_000_000)
    runner = MaturationGateRunner(
        bus=bus,
        config=_make_config(),
        registry=_make_registry(),
        entity_clock=MagicMock(),
        stage_state=_fresh_stage(tmp_path),
        womb_readout_stream="gestation.out",
    )
    await runner._begin_boot()
    result = await runner._womb_readiness_readout()
    assert result is None


@pytest.mark.asyncio
async def test_readout_older_than_boot_ignored(tmp_path: Path):
    stream_entries = [
        _event("gestation", "gestation.readiness", {"readout": {}}, 999_000),
    ]
    bus = _make_bus({"gestation.out": stream_entries}, boot_ms=1_000_000)
    runner = MaturationGateRunner(
        bus=bus,
        config=_make_config(),
        registry=_make_registry(),
        entity_clock=MagicMock(),
        stage_state=_fresh_stage(tmp_path),
        womb_readout_stream="gestation.out",
    )
    await runner._begin_boot()
    result = await runner._womb_readiness_readout()
    assert result is None


@pytest.mark.asyncio
async def test_readout_from_wrong_source_ignored(tmp_path: Path):
    stream_entries = [
        _event("womb", "gestation.readiness", {"readout": {"a": 1}}, 1_002_000),
    ]
    bus = _make_bus({"gestation.out": stream_entries}, boot_ms=1_000_000)
    runner = MaturationGateRunner(
        bus=bus,
        config=_make_config(),
        registry=_make_registry(),
        entity_clock=MagicMock(),
        stage_state=_fresh_stage(tmp_path),
        womb_readout_stream="gestation.out",
    )
    await runner._begin_boot()
    result = await runner._womb_readiness_readout()
    assert result is None
