# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from datetime import datetime, timezone

import pytest

from kaine.bus import Event, EventValidationError, ReservedStreamError, module_stream
from kaine.bus.schema import (
    WORKSPACE_SOURCE,
    WORKSPACE_STREAM,
    ensure_writable,
    validate_event,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def test_valid_event_roundtrips():
    event = Event(
        source="interoception",
        type="wellness.update",
        payload={"score": 0.82},
        salience=0.3,
        timestamp=_now(),
    )
    assert event.source == "interoception"
    assert event.causal_parent is None


def test_salience_out_of_range_rejected():
    with pytest.raises(EventValidationError):
        validate_event(
            source="interoception",
            type="wellness.update",
            payload={},
            salience=1.5,
            timestamp=_now(),
        )


def test_negative_salience_rejected():
    with pytest.raises(EventValidationError):
        validate_event(
            source="interoception",
            type="wellness.update",
            payload={},
            salience=-0.01,
            timestamp=_now(),
        )


def test_missing_source_rejected():
    with pytest.raises(EventValidationError):
        validate_event(
            type="wellness.update",
            payload={},
            salience=0.5,
            timestamp=_now(),
        )


def test_naive_timestamp_rejected():
    with pytest.raises(EventValidationError):
        validate_event(
            source="interoception",
            type="t",
            payload={},
            salience=0.5,
            timestamp=datetime(2026, 5, 18),
        )


def test_whitespace_in_source_rejected():
    with pytest.raises(EventValidationError):
        validate_event(
            source="so ma",
            type="t",
            payload={},
            salience=0.5,
            timestamp=_now(),
        )


def test_module_stream_naming():
    assert module_stream("interoception") == "interoception.out"
    assert module_stream("sequence") == "sequence.out"
    assert module_stream(WORKSPACE_SOURCE) == WORKSPACE_STREAM


def test_workspace_stream_reserved():
    with pytest.raises(ReservedStreamError):
        ensure_writable(WORKSPACE_STREAM, "interoception")
    ensure_writable(WORKSPACE_STREAM, WORKSPACE_SOURCE)


def test_event_is_immutable():
    event = Event(
        source="interoception",
        type="t",
        payload={},
        salience=0.5,
        timestamp=_now(),
    )
    with pytest.raises(Exception):
        event.salience = 0.9  # type: ignore[misc]


def _tick_event(**extra):
    return Event(
        source="interoception",
        type="wellness.update",
        payload={},
        salience=0.3,
        timestamp=_now(),
        **extra,
    )


def test_event_without_tick_seq_parses():
    event = _tick_event()
    assert event.tick is None
    assert event.seq is None


def test_event_with_tick_seq_parses():
    event = _tick_event(tick=42, seq=7)
    assert event.tick == 42
    assert event.seq == 7


def test_event_extra_field_still_rejected():
    with pytest.raises(EventValidationError):
        validate_event(
            source="interoception",
            type="wellness.update",
            payload={},
            salience=0.3,
            timestamp=_now(),
            bogus=1,
        )


def test_tick_seq_in_model_dump():
    dumped = _tick_event(tick=1, seq=0).model_dump()
    assert dumped["tick"] == 1
    assert dumped["seq"] == 0
