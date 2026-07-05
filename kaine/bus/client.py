# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Optional

import redis.asyncio as aioredis
from redis.exceptions import ResponseError

from kaine.bus.config import BusConfig, load_bus_config, maxlen_for
from kaine.bus.errors import BusSecurityError, ReservedStreamError
from kaine.bus.schema import (
    SYNEIDESIS_SOURCE,
    WORKSPACE_STREAM,
    Event,
    ensure_writable,
    module_stream,
)

log = logging.getLogger(__name__)

_BUS_INSTANCE: Optional["AsyncBus"] = None
_BUS_LOCK = asyncio.Lock()


def _encode_event(event: Event) -> dict[str, str]:
    return {
        "source": event.source,
        "type": event.type,
        "salience": repr(event.salience),
        "timestamp": event.timestamp.isoformat(),
        "causal_parent": event.causal_parent or "",
        "payload": json.dumps(event.payload, separators=(",", ":")),
    }


def _decode_event(fields: dict[str, Any]) -> Event:
    def _get(key: str) -> str:
        value = fields.get(key) or fields.get(key.encode())
        if isinstance(value, bytes):
            value = value.decode()
        return value or ""

    causal = _get("causal_parent")
    raw_salience = _get("salience")
    try:
        salience = float(raw_salience)
    except (TypeError, ValueError):
        # Legacy/malformed stored entries may carry an empty salience.
        # Decode to the floor rather than raising; publish-time validation
        # still rejects such events at the write boundary.
        salience = 0.0
    return Event(
        source=_get("source"),
        type=_get("type"),
        salience=salience,
        timestamp=datetime.fromisoformat(_get("timestamp")),
        causal_parent=causal or None,
        payload=json.loads(_get("payload") or "{}"),
    )


def _decode_entry(
    entry_id: Any, fields: dict[str, Any]
) -> Optional[tuple[str, Event]]:
    """Decode one stream entry, tolerating malformed/legacy data.

    Returns ``None`` (with a logged warning) for an entry that cannot be
    decoded at all, so a single poison entry never raises out of a batch
    read and a consumer's cursor can advance past it.
    """
    if isinstance(entry_id, bytes):
        entry_id = entry_id.decode()
    try:
        return entry_id, _decode_event(fields)
    except Exception:
        # Expected for legacy/malformed stored entries (pre-validation data).
        # Debug-level so a large backlog scan doesn't flood the log; the
        # consumer advances past it regardless (see read_entries).
        log.debug("skipping undecodable stream entry %s", entry_id, exc_info=True)
        return None


def _decode_workspace(fields: dict[str, Any]) -> dict[str, Any]:
    raw = fields.get("snapshot") or fields.get(b"snapshot")
    if isinstance(raw, bytes):
        raw = raw.decode()
    return json.loads(raw or "{}")


