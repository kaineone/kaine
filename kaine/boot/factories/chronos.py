# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The Chronos factory."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Mapping, Optional

if TYPE_CHECKING:
    pass
from kaine.boot.common import _check_injections
from kaine.boot.errors import ConfigurationError, _require_keys
from kaine.bus.client import AsyncBus
from kaine.entity_clock import EntityClock
from kaine.modules.base import BaseModule


def make_chronos(
    bus: AsyncBus,
    section: dict[str, Any],
    *,
    entity_clock: Optional[EntityClock] = None,
    injections: Optional[Mapping[str, Any]] = None,
) -> BaseModule:
    from kaine.modules.chronos.module import Chronos

    allowed = {
        "cfc_units",
        "cfc_backend",
        "baseline_salience",
        "alert_salience",
        "anomaly_window",  # consumed by the anomaly detector default
        "anomaly_alert_threshold",
        "rumination_window",
        "rumination_threshold",
        "rumination_bucket_resolution",
        "user_input_streams",
        "interaction_event_types",
        "forward_prediction",
        "prediction_error_window",
    }
    _require_keys(section, allowed)
    kwargs = {
        k: section[k]
        for k in (
            "cfc_units",
            "cfc_backend",
            "baseline_salience",
            "alert_salience",
            "anomaly_alert_threshold",
            "anomaly_window",
            "rumination_window",
            "rumination_threshold",
            "rumination_bucket_resolution",
            "user_input_streams",
            "interaction_event_types",
            "forward_prediction",
            "prediction_error_window",
        )
        if k in section
    }
    if "interaction_event_types" in kwargs:
        types = kwargs["interaction_event_types"]
        if isinstance(types, str) or not isinstance(types, (list, tuple)):
            raise ConfigurationError(
                "[chronos].interaction_event_types must be a list of event types"
            )
        kwargs["interaction_event_types"] = tuple(str(t) for t in types)
    kwargs.update(_check_injections("chronos", injections, {"network"}))
    return Chronos(bus, entity_clock=entity_clock, **kwargs)
