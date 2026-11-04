# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from datetime import datetime, timezone

from kaine.bus.schema import Event
from kaine.cycle.types import WorkspaceSnapshot
from kaine.workspace.feedback import (
    FEEDBACK_KEY,
    REPORT_TYPES,
    FeedbackController,
    WorkspaceFeedbackSettings,
)


def _report(source, *, ratio=None, disagreement=None, gain=1.0, eid=None, salience=0.6):
    """Build a processor‑report event."""
    payload = {
        FEEDBACK_KEY: {
            "error_ratio": ratio,
            "disagreement": disagreement,
            "gain": gain,
        }
    }
    return (
        eid or f"{source}:1",
        Event(
            source=source,
            type=REPORT_TYPES[source],
            payload=payload,
            salience=salience,
            timestamp=datetime.now(timezone.utc),
        ),
    )


def _snapshot(events, *, scores=None, threshold=0.35, inhibited=False):
    """Create a WorkspaceSnapshot from a list of (eid, Event) tuples."""
    scores = dict(scores) if scores else {}
    for eid, _ in events:
        scores.setdefault(eid, 0.6)
    return WorkspaceSnapshot(
        tick_index=0,
        selected_events=events,
        inhibited=inhibited,
        salience_scores=scores,
        metadata={"access_threshold": threshold},
    )


def _conflict_rate(controller, event_factory, runs: int = 200) -> float:
    """Run ``runs`` broadcasts and return the fraction that contain a conflict."""
    conflict_hits = 0
    for i in range(runs):
        events = event_factory(i)
        snapshot = _snapshot(events)
        metadata = controller.on_broadcast(snapshot)
        episodes = metadata.get("episodes", [])
        if any(ep.get("kind") == "conflict" for ep in episodes):
            conflict_hits += 1
    return conflict_hits / runs


def test_synthetic_conflict_flags_inconsistent_inputs():
    """
    The ``full`` arm must flag a conflict in the overwhelming majority of
    broadcasts when at least one processor supplies high disagreement and error
    ratio (≥ 2.0 by default).  We assert a conflict rate of ≥ 0.95.
    """
    settings = WorkspaceFeedbackSettings(arm="full", refractory_s=0.0)
    controller = FeedbackController(settings)

    # Grab any two distinct processor sources.
    processors = list(REPORT_TYPES.keys())
    assert len(processors) >= 2, "Need at least two processor sources for the test"
    src_a, src_b = processors[:2]

    def event_factory(idx: int):
        # src_a deliberately conflicts; src_b stays benign.
        return [
            _report(src_a, ratio=3.0, disagreement=5.0, eid=f"{src_a}:{idx}"),
            _report(src_b, ratio=0.5, disagreement=0.1, eid=f"{src_b}:{idx}"),
        ]

    rate = _conflict_rate(controller, event_factory, runs=200)
    assert rate >= 0.95, f"Conflict rate too low: {rate:.3%}"


def test_synthetic_conflict_clean_at_low_disagreement():
    """
    When all processors report low disagreement and error ratio, the ``full``
    arm should almost never flag a conflict.  We assert a conflict rate of
    ≤ 0.05.
    """
    settings = WorkspaceFeedbackSettings(arm="full", refractory_s=0.0)
    controller = FeedbackController(settings)

    processors = list(REPORT_TYPES.keys())
    assert len(processors) >= 2, "Need at least two processor sources for the test"
    src_a, src_b = processors[:2]

    def event_factory(idx: int):
        # Both sources stay well below the conflict thresholds.
        return [
            _report(src_a, ratio=0.5, disagreement=0.1, eid=f"{src_a}:{idx}"),
            _report(src_b, ratio=0.5, disagreement=0.1, eid=f"{src_b}:{idx}"),
        ]

    rate = _conflict_rate(controller, event_factory, runs=200)
    assert rate <= 0.05, f"Unexpected conflict rate: {rate:.3%}"
