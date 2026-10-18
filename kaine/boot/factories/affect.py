# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The affect module factory."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    pass
from kaine.boot.config_kwargs import config_kwargs
from kaine.boot.errors import ConfigurationError, _require_keys, _warn_retired_keys
from kaine.bus.client import AsyncBus
from kaine.entity_clock import EntityClock
from kaine.modules.base import BaseModule


def make_affect(
    bus: AsyncBus,
    section: dict[str, Any],
    *,
    entity_clock: Optional[EntityClock] = None,
) -> BaseModule:
    from kaine.modules.affect.coupling import CouplingConfig
    from kaine.modules.affect.drives import DriveSet
    from kaine.modules.affect.module import Affect
    from kaine.modules.affect.regulation import (
        PassiveDecay,
        RegulationConfig,
        RegulationPolicy,
        ThreeTierRegulation,
    )
    from kaine.modules.affect.state import DimensionalState

    allowed = {
        "baseline_valence",
        "baseline_arousal",
        "baseline_dominance",
        "drift_rate_per_s",
        "publish_interval_s",
        "baseline_salience",
        "alert_salience",
        "interoception_stream",
        "sequence_stream",
        "episodic_memory_stream",
        "action_selection_stream",
        "fast_time_constant_s",
        "slow_time_constant_s",
        "learning_progress_floor",
        "alert_excess_margin",
        "intent_rate_weight",
        "valence_time_constant_s",
        "valence_progress_gain",
        "valence_rule",
        "goal_stall_s",
        "goal_cap",
        "goal_response_window_s",
        "goal_likelihood_fall",
        "drive_arousal_gain",
        "boredom_engagement_relief",
        "concern_reentry_s",
        "drives",  # nested per-drive sub-tables, consumed by DriveSet default
        "coupling",  # nested [affect.coupling] sub-table
        "regulation",  # nested [affect.regulation] sub-table
    }
    # Retired keys: accepted so old operator files boot, ignored with a warning.
    retired = {"social_drive_time_scale_s"}
    _require_keys(section, allowed | retired)
    _warn_retired_keys(section, retired, "[affect]")
    baseline = DimensionalState(
        valence=float(section.get("baseline_valence", 0.0)),
        arousal=float(section.get("baseline_arousal", 0.3)),
        dominance=float(section.get("baseline_dominance", 0.0)),
    )
    kwargs: dict[str, Any] = {"baseline": baseline}
    kwargs.update(
        config_kwargs(
            section,
            (
                "drift_rate_per_s",
                "publish_interval_s",
                "baseline_salience",
                "alert_salience",
                "interoception_stream",
                "sequence_stream",
                "episodic_memory_stream",
                "action_selection_stream",
                "fast_time_constant_s",
                "slow_time_constant_s",
                "learning_progress_floor",
                "alert_excess_margin",
                "intent_rate_weight",
                "valence_time_constant_s",
                "valence_progress_gain",
                "valence_rule",
                "goal_stall_s",
                "goal_cap",
                "goal_response_window_s",
                "goal_likelihood_fall",
                "drive_arousal_gain",
                "boredom_engagement_relief",
                "concern_reentry_s",
            ),
            Affect,
        )
    )
    # Build DriveSet from the optional [affect.drives] sub-tables.
    drives_section = section.get("drives")
    try:
        drives = DriveSet.from_config(drives_section)
    except ValueError as exc:
        raise ConfigurationError(f"Invalid [affect.drives] configuration: {exc}") from exc
    kwargs["drives"] = drives

    # Build CouplingConfig from the optional [affect.coupling] sub-table.
    coupling_section = section.get("coupling") or {}
    coupling_allowed = {
        "enabled",
        "coupling_base",
        "coupling_familiarity_gain",
        "coupling_ceiling",
        "decay_s",
    }
    # Retired: coupling_max_rate_per_s backed the removed DriftSafeguard
    # (thymos-emergent-affect-coupling).
    coupling_ignored = {"coupling_max_rate_per_s"}
    _require_keys(coupling_section, coupling_allowed | coupling_ignored)
    _warn_retired_keys(coupling_section, coupling_ignored, "[affect.coupling]")
    coupling_kwargs = config_kwargs(coupling_section, coupling_allowed, CouplingConfig)
    kwargs["coupling"] = CouplingConfig(**coupling_kwargs)

    # Build the regulation policy from the optional [affect.regulation] sub-table.
    regulation_section = section.get("regulation") or {}
    regulation_allowed = {
        "policy",
        "set_point",
        "selection_bias",
        "bias_decay_s",
        "sustain_window_s",
    }
    _require_keys(regulation_section, regulation_allowed)
    policy_name = regulation_section.get("policy", "three_tier")
    if policy_name == "passive":
        policy: RegulationPolicy = PassiveDecay()
    elif policy_name == "three_tier":
        reg_config_kwargs = config_kwargs(
            regulation_section,
            (
                "set_point",
                "selection_bias",
                "bias_decay_s",
                "sustain_window_s",
            ),
            RegulationConfig,
        )
        try:
            config = RegulationConfig(**reg_config_kwargs)
        except ValueError as exc:
            raise ConfigurationError(
                f"Invalid [affect.regulation] configuration: {exc}"
            ) from exc
        policy = ThreeTierRegulation(config)
    else:
        raise ConfigurationError(
            '[affect.regulation].policy must be "three_tier" or "passive"'
        )
    kwargs["regulation"] = policy

    return Affect(bus, entity_clock=entity_clock, **kwargs)
