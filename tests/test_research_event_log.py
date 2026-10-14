# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for the research-event-log change.

Covers the curated research event observer (export-eligible), the local-only
raw bus archive consumer (never export-eligible), config gating independent of
[evaluation].enabled, the privacy transforms, and structural isolation of the
raw archive from the metrics bundle.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

import pytest

from kaine.bus.schema import Event
from kaine.dashboard.privacy import CONTENT_FIELDS
from kaine.evaluation.config import (
    EvaluationConfig,
    RawArchiveConfig,
    RawArchiveConfinementError,
    ResearchEventLogConfig,
)
from kaine.evaluation.observers.raw_bus_archive_consumer import (
    _MODULE_OUT_STREAMS,
    RawArchiveAttestationError,
    RawBusArchiveConsumer,
)
from kaine.evaluation.observers.research_event_observer import (
    _CURATED_STREAMS,
    ResearchEventObserver,
)
from kaine.evaluation.registry import SidecarRegistry
from kaine.evaluation.sink import AsyncJsonlSink
from kaine.experiment.log_schema import NONNEG, _bound_for
from kaine.research.submission import (
    DENY_PATTERNS,
    METRICS_ONLY_DIRS,
    build_research_bundle,
)

# ---------------------------------------------------------------------------
# Helpers
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

    async def write(self, entry: dict) -> None:
        self.rows.append(entry)


async def _run(obs, *, delay: float = 0.25) -> None:
    await obs.start()
    try:
        await asyncio.sleep(delay)
    finally:
        await obs.stop()


def _no_content_anywhere(record: dict) -> bool:
    """True if no CONTENT_FIELDS key appears anywhere in the record."""

    def walk(v) -> bool:
        if isinstance(v, dict):
            for k, sub in v.items():
                if k in CONTENT_FIELDS:
                    return False
                if not walk(sub):
                    return False
            return True
        if isinstance(v, list):
            return all(walk(i) for i in v)
        return True

    return walk(record)


# ---------------------------------------------------------------------------
# 6.1 METRICS_ONLY_DIRS membership + deny-pattern safety
# ---------------------------------------------------------------------------


def test_research_events_in_metrics_only_dirs():
    assert "research_events" in METRICS_ONLY_DIRS


def test_research_events_name_avoids_deny_patterns():
    name = "research_events"
    for pat in DENY_PATTERNS:
        assert pat not in name.lower(), f"deny pattern {pat!r} matches research_events"


# ---------------------------------------------------------------------------
# Config gating (disabled by default; independent of evaluation)
# ---------------------------------------------------------------------------


def test_curated_log_disabled_by_default():
    cfg = ResearchEventLogConfig()
    assert cfg.enabled is False
    assert cfg.raw_archive.enabled is False


def test_config_from_mapping_reads_blocks():
    cfg = ResearchEventLogConfig.from_mapping(
        {
            "enabled": True,
            "log_dir": "data/evaluation/research_events",
            "retention_days": 7,
            "raw_archive": {
                "enabled": True,
                "entity_privacy_attested": True,
                "bystander_consent_attested": True,
                "archive_dir": "state/research/raw_bus_archive",
            },
        }
    )
    assert cfg.enabled is True
    assert cfg.retention_days == 7
    assert cfg.raw_archive.enabled is True
    assert cfg.raw_archive.entity_privacy_attested is True
    assert cfg.raw_archive.bystander_consent_attested is True


@pytest.mark.asyncio
async def test_registry_no_research_observer_when_disabled(tmp_path):
    """6.2 — disabled config → no observer constructed, no sink opened."""
    eval_cfg = EvaluationConfig.from_mapping({"enabled": False})
    sidecar = SidecarRegistry(
        bus=FakeBus(),
        config=eval_cfg,
        research_event_log_config=ResearchEventLogConfig(),  # all off
    )
    sidecar.build()
    names = [getattr(o, "name", "") for o in sidecar.observers]
    assert "research_event_log" not in names
    assert "raw_bus_archive" not in names
    await sidecar.start()
    assert sidecar.started is False


@pytest.mark.asyncio
async def test_research_log_runs_when_evaluation_disabled(tmp_path):
    """Independence: [evaluation].enabled=false AND research enabled=true →
    the research observer is constructed and started."""
    eval_cfg = EvaluationConfig.from_mapping({"enabled": False})
    rcfg = ResearchEventLogConfig(enabled=True, log_dir=str(tmp_path / "research_events"))
    sidecar = SidecarRegistry(bus=FakeBus(), config=eval_cfg, research_event_log_config=rcfg)
    sidecar.build()
    names = [getattr(o, "name", "") for o in sidecar.observers]
    assert "research_event_log" in names
    await sidecar.start()
    assert sidecar.started is True
    obs = next(o for o in sidecar.observers if o.name == "research_event_log")
    await asyncio.sleep(0.05)
    assert obs._task is not None and not obs._task.done()
    await sidecar.stop()


@pytest.mark.asyncio
async def test_research_log_off_when_only_evaluation_on(tmp_path):
    """Independence (other direction): [evaluation].enabled=true AND
    [research_event_log].enabled=false → no research observer."""
    eval_cfg = EvaluationConfig.from_mapping(
        {
            "enabled": True,
            "paths": {
                "trajectory_dir": str(tmp_path / "traj"),
                "evaluation_logs": str(tmp_path / "eval"),
            },
        }
    )
    sidecar = SidecarRegistry(
        bus=FakeBus(),
        config=eval_cfg,
        research_event_log_config=ResearchEventLogConfig(enabled=False),
    )
    sidecar.build()
    names = [getattr(o, "name", "") for o in sidecar.observers]
    assert "research_event_log" not in names


# ---------------------------------------------------------------------------
# Curated taxonomy + privacy transforms
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_affect_state_record_has_vad_no_affect_reason():
    """6.3 — affect.state → VAD/emotion kept, affect_reason stripped."""
    bus = FakeBus()
    sink = FakeSink()
    obs = ResearchEventObserver(bus, sink, poll_interval_s=0.02)
    bus.push(
        "affect.out",
        _event(
            "affect",
            "affect.state",
            {
                "state": {"valence": 0.4, "arousal": 0.2, "dominance": -0.1},
                "drives": {"curiosity": 0.7},
                "emotion": "calm",
                "affect_reason": "SECRET internal reason text",
            },
        ),
    )
    await _run(obs)
    assert len(sink.rows) == 1
    rec = sink.rows[0]
    assert rec["event_type"] == "affect.state"
    assert rec["state"]["valence"] == pytest.approx(0.4)
    assert rec["emotion"] == "calm"
    assert "affect_reason" not in rec
    assert _no_content_anywhere(rec)
    assert bus.published == []


