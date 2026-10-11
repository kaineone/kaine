# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""In-process ignition log for the cognitive cycle.

One JSONL record per successful workspace broadcast. Each record carries the
tick index, the bus entry id, wall and monotonic timestamps, the programme
position at the instant of broadcast, the audio feed's own delivered position,
the salience scores and inhibition decision, and the coalition members'
entry ids, sources, types, saliences and original timestamps.

No event payloads are persisted, so no conversation content, video frames, or
audio samples leave the process. The log is never published on the bus and no
module receives it; the entity never learns its place in the programme.

Records are written through AsyncJsonlSink, which adds run id and sequence
number, encrypts at rest when state encryption is on, and never auto-purges
when constructed with retention_days=0. The ignition log is the workspace-graph
record; it is kept for the paper analysis and then as world-model training
data, and is never purged automatically — only the operator deletes it.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from kaine.persistence.jsonl_sink import AsyncJsonlSink

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class IgnitionLogConfig:
    enabled: bool = False
    directory: str = "data/ignition"

    @classmethod
    def from_section(cls, section: dict[str, Any] | None) -> "IgnitionLogConfig":
        if section is None:
            return cls()
        enabled = section.get("enabled", cls.enabled)
        if not isinstance(enabled, bool):
            raise ValueError(
                f"ignition_log.enabled must be a bool, got {type(enabled).__name__}"
            )
        directory = section.get("directory", cls.directory)
        if not isinstance(directory, str) or not directory:
            raise ValueError(
                f"ignition_log.directory must be a non-empty string, got {directory!r}"
            )
        return cls(enabled=enabled, directory=directory)


# ``(item_idx, order, title, offset_s, paused[, paused_by])``: ``paused_by`` is
# the sorted names of the clock's pause holders (``transition``, ``freeze``,
# ``hypnos``, ...), so analysis can tell the womb-to-world crossfade from sleep
# or a freeze. A provider without it yields a record with ``paused_by: None``.
PositionProvider = Callable[[], tuple[Any, ...] | None]
AudioPositionProvider = Callable[[], tuple[int, float] | None]


class IgnitionLog:
    def __init__(
        self,
        sink: Any,
        position_provider: PositionProvider,
        audio_position_provider: AudioPositionProvider | None = None,
    ) -> None:
        self._sink = sink
        self._position_provider = position_provider
        self._audio_position_provider = audio_position_provider

    async def on_broadcast(
        self,
        payload: dict[str, Any],
        entry_id: str,
        wall_ts: Any,
        mono_ts: float,
    ) -> None:
        programme: dict[str, Any] | None = None
        try:
            pos = self._position_provider()
        except Exception:
            log.warning(
                "programme position provider failed on tick %s",
                payload.get("tick_index"),
                exc_info=True,
            )
            pos = None
        if pos is not None:
            item_idx, order, title, offset_s, paused = pos[:5]
            paused_by = list(pos[5]) if len(pos) > 5 and pos[5] is not None else None
            programme = {
                "item_idx": item_idx,
                "order": order,
                "title": title,
                "offset_s": offset_s,
                "paused": paused,
                "paused_by": paused_by,
            }

        audio: dict[str, Any] | None = None
        if self._audio_position_provider is not None:
            try:
                apos = self._audio_position_provider()
            except Exception:
                log.warning(
                    "audio position provider failed on tick %s",
                    payload.get("tick_index"),
                    exc_info=True,
                )
                apos = None
            if apos is not None:
                audio = {"item_idx": apos[0], "delivered_s": apos[1]}

        members: list[dict[str, Any]] = []
        for entry in payload.get("selected", []):
            members.append(
                {
                    "entry_id": entry.get("entry_id"),
                    "source": entry.get("source"),
                    "type": entry.get("type"),
                    "salience": entry.get("salience"),
                    "timestamp": entry.get("timestamp"),
                }
            )

        record: dict[str, Any] = {
            "tick_index": payload.get("tick_index"),
            "entry_id": entry_id,
            "wall_ts": wall_ts.isoformat() if wall_ts is not None else None,
            "mono_ts": mono_ts,
            "programme": programme,
            "audio": audio,
            "inhibited": payload.get("inhibited"),
            "salience_scores": payload.get("salience_scores"),
            "members": members,
            "time_scale": payload.get("time_scale"),
        }

        await self._sink.write(record)

    async def close(self) -> None:
        await self._sink.stop()
        if self._sink.dropped_count > 0:
            log.warning(
                "ignition log dropped %d records under backpressure",
                self._sink.dropped_count,
            )


def ignition_log_sink(directory: str | Path) -> AsyncJsonlSink:
    """Return the ignition-log ``AsyncJsonlSink``.

    The ignition log is the workspace-graph record; it is kept for the paper
    analysis and then as world-model training data, and is never purged
    automatically — only the operator deletes it.
    """
    return AsyncJsonlSink(Path(directory), name="ignition", retention_days=0)


def playlist_position_provider(
    clock: Any, manifest: Any
) -> Callable[[], tuple[int, int, str, float, bool, tuple[str, ...] | None] | None]:
    """Return a zero-arg provider for the shared ``PlaylistClock`` + manifest.

    ``clock`` is duck-typed: it must expose ``started``, ``locate()`` and
    ``paused``, and may expose ``holders`` (the pause holders, reported as
    ``paused_by``). ``manifest.items`` must be an iterable of objects with
    ``order`` and ``path`` attributes. This module deliberately does not
    import kaine.modules so it stays a cycle-layer primitive.
    """

    def _provide() -> tuple[int, int, str, float, bool, tuple[str, ...] | None] | None:
        if not clock.started:
            return None
        idx, offset = clock.locate()
        items = manifest.items
        if idx >= len(items):
            return None
        it = items[idx]
        holders = getattr(clock, "holders", None)
        paused_by = tuple(sorted(holders)) if holders is not None else None
        return (idx, it.order, Path(it.path).name, offset, clock.paused, paused_by)

    return _provide
