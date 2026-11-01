# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The latent rule (change ``latent-content-privacy``): one tag, one strip, and
the record writers, renderers and broadcast record that apply it."""

from __future__ import annotations

import asyncio
import base64
import json
import os
from datetime import datetime, timezone

import numpy as np
import pytest

from kaine.bus.schema import Event
from kaine.cycle.engine import CognitiveCycle
from kaine.cycle.types import WorkspaceSnapshot
from kaine.faithful.felt import felt_renderer, redact_heard_speech_felt
from kaine.faithful.renderer import FaithfulRenderer
from kaine.faithful.templates import fallback_template, redact_heard_speech
from kaine.persistence.encrypted_jsonl import encode_record, iter_records, rewrite_encrypted
from kaine.persistence.jsonl_sink import AsyncJsonlSink
from kaine.privacy_filter import (
    LATENT_DERIVED_KEY,
    LATENT_FIELDS,
    LATENT_RULE_VERSION,
    VECTOR_FIELDS,
    PrivacyFilter,
    holds_latent_field,
    strip_latent,
    strip_vectors,
    without_latent_derived,
)
from kaine.security.crypto import CryptoConfig, StateEncryptor, set_state_encryptor
from tests._fakes import FakeClock, FakeRegistry, FakeWorkspace

# Recognisable latent numbers: none of them is a round value any other field uses.
CODE = [0.123457, -0.654321, 0.271828, 0.314159, -0.161803, 0.577215, 0.693147, -0.207879]
ASCENDING = [0.918273, -0.465564, 0.112358]
LATENT = [0.836541, -0.729183, 0.401234, 0.555123]


def _ev(source: str, type_: str, payload: dict, salience: float = 0.5) -> Event:
    return Event(
        source=source,
        type=type_,
        payload=payload,
        salience=salience,
        timestamp=datetime(2026, 10, 31, tzinfo=timezone.utc),
        causal_parent=None,
    )


def _latent_numbers_in(text: str) -> list[str]:
    """Every latent number of this module that appears in ``text``, at full
    precision or at the renderer's 4-decimal ``_fmt`` precision."""
    hits = []
    for value in CODE + ASCENDING + LATENT:
        for form in (repr(value), f"{value:.4f}".rstrip("0").rstrip(".")):
            if form in text:
                hits.append(form)
    return hits


@pytest.fixture(autouse=True)
def _plaintext_encryptor():
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=False)))
    yield
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=False)))


def _enable_encryption(monkeypatch) -> None:
    monkeypatch.setenv("KAINE_STATE_KEY", base64.b64encode(os.urandom(32)).decode("ascii"))
    set_state_encryptor(StateEncryptor(CryptoConfig(enabled=True)))


# ---------------------------------------------------------------------------
# The tag and strip_latent
# ---------------------------------------------------------------------------


def test_tag_is_a_vector_and_latent_field():
    assert LATENT_DERIVED_KEY == "latent_derived"
    assert "latent_derived" in VECTOR_FIELDS
    assert "latent_derived" in LATENT_FIELDS
    assert LATENT_FIELDS == VECTOR_FIELDS
    assert LATENT_RULE_VERSION == 1


def test_strip_latent_spec_example():
    record = {
        "workspace_feedback": {"gain": 1.1, "latent_derived": {"code": [0.2, 0.4]}},
        "latent": [0.1, 0.3],
    }
    assert strip_latent(record) == {"workspace_feedback": {"gain": 1.1}}


def test_strip_latent_nested_lists_tuples_arrays():
    record = {
        "members": [
            {"source": "vision", "latent": np.asarray(LATENT), "change": 0.2},
            ({"latent_derived": {"code": CODE}, "kept": 1},),
        ],
        "array_of_maps": np.asarray([{"foveal": [0.5, 0.6], "x": 2}], dtype=object),
        "deep": {"a": {"b": {"latent_derived": {"err": np.asarray(ASCENDING)}}}},
        "peripheral": [0.9] * 3,
        "temporal_context": [0.1, 0.2],
        "feature_vector": (0.3, 0.4),
    }
    out = strip_latent(record)
    assert out == {
        "members": [
            {"source": "vision", "change": 0.2},
            ({"kept": 1},),
        ],
        "array_of_maps": [{"x": 2}],
        "deep": {"a": {"b": {}}},
    }
    # Tuples stay tuples; the input is untouched.
    assert isinstance(out["members"][1], tuple)
    assert "latent" in record["members"][0]
    assert not holds_latent_field(out)
    assert holds_latent_field(record)
    assert holds_latent_field({"x": [({"y": {"latent_derived": {}}},)]})
    assert holds_latent_field({"x": np.asarray([{"latent": [1.0]}], dtype=object)})
    assert not holds_latent_field({"x": np.zeros(4), "y": [1, 2], "z": "latent"})


