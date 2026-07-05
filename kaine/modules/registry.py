# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

from typing import Iterator, Optional

from kaine.bus.schema import module_stream
from kaine.entity_clock import EntityClock
from kaine.modules.base import BaseModule


class ModuleRegistry:
    """In-process registry mapping module name → module instance.

    Conforms to `kaine.cycle.protocols.ModuleRegistryProtocol` so the
    cognitive cycle can drive event collection from registered modules
    without further wiring.

    Carries the one shared ``EntityClock`` (the entity's subjective clock)
    that ``build_registry`` constructs from ``[cycle].time_scale`` and injects
    into every cognitive module. The cycle entrypoint reads it back off the
    registry and hands the SAME instance to the ``CognitiveCycle``, so the tick
    pacing and the modules' cognitive timers all dilate off one ``time_scale``
    (no two cognitive clocks ever desynchronize). Left ``None`` when a registry
    is built without a clock (the cycle then constructs its own real-time one).
    """

    def __init__(self) -> None:
        self._modules: dict[str, BaseModule] = {}
        self.entity_clock: Optional[EntityClock] = None

    def register(self, module: BaseModule) -> None:
        if module.name in self._modules:
            raise ValueError(f"module {module.name!r} is already registered")
        self._modules[module.name] = module

    def unregister(self, name: str) -> BaseModule:
        if name not in self._modules:
            raise KeyError(f"module {name!r} is not registered")
        return self._modules.pop(name)

    def replace(self, name: str, module: BaseModule) -> None:
        """Swap a registered module in place (used by Spot's heavy restart).

        The slot must already exist and the new module's ``name`` must match,
        so the registry never silently changes a module's identity.
        """
        if name not in self._modules:
            raise KeyError(f"module {name!r} is not registered")
        if module.name != name:
            raise ValueError(
                f"module name {module.name!r} does not match slot {name!r}"
            )
        self._modules[name] = module

    def get(self, name: str) -> BaseModule:
        return self._modules[name]

    def all_modules(self) -> Iterator[BaseModule]:
        return iter(list(self._modules.values()))

    def active_streams(self) -> list[str]:
        return [module_stream(name) for name in self._modules]

    def __len__(self) -> int:
        return len(self._modules)

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and name in self._modules
