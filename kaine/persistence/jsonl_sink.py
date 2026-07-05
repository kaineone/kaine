# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Async JSONL sink with daily rotation + retention.

A generic, dependency-light persistence primitive: writes go through an
asyncio.Queue and a background flush task batches them out, so the caller is
never blocked on disk I/O. Each line is AES-256-GCM-encrypted when state
encryption is enabled. Used by the evaluation sidecar observers and by the
cycle's Spot incident log; it depends only on stdlib, ``kaine.security.crypto``
(a lazy import), and ``kaine.experiment.run_context`` (stdlib-only, for record
stamping), so importing it never pulls in the evaluation subsystem.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from kaine.experiment.run_context import get_run_context

log = logging.getLogger(__name__)


def _utc_date_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


class AsyncJsonlSink:
    """Writes JSON-serializable dicts as JSONL into a daily-rotated file.

    Sample usage:
        sink = AsyncJsonlSink(Path("data/evaluation/trajectory"))
        await sink.start()
        await sink.write({"tick": 1})  # returns immediately
        await sink.stop()

    Files are named `<name>-<UTC-date>.jsonl` under `dir_path`. The
    directory is created if it doesn't exist. Files older than
    `retention_days` are deleted on `start()` and on each rotation.
    """

    def __init__(
        self,
        dir_path: Path | str,
        *,
        name: str = "log",
        retention_days: int = 30,
        flush_interval_s: float = 0.5,
        queue_maxsize: int = 4096,
    ) -> None:
        self._dir = Path(dir_path)
        self._name = str(name)
        self._retention_days = int(retention_days)
        self._flush_interval_s = float(flush_interval_s)
        self._queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=queue_maxsize)
        self._task: asyncio.Task[None] | None = None
        self._stopped = asyncio.Event()
        self._current_date: str | None = None
        self._current_path: Path | None = None
        self._dropped_count = 0
        self._wrote_count = 0
        # Per-sink monotonic record counter, stamped onto every record while a
        # run context is set (run-identity / completeness gating). Starts at 0;
        # only advances when a context exists, so it is inert outside a run.
        self._seq = 0

    @property
    def directory(self) -> Path:
        return self._dir

    @property
    def name(self) -> str:
        return self._name

    @property
    def wrote_count(self) -> int:
        return self._wrote_count

    @property
    def dropped_count(self) -> int:
        return self._dropped_count

    async def start(self) -> None:
        if self._task is not None:
            return
        self._dir.mkdir(parents=True, exist_ok=True)
        self._enforce_retention()
        self._stopped.clear()
        self._task = asyncio.create_task(self._run(), name=f"jsonl-sink-{self._name}")

    async def stop(self) -> None:
        self._stopped.set()
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=5.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                self._task.cancel()
            self._task = None
        await self._flush_remaining()

    def _stamp(self, entry: dict[str, Any]) -> dict[str, Any]:
        """Stamp run identity onto a record when a run context is active.

        Returns the record to persist. When a context is set, the record carries
        the run's ``run_id`` (without clobbering an explicit one) and a per-sink
        monotonic ``seq`` (from 0); stamping is done on a shallow copy so the
        caller's dict is never mutated. When no context is set this is a no-op
        pass-through — neither ``run_id`` nor ``seq`` is added — keeping the unit
        suite and disabled deployments byte-for-byte unchanged.
        """
        ctx = get_run_context()
        if ctx is None:
            return entry
        stamped = dict(entry)
        stamped.setdefault("run_id", ctx.run_id)
        stamped["seq"] = self._seq
        self._seq += 1
        return stamped

    async def write(self, entry: dict[str, Any]) -> None:
        """Returns immediately. Drops oldest if queue is full."""
        entry = self._stamp(entry)
        try:
            self._queue.put_nowait(entry)
        except asyncio.QueueFull:
            self._dropped_count += 1
            # Drop oldest, push newest — observers care more about recent state.
            try:
                self._queue.get_nowait()
                self._queue.put_nowait(entry)
            except (asyncio.QueueEmpty, asyncio.QueueFull):
                # Benign best-effort drop: a concurrent drain emptied or refilled
                # the queue between the calls above. Losing one record under
                # backpressure is acceptable (the entry was already counted as
                # dropped), so swallow the race rather than raise into the caller.
                pass

    def write_sync(self, entry: dict[str, Any]) -> None:
        """For test code only — bypasses the async path."""
        entry = self._stamp(entry)
        path = self._target_path()
        with path.open("a", encoding="utf-8") as fh:
            fh.write(self._encode_line(entry) + "\n")

    def _encode_line(self, entry: dict[str, Any]) -> str:
        """Serialize one record to a JSONL line, AES-256-GCM-encrypting it when
        state encryption is enabled (each line is its own envelope so append
        and daily rotation keep working unchanged)."""
        from kaine.security.crypto import get_state_encryptor

        line = json.dumps(entry, default=str)
        return get_state_encryptor().encrypt_text(line)

    async def _run(self) -> None:
        try:
            while not self._stopped.is_set():
                await asyncio.sleep(self._flush_interval_s)
                await self._drain_once()
            await self._drain_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("AsyncJsonlSink %s crashed", self._name)

    async def _flush_remaining(self) -> None:
        try:
            await self._drain_once()
        except Exception:
            log.warning("final flush failed for %s", self._name, exc_info=True)

    async def _drain_once(self) -> None:
        batch: list[dict[str, Any]] = []
        while not self._queue.empty():
            try:
                batch.append(self._queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        if not batch:
            return
        path = self._target_path()
        try:
            # The per-line encrypt + file write is blocking CPU/disk work; run it
            # off the event loop so a hot sink (e.g. the per-tick trajectory
            # observer) never stalls the cognitive cycle.
            await asyncio.to_thread(self._encode_and_append, path, batch)
            self._wrote_count += len(batch)
        except Exception:
            log.exception("AsyncJsonlSink %s failed to write %d entries", self._name, len(batch))

    def _encode_and_append(self, path: Path, batch: list[dict[str, Any]]) -> None:
        """Encode (encrypt) and append a batch of records. Blocking; thread-run."""
        with path.open("a", encoding="utf-8") as fh:
            for entry in batch:
                fh.write(self._encode_line(entry) + "\n")

    def _target_path(self) -> Path:
        today = _utc_date_str()
        if today != self._current_date or self._current_path is None:
            if self._current_date is not None:
                # Rotation event — enforce retention again so yesterday's
                # file is purged if it falls out of the window.
                self._enforce_retention()
            self._current_date = today
            self._current_path = self._dir / f"{self._name}-{today}.jsonl"
        return self._current_path

    def _enforce_retention(self) -> None:
        # ``retention_days <= 0`` is the explicit "no-purge" signal: the Spot
        # incident log (kaine/cycle/incident_log.py) constructs this sink with
        # ``retention_days=0`` so research history is NEVER auto-deleted. Do not
        # remove this short-circuit without auditing that contract.
        if self._retention_days <= 0 or not self._dir.exists():
            return
        cutoff = time.time() - (self._retention_days * 86400)
        for entry in self._dir.iterdir():
            if not entry.is_file() or entry.suffix != ".jsonl":
                continue
            if not entry.name.startswith(f"{self._name}-"):
                continue
            try:
                if entry.stat().st_mtime < cutoff:
                    entry.unlink()
            except OSError:
                log.warning("could not purge %s", entry, exc_info=True)