def test_strip_latent_keeps_long_reviewed_lists():
    record = {
        "saliences": [0.01 * i for i in range(40)],
        "step_magnitudes": list(range(64)),
        "scores": [0.1, 0.2, 0.3, 0.4, 0.5],
        "table": [[1.0, 2.0]] * 30,
        "text": "content keys are not this strip's business",
    }
    assert strip_latent(record) == record


def test_strip_latent_converts_an_unreviewed_array_to_exact_numbers():
    values = np.asarray([0.1234567891234, -2.5, 3.0e-9, 7.0, 1.0 / 3.0, 2.0, 5.5, 8.25])
    out = strip_latent({"scores": values})
    assert isinstance(out["scores"], list)
    assert out["scores"] == values.tolist()
    assert all(type(v) is float for v in out["scores"])


def test_without_latent_derived_is_copy_on_write():
    payload = {"change_score": 0.1, "latent": [0.2, 0.3], "nested": [{"a": (1, 2)}]}
    assert without_latent_derived(payload) is payload
    tagged = {"change_score": 0.1, "latent": [0.2], "nested": [{"latent_derived": {"c": CODE}, "a": 1}]}
    out = without_latent_derived(tagged)
    assert out == {"change_score": 0.1, "latent": [0.2], "nested": [{"a": 1}]}
    assert out["latent"] is tagged["latent"]
    assert "latent_derived" in tagged["nested"][0]


# ---------------------------------------------------------------------------
# The diagnostics filter and the episodic store's strip_vectors
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("dev_mode", [False, True])
def test_diagnostics_filter_removes_latent_derived_in_dev_mode(dev_mode):
    event = _ev(
        "cycle",
        "workspace.broadcast",
        {"metadata": {"workspace_feedback": {"gain": 1.0, "latent_derived": {"code": CODE}}}},
    )
    filtered = PrivacyFilter(dev_content_override=dev_mode).filter(event)
    assert filtered.payload == {"metadata": {"workspace_feedback": {"gain": 1.0}}}
    assert strip_vectors({"latent_derived": {"code": CODE[:2]}, "k": 1}) == {"k": 1}


# ---------------------------------------------------------------------------
# The JSONL sink
# ---------------------------------------------------------------------------


def _sink_rows(directory, name):
    rows = []
    for path in sorted(directory.glob(f"{name}-*.jsonl")):
        rows.extend(json.loads(ln) for ln in path.read_text().splitlines() if ln.strip())
    return rows


def _tagged_record(label: str) -> dict:
    return {
        "label": label,
        "payload": {
            "change_score": 0.25,
            "latent": list(LATENT),
            "latent_derived": {"ascending_error": list(ASCENDING)},
        },
        "metadata": {"workspace_feedback": {"latent_derived": {"code": list(CODE)}}},
    }


@pytest.mark.asyncio
async def test_sink_strips_latent_on_write_write_sync_and_enqueue(tmp_path):
    sink = AsyncJsonlSink(tmp_path, name="probe", flush_interval_s=0.02)
    await sink.start()
    try:
        await sink.write(_tagged_record("write"))
        sink.enqueue(_tagged_record("enqueue"))
        sink.write_sync(_tagged_record("write_sync"))
        await asyncio.sleep(0.15)
    finally:
        await sink.stop()
    rows = _sink_rows(tmp_path, "probe")
    assert sorted(r["label"] for r in rows) == ["enqueue", "write", "write_sync"]
    raw = "".join(p.read_text() for p in tmp_path.glob("probe-*.jsonl"))
    assert "latent" not in raw
    assert _latent_numbers_in(raw) == []
    for row in rows:
        assert row["payload"] == {"change_score": 0.25}
        assert row["metadata"] == {"workspace_feedback": {}}


def test_sink_writes_unreviewed_array_as_exact_list(tmp_path):
    values = np.asarray([0.1234567891234, -2.5, 3.0e-9, 7.0, 1.0 / 3.0, 2.0, 5.5, 8.25])
    sink = AsyncJsonlSink(tmp_path, name="probe")
    sink.write_sync({"scores": values, "latent": np.asarray(LATENT)})
    (row,) = _sink_rows(tmp_path, "probe")
    assert row == {"scores": values.tolist()}


# ---------------------------------------------------------------------------
# The encrypted JSONL writer (intent log, sleep corpus)
# ---------------------------------------------------------------------------


