# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""Device-assignment logging and the metrics collector."""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass
from kaine.boot.common import _effective_hot_swap_mode
from kaine.modules.registry import ModuleRegistry
from kaine.shared_services import is_shared
from kaine.text_embedding import (
    resolve_embedding_config,
)

log = logging.getLogger(__name__)


def _log_device_assignments(registry: ModuleRegistry, kaine_config: dict[str, Any]) -> None:
    """One-line-per-module log of which compute device each pinned
    module landed on. Reads the resolved config rather than reaching
    into the constructed modules so this stays cheap and never raises.
    """
    rows: list[tuple[str, str]] = []
    if "topos" in registry:
        rows.append(
            (
                "topos.encoder",
                str((kaine_config.get("topos") or {}).get("device", "auto")),
            )
        )
    if any(m in registry for m in ("mnemos", "empatheia", "hypnos")):
        cfg = resolve_embedding_config(kaine_config)
        if cfg["backend"] == "sentence_transformers":
            value = f"{cfg['backend']}:{cfg['device']}"
        else:
            value = "numpy:cpu"
        rows.append(("embedding", value))
    if "audition" in registry:
        rows.append(
            (
                "audition.emotion",
                str((kaine_config.get("audition") or {}).get("emotion_device", "cpu")),
            )
        )
    if "chronos" in registry:
        rows.append(("chronos.network", "cpu (pinned)"))
    if "hypnos" in registry:
        va = (kaine_config.get("hypnos") or {}).get("voice_alignment") or {}
        rows.append(("hypnos.voice_alignment", str(va.get("training_device", "cuda:0"))))
        raw_hot_swap = str(va.get("hot_swap_mode", "manual"))
        effective_hot_swap = _effective_hot_swap_mode(raw_hot_swap, kaine_config)
        shared_server = (
            kaine_config is not None and is_shared(kaine_config, "model_server")
        )
        display_hot_swap = (
            f"{effective_hot_swap} (model server is shared)"
            if shared_server
            else effective_hot_swap
        )
        rows.append(
            (
                "hypnos.voice_alignment.hot_swap",
                display_hot_swap,
            )
        )
    if not rows:
        return
    log.info("device assignment summary:")
    for module_name, device in rows:
        log.info("  device assignment: %s → %s", module_name, device)


class MetricsCollector:
    """Live cycle metrics for Nexus diagnostics.

    Snapshot is read at request time so the JSON endpoint always
    returns current values.
    """

    def __init__(self, cycle: Any, registry: ModuleRegistry) -> None:
        self._cycle = cycle
        self._registry = registry

    def snapshot(self) -> dict[str, Any]:
        cycle = self._cycle
        return {
            "tick_index": getattr(cycle, "tick_index", 0),
            "processing_rate_hz": getattr(cycle, "processing_rate_hz", 0.0),
            "experiential_rate_hz": getattr(cycle, "experiential_rate_hz", 0.0),
            "error_counts": dict(getattr(cycle, "error_counts", {}) or {}),
            "modules": sorted(name for name in self._iter_module_names()),
        }

    def _iter_module_names(self):
        try:
            for module in self._registry.all_modules():
                yield module.name
        except Exception:
            return
