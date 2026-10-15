# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
"""Tests for the sleep-time ignition audit (change sleep-ignition-audit).

Pure-function fixtures use the REAL payload shapes: ``intent.speak`` /
``intent.act`` events with ``entry_id``; ``external_speech`` /
``vocal.synthesized`` / ``effectors.action`` / ``realization_failed``
realizations; workspace.broadcast snapshots with a ``selected`` coalition
list of ``{entry_id, source, type, salience}`` members.
"""

import inspect

from kaine.modules.sleep.ignition_audit import (
    DRIVE_TYPE,
    EXTERNAL_INPUT_TYPES,
    classify_realizations,
)

# The full content-free allowlist for the audit payload (counts, entry_ids,
# event types, salience values, sleep_index — nothing else).
PAYLOAD_ALLOWLIST = frozenset(
    {
        "sleep_index",
        "realized_total",
        "input_triggered",
        "drive_triggered",
        "self_initiated",
        "planning_initiated",
        "unrealizable_planning_intents",
        "realization_failed_count",
        "planning_proposals_realized",
        "planning_proposals_declined",
        "planning_proposals_forwarded",
        "input_triggered_entry_ids",
        "drive_triggered_entry_ids",
        "self_initiated_entry_ids",
        "planning_initiated_entry_ids",
        "event_types",
        "saliences",
    }
)
FORBIDDEN_CONTENT_KEYS = frozenset(
    {"text", "transcript", "utterance", "latent", "embedding", "prompt"}
)


def test_vocal_synthesized_origin_planning_is_planning_initiated():
    """The vocal module copies the language module's origin, so a planning module utterance is attributed by it."""
    intents = [
        {"stream": "action_selection.out", "type": "intent.speak", "payload": {"kind": "speak", "entry_id": "e1"}},
    ]
    realizations = [
        {
            "stream": "vocal.out",
            "type": "vocal.synthesized",
            "payload": {"success": True, "entry_id": "e1", "origin": "planning"},
        },
    ]
    report = classify_realizations([], intents, realizations)
    assert report.realized_total == 1
    assert report.planning_initiated == 1
    assert report.input_triggered == 0
    assert report.self_initiated == 0


def _intent(entry_id=None, kind="intent.speak", stream="action_selection.out", salience=None):
    payload = {"kind": "speak" if kind == "intent.speak" else "act"}
    if entry_id is not None:
        payload["entry_id"] = entry_id
    if salience is not None:
        payload["salience"] = salience
    return {"stream": stream, "type": kind, "payload": payload}


def _realization(rtype="external_speech", entry_id=None, stream="language.external"):
    payload = {}
    if entry_id is not None:
        payload["entry_id"] = entry_id
    return {"stream": stream, "type": rtype, "payload": payload}


def test_realization_origin_uses_own_payload_not_last_intent():
    """Precise attribution: speech is planning-initiated from its own origin."""
    intents = [
        {"stream": "action_selection.out", "type": "intent.think", "payload": {"kind": "think", "entry_id": "e1", "origin": "planning"}},
        {"stream": "action_selection.out", "type": "intent.think", "payload": {"kind": "think", "entry_id": "e2"}},
        {"stream": "action_selection.out", "type": "intent.think", "payload": {"kind": "think", "entry_id": "e3", "origin": "planning"}},
    ]
    realizations = [
        {"stream": "language.internal", "type": "internal_speech", "payload": {"entry_id": "e1", "origin": "planning"}},
        {"stream": "language.internal", "type": "internal_speech", "payload": {"entry_id": "e2"}},
        {"stream": "language.internal", "type": "internal_speech", "payload": {"entry_id": "e3", "origin": "planning"}},
    ]
    report = classify_realizations([], intents, realizations)
    assert report.planning_initiated == 2
    assert report.self_initiated == 1
    assert report.realized_total == 3


def _broadcast(members):
    return {"selected": list(members)}


def _vocal_synthesized(success=True, entry_id=None):
    payload = {"success": success}
    if entry_id is not None:
        payload["entry_id"] = entry_id
    return {"stream": "vocal.synthesized", "type": "vocal.synthesized", "payload": payload}


def test_vocal_synthesized_failure_counts_as_realization_failed():
    intents = [_intent(entry_id="e1")]
    realizations = [_vocal_synthesized(success=False, entry_id="e1")]
    report = classify_realizations([], intents, realizations)
    assert report.realization_failed_count == 1
    assert report.realized_total == 0


def test_vocal_synthesized_success_still_realized():
    intents = [_intent(entry_id="e1")]
    realizations = [_vocal_synthesized(success=True, entry_id="e1")]
    report = classify_realizations([], intents, realizations)
    assert report.realized_total == 1
    assert report.realization_failed_count == 0
    assert report.self_initiated == 1


