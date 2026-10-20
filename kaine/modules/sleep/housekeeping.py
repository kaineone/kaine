# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Housekeeping for the sleep phase and the awake floor.

Implements section 3.5 and appendix A.5 of the Kaine paper: reclaim disk
space, oldest data first, until each resource budget is met or the time
allowance expires, and report any excess left over as a term of the
housekeeping pressure. The regenerable data handled here are the rotated
backups of the process log, which are deleted, and the closed daily
study-record files, which are exported to the archive volume under a
SHA-256 checksum; a local study-record copy is removed only once its
archive copy is verified, and unexported study records are never
deleted. Host-memory reclamation is out of scope.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import logging.handlers
import math
import os
import re
import stat
import time
from dataclasses import dataclass
from pathlib import Path, PurePath
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


def _sha256_fd(fd: int) -> str:
    """Return the SHA-256 hex digest of ``fd``, read in 1 MiB chunks.

    The descriptor is read to EOF and is not closed.
    """
    digest = hashlib.sha256()
    while True:
        chunk = os.read(fd, 1024 * 1024)
        if not chunk:
            break
        digest.update(chunk)
    return digest.hexdigest()


def _sha256(path: Path) -> str:
    """Return the SHA-256 hex digest of ``path``, read in 1 MiB chunks."""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    try:
        return _sha256_fd(fd)
    finally:
        os.close(fd)


def rotated_log_backups() -> list[Path]:
    """Return the existing rotated backups of every process log.

    For every ``RotatingFileHandler`` on the root logger with a positive
    ``backupCount``, return the existing regular, non-symlink files
    ``<baseFilename>.1`` ... ``<baseFilename>.<backupCount>``. Backups
    under the protected root are dropped: they are never returned and
    never counted.
    """
    protected = resolve(PROTECTED_ROOT).resolve(strict=False)
    found: list[Path] = []
    for handler in logging.getLogger().handlers:
        if not isinstance(handler, logging.handlers.RotatingFileHandler):
            continue
        if handler.backupCount <= 0:
            continue
        for i in range(1, handler.backupCount + 1):
            candidate = Path(f"{handler.baseFilename}.{i}")
            if os.path.islink(candidate) or not candidate.is_file():
                continue
            if candidate.resolve(strict=False).is_relative_to(protected):
                continue
            found.append(candidate)
    return found


class HousekeepingRefused(ValueError):
    """The requested housekeeping operation cannot proceed safely."""


class ArchiveRefused(HousekeepingRefused):
    """Archive-side refusal for a single file: skip it and continue."""


def _check_archive_path(archive: Path, dest: Path) -> None:
    """Refuse when ``dest`` is unsafe relative to ``archive``."""
    if not dest.is_relative_to(archive):
        raise ArchiveRefused(
            f"archive destination is not under the archive: {dest}"
        )
    archive_resolved = archive.resolve(strict=False)
    dest_resolved = dest.resolve(strict=False)
    if not dest_resolved.is_relative_to(archive_resolved):
        raise ArchiveRefused(
            f"archive destination resolves outside the archive: {dest}"
        )
    rel = dest.relative_to(archive)
    for i in range(1, len(rel.parts) + 1):
        part = archive.joinpath(*rel.parts[:i])
        try:
            st = os.lstat(part)
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(st.st_mode):
            raise ArchiveRefused(
                f"archive destination contains a symlink: {part}"
            )


