# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Content-free utterance-outcome observer for voice alignment research.

Watches ``lingua.external`` (external utterances), ``audition.out`` (operator
replies), ``empatheia.out`` (social deviation) and ``thymos.out`` (social
drive). For every external utterance it writes one record containing only
metrics, never transcript text.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from kaine.bus.schema import OPERATOR_SOURCES, Event, module_stream

log = logging.getLogger("kaine.cycle.utterance_outcome")

DEFAULT_REPLY_WINDOW_S = 30.0


def _warn_outcome_reply_window(value: object) -> None:
    log.warning(
        "outcome_reply_window_s must be a finite number > 0 (got %s); using %.0f s",
        type(value).__name__,
        DEFAULT_REPLY_WINDOW_S,
    )


def reply_window_from_lingua(lingua_section: object) -> float:
    """Return a safe reply-window from the ``lingua`` config table.

    Falls back to :data:`DEFAULT_REPLY_WINDOW_S` and logs a single warning
    for any invalid value.  The observer is content-free and must never raise.
    """
    if not isinstance(lingua_section, dict):
        return DEFAULT_REPLY_WINDOW_S

    value = lingua_section.get("outcome_reply_window_s", DEFAULT_REPLY_WINDOW_S)
    if isinstance(value, bool):
        _warn_outcome_reply_window(value)
        return DEFAULT_REPLY_WINDOW_S

    candidate: float
    if isinstance(value, (int, float)):
        candidate = float(value)
    elif isinstance(value, str):
        try:
            candidate = float(value)
        except (ValueError, TypeError):
            _warn_outcome_reply_window(value)
            return DEFAULT_REPLY_WINDOW_S
    else:
        _warn_outcome_reply_window(value)
        return DEFAULT_REPLY_WINDOW_S

    if not math.isfinite(candidate) or candidate <= 0.0:
        _warn_outcome_reply_window(value)
        return DEFAULT_REPLY_WINDOW_S

    return candidate


# Produced by Lingua: each external_speech event opens one outcome record.
LINGUA_EXTERNAL = "lingua.external"
AUDITION_OUT = module_stream("audition")
EMPATHEIA_OUT = module_stream("empatheia")
THYMOS_OUT = module_stream("thymos")

STREAMS = (LINGUA_EXTERNAL, AUDITION_OUT, EMPATHEIA_OUT, THYMOS_OUT)


@dataclass
class _OpenRecord:
    record_id: str
    start_ts: float
    baseline_social_drive: Optional[float]
    latest_social_drive: Optional[float]
    max_empatheia_deviation: Optional[float]


async def start_utterance_outcome_observer(
    bus,
    *,
    path: Path,
    lingua_section: object = None,
    **kwargs: Any,
) -> UtteranceOutcomeObserver | None:
    """Construct and start the observer, returning None if it cannot boot.

    This helper is used by the cycle boot so that a failure to start the
    content-free observer never aborts launch.
    """
    try:
        if "reply_window_s" not in kwargs:
            kwargs["reply_window_s"] = reply_window_from_lingua(lingua_section)
        observer = UtteranceOutcomeObserver(bus, path=path, **kwargs)
        await observer.start()
    except Exception as exc:
        log.warning(
            "utterance-outcome observer disabled: could not start (%s)",
            exc,
            exc_info=True,
        )
        return None
    return observer


