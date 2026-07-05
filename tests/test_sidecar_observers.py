# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the 8 sidecar observers (tasks 5.1-5.4).

Each observer is tested for:
- Scripted source events → expected JSONL rollup (task 5.1)
- Observer NEVER publishes to the bus (task 5.1 assertion)
- Absent stream → clean no-op, no error (task 5.2)

Plus:
- replay_observer redact=True → IDs only (task 5.3)
- replay_observer redact=False → content included (task 5.3)
- welfare_observer emits a count for each of the three Gray-Zone events (task 5.4)
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from kaine.bus.schema import Event
from kaine.evaluation.observers.coherence_observer import CoherenceObserver
from kaine.evaluation.observers.empatheia_observer import EmpatheiaObserver
from kaine.evaluation.observers.fatigue_observer import FatigueObserver
from kaine.evaluation.observers.nous_policy_observer import NousPolicyObserver
from kaine.evaluation.observers.prediction_error_observer import PredictionErrorObserver
from kaine.evaluation.observers.replay_observer import ReplayObserver
from kaine.evaluation.observers.voice_alignment_divergence_observer import (
    VoiceAlignmentDivergenceObserver,
)
from kaine.evaluation.observers.welfare_observer import WelfareObserver
from kaine.evaluation.sink import AsyncJsonlSink


# ---------------------------------------------------------------------------
# Test helpers
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
    """Minimal bus double for observers. Tracks publish calls so tests can
    assert read-only behaviour for the read-only observers — and assert the
    content-free gray-zone events the welfare observer DOES publish."""

    def __init__(self) -> None:
        self.streams: dict[str, list[tuple[str, Event]]] = {}
        self._next = 1
        self.published: list[Event] = []

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
        entries = await self.read(
            stream, last_id=last_id, count=count, block_ms=block_ms
        )
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
        """Read-only observers must NEVER call this; the welfare observer DOES,
        emitting content-free welfare.gray_zone events."""
        self.published.append(event)
        return "fake-id"


class FakeSink:
    """In-memory sink that collects written rows."""

    def __init__(self):
        self.rows: list[dict] = []

    async def start(self):
        pass

    async def stop(self):
        pass

    async def write(self, entry: dict) -> None:
        self.rows.append(entry)


async def _run_observer(obs, bus: FakeBus, *, delay: float = 0.3):
    """Start an observer, wait for events to be processed, stop it."""
    await obs.start()
    try:
        await asyncio.sleep(delay)
    finally:
        await obs.stop()


# ---------------------------------------------------------------------------
# 1. coherence_observer
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_coherence_observer_records_plv(tmp_path):
    bus = FakeBus()
    sink = AsyncJsonlSink(tmp_path, name="coherence", flush_interval_s=0.05)
    obs = CoherenceObserver(bus, sink)
    bus.push(
        "workspace.broadcast",
        _event(
            "syneidesis",
            "workspace.broadcast",
            {
                "tick_index": 10,
                "metadata": {"coherence": {"soma|thymos": 0.82, "soma|nous": 0.61}},
            },
        ),
    )
    await sink.start()
    await _run_observer(obs, bus)
    await sink.stop()
    files = list(tmp_path.glob("coherence-*.jsonl"))
    assert files
    line = json.loads(files[0].read_text().splitlines()[0])
    assert line["tick_index"] == 10
    assert line["coherence"]["soma|thymos"] == pytest.approx(0.82)
    assert line["coherence"]["soma|nous"] == pytest.approx(0.61)
    assert bus.published == [], "coherence observer must not publish to the bus"


@pytest.mark.asyncio
async def test_coherence_observer_noop_when_no_coherence_metadata(tmp_path):
    """Absent coherence metadata → no JSONL output, no error."""
    bus = FakeBus()
    sink = AsyncJsonlSink(tmp_path, name="coherence", flush_interval_s=0.05)
    obs = CoherenceObserver(bus, sink)
    bus.push(
        "workspace.broadcast",
        _event("syneidesis", "workspace.broadcast", {"tick_index": 1, "metadata": {}}),
    )
    await sink.start()
    await _run_observer(obs, bus)
    await sink.stop()
    files = list(tmp_path.glob("coherence-*.jsonl"))
    assert not files or files[0].read_text().strip() == ""


