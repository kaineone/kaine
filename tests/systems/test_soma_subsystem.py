# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Soma subsystem: reads system metrics + cycle latency, publishes wellness."""
from __future__ import annotations

import asyncio

import pytest

from kaine.modules.soma.module import Soma
from kaine.modules.soma.reader import MetricsReader

from tests.systems._harness import SubsystemHarness


class FakeReader:
    async def read_metrics(self):
        return {
            "cpu_percent": 25.0,
            "ram_percent": 40.0,
            "gpu_0_temp_c": 65.0,
            "gpu_0_vram_percent": 55.0,
        }

    async def initialize(self):
        return

    async def shutdown(self):
        return


@pytest.mark.asyncio
async def test_soma_publishes_wellness_event():
    async with SubsystemHarness() as h:
        soma = Soma(h.bus, reader=FakeReader(), read_interval_s=0.05)
        await h.register(soma)
        # Soma's background loop runs at read_interval_s; wait a beat. The
        # developmental warm-up (enabled by default) emits a soma.warmup.started
        # marker first, so select the wellness report by its payload.
        events = await h.collect("soma.out", count=2, timeout=1.0)
        reports = [
            ev
            for ev in events
            if "wellness" in ev.payload or "metrics" in ev.payload
        ]
        assert reports, "Soma should have emitted at least one wellness event"
        assert reports[0].source == "soma"
        assert 0.0 <= reports[0].salience <= 1.0


@pytest.mark.asyncio
async def test_soma_alerts_when_threshold_crossed():
    class HotReader:
        async def read_metrics(self):
            return {"cpu_percent": 99.5, "ram_percent": 99.5}

        async def initialize(self):
            return

        async def shutdown(self):
            return

    async with SubsystemHarness() as h:
        soma = Soma(h.bus, reader=HotReader(), read_interval_s=0.05)
        await h.register(soma)
        events = await h.collect("soma.out", count=2, timeout=1.0)
        # Among the events, at least one should carry elevated salience.
        assert any(ev.salience > 0.4 for ev in events)
