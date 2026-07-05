# SPDX-License-Identifier: LicenseRef-CAL-0.2
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
from kaine.evaluation.config import (
    EvaluationConfig,
    RawArchiveConfig,
    RawArchiveConfinementError,
    ResearchEventLogConfig,
)
from kaine.evaluation.observers.raw_bus_archive_consumer import (
    RawArchiveAttestationError,
    RawBusArchiveConsumer,
)
from kaine.evaluation.observers.raw_bus_archive_consumer import _MODULE_OUT_STREAMS
from kaine.evaluation.observers.research_event_observer import (
    _CURATED_STREAMS,
    ResearchEventObserver,
)
from kaine.evaluation.registry import SidecarRegistry
from kaine.evaluation.sink import AsyncJsonlSink
from kaine.nexus.privacy import CONTENT_FIELDS
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
    rcfg = ResearchEventLogConfig(
        enabled=True, log_dir=str(tmp_path / "research_events")
    )
    sidecar = SidecarRegistry(
        bus=FakeBus(), config=eval_cfg, research_event_log_config=rcfg
    )
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
async def test_thymos_state_record_has_vad_no_affect_reason():
    """6.3 — thymos.state → VAD/emotion kept, affect_reason stripped."""
    bus = FakeBus()
    sink = FakeSink()
    obs = ResearchEventObserver(bus, sink, poll_interval_s=0.02)
    bus.push(
        "thymos.out",
        _event(
            "thymos",
            "thymos.state",
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
    assert rec["event_type"] == "thymos.state"
    assert rec["state"]["valence"] == pytest.approx(0.4)
    assert rec["emotion"] == "calm"
    assert "affect_reason" not in rec
    assert _no_content_anywhere(rec)
    assert bus.published == []


@pytest.mark.asyncio
async def test_mnemos_replay_text_redacted():
    """6.4 — mnemos.replay → memory ids + affect kept, text dropped."""
    bus = FakeBus()
    sink = FakeSink()
    obs = ResearchEventObserver(bus, sink, poll_interval_s=0.02)
    bus.push(
        "mnemos.out",
        _event(
            "mnemos",
            "mnemos.replay",
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
async def test_mundus_visual_raw_never_logged():
    """6.6 — mundus.visual.raw is not in the taxonomy → no record."""
    bus = FakeBus()
    sink = FakeSink()
    obs = ResearchEventObserver(bus, sink, poll_interval_s=0.02)
    bus.push(
        "mundus.out",
        _event("mundus", "mundus.visual.raw", {"frame": [0, 1, 2, 3]}),
    )
    await _run(obs)
    assert sink.rows == []


@pytest.mark.asyncio
async def test_praxis_action_content_stripped():
    """6.7 — praxis.action → metadata kept, content/body/stdout stripped."""
    bus = FakeBus()
    sink = FakeSink()
    obs = ResearchEventObserver(bus, sink, poll_interval_s=0.02)
    bus.push(
        "praxis.out",
        _event(
            "praxis",
            "praxis.action",
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
    # soma.report carries an extra content field that must be scrubbed.
    bus.push(
        "soma.out",
        _event(
            "soma",
            "soma.report",
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
async def test_eidolon_drift_scalar_only_no_self_model():
    """6.15 — eidolon.drift → scalars kept, no self-model doc."""
    bus = FakeBus()
    sink = FakeSink()
    obs = ResearchEventObserver(bus, sink, poll_interval_s=0.02)
    bus.push(
        "eidolon.out",
        _event(
            "eidolon",
            "eidolon.drift",
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
async def test_mundus_proprio_no_raw_coordinates():
    """mundus.proprio → opaque position hash + region label, never x/y/z."""
    bus = FakeBus()
    sink = FakeSink()
    obs = ResearchEventObserver(bus, sink, poll_interval_s=0.02)
    bus.push(
        "mundus.out",
        _event(
            "mundus",
            "mundus.proprio",
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
            "syneidesis",
            "workspace.broadcast",
            {
                "tick_index": 7,
                "inhibited": False,
                "salience_scores": {"thymos": 0.6},
                "selected_events": [
                    {
                        "source": "thymos",
                        "type": "thymos.state",
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
    assert rec["entries"][0]["source"] == "thymos"
    assert rec["entries"][0]["type"] == "thymos.state"
    assert "payload" not in rec["entries"][0]
    serialized = json.dumps(rec)
    assert "SECRET workspace content" not in serialized


@pytest.mark.asyncio
async def test_spot_incident_captured_with_incident_id():
    """freeze-run-annotation — spot.incident is captured into a record carrying
    incident_id + operational fields, with content/paths absent."""
    bus = FakeBus()
    sink = FakeSink()
    obs = ResearchEventObserver(bus, sink, poll_interval_s=0.02)
    bus.push(
        "spot.out",
        _event(
            "spot",
            "spot.incident",
            {
                "incident_id": "inc-123",
                "transition": "detect",
                "module": "lingua",
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
    assert rec["event_type"] == "spot.incident"
    assert rec["incident_id"] == "inc-123"
    assert rec["tick_index"] == 41
    assert rec["transition"] == "detect"
    assert rec["module"] == "lingua"
    assert rec["fault_class"] == "dead"
    assert rec["poll_index"] == 3
    assert _no_content_anywhere(rec)


@pytest.mark.asyncio
async def test_spot_incident_subtype_prefix_captured():
    """The spot.incident.* prefix family also routes to the spot.incident
    taxonomy entry."""
    bus = FakeBus()
    sink = FakeSink()
    obs = ResearchEventObserver(bus, sink, poll_interval_s=0.02)
    bus.push(
        "spot.out",
        _event(
            "spot",
            "spot.incident.restart",
            {
                "incident_id": "inc-9",
                "transition": "restart",
                "module": "soma",
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
async def test_spot_incident_record_stamped_with_run_id(tmp_path):
    """When a run context is set, the captured spot.incident record is stamped
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
    sink = AsyncJsonlSink(
        tmp_path / "no_run", name="research_events", flush_interval_s=0.05
    )
    obs = ResearchEventObserver(bus, sink, poll_interval_s=0.02)
    bus.push(
        "spot.out",
        _event(
            "spot",
            "spot.incident",
            {"incident_id": "inc-A", "transition": "freeze", "module": "lingua"},
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
    inc = next(r for r in rows if r.get("event_type") == "spot.incident")
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
        sink2 = AsyncJsonlSink(
            tmp_path / "with_run", name="research_events", flush_interval_s=0.05
        )
        obs2 = ResearchEventObserver(bus2, sink2, poll_interval_s=0.02)
        bus2.push(
            "spot.out",
            _event(
                "spot",
                "spot.incident",
                {"incident_id": "inc-B", "transition": "detect", "module": "soma"},
            ),
        )
        await sink2.start()
        await obs2.start()
        await asyncio.sleep(0.2)
        await obs2.stop()
        await sink2.stop()
        files2 = list((tmp_path / "with_run").glob("research_events-*.jsonl"))
        assert files2
        rows2 = [
            json.loads(ln)
            for ln in files2[0].read_text().splitlines()
            if ln.strip()
        ]
        inc2 = next(r for r in rows2 if r.get("event_type") == "spot.incident")
        assert inc2["incident_id"] == "inc-B"
        assert inc2["run_id"] == "runX"
    finally:
        set_run_context(None)
    assert get_run_context() is None


@pytest.mark.asyncio
async def test_spot_incident_content_field_never_logged():
    """A content field smuggled into a spot.incident payload never reaches the
    record (allowlist-by-construction)."""
    bus = FakeBus()
    sink = FakeSink()
    obs = ResearchEventObserver(bus, sink, poll_interval_s=0.02)
    bus.push(
        "spot.out",
        _event(
            "spot",
            "spot.incident",
            {
                "incident_id": "inc-C",
                "transition": "detect",
                "module": "lingua",
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
    sink = AsyncJsonlSink(
        tmp_path / "raw", name="raw_bus_archive", flush_interval_s=0.05
    )
    bus.push(
        "lingua.out",
        _event("lingua", "lingua.utterance", {"text": "VERBATIM conversation text"}),
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
    assert any(
        r.get("payload", {}).get("text") == "VERBATIM conversation text" for r in rows
    ), "raw archive must capture verbatim content (that is its purpose)"


def test_raw_archive_path_outside_data_evaluation():
    """6.12 — archive_dir is structurally outside data/evaluation/."""
    cfg = RawArchiveConfig()
    assert "data/evaluation" not in cfg.archive_dir
    assert cfg.archive_dir.startswith("state/research")


def test_raw_archive_under_export_allowlist_rejected_at_config_load():
    """S1 — an archive_dir under data/evaluation/ fails closed at config load."""
    with pytest.raises(RawArchiveConfinementError):
        RawArchiveConfig.from_mapping(
            {"archive_dir": "data/evaluation/raw_bus_archive"}
        )
    # A nested path under the allowlist is also rejected.
    with pytest.raises(RawArchiveConfinementError):
        RawArchiveConfig.from_mapping(
            {"archive_dir": "data/evaluation/research_events/../raw"}
        )
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
    bundle = build_research_bundle(
        eval_root=eval_root, tier="metrics", out_dir=out_dir
    )
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
    bundle = build_research_bundle(
        eval_root=eval_root, tier="metrics", out_dir=out_dir
    )
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