def _open_archive_dir(archive: Path, rel_dir: PurePath) -> int:
    """Open ``rel_dir`` under ``archive`` without following symlinks.

    Each path component is opened relative to the descriptor of the
    preceding directory. Missing directories are created with mode 0o700.
    A symlink anywhere in the path raises ``ArchiveRefused``.
    """
    if rel_dir.is_absolute():
        raise ArchiveRefused(
            f"archive relative directory must be relative: {rel_dir}"
        )

    opened: list[int] = []
    current = -1
    try:
        current = os.open(archive, os.O_RDONLY | os.O_DIRECTORY)
        for part in rel_dir.parts:
            if part in (".", ".."):
                raise ArchiveRefused(
                    f"invalid archive directory component: {part}"
                )
            try:
                nxt = os.open(
                    part,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                    dir_fd=current,
                )
            except FileNotFoundError:
                try:
                    os.mkdir(part, 0o700, dir_fd=current)
                except FileExistsError:
                    nxt = os.open(
                        part,
                        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                        dir_fd=current,
                    )
                else:
                    nxt = os.open(
                        part,
                        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                        dir_fd=current,
                    )
            opened.append(current)
            current = nxt
        ret = current
        current = -1
        return ret
    except OSError as exc:
        raise ArchiveRefused(
            f"cannot open archive directory: {archive / rel_dir}: {exc}"
        ) from exc
    finally:
        for fd in opened:
            try:
                os.close(fd)
            except OSError:
                pass
        if current >= 0:
            try:
                os.close(current)
            except OSError:
                pass


def _same_file(a: Path, b: Path) -> bool:
    """Return whether the files ``a`` and ``b`` refer to are the same inode.

    Links are followed, which is what the export needs to catch a
    destination that refers to the source.
    """
    try:
        a_stat = os.stat(a)
        b_stat = os.stat(b)
    except OSError:
        return False
    return (a_stat.st_dev, a_stat.st_ino) == (b_stat.st_dev, b_stat.st_ino)