@pytest.mark.asyncio
async def test_episodic_memory_replay_text_redacted():
    """6.4 — episodic_memory.replay → memory ids + affect kept, text dropped."""
    bus = FakeBus()
    sink = FakeSink()
    obs = ResearchEventObserver(bus, sink, poll_interval_s=0.02)
    bus.push(
        "episodic_memory.out",
        _event(
            "episodic_memory",
            "episodic_memory.replay",
            {
                "memory_ids": ["m1", "m2"],
                "max_affect_intensity": 0.8,
                "selection_scores": [0.9, 0.5],
                "text": "VERBATIM MEMORY TEXT that must never be logged",
            },
        ),
    )
    await _run(obs)
    assert len(sink.rows) == 1
    rec = sink.rows[0]
    assert rec["memory_ids"] == ["m1", "m2"]
    assert rec["max_affect_intensity"] == pytest.approx(0.8)
    assert "text" not in rec
    assert _no_content_anywhere(rec)


@pytest.mark.asyncio
async def test_audition_transcription_never_logged():
    """6.5 — audition.transcription is not in the taxonomy → no record."""
    bus = FakeBus()
    sink = FakeSink()
    obs = ResearchEventObserver(bus, sink, poll_interval_s=0.02)
    bus.push(
        "audition.out",
        _event(
            "audition",
            "audition.transcription",
            {"transcription": "the user said something private"},
        ),
    )
    await _run(obs)
    assert sink.rows == []


@pytest.mark.asyncio
async def test_embodiment_visual_raw_never_logged():
    """6.6 — embodiment.visual.raw is not in the taxonomy → no record."""
    bus = FakeBus()
    sink = FakeSink()
    obs = ResearchEventObserver(bus, sink, poll_interval_s=0.02)
    bus.push(
        "embodiment.out",
        _event("embodiment", "embodiment.visual.raw", {"frame": [0, 1, 2, 3]}),
    )
    await _run(obs)
    assert sink.rows == []


@pytest.mark.asyncio
async def test_effectors_action_content_stripped():
    """6.7 — effectors.action → metadata kept, content/body/stdout stripped."""
    bus = FakeBus()
    sink = FakeSink()
    obs = ResearchEventObserver(bus, sink, poll_interval_s=0.02)
    bus.push(
        "effectors.out",
        _event(
            "effectors",
            "effectors.action",
            {
                "action_family": "file",
                "effector": "write_file",
                "success": True,
                "duration_ms": 12.0,
                "content": "SECRET file body",
                "body": "SECRET body",
                "stdout": "SECRET stdout",
            },
        ),
    )
    await _run(obs)
    assert len(sink.rows) == 1
    rec = sink.rows[0]
    assert rec["action_family"] == "file"
    assert rec["effector"] == "write_file"
    assert rec["success"] is True
    assert rec["duration_ms"] == pytest.approx(12.0)
    for forbidden in ("content", "body", "stdout"):
        assert forbidden not in rec
    assert _no_content_anywhere(rec)


@pytest.mark.asyncio
async def test_content_fields_absent_from_every_record():
    """6.8 — a CONTENT_FIELDS key in the payload never reaches the record."""
    bus = FakeBus()
    sink = FakeSink()
    obs = ResearchEventObserver(bus, sink, poll_interval_s=0.02)
    # interoception.report carries an extra content field that must be scrubbed.
    bus.push(
        "interoception.out",
        _event(
            "interoception",
            "interoception.report",
            {
                "prediction_error": 0.3,
                "wellness": 0.9,
                "fatigue_value": 0.2,
                "internal_speech": "PRIVATE inner monologue",
                "text": "PRIVATE text",
            },
        ),
    )
    await _run(obs)
    assert len(sink.rows) == 1
    rec = sink.rows[0]
    assert rec["prediction_error"] == pytest.approx(0.3)
    assert _no_content_anywhere(rec)
    serialized = json.dumps(rec)
    assert "PRIVATE inner monologue" not in serialized
    assert "PRIVATE text" not in serialized


@pytest.mark.asyncio
async def test_interoception_unexpected_error_is_recorded():
    """interoception.report's unexpected_error (the error beyond the interoception module's learned
    expected band, which drives sleep pressure) reaches the research log;
    a non-allowlisted field does not."""
    bus = FakeBus()
    sink = FakeSink()
    obs = ResearchEventObserver(bus, sink, poll_interval_s=0.02)
    bus.push(
        "interoception.out",
        _event(
            "interoception",
            "interoception.report",
            {
                "prediction_error": 0.4,
                "unexpected_error": 0.07,
                "wellness": 0.9,
                "fatigue_value": 57.3,
                "alerts": [],
                "metrics": {"cpu_percent": 12.0},
            },
        ),
    )
    await _run(obs)
    assert len(sink.rows) == 1
    rec = sink.rows[0]
    assert rec["unexpected_error"] == pytest.approx(0.07)
    assert rec["fatigue_value"] == pytest.approx(57.3)
    assert "metrics" not in rec


@pytest.mark.asyncio
async def test_self_model_drift_scalar_only_no_self_model():
    """6.15 — self_model.drift → scalars kept, no self-model doc."""
    bus = FakeBus()
    sink = FakeSink()
    obs = ResearchEventObserver(bus, sink, poll_interval_s=0.02)
    bus.push(
        "self_model.out",
        _event(
            "self_model",
            "self_model.drift",
            {
                "score": 0.42,
                "significant": True,
                "self_model": {"identity": "SECRET self model doc"},
                "content": "SECRET",
            },
        ),
    )
    await _run(obs)
    assert len(sink.rows) == 1
    rec = sink.rows[0]
    assert rec["score"] == pytest.approx(0.42)
    assert rec["significant"] is True
    assert "self_model" not in rec
    assert _no_content_anywhere(rec)


