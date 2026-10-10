# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The Thymos factory."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    pass
from kaine.boot.errors import ConfigurationError, _require_keys
from kaine.bus.client import AsyncBus
from kaine.entity_clock import EntityClock
from kaine.modules.base import BaseModule


def make_thymos(
    bus: AsyncBus,
    section: dict[str, Any],
    *,
    entity_clock: Optional[EntityClock] = None,
) -> BaseModule:
    from kaine.modules.thymos.coupling import CouplingConfig
    from kaine.modules.thymos.drives import DriveSet
    from kaine.modules.thymos.module import Thymos
    from kaine.modules.thymos.state import DimensionalState

    allowed = {
        "baseline_valence",
        "baseline_arousal",
        "baseline_dominance",
        "drift_rate_per_s",
        "publish_interval_s",
        "baseline_salience",
        "alert_salience",
        "soma_stream",
        "chronos_stream",
        "mnemos_stream",
        "social_drive_time_scale_s",
        "volition_stream",
        "fast_time_constant_s",
        "slow_time_constant_s",
        "learning_progress_floor",
        "alert_excess_margin",
        "intent_rate_weight",
        "valence_time_constant_s",
        "valence_progress_gain",
        "drives",  # nested per-drive sub-tables, consumed by DriveSet default
        "coupling",  # nested [thymos.coupling] sub-table
    }
    _require_keys(section, allowed)
    baseline = DimensionalState(
        valence=float(section.get("baseline_valence", 0.0)),
        arousal=float(section.get("baseline_arousal", 0.3)),
        dominance=float(section.get("baseline_dominance", 0.0)),
    )
    kwargs: dict[str, Any] = {"baseline": baseline}
    for k in (
        "drift_rate_per_s",
        "publish_interval_s",
        "baseline_salience",
        "alert_salience",
        "soma_stream",
        "chronos_stream",
        "mnemos_stream",
        "social_drive_time_scale_s",
        "volition_stream",
        "fast_time_constant_s",
        "slow_time_constant_s",
        "learning_progress_floor",
        "alert_excess_margin",
        "intent_rate_weight",
        "valence_time_constant_s",
        "valence_progress_gain",
    ):
        if k in section:
            kwargs[k] = section[k]
    # Build DriveSet from the optional [thymos.drives] sub-tables.
    drives_section = section.get("drives")
    try:
        drives = DriveSet.from_config(drives_section)
    except ValueError as exc:
        raise ConfigurationError(f"Invalid [thymos.drives] configuration: {exc}") from exc
    kwargs["drives"] = drives

    # Build CouplingConfig from the optional [thymos.coupling] sub-table.
    coupling_section = section.get("coupling") or {}
    coupling_allowed = {
        "enabled",
        "coupling_base",
        "coupling_familiarity_gain",
        "coupling_ceiling",
        "decay_s",
    }
    # Tolerate (ignore) the legacy ``coupling_max_rate_per_s`` key: it backed the
    # removed DriftSafeguard (thymos-emergent-affect-coupling). Existing local
    # configs that still carry it must not fail to boot.
    coupling_ignored = {"coupling_max_rate_per_s"}
    _require_keys(coupling_section, coupling_allowed | coupling_ignored)
    coupling_kwargs: dict[str, Any] = {}
    for k in coupling_allowed:
        if k in coupling_section:
            coupling_kwargs[k] = coupling_section[k]
    kwargs["coupling"] = CouplingConfig(**coupling_kwargs)
    return Thymos(bus, entity_clock=entity_clock, **kwargs)
