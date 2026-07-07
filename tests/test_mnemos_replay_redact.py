# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Tests for mnemos.replay redact_content option.

Scenarios verified:
- redact_content=True  → observer_payload contains memory IDs and metadata but
                         no raw trace text.
- redact_content=False → observer_payload contains full text content.
"""
from __future__ import annotations

import time


from kaine.modules.mnemos.replay import (
    ReplayEngine,
    ReplayEntry,
    build_replay_events,
)


def _entry(point_id: str, *, text: str = "some trace content", intensity: float = 0.5) -> ReplayEntry:
    return ReplayEntry(
        point_id=point_id,
        text=text,
        affect_intensity=intensity,
        timestamp=time.time(),
        payload={},
        affect={"intensity": intensity},
    )


class TestRedactContent:
    """Scenario: observer payload respects redact_content flag."""

    def test_redact_true_observer_payload_has_no_text(self):
        """When redact_content=True, observer_payload must not contain 'text'."""
        engine = ReplayEngine(redact_content=True)
        engine.open_window()
        candidates = [_entry("mem1", text="private memory content")]
        events = engine.replay(candidates)
        assert len(events) == 1
        observer = events[0].observer_payload
        assert "text" not in observer
        assert "memory_id" in observer

    def test_redact_false_observer_payload_has_text(self):
        """When redact_content=False, observer_payload must contain full text."""
        engine = ReplayEngine(redact_content=False)
        engine.open_window()
        candidates = [_entry("mem2", text="visible memory content")]
        events = engine.replay(candidates)
        assert len(events) == 1
        observer = events[0].observer_payload
        assert "text" in observer
        assert observer["text"] == "visible memory content"

    def test_redact_true_loop_payload_always_has_text(self):
        """Redaction never strips text from the loop-facing payload."""
        engine = ReplayEngine(redact_content=True)
        engine.open_window()
        candidates = [_entry("mem3", text="loop content")]
        events = engine.replay(candidates)
        assert len(events) == 1
        # Loop payload must have the text for cognitive re-processing.
        assert events[0].loop_payload["text"] == "loop content"

    def test_redact_true_observer_payload_has_memory_id(self):
        """Redacted payload still carries memory_id so the observer can index it."""
        engine = ReplayEngine(redact_content=True)
        engine.open_window()
        candidates = [_entry("mem42", text="secret")]
        events = engine.replay(candidates)
        assert events[0].observer_payload["memory_id"] == "mem42"

    def test_redact_true_observer_payload_has_affect_metadata(self):
        """Redacted payload still carries affect intensity and timestamps."""
        engine = ReplayEngine(redact_content=True)
        engine.open_window()
        candidates = [_entry("mem5", intensity=0.8, text="private")]
        events = engine.replay(candidates)
        obs = events[0].observer_payload
        assert "affect_intensity" in obs
        assert "replayed_at" in obs
        assert "source_timestamp" in obs

    def test_redact_false_observer_and_loop_payloads_equal(self):
        """Without redaction the observer and loop payloads are identical."""
        engine = ReplayEngine(redact_content=False)
        engine.open_window()
        candidates = [_entry("mem6", text="open content")]
        events = engine.replay(candidates)
        assert events[0].observer_payload == events[0].loop_payload

    def test_build_replay_events_redact_true(self):
        """build_replay_events with redact_content=True strips text from observer."""
        selected = [_entry("bx", text="build test")]
        events = build_replay_events(selected, redact_content=True)
        assert len(events) == 1
        assert "text" not in events[0].observer_payload
        assert events[0].loop_payload["text"] == "build test"

    def test_build_replay_events_redact_false(self):
        """build_replay_events with redact_content=False preserves text in observer."""
        selected = [_entry("by", text="build test 2")]
        events = build_replay_events(selected, redact_content=False)
        assert len(events) == 1
        assert events[0].observer_payload["text"] == "build test 2"

    def test_multiple_entries_all_redacted(self):
        """All entries are redacted when redact_content=True."""
        engine = ReplayEngine(selection_top_k=10, redact_content=True)
        engine.open_window()
        candidates = [_entry(f"m{i}", text=f"content {i}") for i in range(5)]
        events = engine.replay(candidates)
        for ev in events:
            assert "text" not in ev.observer_payload
            assert "text" in ev.loop_payload