def test_encrypted_jsonl_strips_latent(tmp_path, monkeypatch):
    _enable_encryption(monkeypatch)
    path = tmp_path / "intent.jsonl"
    clean_line = json.dumps({"generated_text": "hello", "n": [1, 2]})
    tagged_line = json.dumps(
        {"generated_text": "x", "snapshot_summary": {"latent_derived": {"code": CODE}, "k": 1}}
    )
    with path.open("w", encoding="utf-8") as fh:
        fh.write(encode_record(_tagged_record("encoded")) + "\n")
        fh.write(clean_line + "\n")
        fh.write(tagged_line + "\n")
        fh.write("not json at all\n")
    assert rewrite_encrypted(path) is True
    raw = path.read_text()
    assert "generated_text" not in raw  # every line is an envelope now
    lines = list(iter_records(path))
    # The non-JSON line is kept (encrypted) and reads back as unreadable.
    assert [ln.unreadable for ln in lines] == [False, False, False, True]
    encoded, clean, tagged = (ln.record for ln in lines[:3])
    assert encoded["payload"] == {"change_score": 0.25}
    assert encoded["metadata"] == {"workspace_feedback": {}}
    assert clean == json.loads(clean_line)
    assert tagged == {"generated_text": "x", "snapshot_summary": {"k": 1}}
    decrypted = json.dumps([encoded, clean, tagged])
    assert "latent" not in decrypted
    assert _latent_numbers_in(decrypted) == []


def test_rewrite_keeps_a_clean_plaintext_line_byte_for_byte(tmp_path, monkeypatch):
    _enable_encryption(monkeypatch)
    from kaine.security.crypto import get_state_encryptor

    path = tmp_path / "corpus.jsonl"
    line = '{"b": 1,   "a": [0.10000, 2]}'
    path.write_text(line + "\n", encoding="utf-8")
    assert rewrite_encrypted(path) is True
    envelope = path.read_text().strip()
    assert get_state_encryptor().decrypt(envelope.encode("ascii")).decode("utf-8") == line


def test_intent_log_numeric_rendering_holds_no_latent_number(tmp_path, monkeypatch):
    from kaine.modules.language.context import ContextAssembler
    from kaine.modules.language.intent_log import IntentExpressionLog

    _enable_encryption(monkeypatch)
    # language.internal_speech is an internal type with no numeric template, so
    # its numeric rendering falls through to fallback_template.
    snap = WorkspaceSnapshot(
        tick_index=3,
        selected_events=[
            ("s", _ev("language", "internal_speech", {"mood": 0.4, "latent_derived": {"code": CODE}})),
        ],
        salience_scores={"s": 0.7},
    )
    ctx = ContextAssembler(awareness_rendering="felt").assemble(
        about="x", snapshot=snap, self_model={}, mode="internal", about_is_heard=False
    )
    assert "mood=0.4" in ctx.numeric_working_memory
    log = IntentExpressionLog(tmp_path / "intent_log.jsonl")
    log.append(
        mode="internal",
        prompt=ctx.logged_prompt,
        generated_text="a thought",
        model="fake",
        faithful_rendering=ctx.logged_working_memory,
        numeric_rendering=ctx.numeric_working_memory,
        snapshot_summary={"latent_derived": {"code": CODE}, "tick": 3},
    )
    (line,) = list(iter_records(log.path))
    decrypted = json.dumps(line.record)
    assert "latent" not in decrypted
    assert _latent_numbers_in(decrypted) == []
    assert line.record["snapshot_summary"] == {"tick": 3}


# ---------------------------------------------------------------------------
# The trajectory and the raw archive (both through the sink)
# ---------------------------------------------------------------------------


class _WorkspaceBus:
    def __init__(self, broadcasts):
        self._broadcasts = broadcasts

    async def subscribe_workspace(self, last_id="$", count=32, poll_interval_s=0.05):
        for entry_id, payload in self._broadcasts:
            yield entry_id, payload


@pytest.mark.asyncio
async def test_trajectory_record_has_no_latent_derived(tmp_path):
    from kaine.evaluation.trajectory import TrajectoryRecorder

    broadcast = {
        "tick_index": 1,
        "is_experiential": True,
        "inhibited": False,
        "salience_scores": {"1-0": 0.9},
        "selected": [{"entry_id": "1-0", "source": "vision", "type": "vision.report", "salience": 0.9}],
        "metadata": {"workspace_feedback": {"gain": 0.5, "latent_derived": {"code": list(CODE)}}},
    }
    sink = AsyncJsonlSink(tmp_path, name="trajectory", flush_interval_s=0.02)
    await sink.start()
    rec = TrajectoryRecorder(_WorkspaceBus([("1-0", broadcast)]), sink)
    await rec.start()
    for _ in range(100):
        await asyncio.sleep(0.01)
        if sink.wrote_count:
            break
    await rec.stop()
    await sink.stop()
    (row,) = _sink_rows(tmp_path, "trajectory")
    assert row["metadata"] == {"workspace_feedback": {"gain": 0.5}}
    raw = "".join(p.read_text() for p in tmp_path.glob("trajectory-*.jsonl"))
    assert "latent_derived" not in raw
    assert _latent_numbers_in(raw) == []