@pytest.mark.asyncio
async def test_embodiment_proprio_no_raw_coordinates():
    """embodiment.proprio → opaque position hash + region label, never x/y/z."""
    bus = FakeBus()
    sink = FakeSink()
    obs = ResearchEventObserver(bus, sink, poll_interval_s=0.02)
    bus.push(
        "embodiment.out",
        _event(
            "embodiment",
            "embodiment.proprio",
            {"x": 128.5, "y": 64.0, "z": 22.0, "region_label": "Sandbox"},
        ),
    )
    await _run(obs)
    assert len(sink.rows) == 1
    rec = sink.rows[0]
    assert rec["region_label"] == "Sandbox"
    assert "avatar_position_hash" in rec
    for coord in ("x", "y", "z"):
        assert coord not in rec
    serialized = json.dumps(rec)
    assert "128.5" not in serialized
    assert "64.0" not in serialized


@pytest.mark.asyncio
async def test_workspace_broadcast_metadata_only():
    """6.14 — workspace broadcast → per-entry metadata, never entry payload."""
    bus = FakeBus()
    sink = FakeSink()
    obs = ResearchEventObserver(bus, sink, poll_interval_s=0.02)
    bus.push(
        "workspace.broadcast",
        _event(
            "workspace",
            "workspace.broadcast",
            {
                "tick_index": 7,
                "inhibited": False,
                "salience_scores": {"affect": 0.6},
                "selected": [
                    {
                        "source": "affect",
                        "type": "affect.state",
                        "salience": 0.6,
                        "causal_parent": None,
                        "payload": {"text": "SECRET workspace content"},
                    }
                ],
            },
        ),
    )
    await _run(obs)
    assert len(sink.rows) == 1
    rec = sink.rows[0]
    assert rec["event_type"] == "workspace.broadcast"
    assert rec["tick_index"] == 7
    assert rec["inhibited"] is False
    assert rec["entries"][0]["source"] == "affect"
    assert rec["entries"][0]["type"] == "affect.state"
    assert "payload" not in rec["entries"][0]
    serialized = json.dumps(rec)
    assert "SECRET workspace content" not in serialized


@pytest.mark.asyncio
async def test_supervisor_incident_captured_with_incident_id():
    """freeze-run-annotation — supervisor.incident is captured into a record carrying
    incident_id + operational fields, with content/paths absent."""
    bus = FakeBus()
    sink = FakeSink()
    obs = ResearchEventObserver(bus, sink, poll_interval_s=0.02)
    bus.push(
        "supervisor.out",
        _event(
            "supervisor",
            "supervisor.incident",
            {
                "incident_id": "inc-123",
                "transition": "detect",
                "module": "language",
                "fault_class": "dead",
                "exception_repr": "FileNotFoundError: <PATH>",
                "poll_index": 3,
                "tick_index": 41,
            },
        ),
    )
    await _run(obs)
    assert len(sink.rows) == 1
    rec = sink.rows[0]
    assert rec["event_type"] == "supervisor.incident"
    assert rec["incident_id"] == "inc-123"
    assert rec["tick_index"] == 41
    assert rec["transition"] == "detect"
    assert rec["module"] == "language"
    assert rec["fault_class"] == "dead"
    assert rec["poll_index"] == 3
    assert _no_content_anywhere(rec)


@pytest.mark.asyncio
async def test_supervisor_incident_subtype_prefix_captured():
    """The supervisor.incident.* prefix family also routes to the supervisor.incident
    taxonomy entry."""
    bus = FakeBus()
    sink = FakeSink()
    obs = ResearchEventObserver(bus, sink, poll_interval_s=0.02)
    bus.push(
        "supervisor.out",
        _event(
            "supervisor",
            "supervisor.incident.restart",
            {
                "incident_id": "inc-9",
                "transition": "restart",
                "module": "interoception",
                "outcome": "recovered",
                "path": "light",
            },
        ),
    )
    await _run(obs)
    assert len(sink.rows) == 1
    rec = sink.rows[0]
    assert rec["incident_id"] == "inc-9"
    assert rec["outcome"] == "recovered"
    assert rec["path"] == "light"


@pytest.mark.asyncio
async def test_supervisor_incident_record_stamped_with_run_id(tmp_path):
    """When a run context is set, the captured supervisor.incident record is stamped
    with the run's run_id (via the A1 sink stamping) — the run<->incident link.
    Without a context, no run_id is added."""
    from kaine.experiment.run_context import (
        RunContext,
        get_run_context,
        set_run_context,
    )

    # 1) No run context -> record has no run_id.
    assert get_run_context() is None
    bus = FakeBus()
    sink = AsyncJsonlSink(tmp_path / "no_run", name="research_events", flush_interval_s=0.05)
    obs = ResearchEventObserver(bus, sink, poll_interval_s=0.02)
    bus.push(
        "supervisor.out",
        _event(
            "supervisor",
            "supervisor.incident",
            {"incident_id": "inc-A", "transition": "freeze", "module": "language"},
        ),
    )
    await sink.start()
    await obs.start()
    await asyncio.sleep(0.2)
    await obs.stop()
    await sink.stop()
    files = list((tmp_path / "no_run").glob("research_events-*.jsonl"))
    assert files
    rows = [json.loads(ln) for ln in files[0].read_text().splitlines() if ln.strip()]
    inc = next(r for r in rows if r.get("event_type") == "supervisor.incident")
    assert inc["incident_id"] == "inc-A"
    assert "run_id" not in inc

    # 2) Run context set -> record carries run_id. Reset in finally.
    ctx = RunContext(
        run_id="runX",
        seed=1,
        started_at="2026-06-14T00:00:00+00:00",
        git_sha=None,
    )
    set_run_context(ctx)
    try:
        bus2 = FakeBus()
        sink2 = AsyncJsonlSink(tmp_path / "with_run", name="research_events", flush_interval_s=0.05)
        obs2 = ResearchEventObserver(bus2, sink2, poll_interval_s=0.02)
        bus2.push(
            "supervisor.out",
            _event(
                "supervisor",
                "supervisor.incident",
                {"incident_id": "inc-B", "transition": "detect", "module": "interoception"},
            ),
        )
        await sink2.start()
        await obs2.start()
        await asyncio.sleep(0.2)
        await obs2.stop()
        await sink2.stop()
        files2 = list((tmp_path / "with_run").glob("research_events-*.jsonl"))
        assert files2
        rows2 = [json.loads(ln) for ln in files2[0].read_text().splitlines() if ln.strip()]
        inc2 = next(r for r in rows2 if r.get("event_type") == "supervisor.incident")
        assert inc2["incident_id"] == "inc-B"
        assert inc2["run_id"] == "runX"
    finally:
        set_run_context(None)
    assert get_run_context() is None


