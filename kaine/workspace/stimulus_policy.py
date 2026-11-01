# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Stage M of the stimulus-control act: the drive-led act after maturation.

A policy wrapper (like the planning proposal source) around the configured
action-selection policy. Installed only when ``[stimulus_control].enabled`` is
true and the operator's effector whitelist names the ``stimulus`` effector; off,
the policy is exactly the wrapped one.

The rule (openspec change ``stimulus-control-act``, design D4). On a
non-inhibited broadcast whose leading member, the coalition member with the
highest salience score, is the entity's own boredom or restlessness drive event
(``affect.drive``, a crossing or a re-entry of a current concern), once the
minimum command interval has passed since the last stimulus act, the wrapper
adds one signed ``act`` intent naming the ``stimulus`` effector. The action is
drawn uniformly from the actions the programme would take now, with a generator
seeded from the run seed. No act forms in the developmental phase.

Why this trigger: boredom is "the aversive experience of wanting, but being
unable, to engage in satisfying activity" (Eastwood, Frischen, Fenske and
Smilek 2012, Perspect Psychol Sci 7:482-495); it motivates the pursuit of new goals and experiences (Bench and
Lench 2013, Behav Sci 3:459-472) and signals the opportunity cost of staying
with the current activity, which favours switching (Agrawal, Mattar, Cohen and
Daw 2022, Psych Rev 129:564-585). Restlessness is the drive for action of the
paper's A.4, which builds while the entity does not act; acting on one's
surroundings to have an effect on them is itself a motive, the tendency to
explore and influence one's environment (effectance; White 1959, Psych Rev
66:297-333, doi:10.1037/h0040934). The link from these drives to an act on the input is that cited
function; which action relieves what is not given: the draw is uniform, and
what follows is left to the world (the credit window of the affect module and
the readout record what does). A fixed mapping such as boredom to ``next``
would hard-wire behaviour the entity can learn; an act bar on salience alone
would skip content when it is most engaging (design D4).

The workspace layer never imports the modules: the allowed actions, the clock
and the developmental probe are injected.
"""
from __future__ import annotations

import random
from typing import Any, Callable, Optional, Sequence

from kaine.cycle.types import WorkspaceSnapshot
from kaine.workspace.action_selection import ACT, Intent

STIMULUS_EFFECTOR = "stimulus"
AFFECT_SOURCE = "affect"
AFFECT_DRIVE_TYPE = "affect.drive"
TRIGGER_DRIVES = frozenset({"boredom", "restlessness"})


def stage_m_generator(seed: int) -> random.Random:
    """The run-seeded generator of the uniform draw (its own stream, not global randomness)."""
    return random.Random(f"kaine.stimulus-control.stage-m:{int(seed)}")


class StimulusActSource:
    """Adds at most one drive-led stimulus act intent per broadcast."""

    def __init__(
        self,
        inner: Any,
        *,
        allowed_actions: Callable[[], Sequence[str]],
        min_interval_s: float,
        clock: Callable[[], float],
        seed: int,
        developing: Optional[Callable[[], bool]] = None,
        ready: Optional[Callable[[], bool]] = None,
    ) -> None:
        self._inner = inner
        # The effector's own interval check, read when the intent forms: the act
        # is realized later, so an act formed when it is ready is ready then too.
        self._ready = ready
        self._allowed_actions = allowed_actions
        self._min_interval_s = float(min_interval_s)
        self._clock = clock
        self._rng = stage_m_generator(seed)
        self._developing = developing
        self._last_act_at = float("-inf")

    @property
    def inner(self) -> Any:
        return self._inner

    def __getattr__(self, name: str) -> Any:
        # Guards, realization hooks and properties of the wrapped policy
        # (speak_in_flight, mark_realized, ...) stay reachable through the wrapper.
        if name.startswith("__"):
            raise AttributeError(name)
        return getattr(self._inner, name)

    @staticmethod
    def _leading(snapshot: WorkspaceSnapshot) -> tuple[str, Any] | None:
        scores = snapshot.salience_scores or {}
        members = list(snapshot.selected_events)
        if not members:
            return None
        return max(members, key=lambda m: float(scores.get(m[0], 0.0)))

    def _stimulus_intent(self, snapshot: WorkspaceSnapshot) -> Intent | None:
        if snapshot.inhibited:
            return None
        if self._developing is not None and self._developing():
            return None
        lead = self._leading(snapshot)
        if lead is None:
            return None
        entry_id, event = lead
        if getattr(event, "source", None) != AFFECT_SOURCE or event.type != AFFECT_DRIVE_TYPE:
            return None
        payload = event.payload if isinstance(event.payload, dict) else {}
        drive = payload.get("drive")
        if drive not in TRIGGER_DRIVES:
            return None
        now = float(self._clock())
        if now - self._last_act_at < self._min_interval_s:
            return None
        if self._ready is not None and not self._ready():
            return None
        allowed = list(self._allowed_actions())
        if not allowed:
            return None
        action = allowed[self._rng.randrange(len(allowed))]
        self._last_act_at = now
        return Intent(
            kind=ACT,
            about=str(drive),
            entry_id=entry_id or None,
            effector=STIMULUS_EFFECTOR,
            params={"action": action},
            about_kind="felt",
            origin="stimulus_stage_m",
        )

    def __call__(self, snapshot: WorkspaceSnapshot) -> list[Intent]:
        intents = list(self._inner(snapshot))
        intent = self._stimulus_intent(snapshot)
        if intent is not None:
            intents.append(intent)
        return intents


__all__ = [
    "STIMULUS_EFFECTOR",
    "StimulusActSource",
    "TRIGGER_DRIVES",
    "stage_m_generator",
]
