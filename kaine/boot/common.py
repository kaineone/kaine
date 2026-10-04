# SPDX-License-Identifier: LicenseRef-CAL-0.2
# Copyright (c) 2026 Kaine.One <kaine.one@tuta.com>

"""The factory signature and helpers that every factory shares."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable, Mapping, Optional

if TYPE_CHECKING:
    pass
from kaine.boot.errors import ConfigurationError
from kaine.bus.client import AsyncBus
from kaine.modules.base import BaseModule
from kaine.modules.registry import ModuleRegistry
from kaine.shared_services import is_shared
from kaine.text_embedding import (
    SharedEmbedder,
    make_text_embedder,
)

ModuleFactory = Callable[[AsyncBus, dict[str, Any]], Optional[BaseModule]]


def shared_embedder(
    registry: ModuleRegistry, kaine_config: dict[str, Any]
) -> SharedEmbedder:
    """Return the registry-wide shared embedder, creating it on first need.

    Public so the evaluation sidecar and any cycle entrypoint can build the
    shared instance from ``[embedding]`` even when memory/social modules are
    disabled.
    """
    existing: SharedEmbedder | None = getattr(registry, "shared_embedder", None)
    if existing is not None:
        return existing
    shared = SharedEmbedder(make_text_embedder(kaine_config))
    registry.shared_embedder = shared
    return shared


def _check_injections(
    module: str, injections: Optional[Mapping[str, Any]], allowed: set[str]
) -> dict[str, Any]:
    """Return the injections for ``module`` after checking every key is a seam
    its constructor accepts (defence in depth: the plugin loader also checks)."""
    out = dict(injections or {})
    unknown = sorted(set(out) - allowed)
    if unknown:
        raise ConfigurationError(
            f"{module} does not accept injection(s) {', '.join(unknown)}"
        )
    return out


def _effective_hot_swap_mode(voice_mode: str, kaine_config: dict[str, Any] | None) -> str:
    """Return the hot-swap mode that is safe for the configured services.

    When the model server is a shared external service, KAINE must not unload,
    restart or reload it, so any automatic hot-swap mode is forced to ``manual``.
    """
    if (
        kaine_config is not None
        and is_shared(kaine_config, "model_server")
        and voice_mode != "manual"
    ):
        return "manual"
    return voice_mode
