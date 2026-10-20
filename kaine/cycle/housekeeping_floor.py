# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Awake floor for sleep housekeeping.

Awake, a floor outside the entity's state keeps free disk space above a
reserve (paper 3.5). It periodically checks each data volume, reclaims
regenerable data oldest first when free space is below the reserve, and
suspends the study record (writing gap markers) if reclaim cannot free
enough space; each action is logged as an operator event (paper A.5,
revised). The floor only calls the housekeeper's reclaim method, which
enforces the allowlist that protects memory stores, the world model,
self-model and identity, voice adapters and preservations.
"""

from __future__ import annotations

import asyncio
import logging
import math
import os
import shutil
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import kaine.storage
from kaine.bus.schema import Event
from kaine.bus.streams import HOUSEKEEPING_SOURCE
from kaine.persistence.study_record_gate import StudyRecordGate, study_record_gate

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class FloorConfig:
    """The awake floor's settings from the ``[sleep.housekeeping]`` table.

    Only the three keys below belong to the floor; every other key of that
    table belongs to the housekeeper and is ignored here.
    """

    reserve_bytes: int = 5 * 1024**3
    reserve_share: float = 0.05
    floor_period_s: float = 60.0

    @classmethod
    def from_section(cls, section: dict | None) -> "FloorConfig":
        """Build the config from the ``[sleep.housekeeping]`` table (None is an empty table)."""
        if section is None:
            section = {}
        if not isinstance(section, dict):
            raise ValueError(f"[sleep.housekeeping] must be a table; got {section!r}")
        reserve_bytes = section.get("reserve_bytes", cls.reserve_bytes)
        if isinstance(reserve_bytes, bool) or not isinstance(reserve_bytes, int) or reserve_bytes < 0:
            raise ValueError(
                f"[sleep.housekeeping] reserve_bytes must be an int >= 0; got {reserve_bytes!r}"
            )
        reserve_share = section.get("reserve_share", cls.reserve_share)
        if (
            isinstance(reserve_share, bool)
            or not isinstance(reserve_share, (int, float))
            or not math.isfinite(reserve_share)
            or reserve_share < 0.0
            or reserve_share >= 1.0
        ):
            raise ValueError(
                f"[sleep.housekeeping] reserve_share must be a finite number in [0, 1); got {reserve_share!r}"
            )
        floor_period_s = section.get("floor_period_s", cls.floor_period_s)
        if (
            isinstance(floor_period_s, bool)
            or not isinstance(floor_period_s, (int, float))
            or not math.isfinite(floor_period_s)
            or floor_period_s <= 0.0
        ):
            raise ValueError(
                f"[sleep.housekeeping] floor_period_s must be a finite number > 0; got {floor_period_s!r}"
            )
        return cls(
            reserve_bytes=reserve_bytes,
            reserve_share=float(reserve_share),
            floor_period_s=float(floor_period_s),
        )


def data_volumes() -> dict[str, Path]:
    """Return the data volumes the floor watches, keyed by label."""
    return {"data": kaine.storage.resolve("data"), "state": kaine.storage.resolve("state")}


class AwakeFloor:
    """Runs the awake housekeeping floor outside the entity's state."""

    def __init__(
        self,
        housekeeper,
        pressure,
        *,
        volumes: Mapping[str, Path],
        reserve_bytes: int,
        reserve_share: float,
        period_s: float,
        is_asleep: Callable[[], bool],
        gate: StudyRecordGate | None = None,
        bus=None,
        disk_usage: Callable[[Path], Any] = shutil.disk_usage,
    ) -> None:
        if isinstance(reserve_bytes, bool) or not isinstance(reserve_bytes, int):
            raise ValueError(f"reserve_bytes must be an int >= 0; got {reserve_bytes!r}")
        if reserve_bytes < 0:
            raise ValueError(f"reserve_bytes must be an int >= 0; got {reserve_bytes!r}")
        if not isinstance(reserve_share, (int, float)) or isinstance(reserve_share, bool):
            raise ValueError(
                f"reserve_share must be a finite number in [0, 1); got {reserve_share!r}"
            )
        if not math.isfinite(reserve_share) or reserve_share < 0.0 or reserve_share >= 1.0:
            raise ValueError(
                f"reserve_share must be a finite number in [0, 1); got {reserve_share!r}"
            )
        if not math.isfinite(period_s) or period_s <= 0.0:
            raise ValueError(f"period_s must be finite and > 0; got {period_s!r}")
        if not volumes:
            raise ValueError("at least one volume must be configured")
        self._housekeeper = housekeeper
        self._pressure = pressure
        self._volumes: Mapping[str, Path] = volumes
        self._reserve_bytes = reserve_bytes
        self._reserve_share = reserve_share
        self._period_s = period_s
        self._is_asleep = is_asleep
        self._gate = gate if gate is not None else study_record_gate()
        self._bus = bus
        self._disk_usage = disk_usage
        self._suspending_volumes: set[str] = set()

    def reserve(self, total: int) -> int:
        """Return the reserve for a volume: the larger of the fixed size and the configured share."""
        return max(self._reserve_bytes, int(self._reserve_share * total))

    async def check_once(self) -> list[dict[str, Any]]:
        """Check each volume once and return the actions taken.

        Actions are also logged as operator events and published on the bus
        when one is available. A publish failure is logged and does not stop
        the floor.
        """
        if self._is_asleep():
            return []

        # Deduplicate volumes that live on the same filesystem.
        seen_devices: set[int] = set()
        unique_volumes: list[tuple[str, Path, int]] = []
        for label, path in self._volumes.items():
            try:
                dev = os.stat(path).st_dev
            except OSError:
                log.warning("volume %s path %s is missing, skipping", label, path)
                continue
            if dev in seen_devices:
                continue
            seen_devices.add(dev)
            unique_volumes.append((label, path, dev))

        actions: list[dict[str, Any]] = []

        for label, path, dev in unique_volumes:
            usage = self._disk_usage(path)
            r = self.reserve(usage.total)
            if usage.free >= r:
                continue

            free_before = usage.free
            result = await self._housekeeper.reclaim_regenerable(
                free_bytes=lambda: self._disk_usage(path).free,
                target_free=2 * r,
                device=dev,
            )
            free_after = self._disk_usage(path).free
            reclaim_action = {
                "action": "reclaim",
                "volume": label,
                "free_bytes_before": free_before,
                "free_bytes_after": free_after,
                "reserve_bytes": r,
                "reclaimed_files": result.get("reclaimed_files", 0),
                "reclaimed_bytes": result.get("reclaimed_bytes", 0),
            }
            actions.append(reclaim_action)
            await self._log_and_publish(reclaim_action)

            self._pressure.note_floor_disk_excess(self._housekeeper.disk_excess())

            if free_after < r:
                already_suspended = self._gate.suspended
                self._suspending_volumes.add(label)
                if not already_suspended:
                    self._gate.suspend()
                    suspend_action = {
                        "action": "suspend",
                        "volume": label,
                        "free_bytes": free_after,
                        "reserve_bytes": r,
                    }
                    actions.append(suspend_action)
                    await self._log_and_publish(suspend_action)

        # Resume the study record once every suspending volume is back at 2R.
        if self._gate.suspended and self._suspending_volumes:
            all_clear = True
            min_free: int | None = None
            max_reserve: int | None = None
            for label in list(self._suspending_volumes):
                path = self._volumes[label]
                usage = self._disk_usage(path)
                r = self.reserve(usage.total)
                if usage.free < 2 * r:
                    all_clear = False
                    break
                if min_free is None or usage.free < min_free:
                    min_free = usage.free
                if max_reserve is None or r > max_reserve:
                    max_reserve = r
            if all_clear:
                self._gate.resume()
                labels = ",".join(sorted(self._suspending_volumes))
                self._suspending_volumes.clear()
                resume_action = {
                    "action": "resume",
                    "volume": labels,
                    "free_bytes": min_free,
                    "reserve_bytes": max_reserve,
                }
                actions.append(resume_action)
                await self._log_and_publish(resume_action)

        return actions

    async def _log_and_publish(self, action: dict[str, Any]) -> None:
        log.warning("housekeeping floor: %s", action)
        if self._bus is None:
            return
        event = Event(
            source=HOUSEKEEPING_SOURCE,
            type="housekeeping.floor",
            payload=action,
            salience=0.05,
            timestamp=datetime.now(timezone.utc),
        )
        try:
            await self._bus.publish(event)
        except Exception:
            log.warning("housekeeping floor publish failed", exc_info=True)

    async def run(self, stop_event: asyncio.Event) -> None:
        """Run the periodic floor until ``stop_event`` is set."""
        while not stop_event.is_set():
            try:
                await self.check_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("housekeeping floor check failed")
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=self._period_s)
            except asyncio.TimeoutError:
                continue