@pytest.mark.asyncio
async def test_supervisor_incident_content_field_never_logged():
    """A content field smuggled into a supervisor.incident payload never reaches the
    record (allowlist-by-construction)."""
    bus = FakeBus()
    sink = FakeSink()
    obs = ResearchEventObserver(bus, sink, poll_interval_s=0.02)
    bus.push(
        "supervisor.out",
        _event(
            "supervisor",
            "supervisor.incident",
            {
                "incident_id": "inc-C",
                "transition": "detect",
                "module": "language",
                "internal_speech": "PRIVATE inner monologue",
                "text": "PRIVATE text",
            },
        ),
    )
    await _run(obs)
    assert len(sink.rows) == 1
    rec = sink.rows[0]
    assert rec["incident_id"] == "inc-C"
    assert _no_content_anywhere(rec)
    serialized = json.dumps(rec)
    assert "PRIVATE inner monologue" not in serialized
    assert "PRIVATE text" not in serialized


@pytest.mark.asyncio
async def test_every_record_carries_ts_event_type_source():
    bus = FakeBus()
    sink = FakeSink()
    obs = ResearchEventObserver(bus, sink, poll_interval_s=0.02)
    bus.push("cycle.out", _event("cycle", "cycle.tick", {"tick_index": 3, "slip_ms": 1.0}))
    await _run(obs)
    rec = sink.rows[0]
    assert set(["ts", "event_type", "source"]).issubset(rec.keys())
    assert rec["tick_index"] == 3
    # ts is ISO-8601 UTC parseable.
    datetime.fromisoformat(rec["ts"])


# ---------------------------------------------------------------------------
# Non-blocking capture
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_observer_runs_as_separate_task(tmp_path):
    bus = FakeBus()
    sink = AsyncJsonlSink(tmp_path, name="research_events", flush_interval_s=0.05)
    obs = ResearchEventObserver(bus, sink, poll_interval_s=0.02)
    await sink.start()
    await obs.start()
    await asyncio.sleep(0.05)
    assert obs._task is not None
    assert obs._task.get_name() == "sidecar-research_event_log"
    assert not obs._task.done()
    await obs.stop()
    await sink.stop()


@pytest.mark.asyncio
async def test_sink_queue_full_drops_oldest_and_counts():
    sink = AsyncJsonlSink("/tmp/does-not-matter", name="research_events", queue_maxsize=2)
    # Do NOT start the drain task, so the queue actually fills.
    await sink.write({"n": 1})
    await sink.write({"n": 2})
    assert sink.dropped_count == 0
    await sink.write({"n": 3})  # queue full → drop oldest, count increments
    assert sink.dropped_count == 1


# ---------------------------------------------------------------------------
# Raw bus archive: attestation gate + isolation
# ---------------------------------------------------------------------------


def test_raw_archive_disabled_by_default():
    cfg = RawArchiveConfig()
    assert cfg.enabled is False


@pytest.mark.asyncio
async def test_raw_archive_refuses_without_entity_privacy_attestation(tmp_path):
    """6.9 — entity_privacy_attested=false → start raises."""
    cfg = RawArchiveConfig(
        enabled=True,
        entity_privacy_attested=False,
        bystander_consent_attested=True,
        archive_dir=str(tmp_path / "raw"),
    )
    sink = FakeSink()
    consumer = RawBusArchiveConsumer(FakeBus(), sink, cfg)
    with pytest.raises(RawArchiveAttestationError):
        await consumer.start()


@pytest.mark.asyncio
async def test_raw_archive_refuses_without_bystander_attestation(tmp_path):
    """6.10 — bystander_consent_attested=false → start raises."""
    cfg = RawArchiveConfig(
        enabled=True,
        entity_privacy_attested=True,
        bystander_consent_attested=False,
        archive_dir=str(tmp_path / "raw"),
    )
    sink = FakeSink()
    consumer = RawBusArchiveConsumer(FakeBus(), sink, cfg)
    with pytest.raises(RawArchiveAttestationError):
        await consumer.start()


@pytest.mark.asyncio
async def test_raw_archive_starts_and_writes_verbatim_with_full_attestation(tmp_path):
    """6.11 — both attestations true → starts and writes verbatim (incl. text)."""
    cfg = RawArchiveConfig(
        enabled=True,
        entity_privacy_attested=True,
        bystander_consent_attested=True,
        archive_dir=str(tmp_path / "raw"),
    )
    bus = FakeBus()
    sink = AsyncJsonlSink(tmp_path / "raw", name="raw_bus_archive", flush_interval_s=0.05)
    bus.push(
        "language.out",
        _event("language", "external_speech", {"text": "VERBATIM conversation text"}),
    )
    consumer = RawBusArchiveConsumer(bus, sink, cfg)
    await sink.start()
    await consumer.start()
    await asyncio.sleep(0.25)
    await consumer.stop()
    await sink.stop()
    files = list((tmp_path / "raw").glob("raw_bus_archive-*.jsonl"))
    assert files, "raw archive should have written a file"
    rows = [json.loads(ln) for ln in files[0].read_text().splitlines() if ln.strip()]
    assert any(r.get("payload", {}).get("text") == "VERBATIM conversation text" for r in rows), (
        "raw archive must capture verbatim content (that is its purpose)"
    )


def test_raw_archive_path_outside_data_evaluation():
    """6.12 — archive_dir is structurally outside data/evaluation/."""
    cfg = RawArchiveConfig()
    assert "data/evaluation" not in cfg.archive_dir
    assert cfg.archive_dir.startswith("state/research")


def test_raw_archive_under_export_allowlist_rejected_at_config_load():
    """S1 — an archive_dir under data/evaluation/ fails closed at config load."""
    with pytest.raises(RawArchiveConfinementError):
        RawArchiveConfig.from_mapping({"archive_dir": "data/evaluation/raw_bus_archive"})
    # A nested path under the allowlist is also rejected.
    with pytest.raises(RawArchiveConfinementError):
        RawArchiveConfig.from_mapping({"archive_dir": "data/evaluation/research_events/../raw"})
    # The shipped default (outside the allowlist) is accepted.
    cfg = RawArchiveConfig.from_mapping({})
    assert cfg.archive_dir == "state/research/raw_bus_archive"


