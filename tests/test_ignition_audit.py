# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
"""Tests for the sleep-time ignition audit (change sleep-ignition-audit).

Pure-function fixtures use the REAL payload shapes: ``intent.speak`` /
``intent.act`` events with ``entry_id``; ``external_speech`` /
``vox.synthesized`` / ``praxis.action`` / ``realization_failed``
realizations; workspace.broadcast snapshots with a ``selected`` coalition
list of ``{entry_id, source, type, salience}`` members.
"""

import inspect

from kaine.modules.hypnos.ignition_audit import (
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
        "unrealizable_nous_intents",
        "realization_failed_count",
        "input_triggered_entry_ids",
        "drive_triggered_entry_ids",
        "self_initiated_entry_ids",
        "event_types",
        "saliences",
    }
)
FORBIDDEN_CONTENT_KEYS = frozenset(
    {"text", "transcript", "utterance", "latent", "embedding", "prompt"}
)


def _intent(entry_id=None, kind="intent.speak", stream="volition.out", salience=None):
    payload = {"kind": "speak" if kind == "intent.speak" else "act"}
    if entry_id is not None:
        payload["entry_id"] = entry_id
    if salience is not None:
        payload["salience"] = salience
    return {"stream": stream, "type": kind, "payload": payload}


def _realization(rtype="external_speech", entry_id=None, stream="lingua.external"):
    payload = {}
    if entry_id is not None:
        payload["entry_id"] = entry_id
    return {"stream": stream, "type": rtype, "payload": payload}


def _broadcast(members):
    return {"selected": list(members)}


def _member(entry_id, mtype, salience=0.5, source=None):
    m = {"entry_id": entry_id, "type": mtype, "salience": salience}
    if source is not None:
        m["source"] = source
    return m


# --- Scenario: realized speak classified self-initiated ---