class _StreamBus:
    def __init__(self) -> None:
        self.streams: dict[str, list[tuple[str, Event]]] = {}
        self._next = 1

    def push(self, stream: str, event: Event) -> None:
        self.streams.setdefault(stream, []).append((f"{self._next}-0", event))
        self._next += 1

    async def read_entries(self, stream, last_id="0", count=100, block_ms=0):
        entries = self.streams.get(stream, [])
        start = 0
        if last_id not in ("0", "0-0"):
            for i, (eid, _) in enumerate(entries):
                if eid == last_id:
                    start = i + 1
        batch = entries[start : start + count]
        return batch, (batch[-1][0] if batch else None)

    async def read(self, stream, *, last_id="0", count=100, block_ms=0):
        return (await self.read_entries(stream, last_id, count, block_ms))[0]


@pytest.mark.asyncio
async def test_raw_archive_holds_no_latent(tmp_path):
    from kaine.evaluation.config import RawArchiveConfig
    from kaine.evaluation.observers.raw_bus_archive_consumer import RawBusArchiveConsumer

    cfg = RawArchiveConfig(
        enabled=True,
        entity_privacy_attested=True,
        bystander_consent_attested=True,
        archive_dir=str(tmp_path / "raw"),
    )
    bus = _StreamBus()
    bus.push(
        "vision.out",
        _ev(
            "vision",
            "vision.report",
            {
                "change_score": 0.31,
                "latent": list(LATENT),
                "peripheral": list(LATENT),
                "foveal": list(LATENT),
                "fovea": [0.5, 0.5],
            },
        ),
    )
    bus.push(
        "language.out",
        _ev(
            "language",
            "external_speech",
            {"text": "VERBATIM words", "context": {"latent_derived": {"code": list(CODE)}}},
        ),
    )
    sink = AsyncJsonlSink(tmp_path / "raw", name="raw_bus_archive", flush_interval_s=0.02)
    consumer = RawBusArchiveConsumer(bus, sink, cfg)
    await sink.start()
    await consumer.start()
    for _ in range(100):
        await asyncio.sleep(0.01)
        if sink.wrote_count >= 2:
            break
    await consumer.stop()
    await sink.stop()
    rows = _sink_rows(tmp_path / "raw", "raw_bus_archive")
    by_type = {r["type"]: r for r in rows}
    assert by_type["vision.report"]["payload"] == {"change_score": 0.31, "fovea": [0.5, 0.5]}
    assert by_type["external_speech"]["payload"] == {"text": "VERBATIM words", "context": {}}
    raw = "".join(p.read_text() for p in (tmp_path / "raw").glob("*.jsonl"))
    assert _latent_numbers_in(raw) == []


# ---------------------------------------------------------------------------
# The renderers
# ---------------------------------------------------------------------------


def _perception(**extra) -> Event:
    payload = {
        "change_score": 0.0421,
        "prediction_error": 0.8765,
        "normalised_error": 1.2,
        "encoder_model_id": "fake-acoustic",
        "latent": list(LATENT),
        "latent_derived": {"ascending_error": list(ASCENDING), "code": list(CODE)},
    }
    payload.update(extra)
    return _ev("audition", "audition.perception", payload)


@pytest.mark.parametrize("rendering", ["felt", "numeric"])
def test_numeric_rendering_of_audition_perception_holds_no_latent_number(rendering):
    from kaine.modules.language.context import ContextAssembler

    snap = WorkspaceSnapshot(
        tick_index=1,
        selected_events=[("a", _perception())],
        salience_scores={"a": 0.8},
    )
    ctx = ContextAssembler(awareness_rendering=rendering).assemble(
        about="x", snapshot=snap, self_model={}, mode="internal", about_is_heard=False
    )
    surfaces = [ctx.prompt, ctx.working_memory, ctx.logged_prompt, ctx.logged_working_memory]
    if rendering == "felt":
        surfaces.append(ctx.numeric_working_memory)
        # The numeric sidecar comes from the audition.perception template.
        assert "Audition via fake-acoustic reports change 0.0421" in ctx.numeric_working_memory
    else:
        assert "Audition via fake-acoustic reports change 0.0421" in ctx.prompt
    for text in surfaces:
        assert _latent_numbers_in(text) == []
        assert "latent" not in text


class _RecordingTemplate:
    def __init__(self) -> None:
        self.payloads: list[dict] = []

    def __call__(self, payload: dict) -> str:
        self.payloads.append(payload)
        return f"saw {sorted(payload)}"


def test_render_event_strips_before_the_template():
    template = _RecordingTemplate()
    renderer = FaithfulRenderer(templates={("audition", "audition.perception"): template})
    renderer.render_event(_perception())
    (seen,) = template.payloads
    assert not holds_latent_field(seen)
    assert seen["change_score"] == 0.0421


def test_render_event_strips_before_the_fallback():
    seen: list[dict] = []

    def fallback(source, type_, payload):
        seen.append(payload)
        return "fallback"

    FaithfulRenderer(templates={}, fallback=fallback).render_event(_perception())
    assert len(seen) == 1 and not holds_latent_field(seen[0])