@pytest.mark.asyncio
async def test_coherence_observer_noop_when_stream_absent(tmp_path):
    """No workspace broadcasts → silent no-op."""
    bus = FakeBus()
    sink = AsyncJsonlSink(tmp_path, name="coherence", flush_interval_s=0.05)
    obs = CoherenceObserver(bus, sink)
    await sink.start()
    await _run_observer(obs, bus, delay=0.1)
    await sink.stop()
    files = list(tmp_path.glob("coherence-*.jsonl"))
    assert not files or files[0].read_text().strip() == ""
    assert bus.published == []


# ---------------------------------------------------------------------------
# 2. replay_observer  (tasks 5.1, 5.2, 5.3)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_replay_observer_redact_true_no_text(tmp_path):
    """task 5.3 — redact=True logs IDs only, no text field."""
    bus = FakeBus()
    sink = AsyncJsonlSink(tmp_path, name="replay", flush_interval_s=0.05)
    obs = ReplayObserver(bus, sink, redact_content=True)
    bus.push(
        "mnemos.out",
        _event(
            "mnemos",
            "mnemos.replay",
            {
                "memory_id": "mem-001",
                "text": "this is sensitive memory content",
                "affect_intensity": 0.7,
                "replayed_at": 1234567890.0,
            },
        ),
    )
    await sink.start()
    await _run_observer(obs, bus)
    await sink.stop()
    files = list(tmp_path.glob("replay-*.jsonl"))
    assert files
    line = json.loads(files[0].read_text().splitlines()[0])
    assert line["redacted"] is True
    assert "text" not in line["payload"], "text field must be absent when redacted"
    assert line["payload"]["memory_id"] == "mem-001"
    assert line["payload"]["affect_intensity"] == pytest.approx(0.7)
    assert bus.published == []


@pytest.mark.asyncio
async def test_replay_observer_redact_false_includes_text(tmp_path):
    """task 5.3 — redact=False includes text content."""
    bus = FakeBus()
    sink = AsyncJsonlSink(tmp_path, name="replay", flush_interval_s=0.05)
    obs = ReplayObserver(bus, sink, redact_content=False)
    bus.push(
        "mnemos.out",
        _event(
            "mnemos",
            "mnemos.replay",
            {
                "memory_id": "mem-002",
                "text": "the rain in Spain",
                "affect_intensity": 0.3,
            },
        ),
    )
    await sink.start()
    await _run_observer(obs, bus)
    await sink.stop()
    files = list(tmp_path.glob("replay-*.jsonl"))
    assert files
    line = json.loads(files[0].read_text().splitlines()[0])
    assert line["redacted"] is False
    assert line["payload"]["text"] == "the rain in Spain"
    assert bus.published == []


@pytest.mark.asyncio
async def test_replay_observer_logs_phantasia_scenario(tmp_path):
    """task 5.1 — phantasia.scenario events are also captured."""
    bus = FakeBus()
    sink = AsyncJsonlSink(tmp_path, name="replay", flush_interval_s=0.05)
    obs = ReplayObserver(bus, sink, redact_content=True)
    bus.push(
        "phantasia.out",
        _event(
            "phantasia",
            "phantasia.scenario",
            {"seed_memory_id": "mem-003", "scenario_index": 0},
        ),
    )
    await sink.start()
    await _run_observer(obs, bus)
    await sink.stop()
    files = list(tmp_path.glob("replay-*.jsonl"))
    assert files
    line = json.loads(files[0].read_text().splitlines()[0])
    assert line["type"] == "phantasia.scenario"
    assert line["payload"]["seed_memory_id"] == "mem-003"
    assert bus.published == []


@pytest.mark.asyncio
async def test_replay_observer_noop_when_stream_absent(tmp_path):
    """task 5.2 — no mnemos.replay or phantasia.scenario events → no output."""
    bus = FakeBus()
    sink = AsyncJsonlSink(tmp_path, name="replay", flush_interval_s=0.05)
    obs = ReplayObserver(bus, sink, redact_content=True)
    await sink.start()
    await _run_observer(obs, bus, delay=0.1)
    await sink.stop()
    files = list(tmp_path.glob("replay-*.jsonl"))
    assert not files or files[0].read_text().strip() == ""
    assert bus.published == []


