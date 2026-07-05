# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Protocol, runtime_checkable

from kaine.bus.schema import Event
from kaine.cycle.types import WorkspaceSnapshot


@runtime_checkable
class SyneidesisProtocol(Protocol):
    async def select(
        self,
        events: list[tuple[str, Event]],
        context: dict[str, Any],
    ) -> WorkspaceSnapshot:
        ...


@runtime_checkable
class ModuleRegistryProtocol(Protocol):
    def active_streams(self) -> list[str]:
        ...


CycleHook = Callable[[], Awaitable[None]]
