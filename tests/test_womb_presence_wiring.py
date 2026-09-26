# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The cycle entrypoint starts the womb presence publisher only in womb mode."""
from __future__ import annotations

import asyncio

import pytest

from kaine.cycle.__main__ import _start_womb_presence
from kaine.modules.topos.feed import WombClock


@pytest.mark.asyncio
async def test_no_womb_clock_starts_nothing() -> None:
    stop = asyncio.Event()
    assert _start_womb_presence({"perception_feed": {"mode": "seeded"}}, object(), stop) is None


@pytest.mark.asyncio
async def test_womb_clock_starts_a_publisher_that_announces_deliveries() -> None:
    published: list = []

    class _Bus:
        async def publish(self, event) -> str:  # noqa: ANN001
            published.append(event)
            return "1-0"

    clock = WombClock(lived_offset_seconds=0.0)
    clock.mark_delivered("video", 7)
    clock.mark_delivered("audio", 3)
    stop = asyncio.Event()
    task = _start_womb_presence(
        {"perception_feed": {"mode": "womb", "_shared_womb_clock": clock}}, _Bus(), stop
    )
    assert task is not None
    await asyncio.sleep(0.05)
    stop.set()
    await asyncio.wait_for(task, timeout=2.0)
    assert published
    assert published[0].source == "gestation"
    assert published[0].type == "gestation.womb"
    assert published[0].payload == {"provider": "local", "frame_index": 7}
