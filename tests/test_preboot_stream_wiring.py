# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Boot-time stream-cap validation."""

import logging

from kaine.preboot import bus_budget


def test_bus_budget_warns_once_for_unknown_per_stream_maxlen_key(caplog):
    """An unknown [bus.per_stream_maxlen] key warns exactly once and names the key."""
    config = {
        "bus": {"per_stream_maxlen": {"audition.out": 10, "auditon.out": 10}},
        "modules": {"audition": True},
    }
    with caplog.at_level(logging.WARNING, logger="kaine.preboot"):
        bus_budget(config)

    warnings = [
        r
        for r in caplog.records
        if r.levelno == logging.WARNING and "auditon.out" in r.message
    ]
    assert len(warnings) == 1, warnings
    message = warnings[0].message.lower()
    assert "cap" in message or "no effect" in message

    # The known key must not generate a warning.
    assert not any(
        "audition.out" in r.message and "nothing publishes" in r.message
        for r in caplog.records
    )
