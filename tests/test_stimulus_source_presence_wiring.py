# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The cycle entrypoint starts the stimulus source presence publisher only in stimulus source mode."""
from __future__ import annotations

import asyncio

import pytest

from kaine.bus.streams import DEVELOPMENT_SOURCE
from kaine.cycle.__main__ import _start_stimulus_source_presence
from kaine.modules.vision.feed import StimulusSourceClock


@pytest.mark.asyncio
async def test_no_stimulus_source_clock_starts_nothing() -> None:
    stop = asyncio.Event()
    assert _start_stimulus_source_presence({"perception_feed": {"mode": "seeded"}}, object(), stop) is None


@pytest.mark.asyncio
async def test_stimulus_source_clock_starts_a_publisher_that_announces_deliveries() -> None:
    published: list = []

    class _Bus:
        async def publish(self, event) -> str:  # noqa: ANN001
            published.append(event)
            return "1-0"

    clock = StimulusSourceClock(lived_offset_seconds=0.0)
    clock.mark_delivered("video", 7)
    clock.mark_delivered("audio", 3)
    stop = asyncio.Event()
    task = _start_stimulus_source_presence(
        {"perception_feed": {"mode": "womb", "_shared_womb_clock": clock}}, _Bus(), stop
    )
    assert task is not None
    await asyncio.sleep(0.05)
    stop.set()
    await asyncio.wait_for(task, timeout=2.0)
    assert published
    assert published[0].source == DEVELOPMENT_SOURCE
    assert published[0].type == "gestation.womb"
    assert published[0].payload == {"provider": "local", "frame_index": 7}
