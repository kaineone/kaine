# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Live maturation-gate runner (`developmental-maturation-gate`).

Tests the periodic gate component without booting a full entity. The runner only
reads injected signals and triggers the monotonic maturation transition.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from kaine.bus.schema import Event
from kaine.bus.streams import DEVELOPMENT_SOURCE, SLEEP_STREAM
from kaine.lifecycle import stage as lifecycle_stage
from kaine.lifecycle.gate_runner import (
    DEFAULT_STIMULUS_SOURCE_READOUT_STREAM,
    MaturationGateRunner,
)
from kaine.lifecycle.maturation_gate import (
    STAGE_DEVELOPMENT_NO_STIMULUS,
    STAGE_MATURATION,
    STAGE_MATURATION_READY,
    MaturationConfig,
)
from kaine.perception_state import read_desired


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
    sleep_stream: str = "sleep.out",
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
                source=DEVELOPMENT_SOURCE,
                type="development.readiness",
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

    # The runner scans the readout stream over a time window (presence and
    # probe events share it), so the readout is served through range().
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
                source="sleep",
                type="sleep.sleep.completed",
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
    # Public embodiment module API the gate uses (operator approval itself is read from
    # KAINE_EMBODIMENT_OPERATOR_APPROVED; tests that need it set the variable).
    embodiment.enabled_by_config = embodiment_enabled
    embodiment.probe_available = AsyncMock(
        return_value=embodiment_enabled and embodiment_approved and embodiment_reachable
    )
    embodiment.activate = AsyncMock(return_value=embodiment_enabled and embodiment_approved)

    vocal = MagicMock()
    vocal.set_dormant = MagicMock()

    # The sleep module is present so the gate applies the sleep and consolidation floors.
    modules = {"sleep": MagicMock(), "world_model": world_model, "embodiment": embodiment, "vocal": vocal}

    def _get(name: str):
        return modules[name]

    registry.get.side_effect = _get
    registry.__contains__.side_effect = lambda name: name in modules
    return registry


def _make_clock(now: float = 0.0) -> Any:
    clock = MagicMock()
    clock.now = MagicMock(return_value=now)
    return clock


def _fresh_development_state(tmp_path: Path) -> lifecycle_stage.StageState:
    """Build a fresh developmental-phase state without mutating the global STAGE_PATH."""
    p = tmp_path / "stage.json"
    return lifecycle_stage.resolve_boot_stage(has_prior_lived_history=False, path=p)


@pytest.mark.asyncio
async def test_no_stimulus_when_developing_without_stimulus_source_feed(tmp_path: Path) -> None:
    published: list[Event] = []
    bus = _make_bus(published=published)
    state = _fresh_development_state(tmp_path)
    runner = MaturationGateRunner(
        bus=bus,
        config=MaturationConfig(enabled=True, gate_cadence_seconds=0.01),
        registry=_make_registry(),
        entity_clock=_make_clock(0.0),
        stage_state=state,
        staging_enabled=True,
        stimulus_source_feed_configured=False,
    )
    stop = asyncio.Event()
    asyncio.get_running_loop().call_later(0.05, stop.set)
    await runner.run(stop)

    assert len(published) == 1
    assert published[0].source == "lifecycle"
    assert published[0].type == STAGE_DEVELOPMENT_NO_STIMULUS


@pytest.mark.asyncio
async def test_gate_keeps_developing_when_conditions_unmet(tmp_path: Path) -> None:
    published: list[Event] = []
    bus = _make_bus(published=published, readout={"endogenous_self_sustain": True}, sleep_count=1)
    state = _fresh_development_state(tmp_path)
    runner = MaturationGateRunner(
        bus=bus,
        config=MaturationConfig(
            enabled=True,
            min_sleep_cycles=5,
            min_consolidation_passes=3,
            min_lived_seconds=86400,
            gate_cadence_seconds=0.01,
        ),
        registry=_make_registry(consolidation_passes=1),
        entity_clock=_make_clock(0.0),
        stage_state=state,
        staging_enabled=True,
        stimulus_source_feed_configured=True,
    )

    await runner._evaluate_once()
    await runner._evaluate_once()

    assert not published
    assert runner.stage.is_developing


