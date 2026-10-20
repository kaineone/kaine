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

When 2R does not fit the volume, the floor reclaims to the midpoint
between R and the volume size so that reclaim has a reachable target.
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
        if (
            isinstance(reserve_bytes, bool)
            or not isinstance(reserve_bytes, int)
            or reserve_bytes <= 0
        ):
            raise ValueError(
                f"[sleep.housekeeping] reserve_bytes must be an int > 0; got {reserve_bytes!r}"
            )
        reserve_share = section.get("reserve_share", cls.reserve_share)
        if (
            isinstance(reserve_share, bool)
            or not isinstance(reserve_share, (int, float))
            or not math.isfinite(reserve_share)
            or reserve_share <= 0.0
            or reserve_share >= 1.0
        ):
            raise ValueError(
                f"[sleep.housekeeping] reserve_share must be a finite number in (0, 1); got {reserve_share!r}"
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


def data_volumes(kaine_config: Mapping[str, Any] | None = None) -> dict[str, Path]:
    """Return the data volumes the floor watches, keyed by label.

    Includes the directories every study sink writes to: evaluation logs,
    trajectory workspace, research event logs, external utterance logs,
    dashboard records, raw bus archives and the state root. Defaults are
    used when a section is absent. Volumes that live on the same filesystem
    are still checked once.
    """
    if kaine_config is None:
        kaine_config = {}
    volumes: dict[str, Path] = {}
    eval_paths = (kaine_config.get("evaluation") or {}).get("paths") or {}
    volumes["evaluation"] = kaine.storage.resolve(
        str(eval_paths.get("evaluation_logs", "data/evaluation"))
    )
    volumes["trajectory"] = kaine.storage.resolve(
        str(eval_paths.get("trajectory_dir", "data/workspace_trajectory"))
    )
    rel = kaine_config.get("research_event_log") or {}
    if rel.get("log_dir"):
        volumes["research_events"] = kaine.storage.resolve(str(rel["log_dir"]))
    ext = rel.get("external_utterances") or {}
    if ext.get("log_dir"):
        volumes["external_utterances"] = kaine.storage.resolve(str(ext["log_dir"]))
    dash = rel.get("dashboard_record") or {}
    if dash.get("log_dir"):
        volumes["dashboard_record"] = kaine.storage.resolve(str(dash["log_dir"]))
    raw = rel.get("raw_archive") or {}
    raw_dir = raw.get("archive_dir")
    if raw_dir:
        volumes["raw_bus_archive"] = kaine.storage.resolve(str(raw_dir))
    volumes["state"] = kaine.storage.resolve("state")
    return volumes


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

    def target(self, total: int) -> int:
        """Reachable free-space target for a volume.

        The paper's target is 2R. When 2R does not fit on the volume, fall
        back to the midpoint between R and the volume size so reclaiming has
        a definite stopping point.
        """
        r = self.reserve(total)
        return min(2 * r, (total + r) // 2)

    def validate_volumes(self) -> None:
        """Raise ValueError if any existing volume can never satisfy its reserve."""
        for label, path in self._volumes.items():
            try:
                usage = self._disk_usage(path)
            except OSError:
                continue
            r = self.reserve(usage.total)
            if r >= usage.total:
                raise ValueError(
                    f"volume {label!r} at {path} has size {usage.total} "
                    f"but reserve is {r}"
                )

    async def check_once(self) -> list[dict[str, Any]]:
        """Check each volume once and return the actions taken.

        The floor reclaims to the paper's 2R target whenever 2R fits the
        volume; otherwise it reclaims to the midpoint between R and the
        volume size. Actions are also logged as operator events and
        published on the bus when one is available. A publish failure is
        logged and does not stop the floor.
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
            if self._is_asleep():
                break
            try:
                usage = self._disk_usage(path)
                r = self.reserve(usage.total)
                if usage.free >= r:
                    continue

                target = self.target(usage.total)
                free_before = usage.free
                result = await self._housekeeper.reclaim_regenerable(
                    free_bytes=lambda: self._disk_usage(path).free,
                    target_free=target,
                    device=dev,
                )
                free_after = self._disk_usage(path).free
                reclaim_action = {
                    "action": "reclaim",
                    "volume": label,
                    "free_bytes_before": free_before,
                    "free_bytes_after": free_after,
                    "reserve_bytes": r,
                    "target_free_bytes": target,
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
            except Exception:
                log.exception("housekeeping floor: reclaim failed for volume %s", label)

        # Resume the study record once every suspending volume is back at its target.
        if self._gate.suspended and self._suspending_volumes:
            all_clear = True
            min_free: int | None = None
            max_reserve: int | None = None
            for label in list(self._suspending_volumes):
                path = self._volumes[label]
                try:
                    usage = self._disk_usage(path)
                except OSError:
                    # A volume that cannot be read now keeps the record suspended.
                    log.warning(
                        "housekeeping floor: cannot read volume %s for resume", label, exc_info=True
                    )
                    all_clear = False
                    break
                r = self.reserve(usage.total)
                target = self.target(usage.total)
                if usage.free < target:
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
