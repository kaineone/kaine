# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The Empatheia factory."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass
from kaine.boot.errors import _require_keys
from kaine.bus.client import AsyncBus
from kaine.modules.base import BaseModule


def make_empatheia(bus: AsyncBus, section: dict[str, Any]) -> BaseModule:
    from kaine.modules.empatheia.module import Empatheia

    # Spot-injected shared embedder; never a TOML key, so pop before validation.
    embedder = section.pop("_embedder", None)

    allowed = {
        "backend",
        "collection",
        "speaker_label",
        "operator_sources",
        "deviation_threshold",
        "baseline_salience",
        "alert_salience",
        "qdrant",  # nested sub-table: host, port, api_key
    }
    _require_keys(section, allowed)
    qdrant = section.get("qdrant") or {}
    kwargs: dict[str, Any] = {k: section[k] for k in allowed - {"qdrant"} if k in section}
    if "operator_sources" in kwargs:
        ops = kwargs["operator_sources"]
        if not isinstance(ops, list) or not all(isinstance(x, str) for x in ops):
            raise ValueError("empatheia.operator_sources must be a list of strings")
    if "host" in qdrant:
        kwargs["qdrant_host"] = qdrant["host"]
    if "port" in qdrant:
        kwargs["qdrant_port"] = qdrant["port"]
    if "api_key" in qdrant:
        kwargs["qdrant_api_key"] = qdrant["api_key"]
    kwargs["embedder"] = embedder
    return Empatheia(bus, **kwargs)
