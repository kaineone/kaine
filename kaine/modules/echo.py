# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

from typing import Any, ClassVar

from kaine.cycle.types import WorkspaceSnapshot
from kaine.modules.base import BaseModule


class EchoModule(BaseModule):
    """Test-only module that records every workspace snapshot it sees.

    EchoModule is permanent test infrastructure for the Phase 1
    end-to-end test. It is disabled in the default config and exists
    only so regression tests on the bus + cycle + Syneidesis path have
    a ground-truth observer.
    """

    name: ClassVar[str] = "echo"

    def __init__(self, bus, message_label: str = "echo") -> None:
        super().__init__(bus)
        self.snapshots: list[WorkspaceSnapshot] = []
        self._message_label = message_label

    async def publish_one(
        self,
        payload: dict[str, Any] | None = None,
        salience: float = 0.7,
    ) -> str:
        return await self.publish(
            "echo.ping",
            payload or {"label": self._message_label},
            salience=salience,
        )

    async def on_workspace(self, snapshot: WorkspaceSnapshot) -> None:
        self.snapshots.append(snapshot)

    def serialize(self) -> dict[str, Any]:
        return {
            "message_label": self._message_label,
            "snapshot_count": len(self.snapshots),
        }

    def deserialize(self, state: dict[str, Any]) -> None:
        self._message_label = state.get("message_label", self._message_label)
