# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the run-recording change.

Covers the two OPTIONAL local-only research recorders:
- ExternalUtteranceLog: external speech only, no inner speech, no bystander input.
- NexusRecord: the exact filtered payload the Nexus bridge displays.

Also verifies config gating, defaults, and export-allowlist confinement.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path

import pytest

from kaine.bus.schema import Event
from kaine.evaluation.config import (
    ExternalUtterancesConfig,
    NexusRecordConfig,
    RawArchiveConfinementError,
    ResearchEventLogConfig,
)
from kaine.evaluation.observers.external_utterance_log import ExternalUtteranceLog
from kaine.evaluation.observers.nexus_record import NexusRecord
from kaine.nexus.privacy import PrivacyFilter

# ---------------------------------------------------------------------------
# Helpers (copied from tests/test_research_event_log.py)
# ---------------------------------------------------------------------------


def _event(source: str, type_: str, payload: dict) -> Event:
    return Event(
        source=source,
        type=type_,
        payload=payload,
        salience=0.5,
        timestamp=datetime.now(timezone.utc),
    )


class FakeBus:
    """Minimal bus double; tracks publish to assert read-only behaviour."""

    def __init__(self) -> None:
        self.streams: dict[str, list[tuple[str, Event]]] = {}
        self._next = 1
        self.published: list[Event] = []  # guard: must stay empty

    def push(self, stream: str, event: Event) -> str:
        eid = f"{self._next}-0"
        self._next += 1
        self.streams.setdefault(stream, []).append((eid, event))
        return eid

    async def read(self, stream, *, last_id="0", count=100, block_ms=0):
        entries = self.streams.get(stream, [])
        if last_id == "$":
            return []
        start = 0
        if last_id not in ("0", "0-0"):
            for i, (eid, _) in enumerate(entries):
                if eid == last_id:
                    start = i + 1
                    break
        return entries[start : start + count]

    async def read_entries(self, stream, last_id="0", count=100, block_ms=0):
        entries = await self.read(stream, last_id=last_id, count=count, block_ms=block_ms)
        last_scanned = entries[-1][0] if entries else None
        return entries, last_scanned

    async def subscribe_workspace(self, last_id="$", count=32, poll_interval_s=0.05):
        idx = 0
        while True:
            entries = self.streams.get("workspace.broadcast", [])
            while idx < len(entries):
                eid, event = entries[idx]
                idx += 1
                yield eid, dict(event.payload or {})
            await asyncio.sleep(poll_interval_s)

    async def current_workspace_id(self):
        return "0"

    async def publish(self, event: Event) -> str:
        self.published.append(event)
        return "fake-id"


class FakeSink:
    """In-memory sink collecting written rows (no encryption / disk)."""

    def __init__(self) -> None:
        self.rows: list[dict] = []

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def write(self, row: dict) -> None:
        self.rows.append(row)


# ---------------------------------------------------------------------------
# ExternalUtteranceLog
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_external_utterance_log_only_records_external_speech_text():
    bus = FakeBus()
    sink = FakeSink()
    observer = ExternalUtteranceLog(
        bus, sink, ExternalUtterancesConfig(enabled=True)
    )

    # Inner-speech events must never be written, regardless of stream.
    inner = _event("lingua", "internal_speech", {"text": "inner thought"})
    await observer.handle("lingua.internal", "1-0", inner)
    await observer.handle("lingua.out", "2-0", inner)

    # External speech records text but drops user_input (bystander speech).
    external = _event(
        "lingua",
        "external_speech",
        {"text": "hello world", "user_input": "user said this"},
    )
    await observer.handle("lingua.external", "3-0", external)

    # External speech with an explicit run_id carries it through.
    external_run = _event(
        "lingua",
        "external_speech",
        {"text": "with run", "run_id": "run-42"},
    )
    await observer.handle("lingua.external", "4-0", external_run)

    assert len(sink.rows) == 2

    assert sink.rows[0]["type"] == "external_speech"
    assert sink.rows[0]["text"] == "hello world"
    assert "user_input" not in sink.rows[0]
    assert sink.rows[0].get("run_id") is None

    assert sink.rows[1]["type"] == "external_speech"
    assert sink.rows[1]["text"] == "with run"
    assert sink.rows[1]["run_id"] == "run-42"


@pytest.mark.asyncio
async def test_external_utterance_log_writes_even_when_text_missing():
    bus = FakeBus()
    sink = FakeSink()
    observer = ExternalUtteranceLog(
        bus, sink, ExternalUtterancesConfig(enabled=True)
    )

    bystander_only = _event(
        "lingua", "external_speech", {"user_input": "bystander only"}
    )
    await observer.handle("lingua.external", "1-0", bystander_only)

    assert len(sink.rows) == 1
    assert sink.rows[0]["type"] == "external_speech"
    assert sink.rows[0]["text"] is None
    assert "user_input" not in sink.rows[0]