# ---------------------------------------------------------------------------
# 3. empatheia_observer
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_empatheia_observer_computes_accuracy(tmp_path):
    """task 5.1 — agent model prediction paired with audition.emotion."""
    bus = FakeBus()
    sink = FakeSink()
    obs = EmpatheiaObserver(bus, sink)
    bus.push(
        "empatheia.out",
        _event(
            "empatheia",
            "empatheia.agent_model",
            {
                "agent_id": "operator",
                "reliability": 0.8,
                "familiarity": 0.6,
                "interaction_count": 10,
            },
        ),
    )
    bus.push(
        "audition.out",
        _event(
            "audition",
            "audition.emotion",
            {"confidence": 0.9},
        ),
    )
    await _run_observer(obs, bus)
    assert sink.rows
    row = sink.rows[0]
    assert row["agent_id"] == "operator"
    assert row["predicted_reliability"] == pytest.approx(0.8)
    assert row["observed_confidence"] == pytest.approx(0.9)
    # accuracy = 1 - |0.8 - 0.9| = 0.9
    assert row["accuracy"] == pytest.approx(0.9, abs=0.001)
    assert bus.published == []


@pytest.mark.asyncio
async def test_empatheia_observer_noop_when_streams_absent(tmp_path):
    """task 5.2 — no empatheia or audition events → silent no-op."""
    bus = FakeBus()
    sink = FakeSink()
    obs = EmpatheiaObserver(bus, sink)
    await _run_observer(obs, bus, delay=0.1)
    assert sink.rows == []
    assert bus.published == []


# ---------------------------------------------------------------------------
# 4. voice_alignment_divergence_observer
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_voice_alignment_divergence_observer_records_cycle(tmp_path):
    """task 5.1 — hypnos.sleep.completed with voice_alignment → logged."""
    bus = FakeBus()
    sink = AsyncJsonlSink(tmp_path, name="vad", flush_interval_s=0.05)
    obs = VoiceAlignmentDivergenceObserver(bus, sink)
    bus.push(
        "hypnos.out",
        _event(
            "hypnos",
            "hypnos.sleep.completed",
            {
                "voice_alignment": {
                    "pairs_processed": 8,
                    "pairs_above_threshold": 3,
                    "dpo_loss": 0.25,
                    "adapter_accepted": True,
                    "capability_score_before": 0.90,
                    "capability_score_after": 0.92,
                    "mean_intent_expression_similarity_before": 0.55,
                    "mean_intent_expression_similarity_after": 0.70,
                }
            },
        ),
    )
    await sink.start()
    await _run_observer(obs, bus)
    await sink.stop()
    files = list(tmp_path.glob("vad-*.jsonl"))
    assert files
    line = json.loads(files[0].read_text().splitlines()[0])
    assert line["pairs_processed"] == 8
    assert line["adapter_accepted"] is True
    assert line["dpo_loss"] == pytest.approx(0.25)
    assert bus.published == []


@pytest.mark.asyncio
async def test_voice_alignment_divergence_noop_when_no_va_field(tmp_path):
    """task 5.2 — sleep event without voice_alignment → no output."""
    bus = FakeBus()
    sink = AsyncJsonlSink(tmp_path, name="vad", flush_interval_s=0.05)
    obs = VoiceAlignmentDivergenceObserver(bus, sink)
    bus.push(
        "hypnos.out",
        _event("hypnos", "hypnos.sleep.completed", {"consolidation": True}),
    )
    await sink.start()
    await _run_observer(obs, bus)
    await sink.stop()
    files = list(tmp_path.glob("vad-*.jsonl"))
    assert not files or files[0].read_text().strip() == ""
    assert bus.published == []


@pytest.mark.asyncio
async def test_voice_alignment_divergence_noop_when_stream_absent(tmp_path):
    """task 5.2 — no hypnos events → silent no-op."""
    bus = FakeBus()
    sink = AsyncJsonlSink(tmp_path, name="vad", flush_interval_s=0.05)
    obs = VoiceAlignmentDivergenceObserver(bus, sink)
    await sink.start()
    await _run_observer(obs, bus, delay=0.1)
    await sink.stop()
    files = list(tmp_path.glob("vad-*.jsonl"))
    assert not files or files[0].read_text().strip() == ""
    assert bus.published == []