@pytest.mark.asyncio
async def test_raw_archive_consumer_rejects_allowlist_path_at_start():
    """S1 — the consumer re-validates confinement at start() (fail closed)."""
    # Construct the config bypassing from_mapping's validation to prove start()
    # is an independent gate.
    cfg = RawArchiveConfig.__new__(RawArchiveConfig)
    object.__setattr__(cfg, "enabled", True)
    object.__setattr__(cfg, "entity_privacy_attested", True)
    object.__setattr__(cfg, "bystander_consent_attested", True)
    object.__setattr__(cfg, "archive_dir", "data/evaluation/raw_bus_archive")
    object.__setattr__(cfg, "retention_days", 30)
    consumer = RawBusArchiveConsumer(FakeBus(), FakeSink(), cfg)
    with pytest.raises(RawArchiveConfinementError):
        await consumer.start()


@pytest.mark.asyncio
async def test_raw_archive_never_in_metrics_bundle(tmp_path):
    """6.13 — files under state/research/raw_bus_archive/ never appear in a
    metrics bundle (the builder only reads from eval_root)."""
    eval_root = tmp_path / "data" / "evaluation"
    # A legit metrics dir with a file (so the bundle is non-empty).
    (eval_root / "welfare").mkdir(parents=True)
    (eval_root / "welfare" / "welfare-2026-06-14.jsonl").write_text(
        json.dumps({"gray_zone_event": "x", "count": 1}) + "\n"
    )
    # The raw archive lives OUTSIDE eval_root.
    raw_dir = tmp_path / "state" / "research" / "raw_bus_archive"
    raw_dir.mkdir(parents=True)
    raw_dir.joinpath("raw_bus_archive-2026-06-14.jsonl").write_text(
        json.dumps({"payload": {"text": "VERBATIM SECRET"}}) + "\n"
    )

    out_dir = tmp_path / "out"
    bundle = build_research_bundle(eval_root=eval_root, tier="metrics", out_dir=out_dir)
    for bf in bundle.files:
        assert "raw_bus_archive" not in bf.rel_path
        assert "raw_bus_archive" not in bf.source_path
    # And nothing under the bundle dir mentions the secret.
    for p in bundle.bundle_dir.rglob("*"):
        if p.is_file():
            assert "VERBATIM SECRET" not in p.read_text(errors="ignore")


@pytest.mark.asyncio
async def test_curated_log_export_eligible_via_bundle(tmp_path):
    """Curated research_events dir IS picked up by the metrics bundle."""
    eval_root = tmp_path / "data" / "evaluation"
    re_dir = eval_root / "research_events"
    re_dir.mkdir(parents=True)
    re_dir.joinpath("research_events-2026-06-14.jsonl").write_text(
        json.dumps({"ts": "t", "event_type": "cycle.tick", "source": "cycle"}) + "\n"
    )
    out_dir = tmp_path / "out"
    bundle = build_research_bundle(eval_root=eval_root, tier="metrics", out_dir=out_dir)
    rels = [bf.rel_path for bf in bundle.files]
    assert any("research_events" in r for r in rels)


# ---------------------------------------------------------------------------
# Batch 1 / A1 — preservation + welfare events reach the research log + archive
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_preservation_event_captured_with_incident_id():
    """A1 — a preservation.preserved event on preservation.out is captured into a
    record carrying incident_id + operational fields, with content/paths absent."""
    bus = FakeBus()
    sink = FakeSink()
    obs = ResearchEventObserver(bus, sink, poll_interval_s=0.02)
    bus.push(
        "preservation.out",
        _event(
            "preservation",
            "preservation.preserved",
            {
                "monitor": "divergence",
                "transition": "preserved",
                "incident_id": "presinc-1",
                "reason": "individuation",
                "preservation_id": "pid1",
                "snapshot_id": "snap1",
                "world_model_captured": True,
                "poll_index": 4,
                # A smuggled content field must never reach the record.
                "internal_speech": "SECRET",
            },
        ),
    )
    await _run(obs)
    assert len(sink.rows) == 1
    rec = sink.rows[0]
    assert rec["event_type"] == "preservation.preserved"
    assert rec["incident_id"] == "presinc-1"
    assert rec["monitor"] == "divergence"
    assert rec["transition"] == "preserved"
    assert rec["preservation_id"] == "pid1"
    assert rec["snapshot_id"] == "snap1"
    assert rec["poll_index"] == 4
    assert _no_content_anywhere(rec)
    assert "internal_speech" not in rec


@pytest.mark.asyncio
async def test_welfare_protective_action_captured():
    """A1 — welfare.protective_action (published on preservation.out by the
    welfare-protective monitor) is captured with its operational fields."""
    bus = FakeBus()
    sink = FakeSink()
    obs = ResearchEventObserver(bus, sink, poll_interval_s=0.02)
    bus.push(
        "preservation.out",
        _event(
            "preservation",
            "welfare.protective_action",
            {
                "monitor": "welfare",
                "transition": "protective_action",
                "incident_id": "welinc-1",
                "reason": "repeated_gray_zone",
                "action": "pause",
                "distress_threshold": 0.8,
                "distress_duration_s": 30.0,
                "poll_index": 2,
            },
        ),
    )
    await _run(obs)
    assert len(sink.rows) == 1
    rec = sink.rows[0]
    assert rec["event_type"] == "welfare.protective_action"
    assert rec["incident_id"] == "welinc-1"
    assert rec["reason"] == "repeated_gray_zone"
    assert rec["action"] == "pause"
    assert _no_content_anywhere(rec)


@pytest.mark.asyncio
async def test_welfare_gray_zone_captured_numeric_only():
    """B3 — a welfare.gray_zone event on welfare.out is recorded with the label +
    EXACT numeric allowlist, and content never leaks."""
    bus = FakeBus()
    sink = FakeSink()
    obs = ResearchEventObserver(bus, sink, poll_interval_s=0.02)
    bus.push(
        "welfare.out",
        _event(
            "welfare",
            "welfare.gray_zone",
            {
                "gray_zone_event": "replay_overload",
                "replay_count_in_window": 12,
                "consolidation_window_s": 5.0,
                "threshold": 10,
                "replay_overload_count": 1,
                # Fields outside the exact allowlist must be dropped.
                "internal_speech": "SECRET",
                "some_future_field": "leak",
            },
        ),
    )
    await _run(obs)
    assert len(sink.rows) == 1
    rec = sink.rows[0]
    assert rec["event_type"] == "welfare.gray_zone"
    assert rec["gray_zone_event"] == "replay_overload"
    assert rec["replay_count_in_window"] == 12
    assert rec["threshold"] == 10
    # Exact allowlist drops the unknown field AND the content field.
    assert "some_future_field" not in rec
    assert "internal_speech" not in rec
    assert _no_content_anywhere(rec)


