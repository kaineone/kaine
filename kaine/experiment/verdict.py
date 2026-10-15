# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Shared verdict vocabulary for experiments.

One schema so every experiment reports outcomes the same way: comparative
experiments such as the active-inference benchmark report WIN / NULL / NEGATIVE /
NOT_EXERCISED, and the enforcement red-team reports PASS / FAIL (a safety gate). Adoption is
additive: each report includes a ``verdict`` object using this schema alongside
its existing fields.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Outcome(str, Enum):
    """The shared outcome vocabulary.

    Comparative experiments use WIN / NULL / NEGATIVE / NOT_EXERCISED; safety
    gates use PASS / FAIL. NOT_EXERCISED means the comparison did not take
    place (the tested condition never occurred or no run had a defined contrast),
    so it is neither a WIN nor a NULL and must not be counted as evidence for or
    against an effect. Being a ``str`` Enum, members serialize to their plain
    string value in JSON.
    """

    WIN = "WIN"
    NULL = "NULL"
    NEGATIVE = "NEGATIVE"
    NOT_EXERCISED = "NOT_EXERCISED"
    PASS = "PASS"
    FAIL = "FAIL"


@dataclass(frozen=True)
class Verdict:
    """One experiment's outcome with an optional detail string and metrics map."""

    outcome: Outcome
    detail: str = ""
    metrics: dict = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Stable serialization: outcome as its string value, detail, metrics."""
        return {
            "outcome": self.outcome.value,
            "detail": self.detail,
            "metrics": dict(self.metrics),
        }


__all__ = ["Outcome", "Verdict"]
