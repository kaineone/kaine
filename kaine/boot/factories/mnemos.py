# SPDX-License-Identifier: LicenseRef-CAL-0.4
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The Mnemos factory."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    pass
from kaine.boot.errors import ConfigurationError, _require_keys
from kaine.bus.client import AsyncBus
from kaine.entity_clock import EntityClock
from kaine.modules.base import BaseModule


def make_mnemos(
    bus: AsyncBus,
    section: dict[str, Any],
    *,
    entity_clock: Optional[EntityClock] = None,
) -> BaseModule:
    from kaine.modules.mnemos.module import Mnemos

    # Spot-injected shared embedder and N_day (traces per entity day); never
    # TOML keys, so pop before validation.
    embedder = section.pop("_embedder", None)
    traces_per_day = section.pop("_traces_per_day", None)

    allowed = {
        "backend",
        "collection_prefix",
        "short_term_capacity",
        "recall_top_k",
        "baseline_salience",
        "alert_salience",
        "recall_on_workspace",
        "recall_cooldown_s",
        "storage_budget_bytes",  # operator's persisted memory budget in bytes
        "qdrant",
        "replay",  # nested sub-table: selection_top_k, affect_weight, recency_weight, redact_content, cross_period_candidates
        "strength",  # nested sub-table: retention_per_day, prune_floor
    }
    if "embedder_model_id" in section:
        raise ConfigurationError(
            "[mnemos].embedder_model_id is replaced by [embedding].model_id"
        )
    if "device" in section:
        raise ConfigurationError("[mnemos].device is replaced by [embedding].device")
    _require_keys(section, allowed)
    qdrant = section.get("qdrant") or {}
    replay = section.get("replay") or {}
    strength = section.get("strength") or {}
    kwargs: dict[str, Any] = {
        k: section[k]
        for k in allowed - {"qdrant", "replay", "strength"}
        if k in section
    }
    if "storage_budget_bytes" in kwargs:
        value = kwargs["storage_budget_bytes"]
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ConfigurationError(
                "[mnemos].storage_budget_bytes must be a positive integer number of bytes"
            )
        kwargs["storage_budget_bytes"] = int(value)
    if "host" in qdrant:
        kwargs["qdrant_host"] = qdrant["host"]
    if "port" in qdrant:
        kwargs["qdrant_port"] = qdrant["port"]
    if "api_key" in qdrant:
        kwargs["qdrant_api_key"] = qdrant["api_key"]
    # Replay sub-table
    if "selection_top_k" in replay:
        kwargs["replay_selection_top_k"] = int(replay["selection_top_k"])
    if "affect_weight" in replay:
        kwargs["replay_affect_weight"] = float(replay["affect_weight"])
    if "recency_weight" in replay:
        kwargs["replay_recency_weight"] = float(replay["recency_weight"])
    if "redact_content" in replay:
        kwargs["replay_redact_content"] = bool(replay["redact_content"])
    if "cross_period_candidates" in replay:
        kwargs["cross_period_candidates"] = int(replay["cross_period_candidates"])
    # Strength sub-table (paper A.10)
    _require_keys(strength, {"retention_per_day", "prune_floor"})
    if "retention_per_day" in strength:
        kwargs["strength_retention_per_day"] = float(strength["retention_per_day"])
    if "prune_floor" in strength:
        kwargs["strength_prune_floor"] = float(strength["prune_floor"])
    if traces_per_day is not None:
        kwargs["traces_per_day"] = float(traces_per_day)
    kwargs["embedder"] = embedder
    return Mnemos(bus, entity_clock=entity_clock, **kwargs)