@pytest.mark.asyncio
async def test_final_sleep_count_catches_sleeps_after_the_last_tick(tmp_path: Path) -> None:
    """Final sleep count persists sleeps that arrived after the last evaluation tick."""
    bus = _make_bus(sleep_count=4)
    state = _fresh_development_state(tmp_path)
    runner = MaturationGateRunner(
        bus=bus,
        config=MaturationConfig(enabled=True, gate_cadence_seconds=0.01),
        registry=_make_registry(),
        entity_clock=_make_clock(0.0),
        stage_state=state,
        staging_enabled=True,
        stimulus_source_feed_configured=True,
    )
    runner._stage = dataclasses.replace(
        runner._stage, hypnos_cursor="2-0", sleep_count=0
    )

    await runner._begin_boot()
    await runner._final_sleep_count()

    assert runner._stage.sleep_count == 2
    assert runner._stage.hypnos_cursor == "4-0"
    stage_file = lifecycle_stage.STAGE_PATH
    assert json.loads(stage_file.read_text())["sleep_count"] == 2


@pytest.mark.asyncio
async def test_final_sleep_count_skips_without_stimulus_feed(tmp_path: Path) -> None:
    """Final count ignores sleeps when no stimulus source feed is configured."""
    bus = _make_bus(sleep_count=4)
    state = _fresh_development_state(tmp_path)
    runner = MaturationGateRunner(
        bus=bus,
        config=MaturationConfig(enabled=True, gate_cadence_seconds=0.01),
        registry=_make_registry(),
        entity_clock=_make_clock(0.0),
        stage_state=state,
        staging_enabled=True,
        stimulus_source_feed_configured=False,
    )
    runner._stage = dataclasses.replace(
        runner._stage, hypnos_cursor="2-0", sleep_count=0
    )
    await runner._begin_boot()

    await runner._final_sleep_count()

    assert runner._stage.sleep_count == 0
    assert runner._stage.hypnos_cursor == "2-0"


@pytest.mark.asyncio
async def test_final_sleep_count_skips_before_boot_is_anchored(tmp_path: Path) -> None:
    """Final count ignores sleeps until boot is anchored."""
    bus = _make_bus(sleep_count=4)
    state = _fresh_development_state(tmp_path)
    runner = MaturationGateRunner(
        bus=bus,
        config=MaturationConfig(enabled=True, gate_cadence_seconds=0.01),
        registry=_make_registry(),
        entity_clock=_make_clock(0.0),
        stage_state=state,
        staging_enabled=True,
        stimulus_source_feed_configured=True,
    )
    runner._stage = dataclasses.replace(
        runner._stage, hypnos_cursor="2-0", sleep_count=0
    )

    await runner._final_sleep_count()

    assert runner._stage.sleep_count == 0
    assert runner._stage.hypnos_cursor == "2-0"


@pytest.mark.asyncio
async def test_final_sleep_count_skips_when_not_developing(tmp_path: Path) -> None:
    """Final count ignores sleeps when the stage is not developing."""
    bus = _make_bus(sleep_count=4)
    state = _fresh_development_state(tmp_path)
    runner = MaturationGateRunner(
        bus=bus,
        config=MaturationConfig(enabled=True, gate_cadence_seconds=0.01),
        registry=_make_registry(),
        entity_clock=_make_clock(0.0),
        stage_state=state,
        staging_enabled=True,
        stimulus_source_feed_configured=True,
    )
    runner._stage = dataclasses.replace(
        runner._stage,
        stage=lifecycle_stage.EMBODIED,
        hypnos_cursor="2-0",
        sleep_count=0,
    )
    await runner._begin_boot()

    await runner._final_sleep_count()

    assert runner._stage.sleep_count == 0
    assert runner._stage.hypnos_cursor == "2-0"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "stimulus_configured,boot_raises,stage",
    [
        (False, False, lifecycle_stage.DEVELOPMENT),
        (True, True, lifecycle_stage.DEVELOPMENT),
        (True, False, lifecycle_stage.EMBODIED),
    ],
)
async def test_final_count_never_counts_what_a_tick_skipped(
    tmp_path: Path,
    stimulus_configured: bool,
    boot_raises: bool,
    stage: str,
) -> None:
    """A tick and the final count agree on whether a sleep cycle counts."""
    bus = _make_bus(sleep_count=4)
    if boot_raises:
        bus.server_time_ms = AsyncMock(side_effect=RuntimeError("down"))
    state = _fresh_development_state(tmp_path)
    runner = MaturationGateRunner(
        bus=bus,
        config=MaturationConfig(enabled=True, gate_cadence_seconds=0.01),
        registry=_make_registry(),
        entity_clock=_make_clock(0.0),
        stage_state=state,
        staging_enabled=True,
        stimulus_source_feed_configured=stimulus_configured,
    )
    runner._stage = dataclasses.replace(
        runner._stage,
        stage=stage,
        hypnos_cursor="2-0",
        sleep_count=0,
    )

    await runner._evaluate_once()
    await runner._final_sleep_count()

    assert runner._stage.sleep_count == 0
    assert runner._stage.hypnos_cursor == "2-0"


