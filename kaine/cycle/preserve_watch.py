# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Operator-requested live preservation watcher.

A cycle-layer task polls ``state/cycle/preserve_request.json``. When a new
``request_id`` appears it pushes a freeze, waits for the cycle to pause, runs
:func:`kaine.lifecycle.preservation.preserve_live`, writes the result to
``state/cycle/preserve_result.json``, and either lifts the freeze or stops
the entity.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable

from kaine.cycle.control_state import pop_freeze, push_freeze
from kaine.state_io import write_json_atomic

log = logging.getLogger(__name__)

PRESERVE_FREEZE_SOURCE = "preserve"
REQUEST_PATH = Path("state/cycle/preserve_request.json")
RESULT_PATH = Path("state/cycle/preserve_result.json")

_REQUEST_ID_RE = re.compile(r"^[0-9a-f]{32}$")


@dataclass(frozen=True)
class PreserveRequest:
    request_id: str
    reason: str
    stop: bool
    requested_at: str


def new_request(reason: str, stop: bool) -> PreserveRequest:
    """Create a new, uniquely identified preservation request."""
    return PreserveRequest(
        request_id=secrets.token_hex(16),
        reason=reason,
        stop=stop,
        requested_at=datetime.now(timezone.utc).isoformat(),
    )


def write_request(req: PreserveRequest, path: Path | None = None) -> None:
    """Write a preservation request atomically."""
    payload = {
        "request_id": req.request_id,
        "reason": req.reason,
        "stop": req.stop,
        "requested_at": req.requested_at,
    }
    write_json_atomic(path or REQUEST_PATH, payload)


def read_request(path: Path | None = None) -> PreserveRequest | None:
    """Read a preservation request, or ``None`` if missing or malformed."""
    target = path or REQUEST_PATH
    if not target.exists():
        return None
    try:
        data = json.loads(target.read_text())
    except (json.JSONDecodeError, OSError):
        return None

    request_id = data.get("request_id")
    reason = data.get("reason")
    stop = data.get("stop")
    requested_at = data.get("requested_at")
    if (
        not isinstance(request_id, str)
        or not _REQUEST_ID_RE.match(request_id)
        or not isinstance(reason, str)
        or not isinstance(stop, bool)
        or not isinstance(requested_at, str)
    ):
        return None

    return PreserveRequest(
        request_id=request_id,
        reason=reason,
        stop=stop,
        requested_at=requested_at,
    )


def write_result(result: dict, path: Path | None = None) -> None:
    """Write a preservation result atomically."""
    write_json_atomic(path or RESULT_PATH, result)


def read_result(path: Path | None = None) -> dict | None:
    """Read a preservation result, or ``None`` if missing or malformed."""
    target = path or RESULT_PATH
    if not target.exists():
        return None
    try:
        data = json.loads(target.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class PreserveRequestWatcher:
    def __init__(
        self,
        *,
        preserve: Callable[[str], Awaitable[Any]],
        bundle_for: Callable[[Any], str],
        is_paused: Callable[[], bool],
        request_stop: Callable[[], None],
        request_path: Path | None = None,
        result_path: Path | None = None,
        control_path: Path | None = None,
        poll_seconds: float = 1.0,
        pause_timeout_seconds: float = 5.0,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._preserve = preserve
        self._bundle_for = bundle_for
        self._is_paused = is_paused
        self._request_stop = request_stop
        self._request_path = request_path or REQUEST_PATH
        self._result_path = result_path or RESULT_PATH
        self._control_path = control_path
        self._poll_seconds = poll_seconds
        self._pause_timeout_seconds = pause_timeout_seconds
        self._clock = clock
        self._sleep = sleep

        # A restart must never re-handle an already-recorded request.
        self._last_handled_id: str | None = None
        prior = read_result(self._result_path)
        if isinstance(prior, dict):
            self._last_handled_id = prior.get("request_id")

        # A failed freeze release is retried at the start of the next step.
        self._release_pending = False

    async def step(self) -> None:
        """Handle one poll of the request file.

        If a prior freeze release failed, retry it first. If it fails again,
        defer request handling to the next poll; once it succeeds, continue the
        poll loop and let the next step handle any new request.
        """
        if self._release_pending:
            try:
                pop_freeze(self._control_path, source=PRESERVE_FREEZE_SOURCE)
            except Exception:
                log.error("could not release pending preserve freeze", exc_info=True)
                return
            self._release_pending = False
            return

        req = read_request(self._request_path)
        if req is None:
            return
        if req.request_id == self._last_handled_id:
            return

        reason = req.reason
        push_freeze(
            reason=f"preserve: {reason}",
            path=self._control_path,
            source=PRESERVE_FREEZE_SOURCE,
        )

        # Wait for the freeze-watch loop to pause the cycle, up to the timeout.
        deadline = self._clock() + self._pause_timeout_seconds
        while self._clock() < deadline:
            if self._is_paused():
                break
            await self._sleep(0.1)

        ok = False
        preservation_id: str | None = None
        bundle: str | None = None
        error: str | None = None
        try:
            result = await self._preserve(reason)
            ok = bool(getattr(result, "ok", False))
            preservation_id = getattr(result, "preservation_id", None)
            bundle = self._bundle_for(result)
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"

        result_payload = {
            "request_id": req.request_id,
            "ok": ok,
            "preservation_id": preservation_id,
            "bundle": bundle,
            "error": error,
            "finished_at": _utc_iso(),
        }
        # Mark the request handled first and release the freeze whatever
        # happens to the result file: a failed result write must never leave a
        # stale preserve freeze, nor let the next poll push another one.
        self._last_handled_id = req.request_id
        try:
            write_result(result_payload, self._result_path)
        except Exception:
            log.error("could not write the preserve result", exc_info=True)
        finally:
            if ok and req.stop:
                try:
                    self._request_stop()
                except Exception:
                    log.error(
                        "could not request stop after preserve",
                        exc_info=True,
                    )
            else:
                try:
                    pop_freeze(self._control_path, source=PRESERVE_FREEZE_SOURCE)
                except Exception:
                    log.error("could not release preserve freeze", exc_info=True)
                    self._release_pending = True

    async def run(self, stop_event: asyncio.Event) -> None:
        """Poll until ``stop_event`` is set."""
        while not stop_event.is_set():
            try:
                await self.step()
            except Exception as exc:
                log.warning("Preserve watcher step failed: %s", exc, exc_info=True)
            await self._sleep(self._poll_seconds)
