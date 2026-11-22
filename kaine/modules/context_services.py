# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Shared services handed to every module by boot via ``ModuleContext`` (module-core task 3.2)."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from kaine.entity_clock import EntityClock
from kaine.persistence.jsonl_sink import AsyncJsonlSink
from kaine.privacy_filter import PrivacyFilter
from kaine.state_io import write_json_atomic
from kaine.storage import resolve


@dataclass(frozen=True)
class ModuleContext:
    """The single handle a module uses to reach shared, cycle-owned services.

    Attached by boot before ``initialize()``; reading ``BaseModule.context``
    before attachment raises a clear ``RuntimeError``.
    """

    clock: EntityClock
    resolve: Callable[[Any], Path] = resolve
    write_json: Callable[[Path, Any], None] = write_json_atomic
    privacy: PrivacyFilter = field(default_factory=PrivacyFilter)

    def jsonl(self, directory: Any, *, name: str, **kwargs: Any) -> AsyncJsonlSink:
        return AsyncJsonlSink(directory, name=name, **kwargs)

    @classmethod
    def build(cls, clock: EntityClock) -> "ModuleContext":
        return cls(
            clock=clock,
            resolve=resolve,
            write_json=write_json_atomic,
            privacy=PrivacyFilter(),
        )