@pytest.mark.asyncio
async def test_shutdown_cancel_path_runs_the_final_count(tmp_path: Path) -> None:
    """Cancelling the run loop still runs the final sleep count before returning."""
    bus = _make_bus(sleep_count=4)
    state = _fresh_development_state(tmp_path)
    runner = MaturationGateRunner(
        bus=bus,
        config=MaturationConfig(enabled=True, gate_cadence_seconds=3600.0),
        registry=_make_registry(),
        entity_clock=_make_clock(0.0),
        stage_state=state,
        staging_enabled=True,
        stimulus_source_feed_configured=True,
    )
    await runner._begin_boot()
    runner._stage = dataclasses.replace(
        runner._stage, hypnos_cursor="2-0", sleep_count=0
    )

    runner._task = asyncio.create_task(runner.run(asyncio.Event()))
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    runner._stage = dataclasses.replace(
        runner._stage, hypnos_cursor="2-0", sleep_count=0
    )
    await runner.shutdown()

    assert runner._stage.sleep_count == 2


@pytest.mark.asyncio
async def test_old_stream_cursor_counts_only_sleeps_on_the_new_stream(tmp_path: Path) -> None:
    """Sleeps are counted from the configured stream, ignoring an old-stream cursor."""
    stream = SLEEP_STREAM
    bus = _make_bus(sleep_stream=stream)
    new_stream_events = [
        (
            f"2000-{i}",
            Event(
                source="sleep",
                type="sleep.sleep.completed",
                payload={},
                salience=0.5,
                timestamp=datetime.now(timezone.utc),
            ),
        )
        for i in range(3)
    ]

    async def _read_entries(
        stream_name: str, last_id: str = "0", count: int = 100, block_ms: int = 0
    ) -> tuple[list[tuple[str, Event]], str | None]:
        if stream_name != stream:
            return [], None
        start = tuple(int(part) for part in last_id.split("-")) if "-" in last_id else (0, 0)
        newer = [e for e in new_stream_events if tuple(int(p) for p in e[0].split("-")) > start]
        if not newer:
            return [], None
        return newer, newer[-1][0]

    bus.read_entries = AsyncMock(side_effect=_read_entries)

    state = _fresh_development_state(tmp_path)
    state = dataclasses.replace(state, hypnos_cursor="1000-2")
    runner = MaturationGateRunner(
        bus=bus,
        config=MaturationConfig(enabled=True, gate_cadence_seconds=0.01),
        registry=_make_registry(),
        entity_clock=_make_clock(0.0),
        stage_state=state,
        staging_enabled=True,
        stimulus_source_feed_configured=True,
        sleep_stream=stream,
    )

    await runner._count_new_sleeps()

    assert runner._stage.sleep_count == 3
    assert runner._stage.hypnos_cursor == "2000-2"