# ---------------------------------------------------------------------------
# 5. fatigue_observer
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fatigue_observer_logs_threshold_crossing(tmp_path):
    """task 5.1 — soma.fatigue event logged as threshold_crossing."""
    bus = FakeBus()
    sink = AsyncJsonlSink(tmp_path, name="fatigue", flush_interval_s=0.05)
    obs = FatigueObserver(bus, sink)
    bus.push(
        "soma.out",
        _event(
            "soma",
            "soma.fatigue",
            {"value": 105.3, "threshold": 100.0, "crossed": True},
        ),
    )
    await sink.start()
    await _run_observer(obs, bus)
    await sink.stop()
    files = list(tmp_path.glob("fatigue-*.jsonl"))
    assert files
    line = json.loads(files[0].read_text().splitlines()[0])
    assert line["event"] == "threshold_crossing"
    assert line["fatigue_value"] == pytest.approx(105.3)
    assert line["fatigue_threshold"] == pytest.approx(100.0)
    assert bus.published == []


@pytest.mark.asyncio
async def test_fatigue_observer_logs_soma_report(tmp_path):
    """task 5.1 — soma.report fatigue fields are also logged."""
    bus = FakeBus()
    sink = AsyncJsonlSink(tmp_path, name="fatigue", flush_interval_s=0.05)
    obs = FatigueObserver(bus, sink)
    bus.push(
        "soma.out",
        _event(
            "soma",
            "soma.report",
            {
                "fatigue_value": 45.2,
                "fatigue_threshold": 100.0,
                "prediction_error": 0.12,
            },
        ),
    )
    await sink.start()
    await _run_observer(obs, bus)
    await sink.stop()
    files = list(tmp_path.glob("fatigue-*.jsonl"))
    assert files
    line = json.loads(files[0].read_text().splitlines()[0])
    assert line["event"] == "report"
    assert line["fatigue_value"] == pytest.approx(45.2)
    assert bus.published == []


@pytest.mark.asyncio
async def test_fatigue_observer_noop_when_stream_absent(tmp_path):
    """task 5.2 — no soma events → silent no-op."""
    bus = FakeBus()
    sink = AsyncJsonlSink(tmp_path, name="fatigue", flush_interval_s=0.05)
    obs = FatigueObserver(bus, sink)
    await sink.start()
    await _run_observer(obs, bus, delay=0.1)
    await sink.stop()
    files = list(tmp_path.glob("fatigue-*.jsonl"))
    assert not files or files[0].read_text().strip() == ""
    assert bus.published == []


# ---------------------------------------------------------------------------
# 6. prediction_error_observer
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_prediction_error_observer_computes_statistics(tmp_path):
    """task 5.1 — scripted errors from soma and chronos → mean/p95/p99."""
    bus = FakeBus()
    sink = FakeSink()
    obs = PredictionErrorObserver(
        bus, sink, window_size=16, flush_interval_s=0.1, poll_interval_s=0.05
    )
    # Push some soma.report events.
    for val in [0.1, 0.2, 0.3, 0.4, 0.5]:
        bus.push(
            "soma.out",
            _event("soma", "soma.report", {"prediction_error": val, "fatigue_value": 0}),
        )
    # Push a chronos.report event.
    bus.push(
        "chronos.out",
        _event("chronos", "chronos.report", {"temporal_prediction_error": 0.6}),
    )
    await _run_observer(obs, bus, delay=0.4)
    assert sink.rows, "expected at least one flush"
    row = sink.rows[-1]
    soma_stats = row["sources"]["soma.out"]
    assert soma_stats["n"] == 5
    assert soma_stats["mean"] == pytest.approx(0.3, abs=0.01)
    assert soma_stats["p95"] is not None
    assert soma_stats["p99"] is not None
    chronos_stats = row["sources"]["chronos.out"]
    assert chronos_stats["n"] == 1
    assert bus.published == []


@pytest.mark.asyncio
async def test_prediction_error_observer_noop_when_streams_absent(tmp_path):
    """task 5.2 — no predictive module events → no JSONL rows."""
    bus = FakeBus()
    sink = FakeSink()
    obs = PredictionErrorObserver(
        bus, sink, window_size=16, flush_interval_s=0.05, poll_interval_s=0.02
    )
    await _run_observer(obs, bus, delay=0.2)
    # May have flushed but with all-zero counts → no rows written.
    assert all(all(v == 0 for v in r.get("event_counts", {}).values()) for r in sink.rows), \
        "no events ingested means all counts must be 0"
    assert bus.published == []