def _member(entry_id, mtype, salience=0.5, source=None):
    m = {"entry_id": entry_id, "type": mtype, "salience": salience}
    if source is not None:
        m["source"] = source
    return m


# --- Scenario: realized speak classified self-initiated ---


def test_realized_speak_self_initiated():
    broadcasts = [
        _broadcast([_member("E1", "episodic_memory.trace", salience=0.9)])
    ]
    intents = [_intent("E1", salience=0.9)]
    realizations = [_realization("external_speech", entry_id="E1")]
    report = classify_realizations(broadcasts, intents, realizations, sleep_index=1)
    assert report.realized_total == 1
    assert report.self_initiated == 1
    assert report.input_triggered == 0
    assert report.drive_triggered == 0
    assert "E1" in report.self_initiated_entry_ids
    assert report.event_types == ["external_speech"]
    assert report.saliences == [0.9]


def test_internal_speech_and_vocal_realizations_count():
    broadcasts = [_broadcast([_member("E1", "episodic_memory.trace")])]
    intents = [_intent("E1"), _intent("E2")]
    realizations = [
        _realization("internal_speech", entry_id="E1", stream="language.internal"),
        _realization("vocal.synthesized", entry_id="E2", stream="vocal.out"),
    ]
    report = classify_realizations(broadcasts, intents, realizations)
    assert report.realized_total == 2
    assert report.self_initiated == 2
    assert set(report.event_types) == {"internal_speech", "vocal.synthesized"}


# --- Scenario: input-triggered classification ---


def test_input_triggered_via_resolved_transcription_member():
    broadcasts = [_broadcast([_member("E1", "audition.transcription")])]
    intents = [_intent("E1")]
    realizations = [_realization("external_speech", entry_id="E1")]
    report = classify_realizations(broadcasts, intents, realizations)
    assert report.input_triggered == 1
    assert report.self_initiated == 0
    assert "E1" in report.input_triggered_entry_ids


def test_input_triggered_via_coalition_membership_embodiment_chat():
    # The resolved member itself is not external, but embodiment.chat was in the
    # winning coalition of the triggering broadcast.
    broadcasts = [
        _broadcast(
            [
                _member("E1", "episodic_memory.trace"),
                _member("M1", "embodiment.chat"),
            ]
        )
    ]
    intents = [_intent("E1")]
    realizations = [_realization("external_speech", entry_id="E1")]
    report = classify_realizations(broadcasts, intents, realizations)
    assert report.input_triggered == 1
    assert report.drive_triggered == 0


def test_input_triggered_via_member_source_field():
    broadcasts = [_broadcast([_member("E1", None, source="embodiment.chat")])]
    intents = [_intent("E1")]
    realizations = [_realization("vocal.synthesized", entry_id="E1")]
    report = classify_realizations(broadcasts, intents, realizations)
    assert report.input_triggered == 1


# --- Scenario: drive-triggered classification ---


def test_drive_triggered_via_coalition_path():
    broadcasts = [
        _broadcast(
            [
                _member("E1", "episodic_memory.trace"),
                _member("D1", DRIVE_TYPE),
            ]
        )
    ]
    intents = [_intent("E1")]
    realizations = [_realization("external_speech", entry_id="E1")]
    report = classify_realizations(broadcasts, intents, realizations)
    assert report.drive_triggered == 1
    assert report.self_initiated == 0
    assert report.input_triggered == 0
    assert "E1" in report.drive_triggered_entry_ids


def test_drive_triggered_realized_action():
    broadcasts = [_broadcast([_member("A1", DRIVE_TYPE)])]
    intents = [_intent("A1", kind="intent.act")]
    realizations = [
        _realization("effectors.action", entry_id="A1", stream="effectors.out")
    ]
    report = classify_realizations(broadcasts, intents, realizations)
    assert report.drive_triggered == 1
    assert report.realized_total == 1


# --- Scenario: input-triggered count zero under first configuration ---


def test_first_configuration_input_triggered_zero():
    # Conversation surface off, transcription off, embodiment module off: no external
    # input types can appear in any coalition, so input_triggered == 0 —
    # the invariant holds every sleep.
    broadcasts = [
        _broadcast([_member("E1", "episodic_memory.trace")]),
        _broadcast([_member("E2", "affect.affect")]),
    ]
    intents = [_intent("E1"), _intent("E2")]
    realizations = [
        _realization("external_speech", entry_id="E1"),
        _realization("internal_speech", entry_id="E2"),
    ]
    report = classify_realizations(broadcasts, intents, realizations)
    assert report.input_triggered == 0
    assert report.realized_total == 2
    assert report.self_initiated == 2


