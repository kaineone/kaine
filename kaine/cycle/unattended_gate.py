# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Unattended boot gate — eight-condition safety net.

The unattended supervision mode is *not* a research run: it reuses the
research safety net's evaluator for conditions 1–5, then adds three more
gates (Spot, caretaker notice, continuous input) before the entity may start
without a person present.

This module is pure over its inputs except for the research-net round-trip,
which is executed by :func:`kaine.cycle.research_gate.evaluate_safety_net`.
"""
from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

from kaine.cycle.research_gate import GateResult, research_mode_requested

UNATTENDED_GATE_EXIT_CODE = 6

SUPERVISION_MODES = ("operator", "unattended")


class SupervisionConfigError(ValueError):
    """The supervision mode configuration is ambiguous or invalid."""


def unattended_mode_requested(
    config: dict[str, object], *, env: dict[str, str] | None = None
) -> bool:
    """True when unattended supervision is selected for this boot.

    ``KAINE_CYCLE_UNATTENDED=1`` in the environment takes precedence over
    ``[cycle].supervision_mode``.  Invalid config values raise
    :class:`SupervisionConfigError`; missing or ``"operator"`` values do not
    select unattended mode.
    """
    env = env if env is not None else os.environ
    if env.get("KAINE_CYCLE_UNATTENDED") == "1":
        return True

    value = (config.get("cycle") or {}).get("supervision_mode")
    if value is None:
        return False
    if not isinstance(value, str) or value not in SUPERVISION_MODES:
        raise SupervisionConfigError(
            "Invalid [cycle].supervision_mode: must be one of "
            f"{', '.join(SUPERVISION_MODES)}"
        )
    return value == "unattended"


def resolve_supervision_mode(
    config: dict[str, object], *, env: dict[str, str] | None = None
) -> str:
    """Resolve exactly one supervision mode for the boot.

    Returns ``"unattended"``, ``"research"``, or ``"operator"``.  Conflicting
    mode selectors (unattended together with research or the operator-present
    flag) raise :class:`SupervisionConfigError`.  Research together with the
    operator flag is not a conflict — research wins, unchanged from before.
    """
    env = env if env is not None else os.environ

    unattended = unattended_mode_requested(config, env=env)
    research = research_mode_requested(config, env=env)
    operator_flag = env.get("KAINE_CYCLE_OPERATOR_PRESENT") == "1"

    if unattended and (research or operator_flag):
        active = ["KAINE_CYCLE_UNATTENDED/[cycle].supervision_mode"]
        if research:
            active.append("KAINE_RESEARCH_MODE/[research].enabled")
        if operator_flag:
            active.append("KAINE_CYCLE_OPERATOR_PRESENT")
        raise SupervisionConfigError(" and ".join(active))

    if unattended:
        return "unattended"
    if research:
        return "research"
    return "operator"


CONDITION_NAMES: dict[int, str] = {
    1: "preservation enabled",
    2: "welfare response wired",
    3: "logging active",
    4: "preserve-revive round-trip",
    5: "encryption satisfied",
    6: "Spot armed and self-tested",
    7: "caretaker told",
    8: "continuous input",
}


@dataclass(frozen=True)
class Condition:
    """One gate condition result."""

    number: int
    name: str
    ok: bool
    reason: str = ""


NOT_BUILT_REASON = (
    "not built in this version of KAINE; unattended boots refuse until it is"
)


def not_built(number: int) -> Condition:
    """A placeholder condition for gates not yet implemented."""
    return Condition(
        number=number,
        name=CONDITION_NAMES[number],
        ok=False,
        reason=NOT_BUILT_REASON,
    )


def conditions_from_safety_net(net: GateResult) -> list[Condition]:
    """Map the shared five-condition research net to unattended conditions 1–5.

    The mapping uses the net's ``checks`` dict; a missing key is treated as
    failed.  Failure reasons are short and config-key specific so an operator
    knows what to fix.
    """
    reasons = {
        1: "[preservation.divergence_monitor].enabled is false",
        2: "[preservation.welfare_response].enabled is false",
        3: "neither [evaluation] nor [research_event_log] is enabled",
        4: "the dry preserve→revive round-trip did not pass on this install",
        5: "[preservation].require_encryption is true but [security.state_encryption] is off",
    }
    keys = [
        "preservation_enabled",
        "welfare_response_wired",
        "logging_active",
        "dry_self_check_passed",
        "encryption_satisfied",
    ]
    out: list[Condition] = []
    for number, key in enumerate(keys, start=1):
        ok = bool(net.checks.get(key, False))
        out.append(
            Condition(
                number=number,
                name=CONDITION_NAMES[number],
                ok=ok,
                reason="" if ok else reasons[number],
            )
        )
    return out


@dataclass(frozen=True)
class UnattendedGateResult:
    """Outcome of :func:`evaluate_unattended_gate`."""

    conditions: tuple[Condition, ...]

    @property
    def ok(self) -> bool:
        """True only when all eight conditions are present and passed."""
        numbers = {c.number for c in self.conditions}
        return (
            len(self.conditions) == 8
            and numbers == set(range(1, 9))
            and all(c.ok for c in self.conditions)
        )

    @property
    def failed(self) -> tuple[Condition, ...]:
        return tuple(c for c in self.conditions if not c.ok)

    @property
    def checks(self) -> dict[str, bool]:
        """Numbered condition names (underscore-normalised) → pass/fail.

        The insertion order follows condition number 1–8 so runtime.json and
        Nexus render the list deterministically.
        """
        ordered = sorted(self.conditions, key=lambda c: c.number)
        return {
            f"{c.number}_{c.name}".replace(" ", "_").replace("-", "_"): c.ok
            for c in ordered
        }

    def message(self) -> str:
        if self.ok:
            return "Unattended gate VERIFIED: all eight conditions passed."
        lines = [
            "Refusing to boot KAINE cycle: the unattended gate is not satisfied.",
            "",
        ]
        for c in self.failed:
            lines.append(f"  {c.number}: {c.name} — {c.reason}")
        no_override = (
            "An unattended boot has no override. Fix the conditions above, "
            "or start the entity supervised with KAINE_CYCLE_OPERATOR_PRESENT=1."
        )
        lines.extend(["", no_override])
        return "\n".join(lines)


def evaluate_unattended_gate(
    net: GateResult, *, built: Mapping[int, Condition] | None = None
) -> UnattendedGateResult:
    """Combine the shared safety net with the unattended-specific conditions.

    Conditions 1–5 come from the research net.  Conditions 6–8 come from
    ``built`` when supplied by a later slice; until then they fail with
    :data:`NOT_BUILT_REASON`.

    ``built`` may only contain keys ``6``, ``7`` or ``8``, and each supplied
    :class:`Condition` must carry the matching number.
    """
    base = conditions_from_safety_net(net)
    built = built or {}

    for number in built:
        if number not in (6, 7, 8):
            raise ValueError(
                f"only conditions 6, 7 and 8 may be supplied by later slices, "
                f"got {number}"
            )

    conditions: list[Condition] = []
    conditions.extend(base)
    for number in (6, 7, 8):
        if number in built:
            condition = built[number]
            if condition.number != number:
                raise ValueError(
                    f"built condition for {number} has mismatched "
                    f"condition.number {condition.number}"
                )
            conditions.append(condition)
        else:
            conditions.append(not_built(number))

    return UnattendedGateResult(conditions=tuple(conditions))


__all__ = [
    "UNATTENDED_GATE_EXIT_CODE",
    "SUPERVISION_MODES",
    "SupervisionConfigError",
    "unattended_mode_requested",
    "resolve_supervision_mode",
    "CONDITION_NAMES",
    "Condition",
    "NOT_BUILT_REASON",
    "not_built",
    "conditions_from_safety_net",
    "UnattendedGateResult",
    "evaluate_unattended_gate",
]