def test_welfare_and_preservation_in_curated_streams():
    """A1 + B3 — welfare.out and preservation.out are followed by the curated
    research observer."""
    assert "welfare.out" in _CURATED_STREAMS
    assert "preservation.out" in _CURATED_STREAMS


def test_raw_archive_includes_welfare_and_preservation_streams():
    """A1 + B4 — the local-only raw archive follows welfare.out and
    preservation.out."""
    assert "welfare.out" in _MODULE_OUT_STREAMS
    assert "preservation.out" in _MODULE_OUT_STREAMS


# ---------------------------------------------------------------------------
# Regression tests for the fix-research-event-contracts change (OpenSpec).
# Fixtures use the REAL producer payload shapes; the record copy is exercised
# through the observer's own module-level helpers.
# ---------------------------------------------------------------------------


def _taxonomy_record(event_type, payload):
    from kaine.evaluation.observers.research_event_observer import (
        _allowed_fields,
        _apply_taxonomy_fields,
    )

    allowed = _allowed_fields(event_type)
    assert allowed is not None, f"{event_type} must be in the taxonomy"
    return _apply_taxonomy_fields(
        event_type,
        payload,
        {"ts": "now", "event_type": event_type, "source": "test"},
    )


def test_intent_speak_think_act_survive_taxonomy():
    # Real action selection payload shape (kaine/workspace/action_selection.py).
    for kind, event_type in (
        ("speak", "intent.speak"),
        ("think", "intent.think"),
        ("act", "intent.act"),
    ):
        payload = {"kind": kind, "about_tag": "interoception:report", "effector": "vocal"}
        record = _taxonomy_record(event_type, payload)
        assert record["kind"] == kind
        assert record["about_tag"] == "interoception:report"
    # The phantom prefix key is gone; unknown intent subtypes are not logged.
    from kaine.evaluation.observers.research_event_observer import _allowed_fields

    assert _allowed_fields("action_selection.intent") is None
    assert _allowed_fields("intent.teleport") is None


def test_planning_action_event_types_in_taxonomy():
    from kaine.evaluation.observers.research_event_observer import _allowed_fields

    for event_type in (
        "planning.proposal",
        "intent.rest",
        "action_selection.proposal_outcome",
        "sleep.rest_request",
    ):
        assert _allowed_fields(event_type) is not None, event_type

    # Origin is retained on the action selection module's intents. The language module's speech events are content
    # and are deliberately not part of the research taxonomy.
    assert "origin" in _allowed_fields("intent.speak")
    assert "origin" in _allowed_fields("intent.think")
    assert "origin" in _allowed_fields("intent.act")
    rest_fields = _allowed_fields("intent.rest")
    assert "about_tag" in rest_fields
    assert "origin" in rest_fields
    assert "about" not in rest_fields


def test_workspace_selected_yields_coalition_metadata():
    from kaine.evaluation.observers.research_event_observer import (
        _workspace_metadata_record,
    )

    # Snapshot shape per kaine/cycle/engine.py (key `selected`).
    snapshot = {
        "tick_index": 42,
        "inhibited": False,
        "salience_scores": {"interoception:report": 0.7},
        "selected": [
            {
                "source": "interoception",
                "type": "interoception.report",
                "salience": 0.7,
                "causal_parent": None,
                "payload": {"secret": "never-logged"},
            }
        ],
    }
    record = _workspace_metadata_record(snapshot)
    assert record["tick_index"] == 42
    assert record["entries"][0]["source"] == "interoception"
    assert record["entries"][0]["salience"] == 0.7
    # Entry payload/content is NEVER copied.
    assert "payload" not in record["entries"][0]
    assert "secret" not in str(record)


def test_audition_perception_numeric_fields_logged_item_dropped():
    record = _taxonomy_record(
        "audition.perception",
        {
            "prediction_error": 0.4,
            "normalised_error": 1.2,
            "alert": False,
            "context_gain": 0.12,
            "null_prediction_error": 0.5,
            "mean_prediction_error": 0.8,
            "context_age_s": 0.3,
            "item": "film.mp4",
            "source_label": "playlist",
        },
    )
    assert record["context_gain"] == 0.12
    assert record["null_prediction_error"] == 0.5
    assert record["mean_prediction_error"] == 0.8
    assert record["alert"] is False
    assert record["context_age_s"] == 0.3
    assert "item" not in record


def test_processor_reports_carry_alert_and_context_gain():
    for event_type in ("vision.report", "interoception.report"):
        record = _taxonomy_record(
            event_type,
            {
                "prediction_error": 0.5,
                "alert": True,
                "context_gain": -0.05,
                "null_prediction_error": 0.5,
                "mean_prediction_error": 0.8,
                "context_age_s": 1.0,
            },
        )
        assert record["alert"] is True
        assert record["context_gain"] == -0.05
        assert record["null_prediction_error"] == 0.5
        assert record["mean_prediction_error"] == 0.8

    assert _taxonomy_record("sequence.report", {"alert": True})["alert"] is True


def test_positive_control_result_is_logged():
    from kaine.modules.positive_control import RESULT_FIELDS

    payload = {
        "processor": "vision",
        "n_reports": 5,
        "min_reports": 100,
        "ig_with": 0.1,
        "ig_without": 0.05,
        "ig_noise": 0.04,
        "effect": 0.05,
        "noise_effect": 0.01,
        "min_effect": 0.01,
        "snr": 10.0,
        "detected": True,
        "noise_detected": False,
        "passed": True,
        "failed": False,
        "final": True,
        "mode": "control",
        "t_learn_s": 120.0,
        "settings_sha256": "a" * 64,
        "pc_sha256": "b" * 64,
        "extra": "x",
    }
    record = _taxonomy_record("positive_control.result", payload)
    for field in RESULT_FIELDS:
        assert record[field] == payload[field]
    assert "extra" not in record


