# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the in-process ignition log, broadcast observer wiring, and the
audio feed's delivered-position primitive.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

from kaine.bus.schema import Event
from kaine.cycle.engine import BASE_EPOCH, CognitiveCycle
from kaine.cycle.ignition_log import (
    IgnitionLog,
    IgnitionLogConfig,
    playlist_position_provider,
)
from kaine.modules.audition.feed import PlaylistAudioStream
from kaine.modules.topos.feed import PlaylistClock
from kaine.persistence.jsonl_sink import AsyncJsonlSink
from kaine.workspace import (
    NoveltyTracker,
    RuleBasedSalience,
    StaticGoalScorer,
    StaticThymosModulator,
    Syneidesis,
)
from kaine.workspace.volition import Volition
from tests._fakes import FakeClock

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_event(source: str, etype: str, salience: float, text: str) -> Event:
    return Event(
        source=source,
        type=etype,
        payload={"text": text},
        salience=salience,
        timestamp=BASE_EPOCH,
    )


def _scripted_streams() -> dict[str, list[tuple[str, Event]]]:
    return {
        "audition.out": [
            (
                "1-0",
                _make_event(
                    "audition", "audition.transcription", 0.62, "hello kaine"
                ),
            ),
        ],
    }


class ScriptedBus:
    def __init__(self, streams: dict[str, list[tuple[str, Event]]]) -> None:
        self._streams = {
            name: list(entries) for name, entries in streams.items()
        }
        self.workspace_broadcasts: list[dict[str, Any]] = []
        self.published: dict[str, list[Event]] = {}

    async def read(
        self,
        stream: str,
        last_id: str = "0",
        count: int = 100,
        block_ms: int = 0,
    ) -> list[tuple[str, Event]]:
        entries = self._streams.get(stream, [])
        out: list[tuple[str, Event]] = []
        for entry_id, event in entries:
            if _id_gt(entry_id, last_id):
                out.append((entry_id, event))
            if len(out) >= count:
                break
        return out

    async def read_entries(
        self,
        stream: str,
        last_id: str = "0",
        count: int = 100,
        block_ms: int = 0,
    ) -> tuple[list[tuple[str, Event]], str | None]:
        entries = await self.read(stream, last_id, count, block_ms)
        return entries, (entries[-1][0] if entries else None)

    async def publish(self, event: Event) -> str:
        self.published.setdefault(event.source, []).append(event)
        return f"{event.source}-pub"

    async def publish_workspace(
        self, snapshot: dict[str, Any], source: str = "syneidesis"
    ) -> str:
        self.workspace_broadcasts.append(snapshot)
        return "workspace-pub"

    async def close(self) -> None:
        return None


def _id_gt(entry_id: str, last_id: str) -> bool:
    if last_id in ("0", "0-0"):
        return True
    return _id_tuple(entry_id) > _id_tuple(last_id)


def _id_tuple(entry_id: str) -> tuple[int, int]:
    parts = entry_id.split("-")
    if len(parts) == 2:
        return int(parts[0]), int(parts[1])
    return int(parts[0]), 0


class StreamRegistry:
    def __init__(self, streams: list[str]) -> None:
        self._streams = list(streams)

    def active_streams(self) -> list[str]:
        return list(self._streams)


def _make_cycle(bus: ScriptedBus) -> CognitiveCycle:
    syneidesis = Syneidesis(
        strategy=RuleBasedSalience(
            novelty=NoveltyTracker(window=32),
            goal_scorer=StaticGoalScorer(),
            thymos_modulator=StaticThymosModulator(),
        ),
        top_k=5,
        publication_threshold=0.35,
    )
    clock = FakeClock()
    return CognitiveCycle(
        bus=bus,
        syneidesis=syneidesis,
        registry=StreamRegistry(sorted(_scripted_streams().keys())),
        volition=Volition(),
        clock=clock,
        sleep=FakeClock().sleep,
        deterministic=True,
    )


