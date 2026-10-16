# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Goal ledger for the affect module.

Goals carry priority, relevance, and lifecycle state. The `relevance`
score against an event is token-overlap-weighted-by-priority — crude
v1, sized for the protocol shape so Phase 7 can replace with
embeddings.

Goals may name the drive they relieve and carry an expected-relief
likelihood, per paper A.4.
"""
from __future__ import annotations

import logging
import math
import re
import time
import uuid
from dataclasses import dataclass, replace
from enum import Enum
from typing import Any, ClassVar, Optional

_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")
log = logging.getLogger(__name__)


class GoalState(str, Enum):
    ACTIVE = "active"
    COMPLETED = "completed"
    ABANDONED = "abandoned"


@dataclass(frozen=True)
class Goal:
    id: str
    description: str
    priority: float  # [0, 1]
    state: GoalState = GoalState.ACTIVE
    created_at: float = 0.0
    completed_at: Optional[float] = None
    drive: Optional[str] = None
    likelihood: Optional[float] = None

    def tokens(self) -> set[str]:
        return {t.lower() for t in _TOKEN_RE.findall(self.description)}


class GoalLedger:
    MAX_FINISHED: ClassVar[int] = 256

    def __init__(self, *, clock: Optional[callable] = None) -> None:
        self._goals: dict[str, Goal] = {}
        self._clock = clock or time.time
        self._completed_total = 0
        self._abandoned_total = 0

    def __len__(self) -> int:
        return len(self._goals)

    def all(self) -> list[Goal]:
        return list(self._goals.values())

    def active(self) -> list[Goal]:
        return [g for g in self._goals.values() if g.state == GoalState.ACTIVE]

    def get(self, goal_id: str) -> Goal:
        return self._goals[goal_id]

    def add(
        self,
        description: str,
        *,
        priority: float = 0.5,
        drive: Optional[str] = None,
        likelihood: Optional[float] = None,
    ) -> Goal:
        if not 0.0 <= priority <= 1.0:
            raise ValueError("priority must be in [0, 1]")
        if not description.strip():
            raise ValueError("description must be non-empty")
        if drive is not None:
            if not isinstance(drive, str) or not drive:
                raise ValueError("drive must be a non-empty string")
        if likelihood is not None:
            if not math.isfinite(likelihood) or not 0.0 <= likelihood <= 1.0:
                raise ValueError("likelihood must be a finite number in [0, 1]")
        gid = uuid.uuid4().hex
        goal = Goal(
            id=gid,
            description=description.strip(),
            priority=float(priority),
            state=GoalState.ACTIVE,
            created_at=float(self._clock()),
            completed_at=None,
            drive=drive,
            likelihood=likelihood,
        )
        self._goals[gid] = goal
        return goal

    def complete(self, goal_id: str) -> Goal:
        return self._transition(goal_id, GoalState.COMPLETED)

    def abandon(self, goal_id: str) -> Goal:
        return self._transition(goal_id, GoalState.ABANDONED)

    def outcome_counts(self) -> tuple[int, int]:
        """The completed and abandoned counts that supply the ledger term's power for coping potential (paper A.4)."""
        return self._completed_total, self._abandoned_total

    def active_for_drive(self, drive: str) -> Optional[Goal]:
        matches = [g for g in self._goals.values() if g.drive == drive and g.state == GoalState.ACTIVE]
        if not matches:
            return None
        return min(matches, key=lambda g: (g.created_at, g.id))

    def set_likelihood(self, goal_id: str, likelihood: float) -> Goal:
        if goal_id not in self._goals:
            raise KeyError(f"unknown goal id {goal_id!r}")
        if not math.isfinite(likelihood) or not 0.0 <= likelihood <= 1.0:
            raise ValueError("likelihood must be a finite number in [0, 1]")
        old = self._goals[goal_id]
        if old.state != GoalState.ACTIVE:
            return old
        new = replace(old, likelihood=float(likelihood))
        self._goals[goal_id] = new
        return new

    def clear_active(self) -> list[Goal]:
        removed: list[Goal] = []
        to_delete: list[str] = []
        for goal_id, goal in self._goals.items():
            if goal.state == GoalState.ACTIVE:
                to_delete.append(goal_id)
                removed.append(goal)
        for goal_id in to_delete:
            del self._goals[goal_id]
        return removed

    def _transition(self, goal_id: str, new_state: GoalState) -> Goal:
        if goal_id not in self._goals:
            raise KeyError(f"unknown goal id {goal_id!r}")
        old = self._goals[goal_id]
        if old.state != GoalState.ACTIVE:
            return old
        new = Goal(
            id=old.id,
            description=old.description,
            priority=old.priority,
            state=new_state,
            created_at=old.created_at,
            completed_at=float(self._clock()),
            drive=old.drive,
            likelihood=old.likelihood,
        )
        self._goals[goal_id] = new
        if new_state == GoalState.COMPLETED:
            self._completed_total += 1
        elif new_state == GoalState.ABANDONED:
            self._abandoned_total += 1
        self._prune_finished()
        return new

    def _prune_finished(self) -> None:
        finished = [
            (goal_id, goal)
            for goal_id, goal in self._goals.items()
            if goal.state != GoalState.ACTIVE
        ]
        if len(finished) <= self.MAX_FINISHED:
            return
        # A restored finished goal may lack completed_at; it counts as oldest.
        finished.sort(
            key=lambda item: (
                item[1].completed_at if item[1].completed_at is not None else -math.inf,
                item[1].created_at,
                item[1].id,
            )
        )
        for goal_id, _ in finished[: len(finished) - self.MAX_FINISHED]:
            del self._goals[goal_id]

    def relevance(self, event_text: str) -> float:
        """Token-overlap-weighted-by-priority relevance over active goals.

        This is a bag-of-words heuristic (token_overlap_v1), not semantic
        similarity.  Consumers of goal_significance in published events
        should treat it as an approximation only.

        Returns 0.0 when no goals are registered (avoids spurious small
        positive scores from the degenerate empty-goals case).
        """
        active = [g for g in self._goals.values() if g.state == GoalState.ACTIVE]
        if not active:
            return 0.0
        ev_tokens = {t.lower() for t in _TOKEN_RE.findall(event_text)}
        if not ev_tokens:
            return 0.0
        best = 0.0
        for goal in active:
            g_tokens = goal.tokens()
            if not g_tokens:
                continue
            overlap = len(ev_tokens & g_tokens)
            denom = max(len(g_tokens), 1)
            score = (overlap / denom) * goal.priority
            if score > best:
                best = score
        return min(1.0, max(0.0, best))

    def to_dict(self) -> dict[str, Any]:
        return {
            "goals": [
                {
                    "id": g.id,
                    "description": g.description,
                    "priority": g.priority,
                    "state": g.state.value,
                    "created_at": g.created_at,
                    "completed_at": g.completed_at,
                    "drive": g.drive,
                    "likelihood": g.likelihood,
                }
                for g in self._goals.values()
            ],
            "outcomes": {
                "completed": self._completed_total,
                "abandoned": self._abandoned_total,
            },
        }

    def load_dict(self, data: Any) -> None:
        """Replace this ledger's goals from a serialized dictionary.

        The ledger is left unchanged unless ``data`` is a dict with a
        list-valued ``goals`` key and every entry is parsed successfully.
        """
        if not isinstance(data, dict):
            log.warning("goal ledger: refusing to load from non-dict data: %r", data)
            return
        goals = data.get("goals")
        if not isinstance(goals, list):
            log.warning(
                "goal ledger: refusing to load from non-list goals: %r", goals
            )
            return
        parsed: dict[str, Goal] = {}
        for entry in goals:
            if not isinstance(entry, dict):
                log.warning("goal ledger: dropping non-dict goal entry: %r", entry)
                continue
            goal = self._parse_goal(entry)
            if goal is None:
                continue
            parsed[goal.id] = goal
        self._goals = parsed
        self._set_counters(data, parsed)

    @classmethod
    def from_dict(cls, data: Any) -> GoalLedger:
        ledger = cls()
        ledger.load_dict(data)
        return ledger

    def _set_counters(self, data: dict[str, Any], parsed: dict[str, Goal]) -> None:
        outcomes = data.get("outcomes")
        if isinstance(outcomes, dict):
            completed_raw = outcomes.get("completed")
            abandoned_raw = outcomes.get("abandoned")
            if (
                isinstance(completed_raw, int)
                and not isinstance(completed_raw, bool)
                and completed_raw >= 0
                and isinstance(abandoned_raw, int)
                and not isinstance(abandoned_raw, bool)
                and abandoned_raw >= 0
            ):
                self._completed_total = completed_raw
                self._abandoned_total = abandoned_raw
                return
        self._completed_total = sum(
            1 for g in parsed.values() if g.state == GoalState.COMPLETED
        )
        self._abandoned_total = sum(
            1 for g in parsed.values() if g.state == GoalState.ABANDONED
        )

    @staticmethod
    def _parse_goal(entry: dict[str, Any]) -> Optional[Goal]:
        gid = entry.get("id")
        description = entry.get("description")
        if not isinstance(gid, str) or not gid:
            log.warning("goal ledger: dropping goal entry with missing id: %r", entry)
            return None
        if not isinstance(description, str) or not description.strip():
            log.warning(
                "goal ledger: dropping goal entry %r with missing description", gid
            )
            return None
        try:
            priority = float(entry["priority"])
        except (KeyError, TypeError, ValueError):
            log.warning("goal ledger: dropping goal entry %r with invalid priority", gid)
            return None
        if not math.isfinite(priority) or not 0.0 <= priority <= 1.0:
            log.warning(
                "goal ledger: dropping goal entry %r with priority outside [0,1]: %r",
                gid,
                priority,
            )
            return None
        try:
            state = GoalState(entry["state"])
        except (KeyError, ValueError, TypeError):
            log.warning(
                "goal ledger: dropping goal entry %r with invalid state: %r",
                gid,
                entry.get("state"),
            )
            return None
        try:
            created_at = float(entry.get("created_at", 0.0))
        except (TypeError, ValueError):
            log.warning(
                "goal ledger: dropping goal entry %r with invalid created_at: %r",
                gid,
                entry.get("created_at"),
            )
            return None
        if not math.isfinite(created_at):
            log.warning(
                "goal ledger: dropping goal entry %r with non-finite created_at: %r",
                gid,
                created_at,
            )
            return None
        completed_raw = entry.get("completed_at")
        if completed_raw is None:
            completed_at: Optional[float] = None
        else:
            try:
                completed_at = float(completed_raw)
            except (TypeError, ValueError):
                log.warning(
                    "goal ledger: dropping goal entry %r with invalid completed_at: %r",
                    gid,
                    completed_raw,
                )
                return None
            if not math.isfinite(completed_at):
                log.warning(
                    "goal ledger: dropping goal entry %r with non-finite completed_at: %r",
                    gid,
                    completed_at,
                )
                return None
        drive = GoalLedger._parse_drive(entry.get("drive"))
        likelihood = GoalLedger._parse_likelihood(entry.get("likelihood"))
        if drive is False or likelihood is False:
            return None
        return Goal(
            id=gid,
            description=description.strip(),
            priority=priority,
            state=state,
            created_at=created_at,
            completed_at=completed_at,
            drive=drive,
            likelihood=likelihood,
        )

    @staticmethod
    def _parse_drive(value: Any) -> Any:
        if value is None:
            return None
        if not isinstance(value, str) or not value:
            log.warning("goal ledger: dropping goal entry with invalid drive: %r", value)
            return False
        return value

    @staticmethod
    def _parse_likelihood(value: Any) -> Any:
        if value is None:
            return None
        try:
            likelihood = float(value)
        except (TypeError, ValueError):
            log.warning("goal ledger: dropping goal entry with invalid likelihood: %r", value)
            return False
        if not math.isfinite(likelihood) or not 0.0 <= likelihood <= 1.0:
            log.warning(
                "goal ledger: dropping goal entry with likelihood outside [0,1]: %r",
                likelihood,
            )
            return False
        return likelihood
