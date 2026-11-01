# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The unattended gate's numbered conditions: their names and their result type.

A leaf module: it imports no gate. The gates and the modules that build one
condition each (the supervisor self-test, the caretaker notice, the input
check) all take these from here, so building a condition never imports the
gate that evaluates it. :mod:`kaine.cycle.unattended_gate` re-exports both.
"""
from __future__ import annotations

from dataclasses import dataclass

CONDITION_NAMES: dict[int, str] = {
    1: "preservation enabled",
    2: "welfare and indicator responses wired",
    3: "logging active",
    4: "preserve-revive round-trip",
    5: "encryption satisfied",
    6: "Supervisor armed and self-tested",
    7: "caretaker told",
    8: "continuous input",
    9: "individuation wired",
}


@dataclass(frozen=True)
class Condition:
    """One gate condition result."""

    number: int
    name: str
    ok: bool
    reason: str = ""


__all__ = ["CONDITION_NAMES", "Condition"]