async def _run_one_broadcast(
    cycle: CognitiveCycle,
    bus: ScriptedBus,
    inner_observer: Any = None,
    max_ticks: int = 20,
) -> list[tuple[dict[str, Any], str, Any, float]]:
    """Tick the cycle until the observer sees one workspace broadcast.

    Returns the arguments passed to the broadcast observer (empty when no
    broadcast happened within ``max_ticks``).
    """
    calls: list[tuple[dict[str, Any], str, Any, float]] = []

    class _Observer:
        async def on_broadcast(
            self,
            payload: dict[str, Any],
            entry_id: str,
            wall_ts: Any,
            mono_ts: float,
        ) -> None:
            calls.append((payload, entry_id, wall_ts, mono_ts))
            if inner_observer is not None:
                await inner_observer.on_broadcast(
                    payload, entry_id, wall_ts, mono_ts
                )

    cycle.set_broadcast_observer(_Observer())
    for _ in range(max_ticks):
        await cycle.tick()
        if calls:
            break
    return calls


def _read_all_records(sink: AsyncJsonlSink) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for path in sorted(sink.directory.glob(f"{sink.name}-*.jsonl")):
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                records.append(json.loads(line))
    return records


def _assert_no_payload_key(obj: Any) -> None:
    if isinstance(obj, dict):
        assert "payload" not in obj
        for value in obj.values():
            _assert_no_payload_key(value)
    elif isinstance(obj, list):
        for value in obj:
            _assert_no_payload_key(value)


# ---------------------------------------------------------------------------
# Record shape and provider behaviour
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_record_shape_has_exact_keys_and_no_payloads(tmp_path: Path) -> None:
    sink = AsyncJsonlSink(tmp_path, name="ignition", retention_days=0)
    await sink.start()

    payload: dict[str, Any] = {
        "tick_index": 7,
        "selected": [
            {
                "entry_id": "e-1",
                "source": "audition",
                "type": "audition.transcription",
                "salience": 0.62,
                "timestamp": "2024-01-01T00:00:00+00:00",
            },
            {
                "entry_id": "e-2",
                "source": "topos",
                "type": "topos.scene",
                "salience": 0.55,
                "timestamp": "2024-01-01T00:00:01+00:00",
            },
        ],
        "salience_scores": {"audition": 0.62, "topos": 0.55},
        "inhibited": False,
    }

    def position_provider() -> tuple[int, int, str, float, bool]:
        return (1, 2, "film2.mp4", 12.5, False)

    def audio_provider() -> tuple[int, float]:
        return (1, 12.48)

    log = IgnitionLog(sink, position_provider, audio_provider)
    wall_ts = datetime.now(timezone.utc)
    await log.on_broadcast(payload, "bus-entry-42", wall_ts, 12345.6)
    await log.close()

    records = _read_all_records(sink)
    assert len(records) == 1
    record = records[0]

    assert set(record.keys()) == {
        "tick_index",
        "entry_id",
        "wall_ts",
        "mono_ts",
        "programme",
        "audio",
        "inhibited",
        "salience_scores",
        "members",
    }
    assert record["tick_index"] == 7
    assert record["entry_id"] == "bus-entry-42"
    assert record["wall_ts"] == wall_ts.isoformat()
    assert record["mono_ts"] == pytest.approx(12345.6)
    assert record["inhibited"] is False
    assert record["salience_scores"] == payload["salience_scores"]

    assert set(record["programme"].keys()) == {
        "item_idx",
        "order",
        "title",
        "offset_s",
        "paused",
    }
    assert record["programme"]["item_idx"] == 1
    assert record["programme"]["order"] == 2
    assert record["programme"]["title"] == "film2.mp4"
    assert record["programme"]["offset_s"] == pytest.approx(12.5)
    assert record["programme"]["paused"] is False

    assert set(record["audio"].keys()) == {"item_idx", "delivered_s"}
    assert record["audio"]["item_idx"] == 1
    assert record["audio"]["delivered_s"] == pytest.approx(12.48)

    assert len(record["members"]) == 2
    for member, entry in zip(record["members"], payload["selected"]):
        assert set(member.keys()) == {
            "entry_id",
            "source",
            "type",
            "salience",
            "timestamp",
        }
        assert member["entry_id"] == entry["entry_id"]
        assert member["timestamp"] == entry["timestamp"]

    _assert_no_payload_key(record)


@pytest.mark.asyncio
async def test_raising_position_provider_yields_none_and_record_still_writes(
    tmp_path: Path,
) -> None:
    sink = AsyncJsonlSink(tmp_path, name="ignition", retention_days=0)
    await sink.start()

    def bad_provider() -> None:
        raise RuntimeError("boom")

    log = IgnitionLog(sink, bad_provider)
    payload = {"tick_index": 1, "selected": [], "inhibited": True}
    await log.on_broadcast(payload, "e-1", datetime.now(timezone.utc), 1.0)
    await log.close()

    records = _read_all_records(sink)
    assert len(records) == 1
    assert records[0]["programme"] is None
    assert records[0]["audio"] is None