def test_fallback_template_names_scalars_and_no_latent_number():
    payload = {"mood": 0.4, "latent_derived": {"code": list(CODE)}, "nested": {"latent": list(LATENT), "n": 2}}
    text = fallback_template("language", "internal_speech", payload)
    assert "mood=0.4" in text
    assert "latent" not in text
    assert _latent_numbers_in(text) == []
    # A renderer with no template for the pair goes the same way.
    text = FaithfulRenderer(templates={}).render_event(_ev("x", "x.thing", payload))
    assert "mood=0.4" in text and _latent_numbers_in(text) == []


@pytest.mark.parametrize("external", [True, False])
def test_redact_heard_speech_strips_before_template_and_fallback(external):
    template = _RecordingTemplate()
    if external:
        event = _ev(
            "embodiment",
            "embodiment.chat",
            {"text": "hello", "latent_derived": {"code": list(CODE)}, "latent": list(LATENT)},
        )
    else:
        # A heard-text field on an internal event takes the field-redaction path.
        event = _ev(
            "audition",
            "audition.perception",
            {"user_input": "words", "latent_derived": {"code": list(CODE)}, "change_score": 0.1},
        )
    key = (event.source, event.type)
    out = redact_heard_speech(event, templates={key: template})
    assert out is not None
    (seen,) = template.payloads
    assert not holds_latent_field(seen)
    seen_fallback: list[dict] = []

    def fallback(source, type_, payload):
        seen_fallback.append(payload)
        return "fallback"

    assert redact_heard_speech(event, templates={}, fallback=fallback) == "fallback"
    assert len(seen_fallback) == 1 and not holds_latent_field(seen_fallback[0])


def test_felt_renderers_hold_no_latent_number():
    event = _perception()
    for text in (
        felt_renderer().render_event(event),
        redact_heard_speech_felt(_perception(user_input="words")) or "",
    ):
        assert _latent_numbers_in(text) == []
        assert not any(ch.isdigit() for ch in text)


# ---------------------------------------------------------------------------
# The broadcast record
# ---------------------------------------------------------------------------


class _NullBus:
    async def read(self, *a, **k):
        return []


def _cycle() -> CognitiveCycle:
    clk = FakeClock()
    return CognitiveCycle(
        bus=_NullBus(),
        workspace=FakeWorkspace(),
        registry=FakeRegistry([]),
        processing_rate_hz=3.333,
        experiential_rate_hz=3.333,
        clock=clk,
        sleep=clk.sleep,
        deterministic=True,
    )


def _reference_payload(cycle: CognitiveCycle, snapshot: WorkspaceSnapshot, is_experiential: bool) -> dict:
    """The broadcast payload as the cycle built it before the latent rule."""
    return {
        "tick_index": snapshot.tick_index,
        "inhibited": snapshot.inhibited,
        "is_experiential": is_experiential,
        "time_scale": cycle._entity_clock.scale,
        "published_at": cycle._entity_clock.now(),
        "salience_scores": dict(snapshot.salience_scores),
        "metadata": dict(snapshot.metadata),
        "selected": [
            {
                "entry_id": entry_id,
                "source": ev.source,
                "type": ev.type,
                "salience": ev.salience,
                "payload": ev.payload,
                "timestamp": ev.timestamp.isoformat(),
                "causal_parent": ev.causal_parent,
            }
            for entry_id, ev in snapshot.selected_events
        ],
    }


def test_broadcast_drops_member_latent_derived():
    cycle = _cycle()
    vision = _ev(
        "vision",
        "vision.report",
        {
            "change_score": 0.2,
            "latent": list(LATENT),
            "latent_derived": {"ascending_error": list(ASCENDING)},
            "nested": {"latent_derived": {"code": list(CODE)}, "k": 1},
        },
    )
    snapshot = WorkspaceSnapshot(
        tick_index=4,
        selected_events=[("1-0", vision)],
        salience_scores={"1-0": 0.9},
        metadata={"workspace_feedback": {"latent_derived": {"code": list(CODE)}}},
    )
    payload = cycle._snapshot_to_payload(snapshot, True)
    member = payload["selected"][0]["payload"]
    assert member == {"change_score": 0.2, "latent": list(LATENT), "nested": {"k": 1}}
    # The event itself is untouched (other consumers in the process hold it).
    assert "latent_derived" in vision.payload
    # Members only in this PR; the metadata is the content code's carrier and
    # the sinks strip it (the bus rule is a separate, pending change).
    assert payload["metadata"] == snapshot.metadata


