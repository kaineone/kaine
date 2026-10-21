# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The housekeeping pressure shared by sleep and the awake floor.

Implements the pressure of paper 3.5 and appendix A.5: the sum over the
resources (disk, host memory, episodic store) of each fractional excess
over its budget. Sleep replaces the terms after every housekeeping pass;
an excess measured by the awake floor raises the disk term until the
next sleep replaces it. An excess left over by an aborted or
out-of-time pass therefore carries over as debt.
"""

from __future__ import annotations

import math
from typing import Any, Mapping


class HousekeepingPressure:
    """The disk, memory, and episodic pressure terms and their sum."""

    def __init__(self) -> None:
        self.disk = 0.0
        self.memory = 0.0
        self.episodic = 0.0

    def set_from_sleep(self, report: Mapping[str, Any]) -> None:
        """Replace the three terms from a sleep housekeeping report.

        The finite non-negative ``disk``, ``memory``, and ``episodic``
        values of the report's ``terms`` dict become the new terms;
        missing or bad values give 0.0. A report without a terms dict
        (disabled or failed housekeeping) changes nothing, so the last
        excess carries over.
        """
        terms = report.get("terms")
        if not isinstance(terms, dict):
            return
        self.disk = _term(terms.get("disk"))
        self.memory = _term(terms.get("memory"))
        self.episodic = _term(terms.get("episodic"))

    def note_floor_disk_excess(self, excess: float) -> None:
        """Raise the disk term to the awake floor's measured excess.

        The disk term becomes ``max(current, excess)`` for a finite
        non-negative excess and is unchanged otherwise. The floor's
        measured excess counts until the next sleep replaces the terms.
        """
        if _is_finite_non_negative(excess):
            self.disk = max(self.disk, float(excess))

    def value(self) -> float:
        """Return the pressure, the sum of the three terms."""
        return self.disk + self.memory + self.episodic

    def reset(self) -> None:
        """Set all three terms to zero."""
        self.disk = 0.0
        self.memory = 0.0
        self.episodic = 0.0


def _is_finite_non_negative(value: Any) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value >= 0
    )


def _term(value: Any) -> float:
    if _is_finite_non_negative(value):
        return float(value)
    return 0.0


_SHARED = HousekeepingPressure()


def shared_pressure() -> HousekeepingPressure:
    """Return the process-wide shared housekeeping pressure."""
    return _SHARED