def test_first_configuration_no_broadcasts_at_all():
    report = classify_realizations([], [_intent("E1")], [_realization(entry_id="E1")])
    assert report.input_triggered == 0
    assert report.self_initiated == 1


# --- Scenario: Planning-originated intents ---


def test_planning_origin_think_realized_as_internal_speech_is_planning_initiated():
    # Even with a drive in the coalition, origin "planning" wins first.
    broadcasts = [_broadcast([_member("D1", "affect.drive"), _member("E1", "episodic_memory.trace")])]
    intents = [
        _intent("E1", kind="intent.think", stream="action_selection.out", salience=0.7),
    ]
    intents[0]["payload"]["origin"] = "planning"
    realizations = [_realization("internal_speech", entry_id="E1")]
    report = classify_realizations(broadcasts, intents, realizations)
    assert report.planning_initiated == 1
    assert report.drive_triggered == 0
    assert report.self_initiated == 0


def test_planning_origin_requested_sleep_is_planning_initiated_rest():
    broadcasts = []
    intents = [
        {"stream": "action_selection.out", "type": "intent.rest", "payload": {"origin": "planning", "entry_id": "R1", "salience": 0.6}},
    ]
    realizations = [
        {"stream": "sleep.out", "type": "sleep.sleep.started", "payload": {"trigger": "requested", "entry_id": "R1"}},
    ]
    report = classify_realizations(broadcasts, intents, realizations)
    assert report.realized_total == 1
    assert report.planning_initiated == 1
    assert "R1" in report.planning_initiated_entry_ids


def test_proposal_outcome_counts():
    outcomes = [
        {"stream": "action_selection_feedback.out", "type": "action_selection.proposal_outcome", "payload": {"proposal_id": "p1", "realized": True}},
        {"stream": "action_selection_feedback.out", "type": "action_selection.proposal_outcome", "payload": {"proposal_id": "p2", "realized": False}},
    ]
    report = classify_realizations([], [], [], proposal_outcomes=outcomes)
    assert report.planning_proposals_realized == 1
    assert report.planning_proposals_declined == 1


def test_proposal_outcome_counts_includes_forwarded():
    outcomes = [
        {"stream": "action_selection_feedback.out", "type": "action_selection.proposal_outcome", "payload": {"proposal_id": "p1", "realized": True}},
        {"stream": "action_selection_feedback.out", "type": "action_selection.proposal_outcome", "payload": {"proposal_id": "p2", "realized": False, "reason": "refractory"}},
        {"stream": "action_selection_feedback.out", "type": "action_selection.proposal_outcome", "payload": {"proposal_id": "p3", "realized": False, "reason": "forwarded"}},
    ]
    report = classify_realizations([], [], [], proposal_outcomes=outcomes)
    assert report.planning_proposals_realized == 1
    assert report.planning_proposals_declined == 1
    assert report.planning_proposals_forwarded == 1


def test_any_intent_on_planning_out_is_unrealizable():
    for kind in ("intent.act", "intent.speak", "intent.think", "intent.rest"):
        report = classify_realizations(
            [],
            [{"stream": "planning.out", "type": kind, "payload": {"entry_id": "x"}}],
            [],
        )
        assert report.unrealizable_planning_intents == 1, kind


# --- Scenario: unrealizable planning intents counted separately ---


def test_unrealizable_planning_intents_counted_separately():
    broadcasts = [_broadcast([_member("A1", "episodic_memory.trace")])]
    intents = [
        _intent("N1", kind="intent.act", stream="planning.out"),
        _intent("N2", kind="intent.act", stream="planning.out"),
        _intent("A1", kind="intent.act", stream="action_selection.out"),
    ]
    realizations = [
        _realization("effectors.action", entry_id="A1", stream="effectors.out")
    ]
    report = classify_realizations(broadcasts, intents, realizations)
    assert report.unrealizable_planning_intents == 2
    # Not counted among executed actions.
    assert report.realized_total == 1
    assert report.drive_triggered + report.input_triggered + report.self_initiated == 1


def test_realization_failed_excluded():
    broadcasts = [_broadcast([_member("E1", "audition.transcription")])]
    intents = [_intent("E1")]
    realizations = [
        {"stream": "action_selection.out", "type": "realization_failed", "payload": {}},
        _realization("external_speech", entry_id="E1"),
    ]
    report = classify_realizations(broadcasts, intents, realizations)
    assert report.realization_failed_count == 1
    assert report.realized_total == 1
    assert report.input_triggered == 1


# --- Scenario: audit content-free ---