def test_broadcast_bit_identical_without_latent_derived():
    cycle = _cycle()
    events = [
        ("1-0", _ev("vision", "vision.report", {"change_score": 0.2, "latent": list(LATENT), "fovea": (0.5, 0.5)})),
        ("2-0", _ev("interoception", "interoception.report", {"wellness": 0.8, "alerts": [], "nested": [{"a": 1}]})),
        ("3-0", _ev("sequence", "sequence.report", {"temporal_context": [0.1] * 32, "anomaly_score": 0.1})),
    ]
    snapshot = WorkspaceSnapshot(
        tick_index=9,
        selected_events=events,
        inhibited=False,
        salience_scores={"1-0": 0.9, "2-0": 0.4, "3-0": 0.3},
        metadata={"coherence": {"vision-audition": 0.4}},
    )
    payload = cycle._snapshot_to_payload(snapshot, False)
    reference = _reference_payload(cycle, snapshot, False)
    assert payload == reference
    assert json.dumps(payload) == json.dumps(reference)
    for member, (_eid, ev) in zip(payload["selected"], events):
        assert member["payload"] is ev.payload


# ---------------------------------------------------------------------------
# Module-state captures (PR 2)
# ---------------------------------------------------------------------------


class _StateModule:
    def __init__(self, name: str, state: dict) -> None:
        self.name = name
        self._state = state

    def serialize(self) -> dict:
        import copy

        return copy.deepcopy(self._state)

    def deserialize(self, state: dict) -> None:
        self._state = dict(state)


class _Registry:
    def __init__(self, *modules) -> None:
        self._modules = list(modules)

    def all_modules(self):
        return list(self._modules)


_WEIGHTS = {"layers": [{"weight": [[0.11, -0.22], [0.33, 0.44]], "bias": [0.05, -0.06]}]}


def _leaky_state() -> dict:
    return {
        "count": 3,
        "forward_model": _WEIGHTS,
        "latent_derived": {"code": list(CODE)},
        "history": [{"tick": 1, "latent": list(LATENT)}],
    }


def _stripped_leaky() -> dict:
    return {"count": 3, "forward_model": _WEIGHTS, "history": [{"tick": 1}]}


def _assert_no_latent_text(text: str) -> None:
    assert "latent_derived" not in text
    assert '"latent"' not in text
    assert _latent_numbers_in(text) == []


def _latent_errors(caplog) -> list[str]:
    return [
        r.getMessage()
        for r in caplog.records
        if r.name == "kaine.lifecycle.latent_strip" and r.levelname == "ERROR"
    ]


def test_strip_module_states_is_copy_on_write():
    from kaine.lifecycle.latent_strip import strip_module_states

    clean = {"forward_model": _WEIGHTS, "n": 1}
    states, meta = strip_module_states({"vision": clean}, capture="test")
    assert states["vision"] is clean
    assert meta == {}


def test_strip_module_states_never_raises(caplog):
    from kaine.lifecycle.latent_strip import LATENT_SCAN_FAILED_KEY, strip_module_states

    deep: dict = {}
    node = deep
    for _ in range(5000):
        node["n"] = {}
        node = node["n"]
    with caplog.at_level("ERROR", logger="kaine.lifecycle.latent_strip"):
        states, meta = strip_module_states({"deep": deep, "leaky": _leaky_state()}, capture="test")
    assert states["deep"] is deep
    assert states["leaky"] == _stripped_leaky()
    assert meta == {"latent_stripped": ["leaky"], LATENT_SCAN_FAILED_KEY: ["deep"]}


def test_fork_snapshot_strips_and_records_latent(tmp_path, caplog):
    from kaine.lifecycle.manager import ForkManager
    from kaine.lifecycle.snapshot import snapshot_dir

    registry = _Registry(
        _StateModule("vision", {"forward_model": _WEIGHTS}),
        _StateModule("leaky", _leaky_state()),
    )
    mgr = ForkManager(tmp_path / "forks")
    with caplog.at_level("ERROR", logger="kaine.lifecycle.latent_strip"):
        snap = mgr.snapshot(registry, label="t")
    assert snap.modules["leaky"] == _stripped_leaky()
    assert snap.modules["vision"] == {"forward_model": _WEIGHTS}
    assert snap.metadata["latent_stripped"] == ["leaky"]
    assert mgr.load(snap.id).metadata["latent_stripped"] == ["leaky"]
    _assert_no_latent_text((snapshot_dir(tmp_path / "forks", snap.id) / "snapshot.json").read_text())
    (message,) = _latent_errors(caplog)
    assert "leaky" in message and "fork snapshot" in message
    assert _latent_numbers_in(message) == []


