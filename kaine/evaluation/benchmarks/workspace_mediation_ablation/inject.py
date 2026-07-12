# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Headless operator text-stimulus injection for the minimal (Audition-absent) build.

A user utterance normally reaches the cognitive cycle as an
``audition.transcription`` event on ``audition.out`` (published by the Audition
module or the remote bridge). The workspace-mediation minimal configuration runs
only Soma, Chronos, and Lingua — no Audition — so ``audition.out`` is not in the
cycle's read set (the cycle reads exactly ``registry.active_streams()``).

This utility lets an operator inject a single seeded utterance into such a build:
it writes a properly-encoded ``audition.transcription`` event onto an ACTIVE
stream the cycle already reads (a registered module's ``.out``). The event keeps
``source="audition"`` / ``type="audition.transcription"`` — the fields Volition
matches to form a speak intent — regardless of which stream carries it, so the
cycle selects it, Volition emits a speak intent, and Lingua answers on
``lingua.external``.

This is operator tooling in the evaluation layer, kept out of the core bus's
public write surface on purpose: the bus's normal ``publish`` routes by event
source (an event goes to ``<source>.out``), and this deliberate foreign-stream
write is a research seam, not a general capability. Choose an active target
stream explicitly (e.g. ``"chronos.out"``).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from kaine.bus.client import AsyncBus, _encode_event
from kaine.bus.config import maxlen_for
from kaine.bus.schema import validate_event

LINGUA_EXTERNAL_STREAM = "lingua.external"


async def inject_utterance(
    bus: AsyncBus,
    text: str,
    *,
    stream: str,
    salience: float = 0.6,
    seq: int = 0,
) -> str:
    """Inject one user utterance onto an active ``stream`` the cycle reads.

    ``stream`` MUST be a stream the cycle currently reads (a registered module's
    ``<name>.out``); on the minimal build use e.g. ``"chronos.out"``. The event
    carries ``source="audition"`` / ``type="audition.transcription"`` so Volition
    forms a speak intent from it. Returns the stream entry id.
    """
    event = validate_event(
        source="audition",
        type="audition.transcription",
        payload={"text": text, "seq": seq},
        salience=salience,
        timestamp=datetime.now(timezone.utc),
    )
    return await bus.client.xadd(
        stream,
        _encode_event(event),
        maxlen=maxlen_for(bus.config, stream),
        approximate=True,
    )


async def read_latest_external(
    bus: AsyncBus, *, last_id: str = "0"
) -> Optional[str]:
    """Return the text of the most recent ``lingua.external`` event, or ``None``.

    Reads the entity's external-speech stream so a headless caller can capture the
    response the injected utterance elicited.
    """
    entries = await bus.read(LINGUA_EXTERNAL_STREAM, last_id=last_id, count=1000)
    if not entries:
        return None
    _entry_id, event = entries[-1]
    text = event.payload.get("text")
    return str(text) if text is not None else None


__all__ = [
    "inject_utterance",
    "read_latest_external",
    "LINGUA_EXTERNAL_STREAM",
]