@pytest.mark.asyncio
async def test_gate_holds_awaiting_embodiment_when_ready_but_embodiment_unavailable(
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
    bus = _make_bus(published=published, readout=readout, sleep_count=1)
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
        registry=_make_registry(consolidation_passes=1, embodiment_enabled=False),
        entity_clock=_make_clock(),
        stage_state=state,
        staging_enabled=True,
        stimulus_source_feed_configured=True,
    )

    await runner._evaluate_once()
    await runner._evaluate_once()

    assert len(published) == 1
    assert published[0].type == STAGE_MATURATION_READY
    assert published[0].payload["reason"] == "awaiting_embodiment"
    assert runner.stage.is_developing


@pytest.mark.asyncio
async def test_gate_maturations_when_ready_and_embodiment_available(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("KAINE_EMBODIMENT_OPERATOR_APPROVED", "1")
    readout = {
        "endogenous_self_sustain": True,
        "entrain_then_autonomy": True,
        "hrv_variability": 0.5,
        "womb_prediction_error": 0.1,
        "return_to_baseline_seconds": 10.0,
    }
    published: list[Event] = []
    bus = _make_bus(published=published, readout=readout, sleep_count=1)
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
        registry=_make_registry(
            consolidation_passes=1,
            embodiment_enabled=True,
            embodiment_approved=True,
            embodiment_reachable=True,
        ),
        entity_clock=_make_clock(),
        stage_state=state,
        staging_enabled=True,
        stimulus_source_feed_configured=True,
    )

    await runner._evaluate_once()
    await runner._evaluate_once()

    assert len(published) == 1
    assert published[0].type == STAGE_MATURATION
    assert runner.stage.is_embodied
    # Maturation gives the entity its voice.
    runner._registry.get("vocal").set_dormant.assert_called_once_with(False)
    # Stage file persisted the transition.
    persisted = lifecycle_stage.read_stage(tmp_path / "stage.json")
    assert persisted is not None
    assert persisted.is_embodied


@pytest.mark.asyncio
async def test_maturation_unlocks_development_locus(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("KAINE_EMBODIMENT_OPERATOR_APPROVED", "1")
    readout = {
        "endogenous_self_sustain": True,
        "entrain_then_autonomy": True,
        "hrv_variability": 0.5,
        "womb_prediction_error": 0.1,
        "return_to_baseline_seconds": 10.0,
    }
    published: list[Event] = []
    bus = _make_bus(published=published, readout=readout, sleep_count=1)
    state = _fresh_development_state(tmp_path)

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
            consolidation_passes=1,
            embodiment_enabled=True,
            embodiment_approved=True,
            embodiment_reachable=True,
        ),
        entity_clock=_make_clock(),
        stage_state=state,
        staging_enabled=True,
        stimulus_source_feed_configured=True,
    )

    await runner._evaluate_once()
    await runner._evaluate_once()

    desired = read_desired(desired_path)
    assert desired.locus == "virtual"
    assert desired.locus_locked is False


class _RecordingEmbodiment:
    def __init__(self, *, probe_result: bool = True, activate_result: bool = True) -> None:
        self.probe_result = probe_result
        self.activate_result = activate_result
        self.activate_calls: list[Any] = []
        self.probe_calls: list[Any] = []
        self._enabled = True

    @property
    def enabled_by_config(self) -> bool:
        return self._enabled

    async def probe_available(self, timeout_s: float = 5.0) -> bool:
        self.probe_calls.append(timeout_s)
        return self.probe_result

    async def activate(self) -> bool:
        # Record the persisted stage at the moment of activation, so a test can
        # prove embodiment starts BEFORE the stage file says "embodied".
        self.activate_calls.append(lifecycle_stage.read_stage())
        return self.activate_result


def _make_registry_with_embodiment(embodiment: _RecordingEmbodiment) -> Any:
    registry = MagicMock()

    world_model = MagicMock()
    world_model.successful_training_passes = 1

    vocal = MagicMock()
    vocal.set_dormant = MagicMock()

    # The sleep module is present so the gate applies the sleep and consolidation floors.
    modules = {"sleep": MagicMock(), "world_model": world_model, "embodiment": embodiment, "vocal": vocal}

    def _get(name: str):
        return modules[name]

    registry.get.side_effect = _get
    registry.__contains__.side_effect = lambda name: name in modules
    return registry


