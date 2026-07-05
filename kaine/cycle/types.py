# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from kaine.bus.schema import Event


@dataclass(frozen=True)
class WorkspaceSnapshot:
    tick_index: int
    selected_events: list[tuple[str, Event]] = field(default_factory=list)
    inhibited: bool = False
    is_experiential: bool = False
    salience_scores: dict[str, float] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TickResult:
    tick_index: int
    wall_duration_ms: float
    target_duration_ms: float
    slip_ms: float
    is_experiential: bool
    modules_seen: int = 0
    events_collected: int = 0
    error: bool = False
    error_message: str | None = None
