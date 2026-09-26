# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Persistent birth request/acknowledgement records for operator-supervised birth.

The maturation gate writes the request record; Nexus writes ONLY the
acknowledgement record. Both are small JSON files under ``state/lifecycle/``.
Readers are forgiving: a missing or malformed file is treated as absent and
never raises.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from kaine.state_io import write_json_atomic

BIRTH_REQUEST_PATH = Path("state/lifecycle/birth_request.json")
BIRTH_ACK_PATH = Path("state/lifecycle/birth_ack.json")

_REQUEST_ID_RE = re.compile(r"^[0-9a-f]{32}$")


@dataclass(frozen=True)
class BirthRequest:
    request_id: str          # 32 lowercase hex (uuid4().hex)
    requested_at: str        # ISO-8601 UTC
    gestation_started_at: str | None


@dataclass(frozen=True)
class BirthAck:
    request_id: str
    acknowledged_at: str


def _is_valid_request_id(value: object) -> bool:
    return isinstance(value, str) and _REQUEST_ID_RE.fullmatch(value) is not None


def _read_json_object(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    if not isinstance(data, dict):
        return None
    return data


def new_request(gestation_started_at: str | None) -> BirthRequest:
    """Mint a new birth request record."""
    return BirthRequest(
        request_id=uuid4().hex,
        requested_at=datetime.now(timezone.utc).isoformat(),
        gestation_started_at=gestation_started_at,
    )


def write_request(req: BirthRequest, path: Path | None = None) -> None:
    """Write the birth request record atomically."""
    target = path or BIRTH_REQUEST_PATH
    payload = {
        "request_id": req.request_id,
        "requested_at": req.requested_at,
        "gestation_started_at": req.gestation_started_at,
    }
    write_json_atomic(target, payload)


def read_request(path: Path | None = None) -> BirthRequest | None:
    """Return the birth request record, or None if missing or malformed."""
    target = path or BIRTH_REQUEST_PATH
    data = _read_json_object(target)
    if data is None:
        return None
    request_id = data.get("request_id")
    requested_at = data.get("requested_at")
    gestation_started_at = data.get("gestation_started_at")
    if not _is_valid_request_id(request_id) or not isinstance(requested_at, str):
        return None
    if gestation_started_at is not None and not isinstance(gestation_started_at, str):
        return None
    return BirthRequest(
        request_id=request_id,
        requested_at=requested_at,
        gestation_started_at=gestation_started_at,
    )


def clear_request(path: Path | None = None) -> None:
    """Remove the birth request file if present."""
    target = path or BIRTH_REQUEST_PATH
    try:
        target.unlink()
    except FileNotFoundError:
        # Already absent: clearing a missing request file is a no-op.
        return


def write_ack(ack: BirthAck, path: Path | None = None) -> None:
    """Write the acknowledgement record atomically."""
    target = path or BIRTH_ACK_PATH
    payload = {
        "request_id": ack.request_id,
        "acknowledged_at": ack.acknowledged_at,
    }
    write_json_atomic(target, payload)


def read_ack(path: Path | None = None) -> BirthAck | None:
    """Return the acknowledgement record, or None if missing or malformed."""
    target = path or BIRTH_ACK_PATH
    data = _read_json_object(target)
    if data is None:
        return None
    request_id = data.get("request_id")
    acknowledged_at = data.get("acknowledged_at")
    if not _is_valid_request_id(request_id) or not isinstance(acknowledged_at, str):
        return None
    return BirthAck(
        request_id=request_id,
        acknowledged_at=acknowledged_at,
    )


def clear_ack(path: Path | None = None) -> None:
    """Remove the acknowledgement file if present."""
    target = path or BIRTH_ACK_PATH
    try:
        target.unlink()
    except FileNotFoundError:
        # Already absent: clearing a missing acknowledgement file is a no-op.
        return


def is_acknowledged(req: BirthRequest | None, ack: BirthAck | None) -> bool:
    """True only when both records exist and their request ids match."""
    if req is None or ack is None:
        return False
    return req.request_id == ack.request_id


__all__ = [
    "BIRTH_REQUEST_PATH",
    "BIRTH_ACK_PATH",
    "BirthRequest",
    "BirthAck",
    "new_request",
    "write_request",
    "read_request",
    "clear_request",
    "write_ack",
    "read_ack",
    "clear_ack",
    "is_acknowledged",
]
