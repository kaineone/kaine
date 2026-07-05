# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Regulation policy for Thymos.

Build prompt §4.1: "regulation (hook for RL policy, passive drift only
for now)." The protocol exposes one async method that returns a
suggested adjustment. The default `PassiveDecay` returns no
adjustment — the dimensional state's homeostatic drift toward baseline
is the regulation.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from kaine.modules.thymos.state import DimensionalState

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class RegulationAdjustment:
    valence: float = 0.0
    arousal: float = 0.0
    dominance: float = 0.0


@runtime_checkable
class RegulationPolicy(Protocol):
    async def suggest(self, state: DimensionalState) -> RegulationAdjustment: ...


class PassiveDecay:
    """No-op regulation: returns zero adjustment every tick.

    The homeostatic drift toward baseline in DimensionalState is the
    sole "regulation" at this stage.  A one-time debug log is emitted
    on first use so the passive policy is visible in traces rather than
    silently doing nothing.
    """

    def __init__(self) -> None:
        self._logged_once = False

    async def suggest(self, state: DimensionalState) -> RegulationAdjustment:
        if not self._logged_once:
            log.debug(
                "thymos regulation: PassiveDecay active — "
                "no active regulation policy; homeostatic drift is the sole regulator"
            )
            self._logged_once = True
        return RegulationAdjustment()
