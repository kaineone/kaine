# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Housekeeping for the sleep phase.

Implements section 3.5 and appendix A.5 of the Kaine paper: reclaim disk
space by archiving the oldest daily study-record JSONL files until each
resource budget is met or the time allowance expires. This first version
handles study records only; regenerable data and host-memory reclamation
are out of scope.
"""

from __future__ import annotations

import asyncio
import logging
import math
import os
import re
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Sequence

from kaine.config import require_known_keys
from kaine.storage import resolve

logger = logging.getLogger(__name__)

ALLOWED_ROOTS: tuple[str, ...] = ("data/evaluation", "data/workspace_trajectory")
PROTECTED_ROOT = "state"
DEFAULT_DISK_BUDGET_BYTES = 10 * 1024**3
DEFAULT_MEMORY_BUDGET_BYTES = 1024**3
DEFAULT_TIME_ALLOWANCE_S = 60.0
DAILY_FILENAME_RE = re.compile(r"^(?P<name>.+)-(?P<date>\d{4}-\d{2}-\d{2})\.jsonl$")


class HousekeepingRefused(ValueError):
    """The requested housekeeping operation cannot proceed safely."""


@dataclass(frozen=True)
class HousekeepingConfig:
    """Configuration for the sleep housekeeping step."""

    enabled: bool = True
    disk_budget_bytes: int = DEFAULT_DISK_BUDGET_BYTES
    memory_budget_bytes: int = DEFAULT_MEMORY_BUDGET_BYTES
    time_allowance_s: float = DEFAULT_TIME_ALLOWANCE_S
    archive_dir: str = ""

    @classmethod
    def from_section(cls, section: dict | None) -> HousekeepingConfig:
        """Load configuration from a ``[sleep.housekeeping]`` table.

        ``None`` is treated as an empty table. A non-dict value raises
        ``ValueError``. Unknown keys, wrong types, or out-of-range values
        also raise ``ValueError`` naming the offending key.
        """
        if section is None:
            section = {}
        if not isinstance(section, dict):
            raise ValueError("[sleep.housekeeping] section must be a table")

        allowed_keys = {
            "enabled",
            "disk_budget_bytes",
            "memory_budget_bytes",
            "time_allowance_s",
            "archive_dir",
        }
        require_known_keys(section, allowed_keys, "[sleep.housekeeping]")

        kwargs: dict[str, Any] = {}

        if "enabled" in section:
            value = section["enabled"]
            if type(value) is not bool:
                raise ValueError(
                    f"[sleep.housekeeping] enabled must be bool: {value!r}"
                )
            kwargs["enabled"] = value

        for key in ("disk_budget_bytes", "memory_budget_bytes"):
            if key in section:
                value = section[key]
                if type(value) is not int or value <= 0:
                    raise ValueError(
                        f"[sleep.housekeeping] {key} must be a positive int: {value!r}"
                    )
                kwargs[key] = value

        if "time_allowance_s" in section:
            value = section["time_allowance_s"]
            if (
                type(value) not in (int, float)
                or not math.isfinite(value)
                or value <= 0
            ):
                raise ValueError(
                    f"[sleep.housekeeping] time_allowance_s must be a finite "
                    f"positive number: {value!r}"
                )
            kwargs["time_allowance_s"] = float(value)

        if "archive_dir" in section:
            value = section["archive_dir"]
            if not isinstance(value, str):
                raise ValueError(
                    f"[sleep.housekeeping] archive_dir must be a string: {value!r}"
                )
            kwargs["archive_dir"] = value

        return cls(**kwargs)


class Housekeeper:
    """Execute one housekeeping pass during sleep."""

    def __init__(
        self,
        config: HousekeepingConfig,
        *,
        roots: Sequence[Path] | None = None,
        protected: Path | None = None,
        memory_reader: Callable[[], Awaitable[int | None]] | None = None,
        episodic_budget_bytes: int | None = None,
        clock: Callable[[], float] = time.monotonic,
        today: Callable[[], str] | None = None,
    ) -> None:
        if roots is None:
            roots = [resolve(r) for r in ALLOWED_ROOTS]
        self._roots = tuple(Path(r).resolve(strict=False) for r in roots)

        if protected is None:
            protected = resolve(PROTECTED_ROOT)
        self._protected = Path(protected).resolve(strict=False)

        self._config = config
        self._memory_reader = memory_reader
        self._episodic_budget_bytes = episodic_budget_bytes
        self._clock = clock
        self._today = today if today is not None else self._default_today

        if config.archive_dir:
            self._archive = Path(config.archive_dir).expanduser().resolve()
            for root in self._roots:
                if self._archive == root or self._archive.is_relative_to(root):
                    raise HousekeepingRefused(
                        f"archive directory lies inside or equals a housekeeping "
                        f"root: {self._archive}"
                    )
            if self._archive == self._protected or self._archive.is_relative_to(
                self._protected
            ):
                raise HousekeepingRefused(
                    f"archive directory lies inside or equals the protected root: "
                    f"{self._archive}"
                )
            for root in self._roots:
                if root.is_relative_to(self._archive):
                    raise HousekeepingRefused(
                        f"archive directory contains a housekeeping root: "
                        f"{self._archive}"
                    )
        else:
            self._archive = None

    @staticmethod
    def _default_today() -> str:
        return time.strftime("%Y-%m-%d", time.gmtime())

    def check_allowed(self, path: Path) -> Path:
        """Validate that ``path`` may be moved or counted.

        Refuse symlinks (checked on the path as given, before resolving),
        non-regular files, files outside the allowed roots, and any file
        that resolves inside the protected root.
        """
        if os.path.islink(path):
            raise HousekeepingRefused(f"symlinks are not allowed: {path}")

        resolved = Path(path).resolve(strict=False)
        if not resolved.is_file():
            raise HousekeepingRefused(f"not a regular file: {resolved}")

        inside_root = any(resolved.is_relative_to(root) for root in self._roots)
        if not inside_root:
            raise HousekeepingRefused(f"file is outside allowed roots: {resolved}")

        if resolved.is_relative_to(self._protected):
            raise HousekeepingRefused(
                f"file is inside the protected root: {resolved}"
            )

        return resolved

    def disk_bytes(self) -> int:
        """Return the total bytes of regular files under the allowed roots.

        Symlinks are ignored. Missing roots contribute 0 bytes.
        """
        total = 0
        for root in self._roots:
            if not root.exists():
                continue
            for dirpath, _dirnames, filenames in os.walk(root, followlinks=False):
                for name in filenames:
                    fpath = Path(dirpath) / name
                    if fpath.is_symlink():
                        continue
                    if fpath.is_file():
                        total += fpath.stat().st_size
        return total

    def candidates(self) -> list[Path]:
        """Return daily files older than today, sorted oldest first.

        Files whose names do not match the daily pattern and files dated
        today or in the future are excluded.
        """
        today = self._today()
        found: list[tuple[str, Path]] = []
        for root in self._roots:
            if not root.exists():
                continue
            for dirpath, _dirnames, filenames in os.walk(root, followlinks=False):
                for name in filenames:
                    match = DAILY_FILENAME_RE.match(name)
                    if not match:
                        continue
                    date = match.group("date")
                    if date >= today:
                        continue
                    candidate = Path(dirpath) / name
                    # A symlink or non-regular file is never a candidate, so
                    # one planted name cannot stop the whole pass.
                    if os.path.islink(candidate) or not candidate.is_file():
                        continue
                    found.append((date, candidate))
        found.sort(key=lambda item: (item[0], str(item[1])))
        return [path for _date, path in found]

    async def run(
        self, *, episodic_store_bytes: int | None = None
    ) -> dict[str, Any]:
        """Run one housekeeping pass and return a content-free report."""
        start = self._clock()
        before = self.disk_bytes()

        if not self._config.enabled:
            return {"enabled": False}

        moved_files = 0
        moved_bytes = 0
        archive = self._archive
        remaining = before
        budget = self._config.disk_budget_bytes
        stopped: str | None = None

        if remaining <= budget:
            stopped = "within_budget"
        elif archive is None:
            stopped = "no_archive"
        else:
            for path in self.candidates():
                if self._clock() - start >= self._config.time_allowance_s:
                    stopped = "time"
                    break
                if remaining <= budget:
                    stopped = "within_budget"
                    break
                try:
                    src = self.check_allowed(path)
                    root = next(r for r in self._roots if src.is_relative_to(r))
                    size = await self._move_to_archive(src, root, archive)
                except HousekeepingRefused:
                    raise
                except OSError as exc:
                    logger.warning("Housekeeping skipped %s: %s", path, exc)
                    continue
                moved_files += 1
                moved_bytes += size
                remaining -= size

            if stopped is None:
                stopped = (
                    "within_budget" if remaining <= budget else "no_candidates"
                )

        after = self.disk_bytes()
        mem = await self._read_memory()

        pressure = 0.0
        if self._config.disk_budget_bytes > 0:
            pressure += max(0.0, after / self._config.disk_budget_bytes - 1.0)
        if mem is not None and self._config.memory_budget_bytes > 0:
            pressure += max(0.0, mem / self._config.memory_budget_bytes - 1.0)
        if (
            episodic_store_bytes is not None
            and self._episodic_budget_bytes is not None
            and self._episodic_budget_bytes > 0
        ):
            pressure += max(
                0.0, episodic_store_bytes / self._episodic_budget_bytes - 1.0
            )

        return {
            "enabled": True,
            "disk_bytes_before": before,
            "disk_bytes_after": after,
            "disk_budget_bytes": self._config.disk_budget_bytes,
            "memory_bytes": mem,
            "memory_budget_bytes": self._config.memory_budget_bytes,
            "episodic_store_bytes": episodic_store_bytes,
            "episodic_budget_bytes": self._episodic_budget_bytes,
            "moved_files": moved_files,
            "moved_bytes": moved_bytes,
            "stopped": stopped,
            "archive": self._archive is not None,
            "elapsed_s": self._clock() - start,
            "pressure": pressure,
        }

    async def _read_memory(self) -> int | None:
        if self._memory_reader is None:
            return None
        try:
            value = await self._memory_reader()
            if isinstance(value, int) and not isinstance(value, bool):
                return value
            return None
        except Exception:
            return None

    async def _move_to_archive(self, src: Path, root: Path, archive: Path) -> int:
        """Copy ``src`` to the archive and remove the source.

        Returns the number of bytes moved.
        """
        rel = src.relative_to(root)
        dest = archive / root.name / rel
        if dest.exists():
            raise HousekeepingRefused(
                f"archive destination already exists: {dest}"
            )

        dest.parent.mkdir(parents=True, exist_ok=True)
        temp = dest.with_suffix(dest.suffix + ".part")
        expected_size = src.stat().st_size

        def _copy_and_remove() -> int:
            shutil.copy2(src, temp)
            fd = os.open(temp, os.O_RDWR)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
            if os.path.getsize(temp) != expected_size:
                os.unlink(temp)
                raise OSError(
                    f"size mismatch after copying {src} to {temp}"
                )
            os.replace(temp, dest)
            src.unlink()
            return expected_size

        return await asyncio.to_thread(_copy_and_remove)


async def bus_memory_bytes(client) -> int | None:
    """Read host memory use from a bus client, if available.

    Calls ``await client.info("memory")`` and returns ``used_memory`` as
    an int when present. Any exception or missing/non-int value yields
    ``None``.
    """
    try:
        info = await client.info("memory")
        value = info.get("used_memory") if isinstance(info, dict) else None
        if isinstance(value, int) and not isinstance(value, bool):
            return value
        return None
    except Exception:
        return None
