# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""SubsystemHarness — one module under test against a fakeredis bus.

Usage:
    @pytest.mark.systems
    @pytest.mark.asyncio
    async def test_some_subsystem():
        async with SubsystemHarness() as h:
            soma = Soma(h.bus)
            await h.register(soma)
            await h.inject_cycle_event(...)
            events = await h.collect("soma.out", count=1, timeout=1.0)
            assert events[0].type == "soma.tick"
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Optional

import pytest

from kaine.bus.client import AsyncBus
from kaine.bus.config import BusConfig
from kaine.bus.schema import Event, validate_event
from kaine.modules.base import BaseModule


class SubsystemHarness:
    """Builds a fakeredis-backed AsyncBus with ONE module under test."""

    def __init__(self) -> None:
        self._fakeredis = pytest.importorskip("fakeredis.aioredis")
        self._client = None
        self.bus: AsyncBus | None = None
        self._module: BaseModule | None = None

    async def __aenter__(self) -> "SubsystemHarness":
        self._client = self._fakeredis.FakeRedis(decode_responses=True)
        self.bus = AsyncBus(
            BusConfig(password="x", audit_required=False), client=self._client
        )
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._module is not None:
            try:
                await self._module.shutdown()
            except Exception:
                # Best-effort teardown: the harness is exiting regardless,
                # and a module's shutdown failure shouldn't mask whatever
                # assertion/error the test itself is already reporting.
                pass
        if self.bus is not None:
            await self.bus.close()

    async def register(self, module: BaseModule) -> None:
        if self._module is not None:
            raise ValueError(
                "SubsystemHarness registers exactly one module; got a "
                f"second registration after {self._module.name!r}"
            )
        self._module = module
        await module.initialize()

    async def inject(
        self,
        stream: str,
        *,
        source: str | None = None,
        type: str = "test.injected",
        payload: dict[str, Any] | None = None,
        salience: float = 0.5,
    ) -> str:
        """Publish into an arbitrary stream by setting `source` to the
        module name implied by the stream (`<source>.out`)."""
        assert self.bus is not None
        if source is None:
            source = stream.split(".", 1)[0] if "." in stream else stream
        event = validate_event(
            source=source,
            type=type,
            payload=payload or {},
            salience=salience,
            timestamp=datetime.now(timezone.utc),
        )
        return await self.bus.publish(event)

    async def inject_raw(
        self, stream: str, fields: dict[str, str]
    ) -> str:
        """Append a raw entry directly (bypasses validation). Used by
        tests that need to inject events to streams whose source doesn't
        match the stream prefix."""
        assert self.bus is not None
        return await self.bus._client.xadd(stream, fields)

    async def inject_to_stream(
        self,
        stream: str,
        *,
        source: str = "test",
        type: str = "test.event",
        payload: dict[str, Any] | None = None,
        salience: float = 0.5,
    ) -> str:
        """Inject a standard-format event into an arbitrary stream
        (e.g. lingua.external) using the same xadd shape AsyncBus.read
        expects to decode."""
        import json

        assert self.bus is not None
        fields = {
            "source": source,
            "type": type,
            "salience": repr(float(salience)),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "causal_parent": "",
            "payload": json.dumps(payload or {}),
        }
        return await self.bus._client.xadd(stream, fields)

    async def collect(
        self,
        stream: str,
        *,
        count: int = 1,
        timeout: float = 1.0,
        filter_type: Optional[str] = None,
    ) -> list[Event]:
        """Poll until `count` events arrive on `stream` or timeout."""
        assert self.bus is not None
        deadline = asyncio.get_event_loop().time() + timeout
        collected: list[Event] = []
        cursor = "0"
        while len(collected) < count:
            entries = await self.bus.read(stream, last_id=cursor, count=64, block_ms=0)
            for entry_id, event in entries:
                cursor = entry_id
                if filter_type is not None and event.type != filter_type:
                    continue
                collected.append(event)
                if len(collected) >= count:
                    break
            if len(collected) >= count:
                break
            if asyncio.get_event_loop().time() >= deadline:
                break
            await asyncio.sleep(0.02)
        return collected

    async def broadcast_workspace(self, payload: dict[str, Any]) -> str:
        """Convenience: publish a workspace.broadcast event via the bus's
        own publish_workspace helper."""
        assert self.bus is not None
        return await self.bus.publish_workspace(payload)
