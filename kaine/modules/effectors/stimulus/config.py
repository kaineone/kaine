# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The ``[stimulus_control]`` section: the switch, the stage and the bounds.

Stimulus control is the entity's act on its own programme: pause and resume
it, move to the next or previous item, make the sound louder or quieter, and
choose among programme channels when the operator configures more than one
(openspec change ``stimulus-control-act``). It is held: off in the shipped
configuration, and off builds nothing, so the run is bit-identical to a build
without it.

The bounds are the change's design values (Table A1 of the paper carries
them): ``min_interval_s`` is the shortest entity time between two accepted
commands (``Delta_sc``), ``seeks_per_awake_hour`` caps ``next`` and
``previous`` (``n_seek``), ``pause_max_s`` releases an entity pause on its own
(``P_max``), and the gain moves in ``gain_step_db`` steps within plus or minus
``gain_max_db`` of the programme level (``G_step``, ``G_max``). The gain bound
cannot be configured above 6 dB, the change's welfare bound on loudness.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Mapping

from kaine.config import require_known_keys

# The stage this build ships. Stage L (the act bar of act-intent-derivation and
# the learned choice of learned-action-selection) needs changes not yet built.
STAGE_MINIMAL = "minimal"
STAGES = (STAGE_MINIMAL,)

PAUSE = "pause"
RESUME = "resume"
NEXT = "next"
PREVIOUS = "previous"
LOUDER = "louder"
QUIETER = "quieter"
CHANNEL_PREFIX = "channel:"
BASE_ACTIONS = (PAUSE, RESUME, NEXT, PREVIOUS, LOUDER, QUIETER)
SEEK_ACTIONS = frozenset({NEXT, PREVIOUS})

# The welfare bound on the programme gain (design D1): the operator may narrow
# it, never widen it.
GAIN_MAX_BOUND_DB = 6.0

_KEYS = {
    "enabled",
    "stage",
    "min_interval_s",
    "seeks_per_awake_hour",
    "pause_max_s",
    "gain_step_db",
    "gain_max_db",
    "channels",
}


class StimulusControlError(RuntimeError):
    """Stimulus control is enabled but cannot be built as configured.

    Raised at boot so the operator learns of it; enabling it never degrades to
    a programme the entity cannot act on while the effector reports success.
    """


def channel_action(index: int) -> str:
    return f"{CHANNEL_PREFIX}{int(index)}"


def parse_channel_action(action: str) -> int | None:
    """The channel index named by ``channel:<k>``, or None for any other action."""
    if not action.startswith(CHANNEL_PREFIX):
        return None
    tail = action[len(CHANNEL_PREFIX):]
    if not tail.isdigit():
        return None
    return int(tail)


def _positive(name: str, value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"[stimulus_control].{name} must be a number")
    v = float(value)
    if not math.isfinite(v) or v <= 0.0:
        raise ValueError(f"[stimulus_control].{name} must be finite and > 0")
    return v


@dataclass(frozen=True)
class StimulusControlConfig:
    enabled: bool = False
    stage: str = STAGE_MINIMAL
    min_interval_s: float = 30.0
    seeks_per_awake_hour: int = 20
    pause_max_s: float = 120.0
    gain_step_db: float = 2.0
    gain_max_db: float = 6.0
    # Further programme channels, as manifest paths. Channel 0 is always
    # [perception_feed].playlist_manifest; an empty list is one channel.
    channels: tuple[str, ...] = field(default_factory=tuple)

    @classmethod
    def from_section(cls, section: Mapping[str, Any] | None) -> "StimulusControlConfig":
        data = {k: v for k, v in dict(section or {}).items() if not str(k).startswith("_")}
        require_known_keys(data, _KEYS, "[stimulus_control]")
        enabled = data.get("enabled", False)
        if not isinstance(enabled, bool):
            raise ValueError("[stimulus_control].enabled must be a bool")
        stage = data.get("stage", STAGE_MINIMAL)
        if stage not in STAGES:
            raise ValueError(
                f"[stimulus_control].stage must be one of {list(STAGES)}; "
                "the learned stage needs act-intent-derivation, drive-reduction-learning "
                "and learned-action-selection, which are not built"
            )
        seeks = data.get("seeks_per_awake_hour", 20)
        if isinstance(seeks, bool) or not isinstance(seeks, int) or seeks < 0:
            raise ValueError("[stimulus_control].seeks_per_awake_hour must be an int >= 0")
        gain_step = _positive("gain_step_db", data.get("gain_step_db", 2.0))
        gain_max = _positive("gain_max_db", data.get("gain_max_db", 6.0))
        if gain_max > GAIN_MAX_BOUND_DB:
            raise ValueError(
                f"[stimulus_control].gain_max_db must be <= {GAIN_MAX_BOUND_DB} (the welfare bound)"
            )
        if gain_step > gain_max:
            raise ValueError("[stimulus_control].gain_step_db must be <= gain_max_db")
        channels = data.get("channels", [])
        if not isinstance(channels, list) or not all(
            isinstance(c, str) and c.strip() for c in channels
        ):
            raise ValueError("[stimulus_control].channels must be a list of manifest paths")
        return cls(
            enabled=enabled,
            stage=stage,
            min_interval_s=_positive("min_interval_s", data.get("min_interval_s", 30.0)),
            seeks_per_awake_hour=int(seeks),
            pause_max_s=_positive("pause_max_s", data.get("pause_max_s", 120.0)),
            gain_step_db=gain_step,
            gain_max_db=gain_max,
            channels=tuple(c.strip() for c in channels),
        )

    @property
    def channel_count(self) -> int:
        return 1 + len(self.channels)

    def declared_actions(self) -> tuple[str, ...]:
        """The effector's declared action set: channels only when there are two or more."""
        if self.channel_count < 2:
            return BASE_ACTIONS
        return BASE_ACTIONS + tuple(channel_action(k) for k in range(self.channel_count))

    def descriptor(self) -> dict[str, Any]:
        """The run-manifest record: the switch, the stage and every bound (no paths)."""
        return {
            "enabled": self.enabled,
            "stage": self.stage,
            "min_interval_s": self.min_interval_s,
            "seeks_per_awake_hour": self.seeks_per_awake_hour,
            "pause_max_s": self.pause_max_s,
            "gain_step_db": self.gain_step_db,
            "gain_max_db": self.gain_max_db,
            "channel_count": self.channel_count,
            "declared_actions": list(self.declared_actions()),
        }


def is_workspace_mediation_study(study: str | None) -> bool:
    """The workspace-mediation arms compare processors on one shared programme."""
    return bool(study) and str(study).startswith("workspace_mediation")


def refuse_in_mediation_arm(study: str | None, config: StimulusControlConfig) -> str | None:
    """The boot refusal for a workspace-mediation arm that enables stimulus control."""
    if config.enabled and is_workspace_mediation_study(study):
        return (
            f"study {study!r} is a workspace-mediation arm, which shares one programme "
            "across arms; [stimulus_control].enabled must be false"
        )
    return None


__all__ = [
    "BASE_ACTIONS",
    "CHANNEL_PREFIX",
    "GAIN_MAX_BOUND_DB",
    "LOUDER",
    "NEXT",
    "PAUSE",
    "PREVIOUS",
    "QUIETER",
    "RESUME",
    "SEEK_ACTIONS",
    "STAGE_MINIMAL",
    "StimulusControlConfig",
    "StimulusControlError",
    "channel_action",
    "is_workspace_mediation_study",
    "parse_channel_action",
    "refuse_in_mediation_arm",
]
