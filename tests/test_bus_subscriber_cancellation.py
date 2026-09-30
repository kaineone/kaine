# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import asyncio
import inspect
from datetime import datetime, timezone

import fakeredis.aioredis
import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.bus.schema import Event, module_stream
from kaine.modules.base import BaseModule


class _CancelCounter:
    __slots__ = ("count",)

    def __init__(self) -> None:
        self.count = 0


def _install_swallowing_xread(client):
    counter = _CancelCounter()

    async def fake_xread(*args, **kwargs):
        # Simulates asyncio.wait_for on Python 3.11 when a cancellation races
        # completion: the first CancelledError is swallowed, later ones propagate.
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            counter.count += 1
            if counter.count == 1:
                return []
            raise
        raise AssertionError("the fake never completes on its own; only a cancellation ends it")

    client.xread = fake_xread
    return client


def _install_swallowing_xadd(client):
    counter = _CancelCounter()

    async def fake_xadd(*args, **kwargs):
        # Same swallowing behaviour as _install_swallowing_xread, but for XADD.
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            counter.count += 1
            if counter.count == 1:
                return "0-1"
            raise
        raise AssertionError("the fake never completes on its own; only a cancellation ends it")

    client.xadd = fake_xadd
    return client


def _make_bus(client=None, swallow=False):
    client = client or fakeredis.aioredis.FakeRedis(decode_responses=True)
    if swallow:
        client = _install_swallowing_xread(client)
    return AsyncBus(BusConfig(password="x", audit_required=False), client=client), client


async def _consume(bus, method, **kwargs):
    async for _ in getattr(bus, method)(**kwargs):
        pass


async def _cancel_and_wait(task):
    task.cancel()
    done, _ = await asyncio.wait({task}, timeout=2.0)
    finished = task in done
    if not finished:
        task.cancel()
        await asyncio.wait({task}, timeout=2.0)
    assert finished, "subscription task did not finish after cancel within timeout"


async def test_subscribe_workspace_block_cancels_with_swallowing_client():
    bus, _client = _make_bus(swallow=True)
    try:
        task = asyncio.create_task(
            _consume(bus, "subscribe_workspace_block", last_id="0-0", block_ms=50)
        )
        await asyncio.sleep(0.2)
        await _cancel_and_wait(task)
        assert task.cancelled()
    finally:
        await bus.close()


async def test_subscribe_workspace_cancels_with_swallowing_client():
    bus, _client = _make_bus(swallow=True)
    try:
        task = asyncio.create_task(
            _consume(bus, "subscribe_workspace", last_id="0-0", poll_interval_s=0.01)
        )
        await asyncio.sleep(0.2)
        await _cancel_and_wait(task)
        assert task.cancelled()
    finally:
        await bus.close()


@pytest.mark.parametrize(
    "method,kwargs",
    [
        ("subscribe_workspace", {"last_id": "0-0", "poll_interval_s": 0.01}),
        ("subscribe_workspace_block", {"last_id": "0-0", "block_ms": 50}),
    ],
)
async def test_subscriber_cancels_with_normal_client(method, kwargs):
    bus, _client = _make_bus(swallow=False)
    try:
        task = asyncio.create_task(_consume(bus, method, **kwargs))
        await asyncio.sleep(0.2)
        await _cancel_and_wait(task)
        assert task.cancelled()
    finally:
        await bus.close()


class _ProbeModule(BaseModule):
    name = "probe"

    async def on_workspace(self, snapshot) -> None:
        pass


async def test_module_shutdown_with_swallowing_client():
    bus, _client = _make_bus(swallow=True)
    module = _ProbeModule(bus)
    try:
        await module.initialize()
        await asyncio.sleep(0.2)
        shutdown_task = asyncio.create_task(module.shutdown())
        done, _ = await asyncio.wait({shutdown_task}, timeout=2.0)
        finished = shutdown_task in done
        if not finished:
            for task in list(module._tasks):
                task.cancel()
            await asyncio.wait({shutdown_task}, timeout=2.0)
        assert finished, "module shutdown did not finish within timeout"
        assert shutdown_task.result() is None
    finally:
        await bus.close()


def _valid_event():
    return Event(
        source="soma",
        type="wellness.update",
        payload={},
        salience=0.3,
        timestamp=datetime.now(timezone.utc),
    )


async def test_publish_reraises_swallowed_cancel():
    bus, raw = _make_bus()
    _install_swallowing_xadd(raw)
    try:
        task = asyncio.create_task(bus.publish(_valid_event()))
        await asyncio.sleep(0.1)
        await _cancel_and_wait(task)
        assert task.cancelled()
    finally:
        await bus.close()


async def test_cleanup_after_caught_cancel_still_uses_bus():
    bus, raw = _make_bus()
    results = []

    async def body():
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            entry = await bus.publish(_valid_event())
            results.append(entry)
            raise

    try:
        task = asyncio.create_task(body())
        await asyncio.sleep(0.05)
        await _cancel_and_wait(task)
        assert task.cancelled()
        assert len(results) == 1
        assert results[0]
        assert await bus.client.xlen(module_stream("soma")) == 1
    finally:
        await bus.close()


async def test_client_passthrough():
    bus, raw = _make_bus()
    try:
        bus.client.some_marker = 7
        assert getattr(raw, "some_marker") == 7
        assert bus.client.connection_pool is raw.connection_pool
        pipeline = bus.client.pipeline()
        assert not inspect.iscoroutine(pipeline)
        assert hasattr(pipeline, "execute")
    finally:
        await bus.close()