@pytest.mark.asyncio
async def test_preservation_strips_and_is_never_refused(tmp_path, caplog):
    from kaine.lifecycle.preservation import preserve_live
    from kaine.lifecycle.snapshot import load_snapshot

    registry = _Registry(
        _StateModule("vision", {"forward_model": _WEIGHTS}),
        _StateModule("leaky", _leaky_state()),
    )
    with caplog.at_level("ERROR", logger="kaine.lifecycle.latent_strip"):
        result = await preserve_live(
            registry,
            fork_root=tmp_path / "forks",
            out_root=tmp_path / "backups",
            entity_name="probe",
            reason="test",
            stage_path=tmp_path / "stage.json",
            individuation_root=tmp_path / "individuation",
        )
    assert result.ok
    snap = load_snapshot(tmp_path / "forks", result.snapshot_id)
    assert snap.modules["leaky"] == _stripped_leaky()
    assert snap.modules["vision"] == {"forward_model": _WEIGHTS}
    assert snap.metadata["latent_stripped"] == ["leaky"]
    for path in list((tmp_path / "forks").rglob("*")) + list((tmp_path / "backups").rglob("*")):
        if path.is_file():
            data = path.read_bytes()
            if path.suffix == ".tar":
                import tarfile

                with tarfile.open(path) as tar:
                    for member in tar.getmembers():
                        fh = tar.extractfile(member)
                        if fh is not None:
                            _assert_no_latent_text(fh.read().decode("utf-8", "replace"))
            else:
                _assert_no_latent_text(data.decode("utf-8", "replace"))
    assert any("preservation" in m and "leaky" in m for m in _latent_errors(caplog))


@pytest.mark.asyncio
async def test_resume_checkpoint_strips_latent(tmp_path, monkeypatch, caplog):
    from kaine.lifecycle.identity import mint_identity
    from kaine.lifecycle.resume_checkpoint import checkpoint_file, read_checkpoint, save_checkpoint

    _enable_encryption(monkeypatch)
    registry = _Registry(
        _StateModule("vision", {"forward_model": _WEIGHTS}),
        _StateModule("leaky", _leaky_state()),
    )
    d = tmp_path / "ckpt"
    with caplog.at_level("ERROR", logger="kaine.lifecycle.latent_strip"):
        assert await save_checkpoint(registry, mint_identity(), reason="periodic", directory=d)
    snap = read_checkpoint(d)
    assert snap.modules["leaky"] == _stripped_leaky()
    assert snap.modules["vision"] == {"forward_model": _WEIGHTS}
    assert snap.metadata["latent_stripped"] == ["leaky"]
    from kaine.security.crypto import get_state_encryptor

    plaintext = get_state_encryptor().maybe_decrypt(checkpoint_file(d).read_bytes()).decode("utf-8")
    _assert_no_latent_text(plaintext)
    assert any("resume checkpoint" in m and "leaky" in m for m in _latent_errors(caplog))


class _VisionEncoder:
    model_id = "fake/encoder-latent-test"
    latent_dim = 4
    clip_len = 1

    async def load(self) -> None:
        pass

    async def shutdown(self) -> None:
        pass

    async def encode(self, image):  # noqa: ARG002
        return [0.4, 0.1, -0.3, 0.2]

    async def encode_clip(self, frames):
        return await self.encode(frames[-1])


def test_snapshot_keeps_forward_model_weights(tmp_path, caplog):
    from types import SimpleNamespace

    from kaine.lifecycle.manager import ForkManager
    from kaine.modules.vision import Vision
    from kaine.modules.vision.forward import LatentForwardModel

    vision = Vision(SimpleNamespace(), encoder=_VisionEncoder(), forward_prediction=True)
    fm = LatentForwardModel(latent_dim=4, units=16, seed=7, lr=0.05)
    for i in range(6):
        fm.step([0.4, 0.1 * i, -0.3, 0.2])
    vision._forward_model = fm
    expected = vision.serialize()
    with caplog.at_level("ERROR", logger="kaine.lifecycle.latent_strip"):
        snap = ForkManager(tmp_path / "forks").snapshot(_Registry(vision))
    assert snap.modules["vision"] == expected
    assert snap.modules["vision"]["forward_model"] == fm.state_dict()
    assert any(layer.get("weight") for layer in snap.modules["vision"]["forward_model"]["layers"])
    assert set(snap.modules["vision"]["buffer_summary"]) == {"n_frames", "mean_norm", "mean_variance"}
    assert "latent_stripped" not in snap.metadata
    assert _latent_errors(caplog) == []


def test_serialize_error_record_keeps_type_and_200_characters(tmp_path, caplog):
    from kaine.lifecycle.manager import ForkManager

    long_message = "0.123457, " * 500  # 5000 characters, latent-looking numbers

    class Boom:
        name = "boom"

        def serialize(self):
            raise ValueError(long_message)

        def deserialize(self, _state):
            pass

    with caplog.at_level("WARNING", logger="kaine.lifecycle.manager"):
        snap = ForkManager(tmp_path / "forks").snapshot(_Registry(Boom()))
    record = snap.modules["boom"]["_serialize_error"]
    assert record == "ValueError: " + long_message[:200]
    assert len(record) <= len("ValueError: ") + 200
    for rec in caplog.records:
        assert len(rec.getMessage()) < 400