class AsyncBus:
    def __init__(
        self,
        config: BusConfig,
        client: Optional[aioredis.Redis] = None,
    ) -> None:
        self._config = config
        self._client = client or aioredis.from_url(
            config.url, decode_responses=True
        )
        self._audited = False

    @property
    def config(self) -> BusConfig:
        return self._config

    @property
    def client(self) -> aioredis.Redis:
        return self._client

    LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})

    def _is_loopback(self) -> bool:
        return self._config.host in self.LOOPBACK_HOSTS

    async def audit(self) -> None:
        if self._audited:
            return
        # The bind check only matters when KAINE reaches Redis over a
        # routable interface. For loopback hosts (the containerized
        # KAINE Redis exposed on 127.0.0.1:6479, or a local system
        # Redis), Docker port mapping or kernel loopback restriction
        # already enforces network isolation regardless of what Redis
        # binds inside the container.
        if not self._is_loopback():
            try:
                bind = await self._client.config_get("bind")
            except ResponseError as exc:
                log.warning("CONFIG GET bind unavailable: %s; cannot verify bind", exc)
                bind = None
            if bind:
                value = bind.get("bind") or bind.get(b"bind")
                if isinstance(value, bytes):
                    value = value.decode()
                if value and ("0.0.0.0" in value or "*" in value):
                    raise BusSecurityError(
                        f"redis bind '{value}' is externally accessible "
                        f"and configured host {self._config.host!r} is "
                        "non-loopback; refuse to start"
                    )
        try:
            rp = await self._client.config_get("requirepass")
        except ResponseError as exc:
            log.warning("CONFIG GET requirepass unavailable: %s; cannot verify auth", exc)
            self._audited = True
            return
        value = rp.get("requirepass") or rp.get(b"requirepass") if rp else None
        if isinstance(value, bytes):
            value = value.decode()
        if not value:
            raise BusSecurityError(
                "redis requirepass is not set; refuse to start unauthenticated. "
                "KAINE requires Redis auth on every host (loopback or not) so the "
                "same checkout is safe to deploy onto a network-attached host."
            )
        self._audited = True

    async def publish(self, event: Event) -> str:
        stream = module_stream(event.source)
        ensure_writable(stream, event.source)
        return await self._client.xadd(
            stream,
            _encode_event(event),
            maxlen=maxlen_for(self._config, stream),
            approximate=True,
        )

    async def publish_workspace(
        self, snapshot: dict[str, Any], source: str = SYNEIDESIS_SOURCE
    ) -> str:
        if source != SYNEIDESIS_SOURCE:
            raise ReservedStreamError(
                f"only the syneidesis module may publish to {WORKSPACE_STREAM}"
            )
        return await self._client.xadd(
            WORKSPACE_STREAM,
            {
                "snapshot": json.dumps(snapshot, separators=(",", ":")),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "source": SYNEIDESIS_SOURCE,
            },
            maxlen=maxlen_for(self._config, WORKSPACE_STREAM),
            approximate=True,
        )

    async def read_entries(
        self, stream: str, last_id: str = "0", count: int = 100, block_ms: int = 0
    ) -> tuple[list[tuple[str, Event]], Optional[str]]:
        """Like :meth:`read`, but also returns the id of the last entry
        *scanned* — decodable or not.

        A cursor-advancing consumer must advance to this id rather than to the
        last *decoded* entry; otherwise a batch made entirely of undecodable
        (legacy/malformed) entries returns no decoded events, the cursor never
        moves, and the consumer re-reads the same poison batch forever.
        """
        response = await self._client.xread(
            {stream: last_id}, count=count, block=block_ms or None
        )
        if not response:
            return [], None
        _, entries = response[0]
        out: list[tuple[str, Event]] = []
        last_scanned: Optional[str] = None
        for entry_id, fields in entries:
            if isinstance(entry_id, bytes):
                entry_id = entry_id.decode()
            last_scanned = entry_id
            decoded = _decode_entry(entry_id, fields)
            if decoded is not None:
                out.append(decoded)
        return out, last_scanned

    async def read(
        self, stream: str, last_id: str = "0", count: int = 100, block_ms: int = 0
    ) -> list[tuple[str, Event]]:
        entries, _ = await self.read_entries(stream, last_id, count, block_ms)
        return entries

    async def range(
        self, stream: str, start: str = "-", end: str = "+", count: Optional[int] = None
    ) -> list[tuple[str, Event]]:
        entries = await self._client.xrange(stream, min=start, max=end, count=count)
        out: list[tuple[str, Event]] = []
        for entry_id, fields in entries:
            decoded = _decode_entry(entry_id, fields)
            if decoded is not None:
                out.append(decoded)
        return out

    async def subscribe_workspace(
        self,
        last_id: str = "$",
        count: int = 32,
        poll_interval_s: float = 0.05,
    ) -> AsyncIterator[tuple[str, dict[str, Any]]]:
        cursor = await self._resolve_dollar(last_id)
        while True:
            response = await self._client.xread(
                {WORKSPACE_STREAM: cursor}, count=count
            )
            if not response:
                await asyncio.sleep(poll_interval_s)
                continue
            _, entries = response[0]
            for entry_id, fields in entries:
                if isinstance(entry_id, bytes):
                    entry_id = entry_id.decode()
                cursor = entry_id
                # A malformed broadcast (e.g. a truncated/corrupt snapshot
                # field) must not kill the subscription for every consumer —
                # skip it and keep following, like the read path tolerates
                # legacy entries. Advancing `cursor` first means it isn't re-read.
                try:
                    decoded = _decode_workspace(fields)
                except Exception:
                    log.warning(
                        "skipping undecodable workspace.broadcast entry %s",
                        entry_id, exc_info=True,
                    )
                    continue
                yield entry_id, decoded

    async def _resolve_dollar(self, last_id: str) -> str:
        if last_id != "$":
            return last_id
        latest = await self._client.xrevrange(WORKSPACE_STREAM, count=1)
        if not latest:
            return "0-0"
        entry_id = latest[0][0]
        if isinstance(entry_id, bytes):
            entry_id = entry_id.decode()
        return entry_id

    async def trim(self, stream: str, maxlen: int) -> int:
        return await self._client.xtrim(stream, maxlen=maxlen, approximate=True)

    async def length(self, stream: str) -> int:
        return await self._client.xlen(stream)

    async def current_workspace_id(self) -> str:
        return await self._resolve_dollar("$")

    async def close(self) -> None:
        await self._client.aclose()


async def get_bus(client: Optional[aioredis.Redis] = None) -> AsyncBus:
    global _BUS_INSTANCE
    if _BUS_INSTANCE is not None:
        return _BUS_INSTANCE
    async with _BUS_LOCK:
        if _BUS_INSTANCE is None:
            config = load_bus_config()
            bus = AsyncBus(config, client=client)
            if config.audit_required:
                await bus.audit()
            _BUS_INSTANCE = bus
    return _BUS_INSTANCE


def reset_bus_for_tests() -> None:
    global _BUS_INSTANCE
    _BUS_INSTANCE = None