@pytest.mark.asyncio
async def test_raising_audio_provider_yields_none_and_record_still_writes(
    tmp_path: Path,
) -> None:
    sink = AsyncJsonlSink(tmp_path, name="ignition", retention_days=0)
    await sink.start()

    def bad_audio() -> None:
        raise RuntimeError("boom")

    log = IgnitionLog(sink, lambda: None, bad_audio)
    payload = {"tick_index": 2, "selected": [], "inhibited": False}
    await log.on_broadcast(payload, "e-2", datetime.now(timezone.utc), 2.0)
    await log.close()

    records = _read_all_records(sink)
    assert len(records) == 1
    assert records[0]["audio"] is None


# ---------------------------------------------------------------------------
# Config and programme position provider
# ---------------------------------------------------------------------------


def test_ignition_log_config_defaults_and_validation() -> None:
    cfg = IgnitionLogConfig.from_section(None)
    assert cfg.enabled is False
    assert cfg.directory == "data/ignition"

    cfg = IgnitionLogConfig.from_section({})
    assert cfg.enabled is False
    assert cfg.directory == "data/ignition"

    cfg = IgnitionLogConfig.from_section(
        {"enabled": True, "directory": "study/run-a"}
    )
    assert cfg.enabled is True
    assert cfg.directory == "study/run-a"

    with pytest.raises(ValueError, match="ignition_log.enabled"):
        IgnitionLogConfig.from_section({"enabled": "yes"})

    with pytest.raises(ValueError, match="ignition_log.directory"):
        IgnitionLogConfig.from_section({"directory": ""})

    with pytest.raises(ValueError, match="ignition_log.directory"):
        IgnitionLogConfig.from_section({"directory": 123})


class _StepClock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


@dataclass(frozen=True)
class _DuckItem:
    path: str
    order: int


class _DuckManifest:
    items = (
        _DuckItem("/study/film1.mp4", 1),
        _DuckItem("/study/film2.mp4", 2),
    )


def test_playlist_position_provider_with_duck_types() -> None:
    clock = PlaylistClock(2, clock=_StepClock())
    clock.start(at=0.0)
    clock.set_duration(0, 10.0)

    provider = playlist_position_provider(clock, _DuckManifest())
    assert provider() == (0, 1, "film1.mp4", 0.0, False)

    clock._clock.advance(12.5)
    assert provider() == (1, 2, "film2.mp4", 2.5, False)

    clock.pause("test")
    assert provider() == (1, 2, "film2.mp4", 2.5, True)

    clock.resume("test")
    assert provider() == (1, 2, "film2.mp4", 2.5, False)


def test_playlist_position_provider_returns_none_before_start_or_after_end() -> None:
    clock = PlaylistClock(2, clock=_StepClock())
    manifest = _DuckManifest()
    provider = playlist_position_provider(clock, manifest)
    assert provider() is None

    clock.start(at=0.0)
    clock.set_duration(0, 5.0)
    clock.set_duration(1, 3.0)
    clock._clock.advance(10.0)
    assert provider() is None


# ---------------------------------------------------------------------------
# Audio delivered position
# ---------------------------------------------------------------------------


class _MinimalManifest:
    manifest_path = "/tmp/playlist.json"

    class _Item:
        def __init__(self, path: str, order: int) -> None:
            self.path = path
            self.order = order

    items = (
        _Item("/tmp/film1.mp4", 1),
        _Item("/tmp/film2.mp4", 2),
    )


def test_playlist_audio_stream_delivered_position_advances_and_resets() -> None:
    stream = PlaylistAudioStream(
        _MinimalManifest(),
        callback=lambda _pcm: None,
        sample_rate=16000,
        channels=1,
        frames_per_block=480,
        playlist_clock=None,
    )

    assert stream.delivered_position is None

    block = b"\x00" * (480 * 1 * 2)  # 480 frames of int16 mono
    seconds_per_block = 480 / 16000

    assert stream._update_delivered(block, 0) == pytest.approx(seconds_per_block)
    assert stream.delivered_position == (0, pytest.approx(seconds_per_block))

    assert stream._update_delivered(block, 0) == pytest.approx(seconds_per_block)
    assert stream.delivered_position == (0, pytest.approx(2 * seconds_per_block))

    assert stream._update_delivered(block, 1) == pytest.approx(seconds_per_block)
    assert stream.delivered_position == (1, pytest.approx(seconds_per_block))

    half_block = b"\x00" * (240 * 1 * 2)
    assert stream._update_delivered(half_block, 1) == pytest.approx(240 / 16000)
    assert stream.delivered_position == (
        1,
        pytest.approx(seconds_per_block + 240 / 16000),
    )


