# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

from __future__ import annotations

from typing import Any, Callable, Mapping, Protocol, runtime_checkable

from kaine.bus.schema import Event


def _clamp01(x: float) -> float:
    if x < 0.0:
        return 0.0
    if x > 1.0:
        return 1.0
    return x


@runtime_checkable
class SalienceStrategy(Protocol):
    async def score(self, event: Event, context: dict[str, Any]) -> float:
        ...


@runtime_checkable
class GoalScorer(Protocol):
    async def relevance(self, event: Event) -> float:
        ...


@runtime_checkable
class ThymosModulator(Protocol):
    async def modulate(self, event: Event) -> float:
        ...


class StaticGoalScorer:
    """Dev-only fallback / negative-control goal scorer.

    Returns the same value for every event, so the product-form salience score
    collapses to ``intensity × novelty × <constant>``. It is NOT the default in
    the live cycle (the real :class:`DriveRelevanceGoalScorer` is selectable via
    ``[syneidesis].salience_goal_factor``); it is retained as the runnable
    two-factor negative control and as a fixed-value seam for crafted tests.
    """

    def __init__(self, default: float = 1.0) -> None:
        if not 0.0 <= default <= 1.0:
            raise ValueError("default must be in [0, 1]")
        self._default = default

    async def relevance(self, event: Event) -> float:
        return self._default


class StaticThymosModulator:
    """Dev-only fallback / negative-control Thymos modulator.

    Returns a constant, bypassing affect-weighting. NOT the live default — the
    real :class:`kaine.modules.thymos.modulator.StateModulator` is wired in by
    default (``[syneidesis].salience_thymos_factor``); this stays as the runnable
    unweighted negative control and a fixed-value seam for crafted tests.
    """

    def __init__(self, default: float = 1.0) -> None:
        if not 0.0 <= default <= 1.0:
            raise ValueError("default must be in [0, 1]")
        self._default = default

    async def modulate(self, event: Event) -> float:
        return self._default


# ENGINEERING EXTENSION (paper §3.4.3). The paper grounds goals as "preferred
# interoceptive states" entering appraisal but does NOT fully specify the goal
# function that weights salience. Grounding it in the four Thymos drives that
# the architecture already accumulates and broadcasts, this table maps each
# drive to the event SOURCES whose arrival tends to relieve it — the operational
# stand-in for "an event relevant to the currently-dominant drive". The mapping
# is a defensible first choice, not a claim from the paper; keep it labeled as
# such and do not overstate it. Sources are canonical module names.
_DRIVE_RELEVANT_SOURCES: dict[str, frozenset[str]] = {
    # Curiosity is relieved by novel exteroceptive / perceptual input.
    "curiosity": frozenset({"perception", "topos", "audition", "mundus", "mnemos"}),
    # Boredom is relieved by any stimulating activity, incl. internal cognition.
    "boredom": frozenset(
        {"perception", "topos", "audition", "mundus", "mnemos", "nous", "phantasia", "lingua"}
    ),
    # Social drive is relieved by social interaction.
    "social_drive": frozenset({"audition", "empatheia", "vox", "lingua", "chronos"}),
    # Restlessness is relieved by motor / effector action.
    "restlessness": frozenset({"praxis", "volition", "vox", "mundus"}),
}


class DriveRelevanceGoalScorer:
    """Goal factor: weight an event by its relevance to the dominant drive.

    ENGINEERING EXTENSION (paper §3.4.3) — see ``_DRIVE_RELEVANT_SOURCES``. The
    entity's current drive levels are injected via ``drive_getter`` (dependency
    injection, so this workspace-layer strategy never imports ``kaine.modules``).
    Each score is the last-known dominant drive attenuating events that do NOT
    serve it, leaving serving events (and the neutral no-drive case) at 1.0:

        factor = 1 - dominant_value × (1 - relevance) × attenuation

    with ``relevance`` = 1.0 for a serving source else 0.0. The factor is bounded
    to ``[1 - attenuation, 1.0] ⊆ [0, 1]`` (a multiplier "around 1.0"): the goal
    factor biases selection toward drive-relevant events without dominating the
    intensity/novelty terms, and clamps cleanly into the product form.

    Pure: a function of the event and the injected drive snapshot only — no
    wall-clock, no RNG — preserving the deterministic-cycle guarantee.
    """

    def __init__(
        self,
        drive_getter: Callable[[], Mapping[str, float]],
        *,
        attenuation: float = 0.5,
    ) -> None:
        if not 0.0 <= attenuation <= 1.0:
            raise ValueError("attenuation must be in [0, 1]")
        self._drive_getter = drive_getter
        self._attenuation = float(attenuation)

    async def relevance(self, event: Event) -> float:
        drives = self._drive_getter()
        if not drives:
            return 1.0
        # Deterministic dominant-drive pick: highest value, ties broken by name
        # (independent of dict insertion order).
        dominant_name, dominant_value = max(
            drives.items(), key=lambda item: (item[1], item[0])
        )
        if dominant_value <= 0.0:
            return 1.0
        serving = _DRIVE_RELEVANT_SOURCES.get(dominant_name, frozenset())
        relevance = 1.0 if event.source in serving else 0.0
        return _clamp01(1.0 - dominant_value * (1.0 - relevance) * self._attenuation)