# ---------------------------------------------------------------------------
# 7. welfare_observer (task 5.4)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_welfare_observer_flags_unmaintained_fatigue():
    """task 5.4 (a) — soma.fatigue with no subsequent maintenance → count."""
    bus = FakeBus()
    sink = FakeSink()
    # Very short window so the test doesn't have to wait 15 minutes.
    obs = WelfareObserver(
        bus,
        sink,
        maintenance_window_s=0.05,  # 50 ms
        extreme_vad_threshold=0.9,
        extreme_vad_duration_s=9999.0,
        consolidation_window_s=9999.0,
        replay_rate_threshold=9999,
        poll_interval_s=0.02,
    )
    bus.push(
        "soma.out",
        _event("soma", "soma.fatigue", {"value": 105.0, "threshold": 100.0}),
    )
    # No hypnos.sleep.completed follows — fatigue is unmaintained.
    await _run_observer(obs, bus, delay=0.3)
    assert obs.unmaintained_fatigue_count >= 1
    assert any(
        r.get("gray_zone_event") == "unmaintained_fatigue" for r in sink.rows
    )
    # B1 — the gray-zone event is also PUBLISHED content-free on welfare.out.
    gz = [e for e in bus.published if e.type == "welfare.gray_zone"]
    assert gz, "welfare observer must publish welfare.gray_zone"
    assert any(e.payload.get("gray_zone_event") == "unmaintained_fatigue" for e in gz)


@pytest.mark.asyncio
async def test_welfare_observer_flags_sustained_extreme_vad():
    """task 5.4 (b) — thymos VAD in extreme zone longer than threshold → count."""
    bus = FakeBus()
    sink = FakeSink()
    obs = WelfareObserver(
        bus,
        sink,
        maintenance_window_s=9999.0,
        extreme_vad_threshold=0.5,
        extreme_vad_duration_s=0.05,  # 50 ms
        consolidation_window_s=9999.0,
        replay_rate_threshold=9999,
        poll_interval_s=0.02,
    )
    # Publish thymos.state with extreme VAD (|valence|=0.9, arousal=0.9).
    for _ in range(3):
        bus.push(
            "thymos.out",
            _event("thymos", "thymos.state", {"state": {"valence": -0.9, "arousal": 0.9}}),
        )
    await _run_observer(obs, bus, delay=0.4)
    assert obs.sustained_extreme_vad_count >= 1
    assert any(
        r.get("gray_zone_event") == "sustained_extreme_vad" for r in sink.rows
    )
    # B1 — published content-free; the raw VAD values are NOT in the payload.
    gz = [e for e in bus.published if e.type == "welfare.gray_zone"]
    assert any(e.payload.get("gray_zone_event") == "sustained_extreme_vad" for e in gz)
    assert all("valence" not in e.payload and "arousal" not in e.payload for e in gz)


@pytest.mark.asyncio
async def test_welfare_observer_flags_replay_overload():
    """task 5.4 (c) — replay write-rate exceeds consolidation window → count."""
    bus = FakeBus()
    sink = FakeSink()
    obs = WelfareObserver(
        bus,
        sink,
        maintenance_window_s=9999.0,
        extreme_vad_threshold=0.9,
        extreme_vad_duration_s=9999.0,
        consolidation_window_s=5.0,  # 5-second window
        replay_rate_threshold=3,     # >3 events triggers alert
        poll_interval_s=0.02,
    )
    # Push 5 mnemos.replay events (> threshold of 3).
    for i in range(5):
        bus.push(
            "mnemos.out",
            _event("mnemos", "mnemos.replay", {"memory_id": f"mem-{i}", "text": "x"}),
        )
    await _run_observer(obs, bus, delay=0.3)
    assert obs.replay_overload_count >= 1
    assert any(
        r.get("gray_zone_event") == "replay_overload" for r in sink.rows
    )
    # B1 — published content-free: label + numeric scalars only, no memory_id/text.
    gz = [e for e in bus.published if e.type == "welfare.gray_zone"]
    assert any(e.payload.get("gray_zone_event") == "replay_overload" for e in gz)
    for e in gz:
        assert e.source == "welfare"
        assert "text" not in e.payload and "memory_id" not in e.payload
        for k, v in e.payload.items():
            assert k == "gray_zone_event" or isinstance(v, (int, float))