def test_external_utterance_log_stream_list_and_source_guard():
    pkg_root = Path(__file__).parent.parent / "kaine" / "evaluation" / "observers"
    eul_src = (pkg_root / "external_utterance_log.py").read_text()
    nr_src = (pkg_root / "nexus_record.py").read_text()

    forbidden = ("lingua.internal", "lingua.out", "internal_speech")
    for token in forbidden:
        assert token not in eul_src, token
        assert token not in nr_src, token

    assert ExternalUtteranceLog.streams == ("lingua.external",)


# ---------------------------------------------------------------------------
# NexusRecord
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_nexus_record_writes_filtered_payload():
    bus = FakeBus()
    sink = FakeSink()
    observer = NexusRecord(bus, sink, NexusRecordConfig(enabled=True))

    event = _event(
        "lingua",
        "external_speech",
        {"text": "hello world", "salience": 0.9, "agent_label": "lingua"},
    )
    await observer.handle("lingua.out", "1-0", event)

    assert len(sink.rows) == 1
    record = sink.rows[0]
    filtered = PrivacyFilter(dev_content_override=False).filter(
        event, surface="diagnostics"
    )

    assert record["stream"] == "lingua.out"
    assert record["entry_id"] == "1-0"
    assert record["source"] == event.source
    assert record["type"] == event.type
    assert record["payload"] == dict(filtered.payload or {})
    assert "text" not in record["payload"]
    assert record["payload"].get("agent_label") == "lingua"


@pytest.mark.asyncio
async def test_nexus_record_of_vision_report_holds_no_vector():
    bus = FakeBus()
    sink = FakeSink()
    observer = NexusRecord(bus, sink, NexusRecordConfig(enabled=True))

    event = _event(
        "topos",
        "topos.report",
        {
            "latent": [0.1] * 768,
            "peripheral": [0.2] * 768,
            "foveal": [0.3] * 768,
            "change_score": 0.4,
            "alert": True,
        },
    )
    await observer.handle("topos.out", "1-0", event)

    assert len(sink.rows) == 1
    record = sink.rows[0]
    assert record["stream"] == "topos.out"
    assert record["entry_id"] == "1-0"
    assert record["source"] == event.source
    assert record["type"] == event.type
    assert record["payload"] == {"change_score": 0.4, "alert": True}


@pytest.mark.asyncio
async def test_nexus_record_drops_event_when_filter_fails():
    bus = FakeBus()
    sink = FakeSink()
    observer = NexusRecord(bus, sink, NexusRecordConfig(enabled=True))

    class _BrokenFilter:
        def filter(self, event, *, surface="diagnostics"):
            raise RuntimeError("filter failure")

    # A filter failure must drop the event, never write it unfiltered.
    observer._privacy = _BrokenFilter()
    event = Event(
        source="lingua",
        type="external_speech",
        payload={"text": "must not be written"},
        salience=0.5,
        timestamp=datetime.now(timezone.utc),
    )
    await observer.handle("lingua.out", "1-0", event)

    assert sink.rows == []


def test_nexus_record_subscribes_to_diagnostics_streams():
    from kaine.evaluation.stream_registry import diagnostics_streams

    assert NexusRecord.streams == diagnostics_streams()


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


def test_run_recording_configs_default_disabled():
    cfg = ResearchEventLogConfig.from_mapping({})
    assert cfg.external_utterances.enabled is False
    assert cfg.nexus_record.enabled is False
    assert cfg.external_utterances.log_dir == "state/research/external_utterances"
    assert cfg.nexus_record.log_dir == "data/nexus_record"
    assert cfg.external_utterances.retention_days == 0
    assert cfg.nexus_record.retention_days == 0


def test_run_recording_configs_parse_enabled_values():
    cfg = ResearchEventLogConfig.from_mapping(
        {
            "external_utterances": {
                "enabled": True,
                "log_dir": "state/research/external_utterances",
                "retention_days": 7,
            },
            "nexus_record": {
                "enabled": True,
                "log_dir": "data/nexus_record",
                "retention_days": 14,
            },
        }
    )
    assert cfg.external_utterances.enabled is True
    assert cfg.external_utterances.retention_days == 7
    assert cfg.nexus_record.enabled is True
    assert cfg.nexus_record.retention_days == 14


def test_run_recording_configs_refuse_export_allowlist():
    with pytest.raises(RawArchiveConfinementError):
        ExternalUtterancesConfig.from_mapping(
            {"log_dir": "data/evaluation/external_utterances"}
        )
    with pytest.raises(RawArchiveConfinementError):
        NexusRecordConfig.from_mapping(
            {"log_dir": "data/evaluation/nexus_record"}
        )
