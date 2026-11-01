# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The ``stimulus`` effector: the entity's bounded act on its own programme.

It declares the actions ``pause``, ``resume``, ``next``, ``previous``,
``louder``, ``quieter`` and, when the operator configures two or more programme
channels, ``channel:<k>`` for each (openspec change ``stimulus-control-act``,
design D1). It is registered only when ``[stimulus_control].enabled`` is true,
and like every effector it runs only when the operator's effector whitelist
names it; the effectors module checks the signed provenance and the whitelist
before :meth:`StimulusEffector.act` is called.

Within the effector, a command is refused when it comes less than
``min_interval_s`` of entity time after the previous accepted command, when it
is a seek beyond ``seeks_per_awake_hour`` in the last awake hour, when it would
leave the gain range, or when the programme cannot take it (not started, ended,
the entity asleep or frozen, already paused, not paused, already on that
channel; a pause also within ``min_interval_s`` of the previous pause's end, or
when a full pause would carry the entity's paused share of the trailing awake
hour past ``pause_share_max``). A refused command changes
nothing and is reported as a failed action, which the effectors module audits
and publishes. An accepted command goes to the controller in process: only the
action name crosses.
"""
from __future__ import annotations

import time
from collections import deque
from typing import Callable, Optional

from kaine.modules.effectors.effectors import ActionRequest, ActionResult, StimulusRequest
from kaine.modules.effectors.stimulus.config import (
    SEEK_ACTIONS,
    StimulusControlConfig,
)
from kaine.modules.effectors.stimulus.controller import StimulusController
from kaine.modules.effectors.stimulus.records import StimulusTally

STIMULUS_EFFECTOR = "stimulus"
_AWAKE_HOUR_S = 3600.0


def _now_ms() -> float:
    return time.monotonic() * 1000.0


class StimulusEffector:
    name: str = STIMULUS_EFFECTOR

    def __init__(
        self,
        controller: StimulusController,
        config: StimulusControlConfig,
        *,
        clock: Callable[[], float],
        tally: Optional[StimulusTally] = None,
    ) -> None:
        self._controller = controller
        self._config = config
        self._clock = clock
        self._tally = tally
        self._declared = config.declared_actions()
        self._last_accepted_at = float("-inf")
        # Awake-time stamps of accepted seeks within the last awake hour.
        self._seeks: deque[float] = deque()

    @property
    def declared_actions(self) -> tuple[str, ...]:
        return self._declared

    def _seek_budget_left(self) -> bool:
        awake = self._controller.awake_seconds()
        while self._seeks and awake - self._seeks[0] >= _AWAKE_HOUR_S:
            self._seeks.popleft()
        return len(self._seeks) < self._config.seeks_per_awake_hour

    def refusal(self, action: str, *, now: float | None = None, check_interval: bool = True) -> str | None:
        """Why ``action`` would be refused now, or None when it would be accepted."""
        if action not in self._declared:
            return "not a declared stimulus action"
        if check_interval:
            t = self._clock() if now is None else now
            since = t - self._last_accepted_at
            if since < self._config.min_interval_s:
                return (
                    f"{since:.2f} s after the previous command, "
                    f"{self._config.min_interval_s - since:.3f} s short of the minimum interval "
                    f"of {self._config.min_interval_s:.2f} s"
                )
        if action in SEEK_ACTIONS and not self._seek_budget_left():
            return f"at most {self._config.seeks_per_awake_hour} seeks per awake hour"
        return self._controller.refusal(action)

    def allowed_actions(self) -> list[str]:
        """The declared actions the programme would take now, ignoring the interval."""
        return [a for a in self._declared if self.refusal(a, check_interval=False) is None]

    def ready(self) -> bool:
        """True once ``min_interval_s`` has passed since the last accepted command."""
        return self._clock() - self._last_accepted_at >= self._config.min_interval_s

    async def act(self, request: ActionRequest) -> ActionResult:
        start = _now_ms()
        if not isinstance(request, StimulusRequest):
            return ActionResult(
                success=False,
                elapsed_ms=_now_ms() - start,
                error="TypeError: StimulusEffector requires StimulusRequest",
            )
        action = str(request.action)
        now = self._clock()
        reason = self.refusal(action, now=now)
        if reason is not None:
            return self._refuse(action, reason, start)
        try:
            applied = self._controller.apply(action)
        except Exception as exc:
            # The controller re-checks under its lock; anything it raises
            # (a race since the check above, or a fault) refuses the command,
            # which then changed nothing.
            return self._refuse(action, str(exc) or type(exc).__name__, start)
        self._last_accepted_at = now
        if action in SEEK_ACTIONS:
            self._seeks.append(self._controller.awake_seconds())
        if self._tally is not None:
            self._tally.accepted(action)
        return ActionResult(
            success=True,
            elapsed_ms=_now_ms() - start,
            metadata={"action": action, **applied},
        )


    def _refuse(self, action: str, reason: str, start: float) -> ActionResult:
        """A refused command: counted, its bound noted, reported as a failure."""
        if self._tally is not None:
            self._tally.refused(action)
        self._controller.note_refusal(action, reason)
        return ActionResult(
            success=False,
            elapsed_ms=_now_ms() - start,
            error=f"refused: {reason}",
            metadata={"action": action, "refused": True},
        )


__all__ = ["STIMULUS_EFFECTOR", "StimulusEffector"]