@pytest.mark.asyncio
async def test_welfare_observer_noop_when_streams_absent():
    """task 5.2 — no events → no gray zone alerts."""
    bus = FakeBus()
    sink = FakeSink()
    obs = WelfareObserver(
        bus,
        sink,
        maintenance_window_s=9999.0,
        extreme_vad_threshold=0.9,
        extreme_vad_duration_s=9999.0,
        consolidation_window_s=9999.0,
        replay_rate_threshold=9999,
        poll_interval_s=0.02,
    )
    await _run_observer(obs, bus, delay=0.1)
    assert obs.unmaintained_fatigue_count == 0
    assert obs.sustained_extreme_vad_count == 0
    assert obs.replay_overload_count == 0
    assert sink.rows == []
    assert bus.published == []


@pytest.mark.asyncio
async def test_welfare_observer_maintenance_clears_fatigue_alarm():
    """Maintenance arriving within the window clears the alarm (no alert)."""
    bus = FakeBus()
    sink = FakeSink()
    obs = WelfareObserver(
        bus,
        sink,
        maintenance_window_s=5.0,  # 5 seconds — maintenance arrives in < 0.3s
        extreme_vad_threshold=0.9,
        extreme_vad_duration_s=9999.0,
        consolidation_window_s=9999.0,
        replay_rate_threshold=9999,
        poll_interval_s=0.02,
    )
    bus.push(
        "soma.out",
        _event("soma", "soma.fatigue", {"value": 105.0, "threshold": 100.0}),
    )
    bus.push(
        "hypnos.out",
        _event("hypnos", "hypnos.sleep.completed", {}),
    )
    await _run_observer(obs, bus, delay=0.3)
    # Maintenance arrived well within 5 s → no unmaintained-fatigue alert.
    assert obs.unmaintained_fatigue_count == 0
    assert bus.published == []


# ---------------------------------------------------------------------------
# welfare_observer — condition (d): sustained interoceptive distress
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_welfare_observer_flags_sustained_interoceptive_distress():
    """task 4.1 — soma.report PE ≥ threshold for ≥ duration → one event."""
    bus = FakeBus()
    sink = FakeSink()
    obs = WelfareObserver(
        bus,
        sink,
        maintenance_window_s=9999.0,
        extreme_vad_threshold=0.9,
        extreme_vad_duration_s=9999.0,
        consolidation_window_s=9999.0,
        replay_rate_threshold=9999,
        interoceptive_distress_threshold=0.5,
        interoceptive_distress_duration_s=0.05,  # 50 ms
        poll_interval_s=0.02,
    )
    # Push several soma.report events with prediction_error above threshold.
    for _ in range(4):
        bus.push(
            "soma.out",
            _event("soma", "soma.report", {"prediction_error": 0.9, "fatigue_value": 0}),
        )
    await _run_observer(obs, bus, delay=0.4)
    assert obs.sustained_interoceptive_distress_count >= 1
    assert any(
        r.get("gray_zone_event") == "sustained_interoceptive_distress" for r in sink.rows
    )
    # Verify the sink record carries expected fields.
    rec = next(
        r for r in sink.rows
        if r.get("gray_zone_event") == "sustained_interoceptive_distress"
    )
    assert "seconds_sustained" in rec
    assert rec.get("interoceptive_distress_threshold") == pytest.approx(0.5)
    assert rec.get("sustained_interoceptive_distress_count") >= 1
    # B1 — published content-free; the raw prediction_error is NOT in the payload.
    gz = [e for e in bus.published if e.type == "welfare.gray_zone"]
    assert any(
        e.payload.get("gray_zone_event") == "sustained_interoceptive_distress"
        for e in gz
    )
    assert all("prediction_error" not in e.payload for e in gz)