def test_payload_content_free_allowlist():
    broadcasts = [
        _broadcast(
            [
                {"entry_id": "E1", "type": "audition.transcription",
                 "salience": 0.7, "text": "hello operator",
                 "transcript": "hello operator", "latent": [0.1, 0.2]},
            ]
        )
    ]
    intents = [
        {
            "stream": "action_selection.out",
            "type": "intent.speak",
            "payload": {
                "kind": "speak",
                "entry_id": "E1",
                "salience": 0.7,
                "text": "draft utterance",
                "latent": [0.3],
            },
        }
    ]
    realizations = [
        {
            "stream": "language.external",
            "type": "external_speech",
            "payload": {"entry_id": "E1", "transcript": "spoken words"},
        }
    ]
    payload = classify_realizations(
        broadcasts, intents, realizations, sleep_index=5
    ).as_payload()
    assert set(payload.keys()) <= PAYLOAD_ALLOWLIST
    for key in FORBIDDEN_CONTENT_KEYS:
        assert key not in payload
    # No content value leaks through any allowlisted field either.
    assert payload["input_triggered"] == 1
    assert payload["input_triggered_entry_ids"] == ["E1"]
    assert payload["event_types"] == ["external_speech"]
    assert payload["saliences"] == [0.7]
    assert payload["sleep_index"] == 5
    joined = repr(payload)
    assert "hello operator" not in joined
    assert "spoken words" not in joined
    assert "draft utterance" not in joined


def test_payload_keys_exactly_allowlist_for_minimal_report():
    payload = classify_realizations([], [], [], sleep_index=0).as_payload()
    assert set(payload.keys()) == PAYLOAD_ALLOWLIST


def test_sleep_index_ordering():
    for i in (1, 2, 3):
        payload = classify_realizations([], [], [], sleep_index=i).as_payload()
        assert payload["sleep_index"] == i


def test_constants():
    assert EXTERNAL_INPUT_TYPES == frozenset({"audition.transcription", "embodiment.chat"})
    assert DRIVE_TYPE == "affect.drive"


# --- Scenario: audit runs every sleep and rides sleep.completed (wiring) ---


def test_pipeline_wires_audit_every_sleep():
    import kaine.modules.sleep.module as sleep_module

    src = inspect.getsource(sleep_module)
    # The audit step exists and is invoked in the sleep pipeline.
    assert "_run_ignition_audit" in src
    assert '"sleep.ignition_audit"' in src
    # Merged into the completed metadata so it rides sleep.sleep.completed
    # into the sleep_snapshots JSONL.
    assert 'summary["ignition_audit"]' in src
    # Boundary (2.5): the sleep module never imports kaine.evaluation.
    assert "import kaine.evaluation" not in src
    assert "from kaine.evaluation" not in src


def test_research_event_taxonomy_registered():
    from kaine.evaluation.observers.research_event_observer import _TAXONOMY

    assert "sleep.ignition_audit" in _TAXONOMY
    allowed = _TAXONOMY["sleep.ignition_audit"]
    # Numeric/categorical only — no content fields in the research log.
    assert "text" not in allowed
    assert "transcript" not in allowed
    assert "latent" not in allowed
    assert "sleep_index" in allowed
    assert "unrealizable_planning_intents" in allowed
    # Every numeric count the audit publishes reaches the research log; only
    # the entry_id lists, event types and saliences stay in the sleep snapshot.
    counts = {
        key
        for key in PAYLOAD_ALLOWLIST
        if key not in {"event_types", "saliences"} and not key.endswith("_entry_ids")
    }
    assert counts <= allowed
    assert allowed - {"audit_error"} <= PAYLOAD_ALLOWLIST


def test_bus_workspace_read_path_exists():
    # workspace.broadcast must be read via the decode-safe workspace path,
    # never bus.range (which cannot decode broadcast entries).
    from kaine.bus.client import AsyncBus

    assert hasattr(AsyncBus, "read_workspace_entries")
    assert hasattr(AsyncBus, "subscribe_workspace")


def test_entry_in_multiple_coalitions_input_wins():
    """F3 — the same entry can win multiple broadcasts; classification scans
    EVERY coalition containing it, and any external-input involvement makes it
    input-triggered (conservative for the first-configuration zero-input invariant)."""
    broadcasts = [
        {"selected": [
            {"entry_id": "E1", "source": "affect", "type": "affect.drive", "salience": 0.7},
        ]},
        {"selected": [
            {"entry_id": "E1", "source": "audition", "type": "audition.transcription", "salience": 0.9},
        ]},
    ]
    intents = [_intent(entry_id="E1")]
    realizations = [_realization("external_speech", entry_id="E1")]
    report = classify_realizations(broadcasts, intents, realizations, sleep_index=3)
    assert report.input_triggered == 1
    assert report.drive_triggered == 0
    assert report.self_initiated == 0
