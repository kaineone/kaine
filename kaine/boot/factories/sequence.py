# SPDX-License-Identifier: LicenseRef-CAL-0.5
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The sequence module factory."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Mapping, Optional

if TYPE_CHECKING:
    pass
from kaine.boot.common import _check_injections
from kaine.boot.errors import ConfigurationError, _require_keys
from kaine.boot.feedback import FEEDBACK_SECTION_KEY, feedback_settings
from kaine.bus.client import AsyncBus
from kaine.entity_clock import EntityClock
from kaine.modules.base import BaseModule


def make_sequence(
    bus: AsyncBus,
    section: dict[str, Any],
    *,
    entity_clock: Optional[EntityClock] = None,
    injections: Optional[Mapping[str, Any]] = None,
) -> BaseModule:
    from kaine.modules.sequence.module import Sequence

    section = dict(section)
    feedback_table = section.pop(FEEDBACK_SECTION_KEY, None)

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
                "[sequence].interaction_event_types must be a list of event types"
            )
        kwargs["interaction_event_types"] = tuple(str(t) for t in types)

    if feedback_settings(feedback_table) is not None:
        kwargs["publish_next_prediction"] = True

    kwargs.update(_check_injections("sequence", injections, {"network"}))
    return Sequence(bus, entity_clock=entity_clock, **kwargs)
