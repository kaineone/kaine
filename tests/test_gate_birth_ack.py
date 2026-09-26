# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Operator acknowledgement gates supervised birth."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from kaine.bus.schema import Event
from kaine.lifecycle import stage as lifecycle_stage
from kaine.lifecycle.birth_ack import (
    BirthAck,
    BirthRequest,
    read_ack,
    read_request,
    write_ack,
    write_request,
)
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
    mundus.enabled_by_config = mundus_enabled
    mundus.probe_available = AsyncMock(
        return_value=mundus_enabled and mundus_approved and mundus_reachable
    )
    mundus.activate = AsyncMock(return_value=mundus_enabled and mundus_approved)

    def _get(name: str):
        return {"phantasia": phantasia, "mundus": mundus}[name]

    registry.get.side_effect = _get
    registry.__contains__.return_value = True
    return registry


def _make_clock(now: float = 0.0) -> Any:
    clock = MagicMock()
    clock.now = MagicMock(return_value=now)
    return clock


def _fresh_gestation_state(tmp_path: Path) -> lifecycle_stage.StageState:
    """Build a fresh gestation state without mutating the global STAGE_PATH."""
    p = tmp_path / "stage.json"
    state = lifecycle_stage.resolve_boot_stage(has_prior_lived_history=False, path=p)
    # One sleep already counted, with the cursor past it, so the entity is ready
    # on the first evaluation (otherwise the first tick only anchors the cursor).
    from dataclasses import replace

    return replace(state, sleep_count=1, hypnos_cursor="1-0")


def _ready_readout() -> dict[str, Any]:
    return {
        "endogenous_self_sustain": True,
        "entrain_then_autonomy": True,
        "hrv_variability": 0.5,
        "womb_prediction_error": 0.1,
        "return_to_baseline_seconds": 10.0,
    }


def _build_runner(
    tmp_path: Path,
    bus: Any,
    readout: dict[str, Any] | None,
    require_ack: bool = True,
) -> MaturationGateRunner:
    state = _fresh_gestation_state(tmp_path)
    return MaturationGateRunner(
        bus=bus,
        config=MaturationConfig(
            enabled=True,
            min_sleep_cycles=1,
            min_consolidation_passes=1,
            min_lived_seconds=0,
            gate_cadence_seconds=0.01,
            require_operator_ack_for_birth=require_ack,
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
        birth_request_path=tmp_path / "birth_request.json",
        birth_ack_path=tmp_path / "birth_ack.json",
    )


@pytest.mark.asyncio
async def test_first_evaluation_holds_writes_request(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("KAINE_MUNDUS_OPERATOR_APPROVED", "1")
    readout = _ready_readout()
    published: list[Event] = []
    bus = _make_bus(published=published, readout=readout, sleep_count=1)
    runner = _build_runner(tmp_path, bus, readout)

    await runner._evaluate_once()

    assert runner.stage.is_gestating
    assert not any(e.type == STAGE_BIRTH for e in published)
    request_path = tmp_path / "birth_request.json"
    assert request_path.exists()
    req = read_request(request_path)
    assert req is not None
    assert runner.status["awaiting_ack"] is True
    assert runner.status["request_id"] == req.request_id


@pytest.mark.asyncio
async def test_wrong_ack_does_not_birth(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("KAINE_MUNDUS_OPERATOR_APPROVED", "1")
    readout = _ready_readout()
    published: list[Event] = []
    bus = _make_bus(published=published, readout=readout, sleep_count=1)
    runner = _build_runner(tmp_path, bus, readout)

    await runner._evaluate_once()
    request_id = runner.status["request_id"]

    write_ack(
        BirthAck(
            request_id="b" * 32,
            acknowledged_at=datetime.now(timezone.utc).isoformat(),
        ),
        path=tmp_path / "birth_ack.json",
    )

    await runner._evaluate_once()

    assert runner.stage.is_gestating
    assert not any(e.type == STAGE_BIRTH for e in published)
    assert read_request(tmp_path / "birth_request.json").request_id == request_id


@pytest.mark.asyncio
async def test_matching_ack_births_and_clears_files(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("KAINE_MUNDUS_OPERATOR_APPROVED", "1")
    readout = _ready_readout()
    published: list[Event] = []
    bus = _make_bus(published=published, readout=readout, sleep_count=1)
    runner = _build_runner(tmp_path, bus, readout)

    await runner._evaluate_once()
    request_id = runner.status["request_id"]

    write_ack(
        BirthAck(
            request_id=request_id,
            acknowledged_at=datetime.now(timezone.utc).isoformat(),
        ),
        path=tmp_path / "birth_ack.json",
    )

    await runner._evaluate_once()

    # The first evaluation announced the hold (stage.birth.ready, awaiting the
    # operator); the acknowledged one births exactly once.
    assert [e.type for e in published].count(STAGE_BIRTH) == 1
    assert published[-1].type == STAGE_BIRTH
    assert runner.stage.is_embodied
    assert not (tmp_path / "birth_request.json").exists()
    assert not (tmp_path / "birth_ack.json").exists()
    assert runner.status["request_id"] is None
    assert runner.status["awaiting_ack"] is False


@pytest.mark.asyncio
async def test_old_request_ack_pair_does_not_birth(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("KAINE_MUNDUS_OPERATOR_APPROVED", "1")
    request_path = tmp_path / "birth_request.json"
    ack_path = tmp_path / "birth_ack.json"
    old_id = "c" * 32
    write_request(
        BirthRequest(
            request_id=old_id,
            requested_at=datetime.now(timezone.utc).isoformat(),
            gestation_started_at=None,
        ),
        path=request_path,
    )
    write_ack(
        BirthAck(
            request_id=old_id,
            acknowledged_at=datetime.now(timezone.utc).isoformat(),
        ),
        path=ack_path,
    )

    readout = _ready_readout()
    published: list[Event] = []
    bus = _make_bus(published=published, readout=readout, sleep_count=1)
    runner = _build_runner(tmp_path, bus, readout)

    await runner._evaluate_once()

    assert runner.stage.is_gestating
    assert not any(e.type == STAGE_BIRTH for e in published)
    assert runner.status["awaiting_ack"] is True
    new_id = runner.status["request_id"]
    assert new_id is not None
    assert new_id != old_id
    assert read_request(request_path).request_id == new_id
    old_ack = read_ack(ack_path)
    assert old_ack is not None
    assert old_ack.request_id == old_id


@pytest.mark.asyncio
async def test_readiness_lost_clears_request(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("KAINE_MUNDUS_OPERATOR_APPROVED", "1")
    readout = _ready_readout()
    published: list[Event] = []
    bus = _make_bus(published=published, readout=readout, sleep_count=1)
    runner = _build_runner(tmp_path, bus, readout)

    await runner._evaluate_once()
    assert runner.status["awaiting_ack"] is True
    request_path = tmp_path / "birth_request.json"
    assert request_path.exists()

    # Simulate loss of the womb readout.
    bus.latest = AsyncMock(return_value=None)
    bus.range = AsyncMock(return_value=[])

    await runner._evaluate_once()

    assert runner.stage.is_gestating
    assert not any(e.type == STAGE_BIRTH for e in published)
    assert not request_path.exists()
    assert runner.status["awaiting_ack"] is False
    assert runner.status["request_id"] is None
