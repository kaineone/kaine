# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Goal ledger for Thymos.

Goals carry priority, relevance, and lifecycle state. The `relevance`
score against an event is token-overlap-weighted-by-priority — crude
v1, sized for the protocol shape so Phase 7 can replace with
embeddings.
"""
from __future__ import annotations

import logging
import math
import re
import time
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional

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

    def tokens(self) -> set[str]:
        return {t.lower() for t in _TOKEN_RE.findall(self.description)}


class GoalLedger:
    def __init__(self, *, clock: Optional[callable] = None) -> None:
        self._goals: dict[str, Goal] = {}
        self._clock = clock or time.time

    def __len__(self) -> int:
        return len(self._goals)

    def all(self) -> list[Goal]:
        return list(self._goals.values())

    def active(self) -> list[Goal]:
        return [g for g in self._goals.values() if g.state == GoalState.ACTIVE]

    def get(self, goal_id: str) -> Goal:
        return self._goals[goal_id]

    def add(self, description: str, *, priority: float = 0.5) -> Goal:
        if not 0.0 <= priority <= 1.0:
            raise ValueError("priority must be in [0, 1]")
        if not description.strip():
            raise ValueError("description must be non-empty")
        gid = uuid.uuid4().hex
        goal = Goal(
            id=gid,
            description=description.strip(),
            priority=float(priority),
            created_at=float(self._clock()),
        )
        self._goals[gid] = goal
        return goal

    def complete(self, goal_id: str) -> Goal:
        return self._transition(goal_id, GoalState.COMPLETED)

    def abandon(self, goal_id: str) -> Goal:
        return self._transition(goal_id, GoalState.ABANDONED)

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
        )
        self._goals[goal_id] = new
        return new

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
                }
                for g in self._goals.values()
            ]
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

    @classmethod
    def from_dict(cls, data: Any) -> GoalLedger:
        ledger = cls()
        ledger.load_dict(data)
        return ledger

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
        return Goal(
            id=gid,
            description=description.strip(),
            priority=priority,
            state=state,
            created_at=created_at,
            completed_at=completed_at,
        )