@pytest.mark.asyncio
async def test_welfare_observer_transient_interoceptive_spike_does_not_fire():
    """task 4.2 — PE exceeds threshold briefly then drops; no event fires."""
    bus = FakeBus()
    sink = FakeSink()
    obs = WelfareObserver(
        bus,
        sink,
        maintenance_window_s=9999.0,
        extreme_vad_threshold=0.9,
        extreme_vad_duration_s=9999.0,
        consolidation_window_s=9999.0,
        replay_rate_threshold=9999,
        interoceptive_distress_threshold=0.5,
        interoceptive_distress_duration_s=9999.0,  # require 9999 s — never fires
        poll_interval_s=0.02,
    )
    # Push one high-PE event followed immediately by a low one.
    bus.push(
        "soma.out",
        _event("soma", "soma.report", {"prediction_error": 0.9, "fatigue_value": 0}),
    )
    bus.push(
        "soma.out",
        _event("soma", "soma.report", {"prediction_error": 0.1, "fatigue_value": 0}),
    )
    await _run_observer(obs, bus, delay=0.3)
    assert obs.sustained_interoceptive_distress_count == 0
    assert not any(
        r.get("gray_zone_event") == "sustained_interoceptive_distress" for r in sink.rows
    )
    assert bus.published == []


@pytest.mark.asyncio
async def test_welfare_observer_interoceptive_distress_two_episodes():
    """task 4.3 — recovery then a second sustained episode → exactly two events.

    Events are pushed in two phases (with an inter-phase sleep) so the
    observer's timed check fires episode 1 before the recovery arrives.
    This mirrors real operation where events arrive over wall-clock time.
    """
    bus = FakeBus()
    sink = FakeSink()
    obs = WelfareObserver(
        bus,
        sink,
        maintenance_window_s=9999.0,
        extreme_vad_threshold=0.9,
        extreme_vad_duration_s=9999.0,
        consolidation_window_s=9999.0,
        replay_rate_threshold=9999,
        interoceptive_distress_threshold=0.5,
        interoceptive_distress_duration_s=0.05,  # 50 ms
        poll_interval_s=0.02,
    )

    await obs.start()
    try:
        # Episode 1: push high-PE events and wait long enough for the timed
        # check to fire (>50 ms sustain duration).
        for _ in range(3):
            bus.push(
                "soma.out",
                _event("soma", "soma.report", {"prediction_error": 0.9, "fatigue_value": 0}),
            )
        await asyncio.sleep(0.2)  # let episode 1 fire

        # Recovery: PE drops below threshold — timer resets.
        bus.push(
            "soma.out",
            _event("soma", "soma.report", {"prediction_error": 0.1, "fatigue_value": 0}),
        )
        await asyncio.sleep(0.05)

        # Episode 2: another sustained high PE.
        for _ in range(3):
            bus.push(
                "soma.out",
                _event("soma", "soma.report", {"prediction_error": 0.9, "fatigue_value": 0}),
            )
        await asyncio.sleep(0.2)  # let episode 2 fire
    finally:
        await obs.stop()

    assert obs.sustained_interoceptive_distress_count == 2
    assert (
        sum(
            1 for r in sink.rows
            if r.get("gray_zone_event") == "sustained_interoceptive_distress"
        )
        == 2
    )
    # B1 — both episodes are also published content-free on welfare.out.
    gz = [
        e for e in bus.published
        if e.type == "welfare.gray_zone"
        and e.payload.get("gray_zone_event") == "sustained_interoceptive_distress"
    ]
    assert len(gz) == 2


@pytest.mark.asyncio
async def test_welfare_observer_interoceptive_defaults_preserve_abc():
    """task 4.4 — defaults leave conditions (a)–(c) bit-for-bit unchanged.

    Constructs a WelfareObserver with default interoceptive parameters and
    verifies that the three existing detectors still fire as before.
    """
    bus = FakeBus()
    sink = FakeSink()
    # Only override timing params to make (a)–(c) fire quickly; leave
    # interoceptive params at their defaults (high threshold, long duration).
    obs = WelfareObserver(
        bus,
        sink,
        maintenance_window_s=0.05,
        extreme_vad_threshold=0.5,
        extreme_vad_duration_s=0.05,
        consolidation_window_s=5.0,
        replay_rate_threshold=2,
        # interoceptive_distress_threshold and interoceptive_distress_duration_s
        # are intentionally left at their class defaults.
        poll_interval_s=0.02,
    )
    # (a) Fatigue crossing — no maintenance.
    bus.push(
        "soma.out",
        _event("soma", "soma.fatigue", {"value": 105.0, "threshold": 100.0}),
    )
    # (b) Extreme VAD.
    for _ in range(3):
        bus.push(
            "thymos.out",
            _event("thymos", "thymos.state", {"state": {"valence": -0.9, "arousal": 0.9}}),
        )
    # (c) Replay overload (3 events > threshold 2).
    for i in range(3):
        bus.push(
            "mnemos.out",
            _event("mnemos", "mnemos.replay", {"memory_id": f"m{i}", "text": "x"}),
        )
    await _run_observer(obs, bus, delay=0.5)
    assert obs.unmaintained_fatigue_count >= 1
    assert obs.sustained_extreme_vad_count >= 1
    assert obs.replay_overload_count >= 1
    # (d) should NOT have fired (PE events below default high threshold).
    assert obs.sustained_interoceptive_distress_count == 0
    # B1 — (a)-(c) detections are published content-free; none is (d).
    gz_labels = {
        e.payload.get("gray_zone_event")
        for e in bus.published
        if e.type == "welfare.gray_zone"
    }
    assert "unmaintained_fatigue" in gz_labels
    assert "sustained_extreme_vad" in gz_labels
    assert "replay_overload" in gz_labels
    assert "sustained_interoceptive_distress" not in gz_labels


