# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Persistent start/acknowledgement records for unattended caretaker boots.

The cycle writes the start record; Nexus writes the acknowledgement record.
Both are small JSON files under ``state/cycle/``. Readers are forgiving: a
missing or malformed file is treated as absent and never raises.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from kaine.state_io import write_json_atomic

START_PATH = Path("state/cycle/caretaker_start.json")
ACK_PATH = Path("state/cycle/caretaker_ack.json")

_START_ID_RE = re.compile(r"^[0-9a-f]{32}$")


@dataclass(frozen=True)
class CaretakerStart:
    start_id: str
    started_at: str


@dataclass(frozen=True)
class CaretakerAck:
    start_id: str
    acknowledged_at: str


def _is_valid_start_id(value: object) -> bool:
    return isinstance(value, str) and _START_ID_RE.fullmatch(value) is not None


def _read_json_object(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def write_start(start: CaretakerStart, path: Path | None = None) -> None:
    """Write the start record atomically."""
    target = path or START_PATH
    payload = {"start_id": start.start_id, "started_at": start.started_at}
    write_json_atomic(target, payload)


def read_start(path: Path | None = None) -> CaretakerStart | None:
    """Return the start record, or None if missing or malformed."""
    target = path or START_PATH
    data = _read_json_object(target)
    if data is None:
        return None
    start_id = data.get("start_id")
    started_at = data.get("started_at")
    if not _is_valid_start_id(start_id) or not isinstance(started_at, str):
        return None
    return CaretakerStart(start_id=start_id, started_at=started_at)


def write_ack(ack: CaretakerAck, path: Path | None = None) -> None:
    """Write the acknowledgement record atomically."""
    target = path or ACK_PATH
    payload = {"start_id": ack.start_id, "acknowledged_at": ack.acknowledged_at}
    write_json_atomic(target, payload)


def read_ack(path: Path | None = None) -> CaretakerAck | None:
    """Return the acknowledgement record, or None if missing or malformed."""
    target = path or ACK_PATH
    data = _read_json_object(target)
    if data is None:
        return None
    start_id = data.get("start_id")
    acknowledged_at = data.get("acknowledged_at")
    if not _is_valid_start_id(start_id) or not isinstance(acknowledged_at, str):
        return None
    return CaretakerAck(start_id=start_id, acknowledged_at=acknowledged_at)


def clear_start(path: Path | None = None) -> None:
    """Remove the start record if present."""
    target = path or START_PATH
    try:
        target.unlink()
    except FileNotFoundError:
        pass


def is_acknowledged(
    start: CaretakerStart | None, ack: CaretakerAck | None
) -> bool:
    """True only when both records exist and their start ids match."""
    if start is None or ack is None:
        return False
    return start.start_id == ack.start_id


__all__ = [
    "START_PATH",
    "ACK_PATH",
    "CaretakerStart",
    "CaretakerAck",
    "write_start",
    "read_start",
    "write_ack",
    "read_ack",
    "clear_start",
    "is_acknowledged",
]