@pytest.mark.asyncio
async def test_maturation_calls_embodiment_activate_before_stage_file_and_unlocks_as_development(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("KAINE_EMBODIMENT_OPERATOR_APPROVED", "1")
    readout = {
        "endogenous_self_sustain": True,
        "entrain_then_autonomy": True,
        "hrv_variability": 0.5,
        "womb_prediction_error": 0.1,
        "return_to_baseline_seconds": 10.0,
    }
    published: list[Event] = []
    bus = _make_bus(published=published, readout=readout, sleep_count=1)
    state = _fresh_development_state(tmp_path)

    desired_path = tmp_path / "desired.json"
    monkeypatch.setattr("kaine.perception_state.DESIRED_PATH", desired_path)
    from kaine import perception_state as _ps

    _ps.write_desired_locus("virtual", locked=True, locked_by="gestation", path=desired_path)

    embodiment = _RecordingEmbodiment(probe_result=True, activate_result=True)
    runner = MaturationGateRunner(
        bus=bus,
        config=MaturationConfig(
            enabled=True,
            min_sleep_cycles=1,
            min_consolidation_passes=1,
            min_lived_seconds=0,
            gate_cadence_seconds=0.01,
        ),
        registry=_make_registry_with_embodiment(embodiment),
        entity_clock=_make_clock(),
        stage_state=state,
        staging_enabled=True,
        stimulus_source_feed_configured=True,
    )

    # First tick anchors the sleep cursor; the second counts the sleep.
    await runner._evaluate_once()
    await runner._evaluate_once()

    # activate ran while the stage was still the developmental phase, then the stage file
    # was written as embodied.
    assert embodiment.activate_calls
    at_activation = embodiment.activate_calls[0]
    assert at_activation is None or at_activation.is_developing
    persisted = lifecycle_stage.read_stage(tmp_path / "stage.json")
    assert persisted is not None
    assert persisted.is_embodied

    # Unlock attributed to the developmental phase
    desired = read_desired(desired_path)
    assert desired.locus == "virtual"
    assert desired.locus_locked is False
    assert desired.locked_by == "gestation"


@pytest.mark.asyncio
async def test_maturation_deferred_when_embodiment_activate_fails(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("KAINE_EMBODIMENT_OPERATOR_APPROVED", "1")
    readout = {
        "endogenous_self_sustain": True,
        "entrain_then_autonomy": True,
        "hrv_variability": 0.5,
        "womb_prediction_error": 0.1,
        "return_to_baseline_seconds": 10.0,
    }
    published: list[Event] = []
    bus = _make_bus(published=published, readout=readout, sleep_count=1)
    state = _fresh_development_state(tmp_path)

    desired_path = tmp_path / "desired.json"
    monkeypatch.setattr("kaine.perception_state.DESIRED_PATH", desired_path)
    from kaine import perception_state as _ps

    _ps.write_desired_locus("virtual", locked=True, locked_by="gestation", path=desired_path)

    embodiment = _RecordingEmbodiment(probe_result=True, activate_result=False)
    runner = MaturationGateRunner(
        bus=bus,
        config=MaturationConfig(
            enabled=True,
            min_sleep_cycles=1,
            min_consolidation_passes=1,
            min_lived_seconds=0,
            gate_cadence_seconds=0.01,
        ),
        registry=_make_registry_with_embodiment(embodiment),
        entity_clock=_make_clock(),
        stage_state=state,
        staging_enabled=True,
        stimulus_source_feed_configured=True,
    )

    await runner._evaluate_once()
    await runner._evaluate_once()

    assert embodiment.activate_calls
    assert len(published) == 1
    assert published[0].type == STAGE_MATURATION_READY
    assert published[0].payload["reason"] == "awaiting_embodiment"
    assert runner.stage.is_developing

    persisted = lifecycle_stage.read_stage(tmp_path / "stage.json")
    assert persisted is not None
    assert persisted.is_developing

    # Locus should stay locked and attributed to the developmental phase
    desired = read_desired(desired_path)
    assert desired.locus == "virtual"
    assert desired.locus_locked is True
    assert desired.locked_by == "gestation"
