# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Unattended boot gate: nine-condition safety net.

The unattended supervision mode is *not* a research run: it reuses the
research safety net's evaluator for conditions 1 to 6 and 9 (every check the net
makes, the supervisor's self-test included), then adds two more gates (caretaker
notice, continuous input) before the entity may start without a person present.

This module is pure over its inputs except for the research-net round-trip,
which is executed by :func:`kaine.cycle.research_gate.evaluate_safety_net`.
"""
from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

# Condition and CONDITION_NAMES live in gate_conditions, which imports no
# gate, so the condition builders (the supervisor self-test, the caretaker
# and the input check) can use them without importing this module.
from kaine.cycle.gate_conditions import CONDITION_NAMES, Condition
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


# every check the research net returns must appear here, so the unattended gate covers the whole net
SAFETY_NET_CONDITIONS: dict[str, int] = {
    "preservation_enabled": 1,
    "welfare_response_wired": 2,
    # The indicator response is part of the welfare response: condition 2
    # holds only when both are wired.
    "indicator_response_wired": 2,
    "logging_active": 3,
    "dry_self_check_passed": 4,
    "encryption_satisfied": 5,
    "supervisor_armed": 6,
    "individuation_enabled": 9,
}

#: Conditions supplied outside the research net.
BUILT_CONDITIONS: tuple[int, ...] = (7, 8)


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


#: Fallback failure reason per research-net check, used when the net gives none.
_FALLBACK_REASONS: dict[str, str] = {
    "preservation_enabled": "[preservation.divergence_monitor].enabled is false",
    "welfare_response_wired": "[preservation.welfare_response].enabled is false",
    "logging_active": "neither [evaluation] nor [research_event_log] is enabled",
    "dry_self_check_passed": "the dry preserve→revive round-trip did not pass on this install",
    "encryption_satisfied": "[preservation].require_encryption is true but [security.state_encryption] is off",
    "supervisor_armed": "the supervisor is not armed and self-tested",
    "indicator_response_wired": "the welfare response to the welfare indicators is not wired",
    "individuation_enabled": "[individuation].enabled is false, its configuration is invalid, or the language module is disabled",
}


def conditions_from_safety_net(net: GateResult) -> list[Condition]:
    """Map every check of the shared research net to its numbered unattended condition.

    The mapping uses the net's ``checks`` dict; a missing key is treated as
    failed. A condition that several checks map to holds only when all of them
    hold. Each failed check's reason comes from the net's ``reasons`` when it
    gives one (condition 6 carries the supervisor self-test's own reason) and
    from a fixed, config-key specific table otherwise.
    """
    net_reasons = getattr(net, "reasons", None) or {}
    by_number: dict[int, list[str]] = {}
    for key, number in SAFETY_NET_CONDITIONS.items():
        by_number.setdefault(number, []).append(key)
    out: list[Condition] = []
    for number in sorted(by_number):
        failed_reasons: list[str] = []
        for key in by_number[number]:
            if bool(net.checks.get(key, False)):
                continue
            reason = str(net_reasons.get(key) or "").strip() or _FALLBACK_REASONS[key]
            failed_reasons.append(reason)
        out.append(
            Condition(
                number=number,
                name=CONDITION_NAMES[number],
                ok=not failed_reasons,
                reason="; ".join(failed_reasons),
            )
        )
    return out


@dataclass(frozen=True)
class UnattendedGateResult:
    """Outcome of :func:`evaluate_unattended_gate`."""

    conditions: tuple[Condition, ...]

    @property
    def ok(self) -> bool:
        """True only when all nine conditions are present and passed."""
        numbers = {c.number for c in self.conditions}
        return (
            len(self.conditions) == 9
            and numbers == set(range(1, 10))
            and all(c.ok for c in self.conditions)
        )

    @property
    def failed(self) -> tuple[Condition, ...]:
        return tuple(c for c in self.conditions if not c.ok)

    @property
    def checks(self) -> dict[str, bool]:
        """Numbered condition names (underscore-normalised) → pass/fail.

        The insertion order follows condition number 1 to 9 so runtime.json and
        the dashboard render the list deterministically.
        """
        ordered = sorted(self.conditions, key=lambda c: c.number)
        return {
            f"{c.number}_{c.name}".replace(" ", "_").replace("-", "_"): c.ok
            for c in ordered
        }

    def message(self) -> str:
        if self.ok:
            return "Unattended gate VERIFIED: all nine conditions passed."
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

    Conditions 1 to 6 and 9 come from the research net (condition 6 is the
    supervisor's self-test, run once inside the net).  Conditions 7 and 8 come
    from ``built`` when supplied; until then they fail with
    :data:`NOT_BUILT_REASON`.

    ``built`` may only contain keys ``7`` or ``8``, and each supplied
    :class:`Condition` must carry the matching number.
    """
    base = conditions_from_safety_net(net)
    built = built or {}

    for number in built:
        if number not in BUILT_CONDITIONS:
            raise ValueError(
                f"only conditions 7 and 8 may be supplied outside the research net, "
                f"got {number}"
            )

    conditions: list[Condition] = []
    conditions.extend(base)
    for number in BUILT_CONDITIONS:
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

    return UnattendedGateResult(conditions=tuple(sorted(conditions, key=lambda c: c.number)))


__all__ = [
    "UNATTENDED_GATE_EXIT_CODE",
    "SUPERVISION_MODES",
    "SupervisionConfigError",
    "unattended_mode_requested",
    "resolve_supervision_mode",
    "CONDITION_NAMES",
    "SAFETY_NET_CONDITIONS",
    "BUILT_CONDITIONS",
    "Condition",
    "NOT_BUILT_REASON",
    "not_built",
    "conditions_from_safety_net",
    "UnattendedGateResult",
    "evaluate_unattended_gate",
]
