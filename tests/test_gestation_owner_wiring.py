# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The cycle entrypoint starts the gestation readout owner only when it can measure."""
from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace

import pytest

from kaine.cycle.__main__ import _start_gestation_owner
from kaine.modules.topos.feed import WombClock


class _Registry:
    def __init__(self, modules: dict, now) -> None:
        self._m = modules
        self.entity_clock = SimpleNamespace(now=now)

    def __contains__(self, name: str) -> bool:
        return name in self._m

    def get(self, name: str):
        return self._m[name]


class _Drive:
    scale = 1.0


class _Soma:
    def __init__(self) -> None:
        self.maternal_drive = _Drive()

    def self_rhythm_state(self):
        return (0.5, 0.1)


class _Bus:
    def __init__(self) -> None:
        self.events = []

    async def publish(self, event) -> str:
        self.events.append(event)
        return "1-0"

    async def latest(self, stream):
        return None

    async def read(self, stream, last_id="0", count=64):
        return []


def _feed(**extra) -> dict:
    feed = {"mode": "womb", "seed": 1, "_shared_womb_clock": WombClock(lived_offset_seconds=0.0)}
    feed["_womb_lived_seconds"] = lambda: 0.0
    feed.update(extra)
    return feed


@pytest.mark.asyncio
async def test_not_started_outside_womb_mode() -> None:
    reg = _Registry({"soma": _Soma()}, now=lambda: 0.0)
    task = _start_gestation_owner(
        {"perception_feed": {"mode": "seeded"}}, _Bus(), reg, asyncio.Event(),
        is_paused=lambda: False,
    )
    assert task is None


@pytest.mark.asyncio
async def test_not_started_without_a_self_rhythm_and_says_why(caplog) -> None:
    reg = _Registry({}, now=lambda: 0.0)
    with caplog.at_level(logging.WARNING):
        task = _start_gestation_owner(
            {"perception_feed": _feed()}, _Bus(), reg, asyncio.Event(),
            is_paused=lambda: False,
        )
    assert task is None
    assert any("gestation readout unavailable" in r.getMessage() for r in caplog.records)


@pytest.mark.asyncio
async def test_started_and_publishes_a_readiness_readout(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)  # the owner's default state path is relative
    clock = {"t": 0.0}
    reg = _Registry({"soma": _Soma()}, now=lambda: clock["t"])
    bus = _Bus()
    stop = asyncio.Event()
    feed = _feed(womb={"readout": {"readout_period_seconds": 0.05, "sample_hz": 100.0}})
    task = _start_gestation_owner(
        {"perception_feed": feed}, bus, reg, stop, is_paused=lambda: False
    )
    assert task is not None
    for _ in range(20):
        clock["t"] += 0.05
        await asyncio.sleep(0.01)
    stop.set()
    await asyncio.wait_for(task, timeout=2.0)
    assert any(e.type == "gestation.readiness" and e.source == "gestation" for e in bus.events)
