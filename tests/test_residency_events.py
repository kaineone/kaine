# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from kaine.residency.events import (
    clear_residency_events,
    record_downgrade,
    record_evict,
    record_load_end,
    record_load_start,
    record_queue_drop,
    record_unload,
    residency_events,
    residency_events_snapshot,
)


def test_record_load_start():
    clear_residency_events()
    e = record_load_start("stt")
    assert e.kind == "load_start"
    assert e.name == "stt"
    assert e.ts > 0
    assert len(residency_events()) == 1


def test_record_load_end():
    clear_residency_events()
    e = record_load_end("stt", 1.5)
    assert e.kind == "load_end"
    assert e.duration_seconds == 1.5


def test_record_unload():
    clear_residency_events()
    e = record_unload("stt", "ttl_expired")
    assert e.kind == "unload"
    assert e.reason == "ttl_expired"


def test_record_evict():
    clear_residency_events()
    e = record_evict("stt", "memory_pressure", 400_000_000)
    assert e.kind == "evict"
    assert e.freed_bytes == 400_000_000


def test_record_downgrade():
    clear_residency_events()
    e = record_downgrade("stt", "insufficient_memory", "moonshine-base", "moonshine-tiny")
    assert e.kind == "downgrade"
    assert e.from_rung == "moonshine-base"
    assert e.to_rung == "moonshine-tiny"


def test_record_queue_drop():
    clear_residency_events()
    e = record_queue_drop("consolidation", "queue_full")
    assert e.kind == "queue_drop"
    assert e.reason == "queue_full"


def test_events_accumulate():
    clear_residency_events()
    record_load_start("stt")
    record_load_end("stt", 0.5)
    record_unload("stt", "ttl")
    assert len(residency_events()) == 3


def test_snapshot_returns_dicts():
    clear_residency_events()
    record_load_start("stt")
    snap = residency_events_snapshot()
    assert len(snap) == 1
    assert snap[0]["kind"] == "load_start"
    assert snap[0]["name"] == "stt"
    assert "ts" in snap[0]


def test_as_dict_omits_none_fields():
    clear_residency_events()
    e = record_load_start("stt")
    d = e.as_dict()
    assert "duration_seconds" not in d
    assert "freed_bytes" not in d
    assert "from_rung" not in d


def test_as_dict_includes_set_fields():
    clear_residency_events()
    e = record_evict("stt", "pressure", 500)
    d = e.as_dict()
    assert d["freed_bytes"] == 500
    assert d["reason"] == "pressure"


def test_clear_resets():
    clear_residency_events()
    record_load_start("stt")
    clear_residency_events()
    assert residency_events() == []


def test_event_is_frozen():
    clear_residency_events()
    e = record_load_start("stt")
    import pytest

    with pytest.raises(AttributeError):
        e.name = "tts"
