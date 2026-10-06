# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from datetime import datetime, timezone

from kaine.bus import Event
from kaine.workspace.nous_proposals import NousProposalSource

_summarize_event_with_kind = NousProposalSource._summarize_event_with_kind


def _event(source: str, type_: str, payload: dict) -> Event:
    return Event(
        source=source,
        type=type_,
        payload=payload,
        salience=0.5,
        timestamp=datetime.now(timezone.utc),
        causal_parent=None,
    )


def test_drive_event_summarized_as_felt_with_no_digits():
    ev = _event("thymos", "thymos.drive", {"drive": "curiosity", "value": 0.9})
    about, kind = _summarize_event_with_kind(None, ev)
    assert kind == "felt"
    assert not any(ch.isdigit() for ch in about)
    assert "value=" not in about
    assert "urge to know more" in about


def test_drive_event_at_moderate_value_is_moderate_phrase():
    ev = _event("thymos", "thymos.drive", {"drive": "boredom", "value": 0.5})
    about, kind = _summarize_event_with_kind(None, ev)
    assert kind == "felt"
    assert about == "I feel bored."


def test_transcription_summarized_as_heard():
    ev = _event("audition", "audition.transcription", {"text": "hello"})
    about, kind = _summarize_event_with_kind(None, ev)
    assert kind == "heard"
    assert about == "hello"