def test_realized_speak_self_initiated():
    broadcasts = [
        _broadcast([_member("E1", "mnemos.trace", salience=0.9)])
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


def test_internal_speech_and_vox_realizations_count():
    broadcasts = [_broadcast([_member("E1", "mnemos.trace")])]
    intents = [_intent("E1"), _intent("E2")]
    realizations = [
        _realization("internal_speech", entry_id="E1", stream="lingua.internal"),
        _realization("vox.synthesized", entry_id="E2", stream="vox.out"),
    ]
    report = classify_realizations(broadcasts, intents, realizations)
    assert report.realized_total == 2
    assert report.self_initiated == 2
    assert set(report.event_types) == {"internal_speech", "vox.synthesized"}


# --- Scenario: input-triggered classification ---


def test_input_triggered_via_resolved_transcription_member():
    broadcasts = [_broadcast([_member("E1", "audition.transcription")])]
    intents = [_intent("E1")]
    realizations = [_realization("external_speech", entry_id="E1")]
    report = classify_realizations(broadcasts, intents, realizations)
    assert report.input_triggered == 1
    assert report.self_initiated == 0
    assert "E1" in report.input_triggered_entry_ids


def test_input_triggered_via_coalition_membership_mundus_chat():
    # The resolved member itself is not external, but mundus.chat was in the
    # winning coalition of the triggering broadcast.
    broadcasts = [
        _broadcast(
            [
                _member("E1", "mnemos.trace"),
                _member("M1", "mundus.chat"),
            ]
        )
    ]
    intents = [_intent("E1")]
    realizations = [_realization("external_speech", entry_id="E1")]
    report = classify_realizations(broadcasts, intents, realizations)
    assert report.input_triggered == 1
    assert report.drive_triggered == 0


def test_input_triggered_via_member_source_field():
    broadcasts = [_broadcast([_member("E1", None, source="mundus.chat")])]
    intents = [_intent("E1")]
    realizations = [_realization("vox.synthesized", entry_id="E1")]
    report = classify_realizations(broadcasts, intents, realizations)
    assert report.input_triggered == 1


# --- Scenario: drive-triggered classification ---


def test_drive_triggered_via_coalition_path():
    broadcasts = [
        _broadcast(
            [
                _member("E1", "mnemos.trace"),
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
        _realization("praxis.action", entry_id="A1", stream="praxis.out")
    ]
    report = classify_realizations(broadcasts, intents, realizations)
    assert report.drive_triggered == 1
    assert report.realized_total == 1


# --- Scenario: input-triggered count zero under base thesis ---


def test_base_thesis_input_triggered_zero():
    # Conversation surface off, transcription off, mundus off: no external
    # input types can appear in any coalition, so input_triggered == 0 —
    # the invariant holds every sleep.
    broadcasts = [
        _broadcast([_member("E1", "mnemos.trace")]),
        _broadcast([_member("E2", "thymos.affect")]),
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


def test_base_thesis_no_broadcasts_at_all():
    report = classify_realizations([], [_intent("E1")], [_realization(entry_id="E1")])
    assert report.input_triggered == 0
    assert report.self_initiated == 1


# --- Scenario: unrealizable nous intents counted separately ---


def test_unrealizable_nous_intents_counted_separately():
    broadcasts = [_broadcast([_member("A1", "mnemos.trace")])]
    intents = [
        _intent("N1", kind="intent.act", stream="nous.out"),
        _intent("N2", kind="intent.act", stream="nous.out"),
        _intent("A1", kind="intent.act", stream="volition.out"),
    ]
    realizations = [
        _realization("praxis.action", entry_id="A1", stream="praxis.out")
    ]
    report = classify_realizations(broadcasts, intents, realizations)
    assert report.unrealizable_nous_intents == 2
    # Not counted among executed actions.
    assert report.realized_total == 1
    assert report.drive_triggered + report.input_triggered + report.self_initiated == 1


def test_realization_failed_excluded():
    broadcasts = [_broadcast([_member("E1", "audition.transcription")])]
    intents = [_intent("E1")]
    realizations = [
        {"stream": "volition.out", "type": "realization_failed", "payload": {}},
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
            "stream": "volition.out",
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
            "stream": "lingua.external",
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
    assert EXTERNAL_INPUT_TYPES == frozenset({"audition.transcription", "mundus.chat"})
    assert DRIVE_TYPE == "thymos.drive"


# --- Scenario: audit runs every sleep and rides sleep.completed (wiring) ---


def test_pipeline_wires_audit_every_sleep():
    import kaine.modules.hypnos.module as hypnos_module

    src = inspect.getsource(hypnos_module)
    # The audit step exists and is invoked in the sleep pipeline.
    assert "_run_ignition_audit" in src
    assert '"hypnos.ignition_audit"' in src
    # Merged into the completed metadata so it rides hypnos.sleep.completed
    # into the sleep_snapshots JSONL.
    assert 'summary["ignition_audit"]' in src
    # Boundary (2.5): hypnos never imports kaine.evaluation.
    assert "import kaine.evaluation" not in src
    assert "from kaine.evaluation" not in src


def test_research_event_taxonomy_registered():
    from kaine.evaluation.observers.research_event_observer import _TAXONOMY

    assert "hypnos.ignition_audit" in _TAXONOMY
    allowed = _TAXONOMY["hypnos.ignition_audit"]
    # Numeric/categorical only — no content fields in the research log.
    assert "text" not in allowed
    assert "transcript" not in allowed
    assert "latent" not in allowed
    assert "sleep_index" in allowed
    assert "unrealizable_nous_intents" in allowed


def test_bus_workspace_read_path_exists():
    # workspace.broadcast must be read via the decode-safe workspace path,
    # never bus.range (which cannot decode broadcast entries).
    from kaine.bus.client import AsyncBus

    assert hasattr(AsyncBus, "read_workspace_entries")
    assert hasattr(AsyncBus, "subscribe_workspace")


def test_entry_in_multiple_coalitions_input_wins():
    """F3 — the same entry can win multiple broadcasts; classification scans
    EVERY coalition containing it, and any external-input involvement makes it
    input-triggered (conservative for the base-thesis zero-input invariant)."""
    broadcasts = [
        {"selected": [
            {"entry_id": "E1", "source": "thymos", "type": "thymos.drive", "salience": 0.7},
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