def test_workspace_record_carries_access_threshold_and_publication_time():
    from kaine.evaluation.observers.research_event_observer import (
        _workspace_metadata_record,
    )

    record = _workspace_metadata_record(
        {
            "tick_index": 1,
            "inhibited": False,
            "metadata": {"access_threshold": 0.35, "coherence": {"x": 1}},
            "published_at": 12.5,
            "selected": [],
        }
    )
    assert record["access_threshold"] == 0.35
    assert record["published_at"] == 12.5
    assert "coherence" not in record
    assert "metadata" not in record


def test_workspace_record_carries_arm():
    from kaine.evaluation.observers.research_event_observer import (
        _workspace_metadata_record,
    )

    record = _workspace_metadata_record(
        {
            "tick_index": 2,
            "inhibited": False,
            "metadata": {"access_threshold": 0.35, "arm": "matched"},
            "selected": [],
        }
    )
    assert record["arm"] == "matched"
    assert record["access_threshold"] == 0.35

    pooled = _workspace_metadata_record(
        {
            "tick_index": 3,
            "inhibited": False,
            "metadata": {"arm": "pooled"},
            "selected": [],
        }
    )
    assert pooled["arm"] == "pooled"
    assert "access_threshold" not in pooled


def test_workspace_selected_events_key_no_longer_used():
    from kaine.evaluation.observers.research_event_observer import (
        _workspace_metadata_record,
    )

    record = _workspace_metadata_record({"selected_events": [{"source": "interoception"}]})
    assert "entries" not in record


def test_sleep_sleep_started_started_at():
    # Real producer payload (kaine/modules/sleep/module.py).
    record = _taxonomy_record("sleep.sleep.started", {"started_at": 1717.5})
    assert record["started_at"] == 1717.5


def test_affect_emotion_emotion_field_retained():
    # Real producer payload (kaine/modules/affect/module.py).
    payload = {
        "emotion": "curiosity",
        "scores": {"curiosity": 0.8, "distress": 0.1},
        "norm_compatibility_available": True,
    }
    record = _taxonomy_record("affect.emotion", payload)
    assert record["emotion"] == "curiosity"
    assert record["scores"]["curiosity"] == 0.8
    assert record["norm_compatibility_available"] is True


def test_vision_report_fields_and_no_scene_change():
    # Real producer payload (kaine/modules/vision/module.py).
    payload = {
        "prediction_error": 0.21,
        "normalised_error": 0.13,
        "change_score": 0.04,
        "habituation_score": 0.77,
        "alert": False,
    }
    record = _taxonomy_record("vision.report", payload)
    assert record["prediction_error"] == 0.21
    assert record["normalised_error"] == 0.13
    assert record["change_score"] == 0.04
    assert record["habituation_score"] == 0.77
    assert record["alert"] is False
    # The producer-less vision.scene_change entry is gone entirely.
    from kaine.evaluation.observers.research_event_observer import (
        _TAXONOMY,
        _allowed_fields,
    )

    assert "vision.scene_change" not in _TAXONOMY
    assert _allowed_fields("vision.scene_change") is None


def test_sequence_report_content_free_allowlist():
    # Real sequence payload shape (kaine/modules/sequence/module.py) plus the
    # latent fields that must NEVER pass.
    payload = {
        "anomaly_score": 0.42,
        "habituation_score": 0.66,
        "rumination_detected": False,
        "temporal_prediction_error": 0.11,
        "time_since_last_interaction_s": 312.0,
        "temporal_context": ["SECRET", "LATENT", "TEXT"],
        "feature_vector": [0.1, 0.2, 0.3],
    }
    record = _taxonomy_record("sequence.report", payload)
    assert record["anomaly_score"] == 0.42
    assert record["rumination_detected"] is False
    assert record["time_since_last_interaction_s"] == 312.0
    assert "temporal_context" not in record
    assert "feature_vector" not in record


def test_sequence_out_in_curated_streams():
    from kaine.evaluation.observers.research_event_observer import _CURATED_STREAMS

    assert "sequence.out" in _CURATED_STREAMS


def test_no_latent_field_in_any_taxonomy_allowlist():
    from kaine.evaluation.observers.research_event_observer import _TAXONOMY

    latent = {"temporal_context", "feature_vector", "latent", "transcript", "text"}
    for event_type, fields in _TAXONOMY.items():
        assert not (set(fields) & latent), f"{event_type} allows latent content"


def test_audition_prosody_hz_fields():
    # Real producer payload (kaine/modules/audition/prosody.py).
    record = _taxonomy_record("audition.prosody", {"f0_mean_hz": 120.5, "f0_std_hz": 18.2})
    assert record["f0_mean_hz"] == 120.5
    assert record["f0_std_hz"] == 18.2


def test_raw_bus_archive_language_aggregate():
    """The language module now publishes an aggregate language.out stream; the raw archive
    follows the canonical module stream set, not the mode-specific split."""
    from kaine.evaluation.observers.raw_bus_archive_consumer import (
        _MODULE_OUT_STREAMS,
    )

    assert "language.out" in _MODULE_OUT_STREAMS
    assert "language.external" not in _MODULE_OUT_STREAMS
    assert "language.internal" not in _MODULE_OUT_STREAMS


@pytest.mark.asyncio
async def test_observer_drains_streams_on_stop():
    from datetime import datetime, timezone

    from kaine.bus.schema import Event

    bus = FakeBus()
    sink = FakeSink()
    obs = ResearchEventObserver(bus, sink, poll_interval_s=10.0)
    await obs.start()
    await asyncio.sleep(0.05)
    event = Event(
        source="positive_control",
        type="positive_control.result",
        payload={"processor": "vision", "n_reports": 5, "final": True},
        salience=0.0,
        timestamp=datetime.now(timezone.utc),
    )
    bus.push("positive_control.out", event)
    await obs.stop()
    assert len(sink.rows) == 1
    assert sink.rows[0]["event_type"] == "positive_control.result"
    assert sink.rows[0]["final"] is True


