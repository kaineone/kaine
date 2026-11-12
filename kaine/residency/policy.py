# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class EvictionEvent:
    name: str
    reason: str
    freed_bytes: int

async def run_ttl_sweep(
    expired_fn: Callable[[], list[str]],
    unload_fn: Callable[[str], Awaitable[None]],
    interval: float = 10.0,
    stop: asyncio.Event | None = None,
) -> None:
    """Periodically call expired_fn() and unload each returned name.

    Runs forever until stop is set (or the task is cancelled). Each
    cycle: sleep interval, call expired_fn, call unload_fn for each
    name. If unload_fn raises, skip that name and continue.
    """
    while True:
        if stop is not None and stop.is_set():
            return
        await asyncio.sleep(interval)
        if stop is not None and stop.is_set():
            return
        for name in expired_fn():
            try:
                await unload_fn(name)
            except Exception:
                pass

async def run_prewarm(
    names: tuple[str, ...],
    submit_fn: Callable[[str], Awaitable[bool]],
) -> list[str]:
    """Submit prewarm loads for the given names at background priority.

    Returns the list of names that were successfully submitted.
    Calls submit_fn(name) for each. If submit_fn returns False or
    raises, skip that name.
    """
    submitted: list[str] = []
    for name in names:
        try:
            ok = await submit_fn(name)
            if ok:
                submitted.append(name)
        except Exception:
            pass
    return submitted

def read_available_memory() -> int:
    """Read MemAvailable from /proc/meminfo. Returns bytes.

    Falls back to 0 if /proc/meminfo is unavailable (non-Linux).
    """
    try:
        text = Path("/proc/meminfo").read_text()
        for line in text.splitlines():
            if line.startswith("MemAvailable:"):
                parts = line.split()
                return int(parts[1]) * 1024
    except (OSError, ValueError, IndexError):
        pass
    return 0

def read_cgroup_limit() -> int | None:
    """Read cgroup v2 memory.max. Returns bytes, or None if uncapped.

    Checks /sys/fs/cgroup/memory.max. "max" means no limit.
    """
    try:
        text = Path("/sys/fs/cgroup/memory.max").read_text().strip()
        if text == "max":
            return None
        return int(text)
    except (OSError, ValueError):
        return None

class PressureValve:
    """Watches system memory and triggers eviction when it nears the reserve.

    Constructor args:
    - reserve_bytes: the safety margin to protect (bytes)
    - eviction_candidates_fn: Callable[[int], list[str]] — returns names
      to evict given the number of bytes needed, ordered best-first
    - unload_fn: Callable[[str], Awaitable[None]] — unloads a named entry
    - footprint_fn: Callable[[str], int] — returns footprint_bytes for a name
    - mem_fn: Callable[[], int] — returns current available memory (default:
      read_available_memory)
    """

    def __init__(
        self,
        reserve_bytes: int,
        eviction_candidates_fn: Callable[[int], list[str]],
        unload_fn: Callable[[str], Awaitable[None]],
        footprint_fn: Callable[[str], int],
        mem_fn: Callable[[], int] = read_available_memory,
    ) -> None:
        self._reserve = reserve_bytes
        self._candidates_fn = eviction_candidates_fn
        self._unload_fn = unload_fn
        self._footprint_fn = footprint_fn
        self._mem_fn = mem_fn
        self._events: list[EvictionEvent] = []

    async def check(self) -> list[EvictionEvent]:
        """Check memory pressure and evict if needed.

        Returns list of EvictionEvent for each eviction performed.
        """
        available = self._mem_fn()
        if available <= 0:
            return []
        shortfall = self._reserve - available
        if shortfall <= 0:
            return []
        candidates = self._candidates_fn(shortfall)
        events: list[EvictionEvent] = []
        for name in candidates:
            footprint = self._footprint_fn(name)
            try:
                await self._unload_fn(name)
                event = EvictionEvent(name=name, reason="memory_pressure", freed_bytes=footprint)
                events.append(event)
                self._events.append(event)
            except Exception:
                pass
        return events

    @property
    def history(self) -> tuple[EvictionEvent, ...]:
        return tuple(self._events)

async def run_pressure_watch(
    valve: PressureValve,
    interval: float = 5.0,
    stop: asyncio.Event | None = None,
) -> None:
    """Periodically run valve.check(). Runs until stop is set."""
    while True:
        if stop is not None and stop.is_set():
            return
        await asyncio.sleep(interval)
        if stop is not None and stop.is_set():
            return
        await valve.check()
