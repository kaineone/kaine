# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from datetime import datetime, timezone


from kaine.bus.schema import Event
from kaine.cycle.types import WorkspaceSnapshot
from kaine.faithful import FaithfulRenderer


def _event(source="soma", type_="soma.report", payload=None) -> Event:
    return Event(
        source=source,
        type=type_,
        payload=payload or {"wellness": 0.5, "alerts": []},
        salience=0.4,
        timestamp=datetime.now(timezone.utc),
    )


def test_renderer_deterministic_for_same_event():
    r = FaithfulRenderer()
    e = _event(payload={"wellness": 0.9, "alerts": []})
    a = r.render_event(e)
    b = r.render_event(e)
    assert a == b


def test_unknown_event_uses_fallback():
    r = FaithfulRenderer()
    e = _event(source="brandnew", type_="x.y", payload={"a": 1, "b": "z"})
    out = r.render_event(e)
    assert "brandnew" in out
    assert "x.y" in out
    assert "a=1" in out


def test_empty_snapshot_returns_configured_text():
    r = FaithfulRenderer()
    snap = WorkspaceSnapshot(tick_index=0, selected_events=[], inhibited=False)
    assert r.render_snapshot(snap) == "(no events selected)"


def test_snapshot_renders_each_event_on_its_own_line():
    r = FaithfulRenderer()
    snap = WorkspaceSnapshot(
        tick_index=0,
        selected_events=[
            ("e1", _event(source="soma", payload={"wellness": 0.5, "alerts": []})),
            ("e2", _event(source="chronos", type_="chronos.report",
                          payload={"anomaly_score": 0.1, "habituation_score": 0.2,
                                   "rumination_detected": False})),
        ],
    )
    text = r.render_snapshot(snap)
    lines = text.splitlines()
    assert len(lines) == 2
    assert all(line.startswith("- ") for line in lines)


def test_snapshot_preserves_event_order():
    r = FaithfulRenderer()
    e1 = _event(payload={"wellness": 0.9, "alerts": []})
    e2 = _event(payload={"wellness": 0.1, "alerts": ["cpu_percent"]})
    snap = WorkspaceSnapshot(
        tick_index=0,
        selected_events=[("a", e1), ("b", e2)],
    )
    text = r.render_snapshot(snap)
    lines = text.splitlines()
    assert "0.9" in lines[0]
    assert "0.1" in lines[1]


def test_custom_empty_snapshot_text():
    r = FaithfulRenderer(empty_snapshot_text="silence")
    snap = WorkspaceSnapshot(tick_index=0, selected_events=[], inhibited=False)
    assert r.render_snapshot(snap) == "silence"


def test_custom_line_prefix():
    r = FaithfulRenderer(line_prefix="* ")
    snap = WorkspaceSnapshot(
        tick_index=0,
        selected_events=[("e1", _event())],
    )
    text = r.render_snapshot(snap)
    assert text.startswith("* ")


def test_renderer_does_not_mutate_payload():
    r = FaithfulRenderer()
    payload = {"wellness": 0.5, "alerts": ["cpu_percent"]}
    e = _event(payload=payload)
    _ = r.render_event(e)
    # Payload dict unchanged
    assert payload == {"wellness": 0.5, "alerts": ["cpu_percent"]}


# ---- render_snapshot_bounded ------------------------------------------------

def _bounded_snap(triples):
    """triples: (entry_id, Event, salience)."""
    selected = [(eid, ev) for eid, ev, _ in triples]
    scores = {eid: s for eid, _, s in triples}
    return WorkspaceSnapshot(tick_index=0, selected_events=selected, salience_scores=scores)


def test_bounded_empty_snapshot_returns_empty_text():
    r = FaithfulRenderer()
    snap = WorkspaceSnapshot(tick_index=0, selected_events=[])
    assert r.render_snapshot_bounded(snap) == r._empty_snapshot_text


def test_bounded_max_events_zero_returns_empty_text():
    r = FaithfulRenderer()
    snap = _bounded_snap([("e1", _event(payload={"wellness": 0.9, "alerts": []}), 0.9)])
    assert r.render_snapshot_bounded(snap, max_events=0, char_budget=9999) == r._empty_snapshot_text


def test_bounded_budget_smaller_than_first_line_still_emits_one():
    r = FaithfulRenderer()
    snap = _bounded_snap([("e1", _event(payload={"wellness": 0.9, "alerts": []}), 0.9)])
    out = r.render_snapshot_bounded(snap, max_events=8, char_budget=1)
    assert len(out.splitlines()) == 1  # at-least-one policy


def test_bounded_all_equal_salience_preserves_coalition_order():
    r = FaithfulRenderer()
    triples = [
        ("a", _event(payload={"wellness": 0.1, "alerts": []}), 0.5),
        ("b", _event(payload={"wellness": 0.9, "alerts": []}), 0.5),
        ("c", _event(payload={"wellness": 0.5, "alerts": []}), 0.5),
    ]
    lines = r.render_snapshot_bounded(_bounded_snap(triples), max_events=3, char_budget=9999).splitlines()
    assert "0.1" in lines[0] and "0.9" in lines[1] and "0.5" in lines[2]


def test_bounded_missing_salience_scores_still_renders():
    r = FaithfulRenderer()
    snap = WorkspaceSnapshot(
        tick_index=0,
        selected_events=[("e1", _event()), ("e2", _event())],
        salience_scores={},
    )
    out = r.render_snapshot_bounded(snap, max_events=8, char_budget=9999)
    assert out.count("- ") == 2