# ---------------------------------------------------------------------------
# The encryption boot check for latent producers (PR 2)
# ---------------------------------------------------------------------------


def test_latent_producer_passes_with_everything_in_place(monkeypatch):
    from kaine.security.latent_producer import check_latent_producer

    _enable_encryption(monkeypatch)
    check_latent_producer("probe", require_encryption=True)


def test_latent_producer_refused_without_encryption():
    from kaine.security.latent_producer import LatentProducerRefused, check_latent_producer

    with pytest.raises(LatentProducerRefused) as info:
        check_latent_producer("probe", require_encryption=True)
    assert len(info.value.reasons) == 1
    assert "state encryption is not in effect" in info.value.reasons[0]


@pytest.mark.parametrize("value", [False, None, "true", 1])
def test_latent_producer_refused_without_require_encryption(monkeypatch, value):
    from kaine.security.latent_producer import LatentProducerRefused, check_latent_producer

    _enable_encryption(monkeypatch)
    with pytest.raises(LatentProducerRefused) as info:
        check_latent_producer("probe", require_encryption=value)
    assert len(info.value.reasons) == 1
    assert "require_encryption" in str(info.value)


@pytest.mark.parametrize("version", [None, 0, True])
def test_latent_producer_refused_without_the_latent_rule(monkeypatch, version):
    import kaine.privacy_filter as pf
    from kaine.security.latent_producer import LatentProducerRefused, check_latent_producer

    _enable_encryption(monkeypatch)
    if version is None:
        monkeypatch.delattr(pf, "LATENT_RULE_VERSION")
    else:
        monkeypatch.setattr(pf, "LATENT_RULE_VERSION", version)
    with pytest.raises(LatentProducerRefused) as info:
        check_latent_producer("probe", require_encryption=True)
    assert len(info.value.reasons) == 1
    assert "latent rule" in str(info.value)


def test_latent_producer_refused_when_the_key_does_not_round_trip():
    from kaine.security.latent_producer import LatentProducerRefused, check_latent_producer

    class _Broken:
        enabled = True

        def encrypt(self, data: bytes) -> bytes:
            return data

        def decrypt(self, data: bytes) -> bytes:
            raise ValueError("bad key")

    with pytest.raises(LatentProducerRefused) as info:
        check_latent_producer("probe", require_encryption=True, encryptor=_Broken())
    assert "round-trip" in str(info.value) and "ValueError" in str(info.value)


def test_latent_producer_names_every_failed_condition(monkeypatch):
    import kaine.privacy_filter as pf
    from kaine.security.latent_producer import LatentProducerRefused, check_latent_producer

    monkeypatch.delattr(pf, "LATENT_RULE_VERSION")
    with pytest.raises(LatentProducerRefused) as info:
        check_latent_producer("probe", require_encryption=False)
    assert len(info.value.reasons) == 3


class _Producer:
    name = "producer"
    produces_latent_derived = True


class _Plain:
    name = "plain"


def test_boot_refuses_a_declared_latent_producer(monkeypatch, caplog):
    from kaine.boot.errors import ConfigurationError
    from kaine.boot.registry import _check_latent_producers

    config = {"preservation": {"require_encryption": True}}
    # No producer: no check, whatever the encryption posture.
    _check_latent_producers(_Registry(_Plain()), {})
    with caplog.at_level("ERROR", logger="kaine.boot.registry"):
        with pytest.raises(ConfigurationError, match="state encryption"):
            _check_latent_producers(_Registry(_Plain(), _Producer()), config)
    assert any("producer" in r.getMessage() for r in caplog.records if r.levelname == "ERROR")
    _enable_encryption(monkeypatch)
    with pytest.raises(ConfigurationError, match="require_encryption"):
        _check_latent_producers(_Registry(_Producer()), {})
    _check_latent_producers(_Registry(_Producer()), config)


def test_shipped_modules_declare_no_latent_producer():
    from kaine.modules.base import BaseModule

    assert BaseModule.produces_latent_derived is False

    def subclasses(cls):
        for sub in cls.__subclasses__():
            yield sub
            yield from subclasses(sub)

    import kaine.modules  # noqa: F401  (imports every shipped module)

    assert [c.__name__ for c in subclasses(BaseModule) if c.produces_latent_derived] == []


@pytest.mark.asyncio
async def test_build_registry_runs_the_latent_producer_check(monkeypatch):
    import kaine.boot.registry as boot_registry
    from kaine.boot import build_registry
    from tests.systems._harness import SubsystemHarness

    seen = []
    monkeypatch.setattr(
        boot_registry, "_check_latent_producers", lambda registry, config: seen.append(registry)
    )
    async with SubsystemHarness() as h:
        registry = build_registry(
            h.bus, {"modules": {}, "security": {"state_encryption": {"enabled": False}}}
        )
    assert seen == [registry]