def _unlink_regular(path: Path) -> int:
    """Unlink a regular file and return its size.

    Symlinks and non-regular files raise ``HousekeepingRefused``.
    """
    try:
        st = os.lstat(path)
    except OSError as exc:
        raise HousekeepingRefused(
            f"cannot stat file for deletion: {path}: {exc}"
        ) from exc
    if stat.S_ISLNK(st.st_mode):
        raise HousekeepingRefused(f"symlinks are not allowed: {path}")
    if not stat.S_ISREG(st.st_mode):
        raise HousekeepingRefused(f"not a regular file: {path}")
    os.unlink(path)
    return st.st_size


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
            # The awake floor's keys, validated by kaine.cycle.housekeeping_floor.FloorConfig.
            "reserve_bytes",
            "reserve_share",
            "floor_period_s",
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
    """Execute one housekeeping pass during sleep, and the awake floor."""

    def __init__(
        self,
        config: HousekeepingConfig,
        *,
        roots: Sequence[Path] | None = None,
        protected: Path | None = None,
        memory_reader: Callable[[], Awaitable[int | None]] | None = None,
        episodic_budget_bytes: int | None = None,
        log_backups: Callable[[], list[Path]] | None = None,
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
        self._log_backups = (
            log_backups if log_backups is not None else rotated_log_backups
        )
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

    def _current_log_backups(self) -> set[Path]:
        """Return the resolved paths of the current process-log backups.

        Symlinks, non-regular files, and backups under the protected root
        are dropped.
        """
        found: set[Path] = set()
        for path in self._log_backups():
            path = Path(path)
            if os.path.islink(path) or not path.is_file():
                continue
            resolved = path.resolve(strict=False)
            if resolved.is_relative_to(self._protected):
                continue
            found.add(resolved)
        return found

    def _is_log_backup(self, path: Path) -> bool:
        """Return whether ``path`` is one of the current log backups."""
        resolved = Path(path).resolve(strict=False)
        return resolved in self._current_log_backups()

    def check_allowed(self, path: Path) -> Path:
        """Validate that ``path`` may be moved, deleted, or counted.

        Refuse symlinks (checked on the path as given, before resolving),
        non-regular files, files outside the allowed roots that are not
        current process-log backups, and any file that resolves inside
        the protected root.
        """
        if os.path.islink(path):
            raise HousekeepingRefused(f"symlinks are not allowed: {path}")

        resolved = Path(path).resolve(strict=False)
        if not resolved.is_file():
            raise HousekeepingRefused(f"not a regular file: {resolved}")

        inside_root = any(resolved.is_relative_to(root) for root in self._roots)
        if not inside_root and resolved not in self._current_log_backups():
            raise HousekeepingRefused(f"file is outside allowed roots: {resolved}")

        if resolved.is_relative_to(self._protected):
            raise HousekeepingRefused(
                f"file is inside the protected root: {resolved}"
            )

        return resolved

    def disk_bytes(self) -> int:
        """Return the total bytes of regular files under the allowed roots
        plus the current process-log backups, each file counted once.

        Symlinks are ignored. Missing roots contribute 0 bytes.
        """
        total = 0
        seen: set[Path] = set()
        for root in self._roots:
            if not root.exists():
                continue
            for dirpath, _dirnames, filenames in os.walk(root, followlinks=False):
                for name in filenames:
                    fpath = Path(dirpath) / name
                    if fpath.is_symlink():
                        continue
                    if fpath.is_file():
                        resolved = fpath.resolve(strict=False)
                        if resolved in seen:
                            continue
                        seen.add(resolved)
                        total += fpath.stat().st_size
        for backup in self._current_log_backups():
            if backup in seen:
                continue
            seen.add(backup)
            total += backup.stat().st_size
        return total

    def disk_excess(self) -> float:
        """Return the disk term of the housekeeping pressure right now."""
        return max(0.0, self.disk_bytes() / self._config.disk_budget_bytes - 1.0)

    def candidates(self) -> list[Path]:
        """Return the reclaimable files, oldest first by modification time.

        These are the current process-log backups and the closed daily
        study-record files (dated before today). Files whose names do not
        match the daily pattern and files dated today or in the future
        are excluded. Ties are broken by path string.
        """
        today = self._today()
        found: list[Path] = []
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
                    found.append(candidate)
        found.extend(self._current_log_backups())
        def _mtime(p: Path) -> float:
            try:
                return p.stat().st_mtime
            except OSError:
                return float("inf")

        found.sort(key=lambda p: (_mtime(p), str(p)))
        return found

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
        deleted_files = 0
        deleted_bytes = 0
        skipped_unexported = 0
        archive = self._archive
        remaining = before
        budget = self._config.disk_budget_bytes
        stopped: str | None = None

        if remaining <= budget:
            stopped = "within_budget"
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
                    if self._is_log_backup(src):
                        size = await asyncio.to_thread(self._delete, src)
                        deleted_files += 1
                        deleted_bytes += size
                    elif archive is None:
                        # Unexported study records are never deleted.
                        skipped_unexported += 1
                        continue
                    else:
                        root = next(
                            r for r in self._roots if src.is_relative_to(r)
                        )
                        size = await self._export_to_archive(src, root, archive)
                        moved_files += 1
                        moved_bytes += size
                except ArchiveRefused as exc:
                    logger.warning(
                        "Housekeeping archive refusal for %s: %s", path, exc
                    )
                    continue
                except HousekeepingRefused:
                    raise
                except OSError as exc:
                    logger.warning("Housekeeping skipped %s: %s", path, exc)
                    continue
                remaining -= size

            if stopped is None:
                if remaining <= budget:
                    stopped = "within_budget"
                elif archive is None and skipped_unexported > 0:
                    stopped = "no_archive"
                else:
                    stopped = "no_candidates"

        after = self.disk_bytes()
        mem = await self._read_memory()

        disk_term = 0.0
        if self._config.disk_budget_bytes > 0:
            disk_term = max(0.0, after / self._config.disk_budget_bytes - 1.0)
        memory_term = 0.0
        if mem is not None and self._config.memory_budget_bytes > 0:
            memory_term = max(0.0, mem / self._config.memory_budget_bytes - 1.0)
        episodic_term = 0.0
        if (
            episodic_store_bytes is not None
            and self._episodic_budget_bytes is not None
            and self._episodic_budget_bytes > 0
        ):
            episodic_term = max(
                0.0, episodic_store_bytes / self._episodic_budget_bytes - 1.0
            )
        pressure = disk_term + memory_term + episodic_term

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
            "deleted_files": deleted_files,
            "deleted_bytes": deleted_bytes,
            "stopped": stopped,
            "archive": self._archive is not None,
            "elapsed_s": self._clock() - start,
            "pressure": pressure,
            "terms": {
                "disk": disk_term,
                "memory": memory_term,
                "episodic": episodic_term,
            },
        }

    async def reclaim_regenerable(
        self, *, free_bytes: Callable[[], int], target_free: int, device: int | None = None
    ) -> dict[str, int]:
        """Reclaim spent data for the awake floor, oldest first.

        Deletes process-log backups and local study-record copies whose
        archive copy exists with the same SHA-256, never exporting
        anything and never deleting a study-record file without a
        verified archive copy, until ``free_bytes()`` reaches
        ``target_free``.

        When ``device`` is given, only candidates on that filesystem
        are considered.
        """
        reclaimed_files = 0
        reclaimed_bytes = 0
        archive = self._archive

        for path in self.candidates():
            if free_bytes() >= target_free:
                break
            if device is not None:
                try:
                    if os.stat(path).st_dev != device:
                        continue
                except OSError as exc:
                    logger.warning("Housekeeping skipped %s: %s", path, exc)
                    continue
            try:
                src = self.check_allowed(path)
                if self._is_log_backup(src):
                    size = await asyncio.to_thread(self._delete, src)
                else:
                    if archive is None:
                        continue
                    root = next(
                        r for r in self._roots if src.is_relative_to(r)
                    )
                    if not await asyncio.to_thread(
                        self._archive_copy_verified, src, root, archive
                    ):
                        continue
                    size = await asyncio.to_thread(self._delete, src)
            except ArchiveRefused as exc:
                logger.warning(
                    "Housekeeping archive refusal for %s: %s", path, exc
                )
                continue
            except HousekeepingRefused:
                raise
            except OSError as exc:
                logger.warning("Housekeeping skipped %s: %s", path, exc)
                continue
            reclaimed_files += 1
            reclaimed_bytes += size

        return {
            "reclaimed_files": reclaimed_files,
            "reclaimed_bytes": reclaimed_bytes,
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

    @staticmethod
    def _delete(path: Path) -> int:
        """Unlink ``path`` and return its size in bytes."""
        return _unlink_regular(path)

    @staticmethod
    def _archive_copy_verified(src: Path, root: Path, archive: Path) -> bool:
        """Return whether the archive holds a copy of ``src`` with the
        same SHA-256."""
        dest = archive / root.name / src.relative_to(root)
        try:
            _check_archive_path(archive, dest)
        except ArchiveRefused:
            return False
        if not os.path.lexists(dest):
            return False
        try:
            st = os.lstat(dest)
        except OSError:
            return False
        if not stat.S_ISREG(st.st_mode):
            return False
        if _same_file(dest, src):
            return False
        return _sha256(dest) == _sha256(src)

    async def _export_to_archive(self, src: Path, root: Path, archive: Path) -> int:
        """Copy ``src`` to the archive, verify the checksum, remove the source.

        When the destination already exists with the same SHA-256, the
        local file is a verified-exported copy and is simply removed. A
        destination with different bytes raises ``OSError`` and the local
        file is kept. Returns the number of bytes exported.
        """
        rel = src.relative_to(root)
        dest = archive / root.name / rel

        def _copy_and_remove() -> int:
            src_digest = _sha256(src)
            src_stat = os.lstat(src)

            _check_archive_path(archive, dest)
            if _same_file(dest, src):
                raise ArchiveRefused(
                    f"archive destination is the same file as the source: {dest}"
                )

            dir_fd = _open_archive_dir(
                archive, dest.relative_to(archive).parent
            )
            try:
                # Existing destination: a regular file with the same digest
                # can replace the local copy.
                try:
                    dest_st = os.lstat(dest.name, dir_fd=dir_fd)
                except FileNotFoundError:
                    dest_st = None

                if dest_st is not None:
                    if not stat.S_ISREG(dest_st.st_mode):
                        raise ArchiveRefused(
                            f"archive destination is not a regular file: {dest}"
                        )
                    if (dest_st.st_dev, dest_st.st_ino) == (
                        src_stat.st_dev,
                        src_stat.st_ino,
                    ):
                        raise ArchiveRefused(
                            f"archive destination is the same file as the source: {dest}"
                        )
                    dest_fd = os.open(
                        dest.name,
                        os.O_RDONLY | os.O_NOFOLLOW,
                        dir_fd=dir_fd,
                    )
                    try:
                        if _sha256_fd(dest_fd) == src_digest:
                            return _unlink_regular(src)
                    finally:
                        os.close(dest_fd)
                    raise OSError(f"archive copy differs: {dest}")

                # Remove a leftover temporary file, but refuse anything else.
                temp_name = dest.name + ".part"
                try:
                    temp_st = os.lstat(temp_name, dir_fd=dir_fd)
                except FileNotFoundError:
                    temp_st = None

                if temp_st is not None:
                    if not stat.S_ISREG(temp_st.st_mode):
                        raise ArchiveRefused(
                            f"temporary archive file is not regular: {dest}"
                        )
                    os.unlink(temp_name, dir_fd=dir_fd)

                # Create and copy the temporary file through the directory
                # descriptor so no archive path component is re-traversed by
                # name after the up-front check.
                src_fd = os.open(src, os.O_RDONLY | os.O_NOFOLLOW)
                try:
                    temp_fd = os.open(
                        temp_name,
                        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                        0o600,
                        dir_fd=dir_fd,
                    )
                    try:
                        while True:
                            chunk = os.read(src_fd, 1024 * 1024)
                            if not chunk:
                                break
                            view = memoryview(chunk)
                            while view:
                                written = os.write(temp_fd, view)
                                view = view[written:]
                        os.fsync(temp_fd)
                    finally:
                        os.close(temp_fd)
                finally:
                    os.close(src_fd)

                # Re-open the temp descriptor to apply source metadata.
                temp_fd = os.open(
                    temp_name,
                    os.O_RDONLY | os.O_NOFOLLOW,
                    dir_fd=dir_fd,
                )
                try:
                    os.fchmod(temp_fd, src_stat.st_mode)
                    os.utime(
                        temp_fd,
                        ns=(src_stat.st_atime_ns, src_stat.st_mtime_ns),
                    )
                finally:
                    os.close(temp_fd)

                # Verify the temp file checksum before atomically replacing
                # the destination.
                temp_fd = os.open(
                    temp_name,
                    os.O_RDONLY | os.O_NOFOLLOW,
                    dir_fd=dir_fd,
                )
                try:
                    if _sha256_fd(temp_fd) != src_digest:
                        os.unlink(temp_name, dir_fd=dir_fd)
                        raise OSError(
                            f"checksum mismatch after copying {src} to {dest}"
                        )
                finally:
                    os.close(temp_fd)

                os.replace(
                    temp_name, dest.name, src_dir_fd=dir_fd, dst_dir_fd=dir_fd
                )
                os.fsync(dir_fd)

                # Re-verify the destination after the replace.
                try:
                    dest_st = os.lstat(dest.name, dir_fd=dir_fd)
                except OSError as exc:
                    raise ArchiveRefused(
                        f"cannot re-verify archive destination: {dest}: {exc}"
                    ) from exc
                if not stat.S_ISREG(dest_st.st_mode):
                    raise ArchiveRefused(
                        f"archive destination is not a regular file after move: {dest}"
                    )
                if (dest_st.st_dev, dest_st.st_ino) == (
                    src_stat.st_dev,
                    src_stat.st_ino,
                ):
                    raise ArchiveRefused(
                        f"archive destination is the same file as the source: {dest}"
                    )

                dest_fd = os.open(
                    dest.name,
                    os.O_RDONLY | os.O_NOFOLLOW,
                    dir_fd=dir_fd,
                )
                try:
                    if _sha256_fd(dest_fd) != src_digest:
                        raise ArchiveRefused(
                            f"archive copy checksum changed after move: {dest}"
                        )
                finally:
                    os.close(dest_fd)

                return _unlink_regular(src)
            finally:
                os.close(dir_fd)

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