# ---------------------------------------------------------------------------
# 8. nous_policy_observer
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_nous_policy_observer_logs_efe_and_action(tmp_path):
    """task 5.1 — nous.policy event → JSONL with EFE, horizon, policy."""
    bus = FakeBus()
    sink = AsyncJsonlSink(tmp_path, name="nous_policy", flush_interval_s=0.05)
    obs = NousPolicyObserver(bus, sink)
    bus.push(
        "nous.out",
        _event(
            "nous",
            "nous.policy",
            {"expected_free_energy": -2.35, "horizon": 1, "policy": "request_speak"},
        ),
    )
    await sink.start()
    await _run_observer(obs, bus)
    await sink.stop()
    files = list(tmp_path.glob("nous_policy-*.jsonl"))
    assert files
    line = json.loads(files[0].read_text().splitlines()[0])
    assert line["expected_free_energy"] == pytest.approx(-2.35)
    assert line["horizon"] == 1
    assert line["policy"] == "request_speak"
    assert bus.published == []


@pytest.mark.asyncio
async def test_nous_policy_observer_noop_when_stream_absent(tmp_path):
    """task 5.2 — no nous events → silent no-op."""
    bus = FakeBus()
    sink = AsyncJsonlSink(tmp_path, name="nous_policy", flush_interval_s=0.05)
    obs = NousPolicyObserver(bus, sink)
    await sink.start()
    await _run_observer(obs, bus, delay=0.1)
    await sink.stop()
    files = list(tmp_path.glob("nous_policy-*.jsonl"))
    assert not files or files[0].read_text().strip() == ""
    assert bus.published == []


# ---------------------------------------------------------------------------
# Config tests
# ---------------------------------------------------------------------------


def test_observers_config_defaults():
    """ObserversConfig defaults: all enabled, replay_redact_content=True."""
    from kaine.evaluation.config import ObserversConfig

    cfg = ObserversConfig()
    assert cfg.coherence is True
    assert cfg.replay is True
    assert cfg.replay_redact_content is True
    assert cfg.empatheia is True
    assert cfg.voice_alignment_divergence is True
    assert cfg.fatigue is True
    assert cfg.prediction_error is True
    assert cfg.welfare is True
    assert cfg.nous_policy is True


def test_observers_config_from_mapping_override():
    """Individual toggles can be disabled via TOML mapping."""
    from kaine.evaluation.config import ObserversConfig

    cfg = ObserversConfig.from_mapping(
        {"replay": False, "replay_redact_content": False, "welfare": False}
    )
    assert cfg.replay is False
    assert cfg.replay_redact_content is False
    assert cfg.welfare is False
    # Others stay true.
    assert cfg.coherence is True
    assert cfg.nous_policy is True


def test_evaluation_config_includes_observers_section():
    """EvaluationConfig.from_mapping passes [evaluation.observers] through."""
    from kaine.evaluation.config import EvaluationConfig

    cfg = EvaluationConfig.from_mapping(
        {"observers": {"coherence": False, "nous_policy": False}}
    )
    assert cfg.observers.coherence is False
    assert cfg.observers.nous_policy is False
    assert cfg.observers.replay is True  # default
