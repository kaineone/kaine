# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Companion-stream declarations and the never-persisted bus at boot.

Each module class says which of its streams carry values a consumer needs off
the persisted bus (``BaseModule.companion_declarations``). The boot collects the
declarations of the enabled modules, gives them to the bus, and refuses to start
when any is declared unless the never-persisted instance answers, requires a
password, does not persist, and caps every declared companion stream within
``[privacy].companion_stream_maxlen`` (``kaine.bus.volatile``). The preboot
runs the same check from the configuration alone.
"""

from __future__ import annotations

import logging
from typing import Any, Iterable, Mapping, Optional

from kaine.bus.companion import CompanionDeclaration, CompanionRegistry
from kaine.bus.volatile import (
    PrivacySettings,
    VolatileBus,
    companion_refusals,
    resolve_volatile_url,
)

log = logging.getLogger(__name__)


def registry_declarations(
    modules: Iterable[Any], kaine_config: Mapping[str, Any]
) -> list[CompanionDeclaration]:
    """The declarations of constructed modules, from their classes and sections."""
    out: list[CompanionDeclaration] = []
    for module in modules:
        declare = getattr(type(module), "companion_declarations", None)
        if not callable(declare):
            continue
        section = kaine_config.get(module.name) or {}
        out.extend(declare(dict(section) if isinstance(section, Mapping) else {}))
    return out


def config_declarations(kaine_config: Mapping[str, Any]) -> list[CompanionDeclaration]:
    """The declarations the enabled modules would make, from the configuration
    alone (for the preboot, which constructs no module)."""
    import kaine.modules  # noqa: F401  (imports every shipped module class)
    from kaine.modules.base import BaseModule

    classes: dict[str, type] = {}
    stack = list(BaseModule.__subclasses__())
    while stack:
        cls = stack.pop()
        stack.extend(cls.__subclasses__())
        name = getattr(cls, "name", None)
        if isinstance(name, str) and cls.__module__.startswith("kaine.modules."):
            classes.setdefault(name, cls)
    toggles = kaine_config.get("modules") or {}
    out: list[CompanionDeclaration] = []
    for name, enabled in sorted(toggles.items() if isinstance(toggles, Mapping) else []):
        cls = classes.get(name)
        if not enabled or cls is None:
            continue
        section = kaine_config.get(name) or {}
        out.extend(cls.companion_declarations(dict(section) if isinstance(section, Mapping) else {}))
    return out


def volatile_from_config(
    kaine_config: Mapping[str, Any],
    *,
    url: Optional[str] = None,
    client_name: Optional[str] = None,
) -> Optional[VolatileBus]:
    """A client of the never-persisted instance, or None when none is configured.

    Companion caps come from ``[bus].per_stream_maxlen`` entries for companion
    streams; every other companion stream takes the ``[privacy]`` bound. Raises
    ``PrivacyConfigError`` on a malformed ``[privacy]`` table.
    """
    settings = PrivacySettings.from_config(kaine_config)
    url = url if url is not None else resolve_volatile_url()
    if not url:
        return None
    bus_doc = kaine_config.get("bus") or {}
    per_stream = bus_doc.get("per_stream_maxlen") if isinstance(bus_doc, Mapping) else None
    caps = {
        str(k): int(v)
        for k, v in (per_stream or {}).items()
        if str(k).endswith(".companion")
    }
    return VolatileBus.from_url(
        url,
        companion_stream_maxlen=settings.companion_stream_maxlen,
        per_stream_maxlen=caps,
        client_name=client_name,
    )


async def declare_and_check(
    bus: Any, modules: Iterable[Any], kaine_config: Mapping[str, Any]
) -> list[str]:
    """Give the enabled modules' declarations to ``bus`` and return every reason
    they may not run (empty when none is declared or all conditions hold)."""
    declarations = registry_declarations(modules, kaine_config)
    if not declarations:
        return []
    bus.declare_companions(declarations)
    settings = PrivacySettings.from_config(kaine_config)
    return await companion_refusals(bus.companions, bus.volatile, settings)


async def preboot_refusals(kaine_config: Mapping[str, Any]) -> tuple[list[str], list[CompanionDeclaration]]:
    """The preboot form: declarations from the configuration, a fresh client."""
    declarations = config_declarations(kaine_config)
    if not declarations:
        return [], []
    settings = PrivacySettings.from_config(kaine_config)
    volatile = volatile_from_config(kaine_config)
    try:
        reasons = await companion_refusals(
            CompanionRegistry(declarations=declarations),
            volatile,
            settings,
        )
    finally:
        if volatile is not None:
            await volatile.close()
    return reasons, declarations