class UtteranceOutcomeObserver:
    """Cycle-layer observer that writes one content-free record per external
    utterance, from bus events only.
    """

    def __init__(
        self,
        bus,
        *,
        path: Path,
        reply_window_s: float = 30.0,
        poll_interval_s: float = 0.1,
        now: Callable[[], float] = time.time,
    ):
        self._bus = bus
        self._path = Path(path)
        self._reply_window_s = float(reply_window_s)
        self._poll_interval_s = float(poll_interval_s)
        self._now = now
        self._task: Optional[asyncio.Task] = None
        self._cursors: dict[str, str] = {}
        self._latest_social_drive: Optional[float] = None
        self._open_record: Optional[_OpenRecord] = None

    @property
    def pending_count(self) -> int:
        """Number of utterance records currently open (0 or 1)."""
        return 1 if self._open_record is not None else 0

    async def start(self) -> None:
        """Seed cursors at the tail of every watched stream and begin polling."""
        for stream in STREAMS:
            self._cursors[stream] = await self._bus.last_entry_id(stream)
        self._task = asyncio.create_task(
            self._run(), name="utterance_outcome_observer"
        )

    async def stop(self) -> None:
        """Cancel the polling loop and drop any open record without writing."""
        if self._task is not None and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass  # expected: we just cancelled it
            except Exception:
                log.warning(
                    "utterance outcome observer task raised during shutdown",
                    exc_info=True,
                )
        if self._open_record is not None:
            log.info(
                "utterance outcome: dropped %d open record(s) at shutdown",
                1,
            )
            self._open_record = None

    async def _run(self) -> None:
        while True:
            try:
                await self._poll()
            except asyncio.CancelledError:
                break
            except Exception:
                log.exception("utterance outcome observer poll failed")
            try:
                await asyncio.sleep(self._poll_interval_s)
            except asyncio.CancelledError:
                break

    async def _poll(self) -> None:
        merged: list[tuple[str, str, Event]] = []
        for stream in STREAMS:
            try:
                entries, last_scanned = await self._bus.read_entries(
                    stream,
                    last_id=self._cursors.get(stream, "0-0"),
                    count=64,
                    block_ms=0,
                )
            except Exception:
                log.warning("failed to read stream %s", stream, exc_info=True)
                continue
            if last_scanned is not None:
                self._cursors[stream] = last_scanned
            for entry_id, event in entries:
                merged.append((stream, entry_id, event))
        merged.sort(key=lambda se: se[2].timestamp.timestamp())
        for stream, entry_id, event in merged:
            try:
                await self._handle_event(stream, event)
            except Exception:
                log.debug(
                    "failed to handle %s event %s; skipping",
                    stream,
                    entry_id,
                    exc_info=True,
                )
        await self._check_expiry()

    async def _handle_event(self, stream: str, event: Event) -> None:
        ts = event.timestamp.timestamp()
        if stream == LINGUA_EXTERNAL and event.type == "external_speech":
            record_id = event.payload.get("record_id")
            if (
                isinstance(record_id, str)
                and re.fullmatch(r"[0-9a-f]{32}", record_id) is not None
            ):
                await self._open_record_if_new(record_id, ts)
            else:
                log.debug(
                    "ignoring external_speech with invalid record_id (type=%s, len=%s)",
                    type(record_id).__name__,
                    len(record_id) if isinstance(record_id, str) else -1,
                )
        elif stream == AUDITION_OUT and event.type == "audition.transcription":
            await self._maybe_reply(event, ts)
        elif stream == EMPATHEIA_OUT and event.type == "empatheia.social_error":
            await self._maybe_empatheia(event, ts)
        elif stream == THYMOS_OUT and event.type == "thymos.state":
            await self._maybe_thymos(event, ts)

    async def _open_record_if_new(self, record_id: str, ts: float) -> None:
        if self._open_record is not None:
            # The next utterance preempts the open one only if it came inside
            # that one's window; otherwise the window had already run out
            # unanswered (a batch can hold both).
            expired = ts - self._open_record.start_ts > self._reply_window_s
            await self._close_open(
                preempted=not expired, replied=False, reply_latency_s=None
            )
        self._open_record = _OpenRecord(
            record_id=record_id,
            start_ts=ts,
            baseline_social_drive=self._latest_social_drive,
            latest_social_drive=self._latest_social_drive,
            max_empatheia_deviation=None,
        )

    async def _maybe_reply(self, event: Event, ts: float) -> None:
        if self._open_record is None:
            return
        payload = event.payload
        source_label = payload.get("source_label")
        if source_label not in OPERATOR_SOURCES:
            return
        text = payload.get("text")
        if not isinstance(text, str) or not text.strip():
            return
        if ts - self._open_record.start_ts > self._reply_window_s:
            return
        latency = max(0.0, ts - self._open_record.start_ts)
        await self._close_open(
            preempted=False, replied=True, reply_latency_s=latency
        )

    async def _maybe_empatheia(self, event: Event, ts: float) -> None:
        if self._open_record is None:
            return
        magnitude = event.payload.get("deviation_magnitude")
        if not isinstance(magnitude, (int, float)) or not math.isfinite(magnitude):
            return
        if ts - self._open_record.start_ts > self._reply_window_s:
            return
        current = self._open_record.max_empatheia_deviation
        if current is None or magnitude > current:
            self._open_record.max_empatheia_deviation = float(magnitude)

    async def _maybe_thymos(self, event: Event, ts: float) -> None:
        drives = event.payload.get("drives") or {}
        value = drives.get("social_drive")
        if not isinstance(value, (int, float)) or not math.isfinite(value):
            return
        self._latest_social_drive = float(value)
        if self._open_record is None:
            return
        if ts - self._open_record.start_ts > self._reply_window_s:
            return
        self._open_record.latest_social_drive = float(value)

    async def _check_expiry(self) -> None:
        if self._open_record is None:
            return
        if self._now() - self._open_record.start_ts > self._reply_window_s:
            await self._close_open(
                preempted=False, replied=False, reply_latency_s=None
            )

    async def _close_open(
        self,
        *,
        preempted: bool,
        replied: bool,
        reply_latency_s: Optional[float],
    ) -> None:
        if self._open_record is None:
            return
        rec = self._open_record
        delta: Optional[float] = None
        if (
            rec.latest_social_drive is not None
            and rec.baseline_social_drive is not None
        ):
            delta = rec.latest_social_drive - rec.baseline_social_drive
        record = {
            "record_id": rec.record_id,
            "replied": replied,
            "reply_latency_s": reply_latency_s,
            "empatheia_deviation": rec.max_empatheia_deviation,
            "social_drive_delta": delta,
            "preempted": preempted,
        }
        await self._write_record(record)
        self._open_record = None

    async def _write_record(self, record: dict[str, Any]) -> None:
        await asyncio.to_thread(self._write_record_sync, record)

    def _write_record_sync(self, record: dict[str, Any]) -> None:
        line = json.dumps(record, sort_keys=True) + "\n"
        try:
            self._path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            try:
                os.chmod(self._path.parent, 0o700)
            except OSError:
                # Best effort: some filesystems refuse chmod; the file itself is
                # still made owner-only below.
                log.debug("could not tighten %s to 0700", self._path.parent)
            fd = os.open(
                self._path,
                os.O_APPEND | os.O_CREAT | os.O_WRONLY,
                0o600,
            )
            try:
                # An existing file keeps its old mode on open; tighten it.
                os.fchmod(fd, 0o600)
                os.write(fd, line.encode("utf-8"))
                os.fsync(fd)
            finally:
                os.close(fd)
        except Exception:
            log.exception(
                "failed to write utterance outcome record to %s", self._path
            )
