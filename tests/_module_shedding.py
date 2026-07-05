# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Phase 7.3 module-shedding test helpers.

`StreamProducerFake` mimics any canonical module's publishing surface
(publishes events on its `<name>.out` stream on demand) without
dragging in the real module's heavyweight dependencies.

The twelve canonical module names match the modules built across
Phases 2-6.
"""
from __future__ import annotations

from typing import Any, ClassVar

from kaine.cycle.types import WorkspaceSnapshot
from kaine.modules.base import BaseModule


CANONICAL_MODULE_NAMES = (
    "soma",
    "chronos",
    "topos",
    "nous",
    "mnemos",
    "eidolon",
    "thymos",
    "praxis",
    "lingua",
    "vox",
    "audition",
    "hypnos",
)


def _make_class(module_name: str) -> type[BaseModule]:
    class _Producer(BaseModule):
        name: ClassVar[str] = module_name

        def __init__(self, bus) -> None:
            super().__init__(bus)
            self.snapshots: list[WorkspaceSnapshot] = []
            self.publish_count = 0

        async def publish_one(
            self,
            payload: dict[str, Any] | None = None,
            salience: float = 0.5,
        ) -> str:
            self.publish_count += 1
            event_payload = payload or {"value": f"{module_name}-{self.publish_count}"}
            return await self.publish(
                f"{module_name}.tick",
                event_payload,
                salience=salience,
            )

        async def on_workspace(self, snapshot: WorkspaceSnapshot) -> None:
            self.snapshots.append(snapshot)

    _Producer.__name__ = f"StreamProducerFake_{module_name}"
    return _Producer


_FAKE_CLASSES: dict[str, type[BaseModule]] = {
    name: _make_class(name) for name in CANONICAL_MODULE_NAMES
}


def make_fake(name: str, bus) -> BaseModule:
    cls = _FAKE_CLASSES.get(name)
    if cls is None:
        raise KeyError(f"unknown canonical module name: {name}")
    return cls(bus)


def build_fakes(names, bus) -> dict[str, BaseModule]:
    return {name: make_fake(name, bus) for name in names}
