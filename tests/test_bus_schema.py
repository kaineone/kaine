# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from datetime import datetime, timezone

import pytest

from kaine.bus import Event, EventValidationError, ReservedStreamError, module_stream
from kaine.bus.schema import (
    SYNEIDESIS_SOURCE,
    WORKSPACE_STREAM,
    ensure_writable,
    validate_event,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def test_valid_event_roundtrips():
    event = Event(
        source="soma",
        type="wellness.update",
        payload={"score": 0.82},
        salience=0.3,
        timestamp=_now(),
    )
    assert event.source == "soma"
    assert event.causal_parent is None


def test_salience_out_of_range_rejected():
    with pytest.raises(EventValidationError):
        validate_event(
            source="soma",
            type="wellness.update",
            payload={},
            salience=1.5,
            timestamp=_now(),
        )


def test_negative_salience_rejected():
    with pytest.raises(EventValidationError):
        validate_event(
            source="soma",
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
            source="soma",
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
    assert module_stream("soma") == "soma.out"
    assert module_stream("chronos") == "chronos.out"
    assert module_stream(SYNEIDESIS_SOURCE) == WORKSPACE_STREAM


def test_workspace_stream_reserved():
    with pytest.raises(ReservedStreamError):
        ensure_writable(WORKSPACE_STREAM, "soma")
    ensure_writable(WORKSPACE_STREAM, SYNEIDESIS_SOURCE)


def test_event_is_immutable():
    event = Event(
        source="soma",
        type="t",
        payload={},
        salience=0.5,
        timestamp=_now(),
    )
    with pytest.raises(Exception):
        event.salience = 0.9  # type: ignore[misc]
