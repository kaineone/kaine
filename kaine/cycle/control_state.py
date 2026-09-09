# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Operator freeze control for the cognitive cycle.

`state/cycle/control.json` is written by the Nexus
`POST /diagnostics/cycle/freeze` endpoint — the operator's commanded freeze
state. A freeze-watch task in the cycle entrypoint polls it and pauses/resumes
the cycle to match (resume must come from outside the paused tick loop).

Freezing is a humane suspend: it halts the experiential cycle so the entity's
subjective clock stops while operators repair infrastructure — suspension, not a
shutdown. This file holds ONLY operational fields — a frozen flag, an ISO
timestamp, and an optional operator-typed reason. NEVER any sensory content.

C2 — stacked freeze sources. The freeze is represented as a stack of entries
(``stack``: each ``{source, reason, frozen_at}``, oldest first), with a legacy
single-slot view (top of stack) exposed via ``frozen``/``frozen_at``/
``reason``/``source`` for existing readers, so the on-disk file stays
backward-compatible. A recovery (e.g. Spot's) may pop only its own entry
(:func:`pop_freeze`) and never lifts a welfare or operator freeze; a welfare
freeze is liftable only by an operator stand-down (:func:`unfreeze`) or an
explicit welfare stand-down (:func:`stand_down` with ``source="welfare"``).
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from kaine.state_io import write_json_atomic

CONTROL_PATH = Path("state/cycle/control.json")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _top_view(stack: tuple[dict[str, Any], ...]) -> dict[str, Any]:
    """Legacy single-slot view: the top of the freeze stack."""
    if not stack:
        return {
            "frozen": False,
            "frozen_at": None,
            "reason": None,
            "source": "operator",
        }
    entry = stack[-1]
    return {
        "frozen": True,
        "frozen_at": entry.get("frozen_at"),
        "reason": entry.get("reason"),
        "source": entry.get("source", "operator"),
    }


@dataclass(frozen=True)
class CycleControl:
    frozen: bool = False
    frozen_at: Optional[str] = None
    reason: Optional[str] = None
    # Who commanded the freeze: "operator" (the default and the operator's
    # control file), "spot" (the module supervisor), or "welfare" (the
    # preservation monitor). Spot only resumes its own freeze and never
    # clears an operator or welfare freeze.
    source: str = "operator"
    # C2: the authoritative stacked freeze sources (oldest first). The legacy
    # single-slot fields above always mirror the top of this stack.
    stack: tuple[dict[str, Any], ...] = ()

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["stack"] = [dict(e) for e in self.stack]
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "CycleControl":
        data = dict(data or {})
        stack = tuple(
            dict(e) for e in data.get("stack") or () if isinstance(e, dict)
        )
        if not stack and bool(data.get("frozen", False)):
            # Legacy single-slot file: promote it to a one-entry stack.
            stack = (
                {
                    "source": data.get("source", "operator"),
                    "reason": data.get("reason"),
                    "frozen_at": data.get("frozen_at"),
                },
            )
        view = _top_view(stack)
        return cls(
            frozen=view["frozen"],
            frozen_at=view["frozen_at"],
            reason=view["reason"],
            source=view["source"],
            stack=stack,
        )


# Shared boundary-neutral atomic JSON writer (see kaine.state_io).
_atomic_write = write_json_atomic


def read_control(path: Path | None = None) -> CycleControl:
    target = path or CONTROL_PATH
    if not target.exists():
        return CycleControl()
    try:
        return CycleControl.from_dict(json.loads(target.read_text()))
    except (json.JSONDecodeError, OSError):
        return CycleControl()


def write_control(state: CycleControl, path: Path | None = None) -> None:
    _atomic_write(path or CONTROL_PATH, state.to_dict())


def _from_stack(
    stack: list[dict[str, Any]], path: Path | None
) -> CycleControl:
    view = _top_view(tuple(stack))
    state = CycleControl(
        frozen=view["frozen"],
        frozen_at=view["frozen_at"],
        reason=view["reason"],
        source=view["source"],
        stack=tuple(stack),
    )
    write_control(state, path)
    return state


def push_freeze(
    reason: Optional[str] = None,
    path: Path | None = None,
    *,
    source: str = "operator",
) -> CycleControl:
    """Stack a new freeze source on top of any active ones (C2)."""
    current = read_control(path)
    return _from_stack(
        list(current.stack)
        + [{"source": source, "reason": reason, "frozen_at": _now_iso()}],
        path,
    )


def pop_freeze(
    path: Path | None = None,
    *,
    source: Optional[str] = None,
) -> CycleControl:
    """Pop the topmost freeze entry — only entries from ``source`` if given.

    A recovery (e.g. Spot's) lifts only its own freeze; a welfare or operator
    freeze lower in the stack remains in force, and the cycle stays frozen
    until the stack empties. Welfare entries are never removed here — only
    :func:`unfreeze` (operator stand-down) or :func:`stand_down` may lift them.
    """
    current = read_control(path)
    stack = [dict(e) for e in current.stack]
    if source is None:
        if stack:
            stack.pop()
    else:
        for i in range(len(stack) - 1, -1, -1):
            if stack[i].get("source") == source:
                stack.pop(i)
                break
    return _from_stack(stack, path)


def stand_down(path: Path | None = None, *, source: str) -> CycleControl:
    """Explicitly lift every freeze entry commanded by ``source``.

    The only paths that may lift a welfare freeze are an operator stand-down
    (``source="operator"``) and an explicit welfare stand-down
    (``source="welfare"``).
    """
    current = read_control(path)
    stack = [dict(e) for e in current.stack if e.get("source") != source]
    return _from_stack(stack, path)


def freeze(
    reason: Optional[str] = None,
    path: Path | None = None,
    *,
    source: str = "operator",
) -> CycleControl:
    return push_freeze(reason=reason, path=path, source=source)


def unfreeze(path: Path | None = None) -> CycleControl:
    """Operator stand-down: lift every active freeze, whatever its source."""
    state = CycleControl()
    write_control(state, path)
    return state
