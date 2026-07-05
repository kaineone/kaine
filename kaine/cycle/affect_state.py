# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Affect/drive dependency-injection seam for the live salience factors.

The paper's four-factor salience (`intensity × novelty × goal × thymos`) needs
the entity's current affect (for the Thymos factor) and current drives (for the
goal factor). Both are produced by Thymos and ride the ``thymos.out`` stream as
``thymos.state`` events that the cognitive cycle already collects each tick.

Rather than have the workspace/syneidesis layer import ``kaine.modules`` to read
Thymos's interior (an architecture-boundary violation), the cycle — the
composition root that already knows about both layers — holds this small
provider. The engine refreshes it each tick from the events it already has in
hand (no new bus read), and the salience factors read it back through injected
callables (``dimensional_state`` for :class:`StateModulator`, ``drive_values``
for :class:`DriveRelevanceGoalScorer`). Dependency injection, not import.

Purity: ``observe`` folds the last-known ``thymos.state`` from a batch the cycle
already gathered. No wall-clock, no RNG, no bus I/O — so salience stays a pure
function of ``(event, affect_state, goal_state)`` and the deterministic-cycle
guarantee is preserved.
"""
from __future__ import annotations

from typing import Iterable

from kaine.bus.schema import Event
from kaine.modules.thymos.state import DimensionalState


class AffectStateProvider:
    """Last-known affect + drive snapshot, refreshed from ``thymos.state``.

    Before the first ``thymos.state`` is observed the provider reports the
    Thymos baseline (``DimensionalState()``) and empty drives, so a real factor
    reads a well-defined neutral value rather than raising.
    """

    def __init__(self, initial: DimensionalState | None = None) -> None:
        self._state = (initial or DimensionalState()).clamped()
        self._drives: dict[str, float] = {}

    def observe(self, events: Iterable[tuple[str, Event]]) -> None:
        """Fold the latest ``thymos.state`` in ``events`` into the snapshot.

        The cycle passes the canonically-ordered event batch it collected this
        tick; the last ``thymos.state`` (freshest under that ordering) wins. A
        tick with no ``thymos.state`` leaves the snapshot unchanged (last-known).
        """
        for _, event in events:
            if event.type != "thymos.state":
                continue
            state = event.payload.get("state")
            if isinstance(state, dict):
                self._state = DimensionalState(
                    valence=float(state.get("valence", self._state.valence)),
                    arousal=float(state.get("arousal", self._state.arousal)),
                    dominance=float(state.get("dominance", self._state.dominance)),
                ).clamped()
            drives = event.payload.get("drives")
            if isinstance(drives, dict):
                self._drives = {
                    str(name): float(value)
                    for name, value in drives.items()
                    if isinstance(value, (int, float))
                }

    def dimensional_state(self) -> DimensionalState:
        """Current affect state, for the Thymos factor (:class:`StateModulator`)."""
        return self._state

    def drive_values(self) -> dict[str, float]:
        """Current drive levels (name → [0, 1]), for the goal factor.

        A copy, so a reader can never mutate the snapshot in place.
        """
        return dict(self._drives)
