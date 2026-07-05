# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Shared verdict vocabulary for experiments.

One schema so every experiment reports outcomes the same way: the active-
inference benchmark reports WIN / NULL / NEGATIVE (comparative), the enforcement
red-team reports PASS / FAIL (a safety gate). Adoption is additive — each report
includes a ``verdict`` object using this schema alongside its existing fields.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Outcome(str, Enum):
    """The shared outcome vocabulary.

    Comparative experiments use WIN / NULL / NEGATIVE; safety gates use
    PASS / FAIL. Being a ``str`` Enum, members serialize to their plain string
    value in JSON.
    """

    WIN = "WIN"
    NULL = "NULL"
    NEGATIVE = "NEGATIVE"
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
