# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Workspace feedback controller.

Implements the workspace side of the workspace feedback extension.
Three context-conditioned processors publish reports; the workspace
scores coalition candidates and attaches feedback metadata to each
non-inhibited broadcast.

Per-processor gains start at one, stay inside [pi_min, pi_max], and are
moved in equal and opposite steps so the mean of the three gains stays
at one.  Gains relax exponentially back toward one with time constant
gain_relax_s.  A refractory interval after a move for a processor
prevents immediate repeated updates.

Arms:
  - head_only: feedback metadata is broadcast, but gains do not move.
  - head_gain: precision-weighted-error competition moves gain from the
    worst eligible processor to the best eligible processor.
  - full: a conflicting processor loses gain to the most precise other
    eligible processor.
  - matched_random: a conflicting processor triggers a random pair of
    processors to move.

Nothing is attached to inhibited broadcasts.
"""
from __future__ import annotations

import math
import random
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from kaine.bus.schema import Event
from kaine.cycle.types import WorkspaceSnapshot

FEEDBACK_ARMS: tuple[str, ...] = ("off", "head_only", "head_gain", "full", "matched_random")
PROCESSORS: tuple[str, ...] = ("vision", "audition", "interoception")
REPORT_TYPES: dict[str, str] = {
    "vision": "vision.report",
    "audition": "audition.perception",
    "interoception": "interoception.report",
}
SEQUENCE_SOURCE = "sequence"
SEQUENCE_REPORT_TYPE = "sequence.report"
SEQUENCE_PREDICTION_KEY = "predicted_next_feature_vector"
SEQUENCE_PREDICTION_DIM = 24
FEEDBACK_KEY = "workspace_feedback"
ALLOWED_KEYS: frozenset[str] = frozenset({
    "enabled", "arm", "pi_min", "pi_max", "disagreement_threshold",
    "conflict_error_ratio", "gain_step", "gain_relax_s", "refractory_s",
    "head_learning_rate",
})


class FeedbackSettingsError(ValueError):
    """Raised when a [workspace.feedback] configuration section is invalid."""


@dataclass(frozen=True)
class WorkspaceFeedbackSettings:
    """Validated settings for workspace feedback.

    A built settings object is never the "off" arm; "off" and disabled
    configurations return None from from_section.
    """

    arm: str
    pi_min: float = 0.8
    pi_max: float = 1.25
    disagreement_threshold: float = 2.0
    conflict_error_ratio: float = 2.0
    gain_step: float = 0.1
    gain_relax_s: float = 10.0
    refractory_s: float = 10.0
    head_learning_rate: float = 1e-3

    @property
    def head_active(self) -> bool:
        """Head feedback is always reported for a built settings object."""
        return True

    @property
    def gain_active(self) -> bool:
        """Whether the arm is allowed to move processor gains."""
        return self.arm in ("head_gain", "full", "matched_random")

    @property
    def conflict_active(self) -> bool:
        """Whether the arm uses conflict detection to trigger moves."""
        return self.arm in ("full", "matched_random")

    @classmethod
    def from_section(cls, section: Mapping[str, Any] | None) -> WorkspaceFeedbackSettings | None:
        """Build settings from a configuration mapping.

        Returns None for a missing or disabled section.  Raises
        FeedbackSettingsError for unknown keys, bad types, values that are
        not finite numbers, or values that violate the constraints.
        Validation runs even when the section is disabled.
        """
        if section is None:
            return None
        if not isinstance(section, Mapping):
            raise FeedbackSettingsError("workspace.feedback section must be a mapping")

        unknown = [key for key in section if key not in ALLOWED_KEYS]
        if unknown:
            raise FeedbackSettingsError(
                f"workspace.feedback has unknown keys: {', '.join(unknown)}"
            )

        enabled = section.get("enabled", False)
        if not isinstance(enabled, bool):
            raise FeedbackSettingsError(
                f"workspace.feedback enabled must be a bool, got {type(enabled).__name__}"
            )

        arm = section.get("arm", "full")
        arm = str(arm).strip().lower()
        if arm not in FEEDBACK_ARMS:
            raise FeedbackSettingsError(
                f"workspace.feedback arm must be one of {FEEDBACK_ARMS}, got {arm!r}"
            )

        numeric_defaults: dict[str, float] = {
            "pi_min": 0.8,
            "pi_max": 1.25,
            "disagreement_threshold": 2.0,
            "conflict_error_ratio": 2.0,
            "gain_step": 0.1,
            "gain_relax_s": 10.0,
            "refractory_s": 10.0,
            "head_learning_rate": 1e-3,
        }

        def _to_float(name: str, value: Any) -> float:
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise FeedbackSettingsError(f"workspace.feedback {name} must be a number")
            try:
                number = float(value)
            except Exception as exc:
                raise FeedbackSettingsError(
                    f"workspace.feedback {name} must be a number"
                ) from exc
            if not math.isfinite(number):
                raise FeedbackSettingsError(
                    f"workspace.feedback {name} must be a finite number"
                )
            return number

        pi_min = _to_float("pi_min", section.get("pi_min", numeric_defaults["pi_min"]))
        pi_max = _to_float("pi_max", section.get("pi_max", numeric_defaults["pi_max"]))
        disagreement_threshold = _to_float(
            "disagreement_threshold",
            section.get("disagreement_threshold", numeric_defaults["disagreement_threshold"]),
        )
        conflict_error_ratio = _to_float(
            "conflict_error_ratio",
            section.get("conflict_error_ratio", numeric_defaults["conflict_error_ratio"]),
        )
        gain_step = _to_float(
            "gain_step", section.get("gain_step", numeric_defaults["gain_step"])
        )
        gain_relax_s = _to_float(
            "gain_relax_s", section.get("gain_relax_s", numeric_defaults["gain_relax_s"])
        )
        refractory_s = _to_float(
            "refractory_s", section.get("refractory_s", numeric_defaults["refractory_s"])
        )
        head_learning_rate = _to_float(
            "head_learning_rate",
            section.get("head_learning_rate", numeric_defaults["head_learning_rate"]),
        )

        if not (0.0 < pi_min <= 1.0):
            raise FeedbackSettingsError("workspace.feedback pi_min must satisfy 0 < pi_min <= 1")
        if not (pi_max >= 1.0):
            raise FeedbackSettingsError("workspace.feedback pi_max must satisfy pi_max >= 1")
        if disagreement_threshold <= 0.0:
            raise FeedbackSettingsError("workspace.feedback disagreement_threshold must be > 0")
        if conflict_error_ratio <= 0.0:
            raise FeedbackSettingsError("workspace.feedback conflict_error_ratio must be > 0")
        if gain_step <= 0.0:
            raise FeedbackSettingsError("workspace.feedback gain_step must be > 0")
        if gain_relax_s <= 0.0:
            raise FeedbackSettingsError("workspace.feedback gain_relax_s must be > 0")
        if refractory_s < 0.0:
            raise FeedbackSettingsError("workspace.feedback refractory_s must be >= 0")
        if head_learning_rate <= 0.0:
            raise FeedbackSettingsError("workspace.feedback head_learning_rate must be > 0")

        if not enabled or arm == "off":
            return None

        return cls(
            arm=arm,
            pi_min=pi_min,
            pi_max=pi_max,
            disagreement_threshold=disagreement_threshold,
            conflict_error_ratio=conflict_error_ratio,
            gain_step=gain_step,
            gain_relax_s=gain_relax_s,
            refractory_s=refractory_s,
            head_learning_rate=head_learning_rate,
        )


class FeedbackController:
    """Workspace-side state for attaching feedback metadata to broadcasts."""

    def __init__(
        self,
        settings: WorkspaceFeedbackSettings,
        *,
        seed: int | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        if settings.arm == "matched_random" and seed is None:
            raise ValueError("the matched_random feedback arm needs a seed")

        self._settings = settings
        self._rng = (
            random.Random(f"feedback-random:{int(seed)}")
            if settings.arm == "matched_random"
            else None
        )
        self._clock = clock if clock is not None else time.monotonic
        self._gains: dict[str, float] = {processor: 1.0 for processor in PROCESSORS}
        self._last_time: float | None = None
        self._refractory_until: dict[str, float] = {
            processor: -math.inf for processor in PROCESSORS
        }
        self._seen: set[str] = set()
        self._sequence_prediction: tuple[float, ...] | None = None

    @property
    def settings(self) -> WorkspaceFeedbackSettings:
        """The configured feedback settings."""
        return self._settings

    @property
    def arm(self) -> str:
        """The active feedback arm."""
        return self._settings.arm

    @property
    def gains(self) -> dict[str, float]:
        """A copy of the current per-processor gains."""
        return dict(self._gains)

    @property
    def sequence_prediction(self) -> tuple[float, ...] | None:
        """The most recently observed sequence feature vector, if any."""
        return self._sequence_prediction

    def _is_usable_number(self, value: Any) -> bool:
        """Return True for finite ints and floats, excluding bool."""
        return (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(value)
        )

    def observe_candidates(self, events: Sequence[tuple[str, Event]]) -> None:
        """Ingest candidate events for the current tick.

        Records processor reports that have been seen and stores the
        latest valid sequence prediction.
        """
        for _entry_id, event in events:
            source = event.source
            if source in PROCESSORS and event.type == REPORT_TYPES[source]:
                self._seen.add(source)

            if source == SEQUENCE_SOURCE and event.type == SEQUENCE_REPORT_TYPE:
                prediction = event.payload.get(SEQUENCE_PREDICTION_KEY)
                if (
                    isinstance(prediction, (list, tuple))
                    and len(prediction) == SEQUENCE_PREDICTION_DIM
                    and all(self._is_usable_number(value) for value in prediction)
                ):
                    self._sequence_prediction = tuple(float(value) for value in prediction)

    def relax(self, now: float) -> None:
        """Apply exponential relaxation of gains toward one.

        Time is only allowed to run forward; a non-positive delta is
        ignored.
        """
        if self._last_time is None:
            self._last_time = float(now)
            return

        delta = float(now) - self._last_time
        if delta <= 0.0:
            return

        factor = math.exp(-delta / self._settings.gain_relax_s)
        for processor in PROCESSORS:
            self._gains[processor] = 1.0 + (self._gains[processor] - 1.0) * factor
        self._last_time = float(now)

    def _shift(self, up: str, down: str) -> float:
        """Move gain from one processor to another, keeping the mean at one.

        The step is clipped by pi_max for the receiver, pi_min for the
        giver, and the configured gain_step.
        """
        delta = min(
            self._settings.gain_step,
            self._settings.pi_max - self._gains[up],
            self._gains[down] - self._settings.pi_min,
        )
        delta = max(0.0, delta)
        self._gains[up] += delta
        self._gains[down] -= delta
        return delta

    def on_broadcast(
        self, snapshot: WorkspaceSnapshot, now: float | None = None
    ) -> dict[str, Any] | None:
        """Produce feedback metadata for a workspace broadcast.

        Returns None for inhibited broadcasts.  Otherwise updates gains
        (depending on the arm), records episodes, and returns the
        metadata dict attached to the broadcast.
        """
        now = self._clock() if now is None else float(now)
        self.relax(now)

        if snapshot.inhibited:
            return None

        threshold = snapshot.metadata.get("access_threshold")
        accessed: dict[str, Event] = {}
        for entry_id, event in snapshot.selected_events:
            if event.source not in PROCESSORS:
                continue
            if event.type != REPORT_TYPES[event.source]:
                continue
            if event.source in accessed:
                continue

            score = snapshot.salience_scores.get(entry_id, event.salience)
            if threshold is None or score >= threshold:
                accessed[event.source] = event

        eligible: dict[str, dict[str, Any]] = {}
        for processor in PROCESSORS:
            event = accessed.get(processor)
            if event is None:
                continue

            feedback = event.payload.get(FEEDBACK_KEY)
            if not isinstance(feedback, dict):
                continue

            ratio = feedback.get("error_ratio")
            disagreement = feedback.get("disagreement")
            reported_gain = feedback.get("gain")

            if not self._is_usable_number(ratio) or ratio < 0.0:
                continue

            gain = (
                float(reported_gain)
                if self._is_usable_number(reported_gain)
                else self._gains[processor]
            )
            eligible[processor] = {
                "pwe": gain * float(ratio),
                "ratio": float(ratio),
                "disagreement": (
                    float(disagreement)
                    if self._is_usable_number(disagreement)
                    else None
                ),
                "gain": gain,
            }

        episodes: list[dict[str, Any]] = []

        if self._settings.gain_active:
            eligible_sources = [p for p in PROCESSORS if p in eligible]

            if self._settings.arm == "head_gain":
                if len(eligible_sources) >= 2:
                    winner = min(eligible_sources, key=lambda p: eligible[p]["pwe"])
                    loser = max(eligible_sources, key=lambda p: eligible[p]["pwe"])
                    if winner != loser and now >= self._refractory_until[loser]:
                        delta = self._shift(winner, loser)
                        self._refractory_until[loser] = now + self._settings.refractory_s
                        episodes.append(
                            {
                                "kind": "precision",
                                "conflicting": None,
                                "toward": winner,
                                "away": loser,
                                "delta": delta,
                            }
                        )

            elif self._settings.arm in ("full", "matched_random"):
                for j in eligible_sources:
                    info = eligible[j]
                    if (
                        info["disagreement"] is not None
                        and info["disagreement"] >= self._settings.disagreement_threshold
                        and info["ratio"] >= self._settings.conflict_error_ratio
                        and now >= self._refractory_until[j]
                    ):
                        self._refractory_until[j] = now + self._settings.refractory_s
                        others = [p for p in eligible_sources if p != j]
                        if not others:
                            episodes.append(
                                {
                                    "kind": "conflict",
                                    "conflicting": j,
                                    "toward": None,
                                    "away": None,
                                    "delta": 0.0,
                                }
                            )
                            continue

                        if self._settings.arm == "full":
                            winner = min(others, key=lambda p: eligible[p]["pwe"])
                            delta = self._shift(winner, j)
                            episodes.append(
                                {
                                    "kind": "conflict",
                                    "conflicting": j,
                                    "toward": winner,
                                    "away": j,
                                    "delta": delta,
                                }
                            )
                        else:  # matched_random
                            pool = (
                                sorted(self._seen)
                                if len(self._seen) >= 2
                                else list(PROCESSORS)
                            )
                            toward, away = self._rng.sample(pool, 2)
                            delta = self._shift(toward, away)
                            episodes.append(
                                {
                                    "kind": "random",
                                    "conflicting": j,
                                    "toward": toward,
                                    "away": away,
                                    "delta": delta,
                                }
                            )

        return {
            "arm": self._settings.arm,
            "gains": dict(self._gains),
            "sequence_prediction": (
                list(self._sequence_prediction)
                if self._sequence_prediction is not None
                else None
            ),
            "episodes": episodes,
        }
