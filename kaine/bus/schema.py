# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from kaine.bus.errors import EventValidationError, ReservedStreamError

WORKSPACE_STREAM = "workspace.broadcast"
SYNEIDESIS_SOURCE = "syneidesis"


class Event(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source: str = Field(min_length=1, max_length=64)
    type: str = Field(min_length=1, max_length=128)
    payload: dict[str, Any] = Field(default_factory=dict)
    salience: float = Field(ge=0.0, le=1.0)
    timestamp: datetime
    causal_parent: Optional[str] = None

    @field_validator("timestamp")
    @classmethod
    def _require_tz(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
            raise ValueError("timestamp must be timezone-aware")
        return value.astimezone(timezone.utc)

    @field_validator("source", "type")
    @classmethod
    def _no_whitespace(cls, value: str) -> str:
        if any(ch.isspace() for ch in value):
            raise ValueError("must not contain whitespace")
        return value


def validate_event(**fields: Any) -> Event:
    try:
        return Event(**fields)
    except Exception as exc:
        raise EventValidationError(str(exc)) from exc


def module_stream(module_name: str) -> str:
    if not module_name or any(ch.isspace() for ch in module_name):
        raise ValueError("module name must be non-empty and whitespace-free")
    if module_name == SYNEIDESIS_SOURCE:
        return WORKSPACE_STREAM
    return f"{module_name}.out"


def ensure_writable(stream: str, source: str) -> None:
    if stream == WORKSPACE_STREAM and source != SYNEIDESIS_SOURCE:
        raise ReservedStreamError(
            f"only the syneidesis module may publish to {WORKSPACE_STREAM}"
        )
