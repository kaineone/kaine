# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Escalation control for the Spot module supervisor.

`state/cycle/escalation.json` records that Spot exhausted its restart budget
for a module and halted the process for operator attention. It mirrors
`control_state.py`: atomic writes, operational fields only — a flag, the failed
module name, attempt count, the saved snapshot id, an ISO timestamp, and an
operator-facing message. NEVER any sensory content.

A clean boot calls `clear_escalation()` so a deliberate fresh launch starts with
no stale escalation; a wrapper that merely restarts the process without an
operator reboot still sees the prior escalation until that happens.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Optional

from kaine.state_io import write_json_atomic

ESCALATION_PATH = Path("state/cycle/escalation.json")


@dataclass(frozen=True)
class EscalationRecord:
    escalated: bool = False
    module: Optional[str] = None
    attempts: int = 0
    snapshot_id: Optional[str] = None
    escalated_at: Optional[str] = None
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "EscalationRecord":
        data = dict(data or {})
        return cls(
            escalated=bool(data.get("escalated", False)),
            module=data.get("module"),
            attempts=int(data.get("attempts", 0)),
            snapshot_id=data.get("snapshot_id"),
            escalated_at=data.get("escalated_at"),
            message=str(data.get("message", "")),
        )


# Shared boundary-neutral atomic JSON writer (see kaine.state_io).
_atomic_write = write_json_atomic


def read_escalation(path: Path | None = None) -> EscalationRecord:
    target = path or ESCALATION_PATH
    if not target.exists():
        return EscalationRecord()
    try:
        return EscalationRecord.from_dict(json.loads(target.read_text()))
    except (json.JSONDecodeError, OSError):
        return EscalationRecord()


def write_escalation(rec: EscalationRecord, path: Path | None = None) -> None:
    _atomic_write(path or ESCALATION_PATH, rec.to_dict())


def clear_escalation(path: Path | None = None) -> EscalationRecord:
    rec = EscalationRecord()
    write_escalation(rec, path)
    return rec
