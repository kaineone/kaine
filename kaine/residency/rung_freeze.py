# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Freeze rung selection for deterministic and study runs.

When [experiment].deterministic is true or a study config is active, the
speech rungs selected at boot are frozen. A component whose frozen rung
fails to load at runtime is recorded as a residency failure and an
incident; no substitute rung is tried.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger(__name__)


@dataclass
class RungLoadFailure:
    component: str
    rung_key: str
    reason: str


@dataclass
class FrozenRungs:
    """Immutable rung assignments recorded at boot for a deterministic/study run."""

    components: dict[str, str] = field(default_factory=dict)
    failures: list[RungLoadFailure] = field(default_factory=list)

    def is_frozen(self, component: str) -> bool:
        return component in self.components

    def expected_rung(self, component: str) -> str | None:
        return self.components.get(component)

    def record_failure(self, component: str, reason: str) -> RungLoadFailure:
        rung = self.components.get(component, "unknown")
        failure = RungLoadFailure(component=component, rung_key=rung, reason=reason)
        self.failures.append(failure)
        log.warning(
            "frozen rung load failure: %s rung=%s reason=%s",
            component, rung, reason,
        )
        return failure


_active: Optional[FrozenRungs] = None


def freeze_rungs(components: dict[str, str]) -> FrozenRungs:
    """Set process-global frozen rungs. Call once at boot in deterministic/study mode."""
    global _active
    _active = FrozenRungs(components=dict(components))
    log.info("rungs frozen for deterministic/study run: %s", components)
    return _active


def get_frozen_rungs() -> Optional[FrozenRungs]:
    """Return the active frozen rungs, or None outside a deterministic/study run."""
    return _active


def clear_frozen_rungs() -> None:
    """Clear process-global frozen rungs (for testing)."""
    global _active
    _active = None
