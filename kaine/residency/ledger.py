# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import asyncio
import enum
import time
from dataclasses import dataclass


class State(enum.Enum):
    ABSENT = "absent"
    COLD = "cold"
    LOADING = "loading"
    RESIDENT = "resident"
    UNLOADING = "unloading"


class Priority(enum.Enum):
    INTERACTIVE = "interactive"
    BACKGROUND = "background"


@dataclass
class Entry:
    name: str
    state: State = State.ABSENT
    footprint_bytes: int = 0
    last_used: float = 0.0
    pinned: bool = False
    priority: Priority = Priority.BACKGROUND
    inflight: int = 0
    ttl_seconds: int = 120


class Ledger:
    def __init__(self, budget_bytes: int, pin: str = "language") -> None:
        self._entries: dict[str, Entry] = {}
        self._budget_bytes = budget_bytes
        self._pin = pin
        self._lock = asyncio.Lock()

    def register(self, name: str, footprint_bytes: int = 0, ttl_seconds: int = 120) -> None:
        entry = self._entries.get(name)
        if entry is None:
            entry = Entry(
                name=name,
                footprint_bytes=footprint_bytes,
                ttl_seconds=ttl_seconds,
            )
            self._entries[name] = entry
        elif entry.state in (State.ABSENT, State.COLD):
            entry.footprint_bytes = footprint_bytes
            entry.ttl_seconds = ttl_seconds

        if name == self._pin:
            entry.pinned = True

    @property
    def headroom(self) -> int:
        used = sum(
            entry.footprint_bytes
            for entry in self._entries.values()
            if entry.state in (State.LOADING, State.RESIDENT)
        )
        return max(0, self._budget_bytes - used)

    @property
    def reserved(self) -> int:
        return sum(
            entry.footprint_bytes
            for entry in self._entries.values()
            if entry.state in (State.LOADING, State.RESIDENT)
        )

    def get(self, name: str) -> Entry | None:
        return self._entries.get(name)

    def entries(self) -> dict[str, Entry]:
        return dict(self._entries)

    async def try_admit(
        self,
        name: str,
        footprint_bytes: int,
        priority: Priority = Priority.INTERACTIVE,
    ) -> bool:
        async with self._lock:
            entry = self._entries.get(name)
            if entry is None:
                return False
            if entry.state in (State.LOADING, State.RESIDENT):
                return True
            if entry.state == State.UNLOADING:
                return False
            if self.headroom >= footprint_bytes:
                entry.state = State.LOADING
                entry.footprint_bytes = footprint_bytes
                entry.priority = priority
                entry.last_used = time.monotonic()
                return True
            return False

    def mark_resident(self, name: str) -> None:
        entry = self._entries.get(name)
        if entry is not None:
            entry.state = State.RESIDENT
            entry.last_used = time.monotonic()

    def mark_unloading(self, name: str) -> None:
        entry = self._entries.get(name)
        if entry is not None:
            entry.state = State.UNLOADING

    def mark_cold(self, name: str) -> None:
        entry = self._entries.get(name)
        if entry is not None:
            entry.state = State.COLD
            entry.footprint_bytes = 0

    def record_use(self, name: str) -> None:
        entry = self._entries.get(name)
        if entry is not None and entry.state == State.RESIDENT:
            entry.last_used = time.monotonic()

    def increment_inflight(self, name: str) -> None:
        entry = self._entries.get(name)
        if entry is not None:
            entry.inflight += 1

    def decrement_inflight(self, name: str) -> None:
        entry = self._entries.get(name)
        if entry is not None:
            entry.inflight = max(0, entry.inflight - 1)

    def eviction_candidates(self, needed_bytes: int) -> list[str]:
        if needed_bytes <= 0:
            return []

        now = time.monotonic()
        candidates: list[tuple[str, Entry]] = []

        for name, entry in self._entries.items():
            if entry.state != State.RESIDENT:
                continue
            if entry.pinned:
                continue
            if entry.inflight > 0:
                continue
            candidates.append((name, entry))

        def sort_key(item: tuple[str, Entry]) -> tuple[int, int, float]:
            name, entry = item
            expired = now - entry.last_used > entry.ttl_seconds
            background = entry.priority == Priority.BACKGROUND
            return (
                0 if expired else 1,
                0 if background else 1,
                entry.last_used,
            )

        candidates.sort(key=sort_key)

        result: list[str] = []
        freed = 0
        for name, entry in candidates:
            result.append(name)
            freed += entry.footprint_bytes
            if freed >= needed_bytes:
                break

        return result

    def ttl_expired(self) -> list[str]:
        now = time.monotonic()
        result: list[str] = []
        for name, entry in self._entries.items():
            if entry.state != State.RESIDENT:
                continue
            if entry.pinned:
                continue
            if entry.inflight > 0:
                continue
            if now - entry.last_used > entry.ttl_seconds:
                result.append(name)
        return result