# ---------------------------------------------------------------------------
# Engine observer wiring
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_engine_calls_observer_once_per_successful_broadcast() -> None:
    bus = ScriptedBus(_scripted_streams())
    cycle = _make_cycle(bus)
    inner = AsyncMock()

    calls = await _run_one_broadcast(cycle, bus, inner)
    assert len(calls) == 1
    assert inner.on_broadcast.call_count == 1

    payload, entry_id, wall_ts, mono_ts = calls[0]
    assert entry_id == "workspace-pub"
    assert "selected" in payload
    assert isinstance(wall_ts, datetime)
    assert isinstance(mono_ts, float)
    assert len(bus.workspace_broadcasts) == 1


@pytest.mark.asyncio
async def test_engine_observer_not_called_when_publish_fails() -> None:
    attempts: list[dict[str, Any]] = []

    class FailingBus(ScriptedBus):
        async def publish_workspace(
            self, snapshot: dict[str, Any], source: str = "syneidesis"
        ) -> str:
            attempts.append(snapshot)
            raise RuntimeError("broadcast refused")

    bus = FailingBus(_scripted_streams())
    cycle = _make_cycle(bus)
    inner = AsyncMock()

    calls = await _run_one_broadcast(cycle, bus, inner)

    assert attempts, "the cycle must have tried to broadcast"
    assert calls == []
    assert inner.on_broadcast.call_count == 0
    assert bus.workspace_broadcasts == []


@pytest.mark.asyncio
async def test_engine_observer_exception_does_not_break_tick() -> None:
    bus = ScriptedBus(_scripted_streams())
    cycle = _make_cycle(bus)
    inner = AsyncMock()
    inner.on_broadcast.side_effect = RuntimeError("observer boom")
    volition_runs: list[Any] = []
    real_run_volition = cycle._run_volition

    async def _recording_run_volition(snapshot: Any) -> None:
        volition_runs.append(snapshot)
        await real_run_volition(snapshot)

    cycle._run_volition = _recording_run_volition  # type: ignore[method-assign]

    calls = await _run_one_broadcast(cycle, bus, inner)
    assert len(calls) == 1
    assert inner.on_broadcast.call_count == 1
    assert len(bus.workspace_broadcasts) == 1
    # The broadcast still counts as successful: executive selection runs.
    assert len(volition_runs) == 1


@pytest.mark.asyncio
async def test_published_payload_identical_with_and_without_observer() -> None:
    bus_a = ScriptedBus(_scripted_streams())
    cycle_a = _make_cycle(bus_a)
    await _run_one_broadcast(cycle_a, bus_a)

    bus_b = ScriptedBus(_scripted_streams())
    cycle_b = _make_cycle(bus_b)
    inner_b = AsyncMock()
    await _run_one_broadcast(cycle_b, bus_b, inner_b)

    assert len(bus_a.workspace_broadcasts) == 1
    assert len(bus_b.workspace_broadcasts) == 1
    assert bus_a.workspace_broadcasts[0] == bus_b.workspace_broadcasts[0]
    assert inner_b.on_broadcast.call_count == 1


def test_playlist_audio_stream_delivered_position_starts_at_the_resync_offset() -> None:
    stream = PlaylistAudioStream(
        _MinimalManifest(),
        callback=lambda _pcm: None,
        sample_rate=16000,
        channels=1,
        frames_per_block=1600,
        playlist_clock=None,
    )
    stream._begin_item(1, 12.5)
    assert stream.delivered_position == (1, 12.5)
    block = b"\x00\x00" * 1600
    stream._update_delivered(block, 1)
    assert stream.delivered_position == (1, pytest.approx(12.6))
    stream._begin_item(0, 0.0)
    assert stream.delivered_position == (0, 0.0)
