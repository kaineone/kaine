# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Goal ledger for Thymos.

Goals carry priority, relevance, and lifecycle state. The `relevance`
score against an event is token-overlap-weighted-by-priority — crude
v1, sized for the protocol shape so Phase 7 can replace with
embeddings.
"""
from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable, Optional


_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")


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
