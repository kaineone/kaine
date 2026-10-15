# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Persistent maturation request/acknowledgement records for operator-supervised maturation.

The maturation gate writes the request record; the dashboard writes ONLY the
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

from kaine import legacy_aliases
from kaine.state_io import write_json_atomic
from kaine.storage import resolve

MATURATION_REQUEST_PATH = Path("state/lifecycle/maturation_request.json")
MATURATION_ACK_PATH = Path("state/lifecycle/maturation_ack.json")

_REQUEST_ID_RE = re.compile(r"^[0-9a-f]{32}$")


@dataclass(frozen=True)
class MaturationRequest:
    request_id: str          # 32 lowercase hex (uuid4().hex)
    requested_at: str        # ISO-8601 UTC
    development_started_at: str | None


@dataclass(frozen=True)
class MaturationAck:
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


def new_request(development_started_at: str | None) -> MaturationRequest:
    """Mint a new maturation request record."""
    return MaturationRequest(
        request_id=uuid4().hex,
        requested_at=datetime.now(timezone.utc).isoformat(),
        development_started_at=development_started_at,
    )


def write_request(req: MaturationRequest, path: Path | None = None) -> None:
    """Write the maturation request record atomically."""
    target = resolve(path or MATURATION_REQUEST_PATH)
    payload = {
        "request_id": req.request_id,
        "requested_at": req.requested_at,
        "development_started_at": req.development_started_at,
    }
    write_json_atomic(target, payload)


def read_request(path: Path | None = None) -> MaturationRequest | None:
    """Return the maturation request record, or None if missing or malformed."""
    target = resolve(path or MATURATION_REQUEST_PATH)
    data = _read_json_object(target)
    if data is None:
        return None
    data = legacy_aliases.map_stage_record(data)
    request_id = data.get("request_id")
    requested_at = data.get("requested_at")
    development_started_at = data.get("development_started_at")
    if not _is_valid_request_id(request_id) or not isinstance(requested_at, str):
        return None
    if development_started_at is not None and not isinstance(development_started_at, str):
        return None
    return MaturationRequest(
        request_id=request_id,
        requested_at=requested_at,
        development_started_at=development_started_at,
    )


def clear_request(path: Path | None = None) -> None:
    """Remove the maturation request file if present."""
    target = resolve(path or MATURATION_REQUEST_PATH)
    try:
        target.unlink()
    except FileNotFoundError:
        # Already absent: clearing a missing request file is a no-op.
        return


def write_ack(ack: MaturationAck, path: Path | None = None) -> None:
    """Write the acknowledgement record atomically."""
    target = resolve(path or MATURATION_ACK_PATH)
    payload = {
        "request_id": ack.request_id,
        "acknowledged_at": ack.acknowledged_at,
    }
    write_json_atomic(target, payload)


def read_ack(path: Path | None = None) -> MaturationAck | None:
    """Return the acknowledgement record, or None if missing or malformed."""
    target = resolve(path or MATURATION_ACK_PATH)
    data = _read_json_object(target)
    if data is None:
        return None
    request_id = data.get("request_id")
    acknowledged_at = data.get("acknowledged_at")
    if not _is_valid_request_id(request_id) or not isinstance(acknowledged_at, str):
        return None
    return MaturationAck(
        request_id=request_id,
        acknowledged_at=acknowledged_at,
    )


def clear_ack(path: Path | None = None) -> None:
    """Remove the acknowledgement file if present."""
    target = resolve(path or MATURATION_ACK_PATH)
    try:
        target.unlink()
    except FileNotFoundError:
        # Already absent: clearing a missing acknowledgement file is a no-op.
        return


def is_acknowledged(req: MaturationRequest | None, ack: MaturationAck | None) -> bool:
    """True only when both records exist and their request ids match."""
    if req is None or ack is None:
        return False
    return req.request_id == ack.request_id


__all__ = [
    "MATURATION_REQUEST_PATH",
    "MATURATION_ACK_PATH",
    "MaturationRequest",
    "MaturationAck",
    "new_request",
    "write_request",
    "read_request",
    "clear_request",
    "write_ack",
    "read_ack",
    "clear_ack",
    "is_acknowledged",
]
