# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Caretaker notifier task and best-effort event sender for unattended runs.

Manages the durable start/acknowledgement lifecycle and repeats a reminder
notice until an operator acknowledges the start in Nexus. Running notices
(Spot escalation, supervision loss, welfare response, boot failure) are sent
best-effort and never stop the entity.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from kaine.cycle.caretaker import CaretakerConfig, ChannelResult, build_notice, notify
from kaine.cycle.caretaker_state import (
    ACK_PATH,
    START_PATH,
    CaretakerStart,
    is_acknowledged,
    read_ack,
    read_start,
    write_start,
)
from kaine.cycle.incident_log import IncidentLog

log = logging.getLogger("kaine.cycle.caretaker_runtime")


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class CaretakerNotifier:
    def __init__(
        self,
        config: CaretakerConfig,
        *,
        start_path: Path | None = None,
        ack_path: Path | None = None,
        log_path: str = "state/cycle/caretaker",
        notify_fn=notify,
        secrets_path: Path = Path("config/secrets.toml"),
        poll_s: float = 5.0,
        clock=time.monotonic,
    ) -> None:
        self._config = config
        self._start_path = start_path or START_PATH
        self._ack_path = ack_path or ACK_PATH
        self._log = IncidentLog(enabled=True, path=log_path, name="caretaker")
        self._notify_fn = notify_fn
        self._secrets_path = secrets_path
        self._poll_s = poll_s
        self._clock = clock
        self._deadline = 0.0
        self._ack_recorded = False

    async def start(self) -> str:
        await self._log.start()
        start_id = uuid.uuid4().hex
        write_start(
            CaretakerStart(start_id=start_id, started_at=_utc_iso()),
            path=self._start_path,
        )
        await self._log.write({"transition": "start", "start_id": start_id})
        self._deadline = self._clock() + self._config.reminder_interval_s
        return start_id

    async def run(self, stop_event: asyncio.Event) -> None:
        while not stop_event.is_set():
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=self._poll_s)
            except asyncio.TimeoutError:
                pass
            else:
                break
            # Cancellation propagates: shutdown cancels this task and awaits it.
            try:
                await self._tick()
            except Exception:
                log.warning("caretaker notifier tick failed", exc_info=True)

    async def _tick(self) -> None:
        start = read_start(self._start_path)
        ack = read_ack(self._ack_path)
        if is_acknowledged(start, ack):
            if not self._ack_recorded:
                await self._log.write(
                    {
                        "transition": "acknowledged",
                        "start_id": ack.start_id,
                        "acknowledged_at": ack.acknowledged_at,
                    }
                )
                self._ack_recorded = True
            return
        if start is None:
            return
        if self._clock() >= self._deadline:
            await self.send_event("reminder")
            self._deadline += self._config.reminder_interval_s

    async def send_event(self, event: str) -> list[ChannelResult]:
        try:
            notice = build_notice(event, self._config)
            results = await asyncio.to_thread(
                self._notify_fn,
                self._config,
                notice,
                secrets_path=self._secrets_path,
            )
            accepted = [r.kind for r in results if r.accepted]
            await self._log.write(
                {"transition": "notice", "event": event, "accepted": accepted}
            )
            return results
        except Exception as exc:
            log.warning(
                "caretaker send_event failed: %s", type(exc).__name__
            )
            return []

    async def stop(self) -> None:
        await self._log.stop()


def send_event_best_effort(
    caretaker_section: dict | None,
    event: str,
    *,
    notify_fn=notify,
    secrets_path: Path = Path("config/secrets.toml"),
) -> None:
    """Best-effort caretaker event outside the event loop.

    Invalid or channel-less config is ignored. A failed send is logged and
    never propagated.
    """
    if caretaker_section is None:
        return
    try:
        cfg = CaretakerConfig.from_section(caretaker_section)
    except Exception:
        return
    if not cfg.channels:
        return
    try:
        notify_fn(cfg, build_notice(event, cfg), secrets_path=secrets_path)
    except Exception as exc:
        log.warning(
            "caretaker best-effort event %s failed: %s",
            event,
            type(exc).__name__,
        )


__all__ = [
    "CaretakerNotifier",
    "send_event_best_effort",
]
