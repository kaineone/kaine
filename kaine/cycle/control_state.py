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


@dataclass(frozen=True)
class CycleControl:
    frozen: bool = False
    frozen_at: Optional[str] = None
    reason: Optional[str] = None
    # Who commanded the freeze: "operator" (the default and the operator's
    # control file) or "spot" (the module supervisor). Spot only resumes its
    # own freeze and never clears an operator freeze.
    source: str = "operator"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "CycleControl":
        data = dict(data or {})
        return cls(
            frozen=bool(data.get("frozen", False)),
            frozen_at=data.get("frozen_at"),
            reason=data.get("reason"),
            source=data.get("source", "operator"),
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


def freeze(
    reason: Optional[str] = None,
    path: Path | None = None,
    *,
    source: str = "operator",
) -> CycleControl:
    state = CycleControl(
        frozen=True, frozen_at=_now_iso(), reason=reason, source=source
    )
    write_control(state, path)
    return state


def unfreeze(path: Path | None = None) -> CycleControl:
    state = CycleControl(frozen=False, frozen_at=None, reason=None)
    write_control(state, path)
    return state
