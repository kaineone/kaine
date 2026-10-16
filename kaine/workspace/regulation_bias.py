# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Selection-side tier-1 emotion regulation (attentional deployment).

Implements paper §3.5 and the ranking invariant of paper A.1: with the
regulation-bias gate disabled, ``I(e) N_k(e)`` alone ranks a tick's candidates.
The workspace layer does not import ``kaine.modules``; the affect module reaches
this gate through ordinary bus events of type ``affect.regulation`` with
``tier == 1``.
"""

from __future__ import annotations

import math
from typing import Any, Callable, Iterable, Optional

from kaine.bus.schema import Event


class RegulationBias:
    """Tier-1 attentional deployment bias gate.

    Holds the most recently observed tier-1 regulation target and decays its
    applied bias with exponential time constant ``decay_s``. Tier-2 and tier-3
    events, malformed payloads, and no-target events are ignored.
    """

    def __init__(self, clock: Callable[[], float]) -> None:
        self._clock = clock
        self._source: Optional[str] = None
        self._bias = 0.0
        self._decay_s = 1.0
        self._t1 = 0.0

    def observe(self, events: Iterable[tuple[str, Event]]) -> None:
        """Adopt the last qualifying tier-1 regulation event, if any."""
        for _entry_id, event in events:
            if event.source != "affect":
                continue
            if event.type != "affect.regulation":
                continue
            payload = event.payload if isinstance(event.payload, dict) else {}
            tier = payload.get("tier")
            if tier != 1:
                continue
            source = payload.get("source")
            if not isinstance(source, str) or not source:
                continue
            bias = payload.get("bias")
            if isinstance(bias, bool) or not isinstance(bias, (int, float)):
                continue
            if not math.isfinite(bias) or not 0.0 <= bias <= 1.0:
                continue
            decay_s = payload.get("decay_s")
            if isinstance(decay_s, bool) or not isinstance(decay_s, (int, float)):
                continue
            if not math.isfinite(decay_s) or decay_s <= 0.0:
                continue

            self._source = source
            self._bias = float(bias)
            self._decay_s = float(decay_s)
            self._t1 = self._clock()

    def bias(self) -> float:
        """Return the decayed bias, or 0.0 when no source is held."""
        if self._source is None:
            return 0.0
        elapsed = max(0.0, self._clock() - self._t1)
        return self._bias * math.exp(-elapsed / self._decay_s)

    def factor_for_source(self, source: str) -> float:
        """Selection multiplier for ``source``."""
        if self._source is not None and source == self._source:
            return 1.0 - self.bias()
        return 1.0

    def describe(self) -> Optional[dict[str, Any]]:
        """Return a description of the active bias, or None when inactive."""
        if self._source is None:
            return None
        b = self.bias()
        if b <= 0.0:
            return None
        return {"source": self._source, "factor": 1.0 - b}
