# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The Perception factory."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    pass
from kaine.bus.client import AsyncBus
from kaine.entity_clock import EntityClock
from kaine.modules.base import BaseModule


def make_perception(
    bus: AsyncBus,
    section: dict[str, Any],
    *,
    entity_clock: Optional[EntityClock] = None,
) -> BaseModule:
    from kaine.modules.perception.module import PerceptionLocus

    kwargs: dict[str, Any] = {}
    for key in ("allow_self_switch", "min_dwell_s"):
        if key in section:
            kwargs[key] = section[key]
    return PerceptionLocus(bus, entity_clock=entity_clock, **kwargs)