@pytest.mark.asyncio
async def test_welfare_blind_sensor_advisories_captured_with_exact_allowlist():
    """B3 - welfare blind-sensor advisories are copied with the processor label
    and exact numeric allowlist; unknown labels and bools are dropped."""
    bus = FakeBus()
    sink = FakeSink()
    obs = ResearchEventObserver(bus, sink, poll_interval_s=0.02)
    bus.push(
        "welfare.out",
        _event(
            "welfare",
            "welfare.blind_sensor",
            {
                "processor": "vision",
                "undefined_samples": 4,
                "undefined_seconds": 30.0,
                "blind_sensor_samples": 0,
                "blind_sensor_duration_s": 30.0,
                "blind_sensor_count": 1,
                # Content and future fields must be dropped by the allowlist.
                "internal_speech": "SECRET",
                "some_future_field": "leak",
            },
        ),
    )
    bus.push(
        "welfare.out",
        _event(
            "welfare",
            "welfare.blind_sensor_cleared",
            {
                "processor": "<script>",
                "undefined_samples": True,
                "blind_sensor_count": 1,
            },
        ),
    )
    await _run(obs)
    assert len(sink.rows) == 2

    rec = sink.rows[0]
    assert rec["event_type"] == "welfare.blind_sensor"
    assert rec["processor"] == "vision"
    assert rec["undefined_samples"] == 4
    assert rec["undefined_seconds"] == 30.0
    assert rec["blind_sensor_samples"] == 0
    assert rec["blind_sensor_duration_s"] == 30.0
    assert rec["blind_sensor_count"] == 1
    assert "internal_speech" not in rec
    assert "some_future_field" not in rec
    assert _no_content_anywhere(rec)

    cleared = sink.rows[1]
    assert cleared["event_type"] == "welfare.blind_sensor_cleared"
    assert "processor" not in cleared
    assert "undefined_samples" not in cleared
    assert cleared["blind_sensor_count"] == 1
    assert _no_content_anywhere(cleared)


async def test_welfare_sensor_silent_advisories_captured_with_exact_allowlist():
    """B3 - welfare sensor-silent advisories are copied with the processor label
    and exact numeric allowlist; unknown labels and bools are dropped."""
    bus = FakeBus()
    sink = FakeSink()
    obs = ResearchEventObserver(bus, sink, poll_interval_s=0.02)
    bus.push(
        "welfare.out",
        _event(
            "welfare",
            "welfare.sensor_silent",
            {
                "processor": "audition_acoustic",
                "silent_seconds": 30.0,
                "sensor_silent_duration_s": 30.0,
                "sensor_silent_count": 1,
                # Content and future fields must be dropped by the allowlist.
                "internal_speech": "SECRET",
                "some_future_field": "leak",
            },
        ),
    )
    bus.push(
        "welfare.out",
        _event(
            "welfare",
            "welfare.sensor_silent_cleared",
            {
                "processor": "<b>",
                "silent_seconds": True,
                "sensor_silent_count": 1,
            },
        ),
    )
    await _run(obs)
    assert len(sink.rows) == 2

    rec = sink.rows[0]
    assert rec["event_type"] == "welfare.sensor_silent"
    assert rec["processor"] == "audition_acoustic"
    assert rec["silent_seconds"] == 30.0
    assert rec["sensor_silent_duration_s"] == 30.0
    assert rec["sensor_silent_count"] == 1
    assert "internal_speech" not in rec
    assert "some_future_field" not in rec
    assert _no_content_anywhere(rec)

    cleared = sink.rows[1]
    assert cleared["event_type"] == "welfare.sensor_silent_cleared"
    assert "processor" not in cleared
    assert "silent_seconds" not in cleared
    assert cleared["sensor_silent_count"] == 1
    assert _no_content_anywhere(cleared)


def test_audition_emotion_record_carries_entry_id(tmp_path):
    observer = ResearchEventObserver(
        bus=None, sink=AsyncJsonlSink(tmp_path / "re", name="research_events")
    )
    event = Event(
        timestamp=datetime.now(timezone.utc),
        source="audition",
        type="audition.emotion",
        salience=0.8,
        payload={
            "category": "happy",
            "confidence": 0.9,
            "scores": {"happy": 0.9},
            "alert": True,
            "tone_error_ratio": 0.3,
            "tone_rule": "error_ratio",
            "classified": True,
            "latency_ms": 12.0,
        },
    )
    record = observer._build_record(event, "audition.out:5-0")
    assert record is not None
    assert record["entry_id"] == "audition.out:5-0"
    assert record["tone_error_ratio"] == 0.3
    assert record["tone_rule"] == "error_ratio"
    assert record["classified"] is True
    assert record["alert"] is True
    assert "latency_ms" not in record


@pytest.mark.asyncio
async def test_handle_writes_stream_qualified_tone_id(tmp_path):
    observer = ResearchEventObserver(
        bus=None, sink=AsyncJsonlSink(tmp_path / "re", name="research_events")
    )
    event = Event(
        timestamp=datetime.now(timezone.utc),
        source="audition",
        type="audition.emotion",
        salience=0.8,
        payload={
            "category": "happy",
            "confidence": 0.9,
            "scores": {"happy": 0.9},
            "alert": True,
            "tone_error_ratio": 0.3,
            "tone_rule": "error_ratio",
            "classified": True,
            "latency_ms": 12.0,
        },
    )
    written = []
    class _FakeSink:
        async def write(self, record):
            written.append(record)
    observer._sink = _FakeSink()
    await observer.handle("audition.out", "5-0", event)
    assert len(written) == 1
    assert written[0]["entry_id"] == "audition.out:5-0"


def test_workspace_metadata_record_copies_entry_id():
    from kaine.evaluation.observers.research_event_observer import (
        _workspace_metadata_record,
    )

    snapshot = {
        "tick_index": 42,
        "inhibited": False,
        "salience_scores": {"audition.out:5-0": 0.7},
        "selected": [
            {
                "entry_id": "audition.out:5-0",
                "source": "audition",
                "type": "audition.emotion",
                "salience": 0.7,
                "causal_parent": None,
                "payload": {"secret": "never-logged"},
            }
        ],
    }
    record = _workspace_metadata_record(snapshot)
    assert record["entries"][0]["entry_id"] == "audition.out:5-0"
    assert record["entries"][0]["source"] == "audition"
    assert "payload" not in record["entries"][0]
    assert "secret" not in str(record)


def test_audition_emotion_tone_error_ratio_bound():
    assert _bound_for("audition.emotion", "tone_error_ratio") == NONNEG
