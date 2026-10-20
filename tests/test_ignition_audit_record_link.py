# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>
"""Tests for record_id linking in the sleep-time ignition audit.

These tests exercise the ``record_links`` mapping that joins language module
realization payloads (which carry ``record_id``) to the ``entry_id`` of the
intent they realized. Only a requested sleep keeps the last-of-kind fallback;
speak, think, and act realizations are never attributed to another intent
when the link is missing.
"""

from kaine.modules.sleep.ignition_audit import DRIVE_TYPE, classify_realizations


def test_record_links_classify_speak_drive_and_self():
    intents = [
        {"stream": "action_selection.out", "type": "intent.speak", "payload": {"kind": "speak", "entry_id": "E1"}},
        {"stream": "action_selection.out", "type": "intent.speak", "payload": {"kind": "speak", "entry_id": "E2"}},
    ]
    broadcasts = [
        {"selected": [{"entry_id": "E1", "type": DRIVE_TYPE, "salience": 0.9}]},
        {"selected": [{"entry_id": "E2", "type": "self", "salience": 0.5}]},
    ]
    realizations = [
        {"stream": "language.external", "type": "external_speech", "payload": {"record_id": "R1"}},
        {"stream": "language.external", "type": "external_speech", "payload": {"record_id": "R2"}},
    ]
    report = classify_realizations(
        broadcasts,
        intents,
        realizations,
        record_links={"R1": "E1", "R2": "E2"},
    )
    assert report.realized_total == 2
    assert report.drive_triggered == 1
    assert report.self_initiated == 1
    assert report.drive_triggered_entry_ids == ["E1"]
    assert report.self_initiated_entry_ids == ["E2"]


def test_record_links_reverse_order_same_counts():
    intents = [
        {"stream": "action_selection.out", "type": "intent.speak", "payload": {"kind": "speak", "entry_id": "E1"}},
        {"stream": "action_selection.out", "type": "intent.speak", "payload": {"kind": "speak", "entry_id": "E2"}},
    ]
    broadcasts = [
        {"selected": [{"entry_id": "E1", "type": DRIVE_TYPE, "salience": 0.9}]},
        {"selected": [{"entry_id": "E2", "type": "self", "salience": 0.5}]},
    ]
    realizations = [
        {"stream": "language.external", "type": "external_speech", "payload": {"record_id": "R2"}},
        {"stream": "language.external", "type": "external_speech", "payload": {"record_id": "R1"}},
    ]
    report = classify_realizations(
        broadcasts,
        intents,
        realizations,
        record_links={"R1": "E1", "R2": "E2"},
    )
    assert report.realized_total == 2
    assert report.drive_triggered == 1
    assert report.self_initiated == 1
    assert report.drive_triggered_entry_ids == ["E1"]
    assert report.self_initiated_entry_ids == ["E2"]


def test_missing_record_links_no_speak_fallback():
    intents = [
        {"stream": "action_selection.out", "type": "intent.speak", "payload": {"kind": "speak", "entry_id": "E1"}},
        {"stream": "action_selection.out", "type": "intent.speak", "payload": {"kind": "speak", "entry_id": "E2"}},
        {"stream": "action_selection.out", "type": "intent.speak", "payload": {"kind": "speak", "entry_id": "E3"}},
    ]
    broadcasts = [
        {"selected": [{"entry_id": "E3", "type": DRIVE_TYPE, "salience": 0.9}]},
    ]
    realizations = [
        {"stream": "language.external", "type": "external_speech", "payload": {"record_id": "R1"}},
        {"stream": "language.external", "type": "external_speech", "payload": {"record_id": "R2"}},
        {"stream": "language.external", "type": "external_speech", "payload": {"record_id": "R3"}},
    ]
    report = classify_realizations(broadcasts, intents, realizations)
    assert report.drive_triggered == 0
    assert report.self_initiated == 3
    assert report.input_triggered_entry_ids == []
    assert report.drive_triggered_entry_ids == []
    assert report.self_initiated_entry_ids == []
    assert report.planning_initiated_entry_ids == []


def test_record_id_absent_from_links_counts_self_no_entry():
    intents = [
        {"stream": "action_selection.out", "type": "intent.speak", "payload": {"kind": "speak", "entry_id": "E1"}},
    ]
    realizations = [
        {"stream": "language.external", "type": "external_speech", "payload": {"record_id": "R1"}},
    ]
    report = classify_realizations([], intents, realizations, record_links={})
    assert report.realized_total == 1
    assert report.self_initiated == 1
    assert report.self_initiated_entry_ids == []


def test_internal_speech_linked_to_planning_think():
    intents = [
        {"stream": "action_selection.out", "type": "intent.think", "payload": {"kind": "think", "entry_id": "E1", "origin": "planning"}},
    ]
    realizations = [
        {"stream": "language.internal", "type": "internal_speech", "payload": {"record_id": "R1"}},
    ]
    report = classify_realizations([], intents, realizations, record_links={"R1": "E1"})
    assert report.realized_total == 1
    assert report.planning_initiated == 1
    assert report.planning_initiated_entry_ids == ["E1"]


def test_payload_entry_id_wins_over_record_links():
    intents = [
        {"stream": "action_selection.out", "type": "intent.speak", "payload": {"kind": "speak", "entry_id": "E1"}},
        {"stream": "action_selection.out", "type": "intent.speak", "payload": {"kind": "speak", "entry_id": "E2"}},
    ]
    broadcasts = [
        {"selected": [{"entry_id": "E1", "type": DRIVE_TYPE, "salience": 0.9}]},
        {"selected": [{"entry_id": "E2", "type": "self", "salience": 0.5}]},
    ]
    realizations = [
        {"stream": "language.external", "type": "external_speech", "payload": {"entry_id": "E1", "record_id": "R2"}},
    ]
    report = classify_realizations(
        broadcasts,
        intents,
        realizations,
        record_links={"R2": "E2"},
    )
    assert report.realized_total == 1
    assert report.drive_triggered == 1
    assert report.drive_triggered_entry_ids == ["E1"]


def test_requested_sleep_keeps_rest_fallback():
    intents = [
        {"stream": "action_selection.out", "type": "intent.rest", "payload": {"kind": "rest", "entry_id": "R9", "origin": "planning"}},
    ]
    realizations = [
        {"stream": "sleep.out", "type": "sleep.sleep.started", "payload": {"trigger": "requested"}},
    ]
    report = classify_realizations([], intents, realizations)
    assert report.realized_total == 1
    assert report.planning_initiated == 1
    assert report.planning_initiated_entry_ids == ["R9"]
