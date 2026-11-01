# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The stimulus-control welfare record and readout, per viewing.

One tally per boot (a viewing). The effector counts accepted and refused
commands by action, the controller accounts awake time, the time the
``entity`` pause holder held the programme, the time spent at each gain and the
programme items visited, and the affect module samples boredom, alert excess
and learning progress with a flag for whether the sample falls within the
credit window after the entity's own realized stimulus act.

The readout answers whether the component does its job: how often the entity
acts on its input, and what follows its acts compared with the rest of the
time (the share of time boredom is at or above its threshold, the mean alert
excess, which is novelty relative to the habituated rate, and the mean learning
progress), plus how many acts were followed by a fall of boredom within the
window.

CONTENT CONTRACT: counts, seconds, shares, means, gains, action names from the
declared set and item identifiers (channel index and manifest order). Never a
frame, a sample, a title, a path or any text.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any

from kaine.modules.effectors.stimulus.config import StimulusControlConfig

RECORD = "stimulus_control"
_OTHER_ACTION = "other"
_MAX_VISITS = 4096


@dataclass
class _Window:
    seconds: float = 0.0
    boredom_above_s: float = 0.0
    alert_excess_s: float = 0.0
    learning_progress_s: float = 0.0

    def add(self, dt: float, *, boredom_above: bool, alert_excess: float, learning_progress: float) -> None:
        self.seconds += dt
        if boredom_above:
            self.boredom_above_s += dt
        self.alert_excess_s += dt * alert_excess
        self.learning_progress_s += dt * learning_progress

    def summary(self) -> dict[str, float | None]:
        if self.seconds <= 0.0:
            return {
                "seconds": 0.0,
                "boredom_above_share": None,
                "mean_alert_excess": None,
                "mean_learning_progress": None,
            }
        return {
            "seconds": self.seconds,
            "boredom_above_share": self.boredom_above_s / self.seconds,
            "mean_alert_excess": self.alert_excess_s / self.seconds,
            "mean_learning_progress": self.learning_progress_s / self.seconds,
        }


class StimulusTally:
    """Thread-safe per-viewing tally behind the ``stimulus_control`` record."""

    def __init__(self, config: StimulusControlConfig) -> None:
        self._config = config
        self._lock = threading.Lock()
        declared = config.declared_actions()
        self._declared = frozenset(declared)
        self._accepted: dict[str, int] = {a: 0 for a in declared}
        self._refused: dict[str, int] = {a: 0 for a in declared}
        self._refused[_OTHER_ACTION] = 0
        self._auto_releases = 0
        self._awake_s = 0.0
        self._entity_paused_s = 0.0
        self._gain_s: dict[float, float] = {}
        self._visits: list[tuple[int, int]] = []
        self._visits_dropped = 0
        self._after = _Window()
        self._otherwise = _Window()
        self._window_open = False
        self._boredom_at_open: float | None = None
        self._boredom_last: float | None = None
        self._acts_observed = 0
        self._acts_boredom_fell = 0
        self._changed = False

    # -- writers ------------------------------------------------------------

    def accepted(self, action: str) -> None:
        with self._lock:
            if action in self._accepted:
                self._accepted[action] += 1
                self._changed = True

    def refused(self, action: str) -> None:
        with self._lock:
            key = action if action in self._declared else _OTHER_ACTION
            self._refused[key] += 1
            self._changed = True

    def auto_released(self) -> None:
        with self._lock:
            self._auto_releases += 1
            self._changed = True

    def account(self, dt: float, *, entity_paused: bool, gain_db: float) -> None:
        """Add ``dt`` seconds of awake time to the viewing."""
        if dt <= 0.0:
            return
        with self._lock:
            self._awake_s += dt
            if entity_paused:
                self._entity_paused_s += dt
            key = round(float(gain_db), 3)
            self._gain_s[key] = self._gain_s.get(key, 0.0) + dt
            self._changed = True

    def visit(self, channel: int, order: int) -> None:
        with self._lock:
            if len(self._visits) < _MAX_VISITS:
                self._visits.append((int(channel), int(order)))
            else:
                self._visits_dropped += 1
            self._changed = True

    def observe_affect(
        self,
        dt: float,
        *,
        awake: bool,
        in_window: bool,
        boredom: float,
        boredom_above: bool,
        alert_excess: float,
        learning_progress: float,
    ) -> None:
        """One affect update: ``dt`` seconds with these values."""
        with self._lock:
            if in_window and not self._window_open:
                self._window_open = True
                self._boredom_at_open = float(boredom)
            elif not in_window and self._window_open:
                self._window_open = False
                self._acts_observed += 1
                if self._boredom_at_open is not None and float(boredom) < self._boredom_at_open:
                    self._acts_boredom_fell += 1
                self._boredom_at_open = None
            self._boredom_last = float(boredom)
            if awake and dt > 0.0:
                target = self._after if in_window else self._otherwise
                target.add(
                    dt,
                    boredom_above=boredom_above,
                    alert_excess=max(0.0, float(alert_excess)),
                    learning_progress=max(0.0, float(learning_progress)),
                )
            self._changed = True

    # -- readers ------------------------------------------------------------

    def record(self) -> dict[str, Any]:
        with self._lock:
            return self._record_locked()

    def _record_locked(self) -> dict[str, Any]:
        awake_h = self._awake_s / 3600.0
        accepted_total = sum(self._accepted.values())
        gain_total = sum(self._gain_s.values())
        return {
            "record": RECORD,
            "stage": self._config.stage,
            "commands": dict(self._accepted),
            "refused": dict(self._refused),
            "auto_releases": self._auto_releases,
            "awake_s": self._awake_s,
            "acts_per_awake_hour": (accepted_total / awake_h) if awake_h > 0 else None,
            "entity_paused_share": (
                self._entity_paused_s / self._awake_s if self._awake_s > 0 else None
            ),
            "gain_seconds": {f"{g:+.1f}": s for g, s in sorted(self._gain_s.items())},
            "gain_mean_db": (
                sum(g * s for g, s in self._gain_s.items()) / gain_total
                if gain_total > 0
                else None
            ),
            "items_visited": [[c, o] for c, o in self._visits],
            "items_visited_dropped": self._visits_dropped,
            "readout": {
                "after_own_act": self._after.summary(),
                "otherwise": self._otherwise.summary(),
                "acts_observed": self._acts_observed,
                "acts_with_boredom_fall": self._acts_boredom_fell,
            },
        }

    def take_records(self) -> list[dict[str, Any]]:
        """The record when anything changed since the last take, else nothing.

        Records are cumulative for the viewing, so the last one written is the
        viewing's total; an unchanged record would repeat the previous one.
        """
        with self._lock:
            if not self._changed:
                return []
            self._changed = False
            return [self._record_locked()]


__all__ = ["RECORD", "StimulusTally"]
