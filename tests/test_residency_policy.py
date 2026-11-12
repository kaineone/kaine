# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

import asyncio

import pytest

from kaine.residency.policy import (
    PressureValve,
    read_available_memory,
    read_cgroup_limit,
    run_prewarm,
    run_ttl_sweep,
)


async def _noop_unload(n):
    pass


@pytest.mark.asyncio
async def test_ttl_sweep_unloads_expired():
    unloaded = []

    async def unload(n):
        unloaded.append(n)

    calls = [0]

    def expired():
        calls[0] += 1
        return ["stt"] if calls[0] == 1 else []

    stop = asyncio.Event()

    async def stopper():
        await asyncio.sleep(0.05)
        stop.set()

    asyncio.create_task(stopper())
    await run_ttl_sweep(expired, unload, interval=0.01, stop=stop)
    assert "stt" in unloaded


@pytest.mark.asyncio
async def test_ttl_sweep_skips_on_unload_error():
    unloaded = []

    async def unload(n):
        if n == "bad":
            raise RuntimeError("fail")
        unloaded.append(n)

    def expired():
        return ["bad", "good"]

    stop = asyncio.Event()

    async def stopper():
        await asyncio.sleep(0.03)
        stop.set()

    asyncio.create_task(stopper())
    await run_ttl_sweep(expired, unload, interval=0.01, stop=stop)
    assert "good" in unloaded
    assert "bad" not in unloaded


@pytest.mark.asyncio
async def test_ttl_sweep_stops_on_event():
    stop = asyncio.Event()
    stop.set()
    await asyncio.wait_for(
        run_ttl_sweep(lambda: [], _noop_unload, interval=0.01, stop=stop),
        timeout=1.0,
    )


@pytest.mark.asyncio
async def test_prewarm_submits_all():
    async def submit(n):
        return True

    result = await run_prewarm(("stt", "tts"), submit)
    assert result == ["stt", "tts"]


@pytest.mark.asyncio
async def test_prewarm_skips_failed():
    async def submit(n):
        return n == "stt"

    result = await run_prewarm(("stt", "tts"), submit)
    assert result == ["stt"]


@pytest.mark.asyncio
async def test_prewarm_skips_exception():
    async def submit(n):
        if n == "bad":
            raise RuntimeError
        return True

    result = await run_prewarm(("bad", "good"), submit)
    assert result == ["good"]


def test_read_available_memory_returns_int():
    val = read_available_memory()
    assert isinstance(val, int)
    assert val >= 0


def test_read_cgroup_limit():
    val = read_cgroup_limit()
    assert val is None or (isinstance(val, int) and val > 0)


@pytest.mark.asyncio
async def test_pressure_valve_no_pressure():
    valve = PressureValve(
        reserve_bytes=1_000_000_000,
        eviction_candidates_fn=lambda n: [],
        unload_fn=_noop_unload,
        footprint_fn=lambda n: 0,
        mem_fn=lambda: 2_000_000_000,
    )
    events = await valve.check()
    assert events == []


@pytest.mark.asyncio
async def test_pressure_valve_evicts_under_pressure():
    unloaded = []

    async def unload(n):
        unloaded.append(n)

    valve = PressureValve(
        reserve_bytes=1_000_000_000,
        eviction_candidates_fn=lambda n: ["stt"],
        unload_fn=unload,
        footprint_fn=lambda n: 600_000_000,
        mem_fn=lambda: 500_000_000,
    )
    events = await valve.check()
    assert len(events) == 1
    assert events[0].name == "stt"
    assert events[0].freed_bytes == 600_000_000


@pytest.mark.asyncio
async def test_pressure_valve_history():
    async def unload(n):
        pass

    valve = PressureValve(
        reserve_bytes=1_000_000_000,
        eviction_candidates_fn=lambda n: ["stt"],
        unload_fn=unload,
        footprint_fn=lambda n: 400_000_000,
        mem_fn=lambda: 500_000_000,
    )
    await valve.check()
    assert len(valve.history) == 1


@pytest.mark.asyncio
async def test_pressure_valve_unload_error_skipped():
    async def unload(n):
        if n == "bad":
            raise RuntimeError

    valve = PressureValve(
        reserve_bytes=1_000_000_000,
        eviction_candidates_fn=lambda n: ["bad", "good"],
        unload_fn=unload,
        footprint_fn=lambda n: 300_000_000,
        mem_fn=lambda: 500_000_000,
    )
    events = await valve.check()
    assert len(events) == 1
    assert events[0].name == "good"
