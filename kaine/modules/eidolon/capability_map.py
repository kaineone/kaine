# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Capability map builder for Eidolon self-inference.

Combines two sources:
- Praxis effector whitelist (what the entity *can* execute).
- Nous EFE policy-outcome history (what it has *successfully done*).

Only categorical/numeric summaries are stored — no raw content.
"""
from __future__ import annotations

import logging
from collections import Counter
from typing import Any, Optional

log = logging.getLogger(__name__)

# Maximum number of recent policy outcomes tracked per action label.
_MAX_OUTCOME_HISTORY = 256


class CapabilityMapBuilder:
    """Accumulates Nous policy events and builds the capability_map entry.

    Praxis whitelist entries are injected at construction time (and do not
    change at runtime); EFE policy outcomes accumulate via ``observe_policy``.
    """

    def __init__(self, whitelist_commands: Optional[list[str]] = None) -> None:
        # Sorted list of whitelisted command names from Praxis.
        self._whitelist: list[str] = sorted(whitelist_commands or [])
        # Count of Nous policy selections (action label → count).
        self._policy_counts: Counter[str] = Counter()
        # Running sum of EFE per action label (for mean EFE).
        self._efe_sums: dict[str, float] = {}

    # ------------------------------------------------------------------
    # Observation

    def observe_policy(self, payload: dict[str, Any]) -> None:
        """Record one nous.policy event.  Only the label and EFE are kept."""
        action = str(payload.get("policy") or "")
        if not action:
            return
        efe = float(payload.get("expected_free_energy") or 0.0)
        self._policy_counts[action] += 1
        self._efe_sums[action] = self._efe_sums.get(action, 0.0) + efe
        # Cap total unique action labels tracked.
        if len(self._policy_counts) > _MAX_OUTCOME_HISTORY:
            least = self._policy_counts.most_common()[:-1][-1][0]
            del self._policy_counts[least]
            self._efe_sums.pop(least, None)

    # ------------------------------------------------------------------
    # Build

    def build(self) -> dict[str, Any]:
        """Return the capability_map dict to write into SelfModel.

        ``effectors`` — whitelisted Praxis commands (what can be executed).
        ``policy_outcomes`` — per-action stats from Nous EFE history.

        If neither source has data yet the result is an empty dict.
        """
        capability_map: dict[str, Any] = {}
        if self._whitelist:
            capability_map["effectors"] = list(self._whitelist)
        if self._policy_counts:
            outcomes: dict[str, Any] = {}
            for action, count in self._policy_counts.items():
                mean_efe = self._efe_sums.get(action, 0.0) / count if count else 0.0
                outcomes[action] = {
                    "count": count,
                    "mean_efe": round(mean_efe, 6),
                }
            capability_map["policy_outcomes"] = outcomes
        return capability_map
