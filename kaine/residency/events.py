# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger(__name__)

VALID_KINDS = frozenset({
    "load_start",
    "load_end",
    "unload",
    "evict",
    "downgrade",
    "queue_drop",
})

@dataclass(frozen=True)
class ResidencyEvent:
    kind: str
    name: str
    ts: float = field(default_factory=time.monotonic)
    reason: str = ""
    duration_seconds: float | None = None
    freed_bytes: int | None = None
    from_rung: str | None = None
    to_rung: str | None = None

    def as_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"kind": self.kind, "name": self.name, "ts": self.ts}
        if self.reason:
            d["reason"] = self.reason
        if self.duration_seconds is not None:
            d["duration_seconds"] = self.duration_seconds
        if self.freed_bytes is not None:
            d["freed_bytes"] = self.freed_bytes
        if self.from_rung is not None:
            d["from_rung"] = self.from_rung
        if self.to_rung is not None:
            d["to_rung"] = self.to_rung
        return d


_LOCK = threading.Lock()
_EVENTS: list[ResidencyEvent] = []

def _record(event: ResidencyEvent) -> ResidencyEvent:
    with _LOCK:
        _EVENTS.append(event)
    return event

def record_load_start(name: str) -> ResidencyEvent:
    event = ResidencyEvent(kind="load_start", name=name)
    _record(event)
    log.info("residency load_start: %s", name)
    return event

def record_load_end(name: str, duration_seconds: float) -> ResidencyEvent:
    event = ResidencyEvent(kind="load_end", name=name, duration_seconds=duration_seconds)
    _record(event)
    log.info("residency load_end: %s (%.2fs)", name, duration_seconds)
    return event

def record_unload(name: str, reason: str) -> ResidencyEvent:
    event = ResidencyEvent(kind="unload", name=name, reason=reason)
    _record(event)
    log.info("residency unload: %s (%s)", name, reason)
    return event

def record_evict(name: str, reason: str, freed_bytes: int) -> ResidencyEvent:
    event = ResidencyEvent(kind="evict", name=name, reason=reason, freed_bytes=freed_bytes)
    _record(event)
    log.info("residency evict: %s freed=%d (%s)", name, freed_bytes, reason)
    return event

def record_downgrade(name: str, reason: str, from_rung: str, to_rung: str) -> ResidencyEvent:
    event = ResidencyEvent(kind="downgrade", name=name, reason=reason, from_rung=from_rung, to_rung=to_rung)
    _record(event)
    log.info("residency downgrade: %s %s -> %s (%s)", name, from_rung, to_rung, reason)
    return event

def record_queue_drop(name: str, reason: str) -> ResidencyEvent:
    event = ResidencyEvent(kind="queue_drop", name=name, reason=reason)
    _record(event)
    log.info("residency queue_drop: %s (%s)", name, reason)
    return event

def residency_events() -> list[ResidencyEvent]:
    with _LOCK:
        return list(_EVENTS)

def residency_events_snapshot() -> list[dict[str, Any]]:
    return [e.as_dict() for e in residency_events()]

def clear_residency_events() -> None:
    with _LOCK:
        _EVENTS.clear()
